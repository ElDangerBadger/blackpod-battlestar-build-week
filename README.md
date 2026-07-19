# BlackPod Battlestar Build Week

This repository contains the Build Week submission spine. Stage 1, Phase 1
initializes a mission through Harbormaster. Stage 1, Phase 2 extends that spine
through the existing Battlestar Oracle and stops with Council as the next
phase.

Harbormaster owns:

- strict validation of `blackpod.mission_request.v1`;
- stable mission identifier allocation;
- canonical `blackpod.mission_snapshot.v1` revisions;
- contained, immutable, hashed mission artifacts and atomic current-snapshot
  publication;
- the Build Week adapter that invokes the sibling Battlestar Oracle; and
- correlation, stage transitions, artifact capture, and Battlestar provenance
  for one Oracle attempt.

Battlestar remains the owner of Oracle acquisition and analysis. The Build
Week adapter does not reproduce calculations or introduce market-analysis
rules. Council, ModelDock, Governor, Navigator, operator UI, and broker
execution are explicitly outside Phase 2. This repository still provides no
web service, database, queue, daemon, scheduler, or UI.

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
export BATTLESTAR_PATH=../blackpod_battlestar
```

Before Oracle runs, preflight verifies that this is a directory, that the
expected Oracle module and fleet configuration exist, and that Git revision
and worktree state can be reported. A dirty worktree is allowed for
development and is recorded clearly.
Use `--strict-battlestar-clean` on `run-oracle` when a dirty checkout must be
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
export BATTLESTAR_PATH=../blackpod_battlestar
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

## Mission directory

After the deterministic Phase 2 example, the mission layout is:

```text
artifacts/phase2-demo/
└── missions/
    └── mission-buildweek-replay-001/
        ├── mission_snapshot.json
        ├── request/
        │   └── mission_request.json
        ├── snapshots/
        │   ├── mission_snapshot-r0001.json
        │   ├── mission_snapshot-r0002.json
        │   └── mission_snapshot-r0003.json
        └── oracle/
            ├── inputs/
            │   ├── oracle_replay_input.json
            │   └── oracles_vapors.example.yaml
            └── attempt-0001/
                ├── fleet-oracles-vapors-example_snapshot.json
                ├── oracle_report_live.json
                ├── oracle_pipeline_run_manifest.json
                └── ... other native Oracle artifacts
```

The request, immutable snapshots, captured inputs, and Oracle outputs are never
overwritten. `mission_snapshot.json` is written via a same-directory temporary
file followed by atomic replace. Every artifact record contains a
mission-relative path, producer, SHA-256 digest, byte size, observed timestamp,
and a schema or contract version when available. All paths are containment
checked beneath the mission root.

## Known Phase 2 limitations

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
- Phase 2 does not wire Council, ModelDock, Governor, Navigator, any UI, or any
  broker/execution path.
