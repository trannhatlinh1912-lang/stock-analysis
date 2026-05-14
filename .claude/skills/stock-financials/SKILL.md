---
name: stock-financials
description: |
  Phân tích BCTC, dòng tiền, nợ vay và red flags tài chính của cổ phiếu Việt Nam.
  Trigger khi user gõ /stock-financials, hỏi về "phân tích BCTC", "dòng tiền",
  "nợ vay", "red flags tài chính", "chất lượng lợi nhuận", "ROE ROA ROIC",
  "financial analysis", "cashflow quality", "interest coverage",
  "hàng tồn kho khoản phải thu", "điểm tài chính". Skill nhận ticker (HPG, VCB...)
  hoặc tên công ty. Lấy data từ vnstock qua Python scripts (delegate Codex để tiết
  kiệm token). Output 7 sections: financial_trend, profitability, balance_sheet_health,
  cashflow_quality, debt_analysis, red_flags, financial_score. Mỗi section label rõ
  [FACT] / [ASSUMPTION] / [CONCLUSION]. Không bịa số liệu. Không kết luận mua/bán.
  Dùng sau /stock-industry để phân tích tài chính sâu của doanh nghiệp cụ thể.
---

# stock-financials

## Bước 1: Parse Input

Xác định ticker từ input:
- **Ticker trực tiếp** (HPG, VCB, FPT...) → dùng luôn
- **Tên công ty/ngành** → map sang ticker đại diện (hỏi user nếu không chắc):

| Tên | Ticker |
|-----|--------|
| thép / steel | HPG |
| ngân hàng / bank | VCB |
| bất động sản / BĐS | VHM |
| chứng khoán | SSI |
| bán lẻ | MWG |
| năng lượng / dầu khí | GAS |
| dược | DHG |
| công nghệ | FPT |
| phân bón | DPM |
| xây dựng | CTD |

Nếu không khớp: hỏi user cung cấp ticker cụ thể.

## Bước 2: Fetch Data (dùng Codex)

```
Dùng /codex:rescue với prompt:
"Run: python ~/.claude/workspace/stock-analysis/scripts/fetch_financials.py --ticker {TICKER}
 Report only: (1) cache hit or fresh fetch, (2) path of output JSON file.
 Do NOT print the JSON content."
```

Fallback nếu không có Codex:
```bash
cd ~/.claude/workspace/stock-analysis && python scripts/fetch_financials.py --ticker {TICKER}
```

Ghi nhận đường dẫn: `data/financial_snapshot_{TICKER}_{DATE}.json`

## Bước 3: Generate Report (dùng Codex)

```
Dùng /codex:rescue với prompt:
"Run: python ~/.claude/workspace/stock-analysis/scripts/generate_financials_report.py --snapshot {SNAPSHOT_PATH}
 Print only the lines starting from '---SNAPSHOT_JSON---' to end of output."
```

Fallback:
```bash
cd ~/.claude/workspace/stock-analysis && python scripts/generate_financials_report.py --snapshot {SNAPSHOT_PATH}
```

Lấy compact JSON từ output (phần sau `---SNAPSHOT_JSON---`).

## Bước 4: Bổ sung BCTC PDF (tùy chọn)

Nếu user muốn đọc thuyết minh, chú thích nợ vay, off-balance items:

**"Bạn có link PDF BCTC hoặc báo cáo thường niên không? Tôi có thể đọc qua NotebookLM để bổ sung thông tin thuyết minh nợ vay và contingent liabilities."**

Nếu có link:
```
Dùng /notebooklm:
"Add URL {PDF_LINK} to notebook '{TICKER} Financial Reports'.
 Create the notebook if it doesn't exist.
 Query: 'Tóm tắt ngắn gọn tối đa 150 từ: (1) nợ vay chi tiết theo loại,
 (2) bất thường trong thuyết minh dòng tiền, (3) contingent liabilities,
 (4) related party transactions đáng chú ý.'"
```

Bước này hoàn toàn tùy chọn.

## Bước 5: Viết 7 Sections Phân tích

Đọc compact JSON (~4KB). Viết đúng 7 sections — **tổng < 500 từ**.
BẮT BUỘC label: `[FACT]` (từ data API), `[ASSUMPTION]` (suy luận), `[CONCLUSION]` (nhận định).
Thiếu data → ghi `[missing_data]`, không bịa số.

```
## financial_trend [FACT]
| Quý | DT (B) | GM% | NM% | NI (B) |
(4 quarters gần nhất — tối giản, không copy đủ 8)
CAGR 2Y: {x}% | YoY latest: {x}% | GM trend: {improving/stable/declining}
[FACT] Nhận định 1 câu: xu hướng doanh thu và lợi nhuận.

## profitability [FACT + CONCLUSION]
Gross margin: {x}% ({trend}) | Net margin: {x}%
ROE: {x}% | ROA: {x}% | ROIC: {x}% (WACC proxy ~10%)
[CONCLUSION]: Sinh lời = [Cao/Trung bình/Thấp]
— 1 câu lý do cụ thể (VD: "ROIC {x}% > WACC → tạo giá trị kinh tế")

## balance_sheet_health [FACT + CONCLUSION]
D/E: {x}× ({trend}) | Net debt: {B VND} | Equity +{x}% YoY
Current ratio: {x}× | Quick ratio: {x}×
[CONCLUSION]: Bảng cân đối = [Lành mạnh / Bình thường / Cần theo dõi]

## cashflow_quality [FACT + CONCLUSION]
OCF 4Q: {B} ✅/⚠️ | FCF 4Q: {B} ✅/⚠️ | Capex/Revenue: {x}%
OCF/NI: {x} | FCF/NI: {x}
[CONCLUSION]: Chất lượng LN = [Cao/Trung bình/Thấp]
— 1 câu: "OCF/NI {x} → lợi nhuận [có/không] chuyển thành tiền thực"

## debt_analysis [FACT + CONCLUSION]
Interest expense 4Q: {B VND} | Coverage: {x}× | Net debt/EBIT: {x}×
[CONCLUSION]: Rủi ro nợ = [Thấp/Trung bình/Cao] — 1 câu lý do

## red_flags [FACT + CONCLUSION]
| # | Flag | Severity | Chi tiết |
(hoặc "Không phát hiện red flags tài chính đáng kể." nếu rỗng)
[CONCLUSION]: [Không có cờ đỏ / {N} cảnh báo cần theo dõi / Rủi ro cao — xem xét kỹ]

## financial_score [FACT]
Điểm: {total}/10 — {band}
| Tiêu chí | Điểm | Max |
|----------|------|-----|
(8 dòng breakdown)
Lưu ý: {data_warnings quan trọng, else "Không có cảnh báo"}
```

Nguyên tắc token: không diễn giải lại từng số thô — chỉ nhận định xu hướng và ý nghĩa.

## Bước 6: Lazy-load Thresholds (khi cần verify)

Chỉ đọc khi cần xác nhận ngưỡng cụ thể:
```
~/.claude/workspace/stock-analysis/references/financial_analysis.md
```

## Bước 7: Xác nhận output đã lưu

Thông báo: `output/financial_report_{TICKER}_{TODAY}.md`

## Bước 8: Lưu NotebookLM (tùy chọn)

Hỏi user: "Lưu báo cáo vào NotebookLM không?"

Nếu đồng ý:
```
Dùng /notebooklm:
"Add file ~/.claude/workspace/stock-analysis/output/financial_report_{TICKER}_{TODAY}.md
 as a source to notebook named 'Stock Financial Analysis'.
 Create the notebook if it doesn't exist."
```
