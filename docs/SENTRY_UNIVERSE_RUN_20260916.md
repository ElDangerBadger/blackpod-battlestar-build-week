# Real Sentry universe run — original hold and corrected rerun

Current status: **classifier fixed and regression-tested; recovery added;
1,299 verified histories checkpointed, 3,860 still pending**. Yahoo throttled the
original rerun, but a bounded three-request recovery check succeeded September 17.
No final 100-symbol universe has been published or connected to the Cabin.

Original run status: **incomplete; not published as a validated universe**.
The authorized classifier correction and separate rerun are tracked below;
the original package and partial history are retained unchanged.

The September 16 authorized run used canonical Battlestar code without changing
it. All new artifacts and yFinance caches are inside Build Week:

`artifacts/sentry-live-universe-20260916/`

## Completed source capture

- Canonical Nasdaq provider, both official listing directories; no fixtures.
- Retrieved September 16, 2026, at approximately 18:03 PDT. The parser does not
  retain the provider's file-creation trailer, so this is a retrieval timestamp,
  not proof of a particular directory publication date.
- Screening `as_of`: September 16; intended final target: 100 symbols.
- Snapshot: `universe-source-snapshot-fb36cb27414c1272e0b1`.
- 13,241 source rows, 13,108 normalized securities, 5,358 provisional symbols,
  7,750 static rejections, and 133 malformed rows.
- All eight bootstrap manifest hashes independently matched. Canonical package
  validation passed. Source provenance has `offline: false` and no fixture flags.
- The 133 malformed rows use unsupported warrant/unit/right symbol syntax and
  were excluded, not silently normalized into different securities.

## Why the original publication was held

An independent review of the real provisional list found existing canonical
security-classification precedence bugs:

1. `ADSEW` — source name `ADS-TEC ENERGY PLC - Warrant` — was classified as
   `ADR_OR_ADS`. The bare `ADS` name rule runs before the warrant rule.
2. `IQMXW` — source name `IQM Quantum Computers Oyj - Warrants to purchase
   American Depositary Shares` — was also classified as `ADR_OR_ADS` before
   reaching the warrant rule.
3. 200 provisional names match the canonical SPAC-name heuristic yet pass as
   `ORDINARY_SHARE`. For example, `AACI` is named `Armada Acquisition Corp. III -
   Class A Ordinary Share`. The ordinary-share return precedes SPAC refinement,
   bypassing the configured SPAC-common exclusion. These are name-rule matches,
   not an independent verification that all 200 issuers are currently SPACs.

Evidence is preserved in the bootstrap package's `provisional_accepted.csv` and
`source_snapshot.json`. Canonical implementation:
`microcap_sentry/universe/classification.py`, `_classify_name`.

Package integrity passing does not establish correct instrument classification.
The 71 existing validation-universe regression tests passed; they do not cover
these real source-name cases. No output has been manually filtered to hide the
problem, no canonical classifier was patched, and no final universe was built.

## Partial history acquisition

Canonical H25 began downloading unadjusted daily bars for July 18 through
September 16, inclusive. A delegating provider wrapper passed returned frames
unchanged and added progress reporting plus a 15-second timeout. Its outputs,
manifest target, ledger target, and timezone/cookie/ISIN caches were all confined
to the Build Week run root.

The exact task-owned process was stopped after the classifier findings. Its
first interrupt was swallowed by a data-library callback; a subsequent process
termination stopped further requests. There are 1,314 partial per-symbol CSV
files, some potentially empty. No completed H25 manifest or final selection
exists. These files are retained for diagnosis, **not** accepted as a completed
or automatically resumable H25 run. Nothing was deleted.

## Additional eligibility limitation

All normalized rows currently lack market capitalization and float metadata.
The existing validation-universe policy allows those gaps with warnings. Even
after classification is fixed, price/history/liquidity validation alone will
not prove that every selected company is a microcap. The separate Phase 1A
eligibility rules also differ from the validation-universe rules.

## Original next-step recommendation

Request permission for a narrowly scoped canonical Battlestar classifier fix
with regression tests for derivative/ADR precedence and SPAC ordinary shares.
Then prepare a new correctly classified package and repeat canonical history
handoff/final validation. Do not edit this snapshot or reuse its completion
claims after a rule change. Any reuse of partial prices needs explicit
date/schema/hash validation under the regenerated handoff.

