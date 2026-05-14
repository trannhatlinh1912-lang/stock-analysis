#!/usr/bin/env python3
"""Fetch industry data from vnstock + yfinance → data/industry_snapshot_{ticker}_{date}.json

Usage:
  python fetch_industry.py --ticker HPG
"""

import argparse
import json
import os
import sys
from datetime import date, timedelta
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent.parent / "data" / ".env")
except ImportError:
    pass

SKILL_DIR = Path(__file__).parent.parent
DATA_DIR = SKILL_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)

TODAY = date.today().isoformat()

# Activate personal API key if available
_vnstock_key = os.getenv("VNSTOCK_API_KEY", "")
if _vnstock_key:
    try:
        import vnstock
        vnstock.change_api_key(_vnstock_key)
    except Exception as e:
        print(f"[WARN] Could not set vnstock API key: {e}", file=sys.stderr)

# ---------------------------------------------------------------------------
# Static reference data
# ---------------------------------------------------------------------------

KNOWN_PEERS = {
    "STEEL":        ["HPG", "HSG", "NKG", "SMC"],
    "BANK":         ["VCB", "BID", "CTG", "MBB", "TCB", "ACB", "VPB"],
    "REALESTATE":   ["VHM", "NVL", "KDH", "PDR", "DXG", "NLG"],
    "SECURITIES":   ["SSI", "VCI", "HCM", "VND", "MBS"],
    "RETAIL":       ["MWG", "FRT", "PNJ", "DGW"],
    "ENERGY":       ["GAS", "PLX", "PVD", "BSR"],
    "PHARMA":       ["DHG", "DMC", "IMP", "TRA"],
    "TECHNOLOGY":   ["FPT", "CMG"],
    "FERTILIZER":   ["DPM", "DCM", "BFC"],
    "CONSTRUCTION": ["CTD", "HBC", "VCG"],
}

TICKER_INDUSTRY_MAP = {
    "HPG": "STEEL",  "HSG": "STEEL",  "NKG": "STEEL",  "SMC": "STEEL",
    "VCB": "BANK",   "BID": "BANK",   "CTG": "BANK",   "MBB": "BANK",
    "TCB": "BANK",   "ACB": "BANK",   "VPB": "BANK",   "HDB": "BANK",
    "STB": "BANK",   "SHB": "BANK",
    "VHM": "REALESTATE", "NVL": "REALESTATE", "KDH": "REALESTATE",
    "PDR": "REALESTATE", "DXG": "REALESTATE", "NLG": "REALESTATE",
    "SSI": "SECURITIES", "VCI": "SECURITIES", "HCM": "SECURITIES",
    "VND": "SECURITIES", "MBS": "SECURITIES",
    "MWG": "RETAIL", "FRT": "RETAIL", "PNJ": "RETAIL", "DGW": "RETAIL",
    "GAS": "ENERGY", "PLX": "ENERGY", "PVD": "ENERGY", "BSR": "ENERGY",
    "DHG": "PHARMA", "DMC": "PHARMA", "IMP": "PHARMA", "TRA": "PHARMA",
    "FPT": "TECHNOLOGY", "CMG": "TECHNOLOGY",
    "DPM": "FERTILIZER", "DCM": "FERTILIZER",
    "CTD": "CONSTRUCTION", "HBC": "CONSTRUCTION", "VCG": "CONSTRUCTION",
}

INDUSTRY_NAMES = {
    "STEEL": "Thép", "BANK": "Ngân hàng", "REALESTATE": "Bất động sản",
    "SECURITIES": "Chứng khoán", "RETAIL": "Bán lẻ",
    "ENERGY": "Năng lượng / Dầu khí", "PHARMA": "Dược phẩm",
    "TECHNOLOGY": "Công nghệ", "FERTILIZER": "Phân bón",
    "CONSTRUCTION": "Xây dựng",
}


# ---------------------------------------------------------------------------
# Industry detection
# ---------------------------------------------------------------------------

def detect_industry(ticker: str) -> tuple[str, str]:
    code = TICKER_INDUSTRY_MAP.get(ticker.upper())
    if code:
        return code, INDUSTRY_NAMES.get(code, code)
    return "UNKNOWN", "Không xác định"


# ---------------------------------------------------------------------------
# Financial data — vnstock.api.financial.Finance (new API)
# ---------------------------------------------------------------------------

def _get_item(df, item_id: str, col: str):
    """Extract a single cell from wide-format income statement."""
    mask = df["item_id"] == item_id
    if not mask.any() or col not in df.columns:
        return None
    val = df.loc[mask, col].values[0]
    return float(val) if val is not None and str(val) not in ("nan", "None") else None


