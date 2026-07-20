from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path

from blackpod_build_week.battlestar_config import (
    ORACLE_FLEET_RELATIVE_PATH,
    ORACLE_MODULE_RELATIVE_PATH,
    BattlestarConfig,
    BattlestarConfigurationError,
)
from blackpod_build_week.modeldock_config import (
    ModelDockConfig,
    ModelDockConfigurationError,
)
from blackpod_build_week.modeldock_preflight import ModelDockPreflightReport
from blackpod_build_week.preflight import (
    CheckStatus,
    InterfaceProbeResult,
    PreflightSettings,
    RunMode,
    probe_battlestar_interfaces,
    run_preflight,
    validate_demo_fixtures,
)
from blackpod_build_week.repository_state import (
    GitWorktreeState,
    inspect_git_worktree,
    scan_committed_secrets,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _config(root: Path, *, dirty: bool = False) -> BattlestarConfig:
    return BattlestarConfig(
        root=root,
        oracle_module_path=root / ORACLE_MODULE_RELATIVE_PATH,
        fleet_path=root / ORACLE_FLEET_RELATIVE_PATH,
        git_revision="a" * 40,
        git_branch="main",
        dirty_worktree=dirty,
    )


def _interfaces(*, missing: str | None = None) -> tuple[InterfaceProbeResult, ...]:
    return tuple(
        InterfaceProbeResult(
            family=family,
            entry_point=f"blackpod.demo.{family}",
            available=family != missing,
            message="callable" if family != missing else "entry point is missing",
        )
        for family in ("oracle", "council", "governor", "operator", "navigator")
    )


def _modeldock_report(
    *,
    inference_ready: bool = True,
    mocked: bool = False,
    issues: tuple[dict[str, object], ...] = (),
) -> ModelDockPreflightReport:
    return ModelDockPreflightReport(
        base_url="http://127.0.0.1:8000",
        timeout_seconds=10.0,
        service_reachable=True,
        health_ready=True,
        health_response={"status": "ok", "service": "modeldock", "version": "0.1.0"},
        models_endpoint_ready=True,
        selected_model_available=True,
        text_generate_endpoint_available=inference_ready,
        inference_ready=inference_ready,
        provider="mlx",
        model="mlx-community/demo-model",
        model_revision="revision-demo",
        trace_id="trace-demo-preflight",
        mocked=mocked,
        latency_ms=12.5,
        observed_at="2026-07-19T12:00:00Z",
        issues=issues,
    )


class PreflightTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.base = Path(self.temporary.name)
        self.artifacts = self.base / "artifacts"
        self.fake_battlestar_root = self.base / "battlestar"
        self.fake_battlestar_root.mkdir()

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def run_ready(
        self,
        *,
        mode: RunMode = RunMode.REPLAY,
        strict_clean: bool = False,
        battlestar_dirty: bool = False,
        build_week_dirty: bool = False,
        import_results: tuple[InterfaceProbeResult, ...] | None = None,
        modeldock_report: ModelDockPreflightReport | None = None,
        modeldock_config_loader=None,
        modeldock_preflight_runner=None,
        battlestar_loader=None,
    ):
        config = _config(self.fake_battlestar_root, dirty=battlestar_dirty)
        loader = battlestar_loader or (lambda **_: config)
        config_loader = modeldock_config_loader or (
            lambda **_: ModelDockConfig(
                base_url="http://127.0.0.1:8000",
                timeout_seconds=10.0,
                model="mlx-community/demo-model",
            )
        )
        runner = modeldock_preflight_runner or (
            lambda _: modeldock_report or _modeldock_report()
        )
        return run_preflight(
            PreflightSettings(mode, self.artifacts, strict_clean),
            environ={"BATTLESTAR_PATH": str(self.fake_battlestar_root)},
            battlestar_loader=loader,
            import_probe=lambda _: import_results or _interfaces(),
            modeldock_config_loader=config_loader,
            modeldock_preflight_runner=runner,
            repository_inspector=lambda root: GitWorktreeState(
                root=root,
                revision="b" * 40,
                branch="stage-2-phase-3-demo-readiness",
                dirty=build_week_dirty,
            ),
            secret_scanner=lambda _: (),
            fixture_probe=validate_demo_fixtures,
            build_week_import_probe=lambda *_: (
                True,
                {"imports": ["blackpod_build_week"], "missing": []},
                "Build Week workflow imports are ready",
            ),
            build_week_root=PROJECT_ROOT,
            now=lambda: datetime(2026, 7, 19, 12, 0, tzinfo=UTC),
        )

    def check(self, report, component: str, name: str):
        return next(
            item
            for item in report.checks
            if item.component == component and item.name == name
        )

    def test_settings_accept_lowercase_mode(self) -> None:
        self.assertEqual(
            PreflightSettings("replay", self.artifacts).mode,
            RunMode.REPLAY,
        )

    def test_replay_is_ready_and_never_loads_modeldock_or_calls_network(self) -> None:
        calls: list[str] = []

        def forbidden_config(**_):
            calls.append("config")
            raise AssertionError("ModelDock configuration loaded during replay")

        def forbidden_network(_):
            calls.append("network")
            raise AssertionError("ModelDock network called during replay")

        report = self.run_ready(
            modeldock_config_loader=forbidden_config,
            modeldock_preflight_runner=forbidden_network,
        )

        self.assertTrue(report.ready)
        self.assertEqual(calls, [])
        replay = self.check(report, "modeldock", "replay_transport")
        self.assertEqual(replay.status, CheckStatus.PASS)
        self.assertFalse(replay.details["network_attempted"])
        self.assertEqual(report.mode, RunMode.REPLAY)

    def test_live_requires_successful_real_mlx_inference(self) -> None:
        report = self.run_ready(mode=RunMode.LIVE)
        self.assertTrue(report.ready)
        inference = self.check(report, "modeldock", "live_inference")
        self.assertEqual(inference.status, CheckStatus.PASS)
        self.assertEqual(inference.details["provider"], "mlx")
        self.assertFalse(inference.details["mocked"])

    def test_shallow_health_is_not_live_readiness(self) -> None:
        report = self.run_ready(
            mode=RunMode.LIVE,
            modeldock_report=_modeldock_report(
                inference_ready=False,
                issues=(
                    {
                        "code": "connection_failure",
                        "message": "local inference unavailable",
                        "resumable": True,
                    },
                ),
            ),
        )
        self.assertFalse(report.ready)
        self.assertEqual(
            self.check(report, "modeldock", "live_inference").status,
            CheckStatus.FAIL,
        )

    def test_unavailable_live_modeldock_is_a_mandatory_failure(self) -> None:
        def missing_config(**_):
            raise ModelDockConfigurationError(
                "MODELDOCK_BASE_URL is not configured"
            )

        report = self.run_ready(
            mode=RunMode.LIVE,
            modeldock_config_loader=missing_config,
        )
        self.assertFalse(report.ready)
        self.assertEqual(
            self.check(report, "modeldock", "configuration").status,
            CheckStatus.FAIL,
        )
        self.assertEqual(
            self.check(report, "modeldock", "live_inference").status,
            CheckStatus.SKIPPED,
        )

    def test_mocked_live_inference_is_rejected_even_if_runner_says_ready(self) -> None:
        report = self.run_ready(
            mode=RunMode.LIVE,
            modeldock_report=_modeldock_report(mocked=True),
        )
        self.assertFalse(report.ready)
        self.assertEqual(
            self.check(report, "modeldock", "live_inference").status,
            CheckStatus.FAIL,
        )

    def test_missing_battlestar_path_is_aggregated_failure(self) -> None:
        def missing(**_):
            raise BattlestarConfigurationError("BATTLESTAR_PATH is not configured")

        report = self.run_ready(battlestar_loader=missing)
        self.assertFalse(report.ready)
        self.assertEqual(
            self.check(report, "battlestar", "configuration").status,
            CheckStatus.FAIL,
        )
        self.assertEqual(
            self.check(report, "battlestar", "interfaces").status,
            CheckStatus.SKIPPED,
        )

    def test_missing_interface_fails_the_family_probe(self) -> None:
        report = self.run_ready(import_results=_interfaces(missing="governor"))
        self.assertFalse(report.ready)
        interface_check = self.check(report, "battlestar", "interfaces")
        self.assertEqual(interface_check.status, CheckStatus.FAIL)
        governor = next(
            item
            for item in interface_check.details["interfaces"]
            if item["family"] == "governor"
        )
        self.assertFalse(governor["available"])

    def test_dirty_worktrees_warn_normally_and_fail_strict_mode(self) -> None:
        development = self.run_ready(
            battlestar_dirty=True,
            build_week_dirty=True,
        )
        self.assertTrue(development.ready)
        self.assertEqual(
            self.check(development, "build_week", "git").status,
            CheckStatus.WARN,
        )
        self.assertEqual(
            self.check(development, "battlestar", "git").status,
            CheckStatus.WARN,
        )

        strict = self.run_ready(
            strict_clean=True,
            battlestar_dirty=True,
            build_week_dirty=True,
        )
        self.assertFalse(strict.ready)
        self.assertEqual(
            self.check(strict, "build_week", "git").status,
            CheckStatus.FAIL,
        )
        self.assertEqual(
            self.check(strict, "battlestar", "git").status,
            CheckStatus.FAIL,
        )

    def test_report_is_typed_sanitized_and_deterministic(self) -> None:
        report = self.run_ready()
        payload = report.to_dict()
        self.assertEqual(payload["schema_version"], "blackpod.demo_preflight.v1")
        self.assertEqual(payload["observed_at"], "2026-07-19T12:00:00Z")
        serialized = json.dumps(payload, sort_keys=True)
        self.assertNotIn(str(self.fake_battlestar_root), serialized)
        self.assertNotIn(str(PROJECT_ROOT), serialized)
        self.assertTrue(payload["ready"])

    def test_committed_fixtures_validate_and_schema_corruption_is_reported(self) -> None:
        valid = validate_demo_fixtures(PROJECT_ROOT)
        self.assertTrue(all(item.valid for item in valid))

        copy_root = self.base / "fixture-copy"
        shutil.copytree(PROJECT_ROOT / "examples", copy_root / "examples")
        shutil.copytree(PROJECT_ROOT / "fixtures", copy_root / "fixtures")
        oracle = copy_root / "fixtures/oracle_replay_quotes.v1.json"
        payload = json.loads(oracle.read_text(encoding="utf-8"))
        payload["schema_version"] = "future.oracle.v2"
        oracle.write_text(json.dumps(payload), encoding="utf-8")

        invalid = validate_demo_fixtures(copy_root)
        oracle_result = next(
            item
            for item in invalid
            if item.path == "fixtures/oracle_replay_quotes.v1.json"
        )
        self.assertFalse(oracle_result.valid)

    def test_symlink_artifact_root_is_rejected(self) -> None:
        target = self.base / "actual-artifacts"
        target.mkdir()
        link = self.base / "artifact-link"
        link.symlink_to(target, target_is_directory=True)
        self.artifacts = link

        report = self.run_ready()
        self.assertFalse(report.ready)
        self.assertEqual(
            self.check(report, "build_week", "artifact_root").status,
            CheckStatus.FAIL,
        )


class RepositoryStateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name) / "repository"
        self.root.mkdir()
        subprocess.run(("git", "init", "-q", str(self.root)), check=True)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def commit(self, path: str, payload: str) -> None:
        target = self.root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(payload, encoding="utf-8")
        subprocess.run(("git", "-C", str(self.root), "add", path), check=True)
        subprocess.run(
            (
                "git",
                "-C",
                str(self.root),
                "-c",
                "user.name=Preflight Test",
                "-c",
                "user.email=preflight@example.invalid",
                "commit",
                "-qm",
                "fixture",
            ),
            check=True,
        )

    def test_git_state_reports_revision_branch_and_dirty(self) -> None:
        self.commit("README.md", "clean\n")
        clean = inspect_git_worktree(self.root)
        self.assertRegex(clean.revision, r"^[0-9a-f]{40}$")
        self.assertIsNotNone(clean.branch)
        self.assertFalse(clean.dirty)
        (self.root / "README.md").write_text("dirty\n", encoding="utf-8")
        self.assertTrue(inspect_git_worktree(self.root).dirty)

    def test_committed_secret_scan_never_returns_secret_value(self) -> None:
        # Construct the synthetic value at runtime so the repository containing
        # this detector test does not itself contain a credential-shaped token.
        credential = "sk-proj-" + "Q9x7Lm2N" + "p8Vr4Ts6" + "Wy3Za5Bc"
        self.commit("config.txt", f'api_key="{credential}"\n')
        findings = scan_committed_secrets(self.root)
        self.assertTrue(findings)
        serialized = json.dumps([item.to_dict() for item in findings])
        self.assertNotIn(credential, serialized)
        self.assertIn("config.txt", serialized)


class BattlestarCallableProbeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name) / "battlestar"
        self.root.mkdir()

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def materialize_interfaces(self) -> None:
        # Importing the private registry is intentional here: this focused test
        # proves every configured public dotted entry point, not a duplicate list.
        from blackpod_build_week.preflight import _INTERFACE_SPECS

        for spec in _INTERFACE_SPECS:
            module = self.root / spec.module_path
            module.parent.mkdir(parents=True, exist_ok=True)
            parent = module.parent
            while parent != self.root:
                (parent / "__init__.py").touch()
                parent = parent.parent
            module_name = spec.module_path.with_suffix("").as_posix().replace("/", ".")
            attribute = spec.entry_point.removeprefix(module_name + ".")
            if "." in attribute:
                class_name, method_name = attribute.split(".", 1)
                source = (
                    f"class {class_name}:\n"
                    "    @staticmethod\n"
                    f"    def {method_name}(*args, **kwargs):\n"
                    "        return None\n"
                )
            else:
                source = (
                    f"def {attribute}(*args, **kwargs):\n"
                    "    return None\n"
                )
            module.write_text(source, encoding="utf-8")

    def test_probe_detects_present_and_missing_callable(self) -> None:
        self.materialize_interfaces()
        config = _config(self.root)
        first = probe_battlestar_interfaces(config)
        self.assertTrue(all(result.available for result in first))

        oracle = self.root / ORACLE_MODULE_RELATIVE_PATH
        oracle.write_text("run_oracle_pipeline = None\n", encoding="utf-8")
        second = probe_battlestar_interfaces(config)
        oracle_result = next(item for item in second if item.family == "oracle")
        self.assertFalse(oracle_result.available)
        self.assertEqual(oracle_result.message, "entry point is not callable")


if __name__ == "__main__":
    unittest.main()
