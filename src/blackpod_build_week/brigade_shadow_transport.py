"""Explicit one-shot local ModelDock capture; verification never invokes inference.

Transport LIVE means a real local text request. The desk remains SHADOW and
every execution, allocation and policy authority stays disabled. A durable
attempt reservation prevents automatic repeats after uncertain delivery.
"""
from datetime import datetime, timezone, timedelta
import json
import math
from pathlib import Path
import time

from .contracts.brigade_shadow import BrigadeShadowRequest
from .contracts.investment_review import disabled_authority
from .contracts.mission_request import parse_rfc3339, parse_strict_json_object_bytes
from .desk_candidate_review_cli import _write
from .forecast_journal import _blob, brigade_context, assess_brigade_shadow, evidence_for_brigade_shadow
from .hashing import canonical_json_bytes, sha256_bytes
from .sentry_history_cache import read_regular

BUNDLE_SCHEMA = "blackpod.brigade_shadow_transcripts.v1"
ATTEMPT_SCHEMA = "blackpod.brigade_shadow_generation_attempt.v1"
BUNDLE_V2_SCHEMA = "blackpod.brigade_shadow_transcripts.v2"
ATTEMPT_V2_SCHEMA = "blackpod.brigade_shadow_generation_attempt.v2"
MAX_ATTEMPT_CALLS = 40
MAX_ATTEMPT_SECONDS = 300
_FORMAT_INSTRUCTION = (
    "This is a SHADOW evidence review. Forecast quantiles are predicted USD close levels, not returns or calibrated probabilities. "
    "A path across future target horizons is not observed price history or a verified chart pattern. "
    "Pathfinder's native ten-period wording refers here to the supplied three-to-five future targets; it is not ten elapsed observations. "
    "All actions are advisory recommendations; no trade, allocation or policy change is authorized. "
    "Return exactly one JSON object with the single field brigade_text containing the requested native response text."
)
_STRUCTURED_FORMAT_INSTRUCTION = (
    "This is a SHADOW evidence review. Forecast quantiles are predicted USD close levels, not returns or calibrated probabilities. "
    "A path across future target horizons is not observed price history or a verified chart pattern. "
    "Pathfinder's native ten-period wording refers here to the supplied three-to-five future targets; it is not ten elapsed observations. "
    "All actions are advisory recommendations; no trade, allocation or policy change is authorized. "
    "The supplied JSON schema replaces ONLY the native text-label output format. Return exactly the JSON object required by that schema, "
    "with the exact schema_version, member and symbol constants. Choose action from BUY, EXIT, HOLD, WATCH. "
    "heuristic_confidence is a numeric heuristic label from 0 to 1, never a calibrated probability. "
    "reasoning must be a nonblank single line, without surrounding whitespace, line breaks or control characters. "
    "Preserve the native analytical instructions and criteria. Do not copy their illustrative rules as your answer. "
    "Do not include brigade_text, labels outside JSON, markdown, orders, quantities, capital allocations or authorization fields."
)


def _response_contract(request):
    return request.to_dict().get("response_contract")


def _bundle_schema(request):
    return BUNDLE_V2_SCHEMA if _response_contract(request) is not None else BUNDLE_SCHEMA


def _attempt_schema(request):
    return ATTEMPT_V2_SCHEMA if _response_contract(request) is not None else ATTEMPT_SCHEMA


def _bindings(request):
    result = {"analysis_id": request.analysis_id, "generated_at": request.generated_at,
        "intake_source_sha256": request.forecast["intake_source_sha256"], "market_sha256": request.market_evidence["sha256"],
        "brigade_sha256": request.source_evidence["brigade"]["sha256"], "decay_sha256": request.source_evidence["decay"]["sha256"], "symbols": request.symbols}
    if _response_contract(request) is not None:
        result["response_contract"] = _response_contract(request)
    return result


