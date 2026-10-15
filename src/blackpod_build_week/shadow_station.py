"""Local research service and desktop entry point; no decision or trading authority."""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
import io
from html import escape
from http.client import HTTPConnection
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import re
import signal
import stat
import subprocess
import sys
import tempfile
import threading
import time
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from .contracts.mission_request import parse_strict_json_object_bytes
from .decision_journal_store import _check_existing_ancestors, check_separate_root
from .hashing import canonical_json_bytes, sha256_bytes
from .sentry_history_cache import read_regular
from .shadow_station_collection import collection_due, run_collection, _off, _pinned_view

CONFIG_VERSION = "blackpod.shadow_station.v1"
STATE_VERSION = "blackpod.shadow_station_state.v1"
CONTROL_VERSION = "blackpod.shadow_station_control.v1"
EXPERIMENT_ID = "prospective-reversal-pilot-2026-10-14"
PROTOCOL_SHA256 = "b965ec0e8e1ad2cd57e356b8ecdcdd1fb1b352f54a7bc041f5a7cf3ddf0a111c"
LABEL = "com.blackpod.shadow-station"
CONFIG_KEYS = {"schema_version", "repo_root", "python_executable", "experiment_root", "runtime_root", "historical_root", "ui_root", "credentials_file", "credential_format", "experiment_id", "protocol_sha256", "station_root"}
PATH_KEYS = CONFIG_KEYS - {"schema_version", "credential_format", "experiment_id", "protocol_sha256"}


def utc_now():
    return datetime.now(timezone.utc)


def _stamp(now):
    return now.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def validate_config(document, expected_repo=None):
    if (not isinstance(document, dict) or set(document) != CONFIG_KEYS
            or document["schema_version"] != CONFIG_VERSION
            or document["experiment_id"] != EXPERIMENT_ID or document["protocol_sha256"] != PROTOCOL_SHA256
            or document["credential_format"] not in {"GALACTICA_YAML", "NAVIGATOR_ENV", "PAPER_ENV"}):
        raise ValueError("unsupported research station configuration")
    for key in PATH_KEYS:
        value = document[key]
        if (not isinstance(value, str) or not value or not Path(value).is_absolute()
                or ".." in Path(value).parts or any(ord(char) < 32 for char in value)):
            raise ValueError("station paths must be explicit absolute paths")
    repo = Path(expected_repo) if expected_repo is not None else Path(__file__).absolute().parents[2]
    root = Path(document["station_root"])
    if (Path(document["repo_root"]) != repo or root == repo / "output"
            or not root.is_relative_to(repo / "output")
            or Path(document["ui_root"]) != repo / "ui/dist"
            or Path(document["python_executable"]) != repo / ".venv/bin/python3.11"):
        raise ValueError("station must use this checkout and existing Python")
    _check_existing_ancestors(root)
    for key in ("experiment_root", "runtime_root", "historical_root", "ui_root"):
        _check_existing_ancestors(Path(document[key]))
        check_separate_root(root, Path(document[key]))
    protected = [Path(document[key]) for key in ("experiment_root", "runtime_root", "historical_root", "ui_root")]
    for index, first in enumerate(protected):
        for other in protected[index + 1:]:
            check_separate_root(first, other)
    check_separate_root(root, Path(document["credentials_file"]).parent)
    return dict(document)


def load_config(path):
    path = Path(path).absolute()
    document = validate_config(parse_strict_json_object_bytes(read_regular(path, max_bytes=32 * 1024)))
    if path.parent != Path(document["station_root"]):
        raise ValueError("configuration must live in its selected station root")
    return document


def read_state(path):
    path = Path(path)
    if not os.path.lexists(path):
        return {}
    try:
        return parse_strict_json_object_bytes(read_regular(path, max_bytes=128 * 1024))
    except (OSError, TypeError, ValueError) as exc:
        raise ValueError("invalid station state") from exc


