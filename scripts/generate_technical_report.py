#!/usr/bin/env python3
"""Generate technical analysis report from snapshot.

Usage:
  python generate_technical_report.py --snapshot data/technical_snapshot_HPG_2026-05-15.json

Output:
  - Saves markdown to output/technical_report_{ticker}_{date}.md
  - Prints markdown + ---SNAPSHOT_JSON--- + compact JSON to stdout
"""

import argparse
import json
import math
import sys
from pathlib import Path

SKILL_DIR = Path(__file__).parent.parent
OUTPUT_DIR = SKILL_DIR / "output"
OUTPUT_DIR.mkdir(exist_ok=True)

ZONE_EMOJI = {
    "ACCUMULATION": "🟢",
    "WATCH":        "🟡",
    "DISTRIBUTION": "🔴",
}

SIGNAL_LABEL = {
    "BULLISH":  "BULLISH",
    "NEUTRAL":  "NEUTRAL",
    "BEARISH":  "BEARISH",
    "CONFIRM":  "CONFIRM",
    "DIVERGE":  "DIVERGE",
    "INFLOW":   "INFLOW",
    "OUTFLOW":  "OUTFLOW",
}


# ── Formatting helpers ──────────────────────────────────────────────────────

def _v(val, na="N/A"):
    if val is None:
        return na
    try:
        if math.isnan(float(val)) or math.isinf(float(val)):
            return na
    except (TypeError, ValueError):
        return na
    return val


def fmt_price(val, na="N/A"):
    v = _v(val, None)
    if v is None:
        return na
    return f"{int(float(v)):,}"


def fmt_pct(val, na="N/A"):
    v = _v(val, None)
    if v is None:
        return na
    f = float(v)
    sign = "+" if f >= 0 else ""
    return f"{sign}{f:.1f}%"


def fmt_vol(val, na="N/A"):
    """Format volume in millions."""
    v = _v(val, None)
    if v is None:
        return na
    return f"{float(v)/1e6:.1f}M"


def fmt_net(val, na="[missing_data]"):
    """Format net money flow in billions VND."""
    v = _v(val, None)
    if v is None:
        return na
    b = float(v) / 1e9
    sign = "+" if b >= 0 else ""
    return f"{sign}{b:.1f} B VND"


def fmt_x(val, na="N/A"):
    v = _v(val, None)
    if v is None:
        return na
    return f"{float(v):.2f}×"


def rsi_label(val) -> str:
    if val is None:
        return "N/A"
    v = float(val)
    if v < 30:
        return f"{v:.1f} (Oversold)"
    if v > 70:
        return f"{v:.1f} (Overbought)"
    if v < 45:
        return f"{v:.1f} (Weak)"
    if v > 55:
        return f"{v:.1f} (Bullish)"
    return f"{v:.1f} (Neutral)"


def macd_label(hist) -> str:
    if hist is None:
        return "N/A"
    v = float(hist)
    if v > 0:
        return "Bullish" if v > abs(v) * 0.1 else "Neutral"
    return "Bearish"


def stoch_label(k) -> str:
    if k is None:
        return "N/A"
    v = float(k)
    if v < 20:
        return "Oversold"
    if v > 80:
        return "Overbought"
    return "Neutral"


def ma_cross_label(ma20, ma50) -> str:
    if ma20 is None or ma50 is None:
        return "N/A"
    ratio = float(ma20) / float(ma50)
    if ratio > 1.005:
        return "Golden Cross zone"
    if ratio < 0.995:
        return "Death Cross zone"
    return "Neutral"


def obv_label(trend: str) -> str:
    return {"rising": "Rising ↑", "falling": "Falling ↓", "flat": "Flat →"}.get(trend, "N/A")


def trend_3m_label(chg_3m) -> str:
    if chg_3m is None:
        return "đi ngang"
    v = float(chg_3m)
    if v > 10:
        return "tăng mạnh"
    if v > 3:
        return "tăng nhẹ"
    if v < -10:
        return "giảm mạnh"
    if v < -3:
        return "giảm nhẹ"
    return "đi ngang"


# ── Section builders ────────────────────────────────────────────────────────

