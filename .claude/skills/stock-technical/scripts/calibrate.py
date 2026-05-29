#!/usr/bin/env python3
"""Calibration suite — replace heuristics with empirically-derived values.

Three calibration jobs:

1. **Backtest param grid search** — sweep (ATR_STOP_MULT, ATR_TARGET_MULT,
   HOLD_BARS) over a list of tickers, score by mean R-multiple net of cost,
   pick the maximiser per ticker + the overall maximiser.

2. **Macro penalty regression** — for each sector basket, regress forward 5D
   return on Brent ret_5d, DXY ret_20d, USDVND ret_20d. Compute beta + R^2,
   translate to score delta calibrated against an empirical 5D std-dev unit.

3. **ATR%% distribution per sector** — pool ATR%% across sector tickers,
   compute median/P90/P95. Use median as `atr_pct_low`, P90 as `atr_pct_high`.

Outputs
-------
- configs/calibrated.yaml             (proposed overrides)
- reports/calibration_report.md       (full transparency)
- data/calibration_cache/{TICKER}_close.csv  (cached close-only series)

Usage
-----
    python scripts/calibrate.py [--lookback 500] [--tickers BSR VCB BMP PLX POW HPG ...]
"""
from __future__ import annotations

import argparse
import json
import sys
import warnings
from datetime import date, datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = REPO_ROOT / "data"
CACHE_DIR = DATA_DIR / "calibration_cache"
CONFIGS_DIR = REPO_ROOT / "configs"
REPORTS_DIR = REPO_ROOT / "reports"
CACHE_DIR.mkdir(parents=True, exist_ok=True)
CONFIGS_DIR.mkdir(exist_ok=True)
REPORTS_DIR.mkdir(exist_ok=True)

sys.path.insert(0, str(Path(__file__).resolve().parent))
from config_loader import SECTOR_MAP  # noqa: E402
from decision_framework import determine_state  # noqa: E402

VN_ROUNDTRIP_COST_PCT = 0.40
TRADEABLE_STATES = {
    "BULLISH_TREND_CONFIRMED",
    "BREAKOUT_CONFIRMED",
    "ACCUMULATION",
}

# Grid search space.
ATR_STOP_GRID = [1.0, 1.5, 2.0, 2.5]
ATR_TARGET_GRID = [1.0, 1.5, 2.0, 3.0]
HOLD_BARS_GRID = [5, 10, 15, 20]


# ---------------------------------------------------------------------------
# Data fetching
# ---------------------------------------------------------------------------


def fetch_close_history(symbol: str, days: int = 540) -> pd.DataFrame | None:
    """Cache-aware close-only fetch. Returns DataFrame[date, close]."""
    cache = CACHE_DIR / f"{symbol}_close.csv"
    if cache.exists():
        try:
            df = pd.read_csv(cache)
            df["date"] = pd.to_datetime(df["date"])
            return df
        except Exception:
            pass
    try:
        from vnstock.api.quote import Quote
        end = date.today()
        start = end - timedelta(days=days)
        q = Quote(symbol=symbol, source="VCI")
        df = q.history(start=start.isoformat(), end=end.isoformat(), interval="1D")
        if df is None or len(df) == 0:
            return None
        df = df.copy()
        df.columns = [c.lower() for c in df.columns]
        if "time" in df.columns:
            df["date"] = pd.to_datetime(df["time"])
        df = df[["date", "close"]].sort_values("date").reset_index(drop=True)
        df.to_csv(cache, index=False)
        return df
    except Exception as e:
        print(f"[calibrate] fetch_close_history({symbol}) FAILED: {e}")
        return None


def fetch_macro_series(period_days: int = 540) -> dict[str, pd.DataFrame]:
    """Fetch Brent / DXY / USDVND close-only via yfinance. Returns dict by name."""
    import yfinance as yf
    end = date.today()
    start = end - timedelta(days=period_days)
    out: dict[str, pd.DataFrame] = {}
    tickers = {"brent": "BZ=F", "dxy": "DX-Y.NYB", "usdvnd": "VND=X"}
    for name, tkr in tickers.items():
        cache = CACHE_DIR / f"_macro_{name}.csv"
        if cache.exists():
            try:
                df = pd.read_csv(cache)
                df["date"] = pd.to_datetime(df["date"])
                out[name] = df
                continue
            except Exception:
                pass
        try:
            d = yf.download(tkr, start=start.isoformat(), end=end.isoformat(),
                            progress=False, auto_adjust=True)
            if d is None or len(d) == 0:
                continue
            close = d["Close"]
            if isinstance(close, pd.DataFrame):
                close = close.iloc[:, 0]
            df = pd.DataFrame({"date": close.index, "close": close.values})
            df["date"] = pd.to_datetime(df["date"]).dt.tz_localize(None)
            df.to_csv(cache, index=False)
            out[name] = df
        except Exception as e:
            print(f"[calibrate] fetch_macro({name}) FAILED: {e}")
    return out


# ---------------------------------------------------------------------------
# Job 1: Grid search backtest params
# ---------------------------------------------------------------------------


def _simulate_grid(
    df: pd.DataFrame, atr_stop: float, atr_target: float, hold_bars: int,
) -> dict:
    """Simulate backtest with given params on a single ticker indicators frame."""
    df = df.reset_index(drop=True).copy()
    try:
        labels = [determine_state(df.iloc[i]) for i in range(len(df))]
    except Exception:
        return {"n_trades": 0}
    df["state"] = labels

    rs: list[float] = []
    rets_net: list[float] = []
    n = len(df)
    for i in range(n - hold_bars - 1):
        state = df.at[i, "state"]
        if state not in TRADEABLE_STATES:
            continue
        close_i = df.at[i, "close"]
        atr_i = df.at[i, "atr14"] if "atr14" in df.columns else np.nan
        sma50_i = df.at[i, "sma50"] if "sma50" in df.columns else np.nan
        if pd.isna(atr_i) or pd.isna(close_i):
            continue
        entry_idx = i + 1
        entry = df.at[entry_idx, "open"]
        if pd.isna(entry):
            continue
        atr_stop_lvl = close_i - atr_stop * atr_i
        if pd.notna(sma50_i) and close_i > sma50_i:
            stop = max(atr_stop_lvl, sma50_i)
        else:
            stop = atr_stop_lvl
        target = close_i + atr_target * atr_i
        risk = entry - stop
        if risk <= 0:
            continue

        exit_price = df.at[min(entry_idx + hold_bars, n - 1), "close"]
        for j in range(entry_idx, min(entry_idx + hold_bars + 1, n)):
            hi = df.at[j, "high"]
            lo = df.at[j, "low"]
            if pd.isna(hi) or pd.isna(lo):
                continue
            if lo <= stop:
                exit_price = stop
                break
            if hi >= target:
                exit_price = target
                break

        reward = exit_price - entry
        rs.append(float(reward / risk))
        rets_net.append(float((exit_price - entry) / entry * 100.0 - VN_ROUNDTRIP_COST_PCT))

    if not rs:
        return {"n_trades": 0}
    arr_r = np.array(rs)
    arr_ret = np.array(rets_net)
    hit = float((arr_ret > 0).mean())
    return {
        "n_trades": int(len(rs)),
        "avg_r": float(arr_r.mean()),
        "median_r": float(np.median(arr_r)),
        "hit_rate": round(hit, 4),
        "avg_ret_net_pct": float(arr_ret.mean()),
        "sharpe_proxy": (
            float(arr_ret.mean() / arr_ret.std())
            if arr_ret.std() > 0 else 0.0
        ),
    }