def atomic_state(path, document):
    path = Path(path).absolute()
    _check_existing_ancestors(path.parent)
    if os.path.lexists(path):
        read_state(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = None
    try:
        descriptor, temporary = tempfile.mkstemp(prefix=".station-", dir=path.parent)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(canonical_json_bytes(document)); stream.flush(); os.fsync(stream.fileno())
        os.replace(temporary, path)
        temporary = None
        descriptor = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    finally:
        if temporary is not None:
            Path(temporary).unlink(missing_ok=True)


@contextmanager
def service_lock(root):
    root = Path(root).absolute()
    _check_existing_ancestors(root)
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd = os.open(root / ".station.lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise ValueError("station already running") from exc
        yield
    finally:
        os.close(fd)


def _code(value, default="UNAVAILABLE"):
    return value if isinstance(value, str) and re.fullmatch(r"[A-Z][A-Z0-9_]{0,90}", value) else default


def _clock_text(value):
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return _stamp(result) if result.tzinfo is not None else None
    except (AttributeError, TypeError, ValueError):
        return None


def public_status(config, state, *, now):
    heartbeat = _clock_text(state.get("heartbeat_at"))
    age = (now - datetime.fromisoformat(heartbeat.replace("Z", "+00:00"))).total_seconds() if heartbeat else None
    experiment, collector = state.get("experiment"), state.get("collector")
    experiment = experiment if isinstance(experiment, dict) else {}
    collector = collector if isinstance(collector, dict) else {}
    auto = state.get("auto_trading")
    auto = auto if isinstance(auto, dict) else {}
    attempt = collector.get("attempt_state")
    attempt = attempt if isinstance(attempt, dict) else {}
    fresh = state.get("serving") is True and age is not None and 0 <= age < 120
    auto_checked = _clock_text(auto.get("checked_at"))
    auto_age = (now - datetime.fromisoformat(auto_checked.replace("Z", "+00:00"))).total_seconds() if auto_checked else None
    off_verified = fresh and auto_age is not None and 0 <= auto_age < 120 and auto.get("state") == "OFF" and all(auto.get(key) is False for key in
        ("requested_entries_enabled", "entries_enabled", "worker_active", "auto_restart_enabled", "capital_transfers_permitted"))
    auto_label = "OFF" if off_verified else "UNVERIFIED" if auto.get("state") == "OFF" else _code(auto.get("state"))
    result = {"schema_version": "blackpod.shadow_station_status.v1", "status": "RUNNING" if state.get("serving") is True and age is not None and 0 <= age < 120 else "STALE_OR_STOPPED",
        "pid": state.get("pid") if type(state.get("pid")) is int else None,
        "heartbeat_at": heartbeat, "auto_trading": {"state": auto_label, "checked_at": auto_checked, "entries_enabled": auto.get("entries_enabled") if type(auto.get("entries_enabled")) is bool else None, "worker_active": auto.get("worker_active") if type(auto.get("worker_active")) is bool else None},
        "experiment": {"id": config["experiment_id"], "conclusion": _code(experiment.get("conclusion")),
            "latest_captured_at": _clock_text(experiment.get("latest_captured_at"))},
        "collector": {"enabled": collector.get("enabled") is True, "schedule": "18:30 America/Los_Angeles; stops after 2026-12-04",
            "reason": _code(collector.get("reason")), "next_attempt_at": _clock_text(collector.get("next_attempt_at")),
            "last_success_at": _clock_text(attempt.get("last_success_at")),
            "last_attempt_at": _clock_text(attempt.get("last_attempt_at")),
            "review_required": collector.get("review_required") is True}}
    for key in ("recorded_prediction_count", "observed_outcome_count", "missed_count", "missing_input_count"):
        value = experiment.get(key)
        result["experiment"][key] = value if type(value) is int and value >= 0 else None
    receipt = collector.get("last_result", {})
    receipt = receipt if isinstance(receipt, dict) else {}
    result["collector"]["last_result"] = {"status": _code(receipt.get("status"))}
    for key in ("provider_calls", "new_prediction_count", "new_outcome_count"):
        value = receipt.get(key)
        result["collector"]["last_result"][key] = value if type(value) is int and value >= 0 else None
    return result


class LocalStatusServer(ThreadingHTTPServer):
    daemon_threads = True
    def __init__(self, address, supplier, bind_and_activate=True, catalyst_supplier=None, catalyst_audit_supplier=None):
        self.status_supplier = supplier
        self.catalyst_supplier = catalyst_supplier
        self.catalyst_audit_supplier = catalyst_audit_supplier
        super().__init__(address, StatusHandler, bind_and_activate)


class LocalHandler(BaseHTTPRequestHandler):
    server_version = "BlackPodResearch"
    sys_version = ""
    def log_message(self, *_):
        pass
    def _local(self):
        expected = {f"127.0.0.1:{self.server.server_port}", f"localhost:{self.server.server_port}"}
        hosts, origins = self.headers.get_all("Host", []), self.headers.get_all("Origin", [])
        return (len(hosts) == 1 and hosts[0] in expected and self.headers.get("Sec-Fetch-Site") != "cross-site"
            and (not origins or origins == ["http://" + hosts[0]]))
    def _send(self, code, raw=b"Read-only resource unavailable.\n", content_type="text/plain; charset=utf-8"):
        self.send_response(code); self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(raw))); self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Cross-Origin-Resource-Policy", "same-origin")
        self.send_header("Content-Security-Policy", "default-src 'none'; style-src 'unsafe-inline'; img-src 'self' data:; object-src 'none'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(raw)
    def _deny(self):
        self._send(405 if self._local() else 403)
    do_POST = do_PUT = do_PATCH = do_DELETE = do_OPTIONS = do_CONNECT = do_TRACE = _deny


class StatusHandler(LocalHandler):
    def do_GET(self):
        if not self._local():
            self._send(403); return
        if self.path not in {"/", "/status.html", "/status.json", "/sentry", "/sentry.json", "/sentry-audit", "/sentry-audit.json"}:
            self._send(404); return
        if self.path in {"/sentry-audit", "/sentry-audit.json"}:
            if self.server.catalyst_audit_supplier is None:
                self._send(503); return
            from .sentry_catalyst_audit import render
            value = self.server.catalyst_audit_supplier()
            if self.path == "/sentry-audit.json":
                self._send(200, canonical_json_bytes(value), "application/json")
            else:
                self._send(200, render(value).encode(), "text/html; charset=utf-8")
            return
        if self.path in {"/sentry", "/sentry.json"}:
            if self.server.catalyst_supplier is None:
                self._send(503); return
            from .sentry_catalyst_presentation import render
            value = self.server.catalyst_supplier()
            if self.path == "/sentry.json":
                self._send(200, canonical_json_bytes(value), "application/json")
            else:
                self._send(200, render(value).encode(), "text/html; charset=utf-8")
            return
        status = self.server.status_supplier()
        if self.path == "/status.json":
            self._send(200, canonical_json_bytes(status), "application/json"); return
        collector, experiment = status["collector"], status["experiment"]
        def local_stamp(value):
            return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(ZoneInfo("America/Los_Angeles")).strftime("%b %d, %Y · %I:%M %p %Z") if value else None
        pairs = [("Background service", status["status"]), ("Auto-trading", status["auto_trading"]["state"]),
            ("Nightly collection", "Enabled" if collector["enabled"] else "Paused"), ("Schedule", collector["schedule"]),
            ("Next nightly collection", local_stamp(collector["next_attempt_at"])), ("Last successful collection", local_stamp(collector["last_success_at"])),
            ("Latest market evidence", local_stamp(experiment["latest_captured_at"])), ("Predictions recorded", experiment["recorded_prediction_count"]),
            ("Outcomes measured", experiment["observed_outcome_count"]), ("Collector state", collector["reason"])]
        rows = "".join("<div><dt>" + escape(key) + "</dt><dd>" + escape(str(value) if value is not None else "Not recorded") + "</dd></div>" for key, value in pairs)
        html = '<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta http-equiv="refresh" content="30"><title>BlackPod status</title><style>body{margin:0;padding:28px;background:#0d1922;color:#e5edf2;font:16px/1.6 system-ui}main{max-width:850px;margin:auto}a{color:#b3dce9}h1{letter-spacing:-.04em}dl>div{display:grid;grid-template-columns:1fr 1.3fr;gap:16px;border-bottom:1px solid #304b59;padding:12px 0}dt{color:#a9c0ce}dd{margin:0;overflow-wrap:anywhere}@media(max-width:600px){dl>div{grid-template-columns:1fr;gap:2px}}</style><main><p>BLACKPOD · RESEARCH MODULE</p><h1>Background service</h1><p>Dashboards and the frozen observational collector run independently of Codex.</p><dl>' + rows + '</dl><p>No trading authority. No orders or policy changes. Keep this Mac logged in; missed prediction deadlines remain missed.</p><p><a href="http://127.0.0.1:5183/sentry">Sentry</a> · <a href="http://127.0.0.1:5181/?view=research">Experiment</a> · <a href="http://127.0.0.1:5182/dashboard.html">Historical baseline</a></p></main></html>'
        self._send(200, html.encode(), "text/html; charset=utf-8")
    do_HEAD = do_GET


class SnapshotServer(ThreadingHTTPServer):
    daemon_threads = True
    def __init__(self, address, historical_root, bind_and_activate=True):
        self.historical_root = Path(historical_root)
        manifest = read_state(self.historical_root / "dashboard-manifest.json")
        allowed = {"dashboard.html", "report.html", "report.json", "rows.csv", "cohorts.json", "bundle-manifest.json"}
        self.file_hashes = {row["path"]: row["sha256"] for row in manifest.get("files", []) if row["path"] in allowed}
        self.file_hashes["dashboard-manifest.json"] = sha256_bytes(read_regular(self.historical_root / "dashboard-manifest.json"))
        super().__init__(address, SnapshotHandler, bind_and_activate)


class SnapshotHandler(LocalHandler):
    def do_GET(self):
        if not self._local():
            self._send(403); return
        path = self.path[1:] if self.path.startswith("/") else ""
        if path not in self.server.file_hashes:
            self._send(404); return
        try:
            raw = read_regular(self.server.historical_root / path, max_bytes=64 * 1024 * 1024)
            if sha256_bytes(raw) != self.server.file_hashes[path]:
                raise ValueError("historical presentation changed")
            suffix = Path(path).suffix
            content_type = {".html": "text/html; charset=utf-8", ".json": "application/json", ".csv": "text/csv; charset=utf-8"}[suffix]
            self._send(200, raw, content_type)
        except (OSError, ValueError):
            self._send(503)
    do_HEAD = do_GET


def verify_assets(config):
    from .shadow_historical_baseline_cli import verify_bundle
    _off(Path(config["runtime_root"]))
    view = _pinned_view(Path(config["experiment_root"]), config["experiment_id"], config["protocol_sha256"])
    verified = verify_bundle(Path(config["historical_root"]))
    root = Path(config["historical_root"])
    manifest = read_state(root / "dashboard-manifest.json")
    if (manifest.get("schema_version") != "blackpod.shadow_historical_dashboard.v1"
            or manifest.get("source_report_id") != verified["report_id"]
            or manifest.get("source_bundle_manifest_sha256") != sha256_bytes(read_regular(root / "bundle-manifest.json"))):
        raise ValueError("historical dashboard unavailable")
    for ref in manifest["files"]:
        from .contracts.decision_journal import validate_evidence_path
        path = validate_evidence_path(ref["path"])
        raw = read_regular(root / path, max_bytes=64 * 1024 * 1024)
        if len(raw) != ref["size_bytes"] or sha256_bytes(raw) != ref["sha256"]:
            raise ValueError("historical dashboard binding differs")
    read_regular(Path(config["ui_root"]) / "index.html")
    return view


def _control(config):
    control = read_state(Path(config["station_root"]) / "control.json")
    if not control:
        return False
    if set(control) != {"schema_version", "collection_enabled"} or control["schema_version"] != CONTROL_VERSION or type(control["collection_enabled"]) is not bool:
        raise ValueError("invalid collection control")
    return control["collection_enabled"]


def refresh_observations(config, state):
    """Refresh after collection; never label an old OFF snapshot newly verified."""
    from .auto_trading_runtime import runtime_status
    try:
        view = _pinned_view(Path(config["experiment_root"]), config["experiment_id"], config["protocol_sha256"])
        state["experiment"] = {"latest_captured_at": view["latest_captured_at"], **view["summary"]}
    except (ValueError, OSError, TypeError, KeyError, RuntimeError):
        state["experiment"] = {}
        state["collector"]["reason"] = "DATA_OR_OFF_GATE_BLOCKED"
    try:
        actual = runtime_status(Path(config["runtime_root"]))
        state["auto_trading"] = {**actual, "checked_at": _stamp(utc_now())}
        if actual.get("state") != "OFF" or any(actual.get(key) is not False for key in
                ("requested_entries_enabled", "entries_enabled", "worker_active", "auto_restart_enabled", "capital_transfers_permitted")):
            state["collector"]["reason"] = "DATA_OR_OFF_GATE_BLOCKED"
    except (ValueError, OSError, TypeError, KeyError, RuntimeError):
        state["auto_trading"] = {}
        state["collector"]["reason"] = "DATA_OR_OFF_GATE_BLOCKED"
    return state


class StationLogHandler(RotatingFileHandler):
    def _open(self):
        path = Path(self.baseFilename)
        _check_existing_ancestors(path.parent)
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND | os.O_NOFOLLOW, 0o600)
        try:
            metadata = os.fstat(descriptor)
            if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
                raise ValueError("station log must not alias evidence or other files")
            stream = io.open(descriptor, mode="a", encoding="utf-8")
            descriptor = None
            return stream
        finally:
            if descriptor is not None:
                os.close(descriptor)


