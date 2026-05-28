# Layer 7 — Lái Detection Specification (LOCKED 2026-05-28)

**Status**: spec finalized. VN-specific risk warning layer.
**Pipeline version target**: v3.0.

## Purpose

**TRÁNH mua mã bị lái**, không trade theo. Mục tiêu: risk filter, không generate signal.

Cảnh báo, không kết luận. False positive expected (news lag, breakout thực).

## 6 Symptoms

| # | Symptom | Window | Auto/Manual | Logic |
|---|---|---|---|---|
| 1 | Volume spike + no news | **5 day** rolling | AUTO | vol_ratio > 3× MA20 AND \|ret_1d\| > 5% AND news_count_5d = 0 (or news keyword non-substantive) |
| 2 | Insider deal heavy | **90 day** | AUTO (snapshot diff) | Officers/shareholders bán >5% holdings cumulative |
| 3 | Prop trade active | n/a | **MANUAL** | User flags from CafeF/SSI broker report (no vnstock data) |
| 4 | Foreign-retail divergence | **5 day** | AUTO | Foreign net_sell cumulative 5d AND price up >5% same 5d |
| 5 | ATC manipulation | n/a | **MANUAL** | User flags from intraday observation (no daily-data proxy) |
| 6 | Pump pattern | **10 day** | AUTO | 5 consecutive +5%/day in last 10 days AND news_count low |

### Variable windows rationale
- Vol spike: short reaction time (5 day catches recent unusual activity)
- Insider deal: long horizon (90 day = quarter, structural pattern)
- Foreign-retail divergence: short (5 day = transient divergence often manipulation)
- Pump pattern: medium (10 day catches multi-session run-up)

## Mode-specific thresholds

Lái signal impact scales with mode urgency. Core (long-term) less sensitive; T+ (tactical) very sensitive.

| Mode | Yellow trigger | Red trigger | Action |
|---|---|---|---|
| **Core** | 3 symptoms | 4+ symptoms | Yellow: monitor; Red: skip new entry, hold existing if thesis intact |
| **Swing** | 2 symptoms | 3+ symptoms | Yellow: size cut 50%; Red: skip |
| **T+** | 1 symptom | 2+ symptoms | Yellow: size cut 50%; Red: skip immediately |

Rationale:
- Core: long-term thesis doesn't depend on short-term lái. Tolerance higher.
- Swing: 2-6 month horizon means lái can hurt in entry window. Standard sensitivity.
- T+: lái = primary risk for tactical trades. Strict.

## Symptom detection details

### Symptom 1 — Volume spike + no news

```
vol_ratio_today = volume_today / MA20(volume)
ret_1d = |price_pct_change_today|
news_count_5d = count(Company.news() where public_date in [today-5d, today]
                     AND not in non_substantive_keywords)
non_substantive_keywords = ["thông báo định kỳ", "cập nhật giao dịch", "thay đổi nhỏ"]
TRIGGER: vol_ratio_today > 3.0 AND ret_1d > 5.0% AND news_count_5d == 0
```

### Symptom 2 — Insider deal heavy

```
shareholders_now = Company.shareholders() snapshot today
shareholders_prior = stored snapshot from 90 days ago (cached daily)
officers_now = Company.officers()
officers_prior = stored 90-day cache

For each officer/major_shareholder:
  delta_pct = (holdings_now - holdings_prior) / holdings_prior * 100
  if delta_pct < -5%: flag as insider_seller
  
TRIGGER: sum(|delta_pct| for insider_sellers) > 5% AND ≥1 insider with C-level/major holder
```

Requires daily snapshot cache → script `scripts/insider_snapshot_daily.py`.

### Symptom 4 — Foreign-retail divergence

```
foreign_net_5d = sum(foreign_buy - foreign_sell, last 5 days) from accumulator
price_change_5d = (close_today / close_5d_ago - 1) * 100

TRIGGER: foreign_net_5d < 0 (net sell) AND price_change_5d > 5% (price up)
```

Requires Layer 2 foreign accumulator daily ≥5 days.

### Symptom 6 — Pump pattern

```
last_10_days_returns = [ret_1d for each of last 10 days]
positive_5pct_days = count(d in last_10_days_returns where d > 5%)
news_count_10d = count(substantive news in last 10 days)

TRIGGER: positive_5pct_days >= 5 AND news_count_10d <= 1
```

### Symptom 3 (manual) — Prop trade active

User reads CafeF/SSI broker report, flags in `configs/lai_manual_flags.yaml`:
```yaml
ticker: ABC
lai_flags_manual:
  - symptom_id: 3_prop_trade_active
    flagged_at: 2026-05-28
    expires_at: 2026-06-28  # 30 days default
    evidence: "SSI broker report Q2 2026 showing prop sequence buy"
    severity: high
```

### Symptom 5 (manual) — ATC manipulation

Same format, user observes intraday on dashboard/iBoard, flags manually.

## Output schema

```yaml
ticker: VHM
as_of: 2026-05-28
lai_check:
  symptoms_active:
    - id: 4_foreign_retail_divergence
      window: 5_day
      evidence: "foreign net -125M, price +8% same 5d"
      severity: high
      detected_by: auto
    - id: 6_pump_pattern
      window: 10_day
      evidence: "6/10 days with +5% return, 1 substantive news"
      severity: medium
      detected_by: auto
  
  symptoms_count: 2
  
  mode_assessment:
    core: yellow  # 2 symptoms < 3 → yellow only
    swing: yellow  # 2 == yellow trigger
    t_plus: red   # ≥2 = red
  
  recommended_action:
    core: monitor_closely
    swing: size_cut_50pct_or_skip
    t_plus: skip_immediately
  
  data_completeness_pct: 100  # all auto-checks ran
  manual_flags_pending_user_input: 0
```

## Implementation scripts (next-week build)

1. `scripts/lai_detector.py` — orchestrator, auto-runs symptom 1, 2, 4, 6.
2. `scripts/insider_snapshot_daily.py` — daily snapshot cache for symptom 2.
3. `configs/lai_manual_flags.yaml` — user manual input for symptom 3, 5.

## False positive handling

- Lái flag = CẢNH BÁO, không kết luận.
- User có quyền override với evidence (vd: breakout thực sự + công ty announce M&A → vol spike + price up + early-stage news = false positive).
- Override input vào `configs/lai_overrides.yaml`:
  ```yaml
  ticker: ABC
  override_until: 2026-06-15
  reason: "M&A announced 2026-05-28, vol spike legitimate, news lag delayed publication"
  user_signature: confirmed
  ```

## Limitations documented

| Symptom | Limitation |
|---|---|
| Prop trade | vnstock không expose. Hoàn toàn dựa manual flag from broker report. |
| ATC manipulation | Cần intraday data (daily aggregate không phát hiện được). Manual observation only. |
| News keyword "substantive" | Subjective. Initial list provided, user expand. |
| Insider snapshot diff | Requires 90-day cache build-up. First 90 days = inconclusive. |

## Re-calibration

- Vol spike threshold 3× MA20 + 5%: review after live tracking 6 months.
- Mode-specific tier mapping: review yearly.
- Insider deal % threshold: review after empirical false positive rate.
- Manual flag yaml: weekly user maintenance.
