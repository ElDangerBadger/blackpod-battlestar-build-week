"""Explicit offline independent-evidence review; no native gate or execution rights."""
from __future__ import annotations

import argparse
from dataclasses import asdict
import json
from pathlib import Path
import stat

from .contracts.evidence_reconciliation import EvidenceReconciliationRequest
from .contracts.mission_request import parse_strict_json_object_bytes
from .contracts.trading_reconciliation import evidence_reference
from .decision_journal_store import JournalStore, JournalStoreError, check_separate_root, _check_existing_ancestors
from .desk_candidate_review_cli import _write
from .hashing import canonical_json_bytes, sha256_bytes
from .sentry_history_cache import read_regular

MAX_REFERENCES = 8192
MAX_BYTES = 64 * 1024 * 1024
MODES = ("SHADOW_RESEARCH", "PAPER_SIMULATION", "LIVE_BROKERAGE")
REVIEW_TYPE = "TRADING_INDEPENDENT_EVIDENCE_RECONCILIATION_RECORDED"


def _authority():
    return {key: False for key in ("authorization_enabled", "capital_activation_enabled", "execution_enabled", "policy_changes_enabled")}


def _read(path):
    path = Path(path).absolute()
    if ".." in path.parts: raise ValueError("reconciliation inputs cannot traverse parents")
    _check_existing_ancestors(path.parent)
    return read_regular(path, max_bytes=MAX_BYTES)


def _output_guard(target, forbidden):
    """Reject protected destinations before expensive source verification."""
    from .decision_journal_store import _reject_source_storage
    target = Path(target).absolute()
    if ".." in target.parts: raise ValueError("output cannot traverse parents")
    for source in forbidden: check_separate_root(target.parent, Path(source).absolute())
    _check_existing_ancestors(target.parent); _reject_source_storage(target.parent)
    package = Path(__file__).absolute().parents[2]
    for ancestor in (target.parent, *target.parent.parents):
        if any((ancestor / name).exists() for name in ("ledger.lock", "worker.lock", ".journal.lock")):
            raise ValueError("output must be separate from journal and installed trading runtime storage")
        if ancestor.name == ".git": raise ValueError("output cannot write repository metadata")
        if (ancestor / ".git").exists():
            if ancestor == package and target.relative_to(ancestor).parts[:1] == ("output",): break
            raise ValueError("output cannot write repository source trees")
    try: details = target.lstat()
    except FileNotFoundError: return target
    if not stat.S_ISREG(details.st_mode) or details.st_nlink != 1:
        raise ValueError("output must be a regular file without symlinks or hardlinks")
    return target


class _LeafReader:
    def __init__(self, retained, root):
        self.blobs, self.paths, self.seen, self.total = dict(retained), {}, set(), 0
        self.root = None if root is None else Path(root).absolute()
        if self.root is not None:
            if ".." in self.root.parts: raise ValueError("evidence root cannot traverse parents")
            _check_existing_ancestors(self.root)

    def load(self, reference):
        reference = evidence_reference(reference, "reconciliation evidence")
        identity = (reference["path"], reference["sha256"], reference["size_bytes"])
        if reference["path"] in self.paths and self.paths[reference["path"]] != identity:
            raise ValueError("reconciliation evidence path binds conflicting identities")
        self.paths[reference["path"]] = identity
        if identity not in self.seen:
            if len(self.seen) >= MAX_REFERENCES or self.total + reference["size_bytes"] > MAX_BYTES:
                raise ValueError("reconciliation evidence exceeds reference or combined-byte bound")
            self.seen.add(identity); self.total += reference["size_bytes"]
            if reference["sha256"] not in self.blobs:
                if self.root is None: raise ValueError("unretained evidence requires an explicit evidence root")
                self.blobs[reference["sha256"]] = _read(self.root / reference["path"])
        raw = self.blobs.get(reference["sha256"])
        if not isinstance(raw, bytes) or len(raw) != reference["size_bytes"] or sha256_bytes(raw) != reference["sha256"]:
            raise ValueError("reconciliation source differs in hash or size")
        return raw


