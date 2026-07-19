# BlackPod Battlestar Build Week

This repository contains the Build Week submission spine. Stage 1, Phase 1 is
limited to Harbormaster mission initialization: it validates a request,
allocates a mission identifier, creates the mission directory, and commits the
first canonical mission snapshot.

Harbormaster currently owns:

- strict validation of `blackpod.mission_request.v1`;
- stable mission identifier allocation;
- the `blackpod.mission_snapshot.v1` Phase 1 state;
- contained, immutable, and hashed mission artifacts;
- atomic publication of the current snapshot.

Harbormaster does **not** yet call Oracle, Council, Governor, Navigator,
ModelDock, market APIs, or any external service. It does not execute orders and
does not provide a web service, database, queue, daemon, scheduler, or UI.

## Python and setup

The package supports Python 3.11 or newer and has no runtime dependencies.

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
```

Run the focused tests:

```bash
python -m unittest discover -s tests -v
```

Initialize the example missions from a clean checkout:

```bash
python -m blackpod_build_week.harbormaster --request examples/mission_request.live.json
python -m blackpod_build_week.harbormaster --request examples/mission_request.replay.json
```

Use `--artifacts-root <path>` to place the `missions/` directory somewhere
other than the default `artifacts/` directory. Repeating an initialization for
the same `mission_id` is intentionally an error; Harbormaster never overwrites
or silently resumes an existing mission.

Initialization is fail-closed. If persistence fails after the mission directory
is reserved, the partial directory is retained for inspection and a retry with
that same `mission_id` is reported as a duplicate rather than overwriting it.

## Request contract

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

## Mission directory

With the default artifacts root, a successful initialization creates:

```text
artifacts/
└── missions/
    └── <mission_id>/
        ├── mission_snapshot.json
        ├── request/
        │   └── mission_request.json
        └── snapshots/
            └── mission_snapshot-r0001.json
```

The request and revision snapshot are written exclusively and never
overwritten. `mission_snapshot.json` is written via a same-directory temporary
file followed by an atomic replace. All artifact references are relative to,
and validated beneath, the mission root.

Revision 1 records a SHA-256 digest of the committed request and has
`previous_snapshot_sha256: null`. Its Phase 1 state is:

- Harbormaster: `SUCCEEDED` with native state `INITIALIZED`;
- Oracle, Council, Governor, and Navigator: `NOT_STARTED`;
- outcome: `INCOMPLETE`;
- current phase: `ORACLE`;
- terminal: `false`.

CLI exit codes are `0` for success, `2` for invalid request/schema/unsafe path,
`3` for duplicate initialization, and `4` for persistence failures.
