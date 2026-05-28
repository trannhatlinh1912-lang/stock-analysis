#!/usr/bin/env python3
"""Market context module — VNINDEX overlay + per-symbol relative strength.

Fetches VNINDEX daily OHLCV, computes index trend indicators (SMA20/50/100,
MACD hist, vol_ratio), and provides a helper to compute relative-strength
(RS) line of a symbol vs VNINDEX. Output is cached daily so multiple
symbols share one fetch.

Outputs
-------
- data/market_context_{DATE}.json   (cache key = report date)

Usage
-----
    python scripts/market_context.py --start 2024-05-18 --end 2026-05-18

    # Optional: compute RS for a specific symbol against the cached index
    python scripts/market_context.py --symbol VCB --csv data/VCB_price_VCI.csv \
        --start 2024-05-18 --end 2026-05-18
"""

from __future__ import annotations

import argparse
import json
import sys
import warnings
from datetime import date
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = REPO_ROOT / "data"
DATA_DIR.mkdir(exist_ok=True)

INDEX_SYMBOL = "VNINDEX"


def _fetch_index(start: str, end: str, source: str = "VCI") -> Optional[pd.DataFrame]:
    """Fetch VNINDEX OHLCV. Returns sorted DataFrame or None on failure."""
    try:
        from vnstock.api.quote import Quote
    except Exception as e:
        print(f"[market_context] vnstock import failed: {e}", file=sys.stderr)
        return None

    try:
        q = Quote(symbol=INDEX_SYMBOL, source=source)
        df = q.history(start=start, end=end, interval="1D")
    except Exception as e:
        print(f"[market_context] fetch failed source={source}: {e}", file=sys.stderr)
        return None

    if df is None or len(df) == 0:
        return None

    df = df.copy()
    df.columns = [c.lower() for c in df.columns]
    if "time" in df.columns:
        df["time"] = pd.to_datetime(df["time"])
    elif "date" in df.columns:
        df["time"] = pd.to_datetime(df["date"])
    df = df.sort_values("time").reset_index(drop=True)
    return df


def _ema(series: pd.Series, span: int) -> pd.Series:
    return series.ewm(span=span, adjust=False).mean()


def _macd_hist(close: pd.Series, fast: int = 12, slow: int = 26, sig: int = 9) -> pd.Series:
    macd_line = _ema(close, fast) - _ema(close, slow)
    signal_line = _ema(macd_line, sig)
    return macd_line - signal_line


def _classify_regime(row: pd.Series) -> str:
    """Map index snapshot to one of risk_on / risk_off / neutral."""
    close = row["close"]
    sma20 = row["sma20"]
    sma50 = row["sma50"]
    sma100 = row["sma100"]
    macd_hist = row["macd_hist"]

    if pd.isna(sma100):
        # Not enough history; fall back to short-term alignment.
        if pd.notna(sma20) and pd.notna(sma50) and close > sma20 > sma50 and macd_hist > 0:
            return "risk_on"
        if pd.notna(sma20) and pd.notna(sma50) and close < sma20 < sma50 and macd_hist < 0:
            return "risk_off"
        return "neutral"

    if close > sma20 > sma50 > sma100 and macd_hist > 0:
        return "risk_on"
    if close < sma20 < sma50 < sma100 and macd_hist < 0:
        return "risk_off"
    return "neutral"


def compute_index_context(df: pd.DataFrame) -> dict:
    """Compute trend snapshot for the index. df has columns time, close, volume."""
    work = df.copy()
    work["sma20"] = work["close"].rolling(20).mean()
    work["sma50"] = work["close"].rolling(50).mean()
    work["sma100"] = work["close"].rolling(100).mean()
    work["macd_hist"] = _macd_hist(work["close"])
    work["vol_ma20"] = work["volume"].rolling(20).mean()
    work["vol_ratio"] = work["volume"] / work["vol_ma20"]
    work["ret_1d"] = work["close"].pct_change()
    work["ret_5d"] = work["close"].pct_change(5)
    work["ret_20d"] = work["close"].pct_change(20)

    last = work.iloc[-1]
    regime = _classify_regime(last)

    def _f(v):
        return None if pd.isna(v) else round(float(v), 4)

    return {
        "as_of": last["time"].strftime("%Y-%m-%d"),
        "close": _f(last["close"]),
        "sma20": _f(last["sma20"]),
        "sma50": _f(last["sma50"]),
        "sma100": _f(last["sma100"]),
        "macd_hist": _f(last["macd_hist"]),
        "vol_ratio": _f(last["vol_ratio"]),
        "ret_1d_pct": _f(last["ret_1d"] * 100 if pd.notna(last["ret_1d"]) else np.nan),
        "ret_5d_pct": _f(last["ret_5d"] * 100 if pd.notna(last["ret_5d"]) else np.nan),
        "ret_20d_pct": _f(last["ret_20d"] * 100 if pd.notna(last["ret_20d"]) else np.nan),
        "regime": regime,
    }