def grid_search_backtest(tickers: list[str], walk_forward: bool = False) -> dict:
    """Grid search per ticker + pool. Returns per-ticker best + overall best.

    walk_forward=True: split each ticker into 70% train / 30% test by date.
    Fit param grid on train, evaluate on test. Detects overfit.
    """
    per_ticker: dict[str, dict] = {}
    pooled_results: list[dict] = []
    wf_rows: list[dict] = []

    for sym in tickers:
        csv = DATA_DIR / f"{sym}_indicators.csv"
        if not csv.exists():
            print(f"[calibrate] {sym}: no indicators CSV, skip")
            continue
        df = pd.read_csv(csv)
        df.columns = [c.lower() for c in df.columns]
        if "date" in df.columns:
            df["date"] = pd.to_datetime(df["date"])

        # Train/test split for walk-forward.
        if walk_forward and len(df) >= 100:
            split = int(len(df) * 0.7)
            df_train = df.iloc[:split].reset_index(drop=True)
            df_test = df.iloc[split:].reset_index(drop=True)
        else:
            df_train = df
            df_test = None

        ticker_grid: list[dict] = []
        for s in ATR_STOP_GRID:
            for t in ATR_TARGET_GRID:
                for h in HOLD_BARS_GRID:
                    res = _simulate_grid(df_train, s, t, h)
                    if res.get("n_trades", 0) < 5:
                        continue
                    res.update({
                        "atr_stop": s, "atr_target": t, "hold_bars": h,
                        "ticker": sym,
                    })
                    ticker_grid.append(res)
                    pooled_results.append(res)

        if ticker_grid:
            best = max(ticker_grid, key=lambda x: x["avg_r"])
            per_ticker[sym] = best

            if walk_forward and df_test is not None and len(df_test) >= 30:
                # Replay best params on test set (out-of-sample).
                oos = _simulate_grid(df_test, best["atr_stop"], best["atr_target"], best["hold_bars"])
                wf_rows.append({
                    "ticker": sym,
                    "best_params_on_train": (best["atr_stop"], best["atr_target"], best["hold_bars"]),
                    "train_n": best["n_trades"],
                    "train_avg_r": round(best["avg_r"], 4),
                    "train_hit_rate": round(best["hit_rate"], 4),
                    "test_n": oos.get("n_trades", 0),
                    "test_avg_r": round(oos.get("avg_r", 0.0), 4) if oos.get("n_trades", 0) > 0 else None,
                    "test_hit_rate": round(oos.get("hit_rate", 0.0), 4) if oos.get("n_trades", 0) > 0 else None,
                })

    # Pool by params.
    by_params: dict[tuple, list[dict]] = {}
    for r in pooled_results:
        key = (r["atr_stop"], r["atr_target"], r["hold_bars"])
        by_params.setdefault(key, []).append(r)

    overall_rows = []
    for params, rows in by_params.items():
        if len(rows) < 2:
            continue
        mean_r = float(np.mean([r["avg_r"] for r in rows]))
        mean_hit = float(np.mean([r["hit_rate"] for r in rows]))
        total_n = int(sum(r["n_trades"] for r in rows))
        overall_rows.append({
            "atr_stop": params[0],
            "atr_target": params[1],
            "hold_bars": params[2],
            "n_tickers_with_data": len(rows),
            "pooled_avg_r": round(mean_r, 4),
            "pooled_hit_rate": round(mean_hit, 4),
            "total_trades": total_n,
        })
    overall_rows.sort(key=lambda x: x["pooled_avg_r"], reverse=True)
    return {
        "per_ticker_best": per_ticker,
        "pooled_top5": overall_rows[:5],
        "pooled_bottom5": overall_rows[-5:],
        "all_pooled": overall_rows,
        "walk_forward": wf_rows,
        "walk_forward_enabled": walk_forward,
    }


# ---------------------------------------------------------------------------
# Job 2: Macro penalty regression
# ---------------------------------------------------------------------------


def _ols_beta(x: np.ndarray, y: np.ndarray) -> dict:
    """Univariate OLS: y = a + b*x. Return beta, alpha, r2, n."""
    mask = ~(np.isnan(x) | np.isnan(y))
    x = x[mask]
    y = y[mask]
    if len(x) < 20:
        return {"n": int(len(x)), "beta": None, "alpha": None, "r2": None}
    A = np.vstack([x, np.ones_like(x)]).T
    beta, alpha = np.linalg.lstsq(A, y, rcond=None)[0]
    yhat = beta * x + alpha
    ss_res = float(((y - yhat) ** 2).sum())
    ss_tot = float(((y - y.mean()) ** 2).sum())
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else 0.0
    return {
        "n": int(len(x)),
        "beta": round(float(beta), 5),
        "alpha": round(float(alpha), 5),
        "r2": round(float(r2), 4),
    }


def _ols_multi(X: np.ndarray, y: np.ndarray, names: list[str]) -> dict:
    """Multi-driver OLS via normal equation. Returns betas, t-stat proxies, adj-R²,
    pairwise correlation of regressors (collinearity check)."""
    mask = ~np.isnan(y)
    for j in range(X.shape[1]):
        mask &= ~np.isnan(X[:, j])
    X = X[mask]
    y = y[mask]
    n, k = X.shape
    if n < 30 or k == 0:
        return {"n": int(n), "error": "insufficient_obs"}
    # Add intercept column
    Xc = np.hstack([X, np.ones((n, 1))])
    try:
        betas, *_ = np.linalg.lstsq(Xc, y, rcond=None)
    except np.linalg.LinAlgError:
        return {"n": int(n), "error": "lstsq_failed"}
    yhat = Xc @ betas
    resid = y - yhat
    ss_res = float((resid ** 2).sum())
    ss_tot = float(((y - y.mean()) ** 2).sum())
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else 0.0
    p = k + 1
    adj_r2 = 1.0 - (1.0 - r2) * (n - 1) / (n - p) if n > p else r2

    # t-stat proxy: beta / SE. SE = sqrt(diag((X'X)^-1 * sigma²))
    sigma2 = ss_res / (n - p) if n > p else float("nan")
    try:
        XtX_inv = np.linalg.inv(Xc.T @ Xc)
        ses = np.sqrt(np.maximum(np.diag(XtX_inv) * sigma2, 0.0))
        t_stats = betas / ses
    except np.linalg.LinAlgError:
        t_stats = np.full_like(betas, np.nan)

    # Pairwise correlations (collinearity)
    corr_pairs = {}
    if k >= 2:
        C = np.corrcoef(X.T)
        for i in range(k):
            for j in range(i + 1, k):
                corr_pairs[f"{names[i]}_vs_{names[j]}"] = round(float(C[i, j]), 3)

    return {
        "n": int(n),
        "r2": round(float(r2), 4),
        "adj_r2": round(float(adj_r2), 4),
        "betas": {names[i]: round(float(betas[i]), 5) for i in range(k)},
        "intercept": round(float(betas[-1]), 5),
        "t_stats": {names[i]: round(float(t_stats[i]), 3) for i in range(k)},
        "intercept_t": round(float(t_stats[-1]), 3),
        "collinearity_pairs": corr_pairs,
    }


