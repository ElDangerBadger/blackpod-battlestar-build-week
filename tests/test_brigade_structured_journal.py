"""Mixed historical and structured journals retain no-authority provenance."""
from __future__ import annotations

import copy
import json
from pathlib import Path
import socket
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from blackpod_build_week.brigade_shadow_transport import make_transcript_bundle
from blackpod_build_week.contracts.brigade_shadow import BrigadeShadowRequest
from blackpod_build_week.contracts.decision_journal import JournalEvent
from blackpod_build_week.contracts.mission_request import ContractValidationError
from blackpod_build_week.decision_journal_store import (
    JournalStore, JournalConflictError, JournalPersistenceError, JournalVerificationError, _publish_immutable,
)
from blackpod_build_week.forecast_intake import evidence_for_forecast_intake
from blackpod_build_week.forecast_journal import build_brigade_shadow_event, evidence_for_brigade_shadow
from blackpod_build_week.hashing import canonical_json_bytes, sha256_bytes
from test_brigade_structured_analysis import RESPONSE_CONTRACT, structured_text
from test_forecast_brigade_journal_contracts import ForecastBrigadeJournalFixture


class BrigadeStructuredJournalTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(patch.object(socket.socket, "connect", side_effect=AssertionError("network forbidden")))
        self.enterContext(patch.object(subprocess, "Popen", side_effect=AssertionError("inference forbidden")))
        self.enterContext(patch("blackpod_build_week.galactica_trading_adapter.run_guarded_navigator", side_effect=AssertionError("execution forbidden")))
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.store = JournalStore(Path(directory.name).resolve() / "journal")
        self.fx = ForecastBrigadeJournalFixture()
        self.store.append(self.fx.forecast_event, evidence_for_forecast_intake(self.fx.f.intake, self.fx.blobs))
        self.original = self.entries()

    def entries(self):
        return {p.name: p.read_bytes() for p in (self.store.root / "entries").iterdir()}

    def assert_originals(self, saved=None):
        for name, raw in (saved or self.original).items():
            self.assertEqual((self.store.root / "entries" / name).read_bytes(), raw)

    def request(self, *, analysis_id="fixture-structured-brigade", retained=False, responder=structured_text, partial=False):
        value = self.fx.request.to_dict()
        value.update(schema_version="blackpod.brigade_shadow_request.v2", response_contract=RESPONSE_CONTRACT, analysis_id=analysis_id)
        request = BrigadeShadowRequest.from_mapping(value)
        if retained:
            records = self.fx.f.build(response_contract=RESPONSE_CONTRACT, text_generator=responder, allow_generation=True)["response_transcripts"]
            if partial: records = records[:2]
            bundle = make_transcript_bundle(request, records)
            value.update(inference_mode="RETAINED_TRANSCRIPT", transcript_evidence=self.fx.reference("brigade/structured-transcripts.json", canonical_json_bytes(bundle)))
            request = BrigadeShadowRequest.from_mapping(value)
        return request

    def event_evidence(self, request=None):
        request = request or self.request()
        events, retained = self.store.verified_contents()
        blobs = {**self.fx.blobs, **retained}
        return build_brigade_shadow_event(request, events, blobs), evidence_for_brigade_shadow(request, events, blobs)

    def append(self, request=None):
        event, evidence = self.event_evidence(request)
        return event, evidence, self.store.append(event, evidence)

    def reject_request(self, mutation):
        value = self.request().to_dict()
        mutation(value)
        with self.assertRaises(ContractValidationError): BrigadeShadowRequest.from_mapping(value)

    def rehash_last(self, mutation):
        path = self.store.root / "entries" / f"{self.store.verify().event_count:08d}.json"
        entry = json.loads(path.read_bytes())
        mutation(entry["event"])
        entry["event_sha256"] = sha256_bytes(JournalEvent.from_mapping(entry["event"]).to_bytes())
        path.chmod(0o600)
        path.write_bytes(canonical_json_bytes(entry))

    def test_v2_request_has_strict_required_contract_and_immutable_roundtrip(self):
        request = self.request()
        self.assertEqual(BrigadeShadowRequest.from_bytes(request.to_bytes()).to_bytes(), request.to_bytes())
        value = request.to_dict()
        value["response_contract"] = "changed"
        self.assertEqual(request.response_contract, RESPONSE_CONTRACT)
        for mutation in (lambda v: v.pop("response_contract"), lambda v: v.update(response_contract=None),
                         lambda v: v.update(response_contract="blackpod.brigade_member_response.v2"), lambda v: v.update(extra=True)):
            self.reject_request(mutation)

    def test_v1_fieldset_unchanged_and_v1_cannot_claim_response_contract(self):
        old = self.fx.request.to_dict()
        self.assertNotIn("response_contract", old)
        self.assertEqual(BrigadeShadowRequest.from_mapping(old).to_bytes(), self.fx.request.to_bytes())
        old["response_contract"] = RESPONSE_CONTRACT
        with self.assertRaises(ContractValidationError): BrigadeShadowRequest.from_mapping(old)

    def test_v2_authority_scope_domain_and_inference_guards_remain(self):
        for field in self.fx.request.authority:
            self.reject_request(lambda v: v["authority"].update({field: True}))
        for field, replacement in (("domain", "INVESTMENT"), ("mode", "PAPER"), ("scope", "ORDER_EXECUTION"), ("inference_mode", "LIVE")):
            self.reject_request(lambda v: v.update({field: replacement}))

    def test_version_shapes_and_wrong_types_reject_cleanly(self):
        for version in (None, 1, True, [], {}, "blackpod.brigade_shadow_request.v3"):
            self.reject_request(lambda v: v.update(schema_version=version))

    def test_v11_uses_versioned_reserved_path_and_preserves_forecast_predecessor(self):
        event, evidence, result = self.append()
        self.assertTrue(result.written)
        self.assertEqual(event.schema_version, "blackpod.decision_journal_event.v11")
        self.assertEqual(event.payload["analysis"]["schema_version"], "blackpod.shadow_brigade_analysis.v2")
        self.assertIn("brigade-shadow/request.v2.json", evidence)
        self.assertNotIn("brigade-shadow/request.v1.json", evidence)
        self.assertEqual(event.decision_id, self.fx.forecast_event.decision_id)
        self.assertFalse(any(event.payload["analysis"]["authority"].values()))
        self.assertFalse(event.payload["analysis"]["auto_trading_enabled"])
        self.assertEqual(JournalEvent.from_bytes(event.to_bytes()).to_bytes(), event.to_bytes())
        self.assert_originals()

    def test_journal_v9_rejects_v2_and_v11_rejects_old_request_or_forecast(self):
        structured = self.event_evidence()[0].to_dict()
        structured["schema_version"] = "blackpod.decision_journal_event.v9"
        with self.assertRaises(ContractValidationError): JournalEvent.from_mapping(structured)
        legacy = build_brigade_shadow_event(self.fx.request, (self.fx.forecast_event,), self.fx.blobs).to_dict()
        legacy["schema_version"] = "blackpod.decision_journal_event.v11"
        with self.assertRaises(ContractValidationError): JournalEvent.from_mapping(legacy)
        forecast = self.fx.forecast_event.to_dict()
        forecast["schema_version"] = "blackpod.decision_journal_event.v11"
        with self.assertRaises(ContractValidationError): JournalEvent.from_mapping(forecast)

    def test_v11_rejects_wrong_response_contract_analysis_version_and_authority(self):
        original = self.event_evidence()[0].to_dict()
        for mutation in (lambda p: p.update(response_contract="unknown"), lambda p: p.update(schema_version="blackpod.shadow_brigade_analysis.v1"),
                         lambda p: p.pop("response_contract"), lambda p: p.update(auto_trading_enabled=True),
                         lambda p: p["authority"].update(execution_enabled=True)):
            value = copy.deepcopy(original)
            mutation(value["payload"]["analysis"])
            with self.assertRaises(ContractValidationError): JournalEvent.from_mapping(value)

    def test_mixed_v9_v11_chain_keeps_originals_and_replays_offline(self):
        legacy, evidence = self.event_evidence(self.fx.request)
        self.store.append(legacy, evidence)
        saved = self.entries()
        new, evidence, _ = self.append(self.request(retained=True))
        self.assertEqual([e.schema_version for e in self.store.events()], ["blackpod.decision_journal_event.v9", "blackpod.decision_journal_event.v9", "blackpod.decision_journal_event.v11"])
        self.assertEqual(self.store.events()[1].to_bytes(), legacy.to_bytes())
        self.assertEqual(self.store.events()[2].to_bytes(), new.to_bytes())
        self.assertEqual(self.store.verify().orphan_evidence_count, 0)
        self.assert_originals(saved)

    def test_exact_retry_after_later_v1_review_returns_original_noop(self):
        request = self.request(retained=True)
        original, evidence, first = self.append(request)
        legacy = self.fx.request.to_dict()
        legacy["analysis_id"] = "fixture-later-legacy"
        self.append(BrigadeShadowRequest.from_mapping(legacy))
        saved = self.entries()
        rebuilt, evidence = self.event_evidence(request)
        self.assertEqual(rebuilt.to_bytes(), original.to_bytes())
        retry = self.store.append(rebuilt, evidence)
        self.assertFalse(retry.written)
        self.assertEqual(retry.sequence, first.sequence)
        self.assert_originals(saved)

    def test_same_analysis_identity_different_contract_version_conflicts(self):
        self.append(self.fx.request)
        structured = self.request(analysis_id=self.fx.request.analysis_id)
        event, evidence = self.event_evidence(structured)
        with self.assertRaises(JournalConflictError): self.store.append(event, evidence)
        self.assertEqual(self.store.verify().event_count, 2)

    def test_partial_retained_capture_appends_explicit_missing_defer(self):
        event, _, _ = self.append(self.request(retained=True, partial=True))
        packet = event.payload["analysis"]
        self.assertEqual([o["recommendation"] for o in packet["symbols"][0]["opinions"]], ["BUY", "BUY", None, None, None])
        self.assertTrue(all(o["structured_response"] is None for o in packet["symbols"][0]["opinions"][2:]))
        self.assertEqual(self.store.verify().orphan_evidence_count, 0)

    def test_invalid_raw_response_is_retained_and_not_promoted(self):
        event, evidence, _ = self.append(self.request(retained=True, responder=lambda _r: "ACTION: BUY\nCONFIDENCE: 0.8\nREASONING: legacy"))
        packet = event.payload["analysis"]
        self.assertTrue(all(o["recommendation"] is None for o in packet["symbols"][0]["opinions"]))
        self.assertTrue(all(c["reason_codes"] == ["STRUCTURED_RESPONSE_INVALID"] for c in packet["symbols"][0]["member_coverage"]))
        self.assertIn(b"ACTION: BUY", next(raw for path, raw in evidence.items() if path.endswith("structured-transcripts.json")))
        self.assertEqual(self.store.events()[-1].to_bytes(), event.to_bytes())

    def test_bundle_request_version_mix_rejects_even_after_rehash(self):
        request = self.request(retained=True)
        raw = self.fx.blobs[request.transcript_evidence["sha256"]]
        bundle = json.loads(raw)
        for change in (lambda b: b.update(schema_version="blackpod.brigade_shadow_transcripts.v1"), lambda b: b.pop("response_contract"), lambda b: b.update(response_contract="different")):
            changed = copy.deepcopy(bundle)
            change(changed)
            value = request.to_dict()
            value["transcript_evidence"] = self.fx.reference(request.transcript_evidence["path"], canonical_json_bytes(changed))
            with self.assertRaisesRegex(ValueError, "bindings|missing"):
                self.event_evidence(BrigadeShadowRequest.from_mapping(value))

    def test_rehashed_structured_projection_tamper_blocks_verification(self):
        self.append(self.request(retained=True))
        self.rehash_last(lambda e: e["payload"]["analysis"]["symbols"][0]["opinions"][0]["structured_response"].update(action="EXIT"))
        with self.assertRaisesRegex(JournalVerificationError, "retained evidence replay"): self.store.verify()
        self.assert_originals()

    def test_rehashed_native_projection_tamper_blocks_verification(self):
        self.append(self.request(retained=True))
        self.rehash_last(lambda e: e["payload"]["analysis"]["symbols"][0]["opinions"][0].update(native_response_projection="ACTION: EXIT"))
        with self.assertRaisesRegex(JournalVerificationError, "retained evidence replay"): self.store.verify()

    def test_rehashed_valid_raw_changed_vote_cannot_preserve_old_opinion(self):
        request = self.request(retained=True)
        event, evidence = self.event_evidence(request)
        bundle = json.loads(self.fx.blobs[request.transcript_evidence["sha256"]])
        response = json.loads(bundle["transcripts"][0]["response_text"])
        response["action"] = "EXIT"
        bundle["transcripts"][0]["response_text"] = canonical_json_bytes(response).decode()
        raw = canonical_json_bytes(bundle)
        value = event.to_dict()
        changed_ref = self.fx.reference(request.transcript_evidence["path"], raw)
        value["payload"]["request"]["transcript_evidence"] = changed_ref
        changed = BrigadeShadowRequest.from_mapping(value["payload"]["request"])
        value["source"]["source_sha256"] = sha256_bytes(changed.to_bytes())
        for ref in value["evidence"]:
            if ref["path"] == changed_ref["path"]: ref.update(changed_ref)
            if ref["path"] == "brigade-shadow/request.v2.json":
                ref.update(sha256=sha256_bytes(changed.to_bytes()), size_bytes=len(changed.to_bytes()))
        supplied = {**evidence, changed_ref["path"]: raw, "brigade-shadow/request.v2.json": changed.to_bytes()}
        with self.assertRaisesRegex(JournalVerificationError, "retained evidence replay"):
            self.store.append(JournalEvent.from_mapping(value), supplied)
        self.assertEqual(self.store.verify().event_count, 1)
        self.assertEqual(self.store.verify().orphan_evidence_count, 0)

    def test_precommit_interruption_recovers_exact_original_once(self):
        event, evidence = self.event_evidence(self.request(retained=True))
        def interrupted(staging, target, name, raw):
            if name.endswith(".json"): raise JournalPersistenceError("injected precommit")
            return _publish_immutable(staging, target, name, raw)
        with patch("blackpod_build_week.decision_journal_store._publish_immutable", side_effect=interrupted):
            with self.assertRaises(JournalPersistenceError): self.store.append(event, evidence)
        self.assertEqual(self.store.verify().event_count, 1)
        recovered = self.store.append(event, evidence)
        self.assertTrue(recovered.written)
        self.assertFalse(self.store.append(event, evidence).written)
        self.assertEqual(self.store.verify().event_count, 2)
        self.assertEqual(self.store.verify().orphan_evidence_count, 0)
        self.assert_originals()

    def test_postcommit_interruption_recovers_noop_without_rewrite(self):
        event, evidence = self.event_evidence(self.request(retained=True))
        def interrupted(staging, target, name, raw):
            _publish_immutable(staging, target, name, raw)
            if name.endswith(".json"): raise JournalPersistenceError("injected postcommit")
        with patch("blackpod_build_week.decision_journal_store._publish_immutable", side_effect=interrupted):
            with self.assertRaises(JournalPersistenceError): self.store.append(event, evidence)
        saved = self.entries()
        retry = self.store.append(event, evidence)
        self.assertFalse(retry.written)
        self.assertEqual(self.store.verify().event_count, 2)
        self.assert_originals(saved)


if __name__ == "__main__": unittest.main()
