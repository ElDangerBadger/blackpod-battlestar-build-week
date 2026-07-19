from __future__ import annotations

import inspect
import json
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

from blackpod_build_week.contracts import (
    ContractValidationError,
    CurrentPhase,
    MissionOutcome,
    MissionRequest,
    MissionSnapshot,
    ModelDockCallStatus,
    OperatorAction,
    OperatorActionStatus,
    OperatorResult,
    RunMode,
    StageStatus,
)
from blackpod_build_week.mission_initialization import (
    ExistingMissionConflictError,
    HarbormasterSettings,
    MissionInitializationAction,
    initialize_or_validate_existing,
)
from blackpod_build_week.hashing import sha256_file
from blackpod_build_week.mission_store import MissionPaths, MissionStore, PersistenceError
import blackpod_build_week.unified_mission_workflow as unified_workflow_module
from blackpod_build_week.unified_mission_workflow import (
    MissionThrough,
    UnifiedMissionAction,
    UnifiedMissionInvocationError,
    UnifiedMissionRunners,
    UnifiedMissionSettings,
    UnifiedMissionStateConflictError,
    resume_unified_mission,
    run_unified_mission,
)


def _request(run_mode: RunMode = RunMode.REPLAY) -> MissionRequest:
    return MissionRequest.from_mapping(
        {
            "schema_version": "blackpod.mission_request.v1",
            "mission_id": "mission-unified-test-001",
            "request_id": "request-unified-test-001",
            "run_mode": run_mode.value,
            "symbol": "AAPL",
            "requested_at": "2026-07-18T18:05:00Z",
            "operator_id": "request-operator",
            "metadata": {},
        }
    )


def _stage(status: StageStatus, native_state=None, *, calls=()):
    return SimpleNamespace(
        status=status,
        native_state=native_state,
        modeldock_calls=tuple(calls),
    )


def _operator():
    return SimpleNamespace(
        action_status=OperatorActionStatus.NOT_STARTED,
        action=None,
        result=None,
        operator_id=None,
    )


