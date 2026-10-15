# Sentry catalyst feed — bounded observations

Open **BlackPod.app → Sentry**, or [the local Sentry page](http://127.0.0.1:5183/sentry).
This is an independent evidence feed. It does not change the frozen reversal
experiment, run agents or inference, recommend trades, submit orders, allocate
capital, or enable auto-trading. Galactica trading rules are not used.

## What to watch

- **Headline cards:** provider source link, publication/update time, BlackPod's
  first-seen and last-observed times, and the number of observed revisions.
- **Symbol tiles:** IEX minute close versus the provider's previous daily close,
  day volume, and the actual minute-bar timestamp. These are USD price proxies,
  not executable quotes or a trade simulation.
- **Warnings:** stale prices, stale captures, unavailable symbols, failed
  collection, and incomplete news pages. A fresh download does not establish
  that its underlying prices or headlines are current.

The initial watchlist is the user's explicit selection:
**SPY, QQQ, NVDA, AMZN, LULU, NKE, DG, PG, CLX, GOOGL**.
These are observation targets, not approved holdings or desk ownership.

Publication time, provider update time, first observed by BlackPod, capture
time, bar time, and reader time are separate facts. Initial startup can discover
old news; it cannot claim to have observed it at publication. Subsequent article
versions append, preserving original observations and the original first-seen
time. First-seen means the first **complete, validated** observation in this
store; a successful orphan transport response is not promoted to a complete
observation after a failed cycle. Exact source bytes remain available for audit.

Day volume is **not unusual/relative volume**: comparing an incomplete day with
a full day would be misleading. Price movement does not prove headline
causation or an opportunity remaining after detection. There are no sentiment,
earnings-surprise, analyst-revision, insider-trade or legal-event classifiers.
Those event-specific feeds and a testable predictive hypothesis remain future,
separately authorized work. This feed is not another trading experiment.

## Bounds and actual provider interfaces

The existing launchd research station supervises an independent Sentry thread:

| Bound | Version 1 behavior |
| --- | --- |
| Watchlist | Explicit, unique, 1–10 normalized symbols |
| Monitoring | Weekdays, 05:00–17:00 America/Los_Angeles, DST aware |
| Polling | At least five minutes between attempts; no catch-up burst |
| Daily budget | Maximum 144 attempted cycles / 288 GETs per LA day |
| Endpoints | Only Alpaca news and stock snapshots; never account/order APIs |
| News | Latest updated-first page, preceding 24 hours, maximum 50 items; no full article content |
| Prices | Explicit `feed=iex`; no automatic entitlement/feed substitution |
| Transport | HTTPS, GET, verified TLS, no proxy/redirect, 20-second request deadline, 1 MiB response bound |
| Failures | No immediate retry; 15-minute cooldown, 75 minutes for HTTP 401/403/429 |
| Evidence capacity | 4,096 complete captures or 256 MiB total evidence/entries/staging; manual archive review required |

Monitoring hours are a weekday operating schedule, **not an exchange calendar**;
holiday or closed-market snapshots may be stale. The Mac must remain awake,
online, and logged in. The app window and Codex may be closed. Overnight/weekend
coverage is absent. Polling, provider latency and subscription coverage prevent
any claim of getting news before other traders. Prices over 15 minutes old are
explicitly STALE; capture freshness is independently limited to ten minutes.

The endpoints and response roles are documented by Alpaca:
[news](https://docs.alpaca.markets/reference/news-3) and
[snapshots](https://docs.alpaca.markets/reference/stocksnapshots-1).
Alpaca describes IEX as one exchange, not consolidated SIP coverage. News
pagination means one bounded page may omit relevant articles. The UI preserves
that warning; it does not automatically request another page or replace feeds.
No provider article pages are scraped. Explicitly clicked HTTPS source links
open in the user's browser, outside the native app's local webview.

## Persistence and recovery

Operational files live under the existing station's `catalyst/` directory,
separate from the pilot journal, historical bundles and runtime:

- `control.json`: versioned enabled flag and exact watchlist.
- `state.json`: last attempt/success, daily budget and sanitized failure code.
- `health.json`: independent worker heartbeat; an old success does not imply a running worker.
- `evidence-store/evidence/`: immutable exact successful response/GET receipt bytes, named by SHA-256.
- `evidence-store/entries/`: immutable sequential, hash-linked captures binding
  evidence, projection and observation-only authority.
- `evidence-store/staging/`: safe interrupted publication remnants, reported by verification.

Uses the existing safe descriptor-based immutable publisher. No decision
journal contracts, mission schemas or frozen code pins were changed. Captures
are replayed from retained source bytes. Same capture retries are idempotent;
revisions are new captures. Conflicting evidence, chain gaps, hash mismatches,
unsafe links, backward clocks and invalid numerical/provider data fail closed.
One bad symbol's bars become explicitly unavailable, never invented prices.

The attempt budget persists **before** credentials are read or requests begin.
A crash consumes its attempt. A successful first endpoint remains as immutable
orphan evidence if the other fails, without manufacturing a complete capture or
alert. Later success appends normally. No repair, retrospective first-seen
assignment, deletion or automatic capacity reset occurs. Capacity includes
orphan evidence and staging. Back up the entire store; Git contains code, not
ignored local observations. Hashes establish internal integrity, not an
independent authenticated proof of original publication or capture time.

The independent worker lock prevents a manual collector from competing with
the running station. A Sentry failure does not call or stop the separate pilot
collector. A failed OFF verification blocks capture and clears displayed
context. Worker failures/staleness are visible independently of capture age.
No credentials, provider exception bodies or absolute private paths are exposed
in the read-only HTTP projection. Credentials are read from the existing local
source; none are bundled with the app or committed.

## Commands

Run from `/Users/nikolai/Projects/blackpod_battlestar_build_week`:

```bash
# Offline status: does not collect or call providers.
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python3.11 \
  -m blackpod_build_week.sentry_catalyst_service status \
  --config output/blackpod-shadow-station/config.json

# Offline full evidence/chain/projection verification.
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python3.11 \
  -m blackpod_build_week.sentry_catalyst_service verify \
  --config output/blackpod-shadow-station/config.json

# Pause Sentry only: omit --enabled. The pilot remains independent.
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python3.11 \
  -m blackpod_build_week.sentry_catalyst_service configure \
  --config output/blackpod-shadow-station/config.json \
  --symbols SPY,QQQ,NVDA,AMZN,LULU,NKE,DG,PG,CLX,GOOGL

# Resume the same watchlist: add --enabled to the command above.
```

`collect --config ...` is an explicit maintenance command that preserves the
same hours, budget, minimum delay, evidence and OFF gates. It is blocked by the
worker's lock while the station runs; stop the managed station before using it.
Never reset retained state to force a request. UI GET/HEAD reads do not collect;
mutating methods, arbitrary paths and cross-origin requests are rejected.

For app packaging, service lifecycle and rollback, see the
[standalone runbook](BLACKPOD_STANDALONE_RESEARCH.md). The Sentry view is served
on existing port 5183 at `/sentry`; `/sentry.json` is its read-only projection.
The existing experiment and historical pages are unchanged. The updated native
window has a fourth Sentry tab. Reopen the window after installing its new binary.

## Validation

Offline tests use authored fixtures and forbid real transport. They cover strict
watchlists, source clocks, exact arithmetic, unavailable/stale symbols,
pagination, revisions, escaped headlines, authority isolation, immutable source
binding, idempotency, interruption/orphan recovery, chain tampering, symlink and
hardlink refusal, capacity, persisted attempts, hours/DST, request bounds,
credential-redaction, failure cooldowns and read-only HTTP behavior.

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests .venv/bin/python3.11 \
  -m unittest test_sentry_catalyst test_sentry_catalyst_capture \
  test_sentry_catalyst_service test_shadow_station \
  test_shadow_station_collection test_shadow_station_macos \
  test_shadow_experiment test_shadow_experiment_cli \
  test_shadow_experiment_capture test_shadow_historical_dashboard \
  test_shadow_historical_baseline test_shadow_historical_cli -q
```

The first real bounded capture on October 15, 2026 at 11:07:36 a.m. PDT retained
**50 headlines and all ten symbol snapshots**, four evidence blobs, zero orphans,
and a verified capture. The news page was truncated. All ten price-bar timestamps
were roughly an hour behind capture and therefore explicitly STALE; this is
not a verified real-time price feed. Offline fixtures and successful HTTP
capture do not establish freshness, complete news coverage, predictive edge,
net profitability or trading authority. Further live captures append under the
same bounds; they do not evaluate or tune the frozen reversal rule.

Deployment validation on October 15, 2026:

- **249 selected offline tests passed in 27.962 seconds**, using the command above.
- The native four-tab app compiled, installed and reopened. Desktop and narrow
  browser layouts were visually checked; the page has no client script or
  provider calls. Read-only source links and evidence clocks are visible.
- The background worker completed its next scheduled capture at **11:12:54 a.m.
  PDT**, independently of the manual validation. Two complete captures, eight
  evidence blobs and zero orphans/staging remnants verified. In that second
  capture, six symbol minute bars were recent and four were explicitly stale.
- The frozen pilot stayed at four events and 25 evidence blobs with the same
  head hash; its nine pinned source files were unchanged. Auto-trading stayed
  OFF with entry, worker, restart and transfer guards disabled.

Internal staging/evidence hardlinks left by an interruption after atomic link
publication are accepted only when every inode link is accounted for inside
this store. External hardlinks remain rejected. Recovery never deletes evidence
or resets the attempt budget. Source hashes are not cryptographic signatures.

The next recommended work is a bounded **latency and coverage audit** of this
feed before proposing an event-driven prediction rule. Do not infer edge from
alert counts or silently replace the existing frozen experiment.