def _log_handler(root):
    root = Path(root).absolute()
    _check_existing_ancestors(root)
    for name in ("service.log", "service.log.1", "service.log.2"):
        path = root / name
        if os.path.lexists(path):
            read_regular(path, max_bytes=1024 * 1024)
    return StationLogHandler(root / "service.log", maxBytes=256 * 1024, backupCount=2)


def run_station(config, *, stop_event=None):
    from .auto_trading_runtime import runtime_status
    from .cabin_reader import CabinHTTPServer, CabinReader
    from .shadow_experiment_reader import ShadowExperimentReader
    from .sentry_catalyst_service import start_worker, status as catalyst_status
    from .sentry_catalyst_audit import audit_status
    stop = stop_event if stop_event is not None else threading.Event()
    root = Path(config["station_root"])
    with service_lock(root):
        verify_assets(config)
        # Only this station's sanitized operational logs are mutable, never evidence.
        handler = _log_handler(root)
        logger = logging.getLogger("blackpod.shadow_station")
        logger.setLevel(logging.INFO); logger.propagate = False; logger.addHandler(handler)
        logger.info("SERVICE_START")
        state = read_state(root / "state.json")
        if state and state.get("schema_version") != STATE_VERSION:
            raise ValueError("unsupported retained station state")
        attempts = state.get("collector", {}).get("attempt_state", {})
        last_result = state.get("collector", {}).get("last_result", {})
        servers, threads = [], []
        try:
            servers.append(CabinHTTPServer(CabinReader(), Path(config["ui_root"]), 5181,
                shadow_experiment_reader=ShadowExperimentReader(Path(config["experiment_root"]))))
            servers.append(SnapshotServer(("127.0.0.1", 5182), Path(config["historical_root"])))
            servers.append(LocalStatusServer(("127.0.0.1", 5183), lambda: public_status(config, read_state(root / "state.json"), now=utc_now()),
                catalyst_supplier=lambda: catalyst_status(config),
                catalyst_audit_supplier=lambda: audit_status(config)))
            for server in servers:
                thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start(); threads.append(thread)
            if stop_event is None:
                signal.signal(signal.SIGTERM, lambda *_: stop.set())
                signal.signal(signal.SIGINT, lambda *_: stop.set())
            catalyst_thread = start_worker(config, stop)
            while not stop.is_set():
                if not catalyst_thread.is_alive():
                    catalyst_thread = start_worker(config, stop)
                if not all(thread.is_alive() for thread in threads):
                    raise ValueError("dashboard thread stopped")
                now, enabled = utc_now(), _control(config)
                state = {"schema_version": STATE_VERSION, "pid": os.getpid(), "heartbeat_at": _stamp(now), "serving": True,
                    "auto_trading": {}, "experiment": {}, "collector": {"enabled": enabled, "attempt_state": attempts, "last_result": last_result}}
                collector = state["collector"]
                try:
                    _off(Path(config["runtime_root"]))
                    state["auto_trading"] = runtime_status(Path(config["runtime_root"]))
                    view = _pinned_view(Path(config["experiment_root"]), config["experiment_id"], config["protocol_sha256"])
                    state["experiment"] = {"latest_captured_at": view["latest_captured_at"], **view["summary"]}
                    due = collection_due(now, attempts, view)
                    collector.update(reason=due["reason"] if enabled else "COLLECTION_PAUSED", next_attempt_at=due["next_attempt_at"],
                        review_required=due["reason"] in {"COMPLETE_MANUAL_REVIEW", "SCHEDULE_ENDED_MANUAL_REVIEW"})
                    if enabled and due["due"]:
                        attempts = due["attempt_state"]; collector["attempt_state"] = attempts
                        atomic_state(root / "state.json", state)  # Count an interrupted attempt before any GET.
                        last_result = run_collection(repo_root=Path(config["repo_root"]), python_executable=Path(config["python_executable"]),
                            experiment_root=Path(config["experiment_root"]), runtime_root=Path(config["runtime_root"]), credentials_file=Path(config["credentials_file"]),
                            credential_format=config["credential_format"], experiment_id=config["experiment_id"], protocol_sha256=config["protocol_sha256"])
                        if last_result["status"] == "VERIFIED":
                            attempts["last_success_at"] = _stamp(utc_now())
                        collector["last_result"] = last_result
                        collector["reason"] = last_result["status"]
                        logger.info("COLLECTION_%s predictions=%s outcomes=%s", _code(last_result["status"]), last_result["new_prediction_count"], last_result["new_outcome_count"])
                except (ValueError, OSError, TypeError, KeyError, RuntimeError):
                    collector["reason"] = "DATA_OR_OFF_GATE_BLOCKED"
                refresh_observations(config, state)
                state["heartbeat_at"] = _stamp(utc_now())
                atomic_state(root / "state.json", state)
                stop.wait(30)
        finally:
            stop.set()
            for server, thread in zip(servers, threads):
                server.shutdown(); thread.join(timeout=5)
            for server in servers:
                server.server_close()
            logger.info("SERVICE_STOP"); logger.removeHandler(handler); handler.close()


