# Stage 4 LIVE Demo Runbook

Stage 4 adds an operator-facing path around the existing mission workflows. It
does not add a second mission engine. The Make targets below call
`blackpod_build_week.harbormaster mission-run`, the strict LIVE demo packager,
the read-only cabin-context capture, and the existing cabin preparation script.

## Demo and Live are explicit

The Captain's Cabin has two presentation selections and never substitutes one
for the other:

| Selection | Browser data root | Meaning |
| --- | --- | --- |
| Demo (default) | `ui/public/demo/approved/` | a frozen, validated mission pack |
| Live | `ui/public/demo/live/` | the explicitly selected current LIVE mission pack |

`make cabin-prepare` preserves the original judge flow and prepares its
deterministic replay plus the committed, fixed-revision AAPL Navigator market
capture. It performs no network call and records portfolio `NOT_CONFIGURED`.
After one LIVE mission has been independently verified,
`make cabin-freeze-live-demo` copies that same immutable evidence into the
default Demo slot. `make cabin-prepare-live` copies it into the Live slot.
These directories are generated, ignored presentation inputs; canonical JSON
under the source mission remains authoritative.

Selecting Live in the browser does not run a mission. Mission execution is an
explicit terminal operation, and a missing or invalid Live pack is shown as a
Live error. It never falls back to Demo.

The embedded Navigator Ship View follows the same rule. **Demo** labels its
canonical mission transport (normally `REPLAY`) alongside the deterministic
capture. **Live** renders only the market and optional portfolio artifacts
referenced by that Live mission's hash-validated cabin context. If those
supplements are absent, corrupt, or correlated to another symbol or run mode,
the UI reports the failure or unavailable state; it never borrows AAPL replay
data to fill a Live display.

## 1. Prepare the local services and inputs

Install the LIVE dependency in the Build Week environment and start ModelDock
separately. Neither sibling checkout is written by these commands.

```bash
.venv/bin/python3.11 -m pip install -e '.[live]'

export BATTLESTAR_PATH=/path/to/read-only/blackpod_battlestar
export MODELDOCK_BASE_URL=http://127.0.0.1:8000
export MODELDOCK_PROFILE=default
export MODELDOCK_PROVIDER=mlx
export MODELDOCK_MODEL=<registered-local-model>
```

For a multimodal Gemma 4 registration, ModelDock owns the engine choice. Its
profile/model registration should use provider `mlx`, engine `mlx-vlm`, and
the model's supported `text` and `vision` capabilities. Build Week's Oracle
narrative request still asks `/text/generate` for the `text` capability only;
it does not attach an image or select ModelDock's internal engine in the
request payload.

Create three explicit, versioned inputs in an ignored local directory:

- a `blackpod.mission_request.v1` request with `run_mode: LIVE`, a current
  `requested_at`, and an explicit `mission_id`;
- a valid `blackpod.council_supporting_input.v1` policy input; and
- a valid `blackpod.governor_supporting_context.v1` input.

The policy and Governor files are inputs to existing adapters, not knobs for
forcing an outcome. Do not copy replay fixtures into a LIVE command.

Export their paths and the matching mission ID:

```bash
export LIVE_ARTIFACTS_ROOT=artifacts/stage4-live
export LIVE_REQUEST=artifacts/stage4-live-inputs/mission_request.json
export LIVE_MISSION_ID=mission-buildweek-live-spy-001
export LIVE_COUNCIL_POLICY=artifacts/stage4-live-inputs/council_policy.json
export LIVE_GOVERNOR_CONTEXT=artifacts/stage4-live-inputs/governor_context.json
export LIVE_OPERATOR_ID=build-week-operator
```

The example ID and symbol are illustrative. The request symbol should match
the selected read-only Navigator market capture. The current Battlestar Oracle
runs its supported fixed market fleet; it does not gain a new single-symbol
analysis path in Stage 4.

## 2. Verify real local inference

```bash
make preflight-live
```

LIVE preflight checks the Build Week and Battlestar interfaces, ModelDock
health/model metadata, and a real non-mocked generation canary. A shallow
`/health` response is not inference readiness. The provider must be local
`mlx`; timeout, mocked output, invalid structured content, or service failure
is reported without replay fallback.

The canary proves the configured model can perform a real bounded structured
generation; it is not permission to relax the mission contract. During a LIVE
mission, deterministic code supplies a stable Oracle fact catalog. Gemma may
select catalog IDs and write interpretation fields only. Build Week expands
those IDs back to source-bound observed facts, copies Oracle warnings, and
validates the completed `blackpod.oracle_narrative.v1` object. A nonconforming
selection or expanded narrative fails the mission explicitly.

## 3. Run the existing complete mission workflow

```bash
make live-mission
```

This expands to the existing Harbormaster workflow with:

- `--with-modeldock` and no replay fixture;
- `--through NAVIGATOR`;
- the explicit LIVE Council and Governor inputs;
- an explicit `APPROVE_HANDOFF` operator event; and
- a positive handoff expiry.

It remains SHADOW-only. Governor `PROCEED` is merely eligibility for operator
review. The mission becomes `APPROVED` only after the explicit operator receipt,
Navigator handoff, accepted intake, and a created SHADOW plan.

