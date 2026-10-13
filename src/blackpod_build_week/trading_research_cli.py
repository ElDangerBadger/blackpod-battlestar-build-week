"""Explicit offline research commands; no provider or trading entry point."""
import argparse
from html import escape
import json
from pathlib import Path
import sys

from .contracts.trading_research import TradingResearchPlan
from .decision_journal_store import JournalStore, JournalStoreError, check_separate_root
from .desk_candidate_review_cli import _references, _write, load_evidence
from .hashing import sha256_bytes
from .sentry_history_cache import read_regular, RecoveryError
from .trading_research_journal import (
    PLAN_TYPE, EVALUATION_TYPE, assess_registered_research, build_plan_event,
    build_evaluation_event, evidence_for_research,
)


def build_parser():
    parser = argparse.ArgumentParser(description="Independent offline trading research; no strategy producer or execution authority")
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("register", "evaluate", "record"):
        sub = commands.add_parser(name)
        sub.add_argument("--plan", type=Path, required=True)
        sub.add_argument("--evidence-root", type=Path)
        sub.add_argument("--journal-root", type=Path, required=True)
        if name == "record":
            sub.add_argument("--evaluation-id", required=True)
            sub.add_argument("--recorded-at", required=True)
    commands.add_parser("verify").add_argument("--journal-root", type=Path, required=True)
    for name in ("show", "render"):
        sub = commands.add_parser(name)
        sub.add_argument("--journal-root", type=Path, required=True)
        sub.add_argument("--event-id", required=True)
        if name == "render":
            sub.add_argument("--output", type=Path, required=True)
    return parser


def render_research_review(event):
    html = _render_research_review(event)
    if event.schema_version == "blackpod.decision_journal_event.v14":
        html = html.replace("SIMULATED ONLY", "DATA QUALITY ONLY · NO STRATEGY PRODUCER")
        html = html.replace("Per-fold simulated outcomes", "Per-fold data readiness")
        html = html.replace("passive journal v12", "passive journal v14")
        html = html.replace("This foundation evaluates externally supplied research decisions.",
            "This study validates retained historical data and empty research intents. Historical availability is a retrospective assumption; source receipt clocks do not prove past publication. Costs and simulated sizing are uncalibrated planning placeholders. No returns or winner are calculated.")
    return html


