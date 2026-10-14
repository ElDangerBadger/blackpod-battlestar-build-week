# Supplemental Oracle Market Brief

Battlestar owns the evidence vocabulary, metric meanings, prompt, draft checks,
and receipt contract in `blackpod/advisors/oracle_market_brief.py`. Build Week
uses that explicit canonical checkout and the existing local ModelDock client
to produce one optional, saved presentation supplement. It does not maintain
another Oracle engine or change Council's inputs.

The Cabin's Oracle narrative page shows a headline and six sections:
participation, leadership, rotation, risk, watchpoints, and limits. Each passage
links to recorded Oracle facts; exact values, their meanings, and model
provenance are expandable. Market snapshot time and generation time are
separate. A brief written today about an old mission is **not today's market**.

## Deterministic semantic guardrails

The existing Build Week publication validator now checks a finite set of
recognizable directional and relationship contradictions against the canonical
evidence catalog. Generation, existing-brief reuse and the read-only reader use
the same checks. They compare positive participation and defensive/cyclical rank
relationships, preserve the declared breadth posture, and reject recognizable
unsupported aggregate price direction, moving-average relationships,
named-sector leadership, market causes, forward certainty and temporal claims
without prior evidence. A participation fraction is not an aggregate index
return; cross-sectional rank strength is not a return or a probability.

Supported explanatory prose, uncertainty and conditional scenarios remain
available. The validator does not generate a metric-only replacement narrative,
repair a response, alter the prompt or retry inference. Rejected prose is not
published; existing sanitized diagnostics and durable attempt reservations
remain in force. A historical brief that fails the current check remains intact
on disk and is unavailable to the reader rather than rewritten.

These English-pattern checks are deliberately bounded. They can miss
paraphrases and do not establish arbitrary semantic entailment, causal truth,
overall narrative quality or predictive effectiveness. The receipt retains
`STRUCTURE_CITATIONS_AND_GUARDRAILS_CHECKED_NOT_ENTAILMENT_VERIFIED`. The current
catalog contains aggregate proxy evidence, not MA histories or named-sector
return observations. Testing unsupported assertions is not a claim that those
missing analytical capabilities have been implemented. See the
[consolidation validation](RESEARCH_ACCEPTANCE_VALIDATION.md) for the actual
regressions, retained-narrative check and unresolved limits.

## Explicit generation from an existing LIVE mission

Use the repository virtual environment and the existing local ModelDock service.
ModelDock owns model selection. This is an operator command,
not an HTTP write endpoint or browser action:

```sh
BATTLESTAR_PATH=/absolute/path/to/blackpod_battlestar \
MODELDOCK_BASE_URL=http://127.0.0.1:8000 \
MODELDOCK_TIMEOUT_SECONDS=180 \
.venv/bin/python3.11 -B -m blackpod_build_week.oracle_market_brief \
  --artifacts-root /absolute/path/to/artifacts \
  --mission-id your-existing-live-mission-id
```

The command requires a succeeded Oracle stage and all five intact source
artifacts: measurements, diagnostics, readiness, assessment, and report.
It fetches no market data and runs no analytical stage. New LIVE requests omit
`model` entirely; there is no registry lookup, activation, fallback, or model
selection in Battlestar/Build Week. Legacy `MODELDOCK_MODEL` environment values
are ignored. ModelDock's returned model identity is saved only as audit metadata,
not compared with a client-side pin. Correlation, non-mocked local-service
provenance, content, and bounded output are still checked. The existing local
MLX response policy remains; this change does not authorize cloud providers.
Default output budget is 3,072 tokens.

The richer brief now sends the unchanged canonical prompt as a semantic
`messages: [{role: "user", content: ...}]` request. ModelDock owns native chat
formatting. This avoids treating an instruction-following brief as raw text
continuation and requires no model/engine/template knowledge in the client.
The brief now also sends the canonical `build_output_schema(evidence)` as
`response_format: {"type": "json_schema", "schema": ...}`. ModelDock must enforce
that schema while decoding and validate the completed JSON. The client requires
`metadata.structured_output: {"mode": "json_schema", "validated": true}` before
accepting the response, so an older appliance cannot silently ignore the option.
The producer independently rechecks that acknowledgement before publication,
including when an injected executor supplies the result.
Unavailable constrained decoding fails the attempt; no prompt-only fallback or
automatic retry is permitted. Deploy a ModelDock version with this capability
before authorizing a live attempt.

