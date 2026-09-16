# Build Week Changelog

This document retains Build Week history and records subsequent Cabin product
changes. It is not the upstream Battlestar or ModelDock changelog; both sibling
repositories remain read-only. The [product specification](PRODUCT_SPEC.md)
now governs scope.

## 2026-09-15 — Readable ledgers and expandable Navigator Reference Tape

- Linked the Reference Tape to a read-only parchment module with captured
  prices, supplied MA context, interval, timestamps, source details, and an
  immediately visible full-Navigator button. Missing captures remain explicit.
- Added deterministic plain-language readings across all 24 pages of the five
  ledgers. Process completion, native results, permission, missing inputs, and
  operational SHADOW planning retain distinct meanings. Exact recorded values
  are expandable, and original evidence links remain available.
- Explained known mission warnings in terms of coverage and permission limits,
  preserving their exact wording and leaving unknown warnings uninterpreted.
  Larger type, wrapped text, scrollable content, disclosure keyboard access,
  and inactive-page focus isolation improve readability without changing the
  Cabin artwork or mission contracts.
- No provider/model calls, mission runs, artifact mutations, upstream edits,
  commits, or GitHub pushes were performed for this presentation update.

Acceptance: 281 UI tests and 13 browser regressions passed. The normal production
build was restored afterward and excludes demo assets. Actual LIVE checks covered all 24
ledger pages and their exact-value disclosures, Reference Tape/full-Navigator
navigation and focus return, and warning wrapping/keyboard access at 1440×1080
and 1280×960. Original market/context/snapshot hashes remain unchanged;
canonical source checks passed and both protected sibling worktrees are clean.

## 2026-09-15 — Transparent bottom-left ship-price readout

- Moved the price readout outside Canvas into a fixed bottom-left overlay,
  keeping its 32px price, supplied values, pointer-pass-through behavior, and
  chart-transition fade. Camera movement no longer positions it over the ship.
- Removed the panel background, border, and shadow; text shadow provides contrast.
  Kept a 64px bottom clearance for camera controls. Only reviewed consumer
  destination hashes changed; canonical Battlestar and ModelDock are unchanged.
- Audited finer intervals: canonical Navigator still exposes only hourly,
  daily, and weekly captures. 1m/5m and ongoing refresh need separately
  authorized upstream work; no one-second bars or live prices were fabricated.

Acceptance: 251 UI tests, 13 browser regressions, production build, and canonical
source guard passed.
Actual LIVE checks at 1440×1080 and 1280×960 confirmed a transparent background,
unchanged 32px price, fixed position during camera pan, hourly MA selection, and
chart-view fade. No market acquisition, mission workflow, or GitHub push ran.

## 2026-09-15 — Captured Navigator interval and MA selection

- Enabled hourly/daily/weekly bars and MA20/50/100/200/250 from captured
  Battlestar responses, following the user's explicit additive-catalog approval.
  No browser indicator calculation, provider API, or standalone store was added.
- Added a hash-bound optional capture catalog to LIVE publications, exact-byte
  variant validation, bounded reads, and an explicit capture CLI with staged,
  no-overwrite publication and rollback. Legacy replay and existing market,
  Cabin-context, and mission contracts remain unchanged.
- Captured 14 supplemental AAPL pairs from canonical V3/yfinance at 18:14 PDT.
  Preserved the original daily/MA250 bytes and overview. New daily captures end
  September 14; the original ends September 15. Per-selection capture/latest-bar
  timestamps and inspectable provenance keep this difference explicit.
- Both WebGL and SVG fallback follow the chosen capture. MA labels use bars;
  hourly timeline controls show UTC time. Preserved history presets/start slider
  and visual exaggeration; constrained the legible price card above the camera
  strip when the new controls shorten the canvas.
- Only Build Week changed. Battlestar and ModelDock are clean; the temporary
  capture service was stopped. No mission, model, approval, or trading workflow
  ran, and nothing was committed or pushed by this update.

Acceptance: 538 backend tests (including 24 new catalog checks), 255 UI tests,
13 browser regressions, normal production build, and canonical source guard
passed. Actual LIVE browser checks covered all 15 pairs with matching captured
values/timestamps and no provider requests, original reset, hourly keyboard
stepping, history/scale controls, chart hover, and desktop/smaller-window layout.
Original market/context/snapshot hashes remain unchanged. Production output
excludes demo assets. See [capture operations](NAVIGATOR_CAPTURE_CATALOG.md).

## 2026-09-15 — Navigator history and visual scale controls

- Added 1M/3M/6M/1Y/All visible-history presets and a history-start slider in
  expanded ship/chart views. UTC windows are anchored to the last captured bar,
  not today's clock; the latest close and supplied MA values remain unchanged.
