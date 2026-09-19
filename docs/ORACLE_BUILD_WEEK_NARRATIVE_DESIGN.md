# Oracle: market meaning and long-view narrative design

September 19, 2026 · **Approved design; first deterministic evidence stage implemented. Narration and Cabin integration remain unimplemented.** See §11 for the implementation checkpoint; §§1–10 retain the original design/audit record.

## 1. Product decision

Oracle is one analytical and narrative capability, not a literal restoration of two Galactica products. Galactica's Archivist, sector Oracle, structural field and Delphi are historical references for useful mechanisms and writing behavior. Their names, dependency graph, model routing, defects and unsupported conclusions are not the implementation specification.

Oracle should answer:

> What kind of market are we looking at, how is it changing, why does BlackPod think that, and what might those conditions imply about the environment ahead?

Its value is **relationships, temporal context and interpretation**, not translating each dashboard value into a sentence. A useful report explains what reinforces the market picture, what contradicts it, what changed, what remains uncertain, and which subsequent observations would strengthen or undermine the interpretation.

“Orthogonal” means an additional analytical perspective: longer horizons, cross-sector relationships, persistence and divergence. It does **not** mean statistically independent evidence merely because another module interprets the same prices.

### Design recommendation

Build one canonical Battlestar capability, consumed by the existing Build Week Oracle book, with two explicitly separated stages:

1. **Market interpretation:** measured market structure plus comparable historical evidence, independent of current-run Council/Senate conclusions.
2. **Later fleet synthesis:** an optional terminal interpretation of completed analysis, including its dependencies, disagreement and limitations. It must not overwrite or feed back into the initial assessment.

The first useful increment does not require a new market-data service, a recreation of Brigade, a cluster model, or a probabilistic forecasting engine. It does require a **canonical temporal evidence adapter and relationship-level interpretation contract**. A longer prompt over today's five brief sources is insufficient.

## 2. Review boundaries and evidence checkpoints

No production code, prompts, accepted reports, market data, model configuration, calibration, or execution authority is changed by this design. No provider/ModelDock calls, pipeline runs or application tests were performed. Read-only inspection included source, saved JSON/CSV, file boundaries, content hashes and artifact lineage. This document is the only new file for this task.

Source aliases:

| Alias | Root / checkpoint |
| --- | --- |
| `B` | `/Users/nikolai/BlackPod-Versions/blackpod_battlestar`; `update/2026-09-18-live-analysis`; HEAD `b2d79331521d57dbcdcdc1ccf8cb27f5bb9dca09` |
| `W` | `/Users/nikolai/Projects/blackpod_battlestar_build_week`; same branch name; HEAD `5f1f63831bbf06b9310c6ec972b10b5c65b79c6b` |
| `G` | `/Users/nikolai/BlackPod-Versions/blackpod_galactica`; historical filesystem snapshot, no committed HEAD |

The previous [parity audit](ORACLE_NARRATIVE_PARITY.md) remains the source inventory. This design supersedes literal-restoration framing, not its factual findings. Both maintained trees already have uncommitted work; it is preserved, not accepted as completion of this design.

“Exists” below is distinguished from “connected to Oracle,” “sufficient for a claim,” and “current.” Local artifact storage under W does not transfer analytical ownership from B. Timestamps describe the inspected evidence, not a permanent freshness guarantee or proof that a collector is running.

## 3. Evidence that actually exists now

### E1 — Native Oracle snapshots and measurements

**Owner:** B native Oracle. `blackpod/runtime/oracle_pipeline.py:75` `run_oracle_pipeline`; `blackpod/advisors/oracle_measurements.py:135` `build_oracle_measurements_from_snapshot_input`; W `src/blackpod_build_week/oracle_adapter.py:835` `_oracle_worker` captures its artifacts.

Saved LIVE mission observations inspected:

| W artifact root / mission | Oracle observation time |
| --- | --- |
| `artifacts/initial-live-20260915` / `mission-live-aapl-20260915-001` | `2026-09-15T22:36:39Z` |
| `artifacts/no-trade-live-20260915` / `mission-live-aapl-20260915-002` | `2026-09-15T23:05:20Z` |
| `artifacts/live-analysis-20260918-001` / `mission-live-aapl-20260918-001` | `2026-09-18T19:05:11Z` |

Under each mission, `oracle/attempt-0001/` contains the normalized snapshot, readiness, measurements, diagnostics, assessment and report. The normalized snapshot retains 21 symbols' prices, previous close, returns, OHLC and volume. Measurements use 14: eleven sector ETFs plus SPY/QQQ/DIA. VXZ, IWF, IWD, IWM, MTUM, USMV and QUAL are observed but excluded by the current measurement policy.

The two September 15 captures contain the same aggregate measurements; they are not two different daily market states. September 18 is an intraday observation, while those September 15 observations are after the regular close. They are not an aligned daily sequence. Thirteen additional B archived measurement files from June 25–26 also have the missing-prior warning; they do not establish continuous market memory.

Existing definitions must remain intact:

- `_breadth_score:607`: fraction of supplied returns positive, not constituent breadth or above-MA breadth.
- `_leadership_concentration:613`: top-two **absolute** move share, including declines, not necessarily winning leadership.
- `_sector_dispersion:621`: normalized cross-sectional range, not realized volatility.
- `_group_strength:649`: rank-group score, not capital flows, return or probability.
- `_rotation_velocity:630`: requires a compatible prior return map. The live adapter supplies `prior={}` at `:182`; zero plus `MISSING_PRIOR_ORACLE_MEASUREMENTS` means unavailable comparison, not no rotation.

**Depth:** sufficient for bounded present-state interpretation; sparse snapshots alone are insufficient for persistent structural change. See [Oracle coverage](ORACLE_COVERAGE.md).

### E2 — Completed-bar Navigator references: the smallest useful temporal source

**Producer/indicator owner:** B `blackpod-navigator-3/backend/src/reference_capture.py:291` `run_once`, `:226` `validate_bars`, `:254` `_market`; `reference_freshness.py:204` `expected_completed_bar`, `:231` `select_completed_bars`; `market_model.py:20` `simple_moving_average`, `:33` `wilder_atr`, `:74` `derive_summary`, `:109` `enrich_bars`.

