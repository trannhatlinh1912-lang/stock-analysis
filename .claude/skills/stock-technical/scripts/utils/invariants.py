"""Data invariants — a runtime safety net for the regime/sector layers.

Unit tests only catch bugs you anticipate. The bugs found 2026-05-29/30 were
all silent: they produced plausible-looking numbers (a fake -22% basket
return, a 1-day foreign proxy mislabelled as 20-day, a silently-skipped
breadth pillar). Invariants instead assert *properties that must hold
regardless of the data*, so they fire on real input every run and catch the
unknown.

Default mode is WARN (print to stderr, never break the pipeline). Set the env
var STOCK_STRICT=1 to raise on any violation (use in CI / pre-commit).

Each checker returns the list of violation strings it found (also reported).
"""
from __future__ import annotations

import os
import sys

ALLOWED_MARKET_REGIMES = {
    "BULLISH", "NEUTRAL", "NEUTRAL_TO_BEARISH", "BEARISH", "CRISIS", "UNKNOWN",
}
ALLOWED_SECTOR_REGIMES = {
    "BULLISH", "NEUTRAL_TO_BULLISH", "NEUTRAL", "NEUTRAL_TO_BEARISH",
    "BEARISH", "CRISIS", "UNKNOWN",
}
# A diversified sector basket should not move beyond this over 20 sessions in
# normal conditions; outside → almost certainly a data/aggregation artifact.
RET_20D_SANITY_PCT = 40.0


class InvariantViolation(Exception):
    """Raised in strict mode when a data invariant fails."""


def _strict() -> bool:
    return os.environ.get("STOCK_STRICT", "") not in ("", "0", "false", "False")


def _report(label: str, violations: list[str]) -> list[str]:
    if not violations:
        return []
    msg = f"[invariant] {label}: " + " | ".join(violations)
    if _strict():
        raise InvariantViolation(msg)
    print(msg, file=sys.stderr)
    return violations


def _in_range(name: str, val, lo: float, hi: float, out: list[str]) -> None:
    if val is None:
        return
    try:
        v = float(val)
    except (TypeError, ValueError):
        out.append(f"{name} not numeric: {val!r}")
        return
    if not (lo <= v <= hi):
        out.append(f"{name}={v} outside [{lo},{hi}]")


def check_mean_within_members(basket_value: float, member_values, where: str) -> list[str]:
    """A mean can never lie outside the range of its inputs. Violation here
    means members were misaligned (NaN dropped from the mean) — the root cause
    of the L3 -22% bug."""
    out: list[str] = []
    vals = [float(v) for v in member_values if v is not None]
    if not vals:
        return out
    lo, hi = min(vals), max(vals)
    # small float tolerance
    if not (lo - 1e-6 <= basket_value <= hi + 1e-6):
        out.append(f"basket {where}={basket_value:.4f} outside member range [{lo:.4f},{hi:.4f}]")
    return _report("basket_mean", out)


def check_market_regime(result: dict) -> list[str]:
    out: list[str] = []
    if result.get("regime") not in ALLOWED_MARKET_REGIMES:
        out.append(f"regime invalid: {result.get('regime')}")
    _in_range("confidence_pct", result.get("confidence_pct"), 0, 100, out)
    _in_range("ret_20d_pct", result.get("ret_20d_pct"), -RET_20D_SANITY_PCT, RET_20D_SANITY_PCT, out)

    pillars = result.get("pillars", {})
    expected = {"trend_long", "trend_medium", "breadth_vn30", "liquidity",
                "margin_debt", "foreign_cum_20d", "volatility"}
    missing = expected - set(pillars)
    if missing:
        out.append(f"missing pillar keys: {sorted(missing)}")

    breadth = pillars.get("breadth_vn30", {})
    _in_range("breadth_pct", breadth.get("value_pct"), 0, 100, out)

    # Foreign data-quality consistency: a directional vote must be backed by
    # >=20 real days; an abstain must not carry a cumulative.
    fr = pillars.get("foreign_cum_20d", {})
    flabel, ndays = fr.get("label"), fr.get("n_days")
    if flabel in ("positive", "negative", "neutral") and ndays is not None and ndays < 20:
        out.append(f"foreign votes '{flabel}' with only n_days={ndays} (<20)")
    if flabel == "data_insufficient" and fr.get("cum_20d_vnd") is not None:
        out.append("foreign data_insufficient but cum_20d_vnd set")
    return _report("market_regime", out)


def check_sector_regime(result: dict, member_ret_20d: list[float] | None = None) -> list[str]:
    out: list[str] = []
    if result.get("regime") not in ALLOWED_SECTOR_REGIMES:
        out.append(f"regime invalid: {result.get('regime')}")
    _in_range("confidence_pct", result.get("confidence_pct"), 0, 100, out)
    ret = result.get("ret_20d_pct")
    _in_range("ret_20d_pct", ret, -RET_20D_SANITY_PCT, RET_20D_SANITY_PCT, out)

    # Equal-weight basket return must sit within member returns (mean property).
    if ret is not None and member_ret_20d:
        vals = [float(v) for v in member_ret_20d if v is not None]
        if vals and not (min(vals) - 1e-6 <= float(ret) <= max(vals) + 1e-6):
            out.append(
                f"basket ret_20d={ret} outside member range "
                f"[{min(vals):.3f},{max(vals):.3f}] — misaligned basket"
            )

    dims = result.get("dimensions", {})
    br = dims.get("breadth", {})
    _in_range("breadth_pct", br.get("pct"), 0, 100, out)
    return _report(f"sector_regime[{result.get('sector')}]", out)
