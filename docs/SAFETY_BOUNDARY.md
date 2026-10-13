# Safety Boundary

The live Captain's Cabin reads and presents canonical mission evidence only.
It cannot start/resume a mission, record operator approval, submit or cancel an
order, or alter a position. The existing producer workflow ends at a validated
Navigator SHADOW plan. Productization does not expand that authority.

The [product specification](PRODUCT_SPEC.md) replaces the historical demo
scope. Cabin trading and add-symbol workflows remain roadmap items. The
separately invoked [Galactica trading controller](AUTO_TRADING.md) is governed
by its explicitly confirmed account/mode/budget profile and defaults OFF.
It adds no authority to the Cabin or canonical Navigator SHADOW workflow.

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
| Investment journal/governance | retain source-bound research, proposed risk checks and declared SHADOW review | execute allocations, authenticate declared identities, enable trading or activate capital |
| Separate Galactica controller | supervise explicitly confirmed PAPER TRADING execution within account/symbol/budget guards and an installed declared desk book | use investment or SHADOW handoff approval as trading authority, activate funded execution, manage protected holdings, transfer capital or restart automatically |
| Paper reconciliation | retain exact broker/attempt identities, cumulative fills and unresolved acceptance; restrict runtime scope through verified book bindings | infer realized P&L, silently classify old holdings, resubmit uncertain orders or activate capital |
| Offline fill-lot accounting | replay individual retained PAPER fills and fees with exact receipts, declared ownership and a verified flat baseline | invent fee completeness, cost basis or fills; assign profit to SHADOW missions; clear runtime barriers or enable trading |

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

Galactica also remains read-only. Its explicitly selected execution import
closure and frozen inputs are copied into a separate private runtime session;
the guarded worker imports that retained snapshot after profile, environment
and dependency checks. Its broker calls occur only through the separate
explicit execution controller. Journal and mission commands do not import
the native executor. See [Auto-trading controls](AUTO_TRADING.md) for OFF,
draining, admission locks, recovery and execution limits.

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

## Shadow desk review boundary

The explicit [two-desk review](SHADOW_DESK_REVIEW.md) commands compute, append,
read and render research proposals only. Journal v8 keeps all four authority
flags false, `readiness=false`, `auto_trading_enabled=false`, and realized trade
P&L null. Proposed ownership is `PROPOSED_NOT_INSTALLED`; the fixed testing
budget remains inactive. No command installs the book, changes the runtime
toggle, submits/cancels an order, transfers capital or rewrites mission state.

The native Oracle/candidate/Senate calculation uses only reviewed, fixed-hash
pure definitions from retained code. Spyglass uses its explicitly pinned native
source and existing dependencies. A historical Brigade transcript is parsed as
dated, incomplete-capable evidence; its original opinions and dissent do not
become current forecasts or approval. Current Brigade inference, model training,
legacy orchestrators and ModelDock calls are not enabled by this integration.
Unrecognized source code cannot become an executable analytical plugin by
adding a new hash to an input record.

Journal verification replays retained input/code/fact bindings and the original
journal prefix. Changed source bytes, fabricated sizes, altered Spyglass facts
and removed historical dissent reject even when outer entry hashes are
recomputed. Source identity checks do not attest economic truth or provider
identity. Shared market ancestry, IEX feed limits, retrospective swing detection
and heuristic confidence remain visible. Proposed stop scenarios are not loss
guarantees, and example parameters never modify existing live risk policies.

A later PAPER test requires separate explicit authorization for the actual
account, desk ownership, budget, size limits and expiry, plus fresh quotes and
the existing deterministic runtime risk/reconciliation checks. A current
research recommendation alone cannot cross that boundary. Auto-trading stays
**OFF** throughout this burst.

## Governed forecast and Brigade shadow boundary

