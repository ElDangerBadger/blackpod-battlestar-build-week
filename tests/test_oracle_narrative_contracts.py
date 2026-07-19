from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path

from blackpod_build_week.contracts.mission_request import ContractValidationError
from blackpod_build_week.contracts.oracle_narrative import (
    EVIDENCE_ARTIFACT_NAMES,
    MODELDOCK_EXPECTED_PROVENANCE_SCHEMA_VERSION,
    MODELDOCK_EXPECTED_SNAPSHOT_CHANGES_SCHEMA_VERSION,
    MODELDOCK_REPLAY_PACK_SCHEMA_VERSION,
    ORACLE_NARRATIVE_REQUEST_SCHEMA_VERSION,
    ORACLE_NARRATIVE_SCHEMA_VERSION,
    ModelDockReplayPack,
    OracleNarrative,
    OracleNarrativeRequest,
    build_oracle_narrative_prompt,
    resolve_json_pointer,
)


OBSERVED_AT = "2026-07-19T19:00:00Z"


def _artifact(name: str, filename: str) -> dict[str, object]:
    return {
        "name": name,
        "path": f"oracle/attempt-0001/{filename}",
        "sha256": (name.encode("utf-8").hex() + "0" * 64)[:64],
        "producer": "oracle",
        "byte_size": 512,
        "schema_version": None,
        "observed_at": OBSERVED_AT,
    }


def valid_request() -> dict[str, object]:
    filenames = {
        "measurements": "oracle_measurements_live.json",
        "diagnostics": "oracle_measurement_diagnostics_live.json",
        "readiness": "fleet-oracles-vapors-example_readiness.json",
        "assessment": "oracle_assessment_live.json",
        "report": "oracle_report_live.json",
    }
    return {
        "schema_version": ORACLE_NARRATIVE_REQUEST_SCHEMA_VERSION,
        "mission_id": "mission-narrative-contract-001",
        "request_id": "request-narrative-contract-001",
        "symbol": "AAPL",
        "run_mode": "REPLAY",
        "oracle_native_state": "READY",
        "measurements": {
            "price": 42.5,
            "volume": 1000,
            "series": [{"close": 41.0}, {"close": 42.5}],
        },
        "diagnostics": {"quality": "GOOD", "missing_fields": 0},
        "readiness": {"state": "READY", "coverage": 0.95},
        "assessment": {"conclusion": "OBSERVED_STRENGTH", "score": 0.7},
        "report": {
            "headline": "Validated Oracle report",
            "as_of": "2026-07-19T18:55:00Z",
        },
        "warnings": ["Coverage is limited to validated inputs."],
        "source_artifacts": {
            evidence_name: _artifact(artifact_name, filenames[evidence_name])
            for evidence_name, artifact_name in EVIDENCE_ARTIFACT_NAMES.items()
        },
    }


def valid_narrative() -> dict[str, object]:
    return {
        "schema_version": ORACLE_NARRATIVE_SCHEMA_VERSION,
        "mission_id": "mission-narrative-contract-001",
        "request_id": "request-narrative-contract-001",
        "symbol": "AAPL",
        "summary": "Oracle evidence includes validated price and volume observations.",
        "observed_facts": [
            {
                "source_artifact": "oracle_measurements",
                "json_pointer": "/price",
                "value": 42.5,
                "statement": "The validated price is 42.5.",
            },
            {
                "source_artifact": "oracle_readiness_report",
                "json_pointer": "/coverage",
                "value": 0.95,
                "statement": "Readiness coverage is 0.95.",
            },
        ],
        "interpretation": "The validated evidence indicates observed strength.",
        "uncertainties": ["Coverage is limited to validated inputs."],
        "warnings": ["The narrative adds no new market facts."],
        "confidence_explanation": "Readiness coverage supports a bounded explanation.",
        "prohibited_actions_acknowledged": True,
    }


