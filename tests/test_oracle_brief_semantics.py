"""Finite semantic regression cases, never market forecasts or real inference."""
from __future__ import annotations

import copy
import json
import os
import unittest

from blackpod_build_week.narrative_diagnostics import (
    CanonicalBriefValidationError, narrative_validation_message,
)
from blackpod_build_week.oracle_brief_reader import validate_brief_semantics
from blackpod_build_week.oracle_market_brief import (
    ATTEMPT_PATH, BRIEF_PATH, OracleMarketBriefError,
)
import test_oracle_market_brief as producer
from test_oracle_brief_reader import rehash


def evidence():
    values = {
        "oracle.measurements.breadth_score": 0.75,
        "oracle.measurements.defensive_strength": 0.7,
        "oracle.measurements.cyclical_strength": 0.3,
        "oracle.assessment.breadth_posture": "EXPANDING_BREADTH",
    }
    return {"facts": [{"fact_id": key, "value": value} for key, value in values.items()],
            "warnings": ["MISSING_PRIOR_ORACLE_MEASUREMENTS"]}


class OracleBriefSemanticTests(unittest.TestCase):
    def check(self, text, *, other=None, source=None):
        report = producer.synthetic_draft()
        report["headline"]["text"] = text
        if other:
            report["sections"][0]["paragraphs"][0]["text"] = other
        return validate_brief_semantics(report, evidence() if source is None else source)

    def rejects(self, text, rule, **kwargs):
        with self.assertRaisesRegex(ValueError, "^Oracle brief semantic check failed: " + rule + "$"):
            self.check(text, **kwargs)

    def test_supported_participation_and_group_relation_preserve_prose(self):
        report = self.check("Most supplied proxies are positive.",
                            other="Defensive group is stronger than the cyclical group.")
        self.assertEqual(report["headline"]["text"], "Most supplied proxies are positive.")

    def test_equal_and_boundary_participation_do_not_become_a_majority(self):
        for value in (0, 0.5):
            with self.subTest(value=value):
                source = evidence()
                source["facts"][0]["value"] = value
                self.rejects("Most measured proxies are positive.",
                             "contradictory_participation_direction", source=source)

    def test_all_and_no_positive_participation_use_exact_boundaries(self):
        for value, allowed, denied in (
            (1, "All supplied proxies are positive.", "No supplied proxies are positive."),
            (0, "No supplied proxies are positive.", "All supplied proxies are positive."),
        ):
            with self.subTest(value=value):
                source = evidence()
                source["facts"][0]["value"] = value
                self.check(allowed, source=source)
                self.rejects(denied, "contradictory_participation_direction", source=source)

    def test_reversed_breadth_posture_rejects(self):
        self.rejects("Breadth is contracting.", "contradictory_breadth_posture")
        self.check("Breadth is expanding.")

    def test_positive_fraction_does_not_supply_negative_count(self):
        self.rejects("Most measured proxies are negative.", "unsupported_negative_participation_count")

    def test_aggregate_price_direction_is_not_inferred_from_breadth(self):
        for direction in ("rising", "falling"):
            with self.subTest(direction=direction):
                self.rejects("The market is " + direction + ".", "unsupported_aggregate_price_direction")

    def test_reversed_group_relationship_rejects(self):
        for text in ("Cyclical outperforms defensive.", "Defensive group is weaker than cyclical group."):
            with self.subTest(text=text):
                self.rejects(text, "contradictory_group_relationship")

    def test_equal_group_scores_support_neither_direction(self):
        source = evidence()
        source["facts"][2]["value"] = 0.7
        for text in ("Cyclical leads defensive.", "Defensive leads cyclical."):
            with self.subTest(text=text):
                self.rejects(text, "contradictory_group_relationship", source=source)

    def test_individually_plausible_opposing_paragraphs_cannot_both_pass(self):
        self.rejects("Defensive is stronger than cyclical.", "contradictory_group_relationship",
                     other="Cyclical is stronger than defensive.")

    def test_named_sector_leadership_is_not_aggregate_group_evidence(self):
        for text in ("Technology is leading.", "Energy stocks are underperforming.",
                     "Financials are strongest."):
            with self.subTest(text=text):
                self.rejects(text, "unsupported_named_sector_leadership")

    def test_uncited_moving_average_relationship_is_unavailable_in_this_catalog(self):
        for text in ("Price is above the moving average.", "Prices crossed below the EMA."):
            with self.subTest(text=text):
                self.rejects(text, "unsupported_moving_average_relationship")

    def test_unsupported_causal_conclusion_rejects(self):
        for text in ("The rally was driven by falling rates.",
                     "Participation is broad due to investor optimism."):
            with self.subTest(text=text):
                self.rejects(text, "unsupported_causality")

    def test_forward_certainty_cannot_pass_as_observation(self):
        for text in ("The market will rally.", "Defensive sectors are expected to outperform.",
                     "Breadth is poised to improve."):
            with self.subTest(text=text):
                self.rejects(text, "unsupported_forward_prediction")

    def test_missing_prior_does_not_become_stability_or_improvement(self):
        for text in ("Rotation remains unchanged.", "Breadth has improved."):
            with self.subTest(text=text):
                self.rejects(text, "unsupported_temporal_comparison")

    def test_explicit_missing_evidence_and_uncertainty_remain_allowed(self):
        self.check("Moving-average relationships are unavailable in this evidence.",
                   other="Named-sector leadership is unknown; prior comparison is unavailable.")

    def test_missing_evidence_can_explain_uncertainty_without_claiming_market_causation(self):
        for text in ("No causal conclusion is possible because of missing evidence.",
                     "Market direction is uncertain due to missing prior measurements."):
            with self.subTest(text=text):
                self.check(text)

    def test_recorded_stable_breadth_is_not_a_temporal_stability_claim(self):
        source = evidence()
        source["facts"][3]["value"] = "STABLE_BREADTH"
        self.check("Breadth is stable.", source=source)

    def test_conditional_scenario_is_not_a_claim_of_future_outcome(self):
        self.check("If participation broadens, the structure could become less concentrated.")

    def test_explicit_counter_scenario_is_distinct_from_a_snapshot_assertion(self):
        self.check("If breadth is contracting, a different interpretation would be needed.")
        self.rejects("If breadth is contracting, a different interpretation would be needed. "
                     "Cyclical is stronger than defensive.", "contradictory_group_relationship")

    def test_explanatory_narrative_is_preserved_instead_of_replaced_with_metrics(self):
        text = "Broad participation alongside stronger defensive ranks presents a mixed structure."
        self.check(text, other="This combination matters for interpreting the breadth of participation; its cause remains unknown.")

    def test_missing_and_boolean_relationship_values_cannot_support_direction(self):
        for value in (None, True, "0.75"):
            with self.subTest(value=value):
                source = evidence()
                source["facts"][0]["value"] = value
                self.rejects("Most supplied proxies are positive.", "missing_relationship_evidence", source=source)

    def test_diagnostics_retain_only_fixed_rule_and_aggregate_field(self):
        try:
            self.check("Cyclical is stronger than defensive.")
        except ValueError as error:
            message = narrative_validation_message(CanonicalBriefValidationError(error))
        self.assertEqual(message, "ModelDock narrative failed its versioned contract validation "
                         "(rule=contradictory_group_relationship; field=brief_text).")


