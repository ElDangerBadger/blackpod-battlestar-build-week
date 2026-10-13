"""Entirely authored, offline examples of governed evidence and risk review.

Every market observation, action response, GET receipt and support statement
is invented for software verification. The approved review applies solely to
simulation declarations; it does not activate a desk or authorize an order.
"""
from __future__ import annotations

import argparse
from datetime import timedelta
from decimal import Decimal
import json
from pathlib import Path
import sys

from .contracts.mission_request import format_rfc3339, parse_rfc3339
from .contracts.trading_continuity_intake import ContinuityCoverageReview, ContinuityIntakeRequest
from .contracts.trading_cost_intake import CostAssumptionReview, CostIntakeRequest
from .contracts.trading_shadow_review import ReviewedShadowStudy
from .contracts.trading_shadow_risk_review import TradingShadowRiskReview, RISK_REVIEW_LIMITATIONS
from .decision_journal_store import JournalStore, JournalStoreError, check_separate_root
from .hashing import canonical_json_bytes, sha256_bytes
from .sentry_history_cache import RecoveryError
from .trading_continuity_intake import build_continuity_intake
from .trading_cost_intake import build_cost_intake
from .trading_shadow_example import _foundation_material as previous_foundation_material

SCHEMA_VERSION = "blackpod.synthetic_trading_shadow_review_example.v1"
CAPTURED_AT = "2025-04-01T11:30:00Z"
INTAKE_RECORDED_AT = "2025-04-01T12:00:00Z"
RISK_RECORDED_AT = "2025-04-01T13:00:00Z"
STUDY_REGISTERED_AT = "2025-04-01T14:00:00Z"
EVALUATED_AT = "2025-04-01T15:00:00Z"


def _authority():
    return {field: False for field in (
        "authorization_enabled", "capital_activation_enabled", "execution_enabled", "policy_changes_enabled",
    )}


def _reference(path, raw):
    return {"path": path, "sha256": sha256_bytes(raw), "size_bytes": len(raw)}


def _retained(evidence, path, value):
    raw = value if isinstance(value, bytes) else value.to_bytes() if hasattr(value, "to_bytes") else canonical_json_bytes(value)
    if path in evidence and evidence[path] != raw:
        raise ValueError("fixture paths bind conflicting retained bytes")
    evidence[path] = raw
    return _reference(path, raw)


def _receipt(url, query, body_ref):
    return {"schema_version": "blackpod.trading_evidence_capture.v1", "method": "GET", "url": url,
        "query": query, "captured_at": CAPTURED_AT, "status": 200,
        "body_sha256": body_ref["sha256"], "size_bytes": body_ref["size_bytes"]}


