from __future__ import annotations

import contextlib
import io
import json
import socket
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest import mock

from blackpod_build_week.contracts import MissionRequest
from blackpod_build_week.decision_journal_cli import main
from blackpod_build_week.decision_journal_store import JournalStore
from blackpod_build_week.hashing import canonical_json_bytes, sha256_file
from blackpod_build_week.mission_store import MissionStore


class DecisionJournalCliTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name).resolve()
        self.journal = self.base / "journal"
        self.source = self.base / "source"
        request = MissionRequest.from_mapping({
            "schema_version": "blackpod.mission_request.v1",
            "mission_id": "mission-journal-cli", "request_id": "request-journal-cli",
            "run_mode": "REPLAY", "symbol": "AAPL", "requested_at": "2026-10-11T00:00:00Z",
            "operator_id": "fixture-operator",
        })
        self.mission = MissionStore(self.source).initialize(
            request, mission_id=request.mission_id, started_at=request.requested_at,
            observed_at=request.requested_at,
        ).paths.mission_root
        self.input_hashes = {
            str(p.relative_to(self.mission)): sha256_file(p)
            for p in self.mission.rglob("*") if p.is_file()
        }
        # These commands must never acquire data or invoke a remote service.
        self.enterContext(mock.patch.object(socket.socket, "connect", side_effect=AssertionError("network forbidden")))
        self.enterContext(mock.patch("subprocess.run", side_effect=AssertionError("producer forbidden")))

    def invoke(self, *args):
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = main(list(map(str, args)))
        return code, stdout.getvalue(), stderr.getvalue()

    def export(self, *extra):
        return self.invoke("export-mission", "--mission-root", self.mission,
                           "--journal-root", self.journal, *extra)

    def write_evaluation(self, decision_id, **changes):
        value = {
            "schema_version": "blackpod.decision_journal_evaluation.v1",
            "evaluation_id": "evaluation-process-001", "decision_id": decision_id,
            "recorded_at": "2026-10-12T00:00:00Z", "evaluator": "fixture-reviewer",
            "evaluation_type": "PROCESS", "conclusion": "No execution was authorized.",
            "outcome_status": "OBSERVED", "realized_trade_pnl": None,
            **changes,
        }
        path = self.base / "evaluation.json"
        path.write_bytes(canonical_json_bytes(value))
        return path

    def test_export_and_retry_preserve_source_and_events(self):
        code, out, err = self.export()
        self.assertEqual((code, err), (0, ""))
        result = json.loads(out)
        self.assertEqual(result["domain"], "UNCLASSIFIED")
        self.assertEqual(result["written"], 1)
        first_bytes = (self.journal / "entries" / "00000001.json").read_bytes()
        code, out, err = self.export()
        self.assertEqual((code, err), (0, ""))
        self.assertEqual(json.loads(out)["unchanged"], 1)
        self.assertEqual(first_bytes, (self.journal / "entries" / "00000001.json").read_bytes())
        self.assertEqual(self.input_hashes, {
            str(p.relative_to(self.mission)): sha256_file(p)
            for p in self.mission.rglob("*") if p.is_file()
        })

    def test_verify_is_read_only_and_retained_evidence_survives_source_removal(self):
        self.assertEqual(self.export()[0], 0)
        moved = self.base / "source-unavailable"
        self.source.rename(moved)
        before = {str(p): (p.read_bytes(), p.stat().st_mtime_ns) for p in self.journal.rglob("*") if p.is_file()}
        code, out, err = self.invoke("verify", "--journal-root", self.journal)
        self.assertEqual((code, err), (0, ""))
        self.assertEqual(json.loads(out)["event_count"], 1)
        self.assertEqual(before, {str(p): (p.read_bytes(), p.stat().st_mtime_ns) for p in self.journal.rglob("*") if p.is_file()})

    def test_missing_source_never_creates_source_or_journal(self):
        missing = self.base / "missing" / "missions" / "mission-absent"
        code, _, err = self.invoke("export-mission", "--mission-root", missing,
                                   "--journal-root", self.journal)
        self.assertEqual(code, 2)
        self.assertTrue(err)
        self.assertFalse((self.base / "missing").exists())
        self.assertFalse(self.journal.exists())

    def test_verify_missing_journal_does_not_create_it(self):
        self.assertEqual(self.invoke("verify", "--journal-root", self.journal)[0], 2)
        self.assertFalse(self.journal.exists())

    def test_export_refuses_any_source_storage_overlap(self):
        for target in (self.source, self.mission, self.mission / "journal", self.source / "journal"):
            with self.subTest(target=target):
                code, _, _ = self.invoke("export-mission", "--mission-root", self.mission,
                                         "--journal-root", target)
                self.assertEqual(code, 2)
        self.assertEqual(self.input_hashes, {
            str(p.relative_to(self.mission)): sha256_file(p)
            for p in self.mission.rglob("*") if p.is_file()
        })

    def test_classification_requires_explicit_reason(self):
        self.assertEqual(self.export("--domain", "INVESTMENT")[0], 2)
        self.assertFalse(self.journal.exists())
        code, out, err = self.export("--domain", "INVESTMENT", "--classification-reason", "Explicit historical research import.")
        self.assertEqual((code, err), (0, ""))
        self.assertEqual(json.loads(out)["domain"], "INVESTMENT")

    def test_reclassification_is_a_conflict(self):
        self.assertEqual(self.export()[0], 0)
        before = JournalStore(self.journal).verify().to_dict()
        self.assertEqual(self.export("--domain", "TRADING", "--classification-reason", "Attempted relabeling.")[0], 2)
        self.assertEqual(JournalStore(self.journal).verify().to_dict(), before)

    def test_linked_evaluation_is_append_only_and_retry_is_idempotent(self):
        decision = json.loads(self.export()[1])["decision_id"]
        original = (self.journal / "entries" / "00000001.json").read_bytes()
        evaluation = self.write_evaluation(decision)
        args = ("append-evaluation", "--journal-root", self.journal, "--evaluation", evaluation)
        code, out, err = self.invoke(*args)
        self.assertEqual((code, err), (0, ""))
        self.assertTrue(json.loads(out)["written"])
        self.assertEqual(original, (self.journal / "entries" / "00000001.json").read_bytes())
        self.assertFalse(json.loads(self.invoke(*args)[1])["written"])
        events = JournalStore(self.journal).events()
        self.assertEqual(len(events), 2)
        self.assertEqual(events[-1].decision_id, decision)
        self.assertIsNone(events[-1].payload["realized_trade_pnl"])

    def test_conflicting_evaluation_id_fails(self):
        decision = json.loads(self.export()[1])["decision_id"]
        args = ("append-evaluation", "--journal-root", self.journal, "--evaluation", self.write_evaluation(decision))
        self.assertEqual(self.invoke(*args)[0], 0)
        self.write_evaluation(decision, conclusion="Changed conclusion using the same identity.")
        self.assertEqual(self.invoke(*args)[0], 2)
        self.assertEqual(len(JournalStore(self.journal).events()), 2)

    def test_evaluation_retry_keeps_original_context_after_source_growth(self):
        decision = json.loads(self.export()[1])["decision_id"]
        path = self.write_evaluation(decision)
        args = ("append-evaluation", "--journal-root", self.journal, "--evaluation", path)
        self.assertEqual(self.invoke(*args)[0], 0)
        store = MissionStore(self.source)
        loaded = store.load_mission("mission-journal-cli")
        updated = replace(loaded.snapshot, revision=2, snapshot_id="mission-journal-cli-r0002",
                          previous_snapshot_sha256=loaded.current_snapshot_sha256,
                          observed_at="2026-10-13T00:00:00Z")
        store.commit_snapshot(loaded.paths, updated)
        self.assertEqual(self.export()[0], 0)
        code, out, err = self.invoke(*args)
        self.assertEqual((code, err), (0, ""))
        self.assertFalse(json.loads(out)["written"])
        self.assertEqual(len(JournalStore(self.journal).events()), 3)

    def test_no_realized_pnl_or_trade_evaluation_for_nonexecution(self):
        decision = json.loads(self.export()[1])["decision_id"]
        for change in ({"realized_trade_pnl": 0}, {"realized_trade_pnl": 12.5}, {"evaluation_type": "TRADE"}):
            with self.subTest(change=change):
                path = self.write_evaluation(decision, **change)
                self.assertEqual(self.invoke("append-evaluation", "--journal-root", self.journal,
                                             "--evaluation", path)[0], 2)
        self.assertEqual(len(JournalStore(self.journal).events()), 1)

    def test_unknown_link_fails(self):
        self.assertEqual(self.export()[0], 0)
        path = self.write_evaluation("journal-decision-" + "f" * 64)
        self.assertEqual(self.invoke("append-evaluation", "--journal-root", self.journal,
                                     "--evaluation", path)[0], 2)

    def test_inactive_baseline_proposal_is_validated_and_idempotent(self):
        proposal = Path(__file__).resolve().parents[1] / "examples/capital_policy.proposed.v1.json"
        args = ("propose-capital-policy", "--journal-root", self.journal, "--proposal", proposal)
        code, out, err = self.invoke(*args)
        self.assertEqual((code, err), (0, ""))
        self.assertEqual(json.loads(out)["status"], "PROPOSED")
        self.assertFalse(json.loads(out)["activation_enabled"])
        self.assertFalse(json.loads(self.invoke(*args)[1])["written"])
        event = JournalStore(self.journal).events()[0]
        self.assertEqual(event.domain, "CAPITAL_ALLOCATION")
        self.assertEqual(event.payload["allocations"], {"TRADING": 0.5, "INVESTMENT": 0.5})

    def test_activated_policy_rejected_before_storage(self):
        proposal = Path(__file__).resolve().parents[1] / "examples/capital_policy.proposed.v1.json"
        value = json.loads(proposal.read_bytes())
        value["activation_enabled"] = True
        path = self.base / "active.json"
        path.write_bytes(canonical_json_bytes(value))
        self.assertEqual(self.invoke("propose-capital-policy", "--journal-root", self.journal,
                                     "--proposal", path)[0], 2)
        self.assertFalse(self.journal.exists())

    def test_policy_command_cannot_write_into_any_mission_storage(self):
        proposal = Path(__file__).resolve().parents[1] / "examples/capital_policy.proposed.v1.json"
        for target in (self.source, self.mission, self.mission / "journal", self.source / "journal"):
            with self.subTest(target=target):
                self.assertEqual(self.invoke("propose-capital-policy", "--journal-root", target,
                                             "--proposal", proposal)[0], 2)
        self.assertEqual(self.input_hashes, {
            str(p.relative_to(self.mission)): sha256_file(p)
            for p in self.mission.rglob("*") if p.is_file()
        })
        self.assertFalse((self.source / "journal").exists())
        self.assertFalse((self.source / ".journal.lock").exists())
        self.assertFalse((self.mission / ".journal.lock").exists())

    def test_malformed_json_is_reported(self):
        self.assertEqual(self.export()[0], 0)
        path = self.base / "invalid.json"
        path.write_text('{"evaluation_id":"one","evaluation_id":"two"}')
        self.assertEqual(self.invoke("append-evaluation", "--journal-root", self.journal,
                                     "--evaluation", path)[0], 2)

    def test_input_symlink_is_rejected(self):
        self.assertEqual(self.export()[0], 0)
        decision = JournalStore(self.journal).events()[0].decision_id
        target = self.write_evaluation(decision)
        linked = self.base / "linked.json"
        linked.symlink_to(target)
        self.assertEqual(self.invoke("append-evaluation", "--journal-root", self.journal,
                                     "--evaluation", linked)[0], 2)

    def test_root_dispatch_and_help(self):
        from blackpod_build_week.harbormaster import main as root_main
        with contextlib.redirect_stdout(io.StringIO()), self.assertRaises(SystemExit) as result:
            root_main(["journal", "--help"])
        self.assertEqual(result.exception.code, 0)


if __name__ == "__main__":
    unittest.main()
