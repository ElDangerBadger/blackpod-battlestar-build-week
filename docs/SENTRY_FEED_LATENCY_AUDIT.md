# Sentry feed latency and coverage audit

Open **BlackPod → Sentry → Feed quality audit**, or
[the read-only audit page](http://127.0.0.1:5183/sentry-audit).
The page refreshes its analysis of saved observations every minute; it never
requests market data or headlines. The original Sentry collector keeps its
existing watchlist, feed, bounds, budget and schedule. The frozen reversal
experiment, auto-trading controls and decision policies are unchanged.

## What the measurements mean

| Measurement | Definition and denominator |
| --- | --- |
| Verified captures | Complete source-bound captures in one verified immutable prefix |
| Baseline headlines | First sighting during the first capture, or the first capture after a watchlist-set change; not live detection |
| Later headline discoveries | Unique provider article IDs first seen after that cohort's baseline; not necessarily newly published stories |
| Discovery lag | Publication to first complete validated observation; measured once per later-discovered article |
| Version lag | Provider update time to first complete observation of each distinct observed revision |
| Repeated observations | Total article appearances minus distinct observed versions; repeated polls are not new alerts |
| Fresh at capture | Minute-bar timestamp at most 15 minutes old when captured; not executable quote quality |
| Stale/unavailable/future | Separate states; their counts plus recent bars partition the requested symbol/capture pairs |
| Bar age now | Latest retained bar's timestamp versus the audit clock, independently of historical capture freshness |
| Per-symbol headlines | Distinct articles actually observed for that symbol; zero does not prove absence of news |
| Empty nominal slots | Fully elapsed weekday LA five-minute slots without a complete capture, starting with the first observed capture's slot |

Distributions report minimum, nearest-rank p50/p95 and maximum in integer
milliseconds. Empty samples have null statistics, not zero latency. Negative
clock lags are excluded from distributions and counted explicitly; future
price timestamps are not classified as fresh. Reordering an unchanged watchlist
does not create a new cohort. Symbol denominators follow the watchlist actually
recorded in each capture. A headline can concern multiple symbols, so summing
symbol headline counts need not equal the unique-article total.

Discovery lag mixes provider availability, polling, downtime, pagination,
selection and local recording delay. It is **not independently measured provider
latency** and does not establish that BlackPod saw an event before other traders.
Baseline articles and repeated readings cannot establish fast discovery.

Five-minute nominal slots are a descriptive reference grid, not a new scheduler
or service-level promise. The collector uses a minimum interval plus processing
and worker-loop time. Missing slots can result from that timing, pauses, sleep,
failed requests or unavailable data. Only complete captures have an immutable
history; the current operational state is not a historical attempt ledger.
Overnight/weekend time is excluded from nominal slots, but wall-clock
inter-capture gap distributions include it. Monitoring weekdays are not an
exchange holiday calendar. The currently open five-minute slot is excluded.
Nothing before the first recorded capture is called a missed poll.

These remain **unknown**:

- Overall news coverage and number of omitted articles: there is no independent
  news universe, and truncated responses explicitly indicate another page.
- Actual HTTP request duration: GET receipts contain completion timestamps,
  but no request-start timestamp.
- Historical failed-attempt count, pause duration, and uptime: no immutable
  attempt/control/heartbeat ledger was recorded.
- Causal price impact, predictive edge, net returns or trading readiness.

## First retained real-data audit

The first immutable report is under
`output/sentry-feed-audit-2026-10-15-001/`, with report ID
`sentry-audit-ee1aca3739cadf3d07e70b394e0d2eac92a927360bec9f044193b763b542d129`.
Its as-of clock is **October 15, 2026, 11:33:17 a.m. PDT**.
The source window is **11:07:36–11:33:13 a.m. PDT**, approximately 26 minutes.
The source head is
`47f5ae3ecebfce8015c92f905d26c2c1601b55be71127875b8b3cc84c7fb4b26`.

| Result | Observed value |
| --- | --- |
| Complete verified captures | 6 |
| Distinct headlines | 54 |
| Startup-baseline headlines | 50 |
| Later-discovered headlines | 4 |
| Later discovery lag: min / p50 / p95 / max | 4.67 / 5.50 / 8.38 / 8.38 minutes |
| Repeated article-version appearances | 246 |
| Truncated news responses | 6 of 6 |
| Recent price observations | 46 of 60 symbol/capture pairs (76.7%) |
| Stale price observations | 14 of 60 (23.3%) |
| Missing/future price observations | 0 / 0 |
| Inter-capture gaps: p50 / maximum | 5.06 / 5.30 minutes |
| Fully elapsed nominal slots with a capture | 5 of 5; the current slot is excluded |
| Orphan evidence / staging remnants | 0 / 0 |

This is evidence that collection and retention worked during this short window.
It does not establish long-term uptime or event-trading suitability. Every news
response was incomplete, four later discoveries are a very small sample, and
nearly one-quarter of the price observations were stale. The initial 50
headlines are an initial inventory, not 50 timely alerts. There is no basis here
to claim a fast, comprehensive news feed or a predictive trading edge.

The live page will incorporate later captures. The exported report remains
fixed; later observations never rewrite it. The source captures continue under
the already authorized Sentry policy, independently of the frozen pilot.

## Offline commands and immutable exports

From `/Users/nikolai/Projects/blackpod_battlestar_build_week`:

```bash
# Print a fresh descriptive report from retained evidence; zero provider calls.
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python3.11 \
  -m blackpod_build_week.sentry_catalyst_audit \
  --config output/blackpod-shadow-station/config.json

# Export to a NEW separate output directory. No overwriting existing reports.
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python3.11 \
  -m blackpod_build_week.sentry_catalyst_audit \
  --config output/blackpod-shadow-station/config.json \
  --output-root output/sentry-feed-audit-next

# Replay the retained first report against its original source prefix,
# even after later captures have appended.
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python3.11 \
  -m blackpod_build_week.sentry_catalyst_audit \
  --config output/blackpod-shadow-station/config.json \
  --verify-export output/sentry-feed-audit-2026-10-15-001
```

Optional `--as-of` fixes an aware audit clock for deterministic report creation.
It must not precede the selected source prefix or lie in the future. An ordinary
new audit reads the entire current verified prefix; use `--verify-export` to
replay an older report after new captures append. Identical prefix, clock and
v1 method produce identical JSON/report ID. Retrying export with identical
content is idempotent; a changed report conflicts instead of replacing files.

Exports contain `report.json`, a static `report.html`, and a hash/size manifest
published last. Interrupted exports retain complete files and can be retried
with identical content. Export paths must be separate from all source, runtime,
station and credential roots. Keep the export together with its source store;
Git does not back up ignored local evidence. Hashes are integrity checks,
not independently authenticated publication/receipt times or signatures.
Version-1 replay verifies the source prefix, deterministic metrics, report ID,
file hashes and the version-1 rendered HTML. Future implementations must retain
v1 replay compatibility or explicitly introduce a new report version.

Live routes `/sentry-audit` and `/sentry-audit.json` retain the station's host,
origin, method and no-store restrictions. Both are read-only. Failed source
verification or failed OFF checks yield an explicit unavailable result with no
cached numerical substitute. Audit work never reads credentials, calls
providers, modifies observations, changes a watchlist, or invokes agents.

## Validation and next recommendation

**271 selected offline tests passed in 28.335 seconds**, including 22 new audit
tests. They cover baseline exclusion, deduplication/revisions, exact
percentiles, clock anomalies, changing symbol denominators, DST/weekend slots,
source tampering, no-provider boundaries, immutable export/recovery, replay
after later appends, HTML escaping and read-only HTTP behavior. The native app
compiled with the Sentry audit kept under its Sentry tab.

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests .venv/bin/python3.11 \
  -m unittest test_sentry_catalyst_audit test_sentry_catalyst \
  test_sentry_catalyst_capture test_sentry_catalyst_service \
  test_shadow_station test_shadow_station_collection test_shadow_station_macos \
  test_shadow_experiment test_shadow_experiment_cli test_shadow_experiment_capture \
  test_shadow_historical_dashboard test_shadow_historical_baseline \
  test_shadow_historical_cli -q
```

The actual six-capture report exported and replayed successfully against real
retained evidence. No extra provider collection was requested for this audit.
The original reversal journal remained at four events/25 blobs with unchanged
head `36a0aa46658e95e049098fb1748e982932aafe45920210a47808f572ec873f4d`.
Its pinned source files remain unchanged and auto-trading remains OFF.

Recommended next burst: **bounded news pagination with append-only request and
attempt timing receipts**, after explicit authorization. This would address the
observed coverage cap and make transport/failure measurements possible. It must
preserve the observation-only boundary and frozen experiment. No feed switching,
pagination expansion, timing instrumentation, strategy selection or trading
authority was introduced by this audit burst.

The user's subsequent product direction is an evidence-backed **Sentry-to-Oracle
market synthesis**, followed by independent challenge and separate trading versus
investment review. Existing Oracle narrative-enrichment and native Senate review
interfaces are candidates for reuse; neither is connected to this Sentry news
feed by the audit. A synthesis must distinguish facts, hypotheses, alternatives,
horizons and invalidation conditions, cite retained evidence and disclose these
feed-quality gaps. Watchlist interpretation is possible without holdings;
portfolio impact requires verified positions, ownership and exposures. No new
agent, inference run, portfolio recommendation or execution authority was added.
The pagination/timing recommendation above remains an input-quality follow-up,
not an automatic change or a substitute for governed synthesis.
