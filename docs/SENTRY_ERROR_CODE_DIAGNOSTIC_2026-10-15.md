# Sentry error-code diagnostic · October 15, 2026

The user authorized one separately recorded diagnostic after 6:15 p.m. PDT,
followed by a demonstrated fix, an accepted brief/challenge review and the
bounded article-content check. These are separate gates: an HTTP error code
alone does not establish its underlying cause or satisfy the review gate.

## Boundaries and retained history

The diagnostic uses transport v4 and the exact terminal v3 HTTP 500 parent:
`sentry-synthesis-e9d89f7792f75bd15e861a88c8a25b64db4a1335e91a0ae87f6a1f635fc16833`.
Its immutable purpose is `EXPLICIT_ERROR_CODE_DIAGNOSTIC`, with scope
`MANUAL_RETAINED_EVIDENCE`. It is a historical diagnostic, not a fresh market
forecast. Its source cutoff remains **October 15, 2:20:44 p.m. PDT**.

The same headlines, model, profile, prompts, strict v2 output contracts,
2,500-token ceiling and 900-second request budget plus 30-second delivery
grace are retained. The three earlier failures remain byte-for-byte intact.
The new capsule binds its own request identity; it never resends an old one.
Shared hourly, four-attempt LA-day, storage, OFF, frozen-source and watchlist
gates remain enforced. Manual scope changes only hours/weekend admission for
this explicit retained-evidence diagnostic. A v4 capsule is not an eligible
parent for another error-code diagnostic.

The optional immutable error observation retains only a closed error-code
category, exact request identity, HTTP status and bounded integrity metadata.
It excludes provider messages, details, raw bodies and generated text. Unknown,
incomplete or mismatched observations remain UNAVAILABLE. Historical errors
are never backfilled with an invented cause.

## Actual command

After OFF, nine frozen source pins, original fingerprints, idle ModelDock,
hourly admission and absent destinations were verified, the owned idle
BlackPod station was gracefully reloaded to display the new version. No
ModelDock restart or configuration change was used to admit the request.

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python3.11 \
  -m blackpod_build_week.sentry_synthesis_service validate-error \
  --config output/blackpod-shadow-station/config.json \
  --source-report-id sentry-synthesis-e9d89f7792f75bd15e861a88c8a25b64db4a1335e91a0ae87f6a1f635fc16833 \
  > output/sentry-error-code-diagnostic-2026-10-15-001/validation-result.json
```

Reservation: **2026-10-16T01:20:50.549330Z**, October 15, **6:20:50 p.m. PDT**.
Capsule: `b13fedbcdfc56f88ea3eac4eb2bc0cad2ac26ea9658f05668711fbc5d1df8039`.
Oracle request:
`sentry-oracle-91e240974bcd556bf5e4bb0373e1343de0b2c76629b4d349d0754a30fe690dcf`.
Original packet SHA-256:
`19f24178e3c03f1355ba1dcaa4c53a6ff1edc6f8b99ac3f469a161cc7c89d97d`.
Original fingerprints are saved privately in
`output/sentry-error-code-diagnostic-2026-10-15-001/all-three-failures-before.json`.

## Offline validation

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests .venv/bin/python3.11 \
  -m unittest discover -s tests -p 'test_sentry*.py' -q
# 430 run; 428 passed; two optional canonical-checkout checks skipped.

PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests .venv/bin/python3.11 \
  -m unittest test_shadow_station test_shadow_station_collection \
  test_shadow_station_macos test_shadow_experiment test_shadow_experiment_capture \
  test_shadow_experiment_cli test_shadow_experiment_reader \
  test_shadow_historical_baseline test_modeldock_delivery -q
# 184 passed.
```

Combined: **612 passed, two skipped**. These are authored offline fixtures,
including local HTTP servers, not real inference or entitlement successes.
Eleven new tests cover version compatibility, strict metadata/UI disclosure,
exact parent eligibility, four-attempt exhaustion, correlated error retention,
interruption, no-resend and OFF/source protections. Independent read-only
review found no blocking issue in the v4 diff; `git diff --check` passed.