def load_review_evidence(request, retained, root):
    """Follow typed relationships only; source documents and account bytes stay opaque."""
    from .contracts.effective_date_reconciliation import EffectiveDateReconciliationRequest, IndependentActionInventory
    from .contracts.historical_feed_cost_applicability import HistoricalFeedCostApplicabilityPacket, HistoricalFeedCostContext
    request = request if isinstance(request, EvidenceReconciliationRequest) else EvidenceReconciliationRequest.from_mapping(request)
    reader = _LeafReader(retained, root)
    effective = EffectiveDateReconciliationRequest.from_bytes(reader.load(request.effective_date_request_evidence))
    reader.load(effective.dataset_evidence); reader.load(effective.native_continuity_export_evidence)
    for reference in effective.independent_inventories:
        inventory = IndependentActionInventory.from_bytes(reader.load(reference))
        reader.load(inventory.body_evidence)
        for reference in inventory.supporting_evidence: reader.load(reference)
    packet = HistoricalFeedCostApplicabilityPacket.from_bytes(reader.load(request.applicability_packet_evidence))
    context = HistoricalFeedCostContext.from_bytes(reader.load(packet.context_evidence))
    for field in ("dataset_evidence", "bars_receipt_evidence", "capture_plan_evidence"):
        reader.load(getattr(context, field))
    for reference in context.quote_receipt_evidence: reader.load(reference)
    if context.account_evidence is not None: reader.load(context.account_evidence)
    for document in packet.source_documents: reader.load(document["evidence"])
    for category in packet.categories:
        for assertion in category["assertions"]:
            reference = assertion["scope"]["account_evidence"]
            if reference is not None: reader.load(reference)
    if request.account_profile_evidence is not None: reader.load(request.account_profile_evidence)
    return reader.blobs


def build_parser():
    parser = argparse.ArgumentParser(description="Offline independent evidence reconciliation; auto-trading OFF")
    commands = parser.add_subparsers(dest="command", required=True)
    prepare = commands.add_parser("prepare", help="Write a strict request without reading source history")
    for name in ("review-id", "recorded-at", "data-cutoff-at", "anchor-review-event-id"):
        prepare.add_argument("--" + name, required=True)
    prepare.add_argument("--declared-evaluation-mode", choices=MODES, required=True, help="Research applicability target only; never an execution switch")
    prepare.add_argument("--inputs", type=Path, required=True)
    prepare.add_argument("--supersedes-event-id")
    prepare.add_argument("--output", type=Path, required=True)
    context = commands.add_parser("context", help="Export source-bound metadata before authoring its applicability packet")
    context.add_argument("--journal-root", type=Path, required=True)
    context.add_argument("--anchor-review-event-id", required=True)
    context.add_argument("--recorded-at", required=True)
    context.add_argument("--declared-evaluation-mode", choices=MODES, required=True)
    context.add_argument("--inputs", type=Path)
    context.add_argument("--evidence-root", type=Path)
    context.add_argument("--output", type=Path, required=True)
    for name in ("assess", "record"):
        command = commands.add_parser(name)
        command.add_argument("--request", type=Path, required=True)
        command.add_argument("--journal-root", type=Path, required=True)
        command.add_argument("--evidence-root", type=Path)
        if name == "assess": command.add_argument("--output", type=Path, required=True)
    commands.add_parser("verify").add_argument("--journal-root", type=Path, required=True)
    show = commands.add_parser("show")
    show.add_argument("--journal-root", type=Path, required=True); show.add_argument("--event-id", required=True)
    return parser


