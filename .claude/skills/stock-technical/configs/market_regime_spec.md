# Layer 2 — Market Regime Specification (LOCKED 2026-05-28)

**Status**: spec finalized.
**Pipeline version target**: v3.0 (next-week build).

## Structure: 2A core + 2B macro overlay

```
[2A] Market Regime — 7 core pillars → state + confidence
[2B] Macro Overlay — USD/VND, DXY, Brent → sector-level modifiers
```

2A and 2B run independently. 2A determines trading mode permissions + NAV cap. 2B feeds sector regime (Layer 3).

## Layer 2A — 7 core pillars

| # | Pillar | Source | Threshold | Default if missing |
|---|---|---|---|---|
| 1 | `trend_long` | VNI close vs SMA200 | up if >, down if < | — (always available) |
| 2 | `trend_medium` | VNI close vs SMA50 | up if >, down if < | — (always available) |
| 3 | `breadth_vn30` | % VN30 stocks > SMA50 | strong ≥55%, weak ≤40% | neutral |
| 4 | `liquidity` | VN30 ΣGTGD 20d MA / 6m MA | rising ≥1.1, falling ≤0.9 | neutral |
| 5 | `margin_debt` | SSC quarterly margin/equity (manual fetch) | safe <50%, stretched >80% | neutral |
| 6 | `foreign_cum_20d` | Cum net foreign 20d (daily accumulator + weekly manual) | positive / neutral / negative | neutral |
| 7 | `volatility` | VNI ret_1d std 20d, vs rolling 252d baseline | spike if > baseline_mean + 1.5σ | normal |

⚠️ **Caveat breadth**: empirical 2024-2026 sample shows high breadth associated with mean reversion (negative forward return). Threshold retained per convention but interpretation noted in output.

### Confidence penalty
Each missing pillar: -10% confidence. Floor = 30%.

## Regime transition rule (Hybrid)

**Gate**: `trend_long`. If trend_long = down → state must be BEARISH or CRISIS regardless of other pillars (circuit breaker).

**Weighted scoring** (when trend_long = up):

Each pillar contributes +1 (positive) / 0 (neutral) / -1 (negative):
- trend_medium: +1 if up, -1 if down
- breadth: +1 if strong, -1 if weak, 0 neutral
- liquidity: +1 if rising, -1 if falling
- margin_debt: +1 if safe, -1 if stretched
- foreign_cum_20d: +1 if positive, -1 if negative
- volatility: 0 if normal, -2 if spike (heavier weight — spike is risk signal)

Score = sum of contributions (range -7 to +6, since vol max negative -2).

| Score | Regime |
|---|---|
| ≥ +4 | BULLISH |
| +1 to +3 | NEUTRAL |
| -1 to -3 | NEUTRAL_TO_BEARISH |
| ≤ -4 | BEARISH |

Special override: if `volatility=spike` AND `ret_20d < -10%` AND `breadth<30%` → CRISIS regardless of score.

## Trading mode permissions per regime

| Regime | Core (long hold) | Swing (2-6mo) | T+ tactical | NAV deploy cap |
|---|---|---|---|---|
| BULLISH | ✓ all modes allowed | ✓ | ✓ (full size) | 90% |
| NEUTRAL | ✓ | ✓ | ✓ but size cap 10% NAV/lệnh | 70% |
| NEUTRAL_TO_BEARISH | ✓ selective | ✓ selective | OFF | 55% |
| BEARISH | Deep value + catalyst only | OFF | OFF | 40% |
| CRISIS | Cash + opportunistic contrarian quality | OFF | OFF | 30% |

## Volatility spike calibration

- Window: rolling 252 trading days from evaluation date T (back to T-252).
- Compute: at each historical date t in window, `vol_t = std(ret_1d over t-20..t-1)`.
- Baseline: `mean(vol_t)` over 252 samples, `std(vol_t)` over 252 samples.
- Spike trigger: `vol_today > baseline_mean + 1.5 × baseline_std`.
- Requires ≥252 phiên of VN-Index history (available from market_context.py).

## Liquidity proxy

