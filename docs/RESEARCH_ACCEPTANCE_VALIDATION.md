# Research acceptance checkpoint validation

Validated on 2026-10-12 America/Los_Angeles (2026-10-13 UTC). Base checkpoint:
`4d864b40b49566ef7b7cd1cc954941ff698d20ce`. Dedicated development branch:
`codex/research-acceptance-gate`. The operator subsequently authorized merge
and push after completion; publication is reported with the final commit ID.

The [acceptance design and usage](RESEARCH_ACCEPTANCE.md) includes the inspected
implementation inventory, gaps, contract fields, domain-specific criteria,
native-status mapping, append-only integration, representative cases and
remaining methodological limits. This report records software verification;
passing tests do not demonstrate trading or investment effectiveness.

## Files changed

Three existing files receive additive changes only:

- `README.md`: link to the acceptance documentation.
- `src/blackpod_build_week/contracts/decision_journal.py`: additive v17 dispatch.
- `src/blackpod_build_week/decision_journal_store.py`: additive acceptance replay dispatch.

New files:

- `src/blackpod_build_week/contracts/research_assessment.py`
- `src/blackpod_build_week/research_acceptance.py`
- `src/blackpod_build_week/research_acceptance_trading.py`
- `src/blackpod_build_week/research_acceptance_investment.py`
- `src/blackpod_build_week/research_acceptance_journal.py`
- `src/blackpod_build_week/research_acceptance_cli.py`
- `src/blackpod_build_week/research_acceptance_examples.py`
- `tests/test_research_assessment_contracts.py`
- `tests/test_research_acceptance_trading.py`
- `tests/test_research_acceptance_investment.py`
- `tests/test_research_acceptance_journal.py`
- `tests/test_research_acceptance_cli.py`
- `tests/test_research_acceptance_examples.py`
- `docs/RESEARCH_ACCEPTANCE.md`
- `docs/RESEARCH_ACCEPTANCE_VALIDATION.md`

A SHA-256 baseline covering 724 previously tracked files confirmed that only
the three stated existing files changed. Frozen calculations, hypotheses,
fixtures, mission schemas, ModelDock configuration/routing and execution
policies remain byte-identical. No dependencies were added.

## New test results

All **123 new tests passed**, including strict booleans/fields/versions,
source/cutoff/pointer binding, native status preservation, scoped classifications,
candidate-result invalidity, retained-only replay, idempotency after later
history, supersession restrictions, source corruption rejection, interrupted
entry publication and safe CLI paths.

Exact commands and final results:

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests .venv/bin/python3.11 \
  -m unittest test_research_acceptance_trading -q
# 26 tests, OK (11.333s)

PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests .venv/bin/python3.11 \
  -m unittest test_research_acceptance_investment -q
# 31 tests, OK (3.067s)

PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests .venv/bin/python3.11 \
  -m unittest test_research_assessment_contracts test_research_acceptance_cli -q
# 30 tests, OK (66.450s)

PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests .venv/bin/python3.11 \
  -m unittest test_research_acceptance_journal -q
# 17 tests, OK (107.855s)

PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests .venv/bin/python3.11 \
  -m unittest test_research_acceptance_examples -q
# 19 tests, OK (362.667s)
```

Times include varying contention from parallel regression jobs and full retained
history replay. Intermediate development failures were corrected before these
final passes: a v14 quality report lacks a strategy status; file protection must
receive source directories; frozen base documents reject attribute assignment;
catalog clocks must remain identical to their frozen hypotheses; example
manifest exports require their own safe output placement. One intermediate
example run correctly rejected a methodology hash changed during development;
the final run used stable pinned source files.

## Existing regression results

All **2,525 selected safe offline regressions passed**; total checkpoint coverage
is **2,648 tests**. No unrestricted live/integration discovery was performed.
Each following module list was run with this exact prefix and suffix:

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests .venv/bin/python3.11 -m unittest MODULES -q
```

| Group | Tests | Result |
| --- | ---: | --- |
| Fill-lot and fee accounting | 164 | PASS |
| Journal, investment hypothesis and review | 249 | PASS |
| Investment governance | 125 | PASS |
| Paper reconciliation and runtime safeguards | 249 | PASS |
| Mission workflows and ModelDock | 172 | PASS |
| Shadow desk candidate review | 233 | PASS |
| Forecast intake and Brigade shadow review | 218 | PASS |
| Governed forecast producer export | 128 | PASS |
| Structured Brigade responses | 144 | PASS |
| Trading research foundation | 164 | PASS |
| Trading hypotheses and historical intake | 189 | PASS |
| Shadow intents and counterfactual evaluation | 221 | PASS |
| Continuity/cost adapters and sizing review | 269 | PASS |