def fetch_financials_vnstock(ticker: str) -> dict:
    """
    Fetch income statement via vnstock.api Finance class.
    Returns compact metrics. Revenue trend is QoQ (4 quarters window)
    since free tier provides 4 quarters; personal key provides more.
    """
    try:
        from vnstock.api.financial import Finance

        df = Finance(source="VCI", symbol=ticker, show_log=False).income_statement(
            period="quarter", lang="en"
        )
        if df is None or df.empty:
            return {}

        # Quarter columns are those containing '-Q'
        q_cols = [c for c in df.columns if "-Q" in str(c)]
        if not q_cols:
            return {}

        latest_q = q_cols[0]   # most recent quarter
        prev_q   = q_cols[1] if len(q_cols) > 1 else None
        yago_q   = q_cols[4] if len(q_cols) > 4 else None  # same Q, prior year

        net_sales_latest = _get_item(df, "isa3", latest_q)
        gross_profit     = _get_item(df, "isa5", latest_q)
        net_income       = _get_item(df, "isa20", latest_q)
        net_sales_prev   = _get_item(df, "isa3", prev_q) if prev_q else None
        net_sales_yago   = _get_item(df, "isa3", yago_q) if yago_q else None

        gross_margin = (
            round(gross_profit / net_sales_latest * 100, 1)
            if gross_profit and net_sales_latest else None
        )
        net_margin = (
            round(net_income / net_sales_latest * 100, 1)
            if net_income and net_sales_latest else None
        )

        # Prefer YoY if we have it (personal key gives >4 quarters)
        if net_sales_latest and net_sales_yago and net_sales_yago != 0:
            revenue_growth = round((net_sales_latest / net_sales_yago - 1) * 100, 1)
            growth_basis = "yoy"
        elif net_sales_latest and net_sales_prev and net_sales_prev != 0:
            revenue_growth = round((net_sales_latest / net_sales_prev - 1) * 100, 1)
            growth_basis = "qoq"
        else:
            revenue_growth = None
            growth_basis = "n/a"

        return {
            "revenue_growth": revenue_growth,
            "growth_basis": growth_basis,
            "gross_margin": gross_margin,
            "net_margin": net_margin,
            "quarters_available": len(q_cols),
            "latest_quarter": latest_q,
        }
    except Exception as e:
        print(f"[WARN] Financial fetch error for {ticker}: {e}", file=sys.stderr)
        return {}


# ---------------------------------------------------------------------------
# Price returns — yfinance
# ---------------------------------------------------------------------------

def fetch_vnindex_return(start: str, end: str):
    try:
        from vnstock.api.quote import Quote
        df = Quote(symbol="VNINDEX", source="VCI").history(start=start, end=end, interval="1D")
        if df is not None and not df.empty:
            prices = df["close"].dropna()
            if len(prices) >= 2:
                return round((float(prices.iloc[-1]) / float(prices.iloc[0]) - 1) * 100, 1)
    except Exception:
        pass
    return None


def fetch_price_returns(tickers: list) -> dict:
    try:
        import yfinance as yf
        from datetime import datetime

        end = datetime.today().strftime("%Y-%m-%d")
        starts = {
            "1y": (datetime.today() - timedelta(days=365)).strftime("%Y-%m-%d"),
            "6m": (datetime.today() - timedelta(days=182)).strftime("%Y-%m-%d"),
            "3m": (datetime.today() - timedelta(days=91)).strftime("%Y-%m-%d"),
        }

        def pct_return(tkr: str, start: str):
            try:
                hist = yf.download(tkr, start=start, end=end, progress=False, auto_adjust=True)
                if hist.empty or len(hist) < 2:
                    return None
                close = hist["Close"]
                # Handle multi-level columns from yfinance
                if hasattr(close, "columns"):
                    close = close.iloc[:, 0]
                prices = close.dropna()
                return round((float(prices.iloc[-1]) / float(prices.iloc[0]) - 1) * 100, 1)
            except Exception:
                return None

        vnindex_1y = fetch_vnindex_return(starts["1y"], end)

        results = {}
        for period, start in starts.items():
            vals = [r for t in tickers[:5] if (r := pct_return(f"{t}.VN", start)) is not None]
            results[f"sector_{period}"] = round(sum(vals) / len(vals), 1) if vals else None
            if period == "1y":
                results["peers_with_data"] = len(vals)

        results["vnindex_1y"] = vnindex_1y
        rel = results.get("sector_1y")
        results["relative_1y"] = (
            round(rel - vnindex_1y, 1) if rel is not None and vnindex_1y is not None else None
        )
        return results
    except Exception as e:
        print(f"[WARN] Price return fetch error: {e}", file=sys.stderr)
        return {}


# ---------------------------------------------------------------------------
# Cycle classification
# ---------------------------------------------------------------------------

