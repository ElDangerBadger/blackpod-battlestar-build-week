# Research validation and evidence gate

## Consolidation checkpoint after journal v24

The completion/validation sprint starts at
`9f221a6c36f532dfb084a53a078af600ba07840c`, with a clean working tree. It
consolidates the existing architecture rather than implementing the previously
recommended coverage-admission burst. That burst remains outstanding. The
[validation report](RESEARCH_ACCEPTANCE_VALIDATION.md) separates this sprint's
executed checks and retained-data baseline from the original v17 checkpoint.

| Component | Actual implementation and validation boundary | Remaining limitation |
| --- | --- | --- |
| Acquisition and normalization | `trading_historical_intake.py` binds retained bars/calendar responses; `train_market_capture.py`, `train_market_export.py` and the segmented consumer retain scoped TRAIN quote chains. The retained QQQ/SPY acquisition completed 228 windows and 456 symbol/session pairs. | Complete retrieval does not prove action coverage, point-in-time vintages, quote-size normalization, costs or executable capacity. |
| Forecasting and historical research | `forecast_producer_export.py`, `shadow_quantitative_producer.py`, `trading_shadow_intents.py` and `trading_shadow_evaluation.py` retain explicit horizons, original hypotheses, reproducible arithmetic and controls. | Retained current forecast records have no subsequent governed outcome measurements. Real trading hypotheses remain deferred; no predictive edge is established. |
| Brigade and Senate | `shadow_brigade_analysis.py`, structured response contracts and `brigade_shadow_transport.py` preserve advisory opinions/dissent. `council_adapter.py` delegates the canonical Council/Senate boundary. | Structured validity is not independent corroboration or semantic truth. The separate Brigade consistency diagnostic is not implemented. |
| Microcap Sentry | `sentry_reader.py`, `sentry_history_cache.py`, `sentry_history_recovery.py`, `sentry_research_reader.py` and `sentry_scan_reader.py` validate retained snapshots, recovery evidence and frozen research. | The legacy observation archive is synthetic; the real universe is not a verified microcap universe. The frozen V2 study selected no successful policy and completed zero prospective sessions. Reader readiness is not scanner or collector health. |
| Oracle | `oracle_adapter.py` delegates canonical observations; `oracle_enrichment_workflow.py` retains optional narration; `oracle_market_brief.py` and `oracle_brief_reader.py` prepare/validate the separate source-bound supplement. | Finite deterministic guards cannot establish arbitrary prose entailment, causality or a forecast. Missing MA, named-sector or historical-comparison evidence cannot be invented. |
| ModelDock | `modeldock_client.py` validates requests/responses, deadlines, structured output, provenance and safe failures. Existing routing remains appliance-owned. | Offline transport tests do not establish current service health or narrative accuracy. No inference is run by this sprint. |
| Navigator | `navigator_adapter.py` checks mission/operator lineage and native SHADOW outputs; reference readers display explicitly selected captured charts. | A SHADOW handoff is not order authorization. The separate legacy PAPER controller remains OFF and is not the replacement Trading Desk strategy. |
| Decision Journal | `decision_journal_store.py` verifies retained evidence and complete mixed-version history; `decision_journal_batch.py` preflights locked immutable suffix publication. Versions v1–v24 remain supported. | Integrity is local retained-byte reproducibility, not authenticated source truth. Large quote-history replay remains expensive; raw local artifacts are not Git backups. |
| Investment Desk | `investment_hypothesis.py`, `investment_review.py`, `investment_governance.py` and `investment_approval.py` retain thesis/expectations, challenge, deadline evidence and portfolio-risk review. | Economic meanings, valuation, independent evidence and full-horizon monitoring are not established by generic scalar predicates. Review identities remain declarations. |
| Trading Desk | Independent frozen hypotheses, next-open shadow producers, matched-entry-notional/duration controls, cost stresses, native qualification and v24 overlay witnesses are implemented. | All 450 selected real opportunities remain deferred. Existing Galactica execution logic is not reused as the replacement research strategy. |
| Capital Allocation | `CapitalPolicyProposal` in `contracts/decision_journal.py` fixes 50%/50%, `PROPOSED`, `INITIAL_ALLOCATION_ONLY`, disabled activation/transfers/reallocation and explicit authorization for later changes. `paper_test_budget.py` retains the separate inactive 25%-of-captured-equity test allocation. | No active allocator, autonomous redistribution or operational desk budget is introduced. Neither research desk can change capital authorization. |
| Research acceptance | Existing v17 contracts, separate desk evaluators and exact-source journal replay already implement all six classifications. | Original v1 presents one classification and a performed flag. The additive state view separates eligibility, integrity and outcome without rewriting that record. |

The Captain's Cabin remains a reader. Opening, refreshing or publishing research
does not start a mission, invoke ModelDock, install ownership or submit an order.
Canonical mission workflows and sibling repositories are unchanged. Historical
demo/replay commands and the OFF legacy executor are retained compatibility
interfaces, not competing new research engines.

Shared evidence does not confer shared decision authority. Trading and
Investment records retain their originating domain, exact hypothesis revision,
method and horizon. Comparisons concern coverage and evidence integrity;
deadline predicates are not pooled with simulated trade returns as one accuracy
score. CAPITAL_ALLOCATION remains separate oversight.

No new journal version, product agent, dependency, live hook, capital policy or
execution path is needed for this consolidation.

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

## Separate eligibility, integrity and outcome

