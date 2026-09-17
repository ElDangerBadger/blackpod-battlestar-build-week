# Resumable Sentry history capture

This is a Build Week command-line acquisition tool, not a Cabin control, scanner,
or observation producer. It wraps Battlestar's existing H25 implementation.
Battlestar and ModelDock are not modified. It never selects a final universe,
changes mission artifacts, or starts trading.

## Recover the saved September 16 request

Run from the Build Week repository using its installed environment. These paths
identify the **corrected** bootstrap, not the earlier classifier-blocked package.
The captured request remains July 18–September 16 inclusive, even when recovery
runs on a later day. It is not relabeled as today's market data.

```bash
export SENTRY_BOOTSTRAP="$PWD/artifacts/sentry-live-universe-20260916-classifier-fix/universes/bootstrap/2026-09-16/universe-source-snapshot-592ebad64d590cf5092b"
export BATTLESTAR_PATH=/Users/nikolai/BlackPod-Versions/blackpod_battlestar

PYTHONDONTWRITEBYTECODE=1 .venv/bin/python3.11 \
  -m blackpod_build_week.sentry_history_recovery \
  --battlestar-path "$BATTLESTAR_PATH" \
  --bootstrap-package "$SENTRY_BOOTSTRAP" \
  --adopt-existing --offline
```

The first command revalidates the canonical bootstrap, verifies existing CSVs,
and pins good nonempty captures into the recovery cache. It makes no provider
requests and publishes no history manifest. Empty or malformed partial files
remain pending; their original bytes remain untouched.

Then acquire a bounded batch:

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python3.11 \
  -m blackpod_build_week.sentry_history_recovery \
  --battlestar-path "$BATTLESTAR_PATH" \
  --bootstrap-package "$SENTRY_BOOTSTRAP" \
  --max-requests 25 --pace-seconds 2 --publish-h25
```

Repeat the same command after a normal budget pause. Already checkpointed
captures are revalidated and reused, not fetched again. `--publish-h25` allows
the canonical history manifest to be assembled **only after every requested
symbol has a verified result**. It does not publish a selected universe.
The default 25-request budget counts history calls, including retries; yFinance
may make multiple internal HTTP requests per history call. A larger
explicit budget is possible; increasing it does not bypass pacing or cooldowns.

On `RATE_LIMITED`, the batch stops on the first detected throttle and stores a
15-minute cooldown. An invocation before `retry_not_before` makes no provider
requests. Let the provider recover; repeatedly launching the command does not
override the recorded cooldown. There is no proxy/account rotation or automatic
provider substitution. Requests are serial, at least two seconds apart by
default, with 15-second timeouts and at most two attempts per symbol. Other
transient failures use bounded exponential retry delays and remain pending if
exhausted. Interrupting a run preserves previously committed captures.
A separate outage guard pauses before a third consecutive unavailable-provider
result. Its state survives budget pauses and cooldowns; cached old histories do
not count as evidence that the provider has recovered.

## Integrity and provenance

- Canonical source-package validation must pass before acquisition. Request
  identity pins the bootstrap manifest, snapshot, dates, exact symbol order,
  and relevant canonical code hashes. Identity changes fail closed.
- Recovery writes are confined to the selected package under Build Week's
  `artifacts/`. Provider caches are package-local too. Symlinked paths, special
  files, hard links, escaping paths and colliding canonical filenames are
  rejected. An exclusive package lock prevents concurrent recovery writers.
- CSV checks require exact canonical columns, increasing unique dates within
  the request, finite positive prices, and nonnegative integral volume. Empty
  legacy CSVs are never adopted as successful or terminal results.
- Each committed capture pins byte hash, size, row count, source kind, and known
  timestamps. Adopted files are labeled `adopted_partial_h25`: their original
  retrieval time is unknown. First verification time is not a provider timestamp,
  and a newly pinned hash is not a retrospective provider attestation.
- Fresh requests run through canonical H25 in isolated single-symbol staging.
  Provider errors are also captured outside H25's broad exception handler.
  Rate limits never become an empty successful checkpoint. Generic errors,
  silent empty frames and malformed data remain pending after bounded retries.
- Two consistent explicit `YFPricesMissingError` or `YFTzMissingError` responses
  can record a provider-unavailable result. That result means this provider
  could not supply the requested window, **not** that the company is invalid or
  ineligible. These results stay distinct from successful histories.
- Cache corruption or changed request metadata is an error, not permission to
  overwrite a verified entry. Do not edit checkpoint files to force a resume.
  Uncommitted/orphan cache files do not establish completed work.

## Publication and exit status

Recovery metadata lives in `<bootstrap-package>/recovery/`. Its checkpoint is
not an H25 manifest. Before final assembly the entire cache is revalidated and
all original `h25_daily/*.csv` files are backed up under `recovery/original_daily/`
with their hashes. Canonical H25 then assembles its normal files using the cache
only—no new network calls—and its public handoff validator must pass. Recovery
metadata preserves individual capture/adoption provenance separately from the
new manifest's assembly timestamp.

`COMPLETE` means a valid H25 handoff, not that all symbols returned market data.
The report separates `ready`, `unavailable`, and `pending`. Provider-unavailable
series retain explicit canonical blockers; they are not fabricated prices.
The final universe's price/history/liquidity gates are a separate subsequent
canonical step. Missing cap/float warnings and the distinction between a ticker
universe and actual Sentry observations still apply.

- Exit `0`: offline audit finished, complete cache ready to publish, or H25
  handoff complete. Read the status and counts; an offline audit is not completion.
- Exit `3`: budget pause, persisted cooldown, rate limit, provider outage guard,
  or exhausted retry.
  Checkpoints remain available for a later run.
- Exit `2`: validation/configuration/filesystem error. Investigate before retrying.
- Exit `130`: interrupted; previously committed captures are retained.

No final 100-symbol export or Cabin source switch happens automatically. See
[the recorded population attempt](SENTRY_UNIVERSE_RUN_20260916.md) for its status
and the separate real-observation producer gap.

## September 17 acceptance

- 64 recovery tests pass, including an actual canonical H25/bootstrap integration
  using synthetic prices without network access. The full Build Week backend
  suite passes all 659 tests with its localhost HTTP checks permitted and the
  real canonical checkout explicitly configured.
- Offline adoption preserved 1,296 reusable histories. Another 1,276 nonempty
  histories had a blank September 16 closing price; these remain pending for
  refetch alongside empty/missing files. No close was filled or inferred.
- A subsequent three-history-call live batch succeeded and stopped at its budget:
  1,299 ready, zero provider-unavailable, 3,860 pending. Previously checkpointed
  histories were not fetched again. This is a recovery smoke test, not completion
  of the full 5,159-symbol population.
- No real final H25 manifest/universe was published, and the Cabin still uses its
  labeled research archive. Original partial files, canonical code, mission
  evidence, and ModelDock are unchanged by this recovery increment.
