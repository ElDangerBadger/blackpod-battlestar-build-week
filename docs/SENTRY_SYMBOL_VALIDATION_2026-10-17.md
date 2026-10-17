# Sentry symbol-keyed validation — October 17, 2026

This burst addresses a structural Oracle failure. It does not establish a better
market interpretation, predictive skill or trading authority. The frozen
QQQ/SPY experiment stays unchanged and auto-trading stays **OFF**.

## Preserved failure

The October 16 parent remains immutable:

| Identity | Value |
| --- | --- |
| Report | `sentry-synthesis-6529b589ed887233082c1c4d251799c376b1bf41a3a4cb3311f8b16bd49d7397` |
| Report SHA-256 | `775e6ef20c32108e3b5824e3e6a8263168c9f25b7c1c4a049c582af6f71f9631` |
| Original packet SHA-256 | `e2afe8569760ade81cb2e52ed52f256f9225162e1bbad3e044013babce2347fe` |

Oracle was rejected with `MODELDOCK_NARRATIVE_SCHEMA_INVALID`. Its verified
local diagnostic identifies `DUPLICATE_SYMBOL` within a theme's implications.
The diagnostic does not identify the repeated ticker; none is inferred.
Its coarse rule/field remain `OTHER` / `UNCLASSIFIED`.

The challenge was **not run** because Oracle never supplied an accepted draft.
The original challenge placeholder still records `UNCERTAIN` with
`ORACLE_NOT_ACCEPTED`; no stored status is rewritten. The UI explains this known
block as “Not run — Oracle draft was rejected/failed.” A genuinely uncertain
challenge delivery, such as a timeout, remains uncertain.

## Separate contract and validation

The explicit v10 transport requests **Oracle draft v3**. Each theme uses
`implications_by_symbol`, a map whose optional keys are restricted to the exact
watchlist. Each present value contains only `linkage`, `trading` and
`investment`. A theme must contain at least one implication. This prevents an
ordinary array from repeating a symbol while retaining strict host checks.
ModelDock's schema subset does not support `minProperties`; BlackPod enforces
the nonempty-map requirement after delivery, without supplying missing values.

Duplicate JSON keys, including equivalent escaped keys, are rejected before
projection. Empty maps, unknown symbols, extra value fields, mixed map/array
representations and invalid direct-mention citations are rejected. No output is
deduplicated, repaired, trimmed into acceptance or silently converted.

Original accepted maps remain maps. The challenge retains its v2 contract and
must hash the **original v3 draft**, not a display array. Rendering and narrative
evaluation use detached display rows; claim paths retain symbol identities,
for example `/draft/themes/0/implications_by_symbol/NVDA/investment`. Original
prose and challenge dissent remain separate.

Retained Oracle v1/v2 arrays, v1–v9 requests, failures and narrative evaluations
continue to replay with their original identities. Future background work uses
v10 under the existing strict gates. This is an offline-validated format fix:
the real-model check below failed at connection delivery and supplies no evidence
that Gemma can generate an accepted v3 response. No authority or schedule changes.

`validate-symbols` admits one deterministic child of the verified terminal v9
Oracle schema rejection with a verified v2 `DUPLICATE_SYMBOL` observation.
Accepted, uncertain, wrong-reason or v10 parents are ineligible. It reuses the
exact historical packet and preserves the failed parent. At most two local
ModelDock calls can occur: Oracle, then challenge only if Oracle is accepted.
The 4,096-token ceiling, 900-second deadline plus 30-second grace, serialization,
archive bounds, watchlist and OFF/source-pin gates remain in force. Existing
reservations are inspected or recovered without automatic resending.

Run from `/Users/nikolai/Projects/blackpod_battlestar_build_week` only when this
specific manual validation is authorized:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python3.11 \
  -m blackpod_build_week.sentry_synthesis_service validate-symbols \
  --config output/blackpod-shadow-station/config.json \
  --source-report-id sentry-synthesis-6529b589ed887233082c1c4d251799c376b1bf41a3a4cb3311f8b16bd49d7397
