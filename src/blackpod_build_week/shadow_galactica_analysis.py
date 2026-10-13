"""Pinned Galactica Spyglass and historical Brigade evidence for SHADOW review.

Only Spyglass's existing pure OHLCV functions and the existing transcript parser
are called. Brigade models, forecast training, Navigator streams and brokers
are never imported. No opinion in a historical transcript is a current vote.
"""
from __future__ import annotations

import math
import re
import sys
import types
from datetime import date, timedelta
from decimal import Context, Decimal, localcontext
from functools import lru_cache

from .contracts.decision_journal import _hash, _object
from .contracts.investment_review import disabled_authority
from .contracts.mission_request import parse_rfc3339, parse_strict_json_object_bytes, normalize_rfc3339
from .contracts.trading_reconciliation import evidence_reference, symbol_text
from .contracts.trading_accounting import accounting_decimal
from .hashing import canonical_json_bytes, sha256_bytes

SCHEMA_VERSION = "blackpod.shadow_galactica_analysis.v1"
SOURCE_PINS = {
    "spyglass.py": "95591a266ae32e4d87ea516bd5a66912385469dda935a933d0ae6170eae05dba",
    "scripts/brigade_debrief.py": "8861d9d41fbb78551e85e703396dc10a2b7e4675928e83001ef63845c6567e6a",
    "agents/blackwell_brigade.py": "cd130e0ce8d6862082af7a3963c75300f2d2a3c8d9e762323d7fff4b301f60be",
}
BAR_LIMIT = 300
CHALLENGE_POLICY_VERSION = "blackpod.shadow_spyglass_challenge.v1"
CHALLENGE_WINDOW_CALENDAR_DAYS = 30
LIMITATIONS = (
    "SPYGLASS_POST_HOC_SWINGS_REQUIRE_RIGHT_HAND_BARS", "PATTERN_CONFIRMATION_IS_HEURISTIC_NOT_FORECAST_PROBABILITY",
    "DAILY_STRUCTURE_IS_NOT_INTRADAY_EXECUTION_EVIDENCE", "HISTORICAL_BRIGADE_VOTES_ARE_NOT_CURRENT_RECOMMENDATIONS",
    "BRIGADE_GENERATION_REQUIRES_GOVERNED_FORECAST_AND_INFERENCE_INPUTS", "DECLARED_LEGACY_MODEL_PROVENANCE_NOT_ATTESTED",
    "SHARED_MARKET_DATA_DOES_NOT_ESTABLISH_INDEPENDENT_EVIDENCE", "NO_EXECUTION_AUTHORITY",
)
_MAX_BYTES = 64 * 1024 * 1024


class ShadowGalacticaAnalysisError(ValueError):
    pass


def _authority():
    return {field: False for field in ("authorization_enabled", "capital_activation_enabled", "execution_enabled", "policy_changes_enabled")}


def _bounded_source(raw, name):
    if not isinstance(raw, bytes) or len(raw) > _MAX_BYTES or sha256_bytes(raw) != SOURCE_PINS[name]:
        raise ShadowGalacticaAnalysisError("the retained " + name + " source differs from the approved native fingerprint")
    return raw


def _reference(path, raw):
    return {"path": path, "sha256": sha256_bytes(raw), "size_bytes": len(raw)}


@lru_cache(maxsize=3)
def _module(name, raw):
    """Execute only approved source bytes in an isolated native module namespace."""
    _bounded_source(raw, name)
    key = "_blackpod_shadow_galactica_" + SOURCE_PINS[name]
    module = types.ModuleType(key)
    module.__file__ = "retained-galactica/" + name
    sys.modules[key] = module
    try:
        exec(compile(raw, module.__file__, "exec"), module.__dict__)
    except Exception as exc:
        sys.modules.pop(key, None)
        raise ShadowGalacticaAnalysisError("approved native shadow module could not load") from exc
    return module


