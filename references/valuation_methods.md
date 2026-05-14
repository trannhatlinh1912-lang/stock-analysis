# Valuation Methods — Reference

## Method Selection by Industry

| Industry | Primary Method | Cross-check | Special Note |
|----------|---------------|-------------|--------------|
| BANK, SECURITIES | P/B | P/E | ROE × P/B drives value; D/E không dùng |
| REALESTATE | P/B | P/E | RNAV cần land bank data (xem phần RNAV) |
| CONGLOMERATE | P/E | SOTP | SOTP cần segment data (xem phần SOTP) |
| ENERGY, UTILITIES | EV/EBITDA | P/E | Capital-intensive; depreciation lớn |
| STEEL, CONSTRUCTION | P/E | EV/EBITDA | Cyclical — dùng mid-cycle EPS |
| RETAIL, TECH, PHARMA | P/E | P/B | Growth premium tùy ngành |

## Vietnam P/E Benchmarks (VN-Index)

| Mức | P/E | Nhận định |
|-----|-----|-----------|
| Rẻ | < 8× | Dưới đáy chu kỳ / crisis |
| Hợp lý | 8–15× | Vùng tích lũy |
| Fair | 12–18× | Giá hợp lý trung bình |
| Đắt | > 18× | Cần tăng trưởng cao để justify |
| High-growth premium | 20–30× | Tech (FPT), consumer staples tăng trưởng cao |

## Vietnam P/B Benchmarks

| Sector | P/B hợp lý | Ghi chú |
|--------|-----------|---------|
| BANK (ROE ~15–20%) | 1.5–2.5× | Higher ROE → higher P/B |
| BANK (ROE < 12%) | 0.8–1.2× | Discount to book |
| REALESTATE | 1.0–2.0× | Tùy land bank quality |
| SECURITIES | 1.0–1.8× | |

## DCF Parameters (Vietnam)

| Parameter | Value | Lý do |
|-----------|-------|-------|
| WACC — default | 11% | Risk-free ~5% + equity premium ~6% |
| WACC — BANK | 12% | Cao hơn do leverage |
| WACC — REALESTATE | 13% | Project risk cao hơn |
| WACC — ENERGY | 10% | Regulated, stable cash flow |
| Terminal growth | 4% | Conservative (VN nominal GDP ~6%, discount 200bps) |
| Tax rate proxy | 20% | Standard VN corporate tax |
| Forecast period | 5 năm | Sau đó dùng terminal value |

**DCF Sensitivity:** ±1% WACC thay đổi giá trị ~15–25%. Terminal value thường chiếm 60–80% tổng value.

## Margin of Safety Guidelines

| MoS (Fair Mid - Current) / Fair Mid | Nhận định |
|--------------------------------------|-----------|
| ≥ 30% | Buy zone — significant discount |
| 10–30% | Fair range — hợp lý để tích lũy |
| 0–10% | Fully priced — limited upside |
| < 0% | Expensive — giá cao hơn fair value |

**Nguyên tắc:** Dùng fair_mid (base case) làm neo. Bear case / bull case là biên rủi ro.
Nhà đầu tư thận trọng dùng bear case làm "floor" kỳ vọng.

## RNAV (REALESTATE only) — Cần Manual Input

RNAV = (Adj. NAV of land bank at market price) + (Completed properties) + (Other assets) − Liabilities

**Bước tính:**
1. Lấy land bank area (m²) từ thuyết minh BCTC hoặc annual report
2. Lấy avg. land price/m² theo khu vực (Hanoi/HCMC tier 1: 50–200 triệu/m²)
3. RNAV land bank = area × price × (1 − discount for entitlement risk ~20–30%)
4. Cộng completed inventory at market + financial investments
5. Trừ net debt

**RNAV typical premium/discount to book VN RE:**
- -20% to +100% tùy chất lượng land bank
- VHM: RNAV premium thường 30–60% above book
- Smaller RE: thường discount to book nếu liquidity kém

**Delegate:** Dùng Codex với input: `equity_b, land_m2, price_per_m2, discount_pct, inventory_b`

## SOTP (CONGLOMERATE) — Cần Manual Input

**Quy trình:**
1. Chia công ty thành N business units (VD: retail, property, food & bev)
2. Value mỗi unit riêng: P/E × EBIT hoặc EV/EBITDA × EBITDA segment
3. Sum all units (total EV)
4. Trừ: net debt tại holding level
5. Apply holding company discount: 15–25% (discount do phức tạp, liquidity thấp hơn)
6. Chia cho số cổ phiếu → giá target/share

**Delegate:** Dùng Codex với input: `[{segment_name, revenue, ebit, target_multiple}]`

## Bear/Base/Bull Multiple Selection Logic

```
P/E bear  = P25 of 8Q historical (or peer median × 0.75)
P/E base  = median of 8Q historical (or peer median)
P/E bull  = P75 of 8Q historical (or peer median × 1.25)
```

**Rationale:**
- P25 = dưới điều kiện thị trường stress / kỳ vọng thấp
- Median = kỳ vọng trung bình của thị trường trong chu kỳ
- P75 = thị trường đang tích cực, câu chuyện tăng trưởng được tin tưởng
