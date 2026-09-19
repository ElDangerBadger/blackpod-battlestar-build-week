"""Supplement integration uses synthetic evidence and an injected HTTP transport."""

from __future__ import annotations

import json
import io
import os
import shutil
import tempfile
import unittest
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from contextlib import contextmanager, redirect_stderr
from unittest.mock import patch

from blackpod_build_week.battlestar_config import BattlestarConfig
from blackpod_build_week.contracts import MissionRequest
from blackpod_build_week.hashing import canonical_json_bytes, sha256_bytes
from blackpod_build_week.mission_store import MissionStore
from blackpod_build_week.modeldock_client import (
    HttpResponse, ModelDockClient, ModelDockClientError, ModelDockFailure,
)
from blackpod_build_week.modeldock_config import ModelDockConfig
from blackpod_build_week.narrative_diagnostics import (
    CanonicalBriefValidationError, narrative_validation_message,
)
from blackpod_build_week.oracle_market_brief import (
    ATTEMPT_PATH, BRIEF_PATH, CANONICAL_MODULE_PATH, REVIEWED_RETRY_PREFIX, REVIEWED_REVISION_PREFIX, OracleMarketBriefError,
    generate_market_brief, load_canonical_brief_module, load_mission_evidence,
    main, _validate_draft_with_diagnostics,
)
from blackpod_build_week.oracle_workflow import OracleRunSettings, run_oracle
from test_oracle_enrichment_workflow import EvidenceOracleAdapter, OBSERVED_AT, oracle_documents


MODEL = "mlx-community/test-model"
CAPTURED_AT = "2026-07-19T12:00:00Z"
CANONICAL_ROOT = os.environ.get("BATTLESTAR_PATH")


class CompleteEvidenceAdapter(EvidenceOracleAdapter):
    """Expand this new fixture without changing legacy replay fixture semantics."""
    def execute(self, *args, **kwargs):
        documents = oracle_documents()
        measurements = documents["oracle_measurements_live.json"]
        documents["oracle_report_live.json"]["key_measurements"] = {
            key: measurements[key] for key in (
                "breadth_score", "leadership_concentration", "sector_dispersion",
                "rotation_velocity", "defensive_strength", "cyclical_strength",
                "risk_on_score", "risk_off_score", "symbols",
            )
        }
        with patch("test_oracle_enrichment_workflow.oracle_documents", return_value=documents):
            return super().execute(*args, **kwargs)


def synthetic_draft():
    """Synthetic model output, never used as a live narrative fallback."""
    topics = (
        ("participation", "oracle.assessment.breadth_posture", "The recorded breadth posture provides the context for market participation."),
        ("leadership", "oracle.assessment.leadership_posture", "The recorded leadership posture describes how participation is distributed."),
        ("rotation", "oracle.assessment.rotation_posture", "The recorded rotation posture provides context for relative sector leadership."),
        ("risk", "oracle.assessment.risk_regime_posture", "The recorded risk posture should be read alongside the limits of the measured fleet."),
        ("watchpoints", "oracle.readiness.freshness_ok", "Freshness at capture does not establish the state of the market now."),
        ("limits", "oracle.diagnostics.provenance_complete", "Recorded provenance remains distinct from the limits of the measured fleet."),
    )
    return {
        "schema_version": "blackpod.oracle_market_brief_draft.v1",
        "headline": {"text": "A bounded reading of recorded market structure", "fact_ids": ["oracle.assessment.breadth_posture"]},
        "sections": [{"section_id": section, "paragraphs": [{"text": text, "fact_ids": [fact]}]} for section, fact, text in topics],
    }


class BriefTransport:
    def __init__(self, *, draft=None, error=None, on_generate=None, model=MODEL, structured_confirmed=True):
        self.draft = synthetic_draft() if draft is None else draft
        self.error = error
        self.on_generate = on_generate
        self.requests = []
        self.model = model
        self.structured_confirmed = structured_confirmed

    @property
    def generations(self):
        return sum(request["url"].endswith("/text/generate") for request in self.requests)

    def request(self, **request):
        self.requests.append(request)
        if request["url"].endswith("/models"):
            body = canonical_json_bytes({"models": [{"name": MODEL, "provider": "mlx", "capabilities": ["text"]}]})
        else:
            if self.on_generate:
                self.on_generate()
            if self.error:
                raise self.error
            wire = json.loads(request["body"])
            body = canonical_json_bytes({
                "status": "ok", "request_type": "text.generate", "profile": "default",
                "provider": "mlx", "model": self.model, "content": json.dumps(self.draft),
                "data": {"engine": "mlx-lm", "model_path": "/private/model/snapshots/test-revision", "profile": "default"},
                "metadata": {"blackpod_correlation": wire["metadata"]["blackpod_correlation"],
                    **({"structured_output": {"mode": "json_schema", "validated": True}} if self.structured_confirmed else {}),
                    "requested_max_tokens": wire["max_tokens"], "effective_max_tokens": wire["max_tokens"],
                    "generated_token_count": 500, "stop_reason": "completed_or_eos", "generation_options": {"temperature": 0.0}},
                "trace_id": "trace-brief-test", "mocked": False,
            })
        return HttpResponse(200, {"Content-Length": str(len(body))}, body)


