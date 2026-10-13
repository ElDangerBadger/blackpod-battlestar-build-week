"""Runnable synthetic v2 examples, immutable publication and portable replay."""
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

from blackpod_build_week.brigade_structured_example import SYMBOL, example_material, main, prepare_example
from blackpod_build_week.contracts.brigade_response import SCHEMA_VERSION as RESPONSE_CONTRACT
from blackpod_build_week.contracts.brigade_shadow import BrigadeShadowRequest
from blackpod_build_week.decision_journal_store import JournalStore, JournalStoreError
from blackpod_build_week.desk_candidate_review_cli import _references, load_evidence
from blackpod_build_week.forecast_brigade_example import example_material as legacy_example_material
from blackpod_build_week.forecast_journal import build_brigade_shadow_event, evidence_for_brigade_shadow
from blackpod_build_week.hashing import canonical_json_bytes


class BrigadeStructuredExampleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve() / "example"

    def call(self, function, argv):
        output, errors = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(errors):
            code = function(argv)
        self.assertEqual(code, 0, errors.getvalue())
        return json.loads(output.getvalue())

    def tree(self):
        return {str(path.relative_to(self.root)): path.read_bytes() for path in self.root.rglob("*") if path.is_file()}

    def test_material_reuses_synthetic_intake_and_marks_no_provider_provenance(self):
        old, material = legacy_example_material(), example_material()
        self.assertEqual(old["intake"].to_bytes(), material["intake"].to_bytes())
        self.assertEqual(old["seed_event"].to_bytes(), material["seed_event"].to_bytes())
        self.assertEqual(material["seed_event"].payload["result"]["admitted_count"], 3)
        self.assertEqual(material["disabled_request"].symbols, [SYMBOL])
        bundle = json.loads(material["evidence"]["brigade/synthetic-structured-transcripts.json"])
        self.assertEqual(bundle["capture_kind"], "DECLARED_REPLAY")
        self.assertEqual(bundle["transport_records"], [])
        self.assertNotIn("brigade/synthetic-declared-transcripts.json", material["evidence"])

    def test_no_test_credentials_provider_or_controller_imports(self):
        source = (Path(__file__).resolve().parents[1] / "src/blackpod_build_week/brigade_structured_example.py").read_text()
        for forbidden in ("from test_", "import test_", "ModelDockClient", "AutoTradingController", "buried_treasure"):
            self.assertNotIn(forbidden, source)

    def test_material_is_deterministic_and_has_distinct_v2_research_identity(self):
        first, second, old = example_material(), example_material(), legacy_example_material()
        for key in ("intake", "seed_event", "disabled_request", "disabled_event", "replay_request", "replay_event"):
            self.assertEqual(first[key].to_bytes(), second[key].to_bytes())
        self.assertEqual(first["evidence"], second["evidence"])
        self.assertNotEqual(first["replay_event"].event_id, old["replay_event"].event_id)
        self.assertEqual(first["replay_request"].schema_version, "blackpod.brigade_shadow_request.v2")
        self.assertEqual(first["replay_request"].response_contract, RESPONSE_CONTRACT)
        self.assertEqual(first["replay_event"].schema_version, "blackpod.decision_journal_event.v11")

    def test_disabled_structured_example_defers_all_members(self):
        analysis = example_material()["disabled_event"].payload["analysis"]
        self.assertEqual(analysis["schema_version"], "blackpod.shadow_brigade_analysis.v2")
        self.assertEqual(analysis["response_contract"], RESPONSE_CONTRACT)
        self.assertEqual(analysis["response_capture_status"], "INFERENCE_DISABLED")
        for member in analysis["symbols"][0]["member_coverage"]:
            self.assertEqual(member["status"], "DEFER")
            self.assertIn("INFERENCE_DISABLED", member["reason_codes"])
        self.assertTrue(all(opinion["recommendation"] is None for opinion in analysis["symbols"][0]["opinions"]))

    def test_raw_json_native_prompts_projection_and_dissent_remain_separate(self):
        old, material = legacy_example_material(), example_material()
        old_transcripts = old["replay_event"].payload["analysis"]["response_transcripts"]
        analysis = material["replay_event"].payload["analysis"]
        symbol = analysis["symbols"][0]
        self.assertEqual(len(analysis["response_transcripts"]), 5)
        self.assertEqual(len(symbol["dissent"]), 5)
        self.assertEqual({opinion["recommendation"] for opinion in symbol["opinions"]}, {"BUY", "EXIT", "HOLD", "WATCH"})
        for transcript, legacy, opinion in zip(analysis["response_transcripts"], old_transcripts, symbol["opinions"]):
            self.assertEqual(transcript["request"], legacy["request"])
            raw = transcript["response_text"]
            self.assertEqual(raw.encode(), canonical_json_bytes(json.loads(raw)))
            self.assertEqual(json.loads(raw), opinion["structured_response"])
            self.assertEqual(json.loads(raw)["action"], opinion["recommendation"])
            self.assertEqual(opinion["native_response_projection"].splitlines()[0], "ACTION: " + opinion["recommendation"])
            self.assertTrue(opinion["trade_plan_suppressed"])
            self.assertFalse(opinion["confidence_is_probability"])
        self.assertFalse(any(analysis["authority"].values()))
        self.assertFalse(analysis["auto_trading_enabled"])

    def test_prepare_is_immutable_idempotent_and_seeds_one_forecast_event(self):
        first = prepare_example(self.root); retained = self.tree(); second = prepare_example(self.root)
        self.assertTrue(first["seed_written"]); self.assertFalse(second["seed_written"])
        self.assertEqual(self.tree(), retained)
        self.assertEqual(first["data_status"], "SYNTHETIC_FIXTURE")
        self.assertEqual(first["source_dates"], "FIXED_SYNTHETIC_NOT_CURRENT_MARKET_RESEARCH")
        self.assertEqual(first["provider_calls"], 0)
        self.assertEqual(first["model_inference_calls"], 0)
        self.assertFalse(first["auto_trading_changed"])
        self.assertFalse(any(first["authority"].values()))
        result = JournalStore(self.root / "journal").verify()
        self.assertEqual(result.event_count, 1)
        self.assertEqual(result.orphan_evidence_count, 0)
        for filename in ("intake.json", "request.disabled.json", "request.replay.json", "expected-ids.json"):
            self.assertTrue((self.root / filename).is_file())

    def test_preparation_and_replay_never_use_network_subprocess_or_model_loading(self):
        from blackpod_build_week.brigade_shadow_cli import main as brigade_cli
        example_material()  # Load existing numerical libraries before guards.
        with patch.object(socket, "socket", side_effect=AssertionError("network forbidden")), \
                patch.object(subprocess, "Popen", side_effect=AssertionError("process forbidden")), \
                patch("pickle.loads", side_effect=AssertionError("model loading forbidden")), \
                patch("blackpod_build_week.modeldock_client.ModelDockClient.generate_text", side_effect=AssertionError("inference forbidden")):
            prepared = self.call(main, ["--output-root", str(self.root)])
            recorded = self.call(brigade_cli, ["record", "--journal-root", str(self.root / "journal"),
                "--request", str(self.root / "request.replay.json"), "--evidence-root", str(self.root / "evidence")])
        self.assertEqual(recorded["event_id"], prepared["expected_ids"]["brigade_replay"])
        self.assertEqual(recorded["orders_submitted"], 0)
        self.assertFalse(recorded["auto_trading_changed"])

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
        result = store.verify()
        self.assertEqual(result.event_count, 3)
        self.assertEqual(result.orphan_evidence_count, 0)

    def test_generated_example_is_portable_using_only_retained_inputs(self):
        prepared = prepare_example(self.root)
        copied = self.root.parent / "portable"; shutil.copytree(self.root, copied)
        request = BrigadeShadowRequest.from_bytes((copied / "request.replay.json").read_bytes())
        store = JournalStore(copied / "journal")
        events, blobs = store.verified_contents()
        blobs = load_evidence(copied / "evidence", _references(request.to_dict()), blobs)
        with patch("blackpod_build_week.forecast_brigade_example.read_regular", side_effect=AssertionError("fixture reread forbidden")):
            event = build_brigade_shadow_event(request, events, blobs)
            self.assertEqual(event.event_id, prepared["expected_ids"]["brigade_replay"])
            store.append(event, evidence_for_brigade_shadow(request, events, blobs))
            self.assertEqual(store.verify().event_count, 2)

    def test_cli_assess_record_show_and_retry_are_offline(self):
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

    def test_tampered_source_fixture_rejects_before_output(self):
        fixtures = self.root.parent / "fixtures"; fixtures.mkdir()
        original = Path(__file__).resolve().parents[1] / "fixtures"
        for directory, filename in (("shadow_galactica_analysis", "blackwell_brigade.py"), ("shadow_brigade_analysis", "decay.py")):
            (fixtures / directory).mkdir()
            shutil.copyfile(original / directory / filename, fixtures / directory / filename)
        source = fixtures / "shadow_galactica_analysis/blackwell_brigade.py"
        source.write_bytes(source.read_bytes() + b"\n# changed\n")
        with self.assertRaises(ValueError): prepare_example(self.root, fixture_root=fixtures)
        self.assertFalse(self.root.exists())

    def test_source_tree_and_symlink_output_reject_without_changes(self):
        target = Path(__file__).resolve().parents[1] / "fixtures/synthetic-structured-write-test"
        with self.assertRaises((ValueError, JournalStoreError)): prepare_example(target)
        self.assertFalse(target.exists())
        real = self.root.parent / "real"; real.mkdir(); self.root.symlink_to(real, target_is_directory=True)
        with self.assertRaises((ValueError, OSError, JournalStoreError)): prepare_example(self.root)
        self.assertEqual(list(real.iterdir()), [])

    def test_existing_changed_input_cannot_be_overwritten(self):
        prepare_example(self.root)
        changed = b"different immutable structured request\n"
        (self.root / "request.replay.json").write_bytes(changed)
        with self.assertRaises((ValueError, OSError, JournalStoreError)): prepare_example(self.root)
        self.assertEqual((self.root / "request.replay.json").read_bytes(), changed)


if __name__ == "__main__":
    unittest.main()
