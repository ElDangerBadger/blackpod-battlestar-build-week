"""Bounded read-only projection of the reviewed, frozen Calibration V2 checkpoint.

This is not a scanner, scientific verifier, collector status client, or generic
artifact server. Four explicitly configured files are checked against reviewed
byte hashes on every read. No canonical package or large research panel is loaded.
"""
from __future__ import annotations

import hashlib
import math
import re
import threading
from datetime import date, datetime, timezone
from pathlib import Path

from .contracts.mission_request import parse_rfc3339, parse_strict_json_object_bytes
from .hashing import canonical_json_bytes
from .sentry_reader import _read_regular, _safe_json_tree, _stamp


SCHEMA_VERSION = "blackpod.sentry_research_feed.v1"
MAX_SOURCE_BYTES = 128 * 1024
MAX_FEED_BYTES = 64 * 1024
MANIFEST_ID = "sentry-prospective-protocol-0532d6b1e78c413dea60bcce113a996e9d46a7f59f1ba48754b830e56f52f533"
ARMS = ("BASELINE", "ELIGIBLE_INCUMBENT_FIRST", "ELIGIBLE_INCUMBENT_FIRST_MAX_2_NEW")
# Dedicated checkpoint adapter: these are independently reviewed byte pins, not
# hashes supplied by the same untrusted documents they purport to authenticate.
SOURCE_PINS = {
    "development-declaration.json": "680d1b190a61ef350af7b4f409eeafb9015b4cb27e134637e9cc42909fe8c456",
    "development-summary.json": "938eb64abd60e51e331310e8cdc028ca7c58e2318986eb7bb6d6bb999265e885",
    "prospective-protocol.json": "6cc5608384f12fd98ce0ed9db9c25d3226471b8d0feba7df38cd36ae7e464fce",
    "failed-warmup-integrity.json": "54727ca7dcdeecd7876c0325fa58dd39feec59e798330e4b461bc1e64ac04ba6",
}
UPSTREAM_PINS = {
    "cache": "2787c0a9bc0034f9945924f9f85deb35ed0e0acff1e2ad39e342ed93cd1ac317",
    "results": "6b92114d2b13cba2c4ad87e6e71c5fabca0c0267333acb1a717bf793f86d4513",
}
LIMITATIONS = [
    "Historical development evidence, not independent holdout validation or current market state.",
    "Top symbols count historical selected sessions; they are not current candidates or recommendations.",
    "This is a fixed archived checkpoint, not live collector or scheduler health.",
    "Upstream cache/results hashes are declared provenance; their large artifacts are not reverified by this view.",
    "No raw normalized sensor measurements, new calibration, downstream analysis, or trading authority is supplied.",
]


def _require(condition: bool) -> None:
    if not condition:
        raise ValueError("research checkpoint validation failed")


def _integer(value, minimum=0, maximum=1_000_000):
    _require(type(value) is int and minimum <= value <= maximum)
    return value


def _ratio(value, *, maximum=1_000_000):
    number = value["value"]
    _require(type(number) in (int, float) and math.isfinite(number) and 0 <= number <= maximum)
    return number


def _day(value):
    _require(isinstance(value, str) and date.fromisoformat(value).isoformat() == value)
    return value


