"""Governed, source-pinned Brigade recommendations with zero trading authority.

The five original Galactica agent prompt builders and parsers are reused in a
restricted AST namespace. Their execution-plan builder and Watchtower are not
loaded. Observed context comes only from retained bars; a future forecast path
is never represented as realized price history. Provider calls are injected,
explicitly enabled, bounded, and captured for provider-free journal replay.
"""
from __future__ import annotations

import __future__
import ast
import builtins
import copy
import math
import re
import sys
from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal, InvalidOperation
from functools import lru_cache
from typing import Any, Dict, Optional, Tuple

from .contracts.mission_request import parse_rfc3339, parse_strict_json_object_bytes
from .contracts.trading_reconciliation import evidence_reference, symbol_text
from .desk_review_sources import validate_market_packet
from .hashing import canonical_json_bytes, sha256_bytes

SCHEMA_VERSION = "blackpod.shadow_brigade_analysis.v1"
SCHEMA_VERSION_V2 = "blackpod.shadow_brigade_analysis.v2"
RESPONSE_CONTRACT = "blackpod.brigade_member_response.v1"
CONTEXT_POLICY_VERSION = "blackpod.shadow_brigade_context.v1"
BRIGADE_SOURCE_SHA256 = "cd130e0ce8d6862082af7a3963c75300f2d2a3c8d9e762323d7fff4b301f60be"
DECAY_SOURCE_SHA256 = "0798769b926b95d808cd18eb54804d4f77af90a6251e34167fc36dfe56146cfb"
MEMBERS = ("Blackwell_Scout", "Blackwell_Sentry", "Blackwell_Advisor", "Blackwell_Canary", "Blackwell_Pathfinder")
MAX_SOURCE_BYTES = 256 * 1024
MAX_RESPONSE_BYTES = 32 * 1024
MAX_GENERATION_CALLS = 100
LIMITATIONS = (
    "SHADOW_RECOMMENDATIONS_ARE_NOT_AUTHORIZATIONS_OR_ORDERS",
    "NATIVE_TRADE_PLAN_BUILDER_IS_SUPPRESSED",
    "AGENT_CONFIDENCE_IS_A_HEURISTIC_LABEL_NOT_A_PROBABILITY",
    "FIVE_AGENT_PERSONAS_SHARE_FORECAST_MARKET_AND_MODEL_EVIDENCE",
    "FORECAST_PATH_IS_NOT_REALIZED_HISTORY",
    "IEX_VOLUME_IS_NOT_CONSOLIDATED_MARKET_VOLUME",
    "DECLARED_FORECAST_AND_MODEL_PROVENANCE_IS_NOT_PROVIDER_ATTESTATION",
    "DECAY_IS_A_SEPARATE_NATIVE_SHADOW_CALCULATION_NOT_WATCHTOWER_COVERAGE",
    "NO_POLICY_IMPROVEMENT_CAPITAL_TRANSFER_OR_EXECUTION_AUTHORITY",
)
_AUTHORITY = {"authorization_enabled": False, "capital_activation_enabled": False,
              "execution_enabled": False, "policy_changes_enabled": False}
_BRIGADE_DEFINITIONS = ("BlackwellBrigadeOpinion", "BlackwellBrigadeAgent", "ScoutAgent", "SentryAgent", "AdvisorAgent", "CanaryAgent", "PathfinderAgent")
_DECAY_DEFINITIONS = ("DecayConfig", "_pct", "_max_drawdown_pct", "_slope", "_impulse_count", "Blackwell_Decay")


class ShadowBrigadeAnalysisError(ValueError):
    pass


def _reference(path, raw):
    return {"path": path, "sha256": sha256_bytes(raw), "size_bytes": len(raw)}


def _retained(blobs, reference):
    ref = evidence_reference(reference)
    raw = blobs.get(ref["sha256"])
    if not isinstance(raw, bytes) or len(raw) != ref["size_bytes"] or sha256_bytes(raw) != ref["sha256"]:
        raise ShadowBrigadeAnalysisError("Brigade retained evidence is missing or differs in size/hash")
    return raw


def _source(raw, expected, name):
    if not isinstance(raw, bytes) or not 0 < len(raw) <= MAX_SOURCE_BYTES or sha256_bytes(raw) != expected:
        raise ShadowBrigadeAnalysisError(name + " differs from the reviewed source pin")


