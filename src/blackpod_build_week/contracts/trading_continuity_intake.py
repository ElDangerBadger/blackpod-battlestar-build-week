"""Closed retained corporate-action declarations, without execution authority.

The vendor endpoint filters process dates. A completed response is not proof
that every ex-date action affecting a historical price interval was returned.
"""
from __future__ import annotations

from .decision_journal import _boolean, _enum, _identifier, _object, _string
from .historical_intake import historical_date
from .investment_review import _fixed_boolean, _list, disabled_authority
from .mission_request import ContractValidationError
from .trading_accounting import accounting_timestamp
from .trading_reconciliation import _ReconciliationDocument, evidence_reference
from .trading_research import _integer, _universe, research_symbol

CONTINUITY_INTAKE_REQUEST_VERSION = "blackpod.trading_continuity_intake_request.v1"
CONTINUITY_INTAKE_EXPORT_VERSION = "blackpod.trading_continuity_intake_export.v1"
CONTINUITY_COVERAGE_REVIEW_VERSION = "blackpod.trading_continuity_coverage_review.v1"
CORPORATE_ACTION_URL = "https://data.alpaca.markets/v1/corporate-actions"
CONTINUITY_LIMITATIONS = (
    "LOCAL_CAPTURE_DECLARATION_NOT_PROVIDER_AUTHENTICATION",
    "PROCESS_DATE_FILTER_NOT_EX_DATE_COVERAGE_PROOF",
    "RAW_PRICE_DISCONTINUITIES_DEFER_ENTIRE_DATASET",
    "UNKNOWN_EFFECTIVE_DATES_ARE_UNRESOLVED",
    "NO_PRICE_ADJUSTMENT_OR_TOTAL_RETURN_REPAIR",
    "NO_EXECUTION_OR_CAPITAL_AUTHORITY",
)


def _constant(row, field, expected):
    if row[field] != expected or type(row[field]) is not type(expected):
        raise ContractValidationError(field + " must be " + repr(expected))


def _refs(value, name):
    refs = [evidence_reference(item, name) for item in _list(value, name)]
    if not 1 <= len(refs) <= 128 or len({ref["path"] for ref in refs}) != len(refs):
        raise ContractValidationError(name + " must have bounded distinct evidence paths")
    return refs


def _safe(row):
    _fixed_boolean(row, "auto_trading_enabled", False)
    row["authority"] = disabled_authority(row["authority"])
    return row


def _request(value):
    row = _object(value, {"schema_version", "run_id", "recorded_at", "domain", "mode", "scope",
        "dataset_evidence", "universe", "process_date_range", "pages", "coverage_basis", "evidence_scope",
        "coverage_review_evidence", "reviewer_id", "review_notes", "auto_trading_enabled", "authority"},
        "continuity intake request")
    for field, expected in (("schema_version", CONTINUITY_INTAKE_REQUEST_VERSION), ("domain", "TRADING"),
                            ("mode", "SHADOW_RESEARCH"), ("scope", "RETAINED_CORPORATE_ACTION_INTAKE_ONLY")):
        _constant(row, field, expected)
    for field in ("run_id", "reviewer_id"):
        row[field] = _identifier(row[field], field)
    row["recorded_at"] = accounting_timestamp(row["recorded_at"], "recorded_at")
    row["dataset_evidence"] = evidence_reference(row["dataset_evidence"], "dataset_evidence")
    row["universe"] = _universe(row["universe"])
    row["evidence_scope"] = _enum(row["evidence_scope"], {"SYNTHETIC_FIXTURE_ONLY", "RETAINED_HISTORY_RESEARCH"}, "evidence_scope")
    dates = _object(row["process_date_range"], {"start", "end"}, "process_date_range")
    for field in dates:
        dates[field] = historical_date(dates[field], field)
    if dates["start"] > dates["end"]:
        raise ContractValidationError("process date range must be chronological")
    row["process_date_range"] = dates
    pages = []
    for item in _list(row["pages"], "pages"):
        page = _object(item, {"response_evidence", "capture_receipt_evidence"}, "corporate action page")
        pages.append({field: evidence_reference(ref, field) for field, ref in page.items()})
    refs = [ref for page in pages for ref in page.values()]
    if not 1 <= len(pages) <= 16 or len({ref["path"] for ref in refs}) != len(refs):
        raise ContractValidationError("one through sixteen distinct retained page pairs required")
    row["pages"] = pages
    row["coverage_basis"] = _enum(row["coverage_basis"], {"EX_DATE_COVERAGE_UNVERIFIED", "REVIEWED_EX_DATE_COVERAGE"}, "coverage_basis")
    if row["coverage_review_evidence"] is not None:
        row["coverage_review_evidence"] = evidence_reference(row["coverage_review_evidence"], "coverage_review_evidence")
    if (row["coverage_basis"] == "REVIEWED_EX_DATE_COVERAGE") != (row["coverage_review_evidence"] is not None):
        raise ContractValidationError("reviewed coverage requires an explicit independent coverage review")
    refs += [row["dataset_evidence"]] + ([] if row["coverage_review_evidence"] is None else [row["coverage_review_evidence"]])
    if len({ref["path"] for ref in refs}) != len(refs):
        raise ContractValidationError("dataset, pages and coverage review require distinct paths")
    row["review_notes"] = _string(row["review_notes"], "review_notes", 10000)
    return _safe(row)


