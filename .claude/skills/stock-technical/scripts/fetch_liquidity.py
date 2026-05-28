#!/usr/bin/env python3
"""Fetch market cap + 20-day avg daily trading value (ADTV) for tradable gate.

Market cap = latest close × shares_outstanding (= share_capital / par_value).
VN par value standard = 10,000 VND. Source: VCI close in 1000-VND units.

ADTV = mean(close × volume) over last 20 trading days, in million VND.

Output: data/liquidity/{TICKER}.json + reports/liquidity_summary.md
"""
from __future__ import annotations

import argparse
import json
import sys
import warnings
from datetime import date, timedelta, datetime
from pathlib import Path

import pandas as pd

warnings.filterwarnings("ignore")

REPO_ROOT = Path(__file__).resolve().parent.parent
LIQ_DIR = REPO_ROOT / "data" / "liquidity"
FUND_DIR = REPO_ROOT / "data" / "fundamentals"
REPORTS_DIR = REPO_ROOT / "reports"
LIQ_DIR.mkdir(parents=True, exist_ok=True)
REPORTS_DIR.mkdir(exist_ok=True)

# VN par value standard.
PAR_VALUE_VND = 10_000

# Layer 1C tradable thresholds (calibrated):
#   Core mode: market cap > 500B VND, ADTV 20d > 1B VND/day
#   T+ mode:   market cap > 2000B VND, ADTV 20d > 5B VND/day
THRESHOLDS = {
    "core": {"market_cap_b_vnd": 500.0, "adtv_b_vnd": 1.0, "min_years_listed": 2},
    "t_plus": {"market_cap_b_vnd": 2000.0, "adtv_b_vnd": 5.0, "min_years_listed": 2},
}


