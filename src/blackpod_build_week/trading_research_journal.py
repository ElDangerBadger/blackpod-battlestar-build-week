"""Immutable offline experiment registration and simulated evaluation records.

No strategy producer, provider, broker or execution adapter is imported here.
Registered inputs stay frozen; later outcomes append independently. Registry
completeness and registration timestamps are local declarations, not proof of
prospective research or blinded access to historical prices.
"""
from .contracts.decision_journal import JournalEvent
from .contracts.mission_request import parse_rfc3339, parse_strict_json_object_bytes
from .contracts.trading_reconciliation import evidence_reference
from .contracts.trading_research import (
    TradingResearchPlan, TradingResearchDataset, TradingResearchIntents,
    validate_research_inputs,
)
from .hashing import canonical_json_bytes, sha256_bytes

PLAN_TYPE = "TRADING_RESEARCH_PLAN_REGISTERED"
EVALUATION_TYPE = "TRADING_RESEARCH_EVALUATION_RECORDED"
SCHEMA_VERSION = "blackpod.decision_journal_event.v12"


def identity(prefix, value):
    return prefix + "-" + sha256_bytes(canonical_json_bytes(value))


def _plan(value):
    return value if isinstance(value, TradingResearchPlan) else TradingResearchPlan.from_mapping(value)


def _blob(blobs, reference):
    raw = blobs.get(reference["sha256"])
    if not isinstance(raw, bytes) or len(raw) != reference["size_bytes"] or sha256_bytes(raw) != reference["sha256"]:
        raise ValueError("offline research evidence differs in hash or size")
    return raw


def research_inputs(plan, blobs):
    plan = _plan(plan)
    dataset = TradingResearchDataset.from_bytes(_blob(blobs, plan.dataset_evidence))
    intents = TradingResearchIntents.from_bytes(_blob(blobs, plan.intents_evidence))
    validate_research_inputs(plan, dataset, intents)
    _source_closure(dataset, blobs)
    return plan, dataset, intents


def _references(value, depth=0):
    if depth > 24:
        raise ValueError("research source reference nesting exceeds supported limits")
    if isinstance(value, dict):
        if set(value) == {"path", "sha256", "size_bytes"}:
            yield evidence_reference(value)
        else:
            for item in value.values():
                yield from _references(item, depth+1)
    elif isinstance(value, list):
        for item in value:
            yield from _references(item, depth+1)


def _source_closure(dataset, blobs):
    """Keep recursively bound source bytes, not only their immediate wrapper."""
    if dataset.schema_version == "blackpod.trading_research_dataset.v2":
        from .trading_historical_intake import validate_historical_dataset
        return dict(validate_historical_dataset(dataset, blobs)["evidence"])
    pending = list(dataset.provenance["source_evidence"])
    visited, retained = set(), {}
    while pending:
        reference = evidence_reference(pending.pop())
        identity = (reference["path"], reference["sha256"], reference["size_bytes"])
        if identity in visited:
            continue
        if len(visited) >= 256:
            raise ValueError("research source closure exceeds its retained-file bound")
        visited.add(identity)
        raw = _blob(blobs, reference)
        if reference["path"] in retained and retained[reference["path"]] != raw:
            raise ValueError("research source paths bind conflicting bytes")
        retained[reference["path"]] = raw
        if reference["path"].endswith('.json'):
            pending.extend(_references(parse_strict_json_object_bytes(raw)))
    return retained


def evidence_for_research(plan, blobs):
    plan, dataset, intents = research_inputs(plan, blobs)
    retained = _source_closure(dataset, blobs)
    for ref in (plan.dataset_evidence, plan.intents_evidence):
        raw = _blob(blobs, ref)
        if ref["path"] in retained and retained[ref["path"]] != raw:
            raise ValueError("offline research source paths bind conflicting bytes")
        retained[ref["path"]] = raw
    if plan.schema_version == "blackpod.trading_research_plan.v2":
        reference = plan.frozen_hypothesis_evidence
        raw = _blob(blobs, reference)
        if reference["path"] in retained and retained[reference["path"]] != raw:
            raise ValueError("frozen hypothesis path binds conflicting bytes")
        retained[reference["path"]] = raw
    path = "trading-research/registered-plan.v2.json" if plan.schema_version.endswith(".v2") else "trading-research/registered-plan.v1.json"
    if path in retained:
        raise ValueError("research source evidence collides with its reserved plan path")
    retained[path] = plan.to_bytes()
    return retained


def _prefix_before_existing_plan(plan, events):
    events = tuple(events)
    for index, event in enumerate(events):
        if event.event_type == PLAN_TYPE and event.source["plan_id"] == plan.plan_id:
            if event.source["source_sha256"] != sha256_bytes(plan.to_bytes()):
                raise ValueError("registered research plan identity is immutable")
            return events[:index]
    return events


def _experiment_signature(plan):
    value = plan.to_dict()
    return {key: value[key] for key in ("universe", "horizon", "dataset_evidence", "protocol", "cost_model", "risk", "benchmark")}


