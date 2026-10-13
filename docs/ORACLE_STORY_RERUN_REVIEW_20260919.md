# Oracle story rerun review — September 19, 2026

## Outcome

**ModelDock deployment/telemetry fixed; narrative acceptance still FAIL.**
One authorized generation used the exact previous frozen request. There was
no retry, content repair, prompt change, new market collection, or publication.
The existing accepted mission brief remains unchanged. Build Week presentation
integration is blocked on an acceptable canonical Oracle story, not on telemetry.

## Deployment and offline gates

The active ModelDock process was PID 30623, started September 19 at 13:30:15
Pacific, running the packaged app. Its manifest reports build
`2026-09-19T20:26:30Z`, version/build `1.0.0 / 1`, commit
`1b3fe3e4987cd57fb2f70c8bdb0541244f3fb9ba`.

Read-only inspection verified native terminal telemetry extraction, schema
constrained decoding, post-generation JSON/schema validation, and preservation
of both telemetry and schema acknowledgement in the API envelope. The packaged
validator accepted the saved request unchanged. No model selection was sent.

The combined package contains structured-output additions not represented by
the clean source commit alone. The gate therefore pins nine packaged files,
including the build/dependency manifests, generation/structured providers,
router, schema validator, and API files. Manifest SHA-256:
`986b961027c8ad830704ada7578914deb68a3fe5fddb429d7a06c64f1b781ecd`.
The exact deployed file descriptors are retained in `offline-gate.json` and
copied into the immutable attempt's `offline_gate_receipt.json`.

Fresh offline checks:

- Battlestar story + temporal tests: **213 passed, 14 subtests passed**.
- Build Week client/preflight/brief/enrichment tests: **120 passed,
  153 subtests passed**.
- Source re-admission, temporal recomputation, and bounded packet validation:
  passed. Packet and request bytes are identical to attempt 001.
- Canonical code, consumer adapter, deployment files, and actual JUnit receipts
  were pinned before the call. Source/evidence validation repeated afterward.

The previous full Build Week backend run recorded **801 passed**; it was not
rerun here. No production implementation changed during this rerun; the native
telemetry compatibility edits from the preceding run were preserved. No UI
tests/build were repeated because no UI or presentation contract changed.

## Single generation

- Local review root: `artifacts/oracle-story-rerun-20260919/` (ignored).
- Attempt: `attempt-002/`; prior `oracle-story-review-20260919/attempt-001/`
  remains intact.
- Started: `2026-09-19T20:37:42.444732Z`.
- Response observed: `2026-09-19T20:40:27.035882Z`.
- Trace: `dc53c6bf-3e13-45ed-8aff-8332aff396e7`.
- Appliance-reported model: `Qwen3-1.7B-4bit`, provider `mlx`, non-mocked,
  revision unavailable. This is returned provenance, not client routing.
- Requested/effective budget: **8192**; generated count **946**, source `native`.
- Finish: `stop`, source `native`; schema acknowledgement `json_schema`,
  `validated: true`. There is no evidence of budget exhaustion in this response.
- Request SHA-256:
  `bfc9e7ceba9326e71f0ea7915d643ecc89670040b069db5bbac9f628d2b89941`.
- Transport-reported raw response SHA-256:
  `df88e0ca38a797b07f4be36d311e8a882331919d1faea99a76461d3a7591d05a`.
- Candidate ID:
  `oracle-story-candidate-b32007a85bca6c673153cd27835c6c6ab1fdbd9a0bb69b57c49f86d005a34e52`.
- Candidate SHA-256:
  `841e5e069009ab7da2aad748b4967b4b0b9cda0b16cb594923d0dc6452fa0fd2`.
- Status **REJECTED**; validator **FAIL / INVALID_DRAFT_STRUCTURE**;
  `generation_calls: 1`, `published: false`, `execution_authority: false`.

## Narrative and evidence review

The canonical serialized draft is byte-identical to attempt 001, SHA-256
`5eb7271ec583c406d20a8142311eda288e1a8c6460a6f04772152d96dd36abb1`.
All six sections are `MARKET_NOW`, each repeating claim `C1` and this text:

> The SPY close MA200 returns have decreased from the prior session, but the current value is still above the prior 21-day MA.

This is rejected generated text, not endorsed analysis. It is already repeated
in ModelDock's response content; Build Week did not create the repetition.
Identical content alone does not prove a response cache or identify a model,
sampler, or decoder defect.

The actual canonical validator stops at the incorrect purpose ordering. Separate
review also finds duplicate claim IDs and duplicate `headline_spy` bindings,
unsupported `INCREASED`/`SAME` predicates, generated prose where `OBSERVED`
requires host-rendered text, an unbound numeric phrase, and a forward condition
outside Weather Ahead referring to nonexistent `headline_spy.current.value`.
That condition supplies invalidation but no reinforcement. These review findings
are not falsely presented as additional emitted validator error codes.

| Product question | Assessment |
| --- | --- |
| Does it tell a coherent market story? | FAIL: one ambiguous sentence repeated six times. |
| Does it explain change? | FAIL: no participation, leadership, growth/value, concentration, or dispersion comparison. |
| Does it expose hidden structure? | FAIL: no relationship between the intact headline trend and deteriorating participation. |
| Does it explain why? | FAIL: typed bindings are not entailed and the prose confuses moving-average and return comparisons. |
| Does it preserve uncertainty? | FAIL: no useful explanation of limitations or conflicting evidence; limitation IDs alone do not supply one. |
| Does Weather Ahead work? | FAIL: no Weather Ahead section or valid confirmation/alternative pair. |

The JSON shape used for generation allows six identical purpose values and
repeated IDs, and enumerates facts/predicates separately. Schema acknowledgement
therefore does not prove those semantic requirements. Canonical validation
correctly rejects the result; no validator was weakened to accept it.

## Preservation and integration boundary

The accepted brief, temporal artifact, input manifest and all eleven old-attempt
files retained their hashes. `preservation-before.json` and
`preservation-after.json` match, including the pre-existing working changes.
No ModelDock changes, Oracle prompt changes, Sentry changes, downstream synthesis,
trading authority changes, Governor/Navigator changes, or Cabin changes occurred.

Both repositories remain on `update/2026-09-19-oracle-story-diagnostics` with
their earlier uncommitted compatibility changes; this rerun adds local review
artifacts and updates documentation. No commits, pushes, merges, or application
restarts were performed by this run.

Even a future passing story cannot be coerced into the legacy mission brief:
that brief is bound to the September 18 19:05:11 UTC mission snapshot, whereas
the temporal story is a frozen reconstruction through September 18 with a
September 19 03:00 UTC evidence cutoff. A separate reviewed-story acceptance
envelope and explicitly dated consumer attachment would be required. Do not
replace the accepted mission brief or present retrospective evidence as live.

## Recommended next step — offline, canonical, not another deployment fix

Tighten the Battlestar-generated narrative contract so the schema expresses
section identity and only valid factual binding choices, instead of expecting
the narrator to satisfy those constraints through instructions alone. Prefer
required named sections, host-owned claim IDs/limitations, and evidence-derived
binding options, subject to ModelDock's supported schema subset. Characterize
this offline without encoding the desired September conclusion or weakening
semantic validation. This may eliminate structural failures; it does not prove
that the narrator can synthesize a useful market story.

No such contract redesign was implemented here. A further generation needs
explicit authorization after those offline gates. Cabin integration remains
deferred until canonical validation and separate product/entailment review pass.