def make_transcript_bundle(request, transcripts, *, capture_kind="DECLARED_REPLAY", transport_records=None):
    if not isinstance(request, BrigadeShadowRequest):
        request = BrigadeShadowRequest.from_mapping(request)
    bundle = {"schema_version": _bundle_schema(request), **_bindings(request), "capture_kind": capture_kind,
        "transcripts": transcripts, "transport_records": transport_records or [], "authority": request.authority}
    return validate_transcript_bundle(bundle, request)


def _brigade_text(value):
    if not isinstance(value, dict) or set(value) != {"brigade_text"} or not isinstance(value["brigade_text"], str):
        raise ValueError("ModelDock must return the single brigade_text field")
    if not value["brigade_text"].strip() or len(value["brigade_text"].encode("utf-8")) > 32 * 1024:
        raise ValueError("ModelDock Brigade text is empty or oversized")
    return value["brigade_text"]


def _structured_text(value):
    # Transport validation retains bounded strict JSON evidence, even if its
    # member semantics fail later. Only the independently replayed contract
    # parser can promote it to a SHADOW recommendation.
    if not isinstance(value, dict):
        raise ValueError("structured Brigade evidence must be a JSON object")
    raw = canonical_json_bytes(value)
    if len(raw) > 32 * 1024:
        raise ValueError("structured Brigade evidence is oversized")
    return raw.decode("utf-8")


def _wire_request(native, config, analysis_id, *, response_contract=None):
    identity = {"analysis_id": analysis_id, "native": native}
    schema = {"type": "object", "additionalProperties": False,
        "properties": {"brigade_text": {"type": "string"}}, "required": ["brigade_text"]}
    instruction = _FORMAT_INSTRUCTION
    if response_contract is not None:
        from .contracts.brigade_response import SCHEMA_VERSION, response_json_schema
        if response_contract != SCHEMA_VERSION:
            raise ValueError("unsupported Brigade response contract")
        identity["response_contract"] = response_contract
        schema = response_json_schema(native["member"], native["symbol"])
        instruction = _STRUCTURED_FORMAT_INSTRUCTION
    request_id = "brigade-" + sha256_bytes(canonical_json_bytes(identity))
    return {"profile": config.profile, "capabilities": ["text"],
        "response_format": {"type": "json_schema", "schema": schema},
        "timeout": max(1, math.ceil(config.timeout_seconds)), "max_tokens": native["max_tokens"],
        "messages": [{"role": "system", "content": instruction + "\n\n" + native["system"]},
                     {"role": "user", "content": native["prompt"]}],
        "metadata": {"blackpod_correlation": {"mission_id": analysis_id, "request_id": request_id,
            "symbol": native["symbol"], "run_mode": "LIVE"}}}


