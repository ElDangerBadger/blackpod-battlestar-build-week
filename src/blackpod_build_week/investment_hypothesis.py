"""Pure, source-bound shadow hypothesis preparation and verification.

The caller supplies the research. These functions bind explicit observations to
previously verified journal evidence; they neither generate economic claims nor
authorize investment, trading, policy changes or capital movement.
"""

from __future__ import annotations

import math
import re
from collections.abc import Mapping, Sequence
from typing import Any

from .contracts.decision_journal import JournalEvent
from .contracts.investment_hypothesis import InvestmentHypothesis, _observations
from .contracts.mission_request import (
    ContractValidationError,
    normalize_rfc3339,
    parse_rfc3339,
    parse_strict_json_object_bytes,
)
from .hashing import canonical_json_bytes, sha256_bytes


class HypothesisEvidenceError(ValueError):
    """A draft cannot be bound to the supplied retained source evidence."""


def _identity(prefix: str, value: object) -> str:
    return f"{prefix}-{sha256_bytes(canonical_json_bytes(value))}"


def _pointer_tokens(pointer: str) -> tuple[str, ...]:
    if pointer == "":
        return ()
    if not isinstance(pointer, str) or not pointer.startswith("/"):
        raise HypothesisEvidenceError("source pointer must be an RFC 6901 JSON pointer")
    raw_tokens = pointer[1:].split("/")
    if any(re.search(r"~(?:[^01]|$)", token) for token in raw_tokens):
        raise HypothesisEvidenceError("source pointer contains an invalid escape")
    return tuple(token.replace("~1", "/").replace("~0", "~") for token in raw_tokens)


def resolve_source_pointer(value: object, pointer: str) -> object:
    """Resolve JSON pointers without ambiguous array indices or coercion."""
    current = value
    for token in _pointer_tokens(pointer):
        if isinstance(current, dict):
            if token not in current:
                raise HypothesisEvidenceError("source pointer does not resolve")
            current = current[token]
        elif isinstance(current, list):
            if not re.fullmatch(r"0|[1-9][0-9]*", token):
                raise HypothesisEvidenceError("source array index is ambiguous or invalid")
            # Bound conversion even if a programmatic caller bypasses file limits.
            if len(token) > 12 or int(token) >= len(current):
                raise HypothesisEvidenceError("source array index is outside the evidence")
            current = current[int(token)]
        else:
            raise HypothesisEvidenceError("source pointer traverses a scalar")
    return current


def _same_scalar(source: object, supplied: object) -> bool:
    if type(source) in (int, float) and type(supplied) in (int, float):
        return (type(source) is int or math.isfinite(source)) and source == supplied
    return type(source) is type(supplied) and source == supplied and type(source) in (str, bool, type(None))


def _bound_sources(
    hypothesis: InvestmentHypothesis,
    events: Sequence[JournalEvent],
    blobs: Mapping[str, bytes],
) -> dict[str, bytes]:
    hypothesis = InvestmentHypothesis.from_mapping(hypothesis.to_dict())
    value = hypothesis.to_dict()
    return bind_journal_observations(value["observations"], value["evidence_cutoff_at"], events, blobs)


