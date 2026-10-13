"""Strict passive intake of existing daily USD price-level forecasts.

Review labels and producer/model identities are retained declarations. They are
not authenticated identities, calibrated probabilities, investment authority,
or order instructions. Missing provenance remains null and blocks admission.
"""
from __future__ import annotations

from datetime import date

from .decision_journal import _enum, _identifier, _object, _string
from .investment_review import _fixed_boolean, _list, disabled_authority
from .mission_request import ContractValidationError, parse_rfc3339
from .trading_accounting import accounting_decimal, accounting_timestamp
from .trading_reconciliation import _ReconciliationDocument, evidence_reference, symbol_text

FORECAST_INTAKE_SCHEMA_VERSION = "blackpod.forecast_intake.v1"
FORECAST_PROVENANCE_SCHEMA_VERSION = "blackpod.forecast_provenance.v1"
FORECAST_RESULT_SCHEMA_VERSION = "blackpod.forecast_intake_result.v1"
FORECAST_INTERFACE_VERSION = "DAILY_USD_PRICE_V1"
FORECAST_INTAKE_SCOPE = "SHADOW_FORECAST_INTAKE_ONLY"
FORECAST_LIMITATIONS = (
    "REVIEW_AND_PRODUCER_IDENTITY_NOT_AUTHENTICATED",
    "SOURCE_BOUND_METADATA_NOT_MODEL_RETRAINING_VERIFICATION",
    "DECLARED_CALENDAR_NOT_AUTHENTICATED_EXCHANGE_SCHEDULE",
    "CONSERVATIVE_24_HOUR_ADMISSION_CAN_DEFER_WEEKEND_FORECASTS",
    "QUANTILE_LABELS_NOT_CALIBRATED_PROBABILITIES",
    "PRICE_LEVELS_NOT_EXPECTED_RETURNS",
    "DAILY_SHORT_HORIZON_NOT_INVESTMENT_THESIS",
    "NO_EXECUTION_AUTHORITY",
)
FORECAST_FORMATS = frozenset({"GALACTICA_PHASE2_CSV", "GALACTICA_PHASE3_CSV", "GOVERNED_PRICE_FORECAST_JSON"})
ROW_METADATA_FIELDS = frozenset({"source_row_number", "symbol", "issued_at", "feature_cutoff", "training_cutoff",
    "horizon_count", "horizon_unit", "target_at", "target_session_evidence", "units", "value_semantics", "reference_price", "reference_at"})
MODEL_FIELDS = frozenset({"model_id", "model_version", "model_kind", "producer_evidence", "model_artifact_evidence",
    "config_evidence", "feature_evidence", "training_evidence", "calibration_evidence"})
RESULT_ROW_FIELDS = frozenset({"row_id", "source_id", "source_row_number", "source_evidence", "symbol", "source_date",
    "source_time_precision", "raw_source_row", "units", "value_semantics", "q10", "q50", "q90", "issued_at", "feature_cutoff",
    "training_cutoff", "horizon_count", "horizon_unit", "target_at", "target_session_evidence", "model_id", "model_version", "reference_price", "reference_at",
    "gate", "reason_codes", "realized_outcome", "evaluation"})


def _constant(result, field, expected):
    if result[field] != expected:
        raise ContractValidationError(field + " must be " + repr(expected))


def _integer(value, name, low, high):
    if type(value) is not int or not low <= value <= high:
        raise ContractValidationError(name + " must be a bounded integer")
    return value


def _nullable_time(value, name):
    return None if value is None else accounting_timestamp(value, name)


def _nullable_text(value, name, *, identifier=False):
    return None if value is None else (_identifier(value, name) if identifier else _string(value, name))


def _source_date(value, name="source_date"):
    """Retain a date as a date; never synthesize midnight or session close."""
    value = _string(value, name, 64)
    if len(value) == 10:
        try:
            if date.fromisoformat(value).isoformat() != value:
                raise ValueError()
        except ValueError as exc:
            raise ContractValidationError(name + " must be ISO date or precise RFC3339") from exc
        return value
    return accounting_timestamp(value, name)


