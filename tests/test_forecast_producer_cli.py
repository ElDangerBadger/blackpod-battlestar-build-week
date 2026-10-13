"""Offline CLI and explicit CPU attempt lifecycle with an injected worker."""
from __future__ import annotations

import contextlib
import copy
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import io
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from blackpod_build_week import forecast_producer_cli as cli
from blackpod_build_week.contracts.forecast_producer import ForecastProducerRequest
from blackpod_build_week.decision_journal_store import JournalStore, JournalPersistenceError
from blackpod_build_week.forecast_producer_export import build_forecast_producer_export
from blackpod_build_week.hashing import canonical_json_bytes, sha256_bytes
from blackpod_build_week.sentry_history_cache import read_regular
from test_forecast_producer_export import fitted_export_material


class ForecastProducerCLITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.request, cls.native, cls.blobs, cls.clocks = fitted_export_material()
        cls.material = build_forecast_producer_export(cls.request, cls.native, cls.blobs, **cls.clocks)
        raw = canonical_json_bytes(cls.native)
        cls.receipt = {"schema_version": "blackpod.shadow_quantitative_worker_receipt.v1", **{key: cls.clocks[key] for key in ("started_at", "completed_at")},
            "output_sha256": sha256_bytes(raw), "size_bytes": len(raw), "symbol_count": 1, "model_fit_count": 15,
            "provider_calls": 0, "orders_submitted": 0, "auto_trading_enabled": False}

    def setUp(self):
        self.enterContext(patch.object(socket.socket, "connect", side_effect=AssertionError("network forbidden")))
        self.enterContext(patch("subprocess.Popen", side_effect=AssertionError("real CPU process forbidden")))
        self.enterContext(patch("blackpod_build_week.modeldock_client.ModelDockClient.generate_text", side_effect=AssertionError("provider forbidden")))
        self.enterContext(patch("blackpod_build_week.paper_account_probe.probe_paper_account", side_effect=AssertionError("broker forbidden")))
        self.enterContext(patch("blackpod_build_week.galactica_trading_adapter.run_guarded_navigator", side_effect=AssertionError("execution forbidden")))
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        self.base = Path(temp.name).resolve()
        self.evidence = self.base / "source-evidence"; self.evidence.mkdir()
        for path, raw in self.material["evidence"].items():
            target = self.evidence / path; target.parent.mkdir(parents=True, exist_ok=True); target.write_bytes(raw)
        self.input_dir = self.base / "captured-worker"; self.input_dir.mkdir()
        self.request_path = self.input_dir / "request.json"; self.request_path.write_bytes(self.request.to_bytes())
        self.native_path = self.input_dir / "result.json"; self.native_path.write_bytes(canonical_json_bytes(self.native))
        self.receipt_path = self.input_dir / "receipt.json"; self.receipt_path.write_bytes(canonical_json_bytes(self.receipt))
        self.output = self.base / "published-export"; self.journal = self.base / "journal"
        self.export_path = self.evidence / "standalone-export.json"; self.export_path.write_bytes(canonical_json_bytes(self.material["export"]))

    def invoke(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            result = cli.main([str(arg) for arg in args])
        return result, json.loads(out.getvalue()) if result == 0 else None, err.getvalue()

    def export(self, **overrides):
        return self.invoke("export", "--request", self.request_path, "--evidence-root", self.evidence,
            "--native-result", overrides.get("native", self.native_path), "--worker-receipt", overrides.get("receipt", self.receipt_path),
            "--output-directory", overrides.get("output", self.output))

    def record(self):
        return self.invoke("record", "--export", self.export_path, "--evidence-root", self.evidence, "--journal-root", self.journal)

    def runner(self, receipt=None):
        captured = []
        def execute(args, **kwargs):
            captured.append((args, kwargs))
            target = Path(args[args.index("--output") + 1]); target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(canonical_json_bytes(self.native))
            return subprocess.CompletedProcess(args, 0, stdout=canonical_json_bytes(receipt or self.receipt), stderr=b"")
        return execute, captured

    def produce(self, runner, directory=None, request=None, python_executable=None):
        with patch.object(cli, "datetime") as clock:
            clock.now.return_value = datetime.fromisoformat(self.request.recorded_at.replace("Z", "+00:00"))
            return cli.produce(request or self.request, self.blobs, directory or self.base / "production", python_executable or Path(sys.executable), runner=runner)

    def test_export_and_verify_are_offline_and_never_fit_or_create_journal(self):
        with patch("blackpod_build_week.shadow_quantitative_producer.build_shadow_quantitative_forecasts", side_effect=AssertionError("implicit fit")):
            code, output, error = self.export()
            self.assertEqual(code, 0, error)
            self.assertEqual(output["admitted_count"], 2); self.assertEqual(output["deferred_count"], 3)
            code, verified, error = self.invoke("verify", "--export", self.output / "export.json", "--evidence-root", self.output / "evidence")
            self.assertEqual(code, 0, error)
        self.assertEqual(verified["run_id"], self.request.run_id)
        self.assertFalse(self.journal.exists())
        self.assertEqual(output["orders_submitted"], 0); self.assertFalse(output["auto_trading_changed"])

    def test_exact_export_retry_does_not_rewrite_evidence(self):
        self.assertEqual(self.export()[0], 0)
        original = {str(path.relative_to(self.output)): path.read_bytes() for path in self.output.rglob("*") if path.is_file()}
        self.assertEqual(self.export()[0], 0)
        self.assertEqual({str(path.relative_to(self.output)): path.read_bytes() for path in self.output.rglob("*") if path.is_file()}, original)

    def test_record_commits_producer_then_intake_and_retries_are_noops(self):
        code, first, error = self.record(); self.assertEqual(code, 0, error)
        self.assertTrue(first["producer_written"]); self.assertTrue(first["intake_written"])
        original = JournalStore(self.journal).verify().to_dict()
        code, retry, error = self.record(); self.assertEqual(code, 0, error)
        self.assertFalse(retry["producer_written"]); self.assertFalse(retry["intake_written"])
        self.assertEqual(first["producer_event_id"], retry["producer_event_id"])
        self.assertEqual(JournalStore(self.journal).verify().to_dict(), original)
        self.assertEqual([row.schema_version for row in JournalStore(self.journal).events()],
            ["blackpod.decision_journal_event.v10", "blackpod.decision_journal_event.v9"])

    def test_record_recovers_after_second_commit_interruption_without_refitting(self):
        original = JournalStore.append
        def fail_intake(store, event, evidence):
            if event.event_type == "FORECAST_INTAKE_RECORDED":
                raise JournalPersistenceError("synthetic second commit interruption")
            return original(store, event, evidence)
        with patch.object(JournalStore, "append", new=fail_intake):
            code, _, error = self.record()
        self.assertEqual(code, 2); self.assertIn("second commit", error)
        self.assertEqual(JournalStore(self.journal).verify().event_count, 1)
        first = (self.journal / "entries/00000001.json").read_bytes()
        code, output, error = self.record(); self.assertEqual(code, 0, error)
        self.assertFalse(output["producer_written"]); self.assertTrue(output["intake_written"])
        self.assertEqual((self.journal / "entries/00000001.json").read_bytes(), first)
        self.assertEqual(JournalStore(self.journal).verify().event_count, 2)

    def test_mutated_source_hash_and_symlink_are_rejected(self):
        source = self.evidence / self.request.sources["market_evidence"]["path"]
        original = source.read_bytes(); source.write_bytes(original + b" ")
        self.assertEqual(self.export()[0], 2); self.assertFalse(self.output.exists())
        source.unlink(); target = self.base / "linked.json"; target.write_bytes(original); source.symlink_to(target)
        self.assertEqual(self.export()[0], 2); self.assertFalse(self.output.exists())

    def test_unsafe_export_destinations_fail_without_source_mutation(self):
        original = self.request_path.read_bytes()
        for directory in (self.evidence, self.evidence / "nested", self.input_dir / "nested"):
            with self.subTest(directory=directory): self.assertEqual(self.export(output=directory)[0], 2)
        self.assertEqual(self.request_path.read_bytes(), original)

    def test_forged_receipt_counts_hash_or_authority_rejected(self):
        for field, item in (("model_fit_count", 1), ("output_sha256", "0" * 64), ("size_bytes", 0),
                            ("provider_calls", 1), ("orders_submitted", 1), ("auto_trading_enabled", True)):
            receipt = dict(self.receipt, **{field: item}); self.receipt_path.write_bytes(canonical_json_bytes(receipt))
            with self.subTest(field=field): self.assertEqual(self.export()[0], 2)
            self.assertFalse(self.output.exists())

    def test_boolean_receipt_counts_are_not_integer_evidence(self):
        for field in ("provider_calls", "orders_submitted", "symbol_count", "size_bytes", "model_fit_count"):
            receipt = dict(self.receipt, **{field: False}); self.receipt_path.write_bytes(canonical_json_bytes(receipt))
            with self.subTest(field=field): self.assertEqual(self.export()[0], 2)
            self.assertFalse(self.output.exists())

    def test_native_prediction_edit_is_rejected_before_export_writes(self):
        value = copy.deepcopy(self.native); value["symbols"][0]["horizons"][0]["raw_quantiles"]["q50"] = "999"
        raw = canonical_json_bytes(value); self.native_path.write_bytes(raw)
        receipt = dict(self.receipt, output_sha256=sha256_bytes(raw), size_bytes=len(raw)); self.receipt_path.write_bytes(canonical_json_bytes(receipt))
        self.assertEqual(self.export()[0], 2); self.assertFalse(self.output.exists())

    def test_explicit_produce_invokes_only_source_pinned_worker_and_reuses_capture(self):
        runner, calls = self.runner(); first = self.produce(runner)
        self.assertEqual(len(calls), 1); self.assertEqual(first["models_fitted_this_invocation"], 15)
        self.assertFalse(first["reused_capture"])
        args, kwargs = calls[0]
        self.assertIn("blackpod_build_week.shadow_quantitative_producer", args)
        self.assertEqual(args[-1], "SYNTHETIC")
        self.assertEqual(kwargs["env"]["PYTHONDONTWRITEBYTECODE"], "1")
        self.assertEqual(kwargs["timeout"], 120); self.assertFalse(kwargs["check"])
        with patch("blackpod_build_week.shadow_quantitative_producer.build_shadow_quantitative_forecasts", side_effect=AssertionError("refit")):
            second = self.produce(lambda *args, **kwargs: self.fail("worker called on retry"))
        self.assertTrue(second["reused_capture"]); self.assertEqual(second["models_fitted_this_invocation"], 0)
        self.assertEqual(first["export"], second["export"])

    def test_declared_virtualenv_launcher_is_executed_while_resolved_binary_is_hashed(self):
        launcher = self.base / "declared-runtime/bin/python"
        launcher.parent.mkdir(parents=True)
        binary = Path(sys.executable).resolve(strict=True)
        launcher.symlink_to(binary)
        runner, calls = self.runner(); self.produce(runner, python_executable=launcher)
        self.assertEqual(calls[0][0][0], str(launcher.absolute()))
        self.assertNotEqual(calls[0][0][0], str(binary))
        intent = json.loads((self.base / "production/intent.json").read_bytes())
        self.assertEqual(intent["python_executable"], str(launcher.absolute()))
        self.assertEqual(intent["resolved_python_executable"], str(binary))
        self.assertEqual(intent["interpreter_sha256"], sha256_bytes(read_regular(binary, max_bytes=64 * 1024 * 1024)))

    def test_produce_attempt_failure_records_fingerprint_and_never_retries(self):
        calls = []
        def fail(args, **kwargs):
            calls.append(args); return subprocess.CompletedProcess(args, 2, stdout=b"", stderr=b"synthetic native failure")
        directory = self.base / "production"
        with self.assertRaisesRegex(ValueError, "no replacement algorithm"):
            self.produce(fail, directory)
        failure = json.loads((directory / "failure.json").read_bytes())
        self.assertEqual(failure["stderr_sha256"], sha256_bytes(b"synthetic native failure"))
        self.assertNotIn("stderr", failure); self.assertFalse(failure["automatic_refit_allowed"])
        with self.assertRaisesRegex(ValueError, "no automatic refit"):
            self.produce(lambda *a, **k: self.fail("automatic retry"), directory)
        self.assertEqual(len(calls), 1)

    def test_timeout_consumes_attempt_and_never_starts_background_work(self):
        def timeout(args, **kwargs): raise subprocess.TimeoutExpired(args, 120)
        directory = self.base / "production"
        with self.assertRaisesRegex(ValueError, "timed out"):
            self.produce(timeout, directory)
        self.assertTrue((directory / "intent.json").exists())
        with self.assertRaisesRegex(ValueError, "no automatic refit"):
            self.produce(lambda *a, **k: self.fail("retry after timeout"), directory)

    def test_unrecoverable_result_or_receipt_does_not_repeat_cpu_fit(self):
        runner, _ = self.runner(); self.produce(runner)
        directory = self.base / "production"; (directory / "worker/receipt.json").unlink()
        with self.assertRaisesRegex(ValueError, "no automatic refit"):
            self.produce(lambda *a, **k: self.fail("retry missing receipt"), directory)

    def test_retained_capture_republishes_after_output_interruption_without_refit(self):
        runner, calls = self.runner()
        with patch.object(cli, "_publish", side_effect=ValueError("synthetic output interruption")):
            with self.assertRaisesRegex(ValueError, "output interruption"):
                self.produce(runner)
        self.assertEqual(len(calls), 1)
        restored = self.produce(lambda *a, **k: self.fail("refit after output interruption"))
        self.assertTrue(restored["reused_capture"])
        self.assertEqual(restored["models_fitted_this_invocation"], 0)
        self.assertTrue(Path(restored["export"]).exists())

    def test_unclaimed_existing_worker_output_blocks_before_reservation_or_refit(self):
        directory = self.base / "production"; target = directory / "worker/result.json"
        target.parent.mkdir(parents=True); target.write_bytes(b"preexisting captured output")
        with self.assertRaises(ValueError):
            self.produce(lambda *a, **k: self.fail("worker started for existing unclaimed output"), directory)
        self.assertEqual(target.read_bytes(), b"preexisting captured output")
        self.assertFalse((directory / "intent.json").exists())

    def test_concurrent_produce_attempts_fit_once_and_reuse_complete_capture(self):
        runner, calls = self.runner(); directory = self.base / "production"
        with patch.object(cli, "datetime") as clock:
            clock.now.return_value = datetime.fromisoformat(self.request.recorded_at.replace("Z", "+00:00"))
            with ThreadPoolExecutor(max_workers=2) as pool:
                outputs = list(pool.map(lambda _: cli.produce(self.request, self.blobs, directory, Path(sys.executable), runner=runner), range(2)))
        self.assertEqual(len(calls), 1)
        self.assertEqual(sum(output["models_fitted_this_invocation"] for output in outputs), 15)
        self.assertEqual(sum(output["reused_capture"] for output in outputs), 1)

    def test_worker_clock_cannot_predate_its_saved_attempt(self):
        receipt = dict(self.receipt, started_at=self.request.recorded_at.replace("20:05", "20:04"))
        runner, calls = self.runner(receipt)
        with self.assertRaisesRegex(ValueError, "reserved CPU attempt"):
            self.produce(runner)
        self.assertEqual(len(calls), 1)
        with self.assertRaisesRegex(ValueError, "reserved CPU attempt"):
            self.produce(lambda *a, **k: self.fail("refit after bad receipt clock"))

    def test_retained_intent_cannot_enable_retry_or_execution_authority(self):
        runner, _ = self.runner(); self.produce(runner)
        directory = self.base / "production"; path = directory / "intent.json"
        original = json.loads(path.read_bytes())
        for change in (lambda v: v.update(automatic_refit_allowed=True), lambda v: v["authority"].update(execution_enabled=True),
                       lambda v: v.update(extra="unsupported")):
            value = copy.deepcopy(original); change(value)
            path.chmod(0o600); path.write_bytes(canonical_json_bytes(value))
            with self.assertRaises(ValueError):
                self.produce(lambda *a, **k: self.fail("refit after intent tamper"))

    def test_changed_retained_worker_prediction_is_not_replayed_or_refitted(self):
        runner, _ = self.runner(); self.produce(runner)
        path = self.base / "production/worker/result.json"
        value = json.loads(path.read_bytes()); value["symbols"][0]["horizons"][0]["raw_quantiles"]["q50"] = "999"
        path.chmod(0o600); path.write_bytes(canonical_json_bytes(value))
        with self.assertRaisesRegex(ValueError, "retained result"):
            self.produce(lambda *a, **k: self.fail("refit after result tamper"))

    def test_changed_run_inputs_conflict_before_worker_or_existing_writes(self):
        runner, _ = self.runner(); self.produce(runner)
        directory = self.base / "production"; original = (directory / "intent.json").read_bytes()
        value = self.request.to_dict(); value["horizons"] = [1]
        changed = ForecastProducerRequest.from_mapping(value)
        with self.assertRaisesRegex(ValueError, "different inputs"):
            self.produce(lambda *a, **k: self.fail("worker after conflict"), request=changed)
        self.assertEqual((directory / "intent.json").read_bytes(), original)

    def test_runtime_git_mission_and_symlink_destinations_block_before_writes(self):
        for marker in ("ledger.lock", ".git", "missions"):
            root = self.base / marker.replace(".", "safe"); root.mkdir()
            if marker == "ledger.lock": (root / marker).write_bytes(b"runtime")
            else: (root / marker).mkdir()
            destination = root / "new-run"
            with self.subTest(marker=marker), self.assertRaises((ValueError, RuntimeError)):
                self.produce(lambda *a, **k: self.fail("unsafe worker"), destination)
            self.assertFalse(destination.exists())
        target = self.base / "target"; target.mkdir(); link = self.base / "link"; link.symlink_to(target, target_is_directory=True)
        with self.assertRaises((ValueError, RuntimeError)):
            self.produce(lambda *a, **k: self.fail("linked worker"), link / "run")
        self.assertEqual(list(target.iterdir()), [])

    def test_production_lock_symlink_hardlink_or_fifo_rejected_without_reservation(self):
        for link_kind in ("symlink", "hardlink", "fifo"):
            directory = self.base / link_kind; directory.mkdir()
            target = self.base / (link_kind + "-target"); target.write_bytes(b"unrelated lock target")
            lock = directory / ".forecast-production.lock"
            if link_kind == "symlink": lock.symlink_to(target)
            elif link_kind == "hardlink": os.link(target, lock)
            else: os.mkfifo(lock)
            with self.subTest(link_kind=link_kind), self.assertRaises((ValueError, RuntimeError, OSError)):
                self.produce(lambda *a, **k: self.fail("worker opened unsafe lock"), directory)
            self.assertFalse((directory / "intent.json").exists())
            self.assertEqual(target.read_bytes(), b"unrelated lock target")


if __name__ == "__main__":
    unittest.main()
