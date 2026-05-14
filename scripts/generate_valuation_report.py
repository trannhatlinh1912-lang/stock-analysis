#!/usr/bin/env python3
"""Generate valuation report from snapshot.

Usage:
  python generate_valuation_report.py --snapshot data/valuation_snapshot_HPG_2026-05-15.json

Output:
  - Saves markdown to output/valuation_report_{ticker}_{date}.md
  - Prints markdown + ---SNAPSHOT_JSON--- + compact JSON to stdout
"""

import argparse
import json
import sys
from pathlib import Path

SKILL_DIR  = Path(__file__).parent.parent
OUTPUT_DIR = SKILL_DIR / "output"
OUTPUT_DIR.mkdir(exist_ok=True)


def fmt_price(val, na="N/A"):
    if val is None:
        return na
    return f"{val:,.0f} VND"


def fmt_num(val, unit="B VND", na="N/A"):
    if val is None:
        return na
    return f"{val:,.0f} {unit}"


def fmt_pct(val, na="N/A"):
    if val is None:
        return na
    sign = "+" if val > 0 else ""
    return f"{sign}{val:.1f}%"


def fmt_x(val, na="N/A"):
    if val is None:
        return na
    return f"{val:.1f}×"


def upside_emoji(pct):
    if pct is None:
        return ""
    return "📈" if pct >= 10 else ("📉" if pct <= -10 else "➡️")


