# Feature: Harbor Panel + Controls

## Overview
The Harbor is the persistent left panel listing supported tickers. Right side hosts the Current Status card (price, MA, %vs MA, position). Top toolbar has MA period selector + timeframe selector + ocean exaggeration slider.

## Goals
- One-click ticker switch.
- Read-at-a-glance status (matches the reference image's right-hand "CURRENT STATUS" card).
- Minimal cognitive load — dark glass panels, IBM Plex Sans, yellow accents.

## UX Layout
```
┌──────────────────────────────────────────────────────────────────────┐
│  ⛵ BLACKPOD NAVIGATOR     [Timeframe] [MA period] [Ocean exag]      │
├──────────┬──────────────────────────────────────────────┬────────────┤
│ HARBOR   │                                              │ CURRENT    │
│ ▸ AAPL   │              3D OCEAN SCENE                  │ STATUS     │
│ ▸ MSFT   │     (ship + wake + MA bearing line)          │ Price …    │
│ ▸ SPY *  │                                              │ MA (200)…  │
│ ▸ QQQ    │                                              │ Δ …        │
│ ▸ NVDA   │                                              │ % vs MA…   │
│ ▸ TSLA   │                                              │ Position…  │
│ ▸ GLD    │                                              │            │
│ ▸ SLV    │                                              │ HOW TO READ│
│ ▸ BTC    │                                              │ …          │
│ ▸ ETH    │                                              │            │
└──────────┴──────────────────────────────────────────────┴────────────┘
```

## Components
- `HarborPanel.tsx` — list with category dividers (Equities / Commodities / Crypto). Each row shows symbol, name, mini-sparkline-color dot (green/red/gray based on `position` after data loads).
- `StatusPanel.tsx` — Price, MA(period), Difference, % vs MA, Position. Numbers in IBM Plex Mono.
- `Toolbar.tsx` — Timeframe segmented control (1H | D | W), MA period pills (20/50/100/200/250), ocean exaggeration slider 0–2.
- `HowToRead.tsx` — collapsible "How to Read" card below status, content from the reference image (5 numbered points).

## State (Zustand `useMarketStore`)
```ts
{
  symbol: 'SPY',
  timeframe: '1d',
  maPeriod: 200,
  oceanExaggeration: 1,
  data: OhlcResponse | null,
  loading: boolean,
  error: string | null,
  setSymbol, setTimeframe, setMaPeriod, setOceanExag, fetchData
}
```

## API Calls
On any of (symbol, timeframe, maPeriod) change → debounced `fetchData()` → `GET /api/ohlc?symbol=...&timeframe=...&ma=...`.

## Edge Cases
- Loading: skeleton shimmer on harbor row dots + status panel.
- Error: red border on status panel + retry button.
- Backend cold start: keep last data visible while reloading.

## Acceptance Criteria
- Clicking ticker swaps scene contents within 1 s on warm cache.
- MA period change does NOT refetch raw data, only re-derives client-side from backend response (backend recomputes server-side — accept either approach; MVP refetches).
- Status panel updates color: green (above), gray (near), red (below).

## Status
Done.