def section_price_trend(snap: dict) -> str:
    ticker  = snap.get("ticker", "")
    dt      = snap.get("date", "")
    p       = snap.get("price", {})
    current = p.get("current")
    h52     = p.get("high_52w")
    l52     = p.get("low_52w")

    vs_high = p.get("vs_52w_high_pct")
    trend3m = trend_3m_label(p.get("change_pct_3m"))

    lines = [
        f"## price_trend [FACT]",
        f"{ticker} — {dt} | Giá: {fmt_price(current)} VND | "
        f"1D: {fmt_pct(p.get('change_pct_1d'))} | "
        f"1M: {fmt_pct(p.get('change_pct_1m'))} | "
        f"3M: {fmt_pct(p.get('change_pct_3m'))}",
        f"52W High: {fmt_price(h52)} | 52W Low: {fmt_price(l52)} | vs 52W High: {fmt_pct(vs_high)}",
        f"[FACT] Xu hướng 3 tháng: {trend3m} ({fmt_pct(p.get('change_pct_3m'))}) — "
        f"giá hiện tại cách đỉnh 52 tuần {fmt_pct(vs_high)}.",
    ]
    return "\n".join(lines)


def section_trend_indicators(snap: dict) -> str:
    ind = snap.get("indicators", {})
    p   = snap.get("price", {})
    sig = snap.get("signals", {})
    current = p.get("current") or 0

    ma20  = ind.get("ma20")
    ma50  = ind.get("ma50")
    ma200 = ind.get("ma200")
    ema20 = ind.get("ema20")

    def vs_pct(curr, ma):
        if curr and ma:
            return fmt_pct((curr - ma) / ma * 100)
        return "N/A"

    trend_verdict = sig.get("trend", "NEUTRAL")
    cross = ma_cross_label(ma20, ma50)

    if trend_verdict == "BULLISH":
        reason = f"Giá ({fmt_price(current)}) > MA50 ({fmt_price(ma50)}) > MA200 ({fmt_price(ma200)}) — uptrend cấu trúc."
    elif trend_verdict == "BEARISH":
        reason = f"Giá ({fmt_price(current)}) < MA50 ({fmt_price(ma50)}) < MA200 ({fmt_price(ma200)}) — downtrend cấu trúc."
    else:
        reason = f"Giá ({fmt_price(current)}) nằm giữa MA50 và MA200 — transition zone, chưa rõ xu hướng."

    lines = [
        "## trend_indicators [FACT + CONCLUSION]",
        f"MA20: {fmt_price(ma20)} | MA50: {fmt_price(ma50)} | MA200: {fmt_price(ma200)} | EMA20: {fmt_price(ema20)}",
        f"Giá vs MA20: {vs_pct(current, ma20)} | Giá vs MA200: {vs_pct(current, ma200)}",
        f"MA20 vs MA50: {cross}",
        f"[CONCLUSION]: Xu hướng = **{trend_verdict}** — {reason}",
    ]
    return "\n".join(lines)


def section_momentum_signals(snap: dict) -> str:
    ind = snap.get("indicators", {})
    sig = snap.get("signals", {})

    rsi   = ind.get("rsi14")
    macd  = ind.get("macd")
    msig  = ind.get("macd_signal")
    mhist = ind.get("macd_hist")
    sk    = ind.get("stoch_k")
    sd    = ind.get("stoch_d")

    momentum = sig.get("momentum", "NEUTRAL")
    if momentum == "BULLISH":
        concl = "Momentum = **MẠNH** — RSI và MACD đồng thuận hướng tăng."
    elif momentum == "BEARISH":
        concl = "Momentum = **YẾU** — RSI thấp hoặc MACD histogram âm."
    else:
        concl = "Momentum = **TRUNG TÍNH** — chưa có tín hiệu rõ ràng."

    lines = [
        "## momentum_signals [FACT + CONCLUSION]",
        f"RSI(14): {rsi_label(rsi)}",
        f"MACD(12,26,9): {fmt_price(macd)} | Signal: {fmt_price(msig)} | "
        f"Histogram: {fmt_price(mhist)} [{macd_label(mhist)}]",
        f"Stoch(14,3): K={fmt_price(sk)} D={fmt_price(sd)} [{stoch_label(sk)}]",
        f"[CONCLUSION]: {concl}",
    ]
    return "\n".join(lines)


