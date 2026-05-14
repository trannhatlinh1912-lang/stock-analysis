---
name: stock-report
description: |
  Tổng hợp kết quả từ các skill phân tích cổ phiếu (macro, industry, business,
  financials, technical, risk, valuation) thành báo cáo phân tích hoàn chỉnh cho
  cổ phiếu Việt Nam. Trigger khi user gõ /stock-report, hỏi "báo cáo tổng hợp",
  "full report", "phân tích toàn diện", "tổng hợp phân tích", "complete analysis",
  "báo cáo đầu tư", "investment report". Skill nhận ticker (HPG, VCB...) hoặc tên
  công ty. Ưu tiên đọc reports đã có trong output/ (synthesis mode) thay vì chạy
  lại sub-skills. Output 9 sections: investment_summary, macro_context,
  industry_context, business_quality, financial_health, valuation, technical_outlook,
  risk_assessment, conclusion. Kết luận BẮT BUỘC: Mua / Theo dõi / Tránh + lý do
  chính + rủi ro lớn nhất + điều kiện phân tích lại. Không bịa số liệu —
  thiếu data → [missing_data].
---

# stock-report

## Bước 1: Parse Input

Xác định ticker từ input:
- **Ticker trực tiếp** (HPG, VCB, FPT...) → dùng luôn
- **Tên công ty/ngành** → map sang ticker:

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

Ghi nhận: `TICKER={ticker}`, `TODAY={YYYY-MM-DD}`.

## Bước 2: Kiểm tra Reports Hiện có (Codex)

Delegate cho Codex để tiết kiệm token:

```
Dùng /codex:rescue với prompt:
"Run: python ~/.claude/workspace/stock-analysis/scripts/aggregate_reports.py \
  --ticker {TICKER} --mode check
 Print only the JSON object on a single line.
 Do NOT print anything else."
```

Fallback nếu không có Codex:
```bash
cd ~/.claude/workspace/stock-analysis && python scripts/aggregate_reports.py --ticker {TICKER} --mode check
```

Output JSON có dạng:
```json
{
  "ticker": "HPG",
  "found": ["macro", "industry", "business", "financials", "valuation", "technical", "risk"],
  "missing": [],
  "report_paths": {
    "macro": "output/macro_report_2026-05-14.md",
    "industry": "output/industry_report_HPG_2026-05-14.md",
    ...
  }
}
```

**QUAN TRỌNG — Ưu tiên tiết kiệm token:**
- Nếu `missing` rỗng hoặc ≤ 2 items → **Synthesis Mode**: tiếp tục Bước 4 ngay.
- Nếu `missing` ≥ 3 items → hỏi user (Bước 3).

## Bước 3: Hỏi User Về Reports Còn Thiếu (chỉ khi missing ≥ 3)

Thông báo cho user:

```
Tìm thấy: {found list}
Còn thiếu: {missing list}

Bạn muốn:
A) Chạy tất cả sub-skills còn thiếu (mất ~15-20 phút, đầy đủ hơn)
B) Tổng hợp từ data hiện có, đánh dấu [missing_data] cho phần thiếu (nhanh hơn)
C) Chạy chọn lọc sub-skills: [user nhập danh sách]
```

- Nếu user chọn **A hoặc C**: Chạy từng sub-skill còn thiếu theo thứ tự:
  1. `/stock-macro` (nếu thiếu macro)
  2. `/stock-industry {TICKER}` (nếu thiếu industry)
  3. `/stock-business {TICKER}` (nếu thiếu business)
  4. `/stock-financials {TICKER}` (nếu thiếu financials)
  5. `/stock-valuation {TICKER}` (nếu thiếu valuation)
  6. `/stock-technical {TICKER}` (nếu thiếu technical)
  7. `/stock-risk {TICKER}` (nếu thiếu risk)

  Sau khi chạy xong → quay lại Bước 2 để lấy lại report_paths.

- Nếu user chọn **B**: Tiếp tục Bước 4 với data hiện có.

## Bước 4: Aggregate Dữ liệu (Codex)

Sau khi đã có đủ (hoặc chấp nhận thiếu) reports, chạy aggregate:

```
Dùng /codex:rescue với prompt:
"Run: python ~/.claude/workspace/stock-analysis/scripts/aggregate_reports.py \
  --ticker {TICKER} --mode extract
 Print only the lines starting from '---AGGREGATE_JSON---' to end of output."
```

