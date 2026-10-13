"""Immutable mixed-version proposal / approval history and recovery tests."""
from __future__ import annotations

import copy
import json
import socket
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest import mock

import test_investment_approval as fixtures
from blackpod_build_week.contracts.decision_journal import JournalEvent
from blackpod_build_week.decision_journal_store import (
    JournalStore, JournalConflictError, JournalVerificationError,
    JournalPersistenceError, _publish_immutable,
)
from blackpod_build_week.hashing import canonical_json_bytes, sha256_bytes
from blackpod_build_week.investment_approval import (
    build_approval_event, evidence_for_approval, approval_state,
)
from blackpod_build_week.contracts.investment_governance import ProposalInput
from blackpod_build_week.investment_governance import build_proposal_event, evidence_for_proposal


class InvestmentGovernanceStoreTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.ApprovalFixture()
        self.addCleanup(self.fixture.close)
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name).resolve() / "journal"
        self.store = JournalStore(self.root)
        self.enterContext(mock.patch.object(socket.socket, "connect", side_effect=AssertionError("network forbidden")))
        self.enterContext(mock.patch("subprocess.run", side_effect=AssertionError("process forbidden")))
        for event in self.fixture.events:
            self.store.append(event, self.fixture.blobs)
        self.original = {path.name: path.read_bytes() for path in (self.root / "entries").iterdir()}

    def approval_event(self, **changes):
        approval = self.fixture.approval(**changes)
        events, blobs = self.store.verified_contents()
        return build_approval_event(approval, events, blobs), evidence_for_approval(approval, events, blobs)

    def assert_originals_unchanged(self):
        for name, raw in self.original.items():
            self.assertEqual((self.root / "entries" / name).read_bytes(), raw)

    def test_mixed_v1_v2_v3_v4_journal_roundtrip_is_reproducible(self):
        event, evidence = self.approval_event()
        result = self.store.append(event, evidence)
        self.assertTrue(result.written)
        summary = self.store.verify()
        self.assertEqual(summary.event_count, len(self.fixture.events) + 1)
        self.assertEqual(summary.orphan_evidence_count, 0)
        self.assertEqual(self.store.events()[-1].to_bytes(), event.to_bytes())
        self.assert_originals_unchanged()

    def test_identical_retry_is_noop_after_revocation(self):
        event, evidence = self.approval_event()
        first = self.store.append(event, evidence)
        revoke, revoke_evidence = self.approval_event(action="REVOKE", approval_id="revocation",
            revokes_approval_event_id=event.event_id, recorded_at="2026-10-12T00:02:00Z")
        self.store.append(revoke, revoke_evidence)
        rebuilt, supplied = self.approval_event()
        self.assertEqual(rebuilt.to_bytes(), event.to_bytes())
        second = self.store.append(rebuilt, supplied)
        self.assertFalse(second.written)
        self.assertEqual(first.sequence, second.sequence)
        self.assert_originals_unchanged()

    def test_same_approval_id_changed_input_conflicts(self):
        event, evidence = self.approval_event()
        self.store.append(event, evidence)
        changed, changed_evidence = self.approval_event(expires_at="2026-10-12T00:08:00Z")
        with self.assertRaises(JournalConflictError):
            self.store.append(changed, changed_evidence)

    def test_rehashed_event_identity_tamper_fails_semantic_verification(self):
        event, evidence = self.approval_event()
        self.store.append(event, evidence)
        path = self.root / "entries" / f"{len(self.fixture.events) + 1:08d}.json"
        path.chmod(0o600)
        entry = json.loads(path.read_bytes())
        entry["event"]["event_id"] = "journal-event-" + "f" * 64
        entry["event_sha256"] = sha256_bytes(JournalEvent.from_mapping(entry["event"]).to_bytes())
        path.write_bytes(canonical_json_bytes(entry))
        with self.assertRaisesRegex(JournalVerificationError, "source projection"):
            self.store.verify()

    def test_rehashed_proposal_report_tamper_fails_semantic_verification(self):
        path = self.root / "entries" / f"{len(self.fixture.events):08d}.json"
        path.chmod(0o600)
        entry = json.loads(path.read_bytes())
        entry["event"]["payload"]["report"]["metrics"]["projected_cash_weight"] = 0.99
        entry["event_sha256"] = sha256_bytes(JournalEvent.from_mapping(entry["event"]).to_bytes())
        path.write_bytes(canonical_json_bytes(entry))
        with self.assertRaisesRegex(JournalVerificationError, "source projection"):
            self.store.verify()

    def test_conflicting_policy_version_and_context_identity_fail(self):
        for field in ("policy", "context"):
            value = copy.deepcopy(self.fixture.proposal_value)
            value["proposal_id"] += "-" + field
            if field == "policy":
                value["risk_policy"]["limits"]["max_position_weight"] = 0.4
            else:
                value["risk_context"]["instruments"][0]["liquidity_score"] = 0.8
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, "conflicting retained content"):
                events, blobs = self.store.verified_contents()
                build_proposal_event(ProposalInput.from_mapping(value), events, blobs)

    def test_interruption_before_entry_publication_recovers_exactly_once(self):
        event, evidence = self.approval_event()

        def interrupt(staging, target_directory, name, payload):
            if name.endswith(".json"):
                raise JournalPersistenceError("injected entry interruption")
            return _publish_immutable(staging, target_directory, name, payload)

        with mock.patch("blackpod_build_week.decision_journal_store._publish_immutable", side_effect=interrupt):
            with self.assertRaises(JournalPersistenceError):
                self.store.append(event, evidence)
        self.assertEqual(self.store.verify().event_count, len(self.fixture.events))
        self.assertGreater(self.store.verify().orphan_evidence_count, 0)
        self.assertTrue(self.store.append(event, evidence).written)
        self.assertFalse(self.store.append(event, evidence).written)
        self.assertEqual(self.store.verify().orphan_evidence_count, 0)
        self.assert_originals_unchanged()

    def test_interruption_after_publication_recovers_as_noop(self):
        event, evidence = self.approval_event()

        def interrupt(staging, target_directory, name, payload):
            _publish_immutable(staging, target_directory, name, payload)
            if name.endswith(".json"):
                raise JournalPersistenceError("injected post-commit interruption")

        with mock.patch("blackpod_build_week.decision_journal_store._publish_immutable", side_effect=interrupt):
            with self.assertRaises(JournalPersistenceError):
                self.store.append(event, evidence)
        self.assertEqual(self.store.verify().event_count, len(self.fixture.events) + 1)
        self.assertFalse(self.store.append(event, evidence).written)
        self.assert_originals_unchanged()

    def test_concurrent_approval_retries_write_one_event(self):
        event, evidence = self.approval_event()
        with ThreadPoolExecutor(max_workers=3) as pool:
            results = list(pool.map(lambda _: JournalStore(self.root).append(event, evidence), range(3)))
        self.assertEqual(sum(result.written for result in results), 1)
        self.assertEqual(self.store.verify().event_count, len(self.fixture.events) + 1)

    def test_restored_copy_keeps_complete_original_packet(self):
        import shutil
        event, evidence = self.approval_event()
        self.store.append(event, evidence)
        restored = self.root.parent / "restored"
        shutil.copytree(self.root, restored)
        copied = JournalStore(restored)
        self.assertEqual(copied.verify().to_dict(), self.store.verify().to_dict())
        self.assertEqual([item.to_bytes() for item in copied.events()], [item.to_bytes() for item in self.store.events()])

    def test_noninvestment_approval_domain_cannot_gain_capital_or_trading_authority(self):
        event, evidence = self.approval_event()
        value = event.to_dict()
        for domain in ("TRADING", "CAPITAL_ALLOCATION"):
            value["domain"] = domain
            with self.subTest(domain=domain), self.assertRaises(ValueError):
                JournalEvent.from_mapping(value)

    def test_journal_keeps_nonexecuted_zero_permission_state(self):
        event, evidence = self.approval_event()
        self.store.append(event, evidence)
        events, _ = self.store.verified_contents()
        state = approval_state(self.fixture.proposal, events, "2026-10-12T00:02:00Z")
        self.assertEqual(state["execution_status"], "NOT_EXECUTED")
        self.assertIsNone(state["realized_trade_pnl"])
        self.assertTrue(all(value is False for value in state["authority"].values()))


if __name__ == "__main__":
    unittest.main()
