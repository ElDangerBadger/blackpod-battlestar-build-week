# Build Week Changelog

This document records submission-scope changes. It is not the upstream
Battlestar or ModelDock changelog; both sibling repositories remain read-only.

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
