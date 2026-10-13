"""Authored evidence-qualification fixtures over unchanged frozen research.

No provider request occurs. New TRAIN-only bodies are explicitly authored
subsets of the old synthetic quote body, never claimed as new captures. Prices,
hypotheses, original receipts, v16 calculations and all holdout values remain
unchanged. Declared reviews authorize no operational action.
"""
from __future__ import annotations

import argparse
from datetime import timedelta
import json
from pathlib import Path
import sys

from .contracts.mission_request import format_rfc3339, parse_rfc3339
from .contracts.trading_evidence_qualification import (
    TradingEvidenceQualificationRequest, TradingTrainingAssumptions,
)
from .decision_journal_store import JournalStore, JournalStoreError, check_separate_root
from .hashing import canonical_json_bytes, sha256_bytes

SCHEMA_VERSION = "blackpod.synthetic_trading_evidence_qualification_example.v1"
POLICY_RECORDED_AT = "2025-04-02T10:00:00Z"
ASSESSMENT_RECORDED_AT = "2025-04-02T11:00:00Z"
DATA_CUTOFF_AT = "2025-04-02T10:30:00Z"


def authority():
    return {key: False for key in (
        "authorization_enabled", "capital_activation_enabled",
        "execution_enabled", "policy_changes_enabled")}


def ref(path, raw):
    return {"path": path, "sha256": sha256_bytes(raw), "size_bytes": len(raw)}


def _retain(evidence, path, value):
    raw = value if isinstance(value, bytes) else value.to_bytes() if hasattr(value, "to_bytes") else canonical_json_bytes(value)
    if path in evidence and evidence[path] != raw:
        raise ValueError("qualification example evidence paths bind conflicting bytes")
    evidence[path] = raw
    return ref(path, raw)


def fixture_uncertainty_protocol():
    """A proposed toy future procedure; no resampling or inference is run."""
    return {"method_version": "blackpod.paired_session_uncertainty_plan.v1",
        "method": "MOVING_BLOCK_BOOTSTRAP_PAIRED_SESSION_NET_CASHFLOWS",
        "metric": "NET_EXCESS_OVER_CASH_AND_MATCHED_CONTROL",
        "resampling_unit": "RETURNED_SESSION_BLOCK_ALL_SYMBOLS_PAIRED",
        "block_length_sessions": 2, "replications": 100, "seed": 7,
        "confidence_level": "0.95", "minimum_evaluation_sessions": 8,
        "minimum_development_folds": 1, "minimum_supported_fold_fraction": "1",
        "support_rule": "POSITIVE_LOWER_BOUND_FOR_BOTH_BENCHMARKS_AT_ALL_STRESSES_AND_DECLARED_STABILITY",
        "cost_stress_multipliers": ["1", "2", "4"], "holdout_scoring": "WITHHELD",
        "parameter_search_allowed": False,
        "multiple_trials_policy": "ALL_REGISTERED_TRIALS_DISCLOSED_NO_WINNER_SELECTION"}


toy_protocol = fixture_uncertainty_protocol


