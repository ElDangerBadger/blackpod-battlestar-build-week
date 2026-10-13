"""Explicit offline two-desk shadow review; never execution or activation."""
import argparse
import json
from pathlib import Path
import sys

from .contracts.desk_candidate_review import DeskReviewInput
from .contracts.mission_request import parse_strict_json_object_bytes
from .contracts.trading_reconciliation import evidence_reference
from .decision_journal_store import JournalStore, JournalStoreError, check_separate_root
from .hashing import canonical_json_bytes, sha256_bytes
from .sentry_history_cache import read_regular, RecoveryError


def _references(value, depth=0):
    if depth > 24:
        raise ValueError("shadow evidence nesting exceeds the supported limit")
    if isinstance(value, dict):
        if set(value) == {"path", "sha256", "size_bytes"}:
            yield evidence_reference(value)
        else:
            for item in value.values():
                yield from _references(item, depth + 1)
    elif isinstance(value, list):
        for item in value:
            yield from _references(item, depth + 1)


def load_evidence(root, references, retained=None):
    """Freeze only explicitly hash-bound files; do not read arbitrary latest data."""
    from .decision_journal_store import _check_existing_ancestors
    root = Path(root).absolute()
    _check_existing_ancestors(root)
    blobs, pending, visited = dict(retained or {}), list(references), set()
    while pending:
        ref = evidence_reference(pending.pop())
        identity = (ref["path"], ref["sha256"], ref["size_bytes"])
        if identity in visited:
            continue
        if len(visited) >= 256:
            raise ValueError("shadow evidence exceeds the retained-file bound")
        visited.add(identity)
        raw = blobs.get(ref["sha256"])
        if raw is None:
            path = root / ref["path"]
            _check_existing_ancestors(path.parent)
            raw = read_regular(path)
        if sha256_bytes(raw) != ref["sha256"] or len(raw) != ref["size_bytes"]:
            raise ValueError("shadow input evidence differs in hash or size")
        blobs[ref["sha256"]] = raw
        if ref["path"].endswith(".json"):
            pending.extend(_references(parse_strict_json_object_bytes(raw)))
    return blobs


def _write(target, raw, sources):
    from .auto_trading_runtime import RuntimeLedger, _immutable
    from .decision_journal_store import _check_existing_ancestors, _reject_source_storage
    target = Path(target).absolute()
    for source in sources:
        check_separate_root(target.parent, Path(source).absolute())
    _check_existing_ancestors(target.parent)
    # A render request has no mutable native-root setting. Protect every Git
    # source tree, including descendants of a sibling checkout. Only this
    # package's ignored output tree is a supported in-repository destination.
    package_root = Path(__file__).absolute().parents[2]
    for ancestor in (target.parent, *target.parent.parents):
        if any((ancestor / name).exists() for name in ("ledger.lock", "worker.lock")):
            raise ValueError("shadow output must be separate from installed trading runtime storage")
        if ancestor.name == ".git":
            raise ValueError("shadow output cannot write inside repository metadata")
        if (ancestor / ".git").exists():
            if ancestor == package_root and target.relative_to(ancestor).parts[0] == "output":
                break
            raise ValueError("shadow output cannot write inside repository source trees")
    _reject_source_storage(target.parent)
    ledger = RuntimeLedger(target.parent)  # Reuses path guards, not execution.
    # Recovery must hold the same parent lock as every passive writer so it
    # cannot remove another writer's active staging file.
    with ledger.lock(name=".shadow-artifact.lock"):
        _immutable(target, raw)


def build_parser():
    parser = argparse.ArgumentParser(description="Source-bound shadow desk review and inactive paper test proposals")
    commands = parser.add_subparsers(dest="command", required=True)
    prepare = commands.add_parser("prepare-analysis", help="Freeze reviewed native code and run only passive calculations")
    prepare.add_argument("--market", type=Path, required=True)
    prepare.add_argument("--evidence-root", type=Path, required=True)
    prepare.add_argument("--native-root", type=Path, required=True)
    prepare.add_argument("--galactica-root", type=Path, required=True)
    prepare.add_argument("--generated-at", required=True)
    prepare.add_argument("--brigade-transcript", type=Path)
    prepare.add_argument("--brigade-as-of")
    for name in ("assess", "record"):
        command = commands.add_parser(name)
        command.add_argument("--journal-root", type=Path, required=True)
        command.add_argument("--review", type=Path, required=True)
        command.add_argument("--evidence-root", type=Path)
    for name in ("show", "render"):
        command = commands.add_parser(name)
        command.add_argument("--journal-root", type=Path, required=True)
        command.add_argument("--event-id", required=True)
        if name == "render":
            command.add_argument("--output", type=Path, required=True)
    return parser


