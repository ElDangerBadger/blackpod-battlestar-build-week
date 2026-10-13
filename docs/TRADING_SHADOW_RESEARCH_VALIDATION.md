# Burst 13 validation: deterministic shadow intents and matched controls

Implemented in the current checkout on October 12, 2026 Pacific (October 13 UTC).
**Auto-trading remains OFF.** This burst imports no Galactica trading rules,
starts no inference or worker, calls no provider or broker, submits no orders,
and activates no ownership, desk budget, capital transfer or policy.

## Files changed

Seven new production modules:

- `src/blackpod_build_week/contracts/trading_shadow_research.py`: immutable study, continuity/cost review and source contracts.
- `src/blackpod_build_week/trading_shadow_gates.py`: exact retained evidence, coverage, chronology, discontinuity and stressed-cost validation.
- `src/blackpod_build_week/trading_shadow_intents.py`: deterministic sign rules, known-close whole-share sizing and opportunity/episode provenance.
- `src/blackpod_build_week/trading_shadow_evaluation.py`: existing generic arithmetic adapter, fractional equal-weight controls, cost stresses and descriptive comparison.
- `src/blackpod_build_week/trading_shadow_journal.py`: source-linked v15 registration/evaluation, trial history and calculation pins.
- `src/blackpod_build_week/trading_shadow_cli.py`: explicit offline prepare/register/evaluate/record/show/render/verify.
- `src/blackpod_build_week/trading_shadow_example.py`: entirely authored end-to-end fixtures.

Two existing production modules extended additively:

- `contracts/decision_journal.py`: strict v15 event parsing; v1–v14 semantics retained.
- `decision_journal_store.py`: v15 dispatch to deterministic source replay.

Seven new test files: `test_trading_shadow_contracts.py`,
`test_trading_shadow_gates.py`, `test_trading_shadow_intents.py`,
`test_trading_shadow_evaluation.py`, `test_trading_shadow_journal.py`,
`test_trading_shadow_cli.py`, `test_trading_shadow_examples.py`.

Two new documents: this report and `TRADING_SHADOW_RESEARCH.md`. README,
ARCHITECTURE and SAFETY_BOUNDARY gained additive descriptions. Existing output
ignore rules already cover the new `output/trading-research-shadow-*` artifacts.
No dependency, migration, canonical mission, live strategy or configuration
change was made. Original research and historical-intake modules are unchanged.

## Actual offline tests

**2,256 unique tests passed: 221 new + 2,035 prior regressions, no failures.**
Repeated targeted verification is not double-counted.

| New suite | Passed |
| --- | ---: |
| Strict contracts | 46 |
| Continuity/cost gates | 27 |
| Deterministic producers | 48 |
| Simulation and matched controls | 31 |
| Journal replay/recovery | 22 |
| CLI integration | 29 |
| Complete synthetic examples | 18 |
| Total | 221 |

Exact final command:

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests .venv/bin/python3.11 -m unittest \
  test_trading_shadow_contracts test_trading_shadow_gates \
  test_trading_shadow_intents test_trading_shadow_evaluation \
  test_trading_shadow_journal test_trading_shadow_cli \
  test_trading_shadow_examples -q
```

Actual final result: `Ran 221 tests in 90.848s — OK`.
Tests block sockets and process creation as appropriate. They cover both sign
rules, exact zero/tiny-return boundaries, prefix availability, future/holdout
perturbations, non-overlap and scheduled exits, sizing/resource bounds, rejected
entries/exits, FIFO episode lineage, costs, pooled control cash/volume/exposure,
fractional arithmetic, incomplete comparisons, changed evidence, replay after
source removal, idempotency, trial history, rehashed tampering, changed installed
calculation hashes, interrupted publication, output conflicts and unsafe paths.

The full prior offline groups from
[Burst 12 validation](TRADING_HISTORICAL_RESEARCH_VALIDATION.md#offline-tests-and-exact-commands)
were rerun with their exact listed module arguments: accounting 164, journal/
investment review 249, governance 125, paper safeguards 249, workflow/ModelDock
172, desk review 233, forecast/Brigade 218, governed producer 128, structured
Brigade 144, original research 164. All **1,846** passed. The previous new
historical research suites were also rerun:

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests .venv/bin/python3.11 -m unittest \
  test_trading_hypothesis_contracts test_trading_hypotheses \
  test_trading_historical_intake_contracts test_trading_historical_intake \
  test_trading_research_v2 test_trading_historical_journal \
  test_trading_historical_cli test_trading_historical_examples -q
```