A current Governor `HOLD`, `BLOCKED`, `REVIEW_REQUIRED`, or `STAND_DOWN` is a
valid canonical decision, not an integration defect. In particular, a `HOLD`
mission cannot be advanced to Navigator and must not be repackaged as approved.
Capture it honestly as a held mission, or run a new mission with a new ID when
new market evidence is available. Do not edit its artifacts or force the
operator boundary.

The target requires `LIVE_MISSION_ID` to match the request and confirms that
the named mission was actually created. Repeating an identical completed run
uses the workflow's existing idempotency behavior.

## 4. Capture optional read-only cabin context

The mission outcome and stage contracts do not contain chart history or a
portfolio account. Stage 4 therefore captures optional presentation
supplements beside the canonical presentation artifacts; it does not inject
them into a mission snapshot.

Capture the strict local Navigator `GET /api/ohlc` response:

```bash
export NAVIGATOR_MARKET_URL='http://127.0.0.1:8765/api/ohlc?symbol=SPY&timeframe=1d&ma=250'
export NAVIGATOR_REPOSITORY=/path/to/read-only/navigator
export CABIN_CAPTURED_AT=2026-07-19T20:00:00Z
make cabin-capture-live
```

For a frozen response file, use an exact captured API payload and its recorded
source revision instead:

```bash
unset NAVIGATOR_MARKET_URL NAVIGATOR_REPOSITORY
export NAVIGATOR_MARKET_JSON=artifacts/stage4-live-inputs/navigator_market.json
export NAVIGATOR_REVISION=<recorded-lowercase-git-revision>
export CABIN_CAPTURED_AT=2026-07-19T20:00:00Z
make cabin-capture-live
```

Exactly one market source and one revision source are required. The capture
rejects non-loopback URLs, symbol mismatches, unsupported shapes, absolute
source identities, and attempts to overwrite different immutable content.
Keeping `CABIN_CAPTURED_AT` explicit makes a repeated identical capture a
deterministic no-op.

Portfolio display is opt-in. To include it, add:

```bash
export PORTFOLIO_JSON=/path/to/explicit/read-only-portfolio-snapshot.json
make cabin-capture-live
```

The file must be a validated `blackpod.portfolio_snapshot.v1` object with an
explicit mode matching its mission (`FROZEN` for Replay, `LIVE` for Live), a
capture timestamp, opaque source identity,
account type, currency, and positions. Stage 4 has no portfolio discovery,
broker adapter, credential lookup, valuation fallback, or mutation path. If no
file is supplied, the UI reports `NOT_CONFIGURED`; it does not display an
illustrative portfolio as real data.

The capture writes only mission-relative presentation supplements:

```text
presentation/
├── cabin_context.json
├── navigator_market.json       # when configured
└── portfolio_snapshot.json     # when explicitly configured
```

## 5. Package only a verified approval

```bash
make package-live-demo
```

The strict packager is read-only except for the immutable
`presentation/demo_manifest.json`. It requires all of the following evidence:

- canonical `run_mode: LIVE`;
- terminal `APPROVED` / `COMPLETE` state;
- all five technical stages succeeded;
- Governor `PROCEED`;
- explicit operator `APPROVED_FOR_HANDOFF`;
- Navigator SHADOW handoff staged, intake accepted, and plan created;
- exactly `VALIDATE` and `PLAN_ONLY` allowed;
- all broker/order operations prohibited; and
- one correlated, successful, non-mocked local MLX ModelDock call.

Freezing also requires a clean Build Week checkout at packaging time and a
clean Battlestar worktree recorded by the mission. This keeps the published
revisions sufficient to identify the executed code.

It also validates presentation correlation and artifact hashes. A held mission
fails packaging by design. An identical existing manifest returns
`NO_OP_ALREADY_SATISFIED`; a different immutable manifest is never replaced.

## 6. Prepare and view the two presentation slots

Prepare the verified mission as the explicit Live selection:

```bash
make cabin-prepare-live
npm --prefix ui install
make cabin-dev-live
```

Open the printed Vite URL with `?mode=live`. The browser loads only
`ui/public/demo/live/`; it does not use the Demo pack on failure.

After review, freeze the exact same verified evidence as the default
deterministic demonstration:

```bash
make cabin-freeze-live-demo
make cabin-dev-demo
```

Open with `?mode=demo`, or omit the query because Demo is the default. A
production build can be made for either prepared slot:

```bash
make cabin-build-demo
make cabin-build-live
```

`make cabin-prepare`, `make cabin-dev`, and `make cabin-build` retain their
original judge-replay behavior. `make judge` is unchanged.

## Safety and repository checks

The Captain's Cabin is a read-only renderer. There are no buttons or routes for
mission execution, approval, order submission, cancellation, portfolio
mutation, or broker calls. The only Navigator permissions remain:

- allowed: `VALIDATE`, `PLAN_ONLY`;
- prohibited: `SUBMIT_ORDER`, `CANCEL_ORDER`, `MODIFY_PORTFOLIO`, `BROKER_CALL`.

Before and after a LIVE rehearsal, confirm that sibling worktrees have not
changed:

```bash
git -C "$BATTLESTAR_PATH" status --short
git -C /path/to/read-only/ModelDock status --short
git status --short
```