def _coverage_review(value):
    row = _object(value, {"schema_version", "review_id", "recorded_at", "dataset_evidence", "universe",
        "coverage_start_session_id", "coverage_end_session_id", "coverage_policy", "status",
        "reviewer_id", "review_notes", "source_evidence", "auto_trading_enabled", "authority"}, "ex-date coverage review")
    _constant(row, "schema_version", CONTINUITY_COVERAGE_REVIEW_VERSION)
    _constant(row, "coverage_policy", "ALL_ACTION_TYPES_EFFECTIVE_DATE_COVERAGE_INDEPENDENTLY_REVIEWED")
    for field in ("review_id", "reviewer_id", "coverage_start_session_id", "coverage_end_session_id"):
        row[field] = _identifier(row[field], field)
    row["recorded_at"] = accounting_timestamp(row["recorded_at"], "recorded_at")
    row["dataset_evidence"] = evidence_reference(row["dataset_evidence"], "dataset_evidence")
    row["universe"] = _universe(row["universe"])
    row["status"] = _enum(row["status"], {"SUPPORTED", "UNRESOLVED"}, "coverage review status")
    row["review_notes"] = _string(row["review_notes"], "review_notes", 10000)
    row["source_evidence"] = _refs(row["source_evidence"], "coverage source evidence")
    if any(ref["path"] == row["dataset_evidence"]["path"] for ref in row["source_evidence"]):
        raise ContractValidationError("coverage evidence must be independent of the dataset itself")
    return _safe(row)