def _build_sector_basket(sector: str) -> list[str]:
    return [tkr for tkr, sec in SECTOR_MAP.items() if sec == sector]


def _basket_returns(symbols: list[str], horizon_days: int = 5) -> pd.DataFrame | None:
    """Equal-weight basket return series for given horizon (forward returns)."""
    series = []
    for sym in symbols:
        df = fetch_close_history(sym, days=540)
        if df is None or len(df) < 50:
            continue
        df = df.copy()
        df["ret"] = df["close"].pct_change(horizon_days) * 100.0
        df = df[["date", "ret"]].rename(columns={"ret": sym})
        series.append(df.set_index("date"))
    if not series:
        return None
    wide = pd.concat(series, axis=1).sort_index()
    # Equal-weight basket return only on dates where ALL members have a return
    # (inner join). mean(axis=1, skipna=True) averaged a shifting membership on
    # partially-populated rows (different listing dates / the pct_change NaN
    # head), feeding a distorted basket into the macro regression — same class
    # as the L3 _basket_close bug. Align first.
    aligned = wide.dropna(how="any")
    if aligned.empty:
        return None
    aligned = aligned.copy()
    aligned["basket_ret"] = aligned.mean(axis=1)
    return aligned.reset_index()[["date", "basket_ret"]]


def calibrate_macro_penalties(sectors: list[str]) -> dict:
    """For each sector basket: regress forward 5D return on macro drivers."""
    macro = fetch_macro_series()
    if not macro:
        return {"error": "no macro series fetched"}

    def _macro_returns(name: str, horizon: int) -> pd.DataFrame | None:
        df = macro.get(name)
        if df is None:
            return None
        d = df.copy()
        d["ret"] = d["close"].pct_change(horizon) * 100.0
        return d[["date", "ret"]].rename(columns={"ret": f"{name}_ret_{horizon}d"})

    brent_5 = _macro_returns("brent", 5)
    dxy_20 = _macro_returns("dxy", 20)
    usdvnd_20 = _macro_returns("usdvnd", 20)

    out: dict = {}
    for sector in sectors:
        basket = _build_sector_basket(sector)
        if not basket:
            out[sector] = {"error": "empty_basket"}
            continue
        ret = _basket_returns(basket, horizon_days=5)
        if ret is None:
            out[sector] = {"error": "no_returns"}
            continue
        m = ret.copy()
        for piece in (brent_5, dxy_20, usdvnd_20):
            if piece is not None:
                m = m.merge(piece, on="date", how="left")

        regressions: dict[str, dict] = {}
        driver_cols = [c for c in ("brent_ret_5d", "dxy_ret_20d", "usdvnd_ret_20d") if c in m.columns]
        for col in driver_cols:
            regressions[col] = _ols_beta(
                m[col].to_numpy(dtype=float),
                m["basket_ret"].to_numpy(dtype=float),
            )

        # Multi-driver OLS
        multi = None
        if len(driver_cols) >= 2:
            X = np.column_stack([m[c].to_numpy(dtype=float) for c in driver_cols])
            y = m["basket_ret"].to_numpy(dtype=float)
            multi = _ols_multi(X, y, driver_cols)

        basket_std = float(np.nanstd(m["basket_ret"].to_numpy(dtype=float)))
        out[sector] = {
            "basket": basket,
            "n_obs": int(m["basket_ret"].notna().sum()),
            "basket_5d_ret_std_pct": round(basket_std, 3),
            "regressions": regressions,
            "multi_driver_ols": multi,
        }
    return out


# ---------------------------------------------------------------------------
# Job 3: ATR% distribution per sector
# ---------------------------------------------------------------------------


RUBRIC_SIGNALS: list[dict] = [
    {"id": "close_above_sma50", "expr": "close > sma50", "current_weight": 10},
    {"id": "close_above_sma200", "expr": "close > sma200", "current_weight": 10},
    {"id": "vol_ratio_ge_1_5", "expr": "vol_ratio >= 1.5", "current_weight": 10},
    {"id": "macd_hist_positive", "expr": "macd_hist > 0", "current_weight": 8},
    {"id": "obv_slope_up", "expr": "obv_slope_20d > 0", "current_weight": 5},
    {"id": "mfi_50_to_80", "expr": "(mfi14 >= 50) & (mfi14 <= 80)", "current_weight": 5},
    {"id": "close_below_sma100", "expr": "close < sma100", "current_weight": -8},
    {"id": "stoch_above_90_at_bb_upper", "expr": "(stoch_k >= 90) & (bb_position == 'above_upper')", "current_weight": -8},
    {"id": "cmf_negative", "expr": "cmf20 < 0", "current_weight": -5},
    {"id": "ma_not_aligned",
     "expr": "~((close > sma20) & (sma20 > sma50) & (sma50 > sma100) & (sma100 > sma200))",
     "current_weight": -5},
]


def calibrate_score_rubric(tickers: list[str], horizon: int = 5) -> dict:
    """For each rubric signal, compute forward N-day return mean when signal is
    True vs False, pooled across tickers. Calibrate weight via z-stat scaling.

    Two-sample t-test approximation (Welch): t = (μ1-μ2) / sqrt(σ1²/n1 + σ2²/n2).
    Recommended weight = round(t / max(|t|) * 10) capped at ±10 to match
    current rubric range.
    """
    pool_true: dict[str, list[float]] = {s["id"]: [] for s in RUBRIC_SIGNALS}
    pool_false: dict[str, list[float]] = {s["id"]: [] for s in RUBRIC_SIGNALS}

    for sym in tickers:
        csv = DATA_DIR / f"{sym}_indicators.csv"
        if not csv.exists():
            continue
        df = pd.read_csv(csv)
        df.columns = [c.lower() for c in df.columns]
        if "atr14" not in df.columns:
            continue
        # Forward return
        df["fwd_ret"] = (df["close"].shift(-horizon) / df["close"] - 1.0) * 100.0

        for sig in RUBRIC_SIGNALS:
            try:
                mask = df.eval(sig["expr"])
            except Exception:
                continue
            if mask is None:
                continue
            mask = mask.astype(bool)
            valid = df["fwd_ret"].notna()
            t_vals = df.loc[mask & valid, "fwd_ret"].to_numpy()
            f_vals = df.loc[(~mask) & valid, "fwd_ret"].to_numpy()
            pool_true[sig["id"]].extend(t_vals.tolist())
            pool_false[sig["id"]].extend(f_vals.tolist())

    raw_rows: list[dict] = []
    for sig in RUBRIC_SIGNALS:
        t_arr = np.array(pool_true[sig["id"]])
        f_arr = np.array(pool_false[sig["id"]])
        n_t = len(t_arr)
        n_f = len(f_arr)
        if n_t < 30 or n_f < 30:
            raw_rows.append({
                "signal": sig["id"], "current_weight": sig["current_weight"],
                "n_true": n_t, "n_false": n_f, "error": "insufficient_samples",
            })
            continue
        mu_t = float(t_arr.mean())
        mu_f = float(f_arr.mean())
        var_t = float(t_arr.var(ddof=1))
        var_f = float(f_arr.var(ddof=1))
        se = float(np.sqrt(var_t / n_t + var_f / n_f))
        t_stat = (mu_t - mu_f) / se if se > 0 else 0.0
        raw_rows.append({
            "signal": sig["id"],
            "current_weight": sig["current_weight"],
            "n_true": int(n_t),
            "n_false": int(n_f),
            "mean_ret_true_pct": round(mu_t, 4),
            "mean_ret_false_pct": round(mu_f, 4),
            "diff_pct": round(mu_t - mu_f, 4),
            "t_stat": round(float(t_stat), 3),
            "significant": bool(abs(t_stat) > 2.0),
        })

    # Translate to recommended weight: scale t-stat into [-10, +10].
    # Anchor: max |t_stat| → 10. Drop signals with |t|<2 to weight 0.
    valid = [r for r in raw_rows if r.get("t_stat") is not None and "error" not in r]
    if valid:
        max_abs_t = max(abs(r["t_stat"]) for r in valid) or 1.0
        for r in valid:
            t = r["t_stat"]
            if abs(t) < 2.0:
                r["recommended_weight"] = 0
            else:
                r["recommended_weight"] = int(round(t / max_abs_t * 10))
        for r in raw_rows:
            if "recommended_weight" not in r and "error" not in r:
                r["recommended_weight"] = 0

    return {
        "horizon_days": horizon,
        "signals": raw_rows,
        "max_abs_t": max_abs_t if valid else None,
    }


