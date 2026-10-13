"""Offline TRAIN export commands and one explicit, bounded market GET action."""
import argparse
from dataclasses import asdict
from datetime import datetime, timezone
import json
from pathlib import Path

from .contracts.train_market_evidence import TrainMarketCapturePlan, TrainMarketCaptureSnapshot, TrainMarketSegmentRequest, TrainMarketExportRequest, PLAN_TYPE, SEGMENT_TYPE, EXPORT_TYPE
from .contracts.trading_continuity_intake import ContinuityCoverageReview
from .contracts.mission_request import parse_strict_json_object_bytes
from .decision_journal_store import JournalStore, JournalStoreError, check_separate_root, _check_existing_ancestors
from .desk_candidate_review_cli import _write
from .sentry_history_cache import read_regular
from .hashing import sha256_bytes, canonical_json_bytes
from .train_market_evidence import prepare_capture_plan, registered_capture_context, _blob
from .train_market_evidence_journal import capture_plan_material, segment_material, export_material


def _read(path, maximum=64 * 1024 * 1024):
    path = Path(path).absolute()
    if ".." in path.parts: raise ValueError("input paths cannot traverse parents")
    _check_existing_ancestors(path.parent)
    return read_regular(path, max_bytes=maximum)


def _now(): return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def build_parser():
    parser = argparse.ArgumentParser(description="Governed TRAIN market GET capture/export; auto-trading OFF")
    commands = parser.add_subparsers(dest="command", required=True)
    prepare = commands.add_parser("prepare")
    for name in ("capture-id", "created-at", "base-plan-event-id"): prepare.add_argument("--" + name, required=True)
    prepare.add_argument("--fold-id", action="append")
    prepare.add_argument("--limits", type=Path)
    prepare.add_argument("--output", type=Path, required=True)
    prepare.add_argument("--journal-root", type=Path, required=True)
    register = commands.add_parser("register")
    register.add_argument("--plan", type=Path, required=True); register.add_argument("--journal-root", type=Path, required=True)
    capture = commands.add_parser("capture", help="The only command permitted to perform fixed market-data GETs")
    capture.add_argument("--plan-event-id", required=True); capture.add_argument("--journal-root", type=Path, required=True)
    capture.add_argument("--capture-root", type=Path, required=True); capture.add_argument("--credential-source", type=Path, required=True)
    capture.add_argument("--credential-format", choices=("GALACTICA_YAML", "PAPER_ENV", "NAVIGATOR_ENV"), required=True)
    capture.add_argument("--request-budget", type=int)
    capture.add_argument("--allow-market-data-get", action="store_true", required=True)
    snapshot = commands.add_parser("snapshot")
    snapshot.add_argument("--plan-event-id", required=True); snapshot.add_argument("--journal-root", type=Path, required=True)
    snapshot.add_argument("--capture-root", type=Path, required=True); snapshot.add_argument("--exported-at", required=True)
    snapshot.add_argument("--output", type=Path, required=True)
    export = commands.add_parser("export")
    export.add_argument("--snapshot", type=Path, required=True); export.add_argument("--evidence-root", type=Path, required=True)
    export.add_argument("--plan-event-id", required=True); export.add_argument("--journal-root", type=Path, required=True)
    export.add_argument("--export-id", required=True); export.add_argument("--output", type=Path, required=True)
    export.add_argument("--continuity-event-id"); export.add_argument("--coverage-review", type=Path)
    export.add_argument("--coverage-evidence-root", type=Path)
    commands.add_parser("verify").add_argument("--journal-root", type=Path, required=True)
    show = commands.add_parser("show"); show.add_argument("--journal-root", type=Path, required=True); show.add_argument("--event-id", required=True)
    return parser


def _load_refs(references, blobs, root):
    for ref in references:
        if ref["sha256"] not in blobs: blobs[ref["sha256"]] = _read(root / ref["path"])
        _blob(blobs, ref)


