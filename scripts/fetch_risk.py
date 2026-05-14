#!/usr/bin/env python3
"""Fetch risk data for stock risk analysis → data/risk_snapshot_{ticker}_{date}.json

Usage:
  python fetch_risk.py --ticker HPG
"""

import argparse
import json
import os
import sys
from datetime import date, datetime, timedelta
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

_vnstock_key = os.getenv("VNSTOCK_API_KEY", "")
if _vnstock_key:
    try:
        import vnstock
        vnstock.change_api_key(_vnstock_key)
    except Exception as e:
        print(f"[WARN] Could not set vnstock API key: {e}", file=sys.stderr)

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

TICKER_INDUSTRY_MAP = {}
for industry, tickers in KNOWN_PEERS.items():
    for t in tickers:
        TICKER_INDUSTRY_MAP[t] = industry


def safe_float(val, default=None):
    try:
        v = float(val)
        return None if (v != v) else v  # NaN check
    except (TypeError, ValueError):
        return default


def safe_int(val, default=None):
    try:
        return int(float(val))
    except (TypeError, ValueError):
        return default


def fetch_overview(ticker: str) -> dict:
    result = {"auditor": None, "listing_date": None, "exchange": None,
              "charter_capital_b": None, "industry": TICKER_INDUSTRY_MAP.get(ticker)}
    try:
        from vnstock3 import Vnstock
        stock = Vnstock().stock(symbol=ticker, source="VCI")
        overview = stock.company.overview()
        if overview is not None and not overview.empty:
            row = overview.iloc[0]
            result["auditor"] = str(row.get("auditor", "") or "").strip() or None
            result["listing_date"] = str(row.get("listing_date", "") or "").strip() or None
            result["exchange"] = str(row.get("exchange", "") or "").strip() or None
            charter = row.get("charter_capital") or row.get("charterCapital")
            if charter:
                result["charter_capital_b"] = round(safe_float(charter, 0) / 1e9, 1)
    except Exception as e:
        result["_error"] = str(e)
    return result


def fetch_shareholders(ticker: str) -> tuple[dict, list]:
    ownership = {"top1_pct": None, "top5_pct": None, "foreign_pct": None,
                 "state_pct": None, "hhi_top5": None}
    shareholders = []
    try:
        from vnstock3 import Vnstock
        stock = Vnstock().stock(symbol=ticker, source="VCI")
        df = stock.company.shareholders()
        if df is not None and not df.empty:
            pcts = []
            for _, row in df.iterrows():
                name = str(row.get("shareholder_name", row.get("name", "")) or "").strip()
                pct_raw = row.get("owned_percent") or row.get("share_percent") or row.get("percent") or 0
                pct = safe_float(pct_raw, 0)
                if pct and pct > 1:
                    pct = pct / 100.0  # normalize if stored as percentage
                pct_display = round(pct * 100, 2) if pct <= 1 else round(pct, 2)
                shareholders.append({"name": name, "pct": pct_display})
                pcts.append(pct_display)

            pcts_sorted = sorted(pcts, reverse=True)
            ownership["top1_pct"] = pcts_sorted[0] if pcts_sorted else None
            ownership["top5_pct"] = round(sum(pcts_sorted[:5]), 2) if len(pcts_sorted) >= 1 else None
            ownership["hhi_top5"] = round(sum(p**2 for p in pcts_sorted[:5]), 1) if pcts_sorted else None

            # Detect state/foreign ownership
            for sh in shareholders:
                name_lower = sh["name"].lower()
                if any(k in name_lower for k in ["nhà nước", "state", "scic", "vietcombank", "nhnn"]):
                    ownership["state_pct"] = (ownership["state_pct"] or 0) + sh["pct"]
                if any(k in name_lower for k in ["foreign", "nước ngoài", "ftse", "veil", "dragon"]):
                    ownership["foreign_pct"] = (ownership["foreign_pct"] or 0) + sh["pct"]
    except Exception as e:
        ownership["_error"] = str(e)

    return ownership, shareholders[:10]


