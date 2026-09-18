"""Read-only, bounded presentation of an explicitly selected canonical scan.

Checks transport integrity, safety, and evidence links, not scientific arithmetic.
No canonical package, scanner, collector, provider, or source artifact is executed.
"""
from __future__ import annotations

from collections import Counter
from datetime import date, datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import re
import threading

from .contracts.mission_request import parse_rfc3339, parse_strict_json_object_bytes
from .hashing import canonical_json_bytes
from .sentry_reader import _read_regular, _safe_json_tree, _stamp

SCHEMA_VERSION = "blackpod.sentry_scan_feed.v1"
MAX_SOURCE_BYTES = 16 * 1024 * 1024
MAX_FEED_BYTES = 256 * 1024
MAX_SYMBOLS = 128
MAX_DISPLAY_DIAGNOSTICS = 8
PROFILES = {"GENERAL_EQUITY", "ETF"}
TOP_KEYS = "schema_version scan_id scan_kind session_date as_of manifest_sha256 reference_manifest_id validation_protocol_id calibration_ids source_files configuration population symbol_receipts windows limitations profile_statuses research_only production_ready observation_only order_submission_enabled current_attention_published".split()
ENTRY_KEYS = "symbol profile sensor_result_id assessment_ids percentile metric_name winning_assessment_id calibration_id reasons assessment_exclusions quality_flags".split()


def _require(value):
    if not value:
        raise ValueError("scan receipt validation failed")


def _object(value, keys):
    _require(isinstance(value, dict) and set(value) == set(keys))
    return value


def _array(value, maximum=MAX_SYMBOLS):
    _require(isinstance(value, list) and len(value) <= maximum)
    return value


def _text(value, maximum=512):
    _require(isinstance(value, str) and value == value.strip() and bool(value)
             and len(value) <= maximum and not any(ord(c) < 32 or ord(c) == 127 for c in value))
    return value


def _identifier(value):
    _text(value, 256)
    _require(re.fullmatch(r"[A-Za-z0-9_.:-]+", value))
    return value


def _hash(value):
    _require(isinstance(value, str) and re.fullmatch(r"[a-f0-9]{64}", value))
    return value


def _integer(value, maximum=2**53 - 1):
    _require(type(value) is int and 0 <= value <= maximum)
    return value


def _number(value, minimum=0, maximum=1):
    _require(type(value) in (int, float) and math.isfinite(value) and minimum <= value <= maximum)
    return value


def _day(value):
    _require(isinstance(value, str) and date.fromisoformat(value).isoformat() == value)
    return value


def _strings(value, maximum=128):
    values = [_text(s) for s in _array(value, maximum)]
    _require(all(re.fullmatch(r"[A-Za-z0-9_ .:(),+-]+", s) for s in values))
    return values


def _symbols(value):
    values = _array(value)
    _require(all(isinstance(s, str) and re.fullmatch(r"[A-Z][A-Z0-9.-]{0,14}", s) for s in values)
             and values == sorted(set(values)))
    return values


def _display_diagnostics(values):
    """Only shorten display detail; preserve the failed symbol and report ID."""
    if len(values) <= MAX_DISPLAY_DIAGNOSTICS:
        return list(values)
    return [*values[:MAX_DISPLAY_DIAGNOSTICS],
            f"ADDITIONAL_DIAGNOSTICS_OMITTED:{len(values) - MAX_DISPLAY_DIAGNOSTICS}"]


def _digest(value):
    # Canonical calibration.digest uses compact, sorted JSON with ASCII escaping.
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def _identity(value, field, prefix):
    _require(value[field] == prefix + _digest({k: v for k, v in value.items() if k != field}))


def _safety(value, research=False):
    _require(value["observation_only"] is True and value["order_submission_enabled"] is False)
    if research:
        _require(value["research_only"] is True)


def _file(value):
    _text(value["file_name"], 255)
    _require(value["file_name"] not in {".", ".."} and ".." not in value["file_name"]
             and not any(c in value["file_name"] for c in "/\\"))
    _hash(value["sha256"]); _integer(value["byte_size"], 64 * 1024 * 1024)


