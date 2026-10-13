# Burst 8 implementation and validation — October 12, 2026

Implemented governed forecast intake, source-pinned native Brigade SHADOW
analysis, separate actual Decay observations, retained-response replay, passive
journal v9 records, explicit local ModelDock capture/recovery, runnable offline
examples and a human review artifact. **Auto-trading is verified OFF.**

No orders, capital transfers, allocation, ownership installation, policy
activation, quantitative model loading/training, actual ModelDock inference or
other provider calls occurred in this burst. Existing ModelDock work,
configuration, canonical missions, stage workflows and Navigator were preserved.

## Files changed

Existing passive journal interfaces extended:

- `src/blackpod_build_week/contracts/decision_journal.py`: additive v9 forecast
  and Brigade events, preserving v1–v8 semantics.
- `src/blackpod_build_week/decision_journal_store.py`: retained-source projection
  and native-response replay on both append and verified reads.

New implementation:

- `src/blackpod_build_week/contracts/forecast_intake.py`
- `src/blackpod_build_week/forecast_intake.py`
- `src/blackpod_build_week/contracts/brigade_shadow.py`
- `src/blackpod_build_week/shadow_brigade_analysis.py`
- `src/blackpod_build_week/forecast_journal.py`
- `src/blackpod_build_week/forecast_intake_cli.py`
- `src/blackpod_build_week/brigade_shadow_cli.py`
- `src/blackpod_build_week/brigade_shadow_transport.py`
- `src/blackpod_build_week/forecast_brigade_example.py`

New tests:

- `tests/test_forecast_intake_contracts.py`
- `tests/test_forecast_intake_engine.py`
- `tests/test_shadow_brigade_analysis.py`
- `tests/test_forecast_brigade_journal_contracts.py`
- `tests/test_forecast_brigade_store.py`
- `tests/test_brigade_shadow_transport.py`
- `tests/test_forecast_brigade_cli.py`
- `tests/test_forecast_brigade_examples.py`

New retained source fixture: `fixtures/shadow_brigade_analysis/decay.py`.
The existing pinned Brigade source fixture is reused unchanged. The runnable
example prepares its source-bound synthetic data without importing test code.

Documentation: new `docs/FORECAST_BRIGADE_SHADOW.md` and this report; append-only
additions to `README.md`, `docs/ARCHITECTURE.md`, `docs/SAFETY_BOUNDARY.md`.
One older example assertion in `tests/test_desk_candidate_review_examples.py`
was corrected to expect the already-existing scoped automation-authority label
and separate runtime-status statement. Its production renderer did not change.

Private real-source captures, journals, examples and reports are in ignored
`output/` directories. Neither sibling repository was edited. No dependency,
database migration, commit, PR, broker adapter or execution controller change
was introduced.

## Actual offline results

**1,410 unique selected tests passed: 218 new tests and 1,192 regressions.**
Repeated development runs are not counted again.

| Final group | Tests | Result | Duration |
| --- | ---: | --- | ---: |
| New forecast/Brigade contracts, engine, journal, transport, CLI and examples | 218 | PASS | 14.516 s |
| Existing two-desk review, Spyglass, native adapters and examples | 233 | PASS | 85.281 s |
| Existing accounting and budget | 164 | PASS | 22.307 s |
| Existing journal, hypotheses and outcome review | 249 | PASS | 17.576 s |
| Existing investment governance and approval | 125 | PASS | 72.336 s |
| Existing reconciliation, runtime, adapter and paper probes | 249 | PASS | 26.788 s |
| Existing missions, Navigator, operator and ModelDock | 172 | PASS | 1.577 s |

New counts: 26 intake contracts, 45 intake engine, 34 native Brigade adapter,
16 journal/request contracts, 34 store, 36 transport, 15 CLI/presentation and
12 example tests.

Exact final test commands, using existing dependencies:

```sh
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

PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests .venv/bin/python3.11 -m unittest \
  test_trading_accounting_contracts test_paper_activity_import \
  test_trading_accounting_engine test_trading_accounting_store \
  test_trading_accounting_cli test_trading_accounting_examples -q

PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests .venv/bin/python3.11 -m unittest \
  test_decision_journal_contracts test_decision_journal_projection \
  test_decision_journal_store test_decision_journal_cli \
  test_investment_hypothesis_contracts test_investment_hypothesis_sources \
  test_investment_hypothesis_store test_investment_hypothesis_examples \
  test_investment_hypothesis_cli test_investment_review_contracts \
  test_investment_review_engine test_investment_review_store \
  test_investment_review_cli -q

PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests .venv/bin/python3.11 -m unittest \
  test_investment_governance_contracts test_investment_governance_engine \
  test_investment_approval test_investment_governance_store \
  test_investment_governance_examples test_investment_governance_cli -q

PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests .venv/bin/python3.11 -m unittest \
  test_trading_reconciliation_contracts test_trading_reconciliation_engine \
  test_trading_reconciliation_store test_trading_receipts \
  test_trading_reconciliation_cli test_paper_account_safety \
  test_paper_order_capture test_trading_reconciliation_examples \
  test_auto_trading_runtime test_galactica_trading_adapter \
  test_trading_automation test_paper_account_probe -q

PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests .venv/bin/python3.11 -m unittest \
  test_contracts test_mission_store test_mission_transitions \
  test_mission_presentation test_cli_help test_navigator_adapter \
  test_operator_adapter test_modeldock_config test_modeldock_client \
  test_modeldock_preflight test_modeldock_delivery -q

git diff --check
```

