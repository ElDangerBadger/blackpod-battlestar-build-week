"""Strict journal envelopes for frozen research policies and candidate intakes."""
from .decision_journal import _object, _journal_id, _evidence, _hash
from .investment_review import _event_id
from .trading_accounting import accounting_timestamp
from .mission_request import ContractValidationError
from ..hashing import canonical_json_bytes, sha256_bytes

JOURNAL_VERSION = "blackpod.decision_journal_event.v23"
POLICY_TYPE = "TRADING_RECONCILED_ACTION_POLICY_RECORDED"
INTAKE_TYPE = "TRADING_RECONCILED_ACTION_INTAKE_RECORDED"
POLICY_KIND = "TRADING_RECONCILED_ACTION_POLICY"
INTAKE_KIND = "TRADING_RECONCILED_ACTION_INTAKE"
LINK_FIELDS = {"anchor_review_event_id", "continuity_event_id", "selected_qualification_event_id"}


def _constant(value, expected, field):
    if value != expected or type(value) is not type(expected):
        raise ContractValidationError(field + " differs from the fixed research journal contract")


def validate_anchor_snapshot(value):
    from .segmented_evidence_qualification import validate_result
    row = _object(value, {"anchor_event_sha256", "anchor_result_sha256", "native_qualification_snapshot",
        "native_qualification_result_sha256"}, "original qualification snapshot")
    for field in ("anchor_event_sha256", "anchor_result_sha256", "native_qualification_result_sha256"):
        _hash(row[field], field)
    row["native_qualification_snapshot"] = validate_result(row["native_qualification_snapshot"])
    if sha256_bytes(canonical_json_bytes(row["native_qualification_snapshot"])) != row["native_qualification_result_sha256"]:
        raise ContractValidationError("original native snapshot hash differs")
    return row


def validate_links(value, *, intake=False):
    row = _object(value, LINK_FIELDS | ({"policy_event_id"} if intake else set()), "reconciled action links")
    return {key: _event_id(item, key) for key, item in row.items()}


def validate_journal_event(value):
    from .reconciled_action_intake import ReconciledActionIntakePolicy, ReconciledActionIntakeRequest, validate_result
    row = dict(value)
    _constant(row["schema_version"], JOURNAL_VERSION, "schema_version")
    _constant(row["domain"], "TRADING", "domain")
    if row["event_type"] not in {POLICY_TYPE, INTAKE_TYPE}:
        raise ContractValidationError("unsupported reconciled action journal event")
    for key in ("event_id", "decision_id"):
        row[key] = _journal_id(row[key], key)
    row["recorded_at"] = accounting_timestamp(row["recorded_at"], "recorded_at")
    intake = row["event_type"] == INTAKE_TYPE
    common = {"links", "anchor_snapshot", "implementation_evidence"}
    payload = _object(row["payload"], common | ({"request", "result", "prior_intake_event_ids"} if intake else {"policy"}), "reconciled action payload")
    payload["links"] = validate_links(payload["links"], intake=intake)
    payload["anchor_snapshot"] = validate_anchor_snapshot(payload["anchor_snapshot"])
    payload["implementation_evidence"] = _evidence(payload["implementation_evidence"])
    if intake:
        document = ReconciledActionIntakeRequest.from_mapping(payload["request"])
        payload["request"] = document.to_dict()
        payload["result"] = validate_result(payload["result"])
        field, identifier, kind = "intake_id", document.intake_id, INTAKE_KIND
        if payload["result"]["intake_id"] != document.intake_id or payload["result"]["policy_evidence"] != document.policy_evidence:
            raise ContractValidationError("intake result differs from the recorded request identity")
        native = payload["anchor_snapshot"]["native_qualification_snapshot"]
        if payload["result"]["original_native_masks"]["sha256"] != sha256_bytes(canonical_json_bytes(native["continuity"])):
            raise ContractValidationError("intake result differs from the original native mask snapshot")
        if payload["links"]["policy_event_id"] != document.policy_event_id:
            raise ContractValidationError("intake journal selects a different policy event")
        ids = payload["prior_intake_event_ids"]
        if not isinstance(ids, list) or len(ids) > 1024:
            raise ContractValidationError("prior intakes require a bounded explicit list")
        ids = [_event_id(item, "prior intake") for item in ids]
        if ids != sorted(set(ids)):
            raise ContractValidationError("prior intakes must be sorted and distinct")
        payload["prior_intake_event_ids"] = ids
    else:
        document = ReconciledActionIntakePolicy.from_mapping(payload["policy"])
        payload["policy"] = document.to_dict()
        field, identifier, kind = "policy_id", document.policy_id, POLICY_KIND
        if payload["links"]["anchor_review_event_id"] != document.anchor_review_event_id:
            raise ContractValidationError("policy journal selects a different v22 anchor")
        native = payload["anchor_snapshot"]["native_qualification_snapshot"]
        if sha256_bytes(canonical_json_bytes(native["continuity"])) != document.original_native_masks_evidence["sha256"]:
            raise ContractValidationError("frozen policy must preserve the original native mask snapshot")
    source = _object(row["source"], {"kind", field, "source_sha256"}, "reconciled action source")
    _constant(source["kind"], kind, "source kind")
    _constant(source[field], identifier, field)
    if source["source_sha256"] != sha256_bytes(document.to_bytes()) or row["recorded_at"] != document.recorded_at:
        raise ContractValidationError("journal source identity or clock differs from the frozen document")
    row.update(source=source, payload=payload, evidence=_evidence(row["evidence"]))
    return row