def _validate_transport_record(record, transcript, request):
    from .contracts.decision_journal import _hash, _object
    from .modeldock_config import ModelDockConfig
    from .modeldock_client import ModelDockClient
    fields = {"native_request_sha256", "configuration", "request_payload", "request_sha256", "status", "safe_response",
        "raw_response_sha256", "response_byte_size", "provider", "model", "model_revision", "trace_id", "mocked", "started_at", "observed_at", "failure"}
    record = _object(record, fields, "ModelDock shadow capture")
    if record["native_request_sha256"] != sha256_bytes(canonical_json_bytes(transcript["request"])):
        raise ValueError("ModelDock capture differs from its native request")
    configuration = _object(record["configuration"], {"base_url", "timeout_seconds", "profile", "provider", "delivery_grace_seconds"}, "ModelDock capture configuration")
    config = ModelDockConfig(**configuration)
    wire = _wire_request(transcript["request"], config, request.analysis_id, response_contract=_response_contract(request))
    if record["request_payload"] != wire or record["request_sha256"] != sha256_bytes(canonical_json_bytes(wire)):
        raise ValueError("ModelDock wire request does not reproduce its native prompt and shadow wrapper")
    correlation = wire["metadata"]["blackpod_correlation"]
    # Validate the recorded request locally. No transport is created or called.
    class NeverTransport:
        def request(self, **kwargs):
            raise AssertionError("provider-free provenance validation cannot call ModelDock")
    ModelDockClient(config, transport=NeverTransport())._validate_request(wire,
        mission_id=request.analysis_id, request_id=correlation["request_id"], symbol=transcript["request"]["symbol"], run_mode="LIVE")
    started = parse_rfc3339(record["started_at"], "capture started_at")
    observed = parse_rfc3339(record["observed_at"], "capture observed_at")
    if not parse_rfc3339(request.generated_at, "generated_at") <= started <= observed <= parse_rfc3339(request.recorded_at, "recorded_at"):
        raise ValueError("ModelDock capture timestamps differ from its recorded processing window")
    if record["status"] == "FAILED":
        if transcript["response_text"] is not None or transcript["error_code"] != "SHADOW_GENERATION_FAILED" or not isinstance(record["failure"], dict):
            raise ValueError("failed ModelDock capture cannot contribute a recommendation")
        if any(record[field] is not None for field in ("safe_response", "raw_response_sha256", "response_byte_size", "provider", "model", "model_revision", "trace_id", "mocked")):
            raise ValueError("failed ModelDock capture must not retain an accepted response")
        failure_fields = {"code", "error_type", "message", "resumable", "latency_ms", "started_at", "observed_at", "raw_response_sha256", "response_byte_size", "safe_response", "delivery"}
        if set(record["failure"]) != failure_fields or type(record["failure"]["resumable"]) is not bool:
            raise ValueError("failed ModelDock capture has unsupported diagnostics")
        return record
    expired = record["status"] == "VALIDATED_EXPIRED"
    rejected = record["status"] == "VALIDATED_REJECTED" and _response_contract(request) is not None
    supported_statuses = {"VALIDATED", "VALIDATED_EXPIRED", *({"VALIDATED_REJECTED"} if _response_contract(request) is not None else set())}
    expected_error = "RESPONSE_EXPIRED_AFTER_GENERATION" if expired else "UNSUPPORTED_OR_OVERSIZED_RESPONSE" if rejected else None
    if record["status"] not in supported_statuses or record["failure"] is not None or transcript["error_code"] != expected_error or ((expired or rejected) and transcript["response_text"] is not None):
        raise ValueError("unsupported ModelDock capture disposition")
    _hash(record["raw_response_sha256"], "raw_response_sha256")
    if type(record["response_byte_size"]) is not int or not 0 < record["response_byte_size"] <= config.max_response_bytes:
        raise ValueError("ModelDock response size exceeds its capture limit")
    envelope = _object(record["safe_response"], {"status", "request_type", "profile", "provider", "model", "data", "metadata", "trace_id", "mocked", "content"}, "projected ModelDock response")
    if envelope["status"] != "ok" or envelope["request_type"] != "text.generate" or envelope["profile"] != config.profile or envelope["provider"] != "mlx" or envelope["mocked"] is not False:
        raise ValueError("ModelDock capture lacks validated local MLX provenance")
    if not isinstance(envelope["data"], dict) or set(envelope["data"]) - {"engine", "profile", "model_revision"} or envelope["data"].get("engine") not in {"mlx-lm", "mlx-vlm"} or envelope["data"].get("profile") != config.profile:
        raise ValueError("ModelDock capture has unsupported projected engine data")
    from .modeldock_client import _safe_token, _model_revision
    try:
        _safe_token(envelope["model"], "model")
        _safe_token(envelope["trace_id"], "trace_id")
        revision = _model_revision(envelope)
    except Exception:
        raise ValueError("ModelDock capture has unsafe model or trace provenance") from None
    meta = envelope["metadata"]
    expected_meta = {"blackpod_correlation", "structured_output", "requested_max_tokens", "effective_max_tokens", "generated_token_count", "generated_token_count_source", "stop_reason", "stop_reason_source"}
    if not isinstance(meta, dict) or set(meta) != expected_meta or meta["blackpod_correlation"] != correlation or meta["structured_output"] != {"mode": "json_schema", "validated": True}:
        raise ValueError("ModelDock capture correlation or structured output is unverified")
    if meta["requested_max_tokens"] != wire["max_tokens"] or meta["effective_max_tokens"] != wire["max_tokens"] or type(meta["generated_token_count"]) is not int or not 0 <= meta["generated_token_count"] <= wire["max_tokens"] or meta["generated_token_count_source"] != "native" or meta["stop_reason"] != "stop" or meta["stop_reason_source"] != "native":
        raise ValueError("ModelDock capture token budget or completion metadata differs")
    if not isinstance(envelope["content"], str) or len(envelope["content"].encode("utf-8")) > config.max_response_bytes:
        raise ValueError("ModelDock retained content must be bounded JSON text")
    mapping = parse_strict_json_object_bytes(envelope["content"].encode("utf-8"))
    content = envelope["content"] if _response_contract(request) is not None else _brigade_text(mapping)
    if _response_contract(request) is not None:
        _structured_text(mapping)
        if not expired and rejected != (len(content.encode("utf-8")) > 32 * 1024):
            raise ValueError("ModelDock retained content rejection differs from its original byte bound")
    if not expired and not rejected and content != transcript["response_text"]:
        raise ValueError("ModelDock retained content differs from the native response transcript")
    for field in ("provider", "model", "trace_id", "mocked"):
        if record[field] != envelope[field]:
            raise ValueError("ModelDock projected response provenance differs")
    if record["model_revision"] != revision:
        raise ValueError("ModelDock revision differs from its projected response")
    return record