def calibrate_risk_thresholds(tickers: list[str], horizon: int = 5) -> dict:
    """Grid-search optimal cutoffs for RSI / 52w / cmf / near_sma100 thresholds.

    For each parameter, sweep candidate cutoffs, compute forward 5D return
    diff (true vs false), pick cutoff with the largest |t-stat|.
    """
    grids = {
        "rsi_overbought": {
            "expr_template": "rsi14 >= {x}",
            "candidates": [65, 70, 72, 75, 78, 80],
        },
        "rsi_oversold": {
            "expr_template": "rsi14 <= {x}",
            "candidates": [20, 25, 28, 30, 35],
        },
        "near_52w_high": {
            "expr_template": "dist_52w_high_pct > {x}",
            "candidates": [-5, -3, -2, -1, 0],
        },
        "near_52w_low": {
            "expr_template": "dist_52w_low_pct < {x}",
            "candidates": [3, 5, 7, 10, 15],
        },
        "cmf_distribution": {
            "expr_template": "cmf20 < {x}",
            "candidates": [-0.1, -0.08, -0.05, -0.02, 0.0],
        },
        "near_sma100_below": {
            "expr_template": "(dist_sma100_pct >= {x}) and (dist_sma100_pct <= 0)",
            "candidates": [-5, -3, -2, -1],
        },
    }

    # Load all ticker indicator data once
    pools: dict[str, list[pd.DataFrame]] = {k: [] for k in grids.keys()}
    pool_frames: list[pd.DataFrame] = []
    for sym in tickers:
        csv = DATA_DIR / f"{sym}_indicators.csv"
        if not csv.exists():
            continue
        df = pd.read_csv(csv)
        df.columns = [c.lower() for c in df.columns]
        df["fwd_ret"] = (df["close"].shift(-horizon) / df["close"] - 1.0) * 100.0
        pool_frames.append(df)
    if not pool_frames:
        return {"error": "no_data"}
    big = pd.concat(pool_frames, ignore_index=True)

    out: dict = {}
    for param, spec in grids.items():
        rows = []
        for x in spec["candidates"]:
            expr = spec["expr_template"].format(x=x)
            try:
                mask = big.eval(expr)
            except Exception as e:
                rows.append({"cutoff": x, "error": str(e)[:80]})
                continue
            mask = mask.astype(bool)
            valid = big["fwd_ret"].notna()
            t_vals = big.loc[mask & valid, "fwd_ret"].to_numpy()
            f_vals = big.loc[(~mask) & valid, "fwd_ret"].to_numpy()
            n_t, n_f = len(t_vals), len(f_vals)
            if n_t < 30 or n_f < 30:
                rows.append({"cutoff": x, "n_true": n_t, "n_false": n_f,
                             "error": "insufficient"})
                continue
            mu_t, mu_f = float(t_vals.mean()), float(f_vals.mean())
            var_t, var_f = float(t_vals.var(ddof=1)), float(f_vals.var(ddof=1))
            se = float(np.sqrt(var_t / n_t + var_f / n_f))
            t = (mu_t - mu_f) / se if se > 0 else 0.0
            rows.append({
                "cutoff": x,
                "n_true": int(n_t),
                "n_false": int(n_f),
                "mean_diff_pct": round(mu_t - mu_f, 4),
                "t_stat": round(float(t), 3),
                "abs_t": round(abs(float(t)), 3),
            })
        valid_rows = [r for r in rows if "error" not in r]
        if valid_rows:
            best = max(valid_rows, key=lambda r: r["abs_t"])
        else:
            best = None
        out[param] = {
            "all": rows,
            "best": best,
        }
    return out


def calibrate_exhaustion_cap(tickers: list[str], horizon: int = 5) -> dict:
    """Validate two safety mechanisms:
       1. BREAKOUT_WITH_EXHAUSTION_RISK state — forward return when triggered.
       2. Triple-risk combo (breakout_exh + near_sma100 + ma_not_aligned) — forward return.

    If forward returns when triggered are POSITIVE (better than non-triggered),
    the cap/penalty is empirically WRONG.
    """
    pool: list[dict] = []
    triple_pool: list[dict] = []
    for sym in tickers:
        csv = DATA_DIR / f"{sym}_indicators.csv"
        if not csv.exists():
            continue
        df = pd.read_csv(csv)
        df.columns = [c.lower() for c in df.columns]
        df["fwd_ret"] = (df["close"].shift(-horizon) / df["close"] - 1.0) * 100.0
        for i in range(len(df)):
            r = df.iloc[i]
            try:
                # Re-evaluate exhaustion conjunction from heuristic
                exh = (
                    str(r.get("bb_position")) == "above_upper"
                    and pd.notna(r.get("vol_ratio")) and r["vol_ratio"] >= 2.0
                    and pd.notna(r.get("stoch_k")) and r["stoch_k"] >= 90.0
                    and pd.notna(r.get("ret_1d")) and r["ret_1d"] >= 5.0
                )
                # near sma100 below
                near = (
                    pd.notna(r.get("close")) and pd.notna(r.get("sma100"))
                    and r["close"] < r["sma100"]
                    and pd.notna(r.get("dist_sma100_pct"))
                    and -2.0 <= r["dist_sma100_pct"] <= 0.0
                )
                # ma not fully aligned
                cl = r.get("close")
                s20 = r.get("sma20"); s50 = r.get("sma50")
                s100 = r.get("sma100"); s200 = r.get("sma200")
                if all(pd.notna(v) for v in (cl, s20, s50, s100, s200)):
                    aligned = (cl > s20 > s50 > s100 > s200)
                else:
                    aligned = True
                not_aligned = not aligned
                fr = r.get("fwd_ret")
                if pd.isna(fr):
                    continue
                pool.append({"triggered": bool(exh), "fwd_ret": float(fr)})
                if exh and near and not_aligned:
                    triple_pool.append({"triggered": True, "fwd_ret": float(fr)})
                else:
                    triple_pool.append({"triggered": False, "fwd_ret": float(fr)})
            except Exception:
                continue

    def _summarize(rows: list[dict]) -> dict:
        df = pd.DataFrame(rows)
        if df.empty:
            return {"n": 0}
        t_arr = df.loc[df["triggered"], "fwd_ret"].to_numpy()
        f_arr = df.loc[~df["triggered"], "fwd_ret"].to_numpy()
        n_t, n_f = len(t_arr), len(f_arr)
        if n_t < 5 or n_f < 30:
            return {"n_true": int(n_t), "n_false": int(n_f),
                    "warning": "insufficient_triggers"}
        mu_t, mu_f = float(t_arr.mean()), float(f_arr.mean())
        var_t = float(t_arr.var(ddof=1)) if n_t > 1 else 0.0
        var_f = float(f_arr.var(ddof=1))
        se = float(np.sqrt(var_t / max(n_t, 1) + var_f / n_f))
        t = (mu_t - mu_f) / se if se > 0 else 0.0
        return {
            "n_true": int(n_t),
            "n_false": int(n_f),
            "mean_ret_true_pct": round(mu_t, 4),
            "mean_ret_false_pct": round(mu_f, 4),
            "diff_pct": round(mu_t - mu_f, 4),
            "t_stat": round(float(t), 3),
            "verdict": (
                "REMOVE_CAP — forward return positive when triggered"
                if (mu_t - mu_f) > 0 and abs(t) > 1.5
                else "KEEP_CAP — risk premium confirmed"
                if (mu_t - mu_f) < 0 and abs(t) > 1.5
                else "INCONCLUSIVE — |t|<1.5"
            ),
        }

    return {
        "horizon_days": horizon,
        "exhaustion_state": _summarize(pool),
        "triple_risk_combo": _summarize(triple_pool),
    }