- Restored canonical V3's 0.2×–2.5× visual exaggeration range as local Cabin
  state. It changes ship-view wake/MA separation, easing back to normal scale
  in the full chart. No standalone store, API, or source acquisition is added.
- Kept source/visible history and observation counts distinct. Bounded sparse
  time ticks and plot padding so even a two-bar window remains legible.
- Hourly/daily/weekly and alternate MA selectors are **not enabled**: the current
  single-artifact contract supplies only one captured pair. A capture catalog
  needs an explicit additive-contract decision; no alternate values were
  synthesized and no existing market artifact was overwritten.

Acceptance: 198 UI tests, 13 browser regressions, production build, and pinned/
current upstream checks passed. Local browser checks at 1640×1234 and 1280×960
covered presets, the two-bar limit, unchanged captured facts, and normal chart
framing with maximum ship exaggeration. Production output excludes demo assets.

## 2026-09-15 — Chart gutters and readable hover

- Moved full-chart price/date ticks 10 CSS pixels outside the grid; increased
  their type size and contrast. Kept the latest-close badge inside the plot
  so it does not collide with the price-axis labels.
- Enhanced the existing hover plane with price/MA selection, a readable
  canvas-bounded tooltip, two-decimal values, UTC dates, and visible crosshair
  markers. Dragging and pointer exit clear the readout. Supplied MA gaps remain
  unavailable; hover selects rendered observations without interpolating facts.
- Preserved camera controls, market artifacts, SVG overview, and read-only
  mission safety. Added chart annotations to the future product roadmap only.
  Updated only reviewed consumer renderer hashes; upstream is unchanged.

Acceptance: 164 UI tests and 13 browser regressions passed. Production build
and the pinned/current upstream renderer check passed. Local LIVE browser checks
at 1640×1234 and 1280×960 confirmed 10-pixel gutters, unclipped hover readouts,
price/MA switching, unavailable MA, drag/exit clearing, and values matching the
captured artifact. Normal production assets exclude demo data.

## 2026-09-15 — Legible in-scene ship price

- Enlarged the floating ship-price card to 224 CSS pixels, with a 32-pixel
  price and larger percentage/MA-position text. Removed distance-based HTML
  scaling so the price does not shrink to a few pixels as the camera moves.
- Preserved the original scene anchor, camera behavior, chart-transition fade,
  supplied values/formatting, and pointer-transparent interaction. The SVG
  overview and canonical market artifacts are unchanged.
- Recorded this user-requested Cabin typography adaptation in the renderer
  mapping, updating only the reviewed destination hashes. Battlestar and
  ModelDock remain unchanged.

Acceptance: 156 UI tests, 13 production browser regressions, the production
build, and canonical renderer checks passed. Actual LIVE ship-view checks at
1640×1234 and 1280×960 verified scale 1, a 32-pixel price, and no clipping or
camera-control overlap. Normal production assets exclude demo data.

## 2026-09-15 — Verified LIVE pipeline through Governor, no trading

- Replaced the invalid LIVE prompt placeholder with a worked example using
  actual catalog IDs. The example must pass the existing strict narrative
  validator before transport; it is never a fallback response. Historical
  REPLAY prompt bytes and recorded fixtures remain unchanged.
- Added allowlisted validation rule/field diagnostics to sanitized failures.
  Rejected generated content, untrusted field names, secrets, and local paths
  remain redacted; error codes, schemas, and fail-closed behavior are preserved.
- Ran a new real mission `mission-live-aapl-20260915-002` under
  `artifacts/no-trade-live-20260915`. Oracle, pinned local Gemma commentary,
  Council, and Governor all succeeded technically. The recorded narrative
  contains five source-linked facts and non-mocked inference provenance.
- Confirmed the explicit no-trade mandate produces Council/Governor `BLOCKED`,
  a terminal `HELD` mission at revision 9, and Governor next step `NONE`.
  Operator route is `CLOSED_BLOCKED`, action `NOT_STARTED`; no approval,
  operational Navigator handoff, order, broker call, or portfolio mutation ran.
- Pointed the read-only Cabin at this new source. The earlier failed mission
  remains preserved for diagnosis rather than being rewritten or relabeled.
- Reattached the verified earlier AAPL chart bytes with their original
  22:36:41 UTC capture timestamp and explicit local-source identity after the
  fresh supplemental fetch was canceled at approval. No fresh chart fetch is
  claimed; the new Oracle acquisition and model inference are independent.

Acceptance: all 513 backend tests and 144 UI tests passed, including deterministic replay,
strict source linkage, sanitized failure provenance, and loopback reader
checks. Battlestar and ModelDock were not modified. This is a real captured
pipeline run, not a continuous producer or streaming quote service.

## 2026-09-15 — Initial LIVE data capture and compatibility