def _namespace(raw, name, selected, dependencies):
    tree = ast.parse(raw.decode("utf-8"), filename=name)
    chosen = [node for node in tree.body if isinstance(node, (ast.FunctionDef, ast.ClassDef)) and node.name in selected]
    if {node.name for node in chosen} != set(selected):
        raise ShadowBrigadeAnalysisError("reviewed native definition closure changed")
    for node in chosen:
        if any(isinstance(child, (ast.Import, ast.ImportFrom)) for child in ast.walk(node)):
            raise ShadowBrigadeAnalysisError("selected native definition contains an import")
    module = ast.Module(body=chosen, type_ignores=[])
    ast.fix_missing_locations(module)
    namespace = {"__name__": __name__, "__builtins__": {key: getattr(builtins, key) for key in (
        "__build_class__", "object", "str", "float", "int", "bool", "len", "range", "max", "min", "round", "super", "Exception",
    )}, "dataclass": dataclass, "Dict": Dict, "Any": Any, "Optional": Optional, "Tuple": Tuple,
        # Calling the native plan builder is intercepted before any quantity,
        # notional, exit, stop, order type or execution guidance is constructed.
        "build_trade_plan": lambda **_kwargs: None, **dependencies}
    exec(compile(module, name, "exec", flags=__future__.annotations.compiler_flag, dont_inherit=True), namespace)
    return namespace


@lru_cache(maxsize=2)
def _native(brigade_source, decay_source):
    _source(brigade_source, BRIGADE_SOURCE_SHA256, "Brigade")
    _source(decay_source, DECAY_SOURCE_SHA256, "Decay")
    try:
        import pandas
        import numpy
    except ImportError as exc:
        raise ShadowBrigadeAnalysisError("existing pandas/numpy are required; no automatic installation") from exc
    brigade = _namespace(brigade_source, "retained-galactica/agents/blackwell_brigade.py", _BRIGADE_DEFINITIONS, {"pd": pandas})
    decay = _namespace(decay_source, "retained-galactica/agents/decay.py", _DECAY_DEFINITIONS, {"np": numpy, "math": math})
    return brigade, decay, pandas, numpy


def _number(value, name, *, nonnegative=False):
    if type(value) not in (str, int, float):
        raise ShadowBrigadeAnalysisError(name + " must be finite numeric evidence")
    try:
        number = Decimal(str(value))
    except InvalidOperation as exc:
        raise ShadowBrigadeAnalysisError(name + " must be finite") from exc
    if not number.is_finite() or abs(number) > Decimal("1e20") or nonnegative and number < 0:
        raise ShadowBrigadeAnalysisError(name + " is outside supported bounds")
    return float(number)


