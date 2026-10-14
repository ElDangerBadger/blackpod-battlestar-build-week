# Independent evidence reconciliation validation

This implementation records descriptive evidence comparisons. It does not close
native prerequisites, authenticate sources or establish a profitable strategy.
Auto-trading remains **OFF**. No trading rules, source prices, native histories,
ModelDock configuration, execution behavior or capital settings are changed.

## Authored fixture coverage

The new small example preserves twenty-two existing fixture events and their
evidence byte-for-byte. One authored segmented TRAIN capture, native qualification
and v21 review establish a 39-event prefix; three v22 reviews produce 42 events.
The sources are explicitly synthetic. No provider is contacted and no real
credential is read. Original hypotheses, prices and old native policies remain
unchanged.

The three cases cover no observed independent rows without completeness proof;
independent missing actions and partial symbol/type/date coverage;
SIP-versus-IEX and event-versus-delivery date mismatch; duplicate-action
ambiguity; missing paper account evidence; and contradictory fee formula claims.
They retain original native results, unresolved coverage proposals, null cost
parameter proposals, no execution and null realized trade P&L.
The inherited toy native result is ready for a shadow study design only. The
independent packets neither upgrade that result nor establish economic support.

## Test and artifact results

The final CLI and example gate passed after the raw-workbook-cell fix:

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests .venv/bin/python3.11 -m unittest test_evidence_reconciliation_cli test_evidence_reconciliation_example -q
```

Result: **24 tests passed in 142.606 seconds**, exit 0. These tests block socket
connections and subprocess workers. They cover schema-only preparation,
source-context export, assessment without append, exact record/retry/show/verify,
typed opaque-source loading, combined source bounds, hash/size failures, unsafe
paths and links, early source/Git/runtime guards, original-event preservation,
missing/ambiguous independent actions, scope conflicts and interrupted-prefix
publication followed by a zero-write retry.

Initial integration smoke found a new-module import and a legacy-link
assumption. Real-workbook integration then exposed unsupported blank-cell
validation arguments in the new contract. These findings are corrected in new
modules; no historical schema or validation rule is relaxed. The immutable
`output/independent-evidence-example-001` artifact retains preliminary method
pins from a previous 24-test pass and is not the final runnable example. The
final gate above uses the fixed sources, and the guide uses a fresh
`output/independent-evidence-example-002` destination.

The final designated gates passed **652 distinct cases: 114 new and 538
preserved**. This is the selected safe offline validation set, rather than an
assertion that every repository test was discovered and run.

After the raw-cell fix, the independent inventory parser and reconciliation gate
passed **39 tests in 1.603 seconds**, exit 0:

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests .venv/bin/python3.11 -m unittest test_independent_action_sources test_effective_date_reconciliation -q
```

This includes a full parser-to-result check of the retained 136-row SSGA source,
preserving blank and padded cells, and synthetic Unicode/whitespace and malformed
raw-cell tests. The two retained-workbook cases are explicitly skipped when that
local ignored evidence file is absent; both ran in this checkout. The other 37
source cases use authored inputs and remain available without that workbook.
No test downloads evidence.

The final combined continuity and independent-source gate passed **109 tests in
2.968 seconds**, exit 0: 70 preserved tests and the same 39 new source tests.
The earlier focused 39-test run is supplementary and is not counted twice.

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests .venv/bin/python3.11 -m unittest test_trading_continuity_intake test_trading_continuity_qualification test_effective_date_reconciliation test_independent_action_sources -q
```

The historical applicability gate passed **30 tests in 0.450 seconds**, exit 0:

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests .venv/bin/python3.11 -m unittest test_historical_feed_cost_applicability -q
```

The final journal gate passed **21 tests in 105.844 seconds**, exit 0:

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests .venv/bin/python3.11 -m unittest test_evidence_reconciliation_journal -q
```

The preserved fast regression gate passed **373 tests in 4.757 seconds**, exit 0:

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests .venv/bin/python3.11 -m unittest test_decision_journal_contracts test_decision_journal_store test_decision_journal_field_access test_auto_trading_runtime test_trading_automation test_paper_order_capture test_modeldock_config test_modeldock_client test_modeldock_preflight test_modeldock_delivery test_contracts test_mission_store test_mission_transitions test_trading_cost_intake test_trading_training_calibration test_trading_historical_intake -q
```

