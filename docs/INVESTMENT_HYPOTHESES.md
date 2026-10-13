# Shadow investment hypotheses

Burst 2 adds explicit, source-bound investment hypothesis drafts to the passive
Decision Journal. The commands read retained journal evidence and append an
immutable draft. They do not run Oracle, Council, Senate, providers, inference,
Navigator, allocation, or trading. The original mission is not modified and the
journal is not connected to live orchestration.

[Validation record](INVESTMENT_HYPOTHESES_VALIDATION.md) lists changed files,
executed commands, actual tests and archived source-binding coverage.

BlackPod retains separate `TRADING` and `INVESTMENT` desks. A new shadow draft
belongs to `INVESTMENT`; linking its evidence to an `UNCLASSIFIED` historical
mission does not relabel that mission or grant it investment authority.
`CAPITAL_ALLOCATION` remains separate oversight. The initial 50/50 proposal is
unchanged and inactive, with no perpetual 50/50 rebalance rule.

## Drafts and evidence

A draft is an explicit human-supplied research proposition. It includes an
economic observation, a causal hypothesis, source-bound evidence, expected
observations, a horizon, competing interpretations, invalidation conditions, and
a fixed evaluation plan. There is no autonomous or LLM-generated hypothesis
originator in this burst. Passing validation establishes contract and source
integrity; it does not establish economic truth, statistical significance, or
independent corroboration.

Each observation binds a journal mission event, a declared artifact path and
SHA-256 digest, an exact JSON scalar pointer/value, an exact timestamp pointer,
and a timestamp role. Units and metric interpretations are author-supplied
annotations; they are not independently checked against source metadata.
The selected mission event must already be in the
verified journal. Validation uses retained evidence, so an exported source
mission can later become unavailable without breaking the draft's provenance.
Only JSON artifacts retained from imported missions are supported; this burst
does not ingest additional data sources.

`PROSPECTIVE` records the draft at its evidence cutoff. `RETROSPECTIVE` explicitly
labels a draft recorded after its cutoff. Neither can cite observations or
source events after that cutoff. A retrospective draft cannot be presented as a
precommitted prediction. Availability-time quality must be assessed by the
researcher: source integrity alone does not prove that data was available to
market participants at a particular moment. Both the draft's dates and the
local source timestamps are supplied data; this local journal does not provide
authenticated author identity or independently attest actual precommitment time.

The expected outcomes and evaluation plan are fixed when the draft is recorded.
They are not realized outcomes or probabilities of success. Alternatives and
invalidation conditions make the proposed reasoning inspectable. Burst 3 adds
explicit supplied challenges and deadline-point comparisons, while economic
adjudication remains manual. Observations from the same artifact are not
independent evidence merely because they occupy separate pointers.

## Authority and immutable history

The new draft and journal event are strictly versioned. The journal accepts the
new additive event version alongside existing v1 mission, evaluation, and capital
proposal records. Exporting a mission still emits its original v1 semantics;
missing historical hypotheses, horizons, expectations, probabilities, and
evaluations remain `NOT_RECORDED`.

A shadow draft has no execution, trading, investment-allocation, policy-change,
or capital-transfer authority. It cannot create an executable order. An approved
Navigator SHADOW handoff remains approval for SHADOW planning only. Forecasts,
recommendations, authorizations, and orders remain distinct concepts.

The hypothesis ID is supplied once and deterministically binds the new decision
and event IDs. Recording identical bytes again is a no-op. Reusing the same
hypothesis ID with changed content is a conflict. The journal retains the
canonical draft and its referenced original evidence, with normal chain/hash
verification, safe publication, and interruption recovery. Subsequent evaluation
appends a linked record through the [Burst 3 review workflow](INVESTMENT_REVIEW.md);
it never rewrites this draft or its fixed evaluation plan. Deadline comparisons
remain subject to manual review and never assign realized trade P&L to a
non-executed draft.

## Runnable offline example

Run from this checkout with the existing environment. The committed source is a
two-revision REPLAY mission fixture, initialized without running any stage. Its
only research artifact is explicitly synthetic: illustrative revenue growth of
5% and financing cost of 6%. Those values and the associated economic idea test
mechanics; they are not actual company observations, a market recommendation,
independent fundamental/statistical proof, or a validated forecast.

```sh
export PYTHONDONTWRITEBYTECODE=1
export PYTHONPATH=src

.venv/bin/python3.11 -m blackpod_build_week.harbormaster journal export-mission \
  --mission-root fixtures/investment_hypothesis/missions/mission-investment-hypothesis-example \
  --journal-root output/investment-hypothesis-example

.venv/bin/python3.11 -m blackpod_build_week.harbormaster journal validate-hypothesis \
  --journal-root output/investment-hypothesis-example \
  --hypothesis examples/investment_hypothesis.shadow.v1.json

.venv/bin/python3.11 -m blackpod_build_week.harbormaster journal record-hypothesis \
  --journal-root output/investment-hypothesis-example \
  --hypothesis examples/investment_hypothesis.shadow.v1.json

.venv/bin/python3.11 -m blackpod_build_week.harbormaster journal show-hypothesis \
  --journal-root output/investment-hypothesis-example \
  --hypothesis-id synthetic-financing-hypothesis-001

.venv/bin/python3.11 -m blackpod_build_week.harbormaster journal verify \
  --journal-root output/investment-hypothesis-example
```

`validate-hypothesis` and `show-hypothesis` are read-only. Recording is an explicit
append; it does not activate a policy or evaluate an investment. These commands
are also available through
`python -m blackpod_build_week.decision_journal_cli <command> ...`.
Success returns JSON and exit code 0; invalid input, unsupported evidence,
conflicts, or integrity failures return exit code 2.

## Offline checks and limits

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python3.11 \
  -m unittest discover -s tests -p 'test_investment_hypothesis*.py' -v
```

The committed fixture tests verify deterministic source identities, actual
artifact hashes and pointers, command behavior, read-only validation/showing,
append-only recording, idempotent retries, and preservation of v1 source records.
They deny network and producer subprocess calls. The fixture is synthetic
coverage, not real-history economic validation or prospective performance.

The local journal's existing POSIX, bounded-file, and trusted-backup limitations
still apply. Human identity is supplied rather than authenticated. No automatic
hypothesis generation, portfolio construction, valuation, outcome acquisition,
economic truth adjudication, policy improvement or allocation authority is
introduced. Explicit challenge and fixed-deadline comparisons are now available
in [Burst 3](INVESTMENT_REVIEW.md).
