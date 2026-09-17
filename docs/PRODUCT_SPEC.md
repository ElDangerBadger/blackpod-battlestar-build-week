# Captain's Cabin — live read-only product specification

Effective 2026-09-15. This document supersedes the Build Week/demo specification
as the governing product scope. Historical implementation notes, replay
fixtures, and scenario tests remain useful but do not impose an approved-only
or demo-default product boundary.

## Product objective

Give an operator an honest, continuously refreshed view of one explicitly
selected real mission, its recorded evidence, and its safety state through the
existing Captain's Cabin. Reuse Battlestar's Navigator V3 renderer behind the
existing presentation contracts. Do not redesign the Cabin or recreate domain
logic in the browser.

The current increment is a local, read-only product. Mission “Live” means
following validated canonical LIVE revisions, not launching mission workflows
or enabling trading. The separately authorized September 16 Alpaca extension
adds optional live last-trade prices in expanded Navigator; these are never
substituted for saved mission evidence.

The current reader follows one explicitly selected mission. Its recorded symbol
is a correlation field, not a requirement that the product have only one
reviewable symbol. Navigator can independently review captured fleet datasets.
Mission-wide symbol semantics and multi-symbol aggregation remain deferred for
product review; the reader does not combine missions into a portfolio result.

## Authority and boundaries

- Battlestar remains the canonical owner of its native mission components and
  Navigator renderer. The September 16 authorized exception adds the recorded
  fleet's missing symbols to its existing Navigator market registry, with tests
  and documentation. A subsequent explicit exception adds credential loading
  from the existing `buried_treasure` configuration and a read-only Alpaca
  price stream in Navigator's backend. All other canonical changes remain out
  of scope. See [Alpaca live market data](ALPACA_LIVE_MARKET.md).
- ModelDock remains a separately operated narrative appliance. The reader does
  not modify its repository, start it, or call it automatically.
- The Cabin renders mission artifacts; it cannot create, resume, approve,
  reject, retry, or otherwise mutate a mission.
- A mission's recorded Governor, operator, and Navigator states retain their
  separate meanings. Governor `PROCEED` is not mission approval.
- Navigator remains SHADOW-only: `VALIDATE` and `PLAN_ONLY` are allowed;
  `SUBMIT_ORDER`, `CANCEL_ORDER`, `MODIFY_PORTFOLIO`, and `BROKER_CALL` remain
  prohibited. “APPROVED” means `NAVIGATOR_SHADOW_HANDOFF`, not permission to trade.

See [Safety Boundary](SAFETY_BOUNDARY.md) for the component-level rules.

## Current product requirements

### Independent Sentry observation ledger

The Sentry navigation entry reads an explicitly configured canonical observation
archive independently of mission evidence. The existing mission-warnings paper
remains separate. Recorded classifications, scores, reasons, risks, and missing
inputs are explained without rerunning analysis. Source times and research
labels remain prominent; synthetic archives cannot become live detections or
feed watchlist/Navigator handoffs. No scanner or producer is started by opening
or refreshing the ledger. See [Sentry ledger](SENTRY_LEDGER.md) for configuration
and validation boundaries.

### Source selection and automatic refresh

The operator explicitly configures an artifact root and a single mission ID
when starting the local reader. The reader never scans a sibling checkout,
selects an arbitrary newest directory, or silently changes missions. The
source must use the existing canonical mission-store layout and LIVE mode.

The browser checks that source every five seconds. It accepts a publication
only after transport, schema, integrity, and mission-correlation checks. A
single immutable publication is used for each coherent displayed update.
Canonical mission schemas are unchanged; a generic publication manifest is an
additive transport contract, not a new mission engine or approval gate.

### Legitimate mission states

The product must display valid evidence for all canonical outcomes:
`INCOMPLETE`, `HELD`, `VETOED`, `FAILED`, and `APPROVED`. It must also represent
stage progression, including `NOT_STARTED`, `RUNNING`, `SUCCEEDED`, `FAILED`,
and `SKIPPED`, without collapsing component-native dispositions into technical
status. A valid held or failed mission is not a broken demo package.

Unpublished, missing, malformed, inconsistent, or hash-invalid evidence is a
reader/data availability issue; it must not be turned into a fabricated
canonical mission failure or approval.

### Honest freshness and availability

Connection to the artifact reader, the last successful check, and the age of
recorded evidence are separate facts. The original snapshot observation time,
market capture time, latest chart bar, portfolio capture time, and ModelDock
inference time are not rewritten when the browser polls.