The frozen pilot, Sentry collection settings, trading policies, capital and
ModelDock model/profile remain unchanged. Auto-trading stays OFF. The intended
content destination remains
`output/sentry-content-entitlement-probe-2026-10-15-001`; any existing intent
must be verified rather than resent. Actual result and follow-up evidence are
recorded below only after they exist.

## Actual diagnostic result

The Oracle role failed again, with the specific code now available:
**`STRUCTURED_OUTPUT_INVALID`**, HTTP 500. Report completion was
`2026-10-16T01:27:26.896207Z`, October 15, **6:27:26 p.m. PDT**.
Report:
`sentry-synthesis-b531fdf49039f8dae915f7265360991379b004e971c96dac2641a3da63b4bf43`.
Report SHA-256:
`2667c3cfba53aae6250e92d8e574356b5c5fb524951d614e8eac283e9c1f28f1`.
Oracle receipt SHA-256:
`f82e6369003fab856362d782ca59d9e8b543093bc19c13878acfeef3c8239034`.
Error-observation SHA-256:
`25173a1dcd1337af2ee1cbae8351fbb04cad12d34c63bb3513858b22d3215372`.

The complete 242-byte error envelope was inspected only by the bounded
observer. Its raw bytes and message/details were not retained or printed;
only code, trusted request identity, size and hashes were published. The error
observation verified against the exact wire request and terminal receipt.
The role has no accepted response/provenance. Challenge remains
`ORACLE_NOT_ACCEPTED`; no challenge request was made.

This code localizes the failure to ModelDock's final `validate_result` gate
after generation. Its current implementation merges JSON syntax, duplicate
keys, nonfinite numbers, mock output and schema violations into the same
error. Native completion telemetry is available internally but is lost from
this failed API response. Token exhaustion is plausible, but is **not verified**
and no token-limit, schema, prompt or validation relaxation was applied.

Provider-free archive verification: four attempts, four FAILED reports,
zero incomplete/abandoned reservations. All three ancestors match the original
fingerprints. OFF and nine frozen source pins verify. Actual manual admission
now returns `DAILY_BUDGET_EXHAUSTED`. There was no fifth attempt or budget reset.
The private metadata-only verification result is
`output/sentry-error-code-diagnostic-2026-10-15-001/verified-result.json`.

The content probe status is `NOT_RUN`, `provider_calls: 0`, with no destination
created. No accepted Oracle/challenge pair exists to review. The underlying
output failure is not yet fixed; brief review, content capture, main merge and
push remain unfinished.

## User-authorized manual allowance and native diagnostics

The four-attempt/one-hour gate was BlackPod's own conservative workload
policy, not a Benzinga, Alpaca or ModelDock quota. After the user asked about
it, they explicitly selected **separate manual diagnostics from background
limits**. The implementation now projects background attempts separately from
retained explicit diagnostics. No ledger or past receipt is changed. Manual
v3/v4/v5 diagnostics bypass only schedule/day/spacing limits; pause, real-clock
sanity, serial service locking, deterministic one-child identities, storage,
OFF, watchlist and frozen-source gates remain. No automatic resends are added.
The earlier exhaustion observation above describes the policy at that time.

ModelDock's final validator now adds closed categorical diagnostics and native
completion counters without exposing text, exception strings or arbitrary
metadata. This is **observability, not an underlying generation fix**.
The local ModelDock branch is `codex/sentry-structured-diagnostics`, commit
`c9d89b6c0e48dcec52de56f969f3560270d6683a`; its remote/main was not changed.
Changed ModelDock paths: `src/validation/structured.py`,
`src/router/request_router.py`, `tests/test_structured_validation_diagnostics.py`.
All **256** focused offline ModelDock tests passed with one existing Starlette
deprecation warning. The new core wheel was built and installed into a staged
clone using `--no-index --no-deps`; all dependency versions stayed identical.
Both primary and isolated runtimes received the same core wheel and refreshed
build/dependency manifests. No dependency, model, profile, route or configuration
was added or changed.

The existing bundle validator passed native, layout, source-independence and
runtime import checks, with zero findings and 165 third-party build-metadata
warnings whose files match the original bundle bytes. An initial sandboxed
import probe failed for lack of Metal access; the identical probe passed with
Metal access. No model weights or inference were used by those checks.
The original native app is retained for rollback at
`/Users/nikolai/Projects/modeldock/artifacts/build/ModelDock-before-sentry-diagnostics-20261015.app`.
Six original configuration/profile/default/paddock hashes verify unchanged.

