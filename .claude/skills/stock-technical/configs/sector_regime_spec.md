# Layer 3 — Sector Regime Specification (LOCKED 2026-05-28)

**Status**: spec finalized. Tiered design (Option C).
**Pipeline version target**: v3.0 (next-week build).

## Structure: Universal + Sector-specific tiers

```
[3 Universal Tier] — Auto-compute for ALL sectors
   - 3.1 Sector RS vs VN-Index (basket equal-weight, slope 20D)
   - 3.2 Sector breadth (% sector stocks > SMA50)
   - 3.3 Sector flow (cum foreign 20D, when accumulator data ≥20 days)

[3 Sector-specific Tier] — Auto-compute from statements + manual override
   - 3.4 Sector fundamental cycle proxy (per sector formula below)
```

If sector-specific data unavailable → flag `cycle_data_missing`, sector regime uses 3 universal dimensions only.

## 7 sectors covered

Banking, Oil & Gas, Real Estate, Steel, Consumer, Tech, Securities.

### Securities basket addition
Watchlist currently has only VND. Add SSI, HCM for basket size ≥3. Sector now n=3 minimum.

## Universal tier — auto compute

### 3.1 Sector RS (Relative Strength)

```
sector_basket(t) = mean(close(stock_i, t) for stock_i in sector_watchlist)
rs(t) = sector_basket(t) / VNI_close(t)
rs_slope_20d = (rs(t) / rs(t-20) - 1) × 100  # %
```

Thresholds (heuristic, pending empirical calibration):
- `leader`: rs_slope_20d > +2%
- `inline`: -2% ≤ rs_slope_20d ≤ +2%
- `laggard`: rs_slope_20d < -2%

### 3.2 Sector breadth

```
sector_breadth(t) = (% stocks in sector basket with close(t) > SMA50(t))
```

Thresholds:
- `strong`: ≥ 60%
- `neutral`: 40-59%
- `weak`: < 40%

⚠️ Caveat (per v2.4 empirical 2024-2026): aggregate breadth flipped sign forward returns. Sector-level breadth caveat retained pending sector-specific calibration.

### 3.3 Sector flow

When `data/foreign_history.csv` has ≥20 trading days for sector basket:
```
sector_foreign_cum_20d = Σ foreign_net(stock_i, last_20_days) for stock_i in basket
```
Labels: `positive` (>0), `neutral` (= 0 ±5% of avg daily volume), `negative` (<0 by ≥5%).

When insufficient data: flag `flow_data_insufficient`, contribute neutral with no score impact.

## Sector-specific tier — auto + manual

### Banking — NIM proxy + NPL direction

**NIM proxy (auto-compute quarterly)**:
```
NIM_proxy = net_interest_income / avg_earning_assets
  where earning_assets = total_assets - non_earning_items (cash, fixed_assets)
  using Finance.income_statement(period=quarter) + balance_sheet(quarter)
```
- `expanding`: latest quarter > 4-quarter mean by 0.1pp
- `stable`: within ±0.1pp
- `compressing`: latest quarter < 4-quarter mean by 0.1pp

**NPL ratio (manual override)**:
- User updates `configs/banking_npl.yaml` quarterly after CTCK reports.
- Format: `{ticker: {npl_pct: X, npl_ratio_growth_qoq: Y, source: "CTCK_VCBS_Q1-2026"}}`
- Auto-compute proxy fallback: provision_expense / loan_book if structured.

Bullish cycle: NIM expanding AND NPL declining.
Bearish cycle: NIM compressing AND NPL rising.

### Oil & Gas — Brent + crack spread

Reuse Layer 2B Macro Overlay output.
- Auto: Brent ret_5d/20d, USD/VND (yfinance).
- Crack spread (Brent - WTI as proxy): yfinance both.
- Bullish cycle: Brent ret_20d > +5% AND crack widening AND USD/VND stable/strengthening.
- Bearish: Brent ret_20d < -10% OR crack collapsing.

### Real Estate — OCF trend + presale (manual)

**OCF trend (auto)**:
- 4-quarter rolling sum OCF compared to prior 4-quarter sum.
- `improving`: latest > prior +10%, `stable` ±10%, `declining` -10%.

**Presale velocity (manual override)**:
- User updates `configs/re_presale.yaml` quarterly with CTCK report data.
- Format: `{ticker: {presale_units_qoq_pct, backlog_months, source}}`.

Bullish: OCF improving AND (presale recovering OR rate cut announced).
Bearish: OCF declining + presale stalling + rate hike.

### Steel — iron ore + HRC proxy + inventory turnover

