"""Prepare an isolated, wholly synthetic offline two-desk review example.

Retained native source fixtures are reused without importing any test module,
starting a workflow, calling a provider, or installing trading configuration.
"""
from __future__ import annotations

import argparse
import base64
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys
import zlib

from .contracts.desk_candidate_review import DeskReviewInput
from .contracts.mission_request import parse_strict_json_object_bytes
from .contracts.trading_reconciliation import BrokerSnapshotInput
from .decision_journal_store import JournalStore, JournalStoreError, check_separate_root
from .desk_candidate_review import build_desk_review_event
from .hashing import canonical_json_bytes, sha256_bytes
from .paper_test_budget import build_paper_test_budget
from .sentry_history_cache import read_regular, RecoveryError
from .shadow_galactica_analysis import build_shadow_galactica_analysis, evidence_for_shadow_galactica_analysis
from .shadow_native_analysis import FLEET_SYMBOLS, MAX_SOURCE_BYTES, SOURCE_PINS, derive_native_analysis
from .trading_reconciliation import build_snapshot_event, evidence_for_snapshot

SCHEMA_VERSION = "blackpod.synthetic_desk_review_example.v1"
ACCOUNT_ID = "synthetic-example-paper-account"
CAPTURED_AT = "2026-10-12T19:00:01Z"
RECORDED_AT = "2026-10-12T20:00:00Z"
BRIGADE_TRANSCRIPT = """SYNTHETIC EXAMPLE: no real predictions, votes or performance.
Model: synthetic-example-legacy
Date: 2026-04-24
🔬 Analyzing XLK
📋 Blackwell Brigade Analysis:
 Blackwell_Scout: BUY (confidence=0.70)
 → Synthetic momentum opinion retained for import demonstration.
 Blackwell_Sentry: EXIT (confidence=0.80)
 → Synthetic risk dissent retained independently.
 Blackwell_Advisor: HOLD (confidence=0.60)
 → Synthetic macro uncertainty.
 Blackwell_Canary: WATCH (confidence=0.65)
 → Synthetic volume uncertainty.
 Blackwell_Pathfinder: HOLD (confidence=0.55)
 → Synthetic pattern uncertainty.
🏛️ Senate Vote:
 ✓ Sen. Momentum: LONG @ 0.60
 → Synthetic majority statement.
 ✗ Sen. Risk: HOLD @ 0.70
 → Synthetic disagreement preserved.
📊 DECISION: LONG @ 0.60
 Cohesion: 50% (1/2 agree)
 Dissent: Sen. Risk
============================================================
""".encode("utf-8")


def _authority():
    return {field: False for field in ("authorization_enabled", "capital_activation_enabled", "execution_enabled", "policy_changes_enabled")}


def _fixture_root():
    return Path(__file__).resolve().parents[2] / "fixtures"


def fixture_native_sources(fixture_root=None):
    """Read bounded byte-exact code fixtures; never search sibling checkouts."""
    root = Path(fixture_root) if fixture_root is not None else _fixture_root()
    bundle = parse_strict_json_object_bytes(read_regular(root / "shadow_native_analysis/source_bundle.v1.json"))
    encoded = bundle.get("sources")
    if not isinstance(encoded, dict) or set(encoded) != set(SOURCE_PINS):
        raise ValueError("synthetic example requires the complete pinned native source fixture")
    result = {}
    for path, text in encoded.items():
        try:
            decompressor = zlib.decompressobj()
            raw = decompressor.decompress(base64.b64decode(text, validate=True), MAX_SOURCE_BYTES + 1)
        except (ValueError, TypeError, zlib.error) as exc:
            raise ValueError("native source fixture encoding is invalid") from exc
        if len(raw) > MAX_SOURCE_BYTES or not decompressor.eof or decompressor.unused_data or sha256_bytes(raw) != SOURCE_PINS[path]:
            raise ValueError("native source fixture differs from the pinned bounded source")
        result[path] = raw
    return result


