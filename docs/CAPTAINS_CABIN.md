# Captain's Cabin

The Captain's Cabin is the live, read-only product presentation layer. A thin
Vite, React, and TypeScript application follows one explicitly selected
canonical LIVE mission through a local read-only artifact reader and renders
it over the fixed 4:3 cabin artwork. It has no mission commands, approval
action, or execution authority. See the current
[product specification](PRODUCT_SPEC.md) and [live runbook](LIVE_PRODUCT_RUNBOOK.md).

The existing `mission_brief.html` remains the deterministic, script-free
reference renderer. The cabin is an additional view and does not replace,
rewrite, or enter the hash lineage of that brief or any canonical JSON.

## Run it

From the repository root:

```bash
make setup
npm --prefix ui ci
make cabin-live \
  CABIN_ARTIFACTS_ROOT=/absolute/path/to/artifacts \
  CABIN_MISSION_ID=your-existing-live-mission-id
```

Open `http://127.0.0.1:5174/`. The reader checks
`<artifact root>/missions/<mission ID>/`; it does not create or resume a mission.
Without source configuration, the UI explains setup rather than loading a
demo. For development, run `make cabin-reader` with those same source variables
in one terminal and `make cabin-dev` in another. Vite proxies `/live` to the
reader at port 5174. Existing mission viewing needs neither Battlestar imports
nor a running ModelDock service.

For non-interactive verification:

```bash
make cabin-test
make cabin-build
```

For browser regression checks, explicitly prepare the offline review fixture:

```bash
make cabin-prepare BATTLESTAR_PATH=/path/to/read-only/battlestar
# Once, if Playwright's Chromium is not installed:
npm --prefix ui exec -- playwright install chromium
make cabin-e2e

# Alternatively use an existing local Chrome installation:
PLAYWRIGHT_CHANNEL=chrome make cabin-e2e
```

Browser tests retain the explicit REPLAY/SHADOW fixture with its Navigator
capture and fail with setup instructions if it is absent. Fixture generation
is test/review setup only, not a live startup dependency. Tests do not produce
or replace a real LIVE mission. The suite builds a replay-included test bundle
and starts its own production preview on ports 4317 and 4318, checking root and
`/cabin/` asset loading.
Reports, screenshots, and failure traces are written beneath
`output/playwright/regressions/`.

Coverage includes the transparent ledger preview, deferred Navigator V3 load,
camera endpoints, modal keyboard/focus behavior, replay progression, explicit
Live failure, and the WebGL/SVG fallback. Camera unit tests exercise smooth
transitions and reversals separately from the reduced-motion browser smoke.

`make cabin-test`, `make cabin-build`, and `make cabin-e2e` also verify the
reviewed renderer fingerprints. Before accepting an upstream Navigator update,
run `make navigator-check-upstream BATTLESTAR_PATH=/path/to/battlestar` and
follow [Navigator source maintenance](NAVIGATOR_V3_INTEGRATION.md). The check
reads the canonical checkout without changing it.

For explicit historical UI review, not ordinary product operation:

```bash
make cabin-dev-replay BATTLESTAR_PATH=/path/to/read-only/battlestar
# Open the Vite URL with ?mode=replay.
```

`?mode=demo` is retained only as an alias. `make cabin-build-replay` is the
explicit replay-included build. Normal `make cabin-dev`, `make cabin-build`,
and `make cabin-live` do not prepare a demo or run the judge workflow; the live
reader does not serve demo directories. There is no ordinary Demo/Live switch.

The retained `make cabin-prepare` command generates the offline replay fixture
through the historical judge path, attaches a fixed-revision AAPL capture, and
materializes `ui/public/demo/approved/`. No portfolio source is bundled.
Generated data, `ui/node_modules/`, coverage, and `ui/dist/` remain ignored by
Git. Old live-demo packagers remain historical utilities; they are not the
current live feed or required to display held/failed missions. Their commands
are documented, with authority warnings, in the archived
[LIVE Demo Runbook](LIVE_DEMO_RUNBOOK.md).

The captured AAPL tape is a supplemental Navigator reference and is labeled as
such in the cabin. It is not attributed to Oracle: the mission symbol is
correlation metadata while the current Oracle interface analyzes its supported
fixed fleet.

## Authority and data flow

```text
canonical snapshot chain and immutable stage artifacts
                         |
                         v
          live reader: coherent verified publication
          /live/current.json -> /live/revisions/<id>/
                         |
                         v
       blackpod.mission_summary.v2
       blackpod.captains_log.v1
       generic publication manifest (transport only)
       blackpod.mission_snapshot.v1
                         |
             validated presentation models
                    /                  \
        Python contract model      TypeScript view model
                 |                         |
                 v                         v
       mission_brief.html          React cabin scene
                                   live read-only view
```

The principal browser inputs are:

- `presentation/mission_summary.json` for ordered stage display state, mission
  outcome, warnings, and the Governor/operator/Navigator boundary;
- `presentation/captains_log.json` for the eight canonical timeline entries and
  their evidence references;
- `presentation/captains_log.md` only when the JSON log is unavailable;
- `presentation/manifest.json` for the live publication's revisions, ModelDock
  mode and identity, hashes, and SHADOW declaration (historical replay uses
  `presentation/demo_manifest.json`); and
