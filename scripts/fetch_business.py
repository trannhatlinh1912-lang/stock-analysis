#!/usr/bin/env python3
"""Fetch business quality data from vnstock → data/business_snapshot_{ticker}_{date}.json

Usage:
  python fetch_business.py --ticker HPG
"""

import argparse
import json
import os
import sys
import time
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

# ---------------------------------------------------------------------------
# Static reference data (reused from fetch_industry.py)
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

# Module-level source — overridden by --source CLI arg in main()
_SOURCE = "VCI"

# Item ID and unit mappings per source
_INCOME_IDS = {
    "VCI": {"revenue": "isa3", "gross_profit": "isa5", "net_income": "isa20"},
    "KBS": {"revenue": "n_3.net_revenue", "gross_profit": "n_5.gross_profit",
            "net_income": "n_18.net_profit_after_tax"},
}
# Raw values from each source are in different units:
#   VCI → VND (raw)          → divide by 1e9 to get B VND
#   KBS → thousand VND       → divide by 1e6 to get B VND
_VALUE_SCALE = {"VCI": 1e9, "KBS": 1e6}

_BALANCE_IDS = {
    "VCI": {"equity": ["bsa84", "total_equity", "equity"],
            "debt":   ["bsa47", "total_debt", "long_term_liabilities"],
            "assets": ["bsa67", "total_assets", "total_asset"]},
    "KBS": {"equity": ["d.owners_equity"],
            "debt":   ["n_11.short_term_borrowings_and_financial_leases"],
            "assets": ["total_assets"]},
}
_CF_IDS = {
    "VCI": {"operating": ["cfa3", "net_cash_operating", "operating_cash_flow"],
            "capex":     ["cfa10", "purchase_fixed_assets", "capital_expenditure"]},
    "KBS": {"operating": ["net_cash_flows_from_operating_activities"],
            "capex":     ["n_1.payment_for_fixed_assets_constructions_and_other_long_term_assets"]},
}
# KBS ratio API provides pre-computed trailing values (already %)
_RATIO_IDS_KBS = {"roe": "roe_trailling", "roa": "roa_trailling", "pe": "p_e", "pb": "p_b"}


def detect_industry(ticker: str) -> tuple:
    code = TICKER_INDUSTRY_MAP.get(ticker.upper())
    if code:
        return code, INDUSTRY_NAMES.get(code, code)
    return "UNKNOWN", "Không xác định"


def _get_item(df, item_id: str, col: str):
    """Extract a single cell from wide-format financial statement."""
    mask = df["item_id"] == item_id
    if not mask.any() or col not in df.columns:
        return None
    val = df.loc[mask, col].values[0]
    return float(val) if val is not None and str(val) not in ("nan", "None") else None


def _safe_float(val) -> float | None:
    try:
        f = float(val)
        return None if f != f else f  # NaN check
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# Company profile — vnstock Vnstock().stock().company
# ---------------------------------------------------------------------------

def fetch_company_profile(ticker: str) -> dict:
    result = {
        "short_name": ticker,
        "description": "",
        "description_available": False,
    }
    try:
        from vnstock import Vnstock
        stock = Vnstock().stock(symbol=ticker, source=_SOURCE)
        df = stock.company.profile()
        if df is not None and not df.empty:
            row = df.iloc[0] if hasattr(df, "iloc") else {}
            result["short_name"] = str(row.get("short_name", ticker) or ticker).strip() or ticker
            desc = str(row.get("company_profile", "") or "").strip()
            result["description"] = desc[:500] if desc else ""
            result["description_available"] = bool(desc)
    except Exception as e:
        print(f"[WARN] company.profile() error for {ticker}: {e}", file=sys.stderr)
    return result