Those **189** passed; all v1 golden hashes remained unchanged. This was selected
safe offline regression testing, not unrestricted discovery or broker/inference
integration testing. `git diff --check` passed.

Independent review identified and resolved three boundaries before the final
runs: isolated Decimal arithmetic and strict validation at every stressed cost,
the 21-digit fee created by an otherwise legal 4× stress, and study identifiers
whose derived intent identifiers exceeded the existing 128-character limit.
Study IDs now reserve eighteen suffix characters, with a maximum of 110.
An interrupted-write test initially used the wrong storage helper name; the
test was corrected to exercise the actual immutable publication function.

## Implemented semantics and gates

Both producers implement the original frozen hypotheses: one-session exposure
after a negative previous-session return; three-session exposure after a
positive five-session return. Selection and quantity use known completed closes
only. Quantity is the floor of an explicitly declared simulated per-symbol
notional divided by that close. Later opening prices or volumes cannot select
or size entries. Every opportunity and deferred exit remains recorded.

Only development TEST segments can generate fills. Planned holding periods
cannot cross TEST boundaries or the final holdout. Final-holdout scoring stays
WITHHELD. No fitting, parameter search, winner selection or live sizing occurs.
The existing v1 arithmetic engine is used through an ephemeral adapter; original
v1/v2 source documents are never rewritten or relabeled in storage. The outer
production/evaluation records carry the genuine new producer provenance and
retrospective availability limitations.

Price and cost reviews bind an exact dataset, full selected universe, complete
coverage and retained source/origin bytes. A review's status alone is insufficient.
Any declared split, distribution, symbol change or other discontinuity defers
the entire dataset under this initial conservative policy. Cost models must be
at least all retained per-symbol review bounds and validate at 1×, 2× and 4×.
Missing optional reviews defer; supplied corrupt evidence fails validation.
Synthetic reviews cannot clear `RETAINED_HISTORY_RESEARCH`. Synthetic eligibility
also requires the explicitly controlled SYNTH universe and fixture intake author.

These are locally reviewed, hash-bound claims. They do not authenticate the
reviewer, provider, original publication time or empirical cost estimation.
Opaque origin material is retained for audit, not interpreted by an LLM or
executed. Raw provider-to-reviewed-source normalization is not implemented here.

The control distributes each admitted candidate entry purchase notional equally
over the fixed universe, with the same holding duration. Fractional quantities
are arithmetic only. It matches initial modeled purchase notional, not daily
path exposure, beta or fill count. Each leg pays costs and the control has its
own shared cash, known-volume and exposure admission constraints. Rejected or
unclosed controls, missing candidate exits, FIFO mismatches or observed risk
breaches make comparison INCONCLUSIVE. No favorable subset replaces the full
fold comparison. Sign classification uses a disclosed 24-decimal USD quantum
to avoid spurious repeating-division residuals; full ledger values are retained.

## Controlled fixture: actual results

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests .venv/bin/python3.11 -m blackpod_build_week.trading_shadow_example \
  --output-root output/trading-research-shadow-example-002

PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests .venv/bin/python3.11 -m blackpod_build_week.trading_shadow_cli verify \
  --journal-root output/trading-research-shadow-example-002/journal
