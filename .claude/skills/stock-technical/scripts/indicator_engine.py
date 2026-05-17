#!/usr/bin/env python3
"""Technical indicator engine for adjusted daily OHLCV.

Reads a CSV produced by ``fetch_price_audit.py`` (e.g.
``data/GAS_price_VCI.csv``) whose adjusted_price_status has been confirmed,
computes a full suite of indicators using only pandas / numpy, dumps the
per-row table to ``data/{SYMBOL}_indicators.csv`` and writes a markdown
snapshot + interpretation to ``reports/{SYMBOL}_indicator_report.md``.

Indicator groups
----------------
1. Trend         — SMA20/50/100/200, EMA20/50, alignment, golden cross, distances
2. Momentum      — RSI14, MACD (12,26,9), Stochastic %K(14)/%D(3)
3. Volatility    — ATR14, BB(20, 2σ), BB position, ATR/Close ratio
4. Volume        — vol_ma20, vol_ratio, up/down-volume 20D, spike flag
5. Money flow    — OBV, OBV slope (20D), MFI14, CMF20
6. Price action  — daily/weekly/monthly/3M/6M returns, 52W high/low + distances
7. S/R           — swing high/low (20/50/100), pivot, ATR-stops (1.5×, 2×)

Run
---
    python scripts/indicator_engine.py --csv data/GAS_price_VCI.csv --symbol GAS
"""

from __future__ import annotations

import argparse
import math
import sys
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = REPO_ROOT / "data"
REPORTS_DIR = REPO_ROOT / "reports"
DATA_DIR.mkdir(exist_ok=True)
REPORTS_DIR.mkdir(exist_ok=True)


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------


def load_ohlcv(csv_path: Path) -> pd.DataFrame:
    """Load OHLCV CSV. Accept ``time`` or ``date`` as the date column."""
    df = pd.read_csv(csv_path)
    df.columns = [c.lower() for c in df.columns]
    if "time" in df.columns:
        df = df.rename(columns={"time": "date"})
    if "date" not in df.columns:
        raise ValueError(f"no date/time column in {csv_path}. cols={list(df.columns)}")

    required = {"date", "open", "high", "low", "close", "volume"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"missing columns: {missing}")

    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date").reset_index(drop=True)
    for col in ("open", "high", "low", "close", "volume"):
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df = df.dropna(subset=["close"]).reset_index(drop=True)
    return df


# ---------------------------------------------------------------------------
# Indicator primitives
# ---------------------------------------------------------------------------


def _sma(s: pd.Series, n: int) -> pd.Series:
    return s.rolling(n, min_periods=n).mean()


def _ema(s: pd.Series, n: int) -> pd.Series:
    return s.ewm(span=n, adjust=False, min_periods=n).mean()


def _rsi(close: pd.Series, n: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0.0)
    loss = -delta.clip(upper=0.0)
    # Wilder's smoothing via EMA with alpha = 1/n
    avg_gain = gain.ewm(alpha=1.0 / n, adjust=False, min_periods=n).mean()
    avg_loss = loss.ewm(alpha=1.0 / n, adjust=False, min_periods=n).mean()
    rs = avg_gain / avg_loss.replace(0.0, np.nan)
    return 100.0 - (100.0 / (1.0 + rs))


def _macd(close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9):
    macd_line = _ema(close, fast) - _ema(close, slow)
    signal_line = macd_line.ewm(span=signal, adjust=False, min_periods=signal).mean()
    hist = macd_line - signal_line
    return macd_line, signal_line, hist


def _stoch(high: pd.Series, low: pd.Series, close: pd.Series, k: int = 14, d: int = 3):
    ll = low.rolling(k, min_periods=k).min()
    hh = high.rolling(k, min_periods=k).max()
    pct_k = 100.0 * (close - ll) / (hh - ll).replace(0.0, np.nan)
    pct_d = pct_k.rolling(d, min_periods=d).mean()
    return pct_k, pct_d


def _true_range(high: pd.Series, low: pd.Series, close: pd.Series) -> pd.Series:
    prev_close = close.shift(1)
    tr = pd.concat(
        [(high - low), (high - prev_close).abs(), (low - prev_close).abs()], axis=1
    ).max(axis=1)
    return tr


