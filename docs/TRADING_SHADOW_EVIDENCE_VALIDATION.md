# Burst 14 validation: governed real-data evidence and shadow risk review

Implemented October 12, 2026 Pacific, with actual UTC source timestamps below.
**Auto-trading remains OFF.** No Galactica trading rules, inference, order
submission, capital transfers, desk activation, migration or new dependency.
Four explicitly authorized read-only market-data GETs captured raw evidence;
the twelve ordinary CLI commands are offline and make zero provider calls.

## Changed files

Twelve new production files under `src/blackpod_build_week/`:

- `contracts/trading_evidence_capture.py`
- `contracts/trading_continuity_intake.py`, `trading_continuity_intake.py`
- `contracts/trading_cost_intake.py`, `trading_cost_intake.py`
- `contracts/trading_shadow_risk_review.py`, `trading_shadow_risk_review.py`
- `contracts/trading_shadow_review.py`, `trading_shadow_review.py`
- `trading_shadow_review_journal.py`
- `trading_shadow_review_cli.py`
- `trading_shadow_review_example.py`

Existing `contracts/decision_journal.py` and `decision_journal_store.py` gained
v16 parsing and replay dispatch. README, ARCHITECTURE and SAFETY_BOUNDARY gained
additive documentation. New documents: this report and `TRADING_SHADOW_EVIDENCE.md`.

Seven new tests: `test_trading_evidence_contracts.py`,
`test_trading_continuity_intake.py`, `test_trading_cost_intake.py`,
`test_trading_shadow_risk_review.py`, `test_trading_shadow_review_journal.py`,
`test_trading_shadow_review_cli.py`, `test_trading_shadow_review_examples.py`.

All seven previously pinned v15 calculation files remain byte-identical.
Original hypotheses, plan/dataset contracts, mission workflow, Navigator,
ModelDock configuration, trading policies, ownership and paper budgets were not
edited. The protected source/history baseline covers **3,537** pre-existing
files, all byte-identical. It excludes dependency trees and existing runtime
artifact/log trees rather than claiming control over independently active logs.

## Actual safe offline tests

**2,525 unique tests passed: 269 new + 2,256 prior regressions.** No failures in
the final runs; repeated targeted checks are not double-counted.

| New suite | Passed |
| --- | ---: |
| Shared receipts and study v2 contracts | 14 |
| Native continuity adapter | 36 |
| Native quote/cost adapter | 47 |
| Explicit sizing/risk review | 58 |
| v16 journal replay/recovery | 40 |
| Twelve CLI commands/integration | 54 |
| Complete governed fixtures | 20 |
| Total | 269 |

Exact final command:

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests .venv/bin/python3.11 -m unittest \
  test_trading_evidence_contracts test_trading_continuity_intake \
  test_trading_cost_intake test_trading_shadow_risk_review \
  test_trading_shadow_review_cli test_trading_shadow_review_journal \
  test_trading_shadow_review_examples -q
