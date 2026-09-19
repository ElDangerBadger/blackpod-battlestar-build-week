# Oracle narrative parity audit

Audit date: September 18, 2026 (Pacific). Scope: **Phases 1–3 only; implementation paused for review.**

## Finding

The original narrative capability was not fully migrated into Battlestar. This is not primarily a missing Build Week screen or an insufficiently polished prompt.

The strongest recovered historical specification is the **Galactica Oracle family**, comprising three separate runnable paths:

1. **Archivist:** a concise interpretation of participation, fragility, dispersion, and volatility, including agreement and tension between signals.
2. **Archivist Oracle:** sector relevance/rotation, historical analogs, sector interplay, regime transitions, and uncertainty.
3. **Oracle of Delphi:** per-symbol Brigade/Senate evidence reduced through batch summaries into a fleet-wide headline diagnosis and analyst report.

Battlestar instead contains passive legacy placeholders, a newer deterministic snapshot/measurement/assessment/narrative/report pipeline, separate deterministic Delphi scenarios, and a recently added, narrower supplemental market-brief contract. Build Week already invokes the native Battlestar Oracle pipeline and consumes the supplemental contract. Neither reproduces the original family end to end.

**Historical narrative behavior is the source of truth for this audit—not historical unsupported conclusions, old model routing, or trading-oriented recommendations.** There is real saved narrative output, but also clear historical grounding and wiring defects. A schema-valid response, a file named Oracle, and a successfully imported module are not evidence of narrative parity.

## 1. Scope, checkpoints, and source attribution

### Repository aliases used below

Every `alias:path:line` reference resolves against this table. Function names are included because line numbers describe the audited working snapshot and can move.

| Alias | Absolute repository/directory root | Audited state |
| --- | --- | --- |
| `G` | `/Users/nikolai/BlackPod-Versions/blackpod_galactica` | Unborn `main`; no HEAD, refs, or reflog. Staged/modified filesystem snapshot. |
| `GC` | `/Users/nikolai/BlackPod-Versions/blackpod_galactica copy` | Unborn `main`; no HEAD, refs, or reflog. Additional preserved run artifacts. |
| `B` | `/Users/nikolai/BlackPod-Versions/blackpod_battlestar` | `update/2026-09-18-live-analysis`, HEAD `b2d79331521d57dbcdcdc1ccf8cb27f5bb9dca09`. |
| `W` | `/Users/nikolai/Projects/blackpod_battlestar_build_week` | `update/2026-09-18-live-analysis`, HEAD `5f1f63831bbf06b9310c6ec972b10b5c65b79c6b`. |

Both maintained working trees already contain uncommitted work. This audit does not reset, finalize, or extend that work. References below distinguish working-tree changes from committed features where material.

Search covered Galactica/main and copy, Destroyer, the standalone Archivist/bridge, archived Delphi variants, and Oracle-related candidates in Manowar, Quorum, Armada, Armada-quartile, Lean, and Projects. Reachable Battlestar history was inspected for original implementation signatures, not just current documentation. No lost full original engine was found in those searches. This is a bounded local-source finding, not proof that no other unavailable repository contains another version.

There is no honest original-Galactica commit SHA to cite. Current Galactica and copy have byte-identical principal Oracle/Delphi source. Their source and archived reports establish recoverable behavior, but report timestamps do **not** cryptographically attest which source revision produced each run.

### Historical source/output fingerprints

| Evidence | SHA-256 / identity |
| --- | --- |
| `G:archivist_bridge/archivist_oracle/oracle.py` | `3193941e56c3b8a077153fc49cc4f3ab5efcb806499434679f60822ab3fcc9a7` |
| `G:archivist_bridge/archivist_narrator/narrator.py` | `5e2e8a39b6170844b5119b217c53bb70d21dfd134aee925587e70df18b263c41` |
| `G:archivist_bridge/main.py` | `a024ddc651bdbdf35cc2024a577e846c7ff2fa1549471a5a7af6aaf96feed68b` |
| `G:scripts/the_oracle_of_delphi.py` | `26f4c4c62e9051aa0c7a38c78b6de04b2ba95d72548a23d8c942b7ed9e2b84e7` |
| `G:agents/ai_client.py` | `70752f2b55dc013d929f07699fdfd00b668dd83e3a465e990df47b9f9472f35e` |
| `GC:data/archivist_logs/latest_prophecy.json`, April 21 | `0b77b2f5240cc3822098bd6fc6f42945d4dddc8b9ad0bf8f16b31df1c42335ff` |
| `G:archivist_bridge/data/archivist_logs/latest_bridge.json`, April 20 | `39246317fb8f443def8637c2b2504d603af1c6bd97fdee27f254959c5525711e` |
| `GC:reports/2026-04-23/market_assessment_llama_compact.json` | `92f4eca469099e36d880ca32e78e7b9e1755ba05276bd12b6ae0ff48ef167de7` |
| Same April 23 report, `.md` | `d49576b4bbe831764d346bf199e414d69fbc2f16b6f5067407829de6426d6485` |
| `GC:reports/2026-02-26/market_assessment.md` | `6237859f54327c503a4dd4d60856f45369bb7472ed89f9082199d7d5e924bf41` |

An earlier analog engine survives byte-identically in `blackpod_destroyer/archivist_bridge/archivist_oracle/oracle.py`, `the_archivist/archivist_oracle/oracle.py`, and the top-level `archivist_bridge/archivist_oracle/oracle.py` under BlackPod-Versions: SHA-256 `ce9b56f4b3d8c5530401a086205e1c92d4c1418df9dc898ac81a7181a9fd7da7`. It also matches Galactica's staged index blob `b98e0d327e7203245224077540f0ff1906b6b96b`. Current Galactica expands this leader-only ancestor with full ranked-sector tiers and transition evidence. It is the richer recovered candidate, not proof of a fully working sphere product.

`G:archive/legacy/scripts/the_oracle_of_delphi_stable_v1.py` (SHA-256 `4fb62546d574ae69f104e48ef55b13c8aaaf14239a9fbaca19880b97bdf1847c`) and `the_oracle_of_delphi copy.py` preserve earlier fleet synthesis. Current Delphi adds partial-input accounting, checkpoint/resume, batch artifacts, compaction, fallback, and final-only synthesis. Earlier variants do not expose a richer narrative architecture.

## 2. Reconstructed original pipeline and file inventory

These paths must not be collapsed into one fictitious original pipeline. They share market context conceptually, but their evidence, invocation, and outputs differ.

### A. Archivist: present-state market-context narration

```text
Historical adjusted-close series / risk proxy
  → relative strength, MA participation, fragility, regime features
  → timestamped snapshot + bucketed historical pattern document
  → meaning / tension / tail-risk instructions
  → Destroyer chat endpoint OR deterministic synthesis fallback
  → free-text response (no semantic grounding validator)
  → latest_bridge.json / snapshot log / pattern store
  → CLI / executive report

SectorFieldEngine → structural summary appended AFTER narration
                   (not part of the narrator's reasoning input)
```

