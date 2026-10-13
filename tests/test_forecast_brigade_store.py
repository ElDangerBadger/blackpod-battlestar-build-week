"""Passive v9 mixed journals, source replay, idempotency and crash recovery."""
from __future__ import annotations

import copy
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import shutil
import socket
import tempfile
import unittest
from unittest.mock import patch

from blackpod_build_week.contracts.brigade_shadow import BrigadeShadowRequest
from blackpod_build_week.contracts.decision_journal import JournalEvent
from blackpod_build_week.contracts.forecast_intake import ForecastIntake
from blackpod_build_week.contracts.trading_automation import TradingAutomationControl
from blackpod_build_week.decision_journal_store import (
    JournalStore, JournalConflictError, JournalPersistenceError, JournalUnsafePathError, JournalVerificationError, _publish_immutable,
)
from blackpod_build_week.forecast_intake import evidence_for_forecast_intake
from blackpod_build_week.forecast_journal import build_forecast_intake_event, build_brigade_shadow_event, evidence_for_brigade_shadow
from blackpod_build_week.hashing import canonical_json_bytes, sha256_bytes
from blackpod_build_week.trading_automation import build_automation_event, evidence_for_automation
from test_forecast_brigade_journal_contracts import ForecastBrigadeJournalFixture
from test_shadow_brigade_analysis import VALID_RESPONSE


class ForecastBrigadeStoreTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(patch.object(socket.socket, "connect", side_effect=AssertionError("network forbidden")))
        self.enterContext(patch("subprocess.Popen", side_effect=AssertionError("process or inference forbidden")))
        self.enterContext(patch("blackpod_build_week.paper_account_probe.probe_paper_account", side_effect=AssertionError("broker forbidden")))
        self.enterContext(patch("blackpod_build_week.galactica_trading_adapter.run_guarded_navigator", side_effect=AssertionError("execution forbidden")))
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.base = Path(directory.name).resolve()
        self.store = JournalStore(self.base / "journal")
        self.fx = ForecastBrigadeJournalFixture()
        self.intake_evidence = evidence_for_forecast_intake(self.fx.f.intake, self.fx.blobs)
        self.store.append(self.fx.forecast_event, self.intake_evidence)
        self.original = self.entry_bytes()

    def entry_bytes(self, store=None):
        store = store or self.store
        return {path.name: path.read_bytes() for path in (store.root / "entries").iterdir()}

    def assert_originals_unchanged(self, original=None, store=None):
        store = store or self.store
        for name, raw in (original or self.original).items():
            self.assertEqual((store.root / "entries" / name).read_bytes(), raw)

    def event_and_evidence(self, request=None):
        events, retained = self.store.verified_contents()
        blobs = {**self.fx.blobs, **retained}
        request = request or self.fx.request
        return build_brigade_shadow_event(request, events, blobs), evidence_for_brigade_shadow(request, events, blobs)

    def append_brigade(self, request=None):
        event, evidence = self.event_and_evidence(request)
        return event, evidence, self.store.append(event, evidence)

    def retained_request(self, *, partial=False, empty=False, analysis_id="fixture-retained-brigade"):
        from blackpod_build_week.brigade_shadow_transport import make_transcript_bundle
        def respond(request):
            action = "EXIT" if request["member"] == "Blackwell_Sentry" else "BUY"
            return VALID_RESPONSE.replace("ACTION: BUY", "ACTION: " + action)
        records = self.fx.f.build(text_generator=respond, allow_generation=True)["response_transcripts"]
        if partial: records = records[:2]
        if empty: records = []
        value = self.fx.request.to_dict()
        value["analysis_id"] = analysis_id
        base_request = BrigadeShadowRequest.from_mapping(value)
        bundle = make_transcript_bundle(base_request, records)
        raw = canonical_json_bytes(bundle)
        value.update(inference_mode="RETAINED_TRANSCRIPT", transcript_evidence=self.fx.reference("brigade/retained-transcripts.json", raw))
        return BrigadeShadowRequest.from_mapping(value), bundle

    def rehash_last_entry(self, mutation):
        path = self.store.root / "entries" / f"{self.store.verify().event_count:08d}.json"
        entry = json.loads(path.read_bytes())
        mutation(entry["event"])
        entry["event_sha256"] = sha256_bytes(JournalEvent.from_mapping(entry["event"]).to_bytes())
        path.chmod(0o600)
        path.write_bytes(canonical_json_bytes(entry))

    def test_passive_v9_roundtrip_retains_code_market_forecasts_and_authority(self):
        event, evidence, result = self.append_brigade()
        self.assertTrue(result.written)
        self.assertEqual(result.sequence, 2)
        events, blobs = self.store.verified_contents()
        self.assertEqual(events[-1].to_bytes(), event.to_bytes())
        self.assertEqual(events[-1].decision_id, events[0].decision_id)
        for raw in evidence.values():
            digest = sha256_bytes(raw)
            self.assertEqual(blobs[digest], raw)
            self.assertEqual((self.store.root / "evidence" / digest).stat().st_mode & 0o777, 0o444)
        self.assertFalse(event.payload["analysis"]["auto_trading_enabled"])
        self.assertFalse(any(event.payload["analysis"]["authority"].values()))
        self.assertEqual(self.store.verify().orphan_evidence_count, 0)
        self.assert_originals_unchanged()

    def test_retained_five_member_votes_and_dissent_are_source_bound_and_passive(self):
        request, bundle = self.retained_request()
        event, evidence, _ = self.append_brigade(request)
        packet = event.payload["analysis"]
        self.assertEqual(packet["response_transcripts"], bundle["transcripts"])
        self.assertEqual({item["recommendation"] for item in packet["symbols"][0]["dissent"]}, {"BUY", "EXIT"})
        self.assertEqual([item["recommendation"] for item in packet["symbols"][0]["opinions"]], ["BUY", "EXIT", "BUY", "BUY", "BUY"])
        self.assertFalse(any(packet["authority"].values()))
        self.assertFalse(packet["auto_trading_enabled"])
        self.assertIn(request.transcript_evidence["path"], evidence)
        self.assertEqual(self.store.events()[-1].to_bytes(), event.to_bytes())

    def test_partial_retained_capture_defers_missing_members_and_never_retries(self):
        request, bundle = self.retained_request(partial=True)
        event, _, _ = self.append_brigade(request)
        packet = event.payload["analysis"]
        self.assertEqual(len(bundle["transcripts"]), 2)
        self.assertEqual(len(packet["response_transcripts"]), 5)
        self.assertEqual([item["recommendation"] for item in packet["symbols"][0]["opinions"]], ["BUY", "EXIT", None, None, None])
        self.assertTrue(all(item["error_code"] == "RETAINED_RESPONSE_MISSING" for item in packet["response_transcripts"][2:]))
        original = self.entry_bytes()
        rebuilt, evidence = self.event_and_evidence(request)
        self.assertFalse(self.store.append(rebuilt, evidence).written)
        self.assert_originals_unchanged(original)

    def test_empty_interrupted_capture_keeps_all_members_deferred(self):
        request, _ = self.retained_request(empty=True)
        event, _, _ = self.append_brigade(request)
        packet = event.payload["analysis"]
        self.assertTrue(all(item["recommendation"] is None for item in packet["symbols"][0]["opinions"]))
        self.assertTrue(all(item["error_code"] == "RETAINED_RESPONSE_MISSING" for item in packet["response_transcripts"]))

    def test_retained_raw_response_blob_hash_is_verified(self):
        request, bundle = self.retained_request()
        self.append_brigade(request)
        bundle["transcripts"][0]["response_text"] = VALID_RESPONSE.replace("BUY", "EXIT")
        path = self.store.root / "evidence" / request.transcript_evidence["sha256"]
        path.chmod(0o600)
        path.write_bytes(canonical_json_bytes(bundle))
        with self.assertRaisesRegex(JournalVerificationError, "evidence hash mismatch"):
            self.store.verify()

    def test_rehashed_changed_response_cannot_preserve_original_recommendation(self):
        request, bundle = self.retained_request()
        event, evidence = self.event_and_evidence(request)
        value = event.to_dict()
        bundle["transcripts"][0]["response_text"] = VALID_RESPONSE.replace("BUY", "EXIT")
        changed_raw = canonical_json_bytes(bundle)
        changed_ref = {**request.transcript_evidence, "sha256": sha256_bytes(changed_raw), "size_bytes": len(changed_raw)}
        value["payload"]["request"]["transcript_evidence"] = changed_ref
        changed_request = BrigadeShadowRequest.from_mapping(value["payload"]["request"])
        value["source"]["source_sha256"] = sha256_bytes(changed_request.to_bytes())
        for reference in value["evidence"]:
            if reference["path"] == changed_ref["path"]: reference.update(changed_ref)
            if reference["path"] == "brigade-shadow/request.v1.json":
                reference.update(sha256=sha256_bytes(changed_request.to_bytes()), size_bytes=len(changed_request.to_bytes()))
        forged = JournalEvent.from_mapping(value)
        supplied = {**evidence, changed_ref["path"]: changed_raw, "brigade-shadow/request.v1.json": changed_request.to_bytes()}
        with self.assertRaisesRegex(JournalVerificationError, "retained evidence replay"):
            self.store.append(forged, supplied)
        self.assertEqual(self.store.verify().event_count, 1)
        self.assertEqual(self.store.verify().orphan_evidence_count, 0)

    def test_changed_retained_response_under_same_analysis_identity_conflicts(self):
        request, bundle = self.retained_request()
        first, _, _ = self.append_brigade(request)
        bundle["transcripts"][0]["response_text"] = VALID_RESPONSE.replace("BUY", "HOLD")
        raw = canonical_json_bytes(bundle)
        value = request.to_dict()
        value["transcript_evidence"] = self.fx.reference("brigade/retained-transcripts.json", raw)
        changed_request = BrigadeShadowRequest.from_mapping(value)
        different, evidence = self.event_and_evidence(changed_request)
        self.assertEqual(first.event_id, different.event_id)
        with self.assertRaises(JournalConflictError): self.store.append(different, evidence)
        self.assertEqual(self.store.verify().event_count, 2)

    def test_rehashed_transcript_bindings_cannot_change_source_analysis_identity(self):
        request, bundle = self.retained_request()
        for field, replacement in (("analysis_id", "another-analysis"), ("market_sha256", "0" * 64),
                                   ("brigade_sha256", "0" * 64), ("intake_source_sha256", "0" * 64)):
            with self.subTest(field=field):
                changed = copy.deepcopy(bundle)
                changed[field] = replacement
                raw = canonical_json_bytes(changed)
                value = request.to_dict()
                value["transcript_evidence"] = self.fx.reference("brigade/retained-transcripts.json", raw)
                with self.assertRaisesRegex(ValueError, "source bindings"):
                    self.event_and_evidence(BrigadeShadowRequest.from_mapping(value))
        self.assertEqual(self.store.verify().event_count, 1)

    def test_rehashed_transcript_prompt_cannot_bypass_original_native_request(self):
        request, bundle = self.retained_request()
        bundle["transcripts"][0]["request"]["prompt"] = "Invented prompt with altered evidence."
        raw = canonical_json_bytes(bundle)
        value = request.to_dict()
        value["transcript_evidence"] = self.fx.reference("brigade/retained-transcripts.json", raw)
        with self.assertRaisesRegex(ValueError, "native prompt/context"):
            self.event_and_evidence(BrigadeShadowRequest.from_mapping(value))
        self.assertEqual(self.store.verify().event_count, 1)

    def test_exact_intake_retry_after_brigade_is_noop(self):
        self.append_brigade()
        original = self.entry_bytes()
        result = self.store.append(build_forecast_intake_event(self.fx.f.intake, self.store.events(), self.fx.blobs), self.intake_evidence)
        self.assertFalse(result.written)
        self.assertEqual(result.sequence, 1)
        self.assert_originals_unchanged(original)

    def test_exact_brigade_retry_after_later_review_and_off_control_is_noop(self):
        first, evidence, result = self.append_brigade()
        later_value = self.fx.request.to_dict()
        later_value.update(analysis_id="fixture-later-brigade", recorded_at="2026-10-12T20:03:00Z")
        self.append_brigade(BrigadeShadowRequest.from_mapping(later_value))
        off = TradingAutomationControl.from_mapping({"schema_version": "blackpod.trading_automation_control.v1",
            "control_id": "fixture-brigade-off", "operator_id": "fixture-reviewer", "recorded_at": "2026-10-12T20:04:00Z",
            "switch_id": "auto-trading", "requested_enabled": False, "scope": "TRADING_CONTROL_INTENT_ONLY",
            "domain": "TRADING", "execution_mode": "DISABLED", "origin": "SIMULATED_TEST"})
        self.store.append(build_automation_event(off), evidence_for_automation(off))
        original = self.entry_bytes()
        rebuilt, replay_evidence = self.event_and_evidence()
        self.assertEqual(rebuilt.to_bytes(), first.to_bytes())
        self.assertEqual(replay_evidence, evidence)
        retry = self.store.append(rebuilt, replay_evidence)
        self.assertFalse(retry.written)
        self.assertEqual(retry.sequence, result.sequence)
        self.assert_originals_unchanged(original)

    def test_same_brigade_identity_with_changed_symbols_conflicts(self):
        first, _, _ = self.append_brigade()
        value = self.fx.request.to_dict()
        value["symbols"] = ["SPY"]
        different, evidence = self.event_and_evidence(BrigadeShadowRequest.from_mapping(value))
        self.assertEqual(different.event_id, first.event_id)
        original = self.store.verify().to_dict()
        with self.assertRaises(JournalConflictError): self.store.append(different, evidence)
        self.assertEqual(self.store.verify().to_dict(), original)

    def test_same_forecast_identity_with_changed_source_hash_conflicts(self):
        value = self.fx.f.intake.to_dict()
        # Dropping provenance is a real semantic change, preserved as DEFER.
        value["sources"][0]["provenance_evidence"] = None
        different = ForecastIntake.from_mapping(value)
        event = build_forecast_intake_event(different, blobs=self.fx.blobs)
        evidence = evidence_for_forecast_intake(different, self.fx.blobs)
        self.assertEqual(event.event_id, self.fx.forecast_event.event_id)
        with self.assertRaises(JournalConflictError): self.store.append(event, evidence)
        self.assertEqual(self.store.verify().event_count, 1)
        self.assert_originals_unchanged()

    def test_investment_intake_is_a_separate_decision_with_no_short_horizon_admission(self):
        value = self.fx.f.intake.to_dict()
        value.update(domain="INVESTMENT", intake_id="fixture-investment-domain")
        intake = ForecastIntake.from_mapping(value)
        event = build_forecast_intake_event(intake, blobs=self.fx.blobs)
        self.store.append(event, evidence_for_forecast_intake(intake, self.fx.blobs))
        self.assertNotEqual(event.decision_id, self.fx.forecast_event.decision_id)
        self.assertEqual(self.store.events()[-1].payload["result"]["admitted_count"], 0)
        self.assert_originals_unchanged()

    def test_missing_forecast_predecessor_cannot_be_substituted_by_payload(self):
        event, evidence = self.event_and_evidence()
        empty = JournalStore(self.base / "empty")
        with self.assertRaisesRegex(JournalVerificationError, "preceding verified forecast"):
            empty.append(event, evidence)
        self.assertEqual(empty.verify().event_count, 0)
        self.assertEqual(empty.verify().evidence_count, 0)

    def test_missing_market_code_or_proof_cannot_publish(self):
        event, evidence = self.event_and_evidence()
        for missing in ("brigade/market-packet.json", "brigade/decay.py", "brigade/blackwell_brigade.py"):
            with self.subTest(missing=missing):
                supplied = {path: raw for path, raw in evidence.items() if path != missing}
                with self.assertRaises(JournalVerificationError): self.store.append(event, supplied)
                self.assertEqual(self.store.verify().event_count, 1)
                self.assertEqual(self.store.verify().orphan_evidence_count, 0)

    def test_hash_mismatch_is_rejected_before_evidence_publication(self):
        event, evidence = self.event_and_evidence()
        supplied = {**evidence, "brigade/decay.py": evidence["brigade/decay.py"] + b"\n# changed"}
        with self.assertRaisesRegex(JournalVerificationError, "hash mismatch"):
            self.store.append(event, supplied)
        self.assertEqual(self.store.verify().event_count, 1)
        self.assertEqual(self.store.verify().orphan_evidence_count, 0)

    def test_rehashed_modified_native_code_is_rejected_by_source_pin(self):
        event, evidence = self.event_and_evidence()
        value = event.to_dict()
        changed_raw = self.fx.f.decay + b"\n# altered native source, never execute\n"
        changed_ref = {"path": "brigade/decay.py", "sha256": sha256_bytes(changed_raw), "size_bytes": len(changed_raw)}
        value["payload"]["request"]["source_evidence"]["decay"] = changed_ref
        request = BrigadeShadowRequest.from_mapping(value["payload"]["request"])
        value["source"]["source_sha256"] = sha256_bytes(request.to_bytes())
        value["payload"]["analysis"]["source_evidence"]["decay"] = changed_ref
        for reference in value["evidence"]:
            if reference["path"] == "brigade/decay.py": reference.update(changed_ref)
            if reference["path"] == "brigade-shadow/request.v1.json":
                reference.update(sha256=sha256_bytes(request.to_bytes()), size_bytes=len(request.to_bytes()))
        forged = JournalEvent.from_mapping(value)
        supplied = {**evidence, "brigade/decay.py": changed_raw, "brigade-shadow/request.v1.json": request.to_bytes()}
        with self.assertRaisesRegex(JournalVerificationError, "reviewed source pin"):
            self.store.append(forged, supplied)
        self.assertEqual(self.store.verify().event_count, 1)
        self.assertEqual(self.store.verify().orphan_evidence_count, 0)

    def test_rehashed_changed_forecast_input_cannot_rewrite_original_link(self):
        event, evidence = self.event_and_evidence()
        intake_value = self.fx.f.intake.to_dict()
        intake_value["sources"][0]["provenance_evidence"] = None
        changed_intake = ForecastIntake.from_mapping(intake_value)
        value = event.to_dict()
        changed_ref = {"path": "brigade/forecast-intake.json", "sha256": sha256_bytes(changed_intake.to_bytes()), "size_bytes": len(changed_intake.to_bytes())}
        value["payload"]["request"]["forecast"].update(intake_source_sha256=changed_ref["sha256"], intake_evidence=changed_ref)
        request = BrigadeShadowRequest.from_mapping(value["payload"]["request"])
        value["source"]["source_sha256"] = sha256_bytes(request.to_bytes())
        for reference in value["evidence"]:
            if reference["path"] == changed_ref["path"]: reference.update(changed_ref)
            if reference["path"] == "brigade-shadow/request.v1.json":
                reference.update(sha256=sha256_bytes(request.to_bytes()), size_bytes=len(request.to_bytes()))
        forged = JournalEvent.from_mapping(value)
        supplied = {**evidence, changed_ref["path"]: changed_intake.to_bytes(), "brigade-shadow/request.v1.json": request.to_bytes()}
        with self.assertRaisesRegex(JournalVerificationError, "verified original event"):
            self.store.append(forged, supplied)
        self.assertEqual(self.store.verify().event_count, 1)
        self.assert_originals_unchanged()

    def test_rehashed_forecast_price_fact_cannot_change_retained_source_projection(self):
        self.rehash_last_entry(lambda event: event["payload"]["result"]["rows"][0].update(q50="102.5"))
        with self.assertRaisesRegex(JournalVerificationError, "retained source projection"):
            self.store.verify()

    def test_rehashed_native_context_is_rejected(self):
        self.append_brigade()
        self.rehash_last_entry(lambda event: event["payload"]["analysis"]["symbols"][0]["context"].update(q50="999.0"))
        with self.assertRaisesRegex(JournalVerificationError, "retained evidence replay"):
            self.store.verify()
        self.assert_originals_unchanged()

    def test_rehashed_invented_vote_is_rejected(self):
        self.append_brigade()
        self.rehash_last_entry(lambda event: event["payload"]["analysis"]["symbols"][0]["opinions"][0].update(
            recommendation="BUY", confidence_label="0.99", status="SHADOW_RECOMMENDATION"))
        with self.assertRaisesRegex(JournalVerificationError, "retained evidence replay"):
            self.store.verify()
        self.assert_originals_unchanged()

    def test_rehashed_invented_dissent_is_rejected(self):
        self.append_brigade()
        self.rehash_last_entry(lambda event: event["payload"]["analysis"]["symbols"][0]["dissent"].append(
            {"member": "Blackwell_Sentry", "recommendation": "EXIT"}))
        with self.assertRaisesRegex(JournalVerificationError, "retained evidence replay"):
            self.store.verify()

    def test_rehashed_native_parser_response_fact_is_rejected(self):
        self.append_brigade()
        self.rehash_last_entry(lambda event: event["payload"]["analysis"]["response_transcripts"][0]["request"].update(prompt="Invented prompt"))
        with self.assertRaisesRegex(JournalVerificationError, "retained evidence replay"):
            self.store.verify()

    def test_missing_or_corrupt_retained_source_blocks_verify(self):
        self.append_brigade()
        digest = self.fx.request.market_evidence["sha256"]
        copied = self.base / "missing"
        shutil.copytree(self.store.root, copied)
        (copied / "evidence" / digest).unlink()
        with self.assertRaises(JournalVerificationError): JournalStore(copied).verify()
        source = self.store.root / "evidence" / digest
        source.chmod(0o600)
        source.write_bytes(b"corrupt evidence")
        with self.assertRaisesRegex(JournalVerificationError, "hash mismatch"):
            self.store.verify()

    def test_restored_journal_replays_without_original_paths_or_native_applications(self):
        event, _, _ = self.append_brigade()
        restored = self.base / "restored"
        shutil.copytree(self.store.root, restored)
        self.fx.blobs.clear()
        with patch("blackpod_build_week.shadow_native_analysis.capture_native_sources", side_effect=AssertionError("native source read forbidden")):
            clone = JournalStore(restored)
            self.assertEqual(clone.verify().to_dict(), self.store.verify().to_dict())
            self.assertEqual(clone.events()[-1].to_bytes(), event.to_bytes())

    def test_concurrent_identical_imports_append_exactly_once(self):
        event, evidence = self.event_and_evidence()
        with ThreadPoolExecutor(max_workers=3) as pool:
            results = list(pool.map(lambda _: JournalStore(self.store.root).append(event, evidence), range(3)))
        self.assertEqual(sum(result.written for result in results), 1)
        self.assertEqual(len({result.sequence for result in results}), 1)
        self.assertEqual(self.store.verify().event_count, 2)
        self.assertEqual(self.store.verify().orphan_evidence_count, 0)

    def test_precommit_interruption_retains_evidence_then_recovers_exactly_once(self):
        event, evidence = self.event_and_evidence()
        def interrupt(staging, target, name, raw):
            if name.endswith(".json"): raise JournalPersistenceError("injected precommit interruption")
            return _publish_immutable(staging, target, name, raw)
        with patch("blackpod_build_week.decision_journal_store._publish_immutable", side_effect=interrupt):
            with self.assertRaises(JournalPersistenceError): self.store.append(event, evidence)
        self.assertEqual(self.store.verify().event_count, 1)
        self.assertGreater(self.store.verify().orphan_evidence_count, 0)
        self.assertTrue(self.store.append(event, evidence).written)
        self.assertFalse(self.store.append(event, evidence).written)
        self.assertEqual(self.store.verify().orphan_evidence_count, 0)
        self.assert_originals_unchanged()

    def test_postcommit_interruption_recovers_as_noop_without_rewrite(self):
        event, evidence = self.event_and_evidence()
        def interrupt(staging, target, name, raw):
            _publish_immutable(staging, target, name, raw)
            if name.endswith(".json"): raise JournalPersistenceError("injected postcommit interruption")
        with patch("blackpod_build_week.decision_journal_store._publish_immutable", side_effect=interrupt):
            with self.assertRaises(JournalPersistenceError): self.store.append(event, evidence)
        original = self.entry_bytes()
        self.assertEqual(self.store.verify().event_count, 2)
        self.assertFalse(self.store.append(event, evidence).written)
        self.assert_originals_unchanged(original)

    def test_staged_fsync_failure_does_not_publish_partial_entry(self):
        event, evidence = self.event_and_evidence()
        original = os.fsync
        def fail(descriptor):
            if os.fstat(descriptor).st_mode & 0o170000 == 0o100000: raise OSError("injected fsync failure")
            return original(descriptor)
        with patch("blackpod_build_week.decision_journal_store.os.fsync", side_effect=fail):
            with self.assertRaises(JournalPersistenceError): self.store.append(event, evidence)
        self.assertEqual(self.store.verify().event_count, 1)
        self.assertTrue(self.store.append(event, evidence).written)

    def test_orphan_staging_is_readonly_reported_and_cleaned_only_on_retry(self):
        event, evidence, _ = self.append_brigade()
        orphan = self.store.root / "staging" / (".publish-" + "a" * 32 + ".tmp")
        orphan.write_bytes(b"interrupted source capture")
        self.assertEqual(self.store.verify().staging_orphan_count, 1)
        self.assertTrue(orphan.exists())
        self.assertFalse(self.store.append(event, evidence).written)
        self.assertFalse(orphan.exists())

    def test_internal_staging_hardlink_recovers_without_rewriting_published_entry(self):
        event, evidence, result = self.append_brigade()
        path = self.store.root / "entries" / f"{result.sequence:08d}.json"
        original = path.read_bytes()
        orphan = self.store.root / "staging" / (".publish-" + "b" * 32 + ".tmp")
        os.link(path, orphan)
        self.assertEqual(self.store.verify().staging_orphan_count, 1)
        self.assertFalse(self.store.append(event, evidence).written)
        self.assertFalse(orphan.exists())
        self.assertEqual(path.stat().st_nlink, 1)
        self.assertEqual(path.read_bytes(), original)

    def test_unknown_staging_and_external_hardlinks_are_never_repaired(self):
        event, evidence, result = self.append_brigade()
        unknown = self.store.root / "staging" / "unknown.tmp"
        unknown.write_bytes(b"preserve unknown bytes")
        with self.assertRaises(JournalVerificationError): self.store.append(event, evidence)
        self.assertTrue(unknown.exists())
        unknown.unlink()
        external = self.base / "external-entry.json"
        os.link(self.store.root / "entries" / f"{result.sequence:08d}.json", external)
        with self.assertRaises(JournalUnsafePathError): self.store.append(event, evidence)
        self.assertTrue(external.exists())

    def test_mixed_v1_through_v9_preserves_original_decision_and_execution_semantics(self):
        from blackpod_build_week import desk_candidate_review, trading_accounting
        from blackpod_build_week.contracts.desk_candidate_review import DeskReviewInput
        from blackpod_build_week.paper_test_budget import build_paper_test_budget
        from test_desk_candidate_review_engine import DeskReviewFixture
        from test_investment_approval import ApprovalFixture
        from test_trading_accounting_engine import AccountingFixture
        legacy, accounting, desk = ApprovalFixture(), AccountingFixture(), DeskReviewFixture()
        for fixture in (legacy, accounting, desk): self.addCleanup(fixture.close)
        mixed = JournalStore(self.base / "mixed")
        for event in legacy.events: mixed.append(event, legacy.blobs)
        off = TradingAutomationControl.from_mapping({"schema_version": "blackpod.trading_automation_control.v1",
            "control_id": "fixture-mixed-brigade-off", "operator_id": "fixture-reviewer", "recorded_at": desk.document.recorded_at,
            "switch_id": "auto-trading", "requested_enabled": False, "scope": "TRADING_CONTROL_INTENT_ONLY",
            "domain": "TRADING", "execution_mode": "DISABLED", "origin": "SIMULATED_TEST"})
        mixed.append(build_automation_event(off), evidence_for_automation(off))
        for event in accounting.events: mixed.append(event, accounting.blobs)
        events, retained = mixed.verified_contents()
        account_blobs = {**accounting.blobs, **retained}
        accounting_event = trading_accounting.build_accounting_event(accounting.accounting, events, account_blobs)
        mixed.append(accounting_event, trading_accounting.evidence_for_accounting(accounting.accounting, events, account_blobs))
        budget = build_paper_test_budget(accounting.start_event, budget_id="fixture-mixed-brigade-budget",
            recorded_at=desk.budget.recorded_at, declared_by=desk.budget.declared_by)
        raw = budget.to_bytes()
        desk.blobs[sha256_bytes(raw)] = raw
        value = desk.document.to_dict()
        value["budget"] = {"proposal_evidence": {"path": "shadow-desk/mixed-budget.json", "sha256": sha256_bytes(raw), "size_bytes": len(raw)},
            "source_snapshot_event_id": accounting.start_event.event_id, "source_snapshot_sha256": accounting.start_event.source["source_sha256"]}
        review = DeskReviewInput.from_mapping(value)
        events, retained = mixed.verified_contents()
        desk_blobs = {**desk.blobs, **retained}
        mixed.append(desk_candidate_review.build_desk_review_event(review, events, desk_blobs),
                     desk_candidate_review.evidence_for_desk_review(review, events, desk_blobs))
        original = self.entry_bytes(mixed)
        mixed.append(self.fx.forecast_event, self.intake_evidence)
        events, retained = mixed.verified_contents()
        all_blobs = {**self.fx.blobs, **retained}
        event = build_brigade_shadow_event(self.fx.request, events, all_blobs)
        mixed.append(event, evidence_for_brigade_shadow(self.fx.request, events, all_blobs))
        versions = {item.schema_version for item in mixed.events()}
        self.assertEqual(versions, {"blackpod.decision_journal_event.v" + str(i) for i in range(1, 10)})
        self.assertEqual(accounting_event.payload["result"]["realized_trade_pnl"], "15.92")
        self.assertFalse(any(event.payload["analysis"]["authority"].values()))
        for item in mixed.events():
            if item.event_type == "MISSION_SNAPSHOT_RECORDED":
                self.assertIn(item.payload["execution_status"], {"NOT_EXECUTED", "SHADOW_ONLY"})
                self.assertIsNone(item.payload.get("realized_trade_pnl"))
        self.assert_originals_unchanged(original, mixed)
        self.assertEqual(mixed.verify().orphan_evidence_count, 0)


if __name__ == "__main__": unittest.main()
