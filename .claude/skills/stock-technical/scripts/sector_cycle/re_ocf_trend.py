"""Real Estate OCF trend (4Q rolling).

Compare sum(OCF, last 4 quarters) vs sum(OCF, prior 4 quarters).
improving: latest > prior + 10%, stable ±10%, declining < -10%.

OCF item_id = cfa18 (Lưu chuyển tiền tệ ròng từ các hoạt động sản xuất kinh doanh).
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


OCF_ID = "cfa18"


def compute_for_ticker(symbol: str) -> dict:
    cf = fetch_quarterly(symbol, "cash_flow")
    if cf is None:
        return {"ticker": symbol, "error": "fetch_fail"}
    ocf_row = item_row(cf, OCF_ID)
    if not ocf_row:
        return {"ticker": symbol, "error": "ocf_item_missing"}
    cols = list(ocf_row.keys())
    if len(cols) < 8:
        return {"ticker": symbol, "error": "insufficient_quarters", "n": len(cols)}
    vals = [ocf_row[c] for c in cols if ocf_row[c] is not None]
    if len(vals) < 8:
        return {"ticker": symbol, "error": "insufficient_values", "n": len(vals)}

    latest_4 = sum(vals[:4])
    prior_4 = sum(vals[4:8])
    if prior_4 == 0:
        return {"ticker": symbol, "error": "prior_4q_zero"}
    pct_change = (latest_4 - prior_4) / abs(prior_4) * 100
    if pct_change > 10:
        trend = "improving"
    elif pct_change < -10:
        trend = "declining"
    else:
        trend = "stable"
    return {
        "ticker": symbol,
        "quarters_used": cols[:8],
        "ocf_latest_4q_sum": latest_4,
        "ocf_prior_4q_sum": prior_4,
        "ocf_yoy_change_pct": round(pct_change, 2),
        "trend": trend,
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
        "mean_yoy_change_pct": round(sum(p["ocf_yoy_change_pct"] for p in valid) / len(valid), 2),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tickers", nargs="+")
    args = ap.parse_args()
    basket = args.tickers or load_basket("real_estate")
    print(f"[re_ocf] basket={basket}")
    per_ticker = []
    for s in basket:
        r = compute_for_ticker(s)
        per_ticker.append(r)
        if "error" in r:
            print(f"  {s}: ERROR {r.get('error')}")
        else:
            print(f"  {s}: 4Q-YoY {r.get('ocf_yoy_change_pct')}% trend={r.get('trend')}")
    agg = aggregate(per_ticker)
    out = {
        "sector": "real_estate",
        "as_of": date.today().isoformat(),
        "metric": "OCF_4Q_rolling_YoY_pct",
        "per_ticker": per_ticker,
        "aggregate": agg,
    }
    p = write_output("real_estate", out)
    print(f"\n[re_ocf] → {p}")
    print(f"  sector_trend={agg.get('sector_trend')}  mean_YoY={agg.get('mean_yoy_change_pct')}%")
    return 0


if __name__ == "__main__":
    sys.exit(main())
