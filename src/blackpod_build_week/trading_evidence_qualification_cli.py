"""Explicit offline policy freeze and evidence qualification commands."""
import argparse
from dataclasses import asdict
import json
from pathlib import Path

from .contracts.trading_evidence_qualification import TradingEvidenceQualificationPolicy, TradingEvidenceQualificationRequest, TradingTrainingAssumptions, POLICY_TYPE, ASSESSMENT_TYPE, STATUSES
from .contracts.mission_request import parse_strict_json_object_bytes
from .decision_journal_store import JournalStore, JournalStoreError, check_separate_root, _check_existing_ancestors
from .desk_candidate_review_cli import _write
from .sentry_history_cache import read_regular
from .trading_research_journal import _blob
from .trading_evidence_qualification import prepare_policy, qualify_evidence
from .trading_evidence_qualification_journal import policy_material, qualification_material


def _read(path):
    path = Path(path).absolute()
    if ".." in path.parts: raise ValueError("input cannot traverse parents")
    _check_existing_ancestors(path.parent)
    return read_regular(path, max_bytes=64 * 1024 * 1024)


def load_policy_evidence(policy, retained, root):
    """Read declared typed leaf references only; opaque bodies stay opaque."""
    blobs = dict(retained)
    references = [*policy.supporting_evidence, *[ref for chain in policy.training_quote_chains for page in chain["pages"] for ref in page.values()]]
    def load(refs):
        for ref in refs:
            if ref["sha256"] not in blobs:
                if root is None: raise ValueError("unretained policy evidence requires explicit evidence root")
                blobs[ref["sha256"]] = _read(root / ref["path"])
            _blob(blobs, ref)
    if policy.training_cost_assumptions_evidence is not None:
        load([policy.training_cost_assumptions_evidence])
        assumptions = TradingTrainingAssumptions.from_bytes(_blob(blobs, policy.training_cost_assumptions_evidence))
        references.extend(assumptions.origin_evidence)
    load(references)
    return blobs


def build_parser():
    parser = argparse.ArgumentParser(description="Frozen training-only evidence qualification; auto-trading OFF")
    commands = parser.add_subparsers(dest="command", required=True)
    prepare = commands.add_parser("prepare", help="Freeze a PROPOSED design without calibration or journal writes")
    for name in ("policy-id", "recorded-at", "base-plan-event-id", "reviewer-id", "review-notes"):
        prepare.add_argument("--" + name, required=True)
    for name in ("continuity-event-id", "cost-event-id", "risk-review-event-id", "supersedes-policy-event-id"):
        prepare.add_argument("--" + name)
    prepare.add_argument("--inputs", type=Path, required=True, help="Exact source declarations and optional protocol JSON")
    prepare.add_argument("--status", choices=sorted(STATUSES), default="PROPOSED")
    prepare.add_argument("--output", type=Path, required=True)
    prepare.add_argument("--journal-root", type=Path, required=True)
    register = commands.add_parser("register")
    register.add_argument("--policy", type=Path, required=True)
    register.add_argument("--evidence-root", type=Path)
    register.add_argument("--journal-root", type=Path, required=True)
    for name in ("assess", "record"):
        command = commands.add_parser(name)
        command.add_argument("--request", type=Path, required=True)
        command.add_argument("--journal-root", type=Path, required=True)
        if name == "assess": command.add_argument("--output", type=Path, required=True)
    commands.add_parser("verify").add_argument("--journal-root", type=Path, required=True)
    show = commands.add_parser("show"); show.add_argument("--journal-root", type=Path, required=True); show.add_argument("--event-id", required=True)
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        store = JournalStore(args.journal_root)
        if args.command == "verify": output = store.verify().to_dict()
        else:
            events, blobs = store.verified_contents()
            if args.command == "prepare":
                inputs = parse_strict_json_object_bytes(_read(args.inputs))
                if set(inputs) != {"supporting_evidence", "training_quote_chains", "training_cost_assumptions_evidence", "uncertainty_protocol"}:
                    raise ValueError("prepare inputs require exact supporting/training/assumption/protocol fields")
                policy = prepare_policy(events, blobs, policy_id=args.policy_id, recorded_at=args.recorded_at,
                    base_plan_event_id=args.base_plan_event_id, reviewer_id=args.reviewer_id, review_notes=args.review_notes,
                    continuity_event_id=args.continuity_event_id, cost_event_id=args.cost_event_id, risk_review_event_id=args.risk_review_event_id,
                    supersedes_policy_event_id=args.supersedes_policy_event_id, status=args.status, **inputs)
                _write(args.output, policy.to_bytes(), [store.root, args.inputs.parent])
                output = {"policy_id": policy.policy_id, "status": policy.status, "output": str(args.output.absolute()), "calibration_performed": False}
            elif args.command == "register":
                check_separate_root(store.root, args.policy.parent)
                if args.evidence_root is not None: check_separate_root(store.root, args.evidence_root)
                policy = TradingEvidenceQualificationPolicy.from_bytes(_read(args.policy))
                blobs = load_policy_evidence(policy, blobs, args.evidence_root)
                material = policy_material(policy, events, blobs)
                output = asdict(store.append(material["event"], material["evidence"]))
            elif args.command == "show":
                matches = [event for event in events if event.event_id == args.event_id and event.event_type in {POLICY_TYPE, ASSESSMENT_TYPE}]
                if len(matches) != 1: raise ValueError("show requires exact retained qualification record")
                output = matches[0].to_dict()
            else:
                check_separate_root(store.root, args.request.parent)
                request = TradingEvidenceQualificationRequest.from_bytes(_read(args.request))
                if args.command == "assess":
                    material = qualify_evidence(request, events, blobs)
                    from .hashing import canonical_json_bytes
                    _write(args.output, canonical_json_bytes(material["result"]), [store.root, args.request.parent])
                    output = {"qualification_id": request.qualification_id, "status": material["result"]["status"], "output": str(args.output.absolute())}
                else:
                    material = qualification_material(request, events, blobs)
                    output = {**asdict(store.append(material["event"], material["evidence"])), "status": material["result"]["status"]}
        print(json.dumps(output, sort_keys=True, indent=2)); return 0
    except (OSError, ValueError, JournalStoreError) as exc:
        print(json.dumps({"error": str(exc), "auto_trading_enabled": False}, sort_keys=True)); return 2


if __name__ == "__main__": raise SystemExit(main())
