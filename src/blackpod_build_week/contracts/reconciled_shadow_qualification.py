"""Closed shadow qualification contracts; reconciled risk can only restrict.

The original qualification remains evidence. This schema does not authorize a
study, trading, allocation, execution, policy mutation or holdout evaluation.
"""
from collections import defaultdict
from copy import deepcopy
from datetime import timedelta, timezone

from .decision_journal import _object, _identifier, _enum, _string, _hash
from .investment_review import _event_id, _fixed_boolean, disabled_authority
from .mission_request import ContractValidationError, parse_rfc3339, _validate_json_value
from .trading_accounting import accounting_timestamp
from .trading_reconciliation import _ReconciliationDocument, evidence_reference
from .trading_research import _universe, research_symbol
from .reconciled_action_intake import ACTION_TYPES, STATUSES, AUTHORITY, OVERLAY_VERSION
from .historical_intake import historical_date
from ..hashing import canonical_json_bytes, sha256_bytes

REQUEST_VERSION = "blackpod.reconciled_shadow_qualification_request.v1"
RESULT_VERSION = "blackpod.reconciled_shadow_qualification.v1"
METHOD_VERSION = RESULT_VERSION
REQUEST_CONSTANTS = {"schema_version": REQUEST_VERSION, "domain": "TRADING", "mode": "SHADOW_RESEARCH", "scope": "RECONCILED_OVERLAY_QUALIFICATION_ONLY"}
REQUEST_FIELDS = set(REQUEST_CONSTANTS) | {"qualification_id", "recorded_at", "data_cutoff_at", "intake_event_id", "intake_result_evidence", "supersedes_event_id", "auto_trading_enabled", "authority"}
ROLES = ("FEATURE", "ENTRY", "HOLDING_EXIT", "UNKNOWN")
MAX_OPPORTUNITIES = 10000
MAX_BOUNDARIES = 30000
MAX_COMPARISONS = 2_000_000
MAX_RESULT_BYTES = 16 * 1024 * 1024
FALSE_FIELDS = {"eligible_for_study_design", "coverage_complete", "coverage_supported", "eligible_for_shadow_study", "existing_gate_override", "native_gate_override", "old_masks_modified", "prices_adjusted", "returns_computed", "costs_computed", "holdout_scored", "strategy_tuning_performed", "economic_hypothesis_supported", "uncertainty_computed", "source_authentication_verified", "historical_point_in_time_verified", "auto_trading_enabled"}
COUNT_FIELDS = {"opportunities", "native_candidate_eligible", "native_benchmark_eligible", "native_combined_eligible", "native_joint_eligible", "candidate_overlay_veto", "benchmark_overlay_veto", "additional_overlay_veto", "overlay_clear", "newly_ineligible_due_to_overlay", "newly_ineligible", "effective_candidate_eligible", "effective_benchmark_eligible", "effective_combined_eligible", "effective_joint_eligible", "deferred", "risk_checks_matched"}
LIMITATIONS = (
    "SEPARATE_SHADOW_CONSUMER_ORIGINAL_NATIVE_QUALIFICATION_AND_MASKS_UNCHANGED",
    "CURRENT_RECONCILED_COVERAGE_AND_STUDY_ELIGIBILITY_REMAIN_FALSE_ALL_EFFECTIVE_WINDOWS_DEFER",
    "BOUNDARY_WITNESSES_ARE_DECLARATIONS_NOT_INDEPENDENT_ECONOMIC_EVENTS_OR_CONFIRMED_PAYMENTS",
    "OVERLAY_VETO_COUNT_INCLUDES_ALREADY_NATIVE_DEFERRED_WINDOWS_NOT_NEWLY_INELIGIBLE_TRADES",
    "UNKNOWN_NONCANCELLED_DATES_VETO_ALL_AFFECTED_WINDOWS_AND_FIXED_UNIVERSE_CONTROLS",
    "CANCELLED_UNKNOWN_OR_KNOWN_DATES_RETAINED_BUT_INACTIVE_WITHOUT_ELIGIBILITY_PROMOTION",
    "NATIVE_CLOCK_FAILURES_AND_OUT_OF_TEST_EXIT_METADATA_RETAINED_WITHOUT_DROPPING_WINDOWS",
    "NO_PRICES_SIGNALS_SIZING_COSTS_RETURNS_UNCERTAINTY_OR_POLICY_RULES_RECALCULATED",
    "FINAL_HOLDOUT_WITHHELD_UNSCORED_NOT_ACCESS_SEALED",
    "RETROSPECTIVE_BOUNDARY_RECONCILIATION_NOT_HISTORICAL_KNOWN_TIME_PROOF",
)
GATE_REASONS = ("RECONCILED_INTAKE_COVERAGE_UNRESOLVED", "RECONCILED_INTAKE_NOT_STUDY_ELIGIBLE", "SHADOW_OVERLAY_DIAGNOSTICS_NOT_REQUALIFIED_NATIVE_INPUTS")


