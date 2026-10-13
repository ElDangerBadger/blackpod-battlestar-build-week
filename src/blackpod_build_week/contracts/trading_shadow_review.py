"""V2 shadow declarations bind adapter evidence and an independent risk review.

The v1 calculation contracts and implementation files remain frozen. All new
authority remains off; an approved review changes simulation inputs only.
"""
from .decision_journal import _object
from .mission_request import ContractValidationError
from .trading_reconciliation import _ReconciliationDocument, evidence_reference
from .trading_shadow_research import TradingShadowStudy

SHADOW_REVIEW_STUDY_VERSION = "blackpod.trading_shadow_study.v2"


def _study(value):
    old_fields = {"schema_version", "study_id", "experiment_id", "registered_at", "domain", "mode", "scope",
        "base_plan_evidence", "sizing", "benchmark", "cost_stress_multipliers", "trial_registry",
        "evidence_scope", "auto_trading_enabled", "authority"}
    new_fields = {"continuity_intake_evidence", "cost_intake_evidence", "risk_review_evidence"}
    row = _object(value, old_fields | new_fields, "reviewed shadow study")
    if row["schema_version"] != SHADOW_REVIEW_STUDY_VERSION:
        raise ContractValidationError("unsupported reviewed shadow study version")
    base = {key: item for key, item in row.items() if key not in new_fields}
    base["schema_version"] = "blackpod.trading_shadow_study.v1"
    base["price_continuity_evidence"] = base["cost_evidence"] = None
    normalized = TradingShadowStudy.from_mapping(base).to_dict()
    normalized.pop("price_continuity_evidence"); normalized.pop("cost_evidence")
    normalized["schema_version"] = SHADOW_REVIEW_STUDY_VERSION
    for field in new_fields:
        normalized[field] = None if row[field] is None and field != "risk_review_evidence" else evidence_reference(row[field], field)
    paths = [normalized[field]["path"] for field in ("base_plan_evidence", *sorted(new_fields)) if normalized[field] is not None]
    if len(paths) != len(set(paths)):
        raise ContractValidationError("reviewed study source paths must be distinct")
    return normalized


class ReviewedShadowStudy(_ReconciliationDocument):
    __slots__ = ()
    _validator = staticmethod(_study)
