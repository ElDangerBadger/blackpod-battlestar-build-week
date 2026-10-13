"""Passive Brigade request linking a verified forecast intake to retained evidence."""
from collections.abc import Mapping
from .decision_journal import _enum, _hash, _identifier, _object
from .investment_review import _event_id, _list, disabled_authority
from .mission_request import ContractValidationError, parse_rfc3339
from .trading_accounting import accounting_timestamp
from .trading_reconciliation import _ReconciliationDocument, evidence_reference, symbol_text

SCHEMA_VERSION = "blackpod.brigade_shadow_request.v1"
SCHEMA_VERSION_V2 = "blackpod.brigade_shadow_request.v2"
RESPONSE_CONTRACT = "blackpod.brigade_member_response.v1"
REQUEST_SCOPE = "BRIGADE_RECOMMENDATIONS_ONLY"


def _request(value):
    version = value.get("schema_version") if isinstance(value, Mapping) else None
    fields = {"schema_version", "analysis_id", "recorded_at", "generated_at", "domain", "mode", "scope",
        "forecast", "market_evidence", "source_evidence", "symbols", "inference_mode", "transcript_evidence", "authority"}
    if version == SCHEMA_VERSION_V2:
        fields.add("response_contract")
    result = _object(value, fields, "Brigade shadow request")
    if type(version) is not str or version not in {SCHEMA_VERSION, SCHEMA_VERSION_V2}:
        raise ContractValidationError("unsupported Brigade shadow request schema_version")
    if version == SCHEMA_VERSION_V2 and result["response_contract"] != RESPONSE_CONTRACT:
        raise ContractValidationError("unsupported Brigade response contract")
    for key, expected in (("domain", "TRADING"), ("mode", "SHADOW"), ("scope", REQUEST_SCOPE)):
        if result[key] != expected:
            raise ContractValidationError(key + " must be " + repr(expected))
    result["analysis_id"] = _identifier(result["analysis_id"], "analysis_id")
    for key in ("recorded_at", "generated_at"):
        result[key] = accounting_timestamp(result[key], key)
    if parse_rfc3339(result["generated_at"], "generated_at") > parse_rfc3339(result["recorded_at"], "recorded_at"):
        raise ContractValidationError("generation time cannot postdate the recorded request")
    forecast = _object(result["forecast"], {"intake_event_id", "intake_id", "intake_source_sha256", "intake_evidence"}, "forecast")
    forecast["intake_event_id"] = _event_id(forecast["intake_event_id"], "intake_event_id")
    forecast["intake_id"] = _identifier(forecast["intake_id"], "intake_id")
    forecast["intake_source_sha256"] = _hash(forecast["intake_source_sha256"], "intake_source_sha256")
    forecast["intake_evidence"] = evidence_reference(forecast["intake_evidence"])
    result["forecast"] = forecast
    result["market_evidence"] = evidence_reference(result["market_evidence"])
    sources = _object(result["source_evidence"], {"brigade", "decay"}, "source_evidence")
    for key in sources:
        sources[key] = evidence_reference(sources[key])
    result["source_evidence"] = sources
    symbols = [symbol_text(item) for item in _list(result["symbols"], "symbols", nonempty=True)]
    if len(symbols) > 8 or len(symbols) != len(set(symbols)):
        raise ContractValidationError("Brigade request requires one to eight distinct symbols")
    result["symbols"] = sorted(symbols)
    result["inference_mode"] = _enum(result["inference_mode"], {"DISABLED", "RETAINED_TRANSCRIPT"}, "inference_mode")
    transcript = result["transcript_evidence"]
    if result["inference_mode"] == "DISABLED" and transcript is not None:
        raise ContractValidationError("disabled inference cannot claim a generated transcript")
    if result["inference_mode"] == "RETAINED_TRANSCRIPT":
        result["transcript_evidence"] = evidence_reference(transcript)
    references = [forecast["intake_evidence"], result["market_evidence"], *sources.values()]
    if result["transcript_evidence"] is not None:
        references.append(result["transcript_evidence"])
    if len({item["path"] for item in references}) != len(references):
        raise ContractValidationError("Brigade evidence paths must be distinct")
    result["authority"] = disabled_authority(result["authority"])
    return result


class BrigadeShadowRequest(_ReconciliationDocument):
    __slots__ = ()
    _validator = staticmethod(_request)
