"""Additive v16 evidence, sizing review and governed shadow study history."""
from pathlib import Path

from .contracts.decision_journal import JournalEvent, _identifier
from .contracts.mission_request import parse_rfc3339
from .contracts.trading_accounting import accounting_timestamp
from .contracts.trading_shadow_risk_review import TradingShadowRiskReview
from .contracts.trading_shadow_review import ReviewedShadowStudy
from .contracts.trading_research import TradingResearchPlan
from .hashing import canonical_json_bytes, sha256_bytes
from .sentry_history_cache import read_regular
from .trading_research_journal import _blob, identity, registered_context, evidence_for_research
from .trading_continuity_intake import verify_continuity_intake
from .trading_cost_intake import verify_cost_intake
from .trading_shadow_risk_review import shadow_risk_review_material
from .trading_shadow_review import mapping, merge_evidence, reviewed_study_material, assess_reviewed_material, ref
from .trading_shadow_journal import CODE_PATHS as V1_CODE_PATHS

SCHEMA_VERSION = "blackpod.decision_journal_event.v16"
CONTINUITY_TYPE = "TRADING_CONTINUITY_INTAKE_RECORDED"
COST_TYPE = "TRADING_COST_INTAKE_RECORDED"
RISK_TYPE = "TRADING_SHADOW_RISK_REVIEW_RECORDED"
STUDY_TYPE = "TRADING_REVIEWED_SHADOW_STUDY_REGISTERED"
EVALUATION_TYPE = "TRADING_REVIEWED_SHADOW_EVALUATION_RECORDED"
CODE_PATHS = (*V1_CODE_PATHS, "contracts/trading_evidence_capture.py", "contracts/trading_continuity_intake.py",
    "trading_continuity_intake.py", "contracts/trading_cost_intake.py", "trading_cost_intake.py",
    "contracts/trading_shadow_risk_review.py", "trading_shadow_risk_review.py",
    "contracts/trading_shadow_review.py", "trading_shadow_review.py")


def implementation_evidence():
    root = Path(__file__).absolute().parent
    return {"reviewed-shadow/implementation/" + path: read_regular(root / path) for path in CODE_PATHS}


def _refs(evidence):
    return [ref(path, raw) for path, raw in sorted(evidence.items())]


def _material(kind, export, blobs):
    if kind not in {"CONTINUITY", "COST"}:
        raise ValueError("unsupported governed evidence intake kind")
    return (verify_continuity_intake if kind == "CONTINUITY" else verify_cost_intake)(export, blobs)


def evidence_for_intake(kind, export, blobs):
    material = _material(kind, export, blobs)
    evidence = dict(material["evidence"])
    path = "continuity-intake/export.v1.json" if kind == "CONTINUITY" else "cost-intake/export.v1.json"
    merge_evidence(evidence, {path: canonical_json_bytes(mapping(material["export"]))})
    return evidence


def _event(kind, identity_fields, document, event_type, evidence, payload, recorded_at, evaluation_id=None, source_kind=None):
    decision_id = identity("journal-decision", {"kind": kind, **identity_fields})
    event_identity = {"decision_id": decision_id, "event_type": event_type}
    source = {"kind": source_kind or kind, **identity_fields, "source_sha256": sha256_bytes(document.to_bytes())}
    if evaluation_id is not None:
        source["evaluation_id"] = evaluation_id; event_identity["evaluation_id"] = evaluation_id
    return JournalEvent.from_mapping({"schema_version": SCHEMA_VERSION,
        "event_id": identity("journal-event", event_identity), "decision_id": decision_id, "domain": "TRADING",
        "event_type": event_type, "recorded_at": recorded_at, "source": source, "evidence": _refs(evidence), "payload": payload})


def build_evidence_intake_event(kind, export, blobs, *, recorded_at):
    material = _material(kind, export, blobs)
    request = material["request"]
    recorded_at = accounting_timestamp(recorded_at, "recorded_at")
    if parse_rfc3339(recorded_at, "event clock") < parse_rfc3339(request.recorded_at, "request clock"):
        raise ValueError("evidence journal record cannot predate intake")
    return _event("TRADING_" + kind + "_INTAKE", {"run_id": request.run_id}, request,
        CONTINUITY_TYPE if kind == "CONTINUITY" else COST_TYPE, evidence_for_intake(kind, export, blobs),
        {"request": request.to_dict(), "export": mapping(material["export"])}, recorded_at)


