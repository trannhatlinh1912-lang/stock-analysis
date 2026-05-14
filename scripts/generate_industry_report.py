#!/usr/bin/env python3
"""Generate industry report from JSON snapshot.

Usage:
  python generate_industry_report.py --snapshot data/industry_snapshot_HPG_2026-05-14.json

Output:
  - Saves markdown to output/industry_report_{ticker}_{date}.md
  - Prints markdown table + ---SNAPSHOT_JSON--- + compact JSON to stdout
"""

import argparse
import json
import sys
from pathlib import Path

SKILL_DIR = Path(__file__).parent.parent
OUTPUT_DIR = SKILL_DIR / "output"
OUTPUT_DIR.mkdir(exist_ok=True)

CYCLE_EMOJI = {
    "đáy": "🔴 ĐÁY",
    "hồi_phục": "🟠 HỒI PHỤC",
    "tăng_trưởng": "🟢 TĂNG TRƯỞNG",
    "đỉnh": "🟡 ĐỈNH",
    "suy_giảm": "⚫ SUY GIẢM",
}

TREND_LABEL = {
    "accelerating": "Tăng tốc",
    "recovering": "Phục hồi",
    "flat": "Đi ngang",
    "declining": "Suy giảm",
    "unknown": "Không có data",
}

MARGIN_LABEL = {
    "peak": "Đỉnh biên",
    "expanding": "Mở rộng",
    "stable": "Ổn định",
    "compressed": "Bị nén",
    "deeply_compressed": "Nén mạnh",
    "unknown": "Không có data",
}

PRICE_LABEL = {
    "outperform": "Vượt trội vs VN-Index",
    "neutral": "Sát VN-Index",
    "underperform": "Kém VN-Index",
    "unknown": "Không có data",
}


def fmt(val, suffix="%", na="N/A") -> str:
    if val is None:
        return na
    return f"{val:+.1f}{suffix}" if "+" in f"{val:+}" else f"{val:.1f}{suffix}"


def build_markdown(snap: dict) -> str:
    industry = snap.get("industry", {})
    peers = snap.get("peers", [])
    financials = snap.get("financials", {})
    sector_avg = snap.get("sector_avg", {})
    price_ret = snap.get("price_return", {})
    signals = snap.get("cycle_signals", {})
    cycle_phase = snap.get("cycle_phase", "unknown")
    ticker = snap.get("input_ticker", "")
    report_date = snap.get("date", "")

    cycle_display = CYCLE_EMOJI.get(cycle_phase, f"❓ {cycle_phase.upper()}")

    lines = [
        f"# Phân tích Ngành: {industry.get('name', '')} ({ticker})",
        f"**Ngày:** {report_date}  |  **Ticker input:** {ticker}  |  **Peers:** {', '.join(peers)}",
        "",
        "---",
        "",
        f"## Chu kỳ Ngành: {cycle_display}",
        "",
        "| Tín hiệu | Trạng thái |",
        "|----------|-----------|",
        f"| Revenue trend | {TREND_LABEL.get(signals.get('revenue_trend', 'unknown'))} |",
        f"| Margin trend  | {MARGIN_LABEL.get(signals.get('margin_trend', 'unknown'))} |",
        f"| Giá vs VN-Index (1Y) | {PRICE_LABEL.get(signals.get('price_vs_index', 'unknown'))} |",
        "",
        "---",
        "",
        "## Chỉ số Tài chính Ngành (trung bình peers)",
        "",
        "| Chỉ số | Giá trị |",
        "|--------|---------|",
        f"| Revenue Growth ({sector_avg.get('growth_basis','yoy').upper()}) | {fmt(sector_avg.get('revenue_growth'))} |",
        f"| Gross Margin | {fmt(sector_avg.get('gross_margin'))} |",
        f"| Net Margin | {fmt(sector_avg.get('net_margin'))} |",
        "",
        "## Hiệu suất Giá",
        "",
        "| Kỳ | Ngành | VN-Index | Relative |",
        "|----|-------|----------|----------|",
        f"| 1 năm | {fmt(price_ret.get('sector_1y'))} | {fmt(price_ret.get('vnindex_1y'))} | {fmt(price_ret.get('relative_1y'))} |",
        f"| 6 tháng | {fmt(price_ret.get('sector_6m'))} | — | — |",
        f"| 3 tháng | {fmt(price_ret.get('sector_3m'))} | — | — |",
        "",
        "## Peers Chi tiết",
        "",
        "| Ticker | Revenue Growth | Gross Margin | Net Margin |",
        "|--------|---------------|--------------|------------|",
    ]

    for p in peers:
        fin = financials.get(p, {})
        basis = fin.get("growth_basis", "yoy").upper()
        lines.append(
            f"| {p} | {fmt(fin.get('revenue_growth'))} ({basis}) | {fmt(fin.get('gross_margin'))} | {fmt(fin.get('net_margin'))} |"
        )

    lines += [
        "",
        "---",
        "",
        "*Data source: vnstock (VCI) + yfinance. Chỉ số tài chính từ báo cáo quý gần nhất.*",
        "*[FACT] = từ data API | [ASSUMPTION] = suy luận | [CONCLUSION] = nhận định Claude*",
    ]

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--snapshot", required=True, help="Path to industry snapshot JSON")
    args = parser.parse_args()

    snapshot_path = Path(args.snapshot)
    if not snapshot_path.exists():
        print(f"[ERROR] Snapshot not found: {snapshot_path}", file=sys.stderr)
        sys.exit(1)

    snap = json.loads(snapshot_path.read_text())
    ticker = snap.get("input_ticker", "UNKNOWN")
    report_date = snap.get("date", "unknown")

    markdown = build_markdown(snap)

    output_file = OUTPUT_DIR / f"industry_report_{ticker}_{report_date}.md"
    output_file.write_text(markdown, encoding="utf-8")
    print(f"[stock-industry] Report saved → {output_file.name}", file=sys.stderr)

    print(markdown)
    print("\n---SNAPSHOT_JSON---")
    print(json.dumps(snap, ensure_ascii=False))


if __name__ == "__main__":
    main()
