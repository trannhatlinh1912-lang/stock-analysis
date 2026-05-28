---
name: stock-technical
description: 9-layer Vietnamese stock investment framework + single-ticker technical timing (v2.6 fully calibrated). Use for portfolio screening across 7 sectors (Banking/Oil&Gas/RE/Steel/Consumer/Tech/Securities) OR single-ticker technical decisions. Never fabricate numbers — missing data → pending_data with explicit reason.
---

# Stock Framework v3.0 + Technical v2.6

## TWO USAGE MODES

| Mode | When | Entry script |
|---|---|---|
| **Portfolio framework** (9 layers, 32-ticker pool) | Daily screening for entries/exits across personal investment portfolio | `scripts/screen_watchlist.py` |
| **Single-ticker technical** (v2.6 pipeline) | Deep technical timing for one symbol | `scripts/decision_framework.py` |

Both share `indicator_engine.py` and `decision_framework.py` outputs. Framework v3.0 wraps the technical pipeline as Layer 6B and adds 8 surrounding layers.

---

## FRAMEWORK v3.0 — 9 LAYERS

Investment principle (locked 2026-05-28):

> Mua cổ phiếu **pass quality gate**, ngành **regime thuận lợi**, có **catalyst** hoặc dòng tiền rõ, **định giá/technical xác nhận**, **không lái red**, **sizing phù hợp conviction**.
>
> Với T+: trend trade trên cổ phiếu tốt để kiếm tiền nhanh, nhưng **trading ngắn hạn** — có entry/exit rõ, **không mua đuổi**, **không gồng lỗ**.

### Layer flow

```
[1] Quality Gate         → fundamentals + tradable
[2] Market Regime        → trading mode permissions + NAV cap
[3] Sector Regime        → per-sector regime + modifier
[4] Trading Mode         → per-ticker eligible modes (core/swing/t_plus)
[5] Catalyst Taxonomy    → 8 category auto + manual, stack rule
[6] Valuation+Technical  → sector-specific val + technical state
[7] Lái Detection        → VN-specific manipulation warning
[8] Position Sizing      → Van Tharp + immutable cap chain
[9] Entry/Exit Plan      → 6 stops + targets + trade journal
```

### Layer specs (locked, in `configs/`)

- `quality_gate_spec.md` — 4 sub-layers, multi-flag pass/fail, sector-specific ROE/D/E thresholds
- `market_regime_spec.md` — 7 pillars, hybrid trend gate, 5 states + CRISIS
- `sector_regime_spec.md` — Universal tier (RS+breadth+flow) + sector cycle proxy
- `trading_mode_spec.md` — 3 modes × 5 regimes permission matrix
- `catalyst_taxonomy_spec.md` — 8 categories, 4 tiers, multi-stack +1 max
- `valuation_technical_spec.md` — 7 sector formulas + EV/EBITDA secondary
- `lai_detection_spec.md` — 6 symptoms, mode-specific yellow/red
- `sizing_tier_spec.md` — 7 tiers, conviction modifier 0.5×–2.0×
- `entry_exit_plan_spec.md` — 6 stops + mode-specific partial profit

### Guardrails (locked, in `configs/build_guardrails.md`)

1. **3-state output** — PASS / WATCH / SKIP (not binary). Killer layers auto-SKIP.
2. **Manual data freshness** — Stale file → degrade with explicit effect, never silent heuristic fallback.
3. **L7 = risk flag, not verdict** — Telemetry jsonl logs every fire. Threshold configurable. User override allowed.
4. **Cap chain immutable** — Conviction modifier UP-only. Caps enforce liquidity → mode → sector → NAV → ticker (in order). `binding_constraint` trace mandatory.

---

## DAILY PIPELINE (14 steps)

Pre-requisites: `pip install vnstock pandas numpy yfinance pyyaml`.

```bash
# 1. Fundamentals + liquidity (refresh after BCTC quarterly, else cached)
python3 scripts/fetch_fundamentals.py
python3 scripts/fetch_liquidity.py

# 2. Market context (VNINDEX cache, daily)
python3 scripts/market_context.py --start <2y ago> --end <today>

# 3. Layer 2 + 3 regimes
python3 scripts/market_regime.py [--no-breadth]
python3 scripts/sector_regime.py

# 4. Layer 1 quality
python3 scripts/quality_gate.py

# 5. Technical pipeline batch (per-ticker)
python3 scripts/technical_runner.py [--skip-fetch]

# 6. Layer 4 mode permissions
python3 scripts/trading_mode.py

# 7. Layer 5 catalyst (auto + manual)
python3 scripts/catalyst_detector.py

# 8. Layer 6 valuation
python3 scripts/valuation_compute.py

# 9. L2/L7 accumulators (daily, must run before market_regime tomorrow)
python3 scripts/foreign_snapshot_daily.py

# 10. Layer 7 lái
python3 scripts/lai_detector.py [--skip-news]

# 11. Orchestrator: classify ticker pool 3-state
python3 scripts/screen_watchlist.py

# 12. Layer 8 sizing (for PASS tickers)
python3 scripts/sizing_calculator.py

# 13. Layer 9 entry/exit plan + journal scaffold (for ENTRY-sized tickers)
python3 scripts/entry_exit_plan.py
```

