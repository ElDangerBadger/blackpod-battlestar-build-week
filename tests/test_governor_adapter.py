from __future__ import annotations

import ast
import json
import tempfile
import unittest
from pathlib import Path

from blackpod_build_week.contracts import (
    ContractValidationError,
    GovernorTransportKind,
    MissionRequest,
    RunMode,
    StageStatus,
)
from blackpod_build_week.governor_adapter import (
    EXPECTED_GOVERNOR_OUTPUT_FILENAMES,
    GOVERNOR_RENDERED_DECISION_SCHEMA_VERSION,
    GOVERNOR_SUPPORTING_CONTEXT_SCHEMA_VERSION,
    GOVERNOR_WARNING_CLASSIFICATION_SCHEMA_VERSION,
    GovernorAdapter,
    GovernorMissionContext,
    GovernorSupportingContext,
    GovernorTransportRequest,
    GovernorTransportTimeout,
    _classify_oracle_warnings,
)


OBSERVED_AT = "2026-07-18T18:05:00Z"
MISSION_ID = "mission-governor-adapter-001"
REQUEST_ID = "request-governor-adapter-001"


def mission_request(
    run_mode: str = "REPLAY", *, mission_id: str = MISSION_ID
) -> MissionRequest:
    return MissionRequest.from_mapping(
        {
            "schema_version": "blackpod.mission_request.v1",
            "request_id": REQUEST_ID,
            "mission_id": mission_id,
            "run_mode": run_mode,
            "symbol": "AAPL",
            "requested_at": OBSERVED_AT,
            "operator_id": "operator-governor-adapter",
            "metadata": {},
        }
    )


def supporting_mapping(
    run_mode: str = "REPLAY",
    *,
    mission_id: str = MISSION_ID,
    request_id: str = REQUEST_ID,
    contract_case: str = "NORMAL",
) -> dict[str, object]:
    return {
        "schema_version": GOVERNOR_SUPPORTING_CONTEXT_SCHEMA_VERSION,
        "context_id": "governor-supporting-context-001",
        "mission_id": mission_id,
        "request_id": request_id,
        "run_mode": run_mode,
        "generated_at": OBSERVED_AT,
        "accountability": {
            "outcomes": [],
            "notes": "No prior accountability observations are available.",
        },
        "replay_contract_case": contract_case,
    }


class RecordingGovernorTransport:
    def __init__(
        self,
        *,
        disposition: str = "PROCEED",
        readiness_state: str | None = None,
        error: Exception | None = None,
        malformed: bool = False,
        artifact_mismatch: bool = False,
    ) -> None:
        self.disposition = disposition
        self.readiness_state = readiness_state or {
            "PROCEED": "READY",
            "HOLD": "READY",
            "REVIEW_REQUIRED": "REVIEW_REQUIRED",
            "BLOCKED": "BLOCKED",
            "STAND_DOWN": "INVALID",
        }.get(disposition, "READY")
        self.error = error
        self.malformed = malformed
        self.artifact_mismatch = artifact_mismatch
        self.calls: list[tuple[GovernorTransportRequest, float]] = []

    def run(
        self, invocation: GovernorTransportRequest, *, deadline_seconds: float
    ) -> dict[str, object]:
        self.calls.append((invocation, deadline_seconds))
        if self.error is not None:
            raise self.error
        supporting = invocation.supporting_context
        output = invocation.mission_root / invocation.output_dir
        output.mkdir(parents=True, exist_ok=True)
        allowed = (
            "NONE" if self.disposition in {"BLOCKED", "STAND_DOWN"} else "OPERATOR_REVIEW"
        )
        warnings = ["caution retained"] if self.disposition == "HOLD" else []
        routine = ["MISSING_PRIOR_ORACLE_MEASUREMENTS"]
        blockers = ["required context blocked"] if self.disposition == "BLOCKED" else []
        reviews = ["Operator review remains pending."] if self.disposition in {"HOLD", "REVIEW_REQUIRED"} else []
        payloads: dict[str, dict[str, object]] = {
            "governor_input_context.json": {
                "context_id": supporting["context_id"],
                "mission_id": supporting["mission_id"],
                "request_id": supporting["request_id"],
            },
            "governor_senate_intake.json": {"intake_id": "governor-intake-001"},
            "governor_deliberation_prep.json": {
                "prep_id": "governor-prep-001",
                "secretary_summary_id": "secretary-summary-001",
            },
            "governor_deliberation.json": {
                "deliberation_id": "governor-deliberation-001",
                "prep_id": "governor-prep-001",
                "unresolved_questions": reviews,
            },
            "governor_decision_readiness.json": {
                "readiness_id": "governor-readiness-001",
                "deliberation_id": "governor-deliberation-001",
                "readiness_state": self.readiness_state,
            },
            "governor_decision.json": {
                "decision_id": "governor-decision-001",
                "deliberation_id": "governor-deliberation-001",
                "readiness_id": "governor-readiness-001",
                "decision_state": self.disposition,
                "decision_status": "RENDERED",
                "allowed_next_step": allowed,
                "warnings": warnings,
                "blockers": blockers,
            },
            "governor_rendered_decision.json": {
                "schema_version": GOVERNOR_RENDERED_DECISION_SCHEMA_VERSION,
                "mission_id": supporting["mission_id"],
                "request_id": supporting["request_id"],
                "decision_id": (
                    "wrong-decision" if self.artifact_mismatch else "governor-decision-001"
                ),
                "disposition": self.disposition,
                "warnings": warnings,
                "routine_warnings": routine,
                "blocking_reasons": blockers,
                "review_requirements": reviews,
            },
            "secretary_outcome_summary.json": {
                "summary_id": "secretary-summary-001"
            },
            "warning_classification.json": {
                "schema_version": GOVERNOR_WARNING_CLASSIFICATION_SCHEMA_VERSION,
                "routine_warnings": routine,
                "decision_warnings": warnings,
            },
        }
        for filename in EXPECTED_GOVERNOR_OUTPUT_FILENAMES:
            (output / filename).write_text(
                json.dumps(payloads[filename], sort_keys=True) + "\n",
                encoding="utf-8",
            )
        result: dict[str, object] = {
            "native_disposition": self.disposition,
            "readiness_state": self.readiness_state,
            "decision_id": "governor-decision-001",
            "allowed_next_step": allowed,
            "produced_paths": [
                f"{invocation.output_dir}/{name}"
                for name in EXPECTED_GOVERNOR_OUTPUT_FILENAMES
            ],
            "context_id": supporting["context_id"],
            "warnings": warnings,
            "routine_warnings": routine,
            "blocking_reasons": blockers,
            "review_requirements": reviews,
        }
        if self.malformed:
            result.pop("decision_id")
        return result