The separate [forecast and Brigade interface](FORECAST_BRIGADE_SHADOW.md)
retains daily forecast sources and provenance before any advisory processing.
Original date-only precision remains date-only; issuance, feature availability,
supervised training-label availability and target timing require explicit
evidence. Neither a historical `LIVE` label nor a filesystem timestamp grants
currentness. Missing, stale or incompatible evidence defers analysis.

Brigade processing remains SHADOW-only. A native BUY or EXIT opinion and its
advisory trade plan are not executable instructions. Heuristic confidence is
not a calibrated probability. Malformed responses cannot acquire a valid
opinion through native fallback labels, and cross-horizon forecast rows cannot
be repurposed as a temporal series. Shared evidence ancestry, incomplete
coverage and dissent remain explicit.

Passive assessment, recording, viewing and journal verification do not call a
provider. Any optional local generation boundary requires an explicit command
and the existing strict ModelDock configuration; it cannot start or configure
the appliance, reconnect a legacy provider or silently retry a failed call.
Replay consumes retained responses and never generates a replacement opinion.

Journal v9 preserves disabled authorization, execution, capital activation and
policy-change authority. No command changes the OFF toggle, installs desk
ownership, modifies budgets, submits/cancels orders, moves money or edits live
rules. No realized trade P&L is assigned to forecasts or SHADOW analysis. The
fixed testing budget and recorded proposals remain inactive.

## Governed forecast-producer boundary

The explicit [forecast export](GOVERNED_FORECAST_EXPORT.md) may fit reviewed
native quantile definitions against retained completed market observations in
the existing fitting runtime. It must retain source bytes, configuration,
training rows, target-label availability and original quantile identities.
It cannot import the legacy orchestrator, deserialize cached models, write
into sibling source/model caches, repair crossed quantiles or change existing
model configuration. Session-date labels cannot become invented timestamps;
incomplete bars cannot become completed training observations.

Optional Brigade text generation uses the preserved local ModelDock capture
boundary with durable intents, bounded requests and no automatic retries.
Status-only discovery makes no inference request; verified journal replay
makes no fitting or text-generation call. Model routing belongs to ModelDock,
and health readiness alone cannot establish that native compute is idle.

Forecast export and Brigade opinions have no authorization, capital activation,
execution or policy-change authority. Auto-trading remains **OFF**, fixed desk
budgets remain inactive, and no ownership or size is installed. Daily forecasts
cannot override a long-horizon investment thesis or deterministic trading risk
controls. SHADOW-only research has no realized trade P&L.

## Structured Brigade response boundary

The [v2 structured response seam](BRIGADE_STRUCTURED_RESPONSES.md) accepts only
the declared member-response contract and its externally bound member/symbol.
Missing fields, unknown fields, execution instructions, numeric coercion,
nonfinite values, blank or multiline reasoning and legacy-response fallbacks
cannot become accepted advisory votes. Raw JSON is retained; valid fields are
projected deterministically for the original native parser, with no response
repair. Original v1/v9 records preserve their original validation and replay.

ModelDock schema acknowledgement does not establish economic truth, calibrated
confidence or trading permission. Fresh local capture remains explicitly
opt-in, bounded and protected by durable call intents. Failed or uncertain
delivery cannot trigger automatic inference retries; recovery consumes retained
receipts and defers missing members. Passive assessment, journal reads and
synthetic examples do not call providers or brokers.

Every structured review has disabled authorization, execution, capital
activation and policy-change authority. Auto-trading remains **OFF**. Typed
BUY/EXIT, native parser success and persona agreement cannot activate budgets,
install ownership, change live rules or bypass deterministic execution risk.
No realized trade P&L is invented for SHADOW-only analysis.

## Independent offline trading research boundary

The [new trading research foundation](TRADING_RESEARCH.md) accepts retained,
versioned specifications, observations and externally authored candidate
decisions. It does not generate decisions by importing Galactica entry/exit
rules, Brigade votes, forecasting presets, Navigator mandates, stop policies
or sizing heuristics. Generic decimal accounting and journal infrastructure
do not confer authority on a legacy strategy.

