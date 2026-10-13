# Burst 6 implementation and validation — October 12, 2026

Implemented deterministic long-only FIFO fill-lot and fee accounting, retained
source imports, additive journal v7 observations, offline CLI commands, recovery
and semantic replay tests, and runnable synthetic examples. Recorded the user's
separate inactive PAPER testing budget: 25% of captured equity, split equally
between TRADING and INVESTMENT. Auto-trading remains OFF.

## Files changed in this burst

Production interfaces extended only for passive journal verification:

- `src/blackpod_build_week/contracts/decision_journal.py` — additive v7 event
  contract; older versions retain their semantics.
- `src/blackpod_build_week/decision_journal_store.py` — retained-source
  accounting replay on append and read.

New offline implementation:

- `src/blackpod_build_week/contracts/trading_accounting.py`
- `src/blackpod_build_week/contracts/paper_test_budget.py`
- `src/blackpod_build_week/paper_activity_import.py`
- `src/blackpod_build_week/trading_accounting.py`
- `src/blackpod_build_week/paper_test_budget.py`
- `src/blackpod_build_week/trading_accounting_cli.py`

New tests:

- `tests/test_trading_accounting_contracts.py`
- `tests/test_paper_activity_import.py`
- `tests/test_trading_accounting_engine.py`
- `tests/test_trading_accounting_store.py`
- `tests/test_trading_accounting_cli.py`
- `tests/test_trading_accounting_examples.py`

Examples and source fixtures:

- `examples/trading_accounting/seed_journal.py`
- `examples/paper_activities.pending-fees.fixture.v1.json`
- `examples/paper_activities.complete-fees.fixture.v1.json`
- `examples/trading_accounting.pending-fees.paper.v1.json`
- `examples/trading_accounting.complete-fees.paper.v1.json`
- `fixtures/trading_accounting/prelude.fixture.json`
- `fixtures/trading_accounting/activity-export.pending-fees.fixture.json`
- `fixtures/trading_accounting/activity-export.complete-fees.fixture.json`
- `fixtures/trading_accounting/expected-accounting.pending-fees.json`
- `fixtures/trading_accounting/expected-accounting.complete-fees.json`

Documentation: new `docs/TRADING_ACCOUNTING.md` and this validation report;
updated `README.md`, `docs/ARCHITECTURE.md` and `docs/SAFETY_BOUNDARY.md`.

The existing ModelDock changes were preserved. No canonical mission contract,
stage workflow, Navigator behavior, Galactica adapter, execution controller,
worker, installed book, configuration, dependency or database schema changed.
Private broker evidence and inactive budget artifacts are in ignored `output`
directories. No commit or PR was created.

## Actual offline results

**959 unique selected tests passed**: 164 tests for this burst and 795 existing
regressions. Repeated development runs are not counted again.

| Test group | Tests | Result | Final duration |
| --- | ---: | --- | ---: |
| New accounting/import/storage/CLI/examples | 164 | PASS | 14.512 s |
| Existing journal/hypotheses/review | 249 | PASS | 11.645 s |
| Existing investment governance/approval | 125 | PASS | 63.325 s |
| Existing paper reconciliation/runtime/adapter/probe | 249 | PASS | 18.737 s |
| Existing missions/Navigator/operator/ModelDock | 172 | PASS | 1.057 s |

New test counts: 41 contracts, 36 source imports, 46 engine, 23 store, 17 CLI
and budget, and one committed-example test. The new tests forbid sockets,
process launches and activation where applicable. Broker and native integration
regressions use mocks and synthetic pinned profiles. These tests did not submit
orders, load native inference, call providers or start a live stream.

Exact final test commands, run from this checkout:

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests .venv/bin/python3.11 -m unittest \
  test_trading_accounting_contracts test_paper_activity_import \
  test_trading_accounting_engine test_trading_accounting_store \
  test_trading_accounting_cli test_trading_accounting_examples -q

PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests .venv/bin/python3.11 -m unittest \
  test_decision_journal_contracts test_decision_journal_projection \
  test_decision_journal_store test_decision_journal_cli \
  test_investment_hypothesis_contracts test_investment_hypothesis_sources \
  test_investment_hypothesis_store test_investment_hypothesis_examples \
  test_investment_hypothesis_cli test_investment_review_contracts \
  test_investment_review_engine test_investment_review_store \
  test_investment_review_cli -q

PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests .venv/bin/python3.11 -m unittest \
  test_investment_governance_contracts test_investment_governance_engine \
  test_investment_approval test_investment_governance_store \
  test_investment_governance_examples test_investment_governance_cli -q

PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests .venv/bin/python3.11 -m unittest \
  test_trading_reconciliation_contracts test_trading_reconciliation_engine \
  test_trading_reconciliation_store test_trading_receipts \
  test_trading_reconciliation_cli test_paper_account_safety \
  test_paper_order_capture test_trading_reconciliation_examples \
  test_auto_trading_runtime test_galactica_trading_adapter \
  test_trading_automation test_paper_account_probe -q

PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests .venv/bin/python3.11 -m unittest \
  test_contracts test_mission_store test_mission_transitions \
  test_mission_presentation test_cli_help test_navigator_adapter \
  test_operator_adapter test_modeldock_config test_modeldock_client \
  test_modeldock_preflight test_modeldock_delivery -q

