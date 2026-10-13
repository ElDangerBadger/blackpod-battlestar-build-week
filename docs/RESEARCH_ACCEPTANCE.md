# Research validation and evidence gate

Research acceptance describes what retained evidence permits BlackPod to
conclude. It grants neither desk permission to trade, invest, activate capital,
change a policy or promote a strategy. Trading and Investment use a common
record and separate evaluators. CAPITAL_ALLOCATION retains independent
authority. Auto-trading stays OFF.

## Implementation inventory before this checkpoint

The inspected Build Week checkpoint was
`4d864b40b49566ef7b7cd1cc954941ff698d20ce`, with a clean working tree. Inspection
included implementations and their offline tests, not just module names.

| Existing capability | Implemented boundary | Research gap |
| --- | --- | --- |
| Journal v1–v16 | `JournalStore._scan` verifies canonical entries, contiguous predecessor hashes, retained evidence and typed historical-prefix replay. `append` provides locking, immutable publication, conflicts and idempotent recovery. | No common desk research classification. Hash integrity proves retained consistency, not the economic truth of an observation. |
| Investment hypothesis v1 / journal v2 | Human-supplied thesis, causal mechanism, observations, alternatives, horizon, fixed expectation and invalidation checks, review date; values and source timestamps bind to earlier mission evidence. | No authenticated fundamentals, release-time history, valuation adjudication or causal inference. Exact document hashes identify existing revisions; the original schema has no revision counter. |
| Investment challenge/outcome / journal v3 | Declared different reviewer identity, source relationship inventory and exact-deadline predicate comparisons; linked corrections append without deleting originals. | Reviewer identity and independence remain declarations. Passing deadline checks does not establish whole-horizon invalidation coverage, economic truth or an attractive investment price. |
| Investment governance / journal v4 | Versioned deterministic risk checks and human shadow approval, independently source-bound. | `REVIEW_READY` or shadow approval is not research support or execution authority. |
| Trading hypotheses / journal v13 | Original reversal and continuation specifications frozen as untested, untuned proposals. | Specification freeze is not historical preregistration or validated alpha. |
| Historical intake / journal v13–v14 | Exact raw bodies, local GET receipts, calendar coverage, timestamp policy, deterministic source reconstruction, quality-only plans. | Retrospective session-end availability is assumed. Fixed QQQ/SPY universe does not control survivorship; IEX raw prices do not supply a total-return series or consolidated executable liquidity. |
| Shadow producers/evaluation / journal v15 | Deterministic entry/exit intents, next-open arithmetic, FIFO accounting, cash and matched-entry-notional/duration controls, 1×/2×/4× cost stress; final holdout unscored. | Positive descriptive signs are not significance, reliable alpha, executable fills or strategy promotion. Counterfactuals share data and are not independent samples. |
| Continuity/cost/risk / journal v16 | Native retained corporate-action and quote adapters; separate coverage and cost assumptions; explicit simulation-only sizing review. | Real action coverage, opening-quote coverage, cost/capacity calibration and risk review are incomplete. Current raw-price discontinuities defer whole-dataset scoring. |
| Canonical Battlestar | Oracle assessment, Council/Senate attention and review, Governor disposition and Navigator SHADOW intake have typed contracts and retained artifacts. | Attention thresholds, agent confidence and persuasive narratives do not constitute research acceptance. Navigator supports non-executable planning only. |

Representative implementation paths are
`src/blackpod_build_week/contracts/decision_journal.py`,
`decision_journal_store.py`, `investment_hypothesis.py`, `investment_review.py`,
`investment_governance.py`, `trading_research_intake_journal.py`,
`trading_shadow_intents.py`, `trading_shadow_evaluation.py`,
`trading_shadow_review.py` and `trading_shadow_review_journal.py`.
Existing tests cover source pointers, chronological cutoffs, immutable original
plans, rehashed report forgery, installed-code changes, idempotency, concurrency,
safe paths and interrupted publication.

Canonical Battlestar was inspected read-only at
`/Users/nikolai/BlackPod-Versions/blackpod_battlestar`: the Oracle assessment,
trading candidate, Senate deliberation and Governor decision contracts, plus
`blackpod/runtime/oracle_pipeline.py`, `blackpod/advisors/trading_candidate_generator.py`,
`blackpod/governor/governor_decision.py` and `blackpod/runtime/navigator_intake.py`. Its existing
candidate thresholds route attention; no such thresholds enter this gate.
Its implementation, policies and ModelDock routing are unchanged.

