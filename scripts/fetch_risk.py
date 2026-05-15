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


def _get_item(df, item_id: str, col: str):
    """Extract a value from vnstock v4 long-format finance DataFrame by item_id."""
    rows = df[df["item_id"] == item_id]
    if rows.empty:
        return None
    return safe_float(rows.iloc[0].get(col))


def _quarter_cols(df, n=4):
    """Return the n most recent quarter column names from a v4 finance DataFrame."""
    cols = [c for c in df.columns if len(c) == 7 and c[4] == "-" and c[5] == "Q"]
    return sorted(cols, reverse=True)[:n]


def fetch_overview(ticker: str) -> dict:
    result = {"auditor": None, "listing_date": None, "exchange": None,
              "issue_share_m": None, "state_pct": None, "foreign_pct": None,
              "industry": TICKER_INDUSTRY_MAP.get(ticker)}
    try:
        from vnstock import Company
        comp = Company(symbol=ticker, source="VCI")
        ov = comp.overview()
        if ov is not None and not ov.empty:
            row = ov.iloc[0]
            listing_raw = str(row.get("listing_date") or "")
            result["listing_date"] = listing_raw[:10] if listing_raw else None
            result["exchange"] = str(row.get("com_group_code") or "").strip() or None
            issue = safe_float(row.get("issue_share"))
            if issue:
                result["issue_share_m"] = round(issue / 1e6, 2)
            state = safe_float(row.get("state_percentage"))
            foreign = safe_float(row.get("foreigner_percentage"))
            if state is not None:
                result["state_pct"] = round(state * 100, 2)
            if foreign is not None:
                result["foreign_pct"] = round(foreign * 100, 4)
    except Exception as e:
        result["_error"] = str(e)
    return result


def fetch_shareholders(ticker: str) -> tuple[dict, list]:
    ownership = {"top1_pct": None, "top5_pct": None, "foreign_pct": None,
                 "state_pct": None, "hhi_top5": None}
    shareholders = []
    try:
        from vnstock import Company
        comp = Company(symbol=ticker, source="VCI")
        df = comp.shareholders()
        if df is not None and not df.empty:
            pcts = []
            for _, row in df.iterrows():
                name = str(row.get("share_holder") or "").strip()
                pct_raw = row.get("share_own_percent") or 0
                pct = safe_float(pct_raw, 0)
                # v4 stores as decimal (0.921) → convert to percentage display
                pct_display = round(pct * 100, 4) if pct <= 1 else round(pct, 4)
                shareholders.append({"name": name, "pct": pct_display})
                pcts.append(pct_display)

            pcts_sorted = sorted(pcts, reverse=True)
            ownership["top1_pct"] = pcts_sorted[0] if pcts_sorted else None
            ownership["top5_pct"] = round(sum(pcts_sorted[:5]), 2) if pcts_sorted else None
            ownership["hhi_top5"] = round(sum(p**2 for p in pcts_sorted[:5]), 1) if pcts_sorted else None

            state_kw = ["dầu khí", "petrovietnam", "pvn", "scic", "nhà nước", "state", "evn", "vnpt", "mobifone", "vinacomin"]
            foreign_kw = ["fund", "dragon", "ftse", "veil", "kim ", "kitmc", "vietnam growth", "ngoại"]
            for sh in shareholders:
                nl = sh["name"].lower()
                if any(k in nl for k in state_kw):
                    ownership["state_pct"] = round((ownership["state_pct"] or 0) + sh["pct"], 2)
                if any(k in nl for k in foreign_kw):
                    ownership["foreign_pct"] = round((ownership["foreign_pct"] or 0) + sh["pct"], 2)
    except Exception as e:
        ownership["_error"] = str(e)

    return ownership, shareholders[:10]


