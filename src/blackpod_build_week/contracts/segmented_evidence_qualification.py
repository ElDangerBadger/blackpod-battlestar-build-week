"""Closed additive segmented qualification records with no operational authority."""
from .decision_journal import _object, _identifier, _enum, _evidence, _string, _boolean, _journal_id, _hash
from .investment_review import disabled_authority, _event_id, _fixed_boolean
from .mission_request import ContractValidationError, parse_rfc3339, _validate_json_value
from .trading_accounting import accounting_timestamp
from .trading_reconciliation import _ReconciliationDocument
from .trading_research import _integer, _decimal, research_symbol
from decimal import Decimal, Context, localcontext

BINDING_VERSION = "blackpod.segmented_evidence_qualification_binding.v1"
REQUEST_VERSION = "blackpod.segmented_evidence_qualification_request.v1"
RESULT_VERSION = "blackpod.segmented_evidence_qualification.v1"
METHOD_VERSION = "blackpod.segmented_train_evidence_qualification.v1"
JOURNAL_VERSION = "blackpod.decision_journal_event.v20"
BINDING_TYPE = "SEGMENTED_TRAIN_EVIDENCE_BINDING_RECORDED"
ASSESSMENT_TYPE = "SEGMENTED_TRAIN_EVIDENCE_QUALIFICATION_RECORDED"
CALIBRATION_SOURCE = "VERIFIED_SEGMENTED_TRAIN_EXPORT_ONLY"
SCOPE = "SEGMENTED_TRAIN_EVIDENCE_QUALIFICATION_ONLY"
LINK_FIELDS = {"qualification_policy_event_id", "capture_plan_event_id", "base_plan_event_id", "hypothesis_event_id", "intake_event_id"}


def _constant(row, field, expected):
    if row[field] != expected or type(row[field]) is not type(expected):
        raise ContractValidationError(field + " must equal " + repr(expected))


def _safe(row):
    _fixed_boolean(row, "auto_trading_enabled", False)
    row["authority"] = disabled_authority(row["authority"])
    return row


def _binding(value):
    row = _object(value, {"schema_version", "binding_id", "recorded_at", "domain", "mode", "scope", "qualification_policy_event_id", "capture_plan_event_id", "calibration_source", "supersedes_binding_event_id", "auto_trading_enabled", "authority"}, "segmented binding")
    for field, expected in {"schema_version": BINDING_VERSION, "domain": "TRADING", "mode": "SHADOW_RESEARCH", "scope": SCOPE, "calibration_source": CALIBRATION_SOURCE}.items():
        _constant(row, field, expected)
    row["binding_id"] = _identifier(row["binding_id"], "binding_id")
    row["recorded_at"] = accounting_timestamp(row["recorded_at"], "recorded_at")
    for field in ("qualification_policy_event_id", "capture_plan_event_id", "supersedes_binding_event_id"):
        if row[field] is not None: row[field] = _event_id(row[field], field)
        elif field != "supersedes_binding_event_id": raise ContractValidationError(field + " is required")
    return _safe(row)


def _request(value):
    row = _object(value, {"schema_version", "qualification_id", "binding_event_id", "aggregate_export_event_id", "recorded_at", "data_cutoff_at", "supersedes_event_id", "auto_trading_enabled", "authority"}, "segmented qualification request")
    _constant(row, "schema_version", REQUEST_VERSION)
    row["qualification_id"] = _identifier(row["qualification_id"], "qualification_id")
    for field in ("binding_event_id", "aggregate_export_event_id", "supersedes_event_id"):
        if row[field] is not None: row[field] = _event_id(row[field], field)
        elif field != "supersedes_event_id": raise ContractValidationError(field + " is required")
    for field in ("recorded_at", "data_cutoff_at"):
        row[field] = accounting_timestamp(row[field], field)
    if parse_rfc3339(row["data_cutoff_at"], "cutoff") > parse_rfc3339(row["recorded_at"], "record clock"):
        raise ContractValidationError("segmented qualification cutoff cannot follow record clock")
    return _safe(row)


def _texts(value, label, maximum=128):
    if not isinstance(value, list) or len(value) > maximum:
        raise ContractValidationError(label + " requires a bounded distinct list")
    items = [_string(item, label, 10000) for item in value]
    if len(items) != len(set(items)): raise ContractValidationError(label + " contains duplicates")
    return items


def _ids(value, label):
    if not isinstance(value, list) or len(value) > 10000:
        raise ContractValidationError(label + " requires a bounded identity list")
    items = [_event_id(item, label) for item in value]
    if len(items) != len(set(items)): raise ContractValidationError(label + " contains duplicates")
    return items


