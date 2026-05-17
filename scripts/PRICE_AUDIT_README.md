# Price Data Quality Audit

Module: `scripts/fetch_price_audit.py`

Mục đích: kiểm tra chuỗi OHLCV của mã chứng khoán Việt Nam trả về từ `vnstock`
là **raw price** hay **adjusted price**, recompute SMA20/50/100/200 trên cột giá
phù hợp, và audit các gap giá bất thường để phát hiện dữ liệu chưa điều chỉnh.

## Cài đặt

```bash
pip install -r requirements.txt
```

## Chạy

```bash
# Mặc định: thử VCI rồi TCBS
python scripts/fetch_price_audit.py \
    --symbol GAS \
    --start 2023-01-01 \
    --end 2026-05-18

# Hoặc chỉ định riêng sources
python scripts/fetch_price_audit.py --symbol HPG --start 2023-01-01 --end 2026-05-18 --sources VCI
```

## Outputs

| File | Mô tả |
|---|---|
| `data/{SYMBOL}_price_VCI.csv` | OHLCV daily từ VCI (nếu fetch thành công) |
| `data/{SYMBOL}_price_TCBS.csv` | OHLCV daily từ TCBS (nếu thư viện hỗ trợ) |
| `data/{SYMBOL}_corporate_actions.csv` | Cổ tức / cổ phiếu thưởng / split (events VCI) |
| `reports/{SYMBOL}_data_quality_report.md` | Báo cáo Markdown tổng hợp |

## Các hàm chính

- `fetch_price(symbol, start, end, source)` — Quote-based OHLCV fetch.
- `fetch_corporate_actions(symbol)` — VCI `Company.events()`.
- `detect_adjusted_price(df, corporate_actions)` — so sánh actual drop vs
  expected drop quanh ex-rights date. Tolerance: ±1.5 pp = raw; ratio < 1/3
  = adjusted; còn lại = ambiguous.
- `calculate_indicators(df, price_col)` — SMA20/50/100/200 (min_periods = window).
- `audit_large_gaps(df, price_col)` — gap ≥ 5 % close-to-close, đánh dấu
  ngày trùng ex-rights window (±1 trading day).
- `generate_data_quality_report(...)` — viết Markdown.

## Quy ước báo cáo

- `adjusted_price_status = "confirmed"` + `long_ma_confidence = "high"` —
  detect_adjusted_price kết luận **adjusted** với confidence ≥ medium.
- `adjusted_price_status = "confirmed_raw"` + `long_ma_confidence = "medium"` —
  chuỗi là raw price; SMA dài có thể bị méo bởi cú drop ex-rights.
- `adjusted_price_status = "unknown"` + `long_ma_confidence = "medium_low"` —
  không đủ ex-rights events trong window hoặc kết luận mơ hồ.

## Hạn chế đã biết (vnstock 4.0.x)

- Nguồn `TCBS` không còn nằm trong `Quote.SUPPORTED_SOURCES` (`KBS, VCI, MSN, FMP`).
  Module vẫn thử và ghi `missing_data` trong report nếu fail — phù hợp với
  yêu cầu "thử cả VCI và TCBS nếu thư viện hỗ trợ".
- `Company.dividends()` đã bị bỏ trong VCI explorer; module dùng `events()`
  thay thế và lọc theo `value_per_share` + tên sự kiện chứa "tiền" để chọn
  cash dividend cho bước detect_adjusted_price.