`contracts/research_acceptance_state.py` and `research_acceptance_state.py`
provide `blackpod.research_acceptance_state.v1`, a read-only projection of one
exact verified v17 assessment. The existing journal format and all five frozen
acceptance methods remain unchanged. This is not a new gate or an evaluation
written back over the original record.

| State field | Meaning |
| --- | --- |
| `eligibility` | `EVALUABLE` or `NOT_EVALUABLE`, derived from the original method's scope and source-bound prerequisites. A performed native calculation is not sufficient. |
| `integrity` | `VALID` or `INVALID` for the selected source-consistency review; `VALID` does not mean authenticated or economically true. Corrupt source history rejects before projection. |
| `outcome` | Null until an eligible scoped assessment has an outcome; otherwise `SUPPORTED`, `CONTRADICTED` or `INCONCLUSIVE`. |
| `original_classification` | The original v17 value, retained verbatim even when the new view separates its eligibility and outcome differently. |
| `classification` | Derived six-way presentation with integrity failure first, missing prerequisites next, then outcome or pre-outcome eligibility. |
| `evaluation_performed`, `native_evaluation_performed` | Scoped outcome assessment versus the original calculation's performed flag. They need not be identical. |

The exact strict original assessment and hypothesis remain embedded, preserving
creation clock, statement, horizon, thresholds, scope, evidence, evaluation
clock, methodology and provenance. Trading scope binds its retained original
research plan; it cannot be replaced by a different symbol list. Source and
projection-method hashes identify the calculation. Both broad
`ECONOMIC_VALIDATION` scopes remain not evaluable under the original v1 evidence
limits, even if descriptive arithmetic ran. Narrow Investment deadline support
is not economic-thesis support. All authority flags remain false.

For the existing authored example's exact pre-evaluation assessment:

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests .venv/bin/python3.11 \
  -m blackpod_build_week.research_acceptance_cli state \
  --journal-root output/research-acceptance-example-001/journal \
  --event-id journal-event-7dcbff71280107c9e2c24ea766ae545e89d3e087847bd5c72c927e4149844daa \
  --output output/research-validation-completion-001/fixture-state.v1.json
```

Omitting `--output` prints the same state. The CLI verifies complete history,
then the projector replays the exact assessment and its prefix. The projector
alone does not attest to unrelated later history. No command appends an event.

## Reproducible research baseline

`research_baseline.py` consumes the existing journal and domain evaluators. It
does not introduce another evaluator or acceptance policy. The explicit offline
`research_baseline_cli` exports a content-identified report with a fixed `as_of`
clock, bound source identities and calculation provenance. Its public path uses
full semantic journal replay; the pure function labels its narrower checks and
does not claim whole-history verification.

Reports preserve desk, native methodology, horizon, evidence scope and original
classification. They inventory hypotheses, dataset provenance, assessments and
supersession, native measurements, forecast reviews and later evidence
diagnostics. Repeated forecast source bytes remain distinct desk/intake reviews;
unique raw-source counts are separate from review counts. Neither count is an
independent prediction sample. Existing simulated cash/control comparisons stay
per native fold and cost stress rather than becoming a cross-desk return.

The caller must explicitly declare one of four cohorts:

- `RECORDED_HISTORICAL_HYPOTHESES`
- `RECONSTRUCTED_HISTORICAL_RESEARCH`
- `PROSPECTIVE_SHADOW_RESEARCH`
- `SYNTHETIC_FIXTURE_ONLY`

Known incompatible synthetic or retrospective inputs reject. A prospective
label alone does not authenticate precommitment, publication-time data or an
independent prospective sample. A report does not transform later-captured
history into historical predictions. The report clock must cover every selected
record; it does not backdate those records or manufacture outcome observations.

Run against the retained latest Trading history on this machine:

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python3.11 \
  -m blackpod_build_week.research_baseline_cli \
  --journal-root output/reconciled-shadow-qualification-real-001/journal \
  --cohort RECONSTRUCTED_HISTORICAL_RESEARCH \
  --as-of 2026-10-14T06:00:00Z \
  --output output/research-validation-completion-001/current-trading-baseline.v1.json
```

This is an expensive full retained-history verification, not a health-check
poll. Use explicitly selected smaller fixture histories during development.
All exports are immutable and use existing source/runtime/path protections.
Exact retries retain the same report bytes. The ignored local journals and
reports are not supplied by a Git push.

Directional accuracy, precision/recall, false-positive rates, forecast error,
calibration, regime performance and predictive effectiveness remain null with
explicit reason codes when appropriate labels, linked outcomes or independent
samples do not exist. Elapsed targets are not measured outcomes. Existing
native descriptive measurements are retained where available; synthetic
measurements demonstrate software behavior only. Sustained prospective work
still needs frozen hypotheses/methods, accountable source/recording clocks,
subsequent governed observations and review of evidence prerequisites. It does
not need a new hierarchy of agents.

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

## Original v17 real-data limits and readiness

At the original v17 checkpoint the retained real dataset contained 760 sessions
per QQQ/SPY symbol. Those studies correctly deferred: corporate-action
effective-date coverage was unverified, raw-price discontinuities were present,
quotes covered one opening minute per symbol, cost assumptions were absent and
sizing approval remained proposed. They produced no intents, fills or scores.
Later bounded TRAIN acquisition completed the requested 456 symbol/session
pairs; see the consolidation inventory above and the
[segmented qualification validation](SEGMENTED_EVIDENCE_QUALIFICATION_VALIDATION.md).
Retrieval completion does not close the remaining native gates. The newer v24
overlay retains all 450 opportunities as deferred, without changing the old
v17 result or claiming real performance.

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
