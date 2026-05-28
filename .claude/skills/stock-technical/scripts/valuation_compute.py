"""Layer 6A — Valuation Compute (sector-specific primary).

Phase 1 scope: primary auto methods for 6 sectors. RE primary requires
RNAV (manual) — return `pending_manual`. EV/EBITDA secondary deferred
(needs D&A + cash parsing — Phase 3).

Per L6 spec (configs/valuation_technical_spec.md):
  Banking      — Justified P/B = (ROE - g) / (CoE - g);  pass if actual < 0.85×just
  Oil & Gas    — P/E normalised (5y avg EPS);            pass if P/E_norm < 10
  Real Estate  — P/RNAV manual                            pending_manual
  Steel        — P/E normalised + cycle position         P/E_norm < 10 + cycle proxy
  Consumer     — P/E vs 5y mean basket + PEG             P/E < mean - 0.5σ AND PEG < 1.5
  Tech         — PEG only (DCF deferred)                 PEG < 1.5
  Securities   — P/B vs 5y mean basket                    P/B < mean - 0.5σ

Inputs:
  - data/fundamentals/{TICKER}.json (per_year EPS, equity, share_capital)
  - data/liquidity/{TICKER}.json (latest_close, shares_outstanding)
  - configs/watchlist.yaml (sector baskets — for basket means)

Output: data/valuation/{TICKER}.json
"""
from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
from datetime import date
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
CONFIGS = ROOT / "configs"


# Justified P/B heuristic defaults (per L6 spec)
JUSTIFIED_PB_DEFAULTS = {
    "banking": {"g_pct": 4.0, "coe_pct": 11.0},
}


def _load_json(p: Path) -> dict | None:
    return json.loads(p.read_text()) if p.exists() else None


def _eps_avg(per_year: dict, years: list[str], n: int) -> float | None:
    """Average EPS of last n years. None if any missing/non-positive."""
    if len(years) < n:
        return None
    vals = []
    for y in years[:n]:
        e = per_year.get(y, {}).get("eps")
        if e is None or e <= 0:
            return None
        vals.append(e)
    return sum(vals) / len(vals)


def _bvps(per_year: dict, latest_year: str) -> float | None:
    """BVPS proxy = equity_vnd / shares_outstanding.

    shares_outstanding ≈ share_capital_vnd / 10_000 (VN par).
    Result = equity * 10_000 / share_capital  (VND/share).
    """
    y = per_year.get(latest_year, {})
    equity = y.get("equity")
    sc = y.get("share_capital")
    if not equity or not sc or sc <= 0:
        return None
    return equity * 10_000 / sc


def _pe_ratio(price: float, eps: float | None) -> float | None:
    if eps is None or eps <= 0:
        return None
    return price / eps


def _pb_ratio(price: float, bvps: float | None) -> float | None:
    if bvps is None or bvps <= 0:
        return None
    return price / bvps


def _peg(pe: float | None, ni_cagr_pct: float | None) -> float | None:
    if pe is None or not ni_cagr_pct or ni_cagr_pct <= 0:
        return None
    return pe / ni_cagr_pct


def _basket_mean_std(values: list[float]) -> tuple[float, float] | None:
    clean = [v for v in values if v is not None and not math.isnan(v) and v > 0]
    if len(clean) < 3:
        return None
    return statistics.mean(clean), statistics.pstdev(clean)


def _compute_basket_pe(basket: list[str], current_ticker: str) -> tuple[float, float] | None:
    pes = []
    for t in basket:
        if t == current_ticker:
            continue
        fund = _load_json(DATA / "fundamentals" / f"{t}.json")
        liq = _load_json(DATA / "liquidity" / f"{t}.json")
        if not fund or not liq:
            continue
        years = sorted(fund.get("per_year", {}).keys(), reverse=True)
        if not years:
            continue
        eps = fund["per_year"][years[0]].get("eps")
        price = liq.get("latest_close_vnd")
        pe = _pe_ratio(price, eps)
        if pe is not None and 0 < pe < 100:  # filter outliers
            pes.append(pe)
    return _basket_mean_std(pes)


def _compute_basket_pb(basket: list[str], current_ticker: str) -> tuple[float, float] | None:
    pbs = []
    for t in basket:
        if t == current_ticker:
            continue
        fund = _load_json(DATA / "fundamentals" / f"{t}.json")
        liq = _load_json(DATA / "liquidity" / f"{t}.json")
        if not fund or not liq:
            continue
        years = sorted(fund.get("per_year", {}).keys(), reverse=True)
        if not years:
            continue
        bvps = _bvps(fund["per_year"], years[0])
        pb = _pb_ratio(liq.get("latest_close_vnd"), bvps)
        if pb is not None and 0 < pb < 20:
            pbs.append(pb)
    return _basket_mean_std(pbs)


