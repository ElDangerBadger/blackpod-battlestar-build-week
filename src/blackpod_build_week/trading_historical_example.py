"""Entirely authored examples for governed independent trading research.

Prices, calendars and HTTP receipt declarations are fixtures. No request is
sent to the named provider; nothing proves an economic edge, actual historical
availability, valid exchange calendar, or authentic provider response.
"""
from __future__ import annotations

import argparse
from datetime import date, timedelta
import json
from pathlib import Path
import sys

from .contracts.historical_intake import HistoricalIntakeRequest
from .decision_journal_store import JournalStore, JournalStoreError, check_separate_root
from .hashing import canonical_json_bytes, sha256_bytes
from .sentry_history_cache import RecoveryError
from .trading_historical_intake import build_historical_intake
from .trading_hypotheses import catalog_documents, catalog_hypotheses

SCHEMA_VERSION = "blackpod.synthetic_historical_research_example.v1"
SYMBOLS = ["SYNTHA", "SYNTHB"]
CAPTURED_AT = "2025-04-01T10:00:00Z"
INTAKE_RECORDED_AT = "2025-04-01T10:05:00Z"
CATALOG_RECORDED_AT = "2025-04-01T10:10:00Z"
REGISTERED_AT = "2025-04-01T10:20:00Z"
EVALUATED_AT = "2025-04-01T11:00:00Z"


def _authority():
    return {field: False for field in (
        "authorization_enabled", "capital_activation_enabled", "execution_enabled", "policy_changes_enabled",
    )}


def _reference(path, raw):
    return {"path": path, "sha256": sha256_bytes(raw), "size_bytes": len(raw)}


def synthetic_source_material():
    """Build exactly 40 invented returned sessions, with no holiday inference.

    The weekday selection only constructs fictional test dates. Intake consumes
    their explicitly retained calendar rows and makes no weekday substitution.
    These rows are not claimed to be the actual US exchange calendar.
    """
    days, cursor = [], date(2025, 1, 2)
    while len(days) < 40:
        if cursor.weekday() < 5:
            days.append(cursor.isoformat())
        cursor += timedelta(days=1)
    calendar = [{"date": day, "open": "09:30", "close": "16:00", "session_open": "0400",
                 "session_close": "2000", "settlement_date": day} for day in days]
    bars = {symbol: [] for symbol in SYMBOLS}
    for index, day in enumerate(days):
        for offset, symbol in enumerate(SYMBOLS):
            opening = 100 + offset * 100 + index
            bars[symbol].append({"t": day + "T05:00:00Z", "o": opening, "h": opening + 2,
                "l": opening - 1, "c": opening + 1, "v": 10000 + index, "n": 100,
                "vw": opening})
    raw_bars = canonical_json_bytes({"bars": bars, "next_page_token": None})
    raw_calendar = canonical_json_bytes(calendar)
    bars_ref = _reference("synthetic-historical/bars.json", raw_bars)
    calendar_ref = _reference("synthetic-historical/calendar.raw", raw_calendar)
    bars_receipt = {"schema_version": "blackpod.read_only_historical_capture.v1", "method": "GET",
        "url": "https://data.alpaca.markets/v2/stocks/bars",
        "query": {"symbols": ",".join(SYMBOLS), "timeframe": "1Day", "start": days[0] + "T00:00:00Z",
            "end": days[-1] + "T23:59:59Z", "feed": "iex", "adjustment": "raw", "sort": "asc", "limit": 10000},
        "captured_at": CAPTURED_AT, "status": 200, "body_sha256": bars_ref["sha256"], "size_bytes": len(raw_bars)}
    calendar_receipt = {"schema_version": "blackpod.read_only_historical_capture.v1", "method": "GET",
        "url": "https://paper-api.alpaca.markets/v2/calendar", "query": {"start": days[0], "end": days[-1]},
        "captured_at": CAPTURED_AT, "status": 200, "body_sha256": calendar_ref["sha256"], "size_bytes": len(raw_calendar)}
    raw_bars_receipt, raw_calendar_receipt = (canonical_json_bytes(row) for row in (bars_receipt, calendar_receipt))
    evidence = {bars_ref["path"]: raw_bars, calendar_ref["path"]: raw_calendar,
        "synthetic-historical/bars-receipt.json": raw_bars_receipt,
        "synthetic-historical/calendar-receipt.json": raw_calendar_receipt}
    request = HistoricalIntakeRequest.from_mapping({"schema_version": "blackpod.trading_historical_intake_request.v1",
        "run_id": "synthetic-independent-historical-intake", "recorded_at": INTAKE_RECORDED_AT,
        "domain": "TRADING", "mode": "OFFLINE_RESEARCH", "scope": "RETAINED_DAILY_RESEARCH_INTAKE_ONLY",
        "universe": SYMBOLS, "date_range": {"start": days[0], "end": days[-1]}, "feed": "IEX", "adjustment": "RAW",
        "availability_assumption": {"policy": "RETURNED_SESSION_END_PLUS_DECLARED_DELAY", "delay_seconds": 60,
            "declared_by": "synthetic-fixture-author", "rationale": "Authored session-end-plus-delay demonstrates assumed timing; it is not observed historical publication."},
        "sources": {"bars_evidence": bars_ref, "calendar_evidence": calendar_ref,
            "bars_receipt_evidence": _reference("synthetic-historical/bars-receipt.json", raw_bars_receipt),
            "calendar_receipt_evidence": _reference("synthetic-historical/calendar-receipt.json", raw_calendar_receipt)},
        "auto_trading_enabled": False, "authority": _authority()})
    return {"request": request, "evidence": evidence, "blobs": {sha256_bytes(raw): raw for raw in evidence.values()}}


