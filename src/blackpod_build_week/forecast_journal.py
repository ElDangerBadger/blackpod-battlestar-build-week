"""Pure journal projections for forecast evidence and Brigade recommendations."""
from .contracts.decision_journal import JournalEvent
from .contracts.forecast_intake import ForecastIntake
from .contracts.mission_request import parse_strict_json_object_bytes
from .hashing import canonical_json_bytes, sha256_bytes


def identity(prefix, value):
    return prefix + "-" + sha256_bytes(canonical_json_bytes(value))


def build_forecast_intake_event(intake, events=(), blobs=None):
    from .forecast_intake import assess_forecast_intake, evidence_for_forecast_intake
    if not isinstance(intake, ForecastIntake):
        intake = ForecastIntake.from_mapping(intake)
    evidence = evidence_for_forecast_intake(intake, blobs or {})
    decision_id = identity("journal-decision", {"kind": "FORECAST_INTAKE", "intake_id": intake.intake_id, "domain": intake.domain})
    return JournalEvent.from_mapping({"schema_version": "blackpod.decision_journal_event.v9",
        "event_id": identity("journal-event", {"decision_id": decision_id, "event_type": "FORECAST_INTAKE_RECORDED"}),
        "decision_id": decision_id, "domain": intake.domain, "event_type": "FORECAST_INTAKE_RECORDED", "recorded_at": intake.recorded_at,
        "source": {"kind": "FORECAST_INTAKE", "intake_id": intake.intake_id, "source_sha256": sha256_bytes(intake.to_bytes())},
        "evidence": [{"path": path, "sha256": sha256_bytes(raw), "size_bytes": len(raw)} for path, raw in sorted(evidence.items())],
        "payload": {"intake": intake.to_dict(), "result": assess_forecast_intake(intake, blobs or {})}})


def validate_forecast_intake_event(event, previous_events, blobs):
    expected = build_forecast_intake_event(event.payload["intake"], previous_events, blobs)
    if event.to_bytes() != expected.to_bytes():
        raise ValueError("forecast intake differs from retained source projection")


def _blob(blobs, reference):
    raw = blobs.get(reference["sha256"])
    if not isinstance(raw, bytes) or sha256_bytes(raw) != reference["sha256"] or len(raw) != reference["size_bytes"]:
        raise ValueError("Brigade source evidence differs in hash or size")
    return raw


def brigade_context(request, events, blobs):
    from .contracts.brigade_shadow import BrigadeShadowRequest
    from .contracts.mission_request import parse_rfc3339
    if not isinstance(request, BrigadeShadowRequest):
        request = BrigadeShadowRequest.from_mapping(request)
    source = next((event for event in events if event.event_id == request.forecast["intake_event_id"]
        and event.event_type == "FORECAST_INTAKE_RECORDED"), None)
    if source is None:
        raise ValueError("Brigade shadow analysis requires a preceding verified forecast intake")
    if source.domain != request.domain or source.source["intake_id"] != request.forecast["intake_id"]:
        raise ValueError("Brigade request belongs to a different forecast domain or identity")
    raw_intake = _blob(blobs, request.forecast["intake_evidence"])
    intake = ForecastIntake.from_bytes(raw_intake)
    if (intake.to_dict() != source.payload["intake"] or sha256_bytes(intake.to_bytes()) != request.forecast["intake_source_sha256"]
            or source.source["source_sha256"] != request.forecast["intake_source_sha256"]):
        raise ValueError("Brigade intake differs from its verified original event")
    if parse_rfc3339(source.recorded_at, "source recorded_at") > parse_rfc3339(request.generated_at, "generated_at"):
        raise ValueError("forecast intake was recorded after Brigade generation")
    transcript = None
    if request.transcript_evidence is not None:
        from .brigade_shadow_transport import validate_transcript_bundle
        transcript = parse_strict_json_object_bytes(_blob(blobs, request.transcript_evidence))
        validate_transcript_bundle(transcript, request)
    return request, source, intake, transcript


