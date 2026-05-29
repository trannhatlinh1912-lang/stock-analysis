"""Layer 2 — Market Regime (2A core 7 pillars + hybrid trend gate).

Pillars (per configs/market_regime_spec.md):
  1 trend_long      — VNI close vs SMA200
  2 trend_medium    — VNI close vs SMA50
  3 breadth_vn30    — % VN30 > SMA50
  4 liquidity       — VN30 ΣGTGD 20d MA / 6m MA (pending vn30_liquidity_daily.py)
  5 margin_debt     — configs/margin_debt.yaml manual quarterly
  6 foreign_cum_20d — pending foreign_snapshot_daily.py
  7 volatility      — VNI ret_1d 20d std vs rolling 252d baseline

Output: data/market_regime_{DATE}.json

Reuses market_context.py for VNI fetch + breadth + SMA. Adds:
  - SMA200 trend_long gate
  - 252d vol baseline + spike detection
  - Manual loader for margin_debt
  - Score → 5-state regime per spec table
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
CONFIGS = ROOT / "configs"

sys.path.insert(0, str(ROOT / "scripts"))
from market_context import (  # noqa: E402
    INDEX_SYMBOL,
    _fetch_index,
    compute_vn30_breadth,
)
from utils.manual_loader import load_manual  # noqa: E402
from utils.invariants import check_market_regime  # noqa: E402


def _sma(s: pd.Series, n: int) -> pd.Series:
    return s.rolling(n).mean()


def _vol_baseline(close: pd.Series, lookback_days: int = 252, window: int = 20) -> dict:
    """Rolling 252-day baseline of (20-day std of ret_1d).

    Returns dict with current_vol, baseline_mean, baseline_std, spike_threshold,
    and label ∈ {normal, elevated, spike}.
    """
    ret_1d = close.pct_change()
    vol = ret_1d.rolling(window).std()
    vol_series = vol.dropna()
    if len(vol_series) < lookback_days + 1:
        return {
            "current_vol": float(vol_series.iloc[-1]) if len(vol_series) else None,
            "baseline_mean": None,
            "baseline_std": None,
            "label": "normal",
            "data_quality": "insufficient_history",
            "n_obs": int(len(vol_series)),
        }

    # baseline computed from prior 252 obs (exclude current)
    baseline_window = vol_series.iloc[-(lookback_days + 1):-1]
    mean = float(baseline_window.mean())
    std = float(baseline_window.std())
    current = float(vol_series.iloc[-1])

    spike_threshold = mean + 1.5 * std
    elevated_threshold = mean + 0.75 * std

    if current >= spike_threshold:
        label = "spike"
    elif current >= elevated_threshold:
        label = "elevated"
    else:
        label = "normal"

    return {
        "current_vol": round(current, 6),
        "baseline_mean": round(mean, 6),
        "baseline_std": round(std, 6),
        "spike_threshold": round(spike_threshold, 6),
        "label": label,
        "data_quality": "high",
        "n_obs": int(len(vol_series)),
    }


def _trend_pillar(close: float, sma: float | None) -> str:
    if sma is None or pd.isna(sma):
        return "missing"
    if close > sma:
        return "up"
    if close < sma:
        return "down"
    return "flat"


def _liquidity_pillar() -> dict:
    """Read precomputed VN30 liquidity if present, else missing."""
    today = date.today().isoformat()
    p = DATA / f"vn30_liquidity_{today}.json"
    if not p.exists():
        return {"label": "missing", "ratio_20d_vs_6m": None}
    try:
        d = json.loads(p.read_text())
    except Exception:
        return {"label": "missing", "ratio_20d_vs_6m": None}
    ratio = d.get("ratio_20d_vs_6m")
    if ratio is None:
        return {"label": "missing", "ratio_20d_vs_6m": None}
    if ratio >= 1.1:
        label = "rising"
    elif ratio <= 0.9:
        label = "falling"
    else:
        label = "flat"
    return {"label": label, "ratio_20d_vs_6m": round(ratio, 4)}


def _margin_pillar() -> dict:
    env = load_manual(CONFIGS / "margin_debt.yaml", "margin_debt")
    if env["status"] in ("missing", "parse_error"):
        return {"label": "missing", "ratio_pct": None, "manual_status": env["status"], "effect": env["effect"]}
    data = env["data"] or {}
    ratio = data.get("ratio_pct") or data.get("latest", {}).get("ratio_pct")
    if ratio is None:
        return {"label": "missing", "ratio_pct": None, "manual_status": "no_ratio"}
    if ratio < 50:
        label = "safe"
    elif ratio > 80:
        label = "stretched"
    else:
        label = "elevated"
    return {"label": label, "ratio_pct": ratio, "manual_status": env["status"]}


FOREIGN_FULL_DAYS = 20        # full ±1 vote needs this many distinct days
FOREIGN_WEAK_MIN_DAYS = 5     # weak ±0.5 vote allowed from here
FOREIGN_SUSTAINED_FRAC = 0.6  # share of days one-sided to call it sustained
FOREIGN_OUTLIER_MULT = 3.0    # |net| > this × median = likely deal/ETF, discount


def _foreign_pillar() -> dict:
    """Market foreign-flow pillar from foreign_history.csv.

    foreign_history.csv holds one row per (date, ticker). Aggregate net_vnd by
    DATE (market-wide daily net), then judge the trailing window. We do NOT
    ignore selling — we scale the vote by how much we can trust it:

      - >=20 distinct days + one-sided >=60% of days → full vote (±1),
        case 'informed_sustained_(sell|buy)'.
      - 5-19 days, or choppy → weak vote (±0.5), case 'partial_or_choppy'.
      - <5 days → 'data_insufficient' (can't tell a one-off spike from a
        trend) → 0 weight.

    A single day whose |net| exceeds FOREIGN_OUTLIER_MULT × the median |net| of
    the window is treated as a likely one-off (block deal / ETF rebalance) and
    excluded from the cumulative, so a mechanical flow doesn't masquerade as a
    directional opinion.
    """
    p = DATA / "foreign_history.csv"
    if not p.exists():
        return {"label": "missing", "cum_20d_vnd": None}
    try:
        df = pd.read_csv(p)
    except Exception:
        return {"label": "missing", "cum_20d_vnd": None}
    if "net_vnd" not in df.columns or "date" not in df.columns:
        return {"label": "missing", "cum_20d_vnd": None}
    df["date"] = pd.to_datetime(df["date"])
    daily = df.groupby("date")["net_vnd"].sum().sort_index()
    n_days = int(daily.shape[0])
    if n_days < FOREIGN_WEAK_MIN_DAYS:
        return {
            "label": "data_insufficient",
            "cum_20d_vnd": None,
            "n_days": n_days,
            "data_quality": "low",
            "case": "insufficient_history",
            "note": f"<{FOREIGN_WEAK_MIN_DAYS}d: cannot distinguish spike vs trend",
        }

    window = daily.tail(FOREIGN_FULL_DAYS)
    n_used = int(window.shape[0])
    absw = window.abs()
    med = float(absw.median())
    outliers = absw > (FOREIGN_OUTLIER_MULT * med) if med > 0 else (absw < 0)
    n_outliers = int(outliers.sum())
    core = window[~outliers] if n_outliers else window
    cum = float(core.sum())
    neg_frac = float((core < 0).mean()) if len(core) else 0.0
    pos_frac = float((core > 0).mean()) if len(core) else 0.0

    full = n_used >= FOREIGN_FULL_DAYS
    if cum < 0:
        sustained = neg_frac >= FOREIGN_SUSTAINED_FRAC
        label = "negative" if (full and sustained) else "negative_weak"
        case = "informed_sustained_sell" if (full and sustained) else "partial_or_choppy_sell"
    elif cum > 0:
        sustained = pos_frac >= FOREIGN_SUSTAINED_FRAC
        label = "positive" if (full and sustained) else "positive_weak"
        case = "informed_sustained_buy" if (full and sustained) else "partial_or_choppy_buy"
    else:
        label = "neutral"
        case = "balanced"
    return {
        "label": label,
        "cum_20d_vnd": cum,
        "n_days": n_days,
        "n_used": n_used,
        "neg_frac": round(neg_frac, 2),
        "pos_frac": round(pos_frac, 2),
        "outliers_excluded": n_outliers,
        "data_quality": "high" if full else "partial",
        "case": case,
    }


PILLAR_SCORE = {
    "trend_medium": {"up": 1, "down": -1, "flat": 0, "missing": 0},
    "breadth":      {"strong": 1, "weak": -1, "neutral": 0, "unknown": 0, "missing": 0},
    "liquidity":    {"rising": 1, "falling": -1, "flat": 0, "missing": 0},
    "margin_debt":  {"safe": 1, "stretched": -1, "elevated": 0, "missing": 0},
    "foreign":      {"positive": 1, "positive_weak": 0.5, "neutral": 0,
                     "negative_weak": -0.5, "negative": -1,
                     "missing": 0, "data_insufficient": 0},
    "volatility":   {"normal": 0, "elevated": -1, "spike": -2},
}


def _score_to_regime(score: int, trend_long_up: bool) -> str:
    if not trend_long_up:
        if score <= -4:
            return "CRISIS"
        return "BEARISH"
    if score >= 4:
        return "BULLISH"
    if score >= 1:
        return "NEUTRAL"
    if score >= -3:
        return "NEUTRAL_TO_BEARISH"
    return "BEARISH"


REGIME_NAV_CAP = {
    "BULLISH": 90,
    "NEUTRAL": 70,
    "NEUTRAL_TO_BEARISH": 55,
    "BEARISH": 40,
    "CRISIS": 30,
}

REGIME_MODES = {
    "BULLISH":            ["core", "swing", "t_plus"],
    "NEUTRAL":            ["core", "swing", "t_plus"],  # T+ size cap 10% per trade
    "NEUTRAL_TO_BEARISH": ["core", "swing"],
    "BEARISH":            ["core"],
    "CRISIS":             ["core"],  # opportunistic contrarian only
}


def compute_market_regime(start: str, end: str, include_breadth: bool = True) -> dict[str, Any]:
    df = _fetch_index(start, end)
    if df is None or len(df) < 200:
        return {
            "as_of": date.today().isoformat(),
            "regime": "UNKNOWN",
            "error": "insufficient_index_history",
            "n_rows": int(len(df)) if df is not None else 0,
        }

    df["sma50"] = _sma(df["close"], 50)
    df["sma200"] = _sma(df["close"], 200)
    last = df.iloc[-1]
    close = float(last["close"])
    sma50 = float(last["sma50"]) if pd.notna(last["sma50"]) else None
    sma200 = float(last["sma200"]) if pd.notna(last["sma200"]) else None

    trend_long = _trend_pillar(close, sma200)
    trend_medium = _trend_pillar(close, sma50)
    vol = _vol_baseline(df["close"])
    liquidity = _liquidity_pillar()
    margin = _margin_pillar()
    foreign = _foreign_pillar()

    if include_breadth:
        breadth = compute_vn30_breadth(start, end)
        if breadth.get("breadth_pct") is None:
            breadth_label = "missing"
        elif breadth["breadth_pct"] >= 55:
            breadth_label = "strong"
        elif breadth["breadth_pct"] <= 40:
            breadth_label = "weak"
        else:
            breadth_label = "neutral"
    else:
        breadth = {"breadth_pct": None}
        breadth_label = "missing"

    # Score
    s = 0
    s += PILLAR_SCORE["trend_medium"].get(trend_medium, 0)
    s += PILLAR_SCORE["breadth"].get(breadth_label, 0)
    s += PILLAR_SCORE["liquidity"].get(liquidity["label"], 0)
    s += PILLAR_SCORE["margin_debt"].get(margin["label"], 0)
    s += PILLAR_SCORE["foreign"].get(foreign["label"], 0)
    s += PILLAR_SCORE["volatility"].get(vol["label"], 0)

    trend_long_up = trend_long == "up"

    # Special crisis override
    ret_20d_pct = (close / float(df["close"].iloc[-21]) - 1.0) * 100 if len(df) > 21 else 0.0
    crisis_override = (
        vol["label"] == "spike"
        and ret_20d_pct < -10
        and breadth_label == "weak"
        and (breadth.get("breadth_pct") or 100) < 30
    )

    if crisis_override:
        regime = "CRISIS"
    else:
        regime = _score_to_regime(s, trend_long_up)

    missing_pillars = []
    if trend_long == "missing":
        missing_pillars.append("trend_long")
    if trend_medium == "missing":
        missing_pillars.append("trend_medium")
    if liquidity["label"] == "missing":
        missing_pillars.append("liquidity")
    if margin["label"] == "missing":
        missing_pillars.append("margin_debt")
    if foreign["label"] == "missing":
        missing_pillars.append("foreign_cum_20d")
    if breadth_label == "missing":
        missing_pillars.append("breadth_vn30")
    confidence = max(30, 100 - 10 * len(missing_pillars))

    # NAV cap — degrade if margin missing (Guardrail 2 + spec stale rule)
    nav_cap = REGIME_NAV_CAP[regime]
    margin_effect = margin.get("effect")
    if margin_effect == "nav_cap_capped_neutral":
        nav_cap = min(nav_cap, REGIME_NAV_CAP["NEUTRAL"])

    result = {
        "as_of": last["time"].strftime("%Y-%m-%d"),
        "regime": regime,
        "confidence_pct": confidence,
        "score": round(float(s), 1),
        "trend_long_gate_passed": trend_long_up,
        "ret_20d_pct": round(ret_20d_pct, 3),
        "pillars": {
            "trend_long": {"label": trend_long, "close": round(close, 2), "sma200": round(sma200, 2) if sma200 else None},
            "trend_medium": {"label": trend_medium, "sma50": round(sma50, 2) if sma50 else None},
            "breadth_vn30": {"label": breadth_label, "value_pct": breadth.get("breadth_pct"),
                             "caveat": "high breadth historically associated with mean reversion (2024-2026 sample)"},
            "liquidity": liquidity,
            "margin_debt": margin,
            "foreign_cum_20d": foreign,
            "volatility": vol,
        },
        "missing_pillars": missing_pillars,
        "trading_modes_allowed": REGIME_MODES[regime],
        "nav_deploy_cap_pct": nav_cap,
        "crisis_override_fired": crisis_override,
        "manual_inputs_status": {
            "margin_debt": {
                "status": margin.get("manual_status", "unknown"),
                "effect": margin_effect,
            },
        },
    }
    check_market_regime(result)
    return result


def main():
    p = argparse.ArgumentParser(description="Layer 2 Market Regime daily compute.")
    p.add_argument("--start", help="Index history start YYYY-MM-DD")
    p.add_argument("--end", help="Index history end YYYY-MM-DD")
    p.add_argument("--no-breadth", action="store_true", help="Skip VN30 breadth (slow).")
    args = p.parse_args()

    end = args.end or date.today().isoformat()
    start = args.start or (date.today() - timedelta(days=365 * 3)).isoformat()
    print(f"[market_regime] start={start} end={end} breadth={not args.no_breadth}")

    result = compute_market_regime(start, end, include_breadth=not args.no_breadth)

    out_path = DATA / f"market_regime_{date.today().isoformat()}.json"
    out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2))
    print(f"[market_regime] → {out_path}")
    print(f"\nRegime: {result['regime']} (score={result.get('score')}, conf={result.get('confidence_pct')}%)")
    print(f"Trading modes: {result.get('trading_modes_allowed')}")
    print(f"NAV cap: {result.get('nav_deploy_cap_pct')}%")
    print(f"Missing pillars: {result.get('missing_pillars')}")


if __name__ == "__main__":
    main()
