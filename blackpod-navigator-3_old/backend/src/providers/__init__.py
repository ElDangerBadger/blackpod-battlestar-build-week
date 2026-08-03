"""Market-data provider package.

A provider is any source of OHLCV bars. The rest of the application depends only
on the :class:`MarketDataProvider` interface, so the underlying source (yfinance,
a licensed feed, or a deterministic synthetic generator) can be swapped via the
``BPN_PROVIDER`` environment variable without touching the API or renderer.
"""
from __future__ import annotations

from functools import lru_cache

from ..config import get_settings
from .base import (
    MarketDataProvider,
    ProviderError,
    TIMEFRAMES,
    TICKERS,
    SYMBOLS,
)


@lru_cache
def get_provider() -> MarketDataProvider:
    """Return the configured provider singleton."""
    name = get_settings().provider.lower()
    if name == "synthetic":
        from .synthetic_provider import SyntheticProvider

        return SyntheticProvider()
    if name in ("yfinance", "yahoo"):
        from .yfinance_provider import YFinanceProvider

        return YFinanceProvider()
    raise ValueError(f"unknown provider: {name!r}")


__all__ = [
    "MarketDataProvider",
    "ProviderError",
    "TIMEFRAMES",
    "TICKERS",
    "SYMBOLS",
    "get_provider",
]