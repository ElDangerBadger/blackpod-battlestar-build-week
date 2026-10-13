"""Pure desk-specific research acceptance over verified frozen history.

This adapter never evaluates a sealed final holdout, changes original research,
or promotes a classification into operational authority. Hashes establish byte
identity and replay, not provider authenticity or economic truth.
"""
from pathlib import Path

from .contracts.research_assessment import (
    ADAPTER_FIELDS, ASSESSMENT_VERSION, EVENT_TYPE, GOVERNANCE_STATUS,
    ResearchAssessment, ResearchAssessmentRequest,
)
from .contracts.mission_request import parse_rfc3339
from .hashing import canonical_json_bytes, sha256_bytes
from .sentry_history_cache import read_regular
from .trading_research_journal import _blob

CODE_PATHS = ("contracts/research_assessment.py", "research_acceptance.py",
              "research_acceptance_trading.py", "research_acceptance_investment.py",
              "research_acceptance_journal.py")


def implementation_evidence():
    root = Path(__file__).absolute().parent
    return {"research-acceptance/implementation/" + path: read_regular(root / path) for path in CODE_PATHS}


def refs(evidence):
    return [{"path": path, "sha256": sha256_bytes(raw), "size_bytes": len(raw)} for path, raw in sorted(evidence.items())]


def prepare_request(events, *, research_event_id, assessment_id, recorded_at, data_cutoff_at,
                    assessment_scope="EXPLORATORY_RESEARCH", evaluation_event_id=None,
                    candidate_result_evidence=None, supersedes_event_id=None, blobs=None):
    """Build a declaration from an exact native registration, without scoring.

All clocks, scope and optional evaluation selection are operator-supplied.
No threshold, hypothesis, maturity, or expected outcome is manufactured here.
"""
    from .contracts.research_assessment import REQUEST_VERSION, METHODS
    events = tuple(events)
    matches = [event for event in events if event.event_id == research_event_id]
    if len(matches) != 1:
        raise ValueError("request preparation requires a unique native research event")
    research = matches[0]
    if research.domain == "INVESTMENT":
        if research.event_type == "INVESTMENT_HYPOTHESIS_RECORDED":
            source = research
        elif research.event_type == "INVESTMENT_CHALLENGE_RECORDED":
            matches = [event for event in events if event.event_id == research.payload["challenge"]["hypothesis_event_id"]]
            if len(matches) != 1:
                raise ValueError("challenge preparation requires its original hypothesis")
            source = matches[0]
        else:
            raise ValueError("Investment acceptance begins with a hypothesis or challenge, not approval")
        document = source.payload
        reference = next((ref for ref in source.evidence if ref["sha256"] == source.source["source_sha256"]), None)
    elif research.domain == "TRADING":
        if research.event_type == "TRADING_RESEARCH_PLAN_REGISTERED":
            plan = research.payload["plan"]
        elif research.event_type in {"TRADING_SHADOW_STUDY_REGISTERED", "TRADING_REVIEWED_SHADOW_STUDY_REGISTERED"}:
            from .contracts.trading_research import TradingResearchPlan
            if blobs is None:
                raise ValueError("shadow preparation needs retained base-plan bytes")
            plan = TradingResearchPlan.from_bytes(_blob(blobs, research.payload["study"]["base_plan_evidence"])).to_dict()
        else:
            raise ValueError("Trading acceptance begins with a governed registration, not an executable instruction")
        reference = plan.get("frozen_hypothesis_evidence")
        if reference is None:
            raise ValueError("native research requires an explicit frozen hypothesis reference")
        if blobs is None:
            raise ValueError("Trading preparation needs retained hypothesis bytes")
        from .contracts.trading_hypothesis import TradingHypothesis
        document = TradingHypothesis.from_bytes(_blob(blobs, reference)).to_dict()
        original_catalog_id = research.payload.get("hypothesis_event_id")
        matches = [event for event in events if event.event_id == original_catalog_id and event.event_type == "TRADING_HYPOTHESIS_CATALOG_RECORDED" and reference in event.evidence and document in event.payload["catalog"]["hypotheses"]]
        if len(matches) != 1:
            raise ValueError("preparation requires the exact original hypothesis catalog")
        source = matches[0]
    else:
        raise ValueError("acceptance has independently governed Trading and Investment domains only")
    if reference is None:
        raise ValueError("preparation cannot invent missing hypothesis evidence")
    return ResearchAssessmentRequest.from_mapping({"schema_version": REQUEST_VERSION, "assessment_id": assessment_id,
        "domain": source.domain, "recorded_at": recorded_at, "data_cutoff_at": data_cutoff_at,
        "assessment_scope": assessment_scope, "methodology_version": METHODS[source.domain],
        "hypothesis": {"hypothesis_id": document["hypothesis_id"], "source_event_id": source.event_id,
            "document_schema_version": document["schema_version"], "evidence": reference},
        "research_event_id": research.event_id, "evaluation_event_id": evaluation_event_id,
        "candidate_result_evidence": candidate_result_evidence, "supersedes_event_id": supersedes_event_id,
        "governance_status": GOVERNANCE_STATUS, "auto_trading_enabled": False,
        "authority": {field: False for field in ("authorization_enabled", "capital_activation_enabled", "execution_enabled", "policy_changes_enabled")}})


