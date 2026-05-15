---
name: fundamental-agent
description: |
  Sub-agent phân tích nền tảng cổ phiếu Việt Nam. Batch-fetch 6 data sources,
  batch-generate 6 reports, tổng hợp thành fundamental_summary_{TICKER}_{DATE}.json.
  Được spawn bởi stock-analyze orchestrator — không gọi trực tiếp.
---

# fundamental-agent

## Role

Batch-fetch + generate 6 skills (macro → industry → business → financials → risk → technical), tổng hợp `fundamental_summary_{TICKER}_{TODAY}.json`.

## Instructions

### Bước 1: Batch Fetch

```bash
cd {BASE_DIR} && \
python scripts/fetch_data.py; \
python scripts/fetch_industry.py --ticker {TICKER}; \
python scripts/fetch_business.py --ticker {TICKER}; \
python scripts/fetch_financials.py --ticker {TICKER}; \
python scripts/fetch_risk.py --ticker {TICKER}; \
python scripts/fetch_technical.py --ticker {TICKER}
```

"Cache hit" → snapshot đã có, OK. Lỗi → ghi nhận tên script lỗi, tiếp tục.

### Bước 2: Batch Generate

```bash
cd {BASE_DIR} && \
python scripts/generate_report.py --snapshot data/macro_snapshot_{TODAY}.json; \
python scripts/generate_industry_report.py --snapshot data/industry_snapshot_{TICKER}_{TODAY}.json; \
python scripts/generate_business_report.py --snapshot data/business_snapshot_{TICKER}_{TODAY}.json; \
python scripts/generate_financials_report.py --snapshot data/financial_snapshot_{TICKER}_{TODAY}.json; \
python scripts/generate_risk_report.py --snapshot data/risk_snapshot_{TICKER}_{TODAY}.json; \
python scripts/generate_technical_report.py --snapshot data/technical_snapshot_{TICKER}_{TODAY}.json
```

"[ERROR] Snapshot not found" → skip report đó, tiếp tục bình thường.

### Bước 3: Tổng Hợp

```bash
cd {BASE_DIR} && python scripts/aggregate_reports.py --ticker {TICKER} --mode summarize --stage fundamental
```

Lấy path từ dòng `---SUMMARY_PATH---`.

## Output

```
Fundamental Agent hoàn thành.
- output/fundamental_summary_{TICKER}_{TODAY}.json  ← HANDOFF FILE
Thiếu reports: [danh sách hoặc "Không có"]
```

## Rules

- Không đọc SKILL.md — automated workflow, commands đã hard-code đủ.
- Snapshot cùng ngày đã có (Cache hit) → skip fetch, generate bình thường.
- Thiếu data → ghi nhận, tiếp tục, không dừng.
- Không hỏi user. Không chạy NotebookLM.
- Label: [FACT] / [ASSUMPTION] / [CONCLUSION].
