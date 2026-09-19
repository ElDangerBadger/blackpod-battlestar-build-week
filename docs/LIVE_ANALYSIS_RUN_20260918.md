# September 18 fresh, no-trade analysis

One user-authorized LIVE run is now the selected local Cabin source. Subsequent
analysis remains operator-triggered. There is no recurring analysis schedule,
browser run/approval control, downstream Sentry handoff, or trading authority.

## Evidence and outcome

Local ignored artifact root: `artifacts/live-analysis-20260918-001`.
Mission: `mission-live-aapl-20260918-001`.
Request: `request-live-aapl-20260918-001`.

The existing canonical runners were sufficient; no production code or contracts
were changed for this activation. Sources at execution:

- Build Week: `5f1f63831bbf06b9310c6ec972b10b5c65b79c6b`.
- Battlestar: `b2d79331521d57dbcdcdc1ccf8cb27f5bb9dca09`.
- Working branches: `update/2026-09-18-live-analysis` in both repositories.

| Component | New recorded result | Limits |
| --- | --- | --- |
| Oracle | SUCCEEDED / READY; market as-of September 18, 19:05:11 UTC | 21 acquired, 14 measured; no prior comparison |
| Council | SUCCEEDED / BLOCKED; lineage observed 19:05:19 UTC | No-trade mandate, not technical failure |
| Governor | SUCCEEDED / BLOCKED; lineage observed 19:06:29 UTC | Allowed next step NONE; no operator approval |
| Sentry | 18 observed through completed September 17 daily session | Independent RESEARCH_ONLY scan; three input failures |
| ModelDock brief | One request; rejected malformed JSON | No accepted brief, no automatic retry |

Mission outcome is `HELD`, revision 7, terminal phase `GOVERNOR`. Operator route
is `CLOSED_BLOCKED`, action `NOT_STARTED`; operational Navigator is `NOT_STARTED`
with no handoff or SHADOW plan. Supplemental market charts are not operational
Navigator execution. Portfolio context remains unconfigured.

Oracle's native headline is “Contracting breadth with risk-on structure.” This
is the canonical market ETF fleet analysis, not AAPL-specific analysis merely
because AAPL is the request's correlation symbol. The current policy measures
the 11 sector ETFs plus SPY, QQQ, and DIA. VXZ, IWF, IWD, IWM, MTUM, USMV, and
QUAL remain outside those measurements. Missing prior measurements still limit
rotation/change comparisons. See [Oracle coverage](ORACLE_COVERAGE.md).

Council/Governor native `generated_at` reflects the supplied input/context time
19:03:52 UTC, not stage completion. The mission lineage records actual execution
times. All 41 mission artifact pins and 39 Council/Governor lineage pins verified.

## Operator-triggered production path

This run used explicit inputs under the artifact root's `inputs/` directory:
`mission_request.json`, `council_policy.json`, and
`governor_context_validated.json`. The mandate denies authority with `ok: false`,
`allowed_sides: []`, `max_trades: 0`, and `risk_posture: READ_ONLY`.

The first Governor context was rejected before that stage started because its
accountability prose contained forbidden action vocabulary. The original input
is preserved. Only the accountability note was corrected to describe missing
prior observations; the mandate and validators were unchanged. Existing
`mission-resume` then ran the not-started Governor stage without rerunning the
succeeded Oracle/Council stages.

For another authorized run, create new root/request/mission IDs and fresh,
validated policy/context inputs; do not overwrite this run or blindly reuse its
timestamps. The command shape is:

```sh
PYTHONDONTWRITEBYTECODE=1 \
BATTLESTAR_PATH=/absolute/path/to/blackpod_battlestar \
.venv/bin/python3.11 -B -m blackpod_build_week.harbormaster mission-run \
  --request /new/artifact-root/inputs/mission_request.json \
  --artifacts-root /new/artifact-root \
  --without-modeldock --through GOVERNOR \
  --council-policy-input /new/artifact-root/inputs/council_policy.json \
  --governor-context-input /new/artifact-root/inputs/governor_context.json \
  --deadline-seconds 240 --strict-battlestar-clean
```

`--without-modeldock` separates deterministic analysis from the optional rich
brief. The mission ModelDock stage correctly remains `NOT_RECORDED`; a separate
brief is not retroactively labeled as that stage. After a succeeded Oracle
stage, an independently authorized one-shot brief uses
[the existing brief command](ORACLE_MARKET_BRIEF.md). ModelDock owns all routing;
the request omits model/provider selection. Do not use `make live-mission` here:
that historical workflow records an operator handoff approval.

### Actual ModelDock result

The one call ran from 19:07:06 to 19:09:56 UTC. ModelDock returned an OK transport
envelope, but its narrative content could not be parsed as JSON:
`response_malformed_json`. The request contained no model/provider/model-ID
selection. Returned appliance identity is audit metadata only, not a routing
instruction. This is not evidence of capacity exhaustion or a client-selected
model failure.

No brief was published. Native Oracle prose remains available on page 1; page 4
correctly has no accepted ModelDock narrative. The immutable attempt and
sanitized diagnostic receipt are preserved under
`missions/mission-live-aapl-20260918-001/presentation/oracle_market_brief_attempt/`.
Do not delete the reservation or retry automatically. A separately authorized
investigation/attempt is needed to validate the richer writing path.

## Independent Sentry scan