def fixture_material():
    """Prepare four new designs over the unchanged fourteen-event fixture."""
    from .trading_evidence_qualification import prepare_policy
    from .trading_shadow_review_example import example_material as frozen_material
    original = frozen_material()
    evidence = {}
    blobs = dict(original["blobs"])
    for retained in original["event_evidence"]:
        blobs.update({sha256_bytes(raw): raw for raw in retained.values()})
    rows = {item["hypothesis"].hypothesis_id: item for item in original["studies"]}
    row = rows["previous-session-reversal-v1"]
    continuation = rows["five-session-continuation-v1"]
    plan, dataset = row["plan"], original["dataset"]
    support_ref = _retain(evidence, "qualification-example/design-origin.raw",
        b"Entirely authored qualification design: reuse frozen fictional prices and hypotheses. Review is a local toy declaration. Training-only spreads, 5 bps slippage, 0 bps proportional fee, USD 0.10 per fill, 1 percent daily-volume participation and a proposed bootstrap design are not authenticated market evidence, validated statistical choices, real costs or execution approval. No provider was contacted.\n")
    assumption_origin = _retain(evidence, "qualification-example/training-assumptions-origin.raw",
        b"Authored fixture assumptions copied transparently from the old toy declarations: slippage 5 bps, fee 0 bps, USD 0.10 per fill and daily-volume participation 0.01. They are not estimated from strategy returns, observed fills or broker fee schedules. Opening depth and actual executable capacity remain unverified.\n")
    def assumptions_for(source, label):
        base_refs = [reference for reference in source["plan_event"].evidence
                     if reference["sha256"] == sha256_bytes(source["plan"].to_bytes())]
        if len(base_refs) != 1:
            raise ValueError("qualification fixture needs the exact original plan reference")
        document = TradingTrainingAssumptions.from_mapping({
            "schema_version": "blackpod.trading_training_assumptions.v1",
            "assumptions_id": "synthetic-qualification-training-assumptions-" + label,
            "recorded_at": "2025-04-02T09:00:00Z",
            "base_plan_evidence": base_refs[0], "dataset_evidence": source["plan"].dataset_evidence,
            "evidence_scope": "SYNTHETIC_FIXTURE_ONLY", "status": "REVIEWED_FOR_SHADOW_QUALIFICATION",
            "parameters": {"slippage_bps": "5", "fee_bps": "0", "fee_per_fill": "0.10"},
            "capacity": {"max_daily_volume_participation_fraction": "0.01"},
            "origin_evidence": [assumption_origin], "reviewer_id": "synthetic-fixture-author",
            "review_notes": "Explicit toy cost/capacity declarations, not observed executions or authenticated human approval.",
            "auto_trading_enabled": False, "authority": authority(),
        })
        reference = _retain(evidence, "qualification-example/training-assumptions-" + label + ".v1.json", document)
        return document, reference
    assumptions, assumptions_ref = assumptions_for(row, "reversal")
    continuation_assumptions, continuation_ref = assumptions_for(continuation, "continuation")
    old_page = original["costs"]["request"].quote_pages[0]
    old_body = json.loads(blobs[old_page["body_evidence"]["sha256"]])
    old_receipt = json.loads(blobs[old_page["receipt_evidence"]["sha256"]])
    chains = []
    for fold in plan.protocol["folds"]:
        first, last = (dataset.sessions[fold["train"][key]] for key in ("start_index", "end_index"))
        start = first["open_at"]
        end = format_rfc3339(parse_rfc3339(last["open_at"], "last TRAIN open") + timedelta(seconds=60))
        source = {"quotes": {symbol: [quote for quote in old_body["quotes"][symbol]
            if parse_rfc3339(start, "TRAIN start") <= parse_rfc3339(quote["t"], "authored quote timestamp") <= parse_rfc3339(end, "TRAIN end")]
            for symbol in dataset.universe}, "next_page_token": None}
        path = "qualification-example/training-" + fold["fold_id"]
        body_ref = _retain(evidence, path + ".raw", source)
        receipt = {**old_receipt,
            "query": {**old_receipt["query"], "start": start, "end": end},
            "body_sha256": body_ref["sha256"], "size_bytes": body_ref["size_bytes"]}
        receipt_ref = _retain(evidence, path + ".receipt.json", receipt)
        chains.append({"fold_id": fold["fold_id"],
            "pages": [{"body_evidence": body_ref, "receipt_evidence": receipt_ref}]})
    blobs.update({sha256_bytes(raw): raw for raw in evidence.values()})
    def common(source):
        return {"recorded_at": POLICY_RECORDED_AT,
            "base_plan_event_id": source["plan_event"].event_id,
            "continuity_event_id": original["intake_events"][0].event_id,
            "cost_event_id": original["intake_events"][1].event_id,
            "risk_review_event_id": source["risk_event"].event_id,
            "supporting_evidence": [support_ref], "reviewer_id": "synthetic-fixture-author",
            "review_notes": "Authored fixture research qualification only. No historical preregistration, economic support, real cost claim or operational authority."}
    clean = prepare_policy(original["events"], blobs,
        policy_id="synthetic-clean-evidence-qualification-policy", **common(row),
        training_quote_chains=chains, training_cost_assumptions_evidence=assumptions_ref,
        uncertainty_protocol=fixture_uncertainty_protocol(), status="REVIEWED_FOR_SHADOW_QUALIFICATION")
    insufficient = prepare_policy(original["events"], blobs,
        policy_id="synthetic-insufficient-joint-sample-policy", **common(continuation),
        training_quote_chains=chains, training_cost_assumptions_evidence=continuation_ref,
        uncertainty_protocol=fixture_uncertainty_protocol(), status="REVIEWED_FOR_SHADOW_QUALIFICATION")
    proposed = prepare_policy(original["events"], blobs,
        policy_id="synthetic-proposed-evidence-qualification-policy", **common(continuation))
    forbidden = prepare_policy(original["events"], blobs,
        policy_id="synthetic-forbidden-holdout-evidence-policy", **common(row),
        training_quote_chains=[{"fold_id": plan.protocol["folds"][0]["fold_id"],
            "pages": [old_page]}], training_cost_assumptions_evidence=assumptions_ref,
        uncertainty_protocol=fixture_uncertainty_protocol(), status="REVIEWED_FOR_SHADOW_QUALIFICATION")
    return {"original": original, "events": original["events"],
        "event_evidence": original["event_evidence"], "dataset": dataset, "plan": plan,
        "evidence": evidence, "blobs": blobs, "assumptions": assumptions,
        "continuation_assumptions": continuation_assumptions,
        "training_quote_chains": chains,
        "cases": [{"case_id": "clean-declared-design", "policy": clean,
                    "hypothesis_id": row["hypothesis"].hypothesis_id,
                    "expected": "READY_FOR_QUALIFIED_STUDY_DESIGN"},
                  {"case_id": "insufficient-joint-sample", "policy": insufficient,
                    "hypothesis_id": continuation["hypothesis"].hypothesis_id,
                    "expected": "DEFER_EVIDENCE_QUALIFICATION"},
                  {"case_id": "inactive-proposed-design", "policy": proposed,
                    "hypothesis_id": continuation["hypothesis"].hypothesis_id,
                    "expected": "DEFER_EVIDENCE_QUALIFICATION"},
                  {"case_id": "forbidden-holdout-cost-evidence", "policy": forbidden,
                    "hypothesis_id": row["hypothesis"].hypothesis_id,
                    "expected": "DEFER_EVIDENCE_QUALIFICATION"}]}