def fetch_officers(ticker: str) -> list:
    try:
        from vnstock import Vnstock
        stock = Vnstock().stock(symbol=ticker, source=_SOURCE)
        df = stock.company.officers()
        if df is None or df.empty:
            return []
        officers = []
        for _, row in df.head(5).iterrows():
            name = str(row.get("officer_name", "") or "").strip()
            pos = str(row.get("officer_position", "") or "").strip()
            if name:
                officers.append({"name": name, "position": pos})
        return officers
    except Exception as e:
        print(f"[WARN] company.officers() error for {ticker}: {e}", file=sys.stderr)
        return []


def fetch_shareholders(ticker: str) -> list:
    try:
        from vnstock import Vnstock
        stock = Vnstock().stock(symbol=ticker, source=_SOURCE)
        df = stock.company.shareholders()
        if df is None or df.empty:
            return []
        holders = []
        for _, row in df.head(5).iterrows():
            name = str(row.get("share_holder", "") or "").strip()
            pct = _safe_float(row.get("share_own_percent"))
            if pct is not None:
                pct = round(pct * 100, 2) if pct < 1.5 else round(pct, 2)
            if name:
                holders.append({"name": name, "pct": pct})
        holders.sort(key=lambda x: x["pct"] or 0, reverse=True)
        return holders
    except Exception as e:
        print(f"[WARN] company.shareholders() error for {ticker}: {e}", file=sys.stderr)
        return []


# ---------------------------------------------------------------------------
# Financial data — vnstock.api.financial.Finance
# ---------------------------------------------------------------------------

def fetch_income_multi_quarter(ticker: str, n_quarters: int = 8) -> dict:
    """Fetch income statement for up to n_quarters, return per-quarter arrays."""
    try:
        from vnstock.api.financial import Finance
        df = Finance(source=_SOURCE, symbol=ticker, show_log=False).income_statement(
            period="quarter", lang="en"
        )
        if df is None or df.empty:
            return {}

        q_cols = [c for c in df.columns if "-Q" in str(c)]
        if not q_cols:
            return {}

        # Deduplicate quarters (KBS sometimes has duplicates like '2025-Q4_1')
        seen, unique_q = set(), []
        for q in q_cols:
            base = q.split("_")[0]  # strip _1 suffix
            if base not in seen:
                seen.add(base)
                unique_q.append(q)
        q_cols = unique_q[:n_quarters]
        quarters = [q.split("_")[0] for q in q_cols]  # normalize quarter labels

        ids = _INCOME_IDS.get(_SOURCE, _INCOME_IDS["VCI"])
        scale = _VALUE_SCALE.get(_SOURCE, 1e9)

        revenue_list, gm_list, nm_list = [], [], []

        for q in q_cols:
            rev = _get_item(df, ids["revenue"], q)
            gp  = _get_item(df, ids["gross_profit"], q)
            ni  = _get_item(df, ids["net_income"], q)

            rev_b = round(rev / scale, 1) if rev else None
            gm = round(gp / rev * 100, 1) if gp and rev else None
            nm = round(ni / rev * 100, 1) if ni and rev else None

            revenue_list.append(rev_b)
            gm_list.append(gm)
            nm_list.append(nm)

        # Derived metrics
        gm_vals = [v for v in gm_list if v is not None]
        nm_latest = nm_list[0] if nm_list else None
        gm_latest = gm_list[0] if gm_list else None
        gm_avg = round(sum(gm_vals) / len(gm_vals), 1) if gm_vals else None

        import statistics
        gm_std = round(statistics.stdev(gm_vals), 2) if len(gm_vals) >= 2 else None

        # Revenue CAGR 2Y: compare Q1 vs Q9 (if 8Q available, that's ~2 years of quarters)
        rev_cagr = None
        rev_vals = [v for v in revenue_list if v is not None]
        if len(rev_vals) >= 8 and rev_vals[7] and rev_vals[7] > 0:
            rev_cagr = round(((rev_vals[0] / rev_vals[7]) ** 0.5 - 1) * 100, 1)

        return {
            "quarters": quarters,
            "revenue_b_vnd": revenue_list,
            "gross_margin": gm_list,
            "net_margin": nm_list,
            "revenue_cagr_2y": rev_cagr,
            "gross_margin_std_8q": gm_std,
            "gross_margin_avg_8q": gm_avg,
            "gross_margin_latest": gm_latest,
            "net_margin_latest": nm_latest,
        }
    except Exception as e:
        print(f"[WARN] Income statement error for {ticker}: {e}", file=sys.stderr)
        return {}