def _prepare(args):
    inputs = parse_strict_json_object_bytes(_read(args.inputs))
    if set(inputs) != {"effective_date_request_evidence", "applicability_packet_evidence", "account_profile_evidence"}:
        raise ValueError("prepare inputs require exactly effective_date_request_evidence, applicability_packet_evidence and account_profile_evidence")
    request = EvidenceReconciliationRequest.from_mapping({
        "schema_version": "blackpod.independent_evidence_reconciliation_request.v1", "review_id": args.review_id,
        "recorded_at": args.recorded_at, "data_cutoff_at": args.data_cutoff_at,
        "domain": "TRADING", "mode": "SHADOW_RESEARCH", "scope": "INDEPENDENT_EVIDENCE_RECONCILIATION_ONLY",
        "anchor_review_event_id": args.anchor_review_event_id, **inputs,
        "declared_evaluation_mode": args.declared_evaluation_mode, "supersedes_event_id": args.supersedes_event_id,
        "auto_trading_enabled": False, "authority": _authority()})
    _write(args.output, request.to_bytes(), (args.inputs.parent,))
    return {"review_id": request.review_id, "output": str(args.output.absolute()),
        "source_history_verified": False, "assessment_performed": False}


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        if hasattr(args, "output"):
            forbidden = [getattr(args, name) for name in ("journal_root", "evidence_root") if getattr(args, name, None) is not None]
            forbidden += [getattr(args, name).parent for name in ("request", "inputs") if getattr(args, name, None) is not None]
            args.output = _output_guard(args.output, forbidden)
        if args.command == "prepare": output = _prepare(args)
        else:
            store = JournalStore(args.journal_root)
            if args.command == "verify": output = store.verify().to_dict()
            else:
                events, blobs = store.verified_contents()
                if args.command == "show":
                    matches = [event for event in events if event.event_id == args.event_id and event.event_type == REVIEW_TYPE]
                    if len(matches) != 1: raise ValueError("show requires an exact retained independent reconciliation record")
                    output = matches[0].to_dict()
                elif args.command == "context":
                    from .evidence_reconciliation import build_source_context
                    account = None
                    if args.inputs is not None:
                        check_separate_root(store.root, args.inputs.parent)
                        value = parse_strict_json_object_bytes(_read(args.inputs))
                        if set(value) != {"account_profile_evidence"}: raise ValueError("context inputs require only account_profile_evidence")
                        account = value["account_profile_evidence"]
                    if args.evidence_root is not None: check_separate_root(store.root, args.evidence_root)
                    reader = _LeafReader(blobs, args.evidence_root)
                    if account is not None: reader.load(account)
                    material = build_source_context(args.anchor_review_event_id, events, reader.blobs,
                        recorded_at=args.recorded_at, declared_evaluation_mode=args.declared_evaluation_mode, account_profile_evidence=account)
                    forbidden = [store.root] + ([] if args.inputs is None else [args.inputs.parent]) + ([] if args.evidence_root is None else [args.evidence_root])
                    _write(args.output, material["context"].to_bytes(), forbidden)
                    output = {"output": str(args.output.absolute()), "assessment_performed": False,
                        "source_history_verified": True, "source_authentication_verified": False}
                else:
                    check_separate_root(store.root, args.request.parent)
                    if args.evidence_root is not None: check_separate_root(store.root, args.evidence_root)
                    request = EvidenceReconciliationRequest.from_bytes(_read(args.request))
                    blobs = load_review_evidence(request, blobs, args.evidence_root)
                    if args.command == "assess":
                        from .evidence_reconciliation import assess_evidence_reconciliation
                        material = assess_evidence_reconciliation(request, events, blobs)
                        _write(args.output, canonical_json_bytes(material["result"]), [store.root, args.request.parent] + ([] if args.evidence_root is None else [args.evidence_root]))
                        output = {"review_id": request.review_id, "status": material["result"]["status"], "output": str(args.output.absolute()), "native_gates_changed": False}
                    else:
                        from .evidence_reconciliation_journal import review_material
                        material = review_material(request, events, blobs)
                        output = {**asdict(store.append(material["event"], material["evidence"])), "status": material["result"]["status"], "native_gates_changed": False}
        output["provider_calls"] = 0; output["auto_trading_enabled"] = False
        print(json.dumps(output, sort_keys=True, indent=2)); return 0
    except (OSError, ValueError, JournalStoreError) as exc:
        print(json.dumps({"error": str(exc), "auto_trading_enabled": False}, sort_keys=True)); return 2


if __name__ == "__main__": raise SystemExit(main())
