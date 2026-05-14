---
name: stock-valuation
description: |
  Định giá cổ phiếu Việt Nam bằng P/E, P/B, EV/EBITDA, DCF, RNAV, SOTP.
  Trigger khi user gõ /stock-valuation, hỏi về "định giá cổ phiếu", "giá trị hợp lý",
  "fair value", "upside downside", "P/E P/B EV/EBITDA", "DCF", "RNAV", "SOTP",
  "margin of safety", "bear case bull case", "kịch bản định giá",
  "giá mục tiêu", "target price", "vùng mua vào", "valuation", "định giá".
  Skill nhận ticker (HPG, VCB...) hoặc tên công ty. Lấy data từ vnstock qua Python
  scripts (delegate Codex). Output 8 sections: valuation_method, key_assumptions,
  bear_case, base_case, bull_case, fair_value_range, upside_downside, margin_of_safety.
  Mỗi section label rõ [FACT] / [ASSUMPTION] / [CONCLUSION]. Không bịa số liệu.
  Không kết luận mua/bán. Dùng sau /stock-financials để định giá chính xác hơn.
---

# stock-valuation

## Bước 1: Parse Input

Xác định ticker từ input:
- **Ticker trực tiếp** (HPG, VCB, FPT...) → dùng luôn
- **Tên công ty/ngành** → map sang ticker đại diện:

| Tên | Ticker | Phương pháp chính |
|-----|--------|-------------------|
| thép / steel | HPG | P/E |
| ngân hàng / bank | VCB | P/B |
| bất động sản / BĐS | VHM | P/B + RNAV note |
| chứng khoán | SSI | P/B |
| bán lẻ | MWG | P/E |
| năng lượng / dầu khí | GAS | EV/EBITDA |
| dược | DHG | P/E |
| công nghệ | FPT | P/E |
| phân bón | DPM | P/E |
| xây dựng | CTD | P/E |

Nếu không khớp: hỏi user cung cấp ticker cụ thể.

## Bước 2: Fetch + Compute Valuation (Codex)

```
Dùng /codex:rescue với prompt:
"Run: python ~/.claude/workspace/stock-analysis/scripts/fetch_valuation.py --ticker {TICKER}
 Report only: (1) cache hit or fresh fetch, (2) path of output JSON file.
 Do NOT print the JSON content."
```

Fallback nếu không có Codex:
```bash
cd ~/.claude/workspace/stock-analysis && python3 scripts/fetch_valuation.py --ticker {TICKER}
```

Ghi nhận: `data/valuation_snapshot_{TICKER}_{DATE}.json`

**Nếu user muốn override WACC:**
```bash
python3 scripts/fetch_valuation.py --ticker {TICKER} --wacc {WACC_VALUE}
```

## Bước 3: Generate Report (Codex)

```
Dùng /codex:rescue với prompt:
"Run: python ~/.claude/workspace/stock-analysis/scripts/generate_valuation_report.py --snapshot {SNAPSHOT_PATH}
 Print only the lines starting from '---SNAPSHOT_JSON---' to end of output."
```

Fallback:
```bash
cd ~/.claude/workspace/stock-analysis && python3 scripts/generate_valuation_report.py --snapshot {SNAPSHOT_PATH}
```

Lấy compact JSON từ output (phần sau `---SNAPSHOT_JSON---`).

## Bước 4: Bổ sung Analyst Report (tùy chọn)

Nếu user có link PDF báo cáo analyst hoặc annual report có RNAV/SOTP breakdown:

**"Bạn có link PDF báo cáo analyst hoặc annual report không? Tôi có thể đọc qua NotebookLM để bổ sung target price analyst và giả định WACC/growth."**

Nếu có link:
```
Dùng /notebooklm:
"Add URL {PDF_LINK} to notebook '{TICKER} Valuation'.
 Create the notebook if it doesn't exist.
 Query: 'Tóm tắt tối đa 100 từ: (1) target price của analyst và phương pháp dùng,
 (2) WACC và terminal growth rate used, (3) RNAV/SOTP breakdown nếu có,
 (4) key assumptions khác biệt với base case.'"
```

## Bước 5: RNAV / SOTP (tùy chọn — chỉ khi user có data)

**Nếu REALESTATE và user cung cấp land bank data:**
```
Dùng /codex:rescue với prompt:
"Compute RNAV for {TICKER}:
 equity_b={EQUITY_B}, net_debt_b={NET_DEBT_B},
 land_bank_segments=[{area_m2, location, price_per_m2, discount_pct}, ...],
 completed_inventory_b={X}, shares_m={SHARES_M}.
 Output: rnav_per_share (VND), premium_to_book (%)."
```

