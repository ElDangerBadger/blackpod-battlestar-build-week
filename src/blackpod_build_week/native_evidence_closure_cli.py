"""Explicit offline native review commands; supplementary claims grant no authority."""
from __future__ import annotations

import argparse
from dataclasses import asdict
import json
from pathlib import Path

from .contracts.native_evidence_closure import (
    REQUEST_VERSION, REVIEW_TYPE, SCOPE,
    NativeEvidenceClosureReviewRequest, NativeEvidenceSupplementalReview,
)
from .contracts.mission_request import parse_strict_json_object_bytes, parse_rfc3339
from .contracts.trading_reconciliation import evidence_reference
from .decision_journal_store import (
    JournalStore, JournalStoreError, check_separate_root, _check_existing_ancestors,
)
from .desk_candidate_review_cli import _write
from .hashing import canonical_json_bytes, sha256_bytes
from .sentry_history_cache import read_regular

MAX_REVIEW_REFERENCES = 256
MAX_REVIEW_BYTES = 64 * 1024 * 1024


def _read(path):
    path = Path(path).absolute()
    if ".." in path.parts:
        raise ValueError("review input paths cannot traverse parents")
    _check_existing_ancestors(path.parent)
    return read_regular(path, max_bytes=MAX_REVIEW_BYTES)


def load_review_evidence(request, retained, root):
    """Load only declared typed leaves, preserving opaque source bytes.

    No URL is fetched and no nested references inside a source body are followed.
    Already retained evidence is verified in place without needing external files.
    """
    request = (request if isinstance(request, NativeEvidenceClosureReviewRequest)
        else NativeEvidenceClosureReviewRequest.from_mapping(request))
    blobs, seen, paths, total = dict(retained), set(), {}, 0
    source_root = None if root is None else Path(root).absolute()
    if source_root is not None:
        if ".." in source_root.parts:
            raise ValueError("review evidence root cannot traverse parents")
        _check_existing_ancestors(source_root)

    def load(reference):
        nonlocal total
        reference = evidence_reference(reference, "review source evidence")
        identity = (reference["path"], reference["sha256"], reference["size_bytes"])
        if reference["path"] in paths and paths[reference["path"]] != identity:
            raise ValueError("review source paths bind conflicting evidence")
        paths[reference["path"]] = identity
        if identity not in seen:
            if len(seen) >= MAX_REVIEW_REFERENCES or total + reference["size_bytes"] > MAX_REVIEW_BYTES:
                raise ValueError("review evidence exceeds its reference or combined-byte bound")
            seen.add(identity)
            total += reference["size_bytes"]
            if reference["sha256"] not in blobs:
                if source_root is None:
                    raise ValueError("unretained review evidence requires an explicit evidence root")
                blobs[reference["sha256"]] = _read(source_root / reference["path"])
        raw = blobs.get(reference["sha256"])
        if not isinstance(raw, bytes) or len(raw) != reference["size_bytes"] or sha256_bytes(raw) != reference["sha256"]:
            raise ValueError("review evidence differs in hash or size")
        return raw

    if request.supplemental_review_evidence is not None:
        supplemental = NativeEvidenceSupplementalReview.from_bytes(load(request.supplemental_review_evidence))
        for category in supplemental.categories:
            for declaration in category["source_documents"]:
                load(declaration["evidence"])
    return blobs


def build_parser():
    parser = argparse.ArgumentParser(
        description="Descriptive native evidence review; offline, auto-trading OFF")
    commands = parser.add_subparsers(dest="command", required=True)
    prepare = commands.add_parser("prepare", help="Write a strict review request without assessing evidence")
    for name in ("review-id", "recorded-at", "data-cutoff-at", "anchor-qualification-event-id"):
        prepare.add_argument("--" + name, required=True)
    prepare.add_argument("--candidate-qualification-event-id")
    prepare.add_argument("--supersedes-event-id")
    prepare.add_argument("--inputs", type=Path,
        help="Exact JSON object containing supplemental_review_evidence (nullable)")
    prepare.add_argument("--output", type=Path, required=True)
    prepare.add_argument("--journal-root", type=Path, required=True)
    for name in ("assess", "record"):
        command = commands.add_parser(name,
            help="Write a descriptive report" if name == "assess" else "Append an immutable descriptive review")
        command.add_argument("--request", type=Path, required=True)
        command.add_argument("--evidence-root", type=Path)
        command.add_argument("--journal-root", type=Path, required=True)
        if name == "assess":
            command.add_argument("--output", type=Path, required=True)
    commands.add_parser("verify").add_argument("--journal-root", type=Path, required=True)
    show = commands.add_parser("show")
    show.add_argument("--journal-root", type=Path, required=True)
    show.add_argument("--event-id", required=True)
    return parser


