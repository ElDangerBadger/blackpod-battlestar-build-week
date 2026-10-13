# Segmented evidence qualification validation

Checkpoint work starts from `9fa244a` on October 13, 2026
America/Los_Angeles. The approved scope includes continued bounded TRAIN
acquisition and an additive offline segmented-evidence consumer. Auto-trading
remains OFF; acquisition progress is separate from research qualification.

The [consumer guide](SEGMENTED_EVIDENCE_QUALIFICATION.md) records inspected
interfaces, exact contract/method boundaries, source linkage, governance and
runnable offline commands. Original v18/v19 calculation files, prices,
hypotheses, raw evidence, mission/execution behavior and ModelDock routing
remain outside the editing scope.

## Implementation files

| File | Change |
| --- | --- |
| `src/blackpod_build_week/contracts/segmented_evidence_qualification.py` | New strict binding, request, calibration and qualification contracts. |
| `src/blackpod_build_week/segmented_evidence_qualification.py` | New exact-source consumer and joint design qualification. |
| `src/blackpod_build_week/segmented_evidence_qualification_journal.py` | New v20 source-linked binding and assessment records/replay. |
| `src/blackpod_build_week/segmented_evidence_qualification_cli.py` | New explicit offline preparation, recording, assessment and inspection commands. |
| `src/blackpod_build_week/segmented_evidence_qualification_example.py` | New authored mixed-version examples with safe exact-prefix publication/recovery. |
| `src/blackpod_build_week/train_market_capture_incremental.py` | New bounded invocation-only verified capture adapter. |
| `src/blackpod_build_week/decision_journal_batch.py` | New locked candidate-suffix preflight and immutable per-event publication. |
| `src/blackpod_build_week/contracts/decision_journal.py` | Additive v20 dispatch and immutable per-field access optimization. |
| `src/blackpod_build_week/decision_journal_store.py` | Additive v20 replay dispatch. |
| `src/blackpod_build_week/train_market_evidence_cli.py` | Explicit opt-in capture-cache and batch-publication flags; defaults preserve original paths. |
| `tests/test_segmented_evidence_qualification.py` | New strict-source qualification tests. |
| `tests/test_segmented_evidence_qualification_journal.py` | New journal replay, identities, retention and recovery tests. |
| `tests/test_segmented_evidence_qualification_cli.py` | New offline CLI tests. |
| `tests/test_segmented_evidence_qualification_example.py` | New representative cases, exact preservation and prefix retry tests. |
| `tests/test_train_market_capture_incremental.py` | Differential/inherited runner tests for the opt-in adapter. |
| `tests/test_decision_journal_batch.py` | New batch preflight, old-CLI behavior and interruption tests. |
| `tests/test_decision_journal_field_access.py` | New defensive field-cache and legacy-object compatibility tests. |
| `docs/SEGMENTED_EVIDENCE_QUALIFICATION.md` | Inspected interfaces, governing semantics and runnable commands. |
| `docs/SEGMENTED_EVIDENCE_QUALIFICATION_VALIDATION.md` | Evidence cases, actual validation and limitations. |
| `README.md` | New checkpoint usage and documentation links. |

The source fixture retains twenty-two original v18 events exactly. Two separately
identified missing-source policies and four authored v19 export groups exercise
the consumer without editing prior inputs. Seven new bindings and assessments
yield an 84-event mixed-version example. New bodies copy original synthetic
quote rows into unchanged TRAIN windows; no provider or real credential is used.
Its original-contract optional operational capture audit remains unselected and
explicitly limited; runner-backed actual capture is reported separately.

## Representative evidence cases