def classify_cycle_signals(sector_avg: dict, price_returns: dict) -> dict:
    signals = {}

    rev = sector_avg.get("revenue_growth")
    basis = sector_avg.get("growth_basis", "n/a")
    # Adjust thresholds: QoQ is typically smaller than YoY
    if rev is not None:
        threshold_high = 5 if basis == "qoq" else 15
        threshold_low  = -3 if basis == "qoq" else -5
        if rev > threshold_high:
            signals["revenue_trend"] = "accelerating"
        elif rev > 0:
            signals["revenue_trend"] = "recovering"
        elif rev > threshold_low:
            signals["revenue_trend"] = "flat"
        else:
            signals["revenue_trend"] = "declining"
    else:
        signals["revenue_trend"] = "unknown"

    net_m = sector_avg.get("net_margin")
    if net_m is not None:
        if net_m > 15:
            signals["margin_trend"] = "peak"
        elif net_m > 8:
            signals["margin_trend"] = "expanding"
        elif net_m > 3:
            signals["margin_trend"] = "stable"
        elif net_m > 0:
            signals["margin_trend"] = "compressed"
        else:
            signals["margin_trend"] = "deeply_compressed"
    else:
        signals["margin_trend"] = "unknown"

    relative = price_returns.get("relative_1y")
    sector_3m = price_returns.get("sector_3m")
    if relative is not None:
        signals["price_vs_index"] = (
            "outperform" if relative > 10 else
            "underperform" if relative < -10 else "neutral"
        )
    elif sector_3m is not None:
        signals["price_vs_index"] = (
            "outperform" if sector_3m > 5 else
            "underperform" if sector_3m < -5 else "neutral"
        )
    else:
        signals["price_vs_index"] = "unknown"

    signals["growth_basis"] = basis
    return signals


def determine_cycle_phase(signals: dict) -> str:
    score = 0
    score += {"accelerating": 2, "recovering": 1, "flat": 0, "declining": -2}.get(signals.get("revenue_trend", ""), 0)
    score += {"peak": 2, "expanding": 2, "stable": 1, "compressed": -1, "deeply_compressed": -2}.get(signals.get("margin_trend", ""), 0)
    score += {"outperform": 1, "neutral": 0, "underperform": -1}.get(signals.get("price_vs_index", ""), 0)

    if score >= 4:
        return "đỉnh" if signals.get("margin_trend") == "peak" else "tăng_trưởng"
    elif score >= 2:
        return "tăng_trưởng"
    elif score >= 0:
        return "hồi_phục"
    elif score >= -2:
        return "đáy"
    else:
        return "suy_giảm"


def avg_financials(financials: dict) -> dict:
    keys = ["revenue_growth", "gross_margin", "net_margin"]
    result = {}
    for k in keys:
        vals = [v[k] for v in financials.values() if v.get(k) is not None]
        result[k] = round(sum(vals) / len(vals), 1) if vals else None
    # Pass through growth_basis from first peer that has it
    for v in financials.values():
        if v.get("growth_basis") and v["growth_basis"] != "n/a":
            result["growth_basis"] = v["growth_basis"]
            break
    else:
        result["growth_basis"] = "n/a"
    return result


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--ticker", required=True)
    args = parser.parse_args()

    ticker = args.ticker.upper().strip()
    output_file = DATA_DIR / f"industry_snapshot_{ticker}_{TODAY}.json"

    if output_file.exists():
        print(f"[stock-industry] Cache hit: {output_file.name}")
        return

    print(f"[stock-industry] Fetching data for {ticker}...")

    industry_code, industry_name = detect_industry(ticker)
    print(f"[stock-industry] Industry: {industry_name} ({industry_code})")

    peers = KNOWN_PEERS.get(industry_code, [ticker])
    if ticker not in peers:
        peers = [ticker] + [p for p in peers if p != ticker]
    peers = peers[:5]
    print(f"[stock-industry] Peers: {peers}")

    print("[stock-industry] Fetching financials (vnstock Finance API)...")
    financials = {}
    for p in peers:
        fin = fetch_financials_vnstock(p)
        if fin:
            financials[p] = fin

    print("[stock-industry] Fetching price returns (yfinance)...")
    price_returns = fetch_price_returns(peers)

    sector_avg = avg_financials(financials)
    cycle_signals = classify_cycle_signals(sector_avg, price_returns)
    cycle_phase = determine_cycle_phase(cycle_signals)

    snapshot = {
        "date": TODAY,
        "input_ticker": ticker,
        "industry": {"code": industry_code, "name": industry_name},
        "peers": peers,
        "financials": financials,
        "sector_avg": sector_avg,
        "price_return": price_returns,
        "cycle_signals": cycle_signals,
        "cycle_phase": cycle_phase,
    }

    output_file.write_text(json.dumps(snapshot, indent=2, ensure_ascii=False))
    print(f"[stock-industry] Saved → {output_file.name}")


if __name__ == "__main__":
    main()