def compute_relative_strength(
    symbol_df: pd.DataFrame, index_df: pd.DataFrame
) -> dict:
    """Compute RS line = close_symbol / close_index, with 20D slope.

    Returns dict: rs_now, rs_slope_20d_pct, label.
    """
    a = symbol_df[["time", "close"]].rename(columns={"close": "sym_close"})
    b = index_df[["time", "close"]].rename(columns={"close": "idx_close"})
    m = a.merge(b, on="time", how="inner").sort_values("time").reset_index(drop=True)
    if len(m) < 25:
        return {"rs_now": None, "rs_slope_20d_pct": None, "label": "insufficient_data"}

    m["rs"] = m["sym_close"] / m["idx_close"]
    rs_now = float(m["rs"].iloc[-1])
    rs_20d_ago = float(m["rs"].iloc[-21])
    slope_pct = (rs_now / rs_20d_ago - 1.0) * 100

    if slope_pct > 2.0:
        label = "leader"
    elif slope_pct < -2.0:
        label = "laggard"
    else:
        label = "inline"

    return {
        "rs_now": round(rs_now, 6),
        "rs_slope_20d_pct": round(slope_pct, 3),
        "label": label,
    }


def compute_vn30_breadth(start: str, end: str) -> dict:
    """Fetch close for each VN30 constituent, compute % above SMA50.

    Returns dict with n_total, n_above_sma50, breadth_pct, sample errors.
    """
    try:
        from vnstock import Vnstock
        from vnstock.api.quote import Quote
        v = Vnstock().stock(symbol="ACB", source="VCI")
        tickers = list(v.listing.symbols_by_group("VN30"))
    except Exception as e:
        return {"error": f"listing_failed: {str(e)[:120]}"}

    above = 0
    total = 0
    errors: list[str] = []
    for sym in tickers:
        try:
            q = Quote(symbol=sym, source="VCI")
            df = q.history(start=start, end=end, interval="1D")
            if df is None or len(df) < 50:
                errors.append(f"{sym}:short_{len(df) if df is not None else 0}")
                continue
            close = df["close"].dropna()
            if len(close) < 50:
                continue
            sma50 = float(close.tail(50).mean())
            last = float(close.iloc[-1])
            total += 1
            if last > sma50:
                above += 1
        except Exception as e:
            errors.append(f"{sym}:{str(e)[:50]}")

    breadth = round(above / total * 100.0, 2) if total else None
    return {
        "n_total": total,
        "n_above_sma50": above,
        "breadth_pct": breadth,
        "regime": (
            "strong" if breadth is not None and breadth >= 60
            else "weak" if breadth is not None and breadth <= 40
            else "neutral" if breadth is not None
            else "unknown"
        ),
        "errors_count": len(errors),
        "sample_errors": errors[:5],
    }


def load_macro_overlay_if_present() -> dict | None:
    today = date.today().isoformat()
    path = DATA_DIR / f"macro_overlay_{today}.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except Exception:
        return None


def load_or_build_context(
    start: str, end: str, force: bool = False, include_breadth: bool = False
) -> dict:
    """Return cached context for today, or build it."""
    today = date.today().isoformat()
    cache_path = DATA_DIR / f"market_context_{today}.json"

    if cache_path.exists() and not force:
        try:
            cached = json.loads(cache_path.read_text())
            # If breadth requested but cache lacks it, rebuild only breadth + merge.
            if include_breadth and "breadth" not in cached:
                cached["breadth"] = compute_vn30_breadth(start, end)
                cache_path.write_text(json.dumps(cached, indent=2, ensure_ascii=False))
            return cached
        except Exception:
            pass

    df = _fetch_index(start, end)
    if df is None or len(df) < 30:
        ctx = {
            "as_of": today,
            "regime": "unknown",
            "error": "failed_to_fetch_index_or_insufficient_data",
        }
    else:
        ctx = compute_index_context(df)
        df.to_csv(DATA_DIR / f"{INDEX_SYMBOL}_price_VCI.csv", index=False)

    if include_breadth:
        ctx["breadth"] = compute_vn30_breadth(start, end)

    macro = load_macro_overlay_if_present()
    if macro:
        ctx["macro_overlay"] = macro

    cache_path.write_text(json.dumps(ctx, indent=2, ensure_ascii=False))
    print(f"[market_context] -> {cache_path}")
    return ctx


def main():
    p = argparse.ArgumentParser(description="VNINDEX market context + RS helper.")
    p.add_argument("--start", required=True, help="YYYY-MM-DD")
    p.add_argument("--end", required=True, help="YYYY-MM-DD")
    p.add_argument("--symbol", default=None, help="Optional: compute RS for this symbol.")
    p.add_argument("--csv", default=None, help="Symbol price CSV path (required if --symbol).")
    p.add_argument("--force", action="store_true", help="Bypass daily cache.")
    p.add_argument("--breadth", action="store_true", help="Include VN30 breadth (slow, ~30 fetches).")
    args = p.parse_args()

    ctx = load_or_build_context(
        args.start, args.end, force=args.force, include_breadth=args.breadth
    )
    print(json.dumps(ctx, indent=2, ensure_ascii=False))

    if args.symbol and args.csv:
        sym_df = pd.read_csv(args.csv)
        sym_df["time"] = pd.to_datetime(sym_df["time"])
        idx_csv = DATA_DIR / f"{INDEX_SYMBOL}_price_VCI.csv"
        if not idx_csv.exists():
            print(f"[market_context] missing {idx_csv}; cannot compute RS", file=sys.stderr)
            return 1
        idx_df = pd.read_csv(idx_csv)
        idx_df["time"] = pd.to_datetime(idx_df["time"])
        rs = compute_relative_strength(sym_df, idx_df)
        print(json.dumps({"symbol": args.symbol, "relative_strength": rs}, indent=2, ensure_ascii=False))

    return 0


if __name__ == "__main__":
    sys.exit(main())
