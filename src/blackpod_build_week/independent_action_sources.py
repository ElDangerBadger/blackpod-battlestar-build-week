"""Bounded offline independent-source adapters; no retrieval or extraction."""
from datetime import datetime
from decimal import Decimal, InvalidOperation
from io import BytesIO
import re
from pathlib import PurePosixPath
from xml.etree import ElementTree as ET
from zipfile import ZipFile, BadZipFile, ZIP_STORED, ZIP_DEFLATED

from .contracts.effective_date_reconciliation import (
    IndependentActionInventory, SSGA_PROFILE, AUTHORED_VERSION, ACTION_TYPES,
)
from .contracts.decision_journal import _object, _identifier, _enum, _string
from .contracts.historical_intake import historical_date
from .contracts.mission_request import ContractValidationError, parse_strict_json_object_bytes
from .contracts.trading_research import _universe
from .hashing import canonical_json_bytes, sha256_bytes

HEADERS = ("FUND NAME", "TICKER", "CUSIP", "EX-DATE", "RECORD DATE", "PAYABLE DATE", "DIVIDEND ($)", "SHORT TERM CAPITAL GAIN ($)", "LONG TERM CAPITAL GAIN ($)", "FREQUENCY")
MAX_ZIP_BYTES = 16 * 1024 * 1024
MAX_UNCOMPRESSED_BYTES = 32 * 1024 * 1024
MAX_MEMBER_BYTES = 16 * 1024 * 1024
MAX_MEMBERS = 64
MAX_ROWS = 50000
MAX_XML_NODES = 1000000
X = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
R = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
P = "{http://schemas.openxmlformats.org/package/2006/relationships}"
AMOUNTS = ("dividend", "short_term_capital_gain", "long_term_capital_gain")


def _error(message): raise ContractValidationError(message)


def _blob(blobs, ref):
    raw = blobs.get(ref["sha256"])
    if not isinstance(raw, bytes) or len(raw) != ref["size_bytes"] or sha256_bytes(raw) != ref["sha256"]: _error("independent source differs in retained hash or size")
    return raw


def _amount(value):
    if value is None: return None
    if not isinstance(value, str) or len(value) > 128 or not re.fullmatch(r"(?:0|[1-9][0-9]*)(?:\.[0-9]+)?", value.strip()): _error("source amounts require exact nonnegative decimal lexemes")
    try: number = Decimal(value)
    except InvalidOperation as exc: raise ContractValidationError("invalid source amount") from exc
    if not number.is_finite() or number > Decimal("1e20"): _error("source amount exceeds bound")
    return value


def _date_lexeme(value):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]{2}/[0-9]{2}/[0-9]{4}", value): _error("SSGA dates require literal MM/DD/YYYY shared strings")
    try: return datetime.strptime(value, "%m/%d/%Y").date().isoformat()
    except ValueError as exc: raise ContractValidationError("SSGA source date is invalid") from exc


def _xml(raw):
    # The observed profile is UTF-8. Reject other encodings before parsing so
    # UTF-16 null interleaving cannot evade the explicit DTD/entity prohibition.
    try: raw.decode("utf-8")
    except UnicodeDecodeError as exc: raise ContractValidationError("workbook XML must preserve the UTF-8 source profile") from exc
    if len(raw) > MAX_MEMBER_BYTES or b"\0" in raw or re.search(br"<!\s*(?:DOCTYPE|ENTITY)", raw, re.I): _error("unsafe or oversized workbook XML")
    try: root = ET.fromstring(raw)
    except (ET.ParseError, ValueError, RecursionError) as exc: raise ContractValidationError("malformed workbook XML") from exc
    stack, count = [(root, 1)], 0
    while stack:
        element, depth = stack.pop(); count += 1
        if depth > 64 or count > MAX_XML_NODES: _error("workbook XML exceeds node/depth limits")
        stack.extend((child, depth + 1) for child in element)
    return root


