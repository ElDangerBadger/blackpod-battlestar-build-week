"""Explicit offline evidence adapters and reviewed simulation-only studies.

These commands consume retained files, never credentials or provider clients.
Preparing a study writes a declaration; registration and evaluation are separate
journal actions. Neither an approved shadow review nor a study activates capital.
"""
from __future__ import annotations

import argparse
from html import escape
import json
from pathlib import Path
import sys

from .contracts.mission_request import parse_strict_json_object_bytes
from .contracts.trading_continuity_intake import (
    ContinuityIntakeRequest, ContinuityIntakeExport, ContinuityCoverageReview,
)
from .contracts.trading_cost_intake import CostIntakeRequest, CostAssumptionReview
from .contracts.trading_research import TradingResearchPlan, TradingResearchDataset
from .contracts.trading_reconciliation import evidence_reference
from .contracts.trading_shadow_review import ReviewedShadowStudy
from .contracts.trading_shadow_risk_review import TradingShadowRiskReview
from .decision_journal_store import JournalStore, JournalStoreError, check_separate_root
from .desk_candidate_review_cli import _references, _write
from .hashing import canonical_json_bytes, sha256_bytes
from .sentry_history_cache import read_regular, RecoveryError
from .trading_continuity_intake import build_continuity_intake
from .trading_cost_intake import build_cost_intake
from .trading_research_intake_cli import load_intake_evidence
from .trading_research_journal import PLAN_TYPE


def _reference(path, raw):
    return {"path": path, "sha256": sha256_bytes(raw), "size_bytes": len(raw)}


def _mapping(value):
    return value.to_mapping() if hasattr(value, "to_mapping") else value


