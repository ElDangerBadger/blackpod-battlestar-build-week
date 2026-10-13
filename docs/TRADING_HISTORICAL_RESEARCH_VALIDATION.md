# Burst 12 validation: independent hypotheses and governed historical intake

Implemented in the current checkout on October 12, 2026 Pacific (October 13 UTC).
Auto-trading remains **OFF**. No Galactica trading rules, provider inference,
broker orders, capital transfers, budget activation or ownership changes were
used. This is an implemented specification and data-readiness burst, with no
strategy producer or scored hypothesis performance.

## Files changed in this burst

New production modules:

- `src/blackpod_build_week/contracts/trading_hypothesis.py`
- `src/blackpod_build_week/trading_hypotheses.py`
- `src/blackpod_build_week/contracts/historical_intake.py`
- `src/blackpod_build_week/trading_historical_intake.py`
- `src/blackpod_build_week/trading_research_intake_journal.py`
- `src/blackpod_build_week/trading_research_intake_cli.py`
- `src/blackpod_build_week/trading_historical_example.py`

Existing production modules extended additively:

- `contracts/decision_journal.py`: journal v13 catalog/intake and v14 linked research.
- `decision_journal_store.py`: dispatch to retained-input intake replay.
- `contracts/trading_research.py`: strict plan/dataset v2, without altering v1.
- `trading_research_evaluation.py`: v2 empty-intent data-quality results.
- `trading_research_journal.py`: original hypothesis/intake links and exact source reconstruction.
- `trading_research_cli.py`: v2 evidence loading and explicit unscored report labels; v1 paths unchanged.

New tests: `test_trading_hypothesis_contracts.py`, `test_trading_hypotheses.py`,
`test_trading_historical_intake_contracts.py`, `test_trading_historical_intake.py`,
`test_trading_research_v2.py`, `test_trading_historical_journal.py`,
`test_trading_historical_cli.py`, `test_trading_historical_examples.py`.

New docs: this report and `TRADING_HISTORICAL_RESEARCH.md`. README,
ARCHITECTURE, SAFETY_BOUNDARY and `.gitignore` gained additive documentation or
ignored output prefixes. No dependencies or migrations were added.

The pre-edit protected baseline covered 2,303 existing files. The sole change
inside that protected set is the intended additive research CLI extension;
the other 2,302 remain byte-identical. Existing ModelDock work, mission schemas,
stage workflows, Navigator and legacy execution files remain untouched.

## Offline tests and exact commands

All commands ran from the repository root using the existing virtual environment.
The new suites block network access and worker/process creation where applicable.

Final result: **189 new tests + 1,846 prior tests = 2,035 passing tests**, no
failures. The new breakdown is 44 hypothesis, 44 intake, 43 v2 contract/evaluator,
25 journal, 12 CLI and 21 synthetic example tests. Counts are unique tests,
rather than the sum of repeated verification runs.

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests .venv/bin/python3.11 -m unittest \
  test_trading_hypothesis_contracts test_trading_hypotheses \
  test_trading_historical_intake_contracts test_trading_historical_intake \
  test_trading_research_v2 test_trading_historical_journal \
  test_trading_historical_cli test_trading_historical_examples -q
```

The original offline regression suites also passed with this exact common prefix:

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests .venv/bin/python3.11 -m unittest
```

Each row below supplies the remaining module arguments, followed by `-q`.
The groups were run concurrently; elapsed time reflects that shared load.

| Group | Module arguments | Passed |
| --- | --- | ---: |
| Accounting | `test_trading_accounting_contracts test_paper_activity_import test_trading_accounting_engine test_trading_accounting_store test_trading_accounting_cli test_trading_accounting_examples` | 164 |
| Journal/hypotheses/review | `test_decision_journal_contracts test_decision_journal_projection test_decision_journal_store test_decision_journal_cli test_investment_hypothesis_contracts test_investment_hypothesis_sources test_investment_hypothesis_store test_investment_hypothesis_examples test_investment_hypothesis_cli test_investment_review_contracts test_investment_review_engine test_investment_review_store test_investment_review_cli` | 249 |
| Investment governance | `test_investment_governance_contracts test_investment_governance_engine test_investment_approval test_investment_governance_store test_investment_governance_examples test_investment_governance_cli` | 125 |
| Paper and execution safeguards | `test_trading_reconciliation_contracts test_trading_reconciliation_engine test_trading_reconciliation_store test_trading_receipts test_trading_reconciliation_cli test_paper_account_safety test_paper_order_capture test_trading_reconciliation_examples test_auto_trading_runtime test_galactica_trading_adapter test_trading_automation test_paper_account_probe` | 249 |
| Workflow/ModelDock | `test_contracts test_mission_store test_mission_transitions test_mission_presentation test_cli_help test_navigator_adapter test_operator_adapter test_modeldock_config test_modeldock_client test_modeldock_preflight test_modeldock_delivery` | 172 |
| Desk review | `test_shadow_native_analysis test_desk_candidate_review_contracts test_desk_candidate_review_engine test_shadow_galactica_analysis test_desk_candidate_review_store test_desk_candidate_review_cli test_desk_review_sources test_desk_candidate_review_examples` | 233 |
| Forecast/Brigade | `test_forecast_intake_contracts test_forecast_intake_engine test_shadow_brigade_analysis test_forecast_brigade_journal_contracts test_forecast_brigade_store test_brigade_shadow_transport test_forecast_brigade_cli test_forecast_brigade_examples` | 218 |
| Governed producer | `test_shadow_quantitative_producer test_forecast_producer_contracts test_forecast_producer_export test_forecast_producer_examples test_forecast_producer_journal test_forecast_producer_cli` | 128 |
| Structured Brigade | `test_brigade_response_contracts test_brigade_structured_analysis test_brigade_structured_journal test_brigade_structured_transport test_brigade_structured_examples test_brigade_structured_cli` | 144 |
| Original research | `test_trading_research_contracts test_trading_research_evaluation test_trading_research_journal test_trading_research_cli test_trading_research_examples` | 164 |

