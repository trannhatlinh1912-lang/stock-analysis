#!/usr/bin/env python3
"""Fetch deep financial data for stock analysis → data/financial_snapshot_{ticker}_{date}.json

Usage:
  python fetch_financials.py --ticker HPG
"""

import argparse
import json
import os
import sys
from datetime import date
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
    "DPM": "FERTILIZER", "DCM": "FERTILIZER", "BFC": "FERTILIZER",
    "CTD": "CONSTRUCTION", "HBC": "CONSTRUCTION", "VCG": "CONSTRUCTION",
}

INDUSTRY_NAMES = {
    "STEEL": "Thép", "BANK": "Ngân hàng", "REALESTATE": "Bất động sản",
    "SECURITIES": "Chứng khoán", "RETAIL": "Bán lẻ",
    "ENERGY": "Năng lượng / Dầu khí", "PHARMA": "Dược phẩm",
    "TECHNOLOGY": "Công nghệ", "FERTILIZER": "Phân bón",
    "CONSTRUCTION": "Xây dựng",
}

_SOURCE = "VCI"
_VALUE_SCALE = {"VCI": 1e9, "KBS": 1e6}

_INCOME_IDS = {
    "VCI": {
        "revenue":          "isa3",
        "gross_profit":     "isa5",
        "net_income":       "isa20",
        "ebit":             ["isa8", "operating_income", "ebit"],
        "interest_expense": ["isa14", "finance_expense", "interest_expense"],
    },
    "KBS": {
        "revenue":          "n_3.net_revenue",
        "gross_profit":     "n_5.gross_profit",
        "net_income":       "n_18.net_profit_after_tax",
        "ebit":             ["operating_income", "ebit"],
        "interest_expense": ["interest_expense", "finance_expense"],
    },
}

_BALANCE_IDS = {
    "VCI": {
        "equity":              ["bsa84", "total_equity", "equity"],
        "total_debt":          ["bsa47", "total_debt", "long_term_liabilities"],
        "total_assets":        ["bsa67", "total_assets", "total_asset"],
        "cash":                ["bsa1", "cash_and_equivalents", "cash"],
        "accounts_receivable": ["bsa4", "short_term_receivables", "accounts_receivable"],
        "inventory":           ["bsa8", "inventories", "inventory"],
        "current_assets":      ["bsa23", "total_current_assets", "current_assets"],
        "current_liabilities": ["bsa43", "total_current_liabilities", "current_liabilities"],
    },
    "KBS": {
        "equity":              ["d.owners_equity"],
        "total_debt":          ["n_11.short_term_borrowings_and_financial_leases"],
        "total_assets":        ["total_assets"],
        "cash":                ["cash_and_equivalents"],
        "accounts_receivable": ["accounts_receivable"],
        "inventory":           ["inventories"],
        "current_assets":      ["current_assets"],
        "current_liabilities": ["current_liabilities"],
    },
}

_CF_IDS = {
    "VCI": {
        "operating": ["cfa3", "net_cash_operating", "operating_cash_flow"],
        "capex":     ["cfa10", "purchase_fixed_assets", "capital_expenditure"],
    },
    "KBS": {
        "operating": ["net_cash_flows_from_operating_activities"],
        "capex":     ["n_1.payment_for_fixed_assets_constructions_and_other_long_term_assets"],
    },
}

_RATIO_IDS_KBS = {"roe": "roe_trailling", "roa": "roa_trailling", "pe": "p_e", "pb": "p_b"}


def detect_industry(ticker: str) -> tuple:
    code = TICKER_INDUSTRY_MAP.get(ticker.upper())
    if code:
        return code, INDUSTRY_NAMES.get(code, code)
    return "UNKNOWN", "Không xác định"


def _get_item(df, item_id, col: str):
    if item_id is None:
        return None
    mask = df["item_id"] == item_id
    if not mask.any() or col not in df.columns:
        return None
    val = df.loc[mask, col].values[0]
    return float(val) if val is not None and str(val) not in ("nan", "None") else None


def _safe_float(val):
    try:
        f = float(val)
        return None if f != f else f
    except (TypeError, ValueError):
        return None


def _find_id(item_ids: list, candidates) -> str | None:
    if isinstance(candidates, str):
        return candidates if candidates in item_ids else None
    for c in candidates:
        if c in item_ids:
            return c
    for c in candidates:
        match = next((i for i in item_ids if c.lower() in str(i).lower()), None)
        if match:
            return match
    return None


