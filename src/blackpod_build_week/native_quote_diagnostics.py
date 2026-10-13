"""Pure source-bound diagnostics of the existing segmented TRAIN admission.

The original native validators and admission rule remain authoritative. This
report counts all retained rows and records a few reproducible witnesses; it
does not select a replacement sample, discard an extremum or qualify costs.
"""
from __future__ import annotations

from decimal import Context, Decimal, ROUND_CEILING, localcontext
import json
import re

from .contracts.decision_journal import JournalEvent, _identifier, _object
from .contracts.investment_review import disabled_authority
from .contracts.mission_request import ContractValidationError, parse_rfc3339
from .contracts.trading_reconciliation import evidence_reference
from .contracts.trading_research import research_symbol
from .contracts.train_market_evidence import EXPORT_TYPE, SEGMENT_TYPE
from .hashing import canonical_json_bytes, sha256_bytes
from .train_market_evidence import export_context, event_by_id
from .train_market_evidence_journal import validate_train_market_event
from .trading_cost_intake import _capture, _nanos
from .trading_historical_intake import parse_historical_json

VERSION = "blackpod.native_quote_diagnostics.v1"
METHOD_VERSION = VERSION
CODE_PATHS = ("native_quote_diagnostics.py",)
SCOPE = "RETAINED_SEGMENTED_TRAIN_QUOTES_ONLY"
ADMISSION_POLICY = "POSITIVE_BID_ASK_SIZE_NONCROSSED_REGULAR_R_CONDITION_OPEN_THROUGH_OPEN_PLUS_60_SECONDS"
NUMBER_ENCODING = "JSON_NUMBER_TOKENS_AS_STRINGS"
HASH_BASIS = "SHA256_CANONICAL_JSON_WITH_NUMERIC_TOKEN_STRINGS"
TIE_BREAK = "FIRST_FROZEN_SEGMENT_THEN_PAGE_THEN_SYMBOL_ARRAY_INDEX"
SPREAD_METHOD = "DECIMAL_256_ROUND_CEILING_18_PLACES_MIDPOINT_BPS"
REJECTION_REASONS = ("NONPOSITIVE_PRICE", "NONPOSITIVE_SIZE", "CROSSED", "CONDITION_NOT_EXACT_REGULAR_R")
MULTIPLIERS = ("1", "2", "4")
AUTHORITY = {key: False for key in ("authorization_enabled", "capital_activation_enabled", "execution_enabled", "policy_changes_enabled")}
LIMITATIONS = (
    "DIAGNOSTICS_PRESERVE_ORIGINAL_ADMISSION_AND_ALL_RETAINED_ROWS",
    "REJECTION_REASON_COUNTS_OVERLAP_AND_ARE_NOT_A_SECOND_ADMISSION_RULE",
    "SPREAD_ONLY_COMPONENT_EXCEEDANCES_NOT_COMPLETE_COST_STRESS_MODEL",
    "EXTREMA_WITNESSES_ARE_NOT_A_REPLACEMENT_SAMPLE_OR_OUTLIER_EXCLUSION",
    "IEX_OPENING_MINUTE_NOT_CONSOLIDATED_NBBO_OR_OPENING_AUCTION_LIQUIDITY",
    "NATIVE_SIDE_SIZE_UNITS_NOT_EXECUTABLE_CAPACITY",
    "RETAINED_RECEIPTS_NOT_PROVIDER_AUTHENTICATION_OR_HISTORICAL_POINT_IN_TIME_PROOF",
    "NO_FEES_SLIPPAGE_CAPACITY_OR_ECONOMIC_RETURN_ESTIMATION",
    "NO_DECISION_POLICY_RISK_OR_EXECUTION_AUTHORITY",
)
_QUANTUM = Decimal("0.000000000000000001")
_NUMBER = re.compile(r"-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?\Z")
_HEX = re.compile(r"[0-9a-f]{64}\Z")
_MAX_REPORT_BYTES = 8 * 1024 * 1024
_FALSE_FIELDS = ("source_authentication_verified", "historical_point_in_time_verified",
    "fees_estimated", "slippage_estimated", "cost_applicability_verified", "opening_execution_capacity_verified",
    "economic_hypothesis_supported", "uncertainty_computed", "existing_gate_override", "auto_trading_enabled")
