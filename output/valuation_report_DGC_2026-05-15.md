# Định giá: DGC
**Ngày:** 2026-05-15  |  **Ngành:** Hóa chất / Phốt pho (Chemicals)  |  **Giá hiện tại:** 51 VND
**Phương pháp chính:** P/E (primary) | Cross-check: EV/EBITDA (limited)  |  **WACC:** 11.0%  |  **Terminal growth:** 4%

---

## Trailing Metrics (TTM)

| Chỉ số | Giá trị | Ghi chú |
|--------|---------|---------|
| Revenue TTM | 10,576 B VND | [FACT] từ API |
| Net Income TTM | 2,782 B VND | [FACT] từ API |
| EBIT TTM | -40 B VND | [FACT] — bất thường: NI >> EBIT → thu nhập tài chính lớn |
| EBITDA TTM | 274 B VND | [FACT] — EV/EBITDA bị méo do EBITDA thấp |
| FCF TTM | -1,205 B VND | [FACT] — Capex 4Q = 1,205B (expansion phase) |
| EPS TTM (tính lại) | 7,326 VND | [ASSUMPTION] NI 2,782B / 379.78M cổ phiếu |
| Shares outstanding | 379.78 M | [FACT] từ risk report |
| Market cap (implied) | 19,369 B VND | [FACT] 51 VND × 379.78M |
| P/E implied | 6.96× | [FACT] 19,369 / 2,782 |

**Lưu ý quan trọng:** [ASSUMPTION] EBIT TTM = -40B nhưng NI TTM = 2,782B → chênh lệch ~2,822B đến từ thu nhập tài chính (financial income) hoặc lợi nhuận khác ngoài hoạt động kinh doanh chính. EPS dựa trên NI có thể KHÔNG bền vững nếu thu nhập tài chính là one-time.

---

## Định giá Hiện tại vs Lịch sử vs Peers

| Chỉ số | Hiện tại | Hist P25 | Hist Median | Hist P75 | Peer Median |
|--------|----------|----------|-------------|----------|-------------|
| P/E | 6.96× | [missing_data] | [missing_data] | [missing_data] | [missing_data] |
| P/B | [missing_data] | [missing_data] | [missing_data] | [missing_data] | [missing_data] |
| EV/EBITDA | 74× | [missing_data] | [missing_data] | [missing_data] | [missing_data] |

[ASSUMPTION] Lịch sử P/E không có từ API — sử dụng VN benchmark: hóa chất chu kỳ thường trade 8–15× ở pha bình thường, 4–8× ở đáy chu kỳ.
[FACT] EV/EBITDA = 74× là vô nghĩa — EBITDA 274B bị méo nghiêm trọng so với NI 2,782B; không dùng để định giá.

---

## valuation_method [FACT + ASSUMPTION]

Phương pháp chính: **P/E** | Cross-check: EV/NI (thay thế do EBITDA méo)

[FACT] P/E được chọn vì: DGC là công ty hóa chất/phốt pho — cyclical, P/E là thước đo phổ biến nhất cho ngành này tại VN.
[ASSUMPTION] WACC: 11% (default VN) | Terminal growth: 4% | EPS TTM base: 7,326 VND (tính từ NI/shares)
[ASSUMPTION] EPS có thể KHÔNG bền vững do EBIT âm — thu nhập hoạt động kinh doanh thực sự đang lỗ ở cấp EBIT.
RNAV/SOTP: Không áp dụng (DGC là công ty hóa chất thuần túy).

---

## key_assumptions [ASSUMPTION]

| Tham số | Bear | Base | Bull |
|---------|------|------|------|
| Target P/E | 5× | 8× | 12× |
| Nguồn multiple | Đáy chu kỳ (< P25 VN) | Vùng "hợp lý" đáy (P25 VN) | Phục hồi chu kỳ (median VN chems) |
| EPS assumption | TTM 7,326 VND (không điều chỉnh) | TTM 7,326 VND | TTM 7,326 VND |
| FCF growth (tham khảo) | Tiếp tục âm | Về 0 trong 2 năm | Dương từ 2027 |
| Revenue growth | -10% YoY | 0% (flat) | +10% YoY (cycle recovery) |
| DCF | Không khả thi | Không khả thi | Không khả thi (FCF âm) |

[ASSUMPTION] Không điều chỉnh EPS theo chu kỳ (mid-cycle EPS) do thiếu đủ data lịch sử.
[ASSUMPTION] P/E được calibrate theo VN benchmark + đặc điểm chu kỳ ngành hóa chất.

---

## bear_case [FACT + ASSUMPTION + CONCLUSION]

Kịch bản bi quan: **P/E 5× = dưới đáy chu kỳ — thị trường lo ngại NI không bền vững**

[FACT] EPS TTM: 7,326 VND | [ASSUMPTION] P/E: 5×
[FACT] Target: **36,630 VND** | [FACT] Downside: **-28.2%** vs giá hiện tại 51 VND

[CONCLUSION] P/E về 5× khi: (1) NI 2,782B bị xác nhận là one-time (thu nhập tài chính không lặp lại), (2) margin tiếp tục suy giảm (GM từ 39% → 23%), (3) FCF âm kéo dài buộc công ty vay thêm để Capex. Kịch bản này xảy ra nếu chu kỳ hóa chất tiếp tục xấu đến 2027.

---

## base_case [FACT + ASSUMPTION + CONCLUSION]

