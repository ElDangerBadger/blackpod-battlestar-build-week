from __future__ import annotations

import unittest

from blackpod_build_week.contracts.mission_request import ContractValidationError
from blackpod_build_week.contracts.oracle_narrative import OracleNarrativeSelection
from blackpod_build_week.narrative_diagnostics import narrative_validation_message


class NarrativeDiagnosticTests(unittest.TestCase):
    def assert_diagnostic(self, error: Exception, rule: str, field: str) -> None:
        self.assertEqual(
            narrative_validation_message(error),
            "ModelDock narrative failed its versioned contract validation "
            f"(rule={rule}; field={field}).",
        )

    def test_known_schema_and_fact_rules_report_only_fixed_fields(self) -> None:
        cases = (
            ("Oracle narrative selection is missing fields: summary", "required_fields", "selection"),
            ("unsupported Oracle narrative selection schema_version: 'arbitrary-model-value'", "schema_version", "schema_version"),
            ("selected_fact_ids must be an array", "invalid_type", "selected_fact_ids"),
            ("selected_fact_ids must not be empty", "required_value", "selected_fact_ids"),
            ("selected_fact_ids[999] is not a canonical fact ID", "fact_id_format", "selected_fact_ids"),
            ("selected_fact_ids contains duplicates", "duplicate_values", "selected_fact_ids"),
            ("selected_fact_ids exceeds 5 entries", "size_limit", "selected_fact_ids"),
            ("prohibited_actions_acknowledged must be true", "safety_acknowledgement", "prohibited_actions_acknowledged"),
        )
        for message, rule, field in cases:
            with self.subTest(message=message):
                self.assert_diagnostic(ContractValidationError(message), rule, field)

    def test_known_text_rules_preserve_only_the_canonical_field(self) -> None:
        cases = (
            ("summary must be a string", "invalid_type", "summary"),
            ("interpretation must be nonblank", "required_value", "interpretation"),
            ("uncertainties[3] may not have surrounding whitespace", "surrounding_whitespace", "uncertainties"),
            ("confidence_explanation exceeds 2000 characters", "size_limit", "confidence_explanation"),
            ("summary contains unsupported control text", "control_text", "summary"),
            ("interpretation contains an absolute local path", "local_path", "interpretation"),
            ("Oracle narrative selection.summary contains credential- or secret-like text", "sensitive_text", "summary"),
        )
        for message, rule, field in cases:
            with self.subTest(message=message):
                self.assert_diagnostic(ContractValidationError(message), rule, field)

    def test_aggregate_rules_do_not_invent_a_specific_prose_field(self) -> None:
        self.assert_diagnostic(
            ContractValidationError("Oracle narrative contains vocabulary absent from the validated Oracle input: inventedword"),
            "source_vocabulary", "narrative_text",
        )
        self.assert_diagnostic(
            ContractValidationError("Oracle narrative contains a Governor disposition or approval claim"),
            "prohibited_authority", "narrative_text",
        )
        self.assert_diagnostic(
            ContractValidationError("Oracle narrative free text may not contain numeric claims; numbers must be source-linked observed facts"),
            "numeric_claim", "narrative_text",
        )

    def test_secret_paths_values_and_untrusted_field_names_never_escape(self) -> None:
        secret = "sk-proj-not-a-real-secret-value"
        path = "/Users/private/model-output"
        for message in (
            f"Oracle narrative selection contains unknown fields: {secret}, {path}",
            f"ModelDock selected an unknown Oracle fact ID: {secret!r}",
            f"Oracle narrative contains vocabulary absent from the validated Oracle input: {secret}, {path}",
            f"{path} contains credential- or secret-like text",
        ):
            with self.subTest(prefix=message.split(":")[0]):
                result = narrative_validation_message(ContractValidationError(message))
                self.assertNotIn(secret, result)
                self.assertNotIn(path, result)
                self.assertLess(len(result), 180)

    def test_unknown_or_custom_errors_are_not_echoed_or_formatted(self) -> None:
        class UnsafeFormattingError(ContractValidationError):
            def __str__(self):
                raise AssertionError("custom formatter must not be called")

        for error in (
            ValueError("summary must be nonblank"),
            ContractValidationError("arbitrary model-authored rejection /private/secret"),
            ContractValidationError({"secret": "not diagnostic data"}),
            UnsafeFormattingError("unrecognized reason"),
        ):
            with self.subTest(error_type=type(error).__name__):
                self.assert_diagnostic(error, "unclassified", "narrative")

    def test_real_selection_validator_remains_strict(self) -> None:
        value = {
            "schema_version": "blackpod.oracle_narrative_selection.v1",
            "selected_fact_ids": ["oracle.assessment.breadth_posture"],
            "summary": "Validated Oracle facts reflect contracting breadth.",
            "interpretation": "The source-linked facts suggest a bounded interpretation.",
            "uncertainties": [],
            "confidence_explanation": "Confidence is bounded by the source-linked facts.",
            "prohibited_actions_acknowledged": True,
        }
        for changed, rule, field in (
            ({"summary": None}, "invalid_type", "summary"),
            ({"selected_fact_ids": []}, "required_value", "selected_fact_ids"),
            ({"prohibited_actions_acknowledged": False}, "safety_acknowledgement", "prohibited_actions_acknowledged"),
            ({"untrusted-secret-field": True}, "unknown_fields", "selection"),
        ):
            with self.subTest(rule=rule):
                with self.assertRaises(ContractValidationError) as caught:
                    OracleNarrativeSelection.from_mapping({**value, **changed})
                self.assert_diagnostic(caught.exception, rule, field)


if __name__ == "__main__":
    unittest.main()
