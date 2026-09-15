# Architecture

BlackPod Battlestar's Captain's Cabin is a live, read-only presentation of
canonical mission evidence. The repository retains its existing filesystem-backed
mission orchestration and bounded ModelDock narrative seam, but the product's
normal startup is a separate artifact reader, not an orchestration command.
The [product specification](PRODUCT_SPEC.md) governs current scope;
Build Week/demo packaging is historical review infrastructure.

## Repository boundaries

| Boundary | Responsibility | Write policy |
| --- | --- | --- |
| This repository | existing contracts/workflows plus read-only publication and Cabin presentation | implementation writable; reader never writes mission state |
| Battlestar sibling | Oracle, Council evidence chain, Governor, operator, Navigator native interfaces | read-only |
| ModelDock sibling/service | local MLX `text.generate` appliance | repository read-only; only separately authorized orchestration calls the service, never the reader |
| Mission root | canonical requests, snapshots, captured component artifacts, presentation projections | producer-owned; read-only to the Cabin reader |

No stage reads arbitrary sibling presentation output or an unqualified
"latest" artifact. Inputs are selected explicitly, copied beneath the mission
root when required, hashed, and correlated to the mission and request.

## Live presentation flow

```text
explicit artifact root + one LIVE mission ID
                    |
                    v
canonical snapshots + captured evidence (read-only)
                    |
                    v
loopback reader: validate and publish immutable bytes in memory
                    |
          /live/current.json (polled every five seconds)
                    |
                    v
browser integrity checks -> existing presentation models
                    |
                    v
Captain's Cabin -> SVG Mission Chart -> expanded Navigator V3
```

The reader accepts all legitimate mission outcomes. It does not require the
legacy approved-demo packager, select a new mission automatically, or call the
producer. The additive publication manifest is a transport wrapper; canonical
mission schemas and domain decisions remain unchanged. Source failures are
availability failures, not fabricated mission outcomes. Last verified evidence
may remain visible with explicit degraded/offline labeling and its original
timestamps.

## Existing canonical producer flow

This flow is invoked only through separately authorized mission commands. It is
not a side effect of launching or refreshing the Cabin.

```text
Mission request
    │
    ▼
Harbormaster ──► Oracle ──► ModelDock narrative (optional, explicit)
                              │
                              ▼
                           Council ──► Governor
                                         │
                              PROCEED only│
                                         ▼
                              explicit operator gate
                                         │ APPROVE_HANDOFF only
                                         ▼
                         Navigator handoff → intake → SHADOW plan
```

The unified command calls the same workflow functions used by the stage-level
commands. It does not collapse transitions, fabricate stage completion, or
rerun completed stages during resume.

## Layers

### Contracts

`src/blackpod_build_week/contracts/` defines strict versioned mission,
snapshot, ModelDock narrative, and presentation contracts. Unknown or
unsupported contract values fail closed. The canonical mission snapshot keeps
all five component stages present and separates technical status from each
component's native state.

### Adapters

The Build Week-owned adapters are narrow process boundaries around current
Battlestar Python entry points. They preserve native results, correlations,
warnings, and provenance. They do not reproduce calculations or policy.

### Stage workflows

Each workflow owns precondition checks, one stage attempt, immutable artifact
capture, and its RUNNING plus terminal snapshot transitions:

- `oracle_workflow.py`
- `oracle_enrichment_workflow.py`
- `council_workflow.py`
- `governor_workflow.py`
- `operator_workflow.py`
- `navigator_workflow.py`

### Unified orchestration

`unified_mission_workflow.py` is state-driven coordination over those existing
workflows. `mission-run` starts a mission; `mission-resume` validates stored
state and continues from the first eligible incomplete operation. Completed
identical work is an explicit no-op.

The historical demo command layer selects committed scenario inputs and
delegates to this same orchestration path. Demo-pack validation remains a
regression/review tool, not a second mission engine or live display gate.

### Persistence

`MissionStore` owns the deterministic layout:

```text
<artifacts-root>/missions/<mission-id>/
├── request/mission_request.json
├── snapshots/mission_snapshot-rNNNN.json
├── mission_snapshot.json
├── oracle/
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

Revision snapshots and stage artifacts are immutable. The producer replaces
the current snapshot and presentation projections atomically. Every revision
carries the SHA-256 of its predecessor, producing a complete tamper-evident
chain. Containment checks reject paths outside the mission root. The reader
does not create this layout, update projections on disk, or write a demo
manifest into the selected source.

### Presentation

`mission_presentation.py` derives `captains_log.json`, `captains_log.md`, the
versioned UI-facing `mission_summary.json`, and a script-free
`mission_brief.html` from validated snapshots and recorded artifacts. The HTML
consumes the validated JSON projections and remains explicitly non-canonical.
The historical demo layer adds `demo_manifest.json`, which hashes the JSON
views and final canonical snapshot. Live publication instead derives verified
projections and a generic `presentation/manifest.json` in memory, independently
of approved-demo packaging. Neither manifest grants mission authority.

`cabin_reader.py` serves `blackpod.cabin_feed.v1` at `/live/current.json`, with
`READY`, `NOT_CONFIGURED`, or `UNAVAILABLE` status. Verified bytes are addressed
under `/live/revisions/<publication-id>/`; only the last three publications are
retained, in memory. The reader binds `127.0.0.1`, supports read methods only,
and serves the built UI without demo assets. A Vite development proxy uses the
same local `/live` interface.

The browser validates the generic manifest, correlated presentation contracts,
immutable snapshot, and referenced evidence before displaying a revision. It
does not mix one revision's projections with another revision's source bytes.
Reader `checked_at` and original snapshot `observed_at` remain distinct;
optional market/portfolio captures and ModelDock inference provenance keep
their own recorded times. Polling does not imply live market acquisition or
present ModelDock service health.

The Cabin's normal route is LIVE. Explicit `?mode=replay` is retained for
developer/historical review, with the old `?mode=demo` as a compatibility alias.
There is no normal Demo/Live switch or automatic fallback.

## State and outcome authority

Technical stage statuses are `NOT_STARTED`, `RUNNING`, `SUCCEEDED`, `FAILED`,
and `SKIPPED`. Component-native states—such as a Council posture or Governor
disposition—remain separate.

Canonical outcomes are derived from validated transitions:

- `INCOMPLETE`: orchestration deliberately stopped before a decision outcome
- `HELD`: review or explicit approval remains open
- `VETOED`: Governor `STAND_DOWN` or explicit operator rejection
- `FAILED`: a technical, schema, state, deadline, integrity, or correlation failure
- `APPROVED`: explicit operator approval followed by a validated Navigator
  SHADOW plan

Governor `PROCEED` alone is never approval.

## Transport policy

Producer LIVE and REPLAY modes are explicit and never substituted for one
another. REPLAY uses deterministic inputs while exercising the same validation,
capture, and transition logic. Producer LIVE uses native interfaces and
requires its real dependencies to succeed. Its ModelDock traffic is limited to
an explicitly configured loopback endpoint and rejects mocked responses.

The read-only live reader requires a canonical LIVE source but makes no provider
calls. Failure to read that source never starts a mission, invokes ModelDock,
selects a replay fixture, or relabels historical evidence as freshly acquired.

## Further reading

- [Product specification](PRODUCT_SPEC.md)
- [Live product runbook](LIVE_PRODUCT_RUNBOOK.md)
- [Archived Demo Runbook](DEMO_RUNBOOK.md)
- [Safety Boundary](SAFETY_BOUNDARY.md)
- [Build Week Changelog](BUILD_WEEK_CHANGELOG.md)
