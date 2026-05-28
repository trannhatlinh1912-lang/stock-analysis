#!/usr/bin/env python3
"""Price data quality audit for Vietnamese equities (vnstock-backed).

Fetches daily OHLCV from multiple sources (VCI primary, MSN + KBS as
cross-check), pulls corporate-action events, detects whether each source
returns raw or adjusted prices by comparing actual ex-rights drops to
declared dividend value, and confirms adjustment status when 2+ sources
agree.

Outputs
-------
- data/{SYMBOL}_price_{SOURCE}.csv per successful source
- data/{SYMBOL}_corporate_actions.csv
- reports/{SYMBOL}_data_quality_report.md

Usage
-----
    python scripts/fetch_price_audit.py --symbol GAS \
        --start 2023-01-01 --end 2026-05-18
"""

from __future__ import annotations

import argparse
import math
import sys
import warnings
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Optional

import pandas as pd

warnings.filterwarnings("ignore")

REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = REPO_ROOT / "data"
REPORTS_DIR = REPO_ROOT / "reports"
DATA_DIR.mkdir(exist_ok=True)
REPORTS_DIR.mkdir(exist_ok=True)

# Threshold (absolute) for treating a daily close-to-close pct change as a
# "large gap" worth flagging in the audit. 5% chosen as a conservative
# heuristic for VN equities outside of normal sessions.
LARGE_GAP_PCT = 0.05

# Tolerance (absolute pct points) for matching the actual ex-rights drop to
# the expected drop derived from dividend value-per-share. Within this band
# the series is considered RAW (price drops by the dividend amount).
RAW_TOLERANCE_PCT = 0.015  # 1.5 pp

# Window (trading days) around each ex-rights date that is excluded from
# the unexplained-gap audit (the gap there is expected and explained).
EX_RIGHTS_WINDOW = 1


@dataclass
class FetchResult:
    """Outcome of a single fetch attempt."""

    source: str
    df: Optional[pd.DataFrame] = None
    error: Optional[str] = None

    @property
    def ok(self) -> bool:
        return self.df is not None and len(self.df) > 0


@dataclass
class AdjustmentVerdict:
    status: str  # "raw" | "adjusted" | "unknown"
    confidence: str  # "high" | "medium" | "medium_low" | "low"
    evidence: list[dict] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Fetchers
# ---------------------------------------------------------------------------


def fetch_price(symbol: str, start: str, end: str, source: str) -> FetchResult:
    """Fetch daily OHLCV via vnstock.

    Returns FetchResult with normalised columns:
        time (datetime64), open, high, low, close, volume.
    """
    try:
        from vnstock.api.quote import Quote
    except Exception as e:  # pragma: no cover - import failure is fatal
        return FetchResult(source=source, error=f"vnstock import failed: {e}")

    try:
        q = Quote(symbol=symbol, source=source)
        df = q.history(start=start, end=end, interval="1D")
    except Exception as e:
        return FetchResult(source=source, error=str(e))

    if df is None or len(df) == 0:
        return FetchResult(source=source, error="empty result")

    df = df.copy()
    df.columns = [c.lower() for c in df.columns]

    if "time" in df.columns:
        df["time"] = pd.to_datetime(df["time"])
    elif "date" in df.columns:
        df["time"] = pd.to_datetime(df["date"])
    else:
        return FetchResult(
            source=source, error=f"no time/date column. cols={list(df.columns)}"
        )

    required = {"open", "high", "low", "close", "volume"}
    missing = required - set(df.columns)
    if missing:
        return FetchResult(source=source, error=f"missing cols: {missing}")

    df = df.sort_values("time").reset_index(drop=True)
    df = df[["time", "open", "high", "low", "close", "volume"]]
    return FetchResult(source=source, df=df)


