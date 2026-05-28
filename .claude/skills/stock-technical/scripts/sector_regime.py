"""Layer 3 — Sector Regime (Universal tier: RS + Breadth + Flow).

Phase 1 scope: 3 universal dimensions auto-computed for all 7 sectors.
Sector-specific cycle proxy (3.4) deferred to Phase 2 (separate scripts:
banking_nim_proxy, re_ocf_trend, steel_inv_turnover, consumer_sssg_proxy).

When cycle missing → contribution=0, flag `cycle_data_missing`, confidence -10%.

Output: data/sector_regime_{DATE}.json (all sectors in one file).
"""
from __future__ import annotations

import argparse
import json
import sys
import warnings
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yaml

warnings.filterwarnings("ignore")

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
CACHE_DIR = DATA / "sector_prices"
CONFIGS = ROOT / "configs"

sys.path.insert(0, str(ROOT / "scripts"))
from market_context import _fetch_index, INDEX_SYMBOL  # noqa: E402


def _load_watchlist() -> dict:
    with (CONFIGS / "watchlist.yaml").open("r") as f:
        return yaml.safe_load(f)


def _fetch_ohlc(symbol: str, start: str, end: str) -> pd.DataFrame | None:
    """Fetch + cache (one CSV per symbol per day)."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    today = date.today().isoformat()
    cache_path = CACHE_DIR / f"{symbol}_{today}.csv"
    if cache_path.exists():
        df = pd.read_csv(cache_path)
        df["time"] = pd.to_datetime(df["time"])
        return df
    try:
        from vnstock.api.quote import Quote
        q = Quote(symbol=symbol, source="VCI")
        df = q.history(start=start, end=end, interval="1D")
    except Exception as e:
        print(f"[sector_regime] fetch fail {symbol}: {str(e)[:80]}", file=sys.stderr)
        return None
    if df is None or len(df) == 0:
        return None
    df = df.copy()
    df.columns = [c.lower() for c in df.columns]
    if "time" in df.columns:
        df["time"] = pd.to_datetime(df["time"])
    elif "date" in df.columns:
        df["time"] = pd.to_datetime(df["date"])
    df = df.sort_values("time").reset_index(drop=True)
    df.to_csv(cache_path, index=False)
    return df


def _basket_close(basket: list[str], start: str, end: str) -> tuple[pd.DataFrame, list[str]]:
    """Equal-weight basket close series. Returns (df with time + basket_close, members_used)."""
    series = {}
    members_used = []
    for sym in basket:
        df = _fetch_ohlc(sym, start, end)
        if df is None or len(df) < 50:
            continue
        s = df.set_index("time")["close"]
        # Normalize to first value (so equal-weight by % return)
        s_norm = s / s.iloc[0] * 100
        series[sym] = s_norm
        members_used.append(sym)
    if not series:
        return pd.DataFrame(), []
    combined = pd.DataFrame(series).dropna(how="all")
    combined["basket"] = combined.mean(axis=1)
    return combined.reset_index(), members_used


def _rs_dimension(basket_df: pd.DataFrame, vni_df: pd.DataFrame) -> dict:
    if basket_df.empty or vni_df.empty:
        return {"label": "missing", "rs_slope_20d_pct": None}
    b = basket_df[["time", "basket"]].rename(columns={"basket": "b_close"})
    v = vni_df[["time", "close"]].rename(columns={"close": "v_close"})
    m = b.merge(v, on="time", how="inner").sort_values("time").reset_index(drop=True)
    if len(m) < 25:
        return {"label": "missing", "rs_slope_20d_pct": None, "n_days": len(m)}
    m["rs"] = m["b_close"] / m["v_close"]
    rs_now = float(m["rs"].iloc[-1])
    rs_20 = float(m["rs"].iloc[-21])
    slope_pct = (rs_now / rs_20 - 1.0) * 100
    if slope_pct > 2:
        label = "leader"
    elif slope_pct < -2:
        label = "laggard"
    else:
        label = "inline"
    return {"label": label, "rs_slope_20d_pct": round(slope_pct, 3), "rs_now": round(rs_now, 6)}


def _breadth_dimension(basket: list[str], start: str, end: str) -> dict:
    above = 0
    total = 0
    for sym in basket:
        df = _fetch_ohlc(sym, start, end)
        if df is None or len(df) < 55:
            continue
        close = df["close"].dropna()
        if len(close) < 50:
            continue
        sma50 = float(close.tail(50).mean())
        last = float(close.iloc[-1])
        total += 1
        if last > sma50:
            above += 1
    if total == 0:
        return {"label": "missing", "pct": None}
    pct = above / total * 100
    if pct >= 60:
        label = "strong"
    elif pct < 40:
        label = "weak"
    else:
        label = "neutral"
    return {"label": label, "pct": round(pct, 2), "n_above": above, "n_total": total}


def _flow_dimension(basket: list[str]) -> dict:
    p = DATA / "foreign_history.csv"
    if not p.exists():
        return {"label": "data_insufficient", "cum_20d_vnd": None}
    try:
        df = pd.read_csv(p)
    except Exception:
        return {"label": "data_insufficient", "cum_20d_vnd": None}
    if "date" in df.columns:
        df["date"] = pd.to_datetime(df["date"])
    if not {"ticker", "net_vnd"}.issubset(df.columns):
        return {"label": "data_insufficient", "cum_20d_vnd": None}
    sub = df[df["ticker"].isin(basket)].sort_values("date")
    if sub["date"].nunique() < 20:
        return {"label": "data_insufficient", "cum_20d_vnd": None, "n_days": int(sub["date"].nunique())}
    recent_dates = sorted(sub["date"].unique())[-20:]
    cum = float(sub[sub["date"].isin(recent_dates)]["net_vnd"].sum())
    if cum > 0:
        label = "positive"
    elif cum < 0:
        label = "negative"
    else:
        label = "neutral"
    return {"label": label, "cum_20d_vnd": cum}


SCORE_MAP = {
    "rs":      {"leader": 1, "laggard": -1, "inline": 0, "missing": 0},
    "breadth": {"strong": 1, "weak": -1, "neutral": 0, "missing": 0},
    "flow":    {"positive": 1, "negative": -1, "neutral": 0, "data_insufficient": 0},
    "cycle":   {"expanding": 1, "compressing": -1, "stable": 0, "missing": 0},
}


def _score_to_state(score: int, ret_20d_pct: float, positive_dims: int) -> str:
    if ret_20d_pct < -15 and positive_dims == 0:
        return "CRISIS"
    if score >= 3:
        return "BULLISH"
    if score >= 1:
        return "NEUTRAL_TO_BULLISH"
    if score == 0:
        return "NEUTRAL"
    if score >= -2:
        return "NEUTRAL_TO_BEARISH"
    return "BEARISH"


MODIFIER = {
    "BULLISH":            {"swing_pct_mod": +3, "t_plus_allowed": True,  "catalyst_required": False},
    "NEUTRAL_TO_BULLISH": {"swing_pct_mod": +1, "t_plus_allowed": True,  "catalyst_required": False},
    "NEUTRAL":            {"swing_pct_mod": 0,  "t_plus_allowed": True,  "catalyst_required": False},
    "NEUTRAL_TO_BEARISH": {"swing_pct_mod": -2, "t_plus_allowed": False, "catalyst_required": True},
    "BEARISH":            {"swing_pct_mod": -5, "t_plus_allowed": False, "catalyst_required": True},
    "CRISIS":             {"swing_pct_mod": -99, "t_plus_allowed": False, "catalyst_required": True},
}


def _cycle_dimension(sector_name: str) -> dict:
    """Read latest sector_cycle/{sector}_{DATE}.json if present."""
    today = date.today().isoformat()
    # Real Estate uses 'real_estate' file name; Securities + Banking + others same
    p = DATA / "sector_cycle" / f"{sector_name}_{today}.json"
    if not p.exists():
        # Fallback: most recent file for this sector
        candidates = sorted((DATA / "sector_cycle").glob(f"{sector_name}_*.json"),
                            reverse=True) if (DATA / "sector_cycle").exists() else []
        if not candidates:
            return {"label": "missing", "note": "no_cycle_proxy_output"}
        p = candidates[0]
    try:
        d = json.loads(p.read_text())
    except Exception:
        return {"label": "missing", "note": "parse_error"}
    agg = d.get("aggregate", {})
    sector_trend = agg.get("sector_trend", "missing")
    # Map sector_trend label → universal cycle label
    label_map = {
        "expanding": "expanding", "improving": "expanding", "accelerating": "expanding",
        "compressing": "compressing", "declining": "compressing",
        "stable": "stable",
        "missing": "missing", "insufficient_data": "missing",
    }
    label = label_map.get(sector_trend, "missing")
    return {
        "label": label,
        "sector_trend_raw": sector_trend,
        "metric": d.get("metric"),
        "source_file": str(p.name),
        "n_valid": agg.get("n_valid"),
    }


def compute_sector(sector_name: str, basket: list[str], start: str, end: str, vni_df: pd.DataFrame) -> dict:
    basket_df, members_used = _basket_close(basket, start, end)
    if not members_used:
        return {
            "sector": sector_name,
            "regime": "UNKNOWN",
            "error": "no_basket_data",
            "basket_requested": basket,
        }

    rs = _rs_dimension(basket_df, vni_df)
    breadth = _breadth_dimension(basket, start, end)
    flow = _flow_dimension(basket)
    cycle = _cycle_dimension(sector_name)

    # Score
    s = 0
    positive_dims = 0
    for dim_key, dim_value in [("rs", rs["label"]), ("breadth", breadth["label"]), ("flow", flow["label"]), ("cycle", cycle["label"])]:
        contrib = SCORE_MAP[dim_key].get(dim_value, 0)
        s += contrib
        if contrib > 0:
            positive_dims += 1

    # basket ret_20d for CRISIS check
    if not basket_df.empty and len(basket_df) > 21:
        ret_20d = (float(basket_df["basket"].iloc[-1]) / float(basket_df["basket"].iloc[-21]) - 1) * 100
    else:
        ret_20d = 0.0

    state = _score_to_state(s, ret_20d, positive_dims)

    missing_dims = []
    for k, v in [("rs", rs["label"]), ("breadth", breadth["label"]), ("flow", flow["label"]), ("cycle", cycle["label"])]:
        if v in ("missing", "data_insufficient"):
            missing_dims.append(k)
    confidence = max(30, 100 - 25 * len(missing_dims))

    return {
        "sector": sector_name,
        "as_of": date.today().isoformat(),
        "regime": state,
        "score": int(s),
        "confidence_pct": confidence,
        "ret_20d_pct": round(ret_20d, 3),
        "basket_members_used": members_used,
        "basket_members_skipped": [m for m in basket if m not in members_used],
        "dimensions": {
            "rs": rs,
            "breadth": breadth,
            "flow": flow,
            "cycle": cycle,
        },
        "missing_dimensions": missing_dims,
        "trading_mode_modifiers": MODIFIER[state],
    }


def main() -> int:
    p = argparse.ArgumentParser(description="Layer 3 Sector Regime (universal tier).")
    p.add_argument("--start", help="History start YYYY-MM-DD")
    p.add_argument("--end", help="History end YYYY-MM-DD")
    p.add_argument("--sectors", nargs="+", help="Subset sectors. Default: all.")
    args = p.parse_args()

    end = args.end or date.today().isoformat()
    start = args.start or (date.today() - timedelta(days=365 * 2)).isoformat()
    print(f"[sector_regime] start={start} end={end}")

    wl = _load_watchlist()
    baskets = wl["sector_baskets"]
    if args.sectors:
        baskets = {k: v for k, v in baskets.items() if k in args.sectors}

    vni_df = _fetch_index(start, end)
    if vni_df is None or len(vni_df) < 30:
        print("[sector_regime] VNINDEX fetch failed; aborting", file=sys.stderr)
        return 1

    results = {}
    for sector, basket in baskets.items():
        print(f"  computing {sector}: {basket}")
        results[sector] = compute_sector(sector, basket, start, end, vni_df)

    out = {
        "as_of": date.today().isoformat(),
        "sectors": results,
    }
    out_path = DATA / f"sector_regime_{date.today().isoformat()}.json"
    out_path.write_text(json.dumps(out, ensure_ascii=False, indent=2))
    print(f"\n[sector_regime] → {out_path}")

    print("\nSummary:")
    for sec, r in results.items():
        print(f"  {sec:14s}  {r.get('regime'):20s} score={r.get('score'):+d}  conf={r.get('confidence_pct')}%  members={len(r.get('basket_members_used', []))}/{len(baskets[sec])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
