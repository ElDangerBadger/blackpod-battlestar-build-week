# Burst 11 implementation and validation — October 12, 2026 Pacific

**The independent Trading Research Contract and Offline Evaluation Foundation
are implemented. Galactica trading rules are not reused. Auto-trading is OFF.**

Brigade evidence-consistency review remains a separate optional diagnostic
branch. It is not a prerequisite or a strategy source for this foundation.
The new evaluator consumes explicit research inputs, not Brigade votes,
legacy forecasts, candidate rankings, mandates, entry/exit thresholds or sizing.

## Delivered functionality

Five new implementation files:

- `src/blackpod_build_week/contracts/trading_research.py`
- `src/blackpod_build_week/trading_research_evaluation.py`
- `src/blackpod_build_week/trading_research_journal.py`
- `src/blackpod_build_week/trading_research_cli.py`
- `src/blackpod_build_week/trading_research_example.py`

Existing passive storage extended:

- `contracts/decision_journal.py`: additive v12 plan/evaluation envelopes.
- `decision_journal_store.py`: source-bound research replay on append/read.
  Existing v1–v11 dispatches and storage publication behavior are unchanged.

Five new test files mirror those subsystem names under `tests/`.
New documentation is `docs/TRADING_RESEARCH.md` and this report. README,
architecture and safety documents received append-only additions.
`.gitignore` adds only `/output/trading-research-*/` for generated artifacts.
Unrelated working-tree changes, including ModelDock work, were preserved.
No commit, PR, dependency installation, database migration or sibling
repository edit occurred.

The versioned contracts freeze hypothesis, expected edge and invalidation
conditions; universe/horizon; original dataset and external decision evidence;
chronological folds and reserved final holdout; explicit costs, simulated risk
bounds, CASH benchmark and trial registry. Enabled authority, unknown fields,
unsupported quantities and invalid timestamps reject.

The pure next-open engine uses new strategy-neutral FIFO simulation with
whole-share supplied quantities, half-spread/slippage adjustments, explicit
fees, available prior-bar volume, pooled participation caps, cash and
entry exposure limits. It rejects unavailable/stale sources, same/earlier
openings, unsupported partitions, holdout fills, unfunded sizes and oversells.
It records price-driven exposure and holding breaches without inventing exits.
A 20,000-row projection cap applies before simulation.

Training features/labels must meet declared cutoffs; boundary/future labels
purge and unusable splits defer scoring. DAY plans defer because daily OHLCV
cannot reconstruct intraday paths. Final holdout is unscored, not access sealed.
There is no strategy generator, fitting, autonomous selection, broker intent,
paper activation, sizing recommendation or LLM inference in this foundation.

Journal registration freezes the exact plan, dataset, external decisions and
recursive raw source closure. Later evaluations append to that registration.
The trial registry includes every earlier registered trial in the same local
experiment even if unscored or unsuccessful. Changed costs/data/protocol/risk
require a different experiment identity. Completeness outside this journal and
prospective preregistration are explicitly unverified.

## Actual test results

**1,846 unique selected offline tests passed: 164 new and 1,682 regressions.**
Development reruns are not counted twice.

| Group | Tests | Result | Final duration |
| --- | ---: | --- | ---: |
| New research contracts/evaluator/journal/CLI/examples | 164 | PASS | 2.136 s |
| Existing structured Brigade | 144 | PASS | 12.057 s |
| Existing forecast producer | 128 | PASS | 47.527 s |
| Existing forecast intake/Brigade | 218 | PASS | 25.597 s |
| Existing shadow two-desk/native review | 233 | PASS | 101.887 s |
| Existing accounting | 164 | PASS | 26.267 s |
| Existing journal/hypotheses/review | 249 | PASS | 20.028 s |
| Existing investment governance | 125 | PASS | 77.541 s |
| Existing paper/runtime/reconciliation | 249 | PASS | 31.179 s |
| Existing mission/operator/Navigator/ModelDock | 172 | PASS | 1.881 s |

