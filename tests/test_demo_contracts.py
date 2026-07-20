from __future__ import annotations

import copy
import unittest

from blackpod_build_week.contracts import (
    CAPTAINS_LOG_SCHEMA_VERSION,
    DEMO_MANIFEST_SCHEMA_VERSION,
    MISSION_SNAPSHOT_SCHEMA_VERSION,
    MISSION_SUMMARY_SCHEMA_VERSION,
    NAVIGATOR_ALLOWED_OPERATIONS,
    NAVIGATOR_PROHIBITED_OPERATIONS,
    SHADOW_ONLY_DECLARATION,
    ContractValidationError,
    DemoManifest,
    DemoModelDockMode,
    DemoScenario,
)


OBSERVED_AT = "2026-07-19T20:00:00Z"


def artifact(
    name: str, path: str, schema_version: str, digest_character: str
) -> dict[str, object]:
    return {
        "name": name,
        "path": path,
        "sha256": digest_character * 64,
        "producer": "harbormaster",
        "byte_size": 128,
        "schema_version": schema_version,
        "observed_at": OBSERVED_AT,
    }


def manifest_mapping() -> dict[str, object]:
    return {
        "schema_version": DEMO_MANIFEST_SCHEMA_VERSION,
        "demo_scenario": "approved",
        "mission_id": "mission-demo-approved-001",
        "symbol": "AAPL",
        "run_mode": "REPLAY",
        "build_week_revision": "a" * 40,
        "battlestar_revision": "b" * 40,
        "modeldock_mode": "REPLAYED",
        "modeldock_revision_or_service_identity": "fixture:modeldock-demo-v1",
        "modeldock_provider": "mlx",
        "modeldock_model": "mlx-community/BlackPod-Narrative-Demo",
        "modeldock_trace_id": "trace-modeldock-replay-001",
        "final_outcome": "APPROVED",
        "snapshot_count": 13,
        "captains_log": artifact(
            "captains_log",
            "presentation/captains_log.json",
            CAPTAINS_LOG_SCHEMA_VERSION,
            "c",
        ),
        "mission_summary": artifact(
            "mission_summary",
            "presentation/mission_summary.json",
            MISSION_SUMMARY_SCHEMA_VERSION,
            "d",
        ),
        "final_snapshot": artifact(
            "mission_snapshot",
            "mission_snapshot.json",
            MISSION_SNAPSHOT_SCHEMA_VERSION,
            "e",
        ),
        "generated_at": OBSERVED_AT,
        "shadow_only_declaration": SHADOW_ONLY_DECLARATION,
        "allowed_operations": list(NAVIGATOR_ALLOWED_OPERATIONS),
        "prohibited_operations": list(NAVIGATOR_PROHIBITED_OPERATIONS),
    }


