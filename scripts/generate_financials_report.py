#!/usr/bin/env python3
"""Generate financial analysis report from snapshot.

Usage:
  python generate_financials_report.py --snapshot data/financial_snapshot_HPG_2026-05-14.json

Output:
  - Saves markdown to output/financial_report_{ticker}_{date}.md
  - Prints markdown + ---SNAPSHOT_JSON--- + compact JSON to stdout
"""

import argparse
import json
import sys
from pathlib import Path

SKILL_DIR = Path(__file__).parent.parent
OUTPUT_DIR = SKILL_DIR / "output"
OUTPUT_DIR.mkdir(exist_ok=True)

SCORE_BAND = {
    (8.0, 10.0): "Mạnh",
    (6.0, 7.9):  "Khá",
    (4.0, 5.9):  "Trung bình",
    (0.0, 3.9):  "Yếu",
}

FLAG_EMOJI = {"high": "🔴", "medium": "🟡", "low": "🟢"}


def fmt_pct(val, na="N/A"):
    if val is None:
        return na
    sign = "+" if val > 0 else ""
    return f"{sign}{val:.1f}%"


def fmt_num(val, unit="B VND", na="N/A"):
    if val is None:
        return na
    return f"{val:,.0f} {unit}"


def fmt_x(val, na="N/A"):
    if val is None:
        return na
    return f"{val:.1f}×"


def score_band(total) -> str:
    if total is None:
        return "N/A"
    for (lo, hi), label in SCORE_BAND.items():
        if lo <= total <= hi:
            return label
    return "Yếu"


