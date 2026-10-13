# Investment proposals and declared SHADOW review

This burst adds deterministic portfolio-risk proposals and explicit declared
human review to the passive journal. All commands are offline. No providers,
inference, live stages, brokers, orders, capital transfers or live policy
changes are invoked. The initial 50/50 capital proposal remains inactive.

## Contracts and decision meaning

The new strict documents are:

| Contract | Purpose |
| --- | --- |
| `blackpod.investment_shadow_risk_policy.v1` | Versioned proposed limits, evidence gates, freshness, reviewer roles and expiry |
| `blackpod.investment_risk_context.v1` | Explicit manually supplied or synthetic account snapshot |
| `blackpod.investment_decision_proposal.v1` | Exact hypothesis/challenge/evaluation links, complete investment targets, rationale and bound risk inputs |
| `blackpod.investment_shadow_approval.v1` | Exact proposal/report/policy/context hashes, action, declared actor, origin and shadow-only confirmation |

Journal event v4 adds `INVESTMENT_DECISION_PROPOSAL_RECORDED` and
`INVESTMENT_SHADOW_APPROVAL_RECORDED`. Existing v1/v2/v3 events remain compatible.
A proposal has its own decision identity; approval/rejection/deferral/revocation
events share that proposal's decision identity. The hypothesis and earlier
reviews remain separate, linked evidence. No event is rewritten.

The deterministic proposal gate is `REVIEW_READY`, `REJECT` or `DEFER`.
`REVIEW_READY` means supplied research and paper risk inputs passed their
recorded checks. It does not establish economic truth, grant investment
authority, allocate capital or authorize a broker order. Forecasts,
recommendations, hypotheses, authorizations and executable orders remain
different concepts. A Navigator SHADOW approval grants no permission here.

Approval scope is exactly `INVESTMENT_SHADOW_RESEARCH_ONLY`. The four authority
flags (`authorization_enabled`, `capital_activation_enabled`,
`execution_enabled`, `policy_changes_enabled`) stay false in all inputs and
reports. Approval records always have `execution_status=NOT_EXECUTED` and
`realized_trade_pnl=null`. A paper target portfolio is not an executable order.

## Deterministic risk checks

Weights are long-only fractions of total account equity. The context includes
both desks' positions and cash. Supplied weights are never normalized. The
contract allows only a tiny representation tolerance, and the deterministic
gate requires an exact Decimal total of one; discrepancies defer review.

The proposal supplies every existing investment symbol, including explicit
zero targets when proposing removal. It cannot spend trading cash. The
investment budget is its currently declared positions plus cash, not an
automatic reset to 50%. Trading positions stay fixed while calculating the
proposed consolidated account exposures.

The versioned method checks desk budget, investment and consolidated gross,
cash reserve, consolidated symbol and sector weights, liquidity, supplied
stress losses, and high absolute correlation pair concentration. Same-symbol
positions across desks count together. Missing metadata, liquidity, stress
inputs or correlations defer rather than silently becoming zero. Hard limit
failures reject; failures take precedence over unknown inputs.

Research gates require a prospective active hypothesis, current context,
selected active reviews, declared fundamental/statistical roles, distinct
retained role artifacts, and no active dissent, unresolved questions or
untested assumptions. Known invalidation rejects. Unmet expected outcomes
defer even when an overall incomplete evaluation is inconclusive. Different
artifacts or declared roles do not establish economic independence.

The policy and context are retained with the proposal. Reusing a policy ID and
version or context ID with different bytes fails verification. No current
policy is substituted into an older proposal during replay. A new policy
version requires a new explicitly supplied proposal; outcomes never modify
policy limits automatically.

## Explicit declared review and immutable lifecycle

An approver must have the exact bound policy's allowed ID and role and differ
from the proposal submitter, hypothesis author, selected challenger and
selected evaluator. These checks establish string separation only.
`approver_identity_authenticated=false` always. Origin is either
`HUMAN_DECLARED` or `SIMULATED_TEST`; simulation produces
`SIMULATED_SHADOW_APPROVED`, never a claim of actual human approval.