New module counts: contracts 48; evaluator 65; journal 23; CLI 13; examples 15.

The tests cover explicit monetary outcomes, fee residuals and partial FIFO
closes, adverse costs, cash/position/gross/liquidity rejection, pooled volume,
simultaneous-decision determinism, both freshness checkpoints, future/late
evidence, cutoff purging, holdout price invariance, DAY deferral, missing data,
open positions, drawdown, exposure drift, holding breaches and resource bounds.
They also cover immutable registration, all local trial IDs, changed-input
conflicts, source/transitive evidence tampering, replay after rehashing,
append interruption/retry, mixed journal versions, passive CLI workflows,
path guards and HTML escaping. Actual network/process/legacy execution and
advisory inference are blocked in relevant tests.

Exact final new-test command:

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests .venv/bin/python3.11 -m unittest \
  test_trading_research_contracts test_trading_research_evaluation \
  test_trading_research_journal test_trading_research_cli \
  test_trading_research_examples -q
```

Exact regression commands:

```sh
# accounting
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests .venv/bin/python3.11 -m unittest \
  test_trading_accounting_contracts \
  test_paper_activity_import \
  test_trading_accounting_engine \
  test_trading_accounting_store \
  test_trading_accounting_cli \
  test_trading_accounting_examples -q

# journal
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests .venv/bin/python3.11 -m unittest \
  test_decision_journal_contracts \
  test_decision_journal_projection \
  test_decision_journal_store \
  test_decision_journal_cli \
  test_investment_hypothesis_contracts \
  test_investment_hypothesis_sources \
  test_investment_hypothesis_store \
  test_investment_hypothesis_examples \
  test_investment_hypothesis_cli \
  test_investment_review_contracts \
  test_investment_review_engine \
  test_investment_review_store \
  test_investment_review_cli -q

# governance
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests .venv/bin/python3.11 -m unittest \
  test_investment_governance_contracts \
  test_investment_governance_engine \
  test_investment_approval \
  test_investment_governance_store \
  test_investment_governance_examples \
  test_investment_governance_cli -q

# paper
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests .venv/bin/python3.11 -m unittest \
  test_trading_reconciliation_contracts \
  test_trading_reconciliation_engine \
  test_trading_reconciliation_store \
  test_trading_receipts \
  test_trading_reconciliation_cli \
  test_paper_account_safety \
  test_paper_order_capture \
  test_trading_reconciliation_examples \
  test_auto_trading_runtime \
  test_galactica_trading_adapter \
  test_trading_automation \
  test_paper_account_probe -q

# workflow
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests .venv/bin/python3.11 -m unittest \
  test_contracts \
  test_mission_store \
  test_mission_transitions \
  test_mission_presentation \
  test_cli_help \
  test_navigator_adapter \
  test_operator_adapter \
  test_modeldock_config \
  test_modeldock_client \
  test_modeldock_preflight \
  test_modeldock_delivery -q

# shadow7
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests .venv/bin/python3.11 -m unittest \
  test_shadow_native_analysis \
  test_desk_candidate_review_contracts \
  test_desk_candidate_review_engine \
  test_shadow_galactica_analysis \
  test_desk_candidate_review_store \
  test_desk_candidate_review_cli \
  test_desk_review_sources \
  test_desk_candidate_review_examples -q

# forecast8
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests .venv/bin/python3.11 -m unittest \
  test_forecast_intake_contracts \
  test_forecast_intake_engine \
  test_shadow_brigade_analysis \
  test_forecast_brigade_journal_contracts \
  test_forecast_brigade_store \
  test_brigade_shadow_transport \
  test_forecast_brigade_cli \
  test_forecast_brigade_examples -q

# producer9
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests .venv/bin/python3.11 -m unittest \
  test_shadow_quantitative_producer \
  test_forecast_producer_contracts \
  test_forecast_producer_export \
  test_forecast_producer_examples \
  test_forecast_producer_journal \
  test_forecast_producer_cli -q

