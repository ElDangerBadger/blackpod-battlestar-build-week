# Burst 9 implementation and validation — October 12, 2026

**Fresh real forecasts now reach governed intake and Brigade SHADOW analysis.**
SPY and QQQ supplied 760 daily bars each. The isolated native producer fitted
30 quantile models and emitted ten raw, ordered, positive forecast rows. All ten
passed intake. Ten local ModelDock calls completed with retained receipts.
Sentry produced an advisory BUY for each symbol; eight other text responses
failed the native label contract and remain DEFER. Separate Decay calculations
returned HOLD. No model response became authorization or an order.

**Auto-trading is verified OFF.** No orders, capital transfers, ownership
installation, budget activation, policy changes, database changes or new
dependencies occurred. ModelDock's existing model/configuration and all
canonical mission, stage and Navigator behavior were preserved.

## Files changed

New implementation:

- `src/blackpod_build_week/contracts/forecast_producer.py`
- `src/blackpod_build_week/shadow_quantitative_producer.py`
- `src/blackpod_build_week/forecast_producer_export.py`
- `src/blackpod_build_week/forecast_producer_journal.py`
- `src/blackpod_build_week/forecast_producer_cli.py`
- `src/blackpod_build_week/forecast_producer_example.py`

Existing passive interfaces extended:

- `contracts/decision_journal.py`: additive v10 producer-export envelope.
- `decision_journal_store.py`: complete source/model export replay on append/read.
- `forecast_intake.py`: additive observation proof v2 for actual feature
  precision and v3 for actual per-horizon training datasets; prior v1 behavior
  and admission policy remain unchanged.

New tests: `test_shadow_quantitative_producer.py`,
`test_forecast_producer_contracts.py`, `test_forecast_producer_export.py`,
`test_forecast_producer_journal.py`, `test_forecast_producer_cli.py`,
`test_forecast_producer_examples.py` under `tests/`.

New fixtures under `fixtures/shadow_quantitative_producer/` retain reviewed
native source code and actual-fitted synthetic data. The example prepares
immutable inputs without test imports, fitting or provider calls.

Documentation: new `docs/GOVERNED_FORECAST_EXPORT.md` and this report;
append-only additions to `README.md`, `docs/ARCHITECTURE.md`,
`docs/SAFETY_BOUNDARY.md`. Real evidence, models, inference captures and HTML
reports remain in ignored `output/` directories. Neither sibling repository
was edited. No commit or PR was created.

## Actual offline results

**1,538 unique selected tests passed: 128 new tests and 1,410 regressions.**
Development reruns are not counted twice.

| Final group | Tests | Result | Duration |
| --- | ---: | --- | ---: |
| New producer/contracts/export/journal/CLI/examples | 128 | PASS | 43.448 s |
| Existing forecast intake and Brigade shadow | 218 | PASS | 21.423 s |
| Existing two-desk/Spyglass/native review | 233 | PASS | 98.925 s |
| Existing accounting and budget | 164 | PASS | 22.920 s |
| Existing journal/hypotheses/outcome review | 249 | PASS | 17.662 s |
| Existing investment governance/approval | 125 | PASS | 75.066 s |
| Existing reconciliation/runtime/paper probes | 249 | PASS | 27.850 s |
| Existing missions/Navigator/operator/ModelDock | 172 | PASS | 1.645 s |

New counts: 32 native producer, 14 contracts, 33 export, 16 journal,
23 CLI/lifecycle and 10 examples. Exact new and immediately adjacent commands:

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests .venv/bin/python3.11 -m unittest \
  test_shadow_quantitative_producer test_forecast_producer_contracts \
  test_forecast_producer_export test_forecast_producer_examples \
  test_forecast_producer_journal test_forecast_producer_cli -q

PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests .venv/bin/python3.11 -m unittest \
  test_forecast_intake_contracts test_forecast_intake_engine \
  test_shadow_brigade_analysis test_forecast_brigade_journal_contracts \
  test_forecast_brigade_store test_brigade_shadow_transport \
  test_forecast_brigade_cli test_forecast_brigade_examples -q

PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests .venv/bin/python3.11 -m unittest \
  test_shadow_native_analysis test_desk_candidate_review_contracts \
  test_desk_candidate_review_engine test_shadow_galactica_analysis \
  test_desk_candidate_review_store test_desk_candidate_review_cli \
  test_desk_review_sources test_desk_candidate_review_examples -q

