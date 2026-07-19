from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from blackpod_build_week.battlestar_config import (
    ADVISOR_HEALTH_ENTRY_POINT,
    ADVISOR_HEALTH_MODULE_RELATIVE_PATH,
    BATTLESTAR_PATH_ENV,
    CANDIDATE_ENTRY_POINT,
    CANDIDATE_MODULE_RELATIVE_PATH,
    COUNCIL_EXECUTIVE_SUMMARY_ENTRY_POINT,
    COUNCIL_EXECUTIVE_SUMMARY_MODULE_RELATIVE_PATH,
    COUNCIL_SYNTHESIS_ENTRY_POINT,
    COUNCIL_SYNTHESIS_MODULE_RELATIVE_PATH,
    GOVERNOR_DELIBERATION_ENTRY_POINT,
    GOVERNOR_DELIBERATION_MODULE_RELATIVE_PATH,
    GOVERNOR_PREPARATION_ENTRY_POINT,
    GOVERNOR_PREPARATION_MODULE_RELATIVE_PATH,
    GOVERNOR_READINESS_ENTRY_POINT,
    GOVERNOR_READINESS_MODULE_RELATIVE_PATH,
    GOVERNOR_RENDERING_ENTRY_POINT,
    GOVERNOR_RENDERING_MODULE_RELATIVE_PATH,
    GOVERNOR_SENATE_INTAKE_ENTRY_POINT,
    GOVERNOR_SENATE_INTAKE_MODULE_RELATIVE_PATH,
    MANDATE_ENTRY_POINT,
    MANDATE_MODULE_RELATIVE_PATH,
    ORACLE_ENTRY_POINT,
    ORACLE_FLEET_RELATIVE_PATH,
    ORACLE_MODULE_RELATIVE_PATH,
    RUNTIME_VALIDATION_ENTRY_POINT,
    RUNTIME_VALIDATION_MODULE_RELATIVE_PATH,
    SENATE_DELIBERATION_ENTRY_POINT,
    SENATE_DELIBERATION_MODULE_RELATIVE_PATH,
    SENATE_REVIEW_ENTRY_POINT,
    SENATE_REVIEW_MODULE_RELATIVE_PATH,
    BattlestarConfigurationError,
    load_battlestar_config,
    load_council_battlestar_config,
    load_governor_battlestar_config,
)


COUNCIL_MODULES = (
    CANDIDATE_MODULE_RELATIVE_PATH,
    SENATE_REVIEW_MODULE_RELATIVE_PATH,
    SENATE_DELIBERATION_MODULE_RELATIVE_PATH,
    MANDATE_MODULE_RELATIVE_PATH,
    COUNCIL_SYNTHESIS_MODULE_RELATIVE_PATH,
    COUNCIL_EXECUTIVE_SUMMARY_MODULE_RELATIVE_PATH,
    ADVISOR_HEALTH_MODULE_RELATIVE_PATH,
    RUNTIME_VALIDATION_MODULE_RELATIVE_PATH,
)
GOVERNOR_MODULES = (
    GOVERNOR_SENATE_INTAKE_MODULE_RELATIVE_PATH,
    GOVERNOR_PREPARATION_MODULE_RELATIVE_PATH,
    GOVERNOR_DELIBERATION_MODULE_RELATIVE_PATH,
    GOVERNOR_READINESS_MODULE_RELATIVE_PATH,
    GOVERNOR_RENDERING_MODULE_RELATIVE_PATH,
)


class BattlestarConfigurationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.base = Path(self.temporary_directory.name)
        self.artifacts_root = self.base / "build-week-artifacts"

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def make_repository(
        self,
        name: str = "battlestar",
        *,
        include_council: bool = False,
        include_governor: bool = False,
    ) -> Path:
        root = self.base / name
        (root / ORACLE_MODULE_RELATIVE_PATH).parent.mkdir(parents=True)
        (root / ORACLE_MODULE_RELATIVE_PATH).write_text(
            "def run_oracle_pipeline():\n    return None\n",
            encoding="utf-8",
        )
        (root / ORACLE_FLEET_RELATIVE_PATH).parent.mkdir(parents=True)
        (root / ORACLE_FLEET_RELATIVE_PATH).write_text(
            "fleet_id: test-oracle-fleet\n",
            encoding="utf-8",
        )
        if include_council:
            for relative_path in COUNCIL_MODULES:
                module = root / relative_path
                module.parent.mkdir(parents=True, exist_ok=True)
                module.write_text("# deterministic test module\n", encoding="utf-8")
        if include_governor:
            for relative_path in GOVERNOR_MODULES:
                module = root / relative_path
                module.parent.mkdir(parents=True, exist_ok=True)
                module.write_text("# deterministic test module\n", encoding="utf-8")
        self.run_git(root, "init", "--quiet")
        self.run_git(root, "config", "user.email", "build-week@example.invalid")
        self.run_git(root, "config", "user.name", "Build Week Tests")
        self.run_git(root, "add", ".")
        self.run_git(root, "commit", "--quiet", "-m", "fixture")
        return root

    def run_git(self, root: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
        environment = os.environ.copy()
        environment["GIT_OPTIONAL_LOCKS"] = "0"
        return subprocess.run(
            ("git", "-C", str(root), *arguments),
            check=True,
            capture_output=True,
            text=True,
            env=environment,
        )

    def load(self, root: Path, *, strict_clean: bool = False):
        return load_battlestar_config(
            artifacts_root=self.artifacts_root,
            environ={BATTLESTAR_PATH_ENV: str(root)},
            strict_clean=strict_clean,
        )

    def test_public_oracle_entry_point_is_stable(self) -> None:
        self.assertEqual(
            ORACLE_ENTRY_POINT,
            "blackpod.runtime.oracle_pipeline.run_oracle_pipeline",
        )

    def test_public_council_entry_points_are_stable(self) -> None:
        self.assertEqual(
            CANDIDATE_ENTRY_POINT,
            "blackpod.advisors.trading_candidate_generator.build_trading_candidate_report",
        )
        self.assertEqual(
            SENATE_REVIEW_ENTRY_POINT,
            "blackpod.advisors.senate_candidate_intake.build_senate_review_packet",
        )
        self.assertEqual(
            SENATE_DELIBERATION_ENTRY_POINT,
            "blackpod.advisors.senate_deliberation.build_senate_deliberation",
        )
        self.assertEqual(
            MANDATE_ENTRY_POINT,
            "blackpod.advisors.mandate.MandateAdvisor.run",
        )
        self.assertEqual(
            COUNCIL_SYNTHESIS_ENTRY_POINT,
            "blackpod.governor.council_synthesis.build_council_synthesis",
        )
        self.assertEqual(
            COUNCIL_EXECUTIVE_SUMMARY_ENTRY_POINT,
            "blackpod.governor.council_executive_summary.build_council_executive_summary",
        )
        self.assertEqual(
            ADVISOR_HEALTH_ENTRY_POINT,
            "blackpod.runtime.advisor_health.build_advisor_health_summary",
        )
        self.assertEqual(
            RUNTIME_VALIDATION_ENTRY_POINT,
            "blackpod.runtime.validation_report.build_runtime_validation_report",
        )

    def test_public_governor_entry_points_are_stable(self) -> None:
        self.assertEqual(
            GOVERNOR_SENATE_INTAKE_ENTRY_POINT,
            "blackpod.governor.governor_senate_intake.build_governor_senate_intake",
        )
        self.assertEqual(
            GOVERNOR_PREPARATION_ENTRY_POINT,
            "blackpod.governor.governor_deliberation_prep.build_governor_deliberation_prep",
        )
        self.assertEqual(
            GOVERNOR_DELIBERATION_ENTRY_POINT,
            "blackpod.governor.governor_deliberation.build_governor_deliberation",
        )
        self.assertEqual(
            GOVERNOR_READINESS_ENTRY_POINT,
            "blackpod.governor.governor_decision_readiness.build_governor_decision_readiness",
        )
        self.assertEqual(
            GOVERNOR_RENDERING_ENTRY_POINT,
            "blackpod.governor.governor_decision.build_governor_decision",
        )

    def test_missing_environment_variable_is_rejected(self) -> None:
        with self.assertRaisesRegex(
            BattlestarConfigurationError,
            "BATTLESTAR_PATH is not configured",
        ):
            load_battlestar_config(
                artifacts_root=self.artifacts_root,
                environ={},
            )

    def test_nonexistent_and_non_directory_paths_are_rejected(self) -> None:
        regular_file = self.base / "regular-file"
        regular_file.write_text("not a repository", encoding="utf-8")

        cases = (
            (self.base / "absent", "does not exist"),
            (regular_file, "is not a directory"),
        )
        for path, expected_message in cases:
            with self.subTest(path=path.name):
                with self.assertRaisesRegex(
                    BattlestarConfigurationError,
                    expected_message,
                ):
                    self.load(path)

    def test_missing_oracle_module_is_rejected(self) -> None:
        root = self.make_repository()
        (root / ORACLE_MODULE_RELATIVE_PATH).unlink()

        with self.assertRaisesRegex(
            BattlestarConfigurationError,
            "Oracle module is missing",
        ):
            self.load(root)

    def test_missing_oracle_fleet_configuration_is_rejected(self) -> None:
        root = self.make_repository()
        (root / ORACLE_FLEET_RELATIVE_PATH).unlink()

        with self.assertRaisesRegex(
            BattlestarConfigurationError,
            "Oracle fleet configuration is missing",
        ):
            self.load(root)

    def test_valid_repository_reports_revision_branch_and_clean_state(self) -> None:
        root = self.make_repository()
        expected_revision = self.run_git(root, "rev-parse", "HEAD").stdout.strip()
        expected_branch = self.run_git(
            root, "symbolic-ref", "--quiet", "--short", "HEAD"
        ).stdout.strip()

        config = self.load(root)

        self.assertEqual(config.root, root.resolve())
        self.assertEqual(
            config.oracle_module_path,
            (root / ORACLE_MODULE_RELATIVE_PATH).resolve(),
        )
        self.assertEqual(
            config.fleet_path,
            (root / ORACLE_FLEET_RELATIVE_PATH).resolve(),
        )
        self.assertEqual(config.git_revision, expected_revision)
        self.assertEqual(config.git_branch, expected_branch)
        self.assertFalse(config.dirty_worktree)
        self.assertIsNone(config.candidate_module_path)
        self.assertIsNone(config.council_synthesis_module_path)

    def test_council_preflight_reports_all_required_native_modules(self) -> None:
        root = self.make_repository(include_council=True)

        config = load_council_battlestar_config(
            artifacts_root=self.artifacts_root,
            environ={BATTLESTAR_PATH_ENV: str(root)},
        )

        expected = {
            "candidate_module_path": CANDIDATE_MODULE_RELATIVE_PATH,
            "senate_review_module_path": SENATE_REVIEW_MODULE_RELATIVE_PATH,
            "senate_deliberation_module_path": SENATE_DELIBERATION_MODULE_RELATIVE_PATH,
            "mandate_module_path": MANDATE_MODULE_RELATIVE_PATH,
            "council_synthesis_module_path": COUNCIL_SYNTHESIS_MODULE_RELATIVE_PATH,
            "council_executive_summary_module_path": (
                COUNCIL_EXECUTIVE_SUMMARY_MODULE_RELATIVE_PATH
            ),
            "advisor_health_module_path": ADVISOR_HEALTH_MODULE_RELATIVE_PATH,
            "runtime_validation_module_path": RUNTIME_VALIDATION_MODULE_RELATIVE_PATH,
        }
        for field_name, relative_path in expected.items():
            with self.subTest(field=field_name):
                self.assertEqual(
                    getattr(config, field_name),
                    (root / relative_path).resolve(),
                )

    def test_council_preflight_rejects_each_missing_native_module(self) -> None:
        cases = (
            (CANDIDATE_MODULE_RELATIVE_PATH, "candidate-generation module is missing"),
            (SENATE_REVIEW_MODULE_RELATIVE_PATH, "Senate review module is missing"),
            (
                SENATE_DELIBERATION_MODULE_RELATIVE_PATH,
                "Senate deliberation module is missing",
            ),
            (MANDATE_MODULE_RELATIVE_PATH, "Mandate module is missing"),
            (
                COUNCIL_SYNTHESIS_MODULE_RELATIVE_PATH,
                "Council synthesis module is missing",
            ),
            (
                COUNCIL_EXECUTIVE_SUMMARY_MODULE_RELATIVE_PATH,
                "Council executive-summary module is missing",
            ),
            (
                ADVISOR_HEALTH_MODULE_RELATIVE_PATH,
                "advisor-health module is missing",
            ),
            (
                RUNTIME_VALIDATION_MODULE_RELATIVE_PATH,
                "runtime-validation module is missing",
            ),
        )
        for index, (relative_path, message) in enumerate(cases):
            with self.subTest(module=str(relative_path)):
                root = self.make_repository(
                    f"battlestar-{index}", include_council=True
                )
                (root / relative_path).unlink()
                with self.assertRaisesRegex(BattlestarConfigurationError, message):
                    load_council_battlestar_config(
                        artifacts_root=self.artifacts_root,
                        environ={BATTLESTAR_PATH_ENV: str(root)},
                    )

    def test_governor_preflight_reports_all_required_native_modules(self) -> None:
        root = self.make_repository(
            include_council=True,
            include_governor=True,
        )

        config = load_governor_battlestar_config(
            artifacts_root=self.artifacts_root,
            environ={BATTLESTAR_PATH_ENV: str(root)},
        )

        expected = {
            "governor_senate_intake_module_path": (
                GOVERNOR_SENATE_INTAKE_MODULE_RELATIVE_PATH
            ),
            "governor_preparation_module_path": (
                GOVERNOR_PREPARATION_MODULE_RELATIVE_PATH
            ),
            "governor_deliberation_module_path": (
                GOVERNOR_DELIBERATION_MODULE_RELATIVE_PATH
            ),
            "governor_readiness_module_path": (
                GOVERNOR_READINESS_MODULE_RELATIVE_PATH
            ),
            "governor_rendering_module_path": (
                GOVERNOR_RENDERING_MODULE_RELATIVE_PATH
            ),
        }
        for field_name, relative_path in expected.items():
            with self.subTest(field=field_name):
                self.assertEqual(
                    getattr(config, field_name),
                    (root / relative_path).resolve(),
                )

    def test_governor_preflight_rejects_each_missing_native_module(self) -> None:
        cases = (
            (
                GOVERNOR_SENATE_INTAKE_MODULE_RELATIVE_PATH,
                "Governor Senate-intake module is missing",
            ),
            (
                GOVERNOR_PREPARATION_MODULE_RELATIVE_PATH,
                "Governor preparation module is missing",
            ),
            (
                GOVERNOR_DELIBERATION_MODULE_RELATIVE_PATH,
                "Governor deliberation module is missing",
            ),
            (
                GOVERNOR_READINESS_MODULE_RELATIVE_PATH,
                "Governor readiness module is missing",
            ),
            (
                GOVERNOR_RENDERING_MODULE_RELATIVE_PATH,
                "Governor rendering module is missing",
            ),
        )
        for index, (relative_path, message) in enumerate(cases):
            with self.subTest(module=str(relative_path)):
                root = self.make_repository(
                    f"battlestar-governor-{index}",
                    include_council=True,
                    include_governor=True,
                )
                (root / relative_path).unlink()
                with self.assertRaisesRegex(BattlestarConfigurationError, message):
                    load_governor_battlestar_config(
                        artifacts_root=self.artifacts_root,
                        environ={BATTLESTAR_PATH_ENV: str(root)},
                    )

    def test_dirty_worktree_is_reported_without_rejecting_development(self) -> None:
        root = self.make_repository()
        (root / "untracked.txt").write_text("local work", encoding="utf-8")

        config = self.load(root)

        self.assertTrue(config.dirty_worktree)

    def test_strict_clean_rejects_dirty_worktree(self) -> None:
        root = self.make_repository()
        (root / ORACLE_MODULE_RELATIVE_PATH).write_text(
            "# local modification\n",
            encoding="utf-8",
        )

        with self.assertRaisesRegex(
            BattlestarConfigurationError,
            "strict clean mode rejects it",
        ):
            self.load(root, strict_clean=True)

    def test_detached_head_reports_no_branch(self) -> None:
        root = self.make_repository()
        revision = self.run_git(root, "rev-parse", "HEAD").stdout.strip()
        self.run_git(root, "checkout", "--quiet", "--detach", revision)

        config = self.load(root)

        self.assertEqual(config.git_revision, revision)
        self.assertIsNone(config.git_branch)

    def test_repository_without_recordable_revision_is_rejected(self) -> None:
        root = self.base / "uncommitted-battlestar"
        (root / ORACLE_MODULE_RELATIVE_PATH).parent.mkdir(parents=True)
        (root / ORACLE_MODULE_RELATIVE_PATH).write_text("# oracle\n", encoding="utf-8")
        (root / ORACLE_FLEET_RELATIVE_PATH).parent.mkdir(parents=True)
        (root / ORACLE_FLEET_RELATIVE_PATH).write_text("fleet_id: test\n", encoding="utf-8")
        self.run_git(root, "init", "--quiet")

        with self.assertRaisesRegex(
            BattlestarConfigurationError,
            "Git revision is unavailable",
        ):
            self.load(root)

    def test_repository_equal_to_or_beneath_artifact_root_is_rejected(self) -> None:
        cases = (
            self.artifacts_root,
            self.artifacts_root / "battlestar",
            self.artifacts_root / "missions",
            self.artifacts_root / "missions" / "mission-001" / "battlestar",
        )
        for index, root in enumerate(cases):
            with self.subTest(index=index):
                root.mkdir(parents=True)
                with self.assertRaisesRegex(
                    BattlestarConfigurationError,
                    "must not overlap",
                ):
                    self.load(root)

    def test_artifact_root_beneath_repository_is_rejected(self) -> None:
        root = self.make_repository()

        with self.assertRaisesRegex(BattlestarConfigurationError, "must not overlap"):
            load_battlestar_config(
                artifacts_root=root / "build-week-artifacts",
                environ={BATTLESTAR_PATH_ENV: str(root)},
            )

    def test_required_file_may_not_resolve_outside_repository(self) -> None:
        if not hasattr(os, "symlink"):
            self.skipTest("symbolic links are unavailable")
        root = self.make_repository()
        external_module = self.base / "external-oracle.py"
        external_module.write_text("# external\n", encoding="utf-8")
        module_path = root / ORACLE_MODULE_RELATIVE_PATH
        module_path.unlink()
        module_path.symlink_to(external_module)

        with self.assertRaisesRegex(
            BattlestarConfigurationError,
            "must resolve inside the Battlestar repository",
        ):
            self.load(root)


if __name__ == "__main__":
    unittest.main()
