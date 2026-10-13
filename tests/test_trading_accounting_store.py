"""Offline mixed-version accounting persistence, semantic replay, and recovery."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import copy
import json
import os
from pathlib import Path
import shutil
import socket
import tempfile
import unittest
from unittest import mock

from blackpod_build_week import trading_accounting as engine
from blackpod_build_week.contracts.decision_journal import JournalEvent
from blackpod_build_week.contracts.mission_request import ContractValidationError
from blackpod_build_week.contracts.trading_accounting import AccountingInput
from blackpod_build_week.contracts.trading_automation import TradingAutomationControl
from blackpod_build_week.decision_journal_projection import load_verified_history, project_history
from blackpod_build_week.decision_journal_store import (
    JournalStore, JournalConflictError, JournalVerificationError, JournalPersistenceError,
    JournalUnsafePathError, _publish_immutable,
)
from blackpod_build_week.hashing import canonical_json_bytes, sha256_bytes
from blackpod_build_week.trading_automation import build_automation_event, evidence_for_automation
import test_decision_journal_projection as projection_fixtures
from test_investment_approval import ApprovalFixture
from test_trading_accounting_engine import AccountingFixture, RECORDED, raw_fee


class TradingAccountingStoreTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(mock.patch.object(socket.socket, "connect", side_effect=AssertionError("network forbidden")))
        self.enterContext(mock.patch("subprocess.Popen", side_effect=AssertionError("executor forbidden")))
        self.enterContext(mock.patch("subprocess.run", side_effect=AssertionError("provider forbidden")))
        self.enterContext(mock.patch("blackpod_build_week.paper_account_probe.probe_paper_account", side_effect=AssertionError("broker probe forbidden")))
        self.enterContext(mock.patch("blackpod_build_week.galactica_trading_adapter.run_guarded_navigator", side_effect=AssertionError("native execution forbidden")))
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.base = Path(directory.name).resolve()
        self.store = JournalStore(self.base / "journal")
        self.f = AccountingFixture()
        self.addCleanup(self.f.close)
        for event in self.f.events:
            self.store.append(event, self.f.blobs)
        self.baseline, self.baseline_blobs = self.store.verified_contents()
        self.original = self.entry_bytes()

    def entry_bytes(self):
        return {path.name: path.read_bytes() for path in (self.store.root / "entries").iterdir()}

    def assert_originals_unchanged(self, originals=None):
        for name, raw in (originals or self.original).items():
            self.assertEqual((self.store.root / "entries" / name).read_bytes(), raw)

    def accounting_event(self, document=None, *, events=None, store=None):
        store = store or self.store
        current, retained = store.verified_contents()
        current = current if events is None else events
        blobs = {**self.f.blobs, **retained}
        document = document or self.f.accounting
        return (engine.build_accounting_event(document, current, blobs),
                engine.evidence_for_accounting(document, current, blobs))

    def append_accounting(self, document=None):
        event, evidence = self.accounting_event(document)
        result = self.store.append(event, evidence)
        return event, evidence, result

    def rehash_last_entry(self, mutation):
        path = self.store.root / "entries" / f"{self.store.verify().event_count:08d}.json"
        entry = json.loads(path.read_bytes())
        mutation(entry["event"])
        entry["event_sha256"] = sha256_bytes(JournalEvent.from_mapping(entry["event"]).to_bytes())
        path.chmod(0o600)
        path.write_bytes(canonical_json_bytes(entry))

    def candidate_with_input(self, changes):
        event, evidence = self.accounting_event()
        value = event.to_dict()
        document = AccountingInput.from_mapping({**value["payload"]["accounting"], **changes})
        raw = document.to_bytes()
        value["payload"]["accounting"] = document.to_dict()
        for field in ("start_snapshot_event_id", "end_reconciliation_event_id", "ownership_event_id"):
            value["payload"]["result"][field] = getattr(document, field)
        value["source"]["source_sha256"] = sha256_bytes(raw)
        for reference in value["evidence"]:
            if reference["path"] == engine.ACCOUNTING_EVIDENCE_PATH:
                reference.update(sha256=sha256_bytes(raw), size_bytes=len(raw))
        return JournalEvent.from_mapping(value), {**evidence, engine.ACCOUNTING_EVIDENCE_PATH: raw}

    def test_mixed_v1_through_v7_preserves_missions_and_existing_records(self):
        legacy = ApprovalFixture()
        self.addCleanup(legacy.close)
        mixed = JournalStore(self.base / "mixed")
        for event in legacy.events:
            mixed.append(event, legacy.blobs)
        control = TradingAutomationControl.from_mapping({
            "schema_version": "blackpod.trading_automation_control.v1", "control_id": "accounting-fixture-off",
            "operator_id": "fixture-operator", "recorded_at": RECORDED, "switch_id": "auto-trading",
            "requested_enabled": False, "scope": "TRADING_CONTROL_INTENT_ONLY", "domain": "TRADING",
            "execution_mode": "DISABLED", "origin": "SIMULATED_TEST",
        })
        mixed.append(build_automation_event(control), evidence_for_automation(control))
        for event in self.f.events:
            mixed.append(event, self.f.blobs)
        originals = {path.name: path.read_bytes() for path in (mixed.root / "entries").iterdir()}
        event, evidence = self.accounting_event(store=mixed)
        mixed.append(event, evidence)
        events = mixed.events()
        self.assertEqual({item.schema_version for item in events}, {"blackpod.decision_journal_event.v" + str(version) for version in range(1, 8)})
        self.assertEqual(events[-1].payload["result"]["realized_trade_pnl"], "15.92")
        for item in events:
            if item.event_type == "MISSION_SNAPSHOT_RECORDED":
                self.assertIsNone(item.payload.get("realized_trade_pnl"))
                self.assertEqual(item.payload["execution_status"], "NOT_EXECUTED")
        for name, raw in originals.items():
            self.assertEqual((mixed.root / "entries" / name).read_bytes(), raw)
        self.assertEqual(mixed.verify().orphan_evidence_count, 0)

    def test_append_retains_all_three_new_sources_as_readonly_immutable_bytes(self):
        event, evidence, result = self.append_accounting()
        self.assertTrue(result.written)
        self.assertEqual(result.sequence, len(self.baseline) + 1)
        events, blobs = self.store.verified_contents()
        self.assertEqual(events[-1].to_bytes(), event.to_bytes())
        self.assertEqual(set(evidence), {"trading/accounting.json", "trading/activities.json", "broker/activity-source.json"})
        for raw in evidence.values():
            digest = sha256_bytes(raw)
            self.assertEqual(blobs[digest], raw)
            self.assertEqual((self.store.root / "evidence" / digest).stat().st_mode & 0o777, 0o444)
        self.assert_originals_unchanged()

    def test_retry_after_late_fee_and_later_off_context_is_identical_noop(self):
        original_rows = copy.deepcopy(self.f.rows)
        self.f.set_activities([row for row in original_rows if row["activity_type"] == "FILL"], fees_complete=False)
        first_document = self.f.accounting_for()
        first, _, result = self.append_accounting(first_document)
        originals = self.entry_bytes()
        first_bytes = first.to_bytes()
        self.f.set_activities(original_rows + [raw_fee("late-fee", "sell-1", "0.5", "fill-sell-1")], activity_set_id="accounting-late-activities")
        later_document = self.f.accounting_for(accounting_id="accounting-late", prior_accounting_event_id=first.event_id)
        later, _, _ = self.append_accounting(later_document)
        self.assertIsNone(first.payload["result"]["realized_trade_pnl"])
        self.assertEqual(later.payload["result"]["realized_trade_pnl"], "15.42")
        control = TradingAutomationControl.from_mapping({
            "schema_version": "blackpod.trading_automation_control.v1", "control_id": "later-fixture-off",
            "operator_id": "fixture-operator", "recorded_at": RECORDED, "switch_id": "auto-trading",
            "requested_enabled": False, "scope": "TRADING_CONTROL_INTENT_ONLY", "domain": "TRADING",
            "execution_mode": "DISABLED", "origin": "SIMULATED_TEST",
        })
        self.store.append(build_automation_event(control), evidence_for_automation(control))
        rebuilt, retained = self.accounting_event(first_document)
        self.assertEqual(rebuilt.to_bytes(), first_bytes)
        retried = self.store.append(rebuilt, retained)
        self.assertFalse(retried.written)
        self.assertEqual(retried.sequence, result.sequence)
        self.assert_originals_unchanged(originals)

    def test_same_accounting_identity_changed_input_conflicts_before_publication(self):
        first, _, _ = self.append_accounting()
        changed = self.f.accounting_for(recorded_at="2026-10-15T00:06:00Z")
        different, evidence = self.accounting_event(changed, events=self.baseline)
        self.assertEqual(first.event_id, different.event_id)
        count = self.store.verify().event_count
        with self.assertRaises(JournalConflictError): self.store.append(different, evidence)
        self.assertEqual(self.store.verify().event_count, count)
        self.assert_originals_unchanged()

    def test_missing_accounting_input_or_activity_sources_never_publish(self):
        event, evidence = self.accounting_event()
        for absent in evidence:
            with self.subTest(absent=absent):
                supplied = {path: raw for path, raw in evidence.items() if path != absent}
                with self.assertRaisesRegex(JournalVerificationError, "missing or mismatched"):
                    self.store.append(event, supplied)
                self.assertEqual(self.store.verify().event_count, len(self.baseline))
                self.assertEqual(self.store.verify().orphan_evidence_count, 0)

    def test_supplied_source_path_or_digest_hash_mismatch_rejects(self):
        event, evidence = self.accounting_event()
        for supplied in ({**evidence, "trading/activities.json": b"changed"}, {**evidence, "0" * 64: b"wrong-digest"}):
            with self.assertRaisesRegex(JournalVerificationError, "hash mismatch"):
                self.store.append(event, supplied)
        self.assertEqual(self.store.verify().event_count, len(self.baseline))

    def test_rehashed_realized_pnl_tampering_is_rejected_by_source_replay(self):
        self.append_accounting()
        def mutate(value):
            result = value["payload"]["result"]
            result["realized_trade_pnl"] = "999"
            result["totals"]["net_realized_pnl"] = "999"
        self.rehash_last_entry(mutate)
        with self.assertRaisesRegex(JournalVerificationError, "reproduce retained evidence"):
            self.store.verify()
        self.assert_originals_unchanged()

    def test_rehashed_fifo_cost_basis_tampering_is_rejected(self):
        self.append_accounting()
        self.rehash_last_entry(lambda value: value["payload"]["result"]["closed_lots"][0].update(buy_price="11"))
        with self.assertRaisesRegex(JournalVerificationError, "reproduce retained evidence"):
            self.store.events()

    def test_rehashed_attempt_or_event_identity_tampering_is_rejected(self):
        for field in ("attempt", "event"):
            copied = self.base / ("identity-" + field)
            event, evidence = self.accounting_event()
            self.store.append(event, evidence)
            shutil.copytree(self.store.root, copied)
            path = copied / "entries" / f"{self.store.verify().event_count:08d}.json"
            entry = json.loads(path.read_bytes())
            if field == "attempt": entry["event"]["payload"]["result"]["matched_fills"][0]["attempt_sha256"] = "f" * 64
            else: entry["event"]["event_id"] = "journal-event-" + "f" * 64
            entry["event_sha256"] = sha256_bytes(JournalEvent.from_mapping(entry["event"]).to_bytes())
            path.chmod(0o600); path.write_bytes(canonical_json_bytes(entry))
            with self.subTest(field=field), self.assertRaisesRegex(JournalVerificationError, "reproduce retained evidence"):
                JournalStore(copied).verify()

    def test_wrong_account_with_consistent_input_hash_is_rejected(self):
        event, evidence = self.candidate_with_input({"account_id": "another-paper-account"})
        with self.assertRaisesRegex(JournalVerificationError, "account or mode"):
            self.store.append(event, evidence)
        self.assertEqual(self.store.verify().event_count, len(self.baseline))
        self.assert_originals_unchanged()

    def test_wrong_link_hash_with_consistent_document_digest_is_rejected(self):
        event, evidence = self.candidate_with_input({"start_snapshot_sha256": "9" * 64})
        with self.assertRaisesRegex(JournalVerificationError, "canonical source hash"):
            self.store.append(event, evidence)
        self.assertEqual(self.store.verify().event_count, len(self.baseline))

    def test_shadow_handoff_cannot_substitute_for_execution_reconciliation(self):
        fixture = projection_fixtures.DecisionJournalProjectionTests("runTest")
        fixture.setUp()
        self.addCleanup(fixture.tearDown)
        fixture.commit_outcome("SHADOW")
        history = load_verified_history(fixture.root)
        projected = project_history(history)
        for event in projected:
            self.store.append(event, dict(history.source_files))
        shadow = projected[-1]
        self.assertEqual(shadow.payload["execution_status"], "SHADOW_ONLY")
        event, evidence = self.candidate_with_input({"end_reconciliation_event_id": shadow.event_id,
                                                    "end_reconciliation_sha256": shadow.source["source_sha256"]})
        with self.assertRaisesRegex(JournalVerificationError, "different type"):
            self.store.append(event, evidence)
        self.assertEqual(self.store.events()[-1].to_bytes(), shadow.to_bytes())

    def test_live_or_shadow_accounting_mode_is_rejected_before_store_write(self):
        for mode in ("LIVE", "SHADOW"):
            value = self.f.accounting.to_dict(); value["mode"] = mode
            with self.assertRaises(ContractValidationError): AccountingInput.from_mapping(value)
        self.assertEqual(self.store.verify().event_count, len(self.baseline))

    def test_retained_raw_source_byte_loss_or_corruption_rejects_verification(self):
        self.append_accounting()
        digest = self.f.activities.provenance["source_evidence"]["sha256"]
        raw_path = self.store.root / "evidence" / digest
        copied = self.base / "lost-source"
        shutil.copytree(self.store.root, copied)
        (copied / "evidence" / digest).unlink()
        with self.assertRaisesRegex(JournalVerificationError, "missing or mismatched"):
            JournalStore(copied).verify()
        raw_path.chmod(0o600); raw_path.write_bytes(b"changed source")
        with self.assertRaisesRegex(JournalVerificationError, "evidence hash mismatch"):
            self.store.verify()

    def test_restored_journal_verifies_after_original_export_and_native_fixture_are_removed(self):
        exported = self.base / "original-export.json"
        exported.write_bytes(self.f.rawsource)
        self.append_accounting()
        restored = self.base / "restored"
        shutil.copytree(self.store.root, restored)
        exported.unlink(); self.f.close()
        restored_store = JournalStore(restored)
        self.assertEqual(restored_store.verify().to_dict(), self.store.verify().to_dict())
        self.assertEqual([event.to_bytes() for event in restored_store.events()], [event.to_bytes() for event in self.store.events()])
        self.assertEqual(restored_store.events()[-1].payload["result"]["realized_trade_pnl"], "15.92")

    def test_precommit_interruption_reuses_orphan_evidence_and_commits_exactly_once(self):
        event, evidence = self.accounting_event()
        def interrupt(staging, target, name, raw):
            if name.endswith(".json"): raise JournalPersistenceError("injected precommit interruption")
            return _publish_immutable(staging, target, name, raw)
        with mock.patch("blackpod_build_week.decision_journal_store._publish_immutable", side_effect=interrupt):
            with self.assertRaises(JournalPersistenceError): self.store.append(event, evidence)
        summary = self.store.verify()
        self.assertEqual(summary.event_count, len(self.baseline))
        self.assertEqual(summary.orphan_evidence_count, 3)
        self.assertTrue(self.store.append(event, evidence).written)
        self.assertFalse(self.store.append(event, evidence).written)
        self.assertEqual(self.store.verify().orphan_evidence_count, 0)
        self.assert_originals_unchanged()

    def test_postcommit_interruption_recovers_as_noop_without_rewriting(self):
        event, evidence = self.accounting_event()
        def interrupt(staging, target, name, raw):
            _publish_immutable(staging, target, name, raw)
            if name.endswith(".json"): raise JournalPersistenceError("injected postcommit interruption")
        with mock.patch("blackpod_build_week.decision_journal_store._publish_immutable", side_effect=interrupt):
            with self.assertRaises(JournalPersistenceError): self.store.append(event, evidence)
        committed = self.entry_bytes()
        self.assertEqual(self.store.verify().event_count, len(self.baseline) + 1)
        self.assertFalse(self.store.append(event, evidence).written)
        self.assert_originals_unchanged(committed)

    def test_file_fsync_failure_never_publishes_partial_accounting_entry(self):
        event, evidence = self.accounting_event()
        original_fsync = os.fsync
        def interrupt(descriptor):
            if os.fstat(descriptor).st_mode & 0o170000 == 0o100000:
                raise OSError("injected staged-file fsync failure")
            return original_fsync(descriptor)
        with mock.patch("blackpod_build_week.decision_journal_store.os.fsync", side_effect=interrupt):
            with self.assertRaises(JournalPersistenceError): self.store.append(event, evidence)
        self.assertEqual(self.store.verify().event_count, len(self.baseline))
        self.assertEqual(self.store.verify().orphan_evidence_count, 0)
        self.assertTrue(self.store.append(event, evidence).written)

    def test_orphan_staging_is_readonly_reported_then_removed_on_retry(self):
        event, evidence, _ = self.append_accounting()
        orphan = self.store.root / "staging" / (".publish-" + "a" * 32 + ".tmp")
        orphan.write_bytes(b"interrupted unpublished accounting bytes")
        summary = self.store.verify()
        self.assertEqual(summary.staging_orphan_count, 1)
        self.assertTrue(orphan.exists())
        self.assertFalse(self.store.append(event, evidence).written)
        self.assertFalse(orphan.exists())
        self.assert_originals_unchanged()

    def test_internal_staging_hardlink_after_publication_is_recoverable(self):
        event, evidence, result = self.append_accounting()
        entry = self.store.root / "entries" / f"{result.sequence:08d}.json"
        raw = entry.read_bytes()
        orphan = self.store.root / "staging" / (".publish-" + "b" * 32 + ".tmp")
        os.link(entry, orphan)
        self.assertEqual(self.store.verify().staging_orphan_count, 1)
        self.assertFalse(self.store.append(event, evidence).written)
        self.assertFalse(orphan.exists())
        self.assertEqual(entry.stat().st_nlink, 1)
        self.assertEqual(entry.read_bytes(), raw)

    def test_unknown_staging_or_external_hardlink_does_not_trigger_unsafe_repair(self):
        event, evidence, result = self.append_accounting()
        unexpected = self.store.root / "staging" / "unknown.tmp"
        unexpected.write_bytes(b"do not delete")
        with self.assertRaisesRegex(JournalVerificationError, "staging"):
            self.store.append(event, evidence)
        self.assertTrue(unexpected.exists())
        unexpected.unlink()
        external = self.base / "external-accounting-entry.json"
        os.link(self.store.root / "entries" / f"{result.sequence:08d}.json", external)
        with self.assertRaises(JournalUnsafePathError): self.store.append(event, evidence)
        self.assertTrue(external.exists())

    def test_concurrent_identical_accounting_appends_publish_one_event(self):
        event, evidence = self.accounting_event()
        with ThreadPoolExecutor(max_workers=3) as pool:
            results = list(pool.map(lambda _: JournalStore(self.store.root).append(event, evidence), range(3)))
        self.assertEqual(sum(result.written for result in results), 1)
        self.assertEqual(len({result.sequence for result in results}), 1)
        self.assertEqual(self.store.verify().event_count, len(self.baseline) + 1)
        self.assertEqual(self.store.verify().orphan_evidence_count, 0)
        self.assert_originals_unchanged()

    def test_accounting_pnl_has_no_mission_execution_or_capital_authority(self):
        self.append_accounting()
        result = self.store.events()[-1].payload["result"]
        self.assertEqual(result["realized_trade_pnl"], "15.92")
        self.assertIn("NO_MISSION_PNL_ATTRIBUTION", result["limitations"])
        for field in ("execution_authority_granted", "provider_verified", "ownership_authenticated", "readiness"):
            self.assertFalse(result[field])
        self.assertTrue(all(flag is False for flag in result["authority"].values()))
        self.assert_originals_unchanged()


if __name__ == "__main__":
    unittest.main()