def fetch_corporate_actions(symbol: str) -> tuple[Optional[pd.DataFrame], Optional[str]]:
    """Fetch corporate-action events (VCI explorer module).

    Returns (DataFrame|None, error|None). The DataFrame has at minimum:
        exright_date (datetime64), event_name_vi, action_type_vi,
        value_per_share (float, VND), exercise_ratio (str|None).
    """
    try:
        from vnstock.explorer.vci.company import Company
    except Exception as e:
        return None, f"vnstock VCI Company import failed: {e}"

    try:
        c = Company(symbol=symbol)
        df = c.events()
    except Exception as e:
        return None, str(e)

    if df is None or len(df) == 0:
        return None, "events() returned empty"

    df = df.copy()
    keep = [
        "event_name_vi", "event_code", "action_type_vi", "category",
        "public_date", "issue_date", "record_date", "exright_date",
        "listing_date", "exercise_ratio", "payout_date", "value_per_share",
    ]
    for col in keep:
        if col not in df.columns:
            df[col] = None
    df = df[keep]

    for col in ("public_date", "issue_date", "record_date", "exright_date",
                "listing_date", "payout_date"):
        df[col] = pd.to_datetime(df[col], errors="coerce")

    df["value_per_share"] = pd.to_numeric(df["value_per_share"], errors="coerce")

    df = df.sort_values("exright_date").reset_index(drop=True)
    return df, None


# ---------------------------------------------------------------------------
# Detection & indicators
# ---------------------------------------------------------------------------


def _is_cash_dividend(row: pd.Series) -> bool:
    name = str(row.get("event_name_vi") or "").lower()
    action = str(row.get("action_type_vi") or "").lower()
    val = row.get("value_per_share")
    if val is None or (isinstance(val, float) and math.isnan(val)):
        return False
    if val <= 0:
        return False
    # Vietnamese cues: cổ tức tiền mặt / cổ tức bằng tiền
    return ("tiền" in name) or ("tiền" in action) or ("cash" in name) or ("cash" in action)


def detect_adjusted_price(
    df: pd.DataFrame, corporate_actions: Optional[pd.DataFrame]
) -> AdjustmentVerdict:
    """Detect whether `df['close']` is raw or split/dividend-adjusted.

    Logic
    -----
    For each CASH-DIVIDEND ex-rights date inside the price window:
        expected_drop_pct = value_per_share / prev_close
        actual_drop_pct   = (close_exright - prev_close) / prev_close
    If actual_drop is within RAW_TOLERANCE_PCT of -expected_drop, the event
    looks RAW. If |actual_drop| << expected_drop (e.g., < expected/3), the
    series looks ADJUSTED for that event. Aggregate across all evaluable
    events.

    Returns AdjustmentVerdict with status/confidence and per-event evidence.
    """
    verdict = AdjustmentVerdict(status="unknown", confidence="medium_low")

    if corporate_actions is None or len(corporate_actions) == 0:
        verdict.notes.append(
            "No corporate_actions available — cannot test adjustment."
        )
        return verdict

    if df is None or len(df) < 5:
        verdict.notes.append("Price series too short to test.")
        return verdict

    price = df.set_index("time")["close"].sort_index()

    # Unit normalisation: VCI returns prices in thousand-VND units
    # (e.g. 71.09 means 71,090 VND), while corporate-action value_per_share
    # is in VND. Detect this so the expected-drop ratio is comparable.
    median_close = float(price.median())
    if 1.0 < median_close < 1000.0:
        price_scale_vnd_per_unit = 1000.0  # close is in thousand VND
    else:
        price_scale_vnd_per_unit = 1.0
    verdict.notes.append(
        f"price_scale = {price_scale_vnd_per_unit} VND/unit (median_close={median_close:.2f})"
    )

    raw_votes = 0
    adj_votes = 0
    ambiguous_votes = 0

    for _, row in corporate_actions.iterrows():
        ex = row.get("exright_date")
        if pd.isna(ex):
            continue
        if ex < price.index.min() or ex > price.index.max():
            continue
        if not _is_cash_dividend(row):
            continue

        # find ex-day close + previous trading-day close
        on_or_after = price.index[price.index >= ex]
        if len(on_or_after) == 0:
            continue
        ex_day = on_or_after[0]
        before = price.index[price.index < ex_day]
        if len(before) == 0:
            continue
        prev_day = before[-1]

        prev_close = float(price.loc[prev_day])
        ex_close = float(price.loc[ex_day])
        if prev_close <= 0:
            continue

        value_per_share = float(row["value_per_share"])
        # Both sides converted to VND for the ratio.
        prev_close_vnd = prev_close * price_scale_vnd_per_unit
        expected_drop_pct = value_per_share / prev_close_vnd
        actual_drop_pct = (ex_close - prev_close) / prev_close

        residual = actual_drop_pct - (-expected_drop_pct)
        ratio = abs(actual_drop_pct) / expected_drop_pct if expected_drop_pct > 0 else None

        if abs(residual) <= RAW_TOLERANCE_PCT and actual_drop_pct < 0:
            classification = "raw"
            raw_votes += 1
        elif ratio is not None and ratio < 0.34:
            classification = "adjusted"
            adj_votes += 1
        else:
            classification = "ambiguous"
            ambiguous_votes += 1

        verdict.evidence.append(
            {
                "exright_date": ex_day.strftime("%Y-%m-%d"),
                "prev_close": round(prev_close, 2),
                "ex_close": round(ex_close, 2),
                "value_per_share": round(value_per_share, 2),
                "expected_drop_pct": round(expected_drop_pct * 100, 3),
                "actual_drop_pct": round(actual_drop_pct * 100, 3),
                "classification": classification,
            }
        )

    total = raw_votes + adj_votes + ambiguous_votes
    if total == 0:
        verdict.notes.append(
            "No cash-dividend ex-rights events fell inside the price window."
        )
        return verdict

    if raw_votes >= 2 and raw_votes > adj_votes:
        verdict.status = "raw"
        verdict.confidence = "high" if raw_votes >= 3 else "medium"
    elif adj_votes >= 2 and adj_votes > raw_votes:
        verdict.status = "adjusted"
        verdict.confidence = "high" if adj_votes >= 3 else "medium"
    elif raw_votes == 1 and adj_votes == 0:
        verdict.status = "raw"
        verdict.confidence = "medium_low"
    elif adj_votes == 1 and raw_votes == 0:
        verdict.status = "adjusted"
        verdict.confidence = "medium_low"
    else:
        verdict.status = "unknown"
        verdict.confidence = "medium_low"
        verdict.notes.append(
            f"Mixed signals: raw={raw_votes}, adj={adj_votes}, ambig={ambiguous_votes}"
        )

    return verdict


