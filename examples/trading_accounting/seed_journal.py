"""Seed only the committed synthetic accounting prelude; never execution."""
import argparse
import json
from pathlib import Path

from blackpod_build_week.contracts.decision_journal import JournalEvent
from blackpod_build_week.contracts.mission_request import parse_strict_json_object_bytes
from blackpod_build_week.decision_journal_store import JournalStore, check_separate_root
from blackpod_build_week.hashing import sha256_bytes
from blackpod_build_week.sentry_history_cache import read_regular


def main(argv=None):
    parser = argparse.ArgumentParser(description="Retain the synthetic FIFO accounting prelude; no broker or worker")
    parser.add_argument("--journal-root", type=Path, required=True)
    args = parser.parse_args(argv)
    fixture_root = Path(__file__).resolve().parents[2] / "fixtures/trading_accounting"
    check_separate_root(args.journal_root, fixture_root)
    fixture = parse_strict_json_object_bytes(read_regular(fixture_root / "prelude.fixture.json"))
    if set(fixture) != {"schema_version", "events", "evidence_by_sha256"} or fixture["schema_version"] != "blackpod.paper_accounting_prelude.fixture.v1":
        raise ValueError("unsupported accounting prelude fixture")
    blobs = {digest: raw.encode("utf-8") for digest, raw in fixture["evidence_by_sha256"].items()}
    if any(sha256_bytes(raw) != digest for digest, raw in blobs.items()):
        raise ValueError("fixture evidence digest mismatch")
    store = JournalStore(args.journal_root)
    for item in fixture["events"]:
        event = JournalEvent.from_mapping(item)
        if event.event_type == "PAPER_BROKER_SNAPSHOT_RECORDED" and event.payload["snapshot"]["capture_provenance"]["source_kind"] != "SYNTHETIC_FIXTURE":
            raise ValueError("prelude must contain synthetic source observations")
        store.append(event, blobs)
    print(json.dumps({**store.verify().to_dict(), "orders_submitted": 0, "auto_trading_changed": False}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
