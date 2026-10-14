"""Pure versioned consumer of an exact recorded reconciled action overlay.

Only session metadata and retained original opportunity booleans are consumed.
No original mask, signal, price, return, cost, capacity or policy is recalculated.
The journal wrapper verifies the selected event and immutable source lineage.
"""
from copy import deepcopy
from zoneinfo import ZoneInfo

from .contracts.reconciled_shadow_qualification import (
    ReconciledShadowQualificationRequest, RESULT_VERSION, METHOD_VERSION,
    AUTHORITY, FALSE_FIELDS, LIMITATIONS, GATE_REASONS, validate_result,
    validate_native_continuity, validate_catalog, project_windows,
)
from .contracts.reconciled_action_intake import ReconciledActionIntakePolicy, validate_result as validate_intake
from .contracts.segmented_evidence_qualification import validate_result as validate_native
from .contracts.trading_continuity_intake import ContinuityIntakeExport
from .contracts.trading_research import TradingResearchDataset
from .contracts.effective_date_reconciliation import IndependentActionInventory
from .contracts.qqq_distribution_inventory import QQQDistributionInventory, VERSION as QQQ_VERSION
from .contracts.mission_request import ContractValidationError, parse_rfc3339, parse_strict_json_object_bytes
from .hashing import canonical_json_bytes, sha256_bytes
from .trading_continuity_intake import _blob

CODE_PATHS = ("contracts/reconciled_shadow_qualification.py", "reconciled_shadow_qualification.py")
MAX_EVIDENCE_BYTES = 32 * 1024 * 1024


def _retain(evidence, reference, blobs):
    raw = _blob(blobs, reference)
    path = reference["path"]
    if path in evidence and evidence[path] != raw: raise ContractValidationError("shadow qualification evidence paths conflict")
    evidence[path] = raw
    if len(evidence) > 32 or sum(map(len, evidence.values())) > MAX_EVIDENCE_BYTES:
        raise ContractValidationError("shadow qualification direct source closure exceeds bound")
    return raw


def _clock(value):
    return parse_rfc3339(value, "reconciled shadow source clock")


def _assert_clock(value, cutoff):
    if _clock(value) > cutoff: raise ContractValidationError("qualification cutoff excludes a selected retained source")