**Storage/read-only consumer:** W `artifacts/navigator-reference-current/`; `src/blackpod_build_week/navigator_reference_reader.py:58` `validate_reference_snapshot`. Original mission chart captures under `presentation/navigator_fleet/` remain separate saved evidence.

Inspected index: `current.json`, generated `2026-09-19T02:26:26.851015Z`, SHA-256 `f26e4d0d63238284d00bca5d1be42181dad29d2f108bf6506c5c8c0f7ec432d1`.

It declares 330 READY entries: 22 symbols × three intervals × five MA periods (20/50/100/200/250). All 330 referenced snapshot hashes were checked. Within each symbol/interval, the five MA variants have identical underlying OHLCV; they are five views of one history, not independent evidence.

| Interval | Actual stored depth | Common population depth / limitation |
| --- | --- | --- |
| Daily | Each of 22 symbols has 753 observations, September 19, 2023–September 18, 2026 | All 753 date labels common; no duplicate labels. Useful starting panel for retrospective participation, relative strength and trend trajectories. |
| Hourly | 286–420 observations per symbol, June 25–September 18, 2026; final label `19:30Z` | Only 286 labels common. Gaps/coverage need explicit policy; do not assume complete intraday history. |
| Weekly | 431–522 observations; most start September 19, 2016; VXZ January 22, 2018; XLC June 18, 2018 | 431 common labels; latest label September 14, 2026 denotes the completed week, not a Monday-only observation. Weekly bars cannot reconstruct daily paths. |

Population: AAPL; eleven sector ETFs; SPY, QQQ, DIA; IWF, IWD, IWM, MTUM, USMV, QUAL; VXZ. AAPL is a single-company reference, benchmarks/factors have different roles, and VXZ is a risk-product proxy. They must not all become interchangeable breadth members.

Snapshots include adjusted OHLCV, per-bar MA and ATR, summary trend/distance fields, `auto_adjust=True`, provider/capture timestamps, calendar ID, completed-bar policy and `valid_until`. Their declared freshness deadlines extend beyond the captured sessions; a new read does not extend those deadlines.

Important qualifications:

- Current references are **supplemental market evidence, not existing Oracle analytical artifacts**. Explicit canonical admission/derivation is required; viewing the chart does not update Oracle or a completed mission.
- Common dates/hash validity do not certify every expected exchange session or validate all historic prices. The verified calendar covers 2026, not the full historical span.
- Prices are adjusted at the capture vintage. They support a reconstruction using that vintage, not proof of what was knowable at a past date. Different snapshot vintages can revise history.
- Publication rounds OHLC/indicators to four decimals. Define numerical tolerance and methodology before using them near analytical boundaries; use the owning producer's higher-precision stored source when required and provenance-compatible.
- The display registry labels 21 proxies as `index`, and sets USD in `_market`. Those are presentation conventions, not independent instrument classification or historical currency verification.
- Wilder ATR and the visual sea-state thresholds describe Navigator's chart context; “storm” is not automatically a market-wide risk regime.

**Depth:** enough to design and characterize a genuine multi-horizon **proxy-market** lens without new downloads, subject to a canonical comparability gate. Not a 26-year daily panel and not whole-market constituent breadth.

### E3 — Longer and broader histories: valuable, but heterogeneous

**Owners:** B `blackpod/runtime/historical_store.py:12` `HistoricalStore`; `yfinance_historical_backfill.py:83` `run_historical_backfill`; Sentry validation/update/reconciliation/identity modules listed below. Most newer study artifacts are local under W.

| Stored source | Observed coverage | What it does / does not support |
| --- | --- | --- |
| B `data/history/yfinance/daily/*.csv` + `artifacts/history/historical_backfill_manifest.json` | 33 files, 197,896 rows, all end July 15, 2026; oldest starts January 1998; manifest July 16 | Long retrospective context, not current observations. Collection uses `auto_adjust=False`, includes adjusted-close fields; full historical adjustment provenance is not authenticated. |
| W `artifacts/sentry-evidence-validation-20260917/cohort-histories/population.json` + 56 candidate CSVs | 249,688 rows; all end September 16; 24 equity and 32 fund-class records accepted for research | Broader cross-asset history, including sectors, growth/value, duration/credit, international and commodity vehicles. Common full-cohort history begins no earlier than XLC's June 19, 2018 inception coverage. |
| W `artifacts/sentry-live-universe-20260916-classifier-fix/.../h25_daily/` | 5,159 physical CSVs; recovery distinguishes 5,136 usable histories and 23 provider gaps | Broad symbol coverage, but most histories have at most 42 sessions. This is not thousands of long historical baselines. |
| W `artifacts/sentry-production-readiness-20260917/inventory-final/data_inventory.json` | Existing September 17 inventory: 16,086 physical histories; 5,161 unique valid daily symbols; many duplicates and 29 conflicting overlap pairs across 20 symbols | A prior inventory receipt, not a fresh census. Duplicate files are not independent sources. |
| Independent comparison in the evidence-validation study | Alpaca SIP for 56 symbols × five sessions (September 10/11/14/15/16): 280 pairs | Short corroboration/identity evidence, not independent decades of calibration. Complete OHLCV pairs are not identical across providers. |

The long Sentry derivatives retain `price_basis:UNKNOWN` after adjustment-revision handling. **Do not splice them into Navigator's `auto_adjust=True` series.** Historical cap/float, delisted membership and point-in-time constituent classifications remain unproven. Twenty-three problem identities were quarantined. Current metadata is not historical metadata. Existing evidence-validation records include 14 adjusted-close reconciliations and separate malformed-tail repairs; neither grants blanket comparability.

Reuse B `sentry/history_validation.py:166` `load_h25_history`, `history_update.py:512` `run_incremental_updates`, `history_reconciliation.py:193` `reconcile_adj_close_receipt`, `:214` `plan_tail_repair`, `:247` `run_tail_repairs`, `instrument_identity.py:220` `review_instrument_identities`, `metadata_provenance.py:85` `build_metadata_catalog`. Do not replace guarded readers with permissive loading or silently repair source history in the narrative layer.

**Depth:** suitable for additional bounded, labeled retrospective work after per-series basis/identity review. Not automatically eligible for current market claims or probability-bearing analogs. No whole-market refresh is needed for the first proposed experience.

### E4 — Sentry: deterministic measurements versus research interpretation

