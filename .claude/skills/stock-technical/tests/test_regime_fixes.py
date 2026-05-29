"""Regression tests locking the L2/L3 regime fixes (2026-05-29/30).

Stdlib unittest only — no pip deps. Run:
    python3 -m unittest discover -s tests -v
    STOCK_STRICT=1 python3 -m unittest discover -s tests   # strict raises

Each test reproduces the *actual* bug signature so the fix cannot silently
regress.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from utils.invariants import (  # noqa: E402
    check_market_regime,
    check_mean_within_members,
    check_sector_regime,
)


class TestInvariants(unittest.TestCase):
    """Pure-function invariants — the safety net itself."""

    def test_mean_within_members_ok(self):
        # 143 is a valid mean of these members
        self.assertEqual(check_mean_within_members(143.0, [100.3, 240.4, 106.3], "x"), [])

    def test_mean_below_members_caught(self):
        v = check_mean_within_members(50.0, [100, 120, 130], "x")
        self.assertTrue(v)

    def test_sector_basket_ret_outside_member_range_caught(self):
        # The exact L3 bug: basket -22% while every member is near flat.
        v = check_sector_regime(
            {"sector": "banking", "regime": "NEUTRAL_TO_BEARISH",
             "confidence_pct": 75, "ret_20d_pct": -22.08, "dimensions": {}},
            member_ret_20d=[5.5, -4.0, 5.9, -0.4, -3.8, 4.7],
        )
        self.assertTrue(any("outside member range" in x for x in v))

    def test_sector_basket_ret_within_range_ok(self):
        v = check_sector_regime(
            {"sector": "banking", "regime": "NEUTRAL",
             "confidence_pct": 75, "ret_20d_pct": 0.5, "dimensions": {}},
            member_ret_20d=[5.5, -4.0, 5.9, -0.4, -3.8, 4.7],
        )
        self.assertEqual(v, [])

    def test_foreign_vote_without_history_caught(self):
        # The L2 bug: a directional vote backed by <20 distinct days.
        v = check_market_regime(_market_result(foreign={"label": "negative", "n_days": 1}))
        self.assertTrue(any("foreign votes" in x for x in v))

    def test_foreign_abstain_ok(self):
        v = check_market_regime(_market_result(
            foreign={"label": "data_insufficient", "n_days": 1, "cum_20d_vnd": None}))
        self.assertEqual(v, [])

    def test_breadth_out_of_bounds_caught(self):
        v = check_market_regime(_market_result(breadth_pct=150.0))
        self.assertTrue(any("breadth_pct" in x for x in v))


class TestForeignPillar(unittest.TestCase):
    """L2 fix: aggregate net_vnd by DATE, gate on >=20 distinct days."""

    def _run_with_history(self, rows: list[dict]):
        import market_regime as mr
        with mock.patch.object(pd, "read_csv", return_value=pd.DataFrame(rows)), \
             mock.patch("pathlib.Path.exists", return_value=True):
            return mr._foreign_pillar()

    def test_one_day_many_tickers_is_insufficient(self):
        # 25 ticker-rows but a SINGLE date — old code mislabelled this 20d.
        rows = [{"date": "2026-05-29", "ticker": f"T{i}", "net_vnd": -1e6} for i in range(25)]
        out = self._run_with_history(rows)
        self.assertEqual(out["label"], "data_insufficient")
        self.assertEqual(out["n_days"], 1)
        self.assertIsNone(out["cum_20d_vnd"])

    def test_twenty_distinct_days_votes(self):
        rows = []
        for d in range(20):
            rows.append({"date": f"2026-05-{d+1:02d}", "ticker": "VCB", "net_vnd": 5e6})
            rows.append({"date": f"2026-05-{d+1:02d}", "ticker": "MBB", "net_vnd": 3e6})
        out = self._run_with_history(rows)
        self.assertEqual(out["label"], "positive")
        self.assertEqual(out["n_days"], 20)
        self.assertGreater(out["cum_20d_vnd"], 0)


class TestBasketAlignment(unittest.TestCase):
    """L3 fix: inner-join member dates before normalizing + mean."""

    def test_misaligned_members_no_fake_return(self):
        import sector_regime as sr
        dates = pd.date_range("2024-01-01", periods=120, freq="D")
        # Member A full history; member B stale (ends 3 days early) + B starts
        # later — the union+mean-over-NaN pattern fabricated tail returns.
        a = pd.DataFrame({"time": dates, "close": [100 + i * 0.1 for i in range(120)]})
        b = pd.DataFrame({"time": dates[10:-3], "close": [200 + i * 0.2 for i in range(107)]})

        def fake_fetch(sym, start, end):
            return {"A": a, "B": b}[sym]

        with mock.patch.object(sr, "_fetch_ohlc", side_effect=fake_fetch):
            df, used = sr._basket_close(["A", "B"], "2024-01-01", "2024-04-30")

        self.assertEqual(set(used), {"A", "B"})
        # No NaN in aligned member columns (would distort the mean).
        self.assertFalse(df[["A", "B"]].isna().any().any())
        # Basket mean within member range at the tail (mean property).
        last = df.iloc[-1]
        self.assertGreaterEqual(last["basket"], min(last["A"], last["B"]) - 1e-6)
        self.assertLessEqual(last["basket"], max(last["A"], last["B"]) + 1e-6)


class TestCalibrateBasket(unittest.TestCase):
    """Audit fix: calibrate._basket_returns must inner-join members, not
    average a shifting membership via mean(skipna=True)."""

    def test_misaligned_members_inner_joined(self):
        import calibrate as cal
        # Both members >=50 rows (pass the len gate) but offset windows, so the
        # union has partial-membership rows the old skipna mean would average.
        a = pd.DataFrame({"date": pd.date_range("2024-01-01", periods=80, freq="D"),
                          "close": [100 + i for i in range(80)]})
        b = pd.DataFrame({"date": pd.date_range("2024-01-21", periods=80, freq="D"),
                          "close": [200 + i for i in range(80)]})

        def fake_hist(sym, days=540):
            return {"A": a, "B": b}[sym]

        with mock.patch.object(cal, "fetch_close_history", side_effect=fake_hist):
            out = cal._basket_returns(["A", "B"], horizon_days=5)

        self.assertIsNotNone(out)
        # No NaN basket_ret (a partial-membership row would have leaked through).
        self.assertFalse(out["basket_ret"].isna().any())
        # Kept dates ⊆ each member's valid (post-pct_change) date set.
        a_valid = set(a["date"].iloc[5:])
        b_valid = set(b["date"].iloc[5:])
        kept = set(out["date"])
        self.assertTrue(kept)
        self.assertTrue(kept.issubset(a_valid & b_valid))


class TestSizingCounterTrend(unittest.TestCase):
    """Option-2 swing fix: val + catalyst but no technical = tier 8
    (counter-trend falling-knife), allowed at a hard-capped tiny size."""

    def test_val_catalyst_no_tech_is_tier8(self):
        import sizing_calculator as sz
        self.assertEqual(
            sz.assign_tier("swing", "hard", valuation_pass=True,
                           technical_pass=False, lai_level="green"), 8)

    def test_cheap_but_no_catalyst_still_rejected(self):
        import sizing_calculator as sz
        # Pure "it's cheap" with no catalyst must NOT get an entry (anti-pattern).
        self.assertIsNone(
            sz.assign_tier("swing", None, valuation_pass=True,
                           technical_pass=False, lai_level="green"))

    def test_tech_confirmed_unchanged(self):
        import sizing_calculator as sz
        self.assertEqual(
            sz.assign_tier("swing", "hard", True, True, "green"), 3)
        self.assertEqual(
            sz.assign_tier("swing", None, False, True, "green"), 4)

    def test_tier8_hard_capped_small(self):
        import sizing_calculator as sz
        out = sz.calculate(
            ticker="X", mode="swing", tier=8, entry_price=100.0,
            primary_stop=99.0,  # tight stop -> large van-tharp base
            atr_pct=1.0, adtv_b_vnd=500.0, sector="banking",
            portfolio={"nav_total_vnd": 1e9, "total_deployed_pct_nav": 0,
                       "positions": [], "sector_allocations_pct_nav": {}},
            nav_deploy_cap_pct=70.0,
        )
        self.assertEqual(out["action"], "ENTRY")
        self.assertLessEqual(out["final_size_pct_nav"], sz.COUNTER_TREND_CAP_PCT + 1e-6)
        self.assertEqual(out["binding_constraint"], "counter_trend_cap")
        self.assertIn("warnings", out)


class TestGoldenSnapshot(unittest.TestCase):
    """Frozen real outputs (2026-05-30, hand-verified after the L2/L3 fixes).

    Guards two directions: (1) the invariant net must accept known-good
    output (so tightening an invariant can't start rejecting valid data —
    a false-positive regression); (2) documents the verified reference.
    """

    GOLDEN = Path(__file__).resolve().parent / "golden"

    def _strict(self, fn, *args):
        import os
        prev = os.environ.get("STOCK_STRICT")
        os.environ["STOCK_STRICT"] = "1"
        try:
            fn(*args)  # must NOT raise on known-good data
        finally:
            if prev is None:
                os.environ.pop("STOCK_STRICT", None)
            else:
                os.environ["STOCK_STRICT"] = prev

    def test_market_regime_golden_passes_invariants(self):
        import json
        d = json.loads((self.GOLDEN / "market_regime.golden.json").read_text())
        self._strict(check_market_regime, d)
        # Reference anchors (frozen): the post-fix accurate read.
        self.assertEqual(d["regime"], "NEUTRAL")
        self.assertEqual(d["pillars"]["foreign_cum_20d"]["label"], "data_insufficient")
        self.assertEqual(d["pillars"]["breadth_vn30"]["label"], "strong")

    def test_sector_regime_golden_passes_invariants(self):
        import json
        d = json.loads((self.GOLDEN / "sector_regime.golden.json").read_text())
        for sector, result in d["sectors"].items():
            with self.subTest(sector=sector):
                self._strict(check_sector_regime, result)


def _market_result(foreign=None, breadth_pct=60.0):
    pillars = {k: {} for k in ("trend_long", "trend_medium", "breadth_vn30",
                               "liquidity", "margin_debt", "foreign_cum_20d", "volatility")}
    pillars["breadth_vn30"] = {"label": "strong", "value_pct": breadth_pct}
    pillars["foreign_cum_20d"] = foreign or {"label": "data_insufficient", "n_days": 1, "cum_20d_vnd": None}
    return {"regime": "NEUTRAL", "confidence_pct": 90, "score": 2,
            "ret_20d_pct": 0.5, "pillars": pillars}


if __name__ == "__main__":
    unittest.main()
