# Sentry consolidated market data

Sentry now supports explicitly selected consolidated stock snapshots instead
of continuing single-exchange IEX collection. The current credential profile
denied real-time SIP but returned **15-minute delayed SIP**. New market-volume
cards identify that delay; original IEX evidence is retained unchanged.

This changes observation coverage. It does not validate a narrative, establish
a trading edge, change trading policies or authorize execution. Auto-trading
remains **OFF**. The frozen QQQ/SPY experiment, its source pins, ModelDock and
Galactica trading rules are outside this change.

## What the numbers mean

- **Market volume:** the provider's retained `dailyBar.v` from consolidated
  `sip` or `delayed_sip`, without scaling or extrapolation.
- **15-minute delayed SIP:** consolidated market coverage with an expected
  900-second feed delay. It is not real-time data. The actual minute-bar time,
  capture time and bar age remain visible or retained separately.
- **Historical IEX-only volume:** one exchange's count from an original v1
  capture, not total market volume. It remains valid historical source evidence
  and is never relabeled or replaced with a newer SIP number.
- **Feed unverified:** unknown or inconsistent feed/delay metadata does not
  establish consolidated market coverage. The UI does not invent it.

The daily bar timestamp identifies its **interval start**, not the last time
volume was updated. A recent download does not prove a complete trading day.
The provider aggregate may include eligible extended-hours trades and need not
equal a regular-session-only or final daily total on another site. Volume is
not time-matched relative volume, a liquidity guarantee or an executable quote.
Alpaca describes the distinction between single-exchange IEX and consolidated
SIP in its [market-data FAQ](https://docs.alpaca.markets/us/docs/market-data-faq).
The [snapshot API reference](https://docs.alpaca.markets/us/reference/stocksnapshots-1)
documents the explicit `delayed_sip` option.

For delayed SIP, a source bar age from zero through 1,800 seconds is labeled
**DELAYED**: expected 900-second delay plus the existing 15-minute freshness
tolerance. Older bars are **STALE**. No delay is subtracted from the retained
`bar_age_seconds`. Real-time SIP bars retain the 900-second freshness boundary.
The current-market panel also respects packet-time aging rather than reusing
an earlier capture's freshness label. Capture freshness is a separate ten-minute clock; **FRESH** capture status
does not mean real-time or complete underlying market data.

## Versioned source and control contracts

| Artifact | New consolidated behavior | Historical behavior |
| --- | --- | --- |
| Catalyst control | `blackpod.sentry_catalyst.v2`, explicit `feed` of `sip` or `delayed_sip` | A v1 control is readable but blocks new collection with `MARKET_FEED_CONFIGURATION_REQUIRED` |
| Capture/projection | v2; top-level `market_feed` and `feed_delay_seconds`, plus per-symbol feed/delay metadata | Original v1 IEX projections, identities, bytes and source hashes replay unchanged |
| Snapshot GET receipt | `blackpod.sentry_catalyst_get.v2`; exact fixed endpoint, query/feed, response hash and byte count are bound | Original v1 IEX snapshot receipts remain valid only for their original feed |
| News GET receipt | Existing v1 news contract; headline-only, bounded original query | Unchanged |
| Feed audit/export | v2 when the reviewed prefix includes consolidated captures; feed counts and delay metadata retained | v1-only reports and static exports replay byte-for-byte unchanged, including after later v2 appends |

The mixed-version immutable store binds each projection to its own exact
source response and receipt. Changing a feed in a retained receipt or
projection fails verification. No old capture, original model packet,
interpretation, challenge or narrative-quality evaluation is rewritten.

The service accepts only explicit consolidated feed controls for new work.
There is **no fallback** from SIP to delayed SIP, from delayed SIP to SIP,
or to IEX. A denied entitlement remains a visible failure and follows the
existing cooldown. Choosing another feed requires an explicit configuration
change. `configure` defaults to SIP if omitted; the examples below spell out
`--feed delayed_sip` because that is the feed this profile successfully tested.

The operating schedule is unchanged: weekdays 05:00–17:00 Los Angeles,
minimum five-minute spacing, at most 144 attempted cycles / 288 GETs per LA
day, durable attempt reservation before credential access, no catch-up bursts,
no automatic resends, unchanged request bounds and cooldowns. One ordinary
cycle requests one headline page and one snapshot response for the same
explicit ten-symbol watchlist. Account, orders, capital and model inference
are not part of this collector. The explicit `collect` command also preserves
the hours, spacing, budget, lock and OFF gates.

## Reading the two views

The [Sentry feed](http://127.0.0.1:5183/sentry) shows the latest saved capture's
actual feed, market volume, saved price, change and minute-bar time. The
consolidated label applies only to a known matching feed/delay pair; it does
not imply complete end-of-day volume.

The [market brief](http://127.0.0.1:5183/sentry-synthesis) adds a separate
**Current market context** panel using the latest verified saved consolidated
capture. It is not a new forecast or a rewrite of the narrative. The original
model evidence remains collapsed under **Source evidence · original historical
snapshot**, with its original IEX label, timestamps and count. New observations
are not attributed to the old Oracle brief or its linked evaluation. If no
consolidated capture is available, the panel says so rather than promoting old
IEX data to current consolidated context. Page reads do not acquire data or
start inference.

## Bounded real entitlement evidence — October 15, 2026

The explicitly authorized check made **one snapshot GET per feed**, for the
same ten-symbol watchlist, with no pagination, retries or automatic fallback.
It retained metadata and exact source bytes under the ignored local directory
`output/sentry-consolidated-feed-check-2026-10-15-001/`.

| Request | Result | Retained evidence |
| --- | --- | --- |
| `feed=sip` | HTTP **403**; one request | `sip/result.json` records `HTTP_ERROR`; real-time SIP was not available to this profile |
| `feed=delayed_sip` | HTTP **200**; one request; all ten symbols | `delayed_sip/result.json` records `AVAILABLE` and response SHA-256 |

The delayed response reported GOOGL `dailyBar.v = 19243640`, displayed as
**19,243,640 shares**. Its daily-bar start was `2026-10-15T04:00:00Z`; its minute
bar was `2026-10-15T23:58:00Z` (4:58 p.m. PDT). Response SHA-256:
`03d16e7aad6e3fd2a3c3c6dee5eca39d0151de9bd4930e652a9648be1a66cca0`.

The preserved brief's earlier IEX count of **501,362** remains unchanged.
These numbers come from different feeds and capture times; their difference
is not a same-time error calculation, a trading outcome or an independently
verified final daily total. Successful sample access does not guarantee future
entitlement, every symbol, real-time access or another provider's matching count.

The check made no broker/account/order, capital, inference or article-content
requests. It did not place a trade or update the frozen experiment. These
transport checks are separate from a complete scheduled Sentry capture.

## Configuration and offline checks

Run from `/Users/nikolai/Projects/blackpod_battlestar_build_week`:

```bash
# Configure the explicit tested feed, paused. This does not acquire data.
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python3.11 \
  -m blackpod_build_week.sentry_catalyst_service configure \
  --config output/blackpod-shadow-station/config.json \
  --symbols SPY,QQQ,NVDA,AMZN,LULU,NKE,DG,PG,CLX,GOOGL \
  --feed delayed_sip

# For enabled collection, use the same command with --enabled.
# This preserves the existing schedule and budget; no immediate fetch is implied.

# Read saved status and verify the complete source store; no provider calls.
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python3.11 \
  -m blackpod_build_week.sentry_catalyst_service status \
  --config output/blackpod-shadow-station/config.json

PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python3.11 \
  -m blackpod_build_week.sentry_catalyst_service verify \
  --config output/blackpod-shadow-station/config.json
```

Keep existing state and budgets. Use the owned service lifecycle from the
[standalone runbook](BLACKPOD_STANDALONE_RESEARCH.md); do not run a competing
collector, delete a lock, backdate a clock or reset attempts to force data.

Offline fixtures cover consolidated and delayed receipts/projections, changed
feed/query/version rejection, legacy-control refusal, exact integer share
formatting, unavailable bars, delay boundaries, immutable mixed-version replay,
unchanged v1 audit exports, read-only HTTP and separation of current observations
from original model evidence. Fixtures establish deterministic behavior; only
the two retained GET results above establish actual profile access.

## Actual initial capture and deployment

After the separate probes, one explicitly authorized operator bootstrap
captured a fresh headline page and delayed SIP snapshots at **9:17:53 p.m. PDT
on October 15, 2026** (`2026-10-16T04:17:53.932105Z`). This was a one-time
initialization outside ordinary collection hours, recorded through the private
bounded script `output/sentry-consolidated-feed-check-2026-10-15-001/activate_capture.py`.
It did not change the ordinary CLI/worker schedule or add an after-hours mode.

Already executed once; **do not rerun**. The retained intent guard refuses a
repeat rather than sending another request:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python3.11 \
  output/sentry-consolidated-feed-check-2026-10-15-001/activate_capture.py
```

The script verified the owned idle LaunchAgent, stopped it during the capture,
held `.station.lock`, retained an activation intent, and advanced the durable
daily attempt counter **70 → 71**, without resetting it. It requested fresh
news and snapshots rather than promoting the earlier entitlement response into
a capture. The managed station restarted successfully in its `finally` path.
The selected control is enabled for the same ten symbols with
`feed=delayed_sip`.

Actual retained capture result:

- Status **CAPTURED**; all ten contexts parsed. All ten are honestly **STALE**
  because this capture occurred after trading/extended-hours observations ended;
  successful access does not make those bars current.
- GOOGL volume **19,243,640 shares**; minute bar `2026-10-15T23:58:00Z`.
- Capture ID `97219bc54279bf27aea76b713e7360b21343843b92ad4eacd8355489b2be2a69`.
- Verified store: **71 captures**, including 70 historical IEX and one delayed
  SIP capture; **225 evidence blobs**, zero orphan evidence or staging remnants.
- Head SHA-256 `50cf44690baae396f92b192958e285ca2ce0950abde3de94b5de35a50d75b6b6`.
- Result metadata: `output/sentry-consolidated-feed-check-2026-10-15-001/activation/result.json`.

There were **four market-data GETs in total**: the two separately requested
entitlement checks, then one fresh news GET and one delayed SIP snapshot GET
for initialization. No inference, order, broker/account or capital request was
made. Auto-trading stayed **OFF**.

After restart, the local Sentry, synthesis, audit and station read-only APIs
returned HTTP 200 with `Cache-Control: no-store`. Sentry and the separate current
market panel showed the consolidated count; the original report still held
its earlier IEX count of 501,362 and its narrative evaluation remained
**AVAILABLE**. The audit used v2 with 70 historical IEX / one delayed SIP capture.
The retained real v1 audit export still verified against its original six-capture
prefix, and the original narrative evaluation verified again with zero provider
calls. These checks establish retained-data bindings and local serving, not
real-time market freshness or uninterrupted future uptime.

The post-deployment proof in `activation/after.json` confirmed that all 70
original source entries, all nine original synthesis capsules, station
configuration, synthesis control and frozen protocol/pilot journal were
unchanged. Only the catalyst feed control was deliberately upgraded. The
existing managed service resumed; no new automation was scheduled.

## Final offline regression results

**789 tests ran: 787 passed and two optional canonical-checkout checks were
skipped because `BATTLESTAR_PATH` was not configured.** These tests use authored
fixtures/in-memory transport; they did not make the real GETs above.

| Suite | Actual result |
| --- | --- |
| Sentry synthesis service | 99 passed in 365.717 seconds |
| Other Sentry modules, including v2 audit and reader-time freshness corrections | 506 ran; 504 passed, two optional skips, in 14.739 seconds |
| Station, frozen experiment, historical baseline and delivery | 184 passed in 34.500 seconds |

Exact offline commands:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests .venv/bin/python3.11 \
  -m unittest test_sentry_synthesis_service -q

PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests .venv/bin/python3.11 - <<'PY'
from pathlib import Path
import unittest
names=[p.stem for p in sorted(Path('tests').glob('test_sentry*.py')) if p.stem!='test_sentry_synthesis_service']
suite=unittest.TestSuite(unittest.defaultTestLoader.loadTestsFromName(n) for n in names)
r=unittest.TextTestRunner(verbosity=1).run(suite)
raise SystemExit(not r.wasSuccessful())
PY

PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests .venv/bin/python3.11 \
  -m unittest test_shadow_station test_shadow_station_collection \
  test_shadow_station_macos test_shadow_experiment test_shadow_experiment_capture \
  test_shadow_experiment_cli test_shadow_experiment_reader \
  test_shadow_historical_baseline test_modeldock_delivery -q
```

Remaining limits are explicit: this profile has **delayed**, rather than
real-time, consolidated access; an after-hours snapshot can remain stale;
daily volume is not guaranteed final or regular-session-only; and the original
Oracle brief has not been regenerated with the new market data. No new strategy,
prediction experiment, narrative revision, automated policy change or trading
authority follows from this update.
