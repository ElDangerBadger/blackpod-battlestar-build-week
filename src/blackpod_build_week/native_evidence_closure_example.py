"""Authored offline closure reviews; no checklist can replace native evidence.

The unchanged 84-event source history remains an exact prefix. A separate,
explicitly synthetic wide quote observation tests diagnostics without changing
the original bars, hypotheses, policies, receipts or quote bodies.
"""
from __future__ import annotations

import argparse
from datetime import timedelta
import json
from pathlib import Path
import sys

from .contracts.native_evidence_closure import (
    CATEGORIES, REQUEST_VERSION, SUPPLEMENTAL_VERSION, SCOPE,
    NativeEvidenceClosureReviewRequest, NativeEvidenceSupplementalReview,
)
from .contracts.segmented_evidence_qualification import SegmentedEvidenceQualificationRequest
from .contracts.train_market_evidence import TrainMarketSegmentRequest, TrainMarketExportRequest, SEGMENT_TYPE
from .contracts.mission_request import parse_rfc3339, format_rfc3339
from .decision_journal_store import JournalStore, JournalStoreError, check_separate_root
from .hashing import canonical_json_bytes, sha256_bytes

SCHEMA_VERSION = "blackpod.synthetic_native_evidence_closure_example.v1"
REVIEW_CLOCK = "2025-04-08T10:00:00Z"


def _authority():
    return {key: False for key in ("authorization_enabled", "capital_activation_enabled",
        "execution_enabled", "policy_changes_enabled")}


def _ref(path, raw):
    return {"path": path, "sha256": sha256_bytes(raw), "size_bytes": len(raw)}


def _retain(blobs, authored, path, value):
    raw = value if isinstance(value, bytes) else canonical_json_bytes(value)
    if path in authored and authored[path] != raw:
        raise ValueError("authored native closure evidence paths conflict")
    authored[path], blobs[sha256_bytes(raw)] = raw, raw
    return _ref(path, raw)


def request_for(anchor, *, review_id, candidate=None, supplemental=None, supersedes=None,
                recorded_at=REVIEW_CLOCK, data_cutoff_at=REVIEW_CLOCK):
    """Require explicit synthetic clocks rather than infer historical intent."""
    return NativeEvidenceClosureReviewRequest.from_mapping({
        "schema_version": REQUEST_VERSION, "review_id": review_id,
        "recorded_at": recorded_at, "data_cutoff_at": data_cutoff_at,
        "domain": "TRADING", "mode": "SHADOW_RESEARCH", "scope": SCOPE,
        "anchor_qualification_event_id": anchor.event_id,
        "candidate_qualification_event_id": None if candidate is None else candidate.event_id,
        "supplemental_review_evidence": supplemental, "supersedes_event_id": supersedes,
        "auto_trading_enabled": False, "authority": _authority()})


