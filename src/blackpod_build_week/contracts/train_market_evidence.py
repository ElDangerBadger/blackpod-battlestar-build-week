"""Frozen TRAIN GET plans and retained segmented market-data export requests."""
from .decision_journal import _object, _identifier, _enum, _evidence, _string
from .investment_review import disabled_authority, _event_id, _fixed_boolean
from .mission_request import ContractValidationError, parse_rfc3339
from .trading_accounting import accounting_timestamp
from .trading_reconciliation import _ReconciliationDocument, evidence_reference
from .trading_research import _integer
from ..trading_cost_intake import _query

PLAN_VERSION = "blackpod.train_market_capture_plan.v1"
SNAPSHOT_VERSION = "blackpod.train_market_capture_snapshot.v1"
SEGMENT_REQUEST_VERSION = "blackpod.train_market_segment_export_request.v1"
EXPORT_REQUEST_VERSION = "blackpod.train_market_export_request.v1"
JOURNAL_VERSION = "blackpod.decision_journal_event.v19"
PLAN_TYPE = "TRAIN_MARKET_CAPTURE_PLAN_RECORDED"
SEGMENT_TYPE = "TRAIN_MARKET_CAPTURE_SEGMENT_RECORDED"
EXPORT_TYPE = "TRAIN_MARKET_CAPTURE_EXPORT_RECORDED"
EVIDENCE_SCOPES = frozenset({"RETAINED_HISTORY_RESEARCH", "SYNTHETIC_FIXTURE_ONLY"})
DEFAULT_LIMITS = {"max_pages_per_segment": 128, "max_rows_per_segment": 200000,
    "max_response_bytes": 8 * 1024 * 1024, "max_segment_bytes": 64 * 1024 * 1024,
    "max_capture_bytes": 512 * 1024 * 1024, "max_total_requests": 4096,
    "max_requests_per_invocation": 32, "min_request_interval_ms": 1000, "timeout_seconds": 20}


def _constant(row, field, expected):
    if row[field] != expected or type(row[field]) is not type(expected):
        raise ContractValidationError(field + " must equal " + repr(expected))


def _safe(row):
    _fixed_boolean(row, "auto_trading_enabled", False)
    row["authority"] = disabled_authority(row["authority"])
    return row


def _limits(value):
    row = _object(value, set(DEFAULT_LIMITS), "capture limits")
    for field, upper in DEFAULT_LIMITS.items():
        lower = 1
        if field == "min_request_interval_ms": lower, upper = 1000, 60000
        elif field == "timeout_seconds": upper = 60
        row[field] = _integer(row[field], field, lower, upper)
    if row["max_response_bytes"] > row["max_segment_bytes"] or row["max_segment_bytes"] > row["max_capture_bytes"]:
        raise ContractValidationError("response, segment and corpus byte limits must be ordered")
    if row["max_requests_per_invocation"] > row["max_total_requests"]:
        raise ContractValidationError("invocation budget cannot exceed lifetime budget")
    return row