| Stage | Exact original implementation | Recovered behavior / limitation |
| --- | --- | --- |
| Universe/configuration | `G:archivist_bridge/main.py:25`, inline `BENCH`, `SECTORS`, `FACTORS`, `RISK`, multiplier maps | SPY, ten sectors, seven factors, VXZ. Not the same universe as current Battlestar. Templates/config are largely inline Python, not a missing external prompt file. |
| Collection | `main.py:34` `_fetch_prices_yfinance`; `:157` `run_once` | Long adjusted-close history from 1998, close fallback, sorting/forward fill. This runner fetches directly. Separate `G:main.py:109` `run_once` prefers cached parquet; these entry points are not interchangeable. |
| Historical snapshots | `G:archivist_bridge/backfill_archivist_history.py:41` `fetch_historical_prices`, `:121` `calculate_snapshot_for_date` | Trailing 252 sessions, minimum 200 observations, at least three eligible sectors; historical risk input where available. No backfill was run in this audit. |
| Rotation | `G:archivist_bridge/rotation.py:36` `RotationModule.compute` | Smoothed relative strength against SPY, ranks/rank changes, rotating-up/down/decaying flags, top-quartile churn. |
| Breadth | `G:archivist_bridge/breadth.py:14` `BreadthModule.compute` | Fractions above 50-/200-day averages; strong/mixed/weak. Not the fraction of positive one-session returns. |
| Fragility | `G:archivist_bridge/fragility.py:18` `FragilityModule.compute`; `main.py:181`; `backfill_archivist_history.py:179` | Percentile → normal/caution/stressed. Concrete original wiring defect: current runner fetches VXZ but checks for VIX, normally falling back to SPY's price percentile. Backfill separately uses VIX when available. Current/historical inputs are not equivalent risk evidence. |
| Regime | `G:archivist_bridge/regime.py:29` `RegimeModule.classify` | Return autocorrelation, realized volatility, cross-sector dispersion, breadth and fragility → trending/mean-reverting/rotational/stressed-vol. |
| Sizing context | `G:archivist_bridge/sizing.py:3` `SizingModule` | Regime/breadth/fragility multipliers. Historical capability to inventory, not authority to port position controls. |
| Evidence persistence | `G:archivist_bridge/snapshot_logger.py:14` `make_snapshot`, `:77` `append_snapshot`; `pattern_store.py:17` `pattern_key`, `:49` `upsert_pattern` | Timestamped contexts, bucket combinations, occurrence counts, sample IDs. Pattern forward-return fields are placeholders, not measured results. |
| Prompt/persona | `G:archivist_bridge/archivist_narrator/narrator.py:13` `_build_prompt` | Market-context narrator; situation → why the combination matters → posture; 3–6 sentences, 120–180 words, no hype/guarantees. Input is bucketed pattern/count/sample IDs, not the entire raw series. |
| Invocation | `G:archivist_bridge/archivist_narrator/openai_adapter.py:11` `OpenAILLM`, `:18` `complete`; `narrator.py:152` `interpret_pattern` | Despite adapter name, calls Destroyer chat endpoint with a selected model. Extracts completion content. Not current ModelDock. |
| Fallback and cross-signal reasoning | `narrator.py:53` `_compose_without_llm`, especially `:123` | Explicit combinations: stressed fragility + subdued volatility; strong breadth + low dispersion; weak breadth + high volatility. Fallback on exception, without narrative entailment validation. |
| Output | `G:archivist_bridge/main.py:228`, `:240`, `:251`, `:255`, `:272`, `:274` | Dynamic brief, optional generated prose, appended structural text, bridge/snapshot JSON, CLI. Cwd-dependent root and nested `data/archivist_logs` contain different “latest” captures. |

**Observed output:** nested `latest_bridge.json` dated April 20 interprets strong participation alongside stressed fragility, rather than defining those terms separately. Root `data/archivist_logs/latest_bridge.json` dated February 3 is a different fallback capture. Neither is current market evidence.

### B. Archivist Oracle: historical sector-rotation/analog narration

```text
Current snapshot + historical snapshot JSONL
  → ordered sector tiers + context signatures
  → sequence matches + observed 5/10-snapshot outcomes
  → sector-transition / regime frequencies and warnings
  → sector analyst persona + analog dates + cross-sector reasoning instructions
  → Destroyer completion
  → raw prose; transport/shape checks, no narrative grounding validator
  → latest_prophecy.json + lightweight run log
  → narrative-first console report / Communiqué
```

| Stage | Exact original implementation | Recovered behavior / limitation |
| --- | --- | --- |
| Input selection | `G:archivist_bridge/oracle_run.py:21` `load_current_state`, `:501` history fallback; `archivist_oracle/oracle.py:57` `_load_snapshots` | Current JSON plus historical JSONL; malformed history lines skipped with a warning. |
| Derived context | `oracle.py:81` `_get_rotation_signature`, `:112` `_extract_sector_rankings`, `:166` `_extract_sector_tiers` | Breadth/fragility/dispersion/vol buckets plus primary/secondary/tertiary/inactive sector relevance. First three ranks primary, next three secondary, next three tertiary. Leader-list fallback when full ranks absent. |
| Analog matching | `oracle.py:214` `_sequence_similarity`, `:251` `find_analogs` | Recent-weighted Jaccard similarity; default 20-snapshot sequence, minimum similarity .6, top 15; examines 5-/10-snapshot outcomes. Snapshot steps are not independently certified trading-session intervals. |
| Outcome transformation | `oracle.py:339` `_summarize_analog`, `:389` `_analyze_sector_outcomes`, `:471` `_analyze_regime_transitions` | Promotions/demotions/stable leadership; before/after tiers; empirical relevance/primary/fading and regime frequencies. Forward-return output remains TODO/empty. |
| Reasoning input / persona | `oracle.py:535` `_build_oracle_prompt`, task at `:598` | Current regime/breadth/fragility/features/tiers; up to ten dated analog descriptions; sector and regime probabilities. Persona's “26 years” is an instruction, not an audited coverage guarantee. |
| Narrative structure | Same `_build_oracle_prompt` | Sector rotation → sector interplay → regime dynamics → edge cases → grounded probabilities; dated analog citations; correct sector identities; absent sectors; explicit insufficient-coverage language. |
| Invocation / raw response | `oracle.py:478` `_call_llm` | Direct Destroyer chat completion, explicit model, system/user messages, temperature .7, default 1000 tokens. Timeout/error becomes a returned string rather than a failed narrative artifact. |
| Validation / uncertainty | `oracle.py:633` `_detect_warnings`, `:685` `prophesy` | Fewer than three analogs suppresses model call. Divergent regime/rotation, coverage/count warnings. Confidence based on count, not truth or successful prose generation. No citation/entailment check. |
| Persistence | `G:archivist_bridge/oracle_run.py:261` `save_prophecy`, `:296` `log_prophecy_run` | Narrative + sector/regime forecasts + warnings + top-five analogs, latest JSON and append log. Full request/response attestation weaker than current architecture. |
| Presentation / evaluation | `oracle_run.py:185` `print_prophecy`; `:110` `compute_regime_accuracy`, `:120` `compute_sector_eval`, eval/backtest paths `:403`, `:450` | Narrative first, then warnings, forecasts, probabilities, analogs. Evaluators concern forecast outcomes, not narrative validity. |
| Intended helper | `G:archivist_bridge/Consult_The_Oracle.py:1` | Two-command Archivist→Oracle workflow; saved helper lacks `import subprocess`. Not proof of a working integrated entry point. |