@unittest.skipUnless(os.environ.get("BATTLESTAR_PATH"), "set BATTLESTAR_PATH for canonical offline integration")
class OracleBriefSemanticDeliveryTests(unittest.TestCase):
    def setUp(self):
        self.fixture = producer.OracleMarketBriefTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.tearDown)

    def test_semantic_failure_never_publishes_and_keeps_durable_no_retry(self):
        draft = producer.synthetic_draft()
        draft["headline"]["text"] = "Cyclical is stronger than defensive."
        transport = producer.BriefTransport(draft=draft)
        with self.assertRaisesRegex(OracleMarketBriefError, "narrative_schema_invalid"):
            self.fixture.invoke(transport)
        self.assertEqual(transport.generations, 1)
        self.assertFalse((self.fixture.root / BRIEF_PATH).exists())
        failure = json.loads((self.fixture.root / ATTEMPT_PATH / "failure.json").read_bytes())
        self.assertIn("rule=contradictory_group_relationship", failure["modeldock_failure"]["message"])
        self.assertNotIn("Cyclical", json.dumps(failure))
        second = producer.BriefTransport()
        with self.assertRaisesRegex(OracleMarketBriefError, "already reserved"):
            self.fixture.invoke(second)
        self.assertEqual(second.requests, [])
        self.fixture.assert_original_unchanged()

    def test_existing_rehashed_contradiction_is_rejected_without_inference(self):
        result, _ = self.fixture.invoke()
        brief = copy.deepcopy(result.brief)
        brief["report"]["headline"]["text"] = "Cyclical is stronger than defensive."
        from blackpod_build_week.hashing import canonical_json_bytes
        before = canonical_json_bytes(rehash(brief))
        (self.fixture.root / BRIEF_PATH).write_bytes(before)
        second = producer.BriefTransport()
        with self.assertRaisesRegex(OracleMarketBriefError, "refusing overwrite"):
            self.fixture.invoke(second)
        self.assertEqual(second.requests, [])
        self.assertEqual((self.fixture.root / BRIEF_PATH).read_bytes(), before)

    def test_reader_rejects_rehashed_semantic_contradiction(self):
        result, _ = self.fixture.invoke()
        brief = copy.deepcopy(result.brief)
        brief["report"]["headline"]["text"] = "Cyclical is stronger than defensive."
        from blackpod_build_week.oracle_market_brief import load_mission_evidence
        from blackpod_build_week.oracle_brief_reader import SOURCE_NAMES, validate_brief_presentation
        from datetime import UTC, datetime
        sources = load_mission_evidence(self.fixture.loaded)
        with self.assertRaisesRegex(ValueError, "contradictory_group_relationship"):
            validate_brief_presentation(rehash(brief), mission_id=self.fixture.request.mission_id,
                request_id=self.fixture.request.request_id, symbol="AAPL",
                references={item.name: item for item in self.fixture.loaded.snapshot.artifacts if item.name in SOURCE_NAMES},
                documents={name: json.loads(item["payload"]) for name, item in sources.items()},
                now=datetime(2026, 7, 20, tzinfo=UTC))