def _constant(row, field, expected):
    if type(row[field]) is not type(expected) or row[field] != expected:
        raise ContractValidationError(field + " differs from the fixed reconciled shadow contract")


def _list(value, label, maximum=MAX_OPPORTUNITIES):
    if not isinstance(value, list) or len(value) > maximum:
        raise ContractValidationError(label + " requires a bounded explicit list")
    return value


def _texts(value, label, maximum=128):
    result = [_string(item, label, 10000) for item in _list(value, label, maximum)]
    if len(result) != len(set(result)): raise ContractValidationError(label + " contains duplicates")
    return result


def _ids(value, label):
    result = [_identifier(item, label) for item in _list(value, label, MAX_BOUNDARIES)]
    if result != sorted(set(result)): raise ContractValidationError(label + " must be sorted and distinct")
    return result


def _integer(value, label, lower=0, upper=1000000):
    if type(value) is not int or not lower <= value <= upper: raise ContractValidationError(label + " is outside its integer bound")
    return value


def _boolean(value, label):
    if type(value) is not bool: raise ContractValidationError(label + " requires a boolean")
    return value


def _request(value):
    row = _object(value, REQUEST_FIELDS, "reconciled shadow qualification request")
    for key, expected in REQUEST_CONSTANTS.items(): _constant(row, key, expected)
    row["qualification_id"] = _identifier(row["qualification_id"], "qualification_id")
    for key in ("recorded_at", "data_cutoff_at"): row[key] = accounting_timestamp(row[key], key)
    if parse_rfc3339(row["data_cutoff_at"], "cutoff") > parse_rfc3339(row["recorded_at"], "record clock"):
        raise ContractValidationError("shadow qualification cutoff cannot follow its record clock")
    row["intake_event_id"] = _event_id(row["intake_event_id"], "intake event")
    row["intake_result_evidence"] = evidence_reference(row["intake_result_evidence"], "exact intake result")
    if not 0 < row["intake_result_evidence"]["size_bytes"] <= 8 * 1024 * 1024: raise ContractValidationError("intake result exceeds retained bound")
    if row["supersedes_event_id"] is not None: row["supersedes_event_id"] = _event_id(row["supersedes_event_id"], "superseded qualification")
    _fixed_boolean(row, "auto_trading_enabled", False); row["authority"] = disabled_authority(row["authority"])
    return row


class ReconciledShadowQualificationRequest(_ReconciliationDocument):
    __slots__ = ()
    _validator = staticmethod(_request)


def evidence_references(request):
    request = request if isinstance(request, ReconciledShadowQualificationRequest) else ReconciledShadowQualificationRequest.from_mapping(request)
    return [request.intake_result_evidence]


NATIVE_WINDOW_FIELDS = {"fold_id", "symbol", "source_session_index", "source_session_id", "feature_start_index", "entry_session_index", "exit_session_index", "decision_at", "window_status", "candidate_eligible", "benchmark_eligible", "combined_eligible", "reason_codes", "candidate_action_ids", "benchmark_action_ids", "source_clock_reasons"}


