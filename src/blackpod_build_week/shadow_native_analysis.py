"""Provider-free, source-pinned reuse of BlackPod's passive native analysis.

The captured files are evidence. Only the reviewed pure definitions below are
compiled, in private namespaces with an explicit standard-library closure.
Native packages, module initializers, CLIs, providers and workflows are never
imported. This is a separate SHADOW calculation, not a canonical mission run.
"""
from __future__ import annotations

import ast
import builtins
import __future__
from collections.abc import Mapping
from dataclasses import dataclass, field, fields, is_dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import hashlib
import json
import math
from pathlib import Path
import re
from types import MappingProxyType
from typing import Any

from .contracts.mission_request import parse_rfc3339, parse_strict_json_object_bytes
from .hashing import canonical_json_bytes, sha256_bytes
from .sentry_history_cache import RecoveryError, read_regular

SCHEMA = "blackpod.shadow_native_analysis.v1"
MARKET_SCHEMA = "blackpod.shadow_market_packet.v1"
FLEET_SYMBOLS = (
    "XLK", "XLF", "XLE", "XLV", "XLI", "XLP", "XLY", "XLU", "XLB",
    "XLRE", "XLC", "SPY", "QQQ", "DIA", "VXZ", "IWF", "IWD", "IWM",
    "MTUM", "USMV", "QUAL",
)
MAX_SOURCE_BYTES = 256 * 1024
MAX_PACKET_BYTES = 4 * 1024 * 1024
AUTHORITY = {
    "execution_authority_granted": False, "capital_allocation_authority_granted": False,
    "policy_change_authority_granted": False, "auto_trading_enabled": False,
}

# Filled with reviewed whole-file hashes below. Unknown code cannot be executed
# merely because it lives at a caller-supplied path or has a matching manifest.
SOURCE_PINS: Mapping[str, str] = MappingProxyType({
    "blackpod/advisors/oracle_assessment.py": "26fce2dea95cb5e888039ae73309c2ce34d05573d1d5365981194a2e7a580460",
    "blackpod/advisors/oracle_measurement_diagnostics.py": "4cffdcf31cda5e3d707d55b7c97e3052b17686f5d30b454e2a55b1d913ea50b0",
    "blackpod/advisors/oracle_measurements.py": "8022b733b75c55a1ed82801001b41c0b883cd6021619aa7ae2c112f6132e38a7",
    "blackpod/advisors/oracle_narrative.py": "8c6f4d2bf5f5dd5dfbaf91cf928785111557c43d6234a1be4cd860fb2f192661",
    "blackpod/advisors/oracle_report.py": "a936c9eb0be49decf3209a7a20fd0250d42890ecc02afacc5ca50842e15e470e",
    "blackpod/advisors/senate_candidate_intake.py": "2ea20094f5e5a55f38b670bbba006f8f131ae91d7ac239d0426d1e48f8bff0d4",
    "blackpod/advisors/senate_deliberation.py": "3c2c4a38221f94947c639e3d4a0635ea8ffea1404f2eef99d960fb995bfbf9a8",
    "blackpod/advisors/trading_candidate_generator.py": "b76d7b8e84ef650da70c9ad44dff022f3c36d83c9f5bffdea242a3bfa1f00ef3",
    "blackpod/contracts/_validation.py": "df7d9021770ee06efe73b5d2292763d1ed6a000f619173de2029206a3557b93e",
    "blackpod/contracts/advisor_snapshot_input.py": "51741ea09ab37206abda4a321a59b571f11fadbd8202839b1d8f984db4db3156",
    "blackpod/contracts/fleet_snapshot.py": "9ab74c898b66e6d30b7c04d15477479527bf1d37708741d03ba2e1b8f99f4bdd",
    "blackpod/contracts/fleet_snapshot_readiness.py": "638d8e168dcc40d998ff90aa5efa6faea6e4a25b24d2fe5ef1cbf0d7927c89b5",
    "blackpod/contracts/normalized_fleet_snapshot.py": "d8146783fb849fdd6150d8524f1810f878df6ab020a9f63de597afd5e2b31507",
    "blackpod/contracts/oracle_assessment.py": "3b64d5346513ba3be9f847a9afd89640c75cf054ac6b4d9917a8e0f26916f885",
    "blackpod/contracts/oracle_measurement_diagnostics.py": "f46843899b09a9eba026450e525a14a0da277502d198918fde70fb3f3c038524",
    "blackpod/contracts/oracle_measurements.py": "b4d4b80ba95bf8ca37e3ea9b61b5ce63e0d3013ccb692fbb435b87816cec2b52",
    "blackpod/contracts/oracle_narrative.py": "ddbeec15f1df3d0380711e159117c923d8da49e04ff2e62e46173a89dddfc7b2",
    "blackpod/contracts/oracle_report.py": "aad5c9881f380b10e974d3a8bde5e86b72072fcf48d6348ef591dbb96f3b6af1",
    "blackpod/contracts/senate_deliberation.py": "8184d165602447042e096d196d7df3a3ae6bef0470ea6fb308e09666e841f5fb",
    "blackpod/contracts/senate_review_packet.py": "e7c1638d029996576d52e17b92fa43299e16f017d5b5809ed4d0b960d0ba5eab",
    "blackpod/contracts/trading_candidate.py": "0ddacbba2b5da6e963933cc8f2f05397063adcd17c5b8567f8916eaf4e8e5e9f",
    "blackpod/contracts/trading_candidate_report.py": "93a53a0fd95700281007ed3a759ab0290acdfadff04f64e21faad30b48669caf",
    "blackpod/runtime/fleet_snapshot_normalizer.py": "4f7844d15c477699364f37fc031231336779c9bee2b9810d177442ec1ad20d4f",
    "blackpod/storage/hash.py": "dba39c64ef06d698752dee8504bebca537b6fdb76d94d443eee445d3750b5938"
})

