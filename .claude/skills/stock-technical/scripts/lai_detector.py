"""Layer 7 — Lái Detector.

6 symptoms (per configs/lai_detection_spec.md):
  1. Vol spike + no news       AUTO (vol_ratio > 3 + |ret|>5% + news_count_5d=0)
  2. Insider deal heavy        DEFER (needs 90d insider snapshot cache)
  3. Prop trade active         MANUAL (configs/lai_manual_flags.yaml)
  4. Foreign-retail divergence AUTO (5d foreign_history + price_up)
  5. ATC manipulation          MANUAL
  6. Pump pattern              AUTO (5/10 days with +5% return)

Mode-specific yellow/red triggers:
  Core  yellow=3 red=4+
  Swing yellow=2 red=3+
  T+    yellow=1 red=2+

Telemetry (Guardrail 3): every fire appended to data/lai_signal_history.jsonl.
Output: data/lai/{TICKER}.json
Warning_level not "verdict". User override allowed.
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
import yaml

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
CONFIGS = ROOT / "configs"
HIST_LOG = DATA / "lai_signal_history.jsonl"

sys.path.insert(0, str(ROOT / "scripts"))
from utils.manual_loader import load_manual  # noqa: E402


# Symptom thresholds (configurable, not hardcoded magic)
THRESHOLDS = {
    "vol_spike_x_ma20": 3.0,
    "ret_1d_pct_abs": 5.0,
    "pump_pos_5pct_days_min": 5,
    "pump_news_max_10d": 1,
    "foreign_5d_window": 5,
    "foreign_price_up_pct": 5.0,
}

MODE_TIER = {
    "core":   {"yellow": 3, "red": 4},
    "swing":  {"yellow": 2, "red": 3},
    "t_plus": {"yellow": 1, "red": 2},
}

NON_SUBSTANTIVE_NEWS_KEYWORDS = [
    "thông báo định kỳ",
    "cập nhật giao dịch",
    "thay đổi nhỏ",
]


def _load_indicators_tail(symbol: str, n: int = 30) -> pd.DataFrame | None:
    p = DATA / f"{symbol}_indicators.csv"
    if not p.exists():
        return None
    df = pd.read_csv(p)
    if df.empty:
        return None
    df["date"] = pd.to_datetime(df.get("date"))
    return df.tail(n).reset_index(drop=True)


def _fetch_news_count_substantive(symbol: str, days: int) -> int | None:
    """Use vnstock Company.news() within last N days. Returns None on API fail."""
    try:
        from vnstock.api.company import Company
        c = Company(symbol=symbol, source="VCI")
        news = c.news()
    except Exception:
        return None
    if news is None or len(news) == 0:
        return 0
    df = news.copy()
    df.columns = [c.lower() for c in df.columns]
    date_col = next((c for c in ["public_date", "date", "release_date"] if c in df.columns), None)
    if date_col is None:
        return None
    df[date_col] = pd.to_datetime(df[date_col], errors="coerce")
    cutoff = pd.Timestamp(date.today() - timedelta(days=days))
    recent = df[df[date_col] >= cutoff]
    if "title" in recent.columns:
        substantive = recent[~recent["title"].fillna("").str.lower().str.contains(
            "|".join(NON_SUBSTANTIVE_NEWS_KEYWORDS), regex=True
        )]
    else:
        substantive = recent
    return int(len(substantive))


def symptom_1_vol_spike_no_news(symbol: str, ind: pd.DataFrame, skip_news: bool = False) -> dict | None:
    if ind is None or len(ind) < 2:
        return None
    last = ind.iloc[-1]
    vol_ratio = last.get("vol_ratio")
    ret_1d = (last["close"] / ind["close"].iloc[-2] - 1) * 100 if len(ind) >= 2 else 0
    if pd.isna(vol_ratio) or vol_ratio <= THRESHOLDS["vol_spike_x_ma20"]:
        return None
    if abs(ret_1d) < THRESHOLDS["ret_1d_pct_abs"]:
        return None
    news_count = None if skip_news else _fetch_news_count_substantive(symbol, days=5)
    if news_count is None and not skip_news:
        return {
            "id": 1,
            "name": "vol_spike_no_news",
            "fired": False,
            "data_quality": "news_api_unavailable",
            "vol_ratio": float(vol_ratio),
            "ret_1d_pct": float(ret_1d),
        }
    if (skip_news or news_count == 0):
        return {
            "id": 1,
            "name": "vol_spike_no_news",
            "fired": True,
            "window": "5_day",
            "vol_ratio": float(vol_ratio),
            "ret_1d_pct": float(ret_1d),
            "news_count_5d": news_count,
            "severity": "high",
            "detected_by": "auto",
        }
    return {
        "id": 1, "name": "vol_spike_no_news", "fired": False,
        "vol_ratio": float(vol_ratio), "ret_1d_pct": float(ret_1d),
        "news_count_5d": news_count,
    }


def symptom_4_foreign_retail_divergence(symbol: str, ind: pd.DataFrame) -> dict | None:
    p = DATA / "foreign_history.csv"
    if not p.exists():
        return {"id": 4, "name": "foreign_retail_divergence", "fired": False,
                "data_quality": "no_foreign_history"}
    fh = pd.read_csv(p)
    fh["date"] = pd.to_datetime(fh["date"])
    sub = fh[fh["ticker"] == symbol].sort_values("date").tail(THRESHOLDS["foreign_5d_window"])
    if len(sub) < THRESHOLDS["foreign_5d_window"]:
        return {"id": 4, "name": "foreign_retail_divergence", "fired": False,
                "data_quality": f"insufficient_history_n={len(sub)}"}
    net_5d = float(sub["net_vnd"].sum()) if "net_vnd" in sub.columns else None
    if ind is None or len(ind) < THRESHOLDS["foreign_5d_window"] + 1:
        return {"id": 4, "name": "foreign_retail_divergence", "fired": False,
                "data_quality": "insufficient_price_history"}
    price_5d_ago = ind["close"].iloc[-(THRESHOLDS["foreign_5d_window"] + 1)]
    price_now = ind["close"].iloc[-1]
    price_change_5d = (price_now / price_5d_ago - 1) * 100
    fired = net_5d is not None and net_5d < 0 and price_change_5d > THRESHOLDS["foreign_price_up_pct"]
    return {
        "id": 4,
        "name": "foreign_retail_divergence",
        "fired": bool(fired),
        "window": "5_day",
        "foreign_net_5d_vnd": net_5d,
        "price_change_5d_pct": float(price_change_5d),
        "severity": "high" if fired else "info",
        "detected_by": "auto",
    }


def symptom_6_pump_pattern(symbol: str, ind: pd.DataFrame, skip_news: bool = False) -> dict | None:
    if ind is None or len(ind) < 11:
        return None
    last_11 = ind.tail(11)
    closes = last_11["close"].values
    rets = [(closes[i] / closes[i - 1] - 1) * 100 for i in range(1, len(closes))]
    positive_5pct_days = sum(1 for r in rets if r > 5)
    news_count = None if skip_news else _fetch_news_count_substantive(symbol, days=10)
    if positive_5pct_days < THRESHOLDS["pump_pos_5pct_days_min"]:
        return {"id": 6, "name": "pump_pattern", "fired": False,
                "positive_5pct_days_in_10d": positive_5pct_days}
    if news_count is None and not skip_news:
        return {"id": 6, "name": "pump_pattern", "fired": False,
                "data_quality": "news_api_unavailable",
                "positive_5pct_days_in_10d": positive_5pct_days}
    fired = skip_news or news_count <= THRESHOLDS["pump_news_max_10d"]
    return {
        "id": 6,
        "name": "pump_pattern",
        "fired": bool(fired),
        "window": "10_day",
        "positive_5pct_days_in_10d": positive_5pct_days,
        "news_count_10d": news_count,
        "severity": "medium" if fired else "info",
        "detected_by": "auto",
    }


def symptom_2_insider_placeholder() -> dict:
    return {
        "id": 2,
        "name": "insider_deal_heavy",
        "fired": False,
        "data_quality": "pending_90d_cache_build_up",
        "detected_by": "auto",
    }


def load_manual_symptoms(ticker: str, manual_env: dict, overrides_env: dict) -> list[dict]:
    out: list[dict] = []
    if manual_env["data"] is not None and manual_env["status"] != "stale":
        flags = (manual_env["data"].get("flags_by_ticker") or {}).get(ticker, []) or []
        today = date.today()
        for f in flags:
            expires = f.get("expires_at")
            try:
                exp_date = pd.Timestamp(expires).date() if expires else None
            except Exception:
                exp_date = None
            if exp_date and exp_date < today:
                continue
            sid = f.get("symptom_id", "")
            if sid.startswith("3"):
                out.append({"id": 3, "name": "prop_trade_active", "fired": True,
                            "severity": f.get("severity", "medium"),
                            "evidence": f.get("evidence"), "detected_by": "manual"})
            elif sid.startswith("5"):
                out.append({"id": 5, "name": "atc_manipulation", "fired": True,
                            "severity": f.get("severity", "medium"),
                            "evidence": f.get("evidence"), "detected_by": "manual"})
    elif manual_env["status"] == "stale":
        out.append({"id": 3, "name": "prop_trade_active", "fired": False,
                    "data_quality": "manual_stale_ignored"})
        out.append({"id": 5, "name": "atc_manipulation", "fired": False,
                    "data_quality": "manual_stale_ignored"})
    return out


def _apply_overrides(symptoms: list[dict], ticker: str, overrides_env: dict) -> list[int]:
    """Return list of symptom IDs suppressed by override."""
    if overrides_env["data"] is None:
        return []
    ovs = (overrides_env["data"].get("overrides_by_ticker") or {}).get(ticker, [])
    suppressed: list[int] = []
    today = date.today()
    for o in ovs:
        until = o.get("override_until")
        try:
            until_date = pd.Timestamp(until).date() if until else None
        except Exception:
            until_date = None
        if until_date and until_date < today:
            continue
        suppressed.extend(o.get("symptom_ids", []))
    return suppressed


def _assess_mode(active_count: int, mode: str) -> str:
    t = MODE_TIER[mode]
    if active_count >= t["red"]:
        return "red"
    if active_count >= t["yellow"]:
        return "yellow"
    return "green"


def _recommend(level: str, mode: str) -> str:
    if level == "red":
        return {"core": "skip_new_entry_hold_if_thesis_intact",
                "swing": "skip",
                "t_plus": "skip_immediately"}[mode]
    if level == "yellow":
        return {"core": "monitor_closely",
                "swing": "size_cut_50pct_or_skip",
                "t_plus": "size_cut_50pct_or_skip"}[mode]
    return "no_action"


def detect_for_ticker(ticker: str, manual_env: dict, overrides_env: dict,
                      skip_news: bool = False) -> dict:
    ind = _load_indicators_tail(ticker, n=30)
    symptoms = []
    for fn in [
        lambda: symptom_1_vol_spike_no_news(ticker, ind, skip_news=skip_news),
        lambda: symptom_2_insider_placeholder(),
        lambda: symptom_4_foreign_retail_divergence(ticker, ind),
        lambda: symptom_6_pump_pattern(ticker, ind, skip_news=skip_news),
    ]:
        r = fn()
        if r is not None:
            symptoms.append(r)
    symptoms.extend(load_manual_symptoms(ticker, manual_env, overrides_env))

    suppressed = _apply_overrides(symptoms, ticker, overrides_env)
    if suppressed:
        for s in symptoms:
            if s["id"] in suppressed and s.get("fired"):
                s["fired"] = False
                s["suppressed_by_override"] = True

    active_count = sum(1 for s in symptoms if s.get("fired"))
    mode_assessment = {m: _assess_mode(active_count, m) for m in ("core", "swing", "t_plus")}
    recommendations = {m: _recommend(level, m) for m, level in mode_assessment.items()}

    data_quality_warnings = [s.get("data_quality") for s in symptoms if s.get("data_quality")]
    completeness = 100 - 25 * sum(1 for d in data_quality_warnings if d not in (None, "pending_90d_cache_build_up"))
    completeness = max(0, completeness)

    return {
        "ticker": ticker,
        "as_of": date.today().isoformat(),
        "symptoms": symptoms,
        "symptoms_active_count": active_count,
        "warning_level_per_mode": mode_assessment,
        "recommendation_per_mode": recommendations,
        "data_completeness_pct": completeness,
        "data_quality_warnings": [d for d in data_quality_warnings if d],
        "user_override_allowed": True,
        "override_path": "configs/lai_overrides.yaml",
        "manual_inputs_status": {
            "lai_manual_flags": {"status": manual_env["status"], "age_days": manual_env["age_days"]},
            "lai_overrides": {"status": overrides_env["status"], "age_days": overrides_env["age_days"]},
        },
    }


def _append_telemetry(records: list[dict]):
    HIST_LOG.parent.mkdir(parents=True, exist_ok=True)
    with HIST_LOG.open("a", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def main() -> int:
    p = argparse.ArgumentParser(description="Layer 7 Lái Detector batch.")
    p.add_argument("--tickers", nargs="+")
    p.add_argument("--skip-news", action="store_true",
                   help="Skip vnstock news fetch (faster, but symptom 1/6 less reliable).")
    args = p.parse_args()

    wl = yaml.safe_load((CONFIGS / "watchlist.yaml").read_text())
    tickers = args.tickers or wl.get("all_fetched", [])
    manual_env = load_manual(CONFIGS / "lai_manual_flags.yaml", "lai_manual_flags")
    overrides_env = load_manual(CONFIGS / "lai_overrides.yaml", "lai_manual_flags")

    out_dir = DATA / "lai"
    out_dir.mkdir(parents=True, exist_ok=True)

    telemetry: list[dict] = []
    rows = []
    for t in tickers:
        r = detect_for_ticker(t, manual_env, overrides_env, skip_news=args.skip_news)
        (out_dir / f"{t}.json").write_text(json.dumps(r, ensure_ascii=False, indent=2))
        rows.append((t, r["symptoms_active_count"],
                     r["warning_level_per_mode"]["core"],
                     r["warning_level_per_mode"]["swing"],
                     r["warning_level_per_mode"]["t_plus"]))
        if r["symptoms_active_count"] > 0:
            telemetry.append({
                "ticker": t,
                "date": r["as_of"],
                "symptoms_active": [s["id"] for s in r["symptoms"] if s.get("fired")],
                "warning_level_per_mode": r["warning_level_per_mode"],
            })

    if telemetry:
        _append_telemetry(telemetry)

    print(f"\n[lai_detector] {len(tickers)} tickers → {out_dir}")
    print(f"[lai_detector] telemetry appended n={len(telemetry)} → {HIST_LOG}")
    print()
    print(f"  {'TICKER':8s} {'ACTIVE':6s} {'CORE':6s} {'SWING':6s} T+")
    for row in sorted(rows, key=lambda x: (-x[1], x[0])):
        print(f"  {row[0]:8s} {row[1]:>5d}  {row[2]:6s} {row[3]:6s} {row[4]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