def valid_replay_pack() -> dict[str, object]:
    request = OracleNarrativeRequest.from_mapping(valid_request())
    narrative = OracleNarrative.from_mapping(valid_narrative()).validate_against(request)
    correlation = {
        "mission_id": request.mission_id,
        "request_id": request.request_id,
        "symbol": request.symbol,
        "run_mode": request.run_mode.value,
    }
    return {
        "schema_version": MODELDOCK_REPLAY_PACK_SCHEMA_VERSION,
        "fixture_id": "modeldock-oracle-replay-001",
        "created_at": "2026-07-19T19:00:00Z",
        "observed_at": "2026-07-19T19:00:01Z",
        "oracle_input": request.to_dict(),
        "request": {
            "profile": "default",
            "prompt": request.build_prompt(),
            "metadata": {"blackpod_correlation": correlation},
        },
        "response": {
            "status": "ok",
            "request_type": "text.generate",
            "provider": "mlx",
            "model": "mlx-community/test-model",
            "data": {"model_revision": "revision-test-001"},
            "content": narrative.to_canonical_json(),
            "trace_id": "trace-replay-001",
            "mocked": False,
            "metadata": {"blackpod_correlation": correlation},
        },
        "expected_narrative": narrative.to_dict(),
        "expected_provenance": {
            "schema_version": MODELDOCK_EXPECTED_PROVENANCE_SCHEMA_VERSION,
            "provider": "mlx",
            "model": "mlx-community/test-model",
            "model_revision": "revision-test-001",
            "trace_id": "trace-replay-001",
            "mocked": False,
        },
        "expected_snapshot_changes": {
            "schema_version": MODELDOCK_EXPECTED_SNAPSHOT_CHANGES_SCHEMA_VERSION,
            "oracle_status": "SUCCEEDED",
            "modeldock_call_status": "SUCCEEDED",
            "current_phase": "COUNCIL",
            "mission_outcome": "INCOMPLETE",
            "terminal": False,
            "narrative_output": "oracle_modeldock_narrative",
        },
    }