```

The final example contains **40 invented sessions, SYNTHA/SYNTHB**, authored
calendar/GET receipts and authored continuity/cost evidence. Simulated sizing is
USD 80 per candidate symbol against the original USD 1,000/$100 generic risk
declarations. No recorded paper budget is consumed. Costs start at authored
10 bps spread, 5 bps slippage, zero proportional fee and USD 0.10 per fill.

Actual journal: **10 events / 29 retained blobs, zero orphans**. The original
six catalog/intake/data-quality records are followed by two shadow registrations
and two evaluations. Final chain hash:
`b573155a372f539da5c5c44d892d667e3bd0f8c28f2e192a8d7ca1dadb4a0bba`.

| Fixture hypothesis | Episodes / intents | Fills per cost stress | Interpretation at all three stresses |
| --- | ---: | ---: | --- |
| Five-session continuation | 4 / 8 | 8, no fill rejections | Complete descriptive comparison; nonpositive against cash |
| Previous-session reversal | 6 / 12 | 12, no fill rejections | INCONCLUSIVE due to observed candidate exposure drift |

Constructed continuation net P&L is −1.336, −2.672 and −5.344 USD at 1×/2×/4×.
Its comparison with the control is positive but it fails the required cash
comparison. Reversal's comparison values remain null because of the retained
risk breach. These values test accounting and falsification behavior; they
are not actual security returns or evidence for selecting either hypothesis.
Both evaluations retain null realized trade P&L and no aggregate portfolio return.

All seven CLI commands and the documentation walkthrough were executed offline
with isolated `/private/tmp` output roots: exact registration/evaluation retries
returned `written=false`; an extra missing-evidence study added two deferred
events and the resulting **12-event** journal verified. Rendered reports escape
external text and display authority OFF, final holdout UNSCORED and INCONCLUSIVE
or DEFER states. Files must live in a separate report directory; an initial
parent-directory report request was correctly rejected by that safety guard.

## Retained real history: actual results

No new API requests or credential access occurred in this burst. The existing
verified QQQ/SPY intake from Burst 12 was reused: **760 sessions / 1,520
symbol-session bars**, October 2, 2023 through October 12, 2026. The six source
journal events and their evidence were copied by verified immutable append into
a separate root, preserving the original history and its chain hash.

Final root: `output/trading-research-shadow-history-002`. Two new studies bind
the original quality plans with explicit `RETAINED_HISTORY_RESEARCH` scope and
USD 100 simulated per-symbol declarations. Those are planning values, not
optimal sizes or desk allocations. The original simulated risk limits remain
unchanged; meaningful whole-share studies of higher-priced securities would
also require a separately declared suitable research sizing/risk plan.

Both studies are **DEFER_EVIDENCE_GATES** with:

- `COST_EVIDENCE_MISSING`
- `PRICE_CONTINUITY_EVIDENCE_MISSING`

Actual production: **zero intents, episodes, fills, cost-stress scores or
strategy performance**. No missing continuity or historical cost facts were
invented. Real-history journal: **10 events / 23 retained blobs**, zero orphans.
Final chain hash:
`5cb23eef153d3112ddbd9f93c31b4f11c9b97f1b03360964dbefbc5bdfa000a8`.

The exact preparation and registration arguments for h1 were dispatched through
the CLI's `main(argv)` entry point in a short Python orchestration script:

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests .venv/bin/python3.11 -m blackpod_build_week.trading_shadow_cli prepare \
  --journal-root output/trading-research-shadow-history-002/journal \
  --base-plan-event-id journal-event-18b31ee2e469466dd078b708b506a12dceb79e9d57002243c6f52a0eb1c854a1 \
  --study-id burst13-retained-history-h1 --experiment-id burst13-retained-history-h1-experiment \
  --registered-at 2026-10-13T01:40:05.813411Z --per-symbol-notional 100 \
  --evidence-scope RETAINED_HISTORY_RESEARCH \
  --output-directory output/trading-research-shadow-history-002/study-h1

PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests .venv/bin/python3.11 -m blackpod_build_week.trading_shadow_cli register \
  --study output/trading-research-shadow-history-002/study-h1/trading-shadow/study.v1.json \
  --evidence-root output/trading-research-shadow-history-002/study-h1 \
  --journal-root output/trading-research-shadow-history-002/journal

PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests .venv/bin/python3.11 -m blackpod_build_week.trading_shadow_cli record \
  --study output/trading-research-shadow-history-002/study-h1/trading-shadow/study.v1.json \
  --evidence-root output/trading-research-shadow-history-002/study-h1 \
  --journal-root output/trading-research-shadow-history-002/journal \
  --evaluation-id burst13-retained-history-h1-evaluation --recorded-at 2026-10-13T01:40:08.823037Z

PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests .venv/bin/python3.11 -m blackpod_build_week.trading_shadow_cli verify \
  --journal-root output/trading-research-shadow-history-002/journal
```

