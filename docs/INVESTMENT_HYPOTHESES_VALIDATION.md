# Burst 2 validation record

Implemented the approved next burst: structured investment hypotheses in shadow
mode, grounded in retained journal observations, with dated expectations,
alternatives, invalidation conditions and fixed review plans. This is an explicit
offline authoring/recording foundation, not an investment authorizer or inference
workflow. Burst 3 was not implemented.

## Files changed for this burst

- New `src/blackpod_build_week/contracts/investment_hypothesis.py`: strict
  immutable `blackpod.investment_hypothesis.v1` draft contract.
- Updated `src/blackpod_build_week/contracts/decision_journal.py`: additive
  hypothesis-only journal event v2; v1 meanings and bytes stay unchanged.
- New `src/blackpod_build_week/investment_hypothesis.py`: pure source pointer,
  scalar, hash, timestamp/cutoff checks and deterministic event preparation.
- Updated `src/blackpod_build_week/decision_journal_store.py`: source validation
  during locked append and verification; coherent read-only retained-content API;
  clean rejection of excessively nested corrupt entries.
- Updated `src/blackpod_build_week/decision_journal_cli.py`: read-only validation,
  explicit recording, verified display, immutable-ID conflict preview.
- New tests: `tests/test_investment_hypothesis_contracts.py`,
  `tests/test_investment_hypothesis_sources.py`,
  `tests/test_investment_hypothesis_store.py`,
  `tests/test_investment_hypothesis_cli.py`,
  `tests/test_investment_hypothesis_examples.py`.
- New `examples/investment_hypothesis.shadow.v1.json` and synthetic source fixture
  beneath `fixtures/investment_hypothesis/` (README, request, two immutable
  revisions, current pointer, declared synthetic JSON observations).
- Documentation: `README.md`, `docs/ARCHITECTURE.md`, `docs/DECISION_JOURNAL.md`,
  `docs/INVESTMENT_HYPOTHESES.md`, this validation report.
- `.gitignore`: generated investment-hypothesis test journals/inputs.

Earlier Burst 1 work and unrelated ModelDock changes were preserved. No
canonical mission schema, stage workflow, decision policy, model configuration,
Navigator behavior, dependency, database or execution integration was changed.

## Actual offline test results

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python3.11 \
  -m unittest discover -s tests -p 'test_investment_hypothesis*.py' -q
```

**62 new tests passed**, no failures/errors/skips (0.650 seconds). Breakdown:
20 contract, 11 source-binding, 17 storage, 10 CLI and 4 example tests.

Coverage includes strict nested/version/type checks, prospective/retrospective
dates, complete fixed plans, disabled authority, exact source IDs/hashes/scalars,
JSON pointer escaping and array ambiguity, timestamps/cutoffs, boolean versus
number distinctions, malformed/deep JSON, source/evidence tampering, v1/v2 mixed
chains, read-only commands, conflicts, retries, source growth, interruption
recovery, source-storage protection and legacy evaluation/P&L isolation.

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python3.11 \
  -m unittest discover -s tests -p 'test_decision_journal*.py' -q
```

**91 Burst 1 journal regression tests passed**, no failures/errors/skips
(1.054 seconds).

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests .venv/bin/python3.11 \
  -m unittest test_contracts test_mission_store test_mission_transitions \
  test_mission_presentation test_cli_help test_navigator_adapter \
  test_operator_adapter test_modeldock_config test_modeldock_client \
  test_modeldock_preflight test_modeldock_delivery -q
