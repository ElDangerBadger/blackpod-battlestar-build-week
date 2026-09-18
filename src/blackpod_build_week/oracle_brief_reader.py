"""Transport checks for a canonical, optional Oracle interpretation supplement.

No model, canonical engine, scoring, or narrative generation is imported here.
Hashes and citations establish evidence identity, not semantic entailment.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import re

from .contracts import ArtifactReference
from .contracts.mission_request import parse_rfc3339


BRIEF_PATH = "presentation/oracle_market_brief.json"
BRIEF_SCHEMA = "blackpod.oracle_market_brief.v1"
MAX_BRIEF_BYTES = 256 * 1024
SOURCE_NAMES = frozenset({"oracle_measurements", "oracle_measurement_diagnostics",
    "oracle_readiness_report", "oracle_assessment", "oracle_report"})
SECTION_IDS = ("participation", "leadership", "rotation", "risk", "watchpoints", "limits")
VALIDATION_STATUS = "STRUCTURE_CITATIONS_AND_GUARDRAILS_CHECKED_NOT_ENTAILMENT_VERIFIED"


def _require(condition):
    if not condition:
        raise ValueError("Oracle market brief has inconsistent presentation evidence")


def _object(value, fields):
    _require(isinstance(value, dict) and set(value) == set(fields.split()))
    return value


def _text(value, maximum=512):
    _require(isinstance(value, str) and bool(value.strip()) and value == value.strip()
        and len(value) <= maximum and not any(ord(c) < 32 or ord(c) == 127 for c in value))
    return value


def _array(value, maximum=128):
    _require(isinstance(value, list) and len(value) <= maximum)
    return value


def _strings(value, maximum=128):
    return [_text(item, 1024) for item in _array(value, maximum)]


def _sha(value):
    _require(isinstance(value, str) and re.fullmatch(r"[a-f0-9]{64}", value))


def _identity(value, key, prefix):
    content = {k: v for k, v in value.items() if k != key}
    encoded = json.dumps(content, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    _require(value[key] == prefix + hashlib.sha256(encoded).hexdigest())


def pointer_value(document, pointer):
    """Resolve a supplied RFC6901 citation without evaluating expressions."""
    _text(pointer, 256)
    _require(pointer.startswith("/") and not re.search(r"~(?![01])", pointer))
    current = document
    for part in pointer[1:].split("/"):
        key = part.replace("~1", "/").replace("~0", "~")
        if isinstance(current, dict):
            _require(key in current)
            current = current[key]
        elif isinstance(current, list):
            _require(re.fullmatch(r"0|[1-9][0-9]*", key) is not None)
            current = current[int(key)]
        else:
            raise ValueError("Oracle brief citation cannot resolve")
    return current


def validate_brief_presentation(value, *, mission_id, request_id, symbol, references, documents, now=None):
    """Validate the saved transport and bind it to already-verified mission data."""
    _object(value, "schema_version brief_id evidence report generated_at provenance generation_method observation_only order_submission_enabled authoritative validation_status")
    _require(value["schema_version"] == BRIEF_SCHEMA
        and value["generation_method"] == "MODELDOCK_GROUNDED_SYNTHESIS"
        and value["observation_only"] is True and value["order_submission_enabled"] is False
        and value["authoritative"] is False and value["validation_status"] == VALIDATION_STATUS)
    _identity(value, "brief_id", "oracle-market-brief-")
    generated = parse_rfc3339(value["generated_at"], "brief generated_at")
    _require(generated <= (now or datetime.now(timezone.utc)))
    evidence = _object(value["evidence"], "schema_version evidence_id mission_id request_id symbol run_mode as_of source_artifacts facts warnings blockers limitations")
    _require(evidence["schema_version"] == "blackpod.oracle_market_brief_evidence.v1"
        and evidence["mission_id"] == mission_id and evidence["request_id"] == request_id
        and evidence["symbol"] == symbol and evidence["run_mode"] == "LIVE")
    _identity(evidence, "evidence_id", "oracle-brief-evidence-")
    as_of = parse_rfc3339(evidence["as_of"], "brief evidence as_of")
    _require(as_of <= generated)
    sources = evidence["source_artifacts"]
    _require(isinstance(sources, dict) and set(sources) == SOURCE_NAMES and SOURCE_NAMES <= set(documents))
    for name, source in sources.items():
        reference = ArtifactReference.from_mapping(source)
        _require(reference.name == name and name in references and source == references[name].to_dict())
        _require(reference.byte_size is not None and reference.observed_at is not None
            and parse_rfc3339(reference.observed_at, "brief source timestamp") <= generated)
    _require(parse_rfc3339(documents["oracle_measurements"]["as_of"], "measurements as_of") == as_of)
    for key in ("warnings", "blockers"):
        _strings(evidence[key], 500)
        expected = set(item for name in SOURCE_NAMES for item in documents[name][key])
        _require(set(evidence[key]) == expected)
    _require(bool(_strings(evidence["limitations"])))
    facts = _array(evidence["facts"], 64)
    _require(bool(facts))
    ids = set()
    for fact in facts:
        _object(fact, "fact_id source_artifact json_pointer label value meaning")
        _text(fact["fact_id"], 128); _text(fact["label"], 160); _text(fact["meaning"], 1600)
        _require(fact["fact_id"] not in ids and fact["source_artifact"] in SOURCE_NAMES)
        ids.add(fact["fact_id"])
        actual = pointer_value(documents[fact["source_artifact"]], fact["json_pointer"])
        # Preserve JSON types: Python otherwise equates True with 1.
        _require(json.dumps(actual, sort_keys=True, allow_nan=False)
            == json.dumps(fact["value"], sort_keys=True, allow_nan=False))
    report = _object(value["report"], "schema_version headline sections")
    _require(report["schema_version"] == "blackpod.oracle_market_brief_draft.v1")

    def paragraph(item, maximum=1200):
        _object(item, "text fact_ids"); _text(item["text"], maximum)
        cited = _strings(item["fact_ids"], 8)
        _require(bool(cited) and len(cited) == len(set(cited)) and set(cited) <= ids)

    paragraph(report["headline"], 240)
    sections = _array(report["sections"], 6)
    _require([item["section_id"] for item in sections] == list(SECTION_IDS))
    for section in sections:
        _object(section, "section_id paragraphs")
        paragraphs = _array(section["paragraphs"], 2)
        _require(bool(paragraphs))
        for item in paragraphs:
            paragraph(item)
    provenance = _object(value["provenance"], "provider model model_revision trace_id mocked request_sha256 response_sha256 started_at observed_at canonical_module_sha256")
    _require(provenance["provider"] == "mlx" and provenance["mocked"] is False)
    for key in ("model", "trace_id"):
        _text(provenance[key], 256)
    if provenance["model_revision"] is not None:
        _text(provenance["model_revision"], 256)
    for key in ("request_sha256", "response_sha256", "canonical_module_sha256"):
        _sha(provenance[key])
    started = parse_rfc3339(provenance["started_at"], "brief inference start")
    observed = parse_rfc3339(provenance["observed_at"], "brief inference end")
    _require(as_of <= started <= observed <= generated)
    _require(all(parse_rfc3339(source["observed_at"], "brief source timestamp") <= started
        for source in sources.values()))
    return value
