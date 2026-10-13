"""Versioned qualification of segmented TRAIN evidence and frozen v18 designs.

Old policies, gates, price histories and declarations remain immutable. Native
segments are replayed before their extrema are used; their raw corpus stays in
the original journal records. This consumer performs no return evaluation.
"""
from decimal import Context, Decimal, ROUND_CEILING, localcontext
from pathlib import Path

from .contracts.segmented_evidence_qualification import (
    SegmentedEvidenceBinding, SegmentedEvidenceQualificationRequest,
    BINDING_TYPE, ASSESSMENT_TYPE, CALIBRATION_SOURCE, RESULT_VERSION, METHOD_VERSION,
    validate_result,
)
from .contracts.trading_evidence_qualification import TradingTrainingAssumptions, POLICY_TYPE
from .contracts.train_market_evidence import PLAN_TYPE, SEGMENT_TYPE, EXPORT_TYPE
from .contracts.mission_request import parse_rfc3339
from .hashing import canonical_json_bytes, sha256_bytes
from .sentry_history_cache import read_regular
from .trading_research_journal import _blob
from .trading_evidence_qualification import policy_context, _risk, _protocol, CODE_PATHS as V18_CODE
from .trading_evidence_qualification_journal import validate_qualification_event
from .train_market_evidence import registered_capture_context, export_context, CODE_PATHS as V19_CODE
from .train_market_evidence_journal import validate_train_market_event
from .trading_shadow_review_journal import CODE_PATHS as V16_CODE
from .trading_research_evaluation import plan_chronological_splits

AUTHORITY = {name: False for name in ("authorization_enabled", "capital_activation_enabled", "execution_enabled", "policy_changes_enabled")}
CODE_PATHS = tuple(dict.fromkeys((
    "contracts/segmented_evidence_qualification.py", "segmented_evidence_qualification.py", "segmented_evidence_qualification_journal.py",
    *V18_CODE, *V19_CODE, *V16_CODE, "contracts/trading_research.py", "contracts/trading_hypothesis.py",
    "contracts/historical_intake.py", "trading_research_journal.py", "trading_research_intake_journal.py",
    "trading_shadow_review_journal.py", "trading_shadow_journal.py", "hashing.py",
)))


def implementation_evidence():
    root = Path(__file__).absolute().parent
    return {"segmented-qualification/implementation/" + path: read_regular(root / path) for path in CODE_PATHS}


def refs(evidence):
    return [{"path": path, "sha256": sha256_bytes(raw), "size_bytes": len(raw)} for path, raw in sorted(evidence.items())]


def merge(target, material):
    for path, raw in material.items():
        if not isinstance(raw, bytes) or (path in target and target[path] != raw):
            raise ValueError("segmented qualification evidence path conflicts")
        target[path] = raw
    if len(target) > 512 or sum(map(len, target.values())) > 64 * 1024 * 1024:
        raise ValueError("segmented qualification exceeds compact evidence bounds")


def _document(value, cls):
    return cls.from_mapping(value.to_dict() if hasattr(value, "to_dict") else value)


def _event(events, identity, types):
    selected = [event for event in events if event.event_id == identity and event.domain == "TRADING" and event.event_type in types]
    if len(selected) != 1: raise ValueError("segmented qualification requires unique preceding TRADING sources")
    return selected[0]


def _prefix(document, events, event_type, key):
    events = tuple(events)
    if len({event.event_id for event in events}) != len(events): raise ValueError("segmented history has ambiguous identities")
    matches = [event for event in events if event.event_type == event_type and event.source[key] == getattr(document, key)]
    if len(matches) > 1: raise ValueError("segmented identity is ambiguous")
    if matches:
        field = "binding" if event_type == BINDING_TYPE else "request"
        if matches[0].payload[field] != document.to_dict(): raise ValueError("segmented identity is immutable")
        events = events[:events.index(matches[0])]
    return events


def _compact(material, blobs):
    policy = material["policy"]
    evidence = {"segmented-qualification/original-policy.v1.json": policy.to_bytes(),
        "segmented-qualification/original-plan.v2.json": material["plan"].to_bytes(),
        "segmented-qualification/original-hypothesis.v1.json": material["hypothesis"].to_bytes()}
    support = list(policy.supporting_evidence)
    if policy.training_cost_assumptions_evidence is not None:
        support.append(policy.training_cost_assumptions_evidence)
        assumptions = TradingTrainingAssumptions.from_bytes(_blob(blobs, policy.training_cost_assumptions_evidence))
        support.extend(assumptions.origin_evidence)
    for reference in support:
        alias = "segmented-qualification/support/" + reference["sha256"] + ".raw"
        merge(evidence, {alias: _blob(blobs, reference)})
    merge(evidence, implementation_evidence())
    return evidence


