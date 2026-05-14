# Financial Analysis — Thresholds Reference

## Financial Score Formula (tổng tối đa 10 điểm)

| Tiêu chí | Max | Thresholds |
|----------|-----|-----------|
| Revenue CAGR 2Y | 1.5 | ≥15%=1.5, ≥5%=1.0, ≥0%=0.5, <0%=0 |
| Net margin (latest) | 1.5 | ≥15%=1.5, ≥8%=1.0, ≥3%=0.5, <3%=0 |
| ROIC (fallback ROE) | 1.5 | ≥15%=1.5, ≥10%=1.0, ≥5%=0.5, <5%=0 |
| OCF/NI — earnings quality | 1.5 | ≥0.9=1.5, ≥0.7=1.0, ≥0.5=0.5, <0.5=0 |
| FCF 4Q | 1.0 | Dương=1.0, âm+OCF dương (REALESTATE)=0.5, âm=0 |
| Interest coverage | 1.5 | ≥5×=1.5, ≥3×=1.0, ≥1.5×=0.5, <1.5×=0 |
| D/E ratio | 1.0 | ≤0.5=1.0, ≤1.0=0.75, ≤2.0=0.5, >2.0=0 |
| Current ratio | 1.0 | ≥2.0=1.0, ≥1.5=0.75, ≥1.0=0.5, <1.0=0 |

## Verdict Bands

| Điểm | Nhận định |
|------|-----------|
| 8.0 – 10.0 | Tài chính mạnh — nền tảng vững |
| 6.0 – 7.9 | Tài chính khá |
| 4.0 – 5.9 | Trung bình — có điểm yếu cần theo dõi |
| < 4.0 | Tài chính yếu — rủi ro cao |

## Industry Exceptions

### Ngân hàng (BANK)
- D/E criterion → thay bằng ROA: ≥1%=1.0, ≥0.7%=0.75, ≥0.5%=0.5, <0.5%=0
- Interest coverage: không áp dụng → 0 pts (ngân hàng kiếm từ spread lãi suất)
- Current ratio: không áp dụng → 0 pts
- Max thực tế cho BANK: ~7.5 điểm

### Bất động sản (REALESTATE)
- FCF âm OK nếu OCF dương (chu kỳ đầu tư dự án 2-5 năm) → 0.5 pts thay vì 0

### Năng lượng / Utilities (ENERGY)
- D/E thresholds nới lỏng: ≤2.0=1.0, ≤3.0=0.75, ≤4.0=0.5, >4.0=0

## Red Flags — Định nghĩa

| Flag | Severity | Điều kiện kích hoạt |
|------|----------|---------------------|
| earnings_quality | 🔴 High | NI +≥10% YoY nhưng OCF ≤-5% YoY |
| ar_rising | 🟡 Medium | AR/Revenue tăng liên tục (Q1 > Q4 × 1.15) |
| inventory_rising | 🟡 Medium | Inventory +>15% khi Revenue giảm >5% |
| interest_coverage_low | 🔴 High | Coverage <1.5× |
| interest_coverage_low | 🟡 Medium | Coverage 1.5–3× |
| debt_acceleration | 🟡 Medium | D/E tăng >30% trong 4Q |
| margin_compression | 🟡 Medium | Gross margin declining trend 6Q |
| fcf_negative_persistent | 🔴 High | FCF âm 3+/4Q (không phải REALESTATE) |
| negative_equity | 🔴 High | Vốn chủ sở hữu âm |

## Lý giải Chỉ số Chính

**ROIC = EBIT × (1−20%) / (Equity + NetDebt)**
- ROIC > WACC proxy (~10%) = tạo ra giá trị kinh tế
- ROIC < WACC = huỷ giá trị dù lợi nhuận dương
- Dùng ROE làm proxy khi không tính được ROIC (thiếu EBIT)

**OCF/NI — chất lượng lợi nhuận:**
- ≥ 0.9: lợi nhuận kế toán chuyển thành tiền tốt (ít accruals)
- 0.5–0.9: có accruals nhưng chấp nhận được
- < 0.5: lợi nhuận phụ thuộc nhiều vào accruals — cần xem xét kỹ

**Interest coverage = EBIT 4Q / Interest expense 4Q:**
- < 1.5×: nguy hiểm — EBIT không đủ trả lãi
- 1.5–3×: biên an toàn mỏng
- ≥ 5×: an toàn

**AR Days trend:**
- Rising = bán chịu nhiều hơn hoặc khó thu hồi → rủi ro dòng tiền
- Falling = thu tiền nhanh hơn → tích cực

## Missing Data Rules
- Metric None → 0 điểm cho criterion + ghi vào data_warnings
- Không suy đoán hay điền số liệu thiếu
- Nếu >3 criteria missing: ghi rõ "score chỉ dựa trên {N}/8 tiêu chí"
- Interest expense = 0 → assume no debt → interest_coverage criterion = 1.5 pts full