- Acquired a real canonical Oracle market snapshot and 751 AAPL daily bars
  using Battlestar's Navigator provider. Created a new local LIVE mission;
  preserved the prior July evidence unchanged. The read-only Cabin now follows
  `mission-live-aapl-20260915-001` under `artifacts/initial-live-20260915`.
- Accepted current Navigator V3 provider/cache metadata and disclaimer without
  rewriting captured bytes, prices, or presentation contracts. Explicit
  synthetic data is rejected in LIVE capture, reader, and browser validation.
  Expanded V3 and SVG fallback expose supplied provenance; provider cache age
  is not presented as streaming quote freshness.
- Contained Oracle's real yfinance runtime caches within the Build Week mission
  directory. Canonical Battlestar and ModelDock remain unmodified.
- Updated the ModelDock preflight consumer for the documented readiness fields,
  retaining the strict pinned, local, non-mocked deep-inference check.
- Real Gemma inference passed preflight but failed the subsequent narrative
  contract. The mission correctly stopped at Oracle enrichment, revision 5,
  `FAILED`; Council and Governor did not run. Their explicit no-trade inputs
  remain staged. No operator approval, orders, broker calls, or portfolio
  changes were made. The independently captured Navigator chart remains usable.
- Preserved failed evidence and documented the remaining narrative prompt/
  diagnostics work in the live runbook. No synthetic commentary or approved
  demo replaced the failed result. Portfolio context remains unconfigured.

Acceptance: 506 backend tests, 144 UI tests, and 13 browser checks passed.
Normal production build excludes demo assets; the 19-file canonical renderer
drift check passes. The actual local reader verifies the new LIVE evidence.
These are captured observations, not a continuous producer or streaming feed.

## 2026-09-15 — Live read-only product transition

- Retired the demo specification as governing product scope. Preserved the old
  README as [Build Week history](BUILD_WEEK_HISTORY.md) and marked both demo
  runbooks historical; added a current product specification and live runbook.
- Made LIVE the ordinary presentation path, with no normal Demo/Live selector.
  Kept explicit deterministic replay review and legacy query compatibility.
- Separated normal build/startup from judge and approved-demo preparation.
  Retained legacy packaging for historical/replay workflows only.
- Added a loopback read-only reader for one explicitly configured canonical
  LIVE mission, publishing verified revision bytes in memory without source
  writes, mission execution, automatic source discovery, or provider calls.
- Removed approved-demo gating from live presentation. Valid incomplete,
  running, held, vetoed, failed, and approved evidence belongs in the product.
- Added periodic source refresh and honest distinction between reader
  availability, last check, and original evidence time, with no replay fallback.
- Preserved calibrated Cabin presentation, SVG overview, Navigator V3, existing
  mission contracts, and the SHADOW-only boundary.
- Recorded add-symbol workflows and eventual trading as roadmap work, not
  implemented authority. A fresh real mission producer, live market acquisition,
  and present ModelDock readiness are not implied by the reader or fixture tests.

Acceptance: 497 backend tests, 133 UI tests, and 13 browser checks passed;
normal production build excludes demo data and the 19-file upstream renderer
check passes. Historical AAPL evidence from `artifacts/final-verification`,
mission `mission-live-064ef6b3f2d8a73dc4ec2b36`, was verified through the actual
reader/browser without source changes. It remains dated 2026-07-19,
initialized-only/INCOMPLETE, with no captured chart or inference—not a fresh
mission run. Backward-compatible v1 records retain original bytes and hashes.
Removed the decorative no-data chart line and covered the artwork's printed
Governor “All Clear” placeholder with the actual recorded disposition.

## 2026-09-15 — Cabin regression coverage and renderer maintenance

- Merged the Navigator V3 integration and the ledger-preview/background fixes
  into local `main`; started `update/2026-09-15-cabin-hardening` from that baseline.
- Removed Finder metadata from version control and ignored `.DS_Store` files.
- Isolated the scene and replay/mode controls while dialogs are open, with
  keyboard containment and reliable focus restoration for Navigator, books,
  and notices.
- Added production browser checks for root and nested asset loading, the SVG
  overview, lazy V3 expansion, camera endpoints, replay, Live failures, and
  WebGL fallback.
- Added deterministic camera transition tests without altering the canonical
  renderer's camera behavior.
- Recorded source and destination fingerprints for the 19 imported renderer
  files and added local/upstream drift checks plus a reviewed update workflow.
  A shared renderer package remains future Battlestar work; Build Week still
  carries the documented snapshot.

Acceptance: 471 backend tests, 71 UI unit tests, and 10 production browser
checks passed. The production build and the 19-file upstream renderer check
also passed. Browser coverage used local Chrome with software WebGL and
reduced motion; smooth camera transitions are covered by deterministic unit
tests. No fresh LIVE mission was run, and nothing was pushed to GitHub. The
existing large lazy-renderer bundle warning remains non-blocking.

