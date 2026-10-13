# TRAIN-window market-evidence capture/export validation

Checkpoint date: 2026-10-13 America/Los_Angeles. Starting commit:
`1de866b1f0f9cbb1e1e93014e198ad1a4b3220d2`. Dedicated branch:
`codex/train-market-evidence-export`. The operator authorized implementation,
bounded market-data capture, and main merge/push after validation. Publication
is reported with its exact commit ID in the final response.

The [capture/export guide](TRAIN_MARKET_EVIDENCE.md) documents the inspected
interfaces, contracts, native query/pagination rules, interrupted-processing
recovery, resource limits, source proofs, journal integration and CLI workflow.
This checkpoint supplies acquisition/export infrastructure, not trading
effectiveness or execution authority.

## Exact files changed

Three existing files change additively:

- `README.md`: documentation link.
- `src/blackpod_build_week/contracts/decision_journal.py`: v19 dispatch.
- `src/blackpod_build_week/decision_journal_store.py`: v19 replay dispatch.

New files:

- `src/blackpod_build_week/contracts/train_market_evidence.py`
- `src/blackpod_build_week/train_market_evidence.py`
- `src/blackpod_build_week/train_market_capture.py`
- `src/blackpod_build_week/train_market_export.py`
- `src/blackpod_build_week/train_market_evidence_journal.py`
- `src/blackpod_build_week/train_market_evidence_cli.py`
- `src/blackpod_build_week/train_market_evidence_example.py`
- `tests/test_train_market_capture.py`
- `tests/test_train_market_export.py`
- `tests/test_train_market_evidence.py`
- `tests/test_train_market_evidence_cli.py`
- `tests/test_train_market_evidence_example.py`
- `docs/TRAIN_MARKET_EVIDENCE.md`
- `docs/TRAIN_MARKET_EVIDENCE_VALIDATION.md`

A SHA-256 baseline covers 753 previously tracked files. Only the three listed
existing files change. Original prices, hypotheses, mission schemas, v15–v18
source pins, ModelDock configuration/routing, Navigator behavior, execution
rules and capital policy remain byte-identical. No new dependencies, trading
agents, inference, migrations or Galactica trading rules are introduced.

## Actual offline test results

All **134 new tests passed**, plus **2,760 selected previous regressions**:
**2,894 tests total**. Repeat runs are not counted twice.

| New suite | Tests | Final result |
| --- | ---: | --- |
| Transport, capture, recovery and pure checkpoint audit | 44 | PASS |
| Pure segmented projection and aggregation | 41 | PASS |
| Contracts, planning and append-only journal | 16 | PASS, 78.818s |
| CLI, scope, source protection and audit forgery rejection | 10 | PASS, 77.846s |
| Controlled full/partial/terminal-empty examples | 23 | PASS, 382.764s |

Exact commands:

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests .venv/bin/python3.11 -m unittest test_train_market_capture test_train_market_export -q
# 85 tests, OK, 8.128s
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests .venv/bin/python3.11 -m unittest test_train_market_evidence -q
# 16 tests, OK, 78.818s
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests .venv/bin/python3.11 -m unittest test_train_market_evidence_cli -q
# 10 tests, OK, 77.846s
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests .venv/bin/python3.11 -m unittest test_train_market_evidence_example -q
# 23 tests, OK, 382.764s
git diff --check
```

Tests include exact TRAIN/calendar/query membership, no sampling, native
symbol/time ordering and ties, pagination/token cycles, empty/unavailable
responses, source-byte/hash consistency, capture/failure distinction, strict
booleans/versions/bounds, credential echoes and error-body suppression,
verified TLS, redirect/proxy refusal, request/time/byte bounds, no synthetic
network default, capture clock regressions before GET, immutable conflicts,
symlinks/hardlinks, interrupted attempts/source-pair publication, pure audit of
checkpoint sequences/counts/statuses, protected outputs, source removal,
idempotency after later records, incomplete coverage and aggregate disclosure.

Review corrected several issues before final validation: resource-limited
unstarted windows retain their budget reason without becoming invented
provider attempts; supplied snapshots now replay checkpoint semantics rather
than merely retaining hashes; every refreshed clock is checked before a GET;
native continuity links require matching dataset/universe/scope and chronological
availability; new method evidence pins consumed old helper files without
editing them. Development assertions were corrected for the actual native
pagination reason and for source-proof references in addition to attempt logs.

The thirteen exact selected module lists in
[RESEARCH_ACCEPTANCE_VALIDATION.md](RESEARCH_ACCEPTANCE_VALIDATION.md#existing-regression-results)
were rerun unchanged: all 2,525 passed. These additional exact commands also
passed:

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests .venv/bin/python3.11 -m unittest test_research_assessment_contracts test_research_acceptance_trading test_research_acceptance_investment test_research_acceptance_journal test_research_acceptance_cli test_research_acceptance_examples -q
# 123 tests, OK, 518.951s
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests .venv/bin/python3.11 -m unittest test_trading_continuity_qualification test_trading_training_calibration test_trading_evidence_qualification test_trading_evidence_qualification_cli test_trading_evidence_qualification_example -q
# 112 tests, OK, 285.183s
```

