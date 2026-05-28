# stock-technical / framework v3.0 — Run guide

Two modes:

1. **Framework v3.0** (9 layers, 32-ticker watchlist) — portfolio screening.
2. **Single-ticker v2.6** — deep technical for one symbol.

## Install

```bash
pip install vnstock pandas numpy yfinance pyyaml
```

Python 3.11+ recommended (project uses 3.14).

---

## MODE 1 — Framework v3.0 daily pipeline

### Quickest: one command

```bash
python3 scripts/run_daily.py            # full pipeline, skip cached, retry rate-limits
python3 scripts/run_daily.py --quick    # skip slow refetch (~2 min total)
python3 scripts/run_daily.py --force    # ignore cache, redo all
```

Output: `reports/screen_{DATE}.md` + `data/run_daily_log_{DATE}.json`.

### Manual per-step (debugging)

End-to-end run in order. Cached steps skip on re-run.

### One-time / quarterly refresh

```bash
# Refresh fundamentals (~8 years of BCTC per ticker)
python3 scripts/fetch_fundamentals.py

# Refresh liquidity (market cap + ADTV 20d)
python3 scripts/fetch_liquidity.py
```

Outputs: `data/fundamentals/{TICKER}.json`, `data/liquidity/{TICKER}.json`.

### Daily run

```bash
# 1. VNINDEX cache (skip if already today)
python3 scripts/market_context.py --start 2024-05-29 --end 2026-05-29

# 2. Layer 2 + 3 regimes
python3 scripts/market_regime.py --no-breadth
python3 scripts/sector_regime.py

# 3. Layer 1 quality
python3 scripts/quality_gate.py

# 4. Per-ticker technical pipeline
python3 scripts/technical_runner.py
# Or skip fetch if CSVs cached:
# python3 scripts/technical_runner.py --skip-fetch

# 5. Layer 4 mode permission per ticker
python3 scripts/trading_mode.py

# 6. Layer 5 catalyst auto+manual
python3 scripts/catalyst_detector.py

# 7. Layer 6 valuation
python3 scripts/valuation_compute.py

# 8. L2/L7 accumulator (foreign net flow append daily)
python3 scripts/foreign_snapshot_daily.py

# 9. Layer 7 lái detector
python3 scripts/lai_detector.py --skip-news

# 10. Orchestrator: classify ticker pool 3-state
python3 scripts/screen_watchlist.py
# Produces reports/screen_{DATE}.md

# 11. Layer 8 sizing (for PASS tickers)
python3 scripts/sizing_calculator.py

# 12. Layer 9 entry/exit plan + trade journal scaffold
python3 scripts/entry_exit_plan.py
```

### Read result

```bash
cat reports/screen_$(date +%Y-%m-%d).md
```

PASS bucket = eligible entries. WATCH = monitor (mode + reason listed). SKIP = killer layer failure.

For PASS tickers with ENTRY sizing: review `data/entry_plan/{TICKER}.json` for targets + 6 stops, fill `data/trade_journal/{TICKER}_{DATE}.yaml` emotional + lesson fields.

---

## MODE 2 — Single-ticker v2.6 technical

For deep analysis of one symbol (e.g. confirming entry on a PASS ticker, or ad-hoc analysis outside watchlist):

```bash
SYM=GAS
python3 scripts/market_context.py --start 2024-05-29 --end 2026-05-29
python3 scripts/fetch_price_audit.py --symbol $SYM --start 2024-05-29 --end 2026-05-29
python3 scripts/indicator_engine.py --csv data/${SYM}_price_VCI.csv --symbol $SYM
python3 scripts/empirical_stats.py --csv data/${SYM}_indicators.csv --symbol $SYM
python3 scripts/decision_framework.py --csv data/${SYM}_indicators.csv --symbol $SYM
```

Outputs:
- `data/${SYM}_decision_snapshot.json` — technical_state, confidence_score, entry_zones, 4-scenario playbook, etc.
- `reports/${SYM}_technical_decision.md` — Vietnamese human-readable.

### Optional v2.6 jobs

```bash
# Walk-forward backtest (quarterly refresh)
python3 scripts/backtest_decision.py --csv data/${SYM}_indicators.csv --symbol $SYM

# Calibration suite (monthly, ~20 tickers)
python3 scripts/calibrate.py --walk-forward
```

---

## USER MANUAL INPUT (framework)

Edit yaml in `configs/` per cadence:

| File | Cadence |
|---|---|
| `portfolio.yaml` | Daily (NAV + positions) |
| `catalyst_manual.yaml` | Weekly (CTCK reports + news) |
| `lai_manual_flags.yaml` | Weekly (prop trade observations) |
| `lai_overrides.yaml` | Ad-hoc (M&A confirmed, breakout real, etc) |
| `margin_debt.yaml` | Quarterly (SSC) |
| `banking_npl.yaml`, `re_presale.yaml`, `re_rnav_manual.yaml` | Quarterly (CTCK) |

Templates already in `configs/`. Each has `last_updated: YYYY-MM-DD` field — keep current to avoid stale degradation.

---

## VERIFY (smoke tests)

```bash
# vnstock API surface
python3 scripts/verify_vnstock_api.py

# manual loader stale check
python3 scripts/utils/manual_loader.py
```

---

## TROUBLESHOOTING

| Symptom | Cause | Fix |
|---|---|---|
| `requires market_regime + sector_regime for today` | L2/L3 cache stale (date rolled) | Re-run `market_regime.py` + `sector_regime.py` |
| `pipeline_failed` on a ticker in technical_runner | vnstock API hit rate limit | Wait + re-run with `--skip-fetch` once CSVs present |
| L2 NEUTRAL with low confidence + nav_cap_capped_neutral | Manual margin_debt.yaml missing/stale | Update with latest SSC quarterly data |
| `L5 catalyst invalid` for many bank tickers | No auto earnings beat + no manual catalyst | Add to `catalyst_manual.yaml` (policy, NIM expansion, etc) |
| `L6 combo fail` for sector | Valuation high P/E OR technical not confirming | Wait for pullback OR add cycle proxy data |
| Securities valuation `missing_inputs` | Basket too small (n=3, after self-exclude n=2 < 3 min) | Known limitation; need broader securities universe |

---

## ARCHITECTURE NOTES

- **No hardcoded ticker thresholds** — sector-level configs only.
- **All numerical knobs annotated** with provenance: `[calibrated 2026-05-28]`, `[heuristic]`, `[manual]`, `[pending_data]`.
- **Cap chain immutable** (Guardrail 4) — caps enforced in order liquidity → mode → sector → NAV → ticker. Conviction modifier scales UP only.
- **Manual data degradation explicit** (Guardrail 2) — stale yaml → tier downgrade with named effect, never silent fallback.
- **L7 lái = warning, not verdict** (Guardrail 3) — telemetry jsonl logs every fire for false-positive analysis after 6 months.
- **3-state output** (Guardrail 1) — PASS / WATCH / SKIP. Killer layers gate auto-SKIP.

---

## SPECS + GUARDRAILS

Read before modifying any layer:

- `configs/quality_gate_spec.md` — L1
- `configs/market_regime_spec.md` — L2
- `configs/sector_regime_spec.md` — L3
- `configs/trading_mode_spec.md` — L4
- `configs/catalyst_taxonomy_spec.md` — L5
- `configs/valuation_technical_spec.md` — L6
- `configs/lai_detection_spec.md` — L7
- `configs/sizing_tier_spec.md` — L8
- `configs/entry_exit_plan_spec.md` — L9
- `configs/build_guardrails.md` — 4 guardrails + audit checklist

Each spec includes re-calibration cadence + test cases.