def bind_journal_observations(
    observations: Sequence[Mapping[str, Any]],
    evidence_cutoff_at: str,
    events: Sequence[JournalEvent],
    blobs: Mapping[str, bytes],
) -> dict[str, bytes]:
    """Bind supplied measurements to retained mission facts without inference.

    An empty list explicitly represents absent measurements. Review workflows
    decide how that absence affects their result; this function never fills it.
    Units remain annotations, as in the original hypothesis contract.
    """
    if not isinstance(observations, (list, tuple)):
        raise HypothesisEvidenceError("observations must be an explicit list of source bindings")
    validated = _observations(list(observations)) if observations else []
    cutoff = parse_rfc3339(evidence_cutoff_at, "evidence_cutoff_at")
    indexed: dict[str, JournalEvent] = {}
    for event in events:
        if event.event_id in indexed:
            raise HypothesisEvidenceError("source journal contains ambiguous event identities")
        indexed[event.event_id] = event
    bound: dict[str, bytes] = {}
    parsed: dict[str, dict[str, Any]] = {}
    time_keys = {"AS_OF": "as_of", "GENERATED_AT": "generated_at",
                 "OBSERVED_AT": "observed_at", "REQUESTED_AT": "requested_at"}
    for observation in validated:
        source = indexed.get(observation["source_event_id"])
        if source is None or source.event_type != "MISSION_SNAPSHOT_RECORDED":
            raise HypothesisEvidenceError("observation requires an existing imported mission event")
        if parse_rfc3339(source.recorded_at, "source.recorded_at") > cutoff:
            raise HypothesisEvidenceError("source event was recorded after the evidence cutoff")
        refs = [ref for ref in source.evidence if ref["path"] == observation["artifact_path"]]
        if len(refs) != 1 or refs[0]["sha256"] != observation["artifact_sha256"]:
            raise HypothesisEvidenceError("observation artifact does not match its source event")
        digest = observation["artifact_sha256"]
        raw = blobs.get(digest)
        if not isinstance(raw, bytes) or sha256_bytes(raw) != digest or len(raw) != refs[0]["size_bytes"]:
            raise HypothesisEvidenceError("observation evidence is missing, changed or incorrectly sized")
        if digest not in parsed:
            try:
                parsed[digest] = parse_strict_json_object_bytes(raw, document_name="hypothesis source")
            except (ContractValidationError, RecursionError, ValueError) as exc:
                raise HypothesisEvidenceError("observation requires a strict retained JSON object") from exc
        document = parsed[digest]
        observed = resolve_source_pointer(document, observation["value_pointer"])
        if not _same_scalar(observed, observation["value"]):
            raise HypothesisEvidenceError("observation value differs from its source pointer")
        tokens = _pointer_tokens(observation["as_of_pointer"])
        if not tokens or tokens[-1] != time_keys[observation["time_role"]]:
            raise HypothesisEvidenceError("observation time role does not match its source timestamp field")
        try:
            observed_time = normalize_rfc3339(
                resolve_source_pointer(document, observation["as_of_pointer"]), "source timestamp"
            )
        except ContractValidationError as exc:
            raise HypothesisEvidenceError("observation timestamp is absent or invalid") from exc
        if observed_time != observation["as_of"]:
            raise HypothesisEvidenceError("observation as_of differs from its source timestamp")
        if parse_rfc3339(observed_time, "source timestamp") > cutoff:
            raise HypothesisEvidenceError("observation was dated after the evidence cutoff")
        alias = f"sources/{source.event_id}/{observation['artifact_path']}"
        if alias in bound and bound[alias] != raw:
            raise HypothesisEvidenceError("observation aliases bind conflicting source evidence")
        bound[alias] = raw
    return bound


def validate_hypothesis_sources(
    hypothesis: InvestmentHypothesis,
    events: Sequence[JournalEvent],
    blobs: Mapping[str, bytes],
) -> None:
    """Check structure, exact source values/times and absence of lookahead."""
    _bound_sources(hypothesis, events, blobs)


def evidence_for_hypothesis(
    hypothesis: InvestmentHypothesis,
    events: Sequence[JournalEvent],
    blobs: Mapping[str, bytes],
) -> dict[str, bytes]:
    """Return immutable source bytes and the normalized supplied draft."""
    result = _bound_sources(hypothesis, events, blobs)
    result[f"hypotheses/{hypothesis.hypothesis_id}/hypothesis.json"] = hypothesis.to_bytes()
    return result


def build_hypothesis_event(
    hypothesis: InvestmentHypothesis,
    events: Sequence[JournalEvent],
    blobs: Mapping[str, bytes],
) -> JournalEvent:
    """Build a v2 shadow event; original mission domains/authority stay intact."""
    evidence = evidence_for_hypothesis(hypothesis, events, blobs)
    decision_id = _identity("journal-decision", {
        "kind": "INVESTMENT_HYPOTHESIS", "hypothesis_id": hypothesis.hypothesis_id,
    })
    event_type = "INVESTMENT_HYPOTHESIS_RECORDED"
    return JournalEvent.from_mapping({
        "schema_version": "blackpod.decision_journal_event.v2",
        "event_id": _identity("journal-event", {"decision_id": decision_id, "event_type": event_type}),
        "decision_id": decision_id,
        "domain": "INVESTMENT",
        "event_type": event_type,
        "recorded_at": hypothesis.recorded_at,
        "source": {
            "kind": "INVESTMENT_HYPOTHESIS", "hypothesis_id": hypothesis.hypothesis_id,
            "source_sha256": sha256_bytes(hypothesis.to_bytes()),
        },
        "evidence": [{"path": path, "sha256": sha256_bytes(raw), "size_bytes": len(raw)}
                     for path, raw in sorted(evidence.items())],
        "payload": hypothesis.to_dict(),
    })


def validate_hypothesis_event(
    event: JournalEvent,
    previous_events: Sequence[JournalEvent],
    blobs: Mapping[str, bytes],
) -> None:
    """Rebuild a stored hypothesis from earlier retained evidence on every scan."""
    if event.event_type != "INVESTMENT_HYPOTHESIS_RECORDED":
        raise HypothesisEvidenceError("unsupported hypothesis event type")
    hypothesis = InvestmentHypothesis.from_mapping(event.payload)
    expected = build_hypothesis_event(hypothesis, previous_events, blobs)
    if expected.to_bytes() != event.to_bytes():
        raise HypothesisEvidenceError("hypothesis event differs from its retained source projection")
    source_bytes = blobs.get(event.source["source_sha256"])
    if source_bytes != hypothesis.to_bytes():
        raise HypothesisEvidenceError("retained hypothesis draft differs from the canonical payload")
