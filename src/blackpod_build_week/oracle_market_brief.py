"""Explicit, one-shot ModelDock rendering of a canonical Oracle market brief.

The supplement is presentation-only. It never edits a mission snapshot, calls
an analytical stage, or replaces the legacy fact-selection narrative. A saved
intent permanently reserves this attempt even when inference is interrupted;
rerunning the command cannot silently issue another model request.
"""

from __future__ import annotations

import argparse
import ast
import math
import os
import sys
import types
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .contracts import RunMode, StageStatus
from .contracts.mission_request import parse_strict_json_object_bytes
from .hashing import canonical_json_bytes, sha256_bytes
from .modeldock_client import ModelDockClient, ModelDockClientError, ModelDockCallResult
from .modeldock_config import load_modeldock_config
from .oracle_enrichment_workflow import ORACLE_EVIDENCE_ARTIFACTS


BRIEF_PATH = "presentation/oracle_market_brief.json"
ATTEMPT_PATH = "presentation/oracle_market_brief_attempt"
CANONICAL_MODULE_PATH = "blackpod/advisors/oracle_market_brief.py"
MAX_BRIEF_BYTES = 256 * 1024
MAX_MODULE_BYTES = 256 * 1024
MAX_EVIDENCE_BYTES = 1024 * 1024
_PURE_IMPORTS = frozenset({
    "__future__", "collections.abc", "copy", "dataclasses", "datetime",
    "decimal", "hashlib", "json", "math", "pathlib", "re", "typing", "unicodedata",
})


class OracleMarketBriefError(RuntimeError):
    """A safe, operator-readable failure without raw model or source text."""


@dataclass(frozen=True)
class OracleMarketBriefResult:
    action: str
    path: Path
    brief: dict[str, Any]


def load_canonical_brief_module(root: Path) -> tuple[types.ModuleType, str]:
    """Load only the explicit, pure canonical file, without package side effects.

    The operator-configured checkout is trusted application code. The import
    allowlist guards the contract seam against accidental provider/runtime
    dependencies; it is not a sandbox for arbitrary untrusted Python.
    """
    from .cabin_reader import _read_file

    root = Path(root)
    if not root.is_absolute():
        raise OracleMarketBriefError("BATTLESTAR_PATH must be an absolute path")
    try:
        source = _read_file(root, CANONICAL_MODULE_PATH, max_bytes=MAX_MODULE_BYTES)
        tree = ast.parse(source, filename=CANONICAL_MODULE_PATH)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import) and any(
                item.name not in _PURE_IMPORTS for item in node.names
            ):
                raise OracleMarketBriefError("canonical brief has unsupported dependencies")
            if isinstance(node, ast.ImportFrom) and (
                node.level or node.module not in _PURE_IMPORTS
            ):
                raise OracleMarketBriefError("canonical brief has unsupported dependencies")
        name = "_canonical_oracle_market_brief_" + uuid.uuid4().hex
        module = types.ModuleType(name)
        module.__file__ = str(root / CANONICAL_MODULE_PATH)
        sys.modules[name] = module
        try:
            exec(compile(tree, module.__file__, "exec"), module.__dict__)
        finally:
            sys.modules.pop(name, None)
        if any(not callable(getattr(module, method, None)) for method in (
            "build_evidence", "build_prompt", "validate_draft", "seal_brief", "validate_brief",
        )):
            raise OracleMarketBriefError("canonical brief API is unavailable")
        return module, sha256_bytes(source)
    except OracleMarketBriefError:
        raise
    except Exception:
        raise OracleMarketBriefError("canonical brief module cannot be loaded safely") from None


def load_mission_evidence(loaded: Any) -> dict[str, dict[str, Any]]:
    """Capture full, hash-verified source bytes for the canonical evidence builder."""
    from .cabin_reader import _read_file

    if loaded.request.run_mode is not RunMode.LIVE or loaded.snapshot.run_mode is not RunMode.LIVE:
        raise OracleMarketBriefError("market brief generation requires an existing LIVE mission")
    oracle = loaded.snapshot.stages["oracle"]
    if oracle.status is not StageStatus.SUCCEEDED:
        raise OracleMarketBriefError("Oracle must have succeeded before market brief generation")
    artifacts = {reference.name: reference for reference in loaded.snapshot.artifacts}
    sources: dict[str, dict[str, Any]] = {}
    for name, expected_path in ORACLE_EVIDENCE_ARTIFACTS.values():
        reference = artifacts.get(name)
        if (
            reference is None or name not in oracle.outputs
            or reference.path != expected_path or reference.producer != "oracle"
            or reference.byte_size is None or reference.observed_at is None
        ):
            raise OracleMarketBriefError("required canonical Oracle evidence is missing")
        payload = _read_file(loaded.paths.mission_root, reference.path, max_bytes=MAX_EVIDENCE_BYTES)
        if len(payload) != reference.byte_size or sha256_bytes(payload) != reference.sha256:
            raise OracleMarketBriefError("Oracle source failed integrity verification")
        sources[name] = {"reference": reference.to_dict(), "payload": payload}
    return sources