**Owner:** B `sentry/measurements.py:104` `measure_daily`, `engine.py:12` `analyze_daily`; `calibration.py:259` `fit_reference`, `:386` `assess`; `attention.py:343`; `operational_scan.py:296`.

Reusable deterministic measurements include return, acceleration, volume, relative volume, range/true range, compression, normal-range movement, baseline standardization, breakout/breakdown distance and trend context. Baselines exclude the observed session and retain missing-data reasons. Sentry's baseline true-range average is not Navigator's Wilder ATR; reuse the correct definition rather than treating both as interchangeable “ATR.”

Latest inspected mission scan: W `artifacts/live-analysis-20260918-001/sentry/scan.json`:

- Session September 17; evidence as-of September 18, `19:05:07.849521Z`.
- 21 requested, 18 observed, three failed: IWM, QQQ, SPY.
- Both 20- and 60-session windows selected zero names; eligibility/capacity is not forced to fill.
- GENERAL_EQUITY and ETF remain **RESEARCH_ONLY**. Percentiles are empirical reference ranks, not probabilities or validated forecasts.

The five-symbol `artifacts/sentry-operational-scan-20260918/scan.json` is a different smoke receipt, not the latest mission scan. The July Microcap archive includes synthetic examples; no selected example becomes live evidence by virtue of its name.

V2 development failed its predeclared stability criteria. Prospective September 17 warmup has 23 READY, one failed and 32 blocked outcomes; inspected September 18 outcomes are all blocked by the prior-session failure. This is **not** a successful continuous prospective record. This design neither repairs nor recalibrates that experiment.

**Depth/stage:** independent of the Oracle/Council dependency graph, but not automatically independent data. Existing research results are not authorized production conclusions. Raw measurements can inform a future explicitly admitted observation layer; optional research commentary must remain labeled and cannot raise market conviction by treating unvalidated anomaly labels as corroboration.

### E5 — Completed Council/Senate analysis: real, but Oracle-dependent

**Owners:** B `blackpod/advisors/trading_candidate_generator.py:74`, `:88`, `:155`; `senate_candidate_intake.py:67`; `senate_deliberation.py:69`, `:144`; `blackpod/governor/council_synthesis.py:15`, `:113`, `:218`; `council_executive_summary.py:94`. W `src/blackpod_build_week/council_adapter.py:1133` through `:1169` wires the current chain.

The current W Council stage generates candidates from **the same normalized Oracle snapshot**. Senate intake and deliberation explicitly consume OracleReport. The five-artifact packet contains Oracle report, mandate, candidates, Senate review and Senate deliberation—not original Brigade votes, Sentry, Delphi or a separate independently analyzed full fleet.

The September 18 mission has 21 candidate/Senate items, all Senate items MONITOR; zero FAVORABLE/UNFAVORABLE/BLOCKED. Council is BLOCKED by the explicit no-trade mandate, with empty alignment/conflict arrays and missing future/memory/accountability context. Its `advisor_count=5` is five loaded artifacts, not five independent analysts agreeing.

Two interpretation traps:

1. Council's `NO_OPPORTUNITY_SIGNAL` reads the legacy `senate_decisions` input family (`council_synthesis.py:113`); W supplies newer `senate_deliberations`. Do not narrate this as “the Senate evaluated every symbol and found no opportunities.” No fix is proposed inside this review task.
2. W's recorded dissent is filtered unfavorable/blocked native Senate items (`council_adapter.py:1274`), not disagreement among original multi-agent senators. Current rule confidence levels are not calibrated certainty.

Council history/evolution code exists (`council_synthesis_history.py:80`, `:115`, `:138`; `council_synthesis_evolution.py:89`; `council_evolution_narrative.py:81`), but W currently builds the executive summary from synthesis alone (`council_adapter.py:1263`). Saved summary explicitly says history/evolution unavailable.

**Depth/stage:** useful completed post-Oracle analysis for a later synthesis; not independent validation, a continuous history or original Brigade consensus.

### E6 — Other named products and confidence boundaries

| Product | Actual ownership / availability | Narrative eligibility |
| --- | --- | --- |
| Original Brigade | No current native B producer found; `B:docs/LEGACY_HARVEST.md:34` describes import mapping | Missing, not silently reconstructed from Council labels. |
| Legacy Senate importer | B `blackpod/advisors/senate.py:32`, `:69`, `:178`, `:267` reads supplied CSV and `Coverage_Conf` | Optional supplied evidence, not proof the original ensemble ran; not in current W packet. |
| Archivist / sector context | B `blackpod/advisors/archivist.py:43`, `oracle_market_context.py:40` read supplied context | Readers do not recompute original historical features; not connected in current W Council path. |
| Native Delphi scenarios | B `blackpod/advisors/delphi_scenarios.py:85` and `delphi_scenario_*` / `delphi_*report` modules | Implemented deterministic branches from Oracle, not independent forecasts. Not in current run; example files are not live output. |
| Armada | B `blackpod/advisors/armada.py:6` uses generic legacy placeholder | No native predictive evidence to narrate. |
| Governor | B `blackpod/governor/governor_deliberation.py:36`, `governor_decision.py:101`; W `governor_adapter.py:1171` | Recorded policy/readiness disposition only. BLOCKED under no-trade authority is not a bearish market opinion. |
| Alpaca live price overlay | Canonical Navigator live-data source; W read-only overlay | Ephemeral trade price, not a stored comparable market-history panel; never substitute it into adjusted historical bars. |
| Existing accepted brief | B `oracle_market_brief.py`; W saved-evidence producer/reader | Presentation over five source artifacts, not another independent analysis. Preserve it unchanged until a separately accepted version exists. |

## 4. Galactica's long-view mechanisms: what to recover conceptually