def _atr(high: pd.Series, low: pd.Series, close: pd.Series, n: int = 14) -> pd.Series:
    tr = _true_range(high, low, close)
    # Wilder's smoothing
    return tr.ewm(alpha=1.0 / n, adjust=False, min_periods=n).mean()


def _bollinger(close: pd.Series, n: int = 20, k: float = 2.0):
    mid = _sma(close, n)
    std = close.rolling(n, min_periods=n).std(ddof=0)
    return mid - k * std, mid, mid + k * std


def _obv(close: pd.Series, volume: pd.Series) -> pd.Series:
    direction = np.sign(close.diff().fillna(0.0))
    return (direction * volume).cumsum()


def _slope(s: pd.Series, n: int) -> pd.Series:
    """Per-step slope of a rolling linear fit (units = series/step)."""
    x = np.arange(n, dtype=float)
    x_mean = x.mean()
    x_var = ((x - x_mean) ** 2).sum()

    def _fit(window: np.ndarray) -> float:
        if np.isnan(window).any():
            return np.nan
        y_mean = window.mean()
        return float(((x - x_mean) * (window - y_mean)).sum() / x_var)

    return s.rolling(n, min_periods=n).apply(_fit, raw=True)


def _mfi(high: pd.Series, low: pd.Series, close: pd.Series, volume: pd.Series, n: int = 14) -> pd.Series:
    tp = (high + low + close) / 3.0
    mf = tp * volume
    delta_tp = tp.diff()
    pos_mf = mf.where(delta_tp > 0, 0.0)
    neg_mf = mf.where(delta_tp < 0, 0.0)
    pos_sum = pos_mf.rolling(n, min_periods=n).sum()
    neg_sum = neg_mf.rolling(n, min_periods=n).sum()
    ratio = pos_sum / neg_sum.replace(0.0, np.nan)
    return 100.0 - (100.0 / (1.0 + ratio))


def _cmf(high: pd.Series, low: pd.Series, close: pd.Series, volume: pd.Series, n: int = 20) -> pd.Series:
    rng = (high - low).replace(0.0, np.nan)
    mfm = ((close - low) - (high - close)) / rng
    mfv = mfm * volume
    return mfv.rolling(n, min_periods=n).sum() / volume.rolling(n, min_periods=n).sum()


# ---------------------------------------------------------------------------
# Master calculator
# ---------------------------------------------------------------------------


