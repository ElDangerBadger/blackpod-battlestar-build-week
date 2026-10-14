# Prospective reversal experiment

BlackPod is running one bounded observational pilot of its existing
`previous-session-reversal-v1` proposal. It records whether a completed down
session in QQQ or SPY is followed by a positive opening-price response. The
purpose is to collect new predictions before their outcomes exist and learn
from one fixed experiment. Auto-trading remains OFF.

## Fixed method and comparisons

The original hypothesis bytes remain unchanged. Its signal is
`close[t] / close[t-1] - 1 < 0`, with a one-session holding horizon. This pilot
uses raw daily IEX price aggregates as **gross observational proxies**. The
provider daily-bar opening price is not verified as a regular-session opening
auction or an executable fill, and its close is not restricted to the regular
session. Therefore this pilot cannot validate the original regular-session
execution basis or classify its net-return hypothesis as supported.
The reversal proposal was selected for its one-session feedback horizon, not
because the deferred historical studies established it as the best performer.
Alpaca describes daily bars as aggregates and IEX as a separate exchange feed
in its [bars reference](https://docs.alpaca.markets/us/reference/stockbars).

The protocol fixes these choices before the first signal close:

| Choice | Frozen rule |
| --- | --- |
| Universe | QQQ and SPY; no symbol substitution |
| Cohort | 30 consecutive returned market-calendar signal sessions, 60 symbol opportunities |
| Signal | Strictly negative completed provider close-to-close change; zero and positive changes abstain |
| Source availability | Returned extended-session close plus 900 seconds, checked against the bars receipt clock |
| Prediction deadline | 300 seconds before the next returned extended-session opening, before the earliest possible entry-bar price |
| Response | Next daily-bar opening price to the following returned session's daily-bar opening price |
| Overlap | Per-symbol candidate intervals cannot overlap; adjacent intervals may meet at their boundary |
| Cash | Zero price return; no interest assumed |
| Matched control | Equal-weight QQQ/SPY opening-price return, identical dates and one unit of gross exposure |
| Arithmetic | Decimal precision 60, round half even; signal sign compares the exact source prices |
| Coverage minimum | 12 observed candidates, an operational minimum rather than a statistical power calculation |
| Positive descriptive result | Both mean candidate gross response and mean excess over the matched control are strictly positive |
| Economic support | Always `NOT_EVALUABLE` in this pilot; net return and realized trade P&L remain absent |
| End of pilot | Manual review; no automatic extension, tuning, promotion or policy change |

A first eligible capture permanently records the opportunity. Missing inputs
seal a deferral; later corrected inputs cannot turn it into a successful
prediction. A capture after the deadline records a missed opportunity without
reconstructing its signal. Every planned opportunity stays in the denominator.
Consequently an incomplete cohort cannot become a positive result through
selection of the remaining observations.

Outcomes wait until the exit day's complete source session plus 900 seconds.
They append to the retained prediction. Missing candidate or control prices
leave the outcome pending; a later capture may supply it. Recorded outcomes
are immutable. Later source versions are retained as new evidence but do not
rewrite a prediction or outcome. Automated correction is deliberately absent.

During collection the conclusion is `PENDING`. After the cohort ends, missing
opportunities or outcomes produce `INCONCLUSIVE_MISSING_EVIDENCE`; fewer than
12 measured candidates produce `INCONCLUSIVE_TOO_FEW_CANDIDATES`. Otherwise the
result is `DESCRIPTIVE_POSITIVE_PROXY_ONLY` or `DESCRIPTIVE_NONPOSITIVE_PROXY`.
QQQ, SPY, and adjacent sessions are correlated. No confidence probability,
statistical significance, annualized return, account P&L or market-wide edge
is inferred from these observations. A positive gross result only warrants a
manual review of whether further testing is justified. A nonpositive gross
comparison argues against pursuing this particular implementation of reversal.

## Read the experiment

The configured local experiment journal is separate from all previous mission,
historical research, investment and runtime storage:

```text
output/prospective-reversal-pilot-2026-10-14/journal
```

From the repository root, inspect and verify it offline:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python3.11 \
  -m blackpod_build_week.shadow_experiment_cli status \
  --experiment-root output/prospective-reversal-pilot-2026-10-14/journal

PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python3.11 \
  -m blackpod_build_week.shadow_experiment_cli verify \
  --experiment-root output/prospective-reversal-pilot-2026-10-14/journal
```

Launch the existing Cabin reader with the explicit experiment root:

```bash
make cabin-live \
  SHADOW_EXPERIMENT_ROOT="$PWD/output/prospective-reversal-pilot-2026-10-14/journal"
```

Open [the research view](http://127.0.0.1:5174/?view=research). It works without
a mission configuration. It displays the frozen protocol, all 60 scheduled
opportunities, saved predictions and reasons, linked outcomes, benchmark
comparisons, evidence clocks and journal integrity. Refresh reads local saved
records only. It never acquires prices or starts a calculation, worker or
mission. An absent or invalid journal shows an explicit unavailable state,
without substituting a fixture or another experiment.

`CABIN_LIVE_PORT` can select another loopback port. An already running reader
must be restarted with `SHADOW_EXPERIMENT_ROOT` to enable the new view. The
underlying endpoint is the fixed read-only
`GET /live/shadow-experiment/current.json`. Mutation methods are rejected.

## Capture observations

Collection is an explicit operation independent of the UI. The production CLI
has no recording-time override. It checks the selected local runtime is OFF,
verifies the existing journal, reads credentials without printing them, and
uses only these bounded GET endpoints:

- `https://paper-api.alpaca.markets/v2/calendar`
- `https://data.alpaca.markets/v2/stocks/bars` with QQQ/SPY, 1Day, IEX, raw prices,
  ascending order and a fixed 1,000-row response limit.

Each call refuses redirects, ambient proxies, oversized or malformed bodies
and credential echoes. There are no account, positions, orders, broker writes,
model calls or execution paths. Sources, exact GET parameters, receipts, hashes,
source clocks and calculation code are retained by the existing append-only
JournalStore. Capture failure returns a sanitized error and does not invent a
prediction. A subsequent successful capture records any elapsed opportunities
as missed. Command/automation failures should be reviewed separately; they are
not fabricated as successful source receipts.

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python3.11 \
  -m blackpod_build_week.shadow_experiment_cli collect \
  --experiment-root output/prospective-reversal-pilot-2026-10-14/journal \
  --runtime-root output/auto-trading-runtime \
  --credentials-file /Users/nikolai/buried_treasure/api_keys.yaml \
  --credential-format GALACTICA_YAML
```

Run after 20:15 New York time and before the next source session's 03:55 New
York deadline. The scheduled collection uses 18:30 Los Angeles time, including
weekends, to capture completed data before the next possible source opening.
The machine and Codex scheduler must be available; missed deadlines stay
missed. Collection stops making provider calls once the completed cohort has
no pending rows. Pending outcomes can still be appended later, without
backfilling valid predictions. Future outcomes cannot be collected ahead of
their scheduled availability.

The original freeze command is:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python3.11 \
  -m blackpod_build_week.shadow_experiment_cli freeze \
  --experiment-root output/prospective-reversal-pilot-2026-10-14/journal \
  --runtime-root output/auto-trading-runtime \
  --experiment-id prospective-reversal-pilot-2026-10-14 \
  --first-signal-session 2026-10-14 \
  --hypothesis-file output/research-acceptance-real-001/journal/evidence/387f11c3babe1f32e612fa1d09827ff4d40697abe54a7add0913b076d0fb4885 \
  --credentials-file /Users/nikolai/buried_treasure/api_keys.yaml \
  --credential-format GALACTICA_YAML
```

An exact freeze retry reads the original record without fetching or rewriting
it. Changing its identity, dates or source hypothesis is rejected. A new trial
requires a separate root and protocol; creating further trials during this
pilot is outside the agreed experiment.

## Integrity and recovery

Journal events use additive `blackpod.decision_journal_event.v25` envelopes.
The protocol event contains the exact old hypothesis, calendar and receipt,
plus nine calculation and capture source files. Observation events contain
exact new source bodies and receipts, immutable prediction rows and linked
outcomes. Every journal scan replays the fixed arithmetic and source bindings.
Earlier v1 through v24 meanings and qualification gates are unchanged.

JournalStore supplies hash-chain checks, deterministic identities, exact retry
idempotency, conflict detection, evidence-first durable publication and
interruption recovery. An interrupted publication may leave verified orphan
evidence, never a partially committed event. Root/path guards keep captures
away from mission, source, credential and installed runtime storage. Concurrent
conflicting captures fail closed and can be retried against the verified head.

Changing pinned source code invalidates continuation rather than silently
changing the method. Retain this revision to replay the pilot. Local clocks
and receipts are not independently authenticated timestamps; the journal proves
retained-byte consistency, not provider truth or third-party preregistration.
The journals are ignored by Git and remain local; preserve the complete root
when backing up, including evidence. No retention deletion is added.

The previous 450 deferred historical opportunities, unresolved feed, cost,
continuity, risk and uncertainty gates, and withheld historical holdout remain
unchanged. Desk budgets and ownership are not activated. The next step is to
collect this cohort and review its result, with no further architecture burst.

## Initial capture and validation results

The real protocol was frozen at **2026-10-14 15:44:44.726723 UTC**, before the
first regular signal close. The returned calendar fixes October 14 through
November 24 as the 30 signal sessions, with the last exit proxy on November 27.
It includes the November 27 early closure. The original source hypothesis SHA
is `387f11c3babe1f32e612fa1d09827ff4d40697abe54a7add0913b076d0fb4885`;
the new frozen protocol SHA is
`b965ec0e8e1ad2cd57e356b8ecdcdd1fb1b352f54a7bc041f5a7cf3ddf0a111c`.

One calendar GET froze the protocol. Two further GETs retained the initial
calendar and one October 13 daily bar for each symbol. The first bars receipt
was captured at **2026-10-14 15:44:56.800745 UTC**. The journal has **2 events,
18 retained blobs, no orphan evidence and no staging orphans**. Its initial head
is `64f2893f2cab7ff96013b09947a53a7d7af18ed64e964e686f633bf3467cd234`.
There are **0 recorded predictions, 60 pending predictions and 0 outcomes**;
the first signal session has not completed. These are real calendar/source
captures, not real performance evidence.

The prior catalog's first entry and exact source hypothesis were checked by
hash and semantic replay. This does not claim a new full replay of its later
260-event historical descendant. Neither that descendant nor its decisions
was modified.

The active Codex thread follow-up, **Collect BlackPod reversal pilot**, captures
daily at 18:30 Los Angeles time, with a schedule cap after December 4. It stops
collection after completed rows are resolved and calls for manual review.
Scheduler/application availability is required; this is a local collector,
not a deployed always-on service. Auto-trading was checked OFF before and
after the real captures. No orders, broker account queries or inference ran.

Validation passed on the implementation revision:

| Gate | Actual result |
| --- | --- |
| Broad selected Python regression run | 316 passed, no failures/errors/skips |
| Final focused experiment run | 67 passed, including exact reader integration and complete-pilot criteria boundary cases |
| Reader and Sentry compatibility run | 67 passed; overlaps the other runs |
| Distinct Python cases across these runs | 348 passed: 67 new experiment cases, 281 preserved cases |
| Full UI suite | 1,181 passed in 66 files: 53 new, 1,128 preserved |
| Production UI build | Passed; existing large-renderer bundle warnings remain |
| Browser inspection | Real pending journal and complete authored fixture; desktop and mobile passed |
| Real journal verification | Passed, 2 events and 18 evidence blobs |

The focused commands are:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests .venv/bin/python3.11 \
  -m unittest discover -s tests -p 'test_shadow_experiment*.py' -q

PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests .venv/bin/python3.11 \
  -m unittest test_shadow_experiment_reader test_cabin_reader \
  test_sentry_scan_reader test_sentry_research_reader -q

NODE_OPTIONS=--no-experimental-webstorage npm --prefix ui test -- --reporter=dot
npm --prefix ui run build
```

The broad run selected `test_shadow_experiment*.py`, `test_decision_journal*.py`,
`test_cabin_reader.py`, `test_cabin_context.py`, `test_trading_hypothesis_contracts.py`,
`test_reconciled_shadow_qualification_journal.py`, and
`test_research_acceptance_state.py`. Its per-test log and summary are retained
under `output/prospective-shadow-validation-001/`. This is a selected safety
and compatibility run, not a claim that every Python test in the repository ran.

Authored fixtures exercise the complete 30-session lifecycle, paired controls,
positive/nonpositive/incomplete criteria, missing data, late capture,
premarket leakage, receipt clocks, exact arithmetic, hash conflicts,
interrupted publication and read-only HTTP boundaries. Only these fixtures
currently supply outcomes. The real journal also passed through the Cabin
reader and frontend validator without changing journal bytes or modification
times; the UI correctly displays all metrics as unavailable. Browser images
are retained in `output/playwright/shadow-experiment-*-real-pending.png`.