git diff --check
```

The five remaining regression commands are exactly the accounting, journal,
investment governance, paper/runtime and mission/ModelDock commands listed in
[Burst 8 validation](FORECAST_BRIGADE_SHADOW_VALIDATION.md#actual-offline-results).
They were rerun in this burst; their actual results are in the table above.

Tests cover source pins, calendar/DST/early-close binding, completed-session
selection, exact native feature and target preparation, actual label
availability, model coefficients and parameters, raw crossings, data-only
replay, full source closure, mixed v1–v10 journals, semantic tampering even
after rehashing, immutable retries, interrupted separate journal commits,
output isolation, explicit runtime selection and concurrent production.
FIFO/symlink/external-hardlink locks are rejected. Retried captures do not
refit, and unsafe or existing unclaimed outputs fail before worker startup.

Offline tests use retained actual-fitted synthetic models and mocks. They do
not contact providers, run broker execution or establish predictive returns.
The separate real exercise below used real fitting and actual local inference.

## Real source, runtime and model evidence

Three fixed GET-only Alpaca requests returned HTTP 200:

- `data.alpaca.markets/v2/stocks/snapshots`: SPY/QQQ, IEX.
- `data.alpaca.markets/v2/stocks/bars`: 1Day, RAW, IEX, ascending,
  October 1, 2023 through the actual capture, limit 10,000, no pagination token.
- `paper-api.alpaca.markets/v2/calendar`: October 1, 2023 through
  October 30, 2026; 774 returned sessions.

Market capture ended `2026-10-12T22:36:43.550499Z` (3:36 p.m. Pacific).
Raw snapshots SHA `a0d40e54f5a81dc7de43ca3acc64135c60f306a9ef5e17581cffc9ef7bae2cab`;
raw bars SHA `b5e74b1543238e18274092378cd6935a9ef4887152b54a8c764e4cae63e79d36`;
raw calendar SHA `00da55ff43922b8cb07b9a7b951a436417a8ab7b65c406dca24635e43d1982e3`.
Credentials were reused in memory from the already-confirmed local YAML source;
they were not printed, copied, changed or retained in evidence.

The existing Galactica interpreter supplied Python 3.11.14, pandas 2.3.1,
NumPy 2.4.2, scikit-learn 1.8.0 and SciPy 1.17.0. No installation occurred.
The reviewed native feature/model definitions use linear quantile defaults,
alpha 0, a 252-row window, quantile labels .10/.50/.90 and horizons one to five.
This is an explicit shadow use of source defaults, not a claim about ambient
Galactica deployment environment settings. Native cache, joblib loading,
directory initialization and persistence functions were excluded.

The governed production run started `2026-10-12T22:55:05.999135Z`, completed
and issued `2026-10-12T22:55:07.995135Z`. It fitted 30 actual models with
251/250/249/248/247 training samples by horizon. The latest feature availability
is the actual captured OHLCV receipt. Reference prices and historical training
label event times use returned regular-session closes. Historical point-in-time
revisions/final volume completeness are not authenticated. Daily OHLC update
rules differ from volume rules. [Alpaca aggregation documentation](https://docs.alpaca.markets/us/docs/market-data-faq).

All ten raw quantile triplets were positive and ordered; **10 admitted,
0 deferred**. Each symbol has one source/model family, with all fifteen
distinct per-horizon/quantile model identities, coefficients, actual training
rows and label times retained. Native sorted preview is separate evidence,
never a repair that changes governed quantile identity. No parameter tuning
was performed to manufacture admission.

An initial exploratory native worker run preceded the governed request.
During integration, a calendar preflight rejected actual auxiliary `0400`/
`2000` time fields; support was corrected and tested. A subsequent CPU attempt
failed because resolving the virtualenv launcher discarded its library prefix.
Its consumed attempt and failure fingerprint were preserved. The corrected
invocation used a new explicit run identity and the declared launcher, hashing
the resolved binary separately. Other repaired issues include strict receipt
counts/timing, unchecked request-reference reads and first-writer directory/
lock races. Final tests above cover these fixes.

## Actual Brigade and ModelDock results

The documented existing appliance at `http://127.0.0.1:8000` returned HTTP 200
for health/stats: READY, MLX, Qwen3-1.7B-4bit, zero active requests/compute.
No service/model start, selection or configuration change occurred.

SPY made five bounded local text requests from `22:56:34.317678Z` through
`22:56:51.836446Z`; QQQ made five from `22:58:18.675551Z` through
`22:58:36.468935Z`. All ten captured validated service envelopes and completed
receipts; there are zero missing local receipts. Final stats returned READY,
zero active requests/compute, the same model and requests-served 11 versus
the pre-run 1, consistent with ten calls.

For **each symbol**, only Sentry's native text labels passed: advisory BUY,
heuristic confidence `0.8`. Scout, Advisor, Canary and Pathfinder responses
failed `RESPONSE_LABELS_MISSING_OR_DUPLICATED`; their original content remains
retained and no vote was fabricated. No retries were used to force a valid
opinion. Separate actual Decay returned HOLD. Agreement between two Sentry
responses is not independent evidence or trading authorization.

Brigade context v1 intentionally excludes same-UTC-day bars. Its observed-price
context therefore ends Friday, October 9, while forecast features use Monday,
October 12. That mismatch is explicit. Existing v1 replay behavior was preserved,
and neither the daily forecast nor local narratives installed desk ownership,
changed investment theses or bypassed trading risk controls.