def calculate_all_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """Return df augmented with all indicator columns.

    The input must have columns: date, open, high, low, close, volume.
    Output preserves all input columns; indicators are appended.
    """
    out = df.copy()
    close, high, low, vol = out["close"], out["high"], out["low"], out["volume"]

    # ---- Trend ----
    for n in (20, 50, 100, 200):
        out[f"sma{n}"] = _sma(close, n)
    out["ema20"] = _ema(close, 20)
    out["ema50"] = _ema(close, 50)

    out["ma_aligned_bull"] = (
        (close > out["sma20"])
        & (out["sma20"] > out["sma50"])
        & (out["sma50"] > out["sma200"])
    )
    # Golden cross (today): SMA50 crosses above SMA200
    sma50_prev = out["sma50"].shift(1)
    sma200_prev = out["sma200"].shift(1)
    out["golden_cross_today"] = (
        (sma50_prev <= sma200_prev) & (out["sma50"] > out["sma200"])
    )
    out["death_cross_today"] = (
        (sma50_prev >= sma200_prev) & (out["sma50"] < out["sma200"])
    )

    for n in (20, 50, 100, 200):
        out[f"dist_sma{n}_pct"] = (close - out[f"sma{n}"]) / out[f"sma{n}"] * 100.0

    # ---- Momentum ----
    out["rsi14"] = _rsi(close, 14)
    macd_line, macd_sig, macd_hist = _macd(close)
    out["macd"] = macd_line
    out["macd_signal"] = macd_sig
    out["macd_hist"] = macd_hist
    pk, pd_ = _stoch(high, low, close, k=14, d=3)
    out["stoch_k"] = pk
    out["stoch_d"] = pd_

    # ---- Volatility ----
    out["atr14"] = _atr(high, low, close, 14)
    bb_low, bb_mid, bb_up = _bollinger(close, 20, 2.0)
    out["bb_lower"] = bb_low
    out["bb_mid"] = bb_mid
    out["bb_upper"] = bb_up
    out["atr_pct"] = out["atr14"] / close * 100.0

    def _bb_position(row):
        c, lo, mi, up = row["close"], row["bb_lower"], row["bb_mid"], row["bb_upper"]
        if any(pd.isna(v) for v in (lo, mi, up)):
            return np.nan
        if c < lo:
            return "below_lower"
        if c < mi:
            return "lower_half"
        if c <= up:
            return "upper_half"
        return "above_upper"

    out["bb_position"] = out.apply(_bb_position, axis=1)

    # ---- Volume ----
    out["vol_ma20"] = _sma(vol, 20)
    out["vol_ratio"] = vol / out["vol_ma20"]
    out["vol_spike"] = out["vol_ratio"] >= 2.0

    direction = np.sign(close.diff().fillna(0.0))
    up_vol = vol.where(direction > 0, 0.0)
    down_vol = vol.where(direction < 0, 0.0)
    out["up_vol_20d"] = up_vol.rolling(20, min_periods=20).sum()
    out["down_vol_20d"] = down_vol.rolling(20, min_periods=20).sum()

    # ---- Money flow ----
    out["obv"] = _obv(close, vol)
    out["obv_slope_20d"] = _slope(out["obv"], 20)
    out["mfi14"] = _mfi(high, low, close, vol, 14)
    out["cmf20"] = _cmf(high, low, close, vol, 20)

    # ---- Price action ----
    out["ret_1d"] = close.pct_change(1) * 100.0
    out["ret_5d"] = close.pct_change(5) * 100.0
    out["ret_20d"] = close.pct_change(20) * 100.0
    out["ret_60d"] = close.pct_change(60) * 100.0
    out["ret_120d"] = close.pct_change(120) * 100.0
    out["hi_52w"] = high.rolling(252, min_periods=20).max()
    out["lo_52w"] = low.rolling(252, min_periods=20).min()
    out["dist_52w_high_pct"] = (close - out["hi_52w"]) / out["hi_52w"] * 100.0
    out["dist_52w_low_pct"] = (close - out["lo_52w"]) / out["lo_52w"] * 100.0

    # ---- Support / Resistance ----
    for n in (20, 50, 100):
        out[f"swing_high_{n}"] = high.rolling(n, min_periods=n).max()
        out[f"swing_low_{n}"] = low.rolling(n, min_periods=n).min()
    # Classic pivot point based on PREVIOUS day's HLC
    prev_h = high.shift(1)
    prev_l = low.shift(1)
    prev_c = close.shift(1)
    out["pivot"] = (prev_h + prev_l + prev_c) / 3.0
    out["pivot_r1"] = 2 * out["pivot"] - prev_l
    out["pivot_s1"] = 2 * out["pivot"] - prev_h
    out["stop_atr_1_5"] = close - 1.5 * out["atr14"]
    out["stop_atr_2_0"] = close - 2.0 * out["atr14"]

    return out


# ---------------------------------------------------------------------------
# Interpretation
# ---------------------------------------------------------------------------


def _fmt(val, digits: int = 2) -> str:
    if val is None:
        return "NaN"
    if isinstance(val, float):
        if math.isnan(val) or math.isinf(val):
            return "NaN"
        return f"{val:,.{digits}f}"
    if isinstance(val, (np.floating,)):
        f = float(val)
        if math.isnan(f) or math.isinf(f):
            return "NaN"
        return f"{f:,.{digits}f}"
    return str(val)


