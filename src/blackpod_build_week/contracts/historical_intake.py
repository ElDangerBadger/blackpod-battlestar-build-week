"""Strict declarations for retained daily market research, never execution.

Receipts bind declared capture semantics to retained bytes. They are local
records, not provider authentication or historical point-in-time attestation.
"""
from __future__ import annotations

from datetime import date
import re

from .decision_journal import _enum, _hash, _identifier, _object, _string
from .investment_review import _fixed_boolean, disabled_authority
from .mission_request import ContractValidationError, parse_rfc3339
from .trading_accounting import accounting_timestamp
from .trading_reconciliation import _ReconciliationDocument, evidence_reference
from .trading_research import _integer, _universe

HISTORICAL_INTAKE_REQUEST_VERSION = "blackpod.trading_historical_intake_request.v1"
HISTORICAL_INTAKE_VERSION = "blackpod.historical_intake_export.v1"
HISTORICAL_CAPTURE_VERSION = "blackpod.read_only_historical_capture.v1"
HISTORICAL_INTAKE_SCOPE = "RETAINED_DAILY_RESEARCH_INTAKE_ONLY"
HISTORICAL_INTAKE_LIMITATIONS = (
    "LOCAL_CAPTURE_DECLARATION_NOT_PROVIDER_AUTHENTICATION",
    "RETROSPECTIVE_AVAILABILITY_ASSUMPTION_NOT_POINT_IN_TIME_VERIFIED",
    "RAW_PRICES_NO_CORPORATE_ACTIONS_OR_TOTAL_RETURN",
    "IEX_FEED_NOT_CONSOLIDATED_VOLUME_OR_EXECUTABLE_QUOTE",
    "FIXED_UNIVERSE_SURVIVORSHIP_NOT_CONTROLLED",
    "NO_EXECUTION_AUTHORITY",
)


def _constant(result, field, expected):
    if result[field] != expected:
        raise ContractValidationError(field + " must be " + repr(expected))


def historical_date(value, name):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value):
        raise ContractValidationError(name + " must be an ISO calendar date")
    try:
        date.fromisoformat(value)
    except ValueError as exc:
        raise ContractValidationError(name + " must be a valid calendar date") from exc
    return value


def _request(value):
    result = _object(value, {"schema_version", "run_id", "recorded_at", "domain", "mode", "scope",
        "universe", "date_range", "feed", "adjustment", "availability_assumption", "sources",
        "auto_trading_enabled", "authority"}, "historical intake request")
    for field, expected in (("schema_version", HISTORICAL_INTAKE_REQUEST_VERSION), ("domain", "TRADING"),
                            ("mode", "OFFLINE_RESEARCH"), ("scope", HISTORICAL_INTAKE_SCOPE),
                            ("feed", "IEX"), ("adjustment", "RAW")):
        _constant(result, field, expected)
    result["run_id"] = _identifier(result["run_id"], "run_id")
    result["recorded_at"] = accounting_timestamp(result["recorded_at"], "recorded_at")
    result["universe"] = _universe(result["universe"])
    dates = _object(result["date_range"], {"start", "end"}, "date_range")
    for field in dates:
        dates[field] = historical_date(dates[field], "date_range." + field)
    if dates["start"] > dates["end"]:
        raise ContractValidationError("date range must be chronological")
    result["date_range"] = dates
    assumption = _object(result["availability_assumption"], {"policy", "delay_seconds", "declared_by", "rationale"}, "availability assumption")
    _constant(assumption, "policy", "RETURNED_SESSION_END_PLUS_DECLARED_DELAY")
    assumption["delay_seconds"] = _integer(assumption["delay_seconds"], "delay_seconds", 0, 7 * 86400)
    assumption["declared_by"] = _identifier(assumption["declared_by"], "declared_by")
    assumption["rationale"] = _string(assumption["rationale"], "rationale", 10000)
    result["availability_assumption"] = assumption
    sources = _object(result["sources"], {"bars_evidence", "bars_receipt_evidence", "calendar_evidence", "calendar_receipt_evidence"}, "historical intake sources")
    result["sources"] = {field: evidence_reference(ref, field) for field, ref in sources.items()}
    if len({ref["path"] for ref in result["sources"].values()}) != 4:
        raise ContractValidationError("all historical source paths must be distinct")
    _fixed_boolean(result, "auto_trading_enabled", False)
    result["authority"] = disabled_authority(result["authority"])
    return result


class HistoricalIntakeRequest(_ReconciliationDocument):
    __slots__ = ()
    _validator = staticmethod(_request)


