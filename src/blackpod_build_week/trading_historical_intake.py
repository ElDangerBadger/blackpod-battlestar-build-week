"""Pure retained-source adapter for independent daily trading research.

No provider, estimator, legacy strategy, account or execution module is used.
Calendar dates and clocks come from the exact retained response, never a
weekday guess. Historical availability is a stated experimental assumption.
"""
from __future__ import annotations

from datetime import datetime, time, timedelta, timezone
from decimal import Decimal
import json
import re
from zoneinfo import ZoneInfo

from .contracts.historical_intake import (
    HISTORICAL_INTAKE_LIMITATIONS, HISTORICAL_INTAKE_VERSION, HistoricalIntakeRequest, HistoricalIntakeExport,
    historical_date, validate_historical_capture,
)
from .contracts.mission_request import ContractValidationError, format_rfc3339, parse_rfc3339
from .contracts.trading_accounting import accounting_decimal
from .contracts.trading_research import TradingResearchDataset
from .hashing import canonical_json_bytes, sha256_bytes

_NY = ZoneInfo("America/New_York")


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ContractValidationError("duplicate historical source field: " + key)
        result[key] = value
    return result


def parse_historical_json(raw):
    """Decode raw numeric tokens exactly, including a JSON calendar list."""
    if not isinstance(raw, bytes) or len(raw) > 64 * 1024 * 1024:
        raise ContractValidationError("historical source must be bounded retained bytes")
    def reject(value):
        raise ContractValidationError("non-finite historical source token " + value)
    def exact_decimal(token):
        # Bound before fixed-point rendering; 1e999999999 must never allocate a
        # giant decimal string. No precision reduction or numeric repair occurs.
        if len(token) > 128:
            raise ContractValidationError("raw historical numeric token exceeds supported bounds")
        number = Decimal(token)
        exponent = number.as_tuple().exponent
        if not -18 <= exponent <= 20 or number.copy_abs() > Decimal("1e20"):
            raise ContractValidationError("raw historical numeric token exceeds fixed-point research bounds")
        return number
    try:
        return json.loads(raw.decode("utf-8"), object_pairs_hook=_pairs,
                          parse_float=exact_decimal, parse_int=exact_decimal, parse_constant=reject)
    except (ValueError, UnicodeError, RecursionError) as exc:
        if isinstance(exc, ContractValidationError):
            raise
        raise ContractValidationError("invalid retained historical JSON") from exc


def _blob(blobs, reference):
    raw = blobs.get(reference["sha256"])
    if not isinstance(raw, bytes) or len(raw) != reference["size_bytes"] or sha256_bytes(raw) != reference["sha256"]:
        raise ContractValidationError("historical evidence differs in hash or size")
    return raw


def _receipt(blobs, receipt_ref, body_ref, kind, recorded):
    # Receipt integers are contract integers. Raw market numbers remain Decimal.
    from .contracts.mission_request import parse_strict_json_object_bytes
    receipt = validate_historical_capture(parse_strict_json_object_bytes(_blob(blobs, receipt_ref)), kind)
    if receipt["body_sha256"] != body_ref["sha256"] or receipt["size_bytes"] != body_ref["size_bytes"]:
        raise ContractValidationError("GET receipt must bind the exact retained response")
    if parse_rfc3339(receipt["captured_at"], "captured_at") > recorded:
        raise ContractValidationError("source capture must not follow intake recording")
    return receipt


def _clock(value, name, *, auxiliary=False):
    pattern = r"([0-9]{2})([0-9]{2})" if auxiliary else r"([0-9]{2}):([0-9]{2})"
    match = re.fullmatch(pattern, value) if isinstance(value, str) else None
    if match is None:
        raise ContractValidationError(name + " must use the actual declared calendar clock format")
    hour, minute = (int(item) for item in match.groups())
    if hour > 23 or minute > 59:
        raise ContractValidationError(name + " is outside the calendar clock range")
    return time(hour, minute)


