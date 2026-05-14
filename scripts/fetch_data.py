#!/usr/bin/env python3
"""Fetch macro data from free APIs → data/macro_snapshot_{date}.json"""

import json
import os
import sys
from datetime import date, timedelta
from pathlib import Path

# Load .env
try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent.parent / "data" / ".env")
except ImportError:
    pass

SKILL_DIR = Path(__file__).parent.parent
DATA_DIR = SKILL_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)

TODAY = date.today().isoformat()
OUTPUT_FILE = DATA_DIR / f"macro_snapshot_{TODAY}.json"

# Activate personal vnstock API key if available
_vnstock_key = os.getenv("VNSTOCK_API_KEY", "")
if _vnstock_key:
    try:
        import vnstock as _vs
        _vs.change_api_key(_vnstock_key)
    except Exception:
        pass


def signal(value, thresholds):
    """thresholds = (bearish_threshold, bullish_threshold, higher_is_bearish)"""
    bear, bull, higher_is_bearish = thresholds
    if higher_is_bearish:
        if value >= bear:
            return "bearish"
        if value <= bull:
            return "bullish"
    else:
        if value <= bear:
            return "bearish"
        if value >= bull:
            return "bullish"
    return "neutral"


def fetch_fred():
    """Fetch US macro data from FRED API."""
    api_key = os.getenv("FRED_API_KEY", "")
    if not api_key or api_key == "your_key_here":
        print("[WARN] FRED_API_KEY not set — skipping FRED data", file=sys.stderr)
        return {}

    try:
        from fredapi import Fred
        fred = Fred(api_key=api_key)

        def latest(series_id):
            s = fred.get_series(series_id, observation_start=(date.today() - timedelta(days=90)).isoformat())
            return float(s.dropna().iloc[-1])

        fed_rate = latest("FEDFUNDS")
        # YoY CPI: lấy 500 ngày để đảm bảo đủ 13 tháng dữ liệu
        s_cpi = fred.get_series("CPIAUCSL", observation_start=(date.today() - timedelta(days=500)).isoformat()).dropna()
        us_cpi_yoy = round((s_cpi.iloc[-1] / s_cpi.iloc[-13] - 1) * 100, 2) if len(s_cpi) >= 13 else None

        unemp = latest("UNRATE")
        yield_spread = latest("T10Y2Y")
        dxy = latest("DTWEXBGS")
        oil = latest("DCOILWTICO")

        return {
            "fed_rate": {"value": round(fed_rate, 2), "signal": signal(fed_rate, (4.5, 3.0, True))},
            "us_cpi_yoy": {"value": us_cpi_yoy, "signal": signal(us_cpi_yoy or 0, (4.0, 2.5, True))},
            "us_unemployment": {"value": round(unemp, 1), "signal": signal(unemp, (3.5, 4.5, False))},
            "yield_curve_10y2y": {"value": round(yield_spread, 2), "signal": signal(yield_spread, (0, 0.5, False))},
            "dxy": {"value": round(dxy, 1), "signal": signal(dxy, (105, 100, True))},
            "oil_wti": {"value": round(oil, 1), "signal": signal(oil, (90, 70, True))},
        }
    except Exception as e:
        print(f"[WARN] FRED fetch error: {e}", file=sys.stderr)
        return {}


def fetch_vnindex():
    """Fetch VN-Index via vnstock API."""
    try:
        from vnstock.api.quote import Quote
        from datetime import datetime
        end = datetime.today().strftime("%Y-%m-%d")
        start = (datetime.today() - timedelta(days=10)).strftime("%Y-%m-%d")
        df = Quote(symbol="VNINDEX", source="VCI").history(start=start, end=end, interval="1D")
        if df is not None and not df.empty:
            return float(df["close"].dropna().iloc[-1])
    except Exception:
        pass
    return None