| Case | Expected scoped outcome | Evidence preserved |
| --- | --- | --- |
| Full reversal | Qualified study design | 24/24 authored TRAIN pairs; reviewed toy assumptions/native coverage; eight joint dates. |
| Partial reversal | Defer | 4/24 pairs; twenty missing pairs retained. |
| Terminal-empty reversal | Defer | All retrieval chains terminal, but 22/24 pairs. |
| Full continuation | Defer | Full quotes; six joint dates against the unchanged minimum of eight. |
| Proposed policy | Defer | Inactive policy and missing assumptions/protocol. |
| Missing assumptions | Defer | Complete quotes do not invent fees/slippage/capacity. |
| Missing independent coverage | Defer | Complete quotes do not create native continuity support. |

These are authored software-verification cases. Their different readiness states
do not rank strategy profitability, estimate confidence or establish an economic
edge. Later outcome evaluation must use separate governed records and preserve
the held-out partition.

## Focused offline example validation

Before the shared field-access optimization, the focused example suite passed:

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests .venv/bin/python3.11 \
  -m unittest test_segmented_evidence_qualification_example -q
```

Actual result: **15 tests, 315.972 seconds, OK**. The later post-optimization
combined run below also includes these cases. Tests block socket connections,
provider subprocesses and worker launches. They cover the seven evidence cases,
all authority flags disabled, unchanged original event/policy bytes, compact
consumer references without copying raw pages, separate quote/native coverage,
unselected operational audit, withheld holdout, mixed-version replay and zero
orphans. Full identical retry preserves file bytes/mtimes and never republishes;
retry from a copied valid 80-event prefix appends exactly the four missing
records without rewriting the original prefix. Retained journal-only replay
survives deletion of external input/evidence folders; symlink output rejects
before any artifact is written.

The new example publishes its missing suffix through the tested locked batch
adapter. This is immutable per-event publication after complete preflight;
interruption does not promise an all-or-nothing transaction. The original
`JournalStore.append` and pinned capture runner remain unchanged.

The durable authored example was generated successfully with:

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests .venv/bin/python3.11 \
  -m blackpod_build_week.segmented_evidence_qualification_example \
  --output-root output/segmented-evidence-qualification-example-001
```

Actual journal: **84 events, 230 retained evidence blobs, zero evidence or
staging orphans**. Its final entry SHA256 is
`6b984645dfa0b3ae6b94163e909761a4ba285439d760da3cec12bf913a7dd25b`.
The manifest, seven inputs and reports identify each exact policy, source export,
binding and qualification. Each case preserves its original hypothesis and
design; one reversal design qualifies within the toy research scope, while six
cases defer.

Standalone CLI verification and reassessment returned exit 0. Verification
confirmed the same 84/230 counts and chain hash. Reassessment was byte-identical
to the retained original report (SHA256
`e54e8dec3ecf0ed1f6f5b8272edbad2a5db9432e3b79007c34c01c1d1662866d`).
The identical `record` retry returned `written=false`, original sequence 72 and
event `journal-event-bc8e8494c6d32a9ab7a84290ef0279a62ee6c23bb206310605ac2926bd6cb724`.
The same retained journal was independently verified again after the final
shared field-access optimization: exit 0, unchanged 84/230 counts and chain
hash, with zero evidence/staging orphans.

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests .venv/bin/python3.11 \
  -m blackpod_build_week.segmented_evidence_qualification_cli verify \
  --journal-root output/segmented-evidence-qualification-example-001/journal

PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests .venv/bin/python3.11 \
  -m blackpod_build_week.segmented_evidence_qualification_cli assess \
  --request output/segmented-evidence-qualification-example-001/input/full-reversal.request.json \
  --journal-root output/segmented-evidence-qualification-example-001/journal \
  --output output/segmented-evidence-qualification-example-001/reports/full-reversal-reassessment.json

PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests .venv/bin/python3.11 \
  -m blackpod_build_week.segmented_evidence_qualification_cli record \
  --request output/segmented-evidence-qualification-example-001/input/full-reversal.request.json \
  --journal-root output/segmented-evidence-qualification-example-001/journal
