"""Offline lifecycle, typed source loading and early safe-output boundaries."""
from contextlib import redirect_stdout
import io
import json
import os
from pathlib import Path
import shutil
import socket
import tempfile
import unittest
from unittest.mock import patch

from blackpod_build_week.contracts.evidence_reconciliation import EvidenceReconciliationRequest
from blackpod_build_week.contracts.effective_date_reconciliation import IndependentActionInventory, EffectiveDateReconciliationRequest, ACTION_TYPES
from blackpod_build_week.contracts.historical_feed_cost_applicability import HistoricalFeedCostContext, HistoricalFeedCostApplicabilityPacket, CATEGORIES
from blackpod_build_week.evidence_reconciliation_cli import main, build_parser, load_review_evidence, _read, _output_guard
from blackpod_build_week.evidence_reconciliation_example import authority, reference
from blackpod_build_week.hashing import canonical_json_bytes, sha256_bytes
from blackpod_build_week.decision_journal_store import JournalStore, JournalStoreError


def reader_material():
    """Typed declarations with opaque leaves; deliberately no semantic source claims."""
    files = {}
    def retain(path, value):
        raw = value if isinstance(value, bytes) else value.to_bytes()
        files[path] = raw; return reference(path, raw)
    data = retain("source/dataset.raw", b"opaque dataset leaf")
    native = retain("source/native-export.raw", b"opaque native export leaf")
    body = retain("source/actions.raw", b'[{"evidence":{"path":"never-follow.raw"}}]')
    support = retain("source/support.raw", b"opaque supporting source")
    manifest = IndependentActionInventory.from_mapping({"schema_version": "blackpod.independent_action_inventory.v1", "inventory_id": "unit-inventory",
        "recorded_at": "2025-04-07T10:00:00Z", "profile": "AUTHORED_EFFECTIVE_DATE_ACTIONS_JSON_V1", "evidence_scope": "SYNTHETIC_FIXTURE_ONLY",
        "publisher": "AUTHORED", "source_url": "https://example.invalid/inventory", "captured_at": "2025-04-07T09:00:00Z", "body_evidence": body,
        "declared_coverage": {"symbols": ["SYNTHAA", "SYNTHBB"], "action_types": list(ACTION_TYPES), "effective_start": "2025-01-01", "effective_end": "2025-01-02", "completeness": "UNKNOWN"},
        "supporting_evidence": [support], "auto_trading_enabled": False, "authority": authority()})
    manifest_ref = retain("declarations/inventory.json", manifest)
    effective = EffectiveDateReconciliationRequest.from_mapping({"schema_version": "blackpod.effective_date_reconciliation_request.v1", "reconciliation_id": "unit-effective",
        "recorded_at": "2025-04-08T10:00:00Z", "data_cutoff_at": "2025-04-08T10:00:00Z", "domain": "TRADING", "mode": "SHADOW_RESEARCH",
        "scope": "RETAINED_INDEPENDENT_EFFECTIVE_DATE_RECONCILIATION_ONLY", "dataset_evidence": data, "native_continuity_export_evidence": native,
        "independent_inventories": [manifest_ref], "auto_trading_enabled": False, "authority": authority()})
    effective_ref = retain("declarations/effective.json", effective)
    context = HistoricalFeedCostContext.from_mapping({"schema_version": "blackpod.historical_feed_cost_context.v1", "context_id": "unit-context",
        "recorded_at": "2025-04-08T10:00:00Z", "capture_plan_event_id": "journal-event-" + "b" * 64,
        "aggregate_export_event_id": "journal-event-" + "c" * 64, "base_plan_event_id": "journal-event-" + "d" * 64,
        "dataset_evidence": data, "bars_receipt_evidence": retain("source/bars-receipt.raw", b"opaque bars receipt"),
        "capture_plan_evidence": retain("source/capture-plan.raw", b"opaque capture plan"),
        "quote_receipt_evidence": [retain("source/quote-receipt.raw", b"opaque quote receipt")],
        "provider": "ALPACA", "endpoint": "https://data.alpaca.markets/v2/stocks/quotes", "feed": "iex", "universe": ["SYNTHAA", "SYNTHBB"], "currency": "USD",
        "market_event_interval": {"start_at": "2025-01-01T14:30:00Z", "end_at": "2025-01-02T14:31:00Z"},
        "delivery_interval": {"start_at": "2025-04-03T11:00:00Z", "end_at": "2025-04-03T11:00:00Z"},
        "collection_mode": "MARKET_DATA_GET_ONLY", "declared_evaluation_mode": "SHADOW_RESEARCH", "account_evidence": None,
        "auto_trading_enabled": False, "authority": authority()})
    context_ref = retain("declarations/context.json", context)
    note = retain("source/note.raw", b'[{"source_url":"https://example.invalid/never-fetch","evidence":{"path":"never-read.raw"}}]')
    packet = HistoricalFeedCostApplicabilityPacket.from_mapping({"schema_version": "blackpod.historical_feed_cost_applicability_packet.v1", "packet_id": "unit-packet",
        "recorded_at": "2025-04-08T10:00:00Z", "data_cutoff_at": "2025-04-08T10:00:00Z", "context_evidence": context_ref,
        "reviewer_id": "authored-unverified", "review_notes": "No source applicability established.",
        "source_documents": [{"document_id": "unit-note", "evidence": note, "source_url": "https://example.invalid/note", "publisher": "AUTHORED", "document_version": None,
            "published_at": None, "observed_at": "2025-04-07T10:00:00Z", "document_kind": "AUTHORED_REVIEW_NOTE"}],
        "categories": [{"category": category, "assertions": []} for category in CATEGORIES], "auto_trading_enabled": False, "authority": authority()})
    packet_ref = retain("declarations/packet.json", packet)
    request = EvidenceReconciliationRequest.from_mapping({"schema_version": "blackpod.independent_evidence_reconciliation_request.v1", "review_id": "unit-review",
        "recorded_at": "2025-04-08T10:00:00Z", "data_cutoff_at": "2025-04-08T10:00:00Z", "domain": "TRADING", "mode": "SHADOW_RESEARCH",
        "scope": "INDEPENDENT_EVIDENCE_RECONCILIATION_ONLY", "anchor_review_event_id": "journal-event-" + "a" * 64,
        "effective_date_request_evidence": effective_ref, "applicability_packet_evidence": packet_ref, "declared_evaluation_mode": "SHADOW_RESEARCH",
        "account_profile_evidence": None, "supersedes_event_id": None, "auto_trading_enabled": False, "authority": authority()})
    return request, files


class OfflineAndReaderTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(patch.object(socket.socket, "connect", side_effect=AssertionError("network forbidden")))
        self.enterContext(patch("subprocess.Popen", side_effect=AssertionError("workers forbidden")))
        temporary = tempfile.TemporaryDirectory(); self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve(); self.request, self.files = reader_material()

    def call(self, args):
        output = io.StringIO()
        with redirect_stdout(output): code = main(args)
        return code, json.loads(output.getvalue())

    def write_sources(self):
        for name, raw in self.files.items():
            path = self.root / name; path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(raw)

    def test_six_offline_commands_have_no_execution_or_provider_options(self):
        command = next(action for action in build_parser()._actions if isinstance(getattr(action, "choices", None), dict))
        self.assertEqual(set(command.choices), {"prepare", "context", "assess", "record", "show", "verify"})
        for parser in command.choices.values():
            options = {option for item in parser._actions for option in item.option_strings}
            self.assertFalse(options & {"--allow-market-data-get", "--broker", "--credential-source", "--activate", "--auto-trading"})

    def test_prepare_never_reads_or_claims_verified_history(self):
        inputs = self.root / "input" / "inputs.json"; inputs.parent.mkdir()
        inputs.write_bytes(canonical_json_bytes({key: getattr(self.request, key) for key in ("effective_date_request_evidence", "applicability_packet_evidence", "account_profile_evidence")}))
        output = self.root / "prepared" / "request.json"
        with patch.object(JournalStore, "verified_contents", side_effect=AssertionError("prepare must not scan")):
            code, result = self.call(["prepare", "--review-id", "prepared", "--recorded-at", self.request.recorded_at, "--data-cutoff-at", self.request.data_cutoff_at,
                "--anchor-review-event-id", self.request.anchor_review_event_id, "--declared-evaluation-mode", "LIVE_BROKERAGE", "--inputs", str(inputs), "--output", str(output)])
        self.assertEqual(code, 0, result); self.assertFalse(result["source_history_verified"]); self.assertFalse(result["assessment_performed"])
        prepared = EvidenceReconciliationRequest.from_bytes(output.read_bytes())
        self.assertEqual(prepared.declared_evaluation_mode, "LIVE_BROKERAGE"); self.assertFalse(prepared.auto_trading_enabled)

    def test_missing_journal_verify_creates_nothing(self):
        path = self.root / "missing"
        self.assertEqual(self.call(["verify", "--journal-root", str(path)])[0], 2); self.assertFalse(path.exists())

    def test_typed_source_closure_preserves_opaque_arrays_and_never_follows_body_refs(self):
        self.write_sources(); blobs = load_review_evidence(self.request, {}, self.root)
        self.assertEqual(set(blobs), {sha256_bytes(raw) for raw in self.files.values()})
        self.assertFalse((self.root / "never-read.raw").exists()); self.assertFalse((self.root / "never-follow.raw").exists())

    def test_closed_retained_sources_require_no_external_files(self):
        blobs = {sha256_bytes(raw): raw for raw in self.files.values()}
        with patch("blackpod_build_week.evidence_reconciliation_cli._read", side_effect=AssertionError("external reads forbidden")):
            self.assertEqual(load_review_evidence(self.request, blobs, None), blobs)

    def test_missing_changed_and_corrupt_retained_leaf_reject(self):
        with self.assertRaisesRegex(ValueError, "explicit evidence root"): load_review_evidence(self.request, {}, None)
        self.write_sources(); (self.root / "source/note.raw").write_bytes(b"changed")
        with self.assertRaisesRegex(ValueError, "hash or size"): load_review_evidence(self.request, {}, self.root)
        blobs = {sha256_bytes(raw): raw for raw in self.files.values()}; blobs[sha256_bytes(self.files["source/note.raw"])] = b"corrupt"
        with self.assertRaisesRegex(ValueError, "hash or size"): load_review_evidence(self.request, blobs, None)

    def test_combined_reference_and_byte_bounds_reject(self):
        self.write_sources()
        with patch("blackpod_build_week.evidence_reconciliation_cli.MAX_REFERENCES", 2):
            with self.assertRaisesRegex(ValueError, "bound"): load_review_evidence(self.request, {}, self.root)
        with patch("blackpod_build_week.evidence_reconciliation_cli.MAX_BYTES", sum(map(len, self.files.values())) - 1):
            with self.assertRaisesRegex(ValueError, "bound"): load_review_evidence(self.request, {}, self.root)

    def test_unsafe_input_links_and_parent_traversal_reject(self):
        target = self.root / "target.raw"; target.write_bytes(b"source")
        link = self.root / "link.raw"; link.symlink_to(target)
        with self.assertRaises((OSError, ValueError)): _read(link)
        link.unlink(); os.link(target, link)
        with self.assertRaises((OSError, ValueError)): _read(link)
        with self.assertRaisesRegex(ValueError, "traverse"): _read(self.root / "x" / ".." / "target.raw")

    def test_output_protection_precedes_journal_scan(self):
        sources = Path(__file__).resolve().parents[1] / "src" / "forbidden-reconciliation.json"
        runtime = self.root / "runtime"; runtime.mkdir(); (runtime / "ledger.lock").write_bytes(b"")
        for output in (sources, runtime / "child" / "report.json", self.root / "journal" / "report.json"):
            with patch.object(JournalStore, "verified_contents", side_effect=AssertionError("output guard must precede scan")):
                code, result = self.call(["assess", "--journal-root", str(self.root / "journal"), "--request", str(self.root / "inputs" / "request.json"), "--output", str(output)])
            self.assertEqual(code, 2, result); self.assertFalse(output.exists())


class ReconciliationLifecycleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from test_evidence_reconciliation_example import retained_fixture
        cls.material, cls.base, cls.retained_temp = retained_fixture()

    def setUp(self):
        self.enterContext(patch.object(socket.socket, "connect", side_effect=AssertionError("network forbidden")))
        self.enterContext(patch("subprocess.Popen", side_effect=AssertionError("workers forbidden")))
        temporary = tempfile.TemporaryDirectory(); self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve(); self.journal = self.root / "journal"; shutil.copytree(self.base, self.journal)
        self.case = self.material["cases"][0]
        self.request = EvidenceReconciliationRequest.from_mapping({**self.case["request"].to_dict(), "review_id": "cli-new-independent-review"})
        self.path = self.root / "input" / "request.json"; self.path.parent.mkdir(); self.path.write_bytes(self.request.to_bytes())

    def call(self, args):
        output = io.StringIO()
        with redirect_stdout(output): code = main(args)
        return code, json.loads(output.getvalue())

    def test_context_export_and_assessment_are_immutable_without_append(self):
        original = {path.name: path.read_bytes() for path in (self.journal / "entries").glob("*.json")}
        context_path = self.root / "context" / "context.json"
        code, result = self.call(["context", "--journal-root", str(self.journal), "--anchor-review-event-id", self.request.anchor_review_event_id,
            "--recorded-at", self.request.data_cutoff_at, "--declared-evaluation-mode", self.request.declared_evaluation_mode, "--output", str(context_path)])
        self.assertEqual(code, 0, result); self.assertFalse(result["assessment_performed"])
        self.assertEqual(context_path.read_bytes(), self.case["context"].to_bytes())
        report = self.root / "reports" / "result.json"
        args = ["assess", "--journal-root", str(self.journal), "--request", str(self.path), "--output", str(report)]
        code, result = self.call(args); self.assertEqual(code, 0, result)
        first = report.read_bytes(); self.assertEqual(self.call(args)[0], 0); self.assertEqual(report.read_bytes(), first)
        self.assertEqual({path.name: path.read_bytes() for path in (self.journal / "entries").glob("*.json")}, original)

    def test_record_retry_show_and_verify_preserve_original_entry_bytes(self):
        original = {path.name: path.read_bytes() for path in (self.journal / "entries").glob("*.json")}
        args = ["record", "--journal-root", str(self.journal), "--request", str(self.path)]
        code, result = self.call(args); self.assertEqual(code, 0, result); self.assertTrue(result["written"])
        code, retry = self.call(args); self.assertEqual(code, 0, retry); self.assertFalse(retry["written"])
        code, shown = self.call(["show", "--journal-root", str(self.journal), "--event-id", result["event_id"]])
        self.assertEqual(code, 0, shown); self.assertIsNone(shown["payload"]["result"]["realized_trade_pnl"])
        code, verified = self.call(["verify", "--journal-root", str(self.journal)])
        self.assertEqual(code, 0, verified); self.assertEqual(verified["event_count"], len(original) + 1)
        self.assertEqual({name: (self.journal / "entries" / name).read_bytes() for name in original}, original)

    def test_show_rejects_anchor_instead_of_new_review(self):
        code, result = self.call(["show", "--journal-root", str(self.journal), "--event-id", self.request.anchor_review_event_id])
        self.assertEqual(code, 2, result)


if __name__ == "__main__": unittest.main()