def _analysis(request, intake, transcript, blobs):
    from .shadow_brigade_analysis import build_shadow_brigade_analysis
    result = build_shadow_brigade_analysis(intake, _blob(blobs, request.market_evidence),
        _blob(blobs, request.source_evidence["brigade"]), _blob(blobs, request.source_evidence["decay"]),
        generated_at=request.generated_at, blobs=blobs,
        transcripts=None if transcript is None else transcript["transcripts"], symbols=request.symbols,
        response_contract=request.to_dict().get("response_contract"))
    if transcript is not None:
        from .brigade_shadow_transport import validate_response_timeliness
        market = parse_strict_json_object_bytes(_blob(blobs, request.market_evidence))
        validate_response_timeliness(transcript, result, market["captured_at"])
    return result


def assess_brigade_shadow(request, events=(), blobs=None):
    request, source, intake, transcript = brigade_context(request, events, blobs or {})
    return _analysis(request, intake, transcript, blobs or {})


def evidence_for_brigade_shadow(request, events=(), blobs=None):
    from .forecast_intake import evidence_for_forecast_intake
    request, source, intake, transcript = brigade_context(request, events, blobs or {})
    analysis = _analysis(request, intake, transcript, blobs or {})
    evidence = evidence_for_forecast_intake(intake, blobs or {})
    refs = [request.forecast["intake_evidence"], request.market_evidence, *request.source_evidence.values()]
    if request.transcript_evidence is not None:
        refs.append(request.transcript_evidence)
    for reference in (*refs, *analysis["source_evidence"].values(), analysis["market_source"], analysis["forecast_intake_evidence"]):
        raw = _blob(blobs, reference)
        if reference["path"] in evidence and evidence[reference["path"]] != raw:
            raise ValueError("Brigade evidence paths collide")
        evidence[reference["path"]] = raw
    # The raw market response closure is separate from source mission storage.
    market = parse_strict_json_object_bytes(_blob(blobs, request.market_evidence))
    for reference in market["source_evidence"]:
        raw = _blob(blobs, reference)
        if reference["path"] in evidence and evidence[reference["path"]] != raw:
            raise ValueError("Brigade market evidence paths collide")
        evidence[reference["path"]] = raw
    reserved = "brigade-shadow/request.v2.json" if request.to_dict().get("response_contract") is not None else "brigade-shadow/request.v1.json"
    if reserved in evidence:
        raise ValueError("Brigade evidence collides with its reserved input path")
    evidence[reserved] = request.to_bytes()
    return evidence


def build_brigade_shadow_event(request, events=(), blobs=None):
    # An exact retry must bind the original predecessor, not later observations.
    analysis_id = request.analysis_id if hasattr(request, "analysis_id") else request["analysis_id"]
    prefix = tuple(events)
    for index, event in enumerate(prefix):
        if event.source["kind"] == "BRIGADE_SHADOW_ANALYSIS" and event.source["analysis_id"] == analysis_id:
            prefix = prefix[:index]
            break
    request, source, intake, transcript = brigade_context(request, prefix, blobs or {})
    evidence = evidence_for_brigade_shadow(request, prefix, blobs or {})
    return JournalEvent.from_mapping({"schema_version": "blackpod.decision_journal_event.v11" if request.to_dict().get("response_contract") is not None else "blackpod.decision_journal_event.v9",
        "event_id": identity("journal-event", {"decision_id": source.decision_id, "event_type": "BRIGADE_SHADOW_ANALYSIS_RECORDED", "analysis_id": request.analysis_id}),
        "decision_id": source.decision_id, "domain": source.domain, "event_type": "BRIGADE_SHADOW_ANALYSIS_RECORDED", "recorded_at": request.recorded_at,
        "source": {"kind": "BRIGADE_SHADOW_ANALYSIS", "analysis_id": request.analysis_id, "source_sha256": sha256_bytes(request.to_bytes())},
        "evidence": [{"path": path, "sha256": sha256_bytes(raw), "size_bytes": len(raw)} for path, raw in sorted(evidence.items())],
        "payload": {"request": request.to_dict(), "analysis": _analysis(request, intake, transcript, blobs or {})}})


def validate_brigade_shadow_event(event, previous_events, blobs):
    expected = build_brigade_shadow_event(event.payload["request"], previous_events, blobs)
    if event.to_bytes() != expected.to_bytes():
        raise ValueError("Brigade recommendations differ from retained evidence replay")