def fetch_events(ticker: str) -> list:
    events = []
    try:
        from vnstock import Company
        comp = Company(symbol=ticker, source="VCI")
        df = comp.events()
        if df is not None and not df.empty:
            cutoff = (datetime.now() - timedelta(days=730)).strftime("%Y-%m-%d")
            risk_keywords = [
                "phát hành", "esop", "chuyển đổi", "trái phiếu", "niêm yết bổ sung",
                "tăng vốn", "ngoại trừ", "going concern", "từ chối", "vi phạm",
                "cảnh báo", "điều tra", "thay kiểm toán", "thay ban lãnh đạo",
                "tạm dừng", "hủy niêm yết", "margin call", "cầm cố cổ phiếu",
                "additional listing", "share issue", "bond",
            ]
            for _, row in df.iterrows():
                ev_date = str(row.get("display_date1") or row.get("public_date") or "")[:10]
                if ev_date and ev_date < cutoff:
                    continue
                ev_type = str(row.get("event_name_en") or row.get("event_name_vi") or "").strip()
                ev_detail = str(row.get("event_title_en") or row.get("event_title_vi") or "").strip()
                is_risky = any(k in (ev_type + ev_detail).lower() for k in risk_keywords)
                events.append({"date": ev_date, "type": ev_type, "detail": ev_detail[:200], "is_risky": is_risky})
            events.sort(key=lambda x: x.get("date", ""), reverse=True)
    except Exception as e:
        events.append({"_error": str(e)})
    return events[:20]


def fetch_shares_trend(ticker: str) -> dict:
    result = {"current_m": None, "1y_ago_m": None, "dilution_pct": None}
    try:
        from vnstock import Company
        comp = Company(symbol=ticker, source="VCI")
        ov = comp.overview()
        if ov is not None and not ov.empty:
            issue = safe_float(ov.iloc[0].get("issue_share"))
            if issue:
                result["current_m"] = round(issue / 1e6, 2)
        # Check capital_history for dilution
        try:
            hist = comp.capital_history()
            if hist is not None and not hist.empty and len(hist) >= 2:
                hist_sorted = hist.sort_values(by=hist.columns[0], ascending=False) if not hist.empty else hist
                latest = safe_float(hist_sorted.iloc[0].get("issue_share") or hist_sorted.iloc[0].get("shares"))
                prev = safe_float(hist_sorted.iloc[-1].get("issue_share") or hist_sorted.iloc[-1].get("shares"))
                if latest and prev and prev > 0:
                    result["dilution_pct"] = round((latest - prev) / prev * 100, 2)
        except Exception:
            pass
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
        from vnstock import Finance
        fin = Finance(symbol=ticker, period="quarter", source="VCI")

        bs = fin.balance_sheet(lang="en")
        if bs is not None and not bs.empty:
            qtrs = _quarter_cols(bs, 1)
            if qtrs:
                q = qtrs[0]
                short_debt = _get_item(bs, "bsa56", q) or 0  # Short-term borrowings
                long_debt  = _get_item(bs, "bsa71", q) or 0  # Long-term borrowings
                equity     = _get_item(bs, "bsa78", q)        # Owner's Equity
                cash       = _get_item(bs, "bsa2",  q)        # Cash and cash equivalents

                total_debt = short_debt + long_debt
                scale = 1e9  # VCI Finance returns values in VND raw → divide by 1e9 for billions
                total_debt_b = round(total_debt / scale, 1) if total_debt else None
                equity_b     = round(equity / scale, 1) if equity else None
                cash_b       = round(cash / scale, 1) if cash else None

                result["total_debt_b"] = total_debt_b
                result["equity_b"] = equity_b
                if total_debt_b and equity_b and equity_b > 0:
                    result["de_ratio"] = round(total_debt_b / equity_b, 2)
                if total_debt_b is not None and cash_b is not None:
                    result["net_debt_b"] = round(total_debt_b - cash_b, 1)

        is_df = fin.income_statement(lang="en")
        if is_df is not None and not is_df.empty:
            qtrs4 = _quarter_cols(is_df, 4)
            interest_ttm = 0
            ebit_ttm = 0
            for q in qtrs4:
                ie = _get_item(is_df, "isa8", q)   # Interest expenses (negative)
                op = _get_item(is_df, "isa11", q)  # Operating profit/EBIT
                if ie is not None:
                    interest_ttm += abs(ie)
                if op is not None:
                    ebit_ttm += op
            is_scale = 1e9
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