Fallback:
```bash
cd ~/.claude/workspace/stock-analysis && python scripts/aggregate_reports.py --ticker {TICKER} --mode extract
```

Lấy compact JSON từ phần sau `---AGGREGATE_JSON---`. JSON gồm các sub-objects:
`macro`, `industry`, `business`, `financials`, `valuation`, `technical`, `risk`,
mỗi sub-object chứa: `verdict/score`, `key_points` (≤3 bullets), `data_source`.

## Bước 5: Viết Báo cáo Tổng hợp

Đọc compact JSON (~6KB max). Viết đúng 9 sections — **tổng < 800 từ**.
BẮT BUỘC label: `[FACT]` / `[ASSUMPTION]` / `[CONCLUSION]`.
Thiếu data → `[missing_data]`. **Tuyệt đối không bịa số liệu.**

---

### Template Báo cáo

```markdown
# Báo cáo Phân tích Đầu tư — {TICKER}
**{Tên công ty đầy đủ}** | {Ngành} | {Sàn giao dịch}
Ngày phân tích: {TODAY} | Giá hiện tại: {price} VND

---

## 1. investment_summary [CONCLUSION]
> **{1 câu thesis chính xác nhất có thể viết từ data hiện có}**

| Chiều | Điểm | Nhận định |
|-------|------|-----------|
| Vĩ mô | {Bullish/Neutral/Bearish} | {3-5 từ} |
| Ngành | {Tăng trưởng/Bão hòa/Suy thoái} | {3-5 từ} |
| Doanh nghiệp | {điểm/10} | {3-5 từ} |
| Tài chính | {điểm/10} | {3-5 từ} |
| Định giá | {Rẻ/Hợp lý/Đắt} — upside {x}% | {3-5 từ} |
| Kỹ thuật | {Buy/Neutral/Sell} | {3-5 từ} |
| Rủi ro | {Thấp/Có thể quản lý/Cao} | {3-5 từ} |

**Verdict sơ bộ:** {Mua / Theo dõi / Tránh} (xem chi tiết phần 9)

---

## 2. macro_context [FACT + CONCLUSION]
[FACT] Macro VN: {Bullish/Neutral/Bearish} | DXY: {trend} | Fed: {rate}%
[FACT] Tác động ngành {TICKER}: {1 câu}
[CONCLUSION] Môi trường vĩ mô = [Thuận lợi / Trung tính / Bất lợi] cho {TICKER}
*Nguồn: {data_source hoặc missing_data}*

---

## 3. industry_context [FACT + CONCLUSION]
[FACT] Chu kỳ ngành: {giai đoạn} | Tăng trưởng ngành: {x}% YoY
[FACT] Vị thế cạnh tranh: {top/mid/bottom tier} | Margin ngành: {x}%
[CONCLUSION] Ngành = [Tăng trưởng / Bão hòa / Suy thoái] — {1 câu lý do chính}
*Nguồn: {data_source hoặc missing_data}*

---

## 4. business_quality [FACT + CONCLUSION]
[FACT] Điểm chất lượng DN: {x}/10 — {band}
[FACT] Moat: {Mạnh/Trung bình/Yếu} | Ban lãnh đạo: {tốt/trung bình/cần theo dõi}
[FACT] Điểm mạnh: {bullet chính nhất}
[CONCLUSION] Chất lượng DN = [{Cao/Trung bình/Thấp}] — {1 câu lý do}
*Nguồn: {data_source hoặc missing_data}*

---

## 5. financial_health [FACT + CONCLUSION]
[FACT] Điểm tài chính: {x}/10 | ROE: {x}% | ROIC: {x}%
[FACT] D/E: {x}× | OCF/NI: {x} | FCF 4Q: {B} VND
[FACT] Red flags: {N flags hoặc "Không có"}
[CONCLUSION] Sức khỏe tài chính = [{Tốt/Trung bình/Cần chú ý}] — {1 câu lý do}
*Nguồn: {data_source hoặc missing_data}*

---

## 6. valuation [FACT + CONCLUSION]
[FACT] Giá hiện tại: {x} VND | Fair value range: {low}–{high} VND
[FACT] P/E: {x}× (ngành: {x}×) | P/B: {x}× | Upside/Downside: {x}%
[FACT] Kịch bản Base case: {x} VND | Bear: {x} VND | Bull: {x} VND
[CONCLUSION] Định giá = [{Rẻ hấp dẫn / Hợp lý / Đắt — tránh}]
*Nguồn: {data_source hoặc missing_data}*

---

## 7. technical_outlook [FACT + CONCLUSION]
[FACT] Trend: {Uptrend/Sideways/Downtrend} | MA20: {trên/dưới} | RSI: {x}
[FACT] Kháng cự: {x} VND | Hỗ trợ: {x} VND | Volume: {tăng/giảm/flat}
[CONCLUSION] Kỹ thuật = [{Buy / Neutral / Sell}] — {1 câu: entry point / tín hiệu chờ}
*Nguồn: {data_source hoặc missing_data}*

---

## 8. risk_assessment [FACT + CONCLUSION]
[FACT] Rủi ro tổng thể: {Thấp/Có thể quản lý/Cao} | Rủi ro cao nhất: {loại}
[FACT] Thesis breakers: {N items hoặc "Không phát hiện"}
| Rủi ro | Severity | Probability |
|--------|----------|-------------|
{top 3 rủi ro từ risk_list}
[CONCLUSION] Risk profile = [{Chấp nhận được / Cần theo dõi / Cao — thận trọng}]
*Nguồn: {data_source hoặc missing_data}*

---

## 9. conclusion [CONCLUSION]

### Verdict: **{MUA / THEO DÕI / TRÁNH}**

**Lý do chính (top 3):**
1. {lý do 1 — cụ thể, có số liệu}
2. {lý do 2 — cụ thể, có số liệu}
3. {lý do 3 — cụ thể, có số liệu}

**Rủi ro lớn nhất:** {1 câu mô tả rủi ro có severity=HIGH và probability≥MEDIUM nhất}

**Điều kiện phân tích lại:**
- Trigger tích cực: {sự kiện/mức giá/chỉ số cụ thể khiến upgrade verdict}
- Trigger tiêu cực: {sự kiện/mức giá/chỉ số cụ thể khiến downgrade verdict}
- Thời điểm review định kỳ: {quý/kết quả KQKD/sự kiện doanh nghiệp cụ thể}

**Horizon phù hợp:** {Ngắn hạn <3T / Trung hạn 3-12T / Dài hạn >12T}

---
*Báo cáo được tổng hợp từ: {danh sách data_source}*
*Phần thiếu data: {missing list hoặc "Không có"}*
*Disclaimer: Đây là phân tích tham khảo, không phải tư vấn đầu tư.*
```

