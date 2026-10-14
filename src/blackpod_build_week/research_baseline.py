"""Read-only research coverage and measurement inventory over retained history.

This is a report consumer, not a new evaluator. It neither scores unseen data
nor turns an operator's cohort declaration into authenticated provenance.
"""
from __future__ import annotations

from collections import Counter
from copy import deepcopy
from pathlib import Path

from .contracts.decision_journal import JournalEvent
from .contracts.mission_request import normalize_rfc3339, parse_rfc3339
from .hashing import canonical_json_bytes, sha256_bytes
from .sentry_history_cache import read_regular

VERSION = "blackpod.research_baseline.v1"
METHOD = "blackpod.retained_research_baseline.v1"
COHORTS = frozenset({"RECORDED_HISTORICAL_HYPOTHESES", "RECONSTRUCTED_HISTORICAL_RESEARCH",
                    "PROSPECTIVE_SHADOW_RESEARCH", "SYNTHETIC_FIXTURE_ONLY"})
TRADING_EVALUATIONS = frozenset({"TRADING_RESEARCH_EVALUATION_RECORDED",
    "TRADING_SHADOW_EVALUATION_RECORDED", "TRADING_REVIEWED_SHADOW_EVALUATION_RECORDED"})
AUTHORITY = {key: False for key in ("authorization_enabled", "capital_activation_enabled",
                                   "execution_enabled", "policy_changes_enabled")}
UNAVAILABLE_METRICS = {
    "directional_accuracy": "NO_PAIRED_PREOUTCOME_DIRECTION_LABELS_AND_REALIZED_OUTCOMES",
    "precision": "NO_PREDECLARED_BINARY_LABEL_AND_POSITIVE_CLASS",
    "recall": "NO_PREDECLARED_BINARY_LABEL_AND_POSITIVE_CLASS",
    "false_positive_rate": "NO_PREDECLARED_BINARY_LABEL_AND_POSITIVE_CLASS",
    "forecast_error": "FORECAST_INTAKE_V1_HAS_NO_LINKED_REALIZED_OUTCOME_CONTRACT",
    "calibration": "QUANTILE_LABELS_NOT_CALIBRATED_PROBABILITIES_NO_LINKED_OUTCOMES",
    "performance_by_regime": "NO_PREDECLARED_POINT_IN_TIME_REGIME_LABELS",
    "predictive_effectiveness": "NO_AUTHENTICATED_INDEPENDENT_PROSPECTIVE_EFFECTIVENESS_SAMPLE",
}


def _time(value):
    return parse_rfc3339(value, "baseline timestamp")


def _counts(items):
    return dict(sorted(Counter(items).items()))


def _implementation_references():
    root = Path(__file__).resolve().parent
    paths = ("research_baseline.py", "research_baseline_cli.py", "research_acceptance_state.py",
             "contracts/research_acceptance_state.py")
    references = []
    for path in paths:
        raw = read_regular(root / path, max_bytes=256 * 1024)
        references.append({"path": "research-baseline/implementation/" + path,
                           "sha256": sha256_bytes(raw), "size_bytes": len(raw)})
    return references


def _unique_events(events):
    unique, duplicates = {}, 0
    for source in events:
        event = JournalEvent.from_mapping(source.to_dict())
        prior = unique.get(event.event_id)
        if prior is not None:
            if prior.to_bytes() != event.to_bytes():
                raise ValueError("baseline event identity binds conflicting bytes")
            duplicates += 1
        else:
            unique[event.event_id] = event
    return tuple(unique.values()), duplicates


def _hypotheses(events):
    rows = []
    for event in events:
        if event.event_type == "TRADING_HYPOTHESIS_CATALOG_RECORDED":
            documents = event.payload["catalog"]["hypotheses"]
        elif event.event_type == "INVESTMENT_HYPOTHESIS_RECORDED":
            documents = [event.payload]
        else:
            continue
        for document in documents:
            if event.domain == "TRADING":
                hypothesis, scope = document["mechanism"]["statement"], None
                preregistration = document["preregistration_claim"]
            else:
                hypothesis, scope = document["hypothesis"]["statement"], document["scope"]
                preregistration = document["research_mode"]
            rows.append({"domain": event.domain, "hypothesis_id": document["hypothesis_id"],
                "source_event_id": event.event_id, "created_at": document["recorded_at"],
                "document_sha256": sha256_bytes(canonical_json_bytes(document)),
                "hypothesis": hypothesis, "scope": deepcopy(scope),
                "horizon": deepcopy(document["horizon"]),
                "native_provenance_claim": preregistration,
                "evidence": deepcopy(list(event.evidence))})
    return rows