def calibrate_base_bias_thresholds(tickers: list[str], horizon: int = 5) -> dict:
    """Find optimal score boundary for bullish/bearish bias labels."""
    pool_frames: list[pd.DataFrame] = []
    for sym in tickers:
        csv = DATA_DIR / f"{sym}_indicators.csv"
        if not csv.exists():
            continue
        df = pd.read_csv(csv)
        df.columns = [c.lower() for c in df.columns]
        df["fwd_ret"] = (df["close"].shift(-horizon) / df["close"] - 1.0) * 100.0
        # Compute a simple proxy score using the calibrated rubric directly
        df["proxy_score"] = 50
        df["proxy_score"] += np.where(df.get("close", 0) > df.get("sma50", 0), 8, 0)
        df["proxy_score"] += np.where(df.get("close", 0) > df.get("sma200", 0), -4, 0)
        df["proxy_score"] += np.where(df.get("macd_hist", 0) > 0, 8, 0)
        df["proxy_score"] += np.where(df.get("vol_ratio", 0) >= 1.5, 6, 0)
        df["proxy_score"] += np.where(df.get("obv_slope_20d", 0) > 0, 10, 0)
        df["proxy_score"] += np.where(df.get("cmf20", 0) < 0, -7, 0)
        pool_frames.append(df[["proxy_score", "fwd_ret"]])
    if not pool_frames:
        return {"error": "no_data"}
    big = pd.concat(pool_frames, ignore_index=True).dropna(subset=["fwd_ret"])

    rows = []
    for thresh in [55, 60, 62, 65, 68, 70, 72, 75]:
        mask = big["proxy_score"] >= thresh
        t = big.loc[mask, "fwd_ret"].to_numpy()
        f = big.loc[~mask, "fwd_ret"].to_numpy()
        if len(t) < 50 or len(f) < 50:
            continue
        mu_t, mu_f = float(t.mean()), float(f.mean())
        var_t, var_f = float(t.var(ddof=1)), float(f.var(ddof=1))
        se = float(np.sqrt(var_t / len(t) + var_f / len(f)))
        ts = (mu_t - mu_f) / se if se > 0 else 0.0
        rows.append({
            "threshold": thresh,
            "n_above": int(len(t)),
            "n_below": int(len(f)),
            "mean_above_pct": round(mu_t, 4),
            "mean_below_pct": round(mu_f, 4),
            "diff_pct": round(mu_t - mu_f, 4),
            "t_stat": round(float(ts), 3),
            "abs_t": round(abs(float(ts)), 3),
        })
    best = max(rows, key=lambda r: r["abs_t"]) if rows else None
    return {"all": rows, "best": best, "note": "proxy_score uses calibrated rubric weights only"}


def calibrate_breadth_thresholds(start_year: int = 2024) -> dict:
    """Compute VN30 breadth history daily, regress forward 5D VNINDEX return on
    breadth, find optimal strong/weak cutoffs."""
    from vnstock.api.quote import Quote
    # VNINDEX history
    idx_csv = DATA_DIR / "VNINDEX_price_VCI.csv"
    if not idx_csv.exists():
        return {"error": "VNINDEX_price_VCI.csv missing"}
    idx = pd.read_csv(idx_csv)
    idx.columns = [c.lower() for c in idx.columns]
    idx["time"] = pd.to_datetime(idx["time"])
    idx["idx_close"] = idx["close"]
    idx["fwd_ret"] = (idx["idx_close"].shift(-5) / idx["idx_close"] - 1.0) * 100.0
    idx = idx[["time", "idx_close", "fwd_ret"]].rename(columns={"time": "date"})

    # VN30 constituents — use config_loader.SECTOR_MAP keys filtered or hardcoded
    vn30 = ["ACB", "BID", "BSR", "CTG", "FPT", "GAS", "HDB", "HPG", "LPB",
            "MBB", "MSN", "MWG", "PLX", "SAB", "SHB", "SSB", "SSI", "STB",
            "TCB", "TPB", "VCB", "VHM", "VIB", "VIC", "VJC", "VNM", "VPB", "VRE"]

    closes = {}
    for sym in vn30:
        df = fetch_close_history(sym, days=540)
        if df is None or len(df) < 60:
            continue
        d = df.copy()
        d["date"] = pd.to_datetime(d["date"])
        d = d.set_index("date")["close"]
        d_sma50 = d.rolling(50, min_periods=50).mean()
        closes[sym] = pd.DataFrame({"close": d, "sma50": d_sma50}).reset_index()

    if not closes:
        return {"error": "no VN30 history"}

    all_dates = sorted(set().union(*[c["date"].tolist() for c in closes.values()]))
    breadth_rows = []
    for d in all_dates:
        n_above = 0
        n_total = 0
        for sym, df in closes.items():
            row = df[df["date"] == d]
            if row.empty:
                continue
            c = float(row["close"].iloc[0])
            sm = float(row["sma50"].iloc[0]) if pd.notna(row["sma50"].iloc[0]) else None
            if sm is None:
                continue
            n_total += 1
            if c > sm:
                n_above += 1
        if n_total >= 15:
            breadth_rows.append({
                "date": d,
                "breadth_pct": n_above / n_total * 100.0,
                "n_total": n_total,
            })
    if not breadth_rows:
        return {"error": "no breadth rows"}

    breadth_df = pd.DataFrame(breadth_rows)
    merged = breadth_df.merge(idx, on="date", how="inner").dropna(subset=["fwd_ret"])
    if len(merged) < 50:
        return {"error": f"insufficient merged rows ({len(merged)})"}

    rows = []
    for hi in [50, 55, 60, 65, 70, 75]:
        for lo in [25, 30, 35, 40, 45]:
            if lo >= hi:
                continue
            strong = merged[merged["breadth_pct"] >= hi]["fwd_ret"]
            weak = merged[merged["breadth_pct"] <= lo]["fwd_ret"]
            neut = merged[(merged["breadth_pct"] > lo) & (merged["breadth_pct"] < hi)]["fwd_ret"]
            if len(strong) < 20 or len(weak) < 20:
                continue
            rows.append({
                "strong_cutoff": hi,
                "weak_cutoff": lo,
                "n_strong": int(len(strong)),
                "n_weak": int(len(weak)),
                "n_neutral": int(len(neut)),
                "mean_strong_pct": round(float(strong.mean()), 4),
                "mean_weak_pct": round(float(weak.mean()), 4),
                "spread_pct": round(float(strong.mean() - weak.mean()), 4),
            })
    if not rows:
        return {"error": "no_valid_combinations"}
    best = max(rows, key=lambda r: r["spread_pct"])
    return {"n_merged": int(len(merged)), "all": rows[:30], "best": best}