def _libraries():
    try:
        import numpy
        import pandas
    except ImportError as exc:
        raise ShadowGalacticaAnalysisError("existing pandas and numpy are required for native Spyglass; install is not automatic") from exc
    return pandas, numpy


def _number(value, name, *, positive=False):
    if type(value) not in (int, float, str):
        raise ShadowGalacticaAnalysisError(name + " must be a finite numeric observation")
    try:
        number = Decimal(accounting_decimal(str(value), name, positive=positive, nonnegative=True))
    except Exception as exc:
        raise ShadowGalacticaAnalysisError(name + " must be numeric") from exc
    if not number.is_finite() or number < 0 or number > Decimal("1e20") or positive and number <= 0:
        raise ShadowGalacticaAnalysisError(name + " is outside the supported observation range")
    return number


def _json_native(value, *, depth=0):
    """Retain native numbers as labels, rather than binary JSON/probability claims."""
    if depth > 12:
        raise ShadowGalacticaAnalysisError("native fact nesting exceeds the supported bound")
    if value is None or type(value) is bool or type(value) is int:
        return value
    if type(value) is float:
        if not math.isfinite(value):
            raise ShadowGalacticaAnalysisError("native analysis produced a nonfinite fact")
        return repr(value)
    if isinstance(value, str):
        if len(value) > 10000:
            raise ShadowGalacticaAnalysisError("native text exceeds the supported bound")
        return value
    if isinstance(value, (list, tuple)):
        if len(value) > 4096:
            raise ShadowGalacticaAnalysisError("native list exceeds the supported bound")
        return [_json_native(item, depth=depth + 1) for item in value]
    if isinstance(value, dict):
        if len(value) > 128 or any(not isinstance(key, str) for key in value):
            raise ShadowGalacticaAnalysisError("native object exceeds the supported bound")
        return {key: _json_native(item, depth=depth + 1) for key, item in value.items()}
    # pandas Timestamp and NumPy scalar outputs are known native types.
    if value.__class__.__module__.startswith("pandas.") and value.__class__.__name__ == "Timestamp":
        return value.isoformat().replace("+00:00", "Z")
    if value.__class__.__module__.startswith("numpy") and hasattr(value, "item"):
        return _json_native(value.item(), depth=depth + 1)
    raise ShadowGalacticaAnalysisError("unsupported native fact type")


def _frame(rows, captured_at, pandas):
    if not isinstance(rows, list) or len(rows) > 10000:
        raise ShadowGalacticaAnalysisError("daily OHLCV bars must be a bounded list")
    cutoff = parse_rfc3339(captured_at, "captured_at")
    points, prior, excluded, days = [], None, 0, set()
    for row in rows:
        if not isinstance(row, dict) or set(row) - {"t", "o", "h", "l", "c", "v", "n", "vw"} or not {"t", "o", "h", "l", "c", "v"} <= set(row):
            raise ShadowGalacticaAnalysisError("daily bars must use explicit retained Alpaca OHLCV fields")
        when = parse_rfc3339(row["t"], "daily bar timestamp")
        if prior is not None and when <= prior or when > cutoff:
            raise ShadowGalacticaAnalysisError("daily bars must be strictly ordered unique prior observations")
        if when.date() in days:
            raise ShadowGalacticaAnalysisError("a daily-bar universe cannot contain duplicate UTC dates")
        days.add(when.date())
        prior = when
        values = {field: _number(row[field], field, positive=field != "v") for field in ("o", "h", "l", "c", "v")}
        if not values["l"] <= min(values["o"], values["c"]) <= max(values["o"], values["c"]) <= values["h"]:
            raise ShadowGalacticaAnalysisError("OHLC prices are inconsistent")
        # A daily bar on the capture's UTC date has not been proven complete.
        if when.date() >= cutoff.date():
            excluded += 1
            continue
        points.append((when, *(float(values[field]) for field in ("o", "h", "l", "c", "v"))))
    selected = points[-BAR_LIMIT:]
    frame = pandas.DataFrame([row[1:] for row in selected], columns=["Open", "High", "Low", "Close", "Volume"],
                             index=pandas.DatetimeIndex([row[0] for row in selected]))
    return frame, excluded