```

## Original regressions and adapter validation

The 767-file preexisting baseline was compared after implementation. Changes
are confined to README, journal contract/dispatch and the explicit v19 CLI
flags listed above. Protected original calculation, mission, workflow,
execution, hypothesis/data, capture-runner and ModelDock files retain their
baseline bytes. The old v18/v19 source pins remain readable.

All sixteen original offline groups were rerun after the field-access
optimization and passed: **2,894 tests**, exit 0 in each group. Exact final
commands and observed counts follow.

| Group | Tests | Seconds | Result |
| --- | ---: | ---: | --- |
| accounting | 164 | 41.081 | OK |
| journal | 249 | 34.137 | OK |
| governance | 125 | 142.255 | OK |
| paper | 249 | 50.153 | OK |
| workflow | 172 | 2.588 | OK |
| forecast8 | 218 | 40.763 | OK |
| producer9 | 128 | 86.256 | OK |
| structured10 | 144 | 19.521 | OK |
| research11 | 164 | 8.579 | OK |
| research12 | 189 | 55.586 | OK |
| shadow7 | 233 | 184.405 | OK |
| shadow13 | 221 | 194.621 | OK |
| evidence14 | 269 | 391.351 | OK |
| acceptance17 | 123 | 507.140 | OK |
| qualification18 | 112 | 333.070 | OK |
| capture19 | 134 | 623.686 | OK |

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests .venv/bin/python3.11 -m unittest test_trading_accounting_contracts test_paper_activity_import test_trading_accounting_engine test_trading_accounting_store test_trading_accounting_cli test_trading_accounting_examples -q

PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests .venv/bin/python3.11 -m unittest test_decision_journal_contracts test_decision_journal_projection test_decision_journal_store test_decision_journal_cli test_investment_hypothesis_contracts test_investment_hypothesis_sources test_investment_hypothesis_store test_investment_hypothesis_examples test_investment_hypothesis_cli test_investment_review_contracts test_investment_review_engine test_investment_review_store test_investment_review_cli -q

PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests .venv/bin/python3.11 -m unittest test_investment_governance_contracts test_investment_governance_engine test_investment_approval test_investment_governance_store test_investment_governance_examples test_investment_governance_cli -q

PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests .venv/bin/python3.11 -m unittest test_trading_reconciliation_contracts test_trading_reconciliation_engine test_trading_reconciliation_store test_trading_receipts test_trading_reconciliation_cli test_paper_account_safety test_paper_order_capture test_trading_reconciliation_examples test_auto_trading_runtime test_galactica_trading_adapter test_trading_automation test_paper_account_probe -q

PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests .venv/bin/python3.11 -m unittest test_contracts test_mission_store test_mission_transitions test_mission_presentation test_cli_help test_navigator_adapter test_operator_adapter test_modeldock_config test_modeldock_client test_modeldock_preflight test_modeldock_delivery -q

PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests .venv/bin/python3.11 -m unittest test_forecast_intake_contracts test_forecast_intake_engine test_shadow_brigade_analysis test_forecast_brigade_journal_contracts test_forecast_brigade_store test_brigade_shadow_transport test_forecast_brigade_cli test_forecast_brigade_examples -q

PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests .venv/bin/python3.11 -m unittest test_shadow_quantitative_producer test_forecast_producer_contracts test_forecast_producer_export test_forecast_producer_examples test_forecast_producer_journal test_forecast_producer_cli -q

PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests .venv/bin/python3.11 -m unittest test_brigade_response_contracts test_brigade_structured_analysis test_brigade_structured_journal test_brigade_structured_transport test_brigade_structured_examples test_brigade_structured_cli -q

PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests .venv/bin/python3.11 -m unittest test_trading_research_contracts test_trading_research_evaluation test_trading_research_journal test_trading_research_cli test_trading_research_examples -q

PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests .venv/bin/python3.11 -m unittest test_trading_hypothesis_contracts test_trading_hypotheses test_trading_historical_intake_contracts test_trading_historical_intake test_trading_research_v2 test_trading_historical_journal test_trading_historical_cli test_trading_historical_examples -q

PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests .venv/bin/python3.11 -m unittest test_shadow_native_analysis test_desk_candidate_review_contracts test_desk_candidate_review_engine test_shadow_galactica_analysis test_desk_candidate_review_store test_desk_candidate_review_cli test_desk_review_sources test_desk_candidate_review_examples -q

PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests .venv/bin/python3.11 -m unittest test_trading_shadow_contracts test_trading_shadow_gates test_trading_shadow_intents test_trading_shadow_evaluation test_trading_shadow_journal test_trading_shadow_cli test_trading_shadow_examples -q

PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests .venv/bin/python3.11 -m unittest test_trading_evidence_contracts test_trading_continuity_intake test_trading_cost_intake test_trading_shadow_risk_review test_trading_shadow_review_cli test_trading_shadow_review_journal test_trading_shadow_review_examples -q

PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests .venv/bin/python3.11 -m unittest test_research_assessment_contracts test_research_acceptance_trading test_research_acceptance_investment test_research_acceptance_journal test_research_acceptance_cli test_research_acceptance_examples -q

PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests .venv/bin/python3.11 -m unittest test_trading_continuity_qualification test_trading_training_calibration test_trading_evidence_qualification test_trading_evidence_qualification_cli test_trading_evidence_qualification_example -q

PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests .venv/bin/python3.11 -m unittest test_train_market_capture test_train_market_export test_train_market_evidence test_train_market_evidence_cli test_train_market_evidence_example -q

```