def _dedup_quarters(q_cols: list, n: int) -> list:
    seen, unique = set(), []
    for q in q_cols:
        base = q.split("_")[0]
        if base not in seen:
            seen.add(base)
            unique.append(q)
    return unique[:n]


# ---------------------------------------------------------------------------
# Income statement — revenue, margins, EBIT, interest expense
# ---------------------------------------------------------------------------

def fetch_income_detailed(ticker: str, n_quarters: int = 8) -> dict:
    try:
        from vnstock.api.financial import Finance
        df = Finance(source=_SOURCE, symbol=ticker, show_log=False).income_statement(
            period="quarter", lang="en"
        )
        if df is None or df.empty:
            return {}

        q_cols = _dedup_quarters([c for c in df.columns if "-Q" in str(c)], n_quarters)
        if not q_cols:
            return {}

        quarters = [q.split("_")[0] for q in q_cols]
        item_ids = df["item_id"].tolist() if "item_id" in df.columns else []
        scale = _VALUE_SCALE.get(_SOURCE, 1e9)
        ids = _INCOME_IDS.get(_SOURCE, _INCOME_IDS["VCI"])

        rev_id    = ids["revenue"] if isinstance(ids["revenue"], str) else _find_id(item_ids, ids["revenue"])
        gp_id     = ids["gross_profit"] if isinstance(ids["gross_profit"], str) else _find_id(item_ids, ids["gross_profit"])
        ni_id     = ids["net_income"] if isinstance(ids["net_income"], str) else _find_id(item_ids, ids["net_income"])
        ebit_id   = _find_id(item_ids, ids["ebit"])
        intexp_id = _find_id(item_ids, ids["interest_expense"])

        revenue_b, gross_profit_b, net_income_b, ebit_b, interest_b = [], [], [], [], []
        gross_margin_pct, net_margin_pct = [], []

        for q in q_cols:
            rev  = _get_item(df, rev_id, q)
            gp   = _get_item(df, gp_id, q)
            ni   = _get_item(df, ni_id, q)
            eb   = _get_item(df, ebit_id, q)
            ie   = _get_item(df, intexp_id, q)

            rev_b_val = round(rev / scale, 1) if rev else None
            gm = round(gp / rev * 100, 1) if gp and rev else None
            nm = round(ni / rev * 100, 1) if ni and rev else None

            revenue_b.append(rev_b_val)
            gross_profit_b.append(round(gp / scale, 1) if gp else None)
            net_income_b.append(round(ni / scale, 1) if ni else None)
            ebit_b.append(round(eb / scale, 1) if eb else None)
            interest_b.append(round(abs(ie) / scale, 1) if ie else None)
            gross_margin_pct.append(gm)
            net_margin_pct.append(nm)

        rev_vals = [v for v in revenue_b if v is not None]
        rev_cagr = None
        if len(rev_vals) >= 8 and rev_vals[7] and rev_vals[7] > 0:
            rev_cagr = round(((rev_vals[0] / rev_vals[7]) ** 0.5 - 1) * 100, 1)

        rev_yoy = None
        if len(revenue_b) >= 5 and revenue_b[0] and revenue_b[4] and revenue_b[4] > 0:
            rev_yoy = round((revenue_b[0] / revenue_b[4] - 1) * 100, 1)

        gm_vals = [v for v in gross_margin_pct if v is not None]
        gm_trend = "unknown"
        if len(gm_vals) >= 6:
            recent = sum(gm_vals[:3]) / 3
            older  = sum(gm_vals[3:6]) / 3
            gm_trend = "improving" if recent > older + 1 else ("declining" if recent < older - 1 else "stable")

        return {
            "quarters":           quarters,
            "revenue_b":          revenue_b,
            "gross_profit_b":     gross_profit_b,
            "net_income_b":       net_income_b,
            "ebit_b":             ebit_b,
            "interest_expense_b": interest_b,
            "gross_margin_pct":   gross_margin_pct,
            "net_margin_pct":     net_margin_pct,
            "revenue_cagr_2y":    rev_cagr,
            "revenue_yoy_latest": rev_yoy,
            "gross_margin_trend": gm_trend,
            "gross_margin_latest": gross_margin_pct[0] if gross_margin_pct else None,
            "net_margin_latest":   net_margin_pct[0] if net_margin_pct else None,
        }
    except Exception as e:
        print(f"[WARN] Income detailed error for {ticker}: {e}", file=sys.stderr)
        return {}