def validate_historical_intake_export(value):
    result = _object(value, {"schema_version", "intake_id", "request_evidence", "dataset_evidence", "coverage",
        "source_evidence", "limitations", "authority", "auto_trading_enabled"}, "historical intake export")
    _constant(result, "schema_version", HISTORICAL_INTAKE_VERSION)
    result["intake_id"] = _identifier(result["intake_id"], "intake_id")
    for field in ("request_evidence", "dataset_evidence"):
        result[field] = evidence_reference(result[field], field)
    coverage = _object(result["coverage"], {"requested_start", "requested_end", "calendar_sessions_in_window",
        "included_session_count", "included_start_session", "included_end_session", "excluded_unavailable_sessions"}, "coverage")
    for field in ("requested_start", "requested_end", "included_start_session", "included_end_session"):
        coverage[field] = historical_date(coverage[field], field)
    for field in ("calendar_sessions_in_window", "included_session_count"):
        coverage[field] = _integer(coverage[field], field, 1, 10000)
    from .investment_review import _list
    excluded = [historical_date(day, "excluded session") for day in _list(coverage["excluded_unavailable_sessions"], "excluded sessions")]
    if excluded != sorted(set(excluded)) or len(excluded) > 10000:
        raise ContractValidationError("excluded sessions must be bounded, sorted and unique")
    if coverage["included_session_count"] + len(excluded) != coverage["calendar_sessions_in_window"]:
        raise ContractValidationError("coverage must account for every returned session in the requested window")
    if not coverage["requested_start"] <= coverage["included_start_session"] <= coverage["included_end_session"] <= coverage["requested_end"]:
        raise ContractValidationError("included session interval must lie inside the requested dates")
    if any(not coverage["requested_start"] <= day <= coverage["requested_end"] for day in excluded):
        raise ContractValidationError("excluded sessions must lie inside the requested window")
    coverage["excluded_unavailable_sessions"] = excluded
    result["coverage"] = coverage
    refs = [evidence_reference(ref) for ref in _list(result["source_evidence"], "source_evidence")]
    if len(refs) != 5 or len({ref["path"] for ref in refs}) != 5 or result["request_evidence"] not in refs:
        raise ContractValidationError("source evidence must retain the request and four distinct sources")
    if result["dataset_evidence"]["path"] in {ref["path"] for ref in refs}:
        raise ContractValidationError("derived dataset must have a separate evidence path")
    result["source_evidence"] = refs
    if result["limitations"] != list(HISTORICAL_INTAKE_LIMITATIONS):
        raise ContractValidationError("historical intake limitations must remain explicit and complete")
    _fixed_boolean(result, "auto_trading_enabled", False)
    result["authority"] = disabled_authority(result["authority"])
    return result


class HistoricalIntakeExport(_ReconciliationDocument):
    __slots__ = ()
    _validator = staticmethod(validate_historical_intake_export)


def validate_historical_capture(value, kind):
    """Validate exact GET declaration; source/body/query binding is separate."""
    if kind not in ("bars", "calendar"):
        raise ContractValidationError("historical capture kind must be bars or calendar")
    result = _object(value, {"schema_version", "method", "url", "query", "captured_at", "status", "body_sha256", "size_bytes"}, "historical GET receipt")
    permitted_schema = {HISTORICAL_CAPTURE_VERSION}
    if kind == "calendar":
        permitted_schema.add("blackpod.read_only_calendar_capture.v1")
    if result["schema_version"] not in permitted_schema:
        raise ContractValidationError("unsupported historical capture version")
    _constant(result, "method", "GET")
    if type(result["status"]) is not int or result["status"] != 200:
        raise ContractValidationError("historical capture requires exact HTTP 200")
    allowed_url = "https://data.alpaca.markets/v2/stocks/bars" if kind == "bars" else "https://paper-api.alpaca.markets/v2/calendar"
    _constant(result, "url", allowed_url)
    result["captured_at"] = accounting_timestamp(result["captured_at"], "captured_at")
    result["body_sha256"] = _hash(result["body_sha256"], "body_sha256")
    result["size_bytes"] = _integer(result["size_bytes"], "size_bytes", 1, 64 * 1024 * 1024)
    if kind == "bars":
        query = _object(result["query"], {"symbols", "timeframe", "start", "end", "feed", "adjustment", "sort", "limit"}, "bars query")
        for field, expected in (("timeframe", "1Day"), ("feed", "iex"), ("adjustment", "raw"), ("sort", "asc")):
            _constant(query, field, expected)
        query["symbols"] = _string(query["symbols"], "query.symbols", 300)
        for field in ("start", "end"):
            query[field] = accounting_timestamp(query[field], "query." + field)
        if not parse_rfc3339(query["start"], "start") < parse_rfc3339(query["end"], "end"):
            raise ContractValidationError("bars request interval must be chronological")
        query["limit"] = _integer(query["limit"], "limit", 1, 10000)
    else:
        query = _object(result["query"], {"start", "end"}, "calendar query")
        for field in query:
            query[field] = historical_date(query[field], "calendar.query." + field)
        if query["start"] > query["end"]:
            raise ContractValidationError("calendar request dates must be chronological")
    result["query"] = query
    return result
