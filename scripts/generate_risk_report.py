#!/usr/bin/env python3
"""Generate compact risk report JSON from risk snapshot.

Usage:
  python generate_risk_report.py --snapshot data/risk_snapshot_HPG_2026-05-15.json
"""

import argparse
import json
import sys
from pathlib import Path

SKILL_DIR = Path(__file__).parent.parent
OUTPUT_DIR = SKILL_DIR / "output"
OUTPUT_DIR.mkdir(exist_ok=True)


def score_ownership_risk(ownership: dict, shareholders: list) -> dict:
    flags = []
    score = 0  # 0=LOW, 1=MEDIUM, 2=HIGH, 3=CRITICAL

    top1 = ownership.get("top1_pct")
    top5 = ownership.get("top5_pct")
    state = ownership.get("state_pct")
    hhi = ownership.get("hhi_top5")

    if top1 is not None:
        if top1 >= 50:
            flags.append(f"Cổ đông lớn nhất nắm {top1}% — kiểm soát tuyệt đối, rủi ro minority squeeze-out")
            score = max(score, 3)
        elif top1 >= 35:
            flags.append(f"Cổ đông lớn nhất nắm {top1}% — quyền kiểm soát thực tế, HĐQT phụ thuộc")
            score = max(score, 2)
        elif top1 >= 20:
            flags.append(f"Cổ đông lớn nhất nắm {top1}% — ảnh hưởng đáng kể lên quyết định")
            score = max(score, 1)

    if top5 is not None and top5 >= 70:
        flags.append(f"Top 5 cổ đông nắm {top5}% — tập trung sở hữu cao, thanh khoản thực tế thấp")
        score = max(score, 2)

    if hhi is not None and hhi >= 2500:
        flags.append(f"HHI top 5 = {hhi} — mức tập trung rất cao (ngưỡng: 2500)")
        score = max(score, 2)
    elif hhi is not None and hhi >= 1500:
        flags.append(f"HHI top 5 = {hhi} — mức tập trung trung bình-cao")
        score = max(score, 1)

    if state is not None and state >= 51:
        flags.append(f"Nhà nước nắm {state}% — hạn chế tối ưu hóa lợi nhuận, rủi ro chính sách")
        score = max(score, 1)

    severity_map = {0: "LOW", 1: "MEDIUM", 2: "HIGH", 3: "CRITICAL"}
    return {"score": score, "severity": severity_map[score], "flags": flags}


def score_dilution_risk(shares_trend: dict, events: list) -> dict:
    flags = []
    score = 0

    current = shares_trend.get("current_m")
    ago_1y = shares_trend.get("1y_ago_m")
    dilution_pct = shares_trend.get("dilution_pct")

    if dilution_pct is not None:
        if dilution_pct >= 15:
            flags.append(f"Pha loãng {dilution_pct}%/năm — rất cao, xói mòn giá trị cổ đông mạnh")
            score = max(score, 3)
        elif dilution_pct >= 5:
            flags.append(f"Pha loãng {dilution_pct}%/năm — đáng chú ý, cần theo dõi EPS diluted")
            score = max(score, 2)
        elif dilution_pct >= 2:
            flags.append(f"Pha loãng {dilution_pct}%/năm — nhẹ")
            score = max(score, 1)
    elif current and not ago_1y:
        flags.append("Không có dữ liệu lịch sử shares outstanding để tính tốc độ pha loãng [missing_data]")

    # Check events for dilution signals
    dilution_keywords = ["phát hành", "esop", "chuyển đổi", "tăng vốn", "niêm yết bổ sung"]
    for ev in events:
        if ev.get("is_risky") and any(k in (ev.get("type", "") + ev.get("detail", "")).lower() for k in dilution_keywords):
            flags.append(f"Sự kiện pha loãng: [{ev.get('date', '?')}] {ev.get('type', '')} — {ev.get('detail', '')[:80]}")
            score = max(score, 2)
            break

    severity_map = {0: "LOW", 1: "LOW", 2: "MEDIUM", 3: "HIGH"}
    return {"score": score, "severity": severity_map[score], "flags": flags}