```

This path makes **no Alpaca, broker, account or article-content requests**.
There is no ModelDock configuration change, new experiment or trading activation.

## Offline verification commands

Authored fixtures cover the new contract/transport, parent eligibility,
interrupted processing, exact map hashes, original dissent, truthful status
labels, escaping and read-only HTTP behavior. They do not establish real-model
success or narrative quality.

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests .venv/bin/python3.11 \
  -m unittest test_sentry_symbol_validation test_sentry_synthesis_contracts \
  test_sentry_synthesis_transport test_sentry_synthesis_core \
  test_sentry_synthesis_presentation test_sentry_synthesis_http \
  test_sentry_narrative_evaluation -q

PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests .venv/bin/python3.11 \
  -m unittest test_sentry_synthesis_service -q
```

Fixture HTTP tests require loopback socket permission. Optional canonical-checkout
tests remain skipped unless their explicitly configured source is available.

## Actual saved-packet check

Exactly one v10 Oracle attempt was recorded. It **failed delivery**; there is no
accepted new brief and the challenge was not requested. No request was resent,
no new destination was selected, and ModelDock was not restarted or reconfigured.

| Item | Recorded value |
| --- | --- |
| Child report | `sentry-synthesis-410032d44c238479a2042683a7b0a1f42883e513cf8431c56a288d35f0c66b4a` |
| Child report SHA-256 | `496fb939697045c2005230821857dde5531000b8406b8c02ef4d4533507a7128` |
| Child directory | `output/blackpod-shadow-station/synthesis/runs/805861709087f32d78e90fc4a79ae3f7d76dcaefc9ec539820cb67ca4c167443` |
| Oracle request | `sentry-oracle-9488203c185c7c8cb89ea982b1e3eb74cf576dda52d57decac90aa0c51c829b1` |
| Run reserved | `2026-10-17T20:57:39.186688Z` / 1:57:39 p.m. PDT |
| Oracle receipt | `2026-10-17T21:00:22.878889Z` / 2:00:22 p.m. PDT |
| Report completed | `2026-10-17T21:00:26.334284Z` / 2:00:26 p.m. PDT |
| Oracle | `FAILED / MODELDOCK_CONNECTION_FAILURE` |
| Challenge | Not run; original placeholder `UNCERTAIN / ORACLE_NOT_ACCEPTED` retained |

Before delivery, local metadata showed ModelDock READY, zero active requests and
compute, and Gemma 4 E4B selected. Its backend log subsequently recorded
`Shutting down`, with a last modification time of `2026-10-17T21:00:20.063489Z`.
At `21:01:06Z`, both documented health and stats GETs received connection refused
on port 8000. This supports a service-availability failure; the shutdown cause
is unconfirmed. No returned model provenance or response was accepted, so the
actual generating model, output quality and v3 compatibility remain unverified.

This check uses the original October 16 headlines and delayed SIP context. It is
not a fresh assessment. Headlines, omissions, single-publisher coverage, absent
holdings and unverified causal claims retain their original limitations. The
offline format fix does not establish better analysis or a trading edge.

## Verification and deployment

Local before/after evidence is retained in
`output/sentry-symbol-validation-2026-10-17-001/before.json` and `after.json`.
The latter verifies:

- All 13 original attempt capsules and 210 catalyst entries are byte/hash unchanged.
- The station configuration and both Sentry controls are unchanged.
- The frozen protocol/source pins and original six-event pilot journal are unchanged.
- The new child has the identical packet hash and exact original parent-report hash.
- All 14 reports replay: one challenged interpretation, seven failed, six rejected;
  zero incomplete attempts or abandoned reservations.
- Auto-trading is OFF; no Alpaca requests, policy changes or automatic resends occurred.

