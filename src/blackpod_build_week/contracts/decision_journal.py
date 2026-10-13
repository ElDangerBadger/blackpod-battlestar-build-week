"""Strict, immutable contracts for the passive two-desk Decision Journal.

These documents convey historical evidence and inactive proposals. They grant
no order, allocation, transfer, policy activation, or execution authority.
"""

from __future__ import annotations

import json
import math
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, ClassVar

from ..hashing import canonical_json_bytes, sha256_bytes
from ..identifiers import IdentifierError, validate_identifier
from .mission_request import (
    ContractValidationError,
    normalize_rfc3339,
    parse_strict_json_object_bytes,
)

JOURNAL_EVENT_SCHEMA_VERSION = "blackpod.decision_journal_event.v1"
JOURNAL_EVENT_V2_SCHEMA_VERSION = "blackpod.decision_journal_event.v2"
JOURNAL_EVENT_V3_SCHEMA_VERSION = "blackpod.decision_journal_event.v3"
JOURNAL_EVENT_V4_SCHEMA_VERSION = "blackpod.decision_journal_event.v4"
JOURNAL_EVENT_V5_SCHEMA_VERSION = "blackpod.decision_journal_event.v5"
JOURNAL_EVENT_V6_SCHEMA_VERSION = "blackpod.decision_journal_event.v6"
JOURNAL_EVENT_V7_SCHEMA_VERSION = "blackpod.decision_journal_event.v7"
JOURNAL_EVENT_V8_SCHEMA_VERSION = "blackpod.decision_journal_event.v8"
JOURNAL_EVENT_V9_SCHEMA_VERSION = "blackpod.decision_journal_event.v9"
JOURNAL_EVENT_V10_SCHEMA_VERSION = "blackpod.decision_journal_event.v10"
JOURNAL_EVENT_V11_SCHEMA_VERSION = "blackpod.decision_journal_event.v11"
JOURNAL_EVENT_V12_SCHEMA_VERSION = "blackpod.decision_journal_event.v12"
JOURNAL_EVENT_V13_SCHEMA_VERSION = "blackpod.decision_journal_event.v13"
JOURNAL_EVENT_V14_SCHEMA_VERSION = "blackpod.decision_journal_event.v14"
JOURNAL_EVENT_V15_SCHEMA_VERSION = "blackpod.decision_journal_event.v15"
JOURNAL_EVENT_V16_SCHEMA_VERSION = "blackpod.decision_journal_event.v16"
JOURNAL_EVENT_V17_SCHEMA_VERSION = "blackpod.decision_journal_event.v17"
JOURNAL_EVENT_V18_SCHEMA_VERSION = "blackpod.decision_journal_event.v18"
JOURNAL_EVENT_V19_SCHEMA_VERSION = "blackpod.decision_journal_event.v19"
JOURNAL_EVENT_V20_SCHEMA_VERSION = "blackpod.decision_journal_event.v20"
JOURNAL_EVENT_V21_SCHEMA_VERSION = "blackpod.decision_journal_event.v21"
INVESTMENT_HYPOTHESIS_EVENT_TYPE = "INVESTMENT_HYPOTHESIS_RECORDED"
INVESTMENT_CHALLENGE_EVENT_TYPE = "INVESTMENT_CHALLENGE_RECORDED"
INVESTMENT_OUTCOME_EVALUATION_EVENT_TYPE = "INVESTMENT_OUTCOME_EVALUATION_RECORDED"
INVESTMENT_DECISION_PROPOSAL_EVENT_TYPE = "INVESTMENT_DECISION_PROPOSAL_RECORDED"
INVESTMENT_SHADOW_APPROVAL_EVENT_TYPE = "INVESTMENT_SHADOW_APPROVAL_RECORDED"
TRADING_AUTOMATION_SWITCH_EVENT_TYPE = "TRADING_AUTOMATION_SWITCH_RECORDED"
PAPER_BROKER_SNAPSHOT_EVENT_TYPE = "PAPER_BROKER_SNAPSHOT_RECORDED"
TRADING_DESK_OWNERSHIP_EVENT_TYPE = "TRADING_DESK_OWNERSHIP_RECORDED"
TRADING_EXECUTION_RECONCILED_EVENT_TYPE = "TRADING_EXECUTION_RECONCILED"
TRADING_FILL_LOT_ACCOUNTING_EVENT_TYPE = "TRADING_FILL_LOT_ACCOUNTING_RECORDED"
SHADOW_DESK_REVIEW_EVENT_TYPE = "SHADOW_DESK_REVIEW_RECORDED"
EVALUATION_SCHEMA_VERSION = "blackpod.decision_journal_evaluation.v1"
CAPITAL_POLICY_SCHEMA_VERSION = "blackpod.capital_policy_proposal.v1"
JOURNAL_DOMAINS = frozenset({"TRADING", "INVESTMENT", "CAPITAL_ALLOCATION", "UNCLASSIFIED"})
JOURNAL_EVENT_TYPES = frozenset({"MISSION_SNAPSHOT_RECORDED", "EVALUATION_RECORDED", "CAPITAL_POLICY_PROPOSED"})
INITIAL_CAPITAL_POLICY_ID = "initial-two-desk-50-50"
_HEX = re.compile(r"^[0-9a-f]{64}$")
_JOURNAL_ID = re.compile(r"^[a-z][a-z0-9]*(?:-[a-z0-9]+)*-[0-9a-f]{64}$")
_HISTORICAL_FIELDS = frozenset({"hypothesis", "expectations", "investment_horizon", "confidence_probability", "evaluation"})


