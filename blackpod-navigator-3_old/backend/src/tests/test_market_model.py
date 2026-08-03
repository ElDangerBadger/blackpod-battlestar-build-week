"""Deterministic unit tests for the market model (indicators + summary)."""
from __future__ import annotations

import math

from src.market_model import (
    Bar,
    derive_summary,
    enrich_bars,
    position_label,
    simple_moving_average,
    volatility_bucket,
    wilder_atr,
)


# --- SMA -------------------------------------------------------------------
def test_sma_basic_window():
    closes = [1, 2, 3, 4, 5]
    out = simple_moving_average(closes, 3)
    assert out[0] is None and out[1] is None
    assert out[2] == 2.0  # (1+2+3)/3
    assert out[3] == 3.0  # (2+3+4)/3
    assert out[4] == 4.0  # (3+4+5)/3


def test_sma_rolling_matches_naive():
    closes = [float(x) for x in range(1, 51)]
    period = 10
    out = simple_moving_average(closes, period)
    for i in range(period - 1, len(closes)):
        expected = sum(closes[i - period + 1 : i + 1]) / period
        assert math.isclose(out[i], expected, rel_tol=1e-12)


def test_sma_period_longer_than_series():
    assert simple_moving_average([1, 2, 3], 5) == [None, None, None]


def test_sma_invalid_period():
    assert simple_moving_average([1, 2, 3], 0) == [None, None, None]


# --- Wilder ATR ------------------------------------------------------------
def test_wilder_atr_constant_range():
    # Each bar has a true range of exactly 2.0 → ATR converges to 2.0.
    n = 30
    highs = [101.0] * n
    lows = [99.0] * n
    closes = [100.0] * n
    out = wilder_atr(highs, lows, closes, period=14)
    assert out[13] is None  # needs period+1 points before first value at index `period`
    assert out[14] is not None
    assert math.isclose(out[14], 2.0, rel_tol=1e-9)
    assert math.isclose(out[-1], 2.0, rel_tol=1e-9)


def test_wilder_atr_insufficient_data():
    out = wilder_atr([1, 2], [0, 1], [1, 1], period=14)
    assert out == [None, None]


def test_wilder_atr_smoothing_formula():
    # Verify the Wilder recursive step explicitly.
    highs = [10, 11, 12, 13, 14, 15]
    lows = [8, 9, 10, 11, 12, 13]
    closes = [9, 10, 11, 12, 13, 14]
    period = 2
    out = wilder_atr(highs, lows, closes, period=period)
    # TR[i] for i>=1 = max(h-l, |h-prev_c|, |l-prev_c|); here h-l=2 always,
    # |h-prev_c| = 2, |l-prev_c| = 0 → TR = 2 for all i>=1.
    # Initial ATR = mean(TR[1..2]) = 2; recursion keeps it at 2.
    assert out[period] is not None
    assert math.isclose(out[period], 2.0, rel_tol=1e-9)
    assert math.isclose(out[-1], 2.0, rel_tol=1e-9)


# --- Volatility buckets (boundary behavior) --------------------------------
def test_volatility_buckets():
    assert volatility_bucket(0.0) == "glass"
    assert volatility_bucket(0.49) == "glass"
    assert volatility_bucket(0.5) == "gentle"
    assert volatility_bucket(0.99) == "gentle"
    assert volatility_bucket(1.0) == "moderate"
    assert volatility_bucket(1.99) == "moderate"
    assert volatility_bucket(2.0) == "high"
    assert volatility_bucket(3.99) == "high"
    assert volatility_bucket(4.0) == "storm"
    assert volatility_bucket(99.0) == "storm"


# --- Position label (0.25% dead-zone) --------------------------------------
def test_position_label_thresholds():
    assert position_label(0.0) == "near"
    assert position_label(0.24) == "near"
    assert position_label(-0.24) == "near"
    assert position_label(0.249) == "near"
    assert position_label(0.25) == "above"   # dead-zone is strict: abs() < 0.25
    assert position_label(-0.25) == "below"
    assert position_label(0.26) == "above"
    assert position_label(-0.26) == "below"


# --- enrich_bars + derive_summary ------------------------------------------
def _ramp_bars(n: int, start: float = 100.0, step: float = 1.0) -> list:
    bars = []
    price = start
    for i in range(n):
        o = price
        c = price + step
        bars.append(Bar(t=1_700_000_000 + i * 86400, o=o, h=c + 0.5, l=o - 0.5, c=c, v=1000))
        price = c
    return bars


def test_enrich_bars_populates_indicators():
    bars = _ramp_bars(60)
    enrich_bars(bars, ma_period=20)
    assert bars[0].ma is None
    assert bars[19].ma is not None
    assert bars[-1].ma is not None
    assert bars[-1].atr is not None


def test_derive_summary_uptrend_above_ma():
    bars = _ramp_bars(60)  # monotonically rising
    enrich_bars(bars, ma_period=20)
    s = derive_summary(bars, ma_period=20)
    assert s["position"] == "above"      # price leads a rising MA
    assert s["pct_vs_ma"] > 0
    assert s["trend_slope_pct"] > 0      # MA rising
    assert s["bar_count"] == 60
    assert s["ma_period"] == 20


def test_derive_summary_empty():
    assert derive_summary([], ma_period=20) == {}


def test_derive_summary_downtrend_below_ma():
    bars = _ramp_bars(60, start=200.0, step=-1.0)  # monotonically falling
    enrich_bars(bars, ma_period=20)
    s = derive_summary(bars, ma_period=20)
    assert s["position"] == "below"
    assert s["pct_vs_ma"] < 0
    assert s["trend_slope_pct"] < 0