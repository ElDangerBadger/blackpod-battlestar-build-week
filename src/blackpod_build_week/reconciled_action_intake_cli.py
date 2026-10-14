"""Explicit offline frozen-policy and candidate-intake lifecycle."""
from __future__ import annotations

import argparse
from dataclasses import asdict
import json
from pathlib import Path

from .contracts.mission_request import parse_strict_json_object_bytes
from .contracts.reconciled_action_intake import (
    ReconciledActionIntakePolicy, ReconciledActionIntakeRequest, REQUEST_CONSTANTS, AUTHORITY,
)
from .contracts.reconciled_action_journal import POLICY_TYPE, INTAKE_TYPE
from .decision_journal_store import JournalStore, JournalStoreError, check_separate_root
from .desk_candidate_review_cli import _write
from .evidence_reconciliation_cli import _LeafReader, _read, _output_guard
from .hashing import canonical_json_bytes


def _inventories(reader, references):
    from .contracts.effective_date_reconciliation import IndependentActionInventory, INVENTORY_VERSION
    from .contracts.qqq_distribution_inventory import QQQDistributionInventory, VERSION as QQQ_VERSION
    for reference in references:
        raw = reader.load(reference)
        declaration = parse_strict_json_object_bytes(raw)
        version = declaration.get("schema_version")
        if version == QQQ_VERSION:
            inventory = QQQDistributionInventory.from_mapping(declaration)
            leaves = [inventory.body_evidence, inventory.receipt_evidence, inventory.discovery_evidence]
        elif version == INVENTORY_VERSION:
            inventory = IndependentActionInventory.from_mapping(declaration)
            leaves = [inventory.body_evidence, *inventory.supporting_evidence]
        else:
            raise ValueError("unsupported typed reconciled inventory schema")
        for leaf in leaves: reader.load(leaf)


def load_inventory_evidence(references, retained, root):
    """Read only typed manifest leaves; raw source bytes remain opaque here."""
    if not isinstance(references, list) or not 0 < len(references) <= 16:
        raise ValueError("independent inventories require one to sixteen explicit references")
    reader = _LeafReader(retained, root)
    _inventories(reader, references)
    return reader.blobs


def _policy_sources(reader, policy):
    for field in ("dataset_evidence", "native_continuity_export_evidence", "original_native_masks_evidence"):
        reader.load(getattr(policy, field))
    _inventories(reader, policy.independent_inventories)


def load_policy_evidence(policy, retained, root):
    policy = policy if isinstance(policy, ReconciledActionIntakePolicy) else ReconciledActionIntakePolicy.from_mapping(policy)
    reader = _LeafReader(retained, root)
    _policy_sources(reader, policy)
    return reader.blobs


def load_intake_evidence(request, retained, root):
    request = request if isinstance(request, ReconciledActionIntakeRequest) else ReconciledActionIntakeRequest.from_mapping(request)
    reader = _LeafReader(retained, root)
    policy = ReconciledActionIntakePolicy.from_bytes(reader.load(request.policy_evidence))
    _policy_sources(reader, policy)
    return reader.blobs


def build_parser():
    parser = argparse.ArgumentParser(description="Offline reconciled action candidates; auto-trading OFF")
    commands = parser.add_subparsers(dest="command", required=True)
    policy = commands.add_parser("prepare-policy", help="Write a frozen policy bundle without journal publication")
    for name in ("anchor-review-event-id", "policy-id", "recorded-at"):
        policy.add_argument("--" + name, required=True)
    policy.add_argument("--journal-root", type=Path, required=True)
    policy.add_argument("--inputs", type=Path, required=True)
    policy.add_argument("--evidence-root", type=Path)
    policy.add_argument("--output-directory", type=Path, required=True)
    register = commands.add_parser("register-policy")
    register.add_argument("--policy", type=Path, required=True)
    register.add_argument("--journal-root", type=Path, required=True)
    register.add_argument("--evidence-root", type=Path)
    prepare = commands.add_parser("prepare", help="Write a strict request without reading source history")
    for name in ("intake-id", "recorded-at", "data-cutoff-at"):
        prepare.add_argument("--" + name, required=True)
    prepare.add_argument("--inputs", type=Path, required=True)
    prepare.add_argument("--output", type=Path, required=True)
    for name in ("assess", "record"):
        command = commands.add_parser(name)
        command.add_argument("--request", type=Path, required=True)
        command.add_argument("--journal-root", type=Path, required=True)
        command.add_argument("--evidence-root", type=Path)
        if name == "assess": command.add_argument("--output", type=Path, required=True)
    commands.add_parser("verify").add_argument("--journal-root", type=Path, required=True)
    show = commands.add_parser("show")
    show.add_argument("--journal-root", type=Path, required=True)
    show.add_argument("--event-id", required=True)
    return parser