h2 used the original event
`journal-event-757983f66ed1f03b862ec5fa25648f39aa1faab98a90a86ac723a75c21513ca0`,
study/experiment/evaluation names with h2, registration
`2026-10-13T01:40:22.103590Z` and evaluation `2026-10-13T01:40:26.600200Z`.
Both verified evaluations rendered to their corresponding files in `reviews/`.
The [usage guide](TRADING_SHADOW_RESEARCH.md) supplies full show/render examples.

Earlier development roots `trading-research-shadow-example` and
`trading-research-shadow-history-001` retain their original bytes and an explicit
development note. Their calculation pins precede the final identifier fix and
intentionally reject the changed installation. They are excluded from validated
results; no original journal entry was rewritten to hide the change.

## Preservation and operational readback

Fifteen earlier valid journals reverified with their original chain hashes:
**116 events / 621 per-journal blobs**, zero orphans. This includes the earlier
13 validated journals plus both Burst 12 real-history and synthetic runs.

The protected baseline covers **59,125** pre-existing files outside the explicitly
authorized edits. **59,124 remain byte-identical**. One existing runtime stdout
log advanced during work:
`artifacts/sentry-calibration-v2-closeout-20260917/runtime/service.stdout.log`.
No code or test in this burst references or writes that log; it was left intact,
without resetting it or changing the associated runtime. Its writer was not
identified. All protected ModelDock source/configuration and existing mission,
execution, ownership and budget artifacts remain unchanged.

Read-only `runtime_status(Path('output/auto-trading-runtime'))` returns **OFF**,
entries/requested entries false, worker inactive and null session/mode. That
runtime root is absent here, so this is the uninitialized OFF state. This burst
did not install, activate or change a trading runtime.

## Limits and recommended next burst

Real historical performance is unassessed until evidence gates clear. Current
continuity gating rejects any declared discontinuity across the entire dataset;
it does not adjust returns or automatically exclude intervals. Cost sources are
reviewed bounds, not an implemented raw quote/fee estimator or executable depth
model. IEX volume and modeled next opens cannot establish opening liquidity.
Counterfactual entry matching is conditional on candidate admission and does not
control daily beta, exposure path or market-wide survivorship. Statistical
significance, power, cross-experiment selection corrections, real-world edge
and promotion criteria remain unassessed.

Seven calculation-source snapshots are retained and checked against the
installed implementation. A new calculation version needs explicit compatible
replay/dispatch before changing those files. The verifier does not execute
archived Python code. This is a detectable reproducibility boundary, not a
general executable environment archive or an independently trusted audit anchor.

Recommended next burst: **governed real-data continuity and cost-evidence
adapters plus an explicit shadow sizing/risk review**. Retain corporate-action
coverage, time-bound quote/fee/capacity inputs and reviewed estimation rules;
define conservative discontinuity treatment before scoring real strategies.
Freeze every new trial, keep the final holdout withheld and auto-trading OFF.
No next-burst work has been implemented.
