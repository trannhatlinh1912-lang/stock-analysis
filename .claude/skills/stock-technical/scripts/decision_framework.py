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

sys.path.insert(0, str(Path(__file__).resolve().parent))
from config_loader import (  # noqa: E402
    load_config,
    eval_macro_penalties,
    eval_custom_risks,
    SECTOR_MAP,
)

PIPELINE_VERSION = "2.6.0-2026-05-28-fully-calibrated"


def _cfg_to_flat(cfg: dict) -> dict:
    """Flatten YAML config sections into the old CONFIG dict shape for callers
    that still read it directly. Keeps backwards compat with existing helpers
    (e.g. _atr_scale_factor, _liquidity_status)."""
    sizing = cfg.get("sizing", {}) or {}
    liq = cfg.get("liquidity", {}) or {}
    sc = cfg.get("scoring", {}) or {}
    adx = cfg.get("adx", {}) or {}
    return {
        "risk_pct_nav": float(sizing.get("risk_pct_nav", 1.0)),
        "max_size_pct_nav": float(sizing.get("max_size_pct_nav", 20.0)),
        "vol_target_daily_pct": float(sizing.get("vol_target_daily_pct", 1.5)),
        "atr_pct_low": float(sizing.get("atr_pct_low", 1.5)),
        "atr_pct_high": float(sizing.get("atr_pct_high", 5.0)),
        "liquidity_floor_turnover_thousand_vnd": float(liq.get("floor_thousand_vnd", 5_000_000.0)),
        "illiquid_size_cap_pct_nav": float(liq.get("illiquid_size_cap_pct_nav", 5.0)),
        "exhaustion_score_cap": int(sc.get("exhaustion_score_cap", 68)),
        "triple_risk_penalty": int(sc.get("triple_risk_penalty", 5)),
        "target_max_dist_pct": float(sc.get("target_max_dist_pct", 12.0)),
        "adx_strong": float(adx.get("strong", 25.0)),
        "adx_developing": float(adx.get("developing", 20.0)),
    }


# Loaded per-symbol in build_snapshot. Initialised here for module-level callers.
CONFIG = _cfg_to_flat(load_config("DEFAULT"))

# Backwards-compat aliases (used by older code paths within this file).
MAX_SIZE_PCT_NAV = CONFIG["max_size_pct_nav"]
RISK_PCT_NAV = CONFIG["risk_pct_nav"]
TARGET_MAX_DIST_PCT = CONFIG["target_max_dist_pct"]


def apply_macro_penalty(
    score: int,
    symbol: str,
    macro: dict | None,
    foreign: dict | None,
    cfg: dict | None = None,
) -> tuple[int, list[str]]:
    """Apply macro penalty via YAML-defined rules merged for this symbol.

    Delegates to config_loader.eval_macro_penalties so the rule set is fully
    data-driven. Caller passes the resolved per-symbol cfg if available;
    otherwise it is loaded here.
    """
    if cfg is None:
        cfg = load_config(symbol)
    rules = cfg.get("macro_penalties", []) or []
    delta, notes = eval_macro_penalties(rules, macro, foreign)
    new_score = max(0, min(100, score + delta))
    return new_score, notes


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


def _state_cfg(cfg: dict | None) -> dict:
    if cfg is None:
        return {}
    return cfg.get("state_classifier", {}) or {}


def _is_breakout_confirmed(r: pd.Series, cfg: dict | None = None) -> bool:
    p = _state_cfg(cfg).get("breakout_confirmed", {})
    vol_min = float(p.get("vol_ratio_min", 1.5))
    ret_min = float(p.get("ret_1d_min_pct", 2.0))
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
        and vr >= vol_min and ret1 > ret_min and mh > 0.0
    )


def _is_breakout_with_exhaustion(r: pd.Series, cfg: dict | None = None) -> bool:
    if not _is_breakout_confirmed(r, cfg):
        return False
    p = _state_cfg(cfg).get("breakout_with_exhaustion", {})
    stoch_min = float(p.get("stoch_k_min", 90.0))
    vol_min = float(p.get("vol_ratio_min", 2.0))
    bb = _str(r, "bb_position")
    sk = _val(r, "stoch_k")
    vr = _val(r, "vol_ratio")
    if bb is None or sk is None or vr is None:
        return False
    return bb == "above_upper" and sk >= stoch_min and vr >= vol_min


def _is_bullish_trend_confirmed(r: pd.Series, cfg: dict | None = None) -> bool:
    p = _state_cfg(cfg).get("bullish_trend_confirmed", {})
    vol_min = float(p.get("vol_ratio_min", 1.0))
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
        and mh > 0.0 and vr >= vol_min
    )


def _is_accumulation(r: pd.Series, cfg: dict | None = None) -> bool:
    p = _state_cfg(cfg).get("accumulation", {})
    near_mult = float(p.get("near_ma_atr_mult", 1.0))
    vr_low = float(p.get("vol_ratio_low", 0.8))
    vr_high = float(p.get("vol_ratio_high", 1.5))
    rsi_min = float(p.get("rsi_min", 45.0))
    rsi_max = float(p.get("rsi_max", 60.0))
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
    near_sma = False
    if s20 is not None and abs(close - s20) <= near_mult * atr:
        near_sma = True
    if s50 is not None and abs(close - s50) <= near_mult * atr:
        near_sma = True
    if not near_sma:
        return False
    if not (vr_low <= vr <= vr_high):
        return False
    momentum_ok = False
    if mh is not None and mh >= 0.0:
        momentum_ok = True
    if rsi is not None and rsi_min <= rsi <= rsi_max:
        momentum_ok = True
    if not momentum_ok:
        return False
    if bb == "above_upper":
        return False
    return True


def _is_distribution(r: pd.Series, cfg: dict | None = None) -> bool:
    close = _val(r, "close")
    s20 = _val(r, "sma20")
    mh = _val(r, "macd_hist")
    cmf = _val(r, "cmf20")
    obv_sl = _val(r, "obv_slope_20d")
    if any(v is None for v in (close, s20, mh, cmf, obv_sl)):
        return False
    return close < s20 and mh < 0.0 and cmf < 0.0 and obv_sl < 0.0


def determine_state(r: pd.Series, cfg: dict | None = None) -> str:
    """Return technical_state under fixed priority order. Thresholds in cfg."""
    if _is_distribution(r, cfg):
        return "DISTRIBUTION"
    if _is_breakout_with_exhaustion(r, cfg):
        return "BREAKOUT_WITH_EXHAUSTION_RISK"
    if _is_bullish_trend_confirmed(r, cfg):
        return "BULLISH_TREND_CONFIRMED"
    if _is_breakout_confirmed(r, cfg):
        return "BREAKOUT_CONFIRMED"
    if _is_accumulation(r, cfg):
        return "ACCUMULATION"
    return "WATCH"


