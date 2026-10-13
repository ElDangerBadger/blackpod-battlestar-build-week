"""Frozen evidence-qualification designs, never live trading policies."""
from decimal import Decimal

from .decision_journal import _object, _identifier, _enum, _ImmutableDocument, _evidence, _string
from .investment_review import disabled_authority, _event_id, _fixed_boolean
from .mission_request import ContractValidationError, parse_rfc3339
from .trading_accounting import accounting_timestamp
from .trading_research import _decimal, _integer
from .trading_reconciliation import evidence_reference

POLICY_VERSION = "blackpod.trading_evidence_qualification_policy.v1"
ASSUMPTIONS_VERSION = "blackpod.trading_training_assumptions.v1"
REQUEST_VERSION = "blackpod.trading_evidence_qualification_request.v1"
JOURNAL_VERSION = "blackpod.decision_journal_event.v18"
POLICY_TYPE = "TRADING_EVIDENCE_QUALIFICATION_POLICY_RECORDED"
ASSESSMENT_TYPE = "TRADING_EVIDENCE_QUALIFICATION_RECORDED"
STATUSES = frozenset({"PROPOSED", "REVIEWED_FOR_SHADOW_QUALIFICATION", "REJECTED"})
EVIDENCE_SCOPES = frozenset({"SYNTHETIC_FIXTURE_ONLY", "RETAINED_HISTORY_RESEARCH"})
CONTINUITY_POLICY = "RAW_PRICE_BOUNDARY_SUSPENSION_NO_ADJUSTMENT"
COST_POLICY = "PER_FOLD_TRAIN_ONLY_MAX_SPREAD_NO_CLIPPING"


def _constant(row, field, expected):
    if row[field] != expected or type(row[field]) is not type(expected):
        raise ContractValidationError(field + " must equal " + repr(expected))


def _refs(value, name):
    if not isinstance(value, list) or not 1 <= len(value) <= 64:
        raise ContractValidationError(name + " requires a nonempty bounded list")
    return _evidence(value)


def _safe(row):
    _fixed_boolean(row, "auto_trading_enabled", False)
    row["authority"] = disabled_authority(row["authority"])
    return row


def uncertainty_protocol(value):
    """A declared future evaluation protocol; no inference is performed here."""
    row = _object(value, {"method_version", "method", "metric", "resampling_unit", "block_length_sessions", "replications", "seed", "confidence_level", "minimum_evaluation_sessions", "minimum_development_folds", "minimum_supported_fold_fraction", "support_rule", "cost_stress_multipliers", "holdout_scoring", "parameter_search_allowed", "multiple_trials_policy"}, "uncertainty protocol")
    for field, expected in {
        "method_version": "blackpod.paired_session_uncertainty_plan.v1",
        "method": "MOVING_BLOCK_BOOTSTRAP_PAIRED_SESSION_NET_CASHFLOWS",
        "metric": "NET_EXCESS_OVER_CASH_AND_MATCHED_CONTROL",
        "resampling_unit": "RETURNED_SESSION_BLOCK_ALL_SYMBOLS_PAIRED",
        "support_rule": "POSITIVE_LOWER_BOUND_FOR_BOTH_BENCHMARKS_AT_ALL_STRESSES_AND_DECLARED_STABILITY",
        "cost_stress_multipliers": ["1", "2", "4"], "holdout_scoring": "WITHHELD",
        "parameter_search_allowed": False,
        "multiple_trials_policy": "ALL_REGISTERED_TRIALS_DISCLOSED_NO_WINNER_SELECTION",
    }.items(): _constant(row, field, expected)
    for field, lower, upper in (("block_length_sessions", 1, 10000), ("replications", 1, 100000), ("seed", 0, 4294967295), ("minimum_evaluation_sessions", 2, 10000), ("minimum_development_folds", 1, 32)):
        row[field] = _integer(row[field], field, lower, upper)
    row["confidence_level"] = _decimal(row["confidence_level"], "confidence_level", positive=True, maximum=Decimal("1"))
    if not Decimal("0.5") < Decimal(row["confidence_level"]) < 1:
        raise ContractValidationError("confidence level must be strictly between 0.5 and 1")
    row["minimum_supported_fold_fraction"] = _decimal(row["minimum_supported_fold_fraction"], "minimum_supported_fold_fraction", positive=True, maximum=Decimal("1"))
    return row


