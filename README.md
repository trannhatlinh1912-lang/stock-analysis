# Stock Analysis — Hệ thống Phân tích Cổ phiếu Việt Nam

Workflow phân tích cổ phiếu tự động dùng 3 sub-agents tuần tự, tích hợp với Claude Code.

## Kiến trúc

```
/stock-analyze {TICKER}
       │
       ├─► Agent 1 — Fundamental Agent
       │     skills: macro → industry → business → financials → risk → technical
       │     output: fundamental_summary_{TICKER}_{DATE}.json
       │
       ├─► Agent 2 — Valuation Agent
       │     skills: valuation (đọc fundamental summary, không re-fetch)
       │     output: valuation_summary_{TICKER}_{DATE}.json
       │
       └─► Agent 3 — Report Agent
             skills: stock-report (synthesis + contradiction check)
             output: stock_report_{TICKER}_{DATE}.md
```

## Skills

| Skill | Trigger | Mô tả |
|-------|---------|-------|
| `/stock-analyze` | `/stock-analyze {TICKER}` | Workflow 3-agent toàn diện |
| `/stock-macro` | `/stock-macro` | Vĩ mô toàn cầu & tác động VN |
| `/stock-industry` | `/stock-industry {TICKER}` | Chu kỳ ngành & cạnh tranh |
| `/stock-business` | `/stock-business {TICKER}` | Chất lượng doanh nghiệp & moat |
| `/stock-financials` | `/stock-financials {TICKER}` | BCTC, dòng tiền, red flags |
| `/stock-risk` | `/stock-risk {TICKER}` | Rủi ro pháp lý, quản trị, pha loãng |
| `/stock-technical` | `/stock-technical {TICKER}` | Kỹ thuật, timing, key levels |
| `/stock-valuation` | `/stock-valuation {TICKER}` | Định giá P/E, P/B, DCF |
| `/stock-report` | `/stock-report {TICKER}` | Báo cáo tổng hợp đơn lẻ |

## Cấu trúc Thư mục

```
.
├── .claude/
│   ├── agents/                  # Định nghĩa 3 sub-agents
│   │   ├── fundamental-agent.md
│   │   ├── valuation-agent.md
│   │   └── report-agent.md
│   └── skills/                 # 9 skill definitions
│       ├── stock-analyze/
│       ├── stock-macro/
│       ├── stock-industry/
│       ├── stock-business/
│       ├── stock-financials/
│       ├── stock-risk/
│       ├── stock-technical/
│       ├── stock-valuation/
│       └── stock-report/
├── scripts/                    # Python scripts
│   ├── aggregate_reports.py    # Orchestration: check/extract/summarize/contradictions
│   ├── fetch_*.py              # Data fetching (vnstock, yfinance, FRED)
│   └── generate_*_report.py   # Report generation
├── references/                 # Ngưỡng & tiêu chí phân tích
│   ├── indicators.md
│   ├── industry_cycles.md
│   ├── business_quality.md
│   ├── financial_analysis.md
│   ├── risk_analysis.md
│   ├── technical_analysis.md
│   └── valuation_methods.md
├── data/                       # Snapshots JSON (gitignored)
└── output/                     # Reports & summaries
```

## Cài đặt

```bash
pip install vnstock yfinance pandas pandas_ta fredapi requests
```

Tạo `data/.env` với API keys cần thiết:
```
FRED_API_KEY=your_key_here
```

## Nguyên tắc Hoạt động

- **Không re-fetch**: Agent sau đọc output của agent trước, không fetch lại data đã có.
- **Technical = timing only**: Tín hiệu kỹ thuật chỉ dùng cho timing và R/R, không thay đổi fair value.
- **Contradiction detection**: `aggregate_reports.py --mode contradictions` so sánh giả định định giá vs dữ liệu cơ bản, tự động downgrade verdict nếu phát hiện mâu thuẫn HIGH.
- **Labeling bắt buộc**: `[FACT]` / `[ASSUMPTION]` / `[CONCLUSION]` trong mọi section. Thiếu data → `[missing_data]`, không bịa số liệu.

## Ví dụ Output

Xem thư mục `output/` cho kết quả phân tích BSR (2026-05-15).