def fetch_events(ticker: str) -> list:
    events = []
    try:
        from vnstock3 import Vnstock
        stock = Vnstock().stock(symbol=ticker, source="VCI")
        df = stock.company.events()
        if df is not None and not df.empty:
            cutoff = (datetime.now() - timedelta(days=730)).strftime("%Y-%m-%d")
            for _, row in df.iterrows():
                ev_date = str(row.get("event_date") or row.get("date") or "")
                if ev_date and ev_date < cutoff:
                    continue
                ev_type = str(row.get("event_type") or row.get("type") or "").strip()
                ev_detail = str(row.get("event_description") or row.get("description") or row.get("detail") or "").strip()

                # Flag risky event types
                risk_keywords = [
                    "phát hành", "esop", "chuyển đổi", "trái phiếu", "niêm yết bổ sung",
                    "tăng vốn", "ngoại trừ", "going concern", "từ chối", "vi phạm",
                    "cảnh báo", "điều tra", "thay kiểm toán", "thay ban lãnh đạo",
                    "tạm dừng", "hủy niêm yết", "margin call", "cầm cố cổ phiếu",
                ]
                is_risky = any(k in (ev_type + ev_detail).lower() for k in risk_keywords)

                events.append({
                    "date": ev_date,
                    "type": ev_type,
                    "detail": ev_detail[:200],
                    "is_risky": is_risky,
                })
            events.sort(key=lambda x: x.get("date", ""), reverse=True)
    except Exception as e:
        events.append({"_error": str(e)})
    return events[:20]


def fetch_shares_trend(ticker: str) -> dict:
    result = {"current_m": None, "1y_ago_m": None, "dilution_pct": None}
    try:
        from vnstock3 import Vnstock
        stock = Vnstock().stock(symbol=ticker, source="VCI")
        # Try to get shares outstanding from balance sheet
        bs = stock.finance.balance_sheet(period="quarter", lang="en")
        if bs is not None and not bs.empty:
            # Look for shares outstanding column
            shares_cols = [c for c in bs.columns if "share" in c.lower() and "outstanding" in c.lower()]
            if not shares_cols:
                shares_cols = [c for c in bs.columns if "charter_capital" in c.lower() or "equity" in c.lower()]

            # Fallback: get from overview charter capital
            from vnstock3 import Vnstock as V2
            ov = V2().stock(symbol=ticker, source="VCI").company.overview()
            if ov is not None and not ov.empty:
                row = ov.iloc[0]
                charter = safe_float(row.get("charter_capital") or row.get("charterCapital"), 0)
                if charter:
                    # Shares = charter_capital / 10000 (par value 10,000 VND)
                    shares_m = round(charter / 10000 / 1e6, 2)
                    result["current_m"] = shares_m
    except Exception as e:
        result["_error"] = str(e)
    return result


def fetch_debt_snapshot(ticker: str) -> dict:
    result = {
        "total_debt_b": None, "equity_b": None, "de_ratio": None,
        "interest_expense_b": None, "ebit_b": None, "coverage": None,
        "net_debt_b": None,
    }
    try:
        from vnstock3 import Vnstock
        stock = Vnstock().stock(symbol=ticker, source="VCI")

        # Balance sheet for debt & equity
        bs = stock.finance.balance_sheet(period="quarter", lang="en")
        if bs is not None and not bs.empty:
            latest_bs = bs.iloc[0]
            # Try common column names
            debt_cols = [c for c in bs.columns if any(k in c.lower() for k in ["long_term_debt", "short_term_debt", "total_liab", "borrow"])]
            equity_cols = [c for c in bs.columns if any(k in c.lower() for k in ["owner_equity", "equity", "stockholder"])]
            cash_cols = [c for c in bs.columns if any(k in c.lower() for k in ["cash", "cash_equivalent"])]

            total_debt = 0
            for col in debt_cols[:3]:
                v = safe_float(latest_bs.get(col), 0)
                if v and v > 0:
                    total_debt = max(total_debt, v)

            equity = 0
            for col in equity_cols[:2]:
                v = safe_float(latest_bs.get(col), 0)
                if v and v > total_debt / 10:
                    equity = max(equity, v)

            cash = 0
            for col in cash_cols[:1]:
                v = safe_float(latest_bs.get(col), 0)
                if v and v > 0:
                    cash = v

            # Determine scale (VCI uses billion, raw vs 1e9)
            scale = 1
            if total_debt > 1e6:  # likely in millions or raw
                scale = 1e9
            elif total_debt > 1e3:
                scale = 1e6

            total_debt_b = round(total_debt / scale, 1) if total_debt else None
            equity_b = round(equity / scale, 1) if equity else None
            cash_b = round(cash / scale, 1) if cash else None

            result["total_debt_b"] = total_debt_b
            result["equity_b"] = equity_b
            if total_debt_b and equity_b and equity_b > 0:
                result["de_ratio"] = round(total_debt_b / equity_b, 2)
            if total_debt_b and cash_b:
                result["net_debt_b"] = round(total_debt_b - cash_b, 1)

        # Income statement for interest expense & EBIT (TTM)
        is_df = stock.finance.income_statement(period="quarter", lang="en")
        if is_df is not None and not is_df.empty:
            recent_4q = is_df.head(4)
            interest_cols = [c for c in is_df.columns if "interest" in c.lower() and "expense" in c.lower()]
            ebit_cols = [c for c in is_df.columns if "operating_profit" in c.lower() or "ebit" in c.lower()]
            revenue_cols = [c for c in is_df.columns if "revenue" in c.lower() or "net_sales" in c.lower()]

            interest_ttm = 0
            for col in interest_cols[:1]:
                vals = [safe_float(v, 0) for v in recent_4q[col].tolist()]
                interest_ttm = sum(abs(v) for v in vals if v)

            ebit_ttm = 0
            for col in ebit_cols[:1]:
                vals = [safe_float(v, 0) for v in recent_4q[col].tolist()]
                ebit_ttm = sum(v for v in vals if v)

            # Determine scale from revenue
            rev_ttm = 0
            for col in revenue_cols[:1]:
                vals = [safe_float(v, 0) for v in recent_4q[col].tolist()]
                rev_ttm = sum(v for v in vals if v)

            is_scale = 1
            if rev_ttm > 1e12:
                is_scale = 1e9
            elif rev_ttm > 1e9:
                is_scale = 1e6

            result["interest_expense_b"] = round(interest_ttm / is_scale, 1) if interest_ttm else None
            result["ebit_b"] = round(ebit_ttm / is_scale, 1) if ebit_ttm else None
            if result["ebit_b"] and result["interest_expense_b"] and result["interest_expense_b"] > 0:
                result["coverage"] = round(result["ebit_b"] / result["interest_expense_b"], 2)

    except Exception as e:
        result["_error"] = str(e)
    return result


