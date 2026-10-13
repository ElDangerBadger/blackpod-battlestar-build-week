# Independent trading shadow research

This burst implements deterministic producers for the two already frozen,
independent hypotheses and a governed offline comparison. Auto-trading stays
OFF. No orders, provider calls, inference, desk ownership, capital activation,
or budget transfers are part of these commands. Galactica trading rules are not
inputs to the producers.

The original hypothesis and research plan remain unchanged. A separate
`blackpod.trading_shadow_study.v1` declaration freezes the base-plan evidence,
gate reviews, sizing rule, benchmark, cost stresses, and trial identity. Journal
v15 stores the registration and its linked, deterministically rebuilt
production and evaluation. Study IDs are limited to 110 characters, reserving
eighteen characters for derived research intent identifiers.

## Producer and comparison semantics

The previous-session reversal candidate requires a strictly negative completed
close-to-close return, then schedules a one-session long exposure. The
five-session continuation candidate requires a strictly positive five-session
completed-close return, then schedules a three-session long exposure. A zero
return produces no candidate. These rules are original, untested proposals;
their implementation establishes neither profitability nor an optimal rule.

At each source-session decision, all lookback closes must already be available.
The whole-share quantity is the floor of the declared per-symbol research
notional divided by the known completed close. Later opening prices and volumes
do not select or size an entry. Entry is simulated at the next available opening;
exit is scheduled after the frozen holding duration. A symbol cannot reenter
while its planned episode remains open. Every opportunity, rejected fill, and
later exit failure is retained.

Only development TEST folds are simulated. Training-label purging and the
declared embargo remain in force. The final holdout is **WITHHELD**. This is a
scoring restriction, not a claim that the historical files are access-sealed.
Cash resets at each fold; no aggregate portfolio return is manufactured.

For every admitted candidate entry, the control creates an unconditional
equal-weight arithmetic cohort across the frozen universe. It matches the
candidate's modeled entry **purchase notional** and holding duration. Fractional
control quantities are counterfactual arithmetic, not executable broker orders.
The control does not match subsequent daily exposure, beta, or the number of
fills. Each control leg pays its own modeled entry and exit costs.

The control has a separate simulated cash ledger and shares its own opening
volume, cash, position and gross-exposure constraints across cohorts. Control
exits precede entries at the same opening; cohort identities determine ties.
Exact accepted candidate entry/exit FIFO lineage must match the episode. Any
unclosed candidate lot, failed control, incomplete match, or observed risk drift
makes the required comparison INCONCLUSIVE. Such failures cannot make the
candidate look better by disappearing from the control.

Costs are replayed at the frozen multipliers **1, 2, and 4**, scaling spread,
slippage, proportional fees and fixed fees. Full Decimal ledger values are
retained. Positive comparison signs use 24 decimal places in dollars with
ROUND_HALF_EVEN so repeating fractional arithmetic cannot turn a numerical
residual into an apparent edge. Cash contributes zero P&L; no interest yield is
invented. Comparisons and cost sensitivity are descriptive: statistical
significance, winner selection, promotion and execution authority remain absent.

## Evidence gates

Both price-continuity and cost evidence must clear before the producers emit
intents. Missing optional review references produce an explicit DEFER record,
empty intents, no fills, and no performance scores. A supplied review with
missing, hash-mismatched, size-mismatched, or contradictory bound source material
is rejected instead of being silently treated as absent.

Every review binds the exact dataset hash and universe. Review and source
declarations must cover the entire included dataset and have clocks between
capture and study registration. Their opaque origin files are retained verbatim
with exact hashes and sizes; they are never executed.

The conservative raw-price policy defers the **entire dataset** if any declared
split, cash distribution, stock distribution, symbol change, merger, or other
price discontinuity occurs, or continuity coverage is incomplete. This burst
does not repair, adjust, or select around those events. Raw-price continuity and
total-return accounting are distinct concerns.