def build_plan_event(plan, events=(), blobs=None):
    plan = _plan(plan); blobs = blobs or {}
    previous = _prefix_before_existing_plan(plan, events)
    peers = [event for event in previous if event.event_type == PLAN_TYPE and event.source["experiment_id"] == plan.experiment_id]
    prior = sorted(event.source["trial_id"] for event in peers)
    if sorted(plan.trial_registry["prior_trial_ids"]) != prior or plan.trial_registry["trial_id"] in prior:
        raise ValueError("trial registry must retain every preceding trial in this experiment")
    if any(_experiment_signature(TradingResearchPlan.from_mapping(event.payload["plan"])) != _experiment_signature(plan) for event in peers):
        raise ValueError("comparison protocol/data/cost/risk changes require a separate experiment identity")
    if any(parse_rfc3339(event.recorded_at, "previous registration") > parse_rfc3339(plan.registered_at, "registered_at") for event in peers):
        raise ValueError("trial registration cannot precede its declared experiment history")
    evidence = evidence_for_research(plan, blobs)
    links = {}
    if plan.schema_version.endswith(".v2"):
        from .trading_research_intake_journal import governed_links
        _, dataset, _ = research_inputs(plan, blobs)
        links = governed_links(plan, dataset, previous, blobs)
    decision_id = identity("journal-decision", {"kind": "TRADING_RESEARCH", "experiment_id": plan.experiment_id, "trial_id": plan.trial_registry["trial_id"]})
    return JournalEvent.from_mapping({"schema_version": "blackpod.decision_journal_event.v14" if links else SCHEMA_VERSION,
        "event_id": identity("journal-event", {"decision_id": decision_id, "event_type": PLAN_TYPE}),
        "decision_id": decision_id, "domain": "TRADING", "event_type": PLAN_TYPE, "recorded_at": plan.registered_at,
        "source": {"kind": "TRADING_RESEARCH_PLAN", "plan_id": plan.plan_id, "experiment_id": plan.experiment_id,
            "trial_id": plan.trial_registry["trial_id"], "source_sha256": sha256_bytes(plan.to_bytes())},
        "evidence": [{"path": path, "sha256": sha256_bytes(raw), "size_bytes": len(raw)} for path, raw in sorted(evidence.items())],
        "payload": {"plan": plan.to_dict(), **links}})


def registered_context(plan, events, blobs):
    plan = _plan(plan)
    original = next((event for event in events if event.event_type == PLAN_TYPE and event.source["plan_id"] == plan.plan_id), None)
    if original is None:
        raise ValueError("offline evaluation requires preceding immutable plan registration")
    if original.payload["plan"] != plan.to_dict() or original.source["source_sha256"] != sha256_bytes(plan.to_bytes()):
        raise ValueError("evaluation input differs from the original registered research plan")
    plan, dataset, intents = research_inputs(plan, blobs)
    if plan.schema_version.endswith(".v2"):
        from .trading_research_intake_journal import governed_links
        previous = tuple(events)[:tuple(events).index(original)]
        links = governed_links(plan, dataset, previous, blobs)
        if any(original.payload[key] != value for key, value in links.items()):
            raise ValueError("registered source links differ from preceding intake")
    return plan, dataset, intents, original


def assess_registered_research(plan, events, blobs):
    from .trading_research_evaluation import evaluate_research
    plan, dataset, intents, original = registered_context(plan, events, blobs)
    result = evaluate_research(plan, dataset, intents)
    result["trial_registry"] = {"registered_trial_id": plan.trial_registry["trial_id"],
        "prior_trial_ids": plan.trial_registry["prior_trial_ids"],
        "declared_trial_count_at_registration": len(plan.trial_registry["prior_trial_ids"]) + 1,
        "prospective_preregistration_verified": False, "global_trial_completeness_verified": False}
    return result


def build_evaluation_event(plan, events, blobs, *, evaluation_id, recorded_at):
    from .contracts.decision_journal import _identifier
    from .contracts.trading_accounting import accounting_timestamp
    evaluation_id = _identifier(evaluation_id, "evaluation_id")
    recorded_at = accounting_timestamp(recorded_at, "recorded_at")
    plan, dataset, intents, original = registered_context(plan, events, blobs)
    if parse_rfc3339(recorded_at, "recorded_at") < max(parse_rfc3339(value, "input clock") for value in (plan.registered_at, dataset.recorded_at, intents.created_at)):
        raise ValueError("evaluation record cannot predate its registration or retained input captures")
    # Freeze the registry context preceding this evaluation; later experiments
    # and outcome records cannot alter an exact retry's original evidence.
    result = assess_registered_research(plan, events, blobs)
    evidence = evidence_for_research(plan, blobs)
    links = {key: original.payload[key] for key in ("hypothesis_event_id", "intake_event_id")} if plan.schema_version.endswith(".v2") else {}
    return JournalEvent.from_mapping({"schema_version": "blackpod.decision_journal_event.v14" if links else SCHEMA_VERSION,
        "event_id": identity("journal-event", {"decision_id": original.decision_id, "event_type": EVALUATION_TYPE, "evaluation_id": evaluation_id}),
        "decision_id": original.decision_id, "domain": "TRADING", "event_type": EVALUATION_TYPE, "recorded_at": recorded_at,
        "source": {"kind": "TRADING_RESEARCH_EVALUATION", "plan_id": plan.plan_id, "experiment_id": plan.experiment_id,
            "trial_id": plan.trial_registry["trial_id"], "source_sha256": sha256_bytes(plan.to_bytes()), "evaluation_id": evaluation_id},
        "evidence": [{"path": path, "sha256": sha256_bytes(raw), "size_bytes": len(raw)} for path, raw in sorted(evidence.items())],
        "payload": {"plan": plan.to_dict(), "plan_event_id": original.event_id, "result": result, **links}})


def validate_research_event(event, previous_events, blobs):
    plan = event.payload["plan"]
    if event.event_type == PLAN_TYPE:
        expected = build_plan_event(plan, previous_events, blobs)
    elif event.event_type == EVALUATION_TYPE:
        expected = build_evaluation_event(plan, previous_events, blobs,
            evaluation_id=event.source["evaluation_id"], recorded_at=event.recorded_at)
    else:
        raise ValueError("unsupported trading research event")
    if expected.to_bytes() != event.to_bytes():
        raise ValueError("offline research event differs from deterministic retained-input replay")
