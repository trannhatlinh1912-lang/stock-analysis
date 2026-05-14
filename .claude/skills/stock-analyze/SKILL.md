---
name: stock-analyze
description: |
  Workflow phân tích cổ phiếu Việt Nam toàn diện bằng 3 sub-agents tuần tự:
  Fundamental Agent (macro/industry/business/financials/risk/technical),
  Valuation Agent (định giá dựa trên nền fundamental), và Report Agent
  (tổng hợp + flag mâu thuẫn giữa agents). Trigger: /stock-analyze {TICKER}.
  Output: output/stock_report_{TICKER}_{DATE}.md + 3 summary JSONs.
---

# stock-analyze

## Bước 1: Parse Input và Setup

Xác định ticker và ngày:
```
TICKER = {input viết hoa}
TODAY  = {YYYY-MM-DD hôm nay}
BASE_DIR = ~/.claude/workspace/stock-analysis
```

Kiểm tra workspace:
```bash
ls {BASE_DIR}/scripts/aggregate_reports.py
```
Nếu không tìm thấy → thông báo lỗi: "Workspace không tồn tại. Kiểm tra BASE_DIR." và dừng.

---

## Bước 2: Launch Agent 1 — Fundamental Agent

### Đọc định nghĩa agent:
Dùng Read tool đọc:
```
{BASE_DIR}/.claude/agent/fundamental-agent.md
```

### Spawn sub-agent:
Dùng **Agent tool** (`subagent_type="claude"`) với prompt = nội dung của `fundamental-agent.md`,
trong đó thay thế các placeholder:
- `{TICKER}` → giá trị TICKER thực
- `{TODAY}` → giá trị TODAY thực
- `{BASE_DIR}` → đường dẫn đầy đủ

**Chờ agent hoàn thành trước khi tiếp tục.**

### Xác nhận output:
```bash
ls {BASE_DIR}/output/fundamental_summary_{TICKER}_*.json
```

Nếu file không tồn tại → thông báo: "Agent 1 thất bại — fundamental_summary không được tạo." và dừng.

Ghi nhận: `FUNDAMENTAL_SUMMARY_PATH` = đường dẫn đầy đủ của file vừa tìm thấy.

---

## Bước 3: Launch Agent 2 — Valuation Agent

### Đọc định nghĩa agent:
Dùng Read tool đọc:
```
{BASE_DIR}/.claude/agent/valuation-agent.md
```

### Spawn sub-agent:
Dùng **Agent tool** (`subagent_type="claude"`) với prompt = nội dung của `valuation-agent.md`,
trong đó thay thế các placeholder:
- `{TICKER}` → giá trị TICKER thực
- `{TODAY}` → giá trị TODAY thực
- `{BASE_DIR}` → đường dẫn đầy đủ
- `{FUNDAMENTAL_SUMMARY_PATH}` → đường dẫn từ Bước 2

**Chờ agent hoàn thành trước khi tiếp tục.**

### Xác nhận output:
```bash
ls {BASE_DIR}/output/valuation_summary_{TICKER}_*.json
```

Nếu file không tồn tại → thông báo: "Agent 2 thất bại — valuation_summary không được tạo." và dừng.

Ghi nhận: `VALUATION_SUMMARY_PATH` = đường dẫn đầy đủ của file vừa tìm thấy.

---

## Bước 4: Launch Agent 3 — Report Agent

### Đọc định nghĩa agent:
Dùng Read tool đọc:
```
{BASE_DIR}/.claude/agent/report-agent.md
```

### Spawn sub-agent:
Dùng **Agent tool** (`subagent_type="claude"`) với prompt = nội dung của `report-agent.md`,
trong đó thay thế các placeholder:
- `{TICKER}` → giá trị TICKER thực
- `{TODAY}` → giá trị TODAY thực
- `{BASE_DIR}` → đường dẫn đầy đủ
- `{FUNDAMENTAL_SUMMARY_PATH}` → đường dẫn từ Bước 2
- `{VALUATION_SUMMARY_PATH}` → đường dẫn từ Bước 3

**Chờ agent hoàn thành trước khi tiếp tục.**

### Xác nhận output:
```bash
ls {BASE_DIR}/output/stock_report_{TICKER}_*.md
```

Nếu file không tồn tại → thông báo: "Agent 3 thất bại — stock_report không được tạo."

---

## Bước 5: Thông Báo Kết Quả

Thông báo cho user:

```
✅ /stock-analyze {TICKER} hoàn thành.

📄 Báo cáo chính:
   output/stock_report_{TICKER}_{TODAY}.md

📦 Files được tạo:
   Agent 1 → output/fundamental_summary_{TICKER}_{TODAY}.json
   Agent 2 → output/valuation_summary_{TICKER}_{TODAY}.json
   Agent 3 → output/contradictions_{TICKER}_{TODAY}.json
             output/stock_report_{TICKER}_{TODAY}.md

Để đọc báo cáo:
   Read {BASE_DIR}/output/stock_report_{TICKER}_{TODAY}.md
```