def _running_status():
    connection = HTTPConnection("127.0.0.1", 5183, timeout=2)
    try:
        connection.request("GET", "/status.json")
        response = connection.getresponse()
        if response.status != 200:
            raise ValueError("station health unavailable")
        return parse_strict_json_object_bytes(response.read(128 * 1024 + 1))
    finally:
        connection.close()


def open_station(config, config_path, *, no_browser=False):
    from .shadow_station_macos import _verify_agent
    agent = Path.home() / "Library/LaunchAgents" / (LABEL + ".plist")
    installed = _verify_agent(agent)
    expected = [config["python_executable"], "-m", "blackpod_build_week.shadow_station", "run", "--config", str(Path(config_path).absolute())]
    if installed.get("Label") != LABEL or installed.get("ProgramArguments") != expected:
        raise ValueError("installed agent differs from this station")
    domain = f"gui/{os.getuid()}"
    running = subprocess.run(["/bin/launchctl", "print", domain + "/" + LABEL], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10)
    if running.returncode:
        subprocess.run(["/bin/launchctl", "bootstrap", domain, str(agent)], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=20)
    deadline = time.monotonic() + 30
    while True:
        try:
            status = _running_status()
            if status["status"] == "RUNNING" and status["experiment"]["id"] == config["experiment_id"]:
                break
        except (OSError, ValueError, KeyError):
            pass
        if time.monotonic() >= deadline:
            raise ValueError("station did not become healthy")
        time.sleep(.5)
    if not no_browser:
        subprocess.run(["/usr/bin/open", "http://127.0.0.1:5181/?view=research"], check=True, timeout=10)
    return status


