# Native evidence-closure validation

This checkpoint records a descriptive offline review, not completed evidence
closure or a validated trading strategy. Auto-trading remains **OFF**. No
provider, broker, order, inference or capital operation is part of this burst.

## Coverage and verification

The runnable example preserves the exact prior 84-event authored fixture and
adds 19 records, giving 103 events. It covers a misleading complete checklist
that cannot replace native coverage, a later native candidate that resolves
only native prerequisites, a separately authored wide observation with an exact
source witness and cost-bound deferral, and a partial capture with retained
missing-window counts. Source numbers and confidence, horizons, hypotheses,
evaluations and P&L are not invented for historical records.

The example's sources are **synthetic fixtures**. They do not authenticate a
provider response, fee/slippage schedule, opening capacity or reviewer identity.
New wide-quote bytes have distinct source identities. Existing bars, original
quote bodies, hypotheses and policies remain unchanged.

New contract, pure engine, diagnostics, journal, CLI and example tests cover
strict schemas, original-method replay, exact candidate scope, native reason
comparison, incomplete capture, opaque supplemental leaves, retained exact
source bytes, precise extrema witnesses, admission reconciliation, false
authority, safe writes, exact retry, immutable conflicts and recovery. Final
source-stable gates passed **544 designated cases**: 449 preserved regressions
and 95 new cases. A supplementary focused rerun of the same early-destination
guard is excluded from that rollup. These are the selected suites for this
burst, not a claim that the entire repository test collection was rerun.

| Final suite | Cases | Observed result |
| --- | ---: | --- |
| Existing journal core and immutable field compatibility | 70 | PASS, 0.711 s |
| Existing runtime, ModelDock and mission boundaries | 200 | PASS, 1.629 s |
| Existing v18 qualification | 112 | PASS, 203.791 s |
| Existing v20 consumer, journal, CLI and examples | 67 | PASS, 697.287 s |
| New closure contract and pure engine | 29 | PASS, 123.364 s |
| New quote diagnostics | 26 | PASS, 14.918 s |
| New closure journal, CLI and examples | 40 | PASS, 604.170 s |

Exact new suite commands:

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests .venv/bin/python3.11 -m unittest test_native_evidence_closure -q
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests .venv/bin/python3.11 -m unittest test_native_quote_diagnostics -q
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests .venv/bin/python3.11 -m unittest test_native_evidence_closure_journal test_native_evidence_closure_cli test_native_evidence_closure_example -q
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests .venv/bin/python3.11 -m unittest test_native_evidence_closure_example.NativeClosureExampleTests.test_source_tree_destination_rejected_before_any_fixture_work -q
```

Exact preserved regression commands, in the same order as the table:

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests .venv/bin/python3.11 -m unittest test_decision_journal_contracts test_decision_journal_store test_decision_journal_field_access -q
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests .venv/bin/python3.11 -m unittest test_auto_trading_runtime test_trading_automation test_paper_order_capture test_modeldock_config test_modeldock_client test_modeldock_preflight test_modeldock_delivery test_contracts test_mission_store test_mission_transitions -q
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests .venv/bin/python3.11 -m unittest test_trading_continuity_qualification test_trading_training_calibration test_trading_evidence_qualification test_trading_evidence_qualification_cli test_trading_evidence_qualification_example -q
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests .venv/bin/python3.11 -m unittest test_segmented_evidence_qualification test_segmented_evidence_qualification_journal test_segmented_evidence_qualification_cli test_segmented_evidence_qualification_example -q
```

## Files changed

Sixteen files comprise this burst. Only the following three existing files are
modified; the remaining thirteen are additive. Existing source-pinned native
methods, mission transitions, ModelDock configuration, trading controls and
Navigator behavior are unchanged. No dependency, database migration, live hook
or new agent is introduced.

The final audit of all 783 previously tracked files confirmed exactly these
three existing-file changes. Independent runtime status remained OFF, with
order-entry controls, capital transfers and the runtime worker disabled. The original 255 source
entry bytes exactly match the new working-copy prefix.

| Existing file | Change |
| --- | --- |
| `README.md` | Link the descriptive review guide and validation record |
| `src/blackpod_build_week/contracts/decision_journal.py` | Add strict journal v21 dispatch |
| `src/blackpod_build_week/decision_journal_store.py` | Add exact native review replay validation |

