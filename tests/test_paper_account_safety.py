"""Persistent account admission tests; no workers, Alpaca or live operations."""
from __future__ import annotations
import asyncio
import copy
import json
from pathlib import Path
import socket
import tempfile
import unittest
from unittest import mock

from test_trading_reconciliation_engine import ReconciliationFixture, NOW, LATER, position
from blackpod_build_week import paper_account_safety as safety
from blackpod_build_week import trading_reconciliation as engine
from blackpod_build_week import auto_trading_worker as worker
from blackpod_build_week import galactica_trading_adapter as adapter
from blackpod_build_week.auto_trading_runtime import RuntimeLedger, profile_hash, enable_trading, _immutable
from blackpod_build_week.decision_journal_store import JournalStore
from blackpod_build_week.hashing import canonical_json_bytes, sha256_bytes


class PaperAccountSafetyTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(mock.patch.object(socket.socket, "connect", side_effect=AssertionError("network forbidden")))
        self.enterContext(mock.patch("subprocess.Popen", side_effect=AssertionError("executor forbidden")))
        self.enterContext(mock.patch("subprocess.run", side_effect=AssertionError("provider forbidden")))
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.base = Path(directory.name).resolve()
        self.fixture = ReconciliationFixture()
        self.addCleanup(self.fixture.close)
        self.store = JournalStore(self.base / "journal")
        for event in self.fixture.events:
            self.store.append(event, self.fixture.blobs)
        self.enterContext(mock.patch.object(safety, "account_state_root", side_effect=lambda account: self.base / "account-state" / sha256_bytes(account.encode())))
        self.account_root = safety.account_state_root(self.fixture.profile["account_id"])

    def install(self, reconciliation=None, ownership=None):
        return safety.install_paper_book(self.store.root, (ownership or self.fixture.ownership_event).event_id,
            None if reconciliation is None else reconciliation.event_id, confirm_account_id=self.fixture.profile["account_id"])

    def session(self, *, profile=None, identity="fixture-session"):
        profile = profile or self.fixture.profile
        control = {"action_id": "fixture-action-" + identity, "session_id": identity,
                   "profile_sha256": profile_hash(profile), "entries_enabled": True,
                   "recorded_at": NOW, "operator_id": "fixture-operator"}
        return safety.PaperSessionSafety(profile, control)

    def receipt(self, *, identity="fixture-session", submitted=False, attempt_id="attempt-1"):
        value = copy.deepcopy(self.fixture.capture["events"][2 if submitted else 1]["payload"])
        value.update(session_id=identity, attempt_id=attempt_id)
        return value

    def reconcile_account_prefix(self, *, identity="resolved-account-prefix"):
        raw = safety.export_runtime(self.account_root)
        reference = {"path": "runtime/account-prefix.json", "sha256": sha256_bytes(raw), "size_bytes": len(raw)}
        document = self.fixture.reconciliation_for(reconciliation_id=identity, runtime_evidence=reference)
        events, blobs = self.store.verified_contents()
        blobs[reference["sha256"]] = raw
        event = engine.build_reconciliation_event(document, events, blobs)
        self.store.append(event, engine.evidence_for_reconciliation(document, events, blobs))
        return event

    def test_missing_book_rejects_before_state_creation_or_native_import(self):
        with self.assertRaises(ValueError):
            self.session()
        self.assertFalse(self.account_root.exists())

    def test_installation_is_idempotent_and_never_grants_capital_or_execution(self):
        first = self.install()
        second = self.install()
        self.assertTrue(first["written"])
        self.assertFalse(second["written"])
        binding = json.loads((self.account_root / "book.json").read_bytes())
        self.assertFalse(binding["execution_authorized"])
        self.assertFalse(binding["capital_policy_activated"])
        self.assertEqual(binding["ownership_event_id"], self.fixture.ownership_event.event_id)
        self.assertEqual(len(list((self.account_root / "book_bindings").glob("*.json"))), 1)

    def test_account_confirmation_and_funded_profile_are_rejected(self):
        with self.assertRaises(ValueError):
            safety.install_paper_book(self.store.root, self.fixture.ownership_event.event_id, confirm_account_id="wrong-account")
        self.assertFalse(self.account_root.exists())
        self.install()
        profile = copy.deepcopy(self.fixture.profile)
        profile["mode"] = "LIVE"
        with self.assertRaises(ValueError):
            self.session(profile=profile)
        profile = copy.deepcopy(self.fixture.profile)
        profile["account_id"] = "another-paper-account"
        with self.assertRaises(ValueError):
            self.session(profile=profile)

    def test_funded_controller_worker_and_adapter_cannot_activate_in_this_paper_burst(self):
        profile = copy.deepcopy(self.fixture.profile)
        profile["mode"] = "LIVE"
        root = self.base / "funded-runtime"
        spawn = mock.Mock(side_effect=AssertionError("funded process forbidden"))
        with self.assertRaisesRegex(ValueError, "funded activation"):
            enable_trading(root, profile, action_id="live-denied", operator_id="fixture-operator",
                confirm_profile_sha256=profile_hash(profile), confirm_account_id=profile["account_id"],
                confirm_mode="LIVE", now=lambda: NOW, spawn=spawn)
        spawn.assert_not_called()
        self.assertFalse(root.exists())
        with mock.patch.object(adapter.importlib, "import_module", side_effect=AssertionError("native import forbidden")) as imports:
            with self.assertRaisesRegex(ValueError, "funded activation"):
                asyncio.run(adapter.run_guarded_navigator(profile, lambda: {"entries_enabled": True}))
        imports.assert_not_called()
        # Simulate a retained pre-burst LIVE startup request; the production
        # worker must refuse it before native imports or source snapshots.
        ledger = RuntimeLedger(root)
        _immutable(root / "profiles" / (profile_hash(profile) + ".json"), canonical_json_bytes(profile))
        ledger.append("CONTROL", {"action_id": "legacy-funded-request", "session_id": "legacy-funded-session",
            "profile_sha256": profile_hash(profile), "entries_enabled": True, "recorded_at": NOW, "operator_id": "fixture-operator"})
        with mock.patch.object(worker, "snapshot_execution_profile", side_effect=AssertionError("snapshot forbidden")) as snapshot:
            with mock.patch.object(adapter, "run_guarded_navigator", side_effect=AssertionError("native runner forbidden")) as run:
                self.assertEqual(worker.run_worker(root, "legacy-funded-session", account_lock_fd=-1), 2)
        snapshot.assert_not_called()
        run.assert_not_called()
        self.assertFalse(ledger.latest_control()["entries_enabled"])
        self.assertEqual(ledger.events()[-1]["payload"]["state"], "START_FAILED")

    def test_profile_must_respect_declared_trading_symbols_and_protected_investments(self):
        self.install()
        for change in ({"symbols": ["AAPL"]}, {"protected_symbols": []},
                       {"symbols": ["MSFT", "AAPL"]}, {"protected_symbols": ["MSFT", "AAPL"]}):
            profile = copy.deepcopy(self.fixture.profile)
            profile.update(change)
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.session(profile=profile)

    def test_profile_cannot_omit_or_protect_a_holding_owned_by_the_trading_book(self):
        expanded = JournalStore(self.base / "expanded-journal")
        snapshot = self.fixture.snapshot_for(snapshot_id="expanded-snapshot",
            positions=[position(), position("AAPL", "1"), position("NVDA", "1")])
        snapshot_event = engine.build_snapshot_event(snapshot, (), self.fixture.blobs)
        expanded.append(snapshot_event, engine.evidence_for_snapshot(snapshot, (), self.fixture.blobs))
        ownership = self.fixture.ownership_for(ownership_id="expanded-ownership",
            broker_snapshot_event_id=snapshot_event.event_id, broker_snapshot_sha256=snapshot_event.source["source_sha256"],
            desks={"TRADING": ["MSFT", "NVDA"], "INVESTMENT": ["AAPL"]})
        events, blobs = expanded.verified_contents()
        ownership_event = engine.build_ownership_event(ownership, events, blobs)
        expanded.append(ownership_event, engine.evidence_for_ownership(ownership, events, blobs))
        safety.install_paper_book(expanded.root, ownership_event.event_id, confirm_account_id=self.fixture.profile["account_id"])
        for protected in (["AAPL"], ["AAPL", "NVDA"]):
            profile = copy.deepcopy(self.fixture.profile)
            profile["protected_symbols"] = protected
            with self.subTest(protected=protected), self.assertRaises(ValueError):
                self.session(profile=profile)
        self.assertEqual(RuntimeLedger(self.account_root).events(), [])

    def test_profile_cannot_expand_the_protected_desk_beyond_the_exact_declaration(self):
        self.install()
        profile = copy.deepcopy(self.fixture.profile)
        profile["protected_symbols"] = ["AAPL", "NVDA"]
        with self.assertRaises(ValueError):
            self.session(profile=profile)
        self.assertEqual(RuntimeLedger(self.account_root).events(), [])

    def test_unknown_acceptance_persists_and_blocks_entries_across_sessions(self):
        self.install()
        first = self.session()
        first.record_receipt(self.receipt())
        self.assertTrue(first.state()["entries_blocked"])
        self.assertFalse(first.permit_mutation("MSFT", True))
        self.assertFalse(first.permit_mutation("MSFT", False))
        second = self.session(identity="session-another-runtime")
        self.assertEqual(first.ledger.root, second.ledger.root)
        self.assertTrue(second.state()["entries_blocked"])
        self.assertFalse(second.permit_mutation("MSFT", True))
        self.assertFalse(second.state()["automatic_resubmission_enabled"])

    def test_distinct_profiles_for_same_account_share_the_durable_barrier(self):
        self.install()
        first = self.session()
        first.record_receipt(self.receipt())
        profile = copy.deepcopy(self.fixture.profile)
        profile["profile_id"] = "another-explicit-profile"
        second = self.session(profile=profile, identity="another-profile-session")
        self.assertEqual(first.ledger.root, second.ledger.root)
        self.assertTrue(second.state()["entries_blocked"])
        self.assertFalse(second.permit_mutation("MSFT", True))

    def test_known_accepted_order_restores_exact_baseline_and_allows_protective_reduction(self):
        self.install()
        session = self.session()
        session.record_receipt(self.receipt())
        session.record_receipt(self.receipt(submitted=True))
        self.assertFalse(session.permit_mutation("MSFT", True))
        self.assertTrue(session.permit_mutation("MSFT", False))
        self.assertEqual(session.restored_inflight(), [{"order_id": "order-1", "symbol": "MSFT", "side": "buy", "qty": "2", "prior_qty": "0"}])

    def test_exact_installed_broker_reconciliation_clears_only_its_retained_prefix(self):
        self.install()
        session = self.session()
        session.record_receipt(self.receipt())
        session.record_receipt(self.receipt(submitted=True))
        self.assertTrue(session.state()["entries_blocked"])
        event = self.reconcile_account_prefix()
        self.install(reconciliation=event)
        self.assertFalse(session.state()["entries_blocked"])
        self.assertTrue(session.permit_mutation("MSFT", True))
        self.assertEqual(session.restored_inflight(), [])
        session.record_receipt(self.receipt(attempt_id="later-unknown"))
        self.assertTrue(session.state()["entries_blocked"])
        self.assertFalse(session.permit_mutation("MSFT", True))
        self.assertFalse(session.permit_mutation("MSFT", False))

    def test_different_runtime_prefix_cannot_clear_the_account_barrier(self):
        self.install()
        session = self.session()
        session.record_receipt(self.receipt())
        session.record_receipt(self.receipt(submitted=True))
        events, blobs = self.store.verified_contents()
        blobs.update(self.fixture.blobs)
        event = engine.build_reconciliation_event(self.fixture.reconciliation, events, blobs)
        self.store.append(event, engine.evidence_for_reconciliation(self.fixture.reconciliation, events, blobs))
        self.install(reconciliation=event)
        self.assertFalse(session.permit_mutation("MSFT", True))

    def test_tampered_binding_and_source_journal_fail_closed(self):
        self.install()
        session = self.session()
        path = self.account_root / "book.json"
        original = path.read_bytes()
        for change in ({"ownership_event_sha256": "f" * 64}, {"execution_authorized": True},
                       {"capital_policy_activated": True}, {"account_id": "wrong-account"}):
            value = json.loads(original)
            value.update(change)
            path.write_bytes(canonical_json_bytes(value))
            with self.subTest(change=change):
                self.assertFalse(session.permit_mutation("MSFT", True))
        path.write_bytes(original)
        entry_path = self.store.root / "entries" / "00000002.json"
        entry_path.chmod(0o600)
        entry_path.write_bytes(b'{"invalid":"not a journal event"}')
        self.assertFalse(session.permit_mutation("MSFT", True))

    def test_corrupted_receipt_chain_does_not_permit_entries_or_protective_duplicates(self):
        self.install()
        session = self.session()
        session.record_receipt(self.receipt())
        path = session.ledger.root / "events" / "000000000002.json"
        value = json.loads(path.read_bytes())
        value["payload"]["qty"] = "3"
        path.write_bytes(canonical_json_bytes(value))
        self.assertFalse(session.permit_mutation("MSFT", True))
        self.assertFalse(session.permit_mutation("MSFT", False))

    def test_book_changes_require_linked_supersession_and_cannot_rollback(self):
        self.install()
        snapshot = self.fixture.snapshot_for(snapshot_id="scope-change-flat", captured_at=LATER,
            capture_window={"started_at": LATER, "completed_at": LATER}, positions=[], orders=[])
        events, blobs = self.store.verified_contents()
        blobs.update(self.fixture.blobs)
        snapshot_event = engine.build_snapshot_event(snapshot, events, blobs)
        self.store.append(snapshot_event, engine.evidence_for_snapshot(snapshot, events, blobs))
        ownership = self.fixture.ownership_for(ownership_id="ownership-linked-change", recorded_at=LATER,
            broker_snapshot_event_id=snapshot_event.event_id, broker_snapshot_sha256=snapshot_event.source["source_sha256"],
            desks={"TRADING": [], "INVESTMENT": ["AAPL"]}, supersedes_event_id=self.fixture.ownership_event.event_id)
        events, blobs = self.store.verified_contents()
        ownership_event = engine.build_ownership_event(ownership, events, blobs)
        self.store.append(ownership_event, engine.evidence_for_ownership(ownership, events, blobs))
        self.assertTrue(self.install(ownership=ownership_event)["written"])
        with self.assertRaises(ValueError):
            self.install(ownership=self.fixture.ownership_event)
        with self.assertRaises(ValueError):
            self.session()
        binding = json.loads((self.account_root / "book.json").read_bytes())
        self.assertFalse(binding["execution_authorized"])
        self.assertFalse(binding["capital_policy_activated"])

    def test_uninstalled_scope_amendment_blocks_entries_and_keeps_unchanged_protective_exits(self):
        self.install()
        session = self.session()
        session.record_receipt(self.receipt())
        session.record_receipt(self.receipt(submitted=True))
        original_binding = (self.account_root / "book.json").read_bytes()
        snapshot = self.fixture.snapshot_for(snapshot_id="scope-expanded-with-risk", captured_at=LATER,
            capture_window={"started_at": LATER, "completed_at": LATER})
        events, blobs = self.store.verified_contents()
        blobs.update(self.fixture.blobs)
        snapshot_event = engine.build_snapshot_event(snapshot, events, blobs)
        self.store.append(snapshot_event, engine.evidence_for_snapshot(snapshot, events, blobs))
        ownership = self.fixture.ownership_for(ownership_id="expanded-retains-msft", recorded_at=LATER,
            broker_snapshot_event_id=snapshot_event.event_id, broker_snapshot_sha256=snapshot_event.source["source_sha256"],
            desks={"TRADING": ["MSFT", "NVDA"], "INVESTMENT": ["AAPL"]},
            supersedes_event_id=self.fixture.ownership_event.event_id)
        events, blobs = self.store.verified_contents()
        ownership_event = engine.build_ownership_event(ownership, events, blobs)
        self.store.append(ownership_event, engine.evidence_for_ownership(ownership, events, blobs))
        self.assertEqual((self.account_root / "book.json").read_bytes(), original_binding)
        self.assertFalse(session.permit_mutation("MSFT", True))
        self.assertTrue(session.permit_mutation("MSFT", False))
        self.assertFalse(session.permit_mutation("AAPL", False))

    def test_passive_reassignment_cannot_remove_installed_worker_exits_before_handoff(self):
        from blackpod_build_week.auto_trading_runtime import account_lock
        self.install()
        session = self.session()
        snapshot = self.fixture.snapshot_for(snapshot_id="reassignment-flat-observation", captured_at=LATER,
            capture_window={"started_at": LATER, "completed_at": LATER}, positions=[], orders=[])
        events, blobs = self.store.verified_contents()
        blobs.update(self.fixture.blobs)
        snapshot_event = engine.build_snapshot_event(snapshot, events, blobs)
        self.store.append(snapshot_event, engine.evidence_for_snapshot(snapshot, events, blobs))
        ownership = self.fixture.ownership_for(ownership_id="passive-reassignment", recorded_at=LATER,
            broker_snapshot_event_id=snapshot_event.event_id, broker_snapshot_sha256=snapshot_event.source["source_sha256"],
            desks={"TRADING": [], "INVESTMENT": ["AAPL", "MSFT"]}, supersedes_event_id=self.fixture.ownership_event.event_id)
        events, blobs = self.store.verified_contents()
        reassigned = engine.build_ownership_event(ownership, events, blobs)
        self.store.append(reassigned, engine.evidence_for_ownership(ownership, events, blobs))
        with account_lock(self.fixture.profile):
            self.assertFalse(session.permit_mutation("MSFT", True))
            self.assertTrue(session.permit_mutation("MSFT", False))
            with self.assertRaises(ValueError):
                self.install(ownership=reassigned)
        self.install(ownership=reassigned)
        self.assertFalse(session.permit_mutation("MSFT", False))


if __name__ == "__main__":
    unittest.main()
