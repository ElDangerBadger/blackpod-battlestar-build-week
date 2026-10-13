# Trading Desk real-evidence qualification validation

Checkpoint date: 2026-10-13 America/Los_Angeles. Starting commit:
`3f4a91228bb2969177a04da0dc2986751160a81b`. Work was isolated on
`codex/trading-real-evidence-qualification`; merge and push are authorized after
successful validation. The final response records the published commit ID.

The [qualification design](TRADING_EVIDENCE_QUALIFICATION.md) documents the
inspected implementation, strict contracts, scope, masking rules, calibration,
governance, append-only linkage and runnable examples.

## Exact changes

Existing files receive only additive discovery/replay integration:

- `README.md`: documentation link.
- `src/blackpod_build_week/contracts/decision_journal.py`: journal v18 dispatch.
- `src/blackpod_build_week/decision_journal_store.py`: replay dispatch for the two v18 kinds.

New files:

- `src/blackpod_build_week/contracts/trading_evidence_qualification.py`
- `src/blackpod_build_week/trading_evidence_qualification.py`
- `src/blackpod_build_week/trading_continuity_qualification.py`
- `src/blackpod_build_week/trading_training_calibration.py`
- `src/blackpod_build_week/trading_evidence_qualification_journal.py`
- `src/blackpod_build_week/trading_evidence_qualification_cli.py`
- `src/blackpod_build_week/trading_evidence_qualification_example.py`
- `tests/test_trading_continuity_qualification.py`
- `tests/test_trading_training_calibration.py`
- `tests/test_trading_evidence_qualification.py`
- `tests/test_trading_evidence_qualification_cli.py`
- `tests/test_trading_evidence_qualification_example.py`
- `docs/TRADING_EVIDENCE_QUALIFICATION.md`
- `docs/TRADING_EVIDENCE_QUALIFICATION_VALIDATION.md`

A SHA-256 baseline of 739 previously tracked files confirms that only the three
listed existing files change. Frozen hypotheses, source prices, mission
schemas, v15–v17 pinned implementations, ModelDock configuration/routing,
Navigator/execution behavior and capital policy remain unchanged. No dependencies,
Galactica trading rules, live hooks, providers or new agents are introduced.

## New deterministic offline tests

All **112 new tests pass**:

| Suite | Tests | Final result |
| --- | ---: | --- |
| Continuity windows | 34 | PASS, 0.605s |
| TRAIN cost/capacity calibration | 28 | PASS, 0.673s |
| Contracts, integration and journal | 17 | PASS, 137.094s |
| Offline CLI and safe paths | 10 | PASS, 48.578s |
| Controlled examples | 23 | PASS, 112.640s |

Exact commands:

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests .venv/bin/python3.11 -m unittest test_trading_continuity_qualification -q
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests .venv/bin/python3.11 -m unittest test_trading_training_calibration -q
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests .venv/bin/python3.11 -m unittest test_trading_evidence_qualification -q
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests .venv/bin/python3.11 -m unittest test_trading_evidence_qualification_cli -q
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests .venv/bin/python3.11 -m unittest test_trading_evidence_qualification_example -q
```

Coverage includes feature/entry/holding/exit and whole-universe control
boundaries, unknown effective dates, actual returned-calendar mapping,
before/after-dataset action retention, chronology, Decimal-context independence,
resource bounds, exact native receipts/pagination, TRAIN coverage, out-of-scope
quotes, no clipping, stressed parameter bounds, distinct declared costs,
daily-volume proxy semantics, disabled authority, immutable source/history,
hash/pin rejection, retries after later records, supersession, safe outputs,
corrupted sources and interrupted-publication recovery.

Review identified and corrected two readiness gaps before final validation:
sample feasibility must use distinct jointly qualified source dates rather than
raw TEST length, and continuity/sizing/capacity must intersect on the same
opportunities. Regression tests reproduce sparse samples and disjoint masks.
No policy minimum or hypothesis was lowered to obtain readiness.

## Regression selection

The 13 exact offline module lists in
[RESEARCH_ACCEPTANCE_VALIDATION.md](RESEARCH_ACCEPTANCE_VALIDATION.md#existing-regression-results)
were rerun unchanged, covering 2,525 existing tests. The previous acceptance
checkpoint's 123 tests were also rerun with this exact command:

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests .venv/bin/python3.11 -m unittest test_research_assessment_contracts test_research_acceptance_trading test_research_acceptance_investment test_research_acceptance_journal test_research_acceptance_cli test_research_acceptance_examples -q
```

All **2,648 selected existing regressions pass**, including 269 v16 evidence
tests and 123 v17 acceptance tests. Total checkpoint coverage is **2,760 tests**.
No unrestricted live/integration discovery was performed. Passing software
tests does not demonstrate trading profitability, sufficient economic support,
calibrated opening liquidity or a statistically valid interval method.

