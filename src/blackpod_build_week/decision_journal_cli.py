"""Explicit offline journal operations; no producer or execution imports."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Sequence

from .contracts.decision_journal import (
    CapitalPolicyProposal,
    EvaluationInput,
    JournalEvent,
)
from .contracts.mission_request import ContractValidationError
from .decision_journal_projection import load_verified_history, project_history
from .decision_journal_store import (
    JournalConflictError, JournalStore, JournalStoreError, check_separate_root,
)
from .hashing import canonical_json_bytes, sha256_bytes
from .mission_store import MissionStoreError
from .sentry_history_cache import RecoveryError, read_regular


def _identity(prefix: str, value: object) -> str:
    return f"{prefix}-{sha256_bytes(canonical_json_bytes(value))}"


def build_policy_event(proposal: CapitalPolicyProposal) -> JournalEvent:
    """Record an inactive proposal; this never issues a capital instruction."""
    value = proposal.to_dict()
    decision_id = _identity(
        "journal-decision", {"kind": "CAPITAL_POLICY", "policy_id": value["policy_id"]}
    )
    payload = proposal.to_bytes()
    return JournalEvent.from_mapping(
        {
            "schema_version": "blackpod.decision_journal_event.v1",
            "event_id": _identity(
                "journal-event",
                {"decision_id": decision_id, "event_type": "CAPITAL_POLICY_PROPOSED"},
            ),
            "decision_id": decision_id,
            "domain": "CAPITAL_ALLOCATION",
            "event_type": "CAPITAL_POLICY_PROPOSED",
            "recorded_at": value["proposed_at"],
            "source": {
                "kind": "CAPITAL_POLICY",
                "policy_id": value["policy_id"],
                "source_sha256": sha256_bytes(payload),
            },
            "evidence": [
                {"path": "capital_policy/proposal.json", "sha256": sha256_bytes(payload),
                 "size_bytes": len(payload)}
            ],
            "payload": value,
        }
    )


def build_evaluation_event(
    evaluation: EvaluationInput, original: JournalEvent
) -> JournalEvent:
    """Bind supplied evaluation to a recorded mission without rewriting it."""
    value = evaluation.to_dict()
    if original.event_type != "MISSION_SNAPSHOT_RECORDED":
        raise ContractValidationError("evaluation requires a recorded mission decision")
    if value["decision_id"] != original.decision_id:
        raise ContractValidationError("evaluation decision_id does not match the original")
    data = evaluation.to_bytes()
    return JournalEvent.from_mapping(
        {
            "schema_version": "blackpod.decision_journal_event.v1",
            "event_id": _identity(
                "journal-event",
                {"decision_id": original.decision_id, "event_type": "EVALUATION_RECORDED",
                 "evaluation_id": value["evaluation_id"]},
            ),
            "decision_id": original.decision_id,
            "domain": original.domain,
            "event_type": "EVALUATION_RECORDED",
            "recorded_at": value["recorded_at"],
            "source": {
                "kind": "EVALUATION", "evaluation_id": value["evaluation_id"],
                "source_sha256": sha256_bytes(data),
            },
            "evidence": [
                {"path": f"evaluations/{value['evaluation_id']}/evaluation.json",
                 "sha256": sha256_bytes(data), "size_bytes": len(data)}
            ],
            "payload": {**value, "execution_status": original.payload["execution_status"]},
        }
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m blackpod_build_week.decision_journal_cli",
        description="Offline passive Decision Journal; no trading or capital activation.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    export = subparsers.add_parser("export-mission", help="verify and retain one mission history")
    export.add_argument("--mission-root", required=True, type=Path)
    export.add_argument("--journal-root", required=True, type=Path)
    export.add_argument(
        "--domain", choices=("UNCLASSIFIED", "TRADING", "INVESTMENT", "CAPITAL_ALLOCATION"),
        default="UNCLASSIFIED", help="explicit import classification; never inferred from symbol",
    )
    export.add_argument("--classification-reason", help="required for an explicit desk/domain")
    verify = subparsers.add_parser("verify", help="read-only chain, evidence and linkage verification")
    verify.add_argument("--journal-root", required=True, type=Path)
    evaluate = subparsers.add_parser("append-evaluation", help="append a supplied linked evaluation")
    evaluate.add_argument("--journal-root", required=True, type=Path)
    evaluate.add_argument("--evaluation", required=True, type=Path)
    policy = subparsers.add_parser("propose-capital-policy", help="record the inactive initial 50/50 proposal")
    policy.add_argument("--journal-root", required=True, type=Path)
    policy.add_argument("--proposal", required=True, type=Path)
    for name, description in (
        ("validate-hypothesis", "read-only structure and retained-source checks"),
        ("record-hypothesis", "append an explicitly supplied INVESTMENT shadow draft"),
    ):
        hypothesis = subparsers.add_parser(name, help=description)
        hypothesis.add_argument("--journal-root", required=True, type=Path)
        hypothesis.add_argument("--hypothesis", required=True, type=Path)
    show = subparsers.add_parser("show-hypothesis", help="read a verified immutable shadow draft")
    show.add_argument("--journal-root", required=True, type=Path)
    show.add_argument("--hypothesis-id", required=True)
    for name in ("validate-challenge", "record-challenge"):
        challenge = subparsers.add_parser(name, help="validate or append a separate source-bound SHADOW review")
        challenge.add_argument("--journal-root", required=True, type=Path)
        challenge.add_argument("--challenge", required=True, type=Path)
    for name in ("evaluate-hypothesis", "record-hypothesis-evaluation"):
        review = subparsers.add_parser(name, help="compare fixed deadline points; optionally record the explicit review")
        review.add_argument("--journal-root", required=True, type=Path)
        review.add_argument("--evaluation", required=True, type=Path)
    for name, field in (("show-challenge", "challenge-id"),
                        ("show-hypothesis-evaluation", "evaluation-id")):
        review = subparsers.add_parser(name, help="read one verified immutable review")
        review.add_argument("--journal-root", required=True, type=Path)
        review.add_argument(f"--{field}", required=True)
        review.add_argument("--hypothesis-id", help="disambiguate a review identifier across hypotheses")
    for name in ("assess-investment-proposal", "record-investment-proposal"):
        proposal = subparsers.add_parser(name, help="assess or retain an explicit SHADOW investment proposal")
        proposal.add_argument("--journal-root", required=True, type=Path)
        proposal.add_argument("--proposal", required=True, type=Path)
    show_proposal = subparsers.add_parser("show-investment-proposal", help="read a verified proposal and explicit-time research approval state")
    show_proposal.add_argument("--journal-root", required=True, type=Path)
    show_proposal.add_argument("--proposal-id", required=True)
    show_proposal.add_argument("--as-of", help="RFC3339 lifecycle time; default is latest journal recording time")
    for name in ("validate-investment-approval", "record-investment-approval"):
        approval = subparsers.add_parser(name, help="validate or retain exact-bound declared human SHADOW review")
        approval.add_argument("--journal-root", required=True, type=Path)
        approval.add_argument("--approval", required=True, type=Path)
        if name == "record-investment-approval":
            approval.add_argument("--confirm-action", choices=("APPROVE", "REJECT", "DEFER", "REVOKE"), required=True)
            approval.add_argument("--confirm-proposal-sha256", required=True)
            approval.add_argument("--acknowledge-shadow-only", action="store_true", required=True)
    show_approval = subparsers.add_parser("show-investment-approval", help="read one immutable SHADOW review and its proposal lifecycle")
    show_approval.add_argument("--journal-root", required=True, type=Path)
    show_approval.add_argument("--approval-id", required=True)
    show_approval.add_argument("--as-of", help="RFC3339 lifecycle time; default is latest journal recording time")
    automation = subparsers.add_parser("set-auto-trading", help="persist ON/OFF intent only; execution remains disabled")
    automation.add_argument("--journal-root", required=True, type=Path)
    automation.add_argument("--control", required=True, type=Path)
    automation_status = subparsers.add_parser("auto-trading-status", help="read persisted OFF/BLOCKED control intent; no broker access")
    automation_status.add_argument("--journal-root", required=True, type=Path)
    return parser


def _retry_prefix(events, *, kind, identity, submitted):
    """Retries retain their original chain prefix even after later evidence."""
    for index, event in enumerate(events):
        if event.source["kind"] == kind and event.source[identity] == getattr(submitted, identity):
            if kind != "INVESTMENT_SHADOW_APPROVAL" or event.payload["approval"]["proposal_event_id"] == submitted.proposal_event_id:
                return events[:index], event
    return events, None


def _lifecycle_time(events, requested):
    from .contracts.mission_request import normalize_rfc3339, parse_rfc3339

    if requested is not None:
        return normalize_rfc3339(requested, "as_of"), "EXPLICIT_AS_OF"
    return max((event.recorded_at for event in events),
               key=lambda value: parse_rfc3339(value, "recorded_at")), "LATEST_JOURNAL_RECORDING"


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        store = JournalStore(args.journal_root)
        if args.command == "export-mission":
            # Check the whole source artifact root: journals cannot be written
            # into a sibling mission or another path beneath producer storage.
            check_separate_root(args.journal_root, args.mission_root)
            if args.mission_root.parent.name == "missions":
                check_separate_root(args.journal_root, args.mission_root.parent.parent)
            history = load_verified_history(args.mission_root)
            events = project_history(
                history, domain=args.domain, classification_reason=args.classification_reason
            )
            results = [
                store.append(event, {ref["path"]: history.source_files[ref["path"]]
                                     for ref in event.evidence})
                for event in events
            ]
            output = {
                "command": args.command, "decision_id": events[0].decision_id,
                "domain": events[0].domain, "source_revisions": len(events),
                "written": sum(result.written for result in results),
                "unchanged": sum(not result.written for result in results),
                "verification": store.verify().to_dict(),
            }
        elif args.command == "verify":
            output = {"command": args.command, **store.verify().to_dict()}
        elif args.command == "append-evaluation":
            submitted = read_regular(args.evaluation)
            evaluation = EvaluationInput.from_bytes(submitted)
            retained = store.events()
            # A retry must use the same decision context as the first append,
            # even when subsequent source revisions have since been imported.
            # The immutable chain position binds that context without editing it.
            for index, previous in enumerate(retained):
                if (previous.event_type == "EVALUATION_RECORDED"
                        and previous.decision_id == evaluation.decision_id
                        and previous.source["evaluation_id"] == evaluation.evaluation_id):
                    retained = retained[:index]
                    break
            originals = [
                event for event in retained
                if event.decision_id == evaluation.decision_id
                and event.event_type == "MISSION_SNAPSHOT_RECORDED"
            ]
            if not originals:
                raise ContractValidationError("evaluation references an unknown mission decision")
            event = build_evaluation_event(evaluation, originals[-1])
            result = store.append(event, {event.evidence[0]["path"]: evaluation.to_bytes()})
            output = {
                "command": args.command, "event_id": result.event_id,
                "decision_id": event.decision_id, "written": result.written,
                "sequence": result.sequence,
            }
        elif args.command == "propose-capital-policy":
            proposal = CapitalPolicyProposal.from_bytes(read_regular(args.proposal))
            event = build_policy_event(proposal)
            result = store.append(event, {"capital_policy/proposal.json": proposal.to_bytes()})
            output = {
                "command": args.command, "event_id": result.event_id,
                "decision_id": event.decision_id, "written": result.written,
                "sequence": result.sequence, "status": "PROPOSED", "activation_enabled": False,
            }
        elif args.command in {"validate-hypothesis", "record-hypothesis"}:
            from .contracts.investment_hypothesis import InvestmentHypothesis
            from .investment_hypothesis import build_hypothesis_event, evidence_for_hypothesis

            hypothesis = InvestmentHypothesis.from_bytes(read_regular(args.hypothesis))
            events, blobs = store.verified_contents()
            event = build_hypothesis_event(hypothesis, events, blobs)
            existing = next((item for item in events if item.event_id == event.event_id), None)
            if existing is not None and existing.to_bytes() != event.to_bytes():
                raise JournalConflictError("hypothesis identity is already bound to a different immutable draft")
            output = {
                "command": args.command, "hypothesis_id": hypothesis.hypothesis_id,
                "event_id": event.event_id, "decision_id": event.decision_id,
                "domain": "INVESTMENT", "mode": "SHADOW", "status": "SHADOW_DRAFT",
                "source_observation_count": len(hypothesis.observations),
                "validation_scope": "STRUCTURE_AND_RETAINED_SOURCE_BINDINGS",
                "economic_truth_evaluated": False, "authority": hypothesis.authority,
                "already_recorded": existing is not None,
            }
            if args.command == "record-hypothesis":
                result = store.append(event, evidence_for_hypothesis(hypothesis, events, blobs))
                output.update({"written": result.written, "sequence": result.sequence})
        elif args.command == "show-hypothesis":
            from .identifiers import validate_identifier

            hypothesis_id = validate_identifier(args.hypothesis_id, "hypothesis_id")
            matches = [event for event in store.events()
                       if event.event_type == "INVESTMENT_HYPOTHESIS_RECORDED"
                       and event.source["hypothesis_id"] == hypothesis_id]
            if len(matches) != 1:
                raise ContractValidationError("hypothesis_id does not identify a recorded shadow draft")
            event = matches[0]
            output = {
                "command": args.command, "hypothesis_id": hypothesis_id,
                "event_id": event.event_id, "decision_id": event.decision_id,
                "mode": "SHADOW", "economic_truth_evaluated": False,
                "hypothesis": event.payload,
            }
        elif args.command in {"validate-challenge", "record-challenge",
                              "evaluate-hypothesis", "record-hypothesis-evaluation"}:
            from .contracts.investment_review import ChallengeInput, OutcomeEvaluationInput
            from .investment_review import (
                build_challenge_event, build_outcome_event,
                evidence_for_challenge, evidence_for_outcome,
            )

            is_challenge = args.command in {"validate-challenge", "record-challenge"}
            contract = ChallengeInput if is_challenge else OutcomeEvaluationInput
            submitted = contract.from_bytes(read_regular(args.challenge if is_challenge else args.evaluation))
            events, blobs = store.verified_contents()
            build = build_challenge_event if is_challenge else build_outcome_event
            retain = evidence_for_challenge if is_challenge else evidence_for_outcome
            event = build(submitted, events, blobs)
            existing = next((item for item in events if item.event_id == event.event_id), None)
            if existing is not None and existing.to_bytes() != event.to_bytes():
                raise JournalConflictError("review identity is already bound to different immutable content")
            identity = "challenge_id" if is_challenge else "evaluation_id"
            report = "assessment" if is_challenge else "result"
            output = {
                "command": args.command, identity: getattr(submitted, identity),
                "event_id": event.event_id, "decision_id": event.decision_id,
                "hypothesis_id": submitted.hypothesis_id, "mode": "SHADOW",
                "already_recorded": existing is not None,
                report: event.payload[report],
            }
            if args.command in {"record-challenge", "record-hypothesis-evaluation"}:
                result = store.append(event, retain(submitted, events, blobs))
                output.update({"written": result.written, "sequence": result.sequence})
        elif args.command in {"assess-investment-proposal", "record-investment-proposal"}:
            from .contracts.investment_governance import ProposalInput
            from .investment_governance import build_proposal_event, evidence_for_proposal

            submitted = ProposalInput.from_bytes(read_regular(args.proposal))
            events, blobs = store.verified_contents()
            prefix, existing = _retry_prefix(events, kind="INVESTMENT_DECISION_PROPOSAL",
                                             identity="proposal_id", submitted=submitted)
            event = build_proposal_event(submitted, prefix, blobs)
            if existing is not None and existing.to_bytes() != event.to_bytes():
                raise JournalConflictError("proposal identity is already bound to different immutable content")
            output = {"command": args.command, "proposal_id": submitted.proposal_id,
                      "event_id": event.event_id, "decision_id": event.decision_id,
                      "hypothesis_id": submitted.hypothesis_id, "domain": "INVESTMENT", "mode": "SHADOW",
                      "already_recorded": existing is not None, "report": event.payload["report"]}
            if args.command == "record-investment-proposal":
                result = store.append(event, evidence_for_proposal(submitted, prefix, blobs))
                output.update(written=result.written, sequence=result.sequence)
        elif args.command in {"validate-investment-approval", "record-investment-approval"}:
            from .contracts.investment_governance import ApprovalInput
            from .investment_approval import build_approval_event, evidence_for_approval

            submitted = ApprovalInput.from_bytes(read_regular(args.approval))
            if args.command == "record-investment-approval":
                if (args.confirm_action != submitted.action
                        or args.confirm_proposal_sha256 != submitted.proposal_sha256
                        or not args.acknowledge_shadow_only):
                    raise ContractValidationError("confirmation flags must match exact action, proposal SHA256, and SHADOW-only scope")
            events, blobs = store.verified_contents()
            prefix, existing = _retry_prefix(events, kind="INVESTMENT_SHADOW_APPROVAL",
                                             identity="approval_id", submitted=submitted)
            event = build_approval_event(submitted, prefix, blobs)
            if existing is not None and existing.to_bytes() != event.to_bytes():
                raise JournalConflictError("approval identity is already bound to different immutable content")
            output = {"command": args.command, "approval_id": submitted.approval_id,
                      "event_id": event.event_id, "decision_id": event.decision_id,
                      "proposal_id": submitted.proposal_id, "domain": "INVESTMENT", "mode": "SHADOW",
                      "already_recorded": existing is not None, "decision": event.payload["decision"]}
            if args.command == "record-investment-approval":
                result = store.append(event, evidence_for_approval(submitted, prefix, blobs))
                output.update(written=result.written, sequence=result.sequence)
        elif args.command in {"show-investment-proposal", "show-investment-approval"}:
            from .identifiers import validate_identifier
            from .investment_approval import approval_state

            is_proposal = args.command == "show-investment-proposal"
            identity = "proposal_id" if is_proposal else "approval_id"
            requested = validate_identifier(getattr(args, identity), identity)
            kind = "INVESTMENT_DECISION_PROPOSAL" if is_proposal else "INVESTMENT_SHADOW_APPROVAL"
            events = store.events()
            matches = [event for event in events if event.source["kind"] == kind and event.source[identity] == requested]
            if len(matches) != 1:
                raise ContractValidationError("governance identifier is missing or ambiguous")
            event = matches[0]
            parent = event if is_proposal else next(item for item in events if item.event_id == event.payload["approval"]["proposal_event_id"])
            as_of, time_basis = _lifecycle_time(events, args.as_of)
            output = {"command": args.command, identity: requested, "event_id": event.event_id,
                      "decision_id": event.decision_id, "domain": "INVESTMENT", "mode": "SHADOW",
                      **event.payload, "approval_state": approval_state(parent, events, as_of),
                      "lifecycle_time_basis": time_basis}
        elif args.command == "set-auto-trading":
            from .contracts.trading_automation import TradingAutomationControl
            from .trading_automation import build_automation_event, evidence_for_automation, auto_trading_status

            control = TradingAutomationControl.from_bytes(read_regular(args.control))
            event = build_automation_event(control)
            result = store.append(event, evidence_for_automation(control))
            output = {"command": args.command, "event_id": result.event_id,
                      "decision_id": event.decision_id, "control_id": control.control_id,
                      "written": result.written, "sequence": result.sequence,
                      "origin": control.origin, "status": event.payload["status"],
                      "current_status": auto_trading_status(store.events())}
        elif args.command == "auto-trading-status":
            from .trading_automation import auto_trading_status

            # A missing journal is the default OFF state, not permission to
            # create a journal or mask corruption in an existing one.
            events = store.events() if store.root.exists() else ()
            output = {"command": args.command, **auto_trading_status(events)}
        else:
            from .identifiers import validate_identifier

            is_challenge = args.command == "show-challenge"
            identity = "challenge_id" if is_challenge else "evaluation_id"
            requested = validate_identifier(getattr(args, identity), identity)
            requested_hypothesis = (validate_identifier(args.hypothesis_id, "hypothesis_id")
                                    if args.hypothesis_id is not None else None)
            kind = "INVESTMENT_CHALLENGE" if is_challenge else "INVESTMENT_OUTCOME_EVALUATION"
            document = "challenge" if is_challenge else "evaluation"
            matches = [event for event in store.events()
                       if event.source["kind"] == kind and event.source[identity] == requested
                       and (requested_hypothesis is None
                            or event.payload[document]["hypothesis_id"] == requested_hypothesis)]
            if len(matches) != 1:
                raise ContractValidationError("review identifier is missing or ambiguous; specify --hypothesis-id when needed")
            event = matches[0]
            output = {
                "command": args.command, identity: requested,
                "event_id": event.event_id, "decision_id": event.decision_id,
                "mode": "SHADOW", **event.payload,
            }
        print(json.dumps(output, sort_keys=True))
        return 0
    except (ContractValidationError, JournalStoreError, MissionStoreError, RecoveryError,
            OSError, ValueError, RecursionError) as exc:
        print(f"decision-journal: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