```

Actual final result: **269 tests in 302.004 seconds, OK**. Network and worker
creation are blocked where applicable. Coverage includes exact request/body
receipts, HTTP failures, pagination chains/cycles, native action schemas and
dates, outside-dataset actions, strict numeric parsing, opaque array origins,
nanosecond precision, distinct same-time quote updates, duplicate rejection,
upward-rounded spread bounds, coverage/assumption separation, whole-share
feasibility, future-price independence, review authority/statuses, immutable
original plans, prefix links, idempotency, scope/hash changes, forged results,
installed-code changes, interrupted publication and protected filesystem paths.

The full prior **2,256** safe offline tests also passed: the exact 1,846 module
arguments documented in [Burst 12](TRADING_HISTORICAL_RESEARCH_VALIDATION.md),
its 189 historical-research tests, and all 221 tests documented in
[Burst 13](TRADING_SHADOW_RESEARCH_VALIDATION.md). Earlier v1 golden hashes
remain unchanged. This was selected offline regression testing, not unrestricted
test discovery or broker/inference integration testing. `git diff --check` passed.

Real-source review corrected two undocumented ordering assumptions: corporate
actions grouped by symbol need not be globally process-date ordered; distinct
quotes can share an exact nanosecond timestamp. Duplicate identical quotes and
descending quote timestamps still reject. A standalone continuity verifier was
also corrected to interpret only its reserved request document, keeping arbitrary
origin JSON arrays opaque. Risk rationale is now preserved in assessment provenance.

An interim test ran while that new calculation source was being finalized and
correctly failed the installed-source pin comparison. The complete final suite
above ran against the stable final files and passed. The first development
fixture retains its original source snapshots and an explicit development note;
it was not rewritten to disguise the version change.

## Read-only actual captures

Raw source root: `output/trading-research-evidence-source-001`. Existing authorized
Alpaca credentials were read in memory; no key value or authentication header
was printed or retained. Redirects and proxies were disabled. Every body was
bounded and checked for credential echoes before immutable publication.

| Capture | Query and observed result |
| --- | --- |
| Corporate actions | GET `https://data.alpaca.markets/v1/corporate-actions`; `symbols=QQQ,SPY`, `start=2023-09-01`, `end=2026-10-12`, `limit=1000`, `sort=asc`, types omitted. HTTP 200; 26 cash-dividend records, terminal token. Captured `2026-10-13T03:55:20.144669Z`; 6,159 bytes. |
| Opening quote page 1 | GET `https://data.alpaca.markets/v2/stocks/quotes`; `symbols=QQQ,SPY`, `start=2026-10-12T13:30:00Z`, `end=2026-10-12T13:31:00Z`, `limit=10000`, `feed=iex`, `currency=USD`, `sort=asc`, `asof=-`. HTTP 200; QQQ 8,763 and SPY 1,237 records, continuation token. Captured `2026-10-13T03:55:21.176340Z`. |
| Opening quote page 2 | Same base query with the exact previous token. HTTP 200; SPY 10,000, another token. Captured `2026-10-13T03:57:51.730270Z`. |
| Opening quote page 3 | Same base query with the exact previous token. HTTP 200; SPY 1,470, terminal token. |

