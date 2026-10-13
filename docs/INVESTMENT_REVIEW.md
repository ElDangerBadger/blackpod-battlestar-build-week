# Shadow hypothesis challenge and outcome evaluation

Burst 3 extends the existing journal with explicit independent-review records and
linked comparisons against an investment hypothesis's fixed evaluation plan.
The commands remain offline. No providers, inference, live stages, brokers,
execution, capital transfers or policy modification are invoked.

See [the validation record](INVESTMENT_REVIEW_VALIDATION.md) for changed files,
exact executed commands, test results and archived-source coverage.

## What is implemented

`blackpod.investment_challenge.v1` records a supplied challenge bound to an exact
v2 hypothesis event and canonical draft hash. It includes a declared reviewer,
reviews of every original assumption, counterhypotheses and discriminating
tests, source observations, unresolved questions, risk notes and a review
disposition. The reviewer ID must differ from the author ID. This enforces
declared separation; it does not authenticate the human behind either ID.

Each observation binds the existing retained mission event, artifact hash,
JSON value pointer, source time pointer/role and cutoff. The assessment identifies
an identical value binding, shared artifact, or distinct retained artifact.
Copied bytes at a different path or in another mission still count as shared.
Declared `FUNDAMENTAL` and `STATISTICAL` roles are inventoried, with missing roles
explicit. An empty missing-role list means only that those labels were supplied.
Different files, providers/groups or role labels never establish independence:
`source_independence_verified` and each `independence_verified` remain false.

`blackpod.investment_outcome_evaluation.v1` links an exact hypothesis and an
existing challenge. The evaluator ID must differ from the hypothesis author;
the evaluator role must match the original fixed plan. Supplied measurements
must reference known original check IDs and match their metric/unit labels and
exact `due_at` or `check_by` points. Source values, timestamps and cutoffs are
validated through the same retained-evidence binder used by hypotheses.
There is no latest-source selection, synthesized measurement, unit conversion,
window aggregation or threshold tuning.

The comparison applies only the recorded `GT`, `GTE`, `LT`, `LTE`, `EQ` or `NE`
predicate. Missing/null/type-incompatible values remain unknown; booleans do not
become numbers and absence does not satisfy `NE`. Reusing a single observation
for two checks is allowed only with the same canonical binding.

| Comparison summary | Meaning |
| --- | --- |
| `PENDING` | At least one original deadline has not arrived by the supplied cutoff |
| `INCONCLUSIVE` | Mature checks lack usable measurements |
| `INVALIDATION_TRIGGERED` | A supplied exact-deadline point triggers a recorded invalidation predicate |
| `EXPECTATIONS_NOT_MET` | Complete usable checks include an unmet expectation without a triggered invalidation |
| `ALL_EXPECTATIONS_MET_NO_DEADLINE_INVALIDATION` | All supplied original deadline checks pass their required comparison |

Triggered invalidation has precedence, then pending, inconclusive and unmet
expectations. A `FINAL` review before the original plan's evaluation date is
rejected; `INTERIM` supports pending deadlines without pretending future data
exists. Every computed report is recomputed during locked append and verification.

These are **deadline-point comparisons**, not an adjudication of the investment
thesis or proof that no invalidation occurred throughout the horizon. The existing
plan does not define monitoring cadence/window coverage, so the comparator does
not invent those semantics. `whole_horizon_invalidation_established=false`,
`manual_review_required=true`, `economic_truth_evaluated=false`, and all authority
flags remain false. `realized_trade_pnl=null`, `execution_status=NOT_EXECUTED`.
An invalidation result does not change the original draft or a live policy.

## Immutable lifecycle and authority

Journal event v3 adds `INVESTMENT_CHALLENGE_RECORDED` and
`INVESTMENT_OUTCOME_EVALUATION_RECORDED`. Original v1 mission/evaluation/capital
records and v2 hypothesis records stay byte-compatible. New events share the
original hypothesis's decision ID but have distinct typed logical identities.
The original hypothesis, its plan, evidence and earlier dissent remain immutable.

Identical retry is a no-op; the same review ID with changed content conflicts.
A correction uses a new ID and explicit `supersedes_event_id`, pointing to an
earlier review of the same type and hypothesis. It cannot retreat recording time
or evidence cutoff, and a final outcome review cannot be downgraded to interim.
Supersession appends a link; it does not delete or hide the earlier record.
Queries never select an arbitrary latest record. If a review ID is reused across
hypotheses, supply `--hypothesis-id` to disambiguate it.

Assessment and comparison methods have explicit immutable version IDs:
`blackpod.source_relationship_assessment.v1` and
`blackpod.deadline_point_comparison.v1`. Changing their semantics requires a
versioned implementation/contract change; past criteria are not rewritten.