The schema requires the exact root, section, headline and paragraph keys,
bounded strings/arrays, the draft version and allowed section/citation IDs.
Canonical validation still checks section order, distinct citations, evidence
alignment and prose/domain rules; schema conformance does not establish truth.
All existing validators, evidence rechecks and publication gates remain active.
Legacy enrichment/preflight requests and frozen REPLAY inputs keep their
original `response_format: {"type": "json"}` behavior.

Implementation and fixture tests do not authorize a live acceptance run.
Existing failed attempts remain reserved, including the reviewed request
revision. Obtain explicit authorization for one concrete invocation using saved
evidence and the existing reviewed workflow; do not remove reservations, refresh
evidence or change the prompt merely to unlock another call.

The same routing boundary applies to the legacy Oracle enrichment producer and
deep ModelDock preflight. Preflight's historical model-registry status fields
are `null` (intentionally not checked), not readiness gates. Frozen replay packs
retain their original model field as historical evidence and never call ModelDock.

The additive files under the selected mission are:

- `presentation/oracle_market_brief.json`: accepted immutable receipt.
- `presentation/oracle_market_brief_attempt/`: durable intent/request and
  success evidence or a sanitized failure receipt.

An existing valid brief is returned without inference. An interrupted or failed
attempt remains reserved: rerunning does **not** silently issue another call.
Do not delete that reservation to force a retry. Investigate the recorded
failure and obtain authorization for a separately reviewed attempt. Invalid
existing output is never overwritten. Source bytes and the canonical module
hash are rechecked before exclusive atomic publication.

For an explicitly authorized retry of the **original failed attempt**, add
`--reviewed-retry-of <SHA256-of-original-failure.json>` to the same command.
The producer requires intact, matching failure/request/intent evidence and
reserves `presentation/oracle_market_brief_retry_<SHA256>/` exclusively.
The original directory is untouched. The retry records its lineage and rechecks
the original attempt before publication. A repeated command cannot issue a
second request; even a failed retry remains reserved. There is no retry loop,
failure-receipt deletion, schema relaxation, or recursive retry of retries.
An accepted brief still uses the single canonical `oracle_market_brief.json`
publication path, and subsequent invocations simply verify that existing brief.

When that reviewed retry has also failed, a separately authorized canonical
prompt correction may use `--reviewed-request-revision` together with the same
`--reviewed-retry-of <original-failure-SHA256>`. This requires both completed,
intact failed attempts and the same evidence. The new canonical prompt must
differ from both previous prompts; changing only a token budget or timeout
does not qualify. An exclusive request-hash-keyed
`presentation/oracle_market_brief_revision_<hash>/` preserves the lineage and
prevents duplicate calls for the same request. Both predecessor histories are
rechecked before publication. This is an explicit invocation, not an automatic
or recursive retry mechanism; another failure must not trigger another call.

The current Battlestar prompt explicitly separates the input evidence schema
from the required output schema, supplies exact JSON object shapes and the
available citation vocabulary, and scopes qualitative-prose restrictions to
`text` fields. Its invalid replacement placeholders cannot pass validation as
a canned report. Evidence, output contracts and safety validators are unchanged.

Failures include only bounded, non-content diagnostics. JSON syntax failures
report line/column and decoded-character offset without retaining the rejected
text. Recognized canonical brief failures report fixed rule/field labels (for
example, `prose_guardrail` for a compound prose-policy rejection); they do
not expose the offending text or claim a narrower cause than the canonical
validator established. Unknown errors remain unclassified. These diagnostics
do not remove reasoning blocks, repair JSON, relax checks, or authorize retries.

## Read-only consumption

Restart the Cabin reader after updating application code, then use the ordinary
LIVE artifact selection. No new reader flag is required. The reader includes an
optional hash-pinned manifest reference only when the receipt exists and passes
mission, source, citation, timestamp, safety, and content-ID checks. The browser
verifies the bounded artifact bytes, source references, and cited values before
display. Opening or refreshing the book never invokes ModelDock.

Old missions without a brief remain readable with their existing native and
fact-selected narratives. A present invalid supplement fails publication closed;
it is not passed off as an absent or successfully generated report.

## Evidence and safety boundaries

