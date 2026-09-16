# Read-only live Navigator prices

The September 16 authorization permits a narrow canonical Battlestar backend
extension: load existing Alpaca credentials and supply market-data-only live
prices to the Build Week consumer. This does not enable execution, orders,
portfolio changes, new mission authority, or ModelDock calls. It does not modify
the recorded `BROKER_CALL` prohibition on operational Navigator plans.

## Data and evidence remain separate

- Canonical Navigator owns Alpaca authentication, the shared upstream stream,
  price normalization, and source timestamps. The browser receives no secrets.
- Saved history, candles, moving averages, Oracle/Council/Governor results,
  mission correlation, and Reference Tape evidence remain immutable.
- The ship follows a separate **last received trade**, not a rewritten bar
  close. Its lateral displacement uses the existing renderer's price axis with
  the captured close as a fixed reference. The camera is not reset on ticks.
  Extreme displacement is visibly capped at the visual edge; the numeric price
  is not capped. The cyan endpoint/connector is not a historical candle.
- The MA remains the **captured MA**, not a live recalculation. A same-source
  historical/rolling-MA update is separate future work. No browser indicators
  or synthetic ticks are created.
- Live prices are available only while the expanded, visible LIVE Navigator
  is open. Symbol changes release the old subscription; interval/MA changes
  reuse the selected symbol's feed. Pause, captured-reference mode, hidden tabs,
  and closing the modal stop that viewer's subscription. Other viewers may
  keep the shared upstream connection active.
- Replay, original desk charts, and the Reference Tape remain captured evidence.

## Credential source

Canonical Navigator reads `APCA_API_KEY_ID` and `APCA_API_SECRET_KEY` when both
are supplied in its server process. Otherwise it reads
`~/buried_treasure/api_keys.yaml`, specifically the existing `alpaca.key_id` and
`alpaca.secret_key` fields. An explicit `BPN_ALPACA_CREDENTIALS_FILE` can select
a different local file. A partial environment pair fails closed.

No keys are copied into this repository, URLs, browser storage, or JavaScript.
Do not paste keys in chat. The YAML's `base_url` is deliberately ignored: only
fixed Alpaca **market-data** HTTPS/WebSocket hosts are used. The trading/account
host is never used. Missing credentials and authentication failures are reported
without raw upstream error bodies or exception details.

## Start locally

Install the canonical backend's runtime dependencies into the chosen Python
environment if needed. Build Week's existing `.venv` can host the process; use
the canonical backend requirements, not a second implementation here.

Terminal 1 (canonical service, loopback, one worker):

```sh
make navigator-live \
  BATTLESTAR_PATH=/Users/nikolai/BlackPod-Versions/blackpod_battlestar
```

Terminal 2 (read-only Cabin):

```sh
make cabin-live \
  CABIN_ARTIFACTS_ROOT=artifacts/no-trade-live-20260915 \
  CABIN_MISSION_ID=mission-live-aapl-20260915-002 \
  NAVIGATOR_LIVE_URL=http://127.0.0.1:8001
```

Open `http://127.0.0.1:5174/` and expand Navigator. The same-origin relay is
disabled unless `NAVIGATOR_LIVE_URL` (or reader `--navigator-live-url`) is given.
The canonical endpoint is independently disabled unless
`BPN_ALPACA_LIVE_ENABLED=true`; the Make target sets that flag explicitly.

## Coverage and honest connection states

The default is `ALPACA_DATA_FEED=iex`: live trades from the IEX exchange only,
not consolidated US-market coverage. Set `ALPACA_DATA_FEED=sip` only when the
account has the required entitlement. There is no silent feed downgrade and no
automatic subscription purchase. The existing credentials were checked on
September 16 with read-only AAPL latest-trade requests: IEX returned 200; SIP
returned 403. This confirms IEX access at that time, not perpetual validity.

Prices are event-driven, not guaranteed once every second. An open socket does
not make an old trade current. Trade age over 60 seconds is shown as **STALE**;
outages retain the last same-symbol value under **UNAVAILABLE**, never LIVE.
An inactive market or infrequently traded symbol can legitimately have no new
trade. Market-open state is not guessed. Heartbeats/retrieval timestamps do not
refresh the trade timestamp. Clock drift beyond five seconds is rejected.

The stream retries with bounded backoff. The UI has a 20-second silence watchdog;
the relay has a 15-second read timeout. Canonical five-second status heartbeats
allow closed clients to release their subscriptions. Only the original capture
symbol or an observed symbol from a verified mission publication is relayed;
browser-local watchlist additions do not grant arbitrary symbol access.

Canonical SSE explicitly observes disconnects through the HTTP middleware and
finishes cancellation-safe socket cleanup. The local startup target bounds
graceful shutdown to five seconds so an open viewer cannot indefinitely hold
up a service restart. The Cabin's separate mission loader allows ten seconds
for the feed pointer and sixty seconds for a new verified bundle, fetching at
most four captured datasets concurrently; all evidence hashes still validate
before the publication is displayed.

## Transport boundary

- Canonical: `GET /api/live-price/{symbol}` — loopback-restricted SSE.
- Cabin: `GET /live/navigator/price/{publication_id}/{symbol}` — no-store,
  same-origin SSE. Only a configured loopback origin and fixed canonical route
  are reachable; no redirect, credentials, arbitrary URL, or order proxy.
- Every event is validated as `navigator.live_price.v1` with matching symbol,
  provider/feed identity, finite positive prices, UTC timestamps, coherent null
  state, clock/freshness limits, and bounded message size. No mission files or
  quote logs are written. The original canonical OHLC contracts stay unchanged.

Official references: [Alpaca WebSocket authentication/subscriptions](https://docs.alpaca.markets/us/docs/streaming-market-data),
[trade messages and timestamps](https://docs.alpaca.markets/us/docs/real-time-stock-pricing-data),
and [IEX versus SIP coverage](https://docs.alpaca.markets/us/docs/market-data-faq).
