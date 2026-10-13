"""Closed, immutable quote evidence and separately reviewed cost assumptions.

Historical quotes can bound an observed spread sample. They cannot measure
slippage, commissions or fees for orders which were never executed.
"""
from decimal import Decimal

from .decision_journal import _enum, _identifier, _object, _string
from .investment_review import _fixed_boolean, _list, disabled_authority
from .mission_request import ContractValidationError
from .trading_accounting import accounting_timestamp
from .trading_reconciliation import _ReconciliationDocument, evidence_reference
from .trading_research import _decimal, _universe

COST_INTAKE_REQUEST_VERSION = "blackpod.trading_cost_intake_request.v1"
COST_ASSUMPTION_REVIEW_VERSION = "blackpod.trading_cost_assumption_review.v1"
COST_INTAKE_EXPORT_VERSION = "blackpod.trading_cost_intake_export.v1"
COST_INTAKE_METHOD_VERSION = "blackpod.alpaca_quote_cost_projection.v1"
_RESERVED_PATHS = frozenset("cost-intake/" + kind + ".v1.json" for kind in ("request", "export", "source", "review"))
COST_INTAKE_LIMITATIONS = (
    "LOCAL_CAPTURE_DECLARATION_NOT_PROVIDER_AUTHENTICATION",
    "RETAINED_HISTORICAL_QUOTES_NOT_POINT_IN_TIME_VERIFIED",
    "IEX_OPENING_MINUTE_SAMPLE_NOT_CONSOLIDATED_MARKET_OR_AUCTION_EXECUTION",
    "MAX_OBSERVED_SPREAD_IS_SAMPLE_BOUND_NOT_FUTURE_EXECUTION_GUARANTEE",
    "SLIPPAGE_AND_FEES_ARE_EXPLICIT_LOCAL_ASSUMPTIONS_NOT_MEASURED_EXECUTION_COSTS",
    "QUOTE_SIZE_IS_NOT_EXECUTION_CAPACITY_OR_FILL_AVAILABILITY",
    "NO_EXECUTION_OR_CAPITAL_AUTHORITY",
)


def _constant(row, field, value):
    if type(row[field]) is not type(value) or row[field] != value:
        raise ContractValidationError(field + " must be " + repr(value))


def _refs(value, name):
    refs = [evidence_reference(item, name) for item in _list(value, name)]
    if not 1 <= len(refs) <= 128 or len({ref["path"] for ref in refs}) != len(refs):
        raise ContractValidationError(name + " requires one through 128 distinct retained paths")
    return refs


def _request(value):
    row = _object(value, {
        "schema_version", "run_id", "recorded_at", "domain", "mode", "scope", "evidence_scope", "dataset_evidence",
        "quote_pages", "assumption_review_evidence", "reviewer_id", "review_notes", "auto_trading_enabled", "authority",
    }, "cost intake request")
    for field, constant in (("schema_version", COST_INTAKE_REQUEST_VERSION), ("domain", "TRADING"),
                            ("mode", "SHADOW_RESEARCH"), ("scope", "COST_EVIDENCE_INTAKE_ONLY")):
        _constant(row, field, constant)
    for field in ("run_id", "reviewer_id"):
        row[field] = _identifier(row[field], field)
    row["recorded_at"] = accounting_timestamp(row["recorded_at"], "recorded_at")
    row["review_notes"] = _string(row["review_notes"], "review_notes", 10000)
    row["evidence_scope"] = _enum(row["evidence_scope"], {"SYNTHETIC_FIXTURE_ONLY", "RETAINED_HISTORY_RESEARCH"}, "evidence_scope")
    row["dataset_evidence"] = evidence_reference(row["dataset_evidence"], "dataset_evidence")
    pages, paths = [], {row["dataset_evidence"]["path"]}
    for page in _list(row["quote_pages"], "quote_pages"):
        item = _object(page, {"body_evidence", "receipt_evidence"}, "quote page")
        for field in item:
            item[field] = evidence_reference(item[field], field)
            if item[field]["path"] in _RESERVED_PATHS:
                raise ContractValidationError("native quote source cannot occupy a reserved derived cost path")
            if item[field]["path"] in paths:
                raise ContractValidationError("quote intake paths must be distinct")
            paths.add(item[field]["path"])
        if not item["body_evidence"]["path"].endswith(".raw"):
            raise ContractValidationError("native quote body must retain an opaque .raw path")
        pages.append(item)
    if not 1 <= len(pages) <= 128:
        raise ContractValidationError("quote_pages requires one through 128 retained pages")
    row["quote_pages"] = pages
    if row["assumption_review_evidence"] is not None:
        row["assumption_review_evidence"] = evidence_reference(row["assumption_review_evidence"], "assumption_review_evidence")
        if row["assumption_review_evidence"]["path"] in _RESERVED_PATHS:
            raise ContractValidationError("assumption review cannot occupy a reserved derived cost path")
        if row["assumption_review_evidence"]["path"] in paths:
            raise ContractValidationError("cost assumption evidence must have a distinct retained path")
    _fixed_boolean(row, "auto_trading_enabled", False)
    row["authority"] = disabled_authority(row["authority"])
    return row


