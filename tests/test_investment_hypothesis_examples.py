"""Exercise committed synthetic examples through the actual offline interfaces."""

from __future__ import annotations

import contextlib
import io
import json
import socket
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from blackpod_build_week.contracts import MissionRequest, MissionSnapshot
from blackpod_build_week.contracts.investment_hypothesis import InvestmentHypothesis
from blackpod_build_week.decision_journal_cli import main
from blackpod_build_week.decision_journal_projection import load_verified_history, project_history
from blackpod_build_week.decision_journal_store import JournalStore
from blackpod_build_week.hashing import canonical_json_bytes, sha256_bytes, sha256_file
from blackpod_build_week.mission_store import MissionStore


CHECKOUT = Path(__file__).resolve().parents[1]
MISSION = CHECKOUT / "fixtures/investment_hypothesis/missions/mission-investment-hypothesis-example"
EXAMPLE = CHECKOUT / "examples/investment_hypothesis.shadow.v1.json"
ARTIFACT = "research/synthetic_observations.json"


def file_state(root: Path):
    return {str(path.relative_to(root)): (path.read_bytes(), path.stat().st_mtime_ns)
            for path in root.rglob("*") if path.is_file()}


class InvestmentHypothesisExampleTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name).resolve()
        self.journal = self.base / "journal"
        # No example command may acquire data, start a producer or call a broker.
        self.enterContext(mock.patch.object(socket.socket, "connect", side_effect=AssertionError("network forbidden")))
        self.enterContext(mock.patch("subprocess.run", side_effect=AssertionError("producer forbidden")))
        self.example = InvestmentHypothesis.from_bytes(EXAMPLE.read_bytes())

    def invoke(self, *args):
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            result = main(list(map(str, args)))
        self.assertEqual((result, stderr.getvalue()), (0, ""), stderr.getvalue())
        return json.loads(stdout.getvalue())

    def export(self):
        return self.invoke("export-mission", "--mission-root", MISSION,
                           "--journal-root", self.journal)

    def test_fixture_reconstructs_exactly_through_public_mission_store(self):
        request = MissionRequest.from_file(MISSION / "request/mission_request.json")
        store = MissionStore(self.base / "reconstructed")
        initialized = store.initialize(request, mission_id=request.mission_id,
                                       started_at=request.requested_at, observed_at=request.requested_at)
        observation = json.loads((MISSION / ARTIFACT).read_bytes())
        self.assertEqual(observation["source_kind"], "SYNTHETIC_FIXTURE")
        artifact = store.write_immutable_artifact(
            request.mission_id, relative_path=ARTIFACT,
            payload=canonical_json_bytes(observation), name="synthetic_observations",
            producer="offline-fixture-author", schema_version=observation["schema_version"],
            observed_at=request.requested_at,
        )
        revision = initialized.snapshot.to_dict()
        revision.update(snapshot_id=request.mission_id + "-r0002", revision=2,
                        previous_snapshot_sha256=initialized.snapshot_sha256,
                        artifacts=[*revision["artifacts"], artifact.to_dict()])
        store.commit_snapshot(initialized.paths, MissionSnapshot.from_mapping(revision))
        expected = {name: value[0] for name, value in file_state(MISSION).items()}
        actual = {name: value[0] for name, value in file_state(initialized.paths.mission_root).items()}
        self.assertEqual(expected, actual)

    def test_example_binds_exact_committed_revision_artifact_and_values(self):
        history = load_verified_history(MISSION)
        events = project_history(history)
        self.assertEqual(len(events), 2)
        self.assertTrue(all(event.domain == "UNCLASSIFIED" for event in events))
        self.assertTrue(all(event.payload["execution_status"] == "NOT_EXECUTED" for event in events))
        self.assertTrue(all(event.payload["historical_semantics"]["hypothesis"] == "NOT_RECORDED" for event in events))
        observations = self.example.to_dict()["observations"]
        artifact = json.loads((MISSION / ARTIFACT).read_bytes())
        for observation in observations:
            self.assertEqual(observation["source_event_id"], events[-1].event_id)
            self.assertEqual(observation["artifact_path"], ARTIFACT)
            self.assertEqual(observation["artifact_sha256"], sha256_file(MISSION / ARTIFACT))
            metric = observation["value_pointer"].split("/")[-1]
            self.assertEqual(observation["value"], artifact["metrics"][metric])
            self.assertEqual(observation["as_of_pointer"], "/as_of")
            self.assertEqual(observation["as_of"], artifact["as_of"])
            self.assertEqual(observation["time_role"], "AS_OF")
        self.assertTrue(all(value is False for value in self.example.to_dict()["authority"].values()))

    def test_documented_cli_sequence_is_read_only_until_explicit_record(self):
        source_before = file_state(MISSION)
        exported = self.export()
        self.assertEqual(exported["written"], 2)
        original = file_state(self.journal)
        self.invoke("validate-hypothesis", "--journal-root", self.journal, "--hypothesis", EXAMPLE)
        self.assertEqual(original, file_state(self.journal))
        recorded = self.invoke("record-hypothesis", "--journal-root", self.journal, "--hypothesis", EXAMPLE)
        self.assertTrue(recorded["written"])
        for path, state in original.items():
            self.assertEqual(file_state(self.journal)[path], state)
        after_record = file_state(self.journal)
        shown = self.invoke("show-hypothesis", "--journal-root", self.journal,
                            "--hypothesis-id", self.example.to_dict()["hypothesis_id"])
        self.assertEqual(shown["hypothesis"], self.example.to_dict())
        self.assertEqual(after_record, file_state(self.journal))
        retry = self.invoke("record-hypothesis", "--journal-root", self.journal, "--hypothesis", EXAMPLE)
        self.assertFalse(retry["written"])
        self.assertEqual(after_record, file_state(self.journal))
        verification = self.invoke("verify", "--journal-root", self.journal)
        self.assertEqual(verification["event_count"], 3)
        events = JournalStore(self.journal).events()
        self.assertEqual([event.schema_version for event in events],
                         ["blackpod.decision_journal_event.v1"] * 2 + ["blackpod.decision_journal_event.v2"])
        self.assertEqual(events[-1].event_type, "INVESTMENT_HYPOTHESIS_RECORDED")
        self.assertEqual(events[-1].domain, "INVESTMENT")
        self.assertTrue(all(event.domain == "UNCLASSIFIED" for event in events[:2]))
        self.assertEqual(source_before, file_state(MISSION))

    def test_retained_example_sources_remain_available_without_mission(self):
        self.export()
        events, blobs = JournalStore(self.journal).verified_contents()
        self.assertIn(sha256_file(MISSION / ARTIFACT), blobs)
        self.assertEqual(blobs[sha256_file(MISSION / ARTIFACT)], (MISSION / ARTIFACT).read_bytes())
        self.assertEqual(sha256_bytes(blobs[sha256_file(MISSION / ARTIFACT)]), sha256_file(MISSION / ARTIFACT))
        # The hypothesis validator receives only verified retained data; even a
        # reference to canonical mission paths in this operation would fail.
        with mock.patch("blackpod_build_week.decision_journal_cli.load_verified_history",
                        side_effect=AssertionError("mission reread forbidden")):
            self.invoke("validate-hypothesis", "--journal-root", self.journal, "--hypothesis", EXAMPLE)
            self.invoke("record-hypothesis", "--journal-root", self.journal, "--hypothesis", EXAMPLE)
        self.assertEqual(len(events), 2)


if __name__ == "__main__":
    unittest.main()
