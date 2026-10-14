# Reconciled action intake validation

This checkpoint is shadow research only. Existing provider records, dataset
prices, hypotheses, native masks, policies, mission schemas, Navigator behavior
and ModelDock configuration remain unchanged. No broker, model inference or
capital movement is part of the new offline intake. Auto-trading stays **OFF**.

## Coverage and trust boundaries

The authored example reuses a small exact v22 fixture prefix and preserves the
twenty-two original fixture events and their evidence. Its synthetic universe
remains SYNTHA/SYNTHB; an authored inventory is not relabeled as real QQQ
issuer evidence. The fixed QQQ source profile has separate parser tests and any
actual retained issuer evidence is reported separately.

The required gates cover frozen policy registration, source identity and date
lineage, conflicting and missing evidence, old-mask preservation, explicit old
consumer incompatibility, safe bounded loading, immutable publication,
idempotent retries and recovery. No test may infer all-type completeness from
matching cash distributions or permit an operational gate override.

## Final offline gates

The final CLI/example gate passed **21 tests in 151.682 seconds**, exit 0:

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests .venv/bin/python3.11 -m unittest test_reconciled_action_intake_cli test_reconciled_action_intake_example -q
```

These tests block socket connections and worker subprocesses. They cover opaque
typed leaves for old and new inventory profiles, safe bounded loading, request
preparation without history reads, policy-bundle preparation and registration,
assessment without append, exact policy/intake retries, show/verify, protected
destinations and interrupted-prefix recovery. The example tests preserve the
different original native-intake decision identity while linking new records to
the original research decision.

The QQQ parser gate passed **28 tests in 0.235 seconds**, exit 0:

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests .venv/bin/python3.11 -m unittest test_qqq_distribution_inventory -q
```

One conditional case uses the actual locally retained issuer body; it ran here
and is skipped when those ignored source files are absent. The other 27 cases
use authored inputs. No test downloads a source.

The final combined source/continuity gate passed **137 tests in 3.230 seconds**,
exit 0. It includes those 28 new cases and 109 preserved cases; the focused
28-case run is supplementary and is not counted twice:

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests .venv/bin/python3.11 -m unittest test_trading_continuity_intake test_trading_continuity_qualification test_effective_date_reconciliation test_independent_action_sources test_qqq_distribution_inventory -q
```

The pure intake gate passed **36 tests in 0.676 seconds**, exit 0:

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests .venv/bin/python3.11 -m unittest test_reconciled_action_intake -q
```

The final journal gate passed **22 tests in 112.177 seconds**, exit 0:

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests .venv/bin/python3.11 -m unittest test_reconciled_action_journal -q
```

An initial tamper-test setup needed write permission to simulate bypassing the
immutable file mode. Only that test setup was repaired; production verification
was not relaxed. The final fresh gate above passed.

The preserved fast gate passed **373 tests in 3.966 seconds**, exit 0:

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests .venv/bin/python3.11 -m unittest test_decision_journal_contracts test_decision_journal_store test_decision_journal_field_access test_auto_trading_runtime test_trading_automation test_paper_order_capture test_modeldock_config test_modeldock_client test_modeldock_preflight test_modeldock_delivery test_contracts test_mission_store test_mission_transitions test_trading_cost_intake test_trading_training_calibration test_trading_historical_intake -q
```

The preserved v22 gate passed **75 tests in 231.340 seconds**, exit 0:

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests .venv/bin/python3.11 -m unittest test_historical_feed_cost_applicability test_evidence_reconciliation_journal test_evidence_reconciliation_cli test_evidence_reconciliation_example -q
```

The final designated set is **664 distinct passing cases: 107 new and 557
preserved**. This is the selected safe offline set, not a claim that every
repository test was discovered. The focused 28-case run is already included in
137 and is excluded from the rollup. The 814-file baseline audit found only the
README and two additive journal-dispatch changes among existing files.

The separate real-history publication and post-publication verification gates
also passed, as recorded below. Fixture results do not substitute for that
retained-history evidence.

## Durable authored example

These exact commands returned exit 0:

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests .venv/bin/python3.11 -m blackpod_build_week.reconciled_action_intake_example --output-root output/reconciled-action-intake-example-001
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests .venv/bin/python3.11 -m blackpod_build_week.reconciled_action_intake_cli verify --journal-root output/reconciled-action-intake-example-001/journal
```

