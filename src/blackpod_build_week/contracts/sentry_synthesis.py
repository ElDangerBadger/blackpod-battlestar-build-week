"""Bounded, source-cited Sentry interpretations and a separate challenge pass.

These model response contracts grant no decision authority. Citation validation
establishes a relationship to the supplied evidence packet, not that a headline
is true, sources are independent, a causal explanation is correct, or a symbol
is a portfolio holding. All authority and provenance belong to the caller.
"""
from __future__ import annotations

from collections.abc import Mapping
import re
import unicodedata

from ..hashing import canonical_json_bytes, sha256_bytes
from .decision_journal import _enum, _object, _string
from .mission_request import ContractValidationError, parse_strict_json_object_bytes

LEGACY_ORACLE_SCHEMA_VERSION = "blackpod.sentry_oracle_draft.v1"
LEGACY_CHALLENGE_SCHEMA_VERSION = "blackpod.sentry_challenge.v1"
ORACLE_SCHEMA_VERSION = "blackpod.sentry_oracle_draft.v2"
CHALLENGE_SCHEMA_VERSION = "blackpod.sentry_challenge.v2"
MAX_RESPONSE_BYTES = 64 * 1024
ROLES = frozenset({"oracle", "challenge"})
LINKAGES = frozenset({"DIRECT_MENTION", "HYPOTHETICAL_READ_THROUGH"})
HORIZONS = frozenset({"UNSPECIFIED", "INTRADAY", "DAYS_TO_WEEKS", "MONTHS_TO_YEARS"})
REVIEW_STATUSES = frozenset({"CONTESTED", "UNTESTED", "EVIDENCE_BOUND"})
THEME_IDS = frozenset({"theme-1", "theme-2", "theme-3"})
_SYMBOL = re.compile(r"[A-Z][A-Z0-9.\-]{0,9}")


def _text(value, name, maximum):
    result = _string(value, name, maximum)
    if any(unicodedata.category(c) in {"Cc", "Cf", "Cs", "Zl", "Zp"} for c in result):
        raise ContractValidationError(name + " contains unsupported control or line-separator characters")
    return result


def _array(value, name, minimum, maximum):
    if not isinstance(value, list) or not minimum <= len(value) <= maximum:
        raise ContractValidationError(f"{name} must contain {minimum} to {maximum} entries")
    return value


def _texts(value, name, maximum_items, maximum_characters):
    result = [_text(v, name, maximum_characters)
              for v in _array(value, name, 0, maximum_items)]
    if len(set(result)) != len(result):
        raise ContractValidationError(name + " contains duplicate text")
    return result


def _packet(packet):
    """Check response-binding metadata; packet replay remains the caller's gate."""
    if not isinstance(packet, Mapping):
        raise ContractValidationError("evidence packet must be an object")
    _text(packet.get("context_id"), "context_id", 256)
    watchlist = [_text(s, "watchlist symbol", 10)
                 for s in _array(packet.get("watchlist"), "watchlist", 1, 10)]
    if len(set(watchlist)) != len(watchlist) or any(not _SYMBOL.fullmatch(s) for s in watchlist):
        raise ContractValidationError("watchlist must contain unique normalized symbols")
    evidence = {}
    for row in _array(packet.get("evidence"), "evidence", 1, 1024):
        if not isinstance(row, Mapping):
            raise ContractValidationError("evidence entry must be an object")
        identity = _text(row.get("evidence_id"), "evidence_id", 256)
        if identity in evidence:
            raise ContractValidationError("duplicate evidence_id")
        _enum(row.get("kind"), {"HEADLINE", "PRICE_CONTEXT", "FEED_QUALITY"}, "evidence.kind")
        selected = [_enum(s, set(watchlist), "evidence.symbol")
                    for s in _array(row.get("symbols"), "evidence.symbols", 0, 10)]
        if len(set(selected)) != len(selected) or not isinstance(row.get("data"), Mapping):
            raise ContractValidationError("invalid evidence symbols or data")
        evidence[identity] = row
    return watchlist, evidence


def _citations(value, evidence, name, maximum=None):
    result = [_enum(v, set(evidence), name)
              for v in _array(value, name, 1, maximum or len(evidence))]
    if len(set(result)) != len(result):
        raise ContractValidationError(name + " contains duplicate evidence IDs")
    return result


def _parse(value):
    if isinstance(value, str):
        try:
            value = value.encode("utf-8")
        except UnicodeEncodeError as exc:
            raise ContractValidationError("response must be valid UTF-8") from exc
    if isinstance(value, bytes):
        if not 0 < len(value) <= MAX_RESPONSE_BYTES:
            raise ContractValidationError("response exceeds bounded JSON size")
        try:
            return parse_strict_json_object_bytes(value, document_name="Sentry synthesis response")
        except (ValueError, RecursionError, OverflowError) as exc:
            if isinstance(exc, ContractValidationError):
                raise
            raise ContractValidationError("response exceeds supported JSON parser limits") from exc
    return value