def fetch_ratios(ticker: str, n_quarters: int = 8) -> dict:
    """Fetch ROE, ROA, P/E, P/B from ratio API."""
    try:
        from vnstock.api.financial import Finance
        df = Finance(source=_SOURCE, symbol=ticker, show_log=False).ratio(
            period="quarter", lang="en"
        )
        if df is None or df.empty:
            return {}

        item_ids = df["item_id"].tolist() if "item_id" in df.columns else []

        if _SOURCE == "KBS":
            # KBS ratio API returns pre-computed trailing values already in %
            ids = _RATIO_IDS_KBS
            q_cols = [c for c in df.columns if "-Q" in str(c)]
            if not q_cols:
                return {}
            q = q_cols[0]
            roe_trail = _get_item(df, ids["roe"], q)
            roa_trail = _get_item(df, ids["roa"], q)
            pe_val    = _get_item(df, ids["pe"],  q)
            pb_val    = _get_item(df, ids["pb"],  q)
            # Build synthetic per-quarter ROE list from available quarters
            roe_list = []
            for qc in q_cols[:n_quarters]:
                v = _get_item(df, "roe", qc)
                roe_list.append(round(v, 2) if v is not None else None)
            roe_vals = [v for v in roe_list if v is not None]
            roe_avg_4q = round(roe_trail, 1) if roe_trail else (
                round(sum(roe_vals[:4]) / len(roe_vals[:4]), 1) if roe_vals[:4] else None
            )
            return {
                "roe_per_quarter": roe_list,
                "roe_avg_4q": roe_avg_4q,
                "roe_trend": "unknown",
                "roa_latest": round(roa_trail, 2) if roa_trail else None,
                "pe_latest": round(pe_val, 1) if pe_val else None,
                "pb_latest": round(pb_val, 2) if pb_val else None,
            }

        # VCI: detect column names dynamically
        q_cols = [c for c in df.columns if "-Q" in str(c)]
        if not q_cols:
            return {}
        q_cols = q_cols[:n_quarters]

        roe_id = next((i for i in item_ids if "roe" in str(i).lower()), None)
        roa_id = next((i for i in item_ids if "roa" in str(i).lower()), None)
        pe_id  = next((i for i in item_ids if str(i).lower() in ("pe", "p_e", "price_earnings")), None)
        pb_id  = next((i for i in item_ids if str(i).lower() in ("pb", "p_b", "price_book")), None)

        roe_list = []
        for q in q_cols:
            val = _get_item(df, roe_id, q) if roe_id else None
            if val and abs(val) > 100:
                val = round(val / 100, 2)
            roe_list.append(round(val, 2) if val is not None else None)

        roe_vals = [v for v in roe_list if v is not None]
        roe_avg_4q = round(sum(roe_vals[:4]) / len(roe_vals[:4]), 1) if roe_vals[:4] else None

        roe_trend = "unknown"
        if len(roe_vals) >= 6:
            recent_avg = sum(roe_vals[:3]) / 3
            older_avg  = sum(roe_vals[3:6]) / 3
            if recent_avg > older_avg * 1.05:
                roe_trend = "improving"
            elif recent_avg < older_avg * 0.95:
                roe_trend = "declining"
            else:
                roe_trend = "stable"

        roa_latest = _get_item(df, roa_id, q_cols[0]) if roa_id else None
        if roa_latest and abs(roa_latest) > 100:
            roa_latest = round(roa_latest / 100, 2)
        pe_latest = _get_item(df, pe_id, q_cols[0]) if pe_id else None
        pb_latest = _get_item(df, pb_id, q_cols[0]) if pb_id else None

        return {
            "roe_per_quarter": roe_list,
            "roe_avg_4q": roe_avg_4q,
            "roe_trend": roe_trend,
            "roa_latest": round(roa_latest, 2) if roa_latest else None,
            "pe_latest": round(pe_latest, 1) if pe_latest else None,
            "pb_latest": round(pb_latest, 2) if pb_latest else None,
        }
    except Exception as e:
        print(f"[WARN] Ratio fetch error for {ticker}: {e}", file=sys.stderr)
        return {}


