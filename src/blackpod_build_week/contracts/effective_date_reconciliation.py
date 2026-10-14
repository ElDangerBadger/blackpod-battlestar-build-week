"""Independent retained action evidence; no coverage or execution authority."""
from urllib.parse import urlsplit
from .decision_journal import _object, _identifier, _enum, _string, _hash
from .investment_review import _fixed_boolean, disabled_authority
from .mission_request import ContractValidationError, parse_rfc3339
from .trading_accounting import accounting_timestamp
from .trading_reconciliation import _ReconciliationDocument, evidence_reference
from .trading_research import _universe
from .historical_intake import historical_date

REQUEST_VERSION = "blackpod.effective_date_reconciliation_request.v1"
INVENTORY_VERSION = "blackpod.independent_action_inventory.v1"
AUTHORED_VERSION = "blackpod.authored_effective_date_actions.v1"
RESULT_VERSION = "blackpod.effective_date_reconciliation.v1"
METHOD_VERSION = RESULT_VERSION
SCOPE = "RETAINED_INDEPENDENT_EFFECTIVE_DATE_RECONCILIATION_ONLY"
SSGA_PROFILE = "SSGA_HISTORICAL_DISTRIBUTIONS_XLSX_V1"
AUTHORED_PROFILE = "AUTHORED_EFFECTIVE_DATE_ACTIONS_JSON_V1"
SSGA_URL = "https://www.ssga.com/library-content/products/fund-data/etfs/us/spdr-etf-historical-distributions.xlsx"
ACTION_TYPES = ("cash_dividends", "cash_mergers", "forward_splits", "name_changes", "redemptions", "reverse_splits", "rights_distributions", "spin_offs", "stock_and_cash_mergers", "stock_dividends", "stock_mergers", "unit_splits", "worthless_removals")
AUTHORITY = {name: False for name in ("authorization_enabled", "capital_activation_enabled", "execution_enabled", "policy_changes_enabled")}


def _constant(row, field, expected):
    if row[field] != expected or type(row[field]) is not type(expected): raise ContractValidationError(field + " must be " + repr(expected))


def _safe(row):
    _fixed_boolean(row, "auto_trading_enabled", False); row["authority"] = disabled_authority(row["authority"])
    return row


def _refs(value, name, maximum=32, nonempty=False):
    if not isinstance(value, list) or len(value) > maximum or (nonempty and not value): raise ContractValidationError(name + " requires a bounded explicit list")
    result = [evidence_reference(ref, name) for ref in value]
    if len({ref["path"] for ref in result}) != len(result): raise ContractValidationError(name + " has duplicate paths")
    return result


def _types(value):
    if not isinstance(value, list) or not value or len(value) > len(ACTION_TYPES): raise ContractValidationError("action types require a nonempty bounded list")
    result = [_enum(item, set(ACTION_TYPES), "action type") for item in value]
    if result != sorted(set(result)): raise ContractValidationError("action types must be sorted distinct native groups")
    return result


def _coverage(value):
    row = _object(value, {"symbols", "action_types", "effective_start", "effective_end", "completeness"}, "declared source coverage")
    row["symbols"] = _universe(row["symbols"]); row["action_types"] = _types(row["action_types"])
    for field in ("effective_start", "effective_end"): row[field] = historical_date(row[field], field)
    if row["effective_start"] > row["effective_end"]: raise ContractValidationError("declared coverage dates are reversed")
    row["completeness"] = _enum(row["completeness"], {"UNKNOWN", "PARTIAL", "DECLARED_COMPLETE"}, "declared completeness")
    return row


def _request(value):
    row = _object(value, {"schema_version", "reconciliation_id", "recorded_at", "data_cutoff_at", "domain", "mode", "scope", "dataset_evidence", "native_continuity_export_evidence", "independent_inventories", "auto_trading_enabled", "authority"}, "effective-date reconciliation request")
    for field, expected in (("schema_version", REQUEST_VERSION), ("domain", "TRADING"), ("mode", "SHADOW_RESEARCH"), ("scope", SCOPE)): _constant(row, field, expected)
    row["reconciliation_id"] = _identifier(row["reconciliation_id"], "reconciliation_id")
    for field in ("recorded_at", "data_cutoff_at"): row[field] = accounting_timestamp(row[field], field)
    if parse_rfc3339(row["data_cutoff_at"], "cutoff") > parse_rfc3339(row["recorded_at"], "record clock"): raise ContractValidationError("cutoff cannot follow record clock")
    for field in ("dataset_evidence", "native_continuity_export_evidence"): row[field] = evidence_reference(row[field], field)
    row["independent_inventories"] = _refs(row["independent_inventories"], "independent inventories", 16, True)
    refs = [row["dataset_evidence"], row["native_continuity_export_evidence"], *row["independent_inventories"]]
    if len({ref["path"] for ref in refs}) != len(refs): raise ContractValidationError("request sources require distinct paths")
    return _safe(row)