The example wrote **42 events and 186 evidence blobs**, with zero evidence
orphans and zero staging orphans. Its final head is
`375ca398059760a22672f2ede6c926d4625f4b95d20a03fb1b8fe0f8e86311da`.
The frozen policy at sequence 41 is
`journal-event-04d609f55e87eb59aa8297547d4c7e34052a1b8b20bc2315e8f0807da7a0268a`;
the candidate intake at sequence 42 is
`journal-event-bcaf95aae6d70f0e753cd45a17ddeaf373c07371f98b92679833650338b7c5b4`.
Both retain the exact v22 anchor
`journal-event-52639297e2766f91f410da27e9f37be4cfa233a092d22fce04e1dc3628b44187`
and the original research decision identity.

The forty source events include all twenty-two original fixture events. The
candidate retains eight authored issuer rows, five issuer-only key groups, one
ambiguous group and one duplicate group. The original provider audit has no
actions; none are manufactured to create positive matches. The source tests
cover positive matches independently.

The artifact remains `SHADOW_CANDIDATE_NOT_ELIGIBLE`, with unchanged old masks,
`legacy_source_compatible=false`, no economic support, `NOT_EXECUTED` and null
realized trade P&L. It reports zero provider API calls, credential-file reads,
orders and inference calls. Auto-trading remains OFF.

## Verified retained real evidence

The actual retained-data intake records **89 QQQ and 136 SPY issuer
observations**, alongside 26 original native observations. The full locked
source replay, new policy/intake publication and complete post-publication
semantic retry passed. This verifies the retained history and deterministic
calculation; it does not authenticate issuer truth or prove complete coverage.

| Comparison scope | Matched keys | Native-only | Issuer-only |
| --- | ---: | ---: | ---: |
| All retained observation keys | 26 | 0 | 199 |
| Within the original dataset span | 24 | 0 | 1 |

Two hundred issuer rows precede the dataset. The in-dataset issuer-only row is
the existing SPY `2026-09-18` discrepancy; its metadata is outside TRAIN and is
not holdout return scoring. No provider row is fabricated to remove it.
Matched keys do not establish agreement of every value, payment or completeness.

The verified candidate overlay retains **251 separate source boundaries**, including
49 active proposed boundary markers. A marker is not an eligible trading or
study instruction. All 26 symbol/action-type coverage cells remain unresolved;
original source records, masks and policies remain unchanged. Total QQQ
distribution amounts and ordinary-income components retain separate literal
source fields, with no payment or tax-classification inference.