_CONTRACTS = (
    "_validation", "fleet_snapshot", "normalized_fleet_snapshot",
    "fleet_snapshot_readiness", "advisor_snapshot_input", "oracle_measurements",
    "oracle_measurement_diagnostics", "oracle_assessment", "oracle_narrative",
    "oracle_report", "trading_candidate", "trading_candidate_report",
    "senate_review_packet", "senate_deliberation",
)
_FUNCTIONS = {
    "blackpod/storage/hash.py": ("sha256_text",),
    "blackpod/runtime/fleet_snapshot_normalizer.py": (
        "normalize_fleet_snapshot", "_normalize_symbol", "_source_fields", "_coerce_alias",
        "_first_alias", "_coerce_number", "_string_alias", "_pct_change", "_range_pct",
        "_snapshot_to_dict", "_raw_symbols", "_canonical",
    ),
    "blackpod/advisors/oracle_measurements.py": (
        "build_oracle_measurements_from_snapshot_input", "_blocked_snapshot_measurements",
        "_snapshot_input_hash", "_snapshot_return_map", "_normalized_return_value",
        "_is_finite_number", "_source_snapshot_ref", "_build_measurements", "_breadth_score",
        "_leadership_concentration", "_sector_dispersion", "_rotation_velocity",
        "_group_strength", "_ranks", "_percentile_scores", "_bounded",
    ),
    "blackpod/advisors/oracle_measurement_diagnostics.py": (
        "build_oracle_measurement_diagnostics", "_diagnostic_items", "_provenance_complete",
        "_symbol_messages", "_is_diagnostic_warning", "_text_tuple", "_string_map", "_first_text",
    ),
    "blackpod/advisors/oracle_assessment.py": (
        "build_oracle_assessment", "_assessment_provenance", "_breadth_posture",
        "_leadership_posture", "_rotation_posture", "_risk_regime_posture", "_confidence",
    ),
    "blackpod/advisors/oracle_narrative.py": (
        "build_oracle_narrative", "_narrative_provenance", "_summary", "_breadth_commentary",
        "_leadership_commentary", "_rotation_commentary", "_risk_regime_commentary",
    ),
    "blackpod/advisors/oracle_report.py": (
        "build_oracle_report", "_headline", "_summary", "_sentence_case", "_key_measurements",
        "_assessment_summary", "_narrative_summary", "_source_refs", "_provenance",
        "_report_as_of", "_missing_warnings", "_dedupe",
    ),
    "blackpod/advisors/trading_candidate_generator.py": (
        "build_trading_candidates", "build_trading_candidate_report", "_candidate_for_symbol",
        "_average_return", "_state_counts",
    ),
    "blackpod/advisors/senate_candidate_intake.py": (
        "build_senate_review_packet", "_review_candidate", "_attention_state",
        "_attention_reason", "_oracle_context", "_attention_counts",
    ),
    "blackpod/advisors/senate_deliberation.py": (
        "build_senate_deliberation", "_deliberation_item", "_deliberation_state",
        "_deliberation_reason", "_market_context_phrase", "_oracle_blocks", "_market_context",
        "_deliberation_counts",
    ),
}
_OUTPUTS = (
    "normalized_snapshot", "shadow_input_readiness", "oracle_measurements", "oracle_diagnostics",
    "oracle_assessment", "oracle_narrative", "oracle_report", "trading_candidate_report",
    "senate_review_packet", "senate_deliberation",
)
_LIMITATIONS = (
    "SHADOW_RECOMPUTATION_NOT_CANONICAL_MISSION",
    "ORACLE_CANDIDATE_AND_SENATE_SHARE_MARKET_EVIDENCE",
    "NATIVE_CONFIDENCE_LABELS_ARE_NOT_SUCCESS_PROBABILITIES",
    "NO_CONNECTED_BRIGADE_SPYGLASS_OR_PREDICTIVE_FORECASTS",
    "NO_FUNDAMENTAL_VALUATION_OR_LONG_HORIZON_THESIS_PROOF",
    "IEX_QUOTES_ARE_NOT_CONSOLIDATED_MARKET_QUOTES",
    "READINESS_CHECKS_INPUT_GEOMETRY_NOT_PROVIDER_ATTESTATION",
    "NO_EXECUTION_OR_POLICY_AUTHORITY",
)


