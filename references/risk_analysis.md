# Risk Analysis Reference — Vietnamese Stocks

## 1. Scoring Scale

Tất cả risk categories dùng scale 0–3:

| Score | Label | Ý nghĩa |
|-------|-------|---------|
| 0 | LOW | Không có dấu hiệu đáng lo ngại |
| 1 | LOW-MEDIUM | Cần chú ý nhưng chưa đáng lo |
| 2 | MEDIUM | Rủi ro rõ ràng, cần theo dõi chủ động |
| 3 | HIGH/CRITICAL | Rủi ro nghiêm trọng, có thể phá vỡ thesis |

## 2. Debt Risk Thresholds

### Non-bank companies
| Chỉ số | LOW | MEDIUM | HIGH |
|--------|-----|--------|------|
| D/E ratio | < 1.5× | 1.5–3.0× | > 3.0× |
| Interest coverage (EBIT/Interest) | > 5× | 2–5× | < 2× |
| Net debt / EBITDA | < 2× | 2–4× | > 4× |

### Banks (D/E không áp dụng)
| Chỉ số | LOW | MEDIUM | HIGH |
|--------|-----|--------|------|
| D/E ratio | < 8× | 8–15× | > 15× |
| CAR (Capital Adequacy Ratio) | > 12% | 9–12% | < 9% |
| NPL ratio | < 1.5% | 1.5–3% | > 3% |

### Real Estate
| Chỉ số | LOW | MEDIUM | HIGH |
|--------|-----|--------|------|
| D/E ratio | < 1× | 1–2.5× | > 2.5× |
| Net debt / Equity | < 0.5× | 0.5–1.5× | > 1.5× |

## 3. Dilution Risk Thresholds

| Tốc độ pha loãng (shares outstanding YoY) | Severity |
|-------------------------------------------|----------|
| < 2% | LOW |
| 2–5% | LOW-MEDIUM |
| 5–15% | MEDIUM |
| > 15% | HIGH |

**Dilution events cần flag ngay:**
- Phát hành riêng lẻ (private placement) > 10% số cổ phiếu hiện hành
- ESOP > 5% số cổ phiếu hiện hành
- Trái phiếu chuyển đổi còn trong thời hạn chuyển đổi
- Warrant chưa được thực hiện

## 4. Ownership Concentration (HHI Top 5)

| HHI Top 5 | Mức tập trung |
|-----------|---------------|
| < 1000 | Phân tán — thấp |
| 1000–1500 | Trung bình |
| 1500–2500 | Trung bình-cao |
| > 2500 | Rất cao — rủi ro minority shareholders |

**Single shareholder thresholds:**
- ≥ 50%: Kiểm soát tuyệt đối — HIGH risk for minority
- 35–50%: Quyền kiểm soát thực tế (veto mọi quyết định)
- 20–35%: Ảnh hưởng lớn (có thể chặn quyết định cần 75%)
- < 20%: Thiểu số — cần xem toàn bộ cấu trúc

## 5. Audit Risk Red Flags

### Ý kiến kiểm toán (theo mức độ nghiêm trọng)
1. **Chấp nhận toàn phần** — không có vấn đề (LOW)
2. **Ngoại trừ (Qualified opinion)** — có vấn đề cụ thể, định lượng được (MEDIUM-HIGH)
3. **Từ chối (Disclaimer)** — không đủ bằng chứng để kết luận (HIGH)
4. **Trái chiều (Adverse)** — BCTC không trung thực (CRITICAL)
5. **Going concern** — nghi ngờ khả năng hoạt động liên tục (CRITICAL)

### Tín hiệu thay kiểm toán đáng ngờ
- Thay Big 4 → công ty nhỏ hơn (downgrade)
- Thay kiểm toán viên sau ý kiến ngoại trừ
- Thay kiểm toán viên liên tiếp 2+ lần trong 3 năm

## 6. Legal / Regulatory Risk Signals

### VN-specific risk events (cần flag ngay)
- **Cảnh báo hủy niêm yết (delisting warning)**: lỗ 3 năm liên tiếp, vốn chủ âm, vi phạm công bố thông tin nghiêm trọng
- **Tạm dừng giao dịch (trading halt)**: điều tra, vi phạm nghiêm trọng
- **Yêu cầu giải trình từ UBCKNN/HoSE/HNX**: vi phạm nhỏ nhưng cần chú ý
- **Điều tra nội bộ / điều tra hình sự**: rủi ro cao nhất
- **Margin call cổ đông lớn**: bán tháo áp lực → giá sụt
- **Cầm cố cổ phiếu ban lãnh đạo > 50% holdings**: rủi ro margin call

### Nguồn kiểm tra (thủ công, không có API)
- HoSE: hsx.vn/Listingboard/Companies
- HNX: hnx.vn/vi-VN/cong-ty-niem-yet.html
- UBCKNN: ssc.gov.vn/ubck/faces/oracle/webcenter/portalapp

## 7. Governance Risk Signals

### Giao dịch bên liên quan (Related Party Transactions — RPT)
**HIGH risk patterns:**
- Bán tài sản cho công ty liên quan với giá dưới thị trường
- Cho vay công ty liên quan với lãi suất ưu đãi, không có bảo đảm
- Mua tài sản từ công ty liên quan với giá trên thị trường
- Hợp đồng dịch vụ với công ty liên quan không rõ điều khoản

**MEDIUM risk patterns:**
- RPT chiếm > 10% doanh thu
- RPT không được tiết lộ đầy đủ trong BCTC

### Board Independence
- HĐQT < 1/3 thành viên độc lập → LOW independence
- Chủ tịch HĐQT kiêm CEO → tập trung quyền lực

## 8. Thesis Breaker Criteria

Một rủi ro là "thesis breaker" khi thỏa MẠN:
- **Severity**: HIGH hoặc CRITICAL
- **Probability**: MEDIUM hoặc HIGH
- **Impact**: Đủ lớn để thay đổi fair value > 20% HOẶC làm mất khả năng thanh toán

**Thesis breaker examples:**
1. Phát hiện gian lận kế toán → giá sụp hoàn toàn
2. Hủy niêm yết → liquidity = 0
3. Default nợ → restructure pha loãng nặng hoặc thanh lý
4. Điều tra hình sự ban lãnh đạo → mất tin tưởng, bank run nếu là ngân hàng
5. Mất license hoạt động → doanh thu = 0

## 9. Missing Data Handling

| Tình huống | Xử lý |
|-----------|-------|
| API trả về null | Ghi `[missing_data]`, không suy luận |
| Crawl news thất bại | Ghi `[missing_data: news crawl failed]` |
| NotebookLM không có link | Bỏ qua bước, ghi "(chưa đọc báo cáo kiểm toán)" |
| Ownership data thiếu | Ghi `[missing_data]`, không tính HHI |
| Shares outstanding không rõ | Không tính dilution rate |

**Nguyên tắc**: Thà ghi missing_data còn hơn bịa số. Báo cáo không đầy đủ tốt hơn báo cáo sai.

## 10. Overall Risk Assessment Bands

| Tổng hợp | Nhận định |
|----------|-----------|
| 0 HIGH + 0 CRITICAL thesis breaker | THẤP — rủi ro có thể chấp nhận |
| 1-2 MEDIUM, 0 HIGH | CÓ THỂ QUẢN LÝ — theo dõi định kỳ |
| 1+ HIGH hoặc 1+ thesis breaker | CAO — cần due diligence sâu trước khi đầu tư |
| 2+ HIGH hoặc 2+ thesis breaker | RẤT CAO — xem xét lại toàn bộ thesis |
