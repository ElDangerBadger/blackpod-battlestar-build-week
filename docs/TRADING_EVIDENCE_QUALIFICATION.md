# Governed Trading Desk evidence qualification

This checkpoint qualifies the evidence and design for a later shadow research
evaluation. It does not establish profitable trading, calculate new strategy
returns, open the final holdout, install a policy or grant either desk authority.
Auto-trading remains OFF. Galactica trading rules are not used.

Qualification uses the existing Decision Journal and exact frozen trading
hypotheses, data-quality plans and native evidence. Investment authority,
CAPITAL_ALLOCATION authority, mission schemas, Navigator behavior, ModelDock
routing and recorded desk budgets remain unchanged.

## Inspected starting point

The inspected checkpoint was `3f4a912`, after the passive two-desk research
acceptance gate. The working tree was clean. The relevant implementations and
tests were inspected before this additive work.

| Existing implementation | Reusable capability | Qualification gap |
| --- | --- | --- |
| `trading_research_intake_journal.py`, `trading_research_journal.py` | Exact frozen hypothesis/catalog, governed raw history, original plan and source identities. | Existing quality-only plans do not declare event-aware eligibility or training-calibrated costs. |
| `trading_continuity_intake.py` | Retained native action/receipt pagination, effective-date mapping and explicit missing coverage. | A process-date query does not establish complete effective-date coverage. The old gate rejects the entire dataset if any discontinuity exists. |
| `trading_cost_intake.py` | Strict native quote fields, nanosecond ordering, pagination, opening-minute admission, hashes and separate assumptions. | The old adapter requires complete full-dataset coverage and uses whole-source spread bounds. It is not a training-only calibrator. |
| `trading_shadow_risk_review.py` | Explicit simulation cash, sizing and deterministic feasibility/risk checks. | Actual retained reviews are proposed. Known-close feasibility does not establish executable capacity or authenticated human approval. |
| `trading_shadow_review.py`, `trading_shadow_review_journal.py` | Source-bound v16 study and calculation replay with immutable original risk and separate internal projections. | Qualification cannot force these original gates to pass or reinterpret their reports. |
| `research_acceptance*.py` | Exact revision links, scoped research classifications, source-bound findings and explicit economic limitations. | Evidence/design readiness does not satisfy the additional prerequisites for economic support. |
| `decision_journal_store.py` | Immutable entries, retained evidence, hash chain, safe publication, idempotent retry, conflicts and recovery. | New qualification records need additive replay and linkage, rather than a second history system. |

The v15, v16 and v17 calculation/source pins remain unchanged. In particular,
historical v16 `DEFER_EVIDENCE_GATES` reports continue to defer when replayed.
New qualification findings describe a new, explicitly frozen design and never
override an old report or substitute `eligible=true` into the old gate.

## The real-data boundary

The retained QQQ/SPY dataset has 760 returned sessions. Its original development
protocol is:

| Partition | Original indices |
| --- | --- |
| TRAIN | 0–227 |
| VALIDATION | 231–379 |
| TEST | 383–607 |
| Final holdout | 611–759 |

The gaps preserve the original three-session embargo. The only previously
captured actual opening quotes are from session **759**, inside the final
holdout. Those quotes cannot calibrate TRAIN costs or establish development
coverage. A recent quote is not evidence for an earlier training window.

Actual action evidence contains mapped dividend discontinuities, with
effective-date coverage unresolved. Actual fee/slippage assumptions are absent;
the recorded USD 10,000 cash / USD 1,000 per-symbol risk declaration is
`PROPOSED`. None of these missing prerequisites becomes an assumed approval,
zero-cost model, complete series or newly observed execution.

The correct real-history qualification stays deferred until the required
evidence and governance declarations exist. Previously retained provider bodies,
receipt bytes, hypothesis definitions, session indices, prices and original
reports remain intact.

## Frozen policy before calibration