A source outage or invalid update may leave the last verified evidence visible
for context, but the UI must explicitly mark it as last verified and
degraded/offline. It must not substitute replay, show unverified new bytes, or
make stale evidence look fresh by changing its timestamp. With no previous
verified evidence, show setup or unavailable state, not invented mission cards.

The reader does not prove present ModelDock inference readiness, refresh
quotes, or update portfolio holdings. Those facts require separately recorded
evidence from their owners.

### Presentation and accessibility

Preserve the calibrated artwork, books, Captain's Log, transparent SVG Mission
Chart overview, and expanded Navigator V3. Keep mission data behind the existing
adapter and presentation models. Modals isolate background controls, contain
keyboard focus, close with Escape, and restore focus to their opening control.
WebGL failure continues to use the canonical SVG fallback.

Every opened ledger page leads with a plain-language reading of the supplied
evidence: the result, what its fields mean, and the limits on interpretation.
Technical process completion is distinct from readiness, action clearance, and
operator approval. Exact recorded values remain available in a disclosure,
with original artifact links preserved. These are deterministic presentation
glosses, not new model-generated analysis, scores, or rewritten evidence.
Unrecognized codes remain explicitly uninterpreted; missing evidence is not
converted into a negative finding or an invented value.

Oracle's opening page surfaces its recorded market narrative: participation,
leadership, rotation, risk posture, original summary, source time, and limitations.
It uses the report's embedded narrative when available, otherwise a correlated
standalone narrative, without splicing prose across partial sources. Missing
commentary stays missing. The separate ModelDock page exposes its recorded
interpretation, confidence explanation, cited statements, and uncertainty limits;
an empty uncertainty list is not proof of certainty. Links use only loaded,
indexed mission evidence. No inference is triggered by opening either page.
These views do not manufacture Delphi forward scenarios or expand Oracle's
measurement universe. See [recorded Oracle coverage](ORACLE_COVERAGE.md).

The Navigator Reference Tape opens a read-only, multi-symbol detail module.
It defaults to the original reference from the desk, or the selected item when
opened from Fleet/Admiral/recorded Watchlist coverage. Symbol, interval, and MA
selectors use exact captured datasets; **Open full Navigator** carries the same
symbol and interval/MA into the expanded chart. Prices, timestamps, provider
metadata, and artifact links belong to the selected capture. The separate saved
fleet observation and Oracle/Council classifications retain their own provenance
and units. A fleet item without a chart capture still has a detail view, with no
invented price history or MA. Watchlist-only labels do not become datasets.
The collapsed desk tape and overview retain the original mission reference;
expanded selections are temporary presentation state, not evidence mutations.
Mission warnings explain known data-coverage and
permission limits, with exact warning text expandable underneath. Long content
scrolls within the parchment panels; inactive ledger pages are excluded from
keyboard focus.

Upper status cells and right-side instrument panels open readable, scrollable
detail modules. The complete Captain's Log paper and the SHADOW-plan paper are
also click targets. Log details preserve captured order and exact summaries,
show human-readable UTC timestamps, and link to their recorded source artifacts.
SHADOW-plan details explain the distinction between a market chart and an
operational plan, and describe the canonical approval/handoff prerequisites
without adding activation, approval, or execution controls.

Fleet status, Watchlist, and Admiral expose the full observed symbol list from
the saved normalized Oracle snapshot. Prices/returns retain source units;
Oracle coverage and Council classifications join only on matching snapshot IDs.
Without that snapshot, the view explicitly falls back to available analytical
records, not an invented configured roster. The captured fleet-input file is
linked separately. Text filtering changes only the view. Observed fleet symbols,
configured membership, portfolio holdings, and the supplemental Navigator symbol
are distinct scopes.

Watchlist also has a separate, editable local list, reachable from Fleet Status
and Admiral. It starts empty and stores only normalized symbol labels in this
browser's origin-scoped localStorage (`blackpod.cabin.local-watchlist.v1`,
version 1); it is not account/device synchronization. Add/remove operations
persist up to 100 unique labels, with a 20-character limit per symbol. Labels
are unverified and do not onboard a Harbor symbol, change future-run fleet
configuration, fetch quotes, select Navigator symbols, or mutate any mission.
Per-symbol evidence labels refer only to the displayed mission, with recorded
fleet coverage distinct from Navigator captures. Clearing site data removes
local preferences; changing browser, host, or port creates a separate list.

Storage failures and malformed/unsupported saved data pause editing, preserve
existing bytes, and never report an unsaved change as persisted. Read retry
does not reset data. Other-tab storage events refresh the displayed list, and
each mutation rereads storage; simultaneous cross-tab writes are not atomic.
Canonical fleet configuration and arbitrary-symbol market acquisition remain
out of scope, as do broker account, approval, and execution actions. The narrow
Alpaca market-data exception does not grant any of those authorities.