def example_material(fixture_root=None):
    """Return reproducible synthetic seed and proposed review, without writes."""
    root = Path(fixture_root) if fixture_root is not None else _fixture_root()
    evidence, blobs = {}, {}

    def retain(path, raw):
        evidence[path] = raw
        blobs[sha256_bytes(raw)] = raw
        return {"path": path, "sha256": sha256_bytes(raw), "size_bytes": len(raw)}

    source = {"schema_version": "blackpod.paper_broker_fixture.v1", "account_id": ACCOUNT_ID, "mode": "PAPER",
        "account": {"status": "ACTIVE", "trading_blocked": False, "account_blocked": False, "currency": "USD",
                    "equity": "81525.11", "cash": "81525.11", "buying_power": None}, "positions": [], "orders": [],
        "capture_window": {"started_at": "2026-10-12T00:00:00Z", "completed_at": "2026-10-12T00:00:00Z"},
        "completeness": {"positions_complete": True, "open_orders_complete": True, "tracked_orders_complete": True}}
    broker_ref = retain("broker/synthetic-source.json", canonical_json_bytes(source))
    snapshot = BrokerSnapshotInput.from_mapping({"schema_version": "blackpod.paper_broker_snapshot.v1", "snapshot_id": "synthetic-desk-example-baseline",
        "captured_at": "2026-10-12T00:00:00Z", **{key: source[key] for key in ("account_id", "mode", "account", "positions", "orders", "capture_window", "completeness")},
        "capture_provenance": {"source_kind": "SYNTHETIC_FIXTURE", "origin": "https://paper-api.alpaca.markets", "source_evidence": broker_ref,
            "sequential_capture": True, "snapshot_atomic": False, "provider_verified": False}, "authority": _authority()})
    seed_event = build_snapshot_event(snapshot, (), blobs)
    seed_evidence = evidence_for_snapshot(snapshot, (), blobs)
    budget = build_paper_test_budget(seed_event, budget_id="synthetic-desk-example-budget", recorded_at="2026-10-12T00:01:00Z", declared_by="synthetic-example-author")
    snapshots, bars = {}, {}
    start = datetime(2026, 8, 10, 4, tzinfo=timezone.utc)
    for symbol in FLEET_SYMBOLS:
        price = 102.0 if symbol == "XLK" else 100.0
        snapshots[symbol] = {"latestTrade": {"p": price, "t": "2026-10-12T19:00:00Z"},
            "latestQuote": {"bp": price - 0.01, "ap": price + 0.01, "t": "2026-10-12T19:00:00Z"},
            "dailyBar": {"o": 100.0, "h": 103.0, "l": 99.0, "c": price, "v": 100000, "t": "2026-10-12T04:00:00Z"},
            "prevDailyBar": {"o": 99.0, "h": 101.0, "l": 98.0, "c": 100.0, "v": 100000, "t": "2026-10-09T04:00:00Z"}}
        bars[symbol] = [{"t": (start + timedelta(days=i)).isoformat().replace("+00:00", "Z"),
            "o": 100, "h": 102, "l": 98, "c": 100, "v": 100000} for i in range(63)]
    market = {"schema_version": "blackpod.shadow_market_packet.v1", "captured_at": CAPTURED_AT, "feed": "IEX", "adjustment": "RAW",
        "snapshots": snapshots, "bars": bars, "source_evidence": [retain("shadow-desk/raw-snapshots.json", canonical_json_bytes(snapshots)),
            retain("shadow-desk/raw-bars.json", canonical_json_bytes({"bars": bars, "next_page_token": None}))]}
    native_sources = fixture_native_sources(root)
    native = derive_native_analysis(market, native_sources)
    for reference in native["source_evidence"]:
        # The native packet references its frozen whole-source closure.
        raw = next(raw for path, raw in native_sources.items() if sha256_bytes(raw) == reference["sha256"])
        retain(reference["path"], raw)
    spyglass = read_regular(root / "shadow_galactica_analysis/spyglass.py")
    parser = read_regular(root / "shadow_galactica_analysis/brigade_debrief.py")
    producer = read_regular(root / "shadow_galactica_analysis/blackwell_brigade.py")
    market_raw = canonical_json_bytes(market)
    galactica = build_shadow_galactica_analysis(market_raw, spyglass, generated_at=RECORDED_AT,
        brigade_transcript=BRIGADE_TRANSCRIPT, brigade_parser_source=parser, brigade_producer_source=producer, brigade_as_of="2026-04-24")
    for path, raw in evidence_for_shadow_galactica_analysis(market_raw, spyglass, brigade_transcript=BRIGADE_TRANSCRIPT,
            brigade_parser_source=parser, brigade_producer_source=producer).items():
        retain(path, raw)
    bundle = {"schema_version": "blackpod.shadow_analysis_bundle.v1", "native": native, "galactica": galactica,
        "source_evidence": list(native["source_evidence"]) + [ref for ref in galactica["source_evidence"].values() if ref is not None]}
    issuer = {"schema_version": "blackpod.shadow_issuer_facts.v1", "captured_at": CAPTURED_AT, "facts": [], "source_evidence": []}
    for symbol, asset_class, corporate_action in (("SPY", "BROAD_EQUITY", False), ("USMV", "LOW_VOL_EQUITY", False), ("QUAL", "FACTOR_EQUITY", True)):
        url = "https://www.ssga.com/fixture/" + symbol.lower()
        excerpt = "Synthetic example for " + symbol + "; not actual issuer research or a verified investment thesis."
        ref = retain("shadow-desk/issuer-source-" + symbol + ".json", canonical_json_bytes({"schema_version": "blackpod.public_issuer_source.v1",
            "source_url": url, "retrieved_at": CAPTURED_AT, "content": excerpt}))
        issuer["source_evidence"].append(ref)
        issuer["facts"].append({"symbol": symbol, "fund_name": "Synthetic " + symbol, "issuer": "Synthetic example issuer",
            "mandate": "Synthetic mandate for test coverage only", "structure": "ETF", "asset_class": asset_class,
            "corporate_action_before_horizon": corporate_action, "source_url": url, "as_of": "2026-10-12", "source_excerpt": excerpt, "source_evidence": ref})
    document = DeskReviewInput.from_mapping({"schema_version": "blackpod.shadow_two_desk_review.v1", "review_id": "synthetic-two-desk-example",
        "recorded_at": RECORDED_AT, "mode": "PAPER", "account_id": ACCOUNT_ID, "scope": "SHADOW_TWO_DESK_REVIEW_ONLY",
        "budget": {"proposal_evidence": retain("shadow-desk/budget.json", budget.to_bytes()), "source_snapshot_event_id": seed_event.event_id,
            "source_snapshot_sha256": seed_event.source["source_sha256"]},
        "sources": {"market_evidence": retain("shadow-desk/market.json", market_raw), "analysis_evidence": retain("shadow-desk/analysis.json", canonical_json_bytes(bundle)),
            "issuer_evidence": retain("shadow-desk/issuers.json", canonical_json_bytes(issuer))},
        "policy": {"status": "PROPOSED_SHADOW_ONLY", "max_entry_fraction": "0.10", "scenario_risk_fraction": "0.0025", "atr_multiple": "2",
            "price_buffer_fraction": "0.01", "investment_candidate_fraction": "0.20", "max_active_entries": 1, "max_completed_cycles": 1,
            "expires_at": "2026-10-13T20:00:00Z", "investment_horizon_days": 90, "benchmark_symbol": "SPY"}, "authority": _authority()})
    event = build_desk_review_event(document, (seed_event,), blobs)
    return {"review": document, "event": event, "seed_event": seed_event, "seed_evidence": seed_evidence, "evidence": evidence, "blobs": blobs}


