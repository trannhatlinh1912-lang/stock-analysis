# Technical Analysis Thresholds

Lazy-load only when interpreting ambiguous signals. Do not read this file for every run.

## RSI(14) Bands

| Range | Label | Interpretation |
|-------|-------|---------------|
| < 30 | Oversold | Strong buy signal zone; look for reversal confirmation |
| 30–45 | Weak | Bearish bias; downtrend continuation likely |
| 45–55 | Neutral | No clear momentum; wait for breakout |
| 55–70 | Bullish | Uptrend momentum; continuation bias |
| > 70 | Overbought | Caution zone; potential pullback; not a sell signal alone |

RSI divergence: Price makes new high but RSI lower high → bearish divergence (ASSUMPTION).

## MACD(12,26,9) Interpretation

| Condition | Signal |
|-----------|--------|
| Histogram > 0 and rising | Bullish momentum strengthening |
| Histogram > 0 and falling | Bullish but weakening |
| Histogram < 0 and falling | Bearish momentum strengthening |
| Histogram < 0 and rising | Bearish but weakening |
| MACD crosses above Signal | Bullish crossover |
| MACD crosses below Signal | Bearish crossover |
| MACD above zero line | Uptrend regime |
| MACD below zero line | Downtrend regime |

## Stochastic(14,3) Bands

| Range | Label |
|-------|-------|
| K < 20 | Oversold |
| K 20–80 | Neutral |
| K > 80 | Overbought |

Bullish signal: K crosses above D in oversold zone.
Bearish signal: K crosses below D in overbought zone.

## Moving Averages

| Condition | Signal |
|-----------|--------|
| Price > MA20 > MA50 > MA200 | Strong uptrend |
| MA20 crosses above MA50 | Golden Cross (bullish) |
| MA20 crosses below MA50 | Death Cross (bearish) |
| Price > MA200 | Long-term uptrend |
| Price < MA200 | Long-term downtrend |
| Price between MA50 and MA200 | Transition zone — NEUTRAL |

## Volume Ratio (Today / MA20)

| Ratio | Label | Interpretation |
|-------|-------|---------------|
| < 0.7 | Low | Weak conviction |
| 0.7–1.3 | Normal | Baseline |
| 1.3–2.0 | High | Conviction move |
| > 2.0 | Spike | Climactic move — potential reversal |

Volume confirms trend when: rising price + vol ratio > 1.3 OR falling price + vol ratio > 1.3.
Volume diverges when: rising price + vol ratio < 0.7 (weak breakout) OR falling price + low vol (shakeout).

## OBV (On-Balance Volume)

- OBV rising while price rising → institutional accumulation (confirm uptrend)
- OBV falling while price rising → distribution (bearish divergence)
- OBV flat while price moves → weak conviction in either direction

## Money Flow — Foreign Investor (Khối ngoại)

| 10-Day Net | Label | Impact |
|------------|-------|--------|
| > +20B VND | Strong Inflow | Significant positive catalyst |
| +5B to +20B VND | Mild Inflow | Moderate support |
| -5B to +5B VND | Neutral | No directional signal |
| -5B to -20B VND | Mild Outflow | Moderate headwind |
| < -20B VND | Strong Outflow | Significant selling pressure |

Note: Foreign flow is a short-term signal only. It can reverse quickly.
Low foreign room remaining (< 5%) may limit further foreign buying.

## Bollinger Bands (20,2)

| BB %B Value | Interpretation |
|-------------|---------------|
| > 0.8 | Price near upper band — overbought in BB context |
| 0.4–0.6 | Price near midband — neutral |
| < 0.2 | Price near lower band — oversold in BB context |

BB squeeze (bands narrowing) → volatility expansion imminent; direction not predictable.

## ATR(14) — Average True Range

- ATR measures volatility, not direction.
- Use ATR to set stop-loss: S1 = current price - 1.5× ATR (common convention).
- Use ATR to set R/R: target R1 should be ≥ 2× ATR above entry.

## Timing Zone Logic

| Zone | Criteria |
|------|----------|
| 🟢 ACCUMULATION | ≥3 of 4 signals BULLISH; price near or above S1 |
| 🟡 WATCH | Mixed signals (2 vs 2, or 3 vs 1 but key signals conflict) |
| 🔴 DISTRIBUTION | ≥3 of 4 signals BEARISH; price near or below R1 |

Signal mapping:
- Trend: BULLISH if price > MA50 > MA200; BEARISH if price < MA50 < MA200; else NEUTRAL
- Momentum: BULLISH if RSI 45-70 + MACD hist > 0; BEARISH if RSI < 40 or hist < 0 strongly; else NEUTRAL
- Volume: CONFIRM (treated as BULLISH) if vol_ratio > 1.3 and aligned with price; DIVERGE (BEARISH) if contradiction; else NEUTRAL
- Money Flow: INFLOW (BULLISH) if foreign_net_10d > +5B; OUTFLOW (BEARISH) if < -5B; else NEUTRAL

## Support & Resistance Identification

Priority (highest to lowest):
1. 52-week high/low (strongest psychological levels)
2. Recent swing highs/lows (last 60 sessions, top 2 peaks/troughs)
3. Bollinger Band upper/lower (dynamic S/R)
4. Pivot point: (H + L + C) / 3 of most recent session

Label as [FACT] when derived from actual price data. Do NOT fabricate levels.
