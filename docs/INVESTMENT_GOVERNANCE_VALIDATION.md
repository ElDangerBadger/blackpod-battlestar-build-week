# Burst 4 implementation and validation — 2026-10-11

Implemented deterministic investment proposal gates and exact-hash declared
SHADOW approval, plus the requested persistent trading intent and separately
invoked guarded Galactica/Alpaca execution toggle. Implementation and tests
leave the actual executor OFF. No native executor, provider, broker, inference,
order submission, database migration or capital movement was run.

## Files changed in this burst

Earlier journal/hypothesis/review work and unrelated ModelDock working-tree
changes remain present. This list describes the current burst's scope:

| Files | Change |
| --- | --- |
| `src/blackpod_build_week/contracts/investment_governance.py` | Strict risk policy, context, proposal, approval and report contracts |
| `src/blackpod_build_week/investment_governance.py` | Pure Decimal risk/evidence gates and retained-source proposal projection |
| `src/blackpod_build_week/investment_approval.py` | Exact evidence/policy/context/report binding, refreshed gate, separation, expiry and revocation |
| `src/blackpod_build_week/contracts/decision_journal.py` | Additive v4 investment governance and v5 trading intent events |
| `src/blackpod_build_week/decision_journal_store.py` | Additive replayable governance/intent validators; existing append-only storage retained |
| `src/blackpod_build_week/decision_journal_cli.py` | Proposal/review CLI, mandatory review confirmations, separate OFF/BLOCKED journal intent |
| `src/blackpod_build_week/contracts/trading_automation.py`, `trading_automation.py` | Immutable non-executable trading-intent contract and projection |
| `src/blackpod_build_week/auto_trading_cli.py`, `auto_trading_runtime.py`, `auto_trading_worker.py` | Explicit OFF/ON/draining process controller, retained profiles/source snapshots, local locks, runtime hash chain and recovery |
| `src/blackpod_build_week/galactica_trading_adapter.py` | Pinned native import connection and scoped account/ownership/order/risk facade |
| `tests/test_investment_governance_contracts.py`, `test_investment_governance_engine.py`, `test_investment_approval.py`, `test_investment_governance_store.py`, `test_investment_governance_cli.py`, `test_investment_governance_examples.py` | Governance tests |
| `tests/test_trading_automation.py`, `test_auto_trading_runtime.py`, `test_galactica_trading_adapter.py` | Intent, controller, recovery, isolation and mocked executable integration tests |
| `examples/investment_risk_policy.shadow.v1.json`, `investment_risk_context.shadow.v1.json`, `investment_proposal.shadow.v1.json`, `investment_approval.simulated.v1.json` | Bound runnable governance example inputs |
| `examples/auto_trading.control.off.v1.json`, `auto_trading_profile.paper.template.json` | Runnable inactive intent and explicitly incomplete runtime template |
| `fixtures/investment_governance/` | Actual MissionStore-produced synthetic sources, bound research, negative cases and expected immutable events/entries |
| `docs/INVESTMENT_GOVERNANCE.md`, `AUTO_TRADING.md`, this report | Design, exact usage and validation |
| `README.md`, `docs/ARCHITECTURE.md`, `docs/SAFETY_BOUNDARY.md`, `.gitignore` | Discoverability, separate authority boundary and ignored runtime output |

Canonical mission contracts, stage policies/workflows, the existing Navigator
adapter, ModelDock configuration, dependencies and sibling repositories were
not edited by this burst. Existing unrelated changes were preserved. No UI
trading button or live orchestration hook was added.

## Actual safe test results

**628 selected offline tests passed: 125 governance, 82 trading-control/adapter,
249 prior journal/research/review, and 172 mission/Navigator/ModelDock
regressions.** Tests use synthetic inputs, retained local history, fake process
launches and broker clients, and mocked native imports. No real native
Galactica import or Alpaca runtime was exercised.

Exact commands run from the checkout:

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests .venv/bin/python3.11 -m unittest \
  test_investment_governance_contracts test_investment_governance_engine \
  test_investment_approval test_investment_governance_store \
  test_investment_governance_examples test_investment_governance_cli -q
# 125 passed, 62.794 seconds

PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests .venv/bin/python3.11 -m unittest \
  test_auto_trading_runtime test_galactica_trading_adapter test_trading_automation -q
# 82 passed, 0.618 seconds (final rerun)

PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests .venv/bin/python3.11 -m unittest \
  test_decision_journal_contracts test_decision_journal_projection \
  test_decision_journal_store test_decision_journal_cli \
  test_investment_hypothesis_contracts test_investment_hypothesis_sources \
  test_investment_hypothesis_store test_investment_hypothesis_examples \
  test_investment_hypothesis_cli test_investment_review_contracts \
  test_investment_review_engine test_investment_review_store \
  test_investment_review_cli -q
# 249 passed, 11.798 seconds

PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests .venv/bin/python3.11 -m unittest \
  test_contracts test_mission_store test_mission_transitions \
  test_mission_presentation test_cli_help test_navigator_adapter \
  test_operator_adapter test_modeldock_config test_modeldock_client \
  test_modeldock_preflight test_modeldock_delivery -q
