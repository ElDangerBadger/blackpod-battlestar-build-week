# Current Navigator references

Battlestar now owns an opt-in completed-bar reference producer. Build Week is a
read-only consumer of its versioned artifacts. This is separate from both the
saved September 15 mission and the ephemeral Alpaca last-trade overlay.

## What updates

- **Current reference:** latest verified completed bars and their matching
  canonical moving average/ATR. The producer reuses Navigator's existing
  yfinance provider, cache, and indicator calculations; the browser calculates
  no indicators. Hourly, daily, weekly and MA20/50/100/200/250 remain supported.
- **Live market data:** existing Alpaca last-trade overlay, with its own trade
  timestamp, feed coverage, and staleness. It is not an additional historical
  bar, and its unadjusted trade need not equal the adjusted reference close.
- **Saved reference / Original mission capture:** original immutable evidence.
  Oracle, Council, Governor, mission ledgers, and approvals do not become current
  merely because Navigator receives a new reference.

Current daily data during a trading session normally ends at the previous
completed session. Current hourly data excludes the forming hourly bar; weekly
data excludes the forming week. No partial bar is silently called complete.
Each snapshot preserves capture time, provider fetch time, latest bar label,
calendar identity, `auto_adjust=True` semantics, and an exclusive `valid_until`
deadline. Freshness expires without a heartbeat or successful new download.

## Ownership and integrity

Canonical modules:

- `blackpod-navigator-3/backend/src/reference_freshness.py`: verifies the
  existing official-source calendar and pinned timezone, determines completed
  sessions/bars, and filters only known in-progress observations.
- `blackpod-navigator-3/backend/src/reference_capture.py`: deterministic
  selection, bounded/paced acquisition, canonical indicators, immutable
  content-addressed snapshots/attempt receipts, atomic `current.json`, and
  foreground `watch` scheduling.

Build Week's `navigator_reference_reader.py` verifies bounded no-symlink reads,
hash/size, schema, symbol/interval/MA identity, provenance and chronology. The
read-only route is:

`GET /live/navigator/reference/{publication_id}/{symbol}/{timeframe}/{ma}`

It accepts only symbols in an already verified mission publication. Local
watchlist edits do not authorize symbols. The route reads local artifacts only;
it cannot start a provider, alter a mission, or submit an order. A corrupt or
failed refresh returns unavailable/stale status, retaining only previously
verified data for that exact pair. New generations never overwrite old ones.

The browser polls the selected pair every minute and expires the canonical
deadline independently. It preserves camera/history controls and rejects
cross-symbol or backwards captures. Saved mode pauses current-reference reads.
Replay never uses the current-reference feed. The main desk follows the original
reference symbol's latest generation; recorded analytical ledgers remain separate.

## Local operation

Run from the Build Week root with its Python environment. The following local
paths describe this September 18 setup; neither raw market data nor calendar
receipts are committed. Calendar compilation uses already captured authoritative
documents, performs no network request, and writes a separate receipt rather
than modifying frozen Sentry evidence.

```sh
make navigator-reference-calendar \
  BATTLESTAR_PATH=/Users/nikolai/BlackPod-Versions/blackpod_battlestar \
  NAVIGATOR_REFERENCE_CALENDAR_CAPTURE_ROOT=artifacts/sentry-calibration-v2-20260917/calendar \
  NAVIGATOR_REFERENCE_CALENDAR=artifacts/navigator-reference-current/calendar.json
```

Start the foreground reference worker in its own terminal (use
`navigator-reference-refresh` instead for a single cycle):

```sh
make navigator-reference-watch \
  BATTLESTAR_PATH=/Users/nikolai/BlackPod-Versions/blackpod_battlestar \
  NAVIGATOR_REFERENCE_ROOT=artifacts/navigator-reference-current \
  NAVIGATOR_REFERENCE_CALENDAR=artifacts/navigator-reference-current/calendar.json \
  NAVIGATOR_REFERENCE_CALENDAR_CAPTURE_ROOT=artifacts/sentry-calibration-v2-20260917/calendar \
  NAVIGATOR_REFERENCE_SYMBOLS=AAPL,XLK,XLF,XLE,XLV,XLI,XLP,XLY,XLU,XLB,XLRE,XLC,SPY,QQQ,DIA,VXZ,IWF,IWD,IWM,MTUM,USMV,QUAL
```

Defaults request all three existing intervals and five MAs. The explicit
22-symbol roster is the mission's 21 observed fleet items plus its original
AAPL reference. This is not whole-market screening or a new mission universe.
The first fill makes at most 66 history requests, not 330 requests for each MA.
Subsequent cycles request only due/failed groups, paced at 1.1 seconds, with a
five-minute retry floor for failed groups. A root's symbol/interval/MA scope is
fixed: use a separate root for a smoke test or changed configuration.