class DemoManifestContractTests(unittest.TestCase):
    def test_round_trip_is_strict_portable_and_shadow_only(self) -> None:
        manifest = DemoManifest.from_mapping(manifest_mapping())

        self.assertEqual(manifest.schema_version, DEMO_MANIFEST_SCHEMA_VERSION)
        self.assertIs(manifest.demo_scenario, DemoScenario.APPROVED)
        self.assertIs(manifest.modeldock_mode, DemoModelDockMode.REPLAYED)
        self.assertEqual(manifest.to_dict(), manifest_mapping())
        self.assertEqual(manifest.allowed_operations, ("VALIDATE", "PLAN_ONLY"))
        self.assertEqual(
            manifest.prohibited_operations,
            ("SUBMIT_ORDER", "CANCEL_ORDER", "MODIFY_PORTFOLIO", "BROKER_CALL"),
        )
        for reference in (
            manifest.captains_log,
            manifest.mission_summary,
            manifest.final_snapshot,
        ):
            self.assertFalse(reference.path.startswith("/"))
            self.assertIsNotNone(reference.byte_size)
            self.assertIsNotNone(reference.observed_at)

    def test_all_canonical_scenarios_are_representable(self) -> None:
        for scenario in DemoScenario:
            with self.subTest(scenario=scenario.value):
                value = manifest_mapping()
                value["demo_scenario"] = scenario.value
                value["final_outcome"] = scenario.value.upper()
                parsed = DemoManifest.from_mapping(value)
                self.assertIs(parsed.demo_scenario, scenario)

    def test_rejects_unknown_version_fields_and_outcome_mismatch(self) -> None:
        cases: list[dict[str, object]] = []
        unsupported = manifest_mapping()
        unsupported["schema_version"] = "blackpod.demo_manifest.v0"
        cases.append(unsupported)
        unknown = manifest_mapping()
        unknown["invented"] = True
        cases.append(unknown)
        mismatch = manifest_mapping()
        mismatch["final_outcome"] = "HELD"
        cases.append(mismatch)

        for value in cases:
            with self.subTest(value=value):
                with self.assertRaises(ContractValidationError):
                    DemoManifest.from_mapping(value)

    def test_rejects_noncanonical_or_unsafe_artifact_references(self) -> None:
        mutations = (
            ("captains_log", "path", "/tmp/captains_log.json"),
            ("captains_log", "path", "presentation/../captains_log.json"),
            ("mission_summary", "sha256", "not-a-digest"),
            ("mission_summary", "byte_size", 0),
            ("final_snapshot", "name", "some_other_snapshot"),
            ("final_snapshot", "observed_at", "2026-07-19T20:00:01Z"),
        )
        for artifact_name, field_name, replacement in mutations:
            with self.subTest(artifact=artifact_name, field=field_name):
                value = copy.deepcopy(manifest_mapping())
                reference = value[artifact_name]
                assert isinstance(reference, dict)
                reference[field_name] = replacement
                with self.assertRaises(ContractValidationError):
                    DemoManifest.from_mapping(value)

    def test_rejects_any_change_to_shadow_safety_boundary(self) -> None:
        value = manifest_mapping()
        value["allowed_operations"] = ["VALIDATE", "PLAN_ONLY", "SUBMIT_ORDER"]
        with self.assertRaises(ContractValidationError):
            DemoManifest.from_mapping(value)

        value = manifest_mapping()
        value["prohibited_operations"] = ["SUBMIT_ORDER"]
        with self.assertRaises(ContractValidationError):
            DemoManifest.from_mapping(value)

        value = manifest_mapping()
        value["shadow_only_declaration"] = "SHADOW"
        with self.assertRaises(ContractValidationError):
            DemoManifest.from_mapping(value)

    def test_modeldock_mode_and_identity_must_match_transport(self) -> None:
        disabled = manifest_mapping()
        disabled.update(
            {
                "modeldock_mode": "DISABLED",
                "modeldock_revision_or_service_identity": None,
                "modeldock_provider": None,
                "modeldock_model": None,
                "modeldock_trace_id": None,
            }
        )
        self.assertIs(
            DemoManifest.from_mapping(disabled).modeldock_mode,
            DemoModelDockMode.DISABLED,
        )

        replay_claiming_live = manifest_mapping()
        replay_claiming_live["modeldock_mode"] = "LIVE"
        with self.assertRaises(ContractValidationError):
            DemoManifest.from_mapping(replay_claiming_live)

        disabled_with_identity = copy.deepcopy(disabled)
        disabled_with_identity["modeldock_provider"] = "mlx"
        with self.assertRaises(ContractValidationError):
            DemoManifest.from_mapping(disabled_with_identity)

        replay_without_service_identity = manifest_mapping()
        replay_without_service_identity[
            "modeldock_revision_or_service_identity"
        ] = None
        with self.assertRaises(ContractValidationError):
            DemoManifest.from_mapping(replay_without_service_identity)

        failed_without_failed_outcome = manifest_mapping()
        failed_without_failed_outcome["modeldock_mode"] = "FAILED"
        with self.assertRaises(ContractValidationError):
            DemoManifest.from_mapping(failed_without_failed_outcome)

        absolute_model = manifest_mapping()
        absolute_model["modeldock_model"] = "/Users/demo/local-model"
        with self.assertRaises(ContractValidationError):
            DemoManifest.from_mapping(absolute_model)

    def test_revisions_and_counts_are_validated(self) -> None:
        value = manifest_mapping()
        value["build_week_revision"] = "dirty-main"
        with self.assertRaises(ContractValidationError):
            DemoManifest.from_mapping(value)

        value = manifest_mapping()
        value["snapshot_count"] = True
        with self.assertRaises(ContractValidationError):
            DemoManifest.from_mapping(value)


if __name__ == "__main__":
    unittest.main()