No unrestricted live/integration discovery was performed. Software test counts
do not establish economically meaningful returns or a profitable strategy.

## Authored fixture coverage

The runnable example uses existing frozen 40-session data and its original
quotes. An injected callback returns only rows from each declared TRAIN window;
literal fixture credentials are not real keys and no credential file or
provider is accessed. Every case preserves all fourteen original source events.

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests .venv/bin/python3.11 -m blackpod_build_week.train_market_evidence_example --output-root output/train-market-evidence-example-001
```

| Case | Events / blobs | Actual result |
| --- | ---: | --- |
| Full | 28 / 143 | Capture complete; 24/24 TRAIN symbol/session pairs covered. |
| Partial | 18 / 83 | Capture incomplete; 4/24 covered, 20 missing. |
| Terminal empty | 28 / 143 | Capture complete; coverage incomplete, 22/24 covered. |

All three verify with zero evidence/staging orphans, including retained source
proofs and attempt checkpoints. Full final chain:
`58c098218747b52ee332f6cc1bc3a8cc224b6684546a125e99112e160f69780a`.
Standalone CLI verification and identical export retry succeeded; retry wrote
zero segment or aggregate events. No scenario supplies independent action
coverage, fees, slippage, execution capacity, economic support or v18 compatibility.

## Bounded actual Alpaca capture

The real capture plan preserves the original six-event governed-history journal
and its 760-session QQQ/SPY dataset. It freezes all **228 original TRAIN windows**
from 2023-10-02 through 2024-08-27, and all **456 required symbol/session pairs**.
Each query uses the original returned open through open plus 60 seconds,
IEX/USD, sorted symbols/time, `asof=-`, and a full 10,000-row native page limit.
No VALIDATION, TEST or final-holdout quote is requested.

The bounded real probe performed **four successful market-data GETs** using the
existing literal credential source in memory. No keys, headers or provider
error bodies were printed, retained or committed. Redirects and proxies were
disabled. It fully paginated the first two original TRAIN sessions and stopped
at the explicit four-request invocation budget. This is intentionally a partial
real capture, not a claim that the whole TRAIN corpus was acquired.

Actual result:

- Four raw pages and exact capture receipts; **30,044 native quote updates**, all
  eligible under the existing regular opening-minute admission definition.
- **2/228 sessions**, **4/456 pairs** covered; **226 sessions and 452 pairs remain
  uncaptured**. The fold's usable aggregate spread profile remains null.
- Raw-body/receipt bytes: **3,404,169**; the complete verified capture source and
  recovery proof retained **4,254,284** bytes.
- Capture and coverage completion both false; independent effective-date
  coverage `UNRESOLVED`; fees/slippage/capacity assumptions absent.
- Consumer status `INCOMPATIBLE_SEGMENTED_INPUT`; no v18 gate override, no
  uncertainty/statistical computation or economic hypothesis support.

Plan event:
`journal-event-fb6aeddbd6352024d1bc4171f01b0dd619efac60f9952b60a239f4b628ee40ff`.
Aggregate event:
`journal-event-ba2509c396bca0653bdf9c07d84b3d41474275906ff6aceecbdc6ececcdadb2b`.
Local source/export root: `output/train-market-evidence-real-001`.
Its original source journal and all original hypothesis/price bytes are preserved.
Local raw captures are ignored; the credential source is outside the checkout.
Neither is a Git publication payload.
The real journal verifies **10 events, 56 retained blobs and zero orphans**;
final chain hash
`2d9cd1fd60065874bb545faa82abdde908c8c271b84d26282438951763bf1ecb`.
The identical actual export retry writes zero segment or aggregate events.

Exact operator commands:

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests .venv/bin/python3.11 /private/tmp/blackpod_prepare_train_real.py
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests .venv/bin/python3.11 -m blackpod_build_week.train_market_evidence_cli capture --plan-event-id journal-event-fb6aeddbd6352024d1bc4171f01b0dd619efac60f9952b60a239f4b628ee40ff --journal-root output/train-market-evidence-real-001/journal --capture-root output/train-market-evidence-real-001/capture --credential-source /Users/nikolai/buried_treasure/api_keys.yaml --credential-format GALACTICA_YAML --request-budget 4 --allow-market-data-get
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests .venv/bin/python3.11 /private/tmp/blackpod_snapshot_train_real.py
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests .venv/bin/python3.11 -m blackpod_build_week.train_market_evidence_cli export --snapshot output/train-market-evidence-real-001/input/snapshot-001.v1.json --evidence-root output/train-market-evidence-real-001/capture --plan-event-id journal-event-fb6aeddbd6352024d1bc4171f01b0dd619efac60f9952b60a239f4b628ee40ff --journal-root output/train-market-evidence-real-001/journal --export-id train-market-real-001-export-001 --output output/train-market-evidence-real-001/reports/export-001.v1.json
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests .venv/bin/python3.11 -m blackpod_build_week.train_market_evidence_cli verify --journal-root output/train-market-evidence-real-001/journal
```