| Mechanism and original reference | What it added beyond a snapshot | Survived into the connected Battlestar Oracle? | Minimum useful design / correction |
| --- | --- | --- | --- |
| `G:archivist_bridge/breadth.py:14`; backfill `:121` | Above-50/200-session participation across dated histories | No; current breadth is positive-return fraction. Underlying histories/MA values now exist in E2/E3. | Derive a dated, declared proxy-participation trajectory; preserve eligibility and denominator. |
| `rotation.py:36` | Smoothed benchmark-relative series, rank changes, slopes and churn | No connected trajectory; current rank comparison has no prior input | Use comparable return-based relative strength, not ranking raw ETF/SPY price-ratio levels with arbitrary share-price scales. |
| `regime.py:21`; `fragility.py:18` | Rolling autocorrelation/realized volatility, dispersion and risk-gauge context | Only a different snapshot rank-group posture survived | Separate volatility, dispersion, participation and defensiveness before any regime interpretation. Original current runner fetched VXZ but checked VIX and fell back to SPY price; do not recreate that risk gauge. |
| `pattern_store.py:17`, `:49` | Counted recurring context combinations and retained example IDs | No connected equivalent | Source-bound dated state history, not a claim of “decades of memory” from persona text or duplicate calls. |
| `archivist_oracle/oracle.py:214`, `:251` | Similar historical configurations and subsequent paths | No | Original constructs 20-step sequences but scores only the last five; current sequence ignores requested cutoff. A later descriptive analog module needs honest session/as-of boundaries, comparable populations and non-overlapping episodes. Not required for the first temporal story. |
| Same file `:389`, `:471` | Sector-tier and regime transition counts | No; native Delphi rules are not equivalent | Correct conditioning and missingness. Original “stay primary” divides by all analogs, not just primary-start cases; it is not a valid conditional persistence probability. |
| `sector_field/encoder.py:54`, `interactions.py:9`, `engine.py:39`, `transitions.py:53` | Momentum/rank trajectories, correlations, state persistence/migration | No connected field analysis | Start with transparent dated relationships. Clustering/Markov machinery is optional; original fit/update/profile defects and per-invocation transition counting require correction before reuse. |
| `scripts/the_oracle_of_delphi.py:313`, `:328` | Integrated diagnosis from many individual analyses | No equivalent ensemble; current Council is a different deterministic graph | Borrow argument structure and attention to disagreement. Delphi itself was one captured run, not a source of long historical comparison. |

The transferable idea is **comparable dated observations → trajectories → relationships → qualified interpretation**. No need to transplant the older infrastructure or build two separate narrative engines.

## 5. Capability-to-evidence map

Each row answers the requested eight points: the question; available evidence; its owner; historical sufficiency; position relative to Council; necessary transformation; missing capability; and whether new collection is required. E1–E6 resolve to the exact owners and source paths above.

`PRE` means eligible upstream evidence, not a claim it was available before a particular saved Council run. `POST` means completed downstream analysis. `SEPARATE` means an independent capture/research path requiring explicit admission and timing checks. **Stored data is not automatically ready-to-use analytical evidence.**

### Question 1 — What does the market look like?

| Capability / question | Available evidence and owner | History sufficient? | Stage | Necessary analytical transformation | Missing today | New collection? |
| --- | --- | --- | --- | --- | --- | --- |
| Participation: is the move broadly shared within the observed market? | E1 Oracle return fraction; E2 canonical Navigator close/MA histories | Yes for declared proxies; not all-stock breadth | PRE; E2 separately captured | Compare participation with trend/leadership; separate sector cohort from benchmarks, factors, risk products and AAPL; include coverage | Canonical above-MA proxy breadth and relationship evidence | No for existing proxy panel; constituent-wide breadth needs an appropriate universe/history/metadata source. |
| Leadership: broad support or concentration in few sectors? | E1 absolute-move concentration; E2 sector returns/benchmark histories | Yes for retrospective proxy comparison | PRE | Retain legacy metric; separately identify directional relative-return leaders, concentration and breadth agreement | Named-sector leadership evidence and distinction between large losses and positive leadership | No for declared sector proxies. |
| Risk appetite versus defensive behavior: do multiple dimensions reinforce that reading? | E1 rank groups; E2 sector/style/risk-product prices | Yes for relative standing and subsequent change; not investor flows | PRE | Relate defensive/cyclical performance to participation, index trend and dispersion, allowing contradictions | Cross-dimension interpretation; verified group roles; no direct accumulation/flow evidence | No for price-based relative behavior. New source required to claim actual accumulation or allocation flows. |
| Market texture: coherent trend or fragmented conditions? | E2 MAs/Wilder ATR/OHLCV; E4 deterministic range/volatility measurements where compatible | Daily/weekly panel supports comparison after warmup; hourly panel incomplete | PRE or SEPARATE | Compare trend persistence, realized variability, cross-sectional dispersion and co-movement; do not equate these concepts | Market-level relational summary and provenance-compatible metric adapters | No for descriptive proxy texture; neither new regime thresholds nor a prediction model is implied. |

### Question 2 — How is that shape changing?

| Capability / question | Available evidence and owner | History sufficient? | Stage | Necessary analytical transformation | Missing today | New collection? |
| Breadth strengthening/weakening: compared with which date/horizon? | E2 common daily panel; E1 sparse snapshots | E2 yes after MA warmup; E1 alone no continuous trend | PRE / SEPARATE | Aligned dated participation levels/deltas on a comparable cohort; separate changing membership from changing prices | Prior-bound Oracle temporal input and comparison receipts | No for historical characterization. Future freshness eventually uses existing capture machinery, explicitly scheduled/authorized. |
| Leadership persistence/rotation: who retains or loses relative prominence? | E2 sector/benchmark histories; E1 prior-map formula exists but is unwired | Yes for explicit daily/weekly horizons | PRE | Relative returns, per-date ranks, rank transitions, leader persistence and turnover; handle ties deterministically | Canonical sector trajectory, horizon definitions and coverage | No for the existing panel. Do not copy Galactica's scale-dependent ratio ranking. |
| Technical structure: is price strength becoming more or less widely sustained? | E2 price/MA/ATR series and summaries; E4 raw trend/range context | Yes for existing multi-horizon observations | PRE / SEPARATE | Across-date and across-sector trend-distance/slope/persistence comparisons, with exact indicator definitions | Cross-sectional trajectory aggregation; summary zero fallbacks must not imply measured stability | No; reuse existing MA/ATR definitions and source series rather than add a competing indicator engine. |
| Emerging defensive behavior/regime transition: sustained change or a brief fluctuation? | E1 current posture; E2 dated relative structure; E3 broader historical assets | Descriptive change yes; validated transition probability no | PRE | Track reinforcing/dissenting trends across horizons; distinguish short/long-view disagreement and observational changes from state-label changes | Source-bound state history, reviewed regime semantics, evidence for persistence | No for a labeled descriptive transition hypothesis. Additional historical validation required for probabilities; more files alone do not solve it. |
| Sector relationships: are groups moving together, separating or exchanging rank? | E2 aligned sectors; E3 broader cross-asset cohort | Yes within common eligible windows; basis review required for E3 | PRE / SEPARATE | Comparable relative-return paths, dispersion/co-movement and their changes; explicit sample/window sensitivity | Relational time-series product; evidence for causal flows absent | No for descriptive coupling. New flow/macro sources needed for causal allocation stories. |
| Historical context: is this familiar, unusual or outside known coverage? | E2 daily/weekly history; E3 longer histories; G analog mechanism as reference | Enough for dated descriptive examples after validation; not calibrated forecast odds | PRE | Freeze method/cutoff, compare configurations, expose differences/coverage, avoid overlapping episode inflation | Audited analog/state contract, as-of-safe outcome eligibility, defensible sampling | No for bounded retrospective examples once source gates pass; new evidence may be needed for independent probability validation. |

