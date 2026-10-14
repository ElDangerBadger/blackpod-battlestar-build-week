"""Frozen source preservation and restrictive overlay diagnostic examples."""
from functools import lru_cache
from pathlib import Path
import socket
import tempfile
import unittest
from unittest.mock import patch

from blackpod_build_week import reconciled_shadow_qualification_example as examples
from blackpod_build_week.contracts.reconciled_shadow_qualification import FALSE_FIELDS
from blackpod_build_week.decision_journal_batch import append_journal_batch
from blackpod_build_week.decision_journal_store import JournalStore
from blackpod_build_week.hashing import canonical_json_bytes, sha256_bytes
from blackpod_build_week.reconciled_shadow_qualification_journal import qualification_material


@lru_cache(maxsize=1)
def fixture_material():
    with patch.object(socket.socket, "connect", side_effect=AssertionError("network forbidden")), patch("subprocess.Popen", side_effect=AssertionError("workers forbidden")):
        return examples.example_material()


@lru_cache(maxsize=1)
def retained_fixture():
    material = fixture_material(); temporary = tempfile.TemporaryDirectory()
    root = Path(temporary.name).resolve() / "journal"
    with patch.object(socket.socket, "connect", side_effect=AssertionError("network forbidden")), patch("subprocess.Popen", side_effect=AssertionError("workers forbidden")):
        append_journal_batch(JournalStore(root), [{"event": event, "evidence": evidence} for event, evidence in
            zip(material["events"], material["event_evidence"])])
    return material, root, temporary


class ReconciledShadowExampleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.material = fixture_material()

    def setUp(self):
        self.enterContext(patch.object(socket.socket, "connect", side_effect=AssertionError("network forbidden")))
        self.enterContext(patch("subprocess.Popen", side_effect=AssertionError("workers forbidden")))

    def test_full_forty_two_and_original_twenty_two_events_and_blobs_stay_identical(self):
        material = self.material; original = material["original"]
        self.assertEqual(len(material["events"]), 43); self.assertEqual(material["source_count"], 42)
        self.assertEqual([event.to_bytes() for event in material["events"][:42]], [event.to_bytes() for event in original["events"]])
        self.assertEqual([event.to_bytes() for event in material["events"][:22]], [event.to_bytes() for event in original["original"]["original"]["events"]])
        for digest, raw in original["blobs"].items(): self.assertEqual(material["blobs"][digest], raw)

    def test_new_event_keeps_original_research_identity_and_exact_intake_reference(self):
        material = self.material; event = material["event"]
        self.assertEqual(event.schema_version, "blackpod.decision_journal_event.v24")
        self.assertEqual(event.decision_id, material["intake_event"].decision_id)
        self.assertEqual(event.payload["links"]["intake_event_id"], material["intake_event"].event_id)
        self.assertEqual(material["request"].intake_result_evidence, material["intake_result_evidence"])
        native = material["original"]["context"]["continuity"]
        self.assertNotEqual(native.decision_id, event.decision_id)

    def test_native_snapshot_masks_catalog_coverage_and_holdout_remain_exact(self):
        material = self.material; result = material["result"]; intake = material["original"]["result"]
        native = material["intake_event"].payload["anchor_snapshot"]["native_qualification_snapshot"]
        self.assertEqual(result["native_qualification_snapshot"], native)
        self.assertEqual(result["boundary_catalog"], intake["candidate_overlay"])
        self.assertEqual(result["coverage_matrix"], intake["coverage_matrix"])
        self.assertEqual(result["final_holdout"], native["continuity"]["final_holdout"])
        reference = result["input_bindings"]["original_native_masks_evidence"]
        self.assertEqual(material["blobs"][reference["sha256"]], canonical_json_bytes(native["continuity"]))
        self.assertEqual(result["input_bindings"]["native_snapshot_sha256"], sha256_bytes(canonical_json_bytes(native)))

    def test_every_native_opportunity_and_clock_reason_survives_without_filtering(self):
        result = self.material["result"]; original = result["native_qualification_snapshot"]["continuity"]["opportunities"]
        self.assertEqual([row["native_opportunity"] for row in result["opportunities"]], original)
        self.assertTrue(any(row["source_clock_reasons"] for row in original))
        for row in result["opportunities"]:
            self.assertTrue(set(row["native_opportunity"]["reason_codes"]) <= set(row["reason_codes"]))

    def test_unknown_symbol_vetoes_own_candidates_and_all_fixed_universe_controls(self):
        result = self.material["result"]
        unknown = next(row for row in result["boundary_catalog"]["boundaries"] if row["mapping"] == "UNKNOWN_EFFECTIVE_DATE")
        self.assertIsNone(unknown["mapped_session_index"]); self.assertIsNone(unknown["mapped_session_id"])
        for row in result["opportunities"]:
            own = row["native_opportunity"]["symbol"] in unknown["affected_symbols"]
            self.assertEqual(row["overlay_candidate_boundary_ids"]["UNKNOWN"], [unknown["boundary_id"]] if own else [])
            self.assertIn(unknown["boundary_id"], row["overlay_benchmark_boundary_ids"])
            self.assertTrue(row["overlay_benchmark_veto"])
            for role in ("FEATURE", "ENTRY", "HOLDING_EXIT"):
                self.assertEqual(row["overlay_candidate_boundary_ids"][role], [])

    def test_diagnostic_candidate_clear_does_not_promote_eligibility_or_missing_risk(self):
        rows = self.material["result"]["opportunities"]
        self.assertTrue(any(not row["overlay_candidate_veto"] for row in rows))
        self.assertTrue(any(row["overlay_candidate_veto"] for row in rows))
        for row in rows:
            self.assertFalse(row["effective_candidate_eligible"]); self.assertFalse(row["effective_benchmark_eligible"])
            self.assertFalse(row["effective_combined_eligible"]); self.assertFalse(row["effective_joint_eligible"])
            self.assertEqual(row["window_status"], "DEFER")
        checks = self.material["result"]["native_qualification_snapshot"]["risk"]["capacity_checks"]
        if not checks: self.assertTrue(all(row["risk_joint_eligible"] is None for row in rows))

    def test_counts_distinguish_vetoes_from_newly_ineligible_native_windows(self):
        result = self.material["result"]; rows = result["opportunities"]; counts = result["counts"]
        self.assertEqual(counts["opportunities"], len(rows))
        self.assertEqual(counts["additional_overlay_veto"], sum(row["additional_overlay_veto"] for row in rows))
        self.assertEqual(counts["newly_ineligible_due_to_overlay"], sum(row["native_combined_eligible"] and row["additional_overlay_veto"] for row in rows))
        self.assertEqual(counts["newly_ineligible"], sum(row["native_combined_eligible"] and not row["effective_combined_eligible"] for row in rows))
        self.assertLessEqual(counts["newly_ineligible_due_to_overlay"], counts["additional_overlay_veto"])
        self.assertEqual(counts["deferred"], len(rows)); self.assertEqual(counts["effective_joint_eligible"], 0)

    def test_all_authority_and_economic_claims_remain_disabled(self):
        result = self.material["result"]
        self.assertEqual(result["status"], "DEFER_RECONCILED_SHADOW_QUALIFICATION")
        for field in FALSE_FIELDS: self.assertFalse(result[field], field)
        self.assertFalse(any(result["authority"].values())); self.assertEqual(result["execution_status"], "NOT_EXECUTED")
        self.assertIsNone(result["realized_trade_pnl"])
        self.assertEqual(qualification_material(self.material["request"], self.material["events"], self.material["blobs"])["event"].to_bytes(), self.material["event"].to_bytes())

    def test_protected_destinations_reject_before_fixture_work(self):
        repository = Path(__file__).resolve().parents[1]
        temporary = tempfile.TemporaryDirectory(); self.addCleanup(temporary.cleanup)
        runtime = Path(temporary.name).resolve(); (runtime / "ledger.lock").write_bytes(b"")
        for output in (repository / "src" / "forbidden-shadow-example", repository / ".git" / "forbidden-shadow-example", runtime / "child"):
            with patch.object(examples, "example_material", side_effect=AssertionError("fixture must not run")):
                with self.assertRaises(ValueError): examples.prepare_example(output)
            self.assertFalse(output.exists())

    def test_interrupted_prefix_recovers_one_event_then_retries_without_rewriting(self):
        temporary = tempfile.TemporaryDirectory(); self.addCleanup(temporary.cleanup)
        root = Path(temporary.name).resolve() / "example"; store = JournalStore(root / "journal")
        append_journal_batch(store, [{"event": event, "evidence": evidence} for event, evidence in
            zip(self.material["events"][:42], self.material["event_evidence"][:42])])
        original = {path.name: path.read_bytes() for path in (store.root / "entries").glob("*.json")}
        with patch.object(examples, "example_material", return_value=self.material):
            first = examples.prepare_example(root); self.assertEqual(first["events_written"], 1)
            manifest = (root / "manifest.json").read_bytes(); second = examples.prepare_example(root)
        self.assertEqual(second["events_written"], 0); self.assertEqual((root / "manifest.json").read_bytes(), manifest)
        self.assertEqual({name: (store.root / "entries" / name).read_bytes() for name in original}, original)
        self.assertEqual(second["journal_verification"]["event_count"], 43)
        self.assertEqual(second["journal_verification"]["orphan_evidence_count"], 0)
        self.assertEqual(second["journal_verification"]["staging_orphan_count"], 0)


if __name__ == "__main__": unittest.main()
