"""Provider-free projection of retained forecast rows into governed shadow intake.

Only source bytes are parsed. No model is loaded, fitted, inferred, executed, or
repaired. Quantile labels remain uncalibrated price levels. Admission concerns
evidence and interface compatibility, never trading or allocation authority.
"""
from __future__ import annotations

import csv
import io
import re
from collections import Counter
from datetime import date
from decimal import Decimal
from types import SimpleNamespace

from .contracts.forecast_intake import (
    FORECAST_INTAKE_SCOPE, FORECAST_LIMITATIONS, FORECAST_RESULT_SCHEMA_VERSION,
    ForecastIntake, _source_date, validate_forecast_provenance, validate_forecast_result,
)
from .contracts.mission_request import ContractValidationError, parse_rfc3339, parse_strict_json_object_bytes
from .contracts.trading_accounting import accounting_decimal, accounting_timestamp
from .contracts.trading_reconciliation import evidence_reference, symbol_text
from .hashing import canonical_json_bytes, sha256_bytes

_CSV_FIELDS = {"Date", "Symbol", "Q10", "Q50", "Q90", "Pattern", "Timeframe"}
_JSON_FIELDS = {"symbol", "source_date", "q10", "q50", "q90", "timeframe", "horizon_count", "horizon_unit", "units", "value_semantics",
    "issued_at", "feature_cutoff", "training_cutoff", "target_at", "reference_price", "reference_at", "model_id", "model_version"}
_REQUIRED_MODEL_REFS = ("producer_evidence", "model_artifact_evidence", "config_evidence", "feature_evidence", "training_evidence")


def _blob(blobs, reference):
    reference = evidence_reference(reference)
    raw = blobs.get(reference["sha256"])
    if not isinstance(raw, bytes) or len(raw) != reference["size_bytes"] or sha256_bytes(raw) != reference["sha256"]:
        raise ContractValidationError("forecast evidence is missing or its hash/size differs: " + reference["path"])
    return raw


def _json(blobs, reference):
    return parse_strict_json_object_bytes(_blob(blobs, reference), document_name="forecast evidence")


def _text(raw):
    try:
        result = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ContractValidationError("forecast source must be UTF-8") from exc
    if "\x00" in result or len(raw) > 16 * 1024 * 1024:
        raise ContractValidationError("forecast source is oversized or contains NUL")
    return result


def _source_rows(source, blobs):
    raw = _blob(blobs, source["evidence"])
    if source["format"] == "GOVERNED_PRICE_FORECAST_JSON":
        packet = parse_strict_json_object_bytes(raw, document_name="governed forecast source")
        if set(packet) != {"schema_version", "rows"} or packet["schema_version"] != "blackpod.daily_price_forecasts.v1" or not isinstance(packet["rows"], list):
            raise ContractValidationError("governed price forecast source has unsupported schema")
        rows = []
        for row in packet["rows"]:
            if not isinstance(row, dict) or set(row) != _JSON_FIELDS:
                raise ContractValidationError("governed price forecast row has unsupported fields")
            for field, item in row.items():
                if field == "horizon_count":
                    if item is not None and (type(item) is not int or not 1 <= item <= 3650):
                        raise ContractValidationError("JSON horizon count must be null or bounded integer")
                elif item is not None and (not isinstance(item, str) or len(item) > 2048):
                    raise ContractValidationError("governed forecast values must be strings or null")
            rows.append(dict(row))
    else:
        reader = csv.DictReader(io.StringIO(_text(raw), newline=""), strict=True)
        expected = _CSV_FIELDS | ({"Horizon"} if source["format"] == "GALACTICA_PHASE2_CSV" else set())
        if reader.fieldnames is None or len(set(reader.fieldnames)) != len(reader.fieldnames) or set(reader.fieldnames) != expected:
            raise ContractValidationError("forecast CSV must have the exact supported columns without duplicates")
        rows = []
        try:
            for row in reader:
                if None in row or any(value is None or len(value) > 2048 for value in row.values()):
                    raise ContractValidationError("forecast CSV row has missing or excess fields")
                if any("\x00" in value for value in row.values()):
                    raise ContractValidationError("forecast CSV row contains NUL")
                rows.append(dict(row))
                if len(rows) > 20000:
                    raise ContractValidationError("forecast source exceeds the supported row count")
        except csv.Error as exc:
            raise ContractValidationError("forecast CSV is malformed") from exc
    if len(rows) > 20000:
        raise ContractValidationError("forecast source exceeds the supported row count")
    serializations = [canonical_json_bytes(row) for row in rows]
    if len(set(serializations)) != len(serializations):
        raise ContractValidationError("forecast source contains duplicate identical rows")
    return rows


