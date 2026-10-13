"""Authored original-prefix examples and ordinary immutable publication."""
from decimal import Decimal
from functools import lru_cache
import json
from pathlib import Path
import socket
import tempfile
import unittest
from unittest.mock import patch

from blackpod_build_week import native_evidence_closure_example as examples
from blackpod_build_week.hashing import canonical_json_bytes, sha256_bytes
from blackpod_build_week.decision_journal_store import JournalStore
from blackpod_build_week.decision_journal_batch import append_journal_batch
from blackpod_build_week.native_evidence_closure_journal import review_material


@lru_cache(maxsize=1)
def fixture_material():
    with patch.object(socket.socket, "connect", side_effect=AssertionError("network forbidden")), patch("subprocess.Popen", side_effect=AssertionError("workers forbidden")):
        return examples.example_material()


class NativeClosureExampleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.material = fixture_material()
        cls.cases = {case["case_id"]: case for case in cls.material["cases"]}

    def setUp(self):
        self.enterContext(patch.object(socket.socket, "connect", side_effect=AssertionError("network forbidden")))
        self.enterContext(patch("subprocess.Popen", side_effect=AssertionError("workers forbidden")))

    def test_all_original_84_events_and_raw_evidence_stay_byte_identical(self):
        old = self.material["original"]
        self.assertEqual(len(old["events"]), 84)
        self.assertEqual([event.to_bytes() for event in self.material["events"][:84]], [event.to_bytes() for event in old["events"]])
        for digest, raw in old["blobs"].items(): self.assertEqual(self.material["blobs"][digest], raw)
        self.assertEqual(len(self.material["events"]), 103)

    def test_four_cases_link_original_decisions_instead_of_new_parallel_history(self):
        self.assertEqual(set(self.cases), {"deceptive-checklist", "native-candidate-comparison", "new-wide-observation", "partial-capture"})
        for case in self.cases.values():
            anchor = next(event for event in self.material["events"] if event.event_id == case["request"].anchor_qualification_event_id)
            self.assertEqual(case["review_event"].decision_id, anchor.decision_id)
            self.assertEqual(case["review_event"].schema_version, "blackpod.decision_journal_event.v21")

    def test_complete_unauthenticated_checklist_cannot_clear_native_deferrals(self):
        result = self.cases["deceptive-checklist"]["result"]
        self.assertTrue(all(category["status"] == "SOURCE_REVIEW_RECORDED" for category in result["supplemental_review"]["categories"]))
        native = result["anchor_qualification"]["result"]
        self.assertEqual(native["status"], "DEFER_EVIDENCE_QUALIFICATION")
        self.assertEqual(result["missing_prerequisites"], native["reason_codes"])
        self.assertFalse(result["supplemental_review_applied_to_native_gates"])
        self.assertFalse(result["reviewer_identity_authenticated"])

    def test_actual_later_native_candidate_resolves_only_native_reason_set(self):
        result = self.cases["native-candidate-comparison"]["result"]
        self.assertIn("TRAINING_COST_AND_CAPACITY_ASSUMPTIONS_MISSING", result["reason_comparison"]["resolved_reason_codes"])
        self.assertEqual(result["candidate_qualification"]["result"]["status"], "READY_FOR_QUALIFIED_STUDY_DESIGN")
        self.assertEqual(result["missing_prerequisites"], [])
        self.assertEqual(result["reason_comparison"]["new_reason_codes"], [])
        self.assertFalse(result["economic_hypothesis_supported"])
        self.assertFalse(result["uncertainty_computed"])

    def test_new_wide_observation_is_retained_unclipped_and_native_candidate_defers(self):
        result = self.cases["new-wide-observation"]["result"]
        self.assertEqual(result["anchor_qualification"]["result"]["status"], "READY_FOR_QUALIFIED_STUDY_DESIGN")
        self.assertEqual(result["candidate_qualification"]["result"]["status"], "DEFER_EVIDENCE_QUALIFICATION")
        self.assertEqual(result["reason_comparison"]["new_reason_codes"], ["TRAINING_COST_STRESS_EXCEEDS_EXISTING_MODEL_BOUND"])
        rows = result["candidate_diagnostics"]["symbols"]
        widest = max(rows, key=lambda row: Decimal(row["max_spread_bps"]))
        self.assertGreater(Decimal(widest["max_spread_bps"]), Decimal("1000"))
        self.assertEqual(widest["spread_only_exceedance_counts"], {"1": 1, "2": 1, "4": 1})

    def test_extreme_witness_reproduces_exact_retained_native_row(self):
        rows = self.cases["new-wide-observation"]["result"]["candidate_diagnostics"]["symbols"]
        witness = max(rows, key=lambda row: Decimal(row["max_spread_bps"]))["max_spread_witness"]
        native = json.loads(self.material["blobs"][witness["body_evidence"]["sha256"]], parse_float=str, parse_int=str)
        _, _, symbol, index = witness["row_pointer"].split("/")
        original = native["quotes"][symbol][int(index)]
        self.assertEqual(witness["native_row"], original)
        self.assertEqual(witness["native_row_sha256"], sha256_bytes(canonical_json_bytes(original)))
        self.assertTrue(all(isinstance(original[key], str) for key in ("bp", "ap", "bs", "as")))

    def test_partial_capture_counts_missing_windows_without_inventing_quote_rows(self):
        result = self.cases["partial-capture"]["result"]
        diagnostics = result["anchor_diagnostics"]
        self.assertEqual(diagnostics["coverage"]["planned_segments"], 12)
        self.assertEqual(diagnostics["coverage"]["provided_segments"], 2)
        self.assertEqual(diagnostics["coverage"]["missing_segments"], 10)
        self.assertEqual(diagnostics["totals"]["raw_quote_count"], 4)
        self.assertIn("TRAIN_SEGMENT_CAPTURE_INCOMPLETE", result["missing_prerequisites"])

    def test_review_evidence_keeps_compact_links_instead_of_duplicating_raw_corpus(self):
        body_hashes = {sha256_bytes(raw) for path, raw in self.material["authored_evidence"].items() if path.endswith(".body.raw")}
        for event in self.material["events"][-4:]:
            self.assertFalse(body_hashes & {ref["sha256"] for ref in event.evidence})
            self.assertIn("native-closure/result.v1.json", {ref["path"] for ref in event.evidence})

    def test_no_case_grants_authority_returns_or_source_authentication(self):
        for case in self.cases.values():
            result = case["result"]
            self.assertEqual(result["status"], "DESCRIPTIVE_REVIEW_ONLY")
            self.assertEqual(result["execution_status"], "NOT_EXECUTED")
            self.assertIsNone(result["realized_trade_pnl"])
            for field in ("native_gate_override", "source_applicability_verified", "source_authentication_verified",
                          "historical_point_in_time_verified", "uncertainty_computed", "economic_hypothesis_supported", "auto_trading_enabled"):
                self.assertFalse(result[field])
            self.assertTrue(all(value is False for value in result["authority"].values()))

    def test_exact_reprojection_after_later_reviews_preserves_original_event(self):
        case = self.cases["deceptive-checklist"]
        replay = review_material(case["request"], self.material["events"], self.material["blobs"])
        self.assertEqual(replay["event"].to_bytes(), case["review_event"].to_bytes())

    def test_source_tree_destination_rejected_before_any_fixture_work(self):
        output = Path(__file__).resolve().parents[1] / "src" / "forbidden-native-example"
        temporary = tempfile.TemporaryDirectory(); self.addCleanup(temporary.cleanup)
        runtime = Path(temporary.name).resolve()
        (runtime / "ledger.lock").write_bytes(b"")
        with patch.object(examples, "example_material", side_effect=AssertionError("fixture must not run")):
            with self.assertRaises(ValueError): examples.prepare_example(output)
            with self.assertRaises(ValueError): examples.prepare_example(runtime / "nested-output")
        self.assertFalse(output.exists())
        self.assertFalse((runtime / "nested-output").exists())

    def test_interrupted_exact_source_prefix_publishes_suffix_then_retries_without_writes(self):
        temporary = tempfile.TemporaryDirectory(); self.addCleanup(temporary.cleanup)
        root = Path(temporary.name).resolve() / "example"
        store = JournalStore(root / "journal")
        # Interruption after source publication, before the four review commits.
        append_journal_batch(store, [{"event": event, "evidence": evidence} for event, evidence in
            zip(self.material["events"][:-4], self.material["event_evidence"][:-4])])
        original = {path.name: path.read_bytes() for path in (store.root / "entries").glob("*.json")}
        with patch.object(examples, "example_material", return_value=self.material):
            first = examples.prepare_example(root)
            self.assertEqual(first["events_written"], 4)
            manifest = (root / "manifest.json").read_bytes()
            second = examples.prepare_example(root)
        self.assertEqual(second["events_written"], 0)
        self.assertEqual((root / "manifest.json").read_bytes(), manifest)
        self.assertEqual({name: (store.root / "entries" / name).read_bytes() for name in original}, original)
        self.assertEqual(second["journal_verification"]["event_count"], 103)
        self.assertEqual(second["journal_verification"]["orphan_evidence_count"], 0)
        self.assertEqual(second["journal_verification"]["staging_orphan_count"], 0)
        self.assertEqual(second["provider_calls"], 0)
        self.assertFalse(second["auto_trading_enabled"])


if __name__ == "__main__": unittest.main()