def _datasets(events, blobs):
    from .contracts.trading_research import TradingResearchDataset
    rows = []
    for event in events:
        if event.event_type != "TRADING_RESEARCH_PLAN_REGISTERED":
            continue
        plan = event.payload["plan"]
        reference = plan["dataset_evidence"]
        raw = blobs.get(reference["sha256"])
        if (not isinstance(raw, bytes) or len(raw) != reference["size_bytes"]
                or sha256_bytes(raw) != reference["sha256"]):
            raise ValueError("baseline dataset evidence must match its exact retained hash and size")
        dataset = TradingResearchDataset.from_bytes(raw).to_dict()
        rows.append({"plan_event_id": event.event_id, "dataset_evidence": deepcopy(reference),
            "dataset_id": dataset["dataset_id"], "source_kind": dataset["provenance"]["source_kind"],
            "timestamp_policy": dataset["provenance"]["timestamp_policy"],
            "recorded_at": dataset["recorded_at"], "universe": deepcopy(dataset["universe"]),
            "session_count": len(dataset["sessions"]),
            "first_session_close_at": dataset["sessions"][0]["close_at"],
            "last_session_close_at": dataset["sessions"][-1]["close_at"],
            "hypothesis_sha256": plan.get("frozen_hypothesis_evidence", {}).get("sha256")})
    return rows


def _native_evaluations(events):
    rows = []
    for event in events:
        if event.event_type in TRADING_EVALUATIONS:
            result = event.payload["result"]
            calculation = result.get("calculation_result", result)
            status = calculation.get("status", result.get("evaluation_purpose"))
            measured = status == "SHADOW_SIMULATED"
            measurements = []
            native_fold_statuses = []
            if calculation.get("schema_version") == "blackpod.trading_research_evaluation.v1":
                # Original strategy-neutral evaluator v1 has only per-fold
                # statuses, not v15's stress-run envelope. Keep its CASH
                # comparison and actual descriptive arithmetic visible.
                for fold in calculation["folds"]:
                    native_fold_statuses.append({"fold_id": fold["fold_id"], "status": fold["status"]})
                    if fold["status"] == "SIMULATED" and fold["metrics"] is not None:
                        measured = True
                        measurements.append({"fold_id": fold["fold_id"],
                            "kind": "NATIVE_SIMULATED_CANDIDATE_METRICS",
                            "metrics": deepcopy(fold["metrics"]),
                            "benchmark": deepcopy(fold["benchmark"])})
            for run in calculation.get("cost_stress_runs", []):
                for fold in run.get("folds", []):
                    measurements.append({"cost_multiplier": run["multiplier"],
                        "fold_id": fold["fold_id"], "kind": "NATIVE_DESCRIPTIVE_COMPARISON",
                        "comparison": deepcopy(fold["comparison"])})
                if run.get("candidate") is not None:
                    for fold in run["candidate"]["folds"]:
                        measurements.append({"cost_multiplier": run["multiplier"],
                            "fold_id": fold["fold_id"], "kind": "NATIVE_SIMULATED_CANDIDATE_METRICS",
                            "metrics": deepcopy(fold["metrics"])})
            rows.append({"domain": event.domain, "event_id": event.event_id,
                "event_type": event.event_type, "recorded_at": event.recorded_at,
                "native_status": status, "measurement_performed": measured,
                "native_fold_statuses": native_fold_statuses,
                "method_version": calculation.get("method_version"),
                "final_holdout": deepcopy(calculation.get("final_holdout")),
                "measurements": measurements, "realized_trade_pnl": None,
                "interpretation": "SIMULATED_ARITHMETIC_NOT_OBSERVED_TRADE_OR_VALIDATED_ALPHA"})
        elif event.event_type == "INVESTMENT_OUTCOME_EVALUATION_RECORDED":
            result = event.payload["result"]
            checks = result["check_results"]
            measured = any(check["observed_value"] is not None for check in checks)
            rows.append({"domain": event.domain, "event_id": event.event_id,
                "event_type": event.event_type, "recorded_at": event.recorded_at,
                "native_status": result["comparison_summary"],
                "measurement_performed": measured,
                "method_version": result["comparison_method_version"],
                "check_results": deepcopy(checks), "realized_trade_pnl": None,
                "interpretation": "RECORDED_DEADLINE_POINTS_NOT_WHOLE_HORIZON_ECONOMIC_TRUTH"})
    return rows


