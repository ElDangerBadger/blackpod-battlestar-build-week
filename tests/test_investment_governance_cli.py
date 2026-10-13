"""Governance CLI is offline, immutable, explicit, and operationally inert."""
from __future__ import annotations

import contextlib
import copy
import io
import json
import socket
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from test_investment_governance_engine import GovernanceFixture
from blackpod_build_week.contracts.decision_journal import CapitalPolicyProposal
from blackpod_build_week.contracts.investment_governance import ProposalInput
from blackpod_build_week.contracts.investment_review import ChallengeInput
from blackpod_build_week.decision_journal_cli import main, build_policy_event, build_parser
from blackpod_build_week.decision_journal_store import JournalStore
from blackpod_build_week.hashing import canonical_json_bytes, sha256_bytes
from blackpod_build_week.investment_review import build_challenge_event, evidence_for_challenge

CHECKOUT = Path(__file__).resolve().parents[1]


def state(root):
    return {str(path.relative_to(root)): (path.read_bytes(), path.stat().st_mtime_ns)
            for path in root.rglob("*") if path.is_file()}


class InvestmentGovernanceCliTests(unittest.TestCase):
    maxDiff = None
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.base = Path(temp.name).resolve()
        self.journal = self.base / "journal"
        self.fixture = GovernanceFixture()
        self.addCleanup(self.fixture.close)
        self.enterContext(mock.patch.object(socket.socket, "connect", side_effect=AssertionError("network forbidden")))
        self.enterContext(mock.patch("socket.create_connection", side_effect=AssertionError("network forbidden")))
        self.enterContext(mock.patch("subprocess.run", side_effect=AssertionError("subprocess forbidden")))
        self.enterContext(mock.patch("subprocess.Popen", side_effect=AssertionError("subprocess forbidden")))
        self.proposal_path = self.base / "proposal.json"
        self.approval_path = self.base / "approval.json"
        self.control_path = self.base / "control.json"
        self.proposal_value = copy.deepcopy(self.fixture.value)
        self.proposal_path.write_bytes(canonical_json_bytes(self.proposal_value))
        self.seed()

    def seed(self):
        store = JournalStore(self.journal)
        for event in self.fixture.events:
            store.append(event, {reference["path"]: self.fixture.blobs[reference["sha256"]]
                                 for reference in event.evidence})

    def invoke(self, command, *extra, journal=None):
        args = [command, "--journal-root", str(self.journal if journal is None else journal)]
        if command in {"assess-investment-proposal", "record-investment-proposal"}:
            args += ["--proposal", str(self.proposal_path)]
        elif command in {"validate-investment-approval", "record-investment-approval"}:
            args += ["--approval", str(self.approval_path)]
        elif command == "set-auto-trading":
            args += ["--control", str(self.control_path)]
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                code = main([*args, *map(str, extra)])
            except SystemExit as exc:
                code = exc.code
        return code, out.getvalue(), err.getvalue()

    def ok(self, command, *extra, journal=None):
        code, out, err = self.invoke(command, *extra, journal=journal)
        self.assertEqual((code, err), (0, ""), err)
        return json.loads(out)

    def ready(self, *, origin="SIMULATED_TEST"):
        self.ok("record-investment-proposal")
        event = JournalStore(self.journal).events()[-1]
        report = event.payload["report"]
        self.approval_value = {
            "schema_version": "blackpod.investment_shadow_approval.v1", "approval_id": "cli-approval",
            "proposal_event_id": event.event_id, "proposal_id": self.proposal_value["proposal_id"],
            "proposal_sha256": event.source["source_sha256"], "risk_policy_sha256": report["risk_policy_sha256"],
            "risk_context_sha256": report["risk_context_sha256"], "report_sha256": sha256_bytes(canonical_json_bytes(report)),
            "recorded_at": "2026-10-13T00:01:00Z", "approver_id": "declared-approver",
            "approver_role": "INVESTMENT_REVIEWER", "action": "APPROVE", "origin": origin,
            "scope": "INVESTMENT_SHADOW_RESEARCH_ONLY", "acknowledged_residual_risks": report["residual_risks"],
            "expires_at": "2026-10-13T00:30:00Z", "revokes_approval_event_id": None,
            "confirmation": {"action": "APPROVE", "proposal_sha256": event.source["source_sha256"], "acknowledges_shadow_only": True},
            "domain": "INVESTMENT", "mode": "SHADOW", "authority": self.proposal_value["authority"]}
        self.save_approval()
        return event

    def save_approval(self):
        self.approval_path.write_bytes(canonical_json_bytes(self.approval_value))

    def confirmations(self):
        return ("--confirm-action", self.approval_value["action"], "--confirm-proposal-sha256",
                self.approval_value["proposal_sha256"], "--acknowledge-shadow-only")

    def automation(self, *, identity="automation-on", enabled=True, timestamp="2026-10-14T00:00:00Z"):
        control = {"schema_version": "blackpod.trading_automation_control.v1", "control_id": identity,
                   "operator_id": "declared-operator", "recorded_at": timestamp, "switch_id": "auto-trading",
                   "requested_enabled": enabled, "scope": "TRADING_CONTROL_INTENT_ONLY", "domain": "TRADING",
                   "execution_mode": "DISABLED", "origin": "SIMULATED_TEST"}
        self.control_path.write_bytes(canonical_json_bytes(control))
        return control

    def test_assess_record_show_retry_never_rewrites_source_or_authority(self):
        source_before = state(self.fixture.review.base)
        before = state(self.journal)
        preview = self.ok("assess-investment-proposal")
        self.assertEqual(preview["report"]["gate"], "REVIEW_READY")
        self.assertEqual(before, state(self.journal))
        recorded = self.ok("record-investment-proposal")
        self.assertTrue(recorded["written"])
        after = state(self.journal)
        retry = self.ok("record-investment-proposal")
        self.assertFalse(retry["written"])
        self.assertEqual(after, state(self.journal))
        shown = self.ok("show-investment-proposal", "--proposal-id", self.proposal_value["proposal_id"])
        self.assertEqual(shown["proposal"], self.proposal_value)
        self.assertEqual(shown["approval_state"]["state"], "UNREVIEWED")
        self.assertFalse(shown["report"]["operational_authority_granted"])
        self.assertEqual(shown["lifecycle_time_basis"], "LATEST_JOURNAL_RECORDING")
        self.assertEqual(source_before, state(self.fixture.review.base))

    def test_validate_and_record_simulated_approval_exact_confirmation_and_no_execution(self):
        self.ready()
        before = state(self.journal)
        preview = self.ok("validate-investment-approval")
        self.assertEqual(preview["decision"]["result"], "SIMULATED_SHADOW_APPROVED")
        self.assertFalse(preview["decision"]["approver_identity_authenticated"])
        self.assertFalse(preview["decision"]["operational_authority_granted"])
        self.assertEqual(preview["decision"]["execution_status"], "NOT_EXECUTED")
        self.assertIsNone(preview["decision"]["realized_trade_pnl"])
        self.assertEqual(before, state(self.journal))
        recorded = self.ok("record-investment-approval", *self.confirmations())
        self.assertTrue(recorded["written"])
        for name, value in before.items():
            self.assertEqual(state(self.journal)[name], value)
        after = state(self.journal)
        self.assertFalse(self.ok("record-investment-approval", *self.confirmations())["written"])
        self.assertEqual(after, state(self.journal))
        shown = self.ok("show-investment-approval", "--approval-id", self.approval_value["approval_id"])
        self.assertEqual(shown["approval"], self.approval_value)
        self.assertEqual(shown["approval_state"]["state"], "SIMULATED_SHADOW_APPROVED")
        expired = self.ok("show-investment-proposal", "--proposal-id", self.proposal_value["proposal_id"], "--as-of", "2026-10-13T00:30:00Z")
        self.assertEqual(expired["approval_state"]["state"], "EXPIRED")
        self.assertEqual(expired["lifecycle_time_basis"], "EXPLICIT_AS_OF")

    def test_declared_human_origin_preserved_without_authentication_claim(self):
        self.ready(origin="HUMAN_DECLARED")
        recorded = self.ok("record-investment-approval", *self.confirmations())
        self.assertEqual(recorded["decision"]["result"], "SHADOW_RESEARCH_APPROVED")
        self.assertEqual(recorded["decision"]["origin"], "HUMAN_DECLARED")
        self.assertFalse(recorded["decision"]["approver_identity_authenticated"])

    def test_confirmation_flags_are_mandatory_and_exact(self):
        self.ready()
        before = state(self.journal)
        variations = [(), ("--confirm-action", "APPROVE"),
                      ("--confirm-action", "REJECT", "--confirm-proposal-sha256", self.approval_value["proposal_sha256"], "--acknowledge-shadow-only"),
                      ("--confirm-action", "APPROVE", "--confirm-proposal-sha256", "a" * 64, "--acknowledge-shadow-only"),
                      ("--confirm-action", "APPROVE", "--confirm-proposal-sha256", self.approval_value["proposal_sha256"])]
        for flags in variations:
            with self.subTest(flags=flags):
                self.assertEqual(self.invoke("record-investment-approval", *flags)[0], 2)
        self.assertEqual(before, state(self.journal))

    def test_changed_proposal_or_approval_identity_is_conflict(self):
        self.ready()
        self.ok("record-investment-approval", *self.confirmations())
        before = state(self.journal)
        self.proposal_value["rationale"] = "Changed immutable research rationale."
        self.proposal_path.write_bytes(canonical_json_bytes(self.proposal_value))
        for command in ("assess-investment-proposal", "record-investment-proposal"):
            self.assertEqual(self.invoke(command)[0], 2)
        self.approval_value["origin"] = "HUMAN_DECLARED"
        self.save_approval()
        for command, flags in (("validate-investment-approval", ()), ("record-investment-approval", self.confirmations())):
            self.assertEqual(self.invoke(command, *flags)[0], 2)
        self.assertEqual(before, state(self.journal))

    def test_retry_uses_original_prefix_after_new_known_dissent(self):
        self.ready()
        self.ok("record-investment-approval", *self.confirmations())
        events, blobs = JournalStore(self.journal).verified_contents()
        value = copy.deepcopy(self.fixture.review.challenge.payload["challenge"])
        value.update(challenge_id="later-dissent", recorded_at="2026-10-13T00:00:00Z",
                     evidence_cutoff_at="2026-10-13T00:00:00Z", disposition="REVIEW_CONTESTS")
        challenge = ChallengeInput.from_mapping(value)
        event = build_challenge_event(challenge, events, blobs)
        JournalStore(self.journal).append(event, evidence_for_challenge(challenge, events, blobs))
        before = state(self.journal)
        self.assertFalse(self.ok("record-investment-proposal")["written"])
        self.assertFalse(self.ok("record-investment-approval", *self.confirmations())["written"])
        self.assertEqual(before, state(self.journal))
        self.proposal_value["proposal_id"] = "new-after-dissent"
        self.proposal_path.write_bytes(canonical_json_bytes(self.proposal_value))
        self.assertEqual(self.ok("assess-investment-proposal")["report"]["gate"], "DEFER")

    def test_rejected_risk_proposal_can_be_recorded_but_not_approved(self):
        self.proposal_value["risk_policy"]["limits"]["max_position_weight"] = 0.01
        self.proposal_path.write_bytes(canonical_json_bytes(self.proposal_value))
        self.ready()
        before = state(self.journal)
        self.assertEqual(self.ok("show-investment-proposal", "--proposal-id", self.proposal_value["proposal_id"])["report"]["gate"], "REJECT")
        self.assertEqual(self.invoke("record-investment-approval", *self.confirmations())[0], 2)
        self.assertEqual(before, state(self.journal))

    def test_rejection_deferral_and_revocation_use_same_explicit_review_boundary(self):
        for action in ("REJECT", "DEFER"):
            journal = self.base / action.lower()
            store = JournalStore(journal)
            events, blobs = JournalStore(self.journal).verified_contents()
            for event in events:
                store.append(event, {ref["path"]: blobs[ref["sha256"]] for ref in event.evidence})
            self.ready()
            self.approval_value.update(action=action, expires_at=None)
            self.approval_value["confirmation"]["action"] = action
            self.save_approval()
            self.ok("record-investment-proposal", journal=journal)
            recorded = self.ok("record-investment-approval", *self.confirmations(), journal=journal)
            self.assertEqual(recorded["decision"]["result"], "REJECTED" if action == "REJECT" else "DEFERRED")
        # Main journal still has only the unreviewed proposal.
        self.ready()
        recorded = self.ok("record-investment-approval", *self.confirmations())
        self.approval_value.update(approval_id="cli-revocation", action="REVOKE", recorded_at="2026-10-13T00:02:00Z",
                                   expires_at=None, revokes_approval_event_id=recorded["event_id"])
        self.approval_value["confirmation"]["action"] = "REVOKE"
        self.save_approval()
        result = self.ok("record-investment-approval", *self.confirmations())
        self.assertEqual(result["decision"]["result"], "REVOKED")
        state_result = self.ok("show-investment-proposal", "--proposal-id", self.proposal_value["proposal_id"])
        self.assertEqual(state_result["approval_state"]["state"], "REVOKED")

    def test_extra_live_fields_or_authority_flags_rejected_without_writes(self):
        baseline = copy.deepcopy(self.proposal_value)
        before = state(self.journal)
        for field, value in (("order", {}), ("realized_trade_pnl", 0), ("capital_transfers_enabled", True)):
            changed = {**baseline, field: value}
            self.proposal_path.write_bytes(canonical_json_bytes(changed))
            self.assertEqual(self.invoke("record-investment-proposal")[0], 2)
        changed = copy.deepcopy(baseline)
        changed["authority"]["execution_enabled"] = True
        self.proposal_path.write_bytes(canonical_json_bytes(changed))
        self.assertEqual(self.invoke("record-investment-proposal")[0], 2)
        self.assertEqual(before, state(self.journal))

    def test_malformed_duplicate_deep_json_and_symlink_inputs_fail_cleanly(self):
        before = state(self.journal)
        for raw in (b'{"proposal_id":"a","proposal_id":"b"}', b'{"value":' + b'[' * 2000 + b'0' + b']' * 2000 + b'}'):
            self.proposal_path.write_bytes(raw)
            self.assertEqual(self.invoke("record-investment-proposal")[0], 2)
        self.proposal_path.write_bytes(canonical_json_bytes(self.proposal_value))
        target = self.base / "target.json"
        self.proposal_path.rename(target)
        self.proposal_path.symlink_to(target)
        self.assertEqual(self.invoke("record-investment-proposal")[0], 2)
        self.assertEqual(before, state(self.journal))

    def test_governance_commands_never_create_missing_or_source_journal(self):
        self.ready()
        missing = self.base / "missing"
        source = self.fixture.review.base / "initial/missions/mission-review-initial"
        before = state(source)
        commands = [("assess-investment-proposal", ()), ("record-investment-proposal", ()),
                    ("validate-investment-approval", ()), ("record-investment-approval", self.confirmations()),
                    ("show-investment-proposal", ("--proposal-id", "missing")),
                    ("show-investment-approval", ("--approval-id", "missing"))]
        for command, flags in commands:
            for root in (missing, source):
                with self.subTest(command=command, root=root):
                    self.assertEqual(self.invoke(command, *flags, journal=root)[0], 2)
        self.assertFalse(missing.exists())
        self.assertEqual(before, state(source))

    def test_default_switch_off_does_not_create_journal_and_on_is_blocked(self):
        missing = self.base / "automation-journal"
        status = self.ok("auto-trading-status", journal=missing)
        self.assertEqual(status["state"], "OFF")
        self.assertFalse(status["effective_enabled"])
        self.assertFalse(missing.exists())
        self.automation()
        result = self.ok("set-auto-trading", journal=missing)
        self.assertEqual(result["status"]["state"], "BLOCKED")
        self.assertTrue(result["status"]["requested_enabled"])
        self.assertFalse(result["status"]["effective_enabled"])
        self.assertFalse(result["status"]["broker_calls_permitted"])
        self.assertFalse(result["status"]["investment_approval_applies"])
        self.assertEqual(self.ok("auto-trading-status", journal=missing)["state"], "BLOCKED")
        self.assertEqual(self.ok("verify", journal=missing)["event_count"], 1)

    def test_switch_toggle_and_retry_do_not_regress_current_state(self):
        self.automation()
        self.assertTrue(self.ok("set-auto-trading")["written"])
        self.assertFalse(self.ok("set-auto-trading")["written"])
        self.automation(identity="automation-off", enabled=False, timestamp="2026-10-14T00:01:00Z")
        self.ok("set-auto-trading")
        self.assertEqual(self.ok("auto-trading-status")["state"], "OFF")
        self.automation()
        retry = self.ok("set-auto-trading")
        self.assertFalse(retry["written"])
        self.assertEqual(retry["status"]["state"], "BLOCKED")
        self.assertEqual(retry["current_status"]["state"], "OFF")
        self.assertEqual(self.ok("auto-trading-status")["state"], "OFF")
        before = state(self.journal)
        control = self.automation()
        control["requested_enabled"] = False
        self.control_path.write_bytes(canonical_json_bytes(control))
        self.assertEqual(self.invoke("set-auto-trading")[0], 2)
        self.assertEqual(before, state(self.journal))

    def test_switch_rejects_execution_modes_and_preserves_capital_proposal(self):
        policy = CapitalPolicyProposal.from_bytes((CHECKOUT / "examples/capital_policy.proposed.v1.json").read_bytes())
        event = build_policy_event(policy)
        JournalStore(self.journal).append(event, {ref["path"]: policy.to_bytes() for ref in event.evidence})
        before = state(self.journal)
        control = self.automation()
        for field, value in (("execution_mode", "LIVE"), ("broker_calls_permitted", True), ("scope", "TRADING_EXECUTION"), ("domain", "INVESTMENT")):
            changed = {**control, field: value}
            self.control_path.write_bytes(canonical_json_bytes(changed))
            self.assertEqual(self.invoke("set-auto-trading")[0], 2)
        self.assertEqual(before, state(self.journal))
        self.automation()
        self.ok("set-auto-trading")
        recorded = next(item for item in JournalStore(self.journal).events() if item.event_type == "CAPITAL_POLICY_PROPOSED")
        self.assertEqual(recorded.to_bytes(), event.to_bytes())
        self.assertFalse(recorded.payload["activation_enabled"])

    def test_show_unknown_invalid_time_and_corrupt_journal_fail(self):
        self.ready()
        for command, flags in (("show-investment-proposal", ("--proposal-id", "unknown")),
                               ("show-investment-approval", ("--approval-id", "unknown")),
                               ("show-investment-proposal", ("--proposal-id", self.proposal_value["proposal_id"], "--as-of", "invalid")),
                               ("show-investment-proposal", ("--proposal-id", self.proposal_value["proposal_id"], "--as-of", "2026-10-11T00:00:00Z"))):
            self.assertEqual(self.invoke(command, *flags)[0], 2)
        blob = self.journal / "evidence" / sha256_bytes(self.proposal_path.read_bytes())
        blob.chmod(0o600)
        blob.write_bytes(b"corrupt")
        for command in ("auto-trading-status", "assess-investment-proposal", "verify"):
            self.assertEqual(self.invoke(command)[0], 2)

    def test_help_keeps_all_legacy_commands_and_new_scope_visible(self):
        text = build_parser().format_help()
        for command in ("export-mission", "verify", "append-evaluation", "propose-capital-policy",
                        "validate-hypothesis", "record-hypothesis", "show-hypothesis", "validate-challenge", "record-challenge",
                        "evaluate-hypothesis", "record-hypothesis-evaluation", "show-challenge", "show-hypothesis-evaluation",
                        "assess-investment-proposal", "record-investment-proposal", "show-investment-proposal",
                        "validate-investment-approval", "record-investment-approval", "show-investment-approval",
                        "set-auto-trading", "auto-trading-status"):
            self.assertIn(command, text)

    def test_committed_governance_sources_and_examples_are_runnable(self):
        journal = self.base / "example-journal"
        fixture = CHECKOUT / "fixtures/investment_governance"
        for name in ("initial", "statistical"):
            self.ok("export-mission", "--mission-root", fixture / f"sources/{name}/missions/mission-review-{name}", journal=journal)
        self.ok("record-hypothesis", "--hypothesis", fixture / "hypothesis.shadow.v1.json", journal=journal)
        self.ok("record-challenge", "--challenge", fixture / "challenge.shadow.v1.json", journal=journal)
        self.ok("record-investment-proposal", "--proposal", CHECKOUT / "examples/investment_proposal.shadow.v1.json", journal=journal)
        path = CHECKOUT / "examples/investment_approval.simulated.v1.json"
        approval = json.loads(path.read_bytes())
        self.ok("record-investment-approval", "--approval", path, "--confirm-action", approval["action"],
                "--confirm-proposal-sha256", approval["proposal_sha256"], "--acknowledge-shadow-only", journal=journal)
        result = self.ok("verify", journal=journal)
        self.assertEqual(result["event_count"], 8)
        self.assertEqual(result["orphan_evidence_count"], 0)


if __name__ == "__main__":
    unittest.main()