- `mission_snapshot.json` when correlation or evidence metadata is needed.

When explicitly captured by a separately operated producer, a separate
`blackpod.cabin_context.v1` presentation supplement references the exact
read-only Navigator market response and optional portfolio snapshot by hash.
These files provide company/timeframe/latest-bar/chart and portfolio display
context only. They do not enter the mission snapshot, change an outcome, or
become trading inputs. If absent, the cabin reports `NOT_CONFIGURED` rather
than inventing values.

The browser validates schema versions, required shapes, canonical stage order,
mission correlation, and mission-relative paths before constructing a display
view model. It validates the live publication and referenced bytes before
replacing the previous verified view. JSON remains authoritative. Formatting,
book pagination, selection, and explicit replay visibility are presentation
state only.

LIVE accepts all valid canonical outcomes, not only approved terminal missions.
Polling follows the selected mission every five seconds. Reader connectivity,
last successful check, and recorded evidence age remain distinct. Invalid or
unavailable updates never fall back to replay; retained last-verified evidence
is explicitly labeled degraded/offline and keeps its original timestamps.
ModelDock provenance is mission-time evidence, not a current health probe.

## Scene and interaction

The 1448 by 1086 template is displayed inside one responsive `aspect-ratio:
4 / 3` scene. All overlay bounds come from a typed percentage-based scene
layout rather than component-local pixel coordinates. This keeps the books,
status panel, log, loose papers, chart, systems panel, and illustrated bottom
navigation aligned as the scene scales.

At desk level, each of the five stage books shows a concise recorded summary.
Selecting a book opens one focused reading surface; only that book's detailed
pages render. Previous/next controls, page position, keyboard activation, and
Escape return are local UI behavior and cannot alter the mission.

The Captain's Log uses the canonical order:

1. Harbormaster
2. Oracle
3. ModelDock
4. Council
5. Governor
6. Operator
7. Navigator
8. Mission

In explicit replay review only, Replay Theater walks through those same entries.
Play, pause, restart, step, and speed affect only which already-recorded entry
is visible. Canonical timestamps and final values are never regenerated or
rewritten. Normal LIVE operation shows the current verified revision without
replay controls.

Bottom navigation is presentation navigation. Bridge restores the full scene;
Oracle, Council, and Navigator select their books; Logbook and Sentry focus
their display regions. Admiral and Config contain no hidden settings or
execution controls.

## Accessibility

- Interactive regions use semantic buttons and descriptive accessible names.
- Book selection and page controls are keyboard operable.
- Keyboard focus remains visibly distinguishable from stage color.
- Escape closes a focused book.
- Opening a book, notice, or expanded Navigator makes the background scene,
  live status or explicit replay controls inert and hidden from assistive
  technology. Focus stays in the dialog and returns to its opening control
  after dismissal, including pointer activation that did not focus that control.
- Replay announcements use an `aria-live` region without rewriting timestamps.
- Status text accompanies every color cue.
- Reduced-motion preferences suppress nonessential transitions.
- Internal parchment scrolling does not prevent keyboard access to content.

## Safety boundary

The cabin must always preserve the distinction among:

```text
Governor PROCEED
    -> explicit operator APPROVED_FOR_HANDOFF
    -> Navigator SHADOW PLAN CREATED
    -> mission APPROVED within NAVIGATOR_SHADOW_HANDOFF scope
```

Governor `PROCEED` is never labeled mission approval. ModelDock is labeled as a
narrative-only appliance; Oracle remains authoritative for facts,
measurements, diagnostics, and readiness.

Allowed operations are exactly:

- `VALIDATE`
- `PLAN_ONLY`

Prohibited operations include:

- `SUBMIT_ORDER`
- `CANCEL_ORDER`
- `MODIFY_PORTFOLIO`
- `BROKER_CALL`

There are no broker, trade, operator-approval, mission-resume, or mutation
controls in the cabin.

## Honest data gaps

The current presentation contracts provide complete mission progression,
outcome, provenance, warnings, and safety state, but they intentionally do not
flatten every native stage artifact. Depending on the selected mission, they
may not expose detailed Oracle measurements, Council dissent or confidence,
Governor rationale and decision identifiers, operator identity and action
timestamps, or Navigator expiry and idempotency fields.

The cabin displays `Not present in this mission artifact` when an expected
presentation field is absent. It does not infer a value from prose, calculate a
replacement score, search for an arbitrary latest sibling artifact, or turn a
missing optional field into a new business rule.

## Visual calibration

The current calibration targets the supplied 1448 by 1086 image and uses
percentage positioning, modest rotation, and parchment-compatible typography.
The artwork already supplies perspective, texture, lighting, borders, and most
visual hierarchy; overlays should remain restrained.

Likely browser-to-browser adjustments are limited to line wrapping, internal
book scroll height, focus outlines, and small percentage offsets around the
narrow Governor and Navigator books. Perfect perspective warping, animated
page turns, new foreground masks, and a generalized dashboard layout are not
part of the current product increment. Calibration changes belong in the
central scene layout and styles, never in canonical contracts or mission logic.
