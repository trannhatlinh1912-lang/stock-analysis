#!/usr/bin/env python3
"""Fetch + compute fundamental metrics for VN equities.

For each ticker:
  1. Fetch income_statement, balance_sheet, cash_flow (period=year, 8y limit).
  2. Compute: ROE, ROA, D/E, NI growth CAGR, OCF positive count, revenue growth.
  3. Detect HARD red flags: consecutive losses 3y, negative equity, severe dilution.
  4. Cache per ticker JSON.
  5. Aggregate sector distribution (median, P25, P75).

NO fabrication. NaN/missing fields explicitly recorded.

Usage:
    python scripts/fetch_fundamentals.py --tickers VCB MBB ACB CTG TCB ...
"""
from __future__ import annotations

import argparse
import json
import sys
import warnings
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = REPO_ROOT / "data" / "fundamentals"
REPORTS_DIR = REPO_ROOT / "reports"
DATA_DIR.mkdir(parents=True, exist_ok=True)
REPORTS_DIR.mkdir(exist_ok=True)

# Sector mapping for the 32-ticker verification watchlist.
SECTOR_MAP: dict[str, str] = {
    # Banking
    "VCB": "banking", "MBB": "banking", "ACB": "banking",
    "CTG": "banking", "TCB": "banking",
    # Oil & Gas
    "BSR": "oil_gas", "GAS": "oil_gas", "PLX": "oil_gas",
    "PVS": "oil_gas", "PVD": "oil_gas",
    # Real Estate
    "VHM": "real_estate", "VIC": "real_estate", "KDH": "real_estate",
    "NLG": "real_estate", "DXG": "real_estate", "NVL": "real_estate",
    # Steel
    "HPG": "steel", "HSG": "steel", "NKG": "steel",
    "TLH": "steel", "SMC": "steel",
    # Consumer
    "MWG": "consumer", "MSN": "consumer", "VNM": "consumer",
    "SAB": "consumer", "FRT": "consumer",
    # Tech / Industrial
    "FPT": "tech", "REE": "tech", "GEX": "tech",
    "PC1": "tech", "CMG": "tech",
    # Securities (basket for Layer 3 sector regime)
    "VND": "securities", "SSI": "securities", "HCM": "securities",
}

# Item IDs from VCI statements (verified empirically against VCB).
# Non-bank vs bank statement structures may differ — we try multiple candidates.
ITEM_IDS = {
    "net_income": ["isa20", "isa22"],  # isa20 lợi nhuận sau thuế / isa22 cổ đông cty mẹ
    "eps": ["isa23"],                   # lãi cơ bản trên cổ phiếu
    "total_assets": ["bsa53"],          # tổng tài sản
    "total_liab": ["bsa54"],            # tổng nợ phải trả
    "equity": ["bsa78"],                # vốn chủ sở hữu
    "share_capital": ["bsa80"],         # vốn điều lệ
    "retained_earnings": ["bsa90"],     # lợi nhuận chưa phân phối
    # Revenue / Net Revenue — varies by company type
    "revenue": ["isa1", "isa3", "isb38"],  # try non-bank revenue + bank net operating income
    # Operating cash flow — typically the first cash_flow item; will fallback to first item
    "ocf": ["cfa20", "cfa21"],
}

# Banks have different statement structure (no "revenue" same way).
BANK_SECTORS = {"banking", "securities"}

# Sector-specific ROE thresholds (calibrated 2026-05-28 from 32-ticker pool).
# Threshold = sector P25 from empirical distribution. Below → quality concern.
SECTOR_ROE_THRESHOLDS = {
    "banking":     {"metric": "roe_pct_3y_avg", "min": 14.0},
    "oil_gas":     {"metric": "roe_pct_5y_avg", "min": 8.0},
    "real_estate": {"metric": "roe_pct_5y_avg", "min": 7.0},
    "steel":       {"metric": "roe_pct_5y_avg", "min": 8.0},
    "consumer":    {"metric": "roe_pct_3y_avg", "min": 10.0},
    "tech":        {"metric": "roe_pct_3y_avg", "min": 10.0},
    "securities":  {"metric": "roe_pct_3y_avg", "min": 10.0},
}

