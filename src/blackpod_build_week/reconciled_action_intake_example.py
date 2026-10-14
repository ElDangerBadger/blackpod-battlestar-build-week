"""One small frozen-policy intake with explicitly authored issuer observations."""
from __future__ import annotations

import argparse
from datetime import timedelta
import json
from pathlib import Path
import sys
from zoneinfo import ZoneInfo

from .contracts.effective_date_reconciliation import IndependentActionInventory
from .contracts.mission_request import parse_rfc3339
from .contracts.reconciled_action_intake import ReconciledActionIntakeRequest, REQUEST_CONSTANTS, AUTHORITY
from .contracts.trading_research import TradingResearchDataset
from .decision_journal_store import JournalStore, JournalStoreError, check_separate_root
from .desk_candidate_review_cli import _write
from .evidence_reconciliation_example import _destination, _retain, _append
from .hashing import canonical_json_bytes

SCHEMA_VERSION = "blackpod.synthetic_reconciled_action_intake_example.v1"


def example_material():
    """Preserve the first40 v22 events; append one policy and one candidate."""
    from .evidence_reconciliation_example import example_material as original_material
    from .reconciled_action_journal import prepare_policy, source_context, intake_material, POLICY_PATH
    original = original_material()
    events, evidence = list(original["events"][:40]), list(original["event_evidence"][:40])
    blobs = dict(original["blobs"])
    anchor = events[-1]
    context = source_context(anchor.event_id, events, blobs)
    dataset = TradingResearchDataset.from_bytes(blobs[context["dataset_evidence"]["sha256"]])
    dates = [parse_rfc3339(session["open_at"], "authored session").astimezone(ZoneInfo("America/New_York")).date() for session in dataset.sessions]
    first, second = dataset.universe
    actions = []
    for identifier, symbol, date, status, amount in (
        ("issuer-only", first, dates[5], "EFFECTIVE", "0.5"),
        ("duplicate-a", first, dates[10], "EFFECTIVE", "0.6"),
        ("duplicate-b", first, dates[10], "EFFECTIVE", "0.7"),
        ("unknown-date", second, None, "UNKNOWN", None),
        ("scheduled", second, dates[15], "SCHEDULED", "0.8"),
        ("cancelled", second, dates[16], "CANCELLED", "0.9"),
        ("before-span", first, dates[0] - timedelta(days=1), "LISTED_STATUS_UNSPECIFIED", "0.4"),
        ("after-span", second, dates[-1] + timedelta(days=1), "LISTED_STATUS_UNSPECIFIED", "0.3"),
    ):
        # The authored profile supports source statuses without implying payment.
        authored_status = "UNKNOWN" if status == "LISTED_STATUS_UNSPECIFIED" else status
        actions.append({"source_action_id": "authored-" + identifier, "native_type": "cash_dividends",
            "affected_symbols": [symbol], "effective_date": None if date is None else date.isoformat(),
            "record_date": None, "payable_date": None, "status": authored_status, "cusip": None,
            "amount_lexemes": {"dividend": amount, "short_term_capital_gain": None, "long_term_capital_gain": None},
            "replaces_source_action_id": None})
    authored = {}
    body_ref = _retain(blobs, authored, "reconciled-fixture/issuer-actions.raw", {
        "schema_version": "blackpod.authored_effective_date_actions.v1", "label": "AUTHORED_UNVERIFIED", "actions": actions})
    inventory = IndependentActionInventory.from_mapping({"schema_version": "blackpod.independent_action_inventory.v1",
        "inventory_id": "authored-reconciled-issuer-inventory", "recorded_at": "2025-04-08T12:00:00Z",
        "profile": "AUTHORED_EFFECTIVE_DATE_ACTIONS_JSON_V1", "evidence_scope": "SYNTHETIC_FIXTURE_ONLY",
        "publisher": "AUTHORED_SYNTHETIC_FIXTURE", "source_url": "https://example.invalid/reconciled-actions",
        "captured_at": "2025-04-08T11:00:00Z", "body_evidence": body_ref,
        "declared_coverage": {"symbols": dataset.universe, "action_types": ["cash_dividends"],
            "effective_start": dates[0].isoformat(), "effective_end": dates[-1].isoformat(), "completeness": "PARTIAL"},
        "supporting_evidence": [], "auto_trading_enabled": False, "authority": dict(AUTHORITY)})
    inventory_ref = _retain(blobs, authored, "reconciled-fixture/issuer-inventory.v1.json", inventory)
    prepared = prepare_policy(anchor.event_id, "authored-frozen-reconciled-policy", "2025-04-09T10:00:00Z",
        [*context["independent_inventories"], inventory_ref], events, blobs)
    _append(events, evidence, blobs, prepared)
    policy_ref = next(ref for ref in prepared["event"].evidence if ref["path"] == POLICY_PATH)
    request = ReconciledActionIntakeRequest.from_mapping({**REQUEST_CONSTANTS,
        "intake_id": "authored-reconciled-intake", "recorded_at": "2025-04-10T12:00:00Z", "data_cutoff_at": "2025-04-10T11:00:00Z",
        "policy_event_id": prepared["event"].event_id, "policy_evidence": policy_ref, "supersedes_event_id": None,
        "auto_trading_enabled": False, "authority": dict(AUTHORITY)})
    intake = intake_material(request, events, blobs)
    _append(events, evidence, blobs, intake)
    return {"original": original, "source_count": 40, "events": tuple(events), "event_evidence": tuple(evidence), "blobs": blobs,
        "authored_evidence": authored, "anchor_event": anchor, "context": context, "inventory": inventory,
        "policy": prepared["policy"], "policy_event": prepared["event"], "request": request,
        "intake_event": intake["event"], "result": intake["result"]}