## Classifications and precedence

| Classification | Meaning |
| --- | --- |
| `NOT_EVALUABLE` | Required evidence, specification or evaluation prerequisites are missing. |
| `EVALUABLE` | The stated scope can be evaluated, but no sufficiently supported outcome has been established. |
| `INCONCLUSIVE` | An evaluation occurred, but its evidence is insufficient for a reliable conclusion within the requested scope. |
| `SUPPORTED` | The evidence supports the precisely stated scope under the recorded method and limitations. |
| `CONTRADICTED` | Available evidence materially contradicts the precisely stated scope. |
| `INVALID` | An intact submitted evaluation is methodologically compromised or inconsistent with its source-bound evaluation. |

These classifications are derived by the evaluator. A request cannot select its
own classification or upgrade it with a reviewer opinion. Structural corruption,
missing retained bytes, bad hashes, forged links and unsafe paths reject the
write; they do not become apparently valid `INVALID` journal records.

Methodological invalidity takes precedence over a favorable number. Missing
prerequisites cannot become a successful evaluation. A positive result with
inadequate robustness remains unresolved. Contradiction is scoped: a fixed
predicate failure can contradict that expectation without disproving an entire
economic explanation.

Legacy statuses are retained alongside the new research classification. Trading
`DEFER_EVIDENCE_GATES` means missing prerequisites; `SHADOW_SIMULATED` means a
calculation ran, not that its hypothesis passed. Investment `PENDING` preserves
unelapsed horizons. `ALL_EXPECTATIONS_MET_NO_DEADLINE_INVALIDATION` only establishes
the recorded deadline comparisons. Existing governance readiness and approval
states never substitute for a research finding.

## Trading criteria

Admission requires an exact frozen hypothesis, explicit entry and exit rules,
holding horizon, fixed universe, sizing and risk assumptions, complete relevant
cost assumptions, chronology and data continuity. Source reconstruction must
identify the dataset and evaluation method. Retained data timestamps and their
availability policy stay visible; local capture identity is not authentication.

When an admitted simulation exists, assessment uses only measurements the
existing evaluator actually provides: gross/net arithmetic, modeled costs,
turnover/exposure/drawdown where present, closed-trade and fold coverage, sample
size, cash/control differences, cost sensitivity, risk breaches and period
stability. Missing metrics remain null or explicit limitations. Unfilled or
unclosed cohorts and incomparable controls do not supply an edge measurement.

The gate considers market direction, concentration, a small favorable trade
count, execution assumptions, fixed-universe selection, parameter selection,
retrospective specification and shared-data bias. Descriptive comparisons do
not establish statistical independence or out-of-sample efficacy. Current
matched controls are arithmetic counterfactuals at candidate entry times with
matched purchase notional and duration; they do not model a fully capitalized
alternative executable portfolio.

Development and independent final evaluation remain distinct. This checkpoint
does not score the final holdout, tune a parameter, select a winner or change
any frozen hypothesis. It cannot turn the current retrospective history into
point-in-time proof.

## Investment criteria

Investment assessment retains the thesis, mechanism, economic observations,
fundamental evidence, alternatives, horizon, risks, expected outcomes,
invalidation conditions and appropriate review schedule. Where applicable,
valuation and price-sensitive expectations are separate prerequisites; a good
business alone does not establish an attractive security at its evaluated price.

Supporting and contradictory observations must be traceable to exact retained
values, timestamps and evidence hashes. Source-role labels, different paths and
different declared reviewers do not authenticate independent economic evidence.
Economic meaning, units, horizon coverage and causal interpretation remain
explicit limitations when the available sources do not establish them.

A long-horizon thesis remains unresolved while its horizon has not elapsed.
Short-term price appreciation does not establish its mechanism or satisfy a
fundamental expectation. A mature exact-deadline predicate result may be
`SUPPORTED` within the narrow recorded-expectation scope while
`economic_hypothesis_supported` remains false. The same evidence can leave the
broader economic thesis `INCONCLUSIVE`. This distinction is intentional.

## Shared records and replay

Both desks use the existing Decision Journal. A research record links the exact
original hypothesis identity and document hash, evaluation events, cutoff,
method/version, findings, counterevidence, limitations, unknowns and next evidence
requirements. The hypothesis hash is its revision identity. No historical
revision number, confidence probability, expected return or missing outcome is
invented.