def _write_exclusive(directory: int, name: str, payload: bytes) -> None:
    descriptor = os.open(
        name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
        0o600, dir_fd=directory,
    )
    try:
        remaining = memoryview(payload)
        while remaining:
            remaining = remaining[os.write(descriptor, remaining):]
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    os.fsync(directory)


def _modeldock_failure_diagnostics(error: ModelDockClientError) -> dict[str, Any]:
    """Preserve the client's sanitized diagnostics, never failed model prose.

    ModelDockClient owns transport/error sanitization. Its public failure DTO
    already omits local model paths and raw HTTP error bodies. Strip content
    again here: even a response validated before a later failure must not turn
    into an unofficial market brief in the failure receipt.
    """
    diagnostics = error.failure.to_dict()
    response = diagnostics["safe_response"]
    if response is not None:
        content = response.pop("content", None)
        if isinstance(content, str):
            encoded = content.encode("utf-8")
            response["content_sha256"] = sha256_bytes(encoded)
            response["content_byte_size"] = len(encoded)
    return diagnostics


def _open_presentation(root: Path) -> int:
    """Create only the additive presentation directory, without following links."""
    descriptor = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        try:
            os.mkdir("presentation", mode=0o700, dir_fd=descriptor)
            os.fsync(descriptor)
        except FileExistsError:
            pass
        return os.open("presentation", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=descriptor)
    finally:
        os.close(descriptor)


def _existing_brief(root: Path, module: types.ModuleType, evidence: dict) -> dict | None:
    from .cabin_reader import _read_file, _safe_path

    target = _safe_path(root, BRIEF_PATH)
    if not target.exists():
        return None
    try:
        raw = _read_file(root, BRIEF_PATH, max_bytes=MAX_BRIEF_BYTES)
        value = parse_strict_json_object_bytes(raw)
        result = module.validate_brief(value, evidence)
        if canonical_json_bytes(result) != raw:
            raise ValueError("serialization differs")
        return result
    except Exception:
        raise OracleMarketBriefError("existing market brief is invalid or source-mismatched; refusing overwrite") from None