def _project(documents, *, checked_at):
    declaration = documents["development-declaration.json"]
    summary = documents["development-summary.json"]
    protocol = documents["prospective-protocol.json"]
    closeout = documents["failed-warmup-integrity.json"]
    science, recorded, warmup = protocol["scientific_spec"], closeout["status"], closeout["warmup"]
    _require(declaration["schema_version"] == "sentry.calibration_v2_declaration.v1"
             and protocol["schema_version"] == "sentry.prospective_protocol.v2"
             and closeout["schema_version"] == "sentry.v2_closeout_integrity.v1")
    _require(protocol["manifest_id"] == closeout["manifest_id"] == recorded["manifest_id"] == MANIFEST_ID)
    _require(protocol["status"] == recorded["status"] == "RESEARCH_ONLY"
             and protocol["production_ready"] is False
             and protocol["observation_only"] is True
             and recorded["observation_only"] is True)
    for value in (declaration, protocol, recorded):
        _require(value["order_submission_enabled"] is False and value["current_attention_published"] is False)
    _require(closeout["execution_authority_changed"] is False
             and closeout["oracle_council_integrated"] is False
             and declaration["oracle_council_integrated"] is False
             and declaration["no_winner_selection"] is True
             and closeout["new_calibration_experiments"] is False)
    hashes = closeout["unchanged_v2_artifact_hashes"]
    for name in ("development-declaration.json", "prospective-protocol.json"):
        _require(hashes[name] == SOURCE_PINS[name])
    _require(summary["cache_sha256"] == hashes["development-cache-seed-1.json"] == UPSTREAM_PINS["cache"]
             and summary["results_sha256"] == hashes["development-results-seed-1.json"] == UPSTREAM_PINS["results"])
    _require(declaration["reference_manifest_id"] == science["reference_manifest_id"]
             and declaration["primary_arm"] == summary["primary_arm"] == science["primary_arm"] == ARMS[1])
    _require(declaration["arms"] == list(ARMS) and declaration["windows"] == science["windows"] == [20, 60]
             and set(summary["windows"]) == {"20", "60"}
             and set(summary["cross_window_comparisons"]) == set(ARMS))
    cohort = declaration["symbols"]
    _require(isinstance(cohort, list) and 1 <= len(cohort) <= 100
             and all(isinstance(s, str) and re.fullmatch(r"[A-Z][A-Z0-9.-]{0,14}", s) for s in cohort)
             and cohort == sorted(set(cohort)) and cohort == science["cohort"])
    _require(declaration["mean_new_names_limit"] == science["mean_new_names_limit"] == 2
             and declaration["minimum_mean_jaccard"] == science["minimum_mean_jaccard"] == [2, 3]
             and declaration["capacity"] == 6 and declaration["per_profile_capacity"] == 4)
    spec_by_arm = {spec["arm"]: spec for spec in science["policies"]}
    _require(len(spec_by_arm) == len(science["policies"]) == 3 and set(spec_by_arm) == set(ARMS))
    sessions, policies = set(), []
    for arm in ARMS:
        spec, comparison = spec_by_arm[arm], summary["cross_window_comparisons"][arm]
        _require(spec["research_only"] is True and spec["order_submission_enabled"] is False
                 and spec["capacity"] == declaration["capacity"]
                 and spec["minimum_percentile"] == declaration["minimum_percentile"] == .95
                 and spec["per_profile_capacity"] == [["ETF", 4], ["GENERAL_EQUITY", 4]])
        values = []
        for window in (20, 60):
            _require(set(summary["windows"][str(window)]) == set(ARMS))
            row = summary["windows"][str(window)][arm]
            count = _integer(row["sessions"], 1, 1000); sessions.add(count)
            tops = row["top_symbols"]
            _require(isinstance(tops, list) and len(tops) <= 6)
            contributors = [{"symbol": symbol, "selected_sessions": _integer(n, 0, count)} for symbol, n in tops]
            _require(len({v["symbol"] for v in contributors}) == len(contributors)
                     and all(v["symbol"] in cohort for v in contributors))
            values.append({"lookback": window, "mean_new_names_per_day": _ratio(row["mean_new_names_per_day"], maximum=6),
                "new_names_total": _integer(row["new_names_total"]), "sessions": count,
                "mean_selected": _ratio(row["selected_mean"], maximum=6),
                "eligible_coverage": _ratio(row["coverage_of_natural_pool"], maximum=1), "top_symbols": contributors})
        _require(comparison["sessions"] in sessions
                 and all(type(comparison[k]) is bool for k in ("mean_jaccard_ge_2_over_3",
                    "workload_both_windows_mean_new_names_le_2", "admission_limit_workload_pass_by_construction")))
        policies.append({"arm": arm, "role": spec["role"], "windows": values,
            "mean_overlap": _ratio(comparison["all_session_mean_jaccard"], maximum=1),
            "meets_overlap": comparison["mean_jaccard_ge_2_over_3"],
            "meets_churn": comparison["workload_both_windows_mean_new_names_le_2"],
            "capped_by_construction": comparison["admission_limit_workload_pass_by_construction"]})
    _require(len(sessions) == 1 and not any(p["meets_overlap"] and p["meets_churn"] for p in policies))
    archive_at = parse_rfc3339(closeout["verified_at"], "archive timestamp")
    _require(archive_at <= checked_at and recorded["checked_at"] == _stamp(archive_at))
    outcomes = warmup["symbol_outcomes"]
    _require(set(outcomes) == {"READY", "CAPTURE_FAILED", "BLOCKED_CAPTURE_FAILURE"}
             and sum(_integer(n, 0, len(cohort)) for n in outcomes.values()) == len(cohort)
             and warmup["complete_cohort_sealed"] is False and warmup["failure_evidence_sealed"] is True
             and recorded["warmup_sealed"] is False
             and recorded["prospective_status"] == "BLOCKED_MISSING_REQUIRED_EVIDENCE")
    progress = recorded["session_progress"]
    dates = [_day(s["session_date"]) for s in science["evaluation_sessions"]]
    _require(dates == sorted(set(dates)) and len(dates) == science["required_sessions"] == progress["required"]
             and _integer(progress["verified_canonical"]) == warmup["prospective_sessions_scored"] == 0
             and len(science["bridge_sessions"]) == 1)
    failures = [f for f in recorded["failures"] if f["status"] == "CAPTURE_FAILED"]
    _require(len(failures) == outcomes["CAPTURE_FAILED"] == 1 and failures[0]["symbol"] in cohort
             and failures[0]["reason"] == "OHLCV_CONFLICT_RETAINED")
    conflict = warmup["conflict"]
    _require(conflict["kind"] == "HISTORICAL_OVERLAP_CONFLICT" and "volume" in conflict["fields"]
             and conflict["session"] == conflict["existing"]["date"] == conflict["incoming"]["date"])
    first, last = (parse_rfc3339(warmup[k], "capture timestamp") for k in ("first_retrieved_at", "last_retrieved_at"))
    _require(first <= last <= archive_at and type(closeout["scheduler_loaded"]) is bool)
    blockers = recorded["future_calendar_blockers"]
    _require(isinstance(blockers, list) and all(d in dates for d in blockers))
    return {
        "study": {"development_id": summary["development_id"], "scope": summary["scope"],
            "training_period": {"start": _day(declaration["training_reference_start"]), "end": _day(declaration["training_reference_end"])},
            "development_period": {"start": _day(declaration["development_start"]), "end": _day(declaration["development_end"])},
            "session_count": next(iter(sessions)), "cohort": cohort, "windows": science["windows"],
            "primary_arm": summary["primary_arm"],
            "profile_statuses": {"GENERAL_EQUITY": protocol["status"], "ETF": protocol["status"]},
            "criteria": {"mean_new_names_limit": declaration["mean_new_names_limit"],
                "minimum_mean_jaccard": declaration["minimum_mean_jaccard"][0] / declaration["minimum_mean_jaccard"][1],
                "capacity": declaration["capacity"], "per_profile_capacity": declaration["per_profile_capacity"]},
            "all_policies_failed": not any(p["meets_churn"] and p["meets_overlap"] for p in policies), "policies": policies},
        "prospective": {"manifest_id": protocol["manifest_id"], "period": {"start": dates[0], "end": dates[-1]},
            "planned_sessions": progress["required"], "completed_sessions": progress["verified_canonical"],
            "status": recorded["prospective_status"],
            "warmup": {"session": _day(science["bridge_sessions"][0]["session_date"]), "status": warmup["status"],
                "expected_symbols": len(cohort), "ready_symbols": outcomes["READY"],
                "failed_symbols": outcomes["CAPTURE_FAILED"], "blocked_symbols": outcomes["BLOCKED_CAPTURE_FAILURE"],
                "complete_cohort_sealed": warmup["complete_cohort_sealed"],
                "failure_evidence_sealed": warmup["failure_evidence_sealed"], "provider_requests": _integer(warmup["provider_requests"], 0, len(cohort)),
                "conflict": {"symbol": failures[0]["symbol"], "session": conflict["session"], "fields": conflict["fields"],
                    "prior_volume": conflict["existing"]["volume"], "incoming_volume": conflict["incoming"]["volume"]},
                "first_captured_at": _stamp(first), "last_captured_at": _stamp(last)},
            "calendar_blocker_dates": blockers, "scheduler_loaded_at_archive": closeout["scheduler_loaded"]},
        "archive_as_of": _stamp(archive_at),
    }