def fetch_balance_sheet(ticker: str) -> dict:
    """Fetch D/E ratio and equity growth from balance sheet."""
    try:
        from vnstock.api.financial import Finance
        df = Finance(source=_SOURCE, symbol=ticker, show_log=False).balance_sheet(
            period="quarter", lang="en"
        )
        if df is None or df.empty:
            return {}

        q_cols = [c for c in df.columns if "-Q" in str(c)]
        if not q_cols:
            return {}

        latest_q = q_cols[0]
        yago_q   = q_cols[4] if len(q_cols) > 4 else None

        item_ids = df["item_id"].tolist() if "item_id" in df.columns else []
        scale = _VALUE_SCALE.get(_SOURCE, 1e9)
        id_map = _BALANCE_IDS.get(_SOURCE, _BALANCE_IDS["VCI"])

        def find_id(candidates):
            for c in candidates:
                if c in item_ids:
                    return c
            # fallback: partial match
            for c in candidates:
                match = next((i for i in item_ids if c.lower() in str(i).lower()), None)
                if match:
                    return match
            return None

        equity_id = find_id(id_map["equity"])
        debt_id   = find_id(id_map["debt"])
        assets_id = find_id(id_map["assets"])

        equity_latest = _get_item(df, equity_id, latest_q) if equity_id else None
        debt_latest   = _get_item(df, debt_id,   latest_q) if debt_id else None
        assets_latest = _get_item(df, assets_id, latest_q) if assets_id else None
        equity_yago   = _get_item(df, equity_id, yago_q)   if (equity_id and yago_q) else None

        de_ratio = None
        if debt_latest and equity_latest and equity_latest > 0:
            de_ratio = round(debt_latest / equity_latest, 2)

        equity_growth = None
        if equity_latest and equity_yago and equity_yago > 0:
            equity_growth = round((equity_latest / equity_yago - 1) * 100, 1)

        assets_b = round(assets_latest / scale, 0) if assets_latest else None

        return {
            "debt_to_equity": de_ratio,
            "equity_growth_yoy": equity_growth,
            "total_assets_latest_b_vnd": assets_b,
        }
    except Exception as e:
        print(f"[WARN] Balance sheet error for {ticker}: {e}", file=sys.stderr)
        return {}