def prepare_example(destination):
    from .decision_journal_batch import append_journal_batch
    output = _destination(destination)
    journal, inputs, evidence_root = output / "journal", output / "input", output / "evidence"
    check_separate_root(journal, inputs); check_separate_root(journal, evidence_root)
    material = example_material(); expected = material["events"]; store = JournalStore(journal)
    previous = store.events() if journal.exists() else ()
    if len(previous) > len(expected) or [event.to_bytes() for event in previous] != [event.to_bytes() for event in expected[:len(previous)]]:
        raise ValueError("existing journal is not the exact immutable authored source prefix")
    suffix = [{"event": event, "evidence": evidence} for event, evidence in
        zip(expected[len(previous):], material["event_evidence"][len(previous):])]
    written = append_journal_batch(store, suffix) if suffix else ()
    for path, raw in material["authored_evidence"].items(): _write(evidence_root / path, raw, (journal,))
    _write(inputs / "policy.v1.json", material["policy"].to_bytes(), (journal,))
    _write(inputs / "request.v1.json", material["request"].to_bytes(), (journal,))
    _write(inputs / "policy-prepare-inputs.json", canonical_json_bytes({"independent_inventories": material["policy"].independent_inventories}), (journal,))
    _write(inputs / "intake-prepare-inputs.json", canonical_json_bytes({key: getattr(material["request"], key) for key in
        ("policy_event_id", "policy_evidence", "supersedes_event_id")}), (journal,))
    _write(output / "reports" / "intake.v1.json", canonical_json_bytes(material["result"]), (journal,))
    summary = {"schema_version": SCHEMA_VERSION, "data_status": "SYNTHETIC_FIXTURE_ONLY", "source_prefix_events": material["source_count"],
        "original_events_preserved": 22, "events_written": sum(item.written for item in written),
        "policy_event_id": material["policy_event"].event_id, "intake_event_id": material["intake_event"].event_id,
        "anchor_event_id": material["anchor_event"].event_id, "status": material["result"]["status"],
        "journal_verification": store.verify().to_dict(), "provider_api_calls": 0, "real_credential_files_read": 0,
        "orders_submitted": 0, "model_inference_calls": 0, "auto_trading_enabled": False,
        "old_masks_modified": False, "legacy_source_compatible": False, "economic_hypothesis_supported": False,
        "execution_status": "NOT_EXECUTED", "realized_trade_pnl": None}
    _write(output / "manifest.json", canonical_json_bytes({key: value for key, value in summary.items() if key != "events_written"}), ())
    return summary


def main(argv=None):
    parser = argparse.ArgumentParser(description="Authored reconciled-action example, offline and auto-trading OFF")
    parser.add_argument("--output-root", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        print(json.dumps(prepare_example(args.output_root), sort_keys=True)); return 0
    except (OSError, ValueError, JournalStoreError) as exc:
        print(str(exc), file=sys.stderr); return 2


if __name__ == "__main__": raise SystemExit(main())
