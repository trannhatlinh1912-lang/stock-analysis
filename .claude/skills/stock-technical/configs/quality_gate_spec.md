# Layer 1 — Quality Gate Specification (LOCKED 2026-05-28)

**Status**: Layer 1 spec finalized after empirical verification on 32-ticker pool.
**Pipeline version target**: v3.0 (next-week build).
**Author**: framework session 2026-05-28.

## Master architecture

```
INPUT: ticker
    ↓
[1A] HARD RED FLAGS   → any triggered = IMMEDIATE DROP (verdict=HARD_FAIL)
[1B] WARNING FLAGS    → report-only, severity-tagged, manual review trigger
[1C] TRADABLE GATE    → market cap + ADTV + listing duration (mode-specific)
[1D] SECTOR-SPECIFIC  → sector ROE threshold + sector D/E ceiling
    ↓
OUTPUT:
  hard_flags: list
  warning_flags: list[severity]
  tradable_core: bool
  tradable_t_plus: bool
  data_completeness_pct: 0-100
  manual_review_required: bool
  verdict: PASS | WARNING | HARD_FAIL
```

Score 0-100 REJECTED in favor of multi-flag pass/fail per dimension. Rationale:
single score hides red flags that may be more important than aggregate quality.

## 1A — HARD RED FLAGS (immediate drop)

| Flag ID | Trigger | Source | Notes |
|---|---|---|---|
| `consecutive_loss_3y` | Net income < 0 in 3 consecutive recent years | income_statement isa20 | |
| `roe_3y_deeply_negative` | ROE 3y avg < -5% | computed | Catches deep value traps (TLH/SMC) |
| `negative_equity` | Latest equity < 0 | balance_sheet bsa78 | |
| `accumulated_loss_exceeds_capital` | retained_earnings < 0 AND \|RE\| > share_capital | balance_sheet bsa90/bsa80 | Delisting precursor |
| `banking_real_dilution_severe` | (sector=banking) sc_3y>250% AND eps_3y<0 AND bvps_3y≤0 | computed | Banking-specific (bonus shares ≠ dilution) |
| `securities_real_dilution_severe` | (sector=securities) sc_3y>200% AND eps_3y<0 AND roe_deteriorating | computed | |
| `severe_dilution` | (non-financial) sc_3y>100% AND (eps_decline OR bvps_decline OR revenue_decline) | computed | True dilution requires per-share decay |

## 1B — WARNING FLAGS (report-only, severity-tagged)

| Flag ID | Severity | Trigger |
|---|---|---|
| `roe_3y_negative` | high | -5% < ROE 3y avg < 0% (turnaround thesis required) |
| `ocf_negative_2of3y` | high | OCF < 0 in 2 of last 3 years |
| `ocf_negative_1y` | medium | OCF < 0 in latest year only |
| `debt_extreme` | high | (non-bank) D/E > 5 |
| `debt_elevated` | medium | (non-bank) D/E > 3 |
| `below_sector_roe_threshold` | medium / high (if >5pp below) | ROE below sector P25 (see 1D) |
| `above_sector_de_ceiling` | medium / high (if >1.5× ceiling) | D/E above sector ceiling (see 1D) |
| `banking_dilution_risk` | medium | (sector=banking) sc_3y>150% AND any per-share metric declines |
| `securities_dilution_risk` | medium | (sector=securities) sc_3y>100% |
| `dilution_with_decay` | high | (non-financial) sc_3y>50% AND eps/bvps decline |
| `dilution_moderate` | medium | (non-financial) sc_3y>100% but per-share OK, OR sc_3y>30% with decay |

## 1C — TRADABLE GATE (mode-specific)

VN par value standard = 10,000 VND. Market cap = latest_close × (share_capital / par).
ADTV = mean(close × volume) over last 20 trading days.

| Mode | Market cap min | ADTV 20d min | Listed years min |
|---|---|---|---|
| Core (long-term) | 500B VND | 1B VND/day | 2 |
| T+ (tactical) | 2000B VND | 5B VND/day | 2 |

## 1D — SECTOR-SPECIFIC THRESHOLDS (calibrated 2026-05-28 from 32-ticker pool)

Thresholds = sector P25 (or sector judgement when sample small).

### ROE thresholds

| Sector | Metric | Min | Empirical P25 / Median / P75 |
|---|---|---|---|
| Banking | roe_pct_3y_avg | 14% | 17.5 / 17.7 / 19.8 |
| Oil & Gas | roe_pct_5y_avg | 8% | 8.3 / 9.9 / 14.2 |
| Real Estate | roe_pct_5y_avg | 7% | 2.5 / 6.0 / 7.8 (NVL+VIC outliers down) |
| Steel | roe_pct_5y_avg | 8% | -4.5 / 9.3 / 9.8 (TLH/SMC outliers down) |
| Consumer | roe_pct_3y_avg | 10% | 10.1 / 11.8 / 18.3 |
| Tech | roe_pct_3y_avg | 10% | 9.0 / 11.6 / 12.3 |
| Securities | roe_pct_3y_avg | 10% | (n=1) |

