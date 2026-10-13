"""Wholly synthetic, externally authored trading research inputs and replay.

Fixed decisions demonstrate simulator behavior; they are not a trading
algorithm, signal, economic forecast, or recommendation for a real symbol.
No native strategy, credential source, provider, broker or model is used.
"""
from __future__ import annotations

import argparse
from decimal import Decimal
import json
from pathlib import Path
import sys

from .contracts.trading_research import TradingResearchDataset, TradingResearchIntents, TradingResearchPlan
from .decision_journal_store import JournalStore, JournalStoreError, check_separate_root
from .hashing import canonical_json_bytes, sha256_bytes
from .sentry_history_cache import RecoveryError

SCHEMA_VERSION = "blackpod.synthetic_trading_research_example.v1"
SYMBOLS = ["SYNTHA", "SYNTHB"]
REGISTERED_AT = "2026-01-22T22:00:00Z"
EVALUATED_AT = "2026-01-22T23:00:00Z"
EVALUATION_ID = "synthetic-independent-trading-evaluation"


def _authority():
    return {"authorization_enabled": False, "capital_activation_enabled": False,
            "execution_enabled": False, "policy_changes_enabled": False}


def example_material():
    """Build deterministic data and declared decisions without fitting a strategy."""
    from .trading_research_journal import build_evaluation_event, build_plan_event

    days = ["2026-01-05", "2026-01-06", "2026-01-07", "2026-01-08", "2026-01-09", "2026-01-12",
            "2026-01-13", "2026-01-14", "2026-01-15", "2026-01-16", "2026-01-20", "2026-01-21"]
    prices = ["95", "96", "97", "98", "99", "100", "100", "100", "100", "102", "103", "104"]
    sessions = []
    for index, (day, price) in enumerate(zip(days, prices)):
        bars = []
        for symbol, opening in zip(SYMBOLS, (price, "50")):
            number = Decimal(opening)
            bars.append({"symbol": symbol, "open": opening, "high": str(number + 1),
                         "low": str(number - 1), "close": str(number + Decimal("0.5")), "volume": "10000"})
        sessions.append({"session_id": "synthetic-session-" + str(index).zfill(2),
            "open_at": day + "T14:30:00Z", "close_at": day + "T21:00:00Z",
            "available_at": day + "T21:01:00Z", "bars": bars})

    evidence, blobs = {}, {}

    def retain(path, value):
        raw = canonical_json_bytes(value)
        evidence[path], blobs[sha256_bytes(raw)] = raw, raw
        return {"path": path, "sha256": sha256_bytes(raw), "size_bytes": len(raw)}

    source_ref = retain("market/synthetic-source.json", {
        "schema_version": "blackpod.synthetic_trading_market_source.v1", "data_status": "SYNTHETIC_FIXTURE",
        "declaration": "Entirely authored prices, dates and availability; not provider observations or a verified exchange calendar.",
        "sessions": sessions})
    dataset = TradingResearchDataset.from_mapping({"schema_version": "blackpod.trading_research_dataset.v1",
        "dataset_id": "synthetic-independent-trading-data", "recorded_at": "2026-01-21T22:00:00Z",
        "universe": SYMBOLS, "provenance": {"source_kind": "SYNTHETIC_FIXTURE", "source_evidence": [source_ref],
            "timestamp_policy": "SYNTHETIC_DECLARED", "historical_point_in_time_verified": False},
        "sessions": sessions, "authority": _authority()})
    dataset_ref = retain("research/dataset.json", dataset.to_dict())
    plan_id = "synthetic-independent-trading-plan"

    def decision(identity, source, minute, action, symbol, qty):
        return {"decision_id": identity, "fold_id": "synthetic-fold-1", "source_session_id": sessions[source]["session_id"],
            "decision_at": days[source] + "T21:" + str(minute).zfill(2) + ":00Z", "action": action, "symbol": symbol, "qty": qty}

    intents = TradingResearchIntents.from_mapping({"schema_version": "blackpod.trading_research_intents.v1",
        "intent_set_id": "synthetic-external-trading-intents", "plan_id": plan_id,
        "created_at": "2026-01-21T22:01:00Z", "origin": "EXTERNALLY_AUTHORED_RESEARCH_ONLY",
        "decisions": [decision("synthetic-buy-2", 7, 2, "BUY", "SYNTHA", "2"),
            decision("synthetic-oversize-reject", 7, 3, "BUY", "SYNTHB", "10000"),
            decision("synthetic-hold", 8, 2, "HOLD", "SYNTHA", "0"),
            decision("synthetic-partial-exit", 8, 3, "SELL", "SYNTHA", "1"),
            decision("synthetic-final-exit", 9, 2, "SELL", "SYNTHA", "1")], "authority": _authority()})
    intents_ref = retain("research/intents.json", intents.to_dict())
    plan = TradingResearchPlan.from_mapping({"schema_version": "blackpod.trading_research_plan.v1", "plan_id": plan_id,
        "experiment_id": "synthetic-independent-trading-experiment", "registered_at": REGISTERED_AT, "domain": "TRADING",
        "mode": "OFFLINE_SIMULATION", "scope": "DEVELOPMENT_EVALUATION_ONLY",
        "strategy": {"strategy_id": "synthetic-authored-accounting-demonstration", "version": "1",
            "hypothesis": "Authored synthetic entry and partial exits demonstrate simulator accounting; no market edge is hypothesized.",
            "expected_edge": "No economic edge claimed; synthetic outcomes are constructed for deterministic tests.",
            "falsification_conditions": ["A future-source fill, rejected-size fill, or inconsistent cash/lot accounting invalidates this demonstration."],
            "ancestry": "INDEPENDENT_NEW_RESEARCH_SPECIFICATION", "implementation_status": "EXTERNAL_INTENTS_ONLY"},
        "universe": SYMBOLS, "horizon": {"kind": "SWING", "max_holding_sessions": 5, "label_horizon_sessions": 1},
        "dataset_evidence": dataset_ref, "intents_evidence": intents_ref,
        "protocol": {"folds": [{"fold_id": "synthetic-fold-1", "train": {"start_index": 0, "end_index": 3},
            "validation": {"start_index": 5, "end_index": 6}, "test": {"start_index": 8, "end_index": 10}}],
            "embargo_sessions": 1, "final_holdout": {"start_index": 11, "end_index": 11}},
        "cost_model": {"spread_bps": "10", "slippage_bps": "5", "fee_bps": "0", "fee_per_fill": "0.10"},
        "risk": {"initial_cash": "1000", "max_order_notional": "300", "max_position_fraction": "0.5",
            "max_gross_exposure_fraction": "0.5", "max_volume_participation_fraction": "0.1", "max_staleness_seconds": 604800},
        "benchmark": {"kind": "CASH"}, "trial_registry": {"trial_id": "synthetic-trading-trial-1", "prior_trial_ids": []},
        "auto_trading_enabled": False, "authority": _authority()})
    plan_event = build_plan_event(plan, (), blobs)
    evaluation_event = build_evaluation_event(plan, (plan_event,), blobs, evaluation_id=EVALUATION_ID, recorded_at=EVALUATED_AT)
    result = evaluation_event.payload["result"]
    return {"plan": plan, "dataset": dataset, "intents": intents, "evidence": evidence, "blobs": blobs,
        "result": result, "plan_event": plan_event, "evaluation_event": evaluation_event,
        "expected_ids": {"plan_event_id": plan_event.event_id, "evaluation_event_id": evaluation_event.event_id}}


