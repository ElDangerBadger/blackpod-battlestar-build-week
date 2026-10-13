from __future__ import annotations

import json
import unittest
from pathlib import Path

from blackpod_build_week.contracts.decision_journal import JournalEvent
from blackpod_build_week.contracts.investment_hypothesis import InvestmentHypothesis
from blackpod_build_week.decision_journal_projection import load_verified_history, project_history
from blackpod_build_week.hashing import canonical_json_bytes, sha256_bytes
from blackpod_build_week.investment_hypothesis import (
    HypothesisEvidenceError, _same_scalar, build_hypothesis_event,
    evidence_for_hypothesis, resolve_source_pointer, validate_hypothesis_event,
    validate_hypothesis_sources,
)


CHECKOUT = Path(__file__).resolve().parents[1]


class InvestmentHypothesisSourceTests(unittest.TestCase):
    def setUp(self):
        self.draft = json.loads((CHECKOUT / "examples/investment_hypothesis.shadow.v1.json").read_bytes())
        history = load_verified_history(CHECKOUT / "fixtures/investment_hypothesis/missions/mission-investment-hypothesis-example")
        self.events = project_history(history)
        self.blobs = {sha256_bytes(raw): raw for raw in history.source_files.values()}

    def hypothesis(self):
        return InvestmentHypothesis.from_mapping(self.draft)

    def test_source_bound_event_is_pure_deterministic_and_separately_owned(self):
        first = build_hypothesis_event(self.hypothesis(), self.events, self.blobs)
        second = build_hypothesis_event(self.hypothesis(), self.events, self.blobs)
        self.assertEqual(first.to_bytes(), second.to_bytes())
        self.assertEqual(first.schema_version, "blackpod.decision_journal_event.v2")
        self.assertEqual(first.domain, "INVESTMENT")
        self.assertTrue(all(event.domain == "UNCLASSIFIED" for event in self.events))
        self.assertNotEqual(first.decision_id, self.events[-1].decision_id)
        self.assertTrue(all(not flag for flag in first.payload["authority"].values()))
        evidence = evidence_for_hypothesis(self.hypothesis(), self.events, self.blobs)
        self.assertEqual(len(evidence), 2)  # Two observations share one source blob.
        validate_hypothesis_event(first, self.events,
                                  {**self.blobs, **{sha256_bytes(raw): raw for raw in evidence.values()}})

    def test_wrong_observed_scalar_is_rejected(self):
        self.draft["observations"][0]["value"] = 99
        with self.assertRaisesRegex(HypothesisEvidenceError, "value differs"):
            validate_hypothesis_sources(self.hypothesis(), self.events, self.blobs)

    def test_missing_mismatched_or_changed_evidence_is_rejected(self):
        digest = self.draft["observations"][0]["artifact_sha256"]
        for blobs in ({}, {**self.blobs, digest: b"changed evidence"}):
            with self.subTest(blobs=bool(blobs)), self.assertRaises(HypothesisEvidenceError):
                validate_hypothesis_sources(self.hypothesis(), self.events, blobs)
        self.draft["observations"][0]["artifact_sha256"] = "f" * 64
        with self.assertRaisesRegex(HypothesisEvidenceError, "does not match"):
            validate_hypothesis_sources(self.hypothesis(), self.events, self.blobs)

    def test_artifact_and_source_event_must_exist_in_preceding_history(self):
        for field, bad in (("artifact_path", "research/missing.json"),
                           ("source_event_id", "journal-event-" + "f" * 64)):
            original = self.draft["observations"][0][field]
            self.draft["observations"][0][field] = bad
            with self.subTest(field=field), self.assertRaises(HypothesisEvidenceError):
                validate_hypothesis_sources(self.hypothesis(), self.events, self.blobs)
            self.draft["observations"][0][field] = original

    def test_missing_pointer_and_scalar_traversal_rejected(self):
        for pointer in ("/metrics/not_present", "/metrics/revenue_growth_pct/child", ""):
            self.draft["observations"][0]["value_pointer"] = pointer
            with self.subTest(pointer=pointer), self.assertRaises(HypothesisEvidenceError):
                validate_hypothesis_sources(self.hypothesis(), self.events, self.blobs)

    def test_timestamp_must_match_exact_source_and_role(self):
        self.draft["observations"][0]["as_of"] = "2026-10-10T00:00:00Z"
        with self.assertRaisesRegex(HypothesisEvidenceError, "as_of differs"):
            validate_hypothesis_sources(self.hypothesis(), self.events, self.blobs)
        self.draft["observations"][0]["as_of"] = "2026-10-11T00:00:00Z"
        self.draft["observations"][0]["time_role"] = "GENERATED_AT"
        with self.assertRaisesRegex(HypothesisEvidenceError, "time role"):
            validate_hypothesis_sources(self.hypothesis(), self.events, self.blobs)

    def test_source_event_after_cutoff_is_rejected(self):
        late = self.events[-1].to_dict()
        late["recorded_at"] = "2026-10-12T00:00:00Z"
        with self.assertRaisesRegex(HypothesisEvidenceError, "after the evidence cutoff"):
            validate_hypothesis_sources(self.hypothesis(), (*self.events[:-1], JournalEvent.from_mapping(late)), self.blobs)

    def test_duplicate_source_identity_is_ambiguous(self):
        with self.assertRaisesRegex(HypothesisEvidenceError, "ambiguous"):
            validate_hypothesis_sources(self.hypothesis(), (*self.events, self.events[-1]), self.blobs)

    def test_pointer_resolution_preserves_escaped_keys_and_exact_array_indices(self):
        source = {"a/b": {"~key": [None, {"": True}]}}
        self.assertIs(resolve_source_pointer(source, "/a~1b/~0key/1/"), True)
        self.assertIs(resolve_source_pointer(source, ""), source)
        for pointer in ("#fragment", "/a~2b", "/a~1b/~0key/01", "/a~1b/~0key/-",
                        "/a~1b/~0key/2", "/a~1b/~0key/" + "9" * 5000):
            with self.subTest(pointer=pointer[:100]), self.assertRaises(HypothesisEvidenceError):
                resolve_source_pointer(source, pointer)

    def test_numeric_equality_never_treats_boolean_as_probability(self):
        self.assertFalse(_same_scalar(True, 1))
        self.assertFalse(_same_scalar(0, False))
        self.assertFalse(_same_scalar(float("nan"), float("nan")))
        self.assertTrue(_same_scalar(5, 5.0))
        self.assertTrue(_same_scalar(None, None))
        self.assertFalse(_same_scalar({}, {}))

    def test_deep_retained_json_fails_cleanly(self):
        # Model a syntactically linked source blob at the pure validator boundary.
        # Actual JournalStore also verifies its canonical mission lineage.
        raw = b'{"metrics":' + b'[' * 2000 + b'0' + b']' * 2000 + b'}'
        digest = sha256_bytes(raw)
        previous = self.events[-1].to_dict()
        path = self.draft["observations"][0]["artifact_path"]
        for ref in previous["evidence"]:
            if ref["path"] == path:
                ref.update(sha256=digest, size_bytes=len(raw))
        for observation in self.draft["observations"]:
            observation["artifact_sha256"] = digest
        with self.assertRaisesRegex(HypothesisEvidenceError, "strict retained JSON"):
            validate_hypothesis_sources(self.hypothesis(),
                                        (*self.events[:-1], JournalEvent.from_mapping(previous)),
                                        {**self.blobs, digest: raw})


if __name__ == "__main__":
    unittest.main()
