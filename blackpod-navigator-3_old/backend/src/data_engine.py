"""Data engine: orchestrates the configured provider through the cache layer.

Kept as a thin facade so callers (the API) depend on a stable surface while the
provider and cache internals can evolve independently.
"""
from __future__ import annotations

from typing import List

from .cache import CacheResult, get_cache
from .market_model import Bar
from .providers import (
    SYMBOLS,
    TICKERS,
    TIMEFRAMES,
    get_provider,
)
from .providers.base import list_tickers

__all__ = [
    "fetch_bars",
    "fetch_bars_cached",
    "list_tickers",
    "SYMBOLS",
    "TICKERS",
    "TIMEFRAMES",
]


def fetch_bars_cached(symbol: str, timeframe: str) -> CacheResult:
    """Fetch bars through the cache (TTL + stale-on-failure fallback)."""
    provider = get_provider()
    return get_cache().get_or_fetch(symbol, timeframe, provider.fetch_bars)


def fetch_bars(symbol: str, timeframe: str) -> List[Bar]:
    """Backwards-compatible helper returning just the bars."""
    return fetch_bars_cached(symbol, timeframe).bars