def qualify_reconciled_overlay(request, intake_result, native_qualification_snapshot, blobs):
    """Return an additive all-window intersection with current coverage DEFER.

    The caller binds the actual recorded intake clock and exact preceding event
    lineage. The result itself has no intake record clock; this pure function
    never invents one or treats a result reference as event authentication.
    """
    request = request if isinstance(request, ReconciledShadowQualificationRequest) else ReconciledShadowQualificationRequest.from_mapping(request)
    intake = validate_intake(intake_result)
    native = validate_native(native_qualification_snapshot)
    evidence = {}
    intake_raw = _retain(evidence, request.intake_result_evidence, blobs)
    if intake_raw != canonical_json_bytes(intake): raise ContractValidationError("qualification must bind the exact canonical recorded intake result")
    policy_raw = _retain(evidence, intake["policy_evidence"], blobs)
    policy = ReconciledActionIntakePolicy.from_bytes(policy_raw)
    if policy_raw != policy.to_bytes() or policy.policy_id != intake["policy_id"]:
        raise ContractValidationError("qualification policy identity differs from selected intake")
    if policy.dataset_evidence != intake["dataset_evidence"] or policy.native_continuity_export_evidence != intake["native_continuity_export_evidence"] or policy.original_native_masks_evidence != intake["original_native_masks"]["evidence"]:
        raise ContractValidationError("qualification cannot independently reselect original source references")
    cutoff = _clock(request.data_cutoff_at)
    _assert_clock(policy.recorded_at, cutoff)
    dataset_raw = _retain(evidence, policy.dataset_evidence, blobs)
    dataset = TradingResearchDataset.from_bytes(dataset_raw)
    if dataset.to_bytes() != dataset_raw or dataset.schema_version != "blackpod.trading_research_dataset.v2" or dataset.universe != intake["universe"]:
        raise ContractValidationError("qualification requires the exact original canonical dataset v2 and universe")
    _assert_clock(dataset.recorded_at, cutoff)
    export_raw = _retain(evidence, policy.native_continuity_export_evidence, blobs)
    export = ContinuityIntakeExport.from_bytes(export_raw)
    if export.to_dict() != intake["original_native_export"] or export.dataset_evidence != policy.dataset_evidence or export.evidence_scope != policy.evidence_scope:
        raise ContractValidationError("qualification cannot replace the original native export")
    _assert_clock(export.recorded_at, cutoff)
    masks_raw = _retain(evidence, policy.original_native_masks_evidence, blobs)
    if masks_raw != canonical_json_bytes(intake["original_native_masks"]["assessment"]) or masks_raw != canonical_json_bytes(native["continuity"]):
        raise ContractValidationError("native qualification must retain the exact original continuity mask fragment")
    if native["continuity"]["native_action_audit"] != export.native_actions:
        raise ContractValidationError("native qualification retains a different original native action audit")
    sources = intake["source_inventories"]
    if [source["manifest_evidence"] for source in sources] != policy.independent_inventories:
        raise ContractValidationError("qualification cannot drop or reselect frozen source manifests")
    for source in sources:
        raw = _retain(evidence, source["manifest_evidence"], blobs)
        value = parse_strict_json_object_bytes(raw, document_name="frozen inventory manifest")
        klass = QQQDistributionInventory if value.get("schema_version") == QQQ_VERSION else IndependentActionInventory
        inventory = klass.from_mapping(value)
        if inventory.to_dict() != source["inventory"] or inventory.evidence_scope != policy.evidence_scope:
            raise ContractValidationError("selected inventory source identity differs from recorded intake")
        _assert_clock(inventory.recorded_at, cutoff); _assert_clock(inventory.captured_at, cutoff)
    # Retrieve session metadata once. No bar, close, volume or return field is
    # read after the existing immutable dataset contract has validated it.
    sessions = dataset.sessions
    validate_native_continuity(native["continuity"], dataset.universe, sessions=sessions,
        fold_ids=[fold["fold_id"] for fold in native["training_calibration"]["folds"]])
    catalog = validate_catalog(intake["candidate_overlay"])
    dates = [_clock(session["open_at"]).astimezone(ZoneInfo("America/New_York")).date().isoformat() for session in sessions]
    for boundary in catalog["boundaries"]:
        day = boundary["declared_effective_date"]
        if day is None:
            if boundary["mapping"] != "UNKNOWN_EFFECTIVE_DATE": raise ContractValidationError("unknown date cannot use original native placeholder")
            continue
        if day < dates[0]:
            if boundary["mapping"] != "BEFORE_DATASET": raise ContractValidationError("out-of-span source boundary mapping differs")
            continue
        if day > dates[-1]:
            if boundary["mapping"] != "AFTER_DATASET": raise ContractValidationError("out-of-span source boundary mapping differs")
            continue
        index = next(index for index, date in enumerate(dates) if date >= day)
        mapping = "EXACT_RETURNED_DATE" if dates[index] == day else "NEXT_RETURNED_DATE"
        if (boundary["mapped_session_index"], boundary["mapped_session_id"], boundary["mapping"]) != (index, sessions[index]["session_id"], mapping):
            raise ContractValidationError("reconciled boundary must bind the original returned calendar without reindexing")
    opportunities, counts = project_windows(native, catalog)
    reasons = set(native["reason_codes"]) | set(GATE_REASONS) | {"NO_EFFECTIVE_RECONCILED_WINDOWS"}
    if counts["additional_overlay_veto"]: reasons.add("ADDITIONAL_RECONCILED_BOUNDARY_VETOES")
    result = {"schema_version": RESULT_VERSION, "method_version": METHOD_VERSION, "qualification_id": request.qualification_id,
        "recorded_at": request.recorded_at, "data_cutoff_at": request.data_cutoff_at, "status": "DEFER_RECONCILED_SHADOW_QUALIFICATION",
        "input_bindings": {"intake_event_id": request.intake_event_id, "intake_id": intake["intake_id"], "intake_result_evidence": request.intake_result_evidence,
            "intake_policy_id": policy.policy_id, "intake_policy_evidence": intake["policy_evidence"], "dataset_evidence": policy.dataset_evidence,
            "original_native_masks_evidence": policy.original_native_masks_evidence, "native_qualification_id": native["qualification_id"], "native_binding_id": native["binding_id"],
            "native_policy_id": native["policy_id"], "native_snapshot_sha256": sha256_bytes(canonical_json_bytes(native))},
        "native_qualification_snapshot": deepcopy(native), "boundary_catalog": deepcopy(catalog), "coverage_matrix": deepcopy(intake["coverage_matrix"]),
        "opportunities": opportunities, "counts": counts, "reason_codes": sorted(reasons), "limitations": list(LIMITATIONS),
        "final_holdout": deepcopy(native["continuity"]["final_holdout"]), "execution_status": "NOT_EXECUTED", "realized_trade_pnl": None,
        "authority": dict(AUTHORITY), **{field: False for field in FALSE_FIELDS}}
    request_raw = request.to_bytes()
    request_path = "reconciled-shadow/request.v1.json"
    if request_path in evidence and evidence[request_path] != request_raw:
        raise ContractValidationError("shadow qualification request path conflicts with selected source evidence")
    evidence[request_path] = request_raw
    if sum(map(len, evidence.values())) > MAX_EVIDENCE_BYTES: raise ContractValidationError("qualification source closure exceeds byte bound")
    return {"result": validate_result(result), "evidence": evidence}