The preserved v21 gate passed **95 tests in 758.824 seconds**, exit 0:

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests .venv/bin/python3.11 -m unittest test_native_evidence_closure test_native_quote_diagnostics test_native_evidence_closure_journal test_native_evidence_closure_cli test_native_evidence_closure_example -q
```

The distinct rollup is 373 existing fast cases, 70 existing continuity cases,
95 existing v21 cases, 39 new source cases, 30 new applicability cases, 21 new
journal cases and 24 new CLI/example cases. Earlier preliminary runs and the
supplementary focused 39-case run are excluded from this count.

The existing runtime status remains OFF, with entries, capital transfers and
worker disabled. A baseline audit of 796 tracked files found only the three
existing-file changes listed below; all remaining implementation files are
additive.

The final read-only runtime command also returned exit 0:

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests .venv/bin/python3.11 -m blackpod_build_week.auto_trading_cli status --runtime-root output/auto-trading-runtime
```

It reports `requested_entries_enabled=false`, `entries_enabled=false`,
`worker_active=false` and `capital_transfers_permitted=false`.

The final authored artifact was generated and checked with these exact commands:

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests .venv/bin/python3.11 -m blackpod_build_week.evidence_reconciliation_example --output-root output/independent-evidence-example-002
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests .venv/bin/python3.11 -m blackpod_build_week.evidence_reconciliation_cli assess --request output/independent-evidence-example-002/input/empty-observations.request.json --journal-root output/independent-evidence-example-002/journal --output output/independent-evidence-example-002/reports/cli-assessment.json
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests .venv/bin/python3.11 -m blackpod_build_week.evidence_reconciliation_cli record --request output/independent-evidence-example-002/input/empty-observations.request.json --journal-root output/independent-evidence-example-002/journal
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests .venv/bin/python3.11 -m blackpod_build_week.evidence_reconciliation_cli verify --journal-root output/independent-evidence-example-002/journal
```

All four returned exit 0. Generation wrote 42 events; assessment changed no
native gates; the existing request retried with `written=false` at sequence 40.
Final verification reports **42 events, 189 evidence blobs, zero evidence
orphans and zero staging orphans**, with head
`4ba737d1a0c916f34f1e91a46fc79c61514d7f8e40fbb13e9162da677f35a28e`.
The first v22 event is
`journal-event-52639297e2766f91f410da27e9f37be4cfa233a092d22fce04e1dc3628b44187`.
The fixture reports zero provider calls, real credential reads, submitted orders
and inference calls; auto-trading and authority remain disabled.

## Changed-file inventory

Existing files receive only the README link and additive v22 journal contract and
store dispatch:

- `README.md`
- `src/blackpod_build_week/contracts/decision_journal.py`
- `src/blackpod_build_week/decision_journal_store.py`

New contracts, deterministic engines and journal adapter:

- `src/blackpod_build_week/contracts/effective_date_reconciliation.py`
- `src/blackpod_build_week/contracts/evidence_reconciliation.py`
- `src/blackpod_build_week/contracts/historical_feed_cost_applicability.py`
- `src/blackpod_build_week/independent_action_sources.py`
- `src/blackpod_build_week/effective_date_reconciliation.py`
- `src/blackpod_build_week/historical_feed_cost_applicability.py`
- `src/blackpod_build_week/evidence_reconciliation.py`
- `src/blackpod_build_week/evidence_reconciliation_journal.py`

New offline interface, example, tests and documentation:

- `src/blackpod_build_week/evidence_reconciliation_cli.py`
- `src/blackpod_build_week/evidence_reconciliation_example.py`
- `tests/test_independent_action_sources.py`
- `tests/test_effective_date_reconciliation.py`
- `tests/test_historical_feed_cost_applicability.py`
- `tests/test_evidence_reconciliation_journal.py`
- `tests/test_evidence_reconciliation_cli.py`
- `tests/test_evidence_reconciliation_example.py`
- `docs/INDEPENDENT_EVIDENCE_RECONCILIATION.md`
- `docs/INDEPENDENT_EVIDENCE_RECONCILIATION_VALIDATION.md`

## Retained real evidence

The prior real v21 journal contains 256 events and 2,138 retained evidence blobs.
Its source head is
`4b482b2b9a8143a6b0d8262c2573c403fc9ff8e877eb788a5c1c8f6acc5f59c6`.
The native qualification remains deferred for eight existing reasons. The new
report is appended in a physical working copy of that same history; the original
source journal remains unchanged. Original IDs and entry bytes are retained,
rather than creating a parallel decision history.

The published report over the retained inputs records 136 SPY
workbook rows, 11 matched comparison keys, 13 native-only keys, one
independent-only key and no ambiguous groups. It binds all 390 quote receipts.
All thirteen native-only keys are QQQ cash dividends, for which this inventory
provides no historical action rows. The sole independent-only key is the SPY
cash dividend dated `2026-09-18`; neither finding manufactures a native row or
proves that a source is complete.
The original 256-event, 2,138-blob history passed full semantic preflight. The
publication also passed the locked native-source preflight and v22 replay.
A current source URL or capture clock does not authenticate historical
coverage, units, fees, slippage or capacity. Issuer distribution data alone
cannot establish all action types or coverage for another issuer's ETF.

The actual result is
`output/effective-date-applicability-real-001/reports/review-001.result.v1.json`,
with status `DESCRIPTIVE_EVIDENCE_RECONCILIATION_ONLY`. Its native coverage
proposal remains `UNRESOLVED`; no cost assumptions are proposed. The exact
original native snapshot and all eight deferral reasons remain unchanged.

| Applicability category | Actual status |
| --- | --- |
| FEED_IDENTITY | UNRESOLVED |
| QUOTE_SIZE_UNITS | SCOPE_MISMATCH |
| FEE_SCHEDULE | UNRESOLVED |
| SLIPPAGE | SCOPE_MISMATCH |
| OPENING_CAPACITY | SCOPE_MISMATCH |

Publication produced event
`journal-event-cf462917740f01d0184fdc743ab1e06b1121c07927a4167155ecf2433d5cbb0c`
at sequence **257**, linked to the original decision
`journal-decision-8ed91c576c9912b90ffd0984abae0edf6d6fe17b798e2ce16e44019b655660dd`.
The working journal now has **257 events and 2,166 evidence blobs**, with head
`55405898493b932da9eff785aec1e3a3c116ed88bea7f749caa0cc7cd73f0f29`.
An independent filesystem audit confirms all 256 original entry bytes are
identical, every retained blob matches its SHA-256, and missing blobs, evidence
orphans and staging orphans are all zero. These byte-level checks are separate
from the completed full post-publication semantic retry described below.

The actual invocation was the local verification driver:

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests .venv/bin/python3.11 -u /private/tmp/blackpod_record_independent_evidence_real.py
```