def _intake(value):
    result = _object(value, {"schema_version", "intake_id", "recorded_at", "shadow_as_of", "domain", "mode", "scope",
        "policy", "sources", "authority"}, "forecast intake")
    _constant(result, "schema_version", FORECAST_INTAKE_SCHEMA_VERSION)
    _constant(result, "mode", "SHADOW")
    _constant(result, "scope", FORECAST_INTAKE_SCOPE)
    result["intake_id"] = _identifier(result["intake_id"], "intake_id")
    result["domain"] = _enum(result["domain"], {"TRADING", "INVESTMENT"}, "domain")
    for field in ("recorded_at", "shadow_as_of"):
        result[field] = accounting_timestamp(result[field], field)
    if parse_rfc3339(result["shadow_as_of"], "shadow_as_of") > parse_rfc3339(result["recorded_at"], "recorded_at"):
        raise ContractValidationError("shadow_as_of cannot be after recorded_at")
    policy = _object(result["policy"], {"interface_version", "max_forecast_age_seconds", "max_feature_age_seconds",
        "max_training_age_seconds", "allowed_horizon_sessions"}, "policy")
    _constant(policy, "interface_version", FORECAST_INTERFACE_VERSION)
    for field, expected in (("max_forecast_age_seconds", 86400), ("max_feature_age_seconds", 86400),
                            ("max_training_age_seconds", 86400), ("allowed_horizon_sessions", [1, 2, 3, 4, 5])):
        if policy[field] != expected or (field != "allowed_horizon_sessions" and type(policy[field]) is not int):
            raise ContractValidationError("policy." + field + " must retain the fixed shadow admission policy")
    if any(type(item) is not int for item in policy["allowed_horizon_sessions"]):
        raise ContractValidationError("allowed horizons must be integers")
    result["policy"] = policy
    sources, identities, paths, hashes = [], set(), set(), set()
    for value in _list(result["sources"], "sources"):
        source = _object(value, {"source_id", "evidence", "format", "provenance_evidence"}, "forecast source")
        source["source_id"] = _identifier(source["source_id"], "source_id")
        source["format"] = _enum(source["format"], FORECAST_FORMATS, "format")
        source["evidence"] = evidence_reference(source["evidence"])
        if source["provenance_evidence"] is not None:
            source["provenance_evidence"] = evidence_reference(source["provenance_evidence"])
        if source["source_id"] in identities or source["evidence"]["sha256"] in hashes:
            raise ContractValidationError("forecast sources require distinct identities and raw evidence hashes")
        identities.add(source["source_id"]); hashes.add(source["evidence"]["sha256"])
        for reference in (source["evidence"], source["provenance_evidence"]):
            if reference is not None:
                if reference["path"] == "forecast-intake/input.v1.json":
                    raise ContractValidationError("forecast evidence path collides with reserved intake input")
                if reference["path"] in paths:
                    raise ContractValidationError("forecast source evidence paths must be unique")
                paths.add(reference["path"])
        sources.append(source)
    if len(sources) > 128:
        raise ContractValidationError("forecast source count exceeds the supported limit")
    result["sources"] = sources
    result["authority"] = disabled_authority(result["authority"])
    return result


class ForecastIntake(_ReconciliationDocument):
    __slots__ = ()
    _validator = staticmethod(_intake)


ForecastIntakeInput = ForecastIntake


def validate_forecast_provenance(value):
    result = _object(value, {"schema_version", "source_sha256", "status", "reviewed_by", "reviewed_at", "model", "rows"}, "forecast provenance")
    _constant(result, "schema_version", FORECAST_PROVENANCE_SCHEMA_VERSION)
    from .decision_journal import _hash
    result["source_sha256"] = _hash(result["source_sha256"], "source_sha256")
    result["status"] = _enum(result["status"], {"DECLARED_UNVERIFIED", "REVIEWED_SOURCE_BOUND"}, "provenance.status")
    result["reviewed_by"] = _nullable_text(result["reviewed_by"], "reviewed_by", identifier=True)
    result["reviewed_at"] = _nullable_time(result["reviewed_at"], "reviewed_at")
    model = _object(result["model"], MODEL_FIELDS, "model")
    for field in ("model_id", "model_version"):
        model[field] = _nullable_text(model[field], field, identifier=True)
    if model["model_kind"] is not None:
        model["model_kind"] = _enum(model["model_kind"], {"QUANTILE_LINEAR", "GBM_QUANTILE", "EXTERNAL_QUANTILE"}, "model_kind")
    for field in MODEL_FIELDS - {"model_id", "model_version", "model_kind"}:
        if model[field] is not None:
            model[field] = evidence_reference(model[field], field)
    result["model"] = model
    rows, numbers = [], set()
    for value in _list(result["rows"], "provenance.rows"):
        row = _object(value, ROW_METADATA_FIELDS, "forecast row metadata")
        row["source_row_number"] = _integer(row["source_row_number"], "source_row_number", 1, 20000)
        if row["source_row_number"] in numbers:
            raise ContractValidationError("forecast row metadata numbers must be unique")
        numbers.add(row["source_row_number"])
        row["symbol"] = symbol_text(row["symbol"])
        for field in ("issued_at", "feature_cutoff", "training_cutoff", "target_at", "reference_at"):
            row[field] = _nullable_time(row[field], field)
        if row["target_session_evidence"] is not None:
            row["target_session_evidence"] = evidence_reference(row["target_session_evidence"], "target_session_evidence")
        if row["horizon_count"] is not None:
            row["horizon_count"] = _integer(row["horizon_count"], "horizon_count", 1, 3650)
        for field, allowed in (("horizon_unit", {"TRADING_SESSION"}), ("units", {"PRICE_USD"}), ("value_semantics", {"PREDICTED_CLOSE_LEVEL"})):
            if row[field] is not None:
                row[field] = _enum(row[field], allowed, field)
        if row["reference_price"] is not None:
            row["reference_price"] = accounting_decimal(row["reference_price"], "reference_price", positive=True)
        if (row["reference_price"] is None) != (row["reference_at"] is None):
            raise ContractValidationError("reference price and timestamp must be supplied together")
        rows.append(row)
    if len(rows) > 20000:
        raise ContractValidationError("forecast row metadata exceeds the supported limit")
    result["rows"] = rows
    return result