def _source_projection(raw, source_format):
    if source_format == "GOVERNED_PRICE_FORECAST_JSON":
        return {"symbol": raw["symbol"], "source_date": raw["source_date"], "q10": raw["q10"], "q50": raw["q50"],
                "q90": raw["q90"], "timeframe": raw["timeframe"], "horizon": raw["horizon_count"]}
    return {"symbol": raw["Symbol"], "source_date": raw["Date"], "q10": raw["Q10"], "q50": raw["Q50"],
            "q90": raw["Q90"], "timeframe": raw["Timeframe"], "horizon": raw.get("Horizon")}


def _parsed_proof(blobs, reference, document_name, cache):
    """Parse a retained proof once, including unsupported symbol/kind cases."""
    key = ("proof_json", reference["sha256"], reference["size_bytes"])
    if key not in cache:
        raw = _blob(blobs, reference)
        try:
            cache[key] = parse_strict_json_object_bytes(raw, document_name=document_name)
        except ContractValidationError:
            cache[key] = None
    return cache[key]


def _proof_observations(blobs, reference, kind, symbol, cache, horizon_count=None):
    """Verify recorded observation times; never execute retained model artifacts.

    TRAINING rows separately identify feature observation and target-label
    availability. A feature-row date alone is insufficient proof.
    """
    packet = _parsed_proof(blobs, reference, "forecast observation proof", cache)
    if packet is None:
        return None, "UNSUPPORTED_" + kind + "_OBSERVATION_PROOF"
    if packet.get("schema_version") == "blackpod.forecast_observation_evidence.v3":
        # A multi-horizon model family has distinct actual training samples
        # and labels per horizon. Never reuse the h1 sample proof for h2..h5
        # or flatten these into one misleading availability sequence.
        if (kind != "TRAINING" or set(packet) != {"schema_version", "kind", "symbol", "datasets"}
                or packet["kind"] != kind or packet["symbol"] != symbol
                or not isinstance(packet["datasets"], list) or not 1 <= len(packet["datasets"]) <= 5):
            return None, "UNSUPPORTED_" + kind + "_OBSERVATION_PROOF"
        cutoffs, horizons = {}, []
        for dataset in packet["datasets"]:
            if (not isinstance(dataset, dict) or set(dataset) != {"horizon_count", "observations"}
                    or type(dataset["horizon_count"]) is not int or dataset["horizon_count"] not in (1, 2, 3, 4, 5)):
                return None, "UNSUPPORTED_TRAINING_OBSERVATION_PROOF"
            h = dataset["horizon_count"]; horizons.append(h)
            raw = canonical_json_bytes({"schema_version": "blackpod.forecast_observation_evidence.v2",
                "kind": kind, "symbol": symbol, "observations": dataset["observations"]})
            ref = {"path": "derived-horizon-validation.json", "sha256": sha256_bytes(raw), "size_bytes": len(raw)}
            cutoff, reason = _proof_observations({ref["sha256"]: raw}, ref, kind, symbol, {})
            if reason is not None:
                return None, reason
            cutoffs[h] = cutoff
        if horizons != sorted(set(horizons)):
            return None, "UNORDERED_OR_DUPLICATE_TRAINING_HORIZON_DATASETS"
        if horizon_count is not None and horizon_count not in cutoffs:
            return None, "MISSING_TRAINING_HORIZON_DATASET"
        return (max(cutoffs.values()) if horizon_count is None else cutoffs[horizon_count]), None
    if set(packet) != {"schema_version", "kind", "symbol", "observations"} or packet["schema_version"] not in {"blackpod.forecast_observation_evidence.v1", "blackpod.forecast_observation_evidence.v2"} or packet["kind"] != kind or packet["symbol"] != symbol:
        return None, "UNSUPPORTED_" + kind + "_OBSERVATION_PROOF"
    # V1 retains its original 18-place accounting numeric contract. Explicit
    # V2 evidence preserves actual native floating-point feature spellings up
    # to the existing bounded output precision; no feature is rounded or
    # discarded merely to satisfy the passive intake interface.
    native_precision = packet["schema_version"] == "blackpod.forecast_observation_evidence.v2"
    observations = packet["observations"]
    if not isinstance(observations, list) or not 1 <= len(observations) <= 20000:
        return None, "UNSUPPORTED_" + kind + "_OBSERVATION_PROOF"
    times, observed_times = [], []
    try:
        for row in observations:
            fields = {"observed_at", "values", "target_observed_at"} if kind == "TRAINING" else {"observed_at", "values"}
            if not isinstance(row, dict) or set(row) != fields:
                return None, "UNSUPPORTED_" + kind + "_OBSERVATION_PROOF"
            observed = accounting_timestamp(row["observed_at"], "observed_at")
            availability = parse_rfc3339(observed, "observed_at")
            observed_times.append(availability)
            if kind == "TRAINING":
                if row["target_observed_at"] is None:
                    return None, "MISSING_TRAINING_LABEL_AVAILABILITY"
                target_observed = parse_rfc3339(accounting_timestamp(row["target_observed_at"], "target_observed_at"), "target_observed_at")
                if target_observed < availability:
                    return None, "TRAINING_LABEL_BEFORE_FEATURE_OBSERVATION"
                availability = target_observed
            values = row["values"]
            if not isinstance(values, dict) or not 1 <= len(values) <= 128 or any(not isinstance(key, str) or not key or len(key) > 128 for key in values):
                return None, "UNSUPPORTED_" + kind + "_OBSERVATION_PROOF"
            for value in values.values():
                accounting_decimal(value, "observation numeric value", output=native_precision)
            times.append(availability)
    except ContractValidationError:
        return None, "UNSUPPORTED_" + kind + "_OBSERVATION_PROOF"
    if (len(set(times)) != len(times) or times != sorted(times)
            or len(set(observed_times)) != len(observed_times) or observed_times != sorted(observed_times)):
        return None, "UNORDERED_" + kind + "_OBSERVATION_PROOF"
    return max(times), None


