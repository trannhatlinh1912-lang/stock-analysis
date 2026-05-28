#!/usr/bin/env python3
"""External macro + foreign-flow overlay.

Pulls daily series for:
  - Brent crude (yfinance BZ=F)
  - WTI crude  (yfinance CL=F) — for oil & gas sector
  - USD/VND   (yfinance VND=X)
  - DXY       (yfinance DX-Y.NYB)
  - Foreign-flow snapshot (vnstock KBS price_board) — latest only, not historical

Cache layout
------------
- data/macro_overlay_{DATE}.json   (shared across symbols)
- data/{SYMBOL}_foreign_snapshot.json (per symbol, latest price_board row)

Decision framework reads these if present.

Usage
-----
    python scripts/external_overlay.py --symbol BSR
"""
from __future__ import annotations

import argparse
import json
import sys
import warnings
from datetime import date
from pathlib import Path

warnings.filterwarnings("ignore")

REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = REPO_ROOT / "data"
DATA_DIR.mkdir(exist_ok=True)

MACRO_TICKERS = {
    "brent": "BZ=F",
    "wti": "CL=F",
    "usdvnd": "VND=X",
    "dxy": "DX-Y.NYB",
}


def _pct(a, b):
    if a is None or b is None or b == 0:
        return None
    return round((a / b - 1.0) * 100.0, 3)


def fetch_macro(period: str = "6mo") -> dict:
    import pandas as pd
    import yfinance as yf

    out: dict = {"as_of": date.today().isoformat(), "tickers": {}}
    for name, ticker in MACRO_TICKERS.items():
        try:
            df = yf.download(ticker, period=period, progress=False, auto_adjust=True)
            if df is None or len(df) == 0:
                out["tickers"][name] = {"error": "no_data"}
                continue
            close = df["Close"]
            if isinstance(close, pd.DataFrame):
                close = close.iloc[:, 0]
            close = close.dropna()
            if len(close) < 25:
                out["tickers"][name] = {"error": f"short_series_{len(close)}"}
                continue
            last = float(close.iloc[-1])
            ret_5d = _pct(last, float(close.iloc[-6])) if len(close) > 5 else None
            ret_20d = _pct(last, float(close.iloc[-21])) if len(close) > 20 else None
            ret_60d = _pct(last, float(close.iloc[-61])) if len(close) > 60 else None
            sma20 = float(close.tail(20).mean())
            sma50 = float(close.tail(50).mean()) if len(close) >= 50 else None
            trend = (
                "up" if sma50 and last > sma20 > sma50
                else "down" if sma50 and last < sma20 < sma50
                else "flat"
            )
            out["tickers"][name] = {
                "ticker": ticker,
                "last_date": close.index[-1].strftime("%Y-%m-%d"),
                "last_close": round(last, 4),
                "sma20": round(sma20, 4),
                "sma50": round(sma50, 4) if sma50 else None,
                "ret_5d_pct": ret_5d,
                "ret_20d_pct": ret_20d,
                "ret_60d_pct": ret_60d,
                "trend": trend,
            }
        except Exception as e:
            out["tickers"][name] = {"error": str(e)[:120]}

    # Quick narrative
    brent = out["tickers"].get("brent", {})
    usdvnd = out["tickers"].get("usdvnd", {})
    out["narrative"] = {
        "oil_regime": brent.get("trend", "unknown"),
        "usdvnd_regime": usdvnd.get("trend", "unknown"),
        "fx_pressure": (
            "high" if usdvnd.get("ret_20d_pct") and usdvnd["ret_20d_pct"] > 1.5
            else "low" if usdvnd.get("ret_20d_pct") and usdvnd["ret_20d_pct"] < -1.0
            else "neutral"
        ),
    }
    return out


def fetch_foreign_snapshot(symbol: str) -> dict | None:
    """Latest foreign buy/sell from KBS price_board."""
    try:
        from vnstock.api.trading import Trading
        t = Trading(symbol=symbol, source="KBS")
        df = t.price_board([symbol])
        if df is None or len(df) == 0:
            return {"error": "empty price_board"}
        row = df.iloc[0]
        fb = row.get("foreign_buy_volume")
        fs = row.get("foreign_sell_volume")
        fr = row.get("foreign_room")
        total_vol = row.get("volume_accumulated")
        def _to_float(v):
            try:
                return float(v) if v is not None else None
            except (TypeError, ValueError):
                return None
        fb_f = _to_float(fb)
        fs_f = _to_float(fs)
        fr_f = _to_float(fr)
        tv_f = _to_float(total_vol)
        net = (fb_f - fs_f) if (fb_f is not None and fs_f is not None) else None
        share = (
            round((fb_f + fs_f) / tv_f * 100.0, 2)
            if (fb_f is not None and fs_f is not None and tv_f and tv_f > 0)
            else None
        )
        bias = (
            "net_buy" if net is not None and net > 0
            else "net_sell" if net is not None and net < 0
            else "flat" if net == 0
            else "unknown"
        )
        return {
            "symbol": symbol,
            "as_of": date.today().isoformat(),
            "foreign_buy_volume": fb_f,
            "foreign_sell_volume": fs_f,
            "foreign_room": fr_f,
            "total_volume": tv_f,
            "net_foreign_volume": net,
            "foreign_share_of_volume_pct": share,
            "bias": bias,
        }
    except Exception as e:
        return {"error": str(e)[:160]}


def run(symbol: str | None) -> tuple[Path, Path | None]:
    macro = fetch_macro("6mo")
    macro_path = DATA_DIR / f"macro_overlay_{date.today().isoformat()}.json"
    macro_path.write_text(json.dumps(macro, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"[external_overlay] macro -> {macro_path}")

    foreign_path = None
    if symbol:
        fs = fetch_foreign_snapshot(symbol)
        foreign_path = DATA_DIR / f"{symbol}_foreign_snapshot.json"
        foreign_path.write_text(
            json.dumps(fs or {}, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        print(f"[external_overlay] foreign -> {foreign_path}")

    return macro_path, foreign_path


def main() -> int:
    p = argparse.ArgumentParser(description="External macro + foreign-flow overlay.")
    p.add_argument("--symbol", required=False, help="Ticker for foreign-flow snapshot.")
    args = p.parse_args()
    sym = args.symbol.upper() if args.symbol else None
    run(sym)
    return 0


if __name__ == "__main__":
    sys.exit(main())
