from __future__ import annotations

import contextlib
import io
import json
import socket
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from blackpod_build_week.contracts import MissionSnapshot
from blackpod_build_week.decision_journal_cli import main
from blackpod_build_week.decision_journal_projection import VerifiedHistory, load_verified_history, project_history
from blackpod_build_week.decision_journal_store import JournalStore
from blackpod_build_week.hashing import canonical_json_bytes, sha256_bytes


CHECKOUT = Path(__file__).resolve().parents[1]
SOURCE = CHECKOUT / "fixtures/investment_hypothesis/missions/mission-investment-hypothesis-example"
EXAMPLE = CHECKOUT / "examples/investment_hypothesis.shadow.v1.json"


def state(root):
    return {str(path.relative_to(root)): (path.read_bytes(), path.stat().st_mtime_ns)
            for path in root.rglob("*") if path.is_file()}


class InvestmentHypothesisCliTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name).resolve()
        self.journal = self.base / "journal"
        self.draft = json.loads(EXAMPLE.read_bytes())
        self.input = self.base / "hypothesis.json"
        self.input.write_bytes(canonical_json_bytes(self.draft))
        self.history = load_verified_history(SOURCE)
        self.store = JournalStore(self.journal)
        for event in project_history(self.history):
            self.store.append(event, {ref["path"]: self.history.source_files[ref["path"]] for ref in event.evidence})
        self.enterContext(mock.patch.object(socket.socket, "connect", side_effect=AssertionError("network forbidden")))
        self.enterContext(mock.patch("subprocess.run", side_effect=AssertionError("producer forbidden")))

    def invoke(self, command, *extra):
        out, err = io.StringIO(), io.StringIO()
        args = [command, "--journal-root", str(self.journal)]
        if command in {"validate-hypothesis", "record-hypothesis"}:
            args += ["--hypothesis", str(self.input)]
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = main([*args, *map(str, extra)])
        return code, out.getvalue(), err.getvalue()

    def update_input(self, **changes):
        self.draft.update(changes)
        self.input.write_bytes(canonical_json_bytes(self.draft))

    def test_validation_does_not_append_or_claim_economic_truth(self):
        before = state(self.journal)
        code, out, err = self.invoke("validate-hypothesis")
        self.assertEqual((code, err), (0, ""))
        result = json.loads(out)
        self.assertFalse(result["economic_truth_evaluated"])
        self.assertFalse(result["already_recorded"])
        self.assertTrue(all(not flag for flag in result["authority"].values()))
        self.assertEqual(before, state(self.journal))

    def test_wrong_value_and_tampered_source_fail_without_append(self):
        before = state(self.journal)
        self.draft["observations"][0]["value"] = 88
        self.update_input()
        self.assertEqual(self.invoke("record-hypothesis")[0], 2)
        self.assertEqual(before, state(self.journal))
        blob = self.journal / "evidence" / self.draft["observations"][0]["artifact_sha256"]
        blob.chmod(0o600)
        blob.write_bytes(b"tampered retained observation")
        for command in ("validate-hypothesis", "record-hypothesis"):
            self.assertEqual(self.invoke(command)[0], 2)
        self.assertEqual(len(list((self.journal / "entries").iterdir())), 2)

    def test_plan_conflict_is_rejected_by_validation_and_recording(self):
        self.assertEqual(self.invoke("record-hypothesis")[0], 0)
        before = state(self.journal)
        self.draft["expected_outcomes"][0]["threshold"] = 77
        self.update_input()
        for command in ("validate-hypothesis", "record-hypothesis"):
            code, _, err = self.invoke(command)
            self.assertEqual(code, 2)
            self.assertIn("immutable draft", err)
        self.assertEqual(before, state(self.journal))

    def test_show_unknown_or_invalid_identity_is_read_only(self):
        before = state(self.journal)
        for identity in ("missing-hypothesis", "../escape"):
            self.assertEqual(self.invoke("show-hypothesis", "--hypothesis-id", identity)[0], 2)
        self.assertEqual(before, state(self.journal))

    def test_missing_journal_does_not_create_state(self):
        missing = self.base / "absent"
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            result = main(["record-hypothesis", "--journal-root", str(missing),
                           "--hypothesis", str(self.input)])
        self.assertEqual(result, 2)
        self.assertFalse(missing.exists())

    def test_linked_source_can_grow_without_rewriting_hypothesis(self):
        self.assertEqual(self.invoke("record-hypothesis")[0], 0)
        recorded = self.store.events()[-1].to_bytes()
        previous = self.history.snapshot_history[-1]
        third = previous.to_dict()
        third.update(revision=3, snapshot_id=previous.mission_id + "-r0003",
                     previous_snapshot_sha256=sha256_bytes(self.history.source_files["snapshots/mission_snapshot-r0002.json"]),
                     observed_at="2026-10-12T00:00:00Z")
        raw = canonical_json_bytes(MissionSnapshot.from_mapping(third).to_dict())
        files = {**self.history.source_files, "snapshots/mission_snapshot-r0003.json": raw}
        captured = VerifiedHistory(SOURCE, self.history.source_files["request/mission_request.json"], (raw,), files)
        event = project_history(captured)[0]
        self.store.append(event, {ref["path"]: files[ref["path"]] for ref in event.evidence})
        code, out, err = self.invoke("record-hypothesis")
        self.assertEqual((code, err), (0, ""))
        self.assertFalse(json.loads(out)["written"])
        hyp = [entry for entry in self.store.events() if entry.event_type == "INVESTMENT_HYPOTHESIS_RECORDED"]
        self.assertEqual([entry.to_bytes() for entry in hyp], [recorded])

    def test_deep_json_duplicate_keys_and_authority_activation_fail_cleanly(self):
        for raw in (b'{"observations":' + b'[' * 2000 + b'0' + b']' * 2000 + b'}',
                    b'{"hypothesis_id":"one","hypothesis_id":"two"}'):
            self.input.write_bytes(raw)
            self.assertEqual(self.invoke("validate-hypothesis")[0], 2)
            self.assertEqual(self.invoke("record-hypothesis")[0], 2)
        self.draft["authority"]["capital_activation_enabled"] = True
        self.update_input()
        self.assertEqual(self.invoke("record-hypothesis")[0], 2)
        self.assertEqual(self.store.verify().event_count, 2)

    def test_hypothesis_input_links_are_rejected(self):
        original = self.base / "original.json"
        self.input.rename(original)
        self.input.symlink_to(original)
        self.assertEqual(self.invoke("record-hypothesis")[0], 2)
        self.assertEqual(self.store.verify().event_count, 2)

    def test_no_new_command_can_write_into_mission_storage(self):
        before = state(SOURCE)
        for command in ("validate-hypothesis", "record-hypothesis", "show-hypothesis"):
            args = [command, "--journal-root", str(SOURCE)]
            args += (["--hypothesis-id", self.draft["hypothesis_id"]] if command == "show-hypothesis"
                     else ["--hypothesis", str(self.input)])
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(main(args), 2)
        self.assertEqual(before, state(SOURCE))

    def test_legacy_evaluation_does_not_grant_hypothesis_pnl_or_authority(self):
        result = json.loads(self.invoke("record-hypothesis")[1])
        evaluation = self.base / "evaluation.json"
        evaluation.write_bytes(canonical_json_bytes({
            "schema_version": "blackpod.decision_journal_evaluation.v1",
            "evaluation_id": "unsupported-investment-evaluation", "decision_id": result["decision_id"],
            "recorded_at": "2027-04-12T00:00:00Z", "evaluator": "reviewer",
            "evaluation_type": "THESIS", "conclusion": "No hypothesis evaluation workflow implemented.",
            "outcome_status": "INCONCLUSIVE", "realized_trade_pnl": None,
        }))
        self.assertEqual(self.invoke("append-evaluation", "--evaluation", evaluation)[0], 2)
        self.assertEqual(self.store.verify().event_count, 3)


if __name__ == "__main__":
    unittest.main()
