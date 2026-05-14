#!/usr/bin/env python3
"""Generate business quality report from JSON snapshot.

Usage:
  python generate_business_report.py --snapshot data/business_snapshot_HPG_2026-05-14.json

Output:
  - Saves markdown to output/business_report_{ticker}_{date}.md
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
    (8.0, 10.0): "Cao",
    (6.0, 7.9):  "Khá",
    (4.0, 5.9):  "Trung bình",
    (0.0, 3.9):  "Thấp",
}

ROE_TREND_LABEL = {
    "improving": "Cải thiện ↑",
    "stable":    "Ổn định →",
    "declining": "Suy giảm ↓",
    "unknown":   "Không đủ data",
}


def fmt_pct(val, na="N/A") -> str:
    if val is None:
        return na
    sign = "+" if val > 0 else ""
    return f"{sign}{val:.1f}%"


def fmt_num(val, unit="B", na="N/A") -> str:
    if val is None:
        return na
    return f"{val:,.0f} {unit}"


def score_band(total: float) -> str:
    for (lo, hi), label in SCORE_BAND.items():
        if lo <= total <= hi:
            return label
    return "Thấp"


def build_markdown(snap: dict) -> str:
    ticker       = snap.get("ticker", "")
    industry     = snap.get("industry_name", "")
    report_date  = snap.get("date", "")
    company      = snap.get("company", {})
    officers     = snap.get("officers", [])
    shareholders = snap.get("shareholders", [])
    financials   = snap.get("financials", {})
    ratios       = snap.get("ratios", {})
    balance      = snap.get("balance_sheet", {})
    cf           = snap.get("cash_flow", {})
    peer_rank    = snap.get("peer_revenue_rank", [])
    ind_avg      = snap.get("industry_avg", {})
    qs           = snap.get("quality_score", {})
    warnings     = snap.get("data_warnings", [])

    short_name = company.get("short_name", ticker)
    desc = company.get("description", "")
    desc_display = (desc[:200] + "...") if len(desc) > 200 else desc
    if not desc_display:
        desc_display = "[không có mô tả]"

    total_score = qs.get("total", 0)
    band = score_band(total_score)
    breakdown = qs.get("breakdown", {})

    quarters = financials.get("quarters", [])
    rev_list = financials.get("revenue_b_vnd", [])
    gm_list  = financials.get("gross_margin", [])
    nm_list  = financials.get("net_margin", [])

    roe_list = ratios.get("roe_per_quarter", [])
    roe_avg  = ratios.get("roe_avg_4q")
    roe_trend = ratios.get("roe_trend", "unknown")

    lines = [
        f"# Phân tích Doanh nghiệp: {short_name} ({ticker})",
        f"**Ngày:** {report_date}  |  **Ngành:** {industry}  |  **Ticker:** {ticker}",
        "",
        "---",
        "",
        "## Tổng quan Công ty",
        "",
        f"**Tên:** {short_name}",
        f"**Mô tả:** {desc_display}",
        "",
        "---",
        "",
        "## Điểm Chất lượng Doanh nghiệp",
        "",
        f"### **{total_score}/10 — {band}**",
        "",
        "| Tiêu chí | Điểm | Max |",
        "|----------|------|-----|",
    ]

    criteria_labels = {
        "roe":            "ROE avg 4Q",
        "net_margin":     "Net Margin",
        "margin_stability": "Biên lợi nhuận ổn định",
        "debt_to_equity": "D/E Ratio",
        "roa_bank":       "ROA (ngân hàng)",
        "fcf":            "Chất lượng FCF",
        "revenue_growth": "Tăng trưởng doanh thu",
    }
    max_pts = {
        "roe": 1.5, "net_margin": 1.5, "margin_stability": 2.0,
        "debt_to_equity": 2.0, "roa_bank": 2.0, "fcf": 2.0, "revenue_growth": 1.0,
    }
    for key, label in criteria_labels.items():
        if key in breakdown:
            pts = breakdown[key]
            mx  = max_pts.get(key, 2.0)
            lines.append(f"| {label} | {pts:.1f} | {mx:.1f} |")

    lines += [
        "",
        "---",
        "",
        "## Xu hướng Tài chính (4Q gần nhất)",
        "",
        "| Quý | Doanh thu (B VND) | Gross Margin | Net Margin |",
        "|-----|-------------------|--------------|------------|",
    ]

    for i in range(min(4, len(quarters))):
        q   = quarters[i] if i < len(quarters) else "?"
        rev = fmt_num(rev_list[i] if i < len(rev_list) else None, "B")
        gm  = fmt_pct(gm_list[i] if i < len(gm_list) else None)
        nm  = fmt_pct(nm_list[i] if i < len(nm_list) else None)
        lines.append(f"| {q} | {rev} | {gm} | {nm} |")

    gm_std = financials.get("gross_margin_std_8q")
    gm_avg = financials.get("gross_margin_avg_8q")
    lines += [
        "",
        f"*Gross margin (8Q): avg {fmt_pct(gm_avg)}, std ±{fmt_pct(gm_std, 'N/A')}*",
        f"*Industry avg gross margin: {fmt_pct(ind_avg.get('gross_margin'))} | net margin: {fmt_pct(ind_avg.get('net_margin'))}*",
        "",
        "---",
        "",
        "## Chỉ số Tài chính Chính",
        "",
        "| Chỉ số | Giá trị |",
        "|--------|---------|",
        f"| ROE avg 4Q | {fmt_pct(roe_avg)} ({ROE_TREND_LABEL.get(roe_trend, roe_trend)}) |",
        f"| ROA (latest) | {fmt_pct(ratios.get('roa_latest'))} |",
        f"| P/E (latest) | {ratios.get('pe_latest') or 'N/A'}x |",
        f"| P/B (latest) | {ratios.get('pb_latest') or 'N/A'}x |",
        f"| D/E (latest) | {balance.get('debt_to_equity') or 'N/A'}x |",
        f"| Equity growth YoY | {fmt_pct(balance.get('equity_growth_yoy'))} |",
        f"| FCF 4Q sum | {fmt_num(cf.get('fcf_4q_sum_b_vnd'), 'B VND')} ({'Dương ✅' if cf.get('fcf_positive') else 'Âm ⚠️' if cf.get('fcf_positive') is not None else 'N/A'}) |",
        f"| Total assets | {fmt_num(balance.get('total_assets_latest_b_vnd'), 'B VND')} |",
        "",
        "---",
        "",
        "## Vị thế trong Ngành (Doanh thu)",
        "",
        "| Rank | Ticker | Doanh thu Q gần nhất (B VND) |",
        "|------|--------|------------------------------|",
    ]

    for p in peer_rank:
        rank_str = str(p.get("rank") or "?")
        t = p.get("ticker", "")
        rev = fmt_num(p.get("revenue_latest_q_b_vnd"))
        marker = " ◀" if t == ticker else ""
        lines.append(f"| {rank_str} | {t}{marker} | {rev} |")

    lines += [
        "",
        "---",
        "",
        "## Ban Lãnh đạo",
        "",
        "| Tên | Chức danh |",
        "|-----|-----------|",
    ]

    if officers:
        for o in officers:
            lines.append(f"| {o.get('name', '')} | {o.get('position', '')} |")
    else:
        lines.append("| [missing_data] | — |")

    lines += [
        "",
        "## Cổ đông Lớn",
        "",
        "| Cổ đông | Tỷ lệ sở hữu |",
        "|---------|--------------|",
    ]

    if shareholders:
        for s in shareholders:
            pct = f"{s['pct']:.2f}%" if s.get("pct") is not None else "N/A"
            lines.append(f"| {s.get('name', '')} | {pct} |")
    else:
        lines.append("| [missing_data] | — |")

    if warnings:
        lines += [
            "",
            "---",
            "",
            "## Data Warnings",
            "",
        ]
        for w in warnings:
            lines.append(f"- `{w}`")

    lines += [
        "",
        "---",
        "",
        "*Data source: vnstock (VCI). Tài chính từ báo cáo quý.*",
        "*[FACT] = từ data API | [ASSUMPTION] = suy luận | [CONCLUSION] = nhận định Claude*",
    ]

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--snapshot", required=True, help="Path to business snapshot JSON")
    args = parser.parse_args()

    snapshot_path = Path(args.snapshot)
    if not snapshot_path.exists():
        print(f"[ERROR] Snapshot not found: {snapshot_path}", file=sys.stderr)
        sys.exit(1)

    snap = json.loads(snapshot_path.read_text(encoding="utf-8"))
    ticker      = snap.get("ticker", "UNKNOWN")
    report_date = snap.get("date", "unknown")

    markdown = build_markdown(snap)

    output_file = OUTPUT_DIR / f"business_report_{ticker}_{report_date}.md"
    output_file.write_text(markdown, encoding="utf-8")
    print(f"[stock-business] Report saved → {output_file.name}", file=sys.stderr)

    print(markdown)
    print("\n---SNAPSHOT_JSON---")
    print(json.dumps(snap, ensure_ascii=False))


if __name__ == "__main__":
    main()
