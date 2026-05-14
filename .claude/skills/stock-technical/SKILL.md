---
name: stock-technical
description: |
  Phân tích kỹ thuật và dòng tiền cho cổ phiếu Việt Nam để hỗ trợ timing mua/bán.
  KHÔNG thay thế phân tích cơ bản — dùng SAU /stock-valuation để xác nhận điểm vào/ra.
  Trigger khi user gõ /stock-technical, hỏi về "phân tích kỹ thuật", "chart", "RSI",
  "MACD", "MA", "hỗ trợ kháng cự", "dòng tiền", "khối ngoại", "timing", "điểm vào",
  "điểm ra", "tín hiệu mua/bán", "technical analysis", "money flow", "foreign flow",
  "volume analysis", "momentum", "trend", "breakout", "bollinger", "signal kỹ thuật",
  "tín hiệu kỹ thuật", "vùng tích lũy", "vùng phân phối".
  Skill nhận ticker (HPG, VCB...) hoặc tên công ty. Lấy OHLCV + foreign flow từ vnstock,
  tính TA indicators qua pandas_ta, delegate Codex để tiết kiệm token.
  Output 7 sections: price_trend, trend_indicators, momentum_signals, volume_analysis,
  money_flow, key_levels, timing_signal. Mỗi section label rõ [FACT] / [ASSUMPTION] /
  [CONCLUSION]. Không bịa số liệu. Không khuyến nghị mua/bán — chỉ báo Timing Zone
  (ACCUMULATION / WATCH / DISTRIBUTION). Dùng sau /stock-valuation.
---

# stock-technical

## Bước 1: Parse Input

Xác định ticker từ input:
- **Ticker trực tiếp** (HPG, VCB, FPT...) → dùng luôn
- **Tên công ty/ngành** → map sang ticker đại diện (hỏi user nếu không chắc):

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

## Bước 2: Fetch Data (dùng Codex)

```
Dùng /codex:rescue với prompt:
"Run: python ~/.claude/workspace/stock-analysis/scripts/fetch_technical.py --ticker {TICKER}
 Report only: (1) cache hit or fresh fetch, (2) path of output JSON file.
 Do NOT print the JSON content."
```

Fallback nếu không có Codex:
```bash
cd ~/.claude/workspace/stock-analysis && python scripts/fetch_technical.py --ticker {TICKER}
```

Ghi nhận đường dẫn: `data/technical_snapshot_{TICKER}_{DATE}.json`

## Bước 3: Generate Report (dùng Codex)

```
Dùng /codex:rescue với prompt:
"Run: python ~/.claude/workspace/stock-analysis/scripts/generate_technical_report.py --snapshot {SNAPSHOT_PATH}
 Print only the lines starting from '---SNAPSHOT_JSON---' to end of output."
```

Fallback:
```bash
cd ~/.claude/workspace/stock-analysis && python scripts/generate_technical_report.py --snapshot {SNAPSHOT_PATH}
```

Lấy compact JSON từ output (phần sau `---SNAPSHOT_JSON---`).

## Bước 4: Viết 7 Sections Phân tích

Đọc compact JSON (~3 KB). Viết đúng 7 sections — **tổng < 450 từ**.
BẮT BUỘC label: `[FACT]` (từ data API), `[ASSUMPTION]` (suy luận), `[CONCLUSION]` (nhận định).
Thiếu data → ghi `[missing_data]`, không bịa số.

```
## price_trend [FACT]
{TICKER} — {DATE} | Giá: {price} VND | 1D: {+/-x}% | 1M: {+/-x}% | 3M: {+/-x}%
52W High: {x} | 52W Low: {x} | vs 52W High: {-x}%
[FACT] Xu hướng 3 tháng: [tăng/giảm/đi ngang] — 1 câu mô tả ngắn gọn.

## trend_indicators [FACT + CONCLUSION]
MA20: {x} | MA50: {x} | MA200: {x} | EMA20: {x}
Giá vs MA20: {+/-x}% | Giá vs MA200: {+/-x}%
MA20 vs MA50: [Golden Cross / Death Cross / Neutral]
[CONCLUSION]: Xu hướng = [TĂNG / GIẢM / TRUNG TÍNH] — 1 câu lý do cụ thể.

## momentum_signals [FACT + CONCLUSION]
RSI(14): {x} [{Oversold <30 / Neutral / Overbought >70}]
MACD(12,26,9): {x} | Signal: {x} | Histogram: {+/-x} [{Bullish/Bearish/Neutral}]
Stoch(14,3): K={x} D={x} [{Oversold/Neutral/Overbought}]
[CONCLUSION]: Momentum = [MẠNH / TRUNG TÍNH / YẾU] — 1 câu.

## volume_analysis [FACT + CONCLUSION]
Volume hôm nay: {x}M cp | MA20 Vol: {x}M cp | Tỷ lệ: {x}×
OBV trend: [rising/falling/flat]
[CONCLUSION]: Volume = [XÁC NHẬN xu hướng / MÂU THUẪN / TRUNG TÍNH] — 1 câu.

## money_flow [FACT + CONCLUSION]
Khối ngoại 10D: Net {+/-x} B VND (Mua {x} B / Bán {x} B)
Sở hữu NN: {x}% | Room còn: {x}%
[CONCLUSION]: Khối ngoại = [MUA RÒNG / BÁN RÒNG / TRUNG TÍNH] — tác động ngắn hạn.

## key_levels [FACT]
Kháng cự 1: {x} | Kháng cự 2: {x}
Hỗ trợ 1: {x}  | Hỗ trợ 2:  {x}
Pivot: {x} | BB Upper: {x} | BB Lower: {x} | ATR(14): {x}
R/R từ giá hiện tại: +{x}% → R1 / -{x}% → S1

## timing_signal [CONCLUSION]
⏱ Timing Zone: [🟢 ACCUMULATION / 🟡 WATCH / 🔴 DISTRIBUTION]
| Signal     | Verdict   |
|------------|-----------|
| Trend      | {BULLISH/NEUTRAL/BEARISH} |
| Momentum   | {BULLISH/NEUTRAL/BEARISH} |
| Volume     | {CONFIRM/NEUTRAL/DIVERGE} |
| Money Flow | {INFLOW/NEUTRAL/OUTFLOW}  |
[CONCLUSION] 2 câu: vị trí giá hiện tại so với S/R + điều kiện cần để signal đổi chiều.
```

Nguyên tắc token: không diễn giải lại từng số thô — chỉ nhận định xu hướng và ý nghĩa.

## Bước 5: Lazy-load Thresholds (khi cần verify)

Chỉ đọc khi cần xác nhận ngưỡng cụ thể (RSI vùng 45-65, MACD gần zero, v.v.):
```
~/.claude/workspace/stock-analysis/references/technical_analysis.md
```

## Bước 6: Xác nhận & Lưu NotebookLM (tùy chọn)

Thông báo: `output/technical_report_{TICKER}_{TODAY}.md`

Hỏi user: "Lưu báo cáo vào NotebookLM không?"

Nếu đồng ý:
```
Dùng /notebooklm:
"Add file ~/.claude/workspace/stock-analysis/output/technical_report_{TICKER}_{TODAY}.md
 as a source to notebook named 'Stock Technical Analysis History'.
 Create the notebook if it doesn't exist."
```