Final new-path verification and compatibility results:

| Run | Tests | Seconds | Result |
| --- | ---: | ---: | --- |
| Consumer, journal, CLI, examples and adapters | 151 | 858.064 | OK |
| Final field access and existing core contracts/store | 70 | 0.771 | OK |

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests .venv/bin/python3.11 -m unittest test_decision_journal_field_access test_segmented_evidence_qualification test_segmented_evidence_qualification_cli test_segmented_evidence_qualification_journal test_segmented_evidence_qualification_example test_train_market_capture_incremental test_decision_journal_batch -q

PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests .venv/bin/python3.11 -m unittest test_decision_journal_field_access test_decision_journal_contracts test_decision_journal_store -q

```

The combined run started with eleven field-access tests. Two additional
legacy-format cases passed in the final thirteen-case field suite, together
with 57 existing core cases. Designated coverage is therefore **3,047 passing
cases = 2,894 original + 140 consumer/adapter + 13 field-access cases**.
This rollup counts each designated case once, rather than adding overlapping
reruns. A fresh invocation of the combined command includes the two added
cases. The consumer/adapter groups intentionally include inherited runner and
export-CLI behavior exercised through the new optional paths.

The incremental runner tests compare the opt-in adapter with original
checkpoint/transport behavior and inherited safety cases. The batch tests
cover full-suffix validation, immutable identities, unsafe paths, byte/event
bounds, lock/fsync interruption recovery and original export-CLI behavior with
the new optional path. The mixed-version example covers the seven source/gate
cases, exact old-history preservation and retained-only prefix recovery.
Original execution/provider test names refer to offline fixtures; they do
not mean broker calls or inference occurred.

An additional earlier v19 CLI rerun passed **10 tests in 77.331 seconds**
after final flag changes; the later 134-case group also includes that CLI.
That supplementary repetition is excluded from the rollup. Its command:

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests .venv/bin/python3.11 -m unittest test_train_market_evidence_cli -q
```

Two initial test expectations were corrected before passing reruns: a tamper
assertion now changes a native bound field, and the unsafe-ancestor case
expects the existing store exception family. No production behavior was
relaxed to make those assertions pass.

