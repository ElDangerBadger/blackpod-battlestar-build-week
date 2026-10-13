# models/model_library.py
# Lightweight technical indicator library with zero hard deps.
# Provides enrich_features(df) to add common TA features safely.
# Works even if only Close is present; uses OHLCV if available.

from __future__ import annotations
import pandas as pd
import numpy as np
from typing import Dict, Optional

# -----------------------------
# Helper: safe rolling ops
# -----------------------------

def _sma(s: pd.Series, n: int) -> pd.Series:
    return s.rolling(n, min_periods=n).mean()

def _ema(s: pd.Series, n: int) -> pd.Series:
    return s.ewm(span=n, adjust=False, min_periods=n).mean()

def _rsi(close: pd.Series, n: int = 14) -> pd.Series:
    # Wilder's RSI
    delta = close.diff()
    gain = (delta.where(delta > 0, 0.0)).ewm(alpha=1/n, min_periods=n, adjust=False).mean()
    loss = (-delta.where(delta < 0, 0.0)).ewm(alpha=1/n, min_periods=n, adjust=False).mean()
    rs = gain / loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))
    return rsi

def _macd(close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9) -> pd.DataFrame:
    ema_fast = _ema(close, fast)
    ema_slow = _ema(close, slow)
    macd = ema_fast - ema_slow
    macd_signal = macd.ewm(span=signal, adjust=False, min_periods=signal).mean()
    macd_hist = macd - macd_signal
    return pd.DataFrame({"MACD": macd, "MACD_Signal": macd_signal, "MACD_Hist": macd_hist})

def _bollinger(close: pd.Series, n: int = 20, k: float = 2.0) -> pd.DataFrame:
    mid = _sma(close, n)
    sd = close.rolling(n, min_periods=n).std()
    up = mid + k*sd
    low = mid - k*sd
    return pd.DataFrame({"BB_Mid": mid, "BB_Up": up, "BB_Low": low})

def _atr(df: pd.DataFrame, n: int = 14) -> pd.Series:
    # Requires High, Low, Close; returns NaN if not available
    if not {"High", "Low", "Close"}.issubset(df.columns):
        return pd.Series(index=df.index, dtype=float)
    high = df["High"].astype(float)
    low = df["Low"].astype(float)
    close = df["Close"].astype(float)
    prev_close = close.shift(1)
    tr = pd.concat([
        (high - low),
        (high - prev_close).abs(),
        (low - prev_close).abs()
    ], axis=1).max(axis=1)
    atr = tr.ewm(alpha=1/n, min_periods=n, adjust=False).mean()
    return atr

# -----------------------------
# Public: enrich_features
# -----------------------------

def enrich_features(df: pd.DataFrame, cfg: Optional[Dict] = None) -> pd.DataFrame:
    """Add common TA features; drop warmup NaNs; return a copy.
    Expects at least columns: ["Date","Close"]. Uses OHLCV if present.
    cfg (optional): allows overriding default periods.
    """
    if df is None or df.empty:
        return pd.DataFrame(columns=["Date","Close"])  # guard

    out = df.copy()
    # Ensure proper types
    if not pd.api.types.is_datetime64_any_dtype(out["Date"]):
        out["Date"] = pd.to_datetime(out["Date"], errors="coerce")
    out = out.sort_values("Date").dropna(subset=["Date","Close"]).reset_index(drop=True)

    # Defaults (override via cfg)
    rsi_n = int((cfg or {}).get("rsi_period", 14))
    macd_fast = int((cfg or {}).get("macd_fast", 12))
    macd_slow = int((cfg or {}).get("macd_slow", 26))
    macd_sig  = int((cfg or {}).get("macd_signal", 9))
    bb_n = int((cfg or {}).get("bb_window", 20))
    bb_k = float((cfg or {}).get("bb_k", 2.0))
    sma_windows = (cfg or {}).get("sma_windows", [5, 20, 50])
    ema_windows = (cfg or {}).get("ema_windows", [12, 26])
    atr_n = int((cfg or {}).get("atr_period", 14))

    close = out["Close"].astype(float)

    # Returns
    out["ret_1"] = close.pct_change()
    out["ret_5"] = close.pct_change(5)

    # SMA/EMA
    for n in sma_windows:
        out[f"SMA_{n}"] = _sma(close, int(n))
    for n in ema_windows:
        out[f"EMA_{n}"] = _ema(close, int(n))

    # RSI
    out["RSI"] = _rsi(close, rsi_n)

    # MACD
    macd_df = _macd(close, macd_fast, macd_slow, macd_sig)
    out = pd.concat([out, macd_df], axis=1)

    # Bollinger
    bb_df = _bollinger(close, bb_n, bb_k)
    out = pd.concat([out, bb_df], axis=1)

    # ATR (if OHLC available)
    out["ATR"] = _atr(out, atr_n)

    # Final cleanup: drop warmup NaNs
    out = out.dropna().reset_index(drop=True)
    return out
  
