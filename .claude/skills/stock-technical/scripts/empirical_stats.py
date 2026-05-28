#!/usr/bin/env python3
"""Empirical backtest stats for technical states.

Reads an indicators CSV (output of ``indicator_engine.py``), classifies the
state of every historical row using the same priority logic as
``decision_framework.determine_state``, and aggregates forward returns
(1D / 5D / 20D), hit rate on a +1 ATR target within 5 bars, and sample
size per state. Lookback caps the window to the most recent N rows.

Usage
-----
    python scripts/empirical_stats.py --csv data/VCB_indicators.csv \
        --symbol VCB --lookback 500
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = REPO_ROOT / "data"
DATA_DIR.mkdir(exist_ok=True)

# Reuse the state classifier from decision_framework to guarantee parity.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from decision_framework import determine_state  # noqa: E402

# VN round-trip cost: 0.15% buy + 0.15% sell + 0.1% tax on sell ≈ 0.4%.
VN_ROUNDTRIP_COST_PCT = 0.40
BOOTSTRAP_ITERS = 1000
BOOTSTRAP_SEED = 42


def _bootstrap_ci(values: np.ndarray, stat_fn, iters: int = BOOTSTRAP_ITERS, ci: float = 0.95) -> tuple[float, float]:
    """Percentile bootstrap CI for a scalar statistic of a numeric array."""
    if len(values) == 0:
        return (float("nan"), float("nan"))
    rng = np.random.default_rng(BOOTSTRAP_SEED)
    n = len(values)
    samples = np.empty(iters)
    for i in range(iters):
        idx = rng.integers(0, n, n)
        samples[i] = stat_fn(values[idx])
    alpha = (1.0 - ci) / 2.0
    lo, hi = np.percentile(samples, [alpha * 100, (1 - alpha) * 100])
    return (float(lo), float(hi))


def _classify_all(df: pd.DataFrame) -> pd.Series:
    """Apply determine_state row-by-row. Returns Series of state strings."""
    labels = []
    for i in range(len(df)):
        row = df.iloc[i]
        try:
            labels.append(determine_state(row))
        except Exception:
            labels.append("WATCH")
    return pd.Series(labels, index=df.index, name="state")


def _forward_returns(close: pd.Series, horizon: int) -> pd.Series:
    """Pct change from t to t+horizon, expressed in %."""
    fwd = close.shift(-horizon)
    return (fwd / close - 1.0) * 100.0


def _hit_target_atr(close: pd.Series, atr: pd.Series, horizon: int = 5, mult: float = 1.0) -> pd.Series:
    """Did high (proxied by close) ever exceed close[t] + mult*ATR within horizon bars?"""
    n = len(close)
    out = np.zeros(n, dtype=bool)
    arr_close = close.values
    arr_atr = atr.values
    for t in range(n):
        if np.isnan(arr_atr[t]):
            continue
        target = arr_close[t] + mult * arr_atr[t]
        end = min(t + horizon + 1, n)
        if (arr_close[t + 1:end] >= target).any():
            out[t] = True
    return pd.Series(out, index=close.index)


def aggregate(df: pd.DataFrame, lookback: int = 500) -> dict:
    """Build aggregate stats per state over the last `lookback` rows."""
    work = df.copy()
    work = work.iloc[-(lookback + 20):].reset_index(drop=True)  # +20 for forward window
    work["state"] = _classify_all(work)
    work["fwd_1d"] = _forward_returns(work["close"], 1)
    work["fwd_5d"] = _forward_returns(work["close"], 5)
    work["fwd_20d"] = _forward_returns(work["close"], 20)
    work["hit_1atr_5d"] = _hit_target_atr(work["close"], work["atr14"], horizon=5, mult=1.0)

    # Restrict aggregation window to the actual lookback (drop the +20 buffer
    # that exists only to produce forward returns at the tail).
    cutoff = work.iloc[-lookback:].copy() if lookback < len(work) else work
    # Drop rows where fwd returns are NaN (recent tail beyond data).
    cutoff = cutoff.dropna(subset=["fwd_5d"])

    stats: dict[str, dict] = {}
    for state, grp in cutoff.groupby("state"):
        n = len(grp)
        if n == 0:
            continue
        fwd1 = grp["fwd_1d"].to_numpy()
        fwd5 = grp["fwd_5d"].to_numpy()
        up_1d = (fwd1 > 0).astype(float)
        up_5d = (fwd5 > 0).astype(float)
        hit = grp["hit_1atr_5d"].astype(float).to_numpy()
        # Cost-adjusted: subtract round-trip cost from forward returns.
        fwd5_net = fwd5 - VN_ROUNDTRIP_COST_PCT
        p_up_5d_net = float((fwd5_net > 0).mean()) if n else None

        p_up_1d_lo, p_up_1d_hi = _bootstrap_ci(up_1d, np.mean) if n >= 5 else (float("nan"), float("nan"))
        p_up_5d_lo, p_up_5d_hi = _bootstrap_ci(up_5d, np.mean) if n >= 5 else (float("nan"), float("nan"))
        hit_lo, hit_hi = _bootstrap_ci(hit, np.mean) if n >= 5 else (float("nan"), float("nan"))
        median5_lo, median5_hi = _bootstrap_ci(fwd5, np.median) if n >= 5 else (float("nan"), float("nan"))

        def _r(x):
            return None if np.isnan(x) else round(float(x), 4)

        rec = {
            "n_samples": int(n),
            "p_up_1d": round(float(up_1d.mean()), 4),
            "p_up_1d_ci95": [_r(p_up_1d_lo), _r(p_up_1d_hi)],
            "p_up_5d": round(float(up_5d.mean()), 4),
            "p_up_5d_ci95": [_r(p_up_5d_lo), _r(p_up_5d_hi)],
            "p_up_5d_net_of_cost": round(p_up_5d_net, 4) if p_up_5d_net is not None else None,
            "mean_ret_1d_pct": round(float(fwd1.mean()), 3),
            "median_ret_1d_pct": round(float(np.median(fwd1)), 3),
            "mean_ret_5d_pct": round(float(fwd5.mean()), 3),
            "median_ret_5d_pct": round(float(np.median(fwd5)), 3),
            "median_ret_5d_pct_ci95": [_r(median5_lo), _r(median5_hi)],
            "mean_ret_5d_net_of_cost_pct": round(float(fwd5_net.mean()), 3),
            "mean_ret_20d_pct": round(float(grp["fwd_20d"].mean()), 3) if grp["fwd_20d"].notna().any() else None,
            "std_ret_5d_pct": round(float(fwd5.std()), 3) if n > 1 else None,
            "hit_target_1atr_5d": round(float(hit.mean()), 4),
            "hit_target_1atr_5d_ci95": [_r(hit_lo), _r(hit_hi)],
            "low_sample_warning": bool(n < 10),
            "cost_pct_assumed": VN_ROUNDTRIP_COST_PCT,
        }
        stats[state] = rec

    return {
        "lookback_used": int(min(lookback, len(cutoff))),
        "first_date": cutoff["date"].min().strftime("%Y-%m-%d") if "date" in cutoff.columns else None,
        "last_date": cutoff["date"].max().strftime("%Y-%m-%d") if "date" in cutoff.columns else None,
        "by_state": stats,
    }


def run(csv_path: Path, symbol: str, lookback: int) -> Path:
    df = pd.read_csv(csv_path)
    df.columns = [c.lower() for c in df.columns]
    if "date" in df.columns:
        df["date"] = pd.to_datetime(df["date"])
    elif "time" in df.columns:
        df["date"] = pd.to_datetime(df["time"])
    df = df.sort_values("date").reset_index(drop=True)
    if len(df) < 30:
        raise ValueError(f"insufficient rows for backtest: {len(df)}")

    pkg = aggregate(df, lookback=lookback)
    pkg["symbol"] = symbol
    out_path = DATA_DIR / f"{symbol}_empirical_stats.json"
    out_path.write_text(json.dumps(pkg, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"[empirical_stats] wrote {out_path} (lookback={pkg['lookback_used']})")
    return out_path


def main() -> int:
    p = argparse.ArgumentParser(description="Empirical state-conditional return stats.")
    p.add_argument("--csv", required=True, help="Indicators CSV path.")
    p.add_argument("--symbol", required=True, help="Ticker.")
    p.add_argument("--lookback", type=int, default=500, help="Recent rows to include.")
    args = p.parse_args()
    run(Path(args.csv), args.symbol.upper(), args.lookback)
    return 0


if __name__ == "__main__":
    sys.exit(main())
