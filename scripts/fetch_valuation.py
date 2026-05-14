#!/usr/bin/env python3
"""Fetch valuation snapshot for Vietnamese stock.

Usage:
  python fetch_valuation.py --ticker HPG
  python fetch_valuation.py --ticker VCB --wacc 12.0 --force
"""

import argparse
import json
import os
import sys
import warnings
from datetime import date, timedelta
from pathlib import Path

warnings.filterwarnings("ignore")

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent.parent / "data" / ".env")
except ImportError:
    pass

SKILL_DIR = Path(__file__).parent.parent
DATA_DIR  = SKILL_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)

TODAY = date.today().isoformat()

_vnstock_key = os.getenv("VNSTOCK_API_KEY", "")
if _vnstock_key:
    try:
        import vnstock as _vn
        _vn.change_api_key(_vnstock_key)
    except Exception as e:
        print(f"[WARN] Could not set vnstock API key: {e}", file=sys.stderr)

# ─── Constants (same as fetch_financials.py) ──────────────────────────────────

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
    "HPG":"STEEL",  "HSG":"STEEL",  "NKG":"STEEL",  "SMC":"STEEL",
    "VCB":"BANK",   "BID":"BANK",   "CTG":"BANK",   "MBB":"BANK",
    "TCB":"BANK",   "ACB":"BANK",   "VPB":"BANK",   "HDB":"BANK",
    "STB":"BANK",   "SHB":"BANK",
    "VHM":"REALESTATE","NVL":"REALESTATE","KDH":"REALESTATE",
    "PDR":"REALESTATE","DXG":"REALESTATE","NLG":"REALESTATE",
    "SSI":"SECURITIES","VCI":"SECURITIES","HCM":"SECURITIES",
    "VND":"SECURITIES","MBS":"SECURITIES",
    "MWG":"RETAIL", "FRT":"RETAIL", "PNJ":"RETAIL", "DGW":"RETAIL",
    "GAS":"ENERGY", "PLX":"ENERGY", "PVD":"ENERGY", "BSR":"ENERGY",
    "DHG":"PHARMA", "DMC":"PHARMA", "IMP":"PHARMA", "TRA":"PHARMA",
    "FPT":"TECHNOLOGY","CMG":"TECHNOLOGY",
    "DPM":"FERTILIZER","DCM":"FERTILIZER","BFC":"FERTILIZER",
    "CTD":"CONSTRUCTION","HBC":"CONSTRUCTION","VCG":"CONSTRUCTION",
}

INDUSTRY_NAMES = {
    "STEEL":"Thép","BANK":"Ngân hàng","REALESTATE":"Bất động sản",
    "SECURITIES":"Chứng khoán","RETAIL":"Bán lẻ",
    "ENERGY":"Năng lượng / Dầu khí","PHARMA":"Dược phẩm",
    "TECHNOLOGY":"Công nghệ","FERTILIZER":"Phân bón","CONSTRUCTION":"Xây dựng",
}

_SOURCE      = "VCI"
_VALUE_SCALE = {"VCI": 1e9, "KBS": 1e6}

_INCOME_IDS = {
    "VCI": {
        "revenue":      "isa3",
        "gross_profit": "isa5",
        "net_income":   "isa20",
        "ebit":         ["isa8", "operating_income", "ebit"],
    },
    "KBS": {
        "revenue":      "n_3.net_revenue",
        "gross_profit": "n_5.gross_profit",
        "net_income":   "n_18.net_profit_after_tax",
        "ebit":         ["operating_income", "ebit"],
    },
}

_BALANCE_IDS = {
    "VCI": {
        "equity":     ["bsa84", "total_equity", "equity"],
        "total_debt": ["bsa47", "total_debt", "long_term_liabilities"],
        "cash":       ["bsa1",  "cash_and_equivalents", "cash"],
    },
    "KBS": {
        "equity":     ["d.owners_equity"],
        "total_debt": ["n_11.short_term_borrowings_and_financial_leases"],
        "cash":       ["cash_and_equivalents"],
    },
}

_CF_IDS = {
    "VCI": {
        "operating": ["cfa3", "net_cash_operating", "operating_cash_flow"],
        "capex":     ["cfa10", "purchase_fixed_assets", "capital_expenditure"],
        "da":        ["cfa2",  "depreciation_amortization", "da"],
    },
    "KBS": {
        "operating": ["net_cash_flows_from_operating_activities"],
        "capex":     ["n_1.payment_for_fixed_assets_constructions_and_other_long_term_assets"],
        "da":        ["depreciation_and_amortization"],
    },
}

