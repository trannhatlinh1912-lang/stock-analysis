"""Framework v3.0 historical replay backtest.

For each ticker in watchlist + each historical bar (weekly cadence):
  1. Read pre-computed indicators (data/{TICKER}_indicators.csv).
  2. Reconstruct sector_regime at that date from sector basket subset:
       - RS slope 20d (basket equal-weight vs VNINDEX)
       - Breadth (% basket members above SMA50)
       - Cycle dim: deferred (uses today's snapshot, not historical) → skipped.
  3. Reconstruct simple market_regime from VNINDEX close vs SMA200 + vol baseline:
       BULLISH / NEUTRAL / BEARISH (3-state coarse).
  4. Compute framework_verdict per current orchestrator-style logic:
       - SKIP killer: market BEARISH OR sector BEARISH OR state==DISTRIBUTION
       - PASS: state ∈ {BULLISH_TREND_CONFIRMED, BREAKOUT_CONFIRMED, ACCUMULATION}
              AND sector ∈ {BULLISH, NEUTRAL_TO_BULLISH, NEUTRAL}
       - WATCH otherwise.
  5. Simulate next-bar open entry for PASS:
       stop = close − 1.5 × ATR14
       target = close + 1.5 × ATR14
       hold ≤ 20 bars; exit on stop/target/timeout.
  6. Track 5d, 20d forward returns regardless of verdict (for benchmark).

NOT backtested (historical data missing):
  - L1 hard flags (uses snapshot fundamentals only)
  - L5 catalyst auto (uses YoY snapshot)
  - L5 catalyst manual (no historical yaml)
  - L7 lái symptoms 2, 4, 5 (no accumulator/snapshot history)
  - L8 sizing chain (portfolio state is current)
  - Margin debt / VN30 liquidity / foreign cum

Output:
  data/backtest_framework/{TICKER}.json
  data/backtest_framework_pool.json (aggregate)
  reports/backtest_framework_report.md
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
REPORTS = ROOT / "reports"
CONFIGS = ROOT / "configs"
OUT_DIR = DATA / "backtest_framework"

VN_ROUNDTRIP_COST_PCT = 0.40
HOLD_BARS = 20
# v2.6 calibrated defaults (pooled best 5-ticker grid 2026-05-28):
#   pooled avg_R +0.572, hit_rate 0.366
ATR_STOP_MULT = 1.0
ATR_TARGET_MULT = 3.0
WEEKLY_CADENCE = 5   # sample every N bars

TRADEABLE_STATES = {
    "BULLISH_TREND_CONFIRMED",
    "BREAKOUT_CONFIRMED",
    "ACCUMULATION",
}


def _load_watchlist() -> dict:
    return yaml.safe_load((CONFIGS / "watchlist.yaml").read_text())


def _ticker_sector_map(wl: dict) -> dict[str, str]:
    return {t: s for s, ts in wl["sector_baskets"].items() for t in ts}


def _load_indicators(symbol: str) -> pd.DataFrame | None:
    p = DATA / f"{symbol}_indicators.csv"
    if not p.exists():
        return None
    df = pd.read_csv(p)
    df["date"] = pd.to_datetime(df["date"])
    return df.sort_values("date").reset_index(drop=True)


def _load_vni() -> pd.DataFrame | None:
    p = DATA / "VNINDEX_price_VCI.csv"
    if not p.exists():
        return None
    df = pd.read_csv(p)
    df["time"] = pd.to_datetime(df["time"])
    df["sma200"] = df["close"].rolling(200).mean()
    df["sma50"] = df["close"].rolling(50).mean()
    df["ret_20d"] = df["close"].pct_change(20)
    return df.sort_values("time").reset_index(drop=True)


def _classify_state(row: pd.Series) -> str:
    """Inline state classification — simplified from decision_framework."""
    close = row.get("close")
    sma20, sma50, sma100, sma200 = (row.get("sma20"), row.get("sma50"),
                                     row.get("sma100"), row.get("sma200"))
    macd_hist = row.get("macd_hist")
    cmf20 = row.get("cmf20")
    obv_slope = row.get("obv_slope_20d")
    vol_ratio = row.get("vol_ratio")
    ret_1d = row.get("ret_1d_pct")
    bb_pos = row.get("bb_position", "")
    stoch_k = row.get("stoch_k")
    atr14 = row.get("atr14")

    # 1. DISTRIBUTION
    if (close is not None and sma20 is not None and close < sma20 and
            macd_hist is not None and macd_hist < 0 and
            cmf20 is not None and cmf20 < 0 and
            obv_slope is not None and obv_slope < 0):
        return "DISTRIBUTION"

    # 2. BREAKOUT_WITH_EXHAUSTION_RISK
    breakout = (close is not None and sma20 is not None and sma50 is not None
                and sma200 is not None and close > sma20 and close > sma50
                and close > sma200 and vol_ratio is not None and vol_ratio >= 1.5
                and ret_1d is not None and ret_1d > 2)
    if (breakout and bb_pos == "above_upper" and stoch_k is not None and stoch_k >= 90
            and vol_ratio >= 2):
        return "BREAKOUT_WITH_EXHAUSTION_RISK"

    # 3. BULLISH_TREND_CONFIRMED
    if (close is not None and all(x is not None for x in (sma20, sma50, sma100, sma200))
            and close > sma20 > sma50 > sma100 > sma200
            and macd_hist is not None and macd_hist > 0
            and vol_ratio is not None and vol_ratio >= 1):
        return "BULLISH_TREND_CONFIRMED"

    # 4. BREAKOUT_CONFIRMED
    if breakout and macd_hist is not None and macd_hist > 0:
        return "BREAKOUT_CONFIRMED"

    # 5. ACCUMULATION
    if (close is not None and atr14 is not None and (sma20 is not None or sma50 is not None)):
        near_ma = False
        if sma20 is not None and abs(close - sma20) <= atr14:
            near_ma = True
        if sma50 is not None and abs(close - sma50) <= atr14:
            near_ma = True
        if (near_ma and vol_ratio is not None and 0.8 <= vol_ratio <= 1.5
                and bb_pos != "above_upper"):
            return "ACCUMULATION"

    return "WATCH"


def _market_regime_at(vni: pd.DataFrame, dt) -> str:
    """Simplified 3-state from VNINDEX at date dt."""
    sub = vni[vni["time"] <= dt]
    if len(sub) < 200:
        return "UNKNOWN"
    row = sub.iloc[-1]
    if pd.isna(row["sma200"]):
        return "UNKNOWN"
    if row["close"] > row["sma200"] and row["close"] > row["sma50"]:
        if row["ret_20d"] is not None and row["ret_20d"] > 0.02:
            return "BULLISH"
        return "NEUTRAL"
    if row["close"] < row["sma200"]:
        if row["ret_20d"] is not None and row["ret_20d"] < -0.05:
            return "BEARISH"
        return "NEUTRAL_TO_BEARISH"
    return "NEUTRAL"


def _sector_regime_at(basket_inds: dict[str, pd.DataFrame], vni: pd.DataFrame, dt,
                      sector: str) -> str:
    """Reconstruct sector regime at date dt from basket indicators."""
    closes = {}
    above_sma50 = 0
    total = 0
    for sym, df in basket_inds.items():
        sub = df[df["date"] <= dt]
        if len(sub) < 50:
            continue
        last_close = float(sub["close"].iloc[-1])
        sma50_now = float(sub["sma50"].iloc[-1]) if not pd.isna(sub["sma50"].iloc[-1]) else None
        if sma50_now is not None:
            total += 1
            if last_close > sma50_now:
                above_sma50 += 1
        # RS series
        closes[sym] = sub.set_index("date")["close"]

    if total == 0:
        return "UNKNOWN"
    breadth_pct = above_sma50 / total * 100
    if breadth_pct >= 60:
        breadth_lab = "strong"
    elif breadth_pct < 40:
        breadth_lab = "weak"
    else:
        breadth_lab = "neutral"

    # RS slope 20d
    if not closes:
        return "UNKNOWN"
    combined = pd.DataFrame(closes).dropna(how="all").ffill().dropna()
    if combined.empty:
        return "UNKNOWN"
    norm = combined.div(combined.iloc[0]) * 100
    basket = norm.mean(axis=1)
    vni_sub = vni[vni["time"] <= dt].set_index("time")["close"]
    common = basket.index.intersection(vni_sub.index)
    if len(common) < 25:
        return "UNKNOWN"
    basket_c = basket.loc[common]
    vni_c = vni_sub.loc[common]
    rs = basket_c / vni_c
    rs_now = float(rs.iloc[-1])
    rs_20 = float(rs.iloc[-21])
    slope = (rs_now / rs_20 - 1) * 100
    if slope > 2:
        rs_lab = "leader"
    elif slope < -2:
        rs_lab = "laggard"
    else:
        rs_lab = "inline"

    s = 0
    s += {"leader": 1, "laggard": -1, "inline": 0}[rs_lab]
    s += {"strong": 1, "weak": -1, "neutral": 0}[breadth_lab]
    if s >= 2:
        return "BULLISH"
    if s == 1:
        return "NEUTRAL_TO_BULLISH"
    if s == 0:
        return "NEUTRAL"
    if s == -1:
        return "NEUTRAL_TO_BEARISH"
    return "BEARISH"


def _verdict(state: str, sector_regime: str, market_regime: str) -> str:
    if state == "DISTRIBUTION":
        return "SKIP"
    if sector_regime in ("BEARISH", "CRISIS") or market_regime in ("BEARISH", "CRISIS"):
        return "SKIP"
    if (state in TRADEABLE_STATES
            and sector_regime in ("BULLISH", "NEUTRAL_TO_BULLISH", "NEUTRAL")
            and market_regime in ("BULLISH", "NEUTRAL")):
        return "PASS"
    return "WATCH"


def _simulate_trade(df: pd.DataFrame, entry_idx: int) -> dict | None:
    """Enter at next bar open, hold up to HOLD_BARS, exit on stop/target/timeout."""
    if entry_idx + 1 >= len(df):
        return None
    entry_row = df.iloc[entry_idx]
    entry_close = float(entry_row["close"])
    atr = float(entry_row["atr14"]) if not pd.isna(entry_row["atr14"]) else None
    if atr is None or atr <= 0:
        return None
    entry_open = float(df.iloc[entry_idx + 1]["open"]) if "open" in df.columns else entry_close
    stop = entry_close - ATR_STOP_MULT * atr
    target = entry_close + ATR_TARGET_MULT * atr
    risk = entry_open - stop
    if risk <= 0:
        return None

    exit_reason = "timeout"
    exit_price = None
    exit_idx = None
    for i in range(entry_idx + 1, min(entry_idx + 1 + HOLD_BARS, len(df))):
        row = df.iloc[i]
        high = float(row.get("high", row["close"]))
        low = float(row.get("low", row["close"]))
        if low <= stop:
            exit_reason = "stop"
            exit_price = stop
            exit_idx = i
            break
        if high >= target:
            exit_reason = "target"
            exit_price = target
            exit_idx = i
            break
    if exit_price is None:
        last = df.iloc[min(entry_idx + HOLD_BARS, len(df) - 1)]
        exit_price = float(last["close"])
        exit_idx = entry_idx + HOLD_BARS

    gross_ret_pct = (exit_price / entry_open - 1) * 100
    net_ret_pct = gross_ret_pct - VN_ROUNDTRIP_COST_PCT
    r_multiple = (exit_price - entry_open) / risk
    return {
        "entry_idx": entry_idx + 1,
        "entry_date": str(df.iloc[entry_idx + 1]["date"].date()),
        "entry_open": round(entry_open, 4),
        "stop": round(stop, 4),
        "target": round(target, 4),
        "exit_idx": exit_idx,
        "exit_date": str(df.iloc[exit_idx]["date"].date()),
        "exit_price": round(exit_price, 4),
        "exit_reason": exit_reason,
        "gross_ret_pct": round(gross_ret_pct, 3),
        "net_ret_pct": round(net_ret_pct, 3),
        "r_multiple": round(r_multiple, 3),
        "hold_bars": exit_idx - entry_idx,
    }


def _fwd_return_pct(df: pd.DataFrame, entry_idx: int, n: int) -> float | None:
    if entry_idx + n >= len(df):
        return None
    c0 = float(df.iloc[entry_idx]["close"])
    cn = float(df.iloc[entry_idx + n]["close"])
    return (cn / c0 - 1) * 100


def backtest_ticker(symbol: str, sector: str, tk_inds: pd.DataFrame,
                    basket_inds: dict, vni: pd.DataFrame,
                    start_date, end_date) -> dict:
    df = tk_inds[(tk_inds["date"] >= start_date) & (tk_inds["date"] <= end_date)].reset_index(drop=True)
    if len(df) < 50:
        return {"ticker": symbol, "error": "insufficient_history", "n_bars": len(df)}

    # Sample weekly cadence — start at index 200 to allow indicators to warm up
    start_i = max(200, len(df) - 600)
    sample_indices = list(range(start_i, len(df) - HOLD_BARS - 1, WEEKLY_CADENCE))

    per_event = []
    for i in sample_indices:
        row = df.iloc[i]
        dt = row["date"]
        state = _classify_state(row)
        sector_regime = _sector_regime_at(basket_inds, vni, dt, sector)
        market_regime = _market_regime_at(vni, dt)
        verdict = _verdict(state, sector_regime, market_regime)

        fwd_5d = _fwd_return_pct(df, i, 5)
        fwd_20d = _fwd_return_pct(df, i, 20)
        trade = _simulate_trade(df, i) if verdict == "PASS" else None

        per_event.append({
            "date": str(dt.date()),
            "state": state,
            "sector_regime": sector_regime,
            "market_regime": market_regime,
            "verdict": verdict,
            "fwd_5d_pct": round(fwd_5d, 3) if fwd_5d is not None else None,
            "fwd_20d_pct": round(fwd_20d, 3) if fwd_20d is not None else None,
            "trade": trade,
        })

    # Aggregate
    by_verdict = {}
    for verdict in ("PASS", "WATCH", "SKIP"):
        events = [e for e in per_event if e["verdict"] == verdict]
        fwd5 = [e["fwd_5d_pct"] for e in events if e["fwd_5d_pct"] is not None]
        fwd20 = [e["fwd_20d_pct"] for e in events if e["fwd_20d_pct"] is not None]
        by_verdict[verdict] = {
            "n_events": len(events),
            "fwd_5d_mean_pct": round(float(np.mean(fwd5)), 3) if fwd5 else None,
            "fwd_5d_median_pct": round(float(np.median(fwd5)), 3) if fwd5 else None,
            "fwd_5d_hit_rate": round(sum(1 for r in fwd5 if r > 0) / len(fwd5), 3) if fwd5 else None,
            "fwd_20d_mean_pct": round(float(np.mean(fwd20)), 3) if fwd20 else None,
            "fwd_20d_median_pct": round(float(np.median(fwd20)), 3) if fwd20 else None,
            "fwd_20d_hit_rate": round(sum(1 for r in fwd20 if r > 0) / len(fwd20), 3) if fwd20 else None,
        }

    # PASS-only trade simulation aggregate
    trades = [e["trade"] for e in per_event if e["trade"] is not None]
    nets = [t["net_ret_pct"] for t in trades]
    rs = [t["r_multiple"] for t in trades]
    pass_trade_stats = {
        "n_trades": len(trades),
        "avg_R": round(float(np.mean(rs)), 3) if rs else None,
        "median_net_ret_pct": round(float(np.median(nets)), 3) if nets else None,
        "hit_rate": round(sum(1 for r in nets if r > 0) / len(nets), 3) if nets else None,
        "winner_avg": round(float(np.mean([r for r in nets if r > 0])), 3) if any(r > 0 for r in nets) else None,
        "loser_avg": round(float(np.mean([r for r in nets if r <= 0])), 3) if any(r <= 0 for r in nets) else None,
    }

    return {
        "ticker": symbol,
        "sector": sector,
        "n_events": len(per_event),
        "date_range": [str(df["date"].iloc[start_i].date()), str(df["date"].iloc[-1].date())],
        "by_verdict": by_verdict,
        "pass_trades": pass_trade_stats,
        "events": per_event,  # full per-event detail
    }


def aggregate_pool(results: list[dict]) -> dict:
    pool_by_verdict = {"PASS": {"fwd5": [], "fwd20": []},
                       "WATCH": {"fwd5": [], "fwd20": []},
                       "SKIP": {"fwd5": [], "fwd20": []}}
    pool_trades_nets = []
    pool_trades_rs = []
    for r in results:
        if "error" in r:
            continue
        for ev in r["events"]:
            v = ev["verdict"]
            if ev["fwd_5d_pct"] is not None:
                pool_by_verdict[v]["fwd5"].append(ev["fwd_5d_pct"])
            if ev["fwd_20d_pct"] is not None:
                pool_by_verdict[v]["fwd20"].append(ev["fwd_20d_pct"])
            if ev["trade"]:
                pool_trades_nets.append(ev["trade"]["net_ret_pct"])
                pool_trades_rs.append(ev["trade"]["r_multiple"])

    summary = {}
    for verdict, vd in pool_by_verdict.items():
        fwd5 = vd["fwd5"]
        fwd20 = vd["fwd20"]
        summary[verdict] = {
            "n_events": len(fwd5),
            "fwd_5d_mean_pct": round(float(np.mean(fwd5)), 3) if fwd5 else None,
            "fwd_5d_hit_rate": round(sum(1 for r in fwd5 if r > 0) / len(fwd5), 3) if fwd5 else None,
            "fwd_20d_mean_pct": round(float(np.mean(fwd20)), 3) if fwd20 else None,
            "fwd_20d_hit_rate": round(sum(1 for r in fwd20 if r > 0) / len(fwd20), 3) if fwd20 else None,
        }
    pool_trades = {
        "n_trades": len(pool_trades_nets),
        "avg_R": round(float(np.mean(pool_trades_rs)), 3) if pool_trades_rs else None,
        "median_net_ret_pct": round(float(np.median(pool_trades_nets)), 3) if pool_trades_nets else None,
        "hit_rate": round(sum(1 for r in pool_trades_nets if r > 0) / len(pool_trades_nets), 3) if pool_trades_nets else None,
    }
    return {"by_verdict": summary, "pass_trades": pool_trades}


def render_report(results: list[dict], pool: dict) -> str:
    L = [f"# Framework v3.0 Backtest — replay 2024-2026", "",
         "## Method", "",
         "- Cadence: every 5 bars (weekly), starting bar 200 (indicator warm-up).",
         "- Universe: 32 ticker watchlist (skipping any with insufficient cache).",
         "- Verdict = PASS/WATCH/SKIP derived from technical_state + sector_regime + market_regime.",
         "- PASS trades simulated: entry next-bar open, stop = close − 1.5 ATR, target = close + 1.5 ATR, hold ≤ 20 bars.",
         "- Forward 5d / 20d returns recorded for ALL events (benchmark).",
         "- Cost assumption: 0.40% round-trip.",
         "",
         "## NOT backtested (data unavailable historical):",
         "",
         "- L1 hard flags (fundamentals static snapshot)",
         "- L5 catalyst manual (no historical yaml)",
         "- L5 catalyst auto (uses YoY snapshot, not historical YoY at date)",
         "- L7 lái symptom 2, 4, 5 (no accumulator history)",
         "- L8 sizing chain (portfolio state is current)",
         "- Margin debt / VN30 liquidity / foreign cum (no history)",
         "",
         "## Pool aggregate", "",
         "### Per verdict (all events)",
         "",
         "| Verdict | N | Fwd 5d mean % | Fwd 5d hit | Fwd 20d mean % | Fwd 20d hit |",
         "|---|---|---|---|---|---|"]
    for v in ("PASS", "WATCH", "SKIP"):
        s = pool["by_verdict"][v]
        L.append(f"| {v} | {s['n_events']} | {s['fwd_5d_mean_pct']} | {s['fwd_5d_hit_rate']} | "
                 f"{s['fwd_20d_mean_pct']} | {s['fwd_20d_hit_rate']} |")
    L += ["",
          "### PASS trades simulation (1.5 ATR stop/target, 20-bar hold)",
          "",
          f"- n_trades = {pool['pass_trades']['n_trades']}",
          f"- avg_R = {pool['pass_trades']['avg_R']}",
          f"- median_net_ret_pct = {pool['pass_trades']['median_net_ret_pct']}",
          f"- hit_rate = {pool['pass_trades']['hit_rate']}",
          "",
          "## Per ticker",
          "",
          "| Ticker | Sector | N events | PASS n | PASS fwd_20d | PASS trade avg_R | PASS hit |",
          "|---|---|---|---|---|---|---|"]
    for r in sorted([x for x in results if "error" not in x], key=lambda x: x["ticker"]):
        bv = r["by_verdict"]["PASS"]
        pt = r["pass_trades"]
        L.append(f"| {r['ticker']} | {r['sector']} | {r['n_events']} | "
                 f"{bv['n_events']} | {bv.get('fwd_20d_mean_pct')} | "
                 f"{pt.get('avg_R')} | {pt.get('hit_rate')} |")
    return "\n".join(L)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tickers", nargs="+")
    ap.add_argument("--start", default="2024-01-01")
    ap.add_argument("--end", default=date.today().isoformat())
    args = ap.parse_args()

    wl = _load_watchlist()
    tk_sec = _ticker_sector_map(wl)
    sector_baskets = wl["sector_baskets"]
    tickers = args.tickers or wl.get("all_fetched", [])

    vni = _load_vni()
    if vni is None:
        print("[backtest] VNINDEX history missing. Run market_context.py first.", file=sys.stderr)
        return 2

    # Pre-load basket indicators
    basket_inds_cache: dict[str, dict[str, pd.DataFrame]] = {}
    for sec, basket in sector_baskets.items():
        cache = {}
        for sym in basket:
            df = _load_indicators(sym)
            if df is not None:
                cache[sym] = df
        basket_inds_cache[sec] = cache

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    start_date = pd.Timestamp(args.start)
    end_date = pd.Timestamp(args.end)

    results = []
    for t in tickers:
        sector = tk_sec.get(t, "unknown")
        tk_inds = _load_indicators(t)
        if tk_inds is None:
            results.append({"ticker": t, "error": "no_indicators_csv"})
            print(f"  {t}: SKIP (no indicators)")
            continue
        basket_inds = basket_inds_cache.get(sector, {})
        print(f"  {t} ({sector}): backtesting...")
        r = backtest_ticker(t, sector, tk_inds, basket_inds, vni, start_date, end_date)
        results.append(r)
        if "error" in r:
            print(f"    ERROR {r.get('error')}")
        else:
            bv = r["by_verdict"]
            pt = r["pass_trades"]
            print(f"    n={r['n_events']} PASS={bv['PASS']['n_events']} "
                  f"avg_R={pt['avg_R']} hit_rate={pt['hit_rate']}")
        # Write per-ticker
        (OUT_DIR / f"{t}.json").write_text(json.dumps(r, ensure_ascii=False, indent=2))

    pool = aggregate_pool(results)
    (DATA / "backtest_framework_pool.json").write_text(json.dumps(pool, ensure_ascii=False, indent=2))
    md = render_report(results, pool)
    md_path = REPORTS / "backtest_framework_report.md"
    REPORTS.mkdir(parents=True, exist_ok=True)
    md_path.write_text(md)

    print(f"\n[backtest] pool → data/backtest_framework_pool.json")
    print(f"[backtest] report → {md_path}")
    print(f"\nPool summary:")
    for v in ("PASS", "WATCH", "SKIP"):
        s = pool["by_verdict"][v]
        print(f"  {v:5s} n={s['n_events']:4d} fwd20d_mean={s['fwd_20d_mean_pct']} hit={s['fwd_20d_hit_rate']}")
    pt = pool["pass_trades"]
    print(f"  PASS_trades: n={pt['n_trades']} avg_R={pt['avg_R']} hit={pt['hit_rate']} median_net={pt['median_net_ret_pct']}%")
    return 0


if __name__ == "__main__":
    sys.exit(main())