git diff --check
```

The final diff check passed. A SHA-256 manifest captured before this burst
verified **26 protected files unchanged**, including ModelDock changes, existing
execution modules and original real paper journal entries/evidence.

## Accounting and recovery coverage

Tests establish individual activity identity, exact retained source projection,
immutable prior rows and raw metadata, duplicate rejection/deduplication,
account/mode/currency isolation, flat baseline and ownership timing, exact
attempt/order attribution, historical receipt positions, FIFO partial closes,
cumulative quantity and average-price checks, remaining positions, missing and
unallocated fees, credits, precision and fee conservation, and hostile ambient
Decimal contexts. Unsupported shorts, legs, replacements, financial activities,
precision and ambiguous sequences defer or reject explicitly.

Storage tests include mixed v1–v7 chains, conflict detection, concurrent retries,
missing or altered blobs, rehashed economic/report tampering, restoration without
original source files, pre/post-publication and fsync interruption, orphan
staging/evidence, safe internal hard-link recovery, and rejection of unsafe
external links. Original decision and evidence bytes are never rewritten.

During development, independent review found and corrected fee sign/rounding,
price consistency, historical receipt position, raw identity and Decimal-context
issues. Initial failing tests were resolved; the final suite above is green.

## Real evidence versus fixtures

Real account coverage in this burst consists of **four authenticated GETs** to
the fixed paper host: account, positions, bounded open orders and clock. All
returned HTTP 200 and matched the previously confirmed account. There were no
tracked order requests, submit/cancel/close calls, inference runs or transfers.
Credentials were read in memory from the already confirmed Galactica YAML
source. No keys were printed, changed, copied or rotated.

The capture ended `2026-10-12T19:36:38.126342Z` (12:36 p.m. Pacific), with:

- equity/cash: **$81,525.11**;
- current positions/open orders: **0 / 0**;
- test cap: **$20,381.27**;
- TRADING: **$10,190.63**;
- INVESTMENT: **$10,190.63**;
- unassigned within the test cap: **$0.01**;
- outside the test: **$61,143.84**.

Cent rounding never exceeds 25% of equity and conserves the full balance. These
are fixed budgets at this capture, not ongoing percentage rebalancing. Buying
power was not used. The user's reported roughly 20% historical drawdown and
outperformance hypothesis were not independently evaluated from trade history.

Actual artifacts:

| Artifact | Location or hash |
| --- | --- |
| Broker capture | `output/auto-trading-paper-budget-source/paper-probe-4d3350c46a525e2fec013d2f858e3c7dd7118c1b451c75adc22c437366d22f91.json` |
| Source journal | `output/auto-trading-test-budget-journal` |
| Source snapshot event | `journal-event-386cb20ca17769f5829f753b162d57fec07d877c97ad4d740d81b66cb05d1efc` |
| Source journal result | 1 event, 2 blobs, zero orphans |
| Source journal last hash | `0c83a15fd446e7493fc716e1e4c6c08b00f771eaa4eb7f849f600f1c1bd61c3f` |
| Budget artifact | `output/auto-trading-paper-test-budget/paper-test-budget-08375f1f5d6f2fa04b43912104dca1bc874f9178815b5b61f6b01c5f7c40fa56.json` |
| Budget hash | `eeb60f7a03fd81ee40fe8b733c7983b8a3616baa655d9edabbf3dfceee1a8652` |
| Exact saved local budget command arguments | `output/auto-trading-paper-test-budget-inputs/command.json` |

The budget is `DECLARED_INACTIVE` / `NOT_INSTALLED`, with all authority and
activation flags false. Its source snapshot is journaled; the budget itself is
an immutable linked artifact, not a new journal event. Ownership, entry size,
total entry-test notional and expiry remain unset. No runtime budget was
installed. The existing initial 50/50 capital proposal remains unchanged.

The network capture was run through this exact script; the expected account
identity comes from retained local evidence rather than a pasted credential:

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python3.11 - <<'PY'
import json
from pathlib import Path
from blackpod_build_week.paper_order_capture import capture_paper_orders
from blackpod_build_week.trading_reconciliation import snapshot_input_from_probe
from blackpod_build_week.hashing import sha256_bytes
baseline=Path('output/auto-trading-paper-check/paper-probe-8b9ee7b4c9b5f4211a389143dabc719248a3ed0157e18545b0be0ec14fd7250f.json')
previous=snapshot_input_from_probe(baseline.read_bytes(),snapshot_id='budget-source-identity',evidence_path='broker/identity.json')
result=capture_paper_orders(Path('/Users/nikolai/buried_treasure/api_keys.yaml'),'GALACTICA_YAML',Path('output/auto-trading-paper-budget-source'),(),expected_account_id=previous.account_id)
if result['result']!='CONFIRMED':
 print(json.dumps({'result':result['result'],'orders_submitted':0}))
 raise SystemExit(2)
p=Path(result['evidence_path'])
raw=p.read_bytes()
snapshot=snapshot_input_from_probe(raw,snapshot_id='paper-test-budget-baseline-'+sha256_bytes(raw),evidence_path='broker_captures/'+sha256_bytes(raw)+'.json')
print(json.dumps({'result':'CONFIRMED','evidence_path':str(p),'source_sha256':sha256_bytes(raw),'captured_at':snapshot.captured_at,'equity':snapshot.account['equity'],'cash':snapshot.account['cash'],'position_count':len(snapshot.positions),'open_order_count':len(snapshot.orders),'orders_submitted':0,'account_identity_matched':True}))
PY
```

The completed capture was imported with:

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python3.11 \
  -m blackpod_build_week.trading_reconciliation_cli import-probe \
  --journal-root output/auto-trading-test-budget-journal \
  --snapshot-id paper-test-budget-baseline-4d3350c46a525e2fec013d2f858e3c7dd7118c1b451c75adc22c437366d22f91 \
  --probe output/auto-trading-paper-budget-source/paper-probe-4d3350c46a525e2fec013d2f858e3c7dd7118c1b451c75adc22c437366d22f91.json
