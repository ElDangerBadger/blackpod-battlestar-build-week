"""Offline CLI integration and immutable output protection for governed intake."""
import contextlib
import io
import json
from pathlib import Path
import socket
import tempfile
import unittest
from unittest.mock import patch

from blackpod_build_week.decision_journal_store import JournalStore
from blackpod_build_week.trading_historical_example import synthetic_source_material, example_material, REGISTERED_AT, EVALUATED_AT
from blackpod_build_week.trading_research_intake_cli import main
from blackpod_build_week.trading_research_cli import main as research_main, render_research_review


class HistoricalCLITests(unittest.TestCase):
    def setUp(self):
        self.enterContext(patch.object(socket.socket, "connect", side_effect=AssertionError("network forbidden")))
        self.enterContext(patch("subprocess.Popen", side_effect=AssertionError("inference/worker forbidden")))
        temporary = tempfile.TemporaryDirectory(); self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name).resolve()
        self.source = self.base / "source"; self.source.mkdir()
        sources = synthetic_source_material()
        for path, raw in sources["evidence"].items():
            target = self.source / path; target.parent.mkdir(parents=True, exist_ok=True); target.write_bytes(raw)
        self.request = self.source / "request.json"; self.request.write_bytes(sources["request"].to_bytes())
        self.export = self.base / "export"; self.journal = self.base / "journal"

    def call(self, args, function=main):
        output, errors = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(errors):
            code = function(args)
        return code, json.loads(output.getvalue()) if output.getvalue() else None, errors.getvalue()

    def export_args(self, target=None):
        return ["export", "--request", str(self.request), "--evidence-root", str(self.source),
                "--output-directory", str(target or self.export)]

    def record_args(self, clock="2025-04-01T10:15:00Z"):
        return ["record-intake", "--export", str(self.export / "historical-intake/export.v1.json"),
                "--evidence-root", str(self.export), "--journal-root", str(self.journal), "--recorded-at", clock]

    def freeze(self, clock="2025-04-01T09:00:00Z"):
        return self.call(["freeze-hypotheses", "--recorded-at", clock, "--author-id", "fixture-author",
                          "--output-directory", str(self.base / "catalog"), "--journal-root", str(self.journal)])

    def prepare(self, prefix="cli-study"):
        events = JournalStore(self.journal).events()
        return self.call(["prepare-plans", "--journal-root", str(self.journal),
            "--catalog-event-id", events[0].event_id, "--intake-event-id", events[1].event_id,
            "--registered-at", REGISTERED_AT, "--output-directory", str(self.base / "plans"), "--id-prefix", prefix])

    def test_export_verify_and_exact_retry_are_offline(self):
        first = self.call(self.export_args()); second = self.call(self.export_args())
        self.assertEqual(first, second); self.assertEqual(first[0], 0, first[2])
        code, output, errors = self.call(["verify-export", "--export", str(self.export / "historical-intake/export.v1.json"), "--evidence-root", str(self.export)])
        self.assertEqual(code, 0, errors); self.assertTrue(output["verified"])
        self.assertEqual(output["coverage"]["included_session_count"], 40)
        self.assertFalse(self.journal.exists()); self.assertEqual(output["provider_calls"], 0)

    def test_full_cli_pipeline_and_linked_evaluations(self):
        self.assertEqual(self.freeze()[0], 0)
        self.assertEqual(self.call(self.export_args())[0], 0)
        self.assertEqual(self.call(self.record_args())[0], 0)
        code, output, errors = self.prepare(); self.assertEqual(code, 0, errors)
        for row in output["plans"]:
            shared = ["--plan", row["path"], "--journal-root", str(self.journal), "--evidence-root", str(self.base / "plans")]
            self.assertEqual(self.call(["register", *shared], research_main)[0], 0)
            code, evaluation, errors = self.call(["record", *shared, "--evaluation-id", row["plan_id"] + "-quality", "--recorded-at", EVALUATED_AT], research_main)
            self.assertEqual(code, 0, errors); self.assertTrue(evaluation["written"])
        events = JournalStore(self.journal).events()
        self.assertEqual(len(events), 6)
        for event in (events[3], events[5]):
            self.assertIsNone(event.payload["result"]["folds"][0]["metrics"])
            self.assertEqual(event.payload["result"]["folds"][0]["fills"], [])
            self.assertEqual(event.payload["intake_event_id"], events[1].event_id)

    def test_catalog_retry_and_changed_clock_conflict(self):
        self.assertTrue(self.freeze()[1]["written"])
        self.assertFalse(self.freeze()[1]["written"])
        self.assertEqual(self.freeze("2025-04-01T09:01:00Z")[0], 2)
        self.assertEqual(JournalStore(self.journal).verify().event_count, 1)

    def test_intake_retry_and_clock_conflict(self):
        self.call(self.export_args())
        self.assertTrue(self.call(self.record_args())[1]["written"])
        self.assertFalse(self.call(self.record_args())[1]["written"])
        self.assertEqual(self.call(self.record_args("2025-04-01T10:16:00Z"))[0], 2)

    def test_pre_capture_intake_clock_is_rejected(self):
        self.call(self.export_args())
        self.assertEqual(self.call(self.record_args("2025-04-01T09:59:00Z"))[0], 2)

    def test_source_overwrite_is_rejected(self):
        original = self.request.read_bytes()
        self.assertEqual(self.call(self.export_args(self.source))[0], 2)
        self.assertEqual(self.request.read_bytes(), original)

    def test_hash_mismatched_source_is_rejected(self):
        path = self.source / "synthetic-historical/bars.json"
        path.write_bytes(path.read_bytes() + b" ")
        self.assertEqual(self.call(self.export_args())[0], 2)
        self.assertFalse(self.export.exists())

    def test_symlink_output_is_rejected(self):
        self.export.symlink_to(self.source, target_is_directory=True)
        self.assertEqual(self.call(self.export_args())[0], 2)

    def test_unclassified_or_unknown_predecessor_rejected(self):
        self.freeze(); self.call(self.export_args()); self.call(self.record_args())
        events = JournalStore(self.journal).events()
        code, _, _ = self.call(["prepare-plans", "--journal-root", str(self.journal), "--catalog-event-id", events[1].event_id,
            "--intake-event-id", events[0].event_id, "--registered-at", REGISTERED_AT,
            "--output-directory", str(self.base / "plans"), "--id-prefix", "fixture"])
        self.assertEqual(code, 2)

    def test_plan_preparation_does_not_register_or_size_trades(self):
        self.freeze(); self.call(self.export_args()); self.call(self.record_args())
        code, output, errors = self.prepare(); self.assertEqual(code, 0, errors)
        self.assertEqual(JournalStore(self.journal).verify().event_count, 2)
        self.assertEqual(output["strategy_producers"], 0)
        self.assertFalse(output["auto_trading_changed"])
        self.assertEqual(output["orders_submitted"], 0)

    def test_bad_plan_identity_rejected_before_output(self):
        self.freeze(); self.call(self.export_args()); self.call(self.record_args())
        self.assertEqual(self.prepare("../escape")[0], 2)
        self.assertFalse((self.base / "plans").exists())

    def test_render_v14_makes_unscored_status_explicit_and_escapes_text(self):
        event = example_material()["studies"][0]["evaluation_event"]
        html = render_research_review(event)
        self.assertIn("DATA QUALITY ONLY", html); self.assertIn("passive journal v14", html)
        self.assertIn("retrospective assumption", html); self.assertIn("uncalibrated", html)
        self.assertNotIn("passive journal v12", html)


if __name__ == "__main__": unittest.main()