def build_markdown(snap: dict) -> str:
    ticker      = snap.get("ticker", "")
    industry    = snap.get("industry_name", "")
    report_date = snap.get("date", "")
    income      = snap.get("income", {})
    balance     = snap.get("balance_sheet", {})
    cashflow    = snap.get("cashflow", {})
    ratios      = snap.get("ratios", {})
    derived     = snap.get("derived", {})
    red_flags   = snap.get("red_flags", [])
    fs          = snap.get("financial_score", {})
    warnings    = snap.get("data_warnings", [])

    total_score = fs.get("total", 0)
    band        = score_band(total_score)
    breakdown   = fs.get("breakdown", {})
    quarters    = income.get("quarters", [])

    lines = [
        f"# Phân tích Tài chính: {ticker}",
        f"**Ngày:** {report_date}  |  **Ngành:** {industry}",
        "",
        "---",
        "",
        f"## Điểm Tài chính: **{total_score}/10 — {band}**",
        "",
        "| Tiêu chí | Điểm | Max |",
        "|----------|------|-----|",
    ]

    criteria_labels = {
        "revenue_cagr":     "Tăng trưởng DT (CAGR 2Y)",
        "net_margin":       "Net Margin",
        "roic":             "ROIC / ROE",
        "earnings_quality": "Chất lượng LN (OCF/NI)",
        "fcf":              "FCF 4Q",
        "interest_coverage":"Interest Coverage",
        "de_or_roa":        "D/E (hoặc ROA ngân hàng)",
        "current_ratio":    "Current Ratio",
    }
    max_pts = {
        "revenue_cagr": 1.5, "net_margin": 1.5, "roic": 1.5,
        "earnings_quality": 1.5, "fcf": 1.0, "interest_coverage": 1.5,
        "de_or_roa": 1.0, "current_ratio": 1.0,
    }
    for key, label in criteria_labels.items():
        if key in breakdown:
            pts = breakdown[key]
            mx  = max_pts.get(key, 1.5)
            lines.append(f"| {label} | {pts:.2f} | {mx:.1f} |")

    # Income trend table (8Q)
    revenue_b = income.get("revenue_b", [])
    gm_pct    = income.get("gross_margin_pct", [])
    nm_pct    = income.get("net_margin_pct", [])
    ni_b      = income.get("net_income_b", [])

    lines += [
        "",
        "---",
        "",
        "## Xu hướng Doanh thu & Lợi nhuận (8Q)",
        "",
        "| Quý | DT (B VND) | GM% | NM% | NI (B VND) |",
        "|-----|-----------|-----|-----|-----------|",
    ]
    for i in range(min(8, len(quarters))):
        q   = quarters[i] if i < len(quarters) else "?"
        rev = fmt_num(revenue_b[i] if i < len(revenue_b) else None, "")
        gm  = fmt_pct(gm_pct[i] if i < len(gm_pct) else None)
        nm  = fmt_pct(nm_pct[i] if i < len(nm_pct) else None)
        ni  = fmt_num(ni_b[i] if i < len(ni_b) else None, "")
        lines.append(f"| {q} | {rev} | {gm} | {nm} | {ni} |")

    lines += [
        "",
        f"*CAGR 2Y: {fmt_pct(income.get('revenue_cagr_2y'))} | YoY latest: {fmt_pct(income.get('revenue_yoy_latest'))} | GM trend: {income.get('gross_margin_trend', 'N/A')}*",
        "",
        "---",
        "",
        "## Sinh lời & Hiệu quả Vốn",
        "",
        "| Chỉ số | Giá trị |",
        "|--------|---------|",
        f"| ROE avg 4Q | {fmt_pct(ratios.get('roe_avg_4q'))} |",
        f"| ROA (latest) | {fmt_pct(ratios.get('roa_latest'))} |",
        f"| ROIC | {fmt_pct(derived.get('roic'))} |",
        f"| P/E | {ratios.get('pe_latest') or 'N/A'}× |",
        f"| P/B | {ratios.get('pb_latest') or 'N/A'}× |",
        f"| Capex/Revenue | {fmt_pct(derived.get('capex_to_revenue_pct'))} |",
        "",
        "---",
        "",
        "## Bảng cân đối kế toán",
        "",
        "| Chỉ số | Giá trị |",
        "|--------|---------|",
        f"| D/E ratio | {fmt_x(balance.get('de_ratio'))} |",
        f"| Net debt | {fmt_num(balance.get('net_debt_b'))} |",
        f"| Current ratio | {fmt_x(balance.get('current_ratio'))} |",
        f"| Quick ratio | {fmt_x(balance.get('quick_ratio'))} |",
        f"| Equity growth YoY | {fmt_pct(balance.get('equity_growth_yoy'))} |",
        f"| D/E trend (4Q) | {balance.get('de_trend', 'N/A')} |",
        "",
        "---",
        "",
        "## Chất lượng Dòng tiền",
        "",
        "| Chỉ số | Giá trị |",
        "|--------|---------|",
        f"| OCF 4Q | {fmt_num(cashflow.get('ocf_4q_sum_b'))} ({'✅' if cashflow.get('ocf_positive') else '⚠️' if cashflow.get('ocf_positive') is not None else ''}) |",
        f"| FCF 4Q | {fmt_num(cashflow.get('fcf_4q_sum_b'))} ({'✅' if cashflow.get('fcf_positive') else '⚠️' if cashflow.get('fcf_positive') is not None else ''}) |",
        f"| Capex 4Q | {fmt_num(cashflow.get('capex_4q_sum_b'))} |",
        f"| OCF/NI | {derived.get('ocf_to_ni') or 'N/A'} |",
        f"| FCF/NI | {derived.get('fcf_to_ni') or 'N/A'} |",
        "",
        "---",
        "",
        "## Phân tích Nợ vay",
        "",
        "| Chỉ số | Giá trị |",
        "|--------|---------|",
        f"| Interest expense 4Q | {fmt_num(derived.get('interest_expense_4q_b'))} |",
        f"| Interest coverage | {fmt_x(derived.get('interest_coverage'))} |",
        f"| Net debt / EBIT | {fmt_x(derived.get('net_debt_to_ebit'))} |",
        "",
        "---",
        "",
        "## Vòng quay Ngắn hạn",
        "",
        "| Chỉ số | Giá trị | Xu hướng |",
        "|--------|---------|----------|",
        f"| AR days | {derived.get('ar_days') or 'N/A'} ngày | {derived.get('ar_days_trend', 'N/A')} |",
        f"| Inventory days | {derived.get('inventory_days') or 'N/A'} ngày | {derived.get('inventory_days_trend', 'N/A')} |",
        "",
        "---",
        "",
        "## Red Flags Tài chính",
        "",
    ]

    if red_flags:
        lines += ["| # | Flag | Severity | Chi tiết |", "|---|------|----------|----------|"]
        for i, f in enumerate(red_flags, 1):
            sev = f.get("severity", "low")
            lines.append(f"| {i} | {f.get('flag','')} | {FLAG_EMOJI.get(sev,'')} {sev} | {f.get('detail','')} |")
    else:
        lines.append("*Không phát hiện red flags tài chính đáng kể.*")

    if warnings:
        lines += ["", "---", "", "## Data Warnings", ""]
        for w in warnings:
            lines.append(f"- `{w}`")

    lines += [
        "",
        "---",
        "",
        "*Data source: vnstock (VCI). [FACT]=từ API | [ASSUMPTION]=suy luận | [CONCLUSION]=nhận định*",
    ]

    return "\n".join(lines)