Positive approval requires the exact original `REVIEW_READY` report and
acknowledgment of every residual risk. Its recording time cannot precede the
proposal; its expiry must fit both proposal validity and policy lifetime. The
context freshness and hypothesis horizon are checked again at approval time.
The full gate is reassessed against newly known source-bound reviews. New
dissent, unmet expectations, invalidation, superseded selected reviews, a
superseded proposal or a newer recorded portfolio context prevent approval of
the older packet.

The input confirmation binds the exact action and canonical proposal hash.
The recording CLI additionally requires `--confirm-action`,
`--confirm-proposal-sha256` and `--acknowledge-shadow-only`. JSON alone is not
the explicit recording confirmation. Validation is read-only.

One `APPROVE`, `REJECT` or `DEFER` action is permitted per proposal. Reconsider
with a new proposal rather than rewriting that action. `REVOKE` references
the exact prior `APPROVE` for the same proposal and cannot predate or revoke it
twice. Identical retries replay the original event's history prefix and remain
no-ops after expiry, revocation or later evidence changes. Changed content
under the same event identity conflicts.

Use an explicit `--as-of` when inspecting approval lifecycle. Results include
`UNREVIEWED`, `SIMULATED_SHADOW_APPROVED`, `SHADOW_RESEARCH_APPROVED`,
`REJECTED`, `DEFERRED`, `REVOKED` or `EXPIRED`. A lifecycle query describes the
recorded review; it does not grant operational authority or continuously
revalidate a live portfolio. No automatic action follows expiry or revocation.

## Runnable synthetic example

The source histories were created through the actual `MissionStore` and are
verified on import. All values, research, identities, risk scores and dates
are synthetic fixtures. Passing source bindings demonstrates consistency with
retained bytes, not actual economic evidence or investment performance. The
example records only a `SIMULATED_TEST` approval.

Run from this checkout. The journal output stays separate from source storage.

```sh
export PYTHONDONTWRITEBYTECODE=1
export PYTHONPATH=src

.venv/bin/python3.11 -m blackpod_build_week.harbormaster journal export-mission \
  --mission-root fixtures/investment_governance/sources/initial/missions/mission-review-initial \
  --journal-root output/investment-governance-example

.venv/bin/python3.11 -m blackpod_build_week.harbormaster journal export-mission \
  --mission-root fixtures/investment_governance/sources/statistical/missions/mission-review-statistical \
  --journal-root output/investment-governance-example

.venv/bin/python3.11 -m blackpod_build_week.harbormaster journal record-hypothesis \
  --journal-root output/investment-governance-example \
  --hypothesis fixtures/investment_governance/hypothesis.shadow.v1.json

.venv/bin/python3.11 -m blackpod_build_week.harbormaster journal record-challenge \
  --journal-root output/investment-governance-example \
  --challenge fixtures/investment_governance/challenge.shadow.v1.json

.venv/bin/python3.11 -m blackpod_build_week.harbormaster journal assess-investment-proposal \
  --journal-root output/investment-governance-example \
  --proposal examples/investment_proposal.shadow.v1.json

.venv/bin/python3.11 -m blackpod_build_week.harbormaster journal record-investment-proposal \
  --journal-root output/investment-governance-example \
  --proposal examples/investment_proposal.shadow.v1.json

.venv/bin/python3.11 -m blackpod_build_week.harbormaster journal validate-investment-approval \
  --journal-root output/investment-governance-example \
  --approval examples/investment_approval.simulated.v1.json

.venv/bin/python3.11 -m blackpod_build_week.harbormaster journal record-investment-approval \
  --journal-root output/investment-governance-example \
  --approval examples/investment_approval.simulated.v1.json \
  --confirm-action APPROVE \
  --confirm-proposal-sha256 db510122f40fe70bf84b350a1340e04e6ef47d431c580b6cfd76a0be0cd380f5 \
  --acknowledge-shadow-only

.venv/bin/python3.11 -m blackpod_build_week.harbormaster journal show-investment-proposal \
  --journal-root output/investment-governance-example \
  --proposal-id proposal-fixture --as-of 2026-10-13T00:02:00Z

.venv/bin/python3.11 -m blackpod_build_week.harbormaster journal show-investment-approval \
  --journal-root output/investment-governance-example \
  --approval-id approval-simulated-fixture --as-of 2026-10-13T00:02:00Z

.venv/bin/python3.11 -m blackpod_build_week.harbormaster journal propose-capital-policy \
  --journal-root output/investment-governance-example \
  --proposal examples/capital_policy.proposed.v1.json

.venv/bin/python3.11 -m blackpod_build_week.harbormaster journal verify \
  --journal-root output/investment-governance-example
```