def _project(receipt, checked_at):
    _object(receipt, TOP_KEYS)
    _require(receipt["schema_version"] == "sentry.operational_scan.v1"
             and receipt["scan_kind"] == "OFFLINE_RESEARCH_SNAPSHOT"
             and receipt["production_ready"] is False and receipt["current_attention_published"] is False)
    _safety(receipt, True); _identity(receipt, "scan_id", "sentry-operational-scan-")
    session = _day(receipt["session_date"])
    as_of = parse_rfc3339(receipt["as_of"], "scan as_of")
    _require(as_of.utcoffset().total_seconds() == 0 and session < as_of.date().isoformat() and as_of <= checked_at)
    _hash(receipt["manifest_sha256"])
    for field in ("reference_manifest_id", "validation_protocol_id"):
        _identifier(receipt[field])
    references = _array(receipt["calibration_ids"], 100)
    _require(references == sorted(set(references)) and bool(references))
    for value in references:
        _identifier(value)
    files = _array(receipt["source_files"], 2)
    _require([v["role"] for v in files] == ["protocol", "references"])
    for value in files:
        _object(value, ["role", "file_name", "sha256", "byte_size"]); _file(value)
    profiles = _object(receipt["profile_statuses"], PROFILES)
    _require(all(v == "RESEARCH_ONLY" for v in profiles.values()))
    config = _object(receipt["configuration"], ["windows", "minimum_history_sessions", "capacity", "minimum_percentile", "per_profile_capacity"])
    _require(config["windows"] == [20, 60] and config["minimum_history_sessions"] == 66)
    _integer(config["capacity"], MAX_SYMBOLS); _number(config["minimum_percentile"])
    _require(config["minimum_percentile"] == .95)
    caps = _object(config["per_profile_capacity"], PROFILES)
    for value in caps.values():
        _integer(value, MAX_SYMBOLS)
    population = _object(receipt["population"], ["requested", "observed", "failed", "requested_count", "observed_count", "failed_count"])
    requested, observed, failed = [_symbols(population[k]) for k in ("requested", "observed", "failed")]
    _require(bool(requested) and not set(observed) & set(failed) and sorted(observed + failed) == requested)
    for key in ("requested", "observed", "failed"):
        _require(_integer(population[key + "_count"], MAX_SYMBOLS) == len(population[key]))
    rows = _array(receipt["symbol_receipts"])
    _require([r["symbol"] for r in rows] == requested)
    by_symbol, symbols = {}, []
    for row in rows:
        _object(row, "symbol status reasons profile metadata_fingerprint history failure_evidence history_validation observation_ids".split())
        name = row["symbol"]; by_symbol[name] = row
        _require(row["status"] == ("OBSERVED" if name in observed else "EXCLUDED"))
        reasons = _strings(row["reasons"])
        _require(bool(reasons) if name in failed else True)
        _require(row["profile"] is None or row["profile"] in PROFILES)
        if row["metadata_fingerprint"] is not None:
            _hash(row["metadata_fingerprint"])
        history = row["history"]
        if history is not None:
            _object(history, "file_name sha256 byte_size provider captured_at source_receipt_id first_session last_session row_count".split()); _file(history)
            _identifier(history["provider"]); _identifier(history["source_receipt_id"])
            captured = parse_rfc3339(history["captured_at"], "history capture")
            _require(captured.utcoffset().total_seconds() == 0 and captured <= as_of)
            # An excluded malformed/stale/after-target history is still evidence
            # of the exclusion. Do not make its bad dates abort healthy symbols.
            for field in ("first_session", "last_session"):
                if history[field] is not None:
                    _day(history[field])
            _integer(history["row_count"], 1_000_000)
        failure = row["failure_evidence"]
        if failure is not None:
            _object(failure, "file_name sha256 byte_size receipt_id status".split()); _file(failure)
            _identifier(failure["receipt_id"]); _identifier(failure["status"])
            _require(reasons == ["CAPTURE_" + failure["status"]])
        validation = row["history_validation"]
        if validation is not None:
            _object(validation, "report_id structurally_valid research_usable errors warnings".split())
            _identifier(validation["report_id"])
            _require(type(validation["structurally_valid"]) is bool and type(validation["research_usable"]) is bool)
            _strings(validation["errors"]); _strings(validation["warnings"])
        if name in observed:
            _require(row["profile"] in PROFILES and row["metadata_fingerprint"] is not None
                     and history is not None and history["first_session"] is not None
                     and history["first_session"] <= session and history["last_session"] == session and history["row_count"] >= 66
                     and failure is None and validation is not None and validation["research_usable"] is True
                     and validation["structurally_valid"] is True and not validation["errors"] and not reasons
                     and captured.date().isoformat() > session)
            _object(row["observation_ids"], ["20", "60"])
        else:
            _require(row["observation_ids"] is None)
        displayed = {k: row[k] for k in ("symbol", "status", "reasons", "profile", "history", "failure_evidence", "history_validation")}
        if validation is not None:
            displayed["history_validation"] = {**validation,
                "errors": _display_diagnostics(validation["errors"]),
                "warnings": _display_diagnostics(validation["warnings"])}
        symbols.append(displayed)
    windows = _array(receipt["windows"], 2)
    _require([w["lookback"] for w in windows] == [20, 60])
    summaries = []
    for window in windows:
        _object(window, ["lookback", "sensors", "assessments", "attention"])
        lookback = window["lookback"]
        sensors = _array(window["sensors"])
        _require(sorted(s["symbol"] for s in sensors) == observed)
        sensor_ids = {}
        for sensor in sensors:
            _object(sensor, "symbol instrument_class profile as_of state direction calibration_status measurements measurement_context provenance quality_flags missing_information reasons legacy_classification legacy_scores legacy_event_id method_version observation_only order_submission_enabled schema_version result_id".split())
            _require(sensor["schema_version"] == "sentry.sensor_result.v1")
            _safety(sensor); _identity(sensor, "result_id", "sentry-sensor-")
            name = sensor["symbol"]; original = by_symbol[name]
            _require(sensor["profile"] == original["profile"] and sensor["state"] == "RESEARCH_OBSERVATION"
                     and sensor["direction"] == "UNKNOWN" and sensor["calibration_status"] == "UNCALIBRATED"
                     and sensor["result_id"] == original["observation_ids"][str(lookback)]
                     and parse_rfc3339(sensor["as_of"], "sensor timestamp") == as_of)
            _require(sensor["instrument_class"] == ("ETF" if original["profile"] == "ETF" else "EQUITY")
                     and sensor["legacy_classification"] is None and sensor["legacy_event_id"] is None and sensor["legacy_scores"] == [])
            pairs = _array(sensor["measurement_context"], 64)
            _require(all(isinstance(p, list) and len(p) == 2 and all(isinstance(v, str) for v in p) for p in pairs))
            context = dict(pairs)
            _require(len(context) == len(pairs))
            _require(context["lookback"] == str(lookback) and context["observed_session"] == session
                     and context["metadata_fingerprint"] == original["metadata_fingerprint"])
            sensor_ids[name] = sensor["result_id"]
        assessments = _array(window["assessments"], MAX_SYMBOLS * 20)
        by_assessment = {}
        for assessment in assessments:
            _object(assessment, "symbol profile session_date sensor_result_id calibration_id metric_name percentile tail_exceeded eligible training_end exclusion_reasons quality_flags observed_value threshold reference_count tail research_only observation_only order_submission_enabled schema_version assessment_id".split())
            _require(assessment["schema_version"] == "sentry.anomaly_assessment.v1")
            _safety(assessment, True); _identity(assessment, "assessment_id", "sentry-assessment-")
            name = assessment["symbol"]
            _require(name in sensor_ids and assessment["sensor_result_id"] == sensor_ids[name]
                     and assessment["profile"] == by_symbol[name]["profile"] and assessment["session_date"] == session
                     and _day(assessment["training_end"]) < session and assessment["calibration_id"] in references)
            _require(assessment["assessment_id"] not in by_assessment)
            by_assessment[assessment["assessment_id"]] = assessment
        attention = window["attention"]
        _object(attention, "schema_version policy_version session_date capacity minimum_percentile per_profile_capacity selected excluded input_assessment_ids input_count unique_assessment_count duplicate_count candidate_count eligible_candidate_count capacity_remaining research_only observation_only order_submission_enabled policy_id selection_id".split())
        for count in ("capacity", "input_count", "unique_assessment_count", "duplicate_count", "candidate_count", "eligible_candidate_count", "capacity_remaining"):
            _integer(attention[count], MAX_SYMBOLS * 20)
        for pair in _array(attention["per_profile_capacity"], 2):
            _require(isinstance(pair, list) and len(pair) == 2)
            _integer(pair[1], MAX_SYMBOLS)
        _require(attention["schema_version"] == "sentry.attention_selection.v1"
                 and attention["policy_version"] == "sentry.attention.max_eligible_percentile.v1")
        _safety(attention, True); _identity(attention, "selection_id", "sentry-attention-")
        policy = {k: attention[k] for k in ("policy_version", "capacity", "per_profile_capacity", "minimum_percentile")}
        _require(attention["policy_id"] == "sentry-attention-policy-" + _digest(policy)
                 and attention["session_date"] == session and attention["capacity"] == config["capacity"]
                 and attention["minimum_percentile"] == config["minimum_percentile"]
                 and attention["per_profile_capacity"] == [[p, caps[p]] for p in sorted(caps)]
                 and attention["input_assessment_ids"] == sorted(by_assessment)
                 and attention["input_count"] == attention["unique_assessment_count"] == len(by_assessment)
                 and attention["duplicate_count"] == 0)
        entries, presented, evidence_ids = [], {}, []
        for group in ("selected", "excluded"):
            presented[group] = []
            for entry in _array(attention[group]):
                _object(entry, ENTRY_KEYS)
                name = entry["symbol"]; entries.append(entry)
                _require(name in observed and entry["profile"] == by_symbol[name]["profile"] and entry["sensor_result_id"] == sensor_ids[name])
                ids = _array(entry["assessment_ids"], 20)
                _require(bool(ids) and ids == sorted(set(ids)) and all(key in by_assessment and by_assessment[key]["symbol"] == name for key in ids))
                evidence_ids.extend(ids); _strings(entry["reasons"]); _strings(entry["quality_flags"])
                if entry["percentile"] is not None:
                    _number(entry["percentile"])
                    winner = by_assessment.get(entry["winning_assessment_id"])
                    _require(winner is not None and entry["winning_assessment_id"] in ids
                             and winner["eligible"] is True and winner["tail_exceeded"] is True
                             and all(entry[k] == winner[k] for k in ("percentile", "metric_name", "calibration_id")))
                    _identifier(entry["metric_name"])
                else:
                    _require(all(entry[k] is None for k in ("metric_name", "winning_assessment_id", "calibration_id")))
                if group == "selected":
                    _require(entry["percentile"] is not None and entry["percentile"] >= config["minimum_percentile"] and entry["reasons"] == ["SELECTED"])
                else:
                    _require(bool(entry["reasons"]) and "SELECTED" not in entry["reasons"])
                presented[group].append({k: entry[k] for k in ("symbol", "profile", "percentile", "metric_name", "sensor_result_id", "winning_assessment_id", "calibration_id", "reasons", "quality_flags")})
        _require(sorted(e["symbol"] for e in entries) == observed and sorted(evidence_ids) == sorted(by_assessment)
                 and attention["candidate_count"] == len(entries)
                 and attention["eligible_candidate_count"] == sum(e["percentile"] is not None for e in entries)
                 and len(presented["selected"]) <= config["capacity"]
                 and attention["capacity_remaining"] == config["capacity"] - len(presented["selected"]))
        _require(all(n <= caps[p] for p, n in Counter(e["profile"] for e in presented["selected"]).items()))
        summaries.append({"lookback": lookback, **{k: attention[k] for k in ("selection_id", "policy_id", "candidate_count", "eligible_candidate_count", "capacity_remaining")}, **presented})
    _strings(receipt["limitations"], 40)
    return {**{k: receipt[k] for k in ("scan_id", "scan_kind", "session_date", "as_of", "manifest_sha256", "reference_manifest_id", "validation_protocol_id", "calibration_ids", "configuration", "population", "profile_statuses", "limitations")}, "symbols": symbols, "windows": summaries}


