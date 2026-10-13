"""Closed declarations for independent, development-only shadow studies.

An evidence review is a claim that must be checked against retained sources by
the pure gate verifier. Its status cannot authorize simulation by itself. None
of these contracts authenticates a provider, historical availability, observed
execution costs, economic edge, a desk budget, or an executable broker order.
The original research plan and hypothesis remain immutable source evidence.
"""
from __future__ import annotations

from decimal import Decimal

from .decision_journal import _boolean, _enum, _identifier, _object, _string
from .investment_review import _fixed_boolean, _list, disabled_authority
from .mission_request import ContractValidationError
from .trading_accounting import accounting_timestamp
from .trading_reconciliation import _ReconciliationDocument, evidence_reference
from .trading_research import _decimal, _universe, research_symbol

TRADING_SHADOW_STUDY_VERSION = "blackpod.trading_shadow_study.v1"
PRICE_CONTINUITY_EVIDENCE_VERSION = "blackpod.price_continuity_evidence.v1"
TRADING_COST_EVIDENCE_VERSION = "blackpod.trading_cost_evidence.v1"
PRICE_CONTINUITY_SOURCE_VERSION = "blackpod.trading_price_continuity_source.v1"
TRADING_COST_SOURCE_VERSION = "blackpod.trading_cost_source.v1"
TRADING_SHADOW_MODE = "SHADOW_RESEARCH"
TRADING_SHADOW_SCOPE = "DEVELOPMENT_TEST_ONLY"
COST_STRESS_MULTIPLIERS = ("1", "2", "4")
COST_MODEL_FIELDS = frozenset({"spread_bps", "slippage_bps", "fee_bps", "fee_per_fill"})
STUDY_ID_MAX_LENGTH = 128 - len("-candidate-intents")


def _constant(row, field, expected):
    if row[field] != expected or type(row[field]) is not type(expected):
        raise ContractValidationError(field + " must be " + repr(expected))


def _references(value, name):
    rows = [evidence_reference(item, name) for item in _list(value, name)]
    if not 1 <= len(rows) <= 128 or len({row["path"] for row in rows}) != len(rows):
        raise ContractValidationError(name + " must contain one through 128 distinct source paths")
    return rows


def _texts(value, name):
    rows = [_string(item, name, 10000) for item in _list(value, name)]
    if not 1 <= len(rows) <= 32 or len(set(rows)) != len(rows):
        raise ContractValidationError(name + " must contain one through 32 distinct explicit statements")
    return rows


def validate_shadow_cost_model(value):
    """Validate cost parameters as exact declarations, never observed fills."""
    row = _object(value, COST_MODEL_FIELDS, "shadow cost model")
    for field in ("spread_bps", "slippage_bps", "fee_bps"):
        row[field] = _decimal(row[field], "cost_model." + field, maximum=Decimal("1000"))
    row["fee_per_fill"] = _decimal(row["fee_per_fill"], "cost_model.fee_per_fill")
    return row


