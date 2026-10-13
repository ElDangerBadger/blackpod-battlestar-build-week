"""Authored segmented TRAIN captures over unchanged frozen fixture quotes.

Every response is produced by an injected offline callback. Literal fixture
credentials are not real keys; no credential file or provider is accessed.
Existing prices, hypotheses, captured source bytes and old reports stay intact.
"""
from __future__ import annotations

import argparse
from datetime import timedelta
import json
from pathlib import Path
import sys

from .contracts.mission_request import format_rfc3339, parse_rfc3339
from .contracts.train_market_evidence import TrainMarketExportRequest, TrainMarketSegmentRequest
from .decision_journal_store import JournalStore, JournalStoreError, check_separate_root
from .hashing import canonical_json_bytes, sha256_bytes

SCHEMA_VERSION = "blackpod.synthetic_train_market_evidence_example.v1"
CREATED_AT = "2025-04-02T10:00:00Z"
SEGMENTS_EXPORTED_AT = "2025-04-03T10:00:00Z"
EXPORTED_AT = "2025-04-03T10:00:00Z"


def fixture_sources():
    """Reuse the fourteen frozen source events with their exact evidence."""
    from .trading_shadow_review_example import example_material
    original = example_material()
    blobs = dict(original["blobs"])
    for evidence in original["event_evidence"]:
        blobs.update({sha256_bytes(raw): raw for raw in evidence.values()})
    return {**original, "blobs": blobs}


class FixtureClock:
    """An explicit synthetic receipt clock after the declared plan freeze."""
    def __init__(self):
        self.current = parse_rfc3339("2025-04-02T11:00:00Z", "fixture capture clock")

    def __call__(self):
        result = format_rfc3339(self.current)
        self.current += timedelta(seconds=2)
        return result


class AuthoredQuoteTransport:
    """Return existing authored quote rows within each exact frozen query."""
    def __init__(self, sources, *, empty_first_window=False):
        reference = sources["costs"]["request"].quote_pages[0]["body_evidence"]
        self.original = json.loads(sources["blobs"][reference["sha256"]])
        self.empty_first_window = empty_first_window
        self.first_window = sources["dataset"].sessions[0]["open_at"]
        self.calls = []

    def __call__(self, query, credentials, timeout, max_response_bytes):
        from .train_market_capture import MarketResponse
        self.calls.append(dict(query))
        if "page_token" in query:
            raise AssertionError("the authored example has exactly one page per segment")
        if self.empty_first_window and query["start"] == self.first_window:
            value = {"quotes": {}, "next_page_token": None}
        else:
            start, end = (parse_rfc3339(query[field], "fixture query") for field in ("start", "end"))
            value = {"quotes": {symbol: [row for row in self.original["quotes"][symbol]
                if start <= parse_rfc3339(row["t"], "authored quote timestamp") <= end]
                for symbol in query["symbols"].split(",")}, "next_page_token": None}
        raw = canonical_json_bytes(value)
        if len(raw) > max_response_bytes or timeout != 20:
            raise AssertionError("authored capture must respect its fixed response/time limits")
        return MarketResponse(200, raw)


def _authority():
    return {key: False for key in (
        "authorization_enabled", "capital_activation_enabled",
        "execution_enabled", "policy_changes_enabled")}


def _retain_blobs(blobs, evidence):
    blobs.update({sha256_bytes(raw): raw for raw in evidence.values()})


