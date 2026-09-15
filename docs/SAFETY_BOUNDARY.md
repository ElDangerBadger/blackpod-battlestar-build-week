# Safety Boundary

The live Captain's Cabin reads and presents canonical mission evidence only.
It cannot start/resume a mission, record operator approval, submit or cancel an
order, or alter a position. The existing producer workflow ends at a validated
Navigator SHADOW plan. Productization does not expand that authority.

The [product specification](PRODUCT_SPEC.md) replaces the historical demo
scope. Future trading and add-symbol requests are roadmap items, not current
execution authority.

## Authority by component

| Component | May do | Must not do |
| --- | --- | --- |
| Oracle | produce measurements, diagnostics, readiness, and typed analytical conclusions | approve a mission or execute a trade |
| ModelDock | explain validated Oracle evidence in a strict structured narrative | change facts, invent measurements, decide disposition, approve, or execute |
| Council | synthesize recorded Oracle, candidate, Senate, and Mandate evidence using existing Battlestar policy | invent new voting or confidence policy |
| Governor | render the current canonical disposition | approve Navigator handoff or perform an operator action |
| Operator | record one explicit supported action against a valid review packet | bypass Governor state or invoke Navigator implicitly |
| Navigator | validate an approved handoff and create a SHADOW plan | call a broker, submit orders, or modify a portfolio |
| Cabin artifact reader | verify and publish explicitly selected LIVE mission evidence in memory | run workflows, write source artifacts, call providers, or select an arbitrary latest mission |
| Cabin UI | display verified evidence, provenance, availability, and local presentation interactions | create facts, mutate missions, approve, select trading symbols, or execute |

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

The Cabin has no broker client, broker credentials, order API, or portfolio
mutation path. An artifact's SHADOW approval cannot become a trading permission
through display wording or a change from Replay to LIVE presentation.

## ModelDock boundary

- Oracle facts are materialized and validated before narrative enrichment.
- Deterministic code enumerates a bounded Oracle fact catalog. Each stable ID
  records its immutable source artifact, canonical pointer, and exact value;
  arbitrary filesystem content and absolute paths are excluded.
- ModelDock selects only catalog IDs and authors interpretation fields. It may
  not author canonical observed-fact objects or Oracle warnings.
- Deterministic code expands selected IDs, copies Oracle warnings, and validates
  the completed canonical `blackpod.oracle_narrative.v1` object. Output is
  structured JSON, not unconstrained prose.
- Unsupported numerical claims, authority claims, malformed output,
  correlation mismatches, and mocked LIVE results are rejected.
- LIVE accepts only the configured local MLX policy at a loopback origin.
- A ModelDock failure never becomes a source of substitute market facts and
  never triggers a hidden REPLAY fallback.
- These rules govern separately authorized producer calls. Opening the live
  Cabin does not call ModelDock. Displayed inference provenance refers to the
  recorded mission-time result, not present model/service health.

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
- The reader validates existing source evidence without persisting projections,
  repairing artifacts, or modifying the source mission. Published byte snapshots
  are immutable and bounded in memory.
- An unavailable or invalid update does not replace verified evidence. If old
  evidence stays visible, it remains explicitly last-verified/degraded with its
  original timestamps. No fallback replay or fabricated state is allowed.

## Repository and service boundary

Battlestar and ModelDock sibling repositories remain read-only. This repository
does not format, install into, or generate files inside them. ModelDock must be
started separately for an explicitly authorized producer LIVE call. REPLAY
never calls its network endpoint; the artifact reader does not call it in
either case.

The current product has an interactive read-only UI and a loopback-only HTTP
reader, unlike the original submission. It has no mission mutation API,
provider-calling startup path, database, queue, or workflow scheduler. UI
polling reads existing evidence; it does not schedule mission execution. The
generated HTML mission brief remains static, script-free, and read-only.

The reader is a local product, not an authenticated remote deployment. Do not
expose it through public forwarding or treat loopback binding as a design for
multi-user authorization. Remote hosting requires a separate security scope.

Historical commands remain capable of explicit producer work. In particular,
`make live-mission` records `APPROVE_HANDOFF`; it is never a normal Cabin
startup, repair, or refresh step.

## Failure semantics

Technical, schema, integrity, expiry, and correlation failures produce
`FAILED`; they are not reinterpreted as a Governor veto. Native caution,
warning, disagreement, `HOLD`, `BLOCKED`, or `REVIEW_REQUIRED` states remain
valid domain results when their owning contract says so.

The reader displays any valid canonical outcome, including incomplete, held,
vetoed, and failed missions. It does not require approval merely to present
evidence. Reader/configuration/integrity failures remain availability states,
not invented Governor vetoes or canonical mission failures.

Historical controlled-failure fixtures remain evidence of producer fail-closed
behavior: that explicit workflow creates a canonical failure snapshot and
returns exit code `11`. It is not run during live-product startup.
