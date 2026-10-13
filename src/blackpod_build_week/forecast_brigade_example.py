"""Reproducible, wholly synthetic forecast intake and Brigade replay examples.

No test modules, credentials, providers, model inference, brokers, execution
controls, or sibling checkouts are used. Pinned native code fixtures supply the
actual five Brigade prompt builders/parsers and separate Decay calculation.
"""
from __future__ import annotations

import argparse
import json
import math
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys

from .contracts.brigade_shadow import BrigadeShadowRequest
from .contracts.forecast_intake import ForecastIntake
from .decision_journal_store import JournalStore, JournalStoreError, check_separate_root
from .forecast_intake import evidence_for_forecast_intake
from .forecast_journal import build_brigade_shadow_event, build_forecast_intake_event
from .hashing import canonical_json_bytes, sha256_bytes
from .sentry_history_cache import RecoveryError, read_regular
from .shadow_brigade_analysis import (
    BRIGADE_SOURCE_SHA256, DECAY_SOURCE_SHA256, MEMBERS, build_shadow_brigade_analysis,
)

SCHEMA_VERSION = "blackpod.synthetic_forecast_brigade_example.v1"
SYMBOL = "SYNTHETIC"
AS_OF = "2026-10-12T21:00:00Z"
GENERATED_AT = "2026-10-12T21:01:00Z"
FEATURE_CUTOFF = "2026-10-12T20:00:00Z"
ISSUED_AT = "2026-10-12T20:05:00Z"


def _authority():
    return {field: False for field in ("authorization_enabled", "capital_activation_enabled", "execution_enabled", "policy_changes_enabled")}


def _fixture_root():
    return Path(__file__).resolve().parents[2] / "fixtures"


