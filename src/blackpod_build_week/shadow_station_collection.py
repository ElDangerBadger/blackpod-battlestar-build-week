"""Bounded scheduling adapter for the existing frozen observational collector.

No forecast or price arithmetic lives here. The unchanged collector owns actual
wall-clock admission, immutable source pins, missing observations and outcomes.
The caller persists attempt state under its own single-process lock.
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
import json
import os
from pathlib import Path
import re
import subprocess
from zoneinfo import ZoneInfo

from .hashing import canonical_json_bytes, sha256_bytes

LA = ZoneInfo("America/Los_Angeles")
FINAL_COLLECTION_DATE = date(2026, 12, 4)
ATTEMPT_LIMIT = 3
RETRY_SECONDS = 300


def _utc_now():
    return datetime.now(timezone.utc)


def _clock(value):
    if isinstance(value, str):
        value = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("station requires an aware clock")
    return value.astimezone(timezone.utc)


def _stamp(value):
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _scheduled(day):
    return datetime.combine(day, time(18, 30), LA).astimezone(timezone.utc)


def _has_ready_work(view, now):
    protocol = view["protocol"]
    available = timedelta(seconds=protocol["availability_buffer_seconds"])
    predictions = view["predictions"]
    retained = {(row["signal_session"], row["symbol"]) for row in predictions}
    for signal in protocol["sessions"]:
        if _clock(signal["session_close_at"]) + available <= now and any(
                (signal["date"], symbol) not in retained for symbol in protocol["universe"]):
            return True
    finished = {row["prediction_id"] for row in view["outcomes"]}
    return any(row["prediction_id"] not in finished and _clock(row["outcome_available_at"]) <= now
               for row in predictions)


def collection_due(now: datetime, state: dict, view: dict) -> dict:
    """Pure LA-local daily schedule; startup never substitutes a recording clock.

    State fields are due_date, attempt_count, last_attempt_at and last_success_at.
    An earlier daytime capture does not count as that evening's success. An
    overdue original opportunity can be retained as missed by the real collector;
    this adapter never reconstructs it or manufactures another signal session.
    """
    now = _clock(now)
    local = now.astimezone(LA)
    result = {"due": False, "reason": "NOT_DUE", "due_date": None,
              "next_attempt_at": None, "attempts": 0}
    if local.date() > FINAL_COLLECTION_DATE:
        return {**result, "reason": "SCHEDULE_ENDED_MANUAL_REVIEW"}
    summary = view["summary"]
    if (summary["conclusion"] != "PENDING" and summary["pending_prediction_count"] == 0
            and summary["pending_outcome_count"] == 0):
        return {**result, "reason": "COMPLETE_MANUAL_REVIEW"}
    first = date.fromisoformat(view["protocol"]["first_signal_session"])
    day = local.date() if now >= _scheduled(local.date()) else local.date() - timedelta(days=1)
    if day < first:
        return {**result, "next_attempt_at": _stamp(_scheduled(first))}
    due_at = _scheduled(day)
    result["due_date"] = day.isoformat()
    if state.get("last_success_at") is not None and _clock(state["last_success_at"]) > now:
        raise ValueError("station success clock is in the future")
    if state.get("last_success_at") is not None and _clock(state["last_success_at"]) >= due_at:
        return {**result, "reason": "ALREADY_COLLECTED", "next_attempt_at": _stamp(_scheduled(day + timedelta(days=1)))}
    attempts = state.get("attempt_count", 0) if state.get("due_date") == day.isoformat() else 0
    if type(attempts) is not int or not 0 <= attempts <= ATTEMPT_LIMIT:
        raise ValueError("station attempt count is invalid")
    result["attempts"] = attempts
    if attempts == ATTEMPT_LIMIT:
        return {**result, "reason": "RETRIES_EXHAUSTED", "next_attempt_at": _stamp(_scheduled(day + timedelta(days=1)))}
    if attempts:
        last = _clock(state["last_attempt_at"])
        if last < due_at or last > now:
            raise ValueError("station attempt clock differs from its due day")
        retry = last + timedelta(seconds=RETRY_SECONDS)
        if now < retry:
            return {**result, "reason": "RETRY_WAIT", "next_attempt_at": _stamp(retry)}
    if not _has_ready_work(view, now):
        return {**result, "reason": "NO_READY_ORIGINAL_OPPORTUNITY",
                "next_attempt_at": _stamp(_scheduled(day + timedelta(days=1)))}
    return {**result, "due": True, "reason": "COLLECT_ORIGINAL_OPPORTUNITIES",
            "attempt_state": {"due_date": day.isoformat(), "attempt_count": attempts + 1,
                              "last_attempt_at": _stamp(now), "last_success_at": state.get("last_success_at")}}


def _read_view(root):
    from .shadow_experiment import read_experiment_view
    return read_experiment_view(root)


def _off(root):
    from .auto_trading_runtime import runtime_status
    status = runtime_status(root)
    if (status["state"] != "OFF" or any(status.get(field) is not False for field in
            ("requested_entries_enabled", "entries_enabled", "worker_active", "auto_restart_enabled", "capital_transfers_permitted"))):
        raise ValueError("station requires auto-trading OFF")


def _pinned_view(root, experiment_id, protocol_sha256):
    if not isinstance(protocol_sha256, str) or not re.fullmatch(r"[a-f0-9]{64}", protocol_sha256):
        raise ValueError("invalid frozen protocol pin")
    view = _read_view(root)
    if (view["protocol"]["experiment_id"] != experiment_id
            or sha256_bytes(canonical_json_bytes(view["protocol"])) != protocol_sha256):
        raise ValueError("frozen experiment differs from station pins")
    return view


def _retained_delta(before, after):
    result = {"event_head": after["journal"]["last_entry_sha256"],
              "new_prediction_count": after["summary"]["recorded_prediction_count"] - before["summary"]["recorded_prediction_count"],
              "new_outcome_count": len(after["outcomes"]) - len(before["outcomes"])}
    if any(type(result[field]) is not int or not 0 <= result[field] <= 60
           for field in ("new_prediction_count", "new_outcome_count")):
        raise ValueError("collector counts are invalid")
    return result


def run_collection(*, repo_root, python_executable, experiment_root, runtime_root,
                   credentials_file, credential_format, experiment_id,
                   protocol_sha256, timeout_seconds=120) -> dict:
    """Call only the existing CLI, with bounded time and sanitized results.

    Secrets and provider bodies are never copied into service receipts. Failures
    return constant codes; raw subprocess output and exception text are discarded.
    Runtime, protocol and journal verification fail closed before a provider call.
    """
    result = {"status": "BLOCKED", "provider_calls": None, "new_prediction_count": 0,
              "new_outcome_count": 0, "event_head": None}
    try:
        if _utc_now().astimezone(LA).date() > FINAL_COLLECTION_DATE:
            raise ValueError("station collection cap has elapsed")
        paths = [Path(item) for item in (repo_root, python_executable, experiment_root, runtime_root, credentials_file)]
        if any(not item.is_absolute() or ".." in item.parts or any(ord(c) < 32 for c in str(item)) for item in paths):
            raise ValueError("station paths must be absolute and normalized")
        if credential_format not in {"GALACTICA_YAML", "NAVIGATOR_ENV", "PAPER_ENV"}:
            raise ValueError("invalid credential format")
        if type(timeout_seconds) is not int or not 1 <= timeout_seconds <= 300:
            raise ValueError("invalid collector timeout")
        _off(runtime_root)
        before = _pinned_view(experiment_root, experiment_id, protocol_sha256)
        result["event_head"] = before["journal"]["last_entry_sha256"]
        argv = [str(python_executable), "-m", "blackpod_build_week.shadow_experiment_cli", "collect",
                "--experiment-root", str(experiment_root), "--runtime-root", str(runtime_root),
                "--credentials-file", str(credentials_file), "--credential-format", credential_format]
        environment = os.environ.copy()
        environment.update(PYTHONDONTWRITEBYTECODE="1", PYTHONPATH=str(Path(repo_root) / "src"))
        timed_out = False
        try:
            child = subprocess.run(argv, cwd=str(repo_root), env=environment, shell=False,
                                   stdin=subprocess.DEVNULL, capture_output=True,
                                   timeout=timeout_seconds, check=False)
        except subprocess.TimeoutExpired:
            # subprocess.run kills and waits for this non-forking CLI. An append
            # may already have committed: verify it instead of claiming zero work.
            timed_out = True
        _off(runtime_root)
        after = _pinned_view(experiment_root, experiment_id, protocol_sha256)
        result.update(_retained_delta(before, after))
        if timed_out:
            return {**result, "status": "TIMED_OUT"}
        if child.returncode != 0:
            return {**result, "status": "COLLECTION_FAILED"}
        if len(child.stdout) > 1024 * 1024:
            raise ValueError("collector result exceeds limit")
        payload = json.loads(child.stdout)
        if (not isinstance(payload, dict) or payload.get("command") != "collect"
                or type(payload.get("provider_calls")) is not int or payload["provider_calls"] not in {0, 2}):
            raise ValueError("collector result differs from expected interface")
        return {**result, "status": "VERIFIED", "provider_calls": payload["provider_calls"]}
    except (ValueError, TypeError, KeyError, OSError, RuntimeError):
        return result