def calibrate_atr_pct_per_sector(sectors: list[str]) -> dict:
    """Pool ATR% across sector tickers (from existing indicators CSVs). Return P50/P75/P90/P95."""
    out: dict = {}
    for sector in sectors:
        basket = _build_sector_basket(sector)
        pool: list[float] = []
        used: list[str] = []
        for sym in basket:
            csv = DATA_DIR / f"{sym}_indicators.csv"
            if not csv.exists():
                continue
            try:
                df = pd.read_csv(csv, usecols=["atr_pct"])
                vals = df["atr_pct"].dropna().to_numpy()
                if len(vals) > 30:
                    pool.extend(vals.tolist())
                    used.append(sym)
            except Exception:
                continue
        if not pool:
            out[sector] = {"n_obs": 0}
            continue
        arr = np.array(pool)
        out[sector] = {
            "n_obs": int(len(arr)),
            "tickers_used": used,
            "median": round(float(np.median(arr)), 3),
            "p75": round(float(np.percentile(arr, 75)), 3),
            "p90": round(float(np.percentile(arr, 90)), 3),
            "p95": round(float(np.percentile(arr, 95)), 3),
        }
    return out


# ---------------------------------------------------------------------------
# Translate beta → score delta
# ---------------------------------------------------------------------------


def _beta_to_score_delta(beta: float | None, threshold_move_pct: float, basket_std_pct: float) -> int:
    """Map empirical beta into integer score delta.

    Delta scales so that a `threshold_move_pct` move in the driver translates
    into the predicted basket return measured in standard deviations.
    1σ = -3 score; 2σ = -6; -1σ = +3.
    """
    if beta is None or basket_std_pct <= 0:
        return 0
    predicted_pct = beta * threshold_move_pct        # basket pct return at threshold move
    sigmas = predicted_pct / basket_std_pct
    delta = -int(round(sigmas * 3))
    return max(-10, min(10, delta))


# ---------------------------------------------------------------------------
# Render report + YAML
# ---------------------------------------------------------------------------


