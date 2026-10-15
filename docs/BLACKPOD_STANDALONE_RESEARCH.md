# BlackPod standalone research station

Double-click **BlackPod.app** in `~/Applications`, or run:

```bash
open "$HOME/Applications/BlackPod.app"
```

The native window has four tabs:

| Tab | Local address | What it shows |
| --- | --- | --- |
| Experiment | <http://127.0.0.1:5181/?view=research> | Saved prospective predictions and outcomes |
| Historical baseline | <http://127.0.0.1:5182/dashboard.html> | The retained rule-versus-control backtest |
| Sentry | <http://127.0.0.1:5183/sentry> | Bounded headlines, IEX price/volume context and evidence clocks |
| Station status | <http://127.0.0.1:5183/> | Background service, collection schedule, latest capture and OFF verification |

The user LaunchAgent `com.blackpod.shadow-station` runs the research module
independently of Codex and the app window. Closing either window does not stop
collection. The service starts after login and launchd restarts it after a
process failure. The earlier Codex collector is **PAUSED**; do not enable it
alongside this station.

The [Sentry catalyst feed](SENTRY_CATALYST_FEED.md) has its own worker, bounds,
watchlist, evidence store and controls. Pausing the pilot collector does not pause
Sentry, and pausing Sentry does not change the pilot. To stop both, stop the station.

This is a local research launcher using the existing checkout and `.venv`,
not a self-contained distribution of every BlackPod service. Keep
`/Users/nikolai/Projects/blackpod_battlestar_build_week` and its Python environment
in place. It does not start Oracle, Senate, Brigade, ModelDock, broker execution
or another experiment. The dashboards are read-only and auto-trading stays OFF.

## Nightly operation

Collection is enabled for the existing frozen pilot at **6:30 p.m.
America/Los_Angeles**, including weekends when original evidence remains due.
The first scheduled standalone collection is October 14, 2026, at 6:30 p.m.;
installation and health checks do not claim that this run has occurred.
The local time remains 6:30 p.m. after November's clock change: 01:30 UTC
before the change, 02:30 UTC afterward.

The signal cohort remains **October 14–November 24, 2026**: 30 sessions,
QQQ/SPY, 60 planned checks. The final exit window is November 27. Later
captures may only resolve original opportunities, through the existing
**December 4, 2026, Los Angeles** collection cap. Completion or the cap stops
provider collection and marks the record for manual review. It does not select
another rule, extend the cohort, tune criteria, or enable trading.

