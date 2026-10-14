"""One frozen, descriptive prospective pilot; never an execution contract."""
from __future__ import annotations

from copy import deepcopy

from .decision_journal import _evidence, _hash, _identifier, _journal_id, _object
from .investment_review import disabled_authority
from .mission_request import ContractValidationError, parse_rfc3339
from .trading_accounting import accounting_timestamp
from .trading_reconciliation import _ReconciliationDocument, evidence_reference
from ..hashing import canonical_json_bytes, sha256_bytes

PROTOCOL_VERSION = "blackpod.shadow_experiment_protocol.v1"
OBSERVATION_VERSION = "blackpod.shadow_experiment_observation.v1"
VIEW_VERSION = "blackpod.shadow_experiment_view.v1"
JOURNAL_VERSION = "blackpod.decision_journal_event.v25"
PROTOCOL_TYPE = "SHADOW_EXPERIMENT_PROTOCOL_FROZEN"
OBSERVATION_TYPE = "SHADOW_EXPERIMENT_OBSERVATION_RECORDED"
KIND = "SHADOW_EXPERIMENT"
METHOD = "blackpod.prospective_reversal_gross_proxy.v1"
AUTHORITY = {name: False for name in ("authorization_enabled", "capital_activation_enabled", "execution_enabled", "policy_changes_enabled")}
CRITERIA = {
    "signal_sessions": 30, "opportunity_count": 60, "minimum_observed_candidates": 12,
    "candidate_rule": "COMPLETED_PROVIDER_CLOSE_OVER_PRIOR_CLOSE_MINUS_ONE_LT_ZERO",
    "holding_sessions": 1, "overlap_policy": "NO_OVERLAPPING_CANDIDATE_PER_SYMBOL",
    "cash_benchmark": "ZERO_RETURN_NO_INTEREST_ASSUMED",
    "control_benchmark": "EQUAL_WEIGHT_QQQ_SPY_SAME_PROVIDER_OPEN_DATES_UNIT_GROSS_EXPOSURE",
    "positive_descriptive_rule": "MEAN_GROSS_RETURN_AND_MEAN_GROSS_EXCESS_OVER_CONTROL_STRICTLY_POSITIVE",
    "sample_unit": "SYMBOL_SESSION_NOT_INDEPENDENT_OBSERVATIONS",
    "inference": "DESCRIPTIVE_ONLY_NO_SIGNIFICANCE_OR_ECONOMIC_EDGE_CLAIM",
    "cost_policy": "UNKNOWN_NET_METRICS_UNAVAILABLE",
    "parameter_changes": "NO_CHANGES_WITHIN_RUN_NEW_PROTOCOL_REQUIRED",
    "admission_deadline_seconds_before_source_session_open": 300,
    "proxy_clock_basis": "DECLARED_EXTENDED_SESSION_OPEN_LOWER_BOUND_NOT_ACTUAL_FIRST_TRADE_TIME",
    "source_completion": "EXTENDED_SESSION_CLOSE_PLUS_900_SECONDS",
    "arithmetic": "DECIMAL_60_SIGNIFICANT_DIGITS_ROUND_HALF_EVEN_EXACT_PRICE_COMPARISON_FOR_SIGNAL",
}
LIMITATIONS = [
    "GROSS_PROVIDER_BAR_PROXY_NOT_EXECUTABLE_RETURN_OR_REALIZED_TRADE_PNL",
    "IEX_DAILY_BAR_OPEN_NOT_VERIFIED_REGULAR_SESSION_OPEN_OR_AUCTION",
    "OBSERVATIONAL_PROXY_BASIS_DIFFERS_FROM_ORIGINAL_REGULAR_OPEN_HYPOTHESIS",
    "COSTS_SLIPPAGE_CONTINUITY_CAPACITY_RISK_AND_UNCERTAINTY_UNQUALIFIED",
    "LOCAL_CLOCK_AND_RETAINED_RECEIPTS_NOT_INDEPENDENT_AUTHENTICATED_PREREGISTRATION",
    "QQQ_SPY_AND_ADJACENT_SESSIONS_CORRELATED_NO_INDEPENDENT_SAMPLE_CLAIM",
    "NO_AUTOMATIC_CORRECTION_OF_PREVIOUSLY_RECORDED_SOURCE_VALUES",
    "ORIGINAL_NATIVE_GATES_AND_FINAL_HOLDOUT_UNCHANGED",
    "NO_ECONOMIC_EDGE_VALIDATION_PROMOTION_OR_EXECUTION_AUTHORITY",
]
SESSION_FIELDS = {"date", "open_at", "close_at", "session_open_at", "session_close_at"}
PROTOCOL_FIELDS = {"schema_version", "method_version", "experiment_id", "frozen_at", "first_signal_session",
    "universe", "sessions", "context_sessions", "hypothesis_evidence", "calendar_evidence", "calendar_receipt_evidence",
    "calendar_captured_at", "original_hypothesis_id", "original_horizon", "observation_basis", "availability_buffer_seconds",
    "criteria", "scope", "auto_trading_enabled", "authority", "execution_status", "realized_trade_pnl", "limitations"}