## Persisted authored example

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests .venv/bin/python3.11 -m blackpod_build_week.trading_evidence_qualification_example --output-root output/trading-real-evidence-qualification-example-001
```

The example preserves all 14 original native v16 events and appends four frozen
policies and four qualifications. It verifies **22 events, 76 retained blobs,
zero evidence or staging orphans**, with final chain hash
`3a80135944abd7853b0129e575831bb5d639e806ca520ac0abbab63b3ab1f3b8`.

| Case | Result | Evidence |
| --- | --- | --- |
| Original reversal, declared reviewed toy design | `READY_FOR_QUALIFIED_STUDY_DESIGN` | Eight joint dates meet its unchanged minimum of eight. |
| Original continuation, same declared minimum | `DEFER_EVIDENCE_QUALIFICATION` | Six joint dates fail the minimum; protocol/sample feasibility remains unresolved. |
| Inactive proposed policy | `DEFER_EVIDENCE_QUALIFICATION` | Missing review/assumptions/protocol remain visible. |
| Whole-dataset quote sample containing holdout observations | `DEFER_EVIDENCE_QUALIFICATION` | Contaminated chains produce no spread measurements or cost model. |

TRAIN-only fixture bodies are openly authored subsets of the old synthetic
quote body: 12 sessions, 24 symbol quotes. They are not actual new provider
captures. Old prices, hypotheses, costs and reports remain intact. Both
hypotheses are retained; this procedure does not rank or select a winner.

Standalone CLI `verify`, `assess` and identical `record` succeeded. The retry
returned `written:false`, sequence 16, preserving the same journal chain.
Result flags remain `uncertainty_computed=false`,
`economic_hypothesis_supported=false`, `existing_gate_override=false`,
`auto_trading_enabled=false`, `execution_status=NOT_EXECUTED`, with null
realized trade P&L and every authority flag false.

## Real evidence and methodological limits

The existing real journal contains 760 QQQ/SPY sessions and preserves both
original hypotheses' native deferrals and v17 assessments. Its only quote
sample is session 759 inside final holdout, outside TRAIN 0–227. The new
calibrator rejects those observations as input rather than relabeling them.
VALIDATION 231–379 and TEST 383–607 retain the original embargoes and indices.

New proposed qualification records use a separate ignored output journal;
source evidence and the original journal are retained unchanged. Real coverage
is unverified, no reviewed fee/slippage or capacity assumptions exist, risk is
still proposed, and the uncertainty protocol is unspecified. Neither real
hypothesis can qualify by assertion or by using the holdout quote sample.

The completed real replay preserves all **16 original events** byte-for-byte
and their original verified chain summary. Two proposed policies and two
qualification assessments append in
`output/trading-real-evidence-qualification-real-001/journal`, which verifies
**20 events, 74 retained blobs, zero evidence or staging orphans**. Final chain:
`0e0cee016d494017a9dee53f0c4dee2511c2a8ed41e3e4dd020df4b277174cef`.
Both hypotheses return `DEFER_EVIDENCE_QUALIFICATION`. Each retains 450
pre-signal opportunities, zero jointly qualified windows, 456 missing TRAIN
symbol/session quote pairs, and null quote measurements/cost models. Native
continuity remains `UNRESOLVED`, and the uncertainty protocol remains `MISSING`.
No quote is transferred from holdout to TRAIN.

Actual additional checks:

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests .venv/bin/python3.11 /private/tmp/blackpod_real_qualification_check.py
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests .venv/bin/python3.11 -m blackpod_build_week.auto_trading_cli status --runtime-root output/auto-trading-runtime
git diff --check
```

The temporary real-history helper copies only verified source events and bytes
to the separate journal, freezes proposed policies against their original plan
and native evidence IDs, appends qualifications, and asserts source preservation
and absence of measurements from contaminated quotes. Network connections and
worker creation are patched to raise. It is an operator validation helper,
not a new provider or committed dependency. Its report is
`output/trading-real-evidence-qualification-real-001/reports/real-qualification-summary.json`.
Local evidence exports remain ignored and are not publication payloads.

Runtime status returns `state=OFF`, `entries_enabled=false`,
`worker_active=false`, `auto_restart_enabled=false`, and
`capital_transfers_permitted=false`. The documented runtime remains absent;
this is the uninitialized OFF state. No runtime was created or started.

The real-history replay audit uses caller-supplied check clocks of
2026-10-13T08:00:00Z and 08:01:00Z after the original source captures. These
are audit declarations, not authenticated production decision timestamps or
claims that the newly generated design existed historically. Source capture
timestamps remain unchanged. Future operational records need trusted
recording-time provenance in addition to the existing source/hash checks.

Raw daily-volume minima and declared participation produce only research
proxies. Corporate-action adjustment of volume units, actual opening depth,
slippage, fills, fees, price impact and execution capacity are not established.
Coverage/reviewer labels and capture receipts do not authenticate providers,
reviewers, release-time availability or historical preregistration. Source
integrity validation reads already retained bodies, but computes no holdout
calibration bound or strategy score.

The uncertainty/stability method is frozen as a future design, with declared
paired session blocks, seed, replication count, nominal confidence level,
sample/fold requirements and cash/control comparisons at 1×/2×/4× costs. It
does not compute intervals or establish that those design choices are
statistically adequate. Full-chain replay deliberately verifies native evidence
again; large historical journals remain expensive offline operations.

## Next bounded milestone

Recommended next burst: **governed TRAIN-window market-evidence capture/export**.
Retain explicitly scoped historical TRAIN quote chains and independent
effective-date coverage support under the current frozen identities; keep
cost/slippage/capacity assumptions separate and source justified. Gate completion
on receipt/query identity, complete pagination, required TRAIN symbol/session
coverage, no held-out data leakage, no silent sampling/downscaling, and explicit
shadow risk review. If evidence is unavailable, preserve the deferral.

This next burst is not implemented here. A qualified shadow simulator and
statistical evaluator must subsequently consume the frozen mask/protocol through
new versioned records; existing v16 gates are never silently bypassed.
Auto-trading remains OFF, budgets inactive and execution authority unchanged.
