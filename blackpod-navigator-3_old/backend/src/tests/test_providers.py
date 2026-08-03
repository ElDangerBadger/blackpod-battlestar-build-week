"""Tests for the provider abstraction + synthetic provider determinism."""
from __future__ import annotations

import pytest

from src.providers import SYMBOLS, TIMEFRAMES
from src.providers.base import MarketDataProvider, list_tickers
from src.providers.synthetic_provider import SyntheticProvider


def test_synthetic_is_a_provider():
    assert isinstance(SyntheticProvider(), MarketDataProvider)


def test_synthetic_deterministic():
    p = SyntheticProvider()
    a = p.fetch_bars("SPY", "1d")
    b = p.fetch_bars("SPY", "1d")
    assert len(a) == len(b) > 0
    assert [bar.c for bar in a] == [bar.c for bar in b]


def test_synthetic_distinct_series_per_symbol():
    p = SyntheticProvider()
    spy = [bar.c for bar in p.fetch_bars("SPY", "1d")]
    qqq = [bar.c for bar in p.fetch_bars("QQQ", "1d")]
    assert spy != qqq


def test_synthetic_bars_are_ordered_and_valid():
    p = SyntheticProvider()
    bars = p.fetch_bars("AAPL", "1d")
    # chronological
    assert all(bars[i].t < bars[i + 1].t for i in range(len(bars) - 1))
    # OHLC sanity: high >= max(o,c), low <= min(o,c), positive prices
    for bar in bars:
        assert bar.h >= max(bar.o, bar.c) - 1e-9
        assert bar.l <= min(bar.o, bar.c) + 1e-9
        assert bar.c > 0 and bar.o > 0


def test_synthetic_timeframe_bar_counts_differ():
    p = SyntheticProvider()
    assert len(p.fetch_bars("SPY", "1h")) != len(p.fetch_bars("SPY", "1wk"))


@pytest.mark.parametrize("bad_symbol", ["NOPE", "", "spyx"])
def test_invalid_symbol_raises_valueerror(bad_symbol):
    p = SyntheticProvider()
    with pytest.raises(ValueError):
        p.fetch_bars(bad_symbol, "1d")


def test_invalid_timeframe_raises_valueerror():
    p = SyntheticProvider()
    with pytest.raises(ValueError):
        p.fetch_bars("SPY", "13m")


def test_registry_consistency():
    assert set(SYMBOLS.keys()) == {t["symbol"] for t in list_tickers()}
    # public ticker metadata must not leak provider-specific fields
    for t in list_tickers():
        assert set(t.keys()) == {"symbol", "name", "category"}
    assert "1d" in TIMEFRAMES