Contracts are `blackpod.research_assessment_request.v1`,
`blackpod.research_assessment.v1` and additive journal event v17. Their implementation
is `contracts/research_assessment.py`; `research_acceptance.py` validates shared
links and exact scalar finding pointers, with separate
`research_acceptance_trading.py` and `research_acceptance_investment.py` adapters.
`research_acceptance_journal.py` rebuilds the complete event on append and read.

| Record field | Interpretation |
| --- | --- |
| `request.domain`, `request.hypothesis` | Desk and exact original hypothesis ID, source event, schema and evidence reference. |
| `hypothesis_revision` | Native document schema and SHA-256; an immutable content identity. |
| `request.research_event_id`, `request.evaluation_event_id` | Explicit existing registration/challenge and optional existing native evaluation. |
| `request.methodology_version`, `request.recorded_at`, `evaluation_timestamp`, `request.data_cutoff_at` | Versioned method and separate recording, source-evaluation and evidence-cutoff clocks. |
| `evidence` | Relative identities, byte lengths and SHA-256 hashes for retained source, request and methodology bytes. |
| `classification`, `native_status_mapping`, `claim_scope`, `maturity` | Derived, scoped research conclusion alongside unchanged original statuses; v1 maturity is descriptive only. |
| `findings`, `supporting_findings`, `contradictory_findings` | Deterministic statements with typed effects and exact event/scalar pointers where available; indexes do not invent additional evidence. |
| `limitations`, `unresolved_questions`, `next_evidence_requirements` | What remains unknown and the evidence needed to change the assessment. |
| `governance_status`, `authority`, `auto_trading_enabled` | Research-only status, all four authority flags false and auto-trading false. |

The request cannot supply a conclusion. `economic_hypothesis_supported`,
`source_authentication_verified` and `historical_point_in_time_verified` remain
false for this version, including a narrowly supported predicate case.

Assessment records append under the original research decision ID. Each has an
immutable assessment identity; an exact retry is a no-op and changed content
under that identity conflicts. Corrections use a new assessment ID and an
explicit link to the previous assessment. Previous hypotheses, outcomes, dissent
and classifications remain readable. Evaluations and later assessments refer to
the same history rather than maintaining a second decision database.

Read and append replay the assessment from retained request/source bytes and
earlier verified journal events. The installed methodology is versioned and
retained for reproducibility. Existing v1–v16 semantics and source pins remain
unchanged. A new methodology requires a new version, not silently recomputed
historical conclusions.

Governance remains `RESEARCH_ONLY_NOT_AUTHORIZATION`: authorization, capital activation, execution,
policy change and promotion stay disabled. Realized trade P&L remains null for
these non-executed studies. No assessment installs a budget, ownership book,
order, strategy or automatic capital reallocation.

## Representative offline cases

The example reuses frozen authored fixtures without optimizing prices, rules,
costs, horizons or original hypotheses. All fixture market data and future
investment observations are synthetic; their numbers are software-verification
inputs, not actual security performance.

| Case | Expected research meaning |
| --- | --- |
| Valid specification before evaluation | `EVALUABLE`, unproven. |
| Missing relevant continuity/cost prerequisite | `NOT_EVALUABLE`. |
| Separately retained claimed result disagrees with canonical result | `INVALID`; original result preserved. |
| Continuation fixture fails required cash/control comparison | `CONTRADICTED` within the declared comparison scope. |
| Reversal fixture has positive 1× signs but fails 4× costs | `INCONCLUSIVE` for robust economic support. |
| Mature synthetic investment deadline predicates pass | `SUPPORTED` only for those recorded predicates. |
| Same investment evidence assessed as economic thesis | `INCONCLUSIVE`; no economic-truth claim. |

Each result records its source identity and a traceable explanation. The examples
do not manufacture a supported real-market hypothesis. Their source journal and
raw findings remain unchanged when new assessments append.

## Runnable offline commands

Run from the Build Week checkout. The first command imports the unchanged authored
fixtures into a separate journal and appends seven new assessments. It makes no
data/provider requests. `manifest.json` lists exact source and assessment IDs,
classifications, revision hashes, finding pointers and claim scopes.

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests .venv/bin/python3.11 \
  -m blackpod_build_week.research_acceptance_examples \
  --output-root output/research-acceptance-example

PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests .venv/bin/python3.11 \
  -m blackpod_build_week.research_acceptance_cli verify \
  --journal-root output/research-acceptance-example/journal

PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests .venv/bin/python3.11 \
  -m blackpod_build_week.research_acceptance_cli assess \
  --request output/research-acceptance-example/input/positive-insufficient-robustness.request.json \
  --journal-root output/research-acceptance-example/journal \
  --output output/research-acceptance-example/reports/reversal-assessment.v1.json

PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests .venv/bin/python3.11 \
  -m blackpod_build_week.research_acceptance_cli record \
  --request output/research-acceptance-example/input/positive-insufficient-robustness.request.json \
  --journal-root output/research-acceptance-example/journal
```

The last command is an identical retry of the example assessment and writes no
new event. `assess` writes an immutable export outside the journal; it does not
append history. `show --event-id` reads one exact retained assessment. `verify`
checks the complete mixed-version chain, not only a report file.

To prepare another request, select a retained registration and optionally its
exact evaluation. Explicit clocks and scope are required; the command does not
invent a current cutoff, evidence, hypothesis or conclusion:

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests .venv/bin/python3.11 \
  -m blackpod_build_week.research_acceptance_cli prepare \
  --journal-root /absolute/path/to/verified/journal \
  --research-event-id journal-event-REPLACE_WITH_RETAINED_REGISTRATION_HASH \
  --evaluation-event-id journal-event-REPLACE_WITH_RETAINED_EVALUATION_HASH \
  --assessment-id explicit-new-assessment-id \
  --recorded-at 2026-10-13T00:00:00Z \
  --data-cutoff-at 2026-10-12T23:00:00Z \
  --scope EXPLORATORY_RESEARCH \
  --output-directory output/research-acceptance-prepared
```

Replace placeholder IDs and clocks with the selected existing history. For
pre-evaluation admission omit `--evaluation-event-id`. Investment scopes also
include `DECLARED_DEADLINE_PREDICATES`; `ECONOMIC_VALIDATION` preserves the
additional unresolved economic-evidence prerequisites for both desks.

An optional `--candidate-result-file` retains a separately supplied native result
dictionary for consistency review. It cannot replace a journal evaluation or
choose its classification. The exported request/evidence directory becomes the
explicit `--evidence-root` for `assess` or `record` until those bytes are retained
in the journal. Corrections use a new assessment ID and
`--supersedes-event-id`; they must preserve the domain, hypothesis revision and
scope and cannot move the recording clock or cutoff backwards.

Success returns exit 0 and JSON. Invalid input, evidence, scope, identity,
linkage or publication returns exit 2. No CLI command starts inference, a stage
workflow, a broker session or an execution worker.

Focused example tests:

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests .venv/bin/python3.11 \
  -m unittest test_research_acceptance_examples -q
```

The checkpoint validation report records actual final results and the selected
offline regression commands; software test counts are not performance metrics.

## Real-data limits and readiness

The retained real dataset contains 760 sessions per QQQ/SPY symbol. The existing
real studies correctly deferred: corporate-action effective-date coverage is
unverified, raw-price discontinuities are present, quote evidence covers one
opening minute per symbol rather than the full history, cost assumptions are
absent and sizing approval remains proposed. They produced no intents, fills or
scores. This checkpoint reuses that history and adds no data/provider requests.

Trading can reproduce deterministic evaluations of fully specified authored
fixtures. It cannot yet demonstrate a credible economically robust evaluation
on the retained real history. The smallest next evidence milestone is a governed
event-aware eligibility/continuity policy and training-only cost/capacity
calibration, followed by explicit simulation-risk review. Those items require
independently justified evidence, not an exception to this gate.

Investment can assess specification quality and exact retained deadline
evidence without treating it as realized performance. Broader evidentiary
support still requires economic observation semantics, valuation where relevant,
independent fundamental/statistical evidence and horizon monitoring coverage.
The smallest next milestone is a source-bound investment evidence adapter with
explicit metric meaning, release time and coverage, rather than another agent.

The shared journal already links outcomes without rewriting decisions; this
checkpoint supplies the common research classification link. It still relies
on trusted local storage and local source declarations. Passing deterministic
software tests does not demonstrate investment performance.

Stop at this checkpoint. Final holdout opening, strategy promotion, execution,
budget activation, capital transfer, automatic rebalancing, new Oracle narratives,
ModelDock changes, UI expansion and desktop packaging remain outside scope.
