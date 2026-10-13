"""Explicit offline fill-lot accounting; no broker calls or execution controls."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from .contracts.trading_accounting import AccountingInput, PaperActivitiesInput
from .decision_journal_store import JournalStore, JournalStoreError, check_separate_root
from .hashing import sha256_bytes
from .sentry_history_cache import RecoveryError, read_regular


def build_parser():
    parser = argparse.ArgumentParser(description="Offline PAPER fill-lot and fee accounting; never enables trading")
    commands = parser.add_subparsers(dest="command", required=True)
    normalize = commands.add_parser("normalize-activities", help="normalize an explicitly declared retained activity export")
    normalize.add_argument("--export", type=Path, required=True)
    normalize.add_argument("--activity-set-id", required=True)
    normalize.add_argument("--output", type=Path)
    validate = commands.add_parser("validate-activities", help="verify strict activity inputs against original source bytes")
    validate.add_argument("--activities", type=Path, required=True)
    validate.add_argument("--source-evidence", type=Path, required=True)
    for name in ("assess", "record"):
        command = commands.add_parser(name, help="preview without writes" if name == "assess" else "append a reproducible accounting observation")
        command.add_argument("--journal-root", type=Path, required=True)
        command.add_argument("--accounting", type=Path, required=True)
        command.add_argument("--activities", type=Path)
        command.add_argument("--source-evidence", type=Path)
    show = commands.add_parser("show", help="read a verified accounting event without changing storage")
    show.add_argument("--journal-root", type=Path, required=True)
    show.add_argument("--event-id", required=True)
    budget = commands.add_parser("plan-paper-test-budget", help="retain an inactive 25%-of-equity test envelope; no runtime installation")
    budget.add_argument("--journal-root", type=Path, required=True)
    budget.add_argument("--snapshot-event-id", required=True)
    budget.add_argument("--budget-id", required=True)
    budget.add_argument("--recorded-at", required=True)
    budget.add_argument("--declared-by", required=True)
    budget.add_argument("--confirm-account-id", required=True)
    budget.add_argument("--output-root", type=Path, required=True)
    verify_budget = commands.add_parser("validate-paper-test-budget", help="verify the inactive artifact against retained equity evidence")
    verify_budget.add_argument("--journal-root", type=Path, required=True)
    verify_budget.add_argument("--budget", type=Path, required=True)
    return parser


def _retain_file(blobs, path, journal_root):
    check_separate_root(journal_root, path.absolute().parent)
    raw = read_regular(path)
    return {**blobs, sha256_bytes(raw): raw}


def _write_normalized(target, raw, source):
    # Reuse the existing private no-replace writer and source-tree guards.
    # Importing these helpers does not construct a worker or load Galactica.
    from .auto_trading_runtime import RuntimeLedger, _immutable
    from .decision_journal_store import _check_existing_ancestors, _reject_source_storage
    check_separate_root(target.absolute().parent, source.absolute().parent)
    _check_existing_ancestors(target.absolute().parent)
    _reject_source_storage(target.absolute().parent)
    RuntimeLedger(target.absolute().parent)
    _immutable(target.absolute(), raw)


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        from .paper_activity_import import activities_input_from_export, validate_activities_source
        if args.command == "normalize-activities":
            raw = read_regular(args.export)
            submitted = activities_input_from_export(raw, activity_set_id=args.activity_set_id,
                evidence_path="activity_sources/" + sha256_bytes(raw) + ".json")
            if args.output:
                _write_normalized(args.output, submitted.to_bytes(), args.export)
            output = {"activities": submitted.to_dict(), "activities_sha256": sha256_bytes(submitted.to_bytes()),
                "output_path": str(args.output.absolute()) if args.output else None}
        elif args.command == "validate-activities":
            submitted = PaperActivitiesInput.from_bytes(read_regular(args.activities))
            validate_activities_source(submitted, read_regular(args.source_evidence))
            output = {"valid": True, "activity_set_id": submitted.activity_set_id,
                "activities_sha256": sha256_bytes(submitted.to_bytes()), "provider_verified": False}
        else:
            from .trading_accounting import build_accounting_event, evidence_for_accounting
            store = JournalStore(args.journal_root)
            events, blobs = store.verified_contents() if store.root.exists() else ((), {})
            if args.command in {"plan-paper-test-budget", "validate-paper-test-budget"}:
                from .paper_test_budget import build_paper_test_budget, budget_filename, validate_budget_source
                from .contracts.paper_test_budget import PaperTestBudget
                if args.command == "validate-paper-test-budget":
                    budget = PaperTestBudget.from_bytes(read_regular(args.budget))
                    validate_budget_source(budget, events)
                    output = {"valid": True, "budget_id": budget.budget_id, "budget_sha256": sha256_bytes(budget.to_bytes()),
                        "status": budget.status, "enforcement_status": budget.enforcement_status}
                else:
                    source = next((item for item in events if item.event_id == args.snapshot_event_id), None)
                    if source is None:
                        raise ValueError("unknown test budget source snapshot")
                    budget = build_paper_test_budget(source, budget_id=args.budget_id, recorded_at=args.recorded_at, declared_by=args.declared_by)
                    if budget.account_id != args.confirm_account_id:
                        raise ValueError("test budget account confirmation differs from equity source")
                    latest = next((item for item in reversed(events) if item.event_type == "PAPER_BROKER_SNAPSHOT_RECORDED"
                        and item.payload["snapshot"]["account_id"] == budget.account_id), None)
                    if latest is None or latest.event_id != source.event_id:
                        raise ValueError("a new test budget must bind the latest retained account snapshot")
                    target = args.output_root / budget_filename(budget)
                    _write_normalized(target, budget.to_bytes(), args.journal_root / "linked-equity-source")
                    output = {"budget": budget.to_dict(), "budget_sha256": sha256_bytes(budget.to_bytes()),
                        "evidence_path": str(target.absolute()), "journal_event_appended": False}
            elif args.command == "show":
                event = next((item for item in events if item.event_id == args.event_id
                    and item.event_type == "TRADING_FILL_LOT_ACCOUNTING_RECORDED"), None)
                if event is None:
                    raise ValueError("unknown accounting event")
                output = event.to_dict()
            else:
                submitted = AccountingInput.from_bytes(read_regular(args.accounting))
                for path in (args.activities, args.source_evidence):
                    if path is not None:
                        blobs = _retain_file(blobs, path, store.root)
                event = build_accounting_event(submitted, events, blobs)
                output = {"event_id": event.event_id, "decision_id": event.decision_id, **event.payload}
                if args.command == "record":
                    result = store.append(event, evidence_for_accounting(submitted, events, blobs))
                    output.update(written=result.written, sequence=result.sequence)
        print(json.dumps({"command": args.command, **output, "orders_submitted": 0,
            "auto_trading_changed": False}, sort_keys=True))
        return 0
    except (ValueError, OSError, JournalStoreError, RecoveryError, TypeError, RecursionError) as exc:
        print("paper-accounting: " + str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