Open **Sentry → Scan results**. The default **Microcap** tab still shows its
explicitly historical July 15 research archive; **Sentry Research** retains the
frozen V2 study. Neither is replaced or relabeled as this new scan.

Scan ID:
`sentry-operational-scan-6061865e4c1026642490389e8e2fcd37a6d7e94c9cd05501feb2138f9416d3ce`.
As-of: September 18, 19:05:07 UTC. Latest completed session: September 17;
September 18's session was still open at acquisition.

- 22 requested overall; VXZ excluded before acquisition as an ETN outside the
  frozen Equity/ETF reference membership. This is recorded in `sentry/request.json`.
- 21 scanner members; 18 observed; IWM, QQQ, and SPY excluded for historical
  **volume conflicts**, not replaced with synthesized observations.
- 16 incremental provider requests at two-second pacing; four already-current
  audited captures reused; IWM's known conflict retained without another request.
- MTUM/QUAL/USMV used the existing audited OHLCV-only reconciliation for
  adjusted-close-only revisions. Raw OHLCV conflicts remain disqualifying.
- Frozen 20/60 windows, .95 minimum percentile, total capacity six, and per-profile
  capacities four were unchanged. **Both selections are empty, six slots unused.**
  No qualifying names means no padding or lower threshold to fill the list.
- All 18 observed histories contain the last 66 scheduled sessions; canonical
  scan replay is byte-identical and the Build Week reader reports READY.

Sentry uses the canonical unadjusted OHLCV path. Navigator's auto-adjusted bars
are not silently substituted into this calibration. Historical metadata and
provider authenticity limitations remain. Equity and ETF are `RESEARCH_ONLY`;
this is not prospective evidence, a production universe publication, or an
Oracle/Council input. Supporting receipts are under `sentry/`, including
`execution.json`, `scan-manifest.json`, `scan.json`, and `verification.json`.

## Navigator and evidence timing

The new mission has its own original AAPL context and interval/MA catalog plus
the observed-fleet capture catalog. Saved captures carry real new capture times
and producer revision/fingerprint; September 15 bytes were not relabeled.
All 330 saved datasets across 22 symbols validated: original AAPL at 19:07:00
UTC, 14 additional AAPL variants at 19:07:32 UTC, and 315 fleet variants completed
at 19:16:19 UTC. There were 66 provider responses and 264 memory-cache responses,
with no acquisition failures. The complete publication has 387 verified files
and ID `549bf0c2f7e0921b6ab513d690fec9fbdde2b19e83ce1d34533407ecb4b5c30f`.
Saved provider observations may include a forming daily/weekly bar and are not
assertions that that session is complete.

**Current reference** is separate: the existing completed-bar worker and its
calendar freshness checks continue unchanged. **Live market data** is separate
Alpaca transient price context. Neither refreshes Oracle/Council/Governor or
changes the canonical mission outcome. A captured VXZ hourly observation does
not resolve a missing completed-bar Current-reference interval: its latest label
remains 15:30 UTC versus 18:30 UTC for other saved hourly series. A provider
`stale: false` flag describes fetch freshness, not complete or timely coverage.

## Start the selected Cabin without executing analysis

From the Build Week repository, with `ui/dist` already built:

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src \
.venv/bin/python3.11 -B -m blackpod_build_week.cabin_reader \
  --ui-root ui/dist --port 5174 \
  --artifacts-root artifacts/live-analysis-20260918-001 \
  --mission-id mission-live-aapl-20260918-001 \
  --navigator-live-url http://127.0.0.1:8001 \
  --navigator-reference-root artifacts/navigator-reference-current \
  --sentry-research-root artifacts/sentry-calibration-v2-20260917 \
  --sentry-research-closeout-root artifacts/sentry-calibration-v2-closeout-20260917 \
  --sentry-scan-archive artifacts/live-analysis-20260918-001/sentry/scan.json \
  --sentry-archive /Users/nikolai/BlackPod-Versions/blackpod_battlestar/artifacts/microcap_sentry/events/2026-07-15.jsonl \
  --sentry-source-kind research \
  --sentry-source-label 'Canonical Sentry research archive · July 15' \
  --sentry-canonical-root /Users/nikolai/BlackPod-Versions/blackpod_battlestar
```

Open <http://127.0.0.1:5174/>. Stop the old reader before starting another on the
same port. The reader and reference worker are foreground/local processes, not
new reboot-persistent services. Saved evidence works without acquisition running;
live prices need the separately configured canonical API. A new analysis run
needs another explicit operator command and a reader source switch.

## Validation and unchanged boundaries

- Focused canonical scan/history/reconciliation/attention tests: 142 passed,
  45 subtests passed.
- Focused Build Week reader/brief/scan/mission-CLI tests: 88 passed,
  133 subtests passed. The initial sandbox run could not bind test HTTP sockets;
  rerunning with loopback permission passed.
- Mission/source pin checks and exact Sentry replay passed. Browser checks use
  the real new mission, not a replay fixture or manufactured accepted brief.
- No production source changed. No full-suite rerun was needed for this
  artifact activation; the preceding source checkpoint records those results.
- No Governor/Navigator authority, ModelDock configuration, Sentry calibration,
  prospective collection, or Oracle/Council integration boundary changed.
- Market histories, captures, receipts, and browser artifacts remain local and
  ignored. They are not made durable remotely by committing these operator docs.
