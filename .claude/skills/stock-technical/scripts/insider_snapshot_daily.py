"""Insider daily snapshot accumulator (L7 symptom 2).

Each day, fetch Company.shareholders + Company.officers for each watchlist
ticker. Persist to data/insider_history/{TICKER}/{DATE}.json. After 90-day
build-up, L7 symptom 2 can compare today vs T-90 to detect heavy insider
selling (>5% holdings reduction cumulative).

Idempotent per (ticker, date).
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
CONFIGS = ROOT / "configs"
INSIDER_DIR = DATA / "insider_history"


def _fetch(symbol: str) -> dict:
    try:
        from vnstock.api.company import Company
        c = Company(symbol=symbol, source="VCI")
    except Exception as e:
        return {"error": f"company_init_fail: {str(e)[:80]}"}

    out: dict = {"symbol": symbol, "as_of": date.today().isoformat()}
    try:
        sh = c.shareholders()
        if sh is not None and len(sh) > 0:
            out["shareholders"] = sh.fillna("").to_dict(orient="records")
        else:
            out["shareholders"] = []
    except Exception as e:
        out["shareholders_error"] = str(e)[:100]
    try:
        offs = c.officers()
        if offs is not None and len(offs) > 0:
            out["officers"] = offs.fillna("").to_dict(orient="records")
        else:
            out["officers"] = []
    except Exception as e:
        out["officers_error"] = str(e)[:100]
    return out


def snapshot_ticker(symbol: str) -> dict:
    snap = _fetch(symbol)
    out_dir = INSIDER_DIR / symbol
    out_dir.mkdir(parents=True, exist_ok=True)
    p = out_dir / f"{date.today().isoformat()}.json"
    if p.exists():
        return {"ticker": symbol, "status": "already_exists", "path": str(p)}
    p.write_text(json.dumps(snap, ensure_ascii=False, indent=2))
    return {
        "ticker": symbol,
        "status": "saved" if "error" not in snap else "save_with_error",
        "n_shareholders": len(snap.get("shareholders", [])),
        "n_officers": len(snap.get("officers", [])),
        "errors": [k for k in snap if k.endswith("_error")],
        "path": str(p),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tickers", nargs="+")
    args = ap.parse_args()
    wl = yaml.safe_load((CONFIGS / "watchlist.yaml").read_text())
    tickers = args.tickers or wl.get("all_fetched", [])
    INSIDER_DIR.mkdir(parents=True, exist_ok=True)
    results = []
    for t in tickers:
        r = snapshot_ticker(t)
        results.append(r)
        print(f"  {t}: {r['status']} (sh={r.get('n_shareholders')}, off={r.get('n_officers')})"
              + (f" errors={r.get('errors')}" if r.get("errors") else ""))
    summary = {
        "as_of": date.today().isoformat(),
        "n_tickers": len(tickers),
        "saved": sum(1 for r in results if r["status"] == "saved"),
        "already_exists": sum(1 for r in results if r["status"] == "already_exists"),
        "errors": sum(1 for r in results if r["status"] == "save_with_error"),
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
