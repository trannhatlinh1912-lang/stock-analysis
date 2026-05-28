"""Layer 5 — Catalyst Detector.

Phase 1 scope:
  - 5.2 Earnings    AUTO (from fundamentals YoY)
  - 5.3 Industry Cycle AUTO (from sector_regime)
  - 5.5 Corp Action MANUAL (Phase 3 will add Company.events scan)
  - 5.7 Flow        DEFER (needs foreign_history.csv from Phase 3)
  - 5.1, 5.4, 5.6, 5.8 MANUAL via configs/catalyst_manual.yaml

Multi-catalyst stack rule (per L5 spec):
  - ≥2 catalysts same direction with ≥1 verified (hard/medium) → tier upgrade +1 (max hard)
  - Speculative or sentiment alone → no upgrade

Output: data/catalyst/{TICKER}.json per ticker. Aggregate effective_tier +
direction net + recommended_mode.

Manual stale (>14 days) → all manual catalysts tier-downgrade 1 step.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
CONFIGS = ROOT / "configs"

sys.path.insert(0, str(ROOT / "scripts"))
from utils.manual_loader import load_manual  # noqa: E402


TIER_RANK = {"speculative": 0, "soft": 1, "medium": 2, "hard": 3}
RANK_TIER = {v: k for k, v in TIER_RANK.items()}


def _downgrade(tier: str, steps: int = 1) -> str:
    r = TIER_RANK.get(tier, 0)
    return RANK_TIER[max(0, r - steps)]


def _upgrade(tier: str, steps: int = 1) -> str:
    r = TIER_RANK.get(tier, 0)
    return RANK_TIER[min(3, r + steps)]


def detect_earnings_catalyst(fund: dict) -> dict | None:
    """5.2 Earnings — YoY revenue + NI + margin from per_year fundamentals."""
    py = fund.get("per_year", {})
    years = sorted(py.keys(), reverse=True)
    if len(years) < 2:
        return None
    latest_yr, prior_yr = years[0], years[1]
    latest = py[latest_yr]
    prior = py[prior_yr]

    rev_curr = latest.get("revenue")
    rev_prior = prior.get("revenue")
    ni_curr = latest.get("net_income")
    ni_prior = prior.get("net_income")

    if None in (rev_curr, rev_prior, ni_curr, ni_prior):
        return None
    if rev_prior <= 0 or ni_prior <= 0:
        # Turnaround year — handle separately
        if ni_prior <= 0 < ni_curr:
            return {
                "id": f"turnaround_{latest_yr}",
                "category": "5.2_earnings",
                "tier": "medium",
                "direction": "bullish",
                "description": f"NI turnaround: {ni_prior:.0f} → {ni_curr:.0f} ({latest_yr} vs {prior_yr})",
                "sources": [f"fundamentals.per_year[{latest_yr}].net_income vs [{prior_yr}]"],
                "detected_by": "auto",
                "detected_at": date.today().isoformat(),
            }
        return None

    rev_yoy = (rev_curr / rev_prior - 1.0) * 100
    ni_yoy = (ni_curr / ni_prior - 1.0) * 100
    margin_curr = ni_curr / rev_curr * 100
    margin_prior = ni_prior / rev_prior * 100
    margin_delta_pp = margin_curr - margin_prior

    if rev_yoy > 10 and ni_yoy > 15 and margin_delta_pp > 0:
        return {
            "id": f"earnings_beat_{latest_yr}",
            "category": "5.2_earnings",
            "tier": "hard",
            "direction": "bullish",
            "description": (
                f"Revenue YoY {rev_yoy:+.1f}%, NI YoY {ni_yoy:+.1f}%, "
                f"margin Δ {margin_delta_pp:+.2f}pp ({latest_yr} vs {prior_yr})"
            ),
            "sources": [f"fundamentals.per_year[{latest_yr}] vs [{prior_yr}]"],
            "detected_by": "auto",
            "detected_at": date.today().isoformat(),
        }
    if ni_yoy < -20 and rev_yoy < 0:
        return {
            "id": f"earnings_miss_{latest_yr}",
            "category": "5.2_earnings",
            "tier": "medium",
            "direction": "bearish",
            "description": f"Revenue YoY {rev_yoy:+.1f}%, NI YoY {ni_yoy:+.1f}%",
            "sources": [f"fundamentals.per_year[{latest_yr}]"],
            "detected_by": "auto",
            "detected_at": date.today().isoformat(),
        }
    return None


def detect_cycle_catalyst(sector_data: dict) -> dict | None:
    """5.3 Industry Cycle — derive from sector_regime universal tier."""
    regime = sector_data.get("regime")
    score = sector_data.get("score", 0)
    rs_label = sector_data.get("dimensions", {}).get("rs", {}).get("label")

    if regime == "BULLISH":
        return {
            "id": f"sector_cycle_bullish_{sector_data.get('sector')}",
            "category": "5.3_cycle",
            "tier": "medium",
            "direction": "bullish",
            "description": f"Sector regime BULLISH (score={score:+d}, rs={rs_label})",
            "sources": [f"sector_regime.{sector_data.get('sector')}"],
            "detected_by": "auto",
            "detected_at": date.today().isoformat(),
        }
    if regime == "NEUTRAL_TO_BULLISH" and rs_label == "leader":
        return {
            "id": f"sector_cycle_inflecting_{sector_data.get('sector')}",
            "category": "5.3_cycle",
            "tier": "soft",
            "direction": "bullish",
            "description": f"Sector NEUTRAL_TO_BULLISH + RS leader (score={score:+d})",
            "sources": [f"sector_regime.{sector_data.get('sector')}"],
            "detected_by": "auto",
            "detected_at": date.today().isoformat(),
        }
    if regime in ("BEARISH", "CRISIS"):
        return {
            "id": f"sector_cycle_bearish_{sector_data.get('sector')}",
            "category": "5.3_cycle",
            "tier": "medium",
            "direction": "bearish",
            "description": f"Sector regime {regime} (score={score:+d})",
            "sources": [f"sector_regime.{sector_data.get('sector')}"],
            "detected_by": "auto",
            "detected_at": date.today().isoformat(),
        }
    return None


def _load_manual_catalysts(ticker: str, manual_env: dict) -> list[dict]:
    if manual_env["data"] is None:
        return []
    table = manual_env["data"].get("catalysts_by_ticker") or {}
    items = table.get(ticker, []) or []
    out = []
    for it in items:
        rec = dict(it)
        rec["detected_by"] = "manual"
        if manual_env["status"] == "stale":
            rec["tier"] = _downgrade(rec.get("tier", "speculative"))
            rec["stale_downgraded"] = True
        out.append(rec)
    return out


def _apply_stack_rule(catalysts: list[dict]) -> tuple[str, dict]:
    """Net direction + effective tier after stack.

    Rule:
      - Group by direction.
      - Net = #bullish - #bearish.
      - For dominant direction: count verified (hard/medium) items.
      - If #items >=2 AND ≥1 verified → upgrade tier max +1.
      - Effective tier = max tier in dominant + upgrade (capped hard).
      - If net == 0 (tie) → no catalyst valid.
    """
    bull = [c for c in catalysts if c.get("direction") == "bullish"]
    bear = [c for c in catalysts if c.get("direction") == "bearish"]
    net = len(bull) - len(bear)
    if net == 0:
        return "neutral", {
            "effective_tier": "none",
            "bullish_count": len(bull),
            "bearish_count": len(bear),
            "verified_bullish": 0,
            "verified_bearish": 0,
            "catalyst_valid": False,
            "reason": "net=0 ambiguous → invalid",
        }
    dominant = "bullish" if net > 0 else "bearish"
    group = bull if dominant == "bullish" else bear

    verified = [c for c in group if c.get("tier") in ("hard", "medium")]
    max_rank = max((TIER_RANK.get(c.get("tier", "speculative"), 0) for c in group), default=0)
    if len(group) >= 2 and len(verified) >= 1 and max_rank < 3:
        effective_rank = max_rank + 1
    else:
        effective_rank = max_rank
    effective_tier = RANK_TIER[effective_rank]

    catalyst_valid = effective_tier in ("hard", "medium", "soft") and len(verified) >= 1
    if dominant == "bearish":
        catalyst_valid = False  # bearish catalyst → no buy

    return dominant, {
        "effective_tier": effective_tier,
        "bullish_count": len(bull),
        "bearish_count": len(bear),
        "verified_bullish": len([c for c in bull if c.get("tier") in ("hard", "medium")]),
        "verified_bearish": len([c for c in bear if c.get("tier") in ("hard", "medium")]),
        "catalyst_valid": catalyst_valid,
    }


def _recommended_mode(effective_tier: str) -> str | None:
    return {
        "hard": "core",
        "medium": "swing",
        "soft": "t_plus",
        "speculative": None,
        "none": None,
    }.get(effective_tier)


def detect_for_ticker(
    ticker: str,
    fund: dict,
    sector_data: dict,
    manual_env: dict,
) -> dict:
    catalysts = []
    e = detect_earnings_catalyst(fund)
    if e:
        catalysts.append(e)
    c = detect_cycle_catalyst(sector_data)
    if c:
        catalysts.append(c)
    catalysts.extend(_load_manual_catalysts(ticker, manual_env))

    direction, agg = _apply_stack_rule(catalysts)
    rec_mode = _recommended_mode(agg["effective_tier"])

    return {
        "ticker": ticker,
        "as_of": date.today().isoformat(),
        "catalysts": catalysts,
        "aggregate": {
            **agg,
            "net_direction": direction,
            "recommended_mode": rec_mode,
        },
        "manual_inputs_status": {
            "catalyst_manual": {
                "status": manual_env["status"],
                "age_days": manual_env["age_days"],
                "effect": manual_env["effect"],
            }
        },
    }


def main() -> int:
    p = argparse.ArgumentParser(description="Layer 5 Catalyst Detector batch.")
    p.add_argument("--tickers", nargs="+")
    args = p.parse_args()

    today = date.today().isoformat()
    l3 = json.loads((DATA / f"sector_regime_{today}.json").read_text())
    wl = yaml.safe_load((CONFIGS / "watchlist.yaml").read_text())
    tk_sec = {t: sec for sec, ts in wl["sector_baskets"].items() for t in ts}
    tickers = args.tickers or wl.get("all_fetched", [])

    manual_env = load_manual(CONFIGS / "catalyst_manual.yaml", "catalyst_manual")
    print(f"[catalyst] manual_yaml status={manual_env['status']} age={manual_env['age_days']}d")

    out_dir = DATA / "catalyst"
    out_dir.mkdir(parents=True, exist_ok=True)

    rows = []
    for t in tickers:
        sec = tk_sec.get(t, "unknown")
        fund_path = DATA / "fundamentals" / f"{t}.json"
        if not fund_path.exists():
            continue
        fund = json.loads(fund_path.read_text())
        sector_data = l3.get("sectors", {}).get(sec, {})
        r = detect_for_ticker(t, fund, sector_data, manual_env)
        (out_dir / f"{t}.json").write_text(json.dumps(r, ensure_ascii=False, indent=2))
        agg = r["aggregate"]
        rows.append((t, sec, len(r["catalysts"]), agg["net_direction"], agg["effective_tier"],
                    "✓" if agg["catalyst_valid"] else "-",
                    agg.get("recommended_mode") or "-"))

    print()
    print(f"  {'TICKER':8s} {'SECTOR':14s} {'N':3s} {'DIR':10s} {'TIER':12s} {'VALID':6s} REC_MODE")
    for row in sorted(rows, key=lambda x: (x[1], x[0])):
        print(f"  {row[0]:8s} {row[1]:14s} {row[2]:3d} {row[3]:10s} {row[4]:12s} {row[5]:6s} {row[6]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