It blocks socket connections and subprocess workers, works only from retained
inputs, and uses the existing `append_journal_batch` API for publication and an
exact retained-event retry. This is a local helper invocation, not a claim that
the real journal was recorded or verified through the public CLI. Public CLI
verification passed on the authored fixture. The real review remains
`NOT_EXECUTED`, with null realized trade P&L and auto-trading OFF.

Raw source bodies, input packets and working journals remain in the ignored
local `output/` directories. They are retained locally, not backed up by the
Git push; the implementation, tests and this validation record are tracked.

The driver completed with **exit 0**. Its durable summary is
`output/effective-date-applicability-real-001/reports/review-001.summary.v1.json`.
The exact retained-event retry passed the full locked post-publication semantic
replay: **one event retried, zero events written**, with the same 257 events,
2,166 evidence blobs and head hash. The summary confirms original entry bytes
preserved, zero evidence orphans and zero staging orphans. It records zero
provider API calls, orders and model inference calls, auto-trading false, and
`separate_verify_cli_run=false`. This semantic gate came from the retained-record
API retry, not a separate real CLI `verify` invocation.

The independent inventory retains the original [SSGA historical-distributions
workbook](https://www.ssga.com/library-content/products/fund-data/etfs/us/spdr-etf-historical-distributions.xlsx),
581,242 bytes, SHA-256
`b162dd17027d1128f2209e312b0f634960daa78319dafe0ab821ab0b7e77ce23`.
Its declared scope is SPY cash dividends from `2023-10-02` through `2026-10-12`,
with completeness `UNKNOWN`. QQQ product-page bytes and a source-gap note are
supporting evidence; they do not constitute a parsed QQQ historical inventory.
No other action type or authenticated complete calendar is inferred.

The applicability packet retains eight original public documents and explicit
claims. Publication-time precision remains unknown in these declarations.

| Retained source | What remains unresolved |
| --- | --- |
| [Alpaca historical-data documentation](https://docs.alpaca.markets/us/v1.1/docs/historical-stock-data-1.md) | Single-venue IEX identity is separate from consolidated SIP coverage; missing historical scopes remain explicit. |
| [2023 IEX staff response](https://forum.alpaca.markets/t/bid-and-ask-size-for-iex-data-is-not-as-reported-by-iex/12712) | A historical lot-size statement does not establish how historical IEX observations delivered in 2026 were normalized. |
| [CTA/UTP size-change notice](https://docs.alpaca.markets/us/v1.1/changelog/marketdata-bid-and-ask-size-display-change.md) | Its consolidated-feed display change does not automatically convert retained IEX units. |
| [Paper simulation documentation](https://docs.alpaca.markets/us/docs/paper-trading.md) | NBBO matching and simulator omissions do not establish IEX opening capacity or measured historical slippage. |
| [Current broker fee documentation](https://docs.alpaca.markets/us/v1.1/docs/regulatory-fees.md) | Current documentation does not establish historical account pass-through, caps or rounding. |
| [SEC 2023 Section 31 order](https://www.sec.gov/files/rules/other/2023/34-96724.pdf) | Retained charge-rate claims are not mapped automatically to trade dates or account charges. |
| [SEC 2024 advisory](https://www.sec.gov/rules-regulations/fee-rate-advisories/2024-2) | Effective charge periods and historical account applicability require separate evidence. |
| [FINRA 2024 filing](https://www.finra.org/sites/default/files/2024-11/sr-finra-2024-019.pdf) | Then-current descriptions and proposed future changes remain distinguishable; proposals are not presumed effective. |

Numeric claims remain their exact declared strings. The original constant-bps
plus per-fill model is not assumed to express side-dependent, per-share, capped
and rounded charges. The packet supplies no account evidence, fee parameters,
unit multiplier, slippage estimate or executable capacity.

The retained quote context separates the original TRAIN market-event interval,
`2023-10-02T13:30:00Z` through `2024-08-27T13:31:00Z`, from its retrospective
delivery interval, `2026-10-13T16:07:31.497650Z` through
`2026-10-13T17:22:30.411934Z`. No current document is automatically applied to
those historical periods. The independent SPY `2026-09-18` action discrepancy
is issuer-workbook metadata outside TRAIN and within the retained dataset span;
it is not holdout return scoring. No outcome, strategy return or realized P&L
is computed.

## Remaining limitations and next burst

Matching observed rows does not prove complete all-type effective-date coverage.
Independent action rows do not automatically enter old native masks. Current
documentation cannot silently supply historical account rates or convert native
quote units. No assumption or risk approval is manufactured. Wide spreads remain
unclipped, and no strategy return or uncertainty statistic is computed.

Full semantic replay of the real source corpus remains expensive. The new
metadata context is not a trusted cache; source history is still verified at
journal boundaries.

The single recommended next burst is a **governed versioned reconciled native
action intake with a retained independent QQQ distribution inventory**. Keep
provider and issuer records separately identifiable, and surface the SPY
`2026-09-18` discrepancy conservatively. An issuer observation must never become
a fabricated Alpaca record.

Proposed acceptance criteria for that future burst:

- Retain original QQQ issuer distribution bytes with publisher, URL, hash,
  capture clock, explicit symbol/type/date scope and unresolved gaps. A product
  page alone does not count as a historical distribution inventory.
- Produce an append-only, versioned reconciliation artifact that links every
  admitted observation to its original provider or issuer identity. Tests cover
  matches, missing rows, duplicates, conflicts, unknown dates and status changes;
  the SPY discrepancy remains visible until separately resolved by evidence.
- Preserve all existing source bytes, masks and policies exactly. Freeze a new
  source-selection and effective-date policy and pass deterministic mapping and
  failure tests before any mask change; any new shadow artifact has explicit
  lineage and no automatic authority to replace an existing mask.
- Prove idempotent retries, conflict rejection and interrupted-publication
  recovery. Tests must keep uncovered symbol/type/date cells unresolved: positive
  cash-distribution matches cannot establish completeness across all thirteen
  action types or create economic, execution or policy authority.

Historical IEX normalization and account-specific cost applicability remain
separate prerequisites; this proposed intake cannot clear them. Keep
auto-trading OFF. This recommendation is not implemented in this checkpoint.
