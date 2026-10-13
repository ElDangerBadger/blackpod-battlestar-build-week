"""Explicit offline research acceptance commands; no orchestration hooks."""
import argparse
from dataclasses import asdict
import json
from pathlib import Path

from .contracts.research_assessment import EVENT_TYPE, ResearchAssessmentRequest, SCOPES
from .decision_journal_store import JournalStore, JournalStoreError, check_separate_root
from .desk_candidate_review_cli import _write
from .hashing import sha256_bytes
from .research_acceptance import assess_research, prepare_request
from .research_acceptance_journal import assessment_material
from .sentry_history_cache import read_regular


def build_parser():
    parser = argparse.ArgumentParser(description="Offline two-desk research acceptance; no execution or capital authority")
    commands = parser.add_subparsers(dest="command", required=True)
    command = commands.add_parser("prepare", help="Declare exact sources and clocks without evaluating or writing journal history")
    for flag in ("research-event-id", "assessment-id", "recorded-at", "data-cutoff-at"):
        command.add_argument("--" + flag, required=True)
    command.add_argument("--scope", choices=sorted(SCOPES), default="EXPLORATORY_RESEARCH")
    command.add_argument("--evaluation-event-id")
    command.add_argument("--supersedes-event-id")
    command.add_argument("--candidate-result-file", type=Path)
    command.add_argument("--output-directory", type=Path, required=True)
    command.add_argument("--journal-root", type=Path, required=True)
    for name in ("assess", "record"):
        command = commands.add_parser(name)
        command.add_argument("--request", type=Path, required=True)
        command.add_argument("--journal-root", type=Path, required=True)
        command.add_argument("--evidence-root", type=Path)
        if name == "assess": command.add_argument("--output", type=Path, required=True)
    commands.add_parser("verify").add_argument("--journal-root", type=Path, required=True)
    command = commands.add_parser("show")
    command.add_argument("--journal-root", type=Path, required=True)
    command.add_argument("--event-id", required=True)
    return parser


def _candidate_blobs(request, blobs, evidence_root, journal_root):
    reference = request.candidate_result_evidence
    if reference is None:
        return blobs
    if reference["size_bytes"] > 4 * 1024 * 1024:
        raise ValueError("candidate result exceeds the 4 MiB input bound")
    if reference["sha256"] in blobs:
        return blobs
    if evidence_root is None:
        raise ValueError("unretained candidate result requires an explicit evidence root")
    check_separate_root(journal_root, evidence_root)
    raw = _read_input(evidence_root / reference["path"])
    if len(raw) != reference["size_bytes"] or sha256_bytes(raw) != reference["sha256"]:
        raise ValueError("candidate result evidence differs from declared hash or size")
    if len(raw) > 4 * 1024 * 1024:
        raise ValueError("candidate result exceeds the 4 MiB input bound")
    return {**blobs, reference["sha256"]: raw}


def _read_input(path):
    from .decision_journal_store import _check_existing_ancestors
    path = Path(path).absolute()
    if ".." in path.parts:
        raise ValueError("input paths cannot use parent traversal")
    _check_existing_ancestors(path.parent)
    return read_regular(path, max_bytes=4 * 1024 * 1024)


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        store = JournalStore(args.journal_root)
        if args.command == "verify":
            result = store.verify().to_dict()
        else:
            events, blobs = store.verified_contents()
            if args.command == "prepare":
                reference, candidate = None, None
                if args.candidate_result_file is not None:
                    check_separate_root(store.root, args.candidate_result_file.parent)
                    candidate = _read_input(args.candidate_result_file)
                    if len(candidate) > 4 * 1024 * 1024:
                        raise ValueError("candidate result exceeds the 4 MiB input bound")
                    reference = {"path": "candidate-result/result.json", "sha256": sha256_bytes(candidate), "size_bytes": len(candidate)}
                request = prepare_request(events, research_event_id=args.research_event_id, assessment_id=args.assessment_id,
                    recorded_at=args.recorded_at, data_cutoff_at=args.data_cutoff_at, assessment_scope=args.scope,
                    evaluation_event_id=args.evaluation_event_id, candidate_result_evidence=reference,
                    supersedes_event_id=args.supersedes_event_id, blobs=blobs)
                protected = [store.root] + ([] if args.candidate_result_file is None else [args.candidate_result_file.parent])
                if candidate is not None:
                    _write(args.output_directory / reference["path"], candidate, protected)
                path = args.output_directory / "request.v1.json"
                _write(path, request.to_bytes(), protected)
                result = {"request_path": str(path.absolute()), "assessment_id": request.assessment_id, "auto_trading_enabled": False}
            elif args.command == "show":
                matches = [event for event in events if event.event_id == args.event_id and event.event_type == EVENT_TYPE]
                if len(matches) != 1:
                    raise ValueError("show requires a retained research assessment event")
                result = matches[0].to_dict()
            else:
                check_separate_root(store.root, args.request.parent)
                request = ResearchAssessmentRequest.from_bytes(_read_input(args.request))
                blobs = _candidate_blobs(request, blobs, args.evidence_root, store.root)
                if args.command == "assess":
                    material = assess_research(request, events, blobs)
                    _write(args.output, material["assessment"].to_bytes(), [store.root, args.request.parent] + ([] if args.evidence_root is None else [args.evidence_root]))
                    result = {"assessment_id": request.assessment_id, "classification": material["assessment"].classification,
                        "output_path": str(args.output.absolute()), "auto_trading_enabled": False}
                else:
                    material = assessment_material(request, events, blobs)
                    appended = store.append(material["event"], material["evidence"])
                    result = {**asdict(appended), "classification": material["assessment"].classification, "auto_trading_enabled": False}
        print(json.dumps(result, sort_keys=True, indent=2))
        return 0
    except (OSError, ValueError, JournalStoreError) as exc:
        print(json.dumps({"error": str(exc), "auto_trading_enabled": False}, sort_keys=True))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