def example_material(fixture_root=None):
    """Construct source-bound synthetic inputs, requests and expected events."""
    from .brigade_shadow_transport import make_transcript_bundle
    root = Path(fixture_root) if fixture_root is not None else _fixture_root()
    evidence, blobs = {}, {}
    def retain(path, value):
        raw = value if isinstance(value, bytes) else canonical_json_bytes(value)
        if path in evidence and evidence[path] != raw:
            raise ValueError("synthetic example evidence path conflicts")
        evidence[path], blobs[sha256_bytes(raw)] = raw, raw
        return {"path": path, "sha256": sha256_bytes(raw), "size_bytes": len(raw)}

    brigade = read_regular(root / "shadow_galactica_analysis/blackwell_brigade.py")
    decay = read_regular(root / "shadow_brigade_analysis/decay.py")
    if sha256_bytes(brigade) != BRIGADE_SOURCE_SHA256 or sha256_bytes(decay) != DECAY_SOURCE_SHA256:
        raise ValueError("synthetic example requires exact reviewed Brigade and Decay code fixtures")
    brigade_ref = retain("brigade/blackwell_brigade.py", brigade)
    decay_ref = retain("brigade/decay.py", decay)
    raw_forecast = ("Date,Symbol,Q10,Q50,Q90,Pattern,Timeframe,Horizon\n" + "".join(
        f"2026-10-12,{SYMBOL},{98 + horizon},{100 + horizon},{103 + horizon},LIVE,1D,{horizon}D\n"
        for horizon in (1, 2, 3))).encode()
    raw_ref = retain("forecast/synthetic-price-levels.csv", raw_forecast)
    calendar_ref = retain("forecast/declared-synthetic-session-calendar.json", {
        "schema_version": "blackpod.forecast_session_calendar.v1", "symbol": SYMBOL,
        "anchor_at": FEATURE_CUTOFF, "captured_at": FEATURE_CUTOFF,
        "sessions": [{"opens_at": f"2026-10-{day:02d}T13:30:00Z", "closes_at": f"2026-10-{day:02d}T20:00:00Z"} for day in (13, 14, 15)]})
    features_ref = retain("forecast/synthetic-feature-observations.json", {
        "schema_version": "blackpod.forecast_observation_evidence.v1", "kind": "FEATURES", "symbol": SYMBOL,
        "observations": [{"observed_at": FEATURE_CUTOFF, "values": {"close_lag": "100"}}]})
    training_ref = retain("forecast/synthetic-training-observations.json", {
        "schema_version": "blackpod.forecast_observation_evidence.v1", "kind": "TRAINING", "symbol": SYMBOL,
        "observations": [{"observed_at": "2026-10-09T20:00:00Z", "target_observed_at": FEATURE_CUTOFF,
            "values": {"close_lag": "99", "target_close": "100"}}]})
    config_ref = retain("forecast/synthetic-model-config.json", {
        "schema_version": "blackpod.forecast_model_config.v1", "model_kind": "EXTERNAL_QUANTILE",
        "quantile_levels": ["0.10", "0.50", "0.90"], "target": "FUTURE_CLOSE", "currency": "USD", "feature_names": ["close_lag"]})
    model_ref = retain("forecast/synthetic-model-artifact.bin", b"SYNTHETIC FIXTURE model bytes, not executable or fitted.\n")
    producer_ref = retain("forecast/synthetic-producer.txt", b"SYNTHETIC FIXTURE: hard-coded test prices, no forecast inference.\n")
    manifest_ref = retain("forecast/synthetic-provenance.json", {
        "schema_version": "blackpod.forecast_provenance.v1", "source_sha256": raw_ref["sha256"],
        "status": "REVIEWED_SOURCE_BOUND", "reviewed_by": "synthetic-example-reviewer", "reviewed_at": "2026-10-12T20:30:00Z",
        "model": {"model_id": "synthetic-example-model-not-inferred", "model_version": "fixture-v1", "model_kind": "EXTERNAL_QUANTILE",
            "producer_evidence": producer_ref, "model_artifact_evidence": model_ref, "config_evidence": config_ref,
            "feature_evidence": features_ref, "training_evidence": training_ref, "calibration_evidence": None},
        "rows": [{"source_row_number": horizon, "symbol": SYMBOL, "issued_at": ISSUED_AT, "feature_cutoff": FEATURE_CUTOFF,
            "training_cutoff": FEATURE_CUTOFF, "horizon_count": horizon, "horizon_unit": "TRADING_SESSION",
            "target_at": f"2026-10-{12 + horizon:02d}T20:00:00Z", "target_session_evidence": calendar_ref,
            "units": "PRICE_USD", "value_semantics": "PREDICTED_CLOSE_LEVEL", "reference_price": "100", "reference_at": FEATURE_CUTOFF}
            for horizon in (1, 2, 3)]})
    intake = ForecastIntake.from_mapping({"schema_version": "blackpod.forecast_intake.v1", "intake_id": "synthetic-forecast-brigade-example",
        "recorded_at": AS_OF, "shadow_as_of": AS_OF, "domain": "TRADING", "mode": "SHADOW", "scope": "SHADOW_FORECAST_INTAKE_ONLY",
        "policy": {"interface_version": "DAILY_USD_PRICE_V1", "max_forecast_age_seconds": 86400, "max_feature_age_seconds": 86400,
            "max_training_age_seconds": 86400, "allowed_horizon_sessions": [1, 2, 3, 4, 5]},
        "sources": [{"source_id": "synthetic-price-levels", "evidence": raw_ref, "format": "GALACTICA_PHASE2_CSV", "provenance_evidence": manifest_ref}],
        "authority": _authority()})
    intake_ref = retain("forecast-intake/input.v1.json", intake.to_bytes())
    seed_event = build_forecast_intake_event(intake, (), blobs)
    seed_evidence = evidence_for_forecast_intake(intake, blobs)

    bars = []
    start = datetime(2026, 7, 1, 20, tzinfo=timezone.utc)
    for day in range(104):
        when = start + timedelta(days=day)
        if when.weekday() < 5:
            index = len(bars)
            close = 100 + index * 0.02 + math.sin(index / 4)
            bars.append({"t": when.isoformat().replace("+00:00", "Z"), "o": close, "h": close + 1,
                "l": close - 1, "c": close, "v": 10000 + index * 17})
    snapshots = {symbol: {"latestQuote": {"bp": 99.98, "ap": 100.02, "t": AS_OF},
        "latestTrade": {"p": 100, "t": AS_OF}} for symbol in (SYMBOL, "SPY")}
    bar_map = {symbol: list(bars) for symbol in (SYMBOL, "SPY")}
    market = {"schema_version": "blackpod.shadow_market_packet.v1", "captured_at": AS_OF, "feed": "IEX", "adjustment": "RAW",
        "snapshots": snapshots, "bars": bar_map, "source_evidence": [retain("market/synthetic-snapshots.json", snapshots),
            retain("market/synthetic-bars.json", {"bars": bar_map, "next_page_token": None})]}
    market_raw = canonical_json_bytes(market)
    market_ref = retain("brigade/market-packet.json", market_raw)
    base_request = {"schema_version": "blackpod.brigade_shadow_request.v1", "analysis_id": "synthetic-brigade-disabled",
        "recorded_at": GENERATED_AT, "generated_at": GENERATED_AT, "domain": "TRADING", "mode": "SHADOW", "scope": "BRIGADE_RECOMMENDATIONS_ONLY",
        "forecast": {"intake_event_id": seed_event.event_id, "intake_id": intake.intake_id,
            "intake_source_sha256": sha256_bytes(intake.to_bytes()), "intake_evidence": intake_ref},
        "market_evidence": market_ref, "source_evidence": {"brigade": brigade_ref, "decay": decay_ref}, "symbols": [SYMBOL],
        "inference_mode": "DISABLED", "transcript_evidence": None, "authority": _authority()}
    disabled_request = BrigadeShadowRequest.from_mapping(base_request)
    disabled_event = build_brigade_shadow_event(disabled_request, (seed_event,), blobs)

    # These responses are authored test strings, not generated investment views.
    actions = dict(zip(MEMBERS, ("BUY", "EXIT", "HOLD", "WATCH", "HOLD")))
    def fixture_response(request):
        return "ACTION: " + actions[request["member"]] + "\nCONFIDENCE: 0.60\nREASONING: Synthetic example response for offline replay; no actual market prediction."
    captured = build_shadow_brigade_analysis(intake, market_raw, brigade, decay, generated_at=GENERATED_AT, blobs=blobs,
        text_generator=fixture_response, allow_generation=True, symbols=[SYMBOL])
    if len(captured["response_transcripts"]) != len(MEMBERS):
        raise ValueError("synthetic source fixture failed the complete five-member replay gate")
    replay_value = dict(base_request, analysis_id="synthetic-brigade-declared-replay")
    replay_base = BrigadeShadowRequest.from_mapping(replay_value)
    bundle = make_transcript_bundle(replay_base, captured["response_transcripts"], capture_kind="DECLARED_REPLAY", transport_records=[])
    transcript_ref = retain("brigade/synthetic-declared-transcripts.json", bundle)
    replay_value.update(inference_mode="RETAINED_TRANSCRIPT", transcript_evidence=transcript_ref)
    replay_request = BrigadeShadowRequest.from_mapping(replay_value)
    replay_event = build_brigade_shadow_event(replay_request, (seed_event,), blobs)
    return {"intake": intake, "seed_event": seed_event, "seed_evidence": seed_evidence,
        "disabled_request": disabled_request, "disabled_event": disabled_event, "replay_request": replay_request,
        "replay_event": replay_event, "evidence": evidence, "blobs": blobs}