# ---------------------------------------------------------------------------
# Key risks (independent of indicator_engine to keep this module self-contained)
# ---------------------------------------------------------------------------


def compute_key_risks(r: pd.Series, cfg: dict | None = None) -> list[str]:
    t = (cfg or {}).get("risk_thresholds", {}) if cfg else {}
    rsi_overbought = float(t.get("rsi_overbought", 75.0))
    rsi_oversold = float(t.get("rsi_oversold", 25.0))
    near_52h = float(t.get("near_52w_high_dist_pct", -3.0))
    near_52l = float(t.get("near_52w_low_dist_pct", 5.0))
    sma100_low = float(t.get("near_sma100_lower_band_pct", -2.0))
    sma100_high = float(t.get("near_sma100_upper_band_pct", 0.0))
    cmf_cutoff = float(t.get("cmf_distribution_cutoff", -0.05))
    exh_ret = float(t.get("exhaustion_ret_1d_min_pct", 5.0))
    exh_vr = float(t.get("exhaustion_vol_ratio_min", 2.0))
    exh_sk = float(t.get("exhaustion_stoch_k_min", 90.0))

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

    if (
        bb == "above_upper"
        and vr is not None and vr >= exh_vr
        and sk is not None and sk >= exh_sk
        and ret1 is not None and ret1 >= exh_ret
    ):
        risks.append(
            "breakout_exhaustion_risk: giá tăng mạnh vượt Bollinger Upper với "
            "volume spike và Stoch quá nóng; rủi ro pullback/throwback 1-5 phiên cao."
        )

    if (
        close is not None and s100 is not None and close < s100
        and dist_s100 is not None and sma100_low <= dist_s100 <= sma100_high
    ):
        risks.append(
            "near_sma100_resistance: giá đang sát dưới SMA100, cần vượt và "
            "giữ trên SMA100 để xác nhận trend trung hạn."
        )

    if all(v is not None for v in (close, s20, s50, s100, s200)):
        if not (close > s20 > s50 > s100 > s200):
            risks.append(
                "trend_not_fully_aligned: MA chưa xếp hàng tăng hoàn chỉnh, "
                "xu hướng trung hạn chưa xác nhận."
            )

    if rsi is not None and rsi >= rsi_overbought:
        risks.append(f"rsi_overbought ({rsi:.1f}): rủi ro pullback ngắn hạn.")
    if rsi is not None and rsi <= rsi_oversold:
        risks.append(f"rsi_oversold ({rsi:.1f}): bounce hoặc capitulation.")

    if cmf is not None and cmf < cmf_cutoff and close is not None and s50 is not None and close > s50:
        risks.append("cmf_distribution_divergence: giá trên SMA50 nhưng CMF20 âm.")

    if mh is not None and mh < 0 and _val(r, "macd") is not None and _val(r, "macd") > 0:
        risks.append("macd_momentum_fade: MACD trên 0 nhưng histogram âm.")

    if dist_52h is not None and dist_52h > near_52h:
        risks.append("near_52w_high: rủi ro failed breakout.")
    if dist_52l is not None and dist_52l < near_52l:
        risks.append("near_52w_low: rủi ro tiếp diễn xu hướng giảm.")

    return risks


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------


def _eval_rubric_signal(
    sig: dict, r: pd.Series, key_risks: list[str]
) -> bool | None:
    """Evaluate a single rubric signal. Returns True/False or None if missing data."""
    cond = sig.get("condition", "")
    if cond.startswith("_risk:"):
        risk_id = cond.split(":", 1)[1].strip()
        return any(risk_id in kr for kr in key_risks)

    ns: dict[str, Any] = {}
    for key in ("close", "sma20", "sma50", "sma100", "sma200",
                "vol_ratio", "macd_hist", "obv_slope_20d", "mfi14",
                "stoch_k", "cmf20", "atr14", "atr_pct", "adx14",
                "plus_di14", "minus_di14"):
        ns[key] = _val(r, key)
    ns["bb_position"] = _str(r, "bb_position")
    ns["ichi_cloud_position"] = _str(r, "ichi_cloud_position")
    if any(ns.get(k) is None for k in ("close",) if k in cond):
        return None
    try:
        return bool(eval(cond, {"__builtins__": {}}, ns))  # noqa: S307
    except Exception:
        return None


