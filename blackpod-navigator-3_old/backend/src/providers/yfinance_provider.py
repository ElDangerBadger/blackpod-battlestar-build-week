"""yfinance-backed market data provider.

NOTE: yfinance is an *unofficial* scraper of Yahoo Finance and is unsuitable as
a sole source for a commercial production deployment (ToS/licensing + reliability
risk). It is retained here as the default development provider; production should
register a licensed feed implementing :class:`MarketDataProvider`.
"""
from __future__ import annotations

from typing import List

from ..market_model import Bar
from .base import MarketDataProvider, ProviderError, SYMBOLS, TIMEFRAMES


class YFinanceProvider(MarketDataProvider):
    name = "yfinance"

    def fetch_bars(self, symbol: str, timeframe: str) -> List[Bar]:
        self._validate(symbol, timeframe)

        import yfinance as yf  # imported lazily so tests/synthetic mode need no network stack

        yahoo_symbol = SYMBOLS[symbol]["yahoo"]
        cfg = TIMEFRAMES[timeframe]

        try:
            df = yf.download(
                yahoo_symbol,
                period=cfg["period"],
                interval=cfg["interval"],
                progress=False,
                auto_adjust=True,
                threads=False,
            )
        except Exception as e:  # noqa: BLE001 — normalize any upstream failure
            raise ProviderError(f"yfinance error: {e}") from e

        if df is None or df.empty:
            return []

        # yfinance may return MultiIndex columns for a single ticker — flatten.
        if hasattr(df.columns, "nlevels") and df.columns.nlevels > 1:
            df.columns = [c[0] if isinstance(c, tuple) else c for c in df.columns]

        bars: List[Bar] = []
        for ts, row in df.iterrows():
            try:
                o = float(row["Open"])
                h = float(row["High"])
                low = float(row["Low"])
                c = float(row["Close"])
                v = float(row["Volume"]) if "Volume" in row and row["Volume"] == row["Volume"] else 0.0
            except (KeyError, ValueError, TypeError):
                continue
            if any(x != x for x in (o, h, low, c)):  # NaN guard
                continue
            bars.append(Bar(t=int(ts.timestamp()), o=o, h=h, l=low, c=c, v=v))

        return bars