def _oracle(value, watchlist, evidence):
    result = _object(value, {"schema_version", "overview", "themes", "unresolved_questions"}, "Oracle draft")
    if result["schema_version"] not in {ORACLE_SCHEMA_VERSION, LEGACY_ORACLE_SCHEMA_VERSION}:
        raise ContractValidationError("unsupported Oracle draft schema_version")
    overview = _object(result["overview"], {"text", "evidence_ids"}, "overview")
    result["overview"] = {"text": _text(overview["text"], "overview.text", 600),
                          "evidence_ids": _citations(overview["evidence_ids"], evidence, "overview.evidence_ids")}
    themes, seen = [], set()
    for row in _array(result["themes"], "themes", 0, 3):
        theme = _object(row, {"theme_id", "title", "interpretation", "evidence_ids", "implications",
                              "alternative", "proposed_invalidation", "proposed_review_horizon"}, "theme")
        identity = _enum(theme["theme_id"], THEME_IDS, "theme_id")
        if identity in seen:
            raise ContractValidationError("duplicate theme_id")
        seen.add(identity)
        for field, maximum in (("title", 120), ("interpretation", 600), ("alternative", 400)):
            theme[field] = _text(theme[field], "theme." + field, maximum)
        theme["evidence_ids"] = _citations(theme["evidence_ids"], evidence, "theme.evidence_ids", 6)
        implications, symbols = [], set()
        for entry in _array(theme["implications"], "implications", 1, 10):
            implication = _object(entry, {"symbol", "linkage", "trading", "investment"}, "implication")
            symbol = _enum(implication["symbol"], set(watchlist), "implication.symbol")
            if symbol in symbols:
                raise ContractValidationError("duplicate implication symbol")
            symbols.add(symbol)
            linkage = _enum(implication["linkage"], LINKAGES, "linkage")
            if linkage == "DIRECT_MENTION" and not any(
                    evidence[i]["kind"] == "HEADLINE" and symbol in evidence[i]["symbols"]
                    for i in theme["evidence_ids"]):
                raise ContractValidationError("DIRECT_MENTION requires cited headline evidence for that symbol")
            implication["trading"] = _text(implication["trading"], "implication.trading", 300)
            implication["investment"] = _text(implication["investment"], "implication.investment", 300)
            implications.append(implication)
        theme["implications"] = implications
        if result["schema_version"] == LEGACY_ORACLE_SCHEMA_VERSION:
            if theme["proposed_invalidation"] is not None:
                theme["proposed_invalidation"] = _text(theme["proposed_invalidation"], "proposed_invalidation", 400)
        else:
            invalidation = _object(theme["proposed_invalidation"], {"status", "text"}, "proposed_invalidation")
            _enum(invalidation["status"], {"UNSPECIFIED", "PROPOSED"}, "proposed_invalidation.status")
            if invalidation["status"] == "UNSPECIFIED":
                if invalidation["text"] != "":
                    raise ContractValidationError("UNSPECIFIED invalidation requires explicitly empty text")
            else:
                invalidation["text"] = _text(invalidation["text"], "proposed_invalidation.text", 400)
            theme["proposed_invalidation"] = invalidation
        theme["proposed_review_horizon"] = _enum(theme["proposed_review_horizon"], HORIZONS, "proposed_review_horizon")
        themes.append(theme)
    result["themes"] = themes
    result["unresolved_questions"] = _texts(result["unresolved_questions"], "unresolved_questions", 5, 250)
    return result


def _challenge(value, evidence, draft):
    result = _object(value, {"schema_version", "draft_sha256", "reviews", "overall_limitations"}, "independent challenge")
    if result["schema_version"] not in {CHALLENGE_SCHEMA_VERSION, LEGACY_CHALLENGE_SCHEMA_VERSION}:
        raise ContractValidationError("unsupported challenge schema_version")
    if result["draft_sha256"] != sha256_bytes(canonical_json_bytes(draft)):
        raise ContractValidationError("challenge draft_sha256 differs from original validated draft")
    expected = {theme["theme_id"] for theme in draft["themes"]}
    reviews, seen = [], set()
    for row in _array(result["reviews"], "reviews", len(expected), len(expected)):
        review = _object(row, {"theme_id", "status", "reason", "evidence_ids", "alternative", "missing_evidence"}, "theme review")
        identity = _enum(review["theme_id"], expected, "review.theme_id")
        if identity in seen:
            raise ContractValidationError("duplicate theme review")
        seen.add(identity)
        review["status"] = _enum(review["status"], REVIEW_STATUSES, "review.status")
        review["reason"] = _text(review["reason"], "review.reason", 500)
        review["evidence_ids"] = _citations(review["evidence_ids"], evidence, "review.evidence_ids")
        review["alternative"] = _text(review["alternative"], "review.alternative", 400)
        review["missing_evidence"] = _texts(review["missing_evidence"], "missing_evidence", 3, 250)
        reviews.append(review)
    if seen != expected:
        raise ContractValidationError("challenge must cover every draft theme exactly once")
    result["reviews"] = reviews
    result["overall_limitations"] = _texts(result["overall_limitations"], "overall_limitations", 5, 250)
    return result


