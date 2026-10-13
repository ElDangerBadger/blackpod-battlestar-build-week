"""Pure source-bound export of actual isolated quantitative producer results.

This module never trains, loads estimator pickles, calls providers, writes
files, or changes controls. It retains native sorted output separately from
the raw fitted quantile identities admitted by the existing forecast intake.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
import json
import re
from zoneinfo import ZoneInfo

from .contracts.forecast_intake import ForecastIntake, validate_forecast_provenance
from .contracts.forecast_producer import (
    FORECAST_PRODUCER_EXPORT_VERSION, FORECAST_PRODUCER_LIMITATIONS, ForecastProducerRequest,
    validate_forecast_producer_export,
)
from .contracts.mission_request import (
    ContractValidationError, _object_without_duplicate_keys, _reject_json_constant, parse_rfc3339,
    parse_strict_json_object_bytes,
)
from .contracts.trading_accounting import accounting_timestamp
from .contracts.trading_reconciliation import evidence_reference
from .desk_review_sources import validate_market_packet
from .forecast_intake import assess_forecast_intake, evidence_for_forecast_intake
from .hashing import canonical_json_bytes, sha256_bytes

_CALENDAR_URL = "https://paper-api.alpaca.markets/v2/calendar"
_TIME = re.compile(r"^([0-9]{2}):([0-9]{2})(?::([0-9]{2}))?$")
_AUX_TIME = re.compile(r"^([0-9]{2})([0-9]{2})$")
_MODEL_KEYS = ("q10", "q50", "q90")


def _blob(blobs, reference):
    reference = evidence_reference(reference)
    raw = blobs.get(reference["sha256"])
    if not isinstance(raw, bytes) or sha256_bytes(raw) != reference["sha256"] or len(raw) != reference["size_bytes"]:
        raise ContractValidationError("producer evidence hash/size is missing or inconsistent: " + reference["path"])
    return raw


def _json(blobs, reference):
    return parse_strict_json_object_bytes(_blob(blobs, reference), document_name="forecast producer evidence")


def validate_raw_calendar(raw, receipt):
    """Project only returned exchange dates/times, retaining actual UTC closes.