class GovernorSupportingContextTests(unittest.TestCase):
    def test_strict_versioned_context_round_trips(self) -> None:
        value = supporting_mapping()
        parsed = GovernorSupportingContext.from_mapping(value)

        self.assertEqual(
            GovernorSupportingContext.from_bytes(json.dumps(value).encode()), parsed
        )
        self.assertIs(parsed.run_mode, RunMode.REPLAY)
        self.assertEqual(parsed.accountability.outcomes, ())

    def test_unknown_duplicate_and_unsupported_fields_are_rejected(self) -> None:
        unknown = supporting_mapping()
        unknown["unexpected"] = True
        with self.assertRaisesRegex(ContractValidationError, "unknown fields"):
            GovernorSupportingContext.from_mapping(unknown)
        with self.assertRaisesRegex(ContractValidationError, "duplicate JSON field"):
            GovernorSupportingContext.from_bytes(
                b'{"schema_version":"blackpod.governor_supporting_context.v1",'
                b'"schema_version":"duplicate"}'
            )
        unsupported = supporting_mapping()
        unsupported["schema_version"] = "blackpod.governor_supporting_context.v2"
        with self.assertRaisesRegex(ContractValidationError, "unsupported"):
            GovernorSupportingContext.from_mapping(unsupported)

    def test_phase4_accountability_and_live_case_are_strict(self) -> None:
        outcomes = supporting_mapping()
        outcomes["accountability"]["outcomes"] = [{}]  # type: ignore[index]
        with self.assertRaisesRegex(ContractValidationError, "empty array"):
            GovernorSupportingContext.from_mapping(outcomes)

        unsafe_notes = supporting_mapping()
        unsafe_notes["accountability"]["notes"] = "Submit an order."  # type: ignore[index]
        with self.assertRaisesRegex(ContractValidationError, "unsupported"):
            GovernorSupportingContext.from_mapping(unsafe_notes)

        with self.assertRaisesRegex(ContractValidationError, "LIVE"):
            GovernorSupportingContext.from_mapping(
                supporting_mapping("LIVE", contract_case="INVALID_STAND_DOWN")
            )


class GovernorAdapterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.battlestar_path = root / "battlestar"
        modules = (
            "blackpod/advisors/mandate.py",
            "blackpod/advisors/oracle_measurement_diagnostics.py",
            "blackpod/advisors/secretary_outcomes.py",
            "blackpod/advisors/senate_candidate_intake.py",
            "blackpod/advisors/senate_deliberation.py",
            "blackpod/advisors/trading_candidate_generator.py",
            "blackpod/governor/governor_senate_intake.py",
            "blackpod/governor/governor_deliberation_prep.py",
            "blackpod/governor/governor_deliberation.py",
            "blackpod/governor/governor_decision_readiness.py",
            "blackpod/governor/governor_decision.py",
        )
        for relative in modules:
            target = self.battlestar_path / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("# interface sentinel\n", encoding="utf-8")
        self.mission_root = root / "artifacts/missions" / MISSION_ID
        self.mission_root.mkdir(parents=True)
        self.context = GovernorMissionContext(
            mission_id=MISSION_ID,
            mission_root=self.mission_root,
        )
        for relative in self.context.input_paths:
            target = self.mission_root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("{}\n", encoding="utf-8")
        self.supporting = GovernorSupportingContext.from_mapping(
            supporting_mapping()
        )

    def adapter(self, transport) -> GovernorAdapter:
        return GovernorAdapter(
            self.battlestar_path.resolve(),
            transport=transport,
            deadline_seconds=7.5,
        )

    def clear_outputs(self) -> None:
        if self.context.output_absolute.exists():
            for path in self.context.output_absolute.iterdir():
                path.unlink()

    def test_all_canonical_dispositions_are_technical_successes(self) -> None:
        for disposition in (
            "PROCEED",
            "HOLD",
            "REVIEW_REQUIRED",
            "BLOCKED",
            "STAND_DOWN",
        ):
            with self.subTest(disposition=disposition):
                self.clear_outputs()
                transport = RecordingGovernorTransport(disposition=disposition)
                result = self.adapter(transport).execute(
                    mission_request(), self.context, supporting_context=self.supporting
                )
                self.assertIs(result.status, StageStatus.SUCCEEDED)
                self.assertEqual(result.native_disposition, disposition)
                self.assertIsNone(result.failure)
                self.assertEqual(transport.calls[0][1], 7.5)

    def test_success_preserves_correlation_warning_classes_and_lineage(self) -> None:
        result = self.adapter(RecordingGovernorTransport(disposition="HOLD")).execute(
            mission_request(), self.context, supporting_context=self.supporting
        )

        self.assertEqual(result.mission_id, MISSION_ID)
        self.assertEqual(result.request_id, REQUEST_ID)
        self.assertIs(result.transport, GovernorTransportKind.REPLAY_FIXTURE)
        self.assertEqual(result.warnings, ("caution retained",))
        self.assertEqual(
            result.routine_warnings, ("MISSING_PRIOR_ORACLE_MEASUREMENTS",)
        )
        self.assertEqual(
            result.source_lineage,
            (*self.context.input_paths, "governor/inputs/governor_supporting_context.json"),
        )

    def test_legacy_malformed_and_inconsistent_returns_fail_closed(self) -> None:
        for transport in (
            RecordingGovernorTransport(disposition="WATCH_ONLY"),
            RecordingGovernorTransport(malformed=True),
            RecordingGovernorTransport(artifact_mismatch=True),
        ):
            with self.subTest(transport=transport):
                self.clear_outputs()
                result = self.adapter(transport).execute(
                    mission_request(), self.context, supporting_context=self.supporting
                )
                self.assertIs(result.status, StageStatus.FAILED)
                self.assertEqual(result.failure.code, "GOVERNOR_MALFORMED_RESULT")

    def test_technical_exception_and_timeout_are_structured_and_sanitized(self) -> None:
        secret = self.mission_root / "private-context.json"
        failed = self.adapter(
            RecordingGovernorTransport(error=RuntimeError(f"failed reading {secret}"))
        ).execute(mission_request(), self.context, supporting_context=self.supporting)
        self.assertEqual(failed.failure.code, "GOVERNOR_EXECUTION_FAILED")
        self.assertNotIn(str(self.mission_root), failed.failure.message)
        self.assertIn("<redacted-path>", failed.failure.message)

        live = GovernorSupportingContext.from_mapping(supporting_mapping("LIVE"))
        timeout = self.adapter(
            RecordingGovernorTransport(error=GovernorTransportTimeout("expired"))
        ).execute(
            mission_request("LIVE"), self.context, supporting_context=live
        )
        self.assertEqual(timeout.failure.code, "GOVERNOR_TIMEOUT")
        self.assertTrue(timeout.failure.resumable)

    def test_correlation_and_mode_mismatch_never_call_transport(self) -> None:
        transport = RecordingGovernorTransport()
        mismatched = GovernorSupportingContext.from_mapping(
            supporting_mapping(request_id="request-other-001")
        )
        correlation = self.adapter(transport).execute(
            mission_request(), self.context, supporting_context=mismatched
        )
        self.assertEqual(correlation.failure.code, "GOVERNOR_CORRELATION_MISMATCH")
        self.assertEqual(transport.calls, [])

        live = GovernorSupportingContext.from_mapping(supporting_mapping("LIVE"))
        mode = self.adapter(transport).execute(
            mission_request(), self.context, supporting_context=live
        )
        self.assertEqual(mode.failure.code, "GOVERNOR_MODE_MISMATCH")
        self.assertEqual(transport.calls, [])

    def test_live_and_replay_transport_are_explicit_without_fallback(self) -> None:
        replay_transport = RecordingGovernorTransport()
        replay = self.adapter(replay_transport).execute(
            mission_request(), self.context, supporting_context=self.supporting
        )
        self.assertIs(replay.transport, GovernorTransportKind.REPLAY_FIXTURE)
        self.assertEqual(
            replay_transport.calls[0][0].supporting_context["run_mode"], "REPLAY"
        )

        self.clear_outputs()
        live_transport = RecordingGovernorTransport()
        live_context = GovernorSupportingContext.from_mapping(supporting_mapping("LIVE"))
        live = self.adapter(live_transport).execute(
            mission_request("LIVE"), self.context, supporting_context=live_context
        )
        self.assertIs(live.transport, GovernorTransportKind.LIVE_MISSION_INPUTS)
        self.assertEqual(
            live_transport.calls[0][0].supporting_context["run_mode"], "LIVE"
        )

    def test_missing_input_and_existing_output_fail_before_transport(self) -> None:
        transport = RecordingGovernorTransport()
        missing = self.mission_root / self.context.council_summary_path
        missing.unlink()
        result = self.adapter(transport).execute(
            mission_request(), self.context, supporting_context=self.supporting
        )
        self.assertEqual(result.failure.code, "GOVERNOR_INPUT_INVALID")
        self.assertEqual(transport.calls, [])

        missing.write_text("{}\n", encoding="utf-8")
        self.context.output_absolute.mkdir(parents=True)
        sentinel = self.context.output_absolute / "governor_decision.json"
        sentinel.write_text("immutable\n", encoding="utf-8")
        result = self.adapter(transport).execute(
            mission_request(), self.context, supporting_context=self.supporting
        )
        self.assertEqual(result.failure.code, "GOVERNOR_IMMUTABLE_COLLISION")
        self.assertEqual(sentinel.read_text(encoding="utf-8"), "immutable\n")

    def test_context_rejects_path_escape(self) -> None:
        with self.assertRaisesRegex(Exception, "beneath"):
            GovernorMissionContext(
                mission_id=MISSION_ID,
                mission_root=self.mission_root,
                output_dir="../escape",
            )

    def test_native_classifier_preserves_routine_warnings_separately(self) -> None:
        class Diagnostics:
            @staticmethod
            def _is_diagnostic_warning(value: str) -> bool:
                return value != "ROUTINE"

        routine, decision = _classify_oracle_warnings(
            ("ROUTINE", "DEGRADING"), Diagnostics
        )
        self.assertEqual(routine, ("ROUTINE",))
        self.assertEqual(decision, ("DEGRADING",))

    def test_source_has_no_operator_navigator_modeldock_broker_or_provider_calls(self) -> None:
        source = Path(__file__).parents[1] / "src/blackpod_build_week/governor_adapter.py"
        text = source.read_text(encoding="utf-8")
        tree = ast.parse(text)
        imports = {
            alias.name.lower()
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        }
        imports.update(
            node.module.lower()
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module
        )
        for forbidden in (
            "modeldock",
            "blackpod.runtime.governor_decision_consumer",
            "blackpod.runtime.navigator",
            "blackpod.execution",
            "yfinance",
            "alpaca",
        ):
            self.assertFalse(
                any(module == forbidden or module.startswith(f"{forbidden}.") for module in imports)
            )
        forbidden_calls = {
            "consume_run_dir",
            "run_navigator",
            "submit_order",
            "place_order",
            "run_oracle_pipeline",
        }
        calls = {
            node.func.attr
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
        }
        calls.update(
            node.func.id
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        )
        self.assertTrue(forbidden_calls.isdisjoint(calls))


if __name__ == "__main__":
    unittest.main()
