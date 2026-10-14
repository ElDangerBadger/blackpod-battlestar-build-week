# Reversal historical baseline

The fixed QQQ/SPY reversal rule now has a reproducible historical price-proxy
baseline. Across **6,165 paired observations**, the mean candidate response is
**0.0726206353%**, versus **0.0735181424%** for the equal-weight matched control.
Mean excess is **−0.0008975071%** per candidate window, before costs.
This pooled historical comparison does not show an advantage over the control.

The [prospective experiment](PROSPECTIVE_SHADOW_EXPERIMENT.md) remains unchanged:
30 sessions, its original universe and criteria, append-only predictions and
outcomes, and auto-trading OFF. Historical reconstructions never enter its
60-opportunity record. This work adds an offline calculator and a separate
read-only report, without changing mission schemas, decision policies,
ModelDock, brokers, desk budgets, execution or the existing UI.

## Watching the experiment

Open [the experiment](http://127.0.0.1:5181/?view=research) and use **Refresh
saved records** when returning to a hidden/paused tab. Refresh reads the saved
journal; it does not collect prices. Daily collection is scheduled for 18:30
Los Angeles time and requires the local machine and Codex scheduler to be
available.

Watch the page in this order:

1. **Last evidence capture:** this should advance when collection runs.
   **Reader checked** only says when the page read the saved record. A fresh
   reader timestamp does not make old market evidence current.
2. **Predictions recorded:** two opportunities become recorded for each
   completed signal session, even if both abstain. A candidate is a research
   prediction; an abstention means the frozen condition was not met. Missed
   deadlines and missing inputs are visible operational/data problems and
   cannot be repaired into successful past predictions.
3. **Entry and exit dates:** the response spans the next opening-price proxy
   to the following session's opening-price proxy. For an October 14 candidate,
   these dates are October 15 and 16. The outcome waits for the exit day's
   full source session and availability buffer, then the next collection.
4. **Candidate and control response:** a candidate gaining 0.20% while its
   matched control gains 0.30% has **−0.10 percentage points** of excess. A
   positive price move alone does not satisfy the hypothesis's comparison.
5. **Mean gross excess and sample size:** compare all paired outcomes rather
   than selected winners. The frozen descriptive rule needs both a positive
   mean candidate response and a positive mean excess, with at least 12
   candidates and a complete, usable cohort. Twelve is a coverage minimum,
   not proof of statistical power.
6. **Final conclusion:** it stays pending while the fixed cohort runs. Do not
   change the rule after a few good or bad observations. Gross results still
   cannot establish net profitability, trading authority or a calibrated
   probability. The final outcome window ends November 27.

At baseline publication the real pilot still has **2 events, 18 retained
blobs, 0 recorded predictions, 60 pending predictions and 0 outcomes**. Its
head remains
`64f2893f2cab7ff96013b09947a53a7d7af18ed64e964e686f633bf3467cd234`.
The historical report does not populate those counters.

## Historical data and scope

The original Battlestar daily histories were read without modification:

| Symbol | Retained coverage | Retained rows | Price rows through cutoff |
| --- | --- | ---: | ---: |
| SPY | January 2, 1998 through July 15, 2026 | 7,176 | 7,086 |
| QQQ | March 10, 1999 through July 15, 2026 | 6,879 | 6,789 |

They are located under
`/Users/nikolai/BlackPod-Versions/blackpod_battlestar/data/history/yfinance/daily/`.
Their exact seven-column CSV bytes and original backfill manifest are retained
in the report bundle. The manifest's July 16 generation time is declared
metadata, not authenticated proof that today's files were captured then.

QQQ's [inception was March 10, 1999](https://www.invesco.com/qqq-etf/en/home.html).
The report preserves unavailable QQQ opportunities in 1998; it neither creates
prices nor substitutes SPY. The fixed joint 30-session blocks begin March 11,
1999, when both symbols have an observed prior close. SPY's earlier candidate
responses remain in the rows, with matched results unavailable where QQQ's
entry/exit prices do not exist.

All scored signal, entry and exit prices stop on **March 5, 2026**. The cutoff
is independently rederived from the retained old research plan and its
calendar, preserving the March 6–10 embargo and March 11–October 12 holdout
across providers. The old price dataset was not loaded to establish this scope.
This verifies retained plan structure and calendar receipts, not a new full
semantic replay of the old journal.

A single explicit GET captured the
[Alpaca market calendar](https://docs.alpaca.markets/us/v1.1/reference/getcalendar-1)
for January 1, 1998 through March 5, 2026. The response contains **7,086 market
sessions**. SPY covers all of them; QQQ has no missing returned-calendar date
after its first observation. This avoids guessing holidays, emergency closures
or the next session from CSV row adjacency. No new price histories, account
snapshots, forecasts or orders were requested.

Prices are used exactly as stored. The baseline does not reinterpret adjusted
close as an adjustment factor for opening prices, apply corporate-action
repairs, fill gaps or infer historical publication times. The Yahoo price
basis remains **UNKNOWN** and is not certified equivalent to the live pilot's
IEX daily aggregates. Calendar coverage does not resolve price adjustment or
corporate-action continuity. All results are retrospective gross diagnostics;
net return, realized trade P&L and economic support remain unavailable.

## Historical results

The calendar supplies **14,172 symbol-session opportunities**: 6,304 candidates,
7,569 nonnegative-return abstentions, 297 QQQ opportunities before source
availability and two initial lookback/missing-input records. Of the candidates,
139 have no complete paired comparison and remain explicitly retained.

| Paired sample measure | Historical result |
| --- | ---: |
| Paired candidate observations | 6,165 |
| Mean candidate gross response | +0.0726206353% |
| Mean matched-control gross response | +0.0735181424% |
| Mean gross excess over control | −0.0008975071% |
| Positive candidate response fraction | 54.4849959% |
| Net return and realized trading P&L | Unavailable |

These are means per candidate opening-price window, not annualized returns,
portfolio returns or account P&L. Cash assumes zero interest. Every measured
candidate and control use identical entry/exit dates and one unit of gross
exposure. When both symbols qualify on the same dates, their average equals
the equal-weight control; excess mainly comes from dates with one selected
symbol.

There are **227 fixed nonoverlapping blocks**, anchored once at March 11, 1999:
226 complete 30-session blocks and one eight-session final block. All blocks
remain listed. Among the complete blocks, **84** meet both gross-positive
criteria and **142** do not. These counts are historical descriptions, not the
probability of the live pilot succeeding.

| Complete 30-session block measure | 10th percentile | Median | 90th percentile |
| --- | ---: | ---: | ---: |
| Mean candidate gross response | −0.2560% | +0.1027% | +0.4714% |
| Mean gross excess over control | −0.0302% | +0.0013% | +0.0307% |
| Paired candidates | 21 | 27 | 33 |

Percentiles use empirical nearest ranks. They describe variation across past
eligible blocks; they are not confidence intervals or calibrated forecasts.
Symbols, adjacent observations and adjoining block boundaries are correlated.
Incomplete blocks, missing evidence and too-few-candidate blocks are retained
in the cohort inventory, outside the declared comparable distribution.

The report also shows symbol and calendar-year summaries. The 2026 year is
partial through the cutoff. QQQ's historical excess is positive and SPY's is
negative; this exploratory split does not authorize dropping SPY, selecting a
winner or modifying the frozen hypothesis. Risk exposures and costs have not
been qualified.

## Inspect and reproduce the report

Final bundle:
`output/reversal-historical-baseline-002/`.
Report identity:
`shadow-historical-baseline-dc25447c6e1a2938e6e7587de8bbf23e076c10586d50737a155d25c3a9d01eda`.
An earlier development export remains local and is superseded by this bundle;
it is not an additional trial or independent performance sample.

The bundle retains **27 immutable payload files**, including the exact CSVs,
calendar/receipt, original backfill metadata, old holdout metadata, original
hypothesis and frozen protocol, calculation source files, all opportunity rows,
all cohorts, CSV export and standalone HTML. An additional final manifest commits all file
hashes. Verification replays the arithmetic and validates named provenance
links. Hash consistency establishes local retained-byte identity, not provider
authentication.

```bash
# One bounded calendar GET. An exact completed retry makes no provider call.
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python3.11 \
  -m blackpod_build_week.shadow_historical_baseline_cli capture-calendar \
  --output-root output/reversal-historical-calendar-001 \
  --runtime-root output/auto-trading-runtime \
  --credentials-file /Users/nikolai/buried_treasure/api_keys.yaml \
  --credential-format GALACTICA_YAML

# Offline reconstruction. No fitting, inference, providers or broker calls.
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python3.11 \
  -m blackpod_build_week.shadow_historical_baseline_cli build \
  --experiment-root output/prospective-reversal-pilot-2026-10-14/journal \
  --history-root /Users/nikolai/BlackPod-Versions/blackpod_battlestar/data/history/yfinance/daily \
  --backfill-manifest /Users/nikolai/BlackPod-Versions/blackpod_battlestar/artifacts/history/historical_backfill_manifest.json \
  --calendar-root output/reversal-historical-calendar-001 \
  --protected-study-root output/trading-research-governed-evidence-real-001/study-h2 \
  --output-root output/reversal-historical-baseline-002 \
  --runtime-root output/auto-trading-runtime

# Read-only replay, source hashes, provenance and derived artifacts.
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python3.11 \
  -m blackpod_build_week.shadow_historical_baseline_cli verify \
  --output-root output/reversal-historical-baseline-002

# Optional local preview; no execution or collection controls.
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python3.11 -m http.server 5182 \
  --bind 127.0.0.1 --directory output/reversal-historical-baseline-002
```

Open [the separate historical report](http://127.0.0.1:5182/report.html).
The existing experiment UI remains on port 5181. Historical results do not
automatically become live predictions or change any journal entries. Report
sources stay under ignored `output/`; back up the complete bundle to preserve
offline replay.

## Validation

The implementation adds only the historical calculator, calendar-only capture,
explicit CLI, standalone presentation and tests. It does not edit any of the
prospective protocol's nine pinned calculation/capture files.

The final combined run passed **97 distinct cases** in 24.752 seconds: 39 new
historical tests and 58 preserved pilot/core/capture/CLI tests. A focused run
of the same 39 historical cases also passed; repeated cases are not counted
as additional coverage. Exact commands:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests .venv/bin/python3.11 \
  -m unittest test_shadow_historical_baseline test_shadow_historical_cli \
  test_shadow_experiment test_shadow_experiment_capture test_shadow_experiment_cli -q

PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests .venv/bin/python3.11 \
  -m unittest test_shadow_historical_baseline test_shadow_historical_cli -q
```

Fixtures cover exact sign and Decimal arithmetic, future-price independence,
missing-session preservation, paired benchmark dates/exposure, pre-source
availability, cutoff enforcement, unchanged pilot evidence, credential-safe
transport, metadata binding, immutable conflicts, interruption recovery and
report escaping. An independent 100-digit Decimal calculation reproduced the
real 6,165-observation pooled and symbol means within `1.8e-62`. Final bundle
verification passed, and the real HTML report was opened and visually checked.
The prospective journal still verifies at two events and its original head;
runtime status remains OFF. No live execution or inference occurred.

Next, collect the fixed prospective cohort. Review its gross comparison and
operational completeness after the final outcome window, without retuning from
this historical result or adding another architecture layer.
