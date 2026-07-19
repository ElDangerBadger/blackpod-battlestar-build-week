from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from blackpod_build_week.contracts import (
    ArtifactReference,
    ComponentProvenance,
    ContractValidationError,
    CouncilComponentProvenance,
    CouncilTransportKind,
    CurrentPhase,
    MissionOutcome,
    MissionRequest,
    MissionSnapshot,
    RunMode,
    StageStatus,
)
from blackpod_build_week.identifiers import allocate_mission_id


def valid_request(**overrides: object) -> dict[str, object]:
    request: dict[str, object] = {
        "schema_version": "blackpod.mission_request.v1",
        "request_id": "request-contract-001",
        "run_mode": "LIVE",
        "symbol": "AAPL",
        "requested_at": "2026-07-18T11:00:00-07:00",
        "operator_id": "operator-001",
        "metadata": {"purpose": "contract-test"},
    }
    request.update(overrides)
    return request


class MissionRequestContractTests(unittest.TestCase):
    def test_valid_live_request(self) -> None:
        request = MissionRequest.from_mapping(valid_request())

        self.assertIs(request.run_mode, RunMode.LIVE)
        self.assertEqual(request.requested_at, "2026-07-18T18:00:00Z")
        self.assertIsNone(request.mission_id)

    def test_valid_replay_request_is_deterministic(self) -> None:
        first = MissionRequest.from_mapping(
            valid_request(
                run_mode="REPLAY",
                metadata={"z": 2, "a": 1},
            )
        )
        second = MissionRequest.from_mapping(
            {
                "metadata": {"a": 1, "z": 2},
                "operator_id": "operator-001",
                "requested_at": "2026-07-18T18:00:00Z",
                "symbol": "AAPL",
                "run_mode": "REPLAY",
                "request_id": "request-contract-001",
                "schema_version": "blackpod.mission_request.v1",
            }
        )

        first_id = allocate_mission_id(
            first.identity_payload(),
            request_id=first.request_id,
            run_mode=first.run_mode.value,
            supplied_mission_id=first.mission_id,
        )
        second_id = allocate_mission_id(
            second.identity_payload(),
            request_id=second.request_id,
            run_mode=second.run_mode.value,
            supplied_mission_id=second.mission_id,
        )

        self.assertEqual(first_id, second_id)
        self.assertTrue(first_id.startswith("mission-replay-"))

    def test_malformed_request_json_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            request_path = Path(temporary_directory) / "request.json"
            request_path.write_text('{"schema_version": ', encoding="utf-8")

            with self.assertRaisesRegex(ContractValidationError, "not valid JSON"):
                MissionRequest.from_file(request_path)

    def test_duplicate_json_fields_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            request_path = Path(temporary_directory) / "request.json"
            request_path.write_text(
                '{"schema_version":"blackpod.mission_request.v1",'
                '"schema_version":"blackpod.mission_request.v1"}',
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ContractValidationError, "duplicate JSON field"):
                MissionRequest.from_file(request_path)

    def test_unsupported_schema_version_is_rejected(self) -> None:
        with self.assertRaisesRegex(ContractValidationError, "unsupported schema_version"):
            MissionRequest.from_mapping(valid_request(schema_version="future.v2"))

    def test_invalid_run_mode_is_rejected_without_coercion(self) -> None:
        for run_mode in ("live", "REPLAY ", "DRY_RUN"):
            with self.subTest(run_mode=run_mode):
                with self.assertRaisesRegex(ContractValidationError, "unsupported run_mode"):
                    MissionRequest.from_mapping(valid_request(run_mode=run_mode))

    def test_malformed_timestamps_are_rejected(self) -> None:
        for timestamp in (
            "2026-07-18",
            "2026-07-18 18:00:00Z",
            "2026-07-18T18:00:00",
            "0001-01-01T00:00:00+14:00",
            "not-a-time",
        ):
            with self.subTest(timestamp=timestamp):
                with self.assertRaises(ContractValidationError):
                    MissionRequest.from_mapping(valid_request(requested_at=timestamp))

    def test_blank_identifiers_and_unknown_fields_are_rejected(self) -> None:
        for field in ("request_id", "operator_id"):
            with self.subTest(field=field):
                with self.assertRaises(ContractValidationError):
                    MissionRequest.from_mapping(valid_request(**{field: "   "}))

        with self.assertRaisesRegex(ContractValidationError, "unknown fields"):
            MissionRequest.from_mapping(valid_request(typo_field=True))

    def test_metadata_is_the_open_extension_point(self) -> None:
        request = MissionRequest.from_mapping(
            valid_request(metadata={"nested": {"free_form": [1, True, None]}})
        )
        self.assertEqual(request.metadata["nested"]["free_form"], [1, True, None])

    def test_non_utf8_unicode_scalar_values_are_rejected_cleanly(self) -> None:
        for overrides in (
            {"symbol": "\ud800"},
            {"metadata": {"invalid": "\ud800"}},
        ):
            with self.subTest(overrides=repr(overrides)):
                with self.assertRaisesRegex(ContractValidationError, "Unicode|UTF-8"):
                    MissionRequest.from_mapping(valid_request(**overrides))


class MissionSnapshotContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.snapshot = MissionSnapshot.create_phase1(
            mission_id="mission-contract-001",
            request_id="request-contract-001",
            run_mode=RunMode.REPLAY,
            started_at="2026-07-18T18:00:00Z",
            observed_at="2026-07-18T18:00:00Z",
            request_artifact=ArtifactReference.from_mapping(
                {
                    "name": "mission_request",
                    "path": "request/mission_request.json",
                    "sha256": "0" * 64,
                }
            ),
        )

    def test_all_stages_are_always_present(self) -> None:
        self.assertEqual(
            set(self.snapshot.stages),
            {"harbormaster", "oracle", "council", "governor", "navigator"},
        )

    def test_phase1_state_derives_incomplete(self) -> None:
        self.assertIs(
            self.snapshot.stages["harbormaster"].status,
            StageStatus.SUCCEEDED,
        )
        self.assertEqual(
            self.snapshot.stages["harbormaster"].native_state,
            "INITIALIZED",
        )
        for stage_name in ("oracle", "council", "governor", "navigator"):
            with self.subTest(stage=stage_name):
                self.assertIs(
                    self.snapshot.stages[stage_name].status,
                    StageStatus.NOT_STARTED,
                )
                self.assertIsNone(self.snapshot.stages[stage_name].native_state)
        self.assertIs(self.snapshot.mission_outcome, MissionOutcome.INCOMPLETE)
        self.assertIs(self.snapshot.current_phase, CurrentPhase.ORACLE)
        self.assertFalse(self.snapshot.terminal)
        self.assertIsNone(self.snapshot.previous_snapshot_sha256)

    def test_snapshot_contract_can_represent_all_outcome_enum_values(self) -> None:
        base = self.snapshot.to_dict()
        for outcome in MissionOutcome:
            with self.subTest(outcome=outcome.value):
                candidate = json.loads(json.dumps(base))
                candidate["mission_outcome"] = outcome.value
                parsed = MissionSnapshot.from_mapping(candidate)
                self.assertIs(parsed.mission_outcome, outcome)

    def test_snapshot_rejects_missing_or_extra_stage(self) -> None:
        missing = self.snapshot.to_dict()
        del missing["stages"]["council"]
        with self.assertRaisesRegex(ContractValidationError, "exactly"):
            MissionSnapshot.from_mapping(missing)

        extra = self.snapshot.to_dict()
        extra["stages"]["operator"] = {
            "status": "NOT_STARTED",
            "native_state": None,
        }
        with self.assertRaisesRegex(ContractValidationError, "exactly"):
            MissionSnapshot.from_mapping(extra)

    def test_snapshot_rejects_unsafe_artifact_path(self) -> None:
        candidate = self.snapshot.to_dict()
        candidate["artifacts"][0]["path"] = "../outside.json"
        with self.assertRaisesRegex(ContractValidationError, "beneath"):
            MissionSnapshot.from_mapping(candidate)

    def test_snapshot_round_trips_oracle_and_council_component_types(self) -> None:
        candidate = self.snapshot.to_dict()
        candidate["components"] = {
            "battlestar": {
                "git_revision": "a" * 40,
                "git_branch": "main",
                "dirty_worktree": False,
                "oracle_entry_point": (
                    "blackpod.runtime.oracle_pipeline.run_oracle_pipeline"
                ),
                "run_mode": "REPLAY",
                "transport": "REPLAY_FIXTURE",
                "replay_fixture_id": "oracle-fixture-v1",
                "replay_fixture_sha256": "b" * 64,
            },
            "battlestar_council": {
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
                "replay_fixture_id": "council-fixture-v1",
                "replay_fixture_sha256": "c" * 64,
            },
        }

        parsed = MissionSnapshot.from_mapping(candidate)

        self.assertIsInstance(parsed.components["battlestar"], ComponentProvenance)
        council = parsed.components["battlestar_council"]
        self.assertIsInstance(council, CouncilComponentProvenance)
        self.assertIs(council.transport, CouncilTransportKind.REPLAY_FIXTURE)
        self.assertEqual(
            council.runtime_validation_entry_point,
            "native.runtime_validation",
        )
        self.assertEqual(council.advisor_health_entry_point, "native.advisor_health")
        self.assertEqual(parsed.to_dict()["components"], candidate["components"])

    def test_council_provenance_enforces_transport_identity_rules(self) -> None:
        base = {
            "git_revision": "a" * 40,
            "git_branch": None,
            "dirty_worktree": True,
            "candidate_entry_point": "native.candidate",
            "senate_review_entry_point": "native.senate_review",
            "senate_deliberation_entry_point": "native.senate_deliberation",
            "mandate_entry_point": "native.mandate",
            "runtime_validation_entry_point": "native.runtime_validation",
            "advisor_health_entry_point": "native.advisor_health",
            "council_synthesis_entry_point": "native.council_synthesis",
            "council_executive_summary_entry_point": "native.council_summary",
            "run_mode": "LIVE",
            "transport": "LIVE_MISSION_INPUTS",
            "replay_fixture_id": None,
            "replay_fixture_sha256": None,
        }
        live = CouncilComponentProvenance.from_mapping(base)
        self.assertIs(live.transport, CouncilTransportKind.LIVE_MISSION_INPUTS)

        invalid = dict(base)
        invalid.update(
            {
                "run_mode": "REPLAY",
                "transport": "REPLAY_FIXTURE",
                "replay_fixture_id": None,
                "replay_fixture_sha256": None,
            }
        )
        with self.assertRaisesRegex(ContractValidationError, "fixture identity"):
            CouncilComponentProvenance.from_mapping(invalid)

    def test_council_component_requires_oracle_and_matching_mission_mode(self) -> None:
        candidate = self.snapshot.to_dict()
        candidate["components"] = {
            "battlestar_council": {
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
                "replay_fixture_id": "fixture-v1",
                "replay_fixture_sha256": "b" * 64,
            }
        }
        with self.assertRaisesRegex(ContractValidationError, "requires Battlestar Oracle"):
            MissionSnapshot.from_mapping(candidate)

        candidate["components"]["battlestar"] = {
            "git_revision": "a" * 40,
            "git_branch": "main",
            "dirty_worktree": False,
            "oracle_entry_point": "native.oracle",
            "run_mode": "LIVE",
            "transport": "LIVE_YFINANCE",
            "replay_fixture_id": None,
            "replay_fixture_sha256": None,
        }
        with self.assertRaisesRegex(ContractValidationError, "run_mode must match"):
            MissionSnapshot.from_mapping(candidate)


if __name__ == "__main__":
    unittest.main()
