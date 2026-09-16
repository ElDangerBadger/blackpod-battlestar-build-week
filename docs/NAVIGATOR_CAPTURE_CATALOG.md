# Captured Navigator datasets

The user approved captured Battlestar data for interval and moving-average
selection. The Cabin remains a read-only consumer, not a market-data service or
indicator calculator. ModelDock is unchanged. The September 16 scope exception
extends only Battlestar's existing Navigator symbol registry for the recorded
fleet, with accompanying tests/documentation; its renderer and APIs are reused.

## Evidence boundary

The original `presentation/navigator_market.json` and `cabin_context.json` remain
byte-for-byte unchanged. They drive the overview and initial expanded view.
The optional `presentation/navigator_catalog.json` describes additional captures
at allowlisted `presentation/navigator_variants/{timeframe}-ma{period}.json` paths.
The catalog excludes the original pair and prohibits duplicate pairs.

Supported intervals are `1h`, `1d`, and `1wk`; MA periods are 20, 50, 100, 200,
and 250 **bars**, not universally days. Each entry contains its exact artifact
hash/size, capture time, transport, opaque source identity, and canonical
Navigator Git revision. Captures may cover different histories and times.
Missing MA warm-up values remain null. Provider cache metadata and source
disclaimers are preserved; a capture is never represented as a streaming quote.

The existing live presentation manifest optionally references the catalog by
hash. The reader captures and rechecks every referenced byte before publishing
one digest-addressed bundle. The browser verifies the catalog and each variant,
including symbol, mission correlation, interval/MA, capture metadata, and LIVE
provider restrictions. An invalid referenced variant rejects the publication;
the normal last-verified/offline behavior applies. The browser never discovers
unreferenced files or combines captures from unrelated missions.

## Explicit acquisition

With the canonical Navigator service already running on a loopback address:

```sh
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python3.11 scripts/capture_navigator_catalog.py \
  --artifacts-root artifacts/no-trade-live-20260915 \
  --mission-id mission-live-aapl-20260915-002 \
  --navigator-base-url http://127.0.0.1:8001 \
  --navigator-repository /Users/nikolai/BlackPod-Versions/blackpod_battlestar
```

The default requests all non-default pairs (14 for this mission). Optional
repeatable `--pair 1h:20` arguments restrict an explicit initial capture. All
responses are validated before publishing the catalog commit marker. A failed
acquisition does not publish a partial catalog. Existing conflicting captures
are never overwritten; repeated acquisition is not an update mechanism.

Starting the provider is a separate explicit operation. Confine canonical
provider caches, yfinance caches, and runtime writes to Build Week or a temporary
directory; disable Python bytecode writes in the canonical checkout. Use the
real provider, not synthetic data. No model inference or mission workflow is
needed for these supplemental market captures. Stop a temporary capture service
when finished. The Cabin itself does not need that service to remain running.

## Selection and compatibility

The expanded Navigator offers captured bar interval and MA selectors only when
variants exist. Unsupported choices remain unavailable. Switching intervals
retains the selected MA when captured there; otherwise it selects an available
MA and visibly updates the selector. “Original mission capture” restores the
original data and timestamp. The selected artifact's provenance is inspectable.
Both WebGL and SVG fallback use the same selection. No arbitrary ticker entry,
approval, order, execution, store, or standalone API control was introduced.

Replay and legacy publications without the catalog behave as before. This
catalog currently applies to explicitly correlated LIVE publications only.

## Recorded fleet symbol selection — September 16

The separate optional `presentation/navigator_fleet_catalog.json` uses
`blackpod.navigator_fleet_catalog.v1`. Its entries reference exact bytes at
`presentation/navigator_fleet/{SYMBOL}-{timeframe}-ma{period}.json`. The existing
single-symbol catalog and original chart remain unchanged. The reader includes
both catalogs in one verified publication, and the browser validates every
referenced dataset before making it selectable.

Fleet membership is bound to the exact indexed `oracle_normalized_snapshot`
artifact (including hash and byte size), not the browser-local watchlist or a
directory scan. Entries cannot replace the original chart symbol. The catalog
records the canonical Git revision, a SHA-256 fingerprint of Navigator backend
Python runtime sources, and whether that checkout was dirty. A dirty fingerprint
is disclosed rather than represented as a committed revision. Keep source and
mission evidence fixed for the entire acquisition.

With the real canonical Navigator service already running on loopback:

```sh
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python3.11 scripts/capture_navigator_fleet.py \
  --artifacts-root artifacts/no-trade-live-20260915 \
  --mission-id mission-live-aapl-20260915-002 \
  --navigator-base-url http://127.0.0.1:8001 \
  --navigator-repository /Users/nikolai/BlackPod-Versions/blackpod_battlestar/blackpod-navigator-3 \
  --all-observed --all-pairs \
  --source-identity navigator-v3-fleet-yfinance
```

`--all-observed` explicitly requests the recorded fleet, excluding an existing
original chart symbol. Without `--all-pairs`, only daily MA250 is requested;
repeatable `--pair 1h:20` arguments select particular pairs. Requests are paced
at least 1.1 seconds apart through the existing canonical API. Validation is
all-or-nothing, with bounded bytes and catalog-last publication. An existing
catalog is never replaced; this command is not a refresh or overwrite workflow.

The expanded symbol picker and Fleet/Admiral **Review chart** buttons use these
saved datasets. Switching symbols preserves the interval/MA when available;
otherwise an available pair is visibly selected. Each series exposes its own
capture time and provenance. Selection performs no provider or ModelDock call.
The overview and collapsed desk Reference Tape keep the original AAPL reference.
The expanded Reference Tape can independently select any recorded fleet item
and its captured interval/MA, with selected-source prices, times, and artifact
links. Fleet/Admiral/recorded Watchlist rows provide **View details** even when
no chart capture exists; missing chart values remain explicit. Its **Open full
Navigator** action preserves the exact selected symbol and capture pair. Oracle
coverage, Council/Governor decisions, and mission correlation do not change.
This is independent chart review, not a new single-symbol mission constraint.

## Finer intervals and ongoing progression

The current canonical Navigator registry/API supports only `1h`, `1d`, and
`1wk`; `1m`, `5m`, and `1s` are not available from this captured catalog. The
underlying yfinance download API documents 1m and 5m, but not 1s OHLC bars
([provider documentation](https://ranaroussi.github.io/yfinance/reference/api/yfinance.download.html)).
Exposing those finer intervals requires a separately authorized canonical
Battlestar extension, then matching capture/validation support here. Do not
bypass Battlestar, relabel existing bars, or manufacture sub-hour data.

Choosing finer bars is distinct from watching incoming prices. The read-only
reader polls published mission evidence; it does not acquire new market bars.
Continuous ship/MA progression needs an explicit refresh producer and append-only,
verified capture publications while retaining old evidence. The current history
slider only changes the visible start; it is not live playback. Neither finer
intervals nor ongoing acquisition was added by the transparent-price UI update.
The user initially deferred these changes on September 15. On September 16 the
user separately authorized a canonical, read-only Alpaca **last-trade stream**
using the existing `buried_treasure` credentials. That ephemeral live overlay
does not overwrite this catalog, extend its bar intervals, or refresh its MA.
See [Alpaca live market data](ALPACA_LIVE_MARKET.md) for the distinction and startup.