def validate_native_continuity(value, universe, sessions=None, fold_ids=None):
    """Validate every original window without reading any bar/price value.

    Deferred negative lookback and unavailable exits are legitimate historical
    metadata. Their original clock reasons and booleans must survive unchanged.
    """
    row = _object(value, {"method_version", "continuity_policy", "status", "reason_codes", "coverage_supported", "native_continuity_review_status", "opportunities", "counts", "native_action_audit", "final_holdout", "price_policy", "limitations"}, "original native continuity")
    _constant(row, "method_version", "blackpod.event_aware_continuity_qualification.v1")
    _constant(row, "continuity_policy", "RAW_PRICE_BOUNDARY_SUSPENSION_NO_ADJUSTMENT")
    _constant(row, "price_policy", "RAW_UNMODIFIED_NO_REINDEX")
    _boolean(row["coverage_supported"], "native coverage")
    _texts(row["reason_codes"], "native continuity reasons"); _texts(row["limitations"], "native limitations")
    if row["native_continuity_review_status"] is not None: _string(row["native_continuity_review_status"], "native review status", 128)
    windows = _list(row["opportunities"], "native opportunities")
    if not windows: raise ContractValidationError("native opportunity inventory cannot be empty")
    audit_ids = set()
    for action in _list(row["native_action_audit"], "original native audit", 10000):
        if not isinstance(action, dict): raise ContractValidationError("original native action audit must retain objects")
        identity = _identifier(action.get("native_id"), "original native action id")
        if identity in audit_ids: raise ContractValidationError("original native action audit duplicates an identity")
        audit_ids.add(identity)
    identities, groups, horizons = set(), defaultdict(set), set()
    by_fold = defaultdict(set)
    for item in windows:
        item = _object(item, NATIVE_WINDOW_FIELDS, "original native opportunity")
        for key in ("fold_id", "source_session_id"): _identifier(item[key], key)
        symbol = research_symbol(item["symbol"])
        if symbol not in universe: raise ContractValidationError("native opportunity symbol changes original universe")
        source = _integer(item["source_session_index"], "source index", 0, 999999)
        feature = _integer(item["feature_start_index"], "feature index", -10000, 999999)
        entry = _integer(item["entry_session_index"], "entry index", 1, 1000000)
        exit_at = _integer(item["exit_session_index"], "exit index", 2, 1010000)
        if not feature < source or entry != source + 1 or not entry < exit_at:
            raise ContractValidationError("native window feature/entry/horizon relations are invalid")
        horizons.add((source-feature, exit_at-entry))
        identity = item["fold_id"], symbol, item["source_session_id"]
        if identity in identities: raise ContractValidationError("duplicate original native opportunity")
        identities.add(identity); groups[(item["fold_id"], source, item["source_session_id"])].add(symbol); by_fold[item["fold_id"]].add(source)
        for key in ("candidate_eligible", "benchmark_eligible", "combined_eligible"): _boolean(item[key], key)
        if item["combined_eligible"] != (item["candidate_eligible"] and item["benchmark_eligible"]): raise ContractValidationError("native candidate/control eligibility disagrees")
        _constant(item, "window_status", "ELIGIBLE_WINDOW_ONLY" if item["combined_eligible"] else "DEFER")
        _texts(item["reason_codes"], "original window reasons"); _texts(item["source_clock_reasons"], "original clock reasons")
        roles = _object(item["candidate_action_ids"], set(ROLES), "native role identities")
        for role in ROLES:
            if not set(_ids(roles[role], "native role ids")) <= audit_ids: raise ContractValidationError("native role contains an unretained action identity")
        if not set(_ids(item["benchmark_action_ids"], "native benchmark ids")) <= audit_ids: raise ContractValidationError("native control contains an unretained action identity")
        accounting_timestamp(item["decision_at"], "native decision clock")
        if feature < 0 and ("INSUFFICIENT_COMPLETED_FEATURE_LOOKBACK" not in item["source_clock_reasons"] or item["combined_eligible"]): raise ContractValidationError("negative feature history must remain deferred with its original reason")
        if sessions is not None:
            if source >= len(sessions) or sessions[source]["session_id"] != item["source_session_id"]: raise ContractValidationError("native source index/session identity is invalid")
            decision = parse_rfc3339(sessions[source]["available_at"], "source availability") + timedelta(microseconds=1)
            if parse_rfc3339(item["decision_at"], "native decision") != decision: raise ContractValidationError("native decision clock differs from completed source session")
            if entry >= len(sessions) and ("ENTRY_RETURNED_CALENDAR_SESSION_UNAVAILABLE" not in item["source_clock_reasons"] or item["combined_eligible"]): raise ContractValidationError("unavailable native entry cannot become eligible")
            if exit_at >= len(sessions) and (not any(reason in item["source_clock_reasons"] for reason in ("DECLARED_EXIT_OUTSIDE_ORIGINAL_TEST", "EXIT_RETURNED_CALENDAR_SESSION_UNAVAILABLE")) or item["combined_eligible"]): raise ContractValidationError("unavailable native exit cannot become eligible")
    if len(horizons) != 1: raise ContractValidationError("one frozen native hypothesis must retain its fixed lookback and holding horizon")
    if any(symbols != set(universe) for symbols in groups.values()): raise ContractValidationError("native source-session inventory omits a fixed universe constituent")
    for values in by_fold.values():
        if len(values) != max(values)-min(values)+1: raise ContractValidationError("native TEST opportunities cannot omit source sessions")
    if fold_ids is not None and set(by_fold) != set(fold_ids): raise ContractValidationError("native opportunity fold inventory differs from original calibration")
    counts = {"opportunities": len(windows), "candidate_eligible": sum(item["candidate_eligible"] for item in windows), "benchmark_eligible": sum(item["benchmark_eligible"] for item in windows), "combined_eligible": sum(item["combined_eligible"] for item in windows), "deferred": sum(not item["combined_eligible"] for item in windows)}
    if _object(row["counts"], set(counts), "native opportunity counts") != counts or any(type(row["counts"][key]) is not int for key in counts): raise ContractValidationError("native opportunity counts differ from complete inventory")
    _constant(row, "status", "ELIGIBLE_WINDOWS_ONLY" if counts["combined_eligible"] else "DEFER")
    holdout = _object(row["final_holdout"], {"start_index", "end_index", "scoring_status", "access_sealed"}, "original withheld holdout")
    _integer(holdout["start_index"], "holdout start"); _integer(holdout["end_index"], "holdout end")
    if holdout["end_index"] < holdout["start_index"]: raise ContractValidationError("native holdout interval is reversed")
    _constant(holdout, "scoring_status", "WITHHELD"); _constant(holdout, "access_sealed", False)
    if any(item["entry_session_index"] >= holdout["start_index"] for item in windows): raise ContractValidationError("native TEST source inventory enters final holdout")
    if sessions is not None and holdout["end_index"] >= len(sessions): raise ContractValidationError("native final holdout is outside returned dataset")
    _list(row["native_action_audit"], "original native audit", 10000)
    _validate_json_value(row["native_action_audit"], "original native audit")
    return row