_COUNTS = {"raw_quote_count", "admitted_quote_count", "rejected_quote_count", "rejection_reasons", "spread_only_exceedance_counts"}
_NATIVE_FIELDS = {"t", "bp", "bs", "bx", "ap", "as", "ax", "c", "z"}


def _text(value):
    rendered = format(value, "f")
    return rendered.rstrip("0").rstrip(".") if "." in rendered else rendered


def _spread(bid, ask):
    with localcontext(Context(prec=256, rounding=ROUND_CEILING)):
        return ((ask - bid) * Decimal("20000") / (ask + bid)).quantize(_QUANTUM, rounding=ROUND_CEILING)


def _blob(blobs, reference):
    raw = blobs.get(reference["sha256"])
    if not isinstance(raw, bytes) or len(raw) != reference["size_bytes"] or sha256_bytes(raw) != reference["sha256"]:
        raise ContractValidationError("quote diagnostic evidence differs in hash or size")
    return raw


def _empty_counts():
    return {"raw_quote_count": 0, "admitted_quote_count": 0, "rejected_quote_count": 0,
        "rejection_reasons": {reason: 0 for reason in REJECTION_REASONS},
        "spread_only_exceedance_counts": {multiplier: 0 for multiplier in MULTIPLIERS}}


def _rejections(row):
    reasons = []
    if row["bp"] <= 0 or row["ap"] <= 0: reasons.append("NONPOSITIVE_PRICE")
    if row["bs"] <= 0 or row["as"] <= 0: reasons.append("NONPOSITIVE_SIZE")
    if row["ap"] < row["bp"]: reasons.append("CROSSED")
    if row["c"] != ["R"]: reasons.append("CONDITION_NOT_EXACT_REGULAR_R")
    return reasons


def _witness(event, segment, page, symbol, index, native, spread, size):
    return {"source_segment_event_id": event.event_id, "segment_id": segment["segment_id"],
        "fold_id": segment["fold_id"], "session_id": segment["session_id"],
        "body_evidence": page["body_evidence"], "receipt_evidence": page["receipt_evidence"],
        "row_pointer": "/quotes/" + symbol + "/" + str(index), "native_row_sha256": sha256_bytes(canonical_json_bytes(native)),
        "symbol": symbol, "native_row": native, "spread_bps": _text(spread),
        "reported_side_size_native_units": _text(size)}


def _sum_counts(rows):
    total = _empty_counts()
    for row in rows:
        for field in ("raw_quote_count", "admitted_quote_count", "rejected_quote_count"):
            total[field] += row[field]
        for field in ("rejection_reasons", "spread_only_exceedance_counts"):
            for key, value in row[field].items(): total[field][key] += value
    return total


