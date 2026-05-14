#!/usr/bin/env python3
"""
Aggregate existing sub-skill reports for a ticker into compact JSON.
Modes:
  --mode check   → detect which reports exist, output paths JSON
  --mode extract → extract key metrics from each report, output compact JSON
"""
import argparse
import glob
import json
import os
import re
import sys
from datetime import datetime

WORKSPACE = os.path.expanduser("~/.claude/workspace/stock-analysis")
OUTPUT_DIR = os.path.join(WORKSPACE, "output")

REPORT_PATTERNS = {
    "macro":      ["macro_report_*.md"],
    "industry":   ["industry_report_{ticker}_*.md", "industry_report_*.md"],
    "business":   ["business_report_{ticker}_*.md"],
    "financials": ["financial_report_{ticker}_*.md"],
    "valuation":  ["valuation_report_{ticker}_*.md"],
    "technical":  ["technical_report_{ticker}_*.md"],
    "risk":       ["risk_report_{ticker}_*.md"],
}

FUNDAMENTAL_KEYS = ["macro", "industry", "business", "financials", "risk", "technical"]
VALUATION_KEYS   = ["macro", "industry", "business", "financials", "risk", "technical", "valuation"]

CONTRADICTION_THRESHOLDS = {
    "growth_ratio_max":   2.0,   # valuation growth > actual CAGR × 2 → flag
    "margin_diff_max_pp": 20.0,  # absolute margin diff > 20pp → flag
    "wacc_high_risk_min": 12.0,  # if risk=HIGH and WACC < this → flag
}

def find_latest(patterns: list[str], ticker: str) -> str | None:
    candidates = []
    for pat in patterns:
        pat_expanded = pat.replace("{ticker}", ticker)
        matches = glob.glob(os.path.join(OUTPUT_DIR, pat_expanded))
        candidates.extend(matches)
    if not candidates:
        return None
    return max(candidates, key=os.path.getmtime)


def check_mode(ticker: str) -> dict:
    found, missing, paths = [], [], {}
    for key, patterns in REPORT_PATTERNS.items():
        path = find_latest(patterns, ticker)
        if path:
            found.append(key)
            paths[key] = os.path.relpath(path, WORKSPACE)
        else:
            missing.append(key)
    return {"ticker": ticker, "found": found, "missing": missing, "report_paths": paths}


# --- Extractor helpers ---

def _grep(text: str, pattern: str, default="[missing_data]") -> str:
    m = re.search(pattern, text, re.IGNORECASE | re.MULTILINE)
    return m.group(1).strip() if m else default


def extract_macro(text: str) -> dict:
    verdict = _grep(text, r"Verdict:\s*(?:🟢|🔴|🟡)?\s*(BULLISH|NEUTRAL|BEARISH|Bullish|Neutral|Bearish)")
    dxy     = _grep(text, r"DXY\s*\|\s*[\d,.]+\s*\|\s*(?:🟢|🔴|🟡)?\s*(\w+)")
    fed     = _grep(text, r"Fed Rate\s*\|\s*([\d.]+%)")
    vn_gdp  = _grep(text, r"GDP Growth VN\s*\|\s*([\d.]+%)")
    vn_idx  = _grep(text, r"VN-Index\s*\|\s*([\d,]+)")
    return {
        "verdict": verdict,
        "key_points": [
            f"Fed Rate: {fed}",
            f"DXY trend: {dxy}",
            f"GDP VN: {vn_gdp} | VN-Index: {vn_idx}",
        ],
        "data_source": "macro_report",
    }


def extract_industry(text: str) -> dict:
    cycle   = _grep(text, r"Chu kỳ Ngành[:\s]*(?:🟠|🟢|🔴|🟡)?\s*([^\n]+)")
    growth  = _grep(text, r"Revenue Growth.*?\|\s*([-+]?\d+\.?\d*%)")
    gm      = _grep(text, r"Gross Margin.*?\|\s*([-+]?\d+\.?\d*%)")
    rel1y   = _grep(text, r"1 năm\s*\|[^|]+\|[^|]+\|\s*([-+]?\d+\.?\d*%)")
    verdict_map = {
        "hồi phục": "Tăng trưởng",
        "tăng trưởng": "Tăng trưởng",
        "đỉnh": "Bão hòa",
        "suy thoái": "Suy thoái",
        "đáy": "Phục hồi",
    }
    verdict = "[missing_data]"
    for k, v in verdict_map.items():
        if k in cycle.lower():
            verdict = v
            break
    return {
        "verdict": verdict,
        "key_points": [
            f"Chu kỳ: {cycle.strip()}",
            f"Revenue growth: {growth} | Gross margin: {gm}",
            f"Relative vs VN-Index 1Y: {rel1y}",
        ],
        "data_source": "industry_report",
    }


