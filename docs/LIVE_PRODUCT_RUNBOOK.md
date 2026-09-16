# Live product runbook

This is the current local startup path for the read-only Captain's Cabin.
The [product specification](PRODUCT_SPEC.md) supersedes the Build Week/demo
scope. Starting the Cabin does not run a mission or grant operator approval.

## 1. Install the local application dependencies

From the repository root, use Python 3.11 or newer, Node/npm, and Make:

```bash
make setup
npm --prefix ui ci
```

`make setup` creates the local `.venv` and installs this repository. It does not
install into Battlestar or ModelDock. Viewing an existing mission does not need
a running ModelDock service or a `BATTLESTAR_PATH` setting.

## 2. Select one existing canonical LIVE mission

The reader expects:

```text
<artifact root>/missions/<mission ID>/
    request/mission_request.json
    mission_snapshot.json
    snapshots/mission_snapshot-rNNNN.json
    ... recorded component artifacts ...
```

Set the root above `missions/`, not the mission's own directory. Use an
explicit mission ID; the reader never scans directories to choose a newest
mission. Navigator may independently review available fleet chart captures;
the reader's mission correlation does not restrict the product to one reviewable
symbol. Mission-wide symbol semantics and aggregation remain future work.
The source must be a genuine
`LIVE` mission in the canonical store
format, with a valid snapshot chain and captured-artifact integrity. Do not
change a REPLAY request's mode or timestamps to make it appear live.

```bash
make cabin-live \
  CABIN_ARTIFACTS_ROOT=/absolute/path/to/artifacts \
  CABIN_MISSION_ID=your-existing-live-mission-id
```