def score_debt_risk(debt: dict, industry: str) -> dict:
    flags = []
    score = 0

    de = debt.get("de_ratio")
    coverage = debt.get("coverage")
    net_debt = debt.get("net_debt_b")
    total_debt = debt.get("total_debt_b")

    # Industry-adjusted thresholds
    is_bank = industry == "BANK"
    de_high = 15.0 if is_bank else 3.0
    de_medium = 8.0 if is_bank else 1.5
    cov_low = 1.5
    cov_danger = 1.0

    if de is not None:
        if de >= de_high:
            flags.append(f"D/E = {de}× — vượt ngưỡng cao {'(ngân hàng)' if is_bank else ''}")
            score = max(score, 3)
        elif de >= de_medium:
            flags.append(f"D/E = {de}× — mức trung bình-cao, cần theo dõi")
            score = max(score, 2)
        elif de >= 1.0 and not is_bank:
            flags.append(f"D/E = {de}× — đòn bẩy vừa phải")
            score = max(score, 1)

    if coverage is not None:
        if coverage <= cov_danger:
            flags.append(f"Interest coverage = {coverage}× — NGUY HIỂM, EBIT gần không đủ trả lãi")
            score = max(score, 3)
        elif coverage <= cov_low:
            flags.append(f"Interest coverage = {coverage}× — mỏng, dễ tổn thương khi lợi nhuận giảm")
            score = max(score, 2)
        elif coverage <= 3.0:
            flags.append(f"Interest coverage = {coverage}× — đủ nhưng chưa thoải mái")
            score = max(score, 1)
    elif not is_bank:
        flags.append("Interest coverage không tính được [missing_data]")
        score = max(score, 1)

    if net_debt and net_debt > 0 and not is_bank:
        flags.append(f"Net debt = {net_debt}B VND — công ty đang ở vị thế net debt")

    severity_map = {0: "LOW", 1: "LOW", 2: "MEDIUM", 3: "HIGH"}
    return {"score": score, "severity": severity_map[score], "flags": flags}


def score_audit_risk(overview: dict, events: list) -> dict:
    flags = []
    score = 0

    auditor = overview.get("auditor")
    if not auditor:
        flags.append("Không có thông tin kiểm toán viên [missing_data]")
        score = max(score, 1)
    else:
        # Big 4 / reputable check
        big4 = ["deloitte", "kpmg", "pwc", "ernst", "ey", "e&y", "baker tilly", "grant thornton", "bdo"]
        is_big4 = any(b in auditor.lower() for b in big4)
        if not is_big4:
            flags.append(f"Kiểm toán viên '{auditor}' — không phải Big 4 / công ty lớn, độ tin cậy thấp hơn")
            score = max(score, 1)

    # Check events for audit-related flags
    audit_keywords = ["ngoại trừ", "going concern", "từ chối", "thay kiểm toán", "qualified opinion"]
    for ev in events:
        detail_text = (ev.get("type", "") + " " + ev.get("detail", "")).lower()
        if any(k in detail_text for k in audit_keywords):
            flags.append(f"Cờ đỏ kiểm toán: [{ev.get('date', '?')}] {ev.get('detail', '')[:100]}")
            score = max(score, 3)

    severity_map = {0: "LOW", 1: "MEDIUM", 2: "HIGH", 3: "CRITICAL"}
    return {"score": score, "severity": severity_map[min(score, 3)], "flags": flags}


def score_legal_risk(events: list) -> dict:
    flags = []
    score = 0

    legal_keywords = ["vi phạm", "điều tra", "truy tố", "cảnh báo", "tạm dừng", "hủy niêm yết",
                      "phạt", "nhắc nhở", "giải trình", "ubcknn", "hose", "hnx yêu cầu"]
    for ev in events:
        detail_text = (ev.get("type", "") + " " + ev.get("detail", "")).lower()
        if any(k in detail_text for k in legal_keywords):
            flags.append(f"Sự kiện pháp lý: [{ev.get('date', '?')}] {ev.get('detail', '')[:120]}")
            if any(k in detail_text for k in ["điều tra", "truy tố", "hủy niêm yết", "tạm dừng"]):
                score = max(score, 3)
            else:
                score = max(score, 2)

    if not flags:
        flags.append("Không phát hiện sự kiện pháp lý qua API events [cần bổ sung news crawl]")

    severity_map = {0: "LOW", 1: "LOW", 2: "MEDIUM", 3: "HIGH"}
    return {"score": score, "severity": severity_map[min(score, 3)], "flags": flags}


