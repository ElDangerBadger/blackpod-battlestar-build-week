# Explicit Galactica / Alpaca trading control

This burst adds an executable connection to Galactica's blessed
`blackwell_navigator_trickle.py` and `execution/broker.py`. It defaults **OFF**.
It is separate from the Cabin, mission stages, ModelDock, investment approvals
and the offline journal CLI. No worker, market-data stream or broker is started
by importing these modules, opening the Cabin or recording journal evidence.

The subsequent [paper reconciliation burst](TRADING_RECONCILIATION.md) adds
required installed desk ownership and a persistent account-level receipt ledger.
Activation is now PAPER-only; funded profiles remain representable as proposals
but cannot start an executor through this controller or adapter.

No execution was activated during implementation. Native interfaces were
inspected in `/Users/nikolai/BlackPod-Versions/blackpod_galactica`; no files there
were edited. Its old `blackwell_navigator_stream.py` and `run_navigator.sh` are
not used. The native source has no usable Git HEAD, so provenance uses exact
file hashes.

## Two distinct controls

| Interface | Meaning |
| --- | --- |
| `harbormaster journal set-auto-trading --control ...` | Append immutable TRADING intent; an ON request remains BLOCKED and grants no execution authority |
| `harbormaster journal auto-trading-status` | Read the journal's intent projection; does not describe a running executor |
| `auto_trading_cli enable` | Explicitly confirm a runtime profile and start its guarded executor |
| `auto_trading_cli disable` | Block further increases, retain protective exits, and drain until flat |
| `auto_trading_cli status` | Read the actual local worker/entry-gate state without broker calls |

An approved Navigator SHADOW handoff and an
`INVESTMENT_SHADOW_RESEARCH_ONLY` approval cannot start this worker. Journal v5
intent is separate from runtime authority. The initial capital proposal remains
PROPOSED and inactive. No command activates it, transfers capital, resets desk
budgets to 50/50 or changes investment allocations.

## Runtime profile

The strict versioned profile is `blackpod.galactica_trading_profile.v1`.
Use `examples/auto_trading_profile.paper.template.json` as a **non-runnable
template**: every replacement marker must be resolved explicitly. A profile
declares:

- PAPER or LIVE, exact account ID and an existing compatible Python executable.
- Galactica root and all twelve required import-closure hashes; absent optional
  package initializers are also pinned as absent.
- Frozen bias CSV and mandate JSON paths and hashes.
- Owned TRADING symbols and disjoint protected INVESTMENT symbols, with either
  `DEDICATED_TRADING` or `SHARED_DISJOINT` account ownership.
- Explicit fixed trading-dollar budget, per-order notional cap, consolidated
  account gross cap, price freshness/buffer and authorization expiry.
- A declared capital authorization ID and an allowlisted set of native settings.

The budget is a fixed explicitly authorized cap. It is not automatically
derived from account equity or from the inactive 50/50 proposal. Capital
authorization IDs and operator IDs are declarations, not authenticated
approvals. Same-symbol holdings shared across desks are unsupported because
Alpaca's native close works on the whole symbol position. Ownership must be
declared completely; unclassified positions block increases.

Runtime credentials are inherited only through `APCA_API_KEY_ID` and
`APCA_API_SECRET_KEY`; they are never written into profiles, commands, reports
or control events. The controller sets `ALPACA_PAPER` to match the explicitly
confirmed profile. The adapter constructs native `ExecutionConfig` directly
and never calls its YAML credential fallback. Paper and live credentials are
separate; profile mode and the actual returned account ID are checked before
any broker mutation.

No dependencies are added to this checkout. The chosen interpreter must
already have Galactica's pinned `alpaca-py==0.42.0` and `pandas==2.3.1`.
These versions are checked before any native import. The current checkout
interpreter has no alpaca-py and has pandas 2.3.3; it is sufficient for offline
tests and cannot activate the executor. No compatible external interpreter
was operationally verified in this burst. Later metadata inspection located
BlackPod_Quorum's existing `venv/bin/python` with both matching pinned versions;
no packages were installed and no native executor was started.

## Deterministic execution boundary

The guardian preserves Galactica's EMA, bias, mandate and exit rules. It adds
account/symbol ownership and budget admission at its broker boundary. Native
settings are explicit profile inputs; execution mode, credentials, recruits,
startup-plan and Senate overwrite cannot be injected through that mapping.
New short exposure and crossing an existing short into a long are disabled.
Existing short positions can be reduced within their current quantity.

Every mutation, including OFF reductions, verifies the exact active account.
Entry admission requires the persistent switch, unexpired authorization,
fresh timestamped streamed price, native mandate approval, verified account
cash and consolidated valuations, no pending orders, and room under all
declared dollar caps. Missing or stale facts block admission. An accepted
order remains reserved until its terminal fill is reflected in positions.
Replacements, ambiguous submissions and inconsistent results require manual
reconciliation. There is no automatic resubmission after an uncertain result.

Native EOD position discovery sees only owned trading symbols. Scoped
`flatten_all` closes only those symbols and never delegates native
`close_all_positions(cancel_orders=True)`. Investment symbols and their orders
are not closed, cancelled or managed by this worker.