def source_material():
    """The exact old prefix plus separately authored native source comparisons."""
    from .segmented_evidence_qualification_example import example_material as old_material
    from .segmented_evidence_qualification_journal import qualification_material
    from .train_market_evidence_journal import segment_material, export_material
    original = old_material()
    events, retained = list(original["events"]), list(original["event_evidence"])
    blobs, authored = dict(original["blobs"]), {}
    cases = {row["case_id"]: row for row in original["cases"]}
    clean = cases["full-reversal"]

    def append(material):
        events.append(material["event"]); retained.append(material["evidence"])
        blobs.update({sha256_bytes(raw): raw for raw in material["evidence"].values()})

    # Reuse the already frozen reviewed toy policy, never manufacture approval.
    clean_request = SegmentedEvidenceQualificationRequest.from_mapping({
        **clean["request"].to_dict(), "qualification_id": "closure-fixture-clean-native-candidate",
        "recorded_at": "2025-04-06T14:00:00Z", "data_cutoff_at": "2025-04-06T13:00:00Z",
        "supersedes_event_id": clean["qualification_event"].event_id})
    clean_candidate = qualification_material(clean_request, events, blobs)
    append(clean_candidate)

    # NEW authored observation, distinct identity/raw bytes. All original
    # source records stay intact. This is a test input, not cleaned market data.
    plan = clean["capture"]["plan"]
    old_export = clean["capture"]["export_event"]
    old_segments = {event.source["segment_id"]: event for event in original["events"]
        if event.event_type == SEGMENT_TYPE
        and event.payload["request"]["capture_plan_event_id"] == clean["capture"]["plan_event"].event_id}
    wide_segment_ids = []
    for index, segment in enumerate(plan.segments):
        old = old_segments[segment["segment_id"]]
        body = json.loads(blobs[old.payload["request"]["pages"][0]["body_evidence"]["sha256"]])
        if index == 0:
            symbol = plan.universe[0] if hasattr(plan, "universe") else segment["query"]["symbols"].split(",")[0]
            body["quotes"][symbol][0]["ap"] = body["quotes"][symbol][0]["bp"] * 2
        prefix = "native-closure-fixture/wide/window-%04d" % index
        body_ref = _retain(blobs, authored, prefix + ".body.raw", body)
        receipt_ref = _retain(blobs, authored, prefix + ".receipt.json", {
            "schema_version": "blackpod.trading_evidence_capture.v1", "method": "GET",
            "url": "https://data.alpaca.markets/v2/stocks/quotes", "query": segment["query"],
            "captured_at": format_rfc3339(parse_rfc3339("2025-04-06T15:00:00Z", "authored clock") + timedelta(seconds=index)),
            "status": 200, "body_sha256": body_ref["sha256"], "size_bytes": body_ref["size_bytes"]})
        request = TrainMarketSegmentRequest.from_mapping({
            "schema_version": "blackpod.train_market_segment_export_request.v1",
            "export_id": "closure-fixture-wide-export", "capture_plan_event_id": clean["capture"]["plan_event"].event_id,
            "segment_id": segment["segment_id"], "pages": [{"body_evidence": body_ref, "receipt_evidence": receipt_ref}],
            "failure": None, "exported_at": "2025-04-06T16:00:00Z",
            "auto_trading_enabled": False, "authority": _authority()})
        material = segment_material(request, events, blobs); append(material)
        wide_segment_ids.append(material["event"].event_id)
    export_request = TrainMarketExportRequest.from_mapping({
        **old_export.payload["request"], "export_id": "closure-fixture-wide-export",
        "segment_event_ids": sorted(wide_segment_ids), "exported_at": "2025-04-06T16:00:00Z"})
    wide_export = export_material(export_request, events, blobs); append(wide_export)
    wide_request = SegmentedEvidenceQualificationRequest.from_mapping({
        **clean_request.to_dict(), "qualification_id": "closure-fixture-wide-native-candidate",
        "aggregate_export_event_id": wide_export["event"].event_id,
        "recorded_at": "2025-04-06T17:00:00Z", "data_cutoff_at": "2025-04-06T16:30:00Z",
        "supersedes_event_id": clean_candidate["event"].event_id})
    wide_candidate = qualification_material(wide_request, events, blobs); append(wide_candidate)
    deceptive_anchor = cases["missing-independent-coverage"]["qualification_event"]
    opaque = _retain(blobs, authored, "native-closure-fixture/unsupported-checklist-claim.raw",
        b'[{"claim":"ALL GATES COMPLETE","evidence":{"path":"do-not-follow.raw","sha256":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","size_bytes":1}}]')
    supplemental = NativeEvidenceSupplementalReview.from_mapping({
        "schema_version": SUPPLEMENTAL_VERSION, "supplemental_review_id": "closure-fixture-unauthenticated-checklist",
        "recorded_at": "2025-04-07T10:00:00Z", "anchor_qualification_event_id": deceptive_anchor.event_id,
        "candidate_qualification_event_id": None, "reviewer_id": "AUTHORED_SYNTHETIC_REVIEWER_NOT_AUTHENTICATED",
        "review_notes": "Deliberately misleading complete checklist; no original native evidence is replaced.",
        "categories": [{"category": category, "status": "SOURCE_REVIEW_RECORDED", "source_event_ids": [],
            "source_documents": [{"evidence": opaque, "source_url": "https://example.invalid/authored-review",
                "captured_at": "2025-04-07T09:00:00Z", "effective_coverage_start_at": None, "effective_coverage_end_at": None}],
            "notes": "Authored complete-checklist claim is unverified and cannot clear a native gate."} for category in CATEGORIES],
        "auto_trading_enabled": False, "authority": _authority()})
    supplemental_ref = _retain(blobs, authored, "native-closure-fixture/supplemental-review.v1.json", supplemental.to_bytes())
    specs = (
        ("deceptive-checklist", deceptive_anchor, None, supplemental_ref),
        ("native-candidate-comparison", cases["missing-assumptions"]["qualification_event"], clean_candidate["event"], None),
        ("new-wide-observation", clean["qualification_event"], wide_candidate["event"], None),
        ("partial-capture", cases["partial-reversal"]["qualification_event"], None, None),
    )
    return {"original": original, "events": tuple(events), "event_evidence": tuple(retained),
        "blobs": blobs, "authored_evidence": authored, "supplemental": supplemental,
        "clean_candidate": clean_candidate, "wide_candidate": wide_candidate,
        "cases": [{"case_id": label, "request": request_for(anchor, review_id="closure-fixture-" + label,
            candidate=candidate, supplemental=supplemental_ref)} for label, anchor, candidate, supplemental_ref in specs]}


