"""Layer 4 — Trading Mode permission per ticker.

Pure-logic decision module. Inputs:
  - Layer 1 quality_gate result
  - Layer 2 market_regime result (today)
  - Layer 3 sector_regime result (today)
  - Optional Layer 5 catalyst summary (None during Phase 1 build)
  - Optional Layer 6 valuation + technical (None during Phase 1 build)
  - Optional Layer 7 lai status (None during Phase 1)

Output per ticker:
  {
    eligible_modes: [core?, swing?, t_plus?],
    rationale_per_mode: {mode: pass | reason_skipped},
    mode_specific_caps: {core_max_pct, swing_max_pct, t_plus_max_pct},
    neutral_t_plus_conditional: bool,
    notes: [...]
  }

L4 spec: permission matrix from Market Regime × Mode + per-mode entry criteria.
T+ in NEUTRAL regime needs: sector BULLISH/NEUTRAL_TO_BULLISH AND RS leader AND
vol>=1.5xMA20 AND 50% cap reduction. Some criteria need L6 technical data —
return `requires_l6_confirm` flag when L6 not available yet.
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


# Mode caps per regime (% NAV per single ticker)
MODE_CAPS_PER_REGIME = {
    "BULLISH":            {"core_max_pct": 20, "swing_max_pct": 15, "t_plus_max_pct": 10},
    "NEUTRAL":            {"core_max_pct": 20, "swing_max_pct": 15, "t_plus_max_pct": 5},  # T+ 50%
    "NEUTRAL_TO_BEARISH": {"core_max_pct": 15, "swing_max_pct": 10, "t_plus_max_pct": 0},
    "BEARISH":            {"core_max_pct": 10, "swing_max_pct": 0,  "t_plus_max_pct": 0},
    "CRISIS":             {"core_max_pct": 5,  "swing_max_pct": 0,  "t_plus_max_pct": 0},
}


# Sector regimes that allow mode entry
CORE_SECTOR_BLOCK = {"CRISIS"}                      # block Core only on CRISIS
SWING_SECTOR_BLOCK = {"BEARISH", "CRISIS"}          # block Swing on BEARISH/CRISIS
T_PLUS_SECTOR_REQUIRED = {"BULLISH", "NEUTRAL_TO_BULLISH"}  # T+ ONLY in bullish-leaning


def _l1_ok_for_mode(l1: dict, mode: str) -> tuple[bool, str]:
    """Layer 1 quality check per mode entry criteria."""
    verdict = l1.get("verdict")
    if verdict == "HARD_FAIL":
        return False, "L1 hard_fail"
    if verdict == "DATA_MISSING":
        return False, "L1 data missing"
    warn_n = len(l1.get("warning_flags", []))
    if mode == "core" and warn_n > 1:
        return False, f"L1 warn_count={warn_n} > 1 (Core needs clean/low warn)"
    if mode == "t_plus" and warn_n > 0:
        return False, f"L1 warn_count={warn_n} (T+ needs PASS clean)"
    return True, ""


def _l1_tradable_ok(l1: dict, mode: str) -> tuple[bool, str]:
    trad = l1.get("tradable", {})
    if mode == "t_plus":
        if not trad.get("t_plus", False):
            return False, "tradable_t_plus=False (mcap<2000B OR ADTV<5B)"
    else:
        if not trad.get("core", False):
            return False, "tradable_core=False (mcap<500B OR ADTV<1B)"
    return True, ""


def decide(
    l1: dict,
    l2: dict,
    l3: dict,
    technical_data: dict | None = None,
) -> dict:
    market_regime = l2.get("regime", "UNKNOWN")
    sector_regime = l3.get("regime", "UNKNOWN")

    if market_regime in ("UNKNOWN", "CRISIS"):
        return {
            "eligible_modes": [],
            "market_regime": market_regime,
            "sector_regime": sector_regime,
            "rationale_per_mode": {
                "core": f"market_regime={market_regime}",
                "swing": f"market_regime={market_regime}",
                "t_plus": f"market_regime={market_regime}",
            },
            "mode_specific_caps": MODE_CAPS_PER_REGIME.get(market_regime, {}),
            "neutral_t_plus_conditional": False,
            "notes": [],
        }

    modes_allowed_by_market = set(l2.get("trading_modes_allowed", []))

    eligible: list[str] = []
    rationale: dict[str, str] = {}
    notes: list[str] = []

    # ---- Core ----
    if "core" not in modes_allowed_by_market:
        rationale["core"] = f"market_regime={market_regime} blocks core"
    elif sector_regime in CORE_SECTOR_BLOCK:
        rationale["core"] = f"sector_regime={sector_regime} blocks core"
    else:
        ok_q, why = _l1_ok_for_mode(l1, "core")
        ok_t, why_t = _l1_tradable_ok(l1, "core")
        if not ok_q:
            rationale["core"] = why
        elif not ok_t:
            rationale["core"] = why_t
        else:
            eligible.append("core")
            rationale["core"] = "pass"
            if sector_regime == "BEARISH":
                notes.append("Core in BEARISH sector: deep_value + catalyst REQUIRED (L5 must verify)")

    # ---- Swing ----
    if "swing" not in modes_allowed_by_market:
        rationale["swing"] = f"market_regime={market_regime} blocks swing"
    elif sector_regime in SWING_SECTOR_BLOCK:
        rationale["swing"] = f"sector_regime={sector_regime} blocks swing"
    else:
        ok_q, why = _l1_ok_for_mode(l1, "swing")
        ok_t, why_t = _l1_tradable_ok(l1, "swing")
        if not ok_q:
            rationale["swing"] = why
        elif not ok_t:
            rationale["swing"] = why_t
        else:
            eligible.append("swing")
            rationale["swing"] = "pass"
            if sector_regime == "NEUTRAL_TO_BEARISH":
                notes.append("Swing in NEUTRAL_TO_BEARISH sector: selective + catalyst REQUIRED")

    # ---- T+ ----
    neutral_conditional = False
    if "t_plus" not in modes_allowed_by_market:
        rationale["t_plus"] = f"market_regime={market_regime} blocks t_plus"
    elif sector_regime not in T_PLUS_SECTOR_REQUIRED:
        rationale["t_plus"] = f"sector_regime={sector_regime} not in {T_PLUS_SECTOR_REQUIRED}"
    else:
        ok_q, why = _l1_ok_for_mode(l1, "t_plus")
        ok_t, why_t = _l1_tradable_ok(l1, "t_plus")
        if not ok_q:
            rationale["t_plus"] = why
        elif not ok_t:
            rationale["t_plus"] = why_t
        else:
            # NEUTRAL → T+ conditional check
            if market_regime == "NEUTRAL":
                neutral_conditional = True
                conditions_met = []
                conditions_unmet = []
                # Condition: sector BULLISH/NEUTRAL_TO_BULLISH → already verified above
                conditions_met.append("sector_BULLISH_leaning")
                # Condition: RS leader — need ticker-level RS (not basket)
                if technical_data and technical_data.get("rs_label") == "leader":
                    conditions_met.append("rs_leader")
                elif technical_data:
                    conditions_unmet.append(f"rs_label={technical_data.get('rs_label')} (not leader)")
                else:
                    conditions_unmet.append("requires_l6_confirm:rs_leader")
                # Condition: vol >= 1.5 MA20 on entry day
                if technical_data and (technical_data.get("vol_ratio") or 0) >= 1.5:
                    conditions_met.append(f"vol_ratio={technical_data.get('vol_ratio')}")
                elif technical_data:
                    conditions_unmet.append(f"vol_ratio={technical_data.get('vol_ratio')} (<1.5)")
                else:
                    conditions_unmet.append("requires_l6_confirm:vol_ratio_>=1.5")

                if conditions_unmet:
                    rationale["t_plus"] = "conditional_pending: " + ", ".join(conditions_unmet)
                    notes.append(f"T+ NEUTRAL conditions met: {conditions_met}; pending: {conditions_unmet}")
                else:
                    eligible.append("t_plus")
                    rationale["t_plus"] = "pass (NEUTRAL conditional all met, size cap 50%)"
            else:
                # BULLISH regime — T+ full size
                eligible.append("t_plus")
                rationale["t_plus"] = "pass (BULLISH regime, full T+ size)"

    return {
        "eligible_modes": eligible,
        "market_regime": market_regime,
        "sector_regime": sector_regime,
        "rationale_per_mode": rationale,
        "mode_specific_caps": MODE_CAPS_PER_REGIME.get(market_regime, {}),
        "neutral_t_plus_conditional": neutral_conditional,
        "notes": notes,
    }


def _load_json(p: Path) -> dict | None:
    return json.loads(p.read_text()) if p.exists() else None


def _load_watchlist() -> dict:
    return yaml.safe_load((CONFIGS / "watchlist.yaml").read_text())


def _ticker_sector_map(wl: dict) -> dict[str, str]:
    return {t: sec for sec, ts in wl["sector_baskets"].items() for t in ts}


def main() -> int:
    p = argparse.ArgumentParser(description="Layer 4 Trading Mode decider (batch).")
    p.add_argument("--tickers", nargs="+", help="Subset. Default: all in watchlist.")
    args = p.parse_args()

    today = date.today().isoformat()
    l2 = _load_json(DATA / f"market_regime_{today}.json")
    l3_all = _load_json(DATA / f"sector_regime_{today}.json")
    if l2 is None or l3_all is None:
        print("[trading_mode] requires market_regime + sector_regime for today. Run those first.", file=sys.stderr)
        return 2

    wl = _load_watchlist()
    tk_sec = _ticker_sector_map(wl)
    tickers = args.tickers or wl.get("all_fetched", [])

    out_dir = DATA / "trading_mode"
    out_dir.mkdir(parents=True, exist_ok=True)
    results: dict[str, dict] = {}

    for t in tickers:
        sector = tk_sec.get(t, "unknown")
        l1 = _load_json(DATA / "quality_gate" / f"{t}.json") or {"verdict": "DATA_MISSING"}
        l3 = l3_all.get("sectors", {}).get(sector, {})
        r = decide(l1, l2, l3)
        r["ticker"] = t
        r["sector"] = sector
        results[t] = r
        (out_dir / f"{t}.json").write_text(json.dumps(r, ensure_ascii=False, indent=2))

    # Print summary
    rows = []
    for t, r in results.items():
        rows.append((t, r["sector"], ",".join(r["eligible_modes"]) or "-", r["sector_regime"]))
    print(f"[trading_mode] {len(results)} tickers processed → {out_dir}")
    print()
    print(f"  {'TICKER':8s} {'SECTOR':14s} {'ELIGIBLE':22s} SECTOR_REGIME")
    for row in sorted(rows, key=lambda x: (x[1], x[0])):
        print(f"  {row[0]:8s} {row[1]:14s} {row[2]:22s} {row[3]}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