# Sector D/E ceiling (non-bank).
SECTOR_DE_CEILING = {
    "oil_gas":     2.0,
    "real_estate": 3.0,
    "steel":       1.5,
    "consumer":    2.5,
    "tech":        2.0,
    "securities":  2.0,
}


def _find_row(df: pd.DataFrame, item_ids: list[str]) -> pd.Series | None:
    """Return first row whose item_id matches any candidate."""
    for iid in item_ids:
        mask = df["item_id"] == iid
        if mask.any():
            return df[mask].iloc[0]
    return None


def _year_cols(df: pd.DataFrame) -> list[str]:
    """Return year columns sorted descending (most recent first)."""
    cols = [c for c in df.columns if c not in ("item", "item_en", "item_id")]
    # Filter numeric-year columns
    year_cols = []
    for c in cols:
        try:
            int(str(c)[:4])
            year_cols.append(str(c))
        except (ValueError, TypeError):
            continue
    # Sort descending
    return sorted(year_cols, reverse=True)


def _safe_float(v) -> float | None:
    if v is None:
        return None
    try:
        f = float(v)
        if np.isnan(f) or np.isinf(f):
            return None
        return f
    except (TypeError, ValueError):
        return None


def _cagr(series: list[float], years: int) -> float | None:
    """Compute CAGR over `years` periods. Returns None if invalid."""
    clean = [v for v in series if v is not None and v > 0]
    if len(clean) < years + 1:
        return None
    end = clean[0]   # most recent
    start = clean[years]
    if start <= 0:
        return None
    return (end / start) ** (1.0 / years) - 1.0