class SentryScanReader:
    def __init__(self, archive: Path | None = None):
        if archive is not None:
            path = Path(archive)
            if ".." in path.parts or ".." in path.name or any(ord(c) < 32 or ord(c) == 127 for c in str(path)) or not path.name or any(c in path.name for c in "\\"):
                raise ValueError("Sentry scan archive must be an explicit normalized file path.")
        self.archive = None if archive is None else Path(archive)
        self._lock = threading.Lock()

    def current(self):
        with self._lock:
            now = datetime.now(timezone.utc)
            base = {"schema_version": SCHEMA_VERSION, "checked_at": _stamp(now), "source": None, "scan": None,
                    "observation_only": True, "order_submission_enabled": False, "current_attention_published": False}
            if self.archive is None:
                return {**base, "status": "NOT_CONFIGURED", "message": "No recorded Sentry scan is configured. Opening this view does not run a scan."}
            try:
                raw = _read_regular(self.archive, MAX_SOURCE_BYTES)
                receipt = parse_strict_json_object_bytes(raw, document_name="Sentry scan")
                scan = _project(receipt, now)
                result = {**base, "status": "READY", "message": "Recorded offline research scan; not streaming, current market verification, or a published production attention universe.",
                          "source": {"file_name": self.archive.name, "sha256": hashlib.sha256(raw).hexdigest(), "byte_size": len(raw), "declared_evidence_reverified": False}, "scan": scan}
                _safe_json_tree(result); _require(len(canonical_json_bytes(result)) <= MAX_FEED_BYTES)
                return result
            except (OSError, ValueError, TypeError, KeyError, IndexError, OverflowError, RecursionError):
                return {**base, "status": "UNAVAILABLE", "message": "The configured Sentry scan receipt is missing, changing, or invalid. No substitute scan is shown."}