A qualification policy binds an exact original base-plan event and hypothesis
revision, returned-session calendar, dataset, selected continuity/cost/risk
events and separately retained support. Before calibration it declares the
training quote chains, cost and capacity assumptions, event suspension rules,
partition boundaries and later uncertainty/stability protocol.

`PROPOSED` is inactive. A locally declared
`REVIEWED_FOR_SHADOW_QUALIFICATION` status applies only to this research
qualification design; it does not authenticate a human reviewer or approve an
order, live strategy, desk budget, transfer or rebalance. Missing review,
assumptions, coverage or design remains explicit.

The original hypothesis's entry rule, lookback, holding horizon and falsification
conditions are preserved. A new design must not be selected by observing which
parameters make historical returns attractive. Its freeze means **before this
qualification/calibration procedure**, not prospective blind historical
preregistration. Existing retrospective availability and specification limitations
remain visible.

The exact new contracts are
`blackpod.trading_evidence_qualification_policy.v1`,
`blackpod.trading_training_assumptions.v1` and
`blackpod.trading_evidence_qualification_request.v1`, implemented in
`contracts/trading_evidence_qualification.py`. The result is
`blackpod.trading_evidence_qualification.v1`. Journal event v18 adds policy
registration and linked qualification; it leaves earlier event vocabularies
intact.

| Policy/input fields | Purpose |
| --- | --- |
| Original plan event and plan/dataset/hypothesis references | Preserve exact frozen scope, prices, session indices and decision identity. |
| Continuity/cost/risk event IDs | Select earlier verified native evidence and simulation-only risk declarations. |
| `training_quote_chains` | Fold-specific forward native page/receipt chains; each body and receipt is hash bound. |
| `training_cost_assumptions_evidence` | Separate typed declaration of slippage, proportional/per-fill fees and daily-volume participation, with retained origins. |
| `continuity_policy`, `cost_policy` | Fixed raw-price boundary suspension and per-fold TRAIN-only maximum spread, with no adjustment or clipping. |
| `uncertainty_protocol` | Explicit future method, dependence unit, sample/stability requirements, resampling configuration, stresses and withheld-holdout boundary. |
| `supporting_evidence`, reviewer and notes | Retained support and declared local reviewer identity; not authenticated approval. |
| Policy/request supersession links | New linked records for changes or later evidence; existing bytes remain immutable. |

The qualification request selects the exact registered policy and supplies a
recording time and data cutoff. The result distinguishes
`READY_FOR_QUALIFIED_STUDY_DESIGN` from `DEFER_EVIDENCE_QUALIFICATION`, with typed
continuity, training calibration, risk and future-protocol findings. Readiness
means scoped design prerequisites passed; it is not a research `SUPPORTED`
classification, a simulation result or a permission.

## Event-aware eligibility

Eligibility is determined before generating signals. For each prospective
hypothesis episode the design considers its original feature lookback, sizing
observation, entry, holding interval, exit and matched-control universe.

A known action becomes effective at the mapped returned New York session open.
A feature interval spanning that discontinuity is suspended; so are sizing,
entry or holding/exit intervals that cross it. Continuity checks must also cover
every symbol contributing to the equal-weight matched control: a clean candidate
symbol alone does not establish a comparable control.

An unknown effective date cannot be placed arbitrarily on the first returned
session. It defers affected-symbol windows until its timing can be justified.
Incomplete effective-date coverage remains a prerequisite rather than being
inferred from an empty process-date response.

Every mask row retains the original fold, source-session and symbol identities,
the reason for suspension and the event evidence. Suspended observations remain
in the retained source; prices are not adjusted, reindexed or deleted. This
qualification does not reconnect execution or silently remove difficult periods
from the original research history.

## Training-only cost and capacity evidence

Each training quote chain belongs to one exact original fold. Its query, native
timestamps and admitted opening-minute observations must fall inside that
fold's TRAIN range. VALIDATION, TEST and final-holdout quotes do not become
calibration input. Native pagination must complete; missing symbol/session
coverage, unavailable responses and out-of-training rows remain explicit.

