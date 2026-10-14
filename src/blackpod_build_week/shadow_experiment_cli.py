"""Explicit prospective pilot collection and offline inspection; no trading.

Only `freeze` and `collect` can call the two fixed market-data GETs. There is
no operator supplied recording clock: production admission uses the local UTC
wall clock after capture. This is local provenance, not a trusted timestamp.
"""
from __future__ import annotations

import argparse
from datetime import datetime, time, timedelta, timezone
import json
import os
from pathlib import Path
import sys
from zoneinfo import ZoneInfo

from .contracts.mission_request import parse_rfc3339, parse_strict_json_object_bytes
from .decision_journal_store import JournalStore, JournalStoreError, check_separate_root
from .paper_account_probe import MAX_CREDENTIAL_BYTES, _read_regular, parse_credentials
from .shadow_experiment_capture import ExperimentCaptureError, market_get, utc_now

NY = ZoneInfo("America/New_York")


def _safe_root(root):
    """Reject sensitive destinations before credential reads or network calls."""
    from .decision_journal_store import _check_existing_ancestors, _reject_source_storage
    root = Path(root).absolute()
    _check_existing_ancestors(root)
    _reject_source_storage(root)
    package = Path(__file__).absolute().parents[2]
    if ".." in root.parts or root == Path(root.anchor):
        raise ValueError("unsafe experiment root")
    for parent in (root, *root.parents):
        if parent.name in {"src", "tests", "fixtures", ".git", "missions"}:
            raise ValueError("experiment root overlaps source storage")
        if any(os.path.lexists(parent / name) for name in ("ledger.lock", "worker.lock", "blackwell_navigator_trickle.py")):
            raise ValueError("experiment root overlaps installed runtime storage")
        if os.path.lexists(parent / ".git"):
            if parent != package or root == parent or root.relative_to(parent).parts[0] != "output":
                raise ValueError("experiment root overlaps repository source storage")
    return root


def _off(runtime_root):
    from .auto_trading_runtime import runtime_status
    status = runtime_status(runtime_root)
    if (status["state"] != "OFF" or status["requested_entries_enabled"]
            or status["worker_active"] or status["entries_enabled"]):
        raise ValueError("shadow experiment requires the selected local runtime OFF")
    return status


def _credentials(args, root):
    source = args.credentials_file.absolute()
    check_separate_root(root, source.parent)
    return parse_credentials(_read_regular(source, MAX_CREDENTIAL_BYTES), args.credential_format)


def _calendar_query(first, last):
    return {"start": first, "end": last}


def _bars_query(first, last):
    def stamp(day, at):
        return datetime.combine(datetime.fromisoformat(day).date(), at, NY).astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    return {"symbols": "QQQ,SPY", "timeframe": "1Day", "feed": "iex", "adjustment": "raw",
        "sort": "asc", "limit": 1000, "start": stamp(first, time()), "end": stamp(last, time(23, 59, 59))}