def validate_transcript_bundle(bundle, request):
    from .contracts.decision_journal import _object
    from .shadow_brigade_analysis import _supplied_transcripts
    fields = {"schema_version", *(_bindings(request)), "capture_kind", "transcripts", "transport_records", "authority"}
    bundle = _object(bundle, fields, "Brigade transcript bundle")
    if bundle["schema_version"] != _bundle_schema(request) or any(bundle[key] != expected for key, expected in _bindings(request).items()):
        raise ValueError("Brigade transcript source bindings differ from its request")
    bundle["authority"] = disabled_authority(bundle["authority"])
    parsed = _supplied_transcripts(bundle["transcripts"], response_contract=_response_contract(request))
    if parsed is None:
        raise ValueError("retained transcript bundle must have an explicit list")
    if not isinstance(bundle["transport_records"], list) or len(bundle["transport_records"]) > MAX_ATTEMPT_CALLS:
        raise ValueError("ModelDock capture count exceeds the bounded attempt")
    if bundle["capture_kind"] == "DECLARED_REPLAY":
        if bundle["transport_records"]:
            raise ValueError("declared replay cannot claim an authenticated provider capture")
        return bundle
    if bundle["capture_kind"] != "MODELDOCK_CAPTURE":
        raise ValueError("unsupported Brigade capture kind")
    by_hash = {sha256_bytes(canonical_json_bytes(row["request"])): row for row in parsed.values()}
    used = set()
    for record in bundle["transport_records"]:
        digest = record.get("native_request_sha256") if isinstance(record, dict) else None
        if digest not in by_hash or digest in used:
            raise ValueError("ModelDock capture has unknown or duplicate request identity")
        used.add(digest)
        _validate_transport_record(record, by_hash[digest], request)
    for digest, row in by_hash.items():
        if digest not in used and (row["response_text"] is not None or row["error_code"] != "RETAINED_RESPONSE_MISSING"):
            raise ValueError("ModelDock response lacks its captured provenance")
    return bundle