def _calendar(raw, receipt):
    source = parse_historical_json(raw)
    if not isinstance(source, list) or not 1 <= len(source) <= 10000:
        raise ContractValidationError("calendar must be a bounded nonempty returned list")
    result, prior = {}, None
    for item in source:
        if not isinstance(item, dict) or set(item) != {"date", "open", "close", "session_open", "session_close", "settlement_date"}:
            raise ContractValidationError("calendar requires exact returned regular and extended session fields")
        day = historical_date(item["date"], "calendar.date")
        historical_date(item["settlement_date"], "calendar.settlement_date")
        if not receipt["query"]["start"] <= day <= receipt["query"]["end"]:
            raise ContractValidationError("calendar date lies outside the retained request")
        if prior is not None and day <= prior:
            raise ContractValidationError("calendar dates must be strictly increasing and unique")
        prior = day
        clocks = {}
        for field in ("open", "close", "session_open", "session_close"):
            clock = _clock(item[field], "calendar." + field, auxiliary=field.startswith("session_"))
            clocks[field] = datetime.combine(datetime.fromisoformat(day).date(), clock, _NY).astimezone(timezone.utc)
        if not clocks["session_open"] <= clocks["open"] < clocks["close"] <= clocks["session_close"]:
            raise ContractValidationError("calendar session bounds must surround the regular session")
        result[day] = clocks
    return result


def _number(value, name, *, positive=False, integer=False):
    if not isinstance(value, Decimal) or not value.is_finite():
        raise ContractValidationError(name + " must be an actual finite raw JSON number")
    if integer and value != value.to_integral_value():
        raise ContractValidationError(name + " must be a whole raw JSON count")
    text = format(value, "f")
    return accounting_decimal(text, name, positive=positive, nonnegative=not positive)


def _bars(raw, receipt, universe, calendar):
    source = parse_historical_json(raw)
    if not isinstance(source, dict) or set(source) != {"bars", "next_page_token"}:
        raise ContractValidationError("daily bars response must have exact bars and pagination fields")
    if source["next_page_token"] is not None:
        raise ContractValidationError("paginated historical responses are not complete; retain all pages in a future version")
    if not isinstance(source["bars"], dict) or sorted(source["bars"]) != universe:
        raise ContractValidationError("raw historical universe must match exactly")
    if receipt["query"]["symbols"].split(",") != universe:
        raise ContractValidationError("retained bars query must bind the exact sorted universe")
    query_start, query_end = (parse_rfc3339(receipt["query"][field], field) for field in ("start", "end"))
    result = {}
    for symbol in universe:
        rows = source["bars"][symbol]
        if not isinstance(rows, list) or not 1 <= len(rows) <= 10000:
            raise ContractValidationError("every symbol requires bounded nonempty historical bars")
        prior, values = None, {}
        for row in rows:
            if not isinstance(row, dict) or set(row) != {"t", "o", "h", "l", "c", "v", "n", "vw"}:
                raise ContractValidationError("raw daily bar must preserve exact native OHLCV, count and VWAP fields")
            stamp = parse_rfc3339(row["t"], "bar.t")
            day = stamp.astimezone(_NY).date().isoformat()
            midnight = datetime.combine(stamp.astimezone(_NY).date(), time(), _NY).astimezone(timezone.utc)
            if stamp != midnight or not query_start <= stamp <= query_end:
                raise ContractValidationError("daily label must be New York midnight within its retained query")
            if day not in calendar:
                raise ContractValidationError("bar date is absent from the actual returned calendar")
            if prior is not None and stamp <= prior:
                raise ContractValidationError("symbol daily bars must be strictly ordered and unique")
            prior = stamp
            _number(row["n"], "bar.n", integer=True)
            _number(row["vw"], "bar.vw", positive=True)
            values[day] = {"symbol": symbol, "open": _number(row["o"], "bar.open", positive=True),
                "high": _number(row["h"], "bar.high", positive=True), "low": _number(row["l"], "bar.low", positive=True),
                "close": _number(row["c"], "bar.close", positive=True), "volume": _number(row["v"], "bar.volume", integer=True)}
            lower, upper = Decimal(values[day]["low"]), Decimal(values[day]["high"])
            if lower > upper or any(not lower <= Decimal(values[day][field]) <= upper for field in ("open", "close")):
                raise ContractValidationError("historical OHLC range is internally inconsistent")
        result[symbol] = values
    return result