def validate_catalog(value):
    row = _object(value, {"schema_version", "status", "boundaries", "unknown_date_scope", "coverage_complete", "eligible_for_shadow_study", "native_gate_override"}, "exact reconciled boundary catalog")
    _constant(row, "schema_version", OVERLAY_VERSION); _constant(row, "status", "NOT_ELIGIBLE_COVERAGE_UNRESOLVED")
    for key in ("coverage_complete", "eligible_for_shadow_study", "native_gate_override"): _fixed_boolean(row, key, False)
    identities, sources = set(), set()
    for item in _list(row["boundaries"], "reconciled boundary catalog", MAX_BOUNDARIES):
        item = _object(item, {"boundary_id", "origin", "source_id", "native_type", "affected_symbols", "declared_effective_date", "mapped_session_id", "mapped_session_index", "mapping", "source_status", "boundary_flag", "legacy_placeholder_retained", "eligible", "confirmed_payment"}, "reconciled boundary")
        for key in ("boundary_id", "source_id"): _identifier(item[key], key)
        origin = _enum(item["origin"], {"NATIVE", "ISSUER_DECLARATION"}, "boundary origin")
        if item["boundary_id"] in identities or (origin, item["source_id"]) in sources: raise ContractValidationError("reconciled catalog duplicates an identity")
        identities.add(item["boundary_id"]); sources.add((origin, item["source_id"]))
        expected = "reconciled-boundary-" + sha256_bytes(canonical_json_bytes({"origin": origin, "source_id": item["source_id"]}))
        if item["boundary_id"] != expected: raise ContractValidationError("reconciled boundary identity differs")
        _enum(item["native_type"], set(ACTION_TYPES), "boundary action type"); _universe(item["affected_symbols"])
        mapping = _enum(item["mapping"], {"UNKNOWN_EFFECTIVE_DATE", "BEFORE_DATASET", "AFTER_DATASET", "EXACT_RETURNED_DATE", "NEXT_RETURNED_DATE"}, "boundary mapping")
        if item["declared_effective_date"] is not None: historical_date(item["declared_effective_date"], "declared effective date")
        if (item["declared_effective_date"] is None) != (mapping == "UNKNOWN_EFFECTIVE_DATE"): raise ContractValidationError("unknown boundary cannot gain an inferred date")
        mapped = mapping in {"EXACT_RETURNED_DATE", "NEXT_RETURNED_DATE"}
        if (item["mapped_session_id"] is not None) != mapped or (item["mapped_session_index"] is not None) != mapped: raise ContractValidationError("boundary index/session must agree with mapping")
        if mapped: _identifier(item["mapped_session_id"], "mapped session"); _integer(item["mapped_session_index"], "mapped session index")
        _enum(item["source_status"], {"NATIVE_STATUS_UNAVAILABLE"} if origin == "NATIVE" else STATUSES, "source status")
        _constant(item, "boundary_flag", mapped and item["source_status"] != "CANCELLED")
        _constant(item, "legacy_placeholder_retained", origin == "NATIVE" and mapping == "UNKNOWN_EFFECTIVE_DATE")
        for key in ("eligible", "confirmed_payment"): _fixed_boolean(item, key, False)
    expected_unknown = [{"origin": item["origin"], "source_id": item["source_id"], "affected_symbols": item["affected_symbols"], "reason": "UNKNOWN_EFFECTIVE_DATE_NO_INVENTED_BOUNDARY"} for item in row["boundaries"] if item["declared_effective_date"] is None]
    if row["unknown_date_scope"] != expected_unknown: raise ContractValidationError("catalog must retain every unknown-date declaration including cancelled rows")
    return row


