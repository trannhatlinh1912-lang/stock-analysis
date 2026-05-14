#!/usr/bin/env python3
"""Fetch technical analysis data → data/technical_snapshot_{ticker}_{date}.json

Usage:
  python fetch_technical.py --ticker HPG
  python fetch_technical.py --ticker HPG --force
"""

import argparse
import json
import os
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent.parent / "data" / ".env")
except ImportError:
    pass

SKILL_DIR = Path(__file__).parent.parent
DATA_DIR = SKILL_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)

TODAY = date.today().isoformat()

_vnstock_key = os.getenv("VNSTOCK_API_KEY", "")
if _vnstock_key:
    try:
        import vnstock as _vs_mod
        _vs_mod.change_api_key(_vnstock_key)
    except Exception:
        pass

TICKER_INDUSTRY_MAP = {
    "HPG": "STEEL",  "HSG": "STEEL",  "NKG": "STEEL",  "SMC": "STEEL",
    "VCB": "BANK",   "BID": "BANK",   "CTG": "BANK",   "MBB": "BANK",
    "TCB": "BANK",   "ACB": "BANK",   "VPB": "BANK",   "HDB": "BANK",
    "STB": "BANK",   "SHB": "BANK",
    "VHM": "REALESTATE", "NVL": "REALESTATE", "KDH": "REALESTATE",
    "PDR": "REALESTATE", "DXG": "REALESTATE", "NLG": "REALESTATE",
    "SSI": "SECURITIES", "VCI": "SECURITIES", "HCM": "SECURITIES",
    "VND": "SECURITIES", "MBS": "SECURITIES",
    "MWG": "RETAIL", "FRT": "RETAIL", "PNJ": "RETAIL", "DGW": "RETAIL",
    "GAS": "ENERGY", "PLX": "ENERGY", "PVD": "ENERGY", "BSR": "ENERGY",
    "DHG": "PHARMA", "DMC": "PHARMA", "IMP": "PHARMA", "TRA": "PHARMA",
    "FPT": "TECHNOLOGY", "CMG": "TECHNOLOGY",
    "DPM": "FERTILIZER", "DCM": "FERTILIZER", "BFC": "FERTILIZER",
    "CTD": "CONSTRUCTION", "HBC": "CONSTRUCTION", "VCG": "CONSTRUCTION",
}

INDUSTRY_NAMES = {
    "STEEL": "Thép", "BANK": "Ngân hàng", "REALESTATE": "Bất động sản",
    "SECURITIES": "Chứng khoán", "RETAIL": "Bán lẻ",
    "ENERGY": "Năng lượng / Dầu khí", "PHARMA": "Dược phẩm",
    "TECHNOLOGY": "Công nghệ", "FERTILIZER": "Phân bón",
    "CONSTRUCTION": "Xây dựng",
}

MAX_ROOM_PCT = 49.0  # default foreign ownership room for non-bank


def _safe(val):
    """Convert numpy scalar to Python float, handling None/NaN."""
    if val is None:
        return None
    try:
        import math
        f = float(val)
        return None if math.isnan(f) or math.isinf(f) else round(f, 4)
    except (TypeError, ValueError):
        return None


def fetch_price_history(ticker: str) -> "pd.DataFrame":
    import pandas as pd
    start = (datetime.today() - timedelta(days=400)).strftime("%Y-%m-%d")
    end = datetime.today().strftime("%Y-%m-%d")

    errors = []
    for source in ("VCI", "TCBS"):
        try:
            from vnstock import Vnstock
            stock = Vnstock().stock(symbol=ticker, source=source)
            df = stock.quote.history(start=start, end=end, interval="1D")
            if df is not None and len(df) > 30:
                df.columns = [c.lower() for c in df.columns]
                for col in ("open", "high", "low", "close", "volume"):
                    if col not in df.columns:
                        # try common aliases
                        aliases = {"open": ["open_price"], "close": ["close_price", "price"],
                                   "volume": ["vol", "match_vol"]}
                        for alias in aliases.get(col, []):
                            if alias in df.columns:
                                df[col] = df[alias]
                                break
                df = df.dropna(subset=["close"])
                if len(df) > 30:
                    return df
        except Exception as e:
            errors.append(str(e))

    # fallback to yfinance
    try:
        import yfinance as yf
        sym = ticker + ".VN"
        hist = yf.download(sym, period="14mo", auto_adjust=True, progress=False)
        if len(hist) > 30:
            hist.columns = [c.lower() for c in hist.columns]
            return hist.reset_index()
    except Exception as e:
        errors.append(str(e))

    raise RuntimeError(f"Cannot fetch price history for {ticker}: {errors}")


