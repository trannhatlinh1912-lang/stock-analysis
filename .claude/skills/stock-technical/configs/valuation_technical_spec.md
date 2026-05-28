# Layer 6 — Valuation + Technical Setup Specification (LOCKED 2026-05-28)

**Status**: spec finalized.
**Pipeline version target**: v3.0.

## 6A — Valuation per sector

### Primary methods (per sector)

| Sector | Primary formula | Auto/Manual | Entry threshold |
|---|---|---|---|
| Banking | Justified P/B = (ROE - g) / (CoE - g) | Auto | Actual P/B < Justified × 0.85 |
| Oil & Gas | P/E normalised (5y avg EPS) | Auto | P/E_norm < 10 |
| Real Estate | P/RNAV | Manual (CTCK report) | P/RNAV < 0.5 |
| Steel | P/E normalised + commodity cycle position | Auto + manual | P/E_norm < 10 AND iron ore < bottom 25%ile |
| Consumer | P/E vs 5y mean ngành + PEG | Auto | P/E < 5y_mean − 0.5σ AND PEG < 1.5 |
| Tech | PEG + DCF (2-stage simple) | Auto PEG + manual DCF | PEG < 1.5 OR DCF discount > 20% |
| Securities | P/B vs 5y mean | Auto | P/B < 5y_mean − 0.5σ |

### Secondary check: EV/EBITDA

Apply as confirmation for:
- **Consumer**: EV/EBITDA < 10
- **Tech**: EV/EBITDA < 15
- **Oil & Gas**: EV/EBITDA < 6
- **Steel**: EV/EBITDA < 8

EV = Market Cap + Total Debt − Cash. EBITDA from cash_flow + adjustments.

Banking and RE skip EV/EBITDA (banking has different capital structure, RE has lumpy EBITDA).

### Compute requirements

- **Current price**: Quote.history latest close (auto)
- **EPS series**: income_statement isa23 (auto, 8y limit)
- **Total debt**: balance_sheet bsa54 (auto)
- **Cash**: balance_sheet (need parse "tiền và tương đương" item)
- **Sector P/E mean**: compute from watchlist basket, caveat small sample
- **Justified P/B inputs**:
  - g (growth) = heuristic 3-5% (manual override per ticker)
  - CoE (cost of equity) = heuristic 10-13% banking, 12-15% non-bank (manual override)
- **PEG**: P/E ÷ NI 3y CAGR (auto)
- **DCF tech**: 2-stage simple, growth + terminal value, user input growth + WACC

### Outputs

```yaml
ticker: VCB
sector: banking
valuation:
  primary:
    method: justified_pb
    actual_pb: 2.85
    justified_pb: 3.20
    inputs: {roe_3y_avg: 17.66, g_assumed: 4.0, coe_assumed: 11.0}
    discount_vs_justified_pct: 10.9
    threshold_pct: 15  # actual must be < justified × 0.85
    pass: false  # 10.9% discount < 15% threshold
  secondary:
    method: ev_ebitda
    skipped_reason: banking_excluded
data_completeness_pct: 100
```

## 6B — Technical setup per mode

### Core entry technical (LOOSE — "good enough, not breaking down")
- Close > SMA200 (long-term uptrend intact)
- OR mean reversion to SMA200 from above (close ∈ [SMA200 × 0.95, SMA200 × 1.05]) with volume confirm
- RSI 14 ∈ [40, 65] (not extreme either direction)
- No major support break in last 6 months

### Swing entry technical (MEDIUM)
- Close > SMA50 OR pullback to SMA50 within 1 ATR
- Volume confirm: vol_ratio ∈ [1.0, 1.5] × MA20 (not extreme spike, not dead)
- MACD hist positive or turning positive (slope last 5 days ≥ 0)
- Structure: HH/HL intact (structure_label != downtrend_structure)

### T+ entry technical (STRICT)
- Setup A: Breakout from base ≥5 weeks (close > swing_high_20 with volume ≥ 1.5× MA20)
- OR Setup B: Pullback to MA20 in uptrend (close > SMA50 > SMA200) with RSI bounce from 40 zone
- ADX > 20 (trend developing or strong)
- Ichimoku: above_cloud OR breaking cloud upward
- VWAP: close ≥ VWAP20 (institutional support)

## 6C — Combination rules per mode

| Mode | Valuation | Technical | Logic |
|---|---|---|---|
| Core | REQUIRED pass | REQUIRED pass (loose) | AND |
| Swing | OR | OR | At least 1 of 2 |
| T+ | Optional (neutral OK) | REQUIRED pass (strict) | Technical drives |

Note for Swing: if neither passes → SKIP. If valuation pass but technical broken → wait for technical confirm. If technical pass but valuation extreme overvalued → smaller size or skip.

## 6D — Output structure (no aggregate score)

```yaml
ticker: VCB
mode_requested: core
layer_6:
  valuation_pass: true
  technical_pass: true
  entry_recommended: true
  combination_rule: "core_requires_both"
  
  valuation_detail:
    primary_method: justified_pb
    primary_pass: true
    secondary_method: ev_ebitda
    secondary_pass: skipped
  
  technical_detail:
    setup_type: core_long_term_uptrend
    close_vs_sma200: above
    rsi_in_range: true (rsi14=52)
    no_major_breakdown_6m: true
```

## Data gaps + workarounds

| Item | Status | Workaround |
|---|---|---|
| Sector P/E 5y mean | ⚠️ small basket sample (5-6 mã) | Compute caveat sample size, allow user override `configs/sector_valuation_overrides.yaml` |
| RNAV cho RE | ✗ no source | Manual CTCK input `configs/re_rnav_manual.yaml` quarterly |
| DCF tech | ✗ requires assumptions | Simple 2-stage Excel-style model, user input g + WACC |
| Justified P/B (g, CoE) | ⚠️ heuristic | Default per sector + user override |
| Cash for EV | ⚠️ parse balance_sheet | Find item_id for "tiền và tương đương" |
| iron ore bottom 25%ile (steel cycle) | ⚠️ requires historical | yfinance TIO=F + compute percentile |

## Re-calibration

- Sector P/E 5y mean: re-compute quarterly.
- Justified P/B default inputs (g, CoE): yearly review based on rate environment.
- Technical thresholds (RSI 40-65, ADX 20, vol_ratio 1.5): already calibrated in v2.5.
- DCF assumptions: per-ticker manual update yearly.

## Integration với existing skills

- `stock-valuation` skill (đã có) cung cấp framework valuation. Layer 6A reuse.
- `stock-technical` skill v2.6 (đã có, calibrated) cung cấp technical signals. Layer 6B reuse `decision_framework.determine_state` + indicators directly.
- Mới: combination layer (6C) + sector-specific valuation formulas (6A primary + secondary).
