# GAS — Data Quality Report

- Generated: `2026-05-18`
- Window: `2023-01-01` → `2026-05-18`
- adjusted_price_status: **confirmed**
- long_ma_confidence: **high**

## 1. Nguồn dữ liệu

| Source | Status | Rows | First | Last | Error |
|---|---|---|---|---|---|
| VCI | ok | 883 | 2022-10-26 | 2026-05-15 | — |
| TCBS | failed | 0 | — | — | Lớp Quote chỉ nhận giá trị tham số source là kbs, vci, msn, dnse, binance, fmp, fmarket. |

## 2. Corporate actions

- Events fetched: **50**
- Events with exright_date in window: **11**

| ex-right | event | action | value/share | exercise_ratio |
|---|---|---|---|---|
| 2023-04-28 | Đại hội Đồng Cổ đông | nan | missing_data | nan |
| 2023-08-29 | Trả cổ tức bằng tiền mặt | nan | 3,600.00 | 0.36 |
| 2023-09-22 | Phát hành cổ phiếu | nan | missing_data | 0.2 |
| 2024-04-26 | Đại hội Đồng Cổ đông | nan | missing_data | nan |
| 2024-09-13 | Trả cổ tức bằng tiền mặt | nan | 6,000.00 | 0.6 |
| 2024-09-13 | Phát hành cổ phiếu | nan | missing_data | 0.02 |
| 2025-04-28 | Đại hội Đồng Cổ đông | nan | missing_data | nan |
| 2025-08-28 | Trả cổ tức bằng tiền mặt | nan | 2,100.00 | 0.21 |
| 2025-08-28 | Phát hành cổ phiếu | nan | missing_data | 0.03 |
| 2025-08-28 | Phát hành cổ phiếu | nan | missing_data | 0.03 |
| 2026-04-17 | Đại hội Đồng Cổ đông | nan | missing_data | nan |

## 3. Chuỗi giá dùng phân tích kỹ thuật

- Source dùng: **VCI**
- Cột giá dùng tính MA: **`close`**
- Số phiên hợp lệ: **883**
- Ngày đầu / cuối: **2022-10-26** → **2026-05-15**

| Chỉ báo | Giá trị (mới nhất) |
|---|---|
| close (2026-05-15) | 89.40 |
| SMA20 | 78.36 |
| SMA50 | 84.34 |
| SMA100 | 90.26 |
| SMA200 | 76.42 |

## 4. Adjusted vs Raw price

- Status: **adjusted**  (confidence: high)

| ex-right | prev_close | ex_close | div/share | expected drop % | actual drop % | verdict |
|---|---|---|---|---|---|---|
| 2023-08-29 | 71.09 | 71.31 | 3600 | 5.06 | 0.31 | adjusted |
| 2024-09-13 | 71.61 | 69.94 | 6000 | 8.38 | -2.33 | adjusted |
| 2025-08-28 | 64.86 | 64.90 | 2100 | 3.24 | 0.06 | adjusted |
- note: price_scale = 1000.0 VND/unit (median_close=66.56)

## 5. Audit các gap giá lớn

- Ngưỡng gap: ±5.0% close-to-close
- Tổng gap: **36** — trong đó **36** không trùng ngày ex-rights.

| date | pct_change | near_ex_rights |
|---|---|---|
| 2022-11-28 | +6.97% | False |
| 2023-10-26 | -6.10% | False |
| 2025-04-03 | -6.86% | False |
| 2025-04-04 | -6.09% | False |
| 2025-04-08 | -6.99% | False |
| 2025-04-09 | -6.95% | False |
| 2025-04-10 | +6.88% | False |
| 2025-04-11 | +7.00% | False |
| 2025-06-16 | +6.99% | False |
| 2025-10-22 | +5.36% | False |
| 2025-12-29 | +6.52% | False |
| 2026-01-05 | +6.91% | False |
| 2026-01-06 | +6.98% | False |
| 2026-01-07 | +6.88% | False |
| 2026-01-09 | +6.00% | False |
| 2026-01-13 | +6.91% | False |
| 2026-01-19 | +6.01% | False |
| 2026-01-21 | +5.26% | False |
| 2026-01-26 | +6.94% | False |
| 2026-01-27 | +6.96% | False |
| 2026-02-10 | -6.91% | False |
| 2026-02-11 | -5.29% | False |
| 2026-02-23 | +6.99% | False |
| 2026-03-02 | +6.95% | False |
| 2026-03-03 | +6.93% | False |
| 2026-03-05 | -6.99% | False |
| 2026-03-06 | -6.35% | False |
| 2026-03-09 | -6.96% | False |
| 2026-03-10 | -7.00% | False |
| 2026-03-11 | +6.19% | False |
| 2026-03-13 | -6.99% | False |
| 2026-03-18 | +6.13% | False |
| 2026-03-20 | -6.92% | False |
| 2026-04-28 | -6.13% | False |
| 2026-05-13 | +6.93% | False |
| 2026-05-15 | +6.94% | False |

## 6. Kết luận

Dữ liệu đủ tin cậy cho phân tích kỹ thuật dài hạn (SMA100/SMA200). Chuỗi giá được xác nhận là **adjusted**, các MA dài phản ánh xu hướng thực.
