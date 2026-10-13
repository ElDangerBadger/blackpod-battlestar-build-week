"""Auto-trading request control, explicitly incapable of granting execution."""

from __future__ import annotations

from .decision_journal import _ImmutableDocument, _object, _identifier, _boolean, _enum
from .mission_request import ContractValidationError, normalize_rfc3339


TRADING_AUTOMATION_SCHEMA_VERSION = "blackpod.trading_automation_control.v1"
AUTOTRADING_EVENT_SCHEMA = "blackpod.decision_journal_event.v5"
AUTOTRADING_EVENT_TYPE = "TRADING_AUTOMATION_SWITCH_RECORDED"


def _control(value):
    result = _object(value, {"schema_version", "control_id", "operator_id", "recorded_at",
                             "switch_id", "requested_enabled", "scope", "domain",
                             "execution_mode", "origin"}, "trading automation control")
    for field, expected in {"schema_version": TRADING_AUTOMATION_SCHEMA_VERSION,
                            "switch_id": "auto-trading", "scope": "TRADING_CONTROL_INTENT_ONLY",
                            "domain": "TRADING", "execution_mode": "DISABLED"}.items():
        if result[field] != expected:
            raise ContractValidationError(f"trading automation {field} must be {expected!r}")
    for field in ("control_id", "operator_id"):
        result[field] = _identifier(result[field], field)
    result["recorded_at"] = normalize_rfc3339(result["recorded_at"], "recorded_at")
    result["requested_enabled"] = _boolean(result["requested_enabled"], "requested_enabled")
    result["origin"] = _enum(result["origin"], {"HUMAN_DECLARED", "SIMULATED_TEST"}, "origin")
    return result


class TradingAutomationControl(_ImmutableDocument):
    """Immutable ON/OFF intent, not a broker or automation permission."""

    __slots__ = ()
    _validator = staticmethod(_control)


def control_status(control: TradingAutomationControl) -> dict:
    return {"requested_enabled": control.requested_enabled,
            "effective_enabled": False,
            "state": "BLOCKED" if control.requested_enabled else "OFF",
            "reason_code": "INTENT_ONLY_NO_EXECUTION_AUTHORIZATION" if control.requested_enabled else "REQUESTED_OFF",
            "execution_mode": "DISABLED", "investment_approval_applies": False,
            "broker_calls_permitted": False, "capital_transfers_permitted": False}


def validate_automation_status(value: object, control: TradingAutomationControl) -> dict:
    expected = control_status(control)
    result = _object(value, set(expected), "automation status")
    for field in ("requested_enabled", "effective_enabled", "investment_approval_applies",
                  "broker_calls_permitted", "capital_transfers_permitted"):
        result[field] = _boolean(result[field], field)
    if result != expected:
        raise ContractValidationError("auto-trading intent cannot grant execution or investment authority")
    return result