def risk_checks(snapshot, windows):
    risk = _object(snapshot["risk"], {"eligible", "reason_codes", "native_assessment", "capacity_checks"}, "unchanged native risk")
    _boolean(risk["eligible"], "native risk eligible"); _texts(risk["reason_codes"], "native risk reasons")
    if risk["native_assessment"] is not None and not isinstance(risk["native_assessment"], dict): raise ContractValidationError("native risk assessment requires an object or null")
    checks, result = _list(risk["capacity_checks"], "native capacity checks"), {}
    expected = set()
    for item in windows:
        if not isinstance(item, dict): raise ContractValidationError("native risk source window requires an object")
        key = (_identifier(item.get("fold_id"), "native window fold id"), research_symbol(item.get("symbol")),
            _identifier(item.get("source_session_id"), "native window source session id"))
        if key in expected: raise ContractValidationError("native risk source windows duplicate an identity")
        expected.add(key)
    for item in checks:
        item = _object(item, {"fold_id", "symbol", "source_session_id", "whole_quantity", "maximum_daily_proxy_quantity", "within_daily_proxy", "known_close_feasible", "continuity_comparable", "joint_eligible", "native_reason_codes", "opening_fill_capacity_verified"}, "native capacity intersection")
        key = (_identifier(item["fold_id"], "capacity fold id"), research_symbol(item["symbol"]),
            _identifier(item["source_session_id"], "capacity source session id"))
        if key not in expected or key in result: raise ContractValidationError("native capacity checks require distinct exact source-window keys")
        for field in ("within_daily_proxy", "known_close_feasible", "continuity_comparable", "joint_eligible"): _boolean(item[field], field)
        if item["joint_eligible"] != (item["within_daily_proxy"] and item["known_close_feasible"] and item["continuity_comparable"]): raise ContractValidationError("original risk intersection booleans disagree")
        _fixed_boolean(item, "opening_fill_capacity_verified", False)
        _string(item["whole_quantity"], "original whole quantity", 128)
        if item["maximum_daily_proxy_quantity"] is not None: _string(item["maximum_daily_proxy_quantity"], "original daily capacity proxy", 128)
        _texts(item["native_reason_codes"], "native sizing reasons")
        result[key] = item["joint_eligible"]
    if checks and set(result) != expected: raise ContractValidationError("native capacity inventory omits original windows")
    return result


