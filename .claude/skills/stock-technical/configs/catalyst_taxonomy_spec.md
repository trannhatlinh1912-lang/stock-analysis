# Layer 5 — Catalyst Taxonomy Specification (LOCKED 2026-05-28)

**Status**: spec finalized.
**Pipeline version target**: v3.0.

## 8 Valid Catalyst Categories

| # | Category | Sub-types | Detection |
|---|---|---|---|
| 5.1 | **Policy / Regulation** | Rate cut, sector reform, tax policy, FOL relax | News keyword + manual flag |
| 5.2 | **Earnings / Results** | EPS beat, guidance upgrade, margin expansion confirmed | Income statement quarterly compare |
| 5.3 | **Industry Cycle** | Commodity recovery, demand inflection, capex cycle turn | Macro overlay + sector cycle proxies |
| 5.4 | **Commodity / Input** | Brent drop (refining margin), iron ore drop (steel), USD strength | yfinance commodities |
| 5.5 | **Corporate Action** | Buyback, SOE divestment, M&A, spin-off, FOL increase | Company.events() + news |
| 5.6 | **Upgrade / Recognition** | FTSE/MSCI upgrade, MSCI rebalance, foreign room relax | News + manual flag |
| 5.7 | **Flow / Positioning** | Foreign net_buy 20d turning positive, prop active, retail inflows | Foreign accumulator |
| 5.8 | **Management / Operational Improvement** | New CEO turnaround, restructuring milestone, cost reduction confirmed | News + earnings + manual |

## Invalid (NOT catalyst — common traps)

| Anti-pattern | Reason |
|---|---|
| "Cổ phiếu tốt nên sẽ tăng" | Quality alone — already in Layer 1 |
| "Đã giảm nhiều rồi" | Mean reversion bias ≠ catalyst |
| "Rất nhiều người nói tốt" | Sentiment ≠ catalyst |
| "Vẽ sóng Elliott xong" | Chart pattern ≠ catalyst |
| "P/E thấp hơn lịch sử" | Valuation alone ≠ catalyst (need re-rate reason) |
| "Oversold quá rồi" | Technical extreme ≠ catalyst |

## Catalyst Strength Tiers

| Tier | Definition | Hold horizon |
|---|---|---|
| **Hard** | Documented confirmed event (policy released, earnings reported, M&A signed) | Core 6-12+ months |
| **Medium** | Cycle turn signal + 1-2 confirming data points | Swing 2-6 months |
| **Soft** | Flow / positioning only OR single soft data point | T+ tactical weeks |
| **Speculative** | Rumor / unconfirmed news / single anonymous source | SKIP or smallest T+ size only |

### Multi-catalyst stacked rule

- Khi nhiều catalyst confirm cùng direction → tier có thể nâng lên **1 bậc** (max).
- BẮT BUỘC có ≥1 catalyst với source xác thực (Hard or Medium).
- Vd: Cycle (Medium) + Flow (Soft) + Earnings (Hard) → final Hard (already top).
- Vd: Flow (Soft) + Sentiment (none) + "people say bullish" (none) → vẫn Soft (only 1 valid).
- Vd: Cycle Medium + Commodity Medium → up to Hard (need verified Brent data + sector confirm).
- Stack capped: never beyond Hard regardless of count.

## Timeline Buckets

| Bucket | Window | Best mode |
|---|---|---|
| Immediate | < 1 month | T+ tactical (pre-event positioning) |
| Near-term | 1-3 months | Swing (ride into event) |
| Medium-term | 3-12 months | Core entry (accumulate before event) |
| Long-term | 12+ months | Core deep value (cycle positioning) |

## Auto-detect implementation (catalyst_detector.py)