Exact module selections, one command per line:

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests .venv/bin/python3.11 -m unittest test_trading_accounting_contracts test_paper_activity_import test_trading_accounting_engine test_trading_accounting_store test_trading_accounting_cli test_trading_accounting_examples -q
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests .venv/bin/python3.11 -m unittest test_decision_journal_contracts test_decision_journal_projection test_decision_journal_store test_decision_journal_cli test_investment_hypothesis_contracts test_investment_hypothesis_sources test_investment_hypothesis_store test_investment_hypothesis_examples test_investment_hypothesis_cli test_investment_review_contracts test_investment_review_engine test_investment_review_store test_investment_review_cli -q
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests .venv/bin/python3.11 -m unittest test_investment_governance_contracts test_investment_governance_engine test_investment_approval test_investment_governance_store test_investment_governance_examples test_investment_governance_cli -q
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests .venv/bin/python3.11 -m unittest test_trading_reconciliation_contracts test_trading_reconciliation_engine test_trading_reconciliation_store test_trading_receipts test_trading_reconciliation_cli test_paper_account_safety test_paper_order_capture test_trading_reconciliation_examples test_auto_trading_runtime test_galactica_trading_adapter test_trading_automation test_paper_account_probe -q
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests .venv/bin/python3.11 -m unittest test_contracts test_mission_store test_mission_transitions test_mission_presentation test_cli_help test_navigator_adapter test_operator_adapter test_modeldock_config test_modeldock_client test_modeldock_preflight test_modeldock_delivery -q
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests .venv/bin/python3.11 -m unittest test_shadow_native_analysis test_desk_candidate_review_contracts test_desk_candidate_review_engine test_shadow_galactica_analysis test_desk_candidate_review_store test_desk_candidate_review_cli test_desk_review_sources test_desk_candidate_review_examples -q
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests .venv/bin/python3.11 -m unittest test_forecast_intake_contracts test_forecast_intake_engine test_shadow_brigade_analysis test_forecast_brigade_journal_contracts test_forecast_brigade_store test_brigade_shadow_transport test_forecast_brigade_cli test_forecast_brigade_examples -q
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests .venv/bin/python3.11 -m unittest test_shadow_quantitative_producer test_forecast_producer_contracts test_forecast_producer_export test_forecast_producer_examples test_forecast_producer_journal test_forecast_producer_cli -q
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests .venv/bin/python3.11 -m unittest test_brigade_response_contracts test_brigade_structured_analysis test_brigade_structured_journal test_brigade_structured_transport test_brigade_structured_examples test_brigade_structured_cli -q
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests .venv/bin/python3.11 -m unittest test_trading_research_contracts test_trading_research_evaluation test_trading_research_journal test_trading_research_cli test_trading_research_examples -q
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests .venv/bin/python3.11 -m unittest test_trading_hypothesis_contracts test_trading_hypotheses test_trading_historical_intake_contracts test_trading_historical_intake test_trading_research_v2 test_trading_historical_journal test_trading_historical_cli test_trading_historical_examples -q
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests .venv/bin/python3.11 -m unittest test_trading_shadow_contracts test_trading_shadow_gates test_trading_shadow_intents test_trading_shadow_evaluation test_trading_shadow_journal test_trading_shadow_cli test_trading_shadow_examples -q
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests .venv/bin/python3.11 -m unittest test_trading_evidence_contracts test_trading_continuity_intake test_trading_cost_intake test_trading_shadow_risk_review test_trading_shadow_review_cli test_trading_shadow_review_journal test_trading_shadow_review_examples -q
```

## Fixture versus real-history coverage

The representative synthetic journal preserves 25 original events and appends
seven v17 assessments, exercising all six classifications. It uses the existing
unmodified reversal/continuation fixtures and committed investment examples.
The investment final deadline observation is future-dated, explicitly synthetic
and supports only the original exact predicate. No real-world hypothesis or
economic performance is declared supported.

Real-history verification uses the existing journal at
`output/trading-research-governed-evidence-real-001/journal`, with 14 source events
and 53 retained blobs. The independent evaluation preserves the entire original
history and appends two assessments to a separate journal under
`output/research-acceptance-real-001`. No new data is captured and the original
journal is not modified. Real studies remain deferred rather than being scored
through missing evidence.

Actual retained-data results:

| Frozen hypothesis | Native status | Research classification | Strategy evaluation performed |
| --- | --- | --- | --- |
| `five-session-continuation-v1` | `DEFER_EVIDENCE_GATES` | `NOT_EVALUABLE` | false |
| `previous-session-reversal-v1` | `DEFER_EVIDENCE_GATES` | `NOT_EVALUABLE` | false |

The separate real journal verifies **16 events, 62 retained blobs, zero orphan
evidence and zero staging orphans**. The original 14 events are byte-identical;
its verified chain summary is unchanged. Both assessments retain
`economic_hypothesis_supported=false`. Reason codes:
`CONTINUITY_ADAPTER_UNRESOLVED`, `COST_ADAPTER_UNRESOLVED`,
`EXPLICIT_COST_ASSUMPTIONS_MISSING`, `EX_DATE_COVERAGE_UNVERIFIED`,
`OPENING_MINUTE_COVERAGE_INCOMPLETE`,
`PRICE_CONTINUITY_DISCONTINUITY_PRESENT`,
`RISK_REVIEW_NOT_APPROVED_FOR_SHADOW`.

The persisted synthetic example verifies **32 events, 91 retained blobs and
zero orphans**. Its seven classifications match the design table. The local
manifest is `output/research-acceptance-example-001/manifest.json`; retained real
findings are `output/research-acceptance-real-001/reports/real-history-summary.json`.
These local evidence exports remain ignored and are not Git publication payloads.

Exact additional operator checks:

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests .venv/bin/python3.11 -m blackpod_build_week.research_acceptance_examples --output-root output/research-acceptance-example-001 > /private/tmp/blackpod-acceptance-example-001.stdout.json
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests .venv/bin/python3.11 -m blackpod_build_week.research_acceptance_cli verify --journal-root output/research-acceptance-example-001/journal
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests .venv/bin/python3.11 -m blackpod_build_week.research_acceptance_cli assess --request output/research-acceptance-example-001/input/positive-insufficient-robustness.request.json --journal-root output/research-acceptance-example-001/journal --output output/research-acceptance-example-001/reports/reversal-assessment.v1.json
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests .venv/bin/python3.11 -m blackpod_build_week.research_acceptance_cli record --request output/research-acceptance-example-001/input/positive-insufficient-robustness.request.json --journal-root output/research-acceptance-example-001/journal
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests .venv/bin/python3.11 /private/tmp/blackpod_acceptance_real_check.py
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests .venv/bin/python3.11 -m blackpod_build_week.auto_trading_cli status --runtime-root output/auto-trading-runtime
git diff --check
```

