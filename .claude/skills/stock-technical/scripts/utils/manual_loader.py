"""Manual file loader with staleness check (Guardrail 2).

Loader wrapper for user-maintained yaml inputs (margin_debt, banking_npl,
re_presale, catalyst_manual, lai_manual_flags, lai_overrides,
sector_valuation_overrides, re_rnav_manual, portfolio, watchlist).

Returns standardized dict so downstream layers know to degrade behavior
when manual input is stale or missing — never silently fallback to
heuristic guess.
"""
from __future__ import annotations

import os
from datetime import datetime, date
from pathlib import Path
from typing import Any

import yaml

# Staleness threshold per file type (days)
STALE_DAYS: dict[str, int] = {
    "catalyst_manual":            14,
    "banking_npl":                90,
    "re_presale":                 90,
    "re_rnav_manual":             90,
    "margin_debt":                30,
    "lai_manual_flags":           30,
    "sector_valuation_overrides": 90,
    "portfolio":                  7,
    "watchlist":                  30,
}

# Effect string when stale — downstream layers read this for behavior gate
DEGRADATION_EFFECT: dict[str, str] = {
    "catalyst_manual":            "tier_downgrade_1_step",
    "banking_npl":                "tier1_blocked_banking",
    "re_presale":                 "tier1_blocked_real_estate",
    "re_rnav_manual":             "re_valuation_primary_unavailable",
    "margin_debt":                "nav_cap_capped_neutral",
    "lai_manual_flags":           "manual_symptoms_3_5_ignored",
    "sector_valuation_overrides": "use_basket_with_sample_warning",
    "portfolio":                  "stale_portfolio_warning",
    "watchlist":                  "stale_watchlist_warning",
}


def _read_yaml(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _file_age_days(path: Path) -> int:
    mtime = datetime.fromtimestamp(path.stat().st_mtime)
    return (datetime.now() - mtime).days


def _parse_last_updated(data: dict[str, Any]) -> int | None:
    """If yaml carries `last_updated: YYYY-MM-DD`, prefer that over mtime."""
    raw = data.get("last_updated")
    if raw is None:
        return None
    if isinstance(raw, date):
        return (date.today() - raw).days
    try:
        d = datetime.strptime(str(raw), "%Y-%m-%d").date()
        return (date.today() - d).days
    except ValueError:
        return None


def load_manual(path: str | Path, file_type: str) -> dict[str, Any]:
    """Load manual yaml + return standardized status envelope.

    Returns:
        {
            "data": parsed_dict | None,
            "status": "fresh" | "stale" | "missing",
            "age_days": int | None,
            "data_quality": "high" | "low" | "missing",
            "effect": str | None,
            "path": str,
            "file_type": file_type,
        }
    """
    p = Path(path)
    threshold = STALE_DAYS.get(file_type)
    if threshold is None:
        raise ValueError(f"Unknown file_type={file_type!r}. Add to STALE_DAYS.")

    if not p.exists():
        return {
            "data": None,
            "status": "missing",
            "age_days": None,
            "data_quality": "missing",
            "effect": DEGRADATION_EFFECT.get(file_type),
            "path": str(p),
            "file_type": file_type,
        }

    try:
        data = _read_yaml(p)
    except yaml.YAMLError as e:
        return {
            "data": None,
            "status": "parse_error",
            "age_days": None,
            "data_quality": "missing",
            "effect": DEGRADATION_EFFECT.get(file_type),
            "path": str(p),
            "file_type": file_type,
            "error": str(e),
        }

    # Prefer in-file last_updated over mtime (user-controlled)
    age = _parse_last_updated(data)
    if age is None:
        age = _file_age_days(p)

    if age > threshold:
        return {
            "data": data,
            "status": "stale",
            "age_days": age,
            "data_quality": "low",
            "effect": DEGRADATION_EFFECT.get(file_type),
            "path": str(p),
            "file_type": file_type,
        }

    return {
        "data": data,
        "status": "fresh",
        "age_days": age,
        "data_quality": "high",
        "effect": None,
        "path": str(p),
        "file_type": file_type,
    }


def is_blocking_stale(envelope: dict, killer: bool) -> bool:
    """Check whether the loaded envelope blocks killer-layer execution.

    Used by orchestrator: if a killer layer depends on a manual file that
    is missing/parse_error, the orchestrator must EXIT with `pending_data`
    instead of inferring values. Non-killer layers may proceed with
    degradation effect noted.
    """
    if not killer:
        return False
    return envelope["status"] in {"missing", "parse_error"}


def summarize_envelopes(envelopes: dict[str, dict]) -> dict[str, Any]:
    """Build the `manual_inputs_status` block for layer output yaml."""
    out: dict[str, Any] = {}
    for key, env in envelopes.items():
        out[key] = {
            "status": env["status"],
            "age_days": env["age_days"],
            "effect": env["effect"],
        }
    return out


if __name__ == "__main__":
    # Smoke test on existing portfolio.yaml
    base = Path(__file__).resolve().parents[2] / "configs"
    portfolio = load_manual(base / "portfolio.yaml", "portfolio")
    watchlist = load_manual(base / "watchlist.yaml", "watchlist")
    missing = load_manual(base / "margin_debt.yaml", "margin_debt")
    print(f"portfolio: status={portfolio['status']} age={portfolio['age_days']}")
    print(f"watchlist: status={watchlist['status']} age={watchlist['age_days']}")
    print(f"margin_debt (expected missing): status={missing['status']} effect={missing['effect']}")
