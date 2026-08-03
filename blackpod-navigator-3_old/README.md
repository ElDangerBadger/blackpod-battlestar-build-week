# BlackPod Navigator

> A financial-market visualization that reimagines markets as a navigable ocean.
> The **ship** is the current price, its **wake** is price history, the **yellow
> dashed line** is the moving average (your bearing), and the **sea state**
> reflects volatility. Zoom continuously from a 3D ocean down to a conventional
> top-down chart.

> ⚠️ **Disclaimer:** BlackPod Navigator is a market-data *visualization* for
> educational and informational purposes only. It is **not investment advice**.
> Data may be delayed, synthetic, or inaccurate.

---

## What's in the box

| Part | Stack | Location |
|---|---|---|
| **Frontend** | React + TypeScript + Vite + React Three Fiber (Three.js) | `frontend/` |
| **Backend** | FastAPI + Python (yfinance / synthetic data providers) | `backend/` |
| **Specs** | Feature specs & architecture notes | `specs/` |
| **Deploy** | Single-container Dockerfile + detailed guide | `Dockerfile`, `DEPLOY.md` |

The frontend renders the ocean; the backend fetches OHLC data and computes the
moving average, ATR, and volatility "sea state". The renderer never computes
indicators — it only visualizes what the backend provides.

---

## Prerequisites

Choose **one** of the two paths below.

- **Option A — Docker only:** [Docker](https://docs.docker.com/get-docker/). Simplest; nothing else to install.
- **Option B — Local dev:**
  - [Python](https://www.python.org/) 3.11+ (for the backend)
  - [Bun](https://bun.sh/) **or** [Node.js](https://nodejs.org/) 20+ (for the frontend)

---

## Option A — Run as a standalone app (Docker) ✅ recommended

This builds the frontend, bundles it into the FastAPI backend, and serves the
whole app from **one container on one port**.

```bash
# From the project root (the folder containing this README)
docker build -t blackpod-navigator .

docker run --rm -p 8000:8000 blackpod-navigator
```

Then open **<http://localhost:8000>**. The UI and API share the same origin, so
there's nothing else to configure.

To persist the market-data cache across restarts, mount a volume:

```bash
docker run --rm -p 8000:8000 -v bpn-cache:/app/.cache blackpod-navigator
```

Want to run fully offline / without live network data? Use the deterministic
synthetic provider:

```bash
docker run --rm -p 8000:8000 -e BPN_PROVIDER=synthetic blackpod-navigator
```

---

## Option B — Run locally for development (two processes)

Run the backend and frontend in **two separate terminals**.

### 1. Backend (FastAPI, port 8000)

```bash
cd backend
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt  # or requirements-dev.txt to also get test tools
uvicorn src.main:app --reload --port 8000
```

Backend is now at <http://localhost:8000> (API docs at `/docs`).

### 2. Frontend (Vite dev server, port 3000)

```bash
cd frontend
bun install        # or: npm install
bun run dev        # or: npm run dev
```

Open **<http://localhost:3000>**. In local dev the frontend automatically talks
to the backend at `http://localhost:8000`.

---

## Configuration

All backend settings are environment variables with the `BPN_` prefix. Copy
[`.env.example`](./.env.example) to `.env` and edit as needed. The most useful:

| Variable | Default | Purpose |
|---|---|---|
| `BPN_PROVIDER` | `yfinance` | `yfinance` (live) or `synthetic` (offline/deterministic) |
| `BPN_CACHE_DIR` | `.cache` | On-disk cache dir (mount a volume to persist) |
| `BPN_CACHE_STALE_MAX_SECONDS` | `604800` | How long stale data may be served if the upstream fails |
| `BPN_ALLOWED_ORIGINS` | localhost set | Comma-separated browser origin allowlist (CORS) |
| `BPN_RATE_LIMIT_OHLC` | `60/minute` | Per-IP limit on the price endpoint |
| `BPN_ENVIRONMENT` | `development` | `production` hardens CORS |

Frontend build-time override: set `VITE_API_BASE` to point the browser at a
specific API URL (otherwise it auto-detects: same-origin in production,
`localhost:8000` in dev).

See **[`DEPLOY.md`](./DEPLOY.md)** for the full reference, health/readiness
probes, and Kubernetes examples.

---

## Using the app

- **Harbor (left):** pick a vessel (ticker). 10 instruments across equities,
  indices, commodities, and crypto.
- **Top bar:** choose timeframe (1H / Daily / Weekly) and moving-average period.
- **Vantage slider (bottom of the scene):** drag from **Close → Far → High →
  Chart** to zoom continuously from the 3D ocean to a flat top-down chart.
  - Watch the **ship rise, fall, and pitch** with the swell — the sea gets
    choppier in higher-volatility instruments.
- **Current Status (right):** price vs. MA, trend, ATR, and the sea-state label.
- **Ocean Exag.:** exaggerate wave amplitude for emphasis.

Scroll to zoom · left-drag to pan · right-drag to rotate · double-click to reset.

---

## Tests

```bash
# Backend — 41 tests (deterministic synthetic provider, network-free)
cd backend
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest

# Frontend — 20 tests (wave-height math + scene projection)
cd frontend
bun run test        # or: npm run test
```

---

## Key implementation notes

- **Wave-riding boat:** `frontend/src/scene/oceanHeight.ts` is a CPU mirror of
  the ocean's GLSL vertex shader, so the ship samples the *same* wave surface the
  GPU renders and bobs/pitches/rolls with it. Foam decals stay flat on the water.
- **Provider adapter:** swap live vs. synthetic data via `BPN_PROVIDER` with no
  code changes (`backend/src/providers/`).
- **Stale-on-failure cache:** if the upstream data source fails, the last known
  good data is served and clearly labelled as stale in the UI.

---

## Project layout

```
blackpod-navigator/
├── README.md            ← you are here
├── DEPLOY.md            ← full deployment / ops guide
├── .env.example         ← configuration reference
├── Dockerfile           ← single-container build (frontend + backend)
├── package.json         ← root convenience scripts
├── backend/
│   ├── requirements.txt
│   └── src/             ← FastAPI app, providers, cache, market model
├── frontend/
│   └── src/
│       ├── scene/       ← Three.js ocean, ship, wave sampler, camera
│       ├── ui/          ← harbor, status panel, vantage slider
│       └── ...
└── specs/               ← feature specs & architecture
```