Forecasts, hypotheses, reviewer opinions, comparisons, recommendations,
authorizations and executable orders remain distinct. No outcome success or
review disposition activates an investment decision, trades, budget, capital
transfer, reallocation or policy improvement. The proposed initial 50/50 desk
split stays inactive and does not become a perpetual rebalance rule.

## Runnable synthetic example

Run from this checkout. All fixture data are explicitly synthetic. The outcome
fixture is future-dated to exercise mature checks; it is not an actual observed
investment outcome or evidence of prospective performance. No original fixture
or source mission is changed by export/review.

```sh
export PYTHONDONTWRITEBYTECODE=1
export PYTHONPATH=src

.venv/bin/python3.11 -m blackpod_build_week.harbormaster journal export-mission \
  --mission-root fixtures/investment_hypothesis/missions/mission-investment-hypothesis-example \
  --journal-root output/investment-review-example

.venv/bin/python3.11 -m blackpod_build_week.harbormaster journal record-hypothesis \
  --journal-root output/investment-review-example \
  --hypothesis examples/investment_hypothesis.shadow.v1.json

.venv/bin/python3.11 -m blackpod_build_week.harbormaster journal export-mission \
  --mission-root fixtures/investment_review/missions/mission-investment-challenge-evidence \
  --journal-root output/investment-review-example

.venv/bin/python3.11 -m blackpod_build_week.harbormaster journal validate-challenge \
  --journal-root output/investment-review-example \
  --challenge examples/investment_challenge.shadow.v1.json

.venv/bin/python3.11 -m blackpod_build_week.harbormaster journal record-challenge \
  --journal-root output/investment-review-example \
  --challenge examples/investment_challenge.shadow.v1.json

.venv/bin/python3.11 -m blackpod_build_week.harbormaster journal show-challenge \
  --journal-root output/investment-review-example \
  --challenge-id synthetic-financing-challenge-001

.venv/bin/python3.11 -m blackpod_build_week.harbormaster journal export-mission \
  --mission-root fixtures/investment_review/missions/mission-investment-outcome-evidence \
  --journal-root output/investment-review-example

.venv/bin/python3.11 -m blackpod_build_week.harbormaster journal evaluate-hypothesis \
  --journal-root output/investment-review-example \
  --evaluation examples/investment_outcome_evaluation.final.v1.json

.venv/bin/python3.11 -m blackpod_build_week.harbormaster journal record-hypothesis-evaluation \
  --journal-root output/investment-review-example \
  --evaluation examples/investment_outcome_evaluation.final.v1.json

.venv/bin/python3.11 -m blackpod_build_week.harbormaster journal show-hypothesis-evaluation \
  --journal-root output/investment-review-example \
  --evaluation-id synthetic-financing-final-001

.venv/bin/python3.11 -m blackpod_build_week.harbormaster journal verify \
  --journal-root output/investment-review-example
```

`validate-challenge`, `evaluate-hypothesis` and both `show-*` commands are
read-only. Only the explicit `record-*` commands append. The existing
`append-evaluation` remains a mission evaluation interface and does not accept
these investment review documents. The standalone equivalent is
`python -m blackpod_build_week.decision_journal_cli <command> ...`.
Success emits JSON and exit 0; invalid input, evidence, linkage, conflicts or
persistence return exit 2.

To inspect other comparison cases without writing them, replace `final` with
`missing`, `interim` or `invalidation` in the `evaluate-hypothesis` input path.
The expected summaries are `INCONCLUSIVE`, `PENDING`, and
`INVALIDATION_TRIGGERED`, respectively. The complete recorded example verifies
as 9 events/16 unique evidence blobs; repeating record commands writes nothing.

## Tests, limits and next step

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python3.11 \
  -m unittest discover -s tests -p 'test_investment_review*.py' -q
```

The tests cover contracts, source dependencies, predicates, maturity/missing
data, timing/role/unit guards, immutable plans, typed authority, supersession,
idempotency, source-root protection, tampering, concurrency, interrupted
publication, CLI behavior and old-version compatibility. They are offline
mechanics tests, not investment calibration or performance validation.

Reviewer identity, source roles/groups, economic metric meaning, units and dates
are supplied claims, not independently authenticated or validated economic
truth. A source pointer proves retained-value consistency, not that the value
economically represents its label. Generic retained mission JSON is the only
data input. Release-time availability, sampling independence, interval coverage,
portfolio risk and causal inference require further evidence and review. Local
POSIX storage, bounded files and trusted-root hash limitations still apply.

Recommended next burst: governed investment decision proposals with deterministic
risk-policy checks and explicit human approval bound to exact evidence and policy
versions. Keep execution and capital activation disabled. That burst is not
implemented here; no live policies improve themselves from these outcomes.