# 172 passed, 1.157 seconds

git diff --check
# passed
```

Governance CLI tests were also rerun after the journal intent reason wording
was clarified; these are repeat coverage, not additional unique tests.
Initial failing test runs exposed interface/lifecycle issues during development;
they were repaired before these final passing runs.

Tests cover strict fields, confidence/authority non-escalation, exact source
and hash binding, caps and unknown inputs, unchanged trading desk budgets,
known dissent/invalidation, final/interim scope, separation and freshness,
revocation/expiry/supersession, idempotency, concurrency, semantic tampering,
backup restoration and publication recovery. Runtime tests cover pre/post
publication interruption, retained source snapshots, failed/lost startup,
same-account locks across roots, OFF/admission serialization, pending and
ambiguous orders, investment isolation, reductions, dependency checks and the
actual worker-to-adapter calling path with mocked native classes/imports.

## Runnable smoke results

All commands in the [governance example](INVESTMENT_GOVERNANCE.md#runnable-synthetic-example)
were run against `output/investment-governance-example`:

- Both verified synthetic MissionStore histories exported successfully.
- Hypothesis/challenge/proposal persisted; gate `REVIEW_READY`.
- Approval persisted as `SIMULATED_SHADOW_APPROVED`; no operational authority.
- Inactive initial 50/50 capital proposal persisted; activation stays disabled.
- Verification: **9 events, 18 evidence blobs, zero orphans**.
- Exact last-entry hash matched the committed expected fixture:
  `ae2378887ef57fb82e14560f95de45e878f3d37db8f2cc136b99b852affb3729`.
- Excessive-target preview rejected; incomplete-context preview deferred.
- Repeating both exports and all five recording commands wrote nothing;
  two original revisions per export stayed unchanged.

The [offline auto-trading commands](AUTO_TRADING.md#runnable-offline-commands)
were run: native source manifest inspection, runtime status, simulated OFF
journal recording and journal status. Actual runtime status is **OFF**,
`worker_active=false`, `entries_enabled=false`, `auto_restart_enabled=false`.
The OFF journal is `output/auto-trading-intent-example`; it grants no broker
permission. No `enable` command was run.

## Real history versus fixtures

Read-only verification was rerun with exact commands:

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python3.11 \
  -m blackpod_build_week.harbormaster journal verify \
  --journal-root output/decision-journal-archive-check
# 20 events, 122 evidence blobs

PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python3.11 \
  -m blackpod_build_week.harbormaster journal verify \
  --journal-root output/investment-hypothesis-history-check
# 22 events, 124 evidence blobs

PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python3.11 \
  -m blackpod_build_week.harbormaster journal verify \
  --journal-root output/investment-review-history-check
# 26 events, 128 evidence blobs
```

All have zero orphan evidence/staging files. Their previous final hashes
remain respectively `30b24cd1ae99ddc3dbd9649fbc79ae2fbe92c6e7bbf5a4f38e15ad2ce9051ba6`,
`64525c583671e9ad13a6246254e14d73341acd0a64e2d8a971c2bfc6ec6ffb3d`, and
`d3f752bdcd7bffb87fb0c8b0cda38eae045bf6863f69de96f78e52b02d1a1142`.

The base archive contains 7 existing LIVE and 13 REPLAY mission revisions.
The later retrospective research/challenges are explicitly supplied shadow
annotations, not historical economic truth. This burst added no positive
investment approval, invented portfolio context, capital authorization or
realized P&L to those histories. They lack sufficient authoritative current
account/risk evidence for that. Positive governance and execution-admission
coverage is synthetic; real coverage verifies import/replay compatibility and
the actual read-only native interface/source closure.

## Remaining limits and recommended next burst

Investment context, units, statistical/fundamental roles, economic independence,
identities and capital approvals remain supplied claims. Positive approval is
SHADOW research only; no automatic policy improvement or allocation follows.
Final evaluation belongs to an ended hypothesis; approving new prospective
research requires a new hypothesis rather than editing the original horizon.

Galactica's inspected import closure is implemented, but funded execution has
not been validated. The current interpreter lacks alpaca-py and has pandas
2.3.3 instead of the native pinned 2.3.1. No dependency was installed, no
compatible external interpreter/account profile was operationally verified,
and no paper/live account was selected for activation. Credentials files were
not opened. Runtime limits are declared; buffered market-order admission does
not guarantee fill-price caps. External executors and multiple hosts/users are
outside local locks. Software exits need a healthy worker/stream. Large-ledger
replay cost, signed identity, durable desk ownership and reconciliation remain
open. Runtime receipts do not yet populate the Decision Journal automatically.

**Recommended next burst: broker-confirmed paper execution reconciliation and
desk ownership verification.** Add deterministic fill/partial-fill/cancel/
replacement reconciliation, durable ownership and restart recovery, and linked
journal execution/outcome events. Gate acceptance on complete broker order/fill
identity preservation, no duplicate resubmission, verified desk scope and caps,
OFF/draining recovery and P&L derived only from confirmed fills. Select the
paper account and compatible existing runtime explicitly before any paper
operational trial. Funded activation and investment allocation remain separate
decisions. This next burst was not implemented.