Original regression total: **1,846 passed**, no failures. Six v1 golden hashes
for plan/dataset/intents/result/registration/evaluation remain unchanged. The
new suites exercise strict nested contracts, authority rejection, decimal
parsing, calendar/coverage/availability bounds, raw-source reconstruction,
idempotency/conflicts, linked evaluations, rehashed tampering, missing or
ambiguous predecessor events, interrupted publication, safe filesystem paths,
source removal and complete synthetic replay.

Independent review found that a legitimate calendar array named `.json` was
rejected by generic object-only reference discovery. The historical loader now
loads only the exact schema-declared source leaves; the strict historical
parser validates the array. Dataset v2 journal replay reconstructs those same
leaves. Original v1 recursive evidence behavior stays unchanged. The regression
covers this source format through export, verify, record, register and evaluation.

`git diff --check` passed. This report does not claim an unrestricted test
discovery run, external provider/inference integration testing, broker order
testing or live trading validation.

## Actual source capture and real-history coverage

The validated artifacts are under
`output/trading-research-governed-history-002`, with raw capture under
`output/trading-research-history-source-002`.

The hypothesis catalog was recorded at **2026-10-13T00:35:43.939967Z** before
the two retained source captures. Existing local Alpaca credentials were read
in memory from the previously authorized source; no credentials were printed
or retained. Only market-data and paper-calendar GET endpoints were used.

| Source | Endpoint and exact query | Capture | Retained coverage |
| --- | --- | --- | --- |
| Bars | `https://data.alpaca.markets/v2/stocks/bars`: `symbols=QQQ,SPY`, `timeframe=1Day`, `start=2023-10-01T04:00:00Z`, `end=2026-10-13T00:36:36.789024Z`, `feed=iex`, `adjustment=raw`, `sort=asc`, `limit=10000` | HTTP 200, `2026-10-13T00:36:37.363252Z` | 760 rows for each symbol, no unconsumed page token |
| Calendar | `https://paper-api.alpaca.markets/v2/calendar`: `start=2023-10-01`, `end=2026-10-12` | HTTP 200, `2026-10-13T00:36:38.049538Z` | 760 returned sessions |

An initial successful bars GET encountered a local writer-argument error before
publication. Its response was discarded; the final two captures have their own
actual timestamps and receipts. No earlier missing receipt was reconstructed
or passed off as an original capture.

The admitted dataset contains **760 sessions / 1,520 symbol-session bars**,
October 2, 2023 through October 12, 2026, with no missing eligible rows and no
excluded unavailable sessions. The last modeled availability was October 13
00:05 UTC (returned October 12 extended close plus 300 seconds), before capture.
This is an explicit retrospective assumption, not proof of past publication.

The real-history journal verifies **6 events / 14 retained evidence blobs**,
zero evidence or staging orphans. Final chain hash:
`bd00ce8fd7b4c87f5c931fdc6a785d5037d051541a5b824c72895f7eeab80e5d`.
Events comprise one catalog, one intake, two registrations and two linked
evaluations. Both evaluations report `DATA_QUALITY_ONLY_NO_STRATEGY_PRODUCER`:
zero intents, fills or metrics; no aggregate or realized P&L; all authority false.
The continuation and reversal studies project 225 and 227 eligible training
label samples respectively. They do not calculate labels' return values or
train models. Final-holdout indices **611–759** remain unscored and readable,
rather than access-sealed. Separate experiment identities reflect distinct
horizons; there is no cross-hypothesis trial-completeness or winner claim.

### Exact offline real-history commands

The capture itself was an explicitly authorized read-only operator script;
the offline CLI never reads credentials or makes requests. After capture:

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests .venv/bin/python3.11 -m blackpod_build_week.trading_research_intake_cli export \
  --request output/trading-research-history-source-002/intake.request.v1.json \
  --evidence-root output/trading-research-history-source-002 \
  --output-directory output/trading-research-governed-history-002/intake

PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests .venv/bin/python3.11 -m blackpod_build_week.trading_research_cli verify \
  --journal-root output/trading-research-governed-history-002/journal
