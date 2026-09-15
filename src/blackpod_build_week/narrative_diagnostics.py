"""Bounded, non-content diagnostics for rejected ModelDock narratives.

Contract errors may contain model-authored field names, values, IDs, words, or
paths. None of that text is suitable for provenance. Classify only known
validator messages into fixed rule/field tokens; never serialize the exception.
These diagnostics explain a rejection and cannot make invalid content valid.
"""

from __future__ import annotations

import re

from .contracts.mission_request import ContractValidationError


_BASE_MESSAGE = "ModelDock narrative failed its versioned contract validation"
_UNKNOWN = ("unclassified", "narrative")
_TEXT_FIELDS = (
    "summary", "interpretation", "uncertainties", "confidence_explanation",
    "warnings",
)
_MESSAGE_RULES = (
    ("Oracle narrative selection is missing fields:", "required_fields", "selection"),
    ("Oracle narrative selection contains unknown fields:", "unknown_fields", "selection"),
    ("unsupported Oracle narrative selection schema_version:", "schema_version", "schema_version"),
    ("Oracle narrative is missing fields:", "required_fields", "narrative"),
    ("Oracle narrative contains unknown fields:", "unknown_fields", "narrative"),
    ("unsupported Oracle narrative schema_version:", "schema_version", "schema_version"),
    ("ModelDock selected an unknown Oracle fact ID:", "unknown_fact_id", "selected_fact_ids"),
    ("Oracle narrative contains vocabulary absent from the validated Oracle input:", "source_vocabulary", "narrative_text"),
    ("Oracle narrative free text may not contain numeric claims;", "numeric_claim", "narrative_text"),
    ("Oracle narrative contains a factual readiness, diagnostic, posture, or momentum claim not supported by Oracle evidence", "unsupported_claim", "narrative_text"),
    ("Oracle narrative contains an empty factual assertion", "unsupported_claim", "narrative_text"),
    ("mission symbol is correlation-only because no Oracle evidence attributes facts to that symbol", "symbol_attribution", "narrative_text"),
    ("Oracle narrative contains a Governor disposition or approval claim", "prohibited_authority", "narrative_text"),
    ("Oracle narrative contains an order, execution, or trading recommendation", "prohibited_authority", "narrative_text"),
    ("Oracle narrative correlation mismatch", "correlation", "narrative"),
    ("Oracle fact catalog correlation mismatch", "correlation", "selected_fact_ids"),
)
_EXACT_RULES = {
    "Oracle narrative selection must be an object": ("invalid_type", "selection"),
    "Oracle narrative must be an object": ("invalid_type", "narrative"),
    "selected_fact_ids must be an array": ("invalid_type", "selected_fact_ids"),
    "selected_fact_ids must not be empty": ("required_value", "selected_fact_ids"),
    "selected_fact_ids contains duplicates": ("duplicate_values", "selected_fact_ids"),
    "prohibited_actions_acknowledged must be true": ("safety_acknowledgement", "prohibited_actions_acknowledged"),
}
_TEXT_RULES = (
    (r"must be a string|must be an array", "invalid_type"),
    (r"must be nonblank", "required_value"),
    (r"may not have surrounding whitespace", "surrounding_whitespace"),
    (r"exceeds \d+ (?:characters|entries)", "size_limit"),
    (r"must contain valid UTF-8 text", "invalid_encoding"),
    (r"contains unsupported control text", "control_text"),
    (r"contains duplicate entries", "duplicate_values"),
    (r"contains an absolute local path", "local_path"),
    (r"contains credential- or secret-like text", "sensitive_text"),
)


def narrative_validation_message(error: Exception) -> str:
    """Return only fixed, allowlisted diagnostic labels, never exception text.

    ``narrative_text`` is an honest aggregate field label where the existing
    validator reports a rule across prose/facts but does not identify one field.
    Unknown validator errors remain explicitly unclassified.
    """

    rule, field = _classify(error)
    return f"{_BASE_MESSAGE} (rule={rule}; field={field})."


def _classify(error: Exception) -> tuple[str, str]:
    if not isinstance(error, ContractValidationError):
        return _UNKNOWN
    # Known contract errors are ordinary ValueErrors. Avoid formatting custom
    # exception objects or inspecting an unbounded/model-authored payload.
    if len(error.args) != 1 or type(error.args[0]) is not str:
        return _UNKNOWN
    message = error.args[0][:8192]
    if message in _EXACT_RULES:
        return _EXACT_RULES[message]
    for prefix, rule, field in _MESSAGE_RULES:
        if message.startswith(prefix):
            return rule, field
    if re.fullmatch(r"selected_fact_ids\[\d+\] is not a canonical fact ID", message):
        return "fact_id_format", "selected_fact_ids"
    if re.fullmatch(r"selected_fact_ids exceeds \d+ entries", message):
        return "size_limit", "selected_fact_ids"
    for field in _TEXT_FIELDS:
        match = re.fullmatch(
            rf"(?:Oracle narrative(?: selection)?\.)?{field}(?:\[\d+\])? (.+)",
            message,
        )
        if match is not None:
            for pattern, rule in _TEXT_RULES:
                if re.fullmatch(pattern, match.group(1)):
                    return rule, field
    return _UNKNOWN