def _model(value, *, bounded):
    row = _object(value, {"spread_bps", "slippage_bps", "fee_bps", "fee_per_fill"}, "segmented cost model")
    for field in row:
        row[field] = _decimal(row[field], field, maximum=Decimal("1000") if bounded and field != "fee_per_fill" else None)
    return row


CALIBRATION_FIELDS = {"schema_version", "method_version", "calibration_source", "eligible", "status", "reason_codes", "evidence_scope", "folds", "aggregate_export_event_id", "source_segment_event_ids", "assumption_review_evidence", "sampling_policy", "coverage_requirement", "historical_point_in_time_verified", "source_authentication_verified", "cost_applicability_verified", "opening_execution_capacity_verified", "holdout_scored", "strategy_tuning_performed", "auto_trading_enabled", "authority", "limitations"}
FOLD_FIELDS = {"fold_id", "training_range", "train_cutoff_at", "eligible", "status", "reason_codes", "capture_complete", "coverage_complete", "source_segment_ids", "source_segment_event_ids", "training_measurements", "missing_symbol_sessions", "cost_model", "cost_stress_assessment", "capacity_proxy", "cost_applicability_verified", "opening_execution_capacity_verified"}


def _calibration(value):
    row = _object(value, CALIBRATION_FIELDS, "segmented training calibration")
    for field, expected in {"schema_version": "blackpod.segmented_training_calibration.v1", "method_version": "blackpod.segmented_train_quote_calibration.v1", "calibration_source": CALIBRATION_SOURCE, "sampling_policy": "ALL_VERIFIED_SEGMENTED_TRAIN_EXTREMA_NO_CLIPPING_OR_DOWNSAMPLING", "coverage_requirement": "EVERY_ORIGINAL_TRAIN_SYMBOL_SESSION_MUST_HAVE_ADMITTED_NATIVE_QUOTES"}.items():
        _constant(row, field, expected)
    row["evidence_scope"] = _enum(row["evidence_scope"], {"RETAINED_HISTORY_RESEARCH", "SYNTHETIC_FIXTURE_ONLY"}, "evidence_scope")
    row["aggregate_export_event_id"] = _event_id(row["aggregate_export_event_id"], "aggregate_export_event_id")
    row["source_segment_event_ids"] = _ids(row["source_segment_event_ids"], "source_segment_event_ids")
    if row["assumption_review_evidence"] is not None: row["assumption_review_evidence"] = _evidence([row["assumption_review_evidence"]])[0]
    row["eligible"] = _boolean(row["eligible"], "calibration eligible")
    row["reason_codes"] = _texts(row["reason_codes"], "calibration reason_codes")
    _constant(row, "status", "READY_FOR_SHADOW_QUALIFICATION" if row["eligible"] else "DEFER_TRAINING_EVIDENCE")
    if bool(row["reason_codes"]) == row["eligible"]: raise ContractValidationError("calibration reasons and eligibility differ")
    for field in ("historical_point_in_time_verified", "source_authentication_verified", "cost_applicability_verified", "opening_execution_capacity_verified", "holdout_scored", "strategy_tuning_performed"):
        _fixed_boolean(row, field, False)
    row["limitations"] = _texts(row["limitations"], "calibration limitations")
    if not isinstance(row["folds"], list) or not 1 <= len(row["folds"]) <= 32: raise ContractValidationError("segmented folds require a bounded nonempty list")
    folds, identities, events = [], set(), set()
    for value in row["folds"]:
        fold = _object(value, FOLD_FIELDS, "segmented calibration fold")
        fold["fold_id"] = _identifier(fold["fold_id"], "fold_id")
        if fold["fold_id"] in identities: raise ContractValidationError("duplicate calibration fold")
        identities.add(fold["fold_id"])
        interval = _object(fold["training_range"], {"start_index", "end_index"}, "training_range")
        for field in interval: interval[field] = _integer(interval[field], field, 0, 9999)
        if interval["start_index"] > interval["end_index"]: raise ContractValidationError("training range is reversed")
        fold["training_range"] = interval
        fold["train_cutoff_at"] = accounting_timestamp(fold["train_cutoff_at"], "train_cutoff_at")
        for field in ("eligible", "capture_complete", "coverage_complete"): fold[field] = _boolean(fold[field], field)
        if fold["coverage_complete"] and not fold["capture_complete"]: raise ContractValidationError("coverage needs complete capture")
        _constant(fold, "status", "READY_FOR_SHADOW_QUALIFICATION" if fold["eligible"] else "DEFER_TRAINING_EVIDENCE")
        fold["reason_codes"] = _texts(fold["reason_codes"], "fold reasons")
        if bool(fold["reason_codes"]) == fold["eligible"]: raise ContractValidationError("fold reasons and eligibility differ")
        fold["source_segment_ids"] = [_identifier(item, "segment_id") for item in _texts(fold["source_segment_ids"], "segment_ids", 10000)]
        fold["source_segment_event_ids"] = _ids(fold["source_segment_event_ids"], "segment event_ids")
        if len(fold["source_segment_ids"]) != len(fold["source_segment_event_ids"]): raise ContractValidationError("source segment identity lists differ in length")
        events.update(fold["source_segment_event_ids"])
        if not isinstance(fold["missing_symbol_sessions"], list) or len(fold["missing_symbol_sessions"]) > 80000: raise ContractValidationError("missing pairs exceed bound")
        missing = []
        for value in fold["missing_symbol_sessions"]:
            pair = _object(value, {"fold_id", "session_index", "session_id", "segment_id", "symbol"}, "missing TRAIN pair")
            for field in ("fold_id", "session_id", "segment_id"): pair[field] = _identifier(pair[field], field)
            pair["session_index"] = _integer(pair["session_index"], "session_index", interval["start_index"], interval["end_index"])
            pair["symbol"] = research_symbol(pair["symbol"])
            if pair["fold_id"] != fold["fold_id"]: raise ContractValidationError("missing pair belongs to another fold")
            missing.append(pair)
        fold["missing_symbol_sessions"] = missing
        if bool(missing) == fold["coverage_complete"]: raise ContractValidationError("missing pairs and coverage disagree")
        if fold["training_measurements"] is not None:
            if not isinstance(fold["training_measurements"], list) or not 1 <= len(fold["training_measurements"]) <= 8: raise ContractValidationError("measurements require the bounded universe")
            measurements = []
            for value in fold["training_measurements"]:
                item = _object(value, {"symbol", "max_spread_bps", "min_reported_side_size_native_units", "raw_quote_count", "eligible_quote_count", "covered_training_sessions"}, "training extrema")
                item["symbol"] = research_symbol(item["symbol"])
                item["max_spread_bps"] = _decimal(item["max_spread_bps"], "max_spread_bps")
                item["min_reported_side_size_native_units"] = _decimal(item["min_reported_side_size_native_units"], "native quote size", positive=True)
                if Decimal(item["min_reported_side_size_native_units"]) != Decimal(item["min_reported_side_size_native_units"]).to_integral_value(): raise ContractValidationError("reported native quote sizes must be whole")
                for field in ("raw_quote_count", "eligible_quote_count", "covered_training_sessions"): item[field] = _integer(item[field], field, 1, 2000000000)
                if item["eligible_quote_count"] > item["raw_quote_count"] or item["covered_training_sessions"] != interval["end_index"] - interval["start_index"] + 1: raise ContractValidationError("TRAIN extrema counts are inconsistent")
                measurements.append(item)
            fold["training_measurements"] = measurements
        if (fold["training_measurements"] is not None) != fold["coverage_complete"]: raise ContractValidationError("partial coverage cannot invent TRAIN extrema")
        if fold["cost_model"] is not None: fold["cost_model"] = _model(fold["cost_model"], bounded=True)
        if fold["eligible"] != (fold["cost_model"] is not None): raise ContractValidationError("unqualified folds cannot supply a usable cost model")
        if not isinstance(fold["cost_stress_assessment"], list) or len(fold["cost_stress_assessment"]) not in {0, 3}: raise ContractValidationError("cost stresses require all declared levels or none")
        stresses = []
        for position, value in enumerate(fold["cost_stress_assessment"]):
            stress = _object(value, {"multiplier", "declared_cost_model", "within_existing_component_bounds", "exceeded_components"}, "cost stress")
            _constant(stress, "multiplier", ("1", "2", "4")[position])
            stress["declared_cost_model"] = _model(stress["declared_cost_model"], bounded=False)
            stress["within_existing_component_bounds"] = _boolean(stress["within_existing_component_bounds"], "within bounds")
            expected = sorted(field for field in ("spread_bps", "slippage_bps", "fee_bps") if Decimal(stress["declared_cost_model"][field]) > 1000)
            if stress["exceeded_components"] != expected or stress["within_existing_component_bounds"] != (not expected): raise ContractValidationError("cost stress bounds are inconsistent")
            stresses.append(stress)
        fold["cost_stress_assessment"] = stresses
        if stresses:
            if fold["training_measurements"] is None: raise ContractValidationError("cost stresses cannot invent missing TRAIN evidence")
            source_model = stresses[0]["declared_cost_model"]
            if Decimal(source_model["spread_bps"]) != max(Decimal(item["max_spread_bps"]) for item in fold["training_measurements"]): raise ContractValidationError("cost stresses cannot clip measured spread extrema")
            if fold["cost_model"] is not None and any(Decimal(fold["cost_model"][field]) != Decimal(source_model[field]) for field in source_model): raise ContractValidationError("usable cost model must agree with base stress")
            with localcontext(Context(prec=256)):
                for stress in stresses:
                    if any(Decimal(stress["declared_cost_model"][field]) != Decimal(source_model[field]) * Decimal(stress["multiplier"]) for field in source_model): raise ContractValidationError("cost stress arithmetic differs from frozen multipliers")
        elif fold["cost_model"] is not None: raise ContractValidationError("usable cost models require all declared stresses")
        if not isinstance(fold["capacity_proxy"], list) or not 1 <= len(fold["capacity_proxy"]) <= 8: raise ContractValidationError("capacity proxies require the bounded universe")
        capacity = []
        for value in fold["capacity_proxy"]:
            item = _object(value, {"symbol", "minimum_training_daily_volume", "maximum_training_daily_volume", "reviewed_daily_volume_participation_fraction", "daily_quantity_research_proxy", "semantics"}, "capacity proxy")
            item["symbol"] = research_symbol(item["symbol"])
            for field in ("minimum_training_daily_volume", "maximum_training_daily_volume"): item[field] = _decimal(item[field], field)
            if Decimal(item["minimum_training_daily_volume"]) > Decimal(item["maximum_training_daily_volume"]): raise ContractValidationError("training volume bounds are reversed")
            if item["reviewed_daily_volume_participation_fraction"] is not None: item["reviewed_daily_volume_participation_fraction"] = _decimal(item["reviewed_daily_volume_participation_fraction"], "participation fraction", positive=True, maximum=Decimal("1"))
            if item["daily_quantity_research_proxy"] is not None: item["daily_quantity_research_proxy"] = _decimal(item["daily_quantity_research_proxy"], "daily proxy")
            if (item["daily_quantity_research_proxy"] is None) != (item["reviewed_daily_volume_participation_fraction"] is None): raise ContractValidationError("capacity cannot invent a missing fraction")
            if item["daily_quantity_research_proxy"] is not None:
                with localcontext(Context(prec=256)):
                    if Decimal(item["daily_quantity_research_proxy"]) != Decimal(item["minimum_training_daily_volume"]) * Decimal(item["reviewed_daily_volume_participation_fraction"]): raise ContractValidationError("daily proxy arithmetic differs from reviewed fraction")
            _constant(item, "semantics", "RAW_DAILY_VOLUME_RESEARCH_PROXY_NOT_OPENING_FILL_CAPACITY")
            capacity.append(item)
        fold["capacity_proxy"] = capacity
        for field in ("cost_applicability_verified", "opening_execution_capacity_verified"): _fixed_boolean(fold, field, False)
        folds.append(fold)
    if set(row["source_segment_event_ids"]) != events: raise ContractValidationError("calibration source event closure differs")
    if row["eligible"] != all(fold["eligible"] for fold in folds) or row["reason_codes"] != sorted({reason for fold in folds for reason in fold["reason_codes"]}): raise ContractValidationError("calibration disposition differs from folds")
    row["folds"] = folds
    return _safe(row)