Kịch bản cơ sở: **P/E 8× = vùng "hợp lý" đáy chu kỳ theo VN benchmark**

[FACT] EPS TTM: 7,326 VND | [ASSUMPTION] P/E: 8×
[FACT] Target: **58,608 VND** | [FACT] Upside: **+14.9%** vs giá hiện tại 51 VND

[CONCLUSION] Điều kiện để đạt base case: NI duy trì được ở mức TTM (~2,700–2,800B/năm), thu nhập tài chính tiếp tục đóng góp, và không có sự kiện macro lớn ảnh hưởng giá phốt pho. Revenue stabilize ở ~10,000B (flat vs TTM).

---

## bull_case [FACT + ASSUMPTION + CONCLUSION]

Kịch bản tích cực: **P/E 12× = phục hồi chu kỳ + re-rating thị trường**

[FACT] EPS TTM: 7,326 VND | [ASSUMPTION] P/E: 12×
[FACT] Target: **87,912 VND** | [FACT] Upside: **+72.4%** vs giá hiện tại 51 VND

[CONCLUSION] Catalyst cần thiết: (1) Giá phốt pho/phân lân phục hồi → GM mở rộng từ 23% về 30%+, (2) FCF chuyển dương sau khi phase Capex kết thúc, (3) VN-Index recovery thu hút dòng tiền vào ngành hóa chất. Xác suất trong 12 tháng thấp trong bối cảnh hiện tại.

---

## fair_value_range [FACT + CONCLUSION]

Vùng hợp lý: **36,630 – 87,912 VND** | Mid: **58,608 VND**
Giá hiện tại: **51 VND**
DCF base cross-check: [Không khả thi — FCF TTM âm 1,205B VND]

[CONCLUSION]: Hiện tại = **Hợp lý / Dưới fair mid**
Giá hiện tại 51 VND thấp hơn fair_mid 58,608 VND **-13.0%** — nằm trong "Fair range" (MoS 10–30%). Tuy nhiên, định giá P/E 6.96× hiện tại đã phản ánh phần lớn rủi ro NI không bền vững. Upside base case chỉ ~15% — không hấp dẫn nếu so với rủi ro.

---

## upside_downside [FACT]

| Scenario | Target (VND) | vs Hiện tại (51 VND) |
|----------|-------------|----------------------|
| Bear | 36,630 | -28.2% |
| Base | 58,608 | +14.9% |
| Bull | 87,912 | +72.4% |
| DCF base | N/A | N/A (FCF âm) |
| 52W Low | 47 | -7.8% (floor tham chiếu) |
| 52W High | 103 | +101.9% (đỉnh tham chiếu) |

[FACT] R/R asymmetry: Bull upside (+72%) > Bear downside (-28%) về tỷ lệ tuyệt đối, nhưng xác suất bear/base cao hơn bull trong chu kỳ hiện tại.

---

## margin_of_safety [FACT + CONCLUSION]

**MoS vs fair_mid (58,608 VND):** 13.0% [FACT]
[CONCLUSION]: **[FAIR RANGE — 10–30%]**
Vùng tích lũy hợp lý nếu giá về dưới **41,026 VND** (MoS ≥ 30% vs fair_mid).

**Timing context (Technical — chỉ dùng cho timing, không thay đổi fair value):**
[FACT] Giá 51 VND nằm giữa S1 (48) và R1 (77). Trend BEARISH, MACD Histogram = 0 (Bullish tín hiệu nhỏ). Timing zone: **WATCH** — chưa có xác nhận đảo chiều.
[ASSUMPTION] Nếu DGC giữ vững S1 (48) với volume phục hồi → có thể tích lũy dần trong vùng 47–55 VND. Nếu phá vỡ S2 (48) → nguy cơ về test đáy mới.

---

## Cảnh báo Quan trọng [CONCLUSION]

1. **NI vs EBIT anomaly**: NI TTM 2,782B trong khi EBIT = -40B → thu nhập tài chính ~2,822B chiếm phần lớn NI. Cần xác minh tính bền vững của khoản này trước khi dùng EPS TTM làm base.
2. **FCF âm liên tục**: -1,205B VND FCF 4Q liên tiếp — công ty đang đốt tiền cho Capex. Nếu dự án không tạo ra FCF dương từ 2027, cần đánh giá lại toàn bộ fair value.
3. **Revenue declining**: -24.4% YoY, -7.9% CAGR 2Y — chưa có tín hiệu stabilize.
4. **Margin compression**: GM từ 39% (Q2/2024) xuống 23% (Q1/2026) — xu hướng tiêu cực rõ ràng.
5. **Data limitations**: Thiếu lịch sử P/E, BVPS, D/E ratio từ API — định giá dựa trên VN benchmark thay vì lịch sử công ty cụ thể.

---

## Data Warnings

- `ratio: no data — P/E/P/B historical series unavailable`
- `current_price: recovered manually from technical report (51 VND)`
- `shares_m: recovered from risk report (379.78M)`
- `EPS TTM: manually computed (NI/shares) — not from API`
- `EV/EBITDA: distorted (74×) — not used for valuation`
- `DCF: unavailable — FCF TTM = -1,205B VND (negative)`

---

*Data source: vnstock (VCI) + manual computation. [FACT]=từ API | [ASSUMPTION]=giả định | [CONCLUSION]=nhận định*
*Không khuyến nghị mua/bán. Vùng giá trị hợp lý dựa trên dữ liệu và giả định mô hình.*
