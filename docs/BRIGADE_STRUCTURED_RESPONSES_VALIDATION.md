# Burst 10 implementation and validation — October 12, 2026

**Versioned structured Brigade responses are implemented and exercised against
the existing local ModelDock appliance. Auto-trading remains OFF.**

The real SPY/QQQ exercise captured ten responses with ten valid typed contracts,
compared with two valid native text-label responses in Burst 9. SPY has five
advisory BUY recommendations. QQQ has four BUY recommendations and Canary HOLD;
that dissent is retained. Separate native Decay returns HOLD for both.
Contract acceptance validates fields and identity, not economic truth,
confidence calibration, rule consistency, investment value or trading approval.

No orders, broker calls, capital movements, activated budgets, installed
ownership, live policies, native source, canonical mission/stage/Navigator
behavior, ModelDock code/configuration, dependencies or additional agents
were changed by this burst. No quantitative fitting or market refresh occurred.
The real review uses the retained October 12 forecasts from Burst 9.

## Files changed

New implementation:

- `src/blackpod_build_week/contracts/brigade_response.py`
- `src/blackpod_build_week/brigade_structured_example.py`

Additive passive interfaces:

- `contracts/brigade_shadow.py`: explicit request v2 and response contract;
  original request v1 remains supported.
- `shadow_brigade_analysis.py`: analysis v2, strict JSON-to-native projection,
  raw/mapped/projected/parser evidence kept separately, no invalid fallback vote.
- `forecast_journal.py`: request-version projection and v11 Brigade records.
- `contracts/decision_journal.py`: additive v11 envelope; v9 stays v1-specific.
- `brigade_shadow_transport.py`: per-member constrained output, transcript
  and attempt v2, original JSON retention, strict source-bound replay and
  oversized-original-content deferral.
- `brigade_shadow_cli.py`: version-aware passive reports with escaped original
  structured response evidence. Existing commands select versions from their
  strict request documents; no new automatic inference path is introduced.

New tests under `tests/`:

- `test_brigade_response_contracts.py`: 71.
- `test_brigade_structured_analysis.py`: 22.
- `test_brigade_structured_journal.py`: 18.
- `test_brigade_structured_transport.py`: 16.
- `test_brigade_structured_examples.py`: 13.
- `test_brigade_structured_cli.py`: 4.

Documentation: new `docs/BRIGADE_STRUCTURED_RESPONSES.md`, this validation
report, and append-only README, architecture and safety-boundary additions.
Real captures, synthetic CLI output, human HTML and screenshots remain under
ignored `output/`. Existing unrelated changes, particularly ModelDock work,
were preserved. Neither sibling repository was edited. No commit or PR was
created.

## Strict semantics and reproducibility

The member contract has exactly six fields: schema version, member, symbol,
action, numeric heuristic confidence and nonblank bounded single-line reasoning.
Only native BUY/EXIT/HOLD/WATCH actions are supported. Per-request JSON schemas
bind identities with constants; unknown authority, order and allocation fields
reject. Confidence strings/booleans, out-of-bounds exact JSON numeric literals,
nonfinite numbers, malformed/duplicate/fenced JSON, control characters and
legacy `brigade_text` fallback reject. No output repair or policy threshold
adjustment occurs.

The original native system/user prompt bodies, model-owned routing/sampling,
500-token native budget and suppressed trade-plan builder are preserved.
The wrapper changes only response representation and repeats the shadow
interpretation limits. Valid content projects into exactly three native labels;
invalid content contributes no recommendation, even when the native parser
returns a fallback HOLD.

Transport validation and advisory validation are distinct. A validated local
MLX envelope may retain a well-formed but semantically invalid object; the
independently replayed member contract defers it. Original safe-response JSON
is retained verbatim, including decimal literals. An original response over
32 KiB cannot become a vote through whitespace compaction; v2 records it as
VALIDATED_REJECTED with disabled authority. Envelope/syntax failures retain
sanitized diagnostics plus hashes/sizes, not arbitrary malformed provider bodies.

Completed retry and interrupted recovery retain their existing no-inference
semantics. Version mixing, altered inputs, replay tampering and reused analysis
identities conflict. The new journal uses the existing immutable storage;
it does not change source mission storage or live orchestration.

