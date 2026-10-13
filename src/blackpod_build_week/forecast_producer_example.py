"""Prepare portable, actual-fitted synthetic inputs for offline export/replay.

The retained native models were fitted on wholly synthetic prices. This tool
does not fit anything, access a provider, call ModelDock, submit an order, or
change a runtime control. Calendar sessions, HTTP receipts and generation
clocks are explicitly declared fixtures, never current provider observations.
"""
from __future__ import annotations

import argparse
import copy
from datetime import datetime
import json
from pathlib import Path
import sys
from zoneinfo import ZoneInfo

from .contracts.forecast_producer import ForecastProducerRequest
from .contracts.mission_request import parse_strict_json_object_bytes
from .decision_journal_store import JournalStoreError, check_separate_root
from .forecast_journal import build_forecast_intake_event
from .forecast_producer_export import build_forecast_producer_export
from .forecast_producer_journal import build_forecast_producer_event
from .hashing import canonical_json_bytes, sha256_bytes
from .sentry_history_cache import RecoveryError, read_regular
from .shadow_quantitative_producer import capture_quantitative_sources

SCHEMA_VERSION = "blackpod.synthetic_forecast_producer_example.v1"
FIXTURE_SHA256 = "edd5065ebce338799cfdaf08f4ff180a696fe8006204900ab1734d81dc62bda9"
SYMBOL = "SYNTHETIC"


def _fixture_root():
    return Path(__file__).resolve().parents[2] / "fixtures/shadow_quantitative_producer"


def example_material(fixture_root=None):
    """Create fixture request/result/receipt and compatible retained evidence."""
    root = Path(fixture_root) if fixture_root is not None else _fixture_root()
    raw_fixture = read_regular(root / "synthetic_fitted.v1.json")
    if sha256_bytes(raw_fixture) != FIXTURE_SHA256:
        raise ValueError("actual-fitted synthetic fixture differs from its reviewed fingerprint")
    fixture = parse_strict_json_object_bytes(raw_fixture)
    if (set(fixture) != {"schema_version", "data_status", "history", "calendar", "result"}
            or fixture["schema_version"] != "blackpod.synthetic_fitted_quantitative_fixture.v1"
            or fixture["data_status"] != "ACTUAL_NATIVE_FIT_ON_SYNTHETIC_INPUTS"):
        raise ValueError("forecast example requires the explicitly synthetic, actual-fitted native fixture")
    original_history, calendar = fixture["history"], fixture["calendar"]
    native_result = copy.deepcopy(fixture["result"])
    evidence, blobs = {}, {}
    def retain(path, value):
        raw = value if isinstance(value, bytes) else canonical_json_bytes(value)
        if path in evidence and evidence[path] != raw:
            raise ValueError("synthetic producer evidence path conflicts")
        evidence[path], blobs[sha256_bytes(raw)] = raw, raw
        return {"path": path, "sha256": sha256_bytes(raw), "size_bytes": len(raw)}
    captured_at = original_history["captured_at"]
    snapshots = {SYMBOL: {"latestQuote": {"bp": 100, "ap": 100.01, "t": captured_at},
        "latestTrade": {"p": 100, "t": captured_at}}}
    history = {"schema_version": "blackpod.shadow_market_packet.v1", "captured_at": captured_at, "feed": "IEX", "adjustment": "RAW",
        "snapshots": snapshots, "bars": original_history["bars"], "source_evidence": [
            retain("market/synthetic-snapshots.json", snapshots),
            retain("market/synthetic-bars.json", {"bars": original_history["bars"], "next_page_token": None})]}
    market_ref = retain("market/synthetic-packet.json", history)
    zone = ZoneInfo("America/New_York")
    rows = [{"date": row["date"], **{field: datetime.fromisoformat(row[key].replace("Z", "+00:00")).astimezone(zone).strftime("%H:%M")
        for field, key in (("open", "opens_at"), ("close", "closes_at"))}} for row in calendar["sessions"]]
    calendar_ref = retain("calendar/synthetic-response.json", rows)
    # This fixed HTTP receipt is declared fixture data, not a network capture.
    calendar_receipt_ref = retain("calendar/synthetic-receipt.json", {
        "schema_version": "blackpod.read_only_calendar_capture.v1", "url": "https://paper-api.alpaca.markets/v2/calendar",
        "query": {"start": rows[0]["date"], "end": rows[-1]["date"]}, "captured_at": calendar["captured_at"],
        "method": "GET", "status": 200, "body_sha256": calendar_ref["sha256"], "size_bytes": calendar_ref["size_bytes"]})
    source_refs = [retain("native_forecast_code/" + path, raw) for path, raw in capture_quantitative_sources(root).items()]
    # The model-used prices, engineered features, labels and coefficients stay
    # byte-for-byte equivalent. Only the passive history document is wrapped
    # in the market-packet interface and its envelope binding is updated.
    native_result["history_sha256"] = sha256_bytes(canonical_json_bytes(history))
    request = ForecastProducerRequest.from_mapping({"schema_version": "blackpod.forecast_producer_request.v1",
        "run_id": "synthetic-actual-fitted-producer-example", "recorded_at": captured_at, "domain": "TRADING", "mode": "SHADOW",
        "scope": "SHADOW_FORECAST_PRODUCTION_ONLY", "symbols": [SYMBOL], "horizons": [1, 2, 3, 4, 5],
        "sources": {"market_evidence": market_ref, "calendar_evidence": calendar_ref,
            "calendar_receipt_evidence": calendar_receipt_ref, "native_source_evidence": source_refs}, "authority": native_result["authority"]})
    day = native_result["issued_at"][:10]
    started_at, completed_at = day + "T20:05:01Z", day + "T20:09:59Z"
    material = build_forecast_producer_export(request, native_result, blobs, started_at=started_at,
        completed_at=completed_at, issued_at=native_result["issued_at"])
    result_raw = canonical_json_bytes(native_result)
    receipt = {"schema_version": "blackpod.shadow_quantitative_worker_receipt.v1", "started_at": started_at,
        "completed_at": completed_at, "output_sha256": sha256_bytes(result_raw), "size_bytes": len(result_raw),
        "symbol_count": 1, "model_fit_count": 15, "provider_calls": 0, "orders_submitted": 0, "auto_trading_enabled": False}
    producer_event = build_forecast_producer_event(material["export"], material["blobs"])
    intake_event = build_forecast_intake_event(material["intake"], (producer_event,), material["blobs"])
    return {"request": request, "native_result": native_result, "worker_receipt": receipt,
        "evidence": evidence, "blobs": blobs, "export_material": material,
        "expected_ids": {"producer_event_id": producer_event.event_id, "intake_event_id": intake_event.event_id}}


