# Reconciled shadow qualification validation

This checkpoint consumes retained reconciled evidence in shadow research only.
It preserves original source records, native masks, prices, hypotheses,
calibration, uncertainty, risk policies, mission behavior and ModelDock settings.
Auto-trading remains **OFF**. No provider, broker, inference, execution or capital
movement is part of the new consumer.

## Fixture coverage

The authored example preserves all 42 prior v23 fixture events and their
evidence, including all 22 original source events. One new v24 event produces a
43-event history. The unchanged SYNTHA/SYNTHB evidence includes duplicate,
unknown-date and outside-span observations; it is not relabeled as real issuer
data. Candidate versus benchmark witness diagnostics remain separate from
native and final effective eligibility.

The frozen example was generated with:

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests .venv/bin/python3.11 -m blackpod_build_week.reconciled_shadow_qualification_example --output-root output/reconciled-shadow-qualification-example-001
```

The command exited 0 and produced 43 events, 192 evidence blobs, zero evidence
orphans and zero staging orphans. The final envelope SHA-256 is
`4ebb1ca70ebe202f53b01f992aa157d63ef0b79870eb1a72fdb93d578f94fc04`.
The new qualification is
`journal-event-c6861fdfe552d4605d3cdcc215f36b17e921189eb9a19c03aaa175a7680f3fa7`
at sequence 43, linked to the unchanged v23 intake
`journal-event-bcaf95aae6d70f0e753cd45a17ddeaf373c07371f98b92679833650338b7c5b4`.
An independent read-only comparison against the preceding durable v23 example
confirmed all 42 original entry files are byte-identical.

| Authored fixture measure | Count |
| --- | ---: |
| Original opportunities retained | 18 |
| Candidate / benchmark / either diagnostic veto | 9 / 18 / 18 |
| Original native combined / joint eligible | 16 / 16 |
| Newly ineligible / newly ineligible due to an overlay veto | 16 / 16 |
| Effective combined / joint eligible | 0 / 0 |
| Original risk checks retained | 18 |

Every window is deferred. Original final holdout indices 35–39 remain
`WITHHELD` and `access_sealed: false`. These are toy diagnostic counts, not
trades avoided or an economic result. The actual real history has different
native eligibility and must not inherit the fixture's count of 16 newly
ineligible windows.

The following public CLI commands were then executed, all with exit 0:

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests .venv/bin/python3.11 -m blackpod_build_week.reconciled_shadow_qualification_cli prepare --qualification-id authored-reconciled-shadow-qualification --recorded-at 2025-04-11T12:00:00Z --data-cutoff-at 2025-04-11T11:00:00Z --inputs output/reconciled-shadow-qualification-example-001/input/prepare-inputs.json --output output/reconciled-shadow-qualification-example-001/prepared/request.v1.json
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests .venv/bin/python3.11 -m blackpod_build_week.reconciled_shadow_qualification_cli assess --request output/reconciled-shadow-qualification-example-001/prepared/request.v1.json --journal-root output/reconciled-shadow-qualification-example-001/journal --output output/reconciled-shadow-qualification-example-001/reports/assessed.v1.json
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests .venv/bin/python3.11 -m blackpod_build_week.reconciled_shadow_qualification_cli record --request output/reconciled-shadow-qualification-example-001/prepared/request.v1.json --journal-root output/reconciled-shadow-qualification-example-001/journal
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests .venv/bin/python3.11 -m blackpod_build_week.reconciled_shadow_qualification_cli show --event-id journal-event-c6861fdfe552d4605d3cdcc215f36b17e921189eb9a19c03aaa175a7680f3fa7 --journal-root output/reconciled-shadow-qualification-example-001/journal
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests .venv/bin/python3.11 -m blackpod_build_week.reconciled_shadow_qualification_cli verify --journal-root output/reconciled-shadow-qualification-example-001/journal
```

