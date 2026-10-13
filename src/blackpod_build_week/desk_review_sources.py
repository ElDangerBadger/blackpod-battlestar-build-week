"""Pure verification of frozen market captures and declared issuer research.

Hashes prove retained bytes and bindings, not provider identity or economic
truth. Issuer excerpts bind a reviewed interpretation to a public source; they
do not establish an independent forecast, attractive valuation or trading edge.
"""
from datetime import date
from urllib.parse import urlsplit

from .contracts.decision_journal import _object, _string
from .contracts.mission_request import parse_rfc3339, parse_strict_json_object_bytes
from .contracts.trading_reconciliation import evidence_reference, symbol_text
from .hashing import sha256_bytes


def _blob(blobs, reference):
    reference = evidence_reference(reference)
    raw = blobs.get(reference["sha256"])
    if not isinstance(raw, bytes) or len(raw) != reference["size_bytes"] or sha256_bytes(raw) != reference["sha256"]:
        raise ValueError("research source evidence is missing or differs in size/hash")
    return raw


def _refs(value):
    if not isinstance(value, list) or not value or len(value) > 128:
        raise ValueError("research source references must be an explicit bounded nonempty list")
    refs = [evidence_reference(reference) for reference in value]
    if len({ref["path"] for ref in refs}) != len(refs):
        raise ValueError("research source paths must be unique")
    return refs


def validate_market_packet(packet, blobs):
    packet = _object(packet, {"schema_version", "captured_at", "feed", "adjustment", "snapshots", "bars", "source_evidence"}, "shadow market packet")
    if packet["schema_version"] != "blackpod.shadow_market_packet.v1" or packet["feed"] != "IEX" or packet["adjustment"] != "RAW":
        raise ValueError("shadow market packet requires explicit IEX/RAW observations")
    parse_rfc3339(packet["captured_at"], "market captured_at")
    if not isinstance(packet["snapshots"], dict) or not isinstance(packet["bars"], dict) or not 1 <= len(packet["snapshots"]) <= 128:
        raise ValueError("market symbol maps must be explicit and bounded")
    if set(packet["snapshots"]) != set(packet["bars"]):
        raise ValueError("market snapshots and daily history must cover the same explicit symbols")
    for symbol in packet["snapshots"]:
        symbol_text(symbol)
        if not isinstance(packet["snapshots"][symbol], dict) or not isinstance(packet["bars"][symbol], list) or len(packet["bars"][symbol]) > 10000:
            raise ValueError("market symbol observations exceed the supported shape")
    snapshots, bars = None, None
    for reference in _refs(packet["source_evidence"]):
        raw = parse_strict_json_object_bytes(_blob(blobs, reference))
        if "bars" in raw:
            if bars is not None or raw.get("next_page_token") is not None:
                raise ValueError("bar capture must be one fully retained page without a continuation token")
            bars = raw["bars"]
        elif "snapshots" in raw:
            if snapshots is not None:
                raise ValueError("snapshot capture has ambiguous source maps")
            snapshots = raw["snapshots"]
        elif raw and all(isinstance(value, dict) and "latestQuote" in value for value in raw.values()):
            if snapshots is not None:
                raise ValueError("snapshot capture has ambiguous source maps")
            snapshots = raw
        else:
            raise ValueError("unsupported market raw capture; source roles must be explicit")
    if snapshots != packet["snapshots"] or bars != packet["bars"]:
        raise ValueError("normalized market observations differ from retained provider maps")
    return packet


def validate_issuer_packet(packet, blobs):
    packet = _object(packet, {"schema_version", "captured_at", "facts", "source_evidence"}, "shadow issuer facts")
    if packet["schema_version"] != "blackpod.shadow_issuer_facts.v1":
        raise ValueError("unsupported issuer facts schema")
    cutoff = parse_rfc3339(packet["captured_at"], "issuer captured_at")
    refs = _refs(packet["source_evidence"])
    retained = {(ref["path"], ref["sha256"], ref["size_bytes"]) for ref in refs}
    if not isinstance(packet["facts"], list) or not 1 <= len(packet["facts"]) <= 128:
        raise ValueError("issuer facts must be an explicit bounded list")
    identities = set()
    for entry in packet["facts"]:
        fact = _object(entry, {"symbol", "fund_name", "issuer", "mandate", "asset_class", "structure", "corporate_action_before_horizon", "source_url", "as_of", "source_excerpt", "source_evidence"}, "issuer fact")
        symbol = symbol_text(fact["symbol"])
        if symbol in identities:
            raise ValueError("issuer facts contain duplicate symbols")
        identities.add(symbol)
        for field in ("fund_name", "issuer", "mandate", "source_excerpt"):
            _string(fact[field], field, 2048)
        if fact["structure"] not in {"ETF", "ETN"} or fact["asset_class"] not in {"BROAD_EQUITY", "LOW_VOL_EQUITY", "FACTOR_EQUITY", "SECTOR_EQUITY", "VOLATILITY_DERIVATIVE"}:
            raise ValueError("unsupported explicit instrument structure or exposure class")
        if type(fact["corporate_action_before_horizon"]) is not bool:
            raise ValueError("corporate action assessment must be explicitly boolean")
        try:
            as_of = date.fromisoformat(fact["as_of"])
        except (TypeError, ValueError):
            raise ValueError("issuer as_of must be an explicit calendar date") from None
        if as_of > cutoff.date():
            raise ValueError("issuer facts cannot postdate their capture")
        parsed = urlsplit(fact["source_url"])
        if (parsed.scheme != "https" or parsed.hostname not in {"www.ssga.com", "www.ishares.com", "www.invesco.com", "www.sec.gov", "www.federalreserve.gov"}
                or parsed.username or parsed.password or parsed.port not in (None, 443)):
            raise ValueError("issuer facts require an explicit primary HTTPS source")
        reference = evidence_reference(fact["source_evidence"])
        if (reference["path"], reference["sha256"], reference["size_bytes"]) not in retained:
            raise ValueError("issuer row source is not retained by the packet")
        source = _object(parse_strict_json_object_bytes(_blob(blobs, reference)), {"schema_version", "source_url", "retrieved_at", "content"}, "public issuer source")
        if source["schema_version"] != "blackpod.public_issuer_source.v1" or source["source_url"] != fact["source_url"]:
            raise ValueError("issuer source URL or schema differs from the factual binding")
        retrieved = parse_rfc3339(source["retrieved_at"], "issuer retrieved_at")
        if retrieved > cutoff or not isinstance(source["content"], str) or fact["source_excerpt"] not in source["content"]:
            raise ValueError("issuer excerpt or retrieval timestamp differs from retained evidence")
    for reference in refs:
        _blob(blobs, reference)
    return packet
