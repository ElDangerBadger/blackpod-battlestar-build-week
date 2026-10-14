"""Prepare and install the user-owned macOS research station wrappers.

This module does not start services, submit orders, read credentials, or change
the experiment. A LaunchAgent runs the separate shadow_station supervisor after
user login. Neither launchd nor this wrapper promises collection while asleep,
powered off, or logged out. Installation is explicit, and unrelated artifacts
are never overwritten. launchctl lifecycle operations belong to the caller.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import plistlib
import platform
import shutil
import stat
import subprocess
import tempfile


LABEL = "com.blackpod.shadow-station"
APP_NAME = "BlackPod.app"
PLIST_NAME = LABEL + ".plist"
_OWNER = "blackpod-shadow-station-macos-v1"
_APP_OWNER = Path("Contents/Resources/blackpod-shadow-station.owner.json")
_APP_PAYLOAD = (Path("Contents/Info.plist"), Path("Contents/MacOS/blackpod-shadow-station"))
_PACKAGE_OWNER = "blackpod-shadow-station-package.json"
_PLIST_OWNER_KEY = "BlackPodShadowStationOwnership"
_MAX_ARTIFACT_BYTES = 1024 * 1024


class MacOSPackagingError(ValueError):
    """An unsafe path, conflicting artifact, or modified wrapper was found."""


def _json_bytes(value):
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode()


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _absolute(value):
    path = Path(value)
    if not path.is_absolute() or ".." in path.parts or "\x00" in str(path):
        raise MacOSPackagingError("packaging paths must be absolute without parent traversal")
    return path


def _safe_directory(path, *, create=False):
    path = _absolute(path)
    if path == Path(path.anchor):
        raise MacOSPackagingError("filesystem root is not an artifact directory")
    for parent in (*reversed(path.parents), path):
        if parent.is_symlink():
            raise MacOSPackagingError("artifact directories cannot use symlinks")
        if parent.exists() and not parent.is_dir():
            raise MacOSPackagingError("artifact parent is not a directory")
    if create:
        path.mkdir(mode=0o700, parents=True, exist_ok=True)
    return path


def _read_file(path):
    try:
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        with os.fdopen(descriptor, "rb") as stream:
            metadata = os.fstat(stream.fileno())
            if not stat.S_ISREG(metadata.st_mode) or metadata.st_size > _MAX_ARTIFACT_BYTES:
                raise MacOSPackagingError("wrapper must be a bounded regular file")
            return stream.read(_MAX_ARTIFACT_BYTES + 1)
    except OSError as exc:
        raise MacOSPackagingError("cannot safely read wrapper artifact") from exc


def _sync_directory(path):
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _write_file(path, raw, mode):
    _safe_directory(path.parent, create=True)
    descriptor, temporary = tempfile.mkstemp(prefix="." + path.name + ".", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fchmod(stream.fileno(), mode)
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        _sync_directory(path.parent)
    finally:
        if os.path.lexists(temporary):
            os.unlink(temporary)


def build_native_launcher(*, source_path, output_path, swift_compiler):
    """Compile the local AppKit shell with an argument vector, never a shell."""
    source, output, compiler = map(_absolute, (source_path, output_path, swift_compiler))
    _safe_directory(output.parent, create=True)
    if os.path.lexists(output):
        raise MacOSPackagingError("native compiler output must be a new path")
    with tempfile.TemporaryDirectory(prefix=".blackpod-swift-cache-", dir=output.parent) as cache:
        try:
            sdk = compiler.parents[4] / "Platforms/MacOSX.platform/Developer/SDKs/MacOSX.sdk" if len(compiler.parents) > 4 else None
            options = ["-sdk", str(sdk), "-target", platform.machine() + "-apple-macosx12.0"] if sdk is not None and sdk.is_dir() else []
            subprocess.run([str(compiler), "-O", *options, "-module-cache-path", cache, "-framework", "AppKit", "-framework", "WebKit", str(source), "-o", str(output)], check=True, capture_output=True, timeout=180)
        except (OSError, subprocess.SubprocessError) as exc:
            raise MacOSPackagingError("native app compilation failed; inspect the local Swift toolchain") from exc
    _read_native_binary(output)
    output.chmod(0o755)
    return str(output)


def _read_native_binary(path):
    # Compiled Mach-O wrappers are larger than property lists, but are bounded.
    try:
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        with os.fdopen(descriptor, "rb") as stream:
            metadata = os.fstat(stream.fileno())
            if not stat.S_ISREG(metadata.st_mode) or not 4 <= metadata.st_size <= 32 * 1024 * 1024:
                raise MacOSPackagingError("native launcher must be a bounded regular binary")
            raw = stream.read(32 * 1024 * 1024 + 1)
            if raw[:4] not in (b"\xcf\xfa\xed\xfe", b"\xfe\xed\xfa\xcf", b"\xca\xfe\xba\xbe", b"\xbe\xba\xfe\xca"):
                raise MacOSPackagingError("native launcher is not a Mach-O executable")
            return raw
    except OSError as exc:
        raise MacOSPackagingError("cannot safely read native app launcher") from exc


def build_launch_agent(*, repo_root, python_executable, config_path, log_root):
    """Return the fixed login supervisor LaunchAgent, without installing it."""
    repo, python, config, logs = map(_absolute, (repo_root, python_executable, config_path, log_root))
    payload = {
        "Label": LABEL,
        "ProgramArguments": [str(python), "-m", "blackpod_build_week.shadow_station", "run", "--config", str(config)],
        "WorkingDirectory": str(repo),
        "EnvironmentVariables": {"PYTHONPATH": str(repo / "src"), "PYTHONDONTWRITEBYTECODE": "1"},
        "RunAtLoad": True,
        "KeepAlive": True,
        "LimitLoadToSessionType": "Aqua",
        "ProcessType": "Background",
        "ThrottleInterval": 30,
        "ExitTimeOut": 20,
        "StandardOutPath": "/dev/null",
        "StandardErrorPath": "/dev/null",
    }
    payload[_PLIST_OWNER_KEY] = {"owner": _OWNER, "sha256": _sha(plistlib.dumps(payload, sort_keys=True))}
    return payload


def _verify_agent(path):
    try:
        payload = plistlib.loads(_read_file(path))
        if not isinstance(payload, dict):
            raise ValueError("not a mapping")
        ownership = payload.pop(_PLIST_OWNER_KEY, None)
        if ownership != {"owner": _OWNER, "sha256": _sha(plistlib.dumps(payload, sort_keys=True))}:
            raise ValueError("ownership mismatch")
        if payload.get("Label") != LABEL:
            raise ValueError("label mismatch")
        payload[_PLIST_OWNER_KEY] = ownership
        return payload
    except (ValueError, TypeError, plistlib.InvalidFileException) as exc:
        raise MacOSPackagingError("LaunchAgent is unrelated or has been modified") from exc


def _verify_app(path):
    _safe_directory(path)
    try:
        expected = {str(item) for item in (*_APP_PAYLOAD, _APP_OWNER)}
        actual = set()
        directories = set()
        for parent, dirs, files in os.walk(path, followlinks=False):
            for name in (*dirs, *files):
                child = Path(parent) / name
                if child.is_symlink():
                    raise MacOSPackagingError("app bundle cannot contain symlinks")
            actual.update(str((Path(parent) / name).relative_to(path)) for name in files)
            directories.update(str((Path(parent) / name).relative_to(path)) for name in dirs)
        if actual != expected or directories != {"Contents", "Contents/MacOS", "Contents/Resources"}:
            raise MacOSPackagingError("app bundle contains unexpected or missing files")
        ownership = json.loads(_read_file(path / _APP_OWNER))
        hashes = {str(item): _sha(_read_native_binary(path / item) if item == _APP_PAYLOAD[1] else _read_file(path / item)) for item in _APP_PAYLOAD}
        if ownership != {"owner": _OWNER, "kind": "app", "files": hashes}:
            raise MacOSPackagingError("app bundle is unrelated or has been modified")
        info = plistlib.loads(_read_file(path / "Contents/Info.plist"))
        if info.get("CFBundleIdentifier") != LABEL:
            raise MacOSPackagingError("app bundle identifier does not match")
        if not (path / _APP_PAYLOAD[1]).stat().st_mode & stat.S_IXUSR:
            raise MacOSPackagingError("app launcher is not executable")
        return hashes
    except (ValueError, TypeError, OSError, plistlib.InvalidFileException) as exc:
        raise MacOSPackagingError("cannot verify owned app bundle") from exc


def _app_bytes(*, repo_root, python_executable, config_path, native_executable):
    info = {
        "CFBundleIdentifier": LABEL,
        "CFBundleName": "BlackPod",
        "CFBundleDisplayName": "BlackPod Research Station",
        "CFBundleExecutable": "blackpod-shadow-station",
        "CFBundlePackageType": "APPL",
        "CFBundleVersion": "1",
        "CFBundleShortVersionString": "1.0",
        "LSMinimumSystemVersion": "12.0",
        "LSUIElement": False,
        "NSHighResolutionCapable": True,
        "NSAppTransportSecurity": {"NSAllowsLocalNetworking": True},
        "NSHumanReadableCopyright": "BlackPod research module. Read-only dashboards; frozen shadow collection only.",
        "BlackPodStationConfig": str(_absolute(config_path)),
        "BlackPodStationPython": str(_absolute(python_executable)),
        "BlackPodStationRepository": str(_absolute(repo_root)),
    }
    files = {
        str(_APP_PAYLOAD[0]): plistlib.dumps(info, sort_keys=True),
        str(_APP_PAYLOAD[1]): _read_native_binary(native_executable),
    }
    files[str(_APP_OWNER)] = _json_bytes({"owner": _OWNER, "kind": "app", "files": {name: _sha(raw) for name, raw in files.items()}})
    return files


def _verify_package(package):
    _safe_directory(package)
    if {child.name for child in package.iterdir()} != {APP_NAME, PLIST_NAME, _PACKAGE_OWNER}:
        raise MacOSPackagingError("package contains unexpected or missing artifacts")
    app_hashes = _verify_app(package / APP_NAME)
    _verify_agent(package / PLIST_NAME)
    expected = {"owner": _OWNER, "kind": "package", "app_files": app_hashes, "launch_agent_sha256": _sha(_read_file(package / PLIST_NAME))}
    try:
        if json.loads(_read_file(package / _PACKAGE_OWNER)) != expected:
            raise MacOSPackagingError("package ownership manifest differs")
    except (ValueError, TypeError) as exc:
        raise MacOSPackagingError("invalid package ownership manifest") from exc
    return expected


def prepare_macos_package(destination, *, repo_root, python_executable, config_path, log_root, native_executable=None, swift_compiler=None):
    """Stage reviewable wrappers. Existing identical owned output is reused."""
    destination = _absolute(destination)
    if native_executable is None:
        compiler = swift_compiler or "/Applications/Xcode.app/Contents/Developer/Toolchains/XcodeDefault.xctoolchain/usr/bin/swiftc"
        parent = _safe_directory(destination.parent, create=True)
        with tempfile.TemporaryDirectory(prefix=".blackpod-native-build-", dir=parent) as temporary:
            binary = Path(temporary) / "blackpod-shadow-station"
            build_native_launcher(source_path=_absolute(repo_root) / "macos/BlackPodApp.swift", output_path=binary, swift_compiler=compiler)
            return prepare_macos_package(destination, repo_root=repo_root, python_executable=python_executable, config_path=config_path, log_root=log_root, native_executable=binary)
    app_files = _app_bytes(repo_root=repo_root, python_executable=python_executable, config_path=config_path, native_executable=native_executable)
    plist = plistlib.dumps(build_launch_agent(repo_root=repo_root, python_executable=python_executable, config_path=config_path, log_root=log_root), sort_keys=True)
    manifest = {"owner": _OWNER, "kind": "package", "app_files": {name: _sha(app_files[name]) for name in map(str, _APP_PAYLOAD)}, "launch_agent_sha256": _sha(plist)}
    if os.path.lexists(destination):
        if _verify_package(destination) != manifest:
            raise MacOSPackagingError("existing prepared package differs; use a new destination")
    else:
        parent = _safe_directory(destination.parent, create=True)
        temporary = Path(tempfile.mkdtemp(prefix=".blackpod-package-", dir=parent))
        try:
            for name, raw in app_files.items():
                _write_file(temporary / APP_NAME / name, raw, 0o755 if name == str(_APP_PAYLOAD[1]) else 0o644)
            _write_file(temporary / PLIST_NAME, plist, 0o600)
            _write_file(temporary / _PACKAGE_OWNER, _json_bytes(manifest), 0o600)
            _verify_package(temporary)
            if os.path.lexists(destination):
                raise MacOSPackagingError("package destination appeared during preparation")
            os.rename(temporary, destination)
            _sync_directory(parent)
        finally:
            if temporary.exists():
                shutil.rmtree(temporary)
    return {"package_root": str(destination), "app_path": str(destination / APP_NAME), "launch_agent_path": str(destination / PLIST_NAME)}


def _install_app(source, target):
    expected = _verify_app(source)
    # The reserved backup enables recovery if interrupted between directory
    # renames. Never remove or replace an unverified backup or target.
    backup = target.with_name("." + target.name + ".blackpod-backup")
    recovered = False
    if os.path.lexists(backup):
        _verify_app(backup)
        if not os.path.lexists(target):
            os.rename(backup, target)
        else:
            _verify_app(target)
            shutil.rmtree(backup)
        recovered = True
        _sync_directory(target.parent)
    if os.path.lexists(target) and _verify_app(target) == expected:
        return recovered
    temporary = Path(tempfile.mkdtemp(prefix=".blackpod-app-", dir=target.parent))
    candidate = temporary / APP_NAME
    try:
        shutil.copytree(source, candidate, symlinks=False)
        _verify_app(candidate)
        if os.path.lexists(target):
            _verify_app(target)
            os.rename(target, backup)
        try:
            os.rename(candidate, target)
            _sync_directory(target.parent)
        except BaseException:
            if backup.exists() and not os.path.lexists(target):
                os.rename(backup, target)
            raise
        if backup.exists():
            shutil.rmtree(backup)
            _sync_directory(target.parent)
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)
    return True


def install_macos_package(package_root, *, applications_dir, launch_agents_dir):
    """Install verified owned wrappers only. Does not invoke launchctl."""
    package = _absolute(package_root)
    _verify_package(package)
    apps = _safe_directory(applications_dir)
    agents = _safe_directory(launch_agents_dir)
    app, plist = apps / APP_NAME, agents / PLIST_NAME
    # Check both ownership conflicts before installing either artifact.
    if os.path.lexists(app):
        _verify_app(app)
    if os.path.lexists(plist):
        _verify_agent(plist)
    backup = app.with_name("." + app.name + ".blackpod-backup")
    if os.path.lexists(backup):
        _verify_app(backup)
    _safe_directory(apps, create=True)
    _safe_directory(agents, create=True)
    payload = _verify_agent(package / PLIST_NAME)
    for key in ("StandardOutPath", "StandardErrorPath"):
        _safe_directory(Path(payload[key]).parent, create=True)
    app_changed = _install_app(package / APP_NAME, app)
    raw = _read_file(package / PLIST_NAME)
    plist_changed = not os.path.lexists(plist) or _read_file(plist) != raw
    if plist_changed:
        _write_file(plist, raw, 0o600)
    return {"app_path": str(app), "launch_agent_path": str(plist), "app_changed": app_changed, "launch_agent_changed": plist_changed, "service_started": False}


def uninstall_macos_package(*, applications_dir, launch_agents_dir):
    """Remove only verified owned wrappers; never stop arbitrary processes."""
    apps = _safe_directory(applications_dir)
    agents = _safe_directory(launch_agents_dir)
    app, plist = apps / APP_NAME, agents / PLIST_NAME
    app_present, plist_present = os.path.lexists(app), os.path.lexists(plist)
    backup = app.with_name("." + app.name + ".blackpod-backup")
    for candidate in (app, backup):
        if os.path.lexists(candidate):
            _verify_app(candidate)
    if plist_present:
        _verify_agent(plist)
    if app_present:
        shutil.rmtree(app)
        _sync_directory(apps)
    if os.path.lexists(backup):
        shutil.rmtree(backup)
        _sync_directory(apps)
    if plist_present:
        plist.unlink()
        _sync_directory(agents)
    return {"app_removed": app_present, "launch_agent_removed": plist_present, "processes_stopped": False}


def main(argv=None):
    parser = argparse.ArgumentParser(description="Explicit macOS packaging for the BlackPod shadow research station")
    subparsers = parser.add_subparsers(dest="command", required=True)
    prepare = subparsers.add_parser("prepare")
    for name in ("destination", "repo-root", "python-executable", "config", "log-root"):
        prepare.add_argument("--" + name, type=Path, required=True)
    prepare.add_argument("--native-executable", type=Path)
    prepare.add_argument("--swift-compiler", type=Path)
    install = subparsers.add_parser("install")
    install.add_argument("--package-root", type=Path, required=True)
    uninstall = subparsers.add_parser("uninstall")
    for command in (install, uninstall):
        command.add_argument("--applications-dir", type=Path, required=True)
        command.add_argument("--launch-agents-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "prepare":
            result = prepare_macos_package(args.destination, repo_root=args.repo_root, python_executable=args.python_executable, config_path=args.config, log_root=args.log_root, native_executable=args.native_executable, swift_compiler=args.swift_compiler)
        elif args.command == "install":
            result = install_macos_package(args.package_root, applications_dir=args.applications_dir, launch_agents_dir=args.launch_agents_dir)
        else:
            result = uninstall_macos_package(applications_dir=args.applications_dir, launch_agents_dir=args.launch_agents_dir)
        print(json.dumps(result, sort_keys=True))
        return 0
    except (MacOSPackagingError, OSError) as exc:
        print(json.dumps({"error": type(exc).__name__, "message": str(exc)}), file=__import__("sys").stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
