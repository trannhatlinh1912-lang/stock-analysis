"""Steel inventory turnover quarterly.

Turnover_q_annualized = revenue_q × 4 / avg(inventory_q, inventory_q-1)

Classification: efficient (>4), stable (2-4), weak (<2).
Trend: compare latest q vs trailing 3-q mean (pp threshold 0.3 turns).
"""
from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
from sector_cycle._common import (  # noqa: E402
    fetch_quarterly, item_row, load_basket, slope_trend, write_output,
)


REVENUE_ID = "isa3"     # Doanh thu thuần
INVENTORY_ID = "bsa15"  # Hàng tồn kho, ròng


def classify_turnover(t: float) -> str:
    if t > 4:
        return "efficient"
    if t >= 2:
        return "stable"
    return "weak"


def compute_for_ticker(symbol: str) -> dict:
    inc = fetch_quarterly(symbol, "income")
    bs = fetch_quarterly(symbol, "balance")
    if inc is None or bs is None:
        return {"ticker": symbol, "error": "fetch_fail"}
    rev_row = item_row(inc, REVENUE_ID)
    inv_row = item_row(bs, INVENTORY_ID)
    if not rev_row or not inv_row:
        return {"ticker": symbol, "error": "item_missing"}
    cols = list(rev_row.keys())
    if len(cols) < 5:
        return {"ticker": symbol, "error": "insufficient_quarters", "n": len(cols)}

    turnovers = []
    for i in range(len(cols) - 1):
        rev = rev_row.get(cols[i])
        inv_curr = inv_row.get(cols[i])
        inv_prev = inv_row.get(cols[i + 1])
        if None in (rev, inv_curr, inv_prev):
            turnovers.append(None)
            continue
        avg_inv = (inv_curr + inv_prev) / 2
        if avg_inv <= 0:
            turnovers.append(None)
            continue
        turnovers.append(rev * 4 / avg_inv)

    clean = [v for v in turnovers if v is not None]
    if len(clean) < 4:
        return {"ticker": symbol, "error": "insufficient_clean", "n": len(clean)}

    trend = slope_trend(clean, pp_threshold=0.3)
    latest = clean[0]
    return {
        "ticker": symbol,
        "quarters_used": cols[: len(turnovers)],
        "turnover_annualized": [round(v, 3) if v is not None else None for v in turnovers],
        "latest_turnover": round(latest, 3),
        "level": classify_turnover(latest),
        "trend": trend,
    }


def aggregate(per_ticker: list[dict]) -> dict:
    valid = [p for p in per_ticker if "error" not in p]
    if not valid:
        return {"sector_trend": "missing", "reason": "no_valid"}
    trends = [p["trend"] for p in valid]
    counts = {t: trends.count(t) for t in set(trends)}
    dominant = max(counts, key=counts.get)
    levels = [p["level"] for p in valid]
    level_counts = {l: levels.count(l) for l in set(levels)}
    return {
        "sector_trend": dominant,
        "trend_distribution": counts,
        "level_distribution": level_counts,
        "n_valid": len(valid),
        "n_total": len(per_ticker),
        "mean_latest_turnover": round(sum(p["latest_turnover"] for p in valid) / len(valid), 3),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tickers", nargs="+")
    args = ap.parse_args()
    basket = args.tickers or load_basket("steel")
    print(f"[steel_inv] basket={basket}")
    per_ticker = []
    for s in basket:
        r = compute_for_ticker(s)
        per_ticker.append(r)
        if "error" in r:
            print(f"  {s}: ERROR {r.get('error')}")
        else:
            print(f"  {s}: turnover={r.get('latest_turnover')} level={r.get('level')} trend={r.get('trend')}")
    agg = aggregate(per_ticker)
    out = {
        "sector": "steel",
        "as_of": date.today().isoformat(),
        "metric": "inventory_turnover_annualized",
        "per_ticker": per_ticker,
        "aggregate": agg,
    }
    p = write_output("steel", out)
    print(f"\n[steel_inv] → {p}")
    print(f"  sector_trend={agg.get('sector_trend')} mean_turnover={agg.get('mean_latest_turnover')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