def merge_evidence(target, material):
    for path, raw in material.items():
        if not isinstance(raw, bytes) or (path in target and target[path] != raw):
            raise ValueError("research acceptance evidence path collision or non-byte content")
        target[path] = raw
    if len(target) > 512 or sum(map(len, target.values())) > 64 * 1024 * 1024:
        raise ValueError("research acceptance exceeds its bounded retained evidence closure")


def _key(request):
    request = request.to_dict() if hasattr(request, "to_dict") else request
    return (request["domain"], request["hypothesis"]["source_event_id"], request["hypothesis"]["hypothesis_id"],
            request["hypothesis"]["document_schema_version"], request["hypothesis"]["evidence"]["sha256"], request["assessment_scope"])


def assessment_context(request, events):
    """Exact retries use the original prefix; subsequent records cannot leak in."""
    request = request if isinstance(request, ResearchAssessmentRequest) else ResearchAssessmentRequest.from_mapping(request)
    events = tuple(events)
    if len({event.event_id for event in events}) != len(events):
        raise ValueError("research acceptance requires unique verified event identities")
    matches = [event for event in events if event.event_type == EVENT_TYPE and event.source["assessment_id"] == request.assessment_id]
    if len(matches) > 1 or (matches and matches[0].payload["request"] != request.to_dict()):
        raise ValueError("research assessment identity is immutable; record a new linked assessment")
    if matches:
        events = events[:events.index(matches[0])]
    source = next((event for event in events if event.event_id == request.hypothesis["source_event_id"]), None)
    if source is None or source.domain != request.domain:
        raise ValueError("research assessment requires its original same-desk hypothesis source")
    if request.hypothesis["evidence"] not in source.evidence:
        raise ValueError("research assessment hypothesis must match its exact original retained evidence")
    selected = [source]
    for identity in (request.research_event_id, request.evaluation_event_id):
        if identity is None:
            continue
        event = next((item for item in events if item.event_id == identity), None)
        if event is None or event.domain != request.domain:
            raise ValueError("research assessment requires preceding same-desk research and evaluation events")
        selected.append(event)
    if any(parse_rfc3339(event.recorded_at, "source clock") > parse_rfc3339(request.data_cutoff_at, "cutoff") for event in selected):
        raise ValueError("research source cannot follow declared data cutoff")
    prior = [event for event in events if event.event_type == EVENT_TYPE and _key(event.payload["request"]) == _key(request)]
    if any(parse_rfc3339(event.recorded_at, "prior assessment clock") > parse_rfc3339(request.recorded_at, "assessment clock") for event in prior):
        raise ValueError("assessment record clock cannot predate its prior same-scope assessment history")
    if request.supersedes_event_id is not None:
        superseded = next((event for event in prior if event.event_id == request.supersedes_event_id), None)
        if superseded is None:
            raise ValueError("supersession must link a preceding same-domain, hypothesis revision and assessment scope")
        if any(event.payload["request"]["supersedes_event_id"] == superseded.event_id for event in prior):
            raise ValueError("assessment supersession cannot branch from an already superseded record")
        old = superseded.payload["request"]
        if any(parse_rfc3339(getattr(request, field), field) < parse_rfc3339(old[field], field) for field in ("recorded_at", "data_cutoff_at")):
            raise ValueError("assessment supersession cannot move record clock or data cutoff backwards")
    return request, events, source, prior


