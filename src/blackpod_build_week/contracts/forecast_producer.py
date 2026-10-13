"""Versioned contracts for explicit, isolated SHADOW forecast production.

These contracts authorize no trading, capital, policy, or broker operation.
Recorded runtime identities are provenance declarations, not authenticated
producer identities. A source-bound validation is never a human approval.
"""
from __future__ import annotations

import re

from .decision_journal import _enum, _identifier, _object, _string
from .investment_review import _fixed_boolean, _list, disabled_authority
from .mission_request import ContractValidationError, parse_rfc3339
from .trading_accounting import accounting_timestamp
from .trading_reconciliation import _ReconciliationDocument, evidence_reference, symbol_text

FORECAST_PRODUCER_REQUEST_VERSION = "blackpod.forecast_producer_request.v1"
FORECAST_PRODUCER_EXPORT_VERSION = "blackpod.forecast_producer_export.v1"
FORECAST_PRODUCER_SCOPE = "SHADOW_FORECAST_PRODUCTION_ONLY"
FORECAST_PRODUCER_LIMITATIONS = (
    "SOURCE_BOUND_MACHINE_VALIDATION_NOT_HUMAN_APPROVAL",
    "PRODUCER_AND_RUNTIME_IDENTITY_NOT_AUTHENTICATED",
    "RAW_QUANTILE_IDENTITIES_PRESERVED_CROSSING_NOT_REPAIRED",
    "UNVALIDATED_UNCALIBRATED_FORECASTS_NOT_EXPECTED_RETURNS",
    "DAILY_SHORT_HORIZON_NOT_INVESTMENT_THESIS",
    "DATA_ONLY_MODEL_ARTIFACT_NOT_PICKLE_OR_ESTIMATOR_RESTORE",
    "NO_EXECUTION_AUTHORITY",
)
_STOCK_SYMBOL = re.compile(r"^[A-Z0-9][A-Z0-9.-]{0,31}$")


def producer_symbol(value):
    value = symbol_text(value)
    if not _STOCK_SYMBOL.fullmatch(value) or ".." in value:
        raise ContractValidationError("forecast producer requires an explicit path-safe stock/ETF symbol")
    return value


def _constant(result, field, expected):
    if result[field] != expected:
        raise ContractValidationError(field + " must be " + repr(expected))


def _refs(values, name, minimum=1, maximum=128):
    result = [evidence_reference(value, name) for value in _list(values, name)]
    if not minimum <= len(result) <= maximum or len({row["path"] for row in result}) != len(result):
        raise ContractValidationError(name + " must contain bounded, distinct evidence paths")
    return result


def _codes(value):
    result = [_identifier(item, "reason_code") for item in _list(value, "reason_codes")]
    if len(set(result)) != len(result) or len(result) > 128:
        raise ContractValidationError("reason codes must be unique and bounded")
    return result


def _request(value):
    result = _object(value, {"schema_version", "run_id", "recorded_at", "domain", "mode", "scope", "symbols",
        "horizons", "sources", "authority"}, "forecast producer request")
    for field, expected in (("schema_version", FORECAST_PRODUCER_REQUEST_VERSION), ("domain", "TRADING"),
                            ("mode", "SHADOW"), ("scope", FORECAST_PRODUCER_SCOPE)):
        _constant(result, field, expected)
    result["run_id"] = _identifier(result["run_id"], "run_id")
    result["recorded_at"] = accounting_timestamp(result["recorded_at"], "recorded_at")
    symbols = [producer_symbol(item) for item in _list(result["symbols"], "symbols")]
    if not 1 <= len(symbols) <= 8 or symbols != sorted(set(symbols)):
        raise ContractValidationError("symbols must be a sorted, nonempty, unique bounded stock/ETF universe")
    result["symbols"] = symbols
    horizons = _list(result["horizons"], "horizons")
    if (not horizons or any(type(item) is not int or item not in (1, 2, 3, 4, 5) for item in horizons)
            or horizons != sorted(set(horizons))):
        raise ContractValidationError("horizons must be sorted unique integer trading-session counts 1 through 5")
    result["horizons"] = list(horizons)
    sources = _object(result["sources"], {"market_evidence", "calendar_evidence", "calendar_receipt_evidence",
        "native_source_evidence"}, "producer sources")
    for field in ("market_evidence", "calendar_evidence", "calendar_receipt_evidence"):
        sources[field] = evidence_reference(sources[field], field)
    sources["native_source_evidence"] = _refs(sources["native_source_evidence"], "native_source_evidence", maximum=32)
    refs = [sources[field] for field in ("market_evidence", "calendar_evidence", "calendar_receipt_evidence")] + sources["native_source_evidence"]
    if len({row["path"] for row in refs}) != len(refs):
        raise ContractValidationError("producer source evidence paths must be distinct")
    result["sources"] = sources
    result["authority"] = disabled_authority(result["authority"])
    return result


class ForecastProducerRequest(_ReconciliationDocument):
    __slots__ = ()
    _validator = staticmethod(_request)