RESULT_FIELDS = {"schema_version", "method_version", "qualification_id", "binding_id", "policy_id", "status", "eligible_for_study_design", "reason_codes", "continuity", "training_calibration", "risk", "uncertainty_protocol", "uncertainty_status", "uncertainty_computed", "economic_hypothesis_supported", "existing_gate_override", "execution_status", "realized_trade_pnl", "limitations", "provenance", "auto_trading_enabled", "authority"}


def validate_result(value):
    row = _object(value, RESULT_FIELDS, "segmented qualification result")
    _constant(row, "schema_version", RESULT_VERSION); _constant(row, "method_version", METHOD_VERSION)
    for field in ("qualification_id", "binding_id", "policy_id"):
        row[field] = _identifier(row[field], field)
    row["status"] = _enum(row["status"], {"READY_FOR_QUALIFIED_STUDY_DESIGN", "DEFER_EVIDENCE_QUALIFICATION"}, "status")
    row["eligible_for_study_design"] = _boolean(row["eligible_for_study_design"], "eligible_for_study_design")
    if row["eligible_for_study_design"] != (row["status"] == "READY_FOR_QUALIFIED_STUDY_DESIGN"):
        raise ContractValidationError("segmented eligibility must agree with status")
    row["reason_codes"] = _texts(row["reason_codes"], "reason_codes")
    if bool(row["reason_codes"]) == row["eligible_for_study_design"]:
        raise ContractValidationError("segmented reasons must agree with eligibility")
    row["limitations"] = _texts(row["limitations"], "limitations")
    if not row["limitations"]: raise ContractValidationError("segmented qualification limitations are required")
    for field in ("uncertainty_computed", "economic_hypothesis_supported", "existing_gate_override"):
        _fixed_boolean(row, field, False)
    _constant(row, "execution_status", "NOT_EXECUTED"); _constant(row, "realized_trade_pnl", None)
    row["uncertainty_status"] = _enum(row["uncertainty_status"], {"MISSING", "INFEASIBLE", "FROZEN_NOT_EVALUATED"}, "uncertainty_status")
    for field in ("continuity", "training_calibration", "risk", "provenance"):
        if not isinstance(row[field], dict): raise ContractValidationError(field + " requires an object")
        _validate_json_value(row[field], field)
    row["training_calibration"] = _calibration(row["training_calibration"])
    if row["uncertainty_protocol"] is not None:
        from .trading_evidence_qualification import uncertainty_protocol
        row["uncertainty_protocol"] = uncertainty_protocol(row["uncertainty_protocol"])
    return _safe(row)


