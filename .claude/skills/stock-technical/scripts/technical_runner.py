"""Layer 6B — Technical Runner (batch wrapper for v2.6 pipeline).

For each ticker, runs the existing 3-step pipeline:
  1. fetch_price_audit.py (only if CSV missing/stale)
  2. indicator_engine.py
  3. decision_framework.py

Then reads data/{TICKER}_decision_snapshot.json and emits compact summary
into data/technical/{TICKER}.json with fields the orchestrator needs:
  - technical_state
  - confidence_score
  - close, sma20/50/100/200, rsi, vol_ratio, atr
  - rs_label (from snapshot.relative_strength)
  - mode_pass.{core,swing,t_plus}  — derived from state per L6B spec
  - entry_zones (top 2)
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
DATA = ROOT / "data"
CONFIGS = ROOT / "configs"


def _load_json(p: Path) -> dict | None:
    return json.loads(p.read_text()) if p.exists() else None


def _run(cmd: list[str], check: bool = True) -> int:
    """Run subprocess silently (stderr passthrough only on fail)."""
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0 and check:
        print(f"[technical_runner] FAILED {' '.join(cmd[:3])}... rc={r.returncode}", file=sys.stderr)
        print(r.stderr[-400:], file=sys.stderr)
    return r.returncode


def ensure_pipeline(symbol: str, start: str, end: str) -> bool:
    """Run pipeline steps as needed. Returns True if decision_snapshot exists at end."""
    price_csv = DATA / f"{symbol}_price_VCI.csv"
    indi_csv = DATA / f"{symbol}_indicators.csv"
    dec_path = DATA / f"{symbol}_decision_snapshot.json"

    # Step 1: fetch if missing
    if not price_csv.exists():
        print(f"  [{symbol}] fetching prices...")
        rc = _run([sys.executable, str(SCRIPTS / "fetch_price_audit.py"),
                   "--symbol", symbol, "--start", start, "--end", end], check=False)
        if rc != 0 or not price_csv.exists():
            return False

    # Step 2: indicators
    if not indi_csv.exists() or indi_csv.stat().st_mtime < price_csv.stat().st_mtime:
        rc = _run([sys.executable, str(SCRIPTS / "indicator_engine.py"),
                   "--csv", str(price_csv), "--symbol", symbol], check=False)
        if rc != 0 or not indi_csv.exists():
            return False

    # Step 3: decision
    if not dec_path.exists() or dec_path.stat().st_mtime < indi_csv.stat().st_mtime:
        rc = _run([sys.executable, str(SCRIPTS / "decision_framework.py"),
                   "--csv", str(indi_csv), "--symbol", symbol], check=False)
        if rc != 0 or not dec_path.exists():
            return False

    return dec_path.exists()


import pandas as pd


def _latest_indicators(symbol: str) -> dict | None:
    p = DATA / f"{symbol}_indicators.csv"
    if not p.exists():
        return None
    df = pd.read_csv(p)
    if df.empty:
        return None
    return df.iloc[-1].to_dict()


# Mode-specific technical pass (L6B spec digest). Reads numerics from
# indicators CSV; reads state/structure from decision snapshot.
def _core_tech_pass(snap: dict, ind: dict) -> tuple[bool, str]:
    close = ind.get("close")
    sma200 = ind.get("sma200")
    rsi = ind.get("rsi14")
    state = snap.get("technical_state", "")
    if pd.isna(close) or pd.isna(sma200):
        return False, "missing sma200/close"
    above_sma200 = close > sma200
    mean_revert = sma200 * 0.95 <= close <= sma200 * 1.05
    rsi_ok = not pd.isna(rsi) and 40 <= rsi <= 65
    no_breakdown = state not in ("DISTRIBUTION",)
    if (above_sma200 or mean_revert) and rsi_ok and no_breakdown:
        return True, f"close{'>' if above_sma200 else '~'}SMA200 RSI={rsi:.1f}"
    return False, (
        f"above_sma200={above_sma200} mean_revert={mean_revert} rsi={rsi} no_breakdown={no_breakdown}"
    )


def _swing_tech_pass(snap: dict, ind: dict) -> tuple[bool, str]:
    close = ind.get("close")
    sma50 = ind.get("sma50")
    vol = ind.get("vol_ratio")
    macd_hist = ind.get("macd_hist")
    atr = ind.get("atr14")
    structure = snap.get("structure_label", "")
    if pd.isna(close) or pd.isna(sma50):
        return False, "missing sma50/close"
    above_sma50 = close > sma50
    within_pullback = not pd.isna(atr) and abs(close - sma50) <= atr
    vol_ok = not pd.isna(vol) and 1.0 <= vol <= 1.5
    macd_ok = not pd.isna(macd_hist) and macd_hist >= 0
    structure_ok = structure != "downtrend"
    if (above_sma50 or within_pullback) and vol_ok and macd_ok and structure_ok:
        return True, f"above_sma50={above_sma50} vol={vol:.2f} macd_h={macd_hist:.3f}"
    return False, (
        f"above_sma50={above_sma50} pullback={within_pullback} vol={vol} "
        f"macd={macd_hist} structure={structure}"
    )


def _t_plus_tech_pass(snap: dict, ind: dict) -> tuple[bool, str]:
    state = snap.get("technical_state", "")
    vol = ind.get("vol_ratio")
    breakout_state = state in ("BREAKOUT_CONFIRMED", "BREAKOUT_WITH_EXHAUSTION_RISK",
                                "BULLISH_TREND_CONFIRMED")
    vol_ok = not pd.isna(vol) and vol >= 1.5
    if breakout_state and vol_ok:
        return True, f"state={state} vol={vol:.2f}"
    return False, f"state={state} vol={vol} breakout={breakout_state}"


def _safe(v):
    if v is None:
        return None
    try:
        if pd.isna(v):
            return None
    except (TypeError, ValueError):
        return v
    return float(v) if isinstance(v, (int, float)) else v


def summarize_snapshot(symbol: str) -> dict:
    snap = _load_json(DATA / f"{symbol}_decision_snapshot.json")
    if snap is None:
        return {"ticker": symbol, "error": "no_snapshot"}
    ind = _latest_indicators(symbol) or {}

    core_ok, core_reason = _core_tech_pass(snap, ind)
    swing_ok, swing_reason = _swing_tech_pass(snap, ind)
    tplus_ok, tplus_reason = _t_plus_tech_pass(snap, ind)

    rs = snap.get("relative_strength") or {}

    return {
        "ticker": symbol,
        "as_of": date.today().isoformat(),
        "technical_state": snap.get("technical_state"),
        "confidence_score": snap.get("confidence_score"),
        "close": _safe(ind.get("close")),
        "sma20": _safe(ind.get("sma20")),
        "sma50": _safe(ind.get("sma50")),
        "sma100": _safe(ind.get("sma100")),
        "sma200": _safe(ind.get("sma200")),
        "rsi14": _safe(ind.get("rsi14")),
        "macd_hist": _safe(ind.get("macd_hist")),
        "vol_ratio": _safe(ind.get("vol_ratio")),
        "atr14": _safe(ind.get("atr14")),
        "atr_pct": _safe(ind.get("atr_pct")),
        "structure_label": snap.get("structure_label"),
        "rs_label": rs.get("label"),
        "rs_slope_20d_pct": rs.get("rs_slope_20d_pct"),
        "weekly_trend": snap.get("weekly_trend"),
        "mode_pass": {
            "core": {"pass": core_ok, "reason": core_reason},
            "swing": {"pass": swing_ok, "reason": swing_reason},
            "t_plus": {"pass": tplus_ok, "reason": tplus_reason},
        },
        "entry_zones": (snap.get("entry_zones") or [])[:2],
        "primary_stop": (snap.get("stop_loss") or {}).get("primary_stop"),
        "hard_stop": (snap.get("stop_loss") or {}).get("hard_stop"),
    }


def main() -> int:
    p = argparse.ArgumentParser(description="Layer 6B Technical Runner (batch).")
    p.add_argument("--tickers", nargs="+")
    p.add_argument("--start", help="Fetch start. Default: today - 3y")
    p.add_argument("--end", help="Fetch end. Default: today")
    p.add_argument("--skip-fetch", action="store_true",
                   help="Only process tickers that already have a price CSV.")
    args = p.parse_args()

    today = date.today()
    end = args.end or today.isoformat()
    start = args.start or (today - timedelta(days=365 * 3)).isoformat()

    wl = yaml.safe_load((CONFIGS / "watchlist.yaml").read_text())
    tickers = args.tickers or wl.get("all_fetched", [])

    out_dir = DATA / "technical"
    out_dir.mkdir(parents=True, exist_ok=True)

    summary_rows = []
    for t in tickers:
        if args.skip_fetch and not (DATA / f"{t}_price_VCI.csv").exists():
            summary_rows.append({"ticker": t, "status": "skipped_no_csv"})
            continue
        ok = ensure_pipeline(t, start, end)
        if not ok:
            summary_rows.append({"ticker": t, "status": "pipeline_failed"})
            continue
        s = summarize_snapshot(t)
        (out_dir / f"{t}.json").write_text(json.dumps(s, ensure_ascii=False, indent=2))
        summary_rows.append({**s, "status": "ok"})

    # Print compact table
    print(f"\n[technical_runner] {len(tickers)} tickers processed → {out_dir}\n")
    print(f"  {'TICKER':8s} {'STATE':30s} {'CONF':5s} {'CORE':6s} {'SWING':6s} {'T+':6s} RS")
    for r in summary_rows:
        if r.get("status") != "ok":
            print(f"  {r['ticker']:8s} -- {r.get('status')}")
            continue
        mp = r.get("mode_pass", {})
        c = "✓" if mp.get("core", {}).get("pass") else "-"
        sw = "✓" if mp.get("swing", {}).get("pass") else "-"
        tp = "✓" if mp.get("t_plus", {}).get("pass") else "-"
        print(f"  {r['ticker']:8s} {str(r.get('technical_state'))[:30]:30s} "
              f"{r.get('confidence_score') or '-':>3}   {c:5s} {sw:5s}  {tp:5s} {r.get('rs_label') or '-'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
