from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from blackpod_build_week.contracts import MissionRequest, MissionSnapshot
from blackpod_build_week.contracts.mission_request import ContractValidationError
from blackpod_build_week.decision_journal_projection import (
    HistoryVerificationError,
    load_verified_history,
    project_history,
)
from blackpod_build_week.hashing import canonical_json_bytes, sha256_bytes
from blackpod_build_week.mission_store import MissionStore


AT = "2026-07-18T19:00:00Z"


class DecisionJournalProjectionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        # macOS temporary paths can have a symlinked /var prefix.  Verification
        # intentionally requires a canonical, unlinked source pathname.
        self.base = Path(self.temp.name).resolve()
        self.store = MissionStore(self.base / "source")
        self.request = MissionRequest.from_mapping({
            "schema_version": "blackpod.mission_request.v1",
            "request_id": "request-journal-001",
            "mission_id": "mission-journal-001",
            "run_mode": "REPLAY",
            "symbol": "AAPL",
            "requested_at": AT,
            "operator_id": "request-operator",
            "metadata": {},
        })
        self.initial = self.store.initialize(
            self.request, mission_id=self.request.mission_id,
            started_at=AT, observed_at=AT,
        )
        self.root = self.initial.paths.mission_root

    def tearDown(self) -> None:
        self.temp.cleanup()

    def artifact(self, name: str, value: dict):
        return self.store.write_immutable_artifact(
            self.request.mission_id,
            relative_path=f"fixture/{name}.json",
            payload=canonical_json_bytes(value), name=name,
            producer="fixture", schema_version=None, observed_at=AT,
        )

    def commit_outcome(self, kind: str) -> None:
        loaded = self.store.load_mission(self.request.mission_id)
        value = loaded.snapshot.to_dict()
        value.update({
            "revision": loaded.snapshot.revision + 1,
            "snapshot_id": f"{self.request.mission_id}-r{loaded.snapshot.revision + 1:04d}",
            "previous_snapshot_sha256": loaded.current_snapshot_sha256,
        })
        if kind == "FAILED":
            value["stages"]["oracle"].update({
                "status": "FAILED", "native_state": None,
                "error": {"code": "FIXTURE_FAILURE", "error_type": "FixtureError",
                          "message": "Offline fixture failure", "resumable": False,
                          "observed_at": AT},
            })
            value.update({"mission_outcome": "FAILED", "current_phase": "ORACLE", "terminal": True})
        else:
            state = "HOLD" if kind == "HELD" else "PROCEED"
            decision = self.artifact("governor_decision", {
                "decision_id": "governor-decision-fixture", "decision_state": state,
            })
            value["artifacts"].append(decision.to_dict())
            for name in ("oracle", "council", "governor"):
                value["stages"][name].update({"status": "SUCCEEDED", "native_state": state if name == "governor" else "READY"})
            value["stages"]["governor"]["outputs"] = [decision.name]
            value["operator"]["route"] = "PENDING_REVIEW" if kind == "HELD" else "PENDING_APPROVAL"
            value.update({"mission_outcome": "HELD", "current_phase": "OPERATOR", "terminal": False})
            if kind in {"VETOED", "SHADOW", "APPROVED_WITHOUT_PLAN"}:
                action = "REJECT" if kind == "VETOED" else "APPROVE_HANDOFF"
                result = "REJECTED" if kind == "VETOED" else "APPROVED_FOR_HANDOFF"
                action_artifact = self.artifact("operator_action", {
                    "action_id": "operator-action-fixture", "operator_id": "fixture-human",
                    "source_run_id": self.request.mission_id, "resulting_status": result,
                    "action": action,
                })
                value["artifacts"].append(action_artifact.to_dict())
                value["operator"].update({
                    "action_status": "SUCCEEDED", "action": action, "result": result,
                    "action_id": "operator-action-fixture", "operator_id": "fixture-human",
                    "acted_at": AT,
                })
                if kind == "VETOED":
                    value.update({"mission_outcome": "VETOED", "current_phase": "COMPLETE", "terminal": True})
                else:
                    value["approval_scope"] = "NAVIGATOR_SHADOW_HANDOFF"
                    value["current_phase"] = "NAVIGATOR"
            if kind == "SHADOW":
                prohibited = ["SUBMIT_ORDER", "CANCEL_ORDER", "MODIFY_PORTFOLIO", "BROKER_CALL"]
                plan = self.artifact("navigator_shadow_plan", {
                    "schema_version": "navigator_shadow_plan.v1", "planning_status": "CREATED",
                    "plan_id": "navigator-plan-fixture", "handoff_id": "navigator-handoff-fixture",
                    "source_run_id": self.request.mission_id,
                    "validated_constraints": {"mode": "SHADOW", "allowed_operations": ["VALIDATE", "PLAN_ONLY"],
                                              "prohibited_operations": prohibited},
                    "prohibited_operations": prohibited,
                    "source_artifact_refs": {"operator_action": action_artifact.path},
                    "source_artifact_hashes": {"operator_action": action_artifact.sha256},
                })
                value["artifacts"].append(plan.to_dict())
                value["stages"]["navigator"].update({"status": "SUCCEEDED", "native_state": "CREATED", "outputs": [plan.name]})
                value["navigator"].update({
                    "mode": "SHADOW", "handoff_status": "STAGED", "intake_status": "ACCEPTED", "plan_status": "CREATED",
                    "handoff_id": "navigator-handoff-fixture", "intake_receipt_id": "navigator-receipt-fixture",
                    "plan_id": "navigator-plan-fixture", "expires_at": "2026-07-18T21:00:00Z", "idempotency_key": "navigator-idempotency-fixture",
                    "allowed_operations": ["VALIDATE", "PLAN_ONLY"], "prohibited_operations": prohibited,
                })
                value.update({"mission_outcome": "APPROVED", "current_phase": "COMPLETE", "terminal": True})
        snapshot = MissionSnapshot.from_mapping(value)
        self.store.commit_snapshot(self.initial.paths, snapshot)

    def test_incomplete_capture_is_immutable_and_projection_is_pure(self) -> None:
        (self.root / "unreferenced.json").write_bytes(b"do not retain")
        before = {path.relative_to(self.root).as_posix(): path.read_bytes() for path in self.root.rglob("*") if path.is_file()}
        history = load_verified_history(self.root)
        self.assertEqual(set(history.source_files), {"request/mission_request.json", "snapshots/mission_snapshot-r0001.json"})
        with self.assertRaises(TypeError):
            history.source_files["injected"] = b"bytes"
        copy = history.snapshot_history[0]
        copy.stages.clear()
        self.assertEqual(len(history.snapshot_history[0].stages), 5)
        with patch("pathlib.Path.read_bytes", side_effect=AssertionError("pure projection must not read")):
            first = project_history(history)
            second = project_history(history)
        self.assertEqual([e.to_dict() for e in first], [e.to_dict() for e in second])
        payload = first[0].to_dict()["payload"]
        self.assertEqual(payload["execution_status"], "NOT_EXECUTED")
        self.assertEqual(payload["mission_outcome"], "INCOMPLETE")
        self.assertEqual(set(payload["historical_semantics"].values()), {"NOT_RECORDED"})
        after = {path.relative_to(self.root).as_posix(): path.read_bytes() for path in self.root.rglob("*") if path.is_file()}
        self.assertEqual(before, after)

    def test_all_fixture_outcomes_preserve_scope_and_nonexecution(self) -> None:
        for kind in ("HELD", "VETOED", "FAILED", "SHADOW", "APPROVED_WITHOUT_PLAN"):
            with self.subTest(kind=kind):
                # Each synthetic history has its own source root.
                if kind != "HELD":
                    self.tearDown()
                    self.setUp()
                self.commit_outcome(kind)
                events = project_history(load_verified_history(self.root))
                self.assertEqual(len(events), 2)
                last = events[-1].to_dict()["payload"]
                self.assertEqual(last["execution_status"], "SHADOW_ONLY" if kind == "SHADOW" else "NOT_EXECUTED")
                if kind in {"SHADOW", "APPROVED_WITHOUT_PLAN"}:
                    self.assertEqual(last["authorization"]["status"], "SHADOW_APPROVED")
                    self.assertEqual(last["authorization"]["scope"], "NAVIGATOR_SHADOW_HANDOFF")
                    self.assertEqual(last["decision"]["decision_id"], "governor-decision-fixture")
                if kind == "VETOED":
                    self.assertEqual(last["authorization"]["status"], "REJECTED")
                self.assertNotIn("realized_trade_pnl", last)

    def test_explicit_desk_classification_does_not_change_source_identity(self) -> None:
        history = load_verified_history(self.root)
        original = project_history(history)[0].to_dict()
        for domain in ("TRADING", "INVESTMENT", "CAPITAL_ALLOCATION"):
            with self.assertRaises(ContractValidationError):
                project_history(history, domain)
            classified = project_history(history, domain, "Explicit offline import classification")[0].to_dict()
            self.assertEqual(classified["event_id"], original["event_id"])
            self.assertEqual(classified["decision_id"], original["decision_id"])
            self.assertEqual(classified["source"], original["source"])
            self.assertEqual(classified["payload"]["classification"]["basis"], "EXPLICIT_IMPORT_CLASSIFICATION")
        for reason in ("", " ", " padded "):
            with self.assertRaises(ContractValidationError):
                project_history(history, "TRADING", reason)

    def test_revision_evidence_is_stable_as_mission_grows(self) -> None:
        initial_event = project_history(load_verified_history(self.root))[0].to_dict()
        self.commit_outcome("HELD")
        history = load_verified_history(self.root)
        events = project_history(history)
        self.assertEqual(events[0].to_dict(), initial_event)
        self.assertNotIn("mission_snapshot.json", history.source_files)
        for event in events:
            value = event.to_dict()
            expected_event = "journal-event-" + sha256_bytes(canonical_json_bytes({
                "decision_id": value["decision_id"], "event_type": value["event_type"],
                "revision": value["source"]["revision"],
            }))
            self.assertEqual(value["event_id"], expected_event)
            for reference in value["evidence"]:
                raw = history.source_files[reference["path"]]
                self.assertEqual(reference["sha256"], sha256_bytes(raw))
                self.assertEqual(reference["size_bytes"], len(raw))

    def test_missing_root_is_read_only(self) -> None:
        missing = self.base / "missing/missions/mission-absent"
        with self.assertRaises(HistoryVerificationError):
            load_verified_history(missing)
        self.assertFalse((self.base / "missing").exists())

    def test_missing_and_tampered_evidence_are_rejected(self) -> None:
        self.commit_outcome("HELD")
        path = self.root / "fixture/governor_decision.json"
        original = path.read_bytes()
        path.write_bytes(original + b" ")
        with self.assertRaisesRegex(HistoryVerificationError, "hash mismatch"):
            load_verified_history(self.root)
        path.unlink()
        with self.assertRaisesRegex(HistoryVerificationError, "missing"):
            load_verified_history(self.root)

    def test_tampered_request_head_and_stray_revision_are_rejected(self) -> None:
        request_path = self.root / "request/mission_request.json"
        original = request_path.read_bytes()
        request_path.write_bytes(original + b" ")
        with self.assertRaisesRegex(HistoryVerificationError, "hash mismatch"):
            load_verified_history(self.root)
        request_path.write_bytes(original)
        current_path = self.root / "mission_snapshot.json"
        head = current_path.read_bytes()
        current_path.write_bytes(head + b" ")
        with self.assertRaisesRegex(HistoryVerificationError, "latest revision"):
            load_verified_history(self.root)
        current_path.write_bytes(head)
        (self.root / "snapshots/mission_snapshot-r0002.json").write_bytes(head)
        with self.assertRaisesRegex(HistoryVerificationError, "stray"):
            load_verified_history(self.root)

    def test_chain_and_every_revision_correlation_are_verified(self) -> None:
        self.commit_outcome("HELD")
        first_path = self.root / "snapshots/mission_snapshot-r0001.json"
        raw = json.loads(first_path.read_bytes())
        raw["request_id"] = "request-other"
        first_path.write_bytes(canonical_json_bytes(raw))
        with self.assertRaisesRegex(HistoryVerificationError, "correlation"):
            load_verified_history(self.root)
        raw["request_id"] = self.request.request_id
        first_path.write_bytes(canonical_json_bytes(raw) + b" ")
        with self.assertRaisesRegex(HistoryVerificationError, "hash chain"):
            load_verified_history(self.root)

    def test_symlinked_ancestors_and_hardlinks_are_rejected(self) -> None:
        linked = self.base / "linked-source"
        linked.symlink_to(self.base / "source", target_is_directory=True)
        with self.assertRaisesRegex(HistoryVerificationError, "ancestor"):
            load_verified_history(linked / "missions" / self.request.mission_id)
        request_path = self.root / "request/mission_request.json"
        os.link(request_path, self.base / "request-hardlink.json")
        with self.assertRaisesRegex(HistoryVerificationError, "unlinked regular file"):
            load_verified_history(self.root)

    def test_concurrent_source_change_is_rejected(self) -> None:
        from blackpod_build_week import decision_journal_projection as module
        original_capture = module._capture_file
        count = 0

        def mutate_after_first_capture(path):
            nonlocal count
            captured = original_capture(path)
            count += 1
            if count == 3:
                head = self.root / "mission_snapshot.json"
                head.write_bytes(head.read_bytes() + b" ")
            return captured

        with patch.object(module, "_capture_file", mutate_after_first_capture):
            with self.assertRaisesRegex(HistoryVerificationError, "changed during verification"):
                load_verified_history(self.root)

    def test_bounded_source_reads_reject_oversize_files(self) -> None:
        with patch("blackpod_build_week.decision_journal_projection.MAX_SOURCE_FILE_BYTES", 1):
            with self.assertRaisesRegex(HistoryVerificationError, "size limit"):
                load_verified_history(self.root)

    def test_claimed_revision_count_is_bounded_by_existing_history(self) -> None:
        head = self.root / "mission_snapshot.json"
        value = json.loads(head.read_bytes())
        value.update({"revision": 1000000000, "snapshot_id": f"{self.request.mission_id}-r1000000000",
                      "previous_snapshot_sha256": "0" * 64})
        head.write_bytes(canonical_json_bytes(value))
        with self.assertRaisesRegex(HistoryVerificationError, "stray"):
            load_verified_history(self.root)

    def test_native_shadow_and_operator_inconsistencies_are_rejected(self) -> None:
        self.commit_outcome("SHADOW")
        history = load_verified_history(self.root)
        # These altered bytes are rejected even for a manually constructed
        # capture; the pure projector cannot bless unverified artifact bytes.
        from dataclasses import replace
        files = dict(history.source_files)
        plan = json.loads(files["fixture/navigator_shadow_plan.json"])
        plan["validated_constraints"]["allowed_operations"].append("SUBMIT_ORDER")
        files["fixture/navigator_shadow_plan.json"] = canonical_json_bytes(plan)
        with self.assertRaisesRegex(HistoryVerificationError, "captured artifact hash mismatch"):
            project_history(replace(history, source_files=files))
        files = dict(history.source_files)
        action = json.loads(files["fixture/operator_action.json"])
        action["source_run_id"] = "mission-other"
        files["fixture/operator_action.json"] = canonical_json_bytes(action)
        with self.assertRaisesRegex(HistoryVerificationError, "captured artifact hash mismatch"):
            project_history(replace(history, source_files=files))

    def rewrite_latest_native_artifact(self, name: str, transform) -> None:
        """Build a hash-consistent but semantically invalid synthetic history."""
        current = json.loads((self.root / "mission_snapshot.json").read_bytes())
        reference = next(a for a in current["artifacts"] if a["name"] == name)
        path = self.root / reference["path"]
        native = json.loads(path.read_bytes())
        transform(native)
        raw = canonical_json_bytes(native)
        path.write_bytes(raw)
        reference["sha256"] = sha256_bytes(raw)
        reference["byte_size"] = len(raw)
        snapshot = canonical_json_bytes(current)
        (self.root / "mission_snapshot.json").write_bytes(snapshot)
        (self.root / f"snapshots/mission_snapshot-r{current['revision']:04d}.json").write_bytes(snapshot)

    def test_hash_consistent_shadow_semantic_tampering_is_rejected(self) -> None:
        self.commit_outcome("SHADOW")
        self.rewrite_latest_native_artifact(
            "navigator_shadow_plan", lambda p: p["validated_constraints"]["allowed_operations"].append("SUBMIT_ORDER"),
        )
        history = load_verified_history(self.root)
        with self.assertRaisesRegex(HistoryVerificationError, "SHADOW constraints"):
            project_history(history)

    def test_hash_consistent_shadow_lineage_types_fail_cleanly(self) -> None:
        self.commit_outcome("SHADOW")
        for value in ([], {}, 7, None):
            with self.subTest(reference=value):
                self.rewrite_latest_native_artifact(
                    "navigator_shadow_plan",
                    lambda p: p["source_artifact_refs"].update({"operator_action": value}),
                )
                with self.assertRaisesRegex(HistoryVerificationError, "source lineage"):
                    project_history(load_verified_history(self.root))
        self.rewrite_latest_native_artifact(
            "navigator_shadow_plan",
            lambda p: p["source_artifact_refs"].update({"operator_action": "fixture/operator_action.json"}),
        )
        for value in ([], {}, 7, None):
            with self.subTest(digest=value):
                self.rewrite_latest_native_artifact(
                    "navigator_shadow_plan",
                    lambda p: p["source_artifact_hashes"].update({"operator_action": value}),
                )
                with self.assertRaisesRegex(HistoryVerificationError, "source lineage"):
                    project_history(load_verified_history(self.root))

    def test_hash_consistent_operator_and_governor_tampering_is_rejected(self) -> None:
        self.commit_outcome("VETOED")
        self.rewrite_latest_native_artifact("operator_action", lambda a: a.update({"source_run_id": "mission-other"}))
        with self.assertRaisesRegex(HistoryVerificationError, "operator action"):
            project_history(load_verified_history(self.root))
        self.rewrite_latest_native_artifact("governor_decision", lambda d: d.update({"decision_state": "HOLD"}))
        with self.assertRaisesRegex(HistoryVerificationError, "Governor disposition"):
            project_history(load_verified_history(self.root))


if __name__ == "__main__":
    unittest.main()