PREDICTION_FIELDS = {"prediction_id", "symbol", "signal_session", "signal_close_at", "signal_available_at", "entry_session",
    "entry_open_at", "exit_session", "exit_open_at", "outcome_available_at", "recorded_at", "status", "reason_codes",
    "signal_return", "signal_close", "previous_close"}
OUTCOME_FIELDS = {"outcome_id", "prediction_id", "symbol", "recorded_at", "status", "candidate_gross_return",
    "control_gross_return", "cash_return", "excess_over_control", "reason_codes", "entry_price", "exit_price"}


def _constant(value, expected, name):
    if canonical_json_bytes(value) != canonical_json_bytes(expected):
        raise ContractValidationError(name + " differs from the fixed pilot contract")


def session(value):
    row = _object(value, SESSION_FIELDS, "pilot calendar session")
    from .historical_intake import historical_date
    row["date"] = historical_date(row["date"], "session.date")
    for field in SESSION_FIELDS - {"date"}:
        row[field] = accounting_timestamp(row[field], field)
    clocks = [parse_rfc3339(row[field], field) for field in ("session_open_at", "open_at", "close_at", "session_close_at")]
    if not clocks[0] <= clocks[1] < clocks[2] <= clocks[3]:
        raise ContractValidationError("pilot session clocks are not chronological")
    return row


def validate_protocol(value):
    row = _object(value, PROTOCOL_FIELDS, "shadow experiment protocol")
    fixed = {"schema_version": PROTOCOL_VERSION, "method_version": METHOD, "universe": ["QQQ", "SPY"],
        "original_hypothesis_id": "previous-session-reversal-v1", "observation_basis": "PROVIDER_DAILY_BAR_OPEN_TO_OPEN_GROSS_PROXY",
        "availability_buffer_seconds": 900, "criteria": CRITERIA, "scope": "PROSPECTIVE_OBSERVATION_ONLY",
        "auto_trading_enabled": False, "execution_status": "NOT_EXECUTED", "realized_trade_pnl": None, "limitations": LIMITATIONS}
    for field, expected in fixed.items():
        _constant(row[field], expected, field)
    row["experiment_id"] = _identifier(row["experiment_id"], "experiment_id")
    for field in ("frozen_at", "calendar_captured_at"):
        row[field] = accounting_timestamp(row[field], field)
    if parse_rfc3339(row["calendar_captured_at"], "calendar capture") > parse_rfc3339(row["frozen_at"], "freeze"):
        raise ContractValidationError("calendar capture follows protocol freeze")
    if not isinstance(row["context_sessions"], list) or len(row["context_sessions"]) != 33:
        raise ContractValidationError("pilot requires prior session,30 signal sessions,and2 following sessions")
    rows = [session(item) for item in row["context_sessions"]]
    if [item["date"] for item in rows] != sorted({item["date"] for item in rows}):
        raise ContractValidationError("pilot sessions must be distinct and chronological")
    _constant(row["sessions"], rows[1:31], "signal sessions")
    _constant(row["first_signal_session"], rows[1]["date"], "first signal session")
    if parse_rfc3339(row["frozen_at"], "freeze") >= parse_rfc3339(rows[1]["close_at"], "first close"):
        raise ContractValidationError("protocol must freeze before the first regular signal close")
    row["context_sessions"], row["sessions"] = rows, deepcopy(rows[1:31])
    for field in ("hypothesis_evidence", "calendar_evidence", "calendar_receipt_evidence"):
        row[field] = evidence_reference(row[field], field)
    expected_horizon = {"kind": "SWING", "holding_sessions": 1, "label_horizon_sessions": 1,
        "entry_clock": "NEXT_SESSION_OPEN_AFTER_INPUT_AVAILABILITY", "exit_clock": "SESSION_OPEN_AFTER_DECLARED_HOLDING_SESSIONS",
        "overlap_policy": "NO_OVERLAPPING_POSITIONS_OR_REENTRY_WHILE_OPEN"}
    _constant(row["original_horizon"], expected_horizon, "original hypothesis horizon")
    row["authority"] = disabled_authority(row["authority"])
    return row


