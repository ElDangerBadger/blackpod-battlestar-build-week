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

# Canonical brief validation combines some checks in one guard. Keep those
# combinations explicit rather than pretending a failure identifies a word,
# field position, or narrower condition that the validator did not report.
_BRIEF_EXACT_RULES = {
    "draft: fields do not match the contract": ("fields_mismatch", "brief"),
    "unsupported draft schema": ("schema_version", "schema_version"),
    "paragraph: fields do not match the contract": ("fields_mismatch", "brief_paragraph"),
    "model prose: expected bounded nonblank plain text": ("bounded_plain_text", "brief_text"),
    "model prose contains unsupported numeric, markup, path, predictive, or action language": ("prose_guardrail", "brief_text"),
    "aggregate briefing cannot create symbol commentary": ("symbol_attribution", "brief_text"),
    "fact citations: expected bounded array": ("bounded_array", "fact_citations"),
    "fact citations: expected bounded nonblank plain text": ("bounded_plain_text", "fact_citations"),
    "fact citations: duplicate values": ("duplicate_values", "fact_citations"),
    "paragraph requires known fact citations": ("required_known_citations", "fact_citations"),
    "draft requires all ordered sections": ("sections_shape", "sections"),
    "section: fields do not match the contract": ("fields_mismatch", "section"),
    "section order or paragraph count invalid": ("section_order_or_paragraph_count", "sections"),
    "document exceeds the bounded byte limit": ("size_limit", "brief_document"),
    "value is not finite canonical JSON": ("canonical_json", "brief_document"),
}


class CanonicalBriefValidationError(ContractValidationError):
    """Trusted adapter for a rejection by the explicitly loaded brief contract.

    The producer catches its loaded module's error class by identity before
    creating this exception. Only fixed labels survive the adapter; neither
    raw prose nor the canonical error message is retained in this exception.
    This does not validate, repair, or accept any draft.
    """

    def __init__(self, error: Exception) -> None:
        self.diagnostic = _UNKNOWN
        if len(error.args) == 1 and type(error.args[0]) is str:
            self.diagnostic = _BRIEF_EXACT_RULES.get(error.args[0], _UNKNOWN)
        super().__init__("Canonical Oracle market brief failed contract validation")


def narrative_validation_message(error: Exception) -> str:
    """Return only fixed, allowlisted diagnostic labels, never exception text.

    ``narrative_text`` is an honest aggregate field label where the existing
    validator reports a rule across prose/facts but does not identify one field.
    Unknown validator errors remain explicitly unclassified.
    """

    rule, field = _classify(error)
    return f"{_BASE_MESSAGE} (rule={rule}; field={field})."


def _classify(error: Exception) -> tuple[str, str]:
    if type(error) is CanonicalBriefValidationError:
        # Return the allowlist's own labels, even if a caller modified the
        # exception. Never trust arbitrary fields attached to other errors.
        if type(error.diagnostic) is tuple and error.diagnostic in _BRIEF_EXACT_RULES.values():
            return error.diagnostic
        return _UNKNOWN
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
