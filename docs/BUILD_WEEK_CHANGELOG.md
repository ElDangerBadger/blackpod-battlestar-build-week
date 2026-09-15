# Build Week Changelog

This document records submission-scope changes. It is not the upstream
Battlestar or ModelDock changelog; both sibling repositories remain read-only.

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

## Feature-freeze statement

Demo readiness changes package and explain existing capabilities. They do not
add analytical rules, Council policy, Governor policy, operator authority,
Navigator execution policy, ModelDock authority, broker integration, or a new
service subsystem.