def example_material():
    """Compose two no-score data-quality studies and their append-only events."""
    from .trading_research_intake_cli import make_plan
    from .trading_research_intake_journal import (
        build_catalog_event, build_intake_event, catalog_evidence, intake_evidence,
    )
    from .trading_research_journal import build_plan_event, build_evaluation_event, evidence_for_research

    sources = synthetic_source_material()
    intake = build_historical_intake(sources["request"], sources["blobs"])
    catalog = catalog_hypotheses(CATALOG_RECORDED_AT, "synthetic-fixture-author", catalog_id="synthetic-independent-hypotheses")
    evidence, blobs = dict(intake["evidence"]), dict(intake["blobs"])
    retained_catalog = catalog_evidence(catalog)
    evidence.update(retained_catalog)
    blobs.update({sha256_bytes(raw): raw for raw in retained_catalog.values()})
    catalog_event = build_catalog_event(catalog)
    intake_event = build_intake_event(intake["export"], blobs, recorded_at=INTAKE_RECORDED_AT)
    events, event_evidence = [catalog_event, intake_event], [retained_catalog, intake_evidence(intake["export"], blobs)]
    studies = []
    for hypothesis in catalog_documents(catalog):
        plan_id = "synthetic-plan-" + hypothesis.hypothesis_id
        material = make_plan(hypothesis, intake["dataset"], blobs, registered_at=REGISTERED_AT,
            experiment_id="synthetic-experiment-" + hypothesis.hypothesis_id, plan_id=plan_id)
        for path, raw in material["evidence"].items():
            if path in evidence and evidence[path] != raw:
                raise ValueError("synthetic study evidence paths collide")
            evidence[path] = raw
        blobs.update(material["blobs"])
        plan = material["plan"]
        plan_event = build_plan_event(plan, tuple(events), blobs)
        events.append(plan_event)
        event_evidence.append(evidence_for_research(plan, blobs))
        evaluation_id = "synthetic-evaluation-" + hypothesis.hypothesis_id
        evaluation_event = build_evaluation_event(plan, tuple(events), blobs,
            evaluation_id=evaluation_id, recorded_at=EVALUATED_AT)
        events.append(evaluation_event)
        event_evidence.append(evidence_for_research(plan, blobs))
        studies.append({"hypothesis": hypothesis, "plan": plan, "intents": material["intents"],
            "plan_event": plan_event, "evaluation_event": evaluation_event, "evaluation_id": evaluation_id,
            "result": evaluation_event.payload["result"]})
    return {"sources": sources, "request": sources["request"], "intake": intake, "dataset": intake["dataset"],
        "catalog": catalog, "studies": studies, "events": tuple(events), "event_evidence": tuple(event_evidence),
        "evidence": evidence, "blobs": blobs}