def binding_context(binding, events, blobs):
    binding = _document(binding, SegmentedEvidenceBinding)
    events = _prefix(binding, events, BINDING_TYPE, "binding_id")
    policy_event = _event(events, binding.qualification_policy_event_id, {POLICY_TYPE})
    capture_event = _event(events, binding.capture_plan_event_id, {PLAN_TYPE})
    validate_qualification_event(policy_event, events[:events.index(policy_event)], blobs)
    policy_material = policy_context(policy_event.payload["policy"], events[:events.index(policy_event)], blobs)
    validate_train_market_event(capture_event, events[:events.index(capture_event)], blobs)
    capture_material = registered_capture_context(capture_event.event_id, events, blobs)
    policy, plan = policy_material["policy"], policy_material["plan"]
    capture = capture_material["plan"]
    if (capture.base_plan_event_id != policy.base_plan_event_id or capture.base_plan_evidence != policy.base_plan_evidence
            or capture.dataset_evidence != policy.dataset_evidence or capture.evidence_scope != policy.evidence_scope
            or capture_material["base_plan"].to_bytes() != plan.to_bytes()
            or capture_material["dataset"].to_bytes() != policy_material["dataset"].to_bytes()
            or sorted(capture.fold_ids) != sorted(fold["fold_id"] for fold in plan.protocol["folds"])):
        raise ValueError("segmented binding must preserve the exact original plan, hypothesis, dataset, scope and full TRAIN folds")
    if any(parse_rfc3339(event.recorded_at, "source clock") > parse_rfc3339(binding.recorded_at, "binding clock") for event in (policy_event, capture_event)):
        raise ValueError("segmented binding cannot precede its selected frozen designs")
    peers = [event for event in events if event.event_type == BINDING_TYPE and event.payload["links"]["base_plan_event_id"] == policy.base_plan_event_id]
    if any(parse_rfc3339(event.recorded_at, "prior binding") > parse_rfc3339(binding.recorded_at, "binding clock") for event in peers):
        raise ValueError("segmented binding cannot backdate preceding same-plan history")
    if binding.supersedes_binding_event_id is not None:
        previous = next((event for event in peers if event.event_id == binding.supersedes_binding_event_id), None)
        if previous is None or any(event.payload["binding"]["supersedes_binding_event_id"] == previous.event_id for event in peers):
            raise ValueError("segmented binding supersession requires an unsuperseded same-plan binding")
        old = _document(previous.payload["binding"], SegmentedEvidenceBinding)
        old_policy = _event(events, old.qualification_policy_event_id, {POLICY_TYPE}).payload["policy"]
        if old_policy["hypothesis_evidence"] != policy.hypothesis_evidence or old_policy["evidence_scope"] != policy.evidence_scope:
            raise ValueError("segmented binding supersession cannot change hypothesis revision or evidence scope")
    links = {"qualification_policy_event_id": policy_event.event_id, "capture_plan_event_id": capture_event.event_id, **policy_material["links"]}
    evidence = _compact(policy_material, blobs)
    merge(evidence, {"segmented-qualification/binding.v1.json": binding.to_bytes()})
    return {"binding": binding, "policy_event": policy_event, "capture_plan_event": capture_event,
        "policy_material": policy_material, "capture_material": capture_material, "plan": plan,
        "dataset": policy_material["dataset"], "hypothesis": policy_material["hypothesis"],
        "parent": policy_material["parent"], "events": events, "links": links, "evidence": evidence}


def _text(number):
    value = format(number, "f")
    return value.rstrip("0").rstrip(".") if "." in value else value