def parse_ssga_distributions(raw, inventory):
    """Parse the actual shared-string SSGA workbook, preserving every target cell."""
    inventory = inventory if isinstance(inventory, IndependentActionInventory) else IndependentActionInventory.from_mapping(inventory)
    if not isinstance(raw, bytes) or len(raw) > MAX_ZIP_BYTES: _error("workbook requires bounded exact ZIP bytes")
    try:
        with ZipFile(BytesIO(raw)) as archive:
            infos = archive.infolist()
            if not 1 <= len(infos) <= MAX_MEMBERS or len({item.filename for item in infos}) != len(infos): _error("workbook members are duplicate or exceed bounds")
            if sum(item.file_size for item in infos) > MAX_UNCOMPRESSED_BYTES: _error("workbook exceeds total expanded byte limit")
            for item in infos:
                path = PurePosixPath(item.filename)
                if path.is_absolute() or ".." in path.parts or "\\" in item.filename or item.flag_bits & 1 or item.compress_type not in {ZIP_STORED, ZIP_DEFLATED} or item.file_size > MAX_MEMBER_BYTES or item.file_size > max(1, item.compress_size) * 200 or (item.external_attr >> 16) & 0o170000 == 0o120000: _error("unsafe or bomb-like workbook archive member")
                if any(token in item.filename.lower() for token in ("vbaproject", "externallinks", "macrosheet")): _error("executable/external workbook content is not supported")
            def read(name):
                try:
                    with archive.open(name) as stream: data = stream.read(MAX_MEMBER_BYTES + 1)
                except (KeyError, OSError, RuntimeError, BadZipFile) as exc: raise ContractValidationError("required workbook member unavailable") from exc
                if len(data) > MAX_MEMBER_BYTES: _error("expanded workbook member exceeds bound")
                return _xml(data)
            book, relations, shared, sheet = (read(name) for name in ("xl/workbook.xml", "xl/_rels/workbook.xml.rels", "xl/sharedStrings.xml", "xl/worksheets/sheet1.xml"))
            sheets = book.find(X + "sheets")
            if sheets is None or len(sheets) != 1 or sheets[0].tag != X + "sheet" or sheets[0].get("name") != "dividend": _error("SSGA profile requires its one dividend sheet")
            relation_id = sheets[0].get(R + "id")
            relation_ids = [item.get("Id") for item in relations]
            if len(set(relation_ids)) != len(relation_ids): _error("duplicate workbook relationship identities")
            selected = [item for item in relations if item.tag == P + "Relationship" and item.get("Id") == relation_id]
            if len(selected) != 1 or selected[0].get("Target") != "worksheets/sheet1.xml" or selected[0].get("TargetMode") is not None or not selected[0].get("Type", "").endswith("/worksheet"): _error("ambiguous or external SSGA sheet relationship")
            shared_relations = [item for item in relations if item.get("Type", "").endswith("/sharedStrings")]
            if len(shared_relations) != 1 or shared_relations[0].get("Target") != "sharedStrings.xml" or shared_relations[0].get("TargetMode") is not None: _error("ambiguous or external SSGA shared-string relationship")
            if shared.tag != X + "sst" or sheet.tag != X + "worksheet": _error("unexpected SSGA XML document types")
            strings = []
            for entry in shared:
                if entry.tag != X + "si" or any(child.tag not in {X + "t", X + "r"} for child in entry): _error("unsupported shared-string entry")
                text = "".join(element.text or "" for element in entry.iter(X + "t"))
                if len(text) > 10000: _error("SSGA shared string exceeds bound")
                strings.append(text)
            if len(strings) > 100000: _error("SSGA shared string count exceeds bound")
            data = sheet.find(X + "sheetData")
            if data is None or not 1 <= len(data) <= MAX_ROWS: _error("workbook row count unavailable or exceeds bound")
            targets, actions, previous, row_count = set(inventory.declared_coverage["symbols"]), [], 0, 0
            for row in data:
                try: number = int(row.get("r", ""))
                except ValueError as exc: raise ContractValidationError("workbook row identity malformed") from exc
                if row.tag != X + "row" or number <= previous or number > MAX_ROWS: _error("duplicate/unordered workbook rows")
                previous, row_count = number, row_count + 1
                cells = {}
                for cell in row:
                    address = cell.get("r", "")
                    match = re.fullmatch(r"([A-J])([1-9][0-9]*)", address)
                    if cell.tag != X + "c" or match is None or int(match[2]) != number or match[1] in cells: _error("ambiguous workbook cell identity")
                    if any(child.tag != X + "v" for child in cell) or len(cell) > 1: _error("formulas and unexpected workbook cell content are forbidden")
                    value = cell.find(X + "v"); token = None if value is None else value.text
                    kind, index = cell.get("t"), None
                    if kind == "s":
                        if token is None or not re.fullmatch(r"0|[1-9][0-9]*", token) or int(token) >= len(strings): _error("invalid shared-string index")
                        index = int(token); lexeme = strings[index]
                    elif kind in {None, "n"}: lexeme = "" if token is None else token
                    else: _error("unsupported source cell representation")
                    cells[match[1]] = {"cell": address, "lexeme": lexeme, "shared_string_index": index, "value_type": kind or "n"}
                if number == 1:
                    if set(cells) != set("ABCDEFGHIJ") or tuple(cells[key]["lexeme"] for key in "ABCDEFGHIJ") != HEADERS: _error("SSGA workbook headers differ from the frozen profile")
                    continue
                ticker = cells.get("B", {}).get("lexeme", "")
                if ticker.strip() not in targets: continue
                if ticker != ticker.strip() or set(cells) != set("ABCDEFGHIJ"): _error("target SSGA row is malformed or incomplete")
                if any(cells[key]["value_type"] != "s" for key in "ABCDEFJ"): _error("SSGA target identity/date fields must be literal shared strings")
                if not cells["A"]["lexeme"] or not re.fullmatch(r"[A-Z0-9]{9}", cells["C"]["lexeme"]): _error("SSGA target fund identity is malformed")
                effective, record, payable = (_date_lexeme(cells[key]["lexeme"]) for key in "DEF")
                amounts = {name: _amount(cells[key]["lexeme"] if cells[key]["lexeme"].strip() else None) for name, key in zip(AMOUNTS, "GHI")}
                if all(amount is None for amount in amounts.values()): _error("SSGA target distribution lacks amount evidence")
                actions.append({"source_action_id": "ssga-dividend-row-" + str(number), "native_type": "cash_dividends", "affected_symbols": [ticker], "effective_date": effective,
                    "record_date": record, "payable_date": payable, "status": "LISTED_STATUS_UNSPECIFIED", "cusip": cells["C"]["lexeme"], "amount_lexemes": amounts, "replaces_source_action_id": None,
                    "provenance": {"body_evidence": inventory.body_evidence, "sheet": "dividend", "row": number, "cells": cells, "row_sha256": sha256_bytes(canonical_json_bytes(cells))}})
            if not previous or not any(row.get("r") == "1" for row in data): _error("SSGA header row missing")
            return {"actions": actions, "rows_scanned": row_count - 1, "observed_action_types": ["cash_dividends"] if actions else [], "source_scope": "LISTED_SSGA_CASH_DISTRIBUTIONS_ONLY", "completeness_verified": False}
    except (BadZipFile, OSError, ValueError, OverflowError, RecursionError) as exc:
        if isinstance(exc, ContractValidationError): raise
        raise ContractValidationError("workbook archive cannot be parsed safely") from exc


