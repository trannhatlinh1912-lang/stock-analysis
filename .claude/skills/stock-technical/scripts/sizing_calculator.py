"""Layer 8 — Sizing Calculator with immutable cap chain (Guardrail 4).

Inputs per ticker:
  - mode (core/swing/t_plus)
  - tier (1-7 per L5 + L7 mapping)
  - entry_price + primary_stop_price (for Van Tharp risk_per_share)
  - ATR pct (current)
  - sector regime modifier
  - portfolio state (NAV, current positions, sector allocations)
  - Layer 2 nav_deploy_cap_pct
  - Layer 7 lai status (Red → SKIP)

Output:
  - final_size_pct_nav
  - binding_constraint (which cap dominated)
  - size_calculation_trace with after_X values
  - REJECT if size <= 0 or Red lái

Cap order (immutable):
  1. liquidity floor (5% if illiquid)
  2. mode cap (Core 20 / Swing 15 / T+ 10)
  3. sector cap (50%)
  4. NAV deploy cap (regime-dependent)
  5. single ticker cap (25%)
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


# Constants per L8 spec
RISK_PER_TRADE_NAV_PCT = 1.0
MODE_CAP = {"core": 20.0, "swing": 15.0, "t_plus": 10.0}
SECTOR_CAP_PCT = 50.0
TICKER_CAP_PCT = 25.0
CASH_BUFFER_MIN_PCT = 10.0
# Counter-trend value (tier 8, falling-knife): hard ceiling so a tight ATR
# stop can't inflate a no-technical entry. Keeps the bet a probe, not a stake.
COUNTER_TREND_CAP_PCT = 4.0

# Conviction modifier per tier (L8 spec)
TIER_MODIFIER = {
    1: 2.0,   # Core deep value + Hard catalyst
    2: 1.6,   # Core fair value + Medium catalyst
    3: 1.4,   # Swing val + tech confirm
    4: 1.2,   # Swing tech only
    5: 1.0,   # T+ standard
    6: 0.5,   # Yellow lái
    7: None,  # Red lái — SKIP
    8: 0.5,   # Swing val + catalyst, NO technical — counter-trend value
              # ("falling knife"): allowed but smallest size, no chasing.
}

# Sector ATR thresholds (calibrated v2.5/v2.6 — use defaults if not present)
DEFAULT_ATR_PCT_LOW = 1.5
DEFAULT_ATR_PCT_HIGH = 4.0


def assign_tier(
    mode: str,
    catalyst_tier: str | None,
    valuation_pass: bool,
    technical_pass: bool,
    lai_level: str,
) -> int | None:
    """Map (mode, catalyst, val, tech, lai) → tier 1-7.

    Red lái → 7 (SKIP). Yellow lái → 6 (max).
    Core deep value (val pass) + Hard → 1.
    Core fair value (val mid) + Medium → 2.
    Swing val + tech → 3.
    Swing tech only → 4.
    T+ standard → 5.
    """
    if lai_level == "red":
        return 7
    if lai_level == "yellow":
        return 6
    if mode == "core":
        if catalyst_tier == "hard" and valuation_pass:
            return 1
        if catalyst_tier in ("hard", "medium") and (valuation_pass or technical_pass):
            return 2
        return None  # Core requires catalyst + at least one pass
    if mode == "swing":
        if catalyst_tier in ("hard", "medium") and valuation_pass and technical_pass:
            return 3
        if technical_pass:
            return 4
        # Counter-trend value: cheap + real catalyst but technical not yet
        # confirmed (e.g. DISTRIBUTION). Allowed as a deliberate falling-knife
        # entry, but smallest conviction (tier 8 = 0.5x) so size stays tiny.
        if catalyst_tier in ("hard", "medium") and valuation_pass:
            return 8
        return None
    if mode == "t_plus":
        if technical_pass:
            return 5
        return None
    return None


def atr_scale(atr_pct: float | None, low: float, high: float) -> float:
    if atr_pct is None or atr_pct <= 0:
        return 1.0
    if atr_pct <= low:
        return 1.0
    if atr_pct >= high:
        return low / atr_pct
    # Linear interp from 1.0 down toward low/high ratio
    return 1.0 - (atr_pct - low) / (high - low) * (1 - low / high)


def van_tharp_base_pct(entry: float, primary_stop: float) -> float | None:
    if entry is None or primary_stop is None or entry <= 0 or primary_stop <= 0:
        return None
    risk_per_share_pct = (entry - primary_stop) / entry * 100
    if risk_per_share_pct <= 0:
        return None
    return RISK_PER_TRADE_NAV_PCT / risk_per_share_pct * 100


def _liquidity_ok(adtv_b_vnd: float | None, mode: str) -> bool:
    if adtv_b_vnd is None:
        return False
    if mode == "t_plus":
        return adtv_b_vnd >= 5.0
    return adtv_b_vnd >= 1.0


def _liquidity_cap(adtv_b_vnd: float | None) -> float:
    """If illiquid (below floor), cap at 5%. Else no extra cap."""
    if adtv_b_vnd is None or adtv_b_vnd < 1.0:
        return 5.0
    return float("inf")


def calculate(
    ticker: str,
    mode: str,
    tier: int,
    entry_price: float,
    primary_stop: float,
    atr_pct: float | None,
    adtv_b_vnd: float | None,
    sector: str,
    portfolio: dict,
    nav_deploy_cap_pct: float,
) -> dict:
    trace: dict[str, Any] = {
        "ticker": ticker, "mode": mode, "tier": tier,
        "inputs": {
            "entry_price": entry_price, "primary_stop": primary_stop,
            "atr_pct": atr_pct, "adtv_b_vnd": adtv_b_vnd,
            "sector": sector, "nav_deploy_cap_pct": nav_deploy_cap_pct,
        },
    }

    modifier = TIER_MODIFIER.get(tier)
    if modifier is None:
        trace["action"] = "REJECT"
        trace["reason"] = "tier_7_red_lai_no_entry"
        return trace

    base = van_tharp_base_pct(entry_price, primary_stop)
    if base is None:
        trace["action"] = "REJECT"
        trace["reason"] = "van_tharp_input_invalid"
        return trace

    atr_factor = atr_scale(atr_pct, DEFAULT_ATR_PCT_LOW, DEFAULT_ATR_PCT_HIGH)

    sizes = {"base_pct": base, "after_conviction": base * modifier}
    sizes["after_atr"] = sizes["after_conviction"] * atr_factor

    # Cap chain (immutable order)
    binding = None

    size_pre = sizes["after_atr"]
    if tier == 8:
        size_ct = min(size_pre, COUNTER_TREND_CAP_PCT)
        if size_ct < size_pre:
            binding = "counter_trend_cap"
        size_pre = size_ct
    sizes["after_counter_trend_cap"] = size_pre

    cap_liq = _liquidity_cap(adtv_b_vnd)
    size_liq = min(size_pre, cap_liq)
    if size_liq < size_pre:
        binding = "liquidity"
    sizes["after_liquidity"] = size_liq

    cap_mode = MODE_CAP[mode]
    size_mode = min(size_liq, cap_mode)
    if size_mode < size_liq:
        binding = "mode_cap"
    sizes["after_mode_cap"] = size_mode

    sector_curr = (portfolio.get("sector_allocations_pct_nav") or {}).get(sector, 0)
    sector_remaining = max(0.0, SECTOR_CAP_PCT - sector_curr)
    size_sec = min(size_mode, sector_remaining)
    if size_sec < size_mode:
        binding = "sector_cap"
    sizes["after_sector_cap"] = size_sec

    nav_curr = portfolio.get("total_deployed_pct_nav", 0) or 0
    nav_remaining = max(0.0, nav_deploy_cap_pct - nav_curr)
    size_nav = min(size_sec, nav_remaining)
    if size_nav < size_sec:
        binding = "nav_cap"
    sizes["after_nav_cap"] = size_nav

    ticker_curr = 0
    for pos in portfolio.get("positions", []) or []:
        if pos.get("ticker") == ticker:
            ticker_curr += pos.get("size_pct_nav", 0)
    ticker_remaining = max(0.0, TICKER_CAP_PCT - ticker_curr)
    size_final = min(size_nav, ticker_remaining)
    if size_final < size_nav:
        binding = "ticker_cap"
    sizes["after_ticker_cap"] = size_final
    sizes["final"] = size_final

    nav_vnd = portfolio.get("nav_total_vnd", 0)
    final_size_vnd = round(size_final / 100 * nav_vnd)

    if size_final <= 0:
        action = "REJECT"
        reason = f"all_caps_exhausted (binding={binding})"
    else:
        action = "ENTRY"
        reason = f"binding_constraint={binding or 'van_tharp_base'}"

    trace.update({
        "conviction_modifier": modifier,
        "atr_scale": round(atr_factor, 4),
        "size_calculation_trace": {k: round(v, 4) for k, v in sizes.items()},
        "binding_constraint": binding,
        "final_size_pct_nav": round(size_final, 3),
        "final_size_vnd": final_size_vnd,
        "action": action,
        "reason": reason,
    })
    if tier == 8 and action == "ENTRY":
        trace["warnings"] = [
            "counter_trend_value: technical NOT confirmed (e.g. distribution). "
            "Falling-knife entry — smallest size (0.5x), tight stop mandatory, "
            "scale in only on technical confirmation. Do not average down."
        ]
    return trace


def _read_portfolio() -> dict:
    env = load_manual(CONFIGS / "portfolio.yaml", "portfolio")
    return env["data"] or {}


def _load_json(p: Path) -> dict | None:
    return json.loads(p.read_text()) if p.exists() else None


def main() -> int:
    p = argparse.ArgumentParser(description="Layer 8 Sizing Calculator batch.")
    p.add_argument("--tickers", nargs="+",
                   help="Default: tickers that PASS L1-L6 from latest screen.")
    args = p.parse_args()

    today = date.today().isoformat()
    screen = _load_json(DATA / f"screen_{today}.json")
    if screen is None:
        print(f"[sizing] no screen_{today}.json. Run screen_watchlist.py first.", file=sys.stderr)
        return 2

    l2 = _load_json(DATA / f"market_regime_{today}.json")
    nav_cap = (l2 or {}).get("nav_deploy_cap_pct", 70)
    portfolio = _read_portfolio()

    pass_tickers = [r["ticker"] for r in screen["results"] if r["verdict"] == "PASS"]
    tickers = args.tickers or pass_tickers

    out_dir = DATA / "sizing"
    out_dir.mkdir(parents=True, exist_ok=True)

    rows = []
    for t in tickers:
        result_row = next((r for r in screen["results"] if r["ticker"] == t), None)
        if not result_row:
            continue
        mode = result_row.get("best_mode")
        if not mode:
            continue

        tech = _load_json(DATA / "technical" / f"{t}.json") or {}
        liq = _load_json(DATA / "liquidity" / f"{t}.json") or {}
        l5 = _load_json(DATA / "catalyst" / f"{t}.json") or {}
        l7 = _load_json(DATA / "lai" / f"{t}.json") or {}
        val = _load_json(DATA / "valuation" / f"{t}.json") or {}

        catalyst_tier = (l5.get("aggregate") or {}).get("effective_tier")
        valuation_pass = val.get("valuation_pass", False)
        technical_pass = (tech.get("mode_pass") or {}).get(mode, {}).get("pass", False)
        lai_level = (l7.get("warning_level_per_mode") or {}).get(mode, "green")

        tier = assign_tier(mode, catalyst_tier, valuation_pass, technical_pass, lai_level)
        if tier is None:
            (out_dir / f"{t}.json").write_text(json.dumps({
                "ticker": t, "mode": mode, "action": "REJECT",
                "reason": "no_tier_match",
                "inputs": {"catalyst_tier": catalyst_tier, "val": valuation_pass,
                           "tech": technical_pass, "lai": lai_level},
            }, ensure_ascii=False, indent=2))
            rows.append((t, mode, "-", "REJECT", "no_tier"))
            continue

        entry_price = tech.get("close")
        primary_stop = tech.get("primary_stop")
        if primary_stop is None and tech.get("entry_zones"):
            primary_stop = tech["entry_zones"][0].get("entry_ref", entry_price) * 0.95
        atr_pct = tech.get("atr_pct")
        adtv = liq.get("adtv_20d_b_vnd")
        sector = result_row.get("sector", "unknown")

        r = calculate(t, mode, tier, entry_price, primary_stop, atr_pct, adtv,
                      sector, portfolio, nav_cap)
        (out_dir / f"{t}.json").write_text(json.dumps(r, ensure_ascii=False, indent=2))
        rows.append((t, mode, str(tier), r.get("action"),
                     f"{r.get('final_size_pct_nav', 0):.2f}% (bind={r.get('binding_constraint')})"))

    print(f"\n[sizing] {len(rows)} tickers processed → {out_dir}\n")
    print(f"  {'TICKER':8s} {'MODE':8s} {'TIER':5s} {'ACTION':8s} RESULT")
    for row in rows:
        print(f"  {row[0]:8s} {row[1]:8s} {row[2]:5s} {row[3]:8s} {row[4]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
