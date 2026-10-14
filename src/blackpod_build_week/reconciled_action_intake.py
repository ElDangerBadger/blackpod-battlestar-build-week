"""Pure conservative research intake of original native and issuer observations.

This creates a separately versioned risk overlay. It never constructs a native
PriceContinuitySource, changes a native mask, adjusts a price, or grants study,
capital, execution or policy authority.
"""
from collections import defaultdict
from copy import deepcopy
from zoneinfo import ZoneInfo

from .contracts.reconciled_action_intake import (
    ReconciledActionIntakePolicy, ReconciledActionIntakeRequest, RESULT_VERSION,
    METHOD_VERSION, OVERLAY_VERSION, ACTION_TYPES, AUTHORITY, FALSE_FIELDS,
    validate_result,
)
from .contracts.effective_date_reconciliation import IndependentActionInventory, AUTHORED_PROFILE
from .contracts.qqq_distribution_inventory import QQQDistributionInventory, VERSION as QQQ_VERSION, evidence_references as qqq_references
from .contracts.trading_research import TradingResearchDataset
from .contracts.trading_continuity_intake import ContinuityIntakeExport
from .contracts.mission_request import ContractValidationError, parse_rfc3339, parse_strict_json_object_bytes
from .hashing import canonical_json_bytes, sha256_bytes
from .trading_continuity_intake import verify_continuity_intake, _blob
from .independent_action_sources import parse_independent_inventory
from .qqq_distribution_inventory import parse_qqq_distribution_inventory

CODE_PATHS = (
    "contracts/reconciled_action_intake.py", "reconciled_action_intake.py",
    "contracts/qqq_distribution_inventory.py", "qqq_distribution_inventory.py",
    "contracts/effective_date_reconciliation.py", "independent_action_sources.py",
    "contracts/trading_continuity_intake.py", "trading_continuity_intake.py",
)
MAX_FILES = 512
MAX_SOURCE_BYTES = 64 * 1024 * 1024
MAX_OBSERVATIONS = 20000
MAX_CONFLICT_COMPARISONS = 2_000_000
LIMITATIONS = (
    "SHADOW_CANDIDATE_ONLY_NO_NATIVE_SOURCE_MASK_OR_GATE_OVERRIDE",
    "ALL_FIXED_SYMBOL_ACTION_TYPE_COVERAGE_CELLS_REMAIN_UNRESOLVED",
    "ISSUER_LISTED_EX_DATES_ARE_RISK_DECLARATIONS_NOT_CONFIRMED_PAYMENT_OR_ECONOMIC_TRUTH",
    "ALL_NATIVE_AND_SELECTED_ISSUER_ROWS_RETAINED_WITHOUT_SOURCE_PRECEDENCE_OR_FUZZY_MATCHING",
    "EXACT_EVENT_KEY_MATCH_DOES_NOT_VERIFY_AMOUNTS_STATUS_OR_PAYMENT",
    "CANCELLED_ROWS_RETAINED_WITHOUT_ACTIVE_BOUNDARY_AND_WITHOUT_ELIGIBILITY_PROMOTION",
    "UNKNOWN_NATIVE_FIRST_SESSION_PLACEHOLDERS_RETAINED_ONLY_IN_ORIGINAL_SOURCE_NOT_KNOWN_BOUNDARIES",
    "RETROSPECTIVE_SOURCE_RECONCILIATION_AND_POLICY_FREEZE_NOT_HISTORICAL_KNOWN_TIME_OR_PRECOMMITMENT_PROOF",
    "DISTINCT_PUBLISHER_URL_AND_BYTES_DO_NOT_AUTHENTICATE_SOURCE_INDEPENDENCE",
    "FULL_ALIAS_SYMBOL_SETS_RETAINED_NO_REPAIRED_PRICES_RETURNS_COSTS_OR_HOLDOUT_SCORES",
    "AUTHORED_INVENTORIES_ACCEPTED_ONLY_AS_EXPLICIT_SYNTHETIC_FIXTURES",
)