def _reference(path, raw):
    return {"path": path, "sha256": sha256_bytes(raw), "size_bytes": len(raw)}


def build_historical_intake(request, blobs):
    """Project hash-bound observations under a named retrospective assumption.

    Missing eligible bars reject the complete intake. Future or not-yet-assumed
    available sessions are explicitly excluded, never silently filled.
    """
    if not isinstance(request, HistoricalIntakeRequest):
        request = HistoricalIntakeRequest.from_mapping(request)
    recorded = parse_rfc3339(request.recorded_at, "recorded_at")
    sources = request.sources
    bars_receipt = _receipt(blobs, sources["bars_receipt_evidence"], sources["bars_evidence"], "bars", recorded)
    calendar_receipt = _receipt(blobs, sources["calendar_receipt_evidence"], sources["calendar_evidence"], "calendar", recorded)
    dates = request.date_range
    if not calendar_receipt["query"]["start"] <= dates["start"] <= dates["end"] <= calendar_receipt["query"]["end"]:
        raise ContractValidationError("retained calendar query must cover the entire requested date interval")
    first_midnight = datetime.combine(datetime.fromisoformat(dates["start"]).date(), time(), _NY).astimezone(timezone.utc)
    last_midnight = datetime.combine(datetime.fromisoformat(dates["end"]).date(), time(), _NY).astimezone(timezone.utc)
    if not parse_rfc3339(bars_receipt["query"]["start"], "start") <= first_midnight <= last_midnight <= parse_rfc3339(bars_receipt["query"]["end"], "end"):
        raise ContractValidationError("retained bars query must cover the entire requested date interval")
    calendar = _calendar(_blob(blobs, sources["calendar_evidence"]), calendar_receipt)
    bars = _bars(_blob(blobs, sources["bars_evidence"]), bars_receipt, request.universe, calendar)
    if sum(len(values) for values in bars.values()) > bars_receipt["query"]["limit"]:
        raise ContractValidationError("retained bars exceed their declared request limit")
    if any(not dates["start"] <= day <= dates["end"] for values in bars.values() for day in values):
        raise ContractValidationError("raw bars lie outside the declared intake date interval")
    window = [day for day in calendar if dates["start"] <= day <= dates["end"]]
    capture_bound = min(parse_rfc3339(receipt["captured_at"], "captured_at") for receipt in (bars_receipt, calendar_receipt))
    sessions, excluded = [], []
    delay = timedelta(seconds=request.availability_assumption["delay_seconds"])
    for day in window:
        clocks = calendar[day]
        available = clocks["session_close"] + delay
        if available > capture_bound:
            excluded.append(day)
            continue
        missing = [symbol for symbol in request.universe if day not in bars[symbol]]
        if missing:
            raise ContractValidationError("eligible returned calendar session lacks raw bars for " + ",".join(missing) + " on " + day)
        sessions.append({"session_id": "alpaca-session-" + day, "open_at": format_rfc3339(clocks["open"]),
            "close_at": format_rfc3339(clocks["close"]), "available_at": format_rfc3339(available),
            "bars": [bars[symbol][day] for symbol in request.universe]})
    if not sessions:
        raise ContractValidationError("no complete sessions meet the declared availability and capture bounds")
    request_raw = request.to_bytes()
    request_ref = _reference("historical-intake/request.v1.json", request_raw)
    source_refs = [request_ref] + [sources[field] for field in sorted(sources)]
    if len({ref["path"] for ref in source_refs}) != 5 or "historical-intake/dataset.v2.json" in {ref["path"] for ref in source_refs}:
        raise ContractValidationError("source paths collide with reserved derived intake evidence")
    intake_id = "historical-intake-" + sha256_bytes(request_raw)
    assumption = request.availability_assumption
    dataset = TradingResearchDataset.from_mapping({"schema_version": "blackpod.trading_research_dataset.v2",
        "dataset_id": "historical-dataset-" + sha256_bytes(request_raw), "recorded_at": request.recorded_at,
        "universe": request.universe, "provenance": {"source_kind": "GOVERNED_HISTORICAL_INTAKE",
            "source_evidence": source_refs, "timestamp_policy": "DECLARED_RETROSPECTIVE_SESSION_END_PLUS_LAG",
            "historical_point_in_time_verified": False,
            "governed_intake": {"intake_id": intake_id, "request_evidence": request_ref,
                "method_version": "blackpod.alpaca_daily_history_projection.v1"},
            "availability_assumption": {"mode": assumption["policy"], "delay_seconds": assumption["delay_seconds"],
                "declared_by": assumption["declared_by"], "rationale": assumption["rationale"], "assumption_verified": False}},
        "sessions": sessions, "authority": request.authority})
    dataset_raw = dataset.to_bytes()
    dataset_ref = _reference("historical-intake/dataset.v2.json", dataset_raw)
    export = HistoricalIntakeExport.from_mapping({"schema_version": HISTORICAL_INTAKE_VERSION, "intake_id": intake_id,
        "request_evidence": request_ref, "dataset_evidence": dataset_ref,
        "coverage": {"requested_start": dates["start"], "requested_end": dates["end"],
            "calendar_sessions_in_window": len(window), "included_session_count": len(sessions),
            "included_start_session": sessions[0]["session_id"].removeprefix("alpaca-session-"),
            "included_end_session": sessions[-1]["session_id"].removeprefix("alpaca-session-"),
            "excluded_unavailable_sessions": excluded},
        "source_evidence": source_refs, "limitations": list(HISTORICAL_INTAKE_LIMITATIONS),
        "authority": request.authority, "auto_trading_enabled": False})
    evidence = {ref["path"]: _blob(blobs, ref) for ref in sources.values()}
    evidence[request_ref["path"]], evidence[dataset_ref["path"]] = request_raw, dataset_raw
    retained_blobs = {sha256_bytes(raw): raw for raw in evidence.values()}
    return {"export": export, "dataset": dataset, "request": request, "evidence": evidence, "blobs": retained_blobs}


