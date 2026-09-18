# Recorded Sentry scan results

The Cabin's **Sentry → Scan results** consumes an explicitly selected Battlestar
`sentry.operational_scan.v1` receipt. This is separate from both the Microcap
observation archive and the frozen Calibration V2 Research tab.

## Failure policy

Battlestar owns scanning, measurements, assessments, and ranking. Its new
`sentry.operational_scan` entry point processes each explicitly supplied history
independently. Missing, invalid, mismatched, stale, or unavailable symbol inputs
are excluded for this scan with an auditable reason. They are not deleted from
the fleet or historical archive.

The unchanged ranker selects the highest-ranked remaining **eligible** symbols
under the supplied total and profile capacities. It does not lower thresholds,
use stale substitutes, or pad the list. If too few names qualify, slots remain
unused. A valid non-anomalous symbol is different from a failed input; the UI
shows these outcomes separately. Invalid shared references/configuration or
unexpected scientific/contract failures stop the whole scan.

## Produce in Battlestar, display in Build Week

Run the canonical producer explicitly, with a reviewed input manifest:

```bash
cd /absolute/path/to/blackpod_battlestar
python3.11 -B -m sentry.operational_scan --manifest /absolute/path/to/manifest.json --output /absolute/path/to/scan.json
```

See Battlestar's `docs/SENTRY_OPERATIONAL_SCAN.md` for the strict manifest and
write-once output contract. Input histories, metadata, frozen training references,
provider declarations, and capture times are explicit; there is no discovery or
automatic market refresh. The operator chooses the snapshot, not the browser.

Then add one setting to your existing Build Week launch:

```bash
make cabin-live \
  CABIN_ARTIFACTS_ROOT=/absolute/path/to/existing/mission/artifacts \
  CABIN_MISSION_ID=your-existing-mission-id \
  SENTRY_SCAN_ARCHIVE=/absolute/path/to/scan.json
```

This also works with `make cabin-reader` after building. Retain existing mission,
Navigator, Microcap, and Research settings as needed; all three Sentry tabs are
independent. Restart the reader after changing arguments. No configured receipt
means **not configured**, never synthetic fallback.

Opening the tab or pressing Refresh reads the saved receipt only. It does not
run Battlestar, call a provider, retry failed captures, alter the watchlist,
or invoke downstream agents. There is no scan-tab polling. A failed refresh may
retain the last verified result with a visible stale/unavailable warning.

## Evidence and interpretation

- Both 20- and 60-session results are shown separately. No consensus or preferred
  baseline is invented. Percentiles are research-reference ranks, not returns,
  probabilities, or recommendations.
- Session date, declared evidence availability (`as_of`), individual capture
  times, and reader-check time have different meanings. A recently read saved
  receipt is not a current-market observation.
- General equity and ETF remain **RESEARCH_ONLY**. Existing references apply
  only to their original symbol/metadata membership. This path cannot silently
  enroll arbitrary symbols or claim whole-market production coverage.
- The producer checks captured history bytes and frozen-reference applicability,
  but successful history provider/capture identity is caller-declared. It does
  not independently certify exchange-session completeness or authenticated
  provider capture. These limitations remain explicit.
- The minimum 66 observations supports the existing 60-session method. The
  128-symbol request bound is an implementation resource limit, not a target
  attention size. Capacity is configuration, never an architectural fixed 100.

## Reader boundary

`GET /live/sentry/scan.json` returns `blackpod.sentry_scan_feed.v1`, with the
existing loopback/origin/method/no-store protections. It reads one bounded regular
file (16 MiB maximum), rejects unsafe paths and contradictory transport/safety
fields, verifies content IDs and evidence associations, and sends a compact
projection (256 KiB maximum). Absolute input paths and full sensor arrays are
not exposed to the browser.

The reader does not import the canonical engine, refit references, recompute
measurements, or rerank. A matching self-hash proves internal content integrity,
not independent authenticity; the operator-selected file is the trust boundary.
Underlying declared source files are not reverified by the Cabin.
Displayed history errors and warnings are limited to the first eight each,
with an explicit omitted-count marker. Every failed symbol remains listed;
the canonical report ID and source hash retain the full evidence identity.

## Bounded saved-evidence check

Local ignored artifacts live in `artifacts/sentry-operational-scan-20260918/`.
The five-symbol functionality check uses already-saved September 17 captures,
declared available at `2026-09-18T04:30:00Z`. AAPL, AGG, AMD, and COST are valid
inputs; IWM retains its real historical-volume conflict as an input exclusion.
No provider requests, calibration experiments, or prospective observations are
made by this check. Its receipt is not canonical production attention state.

The unchanged ranker selects **zero names at 20 sessions** (six unused slots)
and **AGG only at 60 sessions** (five unused slots). The other valid inputs have
no eligible tail metric; their exclusion is not an input failure. Repeating
the exact manifest produces the same write-once receipt:
`sentry-operational-scan-303094648d2190beb75d0c3c6d2f1348ef3734215b69932de2527dd44aba9184`.

The original Calibration V2 failed warmup and protocol remain unchanged. Reusing
saved captures in a separately labeled software smoke test does not repair or
replace that study. Microcap behavior, Oracle/Council integration status,
Governor/Navigator authority, and ModelDock boundaries remain unchanged.

## Verification

- Battlestar: **434 tests plus 322 subtests passed**, including 35 new scanner
  cases, attention, profiles, sensor contracts, Microcap, and frozen prospective
  collector/recomputation regressions.
- Build Week readers/API: **79 tests plus 133 subtests passed**, no skips,
  including the 128-malformed-symbol bounded-projection case and existing
  Microcap, Research, and Cabin reader regressions.
- Complete UI suite: **958 tests across 55 files passed** with Node 22.21.0
  explicitly first on PATH. The initial ambient-runtime run encountered existing
  browser-storage emulation failures; no product workaround was introduced.
- Production TypeScript/Vite build passed. Existing large Navigator chunk and
  multiple-Three.js test warnings remain.
- Playwright desktop/narrow-window checks passed for the real saved receipt,
  failure evidence, unchanged tab defaults, keyboard navigation, Escape focus
  return, failed-refresh stale labeling, and online recovery. Network errors
  during deliberately simulated disconnection/preview restart were expected.
- Frozen V2 declaration, summary, protocol and failed-warmup receipt still match
  their reviewed byte hashes. Canonical changes are three additive files only;
  no existing canonical engine, authority, or frozen-study file was modified.