def prepare_example(output_root):
    """Publish synthetic inputs/expected replay and register only their plan."""
    from .auto_trading_runtime import RuntimeLedger
    from .decision_journal_store import _check_existing_ancestors, _reject_source_storage
    from .desk_candidate_review_cli import _write
    from .trading_research_journal import evidence_for_research

    output = Path(output_root).absolute()
    _check_existing_ancestors(output); _reject_source_storage(output)
    RuntimeLedger(output)  # Read-only path protection, never runtime activation.
    input_root, evidence_root, journal_root = output / "input", output / "evidence", output / "journal"
    check_separate_root(input_root, journal_root)
    check_separate_root(evidence_root, journal_root)
    material = example_material()
    for path, raw in material["evidence"].items():
        _write(evidence_root / path, raw, (journal_root,))
    _write(input_root / "plan.json", material["plan"].to_bytes(), (journal_root,))
    _write(output / "expected-result.json", canonical_json_bytes(material["result"]), ())
    _write(output / "expected-ids.json", canonical_json_bytes(material["expected_ids"]), ())
    seed = JournalStore(journal_root).append(material["plan_event"], evidence_for_research(material["plan"], material["blobs"]))
    manifest = {"schema_version": SCHEMA_VERSION, "data_status": "SYNTHETIC_FIXTURE",
        "observations": "FIXED_AUTHORED_PRICES_DATES_AND_DECISIONS_NOT_CURRENT_MARKET_DATA_OR_A_TRADING_STRATEGY",
        "symbols": SYMBOLS, "session_count": 12, "candidate_decision_count": 5,
        "plan_path": "input/plan.json", "evidence_root": "evidence", "journal_root": "journal",
        "evaluation_id": EVALUATION_ID, "evaluation_recorded_at": EVALUATED_AT, "expected_ids": material["expected_ids"],
        "initial_simulated_cash": "1000", "recorded_paper_budgets_used": False,
        "orders_submitted": 0, "provider_calls": 0, "model_inference_calls": 0,
        "auto_trading_changed": False, "auto_trading_enabled": False, "authority": _authority()}
    _write(output / "example.json", canonical_json_bytes(manifest), ())
    return {**manifest, "output_root": str(output), "seed_written": seed.written, "seed_sequence": seed.sequence,
            "evidence_files": len(material["evidence"])}


def main(argv=None):
    parser = argparse.ArgumentParser(description="Prepare wholly synthetic independent trading research; no strategy, provider or execution")
    parser.add_argument("--output-root", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        print(json.dumps(prepare_example(args.output_root), sort_keys=True))
        return 0
    except (ValueError, OSError, TypeError, KeyError, RecursionError, JournalStoreError, RecoveryError) as exc:
        print("trading-research-example: " + str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