def _study(value):
    row = _object(value, {
        "schema_version", "study_id", "experiment_id", "registered_at", "domain", "mode", "scope",
        "base_plan_evidence", "price_continuity_evidence", "cost_evidence", "sizing", "benchmark",
        "cost_stress_multipliers", "trial_registry", "evidence_scope", "auto_trading_enabled", "authority",
    }, "trading shadow study")
    for field, expected in {
        "schema_version": TRADING_SHADOW_STUDY_VERSION, "domain": "TRADING",
        "mode": TRADING_SHADOW_MODE, "scope": TRADING_SHADOW_SCOPE,
    }.items():
        _constant(row, field, expected)
    for field in ("study_id", "experiment_id"):
        row[field] = _identifier(row[field], field)
    if len(row["study_id"]) > STUDY_ID_MAX_LENGTH:
        raise ContractValidationError("study_id must reserve eighteen characters for derived intent identifiers (maximum 110)")
    row["evidence_scope"] = _enum(row["evidence_scope"], {"SYNTHETIC_FIXTURE_ONLY", "RETAINED_HISTORY_RESEARCH"}, "evidence_scope")
    row["registered_at"] = accounting_timestamp(row["registered_at"], "registered_at")
    row["base_plan_evidence"] = evidence_reference(row["base_plan_evidence"], "base_plan_evidence")
    for field in ("price_continuity_evidence", "cost_evidence"):
        if row[field] is not None:
            row[field] = evidence_reference(row[field], field)
    paths = [row[field]["path"] for field in
             ("base_plan_evidence", "price_continuity_evidence", "cost_evidence") if row[field] is not None]
    if len(set(paths)) != len(paths):
        raise ContractValidationError("base plan and gate evidence must have distinct paths")
    sizing = _object(row["sizing"], {"method", "per_symbol_notional"}, "sizing")
    _constant(sizing, "method", "KNOWN_CLOSE_WHOLE_QUANTITY")
    sizing["per_symbol_notional"] = _decimal(sizing["per_symbol_notional"], "sizing.per_symbol_notional", positive=True)
    row["sizing"] = sizing
    benchmark = _object(row["benchmark"], {"kind"}, "benchmark")
    _constant(benchmark, "kind", "MATCHED_ENTRY_NOTIONAL_AND_DURATION_EQUAL_WEIGHT_COUNTERFACTUAL")
    row["benchmark"] = benchmark
    _constant(row, "cost_stress_multipliers", list(COST_STRESS_MULTIPLIERS))
    registry = _object(row["trial_registry"], {"trial_id", "prior_trial_ids"}, "trial_registry")
    registry["trial_id"] = _identifier(registry["trial_id"], "trial_id")
    prior = [_identifier(item, "prior_trial_id") for item in _list(registry["prior_trial_ids"], "prior_trial_ids")]
    if len(prior) > 10000 or len(set(prior)) != len(prior) or registry["trial_id"] in prior:
        raise ContractValidationError("prior trial identities must be distinct, bounded and exclude the current trial")
    registry["prior_trial_ids"] = prior
    row["trial_registry"] = registry
    _fixed_boolean(row, "auto_trading_enabled", False)
    row["authority"] = disabled_authority(row["authority"])
    return row


def _review(value, *, cost):
    fields = {"schema_version", "evidence_id", "recorded_at", "dataset_evidence", "coverage_start_session_id",
              "coverage_end_session_id", "universe", "basis", "status", "source_evidence", "reviewer_id",
              "review_notes", "limitations", "auto_trading_enabled", "authority"}
    if cost:
        fields.add("cost_model")
    row = _object(value, fields, "trading cost evidence" if cost else "price continuity evidence")
    _constant(row, "schema_version", TRADING_COST_EVIDENCE_VERSION if cost else PRICE_CONTINUITY_EVIDENCE_VERSION)
    for field in ("evidence_id", "reviewer_id", "coverage_start_session_id", "coverage_end_session_id"):
        row[field] = _identifier(row[field], field)
    row["recorded_at"] = accounting_timestamp(row["recorded_at"], "recorded_at")
    row["dataset_evidence"] = evidence_reference(row["dataset_evidence"], "dataset_evidence")
    row["universe"] = _universe(row["universe"])
    retained_basis = "RETAINED_COST_REVIEW" if cost else "RETAINED_CORPORATE_ACTION_REVIEW"
    row["basis"] = _enum(row["basis"], {"SYNTHETIC_FIXTURE", retained_basis}, "basis")
    row["status"] = _enum(row["status"], {"SUPPORTED" if cost else "CONTINUITY_SUPPORTED", "UNRESOLVED"}, "status")
    row["source_evidence"] = _references(row["source_evidence"], "source_evidence")
    if row["dataset_evidence"]["path"] in {source["path"] for source in row["source_evidence"]}:
        raise ContractValidationError("gate source evidence must be distinct from the reviewed dataset")
    row["review_notes"] = _string(row["review_notes"], "review_notes", 10000)
    row["limitations"] = _texts(row["limitations"], "limitations")
    if cost:
        if row["cost_model"] is None:
            if row["status"] == "SUPPORTED":
                raise ContractValidationError("supported cost evidence requires an explicit cost model")
        else:
            row["cost_model"] = validate_shadow_cost_model(row["cost_model"])
    _fixed_boolean(row, "auto_trading_enabled", False)
    row["authority"] = disabled_authority(row["authority"])
    return row


