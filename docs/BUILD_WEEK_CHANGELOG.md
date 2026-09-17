# Build Week Changelog

This document retains Build Week history and records subsequent Cabin product
changes. It is not the upstream Battlestar or ModelDock changelog. ModelDock
remains unchanged; the September 16 Navigator registry and market-data exceptions are recorded
below, along with the narrowly authorized Sentry classifier correction.
The [product specification](PRODUCT_SPEC.md) now governs scope.

## 2026-09-17 — Sentry history recovery and universe publication completed

- Finished the saved September 16 request at the existing two-second pace:
  5,136 usable histories, 23 explicit provider-unavailable results, zero pending.
  All 5,159 cache/final series and 4,066 preserved originals were independently
  verified. Canonical H25 assembled from cache only and passed its handoff checks.
- Canonical selection published exactly 100 unique symbols from 3,401 eligible
  records; dated package and current export are local Build Week artifacts.
  All 27 package/export checks and the separate canonical summary passed.
- No policy/source-date change, manual selection, new canonical code change,
  live producer, long-history backfill, Cabin source switch, or trading action.
  Missing cap/float, fund/trust common-share scope, and 23 provider gaps remain
  explicit limitations; this is not a verified-microcap or live-detection claim.
- Documented reproducible canonical finalization commands and publication IDs in
  [the recovery guide](SENTRY_HISTORY_RECOVERY.md) and
  [run evidence](SENTRY_UNIVERSE_RUN_20260916.md).

## 2026-09-17 — Verified baseline published to main

- Build Week `6685a88` commits the read-only Sentry ledger and checkpointed
  history recovery. Battlestar `04d8509` commits the separately authorized
  classifier correction and its regression tests.
- Both feature branches were pushed, fast-forwarded into their existing `main`,
  and pushed to GitHub. Remote main hashes were verified; neither repository
  has a parallel main. Both then opened and pushed
  `update/2026-09-17-sentry-universe` for the remaining recovery/publication work.
- Pre-merge verification passed: 659 Build Week backend tests, 828 UI tests,
  246 canonical Sentry tests, the production build, and pinned/current-upstream
  renderer checks. ModelDock was not modified.

This Git publication is not a completed market-data or final-universe publication.
The recovery status and evidence remain in
[the population record](SENTRY_UNIVERSE_RUN_20260916.md).

## 2026-09-17 — Throttled, checkpointed Sentry history recovery

- Added a Build Week CLI around canonical public H25 APIs, with isolated staging,
  serial pacing, bounded retry/request budgets, persisted cooldowns, and an outage
  guard that survives process restarts. No new canonical or ModelDock changes.
- Per-symbol atomic commit markers pin source/request identity, original bytes,
  hashes and timestamps. Offline adoption does not invent retrieval times or
  mark empty/incomplete legacy files complete. Unsafe paths and tampering fail
  closed. Final canonical history assembly requires full verified coverage and
  backs up original partial files; it neither selects a universe nor changes UI.
- The offline audit safely reused 1,296 histories; 1,276 other nonempty files have
  a blank latest close and need refetch. A three-request live smoke test succeeded
  and stopped at its budget: 1,299 ready and 3,860 pending. No final publication.

Acceptance: 64 recovery tests, including an offline real-canonical integration,
and all 659 backend tests pass. Existing source/mission hashes are unchanged;
the labeled research ledger remains configured. These changes were subsequently
committed and merged in `6685a88`, as recorded above.
See [recovery operation and boundaries](SENTRY_HISTORY_RECOVERY.md).

## 2026-09-16 — Sentry classifier correction and real-universe rerun

With explicit authorization, canonical Battlestar's security-name classifier and
its regression tests were updated for enclosing derivatives/units, contextual
ADR/ADS descriptions, and existing SPAC refinement of ordinary shares. Provider
authority, the SPAC heuristic, eligibility policy, and data contracts are unchanged.
The 246-test canonical Sentry suite and all 21 Cabin Sentry-reader tests pass.

A fresh official Nasdaq bootstrap passed all 14 canonical validation checks and
eight manifest hash checks, yielding 5,159 provisional symbols. Canonical H25
population then hit confirmed Yahoo `YFRateLimitError`, persisting through a
bounded cooldown retry. The downloader was stopped; 2,572 nonempty price files
are retained, but no completed history manifest or final universe is published.
The partial download is not represented as complete population or live alerts.

All new artifacts/caches remain in Build Week. ModelDock, mission evidence, and
the Cabin's labeled research archive are untouched. No trade path, observation
producer, Git commit, merge, or push was introduced. See
[run evidence and recovery boundary](SENTRY_UNIVERSE_RUN_20260916.md).