def _proof(blobs, reference, kind, symbol, cutoff, cache, horizon_count=None):
    if reference is None or cutoff is None:
        return False, "MISSING_" + kind + "_OBSERVATION_PROOF"
    key = ("observation_proof", reference["sha256"], reference["size_bytes"], kind, symbol, horizon_count)
    if key not in cache:
        cache[key] = _proof_observations(blobs, reference, kind, symbol, cache, horizon_count)
    latest, reason = cache[key]
    if reason is not None:
        return False, reason
    declared = parse_rfc3339(cutoff, "cutoff")
    if latest > declared:
        return False, kind + "_OBSERVATIONS_AFTER_CUTOFF"
    if latest != declared:
        return False, kind + "_CUTOFF_NOT_OBSERVED"
    return True, None


def _calendar(row, intake, blobs, cache):
    reference = row["target_session_evidence"]
    if reference is None:
        return "MISSING_TARGET_SESSION_PROOF"
    packet = _parsed_proof(blobs, reference, "forecast session calendar", cache)
    if packet is None:
        return "UNSUPPORTED_TARGET_SESSION_PROOF"
    try:
        if set(packet) != {"schema_version", "symbol", "anchor_at", "captured_at", "sessions"} or packet["schema_version"] != "blackpod.forecast_session_calendar.v1" or packet["symbol"] != row["symbol"]:
            return "UNSUPPORTED_TARGET_SESSION_PROOF"
        if row["feature_cutoff"] is None or row["issued_at"] is None or row["target_at"] is None or row["horizon_count"] is None:
            return "INCOMPLETE_TARGET_SESSION_BINDING"
        anchor = parse_rfc3339(accounting_timestamp(packet["anchor_at"], "anchor_at"), "anchor_at")
        if anchor != parse_rfc3339(row["feature_cutoff"], "feature_cutoff"):
            return "TARGET_SESSION_ANCHOR_MISMATCH"
        captured = parse_rfc3339(accounting_timestamp(packet["captured_at"], "captured_at"), "captured_at")
        if captured > parse_rfc3339(row["issued_at"], "issued_at") or captured > parse_rfc3339(intake.shadow_as_of, "shadow_as_of"):
            return "TARGET_CALENDAR_CAPTURE_AFTER_ISSUE"
        if not isinstance(packet["sessions"], list) or not 1 <= len(packet["sessions"]) <= 128:
            return "UNSUPPORTED_TARGET_SESSION_PROOF"
        closes, previous_close = [], anchor
        for session in packet["sessions"]:
            if not isinstance(session, dict) or set(session) != {"opens_at", "closes_at"}:
                return "UNSUPPORTED_TARGET_SESSION_PROOF"
            opened = parse_rfc3339(accounting_timestamp(session["opens_at"], "opens_at"), "opens_at")
            closed = parse_rfc3339(accounting_timestamp(session["closes_at"], "closes_at"), "closes_at")
            if not previous_close < opened < closed:
                return "UNORDERED_OR_OVERLAPPING_TARGET_SESSIONS"
            previous_close = closed
            closes.append(closed)
        if row["horizon_count"] > len(closes):
            return "INSUFFICIENT_TARGET_SESSION_PROOF"
        if closes[row["horizon_count"] - 1] != parse_rfc3339(row["target_at"], "target_at"):
            return "TARGET_NOT_DECLARED_HORIZON_SESSION_CLOSE"
    except ContractValidationError:
        return "UNSUPPORTED_TARGET_SESSION_PROOF"
    return None