Observed spreads and supplied slippage/fee assumptions have distinct origins.
The calibrator retains per-symbol bounds and coverage, and never clips a large
spread to obtain eligibility. A quoted spread does not measure order slippage,
commissions, fees or realized execution cost. Absence does not supply zero.

Capacity is an explicitly scoped historical proxy. Daily volume and declared
participation limits do not establish opening liquidity, accessible depth,
market impact, fill probability or broker buying power. Known-close sizing
feasibility remains separate from executable order admission. Real cost and
capacity assumptions require independently justified support and an explicit
shadow review.
Training volumes retain their raw units; corporate-action comparability and
economic applicability are not independently established by this proxy.

The qualifying sample is the intersection of comparable continuity windows,
positive feasible known-close quantities and the declared training-volume
capacity proxy. Minimum sample requirements count distinct jointly eligible
source-session dates per fold, not symbol rows or the unmasked TEST length.
Enough individually eligible continuity and sizing rows do not suffice if their
usable windows do not overlap. No jointly eligible window leaves the design
deferred; an insufficient sample never becomes sufficient by lowering its
already declared minimum.

## Later uncertainty and stability design

The policy freezes a proposed evaluation method before the new calibration.
The method identifies a paired candidate-versus-control net metric, dependence
unit, minimum sample requirements, interval procedure and across-period
stability criteria within the existing development TEST ranges.

Returned-session blocks encode a proposed treatment of dependence;
correlated symbols and overlapping trades do not become independent votes.
The original TEST fold boundaries and episode suspension rules remain explicit.
Additional subperiod splits and the statistical adequacy of this treatment are
unestablished; no interval estimator is implemented in this checkpoint.
Cost stresses and comparison requirements stay visible. Multiple trials,
universe selection, retrospective specification and source availability remain
limitations.

This checkpoint records the protocol only. It calculates **no confidence
interval, p-value, statistical significance, new strategy return or economic
support**. Later outcome/evaluation records must append against this exact
frozen protocol and qualification result. They cannot change original
thresholds, omit unfavorable trials, score the final holdout or rewrite this
policy after seeing performance.

The fixture declares block length 2 sessions, 100 replications, seed 7, nominal
confidence level 0.95, at least 8 evaluation sessions, one development fold and
required fold fraction 1. These are openly authored software-verification
parameters, not validated choices for real data. The confidence level describes
a proposed future interval procedure; it is not a confidence probability for
either hypothesis or an estimated chance of profit. The result's
`uncertainty_status=FROZEN_NOT_EVALUATED` and `uncertainty_computed=false` preserve
that distinction.

## Shared journal and reproducibility

Policy registration and qualification assessment append in the existing
Decision Journal. They identify the original catalog/hypothesis and base plan,
retain exact native source and support bytes, and keep method/version and cutoff
separate from source timestamps.

Exact retries reconstruct their original historical prefix and write nothing.
Changed content under the same identity conflicts. Subsequent qualification
assessments use new IDs and explicit links; old policies, dissent, evidence,
deferred reports and outcomes remain readable. Later strategy evaluations use
separate linked events rather than mutating qualification records.

Reads and locked appends replay the new records from their retained inputs.
Installed new methodology files are pinned independently of existing v15–v17
sources. Source authentication, reviewer authentication and historical
point-in-time availability remain unverified. All execution/capital/policy
authority flags stay false.

## Controlled examples

The runnable example reuses the existing fourteen-event v16 fixture unchanged:
its frozen hypotheses, 40 authored sessions, 80 authored quotes, action evidence,
toy assumptions and shadow sizing. It creates new **authored** TRAIN-only quote
subsets and receipt declarations, with 12 original TRAIN sessions / 24 symbol
quotes. They are not new provider captures or actual security evidence.