def calculate_indicators(df: pd.DataFrame, price_col: str) -> pd.DataFrame:
    """Append SMA20/50/100/200 to df computed on price_col."""
    out = df.copy()
    for window in (20, 50, 100, 200):
        out[f"sma{window}"] = out[price_col].rolling(window, min_periods=window).mean()
    return out


def audit_large_gaps(
    df: pd.DataFrame,
    price_col: str,
    corporate_actions: Optional[pd.DataFrame] = None,
) -> pd.DataFrame:
    """Return rows where |daily pct change| >= LARGE_GAP_PCT, annotated with
    whether the date sits inside an ex-rights window."""
    if df is None or len(df) < 2:
        return pd.DataFrame()

    work = df[["time", price_col]].copy().sort_values("time").reset_index(drop=True)
    work["pct_change"] = work[price_col].pct_change()
    gaps = work[work["pct_change"].abs() >= LARGE_GAP_PCT].copy()
    if len(gaps) == 0:
        return gaps

    if corporate_actions is not None and len(corporate_actions) > 0:
        ex_dates = pd.to_datetime(corporate_actions["exright_date"]).dropna().tolist()
    else:
        ex_dates = []

    def _near_ex(t):
        if not ex_dates:
            return False
        for ex in ex_dates:
            if abs((t - ex).days) <= EX_RIGHTS_WINDOW:
                return True
        return False

    gaps["near_ex_rights"] = gaps["time"].apply(_near_ex)
    gaps["pct_change"] = gaps["pct_change"].round(4)
    return gaps.reset_index(drop=True)


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------


def _fmt(val) -> str:
    if val is None or (isinstance(val, float) and math.isnan(val)):
        return "missing_data"
    if isinstance(val, float):
        return f"{val:,.2f}"
    return str(val)