## 2026-09-16 — Independent Microcap Sentry observation ledger

- The Cabin's Sentry navigation opens a read-only canonical observation ledger;
  the mission-warnings paper remains separate. No scan, producer, model call,
  mission change, or trading control is introduced.
- An optional bounded local-reader endpoint validates an explicitly configured
  archive with Battlestar's pure snapshot contract, collapses exact duplicates,
  rejects conflicting identities, and preserves raw observations and dates.
  It does not import the Sentry engine or write into the canonical checkout.
- The parchment ledger provides symbol/classification filters, complete
  observation history, readable recorded-state explanations, rule-based scores,
  factors, risks, missing inputs, and exact-record/source-integrity disclosures.
- The first local visual review uses the existing July 15 synthetic research
  archive: seven symbols, 22 distinct observations from 36 rows. It is prominently
  marked **not live detections**. Synthetic watchlist/Navigator actions are
  disabled; genuine recorded-source handoffs require explicit user action and
  an existing Navigator capture. See [Sentry configuration](SENTRY_LEDGER.md).
- Source checks run only while the Live ledger is open and visible. Missing,
  empty, malformed, and unavailable archives never become an “all clear” or a
  substitute mission result. Last-verified data remains explicitly labeled
  after failed refresh.

Acceptance: 828 UI tests pass. The 595-test backend suite passed with its optional
canonical-source test skipped; all 21 Sentry tests subsequently passed with the
canonical checkout explicitly configured. Production build, pinned/upstream
renderer checks, and diff checks pass; no demo assets are published. Playwright
visual QA checked research provenance, filters, history, exact JSON, disabled
synthetic actions, and layout overflow. Source archive, mission snapshot, Cabin
context, and original Navigator capture hashes are unchanged. Battlestar and
ModelDock remain clean and untouched. Changes are left uncommitted for review.

## 2026-09-16 — Read-only Alpaca prices in expanded Navigator

- With explicit authorization, canonical Navigator loads the existing server-side
  `buried_treasure` Alpaca credentials and multiplexes a market-data-only stream.
  Build Week relays validated prices for verified publication symbols; no
  credentials reach the browser and no account/order endpoints are used.
- Expanded Navigator shows a separate last-trade overlay, source/feed/time,
  stale/disconnected states, and pause/captured-reference controls. Its ship and
  chart marker move on the renderer's price axis without rewriting saved bars,
  moving averages, mission outcomes, or Oracle/Council/Governor evidence.
- Closing, hiding, pausing, or changing the selected symbol releases that
  viewer's subscription. Replay and the SVG evidence overview remain captured.
  Large price displacement is visually bounded with explicit clipping text;
  the exact numeric price is never clipped.
- Actual credential checks accepted IEX data and denied SIP access. IEX is
  explicitly limited-exchange coverage, not consolidated market pricing. An
  old trade remains STALE even with a healthy connection; there are no simulated
  ticks. See [startup and data boundaries](ALPACA_LIVE_MARKET.md).
- Browser acceptance exposed the large fleet's existing startup deadline and
  reader-lock contention. Loading now has bounded separate feed/bundle deadlines,
  bounded capture concurrency, and short publication-cache locking, preserving
  all hash checks and atomic acceptance.

Acceptance: 754 UI tests, 574 Build Week backend tests, and 138 canonical
Navigator backend tests pass. Production build, pinned/upstream renderer
checks, and diff checks pass; no demo assets are published. Real IEX handshake
and latest-trade reads were verified for AAPL, SPY, and VXZ. Playwright skill
checks verified pause/resume, captured-only price restoration, same-symbol
interval/MA changes, cross-symbol isolation, chart view, Escape/focus return,
and 1440×1080 / 1280×960 layouts. Visual QA moved an overlapping authority
note into the scrollable legend. Closed viewers release the upstream socket;
a middleware disconnect leak was reproduced and fixed with an ASGI regression.
No fresh price sequence arrived during after-hours acceptance: directional
movement is covered by deterministic tests, not claimed as observed live ticks.
Mission snapshot, Cabin context, and original market hashes remain unchanged.
ModelDock was untouched. No commit, merge, or push was performed.

## 2026-09-16 — Multi-symbol Navigator Reference Tape

- The expanded Tape is now a detail view for any recorded fleet item. Its
  symbol, captured interval, and moving-average selectors use the existing
  verified catalogs; they do not fetch or calculate replacement market data.
- Fleet Status, Admiral, and the recorded fleet inside Watchlist offer **View
  details**, including rows without chart captures. **Open full Navigator**
  carries the exact selected symbol/interval/MA and its own capture provenance.
  Closing returns keyboard focus to the original Cabin trigger.
