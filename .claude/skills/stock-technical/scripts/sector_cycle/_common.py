"""Shared helpers for sector cycle proxy scripts.

Each proxy script fetches quarterly statements per basket member,
computes a sector-specific metric, and writes
data/sector_cycle/{sector}_{DATE}.json with per-ticker + sector aggregate.

Quarter labels in vnstock: "2026-Q1", "2025-Q4", ... sorted desc in columns.
"""
from __future__ import annotations

import json
import re
import sys
from datetime import date
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data"
CONFIGS = ROOT / "configs"
OUT_DIR = DATA / "sector_cycle"


def fetch_quarterly(symbol: str, statement: str) -> pd.DataFrame | None:
    """Fetch quarterly statement. statement ∈ {income, balance, cash_flow}."""
    try:
        from vnstock.api.financial import Finance
        f = Finance(symbol=symbol, source="VCI")
        if statement == "income":
            return f.income_statement(period="quarter")
        if statement == "balance":
            return f.balance_sheet(period="quarter")
        if statement == "cash_flow":
            return f.cash_flow(period="quarter")
    except Exception as e:
        print(f"  [{symbol}] quarterly {statement} fail: {str(e)[:80]}", file=sys.stderr)
        return None
    return None


def quarter_cols(df: pd.DataFrame) -> list[str]:
    """Return columns matching YYYY-QX, sorted descending (newest first)."""
    pat = re.compile(r"^\d{4}-Q[1-4]$")
    cols = [c for c in df.columns if pat.match(str(c))]
    return sorted(cols, key=lambda x: (-int(x[:4]), -int(x[-1])))


def item_row(df: pd.DataFrame, item_id: str) -> dict | None:
    """Return latest quarters {col: value} for given item_id."""
    if df is None or df.empty:
        return None
    m = df[df["item_id"] == item_id]
    if m.empty:
        return None
    row = m.iloc[0]
    cols = quarter_cols(df)
    return {c: float(row[c]) if pd.notna(row[c]) else None for c in cols}


def slope_trend(series: list[float], pp_threshold: float = 0.10) -> str:
    """Compare latest vs mean of prior 3 quarters. pp_threshold in percentage points."""
    if len(series) < 4:
        return "insufficient_data"
    latest = series[0]
    prior_mean = sum(series[1:4]) / 3
    delta = latest - prior_mean
    if delta > pp_threshold:
        return "expanding" if pp_threshold < 1 else "improving"
    if delta < -pp_threshold:
        return "compressing" if pp_threshold < 1 else "declining"
    return "stable"


def yoy_change(series: list[float], current_idx: int = 0) -> float | None:
    """Return YoY pct change between series[current_idx] and series[current_idx+4]."""
    if len(series) < current_idx + 5:
        return None
    curr = series[current_idx]
    yoy = series[current_idx + 4]
    if yoy is None or yoy == 0:
        return None
    return (curr / yoy - 1) * 100


def write_output(sector: str, payload: dict) -> Path:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    p = OUT_DIR / f"{sector}_{date.today().isoformat()}.json"
    p.write_text(json.dumps(payload, ensure_ascii=False, indent=2))
    return p


def load_basket(sector: str) -> list[str]:
    import yaml
    wl = yaml.safe_load((CONFIGS / "watchlist.yaml").read_text())
    return wl["sector_baskets"].get(sector, [])