```

**172 existing offline regression tests passed**, no failures/errors/skips
(1.122 seconds). ModelDock tests use test transports; no actual inference was
started. Total across the three runs: **325 passed**. `git diff --check` passed.
Full repository, UI/browser and deployment suites were not run.

## Runnable example and command verification

The exact complete example, including initial mission export, is in
[Investment Hypotheses](INVESTMENT_HYPOTHESES.md). These commands were executed
successfully with exit code 0:

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python3.11 \
  -m blackpod_build_week.harbormaster journal validate-hypothesis \
  --journal-root output/investment-hypothesis-example \
  --hypothesis examples/investment_hypothesis.shadow.v1.json

PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python3.11 \
  -m blackpod_build_week.harbormaster journal record-hypothesis \
  --journal-root output/investment-hypothesis-example \
  --hypothesis examples/investment_hypothesis.shadow.v1.json

PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python3.11 \
  -m blackpod_build_week.harbormaster journal show-hypothesis \
  --journal-root output/investment-hypothesis-example \
  --hypothesis-id synthetic-financing-hypothesis-001

PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python3.11 \
  -m blackpod_build_week.harbormaster journal verify \
  --journal-root output/investment-hypothesis-example
```

The example is explicitly synthetic. Two v1 mission events remain `UNCLASSIFIED`
with historical hypotheses `NOT_RECORDED`; a separate v2 event records the
`INVESTMENT`/`SHADOW_DRAFT` research. Verification: **3 events, 5 retained evidence
blobs, no orphans**. Recording an identical draft again returns `written=false`.
Validation/display do not modify journal bytes or timestamps. All authority
flags are false, and `economic_truth_evaluated=false` is explicit.

## Archived source-binding smoke

Copied the previously verified 20-event archive journal into
`output/investment-hypothesis-history-check`, retaining the exact original entry
bytes. Two newly supplied test drafts were explicitly labeled `RETROSPECTIVE`,
authored at `2026-10-11T00:00:00Z` by `offline-verification`:

| Source | Retained observation | Original authority/status preserved |
| --- | --- | --- |
| September 18 LIVE mission, 7 revisions | Exact `/key_measurements/breadth_score`, source `/as_of`, Oracle report hash and final source event | `UNCLASSIFIED`; Governor `BLOCKED`; `NOT_EXECUTED` |
| Approved REPLAY mission, 13 revisions | Same exact-pointer binding to that mission's recorded Oracle report | `UNCLASSIFIED`; Governor `PROCEED`; `SHADOW_ONLY` |

The supplied input files remain in
`output/investment-hypothesis-history-inputs/live.json` and `replay.json`.
Validation and recording were exercised for both, followed by identical retries
that returned `written=false`. No source mission or earlier journal entry was
changed. The original **20 v1 entry bytes** matched before and after.

Final mixed journal: **22 events, 124 evidence blobs, no orphans**, final entry
hash `64525c583671e9ad13a6246254e14d73341acd0a64e2d8a971c2bfc6ec6ffb3d`.
Verification is reproducible with:

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python3.11 \
  -m blackpod_build_week.harbormaster journal verify \
  --journal-root output/investment-hypothesis-history-check
```

These are provenance checks over archived source evidence, not historical
investment predictions or performance tests. No historical hypothesis was
reconstructed or presented as precommitted. There was no provider acquisition,
inference, broker operation, capital movement or live workflow invocation.

## Remaining limitations and next burst

Source bindings verify retained facts and supplied timestamp consistency, not
economic causality, independence, correct unit interpretation, release-time
availability, authenticated authorship or true precommitment. Draft units and
metric descriptions are supplied annotations. Only retained mission JSON
artifacts are supported; no macro/filing provider integration is added.

The fixed evaluation plan is stored, not executed. Automatic origination,
adversarial challenge, independent evidence scoring, outcome acquisition and
hypothesis evaluation remain absent. Existing mission evaluation commands cannot
assign a trade outcome or authority to a hypothesis. The capital policy remains
inactive. Local POSIX/64 MiB/trusted-backup guarantees from Burst 1 still apply.

Recommended next burst: independent structured hypothesis challenge and linked,
source-bound outcome evaluation with agreed measurement/independence rules.
Keep authorization, execution, policy mutation and capital activation disabled.
That next burst was not implemented.