The initial regression run caught the stale prior-burst label assertion. It was
corrected and the entire 233-test group rerun successfully. Independent review
also caught response expiry during inference, unsafe retained provenance types,
incomplete capture verification and receipt-gap handling; fixes and acceptance
tests passed before the final results above.

## Contracts, replay and recovery coverage

Intake retains original CSV/JSON rows and date precision. It requires explicit
USD predicted-close semantics, ordered positive Q10/Q50/Q90, source/model/config
bindings, reviewed metadata, feature observations, training-label availability
and target-session evidence. Unsupported or missing information remains null
and produces DEFER; there is no crossing repair, inferred midnight, invented
issue time, reconstructed lost horizon or model execution. Proof parsing is
cached within one assessment to avoid repeatedly scanning shared large evidence.

The one-to-five-session interface belongs to short-horizon TRADING research.
INVESTMENT imports retain their evidence but defer as insufficient for a
long-horizon thesis. An admitted row is eligible at its frozen intake clock;
member coverage separately enforces generation-time freshness and target expiry.

The five existing native agent methods are loaded from a fixed reviewed AST
closure. Legacy Watchtower, implicit CSV lookup, provider imports and trade-plan
construction are excluded. Observed history drives trend/regime/volume context;
Pathfinder's future predicted path is explicitly distinguished from elapsed
history. Actual `Blackwell_Decay` runs separately on observed closes. None of
these outputs is an authorization, executable order or calibrated probability.

Tests establish exact linked source identities, mixed v1–v9 chains, immutable
originals, source removal/replay, idempotent retries, conflicts, concurrent
append-once behavior, fsync/publication interruption, orphan staging/evidence,
safe internal links and rejection of external links. Rehashed forecasts,
native context, opinions, dissent, prompts, source pins and bundle bindings
cannot bypass semantic replay.

Optional ModelDock capture is explicit, local-only and bounded to 40 member
calls and 300 seconds. It preserves native prompts while asking for the single
`brigade_text` JSON field. The appliance owns model selection and sampling;
the requested native temperature is retained but not transmitted as an override.
Its transport mode LIVE denotes real text inference, while the desk remains
SHADOW with every authority false.

Transport tests use the actual preserved `ModelDockClient` over in-memory fake
HTTP responses. They exercise native completion/token/correlation validation,
malformed or truncated content, failure sanitization, unsafe model/trace/revision
tokens, no fallback, and expiry before and after a response. Valid but expired
provider text remains retained and cannot contribute a recommendation.

Durable generation and per-call intents precede POSTs. Individual receipts and
an immutable completion clock support recovery after each publication boundary.
A consumed/interrupted attempt cannot silently infer again. Recovery performs
zero new calls, validates saved receipts, rejects unknown/gapped state and
defers uncaptured members. `durable_call_intent_count`, `retained_receipt_count`
and `unconfirmed_call_count` distinguish local reservations and missing receipts;
they do not prove that provider computation stopped after a timeout. The
provider's delivery diagnostics retain that separate uncertainty.

## Real sources versus fixtures

Reconnaissance inspected all **154** Galactica forecast CSVs. Their newest
source date is **June 10, 2026**. No October 12 forecast was found. Galactica
phase 2 supplies Date/Symbol/Q10/Q50/Q90/Pattern/Timeframe/Horizon; Date is a
feature anchor, not an issue-time attestation. Phase 3 drops Horizon, which
cannot safely be recovered from row order. Legacy evaluation logs measure
historical forecast errors, not attributable fills, fees or realized trade P&L.

The real negative exercise retains
`Galactica/forecasts/SPY_1d_forecast.csv`, SHA-256
`ace5d2137b005ca10986c29a9b374d2150259ecaebbe19eafcebc3e6c67ddb3f`.
Its five June-dated rows have missing source-bound provenance, issue/feature/
training/target times, units/semantics and target-session proof. Nothing was
filled in retrospectively. **Zero rows were admitted; five were deferred.**

Using the previously retained October 12 market packet, all five text members
deferred without producing invented votes. Actual Decay computed an observed
SPY HOLD indication; its confidence remains heuristic and there was no usable
separate benchmark. Canary's unavailable-volume reason refers to the absent
combined forecast context, rather than absence of raw market volume.