def _inventory(value):
    row = _object(value, {"schema_version", "inventory_id", "recorded_at", "profile", "evidence_scope", "publisher", "source_url", "captured_at", "body_evidence", "declared_coverage", "supporting_evidence", "auto_trading_enabled", "authority"}, "independent action inventory")
    _constant(row, "schema_version", INVENTORY_VERSION)
    row["inventory_id"] = _identifier(row["inventory_id"], "inventory_id")
    row["profile"] = _enum(row["profile"], {SSGA_PROFILE, AUTHORED_PROFILE}, "source profile")
    row["evidence_scope"] = _enum(row["evidence_scope"], {"SYNTHETIC_FIXTURE_ONLY", "RETAINED_HISTORY_RESEARCH"}, "evidence scope")
    for field in ("recorded_at", "captured_at"): row[field] = accounting_timestamp(row[field], field)
    if parse_rfc3339(row["captured_at"], "source capture") > parse_rfc3339(row["recorded_at"], "inventory clock"): raise ContractValidationError("inventory cannot predate source capture")
    row["publisher"] = _string(row["publisher"], "publisher", 256)
    row["source_url"] = _string(row["source_url"], "source URL", 2048)
    try: url = urlsplit(row["source_url"])
    except ValueError as exc: raise ContractValidationError("source URL is malformed") from exc
    if url.scheme not in {"http", "https"} or not url.hostname or url.username is not None or url.password is not None or any(char.isspace() for char in row["source_url"]): raise ContractValidationError("source URL must be explicit HTTP(S) without credentials")
    if row["profile"] == SSGA_PROFILE and (row["publisher"] != "SSGA" or row["source_url"] != SSGA_URL or row["evidence_scope"] != "RETAINED_HISTORY_RESEARCH"): raise ContractValidationError("SSGA profile requires its exact publisher, public workbook URL and retained-history scope")
    row["body_evidence"] = evidence_reference(row["body_evidence"], "source body")
    row["declared_coverage"] = _coverage(row["declared_coverage"])
    row["supporting_evidence"] = _refs(row["supporting_evidence"], "source support")
    if row["body_evidence"]["path"] in {ref["path"] for ref in row["supporting_evidence"]}: raise ContractValidationError("support cannot reuse source body path")
    return _safe(row)


class EffectiveDateReconciliationRequest(_ReconciliationDocument):
    __slots__ = ()
    _validator = staticmethod(_request)


class IndependentActionInventory(_ReconciliationDocument):
    __slots__ = ()
    _validator = staticmethod(_inventory)


def declared_scope_gaps(start, end, intervals):
    """Inclusive calendar union; this measures declarations, never verification."""
    from datetime import date, timedelta
    first, last = date.fromisoformat(start), date.fromisoformat(end)
    pairs = sorted((max(first, date.fromisoformat(row["start"])), min(last, date.fromisoformat(row["end"]))) for row in intervals if row["start"] <= end and row["end"] >= start)
    cursor, gaps = first, []
    for left, right in pairs:
        if left > cursor: gaps.append({"start": cursor.isoformat(), "end": (left-timedelta(days=1)).isoformat()})
        if right >= cursor: cursor = right+timedelta(days=1)
    if cursor <= last: gaps.append({"start": cursor.isoformat(), "end": last.isoformat()})
    return gaps


def _list(value, name, maximum=20000):
    if not isinstance(value, list) or len(value) > maximum: raise ContractValidationError(name + " requires a bounded list")
    return value


def _ids(value, name):
    values = [_identifier(item, name) for item in _list(value, name)]
    if values != sorted(set(values)): raise ContractValidationError(name + " requires sorted distinct identities")
    return values


def _count(value, name):
    if type(value) is not int or not 0 <= value <= 2000000000: raise ContractValidationError(name + " requires a bounded nonnegative integer")