def _object(value: object, fields: set[str] | frozenset[str], name: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ContractValidationError(f"{name} must be an object")
    if any(not isinstance(key, str) for key in value):
        raise ContractValidationError(f"{name} keys must be strings")
    missing, unknown = fields - set(value), set(value) - fields
    if missing:
        raise ContractValidationError(f"{name} is missing fields: {', '.join(sorted(missing))}")
    if unknown:
        raise ContractValidationError(f"{name} contains unknown fields: {', '.join(sorted(unknown))}")
    return dict(value)


def _string(value: object, name: str, maximum: int = 256) -> str:
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise ContractValidationError(f"{name} must be a nonblank string without surrounding whitespace")
    if len(value) > maximum or any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise ContractValidationError(f"{name} contains unsupported characters or exceeds {maximum} characters")
    try:
        value.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise ContractValidationError(f"{name} must contain valid Unicode text") from exc
    return value


def _nullable_string(value: object, name: str, maximum: int = 256) -> str | None:
    return None if value is None else _string(value, name, maximum)


def _identifier(value: object, name: str) -> str:
    try:
        return validate_identifier(value, name)
    except IdentifierError as exc:
        raise ContractValidationError(str(exc)) from exc


def _journal_id(value: object, name: str) -> str:
    if not isinstance(value, str) or not _JOURNAL_ID.fullmatch(value):
        raise ContractValidationError(f"{name} must have a lowercase token prefix and full SHA-256 suffix")
    return value


def _hash(value: object, name: str) -> str:
    if not isinstance(value, str) or not _HEX.fullmatch(value):
        raise ContractValidationError(f"{name} must be a lowercase SHA-256 digest")
    return value


def _enum(value: object, allowed: set[str] | frozenset[str], name: str) -> str:
    if not isinstance(value, str) or value not in allowed:
        raise ContractValidationError(f"{name} must be one of {', '.join(sorted(allowed))}")
    return value


def _boolean(value: object, name: str) -> bool:
    if type(value) is not bool:
        raise ContractValidationError(f"{name} must be a boolean")
    return value


def _finite_number(value: object) -> bool:
    return type(value) is int or (type(value) is float and math.isfinite(value))


def validate_evidence_path(value: object) -> str:
    """Require an unambiguous relative POSIX path, never a filesystem escape."""
    path = _string(value, "evidence.path", 4096)
    if "\\" in path or ":" in path or path.startswith("/") or any(part in {"", ".", ".."} for part in path.split("/")):
        raise ContractValidationError("evidence.path must be a safe relative POSIX path")
    return path


def _evidence(value: object) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise ContractValidationError("evidence must be a list")
    seen: set[str] = set()
    result = []
    for entry in value:
        item = _object(entry, {"path", "sha256", "size_bytes"}, "evidence entry")
        item["path"] = validate_evidence_path(item["path"])
        item["sha256"] = _hash(item["sha256"], "evidence.sha256")
        if type(item["size_bytes"]) is not int or item["size_bytes"] < 0:
            raise ContractValidationError("evidence.size_bytes must be a nonnegative integer")
        if item["path"] in seen:
            raise ContractValidationError("evidence contains duplicate paths")
        seen.add(item["path"])
        result.append(item)
    return result


def _source(value: object, event_type: str) -> dict[str, Any]:
    kind = {"MISSION_SNAPSHOT_RECORDED": "MISSION", "EVALUATION_RECORDED": "EVALUATION", "CAPITAL_POLICY_PROPOSED": "CAPITAL_POLICY"}[event_type]
    fields = {"kind", "source_sha256"}
    fields |= {"mission_id", "request_id", "run_mode", "revision"} if kind == "MISSION" else {"evaluation_id"} if kind == "EVALUATION" else {"policy_id"}
    result = _object(value, fields, "source")
    if result["kind"] != kind:
        raise ContractValidationError("source.kind does not match event_type")
    result["source_sha256"] = _hash(result["source_sha256"], "source.source_sha256")
    if kind == "MISSION":
        for field in ("mission_id", "request_id"):
            result[field] = _identifier(result[field], f"source.{field}")
        result["run_mode"] = _enum(result["run_mode"], {"LIVE", "REPLAY"}, "source.run_mode")
        if type(result["revision"]) is not int or result["revision"] < 1:
            raise ContractValidationError("source.revision must be a positive integer")
    else:
        field = "evaluation_id" if kind == "EVALUATION" else "policy_id"
        result[field] = _identifier(result[field], f"source.{field}")
    return result


def _mission_payload(value: object, domain: str) -> dict[str, Any]:
    result = _object(value, {"classification", "symbol", "mission_outcome", "current_phase", "terminal", "stages", "decision", "authorization", "execution_status", "historical_semantics"}, "mission payload")
    classification = _object(result["classification"], {"basis", "reason"}, "classification")
    classification["basis"] = _enum(classification["basis"], {"HISTORICAL_UNCLASSIFIED", "EXPLICIT_IMPORT_CLASSIFICATION"}, "classification.basis")
    classification["reason"] = _string(classification["reason"], "classification.reason", 2048)
    required_basis = "HISTORICAL_UNCLASSIFIED" if domain == "UNCLASSIFIED" else "EXPLICIT_IMPORT_CLASSIFICATION"
    if classification["basis"] != required_basis:
        raise ContractValidationError("classification basis does not match domain")
    result["classification"] = classification
    result["symbol"] = _string(result["symbol"], "symbol", 64)
    result["mission_outcome"] = _enum(result["mission_outcome"], {"APPROVED", "HELD", "VETOED", "FAILED", "INCOMPLETE"}, "mission_outcome")
    result["current_phase"] = _enum(result["current_phase"], {"HARBORMASTER", "ORACLE", "COUNCIL", "GOVERNOR", "OPERATOR", "NAVIGATOR", "COMPLETE"}, "current_phase")
    result["terminal"] = _boolean(result["terminal"], "terminal")
    if not isinstance(result["stages"], list):
        raise ContractValidationError("stages must be a list")
    stages, names = [], set()
    for entry in result["stages"]:
        stage = _object(entry, {"name", "status", "native_state"}, "stage")
        stage["name"] = _identifier(stage["name"], "stage.name")
        stage["status"] = _enum(stage["status"], {"NOT_STARTED", "RUNNING", "SUCCEEDED", "FAILED", "SKIPPED"}, "stage.status")
        stage["native_state"] = _nullable_string(stage["native_state"], "stage.native_state")
        if stage["name"] in names:
            raise ContractValidationError("stages contains duplicate names")
        names.add(stage["name"])
        stages.append(stage)
    result["stages"] = stages
    decision = _object(result["decision"], {"disposition", "authority", "decision_id"}, "decision")
    for field in decision:
        decision[field] = _nullable_string(decision[field], f"decision.{field}")
    result["decision"] = decision
    authorization = _object(result["authorization"], {"status", "scope", "operator_id", "action_id"}, "authorization")
    authorization["status"] = _enum(authorization["status"], {"NOT_RECORDED", "REJECTED", "SHADOW_APPROVED"}, "authorization.status")
    if authorization["scope"] is not None:
        authorization["scope"] = _enum(authorization["scope"], {"NAVIGATOR_SHADOW_HANDOFF"}, "authorization.scope")
    for field in ("operator_id", "action_id"):
        if authorization[field] is not None:
            authorization[field] = _identifier(authorization[field], f"authorization.{field}")
    if authorization["status"] == "NOT_RECORDED" and any(authorization[field] is not None for field in ("scope", "operator_id", "action_id")):
        raise ContractValidationError("unrecorded authorization must have null scope and identities")
    if authorization["status"] in {"REJECTED", "SHADOW_APPROVED"} and any(authorization[field] is None for field in ("operator_id", "action_id")):
        raise ContractValidationError("recorded authorization requires operator_id and action_id")
    if authorization["status"] == "SHADOW_APPROVED" and authorization["scope"] != "NAVIGATOR_SHADOW_HANDOFF":
        raise ContractValidationError("SHADOW approval requires NAVIGATOR_SHADOW_HANDOFF scope")
    result["authorization"] = authorization
    result["execution_status"] = _enum(result["execution_status"], {"NOT_EXECUTED", "SHADOW_ONLY"}, "execution_status")
    if result["execution_status"] == "SHADOW_ONLY" and authorization["status"] != "SHADOW_APPROVED":
        raise ContractValidationError("SHADOW_ONLY requires SHADOW_APPROVED authorization")
    historical = _object(result["historical_semantics"], _HISTORICAL_FIELDS, "historical_semantics")
    if any(item != "NOT_RECORDED" for item in historical.values()):
        raise ContractValidationError("missing historical semantics must remain NOT_RECORDED")
    result["historical_semantics"] = historical
    return result


def _evaluation(value: object) -> dict[str, Any]:
    result = _object(value, {"schema_version", "evaluation_id", "decision_id", "recorded_at", "evaluator", "evaluation_type", "conclusion", "outcome_status", "realized_trade_pnl"}, "evaluation")
    if result["schema_version"] != EVALUATION_SCHEMA_VERSION:
        raise ContractValidationError("unsupported evaluation schema_version")
    result["evaluation_id"] = _identifier(result["evaluation_id"], "evaluation_id")
    result["decision_id"] = _journal_id(result["decision_id"], "decision_id")
    result["recorded_at"] = normalize_rfc3339(result["recorded_at"], "recorded_at")
    result["evaluator"] = _identifier(result["evaluator"], "evaluator")
    result["evaluation_type"] = _enum(result["evaluation_type"], {"PROCESS", "THESIS", "COUNTERFACTUAL", "TRADE"}, "evaluation_type")
    result["conclusion"] = _string(result["conclusion"], "conclusion", 10000)
    result["outcome_status"] = _enum(result["outcome_status"], {"OBSERVED", "INCONCLUSIVE", "MANUAL_NOTE"}, "outcome_status")
    pnl = result["realized_trade_pnl"]
    if pnl is not None and not _finite_number(pnl):
        raise ContractValidationError("realized_trade_pnl must be null or a finite number")
    if pnl is not None and result["evaluation_type"] != "TRADE":
        raise ContractValidationError("realized trade P&L requires TRADE evaluation_type")
    return result


def _capital_policy(value: object) -> dict[str, Any]:
    result = _object(value, {"schema_version", "policy_id", "proposed_at", "status", "allocations", "allocation_basis", "rebalance_mode", "activation_enabled", "capital_transfers_enabled", "automated_reallocation_enabled", "consolidated_account_risk_required", "subsequent_changes_require_explicit_authorization"}, "capital policy")
    constants = {"schema_version": CAPITAL_POLICY_SCHEMA_VERSION, "policy_id": INITIAL_CAPITAL_POLICY_ID, "status": "PROPOSED", "allocation_basis": "ACCOUNT_EQUITY", "rebalance_mode": "INITIAL_ALLOCATION_ONLY"}
    for field, expected in constants.items():
        if result[field] != expected:
            raise ContractValidationError(f"capital policy {field} must be {expected!r}")
    result["proposed_at"] = normalize_rfc3339(result["proposed_at"], "proposed_at")
    allocations = _object(result["allocations"], {"TRADING", "INVESTMENT"}, "allocations")
    for desk, fraction in allocations.items():
        if not _finite_number(fraction) or fraction != 0.5:
            raise ContractValidationError(f"allocations.{desk} must be 0.5")
        allocations[desk] = 0.5
    result["allocations"] = allocations
    for field in ("activation_enabled", "capital_transfers_enabled", "automated_reallocation_enabled"):
        if _boolean(result[field], field):
            raise ContractValidationError(f"capital policy {field} must remain disabled")
    for field in ("consolidated_account_risk_required", "subsequent_changes_require_explicit_authorization"):
        if not _boolean(result[field], field):
            raise ContractValidationError(f"capital policy {field} must be true")
    return result


def _event(value: object) -> dict[str, Any]:
    result = _object(value, {"schema_version", "event_id", "decision_id", "domain", "event_type", "recorded_at", "source", "evidence", "payload"}, "journal event")
    if result["schema_version"] == JOURNAL_EVENT_V2_SCHEMA_VERSION:
        return _hypothesis_event(result)
    if result["schema_version"] == JOURNAL_EVENT_V3_SCHEMA_VERSION:
        return _review_event(result)
    if result["schema_version"] == JOURNAL_EVENT_V4_SCHEMA_VERSION:
        return _governance_event(result)
    if result["schema_version"] == JOURNAL_EVENT_V5_SCHEMA_VERSION:
        return _automation_event(result)
    if result["schema_version"] == JOURNAL_EVENT_V6_SCHEMA_VERSION:
        return _trading_reconciliation_event(result)
    if result["schema_version"] == JOURNAL_EVENT_V7_SCHEMA_VERSION:
        return _trading_accounting_event(result)
    if result["schema_version"] == JOURNAL_EVENT_V8_SCHEMA_VERSION:
        return _desk_candidate_review_event(result)
    if result["schema_version"] == JOURNAL_EVENT_V9_SCHEMA_VERSION:
        return _forecast_brigade_event(result)
    if result["schema_version"] == JOURNAL_EVENT_V10_SCHEMA_VERSION:
        return _forecast_producer_event(result)
    if result["schema_version"] == JOURNAL_EVENT_V11_SCHEMA_VERSION:
        return _forecast_brigade_event(result, structured=True)
    if result["schema_version"] == JOURNAL_EVENT_V12_SCHEMA_VERSION:
        return _trading_research_event(result)
    if result["schema_version"] == JOURNAL_EVENT_V13_SCHEMA_VERSION:
        return _trading_intake_event(result)
    if result["schema_version"] == JOURNAL_EVENT_V14_SCHEMA_VERSION:
        return _trading_research_event(result, governed=True)
    if result["schema_version"] == JOURNAL_EVENT_V15_SCHEMA_VERSION:
        return _trading_shadow_event(result)
    if result["schema_version"] == JOURNAL_EVENT_V16_SCHEMA_VERSION:
        return _reviewed_shadow_event(result)
    if result["schema_version"] == JOURNAL_EVENT_V17_SCHEMA_VERSION:
        from .research_assessment import validate_journal_event
        return validate_journal_event(result)
    if result["schema_version"] == JOURNAL_EVENT_V18_SCHEMA_VERSION:
        from .trading_evidence_qualification import validate_journal_event
        return validate_journal_event(result)
    if result["schema_version"] == JOURNAL_EVENT_V19_SCHEMA_VERSION:
        from .train_market_evidence import validate_journal_event
        return validate_journal_event(result)
    if result["schema_version"] == JOURNAL_EVENT_V20_SCHEMA_VERSION:
        from .segmented_evidence_qualification import validate_journal_event
        return validate_journal_event(result)
    if result["schema_version"] == JOURNAL_EVENT_V21_SCHEMA_VERSION:
        from .native_evidence_closure import validate_journal_event
        return validate_journal_event(result)
    if result["schema_version"] != JOURNAL_EVENT_SCHEMA_VERSION:
        raise ContractValidationError("unsupported journal event schema_version")
    for field in ("event_id", "decision_id"):
        result[field] = _journal_id(result[field], field)
    result["domain"] = _enum(result["domain"], JOURNAL_DOMAINS, "domain")
    result["event_type"] = _enum(result["event_type"], JOURNAL_EVENT_TYPES, "event_type")
    result["recorded_at"] = normalize_rfc3339(result["recorded_at"], "recorded_at")
    result["source"] = _source(result["source"], result["event_type"])
    result["evidence"] = _evidence(result["evidence"])
    if result["event_type"] == "MISSION_SNAPSHOT_RECORDED":
        result["payload"] = _mission_payload(result["payload"], result["domain"])
    elif result["event_type"] == "EVALUATION_RECORDED":
        fields = {"schema_version", "evaluation_id", "decision_id", "recorded_at", "evaluator", "evaluation_type", "conclusion", "outcome_status", "realized_trade_pnl", "execution_status"}
        payload = _object(result["payload"], fields, "evaluation payload")
        execution_status = _enum(payload.pop("execution_status"), {"NOT_EXECUTED", "SHADOW_ONLY"}, "execution_status")
        payload = _evaluation(payload)
        if payload["realized_trade_pnl"] is not None or payload["evaluation_type"] == "TRADE":
            raise ContractValidationError("non-executed or SHADOW-only decisions cannot have TRADE evaluations or realized trade P&L")
        for field in ("decision_id", "recorded_at"):
            if result[field] != payload[field]:
                raise ContractValidationError(f"evaluation {field} must match event")
        if result["source"]["evaluation_id"] != payload["evaluation_id"] or result["source"]["source_sha256"] != sha256_bytes(canonical_json_bytes(payload)):
            raise ContractValidationError("evaluation source identity or hash does not match payload")
        result["payload"] = {**payload, "execution_status": execution_status}
    else:
        if result["domain"] != "CAPITAL_ALLOCATION":
            raise ContractValidationError("capital policy requires CAPITAL_ALLOCATION domain")
        payload = _capital_policy(result["payload"])
        if result["recorded_at"] != payload["proposed_at"]:
            raise ContractValidationError("capital policy proposed_at must match event recorded_at")
        if result["source"]["policy_id"] != payload["policy_id"] or result["source"]["source_sha256"] != sha256_bytes(canonical_json_bytes(payload)):
            raise ContractValidationError("capital policy source identity or hash does not match payload")
        result["payload"] = payload
    return result


def _reviewed_shadow_event(result: dict[str, Any]) -> dict[str, Any]:
    from .trading_continuity_intake import ContinuityIntakeRequest
    from .trading_cost_intake import CostIntakeRequest
    from .trading_shadow_risk_review import TradingShadowRiskReview
    from .trading_shadow_review import ReviewedShadowStudy
    from .investment_review import disabled_authority
    if result["domain"] != "TRADING":
        raise ContractValidationError("governed evidence records require TRADING domain")
    for field in ("event_id", "decision_id"):
        result[field] = _journal_id(result[field], field)
    result["recorded_at"] = normalize_rfc3339(result["recorded_at"], "recorded_at")
    types = {
        "TRADING_CONTINUITY_INTAKE_RECORDED": ("TRADING_CONTINUITY_INTAKE", ContinuityIntakeRequest, "request", "run_id"),
        "TRADING_COST_INTAKE_RECORDED": ("TRADING_COST_INTAKE", CostIntakeRequest, "request", "run_id"),
        "TRADING_SHADOW_RISK_REVIEW_RECORDED": ("TRADING_SHADOW_RISK_REVIEW", TradingShadowRiskReview, "review", "risk_review_id"),
        "TRADING_REVIEWED_SHADOW_STUDY_REGISTERED": ("TRADING_REVIEWED_SHADOW_STUDY", ReviewedShadowStudy, "study", "study_id"),
        "TRADING_REVIEWED_SHADOW_EVALUATION_RECORDED": ("TRADING_REVIEWED_SHADOW_EVALUATION", ReviewedShadowStudy, "study", "study_id"),
    }
    if result["event_type"] not in types:
        raise ContractValidationError("unsupported governed evidence event type")
    kind, cls, doc_key, id_key = types[result["event_type"]]
    evaluation = kind == "TRADING_REVIEWED_SHADOW_EVALUATION"
    fields = {"kind", id_key, "source_sha256"}
    payload_fields = {"request", "export"} if doc_key == "request" else {"review", "assessment", "base_plan_event_id", "hypothesis_event_id", "intake_event_id"}
    if doc_key == "study":
        fields |= {"experiment_id", "trial_id"}
        payload_fields = {"study", "base_plan_event_id", "hypothesis_event_id", "intake_event_id", "risk_review_event_id",
            "continuity_event_id", "cost_event_id", "gate_assessment", "risk_assessment", "implementation_evidence"}
        if evaluation:
            fields.add("evaluation_id"); payload_fields |= {"study_event_id", "production", "result"}
    source = _object(result["source"], fields, "governed evidence source")
    if source["kind"] != kind:
        raise ContractValidationError("governed source kind does not match event type")
    for field in fields - {"kind", "source_sha256"}:
        source[field] = _identifier(source[field], field)
    source["source_sha256"] = _hash(source["source_sha256"], "source_sha256")
    payload = _object(result["payload"], payload_fields, "governed evidence payload")
    doc = cls.from_mapping(payload[doc_key]); payload[doc_key] = doc.to_dict()
    if source[id_key] != getattr(doc, id_key) or source["source_sha256"] != sha256_bytes(doc.to_bytes()):
        raise ContractValidationError("governed source identity/hash mismatch")
    if doc_key in {"review", "study"}:
        for field in ("base_plan_event_id", "hypothesis_event_id", "intake_event_id"):
            payload[field] = _journal_id(payload[field], field)
    if doc_key == "review" and result["recorded_at"] != doc.recorded_at:
        raise ContractValidationError("risk review clock mismatch")
    if doc_key == "study":
        if source["experiment_id"] != doc.experiment_id or source["trial_id"] != doc.trial_registry["trial_id"]:
            raise ContractValidationError("reviewed study registry identity mismatch")
        if not evaluation and result["recorded_at"] != doc.registered_at:
            raise ContractValidationError("reviewed study clock mismatch")
        payload["risk_review_event_id"] = _journal_id(payload["risk_review_event_id"], "risk_review_event_id")
        for field in ("continuity_event_id", "cost_event_id"):
            if payload[field] is not None:
                payload[field] = _journal_id(payload[field], field)
        payload["implementation_evidence"] = _evidence(payload["implementation_evidence"])
        if not isinstance(payload["gate_assessment"], dict) or type(payload["gate_assessment"].get("eligible")) is not bool:
            raise ContractValidationError("reviewed evidence must declare exact gate eligibility")
    if evaluation:
        payload["study_event_id"] = _journal_id(payload["study_event_id"], "study_event_id")
        report = payload["result"]
        if (not isinstance(report, dict) or report.get("schema_version") != "blackpod.trading_shadow_reviewed_evaluation.v1"
                or report.get("study_id") != doc.study_id or report.get("mode") != "SHADOW_RESEARCH"
                or report.get("scope") != "DEVELOPMENT_TEST_ONLY" or report.get("auto_trading_enabled") is not False
                or "realized_trade_pnl" not in report or report["realized_trade_pnl"] is not None):
            raise ContractValidationError("reviewed result cannot claim orders, realized P&L or other scope")
        report["authority"] = disabled_authority(report.get("authority"))
        if not isinstance(payload["production"], dict) or payload["production"].get("auto_trading_enabled") is not False:
            raise ContractValidationError("reviewed production requires disabled automation")
        payload["production"]["authority"] = disabled_authority(payload["production"].get("authority"))
    result["source"], result["payload"], result["evidence"] = source, payload, _evidence(result["evidence"])
    return result


def _trading_shadow_event(result: dict[str, Any]) -> dict[str, Any]:
    from .trading_shadow_research import TradingShadowStudy
    from .investment_review import disabled_authority
    registration = result["event_type"] == "TRADING_SHADOW_STUDY_REGISTERED"
    if not registration and result["event_type"] != "TRADING_SHADOW_EVALUATION_RECORDED":
        raise ContractValidationError("journal v15 supports only governed shadow study records")
    if result["domain"] != "TRADING":
        raise ContractValidationError("shadow study requires TRADING domain")
    for field in ("event_id", "decision_id"):
        result[field] = _journal_id(result[field], field)
    result["recorded_at"] = normalize_rfc3339(result["recorded_at"], "recorded_at")
    fields = {"kind", "study_id", "experiment_id", "trial_id", "source_sha256"}
    if not registration:
        fields.add("evaluation_id")
    source = _object(result["source"], fields, "shadow study source")
    if source["kind"] != ("TRADING_SHADOW_STUDY" if registration else "TRADING_SHADOW_EVALUATION"):
        raise ContractValidationError("shadow study source kind mismatch")
    for field in fields - {"kind", "source_sha256"}:
        source[field] = _identifier(source[field], field)
    source["source_sha256"] = _hash(source["source_sha256"], "source_sha256")
    fields = {"study", "base_plan_event_id", "hypothesis_event_id", "intake_event_id", "gate_assessment", "implementation_evidence"}
    if not registration:
        fields |= {"study_event_id", "production", "result"}
    payload = _object(result["payload"], fields, "shadow study payload")
    study = TradingShadowStudy.from_mapping(payload["study"])
    if (source["study_id"] != study.study_id or source["experiment_id"] != study.experiment_id
            or source["trial_id"] != study.trial_registry["trial_id"] or source["source_sha256"] != sha256_bytes(study.to_bytes())):
        raise ContractValidationError("shadow study identity/hash mismatch")
    if registration and result["recorded_at"] != study.registered_at:
        raise ContractValidationError("shadow study registration clock mismatch")
    for field in ("base_plan_event_id", "hypothesis_event_id", "intake_event_id"):
        payload[field] = _journal_id(payload[field], field)
    if not isinstance(payload["gate_assessment"], dict) or type(payload["gate_assessment"].get("eligible")) is not bool:
        raise ContractValidationError("shadow gate assessment must explicitly declare eligibility")
    payload["implementation_evidence"] = _evidence(payload["implementation_evidence"])
    if not registration:
        payload["study_event_id"] = _journal_id(payload["study_event_id"], "study_event_id")
        report = payload["result"]
        if (not isinstance(report, dict) or report.get("schema_version") != "blackpod.trading_shadow_evaluation.v1"
                or report.get("study_id") != study.study_id or report.get("mode") != "SHADOW_RESEARCH"
                or report.get("scope") != "DEVELOPMENT_TEST_ONLY" or report.get("auto_trading_enabled") is not False
                or "realized_trade_pnl" not in report or report["realized_trade_pnl"] is not None):
            raise ContractValidationError("shadow result cannot claim orders, realized P&L or another scope")
        report["authority"] = disabled_authority(report.get("authority"))
        production = payload["production"]
        if not isinstance(production, dict) or production.get("auto_trading_enabled") is not False:
            raise ContractValidationError("shadow production requires disabled automation")
        production["authority"] = disabled_authority(production.get("authority"))
    payload["study"] = study.to_dict()
    result["source"], result["payload"], result["evidence"] = source, payload, _evidence(result["evidence"])
    return result


def _trading_intake_event(result: dict[str, Any]) -> dict[str, Any]:
    from .trading_hypothesis import TradingHypothesisCatalog
    from .historical_intake import HistoricalIntakeExport
    catalog = result["event_type"] == "TRADING_HYPOTHESIS_CATALOG_RECORDED"
    if not catalog and result["event_type"] != "TRADING_HISTORICAL_INTAKE_RECORDED":
        raise ContractValidationError("journal v13 supports only frozen hypotheses and retained history")
    if result["domain"] != "TRADING":
        raise ContractValidationError("research intake domain must be TRADING")
    for field in ("event_id", "decision_id"):
        result[field] = _journal_id(result[field], field)
    result["recorded_at"] = normalize_rfc3339(result["recorded_at"], "recorded_at")
    key, id_key = ("catalog", "catalog_id") if catalog else ("export", "intake_id")
    source = _object(result["source"], {"kind", id_key, "source_sha256"}, "research intake source")
    if source["kind"] != ("TRADING_HYPOTHESIS_CATALOG" if catalog else "TRADING_HISTORICAL_INTAKE"):
        raise ContractValidationError("research intake source kind mismatch")
    source[id_key] = _identifier(source[id_key], id_key)
    source["source_sha256"] = _hash(source["source_sha256"], "source_sha256")
    payload = _object(result["payload"], {key}, "research intake payload")
    cls = TradingHypothesisCatalog if catalog else HistoricalIntakeExport
    doc = cls.from_mapping(payload[key])
    if source[id_key] != getattr(doc, id_key) or source["source_sha256"] != sha256_bytes(doc.to_bytes()):
        raise ContractValidationError("research intake identity/hash mismatch")
    if catalog and result["recorded_at"] != doc.recorded_at:
        raise ContractValidationError("catalog clock mismatch")
    payload[key] = doc.to_dict()
    result["source"], result["payload"], result["evidence"] = source, payload, _evidence(result["evidence"])
    return result


def _trading_research_event(result: dict[str, Any], governed: bool = False) -> dict[str, Any]:
    from .trading_research import TradingResearchPlan
    from .investment_review import disabled_authority
    for field in ("event_id", "decision_id"):
        result[field] = _journal_id(result[field], field)
    if result["domain"] != "TRADING":
        raise ContractValidationError("offline trading research requires TRADING domain")
    result["recorded_at"] = normalize_rfc3339(result["recorded_at"], "recorded_at")
    registration = result["event_type"] == "TRADING_RESEARCH_PLAN_REGISTERED"
    if not registration and result["event_type"] != "TRADING_RESEARCH_EVALUATION_RECORDED":
        raise ContractValidationError("journal v12 supports only offline research registration/evaluation")
    fields = {"kind", "plan_id", "experiment_id", "trial_id", "source_sha256"}
    if not registration:
        fields.add("evaluation_id")
    source = _object(result["source"], fields, "offline research source")
    expected_kind = "TRADING_RESEARCH_PLAN" if registration else "TRADING_RESEARCH_EVALUATION"
    if source["kind"] != expected_kind:
        raise ContractValidationError("offline research source kind differs from event type")
    for field in fields - {"kind", "source_sha256"}:
        source[field] = _identifier(source[field], field)
    source["source_sha256"] = _hash(source["source_sha256"], "source_sha256")
    payload_fields = {"plan"} if registration else {"plan", "plan_event_id", "result"}
    if governed:
        payload_fields |= {"hypothesis_event_id", "intake_event_id"}
    payload = _object(result["payload"], payload_fields, "offline research payload")
    plan = TradingResearchPlan.from_mapping(payload["plan"])
    if plan.schema_version != ("blackpod.trading_research_plan.v2" if governed else "blackpod.trading_research_plan.v1"):
        raise ContractValidationError("journal research version differs from plan version")
    if governed:
        for field in ("hypothesis_event_id", "intake_event_id"):
            payload[field] = _journal_id(payload[field], field)
    if (source["plan_id"] != plan.plan_id or source["experiment_id"] != plan.experiment_id
            or source["trial_id"] != plan.trial_registry["trial_id"] or source["source_sha256"] != sha256_bytes(plan.to_bytes())):
        raise ContractValidationError("offline research identity/hash differs from its plan")
    if registration and result["recorded_at"] != plan.registered_at:
        raise ContractValidationError("registration clock differs from its declared plan")
    if not registration:
        payload["plan_event_id"] = _journal_id(payload["plan_event_id"], "plan_event_id")
        report = payload["result"]
        if not isinstance(report, dict) or report.get("schema_version") != ("blackpod.trading_research_evaluation.v2" if governed else "blackpod.trading_research_evaluation.v1"):
            raise ContractValidationError("unsupported offline research result")
        if (report.get("plan_id") != plan.plan_id or report.get("experiment_id") != plan.experiment_id
                or report.get("trial_id") != source["trial_id"] or report.get("mode") != "OFFLINE_SIMULATION"
                or report.get("scope") != "DEVELOPMENT_EVALUATION_ONLY" or report.get("auto_trading_enabled") is not False
                or "realized_trade_pnl" not in report or report["realized_trade_pnl"] is not None):
            raise ContractValidationError("offline result cannot claim execution, P&L or another research scope")
        report["authority"] = disabled_authority(report.get("authority"))
    payload["plan"] = plan.to_dict()
    result["source"], result["payload"], result["evidence"] = source, payload, _evidence(result["evidence"])
    return result


def _forecast_producer_event(result: dict[str, Any]) -> dict[str, Any]:
    from .forecast_producer import ForecastProducerRequest, validate_forecast_producer_export
    if result["event_type"] != "FORECAST_PRODUCER_EXPORT_RECORDED" or result["domain"] != "TRADING":
        raise ContractValidationError("journal v10 records only passive TRADING producer exports")
    for field in ("event_id", "decision_id"):
        result[field] = _journal_id(result[field], field)
    result["recorded_at"] = normalize_rfc3339(result["recorded_at"], "recorded_at")
    source = _object(result["source"], {"kind", "run_id", "source_sha256"}, "producer source")
    if source["kind"] != "FORECAST_PRODUCER_EXPORT":
        raise ContractValidationError("producer source kind differs from event type")
    source["run_id"] = _identifier(source["run_id"], "run_id")
    source["source_sha256"] = _hash(source["source_sha256"], "source_sha256")
    payload = _object(result["payload"], {"request", "export"}, "producer payload")
    request = ForecastProducerRequest.from_mapping(payload["request"])
    export = validate_forecast_producer_export(payload["export"], request)
    if source["run_id"] != request.run_id or source["source_sha256"] != sha256_bytes(request.to_bytes()) or result["recorded_at"] != export["issued_at"]:
        raise ContractValidationError("producer event identity, input hash or issue time differs")
    result["payload"], result["source"], result["evidence"] = {"request": request.to_dict(), "export": export}, source, _evidence(result["evidence"])
    return result


def _forecast_brigade_event(result: dict[str, Any], *, structured=False) -> dict[str, Any]:
    from .forecast_intake import ForecastIntake, validate_forecast_result
    from .brigade_shadow import BrigadeShadowRequest
    from .investment_review import disabled_authority

    supported = {"BRIGADE_SHADOW_ANALYSIS_RECORDED"} if structured else {"FORECAST_INTAKE_RECORDED", "BRIGADE_SHADOW_ANALYSIS_RECORDED"}
    result["event_type"] = _enum(result["event_type"], supported, "event_type")
    kind, identity_field, input_key, output_key, document_type = {
        "FORECAST_INTAKE_RECORDED": ("FORECAST_INTAKE", "intake_id", "intake", "result", ForecastIntake),
        "BRIGADE_SHADOW_ANALYSIS_RECORDED": ("BRIGADE_SHADOW_ANALYSIS", "analysis_id", "request", "analysis", BrigadeShadowRequest),
    }.get(result["event_type"], (None, None, None, None, None))
    if kind is None:
        raise ContractValidationError("journal v9 requires a forecast or Brigade shadow event")
    for key in ("event_id", "decision_id"):
        result[key] = _journal_id(result[key], key)
    result["recorded_at"] = normalize_rfc3339(result["recorded_at"], "recorded_at")
    result["domain"] = _enum(result["domain"], {"TRADING", "INVESTMENT"}, "domain")
    source = _object(result["source"], {"kind", identity_field, "source_sha256"}, "source")
    if source["kind"] != kind:
        raise ContractValidationError("forecast/Brigade source kind differs from its event type")
    source[identity_field] = _identifier(source[identity_field], identity_field)
    source["source_sha256"] = _hash(source["source_sha256"], "source_sha256")
    payload = _object(result["payload"], {input_key, output_key}, "forecast/Brigade payload")
    document = document_type.from_mapping(payload[input_key])
    if kind == "BRIGADE_SHADOW_ANALYSIS" and document.schema_version != (
            "blackpod.brigade_shadow_request.v2" if structured else "blackpod.brigade_shadow_request.v1"):
        raise ContractValidationError("Brigade request version differs from its journal event version")
    if result["domain"] != document.domain or result["recorded_at"] != document.recorded_at:
        raise ContractValidationError("forecast/Brigade domain and time must match the submitted input")
    if source[identity_field] != getattr(document, identity_field) or source["source_sha256"] != sha256_bytes(document.to_bytes()):
        raise ContractValidationError("forecast/Brigade source identity or hash differs from submitted input")
    payload[input_key] = document.to_dict()
    if kind == "FORECAST_INTAKE":
        payload[output_key] = validate_forecast_result(payload[output_key], document)
    else:
        fields = {"schema_version", "generated_at", "mode", "domain", "context_policy_version", "requested_symbols",
            "forecast_intake_evidence", "forecast_result", "market_source", "source_evidence", "runtime_fingerprint", "response_capture_status",
            "response_transcripts", "symbols", "limitations", "authority", "auto_trading_enabled"}
        if structured:
            fields.add("response_contract")
        packet = _object(payload[output_key], fields, "Brigade packet")
        if structured and packet["response_contract"] != document.response_contract:
            raise ContractValidationError("Brigade response contract differs from its request")
        if (packet["schema_version"] != ("blackpod.shadow_brigade_analysis.v2" if structured else "blackpod.shadow_brigade_analysis.v1") or packet["mode"] != "SHADOW" or packet["domain"] != "TRADING"
                or packet["generated_at"] != document.generated_at or packet["requested_symbols"] != document.symbols):
            raise ContractValidationError("Brigade packet does not match its shadow request")
        packet["authority"] = disabled_authority(packet["authority"])
        if packet["auto_trading_enabled"] is not False:
            raise ContractValidationError("Brigade cannot enable automated trading")
        expected_mode = "INFERENCE_DISABLED" if document.inference_mode == "DISABLED" else "RETAINED_RESPONSES"
        if packet["response_capture_status"] != expected_mode:
            raise ContractValidationError("Brigade response mode differs from its request")
        payload[output_key] = packet  # Full retained-source replay occurs in JournalStore.
    result["source"], result["payload"], result["evidence"] = source, payload, _evidence(result["evidence"])
    return result


def _desk_candidate_review_event(result: dict[str, Any]) -> dict[str, Any]:
    from .desk_candidate_review import DeskReviewInput, validate_review_result

    if result["event_type"] != SHADOW_DESK_REVIEW_EVENT_TYPE:
        raise ContractValidationError("journal event v8 supports only SHADOW_DESK_REVIEW_RECORDED")
    if result["domain"] != "CAPITAL_ALLOCATION":
        raise ContractValidationError("a two-desk research proposal requires CAPITAL_ALLOCATION domain")
    for field in ("event_id", "decision_id"):
        result[field] = _journal_id(result[field], field)
    result["recorded_at"] = normalize_rfc3339(result["recorded_at"], "recorded_at")
    source = _object(result["source"], {"kind", "review_id", "source_sha256"}, "source")
    if source["kind"] != "SHADOW_DESK_REVIEW":
        raise ContractValidationError("two-desk research source.kind does not match event_type")
    source["review_id"] = _identifier(source["review_id"], "source.review_id")
    source["source_sha256"] = _hash(source["source_sha256"], "source.source_sha256")
    result["source"] = source
    result["evidence"] = _evidence(result["evidence"])
    payload = _object(result["payload"], {"review", "result"}, "two-desk research payload")
    document = DeskReviewInput.from_mapping(payload["review"])
    payload["review"] = document.to_dict()
    payload["result"] = validate_review_result(payload["result"], document)
    if source["review_id"] != document.review_id or source["source_sha256"] != sha256_bytes(document.to_bytes()):
        raise ContractValidationError("two-desk research source identity or hash does not match supplied input")
    if result["recorded_at"] != document.recorded_at:
        raise ContractValidationError("two-desk research recorded_at must match event")
    result["payload"] = payload
    return result


def _trading_accounting_event(result: dict[str, Any]) -> dict[str, Any]:
    from .trading_accounting import AccountingInput, validate_accounting_result

    if result["event_type"] != TRADING_FILL_LOT_ACCOUNTING_EVENT_TYPE:
        raise ContractValidationError("journal event v7 supports only TRADING_FILL_LOT_ACCOUNTING_RECORDED")
    if result["domain"] != "TRADING":
        raise ContractValidationError("PAPER fill-lot accounting requires TRADING domain")
    for field in ("event_id", "decision_id"):
        result[field] = _journal_id(result[field], field)
    result["recorded_at"] = normalize_rfc3339(result["recorded_at"], "recorded_at")
    source = _object(result["source"], {"kind", "accounting_id", "source_sha256"}, "source")
    if source["kind"] != "TRADING_FILL_LOT_ACCOUNTING":
        raise ContractValidationError("PAPER fill-lot accounting source.kind does not match event_type")
    source["accounting_id"] = _identifier(source["accounting_id"], "source.accounting_id")
    source["source_sha256"] = _hash(source["source_sha256"], "source.source_sha256")
    result["source"] = source
    result["evidence"] = _evidence(result["evidence"])
    payload = _object(result["payload"], {"accounting", "result"}, "PAPER fill-lot accounting payload")
    document = AccountingInput.from_mapping(payload["accounting"])
    payload["accounting"] = document.to_dict()
    payload["result"] = validate_accounting_result(payload["result"], document)
    if source["accounting_id"] != document.accounting_id or source["source_sha256"] != sha256_bytes(document.to_bytes()):
        raise ContractValidationError("PAPER fill-lot accounting source identity or hash does not match supplied input")
    if result["recorded_at"] != document.recorded_at:
        raise ContractValidationError("PAPER fill-lot accounting recorded_at must match event")
    result["payload"] = payload
    return result


def _trading_reconciliation_event(result: dict[str, Any]) -> dict[str, Any]:
    from .trading_reconciliation import (
        BrokerSnapshotInput, DeskOwnershipInput, ReconciliationInput,
        validate_snapshot_assessment, validate_ownership_assessment, validate_reconciliation_result,
    )
    kinds = {
        PAPER_BROKER_SNAPSHOT_EVENT_TYPE: ("PAPER_BROKER_SNAPSHOT", "snapshot_id", "snapshot", "assessment", "captured_at", BrokerSnapshotInput, validate_snapshot_assessment),
        TRADING_DESK_OWNERSHIP_EVENT_TYPE: ("TRADING_DESK_OWNERSHIP", "ownership_id", "ownership", "assessment", "recorded_at", DeskOwnershipInput, validate_ownership_assessment),
        TRADING_EXECUTION_RECONCILED_EVENT_TYPE: ("TRADING_EXECUTION_RECONCILIATION", "reconciliation_id", "reconciliation", "result", "recorded_at", ReconciliationInput, validate_reconciliation_result),
    }
    result["event_type"] = _enum(result["event_type"], set(kinds), "journal event v6 event_type")
    if result["domain"] != "TRADING":
        raise ContractValidationError("PAPER reconciliation event requires TRADING domain")
    for field in ("event_id", "decision_id"):
        result[field] = _journal_id(result[field], field)
    result["recorded_at"] = normalize_rfc3339(result["recorded_at"], "recorded_at")
    kind, identity, document_key, report_key, timestamp_key, contract, validator = kinds[result["event_type"]]
    source = _object(result["source"], {"kind", identity, "source_sha256"}, "source")
    if source["kind"] != kind:
        raise ContractValidationError("PAPER reconciliation source.kind does not match event_type")
    source[identity] = _identifier(source[identity], "source." + identity)
    source["source_sha256"] = _hash(source["source_sha256"], "source.source_sha256")
    result["source"] = source
    result["evidence"] = _evidence(result["evidence"])
    payload = _object(result["payload"], {document_key, report_key}, "PAPER reconciliation payload")
    document = contract.from_mapping(payload[document_key])
    payload[document_key] = document.to_dict()
    payload[report_key] = validator(payload[report_key], document)
    if source[identity] != getattr(document, identity) or source["source_sha256"] != sha256_bytes(document.to_bytes()):
        raise ContractValidationError("PAPER reconciliation source identity or hash does not match supplied input")
    if result["recorded_at"] != getattr(document, timestamp_key):
        raise ContractValidationError("PAPER reconciliation timestamp must match event")
    result["payload"] = payload
    return result


def _automation_event(result: dict[str, Any]) -> dict[str, Any]:
    # A separate version and TRADING domain cannot inherit investment scope.
    from .trading_automation import TradingAutomationControl, validate_automation_status

    if result["event_type"] != TRADING_AUTOMATION_SWITCH_EVENT_TYPE:
        raise ContractValidationError("journal event v5 supports only TRADING_AUTOMATION_SWITCH_RECORDED")
    if result["domain"] != "TRADING":
        raise ContractValidationError("trading automation control requires TRADING domain")
    for field in ("event_id", "decision_id"):
        result[field] = _journal_id(result[field], field)
    result["recorded_at"] = normalize_rfc3339(result["recorded_at"], "recorded_at")
    source = _object(result["source"], {"kind", "control_id", "source_sha256"}, "source")
    if source["kind"] != "TRADING_AUTOMATION_CONTROL":
        raise ContractValidationError("automation source.kind must be TRADING_AUTOMATION_CONTROL")
    source["control_id"] = _identifier(source["control_id"], "source.control_id")
    source["source_sha256"] = _hash(source["source_sha256"], "source.source_sha256")
    result["source"] = source
    result["evidence"] = _evidence(result["evidence"])
    payload = _object(result["payload"], {"control", "status"}, "trading automation payload")
    document = TradingAutomationControl.from_mapping(payload["control"])
    payload["control"] = document.to_dict()
    payload["status"] = validate_automation_status(payload["status"], document)
    if source["control_id"] != document.control_id or source["source_sha256"] != sha256_bytes(document.to_bytes()):
        raise ContractValidationError("automation source identity or hash does not match supplied control")
    if result["recorded_at"] != document.recorded_at:
        raise ContractValidationError("automation recorded_at must match event")
    result["payload"] = payload
    return result


def _governance_event(result: dict[str, Any]) -> dict[str, Any]:
    # Additive dispatch prevents governance from broadening historical versions.
    from .investment_governance import (
        ApprovalInput, ProposalInput, validate_approval_decision, validate_proposal_report,
    )

    kinds = {
        INVESTMENT_DECISION_PROPOSAL_EVENT_TYPE: ("INVESTMENT_DECISION_PROPOSAL", "proposal_id", "proposal", "report", ProposalInput, validate_proposal_report),
        INVESTMENT_SHADOW_APPROVAL_EVENT_TYPE: ("INVESTMENT_SHADOW_APPROVAL", "approval_id", "approval", "decision", ApprovalInput, validate_approval_decision),
    }
    result["event_type"] = _enum(result["event_type"], set(kinds), "journal event v4 event_type")
    if result["domain"] != "INVESTMENT":
        raise ContractValidationError("investment governance event requires INVESTMENT domain")
    for field in ("event_id", "decision_id"):
        result[field] = _journal_id(result[field], field)
    result["recorded_at"] = normalize_rfc3339(result["recorded_at"], "recorded_at")
    kind, identity, document_key, report_key, contract, report_validator = kinds[result["event_type"]]
    source = _object(result["source"], {"kind", identity, "source_sha256"}, "source")
    if source["kind"] != kind:
        raise ContractValidationError("investment governance source.kind does not match event_type")
    source[identity] = _identifier(source[identity], "source." + identity)
    source["source_sha256"] = _hash(source["source_sha256"], "source.source_sha256")
    result["source"] = source
    result["evidence"] = _evidence(result["evidence"])
    payload = _object(result["payload"], {document_key, report_key}, "investment governance payload")
    document = contract.from_mapping(payload[document_key])
    payload[document_key] = document.to_dict()
    payload[report_key] = report_validator(payload[report_key], document)
    if source[identity] != getattr(document, identity) or source["source_sha256"] != sha256_bytes(document.to_bytes()):
        raise ContractValidationError("investment governance source identity or hash does not match supplied input")
    if result["recorded_at"] != document.recorded_at:
        raise ContractValidationError("investment governance recorded_at must match event")
    result["payload"] = payload
    return result


def _hypothesis_event(result: dict[str, Any]) -> dict[str, Any]:
    # Lazy import keeps the independent hypothesis contract free to reuse the
    # established immutable document and primitive validators above.
    from .investment_hypothesis import InvestmentHypothesis

    if result["event_type"] != INVESTMENT_HYPOTHESIS_EVENT_TYPE:
        raise ContractValidationError("journal event v2 supports only INVESTMENT_HYPOTHESIS_RECORDED")
    if result["domain"] != "INVESTMENT":
        raise ContractValidationError("investment hypothesis event requires INVESTMENT domain")
    for field in ("event_id", "decision_id"):
        result[field] = _journal_id(result[field], field)
    result["recorded_at"] = normalize_rfc3339(result["recorded_at"], "recorded_at")
    source = _object(result["source"], {"kind", "hypothesis_id", "source_sha256"}, "source")
    if source["kind"] != "INVESTMENT_HYPOTHESIS":
        raise ContractValidationError("hypothesis source.kind must be INVESTMENT_HYPOTHESIS")
    source["hypothesis_id"] = _identifier(source["hypothesis_id"], "source.hypothesis_id")
    source["source_sha256"] = _hash(source["source_sha256"], "source.source_sha256")
    result["source"] = source
    result["evidence"] = _evidence(result["evidence"])
    payload = InvestmentHypothesis.from_mapping(result["payload"]).to_dict()
    if source["hypothesis_id"] != payload["hypothesis_id"] or source["source_sha256"] != sha256_bytes(canonical_json_bytes(payload)):
        raise ContractValidationError("hypothesis source identity or hash does not match payload")
    if result["recorded_at"] != payload["recorded_at"]:
        raise ContractValidationError("hypothesis recorded_at must match event")
    result["payload"] = payload
    return result


def _review_event(result: dict[str, Any]) -> dict[str, Any]:
    # Version-specific dispatch leaves historical v1 and v2 schemas unchanged.
    from .investment_review import (
        ChallengeInput, OutcomeEvaluationInput,
        validate_challenge_assessment, validate_outcome_result,
    )

    kinds = {
        INVESTMENT_CHALLENGE_EVENT_TYPE: ("INVESTMENT_CHALLENGE", "challenge_id", "challenge", "assessment", ChallengeInput, validate_challenge_assessment),
        INVESTMENT_OUTCOME_EVALUATION_EVENT_TYPE: ("INVESTMENT_OUTCOME_EVALUATION", "evaluation_id", "evaluation", "result", OutcomeEvaluationInput, validate_outcome_result),
    }
    result["event_type"] = _enum(result["event_type"], set(kinds), "journal event v3 event_type")
    if result["domain"] != "INVESTMENT":
        raise ContractValidationError("investment review event requires INVESTMENT domain")
    for field in ("event_id", "decision_id"):
        result[field] = _journal_id(result[field], field)
    result["recorded_at"] = normalize_rfc3339(result["recorded_at"], "recorded_at")
    kind, identity, document_key, report_key, contract, report_validator = kinds[result["event_type"]]
    source = _object(result["source"], {"kind", identity, "source_sha256"}, "source")
    if source["kind"] != kind:
        raise ContractValidationError("investment review source.kind does not match event_type")
    source[identity] = _identifier(source[identity], "source." + identity)
    source["source_sha256"] = _hash(source["source_sha256"], "source.source_sha256")
    result["source"] = source
    result["evidence"] = _evidence(result["evidence"])
    payload = _object(result["payload"], {document_key, report_key}, "investment review payload")
    document = contract.from_mapping(payload[document_key])
    payload[document_key] = document.to_dict()
    payload[report_key] = report_validator(payload[report_key], document)
    if source[identity] != getattr(document, identity) or source["source_sha256"] != sha256_bytes(document.to_bytes()):
        raise ContractValidationError("investment review source identity or hash does not match supplied input")
    if result["recorded_at"] != document.recorded_at:
        raise ContractValidationError("investment review recorded_at must match event")
    result["payload"] = payload
    return result


@dataclass(frozen=True, slots=True, init=False)
class _ImmutableDocument:
    """Retain canonical bytes; callers receive fresh copies of validated fields."""

    _canonical_bytes: bytes
    _canonical_fields: tuple[tuple[str, bytes], ...] = field(repr=False, compare=False)
    _validator: ClassVar[Any]

    def __init__(self, value: Mapping[str, Any]) -> None:
        validated = self._validator(value)
        object.__setattr__(self, "_canonical_bytes", canonical_json_bytes(validated))
        # Bind these immutable fragments to the canonical document, rather
        # than retaining a mutable decoded object or the caller's input.
        object.__setattr__(self, "_canonical_fields", tuple(
            (name, canonical_json_bytes(item)) for name, item in
            json.loads(self._canonical_bytes).items()))

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]):
        return cls(value)

    @classmethod
    def from_bytes(cls, value: bytes):
        return cls.from_mapping(parse_strict_json_object_bytes(value, document_name=cls.__name__))

    def to_dict(self) -> dict[str, Any]:
        return json.loads(self._canonical_bytes)

    def to_mapping(self) -> dict[str, Any]:
        return self.to_dict()

    def to_bytes(self) -> bytes:
        return self._canonical_bytes

    def __getstate__(self):
        # Keep the original one-slot pickle representation. Field fragments
        # are an internal optimization, never persisted as authoritative data.
        return [self._canonical_bytes]

    def __setstate__(self, state):
        if not isinstance(state, (list, tuple)) or len(state) not in {1, 2} or not isinstance(state[0], bytes):
            raise TypeError("immutable document pickle state requires canonical bytes")
        raw = state[0]
        fields = tuple((name, canonical_json_bytes(item)) for name, item in json.loads(raw).items())
        object.__setattr__(self, "_canonical_bytes", raw)
        object.__setattr__(self, "_canonical_fields", fields)

    def __getattr__(self, name: str) -> Any:
        if name.startswith("_"):
            raise AttributeError(name)
        try:
            fields = object.__getattribute__(self, "_canonical_fields")
        except AttributeError:
            # Older Python pickle state contains only the canonical document.
            # Rebuild the immutable optimization without changing that state.
            fields = tuple((key, canonical_json_bytes(item)) for key, item in
                json.loads(self._canonical_bytes).items())
            object.__setattr__(self, "_canonical_fields", fields)
        for field_name, raw in fields:
            if field_name == name:
                return json.loads(raw)
        raise AttributeError(name)