The intake was recorded at `2026-10-12T21:39:13.552971Z` and the disabled
analysis at `2026-10-12T21:39:13.561700Z` (2:39 p.m. Pacific). An explicit
generate command was exercised against those inputs: it stopped at preflight,
returned `DEFER_NO_CURRENT_ELIGIBLE_MEMBERS`, and made **zero inference calls**.
No credentials were read and no account/market/provider requests were made.
The existing ModelDock endpoint/timeout environment was unconfigured.

All positive eligibility, live-transport-envelope and captured-opinion tests
use synthetic forecasts/proofs/market data and authored responses, with the
actual pinned native analytical code. The runnable example has three synthetic
eligible horizons, five disabled-member deferrals, then five declared advisory
responses with BUY/EXIT/HOLD/WATCH/HOLD dissent. It verifies **3 events,
17 blobs, zero orphans**. This establishes interfaces and audit behavior,
not predictive performance, actual inference, net returns or paper fills.

## Executed real-evidence commands

The original CSV, code and earlier frozen market packet were copied with the
existing guarded immutable writer into a separate evidence root. The intake
was recorded with the pure `build_forecast_intake_event` / `JournalStore.append`
APIs. Subsequent actual CLI commands were:

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python3.11 \
  -m blackpod_build_week.brigade_shadow_cli record \
  --journal-root output/auto-trading-forecast-brigade-real-journal \
  --request output/auto-trading-forecast-brigade-real-source/request.disabled.json \
  --evidence-root output/auto-trading-forecast-brigade-real-source

# Retained-only exact retry: written=false, sequence 2.
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python3.11 \
  -m blackpod_build_week.brigade_shadow_cli record \
  --journal-root output/auto-trading-forecast-brigade-real-journal \
  --request output/auto-trading-forecast-brigade-real-source/request.disabled.json

PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python3.11 \
  -m blackpod_build_week.brigade_shadow_cli generate \
  --journal-root output/auto-trading-forecast-brigade-real-journal \
  --request output/auto-trading-forecast-brigade-real-source/request.disabled.json \
  --evidence-root output/auto-trading-forecast-brigade-real-source \
  --output-directory output/auto-trading-forecast-brigade-real-deferred \
  --modeldock-shadow

PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python3.11 \
  -m blackpod_build_week.brigade_shadow_cli render \
  --journal-root output/auto-trading-forecast-brigade-real-journal \
  --event-id journal-event-aeff7b0514184050bf079d64bbd9ff1d34f4727620f63cbaf37dc44246499a88 \
  --output output/auto-trading-forecast-brigade-real-report/review.html

PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python3.11 \
  -m blackpod_build_week.decision_journal_cli verify \
  --journal-root output/auto-trading-forecast-brigade-real-journal

PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python3.11 \
  -m blackpod_build_week.auto_trading_cli status \
  --runtime-root output/auto-trading-runtime
```

The real journal verifies **2 events / 8 blobs / zero orphans**, chain hash
`5781efdf5548d55913892104379c90c5d57fd3bca69dcaf4c83618ebd62ea659`.
The exact retry preserves its identity and original bytes. All eight older
verified journals retained their original chain hashes and zero orphans.
The report HTML has SHA-256
`e4609dc07752b7492004437e4d036f84a0f37a61bac7d5e433bbdec122be2cbd`.

A source/evidence baseline verified **1,155 pre-existing files unchanged**,
including ModelDock, mission and execution code, UI, original source fixtures,
budget/profile/runtime records and older journal evidence. The authorized old
test assertion correction and the new forecast contract captured while under
construction were accounted for separately. `git diff --check` passed.

Headless rendering used existing bundled Playwright and installed Chrome on
local HTML, with page requests blocked. Desktop and 390-pixel mobile layout
passed with zero browser errors and no document overflow; missing historical
units remain explicitly unverified. Screenshots are under
`output/playwright/blackpod-forecast-brigade/`. No package was installed.

Final runtime readback: `state=OFF`, `entries_enabled=false`,
`requested_entries_enabled=false`, `worker_active=false`,
`auto_restart_enabled=false`, `capital_transfers_permitted=false`.
Existing fixed test budgets remain inactive and unchanged.

## Remaining limits and one recommended next burst

There is no admitted real current forecast, real ModelDock smoke test,
calibrated band coverage, independent fundamental thesis or demonstrated
profitable desk. Source review and calendar labels are declarations, not
identity authentication or proof of training correctness. The fixed 24-hour
issue/feature/training gate is deliberately conservative and can defer valid
weekend or older-trained-model inputs. It is a shadow admission policy, not a
change to live trading or investing rules. Inference and review remain explicit
commands separate from canonical stages and execution.

**Recommended next burst: governed forecast-producer export.** Extend the
existing quantitative producer seam to emit its actual current input hashes,
feature/training-label availability, per-horizon/model/config identities,
target-session evidence and issue timestamps alongside its original forecasts.
Validate a current output through this intake and shadow Brigade path while
keeping automation OFF. Completion requires a reproducible real source-bound
export, zero-lookahead proof, explicit missing/unsupported-data deferral and no
ownership, sizing, allocation or execution side effects. This next burst has
not been implemented.
