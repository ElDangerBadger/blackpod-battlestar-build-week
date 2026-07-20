# Captain's Cabin

The Captain's Cabin is the first interactive Build Week presentation layer. It
is deliberately thin: a Vite, React, and TypeScript application reads one
completed mission and renders it over the fixed 4:3 cabin artwork. It has no
mission commands, persistence, service process, approval action, or execution
authority.

The existing `mission_brief.html` remains the deterministic, script-free
reference renderer. The cabin is an additional view and does not replace,
rewrite, or enter the hash lineage of that brief or any canonical JSON.

## Run it

From the repository root:

```bash
export BATTLESTAR_PATH=/absolute/path/to/blackpod_battlestar
make setup
npm --prefix ui install
make cabin-prepare
make cabin-dev
```

For non-interactive verification:

```bash
make cabin-test
make cabin-build
```

Stage 4 also supports two explicit prepared data slots. Demo remains the
default; Live must be selected and never falls back:

```bash
make cabin-prepare-demo
make cabin-prepare-live LIVE_MISSION_ID=<verified-live-mission-id>
make cabin-dev-live LIVE_MISSION_ID=<verified-live-mission-id>
```

Use `make cabin-freeze-live-demo LIVE_MISSION_ID=<id>` only after the strict
LIVE packager accepts that mission. Full execution, context-capture, and
packaging instructions are in the [Stage 4 LIVE Demo
Runbook](LIVE_DEMO_RUNBOOK.md).

`make cabin-prepare` depends on the existing `make judge` target. Without
changing `make judge`, it then captures the committed AAPL Navigator market
response with its fixed source revision and timestamp, validates the completed
approved mission, and copies its mission-relative tree into
`ui/public/demo/approved/`. This step is deterministic and offline. No
portfolio source is bundled, so the presentation honestly records and displays
portfolio status `NOT_CONFIGURED`. That directory, `ui/node_modules/`,
frontend test coverage, and `ui/dist/` are generated locally and ignored by
Git.

The captured AAPL tape is a supplemental Navigator reference and is labeled as
such in the cabin. It is not attributed to Oracle: the mission symbol is
correlation metadata while the current Oracle interface analyzes its supported
fixed fleet.

## Authority and data flow

```text
canonical snapshot chain and immutable stage artifacts
                         |
                         v
       blackpod.mission_summary.v2
       blackpod.captains_log.v1
       blackpod.demo_manifest.v1
       blackpod.mission_snapshot.v1
                         |
             validated presentation models
                    /                  \
        Python contract model      TypeScript view model
                 |                         |
                 v                         v
       mission_brief.html          React cabin scene
                                   read-only playback
```

The principal browser inputs are:

- `presentation/mission_summary.json` for ordered stage display state, mission
  outcome, warnings, and the Governor/operator/Navigator boundary;
- `presentation/captains_log.json` for the eight canonical timeline entries and
  their evidence references;
- `presentation/captains_log.md` only when the JSON log is unavailable;
- `presentation/demo_manifest.json` for revisions, ModelDock mode and identity,
  hashes, and the exact SHADOW safety declaration; and
- `mission_snapshot.json` when correlation or evidence metadata is needed.

When explicitly captured, Stage 4 adds a separate
`blackpod.cabin_context.v1` presentation supplement that references the exact
read-only Navigator market response and optional portfolio snapshot by hash.
These files provide company/timeframe/latest-bar/chart and portfolio display
context only. They do not enter the mission snapshot, change an outcome, or
become trading inputs. If absent, the cabin reports `NOT_CONFIGURED` rather
than inventing values.

The browser validates schema versions, required shapes, canonical stage order,
mission correlation, and mission-relative paths before constructing a display
view model. JSON remains authoritative. Formatting, book pagination, selection,
and replay visibility are presentation state only.

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

Replay Theater walks through those same entries. Play, pause, restart, step,
and speed affect only which already-recorded entry is visible. Canonical
timestamps and final values are never regenerated or rewritten.

Bottom navigation is presentation navigation. Bridge restores the full scene;
Oracle, Council, and Navigator select their books; Logbook and Sentry focus
their display regions. Admiral and Config contain no hidden settings or
execution controls.

## Accessibility

- Interactive regions use semantic buttons and descriptive accessible names.
- Book selection and page controls are keyboard operable.
- Keyboard focus remains visibly distinguishable from stage color.
- Escape closes a focused book.
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

The first calibration targets the supplied 1448 by 1086 image and uses only
percentage positioning, modest rotation, and parchment-compatible typography.
The artwork already supplies perspective, texture, lighting, borders, and most
visual hierarchy; overlays should remain restrained.

Likely browser-to-browser adjustments are limited to line wrapping, internal
book scroll height, focus outlines, and small percentage offsets around the
narrow Governor and Navigator books. Perfect perspective warping, animated
page turns, new foreground masks, and a generalized dashboard layout are not
part of this phase. Calibration changes belong in the central scene layout and
styles, never in canonical contracts or mission logic.