**Observed output:** `GC:data/archivist_logs/latest_prophecy.json` dated April 21 has 15 analogs and substantial sector rotation/interplay/regime/edge-case prose. It is also embedded in `GC:logs/diplomatic_cable/executive_debrief.md:432`. Sector interplay is therefore demonstrated historical narrative behavior, not a new idea inferred only from a prompt.

**Original defects that constrain parity:** prose copies illustrative `6/8` and `5/8` prompt claims despite 15 analogs, contradicts persisted regime probabilities, and misstates tiers. A later nested April 24 prophecy persists an HTTP 502 error with high confidence. Analog matching takes the recent sequence from the end of supplied history rather than a current-state cutoff; the backtest passes full history. As-of boundaries and outcome availability need correction before historical fixtures could establish valid analog behavior. Current snapshots can omit full ranks while backfilled snapshots include them. None of these defects is authorization to fix or rerun the old system during this audit.

### C. Oracle of Delphi: fleet-wide synthesis

```text
Per-symbol OHLCV / forecast quantiles
  → Brigade context and module assessments
  → Senate votes / cohesion / dissent / final decisions
  → terminal-log parser → fleet summary + per-symbol signal cards
  → batched narrative reasoning → saved batch summaries
  → final synthesis instructions + fleet summary + batches
  → Destroyer completion
  → free-text Markdown (no substantive grounding validator)
  → signal_deck / oracle_state / batch artifacts / market_assessment JSON
  → grand-assessment Markdown report
```

| Stage | Exact original implementation | Recovered behavior / limitation |
| --- | --- | --- |
| Original upstream evidence | `G:phase2_forecast_engine.py:192` `generate_forecast`; `run_brigade_senate.py:29` `load_forecast`, `:92` volume ratio, `:125` `load_raw_ohlcv` | Q10/Q50/Q90/Pattern CSV and market history. These are model/agent-derived evidence, not equivalent to a canonical price snapshot. |
| Agent transformation | `G:agents/blackwell_brigade.py:761` `_calculate_context`, `:737` `BlackwellBrigadeWatchtower.analyze`; `agents/senate.py:938` `Senate.deliberate` | Forecast skew/tails/regime; Scout/Sentry/Advisor/Canary/Pathfinder/optional Decay; ensemble votes, dissent, cohesion. |
| Transcript producer | `G:run_brigade_senate.py:54` `run_brigade_senate_for_symbol` | Prints the structured terminal transcript consumed by Delphi. |
| Parsing | `G:scripts/the_oracle_of_delphi.py:73` `parse_terminal_log` | Extracts module actions/confidence/reasoning, Senate direction/confidence/reasoning, decision/cohesion/dissent, missing/incomplete records. Regex transcript coupling. |
| Reasoning input | `the_oracle_of_delphi.py:202` `build_signal_cards` | Fleet completion/direction counts, average confidence/cohesion, module-action distributions; per-symbol votes, top truncated reasons, override/incomplete flags. |
| Batch preparation | `:279` `chunk_cards`, `:313` `_make_batch_prompt` | Default ten-symbol batches; observations, dominant risks, consensus versus overrides, three hypotheses, representative symbols and reasons. |
| Final narrative instructions | `:328` `_make_final_prompt` | Fleet summary + batch observations → one coherent market statement. One-paragraph headline diagnosis first; tilt/consensus, risk signals, structure/breadth/concentration, posture, watchlist, uncertainty. |
| Model/system invocation | `:429` `call_llm`; `G:agents/ai_client.py:50` `_build_payload`, `:79` `generate`, `:204` `create_ai_client_from_config` | Oracle of Delphi persona, coherent market/regime assessment with uncertainty. Direct Destroyer route, caller-selected model, optional fallback model. Historical client combines system/user instructions for compatibility; factory disables its optional constitution layer. Not ModelDock. |
| Response handling | `:359` `_run_final_with_fallback`, `:543` `_run_batch_with_fallback`, `:294` `_compact_batch_summaries` | Transport handling, optional retry/model fallback, literal truncation of batch text. No narrative schema, citation, entailment, or unsupported-symbol validator. |
| Persistence / resumability | `:517` `_save_batch_artifacts`, `:610` `main`, final output around `:799` | Signal deck, batch prompts/replies/timing/errors, `oracle_state.json`, resume/final-only, final prompt, JSON source metadata and grand assessment. |
| Rendering | `:409` `render_markdown` | Metadata → fleet JSON snapshot → LLM Grand Assessment. Analyst prose leads the assessment itself, but original Markdown still placed raw fleet JSON above it. No separate Oracle browser renderer proven. |

**Dependency-order issue:** original Delphi is a *post-Brigade/Senate* synthesizer. Current Battlestar Oracle feeds Council/Senate/Governor. Porting the old dependency graph literally would introduce a cycle or silently change Oracle's role. Behavioral restoration must explicitly separate primary measured-market interpretation from optional, labeled ensemble-context interpretation. This needs a reviewed design, not a prompt substitution or permission to integrate Council now.

**Observed output:** the April 23 compact report records 163 symbols, 124 completed decisions, 39 missing, 162 flagged incomplete, and 17 batches. `GC:reports/2026-04-23/market_assessment_llama_compact.md:63` opens with a market diagnosis; `:66` qualifies direction by cohesion; `:69` discusses risk; `:72` structure; `:75` posture; `:78` watchlist; `:92` limits. Earlier February 26 output demonstrates the same architecture over 108 symbols/93 completed. These are actual saved narratives, not just template aspirations.

They are not valid conclusion goldens: examples extrapolate batch statistics to the whole fleet, infer market uncertainty from failed/incomplete processing, invent names in small-input runs, and include investment-oriented posture advice. Recovery should preserve synthesis, denominator/coverage awareness, and uncertainty—not these mistakes.

### D. Supporting structural field, reporting, tests, and documentation