class FakeScenario:
    def __init__(
        self,
        base: Path,
        *,
        run_mode: RunMode = RunMode.REPLAY,
        governor_state: str = "PROCEED",
        navigator_fails: bool = False,
    ) -> None:
        self.base = base
        self.request = _request(run_mode)
        mission_root = base / "missions" / (self.request.mission_id or "")
        self.paths = MissionPaths(
            mission_root=mission_root,
            request_path=mission_root / "request/mission_request.json",
            snapshots_dir=mission_root / "snapshots",
            revision_snapshot=mission_root
            / "snapshots/mission_snapshot-r0001.json",
            current_snapshot=mission_root / "mission_snapshot.json",
        )
        self.snapshot = SimpleNamespace(
            mission_id=self.request.mission_id,
            request_id=self.request.request_id,
            run_mode=self.request.run_mode,
            current_phase=CurrentPhase.ORACLE,
            mission_outcome=MissionOutcome.INCOMPLETE,
            terminal=False,
            revision=1,
            stages={
                "harbormaster": _stage(StageStatus.SUCCEEDED, "INITIALIZED"),
                "oracle": _stage(StageStatus.NOT_STARTED),
                "council": _stage(StageStatus.NOT_STARTED),
                "governor": _stage(StageStatus.NOT_STARTED),
                "navigator": _stage(StageStatus.NOT_STARTED),
            },
            operator=_operator(),
            artifacts=(),
            components={},
        )
        self.governor_state = governor_state
        self.navigator_fails = navigator_fails
        self.calls: list[str] = []
        self.presentation_calls = 0
        self.initialization_action = MissionInitializationAction.INITIALIZED

    def loaded(self, _store, _mission_id):
        return SimpleNamespace(
            request=self.request,
            snapshot=self.snapshot,
            paths=self.paths,
            current_snapshot_sha256="0" * 64,
        )

    def initialize(self, _settings, _now):
        return SimpleNamespace(
            request=self.request,
            snapshot=self.snapshot,
            paths=self.paths,
            snapshot_sha256="0" * 64,
            action=self.initialization_action,
        )

    @staticmethod
    def _result():
        return SimpleNamespace(action=SimpleNamespace(value="EXECUTED"))

    def _record_input(self, name: str, path: Path | None) -> None:
        if path is None:
            return
        artifact = SimpleNamespace(name=name, sha256=sha256_file(path))
        existing = {
            item.name: item for item in getattr(self.snapshot, "artifacts", ())
        }
        existing[name] = artifact
        self.snapshot.artifacts = tuple(existing.values())

    def oracle(self, settings, _environ):
        self.calls.append("oracle")
        self.assert_common(settings)
        self._record_input("oracle_replay_input", settings.replay_fixture)
        self.snapshot.stages["oracle"] = _stage(StageStatus.SUCCEEDED, "READY")
        self.snapshot.current_phase = CurrentPhase.COUNCIL
        self.snapshot.revision += 2
        return self._result()

    def enrichment(self, settings, _environ):
        self.calls.append("modeldock")
        self.assert_common(settings)
        if settings.replay_fixture is not None:
            self.snapshot.components["modeldock"] = SimpleNamespace(
                replay_fixture_sha256=sha256_file(settings.replay_fixture)
            )
        call = SimpleNamespace(status=ModelDockCallStatus.SUCCEEDED)
        self.snapshot.stages["oracle"] = _stage(
            StageStatus.SUCCEEDED, "READY", calls=(call,)
        )
        self.snapshot.revision += 2
        return self._result()

    def council(self, settings, _environ):
        self.calls.append("council")
        self.assert_common(settings)
        self._record_input(
            "council_supporting_input",
            settings.replay_fixture or settings.policy_input,
        )
        self.snapshot.stages["council"] = _stage(
            StageStatus.SUCCEEDED, "ALIGNED"
        )
        self.snapshot.current_phase = CurrentPhase.GOVERNOR
        self.snapshot.revision += 2
        return self._result()

    def governor(self, settings, _environ):
        self.calls.append("governor")
        self.assert_common(settings)
        self._record_input(
            "governor_supporting_context",
            settings.replay_fixture or settings.context_input,
        )
        self.snapshot.stages["governor"] = _stage(
            StageStatus.SUCCEEDED, self.governor_state
        )
        self.snapshot.revision += 2
        if self.governor_state == "PROCEED":
            self.snapshot.current_phase = CurrentPhase.OPERATOR
            self.snapshot.mission_outcome = MissionOutcome.HELD
        elif self.governor_state in {"HOLD", "REVIEW_REQUIRED"}:
            self.snapshot.current_phase = CurrentPhase.OPERATOR
            self.snapshot.mission_outcome = MissionOutcome.HELD
        elif self.governor_state == "STAND_DOWN":
            self.snapshot.current_phase = CurrentPhase.COMPLETE
            self.snapshot.mission_outcome = MissionOutcome.VETOED
            self.snapshot.terminal = True
        else:
            self.snapshot.current_phase = CurrentPhase.GOVERNOR
            self.snapshot.mission_outcome = MissionOutcome.HELD
            self.snapshot.terminal = True
        return self._result()

    def operator(self, settings, _environ):
        self.calls.append("operator")
        self.assert_common(settings)
        self._record_input("operator_replay_action", settings.replay_fixture)
        action = (
            settings.action
            if isinstance(settings.action, OperatorAction)
            else OperatorAction(settings.action)
        )
        result = (
            OperatorResult.APPROVED_FOR_HANDOFF
            if action is OperatorAction.APPROVE_HANDOFF
            else OperatorResult.REJECTED
        )
        self.snapshot.operator = SimpleNamespace(
            action_status=OperatorActionStatus.SUCCEEDED,
            action=action,
            result=result,
            operator_id=settings.operator_id,
        )
        self.snapshot.revision += 2
        if result is OperatorResult.APPROVED_FOR_HANDOFF:
            self.snapshot.current_phase = CurrentPhase.NAVIGATOR
            self.snapshot.mission_outcome = MissionOutcome.HELD
        else:
            self.snapshot.current_phase = CurrentPhase.COMPLETE
            self.snapshot.mission_outcome = MissionOutcome.VETOED
            self.snapshot.terminal = True
        return self._result()

    def navigator(self, settings, _environ):
        self.calls.append("navigator")
        self.assert_common(settings)
        self._record_input("navigator_replay_input", settings.replay_fixture)
        self.snapshot.revision += 2
        if self.navigator_fails:
            self.snapshot.stages["navigator"] = _stage(
                StageStatus.FAILED, "REJECTED"
            )
            self.snapshot.current_phase = CurrentPhase.NAVIGATOR
            self.snapshot.mission_outcome = MissionOutcome.FAILED
            self.snapshot.terminal = True
        else:
            self.snapshot.stages["navigator"] = _stage(
                StageStatus.SUCCEEDED, "CREATED"
            )
            self.snapshot.current_phase = CurrentPhase.COMPLETE
            self.snapshot.mission_outcome = MissionOutcome.APPROVED
            self.snapshot.terminal = True
        return self._result()

    def modeldock_config(self, _environ):
        self.calls.append("modeldock-config")
        return object()

    def preflight(self, _config):
        self.calls.append("modeldock-preflight")
        return SimpleNamespace(ready=True)

    def presentation(self, _store, loaded):
        self.presentation_calls += 1
        return {"outcome": loaded.snapshot.mission_outcome.value}

    def assert_common(self, settings):
        if settings.mission_id != self.request.mission_id:
            raise AssertionError("runner correlation mismatch")

    def runners(self) -> UnifiedMissionRunners:
        return UnifiedMissionRunners(
            initializer=self.initialize,
            loader=self.loaded,
            oracle=self.oracle,
            enrichment=self.enrichment,
            council=self.council,
            governor=self.governor,
            operator=self.operator,
            navigator=self.navigator,
            modeldock_config_loader=self.modeldock_config,
            modeldock_preflight=self.preflight,
            presentation_renderer=self.presentation,
        )


