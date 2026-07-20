from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from blackpod_build_week.demo_catalog import (
    DEMO_SCENARIO_NAMES,
    DemoCatalogError,
)
from blackpod_build_week.demo_validation import validate_demo_catalog


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class DemoCatalogValidationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)
        shutil.copytree(PROJECT_ROOT / "fixtures", self.root / "fixtures")
        shutil.copytree(PROJECT_ROOT / "examples", self.root / "examples")
        self.catalog_path = self.root / "fixtures/demo_scenarios.v1.json"

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def read_catalog(self) -> dict[str, object]:
        return json.loads(self.catalog_path.read_text(encoding="utf-8"))

    def write_catalog(self, value: dict[str, object]) -> None:
        self.catalog_path.write_text(
            json.dumps(value, indent=2) + "\n", encoding="utf-8"
        )

    def test_all_committed_scenarios_validate_in_canonical_order(self) -> None:
        catalog = validate_demo_catalog()

        self.assertEqual(
            tuple(scenario.name for scenario in catalog.scenarios),
            DEMO_SCENARIO_NAMES,
        )
        self.assertTrue(catalog.shadow_only)
        self.assertEqual(catalog.allowed_operations, ("VALIDATE", "PLAN_ONLY"))
        self.assertEqual(
            catalog.prohibited_operations,
            ("SUBMIT_ORDER", "CANCEL_ORDER", "MODIFY_PORTFOLIO", "BROKER_CALL"),
        )

    def test_corrupted_fixture_hash_is_rejected(self) -> None:
        fixture = self.root / "fixtures/oracle_replay_quotes.v1.json"
        fixture.write_bytes(fixture.read_bytes() + b"\n")

        with self.assertRaisesRegex(DemoCatalogError, "hash mismatch"):
            validate_demo_catalog(root=self.root)

    def test_changed_expected_outcome_is_rejected(self) -> None:
        value = self.read_catalog()
        scenarios = value["scenarios"]
        assert isinstance(scenarios, list)
        scenarios[0]["expected_outcome"] = "HELD"
        self.write_catalog(value)

        with self.assertRaisesRegex(DemoCatalogError, "policy changed"):
            validate_demo_catalog(root=self.root)

    def test_absolute_pack_path_is_rejected(self) -> None:
        value = self.read_catalog()
        scenarios = value["scenarios"]
        assert isinstance(scenarios, list)
        scenarios[0]["request"]["path"] = "/tmp/private-request.json"
        self.write_catalog(value)

        with self.assertRaises(DemoCatalogError):
            validate_demo_catalog(root=self.root)

    def test_secret_like_committed_value_is_rejected(self) -> None:
        value = self.read_catalog()
        scenarios = value["scenarios"]
        assert isinstance(scenarios, list)
        scenarios[0]["operator_reason"] = "Bearer abcdefghijklmnop"
        self.write_catalog(value)

        with self.assertRaisesRegex(DemoCatalogError, "secret-like value"):
            validate_demo_catalog(root=self.root)

    def test_prohibited_execution_operation_is_rejected(self) -> None:
        value = self.read_catalog()
        safety = value["safety"]
        assert isinstance(safety, dict)
        safety["allowed_operations"] = ["VALIDATE", "PLAN_ONLY", "SUBMIT_ORDER"]
        self.write_catalog(value)

        with self.assertRaisesRegex(DemoCatalogError, "allowed operations"):
            validate_demo_catalog(root=self.root)


if __name__ == "__main__":
    unittest.main()
