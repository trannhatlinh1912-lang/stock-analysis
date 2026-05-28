"""Layer 9 — Entry/Exit Plan + Trade Journal scaffold.

For each ticker with PASS verdict AND non-REJECT sizing, generate:
  - Targets: primary (first resistance / +20% Core), secondary
  - Stops: 6 layers
      1 fundamental (text — user fills sector-specific triggers)
      2 technical (mode-specific from L6B)
      3 time (mode-specific review/forced exit)
      4 kill switch (boilerplate)
      5 lai_escalate (yellow → red transition watch)
      6 trailing (high - N×ATR, mode-specific N)
  - Trade journal scaffold yaml

Output: data/entry_plan/{TICKER}.json + data/trade_journal/{TICKER}_{DATE}.yaml

Per Layer 9 spec partial-profit table:
  Core  +20%/+50%/+100%/target  → trim 25% each
  Swing +half/target              → 50/50
  T+    target only               → all-or-nothing
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"


PARTIAL_PROFIT_RULES = {
    "core":   {"milestones_pct": [20, 50, 100], "trim_each_pct": 25,
               "final_at_target_pct": 25},
    "swing":  {"milestones_pct": [],  # filled per ticker (half-to-target)
               "trim_each_pct": 50, "final_at_target_pct": 50},
    "t_plus": {"milestones_pct": [],  # all-or-nothing
               "trim_each_pct": 100, "final_at_target_pct": 100},
}

TIME_STOP = {
    "core":   {"review_months": 12, "forced_exit_months": 18},
    "swing":  {"review_months": 6,  "forced_exit_months": 9},
    "t_plus": {"review_weeks": 3,   "forced_exit_weeks": 5},
}

TRAILING_ATR_MULT = {"core": 2.0, "swing": 1.5, "t_plus": 1.0}
TRAILING_ACTION = {"core": "trim_25pct_watch", "swing": "trim_50pct",
                   "t_plus": "exit_full"}


def _load_json(p: Path) -> dict | None:
    return json.loads(p.read_text()) if p.exists() else None


def _technical_stop_desc(mode: str, tech: dict) -> str:
    sma50 = tech.get("sma50")
    sma200 = tech.get("sma200")
    if mode == "core":
        return f"close < SMA200 (~{sma200:.2f}) sustained 2 weeks + fundamental confirm worsening"
    if mode == "swing":
        return f"close < swing_low_20 + 2 consecutive close-below + breakdown vol_ratio>1.0"
    if mode == "t_plus":
        return f"close < entry_candle_low OR close < SMA20 with vol_ratio>1.2"
    return "n/a"


def _fundamental_stop_desc(sector: str) -> list[str]:
    base = ["Earnings miss + guidance cut",
            "Debt rollover failure",
            "Audit qualifying opinion",
            "Restructuring announcement negative"]
    sector_specific = {
        "banking":     "NPL spike > sector threshold + NIM compression",
        "real_estate": "Presale velocity drop + OCF turning negative",
        "oil_gas":     "Brent < bottom 20%ile + crack spread compression",
        "steel":       "Iron ore < bottom 25%ile + inventory turnover < 2",
        "consumer":    "SSSG < -5% YoY 2 consecutive quarters",
        "tech":        "Revenue growth < 10% + margin compression",
        "securities":  "Margin debt ratio > 80% + liquidity falling",
    }.get(sector)
    return ([sector_specific] if sector_specific else []) + base


def build_plan(ticker: str, sector: str, mode: str, sizing: dict, tech: dict,
               catalyst: dict, valuation: dict) -> dict:
    entry_price = tech.get("close")
    atr = tech.get("atr14")
    primary_stop = sizing.get("inputs", {}).get("primary_stop") or tech.get("primary_stop")
    hard_stop = tech.get("hard_stop")

    # Targets
    primary_target = None
    secondary_target = None
    if mode == "core":
        primary_target = entry_price * 1.20 if entry_price else None
        secondary_target = entry_price * 1.50 if entry_price else None
    elif mode == "swing":
        # First resistance from entry zone target_ref, else +15%
        ez = (tech.get("entry_zones") or [{}])[0]
        primary_target = ez.get("target_ref") or (entry_price * 1.15 if entry_price else None)
        secondary_target = entry_price * 1.25 if entry_price else None
    elif mode == "t_plus":
        primary_target = entry_price * 1.07 if entry_price else None
        secondary_target = None

    # Time stop
    time_rule = TIME_STOP[mode]
    today = date.today()
    if mode == "t_plus":
        review_dt = today + timedelta(weeks=time_rule["review_weeks"])
        forced_dt = today + timedelta(weeks=time_rule["forced_exit_weeks"])
    else:
        review_dt = today + timedelta(days=30 * time_rule["review_months"])
        forced_dt = today + timedelta(days=30 * time_rule["forced_exit_months"])

    # Trailing rule
    trail_mult = TRAILING_ATR_MULT[mode]
    trail_action = TRAILING_ACTION[mode]

    return {
        "ticker": ticker,
        "sector": sector,
        "mode": mode,
        "as_of": today.isoformat(),
        "entry": {
            "entry_price_vnd": entry_price,
            "size_pct_nav": sizing.get("final_size_pct_nav"),
            "size_vnd": sizing.get("final_size_vnd"),
            "binding_constraint": sizing.get("binding_constraint"),
            "tier": sizing.get("tier"),
        },
        "catalyst": {
            "tier": (catalyst.get("aggregate") or {}).get("effective_tier"),
            "direction": (catalyst.get("aggregate") or {}).get("net_direction"),
            "n_catalysts": len(catalyst.get("catalysts") or []),
            "first": (catalyst.get("catalysts") or [None])[0],
        },
        "targets": {
            "primary_vnd": primary_target,
            "secondary_vnd": secondary_target,
        },
        "stops": {
            "1_fundamental": {
                "triggers": _fundamental_stop_desc(sector),
                "action": "exit_full",
            },
            "2_technical": {
                "desc": _technical_stop_desc(mode, tech),
                "action": "exit_full",
            },
            "3_time": {
                "review_date": review_dt.isoformat(),
                "forced_exit_date": forced_dt.isoformat(),
                "action": "exit_full_unless_extraordinary_evidence",
            },
            "4_kill_switch": {
                "triggers": [
                    "audit qualified opinion published",
                    "HOSE/UPCoM warning/control/suspended",
                    "CEO/Chairman/CFO khởi tố",
                    "UBCKNN manipulation order against ticker",
                ],
                "action": "exit_immediate",
            },
            "5_lai_escalate": {
                "desc": "Yellow→Red lai transition during hold",
                "action": "exit_regardless_of_pnl",
            },
            "6_trailing": {
                "atr_multiplier": trail_mult,
                "rule": f"high_since_entry - {trail_mult}×ATR14",
                "atr14": atr,
                "action_on_break": trail_action,
                "active_after_gain_pct": 20,
            },
        },
        "partial_profit": PARTIAL_PROFIT_RULES[mode],
        "loss_management": {
            "core":   {"-15": "monitor", "-20": "review_thesis", "-25_-30": "hard_review",
                       "-50": "forced_exit_unless_extraordinary"},
            "swing":  {"-15": "monitor", "-20": "review",
                       "-25_-30": "forced_exit", "-50": "n/a_should_have_exited"},
            "t_plus": {"-15": "forced_exit", "-20": "n/a", "-25_-30": "n/a", "-50": "n/a"},
        }[mode],
        "add_on_rules": {
            "current_gain_min_pct": 20,
            "require_thesis_intact": True,
            "require_new_catalyst": True,
            "require_sector_bullish_upgrade": True,
            "max_add_size_pct_of_original": 50,
            "ticker_cap_check": 25,
        },
        "re_entry_cool_down_days": 30,
    }


def write_journal_scaffold(plan: dict, out_dir: Path) -> Path:
    """Write trade journal yaml scaffold — user fills emotional/lesson fields."""
    journal = {
        "ticker": plan["ticker"],
        "sector": plan["sector"],
        "mode": plan["mode"],
        "entry_date": plan["as_of"],
        "entry_price_vnd": plan["entry"]["entry_price_vnd"],
        "size_pct_nav": plan["entry"]["size_pct_nav"],
        "size_vnd": plan["entry"]["size_vnd"],
        "conviction_tier": plan["entry"]["tier"],
        "catalyst": plan["catalyst"],
        "targets": plan["targets"],
        "stops": plan["stops"],
        "external_sources": [
            {"type": "news_link", "url": "<paste here>"},
            {"type": "ctck_report", "ref": "<paste here>"},
            {"type": "chart_screenshot", "path": f"data/screenshots/{plan['ticker']}_{plan['as_of']}.png"},
        ],
        "emotional_state_entry": "<calm|excited|reluctant|FOMO>",
        "emotional_state_during": [],
        "emotional_state_exit": "",
        "lesson_learned": "",
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    p = out_dir / f"{plan['ticker']}_{plan['as_of']}.yaml"
    with p.open("w", encoding="utf-8") as f:
        yaml.safe_dump(journal, f, allow_unicode=True, sort_keys=False)
    return p


def main() -> int:
    p = argparse.ArgumentParser(description="Layer 9 Entry/Exit Plan + Journal scaffold.")
    p.add_argument("--tickers", nargs="+")
    args = p.parse_args()

    today = date.today().isoformat()
    screen = _load_json(DATA / f"screen_{today}.json")
    if screen is None:
        print("[entry_exit] missing screen file. Run screen_watchlist.py first.", file=sys.stderr)
        return 2

    pass_tickers = [r["ticker"] for r in screen["results"] if r["verdict"] == "PASS"]
    tickers = args.tickers or pass_tickers
    if not tickers:
        print("[entry_exit] no PASS tickers from screen — nothing to plan.")
        return 0

    out_plan = DATA / "entry_plan"
    out_journal = DATA / "trade_journal"
    out_plan.mkdir(parents=True, exist_ok=True)
    out_journal.mkdir(parents=True, exist_ok=True)

    rows = []
    for t in tickers:
        screen_row = next((r for r in screen["results"] if r["ticker"] == t), None)
        sizing = _load_json(DATA / "sizing" / f"{t}.json")
        if not screen_row or not sizing or sizing.get("action") != "ENTRY":
            rows.append((t, "SKIPPED", f"sizing={sizing.get('action') if sizing else 'missing'}"))
            continue
        tech = _load_json(DATA / "technical" / f"{t}.json") or {}
        cat = _load_json(DATA / "catalyst" / f"{t}.json") or {}
        val = _load_json(DATA / "valuation" / f"{t}.json") or {}
        sector = screen_row.get("sector", "unknown")
        mode = screen_row.get("best_mode")
        plan = build_plan(t, sector, mode, sizing, tech, cat, val)
        (out_plan / f"{t}.json").write_text(json.dumps(plan, ensure_ascii=False, indent=2))
        jp = write_journal_scaffold(plan, out_journal)
        rows.append((t, "PLAN_BUILT", f"size={plan['entry']['size_pct_nav']}% target={plan['targets']['primary_vnd']}"))

    print(f"\n[entry_exit] {len(rows)} processed → {out_plan}, journal → {out_journal}\n")
    for row in rows:
        print(f"  {row[0]:8s} {row[1]:14s} {row[2]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