def build_snapshot(ticker: str) -> dict:
    warnings = []

    print(f"[INFO] Fetching overview for {ticker}...", file=sys.stderr)
    overview = fetch_overview(ticker)
    if overview.get("_error"):
        warnings.append(f"overview_fetch_failed: {overview['_error'][:80]}")

    print(f"[INFO] Fetching shareholders for {ticker}...", file=sys.stderr)
    ownership, shareholders = fetch_shareholders(ticker)
    if ownership.get("_error"):
        warnings.append(f"shareholders_fetch_failed: {ownership['_error'][:80]}")

    print(f"[INFO] Fetching events for {ticker}...", file=sys.stderr)
    events = fetch_events(ticker)
    if events and events[0].get("_error"):
        warnings.append(f"events_fetch_failed: {events[0]['_error'][:80]}")
        events = []

    print(f"[INFO] Fetching shares trend for {ticker}...", file=sys.stderr)
    shares_trend = fetch_shares_trend(ticker)
    if shares_trend.get("_error"):
        warnings.append(f"shares_trend_fetch_failed: {shares_trend['_error'][:80]}")

    print(f"[INFO] Fetching debt snapshot for {ticker}...", file=sys.stderr)
    debt_snapshot = fetch_debt_snapshot(ticker)
    if debt_snapshot.get("_error"):
        warnings.append(f"debt_fetch_failed: {debt_snapshot['_error'][:80]}")

    # Validate completeness
    if not overview.get("auditor"):
        warnings.append("auditor_info_missing")
    if not ownership.get("top1_pct"):
        warnings.append("ownership_data_missing")
    if not debt_snapshot.get("de_ratio"):
        warnings.append("debt_ratio_missing")
    if not debt_snapshot.get("coverage"):
        warnings.append("interest_coverage_missing")

    return {
        "ticker": ticker,
        "date": TODAY,
        "industry": TICKER_INDUSTRY_MAP.get(ticker, "UNKNOWN"),
        "overview": overview,
        "ownership": ownership,
        "shareholders": shareholders,
        "events": events,
        "shares_trend": shares_trend,
        "debt_snapshot": debt_snapshot,
        "warnings": warnings,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--ticker", required=True)
    parser.add_argument("--force", action="store_true", help="Force re-fetch even if cache exists")
    args = parser.parse_args()

    ticker = args.ticker.upper().strip()
    out_path = DATA_DIR / f"risk_snapshot_{ticker}_{TODAY}.json"

    if out_path.exists() and not args.force:
        print(f"Cache hit: {out_path}")
        return

    snapshot = build_snapshot(ticker)

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(snapshot, f, ensure_ascii=False, indent=2)

    print(f"Fresh fetch: {out_path}")


if __name__ == "__main__":
    main()