def parse_authored_actions(raw, inventory):
    value = _object(parse_strict_json_object_bytes(raw), {"schema_version", "label", "actions"}, "authored inventory body")
    if value["schema_version"] != AUTHORED_VERSION or value["label"] != "AUTHORED_UNVERIFIED": _error("authored source must retain explicit unverified provenance")
    if not isinstance(value["actions"], list) or len(value["actions"]) > 10000: _error("authored action count exceeds bound")
    actions, seen = [], set()
    fields = {"source_action_id", "native_type", "affected_symbols", "effective_date", "record_date", "payable_date", "status", "cusip", "amount_lexemes", "replaces_source_action_id"}
    for index, original in enumerate(value["actions"]):
        row = _object(original, fields, "authored source action")
        row["source_action_id"] = _identifier(row["source_action_id"], "source action id")
        if row["source_action_id"] in seen: _error("duplicate authored source action identity")
        seen.add(row["source_action_id"])
        row["native_type"] = _enum(row["native_type"], set(ACTION_TYPES), "native action type")
        row["affected_symbols"] = _universe(row["affected_symbols"])
        for field in ("effective_date", "record_date", "payable_date"):
            if row[field] is not None: row[field] = historical_date(row[field], field)
        row["status"] = _enum(row["status"], {"EFFECTIVE", "SCHEDULED", "CANCELLED", "REVISED", "UNKNOWN"}, "action status")
        if row["cusip"] is not None: row["cusip"] = _string(row["cusip"], "CUSIP", 128)
        amounts = _object(row["amount_lexemes"], set(AMOUNTS), "amount lexemes")
        row["amount_lexemes"] = {key: _amount(item) for key, item in amounts.items()}
        if row["replaces_source_action_id"] is not None:
            row["replaces_source_action_id"] = _identifier(row["replaces_source_action_id"], "replaced source identity")
            if row["replaces_source_action_id"] == row["source_action_id"]: _error("source action cannot replace itself")
        row["provenance"] = {"body_evidence": inventory.body_evidence, "value_pointer": "/actions/" + str(index), "row_sha256": sha256_bytes(canonical_json_bytes(original))}
        actions.append(row)
    return {"actions": actions, "rows_scanned": len(actions), "observed_action_types": sorted({row["native_type"] for row in actions}), "source_scope": "AUTHORED_UNVERIFIED_INVENTORY_ONLY", "completeness_verified": False}


def parse_independent_inventory(inventory, blobs):
    inventory = inventory if isinstance(inventory, IndependentActionInventory) else IndependentActionInventory.from_mapping(inventory)
    raw = _blob(blobs, inventory.body_evidence)
    parsed = parse_ssga_distributions(raw, inventory) if inventory.profile == SSGA_PROFILE else parse_authored_actions(raw, inventory)
    evidence = {inventory.body_evidence["path"]: raw}
    for reference in inventory.supporting_evidence:
        evidence[reference["path"]] = _blob(blobs, reference)
    return {"inventory": inventory, **parsed, "evidence": evidence}