### Question 3 — What does BlackPod collectively make of it?

| Capability / question | Available evidence and owner | History sufficient? | Stage | Necessary analytical transformation | Missing today | New collection? |
| Completed fleet assessment: what did the actual candidate/Senate/Council analysis conclude? | E5 canonical artifacts for the saved run | Single-run sufficient; longitudinal fleet evolution not recorded | POST | Source-bound synthesis of completed outputs, scope, reasons and absence; preserve their dependency on initial Oracle | Unified later narrative; current output is not original Brigade ensemble | No for the existing completed run. New authentic ensemble outputs require producer/integration work, not invented opinions or merely new prices. |
| Agreement/disagreement: genuinely different perspectives or repeated ancestry? | E1/E5 dependency IDs; E2/E4 share market data; optional E6 imports | Enough to distinguish lineage; independent consensus generally absent | POST, with PRE/SEPARATE sources admitted | Group claims by evidence ancestry, identify actual disagreement and different horizons; count neither artifacts nor repeated labels as votes | Explicit dependency/family annotations and relationship interpretation | No for lineage-aware synthesis; genuine new independent analysis requires actual completed products. |
| Conviction: strong evidence, heuristic confidence or just complete inputs? | E1 readiness/assessment confidence; E5 fixed candidate confidence; E4 percentiles/status | Existing meanings known; no cross-system calibration | PRE and POST, kept separate | Describe coverage, persistence and diversity of support qualitatively; preserve confidence semantics | Valid common confidence model; original cohort/vote evidence unavailable | No new data needed to explain limits. Do not create an aggregate confidence score. |
| Unusual behavior: does Sentry add a useful, distinct observation? | E4 frozen 20/60 sensor/attention receipts | Baseline history exists; production interpretation remains unvalidated | SEPARATE; optional later research context only | Relate explicit raw abnormality measurements to market context, annotate window differences, dates and research status | Approved narrative admission boundary; no validated production anomaly view | No for existing descriptive research evidence. This design does not authorize downstream Sentry integration or profile promotion. |
| Is the fleet itself changing its interpretation? | E5 history/evolution code; saved current report says unavailable | No adequate connected history | POST | Compare same-scope completed runs with aligned methods/mandates; separate policy changes from market changes | Genuine sequence of compatible analysis runs and connected history | Existing compatible runs can be inventoried; unavailable past reasoning cannot be recreated as contemporaneous evidence. Future collection means explicit analysis runs, not just market fetches. |

### Question 4 — What does the weather ahead look like?

| Capability / question | Available evidence and owner | History sufficient? | Stage | Necessary analytical transformation | Missing today | New collection? |
| Conditional implications: what environment is consistent with the observed structure? | E1/E2 admitted relationships; optionally E3 descriptive context | Enough for bounded hypotheses, not arbitrary future direction | PRE; later extension separately POST | Current conditions → observed transition → plausible implication → uncertainty; distinguish observed fact from scenario | Relationship-backed outlook contract and quality review | No for conditional, qualitative reasoning over existing evidence. Do not invent price targets or likelihoods. |
| Reinforcement/invalidation: what observable development would change the reading? | Same admitted measures and comparison dates | Enough to define testable watch conditions | PRE / POST separately | Link each condition to a supported interpretation and named observable; include counterevidence and “inconclusive” outcome | Typed watch-condition/evidence linkage and evaluated/not-yet-observed distinction | No to define conditions; subsequent authorized observations needed to evaluate them. No hidden refresh or execution trigger. |
| Probability-bearing forecast / macro cause / flows | No adequate validated forecast, flow or causal evidence in the current bundle | No | Not eligible | Would require independent definitions, point-in-time data, correct conditioning, holdout validation and/or additional sources | Scientific validation and missing source families | Outside the smallest design; do not manufacture these capabilities from prose, rank changes or historical frequencies. |

## 6. Smallest architecture that can deliver meaning

### Acyclic relationship

```text
Existing canonical sources
  ├─ Oracle snapshot/quality/measurements
  └─ Pinned completed-bar histories / compatible indicators
           │
           ▼
  Canonical temporal + relationship evidence
           │
           ▼
  Initial market interpretation ────────────────► Cabin market story
           (no downstream conclusions)

Existing native OracleReport ─► candidate/Senate/Council ─► Governor
          │                             │                    │
          └──────────────┬───────────────┘                    │
                       ▼                                    │
          Optional later fleet synthesis ◄─────────────────┘
          (Governor is operational context only)
                       │
                       ▼
          Cabin's separately labeled fleet interpretation

No return edge from later synthesis to initial Oracle, Council or execution.
```

This design does not authorize changing which artifacts Council consumes. Initially the existing native OracleReport and mission contracts remain unchanged. The long-view interpretation is an additive observation-only product. Any later decision to let a new analytical contract influence Council is a separate reviewed integration.

### Three small additions, reusing existing owners

**1. Canonical temporal/relationship evidence builder (B).**

Add an adapter and a bounded deterministic builder within canonical Oracle, not another data collector. Inputs are explicitly selected, immutable source descriptors. Reuse compatible canonical indicators, history checks, identities and receipts; do not copy Navigator, Sentry or provider code into W.

