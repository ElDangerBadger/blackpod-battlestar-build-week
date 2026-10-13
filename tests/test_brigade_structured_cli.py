"""Operator rendering and passive commands retain typed evidence safely."""
import contextlib
import io
import json
from pathlib import Path
import socket
import tempfile
import unittest
from unittest.mock import patch

from blackpod_build_week.brigade_shadow_cli import main, render_brigade_review
from blackpod_build_week.brigade_structured_example import example_material, prepare_example
from blackpod_build_week.contracts.brigade_shadow import BrigadeShadowRequest
from blackpod_build_week.decision_journal_store import JournalStore
from blackpod_build_week.forecast_brigade_example import example_material as legacy_material
from blackpod_build_week.forecast_journal import build_brigade_shadow_event
from blackpod_build_week.hashing import canonical_json_bytes, sha256_bytes


class StructuredCLITests(unittest.TestCase):
    def setUp(self):
        self.enterContext(patch.object(socket.socket, "connect", side_effect=AssertionError("network forbidden")))
        self.enterContext(patch("subprocess.Popen", side_effect=AssertionError("process forbidden")))
        self.material = example_material()

    def test_report_names_contract_and_separates_original_json_from_native_projection(self):
        html = render_brigade_review(self.material["replay_event"])
        self.assertIn("passive journal v11", html)
        self.assertIn("blackpod.brigade_member_response.v1", html)
        self.assertIn("Versioned structured response evidence", html)
        self.assertIn("heuristic_confidence", html)
        self.assertIn("AUTOMATION AUTHORITY OFF", html)

    def test_original_v9_report_remains_native_text_format(self):
        html = render_brigade_review(legacy_material()["replay_event"])
        self.assertIn("passive journal v9", html)
        self.assertNotIn("Versioned structured response evidence", html)

    def test_reasoning_and_raw_json_are_html_escaped(self):
        material = self.material
        value = material["replay_request"].to_dict()
        bundle = json.loads(material["blobs"][value["transcript_evidence"]["sha256"]])
        response = json.loads(bundle["transcripts"][0]["response_text"])
        response["reasoning"] = '<script>alert("unsafe")</script>'
        bundle["transcripts"][0]["response_text"] = canonical_json_bytes(response).decode()
        raw = canonical_json_bytes(bundle)
        value["transcript_evidence"].update(sha256=sha256_bytes(raw), size_bytes=len(raw))
        blobs = dict(material["blobs"]); blobs[sha256_bytes(raw)] = raw
        request = BrigadeShadowRequest.from_mapping(value)
        event = build_brigade_shadow_event(request, (material["seed_event"],), blobs)
        html = render_brigade_review(event)
        self.assertNotIn('<script>', html)
        self.assertIn('&lt;script&gt;', html)

    def test_record_then_render_uses_verified_v11_without_inference(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve() / "example"
            prepare_example(root)
            output, errors = io.StringIO(), io.StringIO()
            with contextlib.redirect_stdout(output), contextlib.redirect_stderr(errors):
                status = main(["record", "--journal-root", str(root/'journal'), "--request", str(root/'request.replay.json'), "--evidence-root", str(root/'evidence')])
            self.assertEqual(status, 0, errors.getvalue())
            recorded = json.loads(output.getvalue())
            report = root.parent / 'report' / 'review.html'
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(errors):
                status = main(["render", "--journal-root", str(root/'journal'), "--event-id", recorded['event_id'], "--output", str(report)])
            self.assertEqual(status, 0, errors.getvalue())
            self.assertIn("Versioned structured response evidence", report.read_text())
            events, _ = JournalStore(root/'journal').verified_contents()
            self.assertEqual(len(events), 2)
            self.assertEqual(events[-1].schema_version, 'blackpod.decision_journal_event.v11')
            self.assertEqual(recorded['orders_submitted'], 0)
            self.assertFalse(recorded['auto_trading_changed'])


if __name__ == '__main__': unittest.main()
