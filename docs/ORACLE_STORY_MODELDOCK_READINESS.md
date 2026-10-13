# Oracle story rerun — native telemetry handoff

## Latest status — combined deployment verified and rerun completed

The deployment blocker below is resolved. The restarted app built at
`2026-09-19T20:26:30Z` contains schema-constrained output and native telemetry.
One authorized unchanged frozen-evidence generation completed with **946 native
tokens**, native **stop**, and schema acknowledgement. Canonical narrative
validation still **failed**: the draft is byte-identical to the earlier rejected
draft, repeating the same section six times. No candidate was published.

See [the rerun review](ORACLE_STORY_RERUN_REVIEW_20260919.md) for exact provenance,
validation, product assessment, and the remaining canonical contract work.
The former deployment handoff below is retained as history, not a request to
redeploy again. No automatic retry is authorized by this failed result.

## Earlier September 19, 2026 checkpoint

**Consumer compatibility implemented; generation and Cabin integration blocked
on the ModelDock deployment.** No new inference was attempted. The authorized
frozen-evidence generation remains unused; no second attempt was reserved.

Read-only verification found two separate ModelDock states:

- Clean source HEAD `1b3fe3e4987cd57fb2f70c8bdb0541244f3fb9ba` contains the native
  token-count/finish-reason correction. Its `docs/native-generation-telemetry.md`
  explicitly says schema-constrained output requires independent integration.
- The active port-8000 process (PID 82184, started September 19 at 07:35:06
  Pacific) uses `dist/ModelDock.app/Contents/Resources/runtime/bin/python3`.
  That app's build manifest reports commit
  `ad17d7f929471170eddda5d3da7f1d5599e94b3a`, built
  `2026-09-19T00:10:28Z`. Its packaged `providers/mlx.py` still counts
  `len(content.split())` and infers `completed_or_eos`; the new
  `providers/generation.py` is absent.
- Schema-constrained generation remains in that older package but not in the
  clean source HEAD. Source work is preserved in a ModelDock stash titled
  `Preserved structured-output work before native telemetry correction 2026-09-19`.
  We did not apply, remove, or modify the stash. Rebuilding HEAD alone is not
  sufficient: it would omit a required capability.

This is a deployment observation, not an inference about why the previous
candidate repeated itself. No ModelDock files, configuration, model routing,
processes, or weights were changed.

## Consumer behavior

Build Week's `ModelDockClient.generate_text` now requires, for new LIVE calls:

- `stop_reason == "stop"` and `stop_reason_source == "native"`;
- an integer `generated_token_count` between zero and the effective budget,
  with `generated_token_count_source == "native"`;
- the existing exact budget, correlation, provider, non-mock, JSON/content, and
  schema acknowledgement checks.

Battlestar's canonical `blackpod.oracle_story.runner` independently requires
the same native telemetry in the safe adapter projection. A native `stop` at
the exact token budget is not rejected just for reaching that budget. It is not
relabeled EOS or treated as proof of narrative completeness or quality.

`length`, `unknown`, unavailable/missing source fields, null/invalid counts,
and the former inferred `completed_or_eos` cannot pass the LIVE gate. Rejected
safe projections retain truthful unavailable/native metadata, without retaining
rejected prose or private model paths. Historical REPLAY remains compatible
with its original saved legacy telemetry; old evidence is not rewritten.

## Preservation

Both repositories started clean on
`update/2026-09-19-oracle-story-diagnostics`:

- Build Week: `69cb1bbc68d75964fd2c31a041cb3e6318aa08f7`.
- Battlestar: `4f045e56f0dfe28994d7fec6978068c2ff0767d1`.

The accepted legacy Oracle brief remains SHA-256
`b34acea75b349dc99a301df7399da0868b8255aef0dd98fa25cab4204293dc1d`.
The frozen temporal artifact remains SHA-256
`9f7795c7501a88c022a91ed3fac47925df31b7ca9b8079fb08d7cc619e74fc53`.
The manifest remains SHA-256
`36c670f79be9875b7fc2b216277951b02e0250bf9b192f04f750b003a1fa7c22`.

Frozen source admission and temporal recomputation passed again. The input
packet is byte-equivalent under canonical serialization to the previous attempt:
`oracle-story-input-88ae677c4189172ce31aaa86752f80fa1a0ef1ae8ffd62a79ff21835acd47125`
(43,600 bytes). Prompt, schema, evidence selection and semantic guards are
unchanged. The rejected `artifacts/oracle-story-review-20260919/attempt-001/`
remains intact. No new market data, publication, Cabin changes, fleet synthesis,
Sentry changes, trading permissions, or Governor/Navigator changes occurred.

## Offline verification

- Build Week focused transport/preflight/brief/enrichment tests: **120 passed**.
- Build Week full backend `tests/` suite: **801 passed**. The first sandbox run
  encountered 21 localhost fixture bind permission errors; the approved rerun
  passed using temporary local test servers, not the ModelDock service.
- Battlestar Oracle story and temporal suites: **213 passed, 14 subtests passed**.
- Both repositories pass `git diff --check`. Accepted brief, temporal artifact,
  manifest, and all eleven old-attempt files retain their pre-edit hashes.
- UI tests/build were not repeated: no UI files or presentation contracts changed.
  No end-to-end generation passed or was attempted at this checkpoint.

Compatibility edits remain uncommitted on the existing diagnostic branches.
No commits, pushes, merges, or live application restart occurred in this run.

## Earlier operator handoff — now completed

The ModelDock owner must integrate the preserved schema-constrained output work
with native telemetry, validate that combined implementation, and rebuild/restart
the appliance. Verify both capabilities in the deployed package, not merely Git
HEAD. Do not weaken schema acknowledgement or infer completion from prose.

After that verification, rerun the offline checks and regenerate code-bound gate
receipts before the single authorized frozen-evidence attempt. The old receipt
pins the old runner and must not be reused. Use a new immutable attempt directory;
never overwrite or rerun `attempt-001`. Do not automatically retry a failure.
Only a new candidate that passes canonical validation and separate narrative/
entailment review can unblock Build Week presentation integration. ModelDock
continues to choose the model; returned model identity is audit metadata only.