| Capability | Original files/functions | Wiring / finding |
| --- | --- | --- |
| Full-sector feature space | `G:archivist_bridge/sector_field/encoder.py:54` `FieldEncoder.encode_full_history`, `:145` feature vector; `interactions.py:9` `InteractionMetrics.compute` | Sector momentum/relative strength/rank/rank velocity/volatility, correlation/dispersion/churn/interactions. Actual vector has 58 dimensions despite 54-dimensional comments. |
| Cluster/transition evidence | `sector_field/clustering.py:18` `ClusterEngine.fit`, `:33` `assign`; `transitions.py:13`, `:18`, `:44`, `:53`; `profiles.py:13` `ClusterProfileBuilder.build`; `engine.py:39` `SectorFieldEngine.compute`, `:72`, `:140`; `persistence.py` | KMeans/assignment, transition counts, entropy, multistep probabilities, cluster profiles and local model artifacts. Profile churn/index and forward-return alignment defects need investigation before reuse. |
| Structural narrative | `G:archivist_bridge/main.py:94` `build_structural_narrative`, append at `:251` | Persistence/migration/entropy/transition and multistep description appended after Archivist prose. Not fed to Oracle/Delphi prompts. |
| Sphere-like prototype | `G:archivist_bridge/viz/state_space_3d.py:54` `SectorStateSpace3D.render` | PCA cluster bubbles scaled by occupancy, transition edges, energy surface. No caller found; unseeded visual noise. Bubbles represent **state clusters**, not conserved sector capital. A fully integrated expanding/contracting sector sphere is **UNKNOWN**, not recovered as a working product. |
| Executive report | `G:scripts/the_communique.py:320` `extract_oracle`, `:625` `render_md`, `:817` `main` | Copies prophecy into Executive Synthesis → Environment → Belief Stack → Execution Observations → Contract Fit → Recommendations → Appendices. Executive sentence is deterministic, not another LLM engine. Text-derived direction/risk and clamped probabilities are not safe canonical interpretations to transplant. |
| Input inspection sibling | `G:scripts/brigade_debrief.py:97` `parse_log`, `:257` `render_markdown`, `:323` `write_summary_csv`, `:358` `main` | Same transcript → per-symbol JSON/Markdown/CSV, incompleteness/dissent; does not produce market synthesis. |
| Original tests | `G:archivist_bridge/test_oracle_analogs.py:26`; `oracle_run.py` evaluation/backtest | Manual smoke/display script, no assertion-based narrative characterization. No Delphi/Archivist narrative tests found under original `tests/`. Backtest is not a grounding test. |
| Generic original contract | `G:governor_contracts/oracle_assessment.py` | Advisory field/probability validation exists, but is not called as a narrative validator by the recovered generation paths. |
| Original docs | `G:README_RUNTIME.md:84`, `docs/GOVERNOR_ARTIFACTS.md:50` | Distinguish Archivist/Oracle/Delphi advisory artifact producers and their artifact locations. Useful routing evidence, not proof every named path is functional. |

## 3. What made the original narrative an analyst narrative?

| Question | Recovered behavior, with source anchor |
| --- | --- |
| What was it answering? | What market environment is this, how do its parts reinforce/conflict, and what historical or ensemble evidence qualifies the reading? Archivist `_build_prompt`; Oracle `_build_oracle_prompt`; Delphi `_make_final_prompt`. Oracle additionally asked about possible 5–10-step transitions. |
| How did it combine dimensions? | Archivist joined breadth/fragility/dispersion/volatility; Oracle joined sector tiers/analog outcomes/regime; Delphi joined individual signals and consensus quality across the fleet. These were different evidence paths, not one omniscient narrator. |
| How did it move from measurements to interpretation? | Conditional combinations, observed analog transitions, and explanations of why agreement quality changes the meaning of a directional majority. `narrator.py:123`, `oracle.py:339`, Delphi `:313`, `:328`. |
| Agreement | Strong participation with low dispersion could reinforce a common trend; high-cohesion ensemble decisions differed from mere majority direction. These are original interpretation rules, not guaranteed truths to assert for every fixture. |
| Conflict | Strong breadth versus stressed fragility; risk-module objections versus directional votes; analogs with divergent outcomes. Saved April 20 bridge and April 23 assessment demonstrate this rhetoric. |
| Uncertainty | Insufficient analog count suppresses generation; missing-sector/analog-divergence warnings; explicit insufficient relationship coverage; partial/compacted fleet limits. Implementation sometimes overstated confidence despite these intentions. |
| Participation / breadth | Archivist measured above-MA participation. Delphi used fleet decision-distribution proxies. Neither equals current Battlestar's positive-return fraction; the scopes must remain labeled. |
| Leadership | Oracle represented ordered relevance tiers, promotions/demotions, persistence and fading. Delphi representatives/watchlists were a different notion and lacked guaranteed sector classification. |
| Risk | Fragility versus surface calm, volatility/whipsaw, tail and regime disagreement; Delphi risk-module concerns. Trading-oriented recommendations are not a required restored authority. |
| Sectors | Oracle explicitly requested and produced sector push/pull and competing leadership, citing historical episodes. Claims require verified evidence; conservation of capital was not established. |
| History | Pattern counts/example IDs; dated sequence analogs and forward-outcome frequencies. Delphi itself was a single-run synthesis, not a robust temporal comparator. Historical look-ahead defects prevent treating existing backtests as proof. |
| Overall picture | The final diagnosis preceded its explanatory argument, connecting participation, leadership, consensus, risk and limitations. It answered a market question instead of explaining what Oracle is. |
| Why not a metric glossary? | Connected interpretation, concrete entities/episodes, explicit agreement/disagreement, scope and alternative readings. Longer output alone was not the differentiator. Some prose achieved this form without reliably proving its assertions. |

## 4. What Battlestar and Build Week actually do now

### Native Battlestar pipeline

```text
Configured proxy fleet → provider snapshot → normalization
  → quality/readiness → approved advisor input
  → aggregate measurements → diagnostics → fixed-threshold assessment
  → deterministic enum-to-sentence narrative → OracleReport
  → output files / manifest / ledger
  → Build Week mission artifact capture → Cabin reader → Oracle book
```