def _provenance(source, blobs, row_count):
    if source["provenance_evidence"] is None:
        return None
    manifest = validate_forecast_provenance(_json(blobs, source["provenance_evidence"]))
    if manifest["source_sha256"] != source["evidence"]["sha256"]:
        raise ContractValidationError("forecast provenance binds a different source hash")
    if any(row["source_row_number"] > row_count for row in manifest["rows"]):
        raise ContractValidationError("forecast provenance references nonexistent source rows")
    verified_refs = set()
    def verify_ref(reference):
        if reference is not None:
            key = (reference["sha256"], reference["size_bytes"])
            if key not in verified_refs:
                _blob(blobs, reference)
                verified_refs.add(key)
    for field in _REQUIRED_MODEL_REFS + ("calibration_evidence",):
        if manifest["model"][field] is not None:
            verify_ref(manifest["model"][field])
    for row in manifest["rows"]:
        if row["target_session_evidence"] is not None:
            verify_ref(row["target_session_evidence"])
    return manifest


def _model_config_reason(manifest, blobs):
    reference = manifest["model"]["config_evidence"]
    if reference is None:
        return None  # the separate missing-reference gate supplies the reason
    raw = _blob(blobs, reference)
    try:
        packet = parse_strict_json_object_bytes(raw, document_name="forecast model configuration proof")
    except ContractValidationError:
        return "UNSUPPORTED_MODEL_CONFIG_PROOF"
    if (set(packet) != {"schema_version", "model_kind", "quantile_levels", "target", "currency", "feature_names"}
        or packet["schema_version"] != "blackpod.forecast_model_config.v1"
        or packet["model_kind"] != manifest["model"]["model_kind"]
        or packet["quantile_levels"] != ["0.10", "0.50", "0.90"]
        or packet["target"] != "FUTURE_CLOSE" or packet["currency"] != "USD"
        or not isinstance(packet["feature_names"], list) or not 1 <= len(packet["feature_names"]) <= 128
        or any(not isinstance(item, str) or not item or len(item) > 128 for item in packet["feature_names"])
        or len(set(packet["feature_names"])) != len(packet["feature_names"])):
        return "UNSUPPORTED_MODEL_CONFIG_PROOF"
    return None


