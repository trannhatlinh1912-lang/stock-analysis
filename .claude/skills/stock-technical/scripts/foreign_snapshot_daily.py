"""Daily foreign flow accumulator.

For each watchlist ticker, fetch latest KBS price_board foreign buy/sell
volume, append to data/foreign_history.csv. Used by:
  - Layer 2A `foreign_cum_20d` pillar
  - Layer 7 symptom 4 (foreign-retail divergence)
  - Layer 3 sector flow dimension

Append-only. Idempotent per (date, ticker) pair.

Schema:
  date, ticker, buy_volume, sell_volume, net_volume, close_vnd, net_vnd

CSV must accumulate ≥20 trading days before L2 + L7 symptom 4 can fire
(symptom uses 5-day window; pillar 20-day).
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path
from typing import Any

import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
CONFIGS = ROOT / "configs"
HIST_PATH = DATA / "foreign_history.csv"

sys.path.insert(0, str(ROOT / "scripts"))
from external_overlay import fetch_foreign_snapshot  # noqa: E402


def _latest_close(symbol: str) -> float | None:
    p = DATA / f"{symbol}_price_VCI.csv"
    if not p.exists():
        return None
    df = pd.read_csv(p)
    if df.empty or "close" not in df.columns:
        return None
    return float(df["close"].iloc[-1])


def _load_history() -> pd.DataFrame:
    if not HIST_PATH.exists():
        return pd.DataFrame(columns=["date", "ticker", "buy_volume", "sell_volume",
                                      "net_volume", "close_vnd", "net_vnd"])
    df = pd.read_csv(HIST_PATH)
    df["date"] = pd.to_datetime(df["date"]).dt.date.astype(str)
    return df


def append_snapshots(tickers: list[str]) -> dict[str, Any]:
    hist = _load_history()
    today = date.today().isoformat()
    existing = set(zip(hist["date"], hist["ticker"]))
    new_rows = []
    errors: list[str] = []
    skipped = 0
    for sym in tickers:
        key = (today, sym)
        if key in existing:
            skipped += 1
            continue
        snap = fetch_foreign_snapshot(sym)
        if not snap or "error" in snap:
            errors.append(f"{sym}: {snap.get('error') if snap else 'no_snap'}")
            continue
        buy_v = snap.get("foreign_buy_volume")
        sell_v = snap.get("foreign_sell_volume")
        net_v = snap.get("net_foreign_volume")
        close = _latest_close(sym)
        net_vnd = float(net_v) * float(close) if net_v is not None and close else None
        new_rows.append({
            "date": today,
            "ticker": sym,
            "buy_volume": buy_v,
            "sell_volume": sell_v,
            "net_volume": net_v,
            "close_vnd": close,
            "net_vnd": net_vnd,
        })

    if new_rows:
        out = pd.concat([hist, pd.DataFrame(new_rows)], ignore_index=True)
        out.to_csv(HIST_PATH, index=False)

    return {
        "as_of": today,
        "tickers_requested": len(tickers),
        "new_appended": len(new_rows),
        "skipped_existing": skipped,
        "errors_count": len(errors),
        "errors_sample": errors[:5],
        "history_path": str(HIST_PATH),
        "history_n_rows_total": int(len(hist) + len(new_rows)),
    }


def main() -> int:
    p = argparse.ArgumentParser(description="Daily foreign flow snapshot accumulator.")
    p.add_argument("--tickers", nargs="+")
    args = p.parse_args()

    wl = yaml.safe_load((CONFIGS / "watchlist.yaml").read_text())
    tickers = args.tickers or wl.get("all_fetched", [])
    summary = append_snapshots(tickers)
    print(json.dumps(summary, ensure_ascii=False, indent=2))

    # Persist daily summary too
    (DATA / f"foreign_snapshot_run_{date.today().isoformat()}.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2)
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
