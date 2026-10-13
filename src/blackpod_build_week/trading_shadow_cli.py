"""Explicit passive shadow research commands; no execution or provider client."""
import argparse
from html import escape
import json
from pathlib import Path
import sys

from .contracts.trading_research import TradingResearchDataset, TradingResearchPlan
from .contracts.trading_shadow_research import (
    TradingShadowStudy, PriceContinuityEvidence, TradingCostEvidence,
    PriceContinuitySource, TradingCostSource,
)
from .decision_journal_store import JournalStore, JournalStoreError, check_separate_root
from .desk_candidate_review_cli import _references, _write
from .hashing import sha256_bytes
from .sentry_history_cache import read_regular, RecoveryError
from .trading_research_intake_cli import load_intake_evidence
from .trading_research_journal import PLAN_TYPE
from .trading_shadow_journal import (
    STUDY_TYPE, EVALUATION_TYPE, assess_registered_shadow, build_study_event,
    build_shadow_evaluation_event, evidence_for_shadow,
)


def _reference(path, raw):
    return {"path": path, "sha256": sha256_bytes(raw), "size_bytes": len(raw)}


def load_shadow_evidence(root, study, retained=None):
    """Load typed declarations and their declared opaque leaves only.

    Raw origin material may legitimately be a JSON list. References inside an
    origin body are not followed; review and source contracts explicitly state
    the entire gate closure. Every file is hash/size bound and symlinks reject.
    """
    study = TradingShadowStudy.from_mapping(study.to_dict() if isinstance(study, TradingShadowStudy) else study)
    blobs, visited, paths, total_bytes = dict(retained or {}), set(), {}, 0

    def load(references):
        nonlocal blobs, total_bytes
        for reference in references:
            identity = (reference["path"], reference["sha256"], reference["size_bytes"])
            if reference["path"] in paths and paths[reference["path"]] != identity:
                raise ValueError("shadow evidence paths bind conflicting source bytes")
            paths[reference["path"]] = identity
            if identity in visited:
                continue
            if len(visited) >= 256 or total_bytes + reference["size_bytes"] > 64 * 1024 * 1024:
                raise ValueError("shadow input evidence exceeds retained-file or combined-byte limits")
            visited.add(identity)
            total_bytes += reference["size_bytes"]
            blobs = load_intake_evidence(root, [reference], blobs)

    load(_references(study.to_dict()))
    plan = TradingResearchPlan.from_bytes(blobs[study.base_plan_evidence["sha256"]])
    load(_references(plan.to_dict()))
    dataset = TradingResearchDataset.from_bytes(blobs[plan.dataset_evidence["sha256"]])
    load(dataset.provenance["source_evidence"])
    for reference, review_class, source_class in (
        (study.price_continuity_evidence, PriceContinuityEvidence, PriceContinuitySource),
        (study.cost_evidence, TradingCostEvidence, TradingCostSource),
    ):
        if reference is None:
            continue
        review = review_class.from_bytes(blobs[reference["sha256"]])
        load(review.source_evidence)
        for source_reference in review.source_evidence:
            source = source_class.from_bytes(blobs[source_reference["sha256"]])
            load(source.origin_evidence)
    return blobs


def build_parser():
    parser = argparse.ArgumentParser(description="Governed independent shadow trading research; all execution authority disabled")
    commands = parser.add_subparsers(dest="command", required=True)
    prepare = commands.add_parser("prepare", help="Prepare a frozen shadow declaration without registering it")
    prepare.add_argument("--journal-root", type=Path, required=True)
    prepare.add_argument("--base-plan-event-id", required=True)
    prepare.add_argument("--study-id", required=True)
    prepare.add_argument("--experiment-id", required=True)
    prepare.add_argument("--registered-at", required=True)
    prepare.add_argument("--per-symbol-notional", required=True)
    prepare.add_argument("--evidence-scope", required=True, choices=("SYNTHETIC_FIXTURE_ONLY", "RETAINED_HISTORY_RESEARCH"))
    prepare.add_argument("--price-continuity", type=Path)
    prepare.add_argument("--cost-evidence", type=Path)
    prepare.add_argument("--evidence-root", type=Path)
    prepare.add_argument("--output-directory", type=Path, required=True)
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
        if name == "render":
            command.add_argument("--output", type=Path, required=True)
    return parser