WACC_DEFAULTS = {"BANK": 12.0, "REALESTATE": 13.0, "ENERGY": 10.0, "DEFAULT": 11.0}
TERMINAL_GROWTH = 4.0  # % — conservative (below VN nominal GDP ~6%)

DCF_GROWTH = {
    "bear": -0.03,  # FCF giảm 3%/năm
    "base":  0.07,  # FCF tăng 7%/năm
    "bull":  0.15,  # FCF tăng 15%/năm
}

# Primary valuation method by industry
PRIMARY_METHOD = {
    "BANK": "PB", "SECURITIES": "PB", "REALESTATE": "PB",
    "DEFAULT": "PE",
}


# ─── Helpers (same pattern as fetch_financials.py) ───────────────────────────

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


def detect_industry(ticker: str) -> tuple:
    code = TICKER_INDUSTRY_MAP.get(ticker.upper())
    if code:
        return code, INDUSTRY_NAMES.get(code, code)
    return "UNKNOWN", "Không xác định"


def _pct_stats(series: list) -> dict:
    valid = sorted(v for v in series if v is not None and v > 0)
    if not valid:
        return {"min": None, "max": None, "median": None, "p25": None, "p75": None, "latest": None}
    n = len(valid)
    median = valid[n // 2] if n % 2 else (valid[n // 2 - 1] + valid[n // 2]) / 2

    def _pct(p):
        idx = (n - 1) * p / 100
        lo, hi = int(idx), int(idx) + 1
        if hi >= n:
            return valid[-1]
        return valid[lo] + (idx - lo) * (valid[hi] - valid[lo])

    return {
        "min":    round(min(valid), 1),
        "max":    round(max(valid), 1),
        "median": round(median, 1),
        "p25":    round(_pct(25), 1),
        "p75":    round(_pct(75), 1),
        "latest": round(series[0], 1) if series[0] is not None and series[0] > 0 else None,
    }


# ─── Data Fetchers ────────────────────────────────────────────────────────────

def fetch_ratio_series(ticker: str, n_quarters: int = 8) -> dict:
    """Fetch P/E, P/B, EPS, BVPS time series from ratio statement (8Q)."""
    try:
        from vnstock.api.financial import Finance
        df = Finance(source=_SOURCE, symbol=ticker, show_log=False).ratio(
            period="quarter", lang="en"
        )
        if df is None or df.empty:
            return {}

        item_ids = df["item_id"].tolist() if "item_id" in df.columns else []
        q_cols   = _dedup_quarters([c for c in df.columns if "-Q" in str(c)], n_quarters)
        if not q_cols:
            return {}

        # Flexible ID matching — VCI item_ids are lower-case short codes
        pe_id   = next((i for i in item_ids if str(i).lower() in
                        ("pe", "p_e", "pricetoearnings", "price_earnings", "price_to_earnings")), None)
        pb_id   = next((i for i in item_ids if str(i).lower() in
                        ("pb", "p_b", "pricetobook", "price_book", "price_to_book")), None)
        eps_id  = next((i for i in item_ids
                        if "eps" in str(i).lower() and "bvps" not in str(i).lower()), None)
        bvps_id = next((i for i in item_ids
                        if "bvps" in str(i).lower() or "book_value_per" in str(i).lower()), None)
        shares_id = next((i for i in item_ids
                          if ("listed" in str(i).lower() or "outstanding" in str(i).lower())
                          and "share" in str(i).lower()), None)

        pe_vals, pb_vals, eps_vals, bvps_vals = [], [], [], []
        for q in q_cols:
            pe   = _get_item(df, pe_id,   q) if pe_id   else None
            pb   = _get_item(df, pb_id,   q) if pb_id   else None
            eps  = _get_item(df, eps_id,  q) if eps_id  else None
            bvps = _get_item(df, bvps_id, q) if bvps_id else None
            # Sanity filters
            pe_vals.append(pe   if pe   and 0 < pe   < 200 else None)
            pb_vals.append(pb   if pb   and 0 < pb   < 50  else None)
            eps_vals.append(eps   if eps   and eps   > 0 else None)
            bvps_vals.append(bvps if bvps and bvps > 0 else None)

        # Shares outstanding
        shares_m = None
        if shares_id:
            sv = _get_item(df, shares_id, q_cols[0])
            if sv and sv > 0:
                # Vietnamese stocks: 100M–5B shares; raw units > 1e8
                shares_m = round(sv / 1e6, 1) if sv > 1e8 else round(sv, 1)

        return {
            "quarters":    [q.split("_")[0] for q in q_cols],
            "hist_pe":     _pct_stats(pe_vals),
            "hist_pb":     _pct_stats(pb_vals),
            "eps_latest":  eps_vals[0] if eps_vals else None,
            "bvps_latest": bvps_vals[0] if bvps_vals else None,
            "shares_m":    shares_m,
        }
    except Exception as e:
        print(f"[WARN] Ratio series fetch error for {ticker}: {e}", file=sys.stderr)
        return {}


def fetch_income_ttm(ticker: str) -> dict:
    """Fetch income statement (8Q), compute TTM totals."""
    try:
        from vnstock.api.financial import Finance
        df = Finance(source=_SOURCE, symbol=ticker, show_log=False).income_statement(
            period="quarter", lang="en"
        )
        if df is None or df.empty:
            return {}

        q_cols   = _dedup_quarters([c for c in df.columns if "-Q" in str(c)], 8)
        if not q_cols:
            return {}

        item_ids = df["item_id"].tolist() if "item_id" in df.columns else []
        scale    = _VALUE_SCALE.get(_SOURCE, 1e9)
        ids      = _INCOME_IDS.get(_SOURCE, _INCOME_IDS["VCI"])

        rev_id  = ids["revenue"]      if isinstance(ids["revenue"], str)      else _find_id(item_ids, ids["revenue"])
        gp_id   = ids["gross_profit"] if isinstance(ids["gross_profit"], str) else _find_id(item_ids, ids["gross_profit"])
        ni_id   = ids["net_income"]   if isinstance(ids["net_income"], str)   else _find_id(item_ids, ids["net_income"])
        ebit_id = _find_id(item_ids, ids["ebit"])

        rev_b, gp_b, ni_b, ebit_b = [], [], [], []
        for q in q_cols:
            rev  = _get_item(df, rev_id,  q)
            gp   = _get_item(df, gp_id,   q)
            ni   = _get_item(df, ni_id,   q)
            eb   = _get_item(df, ebit_id, q)
            rev_b.append(round(rev / scale, 1)  if rev  else None)
            gp_b.append(round(gp  / scale, 1)   if gp   else None)
            ni_b.append(round(ni  / scale, 1)   if ni   else None)
            ebit_b.append(round(eb / scale, 1)  if eb   else None)

        def _ttm(lst):
            vals = [v for v in lst[:4] if v is not None]
            return round(sum(vals), 1) if vals else None

        return {
            "revenue_b":      rev_b,
            "ni_b":           ni_b,
            "ebit_b":         ebit_b,
            "revenue_ttm_b":  _ttm(rev_b),
            "ni_ttm_b":       _ttm(ni_b),
            "ebit_ttm_b":     _ttm(ebit_b),
        }
    except Exception as e:
        print(f"[WARN] Income TTM fetch error for {ticker}: {e}", file=sys.stderr)
        return {}


def fetch_balance_latest(ticker: str) -> dict:
    """Fetch balance sheet, return latest quarter equity, debt, cash."""
    try:
        from vnstock.api.financial import Finance
        df = Finance(source=_SOURCE, symbol=ticker, show_log=False).balance_sheet(
            period="quarter", lang="en"
        )
        if df is None or df.empty:
            return {}

        q_cols   = _dedup_quarters([c for c in df.columns if "-Q" in str(c)], 2)
        if not q_cols:
            return {}

        item_ids = df["item_id"].tolist() if "item_id" in df.columns else []
        scale    = _VALUE_SCALE.get(_SOURCE, 1e9)
        id_map   = _BALANCE_IDS.get(_SOURCE, _BALANCE_IDS["VCI"])

        equity_id = _find_id(item_ids, id_map["equity"])
        debt_id   = _find_id(item_ids, id_map["total_debt"])
        cash_id   = _find_id(item_ids, id_map["cash"])

        q = q_cols[0]
        equity = _get_item(df, equity_id, q)
        debt   = _get_item(df, debt_id,   q)
        cash   = _get_item(df, cash_id,   q)

        equity_b   = round(equity / scale, 1) if equity else None
        debt_b     = round(debt   / scale, 1) if debt   else None
        cash_b     = round(cash   / scale, 1) if cash   else None
        net_debt_b = round(debt_b - cash_b, 1) if debt_b is not None and cash_b is not None else None

        return {
            "equity_b":   equity_b,
            "debt_b":     debt_b,
            "cash_b":     cash_b,
            "net_debt_b": net_debt_b,
        }
    except Exception as e:
        print(f"[WARN] Balance latest fetch error for {ticker}: {e}", file=sys.stderr)
        return {}


def fetch_cashflow_ttm(ticker: str) -> dict:
    """Fetch cash flow (4Q), compute TTM OCF, capex, FCF, D&A."""
    try:
        from vnstock.api.financial import Finance
        df = Finance(source=_SOURCE, symbol=ticker, show_log=False).cash_flow(
            period="quarter", lang="en"
        )
        if df is None or df.empty:
            return {}

        q_cols   = _dedup_quarters([c for c in df.columns if "-Q" in str(c)], 4)
        if not q_cols:
            return {}

        item_ids = df["item_id"].tolist() if "item_id" in df.columns else []
        scale    = _VALUE_SCALE.get(_SOURCE, 1e9)
        cf_map   = _CF_IDS.get(_SOURCE, _CF_IDS["VCI"])

        ocf_id   = _find_id(item_ids, cf_map["operating"])
        capex_id = _find_id(item_ids, cf_map["capex"])
        da_id    = _find_id(item_ids, cf_map["da"])

        ocf_b, capex_b, fcf_b, da_b = [], [], [], []
        for q in q_cols:
            ocf   = _get_item(df, ocf_id,   q) if ocf_id   else None
            capex = _get_item(df, capex_id, q) if capex_id else None
            da    = _get_item(df, da_id,    q) if da_id    else None

            ocf_v   = round(ocf   / scale, 1) if ocf   is not None else None
            capex_v = round(capex / scale, 1) if capex is not None else None
            da_v    = round(abs(da) / scale, 1) if da  is not None else None
            fcf_v   = round(ocf_v - abs(capex_v), 1) if ocf_v is not None and capex_v is not None else ocf_v

            ocf_b.append(ocf_v); capex_b.append(capex_v)
            fcf_b.append(fcf_v); da_b.append(da_v)

        def _sum(lst):
            vals = [v for v in lst if v is not None]
            return round(sum(vals), 1) if vals else None

        return {
            "ocf_ttm_b":   _sum(ocf_b),
            "capex_ttm_b": _sum([abs(v) for v in capex_b if v is not None]),
            "fcf_ttm_b":   _sum(fcf_b),
            "da_ttm_b":    _sum(da_b),
        }
    except Exception as e:
        print(f"[WARN] Cashflow TTM fetch error for {ticker}: {e}", file=sys.stderr)
        return {}


def fetch_current_price(ticker: str) -> float | None:
    """Fetch latest closing price from trading history (last 15 days)."""
    try:
        from vnstock import Vnstock
        end   = TODAY
        start = (date.today() - timedelta(days=15)).isoformat()
        hist  = Vnstock().stock(symbol=ticker, source=_SOURCE).trading.history(
            symbol=ticker, start=start, end=end, interval="1D"
        )
        if hist is not None and len(hist) > 0:
            price = _safe_float(hist.iloc[-1]["close"])
            if price and price > 0:
                return price
    except Exception as e:
        print(f"[WARN] Current price fetch error for {ticker}: {e}", file=sys.stderr)
    return None


def fetch_peer_multiples(industry_code: str, ticker: str) -> dict:
    """Fetch latest P/E and P/B for peers (max 4, excluding self)."""
    peers = [p for p in KNOWN_PEERS.get(industry_code, []) if p != ticker][:4]
    pe_list, pb_list, valid_tickers = [], [], []

    for peer in peers:
        try:
            from vnstock.api.financial import Finance
            df = Finance(source=_SOURCE, symbol=peer, show_log=False).ratio(
                period="quarter", lang="en"
            )
            if df is None or df.empty:
                continue
            item_ids = df["item_id"].tolist() if "item_id" in df.columns else []
            q_cols   = _dedup_quarters([c for c in df.columns if "-Q" in str(c)], 1)
            if not q_cols:
                continue

            pe_id = next((i for i in item_ids if str(i).lower() in
                          ("pe", "p_e", "pricetoearnings", "price_earnings")), None)
            pb_id = next((i for i in item_ids if str(i).lower() in
                          ("pb", "p_b", "pricetobook", "price_book")), None)

            q  = q_cols[0]
            pe = _get_item(df, pe_id, q) if pe_id else None
            pb = _get_item(df, pb_id, q) if pb_id else None

            if pe and 0 < pe < 100:
                pe_list.append(pe)
            if pb and 0 < pb < 20:
                pb_list.append(pb)
            if pe or pb:
                valid_tickers.append(peer)
        except Exception:
            pass

    def _median(lst):
        valid = sorted(v for v in lst if v is not None)
        if not valid:
            return None
        n   = len(valid)
        mid = n // 2
        return round((valid[mid - 1] + valid[mid]) / 2, 1) if n % 2 == 0 else round(valid[mid], 1)

    return {
        "pe_median":  _median(pe_list),
        "pb_median":  _median(pb_list),
        "tickers":    valid_tickers,
    }


# ─── Computation ─────────────────────────────────────────────────────────────

def compute_ebitda(income: dict, cashflow: dict) -> float | None:
    """EBITDA = EBIT + D&A (fallback to EBIT if D&A unavailable)."""
    ebit = income.get("ebit_ttm_b")
    da   = cashflow.get("da_ttm_b")
    if ebit is None:
        return None
    return round(ebit + da, 1) if da else ebit


def compute_current_multiples(income: dict, balance: dict, cashflow: dict,
                               ratio: dict, current_price: float | None,
                               shares_m: float | None) -> dict:
    """Current P/E (from ratio), P/B, EV/EBITDA."""
    hist_pe = ratio.get("hist_pe", {})
    hist_pb = ratio.get("hist_pb", {})
    pe_ttm    = hist_pe.get("latest")
    pb_latest = hist_pb.get("latest")

    market_cap_b = None
    if shares_m and current_price and shares_m > 0:
        # shares_m (millions) × price (VND) / 1000 = B VND
        market_cap_b = round(shares_m * current_price / 1000, 1)

    ebitda_ttm_b = compute_ebitda(income, cashflow)
    ev_ebitda    = None
    if market_cap_b is not None and balance.get("net_debt_b") is not None and ebitda_ttm_b and ebitda_ttm_b > 0:
        ev = market_cap_b + balance["net_debt_b"]
        ev_ebitda = round(ev / ebitda_ttm_b, 1)

    return {
        "pe_ttm":        pe_ttm,
        "pb_latest":     pb_latest,
        "ev_ebitda":     ev_ebitda,
        "market_cap_b":  market_cap_b,
        "ebitda_ttm_b":  ebitda_ttm_b,
    }


def build_scenarios(primary_method: str,
                    hist_pe: dict, hist_pb: dict,
                    peer_multiples: dict,
                    eps_ttm: float | None,
                    bvps_latest: float | None,
                    current_price: float | None) -> dict:
    """Build bear/base/bull price targets from historical + peer multiples."""

    def _upside(target, price):
        if target and price and price > 0:
            return round((target - price) / price * 100, 1)
        return None

    peer_pe = peer_multiples.get("pe_median")
    peer_pb = peer_multiples.get("pb_median")

    if primary_method == "PE" and eps_ttm and eps_ttm > 0:
        pe_bear = hist_pe.get("p25")  or (round(peer_pe * 0.75, 1) if peer_pe else None)
        pe_base = hist_pe.get("median") or peer_pe
        pe_bull = hist_pe.get("p75")  or (round(peer_pe * 1.25, 1) if peer_pe else None)

        def _label_pe(multiple, hist_key, hist_dict, fallback_suffix):
            if hist_dict.get(hist_key):
                return f"P/E {multiple}× ({hist_key} hist 8Q)"
            return f"P/E {multiple}× (peer {fallback_suffix})"

        bear_tp = round(pe_bear * eps_ttm) if pe_bear else None
        base_tp = round(pe_base * eps_ttm) if pe_base else None
        bull_tp = round(pe_bull * eps_ttm) if pe_bull else None

        return {
            "primary_method": "PE",
            "eps_ttm": eps_ttm,
            "bear": {"multiple": pe_bear, "assumption": _label_pe(pe_bear, "p25",    hist_pe, "× 0.75"), "target_price": bear_tp, "upside_pct": _upside(bear_tp, current_price)},
            "base": {"multiple": pe_base, "assumption": _label_pe(pe_base, "median", hist_pe, "median"), "target_price": base_tp, "upside_pct": _upside(base_tp, current_price)},
            "bull": {"multiple": pe_bull, "assumption": _label_pe(pe_bull, "p75",    hist_pe, "× 1.25"), "target_price": bull_tp, "upside_pct": _upside(bull_tp, current_price)},
        }

    elif primary_method == "PB" and bvps_latest and bvps_latest > 0:
        pb_bear = hist_pb.get("p25")   or (round(peer_pb * 0.75, 2) if peer_pb else None)
        pb_base = hist_pb.get("median") or peer_pb
        pb_bull = hist_pb.get("p75")   or (round(peer_pb * 1.25, 2) if peer_pb else None)

        def _label_pb(multiple, hist_key, hist_dict, fallback_suffix):
            if hist_dict.get(hist_key):
                return f"P/B {multiple}× ({hist_key} hist 8Q)"
            return f"P/B {multiple}× (peer {fallback_suffix})"

        bear_tp = round(pb_bear * bvps_latest) if pb_bear else None
        base_tp = round(pb_base * bvps_latest) if pb_base else None
        bull_tp = round(pb_bull * bvps_latest) if pb_bull else None

        return {
            "primary_method": "PB",
            "bvps_latest": bvps_latest,
            "bear": {"multiple": pb_bear, "assumption": _label_pb(pb_bear, "p25",    hist_pb, "× 0.75"), "target_price": bear_tp, "upside_pct": _upside(bear_tp, current_price)},
            "base": {"multiple": pb_base, "assumption": _label_pb(pb_base, "median", hist_pb, "median"), "target_price": base_tp, "upside_pct": _upside(base_tp, current_price)},
            "bull": {"multiple": pb_bull, "assumption": _label_pb(pb_bull, "p75",    hist_pb, "× 1.25"), "target_price": bull_tp, "upside_pct": _upside(bull_tp, current_price)},
        }

    else:
        missing = "eps_ttm" if primary_method == "PE" else "bvps_latest"
        return {
            "primary_method": primary_method,
            "bear": {"multiple": None, "assumption": f"[missing_data: {missing}]", "target_price": None, "upside_pct": None},
            "base": {"multiple": None, "assumption": f"[missing_data: {missing}]", "target_price": None, "upside_pct": None},
            "bull": {"multiple": None, "assumption": f"[missing_data: {missing}]", "target_price": None, "upside_pct": None},
        }


def build_dcf(fcf_ttm_b: float | None, wacc_pct: float, tg_pct: float,
              net_debt_b: float | None, shares_m: float | None) -> dict:
    """5-year DCF with bear/base/bull FCF growth scenarios."""
    if not fcf_ttm_b or fcf_ttm_b <= 0:
        return {
            "available":           False,
            "wacc_pct":            wacc_pct,
            "terminal_growth_pct": tg_pct,
            "fcf_ttm_b":           fcf_ttm_b,
            "note":                "FCF TTM ≤ 0 — DCF không khả thi với dòng tiền âm",
        }

    wacc = wacc_pct / 100
    tg   = tg_pct   / 100
    result = {}

    for name, g in DCF_GROWTH.items():
        pv_fcf = 0.0
        cf = fcf_ttm_b
        for yr in range(1, 6):
            cf *= (1 + g)
            pv_fcf += cf / ((1 + wacc) ** yr)

        terminal_pv    = cf * (1 + tg) / (wacc - tg) / ((1 + wacc) ** 5)
        equity_value_b = pv_fcf + terminal_pv - (net_debt_b or 0)

        target_price = None
        if shares_m and shares_m > 0:
            # equity_value_b (B VND) / shares_m (M) × 1000 = VND/share
            target_price = round(equity_value_b / shares_m * 1000)

        result[name] = {
            "growth_pct":     round(g * 100, 1),
            "label":          f"FCF {'giảm' if g < 0 else 'tăng'} {abs(g)*100:.0f}%/năm",
            "equity_value_b": round(equity_value_b, 1),
            "target_price":   target_price,
        }

    return {
        "available":           True,
        "wacc_pct":            wacc_pct,
        "terminal_growth_pct": tg_pct,
        "fcf_ttm_b":           fcf_ttm_b,
        "bear":                result.get("bear"),
        "base":                result.get("base"),
        "bull":                result.get("bull"),
        "note":                None if shares_m else "shares_m unavailable — chỉ tính equity_value_b (B VND)",
    }


def compute_fair_value_and_mos(scenarios: dict, dcf: dict,
                                current_price: float | None) -> tuple:
    """Compute fair value range, upside/downside table, margin of safety."""
    bear_tp = (scenarios.get("bear") or {}).get("target_price")
    base_tp = (scenarios.get("base") or {}).get("target_price")
    bull_tp = (scenarios.get("bull") or {}).get("target_price")
    dcf_base_tp = ((dcf.get("base") or {}).get("target_price") if dcf.get("available") else None)

    # Blend DCF base into mid if available
    fair_mid = base_tp
    if dcf_base_tp and base_tp:
        fair_mid = round((base_tp + dcf_base_tp) / 2)

    fair_value = {
        "low":            bear_tp,
        "mid":            fair_mid,
        "high":           bull_tp,
        "dcf_blend_used": bool(dcf_base_tp and base_tp),
    }

    mos = {}
    upside = {"current_price": current_price}

    if current_price and current_price > 0:
        for label, tp in [("vs_bear", bear_tp), ("vs_base", base_tp),
                          ("vs_mid", fair_mid),  ("vs_bull", bull_tp),
                          ("vs_dcf_base", dcf_base_tp)]:
            if tp:
                upside[f"{label}_pct"] = round((tp - current_price) / current_price * 100, 1)

        if fair_mid:
            mos_pct = round((fair_mid - current_price) / fair_mid * 100, 1)
            mos = {
                "pct":           mos_pct,
                "vs_mid_pct":    round((fair_mid - current_price) / current_price * 100, 1),
                "current_price": current_price,
                "note": (
                    "Có biên an toàn ≥30% — vùng tích lũy"   if mos_pct >= 30 else
                    "Biên mỏng 10–30% — gần vùng hợp lý"      if mos_pct >= 10 else
                    "Biên an toàn thấp 0–10% — fully priced"   if mos_pct >= 0  else
                    "Giá đang cao hơn fair value — không có MoS"
                ),
            }

    return fair_value, mos, upside


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    global _SOURCE

    parser = argparse.ArgumentParser()
    parser.add_argument("--ticker", required=True)
    parser.add_argument("--source", default="VCI")
    parser.add_argument("--wacc",   type=float, default=None,
                        help="Override WACC %% (default: per industry)")
    parser.add_argument("--force",  action="store_true")
    args = parser.parse_args()

    ticker  = args.ticker.upper().strip()
    _SOURCE = args.source.upper()
    source_suffix = f"_{_SOURCE}" if _SOURCE != "VCI" else ""
    output_file = DATA_DIR / f"valuation_snapshot_{ticker}{source_suffix}_{TODAY}.json"

    if output_file.exists() and not args.force:
        print(f"[stock-valuation] Cache hit: {output_file.name}")
        return

    print(f"[stock-valuation] Fetching {ticker} (source={_SOURCE})...")
    industry_code, industry_name = detect_industry(ticker)
    print(f"[stock-valuation] Industry: {industry_name} ({industry_code})")

    data_warnings = []
    wacc_pct      = args.wacc or WACC_DEFAULTS.get(industry_code, WACC_DEFAULTS["DEFAULT"])
    primary_method = PRIMARY_METHOD.get(industry_code, PRIMARY_METHOD["DEFAULT"])

    # ── Fetch ────────────────────────────────────────────────────────────────

    print("[stock-valuation] Fetching ratio series (P/E, P/B, EPS, BVPS — 8Q)...")
    ratio = fetch_ratio_series(ticker, 8)
    if not ratio:
        data_warnings.append("ratio: no data — P/E/P/B scenarios unavailable")

    print("[stock-valuation] Fetching income TTM...")
    income = fetch_income_ttm(ticker)
    if not income:
        data_warnings.append("income: no data returned")

    print("[stock-valuation] Fetching balance sheet...")
    balance = fetch_balance_latest(ticker)
    if not balance:
        data_warnings.append("balance_sheet: no data returned")

    print("[stock-valuation] Fetching cashflow TTM...")
    cashflow = fetch_cashflow_ttm(ticker)
    if not cashflow:
        data_warnings.append("cashflow: no data returned")

    print("[stock-valuation] Fetching current price...")
    current_price = fetch_current_price(ticker)
    if not current_price:
        data_warnings.append("current_price: unavailable — upside/downside/MoS = null")

    shares_m = ratio.get("shares_m")
    if not shares_m:
        data_warnings.append("shares_m: unavailable — DCF per-share price = null, EV/EBITDA = null")

    print(f"[stock-valuation] Fetching peer multiples (industry={industry_code})...")
    peer_multiples = fetch_peer_multiples(industry_code, ticker)

    # ── Compute ──────────────────────────────────────────────────────────────

    current_multiples = compute_current_multiples(income, balance, cashflow,
                                                   ratio, current_price, shares_m)

    eps_ttm     = ratio.get("eps_latest")
    bvps_latest = ratio.get("bvps_latest")
    fcf_ttm_b   = cashflow.get("fcf_ttm_b")

    # Fallback EPS: NI_TTM / shares_m
    if eps_ttm is None and income.get("ni_ttm_b") and shares_m:
        eps_ttm = round(income["ni_ttm_b"] / shares_m * 1000)
        data_warnings.append("eps_ttm: computed from NI_TTM / shares_m (not from ratio data)")

    trailing_metrics = {
        "revenue_ttm_b": income.get("revenue_ttm_b"),
        "ni_ttm_b":      income.get("ni_ttm_b"),
        "ebit_ttm_b":    income.get("ebit_ttm_b"),
        "ebitda_ttm_b":  current_multiples.get("ebitda_ttm_b"),
        "fcf_ttm_b":     fcf_ttm_b,
        "eps_ttm":       eps_ttm,
        "bvps_latest":   bvps_latest,
        "shares_m":      shares_m,
    }

    hist_pe = ratio.get("hist_pe", {})
    hist_pb = ratio.get("hist_pb", {})

    scenarios   = build_scenarios(primary_method, hist_pe, hist_pb,
                                   peer_multiples, eps_ttm, bvps_latest, current_price)
    dcf         = build_dcf(fcf_ttm_b, wacc_pct, TERMINAL_GROWTH,
                             balance.get("net_debt_b"), shares_m)
    fair_value, mos, upside = compute_fair_value_and_mos(scenarios, dcf, current_price)

    # ── Industry-specific notes ───────────────────────────────────────────────

    rnav_note = ("RNAV cần land bank data từ thuyết minh BCTC hoặc analyst report — "
                 "giao NotebookLM nếu có PDF" if industry_code == "REALESTATE" else None)
    sotp_note = ("SOTP cần segment revenue/EBIT thủ công — giao Codex với dữ liệu segment"
                 if industry_code == "CONGLOMERATE" else None)

    # ── Assemble snapshot ────────────────────────────────────────────────────

    snapshot = {
        "date":              TODAY,
        "ticker":            ticker,
        "industry_code":     industry_code,
        "industry_name":     industry_name,
        "current_price":     current_price,
        "primary_method":    primary_method,
        "wacc_pct":          wacc_pct,
        "trailing_metrics":  trailing_metrics,
        "current_multiples": {
            "pe_ttm":       current_multiples.get("pe_ttm"),
            "pb_latest":    current_multiples.get("pb_latest"),
            "ev_ebitda":    current_multiples.get("ev_ebitda"),
            "market_cap_b": current_multiples.get("market_cap_b"),
        },
        "hist_pe":           hist_pe,
        "hist_pb":           hist_pb,
        "peer_multiples":    peer_multiples,
        "scenarios":         scenarios,
        "dcf":               dcf,
        "fair_value":        fair_value,
        "upside_downside":   upside,
        "margin_of_safety":  mos,
        "rnav_note":         rnav_note,
        "sotp_note":         sotp_note,
        "data_warnings":     data_warnings,
    }

    output_file.write_text(json.dumps(snapshot, indent=2, ensure_ascii=False))
    print(f"[stock-valuation] Snapshot saved → {output_file.name}")


if __name__ == "__main__":
    main()
