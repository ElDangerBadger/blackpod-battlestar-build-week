# Bounded Alpaca article-content probe

This is a one-request technical check of article content available through the
existing Alpaca credentials. It is separate from the running Sentry feed,
Oracle synthesis, the frozen reversal experiment and all trading behavior.
**Auto-trading stays OFF.** No subscription is purchased and no Benzinga Pro
login, direct Benzinga adapter or paywall scraping is introduced.

The sequence is deliberate: **review an accepted Oracle brief and its accepted
challenge first**, then bind the content check to that exact report. A failed
draft, draft-only report or unverified challenge does not satisfy the gate.

## Validation record

**Latest, October 15 at 4:13 p.m. Los Angeles:** the separately authorized
v2 validation reached ModelDock but returned `MODELDOCK_HTTP_504` after about
90 seconds. Both failures are preserved. No accepted pair exists and no
article-content GET ran. The native endpoint and named client activity are
verified. See [actual validation evidence and commands](SENTRY_V2_VALIDATION_STATUS_2026-10-15.md).
The preparation and earlier continuation records below describe their
original observation times.

**Pending:** the first accepted Oracle/challenge pair has not yet been recorded
in this runbook. No article-content probe result is claimed here. The report
ID, review findings, actual command, response summary and integrity checks must
be recorded after they exist. Do not substitute fixture results for a real
accepted pair or a real content response.

Preparation on October 15, 2026: the retained ledger had one failed Oracle
attempt, no accepted draft and no challenge. The synthesis worker was healthy,
ModelDock reported READY, and the next eligible attempt was
`2026-10-15T22:20:44.916557Z` (3:20 p.m. Los Angeles). The explicit probe correctly
rejected that failed report with `REVIEW_PAIR_NOT_ACCEPTED` before reading
credentials or creating an output directory. No content GET has been made.

The probe implementation and forty authored offline tests are ready. Full
Sentry regression: 362 tests run, 360 passed, two optional canonical-checkout
checks skipped. Station, frozen-experiment and historical-baseline regression:
173 passed. Initial local fixture socket-bind errors passed when rerun with
loopback permission; no real provider or inference requests were used by these
tests. Exact commands:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests .venv/bin/python3.11 \
  -m unittest test_sentry_content_probe -q

PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests .venv/bin/python3.11 \
  -m unittest discover -s tests -p 'test_sentry*.py' -q

PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests .venv/bin/python3.11 \
  -m unittest test_shadow_station test_shadow_station_collection \
  test_shadow_station_macos test_shadow_experiment test_shadow_experiment_capture \
  test_shadow_experiment_cli test_shadow_experiment_reader \
  test_shadow_historical_baseline -q
```

The one-time continuation ran on **October 15 at 3:27 p.m. Los Angeles**.
No accepted pair existed: the current headline signature matched the previous
failed attempt, so the unchanged-evidence gate prevented another request.
Sentry captures and both workers were healthy. No content GET, main merge or
push occurred. The follow-up was paused without another schedule; the
unfinished branch remains unmerged. See the
[dated status and supporting evidence](SENTRY_CONTENT_CHECK_STATUS_2026-10-15.md).
BlackPod's own bounded schedules remain unchanged.

## Review the first accepted pair

Open [Market synthesis](http://127.0.0.1:5183/sentry-synthesis), or inspect the
provider-free saved status and verification:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python3.11 \
  -m blackpod_build_week.sentry_synthesis_service status \
  --config output/blackpod-shadow-station/config.json

PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python3.11 \
  -m blackpod_build_week.sentry_synthesis_service verify \
  --config output/blackpod-shadow-station/config.json
```

Check for a retained `CHALLENGED_INTERPRETATION` report, with accepted Oracle
and challenge receipts and a verified original source prefix. Preserve its
exact `report_id`. Verification establishes internal bindings, not that the
interpretation is true or that the review is economically independent.

Read each theme alongside its challenge:

- Resolve the cited evidence IDs to the report's original evidence packet.
  Check the headline, provider article ID, revision, publication/update clocks
  and BlackPod first-seen clock. Do not replace the original packet with a newer
  feed when evaluating what the model actually saw.
- Separate quoted headline observations from inferred causes or implications.
  A headline tagged with a symbol does not establish materiality, novelty or a
  verified portfolio exposure.
- Preserve challenge dissent, alternative explanations and missing evidence.
  A separate prompt using the same catalog is a separate review pass, not proof
  of independent sources or a different underlying model.
- Check single-publisher concentration, truncated news pages, selected/omitted
  headline counts and stale IEX context. A minute close versus previous daily
  close is not a measured post-headline reaction or matched SPY/QQQ excess.
- Record what is source-supported, what remains speculative, what was
  contested, and what further evidence is needed. Unknown holdings, horizons
  and business economics must remain unknown.