def prepare_example(output_root, *, fixture_root=None):
    """Publish only immutable input fixtures; explicit export/record comes next."""
    from .auto_trading_runtime import RuntimeLedger
    from .decision_journal_store import _check_existing_ancestors, _reject_source_storage
    from .desk_candidate_review_cli import _write
    output = Path(output_root).absolute()
    fixtures = Path(fixture_root).absolute() if fixture_root is not None else _fixture_root()
    check_separate_root(output, fixtures)
    _check_existing_ancestors(output); _reject_source_storage(output)
    RuntimeLedger(output)  # Read-only directory guards; no execution controller.
    material = example_material(fixtures)
    evidence_root = output / "evidence"
    for path, raw in material["evidence"].items():
        _write(evidence_root / path, raw, (fixtures,))
    for filename, raw in (("request.json", material["request"].to_bytes()),
                          ("native-result.json", canonical_json_bytes(material["native_result"])),
                          ("worker-receipt.json", canonical_json_bytes(material["worker_receipt"]))):
        _write(output / filename, raw, (fixtures,))
    summary = {"schema_version": SCHEMA_VERSION, "data_status": "ACTUAL_NATIVE_FIT_ON_SYNTHETIC_INPUTS",
        "observations": "FIXED_SYNTHETIC_PRICES_CALENDAR_RECEIPTS_AND_CLOCKS_NOT_CURRENT_PROVIDER_DATA",
        "symbol": SYMBOL, "historical_fixture_fit_count": 15, "model_fit_count_this_invocation": 0,
        "expected_forecast_rows": 5, "expected_admitted_count": 2, "expected_deferred_count": 3,
        "expected_crossed_quantile_horizons": [1, 4, 5], "expected_ids": material["expected_ids"],
        "request_path": "request.json", "native_result_path": "native-result.json", "worker_receipt_path": "worker-receipt.json",
        "evidence_root": "evidence", "orders_submitted": 0, "provider_calls": 0, "auto_trading_changed": False,
        "authority": material["request"].authority}
    _write(output / "example.json", canonical_json_bytes(summary), (fixtures,))
    return {**summary, "output_root": str(output), "evidence_files": len(material["evidence"])}


def main(argv=None):
    parser = argparse.ArgumentParser(description="Prepare immutable actual-fitted synthetic forecast export inputs; no fit or provider calls")
    parser.add_argument("--output-root", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        print(json.dumps(prepare_example(args.output_root), sort_keys=True))
        return 0
    except (ValueError, OSError, TypeError, KeyError, RecursionError, JournalStoreError, RecoveryError) as error:
        print("forecast-producer-example: " + str(error), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