def main(argv=None):
    parser = argparse.ArgumentParser(description="BlackPod research app: read-only dashboards and frozen nightly collection")
    parser.add_argument("command", choices=("run", "check", "status", "open", "enable-collection", "disable-collection"))
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args(argv)
    try:
        config = load_config(args.config)
        if args.command == "run":
            run_station(config); return 0
        if args.command == "check":
            verify_assets(config); result = {"valid": True, "provider_calls": 0, "auto_trading_changed": False}
        elif args.command == "open":
            result = open_station(config, args.config, no_browser=args.no_browser)
        elif args.command in {"enable-collection", "disable-collection"}:
            if args.command == "enable-collection":
                verify_assets(config)
            atomic_state(Path(config["station_root"]) / "control.json", {"schema_version": CONTROL_VERSION, "collection_enabled": args.command == "enable-collection"})
            result = {"collection_enabled": args.command == "enable-collection", "auto_trading_changed": False}
        else:
            result = public_status(config, read_state(Path(config["station_root"]) / "state.json"), now=utc_now())
        print(json.dumps(result, sort_keys=True)); return 0
    except (ValueError, OSError, TypeError, KeyError, RuntimeError, subprocess.SubprocessError):
        print("BlackPod research station: configuration, service or verification unavailable; no trading settings changed.", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
