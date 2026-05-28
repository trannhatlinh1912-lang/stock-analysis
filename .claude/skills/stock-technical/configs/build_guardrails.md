# Build Guardrails — Framework v3 (LOCKED 2026-05-28)

**Purpose**: 4 ràng buộc bắt buộc khi build v3.0. Tránh drift khi implement.

**Áp dụng**: mọi script trong `scripts/` + orchestrator `screen_watchlist.py`.

---

## Guardrail 1 — 3-state output (chống overfitting)

### Rule

Output orchestrator phải là một trong 3 trạng thái, KHÔNG chỉ PASS/SKIP:

| State | Định nghĩa | Action |
|---|---|---|
| **PASS** | 9/9 layer pass theo combination rule | Eligible entry, tính size theo L8 |
| **WATCH** | 7-8/9 layer pass, miss 1-2 non-killer layer | Add vào watchlist, monitor catalyst/technical confirm |
| **SKIP** | Fail ≥1 killer layer HOẶC fail ≥3 layer | Loại khỏi entry candidate |

### Killer layers (auto SKIP nếu fail)

| Layer | Killer condition |
|---|---|
| L1 Quality Gate | Hard flag fire (consecutive_loss_3y, negative_equity, severe_dilution, accumulated_loss_exceeds_capital, roe_3y_deeply_negative, kill switch) |
| L2 Market Regime | State = CRISIS |
| L4 Trading Mode | Mode requested forbidden bởi permission matrix |
| L7 Lái Detection | Red flag cho mode tương ứng |
| L9 Kill Switch | Bất kỳ kill switch nào active |

### Non-killer layers (miss → WATCH, không SKIP)

- L5 Catalyst tier mismatch (vd: muốn Core nhưng chỉ có Soft catalyst) → WATCH chờ catalyst nâng tier
- L6 Technical chưa confirm (valuation OK, technical pending breakout) → WATCH chờ technical setup
- L3 Sector NEUTRAL_TO_BEARISH (không phải BEARISH) → WATCH chờ sector regime cải thiện
- L8 Sector cap full → WATCH chờ rebalance

### Code requirement

```python
# scripts/screen_watchlist.py
def classify_ticker(layer_results: dict) -> str:
    if any_killer_failed(layer_results):
        return "SKIP"
    pass_count = sum(1 for layer in layer_results.values() if layer.passed)
    if pass_count >= 9:
        return "PASS"
    if pass_count >= 7:
        return "WATCH"
    return "SKIP"
```

Unit test bắt buộc:
- `test_all_pass → PASS`
- `test_1_killer_fail → SKIP`
- `test_2_non_killer_miss → WATCH`
- `test_3_layer_fail_no_killer → SKIP`

---

## Guardrail 2 — Manual data freshness + degradation policy

### Rule

CẤM fallback heuristic khi manual file stale. Phải tag `data_quality` + degrade theo bảng.

### Staleness threshold + degradation

| File | Stale threshold | Effect khi stale |
|---|---|---|
| `configs/catalyst_manual.yaml` | > 14 days | Catalyst tier downgrade 1 bậc + flag `manual_stale` |
| `configs/banking_npl.yaml` | > 1 quý (90 days) | `data_quality=low`, banking ticker cấm Tier 1 sizing (max Tier 2) |
| `configs/re_presale.yaml` | > 1 quý | `data_quality=low`, RE ticker cấm Tier 1 sizing |
| `configs/re_rnav_manual.yaml` | > 1 quý | RE valuation primary fail → fallback secondary OR WATCH |
| `configs/margin_debt.yaml` | > 30 days | L2 Market Regime NAV cap về Neutral max (70%) bất kể regime actual |
| `configs/lai_manual_flags.yaml` | > 30 days | Manual symptom 3, 5 ignored, auto-only assessment |
| `configs/lai_overrides.yaml` | Per-entry `override_until` date | Override expired → revert to auto detection |
| `configs/sector_valuation_overrides.yaml` | > 1 quý | Use basket-derived 5y mean với caveat sample_size_warning |

### Code requirement

```python
# Mỗi loader script
def load_manual(path, max_age_days):
    if not path.exists():
        return {"data": None, "status": "missing", "data_quality": "low"}
    age = (today - file_mtime(path)).days
    if age > max_age_days:
        return {"data": parsed, "status": "stale", "age_days": age, "data_quality": "low"}
    return {"data": parsed, "status": "fresh", "data_quality": "high"}
```

### Output yaml requirement (mọi layer)

```yaml
data_completeness_pct: 85
manual_inputs_status:
  catalyst_manual: {status: fresh, age_days: 3}
  margin_debt: {status: stale, age_days: 45, effect: "nav_cap_capped_neutral"}
  banking_npl: {status: missing, effect: "tier1_blocked_banking"}
```

### Exit code policy

- Manual file missing + cần thiết cho layer killer → exit code 2 `pending_data`, KHÔNG infer.
- Manual file stale + non-killer → exit code 0 nhưng flag in output.

---

## Guardrail 3 — Layer 7 Lái = risk flag, không phải kết luận

### Rule

L7 output luôn là **CẢNH BÁO + telemetry**, không phải verdict.

### Telemetry requirement (build phase)

Mỗi lần L7 fire flag (yellow/red), log vào `data/lai_signal_history.jsonl`:

```jsonl
{"ticker":"BSR","date":"2026-05-28","symptoms_active":[1,4],"mode":"swing","verdict":"yellow","price_at_signal":15500,"forward_5d_pct":null,"forward_20d_pct":null,"news_within_5d":[]}
```

