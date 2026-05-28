# Layer 8 — Position Sizing Tier Specification (LOCKED 2026-05-28)

**Status**: spec finalized.
**Pipeline version target**: v3.0.

## 7 Sizing Tiers

| Tier | Mode | Conditions | Size NAV/mã |
|---|---|---|---|
| 1 | Core | Quality + deep value + Hard catalyst | 15-20% |
| 2 | Core | Quality + fair value + Medium catalyst | 12-15% |
| 3 | Swing | Catalyst Medium + valuation pass + technical confirm | 10-15% |
| 4 | Swing | Catalyst Medium + technical strong, valuation neutral | 8-12% |
| 5 | T+ | Sector BULLISH + flow positive + technical strict | 5-10% |
| 6 | Any | Yellow lái flag (existing or new entry) | 5-8% max |
| 7 | Any | **Red lái flag — SKIP new entry** | **0 (no entry)** |

Note Tier 7: Red lái means **no new position**. Existing positions handled by separate risk review (Layer 9), NOT entry-size calculation.

## Base size formula (Van Tharp adapted)

```
risk_per_share_pct = (entry - primary_stop) / entry × 100  # in %
risk_per_trade_pct = RISK_PER_TRADE_NAV / risk_per_share_pct × 100

base_size_pct = risk_per_trade_pct × conviction_modifier
```

Where:
- `RISK_PER_TRADE_NAV = 1.0` (% NAV at risk per trade, Van Tharp standard)
- `conviction_modifier` = per tier (see below)

Then apply caps in order:
1. ATR%-scaled multiplier (Layer 6 / v2.5 calibrated)
2. Liquidity floor (v2.5 calibrated; below floor → cap 5%)
3. Mode cap (Core 20%, Swing 15%, T+ 10%)
4. Sector cap (50% NAV per sector)
5. Total NAV deploy cap (regime-dependent: Bullish 90%, Neutral 70%, etc.)

## Conviction modifier (conservative initial)

| Tier | Modifier | Rationale |
|---|---|---|
| 1 (Core deep value + Hard catalyst) | **2.0×** | Highest conviction, max size |
| 2 (Core fair value + Medium catalyst) | **1.6×** | |
| 3 (Swing val + tech confirm) | **1.4×** | |
| 4 (Swing tech only) | **1.2×** | |
| 5 (T+ standard) | **1.0×** | Base |
| 6 (Yellow lái) | **0.5×** | Risk-reduced |
| 7 (Red lái) | **SKIP** (no entry) | No multiplier — no size |

Tier 1 modifier = 2.0× (not 2.5×) — conservative pending live calibration.

After 6 months live journal + backtest data → re-calibrate.

## Volatility scaling (reuse v2.5 calibrated)

```
atr_pct_current = ATR14 / close × 100
atr_pct_low = sector-specific (from configs/sectors/*.yaml)
atr_pct_high = sector-specific

if atr_pct_current ≤ atr_pct_low:
  atr_scale = 1.0
elif atr_pct_current ≥ atr_pct_high:
  atr_scale = atr_pct_low / atr_pct_current
else:
  # Linear interp
  atr_scale = 1.0 - (atr_pct_current - atr_pct_low) / (atr_pct_high - atr_pct_low) × (1 - atr_pct_low/atr_pct_high)
```

Output: `0 < atr_scale ≤ 1`. Multiply final size.

## Caps applied in order

```python
size = base_size × conviction_modifier × atr_scale

# 1. Liquidity floor
if adtv_20d_b_vnd < liquidity_floor:
    size = min(size, 5.0)  # max 5% NAV for illiquid

# 2. Mode cap
if mode == "core":
    size = min(size, 20.0)
elif mode == "swing":
    size = min(size, 15.0)
elif mode == "t_plus":
    size = min(size, 10.0)

# 3. Sector cap (per sector)
sector_current_allocation = sum(positions where sector matches)
sector_remaining = 50.0 - sector_current_allocation
size = min(size, sector_remaining)

# 4. Total NAV deploy cap (regime-dependent)
total_current = sum(all positions size)
nav_cap = regime_nav_cap_pct  # 90 Bullish, 70 Neutral, etc.
remaining_total = nav_cap - total_current
size = min(size, remaining_total)

# 5. Single ticker cap
existing_ticker_size = current_position_in_this_ticker
size = min(size, 25.0 - existing_ticker_size)  # 25% max per ticker regardless of mode mix

if size <= 0:
    REJECT entry (caps exceeded)
```

## Multi-position rules

### Sector concentration
- Max 50% NAV per sector across all modes.
- If sector at cap → new sector entry rejected.

### Single ticker cap
- Max 25% NAV per ticker (across Core + Swing + T+ combined).
- Prevents over-concentration even with mixed-mode rationalization.

### Cash buffer
- Always ≥ 10% NAV cash regardless of regime.

### Open position count
- Recommended max 8-12 positions across all modes.
- Soft cap (no hard rule), tracked for monitoring.

## Output schema

```yaml
ticker: VCB
mode: core
entry_calculation:
  tier: 1  # Core deep value + Hard catalyst
  base_size_pct_nav: 12.5  # before modifier
  conviction_modifier: 2.0
  atr_scale: 0.85
  size_after_modifier_atr: 21.25  # 12.5 × 2.0 × 0.85
  
  caps_applied:
    liquidity_pass: true  # ADTV > floor
    mode_cap: 20.0
    sector_remaining_cap: 30.0  # 50 - current 20%
    nav_remaining_cap: 35.0
    ticker_existing_cap: 25.0  # no existing position
  
  final_size_pct_nav: 20.0  # min of (size_after, mode_cap)
  final_size_vnd: 20_000_000  # for 100M NAV
  
  notional_per_100m_nav: 20_000_000
  
  reasoning: "Core tier 1, mode cap dominated"
```

## Re-balancing rules

- Positions reach +50% from entry → trim 25% (lock partial profit).
- Position drops to -50% from entry without thesis break → re-evaluate (not auto-add).
- Quarterly portfolio re-balance: bring sector allocations within targets.

## Integration với existing skills

- ATR scaling logic + liquidity floor: reuse from `stock-technical` v2.5/v2.6.
- Sector caps: new component.
- Conviction modifier per tier: new component.

## Re-calibration

- Conviction modifier values: review after 6 months live trade journal.
- Mode caps (20/15/10): review yearly.
- Sector cap 50%: review yearly.
- Single ticker cap 25%: review after concentration drawdown analysis.
- Cash buffer 10%: review per regime.