def prepare_analysis(args):
    from .desk_review_sources import validate_market_packet
    from .shadow_native_analysis import capture_native_sources, derive_native_analysis
    from .shadow_galactica_analysis import build_shadow_galactica_analysis, evidence_for_shadow_galactica_analysis
    if (args.brigade_transcript is None) != (args.brigade_as_of is None):
        raise ValueError("historical Brigade transcript and its explicit source date must be supplied together")
    for source in (args.native_root, args.galactica_root):
        check_separate_root(args.evidence_root, source)
    raw_market = read_regular(args.market)
    market = parse_strict_json_object_bytes(raw_market)
    blobs = load_evidence(args.evidence_root, _references(market))
    validate_market_packet(market, blobs)
    sources = capture_native_sources(args.native_root)
    native = derive_native_analysis(market, sources)
    spyglass = read_regular(args.galactica_root / "spyglass.py", max_bytes=256 * 1024)
    kwargs = {}
    if args.brigade_transcript is not None:
        kwargs = {"brigade_transcript": read_regular(args.brigade_transcript, max_bytes=4 * 1024 * 1024),
            "brigade_parser_source": read_regular(args.galactica_root / "scripts/brigade_debrief.py", max_bytes=256 * 1024),
            "brigade_producer_source": read_regular(args.galactica_root / "agents/blackwell_brigade.py", max_bytes=256 * 1024),
            "brigade_as_of": args.brigade_as_of}
    galactica = build_shadow_galactica_analysis(raw_market, spyglass, generated_at=args.generated_at, **kwargs)
    evidence = {"native_analysis_code/" + path: raw for path, raw in sources.items()}
    evidence.update(evidence_for_shadow_galactica_analysis(raw_market, spyglass,
        **{key: value for key, value in kwargs.items() if key != "brigade_as_of"}))
    references = native["source_evidence"] + [ref for ref in galactica["source_evidence"].values() if ref is not None]
    packet = {"schema_version": "blackpod.shadow_analysis_bundle.v1", "native": native,
        "galactica": galactica, "source_evidence": references}
    raw = canonical_json_bytes(packet)
    sources_to_protect = (args.native_root, args.galactica_root)
    for path, content in sorted(evidence.items()):
        _write(args.evidence_root / path, content, sources_to_protect)
    target = args.evidence_root / ("analysis-bundle-" + sha256_bytes(raw) + ".json")
    _write(target, raw, sources_to_protect)
    return {"path": str(target.absolute()), "sha256": sha256_bytes(raw), "size_bytes": len(raw),
        "spyglass_status": galactica["spyglass"]["status"], "brigade_status": galactica["brigade"]["status"],
        "current_brigade_inference_run": False}


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        if args.command == "prepare-analysis":
            output = prepare_analysis(args)
            print(json.dumps({"command": args.command, **output, "orders_submitted": 0,
                "auto_trading_changed": False}, sort_keys=True))
            return 0
        from .desk_candidate_review import build_desk_review_event, evidence_for_desk_review
        store = JournalStore(args.journal_root)
        events, blobs = store.verified_contents() if store.root.exists() else ((), {})
        if args.command in {"show", "render"}:
            event = next((item for item in events if item.event_id == args.event_id
                and item.event_type == "SHADOW_DESK_REVIEW_RECORDED"), None)
            if event is None:
                raise ValueError("unknown verified shadow review")
            if args.command == "show":
                output = event.to_dict()
            else:
                from .desk_candidate_review_presentation import render_desk_review
                raw = render_desk_review(event, blobs).encode("utf-8")
                _write(args.output, raw, (store.root,))
                output = {"path": str(args.output.absolute()), "sha256": sha256_bytes(raw)}
        else:
            submitted = DeskReviewInput.from_bytes(read_regular(args.review))
            if args.evidence_root is not None:
                check_separate_root(store.root, args.evidence_root)
                blobs = load_evidence(args.evidence_root, _references(submitted.to_dict()), blobs)
            event = build_desk_review_event(submitted, events, blobs)
            output = {"event_id": event.event_id, "decision_id": event.decision_id, **event.payload}
            if args.command == "record":
                result = store.append(event, evidence_for_desk_review(submitted, events, blobs))
                output.update(written=result.written, sequence=result.sequence)
        print(json.dumps({"command": args.command, **output, "orders_submitted": 0,
            "auto_trading_changed": False}, sort_keys=True))
        return 0
    except (ValueError, OSError, JournalStoreError, RecoveryError, TypeError, RecursionError) as exc:
        print("shadow-desk-review: " + str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
