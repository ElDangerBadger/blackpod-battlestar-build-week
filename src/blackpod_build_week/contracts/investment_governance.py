"""Strict source-bound SHADOW proposal, risk, and declared human review contracts.

These documents preserve research governance only. They never enable execution,
allocation, capital transfer, policy activation, or authenticated identity claims.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from ..hashing import sha256_bytes
from .decision_journal import (
    _ImmutableDocument, _boolean, _enum, _finite_number, _hash, _identifier,
    _object, _string,
)
from .investment_hypothesis import _scalar
from .investment_review import _event_id, _fixed_boolean, _list, _texts, disabled_authority
from .mission_request import (
    ContractValidationError, normalize_rfc3339, parse_rfc3339,
    parse_strict_json_object_bytes,
)

SHADOW_RISK_POLICY_SCHEMA_VERSION = "blackpod.investment_shadow_risk_policy.v1"
RISK_CONTEXT_SCHEMA_VERSION = "blackpod.investment_risk_context.v1"
PROPOSAL_SCHEMA_VERSION = "blackpod.investment_decision_proposal.v1"
APPROVAL_SCHEMA_VERSION = "blackpod.investment_shadow_approval.v1"
RISK_METHOD_VERSION = "blackpod.shadow_long_only_risk.v1"
SHADOW_APPROVAL_SCOPE = "INVESTMENT_SHADOW_RESEARCH_ONLY"
RISK_LIMIT_FIELDS = frozenset({
    "max_position_weight", "max_sector_weight", "max_consolidated_gross", "max_investment_gross",
    "min_cash_weight", "min_liquidity_score", "max_stress_loss_weight",
    "max_correlated_pair_weight", "high_correlation_threshold",
})
APPROVAL_ACTIONS = frozenset({"APPROVE", "REJECT", "DEFER", "REVOKE"})
APPROVAL_ORIGINS = frozenset({"HUMAN_DECLARED", "SIMULATED_TEST"})


def _number(value: object, name: str, lower: float = 0, upper: float | None = 1) -> int | float:
    if not _finite_number(value) or value < lower or (upper is not None and value > upper):
        raise ContractValidationError(f"{name} must be a finite number in [{lower}, {upper}]")
    return value


def _positive_integer(value: object, name: str) -> int:
    if type(value) is not int or value < 1:
        raise ContractValidationError(f"{name} must be a positive integer")
    return value


def _symbol(value: object, name: str = "symbol") -> str:
    result = _string(value, name, 64)
    if result != result.upper():
        raise ContractValidationError(f"{name} must be uppercase")
    return result


def _constant(result: dict, field: str, expected: object) -> None:
    if result[field] != expected:
        raise ContractValidationError(f"{field} must be {expected!r}")


def _base(value: object, fields: set[str], schema: str, name: str) -> dict[str, Any]:
    result = _object(value, fields, name)
    for field, expected in {"schema_version": schema, "domain": "INVESTMENT", "mode": "SHADOW"}.items():
        _constant(result, field, expected)
    result["recorded_at"] = normalize_rfc3339(result["recorded_at"], "recorded_at")
    result["authority"] = disabled_authority(result["authority"])
    return result


def _risk_policy(value: object) -> dict[str, Any]:
    result = _base(value, {
        "schema_version", "policy_id", "policy_version", "recorded_at", "status", "domain", "mode",
        "method_version", "max_context_age_seconds", "max_approval_lifetime_seconds", "required_approver_role",
        "authorized_approver_ids", "require_final_evaluation", "require_role_coverage",
        "require_distinct_role_artifacts", "require_no_active_dissent", "limits", "authority",
    }, SHADOW_RISK_POLICY_SCHEMA_VERSION, "shadow risk policy")
    _constant(result, "status", "SHADOW_PROPOSED")
    _constant(result, "method_version", RISK_METHOD_VERSION)
    result["policy_id"] = _identifier(result["policy_id"], "policy_id")
    for field in ("policy_version", "max_context_age_seconds", "max_approval_lifetime_seconds"):
        result[field] = _positive_integer(result[field], field)
    result["required_approver_role"] = _string(result["required_approver_role"], "required_approver_role")
    result["authorized_approver_ids"] = _texts(result["authorized_approver_ids"], "authorized_approver_ids", identifiers=True)
    if not result["authorized_approver_ids"]:
        raise ContractValidationError("authorized_approver_ids must be nonempty")
    result["require_final_evaluation"] = _boolean(result["require_final_evaluation"], "require_final_evaluation")
    for field in ("require_role_coverage", "require_distinct_role_artifacts", "require_no_active_dissent"):
        _fixed_boolean(result, field, True)
    limits = _object(result["limits"], RISK_LIMIT_FIELDS, "limits")
    for field in limits:
        limits[field] = _number(limits[field], "limits." + field)
    if limits["high_correlation_threshold"] <= 0:
        raise ContractValidationError("high_correlation_threshold must be greater than zero")
    result["limits"] = limits
    return result


def _risk_context(value: object) -> dict[str, Any]:
    result = _object(value, {
        "schema_version", "context_id", "as_of", "source_kind", "portfolio_scope_id", "basis", "scope_mode",
        "is_complete", "positions", "cash_by_desk", "instruments", "correlations",
    }, "risk context")
    for field, expected in {"schema_version": RISK_CONTEXT_SCHEMA_VERSION, "basis": "ACCOUNT_EQUITY_FRACTIONS", "scope_mode": "LONG_ONLY"}.items():
        _constant(result, field, expected)
    for field in ("context_id", "portfolio_scope_id"):
        result[field] = _identifier(result[field], field)
    result["as_of"] = normalize_rfc3339(result["as_of"], "as_of")
    result["source_kind"] = _enum(result["source_kind"], {"SYNTHETIC_FIXTURE", "MANUAL_SHADOW_INPUT"}, "source_kind")
    result["is_complete"] = _boolean(result["is_complete"], "is_complete")
    positions, keys = [], set()
    for entry in _list(result["positions"], "positions"):
        item = _object(entry, {"symbol", "desk", "weight"}, "position")
        item["symbol"] = _symbol(item["symbol"])
        item["desk"] = _enum(item["desk"], {"TRADING", "INVESTMENT"}, "desk")
        item["weight"] = _number(item["weight"], "weight")
        key = item["symbol"], item["desk"]
        if key in keys:
            raise ContractValidationError("positions contains duplicate symbol/desk")
        keys.add(key)
        positions.append(item)
    result["positions"] = positions
    cash = _object(result["cash_by_desk"], {"TRADING", "INVESTMENT"}, "cash_by_desk")
    for desk in cash:
        cash[desk] = _number(cash[desk], "cash_by_desk." + desk)
    total = sum((Decimal(str(item["weight"])) for item in positions), Decimal(0)) + sum((Decimal(str(weight)) for weight in cash.values()), Decimal(0))
    if abs(total - Decimal(1)) > Decimal("1e-12"):
        raise ContractValidationError("positions plus cash must equal account equity (1) within 1e-12; normalization is forbidden")
    result["cash_by_desk"] = cash
    instruments, symbols = [], set()
    for entry in _list(result["instruments"], "instruments"):
        item = _object(entry, {"symbol", "sector", "liquidity_score", "stress_loss_fraction"}, "instrument")
        item["symbol"] = _symbol(item["symbol"])
        if item["symbol"] in symbols:
            raise ContractValidationError("instruments contains duplicate symbol")
        symbols.add(item["symbol"])
        item["sector"] = _string(item["sector"], "sector")
        for field in ("liquidity_score", "stress_loss_fraction"):
            if item[field] is not None:
                item[field] = _number(item[field], field)
        instruments.append(item)
    result["instruments"] = instruments
    correlations, pairs = [], set()
    for entry in _list(result["correlations"], "correlations"):
        item = _object(entry, {"symbol_a", "symbol_b", "correlation"}, "correlation")
        for field in ("symbol_a", "symbol_b"):
            item[field] = _symbol(item[field], field)
        if item["symbol_a"] == item["symbol_b"]:
            raise ContractValidationError("correlation self-pairs are forbidden")
        pair = tuple(sorted((item["symbol_a"], item["symbol_b"])))
        if pair in pairs:
            raise ContractValidationError("correlations contains duplicate unordered symbol pair")
        pairs.add(pair)
        if item["correlation"] is not None:
            item["correlation"] = _number(item["correlation"], "correlation", -1, 1)
        correlations.append(item)
    result["correlations"] = correlations
    return result


def _proposal(value: object) -> dict[str, Any]:
    result = _base(value, {
        "schema_version", "proposal_id", "recorded_at", "evidence_cutoff_at", "submitted_by",
        "hypothesis_event_id", "hypothesis_id", "hypothesis_sha256", "challenge_event_id", "evaluation_event_id",
        "rationale", "targets", "risk_policy", "risk_context", "valid_until", "supersedes_event_id", "domain", "mode", "authority",
    }, PROPOSAL_SCHEMA_VERSION, "investment proposal")
    for field in ("proposal_id", "submitted_by", "hypothesis_id"):
        result[field] = _identifier(result[field], field)
    for field in ("hypothesis_event_id", "challenge_event_id"):
        result[field] = _event_id(result[field], field)
    for field in ("evaluation_event_id", "supersedes_event_id"):
        if result[field] is not None:
            result[field] = _event_id(result[field], field)
    result["hypothesis_sha256"] = _hash(result["hypothesis_sha256"], "hypothesis_sha256")
    result["evidence_cutoff_at"] = normalize_rfc3339(result["evidence_cutoff_at"], "evidence_cutoff_at")
    result["valid_until"] = normalize_rfc3339(result["valid_until"], "valid_until")
    recorded = parse_rfc3339(result["recorded_at"], "recorded_at")
    if parse_rfc3339(result["evidence_cutoff_at"], "evidence_cutoff_at") > recorded:
        raise ContractValidationError("evidence_cutoff_at must not be after recorded_at")
    if parse_rfc3339(result["valid_until"], "valid_until") <= recorded:
        raise ContractValidationError("valid_until must be after recorded_at")
    result["rationale"] = _string(result["rationale"], "rationale", 10000)
    targets, symbols = [], set()
    for entry in _list(result["targets"], "targets"):
        item = _object(entry, {"symbol", "weight"}, "target")
        item["symbol"] = _symbol(item["symbol"])
        item["weight"] = _number(item["weight"], "target.weight")
        if item["symbol"] in symbols:
            raise ContractValidationError("targets contains duplicate symbol")
        symbols.add(item["symbol"])
        targets.append(item)
    result["targets"] = targets
    result["risk_policy"] = ShadowRiskPolicy.from_mapping(result["risk_policy"]).to_dict()
    result["risk_context"] = RiskContextInput.from_mapping(result["risk_context"]).to_dict()
    return result


def _approval(value: object) -> dict[str, Any]:
    result = _base(value, {
        "schema_version", "approval_id", "proposal_event_id", "proposal_id", "proposal_sha256", "risk_policy_sha256",
        "risk_context_sha256", "report_sha256", "recorded_at", "approver_id", "approver_role", "action", "origin", "scope",
        "acknowledged_residual_risks", "expires_at", "revokes_approval_event_id", "confirmation", "domain", "mode", "authority",
    }, APPROVAL_SCHEMA_VERSION, "shadow approval")
    for field in ("approval_id", "proposal_id", "approver_id"):
        result[field] = _identifier(result[field], field)
    result["proposal_event_id"] = _event_id(result["proposal_event_id"], "proposal_event_id")
    for field in ("proposal_sha256", "risk_policy_sha256", "risk_context_sha256", "report_sha256"):
        result[field] = _hash(result[field], field)
    result["approver_role"] = _string(result["approver_role"], "approver_role")
    result["action"] = _enum(result["action"], APPROVAL_ACTIONS, "action")
    result["origin"] = _enum(result["origin"], APPROVAL_ORIGINS, "origin")
    _constant(result, "scope", SHADOW_APPROVAL_SCOPE)
    result["acknowledged_residual_risks"] = _texts(result["acknowledged_residual_risks"], "acknowledged_residual_risks")
    if result["action"] == "APPROVE":
        if not result["acknowledged_residual_risks"]:
            raise ContractValidationError("APPROVE requires acknowledged_residual_risks")
        result["expires_at"] = normalize_rfc3339(result["expires_at"], "expires_at")
        if parse_rfc3339(result["expires_at"], "expires_at") <= parse_rfc3339(result["recorded_at"], "recorded_at"):
            raise ContractValidationError("approval expires_at must be after recorded_at")
    elif result["expires_at"] is not None:
        raise ContractValidationError("non-APPROVE actions require null expires_at")
    if result["action"] == "REVOKE":
        result["revokes_approval_event_id"] = _event_id(result["revokes_approval_event_id"], "revokes_approval_event_id")
    elif result["revokes_approval_event_id"] is not None:
        raise ContractValidationError("only REVOKE can reference an approval revocation target")
    confirmation = _object(result["confirmation"], {"action", "proposal_sha256", "acknowledges_shadow_only"}, "confirmation")
    if confirmation["action"] != result["action"] or confirmation["proposal_sha256"] != result["proposal_sha256"]:
        raise ContractValidationError("confirmation must bind the exact action and proposal_sha256")
    _fixed_boolean(confirmation, "acknowledges_shadow_only", True)
    result["confirmation"] = confirmation
    return result


def validate_proposal_report(value: object, proposal: ProposalInput) -> dict[str, Any]:
    """Validate deterministic risk gate shape; journal scans recompute its values."""
    result = _object(value, {
        "risk_method_version", "gate", "checks", "metrics", "risk_policy_sha256", "risk_context_sha256", "residual_risks",
        "proposal_ready_for_human_review", "approval_scope", "economic_truth_evaluated", "operational_authority_granted", "authority",
    }, "proposal report")
    _constant(result, "risk_method_version", RISK_METHOD_VERSION)
    result["gate"] = _enum(result["gate"], {"REVIEW_READY", "REJECT", "DEFER"}, "gate")
    checks, identities = [], set()
    for entry in _list(result["checks"], "checks", nonempty=True):
        item = _object(entry, {"check_id", "status", "observed", "limit", "reason_code"}, "risk check")
        item["check_id"] = _identifier(item["check_id"], "check_id")
        if item["check_id"] in identities:
            raise ContractValidationError("checks contains duplicate check_id")
        identities.add(item["check_id"])
        item["status"] = _enum(item["status"], {"PASS", "FAIL", "UNKNOWN"}, "check.status")
        for field in ("observed", "limit"):
            item[field] = _scalar(item[field], "check." + field)
        item["reason_code"] = _identifier(item["reason_code"], "reason_code")
        checks.append(item)
    result["checks"] = checks
    statuses = {item["status"] for item in checks}
    expected_gate = "REJECT" if "FAIL" in statuses else "DEFER" if "UNKNOWN" in statuses else "REVIEW_READY"
    if result["gate"] != expected_gate:
        raise ContractValidationError("gate must reflect FAIL/UNKNOWN/PASS check precedence")
    _fixed_boolean(result, "proposal_ready_for_human_review", result["gate"] == "REVIEW_READY")
    metrics = _object(result["metrics"], {
        "investment_budget_weight", "proposed_investment_gross", "projected_consolidated_gross", "projected_cash_weight",
        "projected_stress_loss_weight", "projected_symbol_weights", "projected_sector_weights",
    }, "risk metrics")
    for field in ("investment_budget_weight", "proposed_investment_gross", "projected_consolidated_gross"):
        metrics[field] = _number(metrics[field], field, upper=None)
    if not _finite_number(metrics["projected_cash_weight"]):
        raise ContractValidationError("projected_cash_weight must be a finite number")
    if metrics["projected_stress_loss_weight"] is not None:
        metrics["projected_stress_loss_weight"] = _number(metrics["projected_stress_loss_weight"], "projected_stress_loss_weight", upper=None)
    for field, identity in (("projected_symbol_weights", "symbol"), ("projected_sector_weights", "sector")):
        entries, keys = [], set()
        for entry in _list(metrics[field], field):
            item = _object(entry, {identity, "weight"}, field + " entry")
            item[identity] = _symbol(item[identity]) if identity == "symbol" else _string(item[identity], "sector")
            if item[identity] in keys:
                raise ContractValidationError(field + " contains duplicate " + identity)
            keys.add(item[identity])
            item["weight"] = _number(item["weight"], field + ".weight", upper=None)
            entries.append(item)
        metrics[field] = entries
    result["metrics"] = metrics
    for field, document_key in (("risk_policy_sha256", "risk_policy"), ("risk_context_sha256", "risk_context")):
        result[field] = _hash(result[field], field)
        contract = ShadowRiskPolicy if document_key == "risk_policy" else RiskContextInput
        if result[field] != sha256_bytes(contract.from_mapping(getattr(proposal, document_key)).to_bytes()):
            raise ContractValidationError(field + " must bind proposal input")
    result["residual_risks"] = _texts(result["residual_risks"], "residual_risks", identifiers=True)
    if not result["residual_risks"]:
        raise ContractValidationError("residual_risks must be nonempty")
    _constant(result, "approval_scope", SHADOW_APPROVAL_SCOPE)
    for field in ("economic_truth_evaluated", "operational_authority_granted"):
        _fixed_boolean(result, field, False)
    result["authority"] = disabled_authority(result["authority"])
    return result


def validate_approval_decision(value: object, approval: ApprovalInput) -> dict[str, Any]:
    """Validate the explicitly non-executable declared human review result."""
    result = _object(value, {
        "action", "result", "origin", "scope", "expires_at", "approver_identity_authenticated", "operational_authority_granted",
        "execution_status", "realized_trade_pnl", "authority",
    }, "approval decision")
    for field in ("action", "origin", "scope", "expires_at"):
        if result[field] != getattr(approval, field):
            raise ContractValidationError("approval decision " + field + " must match supplied approval")
    expected = {"REJECT": "REJECTED", "DEFER": "DEFERRED", "REVOKE": "REVOKED"}.get(approval.action)
    if approval.action == "APPROVE":
        expected = "SIMULATED_SHADOW_APPROVED" if approval.origin == "SIMULATED_TEST" else "SHADOW_RESEARCH_APPROVED"
    _constant(result, "result", expected)
    _constant(result, "execution_status", "NOT_EXECUTED")
    if result["realized_trade_pnl"] is not None:
        raise ContractValidationError("shadow approval cannot have realized trade P&L")
    for field in ("approver_identity_authenticated", "operational_authority_granted"):
        _fixed_boolean(result, field, False)
    result["authority"] = disabled_authority(result["authority"])
    return result


class _GovernanceDocument(_ImmutableDocument):
    __slots__ = ()

    def __init__(self, value):
        try:
            super().__init__(value)
        except (RecursionError, ValueError, OverflowError) as exc:
            if isinstance(exc, ContractValidationError):
                raise
            raise ContractValidationError("investment governance nesting or numeric representation exceeds supported limits") from exc

    @classmethod
    def from_bytes(cls, value: bytes):
        try:
            parsed = parse_strict_json_object_bytes(value, document_name=cls.__name__)
        except (RecursionError, ValueError, OverflowError) as exc:
            if isinstance(exc, ContractValidationError):
                raise
            raise ContractValidationError("investment governance JSON nesting or numeric representation exceeds supported limits") from exc
        return cls.from_mapping(parsed)


class ShadowRiskPolicy(_GovernanceDocument):
    __slots__ = ()
    _validator = staticmethod(_risk_policy)


class RiskContextInput(_GovernanceDocument):
    __slots__ = ()
    _validator = staticmethod(_risk_context)


class ProposalInput(_GovernanceDocument):
    __slots__ = ()
    _validator = staticmethod(_proposal)


class ApprovalInput(_GovernanceDocument):
    __slots__ = ()
    _validator = staticmethod(_approval)