def fixture_material():
    """Extend six source foundation events with newly reconstructed gates."""
    original = previous_foundation_material()
    dataset = original["dataset"]
    # The previous fixture also prepares its v1 shadow declarations. They are
    # deliberately absent here: only the original six quality events and their
    # retained inputs seed this new, independently governed example.
    evidence = dict(original["evidence"])
    dataset_ref = original["base_studies"][0]["plan"].dataset_evidence
    span = {"coverage_start_session_id": dataset.sessions[0]["session_id"],
            "coverage_end_session_id": dataset.sessions[-1]["session_id"]}
    dates = [session["open_at"][:10] for session in dataset.sessions]
    action_ref = _retained(evidence, "synthetic-reviewed/actions.raw", {"corporate_actions": {}, "next_page_token": None})
    action_receipt_ref = _retained(evidence, "synthetic-reviewed/actions-receipt.json", _receipt(
        "https://data.alpaca.markets/v1/corporate-actions",
        {"symbols": ",".join(dataset.universe), "start": dates[0], "end": dates[-1], "sort": "asc", "limit": 1000}, action_ref))
    coverage_origin_ref = _retained(evidence, "synthetic-reviewed/coverage-review-origin.raw",
        b"Independent authored fixture statement: every synthetic effective date and action type was reviewed; this constructed price history has no actions. This is not a real-security or provider completeness attestation.\n")
    coverage = ContinuityCoverageReview.from_mapping({"schema_version": "blackpod.trading_continuity_coverage_review.v1",
        "review_id": "synthetic-reviewed-ex-date-coverage", "recorded_at": "2025-04-01T11:40:00Z",
        "dataset_evidence": dataset_ref, "universe": dataset.universe, **span,
        "coverage_policy": "ALL_ACTION_TYPES_EFFECTIVE_DATE_COVERAGE_INDEPENDENTLY_REVIEWED", "status": "SUPPORTED",
        "reviewer_id": "synthetic-fixture-author", "review_notes": "All authored fixture action types and dates were checked. No real continuity claim.",
        "source_evidence": [coverage_origin_ref], "auto_trading_enabled": False, "authority": _authority()})
    coverage_ref = _retained(evidence, "synthetic-reviewed/coverage-review.v1.json", coverage)
    continuity_request = ContinuityIntakeRequest.from_mapping({"schema_version": "blackpod.trading_continuity_intake_request.v1",
        "run_id": "synthetic-reviewed-continuity-intake", "recorded_at": INTAKE_RECORDED_AT, "domain": "TRADING",
        "mode": "SHADOW_RESEARCH", "scope": "RETAINED_CORPORATE_ACTION_INTAKE_ONLY", "evidence_scope": "SYNTHETIC_FIXTURE_ONLY",
        "dataset_evidence": dataset_ref, "universe": dataset.universe, "process_date_range": {"start": dates[0], "end": dates[-1]},
        "pages": [{"response_evidence": action_ref, "capture_receipt_evidence": action_receipt_ref}],
        "coverage_basis": "REVIEWED_EX_DATE_COVERAGE", "coverage_review_evidence": coverage_ref,
        "reviewer_id": "synthetic-fixture-author", "review_notes": "Authored native-shaped empty action response plus independent authored ex-date coverage review.",
        "auto_trading_enabled": False, "authority": _authority()})
    quotes = {symbol: [] for symbol in dataset.universe}
    for session in dataset.sessions:
        stamp = format_rfc3339(parse_rfc3339(session["open_at"], "fixture open") + timedelta(seconds=1))
        for bar in session["bars"]:
            # Numeric tokens belong to an authored fixture. The intake parses
            # their retained JSON spelling as Decimal, never as binary prices.
            bid = int(Decimal(bar["open"]))
            quotes[bar["symbol"]].append({"t": stamp, "bp": bid, "bs": 100, "bx": "V",
                "ap": float(Decimal(bid) + Decimal("0.01")), "as": 100, "ax": "V", "c": ["R"], "z": "C"})
    quote_ref = _retained(evidence, "synthetic-reviewed/quotes.raw", {"quotes": quotes, "next_page_token": None})
    quote_end = format_rfc3339(parse_rfc3339(dataset.sessions[-1]["open_at"], "fixture last open") + timedelta(seconds=60))
    quote_receipt_ref = _retained(evidence, "synthetic-reviewed/quotes-receipt.json", _receipt(
        "https://data.alpaca.markets/v2/stocks/quotes",
        {"symbols": ",".join(dataset.universe), "start": dataset.sessions[0]["open_at"], "end": quote_end,
         "feed": "iex", "currency": "USD", "sort": "asc", "asof": "-", "limit": 10000}, quote_ref))
    assumption_origin_ref = _retained(evidence, "synthetic-reviewed/cost-assumptions-origin.raw",
        b"Authored fixture assumptions: slippage 5 basis points, fee 0 basis points and USD 0.10 per simulated fill. These are toy declarations, not quotes, observed executions, broker fees or calibrated estimates.\n")
    assumptions = CostAssumptionReview.from_mapping({"schema_version": "blackpod.trading_cost_assumption_review.v1",
        "review_id": "synthetic-reviewed-cost-assumptions", "recorded_at": "2025-04-01T11:45:00Z",
        "dataset_evidence": dataset_ref, "universe": dataset.universe, **span, "evidence_scope": "SYNTHETIC_FIXTURE_ONLY",
        "status": "REVIEWED_SHADOW_ASSUMPTIONS", "parameters": {"slippage_bps": "5", "fee_bps": "0", "fee_per_fill": "0.10"},
        "origin_evidence": [assumption_origin_ref], "reviewer_id": "synthetic-fixture-author",
        "review_notes": "Declared toy assumptions solely exercise separate spread, slippage and fee provenance. No observed execution cost claim.",
        "auto_trading_enabled": False, "authority": _authority()})
    assumption_ref = _retained(evidence, "synthetic-reviewed/cost-assumptions.v1.json", assumptions)
    cost_request = CostIntakeRequest.from_mapping({"schema_version": "blackpod.trading_cost_intake_request.v1",
        "run_id": "synthetic-reviewed-cost-intake", "recorded_at": INTAKE_RECORDED_AT, "domain": "TRADING", "mode": "SHADOW_RESEARCH",
        "scope": "COST_EVIDENCE_INTAKE_ONLY", "evidence_scope": "SYNTHETIC_FIXTURE_ONLY", "dataset_evidence": dataset_ref,
        "quote_pages": [{"body_evidence": quote_ref, "receipt_evidence": quote_receipt_ref}], "assumption_review_evidence": assumption_ref,
        "reviewer_id": "synthetic-fixture-author", "review_notes": "Complete authored regular-quote opening-minute coverage. Assumptions remain distinct from measured spreads.",
        "auto_trading_enabled": False, "authority": _authority()})
    blobs = {sha256_bytes(raw): raw for raw in evidence.values()}
    continuity, costs = build_continuity_intake(continuity_request, blobs), build_cost_intake(cost_request, blobs)
    for item in (continuity, costs):
        for path, raw in item["evidence"].items():
            _retained(evidence, path, raw)
    continuity_export_ref = _retained(evidence, "synthetic-reviewed/continuity-intake.v1.json", continuity["export"])
    cost_export_ref = _retained(evidence, "synthetic-reviewed/cost-intake.v1.json", costs["export"])
    risk_origin_ref = _retained(evidence, "synthetic-reviewed/sizing-risk-origin.raw",
        b"Authored simulation brief: USD 1000 toy cash; USD 60 per symbol; order USD 100; position 0.10; gross 0.20; known volume 0.01; staleness 604800 seconds. These caps are not the recorded PAPER desk budgets and authorize no broker order or capital movement.\n")
    studies = []
    for index, base in enumerate(original["base_studies"], 1):
        plan_ref = _retained(evidence, "synthetic-reviewed/base-plan-h%d.v2.json" % index, base["plan"])
        sizing = {"method": "KNOWN_CLOSE_WHOLE_QUANTITY", "per_symbol_notional": "60"}
        risk_review = TradingShadowRiskReview.from_mapping({"schema_version": "blackpod.trading_shadow_risk_review.v1",
            "risk_review_id": "synthetic-reviewed-risk-h%d" % index, "recorded_at": RISK_RECORDED_AT,
            "reviewer_id": "synthetic-fixture-author", "review_notes": "Explicit toy simulation review; no optimal capital allocation or execution authorization.",
            "domain": "TRADING", "mode": "SHADOW_RESEARCH", "scope": "SIMULATION_SIZING_ONLY", "status": "APPROVED_FOR_SHADOW",
            "base_plan_evidence": plan_ref, "evidence_scope": "SYNTHETIC_FIXTURE_ONLY",
            "simulation_risk": {"initial_cash": "1000", "max_order_notional": "100", "max_position_fraction": "0.1",
                "max_gross_exposure_fraction": "0.2", "max_volume_participation_fraction": "0.01", "max_staleness_seconds": 604800},
            "sizing": sizing, "source_evidence": [risk_origin_ref], "limitations": list(RISK_REVIEW_LIMITATIONS),
            "auto_trading_enabled": False, "authority": _authority()})
        risk_ref = _retained(evidence, "synthetic-reviewed/risk-review-h%d.v1.json" % index, risk_review)
        study = ReviewedShadowStudy.from_mapping({"schema_version": "blackpod.trading_shadow_study.v2",
            "study_id": "synthetic-reviewed-shadow-study-h%d" % index, "experiment_id": "synthetic-reviewed-shadow-experiment-h%d" % index,
            "registered_at": STUDY_REGISTERED_AT, "domain": "TRADING", "mode": "SHADOW_RESEARCH", "scope": "DEVELOPMENT_TEST_ONLY",
            "evidence_scope": "SYNTHETIC_FIXTURE_ONLY", "base_plan_evidence": plan_ref, "sizing": sizing,
            "continuity_intake_evidence": continuity_export_ref, "cost_intake_evidence": cost_export_ref, "risk_review_evidence": risk_ref,
            "benchmark": {"kind": "MATCHED_ENTRY_NOTIONAL_AND_DURATION_EQUAL_WEIGHT_COUNTERFACTUAL"}, "cost_stress_multipliers": ["1", "2", "4"],
            "trial_registry": {"trial_id": "synthetic-reviewed-shadow-trial-h%d" % index, "prior_trial_ids": []},
            "auto_trading_enabled": False, "authority": _authority()})
        _retained(evidence, "synthetic-reviewed/study-h%d.v2.json" % index, study)
        studies.append({**base, "risk_review": risk_review, "study": study,
                        "evaluation_id": "synthetic-reviewed-shadow-evaluation-h%d" % index})
    return {"request": original["request"], "dataset": dataset, "catalog": original["catalog"], "intake": original["intake"],
        "events": original["events"], "event_evidence": original["event_evidence"], "base_studies": original["base_studies"],
        "continuity": continuity, "costs": costs, "coverage_review": coverage, "assumptions": assumptions,
        "studies": studies, "evidence": evidence, "blobs": {sha256_bytes(raw): raw for raw in evidence.values()}}