class NativeAnalysisError(ValueError):
    """Unsupported inputs or code fail before any native calculation."""


def capture_native_sources(battlestar_root: Path) -> dict[str, bytes]:
    """Read only the exact reviewed source closure; no native imports or writes."""
    root = Path(battlestar_root).absolute()
    try:
        result = {path: read_regular(root / path, max_bytes=MAX_SOURCE_BYTES) for path in SOURCE_PINS}
        _validate_sources(result)
        # Re-read to reject a mixed-vintage source closure during concurrent edits.
        for path, raw in result.items():
            if read_regular(root / path, max_bytes=MAX_SOURCE_BYTES) != raw:
                raise NativeAnalysisError("native source changed during capture")
    except RecoveryError as exc:
        raise NativeAnalysisError("native source cannot be captured safely") from exc
    return result


def _validate_sources(sources: Mapping[str, bytes]) -> None:
    if not isinstance(sources, Mapping) or set(sources) != set(SOURCE_PINS):
        raise NativeAnalysisError("native code must contain the exact reviewed closure")
    for path, expected in SOURCE_PINS.items():
        raw = sources[path]
        if not isinstance(raw, bytes) or not 0 < len(raw) <= MAX_SOURCE_BYTES or sha256_bytes(raw) != expected:
            raise NativeAnalysisError(f"native source pin mismatch: {path}")


class _RemoveImports(ast.NodeTransformer):
    def visit_Import(self, node):
        # The only reviewed nested import is normalizer._canonical's stdlib
        # json; it is bound in the namespace instead of resolving packages.
        if any(alias.name != "json" or alias.asname is not None for alias in node.names):
            raise NativeAnalysisError("native selected definition imports outside its closure")
        return None

    def visit_ImportFrom(self, node):
        raise NativeAnalysisError("native selected definition contains an unexpected nested import")


