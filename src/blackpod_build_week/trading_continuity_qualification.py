"""Pre-signal, event-aware qualification of frozen raw-price TEST windows.

This is a separate research qualification, never an override of the original
whole-dataset continuity gate. It neither repairs prices nor submits intents.
An action is a retrospective censoring boundary, not proof that the action was
known to a historical decision maker.
"""
from __future__ import annotations

from datetime import timedelta, timezone
from decimal import Context, Decimal, DivisionByZero, InvalidOperation, Overflow, ROUND_HALF_EVEN, localcontext

from .contracts.mission_request import parse_rfc3339
from .contracts.trading_continuity_intake import ContinuityIntakeExport
from .contracts.trading_hypothesis import TradingHypothesis
from .contracts.trading_research import TradingResearchDataset, TradingResearchPlan
from .contracts.trading_shadow_research import PriceContinuitySource, PriceContinuityEvidence
from .hashing import sha256_bytes
from .trading_hypotheses import hypothesis_research_strategy

METHOD_VERSION = "blackpod.event_aware_continuity_qualification.v1"
POLICY = "RAW_PRICE_BOUNDARY_SUSPENSION_NO_ADJUSTMENT"
MAX_ACTION_WINDOW_COMPARISONS = 2_000_000
LIMITATIONS = (
    "QUALIFIED_WINDOWS_NOT_TRADING_AUTHORITY_OR_LEGACY_GATE_OVERRIDE",
    "RETROSPECTIVE_ACTION_CENSORING_NOT_HISTORICAL_KNOWN_TIME_PROOF",
    "PROCESS_DATE_PAGINATION_NOT_EFFECTIVE_DATE_COVERAGE_PROOF",
    "INDEPENDENT_COVERAGE_REVIEW_IS_RETAINED_DECLARATION_NOT_PROVIDER_AUTHENTICATION",
    "RAW_PRICES_UNCHANGED_NO_SPLIT_DIVIDEND_OR_TOTAL_RETURN_REPAIR",
    "MASKS_ENUMERATED_BEFORE_SIGNAL_SELECTION_NO_RETURN_OR_PNL_FILTERING",
    "MATCHED_CONTROL_REQUIRES_EVERY_FIXED_UNIVERSE_CONSTITUENT_CONTINUITY",
    "FINAL_HOLDOUT_NOT_SCORED_AND_NOT_ACCESS_SEALED",
)


def _mapping(value):
    return value.to_dict() if hasattr(value, "to_dict") else dict(value)


def _document(value, kind):
    return value if isinstance(value, kind) else kind.from_mapping(_mapping(value))


def _time(value):
    return parse_rfc3339(value, "qualification session clock")


