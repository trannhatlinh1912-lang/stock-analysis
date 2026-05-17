# GAS — Technical Decision

- as_of: **2026-05-15**
- generated_at: `2026-05-18 03:00:12`
- close: **89.40**

## 1. Technical state

- **BREAKOUT_WITH_EXHAUSTION_RISK**
- trend_status: bullish_partial
- momentum_status: rsi_neutral_64.7, macd_hist_positive
- volume_status: spike_2.42x
- money_flow_status: cmf20_-0.020, mfi_neutral_67.9, obv_slope_up
- volatility_status: atr_pct_4.14_high, bb_above_upper

## 2. Confidence score

- raw_score: **72**
- adjusted_score: **67**  (triple_risk_penalty_applied: True)
- final_score: **67 / 100**  (exhaustion_cap_applied: True)

## 3. Entry strategy

- Không mua đuổi tỷ trọng lớn. Ưu tiên chờ retest hoặc chỉ mua thăm dò nếu vượt kháng cự gần với volume duy trì.

## 4. Entry zones

- **retest_aggressive**: 85.70 – 87.55 (Pullback nông: close − 0.5 ATR đến close − 1.0 ATR.)
- **retest_standard**: 84.34 – 85.70 (Pullback chuẩn: max(SMA50, close − 1.5 ATR) đến close − 1.0 ATR.)
- **breakout_confirmation_zone**: 90.26 (SMA100 — mốc cần đóng cửa trên để xác nhận trend trung hạn.)

## 5. Support / Resistance

**Resistance (trên close):**
- **confluence_resistance**: 90.00 – 90.26  (sources: psychological_90 + sma100)
- psychological_95: 95.00
- psychological_100: 100.00
- **confluence_resistance**: 131.50 – 131.50  (sources: swing_high_50 + high_52w)

**Support (dưới close):**
- sma50: 84.34
- atr_stop_1_5x: 83.85
- sma20: 78.36
- sma200: 76.42
- swing_low_20: 73.00

## 6. Stop loss

- **primary_stop**: 84.34 (max(SMA50, ATR_1.5x))
- **hard_stop**: 82.00 (ATR_2.0x)
- **structural_stop**: 73.00 (swing_low_20, 18.34% từ close, informational_only)
  - Cách close > 10% — chỉ tham khảo cấu trúc, không dùng làm stop chính.
- atr_stop_1_5x: 83.85
- atr_stop_2_0x: 82.00
- sma50_stop: 84.34
- swing_low_20_stop: 73.00

## 7. Upgrade / downgrade conditions

**Upgrade khi:**
- Close trên SMA100 tối thiểu 2-3 phiên.
- Volume duy trì >= MA20.
- CMF20 chuyển dương.
- MACD histogram tiếp tục mở rộng.
- MA alignment cải thiện (close > SMA20 > SMA50 > SMA100 > SMA200).

**Downgrade khi:**
- Breakout thất bại nếu close dưới ATR stop 1.5x.
- Close quay lại dưới SMA50.
- Volume tăng nhưng giá giảm mạnh.
- MACD histogram co lại dưới 0.
- CMF20 tiếp tục âm.

## 8. Key risks

- breakout_exhaustion_risk: giá tăng mạnh vượt Bollinger Upper với volume spike và Stoch quá nóng; rủi ro pullback/throwback 1-5 phiên cao.
- near_sma100_resistance: giá đang sát dưới SMA100, cần vượt và giữ trên SMA100 để xác nhận trend trung hạn.
- trend_not_fully_aligned: MA chưa xếp hàng tăng hoàn chỉnh, xu hướng trung hạn chưa xác nhận.

## 9. Final view

Breakout có dấu hiệu quá mua — tránh mua đuổi, chờ retest. Điểm tin cậy: 67/100. Rủi ro nổi bật: breakout_exhaustion_risk: giá tăng mạnh vượt Bollinger Upper với volume spike và Stoch quá nóng; rủi ro pullback/throwback 1-5 phiên cao.

> Báo cáo thuần kỹ thuật. Không phải khuyến nghị mua/bán. Dùng kèm phân tích nền tảng và bối cảnh thị trường.