def _plan(value):
    row = _object(value, {"schema_version", "capture_id", "created_at", "domain", "mode", "scope", "base_plan_event_id", "base_plan_evidence", "dataset_evidence", "evidence_scope", "fold_ids", "segments", "limits", "auto_trading_enabled", "authority"}, "TRAIN capture plan")
    for field, expected in {"schema_version": PLAN_VERSION, "domain": "TRADING", "mode": "MARKET_DATA_GET_ONLY", "scope": "TRAIN_OPENING_MINUTE_QUOTES_ONLY"}.items(): _constant(row, field, expected)
    row["capture_id"] = _identifier(row["capture_id"], "capture_id")
    row["created_at"] = accounting_timestamp(row["created_at"], "created_at")
    row["base_plan_event_id"] = _event_id(row["base_plan_event_id"], "base_plan_event_id")
    for field in ("base_plan_evidence", "dataset_evidence"): row[field] = evidence_reference(row[field], field)
    row["evidence_scope"] = _enum(row["evidence_scope"], EVIDENCE_SCOPES, "evidence_scope")
    if not isinstance(row["fold_ids"], list) or not 1 <= len(row["fold_ids"]) <= 32:
        raise ContractValidationError("capture folds must be a bounded nonempty list")
    row["fold_ids"] = [_identifier(value, "fold_id") for value in row["fold_ids"]]
    if len(set(row["fold_ids"])) != len(row["fold_ids"]): raise ContractValidationError("capture folds must be distinct")
    row["limits"] = _limits(row["limits"])
    if not isinstance(row["segments"], list) or not 1 <= len(row["segments"]) <= 10000:
        raise ContractValidationError("capture segments must be a bounded nonempty list")
    segments, ids, positions = [], set(), set()
    for segment in row["segments"]:
        segment = _object(segment, {"segment_id", "fold_id", "session_index", "session_id", "query"}, "TRAIN capture segment")
        for field in ("segment_id", "fold_id", "session_id"): segment[field] = _identifier(segment[field], field)
        segment["session_index"] = _integer(segment["session_index"], "session_index", 0, 9999)
        if segment["fold_id"] not in row["fold_ids"] or segment["segment_id"] in ids or (segment["fold_id"], segment["session_index"]) in positions:
            raise ContractValidationError("segments must have distinct identities and selected fold positions")
        ids.add(segment["segment_id"]); positions.add((segment["fold_id"], segment["session_index"]))
        query = _object(segment["query"], {"symbols", "start", "end", "limit", "feed", "currency", "sort", "asof"}, "frozen quote query")
        if not isinstance(query["symbols"], str): raise ContractValidationError("symbols must be an explicit string")
        universe = query["symbols"].split(",")
        if universe != sorted(set(universe)) or not all(universe): raise ContractValidationError("query symbols must be sorted and distinct")
        _query(query, universe)
        if query["limit"] != 10000: raise ContractValidationError("capture retains the declared full native page limit without sampling")
        segment["query"] = query; segments.append(segment)
    row["segments"] = segments
    return _safe(row)


def _failure(value):
    if value is None: return None
    row = _object(value, {"code", "http_status"}, "capture failure")
    row["code"] = _string(row["code"], "failure code", 128)
    if row["http_status"] is not None: row["http_status"] = _integer(row["http_status"], "failure HTTP status", 100, 599)
    return row


def _pages(value):
    if not isinstance(value, list) or len(value) > 128: raise ContractValidationError("segment pages exceed their bounded list")
    pages = []
    for page in value:
        page = _object(page, {"body_evidence", "receipt_evidence"}, "segment page")
        pages.append({field: evidence_reference(ref, field) for field, ref in page.items()})
    if len({ref["path"] for page in pages for ref in page.values()}) != len(pages) * 2:
        raise ContractValidationError("segment page source paths must be distinct")
    return pages


def _snapshot(value):
    row = _object(value, {"schema_version", "capture_plan_evidence", "capture_id", "exported_at", "segments", "attempt_count", "retained_bytes", "checkpoint_evidence", "auto_trading_enabled", "authority"}, "capture snapshot")
    _constant(row, "schema_version", SNAPSHOT_VERSION)
    row["capture_plan_evidence"] = evidence_reference(row["capture_plan_evidence"], "capture_plan_evidence")
    row["capture_id"] = _identifier(row["capture_id"], "capture_id")
    row["exported_at"] = accounting_timestamp(row["exported_at"], "exported_at")
    row["attempt_count"] = _integer(row["attempt_count"], "attempt_count", 0, 4096)
    row["retained_bytes"] = _integer(row["retained_bytes"], "retained_bytes", 0, DEFAULT_LIMITS["max_capture_bytes"])
    row["checkpoint_evidence"] = _evidence(row["checkpoint_evidence"])
    if len(row["checkpoint_evidence"]) > 20000: raise ContractValidationError("checkpoint evidence exceeds supported count")
    if not isinstance(row["segments"], list) or len(row["segments"]) > 10000: raise ContractValidationError("snapshot segments exceed their bound")
    segments, seen = [], set()
    for segment in row["segments"]:
        segment = _object(segment, {"segment_id", "pages", "status", "failure"}, "snapshot segment")
        segment["segment_id"] = _identifier(segment["segment_id"], "segment_id")
        if segment["segment_id"] in seen: raise ContractValidationError("duplicate snapshot segment identity")
        seen.add(segment["segment_id"])
        segment["pages"] = _pages(segment["pages"])
        segment["status"] = _enum(segment["status"], {"NOT_STARTED", "COMPLETE", "INCOMPLETE", "UNAVAILABLE"}, "snapshot status")
        segment["failure"] = _failure(segment["failure"])
        segments.append(segment)
    row["segments"] = segments
    return _safe(row)


