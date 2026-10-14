"""Offline station scheduling and subprocess contracts; no provider calls."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import subprocess
import unittest
from unittest import mock

from blackpod_build_week.hashing import canonical_json_bytes, sha256_bytes
from blackpod_build_week import shadow_station_collection as station


def clock(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def view():
    return {"protocol": {"experiment_id": "frozen-pilot", "first_signal_session": "2026-10-14",
                         "availability_buffer_seconds": 900, "universe": ["QQQ", "SPY"],
                         "sessions": [{"date": "2026-10-14", "session_close_at": "2026-10-15T00:00:00Z"}]},
            "summary": {"conclusion": "PENDING", "pending_prediction_count": 60,
                        "pending_outcome_count": 0, "recorded_prediction_count": 0},
            "predictions": [], "outcomes": [], "journal": {"last_entry_sha256": "a" * 64}}


def attempted(at="2026-10-15T01:30:00Z", count=1):
    return {"due_date": "2026-10-14", "attempt_count": count,
            "last_attempt_at": at, "last_success_at": None}


class StationScheduleTests(unittest.TestCase):
    def test_first_day_before_schedule_does_not_collect_earlier_context(self):
        result = station.collection_due(clock("2026-10-14T18:32:00Z"), {}, view())
        self.assertFalse(result["due"])
        self.assertEqual(result["next_attempt_at"], "2026-10-15T01:30:00Z")

    def test_first_schedule_is_1830_los_angeles(self):
        result = station.collection_due(clock("2026-10-15T01:30:00Z"), {}, view())
        self.assertTrue(result["due"])
        self.assertEqual(result["due_date"], "2026-10-14")
        self.assertEqual(result["attempt_state"], attempted())

    def test_early_daytime_success_does_not_suppress_evening_prediction(self):
        state = {"last_success_at": "2026-10-14T18:32:00Z"}
        self.assertTrue(station.collection_due(clock("2026-10-15T01:30:00Z"), state, view())["due"])

    def test_success_in_due_window_suppresses_repeated_provider_calls(self):
        state = {**attempted(), "last_success_at": "2026-10-15T01:30:10Z"}
        result = station.collection_due(clock("2026-10-15T01:31:00Z"), state, view())
        self.assertEqual(result["reason"], "ALREADY_COLLECTED")
        self.assertFalse(result["due"])

    def test_restart_recovers_previous_due_day_before_next_evening(self):
        result = station.collection_due(clock("2026-10-15T08:30:00Z"), {}, view())
        self.assertTrue(result["due"])
        self.assertEqual(result["due_date"], "2026-10-14")

    def test_late_restart_delegates_honest_missing_status_never_supplies_clock(self):
        result = station.collection_due(clock("2026-10-15T16:00:00Z"), {}, view())
        self.assertTrue(result["due"])
        self.assertEqual(result["due_date"], "2026-10-14")
        self.assertNotIn("recorded_at", result)

    def test_retry_wait_and_three_attempt_bound_survive_restart(self):
        self.assertEqual(station.collection_due(clock("2026-10-15T01:34:59Z"), attempted(), view())["reason"], "RETRY_WAIT")
        result = station.collection_due(clock("2026-10-15T01:35:00Z"), attempted(), view())
        self.assertTrue(result["due"])
        self.assertEqual(result["attempt_state"]["attempt_count"], 2)
        self.assertEqual(station.collection_due(clock("2026-10-15T01:50:00Z"), attempted(count=3), view())["reason"], "RETRIES_EXHAUSTED")

    def test_next_due_day_gets_only_three_fresh_attempts(self):
        result = station.collection_due(clock("2026-10-16T01:30:00Z"), attempted(count=3), view())
        self.assertTrue(result["due"])
        self.assertEqual(result["attempt_state"]["attempt_count"], 1)
        self.assertEqual(result["due_date"], "2026-10-15")

    def test_daylight_saving_uses_1830_local(self):
        result = station.collection_due(clock("2026-11-03T02:30:00Z"), {}, view())
        self.assertTrue(result["due"])
        self.assertEqual(result["due_date"], "2026-11-02")
        self.assertEqual(result["attempt_state"]["last_attempt_at"], "2026-11-03T02:30:00Z")

    def test_source_close_buffer_prevents_unready_work(self):
        original = view()
        original["protocol"]["sessions"][0]["session_close_at"] = "2026-10-15T02:00:00Z"
        self.assertEqual(station.collection_due(clock("2026-10-15T01:30:00Z"), {}, original)["reason"], "NO_READY_ORIGINAL_OPPORTUNITY")
        self.assertTrue(station.collection_due(clock("2026-10-15T02:15:00Z"), {}, original)["due"])

    def test_recorded_symbols_do_not_trigger_duplicate_work(self):
        original = view()
        original["predictions"] = [{"signal_session": "2026-10-14", "symbol": symbol, "prediction_id": symbol,
                                    "outcome_available_at": "2026-10-17T00:15:00Z"} for symbol in ("QQQ", "SPY")]
        self.assertFalse(station.collection_due(clock("2026-10-15T01:30:00Z"), {}, original)["due"])
        self.assertTrue(station.collection_due(clock("2026-10-17T01:30:00Z"), {}, original)["due"])
        original["outcomes"] = [{"prediction_id": symbol} for symbol in ("QQQ", "SPY")]
        self.assertFalse(station.collection_due(clock("2026-10-17T01:30:00Z"), {}, original)["due"])

    def test_ended_experiment_with_pending_original_outcomes_collects_until_cap(self):
        original = view()
        original["summary"].update(conclusion="INCONCLUSIVE_MISSING_EVIDENCE", pending_prediction_count=0, pending_outcome_count=1)
        self.assertTrue(station.collection_due(clock("2026-12-05T02:30:00Z"), {}, original)["due"])
        result = station.collection_due(clock("2026-12-05T08:00:00Z"), {}, original)
        self.assertFalse(result["due"])
        self.assertEqual(result["reason"], "SCHEDULE_ENDED_MANUAL_REVIEW")

    def test_complete_pilot_requests_manual_review_without_extension(self):
        original = view()
        original["summary"].update(conclusion="DESCRIPTIVE_NONPOSITIVE_PROXY", pending_prediction_count=0, pending_outcome_count=0)
        result = station.collection_due(clock("2026-11-28T02:30:00Z"), {}, original)
        self.assertFalse(result["due"])
        self.assertEqual(result["reason"], "COMPLETE_MANUAL_REVIEW")

    def test_naive_or_future_state_clocks_rejected(self):
        with self.assertRaises(ValueError):
            station.collection_due(datetime(2026, 10, 15), {}, view())
        with self.assertRaises(ValueError):
            station.collection_due(clock("2026-10-15T01:30:00Z"), {"last_success_at": "2026-10-16T00:00:00Z"}, view())
        with self.assertRaises(ValueError):
            station.collection_due(clock("2026-10-15T01:30:00Z"), attempted(at="2026-10-15T02:00:00Z"), view())

    def test_bad_attempt_state_rejected(self):
        for value in (True, -1, 4, "1"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                station.collection_due(clock("2026-10-15T01:30:00Z"), attempted(count=value), view())

    def test_inputs_not_modified(self):
        state, original = attempted(), view()
        retained = deepcopy((state, original))
        station.collection_due(clock("2026-10-15T01:35:00Z"), state, original)
        self.assertEqual((state, original), retained)


class StationRunnerTests(unittest.TestCase):
    def setUp(self):
        self.now = self.enterContext(mock.patch.object(station, "_utc_now", return_value=clock("2026-10-15T01:30:00Z")))
        self.before = view()
        self.after = deepcopy(self.before)
        self.after["summary"]["recorded_prediction_count"] = 2
        self.after["outcomes"] = [{"prediction_id": "original"}]
        self.after["journal"]["last_entry_sha256"] = "b" * 64
        self.arguments = dict(repo_root=Path("/repository"), python_executable=Path("/repository/.venv/bin/python3.11"),
                              experiment_root=Path("/repository/output/pilot/journal"), runtime_root=Path("/repository/output/runtime"),
                              credentials_file=Path("/credentials/keys.yaml"), credential_format="GALACTICA_YAML",
                              experiment_id="frozen-pilot", protocol_sha256=sha256_bytes(canonical_json_bytes(self.before["protocol"])))
        self.off = self.enterContext(mock.patch.object(station, "_off"))
        self.reader = self.enterContext(mock.patch.object(station, "_read_view", side_effect=[self.before, self.after]))
        self.child = self.enterContext(mock.patch.object(station.subprocess, "run", return_value=subprocess.CompletedProcess(
            [], 0, json.dumps({"command": "collect", "provider_calls": 2, "secret": "DO_NOT_RETAIN"}).encode(), b"DO_NOT_RETAIN")))

    def test_only_exact_existing_collect_cli_no_shell_or_recording_clock(self):
        result = station.run_collection(**self.arguments)
        self.assertEqual(result, {"status": "VERIFIED", "provider_calls": 2, "new_prediction_count": 2,
                                  "new_outcome_count": 1, "event_head": "b" * 64})
        args, kwargs = self.child.call_args
        self.assertEqual(args[0], ["/repository/.venv/bin/python3.11", "-m", "blackpod_build_week.shadow_experiment_cli", "collect",
                                  "--experiment-root", "/repository/output/pilot/journal", "--runtime-root", "/repository/output/runtime",
                                  "--credentials-file", "/credentials/keys.yaml", "--credential-format", "GALACTICA_YAML"])
        self.assertFalse(kwargs["shell"])
        self.assertEqual(kwargs["timeout"], 120)
        self.assertEqual(kwargs["env"]["PYTHONDONTWRITEBYTECODE"], "1")
        self.assertEqual(self.off.call_count, 2)

    def test_preexisting_on_runtime_blocks_before_subprocess(self):
        self.off.side_effect = ValueError("DO_NOT_RETAIN")
        self.assertEqual(station.run_collection(**self.arguments)["status"], "BLOCKED")
        self.child.assert_not_called()

    def test_changed_runtime_blocks_postflight(self):
        self.off.side_effect = [None, ValueError("DO_NOT_RETAIN")]
        self.assertEqual(station.run_collection(**self.arguments)["status"], "BLOCKED")

    def test_wrong_id_hash_or_invalid_journal_blocks_before_subprocess(self):
        for updates in ({"experiment_id": "another-trial"}, {"protocol_sha256": "c" * 64}, {"protocol_sha256": "invalid"}):
            with self.subTest(updates=updates):
                self.reader.side_effect = [self.before]
                self.assertEqual(station.run_collection(**{**self.arguments, **updates})["status"], "BLOCKED")
        self.child.assert_not_called()
        self.reader.side_effect = RuntimeError("sensitive local path")
        self.assertEqual(station.run_collection(**self.arguments)["status"], "BLOCKED")

    def test_timeout_does_not_emit_partial_output_or_error_detail(self):
        self.child.side_effect = subprocess.TimeoutExpired("DO_NOT_RETAIN", 120, output=b"DO_NOT_RETAIN", stderr=b"DO_NOT_RETAIN")
        result = station.run_collection(**self.arguments)
        self.assertEqual(result["status"], "TIMED_OUT")
        self.assertNotIn("DO_NOT_RETAIN", json.dumps(result))

    def test_failure_discards_both_streams_but_reverifies_journal(self):
        self.child.return_value = subprocess.CompletedProcess([], 2, b"secret", b"secret")
        result = station.run_collection(**self.arguments)
        self.assertEqual(result["status"], "COLLECTION_FAILED")
        self.assertEqual(result["event_head"], "b" * 64)
        self.assertNotIn("secret", json.dumps(result))

    def test_changed_postflight_protocol_is_rejected(self):
        self.after["protocol"]["experiment_id"] = "another-trial"
        self.assertEqual(station.run_collection(**self.arguments)["status"], "BLOCKED")

    def test_malformed_or_unexpected_stdout_is_rejected_without_echo(self):
        for payload in (b"DO_NOT_RETAIN", b"[]", b'{"command":"collect","provider_calls":true}',
                        b'{"command":"freeze","provider_calls":2}', b'{"command":"collect","provider_calls":3}'):
            with self.subTest(payload=payload):
                self.reader.side_effect = [self.before, self.after]
                self.child.return_value = subprocess.CompletedProcess([], 0, payload, b"secret")
                result = station.run_collection(**self.arguments)
                self.assertEqual(result["status"], "BLOCKED")
                self.assertNotIn("secret", json.dumps(result))

    def test_invalid_paths_timeout_and_format_block_before_subprocess(self):
        for updates in ({"repo_root": Path("relative")}, {"experiment_root": Path("/one/../two")},
                        {"timeout_seconds": 301}, {"timeout_seconds": True}, {"credential_format": "OTHER"}):
            with self.subTest(updates=updates):
                self.assertEqual(station.run_collection(**{**self.arguments, **updates})["status"], "BLOCKED")
        self.child.assert_not_called()

    def test_runner_cap_blocks_even_if_schedule_is_bypassed(self):
        self.now.return_value = clock("2026-12-05T08:00:00Z")
        self.assertEqual(station.run_collection(**self.arguments)["status"], "BLOCKED")
        self.child.assert_not_called()

    def test_timeout_retains_committed_work_and_verifies_after_kill(self):
        self.child.side_effect = subprocess.TimeoutExpired("collect", 120)
        result = station.run_collection(**self.arguments)
        self.assertEqual(result["status"], "TIMED_OUT")
        self.assertEqual(result["new_prediction_count"], 2)
        self.assertEqual(result["event_head"], "b" * 64)
        self.assertEqual(self.reader.call_count, 2)
        self.assertEqual(self.off.call_count, 2)


class StationOffGuardTests(unittest.TestCase):
    def test_strict_off_no_requested_entries_worker_restart_or_transfers(self):
        off = {"state": "OFF", "requested_entries_enabled": False, "entries_enabled": False,
               "worker_active": False, "auto_restart_enabled": False, "capital_transfers_permitted": False}
        with mock.patch("blackpod_build_week.auto_trading_runtime.runtime_status", return_value=off):
            station._off(Path("/runtime"))
        for field in off:
            changed = {**off, field: "ON" if field == "state" else True}
            with self.subTest(field=field), mock.patch("blackpod_build_week.auto_trading_runtime.runtime_status", return_value=changed):
                with self.assertRaises(ValueError):
                    station._off(Path("/runtime"))


if __name__ == "__main__":
    unittest.main()