Open [http://127.0.0.1:5174/](http://127.0.0.1:5174/). This command builds the
UI without demo assets, then starts the loopback reader. Keep the terminal
running; **Ctrl+C** stops it. The browser follows that mission every five
seconds. To select a different mission, stop and restart the reader with the
new explicit source configuration.

The equivalent direct reader command, after a build, is:

```bash
.venv/bin/python3.11 -m blackpod_build_week.cabin_reader \
  --artifacts-root /absolute/path/to/artifacts \
  --mission-id your-existing-live-mission-id \
  --ui-root ui/dist \
  --port 5174
```

The reader binds only `127.0.0.1`; there is no public-host option. It reads
source artifacts and creates verified publication bytes in memory, not in the
mission directory. It does not import or run the mission producer, start
ModelDock, acquire quotes, or repair source files.

After updating reader code, stop and restart this reader to load the new code;
rebuilding the UI alone does not replace an already-running Python process.
Already supported new artifact publications are picked up by normal polling.
Saved Navigator fleet captures require no running provider or ModelDock service.

### If you have not selected a source yet

Run `make cabin-live` without source variables to open the setup state. An
unconfigured reader is not a fresh mission and displays no fallback demo.
Choose the intended real artifact root and mission ID before expecting mission
evidence. Historical local LIVE missions may still be old or fail integrity
checks; their mere presence does not prove current operation.

Do **not** use `make live-mission` as a startup fix. That retained historical
workflow records an explicit `APPROVE_HANDOFF` event and writes mission state.
Creating or resuming a real mission is a separate operator-authorized workflow,
outside this release's read-only Cabin boundary. Do not alter request, Council,
Governor, or operator inputs to force approval or satisfy a display gate.

## 3. Interpret current state honestly

### Current local source — completed no-trade run, 2026-09-15

Navigator's first Harbor row is AAPL. The user-authorized LIVE pipeline test
completed through Council and Governor, without operator approval or trading:

```bash
make cabin-live \
  CABIN_ARTIFACTS_ROOT=artifacts/no-trade-live-20260915 \
  CABIN_MISSION_ID=mission-live-aapl-20260915-002
```

These artifacts are local and ignored by Git; this is not a shipped sample
pack. Starting this command only views the existing run and never repeats it.

- Oracle acquired its canonical market ETF fleet at **2026-09-15 23:05:20 UTC**
  (16:05:20 PDT) and reached native `READY`. Fourteen symbols were used;
  VXZ, IWF, IWD, IWM, MTUM, USMV, and QUAL were excluded. Missing prior Oracle
  measurements remain an explicit warning. This is broad market context,
  **not AAPL-specific Oracle analysis**.
- ModelDock completed real local MLX inference with
  `gemma-4-e4b-it-4bit`, revision `cc3b666c01c20395e0dcebd53854504c7d9821f9`,
  at **23:06:31 UTC**. The accepted narrative selects five source-linked
  Oracle facts, preserves warnings, and records `mocked: false`.
  Trace: `fa1c4493-d307-4a13-aa7e-1b675703737a`.
- Navigator uses the earlier verified **751-bar AAPL capture**, from
  **22:36:41 UTC**, spanning 2023-09-18 through 2026-09-15. A fresh supplemental
  chart request was canceled at approval, so no second provider fetch was
  performed. The exact earlier bytes and original timestamp were attached as
  `LOCAL_JSON`, with source identity
  `navigator-capture-mission-live-aapl-20260915-001`. The preserved yfinance
  provider/cache metadata describes that original capture, not a new fetch.
  The transparent overview and expanded Navigator's original/default selection
  continue to consume it.
- On **September 15 at 18:14:37 PDT** (September 16, 01:14:37 UTC), an explicitly
  authorized canonical Navigator capture added the other **14 interval/MA
  pairs**: hourly/daily/weekly bars with MA20/50/100/200/250. The original daily
  MA250 artifact, Cabin context, and mission snapshot remain byte-identical.
  The expanded view's selectors consume the hash-bound supplemental catalog;
  the browser does not fetch provider data or calculate alternate MAs.
  Hourly captures contain 420 bars through September 15 at 19:30 UTC; weekly
  captures contain 523 bars through the week labeled September 14. The four
  new daily captures contain 750 bars and end on September 14, **one bar earlier
  than the preserved original daily/MA250 capture**. These are the provider's
  exact responses, not synchronized series or streaming quotes. Each selection
  displays its own capture/latest-bar timestamps and provenance. See the
  [capture catalog guide](NAVIGATOR_CAPTURE_CATALOG.md) for acquisition and
  validation boundaries. The temporary provider service was stopped afterward;
  viewing the saved captures needs only the Cabin reader.
- On **September 16**, a separately authorized market-only acquisition added
  **315 datasets for all 21 observed fleet symbols**, covering hourly/daily/weekly
  intervals and MA20/50/100/200/250. Navigator's review-symbol picker and
  Fleet/Admiral **Review chart** buttons select these exact captures. Each
  capture retains its own time and provenance; this is not streaming data.
  The original AAPL reference, prior 14 variants, mission state, and analytical
  exclusions remain unchanged. Only the missing symbols were added to canonical
  Navigator's registry; no ModelDock inference or mission workflow was run.
  See the [fleet capture guide](NAVIGATOR_CAPTURE_CATALOG.md#recorded-fleet-symbol-selection--september-16).
- The Council mandate explicitly denies trading authority: `ok: false`,
  `allowed_sides: []`, `max_trades: 0`, and `risk_posture: READ_ONLY`.
  The authorized stop target is `GOVERNOR`, before any operator approval.
- **Actual result: `HELD`, revision 9, phase `GOVERNOR`, terminal.**
  Oracle, ModelDock, Council, and Governor all completed technically.
  Council's native state and Governor's disposition are `BLOCKED` because of
  `mandate:READ_ONLY_DATA_RUN_NO_TRADING_AUTHORITY`. Governor's allowed next
  step is `NONE`; this is the expected safety outcome, not a technical failure.
- Operator routing is `CLOSED_BLOCKED`, with action `NOT_STARTED` and no
  approval identity or action. Operational Navigator is `NOT_STARTED`, with
  no SHADOW handoff or plan. The supplemental chart is separate from that
  operational stage; no broker/order execution or portfolio mutation occurred.
- Portfolio context remains `NOT_CONFIGURED`; no holdings were invented.

The chart is a captured observation, not a streaming quote. The reader follows
mission revisions but does not refresh this market capture. Evidence-age
warnings will appear naturally as the run ages. A scheduled producer, recurring
captures, and a production market-data service remain separate future work.

The initial `artifacts/initial-live-20260915` mission,
`mission-live-aapl-20260915-001`, remains a preserved revision-5 failure at
Oracle narrative enrichment. Its market capture and sanitized failure evidence
were not rewritten. The exact rejected text was intentionally not retained.
Before this new run, Build Week fixed LIVE prompt guidance to use a real,
validated catalog example and added allowlisted validation rule/field
diagnostics. Strict narrative/authority checks remain unchanged, as do the
recorded REPLAY prompt bytes. No fallback narrative replaces model output.

To perform another authorized producer run, select **new** mission/request IDs
and explicit no-trade policy/context inputs, use `mission-run --with-modeldock
--through GOVERNOR`, and supply the pinned local model configuration. This is
a separate producer operation, not Cabin startup. Do not overwrite past runs,
weaken validation, or change the mandate merely to obtain a green display.

The earlier `artifacts/final-verification` source,
`mission-live-064ef6b3f2d8a73dc4ec2b36`, remains July 19 initialized-only history.
It has not been rewritten or promoted to current data.

### Reading the indicators

Open the **Navigator Reference Tape** for a symbol-selectable detail view, or
choose **View details** on a Fleet/Admiral/recorded Watchlist row. The Tape shows
the selected captured price/MA, timing, provenance, and separate fleet snapshot
and analysis coverage. Its interval/MA choices are captured data only; **Open
full Navigator** carries the selection into the chart. A fleet row without a
chart capture can still be inspected, with missing chart values left explicit.
These local selections do not change the collapsed desk reference or mission.

Open the **Oracle book** to read **Market summary and analysis** on page 1;
recorded ModelDock commentary and its cited facts are on page 4. Long pages
scroll inside the parchment. Native Oracle prose and ModelDock explanations
are distinct sources, retain their recorded times, and are not refreshed by
opening the book. The [Oracle coverage audit](ORACLE_COVERAGE.md) explains why
seven acquired symbols are excluded from the current 14-symbol measurements
and why the missing-prior warning needs producer work, not another identical run.

- A connected reader means the local artifact-reading service responded. It is
  not a ModelDock health check and does not prove the mission producer is running.
- Last checked/verified time describes this reader interaction. Snapshot
  observation time describes when the mission evidence was recorded.
- The current UI marks mission evidence older than 15 minutes as stale. This is
  a presentation-age indicator, not an expiry rule, a market-data SLA, or a
  change to the mission's canonical outcome.
- A held, incomplete, vetoed, or failed mission is valid display content when
  its evidence validates. It does not need to become `APPROVED` before viewing.
- Chart and portfolio information appear only when recorded presentation
  supplements exist. Their original capture/latest-bar timestamps remain
  visible; missing context remains `NOT_CONFIGURED`, not a synthetic holding
  or quote. The reader does not continuously fetch market data.
- Recorded ModelDock inference provenance describes the mission-time result.
  It is not an assertion that the model is loaded or healthy now.
- On a connection or integrity failure, last verified evidence can stay visible
  with a warning. It is not new evidence; a successful poll must not make its
  underlying timestamps younger.

## 4. Develop the UI without generating missions

Use two terminals:

```bash
# Terminal 1: read-only service
make cabin-reader \
  CABIN_ARTIFACTS_ROOT=/absolute/path/to/artifacts \
  CABIN_MISSION_ID=your-existing-live-mission-id

# Terminal 2: UI development server
make cabin-dev
```

Open the URL printed by Vite, normally `http://127.0.0.1:5173/`. Vite proxies
`/live` to the reader at port 5174. Running Vite alone does not create a source
or launch the reader. `make cabin-build` builds the normal UI without any judge
or demo-preparation dependency.

## Transport and diagnostics

For optional price-driven ship movement, start canonical Navigator's read-only
Alpaca stream and pass `NAVIGATOR_LIVE_URL=http://127.0.0.1:8001` to `cabin-live`
or `cabin-reader`. See [Alpaca live market data](ALPACA_LIVE_MARKET.md) for the
credential source, IEX/SIP coverage, startup commands, and stale-feed behavior.
This is separate from mission polling and never replaces captured chart/MA
evidence. No order or execution route is enabled.

The local reader exposes only read operations:

| Resource | Meaning |
| --- | --- |
| `GET`/`HEAD /live/current.json` | `blackpod.cabin_feed.v1` source status and current verified publication reference |
| `GET`/`HEAD /live/revisions/<publication-id>/<mission-relative-path>` | immutable bytes from a retained, verified publication |
| `presentation/manifest.json` within a publication | generic integrity/provenance manifest, not the approved-only demo gate |
| `/` and built UI assets | local production Cabin, without demo directories |

Feed status is `READY`, `NOT_CONFIGURED`, or `UNAVAILABLE`. `checked_at` is the
reader's current check time; a `READY` feed also carries the original snapshot
`observed_at`, publication identity, and relative publication base URL. The
browser performs its own schema, correlation, and hash checks before replacing
the displayed evidence.

The reader retains the last three publications in memory only. Unknown or
evicted publication IDs return 404. Restarting the reader discards that cache;
it does not delete canonical artifacts. This is not a durable archival server.
There is no mutation API or arbitrary source-directory browsing endpoint.

For a read-only service check:

```bash
curl -sS http://127.0.0.1:5174/live/current.json
```

## Troubleshooting

| Symptom | Check / next step |
| --- | --- |
| Source not configured | Supply both artifact root and mission ID, then restart the reader. |
| Reader unavailable in Vite | Start `make cabin-reader`; confirm it is listening on 5174 and inspect its terminal output. |
| Port already in use | Stop the known prior Cabin process or intentionally choose another reader port; keep the development proxy configuration consistent. Do not kill unrelated services. |
| Invalid or unavailable source | Check the explicit mission path and canonical request/snapshot/artifact integrity. The reader will not fix or rewrite it. A concurrently publishing producer may need time to finish a coherent revision. |
| Old timestamps despite a connected reader | The selected source is old or unchanged. Check the independently operated producer; reconnecting the Cabin does not refresh evidence. |
| Chart or portfolio not configured | The selected mission has no verified supplement. Do not copy a demo capture into live evidence or fabricate values. |
| Old publication 404 | The in-memory publication was evicted or the reader restarted; allow the next current-feed refresh to select the current verified publication. |
| Missing production UI | Run `make cabin-build`, or use `make cabin-live` to build and serve. |

## Verification and historical replay

```bash
make test
make cabin-test
make cabin-build
make navigator-check-upstream BATTLESTAR_PATH=/path/to/read-only/battlestar
```

For explicit offline developer review only:

```bash
make cabin-dev-replay BATTLESTAR_PATH=/path/to/read-only/battlestar
# Open the Vite URL with ?mode=replay.
```

`make cabin-build-replay` is the explicit replay-included build; the old
`?mode=demo` query remains an alias. Replay assets are intentionally not served
by the live reader. See [Captain's Cabin](CAPTAINS_CABIN.md) for production
browser regression setup, and the archived [Demo Runbook](DEMO_RUNBOOK.md) for
fixture-generation history. No replay result substitutes for a fresh,
user-selected LIVE mission review.

Future add-symbol workflows and trading are tracked in the
[product roadmap](PRODUCT_SPEC.md#roadmap--not-enabled-in-this-release); neither
is available in this release.