def _prepare(args, store, events):
    inputs = {"supplemental_review_evidence": None}
    if args.inputs is not None:
        check_separate_root(store.root, args.inputs.parent)
        inputs = parse_strict_json_object_bytes(_read(args.inputs))
        if set(inputs) != {"supplemental_review_evidence"}:
            raise ValueError("prepare inputs require only supplemental_review_evidence")
    request = NativeEvidenceClosureReviewRequest.from_mapping({
        "schema_version": REQUEST_VERSION, "review_id": args.review_id,
        "recorded_at": args.recorded_at, "data_cutoff_at": args.data_cutoff_at,
        "domain": "TRADING", "mode": "SHADOW_RESEARCH", "scope": SCOPE,
        "anchor_qualification_event_id": args.anchor_qualification_event_id,
        "candidate_qualification_event_id": args.candidate_qualification_event_id,
        "supplemental_review_evidence": inputs["supplemental_review_evidence"],
        "supersedes_event_id": args.supersedes_event_id, "auto_trading_enabled": False,
        "authority": {key: False for key in ("authorization_enabled", "capital_activation_enabled",
            "execution_enabled", "policy_changes_enabled")}})
    indices = {}
    for identity in (request.anchor_qualification_event_id, request.candidate_qualification_event_id):
        if identity is None:
            continue
        selected = [event for event in events if event.event_id == identity
            and event.event_type == "SEGMENTED_TRAIN_EVIDENCE_QUALIFICATION_RECORDED"
            and event.domain == "TRADING"]
        if len(selected) != 1:
            raise ValueError("prepare requires exact retained native qualification identities")
        if parse_rfc3339(selected[0].recorded_at, "native source clock") > parse_rfc3339(request.data_cutoff_at, "review cutoff"):
            raise ValueError("prepare cutoff excludes a selected native qualification")
        indices[identity] = events.index(selected[0])
    if request.candidate_qualification_event_id is not None and indices[request.candidate_qualification_event_id] <= indices[request.anchor_qualification_event_id]:
        raise ValueError("prepare candidate must be a later retained native qualification")
    forbidden = [store.root] + ([] if args.inputs is None else [args.inputs.parent])
    _write(args.output, request.to_bytes(), forbidden)
    return {"review_id": request.review_id, "output": str(args.output.absolute()),
        "assessment_performed": False, "supplemental_sources_loaded": False}


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        store = JournalStore(args.journal_root)
        if args.command == "verify":
            output = store.verify().to_dict()
        else:
            events, blobs = store.verified_contents()
            if args.command == "prepare":
                output = _prepare(args, store, events)
            elif args.command == "show":
                matches = [event for event in events if event.event_id == args.event_id
                    and event.event_type == REVIEW_TYPE]
                if len(matches) != 1:
                    raise ValueError("show requires an exact retained native evidence review")
                output = matches[0].to_dict()
            else:
                check_separate_root(store.root, args.request.parent)
                if args.evidence_root is not None:
                    check_separate_root(store.root, args.evidence_root)
                request = NativeEvidenceClosureReviewRequest.from_bytes(_read(args.request))
                blobs = load_review_evidence(request, blobs, args.evidence_root)
                if args.command == "assess":
                    from .native_evidence_closure import review_native_evidence_closure
                    material = review_native_evidence_closure(request, events, blobs)
                    _write(args.output, canonical_json_bytes(material["result"]),
                        [store.root, args.request.parent] + ([] if args.evidence_root is None else [args.evidence_root]))
                    output = {"review_id": request.review_id, "status": material["result"]["status"],
                        "output": str(args.output.absolute()), "native_gates_changed": False}
                else:
                    from .native_evidence_closure_journal import review_material
                    material = review_material(request, events, blobs)
                    output = {**asdict(store.append(material["event"], material["evidence"])),
                        "status": material["result"]["status"], "native_gates_changed": False}
        output["provider_calls"] = 0
        output["auto_trading_enabled"] = False
        print(json.dumps(output, sort_keys=True, indent=2))
        return 0
    except (OSError, ValueError, JournalStoreError) as exc:
        print(json.dumps({"error": str(exc), "auto_trading_enabled": False}, sort_keys=True))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