| Category | Auto? | Method |
|---|---|---|
| 5.2 Earnings | ✓ AUTO | Quarterly income_statement: revenue YoY > 10% + NI YoY > 15% + margin expansion → "earnings_beat" flag |
| 5.3 Industry Cycle | ✓ AUTO | Sector basket ROE quarter trend + commodity correlation |
| 5.5 Corporate Action | ✓ AUTO | Company.events() filter for buyback/dividend special/M&A keywords |
| 5.7 Flow / Positioning | ✓ AUTO | Foreign accumulator cum_20d direction + slope |
| 5.1 Policy | ✗ MANUAL | News keyword scan + user confirmation in `configs/catalyst_manual.yaml` |
| 5.4 Commodity | ✓ AUTO (partial) | Reuse macro_overlay (Brent, USD/VND, DXY ret_5d/20d) |
| 5.6 Upgrade | ✗ MANUAL | News + user input |
| 5.8 Management | ✗ MANUAL | News (CEO change, restructure announcements) + user input |

## Catalyst conflict resolution

- Sector catalyst bullish + ticker-specific catalyst bearish → ticker-specific dominates (exit/skip).
- Multiple catalysts opposite directions → calculate net (positive count − negative count), tier based on dominant side.
- Ambiguous (net = 0) → no catalyst valid, SKIP entry.

## Catalyst expiration (mode-specific)

| Mode | Expiration rule |
|---|---|
| **T+** | Strict — if catalyst expires without play, exit immediately |
| **Swing** | Soft — review at expiration, exit unless thesis still has valid evidence |
| **Core** | Flexible — 12-month review; allow extension with new evidence |

Each catalyst entry must specify:
- `expected_play_date`: estimated date catalyst confirms/disproves
- `expiration_date`: hard deadline
- `extension_allowed`: bool (T+ = false, Swing = conditional, Core = true)

## Output schema (catalyst snapshot per ticker)

```yaml
ticker: VCB
as_of: 2026-05-28
catalysts:
  - id: rate_cut_q3_2026
    category: 5.1_policy
    tier: hard
    direction: bullish
    description: "SBV signal rate cut Q3 2026"
    detected_by: manual
    sources: 
      - "https://sbv.gov.vn/..."
      - "VCBS Banking Outlook 2026 p23"
    detected_at: 2026-05-15
    expected_play_date: 2026-08-15
    expiration_date: 2026-12-31
    extension_allowed: true
  - id: nim_expand_observed_q1_2026
    category: 5.2_earnings
    tier: medium
    direction: bullish
    description: "NIM expanded +0.3pp QoQ Q1 2026"
    detected_by: auto_catalyst_detector
    sources: ["finance.income_statement Q1 2026 vs Q4 2025"]
    detected_at: 2026-04-30
    expected_play_date: 2026-08-01
    expiration_date: 2027-04-30
    extension_allowed: true

aggregate:
  net_bullish_catalysts: 2
  net_bearish_catalysts: 0
  effective_tier: hard  # after multi-catalyst stack rule
  trade_mode_recommended: core
  catalyst_valid: true
```

## Manual catalyst input format

`configs/catalyst_manual.yaml`:
```yaml
last_updated: 2026-05-28
catalysts_by_ticker:
  VCB:
    - id: rate_cut_q3_2026
      category: 5.1_policy
      tier: hard
      direction: bullish
      description: "SBV signal rate cut Q3 2026"
      sources: ["url1", "url2"]
      expected_play_date: 2026-08-15
      expiration_date: 2026-12-31
  GAS:
    - id: opec_meeting_jun2026
      category: 5.3_cycle
      tier: medium
      direction: bullish
      description: "OPEC+ likely extend production cut → Brent up"
      sources: ["VCBS Energy Note Q2 2026"]
      expected_play_date: 2026-07-01
      expiration_date: 2026-12-31
```

## Re-calibration

- Auto-detector thresholds (EPS YoY > 10% for "beat"): review quarterly against actual analyst surprise data.
- Manual catalyst list: update weekly after CTCK reports + news scan.
- Expiration rules: review yearly.