def load_reviewed_evidence(root, declaration, retained=None):
    """Load schema-declared closure; opaque origin and provider bodies stay opaque.

    A typed declaration or mapping follows only its explicit typed relationships.
    A list of evidence references loads those leaves only. JSON arrays inside raw
    bodies or origin briefs are never parsed or searched for nested references.
    Every loaded declaration/leaf has a hash, size and safe regular-file check.
    """
    blobs, paths, visited, expanded, total_bytes = dict(retained or {}), {}, set(), set(), 0

    def load(refs):
        nonlocal blobs, total_bytes
        for ref in refs:
            ref = evidence_reference(ref, "reviewed evidence")
            identity = (ref["path"], ref["sha256"], ref["size_bytes"])
            if ref["path"] in paths and paths[ref["path"]] != identity:
                raise ValueError("reviewed evidence paths bind conflicting bytes")
            paths[ref["path"]] = identity
            if identity in visited:
                continue
            if len(visited) >= 256 or total_bytes + ref["size_bytes"] > 64 * 1024 * 1024:
                raise ValueError("reviewed input evidence exceeds retained-file or combined-byte limits")
            visited.add(identity)
            total_bytes += ref["size_bytes"]
            blobs = load_intake_evidence(root, [ref], blobs)

    def typed(ref, cls):
        load([ref])
        value = cls.from_bytes(blobs[ref["sha256"]]).to_mapping()
        follow(value)
        return value

    def cost_export(ref):
        load([ref])
        value = parse_strict_json_object_bytes(blobs[ref["sha256"]])
        follow(value)

    def dataset(ref):
        typed(ref, TradingResearchDataset)

    def follow(value):
        value = _mapping(value)
        if not isinstance(value, dict):
            raise ValueError("reviewed evidence closure requires an explicit typed declaration")
        marker = sha256_bytes(canonical_json_bytes(value))
        if marker in expanded:
            return
        expanded.add(marker)
        version = value.get("schema_version")
        if version in {"blackpod.trading_research_dataset.v1", "blackpod.trading_research_dataset.v2"}:
            value = TradingResearchDataset.from_mapping(value).to_mapping()
            load(value["provenance"]["source_evidence"])
        elif version in {"blackpod.trading_research_plan.v1", "blackpod.trading_research_plan.v2"}:
            value = TradingResearchPlan.from_mapping(value).to_mapping()
            load(_references(value))
            dataset(value["dataset_evidence"])
        elif version == "blackpod.trading_continuity_intake_request.v1":
            value = ContinuityIntakeRequest.from_mapping(value).to_mapping()
            load(_references(value))
            dataset(value["dataset_evidence"])
            if value["coverage_review_evidence"] is not None:
                typed(value["coverage_review_evidence"], ContinuityCoverageReview)
        elif version == "blackpod.trading_continuity_intake_export.v1":
            value = ContinuityIntakeExport.from_mapping(value).to_mapping()
            load(_references(value))
            typed(value["request_evidence"], ContinuityIntakeRequest)
        elif version == "blackpod.trading_continuity_coverage_review.v1":
            value = ContinuityCoverageReview.from_mapping(value).to_mapping()
            load(value["source_evidence"])
            dataset(value["dataset_evidence"])
        elif version == "blackpod.trading_cost_intake_request.v1":
            value = CostIntakeRequest.from_mapping(value).to_mapping()
            load(_references(value))
            dataset(value["dataset_evidence"])
            if value["assumption_review_evidence"] is not None:
                typed(value["assumption_review_evidence"], CostAssumptionReview)
        elif version == "blackpod.trading_cost_intake_export.v1":
            # Full export validation is a deterministic native-source replay.
            expected = {"schema_version", "intake_id", "method_version", "request_evidence", "dataset_evidence",
                        "source_evidence", "review_evidence", "assessment", "limitations", "auto_trading_enabled", "authority"}
            if set(value) != expected:
                raise ValueError("cost intake export requires its exact fields")
            load([value[field] for field in ("request_evidence", "dataset_evidence", "review_evidence")]
                 + ([] if value["source_evidence"] is None else [value["source_evidence"]]))
            typed(value["request_evidence"], CostIntakeRequest)
        elif version == "blackpod.trading_cost_assumption_review.v1":
            value = CostAssumptionReview.from_mapping(value).to_mapping()
            load(value["origin_evidence"])
            dataset(value["dataset_evidence"])
        elif version == "blackpod.trading_shadow_risk_review.v1":
            value = TradingShadowRiskReview.from_mapping(value).to_mapping()
            load(_references(value))
            typed(value["base_plan_evidence"], TradingResearchPlan)
        elif version == "blackpod.trading_shadow_study.v2":
            value = ReviewedShadowStudy.from_mapping(value).to_mapping()
            load(_references(value))
            typed(value["base_plan_evidence"], TradingResearchPlan)
            typed(value["risk_review_evidence"], TradingShadowRiskReview)
            if value["continuity_intake_evidence"] is not None:
                typed(value["continuity_intake_evidence"], ContinuityIntakeExport)
            if value["cost_intake_evidence"] is not None:
                cost_export(value["cost_intake_evidence"])
        else:
            raise ValueError("unsupported reviewed evidence declaration version")

    if isinstance(declaration, (list, tuple)):
        load(declaration)
    else:
        follow(declaration)
    return blobs


def build_parser():
    parser = argparse.ArgumentParser(description="Governed retained-data evidence and simulation sizing review; all execution authority disabled")
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("export-continuity", "export-cost"):
        command = commands.add_parser(name)
        command.add_argument("--request", type=Path, required=True)
        command.add_argument("--evidence-root", type=Path, required=True)
        command.add_argument("--output-directory", type=Path, required=True)
    for name in ("record-continuity", "record-cost"):
        command = commands.add_parser(name)
        command.add_argument("--export", type=Path, required=True)
        command.add_argument("--evidence-root", type=Path, required=True)
        command.add_argument("--journal-root", type=Path, required=True)
        command.add_argument("--recorded-at", required=True)
    command = commands.add_parser("record-risk")
    command.add_argument("--review", type=Path, required=True)
    command.add_argument("--evidence-root", type=Path)
    command.add_argument("--journal-root", type=Path, required=True)
    command = commands.add_parser("prepare", help="Publish a reviewed study declaration without registering it")
    command.add_argument("--journal-root", type=Path, required=True)
    command.add_argument("--base-plan-event-id", required=True)
    command.add_argument("--risk-review-event-id", required=True)
    command.add_argument("--continuity-event-id")
    command.add_argument("--cost-event-id")
    command.add_argument("--study-id", required=True)
    command.add_argument("--experiment-id", required=True)
    command.add_argument("--registered-at", required=True)
    command.add_argument("--output-directory", type=Path, required=True)
    for name in ("register", "evaluate", "record"):
        command = commands.add_parser(name)
        command.add_argument("--study", type=Path, required=True)
        command.add_argument("--evidence-root", type=Path)
        command.add_argument("--journal-root", type=Path, required=True)
        if name == "record":
            command.add_argument("--evaluation-id", required=True)
            command.add_argument("--recorded-at", required=True)
    commands.add_parser("verify").add_argument("--journal-root", type=Path, required=True)
    for name in ("show", "render"):
        command = commands.add_parser(name)
        command.add_argument("--journal-root", type=Path, required=True)
        command.add_argument("--event-id", required=True)
        if name == "render": command.add_argument("--output", type=Path, required=True)
    return parser