def _json_native(value):
    if value is None or type(value) in (bool, int, str):
        return value
    if type(value) is float:
        if not math.isfinite(value):
            raise ShadowBrigadeAnalysisError("native Brigade produced a nonfinite number")
        return repr(value)
    if isinstance(value, dict):
        return {key: _json_native(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_native(item) for item in value]
    if value.__class__.__module__.startswith("numpy") and hasattr(value, "item"):
        return _json_native(value.item())
    raise ShadowBrigadeAnalysisError("native Brigade produced an unsupported fact")


def _market(raw, blobs, shadow_as_of, generated_at):
    if not isinstance(raw, bytes) or len(raw) > 16 * 1024 * 1024:
        raise ShadowBrigadeAnalysisError("market packet must be bounded retained bytes")
    market = validate_market_packet(parse_strict_json_object_bytes(raw), blobs)
    captured = parse_rfc3339(market["captured_at"], "captured_at")
    as_of = parse_rfc3339(shadow_as_of, "shadow_as_of")
    generated = parse_rfc3339(generated_at, "generated_at")
    if captured > as_of or generated < as_of:
        raise ShadowBrigadeAnalysisError("market capture, forecast assessment and Brigade generation timestamps are inconsistent")
    reasons = []
    if generated - captured > timedelta(hours=24):
        reasons.append("MARKET_CAPTURE_STALE")
    if generated - as_of > timedelta(hours=24):
        reasons.append("FORECAST_ASSESSMENT_STALE")
    return market, captured, generated, reasons


def _observations(market, symbol, captured):
    values, prior, dates = [], None, set()
    for raw in market["bars"].get(symbol, []):
        if not isinstance(raw, dict) or not {"t", "o", "h", "l", "c", "v"} <= set(raw):
            raise ShadowBrigadeAnalysisError("observed bars require timestamped OHLCV fields")
        when = parse_rfc3339(raw["t"], "observed bar timestamp")
        if when > captured or prior is not None and when <= prior or when.date() in dates:
            raise ShadowBrigadeAnalysisError("observed daily bars must be ordered unique past observations")
        prior = when
        dates.add(when.date())
        o, h, low, close = [_number(raw[field], field, nonnegative=True) for field in ("o", "h", "l", "c")]
        volume = _number(raw["v"], "volume", nonnegative=True)
        if not 0 < low <= min(o, close) <= max(o, close) <= h:
            raise ShadowBrigadeAnalysisError("observed OHLC prices are inconsistent")
        if when.date() < captured.date():
            values.append((when, close, volume))
    return values[-300:]


def _forecast_path(rows):
    eligible = [row for row in rows if row["gate"] == "CURRENT_SHADOW_ELIGIBLE"]
    if not eligible:
        return [], ["NO_CURRENT_GOVERNED_FORECAST"]
    signatures = {(row.get("source_id"), row.get("model_id"), row.get("model_version"), row.get("issued_at"),
                   row.get("feature_cutoff"), row.get("training_cutoff")) for row in eligible}
    if len(signatures) != 1:
        return [], ["AMBIGUOUS_CURRENT_FORECAST_ORIGINS"]
    if any(row.get("units") != "PRICE_USD" or row.get("value_semantics") != "PREDICTED_CLOSE_LEVEL" for row in eligible):
        return [], ["UNSUPPORTED_FORECAST_VALUE_SEMANTICS"]
    result = sorted(eligible, key=lambda row: parse_rfc3339(row["target_at"], "forecast target_at"))
    if len({parse_rfc3339(row["target_at"], "forecast target_at") for row in result}) != len(result):
        return [], ["DUPLICATE_CURRENT_FORECAST_TARGET"]
    return result, []


def _context(forecasts, observed, pandas):
    if not forecasts:
        return None, None
    last = forecasts[-1]
    q10, q50, q90 = [_number(last[field], field, nonnegative=True) for field in ("q10", "q50", "q90")]
    if not 0 < q10 <= q50 <= q90:
        raise ShadowBrigadeAnalysisError("governed USD forecast quantiles must be positive and ordered")
    band = q90 - q10
    band_safe = max(1e-9, abs(band))
    closes = pandas.Series([item[1] for item in observed], dtype=float)
    sma3 = float(closes.tail(3).mean()) if len(closes) >= 10 else None
    sma10 = float(closes.tail(10).mean()) if len(closes) >= 10 else None
    trend_strength = (sma3 / sma10 - 1.0) if sma10 is not None else None
    z_score = None
    if len(closes) >= 20:
        window = closes.tail(20)
        sigma = float(window.std(ddof=0))
        z_score = (float(closes.iloc[-1]) - float(window.mean())) / sigma if sigma > 1e-9 else 0.0
    ratio = None
    if len(closes) >= 21:
        returns = closes.pct_change().dropna()
        recent = float(returns.tail(14).std(ddof=0))
        base = float(returns.tail(min(60, len(returns))).std(ddof=0))
        ratio = recent / base if base > 1e-9 else 1.0
    regime = None if ratio is None else "HIGH" if ratio >= 1.35 else "LOW" if ratio <= 0.75 else "NORMAL"
    volume_ratio = None
    if len(observed) >= 21:
        mean_volume = sum(item[2] for item in observed[-21:-1]) / 20
        if mean_volume > 0:
            volume_ratio = observed[-1][2] / mean_volume
    price_change = (observed[-1][1] / observed[-2][1] - 1.0) * 100 if len(observed) >= 2 else None
    context = {"q10": q10, "q50": q50, "q90": q90, "band": band,
               "skew": ((q90 - q50) - (q50 - q10)) / band_safe,
               "tail_down_pct": (q50 - q10) / q50, "tail_up_pct": (q90 - q50) / q50,
               "band_tot_pct": band / q50, "sma3": sma3, "sma10": sma10,
               "uptrend": trend_strength is not None and trend_strength > 0.005,
               "downtrend": trend_strength is not None and trend_strength < -0.005,
               "z_score": z_score, "regime": regime, "reg_ratio": ratio,
               "volume_ratio": volume_ratio, "volume_available": volume_ratio is not None,
               "price_change_pct": price_change}
    frame = pandas.DataFrame([{key.upper(): _number(row[key], key, nonnegative=True) for key in ("q10", "q50", "q90")} for row in forecasts])
    return context, frame


def _member_reasons(member, forecasts, observed, context, base_reasons, generated):
    reasons = list(base_reasons)
    if forecasts and any(parse_rfc3339(row["target_at"], "target_at") <= generated for row in forecasts):
        reasons.append("FORECAST_TARGET_NO_LONGER_FUTURE")
    for field in ("issued_at", "feature_cutoff", "training_cutoff"):
        if forecasts and any(generated - parse_rfc3339(row[field], field) > timedelta(hours=24) for row in forecasts):
            reasons.append(field.upper() + "_STALE_AT_GENERATION")
    if not observed:
        reasons.append("NO_OBSERVED_MARKET_HISTORY")
    elif generated - observed[-1][0] > timedelta(days=5):
        reasons.append("OBSERVED_HISTORY_STALE")
    minimum = {"Blackwell_Scout": 21, "Blackwell_Sentry": 1, "Blackwell_Advisor": 21, "Blackwell_Canary": 21, "Blackwell_Pathfinder": 10}[member]
    if len(observed) < minimum:
        reasons.append("INSUFFICIENT_OBSERVED_HISTORY")
    if member == "Blackwell_Pathfinder" and len(forecasts) < 3:
        reasons.append("INSUFFICIENT_FORECAST_PATH_TARGETS")
    if member == "Blackwell_Canary" and (context is None or not context["volume_available"]):
        reasons.append("OBSERVED_VOLUME_UNAVAILABLE")
    return sorted(set(reasons))


def _response_validation(response):
    if not isinstance(response, str) or len(response.encode("utf-8")) > MAX_RESPONSE_BYTES:
        return ["UNSUPPORTED_OR_OVERSIZED_RESPONSE"]
    labels = {}
    for line in response.splitlines():
        # Match the original parser's exact label/colon convention. Accepting
        # "ACTION : BUY" would falsely promote its native fallback HOLD.
        found = re.match(r"^\s*(ACTION|CONFIDENCE|REASONING):(.*)$", line, re.I)
        if found:
            key = found.group(1).upper()
            labels.setdefault(key, []).append(found.group(2).strip())
    reasons = []
    if set(labels) != {"ACTION", "CONFIDENCE", "REASONING"} or any(len(value) != 1 for value in labels.values()):
        reasons.append("RESPONSE_LABELS_MISSING_OR_DUPLICATED")
    if len(labels.get("ACTION", [])) == 1 and labels["ACTION"][0].upper() not in {"BUY", "EXIT", "HOLD", "WATCH"}:
        reasons.append("INVALID_ACTION_LABEL")
    if len(labels.get("CONFIDENCE", [])) == 1:
        try:
            confidence = Decimal(labels["CONFIDENCE"][0])
            if not confidence.is_finite() or not 0 <= confidence <= 1:
                reasons.append("INVALID_CONFIDENCE_LABEL")
        except InvalidOperation:
            reasons.append("INVALID_CONFIDENCE_LABEL")
    if len(labels.get("REASONING", [])) == 1 and not labels["REASONING"][0]:
        reasons.append("EMPTY_REASONING_LABEL")
    return reasons


class _CaptureClient:
    def __init__(self, symbol, member, context, forecasts, records, supplied, generator, count, response_contract=None):
        self.symbol, self.member = symbol, member
        self.context, self.forecasts = context, forecasts
        self.records, self.supplied, self.generator, self.count = records, supplied, generator, count
        self.response_contract = response_contract
        self.structured_response = self.native_response_projection = None
        self.structured_reason_codes = []

    def generate(self, prompt, *, system, temperature, max_tokens):
        request = {"symbol": self.symbol, "member": self.member, "mode": "SHADOW", "prompt": prompt,
                   "system": system, "temperature": repr(temperature), "max_tokens": max_tokens,
                   "context_sha256": sha256_bytes(canonical_json_bytes(_json_native(self.context))),
                   "forecast_row_ids": [row["row_id"] for row in self.forecasts]}
        key = (self.symbol, self.member)
        if self.supplied is not None:
            if key not in self.supplied:
                response, error = None, "RETAINED_RESPONSE_MISSING"
            else:
                saved = self.supplied[key]
                if saved["request"] != request:
                    raise ShadowBrigadeAnalysisError("retained Brigade request differs from deterministic native prompt/context")
                response, error = saved["response_text"], saved["error_code"]
        elif self.generator is not None:
            if self.count[0] >= MAX_GENERATION_CALLS:
                response, error = None, "SHADOW_GENERATION_CALL_LIMIT"
            else:
                self.count[0] += 1
                try:
                    response = self.generator(copy.deepcopy(request))
                    error = None
                except Exception:
                    # Exceptions can contain credentials or backend responses.
                    # Preserve only a deterministic code; do not expose text.
                    response, error = None, "SHADOW_GENERATION_FAILED"
        else:
            response, error = None, "INFERENCE_DISABLED"
        if self.response_contract is not None:
            try:
                supported = isinstance(response, str) and len(response.encode("utf-8")) <= MAX_RESPONSE_BYTES
            except UnicodeEncodeError:
                supported = False
            if error is None and not supported:
                response, error = None, "UNSUPPORTED_OR_OVERSIZED_RESPONSE"
        elif response is not None and (not isinstance(response, str) or len(response.encode("utf-8")) > MAX_RESPONSE_BYTES):
            response, error = None, "UNSUPPORTED_OR_OVERSIZED_RESPONSE"
        record = {"request": request, "response_text": response, "error_code": error}
        self.records.append(record)
        if self.response_contract is not None:
            if error is not None:
                self.structured_reason_codes = [error]
                return ""
            from .contracts.brigade_response import parse_member_response, native_label_projection
            from .contracts.mission_request import ContractValidationError
            try:
                structured = parse_member_response(response, expected_member=self.member, expected_symbol=self.symbol)
                self.structured_response = structured.to_dict()
                self.native_response_projection = native_label_projection(structured)
            except ContractValidationError:
                self.structured_reason_codes = ["STRUCTURED_RESPONSE_INVALID"]
                return ""
            return self.native_response_projection
        return response if response is not None else ""


def _supplied_transcripts(transcripts, *, response_contract=None):
    if transcripts is None:
        return None
    if not isinstance(transcripts, list) or len(transcripts) > MAX_GENERATION_CALLS:
        raise ShadowBrigadeAnalysisError("retained Brigade transcripts exceed the supported call bound")
    supplied = {}
    for record in transcripts:
        if not isinstance(record, dict) or set(record) != {"request", "response_text", "error_code"}:
            raise ShadowBrigadeAnalysisError("retained Brigade response record shape is invalid")
        request = record["request"]
        if not isinstance(request, dict) or set(request) != {"symbol", "member", "mode", "prompt", "system", "temperature", "max_tokens", "context_sha256", "forecast_row_ids"}:
            raise ShadowBrigadeAnalysisError("retained Brigade request shape is invalid")
        symbol_text(request["symbol"])
        if request["member"] not in MEMBERS or request["mode"] != "SHADOW":
            raise ShadowBrigadeAnalysisError("retained Brigade member/mode is invalid")
        response, error = record["response_text"], record["error_code"]
        if response_contract is not None and isinstance(response, str):
            try:
                response.encode("utf-8")
            except UnicodeEncodeError as exc:
                raise ShadowBrigadeAnalysisError("retained Brigade response must be valid UTF-8 text") from exc
        if response is not None and (not isinstance(response, str) or len(response.encode("utf-8")) > MAX_RESPONSE_BYTES):
            raise ShadowBrigadeAnalysisError("retained Brigade response must be bounded text")
        if error not in {None, "INFERENCE_DISABLED", "RETAINED_RESPONSE_MISSING", "SHADOW_GENERATION_FAILED", "SHADOW_GENERATION_CALL_LIMIT", "UNSUPPORTED_OR_OVERSIZED_RESPONSE", "RESPONSE_EXPIRED_AFTER_GENERATION"} or (response is None) == (error is None):
            raise ShadowBrigadeAnalysisError("retained response/error status is inconsistent")
        key = (request["symbol"], request["member"])
        if key in supplied:
            raise ShadowBrigadeAnalysisError("duplicate retained Brigade member response")
        supplied[key] = record
    return supplied


def _intake(value):
    from .contracts.forecast_intake import ForecastIntake
    return value if isinstance(value, ForecastIntake) else ForecastIntake.from_mapping(value)


def build_shadow_brigade_analysis(intake, market_raw, brigade_source, decay_source, *, generated_at,
                                  blobs, transcripts=None, text_generator=None, allow_generation=False, symbols=None,
                                  response_contract=None):
    """Calculate source-bound evidence, or defer; no implicit inference occurs.

    ``text_generator`` receives one read-only SHADOW request mapping and returns
    text. Caller owns its explicitly permitted transport, model configuration,
    timeout and provenance capture. It cannot receive an execution capability.
    Replay requires the exact retained requests, responses and source bytes.
    """
    from .forecast_intake import assess_forecast_intake
    intake = _intake(intake)
    if response_contract is not None and response_contract != RESPONSE_CONTRACT:
        raise ShadowBrigadeAnalysisError("unsupported Brigade response contract")
    intake_doc = intake.to_mapping()
    result = assess_forecast_intake(intake, blobs)
    if type(allow_generation) is not bool or text_generator is not None and not allow_generation:
        raise ShadowBrigadeAnalysisError("fresh shadow generation requires explicit opt-in")
    if transcripts is not None and text_generator is not None:
        raise ShadowBrigadeAnalysisError("generation and retained replay cannot be combined")
    if allow_generation and text_generator is None:
        raise ShadowBrigadeAnalysisError("shadow generation opt-in requires an injected text generator")
    if text_generator is not None and not callable(text_generator):
        raise ShadowBrigadeAnalysisError("shadow generator must be a callable")
    parse_rfc3339(generated_at, "generated_at")
    market, captured, generated, market_reasons = _market(market_raw, blobs, result["shadow_as_of"], generated_at)
    native, decay_native, pandas, numpy = _native(brigade_source, decay_source)
    supplied = _supplied_transcripts(transcripts, response_contract=response_contract)
    grouped = {}
    for row in result["rows"]:
        grouped.setdefault(row["symbol"], []).append(row)
    if symbols is None:
        selected_symbols = sorted(grouped)
    else:
        if not isinstance(symbols, (list, tuple)) or not symbols:
            raise ShadowBrigadeAnalysisError("Brigade symbols must be an explicit nonempty bounded sequence")
        selected_symbols = [symbol_text(symbol) for symbol in symbols]
        if len(set(selected_symbols)) != len(selected_symbols):
            raise ShadowBrigadeAnalysisError("Brigade symbols must be unique")
        selected_symbols = sorted(selected_symbols)
    if not 1 <= len(selected_symbols) <= 8:
        raise ShadowBrigadeAnalysisError("a bounded Brigade shadow review requires one to eight symbols")
    grouped = {symbol: grouped.get(symbol, []) for symbol in selected_symbols}
    records, symbols, count = [], [], [0]
    used = set()
    for symbol in sorted(grouped):
        observed = _observations(market, symbol, captured)
        forecasts, reasons = _forecast_path(grouped[symbol])
        context, frame = _context(forecasts, observed, pandas)
        opinions, coverage = [], []
        for member, class_name in zip(MEMBERS, _BRIGADE_DEFINITIONS[2:]):
            reasons_member = _member_reasons(member, forecasts, observed, context, reasons + market_reasons, generated)
            if reasons_member:
                coverage.append({"member": member, "status": "DEFER", "reason_codes": reasons_member})
                continue
            client = _CaptureClient(symbol, member, context, forecasts, records, supplied, text_generator, count, response_contract)
            opinion = native[class_name](client).analyze(symbol, frame, context)
            record = records[-1]
            used.add((symbol, member))
            invalid = client.structured_reason_codes if response_contract is not None else (
                [record["error_code"]] if record["error_code"] is not None else _response_validation(record["response_text"]))
            coverage.append({"member": member, "status": "DEFER" if invalid else "SHADOW_RECOMMENDATION", "reason_codes": invalid})
            native_parse = {"action": opinion.action, "confidence_label": _json_native(opinion.priority) if math.isfinite(opinion.priority) else str(opinion.priority), "reasoning": opinion.reasoning}
            # Invalid native defaults are retained as parser behavior, never
            # promoted to an invented HOLD vote or a confidence probability.
            if invalid:
                if not math.isfinite(opinion.priority):
                    native_parse["confidence_label"] = str(opinion.priority)
                opinions.append({"member": member, "status": "DEFER", "recommendation": None, "confidence_label": None,
                                 "confidence_is_probability": False, "reasoning": None, "supporting_data": _json_native(opinion.supporting_data),
                                 "native_parser_output": native_parse, "trade_plan_suppressed": opinion.trade_plan is None})
            else:
                opinions.append({"member": member, "status": "SHADOW_RECOMMENDATION", "recommendation": opinion.action,
                                 "confidence_label": _json_native(opinion.priority), "confidence_is_probability": False,
                                 "reasoning": opinion.reasoning, "supporting_data": _json_native(opinion.supporting_data),
                                 "native_parser_output": native_parse, "trade_plan_suppressed": opinion.trade_plan is None})
            if response_contract is not None:
                opinions[-1].update(structured_response=client.structured_response,
                                    native_response_projection=client.native_response_projection)
                if not invalid:
                    # The projection is an adapter for the reviewed native
                    # parser, never an authority boundary or repaired output.
                    opinions[-1]["reasoning"] = client.structured_response["reasoning"]
        if supplied is not None and any(key[0] == symbol and key not in used for key in supplied):
            raise ShadowBrigadeAnalysisError("retained transcript contains a response for a deferred member")
        aligned = []
        benchmark = _observations(market, "SPY", captured) if "SPY" in market["bars"] else []
        bench_by_stamp = {point[0]: point[1] for point in benchmark}
        if symbol != "SPY" and observed and all(point[0] in bench_by_stamp for point in observed[-10:]):
            aligned = [bench_by_stamp[point[0]] for point in observed[-10:]]
        decay = decay_native["Blackwell_Decay"]().analyze(symbol, numpy.asarray([point[1] for point in observed]),
                     bench_closes=numpy.asarray(aligned) if aligned else None)
        decay_reasons = list(market_reasons)
        if len(observed) < 11:
            decay_reasons.append("INSUFFICIENT_OBSERVED_DECAY_HISTORY")
        if observed and generated - observed[-1][0] > timedelta(days=5):
            decay_reasons.append("OBSERVED_HISTORY_STALE")
        symbols.append({"symbol": symbol, "forecast_row_ids": [row["row_id"] for row in grouped[symbol]],
                        "selected_forecast_row_ids": [row["row_id"] for row in forecasts],
                        "forecast_gate": "CURRENT_SHADOW_ELIGIBLE" if forecasts else "DEFER",
                        "observed_bar_count": len(observed), "last_observation_at": observed[-1][0].isoformat().replace("+00:00", "Z") if observed else None,
                        "context": _json_native(context), "forecast_path_semantics": "FUTURE_PREDICTED_CLOSE_LEVELS",
                        "member_coverage": coverage, "opinions": opinions,
                        "dissent": [{"member": opinion["member"], "recommendation": opinion["recommendation"]} for opinion in opinions if opinion["recommendation"] is not None]
                            if len({opinion["recommendation"] for opinion in opinions if opinion["recommendation"] is not None}) > 1 else [],
                        "decay": {"status": "DEFER" if decay_reasons else "CONNECTED_SHADOW_ONLY", "reason_codes": sorted(set(decay_reasons)),
                                  "observed_calculation": _json_native(decay), "recommendation": None if decay_reasons else decay["vote"],
                                  "confidence_is_probability": False, "benchmark_symbol": "SPY" if aligned else None,
                                  "benchmark_timestamp_alignment_verified": bool(aligned)}})
    if supplied is not None and set(supplied) - used:
        raise ShadowBrigadeAnalysisError("retained transcript contains unknown or unused member responses")
    requested = transcripts is not None or text_generator is not None
    packet = {"schema_version": SCHEMA_VERSION if response_contract is None else SCHEMA_VERSION_V2,
            "generated_at": generated_at, "mode": "SHADOW", "domain": result["domain"],
            "context_policy_version": CONTEXT_POLICY_VERSION,
            "requested_symbols": selected_symbols,
            "forecast_intake_evidence": _reference("brigade/forecast-intake.json", canonical_json_bytes(intake_doc)),
            "forecast_result": result, "market_source": _reference("brigade/market-packet.json", market_raw),
            "source_evidence": {"brigade": _reference("brigade/blackwell_brigade.py", brigade_source), "decay": _reference("brigade/decay.py", decay_source)},
            "runtime_fingerprint": {"python": f"{sys.version_info.major}.{sys.version_info.minor}", "pandas": pandas.__version__, "numpy": numpy.__version__},
            "response_capture_status": "RETAINED_RESPONSES" if requested else "INFERENCE_DISABLED",
            "response_transcripts": records, "symbols": symbols,
            "limitations": list(LIMITATIONS), "authority": dict(_AUTHORITY), "auto_trading_enabled": False}
    if response_contract is not None:
        packet["response_contract"] = response_contract
    return packet


def evidence_for_shadow_brigade_analysis(intake, market_raw, brigade_source, decay_source, blobs):
    """Retain original input/code closure; records remain in the packet itself."""
    from .forecast_intake import evidence_for_forecast_intake
    intake = _intake(intake)
    input_raw = _intake(intake).to_bytes()
    result = evidence_for_forecast_intake(intake, blobs)
    market = validate_market_packet(parse_strict_json_object_bytes(market_raw), blobs)
    def keep(path, raw):
        if path in result and result[path] != raw:
            raise ShadowBrigadeAnalysisError("Brigade evidence path binds conflicting bytes")
        result[path] = raw
    for reference in market["source_evidence"]:
        keep(reference["path"], _retained(blobs, reference))
    for path, raw in (("brigade/forecast-intake.json", input_raw), ("brigade/market-packet.json", market_raw),
                      ("brigade/blackwell_brigade.py", brigade_source), ("brigade/decay.py", decay_source)):
        keep(path, raw)
    _source(brigade_source, BRIGADE_SOURCE_SHA256, "Brigade")
    _source(decay_source, DECAY_SOURCE_SHA256, "Decay")
    return result


def validate_shadow_brigade_analysis(packet, blobs):
    """Recompute every opinion and request without calling an external model."""
    if not isinstance(packet, dict) or type(packet.get("schema_version")) is not str or packet.get("schema_version") not in {SCHEMA_VERSION, SCHEMA_VERSION_V2}:
        raise ShadowBrigadeAnalysisError("unsupported Brigade shadow packet")
    try:
        intake = parse_strict_json_object_bytes(_retained(blobs, packet["forecast_intake_evidence"]))
        market_raw = _retained(blobs, packet["market_source"])
        brigade_source = _retained(blobs, packet["source_evidence"]["brigade"])
        decay_source = _retained(blobs, packet["source_evidence"]["decay"])
        if packet["response_capture_status"] not in {"RETAINED_RESPONSES", "INFERENCE_DISABLED"}:
            raise ShadowBrigadeAnalysisError("unsupported response capture status")
        transcripts = packet["response_transcripts"] if packet["response_capture_status"] == "RETAINED_RESPONSES" else None
        expected = build_shadow_brigade_analysis(intake, market_raw, brigade_source, decay_source, generated_at=packet["generated_at"],
                                                blobs=blobs, transcripts=transcripts, symbols=packet["requested_symbols"],
                                                response_contract=packet["response_contract"] if packet["schema_version"] == SCHEMA_VERSION_V2 else None)
    except (KeyError, TypeError, ValueError) as exc:
        if isinstance(exc, ShadowBrigadeAnalysisError):
            raise
        raise ShadowBrigadeAnalysisError("invalid Brigade retained input or packet shape") from exc
    if packet != expected:
        raise ShadowBrigadeAnalysisError("Brigade packet differs from deterministic retained-evidence replay")
    return packet
