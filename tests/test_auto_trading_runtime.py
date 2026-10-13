"""Offline runtime controls; synthetic pins, fake processes, injected workers."""
from __future__ import annotations

import copy
import io
import json
import os
from pathlib import Path
import socket
import sys
import tempfile
import unittest
from unittest import mock

from blackpod_build_week import auto_trading_cli, auto_trading_worker
from blackpod_build_week import auto_trading_runtime as runtime_module
from blackpod_build_week.auto_trading_runtime import (
    MODULE_FILES, PROFILE_SCHEMA, RuntimeLedger, TradingRuntimeError,
    account_lock, disable_trading, enable_trading, profile_hash, runtime_status, source_manifest,
    validate_profile,
)
from blackpod_build_week.hashing import canonical_json_bytes, sha256_bytes

NOW = "2026-10-15T00:00:00Z"
EXPIRY = "2026-10-15T01:00:00Z"


class RuntimeFixture:
    def __init__(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.base = Path(self.temporary.name).resolve()
        self.source = self.base / "synthetic-native"
        self.source.mkdir()
        for name in MODULE_FILES:
            path = self.source / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("# Non-executable synthetic manifest fixture: " + name + "\n")
        self.bias = self.base / "frozen-bias.csv"
        self.bias.write_text("symbol,direction,confidence\nMSFT,LONG,0.9\n")
        self.mandate = self.base / "frozen-mandate.json"
        self.mandate.write_bytes(canonical_json_bytes({"kind": "SYNTHETIC_NONEXECUTABLE_FIXTURE"}))
        self.profile = {
            "schema_version": PROFILE_SCHEMA, "profile_id": "profile-test", "mode": "PAPER",
            "galactica_root": str(self.source), "python_executable": str(Path(sys.executable).resolve()),
            "source_hashes": source_manifest(self.source), "symbols": ["MSFT"], "protected_symbols": ["AAPL"],
            "account_scope": "SHARED_DISJOINT", "account_id": "fixture-account", "capital_authorization_id": "fixture-capital",
            "trading_budget_usd": "100.00", "max_account_gross_usd": "200.00", "max_order_notional_usd": "25.00",
            "price_max_age_seconds": 30, "price_buffer_fraction": "0.05", "authorization_expires_at": EXPIRY,
            "frozen_inputs": {name: {"path": str(path), "sha256": sha256_bytes(path.read_bytes())}
                              for name, path in (("bias_csv", self.bias), ("mandate_path", self.mandate))},
            "native_settings": {"per_trade_usd_cap": 20, "eod_flatten_min": 15, "exit_after_close": True},
        }
        self.root = self.base / "runtime"
        self.spawns = []

    def close(self):
        self.temporary.cleanup()

    def fake_spawn(self, command, **kwargs):
        self.spawns.append((command, kwargs))
        return mock.Mock(pid=12345)

    def enable(self, **changes):
        values = {"action_id": "on-test", "operator_id": "fixture-operator",
                  "confirm_profile_sha256": profile_hash(self.profile), "confirm_account_id": self.profile["account_id"],
                  "confirm_mode": "PAPER", "now": lambda: NOW, "spawn": self.fake_spawn}
        values.update(changes)
        return enable_trading(self.root, self.profile, **values)


class AutoTradingRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.fixture = RuntimeFixture()
        self.addCleanup(self.fixture.close)
        self.enterContext(mock.patch.object(socket.socket, "connect", side_effect=AssertionError("network forbidden")))
        self.enterContext(mock.patch("subprocess.Popen", side_effect=AssertionError("real subprocess forbidden")))
        self.enterContext(mock.patch("subprocess.run", side_effect=AssertionError("real producer forbidden")))

    def test_profile_has_verified_synthetic_source_and_input_pins(self):
        result = validate_profile(self.fixture.profile)
        self.assertEqual(result["source_hashes"], source_manifest(self.fixture.source))
        self.assertEqual(result["mode"], "PAPER")
        self.assertFalse(self.fixture.root.exists())

    def test_invalid_profile_semantics_fail_without_runtime_creation(self):
        edits = [lambda p: p.update(symbols=["MSFT", "MSFT"]),
                 lambda p: p.update(protected_symbols=["MSFT"]),
                 lambda p: p.update(account_scope="UNCLASSIFIED"),
                 lambda p: p.update(mode="SHADOW"),
                 lambda p: p.update(trading_budget_usd="250"),
                 lambda p: p["native_settings"].update(dry_run=False),
                 lambda p: p["native_settings"].update(exit_after_close=False),
                 lambda p: p["native_settings"].update(eod_flatten_min=0)]
        for edit in edits:
            value = copy.deepcopy(self.fixture.profile)
            edit(value)
            with self.subTest(edit=edit), self.assertRaises((ValueError, TypeError)):
                validate_profile(value)
        self.assertFalse(self.fixture.root.exists())

    def test_source_input_and_symlink_mutations_are_rejected(self):
        for target in (self.fixture.source / MODULE_FILES[0], self.fixture.bias, self.fixture.mandate):
            raw = target.read_bytes()
            target.write_bytes(raw + b"# changed\n")
            with self.subTest(target=target.name), self.assertRaises(ValueError):
                validate_profile(self.fixture.profile)
            target.write_bytes(raw)
        original = self.fixture.bias
        link = self.fixture.base / "bias-link.csv"
        link.symlink_to(original)
        value = copy.deepcopy(self.fixture.profile)
        value["frozen_inputs"]["bias_csv"]["path"] = str(link)
        with self.assertRaises(ValueError):
            validate_profile(value)

    def test_missing_runtime_defaults_off_and_status_is_read_only(self):
        state = runtime_status(self.fixture.root)
        self.assertEqual(state["state"], "OFF")
        self.assertFalse(state["entries_enabled"])
        self.assertFalse(state["auto_restart_enabled"])
        self.assertFalse(self.fixture.root.exists())

    def test_existing_runtime_status_creates_no_files(self):
        self.fixture.root.mkdir()
        before = list(self.fixture.root.iterdir())
        state = runtime_status(self.fixture.root)
        self.assertEqual(state["state"], "OFF")
        self.assertEqual(list(self.fixture.root.iterdir()), before)

    def test_confirmation_hash_mode_and_account_are_exact(self):
        for changes in ({"confirm_profile_sha256": "f" * 64}, {"confirm_account_id": "other-account"},
                        {"confirm_mode": "LIVE"}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.fixture.enable(**changes)
        self.assertFalse(self.fixture.root.exists())
        self.assertEqual(self.fixture.spawns, [])

    def test_expired_profile_never_creates_runtime_or_starts_process(self):
        with self.assertRaises(ValueError):
            self.fixture.enable(now=lambda: EXPIRY)
        self.assertFalse(self.fixture.root.exists())
        self.assertEqual(self.fixture.spawns, [])

    def test_on_spawns_only_explicit_isolated_worker_with_no_shell(self):
        output = self.fixture.enable()
        self.assertTrue(output["written"])
        self.assertTrue(output["spawned"])
        self.assertEqual(len(self.fixture.spawns), 1)
        command, kwargs = self.fixture.spawns[0]
        self.assertEqual(command[:4], [self.fixture.profile["python_executable"], "-P", "-m", "blackpod_build_week.auto_trading_worker"])
        self.assertNotIn("shell", kwargs)
        self.assertTrue(kwargs["close_fds"])
        self.assertEqual(kwargs["env"]["ALPACA_PAPER"], "true")
        state = runtime_status(self.fixture.root)
        self.assertFalse(state["entries_enabled"])
        self.assertFalse(state["worker_active"])
        self.assertTrue(state["requested_entries_enabled"])

    def test_retry_never_restarts_unresolved_lost_spawn(self):
        first = self.fixture.enable()
        second = self.fixture.enable()
        self.assertEqual(first["session_id"], second["session_id"])
        self.assertFalse(second["spawned"])
        self.assertEqual(len(self.fixture.spawns), 1)
        with self.assertRaises(ValueError):
            self.fixture.enable(action_id="second-on")
        self.assertFalse(runtime_status(self.fixture.root)["auto_restart_enabled"])

    def test_spawn_failure_closes_gate_and_is_audited(self):
        with self.assertRaises(ValueError):
            self.fixture.enable(spawn=mock.Mock(side_effect=OSError("fixture-no-launch")))
        ledger = RuntimeLedger(self.fixture.root)
        self.assertFalse(ledger.latest_control()["entries_enabled"])
        self.assertFalse(ledger.entries_enabled("any-session", self.fixture.profile, now=lambda: NOW))
        self.assertTrue(any(event["kind"] == "WORKER_STATUS" and event["payload"]["state"] == "START_FAILED"
                            for event in ledger.events()))

    def test_off_does_not_close_positions_cancel_orders_or_kill_process(self):
        self.fixture.enable()
        result = disable_trading(self.fixture.root, action_id="off-test", operator_id="fixture-operator", now=lambda: NOW)
        self.assertTrue(result["exits_retained"])
        self.assertFalse(result["positions_closed"])
        self.assertFalse(result["pending_orders_cancelled"])
        self.assertFalse(RuntimeLedger(self.fixture.root).latest_control()["entries_enabled"])
        self.assertEqual(len(self.fixture.spawns), 1)
        retry = disable_trading(self.fixture.root, action_id="off-test", operator_id="fixture-operator", now=lambda: NOW)
        self.assertFalse(retry["written"])

    def test_gate_rechecks_expiry_mutated_inputs_and_source_without_wall_clock(self):
        result = self.fixture.enable()
        ledger = RuntimeLedger(self.fixture.root)
        self.assertTrue(ledger.entries_enabled(result["session_id"], self.fixture.profile, now=lambda: NOW))
        self.assertFalse(ledger.entries_enabled(result["session_id"], self.fixture.profile, now=lambda: EXPIRY))
        self.assertFalse(ledger.entries_enabled("different-session", self.fixture.profile, now=lambda: NOW))
        for target in (self.fixture.bias, self.fixture.source / MODULE_FILES[0]):
            raw = target.read_bytes()
            target.write_bytes(raw + b"# mutation\n")
            self.assertFalse(ledger.entries_enabled(result["session_id"], self.fixture.profile, now=lambda: NOW))
            target.write_bytes(raw)

    def test_runtime_source_overlap_rejected_before_any_source_write(self):
        self.fixture.root = self.fixture.source / "runtime"
        before = sorted(str(p.relative_to(self.fixture.source)) for p in self.fixture.source.rglob("*"))
        with self.assertRaises(ValueError):
            self.fixture.enable()
        self.assertEqual(sorted(str(p.relative_to(self.fixture.source)) for p in self.fixture.source.rglob("*")), before)

    def test_runtime_root_symlinks_are_rejected(self):
        target = self.fixture.base / "actual-root"
        target.mkdir()
        self.fixture.root.symlink_to(target, target_is_directory=True)
        with self.assertRaises(ValueError):
            self.fixture.enable()
        self.assertEqual(list(target.iterdir()), [])

    def test_duplicate_action_with_changed_profile_or_operator_conflicts(self):
        self.fixture.enable()
        with self.assertRaises(ValueError):
            self.fixture.enable(operator_id="changed-operator")
        with self.assertRaises(ValueError):
            disable_trading(self.fixture.root, action_id="on-test", operator_id="fixture-operator", now=lambda: NOW)

    def test_worker_lock_prevents_second_launch_after_off(self):
        self.fixture.enable()
        disable_trading(self.fixture.root, action_id="off-test", operator_id="fixture-operator", now=lambda: NOW)
        with RuntimeLedger(self.fixture.root).lock("worker.lock"):
            with self.assertRaises(ValueError):
                self.fixture.enable(action_id="next-on")
        self.assertEqual(len(self.fixture.spawns), 1)

    def test_ledger_chain_gap_and_rehashed_invalid_control_fail_closed(self):
        result = self.fixture.enable()
        path = self.fixture.root / "events/000000000001.json"
        raw = path.read_bytes()
        renamed = path.with_name("000000000002.json")
        path.rename(renamed)
        ledger = RuntimeLedger(self.fixture.root)
        self.assertFalse(ledger.entries_enabled(result["session_id"], self.fixture.profile, now=lambda: NOW))
        with self.assertRaises(ValueError):
            ledger.events()
        renamed.rename(path)
        entry = json.loads(raw)
        entry["payload"]["entries_enabled"] = "true"
        unsigned = {key: value for key, value in entry.items() if key != "event_sha256"}
        entry["event_sha256"] = sha256_bytes(canonical_json_bytes(unsigned))
        path.write_bytes(canonical_json_bytes(entry))
        self.assertFalse(ledger.entries_enabled(result["session_id"], self.fixture.profile, now=lambda: NOW))

    def test_invalid_append_and_duplicate_control_rejected_before_commit(self):
        self.fixture.enable()
        ledger = RuntimeLedger(self.fixture.root)
        original = {p.name: p.read_bytes() for p in (self.fixture.root / "events").iterdir()}
        with self.assertRaises(ValueError):
            ledger.append("CONTROL", copy.deepcopy(ledger.latest_control()))
        with self.assertRaises(ValueError):
            ledger.append("UNKNOWN_EVENT", {"secret": "do-not-persist"})
        self.assertEqual(original, {p.name: p.read_bytes() for p in (self.fixture.root / "events").iterdir()})

    def test_injected_worker_has_mapping_gate_and_records_only_sanitized_receipts(self):
        result = self.fixture.enable()
        captured = []
        async def runner(profile, switch_reader, receipt):
            state = switch_reader()
            self.assertIsInstance(state, dict)
            self.assertTrue(state["entries_enabled"])
            for key, value in self.fixture.profile.items():
                if key not in {"galactica_root", "frozen_inputs"}:
                    self.assertEqual(profile[key], value)
            self.assertTrue(Path(profile["galactica_root"]).is_relative_to(self.fixture.root))
            for name in MODULE_FILES:
                self.assertEqual((Path(profile["galactica_root"]) / name).read_bytes(), (self.fixture.source / name).read_bytes())
            for name in ("bias_csv", "mandate_path"):
                path = Path(profile["frozen_inputs"][name]["path"])
                self.assertTrue(path.is_relative_to(self.fixture.root))
                self.assertEqual(sha256_bytes(path.read_bytes()), self.fixture.profile["frozen_inputs"][name]["sha256"])
            captured.append(state)
            receipt({"kind": "WORKER_STATUS", "state": "RUNNING"})
        with mock.patch("blackpod_build_week.auto_trading_worker.utc_now", return_value=NOW), \
                mock.patch("blackpod_build_week.auto_trading_runtime.utc_now", return_value=NOW):
            # entries_enabled's bound default must be explicitly patched for the
            # worker; tests do not infer activation from the machine clock.
            original = RuntimeLedger.entries_enabled
            with mock.patch.object(RuntimeLedger, "entries_enabled", lambda ledger, sid, p: original(ledger, sid, p, now=lambda: NOW)):
                self.assertEqual(auto_trading_worker.run_worker(self.fixture.root, result["session_id"], runner=runner), 0)
        self.assertEqual(len(captured), 1)
        states = [event["payload"]["state"] for event in RuntimeLedger(self.fixture.root).events() if event["kind"] == "WORKER_STATUS"]
        self.assertEqual(states, ["STARTING", "RUNNING", "STOPPED"])

    def test_worker_failure_is_sanitized_and_never_restarted(self):
        result = self.fixture.enable()
        async def runner(profile, switch_reader, receipt):
            raise RuntimeError("SECRET_FIXTURE_VALUE_NEVER_PERSIST")
        original = RuntimeLedger.entries_enabled
        with mock.patch.object(RuntimeLedger, "entries_enabled", lambda ledger, sid, p: original(ledger, sid, p, now=lambda: NOW)), \
                mock.patch("blackpod_build_week.auto_trading_worker.utc_now", return_value=NOW):
            self.assertEqual(auto_trading_worker.run_worker(self.fixture.root, result["session_id"], runner=runner), 2)
        raw = b"".join(path.read_bytes() for path in (self.fixture.root / "events").iterdir())
        self.assertNotIn(b"SECRET_FIXTURE_VALUE", raw)
        self.assertFalse(runtime_status(self.fixture.root)["auto_restart_enabled"])

    def test_worker_does_not_import_executor_without_matching_on(self):
        disable_trading(self.fixture.root, action_id="off-default", operator_id="fixture-operator", now=lambda: NOW)
        runner = mock.Mock(side_effect=AssertionError("executor must remain unavailable"))
        with self.assertRaises(ValueError):
            auto_trading_worker.run_worker(self.fixture.root, "unknown-session", runner=runner)
        runner.assert_not_called()

    def test_startup_pin_mutation_rejects_before_injected_runner(self):
        result = self.fixture.enable()
        self.fixture.bias.write_bytes(self.fixture.bias.read_bytes() + b"# changed after ON\n")
        runner = mock.Mock(side_effect=AssertionError("no executor after changed pins"))
        self.assertEqual(auto_trading_worker.run_worker(self.fixture.root, result["session_id"], runner=runner), 2)
        runner.assert_not_called()
        ledger = RuntimeLedger(self.fixture.root)
        self.assertFalse(ledger.latest_control()["entries_enabled"])
        self.assertEqual(ledger.events()[-1]["payload"]["state"], "START_FAILED")
        self.assertTrue(ledger.events()[-1]["payload"]["manual_position_check_required"])

    def test_session_profile_substitution_fails_closed(self):
        result = self.fixture.enable()
        digest = profile_hash(self.fixture.profile)
        retained = self.fixture.root / "profiles" / (digest + ".json")
        value = json.loads(retained.read_bytes())
        value["mode"] = "LIVE"
        retained.write_bytes(canonical_json_bytes(value))
        ledger = RuntimeLedger(self.fixture.root)
        self.assertFalse(ledger.entries_enabled(result["session_id"], self.fixture.profile, now=lambda: NOW))
        with self.assertRaises(ValueError):
            ledger.events()

    def test_runtime_may_not_overlap_missions_or_journal_roots(self):
        for marker in ("missions", ".journal.lock"):
            root = self.fixture.base / ("protected-" + marker.replace(".", ""))
            root.mkdir()
            if marker == "missions":
                (root / marker).mkdir()
            else:
                (root / marker).write_bytes(b"")
            before = sorted(str(path.relative_to(root)) for path in root.rglob("*"))
            with self.subTest(marker=marker), self.assertRaises((ValueError, RuntimeError)):
                RuntimeLedger(root / "runtime")
            self.assertEqual(sorted(str(path.relative_to(root)) for path in root.rglob("*")), before)

    def test_rehashed_impossible_receipt_semantics_fail_closed(self):
        result = self.fixture.enable()
        ledger = RuntimeLedger(self.fixture.root)
        ledger.append("WORKER_STATUS", {"session_id": result["session_id"], "mode": "PAPER", "recorded_at": NOW,
                                       "state": "STARTING"})
        path = self.fixture.root / "events/000000000002.json"
        item = json.loads(path.read_bytes())
        item["payload"]["mode"] = "LIVE"
        unsigned = {key: value for key, value in item.items() if key != "event_sha256"}
        item["event_sha256"] = sha256_bytes(canonical_json_bytes(unsigned))
        path.write_bytes(canonical_json_bytes(item))
        self.assertFalse(ledger.entries_enabled(result["session_id"], self.fixture.profile, now=lambda: NOW))
        with self.assertRaises(ValueError):
            ledger.events()

    def test_terminal_session_receipt_cannot_restart(self):
        result = self.fixture.enable()
        ledger = RuntimeLedger(self.fixture.root)
        for state in ("STARTING", "RUNNING"):
            ledger.append("WORKER_STATUS", {"session_id": result["session_id"], "mode": "PAPER", "recorded_at": NOW,
                                           "state": state})
        ledger.append("WORKER_STATUS", {"session_id": result["session_id"], "mode": "PAPER", "recorded_at": NOW,
                                       "state": "STOPPED", "auto_restart_enabled": False})
        with self.assertRaises(ValueError):
            ledger.append("WORKER_STATUS", {"session_id": result["session_id"], "mode": "PAPER", "recorded_at": NOW,
                                           "state": "RUNNING"})

    def test_forged_running_receipt_without_starting_is_rejected(self):
        result = self.fixture.enable()
        ledger = RuntimeLedger(self.fixture.root)
        with self.assertRaises(ValueError):
            ledger.append("WORKER_STATUS", {"session_id": result["session_id"], "mode": "PAPER", "recorded_at": NOW,
                                           "state": "RUNNING"})

    def test_account_lock_blocks_a_second_runtime_root(self):
        with account_lock(self.fixture.profile):
            self.fixture.root = self.fixture.base / "other-runtime"
            with self.assertRaises(ValueError):
                self.fixture.enable()
        self.assertEqual(self.fixture.spawns, [])
        self.assertFalse(RuntimeLedger(self.fixture.root).latest_control()["entries_enabled"])

    def test_inherited_account_lock_requires_matching_profile_file(self):
        other = copy.deepcopy(self.fixture.profile)
        other["account_id"] = "other-fixture-account"
        # Create the second account's admission file so the failure is an inode
        # binding mismatch, not a missing file. No worker/process is invoked.
        with account_lock(other):
            pass
        with account_lock(self.fixture.profile) as descriptor:
            duplicate = os.dup(descriptor)
            with self.assertRaises(ValueError):
                with account_lock(other, inherited_descriptor=duplicate):
                    self.fail("unrelated account lock must not authorize this profile")

    def test_worker_callback_broker_receipt_is_source_bound_and_sanitized(self):
        result = self.fixture.enable()
        async def runner(profile, switch_reader, receipt):
            receipt({"kind": "WORKER_STATUS", "state": "RUNNING"})
            receipt({"profile_id": profile["profile_id"], "domain": "TRADING", "account_mode": "PAPER",
                     "symbol": "MSFT", "side": "buy", "qty": "1", "outcome": "BLOCKED",
                     "reason_code": "AUTO_TRADING_OFF_OR_CONTROL_UNVERIFIED", "order_id": None,
                     "capital_authorization_id": profile["capital_authorization_id"]})
        original = RuntimeLedger.entries_enabled
        with mock.patch.object(RuntimeLedger, "entries_enabled", lambda ledger, sid, p: original(ledger, sid, p, now=lambda: NOW)), \
                mock.patch("blackpod_build_week.auto_trading_worker.utc_now", return_value=NOW):
            self.assertEqual(auto_trading_worker.run_worker(self.fixture.root, result["session_id"], runner=runner), 0)
        receipts = [event["payload"] for event in RuntimeLedger(self.fixture.root).events() if event["kind"] == "BROKER_GUARD"]
        self.assertEqual(len(receipts), 1)
        self.assertEqual(receipts[0]["profile_id"], self.fixture.profile["profile_id"])
        self.assertEqual(receipts[0]["session_id"], result["session_id"])
        self.assertEqual(receipts[0]["domain"], "TRADING")

    def test_long_action_identity_launch_failure_still_closes_gate(self):
        with self.assertRaises(ValueError):
            self.fixture.enable(action_id="a" * 128, spawn=mock.Mock(side_effect=OSError("fixture-launch-failure")))
        ledger = RuntimeLedger(self.fixture.root)
        self.assertFalse(ledger.latest_control()["entries_enabled"])

    def test_append_recovers_internal_staging_hardlink_without_changing_committed_bytes(self):
        result = self.fixture.enable()
        path = self.fixture.root / "events/000000000001.json"
        original = path.read_bytes()
        staging = path.parent / (".runtime-" + "a" * 32 + ".tmp")
        os.link(path, staging)
        ledger = RuntimeLedger(self.fixture.root)
        self.assertFalse(ledger.entries_enabled(result["session_id"], self.fixture.profile, now=lambda: NOW))
        ledger.append("WORKER_STATUS", {"session_id": result["session_id"], "mode": "PAPER", "recorded_at": NOW,
                                       "state": "STARTING"})
        self.assertEqual(path.read_bytes(), original)
        self.assertFalse(staging.exists())
        self.assertEqual(path.stat().st_nlink, 1)
        self.assertEqual(len(ledger.events()), 2)

    def test_off_command_recovers_committed_internal_link_before_reading_chain(self):
        self.fixture.enable()
        path = self.fixture.root / "events/000000000001.json"
        original = path.read_bytes()
        staging = path.parent / (".runtime-" + "b" * 32 + ".tmp")
        os.link(path, staging)
        result = disable_trading(self.fixture.root, action_id="off-after-crash", operator_id="fixture-operator", now=lambda: NOW)
        self.assertTrue(result["written"])
        self.assertFalse(staging.exists())
        self.assertEqual(path.read_bytes(), original)
        self.assertFalse(RuntimeLedger(self.fixture.root).latest_control()["entries_enabled"])

    def test_append_removes_unpublished_staging_orphan_and_rejects_external_links(self):
        result = self.fixture.enable()
        ledger = RuntimeLedger(self.fixture.root)
        orphan = self.fixture.root / "events" / (".runtime-" + "c" * 32 + ".tmp")
        orphan.write_bytes(b"partial unpublished synthetic bytes")
        ledger.append("WORKER_STATUS", {"session_id": result["session_id"], "mode": "PAPER", "recorded_at": NOW,
                                       "state": "STARTING"})
        self.assertFalse(orphan.exists())
        target = self.fixture.root / "events/000000000001.json"
        external = self.fixture.base / "external-hardlink"
        os.link(target, external)
        with self.assertRaises(ValueError):
            ledger.append("WORKER_STATUS", {"session_id": result["session_id"], "mode": "PAPER", "recorded_at": NOW,
                                           "state": "RUNNING"})
        self.assertTrue(external.exists())

    def test_prepublication_control_failure_can_retry_without_any_spawn(self):
        immutable = runtime_module._immutable
        def fail_before_control(path, raw):
            if path.parent.name == "events":
                raise OSError("synthetic prepublication interruption")
            return immutable(path, raw)
        with mock.patch.object(runtime_module, "_immutable", side_effect=fail_before_control):
            with self.assertRaises((ValueError, OSError)):
                self.fixture.enable()
        self.assertEqual(self.fixture.spawns, [])
        self.assertEqual(RuntimeLedger(self.fixture.root).events(), [])
        self.assertTrue(self.fixture.enable()["spawned"])
        self.assertEqual(len(self.fixture.spawns), 1)

    def test_postpublication_lost_spawn_never_restarts_on_retry(self):
        immutable = runtime_module._immutable
        def fail_after_control(path, raw):
            immutable(path, raw)
            if path.parent.name == "events":
                raise OSError("synthetic postpublication interruption")
        with mock.patch.object(runtime_module, "_immutable", side_effect=fail_after_control):
            with self.assertRaises((ValueError, OSError)):
                self.fixture.enable()
        self.assertEqual(self.fixture.spawns, [])
        ledger = RuntimeLedger(self.fixture.root)
        self.assertTrue(ledger.latest_control()["entries_enabled"])
        state = runtime_status(self.fixture.root)
        self.assertFalse(state["entries_enabled"])
        self.assertFalse(state["auto_restart_enabled"])
        self.assertFalse(self.fixture.enable()["spawned"])
        self.assertEqual(self.fixture.spawns, [])
        disable_trading(self.fixture.root, action_id="off-unresolved-start", operator_id="fixture-operator", now=lambda: NOW)
        self.assertFalse(ledger.latest_control()["entries_enabled"])

    def test_enable_retry_recovers_retained_profile_internal_link(self):
        result = self.fixture.enable()
        digest = profile_hash(self.fixture.profile)
        path = self.fixture.root / "profiles" / (digest + ".json")
        original = path.read_bytes()
        staging = path.parent / (".runtime-" + "d" * 32 + ".tmp")
        os.link(path, staging)
        retry = self.fixture.enable()
        self.assertFalse(retry["spawned"])
        self.assertEqual(retry["session_id"], result["session_id"])
        self.assertEqual(path.read_bytes(), original)
        self.assertEqual(path.stat().st_nlink, 1)
        self.assertFalse(staging.exists())

    def test_off_waits_for_shared_submission_admission_before_commit(self):
        import threading
        from concurrent.futures import ThreadPoolExecutor
        self.fixture.enable()
        ledger = RuntimeLedger(self.fixture.root)
        started = threading.Event()
        def request_off():
            started.set()
            return disable_trading(self.fixture.root, action_id="off-serialized", operator_id="fixture-operator", now=lambda: NOW)
        with ThreadPoolExecutor(max_workers=1) as pool:
            with ledger.lock("submission.lock"):
                future = pool.submit(request_off)
                self.assertTrue(started.wait(1))
                self.assertFalse(future.done())
                self.assertTrue(ledger.latest_control()["entries_enabled"])
            self.assertTrue(future.result(timeout=2)["written"])
        self.assertFalse(ledger.latest_control()["entries_enabled"])

    def test_offline_cli_validate_status_and_generic_faults_never_spawn(self):
        profile_path = self.fixture.base / "profile.json"
        profile_path.write_bytes(canonical_json_bytes(self.fixture.profile))
        stdout, stderr = io.StringIO(), io.StringIO()
        with mock.patch("sys.stdout", stdout), mock.patch("sys.stderr", stderr):
            self.assertEqual(auto_trading_cli.main(["validate-profile", "--profile", str(profile_path)]), 0)
            self.assertEqual(auto_trading_cli.main(["status", "--runtime-root", str(self.fixture.root)]), 0)
            self.assertEqual(auto_trading_cli.main(["validate-profile", "--profile", str(self.fixture.base / "missing")]), 2)
        self.assertIn("LOCAL_STRUCTURE_AND_FILE_PINS", stdout.getvalue())
        self.assertIn('"broker_calls": 0', stdout.getvalue())
        self.assertNotIn(str(self.fixture.base / "missing"), stderr.getvalue())
        self.assertFalse(self.fixture.root.exists())


if __name__ == "__main__":
    unittest.main()