The Alpaca calendar endpoint documents Eastern market times. Conversion uses
the named America/New_York zone, including DST and early closes. It never
fills omitted dates, infers a close from a daily-bar midnight, or substitutes
a weekday calendar for the retained provider response.
    """
    from .contracts.decision_journal import _object
    receipt = _object(receipt, {"schema_version", "url", "query", "captured_at", "method", "status", "body_sha256", "size_bytes"}, "calendar receipt")
    if (receipt["schema_version"] != "blackpod.read_only_calendar_capture.v1" or receipt["url"] != _CALENDAR_URL
            or receipt["method"] != "GET" or type(receipt["status"]) is not int or receipt["status"] != 200):
        raise ContractValidationError("calendar receipt must bind the fixed read-only Alpaca calendar endpoint")
    if (not isinstance(raw, bytes) or len(raw) > 16 * 1024 * 1024 or type(receipt["size_bytes"]) is not int
            or receipt["size_bytes"] != len(raw) or receipt["body_sha256"] != sha256_bytes(raw)):
        raise ContractValidationError("calendar receipt differs from retained raw response hash/size")
    captured = accounting_timestamp(receipt["captured_at"], "calendar captured_at")
    query = _object(receipt["query"], {"start", "end"}, "calendar query")
    try:
        start, end = (date.fromisoformat(query[field]) for field in ("start", "end"))
        if start.isoformat() != query["start"] or end.isoformat() != query["end"] or start > end:
            raise ValueError()
        rows = json.loads(raw.decode("utf-8"), object_pairs_hook=_object_without_duplicate_keys, parse_constant=_reject_json_constant)
    except (ValueError, TypeError, UnicodeError) as exc:
        raise ContractValidationError("calendar response/query must be strict UTF-8 JSON and ISO dates") from exc
    if not isinstance(rows, list) or not 1 <= len(rows) <= 10000:
        raise ContractValidationError("calendar response must be a bounded nonempty session list")
    sessions, previous = [], None
    zone = ZoneInfo("America/New_York")
    for row in rows:
        if (not isinstance(row, dict) or not {"date", "open", "close"} <= set(row)
                or set(row) - {"date", "open", "close", "session_open", "session_close", "settlement_date"}):
            raise ContractValidationError("calendar session has unsupported fields")
        try:
            day = date.fromisoformat(row["date"])
            if day.isoformat() != row["date"] or not start <= day <= end or (previous is not None and day <= previous):
                raise ValueError()
            previous = day
            times = []
            for field in ("open", "close"):
                match = _TIME.fullmatch(row[field]) if isinstance(row[field], str) else None
                if match is None:
                    raise ValueError()
                hour, minute, second = (int(item or 0) for item in match.groups())
                local = datetime(day.year, day.month, day.day, hour, minute, second, tzinfo=zone)
                if local.astimezone(timezone.utc).astimezone(zone).replace(tzinfo=None) != local.replace(tzinfo=None):
                    raise ValueError()
                if local.replace(fold=0).utcoffset() != local.replace(fold=1).utcoffset():
                    raise ValueError()  # Source supplied no offset/fold for an ambiguous Eastern time.
                times.append(local.astimezone(timezone.utc))
            if not times[0] < times[1]:
                raise ValueError()
            for field in ("session_open", "session_close"):
                if field in row:
                    match = _TIME.fullmatch(row[field]) if isinstance(row[field], str) else None
                    if match is None and isinstance(row[field], str):
                        match = _AUX_TIME.fullmatch(row[field])
                    if match is None:
                        raise ValueError()
                    values = [int(item or 0) for item in match.groups()]
                    hour, minute, second = values + [0] if len(values) == 2 else values
                    datetime(day.year, day.month, day.day, hour, minute, second)
            if "settlement_date" in row and date.fromisoformat(row["settlement_date"]).isoformat() != row["settlement_date"]:
                raise ValueError()
        except (ValueError, TypeError) as exc:
            raise ContractValidationError("calendar dates and Eastern session times must be explicit, ordered and valid") from exc
        sessions.append({"date": day.isoformat(), "opens_at": times[0].isoformat().replace("+00:00", "Z"),
            "closes_at": times[1].isoformat().replace("+00:00", "Z")})
    return {"captured_at": captured, "sessions": sessions}


def _native_sources(request, blobs):
    result = {}
    for reference in request.sources["native_source_evidence"]:
        if not reference["path"].startswith("native_forecast_code/"):
            raise ContractValidationError("native producer sources must retain their reviewed relative source paths")
        name = reference["path"][len("native_forecast_code/"):]
        if name in result:
            raise ContractValidationError("native producer sources contain duplicate relative paths")
        result[name] = _blob(blobs, reference)
    return result


def _material(request, blobs):
    market = _json(blobs, request.sources["market_evidence"])
    validate_market_packet(market, blobs)
    calendar = validate_raw_calendar(_blob(blobs, request.sources["calendar_evidence"]), _json(blobs, request.sources["calendar_receipt_evidence"]))
    if not set(request.symbols) <= set(market["bars"]):
        raise ContractValidationError("every requested symbol requires actual retained market history")
    return market, calendar, _native_sources(request, blobs)


def build_forecast_producer_export(request, native_result, blobs, *, started_at, completed_at, issued_at):
    """Freeze actual fit results into compatible intake documents and evidence.

