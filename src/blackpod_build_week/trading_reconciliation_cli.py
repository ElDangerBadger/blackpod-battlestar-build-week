"""Explicit PAPER observations and append-only reconciliation; never execution."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import sys

from .contracts.trading_reconciliation import BrokerSnapshotInput, DeskOwnershipInput, ReconciliationInput
from .decision_journal_store import JournalStore, JournalStoreError, check_separate_root
from .hashing import canonical_json_bytes, sha256_bytes
from .sentry_history_cache import read_regular, RecoveryError


def _contents(store):
    return store.verified_contents() if store.root.exists() else ((), {})


def build_parser():
    parser = argparse.ArgumentParser(description="PAPER broker evidence, desk declarations and reconciliation; no order submission")
    commands = parser.add_subparsers(dest="command", required=True)
    for name, field in (("import-probe", "probe"), ("import-snapshot", "snapshot"),
                        ("record-ownership", "ownership"), ("record-reconciliation", "reconciliation")):
        command = commands.add_parser(name)
        command.add_argument("--journal-root", type=Path, required=True)
        command.add_argument("--" + field, type=Path, required=True)
        if name == "import-probe":
            command.add_argument("--snapshot-id")
        if name == "import-snapshot":
            command.add_argument("--evidence", type=Path, required=True)
        if name == "record-ownership":
            command.add_argument("--confirm-account-id", required=True)
            command.add_argument("--confirm-desk-scope-sha256", required=True)
        if name == "record-reconciliation":
            command.add_argument("--runtime-evidence", type=Path)
    reconcile = commands.add_parser("reconcile", help="build and append an observation using explicitly selected recorded evidence")
    reconcile.add_argument("--journal-root", type=Path, required=True)
    reconcile.add_argument("--snapshot-event-id", required=True)
    reconcile.add_argument("--reconciliation-id", required=True)
    reconcile.add_argument("--recorded-at", required=True)
    reconcile.add_argument("--ownership-event-id")
    reconcile.add_argument("--prior-reconciliation-event-id")
    reconcile.add_argument("--runtime-evidence", type=Path)
    show = commands.add_parser("show", help="read a verified observation; no broker or worker calls")
    show.add_argument("--journal-root", type=Path, required=True)
    show.add_argument("--event-id", required=True)
    export = commands.add_parser("export-runtime", help="retain a verified local prefix and its bound profiles")
    export.add_argument("--runtime-root", type=Path, required=True)
    export.add_argument("--output", type=Path, required=True)
    install = commands.add_parser("install-paper-book", help="bind a declared ownership event to the persistent account guard")
    install.add_argument("--journal-root", type=Path, required=True)
    install.add_argument("--ownership-event-id", required=True)
    install.add_argument("--reconciliation-event-id")
    install.add_argument("--confirm-account-id", required=True)
    capture = commands.add_parser("capture-paper", help="explicit GET-only paper snapshot and exact tracked order reads")
    capture.add_argument("--credential-source", type=Path, required=True)
    capture.add_argument("--credential-format", choices=("GALACTICA_YAML", "PAPER_ENV", "NAVIGATOR_ENV"), required=True)
    capture.add_argument("--output-root", type=Path, required=True)
    capture.add_argument("--tracked-order-id", action="append", default=[])
    capture.add_argument("--expected-account-id")
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        if args.command == "capture-paper":
            from .paper_order_capture import capture_paper_orders
            result = capture_paper_orders(args.credential_source, args.credential_format, args.output_root,
                args.tracked_order_id, expected_account_id=args.expected_account_id)
            output = {key: value for key, value in result.items() if key not in {"capture", "report"}}
            print(json.dumps({"command": args.command, **output}, sort_keys=True))
            return 0 if result["result"] == "CONFIRMED" else 2
        elif args.command == "export-runtime":
            from .paper_account_safety import export_runtime
            from .auto_trading_runtime import _immutable
            raw = export_runtime(args.runtime_root)
            check_separate_root(args.output.parent, args.runtime_root)
            from .decision_journal_store import _check_existing_ancestors, _reject_source_storage
            target = args.output.absolute()
            _check_existing_ancestors(target.parent)
            _reject_source_storage(target.parent)
            from .auto_trading_runtime import RuntimeLedger
            RuntimeLedger(target.parent)  # Also rejects native/journal source trees.
            _immutable(args.output.absolute(), raw)
            output = {"evidence_path": str(args.output.absolute()), "sha256": sha256_bytes(raw), "orders_submitted": 0}
        elif args.command == "install-paper-book":
            from .paper_account_safety import install_paper_book
            output = install_paper_book(args.journal_root, args.ownership_event_id,
                args.reconciliation_event_id, confirm_account_id=args.confirm_account_id)
        else:
            from .trading_reconciliation import (
                build_snapshot_event, evidence_for_snapshot, build_ownership_event, evidence_for_ownership,
                build_reconciliation_event, evidence_for_reconciliation, snapshot_input_from_probe,
            )
            store = JournalStore(args.journal_root)
            events, blobs = _contents(store)
            if args.command == "show":
                event = next((event for event in events if event.event_id == args.event_id), None)
                if event is None:
                    raise ValueError("unknown journal event")
                output = event.to_dict()
            else:
                if args.command in {"import-probe", "import-snapshot"}:
                    source = args.probe if args.command == "import-probe" else args.evidence
                    check_separate_root(store.root, source.absolute().parent)
                    raw = read_regular(source)
                    if args.command == "import-probe":
                        submitted = snapshot_input_from_probe(raw,
                            snapshot_id=args.snapshot_id or "snapshot-" + sha256_bytes(raw),
                            evidence_path="broker_captures/" + sha256_bytes(raw) + ".json")
                    else:
                        submitted = BrokerSnapshotInput.from_bytes(read_regular(args.snapshot))
                    blobs = {**blobs, sha256_bytes(raw): raw}
                    build, retain = build_snapshot_event, evidence_for_snapshot
                elif args.command == "record-ownership":
                    submitted = DeskOwnershipInput.from_bytes(read_regular(args.ownership))
                    if (args.confirm_account_id != submitted.account_id
                            or args.confirm_desk_scope_sha256 != sha256_bytes(canonical_json_bytes(submitted.desks))):
                        raise ValueError("ownership confirmation does not match declared account and scope")
                    build, retain = build_ownership_event, evidence_for_ownership
                else:
                    if args.command == "record-reconciliation":
                        submitted = ReconciliationInput.from_bytes(read_regular(args.reconciliation))
                    else:
                        parent = next((event for event in events if event.event_id == args.snapshot_event_id
                                       and event.event_type == "PAPER_BROKER_SNAPSHOT_RECORDED"), None)
                        if parent is None:
                            raise ValueError("unknown broker snapshot")
                        ownership = next((event for event in events if event.event_id == args.ownership_event_id
                                          and event.event_type == "TRADING_DESK_OWNERSHIP_RECORDED"), None)
                        if args.ownership_event_id and ownership is None:
                            raise ValueError("unknown desk ownership")
                        runtime = read_regular(args.runtime_evidence) if args.runtime_evidence else None
                        submitted = ReconciliationInput.from_mapping({
                            "schema_version": "blackpod.trading_execution_reconciliation.v1",
                            "reconciliation_id": args.reconciliation_id, "recorded_at": args.recorded_at,
                            "mode": "PAPER", "account_id": parent.payload["snapshot"]["account_id"],
                            "broker_snapshot_event_id": parent.event_id,
                            "broker_snapshot_sha256": parent.source["source_sha256"],
                            "ownership_event_id": ownership.event_id if ownership else None,
                            "ownership_sha256": ownership.source["source_sha256"] if ownership else None,
                            "runtime_evidence": {"path": "runtime_exports/" + sha256_bytes(runtime) + ".json",
                                "sha256": sha256_bytes(runtime), "size_bytes": len(runtime)} if runtime is not None else None,
                            "prior_reconciliation_event_id": args.prior_reconciliation_event_id,
                            "scope": "PAPER_RECONCILIATION_ONLY", "realized_trade_pnl": None,
                            "authority": {"authorization_enabled": False, "capital_activation_enabled": False,
                                "execution_enabled": False, "policy_changes_enabled": False},
                        })
                    if args.runtime_evidence:
                        raw = read_regular(args.runtime_evidence)
                        blobs = {**blobs, sha256_bytes(raw): raw}
                    build, retain = build_reconciliation_event, evidence_for_reconciliation
                event = build(submitted, events, blobs)
                result = store.append(event, retain(submitted, events, blobs))
                output = {"event_id": event.event_id, "decision_id": event.decision_id,
                    "written": result.written, "sequence": result.sequence, **event.payload,
                    "orders_submitted": 0}
        print(json.dumps({"command": args.command, **output}, sort_keys=True))
        return 0
    except (ValueError, OSError, JournalStoreError, RecoveryError, TypeError, RecursionError) as exc:
        print("paper-reconciliation: " + str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
