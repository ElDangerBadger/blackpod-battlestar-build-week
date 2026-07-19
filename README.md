# BlackPod Battlestar Build Week

This repository contains the Build Week submission spine. Stage 1, Phase 1
initializes a mission through Harbormaster. Phase 2 runs the existing
Battlestar Oracle. Phase 3 adds Battlestar's existing candidate, Senate,
Council synthesis, and Council executive-summary interfaces. Phase 4 adds the
current Battlestar Governor preparation, deliberation, readiness, and rendered
decision flow, then stops at the rendered disposition and operator placeholder.

Harbormaster owns:

- strict validation of `blackpod.mission_request.v1`;
- stable mission identifier allocation;
- canonical `blackpod.mission_snapshot.v1` revisions;
- contained, immutable, hashed mission artifacts and atomic current-snapshot
  publication;
- the narrow Build Week adapters that invoke the sibling Battlestar Oracle,
  Council evidence chain, and Governor decision flow; and
- correlation, stage transitions, artifact lineage, and Battlestar provenance
  for one immutable attempt per implemented stage.

Battlestar remains the owner of Oracle acquisition, candidate generation,
Senate deliberation, advisor-health validation, Council synthesis, and
executive-summary logic, as well as Governor preparation, deliberation,
readiness, and decision rendering. The Build Week adapters do not reproduce
calculations, introduce voting rules, add risk formulas, or add market-analysis
policy. Operator actions, Navigator, ModelDock, UI, and broker execution are
explicitly outside Phase 4. This repository still provides no web service,
database, queue, daemon, scheduler, or UI.

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
deliberation, readiness, and decision-rendering modules. A dirty worktree is
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

## Mission directory

After the deterministic Phase 4 PROCEED example, the mission layout is:

```text
artifacts/phase4-demo-proceed/
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
        │   └── mission_snapshot-r0007.json
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
        └── governor/
            ├── inputs/
            │   └── governor_supporting_context.json
            └── attempt-0001/
                ├── governor_input_context.json
                ├── governor_senate_intake.json
                ├── governor_deliberation_prep.json
                ├── governor_deliberation.json
                ├── governor_decision_readiness.json
                ├── governor_decision.json
                ├── governor_rendered_decision.json
                ├── secretary_outcome_summary.json
                ├── warning_classification.json
                ├── governor_provenance.json
                └── lineage_manifest.json
```

The request, immutable snapshots, captured inputs, Oracle outputs, Council
outputs, and Governor outputs are never overwritten. `mission_snapshot.json`
is written via a same-directory temporary file followed by atomic replace.
Every artifact record contains a
mission-relative path, producer, SHA-256 digest, byte size, observed timestamp,
and a schema or contract version when available. All paths are containment
checked beneath the mission root.

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
- Phase 4 records Secretary/accountability context and an operator route but
  does not take an operator action. Operator action, Navigator, ModelDock, UI,
  broker execution, web services, databases, queues, daemons, and schedulers
  are not included in Phase 4.
