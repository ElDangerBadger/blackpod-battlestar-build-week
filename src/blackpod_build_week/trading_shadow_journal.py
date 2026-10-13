"""Passive governed shadow study registration and deterministic linked replay."""
from pathlib import Path

from .contracts.decision_journal import JournalEvent, _identifier
from .contracts.mission_request import parse_rfc3339
from .contracts.trading_accounting import accounting_timestamp
from .contracts.trading_hypothesis import TradingHypothesis
from .contracts.trading_research import TradingResearchPlan
from .contracts.trading_shadow_research import TradingShadowStudy
from .hashing import sha256_bytes
from .sentry_history_cache import read_regular
from .trading_research_journal import identity, _blob, registered_context, evidence_for_research
from .trading_shadow_gates import shadow_gate_material

SCHEMA_VERSION = "blackpod.decision_journal_event.v15"
STUDY_TYPE = "TRADING_SHADOW_STUDY_REGISTERED"
EVALUATION_TYPE = "TRADING_SHADOW_EVALUATION_RECORDED"
CODE_PATHS = (
    "contracts/trading_shadow_research.py", "trading_shadow_gates.py",
    "trading_shadow_intents.py", "trading_shadow_evaluation.py",
    "trading_research_evaluation.py", "trading_historical_intake.py", "trading_hypotheses.py",
)


def _study(value):
    return value if isinstance(value, TradingShadowStudy) else TradingShadowStudy.from_mapping(value)


def _put(retained, path, raw):
    if path in retained and retained[path] != raw:
        raise ValueError("shadow study evidence path collision")
    retained[path] = raw


def implementation_evidence():
    root = Path(__file__).absolute().parent
    return {"trading-shadow/implementation/" + path: read_regular(root / path) for path in CODE_PATHS}


def _refs(retained):
    return [{"path": path, "sha256": sha256_bytes(raw), "size_bytes": len(raw)} for path, raw in sorted(retained.items())]


def shadow_context(study, events, blobs):
    study = _study(study)
    base = TradingResearchPlan.from_bytes(_blob(blobs, study.base_plan_evidence))
    if base.schema_version != "blackpod.trading_research_plan.v2":
        raise ValueError("shadow studies require a preceding v2 quality plan")
    base, dataset, _, original = registered_context(base, events, blobs)
    if parse_rfc3339(study.registered_at, "study clock") < parse_rfc3339(original.recorded_at, "base registration"):
        raise ValueError("shadow registration cannot predate its base plan")
    hypothesis = TradingHypothesis.from_bytes(_blob(blobs, base.frozen_hypothesis_evidence))
    gates = shadow_gate_material(study, base, dataset, blobs)
    links = {"base_plan_event_id": original.event_id,
             "hypothesis_event_id": original.payload["hypothesis_event_id"],
             "intake_event_id": original.payload["intake_event_id"]}
    return {"study": study, "base_plan": base, "dataset": dataset, "hypothesis": hypothesis,
            "gate_assessment": gates["assessment"], "gate_evidence": gates["evidence"], "links": links}


def evidence_for_shadow(study, events, blobs):
    context = shadow_context(study, events, blobs)
    study = context["study"]
    retained = evidence_for_research(context["base_plan"], blobs)
    _put(retained, study.base_plan_evidence["path"], _blob(blobs, study.base_plan_evidence))
    for path, raw in context["gate_evidence"].items():
        _put(retained, path, raw)
    for path, raw in implementation_evidence().items():
        if path in retained:
            raise ValueError("source evidence collides with reserved implementation path")
        retained[path] = raw
    path = "trading-shadow/study.v1.json"
    if path in retained:
        raise ValueError("source evidence collides with reserved study path")
    retained[path] = study.to_bytes()
    return retained


def _prefix(study, events):
    events = tuple(events)
    for index, event in enumerate(events):
        if event.event_type == STUDY_TYPE and event.source["study_id"] == study.study_id:
            if event.payload["study"] != study.to_dict():
                raise ValueError("registered shadow study identity is immutable")
            return events[:index]
    return events


def _signature(study):
    return {key: study.to_dict()[key] for key in ("base_plan_evidence", "price_continuity_evidence",
        "cost_evidence", "benchmark", "cost_stress_multipliers", "evidence_scope")}


def _event(study, event_type, evidence, payload, *, recorded_at, evaluation_id=None):
    decision_id = identity("journal-decision", {"kind": "TRADING_SHADOW_STUDY", "experiment_id": study.experiment_id,
        "trial_id": study.trial_registry["trial_id"]})
    event_identity = {"decision_id": decision_id, "event_type": event_type}
    source = {"kind": "TRADING_SHADOW_STUDY" if event_type == STUDY_TYPE else "TRADING_SHADOW_EVALUATION",
        "study_id": study.study_id, "experiment_id": study.experiment_id,
        "trial_id": study.trial_registry["trial_id"], "source_sha256": sha256_bytes(study.to_bytes())}
    if evaluation_id is not None:
        source["evaluation_id"] = evaluation_id
        event_identity["evaluation_id"] = evaluation_id
    return JournalEvent.from_mapping({"schema_version": SCHEMA_VERSION,
        "event_id": identity("journal-event", event_identity), "decision_id": decision_id,
        "domain": "TRADING", "event_type": event_type, "recorded_at": recorded_at,
        "source": source, "evidence": _refs(evidence), "payload": {"study": study.to_dict(), **payload}})