def validate_response(role, value, packet, draft=None):
    """Return a detached response with exact fields and packet-bound citations.

    Structural validation cannot authenticate sources, establish semantic truth,
    or turn model prose into approved research, a recommendation or an order.
    """
    _enum(role, ROLES, "role")
    watchlist, evidence = _packet(packet)
    value = _parse(value)
    if role == "oracle":
        if draft is not None:
            raise ContractValidationError("Oracle response must not receive another draft")
        return _oracle(value, watchlist, evidence)
    if draft is None:
        raise ContractValidationError("challenge requires the original Oracle draft")
    original = _oracle(_parse(draft), watchlist, evidence)
    return _challenge(value, evidence, original)


def _object_schema(properties):
    return {"type": "object", "additionalProperties": False,
            "properties": properties, "required": list(properties)}


def _text_schema(maximum):
    return {"type": "string", "minLength": 1, "maxLength": maximum}


def _array_schema(items, maximum, minimum=0):
    return {"type": "array", "items": items, "minItems": minimum, "maxItems": maximum}


def response_schema(role, packet, draft=None, *, version="v2"):
    """ModelDock-compatible v2 schema; v1 remains frozen for historical replay.

    V2 uses an explicit status/text object instead of a nullable union, because
    the local appliance's documented schema subset rejects combinators.
    No defaults or missing values are inserted by either version.
    """
    _enum(version, {"v1", "v2"}, "response schema version")
    _enum(role, ROLES, "role")
    watchlist, evidence = _packet(packet)
    citations = lambda maximum=None: _array_schema(
        {"type": "string", "enum": list(evidence)}, maximum or len(evidence), 1)
    if role == "oracle":
        if draft is not None:
            raise ContractValidationError("Oracle response must not receive another draft")
        return _object_schema({
            "schema_version": {"type": "string", "const": LEGACY_ORACLE_SCHEMA_VERSION if version == "v1" else ORACLE_SCHEMA_VERSION},
            "overview": _object_schema({"text": _text_schema(600), "evidence_ids": citations()}),
            "themes": _array_schema(_object_schema({
                "theme_id": {"type": "string", "enum": sorted(THEME_IDS)},
                "title": _text_schema(120), "interpretation": _text_schema(600),
                "evidence_ids": citations(6),
                "implications": _array_schema(_object_schema({
                    "symbol": {"type": "string", "enum": watchlist},
                    "linkage": {"type": "string", "enum": sorted(LINKAGES)},
                    "trading": _text_schema(300), "investment": _text_schema(300),
                }), 10, 1),
                "alternative": _text_schema(400),
                "proposed_invalidation": ({"anyOf": [{"type": "null"}, _text_schema(400)]} if version == "v1" else
                    _object_schema({"status": {"type": "string", "enum": ["UNSPECIFIED", "PROPOSED"]},
                                    "text": {"type": "string", "minLength": 0, "maxLength": 400}})),
                "proposed_review_horizon": {"type": "string", "enum": sorted(HORIZONS)},
            }), 3),
            "unresolved_questions": _array_schema(_text_schema(250), 5),
        })
    if draft is None:
        raise ContractValidationError("challenge requires the original Oracle draft")
    original = _oracle(_parse(draft), watchlist, evidence)
    theme_ids = [row["theme_id"] for row in original["themes"]]
    # Empty draft: maxItems=0 rejects every review. Avoid an invalid empty enum.
    theme_schema = {"type": "string", "enum": theme_ids} if theme_ids else _text_schema(20)
    return _object_schema({
        "schema_version": {"type": "string", "const": LEGACY_CHALLENGE_SCHEMA_VERSION if version == "v1" else CHALLENGE_SCHEMA_VERSION},
        "draft_sha256": {"type": "string", "const": sha256_bytes(canonical_json_bytes(original))},
        "reviews": _array_schema(_object_schema({
            "theme_id": theme_schema,
            "status": {"type": "string", "enum": sorted(REVIEW_STATUSES)},
            "reason": _text_schema(500), "evidence_ids": citations(),
            "alternative": _text_schema(400),
            "missing_evidence": _array_schema(_text_schema(250), 3),
        }), len(theme_ids), len(theme_ids)),
        "overall_limitations": _array_schema(_text_schema(250), 5),
    })