**Nếu CONGLOMERATE và user cung cấp segment data:**
```
Dùng /codex:rescue với prompt:
"Compute SOTP for {TICKER}:
 segments=[{name, revenue_b, ebit_b, target_multiple, method}],
 net_debt_b={X}, holding_discount_pct=20, shares_m={SHARES_M}.
 Output: sotp_per_share (VND), segment breakdown table."
```

## Bước 6: Viết 8 Sections Phân tích

Đọc compact JSON (~4KB). Viết đúng 8 sections — **tổng < 550 từ**.
BẮT BUỘC label: `[FACT]` (từ data API), `[ASSUMPTION]` (giả định), `[CONCLUSION]` (nhận định).
Thiếu data → ghi `[missing_data]`, không bịa số.

```
## valuation_method [FACT + ASSUMPTION]
Phương pháp chính: {PE|PB|EV_EBITDA} | Cross-check: {method}
[FACT] Lý do: 1 câu (VD: "STEEL → P/E primary, cross-check P/B")
[ASSUMPTION] WACC: {x}% | Terminal growth: 4% | EPS/BVPS base: {x} VND
RNAV/SOTP: [không áp dụng / cần dữ liệu land bank bổ sung / đã tính — xem Bước 5]

## key_assumptions [ASSUMPTION]
| Tham số | Bear | Base | Bull |
|---------|------|------|------|
| Target {P/E hoặc P/B} | {x}× | {x}× | {x}× |
| Nguồn multiple | {P25 hist} | {median hist} | {P75 hist} |
| FCF growth (DCF) | -3%/năm | +7%/năm | +15%/năm |
| EPS/BVPS assumption | trailing TTM (no change) | trailing TTM | trailing TTM |

## bear_case [FACT + ASSUMPTION + CONCLUSION]
Kịch bản bi quan: {assumption — VD "P/E 10.5× = P25 lịch sử 8Q"}
[FACT] Target: {price} VND | [FACT] Upside: {x}%
[CONCLUSION] 1 câu lý do (VD: "P/E về mức đáy khi thị trường lo ngại margin squeeze + nhu cầu thép suy yếu")

## base_case [FACT + ASSUMPTION + CONCLUSION]
Kịch bản cơ sở: {assumption — VD "P/E 14× = median lịch sử 8Q"}
[FACT] Target: {price} VND | [FACT] Upside: {x}%
[CONCLUSION] 1 câu: điều kiện giữ nguyên để đạt base case

## bull_case [FACT + ASSUMPTION + CONCLUSION]
Kịch bản tích cực: {assumption — VD "P/E 18× = P75 lịch sử, thị trường re-rate"}
[FACT] Target: {price} VND | [FACT] Upside: {x}%
[CONCLUSION] 1 câu: catalyst cần thiết (VD: "cần chu kỳ thép phục hồi + biên lợi nhuận mở rộng")

## fair_value_range [FACT + CONCLUSION]
Vùng hợp lý: {low}–{high} VND | Mid: {mid} VND
Giá hiện tại: {price} VND
DCF base cross-check: {dcf_base_price} VND (nếu available)
[CONCLUSION]: Hiện tại = [Rẻ đáng kể / Hợp lý / Đang đắt]
— 1 câu: "Giá hiện tại {x}% so với fair_mid"

## upside_downside [FACT]
| Scenario | Target (VND) | vs Hiện tại |
|----------|-------------|-------------|
| Bear | {x} | {y}% |
| Base | {x} | {y}% |
| Bull | {x} | {y}% |
| DCF base | {x} / N/A | {y}% |

## margin_of_safety [FACT + CONCLUSION]
MoS vs fair_mid: {x}% [FACT]
[CONCLUSION]: [{band}]
— 1 câu hướng dẫn: VD "Vùng tích lũy hợp lý nếu giá về dưới {round(fair_mid × 0.7)} VND (MoS ≥30%)"
```

Nguyên tắc token: không diễn giải lại từng số — chỉ nhận định và ý nghĩa.

## Bước 7: Lazy-load Thresholds (khi cần verify)

Chỉ đọc khi cần xác nhận ngưỡng VN benchmark hoặc DCF parameters:
```
~/.claude/workspace/stock-analysis/references/valuation_methods.md
```

## Bước 8: Xác nhận output đã lưu

Thông báo: `output/valuation_report_{TICKER}_{TODAY}.md`

## Bước 9: Lưu NotebookLM (tùy chọn)

Hỏi user: "Lưu báo cáo vào NotebookLM không?"

Nếu đồng ý:
```
Dùng /notebooklm:
"Add file ~/.claude/workspace/stock-analysis/output/valuation_report_{TICKER}_{TODAY}.md
 as a source to notebook named 'Stock Valuation'.
 Create the notebook if it doesn't exist."
```