# ---------------------------------------------------------------------------
# Balance sheet — multi-quarter with current ratio, AR, inventory
# ---------------------------------------------------------------------------

def fetch_balance_detailed(ticker: str, n_quarters: int = 8) -> dict:
    try:
        from vnstock.api.financial import Finance
        df = Finance(source=_SOURCE, symbol=ticker, show_log=False).balance_sheet(
            period="quarter", lang="en"
        )
        if df is None or df.empty:
            return {}

        q_cols = _dedup_quarters([c for c in df.columns if "-Q" in str(c)], n_quarters)
        if not q_cols:
            return {}

        item_ids = df["item_id"].tolist() if "item_id" in df.columns else []
        scale = _VALUE_SCALE.get(_SOURCE, 1e9)
        id_map = _BALANCE_IDS.get(_SOURCE, _BALANCE_IDS["VCI"])

        equity_id  = _find_id(item_ids, id_map["equity"])
        debt_id    = _find_id(item_ids, id_map["total_debt"])
        assets_id  = _find_id(item_ids, id_map["total_assets"])
        cash_id    = _find_id(item_ids, id_map["cash"])
        ar_id      = _find_id(item_ids, id_map["accounts_receivable"])
        inv_id     = _find_id(item_ids, id_map["inventory"])
        ca_id      = _find_id(item_ids, id_map["current_assets"])
        cl_id      = _find_id(item_ids, id_map["current_liabilities"])

        equity_b, debt_b, assets_b = [], [], []
        cash_b, ar_b, inv_b, ca_b, cl_b = [], [], [], [], []

        for q in q_cols:
            def _v(fid):
                v = _get_item(df, fid, q) if fid else None
                return round(v / scale, 1) if v else None

            equity_b.append(_v(equity_id))
            debt_b.append(_v(debt_id))
            assets_b.append(_v(assets_id))
            cash_b.append(_v(cash_id))
            ar_b.append(_v(ar_id))
            inv_b.append(_v(inv_id))
            ca_b.append(_v(ca_id))
            cl_b.append(_v(cl_id))

        eq_lat  = equity_b[0] if equity_b else None
        de_lat  = debt_b[0] if debt_b else None
        ca_lat  = cash_b[0] if cash_b else None
        cur_a   = ca_b[0] if ca_b else None
        cur_l   = cl_b[0] if cl_b else None

        de_ratio = round(de_lat / eq_lat, 2) if de_lat and eq_lat and eq_lat > 0 else None
        net_debt = round(de_lat - ca_lat, 1) if de_lat is not None and ca_lat is not None else None
        current_ratio = round(cur_a / cur_l, 2) if cur_a and cur_l and cur_l > 0 else None
        inv_lat = inv_b[0] if inv_b else None
        quick_ratio = round((cur_a - (inv_lat or 0)) / cur_l, 2) if cur_a and cur_l and cur_l > 0 else None

        equity_growth = None
        if len(equity_b) >= 5 and equity_b[0] and equity_b[4] and equity_b[4] > 0:
            equity_growth = round((equity_b[0] / equity_b[4] - 1) * 100, 1)

        de_trend = "unknown"
        de_series = []
        for i in range(min(5, len(equity_b), len(debt_b))):
            d, e = debt_b[i], equity_b[i]
            if d and e and e > 0:
                de_series.append(d / e)
        if len(de_series) >= 4:
            if de_series[0] > de_series[-1] * 1.3:
                de_trend = "increasing"
            elif de_series[0] < de_series[-1] * 0.7:
                de_trend = "decreasing"
            else:
                de_trend = "stable"

        return {
            "equity_b":          equity_b,
            "debt_b":            debt_b,
            "assets_b":          assets_b,
            "cash_b":            cash_b,
            "ar_b":              ar_b,
            "inventory_b":       inv_b,
            "current_assets_b":  ca_b,
            "current_liabilities_b": cl_b,
            "de_ratio":          de_ratio,
            "net_debt_b":        net_debt,
            "current_ratio":     current_ratio,
            "quick_ratio":       quick_ratio,
            "equity_growth_yoy": equity_growth,
            "de_trend":          de_trend,
            "negative_equity":   bool(eq_lat is not None and eq_lat < 0),
        }
    except Exception as e:
        print(f"[WARN] Balance sheet detailed error for {ticker}: {e}", file=sys.stderr)
        return {}