def fetch_one(symbol: str) -> dict:
    """Compute liquidity metrics for one ticker."""
    out: dict = {
        "symbol": symbol,
        "fetched_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }

    # 1. Get latest share_capital from fundamentals cache.
    fund_path = FUND_DIR / f"{symbol}.json"
    if not fund_path.exists():
        out["error"] = "no fundamentals cache — run fetch_fundamentals.py first"
        return out
    try:
        fund = json.loads(fund_path.read_text())
    except Exception as e:
        out["error"] = f"fundamentals read err: {e}"
        return out

    per_year = fund.get("per_year", {})
    years = sorted(per_year.keys(), reverse=True)
    if not years:
        out["error"] = "no per_year data"
        return out
    latest_y = years[0]
    sc = per_year[latest_y].get("share_capital")
    if sc is None or sc <= 0:
        out["error"] = f"share_capital missing for {latest_y}"
        return out

    shares_outstanding = sc / PAR_VALUE_VND
    out["latest_year"] = latest_y
    out["share_capital_vnd"] = sc
    out["shares_outstanding_estimated"] = round(shares_outstanding, 0)

    # 2. Fetch last 30 trading days of price + volume.
    try:
        from vnstock.api.quote import Quote
        end = date.today()
        start = end - timedelta(days=60)  # buffer for weekends
        q = Quote(symbol=symbol, source="VCI")
        df = q.history(start=start.isoformat(), end=end.isoformat(), interval="1D")
    except Exception as e:
        out["error"] = f"quote fetch err: {str(e)[:200]}"
        return out

    if df is None or len(df) < 5:
        out["error"] = f"insufficient price data: {0 if df is None else len(df)} rows"
        return out

    df = df.copy()
    df.columns = [c.lower() for c in df.columns]
    df["time"] = pd.to_datetime(df["time"])
    df = df.sort_values("time").reset_index(drop=True)

    # VCI close in 1000-VND units → convert
    df["close_vnd"] = df["close"] * 1000.0
    df["trading_value_vnd"] = df["close_vnd"] * df["volume"]

    # Latest close
    latest_close_vnd = float(df["close_vnd"].iloc[-1])
    market_cap_vnd = latest_close_vnd * shares_outstanding
    out["latest_close_vnd"] = latest_close_vnd
    out["latest_date"] = df["time"].iloc[-1].strftime("%Y-%m-%d")
    out["market_cap_vnd"] = round(market_cap_vnd, 0)
    out["market_cap_b_vnd"] = round(market_cap_vnd / 1e9, 2)

    # ADTV 20-day
    last20 = df.tail(20)
    adtv_vnd = float(last20["trading_value_vnd"].mean())
    out["adtv_20d_vnd"] = round(adtv_vnd, 0)
    out["adtv_20d_b_vnd"] = round(adtv_vnd / 1e9, 3)
    out["n_days_used"] = int(len(last20))

    # Listing duration (first available indicator data ≥ 2 years ago?)
    fund_years = len(years)
    out["fundamentals_n_years"] = fund_years
    out["min_years_listed_ok"] = fund_years >= 2

    # Verdict per mode
    core_pass = (
        out["market_cap_b_vnd"] >= THRESHOLDS["core"]["market_cap_b_vnd"]
        and out["adtv_20d_b_vnd"] >= THRESHOLDS["core"]["adtv_b_vnd"]
        and out["min_years_listed_ok"]
    )
    t_plus_pass = (
        out["market_cap_b_vnd"] >= THRESHOLDS["t_plus"]["market_cap_b_vnd"]
        and out["adtv_20d_b_vnd"] >= THRESHOLDS["t_plus"]["adtv_b_vnd"]
        and out["min_years_listed_ok"]
    )
    out["core_tradable"] = bool(core_pass)
    out["t_plus_tradable"] = bool(t_plus_pass)

    return out


def main() -> int:
    p = argparse.ArgumentParser(description="Fetch market cap + ADTV for tradable gate.")
    # Default: all tickers with cached fundamentals
    default = sorted([f.stem for f in FUND_DIR.glob("*.json")])
    p.add_argument("--tickers", nargs="+", default=default,
                   help="Tickers (default: all with fundamentals cache).")
    args = p.parse_args()

    print(f"[fetch_liquidity] {len(args.tickers)} tickers")
    results = {}
    for sym in args.tickers:
        print(f"[fetch] {sym} ...", end=" ", flush=True)
        try:
            r = fetch_one(sym)
            results[sym] = r
            path = LIQ_DIR / f"{sym}.json"
            path.write_text(json.dumps(r, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
            if "error" in r:
                print(f"ERR: {r['error']}")
            else:
                print(f"mcap={r['market_cap_b_vnd']}B, adtv={r['adtv_20d_b_vnd']}B, core={r['core_tradable']}, t+={r['t_plus_tradable']}")
        except Exception as e:
            print(f"FAILED: {e}")
            results[sym] = {"symbol": sym, "error": str(e)[:300]}

    # Report
    L = [f"# Liquidity Summary", ""]
    L.append(f"- Generated: `{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}`")
    L.append(f"- N tickers: {len(args.tickers)}")
    L.append(f"- Core threshold: mcap > {THRESHOLDS['core']['market_cap_b_vnd']}B VND, ADTV > {THRESHOLDS['core']['adtv_b_vnd']}B/day")
    L.append(f"- T+ threshold:   mcap > {THRESHOLDS['t_plus']['market_cap_b_vnd']}B VND, ADTV > {THRESHOLDS['t_plus']['adtv_b_vnd']}B/day")
    L.append("")
    L.append("| Ticker | Market cap (B) | Close (VND) | ADTV 20d (B) | Core? | T+? |")
    L.append("|---|---|---|---|---|---|")
    for sym, r in results.items():
        if "error" in r:
            L.append(f"| {sym} | _err: {r['error'][:50]}_ | — | — | — | — |")
            continue
        L.append(f"| {sym} | {r['market_cap_b_vnd']:,} | {r['latest_close_vnd']:,.0f} | "
                 f"{r['adtv_20d_b_vnd']:.3f} | {'✓' if r['core_tradable'] else '✗'} | "
                 f"{'✓' if r['t_plus_tradable'] else '✗'} |")
    L.append("")

    report = "\n".join(L) + "\n"
    report_path = REPORTS_DIR / "liquidity_summary.md"
    report_path.write_text(report, encoding="utf-8")
    print(f"[fetch_liquidity] wrote {report_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