def example_material():
    """Compose original six foundation events plus eight additive review events."""
    from .trading_shadow_review_journal import (
        build_evidence_intake_event, evidence_for_intake, build_risk_review_event, evidence_for_risk_review,
        build_reviewed_study_event, evidence_for_reviewed_study, build_reviewed_evaluation_event,
    )
    material = fixture_material()
    events, retained = list(material["events"]), list(material["event_evidence"])
    intake_events = []
    for kind, adapter in (("CONTINUITY", material["continuity"]), ("COST", material["costs"])):
        event = build_evidence_intake_event(kind, adapter["export"], material["blobs"], recorded_at=INTAKE_RECORDED_AT)
        events.append(event); intake_events.append(event)
        retained.append(evidence_for_intake(kind, adapter["export"], material["blobs"]))
    risk_events = []
    for row in material["studies"]:
        review = row["risk_review"]
        event = build_risk_review_event(review, tuple(events), material["blobs"])
        events.append(event); risk_events.append(event)
        retained.append(evidence_for_risk_review(review, tuple(events), material["blobs"]))
    studies = []
    for row, risk_event in zip(material["studies"], risk_events):
        study = row["study"]
        event = build_reviewed_study_event(study, tuple(events), material["blobs"])
        events.append(event)
        retained.append(evidence_for_reviewed_study(study, tuple(events), material["blobs"]))
        evaluation = build_reviewed_evaluation_event(study, tuple(events), material["blobs"],
            evaluation_id=row["evaluation_id"], recorded_at=EVALUATED_AT)
        events.append(evaluation)
        retained.append(evidence_for_reviewed_study(study, tuple(events), material["blobs"]))
        studies.append({**row, "risk_event": risk_event, "study_event": event, "evaluation_event": evaluation,
                        "result": evaluation.payload["result"]})
    return {**material, "events": tuple(events), "event_evidence": tuple(retained), "studies": studies,
            "intake_events": tuple(intake_events), "risk_events": tuple(risk_events)}


