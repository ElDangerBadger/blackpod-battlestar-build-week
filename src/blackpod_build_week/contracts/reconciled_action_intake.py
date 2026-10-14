"""Frozen research-only action intake, separate from native continuity schemas.

An issuer observation is a declaration, not proof of payment or complete action
coverage. These documents cannot authorize execution or clear a native gate.
"""
from .decision_journal import _object, _identifier, _enum, _string, _hash
from .effective_date_reconciliation import ACTION_TYPES, _independent_action
from .historical_intake import historical_date
from .investment_review import _event_id, _fixed_boolean, disabled_authority
from .mission_request import ContractValidationError, parse_rfc3339, _validate_json_value
from .trading_accounting import accounting_timestamp
from .trading_reconciliation import _ReconciliationDocument, evidence_reference
from .trading_research import _universe
from ..hashing import canonical_json_bytes, sha256_bytes

POLICY_VERSION = "blackpod.reconciled_action_intake_policy.v1"
REQUEST_VERSION = "blackpod.reconciled_action_intake_request.v1"
RESULT_VERSION = "blackpod.reconciled_action_intake.v1"
METHOD_VERSION = RESULT_VERSION
OVERLAY_VERSION = "blackpod.reconciled_action_risk_overlay.v1"
AUTHORITY = {name: False for name in ("authorization_enabled", "capital_activation_enabled", "execution_enabled", "policy_changes_enabled")}
POLICY_CONSTANTS = {
    "schema_version": POLICY_VERSION, "domain": "TRADING", "mode": "SHADOW_RESEARCH",
    "scope": "RECONCILED_ACTION_INTAKE_POLICY_ONLY", "status": "FROZEN_FOR_SHADOW_INTAKE",
    "selection_policy": "ALL_ORIGINAL_NATIVE_AND_ALL_SELECTED_ISSUER_OBSERVATIONS",
    "match_policy": "EXACT_NATIVE_TYPE_EFFECTIVE_DATE_FULL_SYMBOL_SET",
    "date_policy": "FIRST_RETURNED_SESSION_ON_OR_AFTER_DECLARED_EFFECTIVE_DATE",
    "status_policy": "RETAIN_ALL_STATUSES_NO_PAYMENT_INFERENCE",
    "duplicate_policy": "RETAIN_ALL_AND_FLAG_NO_COLLAPSE",
    "conflict_policy": "RETAIN_ALL_NO_SOURCE_PRECEDENCE",
    "coverage_policy": "ALL_SYMBOL_ACTION_TYPE_CELLS_UNRESOLVED", "price_policy": "RAW_NO_ADJUSTMENT",
}
REQUEST_CONSTANTS = {"schema_version": REQUEST_VERSION, "domain": "TRADING", "mode": "SHADOW_RESEARCH", "scope": "RECONCILED_ACTION_INTAKE_ONLY"}
POLICY_FIELDS = set(POLICY_CONSTANTS) | {"policy_id", "recorded_at", "anchor_review_event_id", "dataset_evidence", "native_continuity_export_evidence", "original_native_masks_evidence", "independent_inventories", "evidence_scope", "auto_trading_enabled", "authority"}
REQUEST_FIELDS = set(REQUEST_CONSTANTS) | {"intake_id", "recorded_at", "data_cutoff_at", "policy_event_id", "policy_evidence", "supersedes_event_id", "auto_trading_enabled", "authority"}
STATUSES = {"EFFECTIVE", "SCHEDULED", "CANCELLED", "REVISED", "UNKNOWN", "LISTED_STATUS_UNSPECIFIED"}
FALSE_FIELDS = {"coverage_complete", "coverage_supported", "source_authentication_verified", "source_independence_verified", "historical_point_in_time_verified", "economic_hypothesis_supported", "uncertainty_computed", "confirmed_payment", "economic_truth_verified", "prices_adjusted", "returns_computed", "costs_computed", "old_masks_modified", "legacy_source_compatible", "eligible_for_shadow_study", "native_gate_override", "auto_trading_enabled"}
MAX_RESULT_BYTES = 8 * 1024 * 1024


