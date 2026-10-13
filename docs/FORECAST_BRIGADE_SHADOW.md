# Governed forecast intake and Brigade shadow analysis

This interface extends the passive two-desk research path. Forecasts are
explicit, source-bound model outputs. Brigade opinions are advisory analysis
of those forecasts. Neither is an authorization, an executable order, a
capital allocation or a change to desk ownership. Auto-trading remains **OFF**;
the fixed test budgets remain inactive.

## Verified source landscape

Read-only reconnaissance on October 12, 2026 inspected the actual Galactica
forecast producers and retained outputs. No provider, broker, model-training
or inference call was made during that inspection. The relevant implementation
is in the read-only sibling `blackpod_galactica`; this burst does not change it.

| Existing source | Observed behavior | Intake implication |
| --- | --- | --- |
| `phase2_forecast_engine.py::generate_forecast` | Uses `Close.shift(-h)` as the training target; emits `Date, Symbol, Q10, Q50, Q90, Pattern, Timeframe, Horizon` | Quantiles are future **USD closing-price levels**, not returns. The horizon counts observed daily bars; `Date` is the last feature observation, not the production timestamp or target timestamp. |
| `phase2_forecast_engine.py::_load_or_train_model` | Loads or fits quantile models; optionally persists joblib models and metadata with model type, features, configuration hash, training row count and training end date | Importing the module creates directories; calling it can train and write. Governed intake must retain explicit producer/model/data evidence instead of importing it, loading pickle-like model files or inferring provenance from a filename. |
| `phase3_forecast_aggregator.py::aggregate_live_forecasts` | Selects rows whose `Pattern` contains `LIVE`; writes a seven-column matrix | Drops `Horizon`. The matrix alone cannot establish which forecast target a row represents. `LIVE` is a historical label, not proof of currentness. |
| `agents/blackwell_brigade.py::BlackwellBrigadeWatchtower` | Collects Scout, Sentry, Advisor, Canary and Pathfinder opinions; its context helper treats consecutive Q50 rows as temporal history and may read `data/raw` implicitly | Different horizons at the same as-of time cannot stand in for a historical forecast series. A safe adapter must distinguish an explicitly labeled future forecast path from retained observed market history, with no implicit disk-source substitution. |
| `agents/blackwell_brigade.py::build_trade_plan` | Derives trading guidance from an agent action and supplied sizing context | Such legacy guidance remains advisory evidence. It cannot become an executable order or bypass the separate execution controller. |
| `agents/ai_client.py::BlackPodAI` | Posts to a legacy chat-completions endpoint with locally selected model and optional constitution prompt | This is not the preserved Build Week ModelDock integration. The new shadow seam must not reconnect the legacy provider/orchestrator. |
| `agents/decay.py::Blackwell_Decay` | Takes close-price arrays and optional benchmark arrays; returns deterministic drift/bleed observations | The Brigade imports `DecayAgent`, which this file does not export. Native optional Decay is unavailable in Watchtower. The new adapter connects the actual deterministic interface separately; five-member native coverage remains five. |
| `blackpod_battlestar/blackpod/advisors/armada.py::ArmadaAdvisor` | Extends `LegacyFileAdvisor` around a forecast CSV | A file adapter is not a connected, current forecasting model. |

All **154** Galactica `*_forecast.csv` files were inspected. Their maximum
retained `Date` is **June 10, 2026**; none has an October 12 forecast. SPY,
USMV and QUAL each retain five June 10 `LIVE` rows for horizons 1D through 5D.
XLE, QQQ and AAPL retain corresponding June 9 rows. These five rows describe
five targets at one as-of date, not five sequential prediction observations.
No clock time or timezone is invented for a date-only source.

The actual `armada_forecast_matrix.csv` has 790 rows with dates from January
2020 through June 10, 2026 and no horizon column. The retained
`armada_senate_current.csv` has 110 June 9 rows; `senate_decisions.csv` has
132 April 24 rows. Their names do not make them current evidence.

Galactica also has forecast evaluation CSVs. The single-source log has 10,225
rows for December 19–23, 2025 forecasts; the multi-source log has 371 rows for
December 22–24, 2025 forecasts. They record forecast-error, quantile loss,
band coverage and observed-price outcomes. They do not establish attributable
fills, fees, realized trade P&L, source independence or investment performance.
They are not promoted to governed current evaluations by this burst.