def build_parser():
    parser = argparse.ArgumentParser(description="One frozen prospective observational pilot, auto-trading OFF")
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("freeze", "collect", "status", "verify"):
        command = commands.add_parser(name)
        command.add_argument("--experiment-root", type=Path, required=True)
        if name in {"freeze", "collect"}:
            command.add_argument("--runtime-root", type=Path, required=True)
            command.add_argument("--credentials-file", type=Path, required=True)
            command.add_argument("--credential-format", choices=("GALACTICA_YAML", "NAVIGATOR_ENV", "PAPER_ENV"), required=True)
        if name == "freeze":
            command.add_argument("--experiment-id", required=True)
            command.add_argument("--first-signal-session", required=True)
            command.add_argument("--hypothesis-file", type=Path, required=True)
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        from .shadow_experiment import build_protocol, collect_observation, freeze_experiment, read_experiment_view
        root = _safe_root(args.experiment_root)
        if args.command == "verify":
            summary = JournalStore(root).verify()
            print(json.dumps({"command": "verify", "verification": summary.to_dict(), "provider_calls": 0}, sort_keys=True))
            return 0
        if args.command == "status":
            print(json.dumps(read_experiment_view(root), sort_keys=True))
            return 0
        _off(args.runtime_root)
        if args.command == "freeze":
            # Reuse the original immutable freeze without fetching or rewriting.
            existing = JournalStore(root).verified_contents()[0] if root.exists() else ()
            if existing:
                view = read_experiment_view(root)
                protocol = view["protocol"]
                from .hashing import sha256_bytes
                hypothesis_raw = _read_regular(args.hypothesis_file.absolute(), 1024 * 1024)
                if (protocol["experiment_id"] != args.experiment_id
                        or protocol["first_signal_session"] != args.first_signal_session
                        or protocol["hypothesis_evidence"]["sha256"] != sha256_bytes(hypothesis_raw)):
                    raise ValueError("existing experiment freeze differs")
                print(json.dumps({"command": "freeze", "written": False, "provider_calls": 0, "experiment": view}, sort_keys=True))
                return 0
            from .contracts.trading_hypothesis import TradingHypothesis
            hypothesis_raw = _read_regular(args.hypothesis_file.absolute(), 1024 * 1024)
            hypothesis = TradingHypothesis.from_bytes(hypothesis_raw)
            if hypothesis.hypothesis_id != "previous-session-reversal-v1":
                raise ValueError("only the frozen reversal pilot is supported")
            first = datetime.fromisoformat(args.first_signal_session).date()
            current = parse_rfc3339(utc_now(), "current local time").astimezone(NY).date()
            if not current <= first <= current + timedelta(days=7):
                raise ValueError("first signal must be within the next seven days, without backdating")
            credentials = _credentials(args, root)
            calendar_raw, calendar_receipt_raw = market_get("calendar", _calendar_query(
                (first - timedelta(days=7)).isoformat(), (first + timedelta(days=80)).isoformat()), credentials)
            calendar_receipt = parse_strict_json_object_bytes(calendar_receipt_raw)
            protocol = build_protocol(experiment_id=args.experiment_id, frozen_at=utc_now(),
                first_signal_session=first.isoformat(), calendar_captured_at=calendar_receipt["captured_at"],
                calendar_raw=calendar_raw, hypothesis_raw=hypothesis_raw, calendar_receipt_raw=calendar_receipt_raw)
            _off(args.runtime_root)
            result = freeze_experiment(root, protocol, {"shadow-experiment/protocol-calendar.json": calendar_raw,
                "shadow-experiment/protocol-calendar-receipt.json": calendar_receipt_raw,
                "shadow-experiment/hypothesis.json": hypothesis_raw})
            print(json.dumps({"command": "freeze", "provider_calls": 1, "result": result}, sort_keys=True))
            return 0
        view = read_experiment_view(root)  # Verify before reading credentials/calling provider.
        protocol = view["protocol"]
        if (view["summary"]["conclusion"] != "PENDING"
                and view["summary"]["pending_outcome_count"] == 0
                and view["summary"]["pending_prediction_count"] == 0):
            print(json.dumps({"command": "collect", "provider_calls": 0, "experiment": view}, sort_keys=True))
            return 0
        # The returned calendar fixes all signal, entry and exit dates. Use only
        # bars whose complete source session plus the frozen buffer has elapsed.
        sessions = protocol["context_sessions"]
        now = parse_rfc3339(utc_now(), "current local time")
        ready = [row for row in sessions if parse_rfc3339(row["session_close_at"], "source close")
                 + timedelta(seconds=protocol["availability_buffer_seconds"]) <= now]
        if not ready:
            print(json.dumps({"command": "collect", "provider_calls": 0, "reason": "NO_COMPLETED_SOURCE_SESSION"}, sort_keys=True))
            return 0
        credentials = _credentials(args, root)
        calendar_raw, calendar_receipt_raw = market_get("calendar", _calendar_query(sessions[0]["date"], sessions[-1]["date"]), credentials)
        bars_raw, bars_receipt_raw = market_get("bars", _bars_query(sessions[0]["date"], ready[-1]["date"]), credentials)
        _off(args.runtime_root)
        result = collect_observation(root, captured_at=utc_now(), calendar_raw=calendar_raw, bars_raw=bars_raw,
            calendar_receipt_raw=calendar_receipt_raw, bars_receipt_raw=bars_receipt_raw)
        print(json.dumps({"command": "collect", "provider_calls": 2, "result": result}, sort_keys=True))
        return 0
    except ExperimentCaptureError as exc:
        print(json.dumps({"error": exc.code, "http_status": exc.http_status, "auto_trading_changed": False}), file=sys.stderr)
        return 2
    except (ValueError, OSError, TypeError, KeyError, JournalStoreError):
        print("shadow-experiment: rejected; check local inputs, immutable journal, clocks and OFF runtime", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