def response_expired(native, forecast_result, market_captured_at, observed_at):
    observed = parse_rfc3339(observed_at, "response observed_at")
    market = parse_rfc3339(market_captured_at, "market captured_at")
    if not timedelta(0) <= observed - market <= timedelta(hours=24):
        return True
    known = {row["row_id"]: row for row in forecast_result["rows"]}
    rows = [known[key] for key in native["forecast_row_ids"]]
    return any(observed >= parse_rfc3339(row["target_at"], "target_at") or any(not timedelta(0) <= observed - parse_rfc3339(row[field], field) <= timedelta(hours=24)
        for field in ("issued_at", "feature_cutoff", "training_cutoff")) for row in rows)


def validate_response_timeliness(bundle, analysis, market_captured_at):
    if bundle["capture_kind"] != "MODELDOCK_CAPTURE":
        return
    transcripts = {sha256_bytes(canonical_json_bytes(row["request"])): row for row in bundle["transcripts"]}
    for record in bundle["transport_records"]:
        if record["status"] in {"VALIDATED", "VALIDATED_EXPIRED"}:
            transcript = transcripts[record["native_request_sha256"]]
            expired = response_expired(transcript["request"], analysis["forecast_result"], market_captured_at, record["observed_at"])
            if (record["status"] == "VALIDATED_EXPIRED") != expired:
                raise ValueError("ModelDock response expiry differs from its retained forecast and processing times")


def _configuration(config):
    return {key: getattr(config, key) for key in ("base_url", "timeout_seconds", "profile", "provider", "delivery_grace_seconds")}


def _finish_capture(request, events, blobs, directory, transcripts, transports, now, *, inference_calls=0):
    intent = parse_strict_json_object_bytes(read_regular(directory / "generation-intent.json"))
    saved_transcripts, saved_transports = _saved_receipts(directory, intent["planned_requests"], intent["configuration"])
    if transcripts != saved_transcripts or transports != saved_transports:
        raise ValueError("capture differs from its original durable receipts")
    # Closing time is separate from the frozen analysis clock.
    clock_path = directory / "completion-clock.json"
    if clock_path.exists():
        clock = parse_strict_json_object_bytes(read_regular(clock_path))
        if set(clock) != {"completed_at", "request_sha256"} or clock["request_sha256"] != sha256_bytes(request.to_bytes()):
            raise ValueError("captured completion clock belongs to different input")
        closing = clock["completed_at"]
    else:
        closing = now().astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
        _write(clock_path, canonical_json_bytes({"completed_at": closing, "request_sha256": sha256_bytes(request.to_bytes())}), ())
    if not parse_rfc3339(request.generated_at, "generated_at") <= parse_rfc3339(closing, "completed_at") <= now().astimezone(timezone.utc):
        raise ValueError("completion clock is outside its actual processing window")
    value = request.to_dict()
    value["recorded_at"] = closing
    pending = BrigadeShadowRequest.from_mapping(value)
    bundle = make_transcript_bundle(pending, transcripts, capture_kind="MODELDOCK_CAPTURE", transport_records=transports)
    raw = canonical_json_bytes(bundle)
    relative = "brigade-shadow/transcript-bundle.json"
    _write(directory / "evidence" / relative, raw, ())
    value.update(inference_mode="RETAINED_TRANSCRIPT", transcript_evidence={"path": relative, "sha256": sha256_bytes(raw), "size_bytes": len(raw)})
    sealed = BrigadeShadowRequest.from_mapping(value)
    updated_blobs = dict(blobs); updated_blobs[sha256_bytes(raw)] = raw
    analysis = assess_brigade_shadow(sealed, events, updated_blobs)
    _write(directory / "request.replay.json", sealed.to_bytes(), ())
    _write(directory / "analysis.json", canonical_json_bytes(analysis), ())
    return {"request": str(directory / "request.replay.json"), "evidence_root": str(directory / "evidence"),
        "analysis": str(directory / "analysis.json"), "inference_calls": inference_calls, **_capture_counts(directory, transports), "automatic_retry_allowed": False,
        "orders_submitted": 0, "auto_trading_changed": False}


