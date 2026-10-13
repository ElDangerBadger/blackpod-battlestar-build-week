# Oracle / ModelDock timing and delivery checkpoint

## Scope and finding

Attempt 010 recorded a client timeout at 300,005.583 ms, with no response body,
hash, draft, or candidate. It remains a failed one-call attempt; nothing is
recovered, retried, published, or reclassified by this checkpoint.

The consumer and service previously both had a 300-second budget, but they did
not start the same clock. Build Week starts before transport. ModelDock performs
admission/restoration and request preparation before starting its provider
execution timer. It also normalizes/validates the returned response afterward.
Consequently, a provider timeout receipt (or a result near the provider deadline)
can arrive after the consumer has already stopped waiting.

This establishes a delivery-deadline race, not the particular slow stage inside
attempt 010. Existing receipts cannot distinguish admission, loading, queuing,
prefill, decoding, or response processing. Raising a deadline is not proof that
inference will finish within it.

Local authoritative references, inspected without calling the appliance:

- ModelDock `src/api/app.py`: `admit_generation`, `invoke`, `generate_text_buffered`.
- ModelDock `src/router/request_router.py`: `generate_text` calls `prepare_text`
  before `asyncio.wait_for(provider.execute(...), timeout=...)`.
- ModelDock `src/providers/mlx.py`: shielded/off-thread compute ownership and
  detached-task handling. HTTP cancellation need not stop native computation.
- ModelDock `tests/test_mlx_execution_lifecycle.py`:
  `test_timed_out_compute_keeps_runtime_busy_and_model_switch_waits` explicitly
  expects HTTP 504 while `active_compute=1`, state `BUSY`, and health `ready=true`.

ModelDock is unchanged. No model selection, sampling, prompt, narrative schema,
completion validator, or evidence-review policy changes belong to this fix.

## Separate budgets

| Setting | Meaning | Bound / default |
| --- | --- | --- |
| `MODELDOCK_TIMEOUT_SECONDS` | Explicit provider/request execution budget; rounded up to an integer on the wire | Required; positive, at most 1800 seconds |
| `MODELDOCK_DELIVERY_GRACE_SECONDS` | Additional LIVE allowance for admission and buffered response delivery/validation | Optional; 30 seconds by default; 0–120 seconds |
| LIVE client delivery deadline | `ceil(timeout_seconds) + delivery_grace_seconds` from client start | Checked before transport and before accepting a result |

A 300-second request now has a 330-second default LIVE delivery allowance. The
wire request still asks ModelDock for 300 seconds; grace cannot be spent by
silently increasing that request. Battlestar's shared Oracle request builder now
allows an explicitly chosen service budget up to 1800 seconds, matching the
consumer. Its existing 300-second runner default remains unchanged.

No active environment, launch configuration, or frozen request was changed.
For a separately authorized future experiment, 600 seconds of provider budget
and 60 seconds of delivery grace would mean a 660-second client allowance. These
are illustrative bounded settings, not a measured latency requirement or a
guarantee of success. Freeze the chosen values with that experiment's receipt.

REPLAY retains its prior `timeout_seconds` deadline, recorded request, and no
new HTTP request header. Increasing LIVE grace does not rewrite replay artifacts.

The standard-library transport uses socket inactivity timeouts and monotonic
checks between reads; the client also refuses responses that finish after its
deadline. This is not a hard wall-clock kill of arbitrary blocking code. A slow
trickle within an individual socket/header read can overrun a check boundary.
Nor does stopping client waiting cancel or prove termination of native compute.

## Delivery diagnostics, without accepting failed prose

`ModelDockCallResult.delivery` and `ModelDockFailure.to_dict()["delivery"]`
provide the additive `blackpod.modeldock_delivery.v1` receipt. Existing canonical
safe-response and mission-provenance schemas remain unchanged. The operator
should retain the successful result's delivery mapping alongside its review
receipt; failure serialization includes it automatically.

The receipt distinguishes request validation, transport, connect/wait-for-headers,
reading response body, response received, response validation, and complete.
It records request/body correlation, service and client budgets, HTTP status,
captured byte count, completion flag, partial-body hash where available, and
whether the echoed HTTP request ID matched. Arbitrary headers, error text, and
incomplete narrative prose are not copied into the receipt.