# ---------------------------------------------------------------------------
# Cash flow — per quarter OCF and capex
# ---------------------------------------------------------------------------

def fetch_cashflow_detailed(ticker: str, n_quarters: int = 8) -> dict:
    try:
        from vnstock.api.financial import Finance
        df = Finance(source=_SOURCE, symbol=ticker, show_log=False).cash_flow(
            period="quarter", lang="en"
        )
        if df is None or df.empty:
            return {}

        q_cols = _dedup_quarters([c for c in df.columns if "-Q" in str(c)], n_quarters)
        if not q_cols:
            return {}

        item_ids = df["item_id"].tolist() if "item_id" in df.columns else []
        scale = _VALUE_SCALE.get(_SOURCE, 1e9)
        cf_map = _CF_IDS.get(_SOURCE, _CF_IDS["VCI"])

        ocf_id   = _find_id(item_ids, cf_map["operating"])
        capex_id = _find_id(item_ids, cf_map["capex"])

        ocf_b, capex_b, fcf_b = [], [], []

        for q in q_cols:
            ocf  = _get_item(df, ocf_id, q) if ocf_id else None
            capex = _get_item(df, capex_id, q) if capex_id else None
            ocf_v  = round(ocf / scale, 1) if ocf is not None else None
            cap_v  = round(capex / scale, 1) if capex is not None else None
            if ocf_v is not None and cap_v is not None:
                fcf_v = round(ocf_v - abs(cap_v), 1)
            else:
                fcf_v = ocf_v
            ocf_b.append(ocf_v)
            capex_b.append(cap_v)
            fcf_b.append(fcf_v)

        ocf_4q  = round(sum(v for v in ocf_b[:4] if v is not None), 1)
        fcf_4q  = round(sum(v for v in fcf_b[:4] if v is not None), 1)
        capex_4q = round(sum(abs(v) for v in capex_b[:4] if v is not None), 1)

        return {
            "ocf_b":           ocf_b,
            "capex_b":         capex_b,
            "fcf_b":           fcf_b,
            "ocf_4q_sum_b":    ocf_4q,
            "fcf_4q_sum_b":    fcf_4q,
            "capex_4q_sum_b":  capex_4q,
            "fcf_positive":    fcf_4q > 0,
            "ocf_positive":    ocf_4q > 0,
        }
    except Exception as e:
        print(f"[WARN] Cash flow detailed error for {ticker}: {e}", file=sys.stderr)
        return {}


# ---------------------------------------------------------------------------
# Ratios — ROE, ROA, PE, PB
# ---------------------------------------------------------------------------

def fetch_ratios_basic(ticker: str, n_quarters: int = 4) -> dict:
    try:
        from vnstock.api.financial import Finance
        df = Finance(source=_SOURCE, symbol=ticker, show_log=False).ratio(
            period="quarter", lang="en"
        )
        if df is None or df.empty:
            return {}

        item_ids = df["item_id"].tolist() if "item_id" in df.columns else []
        q_cols = _dedup_quarters([c for c in df.columns if "-Q" in str(c)], n_quarters)
        if not q_cols:
            return {}

        if _SOURCE == "KBS":
            ids = _RATIO_IDS_KBS
            q = q_cols[0]
            roe_t = _get_item(df, ids["roe"], q)
            roa_t = _get_item(df, ids["roa"], q)
            pe_v  = _get_item(df, ids["pe"],  q)
            pb_v  = _get_item(df, ids["pb"],  q)
            return {
                "roe_avg_4q": round(roe_t, 1) if roe_t else None,
                "roa_latest": round(roa_t, 2) if roa_t else None,
                "pe_latest":  round(pe_v, 1) if pe_v else None,
                "pb_latest":  round(pb_v, 2) if pb_v else None,
            }

        roe_id = next((i for i in item_ids if "roe" in str(i).lower()), None)
        roa_id = next((i for i in item_ids if "roa" in str(i).lower()), None)
        pe_id  = next((i for i in item_ids if str(i).lower() in ("pe", "p_e", "price_earnings")), None)
        pb_id  = next((i for i in item_ids if str(i).lower() in ("pb", "p_b", "price_book")), None)

        roe_vals = []
        for q in q_cols:
            v = _get_item(df, roe_id, q) if roe_id else None
            if v and abs(v) > 100:
                v = round(v / 100, 2)
            roe_vals.append(round(v, 2) if v is not None else None)

        valid_roe = [v for v in roe_vals if v is not None]
        roe_avg = round(sum(valid_roe) / len(valid_roe), 1) if valid_roe else None

        roa = _get_item(df, roa_id, q_cols[0]) if roa_id else None
        if roa and abs(roa) > 100:
            roa = round(roa / 100, 2)
        pe = _get_item(df, pe_id, q_cols[0]) if pe_id else None
        pb = _get_item(df, pb_id, q_cols[0]) if pb_id else None

        return {
            "roe_avg_4q": roe_avg,
            "roa_latest": round(roa, 2) if roa else None,
            "pe_latest":  round(pe, 1) if pe else None,
            "pb_latest":  round(pb, 2) if pb else None,
        }
    except Exception as e:
        print(f"[WARN] Ratios fetch error for {ticker}: {e}", file=sys.stderr)
        return {}