## Actual offline results

**1,682 unique selected tests passed: 144 new plus 1,538 regressions.**
Development reruns are not counted twice.

| Final group | Tests | Result | Duration |
| --- | ---: | --- | ---: |
| New structured contracts/analysis/journal/transport/examples/CLI | 144 | PASS | 6.210 s |
| Existing forecast producer | 128 | PASS | 48.825 s |
| Existing forecast intake and Brigade | 218 | PASS | 25.388 s |
| Existing two-desk/native/Spyglass review | 233 | PASS | 104.619 s |
| Existing accounting | 164 | PASS | 26.569 s |
| Existing journal/hypotheses/review | 249 | PASS | 19.936 s |
| Existing investment governance | 125 | PASS | 80.136 s |
| Existing paper/runtime/reconciliation | 249 | PASS | 32.339 s |
| Existing mission/operator/Navigator/ModelDock | 172 | PASS | 1.833 s |

Exact final test commands:

```sh
# accounting
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests .venv/bin/python3.11 -m unittest \
  test_trading_accounting_contracts \
  test_paper_activity_import \
  test_trading_accounting_engine \
  test_trading_accounting_store \
  test_trading_accounting_cli \
  test_trading_accounting_examples -q

# journal
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests .venv/bin/python3.11 -m unittest \
  test_decision_journal_contracts \
  test_decision_journal_projection \
  test_decision_journal_store \
  test_decision_journal_cli \
  test_investment_hypothesis_contracts \
  test_investment_hypothesis_sources \
  test_investment_hypothesis_store \
  test_investment_hypothesis_examples \
  test_investment_hypothesis_cli \
  test_investment_review_contracts \
  test_investment_review_engine \
  test_investment_review_store \
  test_investment_review_cli -q

# governance
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests .venv/bin/python3.11 -m unittest \
  test_investment_governance_contracts \
  test_investment_governance_engine \
  test_investment_approval \
  test_investment_governance_store \
  test_investment_governance_examples \
  test_investment_governance_cli -q

# paper
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests .venv/bin/python3.11 -m unittest \
  test_trading_reconciliation_contracts \
  test_trading_reconciliation_engine \
  test_trading_reconciliation_store \
  test_trading_receipts \
  test_trading_reconciliation_cli \
  test_paper_account_safety \
  test_paper_order_capture \
  test_trading_reconciliation_examples \
  test_auto_trading_runtime \
  test_galactica_trading_adapter \
  test_trading_automation \
  test_paper_account_probe -q

# workflow
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests .venv/bin/python3.11 -m unittest \
  test_contracts \
  test_mission_store \
  test_mission_transitions \
  test_mission_presentation \
  test_cli_help \
  test_navigator_adapter \
  test_operator_adapter \
  test_modeldock_config \
  test_modeldock_client \
  test_modeldock_preflight \
  test_modeldock_delivery -q

# shadow7
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests .venv/bin/python3.11 -m unittest \
  test_shadow_native_analysis \
  test_desk_candidate_review_contracts \
  test_desk_candidate_review_engine \
  test_shadow_galactica_analysis \
  test_desk_candidate_review_store \
  test_desk_candidate_review_cli \
  test_desk_review_sources \
  test_desk_candidate_review_examples -q

# forecast8
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests .venv/bin/python3.11 -m unittest \
  test_forecast_intake_contracts \
  test_forecast_intake_engine \
  test_shadow_brigade_analysis \
  test_forecast_brigade_journal_contracts \
  test_forecast_brigade_store \
  test_brigade_shadow_transport \
  test_forecast_brigade_cli \
  test_forecast_brigade_examples -q

# producer9
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests .venv/bin/python3.11 -m unittest \
  test_shadow_quantitative_producer \
  test_forecast_producer_contracts \
  test_forecast_producer_export \
  test_forecast_producer_examples \
  test_forecast_producer_journal \
  test_forecast_producer_cli -q

# structured10
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests .venv/bin/python3.11 -m unittest \
  test_brigade_response_contracts \
  test_brigade_structured_analysis \
  test_brigade_structured_journal \
  test_brigade_structured_transport \
  test_brigade_structured_examples \
  test_brigade_structured_cli -q
```