def _dates(row, fields):
    for field in fields:
        if row[field] is not None: historical_date(row[field], field)


def _interval(value, fields):
    row = _object(value, fields, "coverage interval")
    for field in ("start", "end"): historical_date(row[field], field)
    if row["start"] > row["end"]: raise ContractValidationError("coverage interval reversed")
    return row


def _raw_lexeme(value):
    """Keep source cell text exactly, including blanks and surrounding space."""
    if not isinstance(value, str) or len(value) > 10000:
        raise ContractValidationError("source cell lexeme requires bounded raw text")
    try: value.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise ContractValidationError("source cell lexeme must contain valid UTF-8 text") from exc
    return value


def _independent_action(value):
    row = _object(value, {"independent_action_id", "inventory_id", "source_action_id", "native_type", "affected_symbols", "effective_date", "record_date", "payable_date", "status", "cusip", "amount_lexemes", "replaces_source_action_id", "provenance", "dataset_disposition"}, "independent action")
    for field in ("independent_action_id", "inventory_id", "source_action_id"): _identifier(row[field], field)
    _enum(row["native_type"], set(ACTION_TYPES), "native type"); _universe(row["affected_symbols"])
    _dates(row, ("effective_date", "record_date", "payable_date"))
    _enum(row["status"], {"EFFECTIVE", "SCHEDULED", "CANCELLED", "REVISED", "UNKNOWN", "LISTED_STATUS_UNSPECIFIED"}, "source status")
    if row["cusip"] is not None: _string(row["cusip"], "CUSIP", 128)
    if row["replaces_source_action_id"] is not None: _identifier(row["replaces_source_action_id"], "replaced identity")
    from ..independent_action_sources import _amount
    amounts = _object(row["amount_lexemes"], {"dividend", "short_term_capital_gain", "long_term_capital_gain"}, "amount lexemes")
    for amount in amounts.values(): _amount(amount)
    _enum(row["dataset_disposition"], {"IN_DATASET", "BEFORE_DATASET", "AFTER_DATASET", "UNKNOWN_EFFECTIVE_DATE"}, "dataset disposition")
    if (row["effective_date"] is None) != (row["dataset_disposition"] == "UNKNOWN_EFFECTIVE_DATE"): raise ContractValidationError("unknown independent date/disposition mismatch")
    provenance = row["provenance"]
    if not isinstance(provenance, dict): raise ContractValidationError("action provenance requires an object")
    fields = {"body_evidence", "sheet", "row", "cells", "row_sha256"} if "sheet" in provenance else {"body_evidence", "value_pointer", "row_sha256"}
    provenance = _object(provenance, fields, "exact source row provenance")
    evidence_reference(provenance["body_evidence"], "source body"); _hash(provenance["row_sha256"], "source row hash")
    if "sheet" in provenance:
        _constant(provenance, "sheet", "dividend"); _count(provenance["row"], "workbook row")
        if not 2 <= provenance["row"] <= 50000: raise ContractValidationError("target workbook row is out of bounds")
        cells = _object(provenance["cells"], set("ABCDEFGHIJ"), "exact target cells")
        for column, value in cells.items():
            cell = _object(value, {"cell", "lexeme", "shared_string_index", "value_type"}, "source cell")
            _constant(cell, "cell", column+str(provenance["row"])); _raw_lexeme(cell["lexeme"])
            _enum(cell["value_type"], {"s", "n"}, "source cell type")
            if cell["shared_string_index"] is not None: _count(cell["shared_string_index"], "shared-string index")
        from ..hashing import canonical_json_bytes, sha256_bytes
        if provenance["row_sha256"] != sha256_bytes(canonical_json_bytes(cells)): raise ContractValidationError("workbook provenance hash differs from exact cells")
    else:
        import re
        if not isinstance(provenance["value_pointer"], str) or not re.fullmatch(r"/actions/(?:0|[1-9][0-9]{0,3})", provenance["value_pointer"]): raise ContractValidationError("authored action pointer is malformed")
    return row