The first full real export exposed repeated whole-document decoding for scalar
attributes in the shared immutable journal document. Its field-access
optimization derives an immutable tuple of canonical per-field bytes from the
original document. Each getter still constructs fresh defensive values;
`to_dict`, canonical `to_bytes`, validators and stored schemas are unchanged.
Legacy objects missing the derived cache rebuild it from their original bytes.
Explicit object serialization retains only the canonical byte slot; legacy and
interim states reconstruct the derived cache from those bytes.
The shared journal file is outside the original v18/v19/v20 source-pin sets.
Final focused compatibility verification passed **13 new field-access cases plus
57 existing journal contract/store cases: 70 tests, 0.771 seconds, OK**.
Independent field-access review also passed all **13 cases in 0.197 seconds**.

The first actual full export was interrupted with exit 130 while validating its
complete candidate suffix. Its existing 25-event prefix remained intact and no
new event was published. The restart selected the same immutable snapshot and
export ID, using the equivalent field-access optimization; source validation was
retained in full. This interruption exercises safe batch preflight on the actual
large corpus, separately from the offline publication/fsync recovery tests.

## Actual TRAIN acquisition and source audit

The retained acquisition report is
`output/train-market-evidence-real-001/reports/acquisition-burst-002.json`.
The source capture remains separate from
`output/segmented-evidence-qualification-real-001/journal`. The latter preserves
the earlier v19 and v18 histories and adds linked source/consumer records; it
does not rewrite either earlier journal.

| Actual acquisition metric | Result |
| --- | ---: |
| Original TRAIN windows with terminal-success chains | 228/228 |
| Raw-observed symbol/session pairs | 456/456 |
| Total retained GET attempts/body-receipt pairs | 390 |
| New GETs during this continuation | 386 |
| Bounded continuation invocations | 13 |
| Total retained native quote rows | 2,506,098 |
| QQQ native rows | 1,548,414 |
| SPY native rows | 957,684 |
| New native rows during this continuation | 2,476,054 |
| Failed capture requests | 0 |
| Retained body/receipt bytes | 282,963,065 |
| All retained capture bytes | 284,461,202 |

These counts are acquisition observations, not admitted research coverage or
economic readiness. The original frozen plan remains
`journal-event-fb6aeddbd6352024d1bc4171f01b0dd619efac60f9952b60a239f4b628ee40ff`,
with SHA256 `f69b0185d46e3b10d03a93d1bf6f5c61d76fec83df4b265e58d249244183ef44`.
Requested TRAIN windows span `2023-10-02T13:30:00Z` through
`2024-08-27T13:31:00Z`; no VALIDATION, TEST, embargo or final-holdout window was
substituted. The last completed checkpoint is
`2026-10-13T17:22:30.411934Z`.

The first three continuation invocations used the original runner. Later
invocations explicitly selected `blackpod.invocation_local_train_capture.v2`,
source SHA256 `f8b497bf789e4ab7f6008098be99928c591f9ad8e21c857b4e87bb5980176b82`.
The original plan/checkpoint formats and bounds remain unchanged: at most 32
requests per invocation, 4,096 lifetime requests, 512 MiB retained capture,
128 pages/200,000 rows/64 MiB per segment, 8 MiB per response, a minimum one-second
request interval and twenty-second timeout. All thirteen invocations stayed
within these declared bounds.

The exact repeated acquisition commands are recorded in the immutable report.
Their common command and explicit adapter variant were:

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python3.11 \
  -m blackpod_build_week.train_market_evidence_cli capture \
  --plan-event-id journal-event-fb6aeddbd6352024d1bc4171f01b0dd619efac60f9952b60a239f4b628ee40ff \
  --journal-root output/train-market-evidence-real-001/journal \
  --capture-root output/train-market-evidence-real-001/capture \
  --credential-source /Users/nikolai/buried_treasure/api_keys.yaml \
  --credential-format GALACTICA_YAML --request-budget 32 --allow-market-data-get

PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python3.11 \
  -m blackpod_build_week.train_market_evidence_cli capture \
  --plan-event-id journal-event-fb6aeddbd6352024d1bc4171f01b0dd619efac60f9952b60a239f4b628ee40ff \
  --journal-root output/train-market-evidence-real-001/journal \
  --capture-root output/train-market-evidence-real-001/capture \
  --credential-source /Users/nikolai/buried_treasure/api_keys.yaml \
  --credential-format GALACTICA_YAML --request-budget 32 --allow-market-data-get \
  --verified-invocation-cache