Keep final artifacts and future generated long-history handoff paths inside
Build Week. No 1998-present backfill, live scanner, mission change, trade,
broker/account action, ModelDock call, or automatic watchlist update is part
of this run. The Cabin still shows its honestly labeled July research archive;
a universe file is not a Phase 1A observation feed.

## Authorized classifier correction — September 16

The user authorized a narrowly scoped Battlestar classifier fix, regression
tests, and a fresh population/validation run. Canonical edits are limited to
`microcap_sentry/universe/classification.py` and
`tests/microcap_sentry/test_validation_universe_classification.py`.

- Name-based classification recognizes enclosing units, warrants, and rights
  before their underlying share descriptions, without reclassifying genuine
  ADRs that represent units or a right to receive shares.
- Contextual ADR/ADS matching no longer interprets an issuer acronym such as
  ADS-TEC as the instrument type. Genuine country-suffixed ADRs remain supported;
  the ambiguous `PSNYW` name ending `ADS (ADW)` becomes `UNKNOWN`, not assumed ADR.
- Ordinary shares receive the same existing SPAC-name refinement as common
  shares, including explicit ordinary-type fields. The SPAC heuristic itself,
  provider flag/type authority, thresholds, and data contracts are unchanged.
- Regression review preserves existing depositary-preferred, ETN, purchase-
  warrant, genuine ADR, provider-priority, and explicit-type distinctions.
- The initial regression cases reproduced 21 failures before the correction.
  The completed 246-test Microcap Sentry suite passes with 12 new table-driven
  test methods. A separate old/new comparison of all 13,241 saved source rows
  found only the intended 268 changes: 214 ordinary-to-SPAC, 50 derivative-to-
  composite-unit, two ADR-to-warrant, ADSE to ordinary, and PSNYW to unknown.
  These row counts include malformed symbols and are not final eligible counts.

Code provenance for the uncommitted correction:

- Battlestar base commit: `4a4a5311b9cba144554d394d2a3a8d8a9af16ef1`.
- Classifier SHA-256: `660c19e87dfe5ac6acb0d4ead5f00fcece8a5b6f6c97afb31390a27d078e8df1`.
- Classification-test SHA-256: `afd1ac314c00ce023c0d37b8501dced7b2c4f20f1b3463edbc7e5f451a502c22`.

The separate rerun root is
`artifacts/sentry-live-universe-20260916-classifier-fix/`.
It captures fresh Nasdaq source data and requests new unadjusted daily history
for July 18–September 16, inclusive. It does not reuse the incomplete original
H25 handoff. The corrected download was attempted, then stopped on confirmed
provider throttling as detailed below; a source capture alone is not a validated
universe.

### Fresh bootstrap verification

- Retrieved September 16 at approximately 18:44 PDT, screening date September 16.
- Snapshot: `universe-source-snapshot-592ebad64d590cf5092b`.
- Bootstrap: `validation-universe-bootstrap-928effafb6a786fdea38`.
- Real Nasdaq source (`offline: false`): 13,241 rows, 13,108 normalized securities,
  5,159 provisional symbols, 7,949 static exclusions, 133 malformed rows.
- Prepared marker, all 14 canonical validation checks, and all eight manifest
  hashes pass. Each accepted row is still explicitly market-data-unvalidated.
- Versus the original capture, the classifier removes 203 provisional symbols.
  Fresh provider financial-status changes also remove BIOT/HODO and add
  GPRO/KFII/NWGL/RCON/REBN/RITR. Therefore the net decrease of 199 is not solely
  a classifier effect. No symbols were manually added or removed.
- Known warrant/SPAC/ambiguous-ADW exclusions were independently checked, along
  with the retained genuine ADRs and unchanged preferred/ETN exclusions.
- All 21 Build Week Sentry-reader tests pass, including compatibility with the
  real canonical pure snapshot model; no canonical-contract test was skipped.

### Corrected download outcome — provider throttle

The canonical H25 run requested all 5,159 provisional symbols using a delegating
yFinance wrapper (unchanged returned frames, 15-second request timeout, progress
reporting). All output paths and provider caches were checked to remain inside
the new Build Week root. No prior partial CSVs were reused.

