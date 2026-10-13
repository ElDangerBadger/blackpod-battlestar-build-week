"""Explicit offline hypothesis freeze, retained history intake and quality plans.

This module has no capture client, credential access or strategy producer.
"""
import argparse
import json
from pathlib import Path
import sys

from .contracts.historical_intake import HistoricalIntakeRequest, HistoricalIntakeExport
from .contracts.trading_research import TradingResearchPlan, TradingResearchIntents
from .contracts.trading_hypothesis import TradingHypothesisCatalog
from .decision_journal_store import JournalStore, JournalStoreError, check_separate_root
from .desk_candidate_review_cli import _references, _write
from .hashing import sha256_bytes
from .sentry_history_cache import read_regular, RecoveryError
from .trading_historical_intake import build_historical_intake, verify_historical_intake
from .trading_hypotheses import catalog_hypotheses, catalog_documents, hypothesis_research_strategy
from .trading_research_intake_journal import (
    build_catalog_event, catalog_evidence, build_intake_event, intake_evidence, CATALOG_TYPE, INTAKE_TYPE,
)


def _reference(path, raw):
    return {"path": path, "sha256": sha256_bytes(raw), "size_bytes": len(raw)}


def load_intake_evidence(root, references, retained=None):
    """Load only schema-declared leaves; calendar JSON is legitimately a list.

    The strict intake parser subsequently validates every source. No arbitrary
    reference discovery inside raw provider bodies is necessary or permitted.
    """
    from .decision_journal_store import _check_existing_ancestors
    from .contracts.trading_reconciliation import evidence_reference
    root = Path(root).absolute()
    _check_existing_ancestors(root)
    blobs = dict(retained or {})
    for reference in references:
        reference = evidence_reference(reference)
        raw = blobs.get(reference["sha256"])
        if raw is None:
            path = root / reference["path"]
            _check_existing_ancestors(path.parent)
            raw = read_regular(path)
        if len(raw) != reference["size_bytes"] or sha256_bytes(raw) != reference["sha256"]:
            raise ValueError("historical input evidence differs in hash or size")
        blobs[reference["sha256"]] = raw
    return blobs