Keep this Mac **awake, connected to the internet and logged in** during the
collection window. Codex and the app window can be closed. The module cannot
collect while the computer is asleep, powered off or logged out. On startup
or waking, it checks unfinished original work; elapsed prediction deadlines
remain missed. It never backdates a valid prediction. A dependable always-on
machine would be needed for guarantees beyond these local operating limits.
Apple describes the user-agent login lifecycle in its
[LaunchAgent documentation](https://developer.apple.com/library/archive/documentation/MacOSX/Conceptual/BPSystemStartup/Chapters/CreatingLaunchdJobs.html).

The supervisor permits one instance, persists an attempt before collection,
and allows up to **three attempts per due day**, with at least five minutes
between attempts. Each collector subprocess is limited to 120 seconds.
Interrupted attempts remain counted after restart. Journal verification,
frozen source pins and the OFF gate must pass; the existing collector owns
actual recording times and all prediction/outcome validation.

## Check the station

Run commands from the existing checkout:

```bash
cd /Users/nikolai/Projects/blackpod_battlestar_build_week

# Validate the selected evidence, frozen protocol, UI build and OFF runtime.
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python3.11 \
  -m blackpod_build_week.shadow_station check \
  --config output/blackpod-shadow-station/config.json

# Read the station's latest saved operational status.
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python3.11 \
  -m blackpod_build_week.shadow_station status \
  --config output/blackpod-shadow-station/config.json

# Start/check the installed LaunchAgent and open the experiment in a browser.
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python3.11 \
  -m blackpod_build_week.shadow_station open \
  --config output/blackpod-shadow-station/config.json
```

These checks do not call providers. **RUNNING** describes service health, not
strategy performance or current market-data availability. The OFF label needs
both a fresh service heartbeat and a fresh actual runtime check with all entry,
worker, restart and transfer guards disabled. A stale or unverified snapshot
cannot establish OFF. The historical dashboard's OFF wording describes the
retained research record; use Station status for the current check.

Check **Latest market evidence**, **Last successful collection**, and the
collector reason. A new reader/heartbeat timestamp alone does not mean prices
were collected. The experiment's **Refresh saved records** button reads the
journal; it never starts collection. Counts may legitimately remain unchanged
when no original opportunity is ready.

## Pause or resume collection

These commands control the research collector only. They leave dashboards
available and cannot enable auto-trading:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python3.11 \
  -m blackpod_build_week.shadow_station disable-collection \
  --config output/blackpod-shadow-station/config.json

PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python3.11 \
  -m blackpod_build_week.shadow_station enable-collection \
  --config output/blackpod-shadow-station/config.json
```

Resuming does not reset attempts, extend the end date, or reconstruct missed
predictions. Do not run the old Codex heartbeat or a second manual collector
while the standalone collector owns the schedule. The journal's append lock
protects publication; it is not a substitute for one scheduled collector.

## Recovery and retained files

Station configuration, control, receipts and sanitized operational state live
under `output/blackpod-shadow-station/`. They are separate from the append-only
experiment journal and historical evidence bundles. `service.log` rotates at
256 KiB with two backups, approximately 768 KiB total. Startup stdout/stderr go
to `/dev/null`; raw provider bodies, subprocess errors and credentials are not
copied into service receipts. Log links to other files are rejected.

If status reports a blocked gate or exhausted retries, inspect the status and
sanitized log. Check connectivity, the unchanged checkout, source pins,
credentials at their already configured local source, and runtime OFF. Do not
repair journal evidence, reset counters or edit frozen source files to force a
run. Invalid evidence stays unavailable. No fixture or different experiment is
substituted. A full service restart verifies retained evidence again.

The local journals and bundles are ignored by Git. Back up the complete
experiment journal, original historical bundle and dashboard evidence copy;
pushing source code does not back them up. Keep private station configuration
and credential material out of commits.

To stop the whole research module temporarily, first quit its window, then:

```bash
/bin/launchctl bootout "gui/$(/usr/bin/id -u)/com.blackpod.shadow-station"
```

That stops the dashboards and collector until the app starts the installed
agent again or the next login loads it. It does not delete evidence or change
trading settings.

## Prepare, install or remove the app

These are explicit maintenance commands, not nightly work. Preparation builds
the small native Swift/AppKit/WebKit window with the installed Xcode toolchain
and stages an owned app plus LaunchAgent. It installs no new dependencies,
reads no trading keys and does not activate collection. Use a new package
destination when rebuilding; conflicting prepared output is rejected.

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python3.11 \
  -m blackpod_build_week.shadow_station_macos prepare \
  --destination "$PWD/output/blackpod-shadow-station/package-next" \
  --repo-root "$PWD" \
  --python-executable "$PWD/.venv/bin/python3.11" \
  --config "$PWD/output/blackpod-shadow-station/config.json" \
  --log-root "$PWD/output/blackpod-shadow-station"

PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python3.11 \
  -m blackpod_build_week.shadow_station_macos install \
  --package-root "$PWD/output/blackpod-shadow-station/package-next" \
  --applications-dir "$HOME/Applications" \
  --launch-agents-dir "$HOME/Library/LaunchAgents"
```

`prepare` also accepts `--swift-compiler /absolute/path/to/swiftc` or an already
compiled `--native-executable /absolute/path/to/binary`. Installation verifies
ownership before replacing existing wrappers and never invokes `launchctl`.
An unrelated `BlackPod.app` or modified agent is preserved and rejected.

For an update, disable collection, stop the old agent, install the reviewed
package, then load it and verify health before resuming the original schedule:

```bash
/bin/launchctl bootstrap "gui/$(/usr/bin/id -u)" \
  "$HOME/Library/LaunchAgents/com.blackpod.shadow-station.plist"
```

Use the `check`, `status`, and `enable-collection` commands above. Do not
bootstrap another instance while the current agent is loaded. Native window
changes take effect after quitting and reopening the app.

To remove the wrappers permanently, disable collection, quit the window,
stop the agent with `bootout`, then run:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src .venv/bin/python3.11 \
  -m blackpod_build_week.shadow_station_macos uninstall \
  --applications-dir "$HOME/Applications" \
  --launch-agents-dir "$HOME/Library/LaunchAgents"
```

Uninstall removes verified owned wrappers only. It does not stop processes
itself or delete the repository, configuration, journal, evidence or runtime.

## Installation verification: October 14, 2026

The installed user LaunchAgent was verified running under launchd with parent
PID 1. A forced failure and restart of the owned supervisor restored all three
local pages. After the final status/log hardening reload, all three endpoints
again returned HTTP 200 with fresh OFF verification and collection enabled.
The user confirmed the native app window was running. The earlier Codex
collector was confirmed paused.

The retained real journal remained unchanged at **3 events, 21 evidence blobs,
no orphan evidence**. Frozen source files were unchanged. At this verification,
the first scheduled 18:30 standalone provider collection had **not yet run**;
successful installation, app display and offline fixtures are not evidence of
that future capture.

The selected offline regression suite passed **202 tests in 28.069 seconds**:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests .venv/bin/python3.11 \
  -m unittest test_shadow_station test_shadow_station_collection \
  test_shadow_station_macos test_shadow_experiment \
  test_shadow_experiment_cli test_shadow_experiment_capture \
  test_shadow_historical_dashboard test_shadow_historical_baseline \
  test_shadow_historical_cli -q
```

## Offline validation and final review

The station boundaries have deterministic offline tests, including scheduling,
clock changes, caps, retries, interruptions, state and log recovery, ownership
checks, immutable evidence, local HTTP restrictions and fresh OFF verification:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests .venv/bin/python3.11 \
  -m unittest test_shadow_station test_shadow_station_collection \
  test_shadow_station_macos -q
```

These fixtures do not establish real collection success or profitability.
Real retained journal records and the status receipt show what actually ran.
At completion, review the original candidate mean gross response against the
identical-date equal-weight QQQ/SPY control, mean excess, paired count and
completeness. Include abstentions, missed predictions and missing-input
deferrals. Use the frozen criteria and the
[historical baseline and its limitations](REVERSAL_HISTORICAL_BASELINE.md).
Missing evidence remains inconclusive; costs and executable fills remain
unmeasured. Further experiments require explicit user authorization.
