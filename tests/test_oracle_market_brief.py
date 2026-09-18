"""Supplement integration uses synthetic evidence and an injected HTTP transport."""

from __future__ import annotations

import json
import io
import os
import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path
from contextlib import redirect_stderr
from unittest.mock import patch

from blackpod_build_week.battlestar_config import BattlestarConfig
from blackpod_build_week.contracts import MissionRequest
from blackpod_build_week.hashing import canonical_json_bytes
from blackpod_build_week.mission_store import MissionStore
from blackpod_build_week.modeldock_client import (
    HttpResponse, ModelDockClient, ModelDockClientError, ModelDockFailure,
)
from blackpod_build_week.modeldock_config import ModelDockConfig
from blackpod_build_week.oracle_market_brief import (
    ATTEMPT_PATH, BRIEF_PATH, CANONICAL_MODULE_PATH, OracleMarketBriefError,
    generate_market_brief, load_canonical_brief_module, load_mission_evidence,
    main,
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
    def __init__(self, *, draft=None, error=None, on_generate=None, model=MODEL):
        self.draft = synthetic_draft() if draft is None else draft
        self.error = error
        self.on_generate = on_generate
        self.requests = []
        self.model = model

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
                    "requested_max_tokens": wire["max_tokens"], "effective_max_tokens": wire["max_tokens"],
                    "generated_token_count": 500, "stop_reason": "completed_or_eos", "generation_options": {"temperature": 0.0}},
                "trace_id": "trace-brief-test", "mocked": False,
            })
        return HttpResponse(200, {"Content-Length": str(len(body))}, body)


class CanonicalBriefLoaderTests(unittest.TestCase):
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
        self.assertEqual(module.validate_brief(result.brief, evidence), result.brief)
        self.assertEqual(result.brief["provenance"]["canonical_module_sha256"], digest)
        self.assertEqual(result.path.read_bytes(), canonical_json_bytes(result.brief))
        response = (self.root / ATTEMPT_PATH / "response.json").read_text()
        self.assertNotIn("/private/model", response)
        self.assert_original_unchanged()
        self.assertFalse(self.store.load_mission(self.request.mission_id).snapshot.stages["oracle"].modeldock_calls)

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
        self.assertEqual(diagnostics["error_type"], "OracleMarketBriefError")
        self.assertIn("versioned contract validation", diagnostics["message"])
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