# structured10
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests .venv/bin/python3.11 -m unittest \
  test_brigade_response_contracts \
  test_brigade_structured_analysis \
  test_brigade_structured_journal \
  test_brigade_structured_transport \
  test_brigade_structured_examples \
  test_brigade_structured_cli -q
```

## Runnable fixture coverage actually exercised

All commands in the [usage guide](TRADING_RESEARCH.md#runnable-synthetic-example)
were executed: prepare, register, evaluate, record, show, render and verify.
The prepared example registers only its plan. Registering again returned
`written=false`, as did repeating the recorded evaluation.

The entirely authored fixture uses two fictional symbols, 12 synthetic
sessions and five explicit decisions. Its $1,000 cash and seven-day freshness
allowance are standalone simulation parameters, not current paper-account
capital or live policy. It produces:

- Three simulated fills: BUY two at $100.10, SELL one at $101.898 and SELL
  one at $102.897.
- Two FIFO matches, exact $0.05/$0.05 entry-fee allocation.
- One HOLD without a fill; one rejected oversized entry.
- Fees $0.30, adverse modeled price cost $0.405, total modeled cost $0.705.
- Ending simulated equity $1,004.295 and simulated net P&L $4.295.
  This constructed result demonstrates accounting, not a trading edge.
- Final holdout unscored; actual `realized_trade_pnl` null.
  Sharpe/Sortino/annualization/significance remain unassessed/null.

The journal at `output/trading-research-foundation-example/journal` verifies
**2 events / 4 evidence blobs / zero evidence or staging orphans**.
Chain hash:
`fe0b8506d1afd7806d1ff201abefd3bb4c766070a126a11472ebc49ccc8c9cf1`.
Evaluation:
`journal-event-5aabb09a930e5b2c47ab839a986066cd73af1b0b1821ccc637487c30405709d2`.

Final HTML:
`output/trading-research-foundation-example-report/review.v2.html`,
SHA `9f6a6e7115a77a4ade27ebaef7e63401b045e027b874b27ecbe64ab15deac80e`.

## Retained real-history coverage and honest non-scoring

A separate **read-only, offline** probe reused Burst 9's real retained
SPY/QQQ market bytes and returned exchange calendar. No new provider, broker,
credential or market-data request occurred. The temporary projection script was:

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python3.11 \
  /private/tmp/blackpod_burst11_history_probe.py
```

It retained 14 common sessions, September 23 through October 12, 2026.
All observation availability remains the actual retained market capture
`2026-10-12T22:36:43.550499Z`, rather than falsely assigning current archive
values to earlier historical closes. The supplied exchange calendar binds
regular-session open/close labels; it does not authenticate historical
publication or revision timing.

Result: **DEFER_SPLIT_AVAILABILITY_INVALID, zero simulated fills, metrics null.**
No performance was scored and no hypothesis about a tradable market edge was
invented. This verifies that late capture availability blocks retrospective
evaluation; it is not a real-market strategy backtest.

The final journal at
`output/trading-research-retained-history-probe-002/journal` verifies
**2 events / 8 evidence blobs / zero orphans**, chain hash
`d0f59ee7082e66e4f3ddcbd5bf2a4d3dd40649e0ea5268cc9cd1dad6d2b94dd0`.
Evaluation:
`journal-event-e7a37703bec3832106ee395220167662bf78bdbdfdcb01d6ee5d56dc7be01ffd`.

Final HTML:
`output/trading-research-retained-history-probe-report/review.v2.html`,
SHA `668e854b2b33e2c1f823d399430a30f1a6780930b08f9f5300d9755608159171`.

The generic dataset contract validates declared structure, prices, availability
relationships and source hashes. It does **not** independently reconstruct
arbitrary vendor data from source wrappers or authenticate those declarations.
The data-only probe's source projection is an integration exercise, not a
new supported vendor intake API. A proper historical/point-in-time ingestion
contract remains future work.

