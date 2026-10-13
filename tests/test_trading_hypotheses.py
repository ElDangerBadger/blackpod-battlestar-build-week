"""Independent specification export and descriptive-only plan adapter checks."""
import unittest
from unittest.mock import patch

from blackpod_build_week.contracts.mission_request import ContractValidationError
from blackpod_build_week.contracts.trading_hypothesis import TradingHypothesis, TradingHypothesisCatalog
from blackpod_build_week.contracts.trading_research import TradingResearchPlan
from blackpod_build_week.hashing import sha256_bytes
from blackpod_build_week.trading_hypotheses import (
    catalog_documents, catalog_hypotheses, hypothesis_catalog, hypothesis_research_strategy,
    validate_hypothesis_catalog,
)
from test_trading_research_contracts import plan_mapping


STAMP = "2026-10-13T00:00:00Z"


class TradingHypothesisExportTests(unittest.TestCase):
    def catalog(self, **kwargs):
        return catalog_hypotheses(STAMP, "research-reviewer", **kwargs)

    def test_repeated_exports_are_byte_identical_and_hash_stable(self):
        first, second = self.catalog(), self.catalog()
        self.assertEqual(first.to_bytes(), second.to_bytes())
        self.assertEqual(sha256_bytes(first.to_bytes()), sha256_bytes(second.to_bytes()))

    def test_named_alias_returns_same_validated_catalog(self):
        self.assertEqual(hypothesis_catalog(STAMP, "research-reviewer").to_bytes(), self.catalog().to_bytes())

    def test_explicit_catalog_identity_is_retained_without_hidden_clock(self):
        catalog = self.catalog(catalog_id="research-freeze-001")
        self.assertEqual(catalog.catalog_id, "research-freeze-001")
        self.assertEqual(catalog.recorded_at, STAMP)
        self.assertTrue(all(row["recorded_at"] == STAMP for row in catalog.hypotheses))

    def test_invalid_caller_author_clock_and_identity_reject(self):
        for stamp, author, identity in (("yesterday", "reviewer", "study-001"), (STAMP, "../reviewer", "study-001"),
                                       (STAMP, "reviewer", "../study")):
            with self.subTest(stamp=stamp, author=author), self.assertRaises(ContractValidationError):
                catalog_hypotheses(stamp, author, catalog_id=identity)

    def test_no_data_model_votes_rules_or_orders_can_be_supplied(self):
        for keyword in ("prices", "galactica_rules", "brigade_votes", "risk_budget", "forecast", "orders"):
            with self.subTest(keyword=keyword), self.assertRaises(TypeError):
                catalog_hypotheses(STAMP, "research-reviewer", **{keyword: {"buy": True}})

    def test_two_mechanisms_lookbacks_and_horizons_remain_distinct(self):
        documents = {row.signal["family"]: row for row in catalog_documents(self.catalog())}
        reversal, continuation = documents["PREVIOUS_SESSION_REVERSAL"], documents["FIVE_SESSION_CONTINUATION"]
        self.assertEqual((reversal.signal["lookback_sessions"], reversal.horizon["holding_sessions"]), (1, 1))
        self.assertEqual((continuation.signal["lookback_sessions"], continuation.horizon["holding_sessions"]), (5, 3))
        self.assertNotEqual(reversal.mechanism["proposed_causal_mechanism"], continuation.mechanism["proposed_causal_mechanism"])
        self.assertEqual(reversal.signal["candidate_condition"], "RETURN_LT_ZERO")
        self.assertEqual(continuation.signal["candidate_condition"], "RETURN_GT_ZERO")

    def test_catalog_hypotheses_remain_untested_and_do_not_select_a_winner(self):
        catalog = self.catalog()
        self.assertEqual(catalog.selection_policy, "NO_WINNER_SELECTED_NO_INTENTS_GENERATED")
        for document in catalog_documents(catalog):
            self.assertEqual(document.mechanism["evidence_status"], "UNTESTED_PROPOSAL")
            self.assertEqual(document.test_protocol["performance_status"], "NOT_EVALUATED")
            self.assertEqual(document.implementation_status, "SPECIFICATION_ONLY_NO_INTENTS")
            self.assertEqual(document.preregistration_claim, "SPECIFICATION_FREEZE_ONLY_NOT_HISTORICAL_PREREGISTRATION")

    def test_separate_documents_are_immutable_and_bound_to_catalog_content(self):
        catalog = self.catalog(); documents = catalog_documents(catalog)
        self.assertIsInstance(documents, tuple)
        self.assertEqual([document.to_dict() for document in documents], catalog.hypotheses)
        original = documents[0].to_bytes(); documents[0].signal.clear()
        self.assertEqual(documents[0].to_bytes(), original)
        self.assertTrue(all(isinstance(row, TradingHypothesis) for row in documents))

    def test_catalog_import_revalidates_and_does_not_preserve_mutable_input(self):
        value = self.catalog().to_dict(); imported = validate_hypothesis_catalog(value)
        value["hypotheses"].clear()
        self.assertEqual(len(imported.hypotheses), 2)
        clone = validate_hypothesis_catalog(imported)
        self.assertIsInstance(clone, TradingHypothesisCatalog)
        self.assertIsNot(clone, imported)
        self.assertEqual(clone.to_bytes(), imported.to_bytes())

    def test_catalog_import_rejects_selection_claim_and_legacy_fields(self):
        for field, value in (("selection_policy", "WINNER_SELECTED"), ("galactica_rules", {})):
            mapping = self.catalog().to_dict(); mapping[field] = value
            with self.subTest(field=field), self.assertRaises(ContractValidationError):
                validate_hypothesis_catalog(mapping)

    def test_descriptive_adapter_is_compatible_with_existing_offline_plan(self):
        for hypothesis in catalog_documents(self.catalog()):
            plan = plan_mapping(); plan.update(hypothesis_research_strategy(hypothesis))
            validated = TradingResearchPlan.from_mapping(plan)
            self.assertEqual(validated.strategy["strategy_id"], hypothesis.hypothesis_id)
            self.assertEqual(validated.horizon["max_holding_sessions"], hypothesis.horizon["holding_sessions"])
            self.assertEqual(validated.strategy["implementation_status"], "EXTERNAL_INTENTS_ONLY")
            self.assertFalse(any(validated.authority.values()))

    def test_adapter_has_no_decisions_orders_budget_or_forecasts(self):
        for document in catalog_documents(self.catalog()):
            mapping = hypothesis_research_strategy(document)
            self.assertEqual(set(mapping), {"strategy", "horizon"})
            self.assertIn("no edge has been measured", mapping["strategy"]["expected_edge"])
            for forbidden in ("intents", "decisions", "orders", "budget", "qty", "forecast", "investment_authorization"):
                self.assertNotIn(forbidden, mapping)

    def test_adapter_validates_imported_hypothesis_instead_of_trusting_ancestry(self):
        value = catalog_documents(self.catalog())[0].to_dict(); value["ancestry"] = "GALACTICA"
        with self.assertRaises(ContractValidationError): hypothesis_research_strategy(value)

    def test_adapter_output_mutation_does_not_change_hypothesis(self):
        hypothesis = catalog_documents(self.catalog())[0]; original = hypothesis.to_bytes()
        mapping = hypothesis_research_strategy(hypothesis)
        mapping["strategy"]["falsification_conditions"].clear()
        mapping["horizon"]["max_holding_sessions"] = 10
        self.assertEqual(hypothesis.to_bytes(), original)
        self.assertNotEqual(mapping, hypothesis_research_strategy(hypothesis))

    def test_every_authority_boundary_is_disabled_and_investment_desk_has_no_role(self):
        catalog = self.catalog()
        self.assertEqual(catalog.domain, "TRADING")
        self.assertFalse(catalog.auto_trading_enabled)
        self.assertFalse(any(catalog.authority.values()))
        for hypothesis in catalog_documents(catalog):
            self.assertEqual(hypothesis.scope, "RESEARCH_ONLY")
            self.assertFalse(any(hypothesis.authority.values()))
            self.assertFalse(hypothesis.auto_trading_enabled)
            self.assertEqual(hypothesis.exposure_policy["capital_status"], "NO_DESK_BUDGET_OR_OWNERSHIP_ACTIVATION")

    def test_source_bound_costs_and_unimplemented_control_prevent_performance_claim(self):
        for hypothesis in catalog_documents(self.catalog()):
            protocol = hypothesis.test_protocol
            self.assertEqual(protocol["benchmarks"][1]["status"], "DECLARED_NOT_IMPLEMENTED")
            self.assertEqual(protocol["missing_evidence_policy"], "INCONCLUSIVE")
            self.assertEqual(protocol["cost_policy"], "SOURCE_BOUND_SPREAD_SLIPPAGE_AND_FEES_BEFORE_DECISION_GENERATION")
            self.assertEqual(protocol["cost_stress_multipliers"], ["1", "2", "4"])

    def test_catalog_export_and_adapter_make_no_io_provider_or_worker_calls(self):
        def forbidden(*args, **kwargs):
            raise AssertionError("pure specification export attempted external I/O")
        with patch("builtins.open", side_effect=forbidden), patch("socket.create_connection", side_effect=forbidden), \
                patch("subprocess.Popen", side_effect=forbidden):
            catalog = self.catalog()
            for document in catalog_documents(catalog): hypothesis_research_strategy(document)


if __name__ == "__main__":
    unittest.main()
