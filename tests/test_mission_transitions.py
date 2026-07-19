from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from blackpod_build_week.contracts import (
    ArtifactReference,
    ComponentProvenance,
    CouncilComponentProvenance,
    CurrentPhase,
    GovernorComponentProvenance,
    MissionOutcome,
    MissionRequest,
    OracleTransportKind,
    OperatorRoute,
    RunMode,
    StageError,
    StageStatus,
)
from blackpod_build_week.mission_store import ImmutableArtifactError, MissionStore
from blackpod_build_week.mission_transitions import (
    MissionTransitionError,
    begin_council,
    begin_governor,
    begin_oracle,
    complete_council,
    complete_governor,
    complete_oracle,
    fail_council,
    fail_governor,
    fail_oracle,
)


OBSERVED_AT = "2026-07-18T18:05:00Z"


def request() -> MissionRequest:
    return MissionRequest.from_mapping(
        {
            "schema_version": "blackpod.mission_request.v1",
            "request_id": "request-transition-001",
            "mission_id": "mission-transition-001",
            "run_mode": "REPLAY",
            "symbol": "AAPL",
            "requested_at": OBSERVED_AT,
            "operator_id": "operator-transition",
            "metadata": {},
        }
    )


def provenance() -> ComponentProvenance:
    return ComponentProvenance.from_mapping(
        {
            "git_revision": "a" * 40,
            "git_branch": "main",
            "dirty_worktree": False,
            "oracle_entry_point": (
                "blackpod.runtime.oracle_pipeline.run_oracle_pipeline"
            ),
            "run_mode": "REPLAY",
            "transport": "REPLAY_FIXTURE",
            "replay_fixture_id": "fixture-transition-v1",
            "replay_fixture_sha256": "b" * 64,
        }
    )


def council_provenance() -> CouncilComponentProvenance:
    return CouncilComponentProvenance.from_mapping(
        {
            "git_revision": "a" * 40,
            "git_branch": "main",
            "dirty_worktree": False,
            "candidate_entry_point": "native.candidate",
            "senate_review_entry_point": "native.senate_review",
            "senate_deliberation_entry_point": "native.senate_deliberation",
            "mandate_entry_point": "native.mandate",
            "runtime_validation_entry_point": "native.runtime_validation",
            "advisor_health_entry_point": "native.advisor_health",
            "council_synthesis_entry_point": "native.council_synthesis",
            "council_executive_summary_entry_point": "native.council_summary",
            "run_mode": "REPLAY",
            "transport": "REPLAY_FIXTURE",
            "replay_fixture_id": "council-fixture-transition-v1",
            "replay_fixture_sha256": "c" * 64,
        }
    )


def governor_provenance() -> GovernorComponentProvenance:
    return GovernorComponentProvenance.from_mapping(
        {
            "git_revision": "d" * 40,
            "git_branch": "main",
            "dirty_worktree": False,
            "senate_intake_entry_point": "native.governor_senate_intake",
            "preparation_entry_point": "native.governor_preparation",
            "deliberation_entry_point": "native.governor_deliberation",
            "readiness_entry_point": "native.governor_readiness",
            "rendering_entry_point": "native.governor_rendering",
            "run_mode": "REPLAY",
            "transport": "REPLAY_FIXTURE",
            "replay_fixture_id": "governor-fixture-transition-v1",
            "replay_fixture_sha256": "e" * 64,
        }
    )


def artifact(name: str, path: str, payload: bytes) -> ArtifactReference:
    from blackpod_build_week.hashing import sha256_bytes

    return ArtifactReference.from_mapping(
        {
            "name": name,
            "path": path,
            "sha256": sha256_bytes(payload),
            "producer": "oracle" if path.startswith("oracle/attempt") else "harbormaster",
            "byte_size": len(payload),
            "schema_version": None,
            "observed_at": OBSERVED_AT,
        }
    )


class OracleTransitionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.base = Path(self.temporary_directory.name)
        self.store = MissionStore(self.base / "artifacts")
        mission_request = request()
        self.initialized = self.store.initialize(
            mission_request,
            mission_id=mission_request.mission_id or "",
            started_at=OBSERVED_AT,
            observed_at=OBSERVED_AT,
        )
        self.fleet_payload = b"fleet: deterministic\n"
        self.fixture_payload = b'{"fixture":"deterministic"}\n'
        self.fleet = self.store.write_immutable_artifact(
            mission_request.mission_id or "",
            relative_path="oracle/inputs/oracles_vapors.example.yaml",
            payload=self.fleet_payload,
            name="oracle_fleet_input",
            producer="battlestar",
            schema_version=None,
            observed_at=OBSERVED_AT,
        )
        self.fixture = self.store.write_immutable_artifact(
            mission_request.mission_id or "",
            relative_path="oracle/inputs/oracle_replay_input.json",
            payload=self.fixture_payload,
            name="oracle_replay_input",
            producer="harbormaster",
            schema_version="blackpod.oracle_replay_input.v1",
            observed_at=OBSERVED_AT,
        )

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def running_snapshot(self):
        return begin_oracle(
            self.initialized.snapshot,
            previous_snapshot_sha256=self.initialized.snapshot_sha256,
            observed_at=OBSERVED_AT,
            provenance=provenance(),
            input_artifacts=(self.fleet, self.fixture),
        )

    def test_begin_writes_running_revision_and_preserves_all_stages(self) -> None:
        running = self.running_snapshot()
        digest = self.store.commit_snapshot(self.initialized.paths, running)
        loaded = self.store.load_mission("mission-transition-001")

        self.assertEqual(running.revision, 2)
        self.assertEqual(running.previous_snapshot_sha256, self.initialized.snapshot_sha256)
        self.assertEqual(loaded.current_snapshot_sha256, digest)
        self.assertEqual(loaded.snapshot.stages["oracle"].status, StageStatus.RUNNING)
        self.assertEqual(set(loaded.snapshot.stages), {
            "harbormaster", "oracle", "council", "governor", "navigator"
        })
        for name in ("council", "governor", "navigator"):
            self.assertEqual(loaded.snapshot.stages[name].status, StageStatus.NOT_STARTED)

    def test_success_chains_hash_and_advances_only_to_council(self) -> None:
        running = self.running_snapshot()
        running_digest = self.store.commit_snapshot(self.initialized.paths, running)
        payload = b'{"diagnostics_state":"DEGRADED"}\n'
        path = "oracle/attempt-0001/oracle_report_live.json"
        target = self.initialized.paths.mission_root / path
        target.parent.mkdir(parents=True)
        target.write_bytes(payload)
        output = artifact("oracle_report", path, payload)

        complete = complete_oracle(
            running,
            previous_snapshot_sha256=running_digest,
            observed_at=OBSERVED_AT,
            native_state="DEGRADED",
            output_artifacts=(output,),
        )
        self.store.commit_snapshot(self.initialized.paths, complete)

        self.assertEqual(complete.stages["oracle"].status, StageStatus.SUCCEEDED)
        self.assertEqual(complete.stages["oracle"].native_state, "DEGRADED")
        self.assertEqual(complete.current_phase, CurrentPhase.COUNCIL)
        self.assertEqual(complete.mission_outcome, MissionOutcome.INCOMPLETE)
        self.assertFalse(complete.terminal)
        for name in ("council", "governor", "navigator"):
            self.assertEqual(complete.stages[name].status, StageStatus.NOT_STARTED)

    def test_technical_failure_is_distinct_from_native_state(self) -> None:
        running = self.running_snapshot()
        running_digest = self.store.commit_snapshot(self.initialized.paths, running)
        error = StageError.from_mapping(
            {
                "code": "ORACLE_TIMEOUT",
                "error_type": "DeadlineExceeded",
                "message": "Oracle deadline exceeded",
                "resumable": True,
                "observed_at": OBSERVED_AT,
            }
        )
        failed = fail_oracle(
            running,
            previous_snapshot_sha256=running_digest,
            observed_at=OBSERVED_AT,
            native_state=None,
            error=error,
        )

        self.assertEqual(failed.stages["oracle"].status, StageStatus.FAILED)
        self.assertIsNone(failed.stages["oracle"].native_state)
        self.assertEqual(failed.current_phase, CurrentPhase.ORACLE)
        self.assertEqual(failed.mission_outcome, MissionOutcome.FAILED)
        self.assertFalse(failed.terminal)

    def test_non_resumable_failure_is_terminal(self) -> None:
        running = self.running_snapshot()
        error = StageError.from_mapping(
            {
                "code": "ORACLE_MALFORMED_RESULT",
                "error_type": "ContractValidationError",
                "message": "Oracle returned malformed output",
                "resumable": False,
                "observed_at": OBSERVED_AT,
            }
        )
        failed = fail_oracle(
            running,
            previous_snapshot_sha256="c" * 64,
            observed_at=OBSERVED_AT,
            native_state=None,
            error=error,
        )
        self.assertTrue(failed.terminal)

    def test_duplicate_oracle_start_and_revision_overwrite_are_rejected(self) -> None:
        running = self.running_snapshot()
        self.store.commit_snapshot(self.initialized.paths, running)

        with self.assertRaises(MissionTransitionError):
            begin_oracle(
                running,
                previous_snapshot_sha256="d" * 64,
                observed_at=OBSERVED_AT,
                provenance=provenance(),
                input_artifacts=(self.fleet,),
            )
        with self.assertRaises(ImmutableArtifactError):
            self.store.commit_snapshot(self.initialized.paths, running)


