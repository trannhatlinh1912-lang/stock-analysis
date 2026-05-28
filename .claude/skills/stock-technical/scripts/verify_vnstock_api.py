#!/usr/bin/env python3
"""Verify vnstock APIs for Layer 1 Quality Gate requirements.

Tests each API call on a single ticker, reports:
  - Available / Missing / Error per endpoint
  - Sample data shape (columns, rows)
  - First + last date if time series
  - Min / max / NaN count for numeric fields

NO data fabrication. Reports raw API output only.

Usage:
    python scripts/verify_vnstock_api.py --symbol VCB
"""
from __future__ import annotations

import argparse
import json
import sys
import warnings
from datetime import datetime
from pathlib import Path

import pandas as pd

warnings.filterwarnings("ignore")

REPO_ROOT = Path(__file__).resolve().parent.parent
REPORTS_DIR = REPO_ROOT / "reports"
REPORTS_DIR.mkdir(exist_ok=True)


def _safe_repr_df(df) -> dict:
    """Summarize a DataFrame without dumping rows. Returns dict."""
    if df is None:
        return {"type": "None"}
    if isinstance(df, (int, float, str)):
        return {"type": type(df).__name__, "value": str(df)[:200]}
    if isinstance(df, list):
        return {"type": "list", "len": len(df), "sample": str(df[:3])[:200]}
    if isinstance(df, dict):
        return {"type": "dict", "keys": list(df.keys())[:20]}
    if not hasattr(df, "columns"):
        return {"type": type(df).__name__, "repr": str(df)[:200]}
    cols = list(df.columns)
    info = {
        "type": "DataFrame",
        "rows": len(df),
        "columns": cols[:40],
        "n_columns": len(cols),
    }
    # Time series detection
    for tcol in ("time", "date", "period", "yearReport", "quarterReport"):
        if tcol in df.columns and len(df) > 0:
            try:
                series = pd.to_datetime(df[tcol], errors="coerce")
                non_null = series.dropna()
                if len(non_null) > 0:
                    info["time_first"] = str(non_null.min())
                    info["time_last"] = str(non_null.max())
                break
            except Exception:
                pass
    # Numeric column stats — top 10
    num_cols = df.select_dtypes(include=["number"]).columns.tolist()[:10]
    if num_cols:
        stats = {}
        for c in num_cols:
            s = df[c].dropna()
            if len(s) == 0:
                stats[c] = {"all_nan": True}
                continue
            stats[c] = {
                "count": int(len(s)),
                "min": round(float(s.min()), 4),
                "max": round(float(s.max()), 4),
                "mean": round(float(s.mean()), 4),
                "nan_count": int(df[c].isna().sum()),
            }
        info["numeric_stats"] = stats
    return info


def _try_call(name: str, fn, *args, **kwargs) -> dict:
    """Run a callable, capture success/error/result."""
    try:
        result = fn(*args, **kwargs)
        return {"endpoint": name, "status": "ok", "result": _safe_repr_df(result)}
    except Exception as e:
        return {"endpoint": name, "status": "error", "error": str(e)[:300]}


def verify_for(symbol: str) -> dict:
    """Test every vnstock API needed for Layer 1 Quality Gate on this symbol."""
    out = {
        "symbol": symbol,
        "tested_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "results": [],
    }

    # 1. Finance.ratio() — P/E, P/B, ROE, ROA, EPS, NIM (bank specific)
    try:
        from vnstock.api.financial import Finance
        fin_vci = Finance(symbol=symbol, source="VCI")
        out["results"].append(_try_call("Finance(VCI).ratio(period=year)", fin_vci.ratio, period="year"))
        out["results"].append(_try_call("Finance(VCI).ratio(period=quarter)", fin_vci.ratio, period="quarter"))
    except Exception as e:
        out["results"].append({"endpoint": "Finance(VCI) import", "status": "error", "error": str(e)[:200]})

    try:
        from vnstock.api.financial import Finance
        fin_tcbs = Finance(symbol=symbol, source="TCBS")
        out["results"].append(_try_call("Finance(TCBS).ratio(period=year)", fin_tcbs.ratio, period="year"))
    except Exception as e:
        out["results"].append({"endpoint": "Finance(TCBS) import", "status": "error", "error": str(e)[:200]})

    # 2. Finance income_statement / balance_sheet / cash_flow
    try:
        from vnstock.api.financial import Finance
        f = Finance(symbol=symbol, source="VCI")
        out["results"].append(_try_call("Finance(VCI).income_statement(period=year)",
                                          f.income_statement, period="year"))
        out["results"].append(_try_call("Finance(VCI).balance_sheet(period=year)",
                                          f.balance_sheet, period="year"))
        out["results"].append(_try_call("Finance(VCI).cash_flow(period=year)",
                                          f.cash_flow, period="year"))
    except Exception as e:
        out["results"].append({"endpoint": "Finance statements", "status": "error", "error": str(e)[:200]})

    # 3. Trading: insider_deal, prop_trade, foreign_trade
    try:
        from vnstock.api.trading import Trading
        for src in ("VCI", "KBS"):
            try:
                t = Trading(symbol=symbol, source=src)
                for method in ("insider_deal", "prop_trade", "foreign_trade", "side_stats", "order_stats"):
                    if hasattr(t, method):
                        fn = getattr(t, method)
                        out["results"].append(_try_call(f"Trading({src}).{method}()", fn))
            except Exception as e:
                out["results"].append({"endpoint": f"Trading({src})", "status": "error",
                                         "error": str(e)[:200]})
    except Exception as e:
        out["results"].append({"endpoint": "Trading import", "status": "error", "error": str(e)[:200]})

    # 4. VCI Company explorer: events, profile, shareholders, officers, dividends
    try:
        from vnstock.explorer.vci.company import Company
        c = Company(symbol=symbol)
        for method in ("events", "profile", "shareholders", "officers",
                        "dividends", "news", "reports", "subsidiaries", "affiliates"):
            if hasattr(c, method):
                fn = getattr(c, method)
                out["results"].append(_try_call(f"vci.Company.{method}()", fn))
    except Exception as e:
        out["results"].append({"endpoint": "vci.Company import", "status": "error", "error": str(e)[:200]})

    # 5. Listing — industry classification
    try:
        from vnstock import Vnstock
        v = Vnstock().stock(symbol=symbol, source="VCI")
        out["results"].append(_try_call("listing.industries_icb()", v.listing.industries_icb))
    except Exception as e:
        out["results"].append({"endpoint": "Listing", "status": "error", "error": str(e)[:200]})

    return out


