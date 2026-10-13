"""Offline strictness, immutable byte, and version-isolation tests."""

from __future__ import annotations

import copy
import unittest
from dataclasses import FrozenInstanceError

from blackpod_build_week.contracts.decision_journal import (
    JournalEvent, JOURNAL_EVENT_V4_SCHEMA_VERSION, INVESTMENT_DECISION_PROPOSAL_EVENT_TYPE,
    INVESTMENT_SHADOW_APPROVAL_EVENT_TYPE,
)
from blackpod_build_week.contracts.investment_governance import (
    ShadowRiskPolicy, RiskContextInput, ProposalInput, ApprovalInput,
    SHADOW_RISK_POLICY_SCHEMA_VERSION, RISK_CONTEXT_SCHEMA_VERSION,
    PROPOSAL_SCHEMA_VERSION, APPROVAL_SCHEMA_VERSION, RISK_METHOD_VERSION,
    SHADOW_APPROVAL_SCOPE, validate_proposal_report, validate_approval_decision,
)
from blackpod_build_week.contracts.mission_request import ContractValidationError
from blackpod_build_week.hashing import canonical_json_bytes, sha256_bytes


def authority():
    return {"authorization_enabled": False, "capital_activation_enabled": False,
            "execution_enabled": False, "policy_changes_enabled": False}


def policy_mapping():
    return {
        "schema_version": SHADOW_RISK_POLICY_SCHEMA_VERSION, "policy_id": "shadow-policy-001", "policy_version": 1,
        "recorded_at": "2026-10-11T00:00:00Z", "status": "SHADOW_PROPOSED", "domain": "INVESTMENT", "mode": "SHADOW",
        "method_version": RISK_METHOD_VERSION, "max_context_age_seconds": 3600, "max_approval_lifetime_seconds": 86400,
        "required_approver_role": "investment-research-reviewer", "authorized_approver_ids": ["human-001"],
        "require_final_evaluation": False, "require_role_coverage": True, "require_distinct_role_artifacts": True,
        "require_no_active_dissent": True,
        "limits": {"max_position_weight": .2, "max_sector_weight": .4, "max_consolidated_gross": .9,
                   "max_investment_gross": .5, "min_cash_weight": .1, "min_liquidity_score": .6,
                   "max_stress_loss_weight": .2, "max_correlated_pair_weight": .3, "high_correlation_threshold": .8},
        "authority": authority(),
    }


def context_mapping():
    return {
        "schema_version": RISK_CONTEXT_SCHEMA_VERSION, "context_id": "context-001", "as_of": "2026-10-11T00:00:00Z",
        "source_kind": "SYNTHETIC_FIXTURE", "portfolio_scope_id": "synthetic-account-001", "basis": "ACCOUNT_EQUITY_FRACTIONS",
        "scope_mode": "LONG_ONLY", "is_complete": True,
        "positions": [{"symbol": "SPY", "desk": "TRADING", "weight": .2}, {"symbol": "ABC", "desk": "INVESTMENT", "weight": .1}],
        "cash_by_desk": {"TRADING": .3, "INVESTMENT": .4},
        "instruments": [{"symbol": "SPY", "sector": "Market", "liquidity_score": .9, "stress_loss_fraction": .2},
                        {"symbol": "ABC", "sector": "Technology", "liquidity_score": .8, "stress_loss_fraction": .3}],
        "correlations": [{"symbol_a": "SPY", "symbol_b": "ABC", "correlation": .5}],
    }


def proposal_mapping():
    return {
        "schema_version": PROPOSAL_SCHEMA_VERSION, "proposal_id": "proposal-001", "recorded_at": "2026-10-11T00:00:00Z",
        "evidence_cutoff_at": "2026-10-11T00:00:00Z", "submitted_by": "researcher-001",
        "hypothesis_event_id": "journal-event-" + "a" * 64, "hypothesis_id": "hypothesis-001", "hypothesis_sha256": "b" * 64,
        "challenge_event_id": "journal-event-" + "c" * 64, "evaluation_event_id": None,
        "rationale": "Review this synthetic full investment book in shadow mode.", "targets": [{"symbol": "ABC", "weight": .2}],
        "risk_policy": policy_mapping(), "risk_context": context_mapping(), "valid_until": "2026-10-12T00:00:00Z",
        "supersedes_event_id": None, "domain": "INVESTMENT", "mode": "SHADOW", "authority": authority(),
    }