def _pointer(value, pointer):
    for part in pointer[1:].split("/"):
        part = part.replace("~1", "/").replace("~0", "~")
        if isinstance(value, dict):
            value = value[part]
        elif isinstance(value, list) and part.isdigit() and (part == "0" or not part.startswith("0")):
            value = value[int(part)]
        else:
            raise ValueError("finding pointer cannot resolve a recorded value")
    return value


def _validate_findings(fields, events):
    by_id = {event.event_id: event for event in events}
    for finding in fields["findings"]:
        event_id = finding["evidence_event_id"]
        if event_id is not None and event_id not in by_id:
            raise ValueError("finding references unavailable event evidence")
        if finding["value_pointer"] is not None:
            try:
                observed = _pointer(by_id[event_id].to_dict(), finding["value_pointer"])
            except (KeyError, IndexError, TypeError, ValueError) as exc:
                raise ValueError("finding JSON pointer must resolve exact original evidence") from exc
            if canonical_json_bytes(observed) != canonical_json_bytes(finding["observed"]):
                raise ValueError("finding observation differs from exact source scalar")
    for mapping in fields["native_status_mapping"]:
        if mapping["source_event_id"] not in by_id:
            raise ValueError("native status mapping references unavailable history")


def assess_research(request, events, blobs):
    """Return a strict assessment and retained evidence, without any writes.

Callers obtain events/blobs from JournalStore.verified_contents(). Both native
adapters additionally replay their selected original records and source links.
"""
    request, events, source, prior = assessment_context(request, events)
    _blob(blobs, request.hypothesis["evidence"])
    if request.domain == "TRADING":
        from .research_acceptance_trading import assess_trading_acceptance
        material = assess_trading_acceptance(request, events, blobs)
    else:
        from .research_acceptance_investment import assess_investment_acceptance
        material = assess_investment_acceptance(request, events, blobs)
    fields = material["assessment_fields"]
    if set(fields) != ADAPTER_FIELDS:
        raise ValueError("desk acceptance adapter returned unsupported fields")
    _validate_findings(fields, events)
    evidence = dict(material["evidence"])
    merge_evidence(evidence, implementation_evidence())
    merge_evidence(evidence, {"research-acceptance/request.v1.json": request.to_bytes()})
    evaluation = next((event for event in events if event.event_id == request.evaluation_event_id), None)
    assessment = ResearchAssessment.from_mapping({"schema_version": ASSESSMENT_VERSION,
        "request": request.to_dict(), "hypothesis_revision": {"document_schema_version": request.hypothesis["document_schema_version"], "sha256": request.hypothesis["evidence"]["sha256"]},
        "evaluation_timestamp": None if evaluation is None else evaluation.recorded_at,
        "evidence": refs(evidence), **fields,
        "supporting_findings": [item["finding_id"] for item in fields["findings"] if item["effect"] == "SUPPORTS"],
        "contradictory_findings": [item["finding_id"] for item in fields["findings"] if item["effect"] == "CONTRADICTS"],
        "governance_status": GOVERNANCE_STATUS, "auto_trading_enabled": False, "authority": request.authority})
    return {"assessment": assessment, "evidence": evidence,
            "prior_assessment_event_ids": sorted(event.event_id for event in prior)}
