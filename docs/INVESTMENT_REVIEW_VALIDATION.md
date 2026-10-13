# Burst 3 implementation and validation

Implemented the approved independent-challenge and linked-outcome burst in the
current checkout. Work is offline and SHADOW-only. Next-burst governance and
approval authority were not implemented.

## Files changed for this burst

- New `src/blackpod_build_week/contracts/investment_review.py`: immutable
  challenge/evaluation inputs and strict conservative computed-report contracts.
- Updated `src/blackpod_build_week/contracts/decision_journal.py`: additive v3
  dispatch and clean bounded parse errors; valid v1/v2 bytes unchanged.
- New `src/blackpod_build_week/investment_review.py`: source relationships,
  declared-reviewer separation, fixed-deadline comparisons and linked corrections.
- Updated `src/blackpod_build_week/investment_hypothesis.py`: shared source-binding
  interface, retaining the previous hypothesis validation behavior.
- Updated `src/blackpod_build_week/decision_journal_store.py`: review recomputation
  under append lock and during verification; persistence format unchanged.
- Updated `src/blackpod_build_week/decision_journal_cli.py` and Harbormaster help:
  six explicit offline review commands, conflict preview and scoped queries.
- New tests: `tests/test_investment_review_contracts.py`,
  `tests/test_investment_review_engine.py`, `tests/test_investment_review_store.py`,
  `tests/test_investment_review_cli.py`.
- New examples: `examples/investment_challenge.shadow.v1.json` and
  `examples/investment_outcome_evaluation.{final,missing,interim,invalidation}.v1.json`.
- New fixtures: `fixtures/investment_review/README.md`, two canonical initialized
  REPLAY mission trees with immutable revisions and synthetic JSON source artifacts.
- Documentation: `README.md`, `docs/ARCHITECTURE.md`, `docs/DECISION_JOURNAL.md`,
  `docs/INVESTMENT_HYPOTHESES.md`, `docs/INVESTMENT_REVIEW.md`, this report.
- `.gitignore`: generated investment-review journals and supplied smoke inputs.

Previous bursts and unrelated ModelDock edits were preserved. No canonical
mission schema, stage workflow, live decision policy, model configuration,
Navigator behavior, dependency, migration, broker or capital integration changed.

## Actual offline test results

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python3.11 \
  -m unittest discover -s tests -p 'test_investment_review*.py' -q
```

**96 tests passed**, 0 failures/errors/skips (9.369 seconds): 26 contract,
29 engine, 25 storage and 16 CLI tests.

Coverage includes every comparison operator; exact source values, hashes,
timestamps, roles, metric/unit labels and deadlines; missing/interim/early-final
cases; boolean/type guards; shared/copied artifacts; method versions; original
plans and dissent; corrections without cutoff retreat/final downgrade; unknown
or cross-hypothesis links; idempotency/conflicts; recomputation/tampering;
concurrency; interrupted publications; root/link protection; and read-only CLI
behavior. Native MissionStore synthetic source histories exercise actual storage
interfaces, not mocks of the journal persistence protocol.

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python3.11 \
  -m unittest discover -s tests -p 'test_investment_hypothesis*.py' -q

PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python3.11 \
  -m unittest discover -s tests -p 'test_decision_journal*.py' -q

PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests .venv/bin/python3.11 \
  -m unittest test_contracts test_mission_store test_mission_transitions \
  test_mission_presentation test_cli_help test_navigator_adapter \
  test_operator_adapter test_modeldock_config test_modeldock_client \
  test_modeldock_preflight test_modeldock_delivery -q
```

Results: **62 hypothesis**, **91 journal**, and **172 existing offline regression
tests passed** (0.819, 1.155 and 1.199 seconds). Total across all selected runs:
**421 passed**, no failures/errors/skips. ModelDock regression tests use test
transports; no inference was started. CLI tests deny network and producer calls.
`git diff --check` passed. Full repository, UI/browser and deployment suites were
not run.

## Actual CLI and fixture coverage

All six new commands were exercised successfully; the complete runnable export/
record/review sequence is in [Investment Review](INVESTMENT_REVIEW.md). Exact new
command examples executed against the fixture journal:

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python3.11 \
  -m blackpod_build_week.harbormaster journal validate-challenge \
  --journal-root output/investment-review-example \
  --challenge examples/investment_challenge.shadow.v1.json

PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python3.11 \
  -m blackpod_build_week.harbormaster journal record-challenge \
  --journal-root output/investment-review-example \
  --challenge examples/investment_challenge.shadow.v1.json

PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python3.11 \
  -m blackpod_build_week.harbormaster journal show-challenge \
  --journal-root output/investment-review-example \
  --challenge-id synthetic-financing-challenge-001

PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python3.11 \
  -m blackpod_build_week.harbormaster journal evaluate-hypothesis \
  --journal-root output/investment-review-example \
  --evaluation examples/investment_outcome_evaluation.final.v1.json

PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python3.11 \
  -m blackpod_build_week.harbormaster journal record-hypothesis-evaluation \
  --journal-root output/investment-review-example \
  --evaluation examples/investment_outcome_evaluation.final.v1.json

PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python3.11 \
  -m blackpod_build_week.harbormaster journal show-hypothesis-evaluation \
  --journal-root output/investment-review-example \
  --evaluation-id synthetic-financing-final-001
```

Synthetic final comparison: outcome `MET`, invalidation `NOT_TRIGGERED`, summary
`ALL_EXPECTATIONS_MET_NO_DEADLINE_INVALIDATION`. Other supplied fixture previews:
missing data `INCONCLUSIVE`, early/interim `PENDING`, invalidation case
`INVALIDATION_TRIGGERED`. All keep manual review required, economic truth and
whole-horizon invalidation unestablished, execution `NOT_EXECUTED`, trade P&L
null and authority disabled. Future-dated synthetic observations are not actual
investment outcomes or performance claims.

Final fixture journal: **9 events, 16 evidence blobs, no orphans**; final hash
`71de0ca046f40787c83aca98d0797596ce727de7c47c3207c40e7ac26ef3e9ac`.
Identical record retries returned `written=false`. Tests verify journal/source
bytes and timestamps stay unchanged during previews/queries, and the original
hypothesis/plan stays byte-identical after reviews.

## Archived LIVE/REPLAY evidence coverage

Copied the prior verified 22-entry archived-source/hypothesis journal into
`output/investment-review-history-check`. The original LIVE source has 7 mission
revisions; approved REPLAY has 13. The two Burst 2 hypotheses remain explicitly
retrospective. New declared reviewers challenged their descriptive Oracle-only
evidence and recorded interim evaluations without supplied future measurements.

For both hypotheses:

- The original source point was recognized as the same value binding.
- `FUNDAMENTAL` and `STATISTICAL` evidence roles remained missing.
- Independence/authentication/economic truth were not claimed.
- Future-deadline checks remained `PENDING`, with null trade P&L.
- Identical outcome retries wrote nothing.

All **22 prior entry bytes** were unchanged in both the original and copied
journals. New challenge/interim inputs are retained under
`output/investment-review-history-inputs/` for inspection. Final mixed journal:
**26 events, 128 evidence blobs, no orphans**, hash
`d3f752bdcd7bffb87fb0c8b0cda38eae045bf6863f69de96f78e52b02d1a1142`.

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python3.11 \
  -m blackpod_build_week.harbormaster journal verify \
  --journal-root output/investment-review-history-check
```

This verifies archived-source provenance and honest pending status, not current
market acquisition, mature investment performance, or genuine precommitment.
No historical outcomes were invented, and no provider, broker, inference,
capital operation or live orchestration was invoked.

## Remaining limits and next burst

Declared reviewer separation is not identity authentication. Source roles/groups,
units, metric meaning and time availability remain supplied claims; retained
pointer consistency is not independent economic validation. Distinct artifacts
never prove independent datasets. Only imported mission JSON is supported.
Deadline checks do not establish interval coverage or causal correctness.
Original source timestamps do not independently attest publication availability
or authenticated precommitment. Local POSIX/64 MiB/trusted-root limitations remain.

The workflow records research and comparisons, not authorized investments. The
capital policy is still `PROPOSED`; all activation, transfer, execution and policy
modification remain disabled. No result automatically rewrites a thesis or live
decision rule.

Recommended next burst: a governed investment decision proposal interface with
deterministic risk-policy checks and explicit human approval tied to exact
evidence and policy versions. Keep execution and capital activation disabled
until separately authorized and validated. That burst was not implemented.