class SegmentedEvidenceBinding(_ReconciliationDocument):
    __slots__ = ()
    _validator = staticmethod(_binding)


class SegmentedEvidenceQualificationRequest(_ReconciliationDocument):
    __slots__ = ()
    _validator = staticmethod(_request)


def validate_journal_event(value):
    from ..hashing import sha256_bytes
    row = dict(value)
    _constant(row, "schema_version", JOURNAL_VERSION); _constant(row, "domain", "TRADING")
    for field in ("event_id", "decision_id"): row[field] = _journal_id(row[field], field)
    row["recorded_at"] = accounting_timestamp(row["recorded_at"], "recorded_at")
    kind = _enum(row["event_type"], {BINDING_TYPE, ASSESSMENT_TYPE}, "event_type")
    fields = {"binding", "links", "implementation_evidence"} if kind == BINDING_TYPE else {"request", "result", "binding_event_id", "aggregate_export_event_id", "prior_qualification_event_ids", "implementation_evidence"}
    payload = _object(row["payload"], fields, "segmented qualification payload")
    document = SegmentedEvidenceBinding.from_mapping(payload["binding"]) if kind == BINDING_TYPE else SegmentedEvidenceQualificationRequest.from_mapping(payload["request"])
    key = "binding_id" if kind == BINDING_TYPE else "qualification_id"
    source_kind = "SEGMENTED_TRAIN_EVIDENCE_BINDING" if kind == BINDING_TYPE else "SEGMENTED_TRAIN_EVIDENCE_QUALIFICATION"
    source = _object(row["source"], {"kind", key, "source_sha256"}, "segmented source")
    _constant(source, "kind", source_kind)
    source[key] = _identifier(source[key], key); source["source_sha256"] = _hash(source["source_sha256"], "source_sha256")
    if source[key] != getattr(document, key) or source["source_sha256"] != sha256_bytes(document.to_bytes()) or row["recorded_at"] != document.recorded_at:
        raise ContractValidationError("segmented journal source identity/hash/clock mismatch")
    payload["implementation_evidence"] = _evidence(payload["implementation_evidence"])
    row["evidence"] = _evidence(row["evidence"])
    if kind == BINDING_TYPE:
        payload["binding"] = document.to_dict()
        links = _object(payload["links"], LINK_FIELDS, "segmented binding links")
        for field in links: links[field] = _event_id(links[field], field)
        if links["qualification_policy_event_id"] != document.qualification_policy_event_id or links["capture_plan_event_id"] != document.capture_plan_event_id:
            raise ContractValidationError("segmented binding links differ from declaration")
        payload["links"] = links
    else:
        payload["request"] = document.to_dict(); payload["result"] = validate_result(payload["result"])
        if payload["result"]["qualification_id"] != document.qualification_id or payload["binding_event_id"] != document.binding_event_id or payload["aggregate_export_event_id"] != document.aggregate_export_event_id:
            raise ContractValidationError("segmented assessment identity or input links differ")
        prior = payload["prior_qualification_event_ids"]
        if not isinstance(prior, list) or len(prior) > 1024:
            raise ContractValidationError("prior segmented assessments require bounded sorted unique identities")
        for identity in prior: _event_id(identity, "prior assessment")
        if prior != sorted(set(prior)): raise ContractValidationError("prior segmented assessments require sorted unique identities")
    row["source"], row["payload"] = source, payload
    return row