def compute_indicators(df: "pd.DataFrame") -> dict:
    """Compute TA indicators using pandas_ta. Returns dict of scalar values."""
    import pandas as pd
    try:
        import pandas_ta as ta
    except ImportError:
        raise RuntimeError("pandas_ta not installed. Run: pip install pandas_ta")

    close = df["close"].astype(float)
    high  = df["high"].astype(float)
    low   = df["low"].astype(float)
    vol   = df["volume"].astype(float)

    n = len(close)

    # Moving averages
    ma20  = _safe(close.rolling(20).mean().iloc[-1])  if n >= 20  else None
    ma50  = _safe(close.rolling(50).mean().iloc[-1])  if n >= 50  else None
    ma200 = _safe(close.rolling(200).mean().iloc[-1]) if n >= 200 else None
    ema20 = _safe(close.ewm(span=20, adjust=False).mean().iloc[-1]) if n >= 20 else None

    # RSI(14)
    rsi_series = ta.rsi(close, length=14)
    rsi14 = _safe(rsi_series.iloc[-1]) if rsi_series is not None and len(rsi_series) > 0 else None

    # MACD(12,26,9)
    macd_df = ta.macd(close, fast=12, slow=26, signal=9)
    macd_val = macd_hist = macd_sig = None
    if macd_df is not None and len(macd_df) > 0:
        cols = list(macd_df.columns)
        # pandas_ta columns: MACD_12_26_9, MACDh_12_26_9, MACDs_12_26_9
        macd_col  = next((c for c in cols if c.startswith("MACD_")), None)
        hist_col  = next((c for c in cols if c.startswith("MACDh_")), None)
        sig_col   = next((c for c in cols if c.startswith("MACDs_")), None)
        macd_val  = _safe(macd_df[macd_col].iloc[-1])  if macd_col  else None
        macd_hist = _safe(macd_df[hist_col].iloc[-1])  if hist_col  else None
        macd_sig  = _safe(macd_df[sig_col].iloc[-1])   if sig_col   else None

    # Stochastic(14,3)
    stoch_df = ta.stoch(high, low, close, k=14, d=3)
    stoch_k = stoch_d = None
    if stoch_df is not None and len(stoch_df) > 0:
        k_col = next((c for c in stoch_df.columns if c.startswith("STOCHk_")), None)
        d_col = next((c for c in stoch_df.columns if c.startswith("STOCHd_")), None)
        stoch_k = _safe(stoch_df[k_col].iloc[-1]) if k_col else None
        stoch_d = _safe(stoch_df[d_col].iloc[-1]) if d_col else None

    # Bollinger Bands(20,2)
    bb_df = ta.bbands(close, length=20, std=2)
    bb_upper = bb_lower = bb_pct = None
    if bb_df is not None and len(bb_df) > 0:
        u_col = next((c for c in bb_df.columns if "BBU_" in c), None)
        l_col = next((c for c in bb_df.columns if "BBL_" in c), None)
        p_col = next((c for c in bb_df.columns if "BBP_" in c), None)
        bb_upper = _safe(bb_df[u_col].iloc[-1]) if u_col else None
        bb_lower = _safe(bb_df[l_col].iloc[-1]) if l_col else None
        bb_pct   = _safe(bb_df[p_col].iloc[-1]) if p_col else None

    # ATR(14)
    atr_series = ta.atr(high, low, close, length=14)
    atr14 = _safe(atr_series.iloc[-1]) if atr_series is not None and len(atr_series) > 0 else None

    # OBV trend (simple: compare last OBV vs 20-session ago OBV)
    obv_series = ta.obv(close, vol)
    obv_trend = "flat"
    if obv_series is not None and len(obv_series) > 25:
        obv_now   = float(obv_series.iloc[-1])
        obv_prev  = float(obv_series.iloc[-21])
        obv_trend = "rising" if obv_now > obv_prev * 1.02 else ("falling" if obv_now < obv_prev * 0.98 else "flat")

    # Volume stats
    vol_today = _safe(vol.iloc[-1])
    vol_ma20  = _safe(vol.rolling(20).mean().iloc[-1]) if n >= 20 else None
    vol_ratio = _safe(vol_today / vol_ma20) if vol_today and vol_ma20 else None

    return {
        "ma20": ma20, "ma50": ma50, "ma200": ma200, "ema20": ema20,
        "rsi14": rsi14,
        "macd": macd_val, "macd_signal": macd_sig, "macd_hist": macd_hist,
        "bb_upper": bb_upper, "bb_lower": bb_lower, "bb_pct": bb_pct,
        "stoch_k": stoch_k, "stoch_d": stoch_d,
        "atr14": atr14,
        "vol_today": vol_today, "vol_ma20": vol_ma20, "vol_ratio": vol_ratio,
        "obv_trend": obv_trend,
    }


