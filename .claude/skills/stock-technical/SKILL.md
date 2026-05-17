---
name: stock-technical
description: Technical analysis skill for Vietnamese stocks (e.g. GAS, BSR, MBB, REE, HPG). Use for timing zones, risk management, support/resistance, money flow. Always run the data-quality audit before drawing conclusions. Do not fabricate numbers — missing data must be labelled missing_data.
---

# Stock Technical

## 1. Purpose

Technical timing for Vietnamese equities. Supports buy/sell timing — does **not** replace fundamental analysis or valuation. User-facing summaries in Vietnamese; pipeline logs/code in English.

## 2. Mandatory workflow

Run the three modules in `scripts/` in order. Each step writes artifacts the next step consumes.

1. **Fetch OHLCV + corporate actions + audit adjusted price**
   ```bash
   python scripts/fetch_price_audit.py --symbol {SYMBOL} --start YYYY-MM-DD --end YYYY-MM-DD
   ```
   Artifacts: `data/{SYMBOL}_price_VCI.csv`, `data/{SYMBOL}_corporate_actions.csv`, `reports/{SYMBOL}_data_quality_report.md` (includes `adjusted_price_status` + `long_ma_confidence`).

2. **Calculate indicators**
   ```bash
   python scripts/indicator_engine.py --csv data/{SYMBOL}_price_VCI.csv --symbol {SYMBOL}
   ```
   Artifacts: `data/{SYMBOL}_indicators.csv`, `reports/{SYMBOL}_indicator_report.md`.

3. **Decision snapshot**
   ```bash
   python scripts/decision_framework.py --csv data/{SYMBOL}_indicators.csv --symbol {SYMBOL}
   ```
   Artifacts: `data/{SYMBOL}_decision_snapshot.json`, `reports/{SYMBOL}_technical_decision.md`.

Do not skip step 1. The decision is invalid until adjusted-price status is known.

## 3. Data rules

- If `adjusted_price_status != "confirmed"`, treat SMA100/SMA200 as **medium_low confidence** at best; do not promote them to high-confidence trend signals.
- Missing data → write `missing_data`. Never infer or fabricate.
- Price-unit scale check: VCI returns close in **thousand VND**; corporate action `value_per_share` is in **VND**. Normalise before computing expected ex-rights drop. `fetch_price_audit.py` auto-detects when `median_close ∈ (1, 1000)` and applies `scale = 1000 VND/unit`.
- Never load raw OHLCV / long indicator series into the user-facing message.

## 4. Indicators (computed by `indicator_engine.py`)

- Trend: SMA20/50/100/200, EMA20/50, MA alignment flag, golden/death cross, distance-from-MA %.
- Momentum: RSI14, MACD (12,26,9) line/signal/histogram, Stochastic %K(14)/%D(3).
- Volatility: ATR14 (Wilder), Bollinger Bands (20, 2σ), `bb_position`, ATR/Close %.
- Volume: vol_ma20, vol_ratio, up/down-volume 20D, vol_spike flag (≥2× MA20).
- Money flow: OBV, OBV slope 20D, MFI14, CMF20.
- Price action: returns 1/5/20/60/120D, 52W high/low, distance-from-52W %.
- Support/Resistance: swing high/low 20/50/100, classic pivot + R1/S1, ATR stops (1.5×, 2×).

## 5. Decision states (produced by `decision_framework.py`)

Priority order (first match wins):

1. `DISTRIBUTION` — close < SMA20, MACD hist < 0, CMF20 < 0, OBV slope < 0.
2. `BREAKOUT_WITH_EXHAUSTION_RISK` — breakout-confirmed AND BB above_upper AND Stoch %K ≥ 90 AND vol_ratio ≥ 2.
3. `BULLISH_TREND_CONFIRMED` — close > SMA20 > SMA50 > SMA100 > SMA200, MACD hist > 0, vol_ratio ≥ 1.
4. `BREAKOUT_CONFIRMED` — close > SMA20/50/200, vol_ratio ≥ 1.5, ret_1d > 2%, MACD hist > 0.
5. `ACCUMULATION` — close within 1 ATR of SMA20 or SMA50, vol_ratio 0.8–1.5, momentum non-negative, BB ≠ above_upper.
6. `WATCH` — fallback when signals mixed or insufficient.

## 6. Risk rules

- `breakout_exhaustion_risk` — BB == above_upper AND vol_ratio ≥ 2 AND Stoch %K ≥ 90 AND ret_1d ≥ 5%.
- `near_sma100_resistance` — close < SMA100 AND dist_sma100_pct ∈ [-2%, 0%].
- `trend_not_fully_aligned` — NOT (close > SMA20 > SMA50 > SMA100 > SMA200).
- Other automated risks: RSI extremes, CMF distribution divergence, MACD momentum fade, 52W proximity.

## 7. Decision output schema

`data/{SYMBOL}_decision_snapshot.json` must contain:

`technical_state`, `raw_score`, `adjusted_score`, `confidence_score` (final),
`score_breakdown` (incl. `triple_risk_penalty_applied`, `exhaustion_cap_applied`),
`trend_status`, `momentum_status`, `volume_status`, `money_flow_status`, `volatility_status`,
`entry_strategy`, `entry_zones` (`retest_aggressive`, `retest_standard`, `breakout_confirmation_zone`),
`stop_loss` (`primary_stop`, `hard_stop`, `structural_stop`),
`resistance_levels` (incl. `confluence_resistance` merges),
`support_levels`, `upgrade_conditions`, `downgrade_conditions`,
`key_risks`, `final_view` (Vietnamese).

## 8. Hard rules

- `BREAKOUT_WITH_EXHAUSTION_RISK` → entry strategy: **không mua đuổi tỷ trọng lớn**; chờ retest hoặc xác nhận với volume duy trì.
- `BREAKOUT_WITH_EXHAUSTION_RISK` → `confidence_score` is **capped at 68** regardless of raw rubric.
- Triple-risk combo (`breakout_exhaustion_risk` + `near_sma100_resistance` + `trend_not_fully_aligned`) → extra **−5** to `adjusted_score` before the cap.
- **Never** output "STRONG BUY" or equivalent from technical analysis alone.
- Resistance levels within **0.3%** of each other must be **merged into a `confluence_resistance` zone**, preserving every contributing source. Do not drop a source.

## References

See `README.md` for an end-to-end example on GAS.