def render_report(out: dict) -> str:
    L = [f"# vnstock API verification — {out['symbol']}", ""]
    L.append(f"- Tested at: `{out['tested_at']}`")
    L.append(f"- vnstock version: see pip show vnstock")
    L.append("")

    ok = [r for r in out["results"] if r.get("status") == "ok"]
    err = [r for r in out["results"] if r.get("status") == "error"]
    L.append(f"## Summary: {len(ok)} ok / {len(err)} error / {len(out['results'])} total")
    L.append("")

    L.append("## Available endpoints")
    L.append("")
    L.append("| Endpoint | Type | Rows | n_cols | Time range | First numeric cols |")
    L.append("|---|---|---|---|---|---|")
    for r in ok:
        info = r.get("result", {})
        t = info.get("type", "—")
        rows = info.get("rows", "—")
        ncol = info.get("n_columns", "—")
        tr = ""
        if info.get("time_first"):
            tr = f"{info['time_first'][:10]} → {info['time_last'][:10]}"
        ncs = ", ".join(list((info.get("numeric_stats") or {}).keys())[:4])
        L.append(f"| `{r['endpoint']}` | {t} | {rows} | {ncol} | {tr} | {ncs} |")
    L.append("")

    L.append("## Failed endpoints")
    L.append("")
    if not err:
        L.append("_None_")
    else:
        L.append("| Endpoint | Error |")
        L.append("|---|---|")
        for r in err:
            L.append(f"| `{r['endpoint']}` | {r.get('error', '')[:200]} |")
    L.append("")

    L.append("## Full numeric column details (top 10 per endpoint)")
    L.append("")
    for r in ok:
        info = r.get("result", {})
        stats = info.get("numeric_stats")
        if not stats:
            continue
        L.append(f"### `{r['endpoint']}`")
        if info.get("columns"):
            L.append(f"- all columns ({info.get('n_columns', len(info['columns']))}): "
                     f"{', '.join(info['columns'])}")
        L.append("")
        L.append("| col | count | min | max | mean | nan |")
        L.append("|---|---|---|---|---|---|")
        for c, s in stats.items():
            if s.get("all_nan"):
                L.append(f"| {c} | _all_nan_ | — | — | — | — |")
                continue
            L.append(f"| {c} | {s['count']} | {s['min']} | {s['max']} | {s['mean']} | {s['nan_count']} |")
        L.append("")

    return "\n".join(L) + "\n"


def main() -> int:
    p = argparse.ArgumentParser(description="Verify vnstock APIs for Layer 1.")
    p.add_argument("--symbol", default="VCB", help="Ticker to verify (default VCB).")
    args = p.parse_args()

    out = verify_for(args.symbol.upper())
    report = render_report(out)
    report_path = REPORTS_DIR / f"vnstock_api_verify_{args.symbol.upper()}.md"
    report_path.write_text(report, encoding="utf-8")

    # Also dump raw
    raw_path = REPORTS_DIR / f"vnstock_api_verify_{args.symbol.upper()}.json"
    raw_path.write_text(json.dumps(out, indent=2, ensure_ascii=False, default=str), encoding="utf-8")

    print(f"[verify] wrote {report_path}")
    print(f"[verify] wrote {raw_path}")
    print(f"[verify] ok={sum(1 for r in out['results'] if r.get('status')=='ok')}, "
          f"err={sum(1 for r in out['results'] if r.get('status')=='error')}, "
          f"total={len(out['results'])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