| New file | Responsibility |
| --- | --- |
| `src/blackpod_build_week/contracts/native_evidence_closure.py` | Strict request, supplemental packet, result and event contracts |
| `src/blackpod_build_week/native_evidence_closure.py` | Pure retained-source verification and descriptive comparison |
| `src/blackpod_build_week/native_quote_diagnostics.py` | Reconciled native admission and exact extrema witnesses |
| `src/blackpod_build_week/native_evidence_closure_journal.py` | Original-parent append-only review projection |
| `src/blackpod_build_week/native_evidence_closure_cli.py` | Explicit offline lifecycle and bounded typed-leaf loading |
| `src/blackpod_build_week/native_evidence_closure_example.py` | Four authored scenarios preserving the old prefix |
| `tests/test_native_evidence_closure.py` | Strict contract, scope, candidate and missing-source tests |
| `tests/test_native_quote_diagnostics.py` | Precise native reconciliation, witnesses and failure boundaries |
| `tests/test_native_evidence_closure_journal.py` | Immutable storage, retries, conflicts and recovery |
| `tests/test_native_evidence_closure_cli.py` | Offline commands, source loading and path guards |
| `tests/test_native_evidence_closure_example.py` | Original-history preservation and authored publication cases |
| `docs/NATIVE_EVIDENCE_CLOSURE.md` | Architecture, interfaces and runnable commands |
| `docs/NATIVE_EVIDENCE_CLOSURE_VALIDATION.md` | Observed tests, real/fixture distinction and unresolved evidence |

## Runnable artifact checks

The persistent example command in the guide completed with 103 entries, 291
evidence blobs, zero evidence or staging orphans, and last envelope SHA
`83ccbac4a93602569cd2b4fcfb46e0920e8a8a2e0a17f4f5188c7fd136da688a`.
The documented `assess` command succeeded without appending. The documented
`record` retry returned `written=false`, original sequence 100 and original
review event
`journal-event-5e5c9dbf2133eeee45f804f2322d2ff09933f041e1b8f0838aa76be435b75ef1`
after three later reviews. The separate documented `verify` command retained the
same counts, zero orphans and last hash. All three commands returned zero
provider calls and auto-trading false.

During development, a deliberate new method-pin edit made an in-flight retry
fail closed. Those preliminary results were not accepted as the final gate.
The first durable example invocation was interrupted during whole-suffix
preflight after that source change, with zero entries published. The same
destination was safely regenerated with final pins. A meaningful test also
identified missing early rejection of Git source destinations in the new
example helper; the new helper now rejects both Git source/metadata and installed
runtime ancestors before calculation or publication. The final focused guard
test passed (one test, 31.278 seconds). No original source-pinned module or
production behavior was changed to address these findings.

## Existing real source corpus

The selected real native qualification remains the original 255th event:
`journal-event-cac9e53491dfd78ea12bb4bcf9259c2656d1c1554a74017ad869b4555f461e1c`.
Its original source journal had 255 entries, 2,122 retained evidence blobs and
zero evidence or staging orphans. Its exact v20 output is
`DEFER_EVIDENCE_QUALIFICATION`; a supplemental review cannot promote it.

The previously captured source comprises 228 TRAIN sessions and 456 symbol /
session pairs, 390 retained successful GET pages, 2,506,098 native quote rows,
and 2,480,759 admitted rows. All planned pairs had admitted coverage; 25,339 raw
rows were retained but not admitted under the existing native rule. This burst
uses these retained records offline and performs no new acquisition. Complete
quote collection does not establish corporate-action effective-date coverage.

| Symbol | Retained raw rows | Admitted rows | Original maximum spread, bps | Minimum reported native side size |
| --- | ---: | ---: | ---: | ---: |
| QQQ | 1,548,414 | 1,540,429 | 4000.562153046166818917 | 1 |
| SPY | 957,684 | 940,330 | 6918.586083112967718035 | 1 |

The independent offline native diagnostic run completed successfully, with exact
segment-summary and fold-extrema reconciliation. Rejected rows total 25,339.
Overlapping reasons are 25,152 non-regular conditions, 99 crossed prices, 187
nonpositive prices and 187 nonpositive reported sizes; these counts deliberately
do not sum to the rejected-row total.

| Symbol | Rejected rows | Spread-only >1,000 bps at 1x | At 2x | At 4x |
| --- | ---: | ---: | ---: | ---: |
| QQQ | 7,985 | 434 | 1,746 | 2,154 |
| SPY | 17,354 | 1,532 | 3,480 | 3,854 |
| Total | 25,339 | 1,966 | 5,226 | 6,008 |

The exact original maximum-spread witnesses are:

- QQQ: 2023-10-04T13:30:00.39159793Z, bid 284.61 / ask 426.94,
  reported bid/ask size 1 / 1. The first tied row is `/quotes/QQQ/76` in
  `source/attempt-000005.body.raw`, body SHA
  `8a3e983c4248f4d1b00b92d9c5ed7a87e60496291495f9f952f108f8da02deea`.
  Canonical lexical-row SHA is
  `2d986567ef9f62abd3362da5b39737fa9a1580d0e26481c4bfcafc45fd0fd5de`.
- SPY: 2024-04-04T13:30:15.914678016Z, bid 256 / ask 526.79,
  reported bid/ask size 15 / 10. The row is `/quotes/SPY/826` in
  `source/attempt-000250.body.raw`, body SHA
  `bf5e6ffde3329eb7ef59006c2d53d51158bb6bc1eaad0b7e330cfc007699f827`.
  Canonical lexical-row SHA is
  `2245df2be3404a4f04a440b968eb77b34b4bd75c277accd917bed65a4399401c`.

Both witnesses satisfy the existing native admission predicates, including the
regular `R` condition. Their causes and economic applicability remain
unresolved. They are neither automatically labeled corrupt nor removed from
the original admitted sample. The original raw body and exact row pointer
remain the source of truth.

Native maxima are retained without clipping or relaxed cost bounds. Descriptive
spread-only 1x/2x/4x exceedance counts must not be presented as the full stressed
cost model, fees, slippage, fill capacity, executable order sizing, economic
support or proof of data quality. Source URLs, capture clocks and raw receipts
remain unauthenticated declarations. The final holdout remains unscored rather
than technically access-sealed.

## Remaining native prerequisites

The real source already reports these eight native reasons:

- `EXPLICIT_SIMULATION_RISK_REVIEW_UNQUALIFIED`
- `INDEPENDENT_EFFECTIVE_DATE_COVERAGE_UNVERIFIED`
- `NO_COMPARABLE_CONTINUITY_WINDOWS`
- `NO_JOINT_CONTINUITY_SIZING_CAPACITY_WINDOWS`
- `QUALIFICATION_POLICY_NOT_REVIEWED_FOR_SHADOW`
- `RISK_REVIEW_NOT_APPROVED_FOR_SHADOW`
- `TRAINING_COST_AND_CAPACITY_ASSUMPTIONS_MISSING`
- `UNCERTAINTY_STABILITY_PROTOCOL_MISSING`

The review must preserve them until an actual later native qualification changes
its immutable source evidence and results. The v19 export's optional coverage
packet remains separate and cannot upgrade inherited native continuity windows.
The shadow policy's review status is not authenticated human approval. Quotes
alone cannot supply missing fee/slippage assumptions or opening capacity. No
uncertainty statistics or strategy returns are computed here.

Full semantic replay of the real corpus remains operationally expensive. The
new review preserves original source verification and does not create a
persistent trusted verification cache or a shortcut around evidence checks.

## Supplemental real source review

The real review is recorded with ID
`retained-real-native-evidence-closure-001`, no candidate, and the exact original
native anchor. Its supplemental packet,
`retained-real-native-source-review-001`, records current public documentation
notes concerning corporate-action query semantics, paper simulation, native
quote-size changes, regulatory fees and an issuer SPY scheduled-action challenge.
These notes are separately retained declared sources, not authenticated provider
capture or historical economic applicability proof. Four categories remain
`UNRESOLVED`; only `WIDE_SPREAD` records `SOURCE_REVIEW_RECORDED`. Neither status
clears a native reason or approves a policy.