def render_shadow_review(event):
    """Render only a verified evaluation; escape all external content."""
    if event.event_type != EVALUATION_TYPE:
        raise ValueError("a shadow report requires a verified linked evaluation")
    study, result, production = event.payload["study"], event.payload["result"], event.payload["production"]
    text = lambda value: escape(str(value), quote=True)
    gate = event.payload["gate_assessment"]
    rows = []
    for run in result["cost_stress_runs"]:
        candidate_folds = {} if run["candidate"] is None else {fold["fold_id"]: fold for fold in run["candidate"]["folds"]}
        if not run["folds"]:
            rows.append("<tr>" + "".join("<td>" + text(value) + "</td>" for value in (
                run["multiplier"], "—", run["status"], "UNASSESSED", "UNASSESSED", "UNASSESSED", "UNASSESSED", "UNASSESSED")) + "</tr>")
        for row in run["folds"]:
            candidate = candidate_folds[row["fold_id"]]
            metrics = candidate["metrics"] or {}
            comparison = row["comparison"]
            rows.append("<tr>" + "".join("<td>" + text(value) + "</td>" for value in (
                run["multiplier"], row["fold_id"], comparison["status"], metrics.get("simulated_total_pnl", "UNASSESSED"),
                comparison["control_net_pnl"], comparison["net_excess_vs_control"], len(candidate["fills"]), len(candidate["rejections"]))) + "</tr>")
    gate_reasons = "".join("<li>" + text(reason) + "</li>" for reason in gate["reason_codes"])
    limitations = "".join("<li>" + text(item) + "</li>" for item in result["limitations"])
    evidence_rows = "".join("<tr><td>" + text(ref["path"]) + "</td><td><code>" + text(ref["sha256"]) + "</code></td><td>" + text(ref["size_bytes"]) + "</td></tr>" for ref in event.evidence)
    return '''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>BlackPod · Independent shadow research</title>
<style>*{box-sizing:border-box}body{margin:0;background:#edf2f6;color:#183044;font:15px/1.6 system-ui,sans-serif}main{max-width:1200px;margin:auto;padding:26px}header{background:#133047;color:white;border-radius:12px;padding:28px;margin-bottom:22px}h1{font-size:30px;line-height:1.3}section{background:white;border:1px solid #d4dfe8;border-radius:12px;padding:24px;margin-bottom:22px}.badge{display:inline-block;border:1px solid #8fbcae;border-radius:5px;padding:4px 9px;margin:4px 6px 4px 0;font-size:12px}.note{background:#faf5e9;border-left:3px solid #b68c43;padding:14px}.table{overflow:auto}table{border-collapse:collapse;width:100%;font-size:13px}th,td{padding:11px;text-align:left;vertical-align:top;border-bottom:1px solid #dae3eb}th{background:#eff4f8}pre,code,footer{overflow-wrap:anywhere}pre{white-space:pre-wrap;font-size:12px}li{margin:8px 0;overflow-wrap:anywhere}footer{font-size:12px}@media(max-width:700px){main{padding:12px}header,section{padding:18px}h1{font-size:25px}}</style></head><body><main><header>
<h1>Independent trading hypotheses · governed shadow research</h1><span class="badge">SHADOW SIMULATION ONLY</span><span class="badge">ALL EXECUTION AUTHORITY OFF</span><span class="badge">FINAL HOLDOUT UNSCORED</span><p>''' + text(study["study_id"]) + " · " + text(study["trial_registry"]["trial_id"]) + " · " + text(event.recorded_at) + '''. Runtime status is checked separately.</p></header>
<section><h2>Evidence gates and decision scope</h2><p><strong>''' + text(result["status"]) + "</strong> · " + text(study["evidence_scope"]) + '''</p><p>Price continuity and costs eligible: ''' + text(gate["eligible"]) + '''</p><ul>''' + gate_reasons + '''</ul><p class="note">Research simulation is not realized trade P&amp;L, trading authorization or an executable order. Original hypotheses and evidence remain immutable. No Galactica trading rules or Brigade votes choose these intents. Declared sizing activates no desk budget or ownership.</p></section>
<section><h2>Development-only cost sensitivities</h2><div class="table"><table><thead><tr><th>Cost multiplier</th><th>Fold</th><th>Comparison status</th><th>Candidate simulated P&amp;L</th><th>Control simulated P&amp;L</th><th>Net excess vs control</th><th>Candidate fills</th><th>Candidate rejections</th></tr></thead><tbody>''' + "".join(rows) + '''</tbody></table></div><p>INCONCLUSIVE controls stay visible. Matching covers admitted entry purchase notional and holding duration; it does not match daily exposure or beta. Fractional control quantities are arithmetic only. Each fold resets simulated cash. Missing metrics remain UNASSESSED; final holdout scoring is WITHHELD.</p></section>
<section><h2>Frozen producer and interpretation</h2><p>''' + text(production["hypothesis_id"]) + " · " + text(production["status"]) + " · " + text(len(production["episodes"])) + " planned episodes · " + text(len(production["opportunities"])) + ''' retained opportunities.</p><p>Inputs are completed closes available before each research decision. Entry and exit prices belong to the later simulation. Historical availability is a retrospective assumption, not proof of past publication. A positive descriptive comparison does not establish alpha, validated performance or permission to promote a strategy.</p><ul>''' + limitations + '''</ul></section>
<section><details><summary>Complete retained production, evaluation and evidence</summary><pre>''' + text(json.dumps({"production": production, "result": result}, sort_keys=True, indent=2)) + '''</pre><div class="table"><table><thead><tr><th>Retained source</th><th>SHA-256</th><th>Bytes</th></tr></thead><tbody>''' + evidence_rows + '''</tbody></table></div></details></section><footer>BlackPod · passive journal v15 · ''' + text(event.event_id) + ''' · No orders, capital activation, policy changes or automatic strategy selection.</footer></main></body></html>'''