- Details separate Navigator prices/timing from the older saved fleet snapshot,
  Oracle measurement coverage, and Council candidate classifications. Missing
  captures or normalized observations stay explicit; diagnostic-only rows are
  not described as observed prices. Original AAPL desk Tape/overview, mission
  outcomes, local watchlist preferences, and SHADOW restrictions are unchanged.
- This pass changes only Build Week presentation code/tests/documentation. No
  Battlestar or ModelDock modifications, provider calls, new mission, artifact
  edits, commit, merge, or push were performed.

Acceptance: 666 UI tests passed, including 28 Tape and 19 selection-helper
cases. Production build, local/upstream renderer checks, and diff whitespace
check passed; production output contains no demo assets. Playwright skill
checks at 1440×1080 and 1280×960 verified the 22 choices (21 fleet symbols plus
original AAPL), XLK details, exact SPY hourly/MA20 chart handoff, VXZ coverage,
Admiral/Watchlist entry, original-reference reset, focus return, scrolling,
and no horizontal overflow. A monitored symbol change made no requests.
No browser errors occurred; the existing Three.Clock deprecation warning
remains. Mission snapshot, Cabin context, and original market hashes are
unchanged. The separate browser regression suite was not rerun. An initial
reader timeout recovered on polling and did not recur on the final reload;
reader startup performance was not changed in this presentation pass.

## 2026-09-16 — Visible Oracle market narrative and coverage audit

- Oracle page 1 now opens with its recorded participation, leadership, rotation,
  and risk commentary, exact summary, source time, and coverage limitations.
  This content was already hash-loaded but was not surfaced by the ledger.
  The report's embedded narrative is preferred as one coherent source;
  standalone fallback checks recorded identifiers and does not fill gaps by
  mixing prose. Missing commentary stays explicit. The book retains six pages.
- The separate ModelDock page now exposes confidence wording, recorded model
  identity/time, all supplied source-linked statements, and uncertainty limits.
  Only loaded/indexed, safely confined artifact links are offered. Empty
  uncertainty lists do not mean certainty, and model wording cannot override
  Oracle exclusions, measurement authority, or action restrictions.
- Audited the seven excluded symbols: all were acquired successfully, but the
  canonical producer uses a fixed 14-symbol universe. Broadening it changes
  aggregate calculations and requires an explicit upstream analytical policy
  decision and a new immutable run. The missing-prior warning is independent:
  the snapshot path currently supplies no prior-return map. Full evidence and
  proposed boundaries are in [Recorded Oracle coverage](ORACLE_COVERAGE.md).
- No new data acquisition, ModelDock inference, mission run, artifact mutation,
  canonical Oracle changes, commit, or push was performed. Prior authorized
  Navigator registry changes remain untouched. Delphi forward-scenario output
  is separate and was not invented for this mission.

Acceptance: 617 UI tests (including 30 narrative component cases and two added
ledger integration cases), production build, and renderer snapshot check passed.
Playwright skill checks at 1280×960 and 1440×1080 verified native prose visible
without opening disclosures, scrollable warnings, five ModelDock source links,
source timestamps, uncertainty wording, six-page navigation, Escape/focus return,
and no horizontal overflow or browser errors. The visual review also prompted
darker inline evidence links for parchment contrast. Recorded mission and
Oracle/native/model narrative hashes match their original indexed references.
The separate browser regression suite was not rerun in this presentation pass;
production output contains no demo assets.

## 2026-09-16 — Captured fleet selection in Navigator

- Added a review-symbol picker to expanded Navigator and **Review chart** actions
  for captured symbols in Fleet Status and Admiral. Selection preserves an
  available interval/MA pair and changes the supplied chart data, not its label
  alone. Original AAPL overview/Tape, mission correlation, Oracle exclusions,
  Council/Governor results, watchlist preferences, and SHADOW safety stay intact.
- Added an optional exact-byte fleet catalog, bound to the mission's indexed
  normalized fleet snapshot. Capture and reader/browser validation enforce
  membership, symbol/pair identity, integrity, provenance, bounded sizes, and
  all-or-nothing publication. A concurrent mission update rejects acquisition
  instead of re-anchoring it. Existing single-symbol catalogs remain compatible.
- With the user's narrow authorization, canonical Navigator's existing registry
  gained the 19 missing recorded fleet symbols (SPY/QQQ were already supported),
  plus tests/documentation. No standalone provider API or client-side indicators
  were introduced. ModelDock was not called, restarted, or modified. Broader
  mission symbol semantics remain deferred for separate product review.