def report_mapping(proposal=None):
    proposal = proposal or ProposalInput.from_mapping(proposal_mapping())
    return {
        "risk_method_version": RISK_METHOD_VERSION, "gate": "REVIEW_READY",
        "checks": [{"check_id": "synthetic-check", "status": "PASS", "observed": .2, "limit": .2, "reason_code": "WITHIN_LIMIT"}],
        "metrics": {"investment_budget_weight": .5, "proposed_investment_gross": .2, "projected_consolidated_gross": .4,
                    "projected_cash_weight": .6, "projected_stress_loss_weight": .1,
                    "projected_symbol_weights": [{"symbol": "ABC", "weight": .2}, {"symbol": "SPY", "weight": .2}],
                    "projected_sector_weights": [{"sector": "Technology", "weight": .2}, {"sector": "Market", "weight": .2}]},
        "risk_policy_sha256": sha256_bytes(ShadowRiskPolicy.from_mapping(proposal.risk_policy).to_bytes()),
        "risk_context_sha256": sha256_bytes(RiskContextInput.from_mapping(proposal.risk_context).to_bytes()),
        "residual_risks": ["DECLARED_IDENTITIES_NOT_AUTHENTICATED"], "proposal_ready_for_human_review": True,
        "approval_scope": SHADOW_APPROVAL_SCOPE, "economic_truth_evaluated": False,
        "operational_authority_granted": False, "authority": authority(),
    }


def approval_mapping(action="APPROVE", origin="SIMULATED_TEST"):
    proposal = ProposalInput.from_mapping(proposal_mapping())
    report = report_mapping(proposal)
    return {
        "schema_version": APPROVAL_SCHEMA_VERSION, "approval_id": "approval-001", "proposal_event_id": "journal-event-" + "d" * 64,
        "proposal_id": proposal.proposal_id, "proposal_sha256": sha256_bytes(proposal.to_bytes()),
        "risk_policy_sha256": report["risk_policy_sha256"], "risk_context_sha256": report["risk_context_sha256"],
        "report_sha256": sha256_bytes(canonical_json_bytes(report)), "recorded_at": "2026-10-11T01:00:00Z",
        "approver_id": "human-001", "approver_role": "investment-research-reviewer", "action": action, "origin": origin,
        "scope": SHADOW_APPROVAL_SCOPE, "acknowledged_residual_risks": report["residual_risks"] if action == "APPROVE" else [],
        "expires_at": "2026-10-11T02:00:00Z" if action == "APPROVE" else None,
        "revokes_approval_event_id": "journal-event-" + "e" * 64 if action == "REVOKE" else None,
        "confirmation": {"action": action, "proposal_sha256": sha256_bytes(proposal.to_bytes()), "acknowledges_shadow_only": True},
        "domain": "INVESTMENT", "mode": "SHADOW", "authority": authority(),
    }


def decision_mapping(approval=None):
    approval = approval or ApprovalInput.from_mapping(approval_mapping())
    result = {"REJECT": "REJECTED", "DEFER": "DEFERRED", "REVOKE": "REVOKED"}.get(approval.action)
    if approval.action == "APPROVE":
        result = "SIMULATED_SHADOW_APPROVED" if approval.origin == "SIMULATED_TEST" else "SHADOW_RESEARCH_APPROVED"
    return {"action": approval.action, "result": result, "origin": approval.origin, "scope": approval.scope,
            "expires_at": approval.expires_at, "approver_identity_authenticated": False, "operational_authority_granted": False,
            "execution_status": "NOT_EXECUTED", "realized_trade_pnl": None, "authority": authority()}


