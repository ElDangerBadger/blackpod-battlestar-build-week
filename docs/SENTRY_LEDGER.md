# Microcap Sentry observation ledger

The real-universe classifier fix and regression tests are complete. Fresh source
validation passes; after Yahoo throttled population, checkpointed recovery was
added and verified with a bounded live batch. Population is still incomplete
(1,299 verified histories, 3,860 pending); no final universe is published. See
[September 16 run findings](SENTRY_UNIVERSE_RUN_20260916.md). This has not replaced
the research observation archive displayed here; real observation production
remains a separate integration step.

The Cabin's **Sentry → Observations** opens an independent, read-only ledger of
canonical Microcap Sentry Phase 1A snapshots. The mission-warnings paper still
opens that mission's warnings; those warnings are not Sentry detections.

This increment reads a single explicitly configured JSONL archive. It does not
run a scanner, acquire market/news/filing data, call ModelDock, generate scores,
or schedule analysis. Canonical Battlestar owns all classifications, scores,
reasons, and observations. The browser explains recorded fields without
inventing new findings. Phase 1B corpus exploration is not included.

## Configure an existing source

After building the UI, supply all four optional Sentry settings:

```bash
make cabin-reader \
  CABIN_ARTIFACTS_ROOT=artifacts/no-trade-live-20260915 \
  CABIN_MISSION_ID=mission-live-aapl-20260915-002 \
  SENTRY_ARCHIVE=/absolute/path/to/events/YYYY-MM-DD.jsonl \
  SENTRY_SOURCE_KIND=research \
  SENTRY_SOURCE_LABEL="Canonical Sentry research archive" \
  SENTRY_CANONICAL_ROOT=/absolute/path/to/blackpod_battlestar
```

These arguments also work with `make cabin-live`. The separate
`NAVIGATOR_LIVE_URL=http://127.0.0.1:8001` may be retained when an authorized
Navigator market-data service is already running. Sentry never calls it.

`research` labels research/fixture observations and disables watchlist and
Navigator handoffs. Use `recorded` only for genuine supplied observation
records; it means **recorded**, not streaming or recently observed. Supplying
no Sentry settings leaves the feature unconfigured. Partial configuration is
an error. No archive is discovered automatically, and there is no fallback
sample dataset.

The initial local visual review uses canonical
`artifacts/microcap_sentry/events/2026-07-15.jsonl`: **synthetic historical
research**, not today's detections. It contains 36 rows, 22 distinct event IDs,
14 exact duplicate rows, and seven synthetic symbols. The UI preserves its
original July observation times even when read in September.

## Reading the ledger

- The source panel separates observation time from reader-check time and
  discloses the archive filename, byte count, and SHA-256 identity.
- The overview groups observations by symbol. Equal timestamps are not an
  invented sequence; history retains the individual events.
- Details expose the recorded classification, rule-based scores, contributing
  factors, risks, missing inputs, and exact supplied JSON. Scores are not
  probabilities, trade recommendations, or execution permission.
- Missing, empty, invalid, and unavailable archives remain distinct from a
  valid populated source. An empty archive is not an “all clear.” Failed refresh
  may retain last-verified data with an explicit availability warning.
- The expanded ledger checks the archive every 15 seconds while visible in
  Live mode. Closing it, hiding the page, or using replay stops following it.
  Refresh re-reads the archive; it does not launch a scan.
- A recorded-source symbol can be added to the separate browser-local watchlist
  only by explicit user action. Navigator handoff also requires an existing
  verified chart capture for that symbol. Research-source actions are disabled.

## Reader and authority boundary

`GET /live/sentry/current.json` returns `blackpod.sentry_feed.v1`. The endpoint
uses the local reader's same-origin/host/method protections and no-store
responses. It neither enters the mission publication nor alters mission
identity, outcome, evidence hashes, timestamps, or replay.

The reader uses bounded, no-follow regular-file reads (8 MiB archive, 1,000
rows, 256 KiB per row), rejects files changed during reading and malformed or
unsafe records, and invokes the configured canonical pure snapshot model for
validation. It does not import or run the Sentry engine or write into the
canonical checkout. Duplicate JSON keys and non-finite numbers are rejected.
Exact repeated records are counted and collapsed; conflicting records sharing
an event ID reject the archive. Raw accepted observation fields are preserved.

Transport metadata contains no absolute filesystem path, credentials, or raw
exception details. The browser independently validates the bounded response
(also limited to 8 MiB) and expects fully serialized canonical snapshots,
including the older contribution format without `configured_weight`. Sparse
hand-authored records are not filled in by the presentation layer.
Sentry availability does not block the Cabin's mission reader. No orders,
broker/account controls, approvals, fleet mutation, or producer controls are
introduced. Battlestar and ModelDock are unchanged by this integration.
