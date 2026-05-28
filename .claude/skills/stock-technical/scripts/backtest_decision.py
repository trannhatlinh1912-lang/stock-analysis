#!/usr/bin/env python3
"""Walk-forward backtest of decision_framework state classifier.

For each historical bar:
  1. Compute state via decision_framework.determine_state.
  2. If state is one of TRADEABLE_STATES, simulate a long entry at next bar's open.
  3. Set stop = max(SMA50, close - 1.5*ATR14).
  4. Set target = close + 1.5*ATR14 (proxy primary_target).
  5. Walk forward up to HOLD_BARS bars; exit when high ≥ target, low ≤ stop, or timeout.
  6. Realized return is net of VN_ROUNDTRIP_COST_PCT.

Aggregates per state + overall:
  n_trades, hit_rate, avg_R (reward/risk realised), median_ret_pct, max_dd_pct.

Output:
  data/{SYMBOL}_backtest.json
  reports/{SYMBOL}_backtest_report.md
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = REPO_ROOT / "data"
REPORTS_DIR = REPO_ROOT / "reports"
DATA_DIR.mkdir(exist_ok=True)
REPORTS_DIR.mkdir(exist_ok=True)

sys.path.insert(0, str(Path(__file__).resolve().parent))
from decision_framework import determine_state  # noqa: E402

VN_ROUNDTRIP_COST_PCT = 0.40
# Calibrated defaults [2026-05-28] from scripts/calibrate.py pooled top-5:
#   pooled avg_R 0.583, hit_rate 0.341 across BSR/VCB/BMP/PLX/POW (5 tickers).
# Old heuristic was 1.5/1.5/10 — not in top 5.
HOLD_BARS = 20
ATR_STOP_MULT = 1.0
ATR_TARGET_MULT = 3.0
TRADEABLE_STATES = {
    "BULLISH_TREND_CONFIRMED",
    "BREAKOUT_CONFIRMED",
    "ACCUMULATION",
}


def _classify_states(df: pd.DataFrame) -> list[str]:
    out: list[str] = []
    for i in range(len(df)):
        try:
            out.append(determine_state(df.iloc[i]))
        except Exception:
            out.append("WATCH")
    return out


def _max_drawdown_pct(returns: np.ndarray) -> float:
    if len(returns) == 0:
        return 0.0
    equity = np.cumprod(1.0 + returns / 100.0)
    peak = np.maximum.accumulate(equity)
    dd = (equity - peak) / peak * 100.0
    return float(dd.min())


def simulate(df: pd.DataFrame) -> dict:
    """Walk-forward backtest. Assumes df sorted by date."""
    df = df.reset_index(drop=True).copy()
    df["state"] = _classify_states(df)

    trades = []
    n = len(df)
    for i in range(n - 2):
        state = df.at[i, "state"]
        if state not in TRADEABLE_STATES:
            continue
        close_i = df.at[i, "close"]
        atr_i = df.at[i, "atr14"] if "atr14" in df.columns else np.nan
        sma50_i = df.at[i, "sma50"] if "sma50" in df.columns else np.nan
        if pd.isna(atr_i) or pd.isna(close_i):
            continue

        entry_idx = i + 1
        if entry_idx >= n:
            continue
        entry = df.at[entry_idx, "open"]
        if pd.isna(entry):
            continue

        # Stop = max(SMA50, close - 1.5 ATR) if close > SMA50, else close - 1.5 ATR.
        atr_stop = close_i - ATR_STOP_MULT * atr_i
        if pd.notna(sma50_i) and close_i > sma50_i:
            stop = max(atr_stop, sma50_i)
        else:
            stop = atr_stop
        target = close_i + ATR_TARGET_MULT * atr_i
        risk_per_share = entry - stop
        if risk_per_share <= 0:
            continue

        exit_reason = "timeout"
        exit_price = df.at[min(entry_idx + HOLD_BARS, n - 1), "close"]
        exit_idx = min(entry_idx + HOLD_BARS, n - 1)
        for j in range(entry_idx, min(entry_idx + HOLD_BARS + 1, n)):
            hi = df.at[j, "high"]
            lo = df.at[j, "low"]
            if pd.isna(hi) or pd.isna(lo):
                continue
            # Conservative: check stop before target intraday.
            if lo <= stop:
                exit_reason = "stop"
                exit_price = stop
                exit_idx = j
                break
            if hi >= target:
                exit_reason = "target"
                exit_price = target
                exit_idx = j
                break

        ret_pct_gross = (exit_price - entry) / entry * 100.0
        ret_pct_net = ret_pct_gross - VN_ROUNDTRIP_COST_PCT
        reward_per_share = exit_price - entry
        r_multiple = reward_per_share / risk_per_share

        trades.append({
            "entry_date": str(df.at[entry_idx, "date"]),
            "exit_date": str(df.at[exit_idx, "date"]),
            "state": state,
            "entry": round(float(entry), 4),
            "stop": round(float(stop), 4),
            "target": round(float(target), 4),
            "exit_price": round(float(exit_price), 4),
            "exit_reason": exit_reason,
            "ret_pct_gross": round(float(ret_pct_gross), 3),
            "ret_pct_net": round(float(ret_pct_net), 3),
            "r_multiple": round(float(r_multiple), 3),
            "bars_held": int(exit_idx - entry_idx + 1),
        })

    return trades


def aggregate(trades: list[dict]) -> dict:
    """Aggregate per-state and overall."""
    if not trades:
        return {"by_state": {}, "overall": {"n_trades": 0}}

    df = pd.DataFrame(trades)

    def _group_stats(grp: pd.DataFrame) -> dict:
        n = len(grp)
        wins = (grp["ret_pct_net"] > 0).sum()
        hit_rate = round(float(wins / n), 4) if n else 0.0
        return {
            "n": int(n),
            "hit_rate": hit_rate,
            "avg_r": round(float(grp["r_multiple"].mean()), 3),
            "median_r": round(float(grp["r_multiple"].median()), 3),
            "avg_ret_pct": round(float(grp["ret_pct_net"].mean()), 3),
            "median_ret_pct": round(float(grp["ret_pct_net"].median()), 3),
            "best": round(float(grp["ret_pct_net"].max()), 3),
            "worst": round(float(grp["ret_pct_net"].min()), 3),
            "max_dd_pct": round(_max_drawdown_pct(grp["ret_pct_net"].to_numpy()), 3),
            "target_exit_pct": round(float((grp["exit_reason"] == "target").mean() * 100), 2),
            "stop_exit_pct": round(float((grp["exit_reason"] == "stop").mean() * 100), 2),
            "timeout_exit_pct": round(float((grp["exit_reason"] == "timeout").mean() * 100), 2),
        }

    by_state = {state: _group_stats(grp) for state, grp in df.groupby("state")}
    overall = _group_stats(df)

    return {"by_state": by_state, "overall": overall}


def render_markdown(symbol: str, agg: dict, trades: list[dict]) -> str:
    L = [f"# {symbol} — Backtest Report", ""]
    L.append(f"- Generated: `{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}`")
    L.append(f"- Hold bars: {HOLD_BARS}, ATR stop mult: {ATR_STOP_MULT}, ATR target mult: {ATR_TARGET_MULT}")
    L.append(f"- Cost assumed (round-trip): {VN_ROUNDTRIP_COST_PCT}%")
    L.append("")

    overall = agg.get("overall", {})
    L.append("## Overall")
    L.append("")
    if overall.get("n_trades") == 0 or not overall.get("n"):
        L.append("- _no trades simulated_")
    else:
        L.append(f"- n_trades: {overall.get('n')}")
        L.append(f"- hit_rate: {overall.get('hit_rate')}")
        L.append(f"- avg_R: {overall.get('avg_r')} · median_R: {overall.get('median_r')}")
        L.append(f"- avg_ret%: {overall.get('avg_ret_pct')} · median_ret%: {overall.get('median_ret_pct')}")
        L.append(f"- best: {overall.get('best')}% · worst: {overall.get('worst')}%")
        L.append(f"- max_dd: {overall.get('max_dd_pct')}%")
        L.append(
            f"- exit mix: target {overall.get('target_exit_pct')}% / "
            f"stop {overall.get('stop_exit_pct')}% / "
            f"timeout {overall.get('timeout_exit_pct')}%"
        )
    L.append("")

    L.append("## By state")
    L.append("")
    L.append("| State | n | hit_rate | avg_R | avg_ret% | max_dd% | target% | stop% | timeout% |")
    L.append("|---|---|---|---|---|---|---|---|---|")
    for state, s in agg.get("by_state", {}).items():
        L.append(
            f"| {state} | {s['n']} | {s['hit_rate']} | {s['avg_r']} | "
            f"{s['avg_ret_pct']} | {s['max_dd_pct']} | "
            f"{s['target_exit_pct']} | {s['stop_exit_pct']} | {s['timeout_exit_pct']} |"
        )
    L.append("")

    L.append(f"## Last {min(20, len(trades))} trades")
    L.append("")
    L.append("| Entry | Exit | State | Entry$ | Stop$ | Target$ | Exit$ | Reason | Ret%net | R |")
    L.append("|---|---|---|---|---|---|---|---|---|---|")
    for t in trades[-20:]:
        L.append(
            f"| {t['entry_date'][:10]} | {t['exit_date'][:10]} | {t['state']} | "
            f"{t['entry']} | {t['stop']} | {t['target']} | {t['exit_price']} | "
            f"{t['exit_reason']} | {t['ret_pct_net']} | {t['r_multiple']} |"
        )
    L.append("")
    L.append("> Backtest đơn giản; intraday assume stop hit trước target nếu cả 2 cùng phiên.")
    return "\n".join(L) + "\n"


def run(csv_path: Path, symbol: str) -> tuple[Path, Path]:
    df = pd.read_csv(csv_path)
    df.columns = [c.lower() for c in df.columns]
    if "date" in df.columns:
        df["date"] = pd.to_datetime(df["date"])
    elif "time" in df.columns:
        df["date"] = pd.to_datetime(df["time"])
    df = df.sort_values("date").reset_index(drop=True)

    trades = simulate(df)
    agg = aggregate(trades)
    agg["symbol"] = symbol
    agg["as_of"] = datetime.now().strftime("%Y-%m-%d")
    agg["trades_sample"] = trades[-30:]

    json_out = DATA_DIR / f"{symbol}_backtest.json"
    json_out.write_text(json.dumps(agg, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"[backtest] wrote {json_out}")

    md_out = REPORTS_DIR / f"{symbol}_backtest_report.md"
    md_out.write_text(render_markdown(symbol, agg, trades), encoding="utf-8")
    print(f"[backtest] wrote {md_out}")
    return json_out, md_out


def main() -> int:
    p = argparse.ArgumentParser(description="Walk-forward backtest of decision_framework states.")
    p.add_argument("--csv", required=True, help="Indicators CSV path.")
    p.add_argument("--symbol", required=True, help="Ticker.")
    args = p.parse_args()
    run(Path(args.csv), args.symbol.upper())
    return 0


if __name__ == "__main__":
    sys.exit(main())
