# Safety Boundary

This submission ends at a validated Navigator SHADOW plan. It cannot submit,
cancel, or alter a live order or position.

## Authority by component

| Component | May do | Must not do |
| --- | --- | --- |
| Oracle | produce measurements, diagnostics, readiness, and typed analytical conclusions | approve a mission or execute a trade |
| ModelDock | explain validated Oracle evidence in a strict structured narrative | change facts, invent measurements, decide disposition, approve, or execute |
| Council | synthesize recorded Oracle, candidate, Senate, and Mandate evidence using existing Battlestar policy | invent new voting or confidence policy |
| Governor | render the current canonical disposition | approve Navigator handoff or perform an operator action |
| Operator | record one explicit supported action against a valid review packet | bypass Governor state or invoke Navigator implicitly |
| Navigator | validate an approved handoff and create a SHADOW plan | call a broker, submit orders, or modify a portfolio |

## Approval gate

The only successful approval sequence is:

```text
Governor PROCEED
→ operator route PENDING_APPROVAL
→ explicit APPROVE_HANDOFF
→ APPROVED_FOR_HANDOFF
→ handoff STAGED
→ intake ACCEPTED
→ SHADOW plan CREATED
→ mission outcome APPROVED
```

`PROCEED` means “eligible for operator review,” not “approved.” Before the
explicit action, the mission remains `HELD`. Operator rejection produces
`VETOED` and Navigator remains `NOT_STARTED`.

The final approval scope is exactly `NAVIGATOR_SHADOW_HANDOFF`. It does not
authorize execution.

## Navigator operation envelope

Allowed operations are exactly:

- `VALIDATE`
- `PLAN_ONLY`

Prohibited operations include exactly the canonical non-execution envelope:

- `SUBMIT_ORDER`
- `CANCEL_ORDER`
- `MODIFY_PORTFOLIO`
- `BROKER_CALL`

The Build Week package has no broker client, broker credentials, order API, or
portfolio mutation path.

## ModelDock boundary

- Oracle facts are materialized and validated before narrative enrichment.
- The request contains selected Oracle evidence, never arbitrary filesystem
  content or absolute paths.
- Canonical output is structured JSON, not unconstrained prose.
- Unsupported numerical claims, authority claims, malformed output,
  correlation mismatches, and mocked LIVE results are rejected.
- LIVE accepts only the configured local MLX policy at a loopback origin.
- A ModelDock failure never becomes a source of substitute market facts and
  never triggers a hidden REPLAY fallback.

## Persistence and integrity boundary

- Every stored path must remain beneath the mission root.
- Stage artifacts and snapshot revisions are immutable.
- Current mutable projections are written atomically.
- SHA-256, byte size, producer, timestamp, contract version when known, and
  correlation identifiers are recorded for captured artifacts.
- Snapshot revisions form a complete `previous_snapshot_sha256` chain.
- Missing or hash-invalid evidence is rejected rather than silently repaired.
- Canonical snapshots and committed fixtures do not contain machine-specific
  absolute paths or secrets.

## Repository and service boundary

Battlestar and ModelDock sibling repositories remain read-only. Build Week
does not format, install into, or generate files inside them. ModelDock must be
started separately for an explicit LIVE call. REPLAY never calls its network
endpoint.

There is no UI, web service, database, queue, daemon, or scheduler in this
submission.

## Failure semantics

Technical, schema, integrity, expiry, and correlation failures produce
`FAILED`; they are not reinterpreted as a Governor veto. Native caution,
warning, disagreement, `HOLD`, `BLOCKED`, or `REVIEW_REQUIRED` states remain
valid domain results when their owning contract says so.

The demo's controlled failure is deliberate evidence of this fail-closed
behavior. It creates a canonical failure snapshot and returns workflow exit
code `11`.

