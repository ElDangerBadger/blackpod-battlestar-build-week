"""One immutable authored v24 diagnostic after the unchanged v23 source prefix."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from .contracts.reconciled_shadow_qualification import ReconciledShadowQualificationRequest, REQUEST_CONSTANTS
from .decision_journal_store import JournalStore, JournalStoreError, check_separate_root
from .desk_candidate_review_cli import _write
from .evidence_reconciliation_example import _destination, _append, authority
from .hashing import canonical_json_bytes

SCHEMA_VERSION = "blackpod.synthetic_reconciled_shadow_qualification_example.v1"


def example_material():
    from .reconciled_action_intake_example import example_material as source_material
    from .reconciled_action_journal import RESULT_PATH as INTAKE_RESULT_PATH
    from .reconciled_shadow_qualification_journal import qualification_material
    original = source_material()
    events, evidence, blobs = list(original["events"]), list(original["event_evidence"]), dict(original["blobs"])
    intake = original["intake_event"]
    result_ref = next(ref for ref in intake.evidence if ref["path"] == INTAKE_RESULT_PATH)
    request = ReconciledShadowQualificationRequest.from_mapping({**REQUEST_CONSTANTS,
        "qualification_id": "authored-reconciled-shadow-qualification", "recorded_at": "2025-04-11T12:00:00Z",
        "data_cutoff_at": "2025-04-11T11:00:00Z", "intake_event_id": intake.event_id,
        "intake_result_evidence": result_ref, "supersedes_event_id": None,
        "auto_trading_enabled": False, "authority": authority()})
    material = qualification_material(request, events, blobs)
    _append(events, evidence, blobs, material)
    return {"original": original, "source_count": 42, "events": tuple(events), "event_evidence": tuple(evidence),
        "blobs": blobs, "request": request, "event": material["event"], "result": material["result"],
        "intake_event": intake, "intake_result_evidence": result_ref}


def prepare_example(destination):
    from .decision_journal_batch import append_journal_batch
    output = _destination(destination)
    journal, inputs = output / "journal", output / "input"
    check_separate_root(journal, inputs)
    material = example_material(); expected = material["events"]; store = JournalStore(journal)
    previous = store.events() if journal.exists() else ()
    if len(previous) > len(expected) or [event.to_bytes() for event in previous] != [event.to_bytes() for event in expected[:len(previous)]]:
        raise ValueError("existing journal is not the exact immutable authored source prefix")
    suffix = [{"event": event, "evidence": evidence} for event, evidence in
        zip(expected[len(previous):], material["event_evidence"][len(previous):])]
    written = append_journal_batch(store, suffix) if suffix else ()
    _write(inputs / "request.v1.json", material["request"].to_bytes(), (journal,))
    _write(inputs / "prepare-inputs.json", canonical_json_bytes({key: getattr(material["request"], key) for key in
        ("intake_event_id", "intake_result_evidence", "supersedes_event_id")}), (journal,))
    _write(output / "reports" / "qualification.v1.json", canonical_json_bytes(material["result"]), (journal,))
    summary = {"schema_version": SCHEMA_VERSION, "data_status": "SYNTHETIC_FIXTURE_ONLY", "source_prefix_events": 42,
        "original_events_preserved": 22, "events_written": sum(item.written for item in written),
        "qualification_event_id": material["event"].event_id, "intake_event_id": material["intake_event"].event_id,
        "status": material["result"]["status"], "journal_verification": store.verify().to_dict(),
        "provider_api_calls": 0, "real_credential_files_read": 0, "orders_submitted": 0, "model_inference_calls": 0,
        "auto_trading_enabled": False, "execution_status": "NOT_EXECUTED", "realized_trade_pnl": None}
    _write(output / "manifest.json", canonical_json_bytes({key: value for key, value in summary.items() if key != "events_written"}), ())
    return summary


def main(argv=None):
    parser = argparse.ArgumentParser(description="Authored reconciled-overlay qualification, offline and auto-trading OFF")
    parser.add_argument("--output-root", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        print(json.dumps(prepare_example(args.output_root), sort_keys=True)); return 0
    except (OSError, ValueError, JournalStoreError) as exc:
        print(str(exc), file=sys.stderr); return 2


if __name__ == "__main__": raise SystemExit(main())