def section_volume_analysis(snap: dict) -> str:
    ind = snap.get("indicators", {})
    sig = snap.get("signals", {})

    vol_t = ind.get("vol_today")
    vol_m = ind.get("vol_ma20")
    vol_r = ind.get("vol_ratio")
    obv   = ind.get("obv_trend", "flat")

    volume = sig.get("volume", "NEUTRAL")
    if volume == "CONFIRM":
        concl = "Volume = **XÁC NHẬN xu hướng** — thanh khoản cao hỗ trợ chiều giá."
    elif volume == "DIVERGE":
        concl = "Volume = **MÂU THUẪN** — thanh khoản cao nhưng ngược chiều giá, cẩn thận."
    else:
        concl = "Volume = **TRUNG TÍNH** — thanh khoản bình thường, không có tín hiệu mạnh."

    lines = [
        "## volume_analysis [FACT + CONCLUSION]",
        f"Volume hôm nay: {fmt_vol(vol_t)} | MA20 Vol: {fmt_vol(vol_m)} | Tỷ lệ: {fmt_x(vol_r)}",
        f"OBV trend: {obv_label(obv)}",
        f"[CONCLUSION]: {concl}",
    ]
    return "\n".join(lines)


def section_money_flow(snap: dict) -> str:
    mf  = snap.get("money_flow", {})
    sig = snap.get("signals", {})

    net  = mf.get("foreign_net_10d")
    buy  = mf.get("foreign_buy_10d")
    sell = mf.get("foreign_sell_10d")
    own  = mf.get("foreign_own_pct")
    room = mf.get("room_remaining_pct")

    mf_signal = sig.get("money_flow", "NEUTRAL")
    if mf_signal == "INFLOW":
        concl = "Khối ngoại = **MUA RÒNG** — dòng tiền nước ngoài hỗ trợ giá ngắn hạn."
    elif mf_signal == "OUTFLOW":
        concl = "Khối ngoại = **BÁN RÒNG** — áp lực bán từ khối ngoại tạo headwind ngắn hạn."
    else:
        concl = "Khối ngoại = **TRUNG TÍNH** — không có tín hiệu dòng tiền nước ngoài rõ ràng."

    own_str  = f"{own:.1f}%" if own is not None else "[missing_data]"
    room_str = f"{room:.1f}%" if room is not None else "N/A"
    buy_str  = fmt_net(buy, "N/A")
    sell_str = fmt_net(sell, "N/A")

    lines = [
        "## money_flow [FACT + CONCLUSION]",
        f"Khối ngoại 10D: Net {fmt_net(net)} (Mua {buy_str} / Bán {sell_str})",
        f"Sở hữu NN: {own_str} | Room còn: {room_str}",
        f"[CONCLUSION]: {concl}",
    ]
    return "\n".join(lines)


def section_key_levels(snap: dict) -> str:
    sr  = snap.get("support_resistance", {})
    ind = snap.get("indicators", {})
    p   = snap.get("price", {})
    current = float(p.get("current") or 0)

    r1 = sr.get("resistance1")
    r2 = sr.get("resistance2")
    s1 = sr.get("support1")
    s2 = sr.get("support2")
    pv = sr.get("pivot")
    bbu = ind.get("bb_upper")
    bbl = ind.get("bb_lower")
    atr = ind.get("atr14")

    def rr(target):
        if target is None or current == 0:
            return "N/A"
        return fmt_pct((target - current) / current * 100)

    lines = [
        "## key_levels [FACT]",
        f"Kháng cự 1: {fmt_price(r1)} | Kháng cự 2: {fmt_price(r2)}",
        f"Hỗ trợ 1:   {fmt_price(s1)} | Hỗ trợ 2:   {fmt_price(s2)}",
        f"Pivot: {fmt_price(pv)} | BB Upper: {fmt_price(bbu)} | BB Lower: {fmt_price(bbl)} | ATR(14): {fmt_price(atr)}",
        f"R/R từ giá hiện tại: {rr(r1)} → R1 / {rr(s1)} → S1",
    ]
    return "\n".join(lines)