## ModelDock boundary

The existing `ModelDockClient.generate_text` remains the strict local appliance
interface. It validates the request, correlation, bounded response, actual MLX
envelope, returned model identity and delivery metadata. It has no automatic
retry or provider fallback. `load_modeldock_config` requires an explicit
loopback `MODELDOCK_BASE_URL` and request timeout. Model routing belongs to
ModelDock; legacy `MODELDOCK_MODEL` is ignored for new LIVE requests.

The reconnaissance process found the ModelDock configuration environment
variables unset. That is an environment observation, not a claim that the
appliance is unavailable. No health probe, service start, registry lookup,
configuration edit or inference request is implied by reading this document.

The existing [two-desk review](SHADOW_DESK_REVIEW.md),
[Decision Journal](DECISION_JOURNAL.md),
[auto-trading boundary](AUTO_TRADING.md) and
[fill-lot accounting](TRADING_ACCOUNTING.md) remain separate responsibilities.

## Forecast contract and admission

`contracts/forecast_intake.py::ForecastIntake` validates
`blackpod.forecast_intake.v1`. The scope is `SHADOW_FORECAST_INTAKE_ONLY`, the
mode is `SHADOW`, and the domain is explicitly `TRADING` or `INVESTMENT`.
`CAPITAL_ALLOCATION` is not a forecasting domain. Both the submission timestamp
and analytical `shadow_as_of` are supplied; currentness is measured against
that declared analytical instant, not silently refreshed during replay.

Each source binds its exact raw bytes, unique source identity, format and
optional separate provenance bytes. Supported formats are
`GALACTICA_PHASE2_CSV`, `GALACTICA_PHASE3_CSV` and
`GOVERNED_PRICE_FORECAST_JSON`. Legacy source rows remain available verbatim
with their source row number. Missing metadata remains null and contributes a
deferral reason; it is not reconstructed from a directory name, `LIVE` label,
filesystem modification time or current wall clock.

Separate `blackpod.forecast_provenance.v1` metadata binds the raw forecast hash
and records a declared reviewer, review time, producer/model identity and
retained producer, model-artifact, configuration, feature and training
evidence. Calibration evidence has its own optional binding. Row metadata
distinguishes issuance, feature cutoff, training cutoff, explicit target,
horizon and reference price/time. The status `REVIEWED_SOURCE_BOUND` records
that declaration and its retained sources; it does not authenticate a reviewer,
verify model fitting, establish independence or calibrate probabilities.

Configuration evidence must use `blackpod.forecast_model_config.v1`, match
the declared model kind, retain quantile levels `0.10`, `0.50`, `0.90`, and
specify `FUTURE_CLOSE`, `USD` and explicit unique feature names. Opaque model
artifact bytes are hash-bound and retained; they are never loaded or executed.

`blackpod.forecast_observation_evidence.v1` retains ordered, finite feature
observations and training observations. Training rows separately identify
feature observation time and `target_observed_at`, when the supervised target
label was available. The latest retained availability must equal the declared
cutoff; labels observed after the cutoff cannot be treated as earlier training
knowledge. This checks retained timestamp consistency, not the mathematical
correctness of fitting or the completeness of an original dataset.

`target_session_evidence` binds a
`blackpod.forecast_session_calendar.v1` packet to the feature anchor, capture
time and explicitly ordered session opens/closes. Its declared horizon must
end at the corresponding retained session close, and the calendar capture
cannot postdate issuance. This is a retained, declared calendar binding; it
does not authenticate an exchange calendar or fill missing sessions by
guessing calendar-day offsets.

The versioned initial interface is `DAILY_USD_PRICE_V1`: positive finite USD
predicted closing-price levels with declared horizons of one through five
trading sessions. Quantile labels remain labels; their nominal levels do not imply
demonstrated 80% coverage or a probability of a profitable trade. A forecast
price cannot become a return without an explicit reference price and time.
These short daily horizons cannot establish a long-horizon investment thesis.
An `INVESTMENT` intake preserves the same source evidence but defers these
rows with `SHORT_HORIZON_NOT_INVESTMENT_EVIDENCE`; it cannot silently promote a
daily forecast into investment authority.

