"""Strict frozen designs, unchanged source history, no execution authority."""
import copy
from pathlib import Path
import socket
import tempfile
import shutil
import unittest
from unittest.mock import patch

from blackpod_build_week.contracts.trading_evidence_qualification import TradingEvidenceQualificationPolicy, TradingEvidenceQualificationRequest, TradingTrainingAssumptions, uncertainty_protocol
from blackpod_build_week.contracts.decision_journal import JournalEvent
from blackpod_build_week.decision_journal_store import JournalStore, JournalStoreError, JournalPersistenceError
from blackpod_build_week.hashing import sha256_bytes
from blackpod_build_week.trading_evidence_qualification import prepare_policy, qualify_evidence
from blackpod_build_week.trading_evidence_qualification_journal import policy_material, qualification_material, validate_qualification_event
from blackpod_build_week.trading_shadow_review_example import example_material


def context():
    m = example_material(); blobs = dict(m["blobs"])
    for evidence in m["event_evidence"]: blobs.update({sha256_bytes(raw): raw for raw in evidence.values()})
    support = b"Authored design test only, no approval or real market claim.\n"
    ref = {"path": "qualification-test/support.raw", "sha256": sha256_bytes(support), "size_bytes": len(support)}
    blobs[ref["sha256"]] = support
    events = tuple(m["events"])
    base = m["studies"][0]["plan_event"]
    ids = {kind: next(event.event_id for event in events if event.event_type == kind) for kind in ("TRADING_CONTINUITY_INTAKE_RECORDED", "TRADING_COST_INTAKE_RECORDED", "TRADING_SHADOW_RISK_REVIEW_RECORDED")}
    policy = prepare_policy(events, blobs, policy_id="root-qualification-test", recorded_at="2025-04-02T00:00:00Z", base_plan_event_id=base.event_id,
        continuity_event_id=ids["TRADING_CONTINUITY_INTAKE_RECORDED"], cost_event_id=ids["TRADING_COST_INTAKE_RECORDED"], risk_review_event_id=ids["TRADING_SHADOW_RISK_REVIEW_RECORDED"],
        supporting_evidence=[ref], reviewer_id="authored-test", review_notes="Proposed research design without calibration permission.", training_quote_chains=[])
    return m, events, blobs, policy


def request(policy_event, **changes):
    return {"schema_version": "blackpod.trading_evidence_qualification_request.v1", "qualification_id": "root-qualified-test",
        "policy_event_id": policy_event.event_id, "recorded_at": "2025-04-02T01:00:00Z", "data_cutoff_at": "2025-04-02T00:30:00Z",
        "supersedes_event_id": None, "auto_trading_enabled": False, "authority": policy_event.payload["policy"]["authority"], **changes}


class QualificationContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.material, cls.events, cls.blobs, cls.policy = context()

    def test_immutable_strict_roundtrip(self):
        self.assertEqual(self.policy.to_bytes(), TradingEvidenceQualificationPolicy.from_bytes(self.policy.to_bytes()).to_bytes())
        value = self.policy.to_dict(); value["status"] = "REJECTED"
        self.assertEqual(self.policy.status, "PROPOSED")
        with self.assertRaises((AttributeError, TypeError)): self.policy.status = "REJECTED"

    def test_unknown_missing_and_future_fields_reject(self):
        for field, value in (("schema_version", "future"), ("domain", "INVESTMENT"), ("scope", "EXECUTION"), ("confidence_probability", .99)):
            document = self.policy.to_dict(); document[field] = value
            with self.subTest(field=field), self.assertRaises(ValueError): TradingEvidenceQualificationPolicy.from_mapping(document)
        document = self.policy.to_dict(); del document["supporting_evidence"]
        with self.assertRaises(ValueError): TradingEvidenceQualificationPolicy.from_mapping(document)

    def test_all_authority_flags_and_auto_switch_strict_false(self):
        for field in self.policy.authority:
            for value in (True, 1, "false"):
                document = self.policy.to_dict(); document["authority"][field] = value
                with self.subTest(field=field, value=value), self.assertRaises(ValueError): TradingEvidenceQualificationPolicy.from_mapping(document)
        document = self.policy.to_dict(); document["auto_trading_enabled"] = True
        with self.assertRaises(ValueError): TradingEvidenceQualificationPolicy.from_mapping(document)

    def test_safe_evidence_paths_and_unique_fold_chains(self):
        document = self.policy.to_dict(); document["supporting_evidence"][0]["path"] = "../outside"
        with self.assertRaises(ValueError): TradingEvidenceQualificationPolicy.from_mapping(document)
        document = self.policy.to_dict(); chain = {"fold_id": "same", "pages": []}; document["training_quote_chains"] = [chain, chain]
        with self.assertRaises(ValueError): TradingEvidenceQualificationPolicy.from_mapping(document)

    def test_uncertainty_is_predeclared_never_computed(self):
        from blackpod_build_week.trading_evidence_qualification_example import fixture_uncertainty_protocol
        p = fixture_uncertainty_protocol()
        self.assertEqual(uncertainty_protocol(p)["holdout_scoring"], "WITHHELD")
        for field, value in (("confidence_level", "1"), ("block_length_sessions", 0), ("seed", True), ("parameter_search_allowed", True), ("holdout_scoring", "SCORE"), ("support_rule", "POSITIVE_RETURN")):
            with self.subTest(field=field), self.assertRaises(ValueError): uncertainty_protocol({**p, field: value})

    def test_default_prepare_never_invents_review_or_protocol(self):
        self.assertEqual(self.policy.status, "PROPOSED")
        self.assertIsNone(self.policy.uncertainty_protocol)
        self.assertIsNone(self.policy.training_cost_assumptions_evidence)
        self.assertFalse(self.policy.auto_trading_enabled)


class QualificationJournalTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.material, cls.events, cls.blobs, cls.policy = context()
        cls.temp = tempfile.TemporaryDirectory(); cls.addClassCleanup(cls.temp.cleanup)
        cls.base = Path(cls.temp.name).resolve() / "journal"
        store = JournalStore(cls.base)
        for event, evidence in zip(cls.material["events"], cls.material["event_evidence"]): store.append(event, evidence)

    def setUp(self):
        self.enterContext(patch.object(socket.socket, "connect", side_effect=AssertionError("network forbidden")))
        self.enterContext(patch("subprocess.Popen", side_effect=AssertionError("workers forbidden")))
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup); self.root = Path(temp.name).resolve()
        shutil.copytree(self.base, self.root / "journal"); self.store = JournalStore(self.root / "journal")

    def freeze(self, policy=None):
        events, blobs = self.store.verified_contents(); blobs.update(self.blobs)
        m = policy_material(policy or self.policy, events, blobs); self.store.append(m["event"], m["evidence"])
        return m

    def evaluate(self, req):
        events, blobs = self.store.verified_contents(); m = qualification_material(req, events, blobs)
        return self.store.append(m["event"], m["evidence"]), m

    def test_policy_freeze_and_assessment_preserve_original_history(self):
        original = [event.to_bytes() for event in self.store.events()]
        frozen = self.freeze(); written, m = self.evaluate(request(frozen["event"]))
        self.assertTrue(written.written)
        self.assertEqual(m["event"].schema_version, "blackpod.decision_journal_event.v18")
        self.assertEqual(m["event"].decision_id, frozen["event"].decision_id)
        self.assertEqual([event.to_bytes() for event in self.store.events()[:14]], original)
        self.assertEqual(m["result"]["status"], "DEFER_EVIDENCE_QUALIFICATION")
        self.assertFalse(m["result"]["uncertainty_computed"])
        self.assertFalse(m["result"]["existing_gate_override"])
        self.assertIsNone(m["result"]["realized_trade_pnl"])
        self.assertEqual(self.store.verify().orphan_evidence_count, 0)

    def test_exact_retry_after_later_link_is_noop(self):
        frozen = self.freeze(); req = request(frozen["event"]); first, original = self.evaluate(req)
        later = {**req, "qualification_id": "later-qualified-test", "recorded_at": "2025-04-03T00:00:00Z", "data_cutoff_at": "2025-04-02T02:00:00Z", "supersedes_event_id": original["event"].event_id}
        self.evaluate(later)
        retry, repeated = self.evaluate(req)
        self.assertFalse(retry.written); self.assertEqual(repeated["event"].to_bytes(), original["event"].to_bytes())

    def test_identity_conflict_requires_new_record(self):
        frozen = self.freeze(); req = request(frozen["event"]); self.evaluate(req)
        with self.assertRaisesRegex(ValueError, "immutable"): self.evaluate({**req, "data_cutoff_at": "2025-04-02T00:45:00Z"})
        document = self.policy.to_dict(); document["review_notes"] = "Changed"
        with self.assertRaisesRegex(ValueError, "immutable"): self.freeze(TradingEvidenceQualificationPolicy.from_mapping(document))

    def test_future_cutoff_and_policy_clock_reject(self):
        frozen = self.freeze()
        with self.assertRaises(ValueError): self.evaluate(request(frozen["event"], data_cutoff_at="2025-04-01T23:00:00Z"))
        document = self.policy.to_dict(); document["recorded_at"] = "2025-04-01T00:00:00Z"
        with self.assertRaises(ValueError): policy_material(document, self.events, self.blobs)

    def test_forged_result_cannot_override_gates_or_compute_support(self):
        frozen = self.freeze(); events, blobs = self.store.verified_contents(); m = qualification_material(request(frozen["event"]), events, blobs)
        for field in ("economic_hypothesis_supported", "uncertainty_computed", "existing_gate_override", "auto_trading_enabled"):
            value = m["event"].to_dict(); value["payload"]["result"][field] = True
            with self.subTest(field=field), self.assertRaises(ValueError): JournalEvent.from_mapping(value)
        value = m["event"].to_dict(); value["payload"]["result"]["limitations"] = ["Replaced explanation"]
        with self.assertRaises(JournalStoreError): self.store.append(JournalEvent.from_mapping(value), m["evidence"])

    def test_supersession_cannot_cross_policy_or_branch(self):
        first = self.freeze(); _, assessment = self.evaluate(request(first["event"]))
        document = self.policy.to_dict(); document["policy_id"] = "other-qualified-policy"
        other = self.freeze(TradingEvidenceQualificationPolicy.from_mapping(document))
        with self.assertRaises(ValueError): self.evaluate(request(other["event"], qualification_id="other-q", supersedes_event_id=assessment["event"].event_id))
        req = request(first["event"], qualification_id="linked-q", supersedes_event_id=assessment["event"].event_id)
        self.evaluate(req)
        with self.assertRaises(ValueError): self.evaluate({**req, "qualification_id": "branch-q"})

    def test_policy_supersession_is_linked_and_immutable(self):
        first = self.freeze(); document = self.policy.to_dict(); document.update(policy_id="new-policy", supersedes_policy_event_id=first["event"].event_id)
        second = self.freeze(TradingEvidenceQualificationPolicy.from_mapping(document))
        self.assertEqual(second["event"].payload["policy"]["supersedes_policy_event_id"], first["event"].event_id)
        self.assertEqual(self.store.events()[-2].to_bytes(), first["event"].to_bytes())

    def test_methodology_and_source_pins_fail_closed(self):
        frozen = self.freeze(); events, blobs = self.store.verified_contents()
        from blackpod_build_week import trading_evidence_qualification
        with patch.object(trading_evidence_qualification, "implementation_evidence", return_value={"qualification/implementation/changed.py": b"different"}):
            with self.assertRaises(ValueError): qualify_evidence(request(frozen["event"]), events, blobs)

    def test_protocol_counts_joint_qualified_source_dates_not_raw_test_sessions(self):
        from blackpod_build_week.trading_evidence_qualification import _protocol
        from blackpod_build_week.trading_evidence_qualification_example import fixture_uncertainty_protocol
        document = self.policy.to_dict(); document["uncertainty_protocol"] = fixture_uncertainty_protocol()
        policy = TradingEvidenceQualificationPolicy.from_mapping(document)
        plan = self.material["studies"][0]["plan"]
        fold = plan.protocol["folds"][0]["fold_id"]
        risk = {"capacity_checks": [{"fold_id": fold, "source_session_id": "same-date", "joint_eligible": True} for _ in range(12)]}
        status, reasons = _protocol(policy, plan, risk)
        self.assertEqual(status, "INFEASIBLE")
        self.assertIn("DECLARED_UNCERTAINTY_QUALIFIED_SAMPLE_INFEASIBLE", reasons)

    def test_risk_cannot_join_disjoint_continuity_and_sizing_windows(self):
        from blackpod_build_week.trading_evidence_qualification import _risk, policy_context
        material = policy_context(self.policy, self.events, self.blobs)
        fold = material["plan"].protocol["folds"][0]["fold_id"]
        symbol = material["dataset"].universe[0]
        native = {"eligible": True, "reason_codes": [], "opportunities": [
            {"fold_id": fold, "symbol": symbol, "source_session_id": "continuity-only", "whole_quantity": "0", "status": "DEFER", "reason_codes": ["KNOWN_CLOSE_BUDGET_BELOW_ONE_WHOLE_SHARE"]},
            {"fold_id": fold, "symbol": symbol, "source_session_id": "sizing-only", "whole_quantity": "1", "status": "FEASIBLE_AT_KNOWN_CLOSE_ONLY", "reason_codes": []}]}
        calibration = {"folds": [{"fold_id": fold, "capacity_proxy": [{"symbol": symbol, "daily_quantity_research_proxy": "100"}]}]}
        continuity = {"opportunities": [{"fold_id": fold, "symbol": symbol, "source_session_id": "continuity-only", "combined_eligible": True}]}
        with patch("blackpod_build_week.trading_shadow_risk_review.assess_shadow_risk_review", return_value=native):
            risk = _risk(material, calibration, continuity, self.blobs)
        self.assertFalse(risk["eligible"])
        self.assertFalse(any(row["joint_eligible"] for row in risk["capacity_checks"]))
        self.assertIn("NO_JOINT_CONTINUITY_SIZING_CAPACITY_WINDOWS", risk["reason_codes"])

    def test_interrupted_publication_recovers(self):
        from blackpod_build_week import decision_journal_store
        frozen = self.freeze(); events, blobs = self.store.verified_contents(); m = qualification_material(request(frozen["event"]), events, blobs)
        original = decision_journal_store._publish_immutable
        def interrupted(staging, directory, name, raw):
            if name.endswith(".json"): raise JournalPersistenceError("interrupted")
            return original(staging, directory, name, raw)
        with patch.object(decision_journal_store, "_publish_immutable", side_effect=interrupted):
            with self.assertRaises(JournalPersistenceError): self.store.append(m["event"], m["evidence"])
        self.assertEqual(self.store.verify().event_count, 15)
        self.assertTrue(self.store.append(m["event"], m["evidence"]).written)
        self.assertEqual(self.store.verify().orphan_evidence_count, 0)