def section_timing_signal(snap: dict) -> str:
    sig  = snap.get("signals", {})
    zone = sig.get("timing_zone", "WATCH")
    emoji = ZONE_EMOJI.get(zone, "🟡")

    trend   = sig.get("trend", "NEUTRAL")
    mom     = sig.get("momentum", "NEUTRAL")
    vol     = sig.get("volume", "NEUTRAL")
    mf      = sig.get("money_flow", "NEUTRAL")

    sr  = snap.get("support_resistance", {})
    p   = snap.get("price", {})
    current = float(p.get("current") or 0)
    s1  = sr.get("support1")
    r1  = sr.get("resistance1")

    s1_str = fmt_price(s1)
    r1_str = fmt_price(r1)

    if zone == "ACCUMULATION":
        concl = (f"Giá hiện tại ({fmt_price(current)}) nằm trong vùng tích lũy — "
                 f"đa số tín hiệu thuận chiều. "
                 f"Signal đảo chiều sang WATCH nếu RSI vượt 70 hoặc MACD histogram đổi âm.")
    elif zone == "DISTRIBUTION":
        concl = (f"Giá hiện tại ({fmt_price(current)}) trong vùng phân phối — "
                 f"đa số tín hiệu tiêu cực. "
                 f"Signal đảo chiều sang WATCH nếu giá giữ vững trên S1 ({s1_str}) và volume giảm.")
    else:
        concl = (f"Giá hiện tại ({fmt_price(current)}) giữa S1 ({s1_str}) và R1 ({r1_str}) — "
                 f"tín hiệu hỗn hợp. "
                 f"Chờ breakout khỏi R1 với volume > 1.5× MA20 hoặc giữ vững S1 để xác nhận hướng.")

    lines = [
        "## timing_signal [CONCLUSION]",
        f"⏱ Timing Zone: {emoji} **{zone}**",
        "| Signal     | Verdict   |",
        "|------------|-----------|",
        f"| Trend      | {trend}   |",
        f"| Momentum   | {mom} |",
        f"| Volume     | {vol} |",
        f"| Money Flow | {mf}  |",
        f"[CONCLUSION] {concl}",
    ]
    return "\n".join(lines)


# ── Main builder ────────────────────────────────────────────────────────────

def build_markdown(snap: dict) -> str:
    ticker   = snap.get("ticker", "UNKNOWN")
    dt       = snap.get("date", "")
    warnings = snap.get("data_warnings", [])

    sections = [
        f"# Phân tích Kỹ thuật: {ticker} ({dt})\n",
        section_price_trend(snap),
        "",
        section_trend_indicators(snap),
        "",
        section_momentum_signals(snap),
        "",
        section_volume_analysis(snap),
        "",
        section_money_flow(snap),
        "",
        section_key_levels(snap),
        "",
        section_timing_signal(snap),
    ]

    if warnings:
        sections += ["", "---", "_Cảnh báo data: " + " | ".join(warnings) + "_"]

    return "\n".join(sections)


def main():
    parser = argparse.ArgumentParser(description="Generate technical analysis report")
    parser.add_argument("--snapshot", required=True, help="Path to technical snapshot JSON")
    args = parser.parse_args()

    snap_path = Path(args.snapshot)
    if not snap_path.exists():
        print(f"[ERROR] Snapshot not found: {snap_path}", file=sys.stderr)
        sys.exit(1)

    snap = json.loads(snap_path.read_text(encoding="utf-8"))
    ticker = snap.get("ticker", "UNKNOWN")
    dt     = snap.get("date", "unknown")

    md = build_markdown(snap)

    out_path = OUTPUT_DIR / f"technical_report_{ticker}_{dt}.md"
    out_path.write_text(md, encoding="utf-8")

    compact_json = json.dumps(snap, ensure_ascii=False, separators=(",", ":"))
    print(md)
    print("---SNAPSHOT_JSON---")
    print(compact_json)


if __name__ == "__main__":
    main()
