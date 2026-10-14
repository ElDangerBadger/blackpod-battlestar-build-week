"""Authored independent evidence over a small, unchanged native source prefix."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from .contracts.mission_request import parse_rfc3339
from .decision_journal_store import JournalStore, JournalStoreError, check_separate_root
from .hashing import canonical_json_bytes, sha256_bytes

SCHEMA_VERSION = "blackpod.synthetic_independent_evidence_reconciliation_example.v1"
REVIEW_CLOCK = "2025-04-08T10:00:00Z"


def authority():
    return {key: False for key in ("authorization_enabled", "capital_activation_enabled", "execution_enabled", "policy_changes_enabled")}


def reference(path, raw):
    return {"path": path, "sha256": sha256_bytes(raw), "size_bytes": len(raw)}


def _retain(blobs, evidence, path, value):
    raw = value if isinstance(value, bytes) else value.to_bytes() if hasattr(value, "to_bytes") else canonical_json_bytes(value)
    if path in evidence and evidence[path] != raw: raise ValueError("fixture source paths conflict")
    evidence[path], blobs[sha256_bytes(raw)] = raw, raw
    return reference(path, raw)


def _append(events, evidence, blobs, material):
    events.append(material["event"]); evidence.append(material["evidence"])
    blobs.update({sha256_bytes(raw): raw for raw in material["evidence"].values()})


def source_material():
    """Preserve22 existing events and add one capture, qualification and v21 review.

    Native-shaped receipts are authored fixtures, never a claim of new provider
    capture. No historical prices, hypotheses, old policies or raw bodies change.
    """
    from .trading_evidence_qualification_example import example_material as original_material
    from .train_market_evidence import prepare_capture_plan
    from .train_market_evidence_journal import capture_plan_material, segment_material, export_material
    from .contracts.train_market_evidence import TrainMarketSegmentRequest, TrainMarketExportRequest
    from .contracts.segmented_evidence_qualification import SegmentedEvidenceBinding, SegmentedEvidenceQualificationRequest
    from .segmented_evidence_qualification_journal import binding_material, qualification_material
    from .contracts.native_evidence_closure import NativeEvidenceClosureReviewRequest
    from .native_evidence_closure_journal import review_material
    original = original_material()
    case = next(case for case in original["cases"] if case["case_id"] == "clean-declared-design")
    events, retained, blobs = list(original["events"]), list(original["event_evidence"]), dict(original["blobs"])
    authored = {}
    plan = prepare_capture_plan(events, blobs, capture_id="independent-fixture-train-capture",
        created_at="2025-04-03T10:00:00Z", base_plan_event_id=case["policy"].base_plan_event_id)
    registered = capture_plan_material(plan, events, blobs); _append(events, retained, blobs, registered)
    native_ref = original["original"]["costs"]["request"].quote_pages[0]["body_evidence"]
    native = json.loads(blobs[native_ref["sha256"]])
    segment_ids = []
    for index, segment in enumerate(plan.segments):
        lower, upper = (parse_rfc3339(segment["query"][key], "authored window") for key in ("start", "end"))
        body = {"quotes": {symbol: [row for row in native["quotes"][symbol] if lower <= parse_rfc3339(row["t"], "authored quote") <= upper]
            for symbol in segment["query"]["symbols"].split(",")}, "next_page_token": None}
        prefix = "independent-fixture/train/window-%04d" % index
        body_ref = _retain(blobs, authored, prefix + ".body.raw", body)
        receipt_ref = _retain(blobs, authored, prefix + ".receipt.json", {
            "schema_version": "blackpod.trading_evidence_capture.v1", "method": "GET", "url": "https://data.alpaca.markets/v2/stocks/quotes",
            "query": segment["query"], "captured_at": "2025-04-03T11:00:00Z", "status": 200,
            "body_sha256": body_ref["sha256"], "size_bytes": body_ref["size_bytes"]})
        request = TrainMarketSegmentRequest.from_mapping({"schema_version": "blackpod.train_market_segment_export_request.v1",
            "export_id": "independent-fixture-train-export", "capture_plan_event_id": registered["event"].event_id,
            "segment_id": segment["segment_id"], "pages": [{"body_evidence": body_ref, "receipt_evidence": receipt_ref}],
            "failure": None, "exported_at": "2025-04-04T10:00:00Z", "auto_trading_enabled": False, "authority": authority()})
        material = segment_material(request, events, blobs); _append(events, retained, blobs, material)
        segment_ids.append(material["event"].event_id)
    request = TrainMarketExportRequest.from_mapping({"schema_version": "blackpod.train_market_export_request.v1",
        "export_id": "independent-fixture-train-export", "capture_plan_event_id": registered["event"].event_id,
        "segment_event_ids": sorted(segment_ids), "exported_at": "2025-04-04T10:00:00Z",
        "continuity_event_id": None, "coverage_review_evidence": None, "capture_snapshot_evidence": None,
        "capture_checkpoint_evidence": [], "auto_trading_enabled": False, "authority": authority()})
    exported = export_material(request, events, blobs); _append(events, retained, blobs, exported)
    binding = SegmentedEvidenceBinding.from_mapping({"schema_version": "blackpod.segmented_evidence_qualification_binding.v1",
        "binding_id": "independent-fixture-binding", "recorded_at": "2025-04-05T10:00:00Z", "domain": "TRADING", "mode": "SHADOW_RESEARCH",
        "scope": "SEGMENTED_TRAIN_EVIDENCE_QUALIFICATION_ONLY", "qualification_policy_event_id": case["policy_event"].event_id,
        "capture_plan_event_id": registered["event"].event_id, "calibration_source": "VERIFIED_SEGMENTED_TRAIN_EXPORT_ONLY",
        "supersedes_binding_event_id": None, "auto_trading_enabled": False, "authority": authority()})
    bound = binding_material(binding, events, blobs); _append(events, retained, blobs, bound)
    request = SegmentedEvidenceQualificationRequest.from_mapping({"schema_version": "blackpod.segmented_evidence_qualification_request.v1",
        "qualification_id": "independent-fixture-native-qualification", "binding_event_id": bound["event"].event_id,
        "aggregate_export_event_id": exported["event"].event_id, "recorded_at": "2025-04-05T11:00:00Z", "data_cutoff_at": "2025-04-05T10:30:00Z",
        "supersedes_event_id": None, "auto_trading_enabled": False, "authority": authority()})
    qualified = qualification_material(request, events, blobs); _append(events, retained, blobs, qualified)
    request = NativeEvidenceClosureReviewRequest.from_mapping({"schema_version": "blackpod.native_evidence_closure_review_request.v1",
        "review_id": "independent-fixture-native-review", "recorded_at": "2025-04-06T12:00:00Z", "data_cutoff_at": "2025-04-06T11:00:00Z",
        "domain": "TRADING", "mode": "SHADOW_RESEARCH", "scope": "NATIVE_EVIDENCE_CLOSURE_REVIEW_ONLY",
        "anchor_qualification_event_id": qualified["event"].event_id, "candidate_qualification_event_id": None,
        "supplemental_review_evidence": None, "supersedes_event_id": None, "auto_trading_enabled": False, "authority": authority()})
    reviewed = review_material(request, events, blobs); _append(events, retained, blobs, reviewed)
    return {"original": original, "events": tuple(events), "event_evidence": tuple(retained), "blobs": blobs,
        "authored_evidence": authored, "policy": case["policy"], "capture_plan": plan,
        "capture_plan_event": registered["event"], "aggregate_export_event": exported["event"],
        "anchor_qualification_event": qualified["event"], "anchor_review_event": reviewed["event"]}


def example_material():
    """Three authored packets, all descriptive and incapable of upgrading gates."""
    from copy import deepcopy
    from zoneinfo import ZoneInfo
    from .contracts.trading_research import TradingResearchDataset
    from .contracts.effective_date_reconciliation import IndependentActionInventory, EffectiveDateReconciliationRequest, ACTION_TYPES
    from .contracts.historical_feed_cost_applicability import HistoricalFeedCostApplicabilityPacket, CATEGORIES
    from .contracts.evidence_reconciliation import EvidenceReconciliationRequest
    from .evidence_reconciliation import build_source_context
    from .evidence_reconciliation_journal import review_material
    source = source_material()
    events, retained, blobs = list(source["events"]), list(source["event_evidence"]), dict(source["blobs"])
    authored = dict(source["authored_evidence"])
    dataset = TradingResearchDataset.from_bytes(blobs[source["policy"].dataset_evidence["sha256"]])
    dates = [parse_rfc3339(row["open_at"], "fixture session").astimezone(ZoneInfo("America/New_York")).date().isoformat() for row in dataset.sessions]
    native = next(event for event in events if event.event_id == source["policy"].continuity_event_id)
    native_ref = next(ref for ref in native.evidence if ref["path"] == "continuity-intake/export.v1.json")
    rows = []
    for label, count, partial, evaluation_mode in (
        ("empty-observations", 0, False, "SHADOW_RESEARCH"),
        ("partial-missing-mismatched-feed", 1, True, "SHADOW_RESEARCH"),
        ("ambiguous-and-account-conflict", 2, False, "PAPER_SIMULATION"),
    ):
        prefix = "independent-fixture/" + label
        actions = [{"source_action_id": "authored-action-%03d" % index, "native_type": "cash_dividends",
            "affected_symbols": [dataset.universe[0]], "effective_date": dates[5], "record_date": None, "payable_date": None,
            "status": "EFFECTIVE", "cusip": None, "amount_lexemes": {"dividend": "0.5", "short_term_capital_gain": None, "long_term_capital_gain": None},
            "replaces_source_action_id": None} for index in range(count)]
        body_ref = _retain(blobs, authored, prefix + "/actions.raw", {"schema_version": "blackpod.authored_effective_date_actions.v1", "label": "AUTHORED_UNVERIFIED", "actions": actions})
        inventory = IndependentActionInventory.from_mapping({"schema_version": "blackpod.independent_action_inventory.v1",
            "inventory_id": "authored-" + label + "-inventory", "recorded_at": "2025-04-07T10:00:00Z",
            "profile": "AUTHORED_EFFECTIVE_DATE_ACTIONS_JSON_V1", "evidence_scope": "SYNTHETIC_FIXTURE_ONLY",
            "publisher": "AUTHORED_SYNTHETIC_FIXTURE", "source_url": "https://example.invalid/" + label,
            "captured_at": "2025-04-07T09:00:00Z", "body_evidence": body_ref,
            "declared_coverage": {"symbols": dataset.universe[:1] if partial else dataset.universe,
                "action_types": ["cash_dividends"] if partial else list(ACTION_TYPES), "effective_start": dates[0],
                "effective_end": dates[5] if partial else dates[-1], "completeness": "PARTIAL" if partial else "DECLARED_COMPLETE"},
            "supporting_evidence": [], "auto_trading_enabled": False, "authority": authority()})
        inventory_ref = _retain(blobs, authored, prefix + "/inventory.v1.json", inventory)
        effective = EffectiveDateReconciliationRequest.from_mapping({"schema_version": "blackpod.effective_date_reconciliation_request.v1",
            "reconciliation_id": "authored-" + label + "-effective", "recorded_at": REVIEW_CLOCK, "data_cutoff_at": REVIEW_CLOCK,
            "domain": "TRADING", "mode": "SHADOW_RESEARCH", "scope": "RETAINED_INDEPENDENT_EFFECTIVE_DATE_RECONCILIATION_ONLY",
            "dataset_evidence": source["policy"].dataset_evidence, "native_continuity_export_evidence": native_ref,
            "independent_inventories": [inventory_ref], "auto_trading_enabled": False, "authority": authority()})
        effective_ref = _retain(blobs, authored, prefix + "/effective-request.v1.json", effective)
        context_material = build_source_context(source["anchor_review_event"].event_id, events, blobs,
            recorded_at=REVIEW_CLOCK, declared_evaluation_mode=evaluation_mode, account_profile_evidence=None)
        context = context_material["context"]
        context_ref = _retain(blobs, authored, prefix + "/context.v1.json", context)
        document_ref = _retain(blobs, authored, prefix + "/review-note.raw",
            b'[{"label":"AUTHORED_UNVERIFIED","claim":"No rates, units, slippage or capacity are measured","evidence":{"path":"never-follow-this.raw"}}]')
        document = {"document_id": "authored-note", "evidence": document_ref,
            "source_url": "https://example.invalid/authored-applicability", "publisher": "AUTHORED_SYNTHETIC_FIXTURE",
            "document_version": None, "published_at": None, "observed_at": "2025-04-07T10:00:00Z", "document_kind": "AUTHORED_REVIEW_NOTE"}
        scope = {key: deepcopy(getattr(context, key)) for key in ("provider", "endpoint", "feed", "universe", "currency", "collection_mode", "declared_evaluation_mode", "account_evidence", "market_event_interval", "delivery_interval")}
        scope["effective_time_basis"] = "BOTH"
        categories = []
        for category in CATEGORIES:
            assertion_scope = deepcopy(scope)
            if partial and category == "FEED_IDENTITY": assertion_scope["feed"] = "sip"
            if partial and category == "QUOTE_SIZE_UNITS":
                assertion_scope.update(effective_time_basis="DELIVERY_TIME", market_event_interval=None)
            assertion = {"assertion_id": label + "-" + category.lower(), "document_id": "authored-note",
                "claim_key": "authored-" + category.lower(), "claim_value": "Authored scope declaration only",
                "numeric_assertion": None, "fee_formula_shape": "UNRESOLVED", "scope": assertion_scope}
            assertions = [assertion]
            if count == 2 and category == "FEE_SCHEDULE":
                assertion.update(claim_value="first incompatible source claim", numeric_assertion={"value": "0.1", "unit": "authored-fee-unit"}, fee_formula_shape="CONSTANT_BPS_PLUS_PER_FILL")
                other = deepcopy(assertion)
                other.update(assertion_id=assertion["assertion_id"] + "-conflicting", claim_value="second incompatible source claim",
                    numeric_assertion={"value": "0.2", "unit": "authored-fee-unit"}, fee_formula_shape="SIDE_PER_SHARE_CAP_ROUNDING")
                assertions.append(other)
            categories.append({"category": category, "assertions": assertions})
        packet = HistoricalFeedCostApplicabilityPacket.from_mapping({"schema_version": "blackpod.historical_feed_cost_applicability_packet.v1",
            "packet_id": "authored-" + label + "-applicability", "recorded_at": REVIEW_CLOCK, "data_cutoff_at": REVIEW_CLOCK,
            "context_evidence": context_ref, "reviewer_id": "AUTHORED_UNAUTHENTICATED_REVIEWER",
            "review_notes": "Explicit synthetic evidence; no historical fee, size conversion, slippage or capacity established.",
            "source_documents": [document], "categories": categories, "auto_trading_enabled": False, "authority": authority()})
        packet_ref = _retain(blobs, authored, prefix + "/applicability-packet.v1.json", packet)
        request = EvidenceReconciliationRequest.from_mapping({"schema_version": "blackpod.independent_evidence_reconciliation_request.v1",
            "review_id": "authored-" + label + "-combined-review", "recorded_at": REVIEW_CLOCK, "data_cutoff_at": REVIEW_CLOCK,
            "domain": "TRADING", "mode": "SHADOW_RESEARCH", "scope": "INDEPENDENT_EVIDENCE_RECONCILIATION_ONLY",
            "anchor_review_event_id": source["anchor_review_event"].event_id, "effective_date_request_evidence": effective_ref,
            "applicability_packet_evidence": packet_ref, "declared_evaluation_mode": evaluation_mode,
            "account_profile_evidence": None, "supersedes_event_id": None, "auto_trading_enabled": False, "authority": authority()})
        material = review_material(request, events, blobs); _append(events, retained, blobs, material)
        rows.append({"case_id": label, "request": request, "context": context, "effective": effective, "inventory": inventory,
            "packet": packet, "review_event": material["event"], "result": material["result"]})
    return {**source, "events": tuple(events), "event_evidence": tuple(retained), "blobs": blobs, "authored_evidence": authored, "cases": rows}


def _destination(path):
    from .auto_trading_runtime import RuntimeLedger
    from .decision_journal_store import _check_existing_ancestors, _reject_source_storage
    output = Path(path).absolute(); package = Path(__file__).absolute().parents[2]
    for ancestor in (output, *output.parents):
        if any((ancestor / name).exists() for name in ("ledger.lock", "worker.lock")):
            raise ValueError("example must be separate from installed trading runtime storage")
        if ancestor.name == ".git": raise ValueError("example cannot write repository metadata")
        if (ancestor / ".git").exists():
            if ancestor == package and output.relative_to(ancestor).parts[:1] == ("output",): break
            raise ValueError("example cannot write repository source trees")
    _check_existing_ancestors(output); _reject_source_storage(output); RuntimeLedger(output)
    return output


def prepare_example(destination):
    from .decision_journal_batch import append_journal_batch
    from .desk_candidate_review_cli import _write
    output = _destination(destination)
    journal, inputs, evidence_root = output / "journal", output / "input", output / "evidence"
    check_separate_root(journal, inputs); check_separate_root(journal, evidence_root)
    material = example_material(); store = JournalStore(journal)
    previous = store.events() if journal.exists() else ()
    expected = material["events"]
    if len(previous) > len(expected) or [event.to_bytes() for event in previous] != [event.to_bytes() for event in expected[:len(previous)]]:
        raise ValueError("existing journal is not the exact immutable authored prefix")
    suffix = [{"event": event, "evidence": evidence} for event, evidence in zip(expected[len(previous):], material["event_evidence"][len(previous):])]
    written = append_journal_batch(store, suffix) if suffix else ()
    for path, raw in material["authored_evidence"].items(): _write(evidence_root / path, raw, (journal,))
    rows = []
    for case in material["cases"]:
        label = case["case_id"]
        _write(inputs / (label + ".request.json"), case["request"].to_bytes(), (journal,))
        _write(output / "reports" / (label + ".result.json"), canonical_json_bytes(case["result"]), (journal,))
        _write(inputs / (label + ".prepare-inputs.json"), canonical_json_bytes({key: getattr(case["request"], key) for key in
            ("effective_date_request_evidence", "applicability_packet_evidence", "account_profile_evidence")}), (journal,))
        rows.append({"case_id": label, "request_path": "input/" + label + ".request.json", "result_path": "reports/" + label + ".result.json",
            "review_event_id": case["review_event"].event_id, "status": case["result"]["status"]})
    summary = {"schema_version": SCHEMA_VERSION, "data_status": "SYNTHETIC_FIXTURE_ONLY", "cases": rows,
        "original_events_preserved": len(material["original"]["events"]), "source_prefix_events": 39,
        "events_written": sum(row.written for row in written), "journal_verification": store.verify().to_dict(),
        "provider_calls": 0, "real_credential_files_read": 0, "orders_submitted": 0, "model_inference_calls": 0,
        "native_gate_override": False, "source_authentication_verified": False, "economic_hypothesis_supported": False,
        "execution_status": "NOT_EXECUTED", "realized_trade_pnl": None, "auto_trading_enabled": False}
    _write(output / "manifest.json", canonical_json_bytes({key: value for key, value in summary.items() if key != "events_written"}), ())
    return summary


def main(argv=None):
    parser = argparse.ArgumentParser(description="Authored independent evidence reconciliation, offline and auto-trading OFF")
    parser.add_argument("--output-root", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        print(json.dumps(prepare_example(args.output_root), sort_keys=True)); return 0
    except (OSError, ValueError, JournalStoreError) as exc:
        print(str(exc), file=sys.stderr); return 2


if __name__ == "__main__": raise SystemExit(main())