def _risk_context(review, events, blobs):
    review = review if isinstance(review, TradingShadowRiskReview) else TradingShadowRiskReview.from_mapping(review)
    base = TradingResearchPlan.from_bytes(_blob(blobs, review.base_plan_evidence))
    base, dataset, _, original = registered_context(base, events, blobs)
    material = shadow_risk_review_material(review, base, dataset, blobs)
    links = {"base_plan_event_id": original.event_id, "hypothesis_event_id": original.payload["hypothesis_event_id"],
             "intake_event_id": original.payload["intake_event_id"]}
    return review, base, material, links


def evidence_for_risk_review(review, events, blobs):
    review, base, material, _ = _risk_context(review, events, blobs)
    evidence = evidence_for_research(base, blobs)
    merge_evidence(evidence, material["evidence"])
    merge_evidence(evidence, {review.base_plan_evidence["path"]: _blob(blobs, review.base_plan_evidence),
                            "reviewed-shadow/risk-review.v1.json": review.to_bytes()})
    return evidence


def build_risk_review_event(review, events, blobs):
    review, base, material, links = _risk_context(review, events, blobs)
    return _event("TRADING_SHADOW_RISK_REVIEW", {"risk_review_id": review.risk_review_id}, review, RISK_TYPE,
        evidence_for_risk_review(review, events, blobs), {"review": review.to_dict(), "assessment": material["assessment"], **links}, review.recorded_at)


def _prefix(study, events):
    events = tuple(events)
    for index, event in enumerate(events):
        if event.event_type == STUDY_TYPE and event.source["study_id"] == study.study_id:
            if event.payload["study"] != study.to_dict():
                raise ValueError("reviewed shadow study identity is immutable")
            return events[:index]
    return events


def reviewed_context(study, events, blobs):
    material = reviewed_study_material(study, events, blobs)
    study = material["study"]
    links = dict(material["links"])
    for key, event_type, reference, payload_key in (
        ("risk_review_event_id", RISK_TYPE, study.risk_review_evidence, "review"),
        ("continuity_event_id", CONTINUITY_TYPE, study.continuity_intake_evidence, "export"),
        ("cost_event_id", COST_TYPE, study.cost_intake_evidence, "export"),
    ):
        if reference is None:
            links[key] = None; continue
        candidates = [event for event in events if event.event_type == event_type and
            sha256_bytes(canonical_json_bytes(event.payload[payload_key])) == reference["sha256"]]
        if len(candidates) != 1:
            raise ValueError("reviewed study requires unique preceding risk and adapter records")
        if parse_rfc3339(candidates[0].recorded_at, "source journal clock") > parse_rfc3339(study.registered_at, "study clock"):
            raise ValueError("reviewed study cannot predate source journal records")
        links[key] = candidates[0].event_id
    return {**material, "links": links}


def evidence_for_reviewed_study(study, events, blobs):
    material = reviewed_context(study, events, blobs)
    evidence = dict(material["evidence"])
    merge_evidence(evidence, implementation_evidence())
    merge_evidence(evidence, {"trading-shadow-review/study.v2.json": material["study"].to_bytes()})
    return evidence


def _study_event(study, event_type, evidence, payload, recorded_at, evaluation_id=None):
    return _event("TRADING_REVIEWED_SHADOW_STUDY", {"study_id": study.study_id, "experiment_id": study.experiment_id,
        "trial_id": study.trial_registry["trial_id"]}, study, event_type, evidence,
        {"study": study.to_dict(), **payload}, recorded_at, evaluation_id,
        "TRADING_REVIEWED_SHADOW_EVALUATION" if event_type == EVALUATION_TYPE else None)


def _signature(study):
    return {key: study.to_dict()[key] for key in ("base_plan_evidence", "continuity_intake_evidence", "cost_intake_evidence",
        "risk_review_evidence", "evidence_scope", "benchmark", "cost_stress_multipliers")}


