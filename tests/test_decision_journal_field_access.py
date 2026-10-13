"""Canonical equivalence, defensive copies and bounded single-field parsing."""
import copy
from dataclasses import FrozenInstanceError
import json
import pickle
import unittest
from unittest.mock import patch

from blackpod_build_week.contracts.decision_journal import _ImmutableDocument, _object
from blackpod_build_week.hashing import canonical_json_bytes


class SampleDocument(_ImmutableDocument):
    __slots__ = ()
    _validator = staticmethod(lambda value: _object(value,
        {"identifier", "nested", "flag", "number", "fraction", "nothing", "text"}, "sample"))


class CanonicalFieldAccessTests(unittest.TestCase):
    def setUp(self):
        self.mapping = {"identifier": "sample-document", "nested": [{"value": [1, 2, {"label": "preserved"}]}] * 1000,
            "flag": False, "number": 3, "fraction": 0.125, "nothing": None,
            "text": "Unicode Ω, escaped quote \" and newline\nremain canonical."}
        self.document = SampleDocument.from_mapping(self.mapping)

    def test_every_field_matches_original_canonical_document_decoding(self):
        decoded = json.loads(self.document.to_bytes())
        for name in decoded:
            with self.subTest(name=name):
                self.assertEqual(getattr(self.document, name), decoded[name])
                self.assertIs(type(getattr(self.document, name)), type(decoded[name]))

    def test_single_scalar_access_never_parses_the_large_full_document(self):
        with patch("blackpod_build_week.contracts.decision_journal.json.loads", wraps=json.loads) as parsed:
            self.assertEqual(self.document.identifier, "sample-document")
        self.assertEqual(parsed.call_count, 1)
        self.assertEqual(parsed.call_args.args[0], canonical_json_bytes("sample-document"))
        self.assertLess(len(parsed.call_args.args[0]), len(self.document.to_bytes()) // 100)

    def test_nested_field_mutation_cannot_change_original_or_later_access(self):
        original = self.document.to_bytes()
        field = self.document.nested
        field[0]["value"][2]["label"] = "changed"
        field.append({"new": True})
        self.assertEqual(self.document.nested, self.mapping["nested"])
        self.assertEqual(self.document.to_bytes(), original)

    def test_repeated_access_returns_independent_builtin_lists_and_dicts(self):
        left, right = self.document.nested, self.document.nested
        self.assertIs(type(left), list)
        self.assertIs(type(left[0]), dict)
        self.assertIsNot(left, right)
        self.assertIsNot(left[0], right[0])
        left.pop()
        self.assertEqual(len(right), 1000)

    def test_mutating_input_after_validation_cannot_change_cached_fields(self):
        original = self.document.to_bytes()
        self.mapping["identifier"] = "changed"
        self.mapping["nested"][0]["value"].append("changed")
        self.assertEqual(self.document.identifier, "sample-document")
        self.assertEqual(self.document.to_bytes(), original)
        self.assertEqual(self.document.nested, json.loads(original)["nested"])

    def test_to_dict_and_to_mapping_remain_fresh_full_defensive_copies(self):
        original = self.document.to_bytes()
        for method in (self.document.to_dict, self.document.to_mapping):
            value = method()
            value["nested"].clear()
            self.assertEqual(self.document.to_bytes(), original)
            self.assertEqual(len(self.document.nested), 1000)

    def test_canonical_bytes_and_roundtrip_are_exactly_unchanged(self):
        expected = canonical_json_bytes(self.mapping)
        self.assertEqual(self.document.to_bytes(), expected)
        self.assertEqual(SampleDocument.from_bytes(expected).to_bytes(), expected)

    def test_equality_and_hash_remain_based_on_canonical_document(self):
        other = SampleDocument.from_bytes(self.document.to_bytes())
        self.assertEqual(self.document, other)
        self.assertEqual(hash(self.document), hash(other))
        changed = self.mapping.copy()
        changed["identifier"] = "different"
        self.assertNotEqual(self.document, SampleDocument.from_mapping(changed))

    def test_cache_cannot_be_mutated_or_assigned_through_public_access(self):
        self.assertIs(type(self.document._canonical_fields), tuple)
        self.assertTrue(all(type(name) is str and type(raw) is bytes for name, raw in self.document._canonical_fields))
        with self.assertRaises((FrozenInstanceError, AttributeError, TypeError)):
            self.document._canonical_fields = ()
        with self.assertRaises(TypeError):
            self.document._canonical_fields[0] = ("changed", b"null")

    def test_pickle_and_deepcopy_preserve_immutable_public_behavior(self):
        for restored in (pickle.loads(pickle.dumps(self.document)), copy.deepcopy(self.document)):
            self.assertEqual(restored.to_bytes(), self.document.to_bytes())
            self.assertEqual(restored.nested, self.document.nested)
            restored.nested.clear()
            self.assertEqual(len(self.document.nested), 1000)

    def test_unknown_or_internal_missing_attribute_still_raises(self):
        for name in ("unknown", "_missing_private"):
            with self.subTest(name=name), self.assertRaises(AttributeError):
                getattr(self.document, name)

    def test_pre_cache_pickle_state_rebuilds_fields_without_changing_bytes(self):
        restored = object.__new__(SampleDocument)
        restored.__setstate__([self.document.to_bytes()])
        self.assertEqual(restored.identifier, self.document.identifier)
        self.assertEqual(restored.nested, self.document.nested)
        self.assertEqual(restored.to_bytes(), self.document.to_bytes())
        self.assertEqual(hash(restored), hash(self.document))
        copy_of_field = restored.nested
        copy_of_field.clear()
        self.assertEqual(len(restored.nested), 1000)

    def test_legacy_state_can_immediately_be_repickled_or_deepcopied(self):
        restored = object.__new__(SampleDocument)
        restored.__setstate__([self.document.to_bytes()])
        # No public field is accessed before these operations.
        repickled, copied = pickle.loads(pickle.dumps(restored)), copy.deepcopy(restored)
        self.assertEqual(restored.__getstate__(), [self.document.to_bytes()])
        for value in (repickled, copied):
            self.assertEqual(value.to_bytes(), self.document.to_bytes())
            self.assertEqual(value.nested, self.document.nested)