def build_study_event(study, events=(), blobs=None):
    study = _study(study); blobs = blobs or {}
    previous = _prefix(study, events)
    context = shadow_context(study, previous, blobs)
    peers = [event for event in previous if event.event_type == STUDY_TYPE and event.source["experiment_id"] == study.experiment_id]
    prior = sorted(event.source["trial_id"] for event in peers)
    if sorted(study.trial_registry["prior_trial_ids"]) != prior or study.trial_registry["trial_id"] in prior:
        raise ValueError("shadow registry must retain every preceding trial in this experiment")
    if any(_signature(TradingShadowStudy.from_mapping(event.payload["study"])) != _signature(study) for event in peers):
        raise ValueError("shadow evidence or benchmark changes require a distinct experiment")
    if any(parse_rfc3339(event.recorded_at, "previous clock") > parse_rfc3339(study.registered_at, "study clock") for event in peers):
        raise ValueError("shadow trial cannot predate experiment history")
    evidence = evidence_for_shadow(study, previous, blobs)
    return _event(study, STUDY_TYPE, evidence, {**context["links"], "gate_assessment": context["gate_assessment"],
        "implementation_evidence": _refs(implementation_evidence())}, recorded_at=study.registered_at)


def registered_shadow_context(study, events, blobs):
    study = _study(study); events = tuple(events)
    original = next((event for event in events if event.event_type == STUDY_TYPE and event.source["study_id"] == study.study_id), None)
    if original is None or original.payload["study"] != study.to_dict():
        raise ValueError("shadow evaluation requires exact preceding immutable study registration")
    prefix = events[:events.index(original)]
    context = shadow_context(study, prefix, blobs)
    if context["gate_assessment"] != original.payload["gate_assessment"] or any(
            original.payload[key] != value for key, value in context["links"].items()):
        raise ValueError("shadow evaluation source links or evidence gates changed")
    if _refs(implementation_evidence()) != original.payload["implementation_evidence"]:
        raise ValueError("registered shadow implementation differs from installed version; create a new versioned study")
    return context, original


def assess_registered_shadow(study, events, blobs):
    from .trading_shadow_intents import produce_shadow_intents
    from .trading_shadow_evaluation import evaluate_shadow_study
    context, original = registered_shadow_context(study, events, blobs)
    study = context["study"]
    production = produce_shadow_intents(study, context["base_plan"], context["dataset"], context["hypothesis"], context["gate_assessment"])
    result = evaluate_shadow_study(study, context["base_plan"], context["dataset"], context["hypothesis"], production, context["gate_assessment"])
    result["trial_registry"] = {**study.trial_registry, "declared_trial_count_at_registration": len(study.trial_registry["prior_trial_ids"]) + 1,
        "global_trial_completeness_verified": False, "prospective_preregistration_verified": False}
    return {"production": production, "result": result}


def build_shadow_evaluation_event(study, events, blobs, *, evaluation_id, recorded_at):
    context, original = registered_shadow_context(study, events, blobs)
    study = context["study"]
    evaluation_id = _identifier(evaluation_id, "evaluation_id")
    recorded_at = accounting_timestamp(recorded_at, "recorded_at")
    if parse_rfc3339(recorded_at, "evaluation clock") < parse_rfc3339(study.registered_at, "study clock"):
        raise ValueError("shadow evaluation cannot predate its registration")
    assessment = assess_registered_shadow(study, events, blobs)
    evidence = evidence_for_shadow(study, events, blobs)
    return _event(study, EVALUATION_TYPE, evidence, {**context["links"], "study_event_id": original.event_id,
        "gate_assessment": context["gate_assessment"], "implementation_evidence": original.payload["implementation_evidence"],
        **assessment}, recorded_at=recorded_at, evaluation_id=evaluation_id)


def validate_shadow_event(event, previous_events, blobs):
    if event.event_type == STUDY_TYPE:
        expected = build_study_event(event.payload["study"], previous_events, blobs)
    elif event.event_type == EVALUATION_TYPE:
        expected = build_shadow_evaluation_event(event.payload["study"], previous_events, blobs,
            evaluation_id=event.source["evaluation_id"], recorded_at=event.recorded_at)
    else:
        raise ValueError("unsupported shadow study event")
    if event.to_bytes() != expected.to_bytes():
        raise ValueError("shadow journal event differs from retained-input deterministic replay")