def _export(value):
    row = _object(value, {"schema_version", "intake_id", "recorded_at", "status", "evidence_scope", "request_evidence",
        "dataset_evidence", "source_evidence", "price_continuity_source_evidence", "price_continuity_review_evidence",
        "pagination_complete", "coverage_review_supported", "native_actions", "derived_event_count", "limitations",
        "auto_trading_enabled", "authority"}, "continuity intake export")
    _constant(row, "schema_version", CONTINUITY_INTAKE_EXPORT_VERSION)
    row["intake_id"] = _identifier(row["intake_id"], "intake_id")
    row["recorded_at"] = accounting_timestamp(row["recorded_at"], "recorded_at")
    row["status"] = _enum(row["status"], {"AVAILABLE", "UNAVAILABLE", "INCOMPLETE"}, "status")
    row["evidence_scope"] = _enum(row["evidence_scope"], {"SYNTHETIC_FIXTURE_ONLY", "RETAINED_HISTORY_RESEARCH"}, "evidence_scope")
    for field in ("request_evidence", "dataset_evidence", "price_continuity_source_evidence", "price_continuity_review_evidence"):
        row[field] = evidence_reference(row[field], field)
    row["source_evidence"] = _refs(row["source_evidence"], "source_evidence")
    if row["request_evidence"] not in row["source_evidence"] or row["dataset_evidence"] not in row["source_evidence"]:
        raise ContractValidationError("continuity export must retain its exact request and dataset references")
    derived_paths = {row[field]["path"] for field in ("price_continuity_source_evidence", "price_continuity_review_evidence")}
    if len(derived_paths) != 2 or derived_paths & {ref["path"] for ref in row["source_evidence"]}:
        raise ContractValidationError("derived continuity evidence requires distinct reserved output paths")
    for field in ("pagination_complete", "coverage_review_supported"):
        row[field] = _boolean(row[field], field)
    if (row["status"] == "AVAILABLE") != row["pagination_complete"]:
        raise ContractValidationError("available status requires completed pagination; unavailable or incomplete status cannot claim it")
    actions = []
    for item in _list(row["native_actions"], "native_actions"):
        action = _object(item, {"native_id", "native_type", "process_date", "effective_date", "effective_date_basis",
            "affected_symbols", "dataset_disposition", "mapped_session_id"}, "native action audit")
        for field in ("native_id", "native_type"):
            action[field] = _identifier(action[field], field)
        action["process_date"] = historical_date(action["process_date"], "process_date")
        if action["effective_date"] is not None:
            action["effective_date"] = historical_date(action["effective_date"], "effective_date")
        action["effective_date_basis"] = _enum(action["effective_date_basis"], {"EX_DATE", "EFFECTIVE_DATE", "UNKNOWN"}, "effective_date_basis")
        action["affected_symbols"] = [research_symbol(symbol) for symbol in _list(action["affected_symbols"], "affected_symbols")]
        if action["affected_symbols"] != sorted(set(action["affected_symbols"])) or not 1 <= len(action["affected_symbols"]) <= 8:
            raise ContractValidationError("native affected symbols must be bounded, sorted and unique")
        action["dataset_disposition"] = _enum(action["dataset_disposition"], {"IN_DATASET", "BEFORE_DATASET", "AFTER_DATASET", "UNKNOWN_EFFECTIVE_DATE"}, "dataset_disposition")
        if action["mapped_session_id"] is not None:
            action["mapped_session_id"] = _identifier(action["mapped_session_id"], "mapped_session_id")
        unknown = action["effective_date_basis"] == "UNKNOWN"
        if unknown != (action["effective_date"] is None) or unknown != (action["dataset_disposition"] == "UNKNOWN_EFFECTIVE_DATE"):
            raise ContractValidationError("unknown native effective dates must remain explicitly unresolved")
        outside = action["dataset_disposition"] in {"BEFORE_DATASET", "AFTER_DATASET"}
        if outside != (action["mapped_session_id"] is None):
            raise ContractValidationError("outside-dataset actions must be retained without an invented session identity")
        actions.append(action)
    if len(actions) > 10000 or [a["native_id"] for a in actions] != sorted({a["native_id"] for a in actions}):
        raise ContractValidationError("native audit identities must be bounded, sorted and unique")
    row["native_actions"] = actions
    row["derived_event_count"] = _integer(row["derived_event_count"], "derived_event_count", 0, 10000)
    if row["status"] == "UNAVAILABLE" and row["derived_event_count"] != 0:
        raise ContractValidationError("unavailable capture cannot produce inferred continuity events")
    if row["limitations"] != list(CONTINUITY_LIMITATIONS):
        raise ContractValidationError("continuity limitations must remain explicit")
    return _safe(row)


class ContinuityIntakeRequest(_ReconciliationDocument):
    __slots__ = ()
    _validator = staticmethod(_request)


class ContinuityCoverageReview(_ReconciliationDocument):
    __slots__ = ()
    _validator = staticmethod(_coverage_review)


class ContinuityIntakeExport(_ReconciliationDocument):
    __slots__ = ()
    _validator = staticmethod(_export)
