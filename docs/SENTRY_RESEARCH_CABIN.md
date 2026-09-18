# Sentry Research in the Captain's Cabin

Sentry → **Sentry Research** is a read-only view of the accepted Calibration V2
development findings and its recorded prospective closeout. Battlestar owns
the measurements, policies, results, and protocol. Build Week only validates
and presents the saved evidence. The existing Microcap observations tab remains
separate and unchanged.

## Start with the frozen local evidence

From the Build Week repository, add both settings to your normal Cabin launch:

```bash
make cabin-live \
  CABIN_ARTIFACTS_ROOT=/absolute/path/to/your/existing/artifacts \
  CABIN_MISSION_ID=your-existing-live-mission-id \
  SENTRY_RESEARCH_ROOT="$PWD/artifacts/sentry-calibration-v2-20260917" \
  SENTRY_RESEARCH_CLOSEOUT_ROOT="$PWD/artifacts/sentry-calibration-v2-closeout-20260917"
```

These options also work with `make cabin-reader` after `make cabin-build`.
Restart the reader when changing its configuration. Keep any existing
`SENTRY_ARCHIVE`, `SENTRY_SOURCE_KIND`, `SENTRY_SOURCE_LABEL`, and
`SENTRY_CANONICAL_ROOT` options to retain your configured Microcap archive.
Neither source depends on the other. Normal mission and Navigator options
remain unchanged.

The research artifacts are local/ignored, not bundled with the UI or committed
to Git. A fresh clone without them correctly shows **not configured** or
**unavailable**; it does not substitute synthetic data. Do not run a study or
collector to populate this view. It reads already-recorded evidence only.

## What the view means

- **20 and 60 are trading-session baseline windows**, not chart intervals or
  predictions. Both perspectives are preserved. No preferred window or
  winning policy is selected.
- Training references cover **2019–2022**. Development covers **2023–2024**,
  502 supplied sessions, across the fixed 56-symbol population. This is
  previously seen development evidence, **not independent validation** and
  not today's market.
- The unchanged review budget is six total attention slots, four per profile,
  at most two new names per day on average, and at least two-thirds average
  20/60 Jaccard overlap. Jaccard means shared names divided by all distinct
  names in the two sets. The recorded all-session mean is displayed.
- No tested policy met both criteria. Limiting new names reduced churn by
  construction without resolving baseline disagreement. The presentation
  copies recorded results; it does not calculate new classifications.
- Historical contributors are the supplied most-frequently selected names
  for each window and policy. They are **not a current attention universe**,
  recommendations, or a complete list of all selected symbols. The full
  declared study cohort is listed separately.
- **GENERAL_EQUITY and ETF remain RESEARCH_ONLY.** The tab cannot promote a
  profile, tune a threshold, select a policy for operation, add names to the
  fleet/watchlist, open a Navigator handoff, or send anything downstream.

## Prospective closeout is a recorded snapshot

The fixed September 18–December 11, 2026 protocol planned 60 prospective
sessions. Its September 17 warmup was separate, not session one.

At closeout, 23 symbols had successful individual captures, IWM failed on a
historical overlap conflict, and the remaining 32 were blocked. The complete
56-symbol warmup was **not sealed**. Failure evidence was sealed. There were
**zero completed prospective sessions**. IWM's September 16 volume differed
between vintages (27,522,300 versus 27,599,400); the view does not decide which
vintage is correct. The Cboe November 27 early-close clock also remained
unverified.

The closeout timestamp describes that saved state. The reader-check timestamp
only says when the Cabin validated the files. **Refresh re-reads those files;
it does not query the scheduler, capture prices, retry warmup, or turn the
closeout into current collector health.** This panel is not a live collector
monitor. It does not change the prospective calendar or experiment.

## Contract and integrity

`GET /live/sentry/research.json` is separate from
`GET /live/sentry/current.json` (legacy Microcap). Both use the Cabin's existing
loopback, origin, method, and no-store protections.

This first adapter deliberately targets one reviewed, frozen V2 checkpoint.
It accepts an explicit pair of directories and reads only four fixed files:

| Source | Presentation |
| --- | --- |
| `development-declaration.json` | Periods, cohort, windows, unchanged criteria |
| `development-summary.json` | Saved three-policy comparisons and historical contributors |
| `prospective-protocol.json` | Frozen manifest identity and prospective period |
| `failed-warmup-integrity.json` | Recorded blocked warmup and closeout provenance |

Bounded regular-file reads reject symlinks, partial/changed files, malformed
JSON, and bytes that do not match the reviewed SHA-256 pins. Source filenames,
sizes, hashes, and evidence identities are available in the panel, without
absolute filesystem paths. Pins are compatibility/integrity checks, not a
claim of independent scientific validation.

The large result/cache artifacts are neither read on a UI request nor sent to
the browser. Their hashes in the saved summary are **declared upstream
identities**, not fresh re-verification of those large files. No new metric,
sensor, score, policy result, or consensus is computed here. Supporting a
different checkpoint requires an explicitly reviewed adapter update rather
than silently accepting changed evidence under this version.

No canonical source edits, provider requests, calibration experiments,
Oracle/Council integration, ModelDock work, Governor changes, or Navigator
execution-authority changes are part of this UI increment.

## Verification for this increment

- Focused backend: **65 tests plus 101 subtests passed**, including legacy
  Microcap/Cabin reader regression checks and the canonical snapshot contract.
- Complete UI suite: **883 tests passed** across 52 files.
- Production build passed; the existing large Navigator chunk warning remains.
- Real-browser checks covered the configured frozen source, preserved Microcap
  view, keyboard tab/close focus, contributor/cohort/provenance disclosures,
  desktop and narrower layouts, and explicit last-good evidence warnings and
  recovery during an offline refresh. No scientific experiments were run.

Reproduce the code checks (the synthetic tests do not need market artifacts):

```bash
PYTHONDONTWRITEBYTECODE=1 BATTLESTAR_PATH=/absolute/path/to/blackpod_battlestar \
  .venv/bin/python3.11 -B -m pytest -p no:cacheprovider -q \
  tests/test_sentry_research_reader.py tests/test_sentry_reader.py tests/test_cabin_reader.py
NODE_OPTIONS=--no-experimental-webstorage npm --prefix ui test
npm --prefix ui run build
```
