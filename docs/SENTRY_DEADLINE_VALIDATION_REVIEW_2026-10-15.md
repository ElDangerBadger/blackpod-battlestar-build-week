# Sentry slow-host validation and content review · October 15, 2026

Status: **BLOCKED — the longer real request returned HTTP 500.** No accepted
Oracle draft or challenge exists. Brief review and the article-content test
remain gated. All three failures are retained; no fixture response substitutes
for real output. The unfinished branch remains unmerged and unpushed.

## Diagnosis and approved change

The earlier 90-second failure was the **request budget sent by BlackPod**.
ModelDock's router honors `request.timeout` through `asyncio.wait_for`; its
300-second server default is a fallback, not a maximum. Its API timeout field
has a lower bound of one second and no upper API cap. BlackPod's canonical
`ModelDockConfig` already allows up to 1,800 seconds; only Sentry's narrower
service/transport guard needed extension. The exact cause of slow native
generation has not been isolated. No model-performance or completion guarantee
is inferred from increasing the deadline.

On the user's explicit authorization, current Sentry transport v3 supports
**900 seconds per generation plus 30 seconds delivery grace**. The wire sends
`timeout: 900`; the delivery deadline is 930 seconds. Configuration is bound
into the new correlation identity. Output contracts remain v2, with identical
prompts, evidence and 2,500-token limits. ModelDock's model, profile and routing
were not changed, nor was its source, global configuration or running service.

The Sentry control now uses 900/30 for subsequent governed synthesis. Monitoring
hours, frequency, maximum four attempts per LA day and the source collector
remain unchanged. The verified owned BlackPod station was gracefully restarted
while collectors were idle. Its read-only page displayed the pending-attempt
disclosure and auto-trading OFF, HTTP 200 with `Cache-Control: no-store`.

Exact configuration command:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python3.11 \
  -m blackpod_build_week.sentry_synthesis_service configure \
  --config output/blackpod-shadow-station/config.json \
  --modeldock-base-url http://127.0.0.1:8000 \
  --modeldock-timeout-seconds 900 --modeldock-delivery-grace-seconds 30 \
  --modeldock-profile default --enabled
```

## Separate real validation and preserved failures

Before admission, ModelDock reported READY with zero active requests/compute.
The original two capsules replayed and matched the saved byte fingerprints.
The hourly budget had elapsed. The new manual scope permits only this retained
diagnostic outside monitoring hours; it does not change background admission.

| Record | Identity |
| --- | --- |
| Original v1 failure | `sentry-synthesis-605d37b5d48cfdd8a15a10942a7eba2052dc2a5284c73b0d87268634bb49e56e` |
| Preserved v2 HTTP 504 | `sentry-synthesis-f2d06785aff25eb366c39ed9622f42d36654317a87ffbad6e86ebdce2749fe91` |
| V2 parent report SHA-256 | `ec65f0ce43888bb24f21b20599401127e939064b79e853d068412d163130bb04` |
| New v3 capsule | `4de928888e935581ec8a52beb7b7c98fcd297461e0cd5a98f617258d722f07a9` |
| Purpose / scope | `EXPLICIT_DEADLINE_VALIDATION` / `MANUAL_RETAINED_EVIDENCE` |
| Reserved | `2026-10-16T00:15:27.130400Z` · **October 15, 5:15:27 p.m. PDT** |
| Original source cutoff | `2026-10-15T21:20:44.916557Z` · October 15, 2:20:44 p.m. PDT |
| Exact packet SHA-256 | `19f24178e3c03f1355ba1dcaa4c53a6ff1edc6f8b99ac3f469a161cc7c89d97d` |
| Both-failures fingerprint SHA-256 | `8e99e5b2954cb4991b21ea78b98d30c26da5cfe5b6a1ea10e056c845e48a091c` |
| New Oracle request | `sentry-oracle-320dffdb7e5ae9192d6ce9bccd39e3363a69691b354063037043837201083704` |

ModelDock admitted the named `BlackPod-Sentry` request at
`2026-10-16T00:15:29.245986Z`. It remained active beyond 90 seconds, with no
additional served/error counters at that observation. Neither a late result
from the failed request nor a repaired output is being reused.

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python3.11 \
  -m blackpod_build_week.sentry_synthesis_service validate-deadline \
  --config output/blackpod-shadow-station/config.json \
  --source-report-id sentry-synthesis-f2d06785aff25eb366c39ed9622f42d36654317a87ffbad6e86ebdce2749fe91 \
  > output/sentry-deadline-validation-2026-10-15-001/validation-result.json
```