Simulation checks declared chronological evidence availability and execution
timing, costs, cash and bounded exposure. Simulated fills, simulated P&L and
descriptive evaluation measures cannot be mistaken for broker executions,
realized account returns, proven alpha or capital-allocation instructions.
Trial registration and dataset provenance remain retained declarations rather
than independent attestations of every research action or vendor fact.

All offline research authority remains disabled. Auto-trading stays **OFF**;
commands cannot install ownership, activate the fixed testing budgets, change
live rules, start a provider or model, call brokers, submit/cancel orders,
transfer capital or autonomously promote a strategy. Research artifacts and
immutable journal records remain separate from mission/source and installed
execution storage. The investment desk's policies are unchanged.

The separately proposed Brigade evidence-consistency review may append
diagnostic contradictions while preserving original recommendations and
dissent. It is not part of this burst, and a clean diagnostic would grant no
trading authority.

## Historical hypothesis intake boundary

New catalog and historical-intake commands retain specifications and evidence
only. Plan/dataset v2 separates actual capture clocks from retrospective
session-end-plus-delay assumptions; it cannot claim authenticated historical
availability or blind preregistration. Empty intents are mandatory and no
strategy outcomes are scored. Raw prices lack corporate-action continuity
attestation, IEX volume lacks consolidated-market coverage, and modeled costs
and simulated sizes are uncalibrated placeholders.

Journal v13/v14 replay checks exact frozen catalog, GET receipts, raw/calendar
source reconstruction and original plan links. Every authority flag is false.
Auto-trading remains OFF; ownership, paper budgets, capital policy, ModelDock,
mission workflow and execution controls receive no changes. External data
capture is an explicit read-only operator action outside the offline CLI.

## Deterministic shadow intent boundary

Generated BUY/SELL documents are research simulation inputs. Their outer
producer record identifies frozen hypotheses, evidence gates and deterministic
method provenance. They grant no order authorization, ownership, budget or
execution authority. No Galactica rules, Brigade votes, LLM interpretation,
provider call or broker path generates these intents.

Price-continuity evidence requires complete locally reviewed coverage and no
declared discontinuity. Cost evidence must cover every symbol and clear the
predeclared stress bounds; missing reviews defer production. Hash verification
does not authenticate provider data, reviewers, historical publication or
observed trading costs. Synthetic evidence cannot authorize retained-history
research. Controls use fractional arithmetic only and match entry notional and
duration, with independent admission checks. Incomplete controls stay
inconclusive and cannot support a strategy selection.

All authority remains disabled and auto-trading stays OFF. Scoring uses only
development TEST segments; final holdout stays unscored. The investment desk,
capital policy, recorded paper budgets and installed execution configuration
are untouched. Calculation hashes and append-only records prevent silent
reinterpretation under a changed implementation.

## Governed evidence and sizing review boundary

Native data capture receipts permit only GET data endpoints for corporate
actions and historical quotes. Offline adapters never read credentials or call
providers. HTTP failure, incomplete pagination, missing effective-date coverage,
partial quote coverage and absent slippage/fee assumptions cannot imply support.
Origin evidence stays opaque and all raw bytes are retained for audit.

Simulation sizing is explicitly reviewed apart from original quality-plan risk.
PROPOSED, REJECTED and DEFERRED reviews remain ineligible. APPROVED_FOR_SHADOW
can prepare an ephemeral simulation projection, with original risk preserved,
and still requires independent continuity and cost gates. It cannot approve an
order, activate either desk's budget, move funds, modify investment policy or
enable trading. Review identities remain unauthenticated local claims.

Study v2 and journal v16 retain those separate scopes and their exact source
records. Final holdout stays unscored, old calculation versions remain pinned,
and auto-trading stays OFF. Retrospective quote bounds are sample support;
they do not establish costs known at every historical decision or future fills.