def _namespace(raw: bytes, path: str, dependencies: Mapping[str, Any], functions=None) -> dict[str, Any]:
    tree = ast.parse(raw.decode("utf-8"), filename=path)
    chosen = []
    found = set()
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.ClassDef)):
            if functions is None or node.name in functions:
                if functions is None and node.name == "utc_now_iso":
                    continue
                chosen.append(node)
                found.add(node.name)
        elif isinstance(node, ast.Assign):
            # Contract sets and reviewed analytical constants are literal
            # expressions. Never execute a module-level call/assignment from
            # an unrelated advisor or its operational entry point.
            if all(isinstance(target, ast.Name) and target.id.isupper() for target in node.targets):
                chosen.append(node)
    if functions is not None and found != set(functions):
        raise NativeAnalysisError(f"native analytical definition closure changed: {path}")
    selected = ast.Module(body=chosen, type_ignores=[])
    # Future annotations is a compiler flag, so even __future__ imports do not
    # execute. Remove/reject nested imports in the selected definitions.
    for index in range(len(selected.body)):
        selected.body[index] = _RemoveImports().visit(selected.body[index])
    ast.fix_missing_locations(selected)
    namespace = {
        "__name__": __name__, "__builtins__": {name: getattr(builtins, name) for name in (
            "__build_class__", "object", "str", "int", "float", "bool", "dict", "list", "tuple",
            "set", "frozenset", "len", "any", "all", "sum", "min", "max", "sorted", "enumerate",
            "zip", "round", "abs", "isinstance", "hasattr", "getattr", "type", "property", "range",
            "ValueError", "TypeError", "Exception",
        )},
        "dataclass": dataclass, "field": field, "fields": fields, "is_dataclass": is_dataclass,
        "Any": Any, "json": json, "math": math, "re": re, "hashlib": hashlib,
        **dict(dependencies),
    }
    exec(compile(selected, path, "exec", flags=__future__.annotations.compiler_flag, dont_inherit=True), namespace)
    return namespace


def _load_native(sources: Mapping[str, bytes]) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    _validate_sources(sources)
    shared: dict[str, Any] = {}
    for name in _CONTRACTS:
        path = f"blackpod/contracts/{name}.py"
        namespace = _namespace(sources[path], path, shared)
        for key, value in namespace.items():
            if key[0].isupper() or key in {"require_dataclass_text_fields", "require_probability", "require_text", "require_non_negative"}:
                shared[key] = value
    modules = {}
    for path, selected in _FUNCTIONS.items():
        namespace = _namespace(sources[path], path, shared, selected)
        modules[path] = namespace
        if path == "blackpod/storage/hash.py":
            shared["sha256_text"] = namespace["sha256_text"]
    return shared, modules


def _number(value: object, name: str, *, allow_zero: bool = False) -> float:
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        raise NativeAnalysisError(f"{name} must be a finite numeric value")
    try:
        parsed = Decimal(str(value))
    except InvalidOperation as exc:
        raise NativeAnalysisError(f"{name} must be finite") from exc
    if not parsed.is_finite() or parsed < 0 or (parsed == 0 and not allow_zero) or parsed > Decimal("1000000000000"):
        raise NativeAnalysisError(f"{name} is outside supported bounds")
    return float(parsed)


def _stamp(value: object, name: str) -> datetime:
    if not isinstance(value, str):
        raise NativeAnalysisError(f"{name} requires an explicit timestamp")
    try:
        # Alpaca supplies nanosecond timestamps. Keep the original string in
        # evidence/native symbol fields; datetime comparisons use microseconds.
        comparable = re.sub(r"(\.\d{6})\d{1,3}(?=Z$|[+-]\d{2}:\d{2}$)", r"\1", value)
        return parse_rfc3339(comparable, name)
    except ValueError as exc:
        raise NativeAnalysisError(str(exc)) from exc


