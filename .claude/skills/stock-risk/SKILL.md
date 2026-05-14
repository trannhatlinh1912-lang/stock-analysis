---
name: stock-risk
description: |
  Soi rủi ro pháp lý, kiểm toán, quản trị, nợ vay, pha loãng, hủy niêm yết và
  giao dịch bên liên quan của cổ phiếu Việt Nam. Trigger khi user gõ /stock-risk,
  hỏi về "rủi ro cổ phiếu", "soi rủi ro", "risk analysis", "pháp lý", "kiểm toán",
  "quản trị công ty", "pha loãng", "hủy niêm yết", "giao dịch nội bộ",
  "insider trading", "thesis breakers", "rủi ro đầu tư", "nợ vay rủi ro",
  "dilution risk", "governance risk", "audit risk", "legal risk", "delisting risk".
  Skill nhận ticker (HPG, VCB...) hoặc tên công ty. Lấy data từ vnstock qua Python
  scripts (delegate Codex để tiết kiệm token). Output 9 sections: risk_list,
  legal_risk, audit_risk, governance_risk, debt_risk, dilution_risk, severity,
  probability, thesis_breakers. Mỗi section label rõ [FACT] / [ASSUMPTION] /
  [CONCLUSION]. Không bịa số liệu. Không kết luận mua/bán. Ưu tiên tìm lý do
  khoản đầu tư có thể sai, không làm đẹp báo cáo.
---

# stock-risk

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

## Bước 2: Fetch Risk Data (dùng Codex)

```
Dùng /codex:rescue với prompt:
"Run: python ~/.claude/workspace/stock-analysis/scripts/fetch_risk.py --ticker {TICKER}
 Report only: (1) cache hit or fresh fetch, (2) path of output JSON file.
 Do NOT print the JSON content."
```

Fallback nếu không có Codex:
```bash
cd ~/.claude/workspace/stock-analysis && python scripts/fetch_risk.py --ticker {TICKER}
```

Ghi nhận đường dẫn: `data/risk_snapshot_{TICKER}_{DATE}.json`

## Bước 3: Generate Risk Report (dùng Codex)

```
Dùng /codex:rescue với prompt:
"Run: python ~/.claude/workspace/stock-analysis/scripts/generate_risk_report.py --snapshot {SNAPSHOT_PATH}
 Print only the lines starting from '---SNAPSHOT_JSON---' to end of output."
```

Fallback:
```bash
cd ~/.claude/workspace/stock-analysis && python scripts/generate_risk_report.py --snapshot {SNAPSHOT_PATH}
```

Lấy compact JSON từ output (phần sau `---SNAPSHOT_JSON---`).

## Bước 4: Crawl Tin Tức Gần Đây (Codex — tùy chọn, làm nếu có thời gian)

Dùng để bổ sung sự kiện pháp lý, kiểm toán, margin call, pha loãng gần nhất mà API không có:

```
Dùng /codex:rescue với prompt:
"Fetch news about {TICKER} from cafef.vn and stockbiz.vn (last 30 days).
 Search URL patterns:
   https://cafef.vn/thi-truong-chung-khoan/co-phieu-{ticker_lower}.chn
   https://stockbiz.vn/news/search?q={TICKER}
 Filter headlines for keywords: kiểm toán ngoại trừ, going concern, vi phạm,
 phát hành thêm cổ phiếu, ESOP, cảnh báo hủy niêm yết, tạm dừng giao dịch,
 margin call lãnh đạo, giao dịch nội bộ, điều tra, truy tố.
 Return JSON: [{date, source, headline, risk_category}] — max 10 items.
 If no relevant news, return empty array []."
```

Nếu crawl thất bại hoặc không tìm thấy → ghi `[missing_data]` tại news_events.

## Bước 5: Đọc Báo Cáo Kiểm Toán / Tài Liệu Pháp Lý (NotebookLM — chỉ khi user có link)

Hỏi user: **"Bạn có link PDF báo cáo kiểm toán, báo cáo thường niên, hoặc nghị quyết ĐHCĐ không? NotebookLM có thể đọc và tóm tắt ý kiến kiểm toán, giao dịch bên liên quan, và thay đổi ban lãnh đạo."**

Nếu có link:
```
Dùng /notebooklm:
"Add URL {PDF_LINK} to notebook '{TICKER} Risk Documents'.
 Create the notebook if it doesn't exist.
 Query: 'Tóm tắt tối đa 150 từ: (1) ý kiến kiểm toán (ngoại trừ/từ chối/going concern?),
 (2) giao dịch bên liên quan đáng chú ý (quy mô, điều khoản bất thường),
 (3) thay đổi ban lãnh đạo hoặc kiểm toán viên trong năm,
 (4) vi phạm công bố thông tin hoặc yêu cầu giải trình từ UBCKNN/HoSE/HNX,
 (5) cam kết bảo lãnh, nợ tiềm ẩn, nghĩa vụ tài chính ngoài bảng cân đối.'"
```

Bước này hoàn toàn tùy chọn.

## Bước 6: Viết 9 Sections Phân tích

Đọc compact JSON (~4KB) + news summary (nếu có) + NotebookLM summary (nếu có).
Viết đúng 9 sections — **tổng < 600 từ**.
BẮT BUỘC label: `[FACT]` (từ data API), `[ASSUMPTION]` (suy luận), `[CONCLUSION]` (nhận định).
Thiếu data → ghi `[missing_data]`, tuyệt đối không bịa số.
**Ưu tiên tìm lý do khoản đầu tư CÓ THỂ SAI — không làm đẹp báo cáo.**

