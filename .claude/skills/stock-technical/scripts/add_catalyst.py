"""Helper to add catalyst entries to configs/catalyst_manual.yaml.

Use weekly to maintain L5 catalyst data freshness (stale > 14d → tier downgrade).

Usage:
  # Interactive
  python3 scripts/add_catalyst.py --ticker VCB

  # Flag-based (no prompts)
  python3 scripts/add_catalyst.py --ticker VCB \\
      --id rate_cut_q3_2026 \\
      --category 5.1_policy \\
      --tier hard \\
      --direction bullish \\
      --description "SBV signal rate cut Q3 2026" \\
      --source "https://sbv.gov.vn/..." \\
      --source "VCBS Banking Outlook 2026 p23" \\
      --expected-play-date 2026-08-15 \\
      --expiration-date 2026-12-31

  # List existing
  python3 scripts/add_catalyst.py --ticker VCB --list

  # Remove
  python3 scripts/add_catalyst.py --ticker VCB --remove rate_cut_q3_2026

  # Touch last_updated (useful after manual edits)
  python3 scripts/add_catalyst.py --touch

Validation:
  - tier ∈ {hard, medium, soft, speculative}
  - direction ∈ {bullish, bearish}
  - category ∈ {5.1_policy, 5.2_earnings, 5.3_cycle, 5.4_commodity,
                5.5_corp_action, 5.6_upgrade, 5.7_flow,
                5.8_management}
  - At least 1 source required for hard/medium tier
  - expiration_date > today
"""
from __future__ import annotations

import argparse
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
CONFIGS = ROOT / "configs"
CATALYST_YAML = CONFIGS / "catalyst_manual.yaml"

VALID_TIERS = {"hard", "medium", "soft", "speculative"}
VALID_DIRECTIONS = {"bullish", "bearish"}
VALID_CATEGORIES = {
    "5.1_policy", "5.2_earnings", "5.3_cycle", "5.4_commodity",
    "5.5_corp_action", "5.6_upgrade", "5.7_flow", "5.8_management",
}


def _read() -> dict:
    if not CATALYST_YAML.exists():
        return {"last_updated": date.today().isoformat(), "catalysts_by_ticker": {}}
    return yaml.safe_load(CATALYST_YAML.read_text()) or {}


def _write(data: dict):
    data["last_updated"] = date.today().isoformat()
    with CATALYST_YAML.open("w", encoding="utf-8") as f:
        yaml.safe_dump(data, f, allow_unicode=True, sort_keys=False, width=120)


def _validate(entry: dict) -> list[str]:
    errors = []
    if entry.get("tier") not in VALID_TIERS:
        errors.append(f"tier must be one of {VALID_TIERS}")
    if entry.get("direction") not in VALID_DIRECTIONS:
        errors.append(f"direction must be one of {VALID_DIRECTIONS}")
    if entry.get("category") not in VALID_CATEGORIES:
        errors.append(f"category must be one of {VALID_CATEGORIES}")
    if entry.get("tier") in ("hard", "medium") and not entry.get("sources"):
        errors.append("hard/medium tier requires ≥1 source")
    exp = entry.get("expiration_date")
    if exp:
        try:
            exp_d = datetime.strptime(str(exp), "%Y-%m-%d").date()
            if exp_d <= date.today():
                errors.append(f"expiration_date {exp} must be in the future")
        except ValueError:
            errors.append(f"expiration_date {exp} not YYYY-MM-DD")
    return errors


def _prompt(label: str, default: str | None = None, required: bool = True) -> str:
    suffix = f" [{default}]" if default else ""
    while True:
        v = input(f"{label}{suffix}: ").strip()
        if not v and default:
            return default
        if v:
            return v
        if not required:
            return ""
        print("  (required)")


def interactive_entry(ticker: str) -> dict:
    print(f"\nInteractive catalyst entry for {ticker}")
    print(f"Categories: {sorted(VALID_CATEGORIES)}")
    print(f"Tiers: {sorted(VALID_TIERS)}")
    print(f"Directions: {sorted(VALID_DIRECTIONS)}\n")
    entry = {
        "id": _prompt("id (short slug)"),
        "category": _prompt("category"),
        "tier": _prompt("tier"),
        "direction": _prompt("direction", default="bullish"),
        "description": _prompt("description"),
        "sources": [],
        "expected_play_date": _prompt("expected_play_date YYYY-MM-DD", required=False),
        "expiration_date": _prompt("expiration_date YYYY-MM-DD"),
        "extension_allowed": True,
        "detected_at": date.today().isoformat(),
    }
    while True:
        src = _prompt("source (url or report citation, blank to finish)", required=False)
        if not src:
            break
        entry["sources"].append(src)
    return entry