def fetch_yfinance():
    """Fetch market data via yfinance."""
    try:
        import yfinance as yf

        def price(ticker):
            t = yf.Ticker(ticker)
            hist = t.history(period="5d")
            return float(hist["Close"].dropna().iloc[-1]) if not hist.empty else None

        gold = price("GC=F")
        vix = price("^VIX")
        sp500 = price("^GSPC")
        vnindex = fetch_vnindex()
        usd_vnd = price("USDVND=X")

        return {
            "gold": {"value": round(gold, 0) if gold else None, "signal": "neutral"},
            "vix": {"value": round(vix, 1) if vix else None, "signal": signal(vix or 20, (25, 15, True))},
            "sp500": {"value": round(sp500, 0) if sp500 else None, "signal": "neutral"},
            "vnindex": {"value": round(vnindex, 0) if vnindex else None, "signal": "neutral"},
            "usd_vnd": {"value": round(usd_vnd, 0) if usd_vnd else None, "signal": signal(usd_vnd or 25000, (25500, 24500, True))},
        }
    except Exception as e:
        print(f"[WARN] yfinance fetch error: {e}", file=sys.stderr)
        return {}


def fetch_worldbank():
    """Fetch Vietnam macro data from World Bank API (no key needed)."""
    try:
        import wbgapi as wb

        def latest_value(indicator, country="VNM"):
            data = list(wb.data.fetch(indicator, country, mrv=1))
            return data[0]["value"] if data and data[0]["value"] is not None else None

        gdp_growth = latest_value("NY.GDP.MKTP.KD.ZG")
        cpi_vn = latest_value("FP.CPI.TOTL.ZG")
        fdi = latest_value("BX.KLT.DINV.WD.GD.ZS")

        return {
            "gdp_growth_vn": {"value": round(gdp_growth, 1) if gdp_growth else None, "signal": signal(gdp_growth or 0, (5.0, 7.0, False))},
            "cpi_vn_yoy": {"value": round(cpi_vn, 1) if cpi_vn else None, "signal": signal(cpi_vn or 0, (4.5, 3.0, True))},
            "fdi_pct_gdp": {"value": round(fdi, 1) if fdi else None, "signal": "neutral"},
        }
    except Exception as e:
        print(f"[WARN] World Bank fetch error: {e}", file=sys.stderr)
        return {}


def overall_signal(global_data, vietnam_data):
    """Simple weighted signal count."""
    all_signals = []
    for d in [global_data, vietnam_data]:
        for v in d.values():
            if isinstance(v, dict) and "signal" in v:
                all_signals.append(v["signal"])

    counts = {"bullish": all_signals.count("bullish"), "bearish": all_signals.count("bearish"), "neutral": all_signals.count("neutral")}
    if counts["bearish"] > counts["bullish"] + 1:
        return "bearish"
    if counts["bullish"] > counts["bearish"] + 1:
        return "bullish"
    return "neutral"


def main():
    if OUTPUT_FILE.exists():
        print(f"[stock-macro] Cache hit: {OUTPUT_FILE.name}")
        return

    print("[stock-macro] Fetching global data (FRED)...")
    fred_data = fetch_fred()

    print("[stock-macro] Fetching market data (yfinance)...")
    yf_data = fetch_yfinance()

    print("[stock-macro] Fetching Vietnam data (World Bank)...")
    wb_data = fetch_worldbank()

    global_data = {**fred_data, **{k: v for k, v in yf_data.items() if k not in ("vnindex", "usd_vnd")}}
    vietnam_data = {**wb_data, **{k: yf_data[k] for k in ("vnindex", "usd_vnd") if k in yf_data}}

    snapshot = {
        "date": TODAY,
        "global": global_data,
        "vietnam": vietnam_data,
        "overall_signal": overall_signal(global_data, vietnam_data),
    }

    OUTPUT_FILE.write_text(json.dumps(snapshot, indent=2, ensure_ascii=False))
    print(f"[stock-macro] Saved → {OUTPUT_FILE.name}")


if __name__ == "__main__":
    main()