``started_at`` and ``completed_at`` are actual externally measured generation
clocks. ``issued_at`` is the actual post-fit issue clock, also retained by the
native result. The source-bound review identifies this machine validator;
it does not claim a human approved the forecasts or their use for trading.
    """
    if not isinstance(request, ForecastProducerRequest):
        request = ForecastProducerRequest.from_mapping(request)
    market, calendar, native_sources = _material(request, blobs)
    from .shadow_quantitative_producer import validate_shadow_quantitative_forecasts
    validate_shadow_quantitative_forecasts(native_result, market, calendar, native_sources)
    if [row["symbol"] for row in native_result["symbols"]] != request.symbols:
        raise ContractValidationError("native production universe must match the explicit request exactly and in order")
    issued_at = accounting_timestamp(issued_at, "issued_at")
    if native_result["issued_at"] != issued_at:
        raise ContractValidationError("export issue clock must equal retained native production issue clock")
    if parse_rfc3339(calendar["captured_at"], "calendar captured_at") > parse_rfc3339(started_at, "started_at"):
        raise ContractValidationError("generation cannot precede retained source-calendar capture")
    if parse_rfc3339(market["captured_at"], "market captured_at") > parse_rfc3339(started_at, "started_at"):
        raise ContractValidationError("generation cannot precede retained market capture")
    evidence, retained = {}, dict(blobs)
    def keep(path, value):
        raw = value if isinstance(value, bytes) else canonical_json_bytes(value)
        if path in evidence and evidence[path] != raw:
            raise ContractValidationError("producer export evidence path conflicts")
        evidence[path] = raw; retained[sha256_bytes(raw)] = raw
        return {"path": path, "sha256": sha256_bytes(raw), "size_bytes": len(raw)}
    prefix = "forecast-production/" + sha256_bytes(request.to_bytes())
    request_ref = keep(prefix + "/request.json", request.to_bytes())
    config_ref = keep(prefix + "/native-config.json", native_result["config"])
    native_result_ref = keep(prefix + "/native-result.json", native_result)
    # Preserve all source dependencies, including the raw source packets'
    # linked response bodies. Only recognized evidence references are read.
    refs = [request.sources[field] for field in ("market_evidence", "calendar_evidence", "calendar_receipt_evidence")] + request.sources["native_source_evidence"] + list(market["source_evidence"])
    for reference in refs:
        keep(reference["path"], _blob(blobs, reference))
    sources, symbol_results = [], []
    symbols_by_name = {row["symbol"]: row for row in native_result["symbols"]}
    for symbol in request.symbols:
        row = symbols_by_name[symbol]
        feature_ref = keep(prefix + "/" + symbol + "/features.json", {
            "schema_version": "blackpod.forecast_observation_evidence.v2", "kind": "FEATURES", "symbol": symbol,
            "observations": row["feature_observations"]})
        feature_names = row["feature_names"]
        supported_config_ref = keep(prefix + "/" + symbol + "/intake-model-config.json", {
            "schema_version": "blackpod.forecast_model_config.v1", "model_kind": "QUANTILE_LINEAR",
            "quantile_levels": ["0.10", "0.50", "0.90"], "target": "FUTURE_CLOSE", "currency": "USD",
            "feature_names": feature_names})
        future_sessions = [session for session in calendar["sessions"] if parse_rfc3339(session["closes_at"], "close") > parse_rfc3339(row["feature_cutoff"], "feature_cutoff")]
        if not future_sessions or len(future_sessions) > 128:
            raise ContractValidationError("retained future target calendar must be nonempty and bounded")
        session_ref = keep(prefix + "/" + symbol + "/target-sessions.json", {
            "schema_version": "blackpod.forecast_session_calendar.v1", "symbol": symbol,
            "anchor_at": row["feature_cutoff"], "captured_at": calendar["captured_at"],
            "sessions": [{field: session[field] for field in ("opens_at", "closes_at")} for session in future_sessions]})
        horizons_by_count = {item["horizon_count"]: item for item in row["horizons"]}
        horizon_results, forecast_rows, row_metadata, datasets = [], [], [], []
        model_id = "galactica-phase2-quantile-linear-family-" + symbol
        model_version = "source-bound-" + sha256_bytes(canonical_json_bytes(native_result["native_source_sha256"]))[:24]
        for horizon in request.horizons:
            if horizon not in horizons_by_count:
                horizon_results.append({"horizon_count": horizon, "status": "DEFERRED",
                    "reason_codes": ["INSUFFICIENT_NATIVE_TRAINING_LABELS"], "training_cutoff": None,
                    **{field: None for field in ("training_evidence", "model_artifact_evidence", "native_output_evidence",
                        "forecast_evidence", "provenance_evidence", "target_session_evidence")}})
                continue
            item = horizons_by_count[horizon]
            base = prefix + "/" + symbol + "/h" + str(horizon)
            training_ref = keep(base + "/training.json", {"schema_version": "blackpod.forecast_observation_evidence.v2",
                "kind": "TRAINING", "symbol": symbol, "observations": item["training_observations"]})
            model_ref = keep(base + "/models.json", {"schema_version": "blackpod.forecast_quantile_model_bundle.v1",
                "symbol": symbol, "horizon_count": horizon, "model_kind": "QUANTILE_LINEAR",
                "native_config_evidence": config_ref, "training_evidence": training_ref, "feature_evidence": feature_ref,
                "model_family_id": model_id,
                "model_ids": {label: model_id + "-h" + str(horizon) + "-" + label for label in _MODEL_KEYS},
                "models": item["model_artifacts"], "restore_semantics": "DATA_ONLY_NO_PICKLE_NO_REFIT"})
            native_output_ref = keep(base + "/native-output.json", {"schema_version": "blackpod.native_quantile_output.v1",
                "symbol": symbol, "horizon_count": horizon, "raw_quantiles": item["raw_quantiles"],
                "native_sorted_quantiles": item["native_sorted_quantiles"], "model_artifact_evidence": model_ref,
                "sort_semantics": "RETAINED_NATIVE_OUTPUT_NOT_GOVERNED_QUANTILE_IDENTITIES"})
            forecast_row = {"symbol": symbol, "source_date": row["feature_cutoff"],
                **{key: item["raw_quantiles"][key] for key in _MODEL_KEYS}, "timeframe": "1D",
                "horizon_count": horizon, "horizon_unit": "TRADING_SESSION", "units": "PRICE_USD",
                "value_semantics": "PREDICTED_CLOSE_LEVEL", "issued_at": issued_at, "feature_cutoff": row["feature_cutoff"],
                "training_cutoff": item["training_cutoff"], "target_at": item["target_at"],
                "reference_price": row["reference_price"], "reference_at": row["reference_at"],
                "model_id": model_id, "model_version": model_version}
            forecast_rows.append(forecast_row)
            row_metadata.append({"source_row_number": len(forecast_rows), "symbol": symbol, "issued_at": issued_at,
                "feature_cutoff": row["feature_cutoff"], "training_cutoff": item["training_cutoff"],
                "horizon_count": horizon, "horizon_unit": "TRADING_SESSION", "target_at": item["target_at"],
                "target_session_evidence": session_ref, "units": "PRICE_USD", "value_semantics": "PREDICTED_CLOSE_LEVEL",
                "reference_price": row["reference_price"], "reference_at": row["reference_at"]})
            datasets.append({"horizon_count": horizon, "observations": item["training_observations"]})
            horizon_results.append({"horizon_count": horizon, "status": "PRODUCED", "reason_codes": [],
                "training_cutoff": item["training_cutoff"], "training_evidence": training_ref, "model_artifact_evidence": model_ref,
                "native_output_evidence": native_output_ref, "forecast_evidence": None, "provenance_evidence": None,
                "target_session_evidence": session_ref})
        produced = any(item["status"] == "PRODUCED" for item in horizon_results)
        if produced:
            combined_training_ref = keep(prefix + "/" + symbol + "/multi-horizon-training.json", {
                "schema_version": "blackpod.forecast_observation_evidence.v3", "kind": "TRAINING", "symbol": symbol,
                "datasets": datasets})
            family_ref = keep(prefix + "/" + symbol + "/multi-horizon-model-family.json", {
                "schema_version": "blackpod.forecast_multi_horizon_model_family.v1", "symbol": symbol,
                "model_family_id": model_id, "model_kind": "QUANTILE_LINEAR", "native_config_evidence": config_ref,
                "feature_evidence": feature_ref, "training_evidence": combined_training_ref,
                "horizons": [{field: item[field] for field in ("horizon_count", "model_artifact_evidence", "native_output_evidence")}
                    for item in horizon_results if item["status"] == "PRODUCED"],
                "family_semantics": "DISTINCT_FITTED_MODEL_PER_HORIZON_AND_QUANTILE",
                "restore_semantics": "DATA_ONLY_NO_PICKLE_NO_REFIT"})
            forecast_ref = keep(prefix + "/" + symbol + "/forecasts.json", {
                "schema_version": "blackpod.daily_price_forecasts.v1", "rows": forecast_rows})
            provenance = {"schema_version": "blackpod.forecast_provenance.v1", "source_sha256": forecast_ref["sha256"],
                "status": "REVIEWED_SOURCE_BOUND", "reviewed_by": "machine-source-bound-producer-export-v1", "reviewed_at": issued_at,
                "model": {"model_id": model_id, "model_version": model_version, "model_kind": "QUANTILE_LINEAR",
                    "producer_evidence": native_result_ref, "model_artifact_evidence": family_ref, "config_evidence": supported_config_ref,
                    "feature_evidence": feature_ref, "training_evidence": combined_training_ref, "calibration_evidence": None},
                "rows": row_metadata}
            validate_forecast_provenance(provenance)
            provenance_ref = keep(prefix + "/" + symbol + "/provenance.json", provenance)
            sources.append({"source_id": "native-phase2-family-" + symbol, "evidence": forecast_ref,
                "format": "GOVERNED_PRICE_FORECAST_JSON", "provenance_evidence": provenance_ref})
            for item in horizon_results:
                if item["status"] == "PRODUCED":
                    item["forecast_evidence"], item["provenance_evidence"] = forecast_ref, provenance_ref
        symbol_results.append({"symbol": symbol, "status": "PRODUCED" if produced else "DEFERRED",
            "reason_codes": [] if produced else ["NO_REQUESTED_NATIVE_HORIZON_PRODUCED"],
            "feature_cutoff": row["feature_cutoff"], "reference_price": row["reference_price"], "reference_at": row["reference_at"],
            "feature_evidence": feature_ref, "horizon_results": horizon_results})
    intake = ForecastIntake.from_mapping({"schema_version": "blackpod.forecast_intake.v1",
        "intake_id": "forecast-production-" + sha256_bytes(request.to_bytes())[:32], "recorded_at": issued_at, "shadow_as_of": issued_at,
        "domain": "TRADING", "mode": "SHADOW", "scope": "SHADOW_FORECAST_INTAKE_ONLY",
        "policy": {"interface_version": "DAILY_USD_PRICE_V1", "max_forecast_age_seconds": 86400,
            "max_feature_age_seconds": 86400, "max_training_age_seconds": 86400, "allowed_horizon_sessions": [1, 2, 3, 4, 5]},
        "sources": sources, "authority": request.authority})
    evidence.update(evidence_for_forecast_intake(intake, retained))
    for raw in evidence.values():
        retained[sha256_bytes(raw)] = raw
    all_refs = [{"path": path, "sha256": sha256_bytes(raw), "size_bytes": len(raw)} for path, raw in sorted(evidence.items())]
    export = {"schema_version": FORECAST_PRODUCER_EXPORT_VERSION, "run_id": request.run_id, "request_evidence": request_ref,
        "started_at": started_at, "completed_at": completed_at, "issued_at": issued_at,
        "status": "PRODUCED" if any(row["status"] == "PRODUCED" for row in symbol_results) else "DEFERRED",
        "runtime_fingerprint": native_result["runtime_fingerprint"], "native_config_evidence": config_ref, "model_kind": "QUANTILE_LINEAR",
        "symbol_results": symbol_results, "source_evidence": all_refs, "limitations": list(FORECAST_PRODUCER_LIMITATIONS),
        "auto_trading_enabled": False, "authority": request.authority}
    export = validate_forecast_producer_export(export, request)
    return {"export": export, "intake": intake, "evidence": evidence, "blobs": retained,
        "intake_result": assess_forecast_intake(intake, retained)}


def validate_forecast_producer_export_bundle(export, blobs):
    """Replay source/model/output bindings without fitting or provider calls."""
    request = ForecastProducerRequest.from_bytes(_blob(blobs, export["request_evidence"]))
    export = validate_forecast_producer_export(export, request)
    refs = export["source_evidence"]
    by_path = {reference["path"]: reference for reference in refs}
    for reference in refs:
        _blob(blobs, reference)
    prefix = "forecast-production/" + sha256_bytes(request.to_bytes())
    if prefix + "/native-result.json" not in by_path:
        raise ContractValidationError("producer export lacks its retained native production result")
    native_result = _json(blobs, by_path[prefix + "/native-result.json"])
    regenerated = build_forecast_producer_export(request, native_result, blobs,
        started_at=export["started_at"], completed_at=export["completed_at"], issued_at=export["issued_at"])
    if canonical_json_bytes(regenerated["export"]) != canonical_json_bytes(export):
        raise ContractValidationError("forecast producer export differs from exact source/model replay")
    for path, raw in regenerated["evidence"].items():
        if path not in by_path or _blob(blobs, by_path[path]) != raw:
            raise ContractValidationError("forecast producer retained evidence differs from source/model replay")
    return regenerated