def extract_business(text: str) -> dict:
    score_full = _grep(text, r"\*\*\s*([\d.]+/10\s*—\s*[^\*\n]+)\*\*")
    score_alt  = _grep(text, r"([\d.]+/10\s*—\s*[^\n]+)")
    score      = score_full if score_full != "[missing_data]" else score_alt
    roe        = _grep(text, r"ROE[^\|]*\|\s*([-+]?\d+\.?\d*%[^|\n]*)")
    de         = _grep(text, r"D/E.*?\|\s*([\d.]+x)")
    pe         = _grep(text, r"P/E.*?\|\s*([\d.]+x)")
    score_val  = _grep(text, r"([\d.]+)/10")
    try:
        sv = float(score_val)
        if sv >= 7: verdict = "Cao"
        elif sv >= 5: verdict = "Trung bình"
        else: verdict = "Thấp"
    except ValueError:
        verdict = "[missing_data]"
    return {
        "verdict": verdict,
        "key_points": [
            f"Điểm chất lượng: {score}",
            f"ROE: {roe} | D/E: {de}",
            f"P/E: {pe}",
        ],
        "data_source": "business_report",
    }


def extract_financials(text: str) -> dict:
    score    = _grep(text, r"Điểm[:\s]+([\d.]+/10[^\n]*)")
    roe      = _grep(text, r"ROE[:\s]+([\d.]+%)")
    de       = _grep(text, r"D/E[:\s]+([\d.]+×?)")
    ocf_ni   = _grep(text, r"OCF/NI[:\s]+([\d.]+)")
    flags    = _grep(text, r"red_flags.*?\[CONCLUSION\][^\n]*\n([^\n]+)", "[missing_data]")
    verdict  = _grep(text, r"Sức khỏe tài chính\s*=\s*\[([^\]]+)\]",
                     _grep(text, r"## financial_score.*?band[:\s]+([^\n|]+)"))
    return {
        "verdict": verdict,
        "key_points": [
            f"Điểm tài chính: {score} | ROE: {roe}",
            f"D/E: {de} | OCF/NI: {ocf_ni}",
            f"Red flags: {flags}",
        ],
        "data_source": "financial_report",
    }


def extract_valuation(text: str) -> dict:
    fair_low  = _grep(text, r"Fair value.*?(\d[\d,]+)\s*[–-]\s*(\d[\d,]+)")
    current   = _grep(text, r"Giá hiện tại[:\s]+([\d,]+)")
    upside    = _grep(text, r"[Uu]pside.*?([-+]?\d+\.?\d*%)")
    pe        = _grep(text, r"P/E.*?([\d.]+)×")
    base_case = _grep(text, r"[Bb]ase case.*?([\d,]+)\s*VND")
    verdict   = _grep(text, r"Định giá\s*=\s*\[([^\]]+)\]")
    fair_range = _grep(text, r"[Ff]air value.*?(\d[\d,]+\s*[–-]\s*\d[\d,]+)")
    return {
        "verdict": verdict,
        "key_points": [
            f"Giá hiện tại: {current} | Fair value: {fair_range}",
            f"P/E: {pe}× | Upside: {upside}",
            f"Base case: {base_case}",
        ],
        "data_source": "valuation_report",
    }


def extract_technical(text: str) -> dict:
    trend   = _grep(text, r"Trend[:\s]+([^\n|]+)")
    rsi     = _grep(text, r"RSI[:\s]+([\d.]+)")
    support = _grep(text, r"Hỗ trợ[:\s]+([\d,]+)")
    resist  = _grep(text, r"Kháng cự[:\s]+([\d,]+)")
    verdict = _grep(text, r"Kỹ thuật\s*=\s*\[([^\]]+)\]",
                    _grep(text, r"##\s*technical.*?\[CONCLUSION\][^\n]*\n([^\n]+)"))
    return {
        "verdict": verdict,
        "key_points": [
            f"Trend: {trend} | RSI: {rsi}",
            f"Hỗ trợ: {support} | Kháng cự: {resist}",
        ],
        "data_source": "technical_report",
    }


def extract_risk(text: str) -> dict:
    overall     = _grep(text, r"Mức độ rủi ro tổng thể[:\s]+\[([^\]]+)\]")
    breakers    = _grep(text, r"thesis_breakers.*?\[CONCLUSION\][^\n]*\n([^\n]+)", "[missing_data]")
    top_risks   = re.findall(r"\|\s*([A-Za-z_]+)\s*\|\s*(HIGH|MEDIUM|LOW)\s*\|\s*(HIGH|MEDIUM|LOW)", text)
    top3 = [f"{r[0]}: severity={r[1]}, prob={r[2]}" for r in top_risks[:3]]
    return {
        "verdict": overall,
        "key_points": top3 if top3 else ["[missing_data]"],
        "thesis_breakers": breakers,
        "data_source": "risk_report",
    }