def diagnose_segmented_quotes(export_event, events, blobs):
    """Replay an exact v19 export and diagnose every provided native TRAIN row.

    Missing, failed and empty windows remain visible in the full plan inventory.
    They cannot acquire usable extrema. Later history cannot change this export's
    historical prefix. Source numeric tokens are encoded as strings only in the
    compact witness; body bytes and original source number types are untouched.
    """
    if not isinstance(export_event, JournalEvent):
        export_event = JournalEvent.from_mapping(export_event)
    events = tuple(events)
    if len({event.event_id for event in events}) != len(events):
        raise ContractValidationError("quote diagnostics require unambiguous historical event identities")
    if export_event.event_type != EXPORT_TYPE or export_event.domain != "TRADING":
        raise ContractValidationError("quote diagnostics require an original Trading v19 aggregate export")
    present = [event for event in events if event.event_id == export_event.event_id]
    if present:
        if present[0].to_bytes() != export_event.to_bytes():
            raise ContractValidationError("quote diagnostic export identity conflicts with retained history")
        events = events[:events.index(present[0])]
    context = export_context(export_event.payload["request"], events, blobs)
    validate_train_market_event(export_event, events, blobs)
    capture, dataset = context["plan"], context["dataset"]
    selected = [event_by_id(events, identity, {SEGMENT_TYPE}) for identity in context["request"].segment_event_ids]
    by_segment = {event.source["segment_id"]: event for event in selected}
    symbols = {symbol: {"symbol": symbol, **_empty_counts(), "max_spread_bps": None,
        "min_reported_side_size_native_units": None, "max_spread_witness": None, "min_side_size_witness": None}
        for symbol in dataset.universe}
    inventory, fold_counts = [], {}
    for segment in capture.segments:
        event = by_segment.get(segment["segment_id"])
        inventory.append({key: segment[key] for key in ("segment_id", "fold_id", "session_index", "session_id")})
        inventory[-1].update(source_segment_event_id=None if event is None else event.event_id,
            status="MISSING" if event is None else event.payload["result"]["status"])
        if event is None: continue
        validate_train_market_event(event, events[:events.index(event)], blobs)
        local = {symbol: {**_empty_counts(), "max_spread_bps": None, "min_reported_side_size_native_units": None}
            for symbol in dataset.universe}
        for page in event.payload["request"]["pages"]:
            raw = _blob(blobs, page["body_evidence"])
            receipt = _capture(_blob(blobs, page["receipt_evidence"]))
            if receipt["status"] != 200: continue
            native = parse_historical_json(raw)
            # Native replay above verifies structure, duplicate fields, numbers,
            # pagination, symbols, clocks and bounds. Decode number *tokens* a
            # second time for precise witnesses rather than round through float.
            tokens = json.loads(raw.decode("utf-8"), parse_float=str, parse_int=str)
            for symbol in dataset.universe:
                for index, row in enumerate(native["quotes"].get(symbol, [])):
                    global_item, item = symbols[symbol], local[symbol]
                    for target in (global_item, item): target["raw_quote_count"] += 1
                    reasons = _rejections(row)
                    if reasons:
                        for target in (global_item, item):
                            target["rejected_quote_count"] += 1
                            for reason in reasons: target["rejection_reasons"][reason] += 1
                        continue
                    spread, size = _spread(row["bp"], row["ap"]), min(row["bs"], row["as"])
                    with localcontext(Context(prec=256, rounding=ROUND_CEILING)):
                        exceeded = [multiplier for multiplier in MULTIPLIERS if spread * Decimal(multiplier) > Decimal("1000")]
                    for target in (global_item, item):
                        target["admitted_quote_count"] += 1
                        for multiplier in exceeded: target["spread_only_exceedance_counts"][multiplier] += 1
                    witness = None
                    if global_item["max_spread_bps"] is None or spread > Decimal(global_item["max_spread_bps"]):
                        witness = _witness(event, segment, page, symbol, index, tokens["quotes"][symbol][index], spread, size)
                        global_item["max_spread_bps"], global_item["max_spread_witness"] = _text(spread), witness
                    if global_item["min_reported_side_size_native_units"] is None or size < Decimal(global_item["min_reported_side_size_native_units"]):
                        witness = witness or _witness(event, segment, page, symbol, index, tokens["quotes"][symbol][index], spread, size)
                        global_item["min_reported_side_size_native_units"], global_item["min_side_size_witness"] = _text(size), witness
                    item["max_spread_bps"] = _text(spread if item["max_spread_bps"] is None else max(Decimal(item["max_spread_bps"]), spread))
                    item["min_reported_side_size_native_units"] = _text(size if item["min_reported_side_size_native_units"] is None else min(Decimal(item["min_reported_side_size_native_units"]), size))
        for original in event.payload["result"]["symbols"]:
            item = local[original["symbol"]]
            for old, new in (("raw_quote_count", "raw_quote_count"), ("eligible_quote_count", "admitted_quote_count"),
                ("rejected_quote_count", "rejected_quote_count"), ("max_spread_bps", "max_spread_bps"),
                ("min_reported_side_size_native_units", "min_reported_side_size_native_units")):
                if item[new] != original[old]:
                    raise ContractValidationError("quote diagnostic counts or extrema differ from the original native segment")
        fold_counts.setdefault(segment["fold_id"], []).append(local)
    for fold in context["result"]["folds"]:
        if fold["training_spread_profile"] is None: continue
        rows = fold_counts.get(fold["fold_id"], [])
        for retained in fold["training_spread_profile"]:
            measured = [row[retained["symbol"]] for row in rows]
            if (sum(row["raw_quote_count"] for row in measured) != retained["raw_quote_count"]
                or sum(row["admitted_quote_count"] for row in measured) != retained["eligible_quote_count"]
                or _text(max(Decimal(row["max_spread_bps"]) for row in measured)) != retained["max_spread_bps"]
                or _text(min(Decimal(row["min_reported_side_size_native_units"]) for row in measured)) != retained["min_reported_side_size_native_units"]):
                raise ContractValidationError("quote diagnostic measurements differ from original TRAIN fold extrema")
    total = _sum_counts(symbols.values())
    retained_counts = context["result"]["counts"]
    if (total["raw_quote_count"] != retained_counts["raw_quote_count"]
        or total["admitted_quote_count"] != retained_counts["eligible_quote_count"]):
        raise ContractValidationError("quote diagnostic totals differ from the original full export")
    report = {"schema_version": VERSION, "method_version": METHOD_VERSION, "scope": SCOPE,
        "source": {"aggregate_export_event_id": export_event.event_id,
            "capture_plan_event_id": context["request"].capture_plan_event_id,
            "base_plan_event_id": capture.base_plan_event_id, "dataset_evidence": capture.dataset_evidence,
            "capture_id": capture.capture_id, "export_id": context["request"].export_id,
            "exported_at": context["request"].exported_at, "evidence_scope": capture.evidence_scope},
        "existing_admission_policy": ADMISSION_POLICY, "native_row_number_encoding": NUMBER_ENCODING,
        "native_row_hash_basis": HASH_BASIS, "witness_tie_break": TIE_BREAK, "spread_method": SPREAD_METHOD,
        "spread_only_component_threshold": {"component_bound_bps": "1000", "comparator": "STRICT_GREATER_THAN",
            "semantics": "SPREAD_ONLY_NOT_FULL_COST_STRESS_MODEL", "multipliers": list(MULTIPLIERS)},
        "coverage": {key: retained_counts[key] for key in ("planned_segments", "provided_segments", "missing_segments")},
        "segment_inventory": inventory, "source_segment_event_ids": sorted(event.event_id for event in selected),
        "totals": total, "symbols": list(symbols.values()),
        "reconciliation": {"retained_raw_quote_count": retained_counts["raw_quote_count"],
            "retained_admitted_quote_count": retained_counts["eligible_quote_count"], "counts_match": True,
            "segment_summaries_match": True, "fold_extrema_match": True},
        **{field: False for field in _FALSE_FIELDS}, "authority": dict(AUTHORITY), "limitations": list(LIMITATIONS)}
    report["coverage"].update(capture_complete=context["result"]["capture_complete"], coverage_complete=context["result"]["coverage_complete"])
    return validate_diagnostics(report)


