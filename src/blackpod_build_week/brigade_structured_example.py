"""Wholly synthetic v2 Brigade requests and strict structured-response replay.

The forecast, market observations and member views are authored fixtures. No
provider, broker, model inference, credential source or execution controller is
used. The original forecast/Brigade example remains unchanged and independently
replayable; this example adds a distinct v2 research identity.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from .contracts.brigade_response import SCHEMA_VERSION as RESPONSE_CONTRACT
from .contracts.brigade_shadow import BrigadeShadowRequest
from .decision_journal_store import JournalStore, JournalStoreError, check_separate_root
from .forecast_brigade_example import (
    GENERATED_AT, SYMBOL, _authority, _fixture_root, example_material as legacy_example_material,
)
from .forecast_journal import build_brigade_shadow_event
from .hashing import canonical_json_bytes, sha256_bytes
from .sentry_history_cache import RecoveryError
from .shadow_brigade_analysis import MEMBERS, build_shadow_brigade_analysis

SCHEMA_VERSION = "blackpod.synthetic_brigade_structured_example.v1"


def example_material(fixture_root=None):
    """Extend the original synthetic intake with independent strict v2 views."""
    from .brigade_shadow_transport import make_transcript_bundle

    base = legacy_example_material(fixture_root)
    evidence = dict(base["evidence"])
    # The old authored text replay is not a source of the new structured views.
    evidence.pop("brigade/synthetic-declared-transcripts.json")
    blobs = {sha256_bytes(raw): raw for raw in evidence.values()}
    value = base["disabled_request"].to_dict()
    value.update(schema_version="blackpod.brigade_shadow_request.v2", response_contract=RESPONSE_CONTRACT,
                 analysis_id="synthetic-brigade-structured-disabled")
    disabled_request = BrigadeShadowRequest.from_mapping(value)
    disabled_event = build_brigade_shadow_event(disabled_request, (base["seed_event"],), blobs)

    actions = dict(zip(MEMBERS, ("BUY", "EXIT", "HOLD", "WATCH", "HOLD")))

    def authored_response(request):
        return canonical_json_bytes({
            "schema_version": RESPONSE_CONTRACT, "member": request["member"], "symbol": request["symbol"],
            "action": actions[request["member"]], "heuristic_confidence": 0.6,
            "reasoning": "Synthetic structured example view for offline replay; no actual market prediction.",
        }).decode("utf-8")

    captured = build_shadow_brigade_analysis(base["intake"], evidence["brigade/market-packet.json"],
        evidence["brigade/blackwell_brigade.py"], evidence["brigade/decay.py"], generated_at=GENERATED_AT,
        blobs=blobs, text_generator=authored_response, allow_generation=True, symbols=[SYMBOL],
        response_contract=RESPONSE_CONTRACT)
    if len(captured["response_transcripts"]) != len(MEMBERS):
        raise ValueError("synthetic structured example requires complete native five-member coverage")
    replay_value = dict(value, analysis_id="synthetic-brigade-structured-declared-replay")
    replay_base = BrigadeShadowRequest.from_mapping(replay_value)
    bundle = make_transcript_bundle(replay_base, captured["response_transcripts"], capture_kind="DECLARED_REPLAY",
                                   transport_records=[])
    raw = canonical_json_bytes(bundle)
    path = "brigade/synthetic-structured-transcripts.json"
    if path in evidence:
        raise ValueError("synthetic structured transcript evidence path conflicts")
    evidence[path], blobs[sha256_bytes(raw)] = raw, raw
    replay_value.update(inference_mode="RETAINED_TRANSCRIPT", transcript_evidence={
        "path": path, "sha256": sha256_bytes(raw), "size_bytes": len(raw),
    })
    replay_request = BrigadeShadowRequest.from_mapping(replay_value)
    replay_event = build_brigade_shadow_event(replay_request, (base["seed_event"],), blobs)
    return {"intake": base["intake"], "seed_event": base["seed_event"], "seed_evidence": base["seed_evidence"],
        "disabled_request": disabled_request, "disabled_event": disabled_event, "replay_request": replay_request,
        "replay_event": replay_event, "evidence": evidence, "blobs": blobs}


def prepare_example(output_root, *, fixture_root=None):
    """Publish immutable synthetic inputs and seed only their forecast event."""
    from .auto_trading_runtime import RuntimeLedger
    from .decision_journal_store import _check_existing_ancestors, _reject_source_storage
    from .desk_candidate_review_cli import _write

    output = Path(output_root).absolute()
    fixtures = Path(fixture_root).absolute() if fixture_root is not None else _fixture_root()
    check_separate_root(output, fixtures)
    _check_existing_ancestors(output); _reject_source_storage(output)
    RuntimeLedger(output)  # Read-only path guards, no controller activation.
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
        "response_contract": RESPONSE_CONTRACT, "response_capture_kind": "DECLARED_REPLAY",
        "journal_root": "journal", "evidence_root": "evidence", "intake_path": "intake.json",
        "disabled_request_path": "request.disabled.json", "replay_request_path": "request.replay.json",
        "expected_ids": expected, "orders_submitted": 0, "provider_calls": 0, "model_inference_calls": 0,
        "auto_trading_changed": False, "authority": _authority()}
    _write(output / "example.json", canonical_json_bytes(manifest), (fixtures,))
    return {**manifest, "output_root": str(output), "seed_written": seed.written, "seed_sequence": seed.sequence,
            "evidence_files": len(material["evidence"])}


def main(argv=None):
    parser = argparse.ArgumentParser(description="Prepare wholly synthetic structured Brigade shadow replay; no provider calls")
    parser.add_argument("--output-root", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        print(json.dumps(prepare_example(args.output_root), sort_keys=True))
        return 0
    except (ValueError, OSError, TypeError, RecursionError, JournalStoreError, RecoveryError) as exc:
        print("brigade-structured-example: " + str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