def _assumptions(value):
    row = _object(value, {
        "schema_version", "review_id", "recorded_at", "dataset_evidence", "universe",
        "coverage_start_session_id", "coverage_end_session_id", "evidence_scope", "status", "parameters", "origin_evidence",
        "reviewer_id", "review_notes", "auto_trading_enabled", "authority",
    }, "cost assumption review")
    _constant(row, "schema_version", COST_ASSUMPTION_REVIEW_VERSION)
    for field in ("review_id", "reviewer_id", "coverage_start_session_id", "coverage_end_session_id"):
        row[field] = _identifier(row[field], field)
    row["recorded_at"] = accounting_timestamp(row["recorded_at"], "recorded_at")
    row["dataset_evidence"] = evidence_reference(row["dataset_evidence"], "dataset_evidence")
    row["universe"] = _universe(row["universe"])
    row["evidence_scope"] = _enum(row["evidence_scope"], {"SYNTHETIC_FIXTURE_ONLY", "RETAINED_HISTORY_RESEARCH"}, "evidence_scope")
    row["status"] = _enum(row["status"], {"REVIEWED_SHADOW_ASSUMPTIONS", "UNRESOLVED"}, "status")
    if row["parameters"] is None:
        if row["status"] == "REVIEWED_SHADOW_ASSUMPTIONS":
            raise ContractValidationError("reviewed assumptions require explicit parameters")
    else:
        parameters = _object(row["parameters"], {"slippage_bps", "fee_bps", "fee_per_fill"}, "parameters")
        for field in parameters:
            parameters[field] = _decimal(parameters[field], "parameters." + field,
                                         maximum=Decimal("1000") if field != "fee_per_fill" else None)
        row["parameters"] = parameters
    row["origin_evidence"] = _refs(row["origin_evidence"], "origin_evidence")
    if any(ref["path"] in _RESERVED_PATHS for ref in row["origin_evidence"]):
        raise ContractValidationError("assumption origins cannot occupy reserved derived cost paths")
    if row["dataset_evidence"]["path"] in {ref["path"] for ref in row["origin_evidence"]}:
        raise ContractValidationError("assumption origin evidence must be distinct from its dataset")
    row["review_notes"] = _string(row["review_notes"], "review_notes", 10000)
    _fixed_boolean(row, "auto_trading_enabled", False)
    row["authority"] = disabled_authority(row["authority"])
    return row


class CostIntakeRequest(_ReconciliationDocument):
    __slots__ = ()
    _validator = staticmethod(_request)


class CostAssumptionReview(_ReconciliationDocument):
    __slots__ = ()
    _validator = staticmethod(_assumptions)