This is supplemental model interpretation, not authoritative Oracle analysis.
Structural checks, hashes, citation validation, and lexical guardrails do not
prove semantic entailment. The UI explicitly says so. Numbers remain exact
source facts rather than model-generated prose. Coverage warnings and missing
prior measurements remain visible. Aggregate measurements do not justify
inventing per-symbol leadership, causes, forecasts, or a recommendation list.
The configured local producer is a trust boundary: self-hashes are integrity
checks, not digital signatures. Consumers verify transport and source binding;
they do not independently rerun the canonical prose policy or prove that a
locally rewritten, rehashed receipt was generated by a model.

Galactica informed the readable report structure only. Its trading assumptions
and old Brigade/Senate contracts were not ported. Existing deterministic Oracle
outputs, the restricted fact-selection narrative, Council inputs, mission
snapshots, and replay behavior remain unchanged. Sentry is not an input.

Governor already runs its canonical LIVE policy path. The saved September 15
mission's no-trade mandate intentionally blocks action; this feature does not
remove that block or change Governor, Navigator, ModelDock, or order authority.
Generation artifacts stay local/ignored alongside the mission evidence.

## Verification

```sh
BATTLESTAR_PATH=/absolute/path/to/blackpod_battlestar \
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python3.11 -B -m pytest -q -p no:cacheprovider \
  tests/test_oracle_market_brief.py tests/test_oracle_brief_reader.py \
  tests/test_cabin_reader.py
cd ui
npm test -- --run
npm run build
```

Use the project's Node 22 runtime. Canonical tests live separately in
Battlestar's `tests/test_oracle_market_brief.py`; legacy Oracle regressions must
also pass there. Synthetic test briefs are test fixtures, not live model evidence.

## September 18 implementation check

The authorized single ModelDock attempt incorrectly requested a specific model
(`gemma-4-e4b-it-4bit`). The actual returned model was not retained. It used only saved
`mission-live-aapl-20260915-002` evidence under
`artifacts/no-trade-live-20260915`. The five source files yielded 36 facts with
market as-of `2026-09-15T23:05:20Z` and evidence ID
`oracle-brief-evidence-8bc07842b675d1ddcf5a374b1100867c9d766ecb17e4950e372424e9d60f6acd`.

That attempt failed with `MODELDOCK_FAILED`; **no brief was published** and no
retry was made. Its first-version failure receipt did not retain the more
specific sanitized client error. ModelDock's existing access log is insufficient
to reconstruct that cause; HTTP success does not imply accepted model content.
Do not infer that the model was at capacity, that a specific guardrail failed,
or that writing quality has been validated. The request and failure receipt
remain preserved, local and ignored. Later diagnostics changes do not rewrite
that receipt or remove its no-retry reservation.

The routing audit subsequently confirmed that ModelDock uses its active model
even when a request names a different one. The old client-side equality check
could therefore reject a valid appliance response. It has been removed for LIVE
calls, but the original failure cannot be conclusively attributed to that check.
No further inference was performed during the routing correction.
Routing regression validation: the scoped Build Week backend suite passed
735 tests and 759 subtests; the final focused routing/Oracle/preflight run
passed 114 tests and 101 subtests, including historical LIVE no-op compatibility.

The Cabin continues to publish the original mission and native narrative, with
an explicit missing-brief note. No current market data or downstream stage was
run. A new inference requires a separately reviewed attempt and authorization.
Automated component/contract tests cover the richer report; the browser check
covers the real missing-supplement state, not a successful live-generated brief.

A later, separately authorized fresh September 18 mission used appliance-owned
routing correctly. Its single brief attempt returned malformed narrative JSON
and was preserved without retry; native Oracle/Council/Governor execution
succeeded. See the [fresh-run operator record](LIVE_ANALYSIS_RUN_20260918.md)
for that distinct attempt, diagnostics, and current application source.

The [narration integration follow-up](ORACLE_NARRATION_INTEGRATION.md) switched
the richer brief to ModelDock's supported semantic-chat input and added an
explicit hash-bound reviewed retry. Its one authorized saved-evidence call also
failed JSON parsing; no brief or automatic retry was published. This remains an
unresolved output-contract/acceptance issue, not a missing canonical Oracle port.

Final focused validation: 142 Battlestar tests (34 subtests), 162 Build Week
backend tests (200 subtests), and all 1,029 UI tests passed. The UI production
build passed with the existing large-chunk warning. Browser fallback inspection
reported no console errors. The original mission snapshot and frozen Sentry V2
declaration, development summary, and protocol hashes remain unchanged.
