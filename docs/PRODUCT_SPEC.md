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

The current increment is a local, read-only product. “Live” means following
validated canonical LIVE mission revisions, not launching mission workflows,
streaming exchange quotes, or enabling trading.

Initial operation follows one explicitly selected mission/symbol in the Harbor.
Multi-symbol aggregation is deferred to the later V6/V7 roadmap; the current
reader does not combine independent missions into a portfolio-level result.

## Authority and boundaries

- Battlestar remains the canonical owner of its native mission components and
  Navigator renderer. Its repository is read-only during this work.
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

- Add-symbol and universe-management workflows, with explicit source ownership,
  supported universe semantics, validation, and operator intent. A symbol input
  must not merely relabel fixed-fleet Oracle evidence.
- Multi-symbol aggregation in the later V6/V7 scope, after the first single
  mission/symbol path is operational and its evidence boundaries are verified.
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