def validate_forecast_result(value, intake):
    result = _object(value, {"schema_version", "intake_id", "domain", "shadow_as_of", "status", "rows", "source_summaries",
        "admitted_count", "deferred_count", "reason_codes", "limitations", "auto_trading_enabled", "authority"}, "forecast result")
    for field, expected in (("schema_version", FORECAST_RESULT_SCHEMA_VERSION), ("intake_id", intake.intake_id),
                            ("domain", intake.domain), ("shadow_as_of", intake.shadow_as_of), ("status", FORECAST_INTAKE_SCOPE)):
        _constant(result, field, expected)
    rows, ids, row_keys = [], set(), set()
    sources_by_id = {source["source_id"]: source for source in intake.sources}
    domain, allowed_horizons = intake.domain, intake.policy["allowed_horizon_sessions"]
    for value in _list(result["rows"], "rows"):
        row = _object(value, RESULT_ROW_FIELDS, "forecast result row")
        row["row_id"] = _identifier(row["row_id"], "row_id")
        if row["row_id"] in ids:
            raise ContractValidationError("forecast result row identities must be unique")
        ids.add(row["row_id"])
        row["source_id"] = _identifier(row["source_id"], "source_id")
        row["source_row_number"] = _integer(row["source_row_number"], "source_row_number", 1, 20000)
        row["source_evidence"] = evidence_reference(row["source_evidence"])
        if row["source_id"] not in sources_by_id or row["source_evidence"] != sources_by_id[row["source_id"]]["evidence"]:
            raise ContractValidationError("forecast result rows must bind declared source evidence")
        key = (row["source_id"], row["source_row_number"])
        if key in row_keys:
            raise ContractValidationError("forecast result source row numbers must be unique")
        row_keys.add(key)
        if row["target_session_evidence"] is not None:
            row["target_session_evidence"] = evidence_reference(row["target_session_evidence"], "target_session_evidence")
        row["symbol"] = symbol_text(row["symbol"])
        row["source_date"] = _string(row["source_date"], "source_date", 64)
        row["source_time_precision"] = _enum(row["source_time_precision"], {"DATE_ONLY", "RFC3339", "UNVERIFIED"}, "source_time_precision")
        if not isinstance(row["raw_source_row"], dict) or len(row["raw_source_row"]) > 24:
            raise ContractValidationError("raw_source_row must be a bounded object")
        for key, item in row["raw_source_row"].items():
            _string(key, "raw source key", 64)
            if key == "horizon_count" and type(item) is int and 1 <= item <= 3650:
                continue
            if item is not None and (not isinstance(item, str) or len(item) > 2048):
                raise ContractValidationError("raw source values must retain bounded string/null or explicit integer horizon values")
        for field in ("q10", "q50", "q90", "reference_price"):
            if row[field] is not None:
                row[field] = accounting_decimal(row[field], field)
        for field in ("issued_at", "feature_cutoff", "training_cutoff", "target_at", "reference_at"):
            row[field] = _nullable_time(row[field], field)
        for field in ("model_id", "model_version"):
            row[field] = _nullable_text(row[field], field, identifier=True)
        for field, allowed in (("units", {"PRICE_USD"}), ("value_semantics", {"PREDICTED_CLOSE_LEVEL"}), ("horizon_unit", {"TRADING_SESSION"})):
            if row[field] is not None:
                row[field] = _enum(row[field], allowed, field)
        if row["horizon_count"] is not None:
            row["horizon_count"] = _integer(row["horizon_count"], "horizon_count", 1, 3650)
        row["gate"] = _enum(row["gate"], {"CURRENT_SHADOW_ELIGIBLE", "DEFER"}, "gate")
        row["reason_codes"] = _codes(row["reason_codes"], "row.reason_codes")
        if row["gate"] == "CURRENT_SHADOW_ELIGIBLE":
            required = ("units", "value_semantics", "q10", "q50", "q90", "issued_at", "feature_cutoff", "training_cutoff",
                        "horizon_count", "horizon_unit", "target_at", "target_session_evidence", "model_id", "model_version")
            if row["reason_codes"] or any(row[field] is None for field in required) or domain != "TRADING":
                raise ContractValidationError("admitted forecast rows require complete compatible trading evidence without deferral reasons")
            from decimal import Decimal
            quantiles = [Decimal(row[field]) for field in ("q10", "q50", "q90")]
            if min(quantiles) <= 0 or quantiles != sorted(quantiles) or row["horizon_count"] not in allowed_horizons:
                raise ContractValidationError("admitted rows require positive ordered levels and supported horizon")
        elif not row["reason_codes"]:
            raise ContractValidationError("deferred forecast rows must explain the deferral")
        _constant(row, "realized_outcome", None); _constant(row, "evaluation", None)
        rows.append(row)
    if len(rows) > 20000:
        raise ContractValidationError("forecast result exceeds the supported row limit")
    result["rows"] = rows
    summaries, sources = [], set()
    for value in _list(result["source_summaries"], "source_summaries"):
        summary = _object(value, {"source_id", "evidence", "format", "provenance_status", "row_count", "admitted_count", "deferred_count"}, "source summary")
        summary["source_id"] = _identifier(summary["source_id"], "source_id")
        if summary["source_id"] in sources:
            raise ContractValidationError("source summaries require unique identities")
        sources.add(summary["source_id"])
        summary["evidence"] = evidence_reference(summary["evidence"])
        summary["format"] = _enum(summary["format"], FORECAST_FORMATS, "format")
        summary["provenance_status"] = _enum(summary["provenance_status"], {"MISSING", "DECLARED_UNVERIFIED", "REVIEWED_SOURCE_BOUND"}, "provenance_status")
        for field in ("row_count", "admitted_count", "deferred_count"):
            summary[field] = _integer(summary[field], field, 0, 20000)
        if summary["row_count"] != summary["admitted_count"] + summary["deferred_count"]:
            raise ContractValidationError("source row counts must sum")
        source_rows = [row for row in rows if row["source_id"] == summary["source_id"]]
        if (summary["source_id"] not in sources_by_id or summary["evidence"] != sources_by_id[summary["source_id"]]["evidence"]
            or summary["format"] != sources_by_id[summary["source_id"]]["format"]
            or summary["row_count"] != len(source_rows)
            or summary["admitted_count"] != sum(row["gate"] == "CURRENT_SHADOW_ELIGIBLE" for row in source_rows)):
            raise ContractValidationError("source summaries must match projected row evidence and counts")
        summaries.append(summary)
    if sources != {source["source_id"] for source in intake.sources}:
        raise ContractValidationError("source summaries must cover all intake sources")
    result["source_summaries"] = summaries
    for field, expected in (("admitted_count", sum(row["gate"] == "CURRENT_SHADOW_ELIGIBLE" for row in rows)),
                            ("deferred_count", sum(row["gate"] == "DEFER" for row in rows))):
        if type(result[field]) is not int or result[field] != expected:
            raise ContractValidationError(field + " must match projected rows")
    result["reason_codes"] = _codes(result["reason_codes"], "reason_codes")
    if result["limitations"] != list(FORECAST_LIMITATIONS):
        raise ContractValidationError("forecast limitations must retain the versioned policy")
    _fixed_boolean(result, "auto_trading_enabled", False)
    result["authority"] = disabled_authority(result["authority"])
    return result


def _codes(value, name):
    result = [_identifier(item, name) for item in _list(value, name)]
    if len(set(result)) != len(result) or len(result) > 128:
        raise ContractValidationError(name + " must contain unique bounded reason codes")
    return result