---

### Quy tắc Verdict (bắt buộc áp dụng nhất quán)

| Điều kiện | Verdict |
|-----------|---------|
| Định giá Rẻ + Tài chính Tốt + Rủi ro Thấp/Có thể quản lý | **MUA** |
| Định giá Hợp lý + Tài chính Tốt + Rủi ro Thấp | **MUA** |
| Định giá Rẻ + Tài chính Trung bình + Rủi ro Có thể quản lý | **THEO DÕI** |
| Định giá Hợp lý + Tài chính Trung bình | **THEO DÕI** |
| Định giá Đắt + bất kỳ điều kiện nào | **THEO DÕI / TRÁNH** |
| Rủi ro Cao (bất kỳ thesis breaker nào) | **TRÁNH** |
| Tài chính Thấp + Rủi ro Cao | **TRÁNH** |
| Thiếu ≥ 3 analyses quan trọng | **THEO DÕI** (không đủ data để kết luận) |

Khi thiếu data nhưng vẫn viết kết luận → phải ghi rõ độ tin cậy:
`[CONCLUSION — ĐỘ TIN CẬY THẤP do thiếu {missing list}]`

## Bước 6: Lưu Output

Lưu báo cáo vào:
```bash
~/.claude/workspace/stock-analysis/output/stock_report_{TICKER}_{TODAY}.md
```

Thông báo: `Đã lưu: output/stock_report_{TICKER}_{TODAY}.md`

## Bước 7: Lưu NotebookLM (tùy chọn)

Hỏi user: "Lưu báo cáo tổng hợp vào NotebookLM không?"

Nếu đồng ý:
```
Dùng /notebooklm:
"Add file ~/.claude/workspace/stock-analysis/output/stock_report_{TICKER}_{TODAY}.md
 as a source to notebook named 'Stock Investment Reports'.
 Create the notebook if it doesn't exist."
```
