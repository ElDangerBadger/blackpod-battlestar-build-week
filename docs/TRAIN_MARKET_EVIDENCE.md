# Governed TRAIN-window market evidence

This checkpoint captures and exports explicitly scoped historical market
evidence. It grants no trading, investment, capital-allocation or policy-change
authority. Auto-trading remains OFF. It does not reuse Galactica trading rules,
start inference, submit an order, activate a desk budget or evaluate strategy
returns.

Capture planning, raw transport observations and exported evidence remain
separate. The original hypotheses, data-quality plans, session indices, prices,
qualification policies and earlier deferred reports are preserved. The existing
Decision Journal remains the authoritative linked history; no second decision
database or live-orchestration hook is introduced.

## Inspected starting point

The inspected checkpoint was `1de866b`, after governed Trading Desk evidence
qualification. Its working tree was clean. Relevant source implementations,
retained source metadata and tests were inspected before this additive work.

The real QQQ/SPY history has 760 returned sessions. Both original plans have TRAIN
indices 0–227: first open `2023-10-02T13:30:00Z`, last open
`2024-08-27T13:30:00Z`. Their fixed TRAIN universe implies **456 symbol/session
pairs**. The old quote sample is session 759 inside final holdout 611–759; it
remains inadmissible for TRAIN calibration.

| Existing implementation | Reusable capability | Remaining gap |
| --- | --- | --- |
| Governed history and plan journal | Exact original catalog/hypothesis, returned calendar, dataset, chronological partitions and source bytes. | No versioned bounded market-capture plan and persistent resume protocol. |
| Native quote intake and training calibrator | Strict fields, nanosecond order, receipt/body binding, pagination, opening-minute admission and explicit held-out rejection. | Existing full-dataset intake does not capture segmented TRAIN evidence. A new segmented export is distinct from its input format. |
| v18 qualification | Frozen design, event-aware windows, training-only assumptions, joint sizing/capacity sample and future uncertainty plan. | Actual TRAIN quotes, independent effective-date coverage and reviewed real assumptions remain missing. |
| Decision Journal v1–v18 | Immutable events/evidence, source-prefix replay, exact retries, conflicts and safe interrupted publication. | New capture-plan and export records need additive linkage and replay. |
| Existing read-only helpers | Local literal credential parser and fixed market-data interfaces; historical temporary GET scripts. | Temporary scripts do not establish governed capture/export history or completeness. |

Older calculation files and source pins remain unchanged. Capturing new evidence
does not retroactively change the old v16/v17/v18 outcomes.

## Plan and request boundaries

The plan binds an exact original base-plan event, dataset, frozen hypothesis and
selected original fold IDs. Its default covers every returned TRAIN session.
For each session it declares exactly the original regular open through open plus
60 seconds. Returned calendar times govern the windows; weekends, holidays and
daylight-saving changes are not inferred from a weekday shortcut.