Daily job append `forward_5d_pct` + `forward_20d_pct` khi đủ data.

### False positive analysis (sau 6 tháng)

Tính:
- `fp_rate = signals_with_positive_forward_20d / total_signals`
- Per-symptom: `fp_rate_by_symptom[1]`, `fp_rate_by_symptom[4]`, etc.

Re-calibrate threshold nếu `fp_rate > 50%` cho symptom đó.

### Build constraint

- KHÔNG lock threshold số (3× MA20, 5%, etc.) tại commit đầu. Configurable trong `configs/lai_thresholds.yaml`.
- Mode mapping (Core 3/4, Swing 2/3, T+ 1/2) configurable trong `configs/lai_mode_mapping.yaml`.
- Re-calibrate cadence: 6 tháng live data minimum.

### Wording in output

```yaml
lai_check:
  warning_level: yellow  # NOT "verdict" or "conclusion"
  recommendation: "monitor + size cut 50%"  # NOT "do not buy"
  user_override_allowed: true
  override_path: configs/lai_overrides.yaml
```

---

## Guardrail 4 — Cap ưu tiên conviction (enforcement)

### Rule

Conviction modifier (1.0× → 2.0×) chỉ scale UP base size. CẤM bypass cap. Cap chain bắt buộc enforce theo đúng L8 spec order.

### Cap chain (immutable order)

```python
# scripts/portfolio_state.py + sizing_calculator
def calculate_final_size(tier, base_pct, modifiers, caps, state):
    # Step 1: apply conviction modifier (UP only)
    size = base_pct * tier_modifier[tier]  # 0.5× - 2.0×
    
    # Step 2: ATR scale (always reduce or keep)
    size = size * atr_scale  # 0 < scale ≤ 1
    
    # Step 3: caps in order — each is hard floor
    size = min(size, liquidity_cap(state))      # 5% if illiquid
    size = min(size, mode_cap[mode])             # Core 20, Swing 15, T+ 10
    size = min(size, sector_remaining(state))    # 50% sector cap
    size = min(size, nav_remaining(state))       # regime-dependent
    size = min(size, ticker_remaining(state))    # 25% per ticker
    
    if size <= 0:
        return {"action": "REJECT", "reason": "all_caps_exhausted"}
    return {"action": "ENTRY", "size_pct_nav": size}
```

### Forbidden patterns

- ❌ `if tier == 1: size = max(size, mode_cap)` — tier 1 không bypass cap
- ❌ `size = base * modifier  # skip ATR scale` — ATR luôn enforce
- ❌ `if conviction == 'high': sector_cap = 60` — cap immutable theo regime, không theo tier
- ❌ `if user_override: bypass_cap = True` — cấm override cap qua config

### Unit test bắt buộc

| Test | Setup | Expected |
|---|---|---|
| `test_tier1_red_lai` | Tier 1 quality + Red lái flag | REJECT (no entry) |
| `test_tier1_sector_full` | Tier 1 + sector at 50% cap | REJECT (sector_remaining=0) |
| `test_tier1_atr_extreme` | Tier 1 + ATR 8% (extreme) | size ≤ mode_cap × atr_scale, NOT 2.0× base |
| `test_tier1_illiquid` | Tier 1 + ADTV < floor | size ≤ 5% (liquidity floor) |
| `test_tier1_nav_full` | Tier 1 + NAV deploy 90% (Bullish cap) | REJECT (nav_remaining=0) |
| `test_modifier_no_bypass` | All caps low, modifier 2.0× | size = min(cap), NOT base × 2 |

### Reporting

Mỗi entry decision log:
```yaml
size_calculation_trace:
  base_pct: 12.5
  after_conviction: 25.0   # 12.5 × 2.0
  after_atr: 21.25         # × 0.85
  after_liquidity: 21.25
  after_mode_cap: 20.0     # capped from 21.25 → 20 (Core)
  after_sector_cap: 20.0
  after_nav_cap: 20.0
  after_ticker_cap: 20.0
  final: 20.0
  binding_constraint: mode_cap
```

`binding_constraint` field bắt buộc — biết cap nào active để debug.

---

## Enforcement summary

| Guardrail | Enforcement point | File |
|---|---|---|
| 1. 3-state output | `screen_watchlist.py` classifier | scripts/screen_watchlist.py |
| 2. Manual data freshness | Loader wrapper mọi script | scripts/utils/manual_loader.py |
| 3. L7 telemetry + risk-flag wording | `lai_detector.py` output schema | scripts/lai_detector.py |
| 4. Cap chain immutable | `sizing_calculator` core | scripts/portfolio_state.py |

## Audit checklist (post-build)

- [ ] Grep `bypass_cap` trong code → must return 0 results
- [ ] Grep `tier == 1.*max\(` → no tier-based cap removal
- [ ] Grep `if.*stale.*infer` → no heuristic fallback for stale data
- [ ] L7 output yaml: contains `warning_level` not `verdict` field
- [ ] Orchestrator returns one of {PASS, WATCH, SKIP} only
- [ ] Each output yaml has `data_completeness_pct` + `manual_inputs_status`

## Re-calibration (post 6 months live)

| Guardrail | Review |
|---|---|
| 1. Killer layer list | Adjust nếu PASS rate < 5% hoặc > 50% — overfitting indicator |
| 2. Stale threshold | Adjust per file dựa user maintenance cadence thực tế |
| 3. Lái threshold (symptom-level) | Re-calibrate per `fp_rate_by_symptom[]` |
| 4. Mode caps + sector cap | Yearly review per L8 spec |