The expanded renderer can select a trailing visible-history window and adjust
ship-view price/MA separation as local presentation state. The latest captured
close remains the captured-history anchor; an enabled live last-trade overlay
can move the ship relative to it. Source MA values, summaries, and provenance
are not recomputed or overwritten. Full chart view returns to normal visual scale.
History duration is not bar interval. Alternate bar intervals and MA periods
select exact captured canonical Navigator responses from an optional, hash-bound
presentation catalog. The catalog is an additive transport supplement; existing
mission, default market, and Cabin context contracts remain unchanged. The
original capture remains the overview/default. Every alternate exposes its own
capture time and provenance; unavailable pairs are disabled. Captured-pair
selection never fetches replacement history, computes indicators, or mutates
mission artifacts. The separately enabled live-price subscription follows the
selected recorded symbol without changing these captures.

An additional hash-bound fleet catalog permits symbol selection in the expanded
Navigator and direct chart review from Fleet Status and Admiral. Membership
must match the mission's exact normalized Oracle snapshot; a local watchlist
label alone never authorizes a capture. Each response retains its own symbol,
interval/MA, timestamps, provider metadata, and source fingerprint. Uncaptured
symbols are unavailable, not relabeled AAPL data. The selected chart does not
rewrite the overview, original desk tape, mission symbol, Oracle findings, or
Council/Governor outcomes. Market captures for Oracle-excluded symbols do not
change their recorded analytical exclusion.

Normal product use has no Demo/Live switch or replay theater. Historical
playback is explicitly requested through `?mode=replay` in a developer review
environment; `?mode=demo` is a compatibility alias. Replay remains deterministic
and visibly labeled. Production startup and build do not prepare or publish
demo packs.

### Local operation

Serve the built UI and verified publications through a loopback-only reader.
The reader exposes read operations only, retains a bounded number of
publications in memory, and does not persist, repair, or overwrite source
artifacts. Unconfigured startup is permitted so the UI can explain setup.
No automatic provider health probe, mission command, or market acquisition runs
as a side effect of opening the Cabin.
Opening expanded Navigator starts its read-only price subscription only when
the operator has explicitly enabled the canonical service and Cabin relay.

This increment is not a remotely exposed or multi-user deployment. Network
hosting, authentication, operational supervision, and durable historical
publication retention require a separate deployment scope.

## Acceptance criteria

1. Default startup uses LIVE and does not execute the judge/demo workflow.
2. An explicitly selected valid LIVE mission appears regardless of its outcome;
   subsequent valid revisions update without a manual repackaging step.
3. Missing source configuration, offline access, stale evidence, and invalid
   updates are visible without replay fallback or silent timestamp rewriting.
4. Mutation requests, unsafe paths, source substitution, and invalid hashes
   fail closed. Displaying evidence does not change the source tree.
5. Existing presentation contracts, modal interactions, SVG/V3 rendering,
   SHADOW declarations, and deterministic replay checks remain intact.
6. Normal builds omit prepared demo data; replay review is explicit.

Automated acceptance and a fresh, user-selected LIVE source review are distinct
checks. A passing fixture suite or an old LIVE artifact is not proof of a
currently operating mission producer, current market acquisition, or active
ModelDock readiness.

## Roadmap — not enabled in this release

- Chart drawing and annotations as presentation-only overlays, with separately
  defined persistence and undo behavior; never modify supplied market evidence
  or create trading instructions.
- Add-symbol and universe-management workflows, with explicit source ownership,
  supported universe semantics, validation, and operator intent. A symbol input
  must not merely relabel fixed-fleet Oracle evidence.
- Mission-wide symbol semantics and multi-symbol aggregation, following a
  separate product review; independent chart selection is not that redesign.
- Mission initiation/resume and explicit operator decisions, after a separate
  authorization and interaction design review.
- Trading integration, only under a separately defined execution boundary,
  permissions, risk controls, auditability, and confirmation policy. The user's
  future trading intent is not execution authority for this release.
- A shared upstream Navigator renderer package to replace the currently pinned,
  reviewed consumer snapshot. This requires separately authorized Battlestar
  work; the source drift check remains the maintenance mechanism now.

## Historical material

[Build Week history](BUILD_WEEK_HISTORY.md), [Demo Runbook](DEMO_RUNBOOK.md),
and [LIVE Demo Runbook](LIVE_DEMO_RUNBOOK.md) are archived specifications and
legacy workflow references. Preserve them and the replay fixtures for
provenance; do not use their shortcuts as live read-only startup dependencies.
