#!/usr/bin/env python3
"""Read macro_snapshot_{date}.json → output/macro_report_{date}.md (compact format)"""

import json
import sys
from datetime import date
from pathlib import Path

SKILL_DIR = Path(__file__).parent.parent
DATA_DIR = SKILL_DIR / "data"
OUTPUT_DIR = SKILL_DIR / "output"
OUTPUT_DIR.mkdir(exist_ok=True)

TODAY = date.today().isoformat()
SNAPSHOT_FILE = DATA_DIR / f"macro_snapshot_{TODAY}.json"
REPORT_FILE = OUTPUT_DIR / f"macro_report_{TODAY}.md"

SIGNAL_EMOJI = {"bullish": "🟢", "neutral": "🟡", "bearish": "🔴"}

LABELS = {
    "fed_rate": ("Fed Rate", "%"),
    "us_cpi_yoy": ("US CPI", "% YoY"),
    "us_unemployment": ("US Unemployment", "%"),
    "yield_curve_10y2y": ("Yield Curve 10Y-2Y", "%"),
    "dxy": ("DXY", ""),
    "oil_wti": ("Oil WTI", "$"),
    "gold": ("Gold", "$"),
    "vix": ("VIX", ""),
    "sp500": ("S&P 500", ""),
    "gdp_growth_vn": ("GDP Growth VN", "% YoY"),
    "cpi_vn_yoy": ("CPI VN", "% YoY"),
    "fdi_pct_gdp": ("FDI/GDP VN", "%"),
    "vnindex": ("VN-Index", ""),
    "usd_vnd": ("USD/VND", ""),
}


def fmt_row(key, item):
    label, unit = LABELS.get(key, (key, ""))
    v = item.get("value")
    if v is None:
        return None
    if unit == "$":
        val_str = f"${v:,.0f}"
    elif unit:
        val_str = f"{v}{unit}"
    else:
        val_str = f"{v:,.0f}" if v >= 100 else str(v)
    emoji = SIGNAL_EMOJI.get(item.get("signal", "neutral"), "🟡")
    return f"| {label} | {val_str} | {emoji} {item.get('signal', 'neutral').capitalize()} |"


def main():
    if not SNAPSHOT_FILE.exists():
        print(f"[ERROR] Snapshot not found: {SNAPSHOT_FILE}", file=sys.stderr)
        print("Run fetch_data.py first.", file=sys.stderr)
        sys.exit(1)

    snap = json.loads(SNAPSHOT_FILE.read_text())
    overall = snap.get("overall_signal", "neutral")
    emoji = SIGNAL_EMOJI.get(overall, "🟡")

    lines = [
        f"# Báo cáo Vĩ mô — {TODAY}",
        "",
        "## Toàn cầu",
        "| Chỉ số | Giá trị | Tín hiệu |",
        "|---|---|---|",
    ]
    for key, item in snap.get("global", {}).items():
        row = fmt_row(key, item)
        if row:
            lines.append(row)

    lines += [
        "",
        "## Việt Nam",
        "| Chỉ số | Giá trị | Tín hiệu |",
        "|---|---|---|",
    ]
    for key, item in snap.get("vietnam", {}).items():
        row = fmt_row(key, item)
        if row:
            lines.append(row)

    # Count signals for summary
    all_items = list(snap.get("global", {}).values()) + list(snap.get("vietnam", {}).values())
    bearish_count = sum(1 for x in all_items if isinstance(x, dict) and x.get("signal") == "bearish")
    bullish_count = sum(1 for x in all_items if isinstance(x, dict) and x.get("signal") == "bullish")

    lines += [
        "",
        f"## Verdict: {emoji} {overall.upper()}",
        f"> Bearish signals: {bearish_count} | Bullish signals: {bullish_count}",
        "",
        "_[Claude sẽ bổ sung nhận định kênh truyền dẫn và ngành ảnh hưởng ở đây]_",
    ]

    report_content = "\n".join(lines)
    REPORT_FILE.write_text(report_content)
    print(f"[stock-macro] Report saved → {REPORT_FILE.name}")
    print("---SNAPSHOT_JSON---")
    print(json.dumps(snap, ensure_ascii=False))


if __name__ == "__main__":
    main()