def _constant(row, key, expected):
    if type(row[key]) is not type(expected) or row[key] != expected:
        raise ContractValidationError(key + " differs from the frozen reconciled action contract")


def _list(value, name, maximum=20000):
    if not isinstance(value, list) or len(value) > maximum:
        raise ContractValidationError(name + " requires a bounded explicit list")
    return value


def _texts(value, name, maximum=20000):
    rows = [_string(item, name, 10000) for item in _list(value, name, maximum)]
    if len(rows) != len(set(rows)):
        raise ContractValidationError(name + " contains duplicate values")
    return rows


def _ids(value, name):
    rows = [_identifier(item, name) for item in _list(value, name)]
    if rows != sorted(set(rows)):
        raise ContractValidationError(name + " must be sorted and distinct")
    return rows


def _count(value, name, maximum=2000000000):
    if type(value) is not int or not 0 <= value <= maximum:
        raise ContractValidationError(name + " requires a bounded nonnegative integer")
    return value


def _safe(row):
    _fixed_boolean(row, "auto_trading_enabled", False)
    row["authority"] = disabled_authority(row["authority"])
    return row


def _policy(value):
    row = _object(value, POLICY_FIELDS, "reconciled action intake policy")
    for key, expected in POLICY_CONSTANTS.items(): _constant(row, key, expected)
    row["policy_id"] = _identifier(row["policy_id"], "policy_id")
    row["recorded_at"] = accounting_timestamp(row["recorded_at"], "recorded_at")
    row["anchor_review_event_id"] = _event_id(row["anchor_review_event_id"], "anchor review")
    row["evidence_scope"] = _enum(row["evidence_scope"], {"SYNTHETIC_FIXTURE_ONLY", "RETAINED_HISTORY_RESEARCH"}, "evidence scope")
    for key in ("dataset_evidence", "native_continuity_export_evidence", "original_native_masks_evidence"):
        row[key] = evidence_reference(row[key], key)
        if not row[key]["size_bytes"]: raise ContractValidationError(key + " must not be empty")
    row["independent_inventories"] = [evidence_reference(ref, "inventory manifest") for ref in _list(row["independent_inventories"], "independent inventories", 16)]
    if not row["independent_inventories"]: raise ContractValidationError("at least one retained inventory is required")
    refs = [row[key] for key in ("dataset_evidence", "native_continuity_export_evidence", "original_native_masks_evidence")] + row["independent_inventories"]
    if len({ref["path"] for ref in refs}) != len(refs) or len({ref["sha256"] for ref in row["independent_inventories"]}) != len(row["independent_inventories"]):
        raise ContractValidationError("frozen source references require distinct paths and manifest identities")
    return _safe(row)


def _request(value):
    row = _object(value, REQUEST_FIELDS, "reconciled action intake request")
    for key, expected in REQUEST_CONSTANTS.items(): _constant(row, key, expected)
    row["intake_id"] = _identifier(row["intake_id"], "intake_id")
    for key in ("recorded_at", "data_cutoff_at"): row[key] = accounting_timestamp(row[key], key)
    if parse_rfc3339(row["data_cutoff_at"], "cutoff") > parse_rfc3339(row["recorded_at"], "record clock"):
        raise ContractValidationError("intake cutoff cannot follow its record clock")
    row["policy_event_id"] = _event_id(row["policy_event_id"], "policy event")
    row["policy_evidence"] = evidence_reference(row["policy_evidence"], "frozen policy")
    if row["supersedes_event_id"] is not None: row["supersedes_event_id"] = _event_id(row["supersedes_event_id"], "superseded intake")
    return _safe(row)


class ReconciledActionIntakePolicy(_ReconciliationDocument):
    __slots__ = ()
    _validator = staticmethod(_policy)