def _verdict_pass(actual: float, threshold: float, direction: str = "below") -> bool:
    if direction == "below":
        return actual < threshold
    return actual > threshold


def value_banking(ticker: str, fund: dict, liq: dict, basket: list[str]) -> dict:
    metrics = fund.get("metrics", {})
    roe = metrics.get("roe_pct_3y_avg")
    years = sorted(fund.get("per_year", {}).keys(), reverse=True)
    if not years or roe is None:
        return {"method": "justified_pb", "pass": False, "reason": "missing_inputs"}
    bvps = _bvps(fund["per_year"], years[0])
    price = liq.get("latest_close_vnd")
    pb_actual = _pb_ratio(price, bvps)

    g = JUSTIFIED_PB_DEFAULTS["banking"]["g_pct"]
    coe = JUSTIFIED_PB_DEFAULTS["banking"]["coe_pct"]
    if coe <= g:
        return {"method": "justified_pb", "pass": False, "reason": "coe<=g"}
    just_pb = (roe - g) / (coe - g)
    threshold = just_pb * 0.85
    if pb_actual is None:
        return {"method": "justified_pb", "pass": False, "reason": "no_pb"}
    discount_pct = (just_pb - pb_actual) / just_pb * 100
    return {
        "method": "justified_pb",
        "inputs": {"roe_pct_3y_avg": roe, "g_pct": g, "coe_pct": coe},
        "actual_pb": round(pb_actual, 3),
        "justified_pb": round(just_pb, 3),
        "threshold_pb": round(threshold, 3),
        "discount_vs_justified_pct": round(discount_pct, 2),
        "pass": pb_actual < threshold,
    }


def value_oilgas_or_steel(ticker: str, fund: dict, liq: dict, threshold_pe: float = 10.0) -> dict:
    """P/E normalised on 5y avg EPS."""
    years = sorted(fund.get("per_year", {}).keys(), reverse=True)
    eps_5y_avg = _eps_avg(fund.get("per_year", {}), years, n=5)
    if eps_5y_avg is None:
        return {"method": "pe_normalised_5y", "pass": False, "reason": "missing_eps_5y_or_negative"}
    price = liq.get("latest_close_vnd")
    pe_norm = _pe_ratio(price, eps_5y_avg)
    if pe_norm is None:
        return {"method": "pe_normalised_5y", "pass": False, "reason": "no_pe"}
    return {
        "method": "pe_normalised_5y",
        "eps_5y_avg_vnd": round(eps_5y_avg, 2),
        "price_vnd": price,
        "pe_norm": round(pe_norm, 2),
        "threshold_pe": threshold_pe,
        "pass": pe_norm < threshold_pe,
    }


def value_consumer(ticker: str, fund: dict, liq: dict, basket: list[str]) -> dict:
    years = sorted(fund.get("per_year", {}).keys(), reverse=True)
    eps_latest = fund.get("per_year", {}).get(years[0], {}).get("eps") if years else None
    price = liq.get("latest_close_vnd")
    pe = _pe_ratio(price, eps_latest)
    ni_cagr = fund.get("metrics", {}).get("ni_3y_cagr_pct")
    peg = _peg(pe, ni_cagr)
    basket_pe = _compute_basket_pe(basket, ticker)
    if basket_pe is None or pe is None:
        return {"method": "pe_vs_basket_5y_mean_+_peg", "pass": False, "reason": "missing_inputs"}
    mean_pe, std_pe = basket_pe
    threshold = mean_pe - 0.5 * std_pe
    pe_pass = pe < threshold
    peg_pass = peg is not None and peg < 1.5
    return {
        "method": "pe_vs_basket_+_peg",
        "pe_actual": round(pe, 2),
        "basket_pe_mean": round(mean_pe, 2),
        "basket_pe_std": round(std_pe, 2),
        "threshold_pe": round(threshold, 2),
        "pe_pass": pe_pass,
        "peg": round(peg, 3) if peg else None,
        "peg_threshold": 1.5,
        "peg_pass": peg_pass,
        "pass": pe_pass and peg_pass,
        "sample_size_caveat": f"basket n={len(basket)-1}",
    }


def value_tech(ticker: str, fund: dict, liq: dict) -> dict:
    years = sorted(fund.get("per_year", {}).keys(), reverse=True)
    eps_latest = fund.get("per_year", {}).get(years[0], {}).get("eps") if years else None
    price = liq.get("latest_close_vnd")
    pe = _pe_ratio(price, eps_latest)
    ni_cagr = fund.get("metrics", {}).get("ni_3y_cagr_pct")
    peg = _peg(pe, ni_cagr)
    if pe is None or peg is None:
        return {"method": "peg", "pass": False, "reason": "missing_pe_or_growth"}
    return {
        "method": "peg",
        "pe_actual": round(pe, 2),
        "ni_3y_cagr_pct": ni_cagr,
        "peg": round(peg, 3),
        "threshold_peg": 1.5,
        "pass": peg < 1.5,
        "note": "dcf_deferred_to_phase_3",
    }


