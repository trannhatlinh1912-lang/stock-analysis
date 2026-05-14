# Business Quality Score — Thresholds Reference

## Score Formula (tổng tối đa 10 điểm)

| Tiêu chí | Điểm tối đa | Thresholds |
|----------|-------------|------------|
| ROE avg 4Q | 1.5 | ≥20%=1.5, ≥15%=1.0, ≥10%=0.5, <10%=0 |
| Net margin (latest Q) | 1.5 | ≥15%=1.5, ≥8%=1.0, ≥3%=0.5, <3%=0 |
| Gross margin std 8Q | 2.0 | ≤2%=2.0, ≤4%=1.5, ≤6%=1.0, >6%=0.5 |
| D/E ratio (latest) | 2.0 | ≤0.5=2.0, ≤1.0=1.5, ≤2.0=1.0, >2.0=0 |
| FCF quality (FCF/NI) | 2.0 | FCF+, ratio≥0.8=2.0; ratio≥0.5=1.5; FCF+=1.0; FCF-=0 |
| Revenue CAGR 2Y | 1.0 | ≥10%=1.0, ≥0%=0.5, <0%=0 |

## Verdict Bands

| Điểm | Nhận định |
|------|-----------|
| 8.0 – 10.0 | Chất lượng cao — doanh nghiệp nền tảng mạnh |
| 6.0 – 7.9 | Chất lượng khá |
| 4.0 – 5.9 | Trung bình — có điểm yếu rõ |
| < 4.0 | Cần thận trọng |

## Industry Exceptions

### Ngân hàng (BANK)
D/E không phản ánh rủi ro thực vì leverage là đặc thù ngành. Thay thế:
- Bỏ criterion D/E (2.0 pts)
- Thêm ROA criterion (2.0 pts): ROA ≥1%=2.0, ≥0.5%=1.0, <0.5%=0

### Bất động sản (REALESTATE)
FCF thường âm do chu kỳ dự án dài (2-5 năm). Điều chỉnh:
- FCF criterion: nếu FCF âm nhưng operating CF dương → 0.5 pts (không phạt full)
- Gross margin std được weight cao hơn (moat proxy quan trọng hơn)

### Năng lượng / Utilities (ENERGY)
D/E cao là bình thường do đầu tư cơ sở hạ tầng. Điều chỉnh ngưỡng:
- ≤2.0=2.0, ≤3.0=1.5, ≤4.0=1.0, >4.0=0

## Lý giải các proxy

**gross_margin_std** là proxy cho moat vì:
- Biên lợi nhuận gộp ổn định = doanh nghiệp có pricing power
- Biến động cao = phụ thuộc commodity hoặc thiếu differentiation
- Thresholds: std ≤2% = rất ổn định, >6% = không có pricing power

**fcf_to_net_income** đo chất lượng lợi nhuận:
- FCF/NI > 0.8 = earnings chuyển thành tiền mặt tốt (ít accruals)
- FCF/NI < 0.5 = lợi nhuận kế toán nhưng không thu được tiền
- FCF âm với REALESTATE/BĐS không nhất thiết là xấu nếu đang đầu tư dự án

**roe_avg_4q** vs roe_trend:
- ROE cao + improving = moat đang mạnh lên
- ROE cao + declining = cảnh báo cạnh tranh tăng
- ROE thấp + improving = đang phục hồi (cần xem D/E)

## Missing Data Rules

- Metric `None` → 0 điểm cho criterion đó + ghi vào `data_warnings`
- Không suy đoán hay điền số liệu thiếu
- Nếu >3 criteria thiếu: ghi rõ "quality_score chỉ dựa trên {N}/6 tiêu chí"