def _retain(evidence, path, raw):
    if path in evidence and evidence[path] != raw:
        raise ContractValidationError("reconciled intake evidence path binds conflicting bytes")
    evidence[path] = raw
    if len(evidence) > MAX_FILES or sum(map(len, evidence.values())) > MAX_SOURCE_BYTES:
        raise ContractValidationError("reconciled intake source closure exceeds file or byte bound")


def _clock(value):
    return parse_rfc3339(value, "reconciled intake source clock")


def _inventory_leaves(inventory):
    if isinstance(inventory, QQQDistributionInventory): return qqq_references(inventory)
    return [inventory.body_evidence, *inventory.supporting_evidence]


def inspect_policy_sources(policy, blobs):
    """Verify frozen source closure without creating a candidate or new masks.

    The journal wrapper additionally binds the policy to its exact verified v22
    anchor and requires all previously selected inventory manifests unchanged.
    """
    policy = policy if isinstance(policy, ReconciledActionIntakePolicy) else ReconciledActionIntakePolicy.from_mapping(policy)
    frozen_at = _clock(policy.recorded_at)
    dataset_raw = _blob(blobs, policy.dataset_evidence)
    dataset = TradingResearchDataset.from_bytes(dataset_raw)
    export_raw = _blob(blobs, policy.native_continuity_export_evidence)
    export = ContinuityIntakeExport.from_bytes(export_raw)
    if export.dataset_evidence != policy.dataset_evidence or export.evidence_scope != policy.evidence_scope:
        raise ContractValidationError("frozen native dataset or evidence scope differs")
    if _clock(export.recorded_at) > frozen_at:
        raise ContractValidationError("policy cannot precede original native source")
    native = verify_continuity_intake(export, blobs)
    if native["dataset"].to_bytes() != dataset_raw:
        raise ContractValidationError("policy dataset is not the exact original native dataset")
    mask_raw = _blob(blobs, policy.original_native_masks_evidence)
    if len(mask_raw) > 8 * 1024 * 1024:
        raise ContractValidationError("original mask fragment exceeds bound")
    masks = parse_strict_json_object_bytes(mask_raw, document_name="original native mask fragment")
    if canonical_json_bytes(masks) != mask_raw:
        raise ContractValidationError("original mask fragment must retain exact canonical snapshot bytes")
    evidence = {}
    for path, raw in native["evidence"].items(): _retain(evidence, path, raw)
    for ref, raw in ((policy.dataset_evidence, dataset_raw), (policy.native_continuity_export_evidence, export_raw), (policy.original_native_masks_evidence, mask_raw)):
        _retain(evidence, ref["path"], raw)
    forbidden = {ref["sha256"] for ref in export.source_evidence} | {policy.dataset_evidence["sha256"], policy.native_continuity_export_evidence["sha256"], policy.original_native_masks_evidence["sha256"]}
    inventories, inventory_ids = [], set()
    total_actions = 0
    for reference in policy.independent_inventories:
        if reference["size_bytes"] > 256 * 1024:
            raise ContractValidationError("inventory manifest exceeds bound")
        raw = _blob(blobs, reference)
        document = parse_strict_json_object_bytes(raw, document_name="selected action inventory")
        klass = QQQDistributionInventory if document.get("schema_version") == QQQ_VERSION else IndependentActionInventory
        inventory = klass.from_mapping(document)
        if inventory.inventory_id in inventory_ids:
            raise ContractValidationError("selected inventories have conflicting reused identity")
        inventory_ids.add(inventory.inventory_id)
        if inventory.evidence_scope != policy.evidence_scope:
            raise ContractValidationError("selected inventory changes the frozen evidence scope")
        if inventory.profile == AUTHORED_PROFILE and policy.evidence_scope != "SYNTHETIC_FIXTURE_ONLY":
            raise ContractValidationError("authored inventory cannot stand in for retained real issuer evidence")
        if not set(inventory.declared_coverage["symbols"]) <= set(dataset.universe):
            raise ContractValidationError("selected inventory changes the original fixed universe")
        if max(_clock(inventory.recorded_at), _clock(inventory.captured_at)) > frozen_at:
            raise ContractValidationError("policy cannot precede selected source capture or manifest")
        if inventory.body_evidence["sha256"] in forbidden:
            raise ContractValidationError("issuer body cannot relabel original native evidence")
        leaves = _inventory_leaves(inventory)
        if sum(map(len, evidence.values())) + len(raw) + sum(ref["size_bytes"] for ref in leaves if ref["path"] not in evidence) > MAX_SOURCE_BYTES:
            raise ContractValidationError("selected inventory closure exceeds bound before parsing")
        _retain(evidence, reference["path"], raw)
        # Hash every leaf before parsing, including authored supporting material.
        for ref in leaves: _retain(evidence, ref["path"], _blob(blobs, ref))
        parsed = parse_qqq_distribution_inventory(inventory, blobs) if klass is QQQDistributionInventory else parse_independent_inventory(inventory, blobs)
        for action in parsed["actions"]:
            if not set(action["affected_symbols"]) & set(dataset.universe):
                raise ContractValidationError("selected action is unrelated to frozen universe")
        total_actions += len(parsed["actions"])
        if total_actions > MAX_OBSERVATIONS:
            raise ContractValidationError("selected issuer rows exceed intake bound")
        for path, value in parsed["evidence"].items(): _retain(evidence, path, value)
        inventories.append({"manifest_evidence": deepcopy(reference), "inventory": inventory, "parsed": parsed})
    return {"dataset": dataset, "native_material": native, "inventories": inventories, "original_masks": masks, "evidence": evidence}


