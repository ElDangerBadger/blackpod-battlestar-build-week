# BlackPod Battlestar — Captain's Cabin

A live, read-only product for following canonical mission evidence through the
Captain's Cabin and Battlestar Navigator V3. The repository directory and Python
package retain their historical Build Week names; the demo specification is
retired as the governing product scope.

[Product specification](docs/PRODUCT_SPEC.md) ·
[Live startup and operations](docs/LIVE_PRODUCT_RUNBOOK.md) ·
[Safety boundary](docs/SAFETY_BOUNDARY.md)

## Start the product

From this repository, install dependencies once:

```bash
make setup
npm --prefix ui ci
```

Point the reader at one existing canonical LIVE mission:

```bash
make cabin-live \
  CABIN_ARTIFACTS_ROOT=/absolute/path/to/artifacts \
  CABIN_MISSION_ID=your-existing-live-mission-id
```

Open [http://127.0.0.1:5174/](http://127.0.0.1:5174/). The configured source is
`<CABIN_ARTIFACTS_ROOT>/missions/<CABIN_MISSION_ID>/`; select the artifact root,
not the mission directory. Stop the process with **Ctrl+C**.

The [prospective reversal experiment](docs/PROSPECTIVE_SHADOW_EXPERIMENT.md)
also has a small read-only view at `/?view=research`. Start the reader with
`SHADOW_EXPERIMENT_ROOT=/absolute/path/to/the/experiment/journal`; no mission
configuration is required for that view. It shows saved predictions and linked
gross price outcomes, with auto-trading OFF and net performance unqualified.
The [historical reversal baseline](docs/REVERSAL_HISTORICAL_BASELINE.md) provides
a separate retained-data comparison and 30-session historical context. It
does not add retrospective rows to the prospective experiment.

The [standalone BlackPod research app](docs/BLACKPOD_STANDALONE_RESEARCH.md)
keeps these dashboards and the frozen nightly collector running independently
of Codex. Double-click `~/Applications/BlackPod.app`; keep the Mac awake and
logged in. The user LaunchAgent owns the 6:30 p.m. Los Angeles collection;
the old Codex collector is paused and auto-trading stays OFF.

`make cabin-live` builds the UI and starts a loopback-only artifact reader. It
does **not** start a mission, record approval, acquire market data, call
ModelDock, or prepare a demo. With no source configured, it opens an honest
setup state instead of showing old demo evidence. Do not run `make live-mission`
merely to launch the Cabin: that historical orchestration
shortcut includes an explicit `APPROVE_HANDOFF` operation.

No `BATTLESTAR_PATH` or ModelDock service is needed to display an existing
mission. Battlestar remains the canonical owner of its domain logic and
Navigator renderer. Neither sibling repository is modified by the reader.

When separately authorized, narrative producers call **ModelDock**, not a
specific model. ModelDock owns model selection; `MODELDOCK_MODEL` is ignored
for new LIVE calls. Returned model identity is recorded provenance only.

## What “live” means here

The Cabin checks the explicitly selected mission every five seconds and
follows verified revisions automatically. It displays incomplete, running,
held, vetoed, failed, and approved states without requiring an approved-demo
package. There is no automatic selection of a different “latest” mission.

Reader connectivity, last verification, and the age of recorded mission
evidence are separate facts. A reachable reader does not make an old mission
current. Captured chart/portfolio timestamps and recorded ModelDock
provenance remain historical evidence, not assertions of a live quote feed or
present service health.

Unavailable or invalid source data never falls back to replay. Previously
verified evidence may remain visible with an explicit degraded/offline
warning; it is not relabeled as current. See the [runbook](docs/LIVE_PRODUCT_RUNBOOK.md)
for source configuration, development, and recovery.

## Scope and next steps

- Preserve the Cabin books, Mission Chart SVG overview, expanded Navigator V3,
  existing mission contracts, and SHADOW-only safety.
- Read and explain mission artifacts; do not start/resume missions, record
  operator approval, or change canonical evidence.
- Keep deterministic replay for explicit developer/historical review, outside
  normal product use.
- Cabin-managed add-symbol and trading workflows remain roadmap work. The
  read-only product does not start the separate execution controller.

Separate explicit development interfaces now support a passive Decision
Journal, governed investment research, and a guarded Galactica/Alpaca trading
toggle. The Cabin and mission orchestration remain read-only/SHADOW. See
[Investment governance](docs/INVESTMENT_GOVERNANCE.md) and
[Auto-trading controls](docs/AUTO_TRADING.md). Auto-trading defaults OFF;
investment research approval cannot enable it. No capital policy is activated.
The [paper reconciliation and ownership interfaces](docs/TRADING_RECONCILIATION.md)
retain broker facts and restore unresolved-attempt barriers; funded activation
is blocked pending a separately governed path.

[Offline fill-lot and fee accounting](docs/TRADING_ACCOUNTING.md) links
individual execution activities to verified paper history, applies long-only
FIFO and retains later fee observations without rewriting prior results.
Unknown fees leave net P&L unknown. Accounting commands never enable trading.

The mission symbol is correlation metadata. The existing Oracle analyzes its
supported fleet; a Navigator reference chart does not turn that into
single-symbol Oracle evidence.

## Development and checks

```bash
# Terminal 1: selected artifact reader; uses an existing UI build if present
make cabin-reader \
  CABIN_ARTIFACTS_ROOT=/absolute/path/to/artifacts \
  CABIN_MISSION_ID=your-existing-live-mission-id

# Terminal 2: Vite, with /live proxied to the local reader
make cabin-dev
```

Open the URL printed by Vite. Normal development and production builds do not
run the judge workflow or bundle prepared demo evidence.

```bash
make test
make cabin-test
make cabin-build
make navigator-check-upstream BATTLESTAR_PATH=/path/to/read-only/battlestar
```

For explicit offline replay review, run:

```bash
make cabin-dev-replay BATTLESTAR_PATH=/path/to/read-only/battlestar
```

Open `?mode=replay` on the Vite URL.
The old `?mode=demo` query remains a compatibility alias, not the default.
Replay fixtures and legacy packaging commands remain available for regression
testing; they do not govern live-product acceptance. Browser setup and checks:
[Captain's Cabin](docs/CAPTAINS_CABIN.md).

## Documentation

- [Passive Decision Journal and two-desk foundation](docs/DECISION_JOURNAL.md)
- [Source-bound investment hypotheses in shadow mode](docs/INVESTMENT_HYPOTHESES.md)
- [Shadow hypothesis challenge and outcome evaluation](docs/INVESTMENT_REVIEW.md)
- [Research validation and evidence gate](docs/RESEARCH_ACCEPTANCE.md)
- [Governed Trading Desk real-evidence qualification](docs/TRADING_EVIDENCE_QUALIFICATION.md)
- [Governed TRAIN-window market-evidence capture/export](docs/TRAIN_MARKET_EVIDENCE.md)
- [Versioned segmented TRAIN-evidence qualification](docs/SEGMENTED_EVIDENCE_QUALIFICATION.md)
- [Product specification and roadmap](docs/PRODUCT_SPEC.md)
- [Live product runbook](docs/LIVE_PRODUCT_RUNBOOK.md)
- [Architecture](docs/ARCHITECTURE.md)
- [Captain's Cabin presentation and verification](docs/CAPTAINS_CABIN.md)
- [Navigator V3 source mapping and update checks](docs/NAVIGATOR_V3_INTEGRATION.md)
- [Sentry Research: frozen 20/60 comparison and closeout evidence](docs/SENTRY_RESEARCH_CABIN.md)
- [Sentry scan results: isolated failures and recorded snapshot review](docs/SENTRY_SCAN_CABIN.md)
- [Supplemental Oracle market brief: source-linked ModelDock commentary](docs/ORACLE_MARKET_BRIEF.md)
- [Change history](docs/BUILD_WEEK_CHANGELOG.md)

Historical material is retained, not the current startup path:
[Build Week implementation history](docs/BUILD_WEEK_HISTORY.md),
[archived Demo Runbook](docs/DEMO_RUNBOOK.md), and
[archived LIVE Demo Runbook](docs/LIVE_DEMO_RUNBOOK.md).

## Shadow two-desk candidate review

The [shadow desk review](docs/SHADOW_DESK_REVIEW.md) reuses pinned native Oracle,
candidate and Senate calculations, connects Galactica Spyglass to retained
daily bars, and preserves explicitly supplied historical Brigade opinions and
dissent. It records source-bound research rankings, proposed desk ownership and
whole-share PAPER test sizes in journal v8. Fresh Brigade inference and
predictive forecasts remain an explicit gap.

The fixed 25%-of-captured-equity testing budget is split equally between the
desks and stays inactive. Review parameters are proposed research policy;
ownership and sizes are not installed. Auto-trading remains **OFF**. The
offline example and assess/record/show/render commands never start a mission,
call ModelDock, activate capital, submit an order or change existing trading
rules. The linked design includes the complete module inventory and separates
connected analytical paths from optional presentation, research and execution
interfaces.

## Governed forecasts and Brigade shadow analysis

The additive [forecast and Brigade interface](docs/FORECAST_BRIGADE_SHADOW.md)
retains explicit forecast units, horizons, source/model provenance and data
cutoffs before admitting advisory analysis. Legacy `LIVE` filenames and labels
do not establish currentness. Different horizons at the same as-of instant
remain different targets; they do not become historical trend observations.

The separate journal path preserves admitted and deferred evidence, strict
Brigade opinion validation and disabled authority. It leaves canonical mission
stages, existing ModelDock routing/configuration and the independent execution
controller unchanged. Auto-trading remains **OFF**; daily forecasts cannot
authorize a long-horizon investment or activate the inactive desk budgets.

## Governed current forecast export

The separately invoked [forecast producer export](docs/GOVERNED_FORECAST_EXPORT.md)
connects newly fitted native daily price forecasts to the existing intake and
Brigade SHADOW review. It retains completed-session evidence, actual training
rows and target-label availability, original quantile identities and data-only
model provenance. Crossed quantiles, incomplete bars and stale inputs remain
explicit barriers. It uses the existing fitting runtime without changing
Galactica caches, dependency declarations or ModelDock routing.

Fresh fitting and optional local text inference are explicit producer actions.
Verified journal replay performs neither. All research authority remains
disabled, auto-trading stays **OFF**, and the fixed two-desk budgets remain
inactive. Forecast eligibility is advisory evidence, not approval to trade.

## Structured Brigade shadow responses

The [versioned structured response interface](docs/BRIGADE_STRUCTURED_RESPONSES.md)
adds exact typed member responses, deterministic native-parser projections and
passive journal v11 records. Original raw JSON, native prompts, parser output
and dissent remain retained separately. Malformed or mismatched responses defer
without repair, fallback votes or automatic retries. Existing v1/v9 records
continue to replay through their original versions.

Runnable synthetic examples exercise the new interface without provider calls.
Explicit current local captures retain the existing ModelDock boundary and
appliance-owned routing. All opinions remain SHADOW recommendations; auto-trading
stays **OFF**, desk budgets remain inactive, and no execution authority is added.

## Trading strategy rebuild direction

The [trading rebuild roadmap](docs/ARCHITECTURE.md#trading-strategy-rebuild-roadmap--october-12-2026)
records the decision to replace Galactica's trading logic with independently
specified and evaluated day/swing strategies. Existing native trading rules,
prompts, sizing and forecast defaults receive no automatic production reuse.
The journal, accounting, evidence and verified operational safeguards remain
useful infrastructure. The next trading work establishes a new research
contract and offline evaluation foundation before replacement shadow analysis
and separately authorized paper testing. Auto-trading remains **OFF**; this
roadmap changes no current execution behavior or investment-desk policy.

## Independent trading research and offline evaluation

The new [TRADING research foundation](docs/TRADING_RESEARCH.md) establishes a
versioned, strategy-neutral contract and deterministic offline evaluation of
explicitly supplied candidate decisions. It reuses retained evidence and the
passive journal, while excluding Galactica's trading rules, Brigade voting
criteria, forecast defaults, Navigator mandates, stops and sizing heuristics.
Chronological availability, simulation costs, cash/position accounting and
trial provenance remain explicit. Synthetic examples use authored decisions
and standalone simulated cash, without a broker, provider or strategy engine.

Simulation results cannot promote a strategy, activate desk budgets or acquire
execution authority. Auto-trading remains **OFF**. Brigade evidence-consistency
review is a separate optional diagnostic for the retained advisory channel;
it is neither a prerequisite for this new foundation nor a replacement for
economic evaluation of newly specified trading strategies.

## Independent hypotheses and governed historical intake

[Historical research intake](docs/TRADING_HISTORICAL_RESEARCH.md) now freezes
two original, untested daily hypotheses and projects retained Alpaca bars and
returned calendar sessions through strict source-bound contracts. Journal v13
retains the catalog and intake; v14 links data-quality-only research plans and
evaluations to both originals. Historical availability remains a declared
retrospective assumption. No strategy decisions, scores, winners or paper
orders are produced. Auto-trading stays **OFF**. See the
[validation report](docs/TRADING_HISTORICAL_RESEARCH_VALIDATION.md) for exact
commands, actual tests and real-history versus fixture coverage.

## Deterministic shadow intent research

[Governed shadow research](docs/TRADING_SHADOW_RESEARCH.md) implements the two
frozen hypotheses, whole-share sizing from known completed closes, and an
equal-weight counterfactual control matched to admitted entry notional and
holding duration. Strict continuity and cost evidence gates precede production.
Missing reviews defer the study; failed controls remain inconclusive. Journal
v15 freezes each declaration and links reproducible evaluations at 1×, 2× and
4× costs. Final-holdout scoring and every execution authority remain disabled.
Auto-trading stays **OFF**. See the
[validation report](docs/TRADING_SHADOW_RESEARCH_VALIDATION.md) for changed
files, commands, actual tests and fixture-versus-retained-history results.

## Real-data evidence and explicit shadow risk review

[Governed evidence adapters](docs/TRADING_SHADOW_EVIDENCE.md) now retain and
verify native corporate actions, paginated historical quotes and separate cost
assumptions. Study v2 and journal v16 bind those inputs to an explicit simulation
sizing/risk review. A proposal stays deferred; a shadow approval can change
temporary simulation risk only. Original plans and the previous calculation
versions remain immutable. Auto-trading stays **OFF**. See the
[validation report](docs/TRADING_SHADOW_EVIDENCE_VALIDATION.md) for actual
captures, test results, unchanged journals and unresolved evidence.

## Native evidence-closure review

[Governed native closure review](docs/NATIVE_EVIDENCE_CLOSURE.md) now replays exact
native shadow qualifications and retains descriptive source findings, immutable
candidate comparisons and reproducible quote-extrema witnesses in journal v21.
Supplemental checklists, reviewer labels and source URLs cannot replace native
continuity, cost/capacity, risk or uncertainty prerequisites. Wide spreads remain
unclipped; a ready shadow study design establishes no economic or execution
authority. Auto-trading stays **OFF**. See the
[validation record](docs/NATIVE_EVIDENCE_CLOSURE_VALIDATION.md) for exact commands,
fixture and retained-real coverage, results and remaining native prerequisites.

[Independent effective-date and historical applicability reconciliation](docs/INDEPENDENT_EVIDENCE_RECONCILIATION.md)
adds a passive v22 report for retained independent action inventories, feed/size
scope, fee documentation and account/mode applicability. Matching declarations
cannot replace native gates or populate cost parameters. Auto-trading remains
**OFF**. Actual test and evidence results are recorded in the
[validation report](docs/INDEPENDENT_EVIDENCE_RECONCILIATION_VALIDATION.md).

[Governed reconciled action intake](docs/RECONCILED_ACTION_INTAKE.md) freezes
provider and issuer evidence under a new shadow policy and retains a separate
candidate overlay. Original native masks and policies remain unchanged; the
overlay grants no execution authority. Auto-trading remains **OFF**. See its
[validation record](docs/RECONCILED_ACTION_INTAKE_VALIDATION.md).

[Reconciled overlay shadow qualification](docs/RECONCILED_SHADOW_QUALIFICATION.md)
adds versioned window witnesses and restrictive vetoes while retaining every
original native gate. Current effective study eligibility remains false and
auto-trading stays **OFF**. Actual checks are recorded in its
[validation record](docs/RECONCILED_SHADOW_QUALIFICATION_VALIDATION.md).

The [research consolidation inventory](docs/RESEARCH_ACCEPTANCE.md) distinguishes
existing desk research from empirical validation. Read-only acceptance-state
and baseline exports preserve original journal records, separate eligibility
from outcomes, retain domain/horizon differences and report unavailable metrics
explicitly. Oracle's existing supplement validator adds bounded semantic
contradiction checks without claiming general entailment. The
[completion report](docs/RESEARCH_ACCEPTANCE_VALIDATION.md) records actual tests,
retained-data coverage and prospective-readiness blockers. Auto-trading remains
**OFF**; no research publication activates capital or execution.