```
## risk_list [FACT]
| # | Loại rủi ro | Mô tả ngắn | Severity | Probability |
|---|-------------|-----------|----------|-------------|
(liệt kê tất cả rủi ro tìm được — không lọc bỏ)
Tổng: {N} rủi ro | HIGH: {N} | MEDIUM: {N} | LOW: {N}

## legal_risk [FACT + ASSUMPTION + CONCLUSION]
[FACT] Vi phạm/điều tra: {sự kiện cụ thể hoặc "Không phát hiện qua API/news"}
[FACT] Công bố thông tin: {vi phạm nếu có, hoặc "Không phát hiện"}
[ASSUMPTION] Rủi ro tiềm ẩn: {1 câu — VD "Ngành BĐS có rủi ro cao về pháp lý dự án"}
[CONCLUSION] Legal risk = [THẤP / TRUNG BÌNH / CAO]

## audit_risk [FACT + ASSUMPTION + CONCLUSION]
[FACT] Kiểm toán viên: {tên công ty kiểm toán} | Thay đổi gần đây: {có/không/missing_data}
[FACT] Ý kiến kiểm toán: {chấp nhận toàn phần / ngoại trừ / từ chối / missing_data}
[FACT] Going concern: {đề cập / không đề cập / missing_data}
[CONCLUSION] Audit risk = [THẤP / TRUNG BÌNH / CAO]
— 1 câu lý do cụ thể

## governance_risk [FACT + ASSUMPTION + CONCLUSION]
[FACT] Cổ đông lớn nhất: {tên} — {pct}% | Top 5: {pct}% | Nhà nước: {pct}%
[FACT] HHI top 5: {score} → [tập trung cao/trung bình/thấp]
[FACT] Giao dịch bên liên quan: {từ NotebookLM hoặc missing_data}
[ASSUMPTION] Rủi ro lãnh đạo điều hành vì lợi ích cá nhân: {cao/trung bình/thấp}
[CONCLUSION] Governance risk = [THẤP / TRUNG BÌNH / CAO]

## debt_risk [FACT + CONCLUSION]
[FACT] D/E: {x}× | Interest coverage: {x}× | Net debt: {B VND}
[FACT] Rủi ro refinancing: {EBIT_b} EBIT / {interest_b} lãi vay
[CONCLUSION] Debt risk = [THẤP / TRUNG BÌNH / CAO]
— 1 câu: "Coverage {x}× → [đủ/mỏng/nguy hiểm] khả năng trả nợ"

## dilution_risk [FACT + CONCLUSION]
[FACT] Cổ phiếu lưu hành: {current_m}M cổ phiếu | 1 năm trước: {1y_ago_m}M
[FACT] Tốc độ pha loãng: {dilution_pct}%/năm
[FACT] Sự kiện pha loãng gần đây: {ESOP/phát hành thêm/trái phiếu chuyển đổi hoặc "Không phát hiện"}
[CONCLUSION] Dilution risk = [THẤP / TRUNG BÌNH / CAO]
— 1 câu: "Pha loãng {pct}% → [không đáng kể/cần theo dõi/侵蚀 giá trị cổ đông]"

## severity [FACT]
| Danh mục | Severity | Lý do chính |
|----------|----------|-------------|
| Legal     | HIGH/MEDIUM/LOW | ... |
| Audit     | HIGH/MEDIUM/LOW | ... |
| Governance| HIGH/MEDIUM/LOW | ... |
| Debt      | HIGH/MEDIUM/LOW | ... |
| Dilution  | HIGH/MEDIUM/LOW | ... |
Overall worst case: {danh mục} = {HIGH/MEDIUM/LOW}

## probability [ASSUMPTION + CONCLUSION]
| Danh mục | Probability | Căn cứ |
|----------|-------------|--------|
| Legal     | HIGH/MEDIUM/LOW | {1-3 từ} |
| Audit     | HIGH/MEDIUM/LOW | {1-3 từ} |
| Governance| HIGH/MEDIUM/LOW | {1-3 từ} |
| Debt      | HIGH/MEDIUM/LOW | {1-3 từ} |
| Dilution  | HIGH/MEDIUM/LOW | {1-3 từ} |
[ASSUMPTION] Xác suất dựa trên lịch sử ngành VN và dữ liệu hiện có

## thesis_breakers [CONCLUSION]
Yếu tố có thể PHÁ VỠ luận điểm đầu tư (chỉ liệt kê severity=HIGH VÀ probability≥MEDIUM):
| # | Thesis Breaker | Cơ chế phá vỡ | Tín hiệu cảnh báo sớm |
|---|----------------|--------------|----------------------|
(hoặc "Không phát hiện thesis breaker nghiêm trọng từ dữ liệu hiện có." nếu rỗng)
[CONCLUSION] Mức độ rủi ro tổng thể: [THẤP / CÓ THỂ QUẢN LÝ / CAO — cần due diligence sâu]
```

Nguyên tắc token: không diễn giải lại từng số thô — chỉ nhận định xu hướng và ý nghĩa nguy hiểm.

## Bước 7: Lazy-load Thresholds (khi cần verify)

Chỉ đọc khi cần xác nhận ngưỡng cụ thể:
```
~/.claude/workspace/stock-analysis/references/risk_analysis.md
```

## Bước 8: Xác nhận output đã lưu

Thông báo: `output/risk_report_{TICKER}_{TODAY}.md`

## Bước 9: Lưu NotebookLM (tùy chọn)

Hỏi user: "Lưu báo cáo vào NotebookLM không?"

Nếu đồng ý:
```
Dùng /notebooklm:
"Add file ~/.claude/workspace/stock-analysis/output/risk_report_{TICKER}_{TODAY}.md
 as a source to notebook named 'Stock Risk Analysis'.
 Create the notebook if it doesn't exist."
```