Preparation correctly declared no source verification or assessment; its
request bytes match the original fixture request. Assessment wrote no journal
event, and its result bytes match the original fixture report. Recording
retried sequence 43 with `written: false`. `show` selected that exact v24 event.
Public CLI verification confirmed 43 events, 192 blobs, the same head hash and
zero evidence/staging orphans. All commands reported auto-trading false and zero
provider calls. The example also reported zero credential-file reads, model
inference calls and submitted orders.

Required gates cover exact source/policy binding, inherited native decisions,
boundary identities and interval semantics, unknown-date scope, restrictive
vetoes, all-false effective eligibility, safe bounded typed loading, source
preservation, immutable retries and interrupted-prefix recovery.

Two preliminary 22-case CLI/example runs each encountered one replay mismatch
after new method sources changed during the run. The immutable implementation
pin correctly failed closed. Those runs are not final gates, and no durable
example was published from them. Final gates use a fresh process after all
method sources are frozen; no validation rule is weakened to accept changed
pins.

Review also added strict malformed risk-key and boolean checks, required actual
retained source leaves instead of reconstructing missing evidence from installed
code, and rejected request-path collisions. These repairs affect only the new
methods. Earlier successful runs before those repairs are not final gates.

## Final offline tests

The final fresh owned CLI/example command uses frozen calculation sources:

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests .venv/bin/python3.11 -m unittest test_reconciled_shadow_qualification_example test_reconciled_shadow_qualification_cli -q
```

Result: **22 tests passed in 126.791 seconds**, exit 0, after the final
malformed-input and exact-source retention audit. The final pure
contract/engine gate passed:

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests .venv/bin/python3.11 -m unittest test_reconciled_shadow_qualification -q
```

Result: **35 tests passed in 9.469 seconds**, exit 0. These authored tests block
socket connections and worker subprocesses. The final storage gate passed:

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests .venv/bin/python3.11 -m unittest test_reconciled_shadow_qualification_journal -q
```

Result: **29 tests passed in 146.472 seconds**, exit 0. The selected preserved gates passed
with these exact commands (all exit 0):

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests .venv/bin/python3.11 -m unittest test_decision_journal_contracts test_decision_journal_store test_decision_journal_field_access test_auto_trading_runtime test_trading_automation test_paper_order_capture test_modeldock_config test_modeldock_client test_modeldock_preflight test_modeldock_delivery test_contracts test_mission_store test_mission_transitions test_trading_cost_intake test_trading_training_calibration test_trading_historical_intake -q
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests .venv/bin/python3.11 -m unittest test_trading_continuity_intake test_trading_continuity_qualification test_effective_date_reconciliation test_independent_action_sources test_qqq_distribution_inventory -q
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests .venv/bin/python3.11 -m unittest test_reconciled_action_intake test_reconciled_action_journal test_reconciled_action_intake_cli test_reconciled_action_intake_example -q
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests .venv/bin/python3.11 -m unittest test_historical_feed_cost_applicability test_evidence_reconciliation_journal test_evidence_reconciliation_cli test_evidence_reconciliation_example -q
```

| Preserved gate | Cases | Seconds | Result |
| --- | ---: | ---: | --- |
| Journal, runtime, ModelDock, mission and intake | 373 | 3.847 | PASS |
| Native continuity and independent source contracts | 137 | 4.270 | PASS |
| Prior reconciled action intake | 79 | 307.620 | PASS |
| Prior independent reconciliation | 75 | 271.213 | PASS |

These are **664 selected preserved cases**; they are not a claim that every
repository test was executed. The final designated offline gate is **750 passing
cases: 86 new and 664 preserved**. Supplementary development reruns are not added
to that count. A baseline hash audit of 829 tracked files found only the
README and the two additive journal dispatch files changed among existing files.
The 86 new cases use authored fixtures and malformed-input/recovery cases;
they do not constitute a full retained-real journal qualification. Retained
issuer-source parser coverage belongs to the selected preserved gates, while
the new real-history integration is reported separately below.

