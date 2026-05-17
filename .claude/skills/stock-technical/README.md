# stock-technical — Run guide

Three modules, run in order. Example with `GAS`.

## Install

```bash
pip install vnstock pandas numpy
```

## Step 1 — Fetch OHLCV + corporate actions + audit adjusted price

```bash
python scripts/fetch_price_audit.py --symbol GAS --start 2023-01-01 --end 2026-05-18
```

Outputs:

- `data/GAS_price_VCI.csv` — daily OHLCV from VCI.
- `data/GAS_price_TCBS.csv` — only when the source is supported by the installed `vnstock` version; otherwise reported as `missing_data` in the audit.
- `data/GAS_corporate_actions.csv` — events (`exright_date`, `value_per_share`, …).
- `reports/GAS_data_quality_report.md` — `adjusted_price_status`, `long_ma_confidence`, gap audit, conclusion.

## Step 2 — Calculate indicators

```bash
python scripts/indicator_engine.py --csv data/GAS_price_VCI.csv --symbol GAS
```

Outputs:

- `data/GAS_indicators.csv` — full table, ~60 indicator columns.
- `reports/GAS_indicator_report.md` — snapshot + interpretation for the latest row.

## Step 3 — Decision snapshot

```bash
python scripts/decision_framework.py --csv data/GAS_indicators.csv --symbol GAS
```

Outputs:

- `data/GAS_decision_snapshot.json` — structured decision.
- `reports/GAS_technical_decision.md` — Vietnamese markdown report.

## Rules to remember

- Do not skip step 1. If `adjusted_price_status != "confirmed"`, treat SMA100/SMA200 as medium_low confidence.
- Never fabricate. Missing data is labelled `missing_data` in every report.
- `BREAKOUT_WITH_EXHAUSTION_RISK` caps `confidence_score` at 68 and forbids large chase-buys.
- Resistance levels within 0.3% are merged into `confluence_resistance` zones (no source is dropped).
- Never output "STRONG BUY" from technical analysis alone — always combine with fundamentals + macro.
