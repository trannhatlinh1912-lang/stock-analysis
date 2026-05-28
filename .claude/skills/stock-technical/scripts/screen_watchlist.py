"""Orchestrator — Layers 1-8 + 3-state classifier (Guardrail 1).

Phase 3 build. L9 plan generation runs after orchestrator (entry_exit_plan.py)
for PASS tickers with ENTRY sizing.

Reads:
  - data/quality_gate/{TICKER}.json     (L1)
  - data/market_regime_{DATE}.json      (L2)
  - data/sector_regime_{DATE}.json      (L3)
  - data/trading_mode/{TICKER}.json     (L4)
  - data/catalyst/{TICKER}.json         (L5)
  - data/valuation/{TICKER}.json        (L6A)
  - data/technical/{TICKER}.json        (L6B)
  - data/lai/{TICKER}.json              (L7)
  - data/sizing/{TICKER}.json           (L8, computed lazily during orchestrator)
  - configs/watchlist.yaml              (universe + sector map)

Classification (Guardrail 1):
  Killer layers → auto SKIP:
    - L1 HARD_FAIL or DATA_MISSING
    - L2 CRISIS or UNKNOWN
    - L3 sector CRISIS
    - L4 no eligible modes
    - L7 RED lái for best mode
    - L8 sizing REJECT (cap exhausted)
  Non-killer concerns → WATCH:
    - L1 WARNING
    - L2/L3 NEUTRAL_TO_BEARISH/BEARISH
    - L5 catalyst not valid
    - L6 combo fail for all eligible modes
    - L7 YELLOW lái
  All clear → PASS.

Output: reports/screen_{DATE}.md + data/screen_{DATE}.json
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
REPORTS = ROOT / "reports"


def _load_json(path: Path) -> dict | None:
    return json.loads(path.read_text()) if path.exists() else None


def _load_watchlist() -> dict:
    return yaml.safe_load((CONFIGS / "watchlist.yaml").read_text())


def _ticker_sector_map(wl: dict) -> dict[str, str]:
    return {t: sec for sec, ts in wl["sector_baskets"].items() for t in ts}


def _l6_combination(
    mode: str, valuation_pass: bool, technical_pass: bool
) -> tuple[bool, str]:
    """L6 combination rule per spec:
      core: REQUIRED both (AND)
      swing: at least 1 of 2 (OR)
      t_plus: technical REQUIRED (valuation optional)
    """
    if mode == "core":
        return (valuation_pass and technical_pass,
                f"val={valuation_pass} AND tech={technical_pass}")
    if mode == "swing":
        return (valuation_pass or technical_pass,
                f"val={valuation_pass} OR tech={technical_pass}")
    if mode == "t_plus":
        return (technical_pass, f"tech_required={technical_pass}")
    return False, f"unknown_mode={mode}"


def _best_mode_with_l6(l4: dict, l6_val: dict, l6_tech: dict) -> dict:
    """Determine which eligible modes have L6 passing. Returns:
       {best_mode, eligible_modes_after_l6: [...], per_mode: {mode: {l6_pass, reason}}}
    """
    eligible = l4.get("eligible_modes", [])
    val_pass = (l6_val or {}).get("valuation_pass", False)
    technical_mode = (l6_tech or {}).get("mode_pass", {}) or {}

    per_mode = {}
    after_l6 = []
    for m in eligible:
        tech_pass = technical_mode.get(m, {}).get("pass", False)
        ok, reason = _l6_combination(m, val_pass, tech_pass)
        per_mode[m] = {"l6_pass": ok, "reason": reason,
                       "valuation_pass": val_pass,
                       "technical_pass": tech_pass}
        if ok:
            after_l6.append(m)

    # Best mode priority: core > swing > t_plus (highest conviction first)
    order = ["core", "swing", "t_plus"]
    best = next((m for m in order if m in after_l6), None)
    return {"best_mode": best, "modes_after_l6": after_l6, "per_mode": per_mode}


def _is_killer(l1: dict, l2: dict, l3: dict, l4: dict, l7: dict, best_mode: str | None) -> tuple[bool, str]:
    if l1.get("verdict") in ("HARD_FAIL", "DATA_MISSING"):
        return True, f"L1 {l1.get('verdict')}"
    if l2.get("regime") in ("CRISIS", "UNKNOWN"):
        return True, f"L2 {l2.get('regime')}"
    if l3.get("regime") == "CRISIS":
        return True, f"L3 sector CRISIS ({l3.get('sector')})"
    if not l4.get("eligible_modes"):
        return True, "L4 no eligible modes"
    if best_mode:
        lai_level = (l7.get("warning_level_per_mode") or {}).get(best_mode)
        if lai_level == "red":
            return True, f"L7 RED lái for {best_mode}"
    return False, ""


def screen_ticker(
    ticker: str, sector: str, l2_data: dict, sector_data: dict
) -> dict:
    l1 = _load_json(DATA / "quality_gate" / f"{ticker}.json") or {"verdict": "DATA_MISSING"}
    l3 = sector_data.get("sectors", {}).get(sector, {})
    l4 = _load_json(DATA / "trading_mode" / f"{ticker}.json") or {"eligible_modes": []}
    l5 = _load_json(DATA / "catalyst" / f"{ticker}.json") or {}
    l6_val = _load_json(DATA / "valuation" / f"{ticker}.json") or {}
    l6_tech = _load_json(DATA / "technical" / f"{ticker}.json") or {}
    l7 = _load_json(DATA / "lai" / f"{ticker}.json") or {}

    # Compute best_mode preview to gate L7 killer check
    combo_preview = _best_mode_with_l6(l4, l6_val, l6_tech)

    # Killer check first
    killer, reason = _is_killer(l1, l2_data, l3, l4, l7, combo_preview["best_mode"])
    if killer:
        return {
            "ticker": ticker,
            "sector": sector,
            "verdict": "SKIP",
            "rationale": reason,
            "best_mode": None,
            "layer_1_verdict": l1.get("verdict"),
            "layer_1_warning_count": len(l1.get("warning_flags", [])),
            "layer_2_regime": l2_data.get("regime"),
            "layer_3_regime": l3.get("regime"),
            "layer_4_eligible": l4.get("eligible_modes", []),
            "layer_5_tier": (l5.get("aggregate") or {}).get("effective_tier"),
            "layer_5_valid": (l5.get("aggregate") or {}).get("catalyst_valid"),
            "layer_6_combo": None,
            "layer_7_lai_level": (l7.get("warning_level_per_mode") or {}).get(combo_preview["best_mode"]) if combo_preview["best_mode"] else None,
            "layer_7_active_count": l7.get("symptoms_active_count", 0),
            "technical_state": l6_tech.get("technical_state"),
        }

    # Non-killer concerns → WATCH-counted
    watch_reasons = []
    if l1.get("verdict") == "WARNING":
        watch_reasons.append(f"L1 warn n={len(l1.get('warning_flags', []))}")

    sector_regime = l3.get("regime")
    if sector_regime in ("NEUTRAL_TO_BEARISH", "BEARISH"):
        watch_reasons.append(f"L3 sector {sector_regime}")

    market_regime = l2_data.get("regime")
    if market_regime in ("NEUTRAL_TO_BEARISH", "BEARISH"):
        watch_reasons.append(f"L2 market {market_regime}")

    # L5 catalyst
    agg = (l5.get("aggregate") or {})
    catalyst_valid = agg.get("catalyst_valid", False)
    if not catalyst_valid:
        watch_reasons.append(f"L5 catalyst invalid (tier={agg.get('effective_tier')})")

    # L6 combination (reuse preview)
    combo = combo_preview
    if not combo["best_mode"]:
        watch_reasons.append("L6 combo fail for all eligible modes")

    # L7 yellow lái for best mode → WATCH
    if combo["best_mode"]:
        lai_lvl = (l7.get("warning_level_per_mode") or {}).get(combo["best_mode"])
        if lai_lvl == "yellow":
            watch_reasons.append(f"L7 YELLOW lái for {combo['best_mode']}")

    if watch_reasons:
        verdict = "WATCH"
        rationale = "; ".join(watch_reasons)
    else:
        verdict = "PASS"
        rationale = "all layers clear"

    return {
        "ticker": ticker,
        "sector": sector,
        "verdict": verdict,
        "rationale": rationale,
        "best_mode": combo["best_mode"],
        "modes_after_l6": combo["modes_after_l6"],
        "layer_1_verdict": l1.get("verdict"),
        "layer_1_warning_count": len(l1.get("warning_flags", [])),
        "layer_2_regime": market_regime,
        "layer_3_regime": sector_regime,
        "layer_4_eligible": l4.get("eligible_modes", []),
        "layer_5_tier": agg.get("effective_tier"),
        "layer_5_valid": catalyst_valid,
        "layer_5_direction": agg.get("net_direction"),
        "layer_6_combo": combo["per_mode"],
        "layer_7_lai_level": (l7.get("warning_level_per_mode") or {}).get(combo["best_mode"]) if combo["best_mode"] else None,
        "layer_7_active_count": l7.get("symptoms_active_count", 0),
        "technical_state": l6_tech.get("technical_state"),
        "rs_label": l6_tech.get("rs_label"),
    }


def render_report(results: list[dict], l2_data: dict, sector_data: dict, today: str) -> str:
    L = [
        f"# Watchlist Screen — {today}",
        "",
        "## Market regime (Layer 2)",
        f"- State: **{l2_data.get('regime')}** (score={l2_data.get('score')}, conf={l2_data.get('confidence_pct')}%)",
        f"- Trading modes allowed: {l2_data.get('trading_modes_allowed')}",
        f"- NAV deploy cap: {l2_data.get('nav_deploy_cap_pct')}%",
        f"- Missing pillars: {l2_data.get('missing_pillars')}",
        "",
        "## Sector regimes (Layer 3)",
        "",
        "| Sector | Regime | Score | Conf | RS | Breadth | Flow |",
        "|---|---|---|---|---|---|---|",
    ]
    for sec, r in sector_data.get("sectors", {}).items():
        dims = r.get("dimensions", {})
        L.append(
            f"| {sec} | **{r.get('regime')}** | {r.get('score'):+d} | {r.get('confidence_pct')}% | "
            f"{dims.get('rs', {}).get('label', '?')} | "
            f"{dims.get('breadth', {}).get('label', '?')} | "
            f"{dims.get('flow', {}).get('label', '?')} |"
        )

    buckets: dict[str, list[dict]] = {"PASS": [], "WATCH": [], "SKIP": []}
    for r in results:
        buckets.setdefault(r["verdict"], []).append(r)

    L += [
        "",
        "## Ticker classification (Layers 1-6)",
        "",
        f"- **PASS** (all 6 layers clear, mode selected): {len(buckets['PASS'])}",
        f"- **WATCH** (non-killer concerns, monitor): {len(buckets['WATCH'])}",
        f"- **SKIP** (killer layer fail): {len(buckets['SKIP'])}",
        "",
    ]

    for state in ("PASS", "WATCH", "SKIP"):
        L.append(f"### {state} ({len(buckets[state])})")
        L.append("")
        if not buckets[state]:
            L.append("- (none)")
        else:
            L.append("| Ticker | Sector | Best Mode | L1 | L3 sector | L5 cat | Tech state | Rationale |")
            L.append("|---|---|---|---|---|---|---|---|")
            for r in sorted(buckets[state], key=lambda x: (x["sector"], x["ticker"])):
                L.append(
                    f"| **{r['ticker']}** | {r['sector']} | "
                    f"{r.get('best_mode') or '-'} | "
                    f"{r.get('layer_1_verdict')} (w={r.get('layer_1_warning_count')}) | "
                    f"{r.get('layer_3_regime')} | "
                    f"{r.get('layer_5_tier')}/{r.get('layer_5_direction')} | "
                    f"{r.get('technical_state')} | "
                    f"{r['rationale']} |"
                )
        L.append("")
    return "\n".join(L)


def main() -> int:
    p = argparse.ArgumentParser(description="Orchestrator: Layers 1-6 screen + 3-state classifier.")
    p.add_argument("--tickers", nargs="+")
    args = p.parse_args()

    today = date.today().isoformat()
    l2 = _load_json(DATA / f"market_regime_{today}.json")
    l3 = _load_json(DATA / f"sector_regime_{today}.json")
    if l2 is None:
        print(f"[screen] L2 missing for {today}. Run market_regime.py.", file=sys.stderr)
        return 2
    if l3 is None:
        print(f"[screen] L3 missing for {today}. Run sector_regime.py.", file=sys.stderr)
        return 2

    wl = _load_watchlist()
    tk_sec = _ticker_sector_map(wl)
    tickers = args.tickers or wl.get("all_fetched", [])

    results = [screen_ticker(t, tk_sec.get(t, "unknown"), l2, l3) for t in tickers]

    REPORTS.mkdir(parents=True, exist_ok=True)
    out_json = DATA / f"screen_{today}.json"
    out_json.write_text(json.dumps({"as_of": today, "results": results}, ensure_ascii=False, indent=2))
    out_md = REPORTS / f"screen_{today}.md"
    out_md.write_text(render_report(results, l2, l3, today))
    print(f"[screen] json → {out_json}")
    print(f"[screen] md   → {out_md}")

    buckets: dict[str, int] = {"PASS": 0, "WATCH": 0, "SKIP": 0}
    for r in results:
        buckets[r["verdict"]] = buckets.get(r["verdict"], 0) + 1
    print(f"\nN={len(results)}: PASS={buckets['PASS']} WATCH={buckets['WATCH']} SKIP={buckets['SKIP']}")
    print()
    for state in ("PASS", "WATCH", "SKIP"):
        syms = [(r["ticker"], r.get("best_mode") or "-") for r in results if r["verdict"] == state]
        formatted = ", ".join(f"{t}({m})" for t, m in syms) if syms else "(none)"
        print(f"  {state:5s}: {formatted}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