def prepare_example(output_root):
    """Write auditable offline inputs and a replayable fourteen-event journal."""
    from .auto_trading_runtime import RuntimeLedger
    from .decision_journal_store import _check_existing_ancestors, _reject_source_storage
    from .desk_candidate_review_cli import _write
    output = Path(output_root).absolute()
    _check_existing_ancestors(output); _reject_source_storage(output); RuntimeLedger(output)
    input_root, evidence_root, journal_root = output / "input", output / "evidence", output / "journal"
    check_separate_root(input_root, journal_root); check_separate_root(evidence_root, journal_root)
    material = example_material()
    for path, raw in material["evidence"].items():
        _write(evidence_root / path, raw, (journal_root,))
    _write(input_root / "continuity-intake.json", material["continuity"]["request"].to_bytes(), (journal_root,))
    _write(input_root / "cost-intake.json", material["costs"]["request"].to_bytes(), (journal_root,))
    rows = []
    for index, row in enumerate(material["studies"], 1):
        _write(input_root / ("risk-review-%d.json" % index), row["risk_review"].to_bytes(), (journal_root,))
        _write(input_root / ("study-%d.json" % index), row["study"].to_bytes(), (journal_root,))
        _write(input_root / ("base-plan-%d.json" % index), row["plan"].to_bytes(), (journal_root,))
        rows.append({"hypothesis_id": row["hypothesis"].hypothesis_id, "study_id": row["study"].study_id,
            "study_path": "input/study-%d.json" % index, "risk_review_path": "input/risk-review-%d.json" % index,
            "risk_event_id": row["risk_event"].event_id, "study_event_id": row["study_event"].event_id,
            "evaluation_id": row["evaluation_id"], "evaluation_event_id": row["evaluation_event"].event_id,
            "evaluation_recorded_at": EVALUATED_AT})
    _write(output / "expected-results.json", canonical_json_bytes([row["result"] for row in material["studies"]]), ())
    store, written = JournalStore(journal_root), []
    for event, retained in zip(material["events"], material["event_evidence"]):
        written.append(store.append(event, retained).written)
    verification = store.verify().to_dict()
    manifest = {"schema_version": SCHEMA_VERSION, "data_status": "SYNTHETIC_FIXTURE_ONLY",
        "observations": "ENTIRELY_AUTHORED_PRICES_CALENDARS_ACTIONS_QUOTES_RECEIPTS_COVERAGE_ASSUMPTIONS_AND_RISK_NOT_ACTUAL_PROVIDER_RESPONSES",
        "symbols": material["dataset"].universe, "included_session_count": len(material["dataset"].sessions),
        "hypothesis_count": len(material["studies"]), "studies": rows, "journal_root": "journal", "evidence_root": "evidence",
        "controlled_fixture_performance_only": True, "real_market_performance_evaluated": False,
        "historical_point_in_time_verified": False, "final_holdout_scored": False,
        "recorded_paper_budgets_used": False, "desk_budget_activated": False, "orders_submitted": 0,
        "provider_calls": 0, "model_inference_calls": 0, "auto_trading_changed": False,
        "auto_trading_enabled": False, "authority": _authority()}
    _write(output / "example.json", canonical_json_bytes(manifest), ())
    return {**manifest, "output_root": str(output), "events_written": sum(written), "journal_verification": verification}


def main(argv=None):
    parser = argparse.ArgumentParser(description="Prepare governed quote/continuity and sizing fixtures without external calls")
    parser.add_argument("--output-root", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        print(json.dumps(prepare_example(args.output_root), sort_keys=True))
        return 0
    except (ValueError, OSError, TypeError, KeyError, RecursionError, JournalStoreError, RecoveryError) as exc:
        print("trading-shadow-review-example: " + str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