class OracleNarrativeRequestContractTests(unittest.TestCase):
    def test_valid_request_is_canonical_and_exposes_evidence_by_artifact(self) -> None:
        request = OracleNarrativeRequest.from_mapping(valid_request())

        self.assertEqual(request.run_mode.value, "REPLAY")
        self.assertEqual(
            request.evidence_by_artifact["oracle_measurements"]["price"], 42.5
        )
        self.assertEqual(
            request.resolve_pointer("oracle_measurements", "/series/1/close"), 42.5
        )
        self.assertEqual(
            OracleNarrativeRequest.from_json_bytes(request.canonical_json_bytes()),
            request,
        )

    def test_request_rejects_unknown_missing_and_unsupported_fields(self) -> None:
        for mutation, message in (
            (lambda value: value.update({"arbitrary": {}}), "unknown fields"),
            (lambda value: value.pop("measurements"), "missing fields"),
            (
                lambda value: value.update({"schema_version": "future.v2"}),
                "unsupported",
            ),
            (lambda value: value.update({"run_mode": "live"}), "unsupported run_mode"),
        ):
            value = valid_request()
            mutation(value)
            with self.subTest(message=message):
                with self.assertRaisesRegex(ContractValidationError, message):
                    OracleNarrativeRequest.from_mapping(value)

    def test_request_allows_only_the_five_evidence_objects(self) -> None:
        value = valid_request()
        value["candidate_context"] = {"side": "LONG"}
        with self.assertRaisesRegex(ContractValidationError, "unknown fields"):
            OracleNarrativeRequest.from_mapping(value)

        value = valid_request()
        sources = copy.deepcopy(value["source_artifacts"])
        assert isinstance(sources, dict)
        sources["candidate"] = _artifact("candidate", "candidate.json")
        value["source_artifacts"] = sources
        with self.assertRaisesRegex(ContractValidationError, "unknown fields"):
            OracleNarrativeRequest.from_mapping(value)

    def test_source_artifacts_are_exact_full_oracle_references(self) -> None:
        for field, replacement, message in (
            ("name", "wrong-name", "name must"),
            ("producer", "modeldock", "full Oracle"),
            ("path", "/tmp/oracle.json", "beneath the mission root"),
            ("sha256", "bad", "sha256"),
        ):
            value = valid_request()
            sources = copy.deepcopy(value["source_artifacts"])
            assert isinstance(sources, dict)
            measurements = sources["measurements"]
            assert isinstance(measurements, dict)
            measurements[field] = replacement
            value["source_artifacts"] = sources
            with self.subTest(field=field):
                with self.assertRaisesRegex(ContractValidationError, message):
                    OracleNarrativeRequest.from_mapping(value)

    def test_request_rejects_absolute_paths_anywhere_in_evidence(self) -> None:
        for leaked in (
            "/Users/demo/quotes.json",
            "C:\\Users\\demo\\quotes.json",
            "loaded from /private/tmp/quotes.json",
            "loaded from /srv/oracle/quotes.json",
            "loaded from D:\\models\\oracle.bin",
            "loaded from file:///srv/oracle/quotes.json",
        ):
            value = valid_request()
            report = copy.deepcopy(value["report"])
            assert isinstance(report, dict)
            report["source"] = leaked
            value["report"] = report
            with self.subTest(leaked=leaked):
                with self.assertRaisesRegex(ContractValidationError, "absolute local path"):
                    OracleNarrativeRequest.from_mapping(value)

    def test_request_rejects_credential_and_secret_like_material(self) -> None:
        for leaked in (
            "api_key=super-secret-value",
            "Authorization: Bearer abcdefghijklmnop",
            "sk-examplecredential123",
            "-----BEGIN PRIVATE KEY-----",
        ):
            value = valid_request()
            diagnostics = copy.deepcopy(value["diagnostics"])
            assert isinstance(diagnostics, dict)
            diagnostics["note"] = leaked
            value["diagnostics"] = diagnostics
            with self.subTest(leaked=leaked):
                with self.assertRaisesRegex(ContractValidationError, "credential|secret"):
                    OracleNarrativeRequest.from_mapping(value)

        value = valid_request()
        value["assessment"] = {"api_key": None}
        with self.assertRaisesRegex(ContractValidationError, "credential|secret"):
            OracleNarrativeRequest.from_mapping(value)

    def test_request_strict_json_rejects_duplicate_fields_and_nan(self) -> None:
        duplicate = (
            b'{"schema_version":"blackpod.oracle_narrative_request.v1",'
            b'"schema_version":"blackpod.oracle_narrative_request.v1"}'
        )
        with self.assertRaisesRegex(ContractValidationError, "duplicate JSON field"):
            OracleNarrativeRequest.from_json_bytes(duplicate)

        payload = json.dumps(valid_request()).replace('"price": 42.5', '"price": NaN')
        with self.assertRaisesRegex(ContractValidationError, "non-standard JSON"):
            OracleNarrativeRequest.from_json_bytes(payload.encode("utf-8"))

    def test_programmatic_nan_and_non_json_values_are_rejected(self) -> None:
        value = valid_request()
        measurements = copy.deepcopy(value["measurements"])
        assert isinstance(measurements, dict)
        measurements["bad"] = float("nan")
        value["measurements"] = measurements
        with self.assertRaisesRegex(ContractValidationError, "non-finite"):
            OracleNarrativeRequest.from_mapping(value)

        value = valid_request()
        value["report"] = {"bad": Path("relative.json")}
        with self.assertRaisesRegex(ContractValidationError, "non-JSON"):
            OracleNarrativeRequest.from_mapping(value)

    def test_pointer_resolution_supports_escapes_and_rejects_ambiguous_paths(self) -> None:
        document = {"a/b": {"~key": ["zero", "one"]}}
        self.assertEqual(resolve_json_pointer(document, "/a~1b/~0key/1"), "one")
        for pointer in ("", "not/a/pointer", "/a~2b", "/a~1b/~0key/01", "/missing"):
            with self.subTest(pointer=pointer):
                with self.assertRaises(ContractValidationError):
                    resolve_json_pointer(document, pointer)


class OracleNarrativeResponseContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.request = OracleNarrativeRequest.from_mapping(valid_request())

    def test_valid_narrative_resolves_every_fact_and_round_trips(self) -> None:
        narrative = OracleNarrative.from_mapping(valid_narrative())

        self.assertIs(narrative.validate_against(self.request), narrative)
        self.assertEqual(
            OracleNarrative.from_json_bytes(narrative.canonical_json_bytes()), narrative
        )

    def test_correlation_mismatch_is_rejected(self) -> None:
        for field, replacement in (
            ("mission_id", "mission-other-001"),
            ("request_id", "request-other-001"),
            ("symbol", "MSFT"),
        ):
            value = valid_narrative()
            value[field] = replacement
            with self.subTest(field=field):
                narrative = OracleNarrative.from_mapping(value)
                with self.assertRaisesRegex(ContractValidationError, "correlation mismatch"):
                    narrative.validate_against(self.request)

    def test_fact_source_pointer_and_exact_scalar_are_enforced(self) -> None:
        mutations = (
            ("source_artifact", "oracle_unknown", "unknown source"),
            ("json_pointer", "/missing", "does not resolve"),
            ("value", 42.5001, "does not exactly match"),
            ("value", "42.5", "does not exactly match"),
        )
        for field, replacement, message in mutations:
            value = valid_narrative()
            facts = copy.deepcopy(value["observed_facts"])
            assert isinstance(facts, list) and isinstance(facts[0], dict)
            facts[0][field] = replacement
            value["observed_facts"] = facts
            with self.subTest(field=field, replacement=replacement):
                with self.assertRaisesRegex(ContractValidationError, message):
                    OracleNarrative.from_mapping(value).validate_against(self.request)

        value = valid_narrative()
        facts = copy.deepcopy(value["observed_facts"])
        assert isinstance(facts, list) and isinstance(facts[0], dict)
        facts[0]["json_pointer"] = "/series"
        facts[0]["value"] = None
        value["observed_facts"] = facts
        narrative = OracleNarrative.from_mapping(value)
        with self.assertRaisesRegex(ContractValidationError, "resolve to a scalar"):
            narrative.validate_against(self.request)

    def test_numeric_claims_are_allowed_only_in_their_source_linked_fact(self) -> None:
        value = valid_narrative()
        value["interpretation"] = "The evidence includes 42.50 and coverage 0.950."
        with self.assertRaisesRegex(ContractValidationError, "free text"):
            OracleNarrative.from_mapping(value).validate_against(self.request)

        value = valid_narrative()
        facts = copy.deepcopy(value["observed_facts"])
        assert isinstance(facts, list) and isinstance(facts[0], dict)
        facts[0]["statement"] = "The validated price is 42.50."
        value["observed_facts"] = facts
        OracleNarrative.from_mapping(value).validate_against(self.request)

        # Volume 1000 exists elsewhere in the input, but it is not the scalar
        # linked by this fact. Cross-artifact numeric borrowing is forbidden.
        facts[0]["statement"] = "The validated price is 1000."
        value["observed_facts"] = facts
        with self.assertRaisesRegex(ContractValidationError, "source-linked scalar"):
            OracleNarrative.from_mapping(value).validate_against(self.request)

        value = valid_narrative()
        facts = copy.deepcopy(value["observed_facts"])
        assert isinstance(facts, list) and isinstance(facts[0], dict)
        facts[0] = {
            "source_artifact": "oracle_report",
            "json_pointer": "/as_of",
            "value": "2026-07-19T18:55:00Z",
            "statement": "The source timestamp begins with 2026.",
        }
        value["observed_facts"] = facts
        with self.assertRaisesRegex(ContractValidationError, "numeric source scalar"):
            OracleNarrative.from_mapping(value).validate_against(self.request)

    def test_governor_approval_execution_and_order_claims_are_rejected(self) -> None:
        forbidden = (
            "The disposition is PROCEED.",
            "The mission is approved.",
            "You should buy the stock.",
            "Submit an order now.",
            "Invoke BROKER_CALL.",
            "The system must execute the trade.",
            "Accumulate shares.",
            "Reduce the position.",
            "Go long.",
            "Go short.",
            "Enter a position.",
            "Exit the position.",
            "Increase exposure.",
            "Trim the holdings.",
        )
        for statement in forbidden:
            value = valid_narrative()
            value["interpretation"] = statement
            with self.subTest(statement=statement):
                with self.assertRaises(ContractValidationError):
                    OracleNarrative.from_mapping(value).validate_against(self.request)

    def test_explicit_non_authority_language_is_allowed(self) -> None:
        value = valid_narrative()
        value["interpretation"] = (
            "This narrative supplies no trade approval and has no execution authority."
        )
        OracleNarrative.from_mapping(value).validate_against(self.request)

    def test_unsupported_factual_state_posture_and_momentum_claims_are_rejected(self) -> None:
        forbidden = (
            "Readiness is NOT_READY.",
            "Readiness state: DEGRADED.",
            "Diagnostics show failed quality.",
            "Diagnostic quality remains unhealthy.",
            "Analytical posture is bearish.",
            "The evidence shows deteriorating momentum.",
        )
        for statement in forbidden:
            value = valid_narrative()
            value["interpretation"] = statement
            with self.subTest(statement=statement):
                with self.assertRaisesRegex(ContractValidationError, "not supported"):
                    OracleNarrative.from_mapping(value).validate_against(self.request)

        value = valid_narrative()
        value["interpretation"] = "The validated evidence indicates observed strength."
        OracleNarrative.from_mapping(value).validate_against(self.request)

        value["interpretation"] = (
            "Taken together, these inputs suggest a bounded and cautious interpretation."
        )
        OracleNarrative.from_mapping(value).validate_against(self.request)

    def test_qualitative_market_domains_absent_from_oracle_are_rejected(self) -> None:
        value = valid_narrative()
        value["summary"] = (
            "Volatility is elevated and semiconductor leadership is surging."
        )
        with self.assertRaisesRegex(ContractValidationError, "vocabulary absent"):
            OracleNarrative.from_mapping(value).validate_against(self.request)

        value = valid_narrative()
        value["interpretation"] = "Readiness is GOOD."
        with self.assertRaisesRegex(ContractValidationError, "not supported"):
            OracleNarrative.from_mapping(value).validate_against(self.request)

        value = valid_narrative()
        facts = copy.deepcopy(value["observed_facts"])
        assert isinstance(facts, list) and isinstance(facts[0], dict)
        facts[0]["statement"] = (
            "The validated price is 42.5 and volatility is elevated."
        )
        value["observed_facts"] = facts
        with self.assertRaisesRegex(ContractValidationError, "vocabulary absent"):
            OracleNarrative.from_mapping(value).validate_against(self.request)

    def test_mission_symbol_is_correlation_only_without_source_attribution(self) -> None:
        value = valid_narrative()
        value["summary"] = "The validated Oracle evidence describes AAPL."
        with self.assertRaisesRegex(ContractValidationError, "correlation-only"):
            OracleNarrative.from_mapping(value).validate_against(self.request)

        attributed_request = valid_request()
        report = copy.deepcopy(attributed_request["report"])
        assert isinstance(report, dict)
        report["symbol"] = "AAPL"
        attributed_request["report"] = report
        OracleNarrative.from_mapping(value).validate_against(
            OracleNarrativeRequest.from_mapping(attributed_request)
        )

    def test_unknown_missing_duplicate_nan_and_false_acknowledgement_are_rejected(self) -> None:
        value = valid_narrative()
        value["unknown"] = True
        with self.assertRaisesRegex(ContractValidationError, "unknown fields"):
            OracleNarrative.from_mapping(value)

        value = valid_narrative()
        value.pop("summary")
        with self.assertRaisesRegex(ContractValidationError, "missing fields"):
            OracleNarrative.from_mapping(value)

        value = valid_narrative()
        uncertainties = value["uncertainties"]
        assert isinstance(uncertainties, list)
        uncertainties.append(uncertainties[0])
        with self.assertRaisesRegex(ContractValidationError, "duplicate"):
            OracleNarrative.from_mapping(value)

        value = valid_narrative()
        facts = value["observed_facts"]
        assert isinstance(facts, list)
        facts.append(copy.deepcopy(facts[0]))
        with self.assertRaisesRegex(ContractValidationError, "duplicate source pointers"):
            OracleNarrative.from_mapping(value)

        value = valid_narrative()
        value["prohibited_actions_acknowledged"] = False
        with self.assertRaisesRegex(ContractValidationError, "must be true"):
            OracleNarrative.from_mapping(value)

        malformed = json.dumps(valid_narrative()).replace('"value": 42.5', '"value": NaN', 1)
        with self.assertRaisesRegex(ContractValidationError, "non-standard JSON"):
            OracleNarrative.from_json_bytes(malformed.encode("utf-8"))

    def test_absolute_path_and_text_limits_are_rejected(self) -> None:
        for leaked in (
            "/Users/demo/private-output.json",
            "Output came from /srv/modeldock/private-output.json",
            "Output came from C:\\models\\private-output.json",
            "Output came from file:///tmp/private-output.json",
        ):
            value = valid_narrative()
            value["summary"] = leaked
            with self.subTest(leaked=leaked):
                with self.assertRaisesRegex(ContractValidationError, "absolute local path"):
                    OracleNarrative.from_mapping(value)

        value = valid_narrative()
        value["warnings"] = ["password=hunter-example"]
        with self.assertRaisesRegex(ContractValidationError, "credential|secret"):
            OracleNarrative.from_mapping(value)

        value = valid_narrative()
        value["summary"] = "x" * 2001
        with self.assertRaisesRegex(ContractValidationError, "exceeds"):
            OracleNarrative.from_mapping(value)

    def test_strict_json_rejects_duplicate_top_level_fields(self) -> None:
        encoded = OracleNarrative.from_mapping(valid_narrative()).to_canonical_json()
        duplicate = encoded[:-1] + ',"symbol":"AAPL"}'
        with self.assertRaisesRegex(ContractValidationError, "duplicate JSON field"):
            OracleNarrative.from_json_bytes(duplicate.encode("utf-8"))