def _dates(dataset):
    return [_clock(session["open_at"]).astimezone(ZoneInfo("America/New_York")).date().isoformat() for session in dataset.sessions]


def _disposition(day, dates):
    return "UNKNOWN_EFFECTIVE_DATE" if day is None else "BEFORE_DATASET" if day < dates[0] else "AFTER_DATASET" if day > dates[-1] else "IN_DATASET"


def _boundary(origin, identity, row, dates, sessions):
    day = row["effective_date"]
    disposition = _disposition(day, dates)
    index, mapped_id = None, None
    mapping = disposition
    if disposition == "IN_DATASET":
        index = next(index for index, value in enumerate(dates) if value >= day)
        mapped_id = sessions[index]["session_id"]
        mapping = "EXACT_RETURNED_DATE" if dates[index] == day else "NEXT_RETURNED_DATE"
    status = "NATIVE_STATUS_UNAVAILABLE" if origin == "NATIVE" else row["status"]
    return {"boundary_id": "reconciled-boundary-" + sha256_bytes(canonical_json_bytes({"origin": origin, "source_id": identity})),
        "origin": origin, "source_id": identity, "native_type": row["native_type"], "affected_symbols": deepcopy(row["affected_symbols"]),
        "declared_effective_date": day, "mapped_session_id": mapped_id, "mapped_session_index": index, "mapping": mapping,
        "source_status": status, "boundary_flag": index is not None and status != "CANCELLED",
        "legacy_placeholder_retained": origin == "NATIVE" and day is None, "eligible": False, "confirmed_payment": False}


def _key(row):
    return row["native_type"], row["effective_date"], tuple(row["affected_symbols"])


def _group(key, left, right):
    return {"native_type": key[0], "effective_date": key[1], "affected_symbols": list(key[2]),
        "native_action_ids": sorted(left), "independent_action_ids": sorted(right), "comparison": "EXACT_KEY_ONLY_NOT_ECONOMIC_CONFIRMATION"}


def _conflict(kind, left=(), right=()):
    return {"kind": kind, "native_action_ids": sorted(set(left)), "independent_action_ids": sorted(set(right)), "status": "UNRESOLVED"}


