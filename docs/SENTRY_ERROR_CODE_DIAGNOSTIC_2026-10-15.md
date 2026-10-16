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
