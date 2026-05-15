---
name: stock-analyze
description: |
  Workflow phân tích cổ phiếu Việt Nam toàn diện bằng 2 sub-agents tuần tự.
  Trigger khi user gõ /stock-analyze, hỏi "phân tích toàn diện", "full analysis",
  "phân tích cổ phiếu", "analyze stock", "chạy full workflow", "phân tích đầy đủ",
  "comprehensive analysis". Skill nhận ticker (HPG, VCB, BSR...) hoặc tên công ty.
  Agent 1 (Fundamental): macro → industry → business → financials → risk → technical.
  Agent 2 (Valuation+Report): định giá + contradictions + báo cáo cuối.
  Cache-aware: skip agents nếu output cùng ngày đã tồn tại.
  Output: output/stock_report_{TICKER}_{DATE}.md + 3 summary JSONs.
  Contradiction HIGH → verdict downgrade 1 bậc tự động.
---

# stock-analyze

## Bước 1: Parse Input và Setup

```
TICKER = {input viết hoa}
TODAY  = {YYYY-MM-DD hôm nay}
BASE_DIR = /Users/trannhatlinh/.claude/workspace/stock-analysis
```

Kiểm tra workspace:
```bash
ls {BASE_DIR}/scripts/aggregate_reports.py
```
Không tìm thấy → "Workspace không tồn tại. Kiểm tra BASE_DIR." và dừng.

### Cache Check

```bash
ls {BASE_DIR}/output/stock_report_{TICKER}_{TODAY}.md 2>/dev/null && echo "REPORT_EXISTS"; \
ls {BASE_DIR}/output/valuation_summary_{TICKER}_{TODAY}.json 2>/dev/null && echo "VAL_EXISTS"; \
ls {BASE_DIR}/output/fundamental_summary_{TICKER}_{TODAY}.json 2>/dev/null && echo "FUND_EXISTS"
```

Quyết định:
- `REPORT_EXISTS` → tất cả output đã có hôm nay → chuyển thẳng **Bước 4** (thông báo kết quả).
- `VAL_EXISTS` (không có REPORT_EXISTS) → ghi nhận cả 2 summary paths, skip Bước 2+3, chuyển **Bước 4** sau khi xác nhận stock_report tồn tại.
- `FUND_EXISTS` (không có VAL_EXISTS) → ghi nhận FUNDAMENTAL_SUMMARY_PATH, skip Bước 2, bắt đầu **Bước 3**.
- Không có gì → chạy đầy đủ từ **Bước 2**.

---

## Bước 2: Launch Agent 1 — Fundamental Agent

Đọc: `{BASE_DIR}/.claude/agents/fundamental-agent.md`

Spawn **Agent tool** (`subagent_type="claude"`), thay thế `{TICKER}`, `{TODAY}`, `{BASE_DIR}`.

Chờ hoàn thành. Xác nhận:
```bash
ls {BASE_DIR}/output/fundamental_summary_{TICKER}_*.json
```
Không tồn tại → "Agent 1 thất bại — fundamental_summary không được tạo." và dừng.

`FUNDAMENTAL_SUMMARY_PATH` = đường dẫn đầy đủ file vừa tìm thấy.

---

## Bước 3: Launch Agent 2 — Valuation + Report Agent

Đọc: `{BASE_DIR}/.claude/agents/valuation-report-agent.md`

Spawn **Agent tool** (`subagent_type="claude"`), thay thế:
- `{TICKER}` → TICKER
- `{TODAY}` → TODAY
- `{BASE_DIR}` → BASE_DIR
- `{FUNDAMENTAL_SUMMARY_PATH}` → từ Bước 2

Chờ hoàn thành. Xác nhận:
```bash
ls {BASE_DIR}/output/stock_report_{TICKER}_*.md
```
Không tồn tại → "Agent 2 thất bại — stock_report không được tạo."

---

## Bước 4: Thông Báo Kết Quả

```
✅ /stock-analyze {TICKER} hoàn thành.

📄 Báo cáo chính:
   output/stock_report_{TICKER}_{TODAY}.md

📦 Files được tạo:
   Agent 1 → output/fundamental_summary_{TICKER}_{TODAY}.json
   Agent 2 → output/valuation_summary_{TICKER}_{TODAY}.json
             output/contradictions_{TICKER}_{TODAY}.json
             output/stock_report_{TICKER}_{TODAY}.md

Để đọc báo cáo:
   Read {BASE_DIR}/output/stock_report_{TICKER}_{TODAY}.md
```
