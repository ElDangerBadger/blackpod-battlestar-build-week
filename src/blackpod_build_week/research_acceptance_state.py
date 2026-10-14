"""Read-only source-bound eligibility, integrity and outcome projection.

Callers obtain the history from JournalStore.verified_contents(). This pure
function additionally replays the exact selected v17 assessment and its native
sources, not unrelated later history. It never appends, rescales a metric,
admits new evidence, or changes an original classification.
"""
from pathlib import Path

from .contracts.research_acceptance_state import ResearchAcceptanceState, SCHEMA_VERSION, METHOD_VERSION, evaluation_state
from .contracts.research_assessment import EVENT_TYPE, GOVERNANCE_STATUS
from .hashing import sha256_bytes
from .research_acceptance_journal import validate_assessment_event
from .sentry_history_cache import read_regular
from .trading_research_journal import _blob

CODE_PATHS = ("contracts/research_acceptance_state.py", "research_acceptance_state.py")


def implementation_evidence():
    root = Path(__file__).absolute().parent
    return [{"path": "research-acceptance-state/implementation/" + path,
             "sha256": sha256_bytes(raw), "size_bytes": len(raw)}
            for path in CODE_PATHS for raw in (read_regular(root / path),)]


def project_assessment_state(assessment_event_id, events, blobs):
    """Select exactly one retained assessment; missing/corrupt history rejects."""
    events = tuple(events)
    if len({event.event_id for event in events}) != len(events):
        raise ValueError("state requires unique source event identities")
    matches = [event for event in events if event.event_id == assessment_event_id and event.event_type == EVENT_TYPE]
    if len(matches) != 1:
        raise ValueError("state requires an exact retained v17 assessment event")
    event = matches[0]
    for reference in event.evidence:
        _blob(blobs, reference)
    prefix = events[:events.index(event)]
    validate_assessment_event(event, prefix, blobs)
    assessment = event.payload["assessment"]
    references = [ref for ref in event.evidence if ref["path"] == "research-acceptance/assessment.v1.json"]
    if len(references) != 1:
        raise ValueError("state requires the exact retained assessment leaf")
    request = assessment["request"]
    hypothesis_ref = request["hypothesis"]["evidence"]
    if request["domain"] == "TRADING":
        from .contracts.trading_hypothesis import TradingHypothesis
        from .contracts.trading_research import TradingResearchPlan
        document = TradingHypothesis.from_bytes(_blob(blobs, hypothesis_ref))
        research = next(item for item in prefix if item.event_id == request["research_event_id"])
        if "plan" in research.payload:
            plan = TradingResearchPlan.from_mapping(research.payload["plan"])
            matches = [ref for ref in research.evidence if _blob(blobs, ref) == plan.to_bytes()]
            if len(matches) != 1:
                raise ValueError("state requires the original retained Trading plan leaf")
            plan_ref = matches[0]
        else:
            plan_ref = research.payload["study"]["base_plan_evidence"]
            plan = TradingResearchPlan.from_bytes(_blob(blobs, plan_ref))
        trading_plan = {"document_evidence": plan_ref, "document": plan.to_dict()}
        market_scope = {"kind": "SYMBOL", "identifiers": plan.universe}
    else:
        from .contracts.investment_hypothesis import InvestmentHypothesis
        document = InvestmentHypothesis.from_bytes(_blob(blobs, hypothesis_ref))
        market_scope = document.scope
        trading_plan = None
    return ResearchAcceptanceState.from_mapping({"schema_version": SCHEMA_VERSION, "method_version": METHOD_VERSION,
        "domain": event.domain, "source_assessment_event": {"event_id": event.event_id,
            "event_sha256": sha256_bytes(event.to_bytes()), "assessment_evidence": references[0]},
        "source_assessment": assessment, "original_classification": assessment["classification"],
        "hypothesis": {"source_event_id": request["hypothesis"]["source_event_id"],
            "document_evidence": hypothesis_ref, "document": document.to_dict(), "market_scope": market_scope},
        "trading_plan": trading_plan,
        **evaluation_state(assessment), "implementation_evidence": implementation_evidence(),
        "governance_status": GOVERNANCE_STATUS, "auto_trading_enabled": False, "authority": request["authority"]})