def validate_result(value):
    fields = {"schema_version", "method_version", "reconciliation_id", "status", "dataset_evidence", "native_continuity_export_evidence", "effective_span", "universe", "source_inventory", "independent_actions", "native_actions", "matches", "native_only", "independent_only", "ambiguous", "conflicts", "unknown_effective_dates", "duplicate_groups", "coverage_matrix", "reason_codes", "coverage_proposal", "native_gate_override", "coverage_supported", "source_authentication_verified", "source_independence_verified", "historical_point_in_time_verified", "economic_hypothesis_supported", "uncertainty_computed", "execution_status", "realized_trade_pnl", "limitations", "auto_trading_enabled", "authority"}
    row = _object(value, fields, "effective-date reconciliation result")
    for field, expected in (("schema_version", RESULT_VERSION), ("method_version", METHOD_VERSION), ("status", "DESCRIPTIVE_RECONCILIATION_ONLY"), ("execution_status", "NOT_EXECUTED"), ("realized_trade_pnl", None)): _constant(row, field, expected)
    row["reconciliation_id"] = _identifier(row["reconciliation_id"], "reconciliation_id")
    for field in ("dataset_evidence", "native_continuity_export_evidence"): row[field] = evidence_reference(row[field], field)
    row["universe"] = _universe(row["universe"])
    span = _object(row["effective_span"], {"start", "end", "calendar_days"}, "effective span")
    for field in ("start", "end"): historical_date(span[field], field)
    from datetime import date
    expected = (date.fromisoformat(span["end"]) - date.fromisoformat(span["start"])).days + 1
    if type(span["calendar_days"]) is not int or not 1 <= expected <= 40000 or span["calendar_days"] != expected: raise ContractValidationError("effective span must retain exact calendar days")
    for field in ("source_inventory", "independent_actions", "native_actions", "matches", "native_only", "independent_only", "ambiguous", "conflicts", "unknown_effective_dates", "duplicate_groups", "coverage_matrix", "reason_codes", "limitations"):
        _list(row[field], field)
    for field in ("reason_codes", "limitations"):
        texts = [_string(item, field, 10000) for item in row[field]]
        if len(texts) != len(set(texts)): raise ContractValidationError(field + " contains duplicates")
    inventory_ids = set()
    for value in row["source_inventory"]:
        item = _object(value, {"inventory_id", "manifest_evidence", "profile", "publisher", "source_url", "captured_at", "body_evidence", "declared_coverage", "source_scope", "rows_scanned", "observed_target_rows", "observed_symbols", "observed_action_types", "completeness_verified", "source_authentication_verified"}, "parsed source inventory")
        _identifier(item["inventory_id"], "inventory id")
        if item["inventory_id"] in inventory_ids: raise ContractValidationError("duplicate inventory result identity")
        inventory_ids.add(item["inventory_id"])
        for field in ("manifest_evidence", "body_evidence"): evidence_reference(item[field], field)
        _enum(item["profile"], {SSGA_PROFILE, AUTHORED_PROFILE}, "source profile")
        for field in ("publisher", "source_url"): _string(item[field], field, 2048)
        accounting_timestamp(item["captured_at"], "capture clock"); _coverage(item["declared_coverage"])
        _enum(item["source_scope"], {"LISTED_SSGA_CASH_DISTRIBUTIONS_ONLY", "AUTHORED_UNVERIFIED_INVENTORY_ONLY"}, "observed source scope")
        expected_scope = "LISTED_SSGA_CASH_DISTRIBUTIONS_ONLY" if item["profile"] == SSGA_PROFILE else "AUTHORED_UNVERIFIED_INVENTORY_ONLY"
        _constant(item, "source_scope", expected_scope)
        if item["profile"] == SSGA_PROFILE and (item["publisher"] != "SSGA" or item["source_url"] != SSGA_URL): raise ContractValidationError("SSGA source identity differs from its fixed profile")
        for field in ("rows_scanned", "observed_target_rows"): _count(item[field], field)
        if item["observed_symbols"]: _universe(item["observed_symbols"])
        else: _list(item["observed_symbols"], "observed symbols", 8)
        if item["observed_action_types"]: _types(item["observed_action_types"])
        else: _list(item["observed_action_types"], "observed action types", 13)
        for field in ("completeness_verified", "source_authentication_verified"): _fixed_boolean(item, field, False)
    independent_ids = set()
    for action in row["independent_actions"]:
        action = _independent_action(action)
        if action["inventory_id"] not in inventory_ids or action["independent_action_id"] in independent_ids: raise ContractValidationError("independent source identity/link mismatch")
        independent_ids.add(action["independent_action_id"])
        expected_disposition = "UNKNOWN_EFFECTIVE_DATE" if action["effective_date"] is None else "BEFORE_DATASET" if action["effective_date"] < span["start"] else "AFTER_DATASET" if action["effective_date"] > span["end"] else "IN_DATASET"
        _constant(action, "dataset_disposition", expected_disposition)
    for item in row["source_inventory"]:
        observations = [action for action in row["independent_actions"] if action["inventory_id"] == item["inventory_id"]]
        if item["observed_target_rows"] != len(observations) or item["rows_scanned"] < len(observations): raise ContractValidationError("source row counts differ from retained independent observations")
        if item["observed_symbols"] != sorted({symbol for action in observations for symbol in action["affected_symbols"]}) or item["observed_action_types"] != sorted({action["native_type"] for action in observations}): raise ContractValidationError("observed source scope differs from actual independent rows")
    native_ids = set()
    for value in row["native_actions"]:
        item = _object(value, {"native_id", "native_type", "process_date", "effective_date", "effective_date_basis", "affected_symbols", "dataset_disposition", "mapped_session_id"}, "native action audit")
        _identifier(item["native_id"], "native action id"); _enum(item["native_type"], set(ACTION_TYPES), "native type")
        if item["native_id"] in native_ids: raise ContractValidationError("duplicate native action identity")
        native_ids.add(item["native_id"]); historical_date(item["process_date"], "process date"); _dates(item, ("effective_date",)); _universe(item["affected_symbols"])
        _enum(item["effective_date_basis"], {"EX_DATE", "EFFECTIVE_DATE", "UNKNOWN"}, "effective date basis")
        _enum(item["dataset_disposition"], {"IN_DATASET", "BEFORE_DATASET", "AFTER_DATASET", "UNKNOWN_EFFECTIVE_DATE"}, "disposition")
        if item["mapped_session_id"] is not None: _identifier(item["mapped_session_id"], "mapped session id")
        unknown = item["effective_date_basis"] == "UNKNOWN"
        if unknown != (item["effective_date"] is None) or unknown != (item["dataset_disposition"] == "UNKNOWN_EFFECTIVE_DATE"): raise ContractValidationError("native unknown date fields are inconsistent")
    for field in ("matches", "native_only", "independent_only", "ambiguous", "duplicate_groups"):
        for value in row[field]:
            fields = {"native_type", "effective_date", "affected_symbols", "native_action_ids", "independent_action_ids"} | ({"comparison"} if field == "matches" else set())
            item = _object(value, fields, "action comparison")
            _enum(item["native_type"], set(ACTION_TYPES), "native type"); historical_date(item["effective_date"], "effective date"); _universe(item["affected_symbols"])
            if not set(_ids(item["native_action_ids"], "native ids")) <= native_ids or not set(_ids(item["independent_action_ids"], "independent ids")) <= independent_ids: raise ContractValidationError("comparison refers to missing actions")
            if field == "matches": _constant(item, "comparison", "EVENT_KEY_ONLY_AMOUNT_AND_STATUS_UNVERIFIED")
            left, right = len(item["native_action_ids"]), len(item["independent_action_ids"])
            if (field == "matches" and (left,right) != (1,1)) or (field == "native_only" and (not left or right)) or (field == "independent_only" and (left or not right)) or (field in {"ambiguous","duplicate_groups"} and max(left,right) < 2): raise ContractValidationError("action comparison disposition disagrees with identity counts")
    for value in row["unknown_effective_dates"]:
        item = _object(value, {"source", "action_id"}, "unknown effective date")
        _enum(item["source"], {"NATIVE", "INDEPENDENT"}, "unknown date source"); _identifier(item["action_id"], "unknown action id")
        if item["action_id"] not in (native_ids if item["source"] == "NATIVE" else independent_ids): raise ContractValidationError("unknown date action absent")
    for value in row["conflicts"]:
        item = _object(value, {"kind", "independent_action_ids", "native_action_ids", "status"}, "source conflict")
        _enum(item["kind"], {"INDEPENDENT_STATUS_NOT_CONFIRMED_EFFECTIVE", "POSSIBLE_DATE_OR_TYPE_CONFLICT_NOT_RESOLVED", "POSSIBLE_SYMBOL_CONFLICT_NOT_RESOLVED"}, "conflict kind")
        _enum(item["status"], {"SCHEDULED", "CANCELLED", "REVISED", "UNKNOWN", "UNRESOLVED"}, "source conflict status")
        if not set(_ids(item["native_action_ids"], "native ids")) <= native_ids or not set(_ids(item["independent_action_ids"], "independent ids")) <= independent_ids: raise ContractValidationError("conflict refers to missing actions")
    if len(row["coverage_matrix"]) != len(row["universe"]) * len(ACTION_TYPES): raise ContractValidationError("coverage matrix must retain all symbols and action types")
    for position, item in enumerate(row["coverage_matrix"]):
        item = _object(item, {"symbol", "action_type", "observed_event_count", "declared_intervals", "declared_scope_gaps", "observed_effective_dates", "uncovered_intervals", "coverage_supported"}, "coverage matrix entry")
        if (item["symbol"], item["action_type"]) != [(symbol, action) for symbol in row["universe"] for action in ACTION_TYPES][position]: raise ContractValidationError("coverage matrix order/membership differs")
        if type(item["observed_event_count"]) is not int or item["observed_event_count"] < 0: raise ContractValidationError("observed counts must be nonnegative integers")
        for value in _list(item["declared_intervals"], "declared intervals", 16):
            interval = _interval(value, {"inventory_id", "start", "end", "completeness"}); _identifier(interval["inventory_id"], "inventory id")
            if interval["inventory_id"] not in inventory_ids: raise ContractValidationError("declared interval references missing source")
            _enum(interval["completeness"], {"UNKNOWN", "PARTIAL", "DECLARED_COMPLETE"}, "declared completeness")
        expected_intervals = [{"inventory_id": source["inventory_id"], "start": source["declared_coverage"]["effective_start"], "end": source["declared_coverage"]["effective_end"], "completeness": source["declared_coverage"]["completeness"]} for source in row["source_inventory"] if item["symbol"] in source["declared_coverage"]["symbols"] and item["action_type"] in source["declared_coverage"]["action_types"]]
        if item["declared_intervals"] != expected_intervals: raise ContractValidationError("declared interval changes original source coverage declarations")
        for value in _list(item["declared_scope_gaps"], "declared scope gaps", 32): _interval(value, {"start", "end"})
        if item["declared_scope_gaps"] != declared_scope_gaps(span["start"], span["end"], item["declared_intervals"]): raise ContractValidationError("declared scope gap arithmetic differs from inclusive union")
        observed = [historical_date(value, "observed date") for value in _list(item["observed_effective_dates"], "observed dates")]
        if observed != sorted(set(observed)) or len(observed) > item["observed_event_count"]: raise ContractValidationError("observed effective dates inconsistent")
        observations = [action for action in row["independent_actions"] if item["symbol"] in action["affected_symbols"] and item["action_type"] == action["native_type"] and action["dataset_disposition"] == "IN_DATASET"]
        if item["observed_event_count"] != len(observations) or observed != sorted({action["effective_date"] for action in observations}): raise ContractValidationError("coverage cell observations differ from exact retained rows")
        for value in _list(item["uncovered_intervals"], "unverified intervals", 1):
            interval = _interval(value, {"start", "end", "reason"}); _constant(interval, "reason", "CONTINUOUS_EFFECTIVE_DATE_COMPLETENESS_NOT_VERIFIED")
        if item["uncovered_intervals"] != [{"start":span["start"],"end":span["end"],"reason":"CONTINUOUS_EFFECTIVE_DATE_COMPLETENESS_NOT_VERIFIED"}]: raise ContractValidationError("unverified completeness must retain the entire original span")
        _fixed_boolean(item, "coverage_supported", False)
    proposal = row["coverage_proposal"]
    from .trading_continuity_intake import ContinuityCoverageReview
    proposal = ContinuityCoverageReview.from_mapping(proposal)
    if proposal.status != "UNRESOLVED": raise ContractValidationError("coverage proposal cannot auto-support native coverage")
    if proposal.dataset_evidence != row["dataset_evidence"] or proposal.universe != row["universe"]: raise ContractValidationError("unresolved coverage proposal changes original dataset/universe")
    row["coverage_proposal"] = proposal.to_dict()
    for field in ("native_gate_override", "coverage_supported", "source_authentication_verified", "source_independence_verified", "historical_point_in_time_verified", "economic_hypothesis_supported", "uncertainty_computed"): _fixed_boolean(row, field, False)
    return _safe(row)