def _forecast_inventory(events, as_of):
    rows = []
    for event in events:
        if event.event_type != "FORECAST_INTAKE_RECORDED":
            continue
        for row in event.payload["result"]["rows"]:
            # The current source contract forbids outcomes/evaluations. Do not
            # guess them from a later price series or compute a future target.
            if row["realized_outcome"] is not None or row["evaluation"] is not None:
                raise ValueError("baseline does not support an unversioned forecast outcome")
            rows.append({"source_event_id": event.event_id, "row_id": row["row_id"],
                "intake_id": event.payload["intake"]["intake_id"],
                "domain": event.domain, "symbol": row["symbol"],
                "model_id": row["model_id"], "model_version": row["model_version"],
                "issued_at": row["issued_at"], "target_at": row["target_at"],
                "reference_price": row["reference_price"], "reference_at": row["reference_at"],
                "predicted_close_q50": row["q50"], "units": row["units"],
                "horizon_count": row["horizon_count"], "horizon_unit": row["horizon_unit"],
                "native_gate": row["gate"], "reason_codes": deepcopy(row["reason_codes"]),
                "target_elapsed_at_report_clock": None if row["target_at"] is None else _time(row["target_at"]) <= as_of,
                "outcome_available": False, "evaluation_available": False,
                "source_evidence": deepcopy(row["source_evidence"])})
    return rows


def _diagnostics(events):
    rows = []
    for event in events:
        result = event.payload.get("result")
        if (not isinstance(result, dict) or event.event_type in TRADING_EVALUATIONS
                or not any(word in event.event_type for word in ("QUALIFICATION", "CLOSURE_REVIEW", "RECONCILIATION", "RECONCILED_ACTION_INTAKE"))):
            continue
        rows.append({"event_id": event.event_id, "event_type": event.event_type,
            "recorded_at": event.recorded_at, "native_status": result.get("status"),
            "reason_codes": deepcopy(result.get("reason_codes", [])),
            "counts": deepcopy(result.get("counts")),
            "eligible_for_shadow_study": result.get("eligible_for_shadow_study"),
            "coverage_complete": result.get("coverage_complete"),
            "returns_computed": result.get("returns_computed"),
            "interpretation": "EVIDENCE_DIAGNOSTIC_NOT_HYPOTHESIS_OUTCOME"})
    return rows