def compute_score(
    r: pd.Series, key_risks: list[str], state: str, cfg: dict | None = None
) -> dict:
    """Return {raw_score, adjusted_score, final_score, score_audit}.

    Rubric signals + weights are read from cfg['score_rubric']['signals'] (loaded
    from configs/default.yaml). Each signal contributes its weight when condition
    evaluates True. NaN/missing → signal skipped (recorded as None).
    """
    if cfg is None:
        cfg = load_config(getattr(r, "name", "DEFAULT"))
    rubric = cfg.get("score_rubric", {}) or {}
    base = int(rubric.get("base", 50))
    signals = rubric.get("signals", []) or []

    score = base
    audit: list[dict] = []
    for sig in signals:
        sig_id = sig.get("id", "")
        weight = int(sig.get("weight", 0))
        triggered = _eval_rubric_signal(sig, r, key_risks)
        if triggered is True:
            score += weight
            audit.append({"id": sig_id, "triggered": True, "weight": weight, "applied": weight})
        elif triggered is False:
            audit.append({"id": sig_id, "triggered": False, "weight": weight, "applied": 0})
        else:
            audit.append({"id": sig_id, "triggered": None, "weight": weight, "applied": 0,
                          "note": "missing_data"})

    raw_score = score

    sc = cfg.get("scoring", {}) or {}
    triple_penalty = int(sc.get("triple_risk_penalty", 5))
    exhaustion_cap = int(sc.get("exhaustion_score_cap", 100))

    has_exhaustion = any("breakout_exhaustion_risk" in kr for kr in key_risks)
    has_near_sma100 = any("near_sma100_resistance" in kr for kr in key_risks)
    has_not_aligned = any("trend_not_fully_aligned" in kr for kr in key_risks)
    triple = has_exhaustion and has_near_sma100 and has_not_aligned

    adjusted_score = raw_score - triple_penalty if triple else raw_score

    final_score = adjusted_score
    cap_applied = False
    if state == "BREAKOUT_WITH_EXHAUSTION_RISK" and exhaustion_cap < 100:
        if final_score > exhaustion_cap:
            final_score = exhaustion_cap
            cap_applied = True
    final_score = max(0, min(100, int(final_score)))

    return {
        "raw_score": int(raw_score),
        "adjusted_score": int(adjusted_score),
        "final_score": int(final_score),
        "triple_risk_penalty_applied": bool(triple),
        "exhaustion_cap_applied": bool(cap_applied),
        "score_audit": audit,
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
# Risk / reward + position sizing
# ---------------------------------------------------------------------------

def _nearest_target(close: float, resistance: list[dict[str, Any]]) -> dict[str, Any] | None:
    """First resistance level above close within TARGET_MAX_DIST_PCT."""
    if not resistance or close is None:
        return None
    for lvl in resistance:
        # Confluence levels expose lower/upper; use lower as the target.
        if lvl.get("type") == "confluence_resistance":
            target = float(lvl.get("lower"))
        else:
            target = float(lvl.get("level"))
        if target <= close:
            continue
        dist_pct = (target - close) / close * 100.0
        if dist_pct > TARGET_MAX_DIST_PCT:
            continue
        return {"name": lvl.get("name"), "level": target, "dist_pct": round(dist_pct, 2)}
    # Fall back to the first one above close even if it's far.
    for lvl in resistance:
        target = float(lvl.get("lower") if lvl.get("type") == "confluence_resistance" else lvl.get("level"))
        if target > close:
            return {
                "name": lvl.get("name"),
                "level": target,
                "dist_pct": round((target - close) / close * 100.0, 2),
            }
    return None


def _atr_scale_factor(atr_pct: float | None) -> float:
    """Return [0..1] multiplier on position size based on ATR%.

    atr_pct ≤ CONFIG['atr_pct_low'] (1.5%) → 1.0
    atr_pct ≥ CONFIG['atr_pct_high'] (5%)  → CONFIG['atr_pct_low']/atr_pct
    in between: linear interpolation.
    """
    if atr_pct is None or atr_pct <= 0:
        return 1.0
    lo = CONFIG["atr_pct_low"]
    hi = CONFIG["atr_pct_high"]
    if atr_pct <= lo:
        return 1.0
    if atr_pct >= hi:
        return float(lo / atr_pct)
    # Linear: at hi → lo/hi, at lo → 1.0
    edge = lo / hi
    frac = (atr_pct - lo) / (hi - lo)
    return float(1.0 - frac * (1.0 - edge))


def annotate_zones_with_rr(
    zones: list[dict[str, Any]],
    primary_stop: float | None,
    target: dict[str, Any] | None,
    atr_pct: float | None = None,
    liquidity_ok: bool = True,
) -> list[dict[str, Any]]:
    """Add risk_reward, size_pct_nav, notional_per_100m_nav, low_rr_warning."""
    if primary_stop is None or target is None:
        return zones

    target_level = float(target["level"])
    annotated: list[dict[str, Any]] = []
    for z in zones:
        z2 = dict(z)
        # Use the zone midpoint as the assumed entry; for single-level zones, use level.
        if "lower" in z2 and "upper" in z2:
            entry = (float(z2["lower"]) + float(z2["upper"])) / 2.0
        elif "level" in z2:
            entry = float(z2["level"])
        else:
            annotated.append(z2)
            continue

        risk_per_share = entry - primary_stop
        reward_per_share = target_level - entry
        z2["entry_ref"] = round(entry, 4)
        z2["target_ref"] = round(target_level, 4)
        if risk_per_share <= 0 or reward_per_share <= 0:
            z2["risk_reward"] = None
            z2["size_pct_nav"] = None
            z2["low_rr_warning"] = True
            if risk_per_share <= 0:
                z2["rr_invalid_reason"] = "entry_below_or_at_primary_stop"
            else:
                z2["rr_invalid_reason"] = "entry_above_or_at_target"
            annotated.append(z2)
            continue

        rr = reward_per_share / risk_per_share
        size_pct_raw = (RISK_PCT_NAV / 100.0) / (risk_per_share / entry) * 100.0
        atr_scale = _atr_scale_factor(atr_pct)
        size_pct = size_pct_raw * atr_scale
        size_pct = min(size_pct, MAX_SIZE_PCT_NAV)
        if not liquidity_ok:
            size_pct = min(size_pct, 5.0)  # hard cap for illiquid names
        notional_per_100m = size_pct / 100.0 * 100_000_000

        z2["risk_reward"] = round(rr, 2)
        z2["size_pct_nav_raw"] = round(size_pct_raw, 2)
        z2["atr_scale_factor"] = round(atr_scale, 3)
        z2["size_pct_nav"] = round(size_pct, 2)
        z2["notional_per_100m_nav"] = int(round(notional_per_100m))
        z2["low_rr_warning"] = bool(rr < 1.5)
        if not liquidity_ok:
            z2["liquidity_warning"] = True
        annotated.append(z2)
    return annotated


# ---------------------------------------------------------------------------
# External context loaders (market, empirical)
# ---------------------------------------------------------------------------


def load_market_context() -> dict[str, Any] | None:
    """Return today's cached market context if available."""
    today = date.today().isoformat()
    path = DATA_DIR / f"market_context_{today}.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except Exception:
        return None


def load_empirical_stats(symbol: str) -> dict[str, Any] | None:
    path = DATA_DIR / f"{symbol}_empirical_stats.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except Exception:
        return None


def load_macro_overlay() -> dict[str, Any] | None:
    today = date.today().isoformat()
    path = DATA_DIR / f"macro_overlay_{today}.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except Exception:
        return None


def load_foreign_snapshot(symbol: str) -> dict[str, Any] | None:
    path = DATA_DIR / f"{symbol}_foreign_snapshot.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except Exception:
        return None


def load_backtest_report(symbol: str) -> dict[str, Any] | None:
    path = DATA_DIR / f"{symbol}_backtest.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except Exception:
        return None


def compute_relative_strength_inline(
    symbol_close: pd.Series, symbol_dates: pd.Series, cfg: dict | None = None
) -> dict[str, Any] | None:
    """Compute RS using the cached VNINDEX price CSV (if present)."""
    idx_csv = DATA_DIR / "VNINDEX_price_VCI.csv"
    if not idx_csv.exists():
        return None
    p = (cfg or {}).get("base_bias", {}) if cfg else {}
    leader_slope = float(p.get("rs_leader_slope_pct", 2.0))
    laggard_slope = float(p.get("rs_laggard_slope_pct", -2.0))
    try:
        idx = pd.read_csv(idx_csv)
        idx["time"] = pd.to_datetime(idx["time"])
        sym = pd.DataFrame({"date": pd.to_datetime(symbol_dates), "sym_close": symbol_close.values})
        merged = sym.merge(idx[["time", "close"]].rename(columns={"time": "date", "close": "idx_close"}), on="date")
        if len(merged) < 25:
            return None
        rs = merged["sym_close"] / merged["idx_close"]
        rs_now = float(rs.iloc[-1])
        rs_20d = float(rs.iloc[-21])
        slope_pct = (rs_now / rs_20d - 1.0) * 100.0
        label = "leader" if slope_pct > leader_slope else "laggard" if slope_pct < laggard_slope else "inline"
        return {
            "rs_now": round(rs_now, 6),
            "rs_slope_20d_pct": round(slope_pct, 3),
            "label": label,
        }
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Next-session playbook
# ---------------------------------------------------------------------------


def _compute_base_bias(
    state: str,
    final_score: int,
    market_ctx: dict | None,
    weekly_trend: str | None,
    structure_label: str | None,
    rs_label: str | None,
    cfg: dict | None = None,
) -> tuple[str, str]:
    """Aggregate signals to directional bias. Thresholds from cfg.base_bias."""
    p = (cfg or {}).get("base_bias", {}) if cfg else {}
    bull_score = int(p.get("bullish_score_threshold", 70))
    bear_score = int(p.get("bearish_score_threshold", 40))
    bull_net = int(p.get("bullish_net_signals", 3))
    ntb_net = int(p.get("neutral_to_bullish_net", 2))
    bear_net = int(p.get("bearish_net_signals", -2))
    ntb_bear = int(p.get("neutral_to_bearish_net", -1))

    bullish_signals = 0
    bearish_signals = 0
    rationale_bits: list[str] = []

    rationale_bits.append(f"score={final_score}")
    if final_score >= bull_score:
        bullish_signals += 1
    elif final_score < bear_score:
        bearish_signals += 1

    if weekly_trend == "up":
        bullish_signals += 1
        rationale_bits.append("weekly_up")
    elif weekly_trend == "down":
        bearish_signals += 1
        rationale_bits.append("weekly_down")

    if market_ctx:
        regime = market_ctx.get("regime")
        if regime == "risk_on":
            bullish_signals += 1
            rationale_bits.append("market_risk_on")
        elif regime == "risk_off":
            bearish_signals += 1
            rationale_bits.append("market_risk_off")
        else:
            rationale_bits.append(f"market_{regime}")

    if structure_label == "uptrend_structure":
        bullish_signals += 1
        rationale_bits.append("structure_up")
    elif structure_label == "downtrend_structure":
        bearish_signals += 1
        rationale_bits.append("structure_down")

    if rs_label == "leader":
        bullish_signals += 1
        rationale_bits.append("rs_leader")
    elif rs_label == "laggard":
        bearish_signals += 1
        rationale_bits.append("rs_laggard")

    if state == "DISTRIBUTION":
        bearish_signals += 2
        rationale_bits.append("state_distribution")
    elif state == "BREAKOUT_WITH_EXHAUSTION_RISK":
        rationale_bits.append("state_exhaustion")

    net = bullish_signals - bearish_signals
    if net >= bull_net:
        bias = "bullish"
    elif net >= ntb_net:
        bias = "neutral_to_bullish"
    elif net <= bear_net:
        bias = "bearish"
    elif net <= ntb_bear:
        bias = "neutral_to_bearish"
    else:
        bias = "neutral"
    return bias, " + ".join(rationale_bits)


def _build_scenarios(
    state: str,
    close: float | None,
    primary_stop: float | None,
    hard_stop: float | None,
    swing_high_20: float | None,
    target: dict | None,
    bias: str,
) -> list[dict[str, Any]]:
    """Four named scenarios for next session."""
    sh = f"{swing_high_20:.2f}" if swing_high_20 else "swing_high_20"
    ps = f"{primary_stop:.2f}" if primary_stop else "primary_stop"
    hs = f"{hard_stop:.2f}" if hard_stop else "hard_stop"
    tgt = f"{target['level']:.2f}" if target else "kháng cự kế tiếp"

    if state == "BREAKOUT_WITH_EXHAUSTION_RISK":
        gap_up_action = (
            f"Không đuổi. Đợi 30-60 phút retest về {sh} hoặc VWAP. "
            f"Nếu giữ vùng đó với volume duy trì → mua thăm dò 30% size, stop dưới {ps}."
        )
        trend_up_action = (
            f"Hold-and-add chỉ khi đóng nến 1H trên {sh} với volume ≥ 1.2× MA20. "
            f"Mua 30% size tại pullback nhẹ về {sh}; không full size do exhaustion."
        )
    elif state == "BULLISH_TREND_CONFIRMED":
        gap_up_action = (
            f"Có thể giữ vị thế. Không đuổi giá. Đợi retest về SMA20/swing_high_20 "
            f"để gia tăng nếu cần."
        )
        trend_up_action = (
            f"Mua 50% size tại retest_aggressive, add 50% nếu đóng nến 1H trên {sh}. "
            f"Trail stop theo SMA20."
        )
    elif state == "ACCUMULATION":
        gap_up_action = (
            f"Gap up trong vùng tích lũy thường fake — fade về biên trên range, "
            f"chốt 1/3 vị thế nếu đã có. Add chỉ khi đóng nến 1H trên {sh}."
        )
        trend_up_action = (
            f"Mua 50% size tại biên dưới range hoặc retest SMA20/SMA50. "
            f"Add 50% nếu vượt {sh} với volume."
        )
    elif state == "BREAKOUT_CONFIRMED":
        gap_up_action = (
            f"Đuổi 30% size nếu volume open ≥ 1.5× MA20; ưu tiên đợi retest về {sh} "
            f"trong 30-60 phút để vào full size."
        )
        trend_up_action = (
            f"Mua 50% size tại retest_aggressive (close − 0.5–1.0 ATR). Add 50% "
            f"nếu đóng nến 1H trên {sh}. Stop {ps}."
        )
    elif state == "DISTRIBUTION":
        gap_up_action = (
            f"Bull-trap risk cao. Chốt phần còn lại của long position nếu chưa đóng. "
            f"Tránh mua mới."
        )
        trend_up_action = (
            f"Không hành động long. Chỉ trader ngắn hạn cân nhắc bounce-play với "
            f"stop chặt; risk:reward thường ≤ 1."
        )
    else:  # WATCH
        gap_up_action = (
            f"Đợi 30-60 phút xác nhận. Nếu giữ trên {sh} với volume duy trì → "
            f"mua thăm dò 30% size, stop {ps}."
        )
        trend_up_action = (
            f"Mua 30% size khi đóng nến 1H trên {sh} với volume ≥ 1.2× MA20. "
            f"Add 30% nếu duy trì sau 2 phiên."
        )

    gap_down_action = (
        f"Đợi 30-60 phút. Nếu giữ trên {ps} → có thể mua thăm dò 30% size; "
        f"thủng {hs} intraday → bỏ qua, không cố bắt dao rơi."
    )
    range_action = (
        f"Không hành động. Đợi breakout trên {sh} hoặc breakdown dưới {ps} "
        f"với volume xác nhận. Range bó hẹp 4H đầu = chờ."
    )

    return [
        {
            "name": "gap_up_strong",
            "trigger": "Mở cửa gap +2% trở lên so với close phiên trước.",
            "action": gap_up_action,
            "invalidation": f"Đóng nến 1H dưới open hoặc dưới {ps}.",
        },
        {
            "name": "gap_down",
            "trigger": "Mở cửa gap -1.5% trở xuống.",
            "action": gap_down_action,
            "invalidation": f"Thủng {hs} intraday → cắt nếu đã long.",
        },
        {
            "name": "trend_day_up",
            "trigger": (
                "Mở cửa flat-to-positive (±0.5%), giữ trên VWAP > 30 phút đầu, "
                "volume > 1.2× MA20."
            ),
            "action": trend_up_action,
            "invalidation": f"Đóng nến 1H dưới {ps} hoặc volume mất.",
        },
        {
            "name": "range_day",
            "trigger": "Mở cửa flat (±0.5%), range hẹp 4H đầu, volume thấp.",
            "action": range_action,
            "invalidation": f"Breakout {sh} hoặc breakdown {ps} chuyển sang scenario khác.",
        },
    ]


def build_next_session_playbook(
    state: str,
    final_score: int,
    last_row: pd.Series,
    primary_stop: float | None,
    hard_stop: float | None,
    resistance: list[dict[str, Any]],
    market_ctx: dict | None,
    empirical: dict | None,
    rs: dict | None,
    cfg: dict | None = None,
) -> dict[str, Any]:
    close = _val(last_row, "close")
    swing_h20 = _val(last_row, "swing_high_20")
    weekly_trend = _str(last_row, "weekly_trend")
    structure_label = _str(last_row, "structure_label")
    rs_label = rs.get("label") if rs else None

    bias, rationale = _compute_base_bias(
        state, final_score, market_ctx, weekly_trend, structure_label, rs_label, cfg=cfg
    )
    target = _nearest_target(close, resistance) if close else None
    scenarios = _build_scenarios(
        state, close, primary_stop, hard_stop, swing_h20, target, bias
    )

    # Monitoring levels: must_hold, trigger_add, take_profit_1, take_profit_2
    monitoring: dict[str, Any] = {}
    if primary_stop is not None:
        monitoring["must_hold"] = round(primary_stop, 4)
    if swing_h20 is not None:
        monitoring["trigger_add"] = round(swing_h20, 4)
    # Take profit ladder from resistance list
    tp_levels: list[float] = []
    for lvl in resistance:
        v = float(lvl.get("lower") if lvl.get("type") == "confluence_resistance" else lvl.get("level"))
        if close is not None and v > close:
            tp_levels.append(v)
        if len(tp_levels) >= 2:
            break
    if len(tp_levels) >= 1:
        monitoring["take_profit_1"] = round(tp_levels[0], 4)
    if len(tp_levels) >= 2:
        monitoring["take_profit_2"] = round(tp_levels[1], 4)

    # Empirical bias snippet for this state, if any
    empirical_bias: dict[str, Any] | None = None
    if empirical and "by_state" in empirical:
        st = empirical["by_state"].get(state)
        if st:
            empirical_bias = {
                "state": state,
                "n_samples": st["n_samples"],
                "p_up_1d": st["p_up_1d"],
                "p_up_5d": st["p_up_5d"],
                "median_ret_5d_pct": st["median_ret_5d_pct"],
                "hit_target_1atr_5d": st["hit_target_1atr_5d"],
                "low_sample_warning": st["low_sample_warning"],
            }

    return {
        "base_bias": bias,
        "bias_rationale": rationale,
        "weekly_trend": weekly_trend,
        "structure_label": structure_label,
        "scenarios": scenarios,
        "monitoring_levels": monitoring,
        "primary_target": target,
        "empirical_bias": empirical_bias,
    }


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


def _adx_status(r: pd.Series) -> dict[str, Any]:
    adx = _val(r, "adx14")
    pdi = _val(r, "plus_di14")
    mdi = _val(r, "minus_di14")
    if adx is None:
        return {"adx": None, "strength": "missing_data", "direction": "missing_data"}
    if adx >= CONFIG["adx_strong"]:
        strength = "strong"
    elif adx >= CONFIG["adx_developing"]:
        strength = "developing"
    else:
        strength = "weak_or_range"
    if pdi is not None and mdi is not None:
        direction = "bullish" if pdi > mdi else "bearish" if mdi > pdi else "flat"
    else:
        direction = "missing_data"
    return {"adx": round(adx, 2), "strength": strength, "direction": direction,
            "plus_di": round(pdi, 2) if pdi is not None else None,
            "minus_di": round(mdi, 2) if mdi is not None else None}


def _ichimoku_status(r: pd.Series) -> dict[str, Any]:
    pos = _str(r, "ichi_cloud_position")
    tenkan = _val(r, "ichi_tenkan")
    kijun = _val(r, "ichi_kijun")
    sa = _val(r, "ichi_senkou_a")
    sb = _val(r, "ichi_senkou_b")
    cloud_bull = (sa is not None and sb is not None and sa > sb)
    tk_cross = None
    if tenkan is not None and kijun is not None:
        tk_cross = "bullish" if tenkan > kijun else "bearish" if tenkan < kijun else "flat"
    return {
        "cloud_position": pos,
        "cloud_color": "bullish" if cloud_bull else ("bearish" if sa is not None and sb is not None else "missing"),
        "tk_cross": tk_cross,
        "tenkan": round(tenkan, 4) if tenkan is not None else None,
        "kijun": round(kijun, 4) if kijun is not None else None,
    }


def _liquidity_status(r: pd.Series) -> dict[str, Any]:
    turnover = _val(r, "turnover_20d_avg")
    floor = CONFIG["liquidity_floor_turnover_thousand_vnd"]
    if turnover is None:
        return {"turnover_20d_avg_thousand_vnd": None, "ok": True, "note": "missing_data"}
    ok = turnover >= floor
    return {
        "turnover_20d_avg_thousand_vnd": round(turnover, 0),
        "floor_thousand_vnd": floor,
        "ok": bool(ok),
        "note": (
            "đủ thanh khoản"
            if ok else
            f"dưới ngưỡng (turnover < {floor/1e6:.1f} tỷ VND/phiên) — giảm size về ≤5% NAV"
        ),
    }


def _sub_state(state: str, r: pd.Series, cfg: dict | None = None) -> str | None:
    """Sub-state for WATCH/DISTRIBUTION using ADX + Ichimoku + breakdown flag.
    Thresholds from cfg.sub_state_thresholds."""
    t = (cfg or {}).get("sub_state_thresholds", {}) if cfg else {}
    bp_adx_max = float(t.get("watch_breakout_pending_adx_max", 20.0))
    rb_adx_max = float(t.get("watch_range_bound_adx_max", 18.0))
    rb_mh_abs = float(t.get("watch_range_bound_mh_abs_max", 0.01))

    adx = _val(r, "adx14")
    pdi = _val(r, "plus_di14")
    mdi = _val(r, "minus_di14")
    pos = _str(r, "ichi_cloud_position")
    bd = _val(r, "breakdown_structural")
    mh = _val(r, "macd_hist")
    if state == "DISTRIBUTION":
        if bd and bd > 0:
            return "DISTRIBUTION_BREAKDOWN"
        return "DISTRIBUTION_TREND"
    if state == "WATCH":
        if pos == "above_cloud" and adx is not None and adx < bp_adx_max:
            return "WATCH_BREAKOUT_PENDING"
        if pos == "below_cloud" and mdi is not None and pdi is not None and mdi > pdi:
            return "WATCH_BOUNCE_PLAY"
        if adx is not None and adx < rb_adx_max and mh is not None and abs(mh) < rb_mh_abs:
            return "WATCH_RANGE_BOUND"
    return None


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
    # Load per-symbol config + mutate module-level CONFIG so existing helpers
    # (which read CONFIG directly) pick up sector overrides.
    per_symbol_cfg = load_config(symbol)
    CONFIG.update(_cfg_to_flat(per_symbol_cfg))
    global MAX_SIZE_PCT_NAV, RISK_PCT_NAV, TARGET_MAX_DIST_PCT
    MAX_SIZE_PCT_NAV = CONFIG["max_size_pct_nav"]
    RISK_PCT_NAV = CONFIG["risk_pct_nav"]
    TARGET_MAX_DIST_PCT = CONFIG["target_max_dist_pct"]

    last = df.iloc[-1]
    risks = compute_key_risks(last, cfg=per_symbol_cfg)
    state = determine_state(last, cfg=per_symbol_cfg)
    score_pkg = compute_score(last, risks, state, cfg=per_symbol_cfg)
    final_score = score_pkg["final_score"]
    strategy = ENTRY_STRATEGY.get(state, "Chờ xác nhận thêm.")
    zones = compute_entry_zones(last)
    stop = compute_stop_loss(last)
    resistance = compute_resistance_levels(last)
    support = compute_support_levels(last)

    primary_stop = stop.get("primary_stop") if isinstance(stop, dict) else None
    hard_stop = stop.get("hard_stop") if isinstance(stop, dict) else None
    close = _val(last, "close")

    target = _nearest_target(close, resistance) if close is not None else None
    atr_pct = _val(last, "atr_pct")
    liquidity = _liquidity_status(last)
    zones = annotate_zones_with_rr(
        zones, primary_stop, target,
        atr_pct=atr_pct,
        liquidity_ok=liquidity.get("ok", True),
    )

    market_ctx = load_market_context()
    empirical = load_empirical_stats(symbol)
    rs = compute_relative_strength_inline(df["close"], df["date"], cfg=per_symbol_cfg)
    macro = load_macro_overlay()
    foreign = load_foreign_snapshot(symbol)
    backtest = load_backtest_report(symbol)
    adx_status = _adx_status(last)
    ichi_status = _ichimoku_status(last)
    sub_state = _sub_state(state, last, cfg=per_symbol_cfg)

    # Macro-conditional score adjustment via YAML rules.
    macro_adjusted_score, macro_notes = apply_macro_penalty(
        final_score, symbol, macro, foreign, cfg=per_symbol_cfg
    )
    if macro_adjusted_score != final_score:
        score_pkg["macro_adjusted_score"] = macro_adjusted_score
        score_pkg["macro_penalty_notes"] = macro_notes
        final_score = macro_adjusted_score

    # Custom risks from sector/ticker config.
    custom_risk_labels = eval_custom_risks(
        per_symbol_cfg.get("custom_risks", []) or [], macro, foreign
    )
    if custom_risk_labels:
        risks.extend(custom_risk_labels)

    playbook = build_next_session_playbook(
        state=state,
        final_score=final_score,
        last_row=last,
        primary_stop=primary_stop,
        hard_stop=hard_stop,
        resistance=resistance,
        market_ctx=market_ctx,
        empirical=empirical,
        rs=rs,
        cfg=per_symbol_cfg,
    )

    snapshot = {
        "symbol": symbol,
        "pipeline_version": PIPELINE_VERSION,
        "config": dict(CONFIG),
        "resolved_config_sources": {
            "sector": per_symbol_cfg.get("_sector"),
            "default_yaml": "configs/default.yaml",
            "sector_yaml": (
                f"configs/sectors/{per_symbol_cfg.get('_sector')}.yaml"
                if per_symbol_cfg.get("_sector") else None
            ),
            "ticker_yaml": (
                f"configs/tickers/{symbol}.yaml"
                if (REPO_ROOT / "configs" / "tickers" / f"{symbol}.yaml").exists()
                else None
            ),
            "macro_penalty_rules_count": len(per_symbol_cfg.get("macro_penalties", []) or []),
            "custom_risks_count": len(per_symbol_cfg.get("custom_risks", []) or []),
        },
        "as_of": last["date"].strftime("%Y-%m-%d"),
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "close": close,
        "technical_state": state,
        "sub_state": sub_state,
        "confidence_score": final_score,
        "raw_score": score_pkg["raw_score"],
        "adjusted_score": score_pkg["adjusted_score"],
        "score_breakdown": {
            "raw_score": score_pkg["raw_score"],
            "adjusted_score": score_pkg["adjusted_score"],
            "macro_adjusted_score": score_pkg.get("macro_adjusted_score"),
            "final_score": final_score,
            "triple_risk_penalty_applied": score_pkg["triple_risk_penalty_applied"],
            "exhaustion_cap_applied": score_pkg["exhaustion_cap_applied"],
            "macro_penalty_notes": score_pkg.get("macro_penalty_notes", []),
            "sector": per_symbol_cfg.get("_sector"),
            "rubric_audit": score_pkg.get("score_audit", []),
        },
        "trend_status": _trend_status(last),
        "momentum_status": _momentum_status(last),
        "volume_status": _volume_status(last),
        "money_flow_status": _money_flow_status(last),
        "volatility_status": _volatility_status(last),
        "market_context": market_ctx,
        "macro_overlay": macro,
        "foreign_snapshot": foreign,
        "backtest_summary": (
            {k: backtest.get(k) for k in ("by_state", "overall", "as_of")}
            if backtest else None
        ),
        "adx_status": adx_status,
        "ichimoku_status": ichi_status,
        "liquidity_status": liquidity,
        "relative_strength": rs,
        "weekly_trend": _str(last, "weekly_trend"),
        "structure_label": _str(last, "structure_label"),
        "entry_strategy": strategy,
        "entry_zones": zones,
        "stop_loss": stop,
        "resistance_levels": resistance,
        "support_levels": support,
        "primary_target": target,
        "next_session_playbook": playbook,
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
    L.append(f"- **{snap['technical_state']}**" + (f" → sub: `{snap.get('sub_state')}`" if snap.get("sub_state") else ""))
    L.append(f"- trend_status: {snap['trend_status']}")
    L.append(f"- momentum_status: {snap['momentum_status']}")
    L.append(f"- volume_status: {snap['volume_status']}")
    L.append(f"- money_flow_status: {snap['money_flow_status']}")
    L.append(f"- volatility_status: {snap['volatility_status']}")
    adx_st = snap.get("adx_status") or {}
    if adx_st.get("adx") is not None:
        L.append(
            f"- adx_status: ADX={adx_st['adx']} ({adx_st['strength']}), "
            f"+DI={adx_st.get('plus_di')} / -DI={adx_st.get('minus_di')} → {adx_st.get('direction')}"
        )
    ich = snap.get("ichimoku_status") or {}
    if ich.get("cloud_position"):
        L.append(
            f"- ichimoku: {ich['cloud_position']}, cloud={ich.get('cloud_color')}, "
            f"TK cross={ich.get('tk_cross')} (Tenkan={ich.get('tenkan')}, Kijun={ich.get('kijun')})"
        )
    liq = snap.get("liquidity_status") or {}
    if liq:
        L.append(
            f"- liquidity: turnover_20d_avg={liq.get('turnover_20d_avg_thousand_vnd')} (thousand VND), "
            f"ok={liq.get('ok')} — {liq.get('note')}"
        )
    L.append("")

    L.append("## 2. Confidence score")
    L.append("")
    sb = snap["score_breakdown"]
    if sb.get("sector"):
        L.append(f"- sector: `{sb['sector']}`")
    L.append(f"- raw_score: **{sb['raw_score']}**")
    L.append(f"- adjusted_score: **{sb['adjusted_score']}**  "
             f"(triple_risk_penalty_applied: {sb['triple_risk_penalty_applied']})")
    if sb.get("macro_adjusted_score") is not None:
        L.append(f"- macro_adjusted_score: **{sb['macro_adjusted_score']}**")
        for n in sb.get("macro_penalty_notes", []):
            L.append(f"    - {n}")
    L.append(f"- final_score: **{sb['final_score']} / 100**  "
             f"(exhaustion_cap_applied: {sb['exhaustion_cap_applied']})")
    L.append("")

    L.append("## 3. Entry strategy")
    L.append("")
    L.append(f"- {snap['entry_strategy']}")
    L.append("")

    L.append("## 4. Entry zones (R:R + position sizing)")
    L.append("")
    if not snap["entry_zones"]:
        L.append("- _no zones derivable from indicators_")
    else:
        L.append("| Zone | Range | Entry ref | Target | R:R | Size %NAV | Notional / 100m NAV | Note |")
        L.append("|---|---|---|---|---|---|---|---|")
        for z in snap["entry_zones"]:
            if "lower" in z and "upper" in z:
                rng = f"{_fmt_num(z['lower'])} – {_fmt_num(z['upper'])}"
            elif "level" in z:
                rng = f"{_fmt_num(z['level'])}"
            else:
                rng = "—"
            entry_ref = _fmt_num(z.get("entry_ref"))
            target_ref = _fmt_num(z.get("target_ref"))
            rr = z.get("risk_reward")
            rr_str = f"{rr:.2f}" if isinstance(rr, (int, float)) else "—"
            size_pct = z.get("size_pct_nav")
            size_str = f"{size_pct:.2f}%" if isinstance(size_pct, (int, float)) else "—"
            notional = z.get("notional_per_100m_nav")
            notional_str = f"{int(notional):,}" if isinstance(notional, (int, float)) else "—"
            note_bits = []
            if z.get("rr_invalid_reason") == "entry_below_or_at_primary_stop":
                note_bits.append("entry < stop ⚠️ (stop bị thiết kế gần hơn entry — không thực thi)")
            elif z.get("rr_invalid_reason") == "entry_above_or_at_target":
                note_bits.append("entry > target ⚠️ (target gần hơn entry — chờ target xa hơn)")
            elif z.get("low_rr_warning"):
                note_bits.append("R:R < 1.5 ⚠️")
            if z.get("rationale"):
                note_bits.append(z["rationale"])
            note_str = " · ".join(note_bits) if note_bits else "—"
            L.append(
                f"| {z['name']} | {rng} | {entry_ref} | {target_ref} | {rr_str} | {size_str} | {notional_str} | {note_str} |"
            )
    L.append("")
    L.append(
        "> Size dựa trên 1% NAV risk/lệnh, cap 20% concentration, "
        "ATR%-scaled (ATR% > 1.5% giảm size), liquidity floor cắt về 5% nếu turnover < ngưỡng. "
        "Notional cho NAV 100 triệu VND."
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

    # ---- Market context ----
    L.append("## 9. Bối cảnh thị trường")
    L.append("")
    mc = snap.get("market_context")
    rs = snap.get("relative_strength")
    if not mc:
        L.append("- _missing_data — chưa fetch market_context_{DATE}.json_")
    else:
        L.append(f"- VNINDEX regime: **{mc.get('regime','unknown')}**")
        L.append(
            f"- VNINDEX close={_fmt_num(mc.get('close'))}, SMA20={_fmt_num(mc.get('sma20'))}, "
            f"SMA50={_fmt_num(mc.get('sma50'))}, SMA100={_fmt_num(mc.get('sma100'))}"
        )
        L.append(
            f"- ret_1d={_fmt_num(mc.get('ret_1d_pct'))}%, "
            f"ret_5d={_fmt_num(mc.get('ret_5d_pct'))}%, "
            f"ret_20d={_fmt_num(mc.get('ret_20d_pct'))}%"
        )
        breadth = mc.get("breadth") or {}
        if breadth and breadth.get("breadth_pct") is not None:
            L.append(
                f"- VN30 breadth: **{breadth.get('breadth_pct')}%** "
                f"({breadth.get('n_above_sma50')}/{breadth.get('n_total')} stocks > SMA50, "
                f"regime: {breadth.get('regime')})"
            )
    if rs:
        L.append(
            f"- Relative strength vs VNINDEX: **{rs.get('label')}** "
            f"(slope 20D = {rs.get('rs_slope_20d_pct')}%)"
        )
    L.append("")
    L.append(f"- weekly_trend: **{snap.get('weekly_trend')}**")
    L.append(f"- structure_label: **{snap.get('structure_label')}**")
    L.append("")

    # ---- Next-session playbook ----
    L.append("## 10. Kế hoạch phiên sau")
    L.append("")
    pb = snap.get("next_session_playbook") or {}
    L.append(f"- **base_bias**: `{pb.get('base_bias','—')}`")
    L.append(f"- rationale: {pb.get('bias_rationale','—')}")
    tgt = pb.get("primary_target")
    if tgt:
        L.append(
            f"- primary_target: **{_fmt_num(tgt['level'])}** "
            f"({tgt.get('name')}, +{tgt.get('dist_pct')}%)"
        )
    L.append("")

    monitor = pb.get("monitoring_levels") or {}
    if monitor:
        L.append("**Mức theo dõi intraday:**")
        if "must_hold" in monitor:
            L.append(f"- must_hold: **{_fmt_num(monitor['must_hold'])}** (thủng → cắt)")
        if "trigger_add" in monitor:
            L.append(f"- trigger_add: **{_fmt_num(monitor['trigger_add'])}** (vượt → add)")
        if "take_profit_1" in monitor:
            L.append(f"- take_profit_1: {_fmt_num(monitor['take_profit_1'])}")
        if "take_profit_2" in monitor:
            L.append(f"- take_profit_2: {_fmt_num(monitor['take_profit_2'])}")
        L.append("")

    scenarios = pb.get("scenarios") or []
    if scenarios:
        L.append("**4 kịch bản mở cửa:**")
        L.append("")
        L.append("| Kịch bản | Trigger | Action | Invalidation |")
        L.append("|---|---|---|---|")
        for sc in scenarios:
            L.append(
                f"| **{sc['name']}** | {sc['trigger']} | {sc['action']} | {sc['invalidation']} |"
            )
        L.append("")

    eb = pb.get("empirical_bias")
    if eb:
        warn = " ⚠️ low_sample" if eb.get("low_sample_warning") else ""
        L.append(
            f"**Historical bias** (state `{eb['state']}`, n={eb['n_samples']}{warn}): "
            f"P(up 1D)={eb['p_up_1d']}, P(up 5D)={eb['p_up_5d']}, "
            f"median ret 5D={eb['median_ret_5d_pct']}%, hit +1ATR/5D={eb['hit_target_1atr_5d']}"
        )
        L.append("")

    # ---- Macro + foreign + backtest ----
    macro = snap.get("macro_overlay")
    if macro and "tickers" in macro:
        L.append("## 11. Macro overlay")
        L.append("")
        L.append("| Ticker | Last | SMA20 | ret_5d% | ret_20d% | trend |")
        L.append("|---|---|---|---|---|---|")
        for name, info in macro["tickers"].items():
            if "error" in info:
                L.append(f"| {name} | _err: {info['error']}_ | — | — | — | — |")
                continue
            L.append(
                f"| {name} ({info.get('ticker')}) | {info.get('last_close')} | {info.get('sma20')} | "
                f"{info.get('ret_5d_pct')} | {info.get('ret_20d_pct')} | {info.get('trend')} |"
            )
        narr = macro.get("narrative", {})
        if narr:
            L.append("")
            L.append(
                f"- oil_regime: **{narr.get('oil_regime')}**, "
                f"usdvnd_regime: **{narr.get('usdvnd_regime')}**, "
                f"fx_pressure: **{narr.get('fx_pressure')}**"
            )
        L.append("")

    fg = snap.get("foreign_snapshot")
    if fg and "error" not in fg:
        L.append("## 12. Foreign flow (snapshot)")
        L.append("")
        L.append(
            f"- foreign_buy={fg.get('foreign_buy_volume'):,.0f}, "
            f"foreign_sell={fg.get('foreign_sell_volume'):,.0f}, "
            f"net={fg.get('net_foreign_volume'):,.0f}"
        )
        L.append(
            f"- share_of_total_volume: {fg.get('foreign_share_of_volume_pct')}%, "
            f"bias: **{fg.get('bias')}**"
        )
        L.append("")

    bt = snap.get("backtest_summary")
    if bt and bt.get("by_state"):
        L.append("## 13. Backtest snapshot")
        L.append("")
        overall = bt.get("overall") or {}
        if overall:
            L.append(
                f"- overall: n_trades={overall.get('n', overall.get('n_trades'))}, "
                f"hit_rate={overall.get('hit_rate')}, "
                f"avg_R={overall.get('avg_r')}, "
                f"max_dd_pct={overall.get('max_dd_pct')}"
            )
        st_row = bt["by_state"].get(snap["technical_state"])
        if st_row:
            L.append(
                f"- this state (`{snap['technical_state']}`): n={st_row.get('n')}, "
                f"hit_rate={st_row.get('hit_rate')}, avg_R={st_row.get('avg_r')}, "
                f"median_ret_pct={st_row.get('median_ret_pct')}"
            )
        L.append("")

    L.append("## 14. Final view")
    L.append("")
    L.append(snap["final_view"])
    L.append("")
    L.append(
        f"> pipeline_version: `{snap.get('pipeline_version','—')}` · "
        "Báo cáo thuần kỹ thuật. Không phải khuyến nghị mua/bán. "
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