The temporary preparation/snapshot helpers perform offline source preservation,
plan freezing and snapshot validation. They are not new committed dependencies
or additional provider paths. Explicit CLI interfaces in the guide reproduce
the same steps. Future capture continuation reuses this exact immutable plan
and source job, with a new snapshot/export ID; old exports remain unchanged.

## Remaining limits and next engineering milestone

The capture/export implementation is complete; the real TRAIN corpus is not.
Continuation requires explicit bounded capture invocations under the existing
plan. Partial pages remain incomplete, native extremes remain unclipped, and
missing sessions cannot be supplied by recent or held-out data.

The old v18 consumer requires one fixed-query chain per fold and tighter whole
input bounds. Independent per-session query chains cannot be concatenated or
relabelled to satisfy it. New aggregate events link raw segment events without
duplicating the whole corpus. Existing storage still loads retained blobs during
verified scans; large-corpus replay is expensive. Original per-file limits stay
64 MiB. The new per-segment event's combined source-proof closure permits up to
128 MiB so a 64 MiB raw segment can coexist with its original source proof;
individual files and old consumers retain their existing limits.

Independent effective-date review remains a separately supplied, exact-source
packet. Process-date responses, empty responses, quote completeness, a dividend
schedule alone and an unauthenticated reviewer label cannot establish complete
all-action-type evidence. Receipts are local records, not provider signatures or
historical point-in-time attestations. Opening depth, fills, market impact and
realized costs remain unestablished.

Recommended next engineering burst: **a versioned segmented-evidence qualification
consumer** that binds these exports to frozen continuity, sizing and statistical
protocols without changing v18 replay. Gate it on completed or explicitly deferred
TRAIN coverage, independent action support, source-justified cost/capacity
assumptions and an explicit shadow risk review. Continue acquisition through the
existing bounded capture interface before claiming real-data readiness. This
consumer is not implemented here.

Auto-trading remains OFF in the uninitialized documented runtime: no active
worker, entries, auto-restart or capital transfers. No broker/account/order
endpoint was contacted, no orders were submitted, and no budget, policy,
execution authority or ModelDock configuration was changed.