def prepare_example(output_root, *, fixture_root=None):
    """Safely publish source-bound examples and seed one forecast journal event."""
    from .desk_candidate_review_cli import _write
    from .decision_journal_store import _check_existing_ancestors, _reject_source_storage
    from .auto_trading_runtime import RuntimeLedger
    output = Path(output_root).absolute()
    fixtures = Path(fixture_root).absolute() if fixture_root is not None else _fixture_root()
    check_separate_root(output, fixtures)
    _check_existing_ancestors(output); _reject_source_storage(output)
    RuntimeLedger(output)  # Read-only guards, no execution controller.
    material = example_material(fixtures)
    evidence_root, journal_root = output / "evidence", output / "journal"
    check_separate_root(evidence_root, journal_root)
    for path, raw in material["evidence"].items():
        _write(evidence_root / path, raw, (fixtures, journal_root))
    for filename, document in (("intake.json", material["intake"]), ("request.disabled.json", material["disabled_request"]),
                                ("request.replay.json", material["replay_request"])):
        _write(output / filename, document.to_bytes(), (fixtures,))
    expected = {"forecast": material["seed_event"].event_id, "brigade_disabled": material["disabled_event"].event_id,
        "brigade_replay": material["replay_event"].event_id}
    _write(output / "expected-ids.json", canonical_json_bytes(expected), (fixtures,))
    seed = JournalStore(journal_root).append(material["seed_event"], material["seed_evidence"])
    manifest = {"schema_version": SCHEMA_VERSION, "data_status": "SYNTHETIC_FIXTURE", "symbol": SYMBOL,
        "source_dates": "FIXED_SYNTHETIC_NOT_CURRENT_MARKET_RESEARCH", "forecast_admitted_count": 3,
        "journal_root": "journal", "evidence_root": "evidence", "intake_path": "intake.json",
        "disabled_request_path": "request.disabled.json", "replay_request_path": "request.replay.json", "expected_ids": expected,
        "orders_submitted": 0, "provider_calls": 0, "model_inference_calls": 0, "auto_trading_changed": False, "authority": _authority()}
    _write(output / "example.json", canonical_json_bytes(manifest), (fixtures,))
    return {**manifest, "output_root": str(output), "seed_written": seed.written, "seed_sequence": seed.sequence,
        "evidence_files": len(material["evidence"])}


def main(argv=None):
    parser = argparse.ArgumentParser(description="Prepare wholly synthetic governed forecast and Brigade shadow replay examples; no provider calls")
    parser.add_argument("--output-root", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        print(json.dumps(prepare_example(args.output_root), sort_keys=True))
        return 0
    except (ValueError, OSError, TypeError, RecursionError, JournalStoreError, RecoveryError) as exc:
        print("forecast-brigade-example: " + str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