This review never edits the original draft or challenge, changes the frozen
experiment, or grants authorization to trade. If no accepted pair exists, the
content request remains blocked. Do not reset the ledger, force inference or
retry uncertain delivery to manufacture a qualifying report. The separately
authorized `validate-v2` path described in the synthesis guide can retain one
linked compatibility validation of a terminal failed v1 attempt. A resulting
accepted pair is still historical interpretation of its original packet and
needs the same manual review before this content probe; it is not a new market
forecast. Verification replays its parent linkage as well as both responses.

## Exact probe bounds

| Bound | Behavior |
| --- | --- |
| Required parent | Exact retained, verified `CHALLENGED_INTERPRETATION` report |
| Watchlist | Exact symbols from that reviewed report; maximum ten |
| Endpoint | HTTPS GET only: `https://data.alpaca.markets/v1beta1/news` |
| Interval | Explicit UTC start/end covering the preceding 24 hours |
| News request | Updated-first; `limit=3`, `include_content=true` |
| Request budget | One request; no pagination, automatic retry, proxy or redirect |
| Transport | Verified TLS; 20-second deadline; 1 MiB response cap |
| Evidence | Private immutable response, receipt and availability summary in a separate output directory |
| Forbidden effects | No broker/account/order APIs, inference, article-link fetching, HTML rendering or running-feed configuration changes |

The existing collector's headline-only query is not relaxed. The probe uses a
separate bounded interface and output root. It does not promote returned bodies
into the Sentry capture store, model catalog, UI, pilot journal or training
data. Raw article HTML is untrusted retained evidence and is never executed or
rendered.

OFF verification, the reviewed report's source integrity and frozen source pins
are checked around capture. Failed gates block the probe. Retained evidence
cannot be overwritten, repaired or silently replaced to make verification pass.
Credentials stay in their existing local source and must never appear in
commands, output, receipts, logs or Git.

## Commands

Run from `/Users/nikolai/Projects/blackpod_battlestar_build_week`. Replace the
reviewed-report placeholder with the exact verified report ID after completing
the review above. The example output directory must be a direct child of checkout
`output/`, separate from all source, runtime, station, historical and credential
roots.

```bash
# One explicit capture, gated by the exact reviewed accepted report.
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python3.11 \
  -m blackpod_build_week.sentry_content_probe capture \
  --config output/blackpod-shadow-station/config.json \
  --output output/sentry-content-entitlement-probe-001 \
  --reviewed-report-id 'sentry-synthesis-<reviewed report SHA-256>'

# Read retained technical availability; no provider request.
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python3.11 \
  -m blackpod_build_week.sentry_content_probe status \
  --config output/blackpod-shadow-station/config.json \
  --output output/sentry-content-entitlement-probe-001

# Verify original retained bytes, hashes, report and source bindings; no request.
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python3.11 \
  -m blackpod_build_week.sentry_content_probe verify \
  --config output/blackpod-shadow-station/config.json \
  --output output/sentry-content-entitlement-probe-001
```

Do not delete an output directory or create a fresh identity to resend an
uncertain request. Interrupted or missing evidence stays visible; an outage,
timeout, oversized response, malformed response or HTTP rejection is not
permission to retry, change credentials, buy access or widen the request.

## Interpreting the result

An HTTP success with nonempty article content demonstrates **technical
availability for the returned sample**. It does not prove every linked story is
available, every body is complete, coverage is timely, or a Pro subscription is
needed. An empty/contentless sample is inconclusive about broader access.

Use the metadata summary: article IDs, source/time metadata, body-present/empty
counts, response size and integrity hashes. Do not copy article bodies into
chat or render their HTML. Authentication/authorization/rate-limit failures are
reported as bounded failures, with credentials and provider error bodies kept
out of the public summary.

Technical access does not establish contractual rights for every intended
use. Before expanding intake, confirm applicable terms for automated retrieval,
AI processing, retention and display, and define new storage and processing
bounds. Full-text processing or UI display requires separately scoped work;
this probe does not enable it.

## Provider documentation

Alpaca documents `include_content` as requesting article content when available,
alongside page limits, intervals and pagination.
[Alpaca news API reference](https://docs.alpaca.markets/us/reference/news-3)

Alpaca states its news data is supplied directly by Benzinga, which explains the
current publisher concentration.
[Alpaca historical news documentation](https://docs.alpaca.markets/us/docs/historical-news-data)

Benzinga's Pro plan descriptions concern the research workspace; that page
does not establish developer API entitlement. Benzinga separately offers
licensed news APIs supporting article integration. Do not buy Pro solely for
BlackPod before verifying the required access and use terms.
[Benzinga Pro features](https://help.benzinga.com/en/articles/2067149-what-is-the-difference-between-subscription-levels),
[Benzinga Stock Market Newswire API](https://www.benzinga.com/apis/cloud-product/stock-news-api/)

See [synthesis operation and limitations](SENTRY_ORACLE_SYNTHESIS.md) and
[Sentry collection bounds](SENTRY_CATALYST_FEED.md).