def _journal():
    from . import trading_shadow_review_journal
    return trading_shadow_review_journal


def _export_doc(kind, raw):
    return ContinuityIntakeExport.from_bytes(raw) if kind == "CONTINUITY" else parse_strict_json_object_bytes(raw)


def _publish(evidence, output, protected=()):
    for path, raw in evidence.items():
        _write(output / path, raw, protected)


def _event(events, event_id, event_type):
    event = next((row for row in events if row.event_id == event_id and row.event_type == event_type), None)
    if event is None:
        raise ValueError("preparation requires verified preceding event identities of the requested type")
    return event


def _prepare(args, store, events, blobs):
    journal = _journal()
    check_separate_root(store.root, args.output_directory)
    original = _event(events, args.base_plan_event_id, PLAN_TYPE)
    base = TradingResearchPlan.from_mapping(original.payload["plan"])
    if base.schema_version != "blackpod.trading_research_plan.v2":
        raise ValueError("preparation requires an original quality plan v2")
    risk_event = _event(events, args.risk_review_event_id, journal.RISK_TYPE)
    review = TradingShadowRiskReview.from_mapping(risk_event.payload["review"])
    evidence = {
        "trading-shadow-review/base-plan-" + base.plan_id + ".v2.json": base.to_bytes(),
        "trading-shadow-review/risk-review.v1.json": review.to_bytes(),
    }
    refs = {path: _reference(path, raw) for path, raw in evidence.items()}
    fields = {"continuity_intake_evidence": None, "cost_intake_evidence": None}
    for name, event_id, event_type, path in (
        ("continuity_intake_evidence", args.continuity_event_id, journal.CONTINUITY_TYPE, "trading-shadow-review/continuity-export.v1.json"),
        ("cost_intake_evidence", args.cost_event_id, journal.COST_TYPE, "trading-shadow-review/cost-export.v1.json"),
    ):
        if event_id is not None:
            export_event = _event(events, event_id, event_type)
            raw = canonical_json_bytes(export_event.payload["export"])
            evidence[path] = raw
            fields[name] = _reference(path, raw)
    prior = events
    for index, event in enumerate(events):
        if event.event_type == journal.STUDY_TYPE and event.source["study_id"] == args.study_id:
            prior = events[:index]
            break
    peers = [event for event in prior if event.event_type == journal.STUDY_TYPE and event.source["experiment_id"] == args.experiment_id]
    study = ReviewedShadowStudy.from_mapping({
        "schema_version": "blackpod.trading_shadow_study.v2", "study_id": args.study_id,
        "experiment_id": args.experiment_id, "registered_at": args.registered_at,
        "domain": "TRADING", "mode": "SHADOW_RESEARCH", "scope": "DEVELOPMENT_TEST_ONLY",
        "base_plan_evidence": refs["trading-shadow-review/base-plan-" + base.plan_id + ".v2.json"],
        "risk_review_evidence": refs["trading-shadow-review/risk-review.v1.json"], **fields,
        "evidence_scope": review.evidence_scope, "sizing": review.sizing,
        "benchmark": {"kind": "MATCHED_ENTRY_NOTIONAL_AND_DURATION_EQUAL_WEIGHT_COUNTERFACTUAL"},
        "cost_stress_multipliers": ["1", "2", "4"],
        "trial_registry": {"trial_id": args.study_id + "-trial-1", "prior_trial_ids": sorted(event.source["trial_id"] for event in peers)},
        "auto_trading_enabled": False, "authority": review.authority,
    })
    merged = dict(blobs)
    merged.update({sha256_bytes(raw): raw for raw in evidence.values()})
    merged = load_reviewed_evidence(args.output_directory, study, merged)
    event = journal.build_reviewed_study_event(study, events, merged)
    evidence = journal.evidence_for_reviewed_study(study, events, merged)
    path = "trading-shadow-review/study.v2.json"
    if path in evidence and evidence[path] != study.to_bytes():
        raise ValueError("reviewed study publication conflicts with its frozen declaration")
    evidence[path] = study.to_bytes()
    _publish(evidence, args.output_directory, (store.root,))
    return {"study_id": study.study_id, "study_path": str((args.output_directory / path).absolute()),
            "registered": False, "assessment": event.payload.get("gate_assessment", event.payload.get("assessment"))}


