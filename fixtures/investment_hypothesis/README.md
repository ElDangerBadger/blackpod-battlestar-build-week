# Synthetic investment hypothesis source

This is a canonical, two-revision REPLAY mission fixture. It was created with
`MissionStore.initialize`, followed by `write_immutable_artifact` for
`research/synthetic_observations.json` and `commit_snapshot` for revision 2.
No stages, providers, agents, inference, or execution were run.

The artifact supplies invented revenue-growth and financing-cost observations
for exact JSON-pointer/value/time binding tests. It is marked
`SYNTHETIC_FIXTURE`. The two values share one source and do not establish
independent fundamental/statistical corroboration. The accompanying
`examples/investment_hypothesis.shadow.v1.json` is illustrative research only,
not a market recommendation or an authorization.

Mission: `mission-investment-hypothesis-example`.
Request: `request-investment-hypothesis-example`.
Source time: `2026-10-11T00:00:00Z`.

The example binds the deterministic journal event for revision 2 and the exact
committed artifact hash. It cannot be validated against an unrelated journal
or an altered source file. `tests/test_investment_hypothesis_examples.py`
reconstructs the fixture through the public MissionStore interfaces and checks
identical request, snapshots, current projection, and artifact bytes.

See `docs/INVESTMENT_HYPOTHESES.md` for runnable offline export, validate, record,
show, and verify commands.
