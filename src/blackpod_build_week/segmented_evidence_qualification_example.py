"""Authored consumer examples over exact frozen v18/v19 source records.

New native-shaped TRAIN pages copy original synthetic quote rows. They are
explicit authored evidence, not provider captures or operational capture audits.
The consumer records only compact source bindings and never duplicates raw data.
"""
from __future__ import annotations

import argparse
from datetime import timedelta
import json
from pathlib import Path
import sys

from .contracts.mission_request import parse_rfc3339, format_rfc3339
from .contracts.segmented_evidence_qualification import (
    SegmentedEvidenceBinding, SegmentedEvidenceQualificationRequest,
)
from .contracts.trading_evidence_qualification import TradingEvidenceQualificationPolicy
from .contracts.train_market_evidence import TrainMarketSegmentRequest, TrainMarketExportRequest
from .decision_journal_store import JournalStore, JournalStoreError, check_separate_root
from .hashing import canonical_json_bytes, sha256_bytes

SCHEMA_VERSION = "blackpod.synthetic_segmented_evidence_qualification_example.v1"
CAPTURE_CREATED_AT = "2025-04-03T10:00:00Z"
CAPTURED_AT = "2025-04-03T11:00:00Z"
EXPORTED_AT = "2025-04-04T10:00:00Z"
BINDING_RECORDED_AT = "2025-04-05T10:00:00Z"
QUALIFICATION_RECORDED_AT = "2025-04-05T11:00:00Z"
DATA_CUTOFF_AT = "2025-04-05T10:30:00Z"


def _authority():
    return {key: False for key in (
        "authorization_enabled", "capital_activation_enabled",
        "execution_enabled", "policy_changes_enabled")}


def _ref(path, raw):
    return {"path": path, "sha256": sha256_bytes(raw), "size_bytes": len(raw)}


def _retain(blobs, evidence, path, value):
    raw = value if isinstance(value, bytes) else canonical_json_bytes(value)
    reference = _ref(path, raw)
    if path in evidence and evidence[path] != raw:
        raise ValueError("segmented fixture evidence path contains conflicting bytes")
    evidence[path], blobs[reference["sha256"]] = raw, raw
    return reference