def add(ticker: str, entry: dict) -> int:
    errors = _validate(entry)
    if errors:
        for e in errors:
            print(f"  validation error: {e}", file=sys.stderr)
        return 2
    data = _read()
    by_ticker = data.setdefault("catalysts_by_ticker", {})
    if by_ticker is None:
        data["catalysts_by_ticker"] = {}
        by_ticker = data["catalysts_by_ticker"]
    existing = by_ticker.setdefault(ticker, []) or []
    # Replace if id already exists
    existing = [e for e in existing if e.get("id") != entry["id"]]
    existing.append(entry)
    by_ticker[ticker] = existing
    _write(data)
    print(f"[add_catalyst] {ticker} ← {entry['id']} ({entry['tier']}/{entry['direction']}) saved")
    return 0


def remove(ticker: str, cat_id: str) -> int:
    data = _read()
    by_ticker = data.get("catalysts_by_ticker", {}) or {}
    items = by_ticker.get(ticker, []) or []
    before = len(items)
    items = [e for e in items if e.get("id") != cat_id]
    if len(items) == before:
        print(f"[add_catalyst] no catalyst id={cat_id} for {ticker}", file=sys.stderr)
        return 1
    by_ticker[ticker] = items
    _write(data)
    print(f"[add_catalyst] {ticker} ← removed {cat_id}")
    return 0


def list_for(ticker: str) -> int:
    data = _read()
    items = (data.get("catalysts_by_ticker") or {}).get(ticker, []) or []
    if not items:
        print(f"(no catalysts for {ticker})")
        return 0
    print(f"\n{ticker}: {len(items)} catalyst(s)")
    for e in items:
        exp = e.get("expiration_date") or "no_expiry"
        sources = " / ".join(e.get("sources", []) or [])[:80]
        print(f"  - {e['id']:30s} {e['tier']:5s}/{e['direction']:8s} exp={exp}")
        print(f"      {e.get('description', '')[:100]}")
        if sources:
            print(f"      sources: {sources}")
    return 0


def touch() -> int:
    data = _read()
    _write(data)
    print(f"[add_catalyst] last_updated → {date.today().isoformat()}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Catalyst manual yaml helper.")
    ap.add_argument("--ticker")
    ap.add_argument("--id")
    ap.add_argument("--category", help=f"One of {sorted(VALID_CATEGORIES)}")
    ap.add_argument("--tier", help=f"One of {sorted(VALID_TIERS)}")
    ap.add_argument("--direction", help=f"One of {sorted(VALID_DIRECTIONS)}")
    ap.add_argument("--description")
    ap.add_argument("--source", action="append", default=[])
    ap.add_argument("--expected-play-date")
    ap.add_argument("--expiration-date")
    ap.add_argument("--extension-allowed", action="store_true", default=True)
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--remove", metavar="ID")
    ap.add_argument("--touch", action="store_true",
                    help="Just bump last_updated (after manual yaml edits)")
    args = ap.parse_args()

    if args.touch:
        return touch()
    if not args.ticker:
        print("--ticker required (or use --touch)", file=sys.stderr)
        return 2
    if args.list:
        return list_for(args.ticker)
    if args.remove:
        return remove(args.ticker, args.remove)

    # Build entry from flags or prompt
    if args.id and args.category and args.tier:
        entry = {
            "id": args.id,
            "category": args.category,
            "tier": args.tier,
            "direction": args.direction or "bullish",
            "description": args.description or "",
            "sources": args.source,
            "expected_play_date": args.expected_play_date,
            "expiration_date": args.expiration_date,
            "extension_allowed": args.extension_allowed,
            "detected_at": date.today().isoformat(),
        }
    else:
        entry = interactive_entry(args.ticker)

    return add(args.ticker, entry)


if __name__ == "__main__":
    sys.exit(main())