def fetch_cash_flow(ticker: str, n_quarters: int = 4) -> dict:
    """Compute FCF from operating CF - capex over last n quarters."""
    try:
        from vnstock.api.financial import Finance
        df = Finance(source=_SOURCE, symbol=ticker, show_log=False).cash_flow(
            period="quarter", lang="en"
        )
        if df is None or df.empty:
            return {}

        q_cols = [c for c in df.columns if "-Q" in str(c)]
        if not q_cols:
            return {}

        q_cols = q_cols[:n_quarters]
        item_ids = df["item_id"].tolist() if "item_id" in df.columns else []
        scale = _VALUE_SCALE.get(_SOURCE, 1e9)
        cf_map = _CF_IDS.get(_SOURCE, _CF_IDS["VCI"])

        def find_cf_id(candidates):
            for c in candidates:
                if c in item_ids:
                    return c
            for c in candidates:
                match = next((i for i in item_ids if c.lower() in str(i).lower()), None)
                if match:
                    return match
            return None

        op_cf_id = find_cf_id(cf_map["operating"])
        capex_id = find_cf_id(cf_map["capex"])

        op_cf_total = 0.0
        capex_total = 0.0
        quarters_used = 0

        for q in q_cols:
            op = _get_item(df, op_cf_id, q) if op_cf_id else None
            cx = _get_item(df, capex_id, q) if capex_id else None
            if op is not None:
                op_cf_total += op
                quarters_used += 1
            if cx is not None:
                capex_total += cx

        if quarters_used == 0:
            return {}

        fcf = op_cf_total - abs(capex_total)
        fcf_b = round(fcf / scale, 1)
        fcf_positive = fcf > 0

        return {
            "fcf_4q_sum_b_vnd": fcf_b,
            "fcf_positive": fcf_positive,
            "quarters_used": quarters_used,
        }
    except Exception as e:
        print(f"[WARN] Cash flow error for {ticker}: {e}", file=sys.stderr)
        return {}


# ---------------------------------------------------------------------------
# Peer revenue rank
# ---------------------------------------------------------------------------

def fetch_peer_revenue_rank(ticker: str, peers: list) -> list:
    """Fetch latest quarter revenue for peers and rank them."""
    try:
        from vnstock.api.financial import Finance
    except ImportError:
        return []

    results = {}
    for p in peers:
        try:
            df = Finance(source=_SOURCE, symbol=p, show_log=False).income_statement(
                period="quarter", lang="en"
            )
            if df is None or df.empty:
                continue
            q_cols = [c for c in df.columns if "-Q" in str(c)]
            if not q_cols:
                continue
            ids = _INCOME_IDS.get(_SOURCE, _INCOME_IDS["VCI"])
            scale = _VALUE_SCALE.get(_SOURCE, 1e9)
            rev = _get_item(df, ids["revenue"], q_cols[0])
            if rev is not None:
                results[p] = round(rev / scale, 1)
            time.sleep(0.5)
        except Exception as e:
            print(f"[WARN] Peer revenue error for {p}: {e}", file=sys.stderr)
            continue

    sorted_peers = sorted(results.items(), key=lambda x: x[1], reverse=True)
    ranked = []
    for i, (t, rev) in enumerate(sorted_peers, 1):
        ranked.append({"ticker": t, "revenue_latest_q_b_vnd": rev, "rank": i})

    if ticker not in results and results:
        ranked.append({"ticker": ticker, "revenue_latest_q_b_vnd": None, "rank": None})

    return ranked


def compute_industry_avg(peers: list, exclude_ticker: str | None = None) -> dict:
    """Compute average gross_margin and net_margin across peers."""
    try:
        from vnstock.api.financial import Finance
    except ImportError:
        return {}

    gm_vals, nm_vals = [], []
    for p in peers:
        if p == exclude_ticker:
            continue
        try:
            df = Finance(source=_SOURCE, symbol=p, show_log=False).income_statement(
                period="quarter", lang="en"
            )
            if df is None or df.empty:
                continue
            q_cols = [c for c in df.columns if "-Q" in str(c)]
            if not q_cols:
                continue
            ids = _INCOME_IDS.get(_SOURCE, _INCOME_IDS["VCI"])
            rev = _get_item(df, ids["revenue"], q_cols[0])
            gp  = _get_item(df, ids["gross_profit"], q_cols[0])
            ni  = _get_item(df, ids["net_income"], q_cols[0])
            if rev and rev > 0:
                if gp is not None:
                    gm_vals.append(gp / rev * 100)
                if ni is not None:
                    nm_vals.append(ni / rev * 100)
            time.sleep(0.5)
        except Exception:
            continue

    return {
        "gross_margin": round(sum(gm_vals) / len(gm_vals), 1) if gm_vals else None,
        "net_margin": round(sum(nm_vals) / len(nm_vals), 1) if nm_vals else None,
    }