Start with E2's daily panel, treating the eleven sector proxies as the primary sector cohort, SPY/other indices as benchmarks, style/risk products as separately declared context, and AAPL as a symbol—not an extra sector. These are proposed roles for review, not a silent change to E1's existing 14-symbol formulas.

New analytical work should be limited to what no owner currently provides: aligned cross-symbol/time relationships, trajectory summaries, and evidence-linked interpretation inputs. Preserve original metric names and formulas. If an existing private helper needs a public adapter, expose/reuse that implementation later rather than duplicate it. Do not coerce differing ATR, breadth or adjustment definitions into false equivalence.

Existing MA50/MA200 series are available for a short/long trend-participation comparison; the full store supports other existing MA periods. Return, rank-change and persistence windows require a reviewed method specification before implementation. Do not import Sentry's experimental 20/60 settings or failed acceptance criteria as universal Oracle parameters. Continuous observations/deltas can be presented without inventing production regime thresholds.

**2. One canonical interpretation/narrative contract and renderer (B, ModelDock transport reused).**

Use one maintained contract with an explicit stage (`INITIAL_MARKET` or `POST_ANALYSIS`), common evidence rules and stage-specific allowed inputs. Conceptual names are design sketches, not schema changes in this review.

The existing brief contract consumes only five scalar/aggregate source families and has six fixed sections. It cannot express this design merely by rewording the prompt. A reviewed additive contract/version should admit temporal comparisons, relationships and later analysis references while preserving strict source binding and no-action rules. Keep current v1 readers and the accepted brief intact during any future migration.

ModelDock supplies language and bounded interpretation; it does not fetch prices, calculate indicators, invent transition counts, choose missing analysts, or decide authority. Oracle specifies no model. Canonical code owns request construction, evidence eligibility and output validation. Existing W transport, bounded diagnostics and immutable attempt/publication patterns should be reused through a thin integration rather than cloned into another narrator.

No automatic multi-batch model workflow is required for the initial 22-symbol context. Add batching only if later genuine fleet scope demands it, preserving source claims and denominators rather than accumulating ungrounded prose summaries.

**3. Thin Cabin consumer (W).**

Load the accepted canonical artifact, verify source/mission/stage relationships, render prose and drilldowns. Do not compute market relationships, select a regime, merge incompatible histories, or quietly turn old evidence into current analysis in the browser.

Reuse `OracleNarrative.tsx`, `OracleMarketBrief.tsx`, `oracle_brief_reader.py` and source-validation patterns. The current six book pages need not dictate the analytical schema; the existing book can show a narrative hierarchy with expandable supporting evidence. No new standalone routing/store/API service is required merely to describe this design.

### Minimal evidence and relationship contract

An admitted source needs:

- Source artifact hash/size, producer and method version, provider and adjustment basis/vintage.
- Instrument identity, declared role, population/cohort and coverage, missing/excluded items.
- Observed session/time, capture/availability time, generation time, and freshness deadline where applicable.
- Units, horizon, sampling/calendar policy, eligibility/warmup, and raw versus normalized measurement meanings.
- Upstream dependency IDs; same evidence family versus genuinely distinct source; research/production status; success/failure/not-run state.

A relationship record should retain:

- The question being addressed and its supporting fact/trajectory IDs.
- Dates/windows/populations being compared and the deterministic transformation/version.
- Observed direction/persistence/agreement/conflict, with magnitude available for inspection.
- Counterevidence, missing dimensions, alternative readings and explicitly unsupported interpretations.
- Separation between **measurement**, **derived relationship**, **interpretation**, and **conditional implication**.

This is not a collection of hard-coded market stories. A configuration may be coherent, contradictory or inconclusive. The same metric can support different interpretations when its companions, horizon or coverage differ.

### Temporal admission rules

1. Freeze one evidence manifest before analysis. Resolve `current.json` once, pin immutable snapshots, and reject incompatible/unavailable inputs; do not assemble a story from a moving index.
2. Use a common completed-session cutoff for the initial daily lens. Different horizons can coexist, but their timestamps and roles must remain explicit. Do not silently forward-fill missing observations or force every cohort to match by dropping inconvenient symbols.
3. **Availability matters as well as event date.** September 18 close captures produced after the `19:05Z` Oracle run were not evidence available to that initial assessment. A later report may use them as a new, clearly timed edition, not as the explanation of what the earlier Council knew.
4. Existing Council `generated_at` may describe supplied context time (`19:03:52Z`), before Oracle capture. Use source/stage lineage receipts for availability and dependency checks, not timestamp ordering of one field alone.
5. Keep real-time unadjusted Alpaca trades, intraday snapshots, completed adjusted daily bars, and weekly aggregates distinct. No automatic stitching or treating them as independent confirmations.
6. Past values reconstructed from today's adjusted series are retrospective context. They are not prospective observations, point-in-time backtest inputs, or repairs to the failed Sentry study.
7. Before source admission, validate required sessions, warmup, symbols, basis, currency/roles and tolerances. Hash integrity alone proves neither market truth nor scientific comparability.

### Corroboration and conviction rules

Oracle measurements → assessment → narrative → report is one chain. Candidate and Oracle output share a snapshot. Senate conditions on Oracle; Council aggregates those descendants. Native Delphi branches from Oracle. Governor applies policy. Sentry's two baselines share histories. None of these can be counted as independent votes simply because they have separate files.

Report **reinforcement within a shared analysis**, **a distinct temporal perspective on the same prices**, or **independent corroboration** only when the corresponding lineage supports that wording. A confident writer, a high readiness score, a heuristic confidence value and an empirical percentile are different things. Do not average them.

Permission, missing inputs, processing failures and market uncertainty also differ. A valid no-trade mandate can block a mission without implying a weak market. A missing analyst cannot be described as dissenting. No selected Sentry names does not prove ordinary market conditions if inputs or research sensitivity are limited.

## 7. The weather-ahead contract

Conditional outlook is useful without pretending to know an asset's future price. It should contain:

1. **Observed conditions:** what the admitted evidence actually describes.
2. **Observed transition:** what has changed over a stated interval—or explicit inability to determine change.
3. **Plausible implication:** a qualified interpretation of that combination, not a target or guaranteed direction.
4. **Reinforcing developments:** which observable changes would make that reading better supported.
5. **Invalidating developments:** what would contradict it, and what would leave it unresolved.

