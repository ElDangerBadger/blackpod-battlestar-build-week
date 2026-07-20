# Architecture

BlackPod Battlestar Build Week is a filesystem-backed mission orchestrator. It
connects existing Battlestar components and a strictly bounded local ModelDock
narrative seam without duplicating their domain logic.

## Repository boundaries

| Boundary | Responsibility | Write policy |
| --- | --- | --- |
| Build Week | contracts, orchestration, state transitions, artifact capture, validation, presentation | writable |
| Battlestar sibling | Oracle, Council evidence chain, Governor, operator, Navigator native interfaces | read-only |
| ModelDock sibling/service | local MLX `text.generate` appliance | repository read-only; service called only in explicit LIVE mode |
| Mission root | canonical requests, snapshots, captured component artifacts, presentation projections | contained beneath configured artifact root |

No stage reads arbitrary sibling presentation output or an unqualified
"latest" artifact. Inputs are selected explicitly, copied beneath the mission
root when required, hashed, and correlated to the mission and request.

## Canonical flow

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

The demo command layer selects committed scenario inputs and delegates to this
same orchestration path. Demo-pack validation verifies contracts and hashes;
it is not a second mission engine.

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

Revision snapshots and stage artifacts are immutable. The current snapshot and
presentation projections use atomic replacement. Every revision carries the
SHA-256 of its predecessor, producing a complete tamper-evident chain.
Containment checks reject paths outside the mission root.

### Presentation

`mission_presentation.py` derives `captains_log.json`, `captains_log.md`, the
versioned UI-facing `mission_summary.json`, and a script-free
`mission_brief.html` from validated snapshots and recorded artifacts. The HTML
consumes the validated JSON projections and remains explicitly non-canonical.
The demo layer adds `demo_manifest.json`, which hashes the JSON views and the
final canonical snapshot. These files are deterministic views for judges and a
future read-only UI; they are not sources of mission truth.

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

LIVE and REPLAY are explicit and never substituted for one another. REPLAY
uses committed deterministic inputs while exercising the same Build Week
validation, capture, and transition logic. LIVE uses current native interfaces
and requires real dependencies to succeed. ModelDock LIVE traffic is limited
to an explicitly configured loopback endpoint and rejects mocked responses.

## Further reading

- [Demo Runbook](DEMO_RUNBOOK.md)
- [Safety Boundary](SAFETY_BOUNDARY.md)
- [Build Week Changelog](BUILD_WEEK_CHANGELOG.md)