**Inventory turnover (auto)**:
```
inv_turnover = revenue / avg_inventory (quarterly)
```
- `efficient`: > 4 turns/year, `stable` 2-4, `weak` < 2.

**Iron ore proxy (auto from yfinance)**:
- TIO=F (Tahoma iron ore) or HRC=F (steel futures).
- Bullish: HRC rising + USD/VND stable + China stimulus catalyst (manual flag).

### Consumer — Revenue YoY quarterly (SSSG proxy)

**Auto-compute**:
```
sssg_proxy = revenue(Q_recent) / revenue(Q_yoy) - 1  (in %)
```
- `accelerating`: ≥ +10% YoY 2 consecutive quarters
- `stable`: ±10% YoY
- `declining`: < -5% YoY

### Tech — Revenue growth + ROIC trend

**Auto**:
- Revenue 3y CAGR (already computed in Layer 1 fetch_fundamentals).
- ROIC quarterly = NI / (equity + LT debt) trend.

Bullish: revenue growth > 15% AND ROIC trending up.

### Securities — Margin debt + market liquidity

Reuse Layer 2A pillars (margin_debt + liquidity).
- Bullish: margin_debt safe AND liquidity rising AND new accounts growth (manual flag).

## Sector regime states

Score = sum of 4 dimension contributions (RS + breadth + flow + cycle):
- Each dimension: +1 / 0 / -1.
- If cycle missing: 0 contribution (no penalty other than confidence reduction).

| Score | Sector Regime |
|---|---|
| ≥ +3 | BULLISH |
| +1 to +2 | NEUTRAL_TO_BULLISH |
| 0 | NEUTRAL |
| -1 to -2 | NEUTRAL_TO_BEARISH |
| ≤ -3 | BEARISH |

Special: if sector ret_20d < -15% AND no positive dimension → CRISIS.

## Output schema (per sector)

```yaml
sector_name: oil_gas
regime:
  state: BULLISH | NEUTRAL_TO_BULLISH | NEUTRAL | NEUTRAL_TO_BEARISH | BEARISH | CRISIS
  score: -4 to +4
  confidence_pct: 0-100
dimensions:
  rs:
    basket_members: [BSR, GAS, PLX, PVS, PVD]
    rs_slope_20d_pct: X
    label: leader | inline | laggard
  breadth:
    pct_above_sma50: Y
    label: strong | neutral | weak
    caveat: "..."
  flow:
    cum_foreign_20d_vnd: Z (or null if insufficient)
    label: positive | neutral | negative | data_insufficient
  cycle:
    proxy_metric: NIM_proxy | brent_ret_20d | OCF_trend | etc
    value: V
    label: expanding | stable | compressing
    data_source: auto | manual_override
trading_mode_modifiers:
  swing_size_modifier: +0.0 to +5% NAV (bullish sector → larger swing)
  t_plus_allowed: bool
  catalyst_required: bool  # true for bearish sector
```

## Trading mode modifiers per sector regime

Layer 2A determines BASE trading mode permissions. Layer 3 sector regime ADJUSTS sizing:

| Sector regime | Swing size modifier | T+ allowed in sector | Notes |
|---|---|---|---|
| BULLISH | +3% NAV/lệnh (max swing 15% → 18%) | ✓ | Prefer sector |
| NEUTRAL_TO_BULLISH | +1% | ✓ | Standard |
| NEUTRAL | 0 | ✓ | Standard |
| NEUTRAL_TO_BEARISH | -2% | conditional | Need catalyst |
| BEARISH | -5% OR skip | ✗ | Deep value only |
| CRISIS | skip | ✗ | Sector cash |

## Auto-compute scripts needed (next-week build)

1. `scripts/sector_regime.py` — orchestrator, output JSON per sector daily.
2. `scripts/banking_nim_proxy.py` — quarterly auto-compute from statements.
3. `scripts/re_ocf_trend.py` — quarterly OCF rolling.
4. `scripts/steel_inv_turnover.py` — quarterly inventory turnover.
5. `scripts/consumer_sssg_proxy.py` — quarterly revenue YoY.
6. Manual yaml templates: `configs/banking_npl.yaml`, `configs/re_presale.yaml`, etc.

## Securities basket expansion

Currently: VND only. Add to fundamentals fetch:
- SSI (SSI Securities — largest broker)
- HCM (HSC — top 3 broker)

Re-run `fetch_fundamentals.py --tickers SSI HCM` after Layer 3 lock.

## Re-calibration cadence

- RS slope thresholds: yearly review.
- Sector cycle thresholds: quarterly after BCTC season.
- Sector breadth interpretation: yearly (or after regime change).
- Manual override yaml: every CTCK report cycle.
