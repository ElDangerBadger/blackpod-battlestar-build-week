"""Authored source discrepancies without native gate or policy changes."""
from functools import lru_cache
import json
from pathlib import Path
import socket
import tempfile
import unittest
from unittest.mock import patch

from blackpod_build_week import evidence_reconciliation_example as examples
from blackpod_build_week.decision_journal_store import JournalStore
from blackpod_build_week.decision_journal_batch import append_journal_batch
from blackpod_build_week.evidence_reconciliation_journal import review_material
from blackpod_build_week.hashing import canonical_json_bytes, sha256_bytes


@lru_cache(maxsize=1)
def fixture_material():
    with patch.object(socket.socket, "connect", side_effect=AssertionError("network forbidden")), patch("subprocess.Popen", side_effect=AssertionError("workers forbidden")):
        return examples.example_material()


@lru_cache(maxsize=1)
def retained_fixture():
    """One published authored history shared by the offline CLI tests."""
    material = fixture_material()
    temporary = tempfile.TemporaryDirectory()
    root = Path(temporary.name).resolve() / "journal"
    with patch.object(socket.socket, "connect", side_effect=AssertionError("network forbidden")), patch("subprocess.Popen", side_effect=AssertionError("workers forbidden")):
        append_journal_batch(JournalStore(root), [{"event": event, "evidence": evidence} for event, evidence in
            zip(material["events"], material["event_evidence"])])
    return material, root, temporary


class EvidenceReconciliationExampleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.material = fixture_material()
        cls.cases = {case["case_id"]: case for case in cls.material["cases"]}

    def setUp(self):
        self.enterContext(patch.object(socket.socket, "connect", side_effect=AssertionError("network forbidden")))
        self.enterContext(patch("subprocess.Popen", side_effect=AssertionError("workers forbidden")))

    def test_original_twenty_two_events_and_all_evidence_remain_identical(self):
        original = self.material["original"]
        self.assertEqual(len(original["events"]), 22)
        self.assertEqual([event.to_bytes() for event in self.material["events"][:22]], [event.to_bytes() for event in original["events"]])
        for digest, raw in original["blobs"].items(): self.assertEqual(self.material["blobs"][digest], raw)
        self.assertEqual(len(self.material["events"]), 42)
        self.assertEqual(self.material["events"][38].event_type, "TRADING_NATIVE_EVIDENCE_CLOSURE_REVIEW_RECORDED")

    def test_three_reviews_share_original_decision_and_exact_native_anchor(self):
        self.assertEqual(set(self.cases), {"empty-observations", "partial-missing-mismatched-feed", "ambiguous-and-account-conflict"})
        anchor = self.material["anchor_review_event"]
        for case in self.cases.values():
            self.assertEqual(case["request"].anchor_review_event_id, anchor.event_id)
            self.assertEqual(case["review_event"].decision_id, anchor.decision_id)
            self.assertEqual(case["review_event"].schema_version, "blackpod.decision_journal_event.v22")

    def test_empty_observations_do_not_establish_complete_action_coverage(self):
        result = self.cases["empty-observations"]["result"]["effective_date_reconciliation"]
        for key in ("matches", "native_only", "independent_only", "ambiguous"):
            self.assertEqual(result[key], [])
        self.assertEqual(len(result["coverage_matrix"]), 26)
        self.assertFalse(result["coverage_supported"])
        self.assertEqual(result["coverage_proposal"]["status"], "UNRESOLVED")
        self.assertTrue(all(row["uncovered_intervals"] for row in result["coverage_matrix"]))

    def test_missing_independent_action_retains_partial_scope_and_unchanged_native_rows(self):
        result = self.cases["partial-missing-mismatched-feed"]["result"]["effective_date_reconciliation"]
        self.assertEqual(len(result["independent_only"]), 1)
        self.assertEqual(result["native_actions"], [])
        self.assertTrue(any(row["declared_scope_gaps"] for row in result["coverage_matrix"]))
        self.assertFalse(result["native_gate_override"])

    def test_duplicate_actions_remain_ambiguous_instead_of_arbitrary_matching(self):
        result = self.cases["ambiguous-and-account-conflict"]["result"]["effective_date_reconciliation"]
        self.assertEqual(len(result["independent_actions"]), 2)
        self.assertEqual(len(result["ambiguous"]), 1)
        self.assertEqual(len(result["duplicate_groups"]), 1)
        self.assertEqual(result["matches"], [])

    def test_sip_scope_and_delivery_only_claim_cannot_establish_historical_iex_units(self):
        result = self.cases["partial-missing-mismatched-feed"]["result"]["historical_feed_cost_applicability"]
        categories = {row["category"]: row for row in result["category_results"]}
        self.assertEqual(categories["FEED_IDENTITY"]["status"], "SCOPE_MISMATCH")
        self.assertIn("feed", categories["FEED_IDENTITY"]["assertion_results"][0]["mismatched_fields"])
        self.assertIn("CROSS_TIME_APPLICABILITY_UNRESOLVED", categories["QUOTE_SIZE_UNITS"]["reason_codes"])
        self.assertIsNone(result["derived_unit_multiplier"])

    def test_paper_target_retains_missing_account_and_conflicting_numeric_claims(self):
        case = self.cases["ambiguous-and-account-conflict"]
        self.assertEqual(case["context"].declared_evaluation_mode, "PAPER_SIMULATION")
        self.assertIsNone(case["context"].account_evidence)
        result = case["result"]["historical_feed_cost_applicability"]
        fee = next(row for row in result["category_results"] if row["category"] == "FEE_SCHEDULE")
        self.assertEqual(fee["status"], "CONFLICTING_SOURCES")
        self.assertIn("ACCOUNT_SCOPE_UNRESOLVED", fee["reason_codes"])
        self.assertEqual([row["numeric_assertion"]["value"] for row in fee["assertion_results"]], ["0.1", "0.2"])
        self.assertIsNone(result["derived_fee_rates"])

    def test_all_cases_preserve_native_snapshot_and_no_execution_or_parameter_authority(self):
        native = self.material["anchor_review_event"].payload["result"]["anchor_qualification"]["result"]
        for case in self.cases.values():
            result = case["result"]
            self.assertEqual(result["status"], "DESCRIPTIVE_EVIDENCE_RECONCILIATION_ONLY")
            self.assertEqual(result["native_qualification_snapshot"], native)
            self.assertEqual(result["native_reason_codes"], native["reason_codes"])
            self.assertEqual(result["native_coverage_proposal"]["status"], "UNRESOLVED")
            self.assertIsNone(result["cost_assumptions_proposal"])
            self.assertEqual(result["execution_status"], "NOT_EXECUTED")
            self.assertIsNone(result["realized_trade_pnl"])
            for field in ("native_qualification_recomputed", "native_coverage_proposal_applied", "native_gate_override", "source_authentication_verified", "historical_point_in_time_verified", "source_applicability_verified", "opening_execution_capacity_verified", "uncertainty_computed", "economic_hypothesis_supported", "auto_trading_enabled"):
                self.assertFalse(result[field], field)
            self.assertFalse(any(result["authority"].values()))
            applicability = result["historical_feed_cost_applicability"]
            for field in ("derived_fee_rates", "derived_unit_multiplier", "derived_slippage", "derived_fill_capacity"):
                self.assertIsNone(applicability[field])

    def test_new_events_retain_original_independent_bytes_without_duplicate_quote_corpus(self):
        quote_hashes = {sha256_bytes(raw) for path, raw in self.material["authored_evidence"].items() if path.endswith(".body.raw")}
        for case in self.cases.values():
            event = case["review_event"]
            self.assertFalse(quote_hashes & {ref["sha256"] for ref in event.evidence})
            self.assertIn("independent-evidence/result.v1.json", {ref["path"] for ref in event.evidence})
            body = case["inventory"].body_evidence
            self.assertIn(body["sha256"], {ref["sha256"] for ref in event.evidence})
            self.assertEqual(self.material["blobs"][body["sha256"]], self.material["authored_evidence"][body["path"]])

    def test_exact_reprojection_after_later_reviews_uses_original_prefix(self):
        case = self.cases["empty-observations"]
        replay = review_material(case["request"], self.material["events"], self.material["blobs"])
        self.assertEqual(replay["event"].to_bytes(), case["review_event"].to_bytes())

    def test_unsafe_source_git_and_runtime_destinations_reject_before_fixture_work(self):
        repository = Path(__file__).resolve().parents[1]
        temporary = tempfile.TemporaryDirectory(); self.addCleanup(temporary.cleanup)
        root = Path(temporary.name).resolve(); (root / "ledger.lock").write_bytes(b"")
        for output in (repository / "src" / "forbidden-independent-example", repository / ".git" / "forbidden-independent-example", root / "nested"):
            with patch.object(examples, "example_material", side_effect=AssertionError("fixture must not run")):
                with self.assertRaises(ValueError): examples.prepare_example(output)
            self.assertFalse(output.exists())

    def test_interrupted_source_prefix_publication_recovers_and_retries_without_writes(self):
        temporary = tempfile.TemporaryDirectory(); self.addCleanup(temporary.cleanup)
        root = Path(temporary.name).resolve() / "example"
        store = JournalStore(root / "journal")
        append_journal_batch(store, [{"event": event, "evidence": evidence} for event, evidence in
            zip(self.material["events"][:39], self.material["event_evidence"][:39])])
        original = {path.name: path.read_bytes() for path in (store.root / "entries").glob("*.json")}
        with patch.object(examples, "example_material", return_value=self.material):
            first = examples.prepare_example(root)
            self.assertEqual(first["events_written"], 3)
            manifest = (root / "manifest.json").read_bytes()
            second = examples.prepare_example(root)
        self.assertEqual(second["events_written"], 0)
        self.assertEqual((root / "manifest.json").read_bytes(), manifest)
        self.assertEqual({name: (store.root / "entries" / name).read_bytes() for name in original}, original)
        self.assertEqual(second["journal_verification"]["event_count"], 42)
        self.assertEqual(second["journal_verification"]["orphan_evidence_count"], 0)
        self.assertEqual(second["journal_verification"]["staging_orphan_count"], 0)
        self.assertEqual(second["provider_calls"], 0)
        self.assertFalse(second["auto_trading_enabled"])


if __name__ == "__main__": unittest.main()
