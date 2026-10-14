"""Bounded offline parser for the publisher-disclosed QQQ distribution resource.

All rows are retained, including dates outside the declared interval. Numeric
JSON lexemes are encoded as strings in row provenance, never rounded to floats.
Listed source rows do not prove payment, completeness, authentication or PIT.
"""
from collections import defaultdict
from datetime import date
from decimal import Decimal, InvalidOperation, localcontext
from html.parser import HTMLParser
import json
import re

from .contracts.qqq_distribution_inventory import (
    QQQDistributionInventory, URL, RESOURCE_TEMPLATE, AUTHORITY,
    MAX_BODY_BYTES, MAX_DISCOVERY_BYTES, MAX_RECEIPT_BYTES, evidence_references,
)
from .contracts.decision_journal import _object
from .contracts.mission_request import ContractValidationError, parse_rfc3339
from .hashing import canonical_json_bytes, sha256_bytes

CODE_PATHS = ("contracts/qqq_distribution_inventory.py", "qqq_distribution_inventory.py")
ROW_FIELDS = {"exDate", "recordDate", "payDate", "distributionAmountPerUnit", "ordinaryIncomeDistribution", "shortTermCapitalGainsDistribution", "longTermCapitalGainsDistribution", "returnOfCapitalDistribution", "liquidationDistribution"}
DATE_FIELDS = {"exDate", "recordDate", "payDate"}
AMOUNT_FIELDS = ROW_FIELDS - DATE_FIELDS
MAX_ROWS = 10000
NUMBER_ENCODING = "JSON_NUMBER_TOKENS_AS_STRINGS"
HASH_BASIS = "SHA256_CANONICAL_JSON_WITH_NUMERIC_TOKEN_STRINGS"


class _Number(str):
    pass


class _DiscoveryPairs(list):
    """Keep unrelated CMS duplicate keys without concealing either value."""


def _error(message):
    raise ContractValidationError(message)


def _blob(blobs, reference):
    raw = blobs.get(reference["sha256"])
    if not isinstance(raw, bytes) or len(raw) != reference["size_bytes"] or sha256_bytes(raw) != reference["sha256"]:
        _error("QQQ source differs in retained hash or size")
    return raw


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            _error("duplicate JSON object keys are ambiguous")
        result[key] = value
    return result


def _json(raw, maximum, *, depth_limit=16, pairs_hook=_pairs):
    if not isinstance(raw, bytes) or not 0 < len(raw) <= maximum:
        _error("QQQ source requires bounded nonempty raw bytes")
    try:
        text = raw.decode("utf-8")
        # Bound nesting before the recursive JSON decoder allocates a tree.
        depth, quoted, escape = 0, False, False
        for char in text:
            if quoted:
                if escape: escape = False
                elif char == "\\": escape = True
                elif char == '"': quoted = False
            elif char == '"': quoted = True
            elif char in "[{":
                depth += 1
                if depth > depth_limit: _error("QQQ JSON exceeds nesting limit")
            elif char in "]}": depth -= 1
        result = json.loads(text, object_pairs_hook=pairs_hook, parse_int=_Number, parse_float=_Number,
            parse_constant=lambda value: _error("nonfinite JSON number is forbidden"))
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError, ValueError) as exc:
        if isinstance(exc, ContractValidationError): raise
        raise ContractValidationError("malformed QQQ source JSON") from exc
    stack, count = [result], 0
    while stack:
        item = stack.pop(); count += 1
        if count > 200000: _error("QQQ JSON exceeds node bound")
        if isinstance(item, dict): stack.extend(item.values())
        elif isinstance(item, (list, tuple)): stack.extend(item)
        elif isinstance(item, str):
            if len(item) > 10000: _error("QQQ JSON string exceeds bound")
            try: item.encode("utf-8")
            except UnicodeEncodeError as exc: raise ContractValidationError("QQQ JSON requires valid UTF-8 strings") from exc
    return result


def _date(value):
    if type(value) is not str or not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value):
        _error("QQQ source requires literal ISO calendar dates")
    try: date.fromisoformat(value)
    except ValueError as exc: raise ContractValidationError("QQQ calendar date is invalid") from exc
    return value


def _amount(value):
    if value is None: return None
    if not isinstance(value, _Number) or len(value) > 128:
        _error("QQQ amount must preserve an original JSON number token")
    try:
        with localcontext() as context:
            context.prec = 160
            number = Decimal(value)
            if not number.is_finite() or number < 0 or number > Decimal("1e20"):
                _error("QQQ amount exceeds nonnegative bounded source profile")
    except (InvalidOperation, ValueError) as exc:
        raise ContractValidationError("QQQ amount token is invalid") from exc
    return str(value)


def _verify_receipt(raw, inventory):
    row = _object(_json(raw, MAX_RECEIPT_BYTES), {"schema_version", "method", "url", "status", "captured_at", "content_type", "body_sha256", "size_bytes", "source_kind", "credentials_used", "redirects_followed"}, "QQQ public capture receipt")
    constants = {"schema_version": "blackpod.public_document_capture_receipt.v1", "method": "GET", "url": URL,
        "status": _Number("200"), "content_type": "application/json", "source_kind": "PUBLIC_PUBLISHER_DISTRIBUTION_HISTORY", "credentials_used": False, "redirects_followed": False}
    for key, expected in constants.items():
        if type(row[key]) is not type(expected) or row[key] != expected:
            _error("QQQ retained capture receipt differs from the public source profile")
    if row["captured_at"] != inventory.captured_at:
        _error("QQQ manifest and receipt capture clocks differ")
    parse_rfc3339(row["captured_at"], "capture clock")
    if (type(row["body_sha256"]) is not str or row["body_sha256"] != inventory.body_evidence["sha256"]
            or not isinstance(row["size_bytes"], _Number) or row["size_bytes"] != str(inventory.body_evidence["size_bytes"])):
        _error("QQQ retained receipt body binding differs")