def _count(value, name, maximum=2_000_000_000):
    if type(value) is not int or not 0 <= value <= maximum:
        raise ContractValidationError(name + " must be a bounded nonnegative exact integer")
    return value


def _exact_decimal(value, name, *, token=False, positive=False, integer=False):
    if not isinstance(value, str) or len(value) > 128 or not _NUMBER.fullmatch(value):
        raise ContractValidationError(name + " must preserve a bounded JSON numeric token")
    number = parse_historical_json(value.encode("ascii"))
    if not isinstance(number, Decimal) or number < 0 or (positive and number <= 0) or (integer and number != number.to_integral_value()):
        raise ContractValidationError(name + " must be a finite nonnegative exact number")
    if not token and _text(number) != value:
        raise ContractValidationError(name + " must use the canonical exact fixed-point representation")
    return number


def _validate_counts(value):
    row = _object(value, _COUNTS, "quote diagnostic counts")
    for key in ("raw_quote_count", "admitted_quote_count", "rejected_quote_count"): _count(row[key], key)
    if row["raw_quote_count"] != row["admitted_quote_count"] + row["rejected_quote_count"]:
        raise ContractValidationError("quote diagnostic raw/admitted/rejected counts do not reconcile")
    rejected = _object(row["rejection_reasons"], set(REJECTION_REASONS), "overlapping rejection reasons")
    for key, value in rejected.items():
        if _count(value, key) > row["rejected_quote_count"]:
            raise ContractValidationError("an overlapping rejection count exceeds all rejected rows")
    if not row["rejected_quote_count"] <= sum(rejected.values()) <= row["rejected_quote_count"] * len(REJECTION_REASONS):
        raise ContractValidationError("rejected native rows require at least one existing admission reason")
    exceeded = _object(row["spread_only_exceedance_counts"], set(MULTIPLIERS), "spread component counts")
    prior = 0
    for multiplier in MULTIPLIERS:
        current = _count(exceeded[multiplier], "spread-only exceedance count")
        if not prior <= current <= row["admitted_quote_count"]:
            raise ContractValidationError("spread-only counts must be monotone and bounded by admitted rows")
        prior = current
    return row