def _segment_request(value):
    row = _object(value, {"schema_version", "export_id", "capture_plan_event_id", "segment_id", "pages", "failure", "exported_at", "auto_trading_enabled", "authority"}, "segment export request")
    _constant(row, "schema_version", SEGMENT_REQUEST_VERSION)
    for field in ("export_id", "segment_id"): row[field] = _identifier(row[field], field)
    row["capture_plan_event_id"] = _event_id(row["capture_plan_event_id"], "capture_plan_event_id")
    row["exported_at"] = accounting_timestamp(row["exported_at"], "exported_at")
    row["pages"] = _pages(row["pages"]); row["failure"] = _failure(row["failure"])
    return _safe(row)


def _export_request(value):
    row = _object(value, {"schema_version", "export_id", "capture_plan_event_id", "segment_event_ids", "exported_at", "continuity_event_id", "coverage_review_evidence", "capture_snapshot_evidence", "capture_checkpoint_evidence", "auto_trading_enabled", "authority"}, "TRAIN aggregate request")
    _constant(row, "schema_version", EXPORT_REQUEST_VERSION)
    row["export_id"] = _identifier(row["export_id"], "export_id")
    row["capture_plan_event_id"] = _event_id(row["capture_plan_event_id"], "capture_plan_event_id")
    row["exported_at"] = accounting_timestamp(row["exported_at"], "exported_at")
    if not isinstance(row["segment_event_ids"], list) or len(row["segment_event_ids"]) > 10000: raise ContractValidationError("aggregate segment identities exceed bound")
    row["segment_event_ids"] = [_event_id(value, "segment_event_id") for value in row["segment_event_ids"]]
    if row["segment_event_ids"] != sorted(set(row["segment_event_ids"])): raise ContractValidationError("aggregate segment identities must be sorted and unique")
    if row["continuity_event_id"] is not None: row["continuity_event_id"] = _event_id(row["continuity_event_id"], "continuity_event_id")
    if row["coverage_review_evidence"] is not None: row["coverage_review_evidence"] = evidence_reference(row["coverage_review_evidence"], "coverage_review_evidence")
    if row["capture_snapshot_evidence"] is not None: row["capture_snapshot_evidence"] = evidence_reference(row["capture_snapshot_evidence"], "capture_snapshot_evidence")
    row["capture_checkpoint_evidence"] = _evidence(row["capture_checkpoint_evidence"])
    if len(row["capture_checkpoint_evidence"]) > 20000: raise ContractValidationError("capture audit evidence exceeds its reference bound")
    if row["capture_snapshot_evidence"] is None and row["capture_checkpoint_evidence"]: raise ContractValidationError("checkpoint audit evidence requires its exact capture snapshot")
    return _safe(row)


class TrainMarketCapturePlan(_ReconciliationDocument):
    __slots__ = ()
    _validator = staticmethod(_plan)

class TrainMarketCaptureSnapshot(_ReconciliationDocument):
    __slots__ = ()
    _validator = staticmethod(_snapshot)

class TrainMarketSegmentRequest(_ReconciliationDocument):
    __slots__ = ()
    _validator = staticmethod(_segment_request)

class TrainMarketExportRequest(_ReconciliationDocument):
    __slots__ = ()
    _validator = staticmethod(_export_request)