def _settings(
    base: Path,
    *,
    with_modeldock: bool,
    through: MissionThrough = MissionThrough.NAVIGATOR,
    request: bool = True,
    action: str = "APPROVE_HANDOFF",
    live: bool = False,
) -> UnifiedMissionSettings:
    needs_operator = through in {MissionThrough.OPERATOR, MissionThrough.NAVIGATOR}
    input_paths = {
        name: base / f"{name}.json"
        for name in ("oracle", "modeldock", "council", "governor", "operator", "navigator")
    }
    for name, path in input_paths.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            path.write_bytes(f"{name}-fixture-v1\n".encode("utf-8"))
    return UnifiedMissionSettings(
        artifacts_root=base,
        with_modeldock=with_modeldock,
        request_path=base / "request.json" if request else None,
        mission_id=None if request else "mission-unified-test-001",
        through=through,
        operator_action=action if needs_operator else None,
        operator_id="demo-operator" if needs_operator else None,
        operator_reason=(
            "Explicit deterministic handoff decision." if needs_operator else None
        ),
        expires_in_minutes=120 if live and needs_operator else None,
        oracle_replay_fixture=None if live else input_paths["oracle"],
        modeldock_replay_fixture=(
            input_paths["modeldock"] if with_modeldock and not live else None
        ),
        council_replay_fixture=None if live else input_paths["council"],
        council_policy_input=input_paths["council"] if live else None,
        governor_replay_fixture=None if live else input_paths["governor"],
        governor_context_input=input_paths["governor"] if live else None,
        operator_replay_fixture=(
            input_paths["operator"] if needs_operator and not live else None
        ),
        navigator_replay_fixture=None if live else input_paths["navigator"],
    )


class UnifiedMissionWorkflowTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)

    def test_modeldock_enabled_approved_replay_uses_existing_stages(self) -> None:
        scenario = FakeScenario(self.base)
        result = run_unified_mission(
            _settings(self.base, with_modeldock=True),
            runners=scenario.runners(),
        )
        self.assertEqual(
            scenario.calls,
            ["oracle", "modeldock", "council", "governor", "operator", "navigator"],
        )
        self.assertEqual(result.snapshot.mission_outcome, MissionOutcome.APPROVED)
        self.assertEqual(result.action, UnifiedMissionAction.EXECUTED)
        self.assertTrue(result.technical_success)
        self.assertFalse(result.stopped)
        self.assertEqual(result.snapshot.revision, 13)
        self.assertNotIn("modeldock-preflight", scenario.calls)

    def test_without_modeldock_never_loads_or_invokes_it(self) -> None:
        scenario = FakeScenario(self.base)
        result = run_unified_mission(
            _settings(self.base, with_modeldock=False), runners=scenario.runners()
        )
        self.assertEqual(
            scenario.calls,
            ["oracle", "council", "governor", "operator", "navigator"],
        )
        self.assertEqual(result.snapshot.revision, 11)

    def test_stop_after_council_then_resume_skips_completed_stages(self) -> None:
        scenario = FakeScenario(self.base)
        stopped = run_unified_mission(
            _settings(
                self.base,
                with_modeldock=True,
                through=MissionThrough.COUNCIL,
            ),
            runners=scenario.runners(),
        )
        self.assertEqual(stopped.action, UnifiedMissionAction.STOPPED)
        self.assertTrue(stopped.stopped)
        self.assertEqual(scenario.calls, ["oracle", "modeldock", "council"])

        resumed = resume_unified_mission(
            _settings(self.base, with_modeldock=True, request=False),
            runners=scenario.runners(),
        )
        self.assertEqual(
            scenario.calls,
            [
                "oracle",
                "modeldock",
                "council",
                "governor",
                "operator",
                "navigator",
            ],
        )
        self.assertEqual(resumed.snapshot.mission_outcome, MissionOutcome.APPROVED)

    def test_each_supported_stop_is_inclusive_and_resumable(self) -> None:
        cases = (
            (MissionThrough.ORACLE, ["oracle", "modeldock"], 5),
            (MissionThrough.COUNCIL, ["oracle", "modeldock", "council"], 7),
            (
                MissionThrough.GOVERNOR,
                ["oracle", "modeldock", "council", "governor"],
                9,
            ),
            (
                MissionThrough.OPERATOR,
                ["oracle", "modeldock", "council", "governor", "operator"],
                11,
            ),
        )
        for target, expected_calls, revision in cases:
            with self.subTest(target=target.value):
                base = self.base / target.value.lower()
                scenario = FakeScenario(base)
                stopped = run_unified_mission(
                    _settings(base, with_modeldock=True, through=target),
                    runners=scenario.runners(),
                )
                self.assertEqual(scenario.calls, expected_calls)
                self.assertEqual(stopped.snapshot.revision, revision)
                self.assertTrue(stopped.stopped)
                resumed = resume_unified_mission(
                    _settings(base, with_modeldock=True, request=False),
                    runners=scenario.runners(),
                )
                self.assertEqual(resumed.snapshot.mission_outcome, MissionOutcome.APPROVED)
                self.assertEqual(scenario.calls[: len(expected_calls)], expected_calls)

    def test_resume_after_oracle_and_pending_operator_do_not_rerun_history(self) -> None:
        after_oracle = FakeScenario(self.base / "after-oracle")
        run_unified_mission(
            _settings(
                after_oracle.base,
                with_modeldock=False,
                through=MissionThrough.ORACLE,
            ),
            runners=after_oracle.runners(),
        )
        resume_unified_mission(
            _settings(after_oracle.base, with_modeldock=False, request=False),
            runners=after_oracle.runners(),
        )
        self.assertEqual(after_oracle.calls.count("oracle"), 1)

        pending = FakeScenario(self.base / "pending")
        run_unified_mission(
            _settings(
                pending.base,
                with_modeldock=False,
                through=MissionThrough.GOVERNOR,
            ),
            runners=pending.runners(),
        )
        self.assertEqual(pending.calls, ["oracle", "council", "governor"])
        resume_unified_mission(
            _settings(pending.base, with_modeldock=False, request=False),
            runners=pending.runners(),
        )
        self.assertEqual(pending.calls.count("governor"), 1)
        self.assertEqual(pending.calls[-2:], ["operator", "navigator"])

    def test_non_proceed_governor_never_invokes_operator_or_navigator(self) -> None:
        scenario = FakeScenario(self.base, governor_state="HOLD")
        result = run_unified_mission(
            _settings(self.base, with_modeldock=False), runners=scenario.runners()
        )
        self.assertEqual(scenario.calls, ["oracle", "council", "governor"])
        self.assertEqual(result.snapshot.mission_outcome, MissionOutcome.HELD)
        self.assertTrue(result.technical_success)

    def test_reject_is_vetoed_without_navigator(self) -> None:
        scenario = FakeScenario(self.base)
        result = run_unified_mission(
            _settings(
                self.base,
                with_modeldock=False,
                through=MissionThrough.OPERATOR,
                action="REJECT",
            ),
            runners=scenario.runners(),
        )
        self.assertEqual(
            scenario.calls, ["oracle", "council", "governor", "operator"]
        )
        self.assertEqual(result.snapshot.mission_outcome, MissionOutcome.VETOED)
        self.assertEqual(result.action, UnifiedMissionAction.EXECUTED)
        self.assertFalse(result.stopped)
        self.assertNotIn("navigator", scenario.calls)

    def test_oracle_stop_is_explicitly_incomplete(self) -> None:
        scenario = FakeScenario(self.base)
        result = run_unified_mission(
            _settings(
                self.base,
                with_modeldock=True,
                through=MissionThrough.ORACLE,
            ),
            runners=scenario.runners(),
        )
        self.assertEqual(result.action, UnifiedMissionAction.STOPPED)
        self.assertTrue(result.stopped)
        self.assertEqual(result.snapshot.current_phase, CurrentPhase.COUNCIL)
        self.assertEqual(result.snapshot.mission_outcome, MissionOutcome.INCOMPLETE)
        self.assertFalse(result.snapshot.terminal)

    def test_controlled_navigator_failure_returns_typed_failure(self) -> None:
        scenario = FakeScenario(self.base, navigator_fails=True)
        result = run_unified_mission(
            _settings(self.base, with_modeldock=False), runners=scenario.runners()
        )
        self.assertEqual(result.action, UnifiedMissionAction.FAILED)
        self.assertFalse(result.technical_success)
        self.assertEqual(result.snapshot.mission_outcome, MissionOutcome.FAILED)
        self.assertEqual(scenario.presentation_calls, 1)

    def test_live_modeldock_requires_deep_preflight(self) -> None:
        scenario = FakeScenario(self.base, run_mode=RunMode.LIVE)
        result = run_unified_mission(
            _settings(self.base, with_modeldock=True, live=True),
            runners=scenario.runners(),
        )
        self.assertTrue(result.technical_success)
        self.assertEqual(
            scenario.calls[:4],
            ["oracle", "modeldock-config", "modeldock-preflight", "modeldock"],
        )

        unavailable = FakeScenario(self.base / "unavailable", run_mode=RunMode.LIVE)
        runners = unavailable.runners()
        runners = UnifiedMissionRunners(
            **{
                name: getattr(runners, name)
                for name in runners.__dataclass_fields__
                if name != "modeldock_preflight"
            },
            modeldock_preflight=lambda _config: SimpleNamespace(ready=False),
        )
        with self.assertRaisesRegex(
            UnifiedMissionStateConflictError, "preflight is not ready"
        ):
            run_unified_mission(
                _settings(unavailable.base, with_modeldock=True, live=True),
                runners=runners,
            )
        self.assertNotIn("modeldock", unavailable.calls)

    def test_mode_history_and_conflicting_operator_action_fail_closed(self) -> None:
        scenario = FakeScenario(self.base)
        run_unified_mission(
            _settings(self.base, with_modeldock=True), runners=scenario.runners()
        )
        with self.assertRaisesRegex(
            UnifiedMissionStateConflictError, "without-modeldock"
        ):
            resume_unified_mission(
                _settings(self.base, with_modeldock=False, request=False),
                runners=scenario.runners(),
            )

        historical_without = FakeScenario(self.base / "historical-without")
        historical_without.snapshot.stages["oracle"] = _stage(
            StageStatus.SUCCEEDED, "READY"
        )
        historical_without.snapshot.stages["council"] = _stage(
            StageStatus.SUCCEEDED, "ALIGNED"
        )
        historical_without.snapshot.current_phase = CurrentPhase.GOVERNOR
        with self.assertRaisesRegex(
            UnifiedMissionStateConflictError, "after Council has started"
        ):
            resume_unified_mission(
                _settings(
                    historical_without.base,
                    with_modeldock=True,
                    request=False,
                ),
                runners=historical_without.runners(),
            )
        with self.assertRaisesRegex(
            UnifiedMissionStateConflictError, "operator action conflicts"
        ):
            resume_unified_mission(
                _settings(
                    self.base,
                    with_modeldock=True,
                    request=False,
                    action="REJECT",
                ),
                runners=scenario.runners(),
            )

    def test_completed_identical_resume_is_no_op(self) -> None:
        scenario = FakeScenario(self.base)
        run_unified_mission(
            _settings(self.base, with_modeldock=False), runners=scenario.runners()
        )
        before = list(scenario.calls)
        repeated = resume_unified_mission(
            _settings(self.base, with_modeldock=False, request=False),
            runners=scenario.runners(),
        )
        self.assertEqual(scenario.calls, before)
        self.assertEqual(
            repeated.action, UnifiedMissionAction.NO_OP_ALREADY_SATISFIED
        )
        self.assertTrue(repeated.no_op)

    def test_repeated_identical_full_mission_command_is_no_op(self) -> None:
        scenario = FakeScenario(self.base)
        settings = _settings(self.base, with_modeldock=True)
        first = run_unified_mission(settings, runners=scenario.runners())
        before = list(scenario.calls)
        scenario.initialization_action = (
            MissionInitializationAction.NO_OP_EXISTING_VALIDATED
        )

        repeated = run_unified_mission(settings, runners=scenario.runners())

        self.assertEqual(first.snapshot.mission_outcome, MissionOutcome.APPROVED)
        self.assertEqual(scenario.calls, before)
        self.assertEqual(
            repeated.action, UnifiedMissionAction.NO_OP_ALREADY_SATISFIED
        )
        self.assertTrue(repeated.no_op)

    def test_completed_modeldock_fixture_must_match_recorded_provenance(self) -> None:
        scenario = FakeScenario(self.base)
        run_unified_mission(
            _settings(self.base, with_modeldock=True), runners=scenario.runners()
        )
        resumed = _settings(self.base, with_modeldock=True, request=False)
        self.assertIsNotNone(resumed.modeldock_replay_fixture)
        resumed.modeldock_replay_fixture.write_bytes(b"conflicting-modeldock-pack\n")
        with self.assertRaisesRegex(
            UnifiedMissionStateConflictError,
            "ModelDock replay fixture conflicts",
        ):
            resume_unified_mission(resumed, runners=scenario.runners())

    def test_completed_stage_fixture_conflicts_but_omitted_history_is_allowed(self) -> None:
        scenario = FakeScenario(self.base)
        run_unified_mission(
            _settings(self.base, with_modeldock=False), runners=scenario.runners()
        )
        resumed = _settings(self.base, with_modeldock=False, request=False)
        self.assertIsNotNone(resumed.council_replay_fixture)
        resumed.council_replay_fixture.write_bytes(b"conflicting-council-input\n")
        with self.assertRaisesRegex(
            UnifiedMissionStateConflictError, "Council input conflicts"
        ):
            resume_unified_mission(resumed, runners=scenario.runners())

        omitted = replace(
            resumed,
            oracle_replay_fixture=None,
            council_replay_fixture=None,
            governor_replay_fixture=None,
            operator_replay_fixture=None,
            navigator_replay_fixture=None,
        )
        result = resume_unified_mission(omitted, runners=scenario.runners())
        self.assertEqual(result.action, UnifiedMissionAction.NO_OP_ALREADY_SATISFIED)

    def test_operator_boundary_and_disabled_fixture_are_explicit(self) -> None:
        with self.assertRaisesRegex(
            UnifiedMissionInvocationError, "explicit supported operator action"
        ):
            run_unified_mission(
                UnifiedMissionSettings(
                    artifacts_root=self.base,
                    request_path=self.base / "request.json",
                    with_modeldock=False,
                    through=MissionThrough.NAVIGATOR,
                )
            )

    def test_interrupted_running_state_is_not_silently_resumed(self) -> None:
        scenario = FakeScenario(self.base)
        scenario.snapshot.stages["oracle"] = _stage(StageStatus.RUNNING)
        with self.assertRaisesRegex(
            UnifiedMissionStateConflictError, "interrupted RUNNING"
        ):
            resume_unified_mission(
                _settings(
                    self.base,
                    with_modeldock=False,
                    through=MissionThrough.ORACLE,
                    request=False,
                ),
                runners=scenario.runners(),
            )

    def test_orchestrator_source_has_no_broker_or_order_execution_path(self) -> None:
        source = inspect.getsource(unified_workflow_module).lower()
        for forbidden in (
            "submit_order",
            "cancel_order",
            "modify_portfolio",
            "broker_call",
            "alpaca",
            "robinhood",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, source)
        with self.assertRaisesRegex(
            UnifiedMissionInvocationError, "forbids a ModelDock replay fixture"
        ):
            run_unified_mission(
                UnifiedMissionSettings(
                    artifacts_root=self.base,
                    request_path=self.base / "request.json",
                    with_modeldock=False,
                    through=MissionThrough.ORACLE,
                    modeldock_replay_fixture=self.base / "modeldock.json",
                )
            )


class MissionInitializationTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        self.request_path = self.base / "request.json"
        self.request_path.write_text(
            json.dumps(_request().to_dict()) + "\n", encoding="utf-8"
        )
        self.settings = HarbormasterSettings(
            request_path=self.request_path,
            artifacts_root=self.base / "artifacts",
        )

    def test_identical_existing_initialization_is_verified_no_op(self) -> None:
        first = initialize_or_validate_existing(self.settings)
        second = initialize_or_validate_existing(self.settings)
        self.assertEqual(first.action, MissionInitializationAction.INITIALIZED)
        self.assertEqual(
            second.action, MissionInitializationAction.NO_OP_EXISTING_VALIDATED
        )
        self.assertEqual(first.snapshot_sha256, second.snapshot_sha256)
        self.assertEqual(second.snapshot.revision, 1)

    def test_same_mission_id_with_different_request_is_conflict(self) -> None:
        initialize_or_validate_existing(self.settings)
        payload = _request().to_dict()
        payload["symbol"] = "MSFT"
        self.request_path.write_text(json.dumps(payload) + "\n", encoding="utf-8")
        with self.assertRaises(ExistingMissionConflictError):
            initialize_or_validate_existing(self.settings)

    def test_existing_chain_is_validated_before_no_op(self) -> None:
        initialized = initialize_or_validate_existing(self.settings)
        initialized.paths.current_snapshot.write_text("{}\n", encoding="utf-8")
        with self.assertRaises(ContractValidationError):
            initialize_or_validate_existing(self.settings)

    def test_resume_rejects_corrupted_artifact_before_stage_execution(self) -> None:
        initialized = initialize_or_validate_existing(self.settings)
        initialized.paths.request_path.write_bytes(
            initialized.paths.request_path.read_bytes() + b" "
        )
        called = False

        def forbidden_oracle(_settings, _environ):
            nonlocal called
            called = True
            raise AssertionError("Oracle must not run after integrity failure")

        runners = UnifiedMissionRunners(oracle=forbidden_oracle)
        with self.assertRaisesRegex(PersistenceError, "artifact hash mismatch"):
            resume_unified_mission(
                UnifiedMissionSettings(
                    mission_id=initialized.request.mission_id,
                    artifacts_root=self.settings.artifacts_root,
                    with_modeldock=False,
                    through=MissionThrough.ORACLE,
                    oracle_replay_fixture=Path("fixtures/oracle_replay_quotes.v1.json"),
                ),
                runners=runners,
            )
        self.assertFalse(called)

    def test_resume_rejects_broken_snapshot_chain_before_stage_execution(self) -> None:
        initialized = initialize_or_validate_existing(self.settings)
        revision_two = initialized.snapshot.to_dict()
        revision_two.update(
            {
                "snapshot_id": f"{initialized.snapshot.mission_id}-r0002",
                "revision": 2,
                "previous_snapshot_sha256": initialized.snapshot_sha256,
            }
        )
        MissionStore(self.settings.artifacts_root).commit_snapshot(
            initialized.paths,
            MissionSnapshot.from_mapping(revision_two),
        )
        initialized.paths.revision_snapshot.write_bytes(
            initialized.paths.revision_snapshot.read_bytes() + b" "
        )
        called = False

        def forbidden_oracle(_settings, _environ):
            nonlocal called
            called = True
            raise AssertionError("Oracle must not run after chain failure")

        with self.assertRaisesRegex(PersistenceError, "hash chain is invalid"):
            resume_unified_mission(
                UnifiedMissionSettings(
                    mission_id=initialized.request.mission_id,
                    artifacts_root=self.settings.artifacts_root,
                    with_modeldock=False,
                    through=MissionThrough.ORACLE,
                    oracle_replay_fixture=Path("fixtures/oracle_replay_quotes.v1.json"),
                ),
                runners=UnifiedMissionRunners(oracle=forbidden_oracle),
            )
        self.assertFalse(called)


if __name__ == "__main__":
    unittest.main()