def _validate_witness(value, symbol, inventory):
    row = _object(value, {"source_segment_event_id", "segment_id", "fold_id", "session_id", "body_evidence",
        "receipt_evidence", "row_pointer", "native_row_sha256", "symbol", "native_row", "spread_bps", "reported_side_size_native_units"}, "native quote witness")
    for key in ("source_segment_event_id", "segment_id", "fold_id", "session_id"): _identifier(row[key], key)
    selected = inventory.get(row["segment_id"])
    if selected is None or selected["status"] == "MISSING" or any(row[key] != selected[key] for key in ("source_segment_event_id", "fold_id", "session_id")):
        raise ContractValidationError("native quote witness must refer to an inventoried original source segment")
    if row["symbol"] != symbol: raise ContractValidationError("native quote witness changes its original symbol")
    for key in ("body_evidence", "receipt_evidence"): evidence_reference(row[key], key)
    if row["body_evidence"]["sha256"] == row["receipt_evidence"]["sha256"] or row["body_evidence"]["path"] == row["receipt_evidence"]["path"]:
        raise ContractValidationError("native witness body and receipt must retain distinct source identities")
    if not isinstance(row["row_pointer"], str) or not re.fullmatch(re.escape("/quotes/" + symbol + "/") + r"(?:0|[1-9][0-9]{0,5})", row["row_pointer"]):
        raise ContractValidationError("native quote witness requires an exact bounded symbol-array JSON pointer")
    if int(row["row_pointer"].rsplit("/", 1)[1]) >= 10000:
        raise ContractValidationError("native witness cannot exceed its original page row bound")
    native = _object(row["native_row"], _NATIVE_FIELDS, "exact native quote witness row")
    _nanos(native["t"], "native witness timestamp")
    for key in ("bx", "ax"):
        if not isinstance(native[key], str) or not 1 <= len(native[key]) <= 16 or native[key].strip() != native[key]:
            raise ContractValidationError("native quote witness exchange code must be a bounded exact string")
    if not isinstance(native["z"], str) or native["z"] not in {"A", "B", "C"} or native["c"] != ["R"]:
        raise ContractValidationError("extremum witnesses require original admitted native tape/conditions")
    bid, ask = (_exact_decimal(native[key], key, token=True, positive=True) for key in ("bp", "ap"))
    sizes = [_exact_decimal(native[key], key, token=True, positive=True, integer=True) for key in ("bs", "as")]
    if ask < bid: raise ContractValidationError("extremum witness cannot be a crossed quote")
    spread = _exact_decimal(row["spread_bps"], "witness spread")
    size = _exact_decimal(row["reported_side_size_native_units"], "native side size", positive=True, integer=True)
    if spread != _spread(bid, ask) or size != min(sizes):
        raise ContractValidationError("native quote witness calculations differ from its exact native fields")
    if not isinstance(row["native_row_sha256"], str) or not _HEX.fullmatch(row["native_row_sha256"]) or row["native_row_sha256"] != sha256_bytes(canonical_json_bytes(native)):
        raise ContractValidationError("native quote witness digest differs from its exact token-preserving encoding")
    return row