OFF is an entry gate with **draining**, not liquidation. It does not cancel
pending orders or remove protective exits. A shared local admission lock
serializes OFF against check/audit/submission. A request admitted before OFF
can still fill afterward. OFF can wait for an admitted broker request to
return. The worker remains DRAINING while owned positions or orders remain;
it stops only when their flatness is verified. If the stream ends with owned
risk unresolved, the worker records FAILED and requires a manual position
check. SIGTERM/SIGINT stop only a broker-confirmed flat worker. SIGKILL, machine
failure, network loss and broker outages cannot be made safe by this software
gate; native software exits require a running stream.

One private local account lock is shared across runtime roots for this user
and host; the parent passes the locked descriptor to its supervised worker.
There is no startup gap and no PID-based kill that could target a reused PID.
Other users, hosts and external executors do not honor this lock. They must
not concurrently control this owned trading book.

Buffered market-order notional is an admission estimate, **not a guaranteed
fill-price cap**. Slippage can exceed the estimate. Broker/account queries are
not an atomic consolidated snapshot. This burst does not claim live execution
quality or validated funded-account performance.

## Retention and recovery

Runtime storage must be separate from canonical missions, journal storage,
Galactica source and frozen input locations. Source roots, unsafe links and
path traversal are rejected before writes. A private session retains checked
copies of native source and inputs plus the derived execution profile and
guard implementation hashes. Native imports use that snapshot; changes to
the original pinned source/input paths close new-entry admission.

Control requests, sanitized guard intents/results and worker lifecycle receipts
append to a verified local hash chain. Immutable profile identities conflict
on changed bytes. Writes use private staging, fsync and no-replace publication.
Explicit writer operations recover abandoned staging files and the exact
temporary hard link from interrupted publication. They never truncate or
rewrite committed events. Status reads do not repair or create files.

Repeated action IDs do not spawn another process. A lost startup result requires
an explicit OFF and a new action ID before another startup attempt. Startup
failures and failed or completed workers close their matching entry request. Corrupt retained
history stays fail-closed and needs operator recovery. There is no automatic
restart after process or host failure. Local hash chains detect corruption and
semantic inconsistencies; a trusted filesystem root is required and they are
not signed proof against someone rewriting the entire history.

Runtime receipts are not automatically imported into the Decision Journal.
The subsequent reconciliation CLI explicitly imports verified prefixes and
broker observations, while normal paper execution mirrors v2 receipts into a
persistent account ledger before the local session ledger. Missing ownership
or unresolved prior attempts block entries across runtime folders.
No realized P&L is inferred from a submission or a local position estimate.
Receipt reconciliation and broker-confirmed fill observations are now supported
by the separate [reconciliation interfaces](TRADING_RECONCILIATION.md).
Runtime replay currently scans the full bounded ledger; scaling,
retention and a verified checkpoint remain future work.

## Runnable offline commands

To confirm an existing paper account through authenticated GET requests,
use the separate [paper account checker](PAPER_ACCOUNT_CHECK.md). That check
does not start this executor or change the trading switch.

These commands make no broker calls:

```sh
export PYTHONDONTWRITEBYTECODE=1
export PYTHONPATH=src

.venv/bin/python3.11 -m blackpod_build_week.auto_trading_cli source-manifest \
  --galactica-root /Users/nikolai/BlackPod-Versions/blackpod_galactica

.venv/bin/python3.11 -m blackpod_build_week.auto_trading_cli status \
  --runtime-root /Users/nikolai/Projects/blackpod_battlestar_build_week/output/auto-trading-runtime

.venv/bin/python3.11 -m blackpod_build_week.harbormaster journal set-auto-trading \
  --journal-root output/auto-trading-intent-example \
  --control examples/auto_trading.control.off.v1.json

.venv/bin/python3.11 -m blackpod_build_week.harbormaster journal auto-trading-status \
  --journal-root output/auto-trading-intent-example
```

After supplying a complete actual profile, preview it offline:

```sh
.venv/bin/python3.11 -m blackpod_build_week.auto_trading_cli validate-profile \
  --profile /absolute/path/to/explicit-account-profile.json
```

That prints its canonical hash and verifies local pins only; it does not
authenticate capital approval or contact the account.

**The following is an activation example, not a command executed in this burst.**
It starts a market stream and permits Alpaca orders when all native/guardian
gates pass. Use the exact profile hash, account ID and mode from the profile:

```sh
.venv/bin/python3.11 -m blackpod_build_week.auto_trading_cli enable \
  --runtime-root /absolute/path/to/separate-runtime \
  --profile /absolute/path/to/explicit-account-profile.json \
  --action-id explicitly-approved-start-1 --operator-id actual-operator \
  --confirm-profile-sha256 EXACT_CANONICAL_PROFILE_HASH \
  --confirm-account-id EXACT_ACCOUNT_ID --confirm-mode PAPER

.venv/bin/python3.11 -m blackpod_build_week.auto_trading_cli disable \
  --runtime-root /absolute/path/to/separate-runtime \
  --action-id explicitly-requested-off-1 --operator-id actual-operator
```

Restart after draining requires a new explicitly confirmed enable action.
Neither enable command nor a funded-account mode was selected or executed
during development. No credential files were opened, brokers contacted or money moved.

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:tests .venv/bin/python3.11 \
  -m unittest test_auto_trading_runtime test_galactica_trading_adapter \
  test_trading_automation -q
```

The tests use fake processes and broker clients, synthetic native module
bytes and mocked imports. The actual worker-to-adapter path, locks, snapshots
and persisted receipts run locally; native Galactica and Alpaca never run.