Cost reviews must bound every retained per-symbol spread, slippage, proportional
fee and fixed-fee declaration. Zero modeled price friction cannot clear the gate.
All declared stress levels must remain inside the supported calculation bounds.
These are reviewed cost assumptions, not observed executable quotes, opening
liquidity, partial-fill estimates or measured broker costs.

`SYNTHETIC_FIXTURE_ONLY` and `RETAINED_HISTORY_RESEARCH` are separate scopes.
Synthetic continuity/cost declarations never clear a retained-history study.
Review identities, completeness and economic interpretations remain local
declarations. Hash verification proves retained-byte binding; it does **not**
authenticate a provider, reviewer, historical publication time, or economic
truth. Historical availability remains the explicitly declared retrospective
session-end-plus-delay assumption.

The retained QQQ/SPY dataset contains 760 included sessions per symbol. It lacks
both required real continuity and cost reviews, so its two registered shadow
studies defer with zero intents and fills. No real strategy return is reported.
The research sizing declaration uses the base plan's simulated risk limits;
neither those limits nor a USD 100 per-symbol proposal use or activate the
recorded paper-account desk budgets. They are not optimized sizing advice.

## Runnable offline example

Run from the checkout root using the existing Python environment. Use a new
output directory if an earlier example was created with a different pinned
implementation. Artifact writes are immutable; changing bytes are not silently
overwritten.

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests .venv/bin/python3.11 \
  -m blackpod_build_week.trading_shadow_example \
  --output-root output/trading-research-shadow-example-002

PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests .venv/bin/python3.11 \
  -m blackpod_build_week.trading_shadow_cli verify \
  --journal-root output/trading-research-shadow-example-002/journal

PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests .venv/bin/python3.11 \
  -m blackpod_build_week.trading_shadow_cli register \
  --study output/trading-research-shadow-example-002/input/study-1.json \
  --evidence-root output/trading-research-shadow-example-002/evidence \
  --journal-root output/trading-research-shadow-example-002/journal

PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests .venv/bin/python3.11 \
  -m blackpod_build_week.trading_shadow_cli evaluate \
  --study output/trading-research-shadow-example-002/input/study-1.json \
  --journal-root output/trading-research-shadow-example-002/journal

PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests .venv/bin/python3.11 \
  -m blackpod_build_week.trading_shadow_cli record \
  --study output/trading-research-shadow-example-002/input/study-1.json \
  --journal-root output/trading-research-shadow-example-002/journal \
  --evaluation-id synthetic-shadow-evaluation-h1 \
  --recorded-at 2025-04-01T13:00:00Z
```

The example authors 40 fictional daily sessions for SYNTHA/SYNTHB, including
calendar rows, receipts, continuity statements and cost bounds. Its passive
journal has 10 events and 29 content-addressed evidence blobs, with zero orphans:
six foundation records followed by two study registrations and two evaluations.
The `register` and `record` commands above are exact retries and report
`written: false`; `evaluate`, `show`, and `verify` are read-only. Fixture returns
exercise software accounting and controls; they are not evidence of market edge.

Obtain the verified first evaluation identity from the authored manifest and
inspect or render it:

```sh
BLACKPOD_SHADOW_EVENT_ID=$(.venv/bin/python3.11 -c \
  'import json; print(json.load(open("output/trading-research-shadow-example-002/example.json"))["studies"][0]["evaluation_event_id"])')

PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests .venv/bin/python3.11 \
  -m blackpod_build_week.trading_shadow_cli show \
  --journal-root output/trading-research-shadow-example-002/journal \
  --event-id "$BLACKPOD_SHADOW_EVENT_ID"

PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests .venv/bin/python3.11 \
  -m blackpod_build_week.trading_shadow_cli render \
  --journal-root output/trading-research-shadow-example-002/journal \
  --event-id "$BLACKPOD_SHADOW_EVENT_ID" \
  --output output/trading-research-shadow-reports/review-1.html