The initial shadow admission policy fixes maximum issuance, feature and
training ages at **86,400 seconds** each. This is a conservative wall-clock
research gate, not a trading-calendar-aware execution gate or a change to live
risk policy. Weekend or holiday gaps can defer otherwise interpretable daily
sources. A row is either `CURRENT_SHADOW_ELIGIBLE` or `DEFER`; eligibility
permits advisory processing only. Malformed contract structure and corrupt
evidence fail validation rather than becoming research votes.

Results retain all admitted and deferred rows, source summaries, reasons and
limitations. Every row has null `realized_outcome` and `evaluation`.
`auto_trading_enabled` and all four authorization, capital activation,
execution and policy-change flags remain false. The intake itself installs no
desk ownership or runtime sizing policy.

## Native Brigade calculation and retained responses

`shadow_brigade_analysis.py::build_shadow_brigade_analysis` reuses the actual
Galactica Scout, Sentry, Advisor, Canary and Pathfinder `analyze` methods,
prompt builders and parsers. The full original Brigade and Decay source files
must match fixed reviewed fingerprints before a selected AST definition
closure is compiled. Native package initializers, provider imports,
Watchtower, implicit raw-file readers and the execution-plan builder are
excluded. The plan builder is intercepted with a null result before native
sizing, stops, exits, quantities or order guidance can be constructed.

The wrapper's versioned `blackpod.shadow_brigade_context.v1` derives trend,
z-score, volatility regime and volume measures from retained observed daily
OHLCV. It excludes unproven bars on the market capture's UTC date and uses
at most 300 prior daily bars. IEX volume remains single-exchange volume.
Each member's minimum-history checks are explicit; missing or stale observed
context produces `DEFER` before any model call.

Eligible forecast rows from one source/model/issuance ancestry form an ordered
**future predicted closing-price path**. The terminal target supplies the
quantile-band context, and Pathfinder requires at least three distinct future
targets. Its pattern and slope calculations describe a forecast path, not
observed chart patterns or realized returns. Different-horizon target rows
are never substituted for chronological observed prices. Shared inputs and
different personas do not establish independent statistical evidence.

The wrapper also calls the actual `Blackwell_Decay.analyze` separately with
observed closes. When available, a SPY comparison must align the exact source
timestamps; SPY does not benchmark itself. This is an explicitly separate
deterministic shadow calculation, not proof that the legacy Watchtower's
optional sixth-member import works. Its confidence remains a heuristic label.

No inference occurs by default. Supplied retained responses support offline
replay; a freshly injected generator requires explicit opt-in. A review is
bounded to one through eight selected symbols, with a 100-call ceiling and
32 KiB maximum response. Inference failures retain a safe deterministic error
code rather than provider exception text. The wrapper preserves exact native
prompts, personas, context hashes, forecast identities, responses and member
coverage so verified replay never needs a provider.

Raw text must contain exactly one native-compatible `ACTION:`, `CONFIDENCE:`
and nonempty `REASONING:` label. Actions are BUY, EXIT, HOLD or WATCH;
confidence must be finite and between zero and one. Missing, duplicated,
unsupported or malformed labels defer that member. Native fallback HOLD and
0.55 parser outputs can remain visible as parser behavior, but cannot become
invented valid votes. The validated opinion remains a recommendation with
`trade_plan_suppressed=true` and `confidence_is_probability=false`.

Missing current forecasts, stale issuance/data cutoffs, elapsed targets,
missing market context or unavailable inference remain explicit. No member's
absence is repaired with a historical vote or an inferred hypothesis.
Dissent preserves the members' different valid recommendations; it is not
collapsed into a trading authorization.

`contracts/brigade_shadow.py::BrigadeShadowRequest` validates
`blackpod.brigade_shadow_request.v1`. It is `TRADING`, `SHADOW` and
`BRIGADE_RECOMMENDATIONS_ONLY`. The request links a verified intake event,
intake identity, source hash and original intake bytes, then separately binds
market, native Brigade, native Decay and optional retained transcript bytes.
It accepts `DISABLED` or `RETAINED_TRANSCRIPT` inference modes. Recording a
request cannot itself enable inference or execution.

## Explicit ModelDock capture and recovery

`brigade_shadow_transport.py::capture_modeldock` is a separate opt-in
boundary. It uses the preserved `ModelDockClient`, asks for the native response
inside the single `brigade_text` JSON field and adds an explicit SHADOW
instruction: forecast paths are future predicted prices, not observed chart
patterns, and every action is advisory. ModelDock's transport mode `LIVE`
means a real local text request; the desk analysis remains `SHADOW` and grants
no broker permission.