def render_reviewed_shadow(event):
    """Escape the verified record; preserve all unavailable values and dissent."""
    journal = _journal()
    if event.event_type != journal.EVALUATION_TYPE:
        raise ValueError("a reviewed shadow report requires a verified linked evaluation")
    text = lambda value: escape(str(value), quote=True)
    payload = event.payload
    study, result = payload["study"], payload["result"]
    risk = result["risk_assessment"]
    gates = result["gate_assessment"]
    original_risk, reviewed_risk = result["original_simulation_risk"], result["reviewed_simulation_risk"]
    risk_rows = "".join("<tr><td>" + text(field) + "</td><td>" + text(original_risk[field])
                        + "</td><td>" + text(reviewed_risk[field]) + "</td></tr>" for field in sorted(original_risk))
    reasons = "".join("<li>" + text(reason) + "</li>" for reason in gates["reason_codes"])
    stress_rows = []
    for run in result["calculation_result"]["cost_stress_runs"]:
        candidates = {} if run["candidate"] is None else {fold["fold_id"]: fold for fold in run["candidate"]["folds"]}
        for fold in run["folds"]:
            candidate = candidates[fold["fold_id"]]
            metrics, comparison = candidate["metrics"] or {}, fold["comparison"]
            stress_rows.append("<tr>" + "".join("<td>" + text("UNASSESSED" if value is None else value) + "</td>" for value in (
                run["multiplier"], fold["fold_id"], comparison["status"], metrics.get("simulated_total_pnl", "UNASSESSED"),
                comparison["control_net_pnl"], comparison["net_excess_vs_control"], len(candidate["fills"]), len(candidate["rejections"]))) + "</tr>")
    if not stress_rows:
        stress_rows.append('<tr><td colspan="8">UNASSESSED · evidence gates defer simulation.</td></tr>')
    evidence = "".join("<tr><td>" + text(ref["path"]) + "</td><td><code>" + text(ref["sha256"]) + "</code></td><td>" + text(ref["size_bytes"]) + "</td></tr>" for ref in event.evidence)
    return '''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>BlackPod · Reviewed shadow evidence</title>
<style>*{box-sizing:border-box}body{margin:0;background:#edf2f6;color:#183044;font:15px/1.6 system-ui,sans-serif}main{max-width:1200px;margin:auto;padding:26px}header{background:#133047;color:white;border-radius:12px;padding:28px;margin-bottom:22px}h1{font-size:30px;line-height:1.3}section{background:white;border:1px solid #d4dfe8;border-radius:12px;padding:24px;margin-bottom:22px}.badge{display:inline-block;border:1px solid #8fbcae;border-radius:5px;padding:4px 9px;margin:4px 6px 4px 0;font-size:12px}.note{background:#faf5e9;border-left:3px solid #b68c43;padding:14px}.table{overflow:auto}table{border-collapse:collapse;width:100%;font-size:13px}th,td{padding:11px;text-align:left;vertical-align:top;border-bottom:1px solid #dae3eb}th{background:#eff4f8}pre,code,footer,li{overflow-wrap:anywhere}pre{white-space:pre-wrap;font-size:12px}@media(max-width:700px){main{padding:12px}header,section{padding:18px}h1{font-size:25px}}</style></head><body><main><header><h1>Governed evidence · reviewed shadow sizing</h1><span class="badge">SHADOW SIMULATION ONLY</span><span class="badge">ALL EXECUTION AUTHORITY OFF</span><span class="badge">FINAL HOLDOUT UNSCORED</span><p>''' + text(study["study_id"]) + " · " + text(study["evidence_scope"]) + " · " + text(event.recorded_at) + '''</p></header><section><h2>Verified disposition</h2><p><strong>''' + text(result["status"]) + "</strong> · evidence eligible: " + text(gates["eligible"]) + '''</p><ul>''' + reasons + '''</ul><p class="note">Simulation approval is a local review claim. It authenticates no human execution approval, activates no desk budget and submits no order. Original source-plan risk remains immutable. Corporate-action process dates are not effective-date coverage proof. Quote samples do not measure unexecuted fees or slippage.</p></section><section><h2>Explicit simulation sizing and risk review</h2><p>''' + text(risk["risk_review_id"]) + " · " + text(risk["provenance"]["review_status"]) + " · " + text(risk["provenance"]["reviewer_id"]) + '''. Reviewer identity is unauthenticated.</p><p>''' + text(risk["provenance"]["review_notes"]) + '''</p><p>Per-symbol declared notional: ''' + text(risk["sizing"]["per_symbol_notional"]) + " · Known-close feasible opportunities: " + text(risk["opportunity_counts"]["feasible_known_close"]) + " / " + text(risk["opportunity_counts"]["total"]) + " · Deferred opportunities: " + text(risk["opportunity_counts"]["deferred"]) + '''. These counts do not imply accepted fills.</p><div class="table"><table><thead><tr><th>Simulation risk declaration</th><th>Original frozen plan</th><th>Reviewed declaration</th></tr></thead><tbody>''' + risk_rows + '''</tbody></table></div><p>Internal risk projection prepared: ''' + text(result["internal_risk_projection_prepared"]) + '''. A prepared projection exists solely in shadow simulation; it never replaces original risk or activates desk capital.</p></section><section><h2>Development-only cost sensitivities</h2><div class="table"><table><thead><tr><th>Cost multiplier</th><th>Fold</th><th>Comparison status</th><th>Candidate simulated P&amp;L</th><th>Control simulated P&amp;L</th><th>Net excess vs control</th><th>Candidate fills</th><th>Candidate rejections</th></tr></thead><tbody>''' + "".join(stress_rows) + '''</tbody></table></div><p>Matching covers admitted entry purchase notional and holding duration. Daily exposure and beta remain unmatched; fractional controls are arithmetic only. Final holdout scoring is WITHHELD, and simulations are never realized trade P&amp;L or validated economic edge.</p></section><section><details><summary>Complete retained review, evaluation and evidence</summary><pre>''' + text(json.dumps(payload, sort_keys=True, indent=2)) + '''</pre><div class="table"><table><thead><tr><th>Source</th><th>SHA-256</th><th>Bytes</th></tr></thead><tbody>''' + evidence + '''</tbody></table></div></details></section><footer>BlackPod · passive journal · ''' + text(event.event_id) + ''' · No orders, capital activation, policy changes or automatic strategy selection. Runtime OFF status is verified separately.</footer></main></body></html>'''


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        if args.command in {"export-continuity", "export-cost"}:
            check_separate_root(args.output_directory, args.evidence_root)
            check_separate_root(args.output_directory, args.request.parent)
            kind = "CONTINUITY" if args.command == "export-continuity" else "COST"
            request_cls, builder = ((ContinuityIntakeRequest, build_continuity_intake) if kind == "CONTINUITY" else (CostIntakeRequest, build_cost_intake))
            request = request_cls.from_bytes(read_regular(args.request))
            blobs = load_reviewed_evidence(args.evidence_root, request)
            material = builder(request, blobs)
            export = _mapping(material["export"])
            evidence = dict(material["evidence"])
            path = ("continuity-intake" if kind == "CONTINUITY" else "cost-intake") + "/export.v1.json"
            evidence[path] = canonical_json_bytes(export)
            _publish(evidence, args.output_directory, (args.evidence_root, args.request.parent))
            output = {"intake_id": export["intake_id"], "export_path": str((args.output_directory / path).absolute()),
                      "status": export.get("status", export.get("assessment", {}).get("status"))}
        else:
            journal = _journal()
            store = JournalStore(args.journal_root)
            events, blobs = store.verified_contents() if store.root.exists() else ((), {})
            if args.command == "prepare":
                output = _prepare(args, store, events, blobs)
            elif args.command in {"record-continuity", "record-cost"}:
                kind = "CONTINUITY" if args.command == "record-continuity" else "COST"
                check_separate_root(store.root, args.evidence_root)
                check_separate_root(store.root, args.export.parent)
                export = _export_doc(kind, read_regular(args.export))
                blobs = load_reviewed_evidence(args.evidence_root, export, blobs)
                event = journal.build_evidence_intake_event(kind, export, blobs, recorded_at=args.recorded_at)
                appended = store.append(event, journal.evidence_for_intake(kind, export, blobs))
                output = {"intake_id": _mapping(export)["intake_id"], "event_id": event.event_id, "written": appended.written, "sequence": appended.sequence}
            elif args.command == "record-risk":
                check_separate_root(store.root, args.review.parent)
                review = TradingShadowRiskReview.from_bytes(read_regular(args.review))
                if args.evidence_root is not None:
                    check_separate_root(store.root, args.evidence_root)
                    blobs = load_reviewed_evidence(args.evidence_root, review, blobs)
                event = journal.build_risk_review_event(review, events, blobs)
                appended = store.append(event, journal.evidence_for_risk_review(review, events, blobs))
                output = {"risk_review_id": review.risk_review_id, "status": review.status,
                          "event_id": event.event_id, "written": appended.written, "sequence": appended.sequence}
            elif args.command == "verify":
                output = store.verify().to_dict()
            elif args.command in {"show", "render"}:
                types = {journal.CONTINUITY_TYPE, journal.COST_TYPE, journal.RISK_TYPE, journal.STUDY_TYPE, journal.EVALUATION_TYPE}
                event = next((row for row in events if row.event_id == args.event_id and row.event_type in types), None)
                if event is None: raise ValueError("unknown verified reviewed shadow event")
                if args.command == "show": output = event.to_dict()
                else:
                    raw = render_reviewed_shadow(event).encode("utf-8")
                    _write(args.output, raw, (store.root,))
                    output = {"path": str(args.output.absolute()), "sha256": sha256_bytes(raw)}
            else:
                check_separate_root(store.root, args.study.parent)
                study = ReviewedShadowStudy.from_bytes(read_regular(args.study))
                if args.evidence_root is not None:
                    check_separate_root(store.root, args.evidence_root)
                    blobs = load_reviewed_evidence(args.evidence_root, study, blobs)
                if args.command == "evaluate":
                    output = {"study_id": study.study_id, **journal.assess_registered_reviewed_study(study, events, blobs)}
                else:
                    event = journal.build_reviewed_study_event(study, events, blobs) if args.command == "register" else journal.build_reviewed_evaluation_event(
                        study, events, blobs, evaluation_id=args.evaluation_id, recorded_at=args.recorded_at)
                    appended = store.append(event, journal.evidence_for_reviewed_study(study, events, blobs))
                    output = {"study_id": study.study_id, "event_id": event.event_id, "decision_id": event.decision_id,
                              "written": appended.written, "sequence": appended.sequence, "trial_id": study.trial_registry["trial_id"]}
        print(json.dumps({"command": args.command, **output, "orders_submitted": 0, "provider_calls": 0, "auto_trading_changed": False}, sort_keys=True))
        return 0
    except (ValueError, OSError, JournalStoreError, RecoveryError, TypeError, KeyError, RecursionError) as exc:
        print("trading-shadow-review: " + str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