def project_windows(snapshot, catalog):
    """Integer/date-free overlay intersection, shared with strict result replay."""
    windows = snapshot["continuity"]["opportunities"]
    boundaries = catalog["boundaries"]
    if len(windows) * len(boundaries) > MAX_COMPARISONS: raise ContractValidationError("reconciled window-boundary comparisons exceed fixed bound")
    universe = {item["symbol"] for item in windows}
    risk = risk_checks(snapshot, windows)
    result = []
    gate = catalog["coverage_complete"] and catalog["eligible_for_shadow_study"]
    for original in windows:
        candidate, benchmark = {role: [] for role in ROLES}, []
        feature, source, entry, exit_at = (original[key] for key in ("feature_start_index", "source_session_index", "entry_session_index", "exit_session_index"))
        for boundary in boundaries:
            if boundary["source_status"] == "CANCELLED": continue
            affected = set(boundary["affected_symbols"])
            identity = boundary["boundary_id"]
            if boundary["mapping"] == "UNKNOWN_EFFECTIVE_DATE":
                if original["symbol"] in affected: candidate["UNKNOWN"].append(identity)
                if affected & universe: benchmark.append(identity)
                continue
            if not boundary["boundary_flag"]: continue
            index = boundary["mapped_session_index"]
            if original["symbol"] in affected:
                role = "FEATURE" if feature < index <= source else "ENTRY" if source < index <= entry else "HOLDING_EXIT" if entry < index <= exit_at else None
                if role is not None: candidate[role].append(identity)
            if affected & universe and source < index <= exit_at: benchmark.append(identity)
        candidate = {role: sorted(values) for role, values in candidate.items()}; benchmark.sort()
        candidate_veto, benchmark_veto = any(candidate.values()), bool(benchmark)
        candidate_ok, benchmark_ok = gate and not candidate_veto, gate and not benchmark_veto
        effective_candidate = original["candidate_eligible"] and candidate_ok
        effective_benchmark = original["benchmark_eligible"] and benchmark_ok
        effective = effective_candidate and effective_benchmark
        key = original["fold_id"], original["symbol"], original["source_session_id"]
        joint = risk.get(key)
        reasons = set(original["reason_codes"]) | set(GATE_REASONS)
        for role in ROLES:
            if candidate[role]: reasons.add("RECONCILED_CANDIDATE_" + role + "_BOUNDARY")
        if benchmark_veto: reasons.add("RECONCILED_FIXED_UNIVERSE_CONTROL_BOUNDARY_OR_UNKNOWN_DATE")
        result.append({"native_opportunity": deepcopy(original), "overlay_candidate_boundary_ids": candidate, "overlay_benchmark_boundary_ids": benchmark,
            "overlay_candidate_veto": candidate_veto, "overlay_benchmark_veto": benchmark_veto, "additional_overlay_veto": candidate_veto or benchmark_veto,
            "native_candidate_eligible": original["candidate_eligible"], "native_benchmark_eligible": original["benchmark_eligible"], "native_combined_eligible": original["combined_eligible"],
            "overlay_candidate_eligible": candidate_ok, "overlay_benchmark_eligible": benchmark_ok,
            "effective_candidate_eligible": effective_candidate, "effective_benchmark_eligible": effective_benchmark, "effective_combined_eligible": effective,
            "risk_joint_eligible": joint, "effective_joint_eligible": effective and joint is True,
            "window_status": "ELIGIBLE_WINDOW_ONLY" if effective else "DEFER", "reason_codes": sorted(reasons)})
    counts = {"opportunities": len(result), "native_candidate_eligible": sum(item["native_candidate_eligible"] for item in result), "native_benchmark_eligible": sum(item["native_benchmark_eligible"] for item in result),
        "native_combined_eligible": sum(item["native_combined_eligible"] for item in result), "native_joint_eligible": sum(item["risk_joint_eligible"] is True for item in result),
        "candidate_overlay_veto": sum(item["overlay_candidate_veto"] for item in result), "benchmark_overlay_veto": sum(item["overlay_benchmark_veto"] for item in result),
        "additional_overlay_veto": sum(item["additional_overlay_veto"] for item in result), "overlay_clear": sum(not item["additional_overlay_veto"] for item in result),
        "newly_ineligible_due_to_overlay": sum(item["native_combined_eligible"] and item["additional_overlay_veto"] for item in result),
        "newly_ineligible": sum(item["native_combined_eligible"] and not item["effective_combined_eligible"] for item in result),
        "effective_candidate_eligible": sum(item["effective_candidate_eligible"] for item in result), "effective_benchmark_eligible": sum(item["effective_benchmark_eligible"] for item in result),
        "effective_combined_eligible": sum(item["effective_combined_eligible"] for item in result), "effective_joint_eligible": sum(item["effective_joint_eligible"] for item in result),
        "deferred": sum(not item["effective_combined_eligible"] for item in result), "risk_checks_matched": len(risk)}
    return result, counts