The actual source is the publisher-disclosed [Invesco QQQ distribution
resource](https://dng-api.invesco.com/cache/v1/accounts/en_US/shareclasses/46090E103/distribution?idType=cusip&productType=ETF).
Its 27,437-byte response was captured at `2026-10-14T02:05:08.383765Z`, with
SHA-256 `8cac48440d684d73a51016d1b98323b2ffd85a378bd82f987c43c807f0ae1aa2`.
The 502-byte receipt retains SHA-256
`6aa1045cd16ae35309e08503e51ad12dd6c788cf8ba4b5a10533b6cdf6bad332`.
The original retained product-page discovery evidence is separate from that
response. The declaration covers QQQ cash dividends from `2023-10-02` through
`2026-10-12`, with completeness `UNKNOWN`; all 89 returned rows remain retained.

The original native mask fragment remains exactly 357,659 bytes, SHA-256
`93bba5cc035aa09e7bcb9c2dec940c07371845b842135e068a4a9c5191338dc6`.
The frozen policy artifact is 2,160 bytes, SHA-256
`1f7d6bbfccdf4e22b9ab566a9b9eca12950c83817a2febc35d4a81e9c45bfb4e`.
Neither artifact changes an old policy or mask.

Publication appended policy
`journal-event-057034803c3c90476259eae4469d7a987ff47813600120a863f5577aac4b422c`
at sequence **258** and intake
`journal-event-4cec3a9b5f8beeb52d090f3327b3aa7bbe3efde33caa76278872311bf1e8e6f7`
at sequence **259**. The final journal contains **259 events and 2,179 evidence
blobs**, with zero evidence orphans and zero staging orphans. Its head is
`c0bc485655f56403aa9226715da34419dabd11f9a60f99ff2b8572d72c70e106`.
All 257 original prefix entries are byte-identical, and the original source
journal's 257 events and 2,166 blobs remain unchanged.

The real journal is a retained-data descendant containing setup and research
history. Its 259 records are not 259 independent trades or actual investment
decisions. The source journal is
`output/effective-date-applicability-real-001/journal`; the descendant is
`output/reconciled-action-intake-real-001/journal`.

The exact local helper invocations were:

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python3.11 /private/tmp/blackpod_prepare_reconciled_actions_real.py
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python3.11 /private/tmp/blackpod_record_reconciled_actions_real.py
```

These temporary manual helpers use the existing `append_journal_batch` API and
original writer lock, with a physical source copy, no cache or skipped semantic
checks, and socket connections and subprocess workers forbidden during replay.
The locked source/suffix publication gate took **2,020.976 seconds**. The full
259-event post-publication semantic replay and exact two-event retry took
**1,999.595 seconds** and wrote **zero events** (`[false, false]`). The driver
exited 0. This is an API verification result; no standalone public CLI real
`verify` invocation is claimed. Public CLI verification passed on the authored
fixture.

The durable actual results are
`output/reconciled-action-intake-real-001/result.v1.json` and
`output/reconciled-action-intake-real-001/verification-summary.json`.
Source acquisition made one public issuer-history GET. The integration reports
zero broker calls, Alpaca market-data calls, inference calls and submitted
orders. Auto-trading remains OFF; execution is `NOT_EXECUTED` and realized trade
P&L is null. The intake remains `SHADOW_CANDIDATE_NOT_ELIGIBLE`, with
`legacy_source_compatible=false`, `eligible_for_shadow_study=false` and
`native_gate_override=false`.

All 26 coverage cells remain unresolved. The exact original native
qualification still carries all eight reasons:

- `EXPLICIT_SIMULATION_RISK_REVIEW_UNQUALIFIED`
- `INDEPENDENT_EFFECTIVE_DATE_COVERAGE_UNVERIFIED`
- `NO_COMPARABLE_CONTINUITY_WINDOWS`
- `NO_JOINT_CONTINUITY_SIZING_CAPACITY_WINDOWS`
- `QUALIFICATION_POLICY_NOT_REVIEWED_FOR_SHADOW`
- `RISK_REVIEW_NOT_APPROVED_FOR_SHADOW`
- `TRAINING_COST_AND_CAPACITY_ASSUMPTIONS_MISSING`
- `UNCERTAINTY_STABILITY_PROTOCOL_MISSING`

## Changed-file inventory

Existing files receive only the README link and additive v23 contract/store
dispatch:

- `README.md`
- `src/blackpod_build_week/contracts/decision_journal.py`
- `src/blackpod_build_week/decision_journal_store.py`

New implementation and interfaces:

- `src/blackpod_build_week/contracts/qqq_distribution_inventory.py`
- `src/blackpod_build_week/contracts/reconciled_action_intake.py`
- `src/blackpod_build_week/contracts/reconciled_action_journal.py`
- `src/blackpod_build_week/qqq_distribution_inventory.py`
- `src/blackpod_build_week/reconciled_action_intake.py`
- `src/blackpod_build_week/reconciled_action_journal.py`
- `src/blackpod_build_week/reconciled_action_intake_cli.py`
- `src/blackpod_build_week/reconciled_action_intake_example.py`

New tests and documentation:

- `tests/test_qqq_distribution_inventory.py`
- `tests/test_reconciled_action_intake.py`
- `tests/test_reconciled_action_journal.py`
- `tests/test_reconciled_action_intake_cli.py`
- `tests/test_reconciled_action_intake_example.py`
- `docs/RECONCILED_ACTION_INTAKE.md`
- `docs/RECONCILED_ACTION_INTAKE_VALIDATION.md`

## Remaining limitations

Listed issuer distributions do not authenticate occurrence, historical
availability or complete action coverage. A candidate overlay is not a native
qualification or an authorized trading instruction. Historical IEX unit
normalization and account-specific cost evidence remain separate gaps; no fee,
unit multiplier, slippage or capacity parameter is assigned by this intake.

Raw evidence and working journals under ignored `output/` directories are local
artifacts, not backups supplied by a Git push. Full real-history semantic replay
remains expensive and must not be replaced by an unverified cache.

The single recommended next burst is a **versioned shadow qualification
consumer for the reconciled overlay**. Bind exact policy/intake versions and
source lineage, retain every original native gate, and test deterministic
rejection of incompatible or unbound inputs. Coverage, cost and risk evidence
that remains unresolved must keep eligibility false; the consumer must never
override a native gate or activate trading. Keep auto-trading OFF. This next
burst is recommended, not implemented here.