def validate_forecast_producer_export(value, request):
    """Validate retained export shape; exact source/fit replay is a separate gate."""
    if not isinstance(request, ForecastProducerRequest):
        request = ForecastProducerRequest.from_mapping(request)
    result = _object(value, {"schema_version", "run_id", "request_evidence", "started_at", "completed_at", "issued_at",
        "status", "runtime_fingerprint", "native_config_evidence", "model_kind", "symbol_results", "source_evidence",
        "limitations", "auto_trading_enabled", "authority"}, "forecast producer export")
    _constant(result, "schema_version", FORECAST_PRODUCER_EXPORT_VERSION)
    _constant(result, "run_id", request.run_id)
    _constant(result, "model_kind", "QUANTILE_LINEAR")
    result["request_evidence"] = evidence_reference(result["request_evidence"])
    for field in ("started_at", "completed_at", "issued_at"):
        result[field] = accounting_timestamp(result[field], field)
    times = {field: parse_rfc3339(result[field], field) for field in ("started_at", "completed_at", "issued_at")}
    if not parse_rfc3339(request.recorded_at, "recorded_at") <= times["started_at"] <= times["completed_at"] <= times["issued_at"]:
        raise ContractValidationError("request, actual generation, and issue clocks must be ordered")
    result["status"] = _enum(result["status"], {"PRODUCED", "DEFERRED"}, "export status")
    runtime = _object(result["runtime_fingerprint"], {"python", "pandas", "numpy", "scikit-learn", "scipy"}, "runtime fingerprint")
    result["runtime_fingerprint"] = {field: _string(item, field, 128) for field, item in runtime.items()}
    result["native_config_evidence"] = evidence_reference(result["native_config_evidence"])
    symbol_results, symbols = [], []
    for item in _list(result["symbol_results"], "symbol_results"):
        row = _object(item, {"symbol", "status", "reason_codes", "feature_cutoff", "reference_price", "reference_at",
            "feature_evidence", "horizon_results"}, "producer symbol result")
        row["symbol"] = producer_symbol(row["symbol"]); symbols.append(row["symbol"])
        row["status"] = _enum(row["status"], {"PRODUCED", "DEFERRED"}, "symbol status")
        row["reason_codes"] = _codes(row["reason_codes"])
        for field in ("feature_cutoff", "reference_at"):
            row[field] = None if row[field] is None else accounting_timestamp(row[field], field)
        from .trading_accounting import accounting_decimal
        row["reference_price"] = None if row["reference_price"] is None else accounting_decimal(row["reference_price"], "reference_price", positive=True)
        row["feature_evidence"] = None if row["feature_evidence"] is None else evidence_reference(row["feature_evidence"])
        if (row["reference_price"] is None) != (row["reference_at"] is None):
            raise ContractValidationError("reference price and time must be supplied together")
        horizons, counts = [], []
        for item in _list(row["horizon_results"], "horizon_results"):
            horizon = _object(item, {"horizon_count", "status", "reason_codes", "training_cutoff", "training_evidence",
                "model_artifact_evidence", "native_output_evidence", "forecast_evidence", "provenance_evidence",
                "target_session_evidence"}, "producer horizon result")
            if type(horizon["horizon_count"]) is not int or horizon["horizon_count"] not in request.horizons:
                raise ContractValidationError("producer horizon must bind an explicitly requested session count")
            counts.append(horizon["horizon_count"])
            horizon["status"] = _enum(horizon["status"], {"PRODUCED", "DEFERRED"}, "horizon status")
            horizon["reason_codes"] = _codes(horizon["reason_codes"])
            horizon["training_cutoff"] = None if horizon["training_cutoff"] is None else accounting_timestamp(horizon["training_cutoff"], "training_cutoff")
            for field in ("training_evidence", "model_artifact_evidence", "native_output_evidence", "forecast_evidence",
                          "provenance_evidence", "target_session_evidence"):
                horizon[field] = None if horizon[field] is None else evidence_reference(horizon[field], field)
            if horizon["status"] == "PRODUCED":
                if horizon["reason_codes"] or any(horizon[field] is None for field in horizon if field not in ("status", "reason_codes")):
                    raise ContractValidationError("produced horizons require complete evidence and no production deferral")
            elif not horizon["reason_codes"]:
                raise ContractValidationError("deferred horizons require reason codes")
            horizons.append(horizon)
        if counts != request.horizons:
            raise ContractValidationError("each symbol must account for every requested horizon in order")
        row["horizon_results"] = horizons
        produced = any(item["status"] == "PRODUCED" for item in horizons)
        if (row["status"] == "PRODUCED") != produced:
            raise ContractValidationError("symbol status must reflect at least one produced horizon")
        if produced and (row["reason_codes"] or any(row[field] is None for field in ("feature_cutoff", "reference_price", "reference_at", "feature_evidence"))):
            raise ContractValidationError("produced symbols require complete feature provenance without deferral")
        if not produced and not row["reason_codes"]:
            raise ContractValidationError("deferred symbols require reason codes")
        symbol_results.append(row)
    if symbols != request.symbols:
        raise ContractValidationError("producer results must cover every requested symbol exactly and in order")
    result["symbol_results"] = symbol_results
    if (result["status"] == "PRODUCED") != any(row["status"] == "PRODUCED" for row in symbol_results):
        raise ContractValidationError("export status must reflect produced symbol coverage")
    result["source_evidence"] = _refs(result["source_evidence"], "source_evidence", maximum=10000)
    if result["limitations"] != list(FORECAST_PRODUCER_LIMITATIONS):
        raise ContractValidationError("export must retain its versioned limitations")
    _fixed_boolean(result, "auto_trading_enabled", False)
    result["authority"] = disabled_authority(result["authority"])
    return result