The temporary real-history audit script copied only previously verified events
and retained bytes to a separate journal, generated requests for the two exact
native evaluations, appended their assessments, and asserted preservation of
the original chain and source bytes. Network connections and worker creation
were patched to raise. It is an operator validation helper, not a new producer
or committed dependency. CLI usage is reproducible through the documented
prepare/assess/record interfaces with those selected retained source IDs.

The real study evidence contains 760 sessions for each of QQQ and SPY, unverified
effective-date corporate-action coverage, raw-price continuity barriers, sparse
opening quote evidence, missing reviewed fee/slippage assumptions, and proposed
sizing review. Retained source hashes prove reproducibility of local evidence;
they do not authenticate a provider or establish historical publication-time
availability, valuation, causality, prospective trial registration or sample
independence. No threshold, price, horizon or strategy parameter is tuned.

## Readiness and recommended next milestone

Trading can reproduce specified descriptive offline simulations, but credible
economic validation on the retained real history remains blocked by evidence
qualification and uncertainty/stability methodology. Investment can evaluate
specification and exact deadline evidence while keeping thesis support separate
from realized performance; independent economic meaning, valuation applicability
and causal/horizon coverage remain missing. The journal now links assessments,
supersession and later native outcomes without rewriting original decisions.

Recommended next burst: **governed Trading Desk real-evidence qualification**.
Define an independently justified event-aware continuity/eligibility policy and
training-only cost/capacity calibration, plus a frozen uncertainty/stability
protocol before economic evaluation. Gate completion on deterministic source
binding, chronological availability, unchanged holdout, applicable calibrated
cost evidence and explicit simulation-risk review. This recommendation is not
implemented here. Investment fundamental/valuation adapters remain a separately
governed subsequent milestone.

Auto-trading stays OFF in the uninitialized documented runtime, with no active
worker or entry authority. Budgets remain
inactive; no broker/provider calls, inference, capital transfers, automatic
rebalancing or strategy promotion occurred. The repository has no applicable
remote deployment workflow for this offline checkpoint. Publication updates
`main`; it does not start a trading process, UI service or desktop package.