def verify_historical_intake(export, blobs):
    if not isinstance(export, HistoricalIntakeExport):
        export = HistoricalIntakeExport.from_mapping(export)
    request = HistoricalIntakeRequest.from_bytes(_blob(blobs, export.request_evidence))
    replay = build_historical_intake(request, blobs)
    if replay["export"].to_bytes() != export.to_bytes() or replay["dataset"].to_bytes() != _blob(blobs, export.dataset_evidence):
        raise ContractValidationError("retained historical intake differs from deterministic source replay")
    return replay


def validate_historical_dataset(dataset, blobs):
    """Validate a governed dataset directly at the research evidence boundary."""
    if not isinstance(dataset, TradingResearchDataset):
        dataset = TradingResearchDataset.from_mapping(dataset)
    if dataset.schema_version != "blackpod.trading_research_dataset.v2":
        raise ContractValidationError("governed historical replay requires the explicit v2 dataset")
    request_ref = dataset.provenance["governed_intake"]["request_evidence"]
    request = HistoricalIntakeRequest.from_bytes(_blob(blobs, request_ref))
    replay = build_historical_intake(request, blobs)
    if replay["dataset"].to_bytes() != dataset.to_bytes():
        raise ContractValidationError("governed historical dataset differs from its raw-source replay")
    return replay
