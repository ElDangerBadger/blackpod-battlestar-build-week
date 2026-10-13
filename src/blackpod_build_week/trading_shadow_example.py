"""Controlled fixtures for independent intent production and counterfactuals.

Every price, calendar row, receipt, continuity review and cost bound is authored
for software testing. No provider is contacted and no real market performance,
historical preregistration, point-in-time availability, or execution is claimed.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from .contracts.historical_intake import HistoricalIntakeRequest
from .contracts.trading_shadow_research import (
    PriceContinuityEvidence, PriceContinuitySource, TradingCostEvidence, TradingCostSource, TradingShadowStudy,
)
from .decision_journal_store import JournalStore, JournalStoreError, check_separate_root
from .hashing import canonical_json_bytes, sha256_bytes
from .sentry_history_cache import RecoveryError
from .trading_historical_example import (
    CATALOG_RECORDED_AT, INTAKE_RECORDED_AT, REGISTERED_AT, EVALUATED_AT as QUALITY_EVALUATED_AT,
    SYMBOLS, synthetic_source_material,
)
from .trading_historical_intake import build_historical_intake
from .trading_hypotheses import catalog_documents, catalog_hypotheses

SCHEMA_VERSION = "blackpod.synthetic_trading_shadow_example.v1"
SOURCE_RECORDED_AT = "2025-04-01T11:10:00Z"
REVIEW_RECORDED_AT = "2025-04-01T11:20:00Z"
STUDY_REGISTERED_AT = "2025-04-01T12:00:00Z"
EVALUATED_AT = "2025-04-01T13:00:00Z"


def _authority():
    return {field: False for field in (
        "authorization_enabled", "capital_activation_enabled", "execution_enabled", "policy_changes_enabled",
    )}


def _reference(path, raw):
    return {"path": path, "sha256": sha256_bytes(raw), "size_bytes": len(raw)}


def zigzag_source_material():
    """Rebind authored numeric daily bars to exercise both fixed sign rules."""
    material = synthetic_source_material()
    mapping, evidence = material["request"].to_dict(), dict(material["evidence"])
    bars_ref = mapping["sources"]["bars_evidence"]
    bars = json.loads(evidence.pop(bars_ref["path"]))
    pattern = (2, -1, 0, 1, -2, 3, -1, 2)
    for offset, symbol in enumerate(SYMBOLS):
        for index, row in enumerate(bars["bars"][symbol]):
            opening = 10 + offset * 10 + index // 8
            closing = opening + pattern[index % len(pattern)]
            row.update(o=opening, c=closing, h=max(opening, closing) + 2,
                       l=min(opening, closing) - 2, vw=opening)
    raw_bars = canonical_json_bytes(bars)
    bars_ref = _reference("synthetic-shadow/bars.raw", raw_bars)
    evidence[bars_ref["path"]] = raw_bars
    mapping["sources"]["bars_evidence"] = bars_ref
    receipt_ref = mapping["sources"]["bars_receipt_evidence"]
    receipt = json.loads(evidence[receipt_ref["path"]])
    receipt.update(body_sha256=bars_ref["sha256"], size_bytes=len(raw_bars))
    raw_receipt = canonical_json_bytes(receipt)
    evidence[receipt_ref["path"]] = raw_receipt
    mapping["sources"]["bars_receipt_evidence"] = _reference(receipt_ref["path"], raw_receipt)
    mapping["run_id"] = "synthetic-shadow-historical-intake"
    return {"request": HistoricalIntakeRequest.from_mapping(mapping), "evidence": evidence,
            "blobs": {sha256_bytes(raw): raw for raw in evidence.values()}}


def _foundation_material():
    """Retain the existing data-quality contracts before adding new studies."""
    from .trading_research_intake_cli import make_plan
    from .trading_research_intake_journal import (
        build_catalog_event, build_intake_event, catalog_evidence, intake_evidence,
    )
    from .trading_research_journal import build_plan_event, build_evaluation_event, evidence_for_research

    sources = zigzag_source_material()
    intake = build_historical_intake(sources["request"], sources["blobs"])
    catalog = catalog_hypotheses(CATALOG_RECORDED_AT, "synthetic-fixture-author", catalog_id="synthetic-shadow-hypotheses")
    evidence, blobs = dict(intake["evidence"]), dict(intake["blobs"])
    retained_catalog = catalog_evidence(catalog)
    evidence.update(retained_catalog)
    blobs.update({sha256_bytes(raw): raw for raw in retained_catalog.values()})
    events = [build_catalog_event(catalog), build_intake_event(intake["export"], blobs, recorded_at=INTAKE_RECORDED_AT)]
    retained = [retained_catalog, intake_evidence(intake["export"], blobs)]
    base_studies = []
    for index, hypothesis in enumerate(catalog_documents(catalog), 1):
        material = make_plan(hypothesis, intake["dataset"], blobs, registered_at=REGISTERED_AT,
                            experiment_id="synthetic-shadow-base-experiment-h%d" % index,
                            plan_id="synthetic-shadow-base-plan-h%d" % index)
        evidence.update(material["evidence"])
        blobs.update(material["blobs"])
        plan = material["plan"]
        plan_event = build_plan_event(plan, tuple(events), blobs)
        events.append(plan_event)
        retained.append(evidence_for_research(plan, blobs))
        evaluation_id = "synthetic-shadow-quality-evaluation-h%d" % index
        evaluation = build_evaluation_event(plan, tuple(events), blobs, evaluation_id=evaluation_id,
                                           recorded_at=QUALITY_EVALUATED_AT)
        events.append(evaluation)
        retained.append(evidence_for_research(plan, blobs))
        base_studies.append({"hypothesis": hypothesis, "plan": plan, "intents": material["intents"],
                             "plan_event": plan_event, "evaluation_event": evaluation, "evaluation_id": evaluation_id})
    return {"sources": sources, "request": sources["request"], "intake": intake, "dataset": intake["dataset"],
            "catalog": catalog, "base_studies": base_studies, "events": tuple(events),
            "event_evidence": tuple(retained), "evidence": evidence, "blobs": blobs}


def fixture_material():
    """Compose complete synthetic gate inputs without assuming review trust."""
    material = _foundation_material()
    dataset = material["dataset"]
    dataset_ref = material["base_studies"][0]["plan"].dataset_evidence
    evidence, blobs = dict(material["evidence"]), dict(material["blobs"])
    coverage = {"coverage_start_session_id": dataset.sessions[0]["session_id"],
                "coverage_end_session_id": dataset.sessions[-1]["session_id"]}
    limits = ["SYNTHETIC_TEST_EVIDENCE_NOT_REAL_MARKET_SUPPORT", "NO_HISTORICAL_POINT_IN_TIME_ATTESTATION", "NO_EXECUTION_AUTHORITY"]
    origin_material = {
        "synthetic-shadow/continuity-origin.raw": b"Entirely authored fictional price series. No corporate actions occurred in this constructed fixture. This is not a provider response or a review of real securities.\n",
        "synthetic-shadow/cost-origin.raw": b"Entirely authored fixture cost bounds: spread 10 bps; slippage 5 bps; fee 0 bps plus USD 0.10 per fill. No quotes, broker fills, fee schedules or costs were observed.\n",
    }
    evidence.update(origin_material)
    price_source = PriceContinuitySource.from_mapping({
        "schema_version": "blackpod.trading_price_continuity_source.v1", "source_id": "synthetic-shadow-continuity-source",
        "recorded_at": SOURCE_RECORDED_AT, "basis": "SYNTHETIC_FIXTURE", "dataset_evidence": dataset_ref,
        "universe": dataset.universe, **coverage, "coverage_complete": True,
        "price_policy": "RAW_NO_SPLITS_DISTRIBUTIONS_OR_SYMBOL_CHANGES", "events": [],
        "origin_evidence": [_reference(path, raw) for path, raw in origin_material.items() if "continuity" in path],
        "limitations": limits, "auto_trading_enabled": False, "authority": _authority(),
    })
    model = dict(material["base_studies"][0]["plan"].cost_model)
    cost_source = TradingCostSource.from_mapping({
        "schema_version": "blackpod.trading_cost_source.v1", "source_id": "synthetic-shadow-cost-source",
        "recorded_at": SOURCE_RECORDED_AT, "basis": "SYNTHETIC_FIXTURE", "dataset_evidence": dataset_ref,
        "universe": dataset.universe, **coverage, "coverage_complete": True,
        "observations": [{"symbol": symbol, **model} for symbol in dataset.universe],
        "sampling_policy": "DECLARED_REVIEW_BOUNDS_NOT_EXECUTABLE_QUOTES",
        "origin_evidence": [_reference(path, raw) for path, raw in origin_material.items() if "cost" in path],
        "limitations": limits, "auto_trading_enabled": False, "authority": _authority(),
    })
    evidence["synthetic-shadow/continuity-source.v1.json"] = price_source.to_bytes()
    evidence["synthetic-shadow/cost-source.v1.json"] = cost_source.to_bytes()
    price_review = PriceContinuityEvidence.from_mapping({
        "schema_version": "blackpod.price_continuity_evidence.v1", "evidence_id": "synthetic-shadow-continuity-review",
        "recorded_at": REVIEW_RECORDED_AT, "dataset_evidence": dataset_ref, **coverage, "universe": dataset.universe,
        "basis": "SYNTHETIC_FIXTURE", "status": "CONTINUITY_SUPPORTED",
        "source_evidence": [_reference("synthetic-shadow/continuity-source.v1.json", price_source.to_bytes())],
        "reviewer_id": "synthetic-fixture-author", "review_notes": "The retained source declares authored fixture continuity; it does not establish continuity of real securities.",
        "limitations": limits, "auto_trading_enabled": False, "authority": _authority(),
    })
    cost_review = TradingCostEvidence.from_mapping({
        "schema_version": "blackpod.trading_cost_evidence.v1", "evidence_id": "synthetic-shadow-cost-review",
        "recorded_at": REVIEW_RECORDED_AT, "dataset_evidence": dataset_ref, **coverage, "universe": dataset.universe,
        "basis": "SYNTHETIC_FIXTURE", "status": "SUPPORTED", "cost_model": model,
        "source_evidence": [_reference("synthetic-shadow/cost-source.v1.json", cost_source.to_bytes())],
        "reviewer_id": "synthetic-fixture-author", "review_notes": "These exact costs exercise accounting and stress logic. They were authored, not estimated from quotes or executions.",
        "limitations": limits, "auto_trading_enabled": False, "authority": _authority(),
    })
    evidence["synthetic-shadow/continuity-review.v1.json"] = price_review.to_bytes()
    evidence["synthetic-shadow/cost-review.v1.json"] = cost_review.to_bytes()
    studies = []
    for index, base in enumerate(material["base_studies"], 1):
        plan = base["plan"]
        plan_path = "shadow-source/base-plan-h%d.v2.json" % index
        evidence[plan_path] = plan.to_bytes()
        study = TradingShadowStudy.from_mapping({
            "schema_version": "blackpod.trading_shadow_study.v1", "study_id": "synthetic-shadow-study-h%d" % index,
            "experiment_id": "synthetic-shadow-experiment-h%d" % index, "registered_at": STUDY_REGISTERED_AT,
            "domain": "TRADING", "mode": "SHADOW_RESEARCH", "scope": "DEVELOPMENT_TEST_ONLY",
            "evidence_scope": "SYNTHETIC_FIXTURE_ONLY", "base_plan_evidence": _reference(plan_path, plan.to_bytes()),
            "price_continuity_evidence": _reference("synthetic-shadow/continuity-review.v1.json", price_review.to_bytes()),
            "cost_evidence": _reference("synthetic-shadow/cost-review.v1.json", cost_review.to_bytes()),
            "sizing": {"method": "KNOWN_CLOSE_WHOLE_QUANTITY", "per_symbol_notional": "80"},
            "benchmark": {"kind": "MATCHED_ENTRY_NOTIONAL_AND_DURATION_EQUAL_WEIGHT_COUNTERFACTUAL"},
            "cost_stress_multipliers": ["1", "2", "4"], "trial_registry": {"trial_id": "synthetic-shadow-trial-h%d" % index, "prior_trial_ids": []},
            "auto_trading_enabled": False, "authority": _authority(),
        })
        studies.append({**base, "study": study, "evaluation_id": "synthetic-shadow-evaluation-h%d" % index})
    blobs.update({sha256_bytes(raw): raw for raw in evidence.values()})
    return {**material, "studies": studies, "price_source": price_source, "cost_source": cost_source,
            "price_review": price_review, "cost_review": cost_review, "evidence": evidence, "blobs": blobs}


def example_material():
    """Compose six foundation events and four shadow study/evaluation events."""
    from .trading_shadow_journal import build_study_event, build_shadow_evaluation_event, evidence_for_shadow

    material = fixture_material()
    events, retained, studies = list(material["events"]), list(material["event_evidence"]), []
    for row in material["studies"]:
        study = row["study"]
        study_event = build_study_event(study, tuple(events), material["blobs"])
        events.append(study_event)
        retained.append(evidence_for_shadow(study, tuple(events), material["blobs"]))
        evaluation_event = build_shadow_evaluation_event(study, tuple(events), material["blobs"],
            evaluation_id=row["evaluation_id"], recorded_at=EVALUATED_AT)
        events.append(evaluation_event)
        retained.append(evidence_for_shadow(study, tuple(events), material["blobs"]))
        studies.append({**row, "study_event": study_event, "evaluation_event": evaluation_event,
                        "result": evaluation_event.payload["result"]})
    return {**material, "events": tuple(events), "event_evidence": tuple(retained), "studies": studies}


def prepare_example(output_root):
    """Publish bounded fixture inputs and a fully replayable passive journal."""
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
    rows = []
    for index, study in enumerate(material["studies"], 1):
        path = "input/study-%d.json" % index
        _write(output / path, study["study"].to_bytes(), (journal_root,))
        _write(input_root / ("base-plan-%d.json" % index), study["plan"].to_bytes(), (journal_root,))
        rows.append({"hypothesis_id": study["hypothesis"].hypothesis_id, "study_path": path,
                     "study_id": study["study"].study_id, "study_event_id": study["study_event"].event_id,
                     "evaluation_id": study["evaluation_id"], "evaluation_event_id": study["evaluation_event"].event_id,
                     "evaluation_recorded_at": EVALUATED_AT})
    _write(output / "expected-results.json", canonical_json_bytes([study["result"] for study in material["studies"]]), ())
    store, appended = JournalStore(journal_root), []
    for event, retained in zip(material["events"], material["event_evidence"]):
        appended.append(store.append(event, retained).written)
    verification = store.verify().to_dict()
    manifest = {"schema_version": SCHEMA_VERSION, "data_status": "SYNTHETIC_FIXTURE_ONLY",
        "observations": "ENTIRELY_AUTHORED_PRICES_CALENDAR_RECEIPTS_CONTINUITY_AND_COSTS_NOT_ACTUAL_PROVIDER_RESPONSES",
        "symbols": SYMBOLS, "included_session_count": len(material["dataset"].sessions),
        "hypothesis_count": len(material["studies"]), "studies": rows, "evidence_root": "evidence", "journal_root": "journal",
        "controlled_fixture_performance_only": True, "real_market_performance_evaluated": False,
        "final_holdout_scored": False, "historical_point_in_time_verified": False,
        "recorded_paper_budgets_used": False, "orders_submitted": 0, "provider_calls": 0, "model_inference_calls": 0,
        "auto_trading_changed": False, "auto_trading_enabled": False, "authority": _authority()}
    _write(output / "example.json", canonical_json_bytes(manifest), ())
    return {**manifest, "output_root": str(output), "events_written": sum(appended), "journal_verification": verification}


def main(argv=None):
    parser = argparse.ArgumentParser(description="Prepare controlled synthetic shadow intent and matched benchmark studies without external calls")
    parser.add_argument("--output-root", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        print(json.dumps(prepare_example(args.output_root), sort_keys=True))
        return 0
    except (ValueError, OSError, TypeError, KeyError, RecursionError, JournalStoreError, RecoveryError) as exc:
        print("trading-shadow-example: " + str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