## Final audit and reporting commands

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python3.11 \
  -m blackpod_build_week.trading_research_cli verify \
  --journal-root output/trading-research-foundation-example/journal

PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python3.11 \
  -m blackpod_build_week.trading_research_cli verify \
  --journal-root output/trading-research-retained-history-probe-002/journal

PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python3.11 \
  -m blackpod_build_week.trading_research_cli render \
  --journal-root output/trading-research-foundation-example/journal \
  --event-id journal-event-5aabb09a930e5b2c47ab839a986066cd73af1b0b1821ccc637487c30405709d2 \
  --output output/trading-research-foundation-example-report/review.v2.html

PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python3.11 \
  -m blackpod_build_week.trading_research_cli render \
  --journal-root output/trading-research-retained-history-probe-002/journal \
  --event-id journal-event-e7a37703bec3832106ee395220167662bf78bdbdfdcb01d6ee5d56dc7be01ffd \
  --output output/trading-research-retained-history-probe-report/review.v2.html

PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python3.11 \
  -m blackpod_build_week.auto_trading_cli status \
  --runtime-root output/auto-trading-runtime

git diff --check
```

Both final reports passed isolated browser checks at desktop 1360×1000 and
mobile 390×844: no browser errors/document overflow, one fold row, the expected
five/zero decision rows, simulated-only and authority OFF badges, holdout
unscored. Browser network was blocked and an isolated profile was used.
Screenshots under `output/playwright/trading-research/` were visually inspected.
The first report version's long diagnostic codes caused mobile overflow; the
corrected version wraps them and preserves original HTML as a prior artifact.

An exploratory first history probe omitted transitive raw source retention.
Its original journal bytes remain preserved with a development note, and it
is not a valid final v12 research journal. The corrected final probe uses a
new identity/root, and the new transitive-closure tests reject missing children.
No existing source history or prototype record was overwritten to conceal
that integration finding. Preliminary example output likewise stays separate
from the documented final example.

All **11 pre-burst retained journals** reverified with their original hashes
and zero orphans. A SHA-256 baseline verified **2,204 protected pre-existing
files unchanged**. New passive envelope/handler and append-only documentation
changes were explicitly outside that protected baseline. No source mission,
runtime/profile, paper budget, ModelDock configuration or legacy strategy
implementation was altered.

Final runtime readback: OFF; entries/requested entries false; worker inactive;
mode/session null; auto-restart false; capital transfers false.
No paper/account P&L is claimed and no investment authority is changed.

## Limits and recommended next burst

This is a foundation for evaluating new strategies, not an implemented alpha
strategy. Whole next-open fills, fixed costs and prior-bar volume are model
assumptions; they do not show live liquidity or enforce future broker-order
bounds. Close-only drawdown misses intraday losses. Admission limits may be
breached by market drift; annotations do not force exits. No shorting,
leverage, corporate actions, financing, partial fills, realistic capacity,
exposure-matched benchmark or statistical significance is implemented.
CASH comparison alone is not evidence of edge.

Final holdout files are readable, ancestry/availability/preregistration are
unauthenticated declarations, and local trial completeness cannot detect
undisclosed experiments elsewhere. Exact replay requires preserving the v1
method semantics; this burst does not archive/attest a complete executable
environment. Future changes must keep old methods replayable or use an
explicit new version. No autonomous strategy or capital-policy improvement
is authorized.

**Recommended next burst: independent trading hypotheses and governed
historical-data intake.** Define a small number of entirely new falsifiable
day/swing hypotheses and simple comparison baselines, then bind raw data,
sessions, adjustments and explicit availability assumptions through a
tested source adapter. Record every trial, preserve final holdout separation,
report costs/rejections/failures, and distinguish retrospective assumptions
from genuine point-in-time evidence. Add an independently specified strategy
producer only after this evidence contract is reviewable; advanced methods
must earn incremental value. Keep this shadow/offline and auto-trading OFF.
No next-burst work or Brigade consistency implementation was performed.