```

The exact freeze, intake recording and two-plan preparation arguments were:

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests .venv/bin/python3.11 -m blackpod_build_week.trading_research_intake_cli freeze-hypotheses \
  --recorded-at 2026-10-13T00:35:43.939967Z --author-id operator-nikolai \
  --catalog-id independent-trading-burst12-v1 \
  --output-directory output/trading-research-governed-history-002/catalog \
  --journal-root output/trading-research-governed-history-002/journal

PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests .venv/bin/python3.11 -m blackpod_build_week.trading_research_intake_cli record-intake \
  --export output/trading-research-governed-history-002/intake/historical-intake/export.v1.json \
  --evidence-root output/trading-research-governed-history-002/intake \
  --journal-root output/trading-research-governed-history-002/journal \
  --recorded-at 2026-10-13T00:36:59.321790Z

PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests .venv/bin/python3.11 -m blackpod_build_week.trading_research_intake_cli prepare-plans \
  --journal-root output/trading-research-governed-history-002/journal \
  --catalog-event-id journal-event-2e9a8595746388c0ceef6a0b891a3b07bf668f6ce0ac60927eb72f9ee9adde6d \
  --intake-event-id journal-event-576155c55618ab7c0b37112609b9be686831dad5988bb3993dab31c26c86f749 \
  --registered-at 2026-10-13T00:36:59.884273Z --id-prefix burst12-retained-history \
  --output-directory output/trading-research-governed-history-002/plans
```

These actual command arguments were dispatched through the same `main(argv)`
entry points in a short Python orchestration script. They can be replayed as
ordinary CLI calls; immutable event and output retries are idempotent.

For each of the two real plans, these commands were executed, with `h1` or `h2`
substituted in the filename and evaluation ID, and actual recording clocks:

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests .venv/bin/python3.11 -m blackpod_build_week.trading_research_cli register \
  --plan output/trading-research-governed-history-002/plans/trading-research/burst12-retained-history-h1.plan.v2.json \
  --evidence-root output/trading-research-governed-history-002/plans \
  --journal-root output/trading-research-governed-history-002/journal

PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests .venv/bin/python3.11 -m blackpod_build_week.trading_research_cli record \
  --plan output/trading-research-governed-history-002/plans/trading-research/burst12-retained-history-h1.plan.v2.json \
  --evidence-root output/trading-research-governed-history-002/plans \
  --journal-root output/trading-research-governed-history-002/journal \
  --evaluation-id burst12-retained-history-h1.plan.v2-quality --recorded-at 2026-10-13T00:37:14.895019Z
```

The second evaluation's clock is `2026-10-13T00:37:17.854394Z`. Reports rendered
successfully to `reviews/review-3.html` and `reviews/review-5.html` using the
verified evaluation IDs. Reports must be separate from the journal root; an
initial parent-directory render attempt was rejected by that safety guard.

Exploratory `trading-research-governed-history-001` retains a mistakenly
future-dated local catalog and an explicit development note; it is not this
validated run. No immutable declaration was rewritten.

## Fixtures, compatibility and operational readback

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests .venv/bin/python3.11 -m blackpod_build_week.trading_historical_example \
  --output-root output/trading-research-historical-example
```

Actual result: **6 events / 14 evidence blobs**, zero orphans. Forty invented
daily sessions, two fictional symbols and authored GET receipts exercise
deterministic end-to-end replay. They are not actual exchange observations or
economic performance. Documentation shell blocks were also executed with
isolated `/private/tmp` outputs: complete example 6/14, explicit manual
walkthrough 4/12, both zero orphans. Source removal and exact retries are tested.

Thirteen earlier valid journals reverified unchanged: **104 events / 593
per-journal retained blobs**, zero orphans and original chain hashes. This
includes the original research example and valid retained-history probe; the
older exploratory probe with incomplete evidence remains excluded, unchanged.

Read-only `runtime_status(Path('output/auto-trading-runtime'))` returns OFF,
entries/requested entries false, worker inactive, null session/mode, no
auto-restart or capital transfers. That runtime root is absent in this checkout;
the readback reflects the uninitialized OFF state. No runtime was installed or
activated by this burst, and no existing controller files were changed.

## Remaining limits and recommended next burst

No return-generating hypothesis implementation, cost calibration, corporate-
action continuity proof, matched exposure control, uncertainty/power analysis,
cross-experiment comparison or promotion criteria exist in this burst.
Hash-bound receipts authenticate local consistency, not provider identity or
past data vintages. The selected QQQ/SPY universe is not survivorship-controlled.
IEX raw daily history cannot establish consolidated liquidity, executable
prices or total returns. Fixed costs and simulated cash are placeholders,
independent of recorded desk budgets. Final holdout scoring remains withheld.

Recommended next burst: a deterministic **shadow research intent producer and
matched-exposure control**, gated by explicitly retained price-continuity /
corporate-action and cost evidence. Freeze rules before evaluation, retain
every trial and rejection, test look-ahead and holding semantics, and keep
holdout scoring and automatic promotion disabled. Keep auto-trading OFF.
That next burst has not been implemented.