def compute_price_stats(df: "pd.DataFrame") -> dict:
    close = df["close"].astype(float)
    n = len(close)

    current = _safe(close.iloc[-1])
    prev1   = _safe(close.iloc[-2]) if n >= 2 else None
    prev22  = _safe(close.iloc[-22]) if n >= 22 else None
    prev66  = _safe(close.iloc[-66]) if n >= 66 else None
    open_yr = _safe(close.iloc[0])

    high_52w = _safe(close.tail(252).max())
    low_52w  = _safe(close.tail(252).min())

    def pct(a, b):
        if a is None or b is None or b == 0:
            return None
        return round((a - b) / b * 100, 2)

    return {
        "current":        current,
        "high_52w":       high_52w,
        "low_52w":        low_52w,
        "change_pct_1d":  pct(current, prev1),
        "change_pct_1m":  pct(current, prev22),
        "change_pct_3m":  pct(current, prev66),
        "change_pct_ytd": pct(current, open_yr),
        "vs_52w_high_pct": pct(current, high_52w),
    }


def compute_support_resistance(df: "pd.DataFrame", current: float) -> dict:
    """Identify S/R from 52W high/low and recent swing highs/lows (last 60 sessions)."""
    close = df["close"].astype(float)
    high  = df["high"].astype(float)
    low   = df["low"].astype(float)

    last_session = df.iloc[-1]
    pivot = _safe((float(last_session.get("high", last_session["close"])) +
                   float(last_session.get("low",  last_session["close"])) +
                   float(last_session["close"])) / 3)

    # Swing highs/lows from last 60 sessions
    window = 60
    h_window = high.tail(window)
    l_window = low.tail(window)

    # Find local peaks and troughs (simple: rolling max/min with 5-bar lookback)
    peaks   = sorted([_safe(v) for v in h_window.nlargest(4).values if _safe(v)], reverse=True)
    troughs = sorted([_safe(v) for v in l_window.nsmallest(4).values if _safe(v)])

    high_52w = _safe(close.tail(252).max())
    low_52w  = _safe(close.tail(252).min())

    # Build candidate resistances above current price, supports below
    r_candidates = sorted(set(filter(None, peaks + [high_52w])))
    s_candidates = sorted(set(filter(None, troughs + [low_52w])), reverse=True)

    resistances = [v for v in r_candidates if v and v > current * 1.005][:2]
    supports    = [v for v in s_candidates if v and v < current * 0.995][:2]

    while len(resistances) < 2:
        resistances.append(None)
    while len(supports) < 2:
        supports.append(None)

    return {
        "resistance1": resistances[0],
        "resistance2": resistances[1],
        "support1":    supports[0],
        "support2":    supports[1],
        "pivot":       pivot,
    }


