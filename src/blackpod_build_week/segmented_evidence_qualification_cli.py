"""Explicit offline segmented qualification; never performs capture or trading."""
import argparse
from dataclasses import asdict
import json
from pathlib import Path

from .contracts.segmented_evidence_qualification import (
    BINDING_VERSION, BINDING_TYPE, ASSESSMENT_TYPE,
    SegmentedEvidenceBinding, SegmentedEvidenceQualificationRequest,
)
from .decision_journal_store import (
    JournalStore, JournalStoreError, check_separate_root, _check_existing_ancestors,
)
from .desk_candidate_review_cli import _write
from .hashing import canonical_json_bytes
from .sentry_history_cache import read_regular
from .segmented_evidence_qualification import binding_context, qualify_segmented_evidence
from .segmented_evidence_qualification_journal import binding_material, qualification_material


def _read(path):
    path = Path(path).absolute()
    if ".." in path.parts:
        raise ValueError("input paths cannot traverse parents")
    _check_existing_ancestors(path.parent)
    return read_regular(path, max_bytes=64 * 1024 * 1024)


def build_parser():
    parser = argparse.ArgumentParser(
        description="Offline segmented TRAIN-evidence qualification; auto-trading OFF")
    commands = parser.add_subparsers(dest="command", required=True)
    prepare = commands.add_parser("prepare", help="Bind an existing frozen design and capture plan")
    for name in ("binding-id", "recorded-at", "qualification-policy-event-id", "capture-plan-event-id"):
        prepare.add_argument("--" + name, required=True)
    prepare.add_argument("--supersedes-binding-event-id")
    prepare.add_argument("--output", type=Path, required=True)
    prepare.add_argument("--journal-root", type=Path, required=True)
    register = commands.add_parser("register", help="Append an immutable input-method binding")
    register.add_argument("--binding", type=Path, required=True)
    register.add_argument("--journal-root", type=Path, required=True)
    for name in ("assess", "record"):
        command = commands.add_parser(name,
            help="Compute an offline report" if name == "assess" else "Append a linked qualification")
        command.add_argument("--request", type=Path, required=True)
        command.add_argument("--journal-root", type=Path, required=True)
        if name == "assess":
            command.add_argument("--output", type=Path, required=True)
    commands.add_parser("verify").add_argument("--journal-root", type=Path, required=True)
    show = commands.add_parser("show")
    show.add_argument("--journal-root", type=Path, required=True)
    show.add_argument("--event-id", required=True)
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        store = JournalStore(args.journal_root)
        if args.command == "verify":
            output = store.verify().to_dict()
        else:
            events, blobs = store.verified_contents()
            if args.command == "prepare":
                authority = {key: False for key in (
                    "authorization_enabled", "capital_activation_enabled",
                    "execution_enabled", "policy_changes_enabled")}
                binding = SegmentedEvidenceBinding.from_mapping({
                    "schema_version": BINDING_VERSION,
                    "binding_id": args.binding_id, "recorded_at": args.recorded_at,
                    "domain": "TRADING", "mode": "SHADOW_RESEARCH",
                    "scope": "SEGMENTED_TRAIN_EVIDENCE_QUALIFICATION_ONLY",
                    "calibration_source": "VERIFIED_SEGMENTED_TRAIN_EXPORT_ONLY",
                    "qualification_policy_event_id": args.qualification_policy_event_id,
                    "capture_plan_event_id": args.capture_plan_event_id,
                    "supersedes_binding_event_id": args.supersedes_binding_event_id,
                    "auto_trading_enabled": False, "authority": authority})
                binding_context(binding, events, blobs)
                _write(args.output, binding.to_bytes(), [store.root])
                output = {"binding_id": binding.binding_id, "output": str(args.output.absolute()),
                    "calibration_performed": False, "provider_calls": 0}
            elif args.command == "register":
                check_separate_root(store.root, args.binding.parent)
                binding = SegmentedEvidenceBinding.from_bytes(_read(args.binding))
                material = binding_material(binding, events, blobs)
                output = asdict(store.append(material["event"], material["evidence"]))
            elif args.command == "show":
                matches = [event for event in events if event.event_id == args.event_id
                    and event.event_type in {BINDING_TYPE, ASSESSMENT_TYPE}]
                if len(matches) != 1:
                    raise ValueError("show requires an exact retained segmented qualification record")
                output = matches[0].to_dict()
            else:
                check_separate_root(store.root, args.request.parent)
                request = SegmentedEvidenceQualificationRequest.from_bytes(_read(args.request))
                if args.command == "assess":
                    material = qualify_segmented_evidence(request, events, blobs)
                    _write(args.output, canonical_json_bytes(material["result"]),
                        [store.root, args.request.parent])
                    output = {"qualification_id": request.qualification_id,
                        "status": material["result"]["status"], "output": str(args.output.absolute()),
                        "provider_calls": 0}
                else:
                    material = qualification_material(request, events, blobs)
                    output = {**asdict(store.append(material["event"], material["evidence"])),
                        "status": material["result"]["status"], "provider_calls": 0}
        output["auto_trading_enabled"] = False
        print(json.dumps(output, sort_keys=True, indent=2))
        return 0
    except (OSError, ValueError, JournalStoreError) as exc:
        print(json.dumps({"error": str(exc), "auto_trading_enabled": False}, sort_keys=True))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