def _market(raw):
    if not isinstance(raw, bytes) or len(raw) > _MAX_BYTES:
        raise ShadowGalacticaAnalysisError("market capture must be bounded retained bytes")
    try:
        market = parse_strict_json_object_bytes(raw)
        normalize_rfc3339(market.get("captured_at"), "captured_at")
    except ValueError as exc:
        raise ShadowGalacticaAnalysisError("market capture must contain an explicit timestamp and strict JSON") from exc
    bars = market.get("bars")
    if not isinstance(bars, dict) or not bars or len(bars) > 256:
        raise ShadowGalacticaAnalysisError("market capture requires a bounded explicit daily-bar universe")
    for symbol in bars:
        symbol_text(symbol)
    return market


def _brigade_time(value, captured_at):
    capture = parse_rfc3339(captured_at, "market captured_at")
    if isinstance(value, str) and re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value):
        try:
            day = date.fromisoformat(value)
        except ValueError as exc:
            raise ShadowGalacticaAnalysisError("Brigade source date is invalid") from exc
        if day > capture.date():
            raise ShadowGalacticaAnalysisError("historical Brigade source date cannot be in the future")
        # A date-only source has no attested timezone or clock time. Close dates
        # remain uncertain; a gap beyond two calendar days is certainly stale.
        return value, "DATE_ONLY_TIMEZONE_UNSPECIFIED", True if (capture.date() - day).days > 2 else None
    timestamp = normalize_rfc3339(value, "brigade_as_of")
    when = parse_rfc3339(timestamp, "brigade_as_of")
    if when > capture:
        raise ShadowGalacticaAnalysisError("historical Brigade source cannot be in the future")
    return timestamp, "RFC3339", capture - when > timedelta(hours=24)


def _challenge_assessment(structure, captured_at):
    """A fixed SHADOW recency screen; every original native fact is retained."""
    cutoff = parse_rfc3339(captured_at, "market captured_at")
    start = cutoff - timedelta(days=CHALLENGE_WINDOW_CALENDAR_DAYS)
    codes, current, excluded, resistance_indexes = [], [], [], []
    for kind, time_key in (("double_top", "t2"), ("head_shoulders", "tR")):
        for index, pattern in enumerate(structure["patterns"].get(kind, [])):
            if pattern.get("confirmed") is not True:
                continue
            source_time = pattern[time_key]
            when = parse_rfc3339(source_time, "native pattern time")
            fact = {"source_kind": kind, "source_index": index, "source_time": source_time, "reason_code": "BEARISH_PATTERN"}
            (current if start <= when <= cutoff else excluded).append(fact)
            if start <= when <= cutoff:
                codes.append("BEARISH_PATTERN")
    for index, event in enumerate(structure["events"]):
        if event["type"] == "breakout" and event["dir"] == "down":
            when = parse_rfc3339(event["bar"], "native breakout time")
            fact = {"source_kind": "events", "source_index": index, "source_time": event["bar"], "reason_code": "DOWNWARD_BREAKOUT"}
            (current if start <= when <= cutoff else excluded).append(fact)
            if start <= when <= cutoff:
                codes.append("DOWNWARD_BREAKOUT")
    for index, level in enumerate(structure["levels"]):
        if level["kind"] != "resistance":
            continue
        when = parse_rfc3339(level["last_touch"], "native level touch")
        fact = {"source_kind": "levels", "source_index": index, "source_time": level["last_touch"], "reason_code": "RESISTANCE_LEVEL"}
        if start <= when <= cutoff:
            resistance_indexes.append(index)
        else:
            excluded.append(fact)
    return {"policy_version": CHALLENGE_POLICY_VERSION, "window_calendar_days": CHALLENGE_WINDOW_CALENDAR_DAYS,
            "comparison_at": captured_at, "window_started_at": start.isoformat().replace("+00:00", "Z"),
            "current_reason_codes": sorted(set(codes)), "current_pattern_and_event_refs": current,
            "excluded_historical_refs": excluded, "current_resistance_level_indexes": resistance_indexes}


