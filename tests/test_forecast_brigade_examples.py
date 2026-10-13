"""Runnable wholly synthetic forecast/Brigade examples and portable replay."""
from __future__ import annotations

import contextlib
import io
import json
from pathlib import Path
import shutil
import socket
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from blackpod_build_week.contracts.brigade_shadow import BrigadeShadowRequest
from blackpod_build_week.contracts.forecast_intake import ForecastIntake
from blackpod_build_week.decision_journal_store import JournalStore, JournalStoreError
from blackpod_build_week.desk_candidate_review_cli import _references, load_evidence
from blackpod_build_week.forecast_brigade_example import SYMBOL, example_material, main, prepare_example
from blackpod_build_week.forecast_intake_cli import main as forecast_cli
from blackpod_build_week.forecast_journal import (
    assess_brigade_shadow, build_brigade_shadow_event, evidence_for_brigade_shadow,
)
from blackpod_build_week.hashing import sha256_bytes


class ForecastBrigadeExampleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve() / "example"

    def call(self, function, argv):
        output, errors = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(errors): code = function(argv)
        self.assertEqual(code, 0, errors.getvalue())
        return json.loads(output.getvalue())

    def tree(self):
        return {str(path.relative_to(self.root)): path.read_bytes() for path in self.root.rglob("*") if path.is_file()}

    def test_pure_material_uses_explicit_synthetic_data_and_no_test_imports(self):
        material = example_material()
        self.assertEqual(material["intake"].sources[0]["source_id"], "synthetic-price-levels")
        self.assertEqual(material["seed_event"].payload["result"]["admitted_count"], 3)
        self.assertFalse(any(material["intake"].authority.values()))
        self.assertEqual(material["disabled_request"].symbols, [SYMBOL])
        source = (Path(__file__).resolve().parents[1] / "src/blackpod_build_week/forecast_brigade_example.py").read_text()
        self.assertNotIn("from test_", source); self.assertNotIn("import test_", source)
        self.assertNotIn("ModelDockClient", source); self.assertNotIn("AutoTradingController", source)
        self.assertNotIn("buried_treasure", source)

    def test_source_bytes_events_and_requests_are_deterministic(self):
        first, second = example_material(), example_material()
        for key in ("intake", "seed_event", "disabled_request", "disabled_event", "replay_request", "replay_event"):
            self.assertEqual(first[key].to_bytes(), second[key].to_bytes())
        self.assertEqual(first["evidence"], second["evidence"])

    def test_prepare_is_immutable_idempotent_and_seeds_one_forecast_event(self):
        first = prepare_example(self.root); retained = self.tree(); second = prepare_example(self.root)
        self.assertTrue(first["seed_written"]); self.assertFalse(second["seed_written"])
        self.assertEqual(self.tree(), retained)
        store = JournalStore(self.root / "journal")
        self.assertEqual(store.verify().event_count, 1)
        self.assertEqual(store.verify().orphan_evidence_count, 0)
        self.assertEqual(store.events()[0].event_type, "FORECAST_INTAKE_RECORDED")
        for path in ("intake.json", "request.disabled.json", "request.replay.json", "expected-ids.json"):
            self.assertTrue((self.root / path).is_file())

    def test_disabled_example_defers_all_five_members_without_fabricated_views(self):
        material = example_material()
        analysis = material["disabled_event"].payload["analysis"]
        self.assertEqual(analysis["response_capture_status"], "INFERENCE_DISABLED")
        for member in analysis["symbols"][0]["member_coverage"]:
            self.assertEqual(member["status"], "DEFER")
            self.assertIn("INFERENCE_DISABLED", member["reason_codes"])
        for opinion in analysis["symbols"][0]["opinions"]:
            self.assertIsNone(opinion["recommendation"])
        self.assertFalse(analysis["auto_trading_enabled"])

    def test_declared_replay_preserves_native_prompts_dissent_and_suppressed_plans(self):
        material = example_material()
        analysis = material["replay_event"].payload["analysis"]
        symbol = analysis["symbols"][0]
        self.assertEqual(len(analysis["response_transcripts"]), 5)
        self.assertEqual({opinion["recommendation"] for opinion in symbol["opinions"]}, {"BUY", "EXIT", "HOLD", "WATCH"})
        self.assertEqual(len(symbol["dissent"]), 5)
        self.assertTrue(all(opinion["trade_plan_suppressed"] and not opinion["confidence_is_probability"] for opinion in symbol["opinions"]))
        self.assertEqual(symbol["forecast_path_semantics"], "FUTURE_PREDICTED_CLOSE_LEVELS")
        bundle = json.loads(material["evidence"]["brigade/synthetic-declared-transcripts.json"])
        self.assertEqual(bundle["capture_kind"], "DECLARED_REPLAY")
        self.assertEqual(bundle["transport_records"], [])

    def test_example_preparation_and_forecast_retry_use_no_network_subprocess_or_models(self):
        example_material()  # Import existing numerical libraries before the guard.
        with patch.object(socket, "socket", side_effect=AssertionError("network forbidden")), \
                patch.object(subprocess, "Popen", side_effect=AssertionError("process forbidden")), \
                patch("pickle.loads", side_effect=AssertionError("model loading forbidden")):
            prepared = self.call(main, ["--output-root", str(self.root)])
            recorded = self.call(forecast_cli, ["record", "--journal-root", str(self.root / "journal"),
                "--intake", str(self.root / "intake.json"), "--evidence-root", str(self.root / "evidence")])
        self.assertFalse(recorded["written"])
        self.assertEqual(recorded["event_id"], prepared["expected_ids"]["forecast"])
        self.assertEqual(recorded["inference_calls"], 0)
        self.assertEqual(prepared["provider_calls"], 0)
        self.assertEqual(prepared["model_inference_calls"], 0)

    def test_reloaded_artifacts_reproduce_both_expected_linked_events(self):
        prepared = prepare_example(self.root)
        store = JournalStore(self.root / "journal")
        for filename, key in (("request.disabled.json", "brigade_disabled"), ("request.replay.json", "brigade_replay")):
            request = BrigadeShadowRequest.from_bytes((self.root / filename).read_bytes())
            events, blobs = store.verified_contents()
            blobs = load_evidence(self.root / "evidence", _references(request.to_dict()), blobs)
            event = build_brigade_shadow_event(request, events, blobs)
            self.assertEqual(event.event_id, prepared["expected_ids"][key])
            self.assertEqual(event.decision_id, events[0].decision_id)
            self.assertTrue(store.append(event, evidence_for_brigade_shadow(request, events, blobs)).written)
        verification = store.verify()
        self.assertEqual(verification.event_count, 3)
        self.assertEqual(verification.orphan_evidence_count, 0)

    def test_generated_example_is_portable_with_only_its_retained_inputs(self):
        prepared = prepare_example(self.root)
        copied = self.root.parent / "portable"
        shutil.copytree(self.root, copied)
        request = BrigadeShadowRequest.from_bytes((copied / "request.replay.json").read_bytes())
        store = JournalStore(copied / "journal")
        events, blobs = store.verified_contents()
        blobs = load_evidence(copied / "evidence", _references(request.to_dict()), blobs)
        with patch("blackpod_build_week.forecast_brigade_example.read_regular", side_effect=AssertionError("must not reread fixtures")):
            event = build_brigade_shadow_event(request, events, blobs)
            self.assertEqual(event.event_id, prepared["expected_ids"]["brigade_replay"])
            store.append(event, evidence_for_brigade_shadow(request, events, blobs))
            self.assertEqual(store.verify().event_count, 2)

    def test_cli_assess_record_show_and_idempotent_retry_are_offline(self):
        from blackpod_build_week.brigade_shadow_cli import main as brigade_cli
        prepared = prepare_example(self.root)
        with patch.object(socket, "socket", side_effect=AssertionError("network forbidden")), \
                patch.object(subprocess, "Popen", side_effect=AssertionError("process forbidden")):
            for filename, key in (("request.disabled.json", "brigade_disabled"), ("request.replay.json", "brigade_replay")):
                args = ["--journal-root", str(self.root / "journal"), "--request", str(self.root / filename), "--evidence-root", str(self.root / "evidence")]
                assessed = self.call(brigade_cli, ["assess", *args]); recorded = self.call(brigade_cli, ["record", *args])
                self.assertEqual(assessed["event_id"], prepared["expected_ids"][key])
                self.assertEqual(recorded["event_id"], assessed["event_id"])
                self.assertTrue(recorded["written"])
                self.assertFalse(self.call(brigade_cli, ["record", *args])["written"])
                shown = self.call(brigade_cli, ["show", "--journal-root", str(self.root / "journal"), "--event-id", recorded["event_id"]])
                self.assertEqual(shown["payload"]["analysis"], recorded["analysis"])
        self.assertEqual(JournalStore(self.root / "journal").verify().event_count, 3)

    def test_source_fixture_tamper_rejected_before_any_output(self):
        fixtures = self.root.parent / "fixtures"
        fixtures.mkdir()
        original = Path(__file__).resolve().parents[1] / "fixtures"
        for directory, filename in (("shadow_galactica_analysis", "blackwell_brigade.py"), ("shadow_brigade_analysis", "decay.py")):
            (fixtures / directory).mkdir()
            shutil.copyfile(original / directory / filename, fixtures / directory / filename)
        source = fixtures / "shadow_galactica_analysis/blackwell_brigade.py"
        source.write_bytes(source.read_bytes() + b"\n# changed\n")
        with self.assertRaises(ValueError): prepare_example(self.root, fixture_root=fixtures)
        self.assertFalse(self.root.exists())

    def test_source_tree_or_symlink_target_rejected(self):
        target = Path(__file__).resolve().parents[1] / "fixtures/synthetic-forecast-write-test"
        with self.assertRaises((ValueError, JournalStoreError)): prepare_example(target)
        self.assertFalse(target.exists())
        real = self.root.parent / "real"
        real.mkdir(); self.root.symlink_to(real, target_is_directory=True)
        with self.assertRaises((ValueError, OSError, JournalStoreError)): prepare_example(self.root)
        self.assertEqual(list(real.iterdir()), [])

    def test_existing_changed_inputs_cannot_be_overwritten(self):
        prepare_example(self.root)
        changed = b"different immutable input\n"
        (self.root / "intake.json").write_bytes(changed)
        with self.assertRaises((ValueError, OSError, JournalStoreError)): prepare_example(self.root)
        self.assertEqual((self.root / "intake.json").read_bytes(), changed)


if __name__ == "__main__": unittest.main()