```

The escaped HTML includes original evidence, opportunities, cost sensitivities,
candidate rejections, comparison status and limits. A report does not control the
runtime switch; check runtime OFF separately with the existing runtime tooling.

## Preparing a separately deferred study

`prepare` writes a source-bound declaration and its evidence package without
registering a journal event. The following example deliberately supplies neither
review, so it demonstrates a safe DEFER flow rather than a scored strategy. It
adds two records to the fixture journal only after explicit `register`/`record`.

```sh
BLACKPOD_BASE_PLAN_EVENT_ID=$(PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests \
  .venv/bin/python3.11 -c \
  'from blackpod_build_week.decision_journal_store import JournalStore; events, _ = JournalStore("output/trading-research-shadow-example-002/journal").verified_contents(); print(next(e.event_id for e in events if e.event_type == "TRADING_RESEARCH_PLAN_REGISTERED"))')

PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests .venv/bin/python3.11 \
  -m blackpod_build_week.trading_shadow_cli prepare \
  --journal-root output/trading-research-shadow-example-002/journal \
  --base-plan-event-id "$BLACKPOD_BASE_PLAN_EVENT_ID" \
  --study-id documented-deferred-shadow-study \
  --experiment-id documented-deferred-shadow-experiment \
  --registered-at 2025-04-01T14:00:00Z \
  --per-symbol-notional 80 \
  --evidence-scope SYNTHETIC_FIXTURE_ONLY \
  --output-directory output/trading-research-shadow-deferred-input

PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests .venv/bin/python3.11 \
  -m blackpod_build_week.trading_shadow_cli register \
  --study output/trading-research-shadow-deferred-input/trading-shadow/study.v1.json \
  --evidence-root output/trading-research-shadow-deferred-input \
  --journal-root output/trading-research-shadow-example-002/journal

PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests .venv/bin/python3.11 \
  -m blackpod_build_week.trading_shadow_cli evaluate \
  --study output/trading-research-shadow-deferred-input/trading-shadow/study.v1.json \
  --journal-root output/trading-research-shadow-example-002/journal

PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests .venv/bin/python3.11 \
  -m blackpod_build_week.trading_shadow_cli record \
  --study output/trading-research-shadow-deferred-input/trading-shadow/study.v1.json \
  --journal-root output/trading-research-shadow-example-002/journal \
  --evaluation-id documented-deferred-shadow-evaluation \
  --recorded-at 2025-04-01T15:00:00Z

PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests .venv/bin/python3.11 \
  -m blackpod_build_week.trading_shadow_cli verify \
  --journal-root output/trading-research-shadow-example-002/journal
```

To supply reviews, `prepare` accepts `--price-continuity`, `--cost-evidence`, and
`--evidence-root`. Every referenced source and origin body must already exist
with its declared bytes. Input roots, output roots and the journal must remain
separate. A missing review may defer; an invalid supplied review is not a
substitute for missing evidence.

## Audit and reproducibility limits

Registrations preserve the immutable study, preceding base-plan/hypothesis/intake
links, complete retained evidence and seven installed calculation source files.
Evaluations append to the registration; later trials do not rewrite earlier
results or change exact retries. All preceding trials in the same experiment
must be declared. Changing gate evidence, base-plan evidence, benchmark, stress
levels or evidence scope requires another experiment. Global trial completeness
and historical preregistration are not asserted.

Journal verification rebuilds the producer, gate assessment, candidate
simulation and controls. Tampered results fail even if an attacker recalculates
ordinary content hashes. Installed calculation-source changes fail closed
against the retained pins; the verifier never executes retained Python source.
A future implementation version needs an explicit replay/version migration
design before those older shadow records can be evaluated with new code. The
existing v1/v2 research records keep their original semantics and bytes.

Interrupted append recovery, immutable storage, retained-source operation,
idempotency, path protection and content verification use the existing journal
store. Local hash chains do not prove provider authenticity or defeat a fully
privileged rewrite without an independently trusted checkpoint.

The next evidence work should supply retained corporate-action continuity
reviews and measured, time-bound cost/capacity evidence before scoring real
historical strategies. Keep execution authority OFF while validating those
inputs; this burst enables no automatic allocation or strategy promotion.
