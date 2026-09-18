# BlackPod Battlestar — Captain's Cabin

A live, read-only product for following canonical mission evidence through the
Captain's Cabin and Battlestar Navigator V3. The repository directory and Python
package retain their historical Build Week names; the demo specification is
retired as the governing product scope.

[Product specification](docs/PRODUCT_SPEC.md) ·
[Live startup and operations](docs/LIVE_PRODUCT_RUNBOOK.md) ·
[Safety boundary](docs/SAFETY_BOUNDARY.md)

## Start the product

From this repository, install dependencies once:

```bash
make setup
npm --prefix ui ci
```

Point the reader at one existing canonical LIVE mission:

```bash
make cabin-live \
  CABIN_ARTIFACTS_ROOT=/absolute/path/to/artifacts \
  CABIN_MISSION_ID=your-existing-live-mission-id
```

Open [http://127.0.0.1:5174/](http://127.0.0.1:5174/). The configured source is
`<CABIN_ARTIFACTS_ROOT>/missions/<CABIN_MISSION_ID>/`; select the artifact root,
not the mission directory. Stop the process with **Ctrl+C**.

`make cabin-live` builds the UI and starts a loopback-only artifact reader. It
does **not** start a mission, record approval, acquire market data, call
ModelDock, or prepare a demo. With no source configured, it opens an honest
setup state instead of showing old demo evidence. Do not run `make live-mission`
merely to launch the Cabin: that historical orchestration
shortcut includes an explicit `APPROVE_HANDOFF` operation.

No `BATTLESTAR_PATH` or ModelDock service is needed to display an existing
mission. Battlestar remains the canonical owner of its domain logic and
Navigator renderer. Neither sibling repository is modified by the reader.

When separately authorized, narrative producers call **ModelDock**, not a
specific model. ModelDock owns model selection; `MODELDOCK_MODEL` is ignored
for new LIVE calls. Returned model identity is recorded provenance only.

## What “live” means here

The Cabin checks the explicitly selected mission every five seconds and
follows verified revisions automatically. It displays incomplete, running,
held, vetoed, failed, and approved states without requiring an approved-demo
package. There is no automatic selection of a different “latest” mission.

Reader connectivity, last verification, and the age of recorded mission
evidence are separate facts. A reachable reader does not make an old mission
current. Captured chart/portfolio timestamps and recorded ModelDock
provenance remain historical evidence, not assertions of a live quote feed or
present service health.

Unavailable or invalid source data never falls back to replay. Previously
verified evidence may remain visible with an explicit degraded/offline
warning; it is not relabeled as current. See the [runbook](docs/LIVE_PRODUCT_RUNBOOK.md)
for source configuration, development, and recovery.

## Scope and next steps

- Preserve the Cabin books, Mission Chart SVG overview, expanded Navigator V3,
  existing mission contracts, and SHADOW-only safety.
- Read and explain mission artifacts; do not start/resume missions, record
  operator approval, or change canonical evidence.
- Keep deterministic replay for explicit developer/historical review, outside
  normal product use.
- Add-symbol workflows and eventual trading integration are roadmap work.
  Neither is enabled or authorized by this read-only release.

The mission symbol is correlation metadata. The existing Oracle analyzes its
supported fleet; a Navigator reference chart does not turn that into
single-symbol Oracle evidence.

## Development and checks

```bash
# Terminal 1: selected artifact reader; uses an existing UI build if present
make cabin-reader \
  CABIN_ARTIFACTS_ROOT=/absolute/path/to/artifacts \
  CABIN_MISSION_ID=your-existing-live-mission-id

# Terminal 2: Vite, with /live proxied to the local reader
make cabin-dev
```

Open the URL printed by Vite. Normal development and production builds do not
run the judge workflow or bundle prepared demo evidence.

```bash
make test
make cabin-test
make cabin-build
make navigator-check-upstream BATTLESTAR_PATH=/path/to/read-only/battlestar
```

For explicit offline replay review, run:

```bash
make cabin-dev-replay BATTLESTAR_PATH=/path/to/read-only/battlestar
```

Open `?mode=replay` on the Vite URL.
The old `?mode=demo` query remains a compatibility alias, not the default.
Replay fixtures and legacy packaging commands remain available for regression
testing; they do not govern live-product acceptance. Browser setup and checks:
[Captain's Cabin](docs/CAPTAINS_CABIN.md).

## Documentation

- [Product specification and roadmap](docs/PRODUCT_SPEC.md)
- [Live product runbook](docs/LIVE_PRODUCT_RUNBOOK.md)
- [Architecture](docs/ARCHITECTURE.md)
- [Captain's Cabin presentation and verification](docs/CAPTAINS_CABIN.md)
- [Navigator V3 source mapping and update checks](docs/NAVIGATOR_V3_INTEGRATION.md)
- [Sentry Research: frozen 20/60 comparison and closeout evidence](docs/SENTRY_RESEARCH_CABIN.md)
- [Sentry scan results: isolated failures and recorded snapshot review](docs/SENTRY_SCAN_CABIN.md)
- [Supplemental Oracle market brief: source-linked ModelDock commentary](docs/ORACLE_MARKET_BRIEF.md)
- [Change history](docs/BUILD_WEEK_CHANGELOG.md)

Historical material is retained, not the current startup path:
[Build Week implementation history](docs/BUILD_WEEK_HISTORY.md),
[archived Demo Runbook](docs/DEMO_RUNBOOK.md), and
[archived LIVE Demo Runbook](docs/LIVE_DEMO_RUNBOOK.md).
