# Burst 5 validation — 2026-10-12

The intended YAML paper-account pair works. The earlier two environment-file
pairs are different; their HTTP 401 responses did not establish that the user's
original YAML key was bad. Corrected selection is explicit `GALACTICA_YAML`.
Authenticated paper account, positions, open-orders and clock reads all returned
HTTP 200. No key was rotated, copied to another file or logged.

After confirmation, the already approved reconciliation burst was implemented.
Auto-trading remains OFF, no worker was started, no paper or funded order was
submitted, and no capital policy or transfer was activated.

## Files changed

| Files | Change |
| --- | --- |
| `src/blackpod_build_week/paper_account_probe.py` | Explicit bounded YAML selection; existing PyYAML used lazily; selected values remain in memory |
| `src/blackpod_build_week/contracts/trading_reconciliation.py` | Immutable paper snapshot, ownership, reconciliation and computed-report contracts |
| `src/blackpod_build_week/contracts/decision_journal.py` | Additive strict v6 event dispatch |
| `src/blackpod_build_week/trading_reconciliation.py` | Pure source-bound projection, exact identity and cumulative-fill reconciliation, restart barriers |
| `src/blackpod_build_week/decision_journal_store.py` | Strict v6 semantic replay using existing immutable storage |
| `src/blackpod_build_week/trading_reconciliation_cli.py` | Explicit collection/import, ownership confirmations, reconciliation, export, show and book binding |
| `src/blackpod_build_week/paper_order_capture.py` | GET-only paper and tracked UUID capture, one frozen credential pair, typed validation and sanitized partial failures |
| `src/blackpod_build_week/paper_account_safety.py` | Verified installed book and shared per-account receipt ledger across runtime folders |
| `src/blackpod_build_week/auto_trading_runtime.py` | Strict v2 receipt binding; funded startup blocked before spawn |
| `src/blackpod_build_week/auto_trading_worker.py` | Paper book prerequisite, global-first durable receipts, known-order restore and funded rejection |
| `src/blackpod_build_week/galactica_trading_adapter.py` | Stable attempt/prior-quantity/client IDs, ambiguous outcomes, persistent guard and restored latches |
| `tests/test_trading_reconciliation_contracts.py`, `test_trading_reconciliation_engine.py`, `test_trading_reconciliation_store.py`, `test_trading_reconciliation_cli.py`, `test_trading_receipts.py`, `test_paper_account_safety.py`, `test_paper_order_capture.py`, `test_trading_reconciliation_examples.py` | New burst tests |
| `tests/test_paper_account_probe.py` | YAML-format coverage |
| `tests/test_galactica_trading_adapter.py` | Two integration tests extended with actual fixture journals/books/shared account receipts; native modules still mocked |
| `examples/paper_broker_snapshot.fixture.v1.json`, `trading_ownership.paper.v1.json`, `trading_reconciliation.paper.v1.json` | Strict runnable synthetic inputs |
| `fixtures/trading_reconciliation/` | Explicit synthetic broker source and expected canonical reconciliation |
| `docs/TRADING_RECONCILIATION.md`, this report, `docs/PAPER_ACCOUNT_CHECK.md`, `docs/AUTO_TRADING.md`, `README.md` | Corrected source selection, usage, boundaries and results |

Unrelated ModelDock changes remain intact. No Galactica/Quorum source,
credential file, canonical mission schema, stage policy, database or dependency
configuration was edited. The current checkout's existing PyYAML dependency is
unchanged. No inference or legacy runtime was started.

## Actual test results

**795 selected offline tests passed.** Counts are disjoint across these commands:

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests .venv/bin/python3.11 -m unittest \
  test_trading_reconciliation_contracts test_trading_reconciliation_engine \
  test_trading_reconciliation_store test_trading_receipts \
  test_trading_reconciliation_cli test_paper_account_safety \
  test_paper_order_capture test_trading_reconciliation_examples -q
# 142 passed, 17.607 seconds (final passive reassignment / protective-exit rerun)

PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests .venv/bin/python3.11 -m unittest \
  test_auto_trading_runtime test_galactica_trading_adapter \
  test_trading_automation test_paper_account_probe -q
# 107 passed, 1.447 seconds

PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests .venv/bin/python3.11 -m unittest \
  test_decision_journal_contracts test_decision_journal_projection \
  test_decision_journal_store test_decision_journal_cli \
  test_investment_hypothesis_contracts test_investment_hypothesis_sources \
  test_investment_hypothesis_store test_investment_hypothesis_examples \
  test_investment_hypothesis_cli test_investment_review_contracts \
  test_investment_review_engine test_investment_review_store \
  test_investment_review_cli -q
# 249 passed, 12.615 seconds

PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests .venv/bin/python3.11 -m unittest \
  test_investment_governance_contracts test_investment_governance_engine \
  test_investment_approval test_investment_governance_store \
  test_investment_governance_examples test_investment_governance_cli -q
# 125 passed, 63.774 seconds

PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests .venv/bin/python3.11 -m unittest \
  test_contracts test_mission_store test_mission_transitions \
  test_mission_presentation test_cli_help test_navigator_adapter \
  test_operator_adapter test_modeldock_config test_modeldock_client \
  test_modeldock_preflight test_modeldock_delivery -q
# 172 passed, 1.513 seconds

git diff --check
# passed
```

The new tests exercise wrong account/mode/scope, exact runtime/order/client IDs,
partial fill/cancel/reject/expiry, replacements, missing prior position, lost
acceptance, order/position lag, cumulative fill rollback, incomplete captures,
malformed and oversized data, credentials changing mid-capture, source isolation,
corrupt evidence, semantic tampering, pre/postcommit recovery, restore,
concurrent retries and idempotency after later events. They also verify exact
desk sets, preserved protective reductions, shared barriers across runtime
folders, legacy receipt compatibility and pre-import funded rejection.

Development failures were repaired before this final suite. Tests use fake
broker/HTTP responses, synthetic files and mocked native imports; no unit test
submits a broker order or starts a real native executor. The worker-to-adapter
tests include the actual journal, book binding, locks and global receipt writes.

## Actual paper observations

Successful repeatable confirmation:

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python3.11 \
  -m blackpod_build_week.paper_account_probe \
  --credential-source /Users/nikolai/buried_treasure/api_keys.yaml \
  --credential-format GALACTICA_YAML \
  --output-root output/auto-trading-paper-check
```

Result: confirmed PAPER, ACTIVE, trading not blocked, zero positions/open orders
at capture. Four HTTP 200 GET responses; no submit/cancel/close requests.
Account identity is retained privately; its suffix is `415c4c27`.

The newly implemented collector was also exercised against that exact account:

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python3.11 \
  -m blackpod_build_week.trading_reconciliation_cli capture-paper \
  --credential-source /Users/nikolai/buried_treasure/api_keys.yaml \
  --credential-format GALACTICA_YAML \
  --expected-account-id CONFIRMED_ACCOUNT_ID \
  --output-root output/auto-trading-paper-check