# ---------------------------------------------------------------------------
# Quality score
# ---------------------------------------------------------------------------

def compute_quality_score(metrics: dict, industry_code: str) -> dict:
    score = 0.0
    breakdown = {}
    is_bank = industry_code == "BANK"
    is_realestate = industry_code == "REALESTATE"
    is_energy = industry_code == "ENERGY"

    # 1. ROE avg 4Q (1.5 pts)
    roe = metrics.get("roe_avg_4q")
    if roe is not None:
        pts = 1.5 if roe >= 20 else (1.0 if roe >= 15 else (0.5 if roe >= 10 else 0))
    else:
        pts = 0
    score += pts
    breakdown["roe"] = pts

    # 2. Net margin latest (1.5 pts)
    nm = metrics.get("net_margin_latest")
    if nm is not None:
        pts = 1.5 if nm >= 15 else (1.0 if nm >= 8 else (0.5 if nm >= 3 else 0))
    else:
        pts = 0
    score += pts
    breakdown["net_margin"] = pts

    # 3. Gross margin stability (2.0 pts)
    gm_std = metrics.get("gross_margin_std_8q")
    if gm_std is not None:
        pts = 2.0 if gm_std <= 2 else (1.5 if gm_std <= 4 else (1.0 if gm_std <= 6 else 0.5))
    else:
        pts = 0
    score += pts
    breakdown["margin_stability"] = pts

    # 4. D/E ratio (2.0 pts) — replaced by ROA for banks
    if is_bank:
        roa = metrics.get("roa_latest")
        if roa is not None:
            pts = 2.0 if roa >= 1.0 else (1.0 if roa >= 0.5 else 0)
        else:
            pts = 0
        breakdown["roa_bank"] = pts
    else:
        de = metrics.get("debt_to_equity")
        if de is not None:
            if is_energy:
                pts = 2.0 if de <= 2.0 else (1.5 if de <= 3.0 else (1.0 if de <= 4.0 else 0))
            else:
                pts = 2.0 if de <= 0.5 else (1.5 if de <= 1.0 else (1.0 if de <= 2.0 else 0))
        else:
            pts = 0
        breakdown["debt_to_equity"] = pts
    score += pts

    # 5. FCF quality (2.0 pts)
    cf = metrics.get("cash_flow", {})
    fcf_pos = cf.get("fcf_positive")
    fcf_b   = cf.get("fcf_4q_sum_b_vnd")
    nm_val  = metrics.get("net_margin_latest")

    if fcf_pos is None:
        pts = 0
    elif not fcf_pos:
        pts = 0.5 if is_realestate else 0
    else:
        # Try to compute FCF/NI ratio
        rev_b = metrics.get("revenue_latest_b_vnd")
        if rev_b and nm_val and rev_b > 0:
            ni_b = rev_b * nm_val / 100 * 4  # annualized NI estimate
            ratio = fcf_b / ni_b if ni_b and ni_b != 0 else None
        else:
            ratio = None
        if ratio is not None and ratio >= 0.8:
            pts = 2.0
        elif ratio is not None and ratio >= 0.5:
            pts = 1.5
        else:
            pts = 1.0
    score += pts
    breakdown["fcf"] = pts

    # 6. Revenue CAGR 2Y (1.0 pt)
    cagr = metrics.get("revenue_cagr_2y")
    if cagr is not None:
        pts = 1.0 if cagr >= 10 else (0.5 if cagr >= 0 else 0)
    else:
        pts = 0
    score += pts
    breakdown["revenue_growth"] = pts

    return {
        "total": round(min(score, 10.0), 1),
        "max": 10,
        "breakdown": breakdown,
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    global _SOURCE
    parser = argparse.ArgumentParser()
    parser.add_argument("--ticker", required=True)
    parser.add_argument("--source", default="VCI", help="vnstock data source: VCI or TCBS")
    args = parser.parse_args()

    ticker = args.ticker.upper().strip()
    _SOURCE = args.source.upper()
    source_suffix = f"_{_SOURCE}" if _SOURCE != "VCI" else ""
    output_file = DATA_DIR / f"business_snapshot_{ticker}{source_suffix}_{TODAY}.json"

    if output_file.exists():
        print(f"[stock-business] Cache hit: {output_file.name}")
        return

    print(f"[stock-business] Fetching data for {ticker} (source={_SOURCE})...")

    industry_code, industry_name = detect_industry(ticker)
    print(f"[stock-business] Industry: {industry_name} ({industry_code})")

    peers = KNOWN_PEERS.get(industry_code, [ticker])
    if ticker not in peers:
        peers = [ticker] + [p for p in peers if p != ticker]
    peers = peers[:5]

    warnings = []

    print("[stock-business] Fetching company profile...")
    company = fetch_company_profile(ticker)
    officers = fetch_officers(ticker)
    shareholders = fetch_shareholders(ticker)

    print("[stock-business] Fetching income statement (8Q)...")
    income = fetch_income_multi_quarter(ticker, 8)
    if not income:
        warnings.append("income_statement: no data returned")

    print("[stock-business] Fetching ratios (8Q)...")
    ratios = fetch_ratios(ticker, 8)
    if not ratios:
        warnings.append("ratios: no data returned")

    print("[stock-business] Fetching balance sheet...")
    balance = fetch_balance_sheet(ticker)
    if not balance:
        warnings.append("balance_sheet: no data returned")

    print("[stock-business] Fetching cash flow (4Q)...")
    cf = fetch_cash_flow(ticker, 4)
    if not cf:
        warnings.append("cash_flow: no data returned")

    print(f"[stock-business] Fetching peer revenue rank ({peers})...")
    peer_rank = fetch_peer_revenue_rank(ticker, peers)

    print("[stock-business] Computing industry averages...")
    industry_avg = compute_industry_avg(peers, exclude_ticker=ticker)

    # Collect flat metrics for quality score
    metrics = {
        "roe_avg_4q":          ratios.get("roe_avg_4q"),
        "roa_latest":          ratios.get("roa_latest"),
        "net_margin_latest":   income.get("net_margin_latest"),
        "gross_margin_std_8q": income.get("gross_margin_std_8q"),
        "debt_to_equity":      balance.get("debt_to_equity"),
        "revenue_cagr_2y":     income.get("revenue_cagr_2y"),
        "cash_flow":           cf,
        "revenue_latest_b_vnd": income.get("revenue_b_vnd", [None])[0],
    }

    # Check missing criteria
    criteria_keys = ["roe_avg_4q", "net_margin_latest", "gross_margin_std_8q",
                     "debt_to_equity", "revenue_cagr_2y"]
    for k in criteria_keys:
        if metrics.get(k) is None:
            warnings.append(f"quality_score_{k}: missing data → 0 pts")
    if not cf:
        warnings.append("quality_score_fcf: missing data → 0 pts")

    quality_score = compute_quality_score(metrics, industry_code)

    snapshot = {
        "date": TODAY,
        "ticker": ticker,
        "industry_code": industry_code,
        "industry_name": industry_name,
        "company": company,
        "officers": officers,
        "shareholders": shareholders,
        "financials": income,
        "ratios": ratios,
        "balance_sheet": balance,
        "cash_flow": cf,
        "peer_revenue_rank": peer_rank,
        "industry_avg": industry_avg,
        "quality_score": quality_score,
        "data_warnings": warnings,
    }

    output_file.write_text(json.dumps(snapshot, indent=2, ensure_ascii=False))
    print(f"[stock-business] Saved → {output_file.name}")


if __name__ == "__main__":
    main()