Current BlackPod offline regression: **450 run, 448 passed, two optional
canonical-checkout checks skipped**; station/pilot/baseline/delivery: **184
passed**. Total BlackPod: **632 passed, two skipped**. These remain authored
fixtures, separate from actual model delivery. A new explicit `validate-runtime`
v5 diagnostic will preserve all four failures and use the exact same retained
headlines, 900/30 budget, v2 schema and 2,500-token ceiling. Its optional error
sidecar can now verify the closed native category/counters against the exact
request and receipt. No past error is retroactively reclassified.

The reviewed ModelDock change is retained as a portable
[patch](patches/modeldock-structured-validation-diagnostics.patch), SHA-256
`04b055e846476f3386f77a4f4d283b7de78c0748334de15080818b26a740af28`,
against base `970404f4a549c93834218306fcae33e1c9962c67`. It includes its new
privacy tests. This is a review/reproduction artifact, not an automatic
installer or a new BlackPod runtime dependency. Apply only after checking the
target ModelDock checkout and preserving its unrelated work. Empty context
lines are whitespace-normalized; Git's reverse-apply check against the exact
deployed source passed.

The service initially finished native model loading after the CLI's explicit
30-second readiness wait had expired. That CLI retains an ERROR state even
when HTTP health later becomes READY. A graceful idle stop and normal start
with `--wait-seconds 180` restored READY under the owned lifecycle. This was
startup waiting, separate from the 900-second generation budget. No state file
was manually rewritten and no inference was retried.

## Separately recorded runtime diagnostic

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python3.11 \
  -m blackpod_build_week.sentry_synthesis_service validate-runtime \
  --config output/blackpod-shadow-station/config.json \
  --source-report-id sentry-synthesis-b531fdf49039f8dae915f7265360991379b004e971c96dac2641a3da63b4bf43 \
  > output/sentry-runtime-diagnostic-2026-10-15-001/validation-result.json
```

Reserved `2026-10-16T01:53:18.155171Z`, October 15, **6:53:18 p.m. PDT**.
Capsule `0af2dda86a7aa5a84d97f2248bfcd1d4c5a9263e9dc097cdc2b22e7aa59f3955`.
Oracle request
`sentry-oracle-b17a31eab95b61cd9ec521338dd58ab6f8a0b8ace7d47a6951eb0ddcf05c236f`.
All four ancestors were verified and fingerprinted before this new delivery;
the packet SHA-256 remains
`19f24178e3c03f1355ba1dcaa4c53a6ff1edc6f8b99ac3f469a161cc7c89d97d`.
The actual wire retains `timeout: 900` and `max_tokens: 2500`.

The runtime diagnostic completed at `2026-10-16T01:58:08.454070Z`, October 15,
**6:58:08 p.m. PDT**. Report:
`sentry-synthesis-9d971a17b14707ef1109a5122724ff96697655dc0e3578f796e3cd152de2bdc6`.
Its verified v2 error sidecar reports `JSON_SYNTAX`, native
`generated_token_count: 2500`, native `stop_reason: length`. The output reached
the requested ceiling and failed JSON parsing. No draft was accepted and no
challenge was called. All five reports and their ancestry verify; the four
earlier capsule fingerprints remain unchanged. This diagnoses the latest
attempt; it does not backfill the missing details of older failures.

Error-observation SHA-256:
`10d44670a161b7a5de321de308724528e7eb8b8749fba6ada3f59fa8c94d7687`.
Receipt SHA-256:
`90cf6c43d344fb617518d303417d95455904afb2f3ff5287d9c45dd3c8eec55d`.
Only the closed diagnostic was retained; no generated output or arbitrary
provider details were exposed. Metadata-only verification is saved privately
under `output/sentry-runtime-diagnostic-2026-10-15-001/verified-result.json`.

## Model selection correction before any token change

After that request completed, the user observed ModelDock defaulting to Qwen
and selected Gemma again. The post-restart checks had verified readiness but
had not captured the active-model endpoint. **The v5 failed request's actual
model is unverified**, because its failed response has no accepted execution
provenance. Unchanged configuration hashes do not establish an unchanged
in-memory active model. The user's observation is preserved separately from
the independently verified token-exhaustion counters.

At the next check, `/api/v1/models/active` reported `gemma-4-e4b-it-4bit`,
provider `mlx`, engine `mlx-vlm`; health was READY and requests/compute were
both zero. On the user's explicit steering, **no 4,096-token request ran**.
The next separately recorded v6 `validate-model` trial preserves the original
2,500-token ceiling, exact packet, prompts, v2 schema and 900/30 deadline.
Its purpose is `EXPLICIT_MODEL_SELECTION_VALIDATION`. Original attempts stay
unchanged. Any token-budget remedy remains conditional on this Gemma trial.
Actual accepted model provenance must be checked for both roles; preflight
selection alone is not a substitute for that provenance.

The actual original-token command was:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python3.11 \
  -m blackpod_build_week.sentry_synthesis_service validate-model \
  --config output/blackpod-shadow-station/config.json \
  --source-report-id sentry-synthesis-9d971a17b14707ef1109a5122724ff96697655dc0e3578f796e3cd152de2bdc6 \
  > output/sentry-gemma-validation-2026-10-15-001/validation-result.json
```

