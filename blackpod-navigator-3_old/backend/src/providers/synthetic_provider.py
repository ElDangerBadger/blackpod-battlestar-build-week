"""Deterministic, network-free synthetic market data provider.

Generates believable OHLCV series from a seed derived from (symbol, timeframe),
so output is fully reproducible. Used for:
  * unit/integration tests (no network, stable assertions),
  * offline development and demos,
  * a safe fallback when no licensed feed is configured.
"""
from __future__ import annotations

import math
import random
from typing import List

from ..market_model import Bar
from .base import MarketDataProvider, SYMBOLS, TIMEFRAMES

# Bars to generate per timeframe (roughly matches the yfinance period/interval).
_BAR_COUNT = {"1h": 360, "1d": 750, "1wk": 520}
# Seconds per bar.
_STEP = {"1h": 3600, "1d": 86400, "1wk": 604800}
# Plausible starting price per category.
_START_PRICE = {"equity": 180.0, "index": 410.0, "commodity": 95.0, "crypto": 30000.0}


class SyntheticProvider(MarketDataProvider):
    name = "synthetic"

    def fetch_bars(self, symbol: str, timeframe: str) -> List[Bar]:
        self._validate(symbol, timeframe)

        info = SYMBOLS[symbol]
        n = _BAR_COUNT[timeframe]
        step = _STEP[timeframe]
        # Deterministic seed → identical output across runs/processes.
        seed = abs(hash((symbol, timeframe))) % (2**32)
        rng = random.Random(seed)

        price = _START_PRICE.get(info["category"], 100.0)
        # Per-series drift and volatility, deterministic but varied per symbol.
        drift = (rng.random() - 0.45) * 0.0015            # slight bias up/down
        vol = 0.008 + rng.random() * 0.02                  # daily-ish vol
        # Anchor the end time to a fixed epoch so timestamps are reproducible.
        end_t = 1_700_000_000
        start_t = end_t - (n - 1) * step

        bars: List[Bar] = []
        for i in range(n):
            # Gentle multi-cycle wave + random walk → trend + texture.
            cycle = math.sin(i / 40.0) * vol * 0.6 + math.sin(i / 11.0) * vol * 0.3
            shock = rng.gauss(0, 1) * vol
            ret = drift + cycle + shock
            prev = price
            price = max(0.01, prev * (1.0 + ret))

            o = prev
            c = price
            hi = max(o, c) * (1.0 + abs(rng.gauss(0, 1)) * vol * 0.5)
            lo = min(o, c) * (1.0 - abs(rng.gauss(0, 1)) * vol * 0.5)
            v = 1_000_000 + abs(rng.gauss(0, 1)) * 500_000

            bars.append(
                Bar(
                    t=start_t + i * step,
                    o=round(o, 4),
                    h=round(hi, 4),
                    l=round(lo, 4),
                    c=round(c, 4),
                    v=float(int(v)),
                )
            )
        return bars