def _request(case_id, policy_event):
    return TradingEvidenceQualificationRequest.from_mapping({
        "schema_version": "blackpod.trading_evidence_qualification_request.v1",
        "qualification_id": "synthetic-" + case_id + "-qualification",
        "policy_event_id": policy_event.event_id,
        "recorded_at": ASSESSMENT_RECORDED_AT, "data_cutoff_at": DATA_CUTOFF_AT,
        "supersedes_event_id": None, "auto_trading_enabled": False, "authority": authority()})


def example_material():
    """Freeze each policy before its separately appended assessment."""
    from .trading_evidence_qualification_journal import (
        policy_material, qualification_material,
    )
    material = fixture_material()
    events, retained, rows = list(material["events"]), list(material["event_evidence"]), []
    blobs = dict(material["blobs"])
    for case in material["cases"]:
        policy = case["policy"]
        registered = policy_material(policy, events, blobs)
        policy_event, policy_evidence = registered["event"], registered["evidence"]
        events.append(policy_event)
        retained.append(policy_evidence)
        blobs.update({sha256_bytes(raw): raw for raw in policy_evidence.values()})
        request = _request(case["case_id"], policy_event)
        assessed = qualification_material(request, events, blobs)
        assessment, assessment_evidence, result = assessed["event"], assessed["evidence"], assessed["result"]
        if result["status"] != case["expected"]:
            raise ValueError("qualification fixture disagrees with its expected case: " + case["case_id"])
        events.append(assessment)
        retained.append(assessment_evidence)
        blobs.update({sha256_bytes(raw): raw for raw in assessment_evidence.values()})
        rows.append({**case, "policy_event": policy_event, "request": request,
            "assessment_event": assessment, "result": result})
    return {**material, "events": tuple(events), "event_evidence": tuple(retained),
        "cases": rows, "blobs": blobs}