```

The credential-format name identifies the existing parser/source; no Galactica
trading rules are used. The operation only performs fixed market-data GETs to
`https://data.alpaca.markets/v2/stocks/quotes`. No account, order or execution
endpoint is called; no credential value is recorded in this document.

After acquisition, the original `read_capture` and pure
`validate_capture_snapshot` passed over the entire retained capture. The new
immutable source snapshot is
`output/segmented-evidence-qualification-real-001/input/snapshot-002.v1.json`,
with explicit export clock `2026-10-13T17:26:07.359807Z`. Its subsequent aggregate
source replay determines admitted coverage separately from the raw counts.
All large capture/journal/example artifacts remain in ignored local output;
the committed contracts, tests and documentation provide reproducible software
and a record of the observed counts.

The final native aggregate export passed full source replay and immutable batch
publication. Its retained report is
`output/segmented-evidence-qualification-real-001/reports/export-002.v1.json`,
export ID `train-market-real-001-export-002`, event
`journal-event-731c9b940e53db0274fdf7cc6cabc66f170f4d5012247f0944fa3950dd425016`
at sequence 254. It appended all 228 native segment records after the preserved
25-event prefix. All **228/228 retrieval chains and admitted windows, 456/456
symbol/session pairs** are complete, with zero missing pairs. The full export
retains 390 pages and 282,963,065 source body/receipt bytes.

| Symbol | Raw rows | Admitted rows | Maximum observed spread, bps | Minimum reported native side size |
| --- | ---: | ---: | ---: | ---: |
| QQQ | 1,548,414 | 1,540,429 | 4000.562153046166818917 | 1 |
| SPY | 957,684 | 940,330 | 6918.586083112967718035 | 1 |

Total admitted rows are **2,480,759**. The other **25,339 raw observations remain
retained** and are not silently removed from evidence. Admitted coverage means
each planned pair has qualifying native observations under the original method;
it does not mean every retained row is suitable for that profile.

These are quote-availability and unclipped extrema findings. They are not
modeled transaction costs or executable fills. Both observed spread maxima
exceed the existing 1,000-bps cost-component bound; no bound or measurement was
relaxed. Independent source/economic review is required before any cost/design
qualification claim. The export's independent continuity coverage remains
`UNRESOLVED`, with independent support false. Complete quotes do not change that
status or upgrade native continuity windows.

The successful source publication used this exact offline CLI command:

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests .venv/bin/python3.11 \
  -m blackpod_build_week.train_market_evidence_cli export \
  --snapshot output/segmented-evidence-qualification-real-001/input/snapshot-002.v1.json \
  --evidence-root output/train-market-evidence-real-001/capture \
  --plan-event-id journal-event-fb6aeddbd6352024d1bc4171f01b0dd619efac60f9952b60a239f4b628ee40ff \
  --journal-root output/segmented-evidence-qualification-real-001/journal \
  --export-id train-market-real-001-export-002 \
  --output output/segmented-evidence-qualification-real-001/reports/export-002.v1.json \
  --batched-journal-append
