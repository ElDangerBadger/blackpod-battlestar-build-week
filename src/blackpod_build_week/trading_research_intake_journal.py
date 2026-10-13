"""Passive hypothesis and historical intake records with retained-input replay."""
from .contracts.decision_journal import JournalEvent
from .contracts.mission_request import parse_rfc3339
from .contracts.trading_accounting import accounting_timestamp
from .contracts.trading_hypothesis import TradingHypothesisCatalog, TradingHypothesis
from .contracts.historical_intake import HistoricalIntakeExport
from .hashing import sha256_bytes
from .trading_hypotheses import catalog_documents, hypothesis_research_strategy
from .trading_historical_intake import verify_historical_intake, validate_historical_dataset
from .trading_research_journal import identity, _blob

CATALOG_TYPE = "TRADING_HYPOTHESIS_CATALOG_RECORDED"
INTAKE_TYPE = "TRADING_HISTORICAL_INTAKE_RECORDED"


def catalog_evidence(catalog):
    catalog = catalog if isinstance(catalog, TradingHypothesisCatalog) else TradingHypothesisCatalog.from_mapping(catalog)
    retained = {"trading-hypotheses/catalog.v1.json": catalog.to_bytes()}
    retained.update({"trading-hypotheses/" + doc.hypothesis_id + ".v1.json": doc.to_bytes()
                     for doc in catalog_documents(catalog)})
    return retained


def _event(kind, id_key, document, payload_key, retained, recorded_at, event_type):
    decision_id = identity("journal-decision", {"kind": kind, id_key: getattr(document, id_key)})
    return JournalEvent.from_mapping({"schema_version": "blackpod.decision_journal_event.v13",
        "event_id": identity("journal-event", {"decision_id": decision_id, "event_type": event_type}),
        "decision_id": decision_id, "domain": "TRADING", "event_type": event_type, "recorded_at": recorded_at,
        "source": {"kind": kind, id_key: getattr(document, id_key), "source_sha256": sha256_bytes(document.to_bytes())},
        "evidence": [{"path": path, "sha256": sha256_bytes(raw), "size_bytes": len(raw)}
                     for path, raw in sorted(retained.items())], "payload": {payload_key: document.to_dict()}})


def build_catalog_event(catalog):
    catalog = catalog if isinstance(catalog, TradingHypothesisCatalog) else TradingHypothesisCatalog.from_mapping(catalog)
    return _event("TRADING_HYPOTHESIS_CATALOG", "catalog_id", catalog, "catalog",
                  catalog_evidence(catalog), catalog.recorded_at, CATALOG_TYPE)


def intake_evidence(export, blobs):
    material = verify_historical_intake(export, blobs)
    retained = dict(material["evidence"])
    path = "historical-intake/export.v1.json"
    if path in retained:
        raise ValueError("historical evidence collides with reserved export path")
    retained[path] = material["export"].to_bytes()
    return retained


def build_intake_event(export, blobs, *, recorded_at):
    export = export if isinstance(export, HistoricalIntakeExport) else HistoricalIntakeExport.from_mapping(export)
    material = verify_historical_intake(export, blobs)
    recorded_at = accounting_timestamp(recorded_at, "recorded_at")
    if parse_rfc3339(recorded_at, "recorded_at") < parse_rfc3339(material["dataset"].recorded_at, "dataset clock"):
        raise ValueError("intake journal clock cannot predate its capture")
    return _event("TRADING_HISTORICAL_INTAKE", "intake_id", export, "export",
                  intake_evidence(export, blobs), recorded_at, INTAKE_TYPE)


def validate_intake_event(event, previous_events, blobs):
    if event.event_type == CATALOG_TYPE:
        expected = build_catalog_event(event.payload["catalog"])
    elif event.event_type == INTAKE_TYPE:
        expected = build_intake_event(event.payload["export"], blobs, recorded_at=event.recorded_at)
    else:
        raise ValueError("unsupported research intake event")
    if expected.to_bytes() != event.to_bytes():
        raise ValueError("research intake differs from deterministic retained-input replay")


def governed_links(plan, dataset, events, blobs):
    """Bind exact frozen hypothesis and rebuilt dataset to preceding journal events."""
    validate_historical_dataset(dataset, blobs)
    hypothesis = TradingHypothesis.from_bytes(_blob(blobs, plan.frozen_hypothesis_evidence))
    components = hypothesis_research_strategy(hypothesis)
    if plan.strategy != components["strategy"] or plan.horizon != components["horizon"]:
        raise ValueError("plan strategy/horizon differs from its frozen hypothesis")
    catalogs = [event for event in events if event.event_type == CATALOG_TYPE and
                hypothesis.to_dict() in event.payload["catalog"]["hypotheses"] and
                plan.frozen_hypothesis_evidence in event.evidence]
    intakes = [event for event in events if event.event_type == INTAKE_TYPE and
               event.payload["export"]["dataset_evidence"] == plan.dataset_evidence and
               event.payload["export"]["request_evidence"] == dataset.provenance["governed_intake"]["request_evidence"]]
    if len(catalogs) != 1 or len(intakes) != 1:
        raise ValueError("v2 plan requires unique preceding frozen catalog and governed intake")
    if any(parse_rfc3339(event.recorded_at, "source clock") > parse_rfc3339(plan.registered_at, "plan clock")
           for event in (catalogs[0], intakes[0])):
        raise ValueError("plan cannot predate its frozen catalog or intake")
    return {"hypothesis_event_id": catalogs[0].event_id, "intake_event_id": intakes[0].event_id}