class _Discovery(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.matches = 0

    def handle_starttag(self, tag, attrs):
        for _, value in attrs:
            if value is None or RESOURCE_TEMPLATE not in value:
                continue
            parsed = _json(value.encode("utf-8"), MAX_DISCOVERY_BYTES, depth_limit=64, pairs_hook=_DiscoveryPairs)
            stack = [parsed]
            while stack:
                item = stack.pop()
                if isinstance(item, _DiscoveryPairs):
                    if any(key == "url" and value == RESOURCE_TEMPLATE for key, value in item):
                        selected = _strict_discovery_object(item)
                        meta = selected.get("productMetaData")
                        if (selected.get("tableVariation") != "distributions" or selected.get("apiResponseKey") != "distributions"
                                or not isinstance(meta, dict) or type(meta.get("cusip")) is not str or meta.get("cusip") != "46090E103"
                                or meta.get("locale") != "en_US" or meta.get("uniqueIdentifier") != "cusip"
                                or meta.get("isin") != "US46090E1038"):
                            _error("QQQ discovery component has foreign or ambiguous fund identity")
                        self.matches += 1
                    stack.extend(value for _, value in item)
                elif isinstance(item, list): stack.extend(item)


def _strict_discovery_object(value):
    if isinstance(value, _DiscoveryPairs):
        return _pairs((key, _strict_discovery_object(item)) for key, item in value)
    if isinstance(value, list):
        return [_strict_discovery_object(item) for item in value]
    return value


def _verify_discovery(raw):
    if not isinstance(raw, bytes) or not 0 < len(raw) <= MAX_DISCOVERY_BYTES:
        _error("QQQ discovery HTML exceeds bound")
    try:
        parser = _Discovery(); parser.feed(raw.decode("utf-8")); parser.close()
    except (UnicodeDecodeError, ValueError, RecursionError) as exc:
        if isinstance(exc, ContractValidationError): raise
        raise ContractValidationError("QQQ discovery HTML is malformed") from exc
    if parser.matches != 1:
        _error("QQQ discovery must retain one exact publisher-disclosed distribution component")


def parse_qqq_distribution_inventory(inventory, blobs):
    """Retain every source row without asserting completeness or payment status."""
    inventory = inventory if isinstance(inventory, QQQDistributionInventory) else QQQDistributionInventory.from_mapping(inventory)
    raw, receipt, discovery = (_blob(blobs, reference) for reference in evidence_references(inventory))
    _verify_receipt(receipt, inventory)
    _verify_discovery(discovery)
    root = _object(_json(raw, MAX_BODY_BYTES), {"cusip", "currencyCode", "distributions"}, "QQQ distribution body")
    if type(root["cusip"]) is not str or root["cusip"] != "46090E103" or type(root["currencyCode"]) is not str or root["currencyCode"] != "USD":
        _error("QQQ body has foreign fund identity or currency")
    rows = root["distributions"]
    if not isinstance(rows, list) or len(rows) > MAX_ROWS:
        _error("QQQ distribution row count exceeds bound")
    actions, dates = [], defaultdict(list)
    for index, original in enumerate(rows):
        row = _object(original, ROW_FIELDS, "QQQ source row")
        for key in DATE_FIELDS: _date(row[key])
        amounts = {key: _amount(row[key]) for key in AMOUNT_FIELDS}
        if amounts["distributionAmountPerUnit"] is None:
            _error("QQQ row lacks its literal distribution-per-unit amount")
        native_row = {key: str(value) if isinstance(value, _Number) else value for key, value in row.items()}
        pointer = "/distributions/" + str(index)
        actions.append({"source_action_id": "invesco-qqq-distribution-row-" + str(index), "native_type": "cash_dividends",
            "affected_symbols": ["QQQ"], "effective_date": row["exDate"], "record_date": row["recordDate"], "payable_date": row["payDate"],
            "status": "LISTED_STATUS_UNSPECIFIED", "cusip": "46090E103", "amount_lexemes": {"dividend": amounts["distributionAmountPerUnit"],
                "short_term_capital_gain": amounts["shortTermCapitalGainsDistribution"], "long_term_capital_gain": amounts["longTermCapitalGainsDistribution"]},
            "replaces_source_action_id": None, "provenance": {"body_evidence": inventory.body_evidence, "value_pointer": pointer,
                "row_sha256": sha256_bytes(canonical_json_bytes(native_row)), "native_row": native_row,
                "native_row_number_encoding": NUMBER_ENCODING, "native_row_hash_basis": HASH_BASIS}})
        dates[row["exDate"]].append(index)
    evidence = {reference["path"]: _blob(blobs, reference) for reference in evidence_references(inventory)}
    return {"inventory": inventory, "actions": actions, "rows_scanned": len(rows),
        "observed_action_types": ["cash_dividends"] if actions else [], "source_scope": "LISTED_INVESCO_QQQ_DISTRIBUTIONS_ONLY",
        "duplicate_effective_dates": [{"effective_date": key, "row_indices": value} for key, value in sorted(dates.items()) if len(value) > 1],
        "completeness_verified": False, "source_authentication_verified": False, "historical_point_in_time_verified": False,
        "auto_trading_enabled": False, "authority": dict(AUTHORITY), "evidence": evidence}