Representative cases include a complete declared reversal design, a continuation
design with an insufficient joint sample, an inactive proposed policy, and quote
evidence containing final-holdout observations. Both fixed hypotheses keep the
same minimum of eight dates: the original one-session reversal horizon admits
eight distinct joint dates, while the original three-session continuation horizon
admits six and defers. The source prices, hypotheses and protocol are unchanged;
this is qualification feasibility, not a strategy ranking or winner selection.
A clean fixture can qualify for a later shadow design while economic support
and all operational authority remain false. Proposed, insufficient or disallowed
evidence remains deferred. Separate deterministic tests exercise action-boundary
masks and unknown dates.

The example manifest records source preservation, policy and assessment IDs,
qualifying/deferred reasons, evidence hashes, and disabled operational actions.
All fixture assertions and timestamps are explicitly synthetic. Passing these
tests establishes qualification mechanics, not profitable trading.

The original fourteen events include their unchanged old v16 fixture
calculations. The new eight v18 events add four policies and four qualifications;
they calculate no new strategy return and do not reinterpret old performance.

## Runnable offline examples

Run from this checkout. The generator creates a separate mixed-version journal,
retains new authored TRAIN evidence and writes strict policy/request files plus
four result reports. `manifest.json` lists the exact recorded IDs and hypotheses.

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests .venv/bin/python3.11 \
  -m blackpod_build_week.trading_evidence_qualification_example \
  --output-root output/trading-evidence-qualification-example

PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests .venv/bin/python3.11 \
  -m blackpod_build_week.trading_evidence_qualification_cli verify \
  --journal-root output/trading-evidence-qualification-example/journal

PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests .venv/bin/python3.11 \
  -m blackpod_build_week.trading_evidence_qualification_cli assess \
  --request output/trading-evidence-qualification-example/input/clean-declared-design.request.json \
  --journal-root output/trading-evidence-qualification-example/journal \
  --output output/trading-evidence-qualification-example/reports/clean-reassessment.json

PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests .venv/bin/python3.11 \
  -m blackpod_build_week.trading_evidence_qualification_cli record \
  --request output/trading-evidence-qualification-example/input/clean-declared-design.request.json \
  --journal-root output/trading-evidence-qualification-example/journal
```

The final command is an identical retry and writes no new journal event. `assess`
exports a result without appending. `show --event-id` requires one exact retained
policy or qualification ID; it does not select an arbitrary latest result.

For another design, `prepare` requires explicit base-plan/source event IDs,
policy identity, recording clock, reviewer declaration, review notes and an
`--inputs` JSON file containing exactly `supporting_evidence`,
`training_quote_chains`, `training_cost_assumptions_evidence` and
`uncertainty_protocol`. Its default status is `PROPOSED`. Preparation writes a
strict immutable policy export and performs no calibration. `register --policy`
explicitly appends the freeze; separately located, unretained leaf evidence
requires an explicit `--evidence-root`. Neither command acquires market data or
invents a missing assumption. A change uses a new identity and an explicit
supersession link.

Only explicit `register` and `record` append journal history. Inputs, reports
and new evidence are separate from the journal and canonical source storage.
Success returns JSON and exit 0; invalid inputs, identity conflicts, unsafe paths,
missing/altered evidence or replay failures return exit 2. Deferred qualification
is an auditable result, not an opportunity to bypass its reasons.

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests .venv/bin/python3.11 \
  -m unittest test_trading_evidence_qualification_example -q
```

The checkpoint validation report records the actual final focused/regression
results and real-history qualification. No unrestricted provider/broker test
discovery is implied by the offline commands.

## Readiness and next milestone

This foundation can explain whether a precisely declared shadow research design
has sufficient scoped evidence to proceed to its next evaluation stage. It
cannot establish economic efficacy on the current real history: training
quotes, relevant cost assumptions, independent effective-date coverage and
reviewed simulation sizing are still needed.

The next milestone is to acquire or retain the missing development/TRAIN evidence
under the frozen policy, obtain an explicit review of its assumptions and risk,
then implement the separately governed uncertainty/stability evaluator. That
evaluator must preserve declared partitions and masked-episode accounting,
demonstrate deterministic results and append its outcomes. No production
promotion or automated allocation follows from qualification alone.
