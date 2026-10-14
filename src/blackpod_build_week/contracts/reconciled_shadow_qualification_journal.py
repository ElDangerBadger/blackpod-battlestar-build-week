"""Strict research-only envelopes for the reconciled overlay consumer."""
from .decision_journal import _object, _journal_id, _hash, _evidence
from .investment_review import _event_id
from .trading_accounting import accounting_timestamp
from .mission_request import ContractValidationError
from ..hashing import canonical_json_bytes, sha256_bytes

JOURNAL_VERSION = "blackpod.decision_journal_event.v24"
TYPE = "TRADING_RECONCILED_SHADOW_QUALIFICATION_RECORDED"
KIND = "TRADING_RECONCILED_SHADOW_QUALIFICATION"
LINK_FIELDS = {"intake_event_id", "policy_event_id", "anchor_review_event_id",
    "selected_qualification_event_id", "continuity_event_id"}
SNAPSHOT_FIELDS = {"intake_event_sha256", "intake_result_sha256", "policy_event_sha256",
    "native_qualification_event_sha256", "anchor_review_event_sha256"}


def _constant(value, expected, name):
    if type(value) is not type(expected) or value != expected:
        raise ContractValidationError(name + " differs from the fixed shadow consumer contract")


def validate_links(value):
    row = _object(value, LINK_FIELDS, "shadow qualification links")
    return {key: _event_id(item, key) for key, item in row.items()}


def validate_source_snapshot(value):
    row = _object(value, SNAPSHOT_FIELDS, "shadow qualification source hashes")
    return {key: _hash(item, key) for key, item in row.items()}


def validate_journal_event(value):
    from .reconciled_shadow_qualification import ReconciledShadowQualificationRequest, validate_result
    row = dict(value)
    for key, expected in (("schema_version", JOURNAL_VERSION), ("domain", "TRADING"), ("event_type", TYPE)):
        _constant(row[key], expected, key)
    for key in ("event_id", "decision_id"):
        row[key] = _journal_id(row[key], key)
    row["recorded_at"] = accounting_timestamp(row["recorded_at"], "recorded_at")
    payload = _object(row["payload"], {"request", "result", "links", "source_snapshot",
        "prior_qualification_event_ids", "implementation_evidence"}, "shadow qualification payload")
    request = ReconciledShadowQualificationRequest.from_mapping(payload["request"])
    result = validate_result(payload["result"])
    links = validate_links(payload["links"])
    snapshot = validate_source_snapshot(payload["source_snapshot"])
    if (result["qualification_id"] != request.qualification_id
            or result["recorded_at"] != request.recorded_at
            or result["data_cutoff_at"] != request.data_cutoff_at
            or result["input_bindings"]["intake_event_id"] != request.intake_event_id
            or result["input_bindings"]["intake_result_evidence"] != request.intake_result_evidence
            or links["intake_event_id"] != request.intake_event_id
            or snapshot["intake_result_sha256"] != request.intake_result_evidence["sha256"]):
        raise ContractValidationError("shadow qualification identity or selected intake differs")
    if result["input_bindings"]["native_snapshot_sha256"] != sha256_bytes(canonical_json_bytes(result["native_qualification_snapshot"])):
        raise ContractValidationError("shadow qualification original native snapshot hash differs")
    prior = payload["prior_qualification_event_ids"]
    if not isinstance(prior, list) or len(prior) > 1024:
        raise ContractValidationError("prior qualifications require a bounded explicit list")
    prior = [_event_id(item, "prior qualification") for item in prior]
    if prior != sorted(set(prior)):
        raise ContractValidationError("prior qualifications must be sorted and distinct")
    source = _object(row["source"], {"kind", "qualification_id", "source_sha256"}, "shadow qualification source")
    _constant(source["kind"], KIND, "source kind")
    _constant(source["qualification_id"], request.qualification_id, "qualification_id")
    if source["source_sha256"] != sha256_bytes(request.to_bytes()) or row["recorded_at"] != request.recorded_at:
        raise ContractValidationError("shadow qualification source hash or clock differs")
    row["source"] = source
    row["evidence"] = _evidence(row["evidence"])
    row["payload"] = {"request": request.to_dict(), "result": result, "links": links,
        "source_snapshot": snapshot, "prior_qualification_event_ids": prior,
        "implementation_evidence": _evidence(payload["implementation_evidence"])}
    return row
