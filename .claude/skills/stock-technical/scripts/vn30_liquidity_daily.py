"""VN30 daily liquidity (Σ GTGD).

Compute daily Σ(close × volume) across VN30. Maintain accumulator
data/vn30_liquidity_history.csv. Output:
  data/vn30_liquidity_{DATE}.json with:
    - latest_day_b_vnd
    - ma20_b_vnd
    - ma120_b_vnd
    - ratio_20d_vs_6m
    - label (rising / flat / falling)

Used by L2 Market Regime pillar 4 (`liquidity`).

VN30 constituents fetched via vnstock listing API.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
HIST = DATA / "vn30_liquidity_history.csv"

sys.path.insert(0, str(ROOT / "scripts"))
from market_context import _fetch_index  # noqa: E402


def _vn30_constituents() -> list[str]:
    try:
        from vnstock import Vnstock
        v = Vnstock().stock(symbol="ACB", source="VCI")
        return list(v.listing.symbols_by_group("VN30"))
    except Exception as e:
        print(f"[vn30_liquidity] listing fail: {e}", file=sys.stderr)
        return []


def _fetch_ticker_volume_value(symbol: str, start: str, end: str) -> pd.DataFrame | None:
    try:
        from vnstock.api.quote import Quote
        q = Quote(symbol=symbol, source="VCI")
        df = q.history(start=start, end=end, interval="1D")
    except Exception:
        return None
    if df is None or df.empty:
        return None
    df = df.copy()
    df.columns = [c.lower() for c in df.columns]
    if "time" in df.columns:
        df["time"] = pd.to_datetime(df["time"])
    elif "date" in df.columns:
        df["time"] = pd.to_datetime(df["date"])
    if "close" not in df.columns or "volume" not in df.columns:
        return None
    df["value"] = df["close"] * df["volume"]
    return df[["time", "value"]].sort_values("time")


def compute(start: str, end: str) -> dict:
    constituents = _vn30_constituents()
    if not constituents:
        return {"as_of": date.today().isoformat(), "error": "vn30_listing_unavailable"}

    daily_sum: dict[pd.Timestamp, float] = {}
    n_tickers_used = 0
    errors: list[str] = []
    for sym in constituents:
        df = _fetch_ticker_volume_value(sym, start, end)
        if df is None or df.empty:
            errors.append(sym)
            continue
        n_tickers_used += 1
        for _, row in df.iterrows():
            daily_sum[row["time"]] = daily_sum.get(row["time"], 0) + row["value"]

    if not daily_sum:
        return {"as_of": date.today().isoformat(), "error": "no_data"}

    series = pd.Series(daily_sum).sort_index()
    # Convert VCI value (thousand VND per share × shares) → billion VND
    # VCI price is in thousand VND. So value = close (k VND) × volume (shares) = k VND.
    # Convert to billion VND: divide by 1_000_000.
    series_b = series / 1_000_000.0

    latest_b = float(series_b.iloc[-1])
    ma20 = float(series_b.tail(20).mean()) if len(series_b) >= 20 else None
    ma120 = float(series_b.tail(120).mean()) if len(series_b) >= 120 else None
    ratio = ma20 / ma120 if ma20 and ma120 else None
    if ratio is None:
        label = "missing"
    elif ratio >= 1.1:
        label = "rising"
    elif ratio <= 0.9:
        label = "falling"
    else:
        label = "flat"

    return {
        "as_of": date.today().isoformat(),
        "latest_day": str(series_b.index[-1].date()),
        "latest_day_b_vnd": round(latest_b, 2),
        "ma20_b_vnd": round(ma20, 2) if ma20 else None,
        "ma120_b_vnd": round(ma120, 2) if ma120 else None,
        "ratio_20d_vs_6m": round(ratio, 4) if ratio else None,
        "label": label,
        "n_constituents_used": n_tickers_used,
        "n_constituents_total": len(constituents),
        "errors_sample": errors[:5],
    }


def _append_history(snapshot: dict):
    if "error" in snapshot or snapshot.get("latest_day") is None:
        return
    row = {
        "date": snapshot["latest_day"],
        "vn30_sum_b_vnd": snapshot["latest_day_b_vnd"],
        "ma20_b_vnd": snapshot.get("ma20_b_vnd"),
        "ma120_b_vnd": snapshot.get("ma120_b_vnd"),
        "ratio_20d_vs_6m": snapshot.get("ratio_20d_vs_6m"),
        "label": snapshot.get("label"),
    }
    if HIST.exists():
        df = pd.read_csv(HIST)
        if not (df["date"] == row["date"]).any():
            df = pd.concat([df, pd.DataFrame([row])], ignore_index=True)
            df.to_csv(HIST, index=False)
    else:
        pd.DataFrame([row]).to_csv(HIST, index=False)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start")
    ap.add_argument("--end")
    args = ap.parse_args()
    end = args.end or date.today().isoformat()
    start = args.start or (date.today() - timedelta(days=300)).isoformat()
    print(f"[vn30_liquidity] start={start} end={end}")
    snap = compute(start, end)
    out_path = DATA / f"vn30_liquidity_{date.today().isoformat()}.json"
    out_path.write_text(json.dumps(snap, ensure_ascii=False, indent=2))
    _append_history(snap)
    print(json.dumps({k: v for k, v in snap.items() if k != "errors_sample"},
                     ensure_ascii=False, indent=2))
    print(f"\n[vn30_liquidity] → {out_path}, history → {HIST}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
