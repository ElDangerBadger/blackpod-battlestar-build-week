# BlackPod Battlestar Build Week

This repository contains the Build Week submission spine. Stage 1, Phase 1
initializes a mission through Harbormaster. Phase 2 runs the existing
Battlestar Oracle. Phase 3 adds Battlestar's existing candidate, Senate,
Council synthesis, and Council executive-summary interfaces. Phase 4 adds the
current Battlestar Governor preparation, deliberation, readiness, and rendered
decision flow. Phase 5 closes Stage 1 with an explicit operator approval gate
and the current Navigator handoff, intake, and non-executing SHADOW plan.
Stage 2, Phase 1 adds a strictly bounded ModelDock narrative-enrichment step
after Oracle succeeds and before Council runs. ModelDock is a local LLM
appliance in this path; it does not become an analytical or decision authority.
Stage 2, Phase 2 adds the canonical one-command orchestration path, resumable
stage stops, and deterministic presentation projections over that existing
mission lifecycle. Stage 2, Phase 3 packages those frozen capabilities into
validated demo scenarios, replay/live preflight, and a repeatable reviewer
runbook without adding another mission engine.

## Judge / Reviewer Quick Start

The deterministic judge path is offline and ends at a Navigator SHADOW plan.
It never starts ModelDock, calls a market-data service, or imports or invokes a
broker operation.

```bash
export BATTLESTAR_PATH=/absolute/path/to/blackpod_battlestar
make setup
make judge
```

`make judge` runs replay preflight and the canonical approved mission, then
prints the path to `presentation/mission_brief.html`. The brief is a
deterministic, read-only view; `mission_summary.json`, `captains_log.json`,
`demo_manifest.json`, and the immutable snapshot chain remain canonical. Run
`make test` for the full offline suite, `make validate-demo-packs` for all
scenarios, and `make rehearse-approved` for the cold/warm idempotency proof.

To open the same approved mission in the read-only Captain's Cabin:

```bash
npm --prefix ui install
make cabin-prepare
make cabin-dev
```

`make cabin-prepare` first preserves the existing `make judge` workflow, then
validates and materializes its completed mission beneath the ignored
`ui/public/demo/approved/` directory. Use `make cabin-test` for the focused
frontend tests and `make cabin-build` for a production build. The cabin is an
interactive presentation of existing evidence; it cannot run or resume a
mission, record approval, or invoke any execution operation.

`BATTLESTAR_PATH` is required and deliberately has no repository-topology
default. Both sibling repositories remain read-only. Use a new contained root,
such as `DEMO_ROOT=artifacts/rehearsal-002`, when a visibly fresh run is
needed; completed identical missions otherwise return an explicit idempotent
no-op.

The approved rehearsal proves the complete sequence from mission acceptance
through explicit `APPROVE_HANDOFF` and a created Navigator SHADOW plan. It
validates the snapshot hash chain, captured artifact hashes, Captain's Log, and
mission summary. Governor `PROCEED` alone never means approval.

Detailed reviewer material:

- [Demo Runbook](docs/DEMO_RUNBOOK.md)
- [Architecture](docs/ARCHITECTURE.md)
- [Safety Boundary](docs/SAFETY_BOUNDARY.md)
- [Build Week Changelog](docs/BUILD_WEEK_CHANGELOG.md)
- [Captain's Cabin](docs/CAPTAINS_CABIN.md)

Harbormaster owns:

- strict validation of `blackpod.mission_request.v1`;
- stable mission identifier allocation;
- canonical `blackpod.mission_snapshot.v1` revisions;
- contained, immutable, hashed mission artifacts and atomic current-snapshot
  publication;
- the narrow Build Week adapters that invoke the sibling Battlestar Oracle,
  Council evidence chain, Governor decision flow, operator gate, and Navigator
  SHADOW workflow;
- the strict local ModelDock client and Oracle narrative-enrichment
  contract;
- state-driven unified mission orchestration and deterministic Captain's Log
  and mission-summary projections; and
- correlation, stage transitions, artifact lineage, and Battlestar provenance
  for one immutable attempt per implemented stage.

Battlestar remains the owner of Oracle acquisition, candidate generation,
Senate deliberation, advisor-health validation, Council synthesis, and
executive-summary logic, as well as Governor preparation, deliberation,
readiness, and decision rendering. Battlestar also owns the current operator
action, Navigator handoff, intake, and SHADOW-plan contracts. The Build Week
adapters do not reproduce
calculations, introduce voting rules, add risk formulas, or add market-analysis
policy. ModelDock may explain validated Oracle evidence, but Oracle remains
authoritative for every measurement, market fact, diagnostic, readiness state,
and typed analytical conclusion. ModelDock cannot approve a mission, render a
Governor disposition, recommend or execute an order, or call Council,
Governor, operator, Navigator, ModelDock-external providers, or broker APIs.
Stage 1 contains no ModelDock integration. Stage 2 adds the bounded local
narrative seam plus orchestration and presentation over existing stage logic.
The repository contains no broker execution, order submission, order
cancellation, portfolio modification, web service, database, queue, daemon,
scheduler, or state-changing UI. The generated mission brief and Captain's
Cabin are read-only projections of canonical JSON.

## Python and setup

The package supports Python 3.11 or newer. Its only required third-party
dependency is PyYAML, which Battlestar's native fleet parser uses in both
transports. LIVE additionally uses Battlestar's native `yfinance` acquisition
path; install the optional extra when LIVE is needed.

```bash
python3.11 -m venv .venv
.venv/bin/python3.11 -m pip install -e .
# LIVE only:
.venv/bin/python3.11 -m pip install -e '.[live]'
```

Point `BATTLESTAR_PATH` at a read-only sibling Battlestar checkout. Keep the
checkout and Build Week artifact root completely disjoint.

```bash
export BATTLESTAR_PATH=../../BlackPod-Versions/blackpod_battlestar
```

Before a stage runs, preflight verifies that this is a directory, that its
required native modules exist, and that Git revision and worktree state can be
reported. Council preflight additionally checks the candidate, Senate,
Mandate, runtime-validation, advisor-health, synthesis, and executive-summary
modules. Governor preflight checks the current Senate-intake, preparation,
deliberation, readiness, and decision-rendering modules. Phase 5 additionally
checks the Governor decision consumer, explicit operator action, Navigator
handoff, Navigator intake, and documented SHADOW workflow modules. A dirty worktree is
allowed for development and recorded clearly. Use
`--strict-battlestar-clean` on a stage command when a dirty checkout must be
rejected. Neither preflight nor execution writes to the Battlestar checkout.

Run the complete Build Week test suite without live market access:

```bash
.venv/bin/python3.11 -m unittest discover -s tests -v
```

## Phase 1: initialize a mission

Initialize either example request:

```bash
.venv/bin/python3.11 -m blackpod_build_week.harbormaster --request examples/mission_request.live.json
.venv/bin/python3.11 -m blackpod_build_week.harbormaster --request examples/mission_request.replay.json
```

Use `--artifacts-root <path>` to place the `missions/` directory somewhere
other than the default `artifacts/` directory. Repeating initialization for the
same `mission_id` is intentionally an error; Harbormaster never overwrites or
silently resumes an existing mission.

Initialization is fail-closed. If persistence fails after the mission directory
is reserved, the partial directory is retained for inspection and a retry with
that same `mission_id` is reported as a duplicate rather than overwriting it.

### Request contract and identifiers

The required top-level fields are `schema_version`, `request_id`, `run_mode`,
`symbol`, `requested_at`, and `operator_id`. `metadata` and `mission_id` are
optional. Unknown top-level fields are rejected; arbitrary JSON data belongs
inside `metadata`.

Identifiers must be nonblank and may not have leading or trailing whitespace.
An explicit `mission_id` must be one safe filesystem segment and must differ
from `request_id`. When omitted, Harbormaster derives
`mission-<mode>-<24 hex characters>` from the SHA-256 of the canonical request.
This makes retries stable in both modes and guarantees deterministic REPLAY
identifiers without random input.

`requested_at` must be a timezone-aware RFC 3339 timestamp and is normalized to
UTC with a `Z` suffix. REPLAY initialization uses this timestamp for both
`started_at` and `observed_at`, keeping deterministic requests deterministic.
LIVE initialization uses one current UTC reading. Harbormaster never changes a
request's `LIVE` or `REPLAY` mode.

Revision 1 records a SHA-256 digest of the committed request and has
`previous_snapshot_sha256: null`. Its state is:

- Harbormaster: `SUCCEEDED` with native state `INITIALIZED`;
- Oracle, Council, Governor, and Navigator: `NOT_STARTED`;
- outcome: `INCOMPLETE`;
- current phase: `ORACLE`; and
- terminal: `false`.

Phase 1 CLI exit codes are `0` for success, `2` for invalid
request/schema/unsafe path, `3` for duplicate initialization, and `4` for
persistence failures.

## Phase 2: run Oracle

The narrow adapter calls:

```text
blackpod.runtime.oracle_pipeline.run_oracle_pipeline
```

It records the Battlestar Git revision, branch when available, dirty-worktree
flag, entry point, and run mode without placing an absolute checkout path in a
snapshot. It preserves `mission_id` and `request_id`; the request `symbol` is
correlation metadata and does not filter Battlestar's existing Oracle fleet.

### Deterministic REPLAY verification

The committed fixture supplies deterministic quotes to the native Oracle
pipeline. It is an input fixture, not a precomputed mission snapshot. REPLAY
never calls live acquisition and never falls back to LIVE.

From a clean `artifacts/phase2-demo` root, run exactly:

```bash
export BATTLESTAR_PATH=../../BlackPod-Versions/blackpod_battlestar
.venv/bin/python3.11 -m blackpod_build_week.harbormaster \
  --request examples/mission_request.replay.json \
  --artifacts-root artifacts/phase2-demo
.venv/bin/python3.11 -m blackpod_build_week.harbormaster run-oracle \
  --mission-id mission-buildweek-replay-001 \
  --artifacts-root artifacts/phase2-demo \
  --replay-fixture fixtures/oracle_replay_quotes.v1.json
```

A technically successful run writes a RUNNING revision and then a SUCCEEDED
revision. The final Phase 2 state is:

- Harbormaster: `SUCCEEDED`;
- Oracle: `SUCCEEDED`, with its native analytical state preserved;
- Council, Governor, and Navigator: `NOT_STARTED`;
- outcome: `INCOMPLETE`;
- current phase: `COUNCIL`; and
- terminal: `false`.

Oracle warnings or a native non-ready analytical state are preserved as native
state and are not converted to technical failure. A malformed return,
acquisition exception, or expired deadline is a technical failure and produces
a `FAILED` Oracle snapshot with a sanitized structured error. The process-boundary
deadline defaults to 60 seconds and can be changed with `--deadline-seconds`.

### LIVE transport

For a LIVE mission, omit `--replay-fixture`:

```bash
.venv/bin/python3.11 -m blackpod_build_week.harbormaster run-oracle \
  --mission-id <live-mission-id> \
  --artifacts-root artifacts
```

LIVE invokes Battlestar's current acquisition and pipeline path, which requires
the optional `yfinance` dependency, provider availability, and network access.
Acquisition failure is reported explicitly and the command exits nonzero. LIVE
never falls back to REPLAY, and REPLAY never falls back to LIVE.

### Idempotency and restart policy

Phase 2 permits only the first Oracle attempt. A repeated identical invocation
after `SUCCEEDED` validates the existing result and returns an explicit no-op;
it does not rewrite an artifact or snapshot. An existing `RUNNING` state is an
interrupted-attempt conflict, and an existing `FAILED` state is a failed-attempt
conflict. Both exit nonzero. Phase 2 deliberately has no force or retry option.

Immutable snapshot revisions and Oracle artifacts are created exclusively. A
collision is an error, never an overwrite.

## Phase 3: run Council

Council requires a technically successful Oracle stage in `COUNCIL` phase.
It consumes only explicitly recorded mission artifacts: Oracle normalized
fleet data, readiness, report, assessment, narrative, and one versioned policy
input. It then invokes Battlestar's existing deterministic chain:

```text
Oracle normalized snapshot + readiness
  -> trading candidate report
  -> Senate review packet + Oracle report
  -> Senate deliberation
  -> native Council input packet + Mandate
  -> native runtime validation + advisor health
  -> Council synthesis
  -> Council executive summary
```

The advisor-health input to synthesis is derived by Battlestar's native
`build_runtime_validation_report` and `build_advisor_health_summary`
interfaces from an explicit mission-relative advisor manifest; Phase 3 does
not assume or fabricate a healthy state. Every Council input and output is
recorded in a versioned lineage manifest
with its mission-relative path, producer, SHA-256, size, native contract when
known, originating component revision, and mission/request correlation. The
canonical snapshot never stores absolute checkout paths.

### Deterministic Oracle-to-Council replay

Use a new artifact root and run exactly:

```bash
export BATTLESTAR_PATH=../../BlackPod-Versions/blackpod_battlestar
.venv/bin/python3.11 -m blackpod_build_week.harbormaster \
  --request examples/mission_request.replay.json \
  --artifacts-root artifacts/phase3-demo
.venv/bin/python3.11 -m blackpod_build_week.harbormaster run-oracle \
  --mission-id mission-buildweek-replay-001 \
  --artifacts-root artifacts/phase3-demo \
  --replay-fixture fixtures/oracle_replay_quotes.v1.json
.venv/bin/python3.11 -m blackpod_build_week.harbormaster run-council \
  --mission-id mission-buildweek-replay-001 \
  --artifacts-root artifacts/phase3-demo \
  --replay-fixture fixtures/council_replay_policy.v1.json
```

The Council replay fixture supplies deterministic Mandate policy context; it
is not a precomputed synthesis, summary, or mission snapshot. REPLAY invokes
the same native loaders, candidate generator, Senate interfaces, synthesis,
summary, validation, artifact capture, and snapshot transitions as LIVE.
Replay never calls live acquisition and never falls back to LIVE.

On technical success, revision 4 records Council `RUNNING` and revision 5
records Council `SUCCEEDED`. The final state is:

- Harbormaster, Oracle, and Council: `SUCCEEDED`;
- Council native state: one of `ALIGNED`, `MIXED`, `CONFLICTED`, `DEGRADED`, or
  `BLOCKED`;
- Governor and Navigator: `NOT_STARTED`;
- outcome: `INCOMPLETE`;
- current phase: `GOVERNOR`; and
- terminal: `false`.

All five native Council states are technically successful results. Warnings,
blockers, alignments, conflicts, and item-level Senate disagreement remain in
the native artifacts and typed result; Phase 3 does not invent a single
Council score.

### LIVE Council transport

LIVE Council reuses the completed LIVE mission's Oracle artifacts and performs
no additional market acquisition. Supply an explicit versioned policy input:

```bash
.venv/bin/python3.11 -m blackpod_build_week.harbormaster run-council \
  --mission-id <live-mission-id> \
  --artifacts-root artifacts \
  --policy-input <council-policy-input.json>
```

LIVE rejects `--replay-fixture`; REPLAY rejects `--policy-input`. A missing,
malformed, or structurally invalid required input fails explicitly. A valid
restrictive or stale Mandate can produce native Council `BLOCKED` without
becoming a technical execution failure.

### Council idempotency and restart policy

Phase 3 matches Oracle's one-attempt policy. Repeating an identical completed
Council command validates the stored provenance, input hash, canonical output
set, and lineage, then returns an explicit no-op without writing anything.
An existing `RUNNING` or `FAILED` Council attempt is a conflict and exits
nonzero. There is no force, retry, resume, or overwrite option in Phase 3.

## Phase 4: run Governor

Governor requires successful Oracle and Council stages with the mission in
`GOVERNOR` phase. It verifies the hashes, sizes, contracts, lineage, and
correlation identifiers of the recorded Oracle report, diagnostics and
readiness; Council synthesis and executive summary; candidate and Senate
evidence; Mandate policy; advisor health; and Council lineage manifest. It
never reads an arbitrary "latest" sibling-repository artifact.

The narrow adapter then invokes these current Battlestar Python entry points:

```text
blackpod.governor.governor_senate_intake.build_governor_senate_intake
blackpod.governor.governor_deliberation_prep.build_governor_deliberation_prep
blackpod.governor.governor_deliberation.build_governor_deliberation
blackpod.governor.governor_decision_readiness.build_governor_decision_readiness
blackpod.governor.governor_decision.build_governor_decision
```

The preparation entry point is
`blackpod.governor.governor_deliberation_prep.build_governor_deliberation_prep`;
the rendering entry point is
`blackpod.governor.governor_decision.build_governor_decision`. The only native
decision contract accepted as a canonical mission output in either transport is
`blackpod.contracts.governor_decision.GovernorDecision`. Build Week records a
correlated `blackpod.governor_rendered_decision.v1` view of that contract. The
legacy `WATCH_ONLY`, `NO_ACTION`, passive-bridge, and alternate Governor
contracts are rejected.

### Rendered dispositions and operator placeholder

All five canonical dispositions are technically successful Governor results,
so the CLI exits `0` for each. Only a schema, integrity, precondition,
execution, or deadline failure exits nonzero.

| Governor disposition | Mission phase | Mission outcome | Operator route | Terminal |
| --- | --- | --- | --- | --- |
| `PROCEED` | `OPERATOR` | `HELD` | `PENDING_APPROVAL` | `false` |
| `HOLD` | `OPERATOR` | `HELD` | `PENDING_REVIEW` | `false` |
| `REVIEW_REQUIRED` | `OPERATOR` | `HELD` | `PENDING_REVIEW` | `false` |
| `BLOCKED` | `GOVERNOR` | `HELD` | `CLOSED_BLOCKED` | `true` |
| `STAND_DOWN` | `COMPLETE` | `VETOED` | `CLOSED_NO_ACTION` | `true` |

`PROCEED` is a recommendation to enter operator review. It is not approval,
does not produce `APPROVED`, and does not produce `APPROVED_FOR_HANDOFF`. Phase
4 records only the placeholder route; `operator.action`, `operator.result`,
`operator.operator_id`, and `operator.acted_at` all remain `null`. No operator
action is executed, and Navigator remains `NOT_STARTED` for every disposition.

On a technically successful run, revision 6 records Governor `RUNNING` and
revision 7 records Governor `SUCCEEDED` with the native disposition preserved.
A technical failure instead records Governor `FAILED`, leaves the phase at
`GOVERNOR`, produces mission outcome `FAILED`, and exits nonzero.

### Deterministic Oracle-to-Council-to-Governor replays

Each command set below requires `BATTLESTAR_PATH` and a new, unused artifact
root. The Governor fixtures are deterministic supporting context, not
precomputed decisions or final mission snapshots. Each replay exercises the
same Build Week validation, native Governor preparation and rendering,
artifact capture, lineage, and snapshot transitions.

PROCEED to `HELD` / `PENDING_APPROVAL`:

```bash
export BATTLESTAR_PATH=../../BlackPod-Versions/blackpod_battlestar
.venv/bin/python3.11 -m blackpod_build_week.harbormaster \
  --request examples/mission_request.replay.json \
  --artifacts-root artifacts/phase4-demo-proceed
.venv/bin/python3.11 -m blackpod_build_week.harbormaster run-oracle \
  --mission-id mission-buildweek-replay-001 \
  --artifacts-root artifacts/phase4-demo-proceed \
  --replay-fixture fixtures/oracle_replay_quotes.v1.json
.venv/bin/python3.11 -m blackpod_build_week.harbormaster run-council \
  --mission-id mission-buildweek-replay-001 \
  --artifacts-root artifacts/phase4-demo-proceed \
  --replay-fixture fixtures/council_replay_policy.v1.json
.venv/bin/python3.11 -m blackpod_build_week.harbormaster run-governor \
  --mission-id mission-buildweek-replay-001 \
  --artifacts-root artifacts/phase4-demo-proceed \
  --replay-fixture fixtures/governor_replay_context.proceed.v1.json
```

HOLD to `HELD`:

```bash
export BATTLESTAR_PATH=../../BlackPod-Versions/blackpod_battlestar
.venv/bin/python3.11 -m blackpod_build_week.harbormaster \
  --request examples/mission_request.replay-hold.json \
  --artifacts-root artifacts/phase4-demo-hold
.venv/bin/python3.11 -m blackpod_build_week.harbormaster run-oracle \
  --mission-id mission-buildweek-replay-hold-001 \
  --artifacts-root artifacts/phase4-demo-hold \
  --replay-fixture fixtures/oracle_replay_quotes.risk_off.v1.json
.venv/bin/python3.11 -m blackpod_build_week.harbormaster run-council \
  --mission-id mission-buildweek-replay-hold-001 \
  --artifacts-root artifacts/phase4-demo-hold \
  --replay-fixture fixtures/council_replay_policy.v1.json
.venv/bin/python3.11 -m blackpod_build_week.harbormaster run-governor \
  --mission-id mission-buildweek-replay-hold-001 \
  --artifacts-root artifacts/phase4-demo-hold \
  --replay-fixture fixtures/governor_replay_context.hold.v1.json
```

STAND_DOWN to `VETOED`:

```bash
export BATTLESTAR_PATH=../../BlackPod-Versions/blackpod_battlestar
.venv/bin/python3.11 -m blackpod_build_week.harbormaster \
  --request examples/mission_request.replay-stand-down.json \
  --artifacts-root artifacts/phase4-demo-stand-down
.venv/bin/python3.11 -m blackpod_build_week.harbormaster run-oracle \
  --mission-id mission-buildweek-replay-stand-down-001 \
  --artifacts-root artifacts/phase4-demo-stand-down \
  --replay-fixture fixtures/oracle_replay_quotes.v1.json
.venv/bin/python3.11 -m blackpod_build_week.harbormaster run-council \
  --mission-id mission-buildweek-replay-stand-down-001 \
  --artifacts-root artifacts/phase4-demo-stand-down \
  --replay-fixture fixtures/council_replay_policy.v1.json
.venv/bin/python3.11 -m blackpod_build_week.harbormaster run-governor \
  --mission-id mission-buildweek-replay-stand-down-001 \
  --artifacts-root artifacts/phase4-demo-stand-down \
  --replay-fixture fixtures/governor_replay_context.stand_down.v1.json
```

### LIVE and REPLAY Governor transports

A LIVE Governor mission uses only the current mission's completed Oracle and
Council artifacts and requires explicit versioned supporting context:

```bash
.venv/bin/python3.11 -m blackpod_build_week.harbormaster run-governor \
  --mission-id <live-mission-id> \
  --artifacts-root artifacts \
  --context-input <governor-supporting-context.json>
```

LIVE rejects `--replay-fixture`; REPLAY rejects `--context-input` and requires
`--replay-fixture`. Governor performs no market acquisition in either mode and
never falls back between transports. The mission's run mode and all correlation
identifiers must agree with the supporting context. The hard worker deadline
defaults to 60 seconds and is configurable with `--deadline-seconds`.

### Governor idempotency and restart policy

Phase 4 follows the Oracle/Council one-attempt convention. Repeating an
identical completed command verifies Battlestar provenance, the supporting
context hash, canonical inputs and outputs, lineage, disposition, and operator
route, then returns an explicit no-op without writing anything. An existing
Governor `RUNNING` or `FAILED` state is a conflict and exits nonzero. There is
no force, retry, resume, or overwrite option in Phase 4; snapshot revisions and
Governor artifacts are created exclusively.

## Phase 5: operator gate and Navigator SHADOW plan

Phase 5 deliberately separates human authorization from Navigator work. A
Governor `PROCEED` result leaves the mission `HELD` at
`PENDING_APPROVAL`. It cannot start Navigator and is never interpreted as an
approval. The operator must issue a separate, explicit action:

```text
PROCEED
  -> PENDING_APPROVAL
  -> APPROVE_HANDOFF
  -> APPROVED_FOR_HANDOFF
  -> handoff STAGED
  -> intake ACCEPTED
  -> SHADOW plan CREATED
  -> APPROVED
```

The operator adapter accepts only the current native actions supported for a
`PENDING_APPROVAL` route:

- `APPROVE_HANDOFF` produces `APPROVED_FOR_HANDOFF`, advances to
  `NAVIGATOR`, and keeps the mission `HELD`;
- `REJECT` produces `REJECTED`, leaves Navigator `NOT_STARTED`, and closes the
  mission as `VETOED`.

`LEAVE_PENDING` is a control option in Battlestar's combined interactive
workflow, not a recorded native operator action. Phase 5 does not invent it as
an action contract. `ACKNOWLEDGE` applies only to `PENDING_REVIEW`, so it is not
eligible for the Phase 5 `PROCEED` path.

The exact native action entry point is:

```text
blackpod.runtime.operator_inbox_action.record_operator_action
```

Battlestar's decision consumer has no public standalone review-packet builder
and requires a `live_governor_run` manifest. Build Week therefore validates the
current Governor decision, readiness, and deliberation contracts and adapts
their existing `operator_review_packet.v1` fields without pretending a Build
Week REPLAY mission was a live Governor run. All source paths are
mission-relative. The persisted `operator_inbox_action.v1` is the exact native
action payload; Build Week does not add mission, request, decision, or transport
fields under that native schema. Those correlations, plus `observed_at`, are
recorded explicitly in the versioned operator provenance and lineage sidecars.
The native decision-consumer receipt shape is likewise preserved. Its current
ledger event is unversioned, so the artifact and lineage records report a null
schema version instead of claiming a Build Week contract for native data.

Navigator can run only after the stored operator result is exactly
`APPROVED_FOR_HANDOFF`. It invokes these current interfaces separately:

```text
blackpod.runtime.navigator_handoff.stage_navigator_handoff
blackpod.runtime.navigator_intake.accept_handoff_envelope
```

`accept_handoff_envelope` is both the current intake interface and the current
public SHADOW-plan creation entry point. The combined
`navigator_shadow_workflow.run_workflow` is not invoked because operator action
must remain a separately visible mission event.

Navigator mode is always `SHADOW`, regardless of whether the mission transport
is `LIVE` or `REPLAY`. The final approval means only that a validated,
operator-approved decision context completed a non-executing SHADOW handoff
and plan. Its scope is exactly `NAVIGATOR_SHADOW_HANDOFF`.

Allowed operations are exactly:

```text
VALIDATE
PLAN_ONLY
```

Prohibited operations are exactly:

```text
SUBMIT_ORDER
CANCEL_ORDER
MODIFY_PORTFOLIO
BROKER_CALL
```

No `ExecutionIntent`, broker client, order, position, or portfolio interface is
imported or invoked.

### Explicit commands

Record approval, then run Navigator as a separate command:

```bash
.venv/bin/python3.11 -m blackpod_build_week.harbormaster operator-action \
  --mission-id <mission-id> \
  --action APPROVE_HANDOFF \
  --operator-id <operator-id> \
  --reason "Approved for Navigator SHADOW planning." \
  --expires-in-minutes 30 \
  --artifacts-root artifacts
.venv/bin/python3.11 -m blackpod_build_week.harbormaster run-navigator \
  --mission-id <mission-id> \
  --artifacts-root artifacts
```

LIVE uses the same current operator and Navigator Python interfaces against
the current mission artifacts and never performs market acquisition in Phase
5. A LIVE `APPROVE_HANDOFF` requires a positive `--expires-in-minutes`; a
REPLAY approval takes its deterministic expiry from the fixture. LIVE rejects
replay fixtures. REPLAY requires the committed deterministic fixture for each
command and never falls back to LIVE. Expiry in REPLAY is evaluated against
the fixture's deterministic observed time, while LIVE uses the current UTC
clock.

### Deterministic Stage 1 replays

Each scenario starts from the same deterministic PROCEED mission in a different
unused artifact root. From the repository root, the following block is an exact
three-scenario verification sequence:

```bash
export BATTLESTAR_PATH=../../BlackPod-Versions/blackpod_battlestar

phase5_prepare_proceed() {
  local phase5_artifacts_root="$1"
  .venv/bin/python3.11 -m blackpod_build_week.harbormaster \
    --request examples/mission_request.replay.json \
    --artifacts-root "$phase5_artifacts_root"
  .venv/bin/python3.11 -m blackpod_build_week.harbormaster run-oracle \
    --mission-id mission-buildweek-replay-001 \
    --artifacts-root "$phase5_artifacts_root" \
    --replay-fixture fixtures/oracle_replay_quotes.v1.json
  .venv/bin/python3.11 -m blackpod_build_week.harbormaster run-council \
    --mission-id mission-buildweek-replay-001 \
    --artifacts-root "$phase5_artifacts_root" \
    --replay-fixture fixtures/council_replay_policy.v1.json
  .venv/bin/python3.11 -m blackpod_build_week.harbormaster run-governor \
    --mission-id mission-buildweek-replay-001 \
    --artifacts-root "$phase5_artifacts_root" \
    --replay-fixture fixtures/governor_replay_context.proceed.v1.json
}

# A. Approved SHADOW mission (all commands exit 0).
phase5_prepare_proceed artifacts/phase5-demo-approved
.venv/bin/python3.11 -m blackpod_build_week.harbormaster operator-action \
  --mission-id mission-buildweek-replay-001 \
  --action APPROVE_HANDOFF \
  --operator-id demo-operator \
  --reason "Approved for deterministic Navigator SHADOW planning." \
  --artifacts-root artifacts/phase5-demo-approved \
  --replay-fixture fixtures/operator_replay_action.approve.v1.json
.venv/bin/python3.11 -m blackpod_build_week.harbormaster run-navigator \
  --mission-id mission-buildweek-replay-001 \
  --artifacts-root artifacts/phase5-demo-approved \
  --replay-fixture fixtures/navigator_replay.shadow.v1.json

# B. Operator rejection (the action exits 0 and Navigator remains NOT_STARTED).
phase5_prepare_proceed artifacts/phase5-demo-rejected
.venv/bin/python3.11 -m blackpod_build_week.harbormaster operator-action \
  --mission-id mission-buildweek-replay-001 \
  --action REJECT \
  --operator-id demo-operator \
  --reason "Rejected at the deterministic operator gate." \
  --artifacts-root artifacts/phase5-demo-rejected \
  --replay-fixture fixtures/operator_replay_action.reject.v1.json

# C. Controlled Navigator intake failure (the final command exits 9).
phase5_prepare_proceed artifacts/phase5-demo-navigator-failure
.venv/bin/python3.11 -m blackpod_build_week.harbormaster operator-action \
  --mission-id mission-buildweek-replay-001 \
  --action APPROVE_HANDOFF \
  --operator-id demo-operator \
  --reason "Approved for deterministic Navigator SHADOW planning." \
  --artifacts-root artifacts/phase5-demo-navigator-failure \
  --replay-fixture fixtures/operator_replay_action.approve.v1.json
.venv/bin/python3.11 -m blackpod_build_week.harbormaster run-navigator \
  --mission-id mission-buildweek-replay-001 \
  --artifacts-root artifacts/phase5-demo-navigator-failure \
  --replay-fixture fixtures/navigator_replay.intake-failure.v1.json
```

The controlled failure fixture does not contain a final snapshot or plan. It
stages through the native handoff interface with a replay-only unsupported
schema injection, then exercises the actual native intake rejection path. LIVE
cannot enable this seam. The command exits nonzero, records Navigator
`FAILED`, and creates no plan.

### Phase 5 restart and idempotency

Revisions 8 and 9 record the operator action beginning and result. Revisions
10 and 11 record Navigator beginning and completion or technical failure.
Repeating an identical completed approval or successful Navigator command
returns an explicit no-op and writes no new artifact or snapshot. A conflicting
second operator action, an interrupted `RUNNING` state, or a prior technical
`FAILED` state is an explicit conflict. Immutable artifacts and revision files
are never overwritten; there is no force or repair mode. If interruption leaves
only a staged handoff or an accepted intake artifact beneath a `RUNNING`
Navigator attempt, restart also fails explicitly: Phase 5 preserves those
partial immutable records but does not infer completion, overwrite them, or
silently resume past the operator gate.

## Mission directory

After the deterministic approved Phase 5 example, the mission layout is:

```text
artifacts/phase5-demo-approved/
└── missions/
    └── mission-buildweek-replay-001/
        ├── mission_snapshot.json
        ├── request/
        │   └── mission_request.json
        ├── snapshots/
        │   ├── mission_snapshot-r0001.json
        │   ├── mission_snapshot-r0002.json
        │   ├── mission_snapshot-r0003.json
        │   ├── mission_snapshot-r0004.json
        │   ├── mission_snapshot-r0005.json
        │   ├── mission_snapshot-r0006.json
        │   ├── mission_snapshot-r0007.json
        │   ├── mission_snapshot-r0008.json
        │   ├── mission_snapshot-r0009.json
        │   ├── mission_snapshot-r0010.json
        │   └── mission_snapshot-r0011.json
        ├── oracle/
        │   ├── inputs/
        │   │   ├── oracle_replay_input.json
        │   │   └── oracles_vapors.example.yaml
        │   └── attempt-0001/
        │       ├── fleet-oracles-vapors-example_snapshot.json
        │       ├── oracle_report_live.json
        │       ├── oracle_pipeline_run_manifest.json
        │       └── ... other native Oracle artifacts
        ├── council/
        │   ├── inputs/
        │   │   └── council_supporting_input.json
        │   └── attempt-0001/
        │       ├── mandate_policy.json
        │       ├── trading_candidate_report.json
        │       ├── senate_review_packet.json
        │       ├── senate_deliberation.json
        │       ├── council_input_packet.json
        │       ├── council_advisor_runtime_config.json
        │       ├── council_advisor_runtime_validation.json
        │       ├── advisor_health_summary.json
        │       ├── council_synthesis.json
        │       ├── council_executive_summary.json
        │       ├── council_provenance.json
        │       └── council_lineage_manifest.json
        ├── governor/
        │   ├── inputs/
        │   │   └── governor_supporting_context.json
        │   └── attempt-0001/
        │       ├── governor_input_context.json
        │       ├── governor_senate_intake.json
        │       ├── governor_deliberation_prep.json
        │       ├── governor_deliberation.json
        │       ├── governor_decision_readiness.json
        │       ├── governor_decision.json
        │       ├── governor_rendered_decision.json
        │       ├── secretary_outcome_summary.json
        │       ├── warning_classification.json
        │       ├── governor_provenance.json
        │       └── lineage_manifest.json
        ├── operator/
        │   ├── inputs/
        │   │   └── operator_replay_action.json
        │   └── attempt-0001/
        │       ├── review_packet.json
        │       ├── operator_action.json
        │       ├── operator_receipt.json
        │       ├── operator_ledger_entry.json
        │       ├── operator_provenance.json
        │       └── lineage_manifest.json
        └── navigator/
            ├── inputs/
            │   └── navigator_replay.json
            └── attempt-0001/
                ├── handoff/
                │   ├── pending/<handoff-id>.json
                │   ├── staging_receipts/<handoff-id>.json
                │   └── handoff_ledger.jsonl
                ├── intake/
                │   ├── intake_receipts/<handoff-id>.json
                │   ├── shadow_plans/<handoff-id>.json
                │   └── navigator_ledger.jsonl
                ├── navigator_provenance.json
                └── lineage_manifest.json
```

The request, immutable snapshots, captured inputs, Oracle outputs, Council
outputs, Governor outputs, operator records, and Navigator outputs are never
overwritten. `mission_snapshot.json`
is written via a same-directory temporary file followed by atomic replace.
Every artifact record contains a
mission-relative path, producer, SHA-256 digest, byte size, observed timestamp,
and a schema or contract version when available. All paths are containment
checked beneath the mission root.

## Stage 2, Phase 1: ModelDock Oracle narrative enrichment

ModelDock is the local LLM appliance for one bounded task: turning validated
Oracle evidence into a concise, structured explanation. Oracle runs and
materializes its typed analysis first. The `enrich-oracle` command then builds a
versioned request from an explicit projection of those recorded artifacts,
validates ModelDock's structured response, and attaches the narrative and call
provenance to the Oracle stage. It never overwrites the original Oracle report
or changes Oracle's native readiness state.

The authority boundary is strict:

- Oracle remains authoritative for measurements, market facts, diagnostics,
  readiness evidence, warnings, and typed analytical conclusions.
- ModelDock may distinguish observed facts from interpretation, explain
  uncertainty, and summarize the already validated evidence.
- ModelDock cannot fill in missing market facts, add unsupported numerical
  claims, produce a Governor disposition, approve a mission, recommend an
  order, or authorize execution.
- The enrichment path does not call Council, Governor, operator, Navigator,
  ModelDock-external providers, or any broker or order interface.

Council continues to require the original Oracle fact artifacts. When a
successful ModelDock call is recorded, Council additionally validates and
lineages the narrative as an explicit Oracle input. Battlestar's current native
Council synthesis policy interface has no separate narrative parameter, so the
adapter does not invent one or reinterpret the narrative as a score, vote, or
policy signal.

### Configuration and separate startup

Both of these environment variables are required, including for deterministic
REPLAY, so configuration is always explicit:

```bash
export MODELDOCK_BASE_URL=http://127.0.0.1:8000
export MODELDOCK_TIMEOUT_SECONDS=30
```

`MODELDOCK_PROFILE` and `MODELDOCK_PROVIDER` are optional policy settings:

```bash
export MODELDOCK_PROFILE=default
export MODELDOCK_PROVIDER=mlx
```

`MODELDOCK_MODEL` is optional for deterministic REPLAY, which performs no
network call. It is deliberately required for LIVE and deep preflight:

```bash
export MODELDOCK_MODEL=gemma-4-e4b-it-4bit
```

The current ModelDock request schema has no provider-selection field. Pinning
a registered model, then verifying through `/models` that it maps to `mlx`
with text capability, is therefore the only supported pre-dispatch guarantee
that Oracle evidence cannot be routed to another configured provider.

`MODELDOCK_BASE_URL` must be a loopback HTTP(S) origin with no credentials,
path, query, or fragment. Stage 2 LIVE accepts only the local `mlx` provider.
The timeout must be a finite positive value no greater than 300 seconds. A
configured model is a registry name, not an absolute filesystem path.

Build Week does not start ModelDock. In a separate terminal and the separately
managed, read-only sibling ModelDock checkout, use ModelDock's documented
startup command:

```bash
python -m src.server
```

Starting, configuring, and provisioning the ModelDock runtime remain outside
this repository. Do not point the Build Week client at a remote host.

### Deep preflight

Preflight checks `/health` and `/models`, then performs a real structured
`POST /text/generate` smoke inference. A shallow health response alone never
counts as inference readiness, and a mocked smoke response fails LIVE
readiness.

```bash
export MODELDOCK_BASE_URL=http://127.0.0.1:8000
export MODELDOCK_TIMEOUT_SECONDS=30
export MODELDOCK_MODEL=gemma-4-e4b-it-4bit
.venv/bin/python3.11 -m blackpod_build_week.harbormaster modeldock-preflight
```

The report includes the configured origin and timeout, health and endpoint
state, selected provider/model, mocked state, trace ID, and latency. The smoke
call must be non-mocked MLX inference for the command to report ready.

### LIVE and REPLAY behavior

LIVE first performs a metadata-only `GET /models` route check, then sends one
strictly validated request to `POST /text/generate`. No Oracle facts are sent
until the explicitly configured model is proven to be a registered MLX text
model. The generation response requires
HTTP `200`, envelope status `ok`, request type `text.generate`, provider `mlx`,
`mocked: false`, matching mission/request correlation, and nonempty structured
JSON content conforming to `blackpod.oracle_narrative.v1`. The client enforces
the configured deadline and a one-MiB response limit. It rejects malformed or
truncated JSON, unsupported schemas, missing fields, provider substitution,
correlation mismatches, numeric facts absent from the Oracle input, and claims
of approval or execution authority. There is no retry through another provider
and no LIVE-to-REPLAY fallback.

ModelDock may report either native text engine supported by its current MLX
provider: `mlx-lm`, or `mlx-vlm` when a Gemma/multimodal model is deliberately
routed through the VLM runtime for text generation. Engine acceptance does not
relax the LIVE checks: the provider must still be `mlx`, the response must be
non-mocked, and the real MLX completion and token metadata must validate.

REPLAY uses the committed request/response pack and performs no network call.
It exercises the same request construction, response-envelope parsing,
narrative validation, correlation checks, hashing, provenance, artifact
capture, and snapshot transitions as LIVE. It does not load a precomputed
mission snapshot and never falls back to LIVE.

ModelDock narrative is required under the Stage 2 strict policy. An unavailable
service, timeout, non-`200` response, mocked LIVE output, malformed envelope,
or invalid narrative is a technical failure. Build Week preserves every valid
Oracle artifact, writes a new immutable failure snapshot with a sanitized
ModelDock issue, marks the strict enrichment attempt failed, and exits nonzero.
It never silently degrades to an unvalidated or missing narrative.

### Deterministic replay verification

Use a new artifact root and run exactly:

```bash
export BATTLESTAR_PATH=../../BlackPod-Versions/blackpod_battlestar
export MODELDOCK_BASE_URL=http://127.0.0.1:8000
export MODELDOCK_TIMEOUT_SECONDS=30
export MODELDOCK_PROFILE=default
export MODELDOCK_PROVIDER=mlx
unset MODELDOCK_MODEL
.venv/bin/python3.11 -m blackpod_build_week.harbormaster \
  --request examples/mission_request.replay.json \
  --artifacts-root artifacts/stage2-phase1-modeldock-replay
.venv/bin/python3.11 -m blackpod_build_week.harbormaster run-oracle \
  --mission-id mission-buildweek-replay-001 \
  --artifacts-root artifacts/stage2-phase1-modeldock-replay \
  --replay-fixture fixtures/oracle_replay_quotes.v1.json
.venv/bin/python3.11 -m blackpod_build_week.harbormaster enrich-oracle \
  --mission-id mission-buildweek-replay-001 \
  --artifacts-root artifacts/stage2-phase1-modeldock-replay \
  --replay-fixture fixtures/modeldock_oracle_narrative.replay.v1.json
```

The replay pack contains the selected Oracle input, exact ModelDock request and
response envelopes, expected narrative, expected provider/model/trace
provenance identity, and expected snapshot changes. It is evidence for
validation, not a final mission snapshot.
A successful enrichment leaves Oracle `SUCCEEDED`, the mission in `COUNCIL`
phase with outcome `INCOMPLETE`, and records the ModelDock call as `SUCCEEDED`.

### Optional real local canary

The canary is explicitly LIVE. Start ModelDock separately, run deep preflight,
and use a new artifact root. This sequence also runs Battlestar's LIVE Oracle
acquisition path, so its optional LIVE dependencies and market provider/network
access must be available:

```bash
export BATTLESTAR_PATH=../../BlackPod-Versions/blackpod_battlestar
export MODELDOCK_BASE_URL=http://127.0.0.1:8000
export MODELDOCK_TIMEOUT_SECONDS=30
export MODELDOCK_PROVIDER=mlx
export MODELDOCK_MODEL=gemma-4-e4b-it-4bit
.venv/bin/python3.11 -m blackpod_build_week.harbormaster modeldock-preflight
.venv/bin/python3.11 -m blackpod_build_week.harbormaster \
  --request examples/mission_request.live.json \
  --artifacts-root artifacts/stage2-phase1-modeldock-live-canary
.venv/bin/python3.11 -m blackpod_build_week.harbormaster run-oracle \
  --mission-id mission-live-064ef6b3f2d8a73dc4ec2b36 \
  --artifacts-root artifacts/stage2-phase1-modeldock-live-canary
.venv/bin/python3.11 -m blackpod_build_week.harbormaster enrich-oracle \
  --mission-id mission-live-064ef6b3f2d8a73dc4ec2b36 \
  --artifacts-root artifacts/stage2-phase1-modeldock-live-canary
```

The final command prints the provider, model, trace ID, latency, narrative path,
mission phase/outcome, and current snapshot path. It rejects mocked output and
never calls a broker or external execution API.

### Stage 2 artifacts and snapshots

The enrichment output is contained beneath the existing Oracle directory:

```text
artifacts/stage2-phase1-modeldock-replay/
└── missions/
    └── mission-buildweek-replay-001/
        ├── mission_snapshot.json
        ├── snapshots/
        │   ├── mission_snapshot-r0001.json
        │   ├── mission_snapshot-r0002.json
        │   ├── mission_snapshot-r0003.json
        │   ├── mission_snapshot-r0004.json
        │   └── mission_snapshot-r0005.json
        └── oracle/
            ├── attempt-0001/
            │   └── ... original Oracle artifacts remain unchanged
            └── modeldock/
                ├── request.json
                ├── response.json
                ├── oracle_narrative.json
                └── provenance.json
```

Every ModelDock artifact is immutable, containment-checked, hashed with
SHA-256, sized, timestamped, correlated to the mission and request, and listed
with its schema or contract version. The canonical snapshot stores only
mission-relative paths. The response artifact is a safe validated projection:
authorization headers, credentials, secrets, and absolute local model paths
are never persisted. A model revision is recorded only when it can be derived
without exposing a local path.

### Security and privacy boundary

`oracle/modeldock/request.json` contains the exact narrative instruction and
the deliberately selected Oracle evidence and correlation identifiers sent to
the local appliance. Treat the mission artifact root as sensitive mission data
even though the request excludes arbitrary filesystem content, absolute paths,
credentials, authorization headers, and secrets. The client accepts only a
loopback origin, verifies the explicitly selected model's MLX route before
sending LIVE evidence, and persists only a validated, path-sanitized response
projection. `MODELDOCK_PROVIDER` is an acceptance policy for that verified
route and response; it is not a provider selector in ModelDock's request
schema.

ModelDock output remains explanatory data. It cannot approve a mission, change
Oracle facts or readiness, issue a Governor disposition, recommend an order,
or authorize or execute any trade.

When enrichment immediately follows Oracle, revision 4 records the enrichment
attempt running and revision 5 records success or strict failure. Repeating an
identical completed command validates the stored request, call provenance,
artifacts, and snapshot state, then returns an explicit no-op without writing a
new revision. An existing `RUNNING` or `FAILED` enrichment is an explicit
one-attempt conflict. There is no force, overwrite, silent resume, alternate
provider retry, or transport fallback.

Run the complete test suite, which uses injected transports and does not
require a running ModelDock service:

```bash
.venv/bin/python3.11 -m unittest discover -s tests -v
```

## Stage 2, Phase 2: unified mission orchestration

The `mission-run` command is the canonical one-command path through the
capabilities implemented in Stages 1 and 2. It initializes a mission and calls
the existing Oracle, ModelDock-enrichment, Council, Governor, operator, and
Navigator workflow functions in order. It does not duplicate their analysis,
policy, validation, transition, or artifact logic.

Every stage-level command remains available for focused operation and
diagnosis:

```text
run-oracle
enrich-oracle
run-council
run-governor
operator-action
run-navigator
```

Use `mission-run` for a new canonical mission and `mission-resume` for an
existing mission. Both unified commands validate the full immutable snapshot
chain and all referenced artifact hashes before deciding what, if anything,
can run next. A resume skips completed stages; it never calls an earlier stage
again merely to reconstruct state.

### Unified command boundary

A new mission has this shape:

```bash
.venv/bin/python3.11 -m blackpod_build_week.harbormaster mission-run \
  --request <mission-request.json> \
  --artifacts-root <artifact-root> \
  --with-modeldock \
  --through NAVIGATOR \
  --operator-action APPROVE_HANDOFF \
  --operator-id <operator-id> \
  --operator-reason "Approved for Navigator SHADOW planning." \
  <transport-specific inputs>
```

The ModelDock choice is always explicit and mutually exclusive:

- `--with-modeldock` runs strict Oracle narrative enrichment between Oracle
  and Council. An enabled enrichment is required to succeed; it is never
  silently skipped.
- `--without-modeldock` deliberately continues with Oracle's original typed
  facts and no ModelDock call. It is an explicit orchestration choice, not a
  fallback after an enrichment failure.

Unified exit behavior is stable: `0` means a valid completed mission or an
intentional resumable stop; `2` means an invalid invocation or input contract;
`4` means stored mission integrity or persistence failed; and `11` means a
technical workflow or canonical state failure. A controlled `FAILED` mission
therefore writes its canonical failure state and returns `11`.

The inclusive stop target must be one of:

| Option | Last eligible operation | Typical state after a successful stop |
| --- | --- | --- |
| `--through ORACLE` | Oracle and enabled ModelDock enrichment | `COUNCIL` / `INCOMPLETE` |
| `--through COUNCIL` | Council synthesis and executive summary | `GOVERNOR` / `INCOMPLETE` |
| `--through GOVERNOR` | Governor rendered decision | disposition-dependent |
| `--through OPERATOR` | Explicit operator action, when eligible | `NAVIGATOR` / `HELD`, or terminal `VETOED` |
| `--through NAVIGATOR` | Authorized SHADOW intake and plan | terminal `APPROVED`, or an earlier policy outcome |

Stopping never creates a fabricated stage transition. For example, stopping
after Governor `PROCEED` leaves the mission `HELD` at
`PENDING_APPROVAL`; it does not record an operator action. Stopping after
Council leaves the canonical outcome `INCOMPLETE`. Both are resumable.

Commands targeting `OPERATOR` or `NAVIGATOR` require the action, identity, and
reason up front, before any stage advances. Those controls are invoked only if
Governor returns `PROCEED`; the only supported recorded actions remain
`APPROVE_HANDOFF` and `REJECT`. There is no invented `LEAVE_PENDING` action:
use `--through GOVERNOR` to stop safely at pending approval. If Governor
returns `HOLD`, `REVIEW_REQUIRED`, `BLOCKED`, or `STAND_DOWN`, the unified
workflow ignores the configured future action and does not invoke operator or
Navigator.

Common controls are forwarded to the existing stage workflows:

- `--deadline-seconds <seconds>` sets the existing process-boundary deadline;
- `--strict-battlestar-clean` rejects a dirty Battlestar worktree; and
- LIVE approval uses `--expires-in-minutes <positive-minutes>`.

### Deterministic one-command replay

The existing replay fixtures are sufficient for every canonical outcome. They
remain stage inputs, not precomputed stage results or mission snapshots. Each
example below must use its own unused artifact root.

Set the common read-only sibling and local ModelDock configuration first:

```bash
export BATTLESTAR_PATH=../../BlackPod-Versions/blackpod_battlestar
export MODELDOCK_BASE_URL=http://127.0.0.1:8000
export MODELDOCK_TIMEOUT_SECONDS=30
export MODELDOCK_PROFILE=default
export MODELDOCK_PROVIDER=mlx
unset MODELDOCK_MODEL
```

Approved SHADOW mission (`APPROVED`, 13 immutable snapshots):

```bash
.venv/bin/python3.11 -m blackpod_build_week.harbormaster mission-run \
  --request examples/mission_request.replay.json \
  --artifacts-root artifacts/stage2-phase2-approved \
  --with-modeldock \
  --through NAVIGATOR \
  --operator-action APPROVE_HANDOFF \
  --operator-id demo-operator \
  --operator-reason "Approved for deterministic Navigator SHADOW planning." \
  --oracle-replay-fixture fixtures/oracle_replay_quotes.v1.json \
  --modeldock-replay-fixture fixtures/modeldock_oracle_narrative.replay.v1.json \
  --council-replay-fixture fixtures/council_replay_policy.v1.json \
  --governor-replay-fixture fixtures/governor_replay_context.proceed.v1.json \
  --operator-replay-fixture fixtures/operator_replay_action.approve.v1.json \
  --navigator-replay-fixture fixtures/navigator_replay.shadow.v1.json
```

Held at pending operator review (`HELD`, 9 immutable snapshots):

```bash
.venv/bin/python3.11 -m blackpod_build_week.harbormaster mission-run \
  --request examples/mission_request.replay.json \
  --artifacts-root artifacts/stage2-phase2-held \
  --with-modeldock \
  --through GOVERNOR \
  --oracle-replay-fixture fixtures/oracle_replay_quotes.v1.json \
  --modeldock-replay-fixture fixtures/modeldock_oracle_narrative.replay.v1.json \
  --council-replay-fixture fixtures/council_replay_policy.v1.json \
  --governor-replay-fixture fixtures/governor_replay_context.proceed.v1.json
```

This deliberately stops after `PROCEED`. The operator route is
`PENDING_APPROVAL`, Navigator remains `NOT_STARTED`, and Governor has not
approved a trade.

Operator rejection (`VETOED`, 11 immutable snapshots):

```bash
.venv/bin/python3.11 -m blackpod_build_week.harbormaster mission-run \
  --request examples/mission_request.replay.json \
  --artifacts-root artifacts/stage2-phase2-vetoed \
  --with-modeldock \
  --through OPERATOR \
  --operator-action REJECT \
  --operator-id demo-operator \
  --operator-reason "Rejected at the deterministic operator gate." \
  --oracle-replay-fixture fixtures/oracle_replay_quotes.v1.json \
  --modeldock-replay-fixture fixtures/modeldock_oracle_narrative.replay.v1.json \
  --council-replay-fixture fixtures/council_replay_policy.v1.json \
  --governor-replay-fixture fixtures/governor_replay_context.proceed.v1.json \
  --operator-replay-fixture fixtures/operator_replay_action.reject.v1.json
```

Controlled Navigator intake failure (`FAILED`, 13 immutable snapshots; the
command exits nonzero):

```bash
.venv/bin/python3.11 -m blackpod_build_week.harbormaster mission-run \
  --request examples/mission_request.replay.json \
  --artifacts-root artifacts/stage2-phase2-failed \
  --with-modeldock \
  --through NAVIGATOR \
  --operator-action APPROVE_HANDOFF \
  --operator-id demo-operator \
  --operator-reason "Approved for deterministic Navigator SHADOW planning." \
  --oracle-replay-fixture fixtures/oracle_replay_quotes.v1.json \
  --modeldock-replay-fixture fixtures/modeldock_oracle_narrative.replay.v1.json \
  --council-replay-fixture fixtures/council_replay_policy.v1.json \
  --governor-replay-fixture fixtures/governor_replay_context.proceed.v1.json \
  --operator-replay-fixture fixtures/operator_replay_action.approve.v1.json \
  --navigator-replay-fixture fixtures/navigator_replay.intake-failure.v1.json
```

Deliberately incomplete after Oracle and enabled enrichment (`INCOMPLETE`, 5
immutable snapshots):

```bash
.venv/bin/python3.11 -m blackpod_build_week.harbormaster mission-run \
  --request examples/mission_request.replay.json \
  --artifacts-root artifacts/stage2-phase2-incomplete \
  --with-modeldock \
  --through ORACLE \
  --oracle-replay-fixture fixtures/oracle_replay_quotes.v1.json \
  --modeldock-replay-fixture fixtures/modeldock_oracle_narrative.replay.v1.json
```

These paths demonstrate the existing canonical derivation rules:

| Outcome | Canonical cause |
| --- | --- |
| `APPROVED` | Explicit approval followed by a validated Navigator SHADOW plan |
| `HELD` | Review remains open, including `PROCEED` before operator approval |
| `VETOED` | Governor `STAND_DOWN` or explicit operator rejection |
| `FAILED` | A technical, schema, integrity, expiry, or correlation failure |
| `INCOMPLETE` | The mission intentionally stops before a decision outcome |

### Explicit ModelDock-disabled replay

The complete Stage 1 path also remains available without narrative enrichment.
No ModelDock environment variables or fixture are needed, and no ModelDock
configuration, preflight, client, or network operation is invoked:

```bash
export BATTLESTAR_PATH=../../BlackPod-Versions/blackpod_battlestar
.venv/bin/python3.11 -m blackpod_build_week.harbormaster mission-run \
  --request examples/mission_request.replay.json \
  --artifacts-root artifacts/stage2-phase2-approved-without-modeldock \
  --without-modeldock \
  --through NAVIGATOR \
  --operator-action APPROVE_HANDOFF \
  --operator-id demo-operator \
  --operator-reason "Approved for deterministic Navigator SHADOW planning." \
  --oracle-replay-fixture fixtures/oracle_replay_quotes.v1.json \
  --council-replay-fixture fixtures/council_replay_policy.v1.json \
  --governor-replay-fixture fixtures/governor_replay_context.proceed.v1.json \
  --operator-replay-fixture fixtures/operator_replay_action.approve.v1.json \
  --navigator-replay-fixture fixtures/navigator_replay.shadow.v1.json
```

This successful path has 11 immutable snapshots. Council consumes the same
authoritative Oracle fact artifacts without an `oracle_modeldock_narrative`
input.

### Stop and resume

`mission-resume` loads the stored request and current canonical snapshot by
mission ID. It validates the complete hash chain and referenced artifacts,
then continues from the first eligible incomplete stage. Supply the intended
inclusive target and the explicit ModelDock mode again. Replay fixture inputs
remain explicit so completed operation identity and all remaining transports
can be checked.

Stop after Council:

```bash
.venv/bin/python3.11 -m blackpod_build_week.harbormaster mission-run \
  --request examples/mission_request.replay.json \
  --artifacts-root artifacts/stage2-phase2-resume-demo \
  --with-modeldock \
  --through COUNCIL \
  --oracle-replay-fixture fixtures/oracle_replay_quotes.v1.json \
  --modeldock-replay-fixture fixtures/modeldock_oracle_narrative.replay.v1.json \
  --council-replay-fixture fixtures/council_replay_policy.v1.json
```

Resume at Governor and finish through Navigator:

```bash
.venv/bin/python3.11 -m blackpod_build_week.harbormaster mission-resume \
  --mission-id mission-buildweek-replay-001 \
  --artifacts-root artifacts/stage2-phase2-resume-demo \
  --with-modeldock \
  --through NAVIGATOR \
  --operator-action APPROVE_HANDOFF \
  --operator-id demo-operator \
  --operator-reason "Approved for deterministic Navigator SHADOW planning." \
  --oracle-replay-fixture fixtures/oracle_replay_quotes.v1.json \
  --modeldock-replay-fixture fixtures/modeldock_oracle_narrative.replay.v1.json \
  --council-replay-fixture fixtures/council_replay_policy.v1.json \
  --governor-replay-fixture fixtures/governor_replay_context.proceed.v1.json \
  --operator-replay-fixture fixtures/operator_replay_action.approve.v1.json \
  --navigator-replay-fixture fixtures/navigator_replay.shadow.v1.json
```

The second command starts with Governor; it does not rewrite or re-execute
Oracle, ModelDock, or Council. Repeating an identical completed `mission-run`
or `mission-resume` is an explicit no-op. A conflicting operator action, an
interrupted or previously failed one-attempt stage, an inconsistent ModelDock
choice, a corrupted artifact, or a broken snapshot chain fails explicitly.
Presentation projections are left byte-for-byte unchanged for an identical
no-op.

### Captain's Log and mission summary

Every unified run that leaves a valid canonical snapshot, including a
controlled technical failure or deliberate stop, writes four deterministic,
presentation-oriented projections:

```text
artifacts/missions/<mission-id>/presentation/
├── captains_log.json
├── captains_log.md
├── mission_summary.json
└── mission_brief.html
```

The Captain's Log contains only events proven by canonical snapshots and
artifacts: mission acceptance, Oracle result, ModelDock narrative status,
Council state, Governor disposition, operator action, Navigator result, and
the current outcome. Each entry includes the stage, canonical timestamp,
status, a fixed plain-English summary, and mission-relative source artifact
references. The Markdown file is rendered deterministically from the JSON; no
LLM writes or embellishes either form.

`mission_summary.json` is the future UI contract. It contains the mission ID,
symbol, run mode, all stage states, ModelDock provider/model/trace identity,
Governor disposition, operator result, Navigator SHADOW state, current
outcome, important warnings, snapshot count, and canonical current-snapshot
path.

`mission_brief.html` is a self-contained, script-free reviewer view rendered
only from the validated Captain's Log and mission summary contracts. It is not
canonical evidence and is not added to the snapshot or demo-manifest schemas.

The Captain's Cabin is a separate Vite, React, and TypeScript presentation
renderer anchored to `ui/public/captains-cabin-template.png`. It consumes the
same canonical presentation JSON and does not replace the static mission
brief. The approved development mission is prepared with:

```bash
npm --prefix ui install
make cabin-prepare
make cabin-dev

# Non-interactive verification
make cabin-test
make cabin-build
```

The prepared local data set preserves the mission-relative layout and is
ignored by Git. Its primary inputs are:

- `presentation/mission_summary.json`;
- `presentation/captains_log.json`, with the deterministic Markdown form used
  only as a display fallback;
- `presentation/demo_manifest.json`; and
- `mission_snapshot.json` for correlation and evidence references.

The authority flow is intentionally one-way:

```text
immutable mission snapshots and artifacts
    -> canonical presentation JSON
        -> Python reference renderer -> mission_brief.html
        -> validated TypeScript view model -> Captain's Cabin
```

The TypeScript view model selects, formats, and progressively reveals recorded
values. It does not derive outcomes, reinterpret dispositions, invent missing
analysis, or mutate the source files. See
[Captain's Cabin](docs/CAPTAINS_CABIN.md) for its architecture and known data
gaps.

These files are derived presentation state, not replacements for the immutable
snapshot chain. They are atomically refreshed when a stopped mission advances
and are not rewritten when the derived bytes are identical. Canonical stage
artifacts and immutable snapshot revisions are never overwritten.

### Optional unified LIVE ModelDock canary

Start ModelDock separately, configure a registered local MLX text model, and
run deep preflight first. This exact canary intentionally stops after Oracle
and narrative enrichment, so it needs no Council policy, Governor context, or
operator action:

```bash
export BATTLESTAR_PATH=../../BlackPod-Versions/blackpod_battlestar
export MODELDOCK_BASE_URL=http://127.0.0.1:8000
export MODELDOCK_TIMEOUT_SECONDS=30
export MODELDOCK_PROFILE=default
export MODELDOCK_PROVIDER=mlx
export MODELDOCK_MODEL=gemma-4-e4b-it-4bit
.venv/bin/python3.11 -m blackpod_build_week.harbormaster modeldock-preflight
.venv/bin/python3.11 -m blackpod_build_week.harbormaster mission-run \
  --request examples/mission_request.live.json \
  --artifacts-root artifacts/stage2-phase2-live-modeldock-canary \
  --with-modeldock \
  --through ORACLE
```

LIVE sends Oracle evidence only after deep readiness proves the configured
model is registered for non-mocked local MLX text inference. It never uses a
replay fixture or silently changes transport. A complete LIVE continuation
through Council and Governor additionally requires
`--council-policy-input <path>` and `--governor-context-input <path>`. Crossing
the operator boundary also requires the explicit action, operator identity,
rationale, and `--expires-in-minutes 30`. The same
`--deadline-seconds` and `--strict-battlestar-clean` controls are available.

### Unified SHADOW-only safety boundary

The unified command does not weaken any Stage 1 gate. Governor `PROCEED` is
still only a route to operator review. `APPROVED` is produced only after an
explicit `APPROVE_HANDOFF`, accepted Navigator intake, and creation of a
SHADOW plan. Its scope remains exactly `NAVIGATOR_SHADOW_HANDOFF`.

Allowed Navigator operations remain exactly `VALIDATE` and `PLAN_ONLY`.
`SUBMIT_ORDER`, `CANCEL_ORDER`, `MODIFY_PORTFOLIO`, and `BROKER_CALL` remain
prohibited. The unified orchestration imports or invokes no broker client,
order API, portfolio mutation, ModelDock-external provider, or execution path.

Run the complete suite with no live market, ModelDock, or broker dependency:

```bash
.venv/bin/python3.11 -m unittest discover -s tests -v
```

## Known limitations

- Oracle runs Battlestar's complete fixed 21-symbol example fleet. The mission
  request `symbol` is correlation only; Phase 2 does not add symbol filtering.
- The REPLAY seam replaces acquisition data but intentionally exercises the
  same native parsing, validation, report generation, artifact capture, and
  snapshot transitions as LIVE.
- Battlestar names some native output files with a `_live` suffix even during
  deterministic REPLAY. Build Week preserves those native names as provenance.
- The deadline is enforced at the adapter process boundary because the native
  Oracle API does not expose an internal timeout.
- Importing the supported Oracle entry point causes Battlestar's package to
  eagerly import legacy contract definitions. These imports are isolated in
  the child process; the adapter does not use or invoke Governor or Navigator.
- Phase 3 reuses Oracle's normalized 21-symbol ETF/index fleet as candidate
  input because the native candidate contract accepts it. Battlestar's
  runbooks normally use a separate trading fleet; adding a second acquisition
  path is outside this phase.
- Modern `SenateDeliberation` evidence is included in the native Council input
  packet and lineage, but the current synthesis opportunity posture reads only
  the legacy `SenateDecision` CSV contract. No native conversion exists.
  Phase 3 does not invent a direction/confidence mapping, so the native
  synthesis can honestly report `NO_OPPORTUNITY_SIGNAL`. Legacy Senate CSV and
  precomputed Council JSON examples remain reference-only.
- Council advisor health is computed from an adapter-generated, explicit
  manifest over the current mission's Oracle, Mandate, candidate, and Senate
  evidence. The native validation evidence and health summary are immutable,
  hashed, and lineaged; path-only fields are adapted to mission-relative
  values before materialization.
- Executive-summary history/evolution/narrative inputs are optional in the
  native interface and are not fabricated. Phase 3 builds the summary from the
  current synthesis, leaving those native IDs as `missing`.
- The process-boundary deadline remains necessary because the native Council
  interfaces expose no internal timeout.
- Governor warning classification delegates to Battlestar's existing private
  `oracle_measurement_diagnostics._is_diagnostic_warning` seam. Routine,
  non-degrading warnings are retained separately in
  `warning_classification.json` and the rendered decision instead of becoming
  failures. If that native classifier is unavailable, Phase 4 fails explicitly
  rather than inventing a replacement policy.
- Battlestar's current builders render `STAND_DOWN` from an `INVALID`
  deliberation/readiness state, but expose no direct deterministic input seam
  that produces `INVALID` after normal preparation. The committed STAND_DOWN
  replay therefore runs the native preparation chain, applies the narrow
  replay-only `INVALID_STAND_DOWN` contract-validation seam, and then invokes
  the current readiness and decision-rendering interfaces. LIVE rejects this
  seam; it is not a precomputed Governor decision.
- The Governor deadline is enforced at the adapter process boundary because
  the native interfaces expose no internal timeout.
- Battlestar's current Governor consumer exposes no public standalone review
  packet builder and accepts only a `live_governor_run` directory. Phase 5
  therefore adapts the already validated current Governor contracts into the
  existing packet/hash shape and records the mismatch in provenance instead
  of fabricating a live-run manifest.
- The current public Navigator intake call also creates the SHADOW plan; Phase
  5 still records handoff staging, intake acceptance, and plan creation as
  distinct native states and artifacts. That native contract has no separate
  intake-receipt ID or idempotency-key field, so Build Week derives stable
  values from the validated handoff correlation and records that derivation in
  Navigator provenance rather than changing the native receipt.
- Native operator IDs are local audit identities, not cryptographic
  authentication. The Build Week spine proves an explicit, correlated action
  was recorded; it does not provide an identity service.
- Stage 1 `APPROVED` is scoped only to `NAVIGATOR_SHADOW_HANDOFF`. It never
  authorizes a trade and cannot be consumed as broker approval.
- Stage 2 enrichment must run after Oracle and before Council. It does not
  retrofit a completed Council, Governor, operator, or Navigator mission.
- ModelDock's response can expose an absolute MLX `model_path`. Build Week does
  not persist that field; it records a safe model identifier and derives a
  revision only when the value can be represented without a local path.
- Battlestar's current Council synthesis signature has no distinct narrative
  argument. Build Week validates and lineages the narrative alongside the
  original Oracle artifacts but does not alter the native policy interface.
- ModelDock lifecycle and model provisioning remain external. The normal test
  suite and deterministic replay need no running appliance; deep preflight and
  the optional LIVE canary do.
- Structural, correlation, numeric-source, authority-language, and bounded
  vocabulary checks materially constrain narrative output, but no local
  validator can prove every qualitative sentence is semantically entailed.
  Oracle's typed artifacts therefore remain authoritative in every case.
- Operator action, Navigator SHADOW planning, and their immutable audit
  artifacts are included in Phase 5. Stage 2 adds bounded ModelDock narrative
  enrichment, unified orchestration, and deterministic presentation
  projections only. UI, live broker execution, order
  submission/cancellation, portfolio changes, web services, databases,
  queues, daemons, and schedulers remain explicitly absent.