Reserved `2026-10-16T02:09:18.550943Z` (October 15, **7:09:18 p.m. PDT**),
capsule `9d167055ba512965e1a30fc3033cc3c28387045afad65209e6e4a6ee6ef644a5`.
ModelDock's active-model endpoint reported Gemma 4 E4B before, during and after
delivery. These metadata-only observations are retained beside the command
result and explicitly labeled as selection observations, not successful
execution provenance.

The role ended at `2026-10-16T02:15:53.238447Z` (7:15:53 p.m. PDT), again with
HTTP 500 / `STRUCTURED_OUTPUT_INVALID`, `JSON_SYNTAX`, native count **2500** and
native stop **`length`**. No Oracle or challenge was accepted. Report:
`sentry-synthesis-353d720e03c83183ca276ccec3f794fa33344aea9f5dd4c974f2b1197baa6487`,
completed `2026-10-16T02:16:01.408688Z`.
Error-observation SHA-256:
`4084c342d896f54fa4ed849644e8b2663688439cf1828b88451074761a5f0e83`.
Receipt SHA-256:
`4c694b18cfcfa6f93bde6bc61203402680bc71c8723cb4a3039122c47bfea9ae`.
All six reports verify and all five older capsules retain their bytes. No
higher-token request had run before this original-budget Gemma result.

## Explicitly approved persistent startup model

Read-only inspection found the concrete mismatch: the bundled
`defaults/config/server.yaml` selects Gemma, but
`~/Library/Application Support/ModelDock/config/server.yaml` selected
`Qwen3-1.7B-4bit`. The per-user override wins on startup. Runtime activation
does not persist that override in ModelDock's current activation path.

The user explicitly approved **Persist Gemma as the startup default**. At
`2026-10-16T02:15:58.527422Z`, only `active_model` changed to
`gemma-4-e4b-it-4bit`; all other parsed settings and original formatting were
preserved. A private original-file copy and before/after hashes are retained in
`output/sentry-gemma-validation-2026-10-15-001/`. The write was atomic,
fsynced and guarded against concurrent edits. No restart or model activation
was performed, so the running validation was uninterrupted. This is the one
separately authorized ModelDock configuration change; the earlier unchanged
configuration checks above describe their original observation times.

## Targeted output-budget validation

The failed Gemma trial now supports the user's conditional token-budget check.
Transport v7 allows **4,096 tokens** while preserving v1–v6 at exactly 2,500
for replay. Packet, prompts, response schema, profile, model selection and
900/30 deadline remain unchanged. Native `length` completions remain rejected;
format validation and provenance checks are not relaxed. The explicit
`validate-output-budget` path requires the exact verified terminal v6
JSON-syntax / native 2,500-token / `length` failure, retains all six ancestors,
and cannot be resent or used as another output-validation parent.

During this targeted validation, ordinary background synthesis remains pinned
to v6/2,500. Promotion of the normal path is gated on the real validation;
no 4,096-token background call is claimed here.