Output of step 11: `reports/screen_{DATE}.md` + `data/screen_{DATE}.json`.

---

## USER MANUAL INPUT FILES

User maintains these yaml files. Stale > threshold → layer degrades per Guardrail 2.

| File | Frequency | Stale threshold | Effect when stale |
|---|---|---|---|
| `configs/portfolio.yaml` | Daily | 7d | warning only |
| `configs/catalyst_manual.yaml` | Weekly | 14d | catalyst tier downgrade 1 step |
| `configs/lai_manual_flags.yaml` | Weekly | 30d | manual symptoms 3+5 ignored |
| `configs/lai_overrides.yaml` | Ad-hoc | — | per-entry `override_until` |
| `configs/margin_debt.yaml` | Quarterly (SSC) | 30d | NAV cap → Neutral max (70%) |
| `configs/banking_npl.yaml` | Quarterly (CTCK) | 90d | banking Tier 1 blocked |
| `configs/re_presale.yaml` | Quarterly | 90d | RE Tier 1 blocked |
| `configs/re_rnav_manual.yaml` | Quarterly | 90d | RE valuation primary unavailable |
| `configs/sector_valuation_overrides.yaml` | Quarterly | 90d | basket-derived means with sample warning |

---

## OUTPUT ARTIFACTS

```
data/
  fundamentals/{TICKER}.json        # L1 source
  liquidity/{TICKER}.json           # L1 source
  market_regime_{DATE}.json         # L2
  sector_regime_{DATE}.json         # L3
  quality_gate/{TICKER}.json        # L1 result
  trading_mode/{TICKER}.json        # L4
  catalyst/{TICKER}.json            # L5
  valuation/{TICKER}.json           # L6A
  technical/{TICKER}.json           # L6B compact summary
  {TICKER}_decision_snapshot.json   # L6B full v2.6 output
  lai/{TICKER}.json                 # L7
  foreign_history.csv               # L2/L3/L7 accumulator
  lai_signal_history.jsonl          # L7 telemetry (Guardrail 3)
  sizing/{TICKER}.json              # L8
  entry_plan/{TICKER}.json          # L9
  trade_journal/{TICKER}_{DATE}.yaml # L9 scaffold
  screen_{DATE}.json                # orchestrator final
reports/
  screen_{DATE}.md                  # daily human-readable report
  quality_gate_summary_{DATE}.md
  fundamentals_distribution.md
  liquidity_summary.md
```

---

## WATCHLIST (locked 2026-05-28)

34-ticker pool in `configs/watchlist.yaml`:

- **CORE 12**: MBB, VCB, GAS, PLX, VHM, NLG, HPG, HSG, VNM, MWG, FPT, VND
- **SWING tactical 12** (cyclical/turnaround/structural-risk)
- **DROP 3**: TLH, SMC (L1 HARD ROE), NVL (3 high warnings)
- **Sector baskets** for L3 RS: Banking 5, O&G 5, RE 6, Steel 5, Consumer 5, Tech 5, Securities 3

---

## CLASSIFICATION RULES (Guardrail 1)

### Killer layers → auto SKIP

- L1 HARD_FAIL or DATA_MISSING
- L2 CRISIS or UNKNOWN
- L3 sector CRISIS
- L4 no eligible modes (e.g. tradability fail)
- L7 RED lái for best mode
- (L8 sizing REJECT → no entry plan generated)

### Non-killer concerns → WATCH

- L1 WARNING
- L2/L3 NEUTRAL_TO_BEARISH / BEARISH
- L5 catalyst invalid (no actionable bullish)
- L6 combination fail for all eligible modes
- L7 YELLOW lái for best mode

### All clear → PASS

→ proceed to L8 sizing → L9 plan generation.

---

## SECTION 2 — SINGLE-TICKER TECHNICAL (v2.6 pipeline)

For direct technical analysis of one symbol (not portfolio mode):

```bash
python3 scripts/market_context.py --start <2y ago> --end <today>
python3 scripts/fetch_price_audit.py --symbol {SYM} --start ... --end ...
python3 scripts/indicator_engine.py --csv data/{SYM}_price_VCI.csv --symbol {SYM}
python3 scripts/empirical_stats.py --csv data/{SYM}_indicators.csv --symbol {SYM}  # optional
python3 scripts/decision_framework.py --csv data/{SYM}_indicators.csv --symbol {SYM}
```

