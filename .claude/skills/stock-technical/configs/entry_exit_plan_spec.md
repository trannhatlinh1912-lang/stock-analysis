# Layer 9 — Entry/Exit Plan Specification (LOCKED 2026-05-28)

**Status**: FINAL layer. spec finalized.
**Pipeline version target**: v3.0.

## 9A — Entry Execution

Mỗi lệnh BẮT BUỘC pass đủ 8 layers prior:

1. Layer 1 Quality Gate
2. Layer 2 Market Regime allows mode
3. Layer 3 Sector Regime OK
4. Layer 4 Mode decided + permission matrix
5. Layer 5 Catalyst valid + tier matched to mode
6. Layer 6 Valuation + Technical setup pass per combination rule
7. Layer 7 Lái status acceptable for mode
8. Layer 8 Size calculated within caps

Failed any → SKIP entry.

### Trade journal mandatory (Layer 4 spec)

JSON `data/trade_journal/{TICKER}_{ENTRY_DATE}.json`. Required fields:
- mode, ticker, entry_date, entry_price, size
- catalyst (category, tier, sources, expiration)
- targets (primary, secondary)
- stops (all 6 layers — see 9B)
- kill_switch conditions
- external_sources (news, CTCK report links)
- emotional_state (entry, during, exit)
- lesson_learned (filled at exit)

## 9B — Multi-Layer Stop (6 stops, independent)

Any stop fires → immediate action.

### 1. Fundamental stop (all modes)
- NPL spike (banking) > threshold + NIM compression
- Earnings miss + guidance cut
- Debt rollover failure
- Audit qualifying opinion appears
- Restructuring announcement negative

### 2. Technical stop (mode-specific)

| Mode | Technical stop |
|---|---|
| Core | close < SMA200 sustained 2 weeks AND fundamental confirm worsening (KQKD xấu, sector regime → BEARISH) |
| Swing | close < swing_low_20 (key support) + 2 consecutive closes below + volume confirm (vol_ratio > 1.0 on breakdown day) |
| T+ | close < entry_candle_low OR close < SMA20 with vol_ratio > 1.2 on breakdown day |

### 3. Time stop (mode-specific)

| Mode | Review | Forced exit |
|---|---|---|
| Core | 12 months | 18 months if thesis not playing |
| Swing | 6 months | 9 months if catalyst expired |
| T+ | 3 weeks | 5 weeks if no follow-through |

### 4. Kill switch (immediate exit, all modes)
- Audit qualified opinion published
- HOSE/UPCoM warning list / control list / suspended trading
- CEO/Chairman/CFO khởi tố hoặc bị bắt
- Listed company manipulation order from UBCKNN

### 5. Lái escalate (separate from kill)
- During hold, lái symptoms increase (Layer 7 yellow → red transition)
- OR new red flag emerges from manual flag
- → Exit position regardless of P&L

### 6. Trailing stop (lock profit on winner)

```
For each open position with current_gain > +20%:
  high_since_entry = max(high prices since entry_date)
  trailing_stop = high_since_entry - 2 × ATR14
  
  If close < trailing_stop → trigger trim/exit per mode
```

Mode-specific trailing:
- Core: trail at high - 2 ATR; close < trail → trim 25%, watch
- Swing: trail at high - 1.5 ATR; close < trail → trim 50%
- T+: trail at high - 1 ATR; close < trail → exit full

## 9C — Exit Triggers Summary

| Trigger | Action |
|---|---|
| Target hit (primary) | Trim per 9D rule |
| Target hit (secondary) | Exit remainder |
| Fundamental stop | Exit full |
| Technical stop | Exit full |
| Time stop forced | Exit full unless extraordinary evidence |
| Kill switch | Exit immediate |
| Lái red flag escalate | Exit full |
| Trailing stop hit | Trim per 9B.6 rule |
| Mode demotion + cap exceeded | Trim to fit |

## 9D — Partial profit taking (mode-specific)

| Mode | Profit milestones | Trim each |
|---|---|---|
| **Core** | +20%, +50%, +100%, target | 25% each (4-milestone) |
| **Swing** | +half-to-target, target | 50% each (50/50 split) |
| **T+** | target | All or nothing (no partial, exit full at target OR stop) |

Rationale:
- Core: long horizon, gradual lock + ride runner. Final 25% can ride to multiples.
- Swing: medium horizon, simpler 50/50.
- T+: short horizon, no time for partial gradients. Binary outcome.

## 9E — Loss Management (mode-specific)