def _policy(value):
    row = _object(value, {"schema_version", "policy_id", "recorded_at", "domain", "mode", "scope", "status", "base_plan_event_id", "base_plan_evidence", "dataset_evidence", "hypothesis_evidence", "continuity_event_id", "cost_event_id", "risk_review_event_id", "training_quote_chains", "training_cost_assumptions_evidence", "evidence_scope", "continuity_policy", "cost_policy", "uncertainty_protocol", "supporting_evidence", "reviewer_id", "review_notes", "supersedes_policy_event_id", "auto_trading_enabled", "authority"}, "qualification policy")
    for field, expected in {"schema_version": POLICY_VERSION, "domain": "TRADING", "mode": "SHADOW_RESEARCH", "scope": "DEVELOPMENT_EVIDENCE_QUALIFICATION_ONLY", "continuity_policy": CONTINUITY_POLICY, "cost_policy": COST_POLICY}.items(): _constant(row, field, expected)
    for field in ("policy_id", "reviewer_id"): row[field] = _identifier(row[field], field)
    row["recorded_at"] = accounting_timestamp(row["recorded_at"], "recorded_at")
    row["status"] = _enum(row["status"], STATUSES, "status")
    row["evidence_scope"] = _enum(row["evidence_scope"], EVIDENCE_SCOPES, "evidence_scope")
    row["base_plan_event_id"] = _event_id(row["base_plan_event_id"], "base_plan_event_id")
    for field in ("continuity_event_id", "cost_event_id", "risk_review_event_id", "supersedes_policy_event_id"):
        if row[field] is not None: row[field] = _event_id(row[field], field)
    for field in ("base_plan_evidence", "dataset_evidence", "hypothesis_evidence"):
        row[field] = evidence_reference(row[field], field)
    if row["training_cost_assumptions_evidence"] is not None:
        row["training_cost_assumptions_evidence"] = evidence_reference(row["training_cost_assumptions_evidence"], "training_cost_assumptions_evidence")
    chains = row["training_quote_chains"]
    if not isinstance(chains, list) or len(chains) > 32:
        raise ContractValidationError("training quote chains must be a bounded list")
    result, ids = [], set()
    for chain in chains:
        chain = _object(chain, {"fold_id", "pages"}, "training quote chain")
        chain["fold_id"] = _identifier(chain["fold_id"], "fold_id")
        if chain["fold_id"] in ids: raise ContractValidationError("duplicate training fold chain")
        ids.add(chain["fold_id"])
        if not isinstance(chain["pages"], list) or len(chain["pages"]) > 128:
            raise ContractValidationError("training pages must be a bounded list")
        pages = []
        for page in chain["pages"]:
            page = _object(page, {"body_evidence", "receipt_evidence"}, "training quote page")
            pages.append({field: evidence_reference(ref, field) for field, ref in page.items()})
        chain["pages"] = pages; result.append(chain)
    row["training_quote_chains"] = result
    row["supporting_evidence"] = _refs(row["supporting_evidence"], "supporting_evidence")
    if row["uncertainty_protocol"] is not None: row["uncertainty_protocol"] = uncertainty_protocol(row["uncertainty_protocol"])
    row["review_notes"] = _string(row["review_notes"], "review_notes", 10000)
    return _safe(row)


def _assumptions(value):
    row = _object(value, {"schema_version", "assumptions_id", "recorded_at", "base_plan_evidence", "dataset_evidence", "evidence_scope", "status", "parameters", "capacity", "origin_evidence", "reviewer_id", "review_notes", "auto_trading_enabled", "authority"}, "training assumptions")
    _constant(row, "schema_version", ASSUMPTIONS_VERSION)
    for field in ("assumptions_id", "reviewer_id"): row[field] = _identifier(row[field], field)
    row["recorded_at"] = accounting_timestamp(row["recorded_at"], "recorded_at")
    for field in ("base_plan_evidence", "dataset_evidence"): row[field] = evidence_reference(row[field], field)
    row["evidence_scope"] = _enum(row["evidence_scope"], EVIDENCE_SCOPES, "evidence_scope")
    row["status"] = _enum(row["status"], {"REVIEWED_FOR_SHADOW_QUALIFICATION", "UNRESOLVED"}, "status")
    if row["parameters"] is not None:
        params = _object(row["parameters"], {"slippage_bps", "fee_bps", "fee_per_fill"}, "training cost parameters")
        for field in params:
            params[field] = _decimal(params[field], field, maximum=Decimal("1000") if field != "fee_per_fill" else None)
        row["parameters"] = params
    if row["capacity"] is not None:
        capacity = _object(row["capacity"], {"max_daily_volume_participation_fraction"}, "capacity")
        capacity["max_daily_volume_participation_fraction"] = _decimal(capacity["max_daily_volume_participation_fraction"], "max_daily_volume_participation_fraction", positive=True, maximum=Decimal("1"))
        row["capacity"] = capacity
    if row["status"] == "REVIEWED_FOR_SHADOW_QUALIFICATION" and (row["parameters"] is None or row["capacity"] is None):
        raise ContractValidationError("reviewed training assumptions require explicit cost and capacity parameters")
    row["origin_evidence"] = _refs(row["origin_evidence"], "origin_evidence")
    row["review_notes"] = _string(row["review_notes"], "review_notes", 10000)
    return _safe(row)


def _request(value):
    row = _object(value, {"schema_version", "qualification_id", "policy_event_id", "recorded_at", "data_cutoff_at", "supersedes_event_id", "auto_trading_enabled", "authority"}, "qualification request")
    _constant(row, "schema_version", REQUEST_VERSION)
    row["qualification_id"] = _identifier(row["qualification_id"], "qualification_id")
    row["policy_event_id"] = _event_id(row["policy_event_id"], "policy_event_id")
    if row["supersedes_event_id"] is not None: row["supersedes_event_id"] = _event_id(row["supersedes_event_id"], "supersedes_event_id")
    for field in ("recorded_at", "data_cutoff_at"): row[field] = accounting_timestamp(row[field], field)
    if parse_rfc3339(row["data_cutoff_at"], "cutoff") > parse_rfc3339(row["recorded_at"], "clock"):
        raise ContractValidationError("qualification cutoff cannot follow record clock")
    return _safe(row)