def _calibrate(material, export, selected, export_event, blobs):
    policy, plan, dataset = material["policy"], material["plan"], material["dataset"]
    assumptions = None
    global_reasons = []
    reference = policy.training_cost_assumptions_evidence
    if reference is None: global_reasons.append("TRAINING_COST_AND_CAPACITY_ASSUMPTIONS_MISSING")
    else:
        assumptions = TradingTrainingAssumptions.from_bytes(_blob(blobs, reference))
        if assumptions.status != "REVIEWED_FOR_SHADOW_QUALIFICATION": global_reasons.append("TRAINING_ASSUMPTIONS_NOT_REVIEWED")
        if assumptions.parameters is None: global_reasons.append("TRAINING_COST_PARAMETERS_MISSING")
        if assumptions.capacity is None: global_reasons.append("TRAINING_CAPACITY_ASSUMPTION_MISSING")
    by_fold = {fold["fold_id"]: fold for fold in export["folds"]}
    splits = plan_chronological_splits(plan, dataset)
    fold_rows = []
    for fold in plan.protocol["folds"]:
        native = by_fold[fold["fold_id"]]
        reasons = list(global_reasons)
        if any(item["fold_id"] == fold["fold_id"] for item in splits["availability_failures"]):
            reasons.append("TRAINING_CHRONOLOGICAL_AVAILABILITY_INVALID")
        if not native["capture_complete"]: reasons.append("TRAIN_SEGMENT_CAPTURE_INCOMPLETE")
        if not native["coverage_complete"]: reasons.append("TRAIN_SYMBOL_SESSION_COVERAGE_INCOMPLETE")
        profile = native["training_spread_profile"]
        capacities = []
        reviewed = assumptions is not None and assumptions.status == "REVIEWED_FOR_SHADOW_QUALIFICATION"
        fraction = assumptions.capacity["max_daily_volume_participation_fraction"] if reviewed and assumptions.capacity is not None else None
        for symbol in dataset.universe:
            volumes = [Decimal(next(bar["volume"] for bar in dataset.sessions[index]["bars"] if bar["symbol"] == symbol))
                       for index in range(fold["train"]["start_index"], fold["train"]["end_index"] + 1)]
            with localcontext(Context(prec=256, rounding=ROUND_CEILING)):
                quantity = None if fraction is None else min(volumes) * Decimal(fraction)
            if quantity is not None and quantity <= 0: reasons.append("ZERO_DAILY_VOLUME_RESEARCH_PROXY")
            capacities.append({"symbol": symbol, "minimum_training_daily_volume": _text(min(volumes)),
                "maximum_training_daily_volume": _text(max(volumes)), "reviewed_daily_volume_participation_fraction": fraction,
                "daily_quantity_research_proxy": None if quantity is None else _text(quantity),
                "semantics": "RAW_DAILY_VOLUME_RESEARCH_PROXY_NOT_OPENING_FILL_CAPACITY"})
        model, stresses = None, []
        if profile is not None and reviewed and assumptions.parameters is not None:
            model = {"spread_bps": _text(max(Decimal(item["max_spread_bps"]) for item in profile)), **assumptions.parameters}
            with localcontext(Context(prec=256, rounding=ROUND_CEILING)):
                if Decimal(model["spread_bps"]) + Decimal(model["slippage_bps"]) <= 0: reasons.append("TRAINING_ZERO_PRICE_FRICTION_NOT_SUPPORTED")
                for multiplier in ("1", "2", "4"):
                    stressed = {key: _text(Decimal(value) * Decimal(multiplier)) for key, value in model.items()}
                    exceeded = sorted(key for key in ("spread_bps", "slippage_bps", "fee_bps") if Decimal(stressed[key]) > Decimal("1000"))
                    stresses.append({"multiplier": multiplier, "declared_cost_model": stressed, "within_existing_component_bounds": not exceeded, "exceeded_components": exceeded})
                    if exceeded: reasons.append("TRAINING_COST_STRESS_EXCEEDS_EXISTING_MODEL_BOUND")
        reasons = sorted(set(reasons))
        sources = [event for event in selected if event.payload["result"]["fold_id"] == fold["fold_id"]]
        fold_rows.append({"fold_id": fold["fold_id"], "training_range": dict(fold["train"]), "train_cutoff_at": dataset.sessions[fold["train"]["end_index"]]["available_at"],
            "eligible": not reasons, "status": "READY_FOR_SHADOW_QUALIFICATION" if not reasons else "DEFER_TRAINING_EVIDENCE",
            "reason_codes": reasons, "capture_complete": native["capture_complete"], "coverage_complete": native["coverage_complete"],
            "source_segment_ids": [event.source["segment_id"] for event in sources],
            "source_segment_event_ids": [event.event_id for event in sources],
            "training_measurements": profile, "missing_symbol_sessions": native["missing_symbol_sessions"],
            "cost_model": model if not reasons else None, "cost_stress_assessment": stresses, "capacity_proxy": capacities,
            "cost_applicability_verified": False, "opening_execution_capacity_verified": False})
    reasons = sorted({reason for fold in fold_rows for reason in fold["reason_codes"]})
    return {"schema_version": "blackpod.segmented_training_calibration.v1", "method_version": "blackpod.segmented_train_quote_calibration.v1",
        "calibration_source": CALIBRATION_SOURCE, "eligible": not reasons,
        "status": "READY_FOR_SHADOW_QUALIFICATION" if not reasons else "DEFER_TRAINING_EVIDENCE", "reason_codes": reasons,
        "evidence_scope": policy.evidence_scope, "folds": fold_rows, "aggregate_export_event_id": export_event.event_id,
        "source_segment_event_ids": sorted(event.event_id for event in selected), "assumption_review_evidence": reference,
        "sampling_policy": "ALL_VERIFIED_SEGMENTED_TRAIN_EXTREMA_NO_CLIPPING_OR_DOWNSAMPLING",
        "coverage_requirement": "EVERY_ORIGINAL_TRAIN_SYMBOL_SESSION_MUST_HAVE_ADMITTED_NATIVE_QUOTES",
        "historical_point_in_time_verified": False, "source_authentication_verified": False,
        "cost_applicability_verified": False, "opening_execution_capacity_verified": False,
        "holdout_scored": False, "strategy_tuning_performed": False, "auto_trading_enabled": False, "authority": AUTHORITY,
        "limitations": ["REVIEWED_ASSUMPTIONS_NOT_MEASURED_SLIPPAGE_FEES_OR_CAPACITY", "MAX_TRAIN_SAMPLE_SPREAD_NOT_FUTURE_COST_GUARANTEE", "DAILY_VOLUME_PROXY_NOT_OPENING_FILL_CAPACITY", "RETROSPECTIVE_SOURCE_NOT_POINT_IN_TIME_PROOF"]}