def fetch_ticker(symbol: str) -> dict:
    """Fetch raw statements + compute metrics for one ticker."""
    out: dict = {
        "symbol": symbol,
        "sector": SECTOR_MAP.get(symbol, "unknown"),
        "fetched_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "raw_data_available": {},
        "metrics": {},
        "hard_flags": [],
        "warning_flags": [],
        "data_completeness": {},
    }

    try:
        from vnstock.api.financial import Finance
    except Exception as e:
        out["fetch_error"] = f"import_failed: {e}"
        return out

    f = Finance(symbol=symbol, source="VCI")

    # 1. Income statement
    try:
        is_df = f.income_statement(period="year")
        out["raw_data_available"]["income_statement"] = True
    except Exception as e:
        out["raw_data_available"]["income_statement"] = False
        out["raw_data_available"]["income_statement_err"] = str(e)[:200]
        is_df = None

    # 2. Balance sheet
    try:
        bs_df = f.balance_sheet(period="year")
        out["raw_data_available"]["balance_sheet"] = True
    except Exception as e:
        out["raw_data_available"]["balance_sheet"] = False
        out["raw_data_available"]["balance_sheet_err"] = str(e)[:200]
        bs_df = None

    # 3. Cash flow
    try:
        cf_df = f.cash_flow(period="year")
        out["raw_data_available"]["cash_flow"] = True
    except Exception as e:
        out["raw_data_available"]["cash_flow"] = False
        out["raw_data_available"]["cash_flow_err"] = str(e)[:200]
        cf_df = None

    if is_df is None and bs_df is None:
        out["fetch_error"] = "no_statements_available"
        return out

    # Determine year cols (use whichever statement available)
    ref_df = is_df if is_df is not None else bs_df
    years = _year_cols(ref_df)
    out["years_available"] = years
    out["n_years"] = len(years)

    # ---- Compute per-year metrics ----
    per_year: dict[str, dict] = {}

    ni_row = _find_row(is_df, ITEM_IDS["net_income"]) if is_df is not None else None
    eq_row = _find_row(bs_df, ITEM_IDS["equity"]) if bs_df is not None else None
    ta_row = _find_row(bs_df, ITEM_IDS["total_assets"]) if bs_df is not None else None
    tl_row = _find_row(bs_df, ITEM_IDS["total_liab"]) if bs_df is not None else None
    eps_row = _find_row(is_df, ITEM_IDS["eps"]) if is_df is not None else None
    rev_row = _find_row(is_df, ITEM_IDS["revenue"]) if is_df is not None else None
    re_row = _find_row(bs_df, ITEM_IDS["retained_earnings"]) if bs_df is not None else None
    sc_row = _find_row(bs_df, ITEM_IDS["share_capital"]) if bs_df is not None else None

    # OCF — fallback: take first cash_flow item if known IDs miss
    ocf_row = None
    if cf_df is not None:
        ocf_row = _find_row(cf_df, ITEM_IDS["ocf"])
        if ocf_row is None and len(cf_df) > 0:
            # Heuristic: row whose Vietnamese item name contains "hoạt động kinh doanh" + "thuần"
            mask = (
                cf_df["item"].astype(str).str.contains("hoạt động kinh doanh", na=False)
                & cf_df["item"].astype(str).str.contains("thuần|net", regex=True, na=False, case=False)
            )
            if mask.any():
                ocf_row = cf_df[mask].iloc[0]

    field_coverage = {"ni": ni_row is not None, "equity": eq_row is not None,
                      "total_assets": ta_row is not None, "total_liab": tl_row is not None,
                      "eps": eps_row is not None, "revenue": rev_row is not None,
                      "ocf": ocf_row is not None, "retained_earnings": re_row is not None}
    out["data_completeness"]["field_coverage"] = field_coverage
    out["data_completeness"]["pct"] = round(
        100.0 * sum(1 for v in field_coverage.values() if v) / len(field_coverage), 1
    )

    for y in years:
        py: dict = {}
        ni = _safe_float(ni_row[y]) if ni_row is not None else None
        eq = _safe_float(eq_row[y]) if eq_row is not None else None
        ta = _safe_float(ta_row[y]) if ta_row is not None else None
        tl = _safe_float(tl_row[y]) if tl_row is not None else None
        eps = _safe_float(eps_row[y]) if eps_row is not None else None
        rev = _safe_float(rev_row[y]) if rev_row is not None else None
        ocf = _safe_float(ocf_row[y]) if ocf_row is not None else None
        ret_e = _safe_float(re_row[y]) if re_row is not None else None
        sc = _safe_float(sc_row[y]) if sc_row is not None else None

        py["net_income"] = ni
        py["equity"] = eq
        py["total_assets"] = ta
        py["total_liab"] = tl
        py["eps"] = eps
        py["revenue"] = rev
        py["ocf"] = ocf
        py["retained_earnings"] = ret_e
        py["share_capital"] = sc

        py["roe_pct"] = round(ni / eq * 100, 3) if (ni is not None and eq is not None and eq > 0) else None
        py["roa_pct"] = round(ni / ta * 100, 3) if (ni is not None and ta is not None and ta > 0) else None
        py["de"] = round(tl / eq, 3) if (tl is not None and eq is not None and eq > 0) else None

        per_year[y] = py

    out["per_year"] = per_year

    # ---- Aggregate metrics (3y / 5y / 8y means) ----
    def _mean_last_n(key: str, n: int) -> float | None:
        vals = [per_year[y].get(key) for y in years[:n] if per_year[y].get(key) is not None]
        if len(vals) < n:
            return None
        return round(float(np.mean(vals)), 3)

    metrics = {}
    for k in ("roe_pct", "roa_pct", "de"):
        metrics[f"{k}_3y_avg"] = _mean_last_n(k, 3)
        metrics[f"{k}_5y_avg"] = _mean_last_n(k, 5)
        if len(years) >= 8:
            metrics[f"{k}_8y_avg"] = _mean_last_n(k, 8)

    # NI 3y CAGR
    ni_series = [per_year[y].get("net_income") for y in years]
    metrics["ni_3y_cagr_pct"] = (
        round(_cagr(ni_series, 3) * 100, 3) if _cagr(ni_series, 3) is not None else None
    )

    # Revenue 3y CAGR
    rev_series = [per_year[y].get("revenue") for y in years]
    metrics["revenue_3y_cagr_pct"] = (
        round(_cagr(rev_series, 3) * 100, 3) if _cagr(rev_series, 3) is not None else None
    )

    # OCF positive count last 3y and 5y
    ocf_series = [per_year[y].get("ocf") for y in years]
    metrics["ocf_positive_last_3y"] = sum(1 for v in ocf_series[:3] if v is not None and v > 0)
    metrics["ocf_positive_last_5y"] = sum(1 for v in ocf_series[:5] if v is not None and v > 0)
    metrics["ocf_data_count_last_3y"] = sum(1 for v in ocf_series[:3] if v is not None)
    metrics["ocf_data_count_last_5y"] = sum(1 for v in ocf_series[:5] if v is not None)

    # Net income negative streak (consecutive most recent)
    ni_streak = 0
    for v in ni_series:
        if v is not None and v < 0:
            ni_streak += 1
        else:
            break
    metrics["ni_negative_consecutive_recent"] = ni_streak

    # Share capital growth 3y (proxy: 3y change in nominal capital, often bonus shares in banks)
    sc_series = [per_year[y].get("share_capital") for y in years]
    if (len(sc_series) >= 4 and sc_series[0] is not None
            and sc_series[3] is not None and sc_series[3] > 0):
        metrics["share_capital_3y_growth_pct"] = round((sc_series[0] / sc_series[3] - 1) * 100, 2)
    else:
        metrics["share_capital_3y_growth_pct"] = None

    # EPS growth 3y (per-share earnings — true dilution proxy)
    eps_series = [per_year[y].get("eps") for y in years]
    if (len(eps_series) >= 4 and eps_series[0] is not None
            and eps_series[3] is not None and eps_series[3] != 0):
        metrics["eps_3y_growth_pct"] = round((eps_series[0] / eps_series[3] - 1) * 100, 2)
    else:
        metrics["eps_3y_growth_pct"] = None

    # BVPS proxy growth 3y: BVPS ~ equity / share_capital (unit-free, no par_value needed)
    # Bonus shares scale equity + share_capital together → BVPS_proxy stays flat → not dilution.
    # Real dilution (cash issuance with poor deployment) → equity grows slower than capital → BVPS drops.
    def _bvps_proxy(idx: int) -> float | None:
        eq = per_year[years[idx]].get("equity") if idx < len(years) else None
        sc = per_year[years[idx]].get("share_capital") if idx < len(years) else None
        if eq is None or sc is None or sc <= 0:
            return None
        return eq / sc

    bvps_now = _bvps_proxy(0)
    bvps_3y_ago = _bvps_proxy(3) if len(years) >= 4 else None
    if bvps_now is not None and bvps_3y_ago is not None and bvps_3y_ago > 0:
        metrics["bvps_proxy_3y_growth_pct"] = round((bvps_now / bvps_3y_ago - 1) * 100, 2)
    else:
        metrics["bvps_proxy_3y_growth_pct"] = None

    # ROE deterioration (3y avg vs 5y avg) — if 3y < 5y, ROE in decline
    if (metrics.get("roe_pct_3y_avg") is not None and
            metrics.get("roe_pct_5y_avg") is not None):
        metrics["roe_deteriorating"] = bool(metrics["roe_pct_3y_avg"] < metrics["roe_pct_5y_avg"])
    else:
        metrics["roe_deteriorating"] = None

    # Negative equity check
    latest_eq = per_year[years[0]].get("equity") if years else None
    metrics["latest_equity_negative"] = bool(latest_eq is not None and latest_eq < 0)

    out["metrics"] = metrics

    # ---- HARD red flags ----
    if metrics["ni_negative_consecutive_recent"] >= 3:
        out["hard_flags"].append({
            "id": "consecutive_loss_3y",
            "evidence": f"NI < 0 in {metrics['ni_negative_consecutive_recent']} consecutive recent years",
        })

    # ROE 3y avg negative — tiered
    roe_3y = metrics.get("roe_pct_3y_avg")
    if roe_3y is not None:
        if roe_3y < -5:
            out["hard_flags"].append({
                "id": "roe_3y_deeply_negative",
                "evidence": f"ROE 3y avg = {roe_3y}% < -5% (quality unrecoverable)",
            })
        elif roe_3y < 0:
            out["warning_flags"].append({
                "id": "roe_3y_negative",
                "severity": "high",
                "evidence": f"ROE 3y avg = {roe_3y}% (negative but > -5%; turnaround thesis required)",
            })
    if metrics["latest_equity_negative"]:
        out["hard_flags"].append({
            "id": "negative_equity",
            "evidence": f"Latest equity = {latest_eq}",
        })
    # Sector-specific dilution logic — banks/securities issue bonus shares routinely for CAR,
    # so capital growth alone is NOT toxic dilution. True dilution requires per-share metrics decline.
    sc_g = metrics["share_capital_3y_growth_pct"]
    eps_g = metrics["eps_3y_growth_pct"]
    bvps_g = metrics["bvps_proxy_3y_growth_pct"]
    roe_det = metrics.get("roe_deteriorating")
    rev_g = metrics.get("revenue_3y_cagr_pct")
    sector = out["sector"]

    if sc_g is not None:
        if sector == "banking":
            # Banking: exempt unless per-share metrics also deteriorate
            if sc_g > 250 and eps_g is not None and eps_g < 0 and bvps_g is not None and bvps_g <= 0:
                out["hard_flags"].append({
                    "id": "banking_real_dilution_severe",
                    "evidence": f"sc_3y={sc_g}%, eps_3y={eps_g}%, bvps_3y={bvps_g}%. Banks issue bonus shares for CAR — capital growth alone not toxic, but here EPS+BVPS both deteriorated.",
                })
            elif sc_g > 150 and (
                (eps_g is not None and eps_g < 0)
                or (bvps_g is not None and bvps_g <= 0)
                or roe_det is True
            ):
                out["warning_flags"].append({
                    "id": "banking_dilution_risk",
                    "severity": "medium",
                    "evidence": f"sc_3y={sc_g}%, eps_3y={eps_g}, bvps_3y={bvps_g}, roe_deteriorating={roe_det}. Banks routinely bonus-share but per-share metrics also declining.",
                })
            # else: pure bonus-share growth → no flag (correct for VCB/MBB/ACB/CTG/TCB)
        elif sector == "securities":
            # Securities: stricter than banking — actual cash issuance more common
            if sc_g > 200 and eps_g is not None and eps_g < 0 and roe_det is True:
                out["hard_flags"].append({
                    "id": "securities_real_dilution_severe",
                    "evidence": f"sc_3y={sc_g}%, eps_3y={eps_g}%, roe_deteriorating={roe_det}",
                })
            elif sc_g > 100:
                out["warning_flags"].append({
                    "id": "securities_dilution_risk",
                    "severity": "medium",
                    "evidence": f"sc_3y={sc_g}%. Securities often raise cash via SI — verify deployment quality.",
                })
        else:
            # Non-financial: existing logic strengthened with EPS/BVPS/revenue cross-check
            eps_decline = eps_g is not None and eps_g < 0
            bvps_decline = bvps_g is not None and bvps_g <= 0
            rev_decline = rev_g is not None and rev_g < 0
            per_share_problem = eps_decline or bvps_decline

            if sc_g > 100 and per_share_problem:
                out["hard_flags"].append({
                    "id": "severe_dilution",
                    "evidence": f"sc_3y={sc_g}%, eps_3y={eps_g}, bvps_3y={bvps_g}. Capital doubled with per-share metrics declining.",
                })
            elif sc_g > 100 and rev_decline:
                out["hard_flags"].append({
                    "id": "severe_dilution",
                    "evidence": f"sc_3y={sc_g}%, revenue_3y_cagr={rev_g}%. Capital doubled but revenue declining.",
                })
            elif sc_g > 50 and per_share_problem:
                out["warning_flags"].append({
                    "id": "dilution_with_decay",
                    "severity": "high",
                    "evidence": f"sc_3y={sc_g}%, eps_3y={eps_g}, bvps_3y={bvps_g}",
                })
            elif sc_g > 100:
                # Capital doubled but per-share OK → still note as informational
                out["warning_flags"].append({
                    "id": "dilution_moderate",
                    "severity": "medium",
                    "evidence": f"sc_3y={sc_g}%, eps_3y={eps_g} (per-share OK so far)",
                })
            elif sc_g > 30 and per_share_problem:
                out["warning_flags"].append({
                    "id": "dilution_moderate",
                    "severity": "medium",
                    "evidence": f"sc_3y={sc_g}% with eps/bvps decay",
                })
            # else: sc_g ≤ 30% or sc_g 30-100% with per-share growth fine → no flag
    if (re_row is not None and sc_row is not None and years
            and per_year[years[0]].get("retained_earnings") is not None
            and per_year[years[0]].get("share_capital") is not None):
        rs = per_year[years[0]]["retained_earnings"]
        sc_v = per_year[years[0]]["share_capital"]
        if rs < 0 and abs(rs) > sc_v:
            out["hard_flags"].append({
                "id": "accumulated_loss_exceeds_capital",
                "evidence": f"retained_earnings={rs:.0f}, share_capital={sc_v:.0f}",
            })

    # ---- WARNING flags ----
    if metrics["ocf_data_count_last_3y"] >= 2 and metrics["ocf_positive_last_3y"] <= 1:
        out["warning_flags"].append({
            "id": "ocf_negative_2of3y",
            "severity": "high",
            "evidence": f"OCF positive only {metrics['ocf_positive_last_3y']}/{metrics['ocf_data_count_last_3y']} recent 3y",
        })
    elif metrics["ocf_data_count_last_3y"] >= 1 and ocf_series and ocf_series[0] is not None and ocf_series[0] < 0:
        out["warning_flags"].append({
            "id": "ocf_negative_1y",
            "severity": "medium",
            "evidence": f"Latest OCF = {ocf_series[0]:.0f}",
        })

    # D/E elevated — non-bank only (generic limits)
    if sector not in BANK_SECTORS:
        latest_de = per_year[years[0]].get("de") if years else None
        if latest_de is not None and latest_de > 5.0:
            out["warning_flags"].append({
                "id": "debt_extreme",
                "severity": "high",
                "evidence": f"D/E = {latest_de}",
            })
        elif latest_de is not None and latest_de > 3.0:
            out["warning_flags"].append({
                "id": "debt_elevated",
                "severity": "medium",
                "evidence": f"D/E = {latest_de}",
            })

    # Sector-specific ROE threshold (Layer 1 Tầng B, calibrated)
    sec_thr = SECTOR_ROE_THRESHOLDS.get(sector)
    if sec_thr:
        roe_val = metrics.get(sec_thr["metric"])
        if roe_val is not None and roe_val < sec_thr["min"]:
            severity = "high" if roe_val < sec_thr["min"] - 5 else "medium"
            out["warning_flags"].append({
                "id": "below_sector_roe_threshold",
                "severity": severity,
                "evidence": f"{sec_thr['metric']}={roe_val}% < sector {sector} min {sec_thr['min']}%",
            })

    # Sector-specific D/E ceiling (non-bank/securities) — only flag if not already
    if sector in SECTOR_DE_CEILING:
        de_latest = per_year[years[0]].get("de") if years else None
        ceiling = SECTOR_DE_CEILING[sector]
        if de_latest is not None and de_latest > ceiling:
            severity = "high" if de_latest > ceiling * 1.5 else "medium"
            existing_debt = any(f["id"].startswith("debt_") for f in out["warning_flags"])
            if not existing_debt:
                out["warning_flags"].append({
                    "id": "above_sector_de_ceiling",
                    "severity": severity,
                    "evidence": f"D/E={de_latest} > sector {sector} ceiling {ceiling}",
                })

    return out