The worker sleeps until the next completion or retry. **It must remain running**;
this command is not an installed login/reboot service. A stopped worker does not
keep expired references marked current. No OS scheduler or frozen Sentry
collector is changed. Ctrl+C stops the foreground worker.

Add `NAVIGATOR_REFERENCE_ROOT=artifacts/navigator-reference-current` to the
existing `make cabin-live` or `make cabin-reader` command, preserving its
mission, Alpaca, and Sentry options. Restart the reader after changing Python
code/options. Rebuild the UI and reload existing browser tabs after a build.
Starting the reader alone never starts market acquisition.

Local-only evidence status (no provider requests):

```sh
make --silent navigator-reference-status BATTLESTAR_PATH=/Users/nikolai/BlackPod-Versions/blackpod_battlestar NAVIGATOR_REFERENCE_ROOT=artifacts/navigator-reference-current
```

This reports readiness counts, per-pair reasons and the next due attempt. It
describes the evidence, not proof that a worker process is running. Runtime
artifacts live in `snapshots/`, `attempts/`, `current.json`, `provider-cache/`,
and `yfinance-cache/` beneath the chosen root, all ignored by Git.

## Boundaries and limitations

- No Oracle narration, sector-bubble visualization, Council integration,
  ModelDock call, Governor change, Navigator execution change, or trading.
- Uses the existing development yfinance history source, not an Alpaca/SIP
  rolling candle feed. The live Alpaca trade source remains separately labeled.
- The verified calendar covers 2026. Unknown Cboe early-close times, disagreement
  across the included US venues, or an unverifiable next completion fail closed.
  The policy uses a common US-equity regular-session schedule; it does not infer
  a symbol's listing venue. Unexpected closures need new authoritative evidence.
- Current regular-session references apply only to registered US equities/ETFs,
  not crypto, sub-hour bars, extended hours, or every instrument in the market.
- Historical provider observations before the verified calendar's coverage are
  retained and structurally checked, not certified as complete session history.
  Provider adjustment revisions remain visible in distinct immutable generations;
  no old mission data is silently revised.
- This increment does not change Oracle's missing-prior-observation limitation.
  A future sector narrative needs explicit comparable sector observations; it
  cannot infer market-wide rotation from a fresh Navigator price alone.

## Tests

```sh
BATTLESTAR_PATH=/Users/nikolai/BlackPod-Versions/blackpod_battlestar \
  PYTHONDONTWRITEBYTECODE=1 .venv/bin/python3.11 -B -m pytest -q -p no:cacheprovider \
  tests/test_navigator_reference_reader.py tests/test_navigator_live.py tests/test_cabin_reader.py
PATH=/Users/nikolai/.nvm/versions/node/v22.21.0/bin:$PATH npm --prefix ui test -- --run --maxWorkers=2
```

Canonical focused tests live alongside the Navigator backend in
`src/tests/test_reference_capture.py` and `src/tests/test_reference_freshness.py`.

## September 18 local verification

The initial real-provider run covered the 22-symbol roster above and produced
325 verified references out of 330 symbol/interval/MA combinations. VXZ's five
hourly combinations were unavailable because the provider had not supplied the
latest completed bar. No bar was filled or relabeled to hide that gap. These
counts describe the initial check, not a permanent readiness guarantee; use the
status command for current results.

Two historical adjusted-price rows (XLP daily and QUAL weekly) exposed an exact
one-ULP floating-point containment discrepancy. The canonical structural check
now permits only the immediately adjacent representable float at a low/high
boundary, retains raw prices unchanged, and still requires strictly valid OHLC
after Navigator's existing four-decimal serialization. Larger discrepancies
remain invalid; focused tests cover both real examples and rejection boundaries.

The additive 2026 calendar ID is
`sentry-session-calendar-24792c25a993ff8537cbd6c34afe531c3dfcebd17df7d89e6b7c960c690d859e`.
It was compiled from the existing official-source capture
`sentry-calendar-capture-889fd6e864f606da601a9885a5aefa3cf06640ff6cbff8839071d13b5ad2870f`,
without changing the frozen Sentry protocol or calendar.

The original mission and reference bytes were rechecked unchanged:

- `mission_snapshot.json`: `b7b0c86b200cbebc6d1eb22510ab261d27e803eabd46bca2cffbca428298e61f`
- `presentation/navigator_market.json`: `29723ee55accbd21661b0286d16f37e23c54f7d55d0bdf3dd87d3a38966bd794`

Validation passed: 252 canonical Navigator tests; 746 Build Week backend tests
with 776 subtests; then 54 focused backend tests with 112 subtests after the final
reader guard changes; and 1,072 UI tests on the final compact-panel version.
Production build passed. Browser
checks verified the real current/saved prices, live Alpaca overlay, symbol and
hourly selection, and wheel zoom without a source-toggle workaround.