def build_reconciled_action_intake(policy, request, blobs):
    """Retain all observations, classify exact keys and build a risk-only overlay."""
    policy = policy if isinstance(policy, ReconciledActionIntakePolicy) else ReconciledActionIntakePolicy.from_mapping(policy)
    request = request if isinstance(request, ReconciledActionIntakeRequest) else ReconciledActionIntakeRequest.from_mapping(request)
    policy_raw = _blob(blobs, request.policy_evidence)
    # An exact policy byte identity, not a freshly normalized substitute.
    if policy_raw != policy.to_bytes():
        raise ContractValidationError("intake must bind the exact frozen canonical policy")
    if _clock(policy.recorded_at) > _clock(request.data_cutoff_at):
        raise ContractValidationError("intake cutoff cannot precede frozen policy")
    material = inspect_policy_sources(policy, blobs)
    dataset, native = material["dataset"], material["native_material"]
    export = native["export"]
    evidence = dict(material["evidence"])
    _retain(evidence, request.policy_evidence["path"], policy_raw)
    _retain(evidence, "reconciled-action-intake/request.v1.json", request.to_bytes())
    dates = _dates(dataset); span = {"start": dates[0], "end": dates[-1]}
    source_inventories, observations = [], []
    for selected in material["inventories"]:
        inventory, parsed = selected["inventory"], selected["parsed"]
        for action in parsed["actions"]:
            identity = "independent-action-" + sha256_bytes(canonical_json_bytes({"inventory_id": inventory.inventory_id, "source_action_id": action["source_action_id"]}))
            observations.append({"independent_action_id": identity, "inventory_id": inventory.inventory_id, **deepcopy(action), "dataset_disposition": _disposition(action["effective_date"], dates)})
        source_inventories.append({"manifest_evidence": selected["manifest_evidence"], "inventory": inventory.to_dict(), "source_scope": parsed["source_scope"],
            "rows_scanned": parsed["rows_scanned"], "observed_action_count": len(parsed["actions"]), "completeness_verified": False, "source_authentication_verified": False})
    native_rows = export.native_actions
    left, right = defaultdict(list), defaultdict(list)
    conflicts = []
    for row in native_rows:
        if row["effective_date"] is not None: left[_key(row)].append(row["native_id"])
    for row in observations:
        if row["effective_date"] is not None: right[_key(row)].append(row["independent_action_id"])
        if row["status"] in {"SCHEDULED", "CANCELLED", "REVISED", "UNKNOWN"}:
            conflicts.append(_conflict("SOURCE_STATUS_UNRESOLVED", right=[row["independent_action_id"]]))
        if row["replaces_source_action_id"] is not None:
            conflicts.append(_conflict("REPLACEMENT_LINK_UNRESOLVED", right=[row["independent_action_id"]]))
    matches, native_only, issuer_only, ambiguous, duplicates = [], [], [], [], []
    for key in sorted(set(left) | set(right)):
        group = _group(key, left[key], right[key])
        if len(left[key]) > 1 or len(right[key]) > 1:
            ambiguous.append(group); duplicates.append(deepcopy(group))
            conflicts.append(_conflict("EXACT_KEY_MULTIPLICITY", left[key], right[key]))
        elif left[key] and right[key]: matches.append(group)
        elif left[key]: native_only.append(group)
        else: issuer_only.append(group)
    if len(native_only) * len(issuer_only) > MAX_CONFLICT_COMPARISONS:
        raise ContractValidationError("possible source conflict comparisons exceed bound")
    for native_group in native_only:
        for issuer_group in issuer_only:
            same_type = native_group["native_type"] == issuer_group["native_type"]
            same_date = native_group["effective_date"] == issuer_group["effective_date"]
            overlap = bool(set(native_group["affected_symbols"]) & set(issuer_group["affected_symbols"]))
            if (overlap and (same_type or same_date)) or (same_type and same_date):
                conflicts.append(_conflict("POSSIBLE_DATE_TYPE_OR_SYMBOL_CONFLICT", native_group["native_action_ids"], issuer_group["independent_action_ids"]))
                if len(conflicts) > 20000: raise ContractValidationError("source conflicts exceed result bound")
    bodies = defaultdict(list)
    for selected in material["inventories"]: bodies[selected["inventory"].body_evidence["sha256"]].append(selected["inventory"].inventory_id)
    for inventory_ids in bodies.values():
        if len(inventory_ids) > 1:
            conflicts.append(_conflict("DUPLICATE_SOURCE_BODY", right=[row["independent_action_id"] for row in observations if row["inventory_id"] in inventory_ids]))
    # Deduplicate identical conflict descriptions only; every source row remains.
    conflicts = sorted({canonical_json_bytes(item): item for item in conflicts}.values(), key=canonical_json_bytes)
    boundaries = [_boundary("NATIVE", row["native_id"], row, dates, dataset.sessions) for row in native_rows]
    boundaries.extend(_boundary("ISSUER_DECLARATION", row["independent_action_id"], row, dates, dataset.sessions) for row in observations)
    unknown = [{"origin": item["origin"], "source_id": item["source_id"], "affected_symbols": item["affected_symbols"], "reason": "UNKNOWN_EFFECTIVE_DATE_NO_INVENTED_BOUNDARY"} for item in boundaries if item["declared_effective_date"] is None]
    overlay = {"schema_version": OVERLAY_VERSION, "status": "NOT_ELIGIBLE_COVERAGE_UNRESOLVED", "boundaries": boundaries, "unknown_date_scope": unknown,
        "coverage_complete": False, "eligible_for_shadow_study": False, "native_gate_override": False}
    matrix = []
    for symbol in dataset.universe:
        for action_type in ACTION_TYPES:
            matrix.append({"symbol": symbol, "action_type": action_type, "status": "UNRESOLVED", "coverage_complete": False, "eligible": False,
                "declared_source_inventory_ids": sorted(selected["inventory"].inventory_id for selected in material["inventories"] if symbol in selected["inventory"].declared_coverage["symbols"] and action_type in selected["inventory"].declared_coverage["action_types"]),
                "observed_native_count": sum(symbol in row["affected_symbols"] and row["native_type"] == action_type and row["dataset_disposition"] == "IN_DATASET" for row in native_rows),
                "observed_issuer_count": sum(symbol in row["affected_symbols"] and row["native_type"] == action_type and row["dataset_disposition"] == "IN_DATASET" for row in observations), "unresolved_interval": deepcopy(span)})
    reasons = ["ALL_SYMBOL_ACTION_TYPE_COVERAGE_UNRESOLVED", "SEPARATE_SHADOW_INTAKE_NOT_NATIVE_GATE_INPUT"]
    for rows, code in ((native_only, "NATIVE_ONLY_ACTIONS"), (issuer_only, "ISSUER_ONLY_OBSERVATIONS"), (ambiguous, "AMBIGUOUS_EXACT_KEYS"), (conflicts, "UNRESOLVED_SOURCE_CONFLICTS"), (unknown, "UNKNOWN_EFFECTIVE_DATES")):
        if rows: reasons.append(code)
    if not export.pagination_complete: reasons.append("ORIGINAL_NATIVE_CAPTURE_INCOMPLETE_OR_UNAVAILABLE")
    result = {"schema_version": RESULT_VERSION, "method_version": METHOD_VERSION, "intake_id": request.intake_id, "policy_id": policy.policy_id, "policy_evidence": request.policy_evidence,
        "status": "SHADOW_CANDIDATE_NOT_ELIGIBLE", "dataset_evidence": policy.dataset_evidence, "native_continuity_export_evidence": policy.native_continuity_export_evidence,
        "universe": dataset.universe, "effective_span": span, "original_native_masks": {"evidence": policy.original_native_masks_evidence, "sha256": policy.original_native_masks_evidence["sha256"], "assessment": deepcopy(material["original_masks"])},
        "original_native_export": export.to_dict(), "original_native_events": native["source"].events,
        "source_inventories": source_inventories, "issuer_observations": observations, "matches": matches, "native_only": native_only, "issuer_only": issuer_only,
        "ambiguous": ambiguous, "duplicate_groups": duplicates, "conflicts": conflicts, "candidate_overlay": overlay, "coverage_matrix": matrix,
        "reason_codes": sorted(reasons), "limitations": list(LIMITATIONS), "execution_status": "NOT_EXECUTED", "realized_trade_pnl": None, "authority": dict(AUTHORITY), **{key: False for key in FALSE_FIELDS}}
    return {"result": validate_result(result), "evidence": evidence}