def fetch_all(tickers: list[str]) -> dict:
    """Fetch all tickers, return dict by ticker."""
    results: dict[str, dict] = {}
    for sym in tickers:
        print(f"[fetch] {sym} ...", end=" ", flush=True)
        try:
            r = fetch_ticker(sym)
            results[sym] = r
            # Cache per-ticker
            path = DATA_DIR / f"{sym}.json"
            path.write_text(json.dumps(r, indent=2, ensure_ascii=False, default=str),
                            encoding="utf-8")
            n_hard = len(r.get("hard_flags", []))
            n_warn = len(r.get("warning_flags", []))
            print(f"ok (hard_flags={n_hard}, warning={n_warn}, dq={r.get('data_completeness',{}).get('pct','—')}%)")
        except Exception as e:
            print(f"FAILED: {e}")
            results[sym] = {"symbol": sym, "error": str(e)[:300]}
    return results


def render_distribution(results: dict) -> str:
    """Render sector-level distribution + per-ticker table."""
    L = ["# Fundamentals Distribution — Sector verification", ""]
    L.append(f"- Generated: `{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}`")
    L.append(f"- Tickers: {len(results)}")
    L.append("")

    # Per-ticker table
    L.append("## Per-ticker summary")
    L.append("")
    L.append("| Ticker | Sector | n_years | DQ% | ROE3y | ROE5y | D/E latest | NI CAGR 3y | OCF+ 3y | Hard flags | Warning flags |")
    L.append("|---|---|---|---|---|---|---|---|---|---|---|")
    for sym, r in results.items():
        if "error" in r:
            L.append(f"| {sym} | _err: {r['error'][:50]}_ | — | — | — | — | — | — | — | — | — |")
            continue
        m = r.get("metrics", {})
        sector = r.get("sector", "?")
        n_y = r.get("n_years", 0)
        dq = r.get("data_completeness", {}).get("pct", "—")
        roe3 = m.get("roe_pct_3y_avg", "—")
        roe5 = m.get("roe_pct_5y_avg", "—")
        # latest D/E from per_year
        py = r.get("per_year", {})
        if py:
            latest_y = sorted(py.keys(), reverse=True)[0]
            de_latest = py[latest_y].get("de", "—")
        else:
            de_latest = "—"
        ni_cagr = m.get("ni_3y_cagr_pct", "—")
        ocf3 = f"{m.get('ocf_positive_last_3y','?')}/{m.get('ocf_data_count_last_3y','?')}"
        hf = ", ".join(f["id"] for f in r.get("hard_flags", [])) or "—"
        wf = ", ".join(f["id"] for f in r.get("warning_flags", [])) or "—"
        L.append(f"| {sym} | {sector} | {n_y} | {dq} | {roe3} | {roe5} | {de_latest} | {ni_cagr} | {ocf3} | {hf} | {wf} |")
    L.append("")

    # Sector distribution stats
    L.append("## Sector distribution (compute from successful fetches)")
    L.append("")

    rows_by_sector: dict[str, list[dict]] = {}
    for sym, r in results.items():
        if "error" in r:
            continue
        rows_by_sector.setdefault(r["sector"], []).append(r)

    def _stats(values: list[float]) -> dict:
        v = [x for x in values if x is not None]
        if not v:
            return {"n": 0}
        arr = np.array(v)
        return {
            "n": len(arr),
            "min": round(float(arr.min()), 3),
            "p25": round(float(np.percentile(arr, 25)), 3),
            "median": round(float(np.median(arr)), 3),
            "p75": round(float(np.percentile(arr, 75)), 3),
            "max": round(float(arr.max()), 3),
            "mean": round(float(arr.mean()), 3),
        }

    for sector, rs in rows_by_sector.items():
        L.append(f"### {sector} (n={len(rs)} tickers)")
        L.append("")
        L.append("| Metric | n | min | P25 | median | P75 | max | mean |")
        L.append("|---|---|---|---|---|---|---|---|")
        for metric_name in ("roe_pct_3y_avg", "roe_pct_5y_avg", "roa_pct_3y_avg",
                              "de", "ni_3y_cagr_pct", "revenue_3y_cagr_pct"):
            if metric_name == "de":
                values = []
                for r in rs:
                    py = r.get("per_year", {})
                    if py:
                        latest_y = sorted(py.keys(), reverse=True)[0]
                        values.append(py[latest_y].get("de"))
            else:
                values = [r.get("metrics", {}).get(metric_name) for r in rs]
            s = _stats(values)
            if s["n"] == 0:
                L.append(f"| {metric_name} | 0 | — | — | — | — | — | — |")
                continue
            L.append(f"| {metric_name} | {s['n']} | {s['min']} | {s['p25']} | "
                     f"{s['median']} | {s['p75']} | {s['max']} | {s['mean']} |")
        L.append("")

    # Hard flag summary
    L.append("## Hard red flag occurrences")
    L.append("")
    flagged = [(sym, r) for sym, r in results.items()
                if "error" not in r and r.get("hard_flags")]
    if not flagged:
        L.append("_None_")
    else:
        for sym, r in flagged:
            L.append(f"- **{sym}** ({r['sector']}): "
                     + ", ".join(f"{f['id']} ({f['evidence']})" for f in r["hard_flags"]))
    L.append("")

    L.append("## Warning flag occurrences")
    L.append("")
    warned = [(sym, r) for sym, r in results.items()
                if "error" not in r and r.get("warning_flags")]
    if not warned:
        L.append("_None_")
    else:
        for sym, r in warned:
            L.append(f"- **{sym}** ({r['sector']}): "
                     + "; ".join(f"{f['id']} [{f.get('severity','?')}] ({f['evidence']})"
                                 for f in r["warning_flags"]))
    L.append("")

    return "\n".join(L) + "\n"


def main() -> int:
    p = argparse.ArgumentParser(description="Fetch fundamentals + verify quality gate thresholds.")
    default_tickers = list(SECTOR_MAP.keys())
    p.add_argument("--tickers", nargs="+", default=default_tickers,
                   help="Tickers to fetch. Default: built-in 32-ticker watchlist.")
    args = p.parse_args()

    print(f"[fetch_fundamentals] fetching {len(args.tickers)} tickers")
    results = fetch_all(args.tickers)

    report = render_distribution(results)
    report_path = REPORTS_DIR / "fundamentals_distribution.md"
    report_path.write_text(report, encoding="utf-8")
    print(f"[fetch_fundamentals] wrote {report_path}")

    summary = {
        "fetched_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "n_tickers": len(args.tickers),
        "n_success": sum(1 for r in results.values() if "error" not in r),
        "n_with_hard_flag": sum(1 for r in results.values()
                                  if "error" not in r and r.get("hard_flags")),
        "tickers": list(results.keys()),
    }
    (REPORTS_DIR / "fundamentals_summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
