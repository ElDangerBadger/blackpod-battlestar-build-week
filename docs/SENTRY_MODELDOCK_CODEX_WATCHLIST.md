# ModelDock / Codex full-watchlist Sentry

This change adds an explicit Codex route for observation-only scheduled Sentry
assessments. Generic ModelDock callers still require MLX. No trading rules,
orders, allocations, ModelDock configuration or frozen-pilot files are changed.

## Contract and evidence

The new Sentry transport is `blackpod.sentry_synthesis_transport.v18`. It uses the
existing economic V4 reasoning instructions with a declared array-format suffix.
Oracle returns `blackpod.sentry_oracle_draft.v5`: the original economic fields and
a nonempty `implications` array of symbol/linkage/trading/investment entries for
each theme. Symbols must belong to the supplied watchlist and be unique within
each theme. Any relevant subset is allowed; ten-symbol coverage is never forced.
The original array and its order remain intact. There is no array-to-map repair,
deduplication, placeholder filling or output rewrite. Challenge v2 hashes and
reviews the original v5 draft.

V1–V17 wire reconstruction and historical MLX validation remain unchanged. The
new contract avoids optional object properties and combinators, retaining
required fields and closed objects in the supported schema subset. See
[OpenAI structured-output documentation](https://developers.openai.com/api/docs/guides/structured-outputs).
Host validation still checks duplicate symbols, citations, direct-mention
relationships, economic fields, bounds and challenge coverage.

The new Sentry-only client verifies that ModelDock is ready, idle and explicitly
using its Codex provider before each POST. It records the registry alias separately
from the actual reported Codex model, engine, thread and turn. Execution proof
binds the server trace, caller correlation and clocks. Unknown model revisions,
native stop reasons and unavailable usage stay unknown. Codex does not enforce
the submitted 4,096-token parameter; no equal-compute comparison is claimed.

Every role reserves before dispatch, retains the full bounded raw response and
validated public projection, and writes a hash-bound receipt. Accepted Codex
responses require complete HTTP 200 evidence no larger than 512 KiB. The service
deadline remains 900 seconds plus 30 seconds delivery grace. No retries, fallback
providers or response repair occur. Failed or interrupted attempts remain visible.
Recovery and verification never invoke inference.

## Qualification before scheduling

A separate qualification uses one saved full-watchlist packet with verified
source evidence. It sends at most one Oracle request followed by one challenge
only if Oracle passes. It does not enter the frozen QQQ/SPY experiment or replace
an operational report. Repeating capture at that destination only verifies the
existing evidence; a changed packet/config conflicts, and partial attempts cannot
be resumed by resending. The proof is structurally valid compatibility evidence,
not an economic truth label or a trading gate.

A failed terminal challenge has one separately invoked follow-up path, requiring
an exact retained human authorization for one additional request. The immutable
link binds the packet, original failed receipt and approval hashes before a new
role reservation. Verification replays the original failure as well as the linked
result. No unlinked role is adopted; interruption cannot trigger a resend.
This is an explicit new request, not automatic recovery or replacement of failure.

For the October 20 build, the exact saved packet is
`output/sentry-evidence-economic-upgrade-20261018/real-content-packet.json`:
8 headlines, available provider article text and original market context, as of
`2026-10-18T15:49:50.452270Z`. It covers SPY, QQQ, NVDA, AMZN, LULU, NKE, DG,
PG, CLX and GOOGL. Its canonical SHA-256 is
`4ad3a39d2e9104b4714aed16a25381f12bf296560448e747ad50f6bef6ac90da`.
This is preserved historical evidence, not current market analysis.

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src \
  /usr/bin/caffeinate -i -s -t 1890 .venv/bin/python3.11 \
  -m blackpod_build_week.sentry_codex_validation capture \
  --config output/blackpod-shadow-station/config.json \
  --packet output/sentry-evidence-economic-upgrade-20261018/real-content-packet.json \
  --root output/modeldock-codex-full-watchlist-20261020-001

PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python3.11 \
  -m blackpod_build_week.sentry_codex_validation verify \
  --root output/modeldock-codex-full-watchlist-20261020-001
```

Verification reports current auto-trading as `NOT_CHECKED`: it replays retained
proof and does not inspect live runtime. Capture and the scheduled service check
the actual OFF controls and frozen source pins before and after dispatch.

After both roles qualify, this explicit command enables the existing bounded
weekday monitoring schedule, with economic V4 and retained provider content:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python3.11 \
  -m blackpod_build_week.sentry_synthesis_service configure \
  --config output/blackpod-shadow-station/config.json --enabled \
  --modeldock-base-url http://127.0.0.1:8000 \
  --modeldock-timeout-seconds 900 --modeldock-delivery-grace-seconds 30 \
  --modeldock-provider codex --economic-prompt \
  --economic-prompt-version ECONOMIC_V4 --include-article-content \
  --codex-validation-root output/modeldock-codex-full-watchlist-20261020-001 \
  --weekday-monitoring
```

`--schedule finite-schedule.json` is the alternative to `--weekday-monitoring`;
exactly one is required for Codex. The old October 18 finite trial is expired and
is not silently extended. Four background **assessments** per Los Angeles day and
one-hour spacing remain: each assessment may make one Oracle and one challenge
request. Fresh captures, new headline evidence, archive verification, capacity,
OFF, frozen pins, exact watchlist and retained qualification gates still apply.
No catch-up or budget reset occurs. Pausing/changing control during a role blocks
further dispatch and success publication. A changed watchlist requires a new
explicit qualification; it is not automatically sent to the cloud.

The existing standalone supervisor runs the worker and serves
`http://127.0.0.1:5183/sentry-synthesis`. It needs a normal idle service restart to
load changed Python source. No new daemon or native wrapper is necessary. The UI
shows actual provider/model provenance and preserves challenge dissent. Both
passes share a provider and evidence; they do not establish independent consensus.
No new automatic Research intake or decision authority is introduced.

## October 20 rollout record

Code and offline tests are implemented. Automatic approval review rejected the
real capture **before process creation**, requesting explicit permission for the
expanded full-watchlist article payload and scheduled cloud delivery. Its zero-call
record is retained in the qualification proof directory. The user then explicitly
approved both the saved validation and future scheduled packets. That approval is
retained in `explicit-approval.json`. The one-shot capture completed with an
accepted Oracle and a failed challenge. The user separately approved one linked
challenge, which then passed. The complete qualification and original failure
replayed without network calls before enabling the new control.

| Role | Observed result |
| --- | --- |
| Oracle | Accepted; `gpt-6.1-sol`, 7,036 reported output tokens, complete HTTP 200 raw response retained |
| Challenge | `FAILED / MODELDOCK_CODEX_VALIDATION_FAILED`; no retained HTTP response |
| Explicit linked challenge | Accepted; `gpt-6.1-sol`, 2,432 reported output tokens, complete HTTP 200 raw response retained |

Oracle was reserved at `2026-10-20T17:04:47.082429Z` and completed at
`17:07:26.915306Z`. Challenge was reserved at `17:07:28.202864Z` and failed at
`17:07:29.476388Z`. A subsequent metadata-only check observed ModelDock BUSY with
one active request and zero active compute; a later check observed READY. Those
observations are not proof of the original failure phase or of zero prior POSTs.
Both original role records replayed with network access patched to fail.

The user explicitly approved **one linked challenge request** against the exact
accepted Oracle and saved packet. Its approval is retained as
`challenge-followup-approval.json`. It was reserved at
`2026-10-20T17:21:23.053419Z` and completed at `17:22:20.651724Z`. The original
failed receipt remains byte-identical. The approved command was invoked once:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python3.11 \
  -m blackpod_build_week.sentry_codex_validation capture-challenge \
  --config output/blackpod-shadow-station/config.json \
  --root output/modeldock-codex-full-watchlist-20261020-001
```

Without that specific approval, or after an interrupted/failed follow-up, this
command cannot silently send another request. `qualified-postflight.json` records
both accepted roles, zero network calls during replay, and the preserved original
failure. The earlier `gated-postflight.json` remains as the preceding incomplete
state; it was not overwritten.

After qualification, the CLI configured economic V4, transport V18, explicit
Codex and `WEEKDAY_BOUNDED` monitoring. The owned standalone LaunchAgent received
a graceful SIGTERM with the pilot verified idle and OFF, and KeepAlive restarted
it from PID 10296 to PID 23580. No app rebuild, ModelDock configuration change or
nightly-pilot schedule change was needed.

The source collector's separate finite window expired on October 19 at
`13:35:00Z`. The user explicitly approved restoring its standard bounded weekday
collection. The collector retained the same ten symbols, `delayed_sip` feed and
article-content choice; only the expired finite window was removed. It resumed
and retained a fresh capture from the `17:26:28Z` attempt. No source credentials
were printed or changed.

Deployment checks found repeated archive/ancestor replay causing read-only UI
timeouts with the grown source/archive. Assessment admission was temporarily
paused while an operation-scoped verification reuse fix was prepared. The first
scheduled run (`0dd44212d5f2e2af92941b590f0ca6092bc9cee428f83a9a981e45e655d254ac`)
reserved at `17:28:32.611318Z` completed Oracle while that pause was active: the
mandatory gate rejected it with `VALIDATION_OR_GATE_FAILED` and blocked challenge.
Its reservation remains counted. No resend, budget reset or output promotion
was performed. Provider-free recovery appended only that attempt's completion
clock/report; the older incomplete attempt was left untouched.

The replay fix shares verified source, ledger, packet, role and ancestor bytes
within one read/verification operation. Every separate operation starts fresh;
there is no persistent cache, TTL, stat-only trust or skipped ancestry. Dispatch
and OFF gates still make their own fresh checks. Eleven new tests cover reuse,
unchanged report bytes, detached results and subsequent source/receipt/ancestor
tampering. A separate read-only review found no integrity blocker.

With networking patched to fail, the actual archive verified in **10.425 seconds**:
59 attempts, 58 reports (30 challenged interpretations, 21 rejections, 7 failures)
and one pre-existing incomplete attempt. These counts include older MLX work;
they are not 59 new Codex assessments. The qualification also replayed, OFF and
frozen pins verified, and all 45 original pilot files and 582 original Sentry
run files retained their original hashes.

The second idle restart changed PID 23580 to 25625 at `17:36:55Z`. The official
configure command above then re-enabled the same qualified weekday control,
without resetting reservations. Real loopback checks at `17:37:31Z` returned
HTTP 200 for `/sentry-synthesis.json` (7.526 seconds), `/sentry-synthesis`
(7.392 seconds), the experiment dashboard on port 5181 and historical report on
port 5182. The synthesis page shows the new scheduled route separately from its
retained rejected report; provider/model details appear when retained for a role.
The first ordinary next eligibility is `2026-10-20T18:28:32.611318Z`
(11:28 a.m. Pacific), subject to fresh/new evidence and remaining daily capacity.
No additional assessment was forced for deployment verification.

Both native workers now run under the existing standalone LaunchAgent. Collection
uses the restored weekday five-minute cadence (maximum 144 attempts/day); synthesis
retains four background assessments/day and at least one-hour spacing within its
5 a.m.–5 p.m. Pacific weekday window. An assessment can use two inference requests.
ModelDock must remain running, signed in and explicitly selecting Codex. The Mac
must be awake with network access; missed windows do not authorize catch-up.
Codex desktop itself need not remain open. This deployment adds no decision,
execution, experiment or capital authority.

## Offline verification

The exact staged candidate was exported into an isolated temporary checkout to
exclude unrelated uncommitted Investment/research work. Results:

- Sentry: **755 run, 753 passed, 2 optional canonical-checkout tests skipped**,
  290.569 seconds.
- ModelDock policy and standalone station: **166 passed**, 2.530 seconds.
- The four new focused suites: **69 passed**, including all 1,023 nonempty
  watchlist subsets. These tests are included in the Sentry total.
- After adding explicit follow-up linkage, **75 focused tests passed** in 2.913
  seconds. The six additional tests cover original-failure replay, exact human
  authorization types, link chronology, orphan rejection and interrupted follow-up
  recovery with no resend. The original 755-test run preceded this additive path.
- All four genuine retained October 19 responses also replayed through the new
  provider-envelope validator with networking patched to fail.

Final isolated-candidate rerun, including the linked challenge, UI labels and
operation-scoped replay fix:

- **Sentry: 773 run, 771 passed, 2 optional canonical-checkout tests skipped**,
  178.143 seconds.
- **ModelDock policy and standalone station: 166 passed**, 2.614 seconds.
- The replay fix's targeted gate: **35 passed**, 13.243 seconds, included in the
  final Sentry total. The earlier UI/follow-up targeted run passed 68 tests.
- No inference/provider calls occurred in these offline suites. Actual inference
  coverage is the explicitly approved saved-packet qualification above. Runtime
  deployment coverage consists of real collection, provider-free archive replay,
  fresh native worker heartbeats and local HTTP checks, not an additional forced
  assessment. Native collection retained a new successful capture at `17:37:01Z`;
  the Codex worker reported `WAITING_FOR_NEXT_SLOT` at `17:38:29Z`.

The final candidate exported exactly the 23 staged paths; all 37 unrelated
pre-existing changed/untracked files remained byte-identical. Its source and tests
were checked against the deployed checkout before commit. Local proof files are
retained under `output/modeldock-codex-full-watchlist-20261020-001/`, including
`qualified-postflight.json`, `replay-postflight.json`, `archive-preservation.json`,
`final-restart.json`, `native-postflight.json`, `ui-postflight.json` and
`final-offline-test-results.json`. Source packets, article bodies, raw provider
responses and credentials are not committed to Git.

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests .venv/bin/python3.11 \
  -m unittest discover -s tests -p 'test_sentry*.py' -q

PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests .venv/bin/python3.11 \
  -m unittest test_modeldock_config test_modeldock_client test_modeldock_preflight \
  test_modeldock_cli test_modeldock_delivery test_shadow_station \
  test_shadow_station_collection test_shadow_station_macos -q
```

The first workspace-wide Sentry attempt hit 11 sandbox-denied local HTTP binds;
the isolated-candidate rerun above had loopback permission and passed. No provider
calls occurred in either test run. Two redundant service-test processes were
intentionally canceled, not reported as passes or failures. Tests cover truthful
Codex telemetry, original raw/projection/receipt bindings, tampering, conflict and
interruption recovery, no resend, Oracle-before-challenge gating, frozen-pin/OFF
changes including during readiness, explicit cloud admission, mixed historical
replay, source freshness, immutable budgets, scheduling and escaped UI provenance.

Generic ModelDock source and configuration remain unchanged. The installed
ModelDock Codex provider and its source matched SHA-256
`b779e6cd4a0aa0850206ee3257c111b7348595a81959ded4e245dfd32bf25e2a` when inspected.
Its implementation requests read-only tool-disabled inference and rejects tool
or approval requests. This is local implementation evidence, not independent
cloud attestation or proof of narrative quality.

## Changed files

All paths below are relative to the repository root. Some required content and
economic-prompt work was already present locally; it is included so the committed
Sentry route works on a clean checkout, while unrelated Investment/research work
remains uncommitted.

- Contracts and Codex delivery: `src/blackpod_build_week/contracts/sentry_synthesis.py`,
  `sentry_modeldock_codex.py`, `sentry_synthesis_transport.py`,
  `sentry_codex_validation.py` (the latter three under `src/blackpod_build_week/`).
- Retained content and economic reasoning: `src/blackpod_build_week/sentry_content.py`,
  `sentry_economic_reasoning.py`, `sentry_narrative_evaluation.py`.
- Observation capture: `src/blackpod_build_week/sentry_catalyst.py`,
  `sentry_catalyst_capture.py`, `sentry_catalyst_presentation.py`,
  `sentry_catalyst_service.py`.
- Synthesis, scheduling and UI: `src/blackpod_build_week/sentry_synthesis.py`,
  `sentry_synthesis_service.py`, `sentry_synthesis_presentation.py`.
- Tests: `tests/test_sentry_catalyst_service.py`, `test_sentry_codex_contracts.py`,
  `test_sentry_codex_service.py`, `test_sentry_codex_validation.py`,
  `test_sentry_economic_reasoning.py`, `test_sentry_modeldock_codex.py`,
  `test_sentry_replay_context.py`, `test_sentry_synthesis_service.py`.
- Runbook and real results: `docs/SENTRY_MODELDOCK_CODEX_WATCHLIST.md`.

Next work should review the first ordinarily scheduled Codex brief against its
retained evidence and dissent before changing prompts or expanding authority.
Structural compatibility does not establish economic accuracy, independent
corroboration, portfolio suitability or a trading edge.