def render_report(grid: dict, macro: dict, atr_dist: dict, rubric: dict | None = None,
                   risk: dict | None = None, exh: dict | None = None,
                   bias: dict | None = None, breadth: dict | None = None) -> str:
    L = ["# Calibration Report", ""]
    L.append(f"Generated: `{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}`")
    L.append(f"Round-trip cost assumed: {VN_ROUNDTRIP_COST_PCT}%")
    L.append("")

    # --- Job 1 ---
    L.append("## 1. Backtest param grid search")
    L.append("")
    L.append("### Per-ticker best (max avg_R)")
    L.append("")
    L.append("| Ticker | atr_stop | atr_target | hold_bars | n | hit_rate | avg_R | avg_ret_net% |")
    L.append("|---|---|---|---|---|---|---|---|")
    for sym, best in grid.get("per_ticker_best", {}).items():
        L.append(
            f"| {sym} | {best['atr_stop']} | {best['atr_target']} | {best['hold_bars']} | "
            f"{best['n_trades']} | {best['hit_rate']} | {round(best['avg_r'],3)} | "
            f"{round(best['avg_ret_net_pct'],3)} |"
        )
    L.append("")
    L.append("### Pooled top-5 (avg_R across tickers with ≥5 trades)")
    L.append("")
    L.append("| atr_stop | atr_target | hold_bars | n_tickers | pooled_avg_R | pooled_hit_rate | total_trades |")
    L.append("|---|---|---|---|---|---|---|")
    for row in grid.get("pooled_top5", []):
        L.append(
            f"| {row['atr_stop']} | {row['atr_target']} | {row['hold_bars']} | "
            f"{row['n_tickers_with_data']} | {row['pooled_avg_r']} | "
            f"{row['pooled_hit_rate']} | {row['total_trades']} |"
        )
    L.append("")

    # Walk-forward
    if grid.get("walk_forward_enabled") and grid.get("walk_forward"):
        L.append("### Walk-forward (70% train → 30% test, out-of-sample)")
        L.append("")
        L.append("| Ticker | Train params | Train n / avg_R / hit | Test n / avg_R / hit | overfit_gap |")
        L.append("|---|---|---|---|---|")
        n_pos_train = 0
        n_pos_test = 0
        n_total = 0
        for r in grid["walk_forward"]:
            params = r["best_params_on_train"]
            test_r = r.get("test_avg_r")
            train_r = r["train_avg_r"]
            gap = None
            if test_r is not None:
                gap = round(train_r - test_r, 4)
                n_total += 1
                if train_r > 0:
                    n_pos_train += 1
                if test_r > 0:
                    n_pos_test += 1
            L.append(
                f"| {r['ticker']} | {params[0]}/{params[1]}/{params[2]} | "
                f"{r['train_n']} / {train_r} / {r['train_hit_rate']} | "
                f"{r.get('test_n')} / {test_r} / {r.get('test_hit_rate')} | "
                f"{gap if gap is not None else '—'} |"
            )
        if n_total:
            L.append("")
            L.append(
                f"**Robustness check**: {n_pos_train}/{n_total} positive on train, "
                f"{n_pos_test}/{n_total} positive on test. "
                f"Gap > 0.3 = likely overfit. Gap < 0.1 = stable."
            )
        L.append("")

    # --- Job 2 ---
    L.append("## 2. Macro penalty regression (sector basket forward 5D return)")
    L.append("")
    for sector, res in macro.items():
        L.append(f"### {sector}")
        if "error" in res:
            L.append(f"- _{res['error']}_")
            L.append("")
            continue
        L.append(f"- basket: {', '.join(res['basket'])}")
        L.append(f"- n_obs: {res['n_obs']}, 5D ret std: {res['basket_5d_ret_std_pct']}%")
        regs = res.get("regressions", {})
        if regs:
            L.append("")
            L.append("**Univariate OLS**")
            L.append("")
            L.append("| Driver | beta | alpha | r² | n | impl. score Δ at threshold |")
            L.append("|---|---|---|---|---|---|")
            for driver, r in regs.items():
                if r.get("beta") is None:
                    L.append(f"| {driver} | _missing_ | — | — | {r.get('n')} | — |")
                    continue
                if driver == "brent_ret_5d":
                    threshold = -5.0
                elif driver == "dxy_ret_20d":
                    threshold = 2.0
                else:
                    threshold = 1.5
                delta = _beta_to_score_delta(r["beta"], threshold, res["basket_5d_ret_std_pct"])
                L.append(
                    f"| {driver} | {r['beta']} | {r['alpha']} | {r['r2']} | "
                    f"{r['n']} | {delta:+d} @ {threshold:+.1f}% |"
                )

        multi = res.get("multi_driver_ols")
        if multi and "error" not in multi:
            L.append("")
            L.append("**Multi-driver OLS (all 3 simultaneously)**")
            L.append("")
            L.append(f"- n={multi['n']}, R²={multi['r2']}, adj-R²={multi['adj_r2']}")
            L.append("")
            L.append("| Driver | beta | t-stat | significant (|t|>2)? |")
            L.append("|---|---|---|---|")
            for d, b in multi["betas"].items():
                t = multi["t_stats"][d]
                sig = "✓" if abs(t) > 2.0 else ""
                L.append(f"| {d} | {b} | {t} | {sig} |")
            L.append(f"| intercept | {multi['intercept']} | {multi['intercept_t']} | "
                     f"{'✓' if abs(multi['intercept_t']) > 2.0 else ''} |")
            if multi.get("collinearity_pairs"):
                L.append("")
                L.append("Collinearity (|corr| > 0.7 = problematic):")
                for pair, c in multi["collinearity_pairs"].items():
                    flag = " ⚠️" if abs(c) > 0.7 else ""
                    L.append(f"- {pair}: {c}{flag}")
        L.append("")

    # --- Job 3 ---
    L.append("## 3. ATR% distribution per sector")
    L.append("")
    L.append("| Sector | n_obs | tickers | median | p75 | p90 | p95 | recommended atr_pct_low | atr_pct_high |")
    L.append("|---|---|---|---|---|---|---|---|---|")
    for sector, res in atr_dist.items():
        if not res.get("n_obs"):
            continue
        L.append(
            f"| {sector} | {res['n_obs']} | {len(res.get('tickers_used',[]))} | "
            f"{res['median']} | {res['p75']} | {res['p90']} | {res['p95']} | "
            f"{res['median']} | {res['p90']} |"
        )
    L.append("")

    # --- Job 4 ---
    if rubric and rubric.get("signals"):
        L.append("## 4. Score rubric calibration")
        L.append("")
        L.append(f"- Horizon: {rubric['horizon_days']}-day forward return")
        L.append(f"- Max |t-stat| (anchor for ±10 weight scale): {rubric.get('max_abs_t')}")
        L.append("")
        L.append("| Signal | current | n_true | n_false | μ_true% | μ_false% | diff% | t-stat | sig? | recommended |")
        L.append("|---|---|---|---|---|---|---|---|---|---|")
        for r in rubric["signals"]:
            if r.get("error"):
                L.append(f"| {r['signal']} | {r['current_weight']} | _{r.get('error')}_ | — | — | — | — | — | — | — |")
                continue
            sig_mark = "✓" if r["significant"] else ""
            rec = r.get("recommended_weight", "—")
            L.append(
                f"| {r['signal']} | {r['current_weight']:+d} | {r['n_true']} | {r['n_false']} | "
                f"{r['mean_ret_true_pct']} | {r['mean_ret_false_pct']} | {r['diff_pct']} | "
                f"{r['t_stat']} | {sig_mark} | {rec:+d} |"
            )
        L.append("")
        L.append("Interpretation: signals with |t|<2 (non-significant) recommended weight 0. "
                 "Significant signals scaled linearly s.t. max-|t| = ±10. Sign follows direction "
                 "of forward return — positive μ_diff → positive weight.")
        L.append("")

    # --- Job 5 ---
    if risk:
        L.append("## 5. Risk threshold optimization")
        L.append("")
        for param, res in risk.items():
            if "error" in res:
                L.append(f"### {param}: _{res['error']}_")
                continue
            best = res.get("best")
            L.append(f"### {param}")
            if best:
                L.append(f"- **best cutoff: {best['cutoff']}** (|t|={best['abs_t']}, diff={best['mean_diff_pct']}%, n_t={best['n_true']}, n_f={best['n_false']})")
            L.append("")
            L.append("| cutoff | n_true | n_false | diff% | t-stat |")
            L.append("|---|---|---|---|---|")
            for r in res.get("all", []):
                if "error" in r:
                    L.append(f"| {r['cutoff']} | _{r.get('error')}_ | — | — | — |")
                    continue
                L.append(f"| {r['cutoff']} | {r['n_true']} | {r['n_false']} | {r['mean_diff_pct']} | {r['t_stat']} |")
            L.append("")

    # --- Job 6 ---
    if exh:
        L.append("## 6. Exhaustion cap + triple-risk validation")
        L.append("")
        es = exh.get("exhaustion_state", {})
        L.append("### `BREAKOUT_WITH_EXHAUSTION_RISK` state forward 5D return")
        if es and "warning" not in es:
            L.append(f"- n_triggered: {es.get('n_true')}, n_other: {es.get('n_false')}")
            L.append(f"- mean when triggered: {es.get('mean_ret_true_pct')}% vs not: {es.get('mean_ret_false_pct')}%")
            L.append(f"- diff: {es.get('diff_pct')}%, t-stat: {es.get('t_stat')}")
            L.append(f"- **verdict: {es.get('verdict')}**")
        else:
            L.append(f"- _{es.get('warning', 'no data')}_, n_true={es.get('n_true')}, n_false={es.get('n_false')}")
        L.append("")
        ts = exh.get("triple_risk_combo", {})
        L.append("### Triple-risk combo forward 5D return")
        if ts and "warning" not in ts:
            L.append(f"- n_triggered: {ts.get('n_true')}, n_other: {ts.get('n_false')}")
            L.append(f"- mean when triggered: {ts.get('mean_ret_true_pct')}% vs not: {ts.get('mean_ret_false_pct')}%")
            L.append(f"- diff: {ts.get('diff_pct')}%, t-stat: {ts.get('t_stat')}")
            L.append(f"- **verdict: {ts.get('verdict')}**")
        else:
            L.append(f"- _{ts.get('warning', 'no data')}_, n_true={ts.get('n_true')}, n_false={ts.get('n_false')}")
        L.append("")

    # --- Job 7 ---
    if bias:
        L.append("## 7. Base bias score threshold")
        L.append("")
        if bias.get("error"):
            L.append(f"_{bias['error']}_")
        else:
            best = bias.get("best")
            if best:
                L.append(f"- **best threshold: score ≥ {best['threshold']}** (|t|={best['abs_t']}, diff={best['diff_pct']}%)")
            L.append("")
            L.append("| threshold | n_above | n_below | mean_above% | mean_below% | diff% | t-stat |")
            L.append("|---|---|---|---|---|---|---|")
            for r in bias.get("all", []):
                L.append(f"| {r['threshold']} | {r['n_above']} | {r['n_below']} | "
                         f"{r['mean_above_pct']} | {r['mean_below_pct']} | "
                         f"{r['diff_pct']} | {r['t_stat']} |")
            L.append("")
            if bias.get("note"):
                L.append(f"> {bias['note']}")
                L.append("")

    # --- Job 8 ---
    if breadth:
        L.append("## 8. VN30 breadth threshold optimization")
        L.append("")
        if breadth.get("error"):
            L.append(f"_{breadth['error']}_")
        else:
            L.append(f"- n_merged daily observations: {breadth.get('n_merged')}")
            best = breadth.get("best")
            if best:
                L.append(f"- **best (strong ≥{best['strong_cutoff']}%, weak ≤{best['weak_cutoff']}%)**: "
                         f"spread {best['spread_pct']}% (mean_strong {best['mean_strong_pct']}% vs mean_weak {best['mean_weak_pct']}%)")
            L.append("")
            L.append("| strong_≥ | weak_≤ | n_strong | n_weak | mean_strong% | mean_weak% | spread% |")
            L.append("|---|---|---|---|---|---|---|")
            for r in breadth.get("all", [])[:15]:
                L.append(f"| {r['strong_cutoff']} | {r['weak_cutoff']} | "
                         f"{r['n_strong']} | {r['n_weak']} | "
                         f"{r['mean_strong_pct']} | {r['mean_weak_pct']} | {r['spread_pct']} |")
            L.append("")

    L.append("## Notes")
    L.append("")
    L.append("- **Backtest**: max(avg_R) per ticker is post-cost (round-trip 0.40%). Higher hit_rate ≠ better avg_R.")
    L.append("- **Macro regression**: univariate OLS; multi-driver collinearity not handled. Beta translated to score Δ via `(beta × threshold) / basket_std_pct → σ × 3 → rounded`.")
    L.append("- **ATR% recommendation**: median = sizing-neutral baseline, P90 = high-vol cap. Override `configs/sectors/*.yaml` accordingly.")
    L.append("- **Caveat**: sample sizes small for some sectors. Treat as starting point, not final values.")
    return "\n".join(L) + "\n"