def _project_row(intake, source, row_number, raw, manifest, ambiguous, metadata_by_number):
    projection = _source_projection(raw, source["format"])
    symbol = symbol_text(projection["symbol"])
    row = {"row_id": "forecast-row-" + sha256_bytes(canonical_json_bytes({"source_sha256": source["evidence"]["sha256"], "source_row_number": row_number})),
        "source_id": source["source_id"], "source_row_number": row_number, "source_evidence": source["evidence"],
        "symbol": symbol, "source_date": projection["source_date"], "source_time_precision": "UNVERIFIED", "raw_source_row": dict(raw),
        "units": None, "value_semantics": None, "q10": None, "q50": None, "q90": None, "issued_at": None,
        "feature_cutoff": None, "training_cutoff": None, "horizon_count": None, "horizon_unit": None, "target_at": None, "target_session_evidence": None,
        "model_id": None, "model_version": None, "reference_price": None, "reference_at": None,
        "gate": "DEFER", "reason_codes": [], "realized_outcome": None, "evaluation": None}
    reasons = row["reason_codes"]
    if source["format"] == "GOVERNED_PRICE_FORECAST_JSON":
        for field in ("issued_at", "feature_cutoff", "training_cutoff", "target_at", "reference_at"):
            if raw[field] is not None:
                try:
                    row[field] = accounting_timestamp(raw[field], field)
                except ContractValidationError:
                    reasons.append("INVALID_SOURCE_" + field.upper())
        for field, expected in (("units", "PRICE_USD"), ("value_semantics", "PREDICTED_CLOSE_LEVEL"), ("horizon_unit", "TRADING_SESSION")):
            if raw[field] == expected:
                row[field] = expected
        for field in ("model_id", "model_version"):
            if raw[field] is not None:
                from .identifiers import IdentifierError, validate_identifier
                try:
                    row[field] = validate_identifier(raw[field], field)
                except IdentifierError:
                    reasons.append("INVALID_SOURCE_" + field.upper())
        if raw["reference_price"] is not None:
            try:
                row["reference_price"] = accounting_decimal(raw["reference_price"], "reference_price", positive=True)
            except ContractValidationError:
                reasons.append("INVALID_SOURCE_REFERENCE_PRICE")
    try:
        valid_date = _source_date(row["source_date"])
        row["source_time_precision"] = "DATE_ONLY" if len(valid_date) == 10 else "RFC3339"
    except ContractValidationError:
        reasons.append("UNVERIFIED_SOURCE_DATE")
    for field in ("q10", "q50", "q90"):
        try:
            row[field] = accounting_decimal(projection[field], field)
        except ContractValidationError:
            reasons.append("INVALID_" + field.upper())
    if all(row[field] is not None for field in ("q10", "q50", "q90")):
        quantiles = [Decimal(row[field]) for field in ("q10", "q50", "q90")]
        if min(quantiles) <= 0:
            reasons.append("NONPOSITIVE_PRICE_LEVEL")
        if quantiles != sorted(quantiles):
            reasons.append("CROSSED_QUANTILES")
    if source["format"] != "GOVERNED_PRICE_FORECAST_JSON" and raw["Pattern"] != "LIVE":
        reasons.append("NONLIVE_SOURCE_PATTERN")
    if projection["timeframe"] not in {"1D", "1d"}:
        reasons.append("UNSUPPORTED_TIMEFRAME")
    original_horizon = projection["horizon"]
    if source["format"] == "GALACTICA_PHASE2_CSV":
        match = re.fullmatch(r"([1-9][0-9]{0,3})D", original_horizon)
        original_horizon = int(match.group(1)) if match else None
    elif source["format"] == "GOVERNED_PRICE_FORECAST_JSON":
        original_horizon = int(original_horizon) if original_horizon is not None else None
    else:
        reasons.append("HORIZON_NOT_RETAINED")
    if ambiguous:
        reasons.append("AMBIGUOUS_SOURCE_IDENTITY")
    if manifest is None:
        reasons.append("MISSING_SOURCE_BOUND_PROVENANCE")
        if original_horizon is not None:
            row["horizon_count"] = original_horizon  # preserve the declared count; do not infer CSV units
    else:
        model = manifest["model"]
        row["model_id"], row["model_version"] = model["model_id"], model["model_version"]
        metadata = metadata_by_number.get(row_number)
        if metadata is None:
            reasons.append("MISSING_ROW_PROVENANCE")
        else:
            if metadata["symbol"] != symbol:
                raise ContractValidationError("forecast provenance row symbol differs from its source")
            for field in ("units", "value_semantics", "issued_at", "feature_cutoff", "training_cutoff", "horizon_count", "horizon_unit", "target_at", "target_session_evidence", "reference_price", "reference_at"):
                row[field] = metadata[field]
            if source["format"] == "GOVERNED_PRICE_FORECAST_JSON":
                for field in ("units", "value_semantics", "horizon_unit", "issued_at", "feature_cutoff", "training_cutoff", "target_at", "reference_price", "reference_at", "model_id", "model_version"):
                    normalized = accounting_timestamp(raw[field], field) if field in {"issued_at", "feature_cutoff", "training_cutoff", "target_at", "reference_at"} and raw[field] is not None else raw[field]
                    if normalized != row[field]:
                        raise ContractValidationError("governed forecast row metadata differs from bound provenance: " + field)
            if original_horizon != row["horizon_count"]:
                if source["format"] == "GALACTICA_PHASE3_CSV":
                    reasons.append("PROVENANCE_CANNOT_RESTORE_ERASED_HORIZON")
                else:
                    raise ContractValidationError("forecast horizon differs from bound provenance")
        if manifest["status"] != "REVIEWED_SOURCE_BOUND":
            reasons.append("UNREVIEWED_PROVENANCE")
        if manifest["reviewed_by"] is None or manifest["reviewed_at"] is None:
            reasons.append("MISSING_REVIEW_RECORD")
        for field in ("model_id", "model_version", "model_kind"):
            if model[field] is None:
                reasons.append("MISSING_" + field.upper())
        for field in _REQUIRED_MODEL_REFS:
            if model[field] is None:
                reasons.append("MISSING_" + field.upper())
    if row["units"] != "PRICE_USD" or row["value_semantics"] != "PREDICTED_CLOSE_LEVEL":
        reasons.append("UNVERIFIED_PRICE_UNITS_AND_SEMANTICS")
    if row["horizon_count"] not in intake.policy["allowed_horizon_sessions"] or row["horizon_unit"] != "TRADING_SESSION":
        reasons.append("UNSUPPORTED_OR_UNVERIFIED_HORIZON")
    if intake.domain == "INVESTMENT":
        reasons.append("SHORT_HORIZON_NOT_INVESTMENT_EVIDENCE")
    return row