| Layer | Exact current implementation | Difference from original |
| --- | --- | --- |
| Provider/universe | `B:configs/universes/oracles_vapors.example.yaml:1`; `blackpod/runtime/yfinance_snapshot_provider.py:29`, `:62`, `:123`; `fleet_snapshot_normalizer.py:30`, `:106` | 21 configured proxies; `fast_info` snapshot and return/gap/range fields. This path does not gather original multi-period adjusted histories or risk/analog evidence. |
| Safety/readiness | `B:blackpod/runtime/fleet_snapshot_quality.py:42`, `fleet_snapshot_readiness.py:37`, `advisor_snapshot_gate.py` | New explicit evidence/readiness gates worth retaining. Technical readiness is not confidence in a generated interpretation. |
| Orchestration | `B:blackpod/runtime/oracle_pipeline.py:75` `run_oracle_pipeline`, output writes `:124`, `:212`, `:282` | Ends at OracleReport; no old Archivist/analog/Delphi generation or current separate Delphi scenario runner. |
| Measurements | `B:blackpod/advisors/oracle_measurements.py:135` `build_oracle_measurements_from_snapshot_input`; eligible sets `:23`, extraction `:321`, formulas `:607`, `:613`, `:621`, `:630`, `:649` | Eleven sectors + SPY/QQQ/DIA. Seven observed proxies excluded: VXZ, IWF, IWD, IWM, MTUM, USMV, QUAL. Positive-return breadth; largest two absolute moves/total absolute moves; cross-sectional dispersion; group rank scores. Not original MA breadth, realized volatility, fragility or tier transitions. |
| Temporal context | Same file `:182` passes `prior={}`; `_rotation_velocity` `:630` | Missing comparison yields zero placeholder and `MISSING_PRIOR_ORACLE_MEASUREMENTS`. Zero is not evidence of stability. Pipeline/Build Week call supplies no prior snapshot. |
| Interpretation/prose | `B:blackpod/advisors/oracle_assessment.py:113`, thresholds `:21`; `oracle_narrative.py:97`, `_summary` `:160`, commentary lookups `:170` | Four postures, independent fixed sentences. Names such as expanding/contracting do not prove measured temporal change. No generated cross-signal analyst synthesis here. |
| Report/contracts | `B:blackpod/advisors/oracle_report.py:114`; `blackpod/contracts/oracle_{measurements,measurement_diagnostics,assessment,narrative,report}.py` | Typed deterministic artifacts, IDs, hashes, source lineage. Aggregate report does not preserve all per-symbol return/rank fields in the narrative evidence catalog; normalized snapshot exists separately. |
| Legacy adapters | `B:blackpod/advisors/oracle.py:6`, `delphi.py:6`; `_legacy_file.py:12`, `run` at `:22` | Hash existing files, emit confidence-zero HOLD and placeholder text. Do **not** parse or migrate original narratives. |
| Separate newer Delphi | `B:blackpod/advisors/delphi_scenarios.py:85`, `delphi_scenario_history.py:54`, `:63`, `:83`, `delphi_scenario_evolution.py:79`, `delphi_evolution_report.py:57`, `delphi_evolution_narrative.py:60`, `delphi_report.py:79`; corresponding contracts | Deterministic future-scenario/history/evolution framework. `build_delphi_scenarios` discards narrative argument (`:92`). Not original fleet synthesis and not invoked by `run_oracle_pipeline`. |
| Other consumers | `B:blackpod/runtime/advisor_manifest.py:18`, `dashboard_export.py:190`, `:578`; `blackpod/governor/input_packet.py:101`, `council_synthesis.py:148`, `deliberation_engine.py:67`; Senate/Governor intake modules | Consume typed Oracle/Delphi context. No evidence that these callers invoke a hidden original narrative engine. No authority or consumers changed by this audit. |

### Narrative paths layered on top

1. **Build Week fact-selection enrichment:** `W:src/blackpod_build_week/oracle_enrichment_workflow.py:329` `run_oracle_enrichment` loads five hash-verified Oracle artifacts (`:622`), projects fields (`:690`), builds a request (`:742`, `:782`) and calls ModelDock. `contracts/oracle_narrative.py:1098` creates a catalog; `:1207`/`:1316` selection/expansion binds IDs to deterministic statements. Its prompt (`:1688`) permits one-to-five facts, a one-sentence summary beginning `Validated Oracle facts reflect `, a one-sentence interpretation beginning `The source-linked facts suggest `, empty uncertainties, and an exact confidence sentence. Vocabulary/numeric/semantic restrictions appear at `:1452`, `:1550`, `:1577`, `:1596`. This is a new, very narrow BW-owned contract, not migrated original narration.

2. **Canonical supplemental market brief:** `B:blackpod/advisors/oracle_market_brief.py` is a pure evidence/prompt/schema/validation/sealing module. At working-tree lines `:211` `build_evidence`, `:318` `build_output_schema`, `:370` `build_prompt`, `:465` `validate_draft`. It consumes measurements, diagnostics, readiness, assessment and report; six fixed sections: participation, leadership, rotation, risk, watchpoints, limits. It has no provider/model IO, original histories, per-sector analogs, fleet agent deck, news, or separate Delphi scenarios. Prose prohibits numeric quantities/dates/tickers and broad action/prediction vocabulary. Citations bind to facts but do not prove entailment. Receipt validation currently expects real `mlx` provenance; that is a provider-specific acceptance constraint, not client-side model selection.

3. **Build Week supplemental producer:** `W:src/blackpod_build_week/oracle_market_brief.py:58` `load_canonical_brief_module` loads the exact canonical module and records its hash; `:101` `load_mission_evidence`; `:318` `generate_market_brief`. It owns the saved-mission request, structured-output transport, immutable attempt receipts, validation and exclusive publication. Working-tree changes send canonical JSON Schema and verify structured-output acknowledgement even for injected executors (`:426`). No client model selection. This supplement does not rewrite the mission's earlier ModelDock stage or feed Council/Governor.

4. **Build Week native consumer:** `W:src/blackpod_build_week/oracle_adapter.py:835` `_oracle_worker` verifies and invokes `B:blackpod/runtime/oracle_pipeline.py` at `:865`; `oracle_workflow.py:120` captures canonical results and protects completed attempts. `unified_mission_workflow.py:145`/`:149` separately wires native Oracle and fact-selection enrichment. `harbormaster.py:747`, `:780` exposes those workflow entry points. Native Oracle is **already connected**.

5. **Presentation:** `W:src/blackpod_build_week/oracle_brief_reader.py:79` validates the supplement's receipt/evidence; `cabin_reader.py:444` adds its manifest reference. `W:ui/src/data/loadMission.ts:568` verifies receipt hash, mission correlation, source references and fact values; `validateOracleMarketBrief.ts:58` validates shape. `books/OracleNarrative.tsx:47` renders accepted supplement first, otherwise native report/narrative without mixing sources; `:97` renders older enrichment separately. `components/OracleMarketBrief.tsx:37` displays accepted prose verbatim, then sources/limits; `books/OracleOverview.tsx:28` and `data/oracleOverview.ts:85` expose evidence, not new analysis. `books/bookPages.tsx:166` retains six pages. No UI generation, sector sphere, or browser-side market synthesis is present in this path.

The currently dirty UI already prioritizes the accepted brief's first four paragraphs. That can reduce clutter; it cannot turn their independent measurement descriptions into missing historical/sector/fleet synthesis. The UI disclosure label “Original Oracle narrative” currently means **native Battlestar deterministic prose**, not historical Galactica. That terminology needs future correction after review.

### Accepted brief preserved by this audit

