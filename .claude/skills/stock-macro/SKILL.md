---
name: stock-macro
description: |
  Phân tích vĩ mô toàn cầu và tác động đến TTCK Việt Nam. Trigger khi user gõ
  /stock-macro, hỏi về "vĩ mô", "macro VN", "Fed ảnh hưởng", "tình hình kinh tế",
  "phân tích macro", "DXY", "lãi suất Fed". Skill lấy data từ FRED + World Bank +
  yfinance qua scripts Python (delegate cho Codex để tiết kiệm token), tạo báo cáo
  compact với bảng chỉ số + verdict Bullish/Neutral/Bearish, sau đó lưu lịch sử vào
  NotebookLM. Dùng skill này trước khi phân tích cổ phiếu cụ thể để hiểu bức tranh
  vĩ mô tổng thể.
---

# stock-macro

## Bước 1: Kiểm tra Setup

Workspace: `~/.claude/workspace/stock-analysis/`

Kiểm tra `~/.claude/workspace/stock-analysis/data/.env` có FRED_API_KEY chưa.
- Nếu chưa: nhắc user đăng ký free key tại https://fred.stlouisfed.org/docs/api/api_key.html rồi thêm vào file `.env`.
- Nếu chưa cài dependencies: chạy `bash ~/.claude/workspace/stock-analysis/scripts/setup.sh`.

## Bước 2: Fetch Data (dùng Codex)

Delegate cho Codex để không tốn context window:

```
Dùng /codex:rescue với prompt:
"Run the Python script at ~/.claude/workspace/stock-analysis/scripts/fetch_data.py
 and report: (1) whether it used cache or fetched fresh, (2) the path of the output JSON file.
 Do not print the full JSON content."
```

Nếu không có Codex: chạy trực tiếp qua Bash:
```bash
cd ~/.claude/workspace/stock-analysis && python scripts/fetch_data.py
```

## Bước 3: Generate Report (dùng Codex)

```
Dùng /codex:rescue với prompt:
"Run ~/.claude/workspace/stock-analysis/scripts/generate_report.py.
 Print only the lines after '---SNAPSHOT_JSON---' (the JSON object)."
```

Nếu không có Codex:
```bash
cd ~/.claude/workspace/stock-analysis && python scripts/generate_report.py
```

Lấy JSON snapshot từ output của script (phần sau `---SNAPSHOT_JSON---`).

## Bước 4: Viết Nhận định

Đọc JSON snapshot (nhỏ, ~500 chars). Tra cứu `references/indicators.md` nếu cần.
Viết phần nhận định theo format sau — **ngắn gọn, tối đa 5 câu**:

```
## Kênh Truyền dẫn
[1-2 câu: global factor quan trọng nhất đang tác động thế nào đến VN]

## Ngành Ảnh hưởng
- Hưởng lợi: [ngành + lý do ngắn]
- Bất lợi: [ngành + lý do ngắn]

## Verdict: [🟢 BULLISH / 🟡 NEUTRAL / 🔴 BEARISH]
[1 câu tóm tắt lý do]
```

Nguyên tắc token: không diễn giải lại từng chỉ số — chỉ nhận định chuỗi nhân quả.

## Bước 5: Lưu NotebookLM (tùy chọn)

Sau khi tạo xong báo cáo, hỏi user: "Lưu báo cáo vào NotebookLM không?"
Nếu đồng ý:
```
Dùng /notebooklm:
"Add file ~/.claude/workspace/stock-analysis/output/macro_report_{TODAY}.md
 as a source to notebook named 'Stock Macro History'.
 Create the notebook if it doesn't exist."
```

## Tham khảo

- Ngưỡng chỉ số + cơ chế truyền dẫn: `~/.claude/workspace/stock-analysis/references/indicators.md`
- Chỉ đọc file này khi cần tra ngưỡng cụ thể (không load mặc định để tiết kiệm token)