# ---------------------------------------------------------------------------
# Derived metrics
# ---------------------------------------------------------------------------

def compute_derived_metrics(income: dict, balance: dict, cashflow: dict) -> dict:
    result = {}

    ebit_list = income.get("ebit_b", [])
    ebit_4q   = sum(v for v in ebit_list[:4] if v is not None)

    eq_lat   = (balance.get("equity_b") or [None])[0]
    net_debt = balance.get("net_debt_b")

    if ebit_4q and eq_lat and net_debt is not None:
        ic = eq_lat + net_debt
        if ic and ic > 0:
            result["roic"] = round(ebit_4q * 0.8 / ic * 100, 1)

    ocf_4q = cashflow.get("ocf_4q_sum_b")
    ni_list = income.get("net_income_b", [])
    ni_4q   = sum(v for v in ni_list[:4] if v is not None)

    if ocf_4q is not None and ni_4q and ni_4q > 0:
        result["ocf_to_ni"] = round(ocf_4q / ni_4q, 2)

    fcf_4q = cashflow.get("fcf_4q_sum_b")
    if fcf_4q is not None and ni_4q and ni_4q > 0:
        result["fcf_to_ni"] = round(fcf_4q / ni_4q, 2)

    intexp_list = income.get("interest_expense_b", [])
    intexp_4q   = sum(v for v in intexp_list[:4] if v is not None)
    result["interest_expense_4q_b"] = round(intexp_4q, 1) if intexp_4q else None
    if ebit_4q and intexp_4q and intexp_4q > 0:
        result["interest_coverage"] = round(ebit_4q / intexp_4q, 1)

    capex_4q = cashflow.get("capex_4q_sum_b")
    rev_list = income.get("revenue_b", [])
    rev_4q   = sum(v for v in rev_list[:4] if v is not None)
    if capex_4q and rev_4q and rev_4q > 0:
        result["capex_to_revenue_pct"] = round(capex_4q / rev_4q * 100, 1)

    ar_latest  = (balance.get("ar_b") or [None])[0]
    rev_latest = rev_list[0] if rev_list else None
    if ar_latest and rev_latest and rev_latest > 0:
        result["ar_days"] = round(ar_latest / rev_latest * 90)

    inv_latest = (balance.get("inventory_b") or [None])[0]
    gp_latest  = (income.get("gross_profit_b") or [None])[0]
    if rev_latest and gp_latest is not None:
        cogs = rev_latest - gp_latest
        if inv_latest and cogs and cogs > 0:
            result["inventory_days"] = round(inv_latest / cogs * 90)

    ar_list = balance.get("ar_b", [])
    if len(ar_list) >= 4 and len(rev_list) >= 4:
        ar_ratios = []
        for i in range(4):
            a = ar_list[i] if i < len(ar_list) else None
            r = rev_list[i] if i < len(rev_list) else None
            if a and r and r > 0:
                ar_ratios.append(a / r)
        if len(ar_ratios) >= 3:
            result["ar_days_trend"] = ("rising" if ar_ratios[0] > ar_ratios[-1] * 1.15
                                       else "falling" if ar_ratios[0] < ar_ratios[-1] * 0.85
                                       else "stable")

    inv_list = balance.get("inventory_b", [])
    if len(inv_list) >= 4 and len(rev_list) >= 4:
        inv_ratios = []
        for i in range(4):
            iv = inv_list[i] if i < len(inv_list) else None
            r  = rev_list[i] if i < len(rev_list) else None
            if iv and r and r > 0:
                inv_ratios.append(iv / r)
        if len(inv_ratios) >= 3:
            result["inventory_days_trend"] = ("rising" if inv_ratios[0] > inv_ratios[-1] * 1.2
                                               else "falling" if inv_ratios[0] < inv_ratios[-1] * 0.8
                                               else "stable")

    if net_debt is not None and ebit_4q and ebit_4q > 0:
        result["net_debt_to_ebit"] = round(net_debt / ebit_4q, 1)

    return result