Illustrative logic, not a market finding: if a stable benchmark coincides with fewer sector proxies above their longer-term trend and increasing directional concentration, the interpretation may be that headline stability is becoming less broadly supported. Re-expanding participation would weaken that reading; further deterioration across additional sectors would strengthen it. This conclusion requires those actual observations, not a canned phrase attached to the word “breadth.”

Do not equate:

- Relative rank gains with capital inflows, rank losses with redemptions, or sector ETF prices with business expansion/contraction.
- Co-movement with causation, defensive relative strength with proven defensive accumulation, or a volatility product with VIX itself.
- Historical resemblance/frequency with a calibrated transition probability.
- Watch conditions with trade triggers, approvals, order instructions or risk-control changes.

Probability-bearing outlook would require predeclared outcomes/horizons, appropriate conditioning and denominators, independent or overlap-adjusted episodes, point-in-time evidence, chronological holdout validation and uncertainty estimates. It is **not part of the smallest proposed increment**. The initial weather report can be informative, conditional and explicit about ambiguity without those claims.

## 8. Cabin experience: meaning first, details available

Keep the Captain's Cabin as the presentation layer. Proposed reading order:

| Layer | What the operator should receive | Evidence/behavior boundary |
| --- | --- | --- |
| **Market story** | A concise diagnosis and connected explanation of the recognizable environment | No opening glossary or recap of Oracle's implementation. State observed universe and time without burying the story. |
| **Why BlackPod thinks this** | The strongest relationships plus the strongest qualification/counterevidence | Links to relationship records; do not count inherited conclusions as independent support. |
| **How it is changing** | Named comparison periods, persistence, handoffs and deterioration/improvement | Explicit “comparison unavailable” when history cannot support it. |
| **Sector / leadership structure** | Who contributes to the picture, where support is concentrated, and how groups relate | Declared sector proxy scope; charts illustrate the argument instead of substituting for it. |
| **Fleet interpretation** | Completed analysis, disagreement and missing perspectives | Separately labeled later stage; “not run” is acceptable. It must not delay or contaminate the initial market story. |
| **Conditional outlook / weather ahead** | Supported implications, reinforcement/invalidation conditions and unresolved alternatives | No targets, recommendations or made-up probabilities. |
| **Supporting evidence and metrics** | Exact values, definitions, timestamps, provenance, warnings, source files | Expandable but material uncertainty remains next to the affected claim. |

The displayed report needs distinct market-as-of, evidence-available-through and report-generated times. Show separate timing for later fleet analysis or Sentry context. If the current reference updates but analysis has not rerun, retain the prior narrative with its old time; do not display it as refreshed by association with a live chart.

A fallback should honestly offer the existing verified native narrative and evidence with “long-view interpretation unavailable,” rather than manufacture prose, silently use an old report, or relabel partial output as complete. Opening the book must not call a model or trigger analysis.

## 9. Smallest implementation sequence for later authorization

This is a proposed plan only; no step is begun by this document.

1. **Freeze a bounded saved panel and method specification.** Use E2 daily references for the declared proxy roles; inspect calendar coverage, adjustment/capture basis, warmup and numerical tolerances. Do not refresh thousands of histories or change the frozen Sentry protocol.
2. **Build canonical temporal/relationship evidence.** Add only missing trajectory/comparison work in B; reuse existing measurements where definitions match. Begin with participation, relative leadership, trend/dispersion and their agreement/conflict. Do not require clustering, analog forecasts, E3 stitching or research-profile promotion.
3. **Define and offline-test the canonical narrative contract.** Initial-market stage first; later-stage eligibility rules can be specified without integrating Council conclusions upstream. Preserve v1 and its accepted artifact. No prompt changes or inference until this design and implementation scope are authorized.
4. **Separately review one subsequently authorized frozen-evidence generation.** Check narrative usefulness and factual entailment apart from JSON validity. No automatic retries or market refresh implied.
5. **Integrate the accepted canonical artifact into the existing Cabin book.** W remains a reader/presenter. Only then consider a separately authorized post-analysis synthesis, broader audited histories or descriptive analog extension.

### Acceptance criteria for the future implementation

- The opening identifies a supported market configuration, including relationships, not merely metric names.
- Every change claim has comparable dated evidence; no inferred motion from a single snapshot.
- Broad-participation, narrow-leadership, defensive, contradictory, insufficient, missing-comparison and sector-dispersion fixtures exercise different evidence relationships without hard-coded conclusions.
- Missing history/analysts/metadata, contradictory windows and incomplete populations result in explicit limits or abstention.
- Separate price vintages, currencies/roles, duplicate sessions, future-unavailable data and research statuses cannot be silently mixed.
- Duplicate derivative artifacts do not increase conviction; downstream ancestry cannot enter the initial stage.
- Quantities, comparisons and cited relationships match deterministic evidence; schema-valid but unsupported prose fails review.
- Conditional outlook has observable reinforcing/invalidating conditions but no action authority or uncalibrated probability.
- Existing accepted brief, mission evidence, Sentry study and Governor/Navigator permissions remain unchanged; W does not become a second analytical implementation.

## 10. Decision summary and remaining limits

**Can build a useful first long-view lens from stored data:** yes, at the level of the declared sector/index/style proxy population, after canonical evidence admission and deterministic relationship work. E2 is the smallest and most consistent starting source. The core missing component is not another provider or a more expressive model—it is a temporal and relational evidence layer that the narrator can legitimately interpret.

**Already available as canonical Oracle analysis:** no. The histories exist, but the connected Oracle narrative does not consume them. Existing sparse Oracle snapshots and zero rotation placeholders do not establish temporal depth.

**Can honestly reproduce independent fleet consensus today:** no. Current candidate/Senate/Council analysis is real but largely shares evidence and Oracle ancestry. A later narrative can explain it accurately without claiming original Brigade consensus or independent agreement.

**Can provide conditional weather-ahead commentary:** potentially yes, from admitted relationships and explicit scenarios. Calibrated forecasts, capital-flow causation, whole-market constituent breadth and historical point-in-time certainty remain unsupported.

**Need fresh collection now:** no for the review or first saved-evidence characterization. Fresh future editions will need authorized new observations from existing acquisition owners. New source families are necessary only when the desired claim genuinely requires unavailable information; stale or incompatible sources must not be patched through prose.