`DECLARED_REPLAY` bundles retain supplied, unauthenticated response strings.
`MODELDOCK_CAPTURE` bundles also retain validated request/correlation hashes,
projected appliance responses, byte/hash metadata, model/provider provenance
and capture times. Verification uses that retained projection and never calls
the appliance. Raw response hashes do not authenticate a provider, and the
safe projection omits appliance model filesystem paths.

The native temperature request is retained with the prompt. It is not
forwarded as a new unsupported ModelDock parameter; effective sampling and
model selection remain appliance-controlled. No ModelDock configuration,
registry or model is changed by the wrapper.

A real capture requires an analysis clock no more than five minutes behind
the current clock and cannot be future-dated. Before each POST it checks
current target expiry, issue/feature/training ages and market-capture age.
The transport attempt supports at most 40 member calls and 300 seconds; it
does not start another call whose configured delivery deadline would exceed
that bound. With no eligible members, the default path needs no ModelDock
configuration and produces a deferred artifact with zero inference calls.
Explicit process-local override arguments still undergo configuration validation.

Before a request can leave the process, immutable generation and call intents
reserve the attempt. A failure or uncertain delivery stops further calls with
no fallback or retry. Completed receipts are retained individually. Recovery
seals the receipts already present and leaves uncaptured members deferred;
it never repeats the provider work. Reusing a complete capture returns the
existing result, while changing evidence under a consumed attempt conflicts.
Closing/recovery time remains distinct from the original analytical clock.

Responses are checked again at receipt time. A structurally valid reply that
arrives after its target or freshness window is retained as
`VALIDATED_EXPIRED`, with a deferred native recommendation. It cannot become a
current vote simply because the original request was fresh.

Capture reports distinguish calls made by the current invocation from durable
call intents, retained receipts and unconfirmed local receipts. Recovery makes
zero new inference calls. A failure receipt does not prove that server
computation stopped; original delivery diagnostics retain that uncertainty.

Files changed, exact executed commands, real-versus-fixture coverage and final
test results are in [the validation report](FORECAST_BRIGADE_SHADOW_VALIDATION.md).

## Runnable offline example

The example uses the fixed symbol `SYNTHETIC`, authored forecast levels,
nonexecuted model bytes, synthetic observations and authored Brigade response
strings. It demonstrates the actual pinned native prompt/parser and Decay
interfaces, not predictive skill, current market research or actual inference.
It requires the existing dependencies only and reads no sibling checkout or
credentials.

Run from the repository root. Source evidence and the output journal are
separate, and immutable writes reject different existing bytes:

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python3.11 \
  -m blackpod_build_week.forecast_brigade_example \
  --output-root output/auto-trading-forecast-brigade-example

PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python3.11 \
  -m blackpod_build_week.forecast_intake_cli assess \
  --journal-root output/auto-trading-forecast-brigade-example/journal \
  --intake output/auto-trading-forecast-brigade-example/intake.json \
  --evidence-root output/auto-trading-forecast-brigade-example/evidence

PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python3.11 \
  -m blackpod_build_week.forecast_intake_cli record \
  --journal-root output/auto-trading-forecast-brigade-example/journal \
  --intake output/auto-trading-forecast-brigade-example/intake.json \
  --evidence-root output/auto-trading-forecast-brigade-example/evidence

PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python3.11 \
  -m blackpod_build_week.brigade_shadow_cli assess \
  --journal-root output/auto-trading-forecast-brigade-example/journal \
  --request output/auto-trading-forecast-brigade-example/request.disabled.json \
  --evidence-root output/auto-trading-forecast-brigade-example/evidence

PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python3.11 \
  -m blackpod_build_week.brigade_shadow_cli record \
  --journal-root output/auto-trading-forecast-brigade-example/journal \
  --request output/auto-trading-forecast-brigade-example/request.disabled.json \
  --evidence-root output/auto-trading-forecast-brigade-example/evidence

PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python3.11 \
  -m blackpod_build_week.brigade_shadow_cli record \
  --journal-root output/auto-trading-forecast-brigade-example/journal \
  --request output/auto-trading-forecast-brigade-example/request.replay.json \
  --evidence-root output/auto-trading-forecast-brigade-example/evidence

PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python3.11 \
  -m blackpod_build_week.harbormaster journal verify \
  --journal-root output/auto-trading-forecast-brigade-example/journal
```

Preparation seeds one forecast event with three eligible **synthetic** rows.
Repeating `record` for that intake is an idempotent no-op. The separate
`request.disabled.json` prepares a no-inference analysis, while
`request.replay.json` binds authored offline response strings and preserves
BUY/EXIT/HOLD/WATCH dissent. No model is fitted or loaded, no provider is
contacted and no paper orders are submitted. These fixed example dates cannot
become current real forecast evidence.

After both Brigade records, verification reports three events, 17 retained
evidence blobs and zero orphans. Retrying the same recorded input is an
idempotent no-op; after a successful record the verified retained blobs allow
the same retry without `--evidence-root`.

Read the public event identity from the example metadata, then show and render
the verified report:

```sh
brigade_review_event_id=$(.venv/bin/python3.11 -c 'import json; print(json.load(open("output/auto-trading-forecast-brigade-example/expected-ids.json"))["brigade_replay"])')

PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python3.11 \
  -m blackpod_build_week.brigade_shadow_cli show \
  --journal-root output/auto-trading-forecast-brigade-example/journal \
  --event-id "$brigade_review_event_id"

PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python3.11 \
  -m blackpod_build_week.brigade_shadow_cli render \
  --journal-root output/auto-trading-forecast-brigade-example/journal \
  --event-id "$brigade_review_event_id" \
  --output output/auto-trading-forecast-brigade-example-report/review.html
```

The separate static HTML report contains no execution or activation control.
An existing differing report is not overwritten; use a new output filename
when intentionally changing its presentation.

For separately prepared **real**, eligible sources, the explicit generation
command is:

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python3.11 \
  -m blackpod_build_week.brigade_shadow_cli generate \
  --journal-root /absolute/path/to/verified/journal \
  --request /absolute/path/to/request.disabled.json \
  --evidence-root /absolute/path/to/retained/evidence \
  --output-directory output/auto-trading-brigade-capture \
  --modeldock-shadow
```

This example requires a current, source-bound request and existing explicit
ModelDock environment configuration. It is not part of the offline synthetic
example and must not relabel its authored forecasts as real. Optional
`--modeldock-base-url`, `--modeldock-timeout-seconds` and
`--modeldock-delivery-grace-seconds` apply validated process-local overrides;
they do not edit configuration files. With no eligible members, `generate`
writes the deferred assessment and makes zero provider calls.

Recover an interrupted attempt using the same original request and output
directory:

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python3.11 \
  -m blackpod_build_week.brigade_shadow_cli recover \
  --journal-root /absolute/path/to/verified/journal \
  --request /absolute/path/to/request.disabled.json \
  --evidence-root /absolute/path/to/retained/evidence \
  --output-directory output/auto-trading-brigade-capture
```

Recovery needs no ModelDock opt-in or endpoint because it makes no provider
calls. After capture or recovery, `request.replay.json` and the output
directory's `evidence` subdirectory supply the normal passive `assess` and
`record` commands. A recovered missing member remains deferred. No inference
is retried merely to complete coverage.

## Research and governance limits

Hashes and deterministic replay establish retained byte identity and interface
behavior. They do not prove source authenticity, independent evidence,
economic truth, training correctness or predictive skill. A supplied review
identity remains a declaration. Native heuristic confidence and ModelDock
model provenance remain separate from calibrated forecast probabilities.

Current forecast admission is not an allocation recommendation. The short
daily interface supplies no investment hypothesis, expected return, valuation,
long-term horizon, thesis invalidation or human approval by inference. Existing
investment hypotheses and approvals retain their own contracts and authority
semantics. No repeated 50/50 rebalance, capital transfer or recurring service
is created.

Later forecast evaluations should append linked observations to the original
forecast identity, with fixed target/session and statistical metrics. They
must keep forecast accuracy separate from attributable trade execution and
fees. That outcome lifecycle is further work; this burst does not fabricate
historical evaluations or rewrite prior decisions. Any improvement to models,
source fingerprints or decision rules requires a reviewed version change.
No live policy is automatically adapted from historical results or LLM
reasoning.