def _stamp(value):
    return value.astimezone(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _open_reasons(source_index, next_index, sessions, risk, role):
    if source_index < 0 or next_index >= len(sessions):
        return [role + "_RETURNED_CALENDAR_SESSION_UNAVAILABLE"]
    available = _time(sessions[source_index]["available_at"])
    decision = available + timedelta(microseconds=1)
    opened = _time(sessions[next_index]["open_at"])
    reasons = []
    if decision >= opened:
        reasons.append(role + "_OPEN_NOT_AFTER_SOURCE_AVAILABILITY")
    delta = opened - available
    with localcontext(Context(prec=256, rounding=ROUND_HALF_EVEN, flags=[],
                             traps=[DivisionByZero, InvalidOperation, Overflow])):
        age = Decimal(delta.days * 86400 + delta.seconds) + Decimal(delta.microseconds) / Decimal("1000000")
    if age > Decimal(risk["max_staleness_seconds"]):
        reasons.append(role + "_SOURCE_STALE_AT_OPEN")
    return reasons


def _continuity(material, plan, dataset, policy):
    if material is None:
        return None, [], ["CONTINUITY_SOURCE_MISSING"], False
    export = _document(material["export"], ContinuityIntakeExport)
    source = _document(material["source"], PriceContinuitySource)
    review = _document(material["review"], PriceContinuityEvidence)
    supplied = _document(material["dataset"], TradingResearchDataset)
    if supplied.to_bytes() != dataset.to_bytes():
        raise ValueError("continuity qualification must preserve the exact original dataset")
    if export.dataset_evidence != plan.dataset_evidence or source.dataset_evidence != plan.dataset_evidence or review.dataset_evidence != plan.dataset_evidence:
        raise ValueError("continuity qualification evidence belongs to another dataset")
    if export.evidence_scope != policy["evidence_scope"] or source.universe != dataset.universe or review.universe != dataset.universe:
        raise ValueError("continuity qualification scope or universe differs from the original research")
    ids = [session["session_id"] for session in dataset.sessions]
    if ((source.coverage_start_session_id, source.coverage_end_session_id) != (ids[0], ids[-1])
            or (review.coverage_start_session_id, review.coverage_end_session_id) != (ids[0], ids[-1])):
        raise ValueError("continuity qualification requires the original full session coverage span")
    if _time(export.recorded_at) > _time(policy["recorded_at"]):
        raise ValueError("qualification policy cannot precede its retained continuity declaration")
    for action in export.native_actions:
        if action["dataset_disposition"] == "IN_DATASET" and action["mapped_session_id"] not in ids:
            raise ValueError("native action mapping references an unknown returned session")
    reasons = []
    if export.status != "AVAILABLE" or not export.pagination_complete:
        reasons.append("CONTINUITY_CAPTURE_UNAVAILABLE_OR_INCOMPLETE")
    if not export.coverage_review_supported or not source.coverage_complete:
        reasons.append("INDEPENDENT_EFFECTIVE_DATE_COVERAGE_UNVERIFIED")
    supported = not reasons
    # review.status deliberately remains unchanged. Known action rows make the
    # original review UNRESOLVED even where an additive window is uncrossed.
    return review.status, export.native_actions, reasons, supported


def qualify_continuity_windows(policy, plan, dataset, hypothesis, continuity_material_or_none):
    """Enumerate every potential TEST window without reading price values.

    The caller first verifies the original native intake and journal bindings.
    Feature returns cross actions f < j <= s. The sizing/entry boundary is
    s < j <= e; held positions and exits cross e < j <= x. An action exactly at
    the oldest close anchor f has already occurred before all feature prices.
    Unknown dates censor all affected-symbol windows, not their old placeholder
    first-session event. Controls hold the entire original fixed universe.
    """
    policy = _mapping(policy)
    if policy["continuity_policy"] != POLICY:
        raise ValueError("unsupported raw-price continuity qualification policy")
    plan = _document(plan, TradingResearchPlan)
    dataset = _document(dataset, TradingResearchDataset)
    hypothesis = _document(hypothesis, TradingHypothesis)
    if plan.schema_version != "blackpod.trading_research_plan.v2" or dataset.schema_version != "blackpod.trading_research_dataset.v2":
        raise ValueError("continuity qualification requires frozen research v2 inputs")
    if plan.universe != dataset.universe:
        raise ValueError("continuity qualification cannot change the original universe")
    raw = dataset.to_bytes()
    if plan.dataset_evidence["sha256"] != sha256_bytes(raw) or plan.dataset_evidence["size_bytes"] != len(raw):
        raise ValueError("continuity qualification dataset is not the exact original reference")
    projected = hypothesis_research_strategy(hypothesis)
    if plan.strategy != projected["strategy"] or plan.horizon != projected["horizon"]:
        raise ValueError("continuity qualification cannot change the frozen hypothesis or horizon")
    raw = hypothesis.to_bytes()
    if plan.frozen_hypothesis_evidence["sha256"] != sha256_bytes(raw) or plan.frozen_hypothesis_evidence["size_bytes"] != len(raw):
        raise ValueError("continuity qualification hypothesis is not the exact original reference")
    sessions = dataset.sessions
    count = sum(fold["test"]["end_index"] - fold["test"]["start_index"] + 1 for fold in plan.protocol["folds"]) * len(plan.universe)
    if count > 10000:
        raise ValueError("continuity opportunities exceed the fixed research bound")
    if any(fold["test"]["end_index"] >= len(sessions) for fold in plan.protocol["folds"]) or plan.protocol["final_holdout"]["end_index"] >= len(sessions):
        raise ValueError("qualification partitions must bind actual returned sessions")
    review_status, audits, global_reasons, covered = _continuity(continuity_material_or_none, plan, dataset, policy)
    if count * len(audits) > MAX_ACTION_WINDOW_COMPARISONS:
        raise ValueError("continuity action-window workload exceeds the bounded qualification projection")
    index_by_id = {session["session_id"]: index for index, session in enumerate(sessions)}
    lookback = hypothesis.signal["lookback_sessions"]
    holding = hypothesis.horizon["holding_sessions"]
    opportunities = []
    for fold in plan.protocol["folds"]:
        for source_index in range(fold["test"]["start_index"] - 1, fold["test"]["end_index"]):
            source = sessions[source_index]
            feature, entry, exit_at = source_index - lookback, source_index + 1, source_index + 1 + holding
            clocks = []
            if feature < 0:
                clocks.append("INSUFFICIENT_COMPLETED_FEATURE_LOOKBACK")
            else:
                decision = _time(source["available_at"]) + timedelta(microseconds=1)
                if any(_time(sessions[index]["available_at"]) > decision for index in range(feature, source_index + 1)):
                    clocks.append("FEATURE_INPUT_NOT_AVAILABLE_AT_DECISION")
            clocks += _open_reasons(source_index, entry, sessions, plan.risk, "ENTRY")
            if exit_at > fold["test"]["end_index"]:
                clocks.append("DECLARED_EXIT_OUTSIDE_ORIGINAL_TEST")
            else:
                clocks += _open_reasons(exit_at - 1, exit_at, sessions, plan.risk, "EXIT")
            for symbol in plan.universe:
                candidate = {"FEATURE": [], "ENTRY": [], "HOLDING_EXIT": [], "UNKNOWN": []}
                benchmark = []
                for action in audits:
                    affected = set(action["affected_symbols"])
                    if action["dataset_disposition"] == "UNKNOWN_EFFECTIVE_DATE":
                        if symbol in affected:
                            candidate["UNKNOWN"].append(action["native_id"])
                        if affected & set(plan.universe):
                            benchmark.append(action["native_id"])
                        continue
                    if action["dataset_disposition"] != "IN_DATASET":
                        continue
                    boundary = index_by_id[action["mapped_session_id"]]
                    if symbol in affected:
                        role = ("FEATURE" if feature < boundary <= source_index
                                else "ENTRY" if source_index < boundary <= entry
                                else "HOLDING_EXIT" if entry < boundary <= exit_at else None)
                        if role is not None:
                            candidate[role].append(action["native_id"])
                    if affected & set(plan.universe) and source_index < boundary <= exit_at:
                        benchmark.append(action["native_id"])
                candidate = {role: sorted(set(values)) for role, values in candidate.items()}
                benchmark = sorted(set(benchmark))
                reasons = list(global_reasons) + clocks
                for role, identities in candidate.items():
                    if identities:
                        reasons.append("CANDIDATE_" + role + "_ACTION_BOUNDARY")
                if benchmark:
                    reasons.append("MATCHED_CONTROL_ACTION_BOUNDARY_OR_UNKNOWN_DATE")
                candidate_ok = not global_reasons and not clocks and not any(candidate.values())
                benchmark_ok = not global_reasons and not clocks and not benchmark
                combined = candidate_ok and benchmark_ok
                opportunities.append({"fold_id": fold["fold_id"], "symbol": symbol,
                    "source_session_index": source_index, "source_session_id": source["session_id"],
                    "feature_start_index": feature, "entry_session_index": entry, "exit_session_index": exit_at,
                    "decision_at": _stamp(_time(source["available_at"]) + timedelta(microseconds=1)),
                    "window_status": "ELIGIBLE_WINDOW_ONLY" if combined else "DEFER",
                    "candidate_eligible": candidate_ok, "benchmark_eligible": benchmark_ok, "combined_eligible": combined,
                    "reason_codes": sorted(set(reasons)), "candidate_action_ids": candidate,
                    "benchmark_action_ids": benchmark, "source_clock_reasons": sorted(set(clocks))})
    counts = {"opportunities": len(opportunities),
        "candidate_eligible": sum(row["candidate_eligible"] for row in opportunities),
        "benchmark_eligible": sum(row["benchmark_eligible"] for row in opportunities),
        "combined_eligible": sum(row["combined_eligible"] for row in opportunities),
        "deferred": sum(not row["combined_eligible"] for row in opportunities)}
    return {"method_version": METHOD_VERSION, "continuity_policy": POLICY,
        "status": "ELIGIBLE_WINDOWS_ONLY" if counts["combined_eligible"] else "DEFER",
        "reason_codes": sorted(set(global_reasons)), "coverage_supported": covered,
        "native_continuity_review_status": review_status, "opportunities": opportunities, "counts": counts,
        "native_action_audit": audits,
        "final_holdout": {**plan.protocol["final_holdout"], "scoring_status": "WITHHELD", "access_sealed": False},
        "price_policy": "RAW_UNMODIFIED_NO_REINDEX", "limitations": list(LIMITATIONS)}