def build_shadow_galactica_analysis(market_raw, spyglass_source, *, generated_at,
        brigade_transcript=None, brigade_parser_source=None, brigade_producer_source=None, brigade_as_of=None):
    """Run existing Spyglass on frozen bars and optionally parse retained opinions."""
    generated_at = normalize_rfc3339(generated_at, "generated_at")
    market = _market(market_raw)
    if parse_rfc3339(market["captured_at"], "captured_at") > parse_rfc3339(generated_at, "generated_at"):
        raise ShadowGalacticaAnalysisError("market capture cannot occur after analysis generation")
    _bounded_source(spyglass_source, "spyglass.py")
    supplied = (brigade_transcript, brigade_parser_source, brigade_producer_source, brigade_as_of)
    if any(value is not None for value in supplied) and not all(value is not None for value in supplied):
        raise ShadowGalacticaAnalysisError("historical Brigade import requires transcript, parser, producer fingerprint and explicit source time together")
    pandas, numpy = _libraries()
    # Validate all data before loading approved code or running a native function.
    frames = {symbol: _frame(rows, market["captured_at"], pandas) for symbol, rows in sorted(market["bars"].items())}
    native = _module("spyglass.py", spyglass_source)
    from dataclasses import asdict
    sr_config, pattern_config = native.SRConfig(), native.PatternConfig()
    observations = []
    for symbol, (frame, excluded) in frames.items():
        usable = len(frame) >= 60
        structure = native.analyze_structure(frame, sr_config, pattern_config) if usable else {"levels": [], "events": [], "patterns": {}}
        normalized = _json_native(structure)
        observations.append({"symbol": symbol, "status": "ANALYZED_SHADOW_ONLY" if usable else "INSUFFICIENT_HISTORY",
            "bar_count": len(frame), "bar_as_of": None if frame.empty else frame.index[-1].isoformat().replace("+00:00", "Z"),
            "excluded_unproven_daily_bars": excluded, "structure": normalized,
            "challenge_assessment": _challenge_assessment(normalized, market["captured_at"]), "confidence_is_probability": False})
    sources = {"spyglass": _reference("galactica/spyglass.py", spyglass_source),
               "brigade_parser": None, "brigade_producer": None, "brigade_transcript": None}
    brigade = {"status": "MISSING_CURRENT_FORECASTS_AND_INFERENCE", "source_as_of": None, "stale": None,
        "source_time_precision": None,
        "parsed_report": None, "source_model_declared": None, "provider_provenance_verified": False,
        "member_coverage": [],
        "current_generation_enabled": False, "current_opinions_available": False,
        "reason_codes": ["NO_CURRENT_SOURCE_BOUND_FORECASTS", "INFERENCE_GENERATION_NOT_ENABLED"]}
    if brigade_transcript is not None:
        if not isinstance(brigade_transcript, bytes) or len(brigade_transcript) > 4 * 1024 * 1024:
            raise ShadowGalacticaAnalysisError("historical Brigade transcript must be bounded bytes")
        _bounded_source(brigade_parser_source, "scripts/brigade_debrief.py")
        _bounded_source(brigade_producer_source, "agents/blackwell_brigade.py")
        brigade_as_of, precision, stale = _brigade_time(brigade_as_of, market["captured_at"])
        try:
            transcript = brigade_transcript.decode("utf-8")
        except UnicodeError as exc:
            raise ShadowGalacticaAnalysisError("historical Brigade transcript must be UTF-8") from exc
        declared_dates = re.findall(r"\bDate:\s*([0-9]{4}-[0-9]{2}-[0-9]{2})\b", transcript)
        if declared_dates and (len(set(declared_dates)) != 1 or declared_dates[0] != brigade_as_of[:10]):
            raise ShadowGalacticaAnalysisError("supplied Brigade source time conflicts with its retained header date")
        try:
            parsed = _module("scripts/brigade_debrief.py", brigade_parser_source).parse_log(transcript)
        except (ValueError, TypeError, AttributeError, IndexError) as exc:
            raise ShadowGalacticaAnalysisError("historical Brigade transcript could not be parsed by its retained native parser") from exc
        # The native parser's wall-clock field describes parsing, not model time.
        parsed["generated_at"] = generated_at
        parsed = _json_native(parsed)
        expected_members = {"Blackwell_Scout", "Blackwell_Sentry", "Blackwell_Advisor", "Blackwell_Canary", "Blackwell_Pathfinder", "Blackwell_Decay"}
        coverage = []
        for row in parsed["symbols"]:
            symbol_text(row["symbol"])
            present = {opinion["module"] for opinion in row["brigade"]}
            coverage.append({"symbol": row["symbol"], "present_members": sorted(present),
                "missing_members": sorted(expected_members - present), "source_row_incomplete": row["incomplete"],
                "current_generation_status": "DEFER"})
        sources.update(brigade_parser=_reference("galactica/brigade_debrief.py", brigade_parser_source),
            brigade_producer=_reference("galactica/blackwell_brigade.py", brigade_producer_source),
            brigade_transcript=_reference("galactica/brigade-transcript.txt", brigade_transcript))
        declared = re.search(r"Model:\s*([^\n║]+)", transcript)
        brigade.update(status="HISTORICAL_INPUT_ONLY", source_as_of=brigade_as_of,
            source_time_precision=precision, stale=stale,
            parsed_report=parsed, source_model_declared=None if declared is None else declared.group(1).strip(),
            member_coverage=coverage,
            reason_codes=["IMPORTED_HISTORICAL_OPINIONS_NOT_CURRENT_VOTES", "LEGACY_MODEL_AND_SOURCE_RELATIONSHIP_NOT_ATTESTED",
                          "NO_CURRENT_SOURCE_BOUND_FORECASTS", "INFERENCE_GENERATION_NOT_ENABLED"])
    return {"schema_version": SCHEMA_VERSION, "generated_at": generated_at,
        "market_source": {"sha256": sha256_bytes(market_raw), "size_bytes": len(market_raw)}, "source_evidence": sources,
        "runtime_fingerprint": {"python": str(sys.version_info.major) + "." + str(sys.version_info.minor), "pandas": pandas.__version__, "numpy": numpy.__version__},
        "spyglass": {"status": "CONNECTED_SHADOW_ONLY", "timeframe": "1Day", "bar_limit": BAR_LIMIT,
            "sr_config": asdict(sr_config), "pattern_config": asdict(pattern_config), "observations": observations},
        "brigade": brigade, "limitations": list(LIMITATIONS), "authority": _authority()}