def value_securities(ticker: str, fund: dict, liq: dict, basket: list[str]) -> dict:
    years = sorted(fund.get("per_year", {}).keys(), reverse=True)
    bvps = _bvps(fund["per_year"], years[0]) if years else None
    price = liq.get("latest_close_vnd")
    pb = _pb_ratio(price, bvps)
    basket_pb = _compute_basket_pb(basket, ticker)
    if pb is None or basket_pb is None:
        return {"method": "pb_vs_basket_5y_mean", "pass": False, "reason": "missing_inputs"}
    mean_pb, std_pb = basket_pb
    threshold = mean_pb - 0.5 * std_pb
    return {
        "method": "pb_vs_basket",
        "pb_actual": round(pb, 3),
        "basket_pb_mean": round(mean_pb, 3),
        "basket_pb_std": round(std_pb, 3),
        "threshold_pb": round(threshold, 3),
        "pass": pb < threshold,
        "sample_size_caveat": f"basket n={len(basket)-1}",
    }


def value_real_estate(ticker: str) -> dict:
    return {
        "method": "p_rnav",
        "pass": False,
        "status": "pending_manual",
        "reason": "P/RNAV requires manual CTCK input — configs/re_rnav_manual.yaml not built",
    }


def compute_for_ticker(ticker: str, sector: str, basket: list[str]) -> dict:
    fund = _load_json(DATA / "fundamentals" / f"{ticker}.json")
    liq = _load_json(DATA / "liquidity" / f"{ticker}.json")
    if fund is None or liq is None:
        return {"ticker": ticker, "sector": sector, "error": "fundamentals_or_liquidity_missing"}

    if sector == "banking":
        primary = value_banking(ticker, fund, liq, basket)
    elif sector == "oil_gas":
        primary = value_oilgas_or_steel(ticker, fund, liq, threshold_pe=10.0)
    elif sector == "steel":
        primary = value_oilgas_or_steel(ticker, fund, liq, threshold_pe=10.0)
        primary["cycle_position_note"] = "requires_iron_ore_percentile_phase_3"
    elif sector == "consumer":
        primary = value_consumer(ticker, fund, liq, basket)
    elif sector == "tech":
        primary = value_tech(ticker, fund, liq)
    elif sector == "securities":
        primary = value_securities(ticker, fund, liq, basket)
    elif sector == "real_estate":
        primary = value_real_estate(ticker)
    else:
        primary = {"method": "unknown_sector", "pass": False, "reason": f"sector={sector}"}

    return {
        "ticker": ticker,
        "as_of": date.today().isoformat(),
        "sector": sector,
        "primary": primary,
        "secondary": {"method": "ev_ebitda", "status": "deferred_phase_3",
                      "reason": "needs D&A + cash parsing"},
        "valuation_pass": primary.get("pass", False),
    }


def main() -> int:
    p = argparse.ArgumentParser(description="Layer 6A Valuation Compute.")
    p.add_argument("--tickers", nargs="+")
    args = p.parse_args()

    wl = yaml.safe_load((CONFIGS / "watchlist.yaml").read_text())
    sector_baskets = wl["sector_baskets"]
    tk_sec = {t: sec for sec, ts in sector_baskets.items() for t in ts}
    tickers = args.tickers or wl.get("all_fetched", [])

    out_dir = DATA / "valuation"
    out_dir.mkdir(parents=True, exist_ok=True)

    rows = []
    for t in tickers:
        sec = tk_sec.get(t, "unknown")
        basket = sector_baskets.get(sec, [])
        r = compute_for_ticker(t, sec, basket)
        (out_dir / f"{t}.json").write_text(json.dumps(r, ensure_ascii=False, indent=2))
        p = r.get("primary", {})
        method = p.get("method", "-")
        passed = "✓" if r.get("valuation_pass") else "-"
        rationale = p.get("reason") or (
            f"PE={p.get('pe_norm') or p.get('pe_actual')}, thr={p.get('threshold_pe') or p.get('threshold_pb')}"
            if method != "p_rnav" else "pending_manual"
        )
        rows.append((t, sec, method, passed, rationale))

    print(f"[valuation] {len(tickers)} tickers processed → {out_dir}\n")
    print(f"  {'TICKER':8s} {'SECTOR':14s} {'METHOD':22s} PASS  RATIONALE")
    for row in sorted(rows, key=lambda x: (x[1], x[0])):
        print(f"  {row[0]:8s} {row[1]:14s} {row[2]:22s} {row[3]:4s}  {row[4]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