def _forbidden(args):
    return [getattr(args, name) for name in ("journal_root", "evidence_root") if getattr(args, name, None) is not None] + [
        getattr(args, name).parent for name in ("inputs", "request", "policy") if getattr(args, name, None) is not None]


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        from .reconciled_action_journal import prepare_policy, policy_material, intake_material, POLICY_PATH
        if getattr(args, "output", None) is not None:
            args.output = _output_guard(args.output, _forbidden(args))
        if getattr(args, "output_directory", None) is not None:
            # The complete destination is rejected before an expensive scan.
            _output_guard(args.output_directory / POLICY_PATH, _forbidden(args))
        if args.command == "prepare":
            inputs = parse_strict_json_object_bytes(_read(args.inputs))
            if set(inputs) != {"policy_event_id", "policy_evidence", "supersedes_event_id"}:
                raise ValueError("prepare inputs require exactly policy_event_id, policy_evidence and supersedes_event_id")
            request = ReconciledActionIntakeRequest.from_mapping({**REQUEST_CONSTANTS, **inputs,
                "intake_id": args.intake_id, "recorded_at": args.recorded_at, "data_cutoff_at": args.data_cutoff_at,
                "auto_trading_enabled": False, "authority": dict(AUTHORITY)})
            _write(args.output, request.to_bytes(), _forbidden(args))
            output = {"intake_id": request.intake_id, "output": str(args.output.absolute()), "source_history_verified": False,
                "assessment_performed": False}
        else:
            store = JournalStore(args.journal_root)
            if args.command == "verify": output = store.verify().to_dict()
            else:
                events, blobs = store.verified_contents()
                if args.command == "show":
                    matches = [event for event in events if event.event_id == args.event_id and event.event_type in {POLICY_TYPE, INTAKE_TYPE}]
                    if len(matches) != 1: raise ValueError("show requires one exact retained reconciled policy or intake")
                    output = matches[0].to_dict()
                elif args.command == "prepare-policy":
                    check_separate_root(store.root, args.inputs.parent)
                    if args.evidence_root is not None: check_separate_root(store.root, args.evidence_root)
                    inputs = parse_strict_json_object_bytes(_read(args.inputs))
                    if set(inputs) != {"independent_inventories"}:
                        raise ValueError("policy inputs require exactly independent_inventories")
                    blobs = load_inventory_evidence(inputs["independent_inventories"], blobs, args.evidence_root)
                    material = prepare_policy(args.anchor_review_event_id, args.policy_id, args.recorded_at,
                        inputs["independent_inventories"], events, blobs)
                    bundle = args.output_directory.absolute()
                    for path, raw in material["evidence"].items():
                        _write(bundle / path, raw, _forbidden(args))
                    output = {"policy_id": material["policy"].policy_id, "status": material["policy"].status,
                        "policy_path": str(bundle / POLICY_PATH), "evidence_root": str(bundle), "source_history_verified": True,
                        "assessment_performed": False, "journal_written": False}
                elif args.command == "register-policy":
                    check_separate_root(store.root, args.policy.parent)
                    if args.evidence_root is not None: check_separate_root(store.root, args.evidence_root)
                    policy = ReconciledActionIntakePolicy.from_bytes(_read(args.policy))
                    blobs = load_policy_evidence(policy, blobs, args.evidence_root)
                    material = policy_material(policy, events, blobs)
                    output = {**asdict(store.append(material["event"], material["evidence"])), "status": policy.status}
                else:
                    check_separate_root(store.root, args.request.parent)
                    if args.evidence_root is not None: check_separate_root(store.root, args.evidence_root)
                    request = ReconciledActionIntakeRequest.from_bytes(_read(args.request))
                    blobs = load_intake_evidence(request, blobs, args.evidence_root)
                    material = intake_material(request, events, blobs)
                    if args.command == "assess":
                        _write(args.output, canonical_json_bytes(material["result"]), _forbidden(args))
                        output = {"intake_id": request.intake_id, "status": material["result"]["status"],
                            "output": str(args.output.absolute()), "journal_written": False}
                    else:
                        output = {**asdict(store.append(material["event"], material["evidence"])), "status": material["result"]["status"]}
        output["auto_trading_enabled"] = False
        output["provider_api_calls"] = 0
        print(json.dumps(output, sort_keys=True, indent=2)); return 0
    except (OSError, ValueError, JournalStoreError) as exc:
        print(json.dumps({"error": str(exc), "auto_trading_enabled": False}, sort_keys=True)); return 2


if __name__ == "__main__": raise SystemExit(main())
