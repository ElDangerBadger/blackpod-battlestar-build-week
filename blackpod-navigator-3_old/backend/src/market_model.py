"""Market model: indicators and summary stats for BlackPod Navigator."""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Tuple


@dataclass
class Bar:
    t: int          # unix seconds
    o: float
    h: float
    l: float
    c: float
    v: float
    ma: Optional[float] = None
    atr: Optional[float] = None


def simple_moving_average(closes: List[float], period: int) -> List[Optional[float]]:
    n = len(closes)
    out: List[Optional[float]] = [None] * n
    if period <= 0 or n < period:
        return out
    s = sum(closes[:period])
    out[period - 1] = s / period
    for i in range(period, n):
        s += closes[i] - closes[i - period]
        out[i] = s / period
    return out


def wilder_atr(highs: List[float], lows: List[float], closes: List[float], period: int = 14) -> List[Optional[float]]:
    n = len(closes)
    out: List[Optional[float]] = [None] * n
    if n < period + 1:
        return out
    # True ranges
    trs: List[float] = [highs[0] - lows[0]]
    for i in range(1, n):
        tr = max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i - 1]),
            abs(lows[i] - closes[i - 1]),
        )
        trs.append(tr)
    # Wilder smoothing
    atr = sum(trs[1:period + 1]) / period
    out[period] = atr
    for i in range(period + 1, n):
        atr = (atr * (period - 1) + trs[i]) / period
        out[i] = atr
    return out


def volatility_bucket(atr_pct: float) -> str:
    if atr_pct < 0.5:
        return "glass"
    if atr_pct < 1.0:
        return "gentle"
    if atr_pct < 2.0:
        return "moderate"
    if atr_pct < 4.0:
        return "high"
    return "storm"


def position_label(pct_vs_ma: float) -> str:
    if abs(pct_vs_ma) < 0.25:
        return "near"
    return "above" if pct_vs_ma > 0 else "below"


def derive_summary(bars: List[Bar], ma_period: int) -> dict:
    if not bars:
        return {}
    last = bars[-1]
    last_price = last.c
    last_ma = last.ma if last.ma is not None else last_price
    pct_vs_ma = (last_price - last_ma) / last_ma * 100.0 if last_ma else 0.0
    atr = last.atr or 0.0
    atr_pct = (atr / last_price * 100.0) if last_price else 0.0

    # Trend slope: MA[-1] vs MA[-20] (or earliest available)
    slope_lookback = 20
    ma_now = last.ma
    ma_then: Optional[float] = None
    if ma_now is not None and len(bars) > slope_lookback:
        idx = len(bars) - 1 - slope_lookback
        ma_then = bars[idx].ma
    trend_slope_pct = 0.0
    if ma_now is not None and ma_then is not None and ma_then != 0:
        trend_slope_pct = (ma_now - ma_then) / ma_then * 100.0

    return {
        "last_price": round(last_price, 4),
        "last_ma": round(last_ma, 4) if last_ma else None,
        "pct_vs_ma": round(pct_vs_ma, 4),
        "position": position_label(pct_vs_ma),
        "trend_slope_pct": round(trend_slope_pct, 4),
        "volatility": volatility_bucket(atr_pct),
        "atr": round(atr, 4),
        "atr_pct": round(atr_pct, 4),
        "ma_period": ma_period,
        "bar_count": len(bars),
    }


def enrich_bars(bars: List[Bar], ma_period: int) -> List[Bar]:
    closes = [b.c for b in bars]
    highs = [b.h for b in bars]
    lows = [b.l for b in bars]
    mas = simple_moving_average(closes, ma_period)
    atrs = wilder_atr(highs, lows, closes, period=14)
    for i, b in enumerate(bars):
        b.ma = mas[i]
        b.atr = atrs[i]
    return bars