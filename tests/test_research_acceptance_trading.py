"""Offline acceptance projection; frozen software fixtures establish no alpha."""
import ast
import copy
import inspect
import socket
import unittest
from unittest.mock import patch

from blackpod_build_week import research_acceptance_trading as adapter
from blackpod_build_week.contracts.decision_journal import JournalEvent
from blackpod_build_week.contracts.trading_shadow_research import TradingShadowStudy
from blackpod_build_week.contracts.trading_shadow_review import ReviewedShadowStudy
from blackpod_build_week.hashing import canonical_json_bytes, sha256_bytes
from blackpod_build_week.trading_shadow_example import example_material as old_shadow_example
from blackpod_build_week.trading_shadow_review_example import example_material
from blackpod_build_week.trading_shadow_journal import build_study_event, build_shadow_evaluation_event, evidence_for_shadow
from blackpod_build_week.trading_shadow_review_journal import build_reviewed_study_event, build_reviewed_evaluation_event, evidence_for_reviewed_study


def material_with_blobs(factory=example_material):
    material = factory()
    blobs = dict(material["blobs"])
    for retained in material["event_evidence"]:
        blobs.update({sha256_bytes(raw): raw for raw in retained.values()})
    return {**material, "blobs": blobs}


def acceptance_request(material, index=0, *, evaluation=True, scope="EXPLORATORY_RESEARCH"):
    row = material["studies"][index]
    return {
        "schema_version": "blackpod.research_assessment_request.v1",
        "assessment_id": "trading-acceptance-fixture-%d" % index,
        "domain": "TRADING", "recorded_at": "2025-04-02T00:00:00Z",
        "data_cutoff_at": "2025-04-01T23:00:00Z", "assessment_scope": scope,
        "methodology_version": adapter.METHOD_VERSION,
        "hypothesis": {"hypothesis_id": row["hypothesis"].hypothesis_id,
            "source_event_id": row["study_event"].payload["hypothesis_event_id"],
            "document_schema_version": row["hypothesis"].schema_version,
            "evidence": row["plan"].frozen_hypothesis_evidence},
        "research_event_id": row["study_event"].event_id,
        "evaluation_event_id": row["evaluation_event"].event_id if evaluation else None,
        "candidate_result_evidence": None, "supersedes_event_id": None,
        "governance_status": "RESEARCH_ONLY_NOT_AUTHORIZATION", "auto_trading_enabled": False,
        "authority": {key: False for key in ("authorization_enabled", "capital_activation_enabled", "execution_enabled", "policy_changes_enabled")},
    }


class TradingAcceptanceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with patch.object(socket.socket, "connect", side_effect=AssertionError("network forbidden")), patch("subprocess.Popen", side_effect=AssertionError("worker forbidden")):
            cls.frozen = material_with_blobs()
            cls.old_frozen = material_with_blobs(old_shadow_example)

    def setUp(self):
        self.enterContext(patch.object(socket.socket, "connect", side_effect=AssertionError("network forbidden")))
        self.enterContext(patch("subprocess.Popen", side_effect=AssertionError("worker forbidden")))
        self.enterContext(patch("subprocess.run", side_effect=AssertionError("provider forbidden")))
        self.request = acceptance_request(self.frozen)

    def assess(self, request=None, material=None):
        material = material or self.frozen
        return adapter.assess_trading_acceptance(request or self.request, material["events"], material["blobs"])

    def fields(self, **kwargs):
        return self.assess(**kwargs)["assessment_fields"]

    def test_original_continuation_descriptively_contradicted_in_frozen_fixture(self):
        fields = self.fields()
        self.assertEqual(self.frozen["studies"][0]["hypothesis"].hypothesis_id, "five-session-continuation-v1")
        self.assertEqual(fields["classification"], "CONTRADICTED")
        self.assertTrue(fields["evaluation_performed"])
        self.assertFalse(fields["economic_hypothesis_supported"])
        self.assertIn("development intervals only", fields["claim_scope"])

    def test_positive_but_cost_stress_failure_is_inconclusive(self):
        request = acceptance_request(self.frozen, 1)
        fields = self.fields(request=request)
        self.assertEqual(fields["classification"], "INCONCLUSIVE")
        self.assertTrue(any(row["effect"] == "CONTRADICTS" and row["criterion"] == "BENCHMARK_COMPARISON" for row in fields["findings"]))
        self.assertTrue(any(row["criterion"] == "ECONOMIC_ROBUSTNESS" for row in fields["findings"]))
        self.assertFalse(fields["economic_hypothesis_supported"])

    def test_registration_without_outcome_evaluable_exploratory(self):
        request = acceptance_request(self.frozen, evaluation=False)
        fields = self.fields(request=request)
        self.assertEqual(fields["classification"], "EVALUABLE")
        self.assertFalse(fields["evaluation_performed"])

    def test_economic_validation_without_evaluation_not_evaluable(self):
        request = acceptance_request(self.frozen, evaluation=False, scope="ECONOMIC_VALIDATION")
        fields = self.fields(request=request)
        self.assertEqual(fields["classification"], "NOT_EVALUABLE")
        self.assertTrue(any(row["criterion"] == "ECONOMIC_VALIDITY" for row in fields["findings"]))

    def test_fixture_negative_signs_do_not_establish_economic_contradiction(self):
        request = acceptance_request(self.frozen, scope="ECONOMIC_VALIDATION")
        self.assertEqual(self.fields(request=request)["classification"], "INCONCLUSIVE")

    def test_original_v15_evaluation_supported_without_changing_native_method(self):
        request = acceptance_request(self.old_frozen)
        fields = self.fields(request=request, material=self.old_frozen)
        self.assertTrue(fields["evaluation_performed"])
        self.assertNotEqual(fields["classification"], "SUPPORTED")
        self.assertEqual(self.old_frozen["studies"][0]["result"]["schema_version"], "blackpod.trading_shadow_evaluation.v1")

    def test_v14_quality_evaluation_is_not_strategy_evaluation(self):
        row = self.frozen["base_studies"][0]
        request = copy.deepcopy(self.request)
        request["research_event_id"] = row["plan_event"].event_id
        request["evaluation_event_id"] = row["evaluation_event"].event_id
        request["hypothesis"]["hypothesis_id"] = row["hypothesis"].hypothesis_id
        request["hypothesis"]["evidence"] = row["plan"].frozen_hypothesis_evidence
        fields = self.fields(request=request)
        self.assertEqual(fields["classification"], "NOT_EVALUABLE")
        self.assertFalse(fields["evaluation_performed"])

    def test_evidence_ref_hash_or_size_mismatch_rejects(self):
        for field, value in (("sha256", "a" * 64), ("size_bytes", 1)):
            request = copy.deepcopy(self.request)
            request["hypothesis"]["evidence"][field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.assess(request=request)

    def test_wrong_catalog_member_identity_rejects(self):
        request = copy.deepcopy(self.request)
        request["hypothesis"]["hypothesis_id"] = self.frozen["studies"][1]["hypothesis"].hypothesis_id
        with self.assertRaisesRegex(ValueError, "catalog member"):
            self.assess(request=request)

    def test_wrong_hypothesis_research_relationship_rejects(self):
        request = acceptance_request(self.frozen, 1)
        request["hypothesis"] = copy.deepcopy(self.request["hypothesis"])
        with self.assertRaisesRegex(ValueError, "original hypothesis"):
            self.assess(request=request)

    def test_wrong_evaluation_relationship_rejects(self):
        request = copy.deepcopy(self.request)
        request["evaluation_event_id"] = self.frozen["studies"][1]["evaluation_event"].event_id
        with self.assertRaisesRegex(ValueError, "original research"):
            self.assess(request=request)

    def test_missing_source_or_duplicate_event_rejects(self):
        material = {**self.frozen, "events": self.frozen["events"] + (self.frozen["studies"][0]["study_event"],)}
        with self.assertRaisesRegex(ValueError, "unique retained"):
            self.assess(material=material)
        request = copy.deepcopy(self.request); request["research_event_id"] = "journal-event-" + "a" * 64
        with self.assertRaisesRegex(ValueError, "unique retained"):
            self.assess(request=request)

    def test_cutoff_preceding_frozen_evaluation_rejects(self):
        request = copy.deepcopy(self.request); request["data_cutoff_at"] = "2025-04-01T14:59:59Z"
        with self.assertRaisesRegex(ValueError, "cutoff"):
            self.assess(request=request)

    def test_mutated_native_evaluation_is_rejected_not_accepted_as_invalid_source(self):
        original = self.frozen["studies"][0]["evaluation_event"]
        changed = original.to_dict(); changed["payload"]["result"]["status"] = "SHADOW_SIMULATED_FORGED"
        forged = JournalEvent.from_mapping(changed)
        events = tuple(forged if row.event_id == original.event_id else row for row in self.frozen["events"])
        with self.assertRaisesRegex(ValueError, "replay"):
            self.assess(material={**self.frozen, "events": events})

    def candidate(self, value, *, raw=None):
        body = raw if raw is not None else canonical_json_bytes(value)
        ref = {"path": "acceptance/candidate-result.raw", "sha256": sha256_bytes(body), "size_bytes": len(body)}
        request = copy.deepcopy(self.request); request["candidate_result_evidence"] = ref
        return request, {**self.frozen, "blobs": {**self.frozen["blobs"], ref["sha256"]: body}}

    def test_separate_forged_candidate_result_is_invalid_without_rewriting_original(self):
        original = self.frozen["studies"][0]["result"]
        value = copy.deepcopy(original); value["status"] = "SUPPORTED"
        request, material = self.candidate(value)
        fields = self.fields(request=request, material=material)
        self.assertEqual(fields["classification"], "INVALID")
        self.assertTrue(any(row["effect"] == "INVALID" for row in fields["findings"]))
        self.assertEqual(original["status"], "SHADOW_SIMULATED")

    def test_separate_identical_candidate_replays_exactly(self):
        request, material = self.candidate(self.frozen["studies"][0]["result"])
        fields = self.fields(request=request, material=material)
        self.assertEqual(fields["classification"], "CONTRADICTED")
        self.assertTrue(any(row["criterion"] == "REPRODUCIBILITY" and row["observed"] is True for row in fields["findings"]))

    def test_separate_malformed_candidate_is_invalid(self):
        request, material = self.candidate(None, raw=b'{"status":"x","status":"y"}')
        self.assertEqual(self.fields(request=request, material=material)["classification"], "INVALID")

    def test_retained_candidate_bytes_are_in_evidence(self):
        request, material = self.candidate(None, raw=b'{"bad":true}')
        report = self.assess(request=request, material=material)
        self.assertEqual(report["evidence"]["acceptance/candidate-result.raw"], b'{"bad":true}')

    def test_every_native_economic_measurement_preserves_value_and_pointer(self):
        fields = self.fields()
        rows = [row for row in fields["findings"] if row["criterion"] == "ECONOMIC_MEASUREMENTS"]
        metrics = self.frozen["studies"][0]["result"]["calculation_result"]["cost_stress_runs"][0]["candidate"]["folds"][0]["metrics"]
        for key in adapter._METRICS:
            row = next(row for row in rows if row["value_pointer"].endswith("/" + key))
            self.assertEqual(row["observed"], metrics.get(key))
            if row["observed"] is None: self.assertEqual(row["effect"], "UNKNOWN")
        self.assertTrue(any(row["criterion"] == "GROSS_PERFORMANCE" and "adversely adjusted" in row["statement"] for row in fields["findings"]))

    def test_statistical_metrics_not_invented(self):
        fields = self.fields()
        rows = [row for row in fields["findings"] if row["criterion"] == "ECONOMIC_MEASUREMENTS"]
        for key in ("sharpe_ratio", "sortino_ratio", "annualized_return"):
            self.assertTrue(all(row["observed"] is None for row in rows if row["value_pointer"].endswith("/" + key)))
        self.assertTrue(any(row["observed"] == "NOT_ASSESSED" for row in rows))

    def test_traceable_classification_retains_different_source_statuses(self):
        fields = self.fields()
        self.assertEqual([row["native_status"] for row in fields["native_status_mapping"]], ["PROPOSED_SPECIFICATION", "TRADING_REVIEWED_SHADOW_STUDY_REGISTERED", "SHADOW_SIMULATED"])
        self.assertEqual(fields["native_status_mapping"][-1]["mapped_classification"], "CONTRADICTED")

    def test_original_authority_and_holdout_unchanged(self):
        before = [event.to_bytes() for event in self.frozen["events"]]
        fields = self.fields()
        self.assertEqual(before, [event.to_bytes() for event in self.frozen["events"]])
        self.assertEqual(self.frozen["studies"][0]["result"]["final_holdout"]["scoring_status"], "WITHHELD")
        self.assertFalse(self.frozen["studies"][0]["result"]["auto_trading_enabled"])
        self.assertFalse(fields["economic_hypothesis_supported"])
        self.assertFalse(fields["source_authentication_verified"])
        self.assertFalse(fields["historical_point_in_time_verified"])

    def test_outputs_do_not_alias_sources_and_exact_retry_deterministic(self):
        first = self.assess(); second = self.assess()
        self.assertEqual(first, second)
        first["assessment_fields"]["findings"][0]["statement"] = "changed"
        first["evidence"].clear()
        self.assertEqual(second, self.assess())

    def test_missing_gate_registration_and_deferred_evaluation_not_evaluable(self):
        study = self.frozen["studies"][0]["study"].to_dict()
        study.update(study_id="acceptance-missing-gates", experiment_id="acceptance-missing-gates-experiment", registered_at="2025-04-01T16:00:00Z",
                     continuity_intake_evidence=None, cost_intake_evidence=None,
                     trial_registry={"trial_id": "acceptance-missing-gates-trial", "prior_trial_ids": []})
        study = ReviewedShadowStudy.from_mapping(study)
        registration = build_reviewed_study_event(study, self.frozen["events"], self.frozen["blobs"])
        events = self.frozen["events"] + (registration,)
        retained = evidence_for_reviewed_study(study, events, self.frozen["blobs"])
        blobs = {**self.frozen["blobs"], **{sha256_bytes(raw): raw for raw in retained.values()}}
        request = copy.deepcopy(self.request)
        request.update(research_event_id=registration.event_id, evaluation_event_id=None)
        material = {**self.frozen, "events": events, "blobs": blobs}
        fields = self.fields(request=request, material=material)
        self.assertEqual(fields["classification"], "NOT_EVALUABLE")
        self.assertFalse(fields["evaluation_performed"])
        self.assertTrue(any(row["observed"] == "CONTINUITY_INTAKE_MISSING" for row in fields["findings"]))
        evaluation = build_reviewed_evaluation_event(study, events, blobs, evaluation_id="acceptance-missing-gates-evaluation", recorded_at="2025-04-01T17:00:00Z")
        request["evaluation_event_id"] = evaluation.event_id
        material["events"] = events + (evaluation,)
        fields = self.fields(request=request, material=material)
        self.assertEqual(fields["classification"], "NOT_EVALUABLE")
        self.assertFalse(fields["evaluation_performed"])

    def test_every_pointed_finding_resolves_exact_original_scalar(self):
        fields = self.fields()
        events = {row.event_id: row.to_dict() for row in self.frozen["events"]}
        for row in fields["findings"]:
            if row["value_pointer"] is None:
                continue
            current = events[row["evidence_event_id"]]
            for part in row["value_pointer"].split("/")[1:]:
                part = part.replace("~1", "/").replace("~0", "~")
                current = current[int(part)] if isinstance(current, list) else current[part]
            self.assertEqual(row["observed"], current, row)

    def test_no_network_provider_legacy_or_execution_imports(self):
        tree = ast.parse(inspect.getsource(adapter))
        imports = [node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)]
        imports += [alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names]
        for forbidden in ("galactica", "alpaca", "navigator", "modeldock", "subprocess", "socket", "auto_trading"):
            self.assertFalse(any(forbidden in item.lower() for item in imports), forbidden)


if __name__ == "__main__":
    unittest.main()