def generate_market_brief(
    *, artifacts_root: Path, mission_id: str,
    environ: Mapping[str, str] | None = None,
    client: Any | None = None,
    max_tokens: int = 3072,
) -> OracleMarketBriefResult:
    """Ask ModelDock for one bounded supplement, or validate an existing one.

    Model selection belongs to the appliance. Returned model identity is only
    recorded provenance, never a client routing instruction or equality gate.
    """
    from .cabin_reader import ReadOnlyMissionStore, _read_file

    if type(max_tokens) is not int or not 512 <= max_tokens <= 4096:
        raise OracleMarketBriefError("max_tokens must be an integer from 512 to 4096")
    environment = os.environ if environ is None else environ
    configured = environment.get("BATTLESTAR_PATH", "").strip()
    if not configured:
        raise OracleMarketBriefError("BATTLESTAR_PATH must explicitly select the canonical checkout")
    module, module_sha256 = load_canonical_brief_module(Path(configured))
    canonical_root = Path(configured).resolve(strict=True)
    resolved_artifacts = Path(artifacts_root).resolve(strict=False)
    if canonical_root == resolved_artifacts or canonical_root.is_relative_to(resolved_artifacts) or resolved_artifacts.is_relative_to(canonical_root):
        raise OracleMarketBriefError("mission artifacts and canonical checkout must not overlap")
    store = ReadOnlyMissionStore(Path(artifacts_root))
    try:
        loaded = store.load_mission(mission_id)
        sources = load_mission_evidence(loaded)
        evidence = module.build_evidence(
            mission_id=loaded.request.mission_id, request_id=loaded.request.request_id,
            symbol=loaded.request.symbol, run_mode="LIVE", sources=sources,
        )
    except OracleMarketBriefError:
        raise
    except Exception:
        raise OracleMarketBriefError("mission Oracle evidence could not be validated") from None
    root = loaded.paths.mission_root
    existing = _existing_brief(root, module, evidence)
    if existing is not None:
        return OracleMarketBriefResult("ALREADY_CAPTURED", root / BRIEF_PATH, existing)
    config = load_modeldock_config(environ=environment)
    prompt = module.build_prompt(evidence)
    wire = {
        "profile": config.profile,
        "capabilities": ["text"], "response_format": {"type": "json"},
        "timeout": max(1, math.ceil(config.timeout_seconds)),
        "metadata": {"blackpod_correlation": {
            "mission_id": loaded.request.mission_id, "request_id": loaded.request.request_id,
            "symbol": loaded.request.symbol, "run_mode": "LIVE",
        }},
        "prompt": prompt, "max_tokens": max_tokens,
    }
    request_bytes = canonical_json_bytes(wire)
    presentation = _open_presentation(root)
    attempt: int | None = None
    published = False
    try:
        try:
            os.mkdir("oracle_market_brief_attempt", mode=0o700, dir_fd=presentation)
            os.fsync(presentation)
        except FileExistsError:
            raise OracleMarketBriefError("a market brief attempt is already reserved; no automatic retry is permitted") from None
        attempt = os.open("oracle_market_brief_attempt", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=presentation)
        _write_exclusive(attempt, "intent.json", canonical_json_bytes({
            "schema_version": "blackpod.oracle_market_brief_intent.v1",
            "mission_id": mission_id, "request_sha256": sha256_bytes(request_bytes),
            "evidence_id": evidence["evidence_id"],
            "canonical_module_sha256": module_sha256,
            "status": "RESERVED_NO_AUTOMATIC_RETRY", "presentation_only": True,
        }))
        _write_exclusive(attempt, "request.json", request_bytes)
        result = (client or ModelDockClient(config)).generate_text(
            wire, mission_id=loaded.request.mission_id, request_id=loaded.request.request_id,
            symbol=loaded.request.symbol, run_mode=RunMode.LIVE,
            content_validator=lambda value: module.validate_draft(value, evidence),
            content_requires_correlation=False,
        )
        if (
            not isinstance(result, ModelDockCallResult)
            or result.request_sha256 != sha256_bytes(request_bytes)
            or result.request_bytes != request_bytes
            or result.provider != "mlx" or result.mocked is not False
        ):
            raise OracleMarketBriefError("ModelDock result conflicts with the reserved request")
        # Recheck even injected executors: the producer owns final acceptance.
        draft = module.validate_draft(result.parsed_content, evidence)
        provenance = {
            "provider": result.provider, "model": result.model,
            "model_revision": result.model_revision, "trace_id": result.trace_id,
            "mocked": False, "request_sha256": result.request_sha256,
            "response_sha256": result.raw_response_sha256,
            "started_at": result.started_at, "observed_at": result.observed_at,
            "canonical_module_sha256": module_sha256,
        }
        brief = module.seal_brief(evidence, draft, generated_at=result.observed_at, provenance=provenance)
        brief = module.validate_brief(brief, evidence)
        brief_bytes = canonical_json_bytes(brief)
        if len(brief_bytes) > MAX_BRIEF_BYTES:
            raise OracleMarketBriefError("market brief exceeds the capture limit")
        current = store.load_mission(mission_id)
        if current.current_snapshot_sha256 != loaded.current_snapshot_sha256 or load_mission_evidence(current) != sources:
            raise OracleMarketBriefError("mission evidence changed during inference; no brief published")
        if sha256_bytes(_read_file(Path(configured), CANONICAL_MODULE_PATH, max_bytes=MAX_MODULE_BYTES)) != module_sha256:
            raise OracleMarketBriefError("canonical brief module changed during inference")
        _write_exclusive(attempt, "response.json", result.safe_response_bytes)
        _write_exclusive(attempt, "provenance.json", canonical_json_bytes(provenance))
        _write_exclusive(attempt, "validated_brief.json", brief_bytes)
        # Hard linking a fully fsynced immutable file is atomic and never replaces
        # an existing destination. Readers never see a partially written brief.
        os.link("validated_brief.json", "oracle_market_brief.json", src_dir_fd=attempt, dst_dir_fd=presentation, follow_symlinks=False)
        published = True
        os.fsync(presentation)
        return OracleMarketBriefResult("CAPTURED", root / BRIEF_PATH, brief)
    except BaseException as exc:
        diagnostics = _modeldock_failure_diagnostics(exc) if isinstance(exc, ModelDockClientError) else None
        if attempt is not None:
            failure = {
                "schema_version": "blackpod.oracle_market_brief_failure.v1",
                "mission_id": mission_id, "status": "FAILED_NO_AUTOMATIC_RETRY",
                "code": "MODELDOCK_FAILED" if isinstance(exc, ModelDockClientError) else "CAPTURE_FAILED",
                "request_sha256": sha256_bytes(request_bytes),
                "evidence_id": evidence["evidence_id"], "brief_published": published,
                "modeldock_failure": diagnostics,
            }
            try:
                _write_exclusive(attempt, "failure.json", canonical_json_bytes(failure))
            except OSError:
                pass  # The already-durable intent remains the fail-closed receipt.
        if isinstance(exc, (KeyboardInterrupt, SystemExit, OracleMarketBriefError)):
            raise
        if diagnostics is not None:
            raise OracleMarketBriefError(
                f"market brief capture failed [{diagnostics['code']}]: {diagnostics['message']} "
                "Attempt preserved without automatic retry."
            ) from None
        raise OracleMarketBriefError("market brief capture failed; attempt preserved without automatic retry") from None
    finally:
        if attempt is not None:
            os.close(attempt)
        os.close(presentation)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifacts-root", type=Path, required=True)
    parser.add_argument("--mission-id", required=True)
    parser.add_argument("--max-tokens", type=int, default=3072)
    args = parser.parse_args(argv)
    try:
        result = generate_market_brief(artifacts_root=args.artifacts_root, mission_id=args.mission_id, max_tokens=args.max_tokens)
    except Exception as exc:
        message = str(exc) if isinstance(exc, OracleMarketBriefError) else "market brief invocation failed validation"
        print(message, file=sys.stderr)
        return 1
    print(f"{result.action}: {result.path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