class SentryResearchReader:
    """Fixed source paths; mutation or missing evidence yields no fallback data."""

    def __init__(self, research_root: Path | None = None, closeout_root: Path | None = None):
        if (research_root is None) != (closeout_root is None):
            raise ValueError("Sentry research and closeout roots must be configured together.")
        for root in (research_root, closeout_root):
            if root is not None and (".." in Path(root).parts or any(ord(c) < 32 for c in str(root))):
                raise ValueError("Sentry research roots must be normalized paths.")
        self.research_root = None if research_root is None else Path(research_root)
        self.closeout_root = None if closeout_root is None else Path(closeout_root)
        self._lock = threading.Lock()

    def current(self) -> dict:
        with self._lock:
            checked_at = datetime.now(timezone.utc)
            result = {"schema_version": SCHEMA_VERSION, "checked_at": _stamp(checked_at),
                "source": None, "study": None, "prospective": None, "limitations": list(LIMITATIONS),
                "observation_only": True, "order_submission_enabled": False, "current_attention_published": False}
            if self.research_root is None:
                return {**result, "status": "NOT_CONFIGURED", "message": "No frozen Sentry research checkpoint is configured. No study or scan is running."}
            try:
                documents, files = {}, []
                for name, expected in SOURCE_PINS.items():
                    root = self.closeout_root if name == "failed-warmup-integrity.json" else self.research_root
                    raw = _read_regular(root / name, MAX_SOURCE_BYTES)
                    actual = hashlib.sha256(raw).hexdigest()
                    _require(actual == expected)
                    documents[name] = parse_strict_json_object_bytes(raw, document_name="Sentry research artifact")
                    files.append({"file_name": name, "sha256": actual, "byte_size": len(raw)})
                projected = _project(documents, checked_at=checked_at)
                archive_at = projected.pop("archive_as_of")
                result = {**result, **projected, "status": "READY",
                    "message": "Frozen Calibration V2 research findings; historical development and blocked prospective evidence, not live market state.",
                    "source": {"label": "Sentry Calibration V2 archived research", "kind": "FIXED_RESEARCH_CHECKPOINT",
                        "archive_as_of": archive_at, "files": files,
                        "declared_upstream_hashes": dict(UPSTREAM_PINS), "upstream_artifacts_reverified": False}}
                _safe_json_tree(result)
                _require(len(canonical_json_bytes(result)) <= MAX_FEED_BYTES)
                return result
            except (OSError, ValueError, TypeError, KeyError, OverflowError, RecursionError):
                return {**result, "source": None, "study": None, "prospective": None, "status": "UNAVAILABLE",
                    "message": "The configured frozen Sentry research checkpoint is missing, changing, or failed validation. No substitute research results are shown."}
