# Sentry → Oracle market synthesis

Open **BlackPod → Sentry → Market synthesis**, or the local
[market synthesis page](http://127.0.0.1:5183/sentry-synthesis).
The [JSON projection](http://127.0.0.1:5183/sentry-synthesis.json) contains the
same retained report. Reading or refreshing either page never starts inference.

This module turns a bounded selection of saved Sentry observations into an
Oracle interpretation, then asks a separate review pass to challenge it.
Both remain **unverified interpretations**, with their original evidence and
dissent preserved. They do not authorize trades, select positions, size orders,
allocate capital, change policy, or alter the frozen reversal experiment.
Auto-trading must remain **OFF**. Galactica trading rules and its native
candidate-generation workflow are not used.

Canonical Oracle enrichment remains mission-scoped. This supplemental news
role reuses the existing validated local `ModelDockClient` without fabricating
a canonical mission or invoking the old market-brief candidate generator.
Its transport `LIVE` metadata means local inference only; it grants no live
trading authority. The two requests are analytical roles in this worker, not
new autonomous decision agents.

## Reading the brief

- **Overview:** a tentative picture of the selected news, with evidence links.
- **Themes:** at most three interpretations, each linked to retained evidence.
- **Symbol implications:** separate trading and investment questions. A direct
  mention in the retained contract requires a cited headline tagged with that
  symbol by the provider; it does not prove the text names that company. The UI
  labels this as a provider symbol tag with textual connection unverified. A possible wider
  connection is explicitly labeled hypothetical read-through.
- **Challenge:** one review per theme, preserving disagreement, alternatives,
  missing evidence and unresolved assumptions. It cannot approve an action.
- **Review horizon and invalidation:** proposed research questions, not a new
  registered experiment. Unknown horizons remain unspecified; absent
  invalidation conditions remain absent.
- **Quality and age:** headline selection limits, incomplete news coverage,
  stale or unavailable prices, and whether newer Sentry observations exist.

There are no verified portfolio holdings, ownership or position sizes in this
input. The page therefore shows **watchlist implications**, with portfolio
assessment unavailable. A well-written brief does not establish that its
interpretation is correct or that a tradable opportunity remains.

## Evidence and processing bounds

The source is the existing immutable Sentry capture store, fully verified and
replayed before use. This path makes **no Alpaca or broker requests** and reads
no trading credentials. It calls only the explicitly configured local ModelDock
endpoint. Model selection stays in ModelDock; this module does not edit its
configuration or reuse the old mission candidate workflow.

| Bound | Behavior |
| --- | --- |
| Watchlist | Existing explicit Sentry watchlist; maximum ten symbols |
| News input | At most twenty retained headlines, latest observed revision per article, updated within the preceding 24 hours |
| Selection | Exact URL or normalized-headline attention duplicates removed; symbol coverage considered before filling with recent headlines |
| Market context | Latest retained price/volume context for up to ten symbols, with actual source timestamps |
| Feed quality | Retained-prefix audit and explicit unknown coverage; no fabricated missing-news count |
| Model work | At most two calls: Oracle draft, then challenge if the draft passes validation |
| Background schedule | Weekdays, 05:00–17:00 America/Los_Angeles; at least sixty minutes between ordinary attempts; maximum four ordinary attempts per LA day |
| Explicit manual diagnostics | Separate from background hours/daily/spacing limits after the user's October 15 authorization; one serialized, deadline-bound delivery per deterministic identity, with no automatic resends |
| Timeout | Current v6 and retained v3/v4/v5 per-call bound: at most 900 seconds plus 30 seconds delivery grace; historical v1/v2 retain their original 120/10 bounds |
| Activation | Separate synthesis control; disabled until explicitly enabled after validation |
| Archive | At most 256 retained attempt/abandoned capsules and 64 MiB; stop for review, never auto-delete |

This is a bounded sample, not the entire news universe. Selection and omitted
counts are retained. Repeated observations, revisions and similar coverage
cannot establish independent corroboration. Different URLs or publisher names
also do not prove source independence.

Only headlines are read. Article bodies, primary filings, earnings estimates,
analyst research and verified company fundamentals are absent. Price change
means a retained minute close versus the provider's previous daily close. It is
not a measured post-headline response, a matched SPY/QQQ excess return, a causal
effect, an executable quote or realized trade P&L. Day volume is not
time-matched relative volume.

The challenge is a separate role prompt and request bound to the original
draft and evidence packet. That provides a separate review pass; it does not
establish a different underlying model, independent sources or economic truth.

## Administration

Run from `/Users/nikolai/Projects/blackpod_battlestar_build_week`. The existing
station configuration remains unchanged; synthesis has its own control under
`output/blackpod-shadow-station/synthesis/`.

```bash
# Offline status and retained report availability; no inference.
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python3.11 \
  -m blackpod_build_week.sentry_synthesis_service status \
  --config output/blackpod-shadow-station/config.json

# Verify retained synthesis and source bindings; no inference.
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python3.11 \
  -m blackpod_build_week.sentry_synthesis_service verify \
  --config output/blackpod-shadow-station/config.json

# Configure disabled. ModelDock must already be available at the local address.
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python3.11 \
  -m blackpod_build_week.sentry_synthesis_service configure \
  --config output/blackpod-shadow-station/config.json \
  --modeldock-base-url http://127.0.0.1:8000 \
  --modeldock-timeout-seconds 900 --modeldock-delivery-grace-seconds 30 \
  --modeldock-profile default
```

To enable after validation, repeat `configure` with the same arguments and add
`--enabled`. To pause synthesis, repeat it without `--enabled`. This control
does not enable auto-trading or change the Sentry/pilot collectors.

```bash
# Explicit bounded generation; not triggered by UI reads.
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python3.11 \
  -m blackpod_build_week.sentry_synthesis_service generate \
  --config output/blackpod-shadow-station/config.json

# Recover from retained processing artifacts; do not force a new model call.
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python3.11 \
  -m blackpod_build_week.sentry_synthesis_service recover \
  --config output/blackpod-shadow-station/config.json
```

Generation retains the same schedule, budget and verification gates used by
the background worker. Never delete operational state, reset its budget or
resubmit an uncertain model request to force a result. A stopped or unhealthy
ModelDock is a visible unavailable/failed synthesis, not permission to change
providers or substitute invented content.

## Validation, retention and recovery

Source text is untrusted data, not instructions. Model requests have fixed
roles and no tools, browsing or order capabilities. Strict JSON contracts reject
unknown fields, unknown/duplicate citations, unsupported symbols, invalid direct
mentions, mismatched draft hashes and missing or duplicate theme reviews.
Strings and arrays are bounded. Strict validation establishes structure and
provenance bindings; it cannot verify semantic truth or factual entailment.

Current model response contracts are **v2**. An unspecified invalidation is an
explicit `{"status":"UNSPECIFIED","text":""}`; a proposed condition requires
`PROPOSED` and nonblank text. This avoids nullable unions unsupported by the
local ModelDock schema dialect. Historical v1 attempts replay with their
original wire schema, response shape and identities. No retained record is
converted to v2 or resent during migration.

The current background transport is **v6**, using the same v2 output contracts, prompts,
2,500-token limit, model routing and evidence selection. It binds configuration
into its correlation identity and permits a 900-second request budget with
30 seconds of delivery grace for slower local hardware. ModelDock already
honors this per-request timeout; its server default is a fallback, not a hard
90-second cap. No ModelDock appliance modification is needed. Retained v1/v2
request bytes, identities and version-specific deadline limits still replay.
Retained v3/v4/v5 configuration hashes and 900/30 identities also replay exactly.

Separately recorded manual validations retain v6's original 2,500-token trial,
v7's 4,096-token trial, and v8's explicit instructions for the existing strict
host contract. V8 changes only request guidance: unique theme IDs/citations/
symbols, direct-mention citation linkage, text formatting, and exact challenge
coverage. It retains v2 response schemas, the same evidence, 4,096-token ceiling
and 900/30 deadline. V1–v7 request bytes remain replayable unchanged.

`validate-contract` admits only one deterministic v8 child of a verified,
terminal v7 `MODELDOCK_NARRATIVE_SCHEMA_INVALID` rejection. It does not assume
an unavailable cause or retry an uncertain request. An optional
`local-contract-error.json` on a new v8 rejection contains only a closed host
reason category and exact request/receipt/self hashes. Unknown exception text,
rejected content and failed provenance are never retained in that diagnostic.
Historical failures are not backfilled. Ordinary background delivery stays at
v6 until a real accepted pair and its evidence review justify promotion.

`validate-text` permits one separately recorded v9 child only after that exact
v8 rejection has a verified original `TEXT_FORMAT` observation. V9 adds compact
generation instructions: short, plain-character sentences and fewer themes/
implications. These are instructions, not new schema guarantees. The strict
v2 host contract, 4,096-token ceiling and 900/30 deadline stay unchanged.
Only new v9 rejections may retain diagnostic v2, with a closed rule/field pair;
the original v8 diagnostic v1 shape and bytes stay unchanged. Unknown fields
and rules remain explicitly unclassified. No model output is trimmed,
rewritten, coerced, repaired or accepted after a failed validation.

The user separately approved saving Gemma 4 E4B in ModelDock's per-user startup
override. Model routing remains owned by ModelDock; BlackPod does not insert
a model name into its generation requests. See the
[dated diagnostic and deployment record](SENTRY_ERROR_CODE_DIAGNOSTIC_2026-10-15.md)
for actual attempts, fixture coverage, startup evidence and remaining gates.

### Explicit compatibility validation of a failed v1 attempt

The separately authorized `validate-v2` command can record one v2 child of an
original, terminal FAILED/REJECTED v1 Oracle attempt. It is not an automatic
retry: the background worker never invokes it. Accepted or uncertain source
attempts are ineligible. It retains the exact original packet bytes, source
clock and failed capsule, and hashes the parent report linkage into the child.
The shared hourly/four-per-day budget, monitoring window, storage bounds,
auto-trading OFF, frozen source pins and unchanged watchlist still apply.

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python3.11 \
  -m blackpod_build_week.sentry_synthesis_service validate-v2 \
  --config output/blackpod-shadow-station/config.json \
  --source-report-id 'sentry-synthesis-<original terminal v1 failure SHA-256>'
```

Its deterministic child identity permits no second delivery. Repeating the
command reads or recovers retained work without sending; interrupted/uncertain
work stays visible. The UI explicitly labels historical compatibility
validation and shows original evidence time separately from completion time.
It must not be described as a fresh market assessment or new forecast.

The installed app calls dashboard ports 5181–5183; its Python station worker
calls ModelDock at the configured `http://127.0.0.1:8000/text/generate` endpoint.
The default Sentry transport adds `X-ModelDock-Client: BlackPod-Sentry` for
ModelDock's activity display. This label does not change request bodies,
model routing, profiles or authority. “Connected clients” records named
generation activity, not a persistent native-app connection. No additional
ModelDock endpoint is required in the native webview.

### Explicit retained-evidence deadline validation

After a separately authorized timeout diagnosis, `validate-deadline` can record
one v3 child of the terminal **v2 validation with `MODELDOCK_HTTP_504`**. It
requires exactly 900 seconds plus 30 seconds grace. The original v1 failure,
v2 failure and exact historical packet remain unchanged. A v3 child cannot
become another deadline-validation parent.

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python3.11 \
  -m blackpod_build_week.sentry_synthesis_service validate-deadline \
  --config output/blackpod-shadow-station/config.json \
  --source-report-id 'sentry-synthesis-<terminal v2 timeout report SHA-256>'
```

This explicit manual scope permits a historical diagnostic outside monitoring
hours. It does not change the background schedule or admit new market evidence.
The real clock, enabled control, archive bounds, watchlist, OFF and
frozen-source gates still apply. Explicit manual diagnostics no longer consume
the background hourly/daily budget; the user authorized this separation on
October 15 after the fourth diagnostic. No old ledger entry is edited or reset.
Its deterministic identity excludes deadline changes as a way to create another
try. Duplicate and interrupted calls inspect retained work; they never resend.

The read-only UI labels deadline validation and original source time, retains
both the original interpretation and dissent when accepted, and distinguishes
a reserved attempt from the previous completed report. A bounded processing
health allowance reflects the configured delivery window; it does not claim
native token progress or successful completion. Idle health retains its
ordinary five-minute threshold.

### Explicit error-code diagnostic

The separately authorized `validate-error` command records one v4 child of
the exact terminal **v3 deadline validation with `MODELDOCK_HTTP_500`**.
It preserves the original evidence and all three failed capsules. It uses
900/30, the same prompts/schema/token ceiling, and a fresh version-bound
correlation identity. It cannot accept an uncertain, accepted, earlier-version
or v4 parent. No further error-diagnostic child is admitted.

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python3.11 \
  -m blackpod_build_week.sentry_synthesis_service validate-error \
  --config output/blackpod-shadow-station/config.json \
  --source-report-id 'sentry-synthesis-<terminal v3 HTTP 500 report SHA-256>'
```

As with deadline validation, manual diagnostics have a separate schedule
allowance; real-clock sanity, enabled control, serialization, storage, OFF,
source pins and watchlist gates still apply. An existing reservation is never resent.
The UI labels this as an explicit error-code diagnostic and separates the
original evidence clock from its later processing clock. See the
[October 15 diagnostic record](SENTRY_ERROR_CODE_DIAGNOSTIC_2026-10-15.md).

### Explicit runtime diagnostic

After the user's separate authorization and deployment of safe native
validation metadata, `validate-runtime` admits one v5 child of the exact
terminal v4 HTTP 500 with a verified `STRUCTURED_OUTPUT_INVALID` observation.
It retains the original four failures and packet. Accepted, uncertain,
wrong-code, missing-observation and v5 parents are ineligible. No output repair,
token-limit change or automatic retry is introduced.

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python3.11 \
  -m blackpod_build_week.sentry_synthesis_service validate-runtime \
  --config output/blackpod-shadow-station/config.json \
  --source-report-id 'sentry-synthesis-<verified terminal v4 validation failure SHA-256>'
```

### Explicit model-selection validation

The user-selected Gemma trial uses `validate-model`, a single v6 child of the
verified terminal v5 JSON-syntax failure at native 2,500 tokens / `length`.
It preserves the five earlier capsules, original packet, schema, prompts,
profile, 900/30 deadline and **2,500-token ceiling**. It does not increase the
output budget or choose a model behind ModelDock's back. Check the active-model
endpoint immediately before delivery and verify actual accepted provenance
for both roles; a READY health response alone does not identify the model.
Retain a failed role's missing model provenance as unavailable.

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python3.11 \
  -m blackpod_build_week.sentry_synthesis_service validate-model \
  --config output/blackpod-shadow-station/config.json \
  --source-report-id 'sentry-synthesis-<verified terminal v5 syntax/length failure SHA-256>'
```

The UI labels model-selection validation and retains the historical evidence
clock. This is an explicit research diagnostic with the same OFF/source,
serialization, pause, clock and storage gates. It cannot be resent or used as
another model-validation parent. No token increase is enabled by this command.

### Bounded HTTP-error metadata

Sentry's owned HTTP opener can retain an optional `http-error.json` beside a
future failed role. It reads at most 8 KiB, for at most two seconds within the
original deadline with a delivery margin. Only an allowlisted error code with
an exact matching request ID can be AVAILABLE. Malformed, oversized, partial,
unknown-code or mismatched responses remain UNAVAILABLE. The metadata binds
the request, terminal receipt and complete-body hash/count when available;
no error message, arbitrary details, raw body or model output is retained or displayed.

For a complete correlated HTTP 500 / `STRUCTURED_OUTPUT_INVALID`, sidecar v2
can additionally retain exactly one closed native validation diagnostic:
fixed reason/stage labels, an allowlisted schema keyword, and correctly typed
native token/stop counters or explicit unavailability. Extra fields, unknown
labels, inconsistent provenance or private values discard the entire detail
object, leaving the original v1 code-only observation. Schema paths, instance
values and exception strings are excluded. Both versions verify their original
request, receipt and self hashes without rewriting older sidecars.

The canonical mission urllib client still discards HTTP error bodies. Sentry
returns the same terminal status and report shape, and diagnostics cannot
create an automatic retry, relax response validation or alter authority.
Existing capsules are never backfilled. Provider-free
`sentry_synthesis_transport.read_error_observation` verifies this optional
metadata; missing evidence remains unavailable. The completed October 15
HTTP 500 predates this observer, so its specific code cannot be reconstructed.

Requests, sanitized response projections, response hashes, processing receipts and immutable reports
remain local under the separate synthesis operational root. They are not part
of the pilot journal or source Sentry captures. No credentials are included in
model inputs or reports. Treat model output as untrusted research material.
Original response hashes identify delivery bytes; sanitized projections do not
recreate stripped private envelope fields. Private request and intent files
are not served by the read-only HTTP projection.

Reports retain the exact evidence packet and original capture-prefix identity.
Verification replays that original prefix even after later captures append.
Later reports append; they do not rewrite an earlier draft or its challenge.
Hash checks establish internal integrity, not an authenticated external proof
of news publication, source independence or economic accuracy.

Attempt accounting is persisted before model work. Uncertain delivery,
timeouts and invalid JSON do not trigger automatic retries or JSON repair.
The immutable run ledger enforces budgets even if mutable display state is
lost. A packet left before its run reservation is retained as abandoned, with
no invented request time; that exact headline set is not automatically sent.
Interrupted processing is recovered only from retained evidence of what
completed. Missing work remains incomplete. A valid draft with no valid
challenge must be visibly draft-only; it cannot masquerade as challenged.

OFF and source verification gates are enforced around processing and reading.
Corrupt source evidence or an unverifiable OFF state blocks the projection;
there is no substitute cached report presented as current verified research.
When an older retained report is readable, its age and any newer source
observations remain visible. The existing experiment, capital policies and
Navigator behavior are outside this module.

## Benzinga Pro and richer article content

All-Benzinga coverage is expected from the current provider: Alpaca says its
news data is supplied directly by Benzinga.
[Alpaca historical news documentation](https://docs.alpaca.markets/us/docs/historical-news-data)

BlackPod currently asks Alpaca for `include_content=false`; headline-only input
is an explicit collector choice. Alpaca documents an `include_content` option
for article content **when available**. That does not establish that our
credentials provide every linked article, or that existing retention and
processing bounds are suitable for bodies.
[Alpaca news API reference](https://docs.alpaca.markets/us/reference/news-3)

Benzinga Pro could be useful as a human research workspace: its published
plans include newsfeed and watchlist features, with additional capabilities
depending on the plan. The cited Pro subscription page does not establish a
developer API entitlement, so a Pro login should not be treated as an API key.
[Benzinga Pro subscription features](https://help.benzinga.com/en/articles/2067149-what-is-the-difference-between-subscription-levels)

Benzinga separately offers licensed news APIs with full-story integration.
Those could become an input to BlackPod through an explicitly governed adapter
if access and the intended uses are confirmed.
[Benzinga Stock Market Newswire API](https://www.benzinga.com/apis/cloud-product/stock-news-api/)

Before buying specifically for BlackPod, confirm API access and the terms for
automated retrieval, AI processing, local retention and display. First assess
what the current Alpaca entitlement can lawfully supply. This burst adds no
subscription, direct Benzinga connector, article-body requests or paywall
scraping; richer content would require separate bounded intake validation.

See also [Sentry collection](SENTRY_CATALYST_FEED.md),
[feed latency and coverage](SENTRY_FEED_LATENCY_AUDIT.md), and the
[standalone operating guide](BLACKPOD_STANDALONE_RESEARCH.md).

## Build validation · October 15, 2026

The implementation is additive: new `contracts/sentry_synthesis.py`,
`sentry_synthesis.py`, `sentry_synthesis_transport.py`,
`sentry_synthesis_service.py` and `sentry_synthesis_presentation.py` under
`src/blackpod_build_week/`; read-only routing/worker integration in
`shadow_station.py`; a link in `sentry_catalyst_presentation.py`; this guide and
the README. No native app rebuild or React bundle change is required. The
existing Sentry tab accepts the new local page.

Six new offline suites cover contracts, core evidence/reports, transport,
service lifecycle/recovery, presentation and HTTP:
`tests/test_sentry_synthesis_{contracts,core,transport,service,presentation,http}.py`.

```bash
# Entire Sentry regression suite, including the new module.
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests .venv/bin/python3.11 \
  -m unittest discover -s tests -p 'test_sentry*.py' -q

# Station, frozen experiment, historical baseline and ModelDock regression.
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests .venv/bin/python3.11 \
  -m unittest test_shadow_station test_shadow_station_collection \
  test_shadow_station_macos test_shadow_experiment test_shadow_experiment_capture \
  test_shadow_experiment_cli test_shadow_experiment_reader \
  test_shadow_historical_baseline test_modeldock_client -q
```

Results: **322 tests run, 320 passed, two skipped** in the first command;
**214 passed** in the second. The skipped checks require an explicitly supplied
canonical `BATTLESTAR_PATH`; none was invented. Local fixture HTTP servers need
loopback socket permission. Initial sandbox-only socket-bind failures passed
when rerun with that permission. The final focused synthesis suites passed
136 tests; a subsequent service/presentation rerun passed 48 after the next-check
display was added. All model outputs in these suites are authored fixtures.

Real-data validation used the existing verified Sentry capture prefix. At
`2026-10-15T21:20:44.916557Z` the first local Oracle request received HTTP 422:
the v1 nullable union was unsupported by the appliance. Its original failed
receipt/report remain verified; no challenge ran and no retry was forced.
The corrected v2 Oracle/challenge schemas and one/zero-theme fixture outputs
passed the existing ModelDock pure validator offline using its installed
runtime, without new dependencies or model loading. This does **not** establish
successful real inference or semantic quality. The first accepted real v2 brief
and challenge are still pending at deployment.

The standalone LaunchAgent was gracefully restarted. The new page and JSON
projection, existing Sentry/audit pages, prospective view and both historical
pages returned HTTP 200 with `Cache-Control: no-store`. The worker was enabled
and healthy, its attempt count stayed at one, and its next eligible check was
`2026-10-15T22:20:44.916557Z` (3:20 p.m. Los Angeles), requiring new headline
evidence. Future checks retain the same bounded schedule. ModelDock must remain
available; this module never starts it or switches providers.

The frozen pilot still verified as four events, 25 evidence blobs, zero
orphans, with head
`36a0aa46658e95e049098fb1748e982932aafe45920210a47808f572ec873f4d`.
All nine pinned source files matched pre-burst commit `377f194`. Auto-trading
remained OFF, with entries, worker activation, automatic restart and capital
transfers disabled. No broker/account/order requests were made by this module.

Next: inspect the first accepted scheduled brief and its preserved challenge.
Before richer-content work, separately test the current Alpaca content
entitlement with explicit bounds and confirmed use rights. No subsequent
adapter, subscription or experiment is implemented here.
