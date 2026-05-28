# Layer 4 — Trading Mode Specification (LOCKED 2026-05-28)

**Status**: spec finalized.
**Pipeline version target**: v3.0.

## 3 modes

| Mode | Horizon | Size/lệnh | Total NAV cap | Driver |
|---|---|---|---|---|
| **Core holding** | 6-12+ tháng | 15-20% | 50-60% | Quality + value + thesis intact |
| **Swing trung hạn** | 2-6 tháng | 10-15% | 30-40% | Catalyst + sector regime + value/trend |
| **T+ tactical** | vài phiên-vài tuần | 5-10% | 20-30% | Sector sóng + technical setup + flow |

## Mode × Market Regime permission matrix

| Market Regime | Core | Swing | T+ | Total NAV cap |
|---|---|---|---|---|
| BULLISH | ✓ full size | ✓ full size | ✓ full size | 90% |
| NEUTRAL | ✓ | ✓ | ✓ **conditional** (see below) | 70% |
| NEUTRAL_TO_BEARISH | ✓ selective | ✓ selective | ✗ | 55% |
| BEARISH | Deep value + catalyst only | ✗ | ✗ | 40% |
| CRISIS | Cash + opportunistic quality only | ✗ | ✗ | 30% |

### NEUTRAL → T+ conditions (all required)
- Sector = BULLISH OR NEUTRAL_TO_BULLISH
- Ticker = RS leader (rs_slope_20d > +2%)
- Volume confirm: vol_ratio ≥ 1.5× MA20 on entry day
- Total T+ cap reduced to **50% of standard** (vd 10% NAV/lệnh → 5%, total 30% → 15%)

## Entry criteria per mode (all required)

### Core entry
1. Layer 1: PASS clean (0 hard flag) hoặc 1 warning low-severity
2. Layer 2 Market Regime: BULLISH or NEUTRAL
3. Layer 3 Sector Regime: NOT BEARISH/CRISIS
4. Layer 5 Catalyst: VALID (Layer 5 taxonomy)
5. Layer 6 Valuation: discount vs sector mean (P/B-ROE banking < mean-0.5σ, P/E norm < threshold, etc.) OR technical pullback to long-term support
6. Layer 7 Lái: No red flag
7. Tradable: market_cap > 500B AND ADTV_20d > 1B

### Swing entry
1. Layer 1: PASS clean OR 1-2 warnings (cyclical opportunity OK)
2. Layer 2: Allows swing mode (BULLISH/NEUTRAL/NEUTRAL_TO_BEARISH)
3. Layer 3: NEUTRAL_TO_BULLISH or BULLISH (skip if BEARISH/CRISIS)
4. Layer 5 Catalyst: VALID + actionable timeline (≤6 months)
5. Layer 6: Valuation discount OR technical setup (1 of 2 sufficient)
6. Layer 7: No red flag
7. Tradable: market_cap > 500B AND ADTV_20d > 1B

### T+ entry (strictest)
1. Layer 1: PASS clean (no hard flag)
2. Layer 2: BULLISH OR NEUTRAL (NEUTRAL needs conditions above)
3. Layer 3: BULLISH OR NEUTRAL_TO_BULLISH ONLY
4. Layer 5 Catalyst: optional, but flow POSITIVE required (foreign or prop)
5. Layer 6 Technical: REQUIRED breakout from base ≥5 weeks OR pullback to MA20/50 in uptrend
6. Layer 6 Volume: ≥1.5× MA20 on entry day
7. Layer 7: No yellow OR red flag (strictest tier)
8. Tradable T+: market_cap > 2000B AND ADTV_20d > 5B

## Mode locking rules

**Mode decided BEFORE entry**. Written to journal. Cannot be changed mid-trade.

### No promotion
- T+ losing → cắt theo stop, NOT average down, NOT re-evaluate as Swing/Core.
- Swing thesis broken → cắt, NOT re-frame as Core.

### Demotion allowed
- Core: Layer 1 warning xuất hiện mới → downgrade to "Swing-watch" (giảm size to 10-15%, monitor more frequently).
- Swing → T+: NOT allowed (different criteria).

## Mode allocation budget (track daily)

```yaml
nav_total: 100_000_000  # 100M VND example
nav_allocated:
  core: 50_000_000   # currently 50%
  swing: 25_000_000  # currently 25%
  t_plus: 5_000_000  # currently 5%
  cash: 20_000_000   # currently 20%
caps:
  core_max: 60_000_000      # 60%
  swing_max: 40_000_000     # 40%
  t_plus_max: 30_000_000    # 30% (standard) — auto-scaled by regime
  total_deployed_max: 90_000_000  # depends on regime
```

Output `data/portfolio_state.json` daily. Refuse entry if cap exceeded.

## Trade journal (MANDATORY per entry)

JSON file `data/trade_journal/{TICKER}_{ENTRY_DATE}.json`:

```yaml
ticker: VCB
mode: core | swing | t_plus
entry_date: 2026-05-28
entry_price_vnd: 65000
size_pct_nav: 15
size_nav_vnd: 15000000

# Layer 5: Catalyst
catalyst:
  category: policy_change | earnings | cycle | corporate_action | upgrade | flow
  description: "Fed cut rates → VCB NIM expansion expected"
  timeline_months: 3
  evidence_links: ["https://...", "internal_note.md"]

# Targets
targets:
  primary_vnd: 80000
  primary_rationale: "intrinsic + 20% buffer"
  secondary_vnd: 95000
  secondary_rationale: "P/B-ROE upper band"

# Stops (3 layers)
stops:
  fundamental_stop: "NPL ratio > 2.5% AND NIM not expanding next 2 quarters"
  technical_stop: "close < SMA200 sustained 2 weeks + breakdown volume"
  time_stop: "12 months if thesis not playing out → re-evaluate"

# Kill-switch (immediate exit)
kill_switch: "audit qualified opinion OR CEO legal case OR HOSE warning list"

# Behavioral / external (recommended)
external_sources:
  - news_link: "https://cafef.vn/..."
  - ctck_report: "VCBS Banking Outlook Q2-2026"
  - chart_screenshot: "data/screenshots/VCB_2026-05-28.png"

emotional_state_entry: "calm | excited | reluctant | FOMO"
emotional_state_during: []  # update during hold
emotional_state_exit: "..."  # at exit

lesson_learned: ""  # filled at exit
```

## Exit triggers (matches Layer 9 spec — preview)

Bất kỳ trigger nào fire = exit:
1. **Target hit**: primary_vnd reached
2. **Fundamental stop**: thesis sai per stops.fundamental_stop
3. **Technical stop**: per stops.technical_stop
4. **Time stop**: per stops.time_stop  
5. **Kill switch**: immediate (audit/legal/HOSE)
6. **Mode demotion + cap exceeded**: forced trim

## Cross-mode portfolio rules

- No more than 50% NAV in 1 sector (sector concentration cap).
- No more than 25% NAV in 1 ticker even with mixed modes (cap regardless of mode mix).
- Cash buffer ≥ 10% NAV always.

## Reporting (daily)

Script `scripts/portfolio_report.py` outputs:
- Current allocation per mode + cap utilization
- Active positions list with thesis status
- Pending re-evaluation list (warnings appeared, time stop near)
- New signals from screen meeting mode criteria

## Re-calibration

- Mode size ranges: review yearly based on portfolio performance.
- Permission matrix: review after each market regime cycle complete.