# ---------------------------------------------------------------------------
# Red flags
# ---------------------------------------------------------------------------

def detect_red_flags(income: dict, balance: dict, cashflow: dict,
                     derived: dict, industry_code: str) -> list:
    flags = []

    # 1. Earnings quality: NI growing but OCF declining
    ni_list  = income.get("net_income_b", [])
    ocf_list = cashflow.get("ocf_b", [])
    if len(ni_list) >= 5 and len(ocf_list) >= 5:
        ni_r  = sum(v for v in ni_list[:4] if v is not None)
        ni_o  = sum(v for v in ni_list[1:5] if v is not None)
        ocf_r = sum(v for v in ocf_list[:4] if v is not None)
        ocf_o = sum(v for v in ocf_list[1:5] if v is not None)
        if ni_o and ni_o > 0 and ni_r / ni_o >= 1.10 and ocf_o and ocf_o > 0 and ocf_r / ocf_o <= 0.95:
            flags.append({
                "flag": "earnings_quality",
                "severity": "high",
                "detail": f"NI +{round((ni_r/ni_o-1)*100,1)}% nhưng OCF {round((ocf_r/ocf_o-1)*100,1)}% — lợi nhuận tăng không có tiền thực",
            })

    # 2. AR rising
    if derived.get("ar_days_trend") == "rising":
        flags.append({
            "flag": "ar_rising",
            "severity": "medium",
            "detail": "Khoản phải thu/Doanh thu tăng — có thể chính sách bán chịu nới lỏng hoặc khó thu hồi",
        })

    # 3. Inventory rising but revenue falling
    inv_list = balance.get("inventory_b", [])
    rev_list = income.get("revenue_b", [])
    if len(inv_list) >= 4 and len(rev_list) >= 4:
        i0, i3 = inv_list[0], inv_list[3]
        r0, r3 = rev_list[0], rev_list[3]
        if i0 and i3 and r0 and r3 and i0 > i3 * 1.15 and r0 < r3 * 0.95:
            flags.append({
                "flag": "inventory_rising",
                "severity": "medium",
                "detail": f"Tồn kho +{round((i0/i3-1)*100,1)}% trong khi DT {round((r0/r3-1)*100,1)}%",
            })

    # 4. Interest coverage low
    ic = derived.get("interest_coverage")
    if ic is not None and derived.get("interest_expense_4q_b"):
        if ic < 1.5:
            flags.append({"flag": "interest_coverage_low", "severity": "high",
                          "detail": f"Interest coverage {ic}× — EBIT không đủ trả lãi vay (ngưỡng an toàn ≥3×)"})
        elif ic < 3.0:
            flags.append({"flag": "interest_coverage_low", "severity": "medium",
                          "detail": f"Interest coverage {ic}× — biên an toàn thấp (ngưỡng tốt ≥5×)"})

    # 5. D/E accelerating
    if balance.get("de_trend") == "increasing":
        flags.append({
            "flag": "debt_acceleration",
            "severity": "medium",
            "detail": f"D/E tăng nhanh trong 4Q gần nhất (hiện tại {balance.get('de_ratio')}×) — leverage mở rộng",
        })

    # 6. Gross margin compression
    if income.get("gross_margin_trend") == "declining":
        gm = income.get("gross_margin_pct", [])
        if len(gm) >= 4 and gm[0] and gm[3]:
            flags.append({
                "flag": "margin_compression",
                "severity": "medium",
                "detail": f"Gross margin {gm[3]}% → {gm[0]}% xu hướng suy giảm liên tiếp",
            })

    # 7. FCF negative 3+/4Q (not REALESTATE)
    if industry_code not in ("REALESTATE",):
        fcf_list = cashflow.get("fcf_b", [])
        neg = sum(1 for v in fcf_list[:4] if v is not None and v < 0)
        if neg >= 3:
            flags.append({"flag": "fcf_negative_persistent", "severity": "high",
                          "detail": f"FCF âm {neg}/4 quarters — không tạo ra tiền mặt tự do"})

    # 8. Negative equity
    if balance.get("negative_equity"):
        flags.append({"flag": "negative_equity", "severity": "high",
                      "detail": "Vốn chủ sở hữu âm — công ty đã mất vốn"})

    return flags