def _time_gates(row, manifest, intake, blobs, cache):
    reasons = row["reason_codes"]
    as_of = parse_rfc3339(intake.shadow_as_of, "shadow_as_of")
    times = {}
    for field in ("issued_at", "feature_cutoff", "training_cutoff", "target_at"):
        if row[field] is None:
            reasons.append("MISSING_" + field.upper())
        else:
            times[field] = parse_rfc3339(row[field], field)
    if "issued_at" in times:
        issued = times["issued_at"]
        if issued > as_of:
            reasons.append("ISSUED_AFTER_SHADOW_AS_OF")
        elif (as_of - issued).total_seconds() > intake.policy["max_forecast_age_seconds"]:
            reasons.append("STALE_FORECAST")
        for field, label in (("feature_cutoff", "FEATURE"), ("training_cutoff", "TRAINING")):
            if field in times:
                if times[field] > issued:
                    reasons.append(label + "_CUTOFF_AFTER_ISSUE")
                elif (as_of - times[field]).total_seconds() > intake.policy["max_" + label.lower() + "_age_seconds"]:
                    reasons.append("STALE_" + label + "_CUTOFF")
        if "target_at" in times and times["target_at"] <= issued:
            reasons.append("TARGET_NOT_AFTER_ISSUE")
    if "target_at" in times and times["target_at"] <= as_of:
        reasons.append("TARGET_ALREADY_ELAPSED")
    if "training_cutoff" in times and "feature_cutoff" in times and times["training_cutoff"] > times["feature_cutoff"]:
        reasons.append("TRAINING_CUTOFF_AFTER_FEATURE_CUTOFF")
    if "feature_cutoff" in times and row["source_time_precision"] != "UNVERIFIED":
        if row["source_time_precision"] == "DATE_ONLY":
            if times["feature_cutoff"].date().isoformat() != row["source_date"]:
                reasons.append("SOURCE_DATE_FEATURE_CUTOFF_MISMATCH")
        elif parse_rfc3339(_source_date(row["source_date"]), "source_date") != times["feature_cutoff"]:
            reasons.append("SOURCE_DATE_FEATURE_CUTOFF_MISMATCH")
    if row["reference_at"] is not None:
        reference = parse_rfc3339(row["reference_at"], "reference_at")
        if reference > times.get("issued_at", as_of):
            reasons.append("REFERENCE_PRICE_AFTER_ISSUE")
    if manifest is not None:
        config_ref = manifest["model"]["config_evidence"]
        config_key = ("model_config", None if config_ref is None else config_ref["sha256"], manifest["model"]["model_kind"])
        if config_key not in cache:
            cache[config_key] = _model_config_reason(manifest, blobs)
        config_reason = cache[config_key]
        if config_reason is not None:
            reasons.append(config_reason)
        if manifest["reviewed_at"] is not None:
            reviewed = parse_rfc3339(manifest["reviewed_at"], "reviewed_at")
            if reviewed > as_of:
                reasons.append("REVIEW_AFTER_SHADOW_AS_OF")
            if "issued_at" in times and reviewed < times["issued_at"]:
                reasons.append("REVIEW_BEFORE_ISSUE")
        for kind, field in (("FEATURES", "feature_cutoff"), ("TRAINING", "training_cutoff")):
            passed, reason = _proof(blobs, manifest["model"]["feature_evidence" if kind == "FEATURES" else "training_evidence"], kind, row["symbol"], row[field], cache,
                row["horizon_count"] if kind == "TRAINING" else None)
            if not passed:
                reasons.append(reason)
    calendar_key = ("calendar", None if row["target_session_evidence"] is None else row["target_session_evidence"]["sha256"],
        row["symbol"], row["feature_cutoff"], row["issued_at"], row["target_at"], row["horizon_count"])
    if calendar_key not in cache:
        cache[calendar_key] = _calendar(row, intake, blobs, cache)
    calendar_reason = cache[calendar_key]
    if calendar_reason is not None:
        reasons.append(calendar_reason)