def _interpret(last: pd.Series) -> dict[str, str]:
    """Derive short status strings from the last row."""
    # Trend
    if bool(last.get("ma_aligned_bull")):
        trend = "bullish_aligned (close > SMA20 > SMA50 > SMA200)"
    elif (
        pd.notna(last.get("sma50"))
        and pd.notna(last.get("sma200"))
        and last["sma50"] > last["sma200"]
        and last["close"] > last["sma200"]
    ):
        trend = "bullish_partial"
    elif (
        pd.notna(last.get("sma50"))
        and pd.notna(last.get("sma200"))
        and last["sma50"] < last["sma200"]
    ):
        trend = "bearish (SMA50 < SMA200)"
    else:
        trend = "sideways_or_unclear"

    # Momentum
    rsi = last.get("rsi14")
    macd_h = last.get("macd_hist")
    if pd.isna(rsi) or pd.isna(macd_h):
        momentum = "insufficient_data"
    else:
        rsi_lbl = (
            "overbought" if rsi >= 70 else "oversold" if rsi <= 30 else f"neutral ({rsi:.1f})"
        )
        macd_lbl = "MACD_hist_positive" if macd_h > 0 else "MACD_hist_negative"
        momentum = f"RSI {rsi_lbl}, {macd_lbl}"

    # Volume
    vr = last.get("vol_ratio")
    if pd.isna(vr):
        volume_s = "insufficient_data"
    elif vr >= 2.0:
        volume_s = f"spike ({vr:.2f}× MA20)"
    elif vr >= 1.2:
        volume_s = f"above_avg ({vr:.2f}×)"
    elif vr <= 0.7:
        volume_s = f"below_avg ({vr:.2f}×)"
    else:
        volume_s = f"average ({vr:.2f}×)"

    # Money flow
    cmf = last.get("cmf20")
    mfi = last.get("mfi14")
    obv_sl = last.get("obv_slope_20d")
    bits = []
    if pd.notna(cmf):
        bits.append(f"CMF20 {'+' if cmf >= 0 else ''}{cmf:.3f}")
    if pd.notna(mfi):
        if mfi >= 80:
            bits.append(f"MFI overbought ({mfi:.1f})")
        elif mfi <= 20:
            bits.append(f"MFI oversold ({mfi:.1f})")
        else:
            bits.append(f"MFI neutral ({mfi:.1f})")
    if pd.notna(obv_sl):
        bits.append(f"OBV slope {'up' if obv_sl > 0 else 'down'}")
    money_flow = ", ".join(bits) if bits else "insufficient_data"

    # Volatility
    atr_pct = last.get("atr_pct")
    bb_pos = last.get("bb_position")
    if pd.isna(atr_pct):
        volatility = "insufficient_data"
    else:
        vol_band = (
            "high" if atr_pct >= 3 else "low" if atr_pct < 1.5 else "normal"
        )
        volatility = f"ATR%={atr_pct:.2f} ({vol_band}), BB={bb_pos}"

    # Key risks
    risks: list[str] = []
    if pd.notna(rsi) and rsi >= 75:
        risks.append("RSI overbought → pullback risk")
    if pd.notna(rsi) and rsi <= 25:
        risks.append("RSI oversold → bounce-or-capitulation")
    if pd.notna(last.get("dist_52w_high_pct")) and last["dist_52w_high_pct"] > -3:
        risks.append("near 52W high — failed-breakout risk")
    if pd.notna(last.get("dist_52w_low_pct")) and last["dist_52w_low_pct"] < 5:
        risks.append("near 52W low — downtrend continuation risk")
    if pd.notna(cmf) and cmf < -0.05 and trend.startswith("bullish"):
        risks.append("price up but CMF20 negative → distribution divergence")
    if pd.notna(macd_h) and pd.notna(last.get("macd")) and last["macd"] > 0 and macd_h < 0:
        risks.append("MACD above 0 but histogram contracting → momentum fade")
    if bool(last.get("vol_spike")) and last.get("ret_1d", 0) < 0:
        risks.append("volume spike on down day → possible distribution")

    # Breakout exhaustion: BB above_upper + vol ≥2× + Stoch %K ≥90 + 1D ≥5%.
    bb_pos_val = last.get("bb_position")
    vol_ratio_val = last.get("vol_ratio")
    stoch_k_val = last.get("stoch_k")
    ret_1d_val = last.get("ret_1d")
    if (
        bb_pos_val == "above_upper"
        and pd.notna(vol_ratio_val) and vol_ratio_val >= 2.0
        and pd.notna(stoch_k_val) and stoch_k_val >= 90.0
        and pd.notna(ret_1d_val) and ret_1d_val >= 5.0
    ):
        risks.append(
            "breakout_exhaustion_risk: giá tăng mạnh vượt Bollinger Upper với "
            "volume spike và Stoch quá nóng; rủi ro pullback/throwback 1-5 phiên cao."
        )

    # Near SMA100 resistance: close just under SMA100 (within 2%).
    sma100_val = last.get("sma100")
    close_val = last.get("close")
    dist_sma100 = last.get("dist_sma100_pct")
    if (
        pd.notna(close_val) and pd.notna(sma100_val) and close_val < sma100_val
        and pd.notna(dist_sma100) and -2.0 <= dist_sma100 <= 0.0
    ):
        risks.append(
            "near_sma100_resistance: giá đang sát dưới SMA100, cần vượt và "
            "giữ trên SMA100 để xác nhận trend trung hạn."
        )

    # Trend not fully aligned: strict close > SMA20 > SMA50 > SMA100 > SMA200.
    sma20_val = last.get("sma20")
    sma50_val = last.get("sma50")
    sma200_val = last.get("sma200")
    if all(pd.notna(v) for v in (close_val, sma20_val, sma50_val, sma100_val, sma200_val)):
        full_align = (
            close_val > sma20_val > sma50_val > sma100_val > sma200_val
        )
        if not full_align:
            risks.append(
                "trend_not_fully_aligned: MA chưa xếp hàng tăng hoàn chỉnh, "
                "xu hướng trung hạn chưa xác nhận."
            )

    if not risks:
        risks.append("no major flag from indicator set")

    return {
        "trend_status": trend,
        "momentum_status": momentum,
        "volume_status": volume_s,
        "money_flow_status": money_flow,
        "volatility_status": volatility,
        "key_risks": "; ".join(risks),
    }


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------