def fetch_foreign_flow(ticker: str) -> dict:
    """Fetch foreign investor flow from vnstock (10-day net buy/sell)."""
    warnings = []
    try:
        from vnstock import Vnstock
        stock = Vnstock().stock(symbol=ticker, source="VCI")
        end_dt   = datetime.today()
        start_dt = end_dt - timedelta(days=20)
        start_str = start_dt.strftime("%Y-%m-%d")
        end_str   = end_dt.strftime("%Y-%m-%d")

        # Try intraday/trading board style foreign flow
        # vnstock >= 3.x: stock.trading.price_board() may have foreign cols
        try:
            board = stock.trading.price_board(symbols_list=[ticker])
            if board is not None and len(board) > 0:
                cols = [c.lower() for c in board.columns]
                board.columns = cols
                foreign_own = None
                for c in board.columns:
                    if "foreign" in c and "own" in c:
                        foreign_own = _safe(board[c].iloc[0])
                        break
                    if "nn_own" in c or "foreign_pct" in c:
                        foreign_own = _safe(board[c].iloc[0])
                        break
        except Exception:
            foreign_own = None

        # Try stock.quote for historical foreign data if available
        foreign_net_10d = foreign_buy_10d = foreign_sell_10d = None
        try:
            hist = stock.quote.history(start=start_str, end=end_str, interval="1D")
            if hist is not None and len(hist) > 0:
                hist.columns = [c.lower() for c in hist.columns]
                buy_col  = next((c for c in hist.columns if "foreign" in c and "buy" in c), None)
                sell_col = next((c for c in hist.columns if "foreign" in c and "sell" in c), None)
                if buy_col and sell_col:
                    last10 = hist.tail(10)
                    foreign_buy_10d  = _safe(last10[buy_col].sum())
                    foreign_sell_10d = _safe(last10[sell_col].sum())
                    if foreign_buy_10d is not None and foreign_sell_10d is not None:
                        foreign_net_10d = round(foreign_buy_10d - foreign_sell_10d, 4)
        except Exception:
            pass

        if foreign_net_10d is None:
            warnings.append("foreign_flow: could not fetch from vnstock; showing [missing_data]")

        industry = TICKER_INDUSTRY_MAP.get(ticker.upper(), "")
        max_room = 30.0 if industry == "BANK" else MAX_ROOM_PCT
        room_remaining = None
        if foreign_own is not None:
            room_remaining = round(max_room - foreign_own, 2)

        return {
            "foreign_net_10d":  foreign_net_10d,
            "foreign_buy_10d":  foreign_buy_10d,
            "foreign_sell_10d": foreign_sell_10d,
            "foreign_own_pct":  foreign_own,
            "room_remaining_pct": room_remaining,
            "warnings": warnings,
        }

    except Exception as e:
        return {
            "foreign_net_10d":  None,
            "foreign_buy_10d":  None,
            "foreign_sell_10d": None,
            "foreign_own_pct":  None,
            "room_remaining_pct": None,
            "warnings": [f"foreign_flow fetch failed: {e}"],
        }