def build_reviewed_study_event(study, events=(), blobs=None):
    study = study if isinstance(study, ReviewedShadowStudy) else ReviewedShadowStudy.from_mapping(study)
    blobs = blobs or {}; previous = _prefix(study, events)
    material = reviewed_context(study, previous, blobs)
    peers = [event for event in previous if event.event_type == STUDY_TYPE and event.source["experiment_id"] == study.experiment_id]
    prior = sorted(event.source["trial_id"] for event in peers)
    if sorted(study.trial_registry["prior_trial_ids"]) != prior or study.trial_registry["trial_id"] in prior:
        raise ValueError("reviewed registry must retain every preceding trial")
    if any(_signature(ReviewedShadowStudy.from_mapping(event.payload["study"])) != _signature(study) for event in peers):
        raise ValueError("risk or evidence changes require a distinct reviewed experiment")
    if any(parse_rfc3339(event.recorded_at, "prior clock") > parse_rfc3339(study.registered_at, "study clock") for event in peers):
        raise ValueError("reviewed trial cannot predate experiment history")
    return _study_event(study, STUDY_TYPE, evidence_for_reviewed_study(study, previous, blobs),
        {**material["links"], "gate_assessment": material["gate_assessment"],
         "risk_assessment": material["risk_assessment"], "implementation_evidence": _refs(implementation_evidence())}, study.registered_at)


def _registered(study, events, blobs):
    study = study if isinstance(study, ReviewedShadowStudy) else ReviewedShadowStudy.from_mapping(study)
    events = tuple(events)
    original = next((event for event in events if event.event_type == STUDY_TYPE and event.source["study_id"] == study.study_id), None)
    if original is None or original.payload["study"] != study.to_dict():
        raise ValueError("reviewed evaluation requires original immutable study registration")
    material = reviewed_context(study, events[:events.index(original)], blobs)
    if (any(original.payload[key] != value for key, value in material["links"].items())
            or original.payload["gate_assessment"] != material["gate_assessment"]
            or original.payload["risk_assessment"] != material["risk_assessment"]
            or original.payload["implementation_evidence"] != _refs(implementation_evidence())):
        raise ValueError("reviewed source links, risk, gates or installed calculations changed")
    return material, original


def assess_registered_reviewed_study(study, events, blobs):
    material, _ = _registered(study, events, blobs)
    result = assess_reviewed_material(material)
    result["result"]["trial_registry"] = {**material["study"].trial_registry,
        "global_trial_completeness_verified": False, "prospective_preregistration_verified": False}
    return result


def build_reviewed_evaluation_event(study, events, blobs, *, evaluation_id, recorded_at):
    material, original = _registered(study, events, blobs)
    study = material["study"]; evaluation_id = _identifier(evaluation_id, "evaluation_id")
    recorded_at = accounting_timestamp(recorded_at, "recorded_at")
    if parse_rfc3339(recorded_at, "evaluation clock") < parse_rfc3339(study.registered_at, "study clock"):
        raise ValueError("reviewed evaluation cannot predate registration")
    assessed = assess_registered_reviewed_study(study, events, blobs)
    return _study_event(study, EVALUATION_TYPE, evidence_for_reviewed_study(study, events, blobs),
        {**material["links"], "study_event_id": original.event_id, "gate_assessment": material["gate_assessment"],
        "risk_assessment": material["risk_assessment"], "implementation_evidence": original.payload["implementation_evidence"], **assessed},
        recorded_at, evaluation_id)


def validate_reviewed_event(event, previous_events, blobs):
    if event.event_type in {CONTINUITY_TYPE, COST_TYPE}:
        expected = build_evidence_intake_event("CONTINUITY" if event.event_type == CONTINUITY_TYPE else "COST",
            event.payload["export"], blobs, recorded_at=event.recorded_at)
    elif event.event_type == RISK_TYPE:
        expected = build_risk_review_event(event.payload["review"], previous_events, blobs)
    elif event.event_type == STUDY_TYPE:
        expected = build_reviewed_study_event(event.payload["study"], previous_events, blobs)
    elif event.event_type == EVALUATION_TYPE:
        expected = build_reviewed_evaluation_event(event.payload["study"], previous_events, blobs,
            evaluation_id=event.source["evaluation_id"], recorded_at=event.recorded_at)
    else:
        raise ValueError("unsupported governed evidence/review event")
    if expected.to_bytes() != event.to_bytes():
        raise ValueError("governed evidence/review event differs from exact retained-input replay")