class CouncilTransitionTests(unittest.TestCase):
    oracle_input_names = (
        "oracle_normalized_snapshot",
        "oracle_readiness_report",
        "oracle_report",
        "oracle_assessment",
        "oracle_narrative",
    )

    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.base = Path(self.temporary_directory.name)
        self.store = MissionStore(self.base / "artifacts")
        mission_request = request()
        self.initialized = self.store.initialize(
            mission_request,
            mission_id=mission_request.mission_id or "",
            started_at=OBSERVED_AT,
            observed_at=OBSERVED_AT,
        )
        fleet = self.store.write_immutable_artifact(
            mission_request.mission_id or "",
            relative_path="oracle/inputs/oracles_vapors.example.yaml",
            payload=b"fleet: deterministic\n",
            name="oracle_fleet_input",
            producer="battlestar",
            schema_version=None,
            observed_at=OBSERVED_AT,
        )
        replay = self.store.write_immutable_artifact(
            mission_request.mission_id or "",
            relative_path="oracle/inputs/oracle_replay_input.json",
            payload=b'{"fixture":"deterministic"}\n',
            name="oracle_replay_input",
            producer="harbormaster",
            schema_version="blackpod.oracle_replay_input.v1",
            observed_at=OBSERVED_AT,
        )
        oracle_running = begin_oracle(
            self.initialized.snapshot,
            previous_snapshot_sha256=self.initialized.snapshot_sha256,
            observed_at=OBSERVED_AT,
            provenance=provenance(),
            input_artifacts=(fleet, replay),
        )
        oracle_running_sha = self.store.commit_snapshot(
            self.initialized.paths, oracle_running
        )
        filenames = (
            "fleet-oracles-vapors-example_normalized.json",
            "fleet-oracles-vapors-example_readiness.json",
            "oracle_report_live.json",
            "oracle_assessment_live.json",
            "oracle_narrative_live.json",
        )
        self.oracle_outputs = tuple(
            self.store.write_immutable_artifact(
                mission_request.mission_id or "",
                relative_path=f"oracle/attempt-0001/{filename}",
                payload=(f'{{"artifact":"{name}"}}\n').encode(),
                name=name,
                producer="oracle",
                schema_version=None,
                observed_at=OBSERVED_AT,
            )
            for name, filename in zip(self.oracle_input_names, filenames, strict=True)
        )
        self.oracle_complete = complete_oracle(
            oracle_running,
            previous_snapshot_sha256=oracle_running_sha,
            observed_at=OBSERVED_AT,
            native_state="READY",
            output_artifacts=self.oracle_outputs,
        )
        self.oracle_complete_sha = self.store.commit_snapshot(
            self.initialized.paths, self.oracle_complete
        )
        self.mandate = self.store.write_immutable_artifact(
            mission_request.mission_id or "",
            relative_path="council/inputs/mandate.json",
            payload=b'{"ok":true}\n',
            name="council_mandate_input",
            producer="harbormaster",
            schema_version="blackpod.council_replay_input.v1",
            observed_at=OBSERVED_AT,
        )

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def running_snapshot(self):
        return begin_council(
            self.oracle_complete,
            previous_snapshot_sha256=self.oracle_complete_sha,
            observed_at=OBSERVED_AT,
            provenance=council_provenance(),
            existing_input_names=self.oracle_input_names,
            input_artifacts=(self.mandate,),
        )

    def council_outputs(self):
        values = (
            ("council_synthesis", "council_synthesis.json"),
            ("council_executive_summary", "council_executive_summary.json"),
            ("council_lineage_manifest", "lineage_manifest.json"),
        )
        return tuple(
            self.store.write_immutable_artifact(
                "mission-transition-001",
                relative_path=f"council/attempt-0001/{filename}",
                payload=(f'{{"artifact":"{name}"}}\n').encode(),
                name=name,
                producer="council",
                schema_version=None,
                observed_at=OBSERVED_AT,
            )
            for name, filename in values
        )

    def test_begin_records_running_revision_all_inputs_and_both_components(self) -> None:
        running = self.running_snapshot()
        digest = self.store.commit_snapshot(self.initialized.paths, running)
        loaded = self.store.load_mission("mission-transition-001")

        self.assertEqual(running.revision, 4)
        self.assertEqual(running.previous_snapshot_sha256, self.oracle_complete_sha)
        self.assertEqual(loaded.current_snapshot_sha256, digest)
        self.assertEqual(running.stages["council"].status, StageStatus.RUNNING)
        self.assertEqual(
            running.stages["council"].inputs,
            (*self.oracle_input_names, "council_mandate_input"),
        )
        self.assertEqual(
            set(running.stages),
            {"harbormaster", "oracle", "council", "governor", "navigator"},
        )
        self.assertEqual(running.stages["governor"].status, StageStatus.NOT_STARTED)
        self.assertEqual(running.stages["navigator"].status, StageStatus.NOT_STARTED)
        self.assertEqual(set(running.components), {"battlestar", "battlestar_council"})
        self.assertEqual(
            running.components["battlestar"],
            self.oracle_complete.components["battlestar"],
        )

    def test_begin_reuses_exact_oracle_reference_without_duplicate_artifact(self) -> None:
        running = begin_council(
            self.oracle_complete,
            previous_snapshot_sha256=self.oracle_complete_sha,
            observed_at=OBSERVED_AT,
            provenance=council_provenance(),
            existing_input_names=self.oracle_input_names[1:],
            input_artifacts=(self.oracle_outputs[0], self.mandate),
        )

        self.assertEqual(len(running.artifacts), len(self.oracle_complete.artifacts) + 1)
        self.assertEqual(
            set(running.stages["council"].inputs),
            {*self.oracle_input_names, "council_mandate_input"},
        )

    def test_native_blocked_result_is_technical_success_and_advances(self) -> None:
        running = self.running_snapshot()
        running_sha = self.store.commit_snapshot(self.initialized.paths, running)
        complete = complete_council(
            running,
            previous_snapshot_sha256=running_sha,
            observed_at=OBSERVED_AT,
            native_state="BLOCKED",
            output_artifacts=self.council_outputs(),
        )
        complete_sha = self.store.commit_snapshot(self.initialized.paths, complete)
        loaded = self.store.load_mission("mission-transition-001")

        self.assertEqual(complete.revision, 5)
        self.assertEqual(complete.previous_snapshot_sha256, running_sha)
        self.assertEqual(loaded.current_snapshot_sha256, complete_sha)
        self.assertEqual(complete.stages["council"].status, StageStatus.SUCCEEDED)
        self.assertEqual(complete.stages["council"].native_state, "BLOCKED")
        self.assertEqual(complete.current_phase, CurrentPhase.GOVERNOR)
        self.assertEqual(complete.mission_outcome, MissionOutcome.INCOMPLETE)
        self.assertFalse(complete.terminal)
        self.assertEqual(complete.stages["governor"].status, StageStatus.NOT_STARTED)
        self.assertEqual(complete.stages["navigator"].status, StageStatus.NOT_STARTED)
        self.assertEqual(
            complete.components["battlestar"],
            self.oracle_complete.components["battlestar"],
        )

        with self.assertRaises(ImmutableArtifactError):
            self.store.commit_snapshot(self.initialized.paths, complete)

    def test_technical_failure_preserves_native_state_and_resumability(self) -> None:
        running = self.running_snapshot()
        error = StageError.from_mapping(
            {
                "code": "COUNCIL_MALFORMED_RESULT",
                "error_type": "ContractValidationError",
                "message": "Council returned malformed output",
                "resumable": True,
                "observed_at": OBSERVED_AT,
            }
        )
        failed = fail_council(
            running,
            previous_snapshot_sha256="d" * 64,
            observed_at=OBSERVED_AT,
            native_state="CAUTIOUS",
            error=error,
        )

        self.assertEqual(failed.stages["council"].status, StageStatus.FAILED)
        self.assertEqual(failed.stages["council"].native_state, "CAUTIOUS")
        self.assertEqual(failed.current_phase, CurrentPhase.COUNCIL)
        self.assertEqual(failed.mission_outcome, MissionOutcome.FAILED)
        self.assertFalse(failed.terminal)
        self.assertEqual(failed.stages["governor"].status, StageStatus.NOT_STARTED)
        self.assertEqual(failed.stages["navigator"].status, StageStatus.NOT_STARTED)

        terminal_error = StageError.from_mapping(
            {
                "code": "COUNCIL_UNSAFE_RESULT",
                "error_type": "ContractValidationError",
                "message": "Council output was unsafe",
                "resumable": False,
                "observed_at": OBSERVED_AT,
            }
        )
        terminal = fail_council(
            running,
            previous_snapshot_sha256="e" * 64,
            observed_at=OBSERVED_AT,
            native_state=None,
            error=terminal_error,
        )
        self.assertTrue(terminal.terminal)

    def test_wrong_phase_or_oracle_state_and_repeated_start_are_rejected(self) -> None:
        with self.assertRaisesRegex(MissionTransitionError, "COUNCIL phase"):
            begin_council(
                self.initialized.snapshot,
                previous_snapshot_sha256=self.initialized.snapshot_sha256,
                observed_at=OBSERVED_AT,
                provenance=council_provenance(),
                input_artifacts=(self.mandate,),
            )

        running = self.running_snapshot()
        with self.assertRaisesRegex(MissionTransitionError, "NOT_STARTED"):
            begin_council(
                running,
                previous_snapshot_sha256="f" * 64,
                observed_at=OBSERVED_AT,
                provenance=council_provenance(),
                existing_input_names=self.oracle_input_names,
            )

        wrong_oracle = self.oracle_complete.to_dict()
        wrong_oracle["stages"]["oracle"]["status"] = StageStatus.RUNNING.value
        wrong_oracle["stages"]["oracle"]["native_state"] = None
        from blackpod_build_week.contracts import MissionSnapshot

        with self.assertRaisesRegex(MissionTransitionError, "Oracle must have succeeded"):
            begin_council(
                MissionSnapshot.from_mapping(wrong_oracle),
                previous_snapshot_sha256=self.oracle_complete_sha,
                observed_at=OBSERVED_AT,
                provenance=council_provenance(),
                input_artifacts=(self.mandate,),
            )

    def test_unknown_or_changed_existing_input_is_rejected(self) -> None:
        with self.assertRaisesRegex(MissionTransitionError, "unknown existing artifact"):
            begin_council(
                self.oracle_complete,
                previous_snapshot_sha256=self.oracle_complete_sha,
                observed_at=OBSERVED_AT,
                provenance=council_provenance(),
                existing_input_names=("missing_oracle_artifact",),
            )

        changed = self.oracle_outputs[0].to_dict()
        changed["sha256"] = "f" * 64
        with self.assertRaisesRegex(MissionTransitionError, "metadata changed"):
            begin_council(
                self.oracle_complete,
                previous_snapshot_sha256=self.oracle_complete_sha,
                observed_at=OBSERVED_AT,
                provenance=council_provenance(),
                input_artifacts=(ArtifactReference.from_mapping(changed),),
            )


class GovernorTransitionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.base = Path(self.temporary_directory.name)
        self.store = MissionStore(self.base / "artifacts")
        mission_request = request()
        self.initialized = self.store.initialize(
            mission_request,
            mission_id=mission_request.mission_id or "",
            started_at=OBSERVED_AT,
            observed_at=OBSERVED_AT,
        )
        fleet = self.store.write_immutable_artifact(
            mission_request.mission_id or "",
            relative_path="oracle/inputs/oracles_vapors.example.yaml",
            payload=b"fleet: deterministic\n",
            name="oracle_fleet_input",
            producer="battlestar",
            schema_version=None,
            observed_at=OBSERVED_AT,
        )
        replay = self.store.write_immutable_artifact(
            mission_request.mission_id or "",
            relative_path="oracle/inputs/oracle_replay_input.json",
            payload=b'{"fixture":"deterministic"}\n',
            name="oracle_replay_input",
            producer="harbormaster",
            schema_version="blackpod.oracle_replay_input.v1",
            observed_at=OBSERVED_AT,
        )
        oracle_running = begin_oracle(
            self.initialized.snapshot,
            previous_snapshot_sha256=self.initialized.snapshot_sha256,
            observed_at=OBSERVED_AT,
            provenance=provenance(),
            input_artifacts=(fleet, replay),
        )
        oracle_running_sha = self.store.commit_snapshot(
            self.initialized.paths, oracle_running
        )
        oracle_report = self.store.write_immutable_artifact(
            mission_request.mission_id or "",
            relative_path="oracle/attempt-0001/oracle_report_live.json",
            payload=b'{"report_id":"oracle-report-transition"}\n',
            name="oracle_report",
            producer="oracle",
            schema_version="blackpod.contracts.OracleReport",
            observed_at=OBSERVED_AT,
        )
        oracle_complete = complete_oracle(
            oracle_running,
            previous_snapshot_sha256=oracle_running_sha,
            observed_at=OBSERVED_AT,
            native_state="READY",
            output_artifacts=(oracle_report,),
        )
        oracle_complete_sha = self.store.commit_snapshot(
            self.initialized.paths, oracle_complete
        )
        council_policy = self.store.write_immutable_artifact(
            mission_request.mission_id or "",
            relative_path="council/inputs/council_supporting_input.json",
            payload=b'{"policy":"deterministic"}\n',
            name="council_supporting_input",
            producer="harbormaster",
            schema_version="blackpod.council_supporting_input.v1",
            observed_at=OBSERVED_AT,
        )
        council_running = begin_council(
            oracle_complete,
            previous_snapshot_sha256=oracle_complete_sha,
            observed_at=OBSERVED_AT,
            provenance=council_provenance(),
            existing_input_names=("oracle_report",),
            input_artifacts=(council_policy,),
        )
        council_running_sha = self.store.commit_snapshot(
            self.initialized.paths, council_running
        )
        council_values = (
            ("council_synthesis", "council_synthesis.json"),
            ("council_executive_summary", "council_executive_summary.json"),
            ("council_lineage_manifest", "council_lineage_manifest.json"),
        )
        self.council_outputs = tuple(
            self.store.write_immutable_artifact(
                mission_request.mission_id or "",
                relative_path=f"council/attempt-0001/{filename}",
                payload=(f'{{"artifact":"{name}"}}\n').encode(),
                name=name,
                producer="council",
                schema_version=None,
                observed_at=OBSERVED_AT,
            )
            for name, filename in council_values
        )
        self.council_complete = complete_council(
            council_running,
            previous_snapshot_sha256=council_running_sha,
            observed_at=OBSERVED_AT,
            native_state="ALIGNED",
            output_artifacts=self.council_outputs,
        )
        self.council_complete_sha = self.store.commit_snapshot(
            self.initialized.paths, self.council_complete
        )
        self.context = self.store.write_immutable_artifact(
            mission_request.mission_id or "",
            relative_path="governor/inputs/governor_context.json",
            payload=b'{"context":"deterministic"}\n',
            name="governor_context",
            producer="harbormaster",
            schema_version="blackpod.governor_context.v1",
            observed_at=OBSERVED_AT,
        )

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def running_snapshot(self):
        return begin_governor(
            self.council_complete,
            previous_snapshot_sha256=self.council_complete_sha,
            observed_at=OBSERVED_AT,
            provenance=governor_provenance(),
            existing_input_names=tuple(item.name for item in self.council_outputs),
            input_artifacts=(self.context,),
        )

    def governor_output(self):
        return self.store.write_immutable_artifact(
            "mission-transition-001",
            relative_path="governor/attempt-0001/governor_decision.json",
            payload=b'{"decision_status":"RENDERED"}\n',
            name="governor_rendered_decision",
            producer="governor",
            schema_version="blackpod.contracts.GovernorDecision",
            observed_at=OBSERVED_AT,
        )

    def test_begin_records_running_revision_inputs_and_provenance(self) -> None:
        running = self.running_snapshot()
        digest = self.store.commit_snapshot(self.initialized.paths, running)
        loaded = self.store.load_mission("mission-transition-001")

        self.assertEqual(running.revision, 6)
        self.assertEqual(running.previous_snapshot_sha256, self.council_complete_sha)
        self.assertEqual(loaded.current_snapshot_sha256, digest)
        self.assertEqual(running.stages["governor"].status, StageStatus.RUNNING)
        self.assertEqual(
            set(running.stages["governor"].inputs),
            {
                "council_synthesis",
                "council_executive_summary",
                "council_lineage_manifest",
                "governor_context",
            },
        )
        self.assertEqual(
            set(running.components),
            {"battlestar", "battlestar_council", "battlestar_governor"},
        )
        self.assertIsNone(running.operator.route)
        self.assertEqual(running.stages["navigator"].status, StageStatus.NOT_STARTED)

    def test_all_canonical_dispositions_map_without_operator_action(self) -> None:
        running = self.running_snapshot()
        output = self.governor_output()
        expected = {
            "PROCEED": (
                CurrentPhase.OPERATOR,
                MissionOutcome.HELD,
                False,
                OperatorRoute.PENDING_APPROVAL,
            ),
            "HOLD": (
                CurrentPhase.OPERATOR,
                MissionOutcome.HELD,
                False,
                OperatorRoute.PENDING_REVIEW,
            ),
            "REVIEW_REQUIRED": (
                CurrentPhase.OPERATOR,
                MissionOutcome.HELD,
                False,
                OperatorRoute.PENDING_REVIEW,
            ),
            "BLOCKED": (
                CurrentPhase.GOVERNOR,
                MissionOutcome.HELD,
                True,
                OperatorRoute.CLOSED_BLOCKED,
            ),
            "STAND_DOWN": (
                CurrentPhase.COMPLETE,
                MissionOutcome.VETOED,
                True,
                OperatorRoute.CLOSED_NO_ACTION,
            ),
        }
        for disposition, expected_state in expected.items():
            with self.subTest(disposition=disposition):
                complete = complete_governor(
                    running,
                    previous_snapshot_sha256="f" * 64,
                    observed_at=OBSERVED_AT,
                    native_state=disposition,
                    output_artifacts=(output,),
                )
                phase, outcome, terminal, route = expected_state
                self.assertEqual(complete.current_phase, phase)
                self.assertEqual(complete.mission_outcome, outcome)
                self.assertEqual(complete.terminal, terminal)
                self.assertEqual(complete.operator.route, route)
                self.assertIsNone(complete.operator.action)
                self.assertIsNone(complete.operator.result)
                self.assertIsNone(complete.operator.operator_id)
                self.assertIsNone(complete.operator.acted_at)
                self.assertEqual(
                    complete.stages["navigator"].status,
                    StageStatus.NOT_STARTED,
                )

    def test_proceed_commits_hash_chain_and_revision_is_immutable(self) -> None:
        running = self.running_snapshot()
        running_sha = self.store.commit_snapshot(self.initialized.paths, running)
        complete = complete_governor(
            running,
            previous_snapshot_sha256=running_sha,
            observed_at=OBSERVED_AT,
            native_state="PROCEED",
            output_artifacts=(self.governor_output(),),
        )
        complete_sha = self.store.commit_snapshot(self.initialized.paths, complete)
        loaded = self.store.load_mission("mission-transition-001")

        self.assertEqual(complete.revision, 7)
        self.assertEqual(complete.previous_snapshot_sha256, running_sha)
        self.assertEqual(loaded.current_snapshot_sha256, complete_sha)
        self.assertEqual(complete.stages["governor"].status, StageStatus.SUCCEEDED)
        self.assertEqual(complete.operator.route, OperatorRoute.PENDING_APPROVAL)
        with self.assertRaises(ImmutableArtifactError):
            self.store.commit_snapshot(self.initialized.paths, complete)

    def test_technical_failure_stays_governor_and_preserves_resumability(self) -> None:
        running = self.running_snapshot()
        error = StageError.from_mapping(
            {
                "code": "GOVERNOR_EXECUTION_FAILED",
                "error_type": "FixtureFailure",
                "message": "Governor execution failed",
                "resumable": True,
                "observed_at": OBSERVED_AT,
            }
        )
        failed = fail_governor(
            running,
            previous_snapshot_sha256="f" * 64,
            observed_at=OBSERVED_AT,
            native_state=None,
            error=error,
        )

        self.assertEqual(failed.stages["governor"].status, StageStatus.FAILED)
        self.assertEqual(failed.current_phase, CurrentPhase.GOVERNOR)
        self.assertEqual(failed.mission_outcome, MissionOutcome.FAILED)
        self.assertFalse(failed.terminal)
        self.assertIsNone(failed.operator.route)
        self.assertEqual(failed.stages["navigator"].status, StageStatus.NOT_STARTED)

    def test_legacy_disposition_wrong_phase_and_repeat_are_rejected(self) -> None:
        running = self.running_snapshot()
        with self.assertRaisesRegex(MissionTransitionError, "unsupported"):
            complete_governor(
                running,
                previous_snapshot_sha256="f" * 64,
                observed_at=OBSERVED_AT,
                native_state="WATCH_ONLY",
                output_artifacts=(self.governor_output(),),
            )
        with self.assertRaisesRegex(MissionTransitionError, "NOT_STARTED"):
            begin_governor(
                running,
                previous_snapshot_sha256="f" * 64,
                observed_at=OBSERVED_AT,
                provenance=governor_provenance(),
                existing_input_names=("council_executive_summary",),
            )
        with self.assertRaisesRegex(MissionTransitionError, "GOVERNOR phase"):
            begin_governor(
                self.initialized.snapshot,
                previous_snapshot_sha256=self.initialized.snapshot_sha256,
                observed_at=OBSERVED_AT,
                provenance=governor_provenance(),
                input_artifacts=(self.context,),
            )


if __name__ == "__main__":
    unittest.main()
