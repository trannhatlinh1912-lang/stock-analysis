#!/usr/bin/env python3
"""Decision framework — turn indicator snapshot into a structured technical
decision for a Vietnamese equity.

Reads the indicator table produced by ``indicator_engine.py`` (typically
``data/{SYMBOL}_indicators.csv``), inspects the latest row, classifies the
technical state under a fixed priority order, computes a 0–100 confidence
score, derives entry / stop / support / resistance levels strictly from the
columns present, and emits:

- ``data/{SYMBOL}_decision_snapshot.json``
- ``reports/{SYMBOL}_technical_decision.md``

No hardcoded ticker symbols. No hardcoded prices.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = REPO_ROOT / "data"
REPORTS_DIR = REPO_ROOT / "reports"
DATA_DIR.mkdir(exist_ok=True)
REPORTS_DIR.mkdir(exist_ok=True)


# ---------------------------------------------------------------------------
# Loading + helpers
# ---------------------------------------------------------------------------


def load_indicators(csv_path: Path) -> pd.DataFrame:
    df = pd.read_csv(csv_path)
    df.columns = [c.lower() for c in df.columns]
    if "date" in df.columns:
        df["date"] = pd.to_datetime(df["date"])
    elif "time" in df.columns:
        df["date"] = pd.to_datetime(df["time"])
    else:
        raise ValueError(f"no date column. cols={list(df.columns)}")
    df = df.sort_values("date").reset_index(drop=True)
    if len(df) == 0:
        raise ValueError(f"empty CSV: {csv_path}")
    return df


def _val(row: pd.Series, key: str) -> float | None:
    """Return float(row[key]) or None if missing/NaN/non-numeric."""
    if key not in row.index:
        return None
    v = row[key]
    if v is None:
        return None
    if isinstance(v, str):
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    if math.isnan(f) or math.isinf(f):
        return None
    return f


def _str(row: pd.Series, key: str) -> str | None:
    if key not in row.index:
        return None
    v = row[key]
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return None
    return str(v)


def _round_to(x: float, step: int) -> float:
    """Round x UP to the next multiple of step."""
    return float(math.ceil(x / step) * step)


# ---------------------------------------------------------------------------
# Rules — state classification
# ---------------------------------------------------------------------------


def _is_breakout_confirmed(r: pd.Series) -> bool:
    close = _val(r, "close")
    s20 = _val(r, "sma20")
    s50 = _val(r, "sma50")
    s200 = _val(r, "sma200")
    vr = _val(r, "vol_ratio")
    ret1 = _val(r, "ret_1d")
    mh = _val(r, "macd_hist")
    if any(v is None for v in (close, s20, s50, s200, vr, ret1, mh)):
        return False
    return (
        close > s20 and close > s50 and close > s200
        and vr >= 1.5 and ret1 > 2.0 and mh > 0.0
    )


def _is_breakout_with_exhaustion(r: pd.Series) -> bool:
    if not _is_breakout_confirmed(r):
        return False
    bb = _str(r, "bb_position")
    sk = _val(r, "stoch_k")
    vr = _val(r, "vol_ratio")
    if bb is None or sk is None or vr is None:
        return False
    return bb == "above_upper" and sk >= 90.0 and vr >= 2.0


def _is_bullish_trend_confirmed(r: pd.Series) -> bool:
    close = _val(r, "close")
    s20 = _val(r, "sma20")
    s50 = _val(r, "sma50")
    s100 = _val(r, "sma100")
    s200 = _val(r, "sma200")
    mh = _val(r, "macd_hist")
    vr = _val(r, "vol_ratio")
    if any(v is None for v in (close, s20, s50, s100, s200, mh, vr)):
        return False
    return (
        close > s20 > s50 > s100 > s200
        and mh > 0.0 and vr >= 1.0
    )


def _is_accumulation(r: pd.Series) -> bool:
    close = _val(r, "close")
    s20 = _val(r, "sma20")
    s50 = _val(r, "sma50")
    atr = _val(r, "atr14")
    vr = _val(r, "vol_ratio")
    mh = _val(r, "macd_hist")
    rsi = _val(r, "rsi14")
    bb = _str(r, "bb_position")
    if any(v is None for v in (close, atr, vr)):
        return False
    # close gần SMA20 hoặc SMA50 trong vòng 1 ATR
    near_sma = False
    if s20 is not None and abs(close - s20) <= atr:
        near_sma = True
    if s50 is not None and abs(close - s50) <= atr:
        near_sma = True
    if not near_sma:
        return False
    if not (0.8 <= vr <= 1.5):
        return False
    momentum_ok = False
    if mh is not None and mh >= 0.0:
        momentum_ok = True
    if rsi is not None and 45.0 <= rsi <= 60.0:
        momentum_ok = True
    if not momentum_ok:
        return False
    if bb == "above_upper":
        return False
    return True


def _is_distribution(r: pd.Series) -> bool:
    close = _val(r, "close")
    s20 = _val(r, "sma20")
    mh = _val(r, "macd_hist")
    cmf = _val(r, "cmf20")
    obv_sl = _val(r, "obv_slope_20d")
    if any(v is None for v in (close, s20, mh, cmf, obv_sl)):
        return False
    return close < s20 and mh < 0.0 and cmf < 0.0 and obv_sl < 0.0


def determine_state(r: pd.Series) -> str:
    """Return technical_state under the fixed priority order."""
    if _is_distribution(r):
        return "DISTRIBUTION"
    if _is_breakout_with_exhaustion(r):
        return "BREAKOUT_WITH_EXHAUSTION_RISK"
    if _is_bullish_trend_confirmed(r):
        return "BULLISH_TREND_CONFIRMED"
    if _is_breakout_confirmed(r):
        return "BREAKOUT_CONFIRMED"
    if _is_accumulation(r):
        return "ACCUMULATION"
    return "WATCH"


# ---------------------------------------------------------------------------
# Key risks (independent of indicator_engine to keep this module self-contained)
# ---------------------------------------------------------------------------


def compute_key_risks(r: pd.Series) -> list[str]:
    risks: list[str] = []

    close = _val(r, "close")
    s100 = _val(r, "sma100")
    s20 = _val(r, "sma20")
    s50 = _val(r, "sma50")
    s200 = _val(r, "sma200")
    bb = _str(r, "bb_position")
    vr = _val(r, "vol_ratio")
    sk = _val(r, "stoch_k")
    ret1 = _val(r, "ret_1d")
    rsi = _val(r, "rsi14")
    cmf = _val(r, "cmf20")
    mh = _val(r, "macd_hist")
    dist_s100 = _val(r, "dist_sma100_pct")
    dist_52h = _val(r, "dist_52w_high_pct")
    dist_52l = _val(r, "dist_52w_low_pct")

    # Breakout exhaustion
    if (
        bb == "above_upper"
        and vr is not None and vr >= 2.0
        and sk is not None and sk >= 90.0
        and ret1 is not None and ret1 >= 5.0
    ):
        risks.append(
            "breakout_exhaustion_risk: giá tăng mạnh vượt Bollinger Upper với "
            "volume spike và Stoch quá nóng; rủi ro pullback/throwback 1-5 phiên cao."
        )

    # Near SMA100 resistance
    if (
        close is not None and s100 is not None and close < s100
        and dist_s100 is not None and -2.0 <= dist_s100 <= 0.0
    ):
        risks.append(
            "near_sma100_resistance: giá đang sát dưới SMA100, cần vượt và "
            "giữ trên SMA100 để xác nhận trend trung hạn."
        )

    # Strict MA alignment
    if all(v is not None for v in (close, s20, s50, s100, s200)):
        if not (close > s20 > s50 > s100 > s200):
            risks.append(
                "trend_not_fully_aligned: MA chưa xếp hàng tăng hoàn chỉnh, "
                "xu hướng trung hạn chưa xác nhận."
            )

    # RSI extremes
    if rsi is not None and rsi >= 75:
        risks.append(f"rsi_overbought ({rsi:.1f}): rủi ro pullback ngắn hạn.")
    if rsi is not None and rsi <= 25:
        risks.append(f"rsi_oversold ({rsi:.1f}): bounce hoặc capitulation.")

    # CMF divergence on trend
    if cmf is not None and cmf < -0.05 and close is not None and s50 is not None and close > s50:
        risks.append("cmf_distribution_divergence: giá trên SMA50 nhưng CMF20 âm.")

    # MACD fade
    if mh is not None and mh < 0 and _val(r, "macd") is not None and _val(r, "macd") > 0:
        risks.append("macd_momentum_fade: MACD trên 0 nhưng histogram âm.")

    # 52W proximity
    if dist_52h is not None and dist_52h > -3:
        risks.append("near_52w_high: rủi ro failed breakout.")
    if dist_52l is not None and dist_52l < 5:
        risks.append("near_52w_low: rủi ro tiếp diễn xu hướng giảm.")

    return risks


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------


def compute_score(
    r: pd.Series, key_risks: list[str], state: str
) -> dict[str, int]:
    """Return {raw_score, adjusted_score, final_score}.

    - raw_score: from the base rubric (close vs MA, volume, momentum, money flow).
    - adjusted_score: raw - 5 extra if the GAS-style triple-risk combo is present
      (breakout_exhaustion_risk + near_sma100_resistance + trend_not_fully_aligned).
    - final_score: clamped 0..100 and capped at 68 when state is
      BREAKOUT_WITH_EXHAUSTION_RISK.
    """
    score = 50
    close = _val(r, "close")
    s50 = _val(r, "sma50")
    s100 = _val(r, "sma100")
    s200 = _val(r, "sma200")
    vr = _val(r, "vol_ratio")
    mh = _val(r, "macd_hist")
    obv_sl = _val(r, "obv_slope_20d")
    mfi = _val(r, "mfi14")
    bb = _str(r, "bb_position")
    sk = _val(r, "stoch_k")
    cmf = _val(r, "cmf20")

    if close is not None and s50 is not None and close > s50:
        score += 10
    if close is not None and s200 is not None and close > s200:
        score += 10
    if vr is not None and vr >= 1.5:
        score += 10
    if mh is not None and mh > 0:
        score += 8
    if obv_sl is not None and obv_sl > 0:
        score += 5
    if mfi is not None and 50.0 <= mfi <= 80.0:
        score += 5
    if close is not None and s100 is not None and close < s100:
        score -= 8
    if bb == "above_upper" and sk is not None and sk >= 90.0:
        score -= 8
    if cmf is not None and cmf < 0:
        score -= 5
    if any("trend_not_fully_aligned" in kr for kr in key_risks):
        score -= 5

    raw_score = score

    has_exhaustion = any("breakout_exhaustion_risk" in kr for kr in key_risks)
    has_near_sma100 = any("near_sma100_resistance" in kr for kr in key_risks)
    has_not_aligned = any("trend_not_fully_aligned" in kr for kr in key_risks)
    triple = has_exhaustion and has_near_sma100 and has_not_aligned

    adjusted_score = raw_score - 5 if triple else raw_score

    final_score = adjusted_score
    if state == "BREAKOUT_WITH_EXHAUSTION_RISK":
        final_score = min(final_score, 68)
    final_score = max(0, min(100, int(final_score)))

    return {
        "raw_score": int(raw_score),
        "adjusted_score": int(adjusted_score),
        "final_score": int(final_score),
        "triple_risk_penalty_applied": bool(triple),
        "exhaustion_cap_applied": state == "BREAKOUT_WITH_EXHAUSTION_RISK",
    }


# ---------------------------------------------------------------------------
# Entry strategy + zones + stops + S/R
# ---------------------------------------------------------------------------

ENTRY_STRATEGY = {
    "BREAKOUT_WITH_EXHAUSTION_RISK": (
        "Không mua đuổi tỷ trọng lớn. Ưu tiên chờ retest hoặc chỉ mua thăm dò "
        "nếu vượt kháng cự gần với volume duy trì."
    ),
    "BREAKOUT_CONFIRMED": (
        "Có thể mua thăm dò theo breakout, quản trị rủi ro bằng ATR stop."
    ),
    "BULLISH_TREND_CONFIRMED": (
        "Có thể nắm giữ hoặc gia tăng khi retest hỗ trợ động."
    ),
    "ACCUMULATION": (
        "Có thể tích lũy từng phần gần hỗ trợ."
    ),
    "WATCH": "Chờ xác nhận thêm.",
    "DISTRIBUTION": "Không mua mới.",
}


def compute_entry_zones(r: pd.Series) -> list[dict[str, Any]]:
    """Entry zones: retest_aggressive, retest_standard, breakout_confirmation_zone."""
    zones: list[dict[str, Any]] = []
    close = _val(r, "close")
    s50 = _val(r, "sma50")
    s100 = _val(r, "sma100")
    atr = _val(r, "atr14")
    swing_h20 = _val(r, "swing_high_20")

    def _zone(name: str, a: float, b: float, rationale: str) -> dict[str, Any]:
        lo, hi = (a, b) if a <= b else (b, a)
        return {
            "name": name,
            "lower": round(lo, 4),
            "upper": round(hi, 4),
            "rationale": rationale,
        }

    if close is not None and atr is not None:
        # retest_aggressive: close - 0.5 ATR .. close - 1.0 ATR
        zones.append(_zone(
            "retest_aggressive",
            close - 1.0 * atr,
            close - 0.5 * atr,
            "Pullback nông: close − 0.5 ATR đến close − 1.0 ATR.",
        ))
        # retest_standard: max(SMA50, close - 1.5 ATR) .. close - 1.0 ATR
        lower_candidates = [close - 1.5 * atr]
        if s50 is not None:
            lower_candidates.append(s50)
        lower_std = max(lower_candidates)
        zones.append(_zone(
            "retest_standard",
            lower_std,
            close - 1.0 * atr,
            "Pullback chuẩn: max(SMA50, close − 1.5 ATR) đến close − 1.0 ATR.",
        ))

    if close is not None:
        if s100 is not None and close < s100:
            zones.append({
                "name": "breakout_confirmation_zone",
                "level": round(s100, 4),
                "rationale": "SMA100 — mốc cần đóng cửa trên để xác nhận trend trung hạn.",
            })
        elif swing_h20 is not None:
            zones.append({
                "name": "breakout_confirmation_zone",
                "level": round(swing_h20, 4),
                "rationale": "Swing high 20 phiên — mốc breakout gần nhất.",
            })

    return zones


def compute_stop_loss(r: pd.Series) -> dict[str, Any]:
    """Stops with roles.

    - primary_stop = max(SMA50, ATR_1.5x) when close > SMA50; else ATR_1.5x.
    - hard_stop = ATR_2.0x.
    - structural_stop = swing_low_20 (informational unless within 10% of close).
    """
    out: dict[str, Any] = {}
    close = _val(r, "close")
    atr = _val(r, "atr14")
    s50 = _val(r, "sma50")
    swing_l20 = _val(r, "swing_low_20")

    atr_1_5 = None
    atr_2_0 = None
    if close is not None and atr is not None:
        atr_1_5 = round(close - 1.5 * atr, 4)
        atr_2_0 = round(close - 2.0 * atr, 4)
        out["atr_stop_1_5x"] = atr_1_5
        out["atr_stop_2_0x"] = atr_2_0

    primary_components: list[float] = []
    if atr_1_5 is not None:
        primary_components.append(atr_1_5)
    if close is not None and s50 is not None and close > s50:
        primary_components.append(round(s50, 4))
        out["sma50_stop"] = round(s50, 4)
    if primary_components:
        out["primary_stop"] = round(max(primary_components), 4)
        out["primary_stop_basis"] = (
            "max(SMA50, ATR_1.5x)" if close is not None and s50 is not None and close > s50
            else "ATR_1.5x"
        )

    if atr_2_0 is not None:
        out["hard_stop"] = atr_2_0
        out["hard_stop_basis"] = "ATR_2.0x"

    if swing_l20 is not None and close is not None:
        dist_pct = (close - swing_l20) / close * 100.0
        usable = dist_pct <= 10.0
        out["structural_stop"] = {
            "level": round(swing_l20, 4),
            "basis": "swing_low_20",
            "distance_from_close_pct": round(dist_pct, 2),
            "usable_as_primary": bool(usable),
            "note": (
                "Cách close ≤ 10% — có thể dùng làm stop chính."
                if usable else
                "Cách close > 10% — chỉ tham khảo cấu trúc, không dùng làm stop chính."
            ),
        }
        # Backwards-compatible key kept for callers reading the old field name.
        out["swing_low_20_stop"] = round(swing_l20, 4)

    return out


def _psychological_levels_above(close: float, max_count: int = 3) -> list[float]:
    """Up to `max_count` nearest psychological resistance levels above close.

    Combines next multiples of 5 and of 10 above close, dedups, picks the
    `max_count` smallest values above close.
    """
    candidates: set[float] = set()
    # Walk a few steps in each grid to ensure we have enough above close.
    for step in (5, 10):
        first = math.ceil((close + 1e-9) / step) * step
        for k in range(max_count + 2):
            candidates.add(float(first + k * step))
    above = sorted(v for v in candidates if v > close)
    return above[:max_count]


def compute_resistance_levels(r: pd.Series) -> list[dict[str, Any]]:
    """Resistance levels above close in priority order, deduped at <0.3%.

    Priority (first listed wins on dedup):
        1. psychological (top-3 nearest multiples of 5/10 above close)
        2. SMA100 (only if close < SMA100)
        3. swing_high_20
        4. swing_high_50
        5. 52W high

    Dedup rule: a candidate is dropped if a higher-priority kept level is
    within 0.3% (relative to the candidate).
    """
    close = _val(r, "close")
    if close is None:
        return []

    s100 = _val(r, "sma100")
    swing_h20 = _val(r, "swing_high_20")
    swing_h50 = _val(r, "swing_high_50")
    hi_52w = _val(r, "hi_52w")

    candidates: list[dict[str, Any]] = []
    # 1. Psychological
    for v in _psychological_levels_above(close, max_count=3):
        candidates.append({
            "name": f"psychological_{int(v)}" if v == int(v) else f"psychological_{v}",
            "level": round(v, 4),
            "priority": 1,
        })
    # 2. SMA100 (only if close < SMA100)
    if s100 is not None and close < s100:
        candidates.append({"name": "sma100", "level": round(s100, 4), "priority": 2})
    # 3. swing_high_20
    if swing_h20 is not None and swing_h20 > close:
        candidates.append({"name": "swing_high_20", "level": round(swing_h20, 4), "priority": 3})
    # 4. swing_high_50
    if swing_h50 is not None and swing_h50 > close:
        candidates.append({"name": "swing_high_50", "level": round(swing_h50, 4), "priority": 4})
    # 5. 52W high
    if hi_52w is not None and hi_52w > close:
        candidates.append({"name": "high_52w", "level": round(hi_52w, 4), "priority": 5})

    # Filter out anything not above close.
    candidates = [c for c in candidates if c["level"] > close]
    # Sort by level ascending so adjacent items can be grouped in one pass.
    candidates.sort(key=lambda x: x["level"])

    # Group adjacent levels that are within 0.3% of EACH OTHER (chain).
    # When the relative gap to the most recent member exceeds 0.3%, start a
    # new group. Sources retain their original (priority, level) order inside
    # the group.
    groups: list[list[dict[str, Any]]] = []
    for c in candidates:
        if not groups:
            groups.append([c])
            continue
        prev = groups[-1][-1]
        denom = max(c["level"], prev["level"])
        if denom > 0 and abs(c["level"] - prev["level"]) / denom < 0.003:
            groups[-1].append(c)
        else:
            groups.append([c])

    out: list[dict[str, Any]] = []
    for g in groups:
        g_sorted = sorted(g, key=lambda x: (x["priority"], x["level"]))
        levels = [x["level"] for x in g_sorted]
        sources = [x["name"] for x in g_sorted]
        if len(g_sorted) == 1:
            out.append({
                "name": g_sorted[0]["name"],
                "level": round(g_sorted[0]["level"], 4),
                "type": "single",
                "sources": sources,
            })
        else:
            lo = round(min(levels), 4)
            hi = round(max(levels), 4)
            out.append({
                "name": "confluence_resistance",
                "type": "confluence_resistance",
                "level": f"{lo:.2f}-{hi:.2f}",
                "lower": lo,
                "upper": hi,
                "sources": sources,
            })

    return out


def compute_support_levels(r: pd.Series) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    close = _val(r, "close")
    s20 = _val(r, "sma20")
    s50 = _val(r, "sma50")
    s200 = _val(r, "sma200")
    atr = _val(r, "atr14")
    swing_l20 = _val(r, "swing_low_20")
    swing_l50 = _val(r, "swing_low_50")

    if s50 is not None:
        out.append({"name": "sma50", "level": round(s50, 4)})
    if s20 is not None:
        out.append({"name": "sma20", "level": round(s20, 4)})
    if s200 is not None:
        out.append({"name": "sma200", "level": round(s200, 4)})
    if swing_l20 is not None:
        out.append({"name": "swing_low_20", "level": round(swing_l20, 4)})
    if swing_l50 is not None:
        out.append({"name": "swing_low_50", "level": round(swing_l50, 4)})
    if close is not None and atr is not None:
        out.append({"name": "atr_stop_1_5x", "level": round(close - 1.5 * atr, 4)})

    seen: set[float] = set()
    filtered: list[dict[str, Any]] = []
    for lvl in out:
        v = float(lvl["level"])
        if close is not None and v >= close:
            continue
        key = round(v, 4)
        if key in seen:
            continue
        seen.add(key)
        filtered.append(lvl)
    filtered.sort(key=lambda x: x["level"], reverse=True)  # nearest first
    return filtered


# ---------------------------------------------------------------------------
# Upgrade / downgrade conditions (static per spec)
# ---------------------------------------------------------------------------

UPGRADE_CONDITIONS = [
    "Close trên SMA100 tối thiểu 2-3 phiên.",
    "Volume duy trì >= MA20.",
    "CMF20 chuyển dương.",
    "MACD histogram tiếp tục mở rộng.",
    "MA alignment cải thiện (close > SMA20 > SMA50 > SMA100 > SMA200).",
]

DOWNGRADE_CONDITIONS = [
    "Breakout thất bại nếu close dưới ATR stop 1.5x.",
    "Close quay lại dưới SMA50.",
    "Volume tăng nhưng giá giảm mạnh.",
    "MACD histogram co lại dưới 0.",
    "CMF20 tiếp tục âm.",
]


# ---------------------------------------------------------------------------
# Status strings (for JSON output)
# ---------------------------------------------------------------------------


def _trend_status(r: pd.Series) -> str:
    close = _val(r, "close")
    s20 = _val(r, "sma20")
    s50 = _val(r, "sma50")
    s100 = _val(r, "sma100")
    s200 = _val(r, "sma200")
    if all(v is not None for v in (close, s20, s50, s100, s200)) and close > s20 > s50 > s100 > s200:
        return "bullish_fully_aligned"
    if (
        close is not None and s20 is not None and s50 is not None and s200 is not None
        and close > s20 and s20 > s50 and s50 > s200
    ):
        return "bullish_aligned_partial"
    if (
        close is not None and s50 is not None and s200 is not None
        and close > s200 and s50 > s200
    ):
        return "bullish_partial"
    if s50 is not None and s200 is not None and s50 < s200:
        return "bearish"
    return "sideways_or_unclear"


def _momentum_status(r: pd.Series) -> str:
    rsi = _val(r, "rsi14")
    mh = _val(r, "macd_hist")
    if rsi is None or mh is None:
        return "insufficient_data"
    rsi_lbl = (
        "overbought" if rsi >= 70 else "oversold" if rsi <= 30 else f"neutral_{rsi:.1f}"
    )
    hist_lbl = "macd_hist_positive" if mh > 0 else "macd_hist_negative"
    return f"rsi_{rsi_lbl}, {hist_lbl}"


def _volume_status(r: pd.Series) -> str:
    vr = _val(r, "vol_ratio")
    if vr is None:
        return "insufficient_data"
    if vr >= 2.0:
        return f"spike_{vr:.2f}x"
    if vr >= 1.2:
        return f"above_avg_{vr:.2f}x"
    if vr <= 0.7:
        return f"below_avg_{vr:.2f}x"
    return f"average_{vr:.2f}x"


def _money_flow_status(r: pd.Series) -> str:
    bits = []
    cmf = _val(r, "cmf20")
    mfi = _val(r, "mfi14")
    obv_sl = _val(r, "obv_slope_20d")
    if cmf is not None:
        bits.append(f"cmf20_{cmf:+.3f}")
    if mfi is not None:
        if mfi >= 80:
            bits.append(f"mfi_overbought_{mfi:.1f}")
        elif mfi <= 20:
            bits.append(f"mfi_oversold_{mfi:.1f}")
        else:
            bits.append(f"mfi_neutral_{mfi:.1f}")
    if obv_sl is not None:
        bits.append(f"obv_slope_{'up' if obv_sl > 0 else 'down'}")
    return ", ".join(bits) if bits else "insufficient_data"


def _volatility_status(r: pd.Series) -> str:
    atr_pct = _val(r, "atr_pct")
    bb = _str(r, "bb_position")
    if atr_pct is None:
        return "insufficient_data"
    band = "high" if atr_pct >= 3 else "low" if atr_pct < 1.5 else "normal"
    return f"atr_pct_{atr_pct:.2f}_{band}, bb_{bb}"


# ---------------------------------------------------------------------------
# Final view (Vietnamese)
# ---------------------------------------------------------------------------


def _final_view(state: str, score: int, risks: list[str]) -> str:
    headline = {
        "DISTRIBUTION": "Tín hiệu phân phối — không mua mới, ưu tiên bảo vệ vốn.",
        "BREAKOUT_WITH_EXHAUSTION_RISK": (
            "Breakout có dấu hiệu quá mua — tránh mua đuổi, chờ retest."
        ),
        "BULLISH_TREND_CONFIRMED": (
            "Xu hướng tăng đã được xác nhận — có thể nắm giữ và canh gia tăng "
            "tại các nhịp retest."
        ),
        "BREAKOUT_CONFIRMED": (
            "Breakout xác nhận — có thể mua thăm dò với quản trị rủi ro ATR stop."
        ),
        "ACCUMULATION": (
            "Đang trong vùng tích lũy quanh MA — có thể tích lũy từng phần."
        ),
        "WATCH": "Tín hiệu chưa đủ — chờ thêm xác nhận trước khi hành động.",
    }.get(state, "Tín hiệu chưa rõ — chờ thêm xác nhận.")
    risk_line = (
        f" Rủi ro nổi bật: {risks[0]}" if risks else ""
    )
    return f"{headline} Điểm tin cậy: {score}/100.{risk_line}"


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------


def build_snapshot(symbol: str, df: pd.DataFrame) -> dict[str, Any]:
    last = df.iloc[-1]
    risks = compute_key_risks(last)
    state = determine_state(last)
    score_pkg = compute_score(last, risks, state)
    final_score = score_pkg["final_score"]
    strategy = ENTRY_STRATEGY.get(state, "Chờ xác nhận thêm.")
    zones = compute_entry_zones(last)
    stop = compute_stop_loss(last)
    resistance = compute_resistance_levels(last)
    support = compute_support_levels(last)

    snapshot = {
        "symbol": symbol,
        "as_of": last["date"].strftime("%Y-%m-%d"),
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "close": _val(last, "close"),
        "technical_state": state,
        "confidence_score": final_score,
        "raw_score": score_pkg["raw_score"],
        "adjusted_score": score_pkg["adjusted_score"],
        "score_breakdown": {
            "raw_score": score_pkg["raw_score"],
            "adjusted_score": score_pkg["adjusted_score"],
            "final_score": final_score,
            "triple_risk_penalty_applied": score_pkg["triple_risk_penalty_applied"],
            "exhaustion_cap_applied": score_pkg["exhaustion_cap_applied"],
        },
        "trend_status": _trend_status(last),
        "momentum_status": _momentum_status(last),
        "volume_status": _volume_status(last),
        "money_flow_status": _money_flow_status(last),
        "volatility_status": _volatility_status(last),
        "entry_strategy": strategy,
        "entry_zones": zones,
        "stop_loss": stop,
        "resistance_levels": resistance,
        "support_levels": support,
        "upgrade_conditions": UPGRADE_CONDITIONS,
        "downgrade_conditions": DOWNGRADE_CONDITIONS,
        "key_risks": risks,
        "final_view": _final_view(state, final_score, risks),
    }
    return snapshot


def _fmt_num(v) -> str:
    if v is None:
        return "NaN"
    if isinstance(v, (int, np.integer)):
        return f"{int(v):,}"
    if isinstance(v, (float, np.floating)):
        f = float(v)
        if math.isnan(f) or math.isinf(f):
            return "NaN"
        return f"{f:,.2f}"
    return str(v)


def render_markdown(snap: dict[str, Any]) -> str:
    L: list[str] = []
    L.append(f"# {snap['symbol']} — Technical Decision")
    L.append("")
    L.append(f"- as_of: **{snap['as_of']}**")
    L.append(f"- generated_at: `{snap['generated_at']}`")
    L.append(f"- close: **{_fmt_num(snap['close'])}**")
    L.append("")

    L.append("## 1. Technical state")
    L.append("")
    L.append(f"- **{snap['technical_state']}**")
    L.append(f"- trend_status: {snap['trend_status']}")
    L.append(f"- momentum_status: {snap['momentum_status']}")
    L.append(f"- volume_status: {snap['volume_status']}")
    L.append(f"- money_flow_status: {snap['money_flow_status']}")
    L.append(f"- volatility_status: {snap['volatility_status']}")
    L.append("")

    L.append("## 2. Confidence score")
    L.append("")
    sb = snap["score_breakdown"]
    L.append(f"- raw_score: **{sb['raw_score']}**")
    L.append(f"- adjusted_score: **{sb['adjusted_score']}**  "
             f"(triple_risk_penalty_applied: {sb['triple_risk_penalty_applied']})")
    L.append(f"- final_score: **{sb['final_score']} / 100**  "
             f"(exhaustion_cap_applied: {sb['exhaustion_cap_applied']})")
    L.append("")

    L.append("## 3. Entry strategy")
    L.append("")
    L.append(f"- {snap['entry_strategy']}")
    L.append("")

    L.append("## 4. Entry zones")
    L.append("")
    if not snap["entry_zones"]:
        L.append("- _no zones derivable from indicators_")
    else:
        for z in snap["entry_zones"]:
            if "lower" in z and "upper" in z:
                L.append(
                    f"- **{z['name']}**: {_fmt_num(z['lower'])} – {_fmt_num(z['upper'])}"
                    f" ({z.get('rationale','')})"
                )
            else:
                L.append(
                    f"- **{z['name']}**: {_fmt_num(z.get('level'))}"
                    f" ({z.get('rationale','')})"
                )
    L.append("")

    L.append("## 5. Support / Resistance")
    L.append("")
    L.append("**Resistance (trên close):**")
    if not snap["resistance_levels"]:
        L.append("- _none above close_")
    else:
        for lvl in snap["resistance_levels"]:
            if lvl.get("type") == "confluence_resistance":
                src = " + ".join(lvl["sources"])
                L.append(
                    f"- **confluence_resistance**: "
                    f"{_fmt_num(lvl['lower'])} – {_fmt_num(lvl['upper'])}  "
                    f"(sources: {src})"
                )
            else:
                L.append(f"- {lvl['name']}: {_fmt_num(lvl['level'])}")
    L.append("")
    L.append("**Support (dưới close):**")
    if not snap["support_levels"]:
        L.append("- _none below close_")
    else:
        for lvl in snap["support_levels"]:
            L.append(f"- {lvl['name']}: {_fmt_num(lvl['level'])}")
    L.append("")

    L.append("## 6. Stop loss")
    L.append("")
    sl = snap["stop_loss"]
    if not sl:
        L.append("- _no stop derivable_")
    else:
        if "primary_stop" in sl:
            L.append(
                f"- **primary_stop**: {_fmt_num(sl['primary_stop'])}"
                f" ({sl.get('primary_stop_basis','')})"
            )
        if "hard_stop" in sl:
            L.append(
                f"- **hard_stop**: {_fmt_num(sl['hard_stop'])}"
                f" ({sl.get('hard_stop_basis','')})"
            )
        if "structural_stop" in sl:
            ss = sl["structural_stop"]
            usability = "usable" if ss.get("usable_as_primary") else "informational_only"
            L.append(
                f"- **structural_stop**: {_fmt_num(ss['level'])}"
                f" ({ss['basis']}, {ss['distance_from_close_pct']:.2f}% từ close, {usability})"
            )
            L.append(f"  - {ss['note']}")
        # Auxiliary raw levels
        for k in ("atr_stop_1_5x", "atr_stop_2_0x", "sma50_stop", "swing_low_20_stop"):
            if k in sl:
                L.append(f"- {k}: {_fmt_num(sl[k])}")
    L.append("")

    L.append("## 7. Upgrade / downgrade conditions")
    L.append("")
    L.append("**Upgrade khi:**")
    for c in snap["upgrade_conditions"]:
        L.append(f"- {c}")
    L.append("")
    L.append("**Downgrade khi:**")
    for c in snap["downgrade_conditions"]:
        L.append(f"- {c}")
    L.append("")

    L.append("## 8. Key risks")
    L.append("")
    if not snap["key_risks"]:
        L.append("- _no major flag_")
    else:
        for r in snap["key_risks"]:
            L.append(f"- {r}")
    L.append("")

    L.append("## 9. Final view")
    L.append("")
    L.append(snap["final_view"])
    L.append("")
    L.append(
        "> Báo cáo thuần kỹ thuật. Không phải khuyến nghị mua/bán. "
        "Dùng kèm phân tích nền tảng và bối cảnh thị trường."
    )
    return "\n".join(L) + "\n"


def run(csv_path: Path, symbol: str) -> tuple[Path, Path]:
    df = load_indicators(csv_path)
    snap = build_snapshot(symbol, df)
    json_out = DATA_DIR / f"{symbol}_decision_snapshot.json"
    md_out = REPORTS_DIR / f"{symbol}_technical_decision.md"
    json_out.write_text(json.dumps(snap, ensure_ascii=False, indent=2), encoding="utf-8")
    md_out.write_text(render_markdown(snap), encoding="utf-8")
    print(f"[decision] wrote {json_out}")
    print(f"[decision] wrote {md_out}")
    return json_out, md_out


def main() -> int:
    p = argparse.ArgumentParser(description="Technical decision framework.")
    p.add_argument("--csv", required=True, help="Path to indicators CSV (from indicator_engine).")
    p.add_argument("--symbol", required=True, help="Ticker symbol.")
    args = p.parse_args()
    run(Path(args.csv), args.symbol.upper())
    return 0


if __name__ == "__main__":
    sys.exit(main())