def make_plan(hypothesis, dataset, blobs, *, registered_at, experiment_id, plan_id):
    """Prepare empty-intent quality plans; sizing/costs are uncalibrated placeholders.

    Partition fractions and three-session gaps are fixed design choices. No
    prices, forecasts, outcomes or budget policies choose the protocol.
    """
    def disabled_authority():
        return {field: False for field in ("authorization_enabled", "capital_activation_enabled", "execution_enabled", "policy_changes_enabled")}
    n = len(dataset.sessions)
    if n < 40:
        raise ValueError("quality plan preparation requires at least forty retained sessions")
    components = hypothesis_research_strategy(hypothesis)
    evidence = {
        "historical-intake/dataset.v2.json": dataset.to_bytes(),
        "trading-hypotheses/" + hypothesis.hypothesis_id + ".v1.json": hypothesis.to_bytes(),
    }
    intents = TradingResearchIntents.from_mapping({"schema_version": "blackpod.trading_research_intents.v1",
        "intent_set_id": plan_id + "-empty-intents", "plan_id": plan_id, "created_at": registered_at,
        "origin": "EXTERNALLY_AUTHORED_RESEARCH_ONLY", "decisions": [], "authority": disabled_authority()})
    intents_path = "trading-research/" + plan_id + ".empty-intents.v1.json"
    evidence[intents_path] = intents.to_bytes()
    refs = {path: _reference(path, raw) for path, raw in evidence.items()}
    hypothesis_path = "trading-hypotheses/" + hypothesis.hypothesis_id + ".v1.json"
    plan = TradingResearchPlan.from_mapping({
        "schema_version": "blackpod.trading_research_plan.v2", "plan_id": plan_id,
        "experiment_id": experiment_id, "registered_at": registered_at, "domain": "TRADING",
        "mode": "OFFLINE_SIMULATION", "scope": "DEVELOPMENT_EVALUATION_ONLY",
        **components, "universe": dataset.universe,
        "dataset_evidence": refs["historical-intake/dataset.v2.json"], "intents_evidence": refs[intents_path],
        "frozen_hypothesis_evidence": refs[hypothesis_path], "evaluation_purpose": "DATA_QUALITY_ONLY",
        "protocol": {"folds": [{"fold_id": "development-fold-1",
            "train": {"start_index": 0, "end_index": n * 3 // 10 - 1},
            "validation": {"start_index": n * 3 // 10 + 3, "end_index": n // 2 - 1},
            "test": {"start_index": n // 2 + 3, "end_index": n * 4 // 5 - 1}}],
            "embargo_sessions": 3, "final_holdout": {"start_index": n * 4 // 5 + 3, "end_index": n - 1}},
        "cost_model": {"spread_bps": "10", "slippage_bps": "5", "fee_bps": "0", "fee_per_fill": "0.10"},
        "risk": {"initial_cash": "1000", "max_order_notional": "100", "max_position_fraction": "0.1",
            "max_gross_exposure_fraction": "0.2", "max_volume_participation_fraction": "0.01",
            "max_staleness_seconds": 604800},
        "benchmark": {"kind": "CASH"}, "trial_registry": {"trial_id": plan_id + "-trial-1", "prior_trial_ids": []},
        "auto_trading_enabled": False, "authority": disabled_authority()})
    merged = dict(blobs)
    merged.update({sha256_bytes(raw): raw for raw in evidence.values()})
    return {"plan": plan, "intents": intents, "evidence": evidence, "blobs": merged}


def build_parser():
    parser = argparse.ArgumentParser(description="Passive offline historical intake and independent hypothesis specifications")
    commands = parser.add_subparsers(dest="command", required=True)
    sub = commands.add_parser("freeze-hypotheses")
    sub.add_argument("--recorded-at", required=True); sub.add_argument("--author-id", required=True)
    sub.add_argument("--catalog-id", default="independent-trading-hypotheses-v1")
    sub.add_argument("--output-directory", type=Path, required=True)
    sub.add_argument("--journal-root", type=Path, required=True)
    sub = commands.add_parser("export")
    sub.add_argument("--request", type=Path, required=True); sub.add_argument("--evidence-root", type=Path, required=True)
    sub.add_argument("--output-directory", type=Path, required=True)
    for name in ("verify-export", "record-intake"):
        sub = commands.add_parser(name)
        sub.add_argument("--export", type=Path, required=True); sub.add_argument("--evidence-root", type=Path, required=True)
        if name == "record-intake":
            sub.add_argument("--journal-root", type=Path, required=True); sub.add_argument("--recorded-at", required=True)
    sub = commands.add_parser("prepare-plans")
    sub.add_argument("--journal-root", type=Path, required=True)
    sub.add_argument("--catalog-event-id", required=True); sub.add_argument("--intake-event-id", required=True)
    sub.add_argument("--registered-at", required=True); sub.add_argument("--output-directory", type=Path, required=True)
    sub.add_argument("--id-prefix", required=True)
    return parser


def _publish(evidence, output, protected=()):
    for path, raw in evidence.items():
        _write(output / path, raw, protected)


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        if args.command == "freeze-hypotheses":
            store = JournalStore(args.journal_root)
            check_separate_root(store.root, args.output_directory)
            catalog = catalog_hypotheses(args.recorded_at, args.author_id, catalog_id=args.catalog_id)
            evidence = catalog_evidence(catalog)
            event = build_catalog_event(catalog)
            _publish(evidence, args.output_directory, (store.root,))
            appended = store.append(event, evidence)
            result = {"event_id": event.event_id, "written": appended.written, "hypotheses": len(catalog.hypotheses)}
        elif args.command == "export":
            check_separate_root(args.output_directory, args.evidence_root)
            check_separate_root(args.output_directory, args.request.parent)
            request = HistoricalIntakeRequest.from_bytes(read_regular(args.request))
            blobs = load_intake_evidence(args.evidence_root, _references(request.to_dict()), {})
            material = build_historical_intake(request, blobs)
            evidence = dict(material["evidence"])
            evidence["historical-intake/export.v1.json"] = material["export"].to_bytes()
            _publish(evidence, args.output_directory, (args.evidence_root, args.request.parent))
            result = {"intake_id": material["export"].intake_id, "coverage": material["export"].coverage}
        elif args.command in {"verify-export", "record-intake"}:
            export = HistoricalIntakeExport.from_bytes(read_regular(args.export))
            blobs = load_intake_evidence(args.evidence_root, _references(export.to_dict()), {})
            material = verify_historical_intake(export, blobs)
            result = {"intake_id": export.intake_id, "coverage": export.coverage, "verified": True}
            if args.command == "record-intake":
                store = JournalStore(args.journal_root)
                check_separate_root(store.root, args.evidence_root); check_separate_root(store.root, args.export.parent)
                event = build_intake_event(export, blobs, recorded_at=args.recorded_at)
                appended = store.append(event, intake_evidence(export, blobs))
                result.update(event_id=event.event_id, written=appended.written)
        else:
            store = JournalStore(args.journal_root)
            check_separate_root(store.root, args.output_directory)
            events, blobs = store.verified_contents()
            catalog_event = next((e for e in events if e.event_id == args.catalog_event_id and e.event_type == CATALOG_TYPE), None)
            intake_event = next((e for e in events if e.event_id == args.intake_event_id and e.event_type == INTAKE_TYPE), None)
            if catalog_event is None or intake_event is None:
                raise ValueError("preparation requires verified catalog and intake event identities")
            catalog = TradingHypothesisCatalog.from_mapping(catalog_event.payload["catalog"])
            dataset = verify_historical_intake(intake_event.payload["export"], blobs)["dataset"]
            plans = []
            from .trading_research_journal import build_plan_event
            for index, hypothesis in enumerate(catalog_documents(catalog), 1):
                prefix = args.id_prefix + "-h" + str(index)
                material = make_plan(hypothesis, dataset, blobs, registered_at=args.registered_at,
                                     experiment_id=prefix + "-experiment", plan_id=prefix + "-plan")
                # Check exact source linkage before publishing even an unregistered plan.
                build_plan_event(material["plan"], events, material["blobs"])
                evidence = dict(material["evidence"])
                evidence["trading-research/" + prefix + ".plan.v2.json"] = material["plan"].to_bytes()
                _publish(evidence, args.output_directory, (store.root,))
                plans.append({"plan_id": material["plan"].plan_id, "path": str((args.output_directory / "trading-research" / (prefix + ".plan.v2.json")).absolute())})
            result = {"plans": plans, "evaluation_purpose": "DATA_QUALITY_ONLY", "strategy_producers": 0}
        print(json.dumps({"command": args.command, **result, "orders_submitted": 0,
            "provider_calls": 0, "auto_trading_changed": False}, sort_keys=True))
        return 0
    except (ValueError, OSError, JournalStoreError, RecoveryError, TypeError, KeyError, RecursionError) as exc:
        print("trading-research-intake: " + str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