def qualify_segmented_evidence(request, events, blobs):
    request = _document(request, SegmentedEvidenceQualificationRequest)
    events = _prefix(request, events, ASSESSMENT_TYPE, "qualification_id")
    binding_event = _event(events, request.binding_event_id, {BINDING_TYPE})
    before = events[:events.index(binding_event)]
    context = binding_context(binding_event.payload["binding"], before, blobs)
    if binding_event.payload["links"] != context["links"] or binding_event.payload["implementation_evidence"] != refs(implementation_evidence()):
        raise ValueError("segmented binding links or installed methodology changed")
    binding, material = context["binding"], context["policy_material"]
    export_event = _event(events, request.aggregate_export_event_id, {EXPORT_TYPE})
    if export_event.payload["request"]["capture_plan_event_id"] != binding.capture_plan_event_id:
        raise ValueError("segmented assessment export belongs to another frozen capture plan")
    prefix = events[:events.index(export_event)]
    selected = [_event(prefix, identity, {SEGMENT_TYPE}) for identity in export_event.payload["request"]["segment_event_ids"]]
    for event in selected:
        validate_train_market_event(event, prefix[:prefix.index(event)], blobs)
    validate_train_market_event(export_event, prefix, blobs)
    export_material = export_context(export_event.payload["request"], prefix, blobs)
    export = export_material["result"]
    policy = material["policy"]
    native_id = export_event.payload["request"]["continuity_event_id"]
    if native_id is not None and native_id != policy.continuity_event_id:
        raise ValueError("segmented export continuity source conflicts with the frozen policy selection")
    if (export_material["base_plan"].to_bytes() != material["plan"].to_bytes()
            or export_material["dataset"].to_bytes() != material["dataset"].to_bytes()
            or sorted(fold["fold_id"] for fold in export["folds"]) != sorted(fold["fold_id"] for fold in material["plan"].protocol["folds"])):
        raise ValueError("segmented export cannot change source scope or omit original TRAIN folds")
    cutoff = parse_rfc3339(request.data_cutoff_at, "cutoff")
    if any(parse_rfc3339(event.recorded_at, "source clock") > cutoff for event in (binding_event, export_event, *selected)):
        raise ValueError("segmented qualification cutoff excludes selected source records")
    from .trading_continuity_intake import verify_continuity_intake
    from .trading_continuity_qualification import qualify_continuity_windows
    source = material["sources"]["continuity_event_id"]
    native = None if source is None else verify_continuity_intake(source.payload["export"], blobs)
    continuity = qualify_continuity_windows(policy, material["plan"], material["dataset"], material["hypothesis"], native)
    calibration = _calibrate(material, export, selected, export_event, blobs)
    risk = _risk(material, calibration, continuity, blobs)
    protocol_status, protocol_reasons = _protocol(policy, material["plan"], risk)
    reasons = list(continuity["reason_codes"]) + calibration["reason_codes"] + risk["reason_codes"] + protocol_reasons
    if policy.status != "REVIEWED_FOR_SHADOW_QUALIFICATION": reasons.append("QUALIFICATION_POLICY_NOT_REVIEWED_FOR_SHADOW")
    if not continuity["counts"]["combined_eligible"]: reasons.append("NO_COMPARABLE_CONTINUITY_WINDOWS")
    previous = [event for event in events if event.event_type == ASSESSMENT_TYPE and event.payload["binding_event_id"] == binding_event.event_id]
    if any(parse_rfc3339(event.recorded_at, "prior record") > parse_rfc3339(request.recorded_at, "record clock") for event in previous):
        raise ValueError("segmented assessment cannot backdate preceding binding history")
    if request.supersedes_event_id is not None:
        superseded = next((event for event in previous if event.event_id == request.supersedes_event_id), None)
        if superseded is None or any(event.payload["request"]["supersedes_event_id"] == superseded.event_id for event in previous):
            raise ValueError("segmented supersession requires an unsuperseded same-binding assessment")
        if parse_rfc3339(superseded.payload["request"]["data_cutoff_at"], "prior cutoff") > cutoff:
            raise ValueError("segmented supersession cannot move cutoff backwards")
    reasons = sorted(set(reasons))
    provenance = {"links": context["links"], "binding_event_id": binding_event.event_id, "aggregate_export_event_id": export_event.event_id,
        "segment_event_ids": sorted(event.event_id for event in selected), "hypothesis_sha256": policy.hypothesis_evidence["sha256"],
        "original_policy_sha256": sha256_bytes(policy.to_bytes()), "calibration_source": CALIBRATION_SOURCE,
        "old_policy_quote_chains_used": False, "old_policy_cost_model_overridden": False,
        "v19_consumer_v18_status": export["consumer_v18"], "native_continuity_review_status": continuity["native_continuity_review_status"],
        "inherited_native_coverage_supported": continuity["coverage_supported"], "export_continuity_coverage": export["continuity_coverage"],
        "export_continuity_packet_applied_to_native_windows": False, "capture_audit_selected": export["capture_audit"] is not None,
        "source_authentication_verified": False, "historical_point_in_time_verified": False, "reviewer_identity_authenticated": False,
        "design_freeze_semantics": "FROZEN_BINDING_AND_ORIGINAL_DESIGN_BEFORE_THIS_QUALIFICATION_ONLY"}
    limitations = ["QUALIFIED_DESIGN_NOT_SIMULATION_EXECUTION_OR_STRATEGY_PROMOTION", "ORIGINAL_V18_V19_RECORDS_AND_GATE_DISPOSITIONS_UNCHANGED",
        "OLD_POLICY_QUOTE_CHAINS_NOT_CONSUMED_BY_THIS_SEPARATE_METHOD", "EXPORT_COVERAGE_PACKET_DOES_NOT_UPGRADE_NATIVE_CONTINUITY_WINDOWS",
        "LATER_CONTINUITY_SUPPORT_REQUIRES_NEW_NATIVE_INTAKE_AND_POLICY_RECORD", "DAILY_VOLUME_PROXY_NOT_OPENING_LIQUIDITY_OR_FILL_CAPACITY",
        "UNCERTAINTY_PROTOCOL_FROZEN_NOT_IMPLEMENTED_OR_STATISTICALLY_VALIDATED", "FINAL_HOLDOUT_UNSCORED_NOT_ACCESS_SEALED"]
    if export["capture_audit"] is None: limitations.append("CAPTURE_OPERATION_AUDIT_NOT_SELECTED")
    result = validate_result({"schema_version": RESULT_VERSION, "method_version": METHOD_VERSION,
        "qualification_id": request.qualification_id, "binding_id": binding.binding_id, "policy_id": policy.policy_id,
        "status": "DEFER_EVIDENCE_QUALIFICATION" if reasons else "READY_FOR_QUALIFIED_STUDY_DESIGN", "eligible_for_study_design": not reasons,
        "reason_codes": reasons, "continuity": continuity, "training_calibration": calibration, "risk": risk,
        "uncertainty_protocol": policy.uncertainty_protocol, "uncertainty_status": protocol_status,
        "uncertainty_computed": False, "economic_hypothesis_supported": False, "existing_gate_override": False,
        "execution_status": "NOT_EXECUTED", "realized_trade_pnl": None, "limitations": limitations, "provenance": provenance,
        "auto_trading_enabled": False, "authority": AUTHORITY})
    evidence = dict(context["evidence"])
    merge(evidence, {"segmented-qualification/request.v1.json": request.to_bytes()})
    return {**context, "request": request, "binding_event": binding_event, "aggregate_export_event": export_event,
        "result": result, "evidence": evidence, "prior_qualification_event_ids": sorted(event.event_id for event in previous)}
