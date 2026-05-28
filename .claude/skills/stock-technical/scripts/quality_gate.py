"""Layer 1 — Quality Gate runner.

Consumes:
  - data/fundamentals/{TICKER}.json  (cached, produced by fetch_fundamentals.py)
  - data/liquidity/{TICKER}.json     (cached, produced by fetch_liquidity.py)

Per Layer 1 spec (configs/quality_gate_spec.md):
  1A — Hard red flags (already computed by fetch_fundamentals)
  1B — Warning flags  (already computed by fetch_fundamentals)
  1C — Tradable gate  (read from liquidity cache)
  1D — Sector-specific ROE + D/E (already enforced by fetch_fundamentals)

Output schema (returned dict + JSON file):
  {
    ticker, sector, verdict ∈ {PASS, WARNING, HARD_FAIL},
    hard_flags, warning_flags,
    tradable_core, tradable_t_plus,
    data_completeness_pct,
    layer_1_pass: bool   # True if no hard_flags AND core_tradable
  }
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
FUND_DIR = ROOT / "data" / "fundamentals"
LIQ_DIR = ROOT / "data" / "liquidity"
OUT_DIR = ROOT / "data" / "quality_gate"


def _load_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def _verdict(hard_flags: list, warning_flags: list, core_tradable: bool) -> str:
    if hard_flags:
        return "HARD_FAIL"
    if not core_tradable:
        return "HARD_FAIL"  # treat illiquid as auto-skip (killer)
    if warning_flags:
        return "WARNING"
    return "PASS"


def run_quality_gate(ticker: str) -> dict[str, Any]:
    fund = _load_json(FUND_DIR / f"{ticker}.json")
    liq = _load_json(LIQ_DIR / f"{ticker}.json")

    if fund is None:
        return {
            "ticker": ticker,
            "verdict": "DATA_MISSING",
            "error": f"fundamentals/{ticker}.json not found. Run fetch_fundamentals.py.",
            "layer_1_pass": False,
        }
    if liq is None:
        return {
            "ticker": ticker,
            "verdict": "DATA_MISSING",
            "error": f"liquidity/{ticker}.json not found. Run fetch_liquidity.py.",
            "layer_1_pass": False,
        }

    hard_flags = fund.get("hard_flags", [])
    warning_flags = fund.get("warning_flags", [])
    sector = fund.get("sector", "unknown")

    tradable_core = bool(liq.get("core_tradable", False))
    tradable_t_plus = bool(liq.get("t_plus_tradable", False))
    min_years_listed_ok = bool(liq.get("min_years_listed_ok", False))

    # Core tradability requires listing duration
    core_pass = tradable_core and min_years_listed_ok
    t_plus_pass = tradable_t_plus and min_years_listed_ok

    verdict = _verdict(hard_flags, warning_flags, core_pass)

    return {
        "ticker": ticker,
        "as_of": date.today().isoformat(),
        "sector": sector,
        "verdict": verdict,
        "layer_1_pass": verdict in {"PASS", "WARNING"},
        "hard_flags": hard_flags,
        "warning_flags": warning_flags,
        "tradable": {
            "core": core_pass,
            "t_plus": t_plus_pass,
            "min_years_listed_ok": min_years_listed_ok,
            "market_cap_b_vnd": liq.get("market_cap_b_vnd"),
            "adtv_20d_b_vnd": liq.get("adtv_20d_b_vnd"),
        },
        "metrics_summary": {
            "roe_pct_3y_avg": fund.get("metrics", {}).get("roe_pct_3y_avg"),
            "roe_pct_5y_avg": fund.get("metrics", {}).get("roe_pct_5y_avg"),
            "de_3y_avg": fund.get("metrics", {}).get("de_3y_avg"),
            "ocf_positive_last_3y": fund.get("metrics", {}).get("ocf_positive_last_3y"),
        },
        "data_completeness_pct": fund.get("data_completeness", {}).get("pct", 0),
    }


def run_batch(tickers: list[str]) -> dict[str, dict]:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out: dict[str, dict] = {}
    for sym in tickers:
        r = run_quality_gate(sym)
        out[sym] = r
        with (OUT_DIR / f"{sym}.json").open("w", encoding="utf-8") as f:
            json.dump(r, f, ensure_ascii=False, indent=2)
    return out


def summarize(results: dict[str, dict]) -> dict[str, list]:
    buckets: dict[str, list[str]] = {"PASS": [], "WARNING": [], "HARD_FAIL": [], "DATA_MISSING": []}
    for sym, r in results.items():
        buckets.setdefault(r["verdict"], []).append(sym)
    return buckets


def main() -> int:
    p = argparse.ArgumentParser(description="Layer 1 Quality Gate runner.")
    p.add_argument("--tickers", nargs="+", help="Tickers to run. Default: all cached fundamentals.")
    args = p.parse_args()

    if args.tickers:
        tickers = args.tickers
    else:
        tickers = sorted(f.stem for f in FUND_DIR.glob("*.json"))

    print(f"[quality_gate] running {len(tickers)} tickers")
    results = run_batch(tickers)
    buckets = summarize(results)

    print()
    for verdict in ("PASS", "WARNING", "HARD_FAIL", "DATA_MISSING"):
        syms = buckets.get(verdict, [])
        print(f"  {verdict:13s} ({len(syms):2d}): {', '.join(syms) if syms else '-'}")

    # Write summary
    summary_path = ROOT / "reports" / f"quality_gate_summary_{date.today().isoformat()}.md"
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    L = [
        f"# Quality Gate Summary — {date.today().isoformat()}",
        "",
        f"- N tickers: {len(tickers)}",
        f"- PASS: {len(buckets['PASS'])}",
        f"- WARNING: {len(buckets['WARNING'])}",
        f"- HARD_FAIL: {len(buckets['HARD_FAIL'])}",
        f"- DATA_MISSING: {len(buckets['DATA_MISSING'])}",
        "",
        "## Per-bucket detail",
        "",
    ]
    for verdict in ("PASS", "WARNING", "HARD_FAIL", "DATA_MISSING"):
        L.append(f"### {verdict}")
        syms = buckets.get(verdict, [])
        if not syms:
            L.append("- (none)")
        else:
            for s in syms:
                r = results[s]
                hf = ", ".join(f.get("id", "?") if isinstance(f, dict) else str(f) for f in r.get("hard_flags", []))
                wf_count = len(r.get("warning_flags", []))
                L.append(f"- **{s}** ({r.get('sector')}) — hard=[{hf}] warning_n={wf_count}")
        L.append("")
    summary_path.write_text("\n".join(L), encoding="utf-8")
    print(f"\n[quality_gate] summary → {summary_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
