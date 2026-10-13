"""Frozen TRAIN plan contracts and append-only segmented journal boundaries."""
import copy
from datetime import timedelta
from pathlib import Path
import socket
import tempfile
import shutil
import unittest
from unittest.mock import patch

from blackpod_build_week.contracts.train_market_evidence import TrainMarketCapturePlan, TrainMarketSegmentRequest, TrainMarketExportRequest
from blackpod_build_week.contracts.decision_journal import JournalEvent
from blackpod_build_week.contracts.mission_request import parse_rfc3339, format_rfc3339
from blackpod_build_week.hashing import canonical_json_bytes, sha256_bytes
from blackpod_build_week.decision_journal_store import JournalStore, JournalStoreError, JournalPersistenceError
from blackpod_build_week.train_market_evidence import prepare_capture_plan, validate_capture_inputs
from blackpod_build_week.train_market_evidence_journal import capture_plan_material, segment_material, export_material
from blackpod_build_week.trading_shadow_review_example import example_material


def material():
    old = example_material(); blobs = dict(old["blobs"])
    for evidence in old["event_evidence"]: blobs.update({sha256_bytes(raw): raw for raw in evidence.values()})
    plan = prepare_capture_plan(old["events"], blobs, capture_id="root-train-capture", created_at="2025-04-02T10:00:00Z", base_plan_event_id=old["studies"][0]["plan_event"].event_id)
    return old, blobs, plan


def pages(plan, segment, blobs, *, token=None):
    stamp = format_rfc3339(parse_rfc3339(segment["query"]["start"], "start") + timedelta(seconds=1))
    body = canonical_json_bytes({"quotes": {symbol: [{"t": stamp, "bp": 100, "ap": 101, "bs": 10, "as": 20, "bx": "V", "ax": "V", "c": ["R"], "z": "C"}] for symbol in segment["query"]["symbols"].split(",")}, "next_page_token": token})
    path = "root-train-source/" + segment["segment_id"]
    ref = {"path": path + ".raw", "sha256": sha256_bytes(body), "size_bytes": len(body)}
    receipt = canonical_json_bytes({"schema_version": "blackpod.trading_evidence_capture.v1", "method": "GET", "url": "https://data.alpaca.markets/v2/stocks/quotes", "query": segment["query"], "captured_at": "2025-04-02T11:00:00Z", "status": 200, "body_sha256": ref["sha256"], "size_bytes": len(body)})
    other = {"path": path + ".receipt.json", "sha256": sha256_bytes(receipt), "size_bytes": len(receipt)}
    blobs.update({ref["sha256"]: body, other["sha256"]: receipt})
    return [{"body_evidence": ref, "receipt_evidence": other}]


def segment_request(plan_event, segment, source_pages, *, export_id="root-train-export"):
    return TrainMarketSegmentRequest.from_mapping({"schema_version": "blackpod.train_market_segment_export_request.v1", "export_id": export_id,
        "capture_plan_event_id": plan_event.event_id, "segment_id": segment["segment_id"], "pages": source_pages, "failure": None,
        "exported_at": "2025-04-03T00:00:00Z", "auto_trading_enabled": False, "authority": plan_event.payload["plan"]["authority"]})


def aggregate_request(plan_event, ids, **changes):
    return TrainMarketExportRequest.from_mapping({"schema_version": "blackpod.train_market_export_request.v1", "export_id": "root-train-export",
        "capture_plan_event_id": plan_event.event_id, "segment_event_ids": sorted(ids), "exported_at": "2025-04-03T00:00:00Z",
        "continuity_event_id": None, "coverage_review_evidence": None, "capture_snapshot_evidence": None, "capture_checkpoint_evidence": [],
        "auto_trading_enabled": False, "authority": plan_event.payload["plan"]["authority"], **changes})


class TrainEvidenceContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.old, cls.blobs, cls.plan = material()

    def test_strict_immutable_roundtrip(self):
        self.assertEqual(self.plan.to_bytes(), TrainMarketCapturePlan.from_bytes(self.plan.to_bytes()).to_bytes())
        value = self.plan.to_dict(); value["segments"][0]["query"]["feed"] = "sip"
        self.assertEqual(self.plan.segments[0]["query"]["feed"], "iex")

    def test_unknown_fields_versions_modes_and_authority_reject(self):
        for field, value in (("schema_version", "future"), ("domain", "INVESTMENT"), ("mode", "ORDER_EXECUTION"), ("auto_trading_enabled", True), ("credentials", "forbidden")):
            document = self.plan.to_dict(); document[field] = value
            with self.subTest(field=field), self.assertRaises(ValueError): TrainMarketCapturePlan.from_mapping(document)
        for field in self.plan.authority:
            document = self.plan.to_dict(); document["authority"][field] = 1
            with self.subTest(field=field), self.assertRaises(ValueError): TrainMarketCapturePlan.from_mapping(document)

    def test_queries_are_exact_returned_train_opens_with_no_sampling(self):
        sources = validate_capture_inputs(self.plan, self.blobs)
        self.assertEqual(len(self.plan.segments), 12)
        for segment in self.plan.segments:
            session = sources["dataset"].sessions[segment["session_index"]]
            self.assertEqual(segment["query"]["start"], session["open_at"])
            self.assertEqual(segment["query"]["limit"], 10000)
            self.assertEqual(parse_rfc3339(segment["query"]["end"], "end") - parse_rfc3339(session["open_at"], "open"), timedelta(seconds=60))

    def test_train_scope_cannot_be_relabelled_or_undersampled(self):
        for mutate in (lambda d: d["segments"].pop(), lambda d: d["segments"][0].update(session_index=35), lambda d: d["segments"][0]["query"].update(end="2025-04-01T00:00:00Z")):
            document = self.plan.to_dict(); mutate(document)
            with self.assertRaises(ValueError): validate_capture_inputs(document, self.blobs)

    def test_resource_limits_are_frozen_exact_integers(self):
        for field, value in (("max_pages_per_segment", 129), ("max_total_requests", True), ("min_request_interval_ms", 0), ("max_capture_bytes", 1024)):
            document = self.plan.to_dict(); document["limits"][field] = value
            with self.subTest(field=field), self.assertRaises(ValueError): TrainMarketCapturePlan.from_mapping(document)

    def test_safe_paths_duplicate_identities_and_secrets_fields_reject(self):
        document = self.plan.to_dict(); document["dataset_evidence"]["path"] = "../dataset.json"
        with self.assertRaises(ValueError): TrainMarketCapturePlan.from_mapping(document)
        document = self.plan.to_dict(); document["segments"].append(document["segments"][0])
        with self.assertRaises(ValueError): TrainMarketCapturePlan.from_mapping(document)


class TrainEvidenceJournalTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.old, cls.blobs, cls.plan = material(); cls.temp = tempfile.TemporaryDirectory(); cls.addClassCleanup(cls.temp.cleanup)
        cls.base = Path(cls.temp.name).resolve() / "journal"
        store = JournalStore(cls.base)
        for event, evidence in zip(cls.old["events"], cls.old["event_evidence"]): store.append(event, evidence)

    def setUp(self):
        self.enterContext(patch.object(socket.socket, "connect", side_effect=AssertionError("network forbidden")))
        self.enterContext(patch("subprocess.Popen", side_effect=AssertionError("workers forbidden")))
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup); self.root = Path(temp.name).resolve()
        shutil.copytree(self.base, self.root / "journal"); self.store = JournalStore(self.root / "journal")
        self.extra = dict(self.blobs)
        events, blobs = self.store.verified_contents(); self.frozen = capture_plan_material(self.plan, events, blobs)
        self.store.append(self.frozen["event"], self.frozen["evidence"])

    def add_segment(self, index=0, *, token=None, export_id="root-train-export"):
        segment = self.plan.segments[index]; source_pages = pages(self.plan, segment, self.extra, token=token)
        request = segment_request(self.frozen["event"], segment, source_pages, export_id=export_id)
        events, blobs = self.store.verified_contents(); blobs.update(self.extra)
        value = segment_material(request, events, blobs); appended = self.store.append(value["event"], value["evidence"])
        return value, request, appended

    def test_partial_capture_has_explicit_gaps_and_no_qualification_promotion(self):
        segment, _, _ = self.add_segment(); request = aggregate_request(self.frozen["event"], [segment["event"].event_id])
        events, blobs = self.store.verified_contents(); value = export_material(request, events, blobs); self.store.append(value["event"], value["evidence"])
        result = value["result"]
        self.assertFalse(result["capture_complete"]); self.assertFalse(result["coverage_complete"])
        self.assertEqual(result["counts"]["missing_symbol_sessions"], 22)
        self.assertFalse(result["economic_hypothesis_supported"]); self.assertFalse(result["existing_gate_override"])
        self.assertEqual(result["continuity_coverage"]["status"], "UNRESOLVED")
        self.assertEqual(self.store.verify().event_count, 17)

    def test_all_original_source_events_are_byte_identical(self):
        self.add_segment()
        self.assertEqual([e.to_bytes() for e in self.store.events()[:14]], [e.to_bytes() for e in self.old["events"]])

    def test_segment_retry_after_later_export_uses_original_prefix(self):
        first, req, _ = self.add_segment(); self.add_segment(index=1)
        events, blobs = self.store.verified_contents(); value = segment_material(req, events, blobs)
        self.assertFalse(self.store.append(value["event"], value["evidence"]).written)
        self.assertEqual(first["event"].to_bytes(), value["event"].to_bytes())

    def test_no_cherry_pick_of_preceding_segments(self):
        first, _, _ = self.add_segment(); self.add_segment(index=1)
        request = aggregate_request(self.frozen["event"], [first["event"].event_id])
        events, blobs = self.store.verified_contents()
        with self.assertRaisesRegex(ValueError, "every preceding"): export_material(request, events, blobs)

    def test_export_identity_is_immutable(self):
        first, _, _ = self.add_segment(); request = aggregate_request(self.frozen["event"], [first["event"].event_id])
        events, blobs = self.store.verified_contents(); value = export_material(request, events, blobs); self.store.append(value["event"], value["evidence"])
        changed = request.to_dict(); changed["exported_at"] = "2025-04-04T00:00:00Z"
        events, blobs = self.store.verified_contents()
        with self.assertRaisesRegex(ValueError, "immutable"): export_material(changed, events, blobs)

    def test_native_incomplete_page_chain_never_becomes_full_capture(self):
        value, _, _ = self.add_segment(token="more-pages")
        self.assertFalse(value["result"]["capture_complete"])
        self.assertIn("TRAINING_QUOTE_PAGINATION_INCOMPLETE", value["result"]["reason_codes"])

    def test_forged_summary_and_wrong_parent_reject(self):
        value, _, _ = self.add_segment()
        request = aggregate_request(self.frozen["event"], [value["event"].event_id]); events, blobs = self.store.verified_contents()
        m = export_material(request, events, blobs)
        for mutate in (lambda d: d["payload"]["result"].update(capture_complete=True), lambda d: d.update(decision_id="journal-decision-" + "a" * 64)):
            document = m["event"].to_dict(); mutate(document)
            with self.assertRaises((ValueError, JournalStoreError)): self.store.append(JournalEvent.from_mapping(document), m["evidence"])

    def test_authority_and_economic_support_cannot_be_forged(self):
        events, blobs = self.store.verified_contents(); m = export_material(aggregate_request(self.frozen["event"], []), events, blobs)
        for field in ("auto_trading_enabled", "economic_hypothesis_supported", "uncertainty_computed", "existing_gate_override"):
            document = m["event"].to_dict(); document["payload"]["result"][field] = True
            with self.subTest(field=field), self.assertRaises(ValueError): JournalEvent.from_mapping(document)

    def test_metadata_pin_change_rejects(self):
        events, blobs = self.store.verified_contents()
        from blackpod_build_week import train_market_evidence
        with patch.object(train_market_evidence, "implementation_evidence", return_value={"train-evidence/implementation/changed.py": b"changed"}):
            with self.assertRaises(ValueError): segment_material(segment_request(self.frozen["event"], self.plan.segments[0], []), events, blobs)

    def test_interrupted_entry_publication_recovers_without_rewriting_source(self):
        from blackpod_build_week import decision_journal_store as store_module
        segment = self.plan.segments[0]; source_pages = pages(self.plan, segment, self.extra)
        events, blobs = self.store.verified_contents(); blobs.update(self.extra)
        value = segment_material(segment_request(self.frozen["event"], segment, source_pages), events, blobs)
        original = store_module._publish_immutable
        def interrupted(staging, target, name, raw):
            if name.endswith(".json"): raise JournalPersistenceError("interrupted")
            return original(staging, target, name, raw)
        with patch.object(store_module, "_publish_immutable", side_effect=interrupted):
            with self.assertRaises(JournalPersistenceError): self.store.append(value["event"], value["evidence"])
        self.assertEqual(self.store.verify().event_count, 15)
        self.assertTrue(self.store.append(value["event"], value["evidence"]).written)
        self.assertEqual(self.store.verify().orphan_evidence_count, 0)
