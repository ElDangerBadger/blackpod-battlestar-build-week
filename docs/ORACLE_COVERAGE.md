# Recorded Oracle coverage

Audited 2026-09-16. This describes the immutable evidence for
`mission-live-aapl-20260915-002`, not a new calculation or approval.

## Why 21 observed symbols become 14 measurements

The saved `oracles_vapors` fleet enables all 21 symbols. Its provider/normalized
snapshot includes all 21; the seven excluded symbols each have recorded `FRESH`
quality, complete required fields, and no quality warnings or blockers.
The snapshot was approved for reasoning with all 21 symbols. These are historical
quality results at capture time, not a claim of present-day freshness.

Oracle's measurement producer then applies a separate, fixed policy:

- Core: XLK, XLF, XLE, XLV, XLI, XLP, XLY, XLU, XLB, XLRE, XLC.
- Optional indices: SPY, QQQ, DIA.
- Outside that measurement universe: VXZ, IWF, IWD, IWM, MTUM, USMV, QUAL.

Canonical [`oracle_measurements.py:23`](/Users/nikolai/BlackPod-Versions/blackpod_battlestar/blackpod/advisors/oracle_measurements.py:23)
defines these lists. Its return extractor at
[`oracle_measurements.py:321`](/Users/nikolai/BlackPod-Versions/blackpod_battlestar/blackpod/advisors/oracle_measurements.py:321)
excludes other observed symbols **before examining their returns**. This is not
a missing-data, disabled-symbol, Navigator, or ModelDock failure. The canonical
[adapter regression test](/Users/nikolai/BlackPod-Versions/blackpod_battlestar/tests/test_oracle_snapshot_measurement_adapter.py:30)
explicitly expects this 14/7 split.

For eligible symbols, the producer prefers finite `return_pct`; otherwise it can
derive a return from finite price and nonzero previous close. One or two missing
core sectors warn; more than two block. Missing optional indices warn. In this
mission none were missing: diagnostics record `used=14 missing=0 excluded=7
fallbacks=0`. Exclusion and missing-prior warnings are intentionally non-degrading
in [measurement diagnostics](/Users/nikolai/BlackPod-Versions/blackpod_battlestar/blackpod/advisors/oracle_measurement_diagnostics.py:36),
so `READY` does not mean every observed symbol contributed, nor does it grant
trading authority.

Recorded evidence, under
`artifacts/no-trade-live-20260915/missions/mission-live-aapl-20260915-002/`:

- `oracle/inputs/oracles_vapors.example.yaml:103`: enabled volatility/style/size/factor symbols.
- `oracle/attempt-0001/fleet-oracles-vapors-example_quality.json:165`: all seven pass quality checks.
- `oracle/attempt-0001/oracle_advisor_snapshot_input.json:12`: all 21 approved input symbols.
- `oracle/attempt-0001/oracle_measurements_live.json:20`: policy identity and participation provenance.
- `oracle/attempt-0001/oracle_measurement_diagnostics_live.json:163`: exact exclusion records and counts.

## Including them requires an upstream analytical decision

Adding them to the fleet file again, the browser watchlist, or Navigator's market
registry cannot change this policy. The new fleet Navigator captures are separate
price references and do not rewrite Oracle measurements.

The smallest deliberate producer change is to define an explicit additional
optional measurement group in canonical Oracle, extend its eligible universe,
preserve the core-sector readiness requirement, and update optional-group
provenance/warnings, policy identity, and regression tests. No browser-side
measurement calculation is appropriate.

This must not be treated as merely appending seven equivalent returns. The
[measurement builder](/Users/nikolai/BlackPod-Versions/blackpod_battlestar/blackpod/advisors/oracle_measurements.py:427)
uses the entire eligible set for breadth, concentration, and dispersion. Its
[group-strength calculation](/Users/nikolai/BlackPod-Versions/blackpod_battlestar/blackpod/advisors/oracle_measurements.py:649)
ranks groups against that entire set, so adding symbols changes existing scores
even without changing group membership. The fleet explicitly classifies VXZ as
volatility/risk-off and the others as style, size, or factor references; blindly
counting every positive return as breadth would ignore those distinctions.
Decide whether these are separate contextual measures or contributors to revised
aggregate scores, and test the chosen interpretation before changing policy.

## Missing prior measurements is a separate limitation

The live snapshot producer unconditionally supplies `prior={}` at
[`oracle_measurements.py:182`](/Users/nikolai/BlackPod-Versions/blackpod_battlestar/blackpod/advisors/oracle_measurements.py:182).
With fewer than two common current/prior observations,
[`_rotation_velocity`](/Users/nikolai/BlackPod-Versions/blackpod_battlestar/blackpod/advisors/oracle_measurements.py:630)
returns `0.0` and records `MISSING_PRIOR_ORACLE_MEASUREMENTS`. That zero is not
evidence of measured zero rotation. Another unchanged run will retain the warning.

Resolving it requires explicit, provenance-bound prior per-symbol returns from a
compatible earlier observation, with timestamp/universe comparability checks.
Today's `previous_close` is used to compute today's return; it is not the prior
return set needed for rank comparison. Neither the current canonical
[`run_oracle_pipeline`](/Users/nikolai/BlackPod-Versions/blackpod_battlestar/blackpod/runtime/oracle_pipeline.py:75)
signature nor Build Week's [Oracle call](../src/blackpod_build_week/oracle_adapter.py:865)
currently accepts that prior input. This is distinct work from expanding coverage.

## Publication boundary

After any authorized canonical producer change, run a new immutable mission with
a new mission ID and newly captured inputs; do not patch the completed mission's
measurements, diagnostics, narrative, or hashes. Completed Oracle invocations are
[validated no-ops](../src/blackpod_build_week/oracle_workflow.py:155), not a refresh
mechanism. Any refreshed narrative must reference the new evidence. The current
mission and its separately captured Navigator references remain historical records.
No broker, execution, operator-approval, or SHADOW safety changes are required.