Only the fixed market-data GET endpoint
`https://data.alpaca.markets/v2/stocks/quotes` is admitted. Queries explicitly use
the frozen symbol universe, `feed=iex`, `currency=USD`, ascending order,
`asof=-` and limit 10,000. Pagination follows the exact prior native token and
retains the original query. Alpaca sorts by symbol then quote time and applies
the page limit across all symbols, so a populated first page alone does not
establish the other symbol's coverage. See the
[official historical quote interface](https://docs.alpaca.markets/us/reference/stockquotes-1).

Each request is an opening-minute segment rather than a continuous ten-month
query. VALIDATION, TEST and final-holdout windows are excluded by the original
partition identities. There is no feed downgrade, symbol remapping, subscription
purchase or implicit extension of the requested time range.

The declared default bounds are:

| Boundary | Default |
| --- | ---: |
| Quote page limit across symbols | 10,000 rows |
| Pages per segment | 128 |
| Native rows per segment | 200,000 |
| Bytes per response | 8 MiB |
| Retained bytes per segment | 64 MiB |
| Retained capture bytes | 512 MiB |
| Lifetime requests | 4,096 |
| Requests per explicit invocation | 32 |
| Minimum request interval | 1 second |
| Request timeout | 20 seconds |

These are finite capture limits, not a promise that every segment will finish
within them. A bounded invocation can stop with partial evidence and resume
explicitly later. An exhausted bound does not justify discarding raw observations
or claiming completeness.

## Credentials and actual entitlement

The previously authorized local credential source is
`/Users/nikolai/buried_treasure/api_keys.yaml`, using the literal `alpaca.key_id`
and `alpaca.secret_key` pair. Inspection before implementation checked the file's
existence and regular-file metadata without reading or displaying its contents.
Credentials are read only for an explicitly requested capture, held in memory
and never placed in journal evidence, URLs, raw response metadata, CLI reports,
Git or browser state. No account/order endpoint is used.

Past IEX success and SIP rejection establish access only at those past capture
times. Current authentication and entitlement are unknown until the bounded GET
returns an actual status. Alpaca's published Basic market-data plan describes
IEX real-time coverage, historical data since 2016 and 200 historical requests
per minute; those general product limits do not attest this particular key's
present privileges. See the
[official market-data subscription documentation](https://docs.alpaca.markets/us/docs/about-market-data-api).

Authentication failures, forbidden access, rate limits, unavailable endpoints,
timeouts and interrupted attempts are explicit observations. They cannot become
an empty successful quote page, a retried request outside its limits or a
substitute feed. Raw provider error bodies and authentication headers are not
retained or printed.

## Raw observations, resumption and export

The plan freezes scope and limits before the first provider request. Persistent
snapshots retain attempt identities, raw successful response leaves, exact
receipt metadata, status and progress. Interrupted or failed processing remains
auditable; retries cannot reset the lifetime request count or silently widen
scope. Successful HTTP 200 bodies are retained byte-for-byte. Later export
reconstructs their meaning rather than rewriting the source body.

The pure exporter checks the entire forward token/query chain, capture clocks,
declared scope, source hashes and native quote fields. Each segment reports its
planned session/symbol pairs and retained observations. The aggregate reports
all planned pairs, completed/partial/unavailable segments, coverage gaps and
unprocessed work.

Pagination completeness and quote coverage are different facts. A terminal
HTTP 200 response with no quotes is a completed retrieval with missing evidence,
not coverage. A subset of successfully captured sessions does not establish all
456 real TRAIN pairs. IEX sampling does not establish consolidated liquidity,
opening-auction depth, future fills, realized fees/slippage or historical
publication-time availability.

The new segmented profile is a separately versioned input design. This
checkpoint makes no claim that it can be passed unchanged to the old v18
calibrator. Any later adapter must explicitly bind its exact source/session
identity, prove coverage and preserve the frozen qualification boundaries.

The exact contracts are `blackpod.train_market_capture_plan.v1`,
`blackpod.train_market_capture_snapshot.v1`,
`blackpod.train_market_segment_export_request.v1` and
`blackpod.train_market_export_request.v1`, implemented in
`contracts/train_market_evidence.py`. The pure segment/export implementation is
`train_market_export.py`; planning and journal linkage are
`train_market_evidence.py` and `train_market_evidence_journal.py`. The explicit
network boundary and immutable local checkpoints are `train_market_capture.py`.

`CAPTURE_COMPLETE` describes all planned terminal-success retrieval chains.
`coverage_complete` separately requires admitted quotes for every planned
symbol/session pair. Aggregate requests retain the exact capture snapshot and
attempt checkpoints; compact segment summaries link earlier raw segment events,
avoiding a single event containing the entire permitted raw corpus. Neither
status is an investment/trading recommendation or research support finding.

## Independent effective-date coverage remains separate

Quotes cannot prove corporate-action completeness. The existing independent
`ContinuityCoverageReview` may be imported only with exact scope and separately
retained support. Missing review defaults to unresolved; no quote count, empty
action response or provider success manufactures an independent reviewer,
complete effective-date history or authenticated approval.

Alpaca's action API filters by process date and describes delays in receiving
and publishing actions. Its data-quality filter also affects unprocessed
incomplete records. Even complete pagination does not establish when every
action was announced or independently prove all relevant effective dates.
See the [official corporate-action interface](https://docs.alpaca.markets/us/reference/corporateactions-1).

Fee/slippage assumptions, risk review, economic metric applicability and source
authentication remain separate requirements. Capture/export leaves all
economic-support and execution-authority flags false.

## Shared journal and immutable lifecycle

Additive journal v19 records the capture plan, segment exports and aggregate
export under the original research identity. Exact source evidence and explicit
method versions make export replay independent of the original credential file
and provider availability. It never rewrites a hypothesis, earlier capture,
qualification policy or outcome.

An exact retry is a no-op; changed bytes under the same identity conflict.
Further capture/export progress uses new linked records. Verification replays
the already retained inputs and original historical prefix. Future qualification
or evaluation must refer to these exact records and append a separate result.
An export has no authority to upgrade the earlier research classification.

## Controlled examples and real-data reporting

The offline example preserves the original fourteen-event synthetic fixture.
Its authored transport returns unchanged quote rows from the original TRAIN
subset in twelve one-minute segments: 12 sessions and 24 symbol/session pairs.
No provider is contacted. Those bodies and receipt declarations are explicitly
synthetic, not fresh real captures or historical point-in-time attestations.

Examples distinguish completed pair coverage, a partially processed capture and
a terminal empty HTTP 200 page with a coverage gap. Partial and empty retrievals
must remain visible in the manifest and linked exports. Tests also exercise
scope/token rejection, network guards, interrupted processing, safe writes and
retained-only recovery without original inputs.

Any separately authorized actual capture is reported with its actual frozen
plan, source paths, UTC capture timestamps, request/page/body counts, native
statuses and remaining pairs. Its raw local evidence stays separate from
committed code and from synthetic fixtures. No completeness, economic readiness
or authenticated independent coverage is claimed merely because offline tests
pass or an HTTP request succeeds.

## Runnable offline commands

Run from this checkout. The first command uses the injected authored callback;
it reads no credential file and makes no provider request. It creates three
separate journals, preserving the same fourteen original source events in each.
Its manifest lists exact plan/export IDs, counts, gaps and verification hashes.

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests .venv/bin/python3.11 \
  -m blackpod_build_week.train_market_evidence_example \
  --output-root output/train-market-evidence-example

PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests .venv/bin/python3.11 \
  -m blackpod_build_week.train_market_evidence_cli verify \
  --journal-root output/train-market-evidence-example/full/journal

PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests .venv/bin/python3.11 \
  -m blackpod_build_week.train_market_evidence_cli verify \
  --journal-root output/train-market-evidence-example/partial/journal

PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests .venv/bin/python3.11 \
  -m blackpod_build_week.train_market_evidence_cli verify \
  --journal-root output/train-market-evidence-example/terminal-empty/journal

PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests .venv/bin/python3.11 \
  -m blackpod_build_week.train_market_evidence_cli export \
  --snapshot output/train-market-evidence-example/full/input/snapshot.v1.json \
  --evidence-root output/train-market-evidence-example/full/capture \
  --plan-event-id journal-event-2b87f3cc309d38b81b9c6e277048ef102269e39fea8d9bdf539766384b106cf8 \
  --journal-root output/train-market-evidence-example/full/journal \
  --export-id synthetic-train-market-full-export \
  --output output/train-market-evidence-example/full/reports/cli-export-retry.v1.json
```

The full fixture covers 24/24 pairs with twelve pages. The partial fixture covers
4/24 pairs and preserves ten unprocessed sessions. The empty-page fixture
completes all twelve retrieval chains but covers 22/24 pairs. Neither partial
fold produces an imputed training profile. All three retain unresolved
independent action coverage and absent cost assumptions.

An identical example invocation reads verified existing captures and writes no
new events. It deliberately does **not** resume its partial case; only an
explicit capture invocation advances that operational progress.
The final command above retries the same full export identity and writes no new
segment or aggregate event; its report is an immutable export outside the journal.

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests .venv/bin/python3.11 \
  -m unittest test_train_market_evidence_example -q
```

## Explicit provider workflow

`prepare` selects a verified original base-plan event, capture identity,
creation time, optional original folds and optionally stricter limits. It writes
an immutable plan export without accessing a provider. `register` appends the
plan before any request.

The single network-capable command is `capture`. It requires an exact registered
plan ID, separate capture root, explicit local credential source/format and
`--allow-market-data-get`. Its optional invocation request budget cannot exceed
the frozen lifetime/invocation limits. The fixed market-data endpoint provides
no broker, order, account, rebalance or subscription operation.

`snapshot` verifies retained operational progress and exports an exact declared
snapshot clock without contacting a provider. `export` replays a snapshot and
raw leaves from the explicit evidence root, records its segment group and
compact aggregate, and writes an immutable report. It optionally accepts a
separate independently supported coverage-review artifact; it never invents one.

After additional explicitly requested capture, use a new snapshot file and a
new export ID. Earlier partial exports remain immutable. Exact old export
retries retain their original snapshot and segment clocks; a changed snapshot
under the same export ID conflicts. `show --event-id` and `verify` are read-only
and select exact retained identities.

Inputs, raw operational capture, journal entries and reports use separate roots.
Success returns JSON and exit 0; invalid scope, evidence, clocks, identity,
publication or authentication input returns exit 2. Native unavailable/partial
evidence is explicitly reported rather than silently upgraded. The checkpoint
validation report records actual commands and results for any real pilot.

## Readiness and next milestone

This checkpoint can retain and export bounded TRAIN evidence under explicit
scope and lifetime limits. It does not itself complete the real dataset's
qualification or implement the proposed uncertainty/stability calculation.

The next milestone is to finish the governed capture within its frozen bounds,
retain independently justified action-coverage and cost/capacity assumptions,
then explicitly adapt the segmented export into a newly governed qualification
design. That integration must preserve all original partitions, joint sample
counts, inactive budgets and append-only history. Auto-trading stays OFF.
