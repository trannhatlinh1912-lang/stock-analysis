---
name: stock-business
description: |
  Phân tích chất lượng doanh nghiệp của cổ phiếu Việt Nam. Trigger khi user gõ
  /stock-business, hỏi về "phân tích doanh nghiệp", "mô hình kinh doanh", "ban lãnh
  đạo", "cổ đông lớn", "chất lượng doanh nghiệp", "moat", "lợi thế cạnh tranh",
  "business analysis", "điểm chất lượng". Skill nhận ticker (HPG, VCB...) hoặc tên
  công ty. Lấy data từ vnstock qua Python scripts (delegate Codex để tiết kiệm token).
  Output 8 sections: business_model, products, customers_suppliers, market_position,
  moat, management, strengths_weaknesses, quality_score. Mỗi section label rõ [FACT]
  / [ASSUMPTION] / [CONCLUSION]. Không bịa số liệu. Không kết luận mua/bán.
  Dùng sau /stock-industry để hiểu sâu về doanh nghiệp cụ thể.
---

# stock-business

## Bước 1: Parse Input

Xác định ticker từ input của user:
- **Ticker trực tiếp** (HPG, VCB, FPT...) → dùng luôn
- **Tên ngành** → map sang ticker đại diện (hỏi user xác nhận trước khi chạy):

| Tên ngành | Ticker đại diện |
|-----------|----------------|
| thép / steel | HPG |
| ngân hàng / bank | VCB |
| bất động sản / BĐS | VHM |
| chứng khoán / securities | SSI |
| bán lẻ / retail | MWG |
| năng lượng / dầu khí | GAS |
| dược / pharma | DHG |
| công nghệ / tech | FPT |
| phân bón / fertilizer | DPM |
| xây dựng / construction | CTD |

Nếu không khớp: hỏi user cung cấp ticker cụ thể.

## Bước 2: Fetch Data (dùng Codex)

Delegate cho Codex để không tốn context window:

```
Dùng /codex:rescue với prompt:
"Run: python ~/.claude/workspace/stock-analysis/scripts/fetch_business.py --ticker {TICKER}
 Report only: (1) cache hit or fresh fetch, (2) path of output JSON file.
 Do NOT print the JSON content."
```

Fallback nếu không có Codex:
```bash
cd ~/.claude/workspace/stock-analysis && python scripts/fetch_business.py --ticker {TICKER}
```

Ghi nhận đường dẫn JSON từ output (dạng: `data/business_snapshot_{TICKER}_{DATE}.json`).

## Bước 3: Generate Report (dùng Codex)

```
Dùng /codex:rescue với prompt:
"Run: python ~/.claude/workspace/stock-analysis/scripts/generate_business_report.py --snapshot {SNAPSHOT_PATH}
 Print only the lines starting from '---SNAPSHOT_JSON---' to end of output."
```

Fallback:
```bash
cd ~/.claude/workspace/stock-analysis && python scripts/generate_business_report.py --snapshot {SNAPSHOT_PATH}
```

Lấy JSON từ output (phần sau `---SNAPSHOT_JSON---`).

## Bước 4: Bổ sung PDF (tùy chọn)

Nếu cần thêm thông tin khách hàng/nhà cung cấp/chiến lược, hỏi user:
**"Bạn có link PDF báo cáo thường niên không? Tôi có thể đọc qua NotebookLM để bổ sung sections customers_suppliers và management."**

Nếu user cung cấp link:
```
Dùng /notebooklm:
"Add URL {PDF_LINK} as a source to notebook '{TICKER} Annual Report'.
 Create the notebook if it doesn't exist.
 Then query: 'Tóm tắt ngắn gọn: (1) khách hàng chính, (2) nhà cung cấp chính,
 (3) chiến lược tăng trưởng, (4) rủi ro chính được đề cập. Tối đa 150 từ.'"
```

Bước này hoàn toàn tùy chọn — analysis tiến hành bình thường nếu bỏ qua.