def prepare_example(output_root):
    """Publish fixture inputs and a six-event journal; never activate a runtime."""
    from .auto_trading_runtime import RuntimeLedger
    from .decision_journal_store import _check_existing_ancestors, _reject_source_storage
    from .desk_candidate_review_cli import _write

    output = Path(output_root).absolute()
    _check_existing_ancestors(output)
    _reject_source_storage(output)
    RuntimeLedger(output)
    input_root, evidence_root, journal_root = output / "input", output / "evidence", output / "journal"
    check_separate_root(input_root, journal_root)
    check_separate_root(evidence_root, journal_root)
    material = example_material()
    for path, raw in material["evidence"].items():
        _write(evidence_root / path, raw, (journal_root,))
    _write(input_root / "request.json", material["request"].to_bytes(), (journal_root,))
    _write(input_root / "catalog.json", material["catalog"].to_bytes(), (journal_root,))
    _write(input_root / "intake.json", material["intake"]["export"].to_bytes(), (journal_root,))
    study_rows = []
    for index, study in enumerate(material["studies"], 1):
        path = "input/plan-%d.json" % index
        _write(output / path, study["plan"].to_bytes(), (journal_root,))
        study_rows.append({"hypothesis_id": study["hypothesis"].hypothesis_id, "plan_path": path,
            "evaluation_id": study["evaluation_id"], "evaluation_recorded_at": EVALUATED_AT,
            "plan_event_id": study["plan_event"].event_id, "evaluation_event_id": study["evaluation_event"].event_id,
            "scoring_status": "DATA_QUALITY_ONLY_NO_STRATEGY_PRODUCER"})
    _write(output / "expected-results.json", canonical_json_bytes([study["result"] for study in material["studies"]]), ())
    store, appended = JournalStore(journal_root), []
    for event, retained in zip(material["events"], material["event_evidence"]):
        appended.append(store.append(event, retained).written)
    verification = store.verify().to_dict()
    manifest = {"schema_version": SCHEMA_VERSION, "data_status": "SYNTHETIC_FIXTURE",
        "observations": "ENTIRELY_AUTHORED_PRICES_CALENDAR_AND_HTTP_RECEIPT_DECLARATIONS_NOT_ACTUAL_PROVIDER_RESPONSES",
        "symbols": SYMBOLS, "included_session_count": len(material["dataset"].sessions),
        "hypothesis_count": len(material["studies"]), "studies": study_rows,
        "evidence_root": "evidence", "journal_root": "journal", "request_path": "input/request.json",
        "catalog_path": "input/catalog.json", "intake_path": "input/intake.json",
        "hypothesis_performance_evaluated": False, "decision_count": 0, "strategy_producer_present": False,
        "historical_point_in_time_verified": False, "price_return_continuity_verified": False,
        "recorded_paper_budgets_used": False, "orders_submitted": 0, "provider_calls": 0,
        "model_inference_calls": 0, "auto_trading_changed": False, "auto_trading_enabled": False,
        "authority": _authority()}
    _write(output / "example.json", canonical_json_bytes(manifest), ())
    return {**manifest, "output_root": str(output), "events_written": sum(appended),
            "journal_verification": verification}


def main(argv=None):
    parser = argparse.ArgumentParser(description="Prepare entirely synthetic governed historical research; no strategy or external calls")
    parser.add_argument("--output-root", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        print(json.dumps(prepare_example(args.output_root), sort_keys=True))
        return 0
    except (ValueError, OSError, TypeError, KeyError, RecursionError, JournalStoreError, RecoveryError) as exc:
        print("trading-historical-example: " + str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