```

The budget creation and exact retry used `trading_accounting_cli.main` with the
saved arguments. The retained declaration timestamp is
`2026-10-12T19:43:29.487388Z`; account ID is kept in private artifacts. Validation:

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python3.11 - <<'PY'
import json
from pathlib import Path
from blackpod_build_week.trading_accounting_cli import main
args=json.loads(Path('output/auto-trading-paper-test-budget-inputs/command.json').read_text())
raise SystemExit(main(args))
PY
```

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python3.11 \
  -m blackpod_build_week.trading_accounting_cli validate-paper-test-budget \
  --journal-root output/auto-trading-test-budget-journal \
  --budget output/auto-trading-paper-test-budget/paper-test-budget-08375f1f5d6f2fa04b43912104dca1bc874f9178815b5b61f6b01c5f7c40fa56.json
```

It returned valid with the same hash on retry. No real individual fills, fees,
fee completeness, ownership or realized P&L were manufactured for the empty
account. An empty current book does not establish an empty historical trade
record.

All executed-fill, lot, fee and profit results are **synthetic fixture coverage**.
The documented example commands in [TRADING_ACCOUNTING.md](TRADING_ACCOUNTING.md)
were run and verified: 6 events, 13 blobs, zero orphans, last hash
`560a8fff377d85a9ff7ba39049b9d53a545fa38c5dec809c7c8583246cb96d24`.
Both accounting inputs were retried from retained evidence after the later
event: `written=false`, sequences 5/6, hash unchanged. The example's $15.92 net
profit is a calculation test and not an actual trading return.

## Existing history and runtime checks

All five previously retained journal histories verified with their previous
hashes unchanged:

| Root under `output/` | Events / blobs |
| --- | ---: |
| `decision-journal-archive-check` | 20 / 122 |
| `investment-hypothesis-history-check` | 22 / 124 |
| `investment-review-history-check` | 26 / 128 |
| `investment-governance-example` | 9 / 18 |
| `auto-trading-reconciliation-real` | 4 / 6 |

Verification command for each root:

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python3.11 \
  -m blackpod_build_week.harbormaster journal verify --journal-root output/ROOT_FROM_TABLE

PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python3.11 \
  -m blackpod_build_week.auto_trading_cli status --runtime-root output/auto-trading-runtime
```

Status: `OFF`, `worker_active=false`, `entries_enabled=false`,
`auto_restart_enabled=false`, `capital_transfers_permitted=false`. No real book
or profile was installed. No paper entry/exit trial was started.

## Remaining limits and recommended next burst

This burst supports long-only USD FIFO with one retained flat baseline and
ownership declaration per accounting chain. It does not implement shorts,
options, corporate actions, tax accounting, accounting-period roll-forward,
automatic fee attribution, or an activity API collector. Account-level fees
without exact source links remain unallocated. Net profit stays unknown until
bounded fee evidence is complete and attributable.

Raw activity timestamps above microsecond precision reject. Equal-time
economically different fills, rounded broker average-price discrepancies,
legacy missing receipt positions, replacements and leg attribution remain
conservative gaps. Imported provider identity, declared completeness and local
reviewer identity are not signed attestations. Account locks remain scoped to
this checkout/user/host; external executors are not coordinated. Full accounting
replay is bounded to 20,000 activities.

**Recommend one next burst: Shadow Two-Desk Candidate Review and Bounded PAPER
Test Plan.** Verify the connected Oracle, Senate, Brigade, technical and
quantitative evidence paths; extend their existing interfaces to recommend
candidate suitability by horizon with explicit evidence, uncertainty and
invalidation. Produce a proposed desk scope and small entry/exit plan within
the recorded budgets, including order size, total test notional, expiry, exits,
benchmark/evaluation horizon and recovery criteria. Keep auto-trading OFF.

Before execution, demonstrate actual activity/fee format support, full
owned-symbol activity coverage and exclusive execution; resolve precision and
fee attribution gaps; and bind explicit approval to the concrete test plan.
Recommendations alone cannot assign execution authority or change investment
policies. No candidate selection, plan activation or next burst was implemented.