def source_material():
    """Build old source history and four authored segmented export groups.

    This helper is independent of the new qualification method. It supports
    focused contract/journal tests without publishing a large fixture repeatedly.
    """
    from .trading_evidence_qualification_example import example_material as original_material
    from .trading_evidence_qualification_journal import policy_material
    from .train_market_evidence import prepare_capture_plan
    from .train_market_evidence_journal import capture_plan_material, segment_material, export_material
    original = original_material()
    events, retained = list(original["events"]), list(original["event_evidence"])
    blobs = dict(original["blobs"])
    for evidence in retained:
        blobs.update({sha256_bytes(raw): raw for raw in evidence.values()})
    policies = {row["case_id"]: row for row in original["cases"]}
    clean = policies["clean-declared-design"]["policy"]
    new_policies = {}
    for label, field in (("missing-assumptions", "training_cost_assumptions_evidence"),
                         ("missing-independent-coverage", "continuity_event_id")):
        policy = TradingEvidenceQualificationPolicy.from_mapping({
            **clean.to_dict(), "policy_id": "segmented-fixture-" + label + "-policy",
            "recorded_at": "2025-04-02T12:00:00Z", field: None})
        material = policy_material(policy, events, blobs)
        events.append(material["event"])
        retained.append(material["evidence"])
        blobs.update({sha256_bytes(raw): raw for raw in material["evidence"].values()})
        new_policies[label] = {"policy": policy, "policy_event": material["event"]}
    original_quote_ref = original["original"]["costs"]["request"].quote_pages[0]["body_evidence"]
    native = json.loads(blobs[original_quote_ref["sha256"]])
    exports, authored = {}, {}
    capture_specs = (
        ("reversal-full", policies["clean-declared-design"], 12, False),
        ("reversal-partial", policies["clean-declared-design"], 2, False),
        ("reversal-terminal-empty", policies["clean-declared-design"], 12, True),
        ("continuation-full", policies["insufficient-joint-sample"], 12, False),
    )
    for label, source, count, empty in capture_specs:
        plan = prepare_capture_plan(events, blobs,
            capture_id="segmented-fixture-" + label + "-capture",
            created_at=CAPTURE_CREATED_AT, base_plan_event_id=source["policy"].base_plan_event_id)
        registered = capture_plan_material(plan, events, blobs)
        events.append(registered["event"])
        retained.append(registered["evidence"])
        blobs.update({sha256_bytes(raw): raw for raw in registered["evidence"].values()})
        export_id = "segmented-fixture-" + label + "-export"
        segment_ids = []
        for index, segment in enumerate(plan.segments[:count]):
            query = segment["query"]
            lower, upper = (parse_rfc3339(query[field], "fixture window") for field in ("start", "end"))
            body = {"quotes": {} if empty and index == 0 else {
                symbol: [row for row in native["quotes"][symbol]
                    if lower <= parse_rfc3339(row["t"], "authored native quote") <= upper]
                for symbol in query["symbols"].split(",")}, "next_page_token": None}
            path = "segmented-fixture/" + label + "/window-%04d" % index
            body_ref = _retain(blobs, authored, path + ".body.raw", body)
            receipt = {"schema_version": "blackpod.trading_evidence_capture.v1",
                "method": "GET", "url": "https://data.alpaca.markets/v2/stocks/quotes",
                "query": query, "captured_at": format_rfc3339(
                    parse_rfc3339(CAPTURED_AT, "authored capture clock") + timedelta(seconds=index)),
                "status": 200, "body_sha256": body_ref["sha256"], "size_bytes": body_ref["size_bytes"]}
            receipt_ref = _retain(blobs, authored, path + ".receipt.json", receipt)
            request = TrainMarketSegmentRequest.from_mapping({
                "schema_version": "blackpod.train_market_segment_export_request.v1",
                "export_id": export_id, "capture_plan_event_id": registered["event"].event_id,
                "segment_id": segment["segment_id"],
                "pages": [{"body_evidence": body_ref, "receipt_evidence": receipt_ref}],
                "failure": None, "exported_at": EXPORTED_AT,
                "auto_trading_enabled": False, "authority": _authority()})
            material = segment_material(request, events, blobs)
            events.append(material["event"])
            retained.append(material["evidence"])
            blobs.update({sha256_bytes(raw): raw for raw in material["evidence"].values()})
            segment_ids.append(material["event"].event_id)
        request = TrainMarketExportRequest.from_mapping({
            "schema_version": "blackpod.train_market_export_request.v1", "export_id": export_id,
            "capture_plan_event_id": registered["event"].event_id,
            "segment_event_ids": sorted(segment_ids), "exported_at": EXPORTED_AT,
            "continuity_event_id": None, "coverage_review_evidence": None,
            "capture_snapshot_evidence": None, "capture_checkpoint_evidence": [],
            "auto_trading_enabled": False, "authority": _authority()})
        material = export_material(request, events, blobs)
        events.append(material["event"])
        retained.append(material["evidence"])
        blobs.update({sha256_bytes(raw): raw for raw in material["evidence"].values()})
        exports[label] = {"plan": plan, "plan_event": registered["event"],
            "export_event": material["event"], "result": material["result"]}
    case_specs = (
        ("full-reversal", policies["clean-declared-design"], "reversal-full", "READY_FOR_QUALIFIED_STUDY_DESIGN"),
        ("partial-reversal", policies["clean-declared-design"], "reversal-partial", "DEFER_EVIDENCE_QUALIFICATION"),
        ("terminal-empty-reversal", policies["clean-declared-design"], "reversal-terminal-empty", "DEFER_EVIDENCE_QUALIFICATION"),
        ("insufficient-continuation", policies["insufficient-joint-sample"], "continuation-full", "DEFER_EVIDENCE_QUALIFICATION"),
        ("inactive-proposed", policies["inactive-proposed-design"], "continuation-full", "DEFER_EVIDENCE_QUALIFICATION"),
        ("missing-assumptions", new_policies["missing-assumptions"], "reversal-full", "DEFER_EVIDENCE_QUALIFICATION"),
        ("missing-independent-coverage", new_policies["missing-independent-coverage"], "reversal-full", "DEFER_EVIDENCE_QUALIFICATION"),
    )
    return {"original": original, "events": tuple(events), "event_evidence": tuple(retained),
        "blobs": blobs, "authored_evidence": authored, "exports": exports,
        "cases": [{"case_id": label, "policy": source["policy"], "policy_event": source["policy_event"],
            "capture": exports[capture], "expected": expected} for label, source, capture, expected in case_specs]}