def validate_journal_event(value):
    from .decision_journal import _journal_id, _hash
    from ..hashing import sha256_bytes
    row = dict(value); _constant(row, "schema_version", JOURNAL_VERSION); _constant(row, "domain", "TRADING")
    for field in ("event_id", "decision_id"): row[field] = _journal_id(row[field], field)
    row["recorded_at"] = accounting_timestamp(row["recorded_at"], "recorded_at")
    event_type = _enum(row["event_type"], {PLAN_TYPE, SEGMENT_TYPE, EXPORT_TYPE}, "event_type")
    fields = {"plan", "links", "implementation_evidence"} if event_type == PLAN_TYPE else {"request", "result", "links", "implementation_evidence"}
    payload = _object(row["payload"], fields, "TRAIN evidence payload")
    document = TrainMarketCapturePlan.from_mapping(payload["plan"]) if event_type == PLAN_TYPE else (TrainMarketSegmentRequest if event_type == SEGMENT_TYPE else TrainMarketExportRequest).from_mapping(payload["request"])
    key = "capture_id" if event_type == PLAN_TYPE else "export_id"
    kind = {PLAN_TYPE: "TRAIN_MARKET_CAPTURE_PLAN", SEGMENT_TYPE: "TRAIN_MARKET_CAPTURE_SEGMENT", EXPORT_TYPE: "TRAIN_MARKET_CAPTURE_EXPORT"}[event_type]
    source = _object(row["source"], {"kind", key, "source_sha256"} | ({"segment_id"} if event_type == SEGMENT_TYPE else set()), "TRAIN evidence source")
    _constant(source, "kind", kind); source["source_sha256"] = _hash(source["source_sha256"], "source_sha256")
    if source[key] != getattr(document, key) or source["source_sha256"] != sha256_bytes(document.to_bytes()) or row["recorded_at"] != getattr(document, "created_at" if event_type == PLAN_TYPE else "exported_at"):
        raise ContractValidationError("TRAIN evidence source identity/hash/clock differs from document")
    if event_type == SEGMENT_TYPE and source["segment_id"] != document.segment_id: raise ContractValidationError("segment source identity differs from request")
    payload["implementation_evidence"] = _evidence(payload["implementation_evidence"])
    payload["links"] = _object(payload["links"], {"base_plan_event_id", "hypothesis_event_id", "intake_event_id"}, "TRAIN source links")
    for field in payload["links"]: payload["links"][field] = _event_id(payload["links"][field], field)
    if event_type != PLAN_TYPE:
        segment_fields = {"schema_version", "method_version", "capture_id", "segment_id", "fold_id", "session_index", "session_id", "query", "exported_at", "status", "capture_complete", "coverage_complete", "pages", "page_count", "raw_quote_count", "eligible_quote_count", "retained_source_bytes", "symbols", "missing_symbols", "reason_codes", "failure", "source_authentication_verified", "historical_point_in_time_verified", "auto_trading_enabled", "authority", "limitations"}
        aggregate_fields = {"schema_version", "method_version", "capture_id", "base_plan_evidence", "dataset_evidence", "status", "capture_complete", "coverage_complete", "counts", "segments", "missing_symbol_sessions", "folds", "reason_codes", "consumer_v18", "existing_gate_override", "economic_hypothesis_supported", "uncertainty_computed", "source_authentication_verified", "historical_point_in_time_verified", "slippage_estimated", "fees_estimated", "opening_execution_capacity_verified", "final_holdout", "auto_trading_enabled", "authority", "limitations", "retained_source_bytes", "export_id", "exported_at", "segment_event_ids", "continuity_coverage", "cost_assumptions_supplied", "execution_status", "realized_trade_pnl", "capture_audit"}
        result = _object(payload["result"], segment_fields if event_type == SEGMENT_TYPE else aggregate_fields, "TRAIN result")
        _fixed_boolean(result, "auto_trading_enabled", False); disabled_authority(result["authority"])
        for field in ("source_authentication_verified", "historical_point_in_time_verified"): _fixed_boolean(result, field, False)
        from .decision_journal import _boolean
        for field in ("capture_complete", "coverage_complete"): result[field] = _boolean(result[field], field)
        _enum(result["status"], {"CAPTURE_COMPLETE", "CAPTURE_INCOMPLETE"}, "capture status")
        if result["capture_complete"] != (result["status"] == "CAPTURE_COMPLETE") or (result["coverage_complete"] and not result["capture_complete"]):
            raise ContractValidationError("capture status and completion/coverage flags disagree")
        if event_type == EXPORT_TYPE:
            for field in ("economic_hypothesis_supported", "uncertainty_computed", "existing_gate_override", "slippage_estimated", "fees_estimated", "opening_execution_capacity_verified", "cost_assumptions_supplied"):
                _fixed_boolean(result, field, False)
            _constant(result, "consumer_v18", "INCOMPATIBLE_SEGMENTED_INPUT")
            _constant(result, "execution_status", "NOT_EXECUTED"); _constant(result, "realized_trade_pnl", None)
        payload["result"] = result
    row["payload"] = payload; row["source"] = source; row["evidence"] = _evidence(row["evidence"])
    return row