def build_compact_json(snap: dict) -> dict:
    income   = snap.get("income", {})
    balance  = snap.get("balance_sheet", {})
    cashflow = snap.get("cashflow", {})
    ratios   = snap.get("ratios", {})
    derived  = snap.get("derived", {})
    fs       = snap.get("financial_score", {})

    return {
        "ticker":        snap.get("ticker"),
        "industry_name": snap.get("industry_name"),
        "date":          snap.get("date"),

        "income_table": {
            "quarters":           income.get("quarters", [])[:8],
            "revenue_b":          income.get("revenue_b", [])[:8],
            "gm_pct":             income.get("gross_margin_pct", [])[:8],
            "nm_pct":             income.get("net_margin_pct", [])[:8],
            "ni_b":               income.get("net_income_b", [])[:8],
            "revenue_cagr_2y":    income.get("revenue_cagr_2y"),
            "revenue_yoy_latest": income.get("revenue_yoy_latest"),
            "gm_trend":           income.get("gross_margin_trend"),
            "gm_latest":          income.get("gross_margin_latest"),
            "nm_latest":          income.get("net_margin_latest"),
        },

        "profitability": {
            "roe_avg_4q": ratios.get("roe_avg_4q"),
            "roa_latest": ratios.get("roa_latest"),
            "roic":       derived.get("roic"),
            "pe_latest":  ratios.get("pe_latest"),
            "pb_latest":  ratios.get("pb_latest"),
        },

        "balance_sheet": {
            "de_ratio":          balance.get("de_ratio"),
            "net_debt_b":        balance.get("net_debt_b"),
            "current_ratio":     balance.get("current_ratio"),
            "quick_ratio":       balance.get("quick_ratio"),
            "equity_growth_yoy": balance.get("equity_growth_yoy"),
            "de_trend":          balance.get("de_trend"),
            "negative_equity":   balance.get("negative_equity"),
        },

        "cashflow": {
            "ocf_4q_sum_b":          cashflow.get("ocf_4q_sum_b"),
            "fcf_4q_sum_b":          cashflow.get("fcf_4q_sum_b"),
            "capex_4q_sum_b":        cashflow.get("capex_4q_sum_b"),
            "fcf_positive":          cashflow.get("fcf_positive"),
            "ocf_positive":          cashflow.get("ocf_positive"),
            "ocf_to_ni":             derived.get("ocf_to_ni"),
            "fcf_to_ni":             derived.get("fcf_to_ni"),
            "capex_to_revenue_pct":  derived.get("capex_to_revenue_pct"),
        },

        "debt": {
            "interest_expense_4q_b": derived.get("interest_expense_4q_b"),
            "interest_coverage":     derived.get("interest_coverage"),
            "net_debt_to_ebit":      derived.get("net_debt_to_ebit"),
        },

        "working_capital": {
            "ar_days":              derived.get("ar_days"),
            "inventory_days":       derived.get("inventory_days"),
            "ar_days_trend":        derived.get("ar_days_trend"),
            "inventory_days_trend": derived.get("inventory_days_trend"),
        },

        "red_flags": snap.get("red_flags", []),

        "financial_score": {
            "total":     fs.get("total"),
            "max":       fs.get("max"),
            "band":      score_band(fs.get("total")),
            "breakdown": fs.get("breakdown", {}),
        },

        "data_warnings": snap.get("data_warnings", []),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--snapshot", required=True)
    args = parser.parse_args()

    snapshot_path = Path(args.snapshot)
    if not snapshot_path.exists():
        print(f"[ERROR] Snapshot not found: {snapshot_path}", file=sys.stderr)
        sys.exit(1)

    snap = json.loads(snapshot_path.read_text(encoding="utf-8"))
    ticker      = snap.get("ticker", "UNKNOWN")
    report_date = snap.get("date", "unknown")

    markdown = build_markdown(snap)

    output_file = OUTPUT_DIR / f"financial_report_{ticker}_{report_date}.md"
    output_file.write_text(markdown, encoding="utf-8")
    print(f"[stock-financials] Report saved → {output_file.name}", file=sys.stderr)

    print(markdown)
    print("\n---SNAPSHOT_JSON---")
    print(json.dumps(build_compact_json(snap), ensure_ascii=False))


if __name__ == "__main__":
    main()