def build_markdown(snap: dict) -> str:
    ticker       = snap.get("ticker", "")
    industry     = snap.get("industry_name", "")
    report_date  = snap.get("date", "")
    current_p    = snap.get("current_price")
    primary      = snap.get("primary_method", "PE")
    wacc_pct     = snap.get("wacc_pct")
    trailing     = snap.get("trailing_metrics", {})
    cur_mult     = snap.get("current_multiples", {})
    hist_pe      = snap.get("hist_pe", {})
    hist_pb      = snap.get("hist_pb", {})
    peers        = snap.get("peer_multiples", {})
    scenarios    = snap.get("scenarios", {})
    dcf          = snap.get("dcf", {})
    fv           = snap.get("fair_value", {})
    upside       = snap.get("upside_downside", {})
    mos          = snap.get("margin_of_safety", {})
    rnav_note    = snap.get("rnav_note")
    sotp_note    = snap.get("sotp_note")
    warnings     = snap.get("data_warnings", [])

    lines = [
        f"# Định giá: {ticker}",
        f"**Ngày:** {report_date}  |  **Ngành:** {industry}  |  **Giá hiện tại:** {fmt_price(current_p)}",
        f"**Phương pháp chính:** {primary}  |  **WACC:** {wacc_pct}%  |  **Terminal growth:** 4%",
        "",
        "---",
        "",
        "## Trailing Metrics (TTM)",
        "",
        "| Chỉ số | Giá trị |",
        "|--------|---------|",
        f"| Revenue TTM | {fmt_num(trailing.get('revenue_ttm_b'))} |",
        f"| Net Income TTM | {fmt_num(trailing.get('ni_ttm_b'))} |",
        f"| EBIT TTM | {fmt_num(trailing.get('ebit_ttm_b'))} |",
        f"| EBITDA TTM | {fmt_num(trailing.get('ebitda_ttm_b'))} |",
        f"| FCF TTM | {fmt_num(trailing.get('fcf_ttm_b'))} |",
        f"| EPS TTM | {fmt_price(trailing.get('eps_ttm'))} |",
        f"| BVPS (latest) | {fmt_price(trailing.get('bvps_latest'))} |",
        f"| Shares outstanding | {trailing.get('shares_m') or 'N/A'} triệu cổ phiếu |",
        "",
        "---",
        "",
        "## Định giá Hiện tại vs Lịch sử vs Peers",
        "",
        "| Chỉ số | Hiện tại | Hist Min | Hist P25 | Hist Median | Hist P75 | Hist Max | Peer Median |",
        "|--------|----------|----------|----------|-------------|----------|----------|-------------|",
        f"| P/E | {fmt_x(cur_mult.get('pe_ttm'))} | {fmt_x(hist_pe.get('min'))} | {fmt_x(hist_pe.get('p25'))} | {fmt_x(hist_pe.get('median'))} | {fmt_x(hist_pe.get('p75'))} | {fmt_x(hist_pe.get('max'))} | {fmt_x(peers.get('pe_median'))} |",
        f"| P/B | {fmt_x(cur_mult.get('pb_latest'))} | {fmt_x(hist_pb.get('min'))} | {fmt_x(hist_pb.get('p25'))} | {fmt_x(hist_pb.get('median'))} | {fmt_x(hist_pb.get('p75'))} | {fmt_x(hist_pb.get('max'))} | {fmt_x(peers.get('pb_median'))} |",
        f"| EV/EBITDA | {fmt_x(cur_mult.get('ev_ebitda'))} | N/A | N/A | N/A | N/A | N/A | N/A |",
    ]

    if peers.get("tickers"):
        lines.append(f"\n*Peers so sánh: {', '.join(peers['tickers'])}*")

    # Scenarios
    bear = scenarios.get("bear", {})
    base = scenarios.get("base", {})
    bull = scenarios.get("bull", {})

    lines += [
        "",
        "---",
        "",
        f"## Kịch bản Định giá ({primary})",
        "",
        "| Kịch bản | Giả định | Target Price | Upside/Downside |",
        "|----------|----------|-------------|-----------------|",
        f"| 🐻 Bear | {bear.get('assumption','N/A')} | {fmt_price(bear.get('target_price'))} | {fmt_pct(bear.get('upside_pct'))} {upside_emoji(bear.get('upside_pct'))} |",
        f"| ➡️ Base | {base.get('assumption','N/A')} | {fmt_price(base.get('target_price'))} | {fmt_pct(base.get('upside_pct'))} {upside_emoji(base.get('upside_pct'))} |",
        f"| 🐂 Bull | {bull.get('assumption','N/A')} | {fmt_price(bull.get('target_price'))} | {fmt_pct(bull.get('upside_pct'))} {upside_emoji(bull.get('upside_pct'))} |",
    ]

    # DCF
    lines += [
        "",
        "---",
        "",
        "## DCF Analysis",
        "",
    ]

    if dcf.get("available"):
        dcf_bear = dcf.get("bear", {})
        dcf_base = dcf.get("base", {})
        dcf_bull = dcf.get("bull", {})
        lines += [
            f"WACC: {dcf.get('wacc_pct')}% | Terminal growth: {dcf.get('terminal_growth_pct')}% | FCF base: {fmt_num(dcf.get('fcf_ttm_b'))}",
            "",
            "| Kịch bản | FCF Growth | Equity Value | Target Price |",
            "|----------|-----------|-------------|--------------|",
            f"| Bear | {dcf_bear.get('label','N/A')} | {fmt_num(dcf_bear.get('equity_value_b'))} | {fmt_price(dcf_bear.get('target_price'))} |",
            f"| Base | {dcf_base.get('label','N/A')} | {fmt_num(dcf_base.get('equity_value_b'))} | {fmt_price(dcf_base.get('target_price'))} |",
            f"| Bull | {dcf_bull.get('label','N/A')} | {fmt_num(dcf_bull.get('equity_value_b'))} | {fmt_price(dcf_bull.get('target_price'))} |",
        ]
        if dcf.get("note"):
            lines.append(f"\n*⚠️ {dcf['note']}*")
    else:
        lines.append(f"*{dcf.get('note', 'DCF không khả thi.')}*")

    # RNAV / SOTP notes
    if rnav_note:
        lines += ["", "---", "", f"## RNAV Note", "", f"*{rnav_note}*"]
    if sotp_note:
        lines += ["", "---", "", f"## SOTP Note", "", f"*{sotp_note}*"]

    # Fair value range
    lines += [
        "",
        "---",
        "",
        "## Vùng Giá trị Hợp lý",
        "",
        "| | Giá trị |",
        "|-|---------|",
        f"| Fair Value Low (Bear target) | {fmt_price(fv.get('low'))} |",
        f"| Fair Value Mid (Base{'+ DCF blend' if fv.get('dcf_blend_used') else ''}) | {fmt_price(fv.get('mid'))} |",
        f"| Fair Value High (Bull target) | {fmt_price(fv.get('high'))} |",
        f"| Giá hiện tại | {fmt_price(current_p)} |",
    ]

    # Upside/downside summary
    lines += [
        "",
        "---",
        "",
        "## Upside / Downside Summary",
        "",
        "| Mốc | Target | vs Giá hiện tại |",
        "|-----|--------|-----------------|",
    ]
    price_labels = {
        "vs_bear_pct":    (bear.get("target_price"),    "Bear case"),
        "vs_base_pct":    (base.get("target_price"),    "Base case"),
        "vs_bull_pct":    (bull.get("target_price"),    "Bull case"),
        "vs_dcf_base_pct": ((dcf.get("base") or {}).get("target_price"), "DCF base"),
        "vs_mid_pct":     (fv.get("mid"),               "Fair mid"),
    }
    for key, (tp, label) in price_labels.items():
        pct = upside.get(key)
        if tp is not None:
            lines.append(f"| {label} | {fmt_price(tp)} | {fmt_pct(pct)} {upside_emoji(pct)} |")

    # Margin of safety
    lines += [
        "",
        "---",
        "",
        "## Margin of Safety",
        "",
        f"**MoS vs Fair Mid:** {fmt_pct(mos.get('pct'))}",
        "",
        f"*{mos.get('note', 'Không tính được MoS — thiếu current_price hoặc fair_mid.')}*",
    ]

    if warnings:
        lines += ["", "---", "", "## Data Warnings", ""]
        for w in warnings:
            lines.append(f"- `{w}`")

    lines += [
        "",
        "---",
        "",
        "*Data source: vnstock (VCI). [FACT]=từ API | [ASSUMPTION]=giả định | [CONCLUSION]=nhận định*",
        "*Không khuyến nghị mua/bán. Vùng giá trị hợp lý dựa trên dữ liệu lịch sử và giả định mô hình.*",
    ]

    return "\n".join(lines)