def _render_research_review(event):
    if event.event_type != EVALUATION_TYPE:
        raise ValueError("a research report requires a verified simulated evaluation")
    plan, result = event.payload["plan"], event.payload["result"]
    text = lambda value: escape(str(value), quote=True)
    rows, ledgers = [], []
    for fold in result["folds"]:
        metrics = fold.get("metrics") or {}
        rows.append('<tr>' + ''.join('<td>' + text(value) + '</td>' for value in (
            fold["fold_id"], fold["status"], metrics.get("net_return"), metrics.get("simulated_total_pnl"),
            metrics.get("maximum_close_drawdown"), len(fold["fills"]), len(fold["rejections"]), metrics.get("modeled_total_cost"))) + '</tr>')
        for disposition in fold["decisions"]:
            ledgers.append('<tr>' + ''.join('<td>' + text(value) + '</td>' for value in (
                fold["fold_id"], disposition["decision_id"], disposition["disposition"], disposition["reason_code"])) + '</tr>')
    sources = ''.join('<li>' + text(ref["path"]) + ' <code>' + text(ref["sha256"]) + '</code></li>' for ref in event.evidence)
    limitations = ''.join('<li>' + text(item) + '</li>' for item in result["limitations"])
    return '''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>BlackPod · Independent trading research</title>
<style>*{box-sizing:border-box}body{margin:0;background:#edf2f6;color:#183044;font:15px/1.6 system-ui,sans-serif}main{max-width:1200px;margin:auto;padding:26px}header{background:#133047;color:white;border-radius:12px;padding:28px;margin-bottom:22px}h1{font-size:30px;line-height:1.3}section{background:white;border:1px solid #d4dfe8;border-radius:12px;padding:24px;margin-bottom:22px}.badge{display:inline-block;border:1px solid #8fbcae;border-radius:5px;padding:4px 9px;margin:4px 6px 4px 0;font-size:12px}.note{background:#faf5e9;border-left:3px solid #b68c43;padding:14px}.table{overflow:auto}table{border-collapse:collapse;width:100%;font-size:13px}th,td{padding:11px;text-align:left;vertical-align:top;border-bottom:1px solid #dae3eb}th{background:#eff4f8}pre,code,footer{overflow-wrap:anywhere}pre{white-space:pre-wrap;font-size:12px}li{margin:8px 0;overflow-wrap:anywhere}footer{font-size:12px}@media(max-width:700px){main{padding:12px}header,section{padding:18px}h1{font-size:25px}}</style></head><body><main><header>
<h1>Independent trading research · offline evaluation</h1><span class="badge">SIMULATED ONLY</span><span class="badge">AUTOMATION AUTHORITY OFF</span><span class="badge">FINAL HOLDOUT UNSCORED</span><p>''' + text(plan["plan_id"]) + ' · ' + text(plan["trial_registry"]["trial_id"]) + ' · ' + text(event.recorded_at) + '''. Current runtime status is checked separately.</p></header>
<section><h2>Research declaration</h2><p>''' + text(plan["strategy"]["hypothesis"]) + '</p><p>' + text(plan["strategy"]["expected_edge"]) + '''</p><p class="note">This foundation evaluates externally supplied research decisions. It implements no trading strategy, imports no Galactica rules, and supplies no optimal symbol or size. Simulation results are not realized trade P&amp;L, authorization or executable orders.</p></section>
<section><h2>Per-fold simulated outcomes</h2><div class="table"><table><thead><tr><th>Fold</th><th>Status</th><th>Net return</th><th>Simulated total P&amp;L · USD</th><th>Close drawdown</th><th>Fills</th><th>Rejections</th><th>Modeled cost · USD</th></tr></thead><tbody>''' + ''.join(rows) + '''</tbody></table></div><p>Each fold resets its declared simulated cash. There is no aggregated portfolio return. CASH is an arithmetic baseline, not a risk-matched proof of alpha. Missing metrics remain unassessed.</p></section>
<section><h2>Explicit decision dispositions</h2><div class="table"><table><thead><tr><th>Fold</th><th>Research decision</th><th>Disposition</th><th>Reason</th></tr></thead><tbody>''' + ''.join(ledgers) + '''</tbody></table></div><p>Accepted sizes are externally supplied. No automatic sizing, stops, liquidation, order transmission or policy selection occurs. Fill assumptions are daily next-open, long-only and whole quantity; DAY horizons defer.</p></section>
<section><h2>Validation and research boundaries</h2><ul>''' + limitations + '''</ul><p>Training-label availability is projected and purged, not evidence of a fitted model. Final holdout scoring is withheld; files are not access sealed. Registration freezes inputs before local evaluation records but does not authenticate prospective preregistration or all research conducted elsewhere.</p><p>The Brigade consistency review remains a separate optional diagnostic branch; this engine consumes no Brigade votes. Investment authority, ownership and recorded paper budgets are untouched.</p></section>
<section><details><summary>Complete retained result and provenance</summary><pre>''' + text(json.dumps(result, sort_keys=True, indent=2)) + '</pre><ul>' + sources + '''</ul></details></section><footer>BlackPod · passive journal v12 · ''' + text(event.event_id) + ''' · Every authority remains disabled.</footer></main></body></html>'''


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        store = JournalStore(args.journal_root)
        events, blobs = store.verified_contents() if store.root.exists() else ((), {})
        if args.command == "verify":
            output = store.verify().to_dict()
        elif args.command in {"show", "render"}:
            event = next((row for row in events if row.event_id == args.event_id and row.event_type in {PLAN_TYPE, EVALUATION_TYPE}), None)
            if event is None:
                raise ValueError("unknown verified offline research event")
            if args.command == "show":
                output = event.to_dict()
            else:
                raw = render_research_review(event).encode("utf-8")
                _write(args.output, raw, (store.root,))
                output = {"path": str(args.output.absolute()), "sha256": sha256_bytes(raw)}
        else:
            plan = TradingResearchPlan.from_bytes(read_regular(args.plan))
            check_separate_root(store.root, args.plan.parent)
            if args.evidence_root is not None:
                check_separate_root(store.root, args.evidence_root)
                if plan.schema_version == "blackpod.trading_research_plan.v2":
                    from .trading_research_intake_cli import load_intake_evidence
                    from .contracts.trading_research import TradingResearchDataset
                    blobs = load_intake_evidence(args.evidence_root, _references(plan.to_dict()), blobs)
                    dataset = TradingResearchDataset.from_bytes(blobs[plan.dataset_evidence["sha256"]])
                    blobs = load_intake_evidence(args.evidence_root, dataset.provenance["source_evidence"], blobs)
                else:
                    blobs = load_evidence(args.evidence_root, _references(plan.to_dict()), blobs)
            if args.command == "evaluate":
                output = {"plan_id": plan.plan_id, "result": assess_registered_research(plan, events, blobs)}
            else:
                event = build_plan_event(plan, events, blobs) if args.command == "register" else build_evaluation_event(
                    plan, events, blobs, evaluation_id=args.evaluation_id, recorded_at=args.recorded_at)
                appended = store.append(event, evidence_for_research(plan, blobs))
                output = {"event_id": event.event_id, "decision_id": event.decision_id,
                    "plan_id": plan.plan_id, "trial_id": plan.trial_registry["trial_id"],
                    "written": appended.written, "sequence": appended.sequence}
        print(json.dumps({"command": args.command, **output, "orders_submitted": 0,
            "provider_calls": 0, "auto_trading_changed": False}, sort_keys=True))
        return 0
    except (ValueError, OSError, JournalStoreError, RecoveryError, TypeError, KeyError, RecursionError) as exc:
        print("trading-research: " + str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__": raise SystemExit(main())
