"""Research-gate examples over unchanged, explicitly synthetic frozen inputs.

The existing examples supply every price, cost, calendar and investment
observation. This module adds assessments, never adjusts an old hypothesis or
market history, and never obtains data or acquires execution authority.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
import json
from pathlib import Path
import sys

from .decision_journal_store import JournalStore, JournalStoreError, check_separate_root
from .hashing import canonical_json_bytes, sha256_bytes

SCHEMA_VERSION = "blackpod.synthetic_research_acceptance_example.v1"
TRADING_RECORDED_AT = "2025-04-02T00:00:00Z"
TRADING_CUTOFF_AT = "2025-04-01T23:00:00Z"
INVESTMENT_RECORDED_AT = "2027-04-11T00:01:00Z"
INVESTMENT_CUTOFF_AT = "2027-04-11T00:00:00Z"


def _material(events, event_evidence, **additional):
    if len(events) != len(event_evidence):
        raise ValueError("source events and evidence must have identical lengths")
    blobs = {}
    for evidence in event_evidence:
        blobs.update({sha256_bytes(raw): raw for raw in evidence.values()})
    return {"events": tuple(events), "event_evidence": tuple(event_evidence),
            "blobs": blobs, **additional}


def investment_material():
    """Rebuild the committed nine-event investment example without edits."""
    from .contracts.investment_hypothesis import InvestmentHypothesis
    from .contracts.investment_review import ChallengeInput, OutcomeEvaluationInput
    from .decision_journal_projection import load_verified_history, project_history
    from .investment_hypothesis import build_hypothesis_event, evidence_for_hypothesis
    from .investment_review import (
        build_challenge_event, build_outcome_event, evidence_for_challenge, evidence_for_outcome,
    )
    checkout = Path(__file__).resolve().parents[2]
    events, retained = [], []

    def import_fixture(path):
        history = load_verified_history(checkout / path)
        for event in project_history(history):
            events.append(event)
            retained.append(dict(history.source_files))

    import_fixture("fixtures/investment_hypothesis/missions/mission-investment-hypothesis-example")
    hypothesis = InvestmentHypothesis.from_bytes(
        (checkout / "examples/investment_hypothesis.shadow.v1.json").read_bytes())
    context = _material(events, retained)
    parent = build_hypothesis_event(hypothesis, context["events"], context["blobs"])
    retained.append(evidence_for_hypothesis(hypothesis, context["events"], context["blobs"]))
    events.append(parent)
    import_fixture("fixtures/investment_review/missions/mission-investment-challenge-evidence")
    challenge = ChallengeInput.from_bytes(
        (checkout / "examples/investment_challenge.shadow.v1.json").read_bytes())
    context = _material(events, retained)
    challenge_event = build_challenge_event(challenge, context["events"], context["blobs"])
    retained.append(evidence_for_challenge(challenge, context["events"], context["blobs"]))
    events.append(challenge_event)
    import_fixture("fixtures/investment_review/missions/mission-investment-outcome-evidence")
    evaluation = OutcomeEvaluationInput.from_bytes(
        (checkout / "examples/investment_outcome_evaluation.final.v1.json").read_bytes())
    context = _material(events, retained)
    evaluation_event = build_outcome_event(evaluation, context["events"], context["blobs"])
    retained.append(evidence_for_outcome(evaluation, context["events"], context["blobs"]))
    events.append(evaluation_event)
    return _material(events, retained, hypothesis=hypothesis, hypothesis_event=parent,
        challenge_event=challenge_event, evaluation_event=evaluation_event)


def trading_material():
    """Reuse frozen v16 fixtures and append one explicitly missing-gate study."""
    from .contracts.trading_shadow_review import ReviewedShadowStudy
    from .trading_shadow_review_example import example_material as frozen_material
    from .trading_shadow_review_journal import (
        build_reviewed_study_event, build_reviewed_evaluation_event,
        evidence_for_reviewed_study,
    )
    frozen = frozen_material()
    context = _material(frozen["events"], frozen["event_evidence"])
    study = ReviewedShadowStudy.from_mapping({
        **frozen["studies"][0]["study"].to_dict(),
        "study_id": "acceptance-missing-gate-study",
        "experiment_id": "acceptance-missing-gate-experiment",
        "registered_at": "2025-04-01T16:00:00Z",
        "continuity_intake_evidence": None, "cost_intake_evidence": None,
        "trial_registry": {"trial_id": "acceptance-missing-gate-trial", "prior_trial_ids": []},
    })
    events, retained = list(context["events"]), list(context["event_evidence"])
    study_event = build_reviewed_study_event(study, events, context["blobs"])
    retained.append(evidence_for_reviewed_study(study, events, context["blobs"]))
    events.append(study_event)
    context = _material(events, retained)
    evaluation_event = build_reviewed_evaluation_event(study, events, context["blobs"],
        evaluation_id="acceptance-missing-gate-evaluation",
        recorded_at="2025-04-01T17:00:00Z")
    retained.append(evidence_for_reviewed_study(study, events, context["blobs"]))
    events.append(evaluation_event)
    return _material(events, retained, frozen=frozen,
        missing_study_event=study_event, missing_evaluation_event=evaluation_event)


def representative_material():
    """Return seven classifications, preserving every frozen source byte."""
    from .research_acceptance import prepare_request
    trading, investment = trading_material(), investment_material()
    events = [*trading["events"], *investment["events"]]
    retained = [*trading["event_evidence"], *investment["event_evidence"]]
    blobs = {**trading["blobs"], **investment["blobs"]}
    cases = []
    rows = {row["hypothesis"].hypothesis_id: row for row in trading["frozen"]["studies"]}
    continuation = rows["five-session-continuation-v1"]
    reversal = rows["previous-session-reversal-v1"]

    def trading_request(case_id, row, *, evaluation=True, candidate=None):
        return prepare_request(events, research_event_id=row["study_event"].event_id,
            assessment_id=case_id, recorded_at=TRADING_RECORDED_AT,
            data_cutoff_at=TRADING_CUTOFF_AT, assessment_scope="EXPLORATORY_RESEARCH",
            evaluation_event_id=row["evaluation_event"].event_id if evaluation else None,
            candidate_result_evidence=candidate, blobs=blobs)

    cases.append({"case_id": "valid-unproven", "expected": "EVALUABLE",
        "request": prepare_request(events, research_event_id=continuation["study_event"].event_id,
            assessment_id="acceptance-valid-unproven", recorded_at="2025-04-01T14:01:00Z",
            data_cutoff_at="2025-04-01T14:00:00Z", assessment_scope="EXPLORATORY_RESEARCH",
            blobs=blobs)})
    cases.append({"case_id": "missing-prerequisites", "expected": "NOT_EVALUABLE",
        "request": prepare_request(events, research_event_id=trading["missing_study_event"].event_id,
            assessment_id="acceptance-missing-prerequisites", recorded_at=TRADING_RECORDED_AT,
            data_cutoff_at=TRADING_CUTOFF_AT, assessment_scope="EXPLORATORY_RESEARCH",
            evaluation_event_id=trading["missing_evaluation_event"].event_id, blobs=blobs)})
    claimed = deepcopy(continuation["result"])
    claimed["status"] = "SUPPORTED"
    raw_claim = canonical_json_bytes(claimed)
    candidate = {"path": "acceptance-examples/untrusted-claimed-result.json",
        "sha256": sha256_bytes(raw_claim), "size_bytes": len(raw_claim)}
    cases.append({"case_id": "methodologically-invalid", "expected": "INVALID",
        "request": trading_request("acceptance-methodologically-invalid", continuation, candidate=candidate),
        "extra_evidence": {candidate["path"]: raw_claim}})
    cases.append({"case_id": "contradicted-comparison", "expected": "CONTRADICTED",
        "request": trading_request("acceptance-contradicted-comparison", continuation)})
    cases.append({"case_id": "positive-insufficient-robustness", "expected": "INCONCLUSIVE",
        "request": trading_request("acceptance-positive-insufficient-robustness", reversal)})
    for case_id, scope, expected in (
        ("supported-deadline-predicates", "DECLARED_DEADLINE_PREDICATES", "SUPPORTED"),
        ("unresolved-economic-thesis", "EXPLORATORY_RESEARCH", "INCONCLUSIVE"),
    ):
        request = prepare_request(events, research_event_id=investment["hypothesis_event"].event_id,
            assessment_id="acceptance-" + case_id, recorded_at=INVESTMENT_RECORDED_AT,
            data_cutoff_at=INVESTMENT_CUTOFF_AT, assessment_scope=scope,
            evaluation_event_id=investment["evaluation_event"].event_id, blobs=blobs)
        cases.append({"case_id": case_id, "expected": expected, "request": request})
    return _material(events, retained, cases=cases, trading=trading, investment=investment)


def make_examples(destination):
    """Write explicit requests and append linked assessments in a new journal."""
    from .auto_trading_runtime import RuntimeLedger
    from .decision_journal_store import _check_existing_ancestors, _reject_source_storage
    from .desk_candidate_review_cli import _write
    from .research_acceptance_journal import assessment_material
    output = Path(destination).absolute()
    _check_existing_ancestors(output)
    _reject_source_storage(output)
    RuntimeLedger(output)
    input_root, journal_root = output / "input", output / "journal"
    check_separate_root(input_root, journal_root)
    material = representative_material()
    store, written = JournalStore(journal_root), []
    for event, evidence in zip(material["events"], material["event_evidence"]):
        written.append(store.append(event, evidence).written)
    source_bytes = [event.to_bytes() for event in material["events"]]
    rows = []
    for case in material["cases"]:
        request = case["request"]
        _write(input_root / (case["case_id"] + ".request.json"), request.to_bytes(), (journal_root,))
        extra = case.get("extra_evidence", {})
        for path, raw in extra.items():
            _write(output / path, raw, (journal_root,))
        events, blobs = store.verified_contents()
        blobs.update({sha256_bytes(raw): raw for raw in extra.values()})
        projection = assessment_material(request, events, blobs)
        assessed = projection["assessment"]
        if assessed.classification != case["expected"]:
            raise ValueError("frozen example classification disagrees: " + case["case_id"])
        event, retained = projection["event"], projection["evidence"]
        written.append(store.append(event, retained).written)
        rows.append({"case_id": case["case_id"], "classification": assessed.classification,
            "assessment_event_id": event.event_id, "hypothesis_id": request.hypothesis["hypothesis_id"],
            "hypothesis_revision": assessed.hypothesis_revision,
            "assessment_scope": request.assessment_scope,
            "economic_hypothesis_supported": assessed.economic_hypothesis_supported,
            "source_authentication_verified": assessed.source_authentication_verified,
            "historical_point_in_time_verified": assessed.historical_point_in_time_verified,
            "findings": assessed.findings, "claim_scope": assessed.claim_scope,
            "request_path": "input/" + case["case_id"] + ".request.json"})
    final_events = store.events()
    if [event.to_bytes() for event in final_events[:len(source_bytes)]] != source_bytes:
        raise ValueError("example altered an original frozen research event")
    summary = {"schema_version": SCHEMA_VERSION, "data_status": "SYNTHETIC_FIXTURE_ONLY",
        "source_event_count": len(source_bytes), "assessment_count": len(rows),
        "cases": rows, "events_written": sum(written),
        "journal_verification": store.verify().to_dict(), "journal_root": "journal",
        "future_investment_observations_are_synthetic": True,
        "real_market_performance_evaluated": False, "economic_hypothesis_supported": False,
        "final_holdout_scored": False, "hypotheses_tuned": False,
        "provider_calls": 0, "model_inference_calls": 0, "orders_submitted": 0,
        "desk_budget_activated": False, "capital_transfers_enabled": False,
        "auto_trading_enabled": False,
    }
    # Retry bookkeeping is stdout metadata, not immutable artifact content.
    stable = {key: value for key, value in summary.items() if key != "events_written"}
    _write(output / "manifest.json", canonical_json_bytes(stable), ())
    return summary


def main(argv=None):
    parser = argparse.ArgumentParser(description="Run frozen synthetic research acceptance cases offline.")
    parser.add_argument("--output-root", required=True, type=Path)
    arguments = parser.parse_args(argv)
    try:
        result = make_examples(arguments.output_root)
        print(json.dumps(result, sort_keys=True))
        return 0
    except (ValueError, OSError, JournalStoreError) as exc:
        print(str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