`W:artifacts/live-analysis-20260918-001/missions/mission-live-aapl-20260918-001/presentation/oracle_market_brief.json`

- Brief ID: `oracle-market-brief-d1fa623a1c4f856766ad21976eec2f969e2c1ce6f560e4ff6093534710c8b3d8`.
- Generated: `2026-09-19T03:39:28.887086Z` (September 18 Pacific).
- SHA-256: `b34acea75b349dc99a301df7399da0868b8255aef0dd98fa25cab4204293dc1d`.
- Headline repeats the native report headline; its six paragraphs separately paraphrase participation, concentration, unavailable rotation change, group ranks, warnings and coverage. It contains no original analog/sector-interplay or fleet consensus argument.
- Reading that saved artifact is sufficient to explain the user's concern. No fresh generation or replacement was performed.

### Migration history confirms a new implementation, not a completed port

| Battlestar commit | Change relevant to this audit |
| --- | --- |
| `afdc604605fb78ded94c29d09f588410de2fd9fb` | Governor-first foundation; Oracle/Delphi legacy placeholders. |
| `8d5f8ed89ce4d6538fcc951a609e84c255f93a85` | Passive Oracle market context. |
| `4563e7c40c1f7aacfb2a737fa1eb9e9db81658e8` | New measurements. |
| `09a3388832298d3f845e05c1e4d0770665e51585` | New assessment framework. |
| `c3a16d7ffffa2f162eb108fc1c2a0c1e23499dd1` | Deterministic posture-to-sentence narrative, not original narrator import. |
| `ec1c182b31ed9423c9b973c607fefcf831a64101` | Oracle report layer. |
| `ff861aba3643a766f72e8eeaca43a3890a1938d3` through `76c12ce395304b61e4831a06f17c50c65d1d9bd5` | Separate deterministic Delphi scenarios/history/evolution/report. |
| `c56f31d62ca6393afcb273bccdf73c70c76b1dba` | Native live Oracle pipeline runner. |
| `1c2b9b52fa497625ef93eb56220b6a29bc8ac867` | New supplemental source-linked market-brief contract, September 18. |

`B:docs/LEGACY_HARVEST.md:35` lists original Oracle/Delphi as future adapters; `docs/ARCHITECTURE.md:185` describes the deterministic rebuild. Searches of reachable history for distinctive original persona, grand-assessment and sector-field strings did not reveal a lost full migration. “Live narrative pipeline” in continuity documentation describes the newer artifact pipeline, not demonstrated original narrative parity.

Pre-existing uncommitted Battlestar changes are limited to `oracle_market_brief.py`, its documentation, and tests: schema export and market-first prompt instructions. They do not restore original evidence or engines. The audit preserves them without endorsing them as the migration solution. Build Week also has pre-existing uncommitted transport, diagnostic, test, documentation and UI work, preserved unchanged.

## 5. End-to-end parity matrix

Statuses describe recovered **original capability**, not whether the newer implementation is useful. `PARITY` may be explicitly limited to a named sub-capability; it never implies overall parity. `INTENTIONALLY CHANGED` includes newer safety/ownership boundaries to retain. Required actions are **review proposals, not work executed or authorized by this audit**.