### Ledger alignment follow-up

- Recalibrated book and loose-paper ink areas against the artwork, including
  page angles, the Captain's Log gutter, and SHADOW rope/seal clearance.
- Fit the transparent Navigator overview to the portrait ledger area, inset
  its summary from the binding, and kept the expanded renderer and supplied
  observations unchanged.
- Aligned right-hand provenance panels with their illustrated frames and
  covered conflicting printed placeholders beneath the live text.
- Verified the layout at 1280×960, 1448×1086, and 1846×1311. All 75 UI unit
  tests, 10 production browser checks, and the production build passed.

## Stage 6 — Navigator V3 and ledger preview

- Ported the renderer from Battlestar revision `7807798` behind the existing
  mission-artifact adapter; preserved lazy expansion, the SVG overview/fallback,
  Demo/Live selection, deterministic replay, and the SHADOW boundary.
- Made the desk-level chart transparent with colors readable over the ledger.
- Fixed production cabin artwork resolution by letting Vite process its CSS URL.

## Stage 2, Phase 3 — Demo readiness

- Added one replay/live preflight surface for environment and dependency
  readiness reporting.
- Added committed scenario-pack validation before mission execution.
- Added canonical demo scenarios for `APPROVED`, `HELD`, `VETOED`, `FAILED`,
  and `INCOMPLETE` outcomes.
- Added an approved rehearsal mode that validates the resulting snapshot chain,
  artifact hashes, Captain's Log, and mission summary.
- Added a hashed `blackpod.demo_manifest.v1` and the additive UI-facing
  `blackpod.mission_summary.v2` presentation fields.
- Added thin Make targets and an operator runbook; they delegate to the existing
  Harbormaster CLI and do not introduce a second orchestration path.
- Documented architecture, safety boundaries, expected evidence, and
  troubleshooting guidance.
- Removed stale generated Phase 1 mission output that had been tracked outside
  the canonical `artifacts/missions/` root.

## Stage 2, Phase 2 — Unified mission

- Added `mission-run` and `mission-resume` over the existing stage workflows.
- Preserved explicit ModelDock enable/disable selection and the operator gate.
- Added inclusive stop targets and state-driven resume with full integrity
  validation.
- Added deterministic Captain's Log and mission-summary projections.
- Demonstrated all five canonical outcomes without network or broker access.

## Stage 2, Phase 1 — ModelDock narrative enrichment

- Added strict loopback-only ModelDock configuration and `/text/generate`
  client validation.
- Added a versioned Oracle narrative request and response contract.
- Tightened the model boundary to a deterministic, source-linked fact catalog:
  ModelDock selects stable fact IDs and writes prose, while Build Week expands
  exact observed facts and Oracle warnings into the unchanged canonical
  narrative contract.
- Attached validated narrative output to Oracle provenance without changing
  Oracle facts or native readiness.
- Added deterministic REPLAY and explicit, non-mocked LIVE behavior.

## Stage 1, Phase 5 — Operator and Navigator

- Added the explicit operator approval/rejection gate.
- Added Governor-to-Navigator handoff staging, intake validation, receipts,
  lineage, and SHADOW-only planning.
- Defined `APPROVED` as explicit handoff approval followed by a created SHADOW
  plan; Governor `PROCEED` alone remains `HELD`.

## Stage 1, Phase 4 — Governor

- Integrated current Governor preparation, deliberation, readiness, and
  rendered-decision interfaces.
- Preserved canonical dispositions: `PROCEED`, `HOLD`, `STAND_DOWN`, `BLOCKED`,
  and `REVIEW_REQUIRED`.
- Added the non-executing `PENDING_APPROVAL` operator placeholder.

## Stage 1, Phase 3 — Council

- Integrated candidate evidence, Senate deliberation, Mandate context,
  Council synthesis, and executive-summary interfaces.
- Preserved native caution, division, dissent, and insufficient-evidence states
  separately from technical success.

## Stage 1, Phase 2 — Oracle

- Integrated Battlestar's existing Oracle pipeline through a narrow adapter.
- Added explicit LIVE and deterministic REPLAY transports, immutable captured
  artifacts, provenance, deadlines, and restart behavior.

## Stage 1, Phase 1 — Harbormaster spine

- Added the installable Python package, strict mission request contract, and
  canonical mission snapshot.
- Added stable identifiers, a contained mission directory, immutable revisions,
  atomic current-snapshot publication, and SHA-256 chaining.
- Added the original Harbormaster initialization command and focused tests.

## Historical submission feature-freeze statement

This statement describes the original submission, not the live-product
specification. Demo readiness changes package and explain existing
capabilities. They do not add analytical rules, Council policy, Governor policy, operator authority,
Navigator execution policy, ModelDock authority, broker integration, or a new
service subsystem.