def _capture_counts(directory, transports):
    intents = sum(path.name.startswith("call-intent-") for path in directory.iterdir())
    return {"durable_call_intent_count": intents, "retained_receipt_count": len(transports), "unconfirmed_call_count": intents - len(transports)}


def _saved_receipts(directory, planned, configuration):
    import re
    receipts, transports, intents, completed = [], [], {}, set()
    for path in directory.iterdir():
        if path.name.startswith(("receipt-", "call-intent-")):
            match = re.fullmatch(r"(receipt|call-intent)-([0-9]{4})\.json", path.name)
            if match is None or not 1 <= int(match[2]) <= len(planned):
                raise ValueError("generation capsule has unknown call or receipt files")
            index = int(match[2])
            saved = parse_strict_json_object_bytes(read_regular(path))
            native = planned[index - 1]
            if match[1] == "call-intent":
                if set(saved) != {"native_request", "wire_request"} or saved["native_request"] != native:
                    raise ValueError("saved call intent differs from the original native request")
                intents[index] = saved
            else:
                if set(saved) != {"transcript", "transport"} or saved["transcript"]["request"] != native:
                    raise ValueError("saved receipt differs from its planned native request")
                completed.add(index)
                receipts.append((index, saved["transcript"], saved["transport"]))
    if sorted(intents) != list(range(1, len(intents) + 1)) or not completed <= set(intents):
        raise ValueError("saved call intents have a gap or receipts without intents")
    # A sequential attempt can have one uncertain final call and no later call.
    if sorted(completed) != list(range(1, len(completed) + 1)) or len(intents) - len(completed) > 1:
        raise ValueError("saved receipt sequence has missing committed calls")
    for index, transcript, transport in sorted(receipts):
        if intents[index]["wire_request"] != transport["request_payload"] or transport["configuration"] != configuration:
            raise ValueError("saved wire request differs from its original call intent")
        transports.append(transport)
    return [row[1] for row in sorted(receipts)], transports


