# Build Week Demo Runbook

This runbook is the operator-facing path for a deterministic Build Week
rehearsal. It uses the committed demo packs and the canonical Harbormaster CLI.
It does not start ModelDock, access a broker, or modify either sibling
repository.

## Prerequisites

- Python 3.11 or newer
- GNU Make or BSD Make
- a local Battlestar checkout that remains read-only during the demo
- this repository checked out at the intended submission revision

Set `BATTLESTAR_PATH` explicitly. There is intentionally no machine-specific
default:

```bash
export BATTLESTAR_PATH=/absolute/path/to/blackpod_battlestar
```

The directory may be dirty for ordinary rehearsal; preflight reports that
state. The demo commands never write into it. ModelDock is not needed for
REPLAY because the committed response is validated without a network call.

## One-time setup

```bash
make setup
make test
```

`make setup` creates `.venv` and installs this repository in editable mode.
The test suite is offline: it does not require market data, a running
ModelDock appliance, or broker credentials.

## Judge path

Run these commands from the repository root:

```bash
make preflight-replay
make validate-demo-packs
make rehearse-approved
```

For the shortest reviewer path, run `make judge`. It performs replay preflight,
runs the approved scenario, and prints the generated `mission_brief.html` path.
The HTML is a non-canonical projection of the existing JSON contracts.

The rehearsal performs the approved deterministic mission, validates its
immutable evidence, and prints the presentation paths. Its safety boundary is
Navigator `SHADOW`; no order or portfolio operation exists.

For a fresh rehearsal, select a new contained output root rather than deleting
prior evidence:

```bash
make rehearse-approved DEMO_ROOT=artifacts/rehearsal-002
```

## Five canonical outcomes

Each target uses a separate mission-store root because the deterministic
request intentionally produces the same stable mission identifier. Existing
completed runs are explicit no-ops; immutable snapshots and stage artifacts
are never overwritten.

| Target | Expected outcome | Expected snapshots | Process result |
| --- | --- | ---: | --- |
| `make demo-approved` | `APPROVED` | 13 | success |
| `make demo-held` | `HELD` | 9 | success |
| `make demo-vetoed` | `VETOED` | 11 | success |
| `make demo-failed` | `FAILED` | 13 | controlled workflow exit `11`, accepted by Make |
| `make demo-incomplete` | `INCOMPLETE` | 5 | deliberate resumable stop |

Run all five:

```bash
make demo-outcomes
```

The separately maintained ModelDock-disabled control uses the same approved
workflow with an explicit flag:

```bash
.venv/bin/python3.11 -m blackpod_build_week.harbormaster \
  demo approved --without-modeldock \
  --artifacts-root artifacts/demo-readiness/without-modeldock
```

The scenarios prove distinct canonical causes:

- `APPROVED`: Governor `PROCEED`, explicit `APPROVE_HANDOFF`, accepted intake,
  and a created Navigator SHADOW plan.
- `HELD`: Governor has routed the mission for review but no operator approval
  has occurred.
- `VETOED`: the operator explicitly rejects the handoff.
- `FAILED`: controlled Navigator intake validation fails technically.
- `INCOMPLETE`: orchestration deliberately stops after Oracle and ModelDock
  replay enrichment.

## Output layout

The approved target writes beneath:

```text
artifacts/demo-readiness/approved/
└── missions/
    └── <mission-id>/
        ├── request/
        ├── snapshots/
        ├── mission_snapshot.json
        ├── oracle/
        │   └── modeldock/
        ├── council/
        ├── governor/
        ├── operator/
        ├── navigator/
        └── presentation/
            ├── captains_log.json
            ├── captains_log.md
            ├── mission_summary.json
            ├── mission_brief.html
            └── demo_manifest.json
```

The CLI prints the actual mission identifier and exact presentation paths.
Inspect JSON without requiring `jq`:

```bash
.venv/bin/python3.11 -m json.tool \
  artifacts/demo-readiness/approved/missions/mission-buildweek-replay-001/presentation/mission_summary.json

.venv/bin/python3.11 -m json.tool \
  artifacts/demo-readiness/approved/missions/mission-buildweek-replay-001/presentation/captains_log.json
```

The Captain's Log is a deterministic projection of canonical evidence. It is
not LLM-authored and does not replace the snapshot chain.
`demo_manifest.json` records mission-relative references and hashes for the
Captain's Log, mission summary, and final snapshot.