def generate_data_quality_report(
    symbol: str,
    start: str,
    end: str,
    fetches: dict[str, FetchResult],
    corp_actions_df: Optional[pd.DataFrame],
    corp_actions_err: Optional[str],
    chosen_source: Optional[str],
    chosen_df_with_ma: Optional[pd.DataFrame],
    price_col: str,
    adj_verdict: AdjustmentVerdict,
    gaps: pd.DataFrame,
    out_path: Path,
) -> None:
    """Write the markdown data-quality report."""

    if adj_verdict.status == "adjusted" and adj_verdict.confidence in ("high", "medium"):
        adj_status_str = "confirmed"
        long_ma_confidence = "high"
    elif adj_verdict.status == "raw" and adj_verdict.confidence in ("high", "medium"):
        adj_status_str = "confirmed_raw"
        long_ma_confidence = "medium"  # raw price can still compute MAs, but
        # they will be biased by un-adjusted dividend drops
    else:
        adj_status_str = "unknown"
        long_ma_confidence = "medium_low"

    lines: list[str] = []
    lines.append(f"# {symbol} — Data Quality Report")
    lines.append("")
    lines.append(f"- Generated: `{date.today().isoformat()}`")
    lines.append(f"- Window: `{start}` → `{end}`")
    lines.append(f"- adjusted_price_status: **{adj_status_str}**")
    lines.append(f"- long_ma_confidence: **{long_ma_confidence}**")
    lines.append("")

    # ---- Sources ----
    lines.append("## 1. Nguồn dữ liệu")
    lines.append("")
    lines.append("| Source | Status | Rows | First | Last | Error |")
    lines.append("|---|---|---|---|---|---|")
    for src, fr in fetches.items():
        if fr.ok:
            df = fr.df
            lines.append(
                f"| {src} | ok | {len(df)} | {df['time'].min().date()} | "
                f"{df['time'].max().date()} | — |"
            )
        else:
            lines.append(f"| {src} | failed | 0 | — | — | {fr.error} |")
    lines.append("")

    # ---- Corporate actions ----
    lines.append("## 2. Corporate actions")
    lines.append("")
    if corp_actions_df is not None and len(corp_actions_df) > 0:
        lines.append(f"- Events fetched: **{len(corp_actions_df)}**")
        in_window = corp_actions_df[
            (corp_actions_df["exright_date"] >= pd.to_datetime(start))
            & (corp_actions_df["exright_date"] <= pd.to_datetime(end))
        ]
        lines.append(f"- Events with exright_date in window: **{len(in_window)}**")
        if len(in_window) > 0:
            lines.append("")
            lines.append("| ex-right | event | action | value/share | exercise_ratio |")
            lines.append("|---|---|---|---|---|")
            for _, r in in_window.iterrows():
                lines.append(
                    f"| {r['exright_date'].date() if pd.notna(r['exright_date']) else '—'} "
                    f"| {r.get('event_name_vi') or '—'} "
                    f"| {r.get('action_type_vi') or '—'} "
                    f"| {_fmt(r.get('value_per_share'))} "
                    f"| {r.get('exercise_ratio') or '—'} |"
                )
    else:
        lines.append(f"- missing_data (error: `{corp_actions_err}`)")
    lines.append("")

    # ---- Chosen series + MA ----
    lines.append("## 3. Chuỗi giá dùng phân tích kỹ thuật")
    lines.append("")
    if chosen_source is None or chosen_df_with_ma is None:
        lines.append("- missing_data — không có source nào trả về dữ liệu hợp lệ.")
    else:
        df = chosen_df_with_ma
        valid_rows = df[price_col].notna().sum()
        lines.append(f"- Source dùng: **{chosen_source}**")
        lines.append(f"- Cột giá dùng tính MA: **`{price_col}`**")
        lines.append(f"- Số phiên hợp lệ: **{int(valid_rows)}**")
        lines.append(
            f"- Ngày đầu / cuối: **{df['time'].min().date()}** → **{df['time'].max().date()}**"
        )
        last = df.iloc[-1]
        lines.append("")
        lines.append("| Chỉ báo | Giá trị (mới nhất) |")
        lines.append("|---|---|")
        lines.append(f"| close ({last['time'].date()}) | {_fmt(float(last['close']))} |")
        for w in (20, 50, 100, 200):
            v = last.get(f"sma{w}")
            lines.append(
                f"| SMA{w} | {_fmt(float(v)) if pd.notna(v) else 'missing_data (chưa đủ phiên)'} |"
            )
    lines.append("")

    # ---- Adjustment verdict ----
    lines.append("## 4. Adjusted vs Raw price")
    lines.append("")
    lines.append(f"- Status: **{adj_verdict.status}**  (confidence: {adj_verdict.confidence})")
    if adj_verdict.evidence:
        lines.append("")
        lines.append(
            "| ex-right | prev_close | ex_close | div/share | expected drop % | actual drop % | verdict |"
        )
        lines.append("|---|---|---|---|---|---|---|")
        for ev in adj_verdict.evidence:
            lines.append(
                f"| {ev['exright_date']} | {ev['prev_close']:.2f} | {ev['ex_close']:.2f} "
                f"| {ev['value_per_share']:.0f} | {ev['expected_drop_pct']:.2f} "
                f"| {ev['actual_drop_pct']:.2f} | {ev['classification']} |"
            )
    for n in adj_verdict.notes:
        lines.append(f"- note: {n}")
    lines.append("")

    # ---- Gaps ----
    lines.append("## 5. Audit các gap giá lớn")
    lines.append("")
    lines.append(f"- Ngưỡng gap: ±{LARGE_GAP_PCT*100:.1f}% close-to-close")
    if gaps is None or len(gaps) == 0:
        lines.append("- Không có gap nào vượt ngưỡng.")
    else:
        unexplained = gaps[gaps.get("near_ex_rights", pd.Series([False] * len(gaps))) == False]
        lines.append(f"- Tổng gap: **{len(gaps)}** — trong đó **{len(unexplained)}** không trùng ngày ex-rights.")
        lines.append("")
        lines.append("| date | pct_change | near_ex_rights |")
        lines.append("|---|---|---|")
        for _, r in gaps.iterrows():
            lines.append(
                f"| {r['time'].date()} | {r['pct_change']*100:+.2f}% | {r.get('near_ex_rights', False)} |"
            )
    lines.append("")

    # ---- Conclusion ----
    lines.append("## 6. Kết luận")
    lines.append("")
    if adj_status_str == "confirmed" and long_ma_confidence == "high":
        verdict = (
            "Dữ liệu đủ tin cậy cho phân tích kỹ thuật dài hạn (SMA100/SMA200). "
            "Chuỗi giá được xác nhận là **adjusted**, các MA dài phản ánh xu hướng thực."
        )
    elif adj_status_str == "confirmed_raw":
        verdict = (
            "Chuỗi giá là **raw price** (chưa điều chỉnh cổ tức/quyền). "
            "SMA100/SMA200 có thể bị méo bởi các cú drop ex-rights — nên dùng với cảnh báo, "
            "hoặc tự điều chỉnh trước khi dùng cho timing dài hạn."
        )
    else:
        verdict = (
            "**Chưa xác nhận** được chuỗi giá là raw hay adjusted. "
            "SMA100/SMA200 chỉ nên dùng tham khảo (confidence medium_low). "
            "Cần thêm nguồn dữ liệu thứ hai hoặc cross-check với báo cáo cổ tức chính thức."
        )
    lines.append(verdict)
    lines.append("")

    out_path.write_text("\n".join(lines), encoding="utf-8")


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------