def evidence_for_shadow_galactica_analysis(market_raw, spyglass_source, *, brigade_transcript=None,
        brigade_parser_source=None, brigade_producer_source=None):
    result = {"galactica/spyglass.py": _bounded_source(spyglass_source, "spyglass.py")}
    if brigade_transcript is not None:
        result.update({"galactica/brigade_debrief.py": _bounded_source(brigade_parser_source, "scripts/brigade_debrief.py"),
            "galactica/blackwell_brigade.py": _bounded_source(brigade_producer_source, "agents/blackwell_brigade.py"),
            "galactica/brigade-transcript.txt": brigade_transcript})
    return result


def validate_shadow_galactica_analysis(packet, market, blobs):
    """Reproduce every native fact from retained, pinned inputs and source bytes."""
    packet = _object(packet, {"schema_version", "generated_at", "market_source", "source_evidence", "runtime_fingerprint",
                            "spyglass", "brigade", "limitations", "authority"}, "shadow Galactica analysis")
    if packet["schema_version"] != SCHEMA_VERSION:
        raise ShadowGalacticaAnalysisError("unsupported Galactica shadow packet version")
    disabled_authority(packet["authority"])
    market_source = _object(packet["market_source"], {"sha256", "size_bytes"}, "market_source")
    market_source["sha256"] = _hash(market_source["sha256"], "market_source.sha256")
    if type(market_source["size_bytes"]) is not int or not 0 <= market_source["size_bytes"] <= _MAX_BYTES:
        raise ShadowGalacticaAnalysisError("market_source.size_bytes must be bounded")
    raw = blobs.get(market_source["sha256"])
    if not isinstance(raw, bytes) or sha256_bytes(raw) != market_source["sha256"] or len(raw) != market_source["size_bytes"] or canonical_json_bytes(_market(raw)) != canonical_json_bytes(market):
        raise ShadowGalacticaAnalysisError("native analysis must bind exactly the supplied retained market capture")
    refs = _object(packet["source_evidence"], {"spyglass", "brigade_parser", "brigade_producer", "brigade_transcript"}, "source_evidence")
    retained = {}
    for name, reference in refs.items():
        if reference is None:
            retained[name] = None
            continue
        reference = evidence_reference(reference, "source_evidence." + name)
        source = blobs.get(reference["sha256"])
        if not isinstance(source, bytes) or sha256_bytes(source) != reference["sha256"] or len(source) != reference["size_bytes"]:
            raise ShadowGalacticaAnalysisError("retained Galactica source evidence differs in hash or size")
        retained[name] = source
    rebuilt = build_shadow_galactica_analysis(raw, retained["spyglass"], generated_at=packet["generated_at"],
        brigade_transcript=retained["brigade_transcript"], brigade_parser_source=retained["brigade_parser"],
        brigade_producer_source=retained["brigade_producer"], brigade_as_of=packet["brigade"]["source_as_of"])
    if canonical_json_bytes(rebuilt) != canonical_json_bytes(packet):
        raise ShadowGalacticaAnalysisError("Galactica shadow facts do not reproduce their retained native inputs")
    return packet