class OracleNarrativePromptTests(unittest.TestCase):
    def test_prompt_is_deterministic_and_embeds_canonical_input_and_rules(self) -> None:
        request = OracleNarrativeRequest.from_mapping(valid_request())

        first = build_oracle_narrative_prompt(request)
        second = request.build_prompt()

        self.assertEqual(first, second)
        self.assertTrue(first.endswith(request.to_canonical_json()))
        self.assertIn("only source of market facts", first)
        self.assertIn("Do not approve a mission", first)
        self.assertIn("no markdown", first)
        self.assertIn("mission symbol is correlation-only", first)
        self.assertIn("fixed validation fleet", first)
        self.assertLessEqual(len(first.encode("utf-8")), 512 * 1024)
        self.assertIn(ORACLE_NARRATIVE_SCHEMA_VERSION, first)

    def test_request_and_prompt_share_the_client_half_mibibyte_limit(self) -> None:
        value = valid_request()
        value["report"] = {"bounded_blob": "x" * (512 * 1024)}
        with self.assertRaisesRegex(ContractValidationError, "exceeds"):
            OracleNarrativeRequest.from_mapping(value)


class ModelDockReplayPackContractTests(unittest.TestCase):
    def test_committed_stage2_replay_pack_matches_current_contract(self) -> None:
        fixture = (
            Path(__file__).resolve().parents[1]
            / "fixtures/modeldock_oracle_narrative.replay.v1.json"
        )

        pack = ModelDockReplayPack.from_file(fixture)

        self.assertEqual(pack.schema_version, MODELDOCK_REPLAY_PACK_SCHEMA_VERSION)
        self.assertEqual(pack.request["prompt"], pack.oracle_input.build_prompt())
        self.assertEqual(
            pack.expected_snapshot_changes["modeldock_call_status"],
            "SUCCEEDED",
        )
        self.assertEqual(
            pack.expected_narrative.to_dict(),
            OracleNarrative.from_json_bytes(
                pack.response["content"].encode("utf-8")
            ).validate_against(pack.oracle_input).to_dict(),
        )

    def test_valid_pack_preserves_exact_raw_sections_and_round_trips(self) -> None:
        value = valid_replay_pack()
        pack = ModelDockReplayPack.from_mapping(value)

        self.assertEqual(pack.raw_section("request"), value["request"])
        copied = pack.raw_section("request")
        copied["profile"] = "mutated"
        self.assertEqual(pack.request["profile"], "default")
        self.assertEqual(
            ModelDockReplayPack.from_json_bytes(pack.canonical_json_bytes()), pack
        )

        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "pack.json"
            path.write_bytes(pack.canonical_json_bytes())
            self.assertEqual(ModelDockReplayPack.from_file(path), pack)

    def test_pack_rejects_unknown_missing_schema_and_timestamp_errors(self) -> None:
        mutations = (
            (lambda value: value.update({"unknown": {}}), "unknown fields"),
            (lambda value: value.pop("response"), "missing fields"),
            (
                lambda value: value.update({"schema_version": "future.v2"}),
                "unsupported",
            ),
            (
                lambda value: value.update({"observed_at": "2026-07-19T18:59:59Z"}),
                "may not precede",
            ),
        )
        for mutation, message in mutations:
            value = valid_replay_pack()
            mutation(value)
            with self.subTest(message=message):
                with self.assertRaisesRegex(ContractValidationError, message):
                    ModelDockReplayPack.from_mapping(value)

    def test_pack_rejects_request_response_and_expected_correlation_mismatch(self) -> None:
        for section in ("request", "response"):
            value = valid_replay_pack()
            section_value = copy.deepcopy(value[section])
            assert isinstance(section_value, dict)
            metadata = section_value["metadata"]
            assert isinstance(metadata, dict)
            correlation = metadata["blackpod_correlation"]
            assert isinstance(correlation, dict)
            correlation["request_id"] = "request-wrong-001"
            value[section] = section_value
            with self.subTest(section=section):
                with self.assertRaisesRegex(ContractValidationError, "correlation mismatch"):
                    ModelDockReplayPack.from_mapping(value)

        value = valid_replay_pack()
        expected = copy.deepcopy(value["expected_narrative"])
        assert isinstance(expected, dict)
        expected["symbol"] = "MSFT"
        value["expected_narrative"] = expected
        with self.assertRaisesRegex(ContractValidationError, "correlation mismatch"):
            ModelDockReplayPack.from_mapping(value)

    def test_pack_rejects_prompt_content_and_absolute_path_mismatch(self) -> None:
        value = valid_replay_pack()
        request = copy.deepcopy(value["request"])
        assert isinstance(request, dict)
        request["prompt"] = "different prompt"
        value["request"] = request
        with self.assertRaisesRegex(ContractValidationError, "prompt does not match"):
            ModelDockReplayPack.from_mapping(value)

        value = valid_replay_pack()
        response = copy.deepcopy(value["response"])
        assert isinstance(response, dict)
        different = valid_narrative()
        different["summary"] = "Oracle evidence contains a different bounded summary."
        response["content"] = json.dumps(different)
        value["response"] = response
        with self.assertRaisesRegex(ContractValidationError, "does not match"):
            ModelDockReplayPack.from_mapping(value)

        value = valid_replay_pack()
        provenance = copy.deepcopy(value["expected_provenance"])
        assert isinstance(provenance, dict)
        provenance["path"] = "/Users/demo/modeldock"
        value["expected_provenance"] = provenance
        with self.assertRaisesRegex(ContractValidationError, "unknown fields"):
            ModelDockReplayPack.from_mapping(value)

        value = valid_replay_pack()
        response = copy.deepcopy(value["response"])
        assert isinstance(response, dict)
        data = response["data"]
        assert isinstance(data, dict)
        data["model_path"] = "/srv/models/private-model"
        value["response"] = response
        with self.assertRaisesRegex(ContractValidationError, "absolute local path"):
            ModelDockReplayPack.from_mapping(value)

    def test_pack_expected_provenance_is_exact_and_cross_checked(self) -> None:
        for field, replacement in (
            ("provider", "ollama"),
            ("model", "other-model"),
            ("model_revision", "other-revision"),
            ("trace_id", "trace-other-001"),
            ("mocked", True),
        ):
            value = valid_replay_pack()
            provenance = copy.deepcopy(value["expected_provenance"])
            assert isinstance(provenance, dict)
            provenance[field] = replacement
            value["expected_provenance"] = provenance
            with self.subTest(field=field):
                with self.assertRaisesRegex(
                    ContractValidationError, "does not match expected_provenance"
                ):
                    ModelDockReplayPack.from_mapping(value)

        value = valid_replay_pack()
        provenance = copy.deepcopy(value["expected_provenance"])
        assert isinstance(provenance, dict)
        provenance["latency_ms"] = 1
        value["expected_provenance"] = provenance
        with self.assertRaisesRegex(ContractValidationError, "unknown fields"):
            ModelDockReplayPack.from_mapping(value)

        value = valid_replay_pack()
        provenance = copy.deepcopy(value["expected_provenance"])
        assert isinstance(provenance, dict)
        provenance["schema_version"] = "future.v2"
        value["expected_provenance"] = provenance
        with self.assertRaisesRegex(ContractValidationError, "unsupported"):
            ModelDockReplayPack.from_mapping(value)

    def test_pack_expected_snapshot_allows_only_successful_oracle_transition(self) -> None:
        replacements = {
            "oracle_status": "FAILED",
            "modeldock_call_status": "SKIPPED",
            "current_phase": "ORACLE",
            "mission_outcome": "FAILED",
            "terminal": True,
            "narrative_output": "oracle_report",
        }
        for field, replacement in replacements.items():
            value = valid_replay_pack()
            expected = copy.deepcopy(value["expected_snapshot_changes"])
            assert isinstance(expected, dict)
            expected[field] = replacement
            value["expected_snapshot_changes"] = expected
            with self.subTest(field=field):
                with self.assertRaisesRegex(
                    ContractValidationError, "successful strict Oracle-to-Council"
                ):
                    ModelDockReplayPack.from_mapping(value)

        value = valid_replay_pack()
        expected = copy.deepcopy(value["expected_snapshot_changes"])
        assert isinstance(expected, dict)
        expected["governor_status"] = "NOT_STARTED"
        value["expected_snapshot_changes"] = expected
        with self.assertRaisesRegex(ContractValidationError, "unknown fields"):
            ModelDockReplayPack.from_mapping(value)

    def test_pack_strict_parser_rejects_duplicate_fields_and_nan(self) -> None:
        with self.assertRaisesRegex(ContractValidationError, "duplicate JSON field"):
            ModelDockReplayPack.from_json_bytes(
                b'{"schema_version":"blackpod.modeldock_replay_pack.v1",'
                b'"schema_version":"blackpod.modeldock_replay_pack.v1"}'
            )
        value = valid_replay_pack()
        response = copy.deepcopy(value["response"])
        assert isinstance(response, dict)
        metadata = response["metadata"]
        assert isinstance(metadata, dict)
        metadata["latency"] = float("nan")
        value["response"] = response
        with self.assertRaisesRegex(ContractValidationError, "non-finite"):
            ModelDockReplayPack.from_mapping(value)


if __name__ == "__main__":
    unittest.main()
