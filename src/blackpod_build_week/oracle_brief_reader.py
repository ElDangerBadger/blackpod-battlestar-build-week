"""Transport checks for a canonical, optional Oracle interpretation supplement.

No model, canonical engine, scoring, or narrative generation is imported here.
Hashes and citations establish evidence identity, not semantic entailment.
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
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


def validate_brief_semantics(report, evidence):
    """Reject bounded, recognizable contradictions; never attest entailment.

    This aggregate catalog contains participation fractions and relative group
    ranks, but no moving averages, named-sector returns, causal identification,
    or future outcomes. Those missing facts cannot be inferred from citations.
    The checks deliberately do not grade arbitrary prose, economic truth, or
    overall narrative quality. The receipt's original limitation remains true.
    """
    facts = {fact["fact_id"]: fact["value"] for fact in evidence["facts"]}

    def fail(rule):
        # Fixed messages only: callers must never persist rejected model prose.
        raise ValueError("Oracle brief semantic check failed: " + rule)

    def number(name):
        value = facts.get("oracle.measurements." + name)
        if type(value) not in (int, float):
            fail("missing_relationship_evidence")
        try:
            result = Decimal(str(value))
        except InvalidOperation:
            fail("missing_relationship_evidence")
        if not result.is_finite():
            fail("missing_relationship_evidence")
        return result

    paragraphs = [report["headline"], *(
        item for section in report["sections"] for item in section["paragraphs"]
    )]
    for paragraph in paragraphs:
        text = paragraph["text"].lower().replace("-", " ")
        # Only affirmative grammatical patterns are matched. Caveats such as
        # "moving-average relationships are unavailable" remain useful prose.
        if re.search(r"\b(?:price|prices|market|index|indices|stocks?)\b[^.;!?]{0,45}"
                     r"\b(?:above|below|cross(?:es|ed|ing)?)\b[^.;!?]{0,35}"
                     r"\b(?:moving average|ma|sma|ema)\b", text):
            fail("unsupported_moving_average_relationship")
        if re.search(r"\b(?:technology|financials?|energy|utilities|healthcare|"
                     r"industrials?|materials?|real estate|consumer discretionary|"
                     r"consumer staples|communication services)\b\s+"
                     r"(?:(?:sector|stocks?|shares?)\s+)?(?:is\s+|are\s+|remains?\s+)?"
                     r"(?:lead(?:s|ing)?|lag(?:s|ging)?|outperform\w*|underperform\w*|"
                     r"strongest|weakest|the leader|the laggard)\b", text):
            fail("unsupported_named_sector_leadership")
        for clause in re.split(r"[.;!?]", text):
            causal = re.search(r"\b(?:because(?: of)?|due to|driven by|caused by|owing to)\b", clause)
            if causal and re.search(r"\b(?:rally|decline|market|participation|breadth|"
                                      r"sectors?|risk posture|leadership|rotation)\b", clause[:causal.start()]):
                # Missing evidence may explain an epistemic limitation, not a
                # market move. Keep that distinction rather than banning causal
                # conjunctions from useful uncertainty explanations.
                premise, reason = clause[:causal.start()], clause[causal.end():]
                limitation = re.search(r"\b(?:uncertain|unknown|unavailable|cannot|"
                                       r"not established|not supported)\b", premise)
                missing = re.search(r"\b(?:missing|absent|incomplete|unavailable|lack of)\b", reason)
                if not (limitation and missing and (evidence.get("warnings") or evidence.get("blockers"))):
                    fail("unsupported_causality")
            if re.search(r"\binvestors? (?:are |were )?(?:rotat\w*|flee\w*|seek\w*|prefer\w*)\b", clause):
                fail("unsupported_causality")
        if re.search(r"\b(?:will|shall|is going to|are going to|is set to|"
                     r"are set to|is poised to|are poised to|is expected to|"
                     r"are expected to)\s+(?:\w+\s+){0,2}"
                     r"(?:rise|fall|rally|decline|recover|rebound|gain|lose|"
                     r"outperform|underperform|improve|deteriorate)\b", text):
            fail("unsupported_forward_prediction")
        # Explicit conditional sentences are scenarios, not assertions that
        # their antecedents describe this snapshot. Certainty and absent-domain
        # guards above still apply; this is not a general prose trust bypass.
        assertions = " ".join(sentence for sentence in re.split(r"(?<=[.!?])\s+", text)
                              if not re.match(r"\s*(?:if|unless|were)\b", sentence))
        # A positive-participation fraction cannot establish aggregate price
        # direction. In particular, a high concentration can include losses.
        if re.search(r"\b(?:the )?(?:market|index|indices)\s+"
                     r"(?:is\s+|are\s+|was\s+|were\s+)?"
                     r"(?:rising|falling|rallying|declining|advancing|retreating)\b", assertions):
            fail("unsupported_aggregate_price_direction")
        for match in re.finditer(
            r"\b(?P<amount>most|a majority of|all|no)\s+(?:of the\s+|the\s+)?"
            r"(?:measured\s+|supplied\s+|recorded\s+)?proxies\s+"
            r"(?:are|were|have)\s+(?:positive|advancing|negative|declining)\b", assertions
        ):
            claim = match.group(0)
            positive = bool(re.search(r"\b(?:positive|advancing)\b", claim))
            breadth = number("breadth_score")
            amount = match.group("amount")
            # Breadth counts strictly positive returns. Its complement can
            # include unchanged proxies, so negative counts are not supplied.
            if not positive:
                fail("unsupported_negative_participation_count")
            accepted = {"most": breadth > Decimal("0.5"),
                        "a majority of": breadth > Decimal("0.5"),
                        "all": breadth == 1, "no": breadth == 0}[amount]
            if not accepted:
                fail("contradictory_participation_direction")
        for match in re.finditer(
            r"\b(?P<left>defensive|cyclical)(?:\s+group)?\s+"
            r"(?:is\s+|are\s+)?(?P<relation>stronger than|weaker than|"
            r"outperforms?|outperforming|trails?|trailing|leads?|leading)\s+"
            r"(?:the\s+)?(?P<right>defensive|cyclical)(?:\s+group)?\b", assertions
        ):
            left, right = match.group("left"), match.group("right")
            stronger = match.group("relation") not in ("weaker than", "trail", "trails", "trailing")
            comparison = number(left + "_strength") - number(right + "_strength")
            if not (comparison > 0 if stronger else comparison < 0):
                fail("contradictory_group_relationship")
        for match in re.finditer(r"\bbreadth\s+(?:is\s+|remains?\s+)?"
                                 r"(?P<posture>expanding|contracting|stable)\b", assertions):
            expected = match.group("posture").upper() + "_BREADTH"
            if facts.get("oracle.assessment.breadth_posture") != expected:
                fail("contradictory_breadth_posture")
        warnings = evidence.get("warnings", [])
        if "MISSING_PRIOR_ORACLE_MEASUREMENTS" in warnings and re.search(
            r"\b(?:rotation\s+(?:is\s+|remains?\s+)?(?:unchanged|stable)|"
            r"(?:rotation|breadth|leadership|risk posture)\s+"
            r"(?:has\s+|has been\s+)?(?:improved|worsened|accelerat\w*|decelerat\w*))\b", assertions):
            fail("unsupported_temporal_comparison")
    return report


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
    validate_brief_semantics(report, evidence)
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
