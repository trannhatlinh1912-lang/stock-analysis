"""Banking NIM proxy.

NIM_q_annualized = NII_q × 4 / avg(TA_q, TA_q-1)

Trend per basket member: compare latest q vs trailing 3-q mean.
Sector aggregate: mean of per-ticker trend label, majority vote.
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


NII_ID = "isb27"
TA_ID = "bsa53"


def compute_for_ticker(symbol: str) -> dict:
    inc = fetch_quarterly(symbol, "income")
    bs = fetch_quarterly(symbol, "balance")
    if inc is None or bs is None:
        return {"ticker": symbol, "error": "fetch_fail"}

    nii_row = item_row(inc, NII_ID)
    ta_row = item_row(bs, TA_ID)
    if not nii_row or not ta_row:
        return {"ticker": symbol, "error": "item_missing"}

    cols = list(nii_row.keys())
    # Need at least 5 quarters (4 NIM compute + 1 lag TA)
    if len(cols) < 5:
        return {"ticker": symbol, "error": "insufficient_quarters", "n": len(cols)}

    nims = []
    for i in range(len(cols) - 1):
        nii = nii_row.get(cols[i])
        ta_curr = ta_row.get(cols[i])
        ta_prev = ta_row.get(cols[i + 1])
        if None in (nii, ta_curr, ta_prev):
            nims.append(None)
            continue
        avg_ta = (ta_curr + ta_prev) / 2
        if avg_ta <= 0:
            nims.append(None)
            continue
        nims.append(nii * 4 / avg_ta * 100)  # annualized NIM in %

    clean = [v for v in nims if v is not None]
    trend = slope_trend(clean, pp_threshold=0.10) if len(clean) >= 4 else "insufficient_data"

    return {
        "ticker": symbol,
        "quarters_used": cols[: len(nims)],
        "nim_pct_annualized": [round(v, 3) if v is not None else None for v in nims],
        "latest_q": cols[0] if cols else None,
        "latest_nim_pct": round(nims[0], 3) if nims and nims[0] else None,
        "prior_3q_mean_pct": round(sum(clean[1:4]) / 3, 3) if len(clean) >= 4 else None,
        "trend": trend,
    }


def aggregate(per_ticker: list[dict]) -> dict:
    valid = [p for p in per_ticker if "error" not in p]
    if not valid:
        return {"sector_trend": "missing", "reason": "no_valid_tickers"}
    trends = [p["trend"] for p in valid]
    counts = {t: trends.count(t) for t in set(trends)}
    dominant = max(counts, key=counts.get)
    return {
        "sector_trend": dominant,
        "trend_distribution": counts,
        "n_valid": len(valid),
        "n_total": len(per_ticker),
        "mean_latest_nim_pct": round(
            sum(p["latest_nim_pct"] for p in valid if p.get("latest_nim_pct")) /
            max(1, sum(1 for p in valid if p.get("latest_nim_pct"))), 3
        ),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tickers", nargs="+")
    args = ap.parse_args()

    basket = args.tickers or load_basket("banking")
    print(f"[banking_nim] basket={basket}")
    per_ticker = []
    for s in basket:
        r = compute_for_ticker(s)
        per_ticker.append(r)
        if "error" in r:
            print(f"  {s}: ERROR {r.get('error')}")
        else:
            print(f"  {s}: latest_nim={r.get('latest_nim_pct')}% trend={r.get('trend')}")

    agg = aggregate(per_ticker)
    out = {
        "sector": "banking",
        "as_of": date.today().isoformat(),
        "metric": "NIM_proxy_annualized_pct",
        "per_ticker": per_ticker,
        "aggregate": agg,
    }
    p = write_output("banking", out)
    print(f"\n[banking_nim] → {p}")
    print(f"  sector_trend={agg.get('sector_trend')}  mean_NIM={agg.get('mean_latest_nim_pct')}%")
    return 0


if __name__ == "__main__":
    sys.exit(main())