| Public reference retained in the authored review note | Remaining applicability limitation |
| --- | --- |
| [Alpaca corporate actions](https://docs.alpaca.markets/us/v1.1/reference/corporateactions-1) | Process-date pagination does not establish full historical effective-date coverage |
| [Alpaca paper simulation](https://docs.alpaca.markets/us/docs/paper-trading) | Simulator fill behavior does not establish historical IEX costs or opening capacity |
| [CTA/UTP quote-size display change](https://docs.alpaca.markets/us/v1.1/changelog/marketdata-bid-and-ask-size-display-change) | November 2025 size documentation does not establish units for retrospectively delivered 2023–2024 IEX observations |
| [Alpaca regulatory fees](https://docs.alpaca.markets/us/v1.1/docs/regulatory-fees) | Current fee documentation does not establish historical effective rates or account-specific arrangements |
| [Issuer SPDR distribution schedule](https://www.ssga.com/library-content/products/fund-data/etfs/us/distribution/SPDR_Dividend_Distribution_Schedule.pdf) | Scheduled-action occurrence, title/publication timing and full historical inventory remain unverified |

The issuer challenge concerns a declared September 2026 scheduled ex-date in
the withheld final-holdout interval, not an observed missing TRAIN or TEST
action. Publication/date applicability uncertainty is retained. It does not
establish a full independent effective-date inventory. Current simulator, size
or fee documentation likewise cannot be silently applied to historical TRAIN
observations. No native continuity, cost, risk or policy record is changed by
this review.

The real journal is a physical working copy of the same verified original
255-event history, preserving original decision/event identities and entry
bytes. It is not a new decision history or live integration. Its source
`output/segmented-evidence-qualification-real-001/journal` remains unchanged.
Before any v21 append, its last hash was
`35693493736849a0fc00a2b09c8ac59aec5b0ce299fe4f895083d0491ce67e9c`.
The offline typed loader verified six declared leaves (supplemental review plus
five authored public-source notes), totaling 11,478 bytes. No native assumption,
policy, action, risk approval or uncertainty record was manufactured.

## Recorded real review

The working copy appended one v21 event at sequence **256**:
`journal-event-ddc9e6c0d1db7f31d4426ee77cac022acb57955f52c78fdd753235bf90e6a0b0`.
It retains original decision
`journal-decision-8ed91c576c9912b90ffd0984abae0edf6d6fe17b798e2ce16e44019b655660dd`
and declared review clock/cutoff `2026-10-13T21:04:33.643709Z`.
Its previous-entry hash is the original 255-event head above.

The result in
`output/native-evidence-closure-real-001/reports/review-001.result.v1.json` is
`DESCRIPTIVE_REVIEW_ONLY`, with no candidate and all eight original native
prerequisites persisting. Resolved and newly introduced native reason sets are
empty. The exact native qualification remains
`DEFER_EVIDENCE_QUALIFICATION`. All 2,506,098 raw quotes, 2,480,759 admitted quotes,
25,339 rejected rows, extrema and spread-only counts reconcile to the original
source summaries. No new eligibility, cost model, policy approval, uncertainty
statistic or economic support is produced. Execution is `NOT_EXECUTED`, realized
trade P&L is null, all authority flags are false and auto-trading is false.

Final full semantic verification **passed**, and the publication helper exited
0. The working copy contains **256 events and 2,138 evidence blobs**, with zero
evidence or staging orphans. Its last envelope SHA is
`4b482b2b9a8143a6b0d8262c2573c403fc9ff8e877eb788a5c1c8f6acc5f59c6`.
The summary confirms `written=true`, sequence 256 and all original entry bytes
preserved. The prior 255-entry source journal remains unchanged.

The independent retained-record retry also exited 0: **one event retried, zero
events written**, the same 256 entries and the same head hash. Original entry
bytes, including the recorded review, remain preserved. This retry uses the
exact retained `JournalEvent` and `append_journal_batch` with empty supplied
evidence. Its full locked scan revalidates retained source history and blobs;
it is not another CLI record invocation, provider call or reprojection. Both
helpers report zero provider calls, orders and model inference, with
auto-trading false.

Durable verification reports:

- `output/native-evidence-closure-real-001/reports/review-001.summary.v1.json`
- `output/native-evidence-closure-real-001/reports/exact-record-retry.v1.json`

Exact local helper invocations used for this retained-history validation:

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests .venv/bin/python3.11 -u /private/tmp/blackpod_record_native_closure_real.py
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests .venv/bin/python3.11 -u /private/tmp/blackpod_retry_native_closure_real.py
```

The first helper received literal `go` after original source verification and
the final source freeze. All designated offline suites completed before durable
publication. This permits the already authorized passive append;
it grants no trading or capital authority. These local validation helpers are
distinct from the supported public CLI. Both patch `socket.socket.connect` and
`subprocess.Popen` to fail, and neither adds a persistent trusted replay cache.
The portable CLI and authored fixture commands remain in the companion guide.

## Recommended next burst

Record an independently sourced, full-span effective-date coverage packet and
explicit reviewed cost/capacity assumptions through their native intake and
policy interfaces. Keep source applicability unresolved when evidence is
missing, preserve wide-spread observations, and rerun a new linked native
qualification with the frozen risk and uncertainty criteria. Keep auto-trading
OFF; do not run return scoring or activate trading authority before those native
prerequisites qualify. This recommendation is not implemented by this burst.