## Executed production and audit commands

The GET-only capture used the temporary script
`/private/tmp/blackpod_burst9_readonly_capture.py`. The supported production
and append commands actually executed were:

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python3.11 \
  -m blackpod_build_week.forecast_producer_cli produce \
  --request output/auto-trading-forecast-producer-source/request.002.json \
  --evidence-root output/auto-trading-forecast-producer-source \
  --output-directory output/auto-trading-forecast-producer-real-002 \
  --python-executable /Users/nikolai/BlackPod-Versions/blackpod_galactica/galactica/bin/python

PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python3.11 \
  -m blackpod_build_week.forecast_producer_cli record \
  --export output/auto-trading-forecast-producer-real-002/export.json \
  --evidence-root output/auto-trading-forecast-producer-real-002/evidence \
  --journal-root output/auto-trading-forecast-producer-real-journal

# Actual local inference: repeated once for QQQ using its request and output root.
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python3.11 \
  -m blackpod_build_week.brigade_shadow_cli generate \
  --journal-root output/auto-trading-forecast-producer-real-journal \
  --request output/auto-trading-forecast-producer-brigade-source/SPY.request.json \
  --evidence-root output/auto-trading-forecast-producer-brigade-source \
  --output-directory output/auto-trading-forecast-producer-brigade-spy \
  --modeldock-shadow --modeldock-base-url http://127.0.0.1:8000 \
  --modeldock-timeout-seconds 30 --modeldock-delivery-grace-seconds 5

PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python3.11 \
  -m blackpod_build_week.brigade_shadow_cli record \
  --journal-root output/auto-trading-forecast-producer-real-journal \
  --request output/auto-trading-forecast-producer-brigade-spy/request.replay.json \
  --evidence-root output/auto-trading-forecast-producer-brigade-spy/evidence

PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python3.11 \
  -m blackpod_build_week.brigade_shadow_cli record \
  --journal-root output/auto-trading-forecast-producer-real-journal \
  --request output/auto-trading-forecast-producer-brigade-qqq/request.replay.json \
  --evidence-root output/auto-trading-forecast-producer-brigade-qqq/evidence

PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python3.11 \
  -m blackpod_build_week.decision_journal_cli verify \
  --journal-root output/auto-trading-forecast-producer-real-journal

PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python3.11 \
  -m blackpod_build_week.auto_trading_cli status \
  --runtime-root output/auto-trading-runtime
```

Re-executing `produce` reused the retained capture with **zero new fits**.
Re-executing `record` returned both producer/intake `written=false`.
The real journal verifies **4 events / 60 blobs / zero orphans**, chain hash
`6f614a0cf91d5285190426eb40a2c21046c0a89270f410132358585b0a189508`.
All nine older verified journals retained their hashes and zero orphans.

The actual model result SHA is
`eef95cda1c8a9c602a09d06cbfde93907f8e323df88656911d54f7fabb564d8d`.
The human report is `output/auto-trading-forecast-producer-real-report/review.html`,
SHA `8f94304edbe4773fadc3198a26fb58c286b14c58b516de61ad6157fbc93a007e`.
The report passed isolated browser checks at mobile 390×844: no browser errors
or document overflow, ten forecast rows, twelve member-coverage rows and
authority OFF. Desktop 1360×1000 and mobile screenshots were visually inspected
under `output/playwright/blackpod-forecast-producer/`.
The runnable offline example and exact no-fit commands are in
[the usage guide](GOVERNED_FORECAST_EXPORT.md); its fixture journal verifies
two events, 33 blobs, zero orphans, with two admitted and three crossed rows.

A SHA-256 baseline verified **1,183 protected pre-existing files unchanged**.
The authorized additive intake proof parser was accounted for separately.
ModelDock code/configuration, canonical missions, original journal evidence,
execution code, profiles and inactive budgets were preserved. Final runtime
readback is OFF, entries/requested entries false, worker inactive, auto-restart
false and capital transfers false. `git diff --check` passed.

## Remaining limits and one recommended next burst

Successful fitting/admission does not establish quantile calibration, predictive
advantage or positive net returns. Replay verifies source, features, targets and
coefficient predictions without refitting; it does not prove optimizer
optimality. IEX/RAW bulk-history revisions, venue liquidity, human review and
producer identity are not authenticated. These daily horizons are TRADING
research and cannot silently become a long-horizon investment thesis.

**Recommended next burst: versioned structured Brigade response contracts.**
Preserve the native prompts and original responses, require typed action,
heuristic confidence and reasoning fields at the local inference boundary,
then deterministically validate/project them without relaxing malformed-output
deferral or granting execution authority. Complete it with real local-provider
receipts, preserved dissent and verified zero execution effects. Separately
tracked context alignment and append-only forecast outcome evaluation remain
necessary before any trading-performance claim. This next burst has not been
implemented.