## Bước 5: Viết Phân tích 8 Sections

Đọc compact JSON snapshot (~5KB). Viết đúng 8 sections — **tổng < 500 từ**.
Mỗi section BẮT BUỘC có label: `[FACT]` (từ data), `[ASSUMPTION]` (suy luận), `[CONCLUSION]` (nhận định).
Thiếu data → ghi `[missing_data]`, không bịa.

```
## business_model [FACT + ASSUMPTION]
Ngành: {industry_name} | Mô tả: {description hoặc [missing_data]}
[ASSUMPTION] Nguồn doanh thu: [suy luận từ ngành nếu không có segment data]

## products [FACT + ASSUMPTION]
Sản phẩm/dịch vụ chính: [từ company profile nếu có, else ASSUMPTION từ đặc điểm ngành]
Revenue driver: [segment/sản phẩm có biên cao nhất nếu có data]

## customers_suppliers [FACT / missing_data]
Khách hàng chính: [từ PDF NotebookLM nếu có, else [missing_data] — xem BCTC trang XX]
Nhà cung cấp: [tương tự]
[ASSUMPTION]: ngành {industry} thường phụ thuộc vào {nguyên liệu/đầu vào đặc thù}

## market_position [FACT + ASSUMPTION]
Rank doanh thu trong peers: #{rank}/{total peers} | Revenue {Q}: {VND}B vs peers avg {VND}B
[ASSUMPTION] Ước tính thị phần: ~X% (dựa trên revenue rank, không phải data thị phần thực)

## moat [FACT + CONCLUSION]
ROE ổn định: {roe_avg_4q}% avg ({roe_trend}) | Gross margin std 8Q: ±{std}%
Pricing power: gross_margin {latest}% vs industry avg {avg}%
[CONCLUSION]: Moat = [Mạnh / Trung bình / Yếu] — [1 câu lý do cụ thể từ data]

## management [FACT]
{Chức danh chính}: {Tên} | Cổ đông lớn: {Tên} ({pct}%)
Cờ đỏ: [ghi nếu officers list trống hoặc thay đổi thường xuyên = [missing_data]]

## strengths_weaknesses [CONCLUSION]
Điểm mạnh:
1. [dựa trên data: VD ROE cao, margin ổn định]
2. [VD vị thế số 1 trong peers]
3. [VD FCF dương bền vững]
Điểm yếu:
1. [VD D/E cao, FCF âm]
2. [VD missing_data: thiếu thông tin khách hàng]
3. [VD biên lợi nhuận thấp hơn trung bình ngành]

## quality_score [FACT]
Điểm: {total}/10 — {band}
| Tiêu chí | Điểm | Max |
|----------|------|-----|
| ROE avg 4Q | {x} | 1.5 |
| Net margin | {x} | 1.5 |
| Biên ổn định | {x} | 2.0 |
| D/E / ROA | {x} | 2.0 |
| FCF | {x} | 2.0 |
| Tăng trưởng | {x} | 1.0 |
Lưu ý: {data_warnings nếu có, else "Không có cảnh báo"}
```

Nguyên tắc token: không diễn giải lại từng số liệu thô — chỉ nhận định xu hướng và ý nghĩa.

## Bước 6: Tham khảo Thresholds (lazy-load)

Chỉ đọc khi cần verify ngưỡng cụ thể:
- `~/.claude/workspace/stock-analysis/references/business_quality.md`

## Bước 7: Xác nhận output đã lưu

Thông báo đường dẫn file đã lưu:
`output/business_report_{TICKER}_{TODAY}.md`

## Bước 8: Lưu NotebookLM (tùy chọn)

Hỏi user: "Lưu báo cáo vào NotebookLM không?"
Nếu đồng ý:
```
Dùng /notebooklm:
"Add file ~/.claude/workspace/stock-analysis/output/business_report_{TICKER}_{TODAY}.md
 as a source to notebook named 'Stock Business Analysis'.
 Create the notebook if it doesn't exist."
```