This deterministic capsule can be delivered once. Duplicate or interrupted
invocations read/recover retained work without resending. The v3 child cannot
become a parent for another deadline-validation attempt. Shared hourly/daily/
storage bounds, OFF, frozen source pins, watchlist and the original ancestry
are checked around delivery. Both prior failures retain their original bytes.

## Offline coverage

Actual completed test commands:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests .venv/bin/python3.11 \
  -m unittest discover -s tests -p 'test_sentry*.py' -q
# Final run: 419 run, 417 passed, two optional canonical-checkout checks skipped.

PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests .venv/bin/python3.11 \
  -m unittest test_shadow_station test_shadow_station_collection \
  test_shadow_station_macos test_shadow_experiment test_shadow_experiment_capture \
  test_shadow_experiment_cli test_shadow_experiment_reader \
  test_shadow_historical_baseline test_modeldock_delivery -q
# 184 passed.
```

Coverage includes the actual client over authored HTTP fixtures, longer wire/
delivery deadlines, exact v1/v2 replay, missing historical role intents,
configuration-bound identities, strict parent/metadata checks, hourly/daily/
OFF/pin/watchlist gates, no-resend recovery, interruption and processing-health
expiry. The tests made no real inference, provider, broker or content requests.
Real validation and content results must be distinguished from these fixtures.

The final Sentry run includes twelve additional safe-error-observation tests.
Total combined regression: **601 passed, two skipped**. Independent focused
reviews also passed; these are overlapping fixture checks, not extra real
model or entitlement successes.

The pilot verified unchanged before delivery: nine source pins, four events,
25 evidence blobs, two predictions, zero outcomes, head
`36a0aa46658e95e049098fb1748e982932aafe45920210a47808f572ec873f4d`.
Auto-trading, entries, execution worker, restart and capital transfers are OFF.
No orders, capital activation, policy change or Galactica trading rules are
part of this work.

## Actual result and limits of diagnosis

The new Oracle call returned **HTTP 500**, rather than timing out. Its receipt
finished at `2026-10-16T00:22:10.029552Z` (October 15, **5:22:10 p.m. PDT**),
about **400.8 seconds** after admission. The 900-second request budget allowed
it past the old 90-second limit. It did not establish successful generation.

- Report: `sentry-synthesis-e9d89f7792f75bd15e861a88c8a25b64db4a1335e91a0ae87f6a1f635fc16833`.
- Report completion: `2026-10-16T00:22:12.455780Z`.
- Oracle: FAILED / `MODELDOCK_HTTP_500`; response and accepted provenance absent.
- Oracle receipt SHA-256: `d4a38183d71bdb4e72988f29f9bf0abe5316fd433a5496d67ab10142c5a66f12`.
- Challenge: `ORACLE_NOT_ACCEPTED`; no challenge call occurred.
- Archive replay: three attempts, three FAILED reports, zero incomplete or
  abandoned reservations. Both older capsules match their saved fingerprints.

The installed ModelDock log records the HTTP 500, without a specific code or
traceback. Its handled-error path returns an error envelope without logging
that code. BlackPod's canonical urllib transport intentionally discards HTTP
error bodies. The exact error was therefore not retained and cannot honestly
be reconstructed. HTTP 500 alone cannot distinguish native inference failure,
constrained-decoder failure, final JSON/schema rejection or token exhaustion.
No token-limit diagnosis or malformed response was invented.

The late read-only observer fix applies only to future requests. It inspects at
most 8 KiB plus one overflow-detection byte for at most two seconds, leaving a
one-second margin within the original delivery budget. A complete,
well-formed envelope must have the exact expected request ID and a closed,
allowlisted error code. Only code, trusted request ID, HTTP status and integrity
hashes/counts can be retained in an optional immutable `http-error.json` bound
to the exact request and terminal receipt. Message, details, raw body, model
output and credentials are excluded. Unknown, malformed, oversized, truncated,
slow or mismatched input stays UNAVAILABLE. The canonical HTTP transport,
existing receipts/reports, strict output validation and no-resend guards are
unchanged. All three old capsules matched their fingerprints afterward;
provider-free inspection returned `null` for this historical error, rather
than inventing a missing code.

All-three-capsule fingerprint SHA-256:
`c5f4cf5986a7677a04b87b137427fad118a7e50892b99195a3c37d9af3216f3f`.

The exact retained schema was separately checked offline with ModelDock's
installed runtime: `request_schema` accepted it unchanged,
`grammar_from_json_schema` succeeded with the provider's exact overrides, and
tokenizer-free `LLMatcher.validate_grammar` succeeded in 0.265 seconds.
Schema SHA-256:
`65bb624a219998a28d3e267d628daf4063dfb62489f5b5719ec0f5657dcf7334`
(9,747 canonical bytes). No model/tokenizer/MLX inference modules were loaded,
no network was used and no generated response was repaired. These checks
exclude deterministic subset/grammar-compilation failure for this schema;
tokenizer integration, constrained sampling and final output remain unverified.

Reproduce the pure compiler check without overwriting retained metadata:

```bash
PYTHONDONTWRITEBYTECODE=1 HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 \
  /Users/nikolai/Projects/modeldock/dist/ModelDock.app/Contents/Resources/runtime/bin/python3.11 \
  /Users/nikolai/Projects/blackpod_battlestar_build_week/output/sentry-deadline-validation-2026-10-15-001/offline_schema_compile.py
