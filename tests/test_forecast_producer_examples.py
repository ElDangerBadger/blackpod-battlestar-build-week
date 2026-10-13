"""Portable offline prepare/export/record replay using actual-fitted synthetic data."""
import contextlib
import copy
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from blackpod_build_week.contracts.mission_request import parse_strict_json_object_bytes
from blackpod_build_week.decision_journal_store import JournalStore, JournalStoreError
from blackpod_build_week.forecast_producer_cli import main as producer_cli
from blackpod_build_week.forecast_producer_example import example_material, main, prepare_example
from blackpod_build_week.hashing import sha256_bytes


class ForecastProducerExampleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.material = example_material()

    def invoke(self, argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            status = producer_cli(argv)
        self.assertEqual(status, 0, err.getvalue())
        return json.loads(out.getvalue())

    def export(self, input_root, output_root):
        return self.invoke(["export", "--request", str(input_root / "request.json"), "--evidence-root", str(input_root / "evidence"),
            "--native-result", str(input_root / "native-result.json"), "--worker-receipt", str(input_root / "worker-receipt.json"),
            "--output-directory", str(output_root)])

    def test_fixture_is_actual_fitted_and_clearly_synthetic(self):
        result = self.material["export_material"]["intake_result"]
        self.assertEqual(result["admitted_count"], 2); self.assertEqual(result["deferred_count"], 3)
        self.assertEqual([row["horizon_count"] for row in result["rows"] if "CROSSED_QUANTILES" in row["reason_codes"]], [1, 4, 5])
        self.assertEqual(self.material["request"].symbols, ["SYNTHETIC"])

    def test_native_model_used_rows_and_coefficients_are_unchanged(self):
        from blackpod_build_week.forecast_producer_example import _fixture_root
        fixture = json.loads((_fixture_root() / "synthetic_fitted.v1.json").read_bytes())
        self.assertEqual(self.material["native_result"]["symbols"], fixture["result"]["symbols"])
        self.assertEqual(self.material["native_result"]["config"], fixture["result"]["config"])
        self.assertEqual(self.material["native_result"]["runtime_fingerprint"], fixture["result"]["runtime_fingerprint"])

    def test_preparation_never_fits_models_or_calls_a_worker(self):
        from blackpod_build_week.shadow_quantitative_producer import _native
        with tempfile.TemporaryDirectory() as root, patch("subprocess.run", side_effect=AssertionError("no worker")), \
             patch("blackpod_build_week.shadow_quantitative_producer._native", wraps=_native) as native:
            report = prepare_example(Path(root).resolve() / "input")
        self.assertEqual(report["model_fit_count_this_invocation"], 0)
        self.assertEqual(report["historical_fixture_fit_count"], 15)
        self.assertEqual(report["provider_calls"], 0); self.assertEqual(report["orders_submitted"], 0)
        self.assertTrue(all(not call.kwargs.get("fitting", False) for call in native.mock_calls))

    def test_preparation_is_immutable_idempotent_and_does_not_seed_journal(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root).resolve() / "input"; first = prepare_example(path)
            before = {str(p.relative_to(path)): p.read_bytes() for p in path.rglob("*") if p.is_file()}
            second = prepare_example(path)
            self.assertEqual(first, second)
            self.assertEqual(before, {str(p.relative_to(path)): p.read_bytes() for p in path.rglob("*") if p.is_file()})
            self.assertFalse((path / "journal").exists()); self.assertFalse((path / "export.json").exists())
            self.assertTrue(all(flag is False for flag in first["authority"].values()))
            self.assertIn("SYNTHETIC", first["observations"])

    def test_prepare_reports_conflicting_existing_file_without_overwrite(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root).resolve() / "input"; prepare_example(path)
            (path / "worker-receipt.json").write_bytes(b"unrelated-existing-file\n")
            with self.assertRaises(ValueError): prepare_example(path)
            self.assertEqual((path / "worker-receipt.json").read_bytes(), b"unrelated-existing-file\n")

    def test_offline_cli_export_record_verify_and_idempotent_retry(self):
        with tempfile.TemporaryDirectory() as root, patch("subprocess.run", side_effect=AssertionError("export never fits")):
            input_root, output_root, journal_root = (Path(root).resolve() / name for name in ("input", "export", "journal"))
            prepared = prepare_example(input_root)
            exported = self.export(input_root, output_root)
            self.assertEqual((exported["admitted_count"], exported["deferred_count"]), (2, 3))
            record = ["record", "--export", str(output_root / "export.json"), "--evidence-root", str(output_root / "evidence"),
                "--journal-root", str(journal_root)]
            recorded = self.invoke(record)
            self.assertTrue(recorded["producer_written"]); self.assertTrue(recorded["intake_written"])
            self.assertEqual({key: recorded[key] for key in prepared["expected_ids"]}, prepared["expected_ids"])
            before = {file.name: file.read_bytes() for file in (journal_root / "entries").iterdir()}
            retried = self.invoke(record)
            self.assertFalse(retried["producer_written"]); self.assertFalse(retried["intake_written"])
            self.assertEqual(before, {file.name: file.read_bytes() for file in (journal_root / "entries").iterdir()})
            verified = self.invoke(["verify", "--export", str(output_root / "export.json"), "--evidence-root", str(output_root / "evidence")])
            self.assertEqual((verified["admitted_count"], verified["deferred_count"]), (2, 3))
            journal = JournalStore(journal_root); summary = journal.verify()
            self.assertEqual(summary.event_count, 2); self.assertEqual(summary.orphan_evidence_count, 0)
            self.assertEqual(summary.staging_orphan_count, 0)
            self.assertEqual([event.schema_version for event in journal.events()], ["blackpod.decision_journal_event.v10", "blackpod.decision_journal_event.v9"])

    def test_export_evidence_restores_to_new_root_without_fixture_or_native_repository(self):
        with tempfile.TemporaryDirectory() as root:
            input_root, output_root, restore_root = (Path(root).resolve() / name for name in ("input", "export", "restore"))
            prepare_example(input_root); self.export(input_root, output_root)
            import shutil
            shutil.copytree(output_root, restore_root)
            shutil.rmtree(input_root); shutil.rmtree(output_root)
            with patch("blackpod_build_week.forecast_producer_example._fixture_root", side_effect=AssertionError("no fixture reload")), \
                 patch("blackpod_build_week.shadow_quantitative_producer.capture_quantitative_sources", side_effect=AssertionError("no sibling source reload")):
                result = self.invoke(["verify", "--export", str(restore_root / "export.json"), "--evidence-root", str(restore_root / "evidence")])
            self.assertEqual(result["admitted_count"], 2)

    def test_fixture_hash_rejects_edited_actual_fit_declaration(self):
        from blackpod_build_week.forecast_producer_example import _fixture_root
        with tempfile.TemporaryDirectory() as root:
            path = Path(root).resolve(); raw = (_fixture_root() / "synthetic_fitted.v1.json").read_bytes()
            (path / "synthetic_fitted.v1.json").write_bytes(raw + b"\n")
            with self.assertRaisesRegex(ValueError, "fingerprint"): example_material(path)

    def test_source_storage_and_symlink_output_are_rejected(self):
        from blackpod_build_week.forecast_producer_example import _fixture_root
        with self.assertRaises((ValueError, JournalStoreError)): prepare_example(_fixture_root() / "unsafe-child")
        with tempfile.TemporaryDirectory() as root:
            path = Path(root).resolve(); (path / "target").mkdir(); (path / "link").symlink_to(path / "target", target_is_directory=True)
            with self.assertRaises((ValueError, JournalStoreError)): prepare_example(path / "link" / "unsafe-child")

    def test_example_cli_reports_only_fixture_preparation(self):
        with tempfile.TemporaryDirectory() as root:
            out, err = io.StringIO(), io.StringIO()
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err): status = main(["--output-root", str(Path(root).resolve() / "input")])
            self.assertEqual(status, 0, err.getvalue()); report = json.loads(out.getvalue())
            self.assertEqual(report["data_status"], "ACTUAL_NATIVE_FIT_ON_SYNTHETIC_INPUTS")
            self.assertEqual(report["model_fit_count_this_invocation"], 0)
            self.assertFalse(report["auto_trading_changed"])


if __name__ == "__main__": unittest.main()