⚠️ **Quan trọng**: stop fire (9B) BÁN TRƯỚC. Mốc % loss dưới đây là REVIEW framework, không phải auto-exit.

| Mode | -15% | -20% | -25-30% | -50% |
|---|---|---|---|---|
| **Core** | Monitor | Review thesis | Hard review | Forced exit unless extraordinary |
| **Swing** | Monitor | Review | **Forced exit** | — (would have exited earlier) |
| **T+** | **Forced exit** | — | — | — |

Order of priority:
1. Stop fire → exit (highest priority)
2. % loss tier → review/exit per table
3. Manual decision

## 9F — Add-on rules

**No averaging down**. Add-on chỉ khi tất cả conditions:

1. Current position +20% from entry (winner status)
2. Original thesis intact (Layer 5 catalyst still valid)
3. NEW catalyst emerged (Layer 5 multi-catalyst stacked)
4. Sector regime upgraded to BULLISH (Layer 3)
5. Total ticker size after add-on still < 25% NAV cap
6. Total NAV deploy still within regime cap

Add-on size: max 50% of original position size, with new conviction tier applied.

## 9G — Re-entry rules

After exit:
- Same ticker re-entry: cool-down 30 days minimum (avoid revenge trading).
- Different mode: allowed immediately if criteria met.
- Pattern-match: re-entry decision should reference exit decision (avoid repeating mistake — journal review required).

## Output schema (per active position)

```yaml
position_id: VCB_20260528
ticker: VCB
mode: core
entry:
  date: 2026-05-28
  price_vnd: 65_000
  size_pct_nav: 15
  size_vnd: 15_000_000
  conviction_tier: 1
  catalyst_id: rate_cut_q3_2026

current:
  date: 2026-08-15
  price_vnd: 78_000  # +20% gain
  unrealized_pnl_vnd: 3_000_000
  unrealized_pnl_pct: 20.0
  
stops:
  fundamental: "monitor NPL Q2-2026 + NIM Q2-2026 results"
  technical: "close < SMA200 (current ~72,000) + 2-week sustain + KQKD confirm"
  time: "review at 2027-05-28 (12mo), force exit 2027-11-28 (18mo)"
  kill: "audit qualify, HOSE list, CEO legal"
  lai_status: "no symptoms active"
  trailing: 
    high_since_entry: 78_000
    trail_at: 73_500  # high - 2 × ATR14 (assume ATR=2250)

triggers_active:
  target_hit_primary: false (target 80k)
  target_hit_secondary: false (target 95k)
  fundamental_stop_fire: false
  technical_stop_fire: false
  time_stop_review_due: false
  kill_switch: false
  lai_escalate: false
  trailing_hit: false

actions_recommended:
  - first_trim_due_at_+20pct: "20% reached, trim 25% size now per 4-milestone Core rule"
    trim_size: 3_750_000 vnd  # 25% of 15M
    new_size_vnd: 11_250_000

journal_update_required: true
```

## Integration architecture summary

```
[1] Quality Gate           → drop / pass
[2] Market Regime          → mode permission + NAV cap
[3] Sector Regime          → sector modifier + skip bearish
[4] Trading Mode           → Core/Swing/T+ chosen
[5] Catalyst Taxonomy      → valid catalyst tier matched
[6] Valuation+Technical    → entry timing
[7] Lái Detection          → risk flag
[8] Position Sizing        → size %NAV
[9] Entry/Exit Plan        → execution + 6 stops + trim + add-on
```

## All 9 layer specs LOCKED

- `configs/quality_gate_spec.md` ✓
- `configs/market_regime_spec.md` ✓
- `configs/sector_regime_spec.md` ✓
- `configs/trading_mode_spec.md` ✓
- `configs/catalyst_taxonomy_spec.md` ✓
- `configs/valuation_technical_spec.md` ✓
- `configs/lai_detection_spec.md` ✓
- `configs/sizing_tier_spec.md` ✓
- `configs/entry_exit_plan_spec.md` ✓ (this file)

## Re-calibration cadence (global)

| Component | Frequency |
|---|---|
| Sector ROE/D/E thresholds | Quarterly after BCTC |
| Market regime baselines (vol, breadth) | Rolling auto + yearly review |
| Sector regime thresholds | Quarterly |
| Catalyst auto-detector thresholds | Quarterly against analyst surprise data |
| Valuation sector P/E means | Quarterly |
| Lái detection thresholds | After 6mo live false-positive analysis |
| Sizing modifiers | After 6mo live journal |
| Stop loss thresholds | Yearly |