validate_galactica_analysis = validate_shadow_galactica_analysis


def symbol_challenges(packet):
    """Challenge labels describe native daily structures, never trade instructions."""
    result = {}
    for row in packet["spyglass"]["observations"]:
        reasons = []
        if row["status"] != "ANALYZED_SHADOW_ONLY":
            reasons.append("SPYGLASS_INSUFFICIENT_HISTORY")
        reasons.extend(row["challenge_assessment"]["current_reason_codes"])
        result[row["symbol"]] = sorted(set(reasons))
    return result


def symbol_gate(packet, symbol, price, stop_distance):
    """Compare retained resistance headroom with an explicit proposed scenario.

    The caller supplies current reference price and stop-distance proposal. A
    resistance challenge is evidence to defer fresh long research, not a stop,
    order, forecast or loss guarantee.
    """
    row = next((row for row in packet["spyglass"]["observations"] if row["symbol"] == symbol), None)
    reasons = symbol_challenges(packet).get(symbol, ["SPYGLASS_SYMBOL_NOT_REVIEWED"])
    headroom = None
    if row is not None:
        reference = Decimal(accounting_decimal(price, "reference_price", positive=True, output=True))
        distance = Decimal(accounting_decimal(stop_distance, "stop_distance", positive=True, output=True))
        with localcontext(Context(prec=256)):
            current_levels = row["challenge_assessment"]["current_resistance_level_indexes"]
            above = [Decimal(level["price"]) - reference for index, level in enumerate(row["structure"]["levels"])
                     if index in current_levels and level["kind"] == "resistance" and Decimal(level["price"]) >= reference]
        if above:
            nearest = min(above)
            headroom = format(nearest, "f")
            if nearest < distance:
                reasons = sorted(set(reasons) | {"RESISTANCE_HEADROOM_LT_STOP_SCENARIO"})
    return {"blocking_reason_codes": reasons, "nearest_resistance_headroom_usd": headroom,
            "execution_authority_granted": False}