| Capability | Original Oracle | Battlestar | Build Week | Status | Required Action |
| --- | --- | --- | --- | --- | --- |
| Original engine import | G Oracle/Archivist/Delphi paths in §2 | B `oracle.py:6`, `delphi.py:6`, `_legacy_file.py:22` are placeholders; new native engine | W `_oracle_worker:835` invokes new engine | MISSING | Restore behavioral specification in canonical B; do not treat file adapters as migrated analysis. |
| Historical collection | G `main.py:34`, `backfill_archivist_history.py:121` | Oracle path uses snapshot provider, no historical narrator input | Consumes that snapshot path | MISSING | Inventory/reuse suitable canonical local history later with adjustment/as-of provenance; no fetch in audit. |
| Universe semantics | G `main.py:25` ten sectors + factors/risk | B measurements `:23`, `:321`: eleven sectors + three indexes | Same measurement policy; displays exclusions | PARTIAL | Explicitly map universe differences; do not silently append proxies to rank-based formulas. |
| Above-MA participation | G `breadth.py:14` | B `oracle_measurements.py:607` positive-return fraction | Displays new breadth definition | INTENTIONALLY CHANGED | Preserve both definitions distinctly if original MA participation is restored; no relabeling equivalence. |
| Relative strength / leadership tiers | G `rotation.py:36`, Oracle `:112`, `:166` | Aggregate absolute-move concentration and group ranks | Aggregate commentary, no per-sector tier input | MISSING | Restore source-linked per-sector ranks/tier context where evidence supports it. |
| Actual participation change | G rolling histories/rank changes | B live adapter `prior={}` at `:182` | Calls pipeline without prior | MISSING | Reviewed prior-snapshot lineage and comparison semantics; don't interpret placeholders as change. |
| Fragility / realized volatility | G `fragility.py:18`, `regime.py:29` | Rank-group risk posture; cross-sectional dispersion only | Displays those newer meanings | MISSING | Add supported independent original dimensions; do not call dispersion volatility or rank score fragility. |
| Historical pattern memory | G `pattern_store.py:17`, `:49` | No original pattern store in native narration | No consumer | MISSING | Ground counts/examples with auditable windows; avoid persona coverage claims. |
| Analog sequence matching | G Oracle `:214`, `:251` | Not in native pipeline | Not consumed | MISSING | Port corrected as-of-safe evidence behavior, not leaking historical implementation. |
| Tier/regime outcome evidence | G Oracle `:339`, `:389`, `:471` | Separate newer Delphi rules, not analog outcomes | No old outcome evidence | MISSING | Explicit observed denominators/horizons/coverage contract before interpretation. |
| Sector interplay | G Oracle `_build_oracle_prompt:535` and April 21 prose | Brief catalog lacks this evidence | No browser reconstruction | MISSING | Supply verifiable sector/analog relationships before asking for synthesis. |
| Structured sector field | G `sector_field/*`, appended by `main.py:251` | No recovered original field integration | None | PARTIAL | Historical source exists but original narrative wiring incomplete; validate mathematics and actual required behavior before port. |
| Full sector sphere UI | G `viz/state_space_3d.py:54` prototype, no caller | No corresponding renderer found | Evidence tables, not sphere | UNKNOWN / NEEDS INVESTIGATION | Confirm remembered visual/source if it is a requirement; do not claim cluster bubbles are sector-capital flows. |
| Ensemble evidence collection | G Brigade/Senate → Delphi `parse_terminal_log:73` | Native Oracle runs before Council; no original signal deck | No original deck input | MISSING | Resolve dependency-order issue; avoid Council→Oracle→Council cycle and premature downstream integration. |
| Fleet signal cards | G Delphi `build_signal_cards:202` | Not ported | Fixed scalar fact catalog instead | MISSING | Define canonical evidence adapter for supported legacy behavioral inputs, not terminal scraping. |
| Batch-to-grand synthesis | G Delphi `:279`, `:313`, `:328` | Supplemental brief is one aggregate request | One-shot saved-evidence producer | MISSING | Decide whether batching is necessary; preserve full-population synthesis and coverage, not old token truncation. |
| Narrative-first diagnosis | G Delphi `:328`; saved report `:63` | Native enum summary; dirty brief prompt requests overview | Dirty UI foregrounds accepted prose | PARTIAL | Recover question/argument structure using adequate evidence; don't count UI ordering or prompt intent as completed parity. |
| Cross-signal agreement | G Archivist `:123`, Delphi consensus prompt | Independent fixed posture sentences | Separate paragraphs/facts | PARTIAL | Canonical relationship-level evidence and characterization fixtures. |
| Conflicting signals | G Archivist tension, Oracle divergent analogs, Delphi overrides | Values/warnings available; no original conflict reasoning | Displays saved conflict-free paraphrases | PARTIAL | Test supported tensions without forcing a canned conflict conclusion. |
| Consensus versus confidence | G Delphi `:202`, `:328` | No original cohesion/override evidence in brief | Narrow enrichment has fixed confidence sentence | MISSING | Keep agreement, model confidence and data readiness distinct; restore only supplied consensus context. |
| Uncertainty / insufficiency | G Oracle `:633`, `:685`; Delphi partial-input limits | Explicit blockers/warnings; briefs retain them | Verified warning display and fallbacks | PARTIAL | Retain stronger gates and add relationship/analog-specific insufficiency; failures must not become market diagnoses. |
| Historical/comparative discussion | G analog dates and pattern examples | No original history; live prior absent | Honest unavailable-comparison labels | MISSING | Establish immutable comparison evidence before temporal prose. |
| Sector identities in prose | G named-sector tiers/relationships | Brief restricts ticker commentary and lacks per-sector facts | Exact symbols in evidence views, not synthesis | PARTIAL | Ground identities in typed evidence; review a versioned contract if existing prose restrictions prevent required parity. No validator weakening now. |
| Quantities / dated citations | G raw numeric prose/analog dates, not validated | Brief forbids numbers/dates in prose; facts separately cited | Fact values and links outside prose | INTENTIONALLY CHANGED | Preserve exact citation checking; explicitly review quantitative narrative design instead of silently relaxing guards. |
| Persona / section ordering | G three personas; Delphi diagnosis→argument, Oracle interplay→analogs | Native templates plus new fixed six-section brief | Renders six-section brief / six book pages | INTENTIONALLY CHANGED | Select canonical behavior across original paths; avoid disguising six metric sections as recovered original structure. |
| Model selection ownership | G direct Destroyer with selected/fallback models | Pure brief module, no model IO | ModelDock selects model; provenance recorded | INTENTIONALLY CHANGED | Keep ModelDock ownership; no obsolete direct-model routes. Review provider-specific acceptance separately. |
| Error handling | G error strings as prose, silent fallback, optional retries | Canonical validation APIs | Durable failed attempts, no implicit automatic retry/publication | INTENTIONALLY CHANGED | Keep fail-closed receipts and explicit generation authorization. |
| Parsing / shape | G unstructured Markdown/content extraction | Typed native artifacts and strict brief schema | Structured-output ack, canonical draft validation and receipt validation | INTENTIONALLY CHANGED | Keep strict parsing; narrative-quality review remains an additional gate. |
| Citation grounding | G prompt-requested citations, no validator | Fact catalog/pointers/required IDs | Source hashes and browser fact-value verification | INTENTIONALLY CHANGED | Preserve evidence boundary; valid IDs still do not prove inference/entailment. |
| Persistence / lineage | G latest JSON, logs, batch state, source paths | Deterministic IDs/hashes, manifest/ledger | Immutable mission capture and attempt/publication receipts | INTENTIONALLY CHANGED | Reuse stronger architecture; add missing canonical narrative evidence, not competing storage. |
| Native report delivery | G console/Markdown rendering of saved narrative | B OracleReport already available | W `oracle_adapter.py:865`, `OracleNarrative.tsx:47` consumes it | PARITY (delivery only) | No hidden complete original report waiting for a UI import; preserve consumer pattern. |
| Supplemental prose delivery | G persisted free-text reports | B brief validation/sealing APIs | W producer/reader/UI already connected | PARITY (current contract delivery only) | Replace neither accepted artifact nor mission state during audit; future accepted canonical output should use thin consumption. |
| New Delphi scenario evolution | Not original Delphi fleet synthesis | B `delphi_*` modules/contracts | Not invoked through live Oracle runner/book | INTENTIONALLY CHANGED | Do not confuse it with missing original narration; separate decision if exposing it later. |
| BW fact-selection narrator | No equivalent | Not canonical B implementation | W `contracts/oracle_narrative.py:1688` independent narrow protocol | INTENTIONALLY CHANGED | After canonical acceptance, rationalize/retain compatibility deliberately; avoid another independent Oracle. |
| Source-linked drilldown | G raw JSON/Markdown appendices | Canonical source metadata | W fact links, warnings, provenance and evidence pages | INTENTIONALLY CHANGED | Keep; make narrative lead without hiding material uncertainty. |
| Browser recomputation | No demonstrated original integrated browser Oracle | Canonical Python analysis | W read-only projection, no new market reasoning | PARITY (read-only presentation boundary) | Keep analysis in B and presentation in W. |
| Original recommendations / execution | G sizing posture, directional suggestions, watchlist language | New no-action narrative contracts | Explicit no-trade supplemental presentation | INTENTIONALLY CHANGED | Do not restore trade authority, sizing directives, text-inferred approvals or recommendations. |
| Narrative characterization tests | G smoke/evaluation only | Deterministic/schema/safety tests | Contract/UI/fallback tests | MISSING | Add offline behavioral fixtures after authorization; schema tests alone cannot establish original parity. |
| Proven original source revision | G/GC source hashes + real outputs, no commits | B migration history is available | W current source/accepted receipt available | UNKNOWN / NEEDS INVESTIGATION | Preserve fingerprints; confirm remembered original surface if necessary. Do not invent exact source-to-run provenance. |

## 6. Existing test and documentation coverage

This audit inspected tests; it did **not** execute them or claim new passing results.

