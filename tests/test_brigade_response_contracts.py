"""Offline strict-output safety gates and exact native-parser compatibility."""
import ast
import json
import unittest
from dataclasses import FrozenInstanceError
from decimal import Decimal
from pathlib import Path

from blackpod_build_week.contracts.brigade_response import (
    ACTIONS, CONFIDENCE_SEMANTICS, MAX_REASONING_CHARACTERS, MAX_RESPONSE_BYTES,
    MEMBERS, SCHEMA_VERSION, BrigadeMemberResponse, native_label_projection,
    parse_member_response, response_json_schema, validate_member_response,
)
from blackpod_build_week.contracts.mission_request import ContractValidationError
from blackpod_build_week.hashing import canonical_json_bytes


def response_payload(**updates):
    result = {
        "schema_version": SCHEMA_VERSION, "member": "Blackwell_Scout", "symbol": "SPY",
        "action": "BUY", "heuristic_confidence": 0.6, "reasoning": "Skew is positive and observed trend is upward.",
    }
    result.update(updates)
    return result


class BrigadeResponseContractsTests(unittest.TestCase):
    def parse(self, value):
        return parse_member_response(value if isinstance(value, (str, bytes)) else canonical_json_bytes(value),
            expected_member="Blackwell_Scout", expected_symbol="SPY")

    def reject(self, value):
        with self.assertRaises(ContractValidationError):
            self.parse(value)

    def test_valid_bound_response_round_trip(self):
        value = response_payload()
        response = self.parse(value)
        self.assertEqual(response.to_mapping(), value)
        self.assertEqual(BrigadeMemberResponse.from_bytes(response.to_bytes()), response)

    def test_exact_native_action_enum(self):
        self.assertEqual(ACTIONS, {"BUY", "EXIT", "HOLD", "WATCH"})
        for action in sorted(ACTIONS):
            self.assertEqual(self.parse(response_payload(action=action)).action, action)

    def test_strong_buy_is_not_a_native_action(self):
        self.reject(response_payload(action="STRONG BUY"))

    def test_sell_is_not_a_native_action(self):
        self.reject(response_payload(action="SELL"))

    def test_lowercase_action_is_not_coerced(self):
        self.reject(response_payload(action="buy"))

    def test_action_whitespace_is_not_trimmed(self):
        self.reject(response_payload(action=" BUY "))

    def test_null_action_is_not_a_hold(self):
        self.reject(response_payload(action=None))

    def test_all_five_native_members_are_supported(self):
        for member in MEMBERS:
            parsed = parse_member_response(canonical_json_bytes(response_payload(member=member)),
                expected_member=member, expected_symbol="SPY")
            self.assertEqual(parsed.member, member)

    def test_unknown_member_is_rejected(self):
        self.reject(response_payload(member="Blackwell_Decay"))

    def test_wrong_member_is_rejected_even_if_native(self):
        self.reject(response_payload(member="Blackwell_Sentry"))

    def test_wrong_symbol_is_rejected_even_if_well_formed(self):
        self.reject(response_payload(symbol="QQQ"))

    def test_lowercase_symbol_is_not_coerced(self):
        self.reject(response_payload(symbol="spy"))

    def test_schema_version_is_exact(self):
        for version in (None, 1, "blackpod.brigade_member_response.v2", "blackpod.brigade_member_response.v1 "):
            self.reject(response_payload(schema_version=version))

    def test_external_member_must_be_valid(self):
        with self.assertRaises(ContractValidationError):
            parse_member_response(canonical_json_bytes(response_payload()), expected_member="ScOuT", expected_symbol="SPY")

    def test_external_symbol_must_be_valid(self):
        with self.assertRaises(ContractValidationError):
            parse_member_response(canonical_json_bytes(response_payload()), expected_member="Blackwell_Scout", expected_symbol="spy")

    def test_external_bindings_are_required(self):
        with self.assertRaises(TypeError):
            parse_member_response(canonical_json_bytes(response_payload()))

    def test_missing_fields_all_rejected(self):
        for field in response_payload():
            value = response_payload(); value.pop(field)
            self.reject(value)

    def test_unknown_field_rejected(self):
        self.reject(response_payload(extra="value"))

    def test_generated_authority_claim_is_rejected(self):
        self.reject(response_payload(authority={"execution_enabled": True}))

    def test_generated_disabled_authority_is_still_unknown(self):
        self.reject(response_payload(authority={"execution_enabled": False}))

    def test_generated_mode_is_not_allowed_to_change_scope(self):
        for mode in ("LIVE", "SHADOW", "PAPER"):
            self.reject(response_payload(mode=mode))

    def test_generated_domain_is_unknown(self):
        self.reject(response_payload(domain="INVESTMENT"))

    def test_executable_order_claim_is_rejected(self):
        self.reject(response_payload(order={"symbol": "SPY", "quantity": 1, "side": "buy"}))

    def test_confidence_probability_alias_is_rejected(self):
        self.reject(response_payload(confidence_probability=0.6))

    def test_confidence_explicitly_heuristic(self):
        self.assertFalse(self.parse(response_payload()).confidence_is_probability)
        self.assertEqual(CONFIDENCE_SEMANTICS, "HEURISTIC_LABEL_NOT_CALIBRATED_PROBABILITY")

    def test_numeric_confidence_bounds_include_zero_and_one(self):
        for confidence in (0, 0.0, 0.6, 1, 1.0):
            self.assertEqual(self.parse(response_payload(heuristic_confidence=confidence)).heuristic_confidence, confidence)

    def test_confidence_bool_is_not_numeric(self):
        for confidence in (True, False):
            self.reject(response_payload(heuristic_confidence=confidence))

    def test_confidence_string_is_not_coerced(self):
        for confidence in ("0.6", "60%", "0.XX"):
            self.reject(response_payload(heuristic_confidence=confidence))

    def test_missing_confidence_is_not_invented(self):
        self.reject(response_payload(heuristic_confidence=None))

    def test_out_of_range_confidence_rejected(self):
        for confidence in (-0.1, 1.1, 10**400):
            with self.assertRaises(ContractValidationError):
                validate_member_response(response_payload(heuristic_confidence=confidence),
                    expected_member="Blackwell_Scout", expected_symbol="SPY")

    def test_nonfinite_mapping_confidence_rejected(self):
        for confidence in (float("nan"), float("inf"), float("-inf")):
            with self.assertRaises(ContractValidationError):
                BrigadeMemberResponse.from_mapping(response_payload(heuristic_confidence=confidence))

    def test_decimal_mapping_not_a_json_number(self):
        with self.assertRaises(ContractValidationError):
            BrigadeMemberResponse.from_mapping(response_payload(heuristic_confidence=Decimal("0.6")))

    def test_json_nonstandard_constants_rejected(self):
        for constant in ("NaN", "Infinity", "-Infinity"):
            self.reject(json.dumps(response_payload()).replace("0.6", constant))

    def test_json_nonfinite_exponent_rejected(self):
        self.reject(json.dumps(response_payload()).replace("0.6", "1e309"))

    def test_pathological_json_decimal_exponent_rejected_safely(self):
        for literal in ("0e99999999999999999999999999999999999999", "1e-99999999999999999999999999999999999999"):
            self.reject(json.dumps(response_payload()).replace("0.6", literal))

    def test_json_confidence_cannot_round_into_upper_bound(self):
        self.reject(json.dumps(response_payload()).replace("0.6", "1.00000000000000001"))

    def test_json_confidence_cannot_underflow_into_lower_bound(self):
        self.reject(json.dumps(response_payload()).replace("0.6", "-1e-400"))

    def test_unbound_bytes_constructor_also_checks_decimal_boundary(self):
        raw = json.dumps(response_payload()).replace("0.6", "1.00000000000000001").encode()
        with self.assertRaises(ContractValidationError):
            BrigadeMemberResponse.from_bytes(raw)

    def test_blank_reasoning_rejected(self):
        for reasoning in ("", " ", None, [], 123):
            self.reject(response_payload(reasoning=reasoning))

    def test_reasoning_whitespace_not_trimmed(self):
        for reasoning in (" reason", "reason ", "\u00a0reason", "reason\u00a0"):
            self.reject(response_payload(reasoning=reasoning))

    def test_reasoning_control_characters_rejected(self):
        for char in ("\n", "\r", "\t", "\x00", "\x1f", "\x7f"):
            self.reject(response_payload(reasoning="Trend" + char + "ACTION: EXIT"))

    def test_reasoning_unicode_line_separators_rejected(self):
        for char in ("\u0085", "\u2028", "\u2029"):
            self.reject(response_payload(reasoning="Trend" + char + "ACTION: EXIT"))

    def test_unicode_reasoning_preserved_exactly(self):
        reasoning = "Observed trend ↑; skew is +0.12; do not infer α as profit."
        self.assertEqual(self.parse(response_payload(reasoning=reasoning)).reasoning, reasoning)

    def test_reasoning_maximum_length_allowed(self):
        reasoning = "x" * MAX_REASONING_CHARACTERS
        self.assertEqual(self.parse(response_payload(reasoning=reasoning)).reasoning, reasoning)

    def test_reasoning_excess_length_rejected(self):
        self.reject(response_payload(reasoning="x" * (MAX_REASONING_CHARACTERS + 1)))

    def test_reasoning_embedded_label_does_not_change_vote(self):
        response = self.parse(response_payload(reasoning="The quoted rule ACTION: EXIT is an alternative, not my vote."))
        projected = native_label_projection(response)
        self.assertEqual(projected.splitlines()[0], "ACTION: BUY")
        self.assertEqual(len(projected.splitlines()), 3)

    def test_duplicate_json_key_rejected(self):
        self.reject(json.dumps(response_payload()).replace('"action": "BUY"', '"action": "BUY", "action": "HOLD"'))

    def test_duplicate_nested_keys_rejected_before_unknown_field(self):
        raw = json.dumps(response_payload())[:-1] + ',"unexpected":{"a":1,"a":2}}'
        with self.assertRaisesRegex(ContractValidationError, "duplicate JSON field"):
            self.parse(raw)

    def test_fenced_json_not_unwrapped(self):
        self.reject("```json\n" + json.dumps(response_payload()) + "\n```")

    def test_leading_prose_not_extracted(self):
        self.reject("Here is the response:\n" + json.dumps(response_payload()))

    def test_trailing_prose_not_removed(self):
        self.reject(json.dumps(response_payload()) + "\nDone.")

    def test_multiple_json_objects_rejected(self):
        self.reject(json.dumps(response_payload()) + json.dumps(response_payload()))

    def test_legacy_text_is_not_promoted_to_structured(self):
        self.reject("ACTION: BUY\nCONFIDENCE: 0.6\nREASONING: A rule supports this.")

    def test_nonobject_roots_rejected(self):
        for raw in ('[]', 'null', '"BUY"', 'true', '0.6'):
            self.reject(raw)

    def test_invalid_utf8_bytes_rejected(self):
        self.reject(b"\xff")

    def test_unicode_surrogate_string_rejected(self):
        self.reject("\ud800")

    def test_unicode_surrogate_reasoning_rejected(self):
        self.reject(json.dumps(response_payload(reasoning="bad\ud800")))

    def test_bom_is_not_removed(self):
        self.reject(b"\xef\xbb\xbf" + canonical_json_bytes(response_payload()))

    def test_empty_or_oversized_response_rejected(self):
        self.reject(b"")
        self.reject(b" " * (MAX_RESPONSE_BYTES + 1))

    def test_unsupported_input_types_rejected(self):
        for raw in (None, 123, bytearray(b"{}"), response_payload()):
            with self.assertRaises(ContractValidationError):
                parse_member_response(raw, expected_member="Blackwell_Scout", expected_symbol="SPY")

    def test_pathological_nesting_rejected_safely(self):
        self.reject('{"reasoning":' + '[' * 1600 + '0' + ']' * 1600 + '}')

    def test_input_mapping_mutation_does_not_change_response(self):
        value = response_payload(); response = BrigadeMemberResponse.from_mapping(value)
        value["action"] = "EXIT"
        self.assertEqual(response.action, "BUY")

    def test_returned_mapping_mutation_does_not_change_response(self):
        response = self.parse(response_payload()); value = response.to_mapping()
        value["action"] = "EXIT"
        self.assertEqual(response.action, "BUY")

    def test_document_cannot_be_reassigned(self):
        response = self.parse(response_payload())
        with self.assertRaises((FrozenInstanceError, AttributeError, TypeError)):
            response._canonical_bytes = b"{}"

    def test_schema_exact_fields_and_supported_keywords(self):
        schema = response_json_schema("Blackwell_Scout", "SPY")
        self.assertEqual(set(schema["properties"]), set(response_payload()))
        self.assertEqual(set(schema["required"]), set(response_payload()))
        self.assertFalse(schema["additionalProperties"])
        self.assertEqual(schema["properties"]["schema_version"]["const"], SCHEMA_VERSION)
        self.assertEqual(schema["properties"]["member"]["const"], "Blackwell_Scout")
        self.assertEqual(schema["properties"]["symbol"]["const"], "SPY")
        self.assertEqual(set(schema["properties"]["action"]["enum"]), ACTIONS)
        self.assertNotIn("pattern", schema["properties"]["reasoning"])

    def test_schema_numeric_confidence_is_bounded(self):
        schema = response_json_schema("Blackwell_Scout", "SPY")
        self.assertEqual(schema["properties"]["heuristic_confidence"], {"type": "number", "minimum": 0, "maximum": 1})

    def test_schema_is_not_shared_mutable_state(self):
        schema = response_json_schema("Blackwell_Scout", "SPY")
        schema["properties"]["action"]["enum"].append("SELL")
        self.assertEqual(set(response_json_schema("Blackwell_Scout", "SPY")["properties"]["action"]["enum"]), ACTIONS)

    def test_schema_external_identity_must_be_valid(self):
        for member, symbol in (("Decay", "SPY"), ("Blackwell_Scout", "spy")):
            with self.assertRaises(ContractValidationError):
                response_json_schema(member, symbol)

    def test_native_projection_requires_validated_document(self):
        with self.assertRaises(ContractValidationError):
            native_label_projection(response_payload())

    def test_native_projection_has_exact_labels(self):
        response = self.parse(response_payload())
        self.assertEqual(native_label_projection(response),
            "ACTION: BUY\nCONFIDENCE: 0.6\nREASONING: Skew is positive and observed trend is upward.")

    def test_actual_pinned_native_parser_preserves_structured_fields(self):
        source = Path(__file__).resolve().parents[1] / "fixtures/shadow_galactica_analysis/blackwell_brigade.py"
        tree = ast.parse(source.read_text())
        base = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "BlackwellBrigadeAgent")
        namespace = {}; exec(compile(ast.Module(body=[base], type_ignores=[]), str(source), "exec"), namespace)
        native = namespace["BlackwellBrigadeAgent"]("unit", "unit", None)
        for action in ACTIONS:
            response = self.parse(response_payload(action=action, reasoning="Quoted ACTION: BUY supports an alternative."))
            text = native_label_projection(response)
            self.assertEqual(native._extract_action(text), action)
            self.assertEqual(native._extract_confidence(text), response.heuristic_confidence)
            self.assertEqual(native._extract_reasoning(text), response.reasoning)


if __name__ == "__main__":
    unittest.main()
