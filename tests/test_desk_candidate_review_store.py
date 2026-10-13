"""Passive v8 desk research: immutable mixed journals and source replay."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import shutil
import socket
import tempfile
import unittest
from unittest import mock

from blackpod_build_week import desk_candidate_review as engine
from blackpod_build_week.contracts.decision_journal import JournalEvent
from blackpod_build_week.contracts.desk_candidate_review import DeskReviewInput
from blackpod_build_week.contracts.trading_automation import TradingAutomationControl
from blackpod_build_week.decision_journal_store import (
    JournalStore, JournalConflictError, JournalVerificationError, JournalPersistenceError,
    JournalUnsafePathError, _publish_immutable,
)
from blackpod_build_week.hashing import canonical_json_bytes, sha256_bytes
from blackpod_build_week.trading_automation import build_automation_event, evidence_for_automation
from test_desk_candidate_review_engine import DeskReviewFixture
from test_investment_approval import ApprovalFixture
from test_trading_accounting_engine import AccountingFixture
from blackpod_build_week import trading_accounting
from blackpod_build_week.paper_test_budget import build_paper_test_budget


class DeskCandidateReviewStoreTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(mock.patch.object(socket.socket, "connect", side_effect=AssertionError("network forbidden")))
        self.enterContext(mock.patch("subprocess.Popen", side_effect=AssertionError("process or inference forbidden")))
        self.enterContext(mock.patch("subprocess.run", side_effect=AssertionError("native producer forbidden")))
        self.enterContext(mock.patch("blackpod_build_week.paper_account_probe.probe_paper_account", side_effect=AssertionError("broker probe forbidden")))
        self.enterContext(mock.patch("blackpod_build_week.galactica_trading_adapter.run_guarded_navigator", side_effect=AssertionError("execution forbidden")))
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.base = Path(directory.name).resolve()
        self.store = JournalStore(self.base / "journal")
        self.f = DeskReviewFixture()
        self.addCleanup(self.f.close)
        for event in self.f.events:
            self.store.append(event, self.f.blobs)
        self.baseline, self.retained = self.store.verified_contents()
        self.original = self.entry_bytes()

    def entry_bytes(self, store=None):
        store = store or self.store
        return {path.name: path.read_bytes() for path in (store.root / "entries").iterdir()}

    def assert_originals_unchanged(self, originals=None, store=None):
        store = store or self.store
        for name, raw in (originals or self.original).items():
            self.assertEqual((store.root / "entries" / name).read_bytes(), raw)

    def event_and_evidence(self, document=None, *, events=None, store=None):
        store = store or self.store
        current, retained = store.verified_contents()
        prefix = current if events is None else events
        blobs = {**self.f.blobs, **retained}
        document = document or self.f.document
        return engine.build_desk_review_event(document, prefix, blobs), engine.evidence_for_desk_review(document, prefix, blobs)

    def append_review(self, document=None):
        event, evidence = self.event_and_evidence(document)
        result = self.store.append(event, evidence)
        return event, evidence, result

    def rehash_last_entry(self, mutation, *, store=None):
        store = store or self.store
        path = store.root / "entries" / f"{store.verify().event_count:08d}.json"
        entry = json.loads(path.read_bytes())
        mutation(entry["event"])
        entry["event_sha256"] = sha256_bytes(JournalEvent.from_mapping(entry["event"]).to_bytes())
        path.chmod(0o600)
        path.write_bytes(canonical_json_bytes(entry))

    def changed_result(self, mutation):
        event, evidence = self.event_and_evidence()
        value = event.to_dict()
        mutation(value["payload"]["result"])
        return JournalEvent.from_mapping(value), evidence

    def changed_artifact(self, source_field, mutation):
        """Rehash the source and supplied input so only semantic replay can reject."""
        event, evidence = self.event_and_evidence()
        value = event.to_dict()
        document = value["payload"]["review"]
        old_ref = document["sources"][source_field]
        source = json.loads(evidence[old_ref["path"]])
        mutation(source)
        changed_raw = canonical_json_bytes(source)
        document["sources"][source_field] = {**old_ref, "sha256": sha256_bytes(changed_raw), "size_bytes": len(changed_raw)}
        supplied = DeskReviewInput.from_mapping(document)
        value["payload"]["review"] = supplied.to_dict()
        value["source"]["source_sha256"] = sha256_bytes(supplied.to_bytes())
        for reference in value["evidence"]:
            if reference["path"] == old_ref["path"]:
                reference.update(sha256=sha256_bytes(changed_raw), size_bytes=len(changed_raw))
            if reference["path"] == engine.REVIEW_EVIDENCE_PATH:
                reference.update(sha256=sha256_bytes(supplied.to_bytes()), size_bytes=len(supplied.to_bytes()))
        evidence = {**evidence, old_ref["path"]: changed_raw, engine.REVIEW_EVIDENCE_PATH: supplied.to_bytes()}
        return JournalEvent.from_mapping(value), evidence

    def connect_galactica_fixture(self):
        """Real pinned Spyglass/parser code over explicit synthetic evidence."""
        from test_shadow_galactica_analysis import ROOT, TRANSCRIPT, market_mapping
        from blackpod_build_week.shadow_native_analysis import derive_native_analysis
        from blackpod_build_week.shadow_galactica_analysis import (
            build_shadow_galactica_analysis, evidence_for_shadow_galactica_analysis,
        )
        rows = market_mapping()["bars"]["AAA"]
        start = datetime(2026, 7, 17, 4, tzinfo=timezone.utc)
        for index, row in enumerate(rows):
            row["t"] = (start + timedelta(days=index)).isoformat().replace("+00:00", "Z")
        for symbol in self.f.market["bars"]:
            self.f.market["bars"][symbol] = deepcopy(rows)
        self.f.market["source_evidence"] = [
            self.f.reference("synthetic-galactica/snapshots.json", canonical_json_bytes({"snapshots": self.f.market["snapshots"]})),
            self.f.reference("synthetic-galactica/bars.json", canonical_json_bytes({"bars": self.f.market["bars"], "next_page_token": None})),
        ]
        native = derive_native_analysis(self.f.market, self.f.sources)
        raw = canonical_json_bytes(self.f.market)
        spyglass = (ROOT / "spyglass.py").read_bytes()
        parser = (ROOT / "brigade_debrief.py").read_bytes()
        producer = (ROOT / "blackwell_brigade.py").read_bytes()
        galactica = build_shadow_galactica_analysis(raw, spyglass, generated_at=self.f.recorded_at,
            brigade_transcript=TRANSCRIPT, brigade_parser_source=parser, brigade_producer_source=producer,
            brigade_as_of="2026-04-24T20:00:00Z")
        evidence = evidence_for_shadow_galactica_analysis(raw, spyglass, brigade_transcript=TRANSCRIPT,
            brigade_parser_source=parser, brigade_producer_source=producer)
        self.f.blobs.update({sha256_bytes(value): value for value in evidence.values()})
        union = native["source_evidence"] + [reference for reference in galactica["source_evidence"].values() if reference is not None]
        self.f.analysis = {"schema_version": "blackpod.shadow_analysis_bundle.v1", "native": native,
                           "galactica": galactica, "source_evidence": union}
        self.f.document = self.f.document_for()
        return galactica

    def test_v8_roundtrip_retains_immutable_evidence_and_no_authority(self):
        event, evidence, result = self.append_review()
        self.assertTrue(result.written)
        self.assertEqual(result.sequence, len(self.baseline) + 1)
        events, blobs = self.store.verified_contents()
        self.assertEqual(events[-1].to_bytes(), event.to_bytes())
        self.assertEqual(events[-1].schema_version, "blackpod.decision_journal_event.v8")
        self.assertGreaterEqual(len(evidence), 28)
        for raw in evidence.values():
            digest = sha256_bytes(raw)
            self.assertEqual(blobs[digest], raw)
            self.assertEqual((self.store.root / "evidence" / digest).stat().st_mode & 0o777, 0o444)
        report = events[-1].payload["result"]
        self.assertFalse(report["readiness"])
        self.assertFalse(report["auto_trading_enabled"])
        self.assertIsNone(report["realized_trade_pnl"])
        self.assertTrue(all(value is False for value in report["authority"].values()))
        self.assertEqual(report["ownership_proposal"]["status"], "PROPOSED_NOT_INSTALLED")
        self.assert_originals_unchanged()

    def test_mixed_v1_through_v8_retains_mission_and_execution_semantics(self):
        legacy = ApprovalFixture()
        accounting = AccountingFixture()
        self.addCleanup(legacy.close)
        self.addCleanup(accounting.close)
        mixed = JournalStore(self.base / "mixed")
        for event in legacy.events:
            mixed.append(event, legacy.blobs)
        off = TradingAutomationControl.from_mapping({
            "schema_version": "blackpod.trading_automation_control.v1", "control_id": "desk-review-fixture-off",
            "operator_id": "fixture-operator", "recorded_at": self.f.document.recorded_at,
            "switch_id": "auto-trading", "requested_enabled": False, "scope": "TRADING_CONTROL_INTENT_ONLY",
            "domain": "TRADING", "execution_mode": "DISABLED", "origin": "SIMULATED_TEST",
        })
        mixed.append(build_automation_event(off), evidence_for_automation(off))
        for event in accounting.events:
            mixed.append(event, accounting.blobs)
        prefix, retained = mixed.verified_contents()
        blobs = {**accounting.blobs, **retained}
        accounting_event = trading_accounting.build_accounting_event(accounting.accounting, prefix, blobs)
        mixed.append(accounting_event, trading_accounting.evidence_for_accounting(accounting.accounting, prefix, blobs))
        # Keep each account's observations chronological. The mixed journal
        # already retains the accounting fixture's later PAPER snapshot, so
        # bind this research budget to that exact source rather than importing
        # an older, independently constructed account history after it.
        budget = build_paper_test_budget(accounting.start_event, budget_id="mixed-paper-budget",
            recorded_at=self.f.budget.recorded_at, declared_by=self.f.budget.declared_by)
        value = self.f.document.to_dict()
        raw = budget.to_bytes()
        self.f.blobs[sha256_bytes(raw)] = raw
        value["budget"] = {
            "proposal_evidence": {"path": "shadow-desk/mixed-budget.json", "sha256": sha256_bytes(raw), "size_bytes": len(raw)},
            "source_snapshot_event_id": accounting.start_event.event_id,
            "source_snapshot_sha256": accounting.start_event.source["source_sha256"],
        }
        document = DeskReviewInput.from_mapping(value)
        original = self.entry_bytes(mixed)
        event, evidence = self.event_and_evidence(document, store=mixed)
        mixed.append(event, evidence)
        events = mixed.events()
        self.assertEqual({event.schema_version for event in events}, {"blackpod.decision_journal_event.v" + str(version) for version in range(1, 9)})
        for item in events:
            if item.event_type == "MISSION_SNAPSHOT_RECORDED":
                self.assertIsNone(item.payload.get("realized_trade_pnl"))
                self.assertIn(item.payload["execution_status"], {"NOT_EXECUTED", "SHADOW_ONLY"})
        self.assertEqual(accounting_event.payload["result"]["realized_trade_pnl"], "15.92")
        self.assertIsNone(events[-1].payload["result"]["realized_trade_pnl"])
        self.assert_originals_unchanged(original, mixed)
        self.assertEqual(mixed.verify().orphan_evidence_count, 0)

    def test_identical_retry_after_later_review_and_off_context_is_noop(self):
        first, evidence, result = self.append_review()
        original = self.entry_bytes()
        value = self.f.document.to_dict()
        value.update(review_id="desk-review-later", recorded_at="2026-10-15T22:00:00Z")
        later = DeskReviewInput.from_mapping(value)
        self.append_review(later)
        off = TradingAutomationControl.from_mapping({
            "schema_version": "blackpod.trading_automation_control.v1", "control_id": "desk-review-later-off",
            "operator_id": "fixture-operator", "recorded_at": "2026-10-15T22:01:00Z", "switch_id": "auto-trading",
            "requested_enabled": False, "scope": "TRADING_CONTROL_INTENT_ONLY", "domain": "TRADING",
            "execution_mode": "DISABLED", "origin": "SIMULATED_TEST",
        })
        self.store.append(build_automation_event(off), evidence_for_automation(off))
        rebuilt, retained = self.event_and_evidence()
        self.assertEqual(rebuilt.to_bytes(), first.to_bytes())
        self.assertEqual(retained, evidence)
        retry = self.store.append(rebuilt, retained)
        self.assertFalse(retry.written)
        self.assertEqual(retry.sequence, result.sequence)
        self.assert_originals_unchanged(original)

    def test_same_review_identity_with_changed_policy_conflicts(self):
        first, _, _ = self.append_review()
        value = self.f.document.to_dict()
        value["policy"]["max_entry_fraction"] = "0.05"
        different, evidence = self.event_and_evidence(DeskReviewInput.from_mapping(value), events=self.baseline)
        self.assertEqual(first.event_id, different.event_id)
        before = self.store.verify().to_dict()
        with self.assertRaises(JournalConflictError):
            self.store.append(different, evidence)
        self.assertEqual(self.store.verify().to_dict(), before)

    def test_missing_input_market_issuer_or_native_source_cannot_publish(self):
        event, evidence = self.event_and_evidence()
        selected = [engine.REVIEW_EVIDENCE_PATH,
                    self.f.document.sources["market_evidence"]["path"],
                    self.f.document.sources["issuer_evidence"]["path"],
                    next(path for path in evidence if path.startswith("native_analysis_code/"))]
        for absent in selected:
            with self.subTest(absent=absent):
                supplied = {path: raw for path, raw in evidence.items() if path != absent}
                with self.assertRaisesRegex(JournalVerificationError, "missing or mismatched"):
                    self.store.append(event, supplied)
                self.assertEqual(self.store.verify().event_count, len(self.baseline))
                self.assertEqual(self.store.verify().orphan_evidence_count, 0)

    def test_evidence_hash_mismatch_rejects_before_writes(self):
        event, evidence = self.event_and_evidence()
        path = self.f.document.sources["market_evidence"]["path"]
        supplied = {**evidence, path: evidence[path] + b" "}
        with self.assertRaisesRegex(JournalVerificationError, "hash mismatch"):
            self.store.append(event, supplied)
        self.assertEqual(self.store.verify().event_count, len(self.baseline))

    def test_rehashed_price_metric_tampering_fails_semantic_replay(self):
        self.append_review()
        self.rehash_last_entry(lambda value: value["payload"]["result"]["candidates"][0]["metrics"].update(last="123"))
        with self.assertRaisesRegex(JournalVerificationError, "reproduce retained evidence"):
            self.store.verify()
        self.assert_originals_unchanged()

    def test_rehashed_quantity_tampering_fails_semantic_replay(self):
        event, evidence = self.changed_result(lambda report: report["trading_plan"].update(qty=report["trading_plan"]["qty"] + 1))
        with self.assertRaisesRegex(JournalVerificationError, "reproduce retained evidence"):
            self.store.append(event, evidence)
        self.assertEqual(self.store.verify().event_count, len(self.baseline))

    def test_rehashed_native_fact_tampering_fails_semantic_replay(self):
        event, evidence = self.changed_result(lambda report: report["native_summary"].update(oracle_state="INVENTED_NATIVE_STATE"))
        with self.assertRaisesRegex(JournalVerificationError, "reproduce retained evidence"):
            self.store.append(event, evidence)

    def test_invented_spyglass_dissent_cannot_be_appended(self):
        event, evidence = self.changed_result(lambda report: report["candidates"][0]["reason_codes"].append("SPYGLASS_DISAGREEMENT_INVENTED"))
        with self.assertRaisesRegex(JournalVerificationError, "reproduce retained evidence"):
            self.store.append(event, evidence)

    def test_native_output_tampering_rehashed_inside_bound_input_is_rejected(self):
        def mutate(analysis):
            native = analysis.get("native", analysis)
            native["outputs"]["trading_candidate_report"]["candidates"][0]["candidate_state"] = "REJECT"
            native["analysis_id"] = "shadow-native-analysis-" + sha256_bytes(canonical_json_bytes({key: item for key, item in native.items() if key != "analysis_id"}))
        event, evidence = self.changed_artifact("analysis_evidence", mutate)
        with self.assertRaisesRegex(JournalVerificationError, "does not replay"):
            self.store.append(event, evidence)

    def test_market_packet_tampering_with_updated_input_hash_is_rejected(self):
        event, evidence = self.changed_artifact("market_evidence", lambda market: market["snapshots"]["XLK"]["latestTrade"].update(p=123))
        with self.assertRaises(JournalVerificationError):
            self.store.append(event, evidence)
        self.assertEqual(self.store.verify().event_count, len(self.baseline))

    def test_actual_spyglass_and_historical_brigade_bundle_replay_without_authority(self):
        galactica = self.connect_galactica_fixture()
        self.assertTrue(any(pattern.get("confirmed") is True
                            for row in galactica["spyglass"]["observations"]
                            for pattern in row["structure"]["patterns"].get("double_top", [])))
        event, _, _ = self.append_review()
        report = self.store.events()[-1].payload["result"]
        self.assertTrue(any("BEARISH_PATTERN" in row["reason_codes"] for row in report["candidates"]))
        self.assertIn("BRIGADE_HISTORICAL_OPINIONS_ARE_CONTEXT_ONLY_NOT_CURRENT_VOTES", report["reason_codes"])
        self.assertFalse(report["readiness"])
        self.assertFalse(report["auto_trading_enabled"])
        self.assertEqual(self.store.events()[-1].to_bytes(), event.to_bytes())

    def test_rehashed_spyglass_source_facts_cannot_remove_bearish_challenge(self):
        self.connect_galactica_fixture()
        def mutate(analysis):
            for row in analysis["galactica"]["spyglass"]["observations"]:
                row["structure"]["patterns"]["double_top"] = []
        event, evidence = self.changed_artifact("analysis_evidence", mutate)
        with self.assertRaisesRegex(JournalVerificationError, "reproduce.*retained native inputs"):
            self.store.append(event, evidence)
        self.assertEqual(self.store.verify().event_count, len(self.baseline))

    def test_rehashed_brigade_source_opinions_cannot_remove_original_dissent(self):
        self.connect_galactica_fixture()
        def mutate(analysis):
            first = analysis["galactica"]["brigade"]["parsed_report"]["symbols"][0]
            self.assertTrue(first["decision"]["dissent"])
            first["decision"]["dissent"] = []
        event, evidence = self.changed_artifact("analysis_evidence", mutate)
        with self.assertRaisesRegex(JournalVerificationError, "reproduce.*retained native inputs"):
            self.store.append(event, evidence)
        self.assertEqual(self.store.verify().event_count, len(self.baseline))

    def test_missing_budget_snapshot_source_cannot_be_substituted_by_shadow_mission(self):
        event, evidence = self.event_and_evidence()
        empty = JournalStore(self.base / "empty")
        with self.assertRaisesRegex(JournalVerificationError, "source event is missing"):
            empty.append(event, evidence)
        self.assertEqual(empty.verify().event_count, 0)
        self.assertEqual(empty.verify().evidence_count, 0)

    def test_restore_verifies_without_original_native_or_source_files(self):
        event, evidence, _ = self.append_review()
        exported = self.base / "original-market-export.json"
        exported.write_bytes(evidence[self.f.document.sources["market_evidence"]["path"]])
        restored = self.base / "restored"
        shutil.copytree(self.store.root, restored)
        exported.unlink()
        with mock.patch("blackpod_build_week.shadow_native_analysis.capture_native_sources", side_effect=AssertionError("native filesystem read forbidden")):
            clone = JournalStore(restored)
            self.assertEqual(clone.verify().to_dict(), self.store.verify().to_dict())
            self.assertEqual(clone.events()[-1].to_bytes(), event.to_bytes())

    def test_missing_or_corrupt_retained_source_blocks_journal_verification(self):
        self.append_review()
        digest = self.f.document.sources["market_evidence"]["sha256"]
        copied = self.base / "missing"
        shutil.copytree(self.store.root, copied)
        (copied / "evidence" / digest).unlink()
        with self.assertRaisesRegex(JournalVerificationError, "missing or mismatched"):
            JournalStore(copied).verify()
        source = self.store.root / "evidence" / digest
        source.chmod(0o600)
        source.write_bytes(b"corrupt market evidence")
        with self.assertRaisesRegex(JournalVerificationError, "evidence hash mismatch"):
            self.store.verify()

    def test_concurrent_identical_imports_publish_one_review(self):
        event, evidence = self.event_and_evidence()
        with ThreadPoolExecutor(max_workers=3) as pool:
            results = list(pool.map(lambda _: JournalStore(self.store.root).append(event, evidence), range(3)))
        self.assertEqual(sum(result.written for result in results), 1)
        self.assertEqual(len({result.sequence for result in results}), 1)
        self.assertEqual(self.store.verify().event_count, len(self.baseline) + 1)
        self.assertEqual(self.store.verify().orphan_evidence_count, 0)
        self.assert_originals_unchanged()

    def test_precommit_interruption_retains_sources_and_recovers_exactly_once(self):
        event, evidence = self.event_and_evidence()
        def interrupt(staging, target, name, raw):
            if name.endswith(".json"):
                raise JournalPersistenceError("injected precommit interruption")
            return _publish_immutable(staging, target, name, raw)
        with mock.patch("blackpod_build_week.decision_journal_store._publish_immutable", side_effect=interrupt):
            with self.assertRaises(JournalPersistenceError):
                self.store.append(event, evidence)
        summary = self.store.verify()
        self.assertEqual(summary.event_count, len(self.baseline))
        self.assertGreater(summary.orphan_evidence_count, 0)
        self.assertTrue(self.store.append(event, evidence).written)
        self.assertFalse(self.store.append(event, evidence).written)
        self.assertEqual(self.store.verify().orphan_evidence_count, 0)
        self.assert_originals_unchanged()

    def test_postcommit_interruption_recovers_as_noop(self):
        event, evidence = self.event_and_evidence()
        def interrupt(staging, target, name, raw):
            _publish_immutable(staging, target, name, raw)
            if name.endswith(".json"):
                raise JournalPersistenceError("injected postcommit interruption")
        with mock.patch("blackpod_build_week.decision_journal_store._publish_immutable", side_effect=interrupt):
            with self.assertRaises(JournalPersistenceError):
                self.store.append(event, evidence)
        original = self.entry_bytes()
        self.assertEqual(self.store.verify().event_count, len(self.baseline) + 1)
        self.assertFalse(self.store.append(event, evidence).written)
        self.assert_originals_unchanged(original)

    def test_staged_file_fsync_failure_never_publishes_partial_entry(self):
        event, evidence = self.event_and_evidence()
        original_fsync = os.fsync
        def interrupt(descriptor):
            if os.fstat(descriptor).st_mode & 0o170000 == 0o100000:
                raise OSError("injected staged source fsync failure")
            return original_fsync(descriptor)
        with mock.patch("blackpod_build_week.decision_journal_store.os.fsync", side_effect=interrupt):
            with self.assertRaises(JournalPersistenceError):
                self.store.append(event, evidence)
        self.assertEqual(self.store.verify().event_count, len(self.baseline))
        self.assertEqual(self.store.verify().orphan_evidence_count, 0)
        self.assertTrue(self.store.append(event, evidence).written)

    def test_orphan_staging_is_reported_readonly_then_cleaned_on_retry(self):
        event, evidence, _ = self.append_review()
        orphan = self.store.root / "staging" / (".publish-" + "a" * 32 + ".tmp")
        orphan.write_bytes(b"interrupted shadow draft")
        self.assertEqual(self.store.verify().staging_orphan_count, 1)
        self.assertTrue(orphan.exists())
        self.assertFalse(self.store.append(event, evidence).written)
        self.assertFalse(orphan.exists())

    def test_internal_published_staging_hardlink_recovers_without_rewrite(self):
        event, evidence, result = self.append_review()
        path = self.store.root / "entries" / f"{result.sequence:08d}.json"
        original = path.read_bytes()
        orphan = self.store.root / "staging" / (".publish-" + "b" * 32 + ".tmp")
        os.link(path, orphan)
        self.assertEqual(self.store.verify().staging_orphan_count, 1)
        self.assertFalse(self.store.append(event, evidence).written)
        self.assertFalse(orphan.exists())
        self.assertEqual(path.stat().st_nlink, 1)
        self.assertEqual(path.read_bytes(), original)

    def test_unknown_staging_or_external_hardlink_is_never_repaired(self):
        event, evidence, result = self.append_review()
        unknown = self.store.root / "staging" / "unknown.tmp"
        unknown.write_bytes(b"preserve unknown bytes")
        with self.assertRaisesRegex(JournalVerificationError, "staging"):
            self.store.append(event, evidence)
        self.assertTrue(unknown.exists())
        unknown.unlink()
        external = self.base / "external-review.json"
        os.link(self.store.root / "entries" / f"{result.sequence:08d}.json", external)
        with self.assertRaises(JournalUnsafePathError):
            self.store.append(event, evidence)
        self.assertTrue(external.exists())


if __name__ == "__main__":
    unittest.main()