INPUT_BINDING_FIELDS = {"intake_event_id", "intake_id", "intake_result_evidence", "intake_policy_id", "intake_policy_evidence", "dataset_evidence", "original_native_masks_evidence", "native_qualification_id", "native_binding_id", "native_policy_id", "native_snapshot_sha256"}
RESULT_FIELDS = {"schema_version", "method_version", "qualification_id", "recorded_at", "data_cutoff_at", "status", "input_bindings", "native_qualification_snapshot", "boundary_catalog", "coverage_matrix", "opportunities", "counts", "reason_codes", "limitations", "final_holdout", "execution_status", "realized_trade_pnl", "authority"} | FALSE_FIELDS


def validate_result(value):
    from .segmented_evidence_qualification import validate_result as validate_native
    row = _object(value, RESULT_FIELDS, "reconciled shadow qualification result")
    for field, expected in (("schema_version", RESULT_VERSION), ("method_version", METHOD_VERSION), ("status", "DEFER_RECONCILED_SHADOW_QUALIFICATION"), ("execution_status", "NOT_EXECUTED"), ("realized_trade_pnl", None)): _constant(row, field, expected)
    _identifier(row["qualification_id"], "qualification id")
    for field in ("recorded_at", "data_cutoff_at"): accounting_timestamp(row[field], field)
    if parse_rfc3339(row["data_cutoff_at"], "cutoff") > parse_rfc3339(row["recorded_at"], "record clock"): raise ContractValidationError("result cutoff follows record clock")
    for field in FALSE_FIELDS: _fixed_boolean(row, field, False)
    row["authority"] = disabled_authority(row["authority"])
    bindings = _object(row["input_bindings"], INPUT_BINDING_FIELDS, "exact reconciled shadow input bindings")
    _event_id(bindings["intake_event_id"], "selected intake")
    for field in ("intake_id", "intake_policy_id", "native_qualification_id", "native_binding_id", "native_policy_id"): _identifier(bindings[field], field)
    for field in ("intake_result_evidence", "intake_policy_evidence", "dataset_evidence", "original_native_masks_evidence"): evidence_reference(bindings[field], field)
    _hash(bindings["native_snapshot_sha256"], "native snapshot hash")
    native = validate_native(row["native_qualification_snapshot"])
    if bindings["native_snapshot_sha256"] != sha256_bytes(canonical_json_bytes(native)): raise ContractValidationError("original native snapshot hash differs")
    for field, source in (("native_qualification_id", "qualification_id"), ("native_binding_id", "binding_id"), ("native_policy_id", "policy_id")):
        if bindings[field] != native[source]: raise ContractValidationError("native qualification identity differs")
    if bindings["original_native_masks_evidence"]["sha256"] != sha256_bytes(canonical_json_bytes(native["continuity"])) or bindings["original_native_masks_evidence"]["size_bytes"] != len(canonical_json_bytes(native["continuity"])):
        raise ContractValidationError("native continuity snapshot differs from original mask reference")
    cells = _list(row["coverage_matrix"], "unchanged coverage matrix", 104)
    universe = sorted({item.get("symbol") for item in cells if isinstance(item, dict) and isinstance(item.get("symbol"), str)})
    _universe(universe)
    expected_cells = {(symbol, action_type) for symbol in universe for action_type in ACTION_TYPES}; actual_cells = []
    for cell in cells:
        cell = _object(cell, {"symbol", "action_type", "status", "coverage_complete", "eligible", "declared_source_inventory_ids", "observed_native_count", "observed_issuer_count", "unresolved_interval"}, "unchanged unresolved coverage cell")
        research_symbol(cell["symbol"]); _enum(cell["action_type"], set(ACTION_TYPES), "coverage action type")
        actual_cells.append((cell["symbol"], cell["action_type"])); _constant(cell, "status", "UNRESOLVED")
        for field in ("coverage_complete", "eligible"): _fixed_boolean(cell, field, False)
        _ids(cell["declared_source_inventory_ids"], "declared coverage inventories")
        for field in ("observed_native_count", "observed_issuer_count"): _integer(cell[field], field, 0, 30000)
        span = _object(cell["unresolved_interval"], {"start", "end"}, "unchanged unresolved coverage interval")
        for field in span: historical_date(span[field], field)
        if span["start"] > span["end"]: raise ContractValidationError("unresolved coverage interval is reversed")
    if len(actual_cells) != len(expected_cells) or set(actual_cells) != expected_cells: raise ContractValidationError("all original fixed symbol/type cells must remain unresolved")
    validate_native_continuity(native["continuity"], universe, fold_ids=[item["fold_id"] for item in native["training_calibration"]["folds"]])
    catalog = validate_catalog(row["boundary_catalog"])
    windows, counts = project_windows(native, catalog)
    _list(row["opportunities"], "complete shadow opportunities")
    if canonical_json_bytes(row["opportunities"]) != canonical_json_bytes(windows): raise ContractValidationError("shadow window projection must retain every native window and exact boundary witness")
    supplied_counts = _object(row["counts"], COUNT_FIELDS, "reconciled shadow counts")
    if any(type(supplied_counts[field]) is not int for field in COUNT_FIELDS) or supplied_counts != counts: raise ContractValidationError("shadow counts differ from complete window inventory")
    if canonical_json_bytes(row["final_holdout"]) != canonical_json_bytes(native["continuity"]["final_holdout"]): raise ContractValidationError("original holdout must remain unchanged and withheld")
    reasons = set(native["reason_codes"]) | set(GATE_REASONS) | {"NO_EFFECTIVE_RECONCILED_WINDOWS"}
    if counts["additional_overlay_veto"]: reasons.add("ADDITIONAL_RECONCILED_BOUNDARY_VETOES")
    if _texts(row["reason_codes"], "qualification reasons", 256) != sorted(reasons): raise ContractValidationError("native reasons or reconciled defer reasons were changed or omitted")
    _constant(row, "limitations", list(LIMITATIONS))
    if len(canonical_json_bytes(row)) > MAX_RESULT_BYTES: raise ContractValidationError("shadow qualification result exceeds byte bound")
    return row