EXTRACTORS = {
    "macro":      extract_macro,
    "industry":   extract_industry,
    "business":   extract_business,
    "financials": extract_financials,
    "valuation":  extract_valuation,
    "technical":  extract_technical,
    "risk":       extract_risk,
}


def extract_mode(ticker: str) -> dict:
    check = check_mode(ticker)
    result = {
        "ticker": ticker,
        "date": datetime.now().strftime("%Y-%m-%d"),
        "found": check["found"],
        "missing": check["missing"],
        "analyses": {},
    }

    for key in REPORT_PATTERNS:
        rel_path = check["report_paths"].get(key)
        if not rel_path:
            result["analyses"][key] = {"verdict": "[missing_data]", "key_points": [], "data_source": "none"}
            continue
        full_path = os.path.join(WORKSPACE, rel_path)
        try:
            with open(full_path, "r", encoding="utf-8") as f:
                text = f.read()
            result["analyses"][key] = EXTRACTORS[key](text)
            result["analyses"][key]["report_file"] = rel_path
        except Exception as e:
            result["analyses"][key] = {"verdict": "[missing_data]", "key_points": [str(e)], "data_source": "error"}

    return result


def summarize_mode(ticker: str, stage: str) -> dict:
    keys = FUNDAMENTAL_KEYS if stage == "fundamental" else VALUATION_KEYS
    full = extract_mode(ticker)
    date_str = datetime.now().strftime("%Y-%m-%d")

    summary = {
        "ticker":   ticker,
        "date":     date_str,
        "stage":    stage,
        "found":    [k for k in full.get("found", []) if k in keys],
        "missing":  [k for k in keys if k not in full.get("found", [])],
        "analyses": {k: full["analyses"].get(k, {"verdict": "[missing_data]", "key_points": []})
                     for k in keys},
    }

    out_path = os.path.join(OUTPUT_DIR, f"{stage}_summary_{ticker}_{date_str}.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    print("---SUMMARY_PATH---")
    print(out_path)
    return summary


def _extract_number(text: str, pattern: str) -> float | None:
    m = re.search(pattern, text, re.IGNORECASE | re.DOTALL)
    if m:
        try:
            return float(m.group(1).replace(",", ""))
        except ValueError:
            pass
    return None


def contradictions_mode(ticker: str) -> list:
    check = check_mode(ticker)
    contradictions = []
    date_str = datetime.now().strftime("%Y-%m-%d")

    def _read(key: str) -> str:
        rel = check["report_paths"].get(key)
        if not rel:
            return ""
        try:
            with open(os.path.join(WORKSPACE, rel), "r", encoding="utf-8") as f:
                return f.read()
        except Exception:
            return ""

    val_text  = _read("valuation")
    fin_text  = _read("financials")
    risk_text = _read("risk")

    if not val_text:
        result = {
            "ticker": ticker, "date": date_str, "contradictions": [],
            "checks_performed": {"growth_vs_cagr": False, "margin_vs_actual": False, "wacc_vs_risk": False},
            "note": "valuation_report not found — skipping contradiction check",
        }
        out_path = os.path.join(OUTPUT_DIR, f"contradictions_{ticker}_{date_str}.json")
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        print("---CONTRADICTIONS_JSON---")
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return []

    # Extract valuation assumptions
    growth_assumption = (
        _extract_number(val_text, r"FCF growth.*?base.*?([-+]?\d+\.?\d*)%") or
        _extract_number(val_text, r"FCF tăng ([\d.]+)%/năm") or
        _extract_number(val_text, r"terminal.growth.*?([\d.]+)%")
    )
    wacc_assumption   = _extract_number(val_text, r"WACC[:\s]+([\d.]+)%")
    margin_assumption = _extract_number(val_text, r"net.?margin.*?([\d.]+)%")

    # Extract actuals from financials
    actual_cagr       = _extract_number(fin_text, r"CAGR 2Y[:\s]+([-+]?\d+\.?\d*)%")
    actual_net_margin = _extract_number(fin_text, r"Net margin[:\s]+([-+]?\d+\.?\d*)%")

    # Extract risk level
    overall_risk = _grep(risk_text, r"Mức độ rủi ro tổng thể[:\s]+\[([^\]]+)\]") if risk_text else "[missing_data]"

    checks = {
        "growth_vs_cagr":   growth_assumption is not None and actual_cagr is not None,
        "margin_vs_actual": margin_assumption is not None and actual_net_margin is not None,
        "wacc_vs_risk":     wacc_assumption is not None and risk_text != "",
    }

    T = CONTRADICTION_THRESHOLDS

    # Check 1: growth assumption vs actual CAGR
    if checks["growth_vs_cagr"]:
        if actual_cagr == 0 and growth_assumption > 5.0:
            contradictions.append({
                "type": "growth_assumption_vs_actual", "severity": "HIGH",
                "description": f"Valuation assumes FCF growth {growth_assumption:+.1f}%/yr but actual revenue CAGR 2Y = 0%",
                "val_assumption": f"{growth_assumption:+.1f}%", "actual_metric": "0% (flat revenue)",
                "impact": "DCF base case likely overstated",
            })
        elif actual_cagr < 0 and growth_assumption > 5.0:
            contradictions.append({
                "type": "growth_assumption_vs_actual", "severity": "HIGH",
                "description": f"Valuation assumes positive FCF growth {growth_assumption:+.1f}%/yr but revenue is declining ({actual_cagr:+.1f}% CAGR)",
                "val_assumption": f"{growth_assumption:+.1f}%", "actual_metric": f"{actual_cagr:+.1f}% (revenue CAGR 2Y)",
                "impact": "DCF base case likely overstated — verify growth catalyst",
            })
        elif actual_cagr > 0:
            ratio = growth_assumption / actual_cagr
            if ratio > T["growth_ratio_max"]:
                contradictions.append({
                    "type": "growth_assumption_vs_actual", "severity": "HIGH",
                    "description": (f"Valuation assumes FCF growth {growth_assumption:+.1f}%/yr but historical revenue CAGR 2Y = {actual_cagr:+.1f}% "
                                    f"(ratio {ratio:.1f}× > threshold {T['growth_ratio_max']}×)"),
                    "val_assumption": f"{growth_assumption:+.1f}%", "actual_metric": f"{actual_cagr:+.1f}% (revenue CAGR 2Y)",
                    "impact": "Fair value may be overstated — verify growth catalyst",
                })

    # Check 2: margin assumption vs actual
    if checks["margin_vs_actual"]:
        diff = abs(margin_assumption - actual_net_margin)
        if diff > T["margin_diff_max_pp"]:
            contradictions.append({
                "type": "margin_assumption_vs_actual", "severity": "MEDIUM",
                "description": (f"Valuation implies net margin ~{margin_assumption:.1f}% but reported net margin = {actual_net_margin:.1f}% "
                                f"(diff {diff:.1f}pp > threshold {T['margin_diff_max_pp']}pp)"),
                "val_assumption": f"{margin_assumption:.1f}%", "actual_metric": f"{actual_net_margin:.1f}% (latest net margin)",
                "impact": "EPS/FCF base may be inconsistent with recent results",
            })

    # Check 3: WACC vs risk level
    if checks["wacc_vs_risk"]:
        is_high_risk = any(k in overall_risk.upper() for k in ["CAO", "HIGH"])
        if is_high_risk and wacc_assumption < T["wacc_high_risk_min"]:
            contradictions.append({
                "type": "wacc_vs_risk_level", "severity": "MEDIUM",
                "description": (f"Risk analysis flags overall risk as '{overall_risk}' but WACC = {wacc_assumption:.1f}% "
                                f"(threshold: HIGH risk should use WACC ≥{T['wacc_high_risk_min']}%)"),
                "val_assumption": f"WACC {wacc_assumption:.1f}%", "actual_metric": f"Overall risk = {overall_risk}",
                "impact": "Discount rate may understate risk — fair value may be overstated",
            })

    result = {
        "ticker": ticker, "date": date_str,
        "contradictions": contradictions,
        "checks_performed": checks,
        "note": f"{len(contradictions)} contradiction(s) found",
    }

    out_path = os.path.join(OUTPUT_DIR, f"contradictions_{ticker}_{date_str}.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print("---CONTRADICTIONS_JSON---")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return contradictions


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--ticker", required=True)
    parser.add_argument("--mode", choices=["check", "extract", "summarize", "contradictions"], required=True)
    parser.add_argument("--stage", choices=["fundamental", "valuation"], default=None)
    args = parser.parse_args()

    ticker = args.ticker.upper()

    if args.mode == "check":
        result = check_mode(ticker)
        print(json.dumps(result, ensure_ascii=False))
    elif args.mode == "extract":
        result = extract_mode(ticker)
        print("---AGGREGATE_JSON---")
        print(json.dumps(result, ensure_ascii=False, indent=2))
    elif args.mode == "summarize":
        if not args.stage:
            print("[ERROR] --stage fundamental|valuation required with --mode summarize", file=sys.stderr)
            sys.exit(1)
        summarize_mode(ticker, args.stage)
    elif args.mode == "contradictions":
        contradictions_mode(ticker)


if __name__ == "__main__":
    main()