### D/E ceilings (non-bank/securities)

| Sector | D/E max | Rationale |
|---|---|---|
| Oil & Gas | 2.0 | Low-debt sector empirically (P75=1.4) |
| Real Estate | 3.0 | Leveraged but VIC outlier 6.4 |
| Steel | 1.5 | P75=1.25, SMC outlier 3.4 |
| Consumer | 2.5 | FRT outlier 3.6 |
| Tech | 2.0 | P75=1.5 |
| Securities | 2.0 | n=1 |

Banking and Securities exempt from D/E generic limit (different capital structure).

## Sector dilution policy (Layer 1A + 1B detail)

### Banking
- Exempt from generic dilution flag (banks issue bonus shares routinely for CAR).
- Warning IF sc_3y_growth > 150% AND (EPS deteriorates OR BVPS deteriorates OR ROE deteriorating).
- Hard fail IF sc_3y_growth > 250% AND EPS growth 3y < 0 AND BVPS growth 3y ≤ 0.

### Securities
- Stricter than banking (cash SI more common):
- Warning IF sc_3y_growth > 100%.
- Hard fail IF sc_3y_growth > 200% AND EPS 3y < 0 AND ROE deteriorating.

### Non-financial
- Hard fail IF sc_3y_growth > 100% AND (EPS decline OR BVPS decline OR revenue decline).
- Warning_high IF sc_3y_growth > 50% AND per-share decline.
- Warning_medium IF sc_3y_growth > 100% without per-share decline (still notable).

## Test cases (verified 2026-05-28)

| Ticker | Expected | Result | OK? |
|---|---|---|---|
| VCB, MBB, ACB, CTG, TCB | Banking pass (bonus shares not flagged) | 0 dilution flag | ✓ |
| TLH | Drop (deep ROE negative) | HARD `roe_3y_deeply_negative` | ✓ |
| SMC | Drop (deep ROE negative) | HARD `roe_3y_deeply_negative` | ✓ |
| NVL | Quality concerns | 3 high warnings (roe_neg + debt + below_sector) | ✓ |
| VIC | Debt extreme | Warnings: dilution + debt_extreme + below_sector_roe | ✓ |
| BSR | Oil cycle low (warning, not drop) | 1 warning: dilution_with_decay | ✓ |
| PVD | Below sector ROE | Warning: below_sector_roe (2.67% vs 8% min) | ✓ |

## Watchlist final (after Layer 1 applied to 32-ticker test pool)

### CORE — 12 mã (sector cap 2, top quality)
Banking: MBB, VCB. Oil&Gas: GAS, PLX. RE: VHM, NLG. Steel: HPG, HSG.
Consumer: VNM, MWG. Tech: FPT. Securities: VND.

### SWING tactical — 12 mã (3 sub-categories)
- **A. Cyclical Opportunity**: BSR, PVD, NKG, SAB, KDH
- **B. Turnaround Candidate**: REE, PC1, CMG
- **C. Structural Risk** (catalyst-required): VIC, DXG, FRT, GEX

### DROP — 3 mã
TLH (HARD), SMC (HARD), NVL (3 high warnings).

## Data sources verified (vnstock 4.0.2 community edition)

| Endpoint | Available | Notes |
|---|---|---|
| `Finance.income_statement(year)` | ✓ 8y limit | NI, EPS, revenue |
| `Finance.balance_sheet(year)` | ✓ 8y limit | Equity, debt, share_capital, retained_earnings |
| `Finance.cash_flow(year)` | ✓ 8y limit | OCF |
| `Company.events()` | ✓ | Corporate actions, dividends |
| `Company.shareholders/officers/news/subsidiaries` | ✓ | Governance |
| `Quote.history()` | ✓ | Price + volume for liquidity |
| `Finance.ratio()` | ✗ broken | Compute ratios manually |
| `Trading.insider_deal/prop_trade/foreign_trade` | ✗ NotImplementedError | No historical |

## PENDING for future calibration

- NPL ratio (banking specific) — not in raw balance_sheet; require CTCK quarterly report manual fetch.
- CAR (banking specific) — same.
- Presale backlog (RE specific) — manual fetch from CTCK reports.
- Audit opinion structured — currently keyword-detect from news, not structured field.
- Insider deal historical — vnstock doesn't expose; require alternative source.

## Re-calibration cadence

- Sector ROE/D/E thresholds: re-run `fetch_fundamentals.py` + verify quarterly.
- Watchlist refresh: quarterly after BCTC season.
- Layer 1 spec review: yearly.