```

The saved `offline-schema-result.json` records a second successful run in
0.306 seconds using llguidance 1.7.6, with `model_modules_imported: []`.

ModelDock reported Gemma 4 E4B (`gemma-4-e4b-it-4bit`), MLX/`mlx-vlm`, with
structured-output support. No current-token, phase or throughput counters were
available. The 16 GiB Mac had approximately 7.1 GiB system-wide swap in use;
this does not attribute the delay to ModelDock or establish its cause. A
three-second stack sample at 5:23:09 p.m. was taken **after the request had
already ended** and cannot diagnose time spent in that generation. No model,
route, profile or appliance settings were changed.

## Brief review and bounded content gate

No accepted pair exists, so no original themes or model dissent can be
reviewed. None was substituted. The planned probe destination
`output/sentry-content-entitlement-probe-2026-10-15-001` remains absent: no
article-content GET, body retention, rendering or model submission occurred.
The entitlement result remains NOT_RUN and no access/licensing conclusion is
claimed.

An independent preparatory review of the exact packet identified:

- Competing AI valuation and demand narratives, not verified economics or
  independent corroboration.
- Provider symbol tags that do not establish a textual/business relationship:
  one X-related headline is tagged GOOGL. The read-only label now says
  **Provider symbol tag · textual connection unverified**, preserving the
  original enum and model response contracts. Twenty-six presentation tests
  passed after this wording clarification.
- A CLX target reduction with its rating maintained; a PG shelf filing with
  unspecified size; a DG technical question without a confirmed breakout.
- One publisher, 20 selected/61 eligible headlines, eight attention duplicates,
  33 omitted distinct items, truncated coverage and unknown completeness.
- Ten already-stale price contexts (roughly 25–82 minutes old), no matched
  event response and no verified holdings. LULU has no selected headline;
  that is not evidence that it had no news.

These are retained-evidence limitations, not trading conclusions or approval.
Auto-trading remains OFF, and the frozen pilot/pins/journal remain unchanged.
No new request, automatic retry, new experiment, model-output repair, gate
bypass or capital/policy activation followed the HTTP 500.

## Remaining work and release state

The timeout configuration and safe diagnostics are implemented and deployed
locally. Final source changes cover the synthesis service/transport,
composition, read-only presentation, four corresponding test modules and
operation/result documentation. Canonical mission/ModelDock client code,
ModelDock appliance configuration, trading rules and frozen sources are
unchanged. Private output, credentials and article bodies are not committed.

Final local checks after the owned-station restart returned HTTP 200 for the
synthesis JSON and HTML pages, with the exact third report above and OFF
indicator. Sequential reads took about 4.7 and 6.0 seconds. An earlier
concurrent check timed out at 25 seconds; no verification was bypassed to
speed it up. Station status, the frozen experiment and historical report
returned 200 separately. The service heartbeat was current and ModelDock was
READY with zero active requests/compute. Read-only verification latency is a
remaining operational limitation, not evidence of successful model output.

No accepted brief/challenge exists and no content test result is claimed.
Main is therefore not merged or pushed. The next necessary diagnostic is a
**new, separately governed request that can retain ModelDock's safe error
code**, preserving all three failures and existing budgets. This would need
its own deterministic identity; it must not reopen this completed capsule.
The current ledger's one-hour admission would be no earlier than **October
15 at 6:15:27 p.m. PDT**. No new request, schedule, subsequent experiment or
automatic retry was created. Do not guess the cause or relax validation to
manufacture the accepted pair required by the content gate.