def prepare_example(output_root, *, fixture_root=None):
    """Safely publish synthetic inputs and one seed journal event, idempotently."""
    from .desk_candidate_review_cli import _write
    from .decision_journal_store import _reject_source_storage, _check_existing_ancestors
    output = Path(output_root).absolute()
    fixtures = Path(fixture_root).absolute() if fixture_root is not None else _fixture_root()
    check_separate_root(output, fixtures)
    _check_existing_ancestors(output)
    _reject_source_storage(output)
    from .auto_trading_runtime import RuntimeLedger
    RuntimeLedger(output)  # Read-only rejection of journal/native/repository roots.
    material = example_material(fixtures)
    evidence_root, journal_root = output / "evidence", output / "journal"
    check_separate_root(evidence_root, journal_root)
    # Validate the entire material before creating any output.
    for path, raw in material["evidence"].items():
        _write(evidence_root / path, raw, (fixtures, journal_root))
    _write(output / "review.json", material["review"].to_bytes(), (fixtures,))
    _write(output / "expected-event-id.txt", (material["event"].event_id + "\n").encode("utf-8"), (fixtures,))
    result = JournalStore(journal_root).append(material["seed_event"], material["seed_evidence"])
    manifest = {"schema_version": SCHEMA_VERSION, "account_id": ACCOUNT_ID, "data_status": "SYNTHETIC_FIXTURE",
        "review_id": material["review"].review_id, "expected_event_id": material["event"].event_id,
        "authority": _authority(), "auto_trading_changed": False, "orders_submitted": 0,
        "journal_root": "journal", "review_path": "review.json", "evidence_root": "evidence"}
    _write(output / "example.json", canonical_json_bytes(manifest), (fixtures,))
    return {**manifest, "output_root": str(output), "seed_written": result.written, "seed_sequence": result.sequence,
            "evidence_files": len(material["evidence"])}


def main(argv=None):
    parser = argparse.ArgumentParser(description="Prepare wholly synthetic offline shadow desk review examples; never enable trading")
    parser.add_argument("--output-root", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        print(json.dumps(prepare_example(args.output_root), sort_keys=True))
        return 0
    except (ValueError, OSError, TypeError, RecursionError, JournalStoreError, RecoveryError) as exc:
        print("desk-review-example: " + str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__": raise SystemExit(main())
