from __future__ import annotations

import contextlib
import io
import json
import socket
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from unittest import mock

from blackpod_build_week.contracts.investment_hypothesis import InvestmentHypothesis
from blackpod_build_week.decision_journal_cli import main, _identity
from blackpod_build_week.decision_journal_store import JournalStore
from blackpod_build_week.hashing import canonical_json_bytes, sha256_bytes


CHECKOUT = Path(__file__).resolve().parents[1]
HYPOTHESIS = CHECKOUT / "examples/investment_hypothesis.shadow.v1.json"
CHALLENGE = CHECKOUT / "examples/investment_challenge.shadow.v1.json"
EVALUATION = CHECKOUT / "examples/investment_outcome_evaluation.final.v1.json"
HYPOTHESIS_SOURCE = CHECKOUT / "fixtures/investment_hypothesis/missions/mission-investment-hypothesis-example"
CHALLENGE_SOURCE = CHECKOUT / "fixtures/investment_review/missions/mission-investment-challenge-evidence"
OUTCOME_SOURCE = CHECKOUT / "fixtures/investment_review/missions/mission-investment-outcome-evidence"


def state(root):
    return {str(path.relative_to(root)): (path.read_bytes(), path.stat().st_mtime_ns)
            for path in root.rglob("*") if path.is_file()}


class InvestmentReviewCliTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.base = Path(temp.name).resolve()
        self.journal = self.base / "journal"
        self.challenge = json.loads(CHALLENGE.read_bytes())
        self.evaluation = json.loads(EVALUATION.read_bytes())
        self.challenge_input = self.base / "challenge.json"
        self.evaluation_input = self.base / "evaluation.json"
        self.save()
        self.enterContext(mock.patch.object(socket.socket, "connect", side_effect=AssertionError("network forbidden")))
        self.enterContext(mock.patch("subprocess.run", side_effect=AssertionError("producer forbidden")))
        self.assert_ok("export-mission", "--mission-root", HYPOTHESIS_SOURCE)
        self.assert_ok("record-hypothesis", "--hypothesis", HYPOTHESIS)
        self.assert_ok("export-mission", "--mission-root", CHALLENGE_SOURCE)

    def save(self):
        self.challenge_input.write_bytes(canonical_json_bytes(self.challenge))
        self.evaluation_input.write_bytes(canonical_json_bytes(self.evaluation))

    def invoke(self, command, *extra, journal=None):
        args = [command, "--journal-root", str(self.journal if journal is None else journal)]
        if command in {"validate-challenge", "record-challenge"}:
            args += ["--challenge", str(self.challenge_input)]
        elif command in {"evaluate-hypothesis", "record-hypothesis-evaluation"}:
            args += ["--evaluation", str(self.evaluation_input)]
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = main([*args, *map(str, extra)])
        return code, out.getvalue(), err.getvalue()

    def assert_ok(self, command, *extra):
        code, out, err = self.invoke(command, *extra)
        self.assertEqual((code, err), (0, ""), err)
        return json.loads(out)

    def ready(self):
        self.assert_ok("record-challenge")
        self.assert_ok("export-mission", "--mission-root", OUTCOME_SOURCE)

    def test_challenge_validate_show_and_retry_preserve_sources(self):
        before_source = state(HYPOTHESIS_SOURCE), state(CHALLENGE_SOURCE)
        before = state(self.journal)
        preview = self.assert_ok("validate-challenge")
        self.assertEqual(before, state(self.journal))
        assessment = preview["assessment"]
        self.assertFalse(assessment["source_independence_verified"])
        self.assertFalse(assessment["reviewer_identity_authenticated"])
        self.assertEqual(assessment["missing_evidence_roles"], [])
        self.assertIn("SAME_VALUE_BINDING", [item["relationship"] for item in assessment["source_relationships"]])
        self.assertIn("DISTINCT_RETAINED_ARTIFACT", [item["relationship"] for item in assessment["source_relationships"]])
        recorded = self.assert_ok("record-challenge")
        self.assertTrue(recorded["written"])
        after = state(self.journal)
        self.assertFalse(self.assert_ok("record-challenge")["written"])
        shown = self.assert_ok("show-challenge", "--challenge-id", self.challenge["challenge_id"])
        self.assertEqual(shown["challenge"], self.challenge)
        self.assertEqual(after, state(self.journal))
        self.assertEqual(before_source, (state(HYPOTHESIS_SOURCE), state(CHALLENGE_SOURCE)))

    def test_complete_deadline_comparison_is_not_thesis_authorization(self):
        self.ready()
        original = state(self.journal)
        preview = self.assert_ok("evaluate-hypothesis")
        self.assertEqual(original, state(self.journal))
        report = preview["result"]
        self.assertEqual(report["comparison_summary"], "ALL_EXPECTATIONS_MET_NO_DEADLINE_INVALIDATION")
        self.assertTrue(report["manual_review_required"])
        self.assertFalse(report["whole_horizon_invalidation_established"])
        self.assertFalse(report["economic_truth_evaluated"])
        self.assertEqual(report["execution_status"], "NOT_EXECUTED")
        self.assertIsNone(report["realized_trade_pnl"])
        self.assertTrue(all(flag is False for flag in report["authority"].values()))
        self.assertTrue(self.assert_ok("record-hypothesis-evaluation")["written"])
        for path, value in original.items():
            self.assertEqual(state(self.journal)[path], value)
        after = state(self.journal)
        self.assertFalse(self.assert_ok("record-hypothesis-evaluation")["written"])
        shown = self.assert_ok("show-hypothesis-evaluation", "--evaluation-id", self.evaluation["evaluation_id"])
        self.assertEqual(shown["evaluation"], self.evaluation)
        self.assertEqual(after, state(self.journal))
        events = JournalStore(self.journal).events()
        original_hypothesis = next(event for event in events if event.event_type == "INVESTMENT_HYPOTHESIS_RECORDED")
        self.assertEqual(original_hypothesis.payload, json.loads(HYPOTHESIS.read_bytes()))
        self.assertEqual(len(events), 9)

    def test_missing_interim_and_invalidation_results_are_distinct(self):
        self.ready()
        before = state(self.journal)
        for case, expected in (("missing", "INCONCLUSIVE"), ("interim", "PENDING"),
                               ("invalidation", "INVALIDATION_TRIGGERED")):
            self.evaluation = json.loads((CHECKOUT / f"examples/investment_outcome_evaluation.{case}.v1.json").read_bytes())
            self.save()
            with self.subTest(case=case):
                self.assertEqual(self.assert_ok("evaluate-hypothesis")["result"]["comparison_summary"], expected)
        self.assertEqual(before, state(self.journal))

    def test_challenge_required_before_outcome_evaluation(self):
        self.assert_ok("export-mission", "--mission-root", OUTCOME_SOURCE)
        before = state(self.journal)
        self.assertEqual(self.invoke("evaluate-hypothesis")[0], 2)
        self.assertEqual(before, state(self.journal))

    def test_self_challenge_or_self_evaluation_is_rejected(self):
        author = json.loads(HYPOTHESIS.read_bytes())["author_id"]
        self.challenge["reviewer_id"] = author
        self.save()
        self.assertEqual(self.invoke("record-challenge")[0], 2)
        self.challenge = json.loads(CHALLENGE.read_bytes())
        self.save()
        self.ready()
        self.evaluation["evaluator_id"] = author
        self.save()
        self.assertEqual(self.invoke("record-hypothesis-evaluation")[0], 2)

    def test_early_final_does_not_invent_measurements(self):
        self.ready()
        self.evaluation.update(evidence_cutoff_at="2027-01-11T00:00:00Z", recorded_at="2027-01-11T00:00:00Z", measurements=[])
        self.save()
        self.assertEqual(self.invoke("evaluate-hypothesis")[0], 2)
        self.assertEqual(JournalStore(self.journal).verify().event_count, 8)

    def test_metric_unit_role_and_deadline_cannot_override_original_plan(self):
        self.ready()
        baseline = deepcopy(self.evaluation)
        for change in ("metric", "unit", "role", "deadline"):
            self.evaluation = deepcopy(baseline)
            if change == "role":
                self.evaluation["evaluator_role"] = "OTHER_REVIEW_ROLE"
            elif change == "deadline":
                self.evaluation["measurements"] = self.evaluation["measurements"][:1]
                self.evaluation["measurements"][0]["observation"]["as_of"] = "2027-04-10T00:00:00Z"
            else:
                self.evaluation["measurements"][0][change] = "OTHER_DEFINITION"
                if change == "unit":
                    self.evaluation["measurements"] = self.evaluation["measurements"][:1]
                    self.evaluation["measurements"][0]["observation"]["unit"] = "OTHER_DEFINITION"
            self.save()
            with self.subTest(change=change):
                self.assertEqual(self.invoke("record-hypothesis-evaluation")[0], 2)
        self.assertEqual(JournalStore(self.journal).verify().event_count, 8)

    def test_same_review_identity_changed_content_is_a_conflict(self):
        self.ready()
        self.assert_ok("record-hypothesis-evaluation")
        before = state(self.journal)
        self.evaluation["conclusion"] = "Changed narrative under the same immutable evaluation identity."
        self.challenge["risk_notes"].append("Changed risk note under the same challenge identity.")
        self.save()
        for command in ("validate-challenge", "record-challenge", "evaluate-hypothesis", "record-hypothesis-evaluation"):
            self.assertEqual(self.invoke(command)[0], 2)
        self.assertEqual(before, state(self.journal))

    def test_correction_appends_and_original_remains_queryable(self):
        self.ready()
        first = self.assert_ok("record-hypothesis-evaluation")
        original_bytes = (self.journal / "entries/00000009.json").read_bytes()
        self.evaluation.update(evaluation_id="synthetic-final-correction-002", supersedes_event_id=first["event_id"],
                               recorded_at="2027-04-12T00:00:00Z", evidence_cutoff_at="2027-04-12T00:00:00Z",
                               conclusion="Linked correction preserves original fixed deadline measurements and plan.")
        self.save()
        self.assertTrue(self.assert_ok("record-hypothesis-evaluation")["written"])
        self.assertEqual((self.journal / "entries/00000009.json").read_bytes(), original_bytes)
        shown = self.assert_ok("show-hypothesis-evaluation", "--evaluation-id", "synthetic-financing-final-001")
        self.assertEqual(shown["evaluation"]["supersedes_event_id"], None)
        self.assertEqual(JournalStore(self.journal).verify().event_count, 10)

    def test_legacy_mission_evaluation_cannot_be_used_for_thesis_review(self):
        self.ready()
        self.assertEqual(self.invoke("append-evaluation", "--evaluation", self.evaluation_input)[0], 2)
        self.assertEqual(JournalStore(self.journal).verify().event_count, 8)

    def test_realized_pnl_or_activation_fields_are_rejected(self):
        self.ready()
        for field, value in (("realized_trade_pnl", 0), ("order", {}), ("capital_transfers_enabled", True)):
            self.evaluation = json.loads(EVALUATION.read_bytes())
            self.evaluation[field] = value
            self.save()
            with self.subTest(field=field):
                self.assertEqual(self.invoke("record-hypothesis-evaluation")[0], 2)
        self.challenge["authority"]["authorization_enabled"] = True
        self.save()
        self.assertEqual(self.invoke("record-challenge")[0], 2)

    def test_corrupt_source_blocks_review_and_idempotent_retry(self):
        self.ready()
        self.assert_ok("record-hypothesis-evaluation")
        blob = self.journal / "evidence" / self.evaluation["measurements"][0]["observation"]["artifact_sha256"]
        blob.chmod(0o600)
        blob.write_bytes(b"corrupt outcome evidence")
        for command in ("evaluate-hypothesis", "record-hypothesis-evaluation", "validate-challenge", "verify"):
            self.assertEqual(self.invoke(command)[0], 2)
        self.assertEqual(len(list((self.journal / "entries").iterdir())), 9)

    def test_malformed_json_and_linked_input_fail_cleanly(self):
        for raw in (b'{"challenge_id":"a","challenge_id":"b"}',
                    b'{"observations":' + b'[' * 2000 + b'0' + b']' * 2000 + b'}'):
            self.challenge_input.write_bytes(raw)
            self.assertEqual(self.invoke("record-challenge")[0], 2)
        self.save()
        target = self.base / "original-challenge.json"
        self.challenge_input.rename(target)
        self.challenge_input.symlink_to(target)
        self.assertEqual(self.invoke("record-challenge")[0], 2)

    def test_new_commands_never_create_missing_or_mutate_source_storage(self):
        before = state(HYPOTHESIS_SOURCE)
        commands = (("validate-challenge", ()), ("record-challenge", ()),
                    ("evaluate-hypothesis", ()), ("record-hypothesis-evaluation", ()),
                    ("show-challenge", ("--challenge-id", "missing")),
                    ("show-hypothesis-evaluation", ("--evaluation-id", "missing")))
        missing = self.base / "missing"
        for command, arguments in commands:
            for root in (missing, HYPOTHESIS_SOURCE):
                with self.subTest(command=command, root=root):
                    self.assertEqual(self.invoke(command, *arguments, journal=root)[0], 2)
        self.assertFalse(missing.exists())
        self.assertEqual(before, state(HYPOTHESIS_SOURCE))

    def test_query_disambiguation_never_selects_an_arbitrary_hypothesis(self):
        self.assert_ok("record-challenge")
        value = json.loads(HYPOTHESIS.read_bytes())
        value["hypothesis_id"] = "another-synthetic-hypothesis"
        second = InvestmentHypothesis.from_mapping(value)
        path = self.base / "second.json"
        path.write_bytes(second.to_bytes())
        self.assert_ok("record-hypothesis", "--hypothesis", path)
        second_decision = _identity("journal-decision", {"kind": "INVESTMENT_HYPOTHESIS", "hypothesis_id": second.hypothesis_id})
        self.challenge.update(hypothesis_id=second.hypothesis_id, hypothesis_sha256=sha256_bytes(second.to_bytes()),
                              hypothesis_event_id=_identity("journal-event", {"decision_id": second_decision, "event_type": "INVESTMENT_HYPOTHESIS_RECORDED"}))
        self.save()
        self.assert_ok("record-challenge")
        self.assertEqual(self.invoke("show-challenge", "--challenge-id", self.challenge["challenge_id"])[0], 2)
        shown = self.assert_ok("show-challenge", "--challenge-id", self.challenge["challenge_id"], "--hypothesis-id", second.hypothesis_id)
        self.assertEqual(shown["challenge"]["hypothesis_id"], second.hypothesis_id)

    def test_committed_synthetic_fixture_histories_and_examples_validate(self):
        self.ready()
        verification = JournalStore(self.journal).verify()
        self.assertEqual(verification.event_count, 8)
        events = JournalStore(self.journal).events()
        self.assertTrue(all(event.domain == "UNCLASSIFIED" for event in events if event.event_type == "MISSION_SNAPSHOT_RECORDED"))
        self.assertTrue(all(event.payload["historical_semantics"]["hypothesis"] == "NOT_RECORDED"
                            for event in events if event.event_type == "MISSION_SNAPSHOT_RECORDED"))
        self.assertEqual(verification.orphan_evidence_count, 0)


if __name__ == "__main__":
    unittest.main()