def example_material():
    from .native_evidence_closure_journal import review_material
    material = source_material()
    events, retained, blobs = list(material["events"]), list(material["event_evidence"]), dict(material["blobs"])
    rows = []
    for case in material["cases"]:
        assessed = review_material(case["request"], events, blobs)
        events.append(assessed["event"]); retained.append(assessed["evidence"])
        blobs.update({sha256_bytes(raw): raw for raw in assessed["evidence"].values()})
        rows.append({**case, "review_event": assessed["event"], "result": assessed["result"]})
    return {**material, "events": tuple(events), "event_evidence": tuple(retained), "blobs": blobs, "cases": rows}


def prepare_example(destination):
    from .auto_trading_runtime import RuntimeLedger
    from .decision_journal_batch import append_journal_batch
    from .decision_journal_store import _check_existing_ancestors, _reject_source_storage
    from .desk_candidate_review_cli import _write
    output = Path(destination).absolute()
    package_root = Path(__file__).absolute().parents[2]
    for ancestor in (output, *output.parents):
        if any((ancestor / name).exists() for name in ("ledger.lock", "worker.lock")):
            raise ValueError("closure example must be separate from installed trading runtime storage")
        if ancestor.name == ".git":
            raise ValueError("closure example cannot write inside repository metadata")
        if (ancestor / ".git").exists():
            if ancestor == package_root and output.relative_to(ancestor).parts[:1] == ("output",):
                break
            raise ValueError("closure example cannot write inside repository source trees")
    _check_existing_ancestors(output); _reject_source_storage(output); RuntimeLedger(output)
    journal, inputs, evidence_root = output / "journal", output / "input", output / "evidence"
    check_separate_root(journal, inputs); check_separate_root(journal, evidence_root)
    material = example_material(); store = JournalStore(journal)
    existing = store.events() if journal.exists() else ()
    expected = material["events"]
    if len(existing) > len(expected) or [e.to_bytes() for e in existing] != [e.to_bytes() for e in expected[:len(existing)]]:
        raise ValueError("existing closure journal is not the exact immutable fixture prefix")
    suffix = [{"event": event, "evidence": evidence} for event, evidence in
        zip(expected[len(existing):], material["event_evidence"][len(existing):])]
    appended = append_journal_batch(store, suffix) if suffix else ()
    for path, raw in material["authored_evidence"].items():
        _write(evidence_root / path, raw, (journal,))
    rows = []
    for case in material["cases"]:
        label = case["case_id"]
        _write(inputs / (label + ".request.json"), case["request"].to_bytes(), (journal,))
        _write(output / "reports" / (label + ".result.json"), canonical_json_bytes(case["result"]), (journal,))
        rows.append({"case_id": label, "review_event_id": case["review_event"].event_id,
            "anchor_qualification_event_id": case["request"].anchor_qualification_event_id,
            "candidate_qualification_event_id": case["request"].candidate_qualification_event_id,
            "status": case["result"]["status"], "missing_prerequisites": case["result"]["missing_prerequisites"],
            "request_path": "input/" + label + ".request.json", "result_path": "reports/" + label + ".result.json"})
    summary = {"schema_version": SCHEMA_VERSION, "data_status": "SYNTHETIC_FIXTURE_ONLY",
        "original_source_events_preserved": len(material["original"]["events"]), "cases": rows,
        "events_written": sum(result.written for result in appended), "journal_verification": store.verify().to_dict(),
        "provider_calls": 0, "real_credential_files_read": 0, "model_inference_calls": 0, "orders_submitted": 0,
        "old_quote_bodies_changed": False, "new_wide_quote_explicitly_authored": True,
        "native_gate_override": False, "source_authentication_verified": False, "economic_hypothesis_supported": False,
        "uncertainty_computed": False, "execution_status": "NOT_EXECUTED", "realized_trade_pnl": None,
        "final_holdout_scored": False, "auto_trading_enabled": False}
    _write(output / "manifest.json", canonical_json_bytes({key: value for key, value in summary.items() if key != "events_written"}), ())
    return summary


def main(argv=None):
    parser = argparse.ArgumentParser(description="Run authored native closure review cases offline.")
    parser.add_argument("--output-root", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        print(json.dumps(prepare_example(args.output_root), sort_keys=True)); return 0
    except (OSError, ValueError, JournalStoreError) as exc:
        print(str(exc), file=sys.stderr); return 2


if __name__ == "__main__":
    raise SystemExit(main())
