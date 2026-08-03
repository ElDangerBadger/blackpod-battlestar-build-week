# Deploying BlackPod Navigator

BlackPod Navigator ships as a **single container**: the FastAPI backend serves
the built React/Three.js frontend as static files from the same origin, so there
is no CORS to configure in the common case.

> ⚠️ **Disclaimer:** BlackPod Navigator is a market-data *visualization* for
> educational and informational purposes only. It is **not investment advice**.
> Data may be delayed, synthetic, or inaccurate.

## 1. Configuration

All backend settings are environment variables with the `BPN_` prefix. See
[`.env.example`](./.env.example) for the full list. Key ones:

| Variable | Default | Purpose |
| --- | --- | --- |
| `BPN_PROVIDER` | `yfinance` | `yfinance` (live) or `synthetic` (offline/deterministic) |
| `BPN_ENVIRONMENT` | `development` | `production` rejects wildcard CORS |
| `BPN_ALLOWED_ORIGINS` | localhost set | Comma-separated browser origin allowlist |
| `BPN_ALLOW_E2B_PREVIEW` | `true` | Allow any `*.e2b.app` origin (disable in prod) |
| `BPN_CACHE_DIR` | `.cache` | On-disk cache (mount a volume to persist) |
| `BPN_CACHE_STALE_MAX_SECONDS` | `604800` | Max age stale data may be served when upstream fails |
| `BPN_RATE_LIMIT_OHLC` | `60/minute` | Per-IP limit on `/api/ohlc` |
| `VITE_API_BASE` | (auto) | Build-time frontend API base override |

The frontend auto-detects its API base: e2b preview → `8000-` subdomain,
localhost → `http://localhost:8000`, otherwise **same-origin** (production).

## 2. Build & run with Docker

```bash
# Build the image (multi-stage: node build → python runtime)
docker build -t blackpod-navigator .

# Run it
docker run --rm -p 8000:8000 \
  -e BPN_ENVIRONMENT=production \
  -e BPN_ALLOW_E2B_PREVIEW=false \
  -v bpn-cache:/app/.cache \
  blackpod-navigator
```

Then open <http://localhost:8000>. The API and UI share the origin.

The image runs as a non-root user, sets `BPN_STATIC_DIR=static`, and declares a
`HEALTHCHECK` that polls `/ready`.

## 3. Health & readiness probes

| Endpoint | Meaning | Use |
| --- | --- | --- |
| `GET /health` | Process is alive | Kubernetes liveness probe |
| `GET /ready` | Provider configured + registry loaded | Kubernetes readiness probe / LB |
| `GET /api/meta` | Version + provider + disclaimer | Smoke check |

Example Kubernetes probes:

```yaml
livenessProbe:
  httpGet: { path: /health, port: 8000 }
  initialDelaySeconds: 5
readinessProbe:
  httpGet: { path: /ready, port: 8000 }
  initialDelaySeconds: 10
```

## 4. Local development (two processes)

```bash
# Backend
cd backend
pip install -r requirements-dev.txt
uvicorn src.main:app --reload --port 8000

# Frontend (separate terminal)
cd frontend
bun install
bun run dev          # http://localhost:3000
```

## 5. Tests

```bash
# Backend (deterministic synthetic provider, network-free)
cd backend && PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest        # 41 tests

# Frontend (projection / market-model math)
cd frontend && bun run test                                  # 12 tests
```

## 6. Production hardening checklist

- [x] Provider adapter (swap `BPN_PROVIDER` without code changes)
- [x] Stale-on-failure cache fallback (served data is labelled `stale`)
- [x] CORS allowlist + per-IP rate limiting + security headers
- [x] Deterministic market-model & projection test suites
- [x] Single-container deployment path + `/health` & `/ready` probes
- [x] "Not investment advice" disclaimer in API + UI
- [x] Frontend code-splitting (lazy WebGL scene, vendor chunks)
- [ ] Set `BPN_ALLOWED_ORIGINS` to your real frontend origin(s)
- [ ] Disable `BPN_ALLOW_E2B_PREVIEW` outside preview environments
- [ ] Mount a persistent volume at `BPN_CACHE_DIR`
- [ ] Put a TLS-terminating reverse proxy / CDN in front