"""Consumer SSSG proxy — revenue YoY quarterly.

sssg_proxy_q = revenue_q / revenue_q-4 - 1

Classification:
  accelerating: ≥ +10% YoY for 2 consecutive quarters
  stable: ±10% YoY
  declining: < -5% YoY
"""
from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
from sector_cycle._common import (  # noqa: E402
    fetch_quarterly, item_row, load_basket, write_output,
)


REVENUE_ID = "isa3"  # Doanh thu thuần


def classify(yoy_latest: float, yoy_prior: float) -> str:
    if yoy_latest >= 10 and yoy_prior >= 10:
        return "accelerating"
    if yoy_latest < -5:
        return "declining"
    return "stable"


def compute_for_ticker(symbol: str) -> dict:
    inc = fetch_quarterly(symbol, "income")
    if inc is None:
        return {"ticker": symbol, "error": "fetch_fail"}
    rev_row = item_row(inc, REVENUE_ID)
    if not rev_row:
        return {"ticker": symbol, "error": "revenue_item_missing"}
    cols = list(rev_row.keys())
    vals = [rev_row[c] for c in cols]
    if len(vals) < 6 or any(v is None for v in vals[:6]):
        return {"ticker": symbol, "error": "insufficient_or_missing_quarters"}

    # YoY: Q_n vs Q_n-4
    yoys = []
    for i in range(len(vals) - 4):
        curr = vals[i]
        yoy = vals[i + 4]
        if curr is None or yoy is None or yoy == 0:
            yoys.append(None)
            continue
        yoys.append((curr / yoy - 1) * 100)
    clean = [v for v in yoys if v is not None]
    if len(clean) < 2:
        return {"ticker": symbol, "error": "insufficient_yoy"}

    label = classify(clean[0], clean[1])
    return {
        "ticker": symbol,
        "quarters_used": cols[: len(yoys) + 4],
        "revenue_yoy_pct": [round(v, 2) if v is not None else None for v in yoys],
        "latest_yoy_pct": round(clean[0], 2),
        "prior_yoy_pct": round(clean[1], 2),
        "trend": label,
    }


def aggregate(per_ticker: list[dict]) -> dict:
    valid = [p for p in per_ticker if "error" not in p]
    if not valid:
        return {"sector_trend": "missing", "reason": "no_valid"}
    trends = [p["trend"] for p in valid]
    counts = {t: trends.count(t) for t in set(trends)}
    dominant = max(counts, key=counts.get)
    return {
        "sector_trend": dominant,
        "trend_distribution": counts,
        "n_valid": len(valid),
        "n_total": len(per_ticker),
        "mean_latest_yoy_pct": round(sum(p["latest_yoy_pct"] for p in valid) / len(valid), 2),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tickers", nargs="+")
    ap.add_argument("--sector", default="consumer", help="Default consumer; can pass tech etc")
    args = ap.parse_args()
    basket = args.tickers or load_basket(args.sector)
    print(f"[sssg] sector={args.sector} basket={basket}")
    per_ticker = []
    for s in basket:
        r = compute_for_ticker(s)
        per_ticker.append(r)
        if "error" in r:
            print(f"  {s}: ERROR {r.get('error')}")
        else:
            print(f"  {s}: YoY {r.get('latest_yoy_pct')}% (prior {r.get('prior_yoy_pct')}%) trend={r.get('trend')}")
    agg = aggregate(per_ticker)
    out = {
        "sector": args.sector,
        "as_of": date.today().isoformat(),
        "metric": "revenue_yoy_pct_quarterly",
        "per_ticker": per_ticker,
        "aggregate": agg,
    }
    p = write_output(args.sector, out)
    print(f"\n[sssg] → {p}")
    print(f"  sector_trend={agg.get('sector_trend')} mean_YoY={agg.get('mean_latest_yoy_pct')}%")
    return 0


if __name__ == "__main__":
    sys.exit(main())