## Direct CLI equivalents

The Make targets are thin wrappers over these submission commands:

```bash
export MODELDOCK_BASE_URL=http://127.0.0.1:8000
export MODELDOCK_TIMEOUT_SECONDS=30
export MODELDOCK_PROFILE=default
export MODELDOCK_PROVIDER=mlx
unset MODELDOCK_MODEL

.venv/bin/python3.11 -m blackpod_build_week.harbormaster \
  preflight --mode replay --artifacts-root artifacts/demo-readiness/preflight

.venv/bin/python3.11 -m blackpod_build_week.harbormaster \
  validate-demo-packs --artifacts-root artifacts/demo-readiness/validation

.venv/bin/python3.11 -m blackpod_build_week.harbormaster \
  demo approved --rehearse \
  --artifacts-root artifacts/demo-readiness/approved-rehearsal
```

The detailed stage-level commands remain documented in the repository
README. Demo commands reuse those workflows; they do not implement alternate
Oracle, Council, Governor, operator, Navigator, or ModelDock logic.

## Idempotency and evidence preservation

- Repeating an identical completed scenario returns the existing result.
- A different action or fixture identity against an existing mission fails.
- Immutable revision snapshots and immutable stage artifacts are never
  rewritten.
- Mutable presentation projections are refreshed atomically only when their
  canonical source changes.
- There is no Make `clean` target. Set a different `DEMO_ROOT` when fresh
  output is required.

## Optional LIVE readiness

LIVE is not part of the deterministic judge path. Start ModelDock separately,
configure its loopback endpoint and local MLX model, and use the explicit live
preflight command:

```bash
export MODELDOCK_BASE_URL=http://127.0.0.1:8000
export MODELDOCK_TIMEOUT_SECONDS=30
export MODELDOCK_PROFILE=default
export MODELDOCK_PROVIDER=mlx
export MODELDOCK_MODEL=<registered-local-mlx-model>

.venv/bin/python3.11 -m blackpod_build_week.harbormaster \
  preflight --mode live --artifacts-root artifacts/live-preflight
```

A shallow health response is insufficient. LIVE readiness requires a real,
non-mocked smoke inference. Build Week never starts or reconfigures ModelDock
and never falls back from LIVE to REPLAY.

For the complete Stage 4 path from explicit LIVE mission inputs through strict
approved packaging and the two Captain's Cabin data slots, see the [Stage 4
LIVE Demo Runbook](LIVE_DEMO_RUNBOOK.md).

Add `--strict-clean` to either preflight mode when both the Build Week and
Battlestar worktrees must be clean rather than reported with warnings.

## Safety verification

Confirm sibling worktrees before and after a rehearsal:

```bash
git -C "$BATTLESTAR_PATH" status --short
git -C /absolute/path/to/ModelDock status --short
```

The expected Navigator envelope allows exactly `VALIDATE` and `PLAN_ONLY` and
prohibits `SUBMIT_ORDER`, `CANCEL_ORDER`, `MODIFY_PORTFOLIO`, and
`BROKER_CALL`. See [Safety Boundary](SAFETY_BOUNDARY.md).

## Troubleshooting

`BATTLESTAR_PATH is required`
: Export the absolute path to the sibling Battlestar checkout. Do not point it
  inside `artifacts/`.

`BATTLESTAR_PATH is not a directory`
: Correct the path and rerun preflight. The Makefile does not guess repository
  topology.

Replay reports a ModelDock model mismatch
: An inherited `MODELDOCK_MODEL` can conflict with the exact replay pack. Make
  removes it for replay commands; for a direct CLI call, run
  `unset MODELDOCK_MODEL` first.

The demo reports an existing completed mission
: This is the expected idempotent no-op. Use a new contained `DEMO_ROOT` for a
  visibly fresh run.

`make demo-failed` prints exit `11`
: Exit `11` is the expected controlled technical failure for that scenario.
  The Make target rejects any other code.

Unexpected demo command failure
: Normal output is sanitized and omits tracebacks. Rerun the direct `demo`
  command with `--debug` only during development when a traceback is needed.

LIVE preflight cannot reach ModelDock
: Start ModelDock separately and verify the configured URL is a loopback
  origin. No deterministic replay command requires it.
