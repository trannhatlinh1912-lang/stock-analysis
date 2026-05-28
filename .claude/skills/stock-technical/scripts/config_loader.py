#!/usr/bin/env python3
"""Config loader: merge default + sector + ticker YAML files.

Resolution order (later overrides earlier via deep merge):
    1. configs/default.yaml
    2. configs/sectors/{sector}.yaml    (if SECTOR_MAP[ticker] exists)
    3. configs/tickers/{TICKER}.yaml    (if file exists)

Macro penalty rules are LIST-CONCAT, not replaced — sector rules ADD to default
rules. Use id-collision: ticker-level rule with same id as sector/default
replaces upstream rule.

Public API:
    load_config(symbol) -> dict
    eval_macro_penalties(rules, ctx) -> (total_delta, notes)
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
CONFIGS_DIR = REPO_ROOT / "configs"

# Sector mapping. Mirrors decision_framework.SECTOR_MAP for backwards-compat.
SECTOR_MAP: dict[str, str] = {
    "BSR": "oil_gas", "GAS": "oil_gas", "PLX": "oil_gas",
    "PVS": "oil_gas", "PVD": "oil_gas", "PVT": "oil_gas", "OIL": "oil_gas",
    "VCB": "banking", "BID": "banking", "CTG": "banking", "MBB": "banking",
    "TCB": "banking", "ACB": "banking", "VPB": "banking", "HDB": "banking",
    "STB": "banking", "TPB": "banking", "VIB": "banking", "LPB": "banking",
    "SHB": "banking", "SSB": "banking",
    "HPG": "steel", "HSG": "steel", "NKG": "steel", "TVN": "steel",
    "VHM": "real_estate", "VIC": "real_estate", "VRE": "real_estate",
    "NVL": "real_estate", "DXG": "real_estate", "KDH": "real_estate",
    "PDR": "real_estate", "DIG": "real_estate", "NLG": "real_estate",
    "POW": "utilities", "REE": "utilities", "GEX": "utilities",
    "PC1": "utilities", "NT2": "utilities",
    "MWG": "retail", "PNJ": "retail", "DGW": "retail", "FRT": "retail",
    "MSN": "consumer", "VNM": "consumer", "SAB": "consumer",
    "DCM": "fertilizer", "DPM": "fertilizer", "BMP": "materials",
    "FPT": "tech", "CMG": "tech", "ELC": "tech",
}


def _deep_merge(base: dict, override: dict) -> dict:
    """Deep merge override into base. Lists handled per-key below."""
    out = dict(base)
    for k, v in override.items():
        if k == "macro_penalties" and isinstance(v, list) and isinstance(out.get(k), list):
            # Concat with id-collision replace.
            existing = {r.get("id"): r for r in out[k] if isinstance(r, dict)}
            for new_rule in v:
                if isinstance(new_rule, dict) and new_rule.get("id"):
                    existing[new_rule["id"]] = new_rule
                else:
                    existing[f"_anon_{len(existing)}"] = new_rule
            out[k] = list(existing.values())
        elif k == "custom_risks" and isinstance(v, list) and isinstance(out.get(k), list):
            existing = {r.get("id"): r for r in out[k] if isinstance(r, dict)}
            for new_rule in v:
                if isinstance(new_rule, dict) and new_rule.get("id"):
                    existing[new_rule["id"]] = new_rule
                else:
                    existing[f"_anon_{len(existing)}"] = new_rule
            out[k] = list(existing.values())
        elif isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def _load_yaml(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception as e:
        print(f"[config_loader] WARN: failed to load {path}: {e}")
        return {}


def load_config(symbol: str) -> dict[str, Any]:
    """Resolve config for a symbol via default → sector → ticker."""
    symbol = symbol.upper()
    cfg = _load_yaml(CONFIGS_DIR / "default.yaml")

    sector = SECTOR_MAP.get(symbol)
    if sector:
        sector_cfg = _load_yaml(CONFIGS_DIR / "sectors" / f"{sector}.yaml")
        cfg = _deep_merge(cfg, sector_cfg)

    ticker_cfg = _load_yaml(CONFIGS_DIR / "tickers" / f"{symbol}.yaml")
    if ticker_cfg:
        cfg = _deep_merge(cfg, ticker_cfg)

    cfg["_resolved_for"] = symbol
    cfg["_sector"] = sector
    return cfg


def _build_context(macro: dict | None, foreign: dict | None) -> dict:
    """Flatten macro + foreign into a single namespace for rule eval."""
    ctx: dict[str, Any] = {}
    if macro and isinstance(macro, dict):
        tickers = macro.get("tickers", {}) or {}
        for name, info in tickers.items():
            if isinstance(info, dict):
                ctx[name] = _DotDict(info)
            else:
                ctx[name] = _DotDict({})
        narr = macro.get("narrative", {}) or {}
        ctx["narrative"] = _DotDict(narr)
    else:
        for name in ("brent", "wti", "usdvnd", "dxy"):
            ctx[name] = _DotDict({})
        ctx["narrative"] = _DotDict({})

    if foreign and isinstance(foreign, dict) and "error" not in foreign:
        ctx["foreign"] = _DotDict({
            "bias": foreign.get("bias"),
            "share": foreign.get("foreign_share_of_volume_pct"),
            "net": foreign.get("net_foreign_volume"),
        })
    else:
        ctx["foreign"] = _DotDict({"bias": None, "share": None, "net": None})

    return ctx


class _DotDict(dict):
    """dict that exposes keys as attributes for eval-friendly access. Missing keys → None."""
    def __getattr__(self, key: str) -> Any:
        return self.get(key)


def _fmt_note(template: str, ctx: dict, foreign: dict | None) -> str:
    """Substitute {x.y} or {x} placeholders from ctx into template string."""
    def repl(m):
        path = m.group(1).split(".")
        cur: Any = ctx
        for p in path:
            if isinstance(cur, dict):
                cur = cur.get(p)
            elif hasattr(cur, p):
                cur = getattr(cur, p)
            else:
                cur = None
            if cur is None:
                break
        # Special fallback for {share} alias from foreign block.
        if cur is None and len(path) == 1 and foreign and path[0] == "share":
            cur = foreign.get("foreign_share_of_volume_pct")
        return str(cur) if cur is not None else "—"
    return re.sub(r"\{([^}]+)\}", repl, template)


def eval_macro_penalties(
    rules: list[dict],
    macro: dict | None,
    foreign: dict | None,
) -> tuple[int, list[str]]:
    """Evaluate each rule's `when` expression. Sum deltas. Return (total, notes)."""
    if not rules:
        return 0, []
    ctx = _build_context(macro, foreign)
    safe_globals = {"__builtins__": {}}
    total = 0
    notes: list[str] = []
    for rule in rules:
        if not isinstance(rule, dict):
            continue
        when = rule.get("when")
        delta = rule.get("delta", 0)
        note_template = rule.get("note", "")
        if not when:
            continue
        try:
            if eval(when, safe_globals, ctx):  # noqa: S307 — sandboxed namespace
                total += int(delta)
                notes.append(_fmt_note(note_template, ctx, foreign))
        except Exception as e:
            notes.append(f"[rule_eval_error: {rule.get('id')}: {e}]")
    return total, notes


def eval_custom_risks(
    rules: list[dict],
    macro: dict | None,
    foreign: dict | None,
) -> list[str]:
    """Evaluate custom_risks rules — return list of labels for matching rules."""
    if not rules:
        return []
    ctx = _build_context(macro, foreign)
    safe_globals = {"__builtins__": {}}
    out: list[str] = []
    for rule in rules:
        if not isinstance(rule, dict):
            continue
        when = rule.get("when")
        label = rule.get("label", rule.get("id", ""))
        if not when:
            continue
        try:
            if eval(when, safe_globals, ctx):  # noqa: S307
                out.append(_fmt_note(label, ctx, foreign))
        except Exception:
            pass
    return out


if __name__ == "__main__":
    import json
    import sys
    sym = sys.argv[1] if len(sys.argv) > 1 else "BSR"
    cfg = load_config(sym)
    print(json.dumps(cfg, indent=2, ensure_ascii=False, default=str))
