# BlackPod Navigator — Financial Ocean Prototype (MVP v0.1)

## Project Overview
Interactive 3D prototype that reimagines financial markets as a navigable ocean. The user pilots a ship that represents the current price; the wake is exact historical ticker data; a yellow dashed moving-average line is the navigational bearing. Zooming out transitions continuously from cinematic 3D ocean to a traditional top-down stock chart.

**This is not a game and not a trading simulator** — it is an alternative visualization of existing market data. The visualization is mathematically identical to underlying OHLC data.

## Goals (MVP v0.1)
A trader looking at the scene should immediately be able to answer:
- Is price above or below trend?
- How far from trend?
- Is volatility increasing?
- What is the broader trend direction?
- Where is recent support/resistance? *(deferred to v0.2)*

## Art Direction (from reference image)
- **Atmosphere:** dark cinematic ocean, soft sunset/horizon glow, deep blue water with subtle gradient toward warm horizon.
- **Ship:** realistic small vessel — dark/red hull, white cabin, leaves a clear white foam wake.
- **Wake trail:** color-segmented by relationship to MA:
  - Green when price > MA
  - Gray/white when price ≈ MA (within ±0.25%)
  - Red when price < MA
- **MA "bearing" line:** bright yellow dashed line projected onto the water plane, with floating price labels (e.g. 4,200 / 4,400 / 4,600) stacked along it as it recedes to horizon.
- **Water plane:** faint dashed grid lines (the chart projected onto the ocean).
- **Ship callout:** floating dark glass card next to the ship showing `PRICE (SHIP)`, value, % change vs MA, and Above/Near/Below MA.
- **UI panels:** dark glass (`#0d1218` with 80% opacity, subtle border), yellow accents `#facc15`, IBM Plex Sans typography.

## Technical Stack (user-confirmed)
- **Frontend:** React 19 + TypeScript + Vite, Tailwind v4, shadcn/ui, React Three Fiber + drei + postprocessing, Zustand for state, lucide-react icons.
- **Backend:** FastAPI + Python, `yfinance` for Yahoo Finance data, in-memory cache (no DB).
- **Fonts:** IBM Plex Sans (UI), IBM Plex Mono (numeric).

## Architecture Rules
```
Yahoo Finance  →  Data Engine (yfinance fetch + cache)
              →  Market Model (compute MA, ATR, % vs MA, trend slope)
              →  /api/ohlc  (JSON response with raw + derived fields)
              →  Frontend store (Zustand)
              →  Ocean Renderer (R3F, reads from store)
              →  Camera Controller (zoom transitions perspective ↔ top-down)
```
- The renderer **never** computes indicators. Indicators come from the backend market model.
- The scene is a self-contained module (`/scene/*`) with a clean prop API, so it can later be embedded into Battlestar without modification.

## Feature List

| Feature | Status | Spec |
|---|---|---|
| Market data backend (yfinance + MA + ATR) | done | [specs/market-data/document.md](./market-data/document.md) |
| Harbor panel + ticker/timeframe/MA controls | done | [specs/harbor-controls/document.md](./harbor-controls/document.md) |
| Ocean 3D scene (ship, wake, MA line, water, sky) | done | [specs/ocean-scene/document.md](./ocean-scene/document.md) |
| Camera zoom continuum (3D → top-down chart) | done | [specs/camera-zoom-chart/document.md](./camera-zoom-chart/document.md) |
| Production hardening (Phase 1) | done | see "Production Hardening" below |
| Weather, wind, buoys, fleet horizon | deferred to v0.2 | — |
| Capital allocation visualization | deferred to v0.2 | — |

## Production Hardening (Phase 1 — done)

Engineering work to make the prototype operable in real environments. See
[`DEPLOY.md`](../DEPLOY.md) and [`.env.example`](../.env.example).

| Item | Status | Notes |
|---|---|---|
| Provider adapter | done | `MarketDataProvider` interface; `synthetic` + `yfinance`, swap via `BPN_PROVIDER` |
| Stale-cache fallback | done | `BarCache.get_or_fetch` serves last-good data (labelled `stale`) when upstream fails |
| CORS allowlist + rate limiting | done | slowapi per-IP limits, origin allowlist + e2b regex, security headers |
| Deterministic test suites | done | backend pytest (41) + frontend vitest projection/market-model (12) |
| Deployment path | done | single-container Dockerfile (`/ready` HEALTHCHECK, non-root), `.env.example`, `DEPLOY.md` |
| Disclaimers | done | `/api/meta` + every `/api/ohlc` response + UI panel + global footer + `X-BPN-Disclaimer` header |
| Build hygiene | done | pinned backend reqs, lint/typecheck clean, frontend code-split (lazy WebGL scene, vendor chunks) |

## Out of Scope (MVP)
Weather animation, wind particles, support/resistance buoys, fleet horizon ships, capital allocation panels, all timeframes (MVP supports 1h / Daily / Weekly only).