def identify_thesis_breakers(risk_matrix: list) -> list:
    breakers = []
    for item in risk_matrix:
        sev = item.get("severity", "LOW")
        prob = item.get("probability", "LOW")
        if sev in ("HIGH", "CRITICAL") and prob in ("HIGH", "MEDIUM"):
            breakers.append({
                "risk": item["risk"],
                "severity": sev,
                "probability": prob,
                "mechanism": item.get("mechanism", "Xem chi tiết section tương ứng"),
                "early_signal": item.get("early_signal", "[missing_data]"),
            })
    return breakers


def build_risk_matrix(own_risk, dil_risk, debt_risk, audit_risk, legal_risk) -> list:
    def prob_from_score(score):
        if score >= 3: return "HIGH"
        if score >= 2: return "MEDIUM"
        return "LOW"

    matrix = []

    if own_risk["flags"]:
        matrix.append({
            "risk": "Governance / Tập trung quyền lực",
            "severity": own_risk["severity"],
            "probability": prob_from_score(own_risk["score"]),
            "mechanism": "Cổ đông kiểm soát ưu tiên lợi ích riêng, minority bị thiệt",
            "early_signal": "Giao dịch bên liên quan tăng, thay đổi ban lãnh đạo đột ngột",
        })

    if dil_risk["flags"] and dil_risk["score"] >= 1:
        matrix.append({
            "risk": "Pha loãng EPS / Phát hành thêm cổ phiếu",
            "severity": dil_risk["severity"],
            "probability": prob_from_score(dil_risk["score"]),
            "mechanism": "Phát hành mới làm loãng EPS, giá cổ phiếu chịu áp lực",
            "early_signal": "Nghị quyết ĐHCĐ phê duyệt phát hành, nhu cầu vốn lớn",
        })

    if debt_risk["flags"] and debt_risk["score"] >= 1:
        matrix.append({
            "risk": "Rủi ro nợ vay / Refinancing",
            "severity": debt_risk["severity"],
            "probability": prob_from_score(debt_risk["score"]),
            "mechanism": "Lãi suất tăng hoặc lợi nhuận giảm → không đủ trả lãi → restructure/default",
            "early_signal": "Coverage giảm dưới 2×, tăng vay ngắn hạn, trái phiếu đến hạn",
        })

    if audit_risk["score"] >= 2:
        matrix.append({
            "risk": "Rủi ro kiểm toán / Chất lượng BCTC",
            "severity": audit_risk["severity"],
            "probability": "MEDIUM",
            "mechanism": "Ý kiến ngoại trừ → nhà đầu tư mất tin, kiểm soát nội bộ yếu",
            "early_signal": "Thay kiểm toán viên, chậm công bố BCTC, điều chỉnh số liệu hồi tố",
        })

    if legal_risk["score"] >= 2:
        matrix.append({
            "risk": "Rủi ro pháp lý / Điều tra / Hủy niêm yết",
            "severity": legal_risk["severity"],
            "probability": "MEDIUM",
            "mechanism": "Điều tra → phạt, tạm dừng giao dịch, hủy niêm yết",
            "early_signal": "Công văn yêu cầu giải trình, cảnh báo từ HoSE/HNX",
        })

    return matrix