# ---------------------------------------------------------------------------
# Financial score (10 pts)
# ---------------------------------------------------------------------------

def compute_financial_score(income: dict, balance: dict, cashflow: dict,
                             derived: dict, ratios: dict, industry_code: str) -> dict:
    score = 0.0
    breakdown = {}
    score_warnings = []
    is_bank = industry_code == "BANK"
    is_realestate = industry_code == "REALESTATE"
    is_energy = industry_code == "ENERGY"

    # 1. Revenue CAGR 2Y (1.5 pts)
    cagr = income.get("revenue_cagr_2y")
    if cagr is not None:
        pts = 1.5 if cagr >= 15 else (1.0 if cagr >= 5 else (0.5 if cagr >= 0 else 0))
    else:
        pts = 0
        score_warnings.append("revenue_cagr: missing → 0 pts")
    score += pts
    breakdown["revenue_cagr"] = pts

    # 2. Net margin (1.5 pts)
    nm = income.get("net_margin_latest")
    if nm is not None:
        pts = 1.5 if nm >= 15 else (1.0 if nm >= 8 else (0.5 if nm >= 3 else 0))
    else:
        pts = 0
        score_warnings.append("net_margin: missing → 0 pts")
    score += pts
    breakdown["net_margin"] = pts

    # 3. ROIC / ROE (1.5 pts)
    roic = derived.get("roic")
    roe  = ratios.get("roe_avg_4q")
    if roic is not None:
        pts = 1.5 if roic >= 15 else (1.0 if roic >= 10 else (0.5 if roic >= 5 else 0))
    elif roe is not None:
        pts = 1.5 if roe >= 20 else (1.0 if roe >= 15 else (0.5 if roe >= 10 else 0))
        score_warnings.append("roic: using ROE as proxy")
    else:
        pts = 0
        score_warnings.append("roic: missing → 0 pts")
    score += pts
    breakdown["roic"] = pts

    # 4. OCF/NI earnings quality (1.5 pts)
    ocf_ni = derived.get("ocf_to_ni")
    if ocf_ni is not None:
        pts = 1.5 if ocf_ni >= 0.9 else (1.0 if ocf_ni >= 0.7 else (0.5 if ocf_ni >= 0.5 else 0))
    else:
        pts = 0
        score_warnings.append("ocf_to_ni: missing → 0 pts")
    score += pts
    breakdown["earnings_quality"] = pts

    # 5. FCF (1.0 pt)
    fcf_pos = cashflow.get("fcf_positive")
    ocf_pos = cashflow.get("ocf_positive")
    if fcf_pos is None:
        pts = 0
        score_warnings.append("fcf: missing → 0 pts")
    elif fcf_pos:
        pts = 1.0
    elif ocf_pos and is_realestate:
        pts = 0.5
    else:
        pts = 0
    score += pts
    breakdown["fcf"] = pts

    # 6. Interest coverage (1.5 pts) — N/A for banks
    if is_bank:
        pts = 0
        score_warnings.append("interest_coverage: N/A for banks → 0 pts")
    else:
        ic = derived.get("interest_coverage")
        intexp = derived.get("interest_expense_4q_b")
        if ic is None and not intexp:
            pts = 1.5
            score_warnings.append("interest_coverage: no interest expense → 1.5 pts assumed")
        elif ic is not None:
            pts = 1.5 if ic >= 5 else (1.0 if ic >= 3 else (0.5 if ic >= 1.5 else 0))
        else:
            pts = 0
            score_warnings.append("interest_coverage: missing → 0 pts")
    score += pts
    breakdown["interest_coverage"] = pts

    # 7. D/E (1.0 pt) — replaced by ROA for banks
    if is_bank:
        roa = ratios.get("roa_latest")
        if roa is not None:
            pts = 1.0 if roa >= 1.0 else (0.75 if roa >= 0.7 else (0.5 if roa >= 0.5 else 0))
        else:
            pts = 0
            score_warnings.append("roa_bank: missing → 0 pts")
    else:
        de = balance.get("de_ratio")
        if de is not None:
            if is_energy:
                pts = 1.0 if de <= 2.0 else (0.75 if de <= 3.0 else (0.5 if de <= 4.0 else 0))
            else:
                pts = 1.0 if de <= 0.5 else (0.75 if de <= 1.0 else (0.5 if de <= 2.0 else 0))
        else:
            pts = 0
            score_warnings.append("de_ratio: missing → 0 pts")
    score += pts
    breakdown["de_or_roa"] = pts

    # 8. Current ratio (1.0 pt) — N/A for banks
    if is_bank:
        pts = 0
        score_warnings.append("current_ratio: N/A for banks → 0 pts")
    else:
        cr = balance.get("current_ratio")
        if cr is not None:
            pts = 1.0 if cr >= 2.0 else (0.75 if cr >= 1.5 else (0.5 if cr >= 1.0 else 0))
        else:
            pts = 0
            score_warnings.append("current_ratio: missing → 0 pts")
    score += pts
    breakdown["current_ratio"] = pts

    return {
        "total": round(min(score, 10.0), 1),
        "max": 10,
        "breakdown": breakdown,
        "score_warnings": score_warnings,
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    global _SOURCE
    parser = argparse.ArgumentParser()
    parser.add_argument("--ticker", required=True)
    parser.add_argument("--source", default="VCI")
    args = parser.parse_args()

    ticker = args.ticker.upper().strip()
    _SOURCE = args.source.upper()
    source_suffix = f"_{_SOURCE}" if _SOURCE != "VCI" else ""
    output_file = DATA_DIR / f"financial_snapshot_{ticker}{source_suffix}_{TODAY}.json"

    if output_file.exists():
        print(f"[stock-financials] Cache hit: {output_file.name}")
        return

    print(f"[stock-financials] Fetching for {ticker} (source={_SOURCE})...")
    industry_code, industry_name = detect_industry(ticker)
    print(f"[stock-financials] Industry: {industry_name} ({industry_code})")

    data_warnings = []

    print("[stock-financials] Fetching income statement (8Q)...")
    income = fetch_income_detailed(ticker, 8)
    if not income:
        data_warnings.append("income_statement: no data returned")

    print("[stock-financials] Fetching balance sheet (8Q)...")
    balance = fetch_balance_detailed(ticker, 8)
    if not balance:
        data_warnings.append("balance_sheet: no data returned")

    print("[stock-financials] Fetching cash flow (8Q)...")
    cashflow = fetch_cashflow_detailed(ticker, 8)
    if not cashflow:
        data_warnings.append("cash_flow: no data returned")

    print("[stock-financials] Fetching ratios (4Q)...")
    ratios = fetch_ratios_basic(ticker, 4)
    if not ratios:
        data_warnings.append("ratios: no data returned")

    print("[stock-financials] Computing derived metrics...")
    derived = compute_derived_metrics(income, balance, cashflow)

    print("[stock-financials] Detecting red flags...")
    red_flags = detect_red_flags(income, balance, cashflow, derived, industry_code)

    print("[stock-financials] Computing financial score...")
    financial_score = compute_financial_score(income, balance, cashflow, derived, ratios, industry_code)
    data_warnings.extend(financial_score.pop("score_warnings", []))

    snapshot = {
        "date":            TODAY,
        "ticker":          ticker,
        "industry_code":   industry_code,
        "industry_name":   industry_name,
        "income":          income,
        "balance_sheet":   balance,
        "cashflow":        cashflow,
        "ratios":          ratios,
        "derived":         derived,
        "red_flags":       red_flags,
        "financial_score": financial_score,
        "data_warnings":   data_warnings,
    }

    output_file.write_text(json.dumps(snapshot, indent=2, ensure_ascii=False))
    print(f"[stock-financials] Snapshot saved → {output_file.name}")


if __name__ == "__main__":
    main()
