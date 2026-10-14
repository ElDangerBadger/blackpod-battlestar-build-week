"""Descriptive independent effective-date reconciliation, with no gate bridge."""
from collections import defaultdict
from datetime import date
from zoneinfo import ZoneInfo

from .contracts.effective_date_reconciliation import (
    EffectiveDateReconciliationRequest, IndependentActionInventory, ACTION_TYPES,
    RESULT_VERSION, METHOD_VERSION, AUTHORITY, validate_result, declared_scope_gaps,
)
from .contracts.trading_research import TradingResearchDataset
from .contracts.trading_continuity_intake import ContinuityIntakeExport, ContinuityCoverageReview
from .contracts.mission_request import parse_rfc3339
from .hashing import canonical_json_bytes, sha256_bytes
from .trading_continuity_intake import verify_continuity_intake, _blob
from .independent_action_sources import parse_independent_inventory

CODE_PATHS = ("contracts/effective_date_reconciliation.py", "effective_date_reconciliation.py", "independent_action_sources.py")
LIMITATIONS = (
    "DESCRIPTIVE_RECONCILIATION_NO_NATIVE_GATE_OVERRIDE",
    "POSITIVE_ACTION_MATCHES_AND_DECLARED_INTERVALS_DO_NOT_PROVE_ACTION_ABSENCE_OR_COMPLETENESS",
    "SSGA_WORKBOOK_LISTS_CASH_DISTRIBUTIONS_ONLY_NOT_ALL_CORPORATE_ACTION_TYPES",
    "AUTHORED_SOURCE_PROFILE_IS_UNVERIFIED_EVEN_WHEN_DECLARED_COMPLETE",
    "DISTINCT_BYTES_PUBLISHERS_AND_URLS_DO_NOT_AUTHENTICATE_ECONOMIC_SOURCE_INDEPENDENCE",
    "MATCHED_EVENT_KEYS_DO_NOT_VERIFY_AMOUNTS_PAYMENT_STATUS_OR_HISTORICAL_KNOWN_TIME",
    "UNKNOWN_CANCELLED_REVISED_AND_SCHEDULED_ROWS_RETAINED_WITHOUT_NATIVE_REPLACEMENTS",
    "NO_ALPACA_RECORDS_PRICE_REPAIRS_RETURN_SCORING_OR_HOLDOUT_SCORING_CREATED",
    "COVERAGE_PROPOSAL_UNRESOLVED_REQUIRES_NEW_NATIVE_INTAKE_AND_POLICY_IF_LATER_SUPPORTED",
)


def _retain(evidence, path, raw):
    if path in evidence and evidence[path] != raw: raise ValueError("reconciliation evidence paths bind conflicting bytes")
    evidence[path] = raw
    if len(evidence) > 512 or sum(map(len, evidence.values())) > 64 * 1024 * 1024: raise ValueError("reconciliation evidence closure exceeds file/byte bound")


def _key(row, universe):
    # Preserve counterparties/aliases as well as the requested constituents.
    return (row["native_type"], row["effective_date"], tuple(sorted(set(row["affected_symbols"]))))