```

The governed real qualification appended at sequence **255**, event
`journal-event-cac9e53491dfd78ea12bb4bcf9259c2656d1c1554a74017ad869b4555f461e1c`.
Its retained input and result are
`output/segmented-evidence-qualification-real-001/input/qualification-001.request.v1.json`
and `reports/qualification-001.result.v1.json` under that same output root.
Recording clock and data cutoff are both `2026-10-13T18:17:46.205344Z`.

Actual outcome: **`DEFER_EVIDENCE_QUALIFICATION`**, with these exact source/design
reasons:

- `EXPLICIT_SIMULATION_RISK_REVIEW_UNQUALIFIED`
- `INDEPENDENT_EFFECTIVE_DATE_COVERAGE_UNVERIFIED`
- `NO_COMPARABLE_CONTINUITY_WINDOWS`
- `NO_JOINT_CONTINUITY_SIZING_CAPACITY_WINDOWS`
- `QUALIFICATION_POLICY_NOT_REVIEWED_FOR_SHADOW`
- `RISK_REVIEW_NOT_APPROVED_FOR_SHADOW`
- `TRAINING_COST_AND_CAPACITY_ASSUMPTIONS_MISSING`
- `UNCERTAINTY_STABILITY_PROTOCOL_MISSING`

Native continuity remains `UNRESOLVED`, the uncertainty protocol is `MISSING`
and there are zero joint eligible windows. The cost model remains `null` despite
complete observed profiles. Missing assumptions are not assigned zero costs.
The original policy/review and earlier deferred records remain unchanged. This
result computes no economic support, uncertainty or realized trade P&L and
grants no execution, capital or policy-changing authority.

The appended envelope's final chain hash is
`35693493736849a0fc00a2b09c8ac59aec5b0ce299fe4f895083d0491ce67e9c`.
The final complete `JournalStore.verify()` passed, with **255 events, 2,122
retained evidence blobs, zero evidence or staging orphans**, and that exact
unchanged chain hash. The offline helper completed with exit 0 and retained its
summary at
`output/segmented-evidence-qualification-real-001/reports/qualification-001.summary.v1.json`.

The retained-record batch retry also passed with exit 0: **235 existing records
retried, zero new events written, all original entry bytes preserved**, and the
same 255-entry chain hash. It reused the original retained v19/v20 records and
fully verified the journal under the writer lock. This was a retained-record
retry, not another CLI export, source reprojection or provider invocation.
Provider calls and orders were both zero; auto-trading remained false. The
immutable retry summary is
`output/segmented-evidence-qualification-real-001/reports/exact-batch-retry.v1.json`.

## Limitations and recommended next burst

Quote collection and source replay establish the narrowly declared availability
and extrema of retained opening-window IEX evidence. They do not establish
consolidated-market liquidity, executable quote depth, opening-auction capacity,
actual fees, realized slippage or historical publication availability. Native
whole quote sizes remain native units; daily-volume participation is explicitly
a separately declared research proxy. Retrospectively captured history does not
prove historical point-in-time availability.

Full semantic replay remains expensive on the real 2.5-million-row corpus.
The capture, batch-publication and field-access adapters preserve complete
source verification. They add no persistent trusted verification cache and do
not skip native replay because a previous result was valid. This checkpoint
supports explicit offline research; live orchestration would require separate
profiling and operational acceptance criteria before adopting these paths.

Reviewed toy declarations demonstrate software behavior; they are not real
provider authentication, authenticated human approval or market-calibrated
economic choices. Optional export coverage is separately recorded and cannot
upgrade inherited native continuity windows. Missing native coverage needs new
native intake and qualification-policy records. Existing deferred events and
their reasoning remain immutable.

No new returns, p-values, uncertainty intervals or hypothesis-support decisions
are computed here. Ready study-design status grants no trading authority. The
original final holdout remains withheld. No inference, order submission, broker
execution, budget activation, capital transfer or live-policy change is part of
this checkpoint; auto-trading remains OFF.

Recommended next burst: **governed native evidence-closure review**. Retain
independently justified effective-date coverage, applicable real cost/capacity
assumptions and explicit reviewed simulation-risk declarations as new linked
source records. Investigate the retained wide-spread observations through
independent source/economic review. Supplying assumptions alone cannot justify
ignoring extrema beyond the existing component bound. Reassess the unchanged
hypothesis/data/design through the existing consumer. Completion requires each
gate to clear from validated source evidence, or an explicit retained deferral;
it cannot rely on stronger narrative
labels, edit old gates or tune the design to observed returns. The separately
frozen uncertainty/stability study should run only after these prerequisites
clear, under a new shadow evaluation record. This next burst is recommended and
has not been implemented.