def generate_indicator_report(df: pd.DataFrame, symbol: str, out_path: Path) -> None:
    """Write markdown snapshot + interpretation for the latest row."""
    if len(df) == 0:
        out_path.write_text(f"# {symbol} — Indicator Report\n\nNo data.\n", encoding="utf-8")
        return

    last = df.iloc[-1]
    interp = _interpret(last)

    L: list[str] = []
    L.append(f"# {symbol} — Indicator Report")
    L.append("")
    L.append(f"- Generated: `{date.today().isoformat()}`")
    L.append(f"- Rows in series: **{len(df)}**")
    L.append(f"- Window: **{df['date'].min().date()}** → **{df['date'].max().date()}**")
    L.append(f"- Snapshot date: **{last['date'].date()}**")
    L.append("")

    # ---- Snapshot ----
    L.append("## 1. Snapshot — phiên cuối")
    L.append("")
    L.append("| Field | Value |")
    L.append("|---|---|")
    rows: list[tuple[str, str]] = [
        ("date", str(last["date"].date())),
        ("close", _fmt(last["close"])),
        ("volume", _fmt(last["volume"], 0)),
        ("SMA20", _fmt(last["sma20"])),
        ("SMA50", _fmt(last["sma50"])),
        ("SMA100", _fmt(last["sma100"])),
        ("SMA200", _fmt(last["sma200"])),
        ("EMA20", _fmt(last["ema20"])),
        ("EMA50", _fmt(last["ema50"])),
        ("RSI14", _fmt(last["rsi14"])),
        ("MACD", _fmt(last["macd"], 4)),
        ("MACD signal", _fmt(last["macd_signal"], 4)),
        ("MACD hist", _fmt(last["macd_hist"], 4)),
        ("Stoch %K", _fmt(last["stoch_k"])),
        ("Stoch %D", _fmt(last["stoch_d"])),
        ("ATR14", _fmt(last["atr14"], 4)),
        ("BB upper", _fmt(last["bb_upper"])),
        ("BB mid", _fmt(last["bb_mid"])),
        ("BB lower", _fmt(last["bb_lower"])),
        ("BB position", str(last["bb_position"])),
        ("vol_ratio (vs MA20)", _fmt(last["vol_ratio"], 3)),
        ("OBV slope 20D", _fmt(last["obv_slope_20d"], 0)),
        ("MFI14", _fmt(last["mfi14"])),
        ("CMF20", _fmt(last["cmf20"], 4)),
    ]
    for k, v in rows:
        L.append(f"| {k} | {v} |")
    L.append("")

    # ---- Distances + S/R ----
    L.append("## 2. Distances & Support/Resistance")
    L.append("")
    L.append("| Metric | Value |")
    L.append("|---|---|")
    dist_rows = [
        ("dist from SMA20 %", _fmt(last["dist_sma20_pct"])),
        ("dist from SMA50 %", _fmt(last["dist_sma50_pct"])),
        ("dist from SMA100 %", _fmt(last["dist_sma100_pct"])),
        ("dist from SMA200 %", _fmt(last["dist_sma200_pct"])),
        ("52W high", _fmt(last["hi_52w"])),
        ("52W low", _fmt(last["lo_52w"])),
        ("dist 52W high %", _fmt(last["dist_52w_high_pct"])),
        ("dist 52W low %", _fmt(last["dist_52w_low_pct"])),
        ("swing high 20D", _fmt(last["swing_high_20"])),
        ("swing low 20D", _fmt(last["swing_low_20"])),
        ("swing high 50D", _fmt(last["swing_high_50"])),
        ("swing low 50D", _fmt(last["swing_low_50"])),
        ("swing high 100D", _fmt(last["swing_high_100"])),
        ("swing low 100D", _fmt(last["swing_low_100"])),
        ("pivot", _fmt(last["pivot"])),
        ("pivot R1", _fmt(last["pivot_r1"])),
        ("pivot S1", _fmt(last["pivot_s1"])),
        ("stop @ 1.5×ATR", _fmt(last["stop_atr_1_5"])),
        ("stop @ 2.0×ATR", _fmt(last["stop_atr_2_0"])),
    ]
    for k, v in dist_rows:
        L.append(f"| {k} | {v} |")
    L.append("")

    # ---- Returns ----
    L.append("## 3. Returns")
    L.append("")
    L.append("| Period | Return % |")
    L.append("|---|---|")
    for label, col in (("1D", "ret_1d"), ("1W (5D)", "ret_5d"),
                       ("1M (20D)", "ret_20d"), ("3M (60D)", "ret_60d"),
                       ("6M (120D)", "ret_120d")):
        L.append(f"| {label} | {_fmt(last[col])} |")
    L.append("")

    # ---- Flags ----
    L.append("## 4. Flags")
    L.append("")
    L.append(f"- MA alignment bullish: **{bool(last['ma_aligned_bull'])}**")
    L.append(f"- Golden cross today: **{bool(last['golden_cross_today'])}**")
    L.append(f"- Death cross today: **{bool(last['death_cross_today'])}**")
    L.append(f"- Volume spike (≥2× MA20): **{bool(last['vol_spike'])}**")
    L.append("")

    # ---- Interpretation ----
    L.append("## 5. Interpretation")
    L.append("")
    for k in ("trend_status", "momentum_status", "volume_status",
              "money_flow_status", "volatility_status", "key_risks"):
        L.append(f"- **{k}**: {interp[k]}")
    L.append("")

    L.append("> Báo cáo này thuần kỹ thuật. Không phải khuyến nghị mua/bán. "
             "Dùng kèm phân tích nền tảng + bối cảnh thị trường.")
    L.append("")

    out_path.write_text("\n".join(L), encoding="utf-8")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def run(csv_path: Path, symbol: str) -> tuple[Path, Path]:
    df = load_ohlcv(csv_path)
    print(f"[indicator] loaded {len(df)} rows from {csv_path}")
    out = calculate_all_indicators(df)

    csv_out = DATA_DIR / f"{symbol}_indicators.csv"
    out.to_csv(csv_out, index=False)
    print(f"[indicator] wrote {csv_out}")

    md_out = REPORTS_DIR / f"{symbol}_indicator_report.md"
    generate_indicator_report(out, symbol, md_out)
    print(f"[indicator] wrote {md_out}")
    return csv_out, md_out


def main() -> int:
    p = argparse.ArgumentParser(description="Technical indicator engine.")
    p.add_argument("--csv", required=True, help="Path to OHLCV CSV (e.g. data/GAS_price_VCI.csv)")
    p.add_argument("--symbol", required=True, help="Ticker, e.g. GAS")
    args = p.parse_args()
    run(Path(args.csv), args.symbol.upper())
    return 0


if __name__ == "__main__":
    sys.exit(main())