def _export(args, store, events, blobs):
    check_separate_root(store.root, args.evidence_root); check_separate_root(store.root, args.snapshot.parent)
    snapshot = TrainMarketCaptureSnapshot.from_bytes(_read(args.snapshot))
    context = registered_capture_context(args.plan_event_id, events, blobs)
    if snapshot.capture_id != context["plan"].capture_id: raise ValueError("snapshot capture identity differs from registered plan")
    _load_refs([snapshot.capture_plan_evidence], blobs, args.evidence_root)
    if _blob(blobs, snapshot.capture_plan_evidence) != context["plan"].to_bytes(): raise ValueError("snapshot plan source differs from frozen journal plan")
    expected_ids = {segment["segment_id"] for segment in context["plan"].segments}
    if {segment["segment_id"] for segment in snapshot.segments} != expected_ids: raise ValueError("snapshot must inventory every planned TRAIN session")
    if snapshot.attempt_count > context["plan"].limits["max_total_requests"] or snapshot.retained_bytes > context["plan"].limits["max_capture_bytes"]:
        raise ValueError("snapshot exceeds frozen request or corpus bounds")
    # Checkpoints are audit evidence; raw source replay determines completion.
    _load_refs(snapshot.checkpoint_evidence, blobs, args.evidence_root)
    _load_refs([ref for segment in snapshot.segments for page in segment["pages"] for ref in page.values()], blobs, args.evidence_root)
    from .train_market_capture import validate_capture_snapshot
    validate_capture_snapshot(context["plan"], snapshot, blobs)
    ids, written = [], []
    for segment in snapshot.segments:
        if segment["status"] == "NOT_STARTED":
            if segment["pages"]: raise ValueError("uncaptured segment cannot contain hidden source evidence")
            # A frozen budget may prevent an untouched segment from starting.
            # Retain that exact stop reason in the snapshot audit, without
            # manufacturing a provider attempt or a segment source event.
            if segment["failure"] is not None and (segment["failure"]["http_status"] is not None or segment["failure"]["code"] not in {"TOTAL_REQUEST_LIMIT", "CAPTURE_BYTE_LIMIT", "SEGMENT_BYTE_LIMIT", "SEGMENT_PAGE_LIMIT", "SEGMENT_ROW_LIMIT"}):
                raise ValueError("unstarted segment failure must describe a declared resource stop")
            continue
        _load_refs([ref for page in segment["pages"] for ref in page.values()], blobs, args.evidence_root)
        request = TrainMarketSegmentRequest.from_mapping({"schema_version": "blackpod.train_market_segment_export_request.v1", "export_id": args.export_id,
            "capture_plan_event_id": args.plan_event_id, "segment_id": segment["segment_id"], "pages": segment["pages"], "failure": segment["failure"], "exported_at": snapshot.exported_at,
            "auto_trading_enabled": False, "authority": context["plan"].authority})
        material = segment_material(request, events, blobs)
        if (segment["status"] == "COMPLETE") != material["result"]["capture_complete"]: raise ValueError("snapshot completion disagrees with exact native source replay")
        appended = store.append(material["event"], material["evidence"]); ids.append(appended.event_id); written.append(appended.written)
        if all(event.event_id != material["event"].event_id for event in events): events = (*events, material["event"])
        blobs.update({sha256_bytes(raw): raw for raw in material["evidence"].values()})
    coverage_ref = None
    if args.coverage_review is not None:
        if args.coverage_evidence_root is None: raise ValueError("coverage support requires explicit independent evidence root")
        check_separate_root(store.root, args.coverage_review.parent); check_separate_root(store.root, args.coverage_evidence_root)
        raw = _read(args.coverage_review); review = ContinuityCoverageReview.from_bytes(raw)
        coverage_ref = {"path": "train-evidence/independent-coverage-review.v1.json", "sha256": sha256_bytes(raw), "size_bytes": len(raw)}
        blobs[coverage_ref["sha256"]] = raw; _load_refs(review.source_evidence, blobs, args.coverage_evidence_root)
    request = TrainMarketExportRequest.from_mapping({"schema_version": "blackpod.train_market_export_request.v1", "export_id": args.export_id,
        "capture_plan_event_id": args.plan_event_id, "segment_event_ids": sorted(ids), "exported_at": snapshot.exported_at,
        "continuity_event_id": args.continuity_event_id, "coverage_review_evidence": coverage_ref,
        "capture_snapshot_evidence": {"path": "train-evidence/capture-snapshot.v1.json", "sha256": sha256_bytes(snapshot.to_bytes()), "size_bytes": len(snapshot.to_bytes())},
        "capture_checkpoint_evidence": snapshot.checkpoint_evidence,
        "auto_trading_enabled": False, "authority": context["plan"].authority})
    blobs[request.capture_snapshot_evidence["sha256"]] = snapshot.to_bytes()
    material = export_material(request, events, blobs); appended = store.append(material["event"], material["evidence"])
    _write(args.output, canonical_json_bytes(material["result"]), [store.root, args.evidence_root, args.snapshot.parent])
    return {**asdict(appended), "segment_events_written": sum(written), "capture_complete": material["result"]["capture_complete"],
        "coverage_complete": material["result"]["coverage_complete"], "counts": material["result"]["counts"], "consumer_v18": material["result"]["consumer_v18"]}


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        store = JournalStore(args.journal_root)
        if args.command == "verify": output = store.verify().to_dict()
        else:
            events, blobs = store.verified_contents()
            if args.command == "prepare":
                limits = None if args.limits is None else parse_strict_json_object_bytes(_read(args.limits))
                plan = prepare_capture_plan(events, blobs, capture_id=args.capture_id, created_at=args.created_at, base_plan_event_id=args.base_plan_event_id, fold_ids=args.fold_id, limits=limits)
                _write(args.output, plan.to_bytes(), [store.root] + ([] if args.limits is None else [args.limits.parent]))
                output = {"capture_id": plan.capture_id, "planned_segments": len(plan.segments), "output": str(args.output.absolute()), "provider_calls": 0}
            elif args.command == "register":
                check_separate_root(store.root, args.plan.parent)
                plan = TrainMarketCapturePlan.from_bytes(_read(args.plan)); material = capture_plan_material(plan, events, blobs)
                output = asdict(store.append(material["event"], material["evidence"]))
            elif args.command == "capture":
                context = registered_capture_context(args.plan_event_id, events, blobs)
                if context["plan"].evidence_scope != "RETAINED_HISTORY_RESEARCH": raise ValueError("live GETs require a real-history capture plan")
                check_separate_root(store.root, args.capture_root); check_separate_root(args.capture_root, args.credential_source.parent)
                from .paper_account_probe import parse_credentials, MAX_CREDENTIAL_BYTES
                credentials = parse_credentials(_read(args.credential_source, MAX_CREDENTIAL_BYTES), args.credential_format)
                from .train_market_capture import capture_train_quotes
                output = capture_train_quotes(context["plan"], args.capture_root, credentials, request_budget=args.request_budget, source_blobs=blobs)
            elif args.command == "snapshot":
                context = registered_capture_context(args.plan_event_id, events, blobs)
                check_separate_root(store.root, args.capture_root)
                from .train_market_capture import read_capture
                material = read_capture(context["plan"], args.capture_root, exported_at=args.exported_at)
                _write(args.output, canonical_json_bytes(material["snapshot"]), [store.root, args.capture_root])
                output = {"snapshot": str(args.output.absolute()), "provider_calls": 0}
            elif args.command == "export": output = _export(args, store, events, blobs)
            else:
                matches = [event for event in events if event.event_id == args.event_id and event.event_type in {PLAN_TYPE, SEGMENT_TYPE, EXPORT_TYPE}]
                if len(matches) != 1: raise ValueError("show requires an exact TRAIN evidence record")
                output = matches[0].to_dict()
        print(json.dumps(output, sort_keys=True, indent=2)); return 0
    except (OSError, ValueError, JournalStoreError) as exc:
        print(json.dumps({"error": str(exc), "auto_trading_enabled": False}, sort_keys=True)); return 2


if __name__ == "__main__": raise SystemExit(main())