def prepare_example(destination):
    """Publish immutable example inputs and one mixed-version research journal."""
    from .auto_trading_runtime import RuntimeLedger
    from .decision_journal_store import _check_existing_ancestors, _reject_source_storage
    from .desk_candidate_review_cli import _write
    output = Path(destination).absolute()
    _check_existing_ancestors(output)
    _reject_source_storage(output)
    RuntimeLedger(output)
    input_root, evidence_root, journal_root = output / "input", output / "evidence", output / "journal"
    check_separate_root(input_root, journal_root)
    check_separate_root(evidence_root, journal_root)
    material = example_material()
    for path, raw in material["evidence"].items():
        if path.startswith("qualification-example/"):
            _write(evidence_root / path, raw, (journal_root,))
    _write(input_root / "training-assumptions.v1.json", material["assumptions"].to_bytes(), (journal_root,))
    _write(input_root / "continuation-training-assumptions.v1.json", material["continuation_assumptions"].to_bytes(), (journal_root,))
    store, written = JournalStore(journal_root), []
    for event, retained in zip(material["events"], material["event_evidence"]):
        written.append(store.append(event, retained).written)
    original = material["original"]["events"]
    if [event.to_bytes() for event in store.events()[:len(original)]] != [event.to_bytes() for event in original]:
        raise ValueError("qualification altered an original fixture event")
    cases = []
    for row in material["cases"]:
        case_id = row["case_id"]
        _write(input_root / (case_id + ".policy.json"), row["policy"].to_bytes(), (journal_root,))
        _write(input_root / (case_id + ".request.json"), row["request"].to_bytes(), (journal_root,))
        _write(output / "reports" / (case_id + ".result.json"), canonical_json_bytes(row["result"]), (journal_root,))
        cases.append({"case_id": case_id, "hypothesis_id": row["hypothesis_id"], "policy_id": row["policy"].policy_id,
            "policy_status": row["policy"].status, "policy_event_id": row["policy_event"].event_id,
            "qualification_event_id": row["assessment_event"].event_id,
            "status": row["result"]["status"],
            "reason_codes": row["result"]["reason_codes"],
            "eligible_for_study_design": row["result"]["eligible_for_study_design"],
            "uncertainty_status": row["result"]["uncertainty_status"],
            "request_path": "input/" + case_id + ".request.json",
            "policy_path": "input/" + case_id + ".policy.json",
            "result_path": "reports/" + case_id + ".result.json"})
    summary = {"schema_version": SCHEMA_VERSION, "data_status": "SYNTHETIC_FIXTURE_ONLY",
        "source_event_count": len(original), "cases": cases, "events_written": sum(written),
        "journal_verification": store.verify().to_dict(), "journal_root": "journal",
        "original_fixture_preserved": True,
        "training_session_count": 12, "training_quote_count": 24,
        "new_quote_bodies_are_authored_subsets_not_provider_captures": True,
        "real_market_performance_evaluated": False, "new_strategy_returns_computed": False,
        "uncertainty_computed": False, "economic_hypothesis_supported": False,
        "existing_gate_override": False, "final_holdout_scored": False,
        "provider_calls": 0, "model_inference_calls": 0, "orders_submitted": 0,
        "desk_budget_activated": False, "capital_transfers_enabled": False,
        "auto_trading_enabled": False}
    _write(output / "manifest.json", canonical_json_bytes({key: value for key, value in summary.items()
        if key != "events_written"}), ())
    return summary


def main(argv=None):
    parser = argparse.ArgumentParser(description="Run governed synthetic evidence-qualification designs offline.")
    parser.add_argument("--output-root", required=True, type=Path)
    arguments = parser.parse_args(argv)
    try:
        print(json.dumps(prepare_example(arguments.output_root), sort_keys=True))
        return 0
    except (OSError, ValueError, JournalStoreError) as exc:
        print(str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