def capture_modeldock(request, events, blobs, output_directory, *, config=None, client_factory=None,
        now=lambda: datetime.now(timezone.utc), monotonic=time.monotonic, recover=False):
    from .auto_trading_runtime import RuntimeLedger
    from .modeldock_config import load_modeldock_config
    from .modeldock_client import ModelDockClient, ModelDockClientError
    request, source, intake, transcript = brigade_context(request, events, blobs)
    if request.inference_mode != "DISABLED":
        raise ValueError("a new generation attempt requires a disabled request, not an existing transcript")
    directory = Path(output_directory).absolute()
    early_intent = directory / "generation-intent.json"
    if early_intent.exists() and parse_strict_json_object_bytes(read_regular(early_intent)).get("request_sha256") != sha256_bytes(request.to_bytes()):
        raise ValueError("generation attempt identity is already bound to different evidence")
    # Path validation occurs before the lock or any source copy.
    from .desk_candidate_review_cli import _write as guarded_write
    evidence = evidence_for_brigade_shadow(request, events, blobs)
    for path, raw in evidence.items():
        if path != ("brigade-shadow/request.v2.json" if _response_contract(request) is not None else "brigade-shadow/request.v1.json"):
            guarded_write(directory / "evidence" / path, raw, ())
    dry = assess_brigade_shadow(request, events, blobs)
    planned = [row["request"] for row in dry["response_transcripts"]]
    if not planned:
        guarded_write(directory / "analysis.deferred.json", canonical_json_bytes(dry), ())
        return {"status": "DEFER_NO_CURRENT_ELIGIBLE_MEMBERS", "analysis": str(directory / "analysis.deferred.json"),
            "inference_calls": 0, "orders_submitted": 0, "auto_trading_changed": False, "automatic_retry_allowed": False}
    if len(planned) > MAX_ATTEMPT_CALLS:
        raise ValueError("bounded ModelDock attempt supports at most forty native member calls")
    with RuntimeLedger(directory).lock(name=".brigade-generation.lock"):
        intent_path = directory / "generation-intent.json"
        if intent_path.exists():
            intent = parse_strict_json_object_bytes(read_regular(intent_path))
            if set(intent) != {"schema_version", "request_sha256", "planned_requests", "configuration", "automatic_retry_allowed", "authority"} or intent["schema_version"] != _attempt_schema(request) or intent["automatic_retry_allowed"] is not False:
                raise ValueError("generation reservation has unsupported metadata")
            disabled_authority(intent["authority"])
            if intent.get("request_sha256") != sha256_bytes(request.to_bytes()) or intent.get("planned_requests") != planned:
                raise ValueError("generation attempt identity is already bound to different evidence")
            if (directory / "request.replay.json").exists():
                saved = BrigadeShadowRequest.from_bytes(read_regular(directory / "request.replay.json"))
                if _bindings(saved) != _bindings(request) or saved.inference_mode != "RETAINED_TRANSCRIPT":
                    raise ValueError("saved replay request differs from its consumed attempt")
                raw = read_regular(directory / "evidence" / saved.transcript_evidence["path"])
                retained = dict(blobs); retained[sha256_bytes(raw)] = raw
                expected = assess_brigade_shadow(saved, events, retained)
                clock = parse_strict_json_object_bytes(read_regular(directory / "completion-clock.json"))
                if clock != {"completed_at": saved.recorded_at, "request_sha256": sha256_bytes(request.to_bytes())}:
                    raise ValueError("saved completion clock differs from its sealed request")
                transcripts, transports = _saved_receipts(directory, planned, intent["configuration"])
                bundle = parse_strict_json_object_bytes(raw)
                if bundle["transcripts"] != transcripts or bundle["transport_records"] != transports:
                    raise ValueError("saved replay differs from its original captured receipts")
                if not (directory / "analysis.json").exists():
                    if not recover:
                        raise ValueError("capture publication was interrupted; use provider-free recovery")
                    _write(directory / "analysis.json", canonical_json_bytes(expected), ())
                elif read_regular(directory / "analysis.json") != canonical_json_bytes(expected):
                    raise ValueError("saved analysis differs from verified replay")
                return {"request": str(directory / "request.replay.json"), "evidence_root": str(directory / "evidence"),
                    "analysis": str(directory / "analysis.json"), "inference_calls": 0, "automatic_retry_allowed": False,
                    **_capture_counts(directory, transports),
                    "orders_submitted": 0, "auto_trading_changed": False, "reused_capture": True}
            if not recover:
                raise ValueError("generation attempt was consumed or interrupted; recover retained receipts without repeating inference")
            transcripts, transports = _saved_receipts(directory, planned, intent["configuration"])
            return _finish_capture(request, events, blobs, directory, transcripts, transports, now)
        if recover:
            raise ValueError("no consumed generation attempt exists to recover")
        elapsed = now().astimezone(timezone.utc) - parse_rfc3339(request.generated_at, "generated_at")
        if not timedelta(0) <= elapsed <= timedelta(minutes=5):
            raise ValueError("fresh generation requires an analysis clock within five minutes of the current clock")
        config = config or load_modeldock_config()
        if config.delivery_timeout_seconds > MAX_ATTEMPT_SECONDS:
            raise ValueError("configured per-call delivery budget exceeds the bounded 300-second shadow attempt")
        client = (client_factory or ModelDockClient)(config)
        guarded_write(intent_path, canonical_json_bytes({"schema_version": _attempt_schema(request),
            "request_sha256": sha256_bytes(request.to_bytes()), "planned_requests": planned, "configuration": _configuration(config),
            "automatic_retry_allowed": False, "authority": request.authority}), ())
        started_clock = monotonic()
        transcripts, transports = [], []
        for index, native in enumerate(planned, 1):
            if monotonic() - started_clock + config.delivery_timeout_seconds > MAX_ATTEMPT_SECONDS:
                break  # Never start a call that can exceed the attempt budget.
            # Do not consume expired target forecasts while earlier members ran.
            current = now().astimezone(timezone.utc)
            market = parse_strict_json_object_bytes(_blob(blobs, request.market_evidence))
            captured = parse_rfc3339(market["captured_at"], "market captured_at")
            if not timedelta(0) <= current - captured <= timedelta(hours=24):
                break
            relevant = [row for row in dry["forecast_result"]["rows"] if row["row_id"] in native["forecast_row_ids"]]
            if any(current >= parse_rfc3339(row["target_at"], "target_at") or any(not timedelta(0) <= current - parse_rfc3339(row[field], field) <= timedelta(hours=24) for field in ("issued_at", "feature_cutoff", "training_cutoff")) for row in relevant):
                break
            wire = _wire_request(native, config, request.analysis_id, response_contract=_response_contract(request))
            guarded_write(directory / f"call-intent-{index:04d}.json", canonical_json_bytes({"native_request": native, "wire_request": wire}), ())
            base = {"native_request_sha256": sha256_bytes(canonical_json_bytes(native)), "configuration": _configuration(config),
                "request_payload": wire, "request_sha256": sha256_bytes(canonical_json_bytes(wire))}
            before = now().astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
            correlation = wire["metadata"]["blackpod_correlation"]
            try:
                result = client.generate_text(wire, mission_id=request.analysis_id, request_id=correlation["request_id"],
                    symbol=native["symbol"], run_mode="LIVE", content_validator=_structured_text if _response_contract(request) is not None else _brigade_text, content_requires_correlation=False)
                expired = response_expired(native, dry["forecast_result"], market["captured_at"], result.observed_at)
                response_text = result.safe_response["content"] if _response_contract(request) is not None else result.parsed_content
                rejected = _response_contract(request) is not None and len(response_text.encode("utf-8")) > 32 * 1024
                record = {"request": native, "response_text": None if expired or rejected else response_text,
                    "error_code": "RESPONSE_EXPIRED_AFTER_GENERATION" if expired else "UNSUPPORTED_OR_OVERSIZED_RESPONSE" if rejected else None}
                transport = {**base, "status": "VALIDATED_EXPIRED" if expired else "VALIDATED_REJECTED" if rejected else "VALIDATED", "safe_response": dict(result.safe_response), "raw_response_sha256": result.raw_response_sha256,
                    "response_byte_size": result.response_byte_size, "provider": result.provider, "model": result.model,
                    "model_revision": result.model_revision, "trace_id": result.trace_id, "mocked": result.mocked,
                    "started_at": result.started_at, "observed_at": result.observed_at, "failure": None}
            except ModelDockClientError as error:
                failure = error.failure.to_dict()
                safe = failure.get("safe_response")
                if isinstance(safe, dict) and isinstance(safe.get("content"), str):
                    content = safe.pop("content").encode("utf-8")
                    safe.update(content_sha256=sha256_bytes(content), content_byte_size=len(content))
                record = {"request": native, "response_text": None, "error_code": "SHADOW_GENERATION_FAILED"}
                transport = {**base, "status": "FAILED", **{key: None for key in ("safe_response", "raw_response_sha256", "response_byte_size", "provider", "model", "model_revision", "trace_id", "mocked")},
                    "started_at": before, "observed_at": now().astimezone(timezone.utc).isoformat().replace("+00:00", "Z"), "failure": failure}
            guarded_write(directory / f"receipt-{index:04d}.json", canonical_json_bytes({"transcript": record, "transport": transport}), ())
            transcripts.append(record); transports.append(transport)
            if record["error_code"] is not None:
                break  # A failed or uncertain call has no fallback or retry.
        return _finish_capture(request, events, blobs, directory, transcripts, transports, now, inference_calls=len(transports))
