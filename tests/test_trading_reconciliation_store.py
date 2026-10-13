"""Immutable mixed-version paper observation chains, replay and recovery."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import shutil
import socket
import tempfile
import unittest
from unittest import mock

from test_investment_approval import ApprovalFixture
from test_trading_reconciliation_engine import ReconciliationFixture, LATER
from blackpod_build_week.contracts.decision_journal import JournalEvent
from blackpod_build_week.contracts.trading_automation import TradingAutomationControl
from blackpod_build_week.contracts.trading_reconciliation import TradingReconciliationInput
from blackpod_build_week.decision_journal_store import (
    JournalStore, JournalConflictError, JournalVerificationError, JournalPersistenceError,
    _publish_immutable,
)
from blackpod_build_week.hashing import canonical_json_bytes, sha256_bytes
from blackpod_build_week.trading_automation import build_automation_event, evidence_for_automation
from blackpod_build_week import trading_reconciliation as engine


class TradingReconciliationStoreTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(mock.patch.object(socket.socket, "connect", side_effect=AssertionError("network forbidden")))
        self.enterContext(mock.patch("subprocess.Popen", side_effect=AssertionError("executor forbidden")))
        self.enterContext(mock.patch("subprocess.run", side_effect=AssertionError("producer forbidden")))
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.base = Path(directory.name).resolve()
        self.store = JournalStore(self.base / "journal")
        self.legacy = ApprovalFixture()
        self.addCleanup(self.legacy.close)
        for event in self.legacy.events:
            self.store.append(event, self.legacy.blobs)
        control = TradingAutomationControl.from_mapping({
            "schema_version": "blackpod.trading_automation_control.v1", "control_id": "store-fixture-off",
            "operator_id": "fixture-operator", "recorded_at": "2026-10-12T00:00:00Z", "switch_id": "auto-trading",
            "requested_enabled": False, "scope": "TRADING_CONTROL_INTENT_ONLY", "domain": "TRADING",
            "execution_mode": "DISABLED", "origin": "SIMULATED_TEST",
        })
        self.store.append(build_automation_event(control), evidence_for_automation(control))
        self.fixture = ReconciliationFixture()
        self.addCleanup(self.fixture.close)
        for event in self.fixture.events:
            self.store.append(event, self.fixture.blobs)
        self.baseline_events, self.baseline_blobs = self.store.verified_contents()
        self.original = {path.name: path.read_bytes() for path in (self.store.root / "entries").iterdir()}

    def reconciliation_event(self, document=None, *, events=None):
        current, retained = self.store.verified_contents()
        prefix = current if events is None else events
        blobs = {**self.fixture.blobs, **retained}
        document = document or self.fixture.reconciliation
        return (engine.build_reconciliation_event(document, prefix, blobs),
                engine.evidence_for_reconciliation(document, prefix, blobs))

    def append_later_observation(self, prior_event):
        snapshot = self.fixture.snapshot_for(snapshot_id="snapshot-later", captured_at=LATER,
            capture_window={"started_at": LATER, "completed_at": LATER})
        events, retained = self.store.verified_contents()
        blobs = {**self.fixture.blobs, **retained}
        snapshot_event = engine.build_snapshot_event(snapshot, events, blobs)
        self.store.append(snapshot_event, engine.evidence_for_snapshot(snapshot, events, blobs))
        document = self.fixture.reconciliation_for(reconciliation_id="reconciliation-later", recorded_at=LATER,
            broker_snapshot_event_id=snapshot_event.event_id, broker_snapshot_sha256=snapshot_event.source["source_sha256"],
            prior_reconciliation_event_id=prior_event.event_id)
        event, evidence = self.reconciliation_event(document)
        self.store.append(event, evidence)
        return event

    def assert_originals_unchanged(self):
        for name, raw in self.original.items():
            self.assertEqual((self.store.root / "entries" / name).read_bytes(), raw)

    def rehash_last_entry(self, mutation):
        path = self.store.root / "entries" / f"{self.store.verify().event_count:08d}.json"
        entry = json.loads(path.read_bytes())
        mutation(entry["event"])
        entry["event_sha256"] = sha256_bytes(JournalEvent.from_mapping(entry["event"]).to_bytes())
        path.chmod(0o600)
        path.write_bytes(canonical_json_bytes(entry))

    def test_mixed_v1_through_v6_chain_roundtrip_preserves_original_bytes(self):
        event, evidence = self.reconciliation_event()
        result = self.store.append(event, evidence)
        self.assertTrue(result.written)
        events, blobs = self.store.verified_contents()
        self.assertEqual({item.schema_version for item in events}, {
            "blackpod.decision_journal_event.v" + str(version) for version in range(1, 7)})
        self.assertEqual(events[-1].to_bytes(), event.to_bytes())
        self.assertEqual(self.store.verify().orphan_evidence_count, 0)
        self.assertEqual(blobs[event.source["source_sha256"]], self.fixture.reconciliation.to_bytes())
        self.assert_originals_unchanged()

    def test_all_three_v6_inputs_rebuild_and_retry_from_the_original_prefix(self):
        event, evidence = self.reconciliation_event()
        first = self.store.append(event, evidence)
        events, retained = self.store.verified_contents()
        blobs = {**self.fixture.blobs, **retained}
        for document, builder, evidence_builder, original in (
            (self.fixture.snapshot, engine.build_snapshot_event, engine.evidence_for_snapshot, self.fixture.snapshot_event),
            (self.fixture.ownership, engine.build_ownership_event, engine.evidence_for_ownership, self.fixture.ownership_event),
            (self.fixture.reconciliation, engine.build_reconciliation_event, engine.evidence_for_reconciliation, event),
        ):
            with self.subTest(kind=original.source["kind"]):
                rebuilt = builder(document, events, blobs)
                self.assertEqual(rebuilt.to_bytes(), original.to_bytes())
                repeated = self.store.append(rebuilt, evidence_builder(document, events, blobs))
                self.assertFalse(repeated.written)
        self.assertEqual(self.store.verify().event_count, first.sequence)
        self.assert_originals_unchanged()

    def test_changed_input_with_same_reconciliation_id_conflicts(self):
        event, evidence = self.reconciliation_event()
        self.store.append(event, evidence)
        changed = self.fixture.reconciliation.to_dict()
        changed["recorded_at"] = LATER
        document = TradingReconciliationInput.from_mapping(changed)
        different, supplied = self.reconciliation_event(document, events=self.baseline_events)
        self.assertEqual(different.event_id, event.event_id)
        with self.assertRaises(JournalConflictError):
            self.store.append(different, supplied)
        self.assert_originals_unchanged()

    def test_historical_retries_remain_identical_after_later_capture_and_reconciliation(self):
        event, evidence = self.reconciliation_event()
        self.store.append(event, evidence)
        later = self.append_later_observation(event)
        events, blobs = self.store.verified_contents()
        for document, builder, evidence_builder, original in (
            (self.fixture.snapshot, engine.build_snapshot_event, engine.evidence_for_snapshot, self.fixture.snapshot_event),
            (self.fixture.ownership, engine.build_ownership_event, engine.evidence_for_ownership, self.fixture.ownership_event),
            (self.fixture.reconciliation, engine.build_reconciliation_event, engine.evidence_for_reconciliation, event),
        ):
            with self.subTest(kind=original.source["kind"]):
                rebuilt = builder(document, events, blobs)
                self.assertEqual(rebuilt.to_bytes(), original.to_bytes())
                self.assertFalse(self.store.append(rebuilt, evidence_builder(document, events, blobs)).written)
        self.assertEqual(self.store.events()[-1].to_bytes(), later.to_bytes())
        self.assert_originals_unchanged()

    def test_later_observation_preserves_cumulative_fill_and_explicit_prior_link(self):
        original, evidence = self.reconciliation_event()
        self.store.append(original, evidence)
        later = self.append_later_observation(original)
        retained = self.store.events()[-1]
        self.assertEqual(retained.payload["reconciliation"]["prior_reconciliation_event_id"], original.event_id)
        self.assertEqual(retained.payload["result"]["attempts"][0]["filled_qty"], "2")
        self.assertEqual(original.payload["result"]["attempts"][0]["filled_qty"], "2")
        self.assertIsNone(retained.payload["result"]["realized_trade_pnl"])
        self.assertEqual(retained.to_bytes(), later.to_bytes())
        self.assert_originals_unchanged()

    def test_rehashed_reconciliation_report_is_rejected_by_semantic_replay(self):
        event, evidence = self.reconciliation_event()
        self.store.append(event, evidence)
        self.rehash_last_entry(lambda value: value["payload"]["result"].update(status="PENDING"))
        with self.assertRaisesRegex(JournalVerificationError, "retained-source projection"):
            self.store.verify()
        self.assert_originals_unchanged()

    def test_rehashed_snapshot_event_identity_is_rejected_by_semantic_replay(self):
        fresh = JournalStore(self.base / "snapshot-only")
        fresh.append(self.fixture.snapshot_event, self.fixture.blobs)
        path = fresh.root / "entries" / "00000001.json"
        value = json.loads(path.read_bytes())
        value["event"]["event_id"] = "journal-event-" + "f" * 64
        value["event_sha256"] = sha256_bytes(JournalEvent.from_mapping(value["event"]).to_bytes())
        path.chmod(0o600)
        path.write_bytes(canonical_json_bytes(value))
        with self.assertRaisesRegex(JournalVerificationError, "retained-source projection"):
            fresh.verify()

    def test_rehashed_ownership_report_cannot_rewrite_the_declared_baseline(self):
        self.rehash_last_entry(lambda value: value["payload"]["assessment"].update(added_symbols=[]))
        with self.assertRaisesRegex(JournalVerificationError, "retained-source projection"):
            self.store.events()

    def test_wrong_paper_account_with_consistent_input_hash_is_rejected(self):
        event, evidence = self.reconciliation_event()
        value = event.to_dict()
        document = value["payload"]["reconciliation"]
        document["account_id"] = "another-paper-account"
        raw = TradingReconciliationInput.from_mapping(document).to_bytes()
        digest = sha256_bytes(raw)
        value["source"]["source_sha256"] = digest
        for reference in value["evidence"]:
            if reference["path"] == "trading/reconciliation.json":
                reference.update(sha256=digest, size_bytes=len(raw))
        candidate = JournalEvent.from_mapping(value)
        supplied = {**evidence, "trading/reconciliation.json": raw}
        with self.assertRaisesRegex(JournalVerificationError, "account"):
            self.store.append(candidate, supplied)
        self.assertEqual(self.store.verify().event_count, len(self.baseline_events))
        self.assert_originals_unchanged()

    def test_missing_snapshot_source_is_rejected_before_entry_publication(self):
        fresh = JournalStore(self.base / "missing-source")
        supplied = {"trading/snapshot.json": self.fixture.snapshot.to_bytes()}
        with self.assertRaisesRegex(JournalVerificationError, "missing or mismatched"):
            fresh.append(self.fixture.snapshot_event, supplied)
        self.assertEqual(fresh.verify().event_count, 0)
        self.assertEqual(fresh.verify().evidence_count, 0)

    def test_missing_runtime_evidence_is_rejected_before_entry_publication(self):
        event, evidence = self.reconciliation_event()
        del evidence[self.fixture.reconciliation.runtime_evidence["path"]]
        with self.assertRaisesRegex(JournalVerificationError, "missing or mismatched"):
            self.store.append(event, evidence)
        self.assertEqual(self.store.verify().event_count, len(self.baseline_events))
        self.assert_originals_unchanged()

    def test_interruption_before_reconciliation_commit_recovers_exactly_once(self):
        event, evidence = self.reconciliation_event()
        def interrupt(staging, target, name, raw):
            if name.endswith(".json"):
                raise JournalPersistenceError("injected precommit interruption")
            return _publish_immutable(staging, target, name, raw)
        with mock.patch("blackpod_build_week.decision_journal_store._publish_immutable", side_effect=interrupt):
            with self.assertRaises(JournalPersistenceError):
                self.store.append(event, evidence)
        before_retry = self.store.verify()
        self.assertEqual(before_retry.event_count, len(self.baseline_events))
        self.assertGreater(before_retry.orphan_evidence_count, 0)
        self.assertTrue(self.store.append(event, evidence).written)
        self.assertFalse(self.store.append(event, evidence).written)
        self.assertEqual(self.store.verify().orphan_evidence_count, 0)
        self.assert_originals_unchanged()

    def test_interruption_after_reconciliation_commit_recovers_as_a_noop(self):
        event, evidence = self.reconciliation_event()
        def interrupt(staging, target, name, raw):
            _publish_immutable(staging, target, name, raw)
            if name.endswith(".json"):
                raise JournalPersistenceError("injected postcommit interruption")
        with mock.patch("blackpod_build_week.decision_journal_store._publish_immutable", side_effect=interrupt):
            with self.assertRaises(JournalPersistenceError):
                self.store.append(event, evidence)
        self.assertEqual(self.store.verify().event_count, len(self.baseline_events) + 1)
        self.assertFalse(self.store.append(event, evidence).written)
        self.assert_originals_unchanged()

    def test_concurrent_identical_reconciliation_imports_commit_one_event(self):
        event, evidence = self.reconciliation_event()
        with ThreadPoolExecutor(max_workers=3) as pool:
            results = list(pool.map(lambda _: JournalStore(self.store.root).append(event, evidence), range(3)))
        self.assertEqual(sum(item.written for item in results), 1)
        self.assertEqual(len({item.sequence for item in results}), 1)
        self.assertEqual(self.store.verify().event_count, len(self.baseline_events) + 1)
        self.assert_originals_unchanged()

    def test_restored_journal_verifies_after_native_fixture_and_source_removal(self):
        event, evidence = self.reconciliation_event()
        self.store.append(event, evidence)
        restored = self.base / "restored"
        shutil.copytree(self.store.root, restored)
        self.fixture.close()
        self.legacy.close()
        copy_store = JournalStore(restored)
        self.assertEqual(copy_store.verify().to_dict(), self.store.verify().to_dict())
        self.assertEqual([item.to_bytes() for item in copy_store.events()], [item.to_bytes() for item in self.store.events()])
        report = copy_store.events()[-1].payload["result"]
        self.assertTrue(report["execution_observed"])
        self.assertIsNone(report["realized_trade_pnl"])

    def test_retained_runtime_prefix_corruption_cannot_be_masked_by_new_reports(self):
        event, evidence = self.reconciliation_event()
        self.store.append(event, evidence)
        digest = self.fixture.reconciliation.runtime_evidence["sha256"]
        path = self.store.root / "evidence" / digest
        path.chmod(0o600)
        capture = json.loads(path.read_bytes())
        capture["events"][0]["payload"]["entries_enabled"] = False
        path.write_bytes(canonical_json_bytes(capture))
        with self.assertRaisesRegex(JournalVerificationError, "evidence hash mismatch"):
            self.store.verify()

    def test_observed_paper_fill_cannot_enable_trading_or_capital_authority(self):
        event, evidence = self.reconciliation_event()
        self.store.append(event, evidence)
        report = self.store.events()[-1].payload["result"]
        self.assertTrue(report["execution_observed"])
        self.assertTrue(report["attributable_execution_observed"])
        self.assertFalse(report["execution_authority_granted"])
        self.assertFalse(report["readiness"])
        self.assertFalse(report["provider_verified"])
        self.assertFalse(report["ownership_authenticated"])
        self.assertIsNone(report["realized_trade_pnl"])
        self.assertTrue(all(value is False for value in report["authority"].values()))
        self.assertEqual({item["symbol"]: item["desk"] for item in report["positions"]}, {"MSFT": "TRADING", "AAPL": "INVESTMENT"})
        self.assert_originals_unchanged()


if __name__ == "__main__":
    unittest.main()