- Source: VN30 only (30 mã) — represents 60-70% market cap.
- Compute: sum(close × volume) of 30 VN30 stocks per day.
- MA20 / MA120 ratio = rolling indicator.
- Cost: 30 vnstock calls/day (acceptable).

## Foreign accumulator (hybrid)

- **Daily auto-snapshot**: scripts/foreign_snapshot_daily.py runs daily, appends KBS price_board foreign data for watchlist tickers (29 mã) to data/foreign_history.csv.
- **Weekly manual upload**: user exports full market foreign flow CSV from CafeF/VietStock weekly, places in data/foreign_weekly/YYYY-MM-DD.csv.
- Compute cum_20d when ≥20 trading days available; flag missing otherwise.

## Margin debt (manual quarterly)

- User updates configs/margin_debt.yaml each quarter after SBV/SSC report release.
- Format: `{quarter: "Q1-2026", margin_debt_billion_vnd: X, market_equity_billion_vnd: Y, ratio_pct: X/Y*100, source: "SBV"}`.
- If quarterly value missing → pillar=neutral.

## Layer 2B — Macro Overlay

Separate from 2A. Sector-specific impact (already calibrated in v2.x for oil_gas + real_estate).

| Indicator | Source | Sectors affected |
|---|---|---|
| USD/VND ret_20d | yfinance VND=X | banking (NIM proxy), import-heavy (steel, RE) |
| DXY ret_20d | yfinance DX-Y.NYB | banking, RE (rate sensitivity) |
| Brent crude ret_5d/20d | yfinance BZ=F | oil_gas (refining margin) |
| WTI crude | yfinance CL=F | oil_gas (validation) |
| Interbank lending rate | Manual SBV (proxy: VCB lending rate) | banking, all leveraged sectors |

## Output schema (Layer 2)

```yaml
layer_2a_market_regime:
  state: BULLISH | NEUTRAL | NEUTRAL_TO_BEARISH | BEARISH | CRISIS
  confidence_pct: 0-100  # 100 - 10 × missing_pillars_count
  score: -7 to +6
  trend_long_gate_passed: bool
  pillars:
    trend_long: up | down | flat
    trend_medium: up | down | flat
    breadth: {value_pct, label, caveat}
    liquidity: rising | flat | falling
    margin_debt: safe | elevated | stretched | missing
    foreign_cum_20d: {value_vnd, label}
    volatility: normal | elevated | spike
  missing_pillars: [list]
  trading_modes_allowed: [core, swing, t_plus]
  nav_deploy_cap_pct: 30-90

layer_2b_macro_overlay:
  usdvnd: {ret_20d_pct, label}
  dxy: {ret_20d_pct, label}
  brent: {ret_5d_pct, ret_20d_pct, label}
  interbank_rate: {value_pct, label, source}
```

## Today snapshot (2026-05-28) — partial test

Available:
- VNI close: 1874.43
- SMA50: 1795 → trend_medium = up
- SMA100: 1804 → near (mid-term basing)
- SMA200: missing (need fetch)
- breadth VN30: 73% → strong (caveat: empirical sample may flip interpretation)
- ret_20d: +1.14% → not crisis
- vol_20d std: missing baseline (need 252d setup)
- liquidity: not yet computed (Layer 2 script not built)
- margin_debt: not fetched
- foreign_cum_20d: not enough days

Tentative regime (with high missing penalty):
- trend_medium=up (+1), breadth=strong (+1), liquidity=missing (0), margin=missing (0), foreign=missing (0), vol=normal (0)
- Score = +2 (without trend_long verification)
- Confidence = 100 - 30 (3 missing) = 70%
- **Regime: NEUTRAL_TO_BULLISH** (pending trend_long confirm)

## Implementation order (next-week build)

1. `scripts/market_regime.py` — Layer 2A compute, output JSON daily.
2. `scripts/foreign_snapshot_daily.py` — accumulator.
3. `scripts/vn30_liquidity_daily.py` — Σ GTGD VN30.
4. `configs/margin_debt.yaml` — manual quarterly file.
5. Integrate with existing `market_context.py` + `external_overlay.py`.

## Re-calibration cadence

- Vol baseline: rolling, auto.
- Breadth caveat: review yearly after sufficient new regime data.
- Margin threshold: review yearly.
