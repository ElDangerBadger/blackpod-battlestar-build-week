# Burst 1 implementation and validation

Implemented in the current checkout on October 11, 2026. No separate attached
brief was accessible; the supplied implementation message defined the acceptance
scope. The next burst was not implemented.

## Files changed

- New source: `src/blackpod_build_week/contracts/decision_journal.py`,
  `src/blackpod_build_week/decision_journal_projection.py`,
  `src/blackpod_build_week/decision_journal_store.py`,
  `src/blackpod_build_week/decision_journal_cli.py`.
- CLI integration only: `src/blackpod_build_week/harbormaster.py`.
- New tests: `tests/test_decision_journal_contracts.py`,
  `tests/test_decision_journal_projection.py`,
  `tests/test_decision_journal_store.py`, `tests/test_decision_journal_cli.py`.
- Existing test update: `tests/test_cli_help.py`.
- Policy example: `examples/capital_policy.proposed.v1.json`.
- Canonical initialized REPLAY fixture beneath
  `fixtures/decision_journal/missions/mission-journal-example/`:
  `request/mission_request.json`, `snapshots/mission_snapshot-r0001.json`,
  `mission_snapshot.json`.
- Documentation: `README.md`, `docs/ARCHITECTURE.md`,
  `docs/DECISION_JOURNAL.md`, `docs/DECISION_JOURNAL_VALIDATION.md`.
- `.gitignore`: generated example/archive-check journals and evaluation input.

Existing ModelDock source changes, tests and untracked documentation were left
untouched. Canonical mission schemas, decision policies, stage workflows,
Navigator behavior, ModelDock configuration and dependencies were not changed.

## Tests actually executed

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python3.11 \
  -m unittest discover -s tests -p 'test_decision_journal*.py' -q
```

**91 tests passed**, no failures/errors/skips; final run 0.929 seconds.
Breakdown: 24 contract, 16 projection, 33 storage, 18 CLI tests. Synthetic
canonical histories cover incomplete, held, vetoed, failed, approved-for-handoff,
and approved-with-SHADOW-plan states. Coverage includes concurrent writers,
pre/post-publication interruptions, file/directory fsync failure, staging recovery,
tampering, no-lookahead evaluation, read/write bounds, source-root protection,
links, and evaluation retry after source growth.

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests .venv/bin/python3.11 \
  -m unittest test_contracts test_mission_store test_mission_transitions \
  test_mission_presentation test_cli_help test_navigator_adapter \
  test_operator_adapter test_modeldock_config test_modeldock_client \
  test_modeldock_preflight test_modeldock_delivery -v
```

**172 existing offline regression tests passed**, no failures/errors/skips;
1.018 seconds. ModelDock checks use injected/mocked test transports; no actual
service or inference was run. No provider, broker or live orchestration command
was invoked. `git diff --check` passed. The full repository suite, UI/browser
checks and deployment tests were not run.

## Four commands exercised

All commands succeeded with exit 0. Evaluation input was prepared by the Python
snippet in [the usage documentation](DECISION_JOURNAL.md).

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python3.11 \
  -m blackpod_build_week.harbormaster journal export-mission \
  --mission-root fixtures/decision_journal/missions/mission-journal-example \
  --journal-root output/decision-journal-example

PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python3.11 \
  -m blackpod_build_week.harbormaster journal propose-capital-policy \
  --journal-root output/decision-journal-example \
  --proposal examples/capital_policy.proposed.v1.json

PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python3.11 \
  -m blackpod_build_week.harbormaster journal append-evaluation \
  --journal-root output/decision-journal-example \
  --evaluation output/decision-journal-evaluation.json

PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python3.11 \
  -m blackpod_build_week.harbormaster journal verify \
  --journal-root output/decision-journal-example
```

Final fixture journal: **3 events, 4 evidence blobs, no orphans**. Policy remained
`PROPOSED`, with activation disabled. Repeated policy/evaluation commands returned
`written=false`. Source fixture was not modified by export.

## Archived history coverage

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python3.11 \
  -m blackpod_build_week.harbormaster journal export-mission \
  --mission-root artifacts/live-analysis-20260918-001/missions/mission-live-aapl-20260918-001 \
  --journal-root output/decision-journal-archive-check

PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python3.11 \
  -m blackpod_build_week.harbormaster journal export-mission \
  --mission-root artifacts/demo-readiness/judge/approved/missions/mission-buildweek-replay-001 \
  --journal-root output/decision-journal-archive-check

PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python3.11 \
  -m blackpod_build_week.harbormaster journal verify \
  --journal-root output/decision-journal-archive-check
```

| Recorded source | Revisions | Retained source files | Final semantics |
| --- | ---: | ---: | --- |
| LIVE September 18 AAPL-correlated mission | 7 | 48 | `HELD`, Governor `BLOCKED`, `NOT_EXECUTED` |
| Approved REPLAY mission | 13 | 75 | `APPROVED`, Governor `PROCEED`, `SHADOW_ONLY` |

Combined journal: **20 events, 122 unique evidence blobs, no orphans**. The 123
source files share one identical blob. Final entry hash:
`30b24cd1ae99ddc3dbd9649fbc79ae2fbe92c6e7bbf5a4f38e15ad2ce9051ba6`.

Both exports were repeated: 0 writes, 7 and 13 unchanged events. Afterwards,
every captured source file still exactly matched its retained evidence bytes.
A complete copy restored to a fresh temporary directory independently verified
with the same event count, evidence count and final hash. CLI tests also verify
a journal after moving its source tree away.

The archived checks are offline source verification/export, not current-provider,
inference, trading or investment-performance tests. No missing historical
hypothesis, horizon, probability, expectation, evaluation or realized P&L was
invented.

## Remaining limits and next burst

- Local POSIX filesystem assumptions; Windows/network filesystems are unverified.
  Source/blob/event/entry files are bounded to 64 MiB. Verification scans complete
  history/evidence and can fail conservatively during concurrent mutation.
- Hash assurance depends on a trusted root. Authentication, signatures, external
  checkpoints, backup automation and retention enforcement are absent. Corrupt
  committed history is not automatically repaired.
- Evaluations are supplied observations/conclusions. Their structure, linkage and
  non-execution semantics are checked; economic truth and investment performance
  are not adjudicated.
- Capital policy is an inactive proposal. No account equity calculation, active
  budgets, transfers, allocation authority or perpetual rebalancing exists.
- No live hooks, order/fill reconciliation, portfolio accounting or hypothesis
  generation were added.

Recommended next burst: structured investment hypotheses in shadow mode, with
point-in-time evidence, expected observations, horizon, alternatives, invalidation
conditions and fixed evaluation plans. Keep authorization and capital activation
disabled. This next burst was not implemented.