def validate_diagnostics(value):
    """Reject extra fields, malformed witnesses, arithmetic and authority claims.

    This validates a compact report's shape. Source binding is established by
    diagnose_segmented_quotes and by journal byte-for-byte replay, never by a
    standalone report or a self-consistent witness alone.
    """
    fields = {"schema_version", "method_version", "scope", "source", "existing_admission_policy", "native_row_number_encoding",
        "native_row_hash_basis", "witness_tie_break", "spread_method", "spread_only_component_threshold", "coverage", "segment_inventory",
        "source_segment_event_ids", "totals", "symbols", "reconciliation", "authority", "limitations", *_FALSE_FIELDS}
    row = _object(value, fields, "native quote diagnostics")
    for field, expected in (("schema_version", VERSION), ("method_version", METHOD_VERSION), ("scope", SCOPE),
        ("existing_admission_policy", ADMISSION_POLICY), ("native_row_number_encoding", NUMBER_ENCODING),
        ("native_row_hash_basis", HASH_BASIS), ("witness_tie_break", TIE_BREAK), ("spread_method", SPREAD_METHOD)):
        if row[field] != expected: raise ContractValidationError("native quote diagnostic method or semantics changed")
    source = _object(row["source"], {"aggregate_export_event_id", "capture_plan_event_id", "base_plan_event_id", "dataset_evidence", "capture_id", "export_id", "exported_at", "evidence_scope"}, "native diagnostic source")
    for key in ("aggregate_export_event_id", "capture_plan_event_id", "base_plan_event_id", "capture_id", "export_id"): _identifier(source[key], key)
    evidence_reference(source["dataset_evidence"], "dataset_evidence")
    parse_rfc3339(source["exported_at"], "native diagnostic export clock")
    if not isinstance(source["evidence_scope"], str) or source["evidence_scope"] not in {"SYNTHETIC_FIXTURE_ONLY", "RETAINED_HISTORY_RESEARCH"}:
        raise ContractValidationError("native diagnostic evidence scope must remain explicit")
    threshold = _object(row["spread_only_component_threshold"], {"component_bound_bps", "comparator", "semantics", "multipliers"}, "spread-only threshold")
    if threshold != {"component_bound_bps": "1000", "comparator": "STRICT_GREATER_THAN", "semantics": "SPREAD_ONLY_NOT_FULL_COST_STRESS_MODEL", "multipliers": list(MULTIPLIERS)}:
        raise ContractValidationError("native diagnostic cannot substitute its spread-only threshold")
    coverage = _object(row["coverage"], {"planned_segments", "provided_segments", "missing_segments", "capture_complete", "coverage_complete"}, "native diagnostic coverage")
    for key in ("planned_segments", "provided_segments", "missing_segments"): _count(coverage[key], key, 10000)
    for key in ("capture_complete", "coverage_complete"):
        if type(coverage[key]) is not bool: raise ContractValidationError("native diagnostic completion must be exact booleans")
    if not coverage["planned_segments"] or coverage["planned_segments"] != coverage["provided_segments"] + coverage["missing_segments"]:
        raise ContractValidationError("native diagnostic must inventory the complete original plan")
    if not isinstance(row["segment_inventory"], list) or len(row["segment_inventory"]) != coverage["planned_segments"]:
        raise ContractValidationError("native diagnostic must preserve every planned segment")
    inventory, positions = {}, set()
    for item in row["segment_inventory"]:
        item = _object(item, {"segment_id", "fold_id", "session_index", "session_id", "source_segment_event_id", "status"}, "native diagnostic segment")
        for key in ("segment_id", "fold_id", "session_id"): _identifier(item[key], key)
        _count(item["session_index"], "session index", 10000)
        if item["segment_id"] in inventory or (item["fold_id"], item["session_index"]) in positions:
            raise ContractValidationError("native diagnostic source segment identities and fold positions must be distinct")
        positions.add((item["fold_id"], item["session_index"])); inventory[item["segment_id"]] = item
        if not isinstance(item["status"], str) or item["status"] not in {"MISSING", "CAPTURE_INCOMPLETE", "CAPTURE_COMPLETE"}:
            raise ContractValidationError("native diagnostic must preserve capture dispositions")
        if (item["source_segment_event_id"] is None) != (item["status"] == "MISSING"):
            raise ContractValidationError("missing segments cannot receive an invented source event")
        if item["source_segment_event_id"] is not None: _identifier(item["source_segment_event_id"], "source_segment_event_id")
    source_ids = sorted(item["source_segment_event_id"] for item in inventory.values() if item["source_segment_event_id"] is not None)
    if len(set(source_ids)) != len(source_ids) or row["source_segment_event_ids"] != source_ids or len(source_ids) != coverage["provided_segments"]:
        raise ContractValidationError("native diagnostic source links must match every provided original segment")
    if coverage["capture_complete"] != all(item["status"] == "CAPTURE_COMPLETE" for item in inventory.values()) or (coverage["coverage_complete"] and not coverage["capture_complete"]):
        raise ContractValidationError("missing or incomplete native captures cannot claim complete coverage")
    total = _validate_counts(row["totals"])
    if not isinstance(row["symbols"], list) or not 1 <= len(row["symbols"]) <= 8:
        raise ContractValidationError("native diagnostic symbols must be a bounded original universe")
    names = []
    for item in row["symbols"]:
        item = _object(item, {"symbol", "max_spread_bps", "min_reported_side_size_native_units", "max_spread_witness", "min_side_size_witness", *_COUNTS}, "native diagnostic symbol")
        symbol = research_symbol(item["symbol"]); names.append(symbol)
        _validate_counts({key: item[key] for key in _COUNTS})
        extrema_fields = ("max_spread_bps", "min_reported_side_size_native_units", "max_spread_witness", "min_side_size_witness")
        if not item["admitted_quote_count"]:
            if any(item[key] is not None for key in extrema_fields):
                raise ContractValidationError("missing admitted native rows cannot acquire invented extrema")
            continue
        if any(item[key] is None for key in extrema_fields):
            raise ContractValidationError("every admitted symbol requires its exact extrema witnesses")
        _exact_decimal(item["max_spread_bps"], "max spread")
        _exact_decimal(item["min_reported_side_size_native_units"], "minimum native size", positive=True, integer=True)
        maximum = _validate_witness(item["max_spread_witness"], symbol, inventory)
        minimum = _validate_witness(item["min_side_size_witness"], symbol, inventory)
        if maximum["spread_bps"] != item["max_spread_bps"] or minimum["reported_side_size_native_units"] != item["min_reported_side_size_native_units"]:
            raise ContractValidationError("native diagnostic extrema do not match their retained witnesses")
        if Decimal(minimum["spread_bps"]) > Decimal(item["max_spread_bps"]) or Decimal(maximum["reported_side_size_native_units"]) < Decimal(item["min_reported_side_size_native_units"]):
            raise ContractValidationError("native witnesses conflict with reported extrema")
        for multiplier in MULTIPLIERS:
            with localcontext(Context(prec=256, rounding=ROUND_CEILING)):
                exceeds = Decimal(item["max_spread_bps"]) * Decimal(multiplier) > Decimal("1000")
            if exceeds != (item["spread_only_exceedance_counts"][multiplier] > 0):
                raise ContractValidationError("native maximum and spread-only exceedance counts disagree")
    if names != sorted(set(names)): raise ContractValidationError("native diagnostic symbol universe must be sorted and unique")
    if (source["evidence_scope"] == "SYNTHETIC_FIXTURE_ONLY") != all(symbol.startswith("SYNTH") for symbol in names):
        raise ContractValidationError("native diagnostic must preserve fictional versus real source semantics")
    if total != _sum_counts(row["symbols"]): raise ContractValidationError("native diagnostic totals differ from every original symbol")
    reconciliation = _object(row["reconciliation"], {"retained_raw_quote_count", "retained_admitted_quote_count", "counts_match", "segment_summaries_match", "fold_extrema_match"}, "native diagnostic reconciliation")
    if (reconciliation["retained_raw_quote_count"] != total["raw_quote_count"] or reconciliation["retained_admitted_quote_count"] != total["admitted_quote_count"]):
        raise ContractValidationError("native diagnostic must preserve original export counts")
    for key in ("retained_raw_quote_count", "retained_admitted_quote_count"): _count(reconciliation[key], key)
    for key in ("counts_match", "segment_summaries_match", "fold_extrema_match"):
        if reconciliation[key] is not True: raise ContractValidationError("native diagnostic requires exact successful source reconciliation")
    for key in _FALSE_FIELDS:
        if row[key] is not False: raise ContractValidationError("native quote diagnostic cannot acquire applicability or authority")
    disabled_authority(row["authority"])
    if row["limitations"] != list(LIMITATIONS): raise ContractValidationError("native diagnostic limitations must remain explicit")
    if len(canonical_json_bytes(row)) > _MAX_REPORT_BYTES:
        raise ContractValidationError("native diagnostic compact report exceeds its byte bound")
    return row