- Battlestar: `tests/test_oracle_market_context.py`, `test_oracle_measurements.py`, `test_oracle_snapshot_measurement_adapter.py`, `test_oracle_measurement_diagnostics.py`, `test_oracle_assessment.py`, `test_oracle_narrative.py`, `test_oracle_report.py`, `test_oracle_pipeline.py`, `test_oracle_market_brief.py`; Delphi scenario/history/evolution/report tests and dashboard/input/audit tests. They establish current deterministic behavior, contracts, missing-data semantics and safety—not historical narrative parity.
- Build Week: `tests/test_oracle_market_brief.py`, `test_modeldock_client.py`, `test_narrative_diagnostics.py`, Oracle adapter/workflow/enrichment/contract tests; `ui/src/books/OracleNarrative.test.tsx`, `OracleOverview.test.tsx`, `ui/src/components/OracleMarketBrief.test.tsx`, `ui/src/data/oracleOverview.test.ts`, loader/validator tests. These cover current producers/receipts/rendering, not restoration of original evidence and reasoning.
- Relevant current docs: `B:docs/LEGACY_HARVEST.md`, `ARCHITECTURE.md`, `SYSTEM_OVERVIEW.md`, `CONTINUITY_REPORT.md`, `ORACLE_MARKET_BRIEF.md`; `W:docs/ORACLE_COVERAGE.md`, `ORACLE_MARKET_BRIEF.md`, `ORACLE_NARRATION_INTEGRATION.md`, `LIVE_ANALYSIS_RUN_20260918.md`, `LIVE_PRODUCT_RUNBOOK.md`. Earlier narrow brief integration claims do not constitute this end-to-end audit. Those documents remain untouched.

## 7. Explicit answers required before implementation

### 1. How much of original Oracle currently exists in Battlestar?

There is conceptual overlap—breadth, leadership, risk, rotation, narrative/report artifacts—and substantially stronger typed evidence/safety infrastructure. **None of the three recovered original narrative paths is present end to end.** Their shared vocabulary must not be counted as equivalent formulas or interpretation. A percentage would imply unsupported precision; the capability matrix identifies the actual overlap and gaps.

### 2. What original behavior is missing?

Multi-period participation/relative strength/fragility evidence; historical pattern and as-of-safe analog context; ordered sector relevance and transition/interplay explanations; full-fleet signal-card and batch-to-grand synthesis; consensus-versus-override interpretation; connected agreement/conflict reasoning and a substantial diagnosis-led market argument. Some original inputs and structural prototype wiring were themselves incomplete and need explicit characterization rather than invented restoration.

### 3. What has been replaced with new behavior?

In functional terms, current proxy snapshots and aggregate rank-based measurements occupy the role of historical market context; fixed posture sentences occupy the role of generated interpretation. Battlestar instead added a separate deterministic future-scenario framework under the Delphi name; it is not the original ensemble synthesis. A new six-section qualitative brief and BW-specific fact selector were added later. Current ModelDock ownership, evidence receipts and fail-closed validation provide stronger equivalents to the old direct-model/weak-validation paths—improvements to preserve. This describes the observed architectural difference, not an inferred intention to replace each original module.

### 4. What exists in Battlestar but has not reached Build Week?

The separate native Delphi scenario/history/evolution/report framework is not run or presented by Build Week's live Oracle path. That framework is not the old Delphi narrative. **The audited native Oracle pipeline and current market-brief contract already reach Build Week.** No completed original narrative engine was found sitting unused in Battlestar, so a propagation-only fix cannot deliver parity. Uncommitted B prompt/schema additions exist, but are not proof of a restored engine or newly accepted narrative.

### 5. What exists only in Build Week?

Mission orchestration/capture; the restrictive scalar fact-selection narrative protocol; ModelDock request/diagnostic/attempt and publication machinery for the supplement; browser receipt checks; Captain's Cabin pages, first-page arrangement, evidence drilldowns and provenance labels. The canonical market-brief *contract* lives in B, but its current saved-evidence generation/publishing workflow lives in W. This ownership split needs deliberate consolidation after acceptance, not a third narrative implementation.

### 6. What is required for true original-Oracle narrative parity?

A reviewed behavioral scope spanning the recovered original family; canonical, source-linked evidence for each supported dimension; correction of concrete original grounding/as-of defects; original diagnosis-first synthesis and uncertainty behavior; a versioned narrative contract capable of expressing required grounded information without weakening validators; offline characterization tests; and separately reviewed narrative quality from one subsequently authorized frozen-evidence ModelDock generation. Only then should W consume the accepted canonical implementation. Original direct routes, hallucinations, recommendations and inferred authority are explicitly excluded.

## 8. Review boundary and proposed next-phase map (not implemented)

| Reviewed concern | Historical source → proposed canonical ownership → eventual consumer |
| --- | --- |
| Market context / histories | G `rotation/breadth/fragility/regime`, snapshot helpers → B runtime evidence adapters + typed contracts/advisors, reusing suitable existing data infrastructure → W verified artifacts only. |
| Analog / sector reasoning | G `archivist_oracle/oracle.py` → B deterministic, as-of-safe evidence and supported interpretation; exact new file boundaries require design review → W narrative and evidence renderer. |
| Diagnosis / agreement / disagreement | G narrator and Delphi prompt/synthesis behavior → one maintained B narrative specification/contract/validation path → W displays accepted output verbatim. |
| Ensemble synthesis | G Delphi signal cards → reviewed canonical evidence boundary, only if compatible with current upstream/downstream ordering → no Council integration as part of this audit. |
| Model transport | G direct Destroyer callers → existing ModelDock service boundary, no model selection in Oracle → thin W invocation/integration as agreed after canonical acceptance. |
| Reports and tests | G saved reports as behavior exemplars, not truth goldens → B offline fixtures and characterization tests → W consumption/fallback/source-binding tests. |

Required future characterization cases are the user's seven: broad bullish participation, narrow leadership, defensive/risk-off conditions, conflicting signals, insufficient/inconclusive evidence, missing historical comparison, and meaningful sector dispersion. Tests must establish evidence selection, relationships, scope, uncertainty and citations without prescribing a canned market conclusion. A test may name a bullish fixture without requiring forbidden action language in output. Unsupported historical features must produce explicit absence, not fabricated history.

Two scope distinctions should be reviewed before restoration:

1. Whether the desired original experience includes **both** sector-analog analysis and post-ensemble fleet synthesis. Both are recovered; no single saved screen proves which combination the remembered product presented.
2. Whether the sector-field visualization is part of that restoration. Its prototype exists, but an integrated conserved-sector sphere is not established by the recovered source. It should not be silently built under narrative parity.

### Preservation verification

Read-only before/after SHA-256 comparisons verified all 22 pre-existing changed/untracked Build Week files and all three pre-existing changed Battlestar files unchanged. Both branch names and exact HEADs match the audit baseline. The accepted brief matches the SHA-256 recorded in §4. The only additional working-tree file is this audit document. Document whitespace checks produced no errors. No application tests were run for this documentation-only audit.

No new prompt tweaks, production edits, fixtures, generation, validation relaxation, accepted-brief replacement, market collection, or downstream integration were performed. No commit, push, merge, model call, pipeline run or execution-authority change was performed. **Stop at this audit for review before Phase 4.**
