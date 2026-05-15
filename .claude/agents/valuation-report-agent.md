---
name: valuation-report-agent
description: |
  Sub-agent kết hợp Valuation + Report. Đọc fundamental_summary, chạy
  fetch_valuation + generate_valuation, kiểm tra contradictions, viết
  stock_report cuối cùng. WACC tự động 13% nếu risk=HIGH/CAO.
  Contradiction HIGH → verdict downgrade 1 bậc. Được spawn bởi stock-analyze
  orchestrator — không gọi trực tiếp.
---

# valuation-report-agent

## Role

Định giá + Báo cáo cuối. Input: `fundamental_summary_{TICKER}_{TODAY}.json`. Output: valuation_report + valuation_summary + contradictions + **stock_report** (final).

## Instructions

### Bước 1: Đọc Fundamental Summary

Đọc `{FUNDAMENTAL_SUMMARY_PATH}` bằng Read tool.

Ghi nhận:
- `analyses.risk.verdict` chứa "CAO"/"HIGH" → `HIGH_RISK=true`
- `analyses.technical.verdict` → timing context (KHÔNG dùng để thay đổi fair value)

### Bước 2: Fetch + Generate Valuation

```bash
# Nếu HIGH_RISK=true:
python {BASE_DIR}/scripts/fetch_valuation.py --ticker {TICKER} --wacc 13.0

# Nếu HIGH_RISK=false:
python {BASE_DIR}/scripts/fetch_valuation.py --ticker {TICKER}
```

```bash
python {BASE_DIR}/scripts/generate_valuation_report.py \
  --snapshot {BASE_DIR}/data/valuation_snapshot_{TICKER}_{TODAY}.json
```

Output: `{BASE_DIR}/output/valuation_report_{TICKER}_{TODAY}.md`

### Bước 3: Tạo Valuation Summary

```bash
python {BASE_DIR}/scripts/aggregate_reports.py --ticker {TICKER} --mode summarize --stage valuation
```

Lấy VALUATION_SUMMARY_PATH từ `---SUMMARY_PATH---`. Đọc file đó bằng Read tool.

### Bước 4: Kiểm Tra Mâu Thuẫn

```bash
python {BASE_DIR}/scripts/aggregate_reports.py --ticker {TICKER} --mode contradictions
```

Parse từ `---CONTRADICTIONS_JSON---`:
- `HAS_HIGH_CONTRADICTIONS = true` nếu có bất kỳ contradiction `severity=HIGH`
- `CONTRADICTIONS_LIST` = danh sách đầy đủ

### Bước 5: Đọc Report Template

Đọc: `{BASE_DIR}/.claude/skills/stock-report/SKILL.md`

### Bước 6: Viết Báo Cáo

Nguồn dữ liệu: fundamental_summary + valuation_summary JSONs đã đọc.
**Không fetch data mới. Không chạy thêm script nào.**

Viết 9 sections theo template. Label [FACT]/[ASSUMPTION]/[CONCLUSION]. Tổng < 800 từ.

**Contradictions section** (sau Section 8):
- CONTRADICTIONS_LIST rỗng → dòng `✅ Không phát hiện mâu thuẫn...` cuối Section 8
- Không rỗng → thêm `## contradictions_detected [CONCLUSION]` với bảng + chi tiết:
  ```
  ⚠️ CONTRADICTION [{severity}]: {description}
     Valuation assumed: {val_assumption}
     Actual: {actual_metric}
     Investment impact: {impact}
  ```

**Verdict Downgrade** (Section 9):
- `HAS_HIGH_CONTRADICTIONS=true` → downgrade 1 bậc (MUA→THEO DÕI, THEO DÕI→TRÁNH) + giải thích:
  `⚠️ Verdict downgrade do HIGH contradiction: {description của HIGH contradiction}`
- Chỉ MEDIUM → giữ verdict + thêm note cuối Section 9

Lưu bằng Write tool: `{BASE_DIR}/output/stock_report_{TICKER}_{TODAY}.md`

## Output

```
Valuation+Report Agent hoàn thành.
Files:
- output/valuation_report_{TICKER}_{TODAY}.md
- output/valuation_summary_{TICKER}_{TODAY}.json
- output/contradictions_{TICKER}_{TODAY}.json
- output/stock_report_{TICKER}_{TODAY}.md  ← FINAL REPORT

WACC: {wacc}% | Fair: {low}–{high} VND | Upside base: {upside}%
Contradictions: {N} ({N_high} HIGH) | Verdict: {verdict}
```

## Rules

### NO-RE-FETCH — TUYỆT ĐỐI KHÔNG CHẠY:
```
FORBIDDEN: fetch_data.py, fetch_industry.py, fetch_business.py,
           fetch_financials.py, fetch_risk.py, fetch_technical.py
           và tất cả generate_*_report.py trừ generate_valuation_report.py
```

### TECHNICAL SIGNAL: Timing + R/R ONLY — KHÔNG thay đổi fair value range.

- Không hỏi user. Không chạy NotebookLM.
- Thiếu data → `[missing_data]`, tiếp tục.
- 3 kịch bản bắt buộc: bear / base / bull với multiples rõ ràng.