class CanonicalBriefLoaderTests(unittest.TestCase):
    def test_draft_adapter_catches_the_loaded_error_class_not_its_name(self):
        canonical_error = type("OracleMarketBriefError", (ValueError,), {})
        lookalike_error = type("OracleMarketBriefError", (ValueError,), {})
        validator = SimpleNamespace(OracleMarketBriefError=canonical_error)
        for error in (canonical_error("unsupported draft schema"), lookalike_error("unsupported draft schema")):
            with self.subTest(is_actual_class=type(error) is canonical_error):
                def reject(*_, error=error):
                    raise error
                validator.validate_draft = reject
                if type(error) is canonical_error:
                    with self.assertRaises(CanonicalBriefValidationError) as caught:
                        _validate_draft_with_diagnostics(validator, {}, {})
                    self.assertIn("rule=schema_version; field=schema_version", narrative_validation_message(caught.exception))
                else:
                    with self.assertRaises(lookalike_error) as caught:
                        _validate_draft_with_diagnostics(validator, {}, {})
                    self.assertIs(caught.exception, error)

    def test_requires_explicit_canonical_root(self):
        with self.assertRaisesRegex(OracleMarketBriefError, "explicitly"):
            generate_market_brief(artifacts_root=Path("missing"), mission_id="mission-test", environ={})

    def test_rejects_relative_root(self):
        with self.assertRaisesRegex(OracleMarketBriefError, "absolute"):
            load_canonical_brief_module(Path("relative"))

    def test_rejects_runtime_dependencies_before_execution(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / CANONICAL_MODULE_PATH
            target.parent.mkdir(parents=True)
            target.write_text("import os\nraise RuntimeError('must not run')\n")
            with self.assertRaisesRegex(OracleMarketBriefError, "dependencies"):
                load_canonical_brief_module(root)

    def test_rejects_module_symlink(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / CANONICAL_MODULE_PATH
            target.parent.mkdir(parents=True)
            original = root / "module.py"
            original.write_text("raise RuntimeError('must not run')\n")
            target.symlink_to(original)
            with self.assertRaises(OracleMarketBriefError):
                load_canonical_brief_module(root)

    def test_token_budget_checked_before_any_io(self):
        for budget in (True, 0, 511, 4097, "3072"):
            with self.subTest(budget=budget), self.assertRaisesRegex(OracleMarketBriefError, "max_tokens"):
                generate_market_brief(artifacts_root=Path("missing"), mission_id="mission-test", max_tokens=budget)

    def test_retry_hash_checked_before_any_io(self):
        for digest in (True, "", "a" * 63, "A" * 64, "../attempt", 123):
            with self.subTest(digest=digest), self.assertRaisesRegex(OracleMarketBriefError, "lowercase SHA-256"):
                generate_market_brief(artifacts_root=Path("missing"), mission_id="mission-test", reviewed_retry_of=digest)

    def test_revision_requires_explicit_reviewed_retry_and_boolean_before_io(self):
        for flag, digest in ((True, None), (1, "a" * 64), ("true", "a" * 64), (None, None)):
            with self.subTest(flag=flag), self.assertRaisesRegex(OracleMarketBriefError, "requires reviewed_retry_of"):
                generate_market_brief(artifacts_root=Path("missing"), mission_id="mission-test",
                    reviewed_retry_of=digest, reviewed_request_revision=flag)

    def test_cli_forwards_explicit_request_revision_flag(self):
        with patch("blackpod_build_week.oracle_market_brief.generate_market_brief", side_effect=OracleMarketBriefError("test-only failure")) as generate, redirect_stderr(io.StringIO()):
            status = main(["--artifacts-root", "missing", "--mission-id", "mission-test",
                "--reviewed-retry-of", "a" * 64, "--reviewed-request-revision"])
        self.assertEqual(status, 1)
        self.assertEqual(generate.call_args.kwargs["reviewed_retry_of"], "a" * 64)
        self.assertIs(generate.call_args.kwargs["reviewed_request_revision"], True)

    def test_cli_surfaces_only_the_safe_failure_reason(self):
        safe = "market brief capture failed [timeout]: ModelDock request exceeded its client-side deadline. Attempt preserved without automatic retry."
        output = io.StringIO()
        with patch("blackpod_build_week.oracle_market_brief.generate_market_brief", side_effect=OracleMarketBriefError(safe)), redirect_stderr(output):
            status = main(["--artifacts-root", "missing", "--mission-id", "mission-test"])
        self.assertEqual(status, 1)
        self.assertEqual(output.getvalue().strip(), safe)


@unittest.skipUnless(CANONICAL_ROOT, "set BATTLESTAR_PATH for canonical brief integration")
class OracleMarketBriefTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.artifacts = self.base / "artifacts"
        self.store = MissionStore(self.artifacts)
        self.request = MissionRequest.from_mapping({
            "schema_version": "blackpod.mission_request.v1", "mission_id": "mission-market-brief-test",
            "request_id": "request-market-brief-test", "run_mode": "LIVE", "symbol": "AAPL",
            "requested_at": OBSERVED_AT, "operator_id": "test-operator", "metadata": {},
        })
        self.store.initialize(self.request, mission_id=self.request.mission_id, started_at=OBSERVED_AT, observed_at=OBSERVED_AT)
        fake_root = self.base / "fake-runtime"
        native_module = fake_root / "blackpod/runtime/oracle_pipeline.py"
        native_module.parent.mkdir(parents=True)
        native_module.write_text("# injected Oracle adapter; no runtime calls\n")
        fleet = fake_root / "configs/universes/oracles_vapors.example.yaml"
        fleet.parent.mkdir(parents=True)
        fleet.write_text("fleet_id: fleet-test\n")
        config = BattlestarConfig(root=fake_root, oracle_module_path=native_module, fleet_path=fleet,
            git_revision="a" * 40, git_branch="test", dirty_worktree=False)
        run_oracle(OracleRunSettings(mission_id=self.request.mission_id, artifacts_root=self.artifacts),
            adapter=CompleteEvidenceAdapter(), config_loader=lambda **_: config,
            clock=lambda: datetime(2026, 7, 18, 18, 5, tzinfo=UTC))
        self.loaded = self.store.load_mission(self.request.mission_id)
        self.root = self.loaded.paths.mission_root
        self.original = {path.relative_to(self.root): path.read_bytes() for path in self.root.rglob("*") if path.is_file()}
        self.env = {"BATTLESTAR_PATH": CANONICAL_ROOT, "MODELDOCK_BASE_URL": "http://127.0.0.1:8000",
            "MODELDOCK_TIMEOUT_SECONDS": "10"}
        self.config = ModelDockConfig(base_url="http://127.0.0.1:8000", timeout_seconds=10, model=MODEL)

    def tearDown(self):
        self.temp.cleanup()

    def invoke(self, transport=None, **kwargs):
        transport = transport or BriefTransport()
        client = ModelDockClient(self.config, transport=transport,
            now=lambda: datetime(2026, 7, 19, 12, tzinfo=UTC), monotonic=lambda: 0.0)
        result = generate_market_brief(artifacts_root=self.artifacts, mission_id=self.request.mission_id,
            environ=kwargs.pop("environ", self.env), client=client, **kwargs)
        return result, transport

    def assert_original_unchanged(self):
        for relative, original in self.original.items():
            self.assertEqual((self.root / relative).read_bytes(), original, relative)

    def test_success_is_canonical_source_bound_and_additive_only(self):
        result, transport = self.invoke()
        self.assertEqual(result.action, "CAPTURED")
        self.assertEqual(transport.generations, 1)
        self.assertEqual(len(transport.requests), 1)
        self.assertNotIn("model", json.loads(transport.requests[0]["body"]))
        self.assertEqual(transport.requests[0]["url"], "http://127.0.0.1:8000/text/generate")
        module, digest = load_canonical_brief_module(Path(CANONICAL_ROOT))
        evidence = module.build_evidence(mission_id=self.request.mission_id, request_id=self.request.request_id,
            symbol="AAPL", run_mode="LIVE", sources=load_mission_evidence(self.loaded))
        wire = json.loads(transport.requests[0]["body"])
        self.assertNotIn("prompt", wire)
        self.assertEqual(wire["messages"], [{"role": "user", "content": module.build_prompt(evidence)}])
        self.assertEqual(wire["response_format"], {"type": "json_schema", "schema": module.build_output_schema(evidence)})
        self.assertEqual(module.validate_brief(result.brief, evidence), result.brief)
        self.assertEqual(result.brief["provenance"]["canonical_module_sha256"], digest)
        self.assertEqual(result.path.read_bytes(), canonical_json_bytes(result.brief))
        response = (self.root / ATTEMPT_PATH / "response.json").read_text()
        self.assertNotIn("/private/model", response)
        self.assertEqual(json.loads(response)["metadata"]["structured_output"], {"mode": "json_schema", "validated": True})
        self.assert_original_unchanged()
        self.assertFalse(self.store.load_mission(self.request.mission_id).snapshot.stages["oracle"].modeldock_calls)

    def test_older_appliance_cannot_silently_downgrade_structured_generation(self):
        transport = BriefTransport(structured_confirmed=False)
        with self.assertRaisesRegex(OracleMarketBriefError, "response_structured_output_unconfirmed"):
            self.invoke(transport)
        self.assertEqual(transport.generations, 1)
        self.assertFalse((self.root / BRIEF_PATH).exists())
        failure = json.loads((self.root / ATTEMPT_PATH / "failure.json").read_bytes())
        self.assertFalse(failure["brief_published"])
        self.assertEqual(failure["modeldock_failure"]["code"], "response_structured_output_unconfirmed")
        with self.assertRaisesRegex(OracleMarketBriefError, "already reserved"):
            self.invoke(transport)
        self.assertEqual(transport.generations, 1)
        self.assert_original_unchanged()

    def test_injected_executor_cannot_bypass_structured_acknowledgement(self):
        invalid_metadata = (
            None, [], {}, {"structured_output": None}, {"structured_output": []},
            {"structured_output": {}},
            {"structured_output": {"mode": "json", "validated": True}},
            *({"structured_output": {"mode": "json_schema", "validated": value}}
              for value in (None, False, 0, 1, "true")),
        )
        for index, metadata in enumerate(invalid_metadata):
            with self.subTest(metadata=metadata):
                artifacts = self.base / f"injected-artifacts-{index}"
                shutil.copytree(self.artifacts, artifacts)
                root = artifacts / self.root.relative_to(self.artifacts.resolve())
                transport = BriefTransport()
                validated_client = ModelDockClient(self.config, transport=transport,
                    now=lambda: datetime(2026, 7, 19, 12, tzinfo=UTC), monotonic=lambda: 0.0)

                def generate(*args, **kwargs):
                    result = validated_client.generate_text(*args, **kwargs)
                    response = {**result.safe_response, "metadata": metadata}
                    return replace(result, safe_response=response,
                        safe_response_bytes=canonical_json_bytes(response))

                executor = SimpleNamespace(generate_text=generate)
                with self.assertRaisesRegex(OracleMarketBriefError, "lacks confirmed schema-constrained"):
                    generate_market_brief(artifacts_root=artifacts, mission_id=self.request.mission_id,
                        environ=self.env, client=executor)
                self.assertEqual(transport.generations, 1)
                self.assertFalse((root / BRIEF_PATH).exists())
                self.assertFalse((root / ATTEMPT_PATH / "validated_brief.json").exists())
                failure = json.loads((root / ATTEMPT_PATH / "failure.json").read_bytes())
                self.assertEqual(failure["code"], "CAPTURE_FAILED")
                self.assertIs(failure["brief_published"], False)
                with self.assertRaisesRegex(OracleMarketBriefError, "already reserved"):
                    generate_market_brief(artifacts_root=artifacts, mission_id=self.request.mission_id,
                        environ=self.env, client=executor)
                self.assertEqual(transport.generations, 1)
                for relative, original in self.original.items():
                    self.assertEqual((root / relative).read_bytes(), original, relative)
        self.assert_original_unchanged()

    def test_injected_executor_cannot_omit_acknowledgement_from_persisted_response(self):
        transport = BriefTransport()
        validated_client = ModelDockClient(self.config, transport=transport,
            now=lambda: datetime(2026, 7, 19, 12, tzinfo=UTC), monotonic=lambda: 0.0)

        def generate(*args, **kwargs):
            result = validated_client.generate_text(*args, **kwargs)
            metadata = dict(result.safe_response["metadata"])
            metadata.pop("structured_output")
            persisted = {**result.safe_response, "metadata": metadata}
            return replace(result, safe_response_bytes=canonical_json_bytes(persisted))

        executor = SimpleNamespace(generate_text=generate)
        with self.assertRaisesRegex(OracleMarketBriefError, "projection conflicts"):
            generate_market_brief(artifacts_root=self.artifacts, mission_id=self.request.mission_id,
                environ=self.env, client=executor)
        self.assertEqual(transport.generations, 1)
        self.assertFalse((self.root / BRIEF_PATH).exists())
        self.assertFalse((self.root / ATTEMPT_PATH / "response.json").exists())
        failure = json.loads((self.root / ATTEMPT_PATH / "failure.json").read_bytes())
        self.assertEqual(failure["code"], "CAPTURE_FAILED")
        self.assertIs(failure["brief_published"], False)
        with self.assertRaisesRegex(OracleMarketBriefError, "already reserved"):
            generate_market_brief(artifacts_root=self.artifacts, mission_id=self.request.mission_id,
                environ=self.env, client=executor)
        self.assertEqual(transport.generations, 1)
        self.assert_original_unchanged()

    def test_idempotent_existing_brief_requires_no_model_config_or_call(self):
        first, _ = self.invoke()
        second, transport = self.invoke(environ={"BATTLESTAR_PATH": CANONICAL_ROOT})
        self.assertEqual(second.action, "ALREADY_CAPTURED")
        self.assertEqual(second.brief, first.brief)
        self.assertEqual(transport.requests, [])
        self.assert_original_unchanged()

    def test_existing_corrupt_brief_refuses_overwrite_or_inference(self):
        self.invoke()
        (self.root / BRIEF_PATH).write_bytes(b"{}\n")
        transport = BriefTransport()
        with self.assertRaisesRegex(OracleMarketBriefError, "refusing overwrite"):
            self.invoke(transport)
        self.assertEqual(transport.requests, [])
        self.assertEqual((self.root / BRIEF_PATH).read_bytes(), b"{}\n")

    def test_invalid_model_content_never_publishes_or_retries(self):
        draft = synthetic_draft()
        draft["headline"]["text"] = "Buy AAPL now and submit an order"
        transport = BriefTransport(draft=draft)
        with self.assertRaisesRegex(OracleMarketBriefError, "narrative_schema_invalid"):
            self.invoke(transport)
        self.assertEqual(transport.generations, 1)
        self.assertFalse((self.root / BRIEF_PATH).exists())
        failure = (self.root / ATTEMPT_PATH / "failure.json").read_text()
        self.assertNotIn("Buy AAPL", failure)
        diagnostics = json.loads(failure)["modeldock_failure"]
        self.assertEqual(diagnostics["code"], "narrative_schema_invalid")
        self.assertEqual(diagnostics["error_type"], "CanonicalBriefValidationError")
        self.assertIn("versioned contract validation", diagnostics["message"])
        self.assertIn("rule=prose_guardrail; field=brief_text", diagnostics["message"])
        self.assertIsInstance(diagnostics["latency_ms"], float)
        self.assertEqual(diagnostics["started_at"], diagnostics["observed_at"])
        self.assertEqual(len(diagnostics["raw_response_sha256"]), 64)
        self.assertGreater(diagnostics["response_byte_size"], 0)
        self.assertNotIn("content", diagnostics["safe_response"])
        self.assertEqual(len(diagnostics["safe_response"]["content_sha256"]), 64)
        self.assertNotIn("model_path", diagnostics["safe_response"]["data"])
        before = (self.root / ATTEMPT_PATH / "failure.json").read_bytes()
        again = BriefTransport()
        with self.assertRaisesRegex(OracleMarketBriefError, "already reserved"):
            self.invoke(again)
        self.assertEqual(again.requests, [])
        self.assertEqual((self.root / ATTEMPT_PATH / "failure.json").read_bytes(), before)
        self.assert_original_unchanged()

    def assert_draft_failure_rule(self, draft, rule, field):
        transport = BriefTransport(draft=draft)
        with self.assertRaisesRegex(OracleMarketBriefError, "narrative_schema_invalid"):
            self.invoke(transport)
        self.assertEqual(transport.generations, 1)
        self.assertFalse((self.root / BRIEF_PATH).exists())
        failure = json.loads((self.root / ATTEMPT_PATH / "failure.json").read_bytes())
        diagnostics = failure["modeldock_failure"]
        self.assertEqual(diagnostics["code"], "narrative_schema_invalid")
        self.assertEqual(diagnostics["error_type"], "CanonicalBriefValidationError")
        self.assertEqual(diagnostics["message"],
            "ModelDock narrative failed its versioned contract validation "
            f"(rule={rule}; field={field}).")
        self.assertNotIn("content", diagnostics["safe_response"])
        self.assert_original_unchanged()

    def test_real_canonical_brief_structure_rejection_is_diagnostic_only(self):
        draft = synthetic_draft()
        draft["untrusted-model-authored-field"] = "/private/secret-value"
        self.assert_draft_failure_rule(draft, "fields_mismatch", "brief")
        failure = (self.root / ATTEMPT_PATH / "failure.json").read_text()
        self.assertNotIn("untrusted-model-authored-field", failure)
        self.assertNotIn("/private/secret-value", failure)

    def test_real_canonical_brief_citation_rejection_is_diagnostic_only(self):
        draft = synthetic_draft()
        draft["headline"]["fact_ids"] = ["untrusted-model-authored-fact"]
        self.assert_draft_failure_rule(draft, "required_known_citations", "fact_citations")
        self.assertNotIn("untrusted-model-authored-fact", (self.root / ATTEMPT_PATH / "failure.json").read_text())

    def test_real_canonical_brief_section_rejection_is_diagnostic_only(self):
        draft = synthetic_draft()
        draft["sections"].reverse()
        self.assert_draft_failure_rule(draft, "section_order_or_paragraph_count", "sections")

    def test_real_canonical_brief_plain_text_rejection_keeps_compound_reason(self):
        draft = synthetic_draft()
        draft["headline"]["text"] = " "
        self.assert_draft_failure_rule(draft, "bounded_plain_text", "brief_text")

    def test_unknown_canonical_rejection_is_unclassified_without_exception_text(self):
        module, digest = load_canonical_brief_module(Path(CANONICAL_ROOT))
        private_text = "/private/unrecognized-canonical-rejection"
        with patch("blackpod_build_week.oracle_market_brief.load_canonical_brief_module", return_value=(module, digest)), \
             patch.object(module, "validate_draft", side_effect=module.OracleMarketBriefError(private_text)):
            self.assert_draft_failure_rule(synthetic_draft(), "unclassified", "narrative")
        self.assertNotIn(private_text, (self.root / ATTEMPT_PATH / "failure.json").read_text())

    def test_timeout_has_sanitized_failure_and_durable_reservation(self):
        with self.assertRaisesRegex(OracleMarketBriefError, r"\[timeout\].*client-side deadline"):
            self.invoke(BriefTransport(error=TimeoutError("secret model response must not escape")))
        failure = (self.root / ATTEMPT_PATH / "failure.json").read_text()
        self.assertNotIn("secret model", failure)
        diagnostics = json.loads(failure)["modeldock_failure"]
        self.assertEqual(diagnostics["code"], "timeout")
        self.assertEqual(diagnostics["error_type"], "TimeoutError")
        self.assertIsNone(diagnostics["raw_response_sha256"])
        self.assertIsNone(diagnostics["safe_response"])
        self.assertTrue((self.root / ATTEMPT_PATH / "intent.json").exists())
        self.assertFalse((self.root / BRIEF_PATH).exists())
        self.assert_original_unchanged()

    def test_interrupt_keeps_intent_and_prevents_automatic_retry(self):
        with self.assertRaises(KeyboardInterrupt):
            self.invoke(BriefTransport(error=KeyboardInterrupt()))
        with self.assertRaisesRegex(OracleMarketBriefError, "already reserved"):
            self.invoke()
        self.assertFalse((self.root / BRIEF_PATH).exists())

    def test_parallel_invocation_cannot_duplicate_generation(self):
        second = BriefTransport()
        def concurrent():
            with self.assertRaisesRegex(OracleMarketBriefError, "already reserved"):
                self.invoke(second)
        result, first = self.invoke(BriefTransport(on_generate=concurrent))
        self.assertEqual(result.action, "CAPTURED")
        self.assertEqual(first.generations, 1)
        self.assertEqual(second.requests, [])

    def original_failure(self):
        with self.assertRaises(OracleMarketBriefError):
            self.invoke(BriefTransport(error=TimeoutError("test-only timeout")))
        files = {path.name: path.read_bytes() for path in (self.root / ATTEMPT_PATH).iterdir()}
        return sha256_bytes(files["failure.json"]), files

    def test_reviewed_retry_is_separate_hash_bound_and_preserves_failed_attempt(self):
        digest, before = self.original_failure()
        result, transport = self.invoke(reviewed_retry_of=digest)
        self.assertEqual(result.action, "CAPTURED")
        self.assertEqual(transport.generations, 1)
        for name, payload in before.items():
            self.assertEqual((self.root / ATTEMPT_PATH / name).read_bytes(), payload)
        retry = self.root / (REVIEWED_RETRY_PREFIX + digest)
        intent = json.loads((retry / "intent.json").read_bytes())
        self.assertEqual(intent["reviewed_retry_of"]["failure_sha256"], digest)
        self.assertEqual(intent["reviewed_retry_of"]["failure_path"], ATTEMPT_PATH + "/failure.json")
        self.assertEqual((retry / "validated_brief.json").read_bytes(), result.path.read_bytes())
        self.assert_original_unchanged()
        repeated, second = self.invoke(reviewed_retry_of=digest, environ={"BATTLESTAR_PATH": CANONICAL_ROOT})
        self.assertEqual(repeated.action, "ALREADY_CAPTURED")
        self.assertEqual(second.requests, [])

    def test_failed_reviewed_retry_cannot_be_repeated(self):
        digest, before = self.original_failure()
        with self.assertRaises(OracleMarketBriefError):
            self.invoke(BriefTransport(error=TimeoutError("test-only retry failure")), reviewed_retry_of=digest)
        retry = self.root / (REVIEWED_RETRY_PREFIX + digest)
        failure = (retry / "failure.json").read_bytes()
        self.assertEqual(json.loads(failure)["reviewed_retry_of"]["failure_sha256"], digest)
        transport = BriefTransport()
        with self.assertRaisesRegex(OracleMarketBriefError, "already reserved"):
            self.invoke(transport, reviewed_retry_of=digest)
        self.assertEqual(transport.requests, [])
        self.assertEqual((retry / "failure.json").read_bytes(), failure)
        self.assertEqual((self.root / ATTEMPT_PATH / "failure.json").read_bytes(), before["failure.json"])
        self.assertFalse((self.root / BRIEF_PATH).exists())

    def test_reviewed_retry_requires_exact_failed_evidence_before_call(self):
        digest, _ = self.original_failure()
        for mutation in ("hash", "request", "intent", "failure"):
            with self.subTest(mutation=mutation):
                originals = {path: path.read_bytes() for path in (self.root / ATTEMPT_PATH).iterdir()}
                if mutation != "hash":
                    (self.root / ATTEMPT_PATH / f"{mutation}.json").write_bytes(b"{}")
                transport = BriefTransport()
                with self.assertRaisesRegex(OracleMarketBriefError, "exact intact original failure"):
                    self.invoke(transport, reviewed_retry_of="f" * 64 if mutation == "hash" else digest)
                self.assertEqual(transport.requests, [])
                self.assertFalse((self.root / (REVIEWED_RETRY_PREFIX + digest)).exists())
                for path, data in originals.items():
                    path.write_bytes(data)

    def test_reviewed_retry_rejects_missing_failure(self):
        transport = BriefTransport()
        with self.assertRaisesRegex(OracleMarketBriefError, "exact intact original failure"):
            self.invoke(transport, reviewed_retry_of="a" * 64)
        self.assertEqual(transport.requests, [])

    def test_reviewed_retry_cannot_follow_directory_symlink(self):
        digest, _ = self.original_failure()
        elsewhere = self.base / "retry-elsewhere"
        elsewhere.mkdir()
        (self.root / (REVIEWED_RETRY_PREFIX + digest)).symlink_to(elsewhere, target_is_directory=True)
        transport = BriefTransport()
        with self.assertRaisesRegex(OracleMarketBriefError, "already reserved"):
            self.invoke(transport, reviewed_retry_of=digest)
        self.assertEqual(transport.requests, [])
        self.assertEqual(list(elsewhere.iterdir()), [])

    def test_reviewed_retry_race_cannot_duplicate_generation(self):
        digest, _ = self.original_failure()
        second = BriefTransport()
        def concurrent():
            with self.assertRaisesRegex(OracleMarketBriefError, "already reserved"):
                self.invoke(second, reviewed_retry_of=digest)
        _, first = self.invoke(BriefTransport(on_generate=concurrent), reviewed_retry_of=digest)
        self.assertEqual(first.generations, 1)
        self.assertEqual(second.requests, [])

    def test_original_failure_changed_during_retry_prevents_publication(self):
        digest, _ = self.original_failure()
        transport = BriefTransport(on_generate=lambda: (self.root / ATTEMPT_PATH / "failure.json").write_bytes(b"{}"))
        with self.assertRaisesRegex(OracleMarketBriefError, "exact intact original failure"):
            self.invoke(transport, reviewed_retry_of=digest)
        self.assertEqual(transport.generations, 1)
        self.assertFalse((self.root / BRIEF_PATH).exists())

    def test_original_intent_bytes_changed_during_retry_prevents_publication(self):
        digest, _ = self.original_failure()
        def change_intent():
            path = self.root / ATTEMPT_PATH / "intent.json"
            path.write_bytes(path.read_bytes() + b"\n")
        transport = BriefTransport(on_generate=change_intent)
        with self.assertRaisesRegex(OracleMarketBriefError, "evidence changed"):
            self.invoke(transport, reviewed_retry_of=digest)
        self.assertEqual(transport.generations, 1)
        self.assertFalse((self.root / BRIEF_PATH).exists())

    @contextmanager
    def revised_prompt(self):
        module, digest = load_canonical_brief_module(Path(CANONICAL_ROOT))
        build_prompt = module.build_prompt
        with patch("blackpod_build_week.oracle_market_brief.load_canonical_brief_module", return_value=(module, digest)), \
             patch.object(module, "build_prompt", side_effect=lambda evidence: build_prompt(evidence) + "\nTest-only revised canonical instructions."):
            yield

    def failed_reviewed_retry(self, *, legacy_original=False):
        digest, _ = self.original_failure()
        if legacy_original:
            original = self.root / ATTEMPT_PATH
            request = json.loads((original / "request.json").read_bytes())
            request["prompt"] = request.pop("messages")[0]["content"]
            request_bytes = canonical_json_bytes(request)
            (original / "request.json").write_bytes(request_bytes)
            for filename in ("intent.json", "failure.json"):
                record = json.loads((original / filename).read_bytes())
                record["request_sha256"] = sha256_bytes(request_bytes)
                (original / filename).write_bytes(canonical_json_bytes(record))
            digest = sha256_bytes((original / "failure.json").read_bytes())
        with self.assertRaises(OracleMarketBriefError):
            self.invoke(BriefTransport(error=TimeoutError("test-only retry failure")), reviewed_retry_of=digest)
        before = {path.relative_to(self.root): path.read_bytes()
            for directory in (self.root / ATTEMPT_PATH, self.root / (REVIEWED_RETRY_PREFIX + digest))
            for path in directory.iterdir()}
        return digest, before

    def assert_attempts_preserved(self, before):
        for relative, content in before.items():
            self.assertEqual((self.root / relative).read_bytes(), content, relative)
        self.assert_original_unchanged()

    def test_reviewed_revision_is_request_bound_and_preserves_both_failed_attempts(self):
        digest, before = self.failed_reviewed_retry(legacy_original=True)
        with self.revised_prompt():
            result, transport = self.invoke(reviewed_retry_of=digest, reviewed_request_revision=True)
        self.assertEqual(result.action, "CAPTURED")
        self.assertEqual(transport.generations, 1)
        request_bytes = transport.requests[0]["body"]
        revision_id = sha256_bytes(canonical_json_bytes({
            "original_failure_sha256": digest, "request_sha256": sha256_bytes(request_bytes)}))
        revision = self.root / (REVIEWED_REVISION_PREFIX + revision_id)
        intent = json.loads((revision / "intent.json").read_bytes())
        lineage = intent["reviewed_request_revision"]
        self.assertEqual(lineage["revision_id"], revision_id)
        self.assertEqual(lineage["failure_sha256"], sha256_bytes(before[Path(REVIEWED_RETRY_PREFIX + digest) / "failure.json"]))
        self.assertEqual(lineage["intent_sha256"], sha256_bytes(before[Path(REVIEWED_RETRY_PREFIX + digest) / "intent.json"]))
        self.assertNotEqual(lineage["previous_prompt_sha256"], lineage["revised_prompt_sha256"])
        self.assertEqual((revision / "validated_brief.json").read_bytes(), result.path.read_bytes())
        self.assert_attempts_preserved(before)
        repeated, second = self.invoke(reviewed_retry_of=digest, reviewed_request_revision=True,
            environ={"BATTLESTAR_PATH": CANONICAL_ROOT})
        self.assertEqual(repeated.action, "ALREADY_CAPTURED")
        self.assertEqual(second.requests, [])

    def test_reviewed_revision_rejects_unchanged_prompt_even_with_changed_budget(self):
        digest, before = self.failed_reviewed_retry()
        transport = BriefTransport()
        with self.assertRaisesRegex(OracleMarketBriefError, "changed canonical prompt"):
            self.invoke(transport, reviewed_retry_of=digest, reviewed_request_revision=True, max_tokens=4096)
        self.assertEqual(transport.requests, [])
        self.assertEqual(list((self.root / "presentation").glob("oracle_market_brief_revision_*")), [])
        self.assert_attempts_preserved(before)

    def test_reviewed_revision_requires_failed_retry_not_original_failure_alone(self):
        digest, before = self.original_failure()
        transport = BriefTransport()
        with self.revised_prompt(), self.assertRaisesRegex(OracleMarketBriefError, "intact failed reviewed retry"):
            self.invoke(transport, reviewed_retry_of=digest, reviewed_request_revision=True)
        self.assertEqual(transport.requests, [])
        for name, payload in before.items():
            self.assertEqual((self.root / ATTEMPT_PATH / name).read_bytes(), payload)

    def test_reviewed_revision_failure_never_publishes_or_repeats(self):
        digest, before = self.failed_reviewed_retry()
        draft = synthetic_draft()
        draft["headline"]["text"] = "Buy AAPL now"
        transport = BriefTransport(draft=draft)
        with self.revised_prompt():
            with self.assertRaisesRegex(OracleMarketBriefError, "narrative_schema_invalid"):
                self.invoke(transport, reviewed_retry_of=digest, reviewed_request_revision=True)
            revision, = (self.root / "presentation").glob("oracle_market_brief_revision_*")
            reserved = {path.name: path.read_bytes() for path in revision.iterdir()}
            second = BriefTransport()
            with self.assertRaisesRegex(OracleMarketBriefError, "already reserved"):
                self.invoke(second, reviewed_retry_of=digest, reviewed_request_revision=True)
        self.assertEqual(transport.generations, 1)
        self.assertEqual(second.requests, [])
        self.assertEqual({path.name: path.read_bytes() for path in revision.iterdir()}, reserved)
        self.assertNotIn("Buy AAPL", reserved["failure.json"].decode())
        self.assertIn("reviewed_request_revision", json.loads(reserved["failure.json"]))
        self.assertFalse((self.root / BRIEF_PATH).exists())
        self.assert_attempts_preserved(before)

    def test_reviewed_revision_race_cannot_duplicate_generation(self):
        digest, before = self.failed_reviewed_retry()
        second = BriefTransport()
        def concurrent():
            with self.assertRaisesRegex(OracleMarketBriefError, "already reserved"):
                self.invoke(second, reviewed_retry_of=digest, reviewed_request_revision=True)
        with self.revised_prompt():
            result, first = self.invoke(BriefTransport(on_generate=concurrent),
                reviewed_retry_of=digest, reviewed_request_revision=True)
        self.assertEqual(result.action, "CAPTURED")
        self.assertEqual(first.generations, 1)
        self.assertEqual(second.requests, [])
        self.assert_attempts_preserved(before)

    def test_interrupted_revision_keeps_reservation_and_never_repeats(self):
        digest, before = self.failed_reviewed_retry()
        transport = BriefTransport(error=KeyboardInterrupt())
        second = BriefTransport()
        with self.revised_prompt():
            with self.assertRaises(KeyboardInterrupt):
                self.invoke(transport, reviewed_retry_of=digest, reviewed_request_revision=True)
            with self.assertRaisesRegex(OracleMarketBriefError, "already reserved"):
                self.invoke(second, reviewed_retry_of=digest, reviewed_request_revision=True)
        self.assertEqual(transport.generations, 1)
        self.assertEqual(second.requests, [])
        revision, = (self.root / "presentation").glob("oracle_market_brief_revision_*")
        self.assertTrue((revision / "intent.json").is_file())
        self.assertFalse((self.root / BRIEF_PATH).exists())
        self.assert_attempts_preserved(before)

    def test_reviewed_revision_cannot_follow_reservation_symlink(self):
        digest, before = self.failed_reviewed_retry()
        with self.revised_prompt():
            with self.assertRaises(OracleMarketBriefError):
                self.invoke(BriefTransport(error=TimeoutError("test-only revision failure")),
                    reviewed_retry_of=digest, reviewed_request_revision=True)
            revision, = (self.root / "presentation").glob("oracle_market_brief_revision_*")
            elsewhere = self.base / "revision-elsewhere"
            revision.rename(elsewhere)
            revision.symlink_to(elsewhere, target_is_directory=True)
            saved = {path.name: path.read_bytes() for path in elsewhere.iterdir()}
            transport = BriefTransport()
            with self.assertRaisesRegex(OracleMarketBriefError, "already reserved"):
                self.invoke(transport, reviewed_retry_of=digest, reviewed_request_revision=True)
        self.assertEqual(transport.requests, [])
        self.assertEqual({path.name: path.read_bytes() for path in elsewhere.iterdir()}, saved)
        self.assert_attempts_preserved(before)

    def test_reviewed_revision_requires_completed_retry_receipt(self):
        digest, before = self.failed_reviewed_retry()
        retry = self.root / (REVIEWED_RETRY_PREFIX + digest)
        # Represent a durable reservation interrupted before any failure receipt.
        (retry / "failure.json").unlink()
        transport = BriefTransport()
        with self.revised_prompt(), self.assertRaisesRegex(OracleMarketBriefError, "intact failed reviewed retry"):
            self.invoke(transport, reviewed_retry_of=digest, reviewed_request_revision=True)
        self.assertEqual(transport.requests, [])
        self.assertFalse((self.root / BRIEF_PATH).exists())
        self.assertEqual((self.root / ATTEMPT_PATH / "failure.json").read_bytes(), before[Path(ATTEMPT_PATH) / "failure.json"])

    def test_reviewed_revision_rejects_damaged_predecessor_without_call(self):
        digest, before = self.failed_reviewed_retry()
        retry = self.root / (REVIEWED_RETRY_PREFIX + digest)
        for filename in ("failure.json", "intent.json", "request.json"):
            with self.subTest(filename=filename):
                original = (retry / filename).read_bytes()
                (retry / filename).write_bytes(b"{}")
                transport = BriefTransport()
                with self.revised_prompt(), self.assertRaisesRegex(OracleMarketBriefError, "intact failed reviewed retry"):
                    self.invoke(transport, reviewed_retry_of=digest, reviewed_request_revision=True)
                self.assertEqual(transport.requests, [])
                self.assertEqual(list((self.root / "presentation").glob("oracle_market_brief_revision_*")), [])
                (retry / filename).write_bytes(original)
        self.assert_attempts_preserved(before)

    def test_reviewed_revision_rejects_changed_predecessor_evidence_and_lineage(self):
        digest, before = self.failed_reviewed_retry()
        retry = self.root / (REVIEWED_RETRY_PREFIX + digest)
        for key, value in (("evidence_id", "changed"), ("brief_published", True),
                           ("reviewed_retry_of", {}), ("reviewed_request_revision", {})):
            with self.subTest(key=key):
                path = retry / "failure.json"
                original = path.read_bytes()
                record = json.loads(original)
                record[key] = value
                path.write_bytes(canonical_json_bytes(record))
                transport = BriefTransport()
                with self.revised_prompt(), self.assertRaisesRegex(OracleMarketBriefError, "intact failed reviewed retry"):
                    self.invoke(transport, reviewed_retry_of=digest, reviewed_request_revision=True)
                self.assertEqual(transport.requests, [])
                path.write_bytes(original)
        self.assert_attempts_preserved(before)

    def test_reviewed_revision_predecessor_bytes_changed_during_call_blocks_publication(self):
        digest, _ = self.failed_reviewed_retry()
        path = self.root / (REVIEWED_RETRY_PREFIX + digest) / "failure.json"
        def tamper():
            path.write_bytes(path.read_bytes() + b"\n")
        transport = BriefTransport(on_generate=tamper)
        with self.revised_prompt(), self.assertRaisesRegex(OracleMarketBriefError, "evidence changed"):
            self.invoke(transport, reviewed_retry_of=digest, reviewed_request_revision=True)
        self.assertEqual(transport.generations, 1)
        self.assertFalse((self.root / BRIEF_PATH).exists())

    def test_reviewed_revision_original_bytes_changed_during_call_blocks_publication(self):
        digest, _ = self.failed_reviewed_retry()
        path = self.root / ATTEMPT_PATH / "intent.json"
        def tamper():
            path.write_bytes(path.read_bytes() + b"\n")
        transport = BriefTransport(on_generate=tamper)
        with self.revised_prompt(), self.assertRaisesRegex(OracleMarketBriefError, "evidence changed"):
            self.invoke(transport, reviewed_retry_of=digest, reviewed_request_revision=True)
        self.assertEqual(transport.generations, 1)
        self.assertFalse((self.root / BRIEF_PATH).exists())

    def test_source_tamper_before_generation_fails_without_request(self):
        reference = next(item for item in self.loaded.snapshot.artifacts if item.name == "oracle_measurements")
        (self.root / reference.path).write_bytes(b"{}")
        transport = BriefTransport()
        with self.assertRaises(OracleMarketBriefError):
            self.invoke(transport)
        self.assertEqual(transport.requests, [])
        self.assertFalse((self.root / ATTEMPT_PATH).exists())

    def test_source_tamper_during_generation_fails_closed(self):
        reference = next(item for item in self.loaded.snapshot.artifacts if item.name == "oracle_measurements")
        transport = BriefTransport(on_generate=lambda: (self.root / reference.path).write_bytes(b"{}"))
        with self.assertRaises(OracleMarketBriefError):
            self.invoke(transport)
        self.assertEqual(transport.generations, 1)
        self.assertFalse((self.root / BRIEF_PATH).exists())

    def test_presentation_symlink_is_not_followed(self):
        elsewhere = self.base / "elsewhere"
        elsewhere.mkdir()
        (self.root / "presentation").symlink_to(elsewhere, target_is_directory=True)
        transport = BriefTransport()
        with self.assertRaises(Exception):
            self.invoke(transport)
        self.assertEqual(transport.requests, [])
        self.assertEqual(list(elsewhere.iterdir()), [])

    def test_appliance_selects_model_without_client_model_configuration(self):
        result, transport = self.invoke(BriefTransport(model="appliance-selected-model"))
        self.assertEqual(result.brief["provenance"]["model"], "appliance-selected-model")
        self.assertEqual(len(transport.requests), 1)
        self.assertNotIn("model", json.loads(transport.requests[0]["body"]))

    def test_legacy_model_environment_cannot_pin_the_appliance(self):
        env = dict(self.env)
        env["MODELDOCK_MODEL"] = "outdated-client-model-name"
        result, transport = self.invoke(BriefTransport(model="different-active-model"), environ=env)
        self.assertEqual(result.brief["provenance"]["model"], "different-active-model")
        self.assertEqual(len(transport.requests), 1)
        self.assertNotIn("model", json.loads(transport.requests[0]["body"]))

    def test_replay_and_unfinished_oracle_are_not_enriched(self):
        from dataclasses import replace
        from blackpod_build_week.contracts import RunMode, StageStatus

        replay = replace(self.loaded, request=replace(self.loaded.request, run_mode=RunMode.REPLAY))
        with self.assertRaisesRegex(OracleMarketBriefError, "existing LIVE"):
            load_mission_evidence(replay)
        stages = dict(self.loaded.snapshot.stages)
        stages["oracle"] = replace(stages["oracle"], status=StageStatus.NOT_STARTED)
        unfinished = replace(self.loaded, snapshot=replace(self.loaded.snapshot, stages=stages))
        with self.assertRaisesRegex(OracleMarketBriefError, "must have succeeded"):
            load_mission_evidence(unfinished)

    def test_refuses_canonical_checkout_as_artifacts_root(self):
        with self.assertRaisesRegex(OracleMarketBriefError, "must not overlap"):
            generate_market_brief(artifacts_root=Path(CANONICAL_ROOT), mission_id=self.request.mission_id, environ=self.env)

    def test_unknown_citations_and_numeric_prose_are_rejected(self):
        module, _ = load_canonical_brief_module(Path(CANONICAL_ROOT))
        evidence = module.build_evidence(mission_id=self.request.mission_id, request_id=self.request.request_id,
            symbol="AAPL", run_mode="LIVE", sources=load_mission_evidence(self.loaded))
        for field, value in (("text", "A 99 percent expectation"), ("fact_ids", ["oracle.report.invented"])):
            with self.subTest(field=field):
                draft = synthetic_draft()
                draft["headline"][field] = value
                with self.assertRaises(ValueError):
                    module.validate_draft(draft, evidence)

    def test_failed_client_projection_strips_content_even_if_previously_accepted(self):
        failure = ModelDockFailure(
            code="response_validation", error_type="ModelDockProtocolError",
            message="ModelDock response failed final validation", resumable=False,
            latency_ms=7.0, started_at=CAPTURED_AT, observed_at=CAPTURED_AT,
            raw_response_sha256="a" * 64, response_byte_size=200,
            safe_response={"status": "ok", "content": "PRIVATE_UNOFFICIAL_MODEL_TEXT",
                "provider": "mlx", "model": MODEL, "data": {"engine": "mlx-lm"}},
        )
        transport = BriefTransport()
        with patch.object(ModelDockClient, "generate_text", side_effect=ModelDockClientError(failure)) as generate:
            with self.assertRaisesRegex(OracleMarketBriefError, "response_validation"):
                self.invoke(transport)
        self.assertEqual(generate.call_count, 1)
        self.assertEqual(transport.requests, [])
        payload = (self.root / ATTEMPT_PATH / "failure.json").read_text()
        self.assertNotIn("PRIVATE_UNOFFICIAL_MODEL_TEXT", payload)
        safe = json.loads(payload)["modeldock_failure"]["safe_response"]
        self.assertNotIn("content", safe)
        self.assertEqual(len(safe["content_sha256"]), 64)
        self.assertGreater(safe["content_byte_size"], 0)
        self.assertFalse((self.root / BRIEF_PATH).exists())
        self.assert_original_unchanged()

    def test_unexpected_failure_does_not_serialize_exception_text(self):
        with patch.object(ModelDockClient, "generate_text", side_effect=RuntimeError("api_key=PRIVATE_SECRET /private/source")):
            with self.assertRaises(OracleMarketBriefError) as caught:
                self.invoke()
        receipt = (self.root / ATTEMPT_PATH / "failure.json").read_text()
        self.assertNotIn("PRIVATE_SECRET", receipt + str(caught.exception))
        self.assertNotIn("/private/source", receipt + str(caught.exception))
        self.assertIsNone(json.loads(receipt)["modeldock_failure"])
