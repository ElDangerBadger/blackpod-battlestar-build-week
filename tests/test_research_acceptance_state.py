"""Separate eligibility, integrity and outcomes without altering frozen v17."""
import contextlib
import copy
import io
import json
from pathlib import Path
import socket
import tempfile
import unittest
from unittest.mock import patch

from blackpod_build_week.contracts.decision_journal import JournalEvent
from blackpod_build_week.contracts.research_acceptance_state import ResearchAcceptanceState
from blackpod_build_week.decision_journal_store import JournalStore
from blackpod_build_week.hashing import canonical_json_bytes, sha256_bytes
from blackpod_build_week.research_acceptance_cli import main
from blackpod_build_week.research_acceptance_examples import representative_material
from blackpod_build_week.research_acceptance_journal import assessment_material
from blackpod_build_week.research_acceptance_state import project_assessment_state
from test_research_acceptance_investment import FrozenInvestmentContext


def attach(request, events, blobs):
    material = assessment_material(request, events, blobs)
    retained = {**blobs, **{sha256_bytes(raw): raw for raw in material["evidence"].values()}}
    return (*events, material["event"]), retained, material


class ResearchAcceptanceStateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.material = representative_material()
        cls.states, cls.contexts = {}, {}
        for case in cls.material["cases"]:
            blobs = {**cls.material["blobs"], **{sha256_bytes(raw): raw for raw in case.get("extra_evidence", {}).values()}}
            events, blobs, material = attach(case["request"], cls.material["events"], blobs)
            cls.contexts[case["case_id"]] = (events, blobs, material)
            cls.states[case["case_id"]] = project_assessment_state(material["event"].event_id, events, blobs)

    def setUp(self):
        self.enterContext(patch.object(socket.socket, "connect", side_effect=AssertionError("network forbidden")))
        self.enterContext(patch("subprocess.Popen", side_effect=AssertionError("workers forbidden")))

    def state(self, case="contradicted-comparison"):
        return self.states[case]

    def test_all_six_classifications_reproduce(self):
        self.assertEqual({state.classification for state in self.states.values()},
                         {"NOT_EVALUABLE", "EVALUABLE", "INCONCLUSIVE", "SUPPORTED", "CONTRADICTED", "INVALID"})
        for case in self.material["cases"]:
            state = self.state(case["case_id"])
            self.assertEqual(state.original_classification, case["expected"])
            self.assertEqual(state.classification, case["expected"])

    def test_evaluable_is_eligibility_without_terminal_outcome(self):
        state = self.state("valid-unproven")
        self.assertEqual(state.eligibility, "EVALUABLE")
        self.assertIsNone(state.outcome)
        self.assertFalse(state.evaluation_performed)
        self.assertFalse(state.native_evaluation_performed)

    def test_contradiction_and_support_do_not_change_eligibility(self):
        for case, outcome in (("contradicted-comparison", "CONTRADICTED"),
                              ("supported-deadline-predicates", "SUPPORTED"),
                              ("positive-insufficient-robustness", "INCONCLUSIVE")):
            with self.subTest(case=case):
                state = self.state(case)
                self.assertEqual(state.eligibility, "EVALUABLE")
                self.assertEqual(state.outcome, outcome)
                self.assertTrue(state.evaluation_performed)

    def test_missing_prerequisites_have_no_outcome(self):
        state = self.state("missing-prerequisites")
        self.assertEqual(state.eligibility, "NOT_EVALUABLE")
        self.assertIsNone(state.outcome)
        self.assertFalse(state.evaluation_performed)
        self.assertTrue(state.eligibility_reason_codes)

    def test_invalid_candidate_is_integrity_failure_without_promoting_native_result(self):
        state = self.state("methodologically-invalid")
        self.assertEqual(state.eligibility, "EVALUABLE")
        self.assertEqual(state.integrity, "INVALID")
        self.assertEqual(state.classification, "INVALID")
        self.assertIsNone(state.outcome)
        self.assertTrue(state.native_evaluation_performed)
        self.assertFalse(state.evaluation_performed)
        self.assertEqual(state.source_assessment["classification"], "INVALID")

    def test_trading_and_investment_keep_distinct_native_horizons_and_scopes(self):
        trading = self.state()
        investment = self.state("supported-deadline-predicates")
        self.assertEqual(trading.domain, "TRADING")
        self.assertEqual(investment.domain, "INVESTMENT")
        self.assertIn("holding_sessions", trading.hypothesis["document"]["horizon"])
        self.assertIn("end_at", investment.hypothesis["document"]["horizon"])
        self.assertEqual(trading.hypothesis["market_scope"]["kind"], "SYMBOL")
        self.assertIn("recorded_at", trading.hypothesis["document"])
        self.assertIn("recorded_at", investment.hypothesis["document"])
        self.assertNotEqual(trading.source_assessment["request"]["methodology_version"],
                            investment.source_assessment["request"]["methodology_version"])

    def test_economic_scope_remains_not_evaluable_even_when_native_calculation_performed(self):
        for domain in ("TRADING", "INVESTMENT"):
            with self.subTest(domain=domain):
                source = next(case for case in self.material["cases"] if case["case_id"] ==
                              ("positive-insufficient-robustness" if domain == "TRADING" else "supported-deadline-predicates"))
                request = source["request"].to_dict()
                request.update(assessment_id="economic-" + domain.lower(), assessment_scope="ECONOMIC_VALIDATION")
                events, blobs, material = attach(request, self.material["events"], self.material["blobs"])
                state = project_assessment_state(material["event"].event_id, events, blobs)
                self.assertTrue(state.native_evaluation_performed)
                self.assertEqual(state.eligibility, "NOT_EVALUABLE")
                self.assertEqual(state.classification, "NOT_EVALUABLE")
                self.assertIsNone(state.outcome)
                self.assertEqual(state.original_classification, material["assessment"].classification)

    def investment_state(self, outcome=None, scope="DECLARED_DEADLINE_PREDICATES"):
        context = FrozenInvestmentContext(outcome)
        events, blobs, material = attach(context.request(scope), context.events, context.blobs)
        return project_assessment_state(material["event"].event_id, events, blobs)

    def test_absent_deadline_evaluation_is_not_evaluable(self):
        state = self.investment_state()
        self.assertEqual(state.eligibility, "NOT_EVALUABLE")
        self.assertIsNone(state.outcome)

    def test_expired_horizon_with_missing_measurements_is_inconclusive_not_failure(self):
        state = self.investment_state("missing")
        self.assertEqual(state.eligibility, "EVALUABLE")
        self.assertEqual(state.outcome, "INCONCLUSIVE")
        self.assertNotIn("ORIGINAL_INVESTMENT_HORIZON_NOT_ELAPSED", state.source_assessment["limitations"])
        self.assertEqual(state.hypothesis["document"]["horizon"]["end_at"], "2027-04-11T00:00:00Z")

    def test_pending_horizon_remains_inconclusive(self):
        state = self.investment_state("interim")
        self.assertEqual(state.outcome, "INCONCLUSIVE")
        self.assertIn("ORIGINAL_INVESTMENT_HORIZON_NOT_ELAPSED", state.source_assessment["limitations"])

    def test_invalidation_is_scoped_contradiction(self):
        self.assertEqual(self.investment_state("invalidation").outcome, "CONTRADICTED")

    def test_original_assessment_and_source_bytes_unchanged(self):
        events, blobs, material = self.contexts["contradicted-comparison"]
        before = tuple(event.to_bytes() for event in events), dict(blobs)
        state = project_assessment_state(material["event"].event_id, events, blobs)
        self.assertEqual(state.source_assessment, material["assessment"].to_dict())
        self.assertEqual((tuple(event.to_bytes() for event in events), blobs), before)

    def test_exact_identity_and_leaf_hash_binding(self):
        events, blobs, material = self.contexts["contradicted-comparison"]
        state = self.state()
        self.assertEqual(state.source_assessment_event["event_sha256"], sha256_bytes(material["event"].to_bytes()))
        self.assertEqual(state.source_assessment_event["assessment_evidence"]["sha256"], sha256_bytes(material["assessment"].to_bytes()))
        for identity in ("journal-event-" + "f" * 64, events[0].event_id):
            with self.subTest(identity=identity), self.assertRaises(ValueError):
                project_assessment_state(identity, events, blobs)

    def test_duplicate_history_rejected(self):
        events, blobs, material = self.contexts["contradicted-comparison"]
        with self.assertRaises(ValueError):
            project_assessment_state(material["event"].event_id, (*events, events[0]), blobs)

    def test_missing_and_corrupt_retained_implementation_rejected(self):
        events, blobs, material = self.contexts["contradicted-comparison"]
        ref = next(ref for ref in material["event"].evidence if ref["path"].startswith("research-acceptance/implementation/"))
        for value in (None, b"wrong bytes"):
            changed = dict(blobs)
            if value is None: del changed[ref["sha256"]]
            else: changed[ref["sha256"]] = value
            with self.subTest(value=value), self.assertRaises(ValueError):
                project_assessment_state(material["event"].event_id, events, changed)

    def test_tampered_assessment_scalar_rejected_by_replay(self):
        events, blobs, material = self.contexts["contradicted-comparison"]
        changed = material["event"].to_dict()
        changed["payload"]["assessment"]["findings"][0]["statement"] = "Changed interpretation"
        tampered = JournalEvent.from_mapping(changed)
        with self.assertRaises(ValueError):
            project_assessment_state(tampered.event_id, (*events[:-1], tampered), blobs)

    def test_source_cutoff_and_lookahead_contamination_rejected(self):
        source = next(case for case in self.material["cases"] if case["case_id"] == "contradicted-comparison")
        request = source["request"].to_dict()
        request["data_cutoff_at"] = "2025-01-01T00:00:00Z"
        with self.assertRaises(ValueError): attach(request, self.material["events"], self.material["blobs"])
        request["data_cutoff_at"] = "2099-01-01T00:00:00Z"
        with self.assertRaises(ValueError): attach(request, self.material["events"], self.material["blobs"])

    def test_cross_desk_source_rejected(self):
        source = next(case for case in self.material["cases"] if case["case_id"] == "contradicted-comparison")
        request = source["request"].to_dict()
        request["research_event_id"] = self.material["investment"]["hypothesis_event"].event_id
        with self.assertRaises(ValueError): attach(request, self.material["events"], self.material["blobs"])

    def test_canonical_deterministic_roundtrip_and_no_alias(self):
        state = self.state()
        self.assertEqual(ResearchAcceptanceState.from_bytes(state.to_bytes()).to_bytes(), state.to_bytes())
        events, blobs, material = self.contexts["contradicted-comparison"]
        self.assertEqual(project_assessment_state(material["event"].event_id, events, blobs).to_bytes(), state.to_bytes())
        changed = state.to_dict(); changed["hypothesis"]["document"]["name"] = "Changed"
        self.assertNotEqual(state.hypothesis["document"]["name"], "Changed")
        with self.assertRaises((TypeError, AttributeError)): state.eligibility = "NOT_EVALUABLE"

    def test_strict_fields_versions_and_classification_consistency(self):
        for field, value in (("schema_version", "unknown"), ("method_version", "unknown"), ("extra", True),
                             ("eligibility", "SUPPORTED"), ("outcome", "EVALUABLE"), ("classification", "SUPPORTED"),
                             ("original_classification", "INCONCLUSIVE"), ("domain", "INVESTMENT"),
                             ("evaluation_performed", 1), ("integrity", "INVALID"), ("eligibility_reason_codes", [])):
            changed = self.state().to_dict(); changed[field] = value
            with self.subTest(field=field), self.assertRaises(ValueError): ResearchAcceptanceState.from_mapping(changed)

    def test_authority_and_authenticity_never_promoted(self):
        for state in self.states.values():
            self.assertFalse(state.auto_trading_enabled)
            self.assertTrue(all(value is False for value in state.authority.values()))
            self.assertFalse(state.source_assessment["source_authentication_verified"])
            self.assertFalse(state.source_assessment["historical_point_in_time_verified"])
            self.assertFalse(state.source_assessment["economic_hypothesis_supported"])
        for field in self.state().authority:
            changed = self.state().to_dict(); changed["authority"][field] = True
            with self.subTest(field=field), self.assertRaises(ValueError): ResearchAcceptanceState.from_mapping(changed)

    def test_hypothesis_scope_and_reference_corruption_rejects(self):
        for path, value in (("source_event_id", "journal-event-" + "a" * 64),
                            ("document_evidence", {"path": "bad", "sha256": "a" * 64, "size_bytes": 1})):
            changed = self.state().to_dict(); changed["hypothesis"][path] = value
            with self.subTest(path=path), self.assertRaises(ValueError): ResearchAcceptanceState.from_mapping(changed)
        changed = self.state().to_dict(); changed["source_assessment_event"]["assessment_evidence"]["size_bytes"] += 1
        with self.assertRaises(ValueError): ResearchAcceptanceState.from_mapping(changed)

    def test_trading_scope_cannot_replace_original_plan_universe(self):
        changed = self.state().to_dict()
        changed["hypothesis"]["market_scope"]["identifiers"] = ["INVENTED"]
        with self.assertRaises(ValueError): ResearchAcceptanceState.from_mapping(changed)
        changed = self.state().to_dict()
        changed["trading_plan"]["document"]["universe"] = ["INVENTED"]
        with self.assertRaises(ValueError): ResearchAcceptanceState.from_mapping(changed)
        changed = self.state().to_dict()
        changed["trading_plan"]["document_evidence"]["path"] = "unretained-plan.json"
        with self.assertRaises(ValueError): ResearchAcceptanceState.from_mapping(changed)
        changed = self.state().to_dict(); changed["trading_plan"] = None
        with self.assertRaises(ValueError): ResearchAcceptanceState.from_mapping(changed)

    def test_investment_scope_cannot_acquire_trading_plan_or_new_identifiers(self):
        changed = self.state("supported-deadline-predicates").to_dict()
        changed["hypothesis"]["market_scope"]["identifiers"] = ["INVENTED"]
        with self.assertRaises(ValueError): ResearchAcceptanceState.from_mapping(changed)
        changed = self.state("supported-deadline-predicates").to_dict()
        changed["trading_plan"] = self.state().trading_plan
        with self.assertRaises(ValueError): ResearchAcceptanceState.from_mapping(changed)

    def test_cli_state_is_read_only_and_export_is_immutable(self):
        events, _, material = self.contexts["contradicted-comparison"]
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve(); store = JournalStore(root / "journal")
            for event, evidence in zip(self.material["events"], self.material["event_evidence"]):
                store.append(event, evidence)
            store.append(material["event"], material["evidence"])
            before = {str(path.relative_to(store.root)): path.read_bytes() for path in store.root.rglob("*") if path.is_file()}
            output = root / "report" / "state.json"
            argv = ["state", "--event-id", material["event"].event_id, "--journal-root", str(store.root), "--output", str(output)]
            for _ in range(2):
                stream = io.StringIO()
                with contextlib.redirect_stdout(stream): code = main(argv)
                self.assertEqual(code, 0, stream.getvalue())
                self.assertEqual(ResearchAcceptanceState.from_bytes(output.read_bytes()).to_dict(), json.loads(stream.getvalue()))
            after = {str(path.relative_to(store.root)): path.read_bytes() for path in store.root.rglob("*") if path.is_file()}
            self.assertEqual(before, after)
            stream = io.StringIO()
            with contextlib.redirect_stdout(stream):
                code = main([*argv[:-1], str(store.root / "forbidden.json")])
            self.assertEqual(code, 2)
            self.assertFalse((store.root / "forbidden.json").exists())


if __name__ == "__main__":
    unittest.main()