def prepare_example(destination):
    """Write three separately linked journals; retry does not resume partial work."""
    from .auto_trading_runtime import RuntimeLedger
    from .decision_journal_store import _check_existing_ancestors, _reject_source_storage
    from .desk_candidate_review_cli import _write
    from .paper_account_probe import PaperCredentials
    from .train_market_capture import capture_train_quotes, read_capture
    from .train_market_evidence import prepare_capture_plan
    from .train_market_evidence_journal import capture_plan_material, segment_material, export_material
    output = Path(destination).absolute()
    _check_existing_ancestors(output)
    _reject_source_storage(output)
    RuntimeLedger(output)
    sources = fixture_sources()
    rows, written = [], []
    cases = (("full", 12, False), ("partial", 2, False), ("terminal-empty", 12, True))
    for case_id, budget, empty in cases:
        case_root = output / case_id
        journal_root, capture_root = case_root / "journal", case_root / "capture"
        input_root, reports_root = case_root / "input", case_root / "reports"
        check_separate_root(journal_root, capture_root)
        check_separate_root(journal_root, input_root)
        store = JournalStore(journal_root, source_root=capture_root)
        for event, evidence in zip(sources["events"], sources["event_evidence"]):
            written.append(store.append(event, evidence).written)
        plan = prepare_capture_plan(sources["events"], sources["blobs"],
            capture_id="synthetic-train-market-" + case_id, created_at=CREATED_AT,
            base_plan_event_id=sources["studies"][0]["plan_event"].event_id)
        events, blobs = store.verified_contents()
        registered = capture_plan_material(plan, events, blobs)
        written.append(store.append(registered["event"], registered["evidence"]).written)
        # An identical example invocation preserves its deliberately partial
        # historical observation. Explicit capture commands perform resumption.
        if not capture_root.exists():
            transport = AuthoredQuoteTransport(sources, empty_first_window=empty)
            capture_train_quotes(plan, capture_root,
                PaperCredentials("FIXTURE_NOT_A_REAL_KEY", "FIXTURE_NOT_A_REAL_SECRET"),
                source_blobs=sources["blobs"], request_budget=budget,
                transport=transport, clock=FixtureClock(), sleeper=lambda seconds: None)
        captured = read_capture(plan, capture_root, exported_at=EXPORTED_AT)
        snapshot = captured["snapshot"]
        snapshot_raw = canonical_json_bytes(snapshot)
        snapshot_ref = {"path": "train-evidence/capture-snapshot.v1.json",
            "sha256": sha256_bytes(snapshot_raw), "size_bytes": len(snapshot_raw)}
        export_id = "synthetic-train-market-" + case_id + "-export"
        segment_ids = []
        for segment in snapshot["segments"]:
            if segment["status"] == "NOT_STARTED":
                if segment["pages"]:
                    raise ValueError("unstarted example segment cannot contain a retained response")
                continue
            request = TrainMarketSegmentRequest.from_mapping({
                "schema_version": "blackpod.train_market_segment_export_request.v1",
                "export_id": export_id, "capture_plan_event_id": registered["event"].event_id,
                "segment_id": segment["segment_id"], "pages": segment["pages"],
                "failure": segment["failure"], "exported_at": SEGMENTS_EXPORTED_AT,
                "auto_trading_enabled": False, "authority": _authority()})
            events, blobs = store.verified_contents()
            _retain_blobs(blobs, captured["evidence"])
            projected = segment_material(request, events, blobs)
            written.append(store.append(projected["event"], projected["evidence"]).written)
            segment_ids.append(projected["event"].event_id)
        request = TrainMarketExportRequest.from_mapping({
            "schema_version": "blackpod.train_market_export_request.v1",
            "export_id": export_id, "capture_plan_event_id": registered["event"].event_id,
            "segment_event_ids": sorted(segment_ids), "exported_at": EXPORTED_AT,
            "continuity_event_id": None, "coverage_review_evidence": None,
            "capture_snapshot_evidence": snapshot_ref,
            "capture_checkpoint_evidence": snapshot["checkpoint_evidence"],
            "auto_trading_enabled": False, "authority": _authority()})
        events, blobs = store.verified_contents()
        _retain_blobs(blobs, captured["evidence"])
        blobs[snapshot_ref["sha256"]] = snapshot_raw
        aggregate = export_material(request, events, blobs)
        written.append(store.append(aggregate["event"], aggregate["evidence"]).written)
        _write(input_root / "capture-plan.v1.json", plan.to_bytes(), (journal_root, capture_root))
        _write(input_root / "snapshot.v1.json", canonical_json_bytes(snapshot), (journal_root, capture_root))
        _write(input_root / "export-request.v1.json", request.to_bytes(), (journal_root, capture_root))
        _write(reports_root / "export.v1.json", canonical_json_bytes(aggregate["result"]), (journal_root, capture_root))
        final_events = store.events()
        if [event.to_bytes() for event in final_events[:14]] != [event.to_bytes() for event in sources["events"]]:
            raise ValueError("TRAIN capture example changed an original source event")
        result = aggregate["result"]
        rows.append({"case_id": case_id, "capture_id": plan.capture_id,
            "capture_plan_event_id": registered["event"].event_id,
            "export_event_id": aggregate["event"].event_id, "export_id": export_id,
            "status": result["status"], "capture_complete": result["capture_complete"],
            "coverage_complete": result["coverage_complete"], "counts": result["counts"],
            "continuity_coverage": result["continuity_coverage"],
            "attempt_count": snapshot["attempt_count"],
            "journal_root": case_id + "/journal", "capture_root": case_id + "/capture",
            "plan_path": case_id + "/input/capture-plan.v1.json",
            "snapshot_path": case_id + "/input/snapshot.v1.json",
            "export_request_path": case_id + "/input/export-request.v1.json",
            "result_path": case_id + "/reports/export.v1.json",
            "journal_verification": store.verify().to_dict()})
    summary = {"schema_version": SCHEMA_VERSION, "data_status": "SYNTHETIC_FIXTURE_ONLY",
        "source_event_count_per_journal": 14, "cases": rows, "events_written": sum(written),
        "raw_bodies_are_authored_quote_subsets_not_real_provider_captures": True,
        "credential_files_read": 0, "provider_calls": 0, "model_inference_calls": 0,
        "orders_submitted": 0, "new_strategy_returns_computed": False,
        "uncertainty_computed": False, "economic_hypothesis_supported": False,
        "existing_gate_override": False, "desk_budget_activated": False,
        "capital_transfers_enabled": False, "final_holdout_scored": False,
        "auto_trading_enabled": False}
    _write(output / "manifest.json", canonical_json_bytes({key: value for key, value in summary.items()
        if key != "events_written"}), ())
    return summary


def main(argv=None):
    parser = argparse.ArgumentParser(description="Run explicit authored TRAIN capture/export examples offline.")
    parser.add_argument("--output-root", type=Path, required=True)
    arguments = parser.parse_args(argv)
    try:
        print(json.dumps(prepare_example(arguments.output_root), sort_keys=True))
        return 0
    except (OSError, ValueError, JournalStoreError) as exc:
        print(str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