class JournalEvent(_ImmutableDocument):
    """Versioned passive records, research drafts, reviews, or SHADOW governance."""

    __slots__ = ()
    _validator = staticmethod(_event)

    def __init__(self, value: Mapping[str, Any]) -> None:
        try:
            super().__init__(value)
        except (RecursionError, ValueError) as exc:
            if isinstance(exc, ContractValidationError):
                raise
            raise ContractValidationError("journal event nesting or numeric representation exceeds supported limits") from exc

    @classmethod
    def from_bytes(cls, value: bytes):
        """Bound malformed JSON parser failures without changing valid events."""
        try:
            parsed = parse_strict_json_object_bytes(value, document_name=cls.__name__)
        except (RecursionError, ValueError) as exc:
            if isinstance(exc, ContractValidationError):
                raise
            raise ContractValidationError("journal event JSON nesting or numeric representation exceeds supported limits") from exc
        return cls.from_mapping(parsed)


class EvaluationInput(_ImmutableDocument):
    """Human-supplied outcome observation; journal linkage adds execution checks."""

    __slots__ = ()
    _validator = staticmethod(_evaluation)


class CapitalPolicyProposal(_ImmutableDocument):
    """Inactive initial 50/50 desk allocation, never an automatic rebalance."""

    __slots__ = ()
    _validator = staticmethod(_capital_policy)
