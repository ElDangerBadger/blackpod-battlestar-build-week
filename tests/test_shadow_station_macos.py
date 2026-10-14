"""Offline packaging checks: no launchd, GUI, provider, or broker calls."""
from __future__ import annotations

import contextlib
import io
import json
import os
from pathlib import Path
import plistlib
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from blackpod_build_week.shadow_station_macos import (
    APP_NAME, LABEL, PLIST_NAME, MacOSPackagingError, build_launch_agent,
    build_native_launcher, install_macos_package, main, prepare_macos_package,
    uninstall_macos_package,
)


class ShadowStationMacOSTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.repo = self.root / "BlackPod ' $(touch NEVER) `false` project"
        self.repo.mkdir()
        self.python = self.repo / ".venv/bin/python3.11"
        self.config = self.root / "station/config with ' quotes.json"
        self.config.parent.mkdir()
        self.config.write_text('{"api_secret":"NEVER_EMBED_THIS_SECRET"}')
        self.logs = self.root / "station/logs"
        self.binary = self.root / "fake-native"
        self.binary.write_bytes(b"\xcf\xfa\xed\xfefixtures are never executed")
        self.package = self.root / "prepared"
        self.apps = self.root / "Applications"
        self.agents = self.root / "Library/LaunchAgents"

    def prepare(self, **overrides):
        args = dict(repo_root=self.repo, python_executable=self.python, config_path=self.config, log_root=self.logs, native_executable=self.binary)
        args.update(overrides)
        return prepare_macos_package(self.package, **args)

    def install(self):
        return install_macos_package(self.package, applications_dir=self.apps, launch_agents_dir=self.agents)

    def uninstall(self):
        return uninstall_macos_package(applications_dir=self.apps, launch_agents_dir=self.agents)

    def test_launch_agent_is_fixed_argument_vector_and_login_only(self):
        agent = build_launch_agent(repo_root=self.repo, python_executable=self.python, config_path=self.config, log_root=self.logs)
        self.assertEqual(agent["Label"], LABEL)
        self.assertEqual(agent["ProgramArguments"], [str(self.python), "-m", "blackpod_build_week.shadow_station", "run", "--config", str(self.config)])
        self.assertEqual(agent["WorkingDirectory"], str(self.repo))
        self.assertIs(agent["KeepAlive"], True)
        self.assertIs(agent["RunAtLoad"], True)
        self.assertEqual(agent["LimitLoadToSessionType"], "Aqua")
        self.assertNotIn("StartCalendarInterval", agent)
        self.assertNotIn("StartInterval", agent)
        self.assertNotIn("LaunchEvents", agent)
        self.assertNotIn("Program", agent)
        self.assertEqual(agent["EnvironmentVariables"], {"PYTHONPATH": str(self.repo / "src"), "PYTHONDONTWRITEBYTECODE": "1"})
        self.assertEqual(agent["StandardOutPath"], "/dev/null")
        self.assertEqual(agent["StandardErrorPath"], "/dev/null")

    def test_paths_with_metacharacters_remain_literal_plist_strings(self):
        raw = plistlib.dumps(build_launch_agent(repo_root=self.repo, python_executable=self.python, config_path=self.config, log_root=self.logs))
        parsed = plistlib.loads(raw)
        self.assertEqual(parsed["ProgramArguments"][-1], str(self.config))
        self.assertEqual(parsed["ProgramArguments"][0], str(self.python))
        self.assertFalse((self.root / "NEVER").exists())

    def test_package_is_native_app_with_exact_config_and_no_secret_values(self):
        result = self.prepare()
        app = Path(result["app_path"])
        info = plistlib.loads((app / "Contents/Info.plist").read_bytes())
        self.assertEqual(info["CFBundleIdentifier"], LABEL)
        self.assertEqual(info["CFBundleExecutable"], "blackpod-shadow-station")
        self.assertEqual(info["BlackPodStationConfig"], str(self.config))
        self.assertEqual(info["BlackPodStationPython"], str(self.python))
        self.assertEqual(info["BlackPodStationRepository"], str(self.repo))
        executable = app / "Contents/MacOS/blackpod-shadow-station"
        self.assertEqual(executable.read_bytes(), self.binary.read_bytes())
        self.assertTrue(executable.stat().st_mode & 0o100)
        for path in self.package.rglob("*"):
            if path.is_file():
                self.assertNotIn(b"NEVER_EMBED_THIS_SECRET", path.read_bytes())
        self.assertEqual(self.config.read_text(), '{"api_secret":"NEVER_EMBED_THIS_SECRET"}')

    def test_preparation_is_idempotent(self):
        first = self.prepare()
        before = {str(path.relative_to(self.package)): path.stat().st_mtime_ns for path in self.package.rglob("*") if path.is_file()}
        self.assertEqual(self.prepare(), first)
        after = {str(path.relative_to(self.package)): path.stat().st_mtime_ns for path in self.package.rglob("*") if path.is_file()}
        self.assertEqual(before, after)

    def test_preparation_rejects_changed_package_parameters(self):
        self.prepare()
        with self.assertRaises(MacOSPackagingError):
            self.prepare(config_path=self.root / "other-config.json")

    def test_unrelated_preparation_directory_is_not_overwritten(self):
        self.package.mkdir()
        (self.package / "keep.txt").write_text("unrelated")
        with self.assertRaises(MacOSPackagingError):
            self.prepare()
        self.assertEqual((self.package / "keep.txt").read_text(), "unrelated")

    def test_install_and_uninstall_are_idempotent_and_never_start_services(self):
        self.prepare()
        with patch("blackpod_build_week.shadow_station_macos.subprocess.run") as run:
            first = self.install()
            self.assertTrue(first["app_changed"])
            self.assertTrue(first["launch_agent_changed"])
            self.assertFalse(first["service_started"])
            second = self.install()
            self.assertFalse(second["app_changed"])
            self.assertFalse(second["launch_agent_changed"])
            removed = self.uninstall()
            self.assertTrue(removed["app_removed"])
            self.assertTrue(removed["launch_agent_removed"])
            self.assertFalse(removed["processes_stopped"])
            self.assertFalse(self.uninstall()["app_removed"])
            run.assert_not_called()
        self.assertTrue(self.config.exists())
        self.assertTrue(self.package.exists())

    def test_install_replaces_only_owned_unchanged_old_artifacts(self):
        self.prepare()
        self.install()
        self.package = self.root / "new-package"
        changed_config = self.root / "other/config.json"
        self.prepare(config_path=changed_config)
        result = self.install()
        self.assertTrue(result["app_changed"])
        self.assertTrue(result["launch_agent_changed"])
        info = plistlib.loads((self.apps / APP_NAME / "Contents/Info.plist").read_bytes())
        self.assertEqual(info["BlackPodStationConfig"], str(changed_config))

    def test_unrelated_app_prevents_both_install_mutations(self):
        self.prepare()
        app = self.apps / APP_NAME
        app.mkdir(parents=True)
        (app / "precious").write_text("mine")
        with self.assertRaises(MacOSPackagingError):
            self.install()
        self.assertEqual((app / "precious").read_text(), "mine")
        self.assertFalse((self.agents / PLIST_NAME).exists())

    def test_unrelated_agent_prevents_both_install_mutations(self):
        self.prepare()
        self.agents.mkdir(parents=True)
        plist = self.agents / PLIST_NAME
        plist.write_bytes(plistlib.dumps({"Label": LABEL, "ProgramArguments": ["unrelated"]}))
        before = plist.read_bytes()
        with self.assertRaises(MacOSPackagingError):
            self.install()
        self.assertEqual(plist.read_bytes(), before)
        self.assertFalse((self.apps / APP_NAME).exists())

    def test_tampered_installed_app_blocks_upgrade_and_uninstall(self):
        self.prepare()
        self.install()
        executable = self.apps / APP_NAME / "Contents/MacOS/blackpod-shadow-station"
        executable.write_bytes(b"\xcf\xfa\xed\xfemodified")
        for operation in (self.install, self.uninstall):
            with self.assertRaises(MacOSPackagingError):
                operation()
        self.assertTrue((self.agents / PLIST_NAME).exists())
        self.assertTrue(executable.exists())

    def test_tampered_agent_blocks_uninstall_without_removing_app(self):
        self.prepare()
        self.install()
        plist = self.agents / PLIST_NAME
        contents = plistlib.loads(plist.read_bytes())
        contents["ProgramArguments"].append("--unexpected")
        plist.write_bytes(plistlib.dumps(contents))
        with self.assertRaises(MacOSPackagingError):
            self.uninstall()
        self.assertTrue((self.apps / APP_NAME).exists())

    def test_extra_file_or_symlink_in_bundle_is_a_conflict(self):
        self.prepare()
        extra = self.package / APP_NAME / "Contents/Resources/unexpected"
        extra.write_text("not owned")
        with self.assertRaises(MacOSPackagingError):
            self.install()
        extra.unlink()
        extra.symlink_to(self.config)
        with self.assertRaises(MacOSPackagingError):
            self.install()

    def test_symlink_destinations_and_ancestors_are_rejected(self):
        self.prepare()
        outside = self.root / "outside"
        outside.mkdir()
        link = self.root / "linked"
        link.symlink_to(outside, target_is_directory=True)
        with self.assertRaises(MacOSPackagingError):
            install_macos_package(self.package, applications_dir=link / "Applications", launch_agents_dir=self.agents)
        self.assertEqual(list(outside.iterdir()), [])
        self.apps.mkdir()
        (self.apps / APP_NAME).symlink_to(outside, target_is_directory=True)
        with self.assertRaises(MacOSPackagingError):
            self.install()

    def test_relative_and_parent_traversal_paths_are_rejected(self):
        for path in (Path("relative"), self.root / "a/../b"):
            with self.assertRaises(MacOSPackagingError):
                self.prepare(config_path=path)

    def test_changed_prepared_plist_or_manifest_is_rejected(self):
        self.prepare()
        manifest = self.package / "blackpod-shadow-station-package.json"
        contents = json.loads(manifest.read_text())
        contents["launch_agent_sha256"] = "0" * 64
        manifest.write_text(json.dumps(contents))
        with self.assertRaises(MacOSPackagingError):
            self.install()

    def test_install_recovers_owned_backup_after_interrupted_directory_swap(self):
        self.prepare()
        self.install()
        app = self.apps / APP_NAME
        backup = self.apps / ("." + APP_NAME + ".blackpod-backup")
        app.rename(backup)
        result = self.install()
        self.assertTrue(result["app_changed"])
        self.assertTrue(app.exists())
        self.assertFalse(backup.exists())

    def test_install_cleans_verified_backup_after_completed_swap(self):
        self.prepare()
        self.install()
        app = self.apps / APP_NAME
        backup = self.apps / ("." + APP_NAME + ".blackpod-backup")
        shutil.copytree(app, backup)
        self.assertTrue(self.install()["app_changed"])
        self.assertTrue(app.exists())
        self.assertFalse(backup.exists())

    def test_failed_swap_restores_old_app(self):
        self.prepare()
        self.install()
        old_info = (self.apps / APP_NAME / "Contents/Info.plist").read_bytes()
        self.package = self.root / "update"
        self.prepare(config_path=self.root / "new.json")
        rename = os.rename

        def fail_new(source, target):
            if Path(source).parent.name.startswith(".blackpod-app-") and Path(target) == self.apps / APP_NAME:
                raise OSError("simulated interrupted swap")
            return rename(source, target)

        with patch("blackpod_build_week.shadow_station_macos.os.rename", side_effect=fail_new):
            with self.assertRaises(OSError):
                self.install()
        self.assertEqual((self.apps / APP_NAME / "Contents/Info.plist").read_bytes(), old_info)
        self.assertFalse((self.apps / ("." + APP_NAME + ".blackpod-backup")).exists())
        self.assertTrue(self.install()["app_changed"])

    def test_unknown_backup_never_gets_removed(self):
        self.prepare()
        self.apps.mkdir()
        backup = self.apps / ("." + APP_NAME + ".blackpod-backup")
        backup.mkdir()
        (backup / "keep").write_text("mine")
        with self.assertRaises(MacOSPackagingError):
            self.install()
        self.assertEqual((backup / "keep").read_text(), "mine")

    def test_native_compile_uses_literal_arguments_and_bounded_execution(self):
        source = self.repo / "macos/BlackPodApp.swift"
        output = self.root / "native output $(false)"
        compiler = self.root / "compiler with ' quotes"

        def compile_fixture(arguments, **kwargs):
            self.assertEqual(arguments[0], str(compiler))
            self.assertIn(str(source), arguments)
            self.assertEqual(arguments[-2:], ["-o", str(output)])
            self.assertNotIn("shell", kwargs)
            self.assertEqual(kwargs["timeout"], 180)
            output.write_bytes(self.binary.read_bytes())
            return subprocess.CompletedProcess(arguments, 0)

        with patch("blackpod_build_week.shadow_station_macos.subprocess.run", side_effect=compile_fixture) as run:
            self.assertEqual(build_native_launcher(source_path=source, output_path=output, swift_compiler=compiler), str(output))
            run.assert_called_once()
        self.assertFalse(list(self.root.glob(".blackpod-swift-cache-*")))

    def test_native_compile_failure_is_safe_and_does_not_start_anything(self):
        with patch("blackpod_build_week.shadow_station_macos.subprocess.run", side_effect=subprocess.TimeoutExpired("swift", 180)):
            with self.assertRaises(MacOSPackagingError):
                build_native_launcher(source_path=self.root / "source.swift", output_path=self.root / "not-created", swift_compiler=self.root / "swiftc")
        self.assertFalse((self.root / "not-created").exists())

    def test_shell_script_is_not_accepted_as_native_app(self):
        self.binary.write_bytes(b"#!/bin/sh\nexit 0\n")
        with self.assertRaises(MacOSPackagingError):
            self.prepare()

    def test_cli_has_only_explicit_packaging_operations(self):
        arguments = ["prepare", "--destination", str(self.package), "--repo-root", str(self.repo), "--python-executable", str(self.python), "--config", str(self.config), "--log-root", str(self.logs), "--native-executable", str(self.binary)]
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(main(arguments), 0)
        self.assertEqual(json.loads(output.getvalue())["package_root"], str(self.package))
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                main(["enable-trading"])


if __name__ == "__main__":
    unittest.main()