def build_baseline_report(events, blobs, *, cohort, as_of):
    """Deterministic report. The caller must separately verify history.

    CLI uses ``baseline_from_journal`` so the report follows full semantic
    replay. Calling this function establishes typed content identity and
    selected assessment replay only, never whole-journal verification. Bounded
    installed calculation source hashes are also explicit identity inputs;
    these source files are retained in Git, not a new journal storage layer.
    """
    if not isinstance(cohort, str) or cohort not in COHORTS:
        raise ValueError("baseline requires an explicit supported cohort declaration")
    as_of = normalize_rfc3339(as_of, "baseline as_of")
    clock = _time(as_of)
    events, duplicate_count = _unique_events(events)
    if any(_time(event.recorded_at) > clock for event in events):
        raise ValueError("baseline report clock must cover every selected journal record")
    datasets = _datasets(events, blobs)
    fixture = (any(event.payload.get("study", {}).get("evidence_scope") == "SYNTHETIC_FIXTURE_ONLY" for event in events)
               or any(row["source_kind"] == "SYNTHETIC_FIXTURE" for row in datasets))
    if fixture and cohort != "SYNTHETIC_FIXTURE_ONLY":
        raise ValueError("explicitly synthetic study cannot enter a real research cohort")
    hypotheses = _hypotheses(events)
    for row in hypotheses:
        if row["domain"] == "TRADING":
            sources = [dataset for dataset in datasets if dataset["hypothesis_sha256"] == row["document_sha256"]]
            symbols = sorted({symbol for dataset in sources for symbol in dataset["universe"]})
            row["scope"] = None if not symbols else {"kind": "SYMBOLS", "identifiers": symbols}
            row["scope_source_event_ids"] = sorted(dataset["plan_event_id"] for dataset in sources)
    if cohort == "RECORDED_HISTORICAL_HYPOTHESES" and any(
        row["native_provenance_claim"] in {"RETROSPECTIVE", "SPECIFICATION_FREEZE_ONLY_NOT_HISTORICAL_PREREGISTRATION"}
        for row in hypotheses):
        raise ValueError("retrospective reconstruction cannot be relabeled as historically recorded prediction")
    if cohort == "PROSPECTIVE_SHADOW_RESEARCH" and any(
            row["native_provenance_claim"] == "RETROSPECTIVE" for row in hypotheses):
        raise ValueError("explicit retrospective research cannot enter a prospective cohort")
    if cohort == "PROSPECTIVE_SHADOW_RESEARCH" and any(
            event.payload.get("study", {}).get("evidence_scope") == "RETAINED_HISTORY_RESEARCH"
            or (event.event_type == "TRADING_RESEARCH_PLAN_REGISTERED"
                and event.payload["plan"]["schema_version"] == "blackpod.trading_research_plan.v2")
            for event in events):
        raise ValueError("known reconstructed historical trading study cannot enter a prospective cohort")
    from .research_acceptance_state import project_assessment_state
    assessments, superseded = [], set()
    for event in events:
        if event.event_type != "RESEARCH_ASSESSMENT_RECORDED":
            continue
        request = event.payload["request"]
        state = project_assessment_state(event.event_id, events, blobs).to_dict()
        if request["supersedes_event_id"] is not None:
            superseded.add(request["supersedes_event_id"])
        assessments.append({"event_id": event.event_id, "domain": event.domain,
            "hypothesis_id": request["hypothesis"]["hypothesis_id"],
            "hypothesis_sha256": request["hypothesis"]["evidence"]["sha256"],
            "methodology_version": request["methodology_version"],
            "assessment_scope": request["assessment_scope"],
            "evaluation_event_id": request["evaluation_event_id"], "state": state})
    for row in assessments:
        row["superseded"] = row["event_id"] in superseded
    active = [row for row in assessments if not row["superseded"]]
    native = _native_evaluations(events)
    forecasts = _forecast_inventory(events, clock)
    domains = []
    for domain in ("TRADING", "INVESTMENT"):
        h = [row for row in hypotheses if row["domain"] == domain]
        a = [row for row in active if row["domain"] == domain]
        n = [row for row in native if row["domain"] == domain]
        measured = [row for row in n if row["measurement_performed"]]
        domains.append({"domain": domain, "hypothesis_revision_count": len(h),
            "active_assessment_count": len(a), "native_evaluation_record_count": len(n),
            "native_measured_evaluation_count": len(measured),
            "assessed_hypothesis_revision_count": len({(row["hypothesis_id"], row["hypothesis_sha256"]) for row in a}),
            "distinct_assessed_evaluation_count": len({row["evaluation_event_id"] for row in a if row["evaluation_event_id"] is not None}),
            "methodology_counts": _counts(row["methodology_version"] for row in a),
            "horizon_counts": _counts(canonical_json_bytes(row["horizon"]).decode("utf-8").strip() for row in h),
            "original_classification_counts": _counts(row["state"]["original_classification"] for row in a),
            "eligibility_counts": _counts(row["state"]["eligibility"] for row in a),
            "outcome_counts": _counts(row["state"]["outcome"] or "NOT_ASSESSED" for row in a),
            "derived_classification_counts": _counts(row["state"]["classification"] for row in a),
            "scope_evaluation_performed_count": sum(row["state"]["evaluation_performed"] for row in a),
            "scope_warning": "COUNTS_ARE_RESEARCH_RECORDS_NOT_INDEPENDENT_PREDICTIONS_OR_TRADES"})
    report = {"schema_version": VERSION, "method_version": METHOD, "as_of": as_of,
        "implementation_evidence": _implementation_references(),
        "cohort": {"declared": cohort, "authenticated": False,
            "historical_point_in_time_verified": False,
            "meaning": "EXPLICIT_OPERATOR_LABEL_NOT_INDEPENDENT_PROVENANCE_PROOF"},
        "verification": {"scope": "TYPED_EVENTS_AND_SELECTED_ASSESSMENT_REPLAY_ONLY",
            "event_count": len(events), "duplicate_input_event_count": duplicate_count,
            "retained_blob_count": len(blobs),
            "ordered_event_set_sha256": sha256_bytes(canonical_json_bytes([
                {"event_id": event.event_id, "sha256": sha256_bytes(event.to_bytes())} for event in events]))},
        "domains": domains, "hypotheses": hypotheses, "datasets": datasets, "assessments": assessments,
        "native_evaluations": native, "forecast_rows": forecasts,
        "forecast_coverage": {"row_count": len(forecasts), "outcome_count": 0, "evaluation_count": 0,
            "denominator_kind": "INTAKE_ROW_REVIEWS_NOT_INDEPENDENT_PREDICTIONS",
            "unique_raw_source_row_count": len({(row["row_id"], row["source_evidence"]["sha256"]) for row in forecasts}),
            "unique_domain_source_row_count": len({(row["domain"], row["row_id"], row["source_evidence"]["sha256"]) for row in forecasts}),
            "elapsed_target_count": sum(row["target_elapsed_at_report_clock"] is True for row in forecasts),
            "horizon_counts": _counts(str(row["horizon_count"]) + " " + str(row["horizon_unit"]) for row in forecasts)},
        "evidence_diagnostics": _diagnostics(events),
        "metrics": {name: {"value": None, "status": "UNAVAILABLE", "reason_code": reason}
                    for name, reason in UNAVAILABLE_METRICS.items()},
        "simple_baselines": {"cash_and_matched_controls": "PRESERVED_PER_NATIVE_FOLD_WHERE_MEASURED_NO_AGGREGATION",
            "no_change_forecast": "UNAVAILABLE_WITHOUT_LINKED_REALIZED_TARGETS",
            "persistence_forecast": "UNAVAILABLE_WITHOUT_LINKED_REALIZED_TARGETS_AND_PREDECLARED_METHOD"},
        "limitations": ["SELECTED_JOURNAL_ONLY_NOT_REPOSITORY_WIDE_DENOMINATOR",
            "COHORT_DECLARATION_NOT_AUTHENTICATED_OR_PROSPECTIVE_REGISTRATION_PROOF",
            "ASSESSMENTS_SCOPES_AND_REVISIONS_NOT_INDEPENDENT_OBSERVATIONS",
            "NO_CROSS_DOMAIN_PERFORMANCE_OR_SIMULATION_FOLD_AGGREGATION",
            "NO_REGIME_INFERENCE_OR_HOLDOUT_SCORING",
            "SYNTHETIC_COUNTS_AND_VALUES_ESTABLISH_SOFTWARE_BEHAVIOR_ONLY",
            "FROZEN_HISTORICAL_GATES_NOT_REINTERPRETED_BY_REPORT"],
        "governance_status": "RESEARCH_ONLY_NOT_AUTHORIZATION", "auto_trading_enabled": False,
        "authority": dict(AUTHORITY), "execution_status": "NOT_EXECUTED", "realized_trade_pnl": None}
    # A report contains exact record identities, not mutable directory names.
    report["report_id"] = "research-baseline-" + sha256_bytes(canonical_json_bytes(report))
    return report


def baseline_from_journal(journal_root, *, cohort, as_of):
    """Read-only full semantic scan followed by the deterministic report."""
    from .decision_journal_store import JournalStore
    events, blobs = JournalStore(journal_root).verified_contents()
    report = build_baseline_report(events, blobs, cohort=cohort, as_of=as_of)
    report["verification"]["scope"] = "FULL_JOURNAL_SEMANTIC_REPLAY"
    del report["report_id"]
    report["report_id"] = "research-baseline-" + sha256_bytes(canonical_json_bytes(report))
    return report
