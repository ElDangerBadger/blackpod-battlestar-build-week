"""Provider interface + the shared instrument / timeframe registry."""
from __future__ import annotations

import abc
from typing import Dict, List

from ..market_model import Bar


class ProviderError(RuntimeError):
    """Raised when an upstream data source fails (network, rate-limit, parse).

    The cache layer catches this to decide whether to serve stale data.
    """


# --- Instrument registry --------------------------------------------------
# The public symbol is decoupled from the provider-specific ticker so different
# providers can map them differently (e.g. yfinance uses "BTC-USD").
TICKERS: List[dict] = [
    {"symbol": "AAPL", "name": "Apple Inc.",      "category": "equity",    "yahoo": "AAPL"},
    {"symbol": "MSFT", "name": "Microsoft Corp.", "category": "equity",    "yahoo": "MSFT"},
    {"symbol": "NVDA", "name": "NVIDIA Corp.",    "category": "equity",    "yahoo": "NVDA"},
    {"symbol": "TSLA", "name": "Tesla Inc.",      "category": "equity",    "yahoo": "TSLA"},
    {"symbol": "SPY",  "name": "S&P 500 ETF",     "category": "index",     "yahoo": "SPY"},
    {"symbol": "QQQ",  "name": "Nasdaq-100 ETF",  "category": "index",     "yahoo": "QQQ"},
    {"symbol": "GLD",  "name": "Gold ETF",        "category": "commodity", "yahoo": "GLD"},
    {"symbol": "SLV",  "name": "Silver ETF",      "category": "commodity", "yahoo": "SLV"},
    {"symbol": "BTC",  "name": "Bitcoin (USD)",   "category": "crypto",    "yahoo": "BTC-USD"},
    {"symbol": "ETH",  "name": "Ethereum (USD)",  "category": "crypto",    "yahoo": "ETH-USD"},
]
SYMBOLS: Dict[str, dict] = {t["symbol"]: t for t in TICKERS}

# Supported timeframes → coarse fetch hints (period/interval are yfinance-style
# but a provider is free to interpret them however it needs).
TIMEFRAMES: Dict[str, dict] = {
    "1h":  {"period": "60d", "interval": "60m"},
    "1d":  {"period": "3y",  "interval": "1d"},
    "1wk": {"period": "10y", "interval": "1wk"},
}


def list_tickers() -> List[dict]:
    """Public ticker metadata (no provider-specific fields)."""
    return [{k: t[k] for k in ("symbol", "name", "category")} for t in TICKERS]


class MarketDataProvider(abc.ABC):
    """Abstract OHLCV source. Implementations must be side-effect free per call
    and raise :class:`ProviderError` on any upstream failure."""

    #: human-readable provider name, surfaced in API metadata
    name: str = "abstract"

    @abc.abstractmethod
    def fetch_bars(self, symbol: str, timeframe: str) -> List[Bar]:
        """Return chronologically ordered bars (oldest first) for *symbol*.

        Args:
            symbol: a public symbol present in :data:`SYMBOLS`.
            timeframe: a key present in :data:`TIMEFRAMES`.

        Raises:
            ValueError: for unknown symbol/timeframe (caller error).
            ProviderError: for upstream failures (network/rate-limit/parse).
        """

    # Shared validation helper for implementations.
    @staticmethod
    def _validate(symbol: str, timeframe: str) -> None:
        if symbol not in SYMBOLS:
            raise ValueError(f"unsupported symbol: {symbol}")
        if timeframe not in TIMEFRAMES:
            raise ValueError(f"unsupported timeframe: {timeframe}")