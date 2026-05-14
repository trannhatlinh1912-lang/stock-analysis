# Risk Report: BSR — 2026-05-15

```json
{
  "ticker": "BSR",
  "date": "2026-05-15",
  "industry": "ENERGY",
  "risk_summary": {
    "total_risks": 1,
    "high_severity": 0,
    "medium_severity": 0,
    "thesis_breakers": 0
  },
  "ownership_risk": {
    "score": 0,
    "severity": "LOW",
    "top1_pct": null,
    "top5_pct": null,
    "state_pct": null,
    "foreign_pct": null,
    "hhi_top5": null,
    "flags": []
  },
  "dilution_risk": {
    "score": 0,
    "severity": "LOW",
    "current_shares_m": null,
    "dilution_pct_1y": null,
    "flags": []
  },
  "debt_risk": {
    "score": 1,
    "severity": "LOW",
    "de_ratio": null,
    "coverage": null,
    "net_debt_b": null,
    "total_debt_b": null,
    "flags": [
      "Interest coverage không tính được [missing_data]"
    ]
  },
  "audit_risk": {
    "score": 1,
    "severity": "MEDIUM",
    "auditor": null,
    "flags": [
      "Không có thông tin kiểm toán viên [missing_data]"
    ]
  },
  "legal_risk": {
    "score": 0,
    "severity": "LOW",
    "flags": [
      "Không phát hiện sự kiện pháp lý qua API events [cần bổ sung news crawl]"
    ]
  },
  "events_alerts": [],
  "shareholders_top5": [],
  "risk_matrix": [
    {
      "risk": "Rủi ro nợ vay / Refinancing",
      "severity": "LOW",
      "probability": "LOW",
      "mechanism": "Lãi suất tăng hoặc lợi nhuận giảm → không đủ trả lãi → restructure/default",
      "early_signal": "Coverage giảm dưới 2×, tăng vay ngắn hạn, trái phiếu đến hạn"
    }
  ],
  "thesis_breakers": [],
  "data_warnings": [
    "overview_fetch_failed: No module named 'vnstock3'",
    "shareholders_fetch_failed: No module named 'vnstock3'",
    "events_fetch_failed: No module named 'vnstock3'",
    "shares_trend_fetch_failed: No module named 'vnstock3'",
    "debt_fetch_failed: No module named 'vnstock3'",
    "auditor_info_missing",
    "ownership_data_missing",
    "debt_ratio_missing",
    "interest_coverage_missing"
  ]
}
```