**Preservation verified:** before/after SHA-256 comparisons found all 23 pre-existing changed/untracked W files and all three pre-existing changed B files unchanged. Both branch names and HEADs are unchanged. Only this design document was added. The accepted brief remains at SHA-256 `b34acea75b349dc99a301df7399da0868b8255aef0dd98fa25cab4204293dc1d`. Document whitespace checks found no errors; no application tests were run. No commit, push, merge, generation or production change is part of this review. Stop here for design review.

## 11. First implementation stage — deterministic evidence only

Implemented September 19, 2026 after approval of this design. Canonical ownership remains **Battlestar**: new `B:blackpod/oracle_temporal/` contains admission, deterministic analysis, versioned contract/schema and an explicit offline CLI. New `B:tests/test_oracle_temporal_{analysis,guardrails,contract}.py` characterize it. The full implementation specification, formulas, source boundaries, results and repeatable commands are in [`B:docs/ORACLE_TEMPORAL_EVIDENCE.md`](/Users/nikolai/BlackPod-Versions/blackpod_battlestar/docs/ORACLE_TEMPORAL_EVIDENCE.md).

No Build Week analytical or presentation implementation was added. This design addendum is its only task-specific source/document change; generated receipts live in ignored artifact storage. The package has no live-pipeline hook, narrator, ModelDock request, changed prompt, mission publication, downstream synthesis or execution capability.

### Architecture now present

`frozen E2 index + snapshot hashes + official captured calendar + declared metadata → canonical admission → temporal/relational evidence → semantic recomputation validation`

- Fixed 22-symbol daily population; eleven sector ETFs alone form the participation/leadership cohort. Other symbols retain benchmark/style/size/factor/risk-product/single-equity roles.
- Strict source, vintage, metadata, availability, OHLCV, indicator-warmup, known-calendar completeness and full-population alignment checks. No repairing, filling, joining away gaps, new downloads or cross-family stitching.
- Explicit 5/21/63-observation return/comparison offsets; canonical MA50/200; positive-return participation, gain concentration, population dispersion, return-relative spreads, tie-aware leadership changes, evidence conjunctions, prior-only historical positioning/configuration frequencies and explicit unsupported claims.
- Numerical equality uses documented ten-decimal derived-value representation, not a calibrated market threshold. Existing canonical SMA/Wilder ATR remain unchanged and reused.
- Versioned `blackpod.oracle_temporal_evidence.v1`; dated premises, source hashes, formulas, units, denominators and limitations. Rehashed but unsupported relationships fail full deterministic recomputation, even if structurally valid JSON.
- Immutable atomic file publication reuses the existing file publisher only. Validation receipt is the final completion marker; failed/incomplete writes are not accepted evidence. Sentry analytical behavior is untouched.

### Frozen real-evidence checkpoint

The approved E2 index hash remains `f26e4d0d63238284d00bca5d1be42181dad29d2f108bf6506c5c8c0f7ec432d1`. All **22 × 753** daily observations, September 19, 2023–September 18, 2026, passed admission at explicit frozen availability cutoff `2026-09-19T03:00:00Z`. This is a later completed-bar reconstruction, not a relabeling of the September 18 `19:05Z` Oracle mission.

- [Pinned input manifest](../artifacts/oracle-temporal-evidence-20260919/frozen/input_manifest.json): `oracle-temporal-input-e0d85bcb96731dd2d1792db79ae042318c8be791188a967e1846c2d47a924823`.
- [Structured artifact](../artifacts/oracle-temporal-evidence-20260919/evidence.json): `oracle-temporal-evidence-68309a6fe5daf2c24e5aae32f3b0c2e1798848ffe18630bc6d3fea219fdc17be`.
- [Recomputation receipt](../artifacts/oracle-temporal-evidence-20260919/evidence.validation.json): `VERIFIED_BY_RECOMPUTATION`; separate CLI verification reproduces the same ID. These links target local ignored artifacts, not committed fixtures.

### Added analytical value — engineering review

The output establishes information a single snapshot cannot:

| Comparison, August 19 → September 18, 2026 | Structured finding |
| --- | --- |
| Sector participation | MA50: 10/11 → 3/11; MA200: 9/11 → 4/11, while September 18 SPY remains above its MA200. |
| Relative sector leadership, 21-observation returns | XLB/XLE/XLV → XLC/XLE/XLK; only XLE retained. September 11/18 membership is instead unchanged, demonstrating comparison-horizon sensitivity. |
| Growth minus value proxy returns, 21 observations | IWF−IWD: −3.4744 pp → +2.9288 pp, a dated reversal rather than merely a current ranking. |
| Concentration versus dispersion | Positive sector returns: 9 → 2; top-three positive-gain share: 63.6332% → 100%, but sector return dispersion: 3.3524 → 3.1923 pp. Concentration and dispersion do not tell the same story. |

An independent Decimal spot-check reauthenticated 13 raw snapshots and confirmed the dated counts, spread and leader cohorts without using the analysis builder. XLC is a relative leader with a negative return; the only positive 21-observation sector returns at the final observation are XLE and XLK. These distinctions prevent a simplistic bullish-leadership story. The added-value criterion passes for this explicitly limited proxy panel; no final user-facing narrative is generated.

### Validation, limits and stop boundary

**327 tests and 67 subtests passed:** 96 new temporal tests, 158 existing Oracle/calendar tests, and 73 reused Navigator indicator/calendar tests. No UI or unrelated giant-suite rerun was necessary because no existing production callers or presentation code changed.

The artifact remains a declared-metadata, adjusted-capture reconstruction. Full pre-2026 exchange-session completeness is unverified; same capture exchange date does not independently certify adjustment revisions or vendor finality. Historical observations overlap and are not independent trials. Leadership retention describes comparison endpoints, not uninterrupted persistence. Material regime change, flows, causal defensive accumulation, transition probabilities, constituent-wide breadth, forecasts and fleet consensus remain unsupported. Native Oracle scalar definitions, Sentry research status, Governor and Navigator authority are untouched.

The accepted brief and pre-existing user work are preserved; neither repository's branch/HEAD is changed and nothing is committed, pushed or merged in this stage. Next is **review and acceptance of this analytical substrate**, followed only with authorization by offline initial-market narrative-contract work. ModelDock narration, prompts, Cabin integration and fleet synthesis remain outside this implementation.
