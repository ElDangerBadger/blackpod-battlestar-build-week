"""Passive v10 producer records: source replay, mixed history and recovery."""
from __future__ import annotations

import copy
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import shutil
import socket
import tempfile
import unittest
from unittest.mock import patch

from blackpod_build_week.contracts.decision_journal import JournalEvent
from blackpod_build_week.contracts.forecast_producer import ForecastProducerRequest
from blackpod_build_week.decision_journal_store import (
    JournalStore, JournalConflictError, JournalPersistenceError, JournalVerificationError,
)
from blackpod_build_week.forecast_intake import evidence_for_forecast_intake
from blackpod_build_week.forecast_journal import build_forecast_intake_event
from blackpod_build_week.forecast_producer_export import build_forecast_producer_export
from blackpod_build_week.forecast_producer_journal import build_forecast_producer_event
from blackpod_build_week.hashing import canonical_json_bytes, sha256_bytes
from test_forecast_producer_export import fitted_export_material


def replace_reference(value, original, replacement):
    """Update declared reference identity while preserving the changed bytes."""
    if isinstance(value, dict):
        if set(value) == {"path", "sha256", "size_bytes"} and value == original:
            value.update(replacement)
        else:
            for item in value.values():
                replace_reference(item, original, replacement)
    elif isinstance(value, list):
        for item in value:
            replace_reference(item, original, replacement)


class ForecastProducerJournalTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.request, cls.native, cls.source_blobs, cls.clocks = fitted_export_material()
        cls.material = build_forecast_producer_export(cls.request, cls.native, cls.source_blobs, **cls.clocks)
        cls.event = build_forecast_producer_event(cls.material["export"], cls.material["blobs"])

    def setUp(self):
        self.enterContext(patch.object(socket.socket, "connect", side_effect=AssertionError("network forbidden")))
        self.enterContext(patch("subprocess.Popen", side_effect=AssertionError("fit/process forbidden")))
        self.enterContext(patch("blackpod_build_week.modeldock_client.ModelDockClient.generate_text", side_effect=AssertionError("provider forbidden")))
        self.enterContext(patch("blackpod_build_week.paper_account_probe.probe_paper_account", side_effect=AssertionError("broker forbidden")))
        self.enterContext(patch("blackpod_build_week.galactica_trading_adapter.run_guarded_navigator", side_effect=AssertionError("execution forbidden")))
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        self.base = Path(temp.name).resolve(); self.store = JournalStore(self.base / "journal")

    def append(self):
        return self.store.append(self.event, self.material["evidence"])

    def entry_bytes(self):
        return {path.name: path.read_bytes() for path in (self.store.root / "entries").iterdir()}

    def forged_leaf(self, suffix, mutation):
        value = self.event.to_dict()
        reference = next(row for row in value["evidence"] if row["path"].endswith(suffix))
        original = copy.deepcopy(reference)
        packet = json.loads(self.material["evidence"][reference["path"]])
        mutation(packet)
        raw = canonical_json_bytes(packet)
        replacement = {**reference, "sha256": sha256_bytes(raw), "size_bytes": len(raw)}
        replace_reference(value, original, replacement)
        supplied = dict(self.material["evidence"]); supplied[reference["path"]] = raw
        return JournalEvent.from_mapping(value), supplied

    def test_v10_roundtrip_source_closure_all_authority_off(self):
        result = self.append(); self.assertTrue(result.written)
        self.assertEqual(result.sequence, 1)
        events, blobs = self.store.verified_contents()
        self.assertEqual(events[0].schema_version, "blackpod.decision_journal_event.v10")
        self.assertEqual(events[0].to_bytes(), self.event.to_bytes())
        self.assertFalse(any(events[0].payload["request"]["authority"].values()))
        self.assertFalse(any(events[0].payload["export"]["authority"].values()))
        self.assertFalse(events[0].payload["export"]["auto_trading_enabled"])
        for raw in self.material["evidence"].values():
            digest = sha256_bytes(raw)
            self.assertEqual(blobs[digest], raw)
            self.assertEqual((self.store.root / "evidence" / digest).stat().st_mode & 0o777, 0o444)
        self.assertEqual(self.store.verify().orphan_evidence_count, 0)

    def test_journal_event_identity_deterministic_and_object_immutable(self):
        raw = self.event.to_bytes(); value = self.event.to_dict()
        value["payload"]["export"]["runtime_fingerprint"]["python"] = "changed"
        self.assertEqual(self.event.to_bytes(), raw)
        rebuilt = build_forecast_producer_event(self.material["export"], self.material["blobs"])
        self.assertEqual(rebuilt.to_bytes(), raw)

    def test_v10_rejects_unsupported_domain_type_source_and_payload_fields(self):
        for field, value in (("domain", "INVESTMENT"), ("event_type", "ORDER_AUTHORIZED")):
            event = self.event.to_dict(); event[field] = value
            with self.subTest(field=field), self.assertRaises(ValueError): JournalEvent.from_mapping(event)
        event = self.event.to_dict(); event["source"]["kind"] = "MODEL_EXECUTION"
        with self.assertRaises(ValueError): JournalEvent.from_mapping(event)
        event = self.event.to_dict(); event["payload"]["order"] = {"symbol": "SYNTHETIC"}
        with self.assertRaises(ValueError): JournalEvent.from_mapping(event)

    def test_v10_requires_exact_request_identity_and_issue_clock(self):
        for field, value in (("run_id", "different-run"), ("source_sha256", "0" * 64)):
            event = self.event.to_dict(); event["source"][field] = value
            with self.subTest(field=field), self.assertRaises(ValueError): JournalEvent.from_mapping(event)
        event = self.event.to_dict(); event["recorded_at"] = event["recorded_at"].replace("20:10", "20:11")
        with self.assertRaises(ValueError): JournalEvent.from_mapping(event)

    def test_forecast_intake_then_exact_retries_are_noops(self):
        self.append()
        events, blobs = self.store.verified_contents()
        intake = build_forecast_intake_event(self.material["intake"], events, blobs)
        evidence = evidence_for_forecast_intake(self.material["intake"], blobs)
        self.assertTrue(self.store.append(intake, evidence).written)
        original = self.entry_bytes(); summary = self.store.verify().to_dict()
        self.assertFalse(self.append().written)
        self.assertFalse(self.store.append(intake, evidence).written)
        self.assertEqual(self.entry_bytes(), original)
        self.assertEqual(self.store.verify().to_dict(), summary)
        self.assertEqual(self.store.verify().event_count, 2)

    def test_mixed_v1_v9_v10_journal_preserves_older_entries(self):
        from blackpod_build_week.decision_journal_cli import build_policy_event
        from blackpod_build_week.contracts.decision_journal import CapitalPolicyProposal
        from test_decision_journal_contracts import capital_policy
        from test_forecast_brigade_journal_contracts import ForecastBrigadeJournalFixture
        policy = CapitalPolicyProposal.from_mapping(capital_policy())
        older = build_policy_event(policy)
        self.store.append(older, {"capital_policy/proposal.json": policy.to_bytes()})
        fx = ForecastBrigadeJournalFixture()
        self.store.append(fx.forecast_event, evidence_for_forecast_intake(fx.f.intake, fx.blobs))
        original = self.entry_bytes(); self.append()
        self.assertEqual([row.schema_version for row in self.store.events()],
            ["blackpod.decision_journal_event.v1", "blackpod.decision_journal_event.v9", "blackpod.decision_journal_event.v10"])
        for name, raw in original.items():
            self.assertEqual((self.store.root / "entries" / name).read_bytes(), raw)

    def test_restore_from_journal_without_native_checkout_or_model_library(self):
        self.append(); clone = self.base / "restored"; shutil.copytree(self.store.root, clone)
        with patch("blackpod_build_week.shadow_quantitative_producer.capture_quantitative_sources", side_effect=AssertionError("native source read")), patch("blackpod_build_week.shadow_quantitative_producer.build_shadow_quantitative_forecasts", side_effect=AssertionError("refit")):
            restored = JournalStore(clone)
            self.assertEqual(restored.events()[0].to_bytes(), self.event.to_bytes())
            self.assertEqual(restored.verify().to_dict(), self.store.verify().to_dict())

    def test_rehashed_native_coefficients_cannot_change_retained_forecast(self):
        event, supplied = self.forged_leaf("/native-result.json", lambda p: p["symbols"][0]["horizons"][0]["model_artifacts"]["q50"].update(intercept="999"))
        with self.assertRaises(JournalVerificationError): self.store.append(event, supplied)
        self.assertEqual(self.store.verify().event_count, 0)
        self.assertEqual(self.store.verify().orphan_evidence_count, 0)

    def test_rehashed_derived_feature_forecast_target_and_sorted_preview_rejected(self):
        cases = (
            ("/features.json", lambda p: p["observations"][0]["values"].update(RSI="100")),
            ("/forecasts.json", lambda p: p["rows"][0].update(q10="999")),
            ("/target-sessions.json", lambda p: p["sessions"][0].update(closes_at="2026-12-01T20:00:00Z")),
            ("/native-output.json", lambda p: p["native_sorted_quantiles"].update(q10="999")),
        )
        for suffix, mutation in cases:
            with self.subTest(suffix=suffix):
                event, supplied = self.forged_leaf(suffix, mutation)
                with self.assertRaises(JournalVerificationError): self.store.append(event, supplied)
        self.assertEqual(self.store.verify().event_count, 0)

    def test_rehashed_training_availability_cannot_be_backdated(self):
        event, supplied = self.forged_leaf("/native-result.json", lambda p: p["symbols"][0]["horizons"][0]["training_observations"][0].update(target_observed_at=p["symbols"][0]["horizons"][0]["training_observations"][0]["observed_at"]))
        with self.assertRaises(JournalVerificationError): self.store.append(event, supplied)

    def test_rehashed_native_code_fails_reviewed_fingerprint(self):
        value = self.event.to_dict()
        reference = next(row for row in value["evidence"] if row["path"].endswith("phase2_forecast_engine.py"))
        original = copy.deepcopy(reference); raw = self.material["evidence"][reference["path"]] + b"\n# altered source\n"
        replacement = {**reference, "sha256": sha256_bytes(raw), "size_bytes": len(raw)}
        replace_reference(value, original, replacement)
        supplied = dict(self.material["evidence"]); supplied[reference["path"]] = raw
        # The contract itself or retained-source replay must reject the edit.
        with self.assertRaises((ValueError, JournalVerificationError)):
            self.store.append(JournalEvent.from_mapping(value), supplied)

    def test_hash_verification_detects_raw_evidence_corruption(self):
        self.append(); digest = self.event.evidence[0]["sha256"]
        path = self.store.root / "evidence" / digest; path.chmod(0o600); path.write_bytes(b"changed")
        with self.assertRaises(JournalVerificationError): self.store.verify()

    def test_rehashed_envelope_cannot_change_export_runtime_projection(self):
        self.append(); path = self.store.root / "entries/00000001.json"
        envelope = json.loads(path.read_bytes())
        envelope["event"]["payload"]["export"]["runtime_fingerprint"]["python"] = "unsupported-relabel"
        envelope["event_sha256"] = sha256_bytes(JournalEvent.from_mapping(envelope["event"]).to_bytes())
        path.chmod(0o600); path.write_bytes(canonical_json_bytes(envelope))
        with self.assertRaises(JournalVerificationError): self.store.verify()

    def test_same_run_identity_with_changed_requested_horizons_conflicts(self):
        self.append(); value = self.request.to_dict(); value["horizons"] = [1]
        request = ForecastProducerRequest.from_mapping(value)
        material = build_forecast_producer_export(request, self.native, self.source_blobs, **self.clocks)
        changed = build_forecast_producer_event(material["export"], material["blobs"])
        self.assertEqual(changed.event_id, self.event.event_id)
        with self.assertRaises(JournalConflictError): self.store.append(changed, material["evidence"])

    def test_concurrent_producer_append_commits_once(self):
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: self.append(), range(2)))
        self.assertEqual(sum(row.written for row in results), 1)
        self.assertEqual(self.store.verify().event_count, 1)

    def test_interrupted_entry_publish_recovers_retained_evidence_and_retries_without_fit(self):
        import blackpod_build_week.decision_journal_store as module
        original = module._publish_immutable
        def fail_entry(staging, descriptor, name, raw):
            if name.endswith(".json"):
                raise OSError("synthetic entry interruption")
            return original(staging, descriptor, name, raw)
        with patch.object(module, "_publish_immutable", side_effect=fail_entry):
            with self.assertRaises(JournalPersistenceError): self.append()
        self.assertEqual(self.store.verify().event_count, 0)
        self.assertGreater(self.store.verify().orphan_evidence_count, 0)
        self.assertTrue(self.append().written)
        self.assertEqual(self.store.verify().orphan_evidence_count, 0)


if __name__ == "__main__":
    unittest.main()
