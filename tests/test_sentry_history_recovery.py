"""Recovery orchestration tests: fake providers, no network or canonical writes."""
from __future__ import annotations

import csv
from datetime import date, timedelta
import hashlib
import io
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import yaml

from blackpod_build_week.sentry_history_cache import CheckpointStore, CSV_COLUMNS, EMPTY_CSV, RecoveryError
from blackpod_build_week.sentry_history_recovery import RecoveryOptions, _lock, recover


class YFRateLimitError(Exception):
    pass


class YFPricesMissingError(Exception):
    pass


class YFTzMissingError(Exception):
    pass


def bars():
    return [{"date": "2026-09-15", "open": "10", "high": "12", "low": "9",
             "close": "11", "adj_close": "11", "volume": "10000"}]


def csv_bytes(rows):
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, CSV_COLUMNS)
    writer.writeheader()
    writer.writerows(rows)
    return output.getvalue().encode()


class Clock:
    def __init__(self):
        self.epoch = 1_789_600_000.0
        self.sleeps = []

    def now(self):
        return self.epoch

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.epoch += seconds


class Provider:
    def __init__(self, actions=None, *, constructor_error=None):
        self.actions = {key: list(value) for key, value in (actions or {}).items()}
        self.constructor_error = constructor_error
        self.calls = []

    def Ticker(self, symbol):
        if self.constructor_error is not None:
            raise self.constructor_error
        parent = self

        class Ticker:
            def history(self, **kwargs):
                parent.calls.append((symbol, kwargs))
                values = parent.actions.get(symbol, [])
                action = values.pop(0) if values else bars()
                if isinstance(action, BaseException):
                    raise action
                return action

        return Ticker()


class FakeCanonical:
    """Mimic only the public H25 facade, including its broad exception catch."""

    def __init__(self, package, symbols=("AAA", "BBB")):
        self.package = package
        self.symbols = symbols
        self.calls = []
        self.validation_calls = 0
        self.validation_error = None
        self.load_calls = 0
        self.configuration = SimpleNamespace(
            provider="yfinance", interval="1d", start="2026-07-18", end="2026-09-16",
            fleets=(str(package / "provisional_universe.yaml"),),
            out_dir=str(package / "h25_daily"),
            manifest=str(package / "bootstrap_backfill_manifest.json"),
            ledger=str(package / "bootstrap_backfill_ledger.jsonl"),
        )
        self.loaded = SimpleNamespace(plan=SimpleNamespace(
            provisional_symbols=symbols, history_start=date(2026, 7, 18),
            history_end_inclusive=date(2026, 9, 16), bootstrap_id="bootstrap-test",
            snapshot_id="snapshot-test",
        ))

    def load(self, package):
        self.load_calls += 1
        assert package == self.package
        return self.loaded

    def config(self, package):
        assert package == self.package
        return self.configuration

    def filename(self, symbol):
        return "".join(c if c.isalnum() or c in "-_" else "_" for c in symbol) + ".csv"

    def code_identity(self):
        return {"fake-public-h25": "a" * 64}

    def run(self, **kwargs):
        self.calls.append(kwargs)
        symbols = []
        for fleet in kwargs["fleet_paths"]:
            symbols.extend(row["symbol"] for row in yaml.safe_load(Path(fleet).read_text())["symbols"])
        output = Path(kwargs["out_dir"])
        output.mkdir(parents=True, exist_ok=True)
        series = []
        for symbol in symbols:
            blockers = []
            try:
                rows = kwargs["yf_module"].Ticker(symbol).history(
                    start=kwargs["start"],
                    end=(date.fromisoformat(kwargs["end"]) + timedelta(days=1)).isoformat(),
                    interval=kwargs["interval"], auto_adjust=False, actions=False,
                )
            except Exception as exc:
                rows = []
                blockers = [f"HISTORICAL_FETCH_FAILED:{symbol}:{type(exc).__name__}"]
            if not rows and not blockers:
                blockers = [f"NO_HISTORICAL_DATA:{symbol}"]
            data = csv_bytes(rows)
            (output / self.filename(symbol)).write_bytes(data)
            series.append({"symbol": symbol, "blockers": blockers, "row_count": len(rows),
                           "source": {"source_sha256": hashlib.sha256(data).hexdigest()}})
        manifest = {"series": series, "symbol_count_requested": len(symbols),
                    "symbol_count_failed": sum(bool(row["blockers"]) for row in series)}
        if kwargs.get("manifest_path"):
            Path(kwargs["manifest_path"]).write_text(json.dumps(manifest))
        if kwargs.get("ledger_path"):
            with Path(kwargs["ledger_path"]).open("a") as stream:
                stream.write(json.dumps(manifest) + "\n")
        return SimpleNamespace(manifest=manifest)

    def validate_handoff(self, loaded):
        assert loaded is self.loaded
        self.validation_calls += 1
        if self.validation_error:
            raise self.validation_error
        manifest = json.loads((self.package / "bootstrap_backfill_manifest.json").read_text())
        assert tuple(row["symbol"] for row in manifest["series"]) == self.symbols
        return {"complete": True}


class SentryHistoryRecoveryTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.artifacts = self.root / "artifacts"
        self.package = self.artifacts / "bootstrap"
        (self.package / "h25_daily").mkdir(parents=True)
        (self.package / "bootstrap_manifest.json").write_text('{"fixture":true}')
        self.bridge = FakeCanonical(self.package)
        self.write_fleet(self.bridge.symbols)
        self.clock = Clock()
        self.provider = Provider()
        self.factory = Mock(return_value=self.provider)
        self.options = RecoveryOptions(min_delay=1, timeout=2, retry_delay=1,
                                       cooldown=60, max_requests=10)
        self.events = []

    def write_fleet(self, symbols):
        (self.package / "provisional_universe.yaml").write_text(
            yaml.safe_dump({"symbols": [{"symbol": s} for s in symbols]}))

    def set_symbols(self, symbols):
        self.bridge.symbols = symbols
        self.bridge.loaded.plan.provisional_symbols = symbols
        self.write_fleet(symbols)

    def run_recovery(self, **updates):
        arguments = dict(artifacts_root=self.artifacts, options=self.options,
                         provider_factory=self.factory, now=self.clock.now,
                         sleep=self.clock.sleep, progress=self.events.append)
        arguments.update(updates)
        return recover(self.package, self.bridge, **arguments)

    def entries(self):
        state = json.loads((self.package / "recovery/state.json").read_text())
        return CheckpointStore(self.package / "recovery", state["identity"], state["start"],
                               state["end"], tuple(state["symbols"]),
                               lambda: "2026-09-17T00:00:00Z").entries

    def assert_no_publication(self):
        self.assertFalse((self.package / "bootstrap_backfill_manifest.json").exists())
        self.assertFalse((self.package / "bootstrap_backfill_ledger.jsonl").exists())
        self.assertEqual(self.bridge.validation_calls, 0)

    def test_offline_audit_never_constructs_provider_or_runs_h25(self):
        result = self.run_recovery(offline=True)
        self.assertEqual(result["status"], "OFFLINE_AUDIT")
        self.assertEqual(result["pending"], 2)
        self.factory.assert_not_called()
        self.assertEqual(self.bridge.calls, [])
        self.assert_no_publication()

    def test_offline_adoption_preserves_bytes_and_unknown_original_capture_time(self):
        data = csv_bytes(bars())
        original = self.package / "h25_daily/AAA.csv"
        original.write_bytes(data)
        result = self.run_recovery(offline=True, adopt_existing=True)
        self.assertEqual(result["adopted"], 1)
        self.assertEqual(original.read_bytes(), data)
        entry = self.entries()["AAA"]
        self.assertEqual(entry["source_kind"], "adopted_partial_h25")
        self.assertIsNone(entry["source_time"])
        self.assertEqual(entry["source_path"], str(original))
        self.assertEqual(entry["sha256"], hashlib.sha256(data).hexdigest())
        self.factory.assert_not_called()

    def test_empty_legacy_csv_remains_pending_and_is_not_replaced(self):
        original = self.package / "h25_daily/AAA.csv"
        original.write_bytes(EMPTY_CSV)
        result = self.run_recovery(offline=True, adopt_existing=True)
        self.assertEqual(result["invalid_existing"], 1)
        self.assertEqual(self.entries(), {})
        self.assertEqual(original.read_bytes(), EMPTY_CSV)

    def test_offline_cannot_publish(self):
        with self.assertRaises(RecoveryError):
            self.run_recovery(offline=True, publish_h25=True)
        self.factory.assert_not_called()
        self.assert_no_publication()

    def test_zero_budget_never_constructs_provider(self):
        result = self.run_recovery(options=RecoveryOptions(max_requests=0))
        self.assertEqual(result["status"], "BUDGET_PAUSED")
        self.assertEqual(result["requests"], 0)
        self.factory.assert_not_called()
        self.assert_no_publication()

    def test_budget_resume_skips_checkpointed_symbol_and_keeps_provenance(self):
        result = self.run_recovery(options=RecoveryOptions(max_requests=1))
        self.assertEqual(result["status"], "BUDGET_PAUSED")
        first_entry = self.entries()["AAA"]
        result = self.run_recovery()
        self.assertEqual(result["status"], "READY_TO_PUBLISH")
        self.assertEqual([symbol for symbol, _ in self.provider.calls], ["AAA", "BBB"])
        self.assertEqual(self.entries()["AAA"], first_entry)
        self.assert_no_publication()

    def test_sequential_request_shape_inclusive_end_timeout_and_exception_visibility(self):
        result = self.run_recovery()
        self.assertEqual(result["status"], "READY_TO_PUBLISH")
        self.assertEqual(len(self.provider.calls), 2)
        for _, request in self.provider.calls:
            self.assertEqual(request, {"start": "2026-07-18", "end": "2026-09-17",
                "interval": "1d", "auto_adjust": False, "actions": False,
                "timeout": 2, "raise_errors": True})
        self.assertGreaterEqual(sum(self.clock.sleeps), 1)
        self.assertTrue(all(call.get("manifest_path") is None for call in self.bridge.calls))
        self.assert_no_publication()

    def test_rate_limit_stops_immediately_without_empty_checkpoint_or_next_symbol(self):
        self.provider.actions = {"AAA": [YFRateLimitError("Too Many Requests")]}
        result = self.run_recovery(publish_h25=True)
        self.assertEqual(result["status"], "RATE_LIMITED")
        self.assertEqual(len(self.provider.calls), 1)
        self.assertEqual(self.entries(), {})
        self.assertEqual(list((self.package / "h25_daily").iterdir()), [])
        self.assert_no_publication()

    def test_later_rate_limit_preserves_completed_symbol_and_legacy_files(self):
        legacy = self.package / "h25_daily/BBB.csv"
        legacy.write_bytes(EMPTY_CSV)
        self.provider.actions = {"BBB": [YFRateLimitError()]}
        result = self.run_recovery(publish_h25=True)
        self.assertEqual(result["status"], "RATE_LIMITED")
        self.assertEqual(set(self.entries()), {"AAA"})
        self.assertEqual(self.entries()["AAA"]["status"], "ready")
        self.assertEqual(legacy.read_bytes(), EMPTY_CSV)
        self.assertEqual([symbol for symbol, _ in self.provider.calls], ["AAA", "BBB"])
        self.assert_no_publication()

    def test_http_429_and_constructor_rate_limit_also_stop(self):
        error = RuntimeError("provider error")
        error.response = SimpleNamespace(status_code=429)
        self.provider.constructor_error = error
        result = self.run_recovery()
        self.assertEqual(result["status"], "RATE_LIMITED")
        self.assertEqual(self.entries(), {})
        self.assertEqual(self.provider.calls, [])
        self.assertEqual(len(self.bridge.calls), 1)

    def test_cooldown_persists_across_invocations_then_allows_resume(self):
        self.provider.actions = {"AAA": [YFRateLimitError()]}
        self.assertEqual(self.run_recovery()["status"], "RATE_LIMITED")
        self.factory.reset_mock()
        result = self.run_recovery()
        self.assertEqual(result["status"], "COOLDOWN")
        self.factory.assert_not_called()
        self.clock.epoch += 61
        self.assertEqual(self.run_recovery()["status"], "READY_TO_PUBLISH")
        self.assertEqual(set(self.entries()), {"AAA", "BBB"})

    def test_invalid_persisted_cooldown_cannot_trigger_network(self):
        self.provider.actions = {"AAA": [YFRateLimitError()]}
        self.run_recovery()
        path = self.package / "recovery/control.json"
        control = json.loads(path.read_text())
        control["retry_not_before"] = True
        path.write_text(json.dumps(control))
        self.factory.reset_mock()
        with self.assertRaisesRegex(RecoveryError, "invalid persisted cooldown"):
            self.run_recovery()
        self.factory.assert_not_called()

    def test_control_json_rejects_duplicate_keys_and_non_objects(self):
        self.run_recovery(offline=True)
        path = self.package / "recovery/control.json"
        for value in ('[]', 'null', 'false', '{"retry_not_before":0,"retry_not_before":0}'):
            with self.subTest(value=value):
                path.write_text(value)
                with self.assertRaisesRegex(RecoveryError, "invalid recovery JSON"):
                    self.run_recovery()
        self.factory.assert_not_called()

    def test_generic_failures_retry_exponentially_in_short_sleep_chunks_then_pause(self):
        self.provider.actions = {"AAA": [TimeoutError()] * 4}
        options = RecoveryOptions(min_delay=1, timeout=2, max_attempts=4,
                                  retry_delay=10, cooldown=900, max_requests=10)
        result = self.run_recovery(options=options)
        self.assertEqual(result["status"], "RETRY_EXHAUSTED")
        self.assertEqual(len(self.provider.calls), 4)
        self.assertTrue(all(0 < delay <= 30 for delay in self.clock.sleeps))
        self.assertGreaterEqual(sum(self.clock.sleeps), 70)
        self.assertEqual(self.entries(), {})
        self.assert_no_publication()

    def test_repeated_explicit_missing_error_is_checkpointed_unavailable(self):
        self.provider.actions = {"AAA": [YFPricesMissingError(), YFPricesMissingError()]}
        result = self.run_recovery()
        self.assertEqual(result["status"], "READY_TO_PUBLISH")
        self.assertEqual(result["unavailable"], 1)
        self.assertEqual(self.entries()["AAA"]["reason"], "YFPricesMissingError")
        self.assertEqual(self.entries()["AAA"]["row_count"], 0)
        self.assertEqual([symbol for symbol, _ in self.provider.calls], ["AAA", "AAA", "BBB"])
        self.assert_no_publication()

    def test_three_consecutive_unavailable_symbols_trip_breaker_before_third_commit(self):
        self.set_symbols(("AAA", "BBB", "CCC", "DDD"))
        self.provider.actions = {symbol: [YFTzMissingError(), YFTzMissingError()]
                                 for symbol in self.bridge.symbols}
        result = self.run_recovery(publish_h25=True)
        self.assertEqual(result["status"], "PROVIDER_UNAVAILABLE")
        self.assertEqual(result["symbol"], "CCC")
        self.assertEqual(set(self.entries()), {"AAA", "BBB"})
        self.assertEqual([symbol for symbol, _ in self.provider.calls],
                         ["AAA", "AAA", "BBB", "BBB", "CCC", "CCC"])
        self.assert_no_publication()

    def test_unavailable_breaker_survives_budget_resume(self):
        self.set_symbols(("AAA", "BBB", "CCC"))
        self.provider.actions = {symbol: [YFPricesMissingError(), YFPricesMissingError()]
                                 for symbol in self.bridge.symbols}
        self.assertEqual(self.run_recovery(options=RecoveryOptions(max_requests=4))["status"],
                         "BUDGET_PAUSED")
        self.assertEqual(set(self.entries()), {"AAA", "BBB"})
        result = self.run_recovery(publish_h25=True)
        self.assertEqual(result["status"], "PROVIDER_UNAVAILABLE")
        self.assertEqual(set(self.entries()), {"AAA", "BBB"})
        self.assert_no_publication()

    def test_adopting_cached_history_does_not_reset_provider_failure_streak(self):
        self.set_symbols(("AAA", "BBB", "CCC", "DDD"))
        self.provider.actions = {symbol: [YFPricesMissingError(), YFPricesMissingError()]
                                 for symbol in ("AAA", "BBB", "DDD")}
        self.assertEqual(self.run_recovery(options=RecoveryOptions(max_requests=4))["status"],
                         "BUDGET_PAUSED")
        (self.package / "h25_daily/CCC.csv").write_bytes(csv_bytes(bars()))
        result = self.run_recovery(adopt_existing=True, publish_h25=True)
        self.assertEqual(result["status"], "PROVIDER_UNAVAILABLE")
        self.assertEqual(result["symbol"], "DDD")
        self.assertEqual(set(self.entries()), {"AAA", "BBB", "CCC"})
        self.assertEqual(self.entries()["CCC"]["operation"], "adopt")
        self.assert_no_publication()

    def test_unavailable_breaker_remains_effective_after_cooldown(self):
        self.set_symbols(("AAA", "BBB", "CCC"))
        self.provider.actions = {symbol: [YFTzMissingError()] * 4
                                 for symbol in self.bridge.symbols}
        self.assertEqual(self.run_recovery()["status"], "PROVIDER_UNAVAILABLE")
        self.clock.epoch += 61
        self.assertEqual(self.run_recovery(publish_h25=True)["status"], "PROVIDER_UNAVAILABLE")
        self.assertEqual(set(self.entries()), {"AAA", "BBB"})
        self.assert_no_publication()

    def test_invalid_persisted_provider_streak_is_rejected_before_network(self):
        self.provider.actions = {"AAA": [YFRateLimitError()]}
        self.run_recovery()
        path = self.package / "recovery/control.json"
        original = json.loads(path.read_text())
        self.factory.reset_mock()
        for value in (-1, True, 1.0, "2", None):
            with self.subTest(value=value):
                control = dict(original, provider_missing_streak=value)
                path.write_text(json.dumps(control))
                with self.assertRaises(RecoveryError):
                    self.run_recovery()
        self.factory.assert_not_called()

    def test_success_resets_consecutive_unavailable_breaker(self):
        self.set_symbols(("AAA", "BBB", "CCC", "DDD", "EEE"))
        self.provider.actions = {symbol: [YFPricesMissingError(), YFPricesMissingError()]
                                 for symbol in ("AAA", "BBB", "DDD", "EEE")}
        result = self.run_recovery()
        self.assertEqual(result["status"], "READY_TO_PUBLISH")
        self.assertEqual(result["ready"], 1)
        self.assertEqual(result["unavailable"], 4)
        self.assert_no_publication()

    def test_mixed_missing_errors_are_not_completed(self):
        self.provider.actions = {"AAA": [YFPricesMissingError(), YFTzMissingError()]}
        self.assertEqual(self.run_recovery()["status"], "RETRY_EXHAUSTED")
        self.assertEqual(self.entries(), {})

    def test_single_missing_result_under_one_attempt_does_not_establish_no_data(self):
        self.provider.actions = {"AAA": [YFTzMissingError()]}
        self.assertEqual(self.run_recovery(options=RecoveryOptions(max_attempts=1))["status"],
                         "RETRY_EXHAUSTED")
        self.assertEqual(self.entries(), {})

    def test_repeated_silent_empty_history_is_not_no_data_evidence(self):
        self.provider.actions = {"AAA": [[], []]}
        result = self.run_recovery()
        self.assertEqual(result["status"], "RETRY_EXHAUSTED")
        self.assertEqual(result["error_type"], "EMPTY_OR_INVALID_PROVIDER_DATA")
        self.assertEqual(self.entries(), {})

    def test_publication_uses_complete_cache_without_provider_and_preserves_originals(self):
        original = self.package / "h25_daily/AAA.csv"
        original.write_bytes(csv_bytes(bars()))
        self.run_recovery(adopt_existing=True)
        metadata = self.entries()
        self.factory.reset_mock()
        result = self.run_recovery(publish_h25=True, options=RecoveryOptions(max_requests=0))
        self.assertEqual(result["status"], "COMPLETE")
        self.factory.assert_not_called()
        self.assertEqual(self.bridge.validation_calls, 1)
        self.assertEqual(self.entries(), metadata)
        self.assertEqual((self.package / "recovery/original_daily/AAA.csv").read_bytes(),
                         csv_bytes(bars()))
        final = self.bridge.calls[-1]
        self.assertEqual(final["fleet_paths"], self.bridge.configuration.fleets)
        self.assertEqual(final["out_dir"], self.bridge.configuration.out_dir)
        self.assertEqual(final["manifest_path"], self.bridge.configuration.manifest)
        self.assertEqual(final["ledger_path"], self.bridge.configuration.ledger)

    def test_mixed_ready_unavailable_publication_preserves_failure_and_fleet_order(self):
        self.provider.actions = {"AAA": [YFTzMissingError(), YFTzMissingError()]}
        result = self.run_recovery(publish_h25=True)
        self.assertEqual(result["status"], "COMPLETE")
        manifest = json.loads((self.package / "bootstrap_backfill_manifest.json").read_text())
        self.assertEqual([row["symbol"] for row in manifest["series"]], ["AAA", "BBB"])
        self.assertEqual(manifest["symbol_count_failed"], 1)
        self.assertIn("RecordedUnavailable", manifest["series"][0]["blockers"][0])
        self.assertEqual(self.bridge.validation_calls, 1)

    def test_validator_failure_is_not_reported_as_complete(self):
        self.bridge.validation_error = RecoveryError("handoff mismatch")
        with self.assertRaisesRegex(RecoveryError, "handoff mismatch"):
            self.run_recovery(publish_h25=True)
        self.assertFalse(any(event["status"] == "COMPLETE" for event in self.events))

    def test_existing_manifest_requires_complete_recovery_checkpoint(self):
        (self.package / "bootstrap_backfill_manifest.json").write_text("{}")
        with self.assertRaisesRegex(RecoveryError, "complete recovery checkpoint"):
            self.run_recovery()
        self.factory.assert_not_called()

    def test_completed_manifest_is_verified_without_provider_or_rewrite(self):
        self.run_recovery(publish_h25=True)
        existing = (self.package / "bootstrap_backfill_manifest.json").read_bytes()
        calls = len(self.bridge.calls)
        self.factory.reset_mock()
        self.assertEqual(self.run_recovery()["status"], "COMPLETE")
        self.factory.assert_not_called()
        self.assertEqual(len(self.bridge.calls), calls)
        self.assertEqual((self.package / "bootstrap_backfill_manifest.json").read_bytes(), existing)
        self.assertEqual(self.bridge.validation_calls, 2)

    def test_filename_collisions_fail_before_provider_and_cache(self):
        self.bridge.loaded.plan.provisional_symbols = ("A.B", "A_B")
        with self.assertRaisesRegex(RecoveryError, "colliding"):
            self.run_recovery()
        self.factory.assert_not_called()
        self.assertFalse((self.package / "recovery/state.json").exists())

    def test_unsafe_canonical_output_is_rejected_without_outside_write(self):
        outside = self.root / "outside"
        self.bridge.configuration.out_dir = str(outside)
        with self.assertRaisesRegex(RecoveryError, "unsafe canonical out_dir"):
            self.run_recovery()
        self.assertFalse(outside.exists())
        self.factory.assert_not_called()

    def test_package_outside_artifacts_root_is_rejected_before_canonical_load(self):
        with self.assertRaises(RecoveryError):
            self.run_recovery(artifacts_root=self.root / "unrelated")
        self.assertEqual(self.bridge.load_calls, 0)
        self.factory.assert_not_called()

    def test_symlink_inside_package_is_rejected_before_provider_or_canonical_load(self):
        target = self.root / "unrelated.csv"
        target.write_bytes(csv_bytes(bars()))
        (self.package / "h25_daily/AAA.csv").symlink_to(target)
        before = target.read_bytes()
        with self.assertRaisesRegex(RecoveryError, "symlink"):
            self.run_recovery(adopt_existing=True)
        self.assertEqual(target.read_bytes(), before)
        self.assertEqual(self.bridge.load_calls, 0)
        self.factory.assert_not_called()

    def test_checkpoint_tamper_is_rejected_before_provider_or_publication(self):
        self.run_recovery()
        entry = self.entries()["AAA"]
        (self.package / "recovery/cache" / entry["file_name"]).write_bytes(EMPTY_CSV)
        self.factory.reset_mock()
        with self.assertRaises(RecoveryError):
            self.run_recovery(publish_h25=True)
        self.factory.assert_not_called()
        self.assert_no_publication()

    def test_checkpoint_write_failure_is_not_misreported_as_bad_provider_data(self):
        with patch.object(CheckpointStore, "record", side_effect=RecoveryError("checkpoint disk failure")):
            with self.assertRaisesRegex(RecoveryError, "checkpoint disk failure"):
                self.run_recovery()
        self.assertEqual(len(self.provider.calls), 1)
        self.assertEqual(self.entries(), {})
        self.assertFalse((self.package / "recovery/control.json").exists())
        self.assert_no_publication()

    def test_adoption_write_failure_is_not_misreported_as_invalid_legacy_data(self):
        original = self.package / "h25_daily/AAA.csv"
        original.write_bytes(csv_bytes(bars()))
        with patch.object(CheckpointStore, "adopt", side_effect=RecoveryError("adoption disk failure")):
            with self.assertRaisesRegex(RecoveryError, "adoption disk failure"):
                self.run_recovery(offline=True, adopt_existing=True)
        self.assertEqual(original.read_bytes(), csv_bytes(bars()))
        self.assertEqual(self.entries(), {})
        self.factory.assert_not_called()

    def test_options_reject_unsafe_limits(self):
        for arguments in ({"min_delay": 0.5}, {"min_delay": 61}, {"timeout": 61},
                          {"cooldown": 59}, {"cooldown": 86401},
                          {"max_requests": -1}, {"max_requests": 10001}, {"max_requests": True},
                          {"max_attempts": 0}, {"max_attempts": 6}, {"retry_delay": float("inf")},
                          {"timeout": float("nan")}, {"min_delay": True}):
            with self.subTest(arguments=arguments), self.assertRaises(RecoveryError):
                RecoveryOptions(**arguments)

    def test_package_lock_excludes_overlapping_recovery(self):
        original_load = self.bridge.load
        attempted = []

        def load_while_locked(package):
            with self.assertRaisesRegex(RecoveryError, "another recovery process"):
                self.run_recovery(offline=True)
            attempted.append(True)
            return original_load(package)

        self.bridge.load = load_while_locked
        self.assertEqual(self.run_recovery(offline=True)["status"], "OFFLINE_AUDIT")
        self.assertEqual(attempted, [True])
        self.factory.assert_not_called()

    def test_lock_rejects_nonregular_file(self):
        directory = self.package / "lock-fixture"
        directory.mkdir()
        os.mkfifo(directory / ".lock")
        with self.assertRaisesRegex(RecoveryError, "unsafe recovery lock"):
            with _lock(directory):
                self.fail("FIFO must not become the recovery lock")


if __name__ == "__main__":
    unittest.main()