The result is **9 events, 18 unique retained evidence blobs, no orphans**.
Exact projected events, immutable entries and verification results are retained
under `fixtures/investment_governance/expected`. Repeating recording commands
writes nothing. The standalone risk policy and context examples match the
proposal's embedded normalized documents; editing either file does not alter
an already recorded proposal.

To inspect negative gates without recording or approving them:

```sh
.venv/bin/python3.11 -m blackpod_build_week.harbormaster journal assess-investment-proposal \
  --journal-root output/investment-governance-example \
  --proposal fixtures/investment_governance/proposal.reject.shadow.v1.json

.venv/bin/python3.11 -m blackpod_build_week.harbormaster journal assess-investment-proposal \
  --journal-root output/investment-governance-example \
  --proposal fixtures/investment_governance/proposal.defer.shadow.v1.json
```

Their expected gates are `REJECT` for excessive targets and `DEFER` for an
incomplete context. Preview commands create no journal entries.

## Tests and limits

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests .venv/bin/python3.11 \
  -m unittest test_investment_governance_contracts \
  test_investment_governance_engine test_investment_approval \
  test_investment_governance_store test_investment_governance_examples \
  test_investment_governance_cli -q
```

The tests cover input strictness, limits, missing information, declared role
separation, exact source binding, timing, active review changes, scope,
idempotency, semantic tampering, interrupted publication, concurrency,
restoration and old-version compatibility. They validate offline mechanics.

The current context has no signed broker/account snapshot, ownership or
credential authentication. IDs, timestamps, units, correlations, liquidity and
stress assumptions are supplied claims. This method is long-only and does not
model derivatives, leverage financing, transaction costs, tax, intraday
exposure or settlement. Local POSIX storage and the existing 64 MiB bounds and
trusted-root hash limitations remain.

The original hypothesis contract fixes final evaluation at `horizon.end_at`.
Approval rejects an ended horizon. Therefore `require_final_evaluation=true`
generally prevents positive review for that same ended hypothesis. Use its
final evaluation as evidence for a new prospective hypothesis and proposal;
do not change the original horizon to accommodate approval. The example
explicitly sets that requirement false and discloses the absence of final
evaluation among its residual risks. Known interim invalidations and unmet
expectations still block an older packet.

Trading automation controls are a separate `TRADING` scope. Investment
SHADOW approvals cannot enable the trading switch or become broker
authorization. A requested trading-control setting does not make a live
executor available. Capital activation, transfers, perpetual 50/50 rebalancing
and self-modifying policies remain disabled.

The separately invoked [auto-trading controller](AUTO_TRADING.md) supervises a
guarded Galactica trading worker. Its explicitly confirmed runtime profile is
separate from these investment approvals, and this burst leaves it OFF.
Its fixed trading-dollar budget does not activate the capital proposal or
transfer investment cash. No investment allocation execution is implemented.

The next implementation should verify authoritative desk ownership and
paper execution reconciliation before considering automated investment
allocation authority.