## Retained-history coverage

The retained-real integration **passed**, with results retained in
`output/reconciled-shadow-qualification-real-001/verification-summary.json` and
`result.v1.json`. It used a physical working copy of the existing 259-event,
2,179-blob history from `output/reconciled-action-intake-real-001/journal`.
All 259 original entry bytes and the original source journal's entry/blob
hashes remain unchanged. This is a descendant of the same retained research
history, not a separate decision history or 260 independent trades.

The new event is
`journal-event-18422ec718e33d22fd3785e8fa965184b0244314209459fe239b57c981b277ff`
at sequence 260 on original research decision
`journal-decision-8ed91c576c9912b90ffd0984abae0edf6d6fe17b798e2ce16e44019b655660dd`.
It selects the original v23 intake
`journal-event-4cec3a9b5f8beeb52d090f3327b3aa7bbe3efde33caa76278872311bf1e8e6f7`
and policy
`journal-event-057034803c3c90476259eae4469d7a987ff47813600120a863f5577aac4b422c`.
The completed journal contains **260 events and 2,185 blobs**, with zero evidence
orphans and zero staging orphans. Its final envelope SHA-256 is
`d4bcea58269b5c0b3d8e36465869c555e30adfd5a00bcef8c36ca57a414ef15e`.

These exact local verification commands were executed:

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python3.11 /private/tmp/blackpod_prepare_reconciled_shadow_real.py
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python3.11 /private/tmp/blackpod_record_reconciled_shadow_real.py
```

The temporary helpers used the existing `append_journal_batch` API under the
original full writer lock, with socket connections and subprocess creation
forbidden. Complete source replay plus new-event validation/publication passed
in **2,063.546 seconds**. Full post-publication semantic replay of all 260 events
and the exact one-event retry passed in **2,058.401 seconds**, driver exit 0.
The retry returned `[false]`: zero events were written. No trusted verification
cache, skipped source validation or implementation-pin bypass was used.

This real verification used APIs through local helpers; a separate standalone
public CLI `verify` was **not** run against the real corpus. The public CLI's
five-command lifecycle was independently demonstrated on the 43-event authored
fixture above. Passing those fixture tests is distinct from the completed full
retained-real replay.

| Retained-real measure | Count |
| --- | ---: |
| Original opportunities retained / deferred | 450 / 450 |
| Candidate / benchmark / either diagnostic veto | 54 / 30 / 57 |
| No additional diagnostic overlay veto | 393 |
| Native combined / joint eligible | 0 / 0 |
| Effective combined / joint eligible | 0 / 0 |
| Newly ineligible / newly ineligible due to an overlay veto | 0 / 0 |
| Original risk checks retained | 450 |
| Boundary records retained / unresolved coverage cells | 251 / 26 |
| Original late-exit rows retained | 6 |

| Candidate role | Windows with a witness | Boundary witnesses |
| --- | ---: | ---: |
| Feature | 30 | 60 |
| Entry | 6 | 12 |
| Holding/exit | 18 | 36 |
| Unknown date | 0 | 0 |

The fixed-universe benchmark retains 96 boundary witnesses across its 30 vetoed
windows. Provider and issuer identities remain separate, so witness counts are
not counts of independent economic actions. The 393 diagnostically clear
windows remain ineligible. All real windows were already native-ineligible;
the overlay therefore does not newly disqualify any of them. This differs from
the toy fixture's 16 newly ineligible windows.

The original native mask SHA-256 remains
`93bba5cc035aa09e7bcb9c2dec940c07371845b842135e068a4a9c5191338dc6`;
the original full native qualification snapshot SHA-256 remains
`043c5c65ceb40e1d0e4d42a5b2ef1eb33d0a4dd7fa5d0cac1ddaa0f44c39de5a`.
The review retains 42 frozen method source pins. All 26 unresolved coverage
cells and these eight original native reasons remain unchanged:

```text
EXPLICIT_SIMULATION_RISK_REVIEW_UNQUALIFIED
INDEPENDENT_EFFECTIVE_DATE_COVERAGE_UNVERIFIED
NO_COMPARABLE_CONTINUITY_WINDOWS
NO_JOINT_CONTINUITY_SIZING_CAPACITY_WINDOWS
QUALIFICATION_POLICY_NOT_REVIEWED_FOR_SHADOW
RISK_REVIEW_NOT_APPROVED_FOR_SHADOW
TRAINING_COST_AND_CAPACITY_ASSUMPTIONS_MISSING
UNCERTAINTY_STABILITY_PROTOCOL_MISSING
```

The result is `DEFER_RECONCILED_SHADOW_QUALIFICATION`. Final holdout indices
611–759 remain `WITHHELD` and `access_sealed: false`; no outcomes or returns
were computed. Execution remains `NOT_EXECUTED` with null realized trade P&L.
This burst made zero new public-document GETs, broker calls, market-data calls,
model-inference calls or order submissions. Auto-trading remains false.

## Limits

This consumer produces no strategy signal, return, P&L, cost estimate or new
price series. A clean diagnostic interval cannot override an ineligible source,
unknown risk determination or original native gate. Unresolved cash-distribution
and other action-type coverage is not promoted by positive matching keys.

Raw evidence and journals under ignored local `output/` directories are retained
locally, not backed up by a Git push. Full semantic replay of the retained real
corpus remains expensive; source verification is not replaced by a cache or a
snapshot assertion.

## File inventory

The additive implementation consists of these new files:

- `src/blackpod_build_week/contracts/reconciled_shadow_qualification.py`
- `src/blackpod_build_week/contracts/reconciled_shadow_qualification_journal.py`
- `src/blackpod_build_week/reconciled_shadow_qualification.py`
- `src/blackpod_build_week/reconciled_shadow_qualification_journal.py`
- `src/blackpod_build_week/reconciled_shadow_qualification_cli.py`
- `src/blackpod_build_week/reconciled_shadow_qualification_example.py`
- `tests/test_reconciled_shadow_qualification.py`
- `tests/test_reconciled_shadow_qualification_journal.py`
- `tests/test_reconciled_shadow_qualification_cli.py`
- `tests/test_reconciled_shadow_qualification_example.py`
- `docs/RECONCILED_SHADOW_QUALIFICATION.md`
- `docs/RECONCILED_SHADOW_QUALIFICATION_VALIDATION.md`

`README.md` links the new workflow. The existing
`src/blackpod_build_week/contracts/decision_journal.py` and
`src/blackpod_build_week/decision_journal_store.py` add v24 dispatch. Prior
versioned calculation methods, runtime behavior and configuration are not
changed by this burst.

## One recommended next burst

Introduce a governed, versioned **type-scoped coverage evidence review and
admission**. Its acceptance criteria should be:

- Freeze each symbol, action type, effective interval, required source purpose
  and admission rule before assessment; retain the evidence and reviewer claim
  provenance without treating a local label as authenticated approval.
- Preserve provider and issuer identities, contradictions, revisions, unknown
  dates and uncovered intervals. Positive cash-distribution matches cannot
  establish completeness for all 13 action types.
- Emit a new explicit cell-level coverage decision under a new policy/contract
  version. Leave unproved cells unresolved and preserve all existing v23/v24
  records, masks and qualification results.
- Test partial spans, missing types, duplicate/conflicting declarations and
  wrong-scope evidence, including exact retries and historical replay. Any
  eventual mask change must use an independently tested new consumer version.
- Keep historical feed/size applicability, account cost/capacity, risk review
  and uncertainty prerequisites independently closed. Grant no live authority.

This is a recommendation only; it is not implemented in this burst.