def _prepare(args, store, events, blobs):
    check_separate_root(store.root, args.output_directory)
    original = next((event for event in events if event.event_id == args.base_plan_event_id and event.event_type == PLAN_TYPE), None)
    if original is None:
        raise ValueError("preparation requires a verified preceding quality-plan event identity")
    base = TradingResearchPlan.from_mapping(original.payload["plan"])
    if base.schema_version != "blackpod.trading_research_plan.v2":
        raise ValueError("preparation requires an original v2 quality plan")
    base_path = "trading-shadow/base-plan-" + base.plan_id + ".v2.json"
    new_evidence, protected = {base_path: base.to_bytes()}, [store.root]
    fields = {}
    for name, supplied, path, document in (
        ("price_continuity_evidence", args.price_continuity, "trading-shadow/price-review.v1.json", PriceContinuityEvidence),
        ("cost_evidence", args.cost_evidence, "trading-shadow/cost-review.v1.json", TradingCostEvidence),
    ):
        fields[name] = None
        if supplied is not None:
            check_separate_root(store.root, supplied.parent)
            check_separate_root(args.output_directory, supplied.parent)
            raw = read_regular(supplied)
            document.from_bytes(raw)
            new_evidence[path] = raw
            fields[name] = _reference(path, raw)
            protected.append(supplied.parent)
    if args.evidence_root is not None:
        check_separate_root(store.root, args.evidence_root)
        check_separate_root(args.output_directory, args.evidence_root)
        protected.append(args.evidence_root)
    prior_events = events
    for index, event in enumerate(events):
        if event.event_type == STUDY_TYPE and event.source["study_id"] == args.study_id:
            prior_events = events[:index]
            break
    peers = [event for event in prior_events if event.event_type == STUDY_TYPE and event.source["experiment_id"] == args.experiment_id]
    prior = sorted(event.source["trial_id"] for event in peers)
    study = TradingShadowStudy.from_mapping({
        "schema_version": "blackpod.trading_shadow_study.v1", "study_id": args.study_id,
        "experiment_id": args.experiment_id, "registered_at": args.registered_at, "domain": "TRADING",
        "mode": "SHADOW_RESEARCH", "scope": "DEVELOPMENT_TEST_ONLY", "evidence_scope": args.evidence_scope,
        "base_plan_evidence": _reference(base_path, base.to_bytes()), **fields,
        "sizing": {"method": "KNOWN_CLOSE_WHOLE_QUANTITY", "per_symbol_notional": args.per_symbol_notional},
        "benchmark": {"kind": "MATCHED_ENTRY_NOTIONAL_AND_DURATION_EQUAL_WEIGHT_COUNTERFACTUAL"},
        "cost_stress_multipliers": ["1", "2", "4"],
        "trial_registry": {"trial_id": args.study_id + "-trial-1", "prior_trial_ids": prior},
        "auto_trading_enabled": False, "authority": {field: False for field in (
            "authorization_enabled", "capital_activation_enabled", "execution_enabled", "policy_changes_enabled")},
    })
    merged = dict(blobs)
    merged.update({sha256_bytes(raw): raw for raw in new_evidence.values()})
    source_root = args.evidence_root or (args.price_continuity.parent if args.price_continuity is not None
                                       else args.cost_evidence.parent if args.cost_evidence is not None else args.output_directory)
    merged = load_shadow_evidence(source_root, study, merged)
    event = build_study_event(study, events, merged)
    evidence = evidence_for_shadow(study, events, merged)
    for path, raw in evidence.items():
        _write(args.output_directory / path, raw, protected)
    return {"study_id": study.study_id, "study_path": str((args.output_directory / "trading-shadow/study.v1.json").absolute()),
            "gate_assessment": event.payload["gate_assessment"], "registered": False}


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        store = JournalStore(args.journal_root)
        events, blobs = store.verified_contents() if store.root.exists() else ((), {})
        if args.command == "prepare":
            output = _prepare(args, store, events, blobs)
        elif args.command == "verify":
            output = store.verify().to_dict()
        elif args.command in {"show", "render"}:
            event = next((row for row in events if row.event_id == args.event_id and row.event_type in {STUDY_TYPE, EVALUATION_TYPE}), None)
            if event is None:
                raise ValueError("unknown verified shadow research event")
            if args.command == "show":
                output = event.to_dict()
            else:
                raw = render_shadow_review(event).encode("utf-8")
                _write(args.output, raw, (store.root,))
                output = {"path": str(args.output.absolute()), "sha256": sha256_bytes(raw)}
        else:
            study = TradingShadowStudy.from_bytes(read_regular(args.study))
            check_separate_root(store.root, args.study.parent)
            if args.evidence_root is not None:
                check_separate_root(store.root, args.evidence_root)
                blobs = load_shadow_evidence(args.evidence_root, study, blobs)
            if args.command == "evaluate":
                output = {"study_id": study.study_id, **assess_registered_shadow(study, events, blobs)}
            else:
                event = build_study_event(study, events, blobs) if args.command == "register" else build_shadow_evaluation_event(
                    study, events, blobs, evaluation_id=args.evaluation_id, recorded_at=args.recorded_at)
                appended = store.append(event, evidence_for_shadow(study, events, blobs))
                output = {"study_id": study.study_id, "event_id": event.event_id, "decision_id": event.decision_id,
                          "trial_id": study.trial_registry["trial_id"], "written": appended.written, "sequence": appended.sequence}
        print(json.dumps({"command": args.command, **output, "orders_submitted": 0,
                          "provider_calls": 0, "auto_trading_changed": False}, sort_keys=True))
        return 0
    except (ValueError, OSError, JournalStoreError, RecoveryError, TypeError, KeyError, RecursionError) as exc:
        print("trading-shadow: " + str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
