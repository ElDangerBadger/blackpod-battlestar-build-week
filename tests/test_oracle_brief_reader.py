"""Read-only publication tests using a genuinely canonical synthetic receipt."""
from __future__ import annotations

import copy
from datetime import UTC, datetime
import hashlib
import json
import os
import unittest

from blackpod_build_week.cabin_reader import (
    CabinReader, MANIFEST_PATH, ReadOnlyMissionStore, capture_publication,
)
from blackpod_build_week.hashing import canonical_json_bytes, sha256_bytes
from blackpod_build_week.oracle_brief_reader import (
    BRIEF_PATH, SOURCE_NAMES, pointer_value, validate_brief_presentation,
)
from blackpod_build_week.oracle_market_brief import ATTEMPT_PATH, load_mission_evidence
import test_oracle_market_brief as producer_tests


def rehash(value):
    """Adversarial rehashing tests ensure a selfhash is not mistaken for trust."""
    for document, key, prefix in (
        (value["evidence"], "evidence_id", "oracle-brief-evidence-"),
        (value, "brief_id", "oracle-market-brief-"),
    ):
        body = {name: item for name, item in document.items() if name != key}
        raw = json.dumps(body, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
        document[key] = prefix + hashlib.sha256(raw).hexdigest()
    return value


class OracleBriefPointerTests(unittest.TestCase):
    def test_pointer_resolves_escaped_keys_and_array_values(self):
        self.assertEqual(pointer_value({"a/b": {"~key": [True]}}, "/a~1b/~0key/0"), True)

    def test_malformed_pointer_never_evaluates_or_accepts_negative_indexes(self):
        for pointer in ("", "x", "/x/-1", "/x/01", "/x/~2", "/x/0/z"):
            with self.subTest(pointer=pointer), self.assertRaises((ValueError, IndexError)):
                pointer_value({"x": [True]}, pointer)


@unittest.skipUnless(os.environ.get("BATTLESTAR_PATH"), "set BATTLESTAR_PATH for canonical brief integration")
class OracleBriefReaderTests(unittest.TestCase):
    def setUp(self):
        self.fixture = producer_tests.OracleMarketBriefTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.tearDown)
        self.result, transport = self.fixture.invoke()
        self.assertEqual(transport.generations, 1)  # Injected fixture, not HTTP.
        self.root = self.fixture.root
        sources = load_mission_evidence(self.fixture.loaded)
        self.references = {item.name: item for item in self.fixture.loaded.snapshot.artifacts if item.name in SOURCE_NAMES}
        self.documents = {name: json.loads(item["payload"]) for name, item in sources.items()}

    def validate(self, value=None, **kwargs):
        return validate_brief_presentation(
            self.result.brief if value is None else value,
            mission_id=self.fixture.request.mission_id, request_id=self.fixture.request.request_id,
            symbol="AAPL", references=self.references, documents=self.documents,
            now=kwargs.pop("now", datetime(2026, 7, 20, tzinfo=UTC)), **kwargs,
        )

    def file_state(self):
        return {path.relative_to(self.root): (path.read_bytes(), path.stat().st_mtime_ns)
            for path in self.root.rglob("*") if path.is_file()}

    def test_valid_receipt_is_returned_without_reinterpretation(self):
        self.assertEqual(self.validate(), self.result.brief)

    def test_rehashed_fact_tampering_and_json_type_substitution_are_rejected(self):
        for fact_id, substitute in (
            ("oracle.measurements.breadth_score", 0.1),
            ("oracle.readiness.freshness_ok", 1),
            ("oracle.diagnostics.symbols_used_count", 3.0),
        ):
            with self.subTest(fact_id=fact_id):
                value = copy.deepcopy(self.result.brief)
                fact = next(item for item in value["evidence"]["facts"] if item["fact_id"] == fact_id)
                fact["value"] = substitute
                with self.assertRaises(ValueError):
                    self.validate(rehash(value))

    def test_rehashed_source_reference_tampering_is_rejected(self):
        for field, replacement in (("sha256", "0" * 64), ("path", "oracle/unrelated.json"), ("producer", "modeldock")):
            with self.subTest(field=field):
                value = copy.deepcopy(self.result.brief)
                value["evidence"]["source_artifacts"]["oracle_measurements"][field] = replacement
                with self.assertRaises(ValueError):
                    self.validate(rehash(value))

    def test_wrong_correlation_and_replay_fail_even_with_new_hashes(self):
        for field, replacement in (("mission_id", "mission-other"), ("request_id", "request-other"), ("symbol", "SPY"), ("run_mode", "REPLAY")):
            with self.subTest(field=field):
                value = copy.deepcopy(self.result.brief)
                value["evidence"][field] = replacement
                with self.assertRaises(ValueError):
                    self.validate(rehash(value))

    def test_future_generated_and_invalid_inference_timeline_fail(self):
        for path, replacement in (
            (("generated_at",), "2026-07-21T00:00:00Z"),
            (("provenance", "observed_at"), "2026-07-20T00:00:00Z"),
            (("provenance", "started_at"), "2026-07-17T00:00:00Z"),
        ):
            with self.subTest(path=path):
                value = copy.deepcopy(self.result.brief)
                target = value
                for part in path[:-1]:
                    target = target[part]
                target[path[-1]] = replacement
                with self.assertRaises(ValueError):
                    self.validate(rehash(value))

    def test_source_captured_after_inference_start_is_rejected(self):
        value = copy.deepcopy(self.result.brief)
        value["provenance"]["started_at"] = value["evidence"]["as_of"]
        # The fixture's observation time equals as_of. Move both the supplied
        # reference and receipt reference later to test the timeline itself.
        from dataclasses import replace
        name = "oracle_measurements"
        self.references[name] = replace(self.references[name], observed_at="2026-07-18T19:00:00Z")
        value["evidence"]["source_artifacts"][name] = self.references[name].to_dict()
        with self.assertRaises(ValueError):
            self.validate(rehash(value))

    def test_safety_and_real_model_provenance_cannot_be_reclassified(self):
        for field, replacement in (("authoritative", True), ("order_submission_enabled", True), ("observation_only", False)):
            with self.subTest(field=field):
                value = copy.deepcopy(self.result.brief)
                value[field] = replacement
                with self.assertRaises(ValueError):
                    self.validate(rehash(value))
        for field, replacement in (("mocked", True), ("provider", "remote"), ("request_sha256", "not-a-hash")):
            with self.subTest(field=field):
                value = copy.deepcopy(self.result.brief)
                value["provenance"][field] = replacement
                with self.assertRaises(ValueError):
                    self.validate(rehash(value))

    def test_warnings_citations_and_section_order_remain_source_bound(self):
        mutations = (
            lambda value: value["evidence"].update(warnings=[]),
            lambda value: value["report"]["headline"].update(fact_ids=["oracle.report.invented"]),
            lambda value: value["report"]["sections"].reverse(),
        )
        for index, mutate in enumerate(mutations):
            with self.subTest(index=index):
                value = copy.deepcopy(self.result.brief)
                mutate(value)
                with self.assertRaises(ValueError):
                    self.validate(rehash(value))

    def test_publication_serves_only_the_verified_brief_without_writing(self):
        before = self.file_state()
        reader = CabinReader(self.fixture.artifacts, self.fixture.request.mission_id)
        feed = reader.current()
        self.assertEqual(feed["status"], "READY", feed)
        payload = reader.artifact(feed["publication_id"], BRIEF_PATH)
        self.assertEqual(payload, (self.root / BRIEF_PATH).read_bytes())
        manifest = json.loads(reader.artifact(feed["publication_id"], MANIFEST_PATH))
        reference = manifest["oracle_market_brief"]
        self.assertEqual(reference["sha256"], sha256_bytes(payload))
        self.assertEqual(reference["byte_size"], len(payload))
        self.assertEqual(datetime.fromisoformat(reference["observed_at"]),
            datetime.fromisoformat(self.result.brief["generated_at"]))
        self.assertIsNone(reader.artifact(feed["publication_id"], ATTEMPT_PATH + "/request.json"))
        self.assertIsNone(reader.artifact(feed["publication_id"], ATTEMPT_PATH + "/response.json"))
        self.assertEqual(self.file_state(), before)
        self.fixture.assert_original_unchanged()

    def test_absent_optional_brief_keeps_original_mission_available(self):
        # Only a generated temporary test fixture is removed, not user evidence.
        (self.root / BRIEF_PATH).unlink()
        before = self.file_state()
        publication = capture_publication(ReadOnlyMissionStore(self.fixture.artifacts), self.fixture.request.mission_id)
        manifest = json.loads(publication.files[MANIFEST_PATH])
        self.assertNotIn("oracle_market_brief", manifest)
        self.assertNotIn(BRIEF_PATH, publication.files)
        self.assertEqual(self.file_state(), before)

    def test_invalid_optional_brief_fails_closed_without_substitution(self):
        value = copy.deepcopy(self.result.brief)
        value["evidence"]["facts"][0]["value"] = "invented"
        (self.root / BRIEF_PATH).write_bytes(canonical_json_bytes(rehash(value)))
        before = self.file_state()
        reader = CabinReader(self.fixture.artifacts, self.fixture.request.mission_id)
        feed = reader.current()
        self.assertEqual(feed["status"], "UNAVAILABLE")
        self.assertNotIn("publication_id", feed)
        self.assertEqual(self.file_state(), before)

    def test_reader_limits_match_canonical_and_browser_limits(self):
        for kind in ("headline", "paragraph", "citations"):
            with self.subTest(kind=kind):
                value = copy.deepcopy(self.result.brief)
                if kind == "headline":
                    value["report"]["headline"]["text"] = "x" * 241
                elif kind == "paragraph":
                    value["report"]["sections"][0]["paragraphs"][0]["text"] = "x" * 1201
                else:
                    value["report"]["headline"]["fact_ids"] = [fact["fact_id"] for fact in value["evidence"]["facts"][:9]]
                with self.assertRaises(ValueError):
                    self.validate(rehash(value))