LIVE supplies ModelDock's existing `X-Request-ID` header. A compatible correlation
ID is reused; otherwise a stable SHA256-based header is used without altering
the original body/correlation. The echoed ID is diagnostic, not a substitute for
the existing strict response correlation validation.

Unread HTTP error bodies are explicitly incomplete, with no invented empty-body
response hash. HTTP status still proves endpoint delivery for preflight, not
successful inference. Partial-body hashes cover chunks actually returned to the
reader, not bytes still buffered internally. A late full response retains its
captured hash/status; a deadline exceeded during validation strips prose and
keeps diagnostic metadata. Neither path accepts a late narrative.

All failures leave `server_completion=UNKNOWN` and
`automatic_retry_allowed=false`. A valid LIVE result records
`VALIDATED_RESPONSE_RECEIVED`; REPLAY records `VALIDATED_REPLAY_RECEIVED`.
The legacy `resumable` flag means an operator may investigate/resume a workflow;
it is not authorization to resubmit the request automatically.

## Operator boundary and remaining limitation

Do not retry merely because `/health` reports ready. That can coexist with busy
native compute. Use ModelDock's own runtime/compute status to establish idle
state before any separately authorized call. Build Week's deep preflight itself
performs an inference, so it is not a free status-only probe.

The inspected ModelDock API has no durable job/result-retrieval endpoint. A
response lost after client disconnect cannot be assumed recoverable. Structured
JSON generation is buffered; switching to streaming would change its supported
contract and is not part of this fix.

Before another controlled Oracle generation, regenerate the offline source-pinned
gate because the request/client files changed, record the selected two budgets,
confirm the appliance is idle, and retain delivery diagnostics. Exactly one call
and separate narrative/validator review remain necessary. No live outcome is
claimed from the simulated timing tests.

## Files and preservation

Final offline validation:

- Battlestar Oracle regressions: **943 passed, 100 subtests passed**.
- Build Week ModelDock / Oracle regressions: **239 passed, 341 subtests passed**.
- New delivery tests also pass under the repository's `unittest` discovery:
  **11 tests**, included in the 239 above (not additional tests).
- Both broad focused runs used the existing process-wide network-denying runner:
  **zero network attempts**. No live inference or preflight was run.
- Both repositories pass `git diff --check`.

The initial Build Week test invocation lacked the repository root on `PYTHONPATH`
and failed collection of `tests.test_oracle_enrichment_workflow`; no tests ran in
that invocation. Adding the root fixed only test discovery. Both that collection
receipt and the subsequent successful receipts are preserved locally.

Coverage includes service-budget bounds/defaults, integer rounding, unchanged
V4/V5/V6 payloads except an explicitly selected timeout, delayed success and 504,
late rejection, validation overrun, partial/no-header timeouts, redaction,
correlation headers, replay compatibility, and no automatic retries.

Battlestar owns the canonical request-budget bound and its regression tests:
`blackpod/oracle_story/request.py`, `tests/test_oracle_story_request.py`, and
`tests/test_oracle_story_delivery_budget.py`.

Build Week owns operational config, transport, preflight delivery classification,
and their tests: `modeldock_config.py`, `modeldock_client.py`,
`modeldock_preflight.py`, and corresponding `tests/test_modeldock_*.py` files.

Starting branch in both repositories:
`update/2026-09-19-oracle-story-diagnostics`.

- Battlestar HEAD: `e2a919c360fc5a7482ba8339c2b035fa8903f6ef`.
- Build Week HEAD: `69cb1bbc68d75964fd2c31a041cb3e6318aa08f7`.

Both had existing operator changes; they were preserved, not cleaned or staged.
The ignored local checkpoint directory
`artifacts/oracle-delivery-hardening-20260921/` contains before/after preservation
receipts, changed-path inventory, and offline test reports. It also records the
accepted brief and frozen/previous-attempt artifact hashes. No commit, push,
merge, publication, fresh market collection, or ModelDock call was made.