def reconcile_effective_dates(request, blobs):
    request = request if isinstance(request, EffectiveDateReconciliationRequest) else EffectiveDateReconciliationRequest.from_mapping(request)
    dataset_raw = _blob(blobs, request.dataset_evidence)
    dataset = TradingResearchDataset.from_bytes(dataset_raw)
    export_raw = _blob(blobs, request.native_continuity_export_evidence)
    export = ContinuityIntakeExport.from_bytes(export_raw)
    if export.dataset_evidence != request.dataset_evidence: raise ValueError("reconciliation must bind the exact original native dataset")
    cutoff = parse_rfc3339(request.data_cutoff_at, "cutoff")
    if parse_rfc3339(export.recorded_at, "native clock") > cutoff: raise ValueError("reconciliation cutoff excludes the original native source")
    native = verify_continuity_intake(export, blobs)
    if native["dataset"].to_bytes() != dataset_raw: raise ValueError("native source dataset differs from the exact submitted dataset")
    evidence = dict(native["evidence"])
    _retain(evidence, "effective-date/request.v1.json", request.to_bytes())
    _retain(evidence, "effective-date/original-native-export.v1.json", export_raw)
    dates = [parse_rfc3339(session["open_at"], "session open").astimezone(ZoneInfo("America/New_York")).date().isoformat() for session in dataset.sessions]
    start, end = dates[0], dates[-1]
    source_inventory, independent, ids, bodies = [], [], set(), set()
    forbidden = {ref["sha256"] for ref in export.source_evidence} | {request.dataset_evidence["sha256"], request.native_continuity_export_evidence["sha256"]}
    for reference in request.independent_inventories:
        raw = _blob(blobs, reference)
        inventory = IndependentActionInventory.from_bytes(raw)
        if inventory.inventory_id in ids or inventory.body_evidence["sha256"] in bodies: raise ValueError("independent inventories cannot duplicate IDs or source bodies")
        ids.add(inventory.inventory_id); bodies.add(inventory.body_evidence["sha256"])
        if inventory.body_evidence["sha256"] in forbidden: raise ValueError("independent body cannot reuse original dataset/process responses/declarations")
        if inventory.evidence_scope != export.evidence_scope or not set(inventory.declared_coverage["symbols"]) <= set(dataset.universe): raise ValueError("independent inventory must retain original evidence scope and fixed universe")
        if parse_rfc3339(inventory.recorded_at, "inventory clock") > cutoff or parse_rfc3339(inventory.captured_at, "capture clock") > cutoff: raise ValueError("reconciliation cutoff excludes selected independent source")
        _retain(evidence, "effective-date/inventory/" + reference["sha256"] + ".json", raw)
        leaves = [inventory.body_evidence, *inventory.supporting_evidence]
        if sum(map(len, evidence.values())) + sum(ref["size_bytes"] for ref in leaves if ref["path"] not in evidence) > 64 * 1024 * 1024:
            raise ValueError("independent source closure exceeds byte bound before parsing")
        parsed = parse_independent_inventory(inventory, blobs)
        for path, value in parsed["evidence"].items(): _retain(evidence, path, value)
        selected_rows = []
        for row in parsed["actions"]:
            if not set(row["affected_symbols"]) & set(dataset.universe): raise ValueError("independent action does not concern the original universe")
            identity = "independent-action-" + sha256_bytes(canonical_json_bytes({"inventory_id": inventory.inventory_id, "source_action_id": row["source_action_id"]}))
            day = row["effective_date"]
            disposition = "UNKNOWN_EFFECTIVE_DATE" if day is None else "BEFORE_DATASET" if day < start else "AFTER_DATASET" if day > end else "IN_DATASET"
            normalized = {"independent_action_id": identity, "inventory_id": inventory.inventory_id, **row, "dataset_disposition": disposition}
            independent.append(normalized); selected_rows.append(normalized)
        if len(independent) > 20000: raise ValueError("independent action count exceeds bounded reconciliation workload")
        source_inventory.append({"inventory_id": inventory.inventory_id, "manifest_evidence": reference, "profile": inventory.profile,
            "publisher": inventory.publisher, "source_url": inventory.source_url, "captured_at": inventory.captured_at,
            "body_evidence": inventory.body_evidence, "declared_coverage": inventory.declared_coverage,
            "source_scope": parsed["source_scope"], "rows_scanned": parsed["rows_scanned"], "observed_target_rows": len(selected_rows),
            "observed_symbols": sorted({symbol for row in selected_rows for symbol in row["affected_symbols"]}),
            "observed_action_types": parsed["observed_action_types"], "completeness_verified": False, "source_authentication_verified": False})
    native_rows = export.native_actions
    native_by_key, independent_by_key = defaultdict(list), defaultdict(list)
    unknown, conflicts = [], []
    for row in native_rows:
        if row["effective_date"] is None: unknown.append({"source": "NATIVE", "action_id": row["native_id"]})
        elif row["dataset_disposition"] == "IN_DATASET": native_by_key[_key(row, dataset.universe)].append(row["native_id"])
    for row in independent:
        if row["effective_date"] is None: unknown.append({"source": "INDEPENDENT", "action_id": row["independent_action_id"]})
        if row["status"] in {"SCHEDULED", "CANCELLED", "REVISED", "UNKNOWN"}:
            conflicts.append({"kind": "INDEPENDENT_STATUS_NOT_CONFIRMED_EFFECTIVE", "independent_action_ids": [row["independent_action_id"]], "native_action_ids": [], "status": row["status"]})
        elif row["dataset_disposition"] == "IN_DATASET": independent_by_key[_key(row, dataset.universe)].append(row["independent_action_id"])
    matches, native_only, independent_only, ambiguous, duplicates = [], [], [], [], []
    for key in sorted(set(native_by_key) | set(independent_by_key)):
        left, right = sorted(native_by_key[key]), sorted(independent_by_key[key])
        row = {"native_type": key[0], "effective_date": key[1], "affected_symbols": list(key[2]), "native_action_ids": left, "independent_action_ids": right}
        if len(left) > 1 or len(right) > 1:
            ambiguous.append(row); duplicates.append(row)
        elif left and right: matches.append({**row, "comparison": "EVENT_KEY_ONLY_AMOUNT_AND_STATUS_UNVERIFIED"})
        elif left: native_only.append(row)
        else: independent_only.append(row)
    # Potential disagreements are retained as candidates, never fuzzy-matched.
    if len(native_only) * len(independent_only) > 2000000: raise ValueError("reconciliation date/type conflict workload exceeds fixed bound")
    for left in native_only:
        for right in independent_only:
            overlap = bool(set(left["affected_symbols"]) & set(right["affected_symbols"]))
            if (overlap and (left["native_type"] == right["native_type"] or left["effective_date"] == right["effective_date"])) or (not overlap and left["native_type"] == right["native_type"] and left["effective_date"] == right["effective_date"]):
                symbol_conflict = left["native_type"] == right["native_type"] and left["effective_date"] == right["effective_date"] and left["affected_symbols"] != right["affected_symbols"]
                conflicts.append({"kind": "POSSIBLE_SYMBOL_CONFLICT_NOT_RESOLVED" if symbol_conflict else "POSSIBLE_DATE_OR_TYPE_CONFLICT_NOT_RESOLVED", "native_action_ids": left["native_action_ids"], "independent_action_ids": right["independent_action_ids"], "status": "UNRESOLVED"})
                if len(conflicts) > 20000: raise ValueError("reconciliation conflict workload exceeds bound")
    matrix = []
    for symbol in dataset.universe:
        for action_type in ACTION_TYPES:
            rows = [row for row in independent if symbol in row["affected_symbols"] and row["native_type"] == action_type and row["dataset_disposition"] == "IN_DATASET"]
            intervals = [{"inventory_id": item["inventory_id"], "start": item["declared_coverage"]["effective_start"], "end": item["declared_coverage"]["effective_end"], "completeness": item["declared_coverage"]["completeness"]}
                for item in source_inventory if symbol in item["declared_coverage"]["symbols"] and action_type in item["declared_coverage"]["action_types"]]
            matrix.append({"symbol": symbol, "action_type": action_type, "observed_event_count": len(rows), "observed_effective_dates": sorted({row["effective_date"] for row in rows}),
                "declared_intervals": intervals, "declared_scope_gaps": declared_scope_gaps(start, end, intervals), "uncovered_intervals": [{"start": start, "end": end, "reason": "CONTINUOUS_EFFECTIVE_DATE_COMPLETENESS_NOT_VERIFIED"}], "coverage_supported": False})
    reasons = ["INDEPENDENT_FULL_SPAN_ALL_ACTION_TYPE_COVERAGE_UNVERIFIED"]
    for values, reason in ((native_only, "NATIVE_ONLY_ACTIONS"), (independent_only, "INDEPENDENT_ONLY_ACTIONS"), (ambiguous, "AMBIGUOUS_ACTION_KEYS"), (conflicts, "ACTION_SOURCE_CONFLICTS"), (unknown, "UNKNOWN_EFFECTIVE_DATES")):
        if values: reasons.append(reason)
    if not export.pagination_complete: reasons.append("ORIGINAL_NATIVE_CAPTURE_INCOMPLETE_OR_UNAVAILABLE")
    refs = [{"path": "effective-date/inventory/" + ref["sha256"] + ".json", "sha256": ref["sha256"], "size_bytes": ref["size_bytes"]} for ref in request.independent_inventories]
    proposal = ContinuityCoverageReview.from_mapping({"schema_version": "blackpod.trading_continuity_coverage_review.v1", "review_id": request.reconciliation_id,
        "recorded_at": request.recorded_at, "dataset_evidence": request.dataset_evidence, "universe": dataset.universe,
        "coverage_start_session_id": dataset.sessions[0]["session_id"], "coverage_end_session_id": dataset.sessions[-1]["session_id"],
        "coverage_policy": "ALL_ACTION_TYPES_EFFECTIVE_DATE_COVERAGE_INDEPENDENTLY_REVIEWED", "status": "UNRESOLVED", "reviewer_id": "deterministic-reconciliation-not-human-approval",
        "review_notes": "Descriptive independent source reconciliation; no completeness, applicability, approval or native gate override is asserted.",
        "source_evidence": refs, "auto_trading_enabled": False, "authority": AUTHORITY})
    result = validate_result({"schema_version": RESULT_VERSION, "method_version": METHOD_VERSION, "reconciliation_id": request.reconciliation_id, "status": "DESCRIPTIVE_RECONCILIATION_ONLY",
        "dataset_evidence": request.dataset_evidence, "native_continuity_export_evidence": request.native_continuity_export_evidence,
        "effective_span": {"start": start, "end": end, "calendar_days": (date.fromisoformat(end) - date.fromisoformat(start)).days + 1}, "universe": dataset.universe,
        "source_inventory": source_inventory, "independent_actions": independent, "native_actions": native_rows, "matches": matches, "native_only": native_only,
        "independent_only": independent_only, "ambiguous": ambiguous, "conflicts": conflicts, "unknown_effective_dates": unknown, "duplicate_groups": duplicates,
        "coverage_matrix": matrix, "reason_codes": sorted(reasons), "coverage_proposal": proposal.to_dict(),
        "native_gate_override": False, "coverage_supported": False, "source_authentication_verified": False, "source_independence_verified": False,
        "historical_point_in_time_verified": False, "economic_hypothesis_supported": False, "uncertainty_computed": False, "execution_status": "NOT_EXECUTED", "realized_trade_pnl": None,
        "limitations": list(LIMITATIONS), "auto_trading_enabled": False, "authority": AUTHORITY})
    _retain(evidence, "effective-date/coverage-proposal.unresolved.v1.json", proposal.to_bytes())
    return {"request": request, "result": result, "evidence": evidence, "dataset": dataset, "native_material": native}