- Completed 315 real yfinance-backed captures for 21 symbols across 1h/1d/1wk
  and MA20/50/100/200/250. Capture completed at `2026-09-16T16:21:09.374094Z`;
  each dataset retains its own timestamp/cache metadata. All were marked
  non-stale by the provider at capture; this is not an ongoing freshness claim.
  Canonical source provenance records revision `78077983f7945528058102e466dd60a99d02622e`,
  backend SHA-256 `52f812b062003eba4b96890af2a22f8ba7440a125d72dab119197c2bba0dc2a7`,
  and a dirty-worktree flag for the uncommitted registry update.

Acceptance: 585 UI tests, 557 complete offline Python tests (including temporary
loopback HTTP checks), 86 canonical Navigator backend tests, production build,
and local/pinned/current upstream renderer checks passed. The 393-file verified
publication is 19,817,073 bytes; original market/context/snapshot hashes match
the pre-capture baseline. Playwright skill checks at 1440×1080 and 1280×960
verified 22 picker choices (21 fleet plus original AAPL), actual XLK/SPY/QQQ/VXZ/
QUAL data, hourly/weekly MA changes, full-chart hover, Fleet/Admiral focus return,
unchanged Tape, and no horizontal overflow. Selection issued zero new network
requests. No browser errors; the existing Three.Clock deprecation warning
remains. The separate automated browser regression suite was not rerun after
its earlier sandbox/aborted-retry issue. Normal production output omits demo
assets. The temporary market API was stopped; the read-only Cabin reader was
restarted on port 5174. Changes remain uncommitted on the two update branches;
no merge or push was performed.

## 2026-09-16 — Browser-local watchlist

- Added a separate local watchlist editor to the expandable Watchlist panel,
  with a direct link from Fleet Status and Admiral. Add/remove controls persist
  normalized symbol labels only in this browser at the current site address.
  The list starts empty; captured fleet records never silently seed it.
- Kept mission-derived coverage and Navigator-capture labels separate from
  local preferences. Adding a label does not capture prices, select a chart,
  onboard a Harbor symbol, or change the fleet supplied to future runs.
- Added bounded versioned storage, validation, duplicate handling, cross-tab
  rereads, and honest storage-error states. Unreadable data is not overwritten;
  retry is read-only. Dialog transitions preserve focus and the original
  Cabin trigger. Canonical mission evidence remains unchanged.

Acceptance: 445 UI tests and the production build passed, including 63 storage
tests and 25 watchlist component tests. LIVE browser verification at 1280×960
and 1440×1080 covered Fleet→Watchlist navigation, keyboard entry, duplicate and
invalid labels, persistence across reload, removal/focus return, source labels,
and no horizontal overflow or console errors. The three temporary test entries
were removed; the captured 21-symbol fleet stayed unchanged. The automated
browser regression rerun could not start because the sandbox denied its preview
port; an elevated retry was aborted before results. Production output was
restored without demo assets. Mission hashes and protected sibling worktrees
remain unchanged; pinned/current Navigator source checks passed.

## 2026-09-15 — Expandable instruments, Captain's Log, and recorded fleet

- Made all eight upper status cells and seven right-side instrument sections
  accessible expansion targets without moving their artwork-aligned facts.
  Fourteen readable detail modules explain source status, timing, governance,
  model provenance, portfolio availability, and SHADOW-only restrictions.
- The whole Captain's Log paper opens a readable captured-event timeline,
  with UTC timestamps, separate process/decision meanings, and exact summaries
  and recorded evidence links in disclosures. The SHADOW paper also opens even
  when no plan exists, explaining the canonical prerequisites without an
  activation, approval, or execution control.
- Fleet Status, Watchlist, and Admiral now show all observed symbols from the
  hash-verified normalized snapshot. Joined Oracle coverage and Council labels
  require matching snapshot IDs; missing evidence is disclosed. Text filtering
  is view-only. The configured fleet-input file is linked, not reconstructed.
  Current LIVE evidence shows 21 captured symbols, including seven excluded
  from Oracle measurements; AAPL remains separate supplemental chart context.
- Add/remove management awaits the user's choice of a separate watchlist or
  versioned configuration for future runs. No canonical fleet, historical
  capture, provider/model workflow, or trading authority was changed.

Acceptance: 354 UI tests, 13 existing browser regressions, production build,
and pinned/current Navigator source checks passed. LIVE browser checks verified
all new panel routes, Escape/focus return, no horizontal overflow, and exact
seven-symbol exclusion filtering. Checks at 1440×1080 and 1280×960 covered
the full-paper Log trigger, readable UTC times, source disclosures, and both
ModelDock instrument targets. Production output excludes demo assets.
Original market/context/snapshot hashes are unchanged; Battlestar and ModelDock
worktrees remain clean. Work is on `update/2026-09-15-cabin-panels-fleet`.

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
