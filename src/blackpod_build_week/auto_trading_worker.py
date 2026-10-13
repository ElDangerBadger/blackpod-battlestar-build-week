"""Private worker entry point. Never runs as a side effect of journal commands."""
from __future__ import annotations
import argparse
import asyncio
from functools import partial
from pathlib import Path

from .auto_trading_runtime import (
    RuntimeLedger, TradingRuntimeError, account_lock, close_session_entry_gate, read_json,
    snapshot_execution_profile, utc_now, validate_profile,
)


def run_worker(root: Path, session_id: str, *, runner=None, account_lock_fd=None) -> int:
    if runner is None and account_lock_fd is None:
        raise TradingRuntimeError("worker requires supervised account admission")
    ledger = RuntimeLedger(root)
    with ledger.lock("worker.lock", nonblocking=True):
        control = ledger.latest_control()
        if not control or control["session_id"] != session_id or not control["entries_enabled"]:
            raise TradingRuntimeError("worker has no matching active startup request")
        profile = validate_profile(read_json(ledger.root / "profiles" / f"{control['profile_sha256']}.json"), verify_files=False)
        production = runner is None
        safety = None
        restored = []

        def receipt(value):
            # Adapter supplies bounded sanitized fields, never raw API errors.
            kind = value.get("kind", "BROKER_GUARD")
            payload = {key: item for key, item in value.items() if key != "kind"}
            payload.update(session_id=session_id, mode=profile["mode"], recorded_at=utc_now())
            if kind == "BROKER_GUARD" and safety is not None:
                # Persist shared account evidence before local receipts. A
                # local publication failure must never erase a submitted intent.
                safety.record_receipt(payload)
            ledger.append(kind, payload)

        try:
            if not ledger.entries_enabled(session_id, profile):
                raise TradingRuntimeError("worker startup authorization is no longer active")
            if production and profile["mode"] != "PAPER":
                raise TradingRuntimeError("funded execution is unavailable in the paper reconciliation scope")
            if production and profile["mode"] == "PAPER":
                from .paper_account_safety import PaperSessionSafety
                safety = PaperSessionSafety(profile, control)
                restored = safety.restored_inflight()
            execution_profile = snapshot_execution_profile(ledger, session_id, profile)
        except Exception as exc:
            close_session_entry_gate(ledger, session_id)
            receipt({"kind": "WORKER_STATUS", "state": "START_FAILED", "error_type": type(exc).__name__,
                     "manual_position_check_required": True})
            return 2
        receipt({"kind": "WORKER_STATUS", "state": "STARTING"})
        if runner is None:
            from .galactica_trading_adapter import run_guarded_navigator
            runner = partial(run_guarded_navigator, submission_admission=lambda: ledger.lock("submission.lock"),
                persistent_gate=safety.permit_mutation if safety is not None else None,
                restored_inflight=restored)
        try:
            with account_lock(profile, inherited_descriptor=account_lock_fd):
                asyncio.run(runner(execution_profile, lambda: {"entries_enabled": ledger.entries_enabled(session_id, profile)}, receipt))
        except Exception as exc:
            close_session_entry_gate(ledger, session_id)
            receipt({"kind": "WORKER_STATUS", "state": "FAILED", "error_type": type(exc).__name__,
                     "manual_position_check_required": True})
            return 2
        close_session_entry_gate(ledger, session_id)
        receipt({"kind": "WORKER_STATUS", "state": "STOPPED", "auto_restart_enabled": False})
        return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description="Internal guarded auto-trading worker")
    parser.add_argument("--runtime-root", type=Path, required=True)
    parser.add_argument("--session-id", required=True)
    parser.add_argument("--account-lock-fd", type=int)
    args = parser.parse_args(argv)
    try:
        return run_worker(args.runtime_root, args.session_id, account_lock_fd=args.account_lock_fd)
    except (OSError, ValueError):
        # Profile/setup failures must not expose inherited credentials.
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