def governance_event(kind="proposal"):
    is_proposal = kind == "proposal"
    document = ProposalInput.from_mapping(proposal_mapping()) if is_proposal else ApprovalInput.from_mapping(approval_mapping())
    identity = "proposal_id" if is_proposal else "approval_id"
    return {
        "schema_version": JOURNAL_EVENT_V4_SCHEMA_VERSION, "event_id": "journal-event-" + "f" * 64,
        "decision_id": "journal-decision-" + "1" * 64, "domain": "INVESTMENT",
        "event_type": INVESTMENT_DECISION_PROPOSAL_EVENT_TYPE if is_proposal else INVESTMENT_SHADOW_APPROVAL_EVENT_TYPE,
        "recorded_at": document.recorded_at, "source": {"kind": "INVESTMENT_DECISION_PROPOSAL" if is_proposal else "INVESTMENT_SHADOW_APPROVAL",
                                                            identity: getattr(document, identity), "source_sha256": sha256_bytes(document.to_bytes())},
        "evidence": [], "payload": {kind: document.to_dict(), "report" if is_proposal else "decision": report_mapping(document) if is_proposal else decision_mapping(document)},
    }


class InvestmentGovernanceContractTests(unittest.TestCase):
    def test_immutable_canonical_round_trip(self):
        for contract, factory in ((ShadowRiskPolicy, policy_mapping), (RiskContextInput, context_mapping),
                                  (ProposalInput, proposal_mapping), (ApprovalInput, approval_mapping)):
            with self.subTest(contract=contract.__name__):
                supplied = factory()
                document = contract.from_mapping(supplied)
                before = document.to_bytes()
                supplied.clear()
                document.to_dict().clear()
                self.assertEqual(before, document.to_bytes())
                self.assertEqual(document, contract.from_bytes(before))
                self.assertEqual(before, canonical_json_bytes(document.to_dict()))
                with self.assertRaises((FrozenInstanceError, AttributeError, TypeError)):
                    document._canonical_bytes = b"mutated"

    def test_missing_unknown_and_nested_fields_reject(self):
        cases = ((ShadowRiskPolicy, policy_mapping, [(), ("limits",), ("authority",)]),
                 (RiskContextInput, context_mapping, [(), ("positions", 0), ("cash_by_desk",), ("instruments", 0), ("correlations", 0)]),
                 (ProposalInput, proposal_mapping, [(), ("targets", 0), ("risk_policy",), ("risk_context",), ("authority",)]),
                 (ApprovalInput, approval_mapping, [(), ("confirmation",), ("authority",)]))
        for contract, factory, paths in cases:
            for path in paths:
                for mutation in ("unknown", "missing"):
                    value = factory()
                    target = value
                    for part in path:
                        target = target[part]
                    if mutation == "unknown":
                        target["unexpected"] = True
                    else:
                        del target[next(iter(target))]
                    with self.subTest(contract=contract.__name__, path=path, mutation=mutation), self.assertRaises(ContractValidationError):
                        contract.from_mapping(value)

    def test_policy_constants_flags_and_domains(self):
        for field, value in (("status", "ACTIVE"), ("domain", "TRADING"), ("mode", "LIVE"), ("method_version", "other"),
                             ("schema_version", "other"), ("require_role_coverage", False), ("require_distinct_role_artifacts", False),
                             ("require_no_active_dissent", False), ("require_final_evaluation", 1)):
            item = policy_mapping(); item[field] = value
            with self.subTest(field=field), self.assertRaises(ContractValidationError):
                ShadowRiskPolicy.from_mapping(item)

    def test_policy_positive_integer_fields(self):
        for field in ("policy_version", "max_context_age_seconds", "max_approval_lifetime_seconds"):
            for value in (0, -1, True, 1.5, "1", None):
                item = policy_mapping(); item[field] = value
                with self.subTest(field=field, value=value), self.assertRaises(ContractValidationError):
                    ShadowRiskPolicy.from_mapping(item)

    def test_policy_limit_bounds(self):
        for field in policy_mapping()["limits"]:
            for value in (-.01, 1.01, True, float("nan"), float("inf"), "0.2", None):
                item = policy_mapping(); item["limits"][field] = value
                with self.subTest(field=field, value=value), self.assertRaises(ContractValidationError):
                    ShadowRiskPolicy.from_mapping(item)
        item = policy_mapping(); item["limits"]["high_correlation_threshold"] = 0
        with self.assertRaises(ContractValidationError):
            ShadowRiskPolicy.from_mapping(item)

    def test_policy_approver_id_list(self):
        for values in ([], ["human-001", "human-001"], ["../escape"], [True], "human-001"):
            item = policy_mapping(); item["authorized_approver_ids"] = values
            with self.assertRaises(ContractValidationError):
                ShadowRiskPolicy.from_mapping(item)

    def test_authority_always_disabled(self):
        for contract, factory in ((ShadowRiskPolicy, policy_mapping), (ProposalInput, proposal_mapping), (ApprovalInput, approval_mapping)):
            for field in authority():
                for value in (True, 0, None):
                    item = factory(); item["authority"][field] = value
                    with self.subTest(contract=contract.__name__, field=field, value=value), self.assertRaises(ContractValidationError):
                        contract.from_mapping(item)

    def test_context_account_total_is_preserved_not_normalized(self):
        value = context_mapping(); value["cash_by_desk"]["INVESTMENT"] = .4000000000005
        actual = RiskContextInput.from_mapping(value)
        self.assertEqual(actual.cash_by_desk["INVESTMENT"], value["cash_by_desk"]["INVESTMENT"])
        for weight in (.400000000002, .399999999998, .5, .3):
            value = context_mapping(); value["cash_by_desk"]["INVESTMENT"] = weight
            with self.assertRaises(ContractValidationError):
                RiskContextInput.from_mapping(value)

    def test_context_cash_only_and_missing_metadata_allowed(self):
        value = context_mapping(); value["positions"] = []; value["cash_by_desk"] = {"TRADING": .5, "INVESTMENT": .5}
        value["instruments"] = []; value["correlations"] = []; value["is_complete"] = False
        self.assertEqual(RiskContextInput.from_mapping(value).positions, [])
        value = context_mapping()
        value["instruments"][0]["liquidity_score"] = None
        value["instruments"][0]["stress_loss_fraction"] = None
        value["correlations"][0]["correlation"] = None
        self.assertIsNone(RiskContextInput.from_mapping(value).correlations[0]["correlation"])

    def test_context_no_shorts_leverage_or_boolean_numbers(self):
        for path in (("positions", 0, "weight"), ("cash_by_desk", "TRADING"),
                     ("instruments", 0, "liquidity_score"), ("instruments", 0, "stress_loss_fraction")):
            for number in (-.1, 1.1, True, float("nan"), float("inf")):
                value = context_mapping(); target = value
                for part in path[:-1]: target = target[part]
                target[path[-1]] = number
                with self.subTest(path=path, number=number), self.assertRaises(ContractValidationError):
                    RiskContextInput.from_mapping(value)

    def test_context_constants_and_completeness(self):
        for field, replacement in (("source_kind", "BROKER"), ("basis", "DESK_FRACTIONS"), ("scope_mode", "LEVERAGED"), ("is_complete", 1)):
            value = context_mapping(); value[field] = replacement
            with self.assertRaises(ContractValidationError): RiskContextInput.from_mapping(value)
        value = context_mapping(); value["positions"][0]["desk"] = "CAPITAL_ALLOCATION"
        with self.assertRaises(ContractValidationError): RiskContextInput.from_mapping(value)

    def test_context_duplicate_identity_guards(self):
        for field in ("positions", "instruments", "correlations"):
            value = context_mapping(); value[field].append(copy.deepcopy(value[field][0]))
            with self.subTest(field=field), self.assertRaises(ContractValidationError): RiskContextInput.from_mapping(value)
        value = context_mapping(); value["correlations"].append({"symbol_a": "ABC", "symbol_b": "SPY", "correlation": .4})
        with self.assertRaises(ContractValidationError): RiskContextInput.from_mapping(value)
        value = context_mapping(); value["positions"].append({"symbol": "SPY", "desk": "INVESTMENT", "weight": 0})
        self.assertEqual(len(RiskContextInput.from_mapping(value).positions), 3)

    def test_correlation_bounds_and_no_self_pair(self):
        for correlation in (-1, 0, 1, None):
            value = context_mapping(); value["correlations"][0]["correlation"] = correlation
            RiskContextInput.from_mapping(value)
        for correlation in (-1.1, 1.1, True, float("nan")):
            value = context_mapping(); value["correlations"][0]["correlation"] = correlation
            with self.assertRaises(ContractValidationError): RiskContextInput.from_mapping(value)
        value = context_mapping(); value["correlations"][0]["symbol_b"] = "SPY"
        with self.assertRaises(ContractValidationError): RiskContextInput.from_mapping(value)

    def test_proposal_symbol_targets_and_no_order_fields(self):
        for targets in ([], [{"symbol": "ABC", "weight": 0}]):
            value = proposal_mapping(); value["targets"] = targets
            self.assertEqual(ProposalInput.from_mapping(value).targets, targets)
        for targets in ([{"symbol": "ABC", "weight": .1}, {"symbol": "ABC", "weight": .2}],
                        [{"symbol": "abc", "weight": .1}], [{"symbol": "ABC", "weight": True}],
                        [{"symbol": "ABC", "weight": -.1}], [{"symbol": "ABC", "weight": 1.1}],
                        [{"symbol": "ABC", "weight": .1, "desk": "TRADING"}], [{"symbol": "ABC", "weight": .1, "order_type": "MARKET"}]):
            value = proposal_mapping(); value["targets"] = targets
            with self.assertRaises(ContractValidationError): ProposalInput.from_mapping(value)

    def test_proposal_timestamp_boundaries_and_normalization(self):
        value = proposal_mapping(); value["recorded_at"] = "2026-10-10T17:00:00-07:00"
        self.assertEqual(ProposalInput.from_mapping(value).recorded_at, "2026-10-11T00:00:00Z")
        for field, replacement in (("evidence_cutoff_at", "2026-10-11T00:00:01Z"), ("valid_until", "2026-10-11T00:00:00Z"),
                                   ("recorded_at", "2026-10-11")):
            value = proposal_mapping(); value[field] = replacement
            with self.assertRaises(ContractValidationError): ProposalInput.from_mapping(value)

    def test_link_ids_and_hashes_require_full_digests(self):
        for contract, factory, fields in ((ProposalInput, proposal_mapping, ("hypothesis_event_id", "challenge_event_id", "evaluation_event_id", "supersedes_event_id")),
                                         (ApprovalInput, approval_mapping, ("proposal_event_id",))):
            for field in fields:
                for replacement in ("journal-event-short", "journal-decision-" + "a" * 64, True):
                    value = factory(); value[field] = replacement
                    with self.assertRaises(ContractValidationError): contract.from_mapping(value)
        for replacement in ("a" * 63, "A" * 64, True, None):
            value = proposal_mapping(); value["hypothesis_sha256"] = replacement
            with self.assertRaises(ContractValidationError): ProposalInput.from_mapping(value)

    def test_approval_all_actions_and_origins(self):
        for action in ("APPROVE", "REJECT", "DEFER", "REVOKE"):
            for origin in ("HUMAN_DECLARED", "SIMULATED_TEST"):
                document = ApprovalInput.from_mapping(approval_mapping(action, origin))
                report = validate_approval_decision(decision_mapping(document), document)
                self.assertFalse(report["operational_authority_granted"])
                self.assertEqual(report["execution_status"], "NOT_EXECUTED")

    def test_approval_confirmation_binds_action_hash_and_scope(self):
        for field, replacement in (("action", "REJECT"), ("proposal_sha256", "e" * 64), ("acknowledges_shadow_only", False), ("acknowledges_shadow_only", 1)):
            value = approval_mapping(); value["confirmation"][field] = replacement
            with self.assertRaises(ContractValidationError): ApprovalInput.from_mapping(value)
        for field, replacement in (("scope", "NAVIGATOR_SHADOW_HANDOFF"), ("scope", "INVESTMENT_ALLOCATION"), ("origin", "AUTHENTICATED")):
            value = approval_mapping(); value[field] = replacement
            with self.assertRaises(ContractValidationError): ApprovalInput.from_mapping(value)

    def test_approval_expiry_revocation_and_acknowledgements(self):
        for replacement in (None, "2026-10-11T01:00:00Z", "2026-10-10T01:00:00Z"):
            value = approval_mapping(); value["expires_at"] = replacement
            with self.assertRaises(ContractValidationError): ApprovalInput.from_mapping(value)
        for action in ("REJECT", "DEFER", "REVOKE"):
            value = approval_mapping(action); value["expires_at"] = "2026-10-12T00:00:00Z"
            with self.assertRaises(ContractValidationError): ApprovalInput.from_mapping(value)
        value = approval_mapping("REVOKE"); value["revokes_approval_event_id"] = None
        with self.assertRaises(ContractValidationError): ApprovalInput.from_mapping(value)
        value = approval_mapping(); value["revokes_approval_event_id"] = "journal-event-" + "f" * 64
        with self.assertRaises(ContractValidationError): ApprovalInput.from_mapping(value)
        for replacement in ([], ["risk", "risk"], [True]):
            value = approval_mapping(); value["acknowledged_residual_risks"] = replacement
            with self.assertRaises(ContractValidationError): ApprovalInput.from_mapping(value)

    def test_report_gate_precedence(self):
        document = ProposalInput.from_mapping(proposal_mapping())
        for status, gate in (("PASS", "REVIEW_READY"), ("UNKNOWN", "DEFER"), ("FAIL", "REJECT")):
            report = report_mapping(); report["checks"][0]["status"] = status; report["gate"] = gate
            report["proposal_ready_for_human_review"] = gate == "REVIEW_READY"
            validate_proposal_report(report, document)
            report["gate"] = "REJECT" if gate != "REJECT" else "DEFER"
            with self.assertRaises(ContractValidationError): validate_proposal_report(report, document)
        report = report_mapping(); report["checks"].append({"check_id": "second", "status": "UNKNOWN", "observed": None, "limit": None, "reason_code": "MISSING"})
        report["checks"][0]["status"] = "FAIL"; report["gate"] = "REJECT"; report["proposal_ready_for_human_review"] = False
        validate_proposal_report(report, document)

    def test_report_strict_shape_hashes_and_checks(self):
        document = ProposalInput.from_mapping(proposal_mapping())
        for field, replacement in (("risk_policy_sha256", "a" * 64), ("risk_context_sha256", "a" * 64),
                                   ("residual_risks", []), ("checks", []), ("proposal_ready_for_human_review", 1),
                                   ("risk_method_version", "other"), ("approval_scope", "LIVE")):
            report = report_mapping(); report[field] = replacement
            with self.assertRaises(ContractValidationError): validate_proposal_report(report, document)
        report = report_mapping(); report["checks"].append(copy.deepcopy(report["checks"][0]))
        with self.assertRaises(ContractValidationError): validate_proposal_report(report, document)
        for value in (float("nan"), float("inf"), [], {}):
            report = report_mapping(); report["checks"][0]["observed"] = value
            with self.assertRaises(ContractValidationError): validate_proposal_report(report, document)

    def test_report_metrics_allow_rejected_overshoot_without_clamping(self):
        document = ProposalInput.from_mapping(proposal_mapping())
        report = report_mapping(); report["metrics"]["projected_cash_weight"] = -.3
        report["metrics"]["proposed_investment_gross"] = 1.3
        report["checks"][0]["status"] = "FAIL"; report["gate"] = "REJECT"; report["proposal_ready_for_human_review"] = False
        actual = validate_proposal_report(report, document)
        self.assertEqual(actual["metrics"]["projected_cash_weight"], -.3)
        for field in report["metrics"]:
            if not field.startswith("projected_symbol") and not field.startswith("projected_sector"):
                value = report_mapping(); value["metrics"][field] = True
                with self.assertRaises(ContractValidationError): validate_proposal_report(value, document)

    def test_report_cannot_claim_authentication_economic_truth_or_authority(self):
        for field in ("economic_truth_evaluated", "operational_authority_granted"):
            report = report_mapping(); report[field] = True
            with self.assertRaises(ContractValidationError): validate_proposal_report(report, ProposalInput.from_mapping(proposal_mapping()))
        approval = ApprovalInput.from_mapping(approval_mapping())
        for field, value in (("approver_identity_authenticated", True), ("operational_authority_granted", True),
                             ("realized_trade_pnl", 0), ("execution_status", "SHADOW_ONLY"), ("result", "ORDER_AUTHORIZED")):
            report = decision_mapping(); report[field] = value
            with self.assertRaises(ContractValidationError): validate_approval_decision(report, approval)

    def test_v4_event_round_trip_and_source_binding(self):
        for kind in ("proposal", "approval"):
            value = governance_event(kind)
            document = JournalEvent.from_mapping(value)
            self.assertEqual(document.to_bytes(), JournalEvent.from_bytes(document.to_bytes()).to_bytes())
            for path in (("source", "source_sha256"), ("recorded_at",), ("domain",), ("source", "kind")):
                item = copy.deepcopy(value); target = item
                for part in path[:-1]: target = target[part]
                target[path[-1]] = "a" * 64 if path[-1] == "source_sha256" else "2026-10-10T00:00:00Z" if path[-1] == "recorded_at" else "TRADING"
                with self.assertRaises(ContractValidationError): JournalEvent.from_mapping(item)

    def test_v4_does_not_broaden_old_versions(self):
        for kind in ("proposal", "approval"):
            for version in (1, 2, 3, 5):
                value = governance_event(kind); value["schema_version"] = f"blackpod.decision_journal_event.v{version}"
                with self.assertRaises(ContractValidationError): JournalEvent.from_mapping(value)
        from test_investment_review_contracts import challenge_event, evaluation_event
        for factory in (challenge_event, evaluation_event):
            value = factory(); document = JournalEvent.from_mapping(value)
            self.assertEqual(document.to_bytes(), canonical_json_bytes(value))
            value["schema_version"] = JOURNAL_EVENT_V4_SCHEMA_VERSION
            with self.assertRaises(ContractValidationError): JournalEvent.from_mapping(value)

    def test_parsing_duplicate_invalid_json_and_nesting_are_bounded(self):
        for contract, factory in ((ShadowRiskPolicy, policy_mapping), (RiskContextInput, context_mapping),
                                  (ProposalInput, proposal_mapping), (ApprovalInput, approval_mapping)):
            for source in (b'{"x":1,"x":2}', b'{"x":NaN}', b'{"x":Infinity}', b'[]', b'\xff', b'{"x":' + b'[' * 2000 + b'0' + b']' * 2000 + b'}'):
                with self.subTest(contract=contract.__name__, source=source[:30]), self.assertRaises(ContractValidationError): contract.from_bytes(source)
            value = factory(); value["nonstring"] = None; value[3] = None
            with self.assertRaises(ContractValidationError): contract.from_mapping(value)

    def test_report_nested_types_and_unique_metrics(self):
        document = ProposalInput.from_mapping(proposal_mapping())
        for path in ((), ("metrics",), ("metrics", "projected_symbol_weights", 0), ("metrics", "projected_sector_weights", 0), ("checks", 0), ("authority",)):
            report = report_mapping(); target = report
            for part in path: target = target[part]
            target["extra"] = True
            with self.assertRaises(ContractValidationError): validate_proposal_report(report, document)
        for field in ("projected_symbol_weights", "projected_sector_weights"):
            report = report_mapping(); report["metrics"][field].append(copy.deepcopy(report["metrics"][field][0]))
            with self.assertRaises(ContractValidationError): validate_proposal_report(report, document)


if __name__ == "__main__":
    unittest.main()