def generate_report(snapshot_path: str) -> dict:
    with open(snapshot_path, encoding="utf-8") as f:
        snap = json.load(f)

    ticker = snap["ticker"]
    industry = snap.get("industry", "UNKNOWN")
    overview = snap.get("overview", {})
    ownership = snap.get("ownership", {})
    shareholders = snap.get("shareholders", [])
    events = snap.get("events", [])
    shares_trend = snap.get("shares_trend", {})
    debt = snap.get("debt_snapshot", {})
    data_warnings = snap.get("warnings", [])

    own_risk = score_ownership_risk(ownership, shareholders)
    dil_risk = score_dilution_risk(shares_trend, events)
    debt_r = score_debt_risk(debt, industry)
    audit_r = score_audit_risk(overview, events)
    legal_r = score_legal_risk(events)

    risk_matrix = build_risk_matrix(own_risk, dil_risk, debt_r, audit_r, legal_r)
    thesis_breakers = identify_thesis_breakers(risk_matrix)

    risky_events = [e for e in events if e.get("is_risky")]

    high_count = sum(1 for r in risk_matrix if r["severity"] in ("HIGH", "CRITICAL"))
    med_count = sum(1 for r in risk_matrix if r["severity"] == "MEDIUM")

    report = {
        "ticker": ticker,
        "date": snap["date"],
        "industry": industry,
        "risk_summary": {
            "total_risks": len(risk_matrix),
            "high_severity": high_count,
            "medium_severity": med_count,
            "thesis_breakers": len(thesis_breakers),
        },
        "ownership_risk": {
            "score": own_risk["score"],
            "severity": own_risk["severity"],
            "top1_pct": ownership.get("top1_pct"),
            "top5_pct": ownership.get("top5_pct"),
            "state_pct": ownership.get("state_pct"),
            "foreign_pct": ownership.get("foreign_pct"),
            "hhi_top5": ownership.get("hhi_top5"),
            "flags": own_risk["flags"],
        },
        "dilution_risk": {
            "score": dil_risk["score"],
            "severity": dil_risk["severity"],
            "current_shares_m": shares_trend.get("current_m"),
            "dilution_pct_1y": shares_trend.get("dilution_pct"),
            "flags": dil_risk["flags"],
        },
        "debt_risk": {
            "score": debt_r["score"],
            "severity": debt_r["severity"],
            "de_ratio": debt.get("de_ratio"),
            "coverage": debt.get("coverage"),
            "net_debt_b": debt.get("net_debt_b"),
            "total_debt_b": debt.get("total_debt_b"),
            "flags": debt_r["flags"],
        },
        "audit_risk": {
            "score": audit_r["score"],
            "severity": audit_r["severity"],
            "auditor": overview.get("auditor"),
            "flags": audit_r["flags"],
        },
        "legal_risk": {
            "score": legal_r["score"],
            "severity": legal_r["severity"],
            "flags": legal_r["flags"],
        },
        "events_alerts": [
            {"date": e["date"], "type": e["type"], "detail": e["detail"]}
            for e in risky_events[:5]
        ],
        "shareholders_top5": shareholders[:5],
        "risk_matrix": risk_matrix,
        "thesis_breakers": thesis_breakers,
        "data_warnings": data_warnings,
    }

    return report


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--snapshot", required=True)
    args = parser.parse_args()

    snapshot_path = args.snapshot
    if not Path(snapshot_path).exists():
        # Try relative to SKILL_DIR
        alt = SKILL_DIR / snapshot_path
        if alt.exists():
            snapshot_path = str(alt)
        else:
            print(f"[ERROR] Snapshot not found: {snapshot_path}", file=sys.stderr)
            sys.exit(1)

    report = generate_report(snapshot_path)

    ticker = report["ticker"]
    date_str = report["date"]
    out_path = OUTPUT_DIR / f"risk_report_{ticker}_{date_str}.md"

    # Write markdown output
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(f"# Risk Report: {ticker} — {date_str}\n\n")
        f.write("```json\n")
        f.write(json.dumps(report, ensure_ascii=False, indent=2))
        f.write("\n```\n")

    print(f"Report saved: {out_path}")
    print("---SNAPSHOT_JSON---")
    print(json.dumps(report, ensure_ascii=False, separators=(",", ":")))


if __name__ == "__main__":
    main()