def write_calibrated_yaml(grid: dict, macro: dict, atr_dist: dict) -> Path:
    """Emit configs/calibrated.yaml summarizing recommended values."""
    L = ["# Auto-generated calibration output", ""]
    L.append(f"# Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    L.append("# Source: scripts/calibrate.py")
    L.append("# Apply manually to configs/default.yaml + configs/sectors/*.yaml after review.")
    L.append("")

    # Recommended global backtest defaults from pooled top
    top = grid.get("pooled_top5", [])
    if top:
        best = top[0]
        L.append("backtest_defaults:")
        L.append(f"  atr_stop_mult: {best['atr_stop']}")
        L.append(f"  atr_target_mult: {best['atr_target']}")
        L.append(f"  hold_bars: {best['hold_bars']}")
        L.append(f"  pooled_avg_r: {best['pooled_avg_r']}")
        L.append(f"  pooled_hit_rate: {best['pooled_hit_rate']}")
        L.append(f"  total_trades: {best['total_trades']}")
        L.append("")

    # Per-sector ATR% values
    L.append("sectors:")
    for sector, res in atr_dist.items():
        if not res.get("n_obs"):
            continue
        L.append(f"  {sector}:")
        L.append(f"    atr_pct_low_recommended: {res['median']}")
        L.append(f"    atr_pct_high_recommended: {res['p90']}")
        L.append(f"    n_obs: {res['n_obs']}")
        if sector in macro and macro[sector].get("regressions"):
            L.append(f"    macro_regression:")
            for driver, r in macro[sector]["regressions"].items():
                if r.get("beta") is None:
                    continue
                if driver == "brent_ret_5d":
                    threshold = -5.0
                elif driver == "dxy_ret_20d":
                    threshold = 2.0
                else:
                    threshold = 1.5
                delta = _beta_to_score_delta(
                    r["beta"], threshold, macro[sector]["basket_5d_ret_std_pct"]
                )
                L.append(f"      {driver}:")
                L.append(f"        beta: {r['beta']}")
                L.append(f"        r2: {r['r2']}")
                L.append(f"        n: {r['n']}")
                L.append(f"        recommended_score_delta: {delta}")
                L.append(f"        threshold_pct: {threshold}")

    path = CONFIGS_DIR / "calibrated.yaml"
    path.write_text("\n".join(L) + "\n", encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> int:
    p = argparse.ArgumentParser(description="Calibration suite.")
    # Default pool: all tickers that have an indicators CSV.
    default_tickers = sorted({
        f.stem.replace("_indicators", "")
        for f in DATA_DIR.glob("*_indicators.csv")
    })
    p.add_argument("--tickers", nargs="+", default=default_tickers,
                   help="Tickers with existing indicators CSVs for backtest grid.")
    p.add_argument("--sectors", nargs="+",
                   default=["oil_gas", "banking", "steel", "real_estate", "utilities"],
                   help="Sectors to regress.")
    p.add_argument("--extra-fetch", nargs="+", default=[],
                   help="Additional tickers to fetch close history for sector baskets.")
    p.add_argument("--walk-forward", action="store_true",
                   help="Split data 70/30 per ticker; fit on train, eval on test.")
    args = p.parse_args()

    # Pre-fetch close history for sector basket members if needed.
    needed: set[str] = set(args.extra_fetch)
    for sec in args.sectors:
        for tkr, s in SECTOR_MAP.items():
            if s == sec:
                needed.add(tkr)
    print(f"[calibrate] fetching close history for {len(needed)} tickers (cache reused if present)")
    for sym in sorted(needed):
        fetch_close_history(sym, days=540)

    print(f"[calibrate] job 1: backtest grid (n_tickers={len(args.tickers)}, walk_forward={args.walk_forward})")
    grid = grid_search_backtest(args.tickers, walk_forward=args.walk_forward)

    print("[calibrate] job 2: macro regression")
    macro = calibrate_macro_penalties(args.sectors)

    print("[calibrate] job 3: ATR% distribution")
    atr_dist = calibrate_atr_pct_per_sector(args.sectors)

    print("[calibrate] job 4: score rubric weights")
    rubric = calibrate_score_rubric(args.tickers, horizon=5)

    print("[calibrate] job 5: risk thresholds")
    risk = calibrate_risk_thresholds(args.tickers, horizon=5)

    print("[calibrate] job 6: exhaustion + triple risk validation")
    exh = calibrate_exhaustion_cap(args.tickers, horizon=5)

    print("[calibrate] job 7: base_bias thresholds")
    bias = calibrate_base_bias_thresholds(args.tickers, horizon=5)

    print("[calibrate] job 8: VN30 breadth thresholds")
    breadth = calibrate_breadth_thresholds()

    report = render_report(grid, macro, atr_dist, rubric,
                            risk=risk, exh=exh, bias=bias, breadth=breadth)
    report_path = REPORTS_DIR / "calibration_report.md"
    report_path.write_text(report, encoding="utf-8")
    print(f"[calibrate] wrote {report_path}")

    yaml_path = write_calibrated_yaml(grid, macro, atr_dist)
    print(f"[calibrate] wrote {yaml_path}")

    # Dump raw JSON for inspection.
    raw = {"grid": grid, "macro": macro, "atr_dist": atr_dist}
    raw_path = DATA_DIR / "calibration_raw.json"
    raw_path.write_text(json.dumps(raw, indent=2, ensure_ascii=False, default=str),
                        encoding="utf-8")
    print(f"[calibrate] wrote {raw_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