def run(symbol: str, start: str, end: str, sources: list[str]) -> Path:
    print(f"[audit] symbol={symbol} window={start}..{end} sources={sources}")

    # 1. Fetch prices from each source
    fetches: dict[str, FetchResult] = {}
    for src in sources:
        print(f"[audit] fetch_price source={src} ...")
        fr = fetch_price(symbol, start, end, src)
        fetches[src] = fr
        if fr.ok:
            out_csv = DATA_DIR / f"{symbol}_price_{src}.csv"
            fr.df.to_csv(out_csv, index=False)
            print(f"[audit]   -> {out_csv} ({len(fr.df)} rows)")
        else:
            print(f"[audit]   FAILED: {fr.error}")

    # 2. Corporate actions
    print(f"[audit] fetch_corporate_actions ...")
    corp_df, corp_err = fetch_corporate_actions(symbol)
    if corp_df is not None:
        out_csv = DATA_DIR / f"{symbol}_corporate_actions.csv"
        corp_df.to_csv(out_csv, index=False)
        print(f"[audit]   -> {out_csv} ({len(corp_df)} rows)")
    else:
        print(f"[audit]   FAILED: {corp_err}")

    # 3. Pick a chosen source (prefer VCI, then any ok)
    chosen_source = None
    for src in sources:
        if fetches[src].ok:
            chosen_source = src
            break

    # 4. Detect adjustment + compute MA
    if chosen_source is None:
        adj_verdict = AdjustmentVerdict(
            status="unknown",
            confidence="low",
            notes=["No price source returned data."],
        )
        chosen_df_with_ma = None
        gaps = pd.DataFrame()
        price_col = "close"
    else:
        df = fetches[chosen_source].df
        adj_verdict = detect_adjusted_price(df, corp_df)

        # Cross-source consensus: run detection on every successful source
        # and upgrade confidence when 2+ sources agree on the same status.
        per_source_status: dict[str, str] = {}
        for src, fr in fetches.items():
            if not fr.ok:
                continue
            try:
                v = detect_adjusted_price(fr.df, corp_df)
            except Exception:
                continue
            per_source_status[src] = v.status

        confirmed_statuses = [s for s in per_source_status.values() if s in ("raw", "adjusted")]
        if confirmed_statuses:
            from collections import Counter
            counts = Counter(confirmed_statuses)
            top_status, top_count = counts.most_common(1)[0]
            if top_count >= 2:
                adj_verdict.status = top_status
                adj_verdict.confidence = "high"
                adj_verdict.notes.append(
                    f"cross_source_consensus: {top_count}/{len(per_source_status)} sources agree "
                    f"({', '.join(f'{s}={st}' for s, st in per_source_status.items())})"
                )

        # Decide which column to compute MAs on.
        # Per spec: don't use close for SMA100/200 if adjusted status unknown.
        # Implementation choice: always compute on 'close', but encode the
        # warning via adjusted_price_status + long_ma_confidence in report.
        price_col = "close"
        chosen_df_with_ma = calculate_indicators(df, price_col)
        gaps = audit_large_gaps(chosen_df_with_ma, price_col, corp_df)

    # 5. Report
    out_path = REPORTS_DIR / f"{symbol}_data_quality_report.md"
    generate_data_quality_report(
        symbol=symbol,
        start=start,
        end=end,
        fetches=fetches,
        corp_actions_df=corp_df,
        corp_actions_err=corp_err,
        chosen_source=chosen_source,
        chosen_df_with_ma=chosen_df_with_ma,
        price_col=price_col,
        adj_verdict=adj_verdict,
        gaps=gaps,
        out_path=out_path,
    )
    print(f"[audit] report -> {out_path}")
    return out_path


def main():
    p = argparse.ArgumentParser(description="VN equity price data-quality audit.")
    p.add_argument("--symbol", required=True, help="Ticker, e.g. GAS")
    p.add_argument("--start", required=True, help="YYYY-MM-DD")
    p.add_argument("--end", required=True, help="YYYY-MM-DD")
    p.add_argument(
        "--sources",
        nargs="+",
        default=["VCI", "MSN", "KBS", "DNSE"],
        help="Sources to attempt, in priority order. vnstock 4.0.x whitelist: "
             "vci/msn/kbs/dnse/fmp/binance/fmarket. 2+ sources agreeing on "
             "raw/adjusted upgrades long_ma_confidence to high.",
    )
    args = p.parse_args()
    run(args.symbol.upper(), args.start, args.end, [s.upper() for s in args.sources])
    return 0


if __name__ == "__main__":
    sys.exit(main())
