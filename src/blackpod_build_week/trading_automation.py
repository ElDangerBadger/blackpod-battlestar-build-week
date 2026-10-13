"""Persistent auto-trading ON/OFF intent with a closed execution boundary."""

from __future__ import annotations

from .contracts.decision_journal import JournalEvent
from .contracts.trading_automation import TradingAutomationControl, control_status, AUTOTRADING_EVENT_TYPE
from .contracts.mission_request import parse_rfc3339
from .hashing import canonical_json_bytes, sha256_bytes


def _identity(prefix, value):
    return prefix + "-" + sha256_bytes(canonical_json_bytes(value))


def evidence_for_automation(control: TradingAutomationControl) -> dict[str, bytes]:
    return {f"automation_controls/{control.control_id}/control.json": control.to_bytes()}


def build_automation_event(control: TradingAutomationControl) -> JournalEvent:
    control = TradingAutomationControl.from_mapping(control.to_dict())
    decision_id = _identity("journal-decision", {"kind": "TRADING_AUTOMATION_CONTROL",
                                                 "switch_id": control.switch_id})
    evidence = evidence_for_automation(control)
    return JournalEvent.from_mapping({
        "schema_version": "blackpod.decision_journal_event.v5",
        "event_id": _identity("journal-event", {"decision_id": decision_id,
                                                "event_type": AUTOTRADING_EVENT_TYPE,
                                                "control_id": control.control_id}),
        "decision_id": decision_id, "domain": "TRADING", "event_type": AUTOTRADING_EVENT_TYPE,
        "recorded_at": control.recorded_at,
        "source": {"kind": "TRADING_AUTOMATION_CONTROL", "control_id": control.control_id,
                   "source_sha256": sha256_bytes(control.to_bytes())},
        "evidence": [{"path": path, "sha256": sha256_bytes(raw), "size_bytes": len(raw)}
                     for path, raw in evidence.items()],
        "payload": {"control": control.to_dict(), "status": control_status(control)},
    })


def validate_automation_event(event, previous_events, blobs) -> None:
    control = TradingAutomationControl.from_mapping(event.payload["control"])
    if build_automation_event(control).to_bytes() != event.to_bytes():
        raise ValueError("automation event differs from its non-execution request control")
    if blobs.get(event.source["source_sha256"]) != control.to_bytes():
        raise ValueError("retained automation control differs from canonical input")
    prior = [item for item in previous_events if item.event_type == AUTOTRADING_EVENT_TYPE]
    if prior and parse_rfc3339(control.recorded_at, "recorded_at") < parse_rfc3339(prior[-1].recorded_at, "prior recorded_at"):
        raise ValueError("automation control cannot retreat recording time")


def auto_trading_status(events) -> dict:
    controls = [item for item in events if item.event_type == AUTOTRADING_EVENT_TYPE]
    if not controls:
        return {"requested_enabled": False, "effective_enabled": False, "state": "OFF",
                "reason_code": "REQUESTED_OFF", "execution_mode": "DISABLED",
                "investment_approval_applies": False, "broker_calls_permitted": False,
                "capital_transfers_permitted": False, "control_recorded": False,
                "control_id": None, "recorded_at": None}
    current = controls[-1]
    return {**current.payload["status"], "control_recorded": True,
            "control_id": current.source["control_id"], "recorded_at": current.recorded_at}