def _source(value, *, cost):
    fields = {"schema_version", "source_id", "recorded_at", "basis", "dataset_evidence", "universe",
              "coverage_start_session_id", "coverage_end_session_id", "coverage_complete", "origin_evidence",
              "limitations", "auto_trading_enabled", "authority"}
    fields |= {"observations", "sampling_policy"} if cost else {"events", "price_policy"}
    row = _object(value, fields, "trading cost source" if cost else "price continuity source")
    _constant(row, "schema_version", TRADING_COST_SOURCE_VERSION if cost else PRICE_CONTINUITY_SOURCE_VERSION)
    for field in ("source_id", "coverage_start_session_id", "coverage_end_session_id"):
        row[field] = _identifier(row[field], field)
    row["recorded_at"] = accounting_timestamp(row["recorded_at"], "recorded_at")
    row["basis"] = _enum(row["basis"], {"SYNTHETIC_FIXTURE", "RETAINED_REVIEW_SOURCE"}, "basis")
    row["dataset_evidence"] = evidence_reference(row["dataset_evidence"], "dataset_evidence")
    row["universe"] = _universe(row["universe"])
    row["coverage_complete"] = _boolean(row["coverage_complete"], "coverage_complete")
    row["origin_evidence"] = _references(row["origin_evidence"], "origin_evidence")
    if row["dataset_evidence"]["path"] in {ref["path"] for ref in row["origin_evidence"]}:
        raise ContractValidationError("origin evidence must be distinct from the reviewed dataset")
    row["limitations"] = _texts(row["limitations"], "limitations")
    if cost:
        _constant(row, "sampling_policy", "DECLARED_REVIEW_BOUNDS_NOT_EXECUTABLE_QUOTES")
        observations = []
        for item in _list(row["observations"], "observations"):
            observation = _object(item, COST_MODEL_FIELDS | {"symbol"}, "cost observation")
            observation["symbol"] = research_symbol(observation["symbol"])
            model = validate_shadow_cost_model({field: observation[field] for field in COST_MODEL_FIELDS})
            observations.append({"symbol": observation["symbol"], **model})
        if [observation["symbol"] for observation in observations] != row["universe"]:
            raise ContractValidationError("cost observations must contain exactly the sorted source universe")
        row["observations"] = observations
    else:
        _constant(row, "price_policy", "RAW_NO_SPLITS_DISTRIBUTIONS_OR_SYMBOL_CHANGES")
        events = []
        for item in _list(row["events"], "events"):
            event = _object(item, {"event_id", "symbol", "effective_session_id", "kind"}, "continuity event")
            for field in ("event_id", "effective_session_id"):
                event[field] = _identifier(event[field], field)
            event["symbol"] = research_symbol(event["symbol"])
            if event["symbol"] not in row["universe"]:
                raise ContractValidationError("continuity events must concern the declared universe")
            event["kind"] = _enum(event["kind"], {
                "SPLIT", "CASH_DISTRIBUTION", "STOCK_DISTRIBUTION", "SYMBOL_CHANGE", "MERGER", "OTHER_PRICE_DISCONTINUITY",
            }, "continuity event kind")
            events.append(event)
        identities = [event["event_id"] for event in events]
        if len(events) > 10000 or identities != sorted(set(identities)):
            raise ContractValidationError("continuity events must have sorted, unique and bounded identities")
        row["events"] = events
    _fixed_boolean(row, "auto_trading_enabled", False)
    row["authority"] = disabled_authority(row["authority"])
    return row


class TradingShadowStudy(_ReconciliationDocument):
    __slots__ = ()
    _validator = staticmethod(_study)


class PriceContinuityEvidence(_ReconciliationDocument):
    __slots__ = ()
    _validator = staticmethod(lambda value: _review(value, cost=False))


class TradingCostEvidence(_ReconciliationDocument):
    __slots__ = ()
    _validator = staticmethod(lambda value: _review(value, cost=True))


class PriceContinuitySource(_ReconciliationDocument):
    __slots__ = ()
    _validator = staticmethod(lambda value: _source(value, cost=False))


class TradingCostSource(_ReconciliationDocument):
    __slots__ = ()
    _validator = staticmethod(lambda value: _source(value, cost=True))
