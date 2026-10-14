"""Offline qualification diagnostics for an exact reconciled shadow intake."""
from __future__ import annotations

import argparse
from dataclasses import asdict
import json
from pathlib import Path

from .contracts.mission_request import parse_strict_json_object_bytes
from .contracts.reconciled_shadow_qualification import ReconciledShadowQualificationRequest, REQUEST_CONSTANTS
from .decision_journal_store import JournalStore, JournalStoreError, check_separate_root
from .desk_candidate_review_cli import _write
from .evidence_reconciliation_cli import _LeafReader, _read, _output_guard
from .hashing import canonical_json_bytes

TYPE = "TRADING_RECONCILED_SHADOW_QUALIFICATION_RECORDED"


def _authority():
    return {key: False for key in ("authorization_enabled", "capital_activation_enabled", "execution_enabled", "policy_changes_enabled")}


def load_qualification_evidence(request, retained, root):
    """Read typed result/policy/dataset/mask leaves, never raw-document children."""
    from .contracts.reconciled_action_intake import validate_result
    request = request if isinstance(request, ReconciledShadowQualificationRequest) else ReconciledShadowQualificationRequest.from_mapping(request)
    reader = _LeafReader(retained, root)
    result = validate_result(parse_strict_json_object_bytes(reader.load(request.intake_result_evidence)))
    for reference in (result["policy_evidence"], result["dataset_evidence"], result["original_native_masks"]["evidence"]):
        reader.load(reference)
    return reader.blobs


def build_parser():
    parser = argparse.ArgumentParser(description="Offline reconciled-overlay qualification; auto-trading OFF")
    commands = parser.add_subparsers(dest="command", required=True)
    prepare = commands.add_parser("prepare", help="Write a strict request without reading or claiming verified history")
    for name in ("qualification-id", "recorded-at", "data-cutoff-at"):
        prepare.add_argument("--" + name, required=True)
    prepare.add_argument("--inputs", type=Path, required=True)
    prepare.add_argument("--output", type=Path, required=True)
    for name in ("assess", "record"):
        command = commands.add_parser(name)
        command.add_argument("--request", type=Path, required=True)
        command.add_argument("--journal-root", type=Path, required=True)
        command.add_argument("--evidence-root", type=Path)
        if name == "assess": command.add_argument("--output", type=Path, required=True)
    show = commands.add_parser("show")
    show.add_argument("--event-id", required=True); show.add_argument("--journal-root", type=Path, required=True)
    commands.add_parser("verify").add_argument("--journal-root", type=Path, required=True)
    return parser


def _forbidden(args):
    return [getattr(args, name) for name in ("journal_root", "evidence_root") if getattr(args, name, None) is not None] + [
        getattr(args, name).parent for name in ("request", "inputs") if getattr(args, name, None) is not None]


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        if getattr(args, "output", None) is not None:
            args.output = _output_guard(args.output, _forbidden(args))
        if args.command == "prepare":
            inputs = parse_strict_json_object_bytes(_read(args.inputs))
            if set(inputs) != {"intake_event_id", "intake_result_evidence", "supersedes_event_id"}:
                raise ValueError("prepare inputs require exactly intake_event_id, intake_result_evidence and supersedes_event_id")
            request = ReconciledShadowQualificationRequest.from_mapping({**REQUEST_CONSTANTS, **inputs,
                "qualification_id": args.qualification_id, "recorded_at": args.recorded_at, "data_cutoff_at": args.data_cutoff_at,
                "auto_trading_enabled": False, "authority": _authority()})
            _write(args.output, request.to_bytes(), _forbidden(args))
            output = {"qualification_id": request.qualification_id, "output": str(args.output.absolute()),
                "source_history_verified": False, "assessment_performed": False}
        else:
            store = JournalStore(args.journal_root)
            if args.command == "verify": output = store.verify().to_dict()
            else:
                events, blobs = store.verified_contents()
                if args.command == "show":
                    matches = [event for event in events if event.event_id == args.event_id and event.event_type == TYPE]
                    if len(matches) != 1: raise ValueError("show requires one exact retained reconciled-shadow qualification")
                    output = matches[0].to_dict()
                else:
                    from .reconciled_shadow_qualification_journal import qualification_material
                    check_separate_root(store.root, args.request.parent)
                    if args.evidence_root is not None: check_separate_root(store.root, args.evidence_root)
                    request = ReconciledShadowQualificationRequest.from_bytes(_read(args.request))
                    blobs = load_qualification_evidence(request, blobs, args.evidence_root)
                    material = qualification_material(request, events, blobs)
                    if args.command == "assess":
                        _write(args.output, canonical_json_bytes(material["result"]), _forbidden(args))
                        output = {"qualification_id": request.qualification_id, "status": material["result"]["status"],
                            "output": str(args.output.absolute()), "journal_written": False}
                    else:
                        output = {**asdict(store.append(material["event"], material["evidence"])), "status": material["result"]["status"]}
        output["auto_trading_enabled"] = False; output["provider_api_calls"] = 0
        print(json.dumps(output, sort_keys=True, indent=2)); return 0
    except (OSError, ValueError, JournalStoreError) as exc:
        print(json.dumps({"error": str(exc), "auto_trading_enabled": False}, sort_keys=True)); return 2


if __name__ == "__main__": raise SystemExit(main())
