"""Passive producer export audit; replay never fits models or calls providers."""
from .contracts.decision_journal import JournalEvent
from .contracts.forecast_producer import ForecastProducerRequest
from .forecast_journal import identity
from .forecast_producer_export import validate_forecast_producer_export_bundle
from .hashing import sha256_bytes


def build_forecast_producer_event(export, blobs):
    validated = validate_forecast_producer_export_bundle(export, blobs)
    export = validated["export"]
    request = ForecastProducerRequest.from_bytes(blobs[export["request_evidence"]["sha256"]])
    decision_id = identity("journal-decision", {"kind": "FORECAST_PRODUCER_EXPORT", "run_id": request.run_id})
    return JournalEvent.from_mapping({"schema_version": "blackpod.decision_journal_event.v10",
        "event_id": identity("journal-event", {"decision_id": decision_id, "event_type": "FORECAST_PRODUCER_EXPORT_RECORDED"}),
        "decision_id": decision_id, "domain": "TRADING", "event_type": "FORECAST_PRODUCER_EXPORT_RECORDED", "recorded_at": export["issued_at"],
        "source": {"kind": "FORECAST_PRODUCER_EXPORT", "run_id": request.run_id, "source_sha256": sha256_bytes(request.to_bytes())},
        "evidence": export["source_evidence"], "payload": {"request": request.to_dict(), "export": export}})


def validate_forecast_producer_event(event, previous_events, blobs):
    expected = build_forecast_producer_event(event.payload["export"], blobs)
    if expected.to_bytes() != event.to_bytes():
        raise ValueError("producer event does not reproduce its original source/model export")
