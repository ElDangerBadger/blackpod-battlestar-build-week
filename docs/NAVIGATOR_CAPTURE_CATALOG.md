# Captured Navigator datasets

The user approved captured Battlestar data for interval and moving-average
selection. The Cabin remains a read-only consumer, not a market-data service or
indicator calculator. Battlestar and ModelDock are unchanged.

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
Both WebGL and SVG fallback use the same selection. No ticker, approval, order,
execution, store, or standalone API control was introduced.

Replay and legacy publications without the catalog behave as before. This
catalog currently applies to explicitly correlated LIVE publications only.

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
The user explicitly chose to keep Battlestar unchanged for now on September 15;
these extensions remain deferred, not approved implementation work.