class ReconciledActionIntakeRequest(_ReconciliationDocument):
    __slots__ = ()
    _validator = staticmethod(_request)


def evidence_references(policy, request=None):
    """Direct immutable leaves; inventory/native children are traversed by readers."""
    policy = policy if isinstance(policy, ReconciledActionIntakePolicy) else ReconciledActionIntakePolicy.from_mapping(policy)
    refs = [policy.dataset_evidence, policy.native_continuity_export_evidence, policy.original_native_masks_evidence, *policy.independent_inventories]
    if request is not None:
        request = request if isinstance(request, ReconciledActionIntakeRequest) else ReconciledActionIntakeRequest.from_mapping(request)
        refs = [request.policy_evidence, *refs]
    return refs


def _key(row):
    return row["native_type"], row["effective_date"], tuple(row["affected_symbols"])


def _key_fields(row):
    _enum(row["native_type"], set(ACTION_TYPES), "native type")
    historical_date(row["effective_date"], "effective date")
    _universe(row["affected_symbols"])


def _qqq_amount(value):
    """Exact JSON numeric tokens from this source profile, never binary floats."""
    if value is None: return None
    import re
    from decimal import Decimal, InvalidOperation, localcontext
    if type(value) is not str or len(value) > 128 or not re.fullmatch(r"-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?", value):
        raise ContractValidationError("QQQ amount requires a literal bounded JSON number token")
    try:
        with localcontext() as context:
            context.prec = 160
            number = Decimal(value)
            if not number.is_finite() or number < 0 or number > Decimal("1e20"):
                raise ContractValidationError("QQQ source amount is outside its bounded nonnegative profile")
    except InvalidOperation as exc:
        raise ContractValidationError("QQQ source amount token is invalid") from exc
    return value


def _observation(value):
    fields = {"independent_action_id", "inventory_id", "source_action_id", "native_type", "affected_symbols", "effective_date", "record_date", "payable_date", "status", "cusip", "amount_lexemes", "replaces_source_action_id", "provenance", "dataset_disposition"}
    row = _object(value, fields, "retained issuer observation")
    if not isinstance(row["provenance"], dict): raise ContractValidationError("observation provenance requires an object")
    if "native_row" not in row["provenance"]:
        return _independent_action(row)
    # QQQ provenance is a separate profile, never relabeled as frozen v22 data.
    for key in ("independent_action_id", "inventory_id", "source_action_id"): _identifier(row[key], key)
    _constant(row, "native_type", "cash_dividends"); _constant(row, "affected_symbols", ["QQQ"])
    for key in ("effective_date", "record_date", "payable_date"): historical_date(row[key], key)
    _constant(row, "status", "LISTED_STATUS_UNSPECIFIED"); _constant(row, "cusip", "46090E103")
    _constant(row, "replaces_source_action_id", None)
    _enum(row["dataset_disposition"], {"IN_DATASET", "BEFORE_DATASET", "AFTER_DATASET"}, "dataset disposition")
    amounts = _object(row["amount_lexemes"], {"dividend", "short_term_capital_gain", "long_term_capital_gain"}, "raw amounts")
    for amount in amounts.values(): _qqq_amount(amount)
    provenance = _object(row["provenance"], {"body_evidence", "value_pointer", "row_sha256", "native_row", "native_row_number_encoding", "native_row_hash_basis"}, "QQQ row provenance")
    evidence_reference(provenance["body_evidence"]); _hash(provenance["row_sha256"], "row hash")
    import re
    if not isinstance(provenance["value_pointer"], str) or not re.fullmatch(r"/distributions/(?:0|[1-9][0-9]{0,3})", provenance["value_pointer"]):
        raise ContractValidationError("QQQ row pointer is malformed")
    _constant(provenance, "native_row_number_encoding", "JSON_NUMBER_TOKENS_AS_STRINGS")
    _constant(provenance, "native_row_hash_basis", "SHA256_CANONICAL_JSON_WITH_NUMERIC_TOKEN_STRINGS")
    from ..qqq_distribution_inventory import ROW_FIELDS, DATE_FIELDS
    native = _object(provenance["native_row"], ROW_FIELDS, "QQQ literal source row")
    for key in DATE_FIELDS: historical_date(native[key], key)
    for key in ROW_FIELDS - DATE_FIELDS: _qqq_amount(native[key])
    if native["distributionAmountPerUnit"] is None: raise ContractValidationError("QQQ distribution-per-unit amount is required")
    if provenance["row_sha256"] != sha256_bytes(canonical_json_bytes(native)):
        raise ContractValidationError("QQQ row hash differs from retained token strings")
    expected = {"effective_date": native["exDate"], "record_date": native["recordDate"], "payable_date": native["payDate"], "amount_lexemes": {"dividend": native["distributionAmountPerUnit"], "short_term_capital_gain": native["shortTermCapitalGainsDistribution"], "long_term_capital_gain": native["longTermCapitalGainsDistribution"]}}
    if any(row[key] != expected[key] for key in expected): raise ContractValidationError("QQQ normalized observation differs from original source row")
    return row