Offline tests use authored structured views and retained source/fitted fixtures.
They block real sockets, subprocess inference and execution. They verify
malformed deferral, missing/null/invalid UTF-8 responses, confidence literal
bounds, original native parser round trips, dissent, source version mixing,
semantic tampering after rehashing, journal immutability, durable receipts,
no-call retries/recovery, safe reports and runnable examples.

During integration, new temporary test roots initially retained macOS's
`/var` symlink; resolving the fixture root fixed the test path without relaxing
production guards. A report test correctly rejected a destination whose
parent contained the journal; the test and new runbook now use a separate
report directory. No safety check was removed to pass either case.

## Actual local-provider exercise

Status-only health/stats GETs at approximately 23:39:32Z returned HTTP 200.
ModelDock was READY with Qwen3-1.7B-4bit, zero active requests/compute and
requests-served 11. The real review reused the already verified Burst 9
producer/intake events in a separate journal, with new explicit v2 analysis
identities. The market capture is `2026-10-12T22:36:43.550499Z`; forecast
issuance is `2026-10-12T22:55:07.995135Z`. No fresh-data receipt was fabricated.

The native member/source and actual local provider provenance were retained:

| Symbol | First request start | Last response observed | Valid typed views | Dissent |
| --- | --- | --- | ---: | --- |
| SPY | 23:41:42.657933Z | 23:42:06.285089Z | 5 / 5 | Five BUY views |
| QQQ | 23:42:33.445512Z | 23:42:55.746032Z | 5 / 5 | Canary HOLD; four BUY |

Each symbol has five durable call intents, five retained receipts and zero
unconfirmed calls. There were no inference retries. The final status GET at
23:44:58Z returned READY, the same model, zero active requests/compute and
requests-served 21, consistent with ten calls. No service or model was started,
switched or reconfigured. Transport LIVE identifies actual local text calls;
all desk mode and authority remain SHADOW/disabled.

Contract success does **not** validate the narrative. QQQ Canary's retained
reasoning says volume was unavailable, while retained context has
`volume_available=true` and `volume_ratio=0.5773121082189099`.
SPY Pathfinder describes a falling path at range position 0% as near
resistance; its retained native supporting data are Position_In_Range 0.0 and
Price_Direction FALLING. These views remain visible as model interpretations,
not verified economic facts. This burst does not invent a replacement vote or
quietly install new trading criteria to correct them.

Existing observed context v1 still excludes same-UTC-day bars. Observed
technical/Decay history ends October 9 while forecast features use October 12.
The interface also retains Pathfinder's distinction between predicted future
targets and elapsed observed periods. These context limits remain unresolved.

## Executed production, replay and audit commands

A temporary data-only script
`/private/tmp/blackpod_burst10_real_prepare.py` copied the verified original
producer/intake event evidence into the separate research journal and prepared
new v2 SPY/QQQ requests. It called no providers or fitting code.
The following supported commands were executed once for each SYMBOL
(SPY/QQQ, corresponding lowercase output directory):

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python3.11 \
  -m blackpod_build_week.brigade_shadow_cli generate \
  --journal-root output/brigade-structured-real-journal \
  --request output/brigade-structured-real-source/SPY.request.json \
  --evidence-root output/auto-trading-forecast-producer-brigade-source \
  --output-directory output/brigade-structured-real-spy \
  --modeldock-shadow --modeldock-base-url http://127.0.0.1:8000 \
  --modeldock-timeout-seconds 30 --modeldock-delivery-grace-seconds 5

PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python3.11 \
  -m blackpod_build_week.brigade_shadow_cli generate \
  --journal-root output/brigade-structured-real-journal \
  --request output/brigade-structured-real-source/QQQ.request.json \
  --evidence-root output/auto-trading-forecast-producer-brigade-source \
  --output-directory output/brigade-structured-real-qqq \
  --modeldock-shadow --modeldock-base-url http://127.0.0.1:8000 \
  --modeldock-timeout-seconds 30 --modeldock-delivery-grace-seconds 5

PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python3.11 \
  -m blackpod_build_week.brigade_shadow_cli record \
  --journal-root output/brigade-structured-real-journal \
  --request output/brigade-structured-real-spy/request.replay.json \
  --evidence-root output/brigade-structured-real-spy/evidence

PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python3.11 \
  -m blackpod_build_week.brigade_shadow_cli record \
  --journal-root output/brigade-structured-real-journal \
  --request output/brigade-structured-real-qqq/request.replay.json \
  --evidence-root output/brigade-structured-real-qqq/evidence

PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python3.11 \
  -m blackpod_build_week.decision_journal_cli verify \
  --journal-root output/brigade-structured-real-journal

PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python3.11 \
  -m blackpod_build_week.auto_trading_cli status \
  --runtime-root output/auto-trading-runtime

git diff --check
```

Repeating the SPY generate command reused the exact completed capture with
**zero inference calls**. Repeating QQQ record returned `written=false`.
The journal verifies **4 events / 60 evidence blobs / zero evidence or staging
orphans**, final chain hash
`0ac604f7521ff6931f401c6fc1ca78f755fd25434b19218ac526fa4d076f37d4`.
The two new v11 event IDs are:

- SPY: `journal-event-93c12cef98ed85ba8594f8513a804312fb2fc954f7f6c115e6cef4c542ceca81`.
- QQQ: `journal-event-85a1bb88906ba4e82c24e6f614d3d60ddaa52bb2571e3656425ca920b6c346e0`.

The verified report renderer was run for each event into
`output/brigade-structured-real-report/spy.html` and `qqq.html`.
SHA-256 values respectively:
`a401db26f0840692fa631077dfc2dd7e64a7b30cce98ad0934b83d3eec1fb4d3`,
`1339e93100f7faea0c735e698f2721f5da9a62e57c93a14e61b46185ba5e49c6`.

Both reports passed isolated browser checks at 1360×1000 and 390×844:
no script errors or document overflow, ten source forecast rows, six coverage
rows including separate Decay, structured evidence and authority OFF.
Screenshots are under `output/playwright/brigade-structured/`; representative
desktop/mobile views were visually inspected. Browser network requests were
blocked and no existing user browser profile was used.

## Preservation and fixture coverage

All ten older retained journals were reverified with their original hashes and
zero orphans. Five pre-edit v1/v9 fixture digests matched byte-for-byte after
integration. A baseline verified **1,971 protected pre-existing files unchanged**.
One newly created contract happened to exist during baseline capture and was
accounted for separately as authorized new work. The additive files listed above
were explicitly excluded from the protected-file check.

The [runnable offline example](BRIGADE_STRUCTURED_RESPONSES.md#runnable-wholly-synthetic-example)
was actually prepared, assessed, recorded twice (disabled and authored replay),
and verified. Its journal has three events, 17 blobs and zero orphans,
chain hash `62c594bfc619186dd32fed2beaec30475c60f4ee3b4859cb9835543f8a14c3ca`.
Its five valid authored views are fixture coverage, not real inference.
The real exercise above is ten actual local calls consuming actual retained
market and native model evidence. Neither run contains trading outcomes or P&L.

Final runtime readback: OFF, entries/requested entries false, worker inactive,
mode/session null, auto-restart false and capital transfers false.
The existing desk capital proposals and recorded testing budgets remain
inactive. `git diff --check` passed.

## Remaining limits and one recommended next burst

Typed contracts solve the observed label-format failures in this bounded local
exercise. They do not guarantee all future model responses will be valid or
economically correct. Source/provenance declarations are not provider or human
attestation, heuristic confidence is uncalibrated, and shared-model persona
agreement is not independent statistical evidence. Current context alignment,
future-path interpretation and append-only outcome evaluation remain separate
work. No trading-performance claim is justified.

**Recommended next burst: deterministic Brigade evidence-consistency review
in shadow mode.** Retain typed claims linked to explicit context/forecast
fields, flag unavailable-data and direction/range contradictions, preserve the
original recommendation and dissent, and append a separate review disposition.
Complete it with adversarial fixtures, source-bound real local captures,
provider-free replay and verified zero execution effects. Any action-criteria
changes require separate explicit versioned policy governance; this review must
not silently alter native live rules, confidence thresholds, desk ownership,
budgets or execution. This next burst has not been implemented.