def build_compact_json(snap: dict) -> dict:
    """Build ~4KB compact JSON for Claude to read in the skill."""
    return {
        "ticker":          snap.get("ticker"),
        "industry_name":   snap.get("industry_name"),
        "date":            snap.get("date"),
        "current_price":   snap.get("current_price"),
        "primary_method":  snap.get("primary_method"),
        "wacc_pct":        snap.get("wacc_pct"),

        "trailing_metrics": snap.get("trailing_metrics", {}),

        "current_multiples": snap.get("current_multiples", {}),

        "hist_pe": snap.get("hist_pe", {}),
        "hist_pb": snap.get("hist_pb", {}),

        "peer_multiples": snap.get("peer_multiples", {}),

        "scenarios": snap.get("scenarios", {}),

        "dcf": {
            "available":           (snap.get("dcf") or {}).get("available"),
            "wacc_pct":            (snap.get("dcf") or {}).get("wacc_pct"),
            "terminal_growth_pct": (snap.get("dcf") or {}).get("terminal_growth_pct"),
            "fcf_ttm_b":           (snap.get("dcf") or {}).get("fcf_ttm_b"),
            "bear":                (snap.get("dcf") or {}).get("bear"),
            "base":                (snap.get("dcf") or {}).get("base"),
            "bull":                (snap.get("dcf") or {}).get("bull"),
            "note":                (snap.get("dcf") or {}).get("note"),
        },

        "fair_value":       snap.get("fair_value", {}),
        "upside_downside":  snap.get("upside_downside", {}),
        "margin_of_safety": snap.get("margin_of_safety", {}),

        "rnav_note": snap.get("rnav_note"),
        "sotp_note": snap.get("sotp_note"),

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

    snap        = json.loads(snapshot_path.read_text(encoding="utf-8"))
    ticker      = snap.get("ticker", "UNKNOWN")
    report_date = snap.get("date", "unknown")

    markdown = build_markdown(snap)

    output_file = OUTPUT_DIR / f"valuation_report_{ticker}_{report_date}.md"
    output_file.write_text(markdown, encoding="utf-8")
    print(f"[stock-valuation] Report saved → {output_file.name}", file=sys.stderr)

    print(markdown)
    print("\n---SNAPSHOT_JSON---")
    print(json.dumps(build_compact_json(snap), ensure_ascii=False))


if __name__ == "__main__":
    main()