Outputs: `data/{SYM}_decision_snapshot.json` + `reports/{SYM}_technical_decision.md`.

### Technical state priority (decision_framework.py)

1. `DISTRIBUTION` — close < SMA20, MACD hist < 0, CMF20 < 0, OBV slope < 0
2. `BREAKOUT_WITH_EXHAUSTION_RISK` — BB above_upper + Stoch %K ≥ 90 + vol_ratio ≥ 2
3. `BULLISH_TREND_CONFIRMED` — full SMA stack + MACD hist > 0 + vol_ratio ≥ 1
4. `BREAKOUT_CONFIRMED` — close > SMA20/50/200 + vol_ratio ≥ 1.5 + ret_1d > 2%
5. `ACCUMULATION` — close within 1 ATR of SMA20/50 + vol_ratio 0.8–1.5
6. `WATCH` — fallback

### Hard rules (v2.6)

- `BREAKOUT_WITH_EXHAUSTION_RISK` → no chase, confidence capped at 68.
- Triple-risk combo → −5 adjusted score.
- Position size capped 20% NAV, risk-per-trade 1% NAV.
- ATR%-scaled sizing: `atr_pct ≤ 1.5%` → factor 1.0; `≥ 5%` → factor = 1.5/atr_pct.
- Liquidity floor: `turnover_20d_avg < 5B VND/day` → cap 5% NAV.
- Resistance levels within 0.3% → merge confluence.
- Never output "STRONG BUY" from technical alone.

### Macro penalty (v2.1, calibrated)

| Sector | Trigger | Δ score |
|---|---|---|
| oil_gas | Brent ret_5d ≤ −5% | −8 |
| oil_gas | Brent ret_5d ≥ +5% | +4 |
| real_estate | DXY ret_20d ≥ +2% | −3 |
| Universal | foreign bias=net_sell AND share ≥ 20% | −3 |

Banking + steel + utilities macro REMOVED per v2.6 calibration — no significant driver in 2022-2026 OLS.

---

## DATA RULES (BOTH MODES)

- Missing data → write `missing_data` or `pending_data`. **Never infer.**
- vnstock 4.0.2 community version: financial statements limited to 8 years per ticker.
- vnstock whitelist sources: `vci`, `msn`, `kbs`, `dnse`, `fmp`. **TCBS not accepted**.
- VCI close in **thousand VND**; corporate action `value_per_share` in **VND**. `fetch_price_audit.py` auto-detects + normalizes.
- Verified vnstock APIs (see `scripts/verify_vnstock_api.py`):
  - ✓ `Finance.income_statement / balance_sheet / cash_flow`
  - ✓ `Company.events / shareholders / officers / news`
  - ✓ `Quote.history`
  - ✗ `Trading.insider_deal / prop_trade / foreign_trade` (NotImplementedError)
  - ✗ `Finance.ratio()` (returns wrong data, compute manually)
- **CẤM bịa số liệu**. Every threshold in spec annotated:
  - `[calibrated YYYY-MM-DD]` — empirical
  - `[heuristic]` / `[manual]` — judgement
  - `[pending_data]` — uncalibrated with explicit reason

---

## RE-CALIBRATION CADENCE

| Component | Frequency |
|---|---|
| Sector ROE/D/E thresholds | Quarterly after BCTC |
| Market regime baselines (vol, breadth) | Rolling auto + yearly review |
| Sector regime thresholds | Quarterly |
| Catalyst auto-detector thresholds | Quarterly |
| Sector P/E means | Quarterly |
| Lái detection thresholds | After 6mo live false-positive analysis |
| Sizing modifiers | After 6mo live journal |
| Stop loss thresholds | Yearly |
| Single-ticker macro penalty regression | Yearly walk-forward |

---

## DEFERRED / PHASE 4 BACKLOG

| Item | Status | Blocker |
|---|---|---|
| `vn30_liquidity_daily.py` | Pending | L2 liquidity pillar empty |
| `insider_snapshot_daily.py` (L7 symptom 2) | Pending | Needs 90-day cache build-up |
| Banking NIM proxy, RE OCF trend, Steel inv turnover, Consumer SSSG | Pending | L3 cycle dimension empty |
| EV/EBITDA secondary | Pending | Needs D&A + cash parsing |
| RNAV manual yaml (RE valuation primary) | Pending | User maintenance |
| DCF tech valuation | Pending | User input g + WACC |
| News API for L7 substantive keyword check | Pending | Currently --skip-news only |

These do NOT block daily pipeline. Mark as `pending_data` with explicit reason.

---

## REFERENCES

- `README.md` — quickstart end-to-end run guide.
- `configs/*_spec.md` — 9 layer specs (locked).
- `configs/build_guardrails.md` — 4 guardrails with code enforcement points + unit test names.
- `verify_vnstock_api.py` — vnstock 4.0.2 endpoint verification table.