def validate_result(value):
    fields = {"schema_version", "method_version", "intake_id", "policy_id", "policy_evidence", "status", "dataset_evidence", "native_continuity_export_evidence", "universe", "effective_span", "original_native_masks", "original_native_export", "original_native_events", "source_inventories", "issuer_observations", "matches", "native_only", "issuer_only", "ambiguous", "duplicate_groups", "conflicts", "candidate_overlay", "coverage_matrix", "reason_codes", "limitations", "execution_status", "realized_trade_pnl", "authority"} | FALSE_FIELDS
    row = _object(value, fields, "reconciled action intake result")
    for key, expected in (("schema_version", RESULT_VERSION), ("method_version", METHOD_VERSION), ("status", "SHADOW_CANDIDATE_NOT_ELIGIBLE"), ("execution_status", "NOT_EXECUTED"), ("realized_trade_pnl", None)):
        _constant(row, key, expected)
    for key in FALSE_FIELDS: _fixed_boolean(row, key, False)
    row["authority"] = disabled_authority(row["authority"])
    for key in ("intake_id", "policy_id"): _identifier(row[key], key)
    for key in ("policy_evidence", "dataset_evidence", "native_continuity_export_evidence"): evidence_reference(row[key], key)
    universe = _universe(row["universe"])
    span = _object(row["effective_span"], {"start", "end"}, "effective span")
    for key in span: historical_date(span[key], key)
    if span["start"] > span["end"]: raise ContractValidationError("effective span is reversed")
    masks = _object(row["original_native_masks"], {"evidence", "sha256", "assessment"}, "unchanged original masks")
    evidence_reference(masks["evidence"]); _hash(masks["sha256"], "masks hash")
    if not isinstance(masks["assessment"], dict): raise ContractValidationError("original masks must retain an object")
    _validate_json_value(masks["assessment"], "original masks")
    if sha256_bytes(canonical_json_bytes(masks["assessment"])) != masks["sha256"] or masks["evidence"]["sha256"] != masks["sha256"]:
        raise ContractValidationError("original mask fragment hash differs")
    if masks["evidence"]["size_bytes"] != len(canonical_json_bytes(masks["assessment"])): raise ContractValidationError("original mask fragment size differs")
    from .trading_continuity_intake import ContinuityIntakeExport
    export = ContinuityIntakeExport.from_mapping(row["original_native_export"])
    if export.dataset_evidence != row["dataset_evidence"]: raise ContractValidationError("original export binds another dataset")
    events = _list(row["original_native_events"], "original native events", 10000)
    for event in events:
        event = _object(event, {"event_id", "symbol", "effective_session_id", "kind"}, "unchanged original event")
        for key in ("event_id", "effective_session_id"): _identifier(event[key], key)
        from .trading_research import research_symbol
        research_symbol(event["symbol"])
        _enum(event["kind"], {"SPLIT", "CASH_DISTRIBUTION", "STOCK_DISTRIBUTION", "MERGER", "SYMBOL_CHANGE", "OTHER_PRICE_DISCONTINUITY"}, "native kind")
    if len(events) != export.derived_event_count: raise ContractValidationError("original native event count differs")
    from ..trading_continuity_intake import _SCHEMAS
    expected_events = []
    for action in export.native_actions: _enum(action["native_type"], set(ACTION_TYPES), "original native action type")
    if export.status != "UNAVAILABLE":
        for action in export.native_actions:
            if action["mapped_session_id"] is not None:
                for symbol in sorted(set(action["affected_symbols"]) & set(universe)):
                    expected_events.append({"event_id": "alpaca-action-" + action["native_id"] + "-" + symbol, "symbol": symbol,
                        "effective_session_id": action["mapped_session_id"], "kind": _SCHEMAS[action["native_type"]][2]})
    if events != sorted(expected_events, key=lambda item: item["event_id"]): raise ContractValidationError("original native events differ from retained audit and aliases")
    inventory_ids = set()
    inventory_by_id = {}
    from .effective_date_reconciliation import IndependentActionInventory
    from .qqq_distribution_inventory import QQQDistributionInventory, VERSION as QQQ_VERSION
    for source in _list(row["source_inventories"], "source inventories", 16):
        source = _object(source, {"manifest_evidence", "inventory", "source_scope", "rows_scanned", "observed_action_count", "completeness_verified", "source_authentication_verified"}, "retained inventory")
        evidence_reference(source["manifest_evidence"])
        if not isinstance(source["inventory"], dict): raise ContractValidationError("retained inventory must be an object")
        klass = QQQDistributionInventory if source["inventory"].get("schema_version") == QQQ_VERSION else IndependentActionInventory
        inventory = klass.from_mapping(source["inventory"])
        if inventory.inventory_id in inventory_ids: raise ContractValidationError("duplicate inventory identity")
        inventory_ids.add(inventory.inventory_id); inventory_by_id[inventory.inventory_id] = inventory
        _enum(source["source_scope"], {"LISTED_SSGA_CASH_DISTRIBUTIONS_ONLY", "AUTHORED_UNVERIFIED_INVENTORY_ONLY", "LISTED_INVESCO_QQQ_DISTRIBUTIONS_ONLY"}, "source scope")
        for key in ("rows_scanned", "observed_action_count"): _count(source[key], key)
        expected_scope = {"SSGA_HISTORICAL_DISTRIBUTIONS_XLSX_V1": "LISTED_SSGA_CASH_DISTRIBUTIONS_ONLY", "AUTHORED_EFFECTIVE_DATE_ACTIONS_JSON_V1": "AUTHORED_UNVERIFIED_INVENTORY_ONLY", "INVESCO_QQQ_DISTRIBUTIONS_JSON_V1": "LISTED_INVESCO_QQQ_DISTRIBUTIONS_ONLY"}[inventory.profile]
        _constant(source, "source_scope", expected_scope)
        if source["rows_scanned"] < source["observed_action_count"]: raise ContractValidationError("source row count cannot omit retained observations")
        for key in ("completeness_verified", "source_authentication_verified"): _fixed_boolean(source, key, False)
    observations = [_observation(item) for item in _list(row["issuer_observations"], "issuer observations")]
    ids = [item["independent_action_id"] for item in observations]
    if len(ids) != len(set(ids)): raise ContractValidationError("duplicate observation identity")
    for item in observations:
        inventory = inventory_by_id.get(item["inventory_id"])
        if inventory is None or item["provenance"]["body_evidence"] != inventory.body_evidence: raise ContractValidationError("observation binds an unselected source")
        expected = "independent-action-" + sha256_bytes(canonical_json_bytes({"inventory_id": item["inventory_id"], "source_action_id": item["source_action_id"]}))
        if item["independent_action_id"] != expected: raise ContractValidationError("observation deterministic identity differs")
        expected_disposition = "UNKNOWN_EFFECTIVE_DATE" if item["effective_date"] is None else "BEFORE_DATASET" if item["effective_date"] < span["start"] else "AFTER_DATASET" if item["effective_date"] > span["end"] else "IN_DATASET"
        if item["dataset_disposition"] != expected_disposition: raise ContractValidationError("observation disposition differs from declared date")
    for source in row["source_inventories"]:
        if source["observed_action_count"] != sum(item["inventory_id"] == source["inventory"]["inventory_id"] for item in observations):
            raise ContractValidationError("retained source action count differs")
    native_ids = {item["native_id"] for item in export.native_actions}; issuer_ids = set(ids)
    for field in ("matches", "native_only", "issuer_only", "ambiguous", "duplicate_groups"):
        for group in _list(row[field], field):
            group = _object(group, {"native_type", "effective_date", "affected_symbols", "native_action_ids", "independent_action_ids", "comparison"}, "exact action key group")
            _key_fields(group); left = _ids(group["native_action_ids"], "native ids"); right = _ids(group["independent_action_ids"], "issuer ids")
            _constant(group, "comparison", "EXACT_KEY_ONLY_NOT_ECONOMIC_CONFIRMATION")
            if not set(left) <= native_ids or not set(right) <= issuer_ids: raise ContractValidationError("reconciliation contains unretained identities")
    from collections import defaultdict
    left_by_key, right_by_key = defaultdict(list), defaultdict(list)
    for item in export.native_actions:
        if item["effective_date"] is not None: left_by_key[_key(item)].append(item["native_id"])
    for item in observations:
        if item["effective_date"] is not None: right_by_key[_key(item)].append(item["independent_action_id"])
    expected_groups = {key: [] for key in ("matches", "native_only", "issuer_only", "ambiguous", "duplicate_groups")}
    for key in sorted(set(left_by_key) | set(right_by_key)):
        left, right = sorted(left_by_key[key]), sorted(right_by_key[key])
        group = {"native_type": key[0], "effective_date": key[1], "affected_symbols": list(key[2]), "native_action_ids": left, "independent_action_ids": right, "comparison": "EXACT_KEY_ONLY_NOT_ECONOMIC_CONFIRMATION"}
        if len(left) > 1 or len(right) > 1:
            expected_groups["ambiguous"].append(group); expected_groups["duplicate_groups"].append(group)
        else: expected_groups["matches" if left and right else "native_only" if left else "issuer_only"].append(group)
    if any(row[key] != groups for key, groups in expected_groups.items()): raise ContractValidationError("exact key classifications must retain every known-date action without precedence")
    for item in _list(row["conflicts"], "conflicts"):
        item = _object(item, {"kind", "native_action_ids", "independent_action_ids", "status"}, "unresolved conflict")
        _enum(item["kind"], {"SOURCE_STATUS_UNRESOLVED", "EXACT_KEY_MULTIPLICITY", "REPLACEMENT_LINK_UNRESOLVED", "POSSIBLE_DATE_TYPE_OR_SYMBOL_CONFLICT", "DUPLICATE_SOURCE_BODY"}, "conflict kind")
        _constant(item, "status", "UNRESOLVED")
        if not set(_ids(item["native_action_ids"], "native conflict ids")) <= native_ids or not set(_ids(item["independent_action_ids"], "issuer conflict ids")) <= issuer_ids: raise ContractValidationError("conflict references unretained identities")
    overlay = _object(row["candidate_overlay"], {"schema_version", "status", "boundaries", "unknown_date_scope", "coverage_complete", "eligible_for_shadow_study", "native_gate_override"}, "candidate risk overlay")
    _constant(overlay, "schema_version", OVERLAY_VERSION); _constant(overlay, "status", "NOT_ELIGIBLE_COVERAGE_UNRESOLVED")
    for key in ("coverage_complete", "eligible_for_shadow_study", "native_gate_override"): _fixed_boolean(overlay, key, False)
    boundaries = _list(overlay["boundaries"], "candidate boundaries", 30000)
    boundary_ids, boundary_sources = set(), set()
    native_by_id = {item["native_id"]: item for item in export.native_actions}
    issuer_by_id = {item["independent_action_id"]: item for item in observations}
    for item in boundaries:
        item = _object(item, {"boundary_id", "origin", "source_id", "native_type", "affected_symbols", "declared_effective_date", "mapped_session_id", "mapped_session_index", "mapping", "source_status", "boundary_flag", "legacy_placeholder_retained", "eligible", "confirmed_payment"}, "risk-only boundary")
        for key in ("boundary_id", "source_id"): _identifier(item[key], key)
        if item["boundary_id"] in boundary_ids: raise ContractValidationError("duplicate boundary identity")
        boundary_ids.add(item["boundary_id"])
        origin = _enum(item["origin"], {"NATIVE", "ISSUER_DECLARATION"}, "boundary origin")
        if item["source_id"] not in (native_ids if origin == "NATIVE" else issuer_ids): raise ContractValidationError("boundary references an unretained action")
        source_key = origin, item["source_id"]
        if source_key in boundary_sources: raise ContractValidationError("each original action requires a distinct boundary audit")
        boundary_sources.add(source_key)
        original = (native_by_id if origin == "NATIVE" else issuer_by_id)[item["source_id"]]
        for field, original_field in (("native_type", "native_type"), ("affected_symbols", "affected_symbols"), ("declared_effective_date", "effective_date")):
            if item[field] != original[original_field]: raise ContractValidationError("candidate boundary changes original source fields")
        expected_boundary_id = "reconciled-boundary-" + sha256_bytes(canonical_json_bytes({"origin": origin, "source_id": item["source_id"]}))
        if item["boundary_id"] != expected_boundary_id: raise ContractValidationError("boundary deterministic identity differs")
        _enum(item["native_type"], set(ACTION_TYPES), "boundary type"); _universe(item["affected_symbols"])
        if item["declared_effective_date"] is not None: historical_date(item["declared_effective_date"], "declared date")
        mapping = _enum(item["mapping"], {"UNKNOWN_EFFECTIVE_DATE", "BEFORE_DATASET", "AFTER_DATASET", "EXACT_RETURNED_DATE", "NEXT_RETURNED_DATE"}, "date mapping")
        mapped = mapping in {"EXACT_RETURNED_DATE", "NEXT_RETURNED_DATE"}
        if (item["mapped_session_id"] is not None) != mapped or (item["mapped_session_index"] is not None) != mapped: raise ContractValidationError("boundary session must agree with mapping")
        if mapped: _identifier(item["mapped_session_id"], "mapped session"); _count(item["mapped_session_index"], "mapped index", 1000000)
        if (item["declared_effective_date"] is None) != (mapping == "UNKNOWN_EFFECTIVE_DATE"): raise ContractValidationError("unknown date cannot become a known boundary")
        _enum(item["source_status"], STATUSES | {"NATIVE_STATUS_UNAVAILABLE"}, "source status")
        if item["source_status"] != ("NATIVE_STATUS_UNAVAILABLE" if origin == "NATIVE" else original["status"]): raise ContractValidationError("candidate boundary changes source status")
        if origin == "NATIVE" and mapped and item["mapped_session_id"] != original["mapped_session_id"]: raise ContractValidationError("native candidate boundary differs from unchanged native calendar mapping")
        for key in ("boundary_flag", "legacy_placeholder_retained"):
            if type(item[key]) is not bool: raise ContractValidationError(key + " requires a boolean")
        expected_flag = mapped and item["source_status"] != "CANCELLED"
        if item["boundary_flag"] != expected_flag: raise ContractValidationError("candidate boundary flag differs from conservative policy")
        if item["legacy_placeholder_retained"] != (origin == "NATIVE" and mapping == "UNKNOWN_EFFECTIVE_DATE"): raise ContractValidationError("legacy placeholder label differs")
        for key in ("eligible", "confirmed_payment"): _fixed_boolean(item, key, False)
    if len(boundaries) != len(native_ids) + len(issuer_ids): raise ContractValidationError("overlay must retain one boundary audit per original action")
    for item in _list(overlay["unknown_date_scope"], "unknown date scope", 30000):
        item = _object(item, {"origin", "source_id", "affected_symbols", "reason"}, "unresolved unknown-date scope")
        _enum(item["origin"], {"NATIVE", "ISSUER_DECLARATION"}, "unknown origin"); _identifier(item["source_id"], "unknown source"); _universe(item["affected_symbols"])
        _constant(item, "reason", "UNKNOWN_EFFECTIVE_DATE_NO_INVENTED_BOUNDARY")
    expected_unknown = [{"origin": item["origin"], "source_id": item["source_id"], "affected_symbols": item["affected_symbols"], "reason": "UNKNOWN_EFFECTIVE_DATE_NO_INVENTED_BOUNDARY"} for item in boundaries if item["declared_effective_date"] is None]
    if overlay["unknown_date_scope"] != expected_unknown: raise ContractValidationError("all unknown-date scopes must remain explicit")
    cells = _list(row["coverage_matrix"], "coverage matrix", 104)
    expected_cells = {(symbol, action_type) for symbol in universe for action_type in ACTION_TYPES}; actual_cells = []
    for cell in cells:
        cell = _object(cell, {"symbol", "action_type", "status", "coverage_complete", "eligible", "declared_source_inventory_ids", "observed_native_count", "observed_issuer_count", "unresolved_interval"}, "unresolved coverage cell")
        actual_cells.append((cell["symbol"], cell["action_type"])); _constant(cell, "status", "UNRESOLVED")
        for key in ("coverage_complete", "eligible"): _fixed_boolean(cell, key, False)
        if not set(_ids(cell["declared_source_inventory_ids"], "source inventories")) <= inventory_ids: raise ContractValidationError("coverage source is not selected")
        for key in ("observed_native_count", "observed_issuer_count"): _count(cell[key], key)
        _constant(cell, "unresolved_interval", span)
        symbol, action_type = cell["symbol"], cell["action_type"]
        expected_inventory_ids = sorted(identity for identity, inventory in inventory_by_id.items() if symbol in inventory.declared_coverage["symbols"] and action_type in inventory.declared_coverage["action_types"])
        if cell["declared_source_inventory_ids"] != expected_inventory_ids: raise ContractValidationError("coverage cell omits selected declared source scopes")
        for key, actions in (("observed_native_count", export.native_actions), ("observed_issuer_count", observations)):
            count = sum(symbol in item["affected_symbols"] and item["native_type"] == action_type and item["dataset_disposition"] == "IN_DATASET" for item in actions)
            if cell[key] != count: raise ContractValidationError("coverage observations differ from retained actions")
    if len(actual_cells) != len(expected_cells) or set(actual_cells) != expected_cells: raise ContractValidationError("all fixed symbol/type coverage cells must remain unresolved")
    for key in ("reason_codes", "limitations"): _texts(row[key], key, 128)
    if not row["reason_codes"] or not row["limitations"]: raise ContractValidationError("unresolved reasons and limitations are required")
    if len(canonical_json_bytes(row)) > MAX_RESULT_BYTES: raise ContractValidationError("reconciled action result exceeds byte bound")
    return row
