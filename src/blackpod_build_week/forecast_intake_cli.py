"""Explicit provider-free forecast assessment and append-only journal commands."""
import argparse
import json
from pathlib import Path
import sys

from .contracts.forecast_intake import ForecastIntake
from .decision_journal_store import JournalStore, JournalStoreError, check_separate_root
from .desk_candidate_review_cli import _references, load_evidence
from .forecast_intake import evidence_for_forecast_intake
from .forecast_journal import build_forecast_intake_event
from .sentry_history_cache import read_regular, RecoveryError


def build_parser():
    parser = argparse.ArgumentParser(description="Governed SHADOW forecast intake; no inference, orders or activation")
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("assess", "record"):
        sub = commands.add_parser(name)
        sub.add_argument("--journal-root", type=Path, required=True)
        sub.add_argument("--intake", type=Path, required=True)
        sub.add_argument("--evidence-root", type=Path)
    show = commands.add_parser("show")
    show.add_argument("--journal-root", type=Path, required=True)
    show.add_argument("--event-id", required=True)
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        store = JournalStore(args.journal_root)
        events, blobs = store.verified_contents() if store.root.exists() else ((), {})
        if args.command == "show":
            event = next((item for item in events if item.event_id == args.event_id and item.event_type == "FORECAST_INTAKE_RECORDED"), None)
            if event is None:
                raise ValueError("unknown verified forecast intake")
            output = event.to_dict()
        else:
            intake = ForecastIntake.from_bytes(read_regular(args.intake))
            if args.evidence_root is not None:
                check_separate_root(store.root, args.evidence_root)
                blobs = load_evidence(args.evidence_root, _references(intake.to_dict()), blobs)
            event = build_forecast_intake_event(intake, events, blobs)
            output = {"event_id": event.event_id, "decision_id": event.decision_id, **event.payload}
            if args.command == "record":
                appended = store.append(event, evidence_for_forecast_intake(intake, blobs))
                output.update(written=appended.written, sequence=appended.sequence)
        print(json.dumps({"command": args.command, **output, "orders_submitted": 0, "inference_calls": 0,
            "auto_trading_changed": False}, sort_keys=True))
        return 0
    except (ValueError, OSError, JournalStoreError, RecoveryError, TypeError, RecursionError) as exc:
        print("forecast-intake: " + str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
