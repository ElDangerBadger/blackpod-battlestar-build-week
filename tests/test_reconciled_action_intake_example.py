"""Small immutable-prefix examples with no operational mask authority."""
from functools import lru_cache
from pathlib import Path
import socket
import tempfile
import unittest
from unittest.mock import patch

from blackpod_build_week import reconciled_action_intake_example as examples
from blackpod_build_week.contracts.reconciled_action_intake import FALSE_FIELDS
from blackpod_build_week.decision_journal_batch import append_journal_batch
from blackpod_build_week.decision_journal_store import JournalStore
from blackpod_build_week.hashing import canonical_json_bytes, sha256_bytes
from blackpod_build_week.reconciled_action_journal import policy_material, intake_material


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


class ReconciledActionExampleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.material = fixture_material()

    def setUp(self):
        self.enterContext(patch.object(socket.socket, "connect", side_effect=AssertionError("network forbidden")))
        self.enterContext(patch("subprocess.Popen", side_effect=AssertionError("workers forbidden")))

    def test_original_twenty_two_and_full_forty_source_events_stay_identical(self):
        material = self.material; original = material["original"]
        self.assertEqual(len(material["events"]), 42); self.assertEqual(material["source_count"], 40)
        self.assertEqual([event.to_bytes() for event in material["events"][:40]], [event.to_bytes() for event in original["events"][:40]])
        self.assertEqual([event.to_bytes() for event in material["events"][:22]], [event.to_bytes() for event in original["original"]["events"]])
        for digest, raw in original["blobs"].items(): self.assertEqual(material["blobs"][digest], raw)

    def test_distinct_native_intake_identity_is_bound_without_relabeling(self):
        material = self.material; context = material["context"]
        self.assertNotEqual(context["continuity"].decision_id, material["anchor_event"].decision_id)
        for event in (material["policy_event"], material["intake_event"]):
            self.assertEqual(event.decision_id, material["anchor_event"].decision_id)
            self.assertEqual(event.schema_version, "blackpod.decision_journal_event.v23")
        self.assertEqual(material["policy"].native_continuity_export_evidence, context["native_continuity_export_evidence"])

    def test_freeze_preserves_all_original_inventories_and_exact_native_masks(self):
        material = self.material; policy = material["policy"]
        self.assertEqual(policy.status, "FROZEN_FOR_SHADOW_INTAKE")
        for reference in material["context"]["independent_inventories"]: self.assertIn(reference, policy.independent_inventories)
        original = material["anchor_event"].payload["result"]["native_qualification_snapshot"]["continuity"]
        self.assertEqual(material["result"]["original_native_masks"]["assessment"], original)
        self.assertEqual(material["blobs"][policy.original_native_masks_evidence["sha256"]], canonical_json_bytes(original))

    def test_issuer_observations_do_not_fabricate_provider_events(self):
        result = self.material["result"]
        self.assertEqual(result["original_native_events"], [])
        self.assertEqual(result["original_native_export"]["derived_event_count"], 0)
        self.assertEqual(len(result["issuer_observations"]), 8)
        self.assertEqual(result["matches"], [])
        self.assertTrue(all(row["origin"] == "ISSUER_DECLARATION" for row in result["candidate_overlay"]["boundaries"]))

    def test_duplicate_conflicting_and_status_rows_remain_separate(self):
        result = self.material["result"]
        self.assertEqual(len(result["ambiguous"]), 1); self.assertEqual(len(result["duplicate_groups"]), 1)
        observations = result["issuer_observations"]
        self.assertEqual(len({row["independent_action_id"] for row in observations}), 8)
        statuses = {row["source_status"]: row for row in result["candidate_overlay"]["boundaries"]}
        self.assertTrue(statuses["SCHEDULED"]["boundary_flag"])
        self.assertFalse(statuses["CANCELLED"]["boundary_flag"])
        self.assertTrue(all(not row["confirmed_payment"] for row in result["candidate_overlay"]["boundaries"]))

    def test_unknown_and_outside_span_dates_never_get_invented_sessions(self):
        overlay = self.material["result"]["candidate_overlay"]
        self.assertEqual(len(overlay["unknown_date_scope"]), 1)
        rows = {row["mapping"]: row for row in overlay["boundaries"]}
        for key in ("UNKNOWN_EFFECTIVE_DATE", "BEFORE_DATASET", "AFTER_DATASET"):
            self.assertIsNone(rows[key]["mapped_session_id"]); self.assertIsNone(rows[key]["mapped_session_index"])
        self.assertEqual(rows["EXACT_RETURNED_DATE"]["mapping"], "EXACT_RETURNED_DATE")

    def test_all_type_coverage_and_existing_consumers_remain_ineligible(self):
        result = self.material["result"]
        self.assertEqual(result["status"], "SHADOW_CANDIDATE_NOT_ELIGIBLE")
        self.assertEqual(len(result["coverage_matrix"]), 26)
        for field in FALSE_FIELDS: self.assertFalse(result[field], field)
        self.assertFalse(any(result["authority"].values()))
        self.assertEqual(result["execution_status"], "NOT_EXECUTED"); self.assertIsNone(result["realized_trade_pnl"])
        self.assertFalse(self.material["policy"].auto_trading_enabled)

    def test_exact_reprojection_after_later_intake_keeps_policy_and_result_bytes(self):
        material = self.material
        self.assertEqual(policy_material(material["policy"], material["events"], material["blobs"])["event"].to_bytes(), material["policy_event"].to_bytes())
        self.assertEqual(intake_material(material["request"], material["events"], material["blobs"])["event"].to_bytes(), material["intake_event"].to_bytes())

    def test_protected_destinations_reject_before_fixture_work(self):
        repository = Path(__file__).resolve().parents[1]
        temporary = tempfile.TemporaryDirectory(); self.addCleanup(temporary.cleanup)
        runtime = Path(temporary.name).resolve(); (runtime / "ledger.lock").write_bytes(b"")
        for output in (repository / "src" / "forbidden-reconciled-example", repository / ".git" / "forbidden-reconciled-example", runtime / "child"):
            with patch.object(examples, "example_material", side_effect=AssertionError("fixture must not run")):
                with self.assertRaises(ValueError): examples.prepare_example(output)
            self.assertFalse(output.exists())

    def test_interrupted_source_prefix_recovers_two_events_and_retries_with_zero_writes(self):
        temporary = tempfile.TemporaryDirectory(); self.addCleanup(temporary.cleanup)
        root = Path(temporary.name).resolve() / "example"; store = JournalStore(root / "journal")
        append_journal_batch(store, [{"event": event, "evidence": evidence} for event, evidence in
            zip(self.material["events"][:40], self.material["event_evidence"][:40])])
        original = {path.name: path.read_bytes() for path in (store.root / "entries").glob("*.json")}
        with patch.object(examples, "example_material", return_value=self.material):
            first = examples.prepare_example(root); self.assertEqual(first["events_written"], 2)
            manifest = (root / "manifest.json").read_bytes(); second = examples.prepare_example(root)
        self.assertEqual(second["events_written"], 0)
        self.assertEqual((root / "manifest.json").read_bytes(), manifest)
        self.assertEqual({name: (store.root / "entries" / name).read_bytes() for name in original}, original)
        self.assertEqual(second["journal_verification"]["event_count"], 42)
        self.assertEqual(second["journal_verification"]["orphan_evidence_count"], 0)
        self.assertEqual(second["journal_verification"]["staging_orphan_count"], 0)


if __name__ == "__main__": unittest.main()
