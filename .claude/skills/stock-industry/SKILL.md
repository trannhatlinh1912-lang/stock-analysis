---
name: stock-industry
description: |
  Phân tích ngành và chu kỳ ngành của cổ phiếu Việt Nam. Trigger khi user gõ
  /stock-industry, hỏi về "phân tích ngành", "chu kỳ ngành", "ngành [tên ngành]",
  "industry cycle", "sector analysis". Skill nhận ticker (HPG, VCB...) hoặc tên
  ngành (thép, ngân hàng, bất động sản). Lấy data từ vnstock + yfinance qua Python
  scripts (delegate Codex để tiết kiệm token). Output 7 sections: industry_overview,
  cycle_position, supply_demand, competition, sector_margin, outlook, key_risks.
  Mỗi section label rõ [FACT] / [ASSUMPTION] / [CONCLUSION]. Không bịa số liệu.
  Dùng sau /stock-macro để phân tích sâu hơn về ngành cụ thể.
---

# stock-industry

## Bước 1: Parse Input

Xác định input từ user:
- **Ticker** (VD: HPG, VCB, NVL) → dùng trực tiếp
- **Tên ngành tiếng Việt** → map sang ticker đại diện:

| Tên ngành | Ticker đại diện |
|-----------|----------------|
| thép / steel | HPG |
| ngân hàng / bank | VCB |
| bất động sản / BĐS / real estate | VHM |
| chứng khoán / securities | SSI |
| bán lẻ / retail | MWG |
| năng lượng / dầu khí / energy | GAS |
| dược / pharma | DHG |
| công nghệ / tech | FPT |
| phân bón / fertilizer | DPM |
| xây dựng / construction | CTD |

Nếu không khớp: hỏi user cung cấp ticker cụ thể.

## Bước 2: Fetch Data (dùng Codex)

Delegate cho Codex để không tốn context window:

```
Dùng /codex:rescue với prompt:
"Run: python ~/.claude/workspace/stock-analysis/scripts/fetch_industry.py --ticker {TICKER}
 Report only: (1) cache hit or fresh fetch, (2) path of output JSON file, (3) industry name detected.
 Do NOT print the JSON content."
```

Fallback nếu không có Codex:
```bash
cd ~/.claude/workspace/stock-analysis && python scripts/fetch_industry.py --ticker {TICKER}
```

## Bước 3: Generate Report (dùng Codex)

```
Dùng /codex:rescue với prompt:
"Run: python ~/.claude/workspace/stock-analysis/scripts/generate_industry_report.py --snapshot {SNAPSHOT_PATH}
 Print only the lines starting from '---SNAPSHOT_JSON---' to end of output."
```

Fallback:
```bash
cd ~/.claude/workspace/stock-analysis && python scripts/generate_industry_report.py --snapshot {SNAPSHOT_PATH}
```

Lấy JSON từ output (phần sau `---SNAPSHOT_JSON---`).

## Bước 4: Viết Phân tích

Đọc JSON snapshot (compact ~3KB). Viết đúng 7 sections — **tổng < 400 chữ**.
Mỗi section BẮT BUỘC có label: `[FACT]` (từ data), `[ASSUMPTION]` (suy luận), `[CONCLUSION]` (nhận định).

```
## industry_overview [FACT]
Ngành: [tên] | Peers phân tích: [danh sách] | Market context: [1 câu]

## cycle_position [FACT + CONCLUSION]
Giai đoạn: 🔴 ĐÁY / 🟠 HỒI PHỤC / 🟢 TĂNG TRƯỞNG / 🟡 ĐỈNH / ⚫ SUY GIẢM
Bằng chứng: revenue_trend=[...], margin_trend=[...], price_vs_index=[...]

## supply_demand [FACT + ASSUMPTION]
[1-2 câu về cung cầu dựa trên data có được; ghi rõ phần nào là assumption]

## competition [FACT]
Top peers: [bảng nhỏ tên + net_margin + revenue_growth]
Cạnh tranh: [phân tán / tập trung]

## sector_margin [FACT]
Sector avg gross_margin: X% | net_margin: Y%
Trend: [mở rộng / ổn định / co lại] so với 4Q trước

## outlook [CONCLUSION]
[2-3 câu: triển vọng 6-12 tháng, catalyst chính]

## key_risks [CONCLUSION]
1. [rủi ro 1]
2. [rủi ro 2]
3. [rủi ro 3]
```

Nguyên tắc token: không giải thích lại số liệu thô — chỉ nhận định xu hướng và nhân quả.

## Bước 5: Lưu NotebookLM (tùy chọn)

Hỏi user: "Lưu báo cáo vào NotebookLM không?"
Nếu đồng ý:
```
Dùng /notebooklm:
"Add file ~/.claude/workspace/stock-analysis/output/industry_report_{TICKER}_{TODAY}.md
 as a source to notebook named 'Stock Industry History'.
 Create the notebook if it doesn't exist."
```

## Tham khảo

- Ngưỡng chu kỳ ngành: `~/.claude/workspace/stock-analysis/references/industry_cycles.md`
- Chỉ đọc khi cần tra ngưỡng cụ thể (không load mặc định)