def example_material():
    """Append explicit bindings and qualifications to the existing source chain."""
    from .segmented_evidence_qualification_journal import binding_material, qualification_material
    material = source_material()
    events, retained, blobs = list(material["events"]), list(material["event_evidence"]), dict(material["blobs"])
    rows = []
    for case in material["cases"]:
        binding = SegmentedEvidenceBinding.from_mapping({
            "schema_version": "blackpod.segmented_evidence_qualification_binding.v1",
            "binding_id": "segmented-fixture-" + case["case_id"] + "-binding",
            "recorded_at": BINDING_RECORDED_AT, "domain": "TRADING", "mode": "SHADOW_RESEARCH",
            "scope": "SEGMENTED_TRAIN_EVIDENCE_QUALIFICATION_ONLY",
            "qualification_policy_event_id": case["policy_event"].event_id,
            "capture_plan_event_id": case["capture"]["plan_event"].event_id,
            "calibration_source": "VERIFIED_SEGMENTED_TRAIN_EXPORT_ONLY",
            "supersedes_binding_event_id": None, "auto_trading_enabled": False, "authority": _authority()})
        registered = binding_material(binding, events, blobs)
        events.append(registered["event"])
        retained.append(registered["evidence"])
        blobs.update({sha256_bytes(raw): raw for raw in registered["evidence"].values()})
        request = SegmentedEvidenceQualificationRequest.from_mapping({
            "schema_version": "blackpod.segmented_evidence_qualification_request.v1",
            "qualification_id": "segmented-fixture-" + case["case_id"] + "-qualification",
            "binding_event_id": registered["event"].event_id,
            "aggregate_export_event_id": case["capture"]["export_event"].event_id,
            "recorded_at": QUALIFICATION_RECORDED_AT, "data_cutoff_at": DATA_CUTOFF_AT,
            "supersedes_event_id": None, "auto_trading_enabled": False, "authority": _authority()})
        assessed = qualification_material(request, events, blobs)
        if assessed["result"]["status"] != case["expected"]:
            raise ValueError("segmented fixture disagrees with expected case: " + case["case_id"])
        events.append(assessed["event"])
        retained.append(assessed["evidence"])
        blobs.update({sha256_bytes(raw): raw for raw in assessed["evidence"].values()})
        rows.append({**case, "binding": binding, "binding_event": registered["event"],
            "request": request, "qualification_event": assessed["event"], "result": assessed["result"]})
    return {**material, "events": tuple(events), "event_evidence": tuple(retained), "blobs": blobs, "cases": rows}


def prepare_example(destination):
    """Publish once; verified identical prefixes do not require repeated appends."""
    from .auto_trading_runtime import RuntimeLedger
    from .decision_journal_batch import append_journal_batch
    from .decision_journal_store import _check_existing_ancestors, _reject_source_storage
    from .desk_candidate_review_cli import _write
    output = Path(destination).absolute()
    _check_existing_ancestors(output); _reject_source_storage(output); RuntimeLedger(output)
    journal_root, input_root, evidence_root = output / "journal", output / "input", output / "evidence"
    check_separate_root(journal_root, input_root); check_separate_root(journal_root, evidence_root)
    material = example_material()
    store = JournalStore(journal_root)
    existing = store.events() if journal_root.exists() else ()
    expected = material["events"]
    if len(existing) > len(expected) or [event.to_bytes() for event in existing] != [event.to_bytes() for event in expected[:len(existing)]]:
        raise ValueError("existing example journal is not the exact immutable fixture prefix")
    suffix = [{"event": event, "evidence": evidence} for event, evidence in
        zip(expected[len(existing):], material["event_evidence"][len(existing):])]
    appended = append_journal_batch(store, suffix) if suffix else ()
    for path, raw in material["authored_evidence"].items():
        _write(evidence_root / path, raw, (journal_root,))
    rows = []
    for case in material["cases"]:
        label = case["case_id"]
        _write(input_root / (label + ".binding.json"), case["binding"].to_bytes(), (journal_root,))
        _write(input_root / (label + ".request.json"), case["request"].to_bytes(), (journal_root,))
        _write(output / "reports" / (label + ".result.json"), canonical_json_bytes(case["result"]), (journal_root,))
        rows.append({"case_id": label, "policy_id": case["policy"].policy_id,
            "capture_id": case["capture"]["plan"].capture_id,
            "binding_event_id": case["binding_event"].event_id,
            "qualification_event_id": case["qualification_event"].event_id,
            "aggregate_export_event_id": case["capture"]["export_event"].event_id,
            "status": case["result"]["status"], "reason_codes": case["result"]["reason_codes"],
            "request_path": "input/" + label + ".request.json",
            "binding_path": "input/" + label + ".binding.json",
            "result_path": "reports/" + label + ".result.json"})
    summary = {"schema_version": SCHEMA_VERSION, "data_status": "SYNTHETIC_FIXTURE_ONLY",
        "original_v18_events_preserved": len(material["original"]["events"]),
        "cases": rows, "events_written": sum(result.written for result in appended),
        "journal_publication": "VALIDATED_IMMUTABLE_BATCH", "journal_verification": store.verify().to_dict(),
        "journal_root": "journal", "provider_calls": 0, "real_credential_files_read": 0,
        "model_inference_calls": 0, "orders_submitted": 0, "raw_corpus_duplicated_by_consumer": False,
        "raw_bodies_are_authored_quote_subsets_not_real_provider_captures": True,
        "operational_capture_audit_claimed": False, "new_strategy_returns_computed": False,
        "economic_hypothesis_supported": False, "uncertainty_computed": False,
        "existing_gate_override": False, "desk_budget_activated": False, "capital_transfers_enabled": False,
        "final_holdout_scored": False, "auto_trading_enabled": False}
    _write(output / "manifest.json", canonical_json_bytes({key: value for key, value in summary.items() if key != "events_written"}), ())
    return summary


def main(argv=None):
    parser = argparse.ArgumentParser(description="Run authored segmented-evidence qualification cases offline.")
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