After 2,572 nonempty responses, subsequent requests abruptly failed. An isolated
AAPL history probe returned `YFRateLimitError`, and one bounded retry after a
short cooldown returned the same error. The bulk process was paused for diagnosis
and then terminated at approximately 19:00 PDT. No downloader is left running.
No proxy/account rotation, credential change, or alternate-provider substitution
was attempted.

Retained partial output:

- 4,066 per-symbol CSVs: 2,572 nonempty and 1,494 empty/failed; 1,093 provisional
  symbols have no retained CSV. Empty files are not proof of an ineligible company.
- Nonempty files have the canonical seven-column schema, unique dates, and bars
  within the requested inclusive window. 2,551 end on September 16 and 21 on
  September 15. These checks do not establish a complete H25 handoff.
- No completed H25 manifest, final dated package, or current-universe export
  exists. No final selection was made from the alphabetically partial coverage.
- After stopping, canonical `load_bootstrap_package` revalidated all 14 source
  package checks with no errors or warnings. `validate_bootstrap_h25_handoff`
  correctly rejected finalization with `bootstrap H25 manifest is missing`.
- The corrected bootstrap package remains preserved alongside the original run.
  Nothing was deleted, and no mission/research archive was rewritten.

Recovery requires provider access to recover and a controlled history retry with
backoff and checkpointed, schema/date/hash-verified reuse of captured data. Do
not treat these loose CSVs as an automatically resumable or completed canonical
handoff. Complete the exact provisional fleet and obtain a valid canonical H25
manifest before finalizing with the saved bootstrap package. Keep explicit
`--output-root` and `--h25-root` overrides inside Build Week; generated example
commands without those overrides can otherwise target canonical defaults. The
generated long-history handoff is not authorization to run a 1998-present scan.

### Boundary after universe validation

This run populates a screening universe, not a current observation archive.
The existing Cabin research source is not repointed or relabeled.

Canonical Sentry's pure `MicrocapSentryEngine.analyze` can analyze supplied
inputs, and `EventRecorder.record` can persist the resulting bare snapshots.
However, its CLI has no wired real-time observation producer. Its existing
Alpaca integration supplies asset-master records, not Sentry market observations.
The H25 adapter supplies daily bars but no intraday bars, trading calendar, or
point-in-time profiles. The historical observation scheduler returns an empty
schedule when those required observation inputs are unavailable.

The next separately authorized increment would be a bounded read-only producer
that captures real inputs, invokes the existing engine, and records genuine
snapshots before configuring the Cabin with `SENTRY_SOURCE_KIND=recorded`.
Phase 1A requires market cap and float even though validation-universe policy
permits them to be missing. Intraday factors additionally need timestamped
bars, VWAP and expected-volume baselines; quote/news/filing/halt factors need
their respective feeds. Missing feeds must remain unknown, not a false claim
of no events. A Phase 1B corpus `observations.jsonl` contains wrapper records
and cannot be passed directly to the Cabin's bare-snapshot reader.

No producer, provider wiring, eligibility-policy change, continuous scanner,
ModelDock call, trading path, or Cabin source change is part of this correction.

## September 17 — checkpointed recovery

The user authorized a throttled, resumable recovery runner. It is implemented
only in Build Week and uses canonical public H25 staging and finalization, with
per-symbol byte/hash/request-bound checkpoints. See
[recovery commands and safeguards](SENTRY_HISTORY_RECOVERY.md).

The offline recovery audit found a distinction not captured by the earlier
schema/date-only check: 1,276 of the 2,572 nonempty histories have a blank final
September 16 `close` (and `adj_close`). They are preserved but **not adopted** as
usable captures. There are 1,296 strictly valid reusable histories. Empty,
incomplete and absent histories remain pending; none was repaired by inference.

A three-request real-provider verification recovered three more histories,
then stopped at `BUDGET_PAUSED`: **1,299 ready, zero provider-unavailable,
3,860 pending**. It resumed the saved September 16 date window, not a new
September 17 screening universe. No final H25 manifest or selected-universe
export was created. All original files remain intact.

Acceptance: 64 focused recovery tests and all 659 Build Week backend tests pass,
including network-free integration with the real canonical history writer and
handoff validator. Hashes of the canonical classifier/tests, July research
archive, mission snapshot, Cabin context, and Navigator capture remain unchanged
from before this increment. ModelDock is clean. No Git commit, merge, or push
was requested or performed.