class TradingEvidenceQualificationPolicy(_ImmutableDocument):
    __slots__ = ()
    _validator = staticmethod(_policy)


class TradingTrainingAssumptions(_ImmutableDocument):
    __slots__ = ()
    _validator = staticmethod(_assumptions)


class TradingEvidenceQualificationRequest(_ImmutableDocument):
    __slots__ = ()
    _validator = staticmethod(_request)


def validate_journal_event(result):
    from .decision_journal import _journal_id, _hash
    from ..hashing import sha256_bytes
    row = dict(result)
    _constant(row, "schema_version", JOURNAL_VERSION); _constant(row, "domain", "TRADING")
    for field in ("event_id", "decision_id"): row[field] = _journal_id(row[field], field)
    row["recorded_at"] = accounting_timestamp(row["recorded_at"], "recorded_at")
    row["evidence"] = _evidence(row["evidence"])
    kind = _enum(row["event_type"], {POLICY_TYPE, ASSESSMENT_TYPE}, "event_type")
    source_kind = "TRADING_EVIDENCE_QUALIFICATION_POLICY" if kind == POLICY_TYPE else "TRADING_EVIDENCE_QUALIFICATION"
    identity_field = "policy_id" if kind == POLICY_TYPE else "qualification_id"
    row["source"] = _object(row["source"], {"kind", identity_field, "source_sha256"}, "qualification source")
    _constant(row["source"], "kind", source_kind)
    row["source"][identity_field] = _identifier(row["source"][identity_field], identity_field)
    row["source"]["source_sha256"] = _hash(row["source"]["source_sha256"], "source_sha256")
    fields = {"policy", "links", "implementation_evidence"} if kind == POLICY_TYPE else {"request", "result", "policy_event_id", "prior_qualification_event_ids", "implementation_evidence"}
    payload = _object(row["payload"], fields, "qualification payload")
    document = TradingEvidenceQualificationPolicy.from_mapping(payload["policy"]) if kind == POLICY_TYPE else TradingEvidenceQualificationRequest.from_mapping(payload["request"])
    if getattr(document, identity_field) != row["source"][identity_field] or sha256_bytes(document.to_bytes()) != row["source"]["source_sha256"] or document.recorded_at != row["recorded_at"]:
        raise ContractValidationError("qualification source identity/hash/clock mismatch")
    payload["implementation_evidence"] = _evidence(payload["implementation_evidence"])
    if kind == POLICY_TYPE:
        payload["policy"] = document.to_dict()
        payload["links"] = _object(payload["links"], {"base_plan_event_id", "hypothesis_event_id", "intake_event_id"}, "qualification links")
        for field in payload["links"]: payload["links"][field] = _event_id(payload["links"][field], field)
    else:
        payload["request"] = document.to_dict()
        if payload["policy_event_id"] != document.policy_event_id: raise ContractValidationError("policy event link mismatch")
        result_fields = {"schema_version", "method_version", "qualification_id", "policy_id", "status", "eligible_for_study_design", "reason_codes", "continuity", "training_calibration", "risk", "uncertainty_protocol", "uncertainty_status", "uncertainty_computed", "economic_hypothesis_supported", "existing_gate_override", "execution_status", "realized_trade_pnl", "limitations", "provenance", "auto_trading_enabled", "authority"}
        assessment = _object(payload["result"], result_fields, "qualification result")
        _constant(assessment, "schema_version", "blackpod.trading_evidence_qualification.v1")
        _constant(assessment, "method_version", "blackpod.trading_real_evidence_qualification.v1")
        _constant(assessment, "qualification_id", document.qualification_id)
        _enum(assessment["status"], {"READY_FOR_QUALIFIED_STUDY_DESIGN", "DEFER_EVIDENCE_QUALIFICATION"}, "status")
        for field in ("uncertainty_computed", "economic_hypothesis_supported", "existing_gate_override"): _fixed_boolean(assessment, field, False)
        _constant(assessment, "execution_status", "NOT_EXECUTED"); _constant(assessment, "realized_trade_pnl", None)
        _safe(assessment)
        from .decision_journal import _boolean
        _boolean(assessment["eligible_for_study_design"], "eligible_for_study_design")
        if assessment["eligible_for_study_design"] != (assessment["status"] == "READY_FOR_QUALIFIED_STUDY_DESIGN"):
            raise ContractValidationError("qualification eligibility and status mismatch")
        prior = payload["prior_qualification_event_ids"]
        if not isinstance(prior, list) or len(prior) > 1024 or prior != sorted(set(prior)):
            raise ContractValidationError("prior qualification identities require a bounded sorted unique list")
        for entry in prior: _event_id(entry, "prior qualification")
    row["payload"] = payload
    return row