```

`CONFIRMED_ACCOUNT_ID` above redacts the private ID used in the actual command;
the exact value is retained in the ignored confirmation evidence. Result:
confirmed capture with the explicit tracked set empty. It does not
establish the absence of historical trades. Evidence names contain content
hashes and no key material:

- `paper-probe-49bff8bc5b531f14779cfb5abbb5015de199e273e6c2150e6dc31e21d4ed8733.json` — original confirmed probe.
- `paper-probe-8b9ee7b4c9b5f4211a389143dabc719248a3ed0157e18545b0be0ec14fd7250f.json` — new collector's confirmed composite.

Both were imported and separately reconciled in
`output/auto-trading-reconciliation-real`. The later observation links to the
first reconciliation. Result: **4 events, 6 evidence blobs, zero orphans**,
last entry `c55bfa45581f7b5ecd731848beaea7c702591fc921c5c441a40ba9972f0738b7`.
Both reports say `NO_EXECUTION_OBSERVED`, with null P&L and no authority.
Repeating all four real import/reconciliation commands wrote nothing and
preserved that final chain hash, including retries of the older observation.
No real desk ownership, budget allocation or account book was invented or installed.

Exact import/reconciliation commands for those retained files:

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python3.11 \
  -m blackpod_build_week.trading_reconciliation_cli import-probe \
  --journal-root output/auto-trading-reconciliation-real \
  --probe output/auto-trading-paper-check/paper-probe-49bff8bc5b531f14779cfb5abbb5015de199e273e6c2150e6dc31e21d4ed8733.json

PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python3.11 \
  -m blackpod_build_week.trading_reconciliation_cli reconcile \
  --journal-root output/auto-trading-reconciliation-real \
  --snapshot-event-id journal-event-643ad5196c9c9227fe21225cbb00a92544daf06b1a543fc970c2a515364dcc5a \
  --reconciliation-id initial-paper-baseline-20261012 \
  --recorded-at 2026-10-12T17:55:24.960371Z

PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python3.11 \
  -m blackpod_build_week.trading_reconciliation_cli import-probe \
  --journal-root output/auto-trading-reconciliation-real \
  --probe output/auto-trading-paper-check/paper-probe-8b9ee7b4c9b5f4211a389143dabc719248a3ed0157e18545b0be0ec14fd7250f.json

PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python3.11 \
  -m blackpod_build_week.trading_reconciliation_cli reconcile \
  --journal-root output/auto-trading-reconciliation-real \
  --snapshot-event-id journal-event-ace0528f63dc159e78784e1e80967741fd169789c3485584f3a5506b78610221 \
  --reconciliation-id paper-capture-baseline-20261012 \
  --recorded-at 2026-10-12T18:34:34.051283Z \
  --prior-reconciliation-event-id journal-event-54940b1e4b0a162dfcbaea167f5d1ef75cbb0445e6d386d1e53d776bc2ee31fa
```

The synthetic example's documented commands also ran successfully: **3 events,
4 blobs**, no orphans, exact committed expected event. Filled and uncertain
execution cases are synthetic coverage, not real paper performance.

## Existing history and runtime checks

These verification commands passed with their previous hashes unchanged:

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python3.11 \
  -m blackpod_build_week.harbormaster journal verify --journal-root output/decision-journal-archive-check
# 20 events / 122 blobs
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python3.11 \
  -m blackpod_build_week.harbormaster journal verify --journal-root output/investment-hypothesis-history-check
# 22 events / 124 blobs
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python3.11 \
  -m blackpod_build_week.harbormaster journal verify --journal-root output/investment-review-history-check
# 26 events / 128 blobs
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python3.11 \
  -m blackpod_build_week.harbormaster journal verify --journal-root output/investment-governance-example
# 9 events / 18 blobs
```

The original archive still includes 7 LIVE and 13 REPLAY revisions. Retrospective
research remains explicit annotation; no historical trade P&L or horizons were
fabricated. Actual paper coverage is authenticated empty-book observation;
filled-order, restart and native integration coverage uses fixtures/mocks.

Runtime status remains OFF with no active worker, no entries and no automatic
restart. Existing Quorum's interpreter reports alpaca-py 0.42.0 and pandas
2.3.1, matching Galactica pins; this was metadata inspection only. It did not
import/run native execution. No packages were installed.

## Remaining limits and next burst

No real paper order lifecycle was exercised. The working credentials and
compatible interpreter do not authorize trading. Actual symbols, ownership,
fixed dollar budget, expiry, frozen mandate/bias and activation still require
explicit operator inputs. Runtime credentials remain environment-only; the
read-only YAML collector does not silently replace the executor's environment.

Native audit CSVs and full source/input snapshots remain in runtime session
storage; the journal's runtime export retains profiles and their hashes, not
every native CSV or streamed bar. Preserve those archives for a full native
decision reconstruction; automatic native evidence export is future work.

Replacement attribution, legacy missing baselines, fees/lot accounting,
nanosecond ordering, signed identities/checkpoints, cross-checkout/host
coordination and large-ledger replay remain limited. Paper observations do not
validate funded performance. The initial 50/50 policy remains proposed and
inactive; no perpetual rebalancing or automated policy modification exists.

**Recommended next burst: deterministic fill-lot, fee and position accounting,
with a bounded paper acceptance exercise.** Require exact lot/order/fill lineage,
correct partial/cancel/replacement accounting, no fabricated P&L, recovery and
rollback tests, and reconciled broker balances. Run an actual paper entry/exit
only after explicit symbol ownership, budget, size and trial authorization.
Keep funded execution and automatic investment allocation disabled. This next
burst was not implemented or activated.