def _raw_snapshot(market: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(market, Mapping) or market.get("schema_version") != MARKET_SCHEMA or market.get("feed") != "IEX" or market.get("adjustment") != "RAW":
        raise NativeAnalysisError("native shadow analysis requires a raw IEX market packet")
    captured = _stamp(market.get("captured_at"), "market captured_at")
    snapshots = market.get("snapshots")
    if not isinstance(snapshots, dict) or not set(FLEET_SYMBOLS) <= set(snapshots):
        raise NativeAnalysisError("native Oracle fleet requires all 21 configured proxy symbols")
    if not isinstance(market.get("bars"), dict) or not isinstance(market.get("source_evidence"), list):
        raise NativeAnalysisError("market packet is missing retained bars or source evidence")
    digest = sha256_bytes(canonical_json_bytes(dict(market)))
    symbols = []
    for symbol in FLEET_SYMBOLS:
        snapshot = snapshots[symbol]
        if not isinstance(snapshot, dict):
            raise NativeAnalysisError(f"missing market snapshot: {symbol}")
        trade, daily, previous = (snapshot.get(key) for key in ("latestTrade", "dailyBar", "prevDailyBar"))
        if not all(isinstance(item, dict) for item in (trade, daily, previous)):
            raise NativeAnalysisError(f"snapshot requires trade, daily and previous bars: {symbol}")
        trade_at, daily_at, previous_at = (_stamp(item.get("t"), symbol + " source timestamp") for item in (trade, daily, previous))
        if max(trade_at, daily_at, previous_at) > captured or previous_at >= daily_at:
            raise NativeAnalysisError(f"snapshot source timestamps are inconsistent: {symbol}")
        price = _number(trade.get("p"), symbol + " last trade")
        prior = _number(previous.get("c"), symbol + " previous close")
        open_value, high, low, close = (_number(daily.get(key), symbol + " daily " + key) for key in ("o", "h", "l", "c"))
        if not low <= min(open_value, close) <= max(open_value, close) <= high:
            raise NativeAnalysisError(f"daily OHLC geometry is inconsistent: {symbol}")
        volume = _number(daily.get("v"), symbol + " daily volume", allow_zero=True)
        symbols.append({"symbol": symbol, "price": price, "timestamp": trade["t"], "fields": {
            "price": price, "previous_close": prior, "open": open_value, "high": high, "low": low,
            "volume": volume, "timestamp": trade["t"], "provider": "alpaca", "feed": "IEX",
            "adjustment": "RAW", "daily_bar_at": daily["t"], "previous_daily_bar_at": previous["t"],
            "source_path": "market_packet.json", "source_sha256": digest,
        }, "warnings": []})
    return {
        "snapshot_id": "shadow-alpaca-snapshot-" + digest,
        "generated_at": market["captured_at"], "as_of": market["captured_at"],
        "fleet_id": "fleet-oracles-vapors-example", "symbols": symbols, "warnings": [], "blockers": [],
    }


def derive_native_analysis(market: Mapping[str, Any], source_bytes: Mapping[str, bytes]) -> dict[str, Any]:
    """Recompute the exact reviewed native analytical rules over frozen inputs.

    Input completeness is a SHADOW adapter gate, not canonical mission readiness
    or a claim that the IEX provider is independently attested. Prices retain
    source timestamps; freshness for prospective sizing belongs to the caller.
    The native generated_at fields use the frozen market clock for deterministic
    replay; they are not a wall-clock processing-time attestation. The separate
    review records its actual submission time.
    """
    raw = _raw_snapshot(market)
    contracts, modules = _load_native(source_bytes)
    generated = market["captured_at"]
    normalized = modules["blackpod/runtime/fleet_snapshot_normalizer.py"]["normalize_fleet_snapshot"](raw)
    input_digest = sha256_bytes(canonical_json_bytes(dict(market)))
    readiness = contracts["FleetSnapshotReadiness"](
        readiness_id="shadow-input-readiness-" + input_digest,
        generated_at=generated, fleet_id=normalized.fleet_id, source_snapshot_id=normalized.source_snapshot_id,
        normalized_snapshot_id=normalized.normalized_snapshot_id, quality_report_id="shadow-complete-finite-input-" + input_digest,
        readiness_state="READY", coverage_ok=True, freshness_ok=False, completeness_ok=True,
        downstream_ready=True,
    )
    snapshot_input = contracts["AdvisorSnapshotInput"](
        input_id="shadow-advisor-input-" + input_digest, generated_at=generated, advisor_name="oracle",
        fleet_id=normalized.fleet_id, normalized_snapshot_id=normalized.normalized_snapshot_id,
        readiness_id=readiness.readiness_id, symbols=FLEET_SYMBOLS, as_of=generated, approved_for_reasoning=True,
    )
    measurements = modules["blackpod/advisors/oracle_measurements.py"]["build_oracle_measurements_from_snapshot_input"](snapshot_input, normalized, generated_at=generated)
    diagnostics = modules["blackpod/advisors/oracle_measurement_diagnostics.py"]["build_oracle_measurement_diagnostics"](measurements, snapshot_input, normalized, readiness, generated_at=generated)
    assessment = modules["blackpod/advisors/oracle_assessment.py"]["build_oracle_assessment"](
        measurements, generated_at=generated, source_path="oracle_measurements.json",
        source_sha256=sha256_bytes(canonical_json_bytes(measurements.to_dict())), diagnostics=diagnostics,
    )
    narrative = modules["blackpod/advisors/oracle_narrative.py"]["build_oracle_narrative"](
        assessment, generated_at=generated, source_path="oracle_assessment.json",
        source_sha256=sha256_bytes(canonical_json_bytes(assessment.to_dict())),
    )
    report = modules["blackpod/advisors/oracle_report.py"]["build_oracle_report"](
        measurement=measurements, diagnostics=diagnostics, assessment=assessment, narrative=narrative,
        generated_at=generated, source_refs={"input_path": "market_packet.json", "input_sha256": input_digest},
    )
    candidate = modules["blackpod/advisors/trading_candidate_generator.py"]["build_trading_candidate_report"](normalized, readiness, generated_at=generated)
    review = modules["blackpod/advisors/senate_candidate_intake.py"]["build_senate_review_packet"](candidate, oracle_report=report.to_dict(), generated_at=generated)
    senate = modules["blackpod/advisors/senate_deliberation.py"]["build_senate_deliberation"](review, report, generated_at=generated)
    payload = {
        "schema_version": SCHEMA, "generated_at": generated, "input_sha256": input_digest,
        "source_fingerprints": dict(SOURCE_PINS),
        "source_evidence": [{"path": "native_analysis_code/" + path, "sha256": digest,
                             "size_bytes": len(source_bytes[path])} for path, digest in SOURCE_PINS.items()],
        "method": "REVIEWED_NATIVE_PURE_DEFINITIONS_SHADOW_REPLAY",
        "evidence_ancestry": "SAME_FROZEN_MARKET_PACKET",
        "confidence_semantics": "NATIVE_HEURISTIC_LABEL_NOT_FORECAST_PROBABILITY",
        "canonical_mission_run": False, "provider_identity_attested": False,
        "limitations": list(_LIMITATIONS), "authority": dict(AUTHORITY),
        "outputs": {key: value.to_dict() for key, value in zip(_OUTPUTS, (
            normalized, readiness, measurements, diagnostics, assessment, narrative, report, candidate, review, senate,
        ))},
    }
    payload["analysis_id"] = "shadow-native-analysis-" + sha256_bytes(canonical_json_bytes(payload))
    return NativeAnalysisPacket.from_mapping(payload).to_dict()


@dataclass(frozen=True, slots=True)
class NativeAnalysisPacket:
    """Strict transport wrapper; replay establishes the derived content."""
    _raw: bytes

    @classmethod
    def from_mapping(cls, value: object) -> "NativeAnalysisPacket":
        keys = {"schema_version", "analysis_id", "generated_at", "input_sha256", "source_fingerprints", "source_evidence", "method", "evidence_ancestry", "confidence_semantics", "canonical_mission_run", "provider_identity_attested", "limitations", "authority", "outputs"}
        if not isinstance(value, dict) or set(value) != keys:
            raise NativeAnalysisError("native analysis packet fields differ from the supported contract")
        _stamp(value["generated_at"], "native generated_at")
        if (value["schema_version"] != SCHEMA or value["method"] != "REVIEWED_NATIVE_PURE_DEFINITIONS_SHADOW_REPLAY"
                or value["evidence_ancestry"] != "SAME_FROZEN_MARKET_PACKET"
                or value["confidence_semantics"] != "NATIVE_HEURISTIC_LABEL_NOT_FORECAST_PROBABILITY"
                or value["canonical_mission_run"] is not False or value["provider_identity_attested"] is not False
                or value["limitations"] != list(_LIMITATIONS) or value["authority"] != AUTHORITY
                or any(type(item) is not bool or item for item in value["authority"].values())
                or value["source_fingerprints"] != dict(SOURCE_PINS)
                or not isinstance(value["input_sha256"], str) or not re.fullmatch("[a-f0-9]{64}", value["input_sha256"])
                or not isinstance(value["outputs"], dict) or set(value["outputs"]) != set(_OUTPUTS)):
            raise NativeAnalysisError("native analysis packet provenance or authority is inconsistent")
        without_id = {key: item for key, item in value.items() if key != "analysis_id"}
        if value["analysis_id"] != "shadow-native-analysis-" + sha256_bytes(canonical_json_bytes(without_id)):
            raise NativeAnalysisError("native analysis packet identity mismatch")
        evidence = value["source_evidence"]
        if not isinstance(evidence, list) or len(evidence) != len(SOURCE_PINS):
            raise NativeAnalysisError("native code evidence closure is incomplete")
        for item, (path, digest) in zip(evidence, SOURCE_PINS.items()):
            if (not isinstance(item, dict) or set(item) != {"path", "sha256", "size_bytes"}
                    or item["path"] != "native_analysis_code/" + path or item["sha256"] != digest
                    or type(item["size_bytes"]) is not int or not 0 < item["size_bytes"] <= MAX_SOURCE_BYTES):
                raise NativeAnalysisError("native source evidence descriptor is inconsistent")
        raw = canonical_json_bytes(value)
        if len(raw) > MAX_PACKET_BYTES:
            raise NativeAnalysisError("native analysis packet exceeds its bound")
        return cls(raw)

    @classmethod
    def from_bytes(cls, raw: bytes) -> "NativeAnalysisPacket":
        if not isinstance(raw, bytes) or len(raw) > MAX_PACKET_BYTES:
            raise NativeAnalysisError("invalid native packet bytes")
        return cls.from_mapping(parse_strict_json_object_bytes(raw))

    def to_dict(self) -> dict[str, Any]:
        return parse_strict_json_object_bytes(self._raw)

    def to_bytes(self) -> bytes:
        return self._raw


def validate_native_analysis(packet: Mapping[str, Any], market: Mapping[str, Any], source_bytes: Mapping[str, bytes]) -> None:
    retained = NativeAnalysisPacket.from_mapping(dict(packet)).to_bytes()
    # Journal callers hold content-addressed blobs; capture callers hold paths.
    # In either case only the reviewed fixed code identities may be executed.
    if set(SOURCE_PINS) <= set(source_bytes):
        sources = {path: source_bytes[path] for path in SOURCE_PINS}
    else:
        try:
            sources = {path: source_bytes[digest] for path, digest in SOURCE_PINS.items()}
        except KeyError as exc:
            raise NativeAnalysisError("native retained code evidence is missing") from exc
    replayed = canonical_json_bytes(derive_native_analysis(market, sources))
    if retained != replayed:
        raise NativeAnalysisError("native analytical content does not replay from retained inputs and code")


def native_symbol_states(packet: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    value = NativeAnalysisPacket.from_mapping(dict(packet)).to_dict()
    candidate = {item["symbol"]: item for item in value["outputs"]["trading_candidate_report"]["candidates"]}
    senate = {item["symbol"]: item for item in value["outputs"]["senate_deliberation"]["items"]}
    if set(candidate) != set(FLEET_SYMBOLS) or set(senate) != set(FLEET_SYMBOLS):
        raise NativeAnalysisError("native symbol coverage differs from configured fleet")
    return {symbol: {
        "candidate_state": candidate[symbol]["candidate_state"],
        "candidate_confidence_label": candidate[symbol]["confidence"],
        "senate_disposition": senate[symbol]["deliberation_state"],
        "candidate_reasons": candidate[symbol]["reasons"], "senate_reasoning": senate[symbol]["senate_reasoning"],
    } for symbol in FLEET_SYMBOLS}