class ShadowExperimentProtocol(_ReconciliationDocument):
    __slots__ = ()
    _validator = staticmethod(validate_protocol)


def validate_journal_event(value):
    row = dict(value)
    for field, expected in (("schema_version", JOURNAL_VERSION), ("domain", "TRADING")):
        _constant(row[field], expected, field)
    if row["event_type"] not in {PROTOCOL_TYPE, OBSERVATION_TYPE}:
        raise ContractValidationError("unsupported shadow experiment event")
    for field in ("event_id", "decision_id"):
        row[field] = _journal_id(row[field], field)
    row["recorded_at"] = accounting_timestamp(row["recorded_at"], "recorded_at")
    source = _object(row["source"], {"kind", "experiment_id", "source_sha256"}, "pilot source")
    _constant(source["kind"], KIND, "pilot source kind")
    source["experiment_id"] = _identifier(source["experiment_id"], "experiment_id")
    source["source_sha256"] = _hash(source["source_sha256"], "source_sha256")
    fields = {"protocol", "implementation_evidence"} if row["event_type"] == PROTOCOL_TYPE else {
        "schema_version", "experiment_id", "captured_at", "protocol_event_id", "previous_observation_event_id",
        "calendar_evidence", "calendar_receipt_evidence", "bars_evidence", "bars_receipt_evidence", "predictions", "outcomes"}
    payload = _object(row["payload"], fields, "pilot event payload")
    if row["event_type"] == PROTOCOL_TYPE:
        protocol = validate_protocol(payload["protocol"])
        _constant(row["recorded_at"], protocol["frozen_at"], "protocol clock")
        _constant(source["experiment_id"], protocol["experiment_id"], "protocol identity")
        payload["protocol"] = protocol
        payload["implementation_evidence"] = _evidence(payload["implementation_evidence"])
        source_raw = canonical_json_bytes(protocol)
    else:
        _constant(payload["schema_version"], OBSERVATION_VERSION, "observation schema")
        _constant(payload["experiment_id"], source["experiment_id"], "observation identity")
        payload["captured_at"] = accounting_timestamp(payload["captured_at"], "captured_at")
        _constant(row["recorded_at"], payload["captured_at"], "observation clock")
        _journal_id(payload["protocol_event_id"], "protocol_event_id")
        if payload["previous_observation_event_id"] is not None:
            _journal_id(payload["previous_observation_event_id"], "previous_observation_event_id")
        for field in ("calendar_evidence", "calendar_receipt_evidence", "bars_evidence", "bars_receipt_evidence"):
            payload[field] = evidence_reference(payload[field], field)
        for field, fields in (("predictions", PREDICTION_FIELDS), ("outcomes", OUTCOME_FIELDS)):
            if not isinstance(payload[field], list) or len(payload[field]) > 60:
                raise ContractValidationError("pilot rows must be a bounded list")
            payload[field] = [_object(item, fields, field + " row") for item in payload[field]]
        source_raw = canonical_json_bytes(payload)
    _constant(source["source_sha256"], sha256_bytes(source_raw), "pilot source hash")
    row["source"], row["payload"], row["evidence"] = source, payload, _evidence(row["evidence"])
    return row