def generate_signals(price: dict, ind: dict, mf: dict) -> dict:
    current = price.get("current")
    ma50    = ind.get("ma50")
    ma200   = ind.get("ma200")
    rsi     = ind.get("rsi14")
    hist    = ind.get("macd_hist")
    vol_r   = ind.get("vol_ratio")
    chg_1d  = price.get("change_pct_1d", 0) or 0
    fn10    = mf.get("foreign_net_10d")

    # Trend signal
    if current and ma50 and ma200:
        if current > ma50 and ma50 > ma200:
            trend = "BULLISH"
        elif current < ma50 and ma50 < ma200:
            trend = "BEARISH"
        else:
            trend = "NEUTRAL"
    else:
        trend = "NEUTRAL"

    # Momentum signal
    if rsi is not None and hist is not None:
        if 45 <= rsi <= 70 and hist > 0:
            momentum = "BULLISH"
        elif rsi < 40 or (hist is not None and hist < -abs(hist) * 0.5 and rsi < 50):
            momentum = "BEARISH"
        else:
            momentum = "NEUTRAL"
    elif rsi is not None:
        momentum = "BULLISH" if 45 <= rsi <= 70 else ("BEARISH" if rsi < 35 else "NEUTRAL")
    else:
        momentum = "NEUTRAL"

    # Volume signal
    if vol_r is not None:
        price_up = chg_1d >= 0
        if vol_r > 1.3 and price_up:
            volume = "CONFIRM"
        elif vol_r > 1.3 and not price_up:
            volume = "DIVERGE"
        elif vol_r < 0.7:
            volume = "NEUTRAL"
        else:
            volume = "NEUTRAL"
    else:
        volume = "NEUTRAL"

    # Money flow signal
    if fn10 is not None:
        if fn10 > 5e9:
            money_flow = "INFLOW"
        elif fn10 < -5e9:
            money_flow = "OUTFLOW"
        else:
            money_flow = "NEUTRAL"
    else:
        money_flow = "NEUTRAL"

    # Timing zone: count bullish vs bearish
    signal_map = {
        "trend":      {"BULLISH": 1, "NEUTRAL": 0, "BEARISH": -1}[trend],
        "momentum":   {"BULLISH": 1, "NEUTRAL": 0, "BEARISH": -1}[momentum],
        "volume":     {"CONFIRM": 1, "NEUTRAL": 0, "DIVERGE": -1}[volume],
        "money_flow": {"INFLOW": 1, "NEUTRAL": 0, "OUTFLOW": -1}[money_flow],
    }
    score = sum(signal_map.values())
    if score >= 2:
        timing_zone = "ACCUMULATION"
    elif score <= -2:
        timing_zone = "DISTRIBUTION"
    else:
        timing_zone = "WATCH"

    return {
        "trend":       trend,
        "momentum":    momentum,
        "volume":      volume,
        "money_flow":  money_flow,
        "timing_zone": timing_zone,
    }


def main():
    parser = argparse.ArgumentParser(description="Fetch technical analysis snapshot")
    parser.add_argument("--ticker", required=True, help="Stock ticker (e.g. HPG)")
    parser.add_argument("--force", action="store_true", help="Force re-fetch even if cache exists")
    args = parser.parse_args()

    ticker = args.ticker.upper().strip()
    out_path = DATA_DIR / f"technical_snapshot_{ticker}_{TODAY}.json"

    if out_path.exists() and not args.force:
        print(f"cache: True | snapshot: {out_path}")
        return

    print(f"[INFO] Fetching technical data for {ticker}...", file=sys.stderr)

    data_warnings = []

    # Fetch price history
    try:
        df = fetch_price_history(ticker)
    except Exception as e:
        print(f"[ERROR] {e}", file=sys.stderr)
        sys.exit(1)

    # Compute price stats
    price = compute_price_stats(df)
    current = price.get("current") or 0

    # Compute TA indicators
    try:
        indicators = compute_indicators(df)
    except Exception as e:
        data_warnings.append(f"indicators: {e}")
        indicators = {}

    # Compute S/R
    try:
        sr = compute_support_resistance(df, current)
    except Exception as e:
        data_warnings.append(f"support_resistance: {e}")
        sr = {"resistance1": None, "resistance2": None,
              "support1": None, "support2": None, "pivot": None}

    # Fetch money flow
    mf = fetch_foreign_flow(ticker)
    data_warnings.extend(mf.pop("warnings", []))

    # Generate signals
    signals = generate_signals(price, indicators, mf)

    industry_code = TICKER_INDUSTRY_MAP.get(ticker, "UNKNOWN")
    snap = {
        "ticker":   ticker,
        "date":     TODAY,
        "source":   "VCI/TCBS/yfinance",
        "industry": INDUSTRY_NAMES.get(industry_code, industry_code),
        "price":    price,
        "indicators": indicators,
        "money_flow": mf,
        "support_resistance": sr,
        "signals":  signals,
        "data_warnings": data_warnings,
    }

    out_path.write_text(json.dumps(snap, ensure_ascii=False, separators=(",", ":")))
    print(f"cache: False | snapshot: {out_path}")


if __name__ == "__main__":
    main()
