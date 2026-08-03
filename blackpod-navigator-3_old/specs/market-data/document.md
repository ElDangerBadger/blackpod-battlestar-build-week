# Feature: Market Data Backend

## Overview
FastAPI backend that fetches Yahoo Finance OHLC data via `yfinance`, computes derived market-model fields (moving average, ATR, % vs MA, trend slope), caches results in-memory, and serves JSON to the frontend.

## Goals
- Single endpoint that returns everything the renderer needs: raw OHLC + derived fields + summary stats.
- Fast (<150 ms for cached, <2 s cold) — caches per `(ticker, timeframe)` for 60 s.
- Indicators computed server-side, never on the renderer.

## Scope
**In:** AAPL, MSFT, SPY, QQQ, NVDA, TSLA, GLD, SLV, BTC-USD, ETH-USD. Timeframes: `1h`, `1d`, `1wk`. MA periods: 20, 50, 100, 200, 250.
**Not in MVP:** intraday <1h, websocket live updates, support/resistance levels.

## API Contracts

### `GET /api/tickers`
Returns the supported watchlist.
```json
[
  {"symbol":"AAPL","name":"Apple Inc.","category":"equity"},
  ...
]
```

### `GET /api/ohlc?symbol=AAPL&timeframe=1d&ma=200`
- `symbol`: one of supported tickers
- `timeframe`: `1h` | `1d` | `1wk`
- `ma`: 20 | 50 | 100 | 200 | 250

Response:
```json
{
  "symbol": "AAPL",
  "name": "Apple Inc.",
  "timeframe": "1d",
  "ma_period": 200,
  "currency": "USD",
  "points": [
    {"t": 1700611200, "o": 189.1, "h": 190.4, "l": 188.2, "c": 189.7,
     "v": 49000000, "ma": 178.2, "atr": 2.41}
  ],
  "summary": {
    "last_price": 189.7,
    "last_ma": 178.2,
    "pct_vs_ma": 6.45,
    "position": "above",  // "above" | "near" | "below"
    "trend_slope_pct": 0.18,  // % change of MA over last 20 bars
    "volatility": "moderate", // "glass"|"gentle"|"moderate"|"high"|"storm"
    "atr": 2.41,
    "atr_pct": 1.27
  }
}
```

## Data Model / Calculations
- **MA:** simple moving average over close prices, period configurable.
- **ATR:** Wilder's 14-period ATR.
- **% vs MA:** `(last_close - last_ma) / last_ma * 100`.
- **Position thresholds:** `near` if `|pct_vs_ma| < 0.25`, else `above` / `below`.
- **Volatility bucket** (based on ATR as % of price):
  - `glass`: <0.5%
  - `gentle`: 0.5–1%
  - `moderate`: 1–2%
  - `high`: 2–4%
  - `storm`: >4%
- **Trend slope:** `(ma[-1] - ma[-20]) / ma[-20] * 100`.

## Yahoo Period Mapping
| timeframe | yfinance period | yfinance interval | bars target |
|-----------|-----------------|-------------------|-------------|
| `1h`      | `60d`           | `60m`             | ~1000       |
| `1d`      | `3y`            | `1d`              | ~750        |
| `1wk`     | `10y`           | `1wk`             | ~520        |

## Caching
Module-level dict `_cache: Dict[Tuple[str,str], Tuple[float, List[Bar]]]`. TTL 60 s. Thread-safe with `threading.Lock`. MA recomputation is cheap so we cache raw OHLC and re-derive on each request.

## Edge Cases
- yfinance returns empty → 404 with `{"detail": "no data"}`.
- Unsupported symbol/timeframe → 400.
- Bar count < ma_period → still return, mark first (period-1) bars with `ma: null`.
- Crypto symbols use `-USD` suffix internally; frontend uses friendly name.

## Acceptance Criteria
- All 10 tickers return data on `/api/ohlc?...&timeframe=1d&ma=200`.
- Response includes ≥ ma_period bars.
- `summary.position` matches sign of `pct_vs_ma`.
- Cold call <3 s, cached <200 ms.

## Test Plan
- Unit: ATR & SMA correctness on a fixed array.
- Integration: hit `/api/ohlc?symbol=SPY&timeframe=1d&ma=50` → expect 200, `points` non-empty, `summary.last_price > 0`.

## Status
Done.