The ModelDock **packaged runtime** at
`/Users/nikolai/Projects/ModelDock/dist/ModelDock.app/Contents/Resources/runtime/bin/python3.11`
also accepted the exact saved request schema and passed four authored response
cases: zero-theme and one-theme v3 responses validate, and literal/escaped duplicate
JSON keys are rejected. These checks load only its structured validator, not models
or the server. They are fixture compatibility evidence, not successful inference.
Initial probes of the repository venv and older `/Applications` runtime lacked
`jsonschema`; no dependency was installed. An initially uncited authored fixture
was correctly rejected, then corrected before the final four checks passed.

Final regression commands (HTTP fixtures need loopback permission):

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests .venv/bin/python3.11 - <<'PY'
import pathlib, unittest
modules = sorted(p.stem for p in pathlib.Path('tests').glob('test_sentry*.py')
                 if p.stem != 'test_sentry_synthesis_service')
result = unittest.TextTestRunner(verbosity=1).run(
    unittest.defaultTestLoader.loadTestsFromNames(modules))
raise SystemExit(not result.wasSuccessful())
PY

PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests .venv/bin/python3.11 \
  -m unittest test_sentry_synthesis_service -q

PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests .venv/bin/python3.11 \
  -m unittest test_modeldock_delivery test_shadow_experiment \
  test_shadow_experiment_capture test_shadow_experiment_cli \
  test_shadow_experiment_reader test_shadow_station \
  test_shadow_station_collection test_shadow_station_macos -q

PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests .venv/bin/python3.11 \
  -m unittest test_shadow_historical_baseline test_shadow_historical_cli \
  test_shadow_historical_dashboard -q

PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python3.11 \
  -m blackpod_build_week.sentry_synthesis_service verify \
  --config output/blackpod-shadow-station/config.json
```

Final results: 557 non-service Sentry tests run, 555 passed and two optional
canonical-checkout checks skipped; 160 experiment/station/delivery tests passed;
62 historical-baseline/CLI/dashboard tests passed; all 100 final service tests
passed. **879 tests run: 877 passed, two skipped.** An initial sandbox-only run
could not bind fixture HTTP sockets; all affected cases passed with loopback
permission. No authored model fixture is
counted as a successful real model delivery.

The verified owned BlackPod LaunchAgent was gracefully reloaded at
`2026-10-17T21:07:28.989425Z` (PID 80141 → 13993). Auto-trading remained OFF.
The ModelDock service was not restarted. Browser visual inspection is not claimed;
renderer/HTTP fixture tests establish the labels and escaped output, while local
read-only JSON checks establish which report the native app serves.
`/status.json` and `/sentry-synthesis.json` both returned HTTP 200 with
`Cache-Control: no-store`; the station was RUNNING/OFF and synthesis served the
exact new failed child, with `ORACLE_NOT_ACCEPTED` for the unstarted challenge.
Deployment and endpoint metadata are retained beside the before/after records
as `deployment.json` and `http-checks.json`.

The reload used only the verified owned agent:

```bash
/bin/launchctl kill SIGTERM gui/501/com.blackpod.shadow-station
```

## Files and remaining work

- `contracts/sentry_synthesis.py`, `sentry_synthesis_transport.py`: versioned keyed
  Oracle contract, original-draft challenge binding, frozen legacy wire behavior.
- `sentry_synthesis.py`, `sentry_synthesis_service.py`: explicit immutable validation
  linkage/CLI, receipt-bound diagnostics, fail-closed challenge-path checks and
  future background format selection.
- `sentry_synthesis_presentation.py`, `sentry_narrative_evaluation.py`: detached map
  display, truthful challenge status and original symbol-addressed claim paths.
- Seven Sentry test modules cover contracts, transport, service, saved-packet
  validation/recovery, presentation, HTTP and narrative evaluation. README and
  the synthesis guide link this record.

Recommended next step: restore ModelDock availability and explicitly authorize a
separately identified delivery check before evaluating the resulting narrative.
This burst does not retry the retained failed child or claim empirical resolution
of the duplicate-symbol failure. No new experiment, trade, allocation or rule is
authorized by format validation.