The endpoint's process-date filter does not prove full effective-date coverage.
The adapter requires a separate coverage review, as supported by the
[corporate-action API semantics](https://docs.alpaca.markets/us/v1.1/reference/corporateactions-1).
Quote pagination applies across the selected symbols; each native page and token
was retained according to the [historical quote interface](https://docs.alpaca.markets/us/reference/stockquotes-1).

The existing verified **760-session QQQ/SPY dataset** was reused without changes.
The adapter retained **26 native actions: 24 mapped discontinuities and two
earlier actions outside the dataset**. Native pagination is complete and the
export is AVAILABLE, but the continuity review is **UNRESOLVED**: no independent
effective-date coverage review was invented and the raw series contains events.

Quotes total **21,470**, QQQ 8,763 and SPY 12,707. All meet this adapter's explicit
opening-minute quote-admission policy. **489 adjacent timestamps are shared by
distinct native updates**, all retained. Only one session per symbol is covered:
**1,518 symbol/session pairs remain missing** across the original dataset.
Observed sample spread bounds, rounded upward to eighteen decimals:

- QQQ: `601.096540960207035471` bps.
- SPY: `600.566281227327884536` bps.

These large sample bounds are retained, not clipped or represented as ordinary
execution costs. Slippage/fee assumptions are absent. The cost review stays
**UNRESOLVED**, with no complete cost source or invented zero-cost model.
Even after other evidence clears, 4× these observed bounds exceeds the existing
generic engine's supported 1,000 bps component cap; that boundary would defer.

## Explicit inactive sizing/risk proposal

Two retained reviews propose the following standalone simulation declarations:

| Declaration | Proposed value |
| --- | ---: |
| Simulated cash | USD 10,000 |
| Per-symbol notional | USD 1,000 |
| Maximum order notional | USD 1,000 |
| Maximum position fraction | 0.10 |
| Maximum gross fraction | 0.20 |
| Known daily-volume participation fraction | 0.01 |
| Source staleness bound | 604,800 seconds |

Status is **PROPOSED**, reviewer ID `codex-shadow-proposal`. These values are
neither optimized sizes nor current account buying power. They do not use or
activate the recorded desk budgets. Original source plans still declare USD
1,000/$100 simulation cash/order caps. Both original and proposed risk are
visible in the reports; proposed risk is not applied to production.

The proposed whole-universe notional is USD 2,000, equal to the initial-cash
gross cap. There is no assumed fee/gap reserve or guaranteed fill. Each hypothesis
review finds **450 feasible known-close sizing opportunities**, with no quantity
autotuning. Feasibility does not clear `RISK_REVIEW_NOT_APPROVED_FOR_SHADOW`.
New approval must be a new linked record; original proposals cannot be rewritten.

## Final artifacts and actual study outcomes

| Final run | Events / retained blobs | Outcome |
| --- | ---: | --- |
| `output/trading-research-governed-evidence-example-002/journal` | 14 / 53 | Authored 40-session, 80-quote controlled fixture; approved toy reviews and complete fixture evidence exercise both hypotheses and cost stresses. |
| `output/trading-research-governed-evidence-real-001/journal` | 14 / 53 | Native source evidence and two inactive risk proposals; both real-history studies DEFER. |

Both journals verify with zero evidence/staging orphans. Final hashes:

- Fixture: `90fec4d03eb27014ebf5863383ebbdd9442e13510264017559eadab39b166aef`.
- Real: `7cec4dbbeb1f0b64a10b2c1690664e45a922ac6e7b6c907710b47d8d0cc4b8a4`.

Fixture continuation generates four episodes/eight intents; reversal six/twelve.
At each cost stress, eight/twelve candidate fills respectively are compared
with matched arithmetic controls. Continuation fails the cash comparison at
all stresses; reversal has positive descriptive signs at 1×/2× but fails at 4×.
This is constructed verification behavior, not real-security performance, alpha
or a selected strategy. Final holdout remains unscored.

Both real-history studies produce **zero intents, episodes, fills or cost-stress
scores**. Their retained gate reasons include unresolved continuity/cost,
missing explicit cost assumptions, unverified effective-date coverage, missing
opening-minute coverage, declared discontinuities and risk-review nonapproval.
No missing historical hypothesis, expectation, probability or evaluation was
invented. Realized trade P&L stays null.

Seventeen earlier valid journals reverified unchanged: **136 events / 673
per-journal retained blobs**, zero orphans and original chain hashes. This
includes the final v15 fixture and real-history journals. All sixteen calculation
source files for v16 are retained/pinned; the old seven remain unchanged.

## Exact commands and reporting

Executed from the repository root:

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests .venv/bin/python3.11 -m blackpod_build_week.trading_shadow_review_cli export-continuity \
  --request output/trading-research-evidence-source-001/continuity.request.v1.json \
  --evidence-root output/trading-research-evidence-source-001 \
  --output-directory output/trading-research-governed-evidence-real-001/continuity

PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests .venv/bin/python3.11 -m blackpod_build_week.trading_shadow_review_cli export-cost \
  --request output/trading-research-evidence-source-001/cost.request.v1.json \
  --evidence-root output/trading-research-evidence-source-001 \
  --output-directory output/trading-research-governed-evidence-real-001/cost

PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests .venv/bin/python3.11 -m blackpod_build_week.trading_shadow_review_example \
  --output-root output/trading-research-governed-evidence-example-002

PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests .venv/bin/python3.11 -m blackpod_build_week.trading_shadow_review_cli verify \
  --journal-root output/trading-research-governed-evidence-real-001/journal
```

The actual real-data workflow copied the verified six source events/evidence by
immutable append into a separate journal, then dispatched `record-continuity`,
`record-cost`, `record-risk`, `prepare`, `register`, `record`, `render`, `verify`
through the same CLI `main(argv)` entry points. Intake record clocks are
`2026-10-13T04:23:43.381115Z` and `2026-10-13T04:23:50.654685Z`.

For h1, `prepare` used base event
`journal-event-18b31ee2e469466dd078b708b506a12dceb79e9d57002243c6f52a0eb1c854a1`,
risk event `journal-event-92b56c90252f2ff606396c94f7c2569521b91dc8f6ccca72857ed1ec6b6316e7`,
continuity event `journal-event-5d9676c636f0f7926c4e53bdf0c1b64cca879210ab87742314f965dc9bd4b3d5`,
cost event `journal-event-e61eb7b749dee16e32afd6251746a2ec802f09b8278c28e07c613f9be963c1f9`,
study/experiment prefix `burst14-reviewed-history-h1`, clock
`2026-10-13T04:24:19.041547Z`, and output directory `study-h1` under the real root.
Risk recording used `risk-h1/risk-review.v1.json` and its evidence root. Register
and record used `study-h1/trading-shadow-review/study.v2.json` with `study-h1` as
evidence root; evaluation ID `burst14-reviewed-history-h1-evaluation`, clock
`2026-10-13T04:24:27.418631Z`. h2 uses its source-plan/risk IDs retained in the
journal and clocks `2026-10-13T04:25:31.938639Z` / `2026-10-13T04:25:45.628877Z`.
Both reports rendered under `reports/` with the verified evaluation event IDs.

The [guide](TRADING_SHADOW_EVIDENCE.md) contains all twelve full runnable CLI
commands. Every command was executed twice with isolated `/private/tmp` roots:
the walkthrough reached **16 events / 55 blobs / zero orphans**, the second run
had no append writes and unchanged artifact bytes/chain hash. HTML output escapes
external content and shows gate reasons, risk rationale, original versus
reviewed caps, sizing feasibility and cost sensitivity. Reports use sibling
`reports/` roots; a parent-directory request was correctly rejected.

The first source export attempt ran before the asynchronous exact-history copy
had finished and correctly failed without publishing. After the copy completed,
both final export commands above succeeded. Development fixture `example-001`
retains its pre-final helper snapshot and a development note; use `example-002`.

Read-only runtime status remains **OFF**, entries/requested entries false, worker
inactive and null mode/session. `output/auto-trading-runtime` is absent; this is
the uninitialized OFF state. No runtime was installed or activated.

## Remaining limits and recommended next burst

Continuity supports thirteen closed native groups; unfamiliar types/fields fail
closed rather than disappear. Process-date/default complete-record searches
cannot establish all effective-date or pending-action coverage. The current
policy rejects any declared discontinuity across the entire dataset; it does
not adjust prices or suspend individual intervals automatically.

Cost support is a retrospective maximum over a declared opening-quote sample,
not consolidated liquidity, auction fills, executable capacity or costs known
at every historical decision. Full-dataset bounds can include non-TEST and
holdout-session quotes; they do not establish prospective preregistration.
Slippage and fees remain explicit local assumptions and require separate review.
Partial samples cannot be extrapolated. Source hashes do not authenticate
reviewers/providers; source snapshots are not a general executable environment
archive or an independent external audit checkpoint. Replay requires compatible
version handling before changing pinned calculation files, and large raw
datasets make full verification more expensive.

Recommended next burst: **governed event-aware suspension/continuity treatment
and predeclared training-only cost/capacity calibration**, with an explicit
decision on the inactive simulation sizing proposal. Preserve original prices,
fail on unsupported events, retain calibration provenance, leave final holdout
unscored and auto-trading OFF. That next burst is not implemented.
