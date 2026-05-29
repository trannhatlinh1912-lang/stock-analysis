"""Daily news cache batch — Company.news() per watchlist ticker.

Cached at data/news_cache/{TICKER}.json:
  {
    fetched_at: ISO,
    n_items: int,
    items: [{title, public_date, source}, ...]
  }

Used by L7 lái_detector for symptoms 1 (vol spike + no news) and 6 (pump
pattern + low news). Stale > 1 day → refetch.

Throttle: 0.3s between fetches to avoid rate limit.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
CONFIGS = ROOT / "configs"
CACHE_DIR = DATA / "news_cache"


def _fetch_news(symbol: str) -> dict | None:
    try:
        from vnstock.api.company import Company
        c = Company(symbol=symbol, source="VCI")
        df = c.news()
    except Exception as e:
        return {"error": str(e)[:200]}
    if df is None or len(df) == 0:
        return {"items": [], "n_items": 0}
    items = []
    for _, row in df.iterrows():
        items.append({
            "title": row.get("news_title"),
            "public_date": str(row.get("public_date")),
            "source": row.get("news_source"),
            "source_link": row.get("news_source_link"),
        })
    return {"items": items, "n_items": len(items)}


def is_fresh(path: Path, max_age_hours: int = 24) -> bool:
    if not path.exists():
        return False
    age_h = (datetime.now() - datetime.fromtimestamp(path.stat().st_mtime)).total_seconds() / 3600
    return age_h <= max_age_hours


def refresh_ticker(symbol: str, force: bool = False, throttle_s: float = 0.3) -> dict:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    p = CACHE_DIR / f"{symbol}.json"
    if not force and is_fresh(p):
        try:
            data = json.loads(p.read_text())
            return {"ticker": symbol, "status": "fresh", "n_items": data.get("n_items", 0)}
        except Exception:
            pass
    result = _fetch_news(symbol)
    if result is None or "error" in result:
        return {"ticker": symbol, "status": "fetch_error",
                "error": (result or {}).get("error", "no_response")}
    payload = {
        "symbol": symbol,
        "fetched_at": datetime.now().isoformat(timespec="seconds"),
        "n_items": result["n_items"],
        "items": result["items"],
    }
    p.write_text(json.dumps(payload, ensure_ascii=False, indent=2))
    time.sleep(throttle_s)
    return {"ticker": symbol, "status": "saved", "n_items": result["n_items"]}


def count_substantive(symbol: str, days_back: int,
                      non_substantive_keywords: list[str] | None = None) -> int | None:
    """Count substantive news in last `days_back` days. Reads cache.

    Returns None if cache missing or unreadable.
    """
    p = CACHE_DIR / f"{symbol}.json"
    if not p.exists():
        return None
    try:
        d = json.loads(p.read_text())
    except Exception:
        return None
    non_sub = [k.lower() for k in (non_substantive_keywords or [
        "thông báo định kỳ",
        "cập nhật giao dịch",
        "thay đổi nhỏ",
        "công bố thông tin",
    ])]
    cutoff = date.today() - timedelta(days=days_back)
    count = 0
    for item in d.get("items", []):
        pd_str = item.get("public_date") or ""
        try:
            pdt = datetime.fromisoformat(pd_str.replace("Z", "+00:00")).date()
        except (ValueError, TypeError):
            continue
        if pdt < cutoff:
            continue
        title = (item.get("title") or "").lower()
        if any(k in title for k in non_sub):
            continue
        count += 1
    return count


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tickers", nargs="+")
    ap.add_argument("--force", action="store_true", help="Ignore cache freshness.")
    args = ap.parse_args()

    wl = yaml.safe_load((CONFIGS / "watchlist.yaml").read_text())
    tickers = args.tickers or wl.get("all_fetched", [])

    n_saved = 0
    n_fresh = 0
    n_error = 0
    for t in tickers:
        r = refresh_ticker(t, force=args.force)
        if r["status"] == "saved":
            n_saved += 1
        elif r["status"] == "fresh":
            n_fresh += 1
        else:
            n_error += 1
        marker = {"saved": "+", "fresh": "=", "fetch_error": "x"}[r["status"]]
        print(f"  {marker} {t}: {r['status']} n={r.get('n_items', '-')}"
              + (f" err={r.get('error')[:50]}" if r.get("error") else ""))
    print(f"\n[news_cache] saved={n_saved} fresh={n_fresh} error={n_error}")
    return 0 if n_error < len(tickers) / 2 else 1


if __name__ == "__main__":
    sys.exit(main())