def assess_forecast_intake(intake: ForecastIntake, blobs=None):
    if not isinstance(intake, ForecastIntake):
        intake = ForecastIntake.from_mapping(intake)
    blobs = {} if blobs is None else blobs
    context, proof_cache = SimpleNamespace(**intake.to_dict()), {}
    rows, summaries, bound_paths = [], [], {"forecast-intake/input.v1.json": sha256_bytes(intake.to_bytes())}
    def bind(reference):
        if reference is not None:
            if reference["path"] == "forecast-intake/input.v1.json":
                raise ContractValidationError("forecast evidence collides with reserved intake input path")
            if reference["path"] in bound_paths and bound_paths[reference["path"]] != reference["sha256"]:
                raise ContractValidationError("forecast evidence path binds conflicting hashes")
            bound_paths[reference["path"]] = reference["sha256"]
    for source in context.sources:
        bind(source["evidence"]); bind(source["provenance_evidence"])
        raw_rows = _source_rows(source, blobs)
        manifest = _provenance(source, blobs, len(raw_rows))
        metadata_by_number = {} if manifest is None else {row["source_row_number"]: row for row in manifest["rows"]}
        if manifest is not None:
            for field in _REQUIRED_MODEL_REFS + ("calibration_evidence",):
                bind(manifest["model"][field])
            for metadata in manifest["rows"]:
                bind(metadata["target_session_evidence"])
        projections = [_source_projection(raw, source["format"]) for raw in raw_rows]
        counts = Counter((item["symbol"], item["source_date"], item["horizon"]) for item in projections)
        source_rows = []
        for number, (raw, projection) in enumerate(zip(raw_rows, projections), 1):
            ambiguous = counts[(projection["symbol"], projection["source_date"], projection["horizon"])] > 1
            row = _project_row(context, source, number, raw, manifest, ambiguous, metadata_by_number)
            _time_gates(row, manifest, context, blobs, proof_cache)
            row["reason_codes"] = list(dict.fromkeys(row["reason_codes"]))
            if not row["reason_codes"]:
                row["gate"] = "CURRENT_SHADOW_ELIGIBLE"
            source_rows.append(row)
        rows.extend(source_rows)
        if len(rows) > 20000:
            raise ContractValidationError("intake exceeds the total supported row count")
        admitted = sum(row["gate"] == "CURRENT_SHADOW_ELIGIBLE" for row in source_rows)
        summaries.append({"source_id": source["source_id"], "evidence": source["evidence"], "format": source["format"],
            "provenance_status": "MISSING" if manifest is None else manifest["status"], "row_count": len(source_rows),
            "admitted_count": admitted, "deferred_count": len(source_rows) - admitted})
    admitted = sum(row["gate"] == "CURRENT_SHADOW_ELIGIBLE" for row in rows)
    result = {"schema_version": FORECAST_RESULT_SCHEMA_VERSION, "intake_id": intake.intake_id, "domain": intake.domain,
        "shadow_as_of": intake.shadow_as_of, "status": FORECAST_INTAKE_SCOPE, "rows": rows, "source_summaries": summaries,
        "admitted_count": admitted, "deferred_count": len(rows) - admitted,
        "reason_codes": [] if admitted else ["NO_CURRENT_GOVERNED_FORECASTS"], "limitations": list(FORECAST_LIMITATIONS),
        "auto_trading_enabled": False, "authority": intake.authority}
    return validate_forecast_result(result, intake)


def evidence_for_forecast_intake(intake: ForecastIntake, blobs=None):
    if not isinstance(intake, ForecastIntake):
        intake = ForecastIntake.from_mapping(intake)
    blobs = {} if blobs is None else blobs
    assess_forecast_intake(intake, blobs)
    result = {"forecast-intake/input.v1.json": intake.to_bytes()}
    def retain(reference):
        if reference is None:
            return
        raw = _blob(blobs, reference)
        if reference["path"] in result and result[reference["path"]] != raw:
            raise ContractValidationError("forecast evidence path binds conflicting source bytes")
        result[reference["path"]] = raw
    for source in intake.sources:
        retain(source["evidence"]); retain(source["provenance_evidence"])
        if source["provenance_evidence"] is not None:
            manifest = validate_forecast_provenance(_json(blobs, source["provenance_evidence"]))
            for field in _REQUIRED_MODEL_REFS + ("calibration_evidence",):
                retain(manifest["model"][field])
            for row in manifest["rows"]:
                retain(row["target_session_evidence"])
    return result
