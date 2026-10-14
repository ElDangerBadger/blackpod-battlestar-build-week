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
import re
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
from .narrative_diagnostics import CanonicalBriefValidationError
from .oracle_brief_reader import validate_brief_semantics
from .oracle_enrichment_workflow import ORACLE_EVIDENCE_ARTIFACTS


BRIEF_PATH = "presentation/oracle_market_brief.json"
ATTEMPT_PATH = "presentation/oracle_market_brief_attempt"
REVIEWED_RETRY_PREFIX = "presentation/oracle_market_brief_retry_"
REVIEWED_REVISION_PREFIX = "presentation/oracle_market_brief_revision_"
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
            "build_evidence", "build_prompt", "build_output_schema", "validate_draft", "seal_brief", "validate_brief",
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


def _validate_draft_with_diagnostics(module: types.ModuleType, value: Any, evidence: dict) -> dict:
    """Leave acceptance canonical; project only known rejection diagnostics.

    Loaded contract modules have distinct runtime error classes. Match the
    actual class from the trusted module, never a model-supplied class name.
    """
    try:
        result = module.validate_draft(value, evidence)
    except module.OracleMarketBriefError as error:
        raise CanonicalBriefValidationError(error) from None
    try:
        return validate_brief_semantics(result, evidence)
    except ValueError as error:
        raise CanonicalBriefValidationError(error) from None


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
        validate_brief_semantics(result["report"], evidence)
        if canonical_json_bytes(result) != raw:
            raise ValueError("serialization differs")
        return result
    except Exception:
        raise OracleMarketBriefError("existing market brief is invalid or source-mismatched; refusing overwrite") from None


def _reviewed_failure(root: Path, digest: str, mission_id: str, evidence_id: str) -> dict:
    """Bind an explicitly reviewed retry to unchanged failed-attempt evidence.

    This is not a retry loop or a reset. One new immutable reservation is keyed
    by the original failure hash, so repeated commands cannot duplicate a call.
    Unfinished intents and failed retries cannot use this original-attempt path.
    """
    from .cabin_reader import _read_file

    try:
        failure_bytes = _read_file(root, f"{ATTEMPT_PATH}/failure.json", max_bytes=MAX_BRIEF_BYTES)
        failure = parse_strict_json_object_bytes(failure_bytes)
        intent_bytes = _read_file(root, f"{ATTEMPT_PATH}/intent.json", max_bytes=MAX_BRIEF_BYTES)
        intent = parse_strict_json_object_bytes(intent_bytes)
        request = _read_file(root, f"{ATTEMPT_PATH}/request.json", max_bytes=MAX_EVIDENCE_BYTES)
        if (
            sha256_bytes(failure_bytes) != digest
            or failure.get("schema_version") != "blackpod.oracle_market_brief_failure.v1"
            or failure.get("status") != "FAILED_NO_AUTOMATIC_RETRY"
            or failure.get("brief_published") is not False
            or failure.get("mission_id") != mission_id or failure.get("evidence_id") != evidence_id
            or intent.get("schema_version") != "blackpod.oracle_market_brief_intent.v1"
            or intent.get("mission_id") != mission_id or intent.get("evidence_id") != evidence_id
            or intent.get("status") != "RESERVED_NO_AUTOMATIC_RETRY"
            or intent.get("presentation_only") is not True
            or failure.get("request_sha256") != sha256_bytes(request)
            or intent.get("request_sha256") != failure.get("request_sha256")
        ):
            raise ValueError("reviewed failure does not match")
    except Exception:
        raise OracleMarketBriefError("reviewed retry requires the exact intact original failure, request and intent for this evidence") from None
    return {"failure_path": f"{ATTEMPT_PATH}/failure.json", "failure_sha256": digest,
            "request_sha256": failure["request_sha256"], "intent_sha256": sha256_bytes(intent_bytes)}


def _saved_prompt(request_bytes: bytes) -> str:
    """Recognize only the two historical canonical prompt wire formats."""
    request = parse_strict_json_object_bytes(request_bytes)
    if "prompt" in request and "messages" not in request:
        prompt = request["prompt"]
    elif "messages" in request and "prompt" not in request:
        messages = request["messages"]
        if (
            not isinstance(messages, list) or len(messages) != 1
            or not isinstance(messages[0], dict)
            or set(messages[0]) != {"role", "content"}
            or messages[0]["role"] != "user"
        ):
            raise ValueError("unrecognized canonical prompt shape")
        prompt = messages[0]["content"]
    else:
        raise ValueError("unrecognized canonical prompt shape")
    if not isinstance(prompt, str) or not prompt.strip():
        raise ValueError("missing canonical prompt")
    return prompt


def _reviewed_request_revision(
    root: Path, original: dict, mission_id: str, evidence_id: str,
    prompt: str, request_sha256: str,
) -> dict:
    """Allow one explicitly invoked, changed-prompt reservation per request.

    The predecessor must be the completed failed original reviewed retry, not
    an unfinished intent or another revision. Original and retry evidence are
    never deleted/reset; their exact bytes are rechecked before publication.
    Merely changing a timeout/token budget cannot unlock a new attempt.
    """
    from .cabin_reader import _read_file

    retry_path = REVIEWED_RETRY_PREFIX + original["failure_sha256"]
    try:
        failure_bytes = _read_file(root, f"{retry_path}/failure.json", max_bytes=MAX_BRIEF_BYTES)
        failure = parse_strict_json_object_bytes(failure_bytes)
        intent_bytes = _read_file(root, f"{retry_path}/intent.json", max_bytes=MAX_BRIEF_BYTES)
        intent = parse_strict_json_object_bytes(intent_bytes)
        request_bytes = _read_file(root, f"{retry_path}/request.json", max_bytes=MAX_EVIDENCE_BYTES)
        original_bytes = _read_file(root, f"{ATTEMPT_PATH}/request.json", max_bytes=MAX_EVIDENCE_BYTES)
        if (
            failure.get("schema_version") != "blackpod.oracle_market_brief_failure.v1"
            or failure.get("status") != "FAILED_NO_AUTOMATIC_RETRY"
            or failure.get("brief_published") is not False
            or failure.get("mission_id") != mission_id or failure.get("evidence_id") != evidence_id
            or intent.get("schema_version") != "blackpod.oracle_market_brief_intent.v1"
            or intent.get("status") != "RESERVED_NO_AUTOMATIC_RETRY"
            or intent.get("presentation_only") is not True
            or intent.get("mission_id") != mission_id or intent.get("evidence_id") != evidence_id
            or failure.get("reviewed_retry_of") != original or intent.get("reviewed_retry_of") != original
            or "reviewed_request_revision" in intent or "reviewed_request_revision" in failure
            or failure.get("request_sha256") != sha256_bytes(request_bytes)
            or intent.get("request_sha256") != failure.get("request_sha256")
            or sha256_bytes(original_bytes) != original["request_sha256"]
        ):
            raise ValueError("predecessor does not match")
        original_prompt = _saved_prompt(original_bytes)
        previous_prompt = _saved_prompt(request_bytes)
    except Exception:
        raise OracleMarketBriefError("request revision requires the intact failed reviewed retry for the same original evidence") from None
    if prompt in (original_prompt, previous_prompt):
        raise OracleMarketBriefError("request revision requires a changed canonical prompt, not only request settings")
    return {
        "failure_path": f"{retry_path}/failure.json",
        "failure_sha256": sha256_bytes(failure_bytes),
        "intent_sha256": sha256_bytes(intent_bytes),
        "request_sha256": sha256_bytes(request_bytes),
        "previous_prompt_sha256": sha256_bytes(previous_prompt.encode("utf-8")),
        "revised_prompt_sha256": sha256_bytes(prompt.encode("utf-8")),
        "revision_id": sha256_bytes(canonical_json_bytes({
            "original_failure_sha256": original["failure_sha256"],
            "request_sha256": request_sha256,
        })),
    }


def generate_market_brief(
    *, artifacts_root: Path, mission_id: str,
    environ: Mapping[str, str] | None = None,
    client: Any | None = None,
    max_tokens: int = 3072,
    reviewed_retry_of: str | None = None,
    reviewed_request_revision: bool = False,
) -> OracleMarketBriefResult:
    """Ask ModelDock for one bounded supplement, or validate an existing one.

    Model selection belongs to the appliance. Returned model identity is only
    recorded provenance, never a client routing instruction or equality gate.
    """
    from .cabin_reader import ReadOnlyMissionStore, _read_file

    if type(max_tokens) is not int or not 512 <= max_tokens <= 4096:
        raise OracleMarketBriefError("max_tokens must be an integer from 512 to 4096")
    if type(reviewed_request_revision) is not bool or (reviewed_request_revision and reviewed_retry_of is None):
        raise OracleMarketBriefError("reviewed_request_revision must be a boolean and requires reviewed_retry_of")
    if reviewed_retry_of is not None and (
        not isinstance(reviewed_retry_of, str) or re.fullmatch(r"[0-9a-f]{64}", reviewed_retry_of) is None
    ):
        raise OracleMarketBriefError("reviewed_retry_of must be the original failure's lowercase SHA-256")
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
    retry_record = None if reviewed_retry_of is None else _reviewed_failure(
        root, reviewed_retry_of, mission_id, evidence["evidence_id"],
    )
    config = load_modeldock_config(environ=environment)
    prompt = module.build_prompt(evidence)
    wire = {
        "profile": config.profile,
        "capabilities": ["text"],
        "response_format": {"type": "json_schema", "schema": module.build_output_schema(evidence)},
        "timeout": max(1, math.ceil(config.timeout_seconds)),
        "metadata": {"blackpod_correlation": {
            "mission_id": loaded.request.mission_id, "request_id": loaded.request.request_id,
            "symbol": loaded.request.symbol, "run_mode": "LIVE",
        }},
        # Semantic input lets ModelDock own all native chat-template details.
        # The canonical instructions/evidence bytes themselves remain unchanged.
        "messages": [{"role": "user", "content": prompt}], "max_tokens": max_tokens,
    }
    request_bytes = canonical_json_bytes(wire)
    revision_record = _reviewed_request_revision(
        root, retry_record, mission_id, evidence["evidence_id"], prompt, sha256_bytes(request_bytes),
    ) if reviewed_request_revision else None
    if revision_record is not None:
        attempt_path = REVIEWED_REVISION_PREFIX + revision_record["revision_id"]
    else:
        attempt_path = ATTEMPT_PATH if reviewed_retry_of is None else REVIEWED_RETRY_PREFIX + reviewed_retry_of
    attempt_name = Path(attempt_path).name
    presentation = _open_presentation(root)
    attempt: int | None = None
    published = False
    try:
        try:
            os.mkdir(attempt_name, mode=0o700, dir_fd=presentation)
            os.fsync(presentation)
        except FileExistsError:
            raise OracleMarketBriefError("a market brief attempt is already reserved; no automatic retry is permitted") from None
        attempt = os.open(attempt_name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=presentation)
        _write_exclusive(attempt, "intent.json", canonical_json_bytes({
            "schema_version": "blackpod.oracle_market_brief_intent.v1",
            "mission_id": mission_id, "request_sha256": sha256_bytes(request_bytes),
            "evidence_id": evidence["evidence_id"],
            "canonical_module_sha256": module_sha256,
            "status": "RESERVED_NO_AUTOMATIC_RETRY", "presentation_only": True,
            **({"reviewed_retry_of": retry_record} if retry_record is not None else {}),
            **({"reviewed_request_revision": revision_record} if revision_record is not None else {}),
        }))
        _write_exclusive(attempt, "request.json", request_bytes)
        result = (client or ModelDockClient(config)).generate_text(
            wire, mission_id=loaded.request.mission_id, request_id=loaded.request.request_id,
            symbol=loaded.request.symbol, run_mode=RunMode.LIVE,
            content_validator=lambda value: _validate_draft_with_diagnostics(module, value, evidence),
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
        if (
            not isinstance(result.safe_response, Mapping)
            or result.safe_response_bytes != canonical_json_bytes(dict(result.safe_response))
        ):
            raise OracleMarketBriefError("ModelDock result projection conflicts with its persisted response")
        metadata = result.safe_response.get("metadata")
        acknowledgement = metadata.get("structured_output") if isinstance(metadata, Mapping) else None
        if (
            not isinstance(acknowledgement, Mapping)
            or acknowledgement.get("mode") != "json_schema"
            or acknowledgement.get("validated") is not True
        ):
            raise OracleMarketBriefError("ModelDock result lacks confirmed schema-constrained generation and validation")
        draft = _validate_draft_with_diagnostics(module, result.parsed_content, evidence)
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
        if reviewed_retry_of is not None:
            if _reviewed_failure(root, reviewed_retry_of, mission_id, evidence["evidence_id"]) != retry_record:
                raise OracleMarketBriefError("original failed-attempt evidence changed during the reviewed retry")
        if revision_record is not None:
            if _reviewed_request_revision(
                root, retry_record, mission_id, evidence["evidence_id"], prompt, sha256_bytes(request_bytes),
            ) != revision_record:
                raise OracleMarketBriefError("failed reviewed-retry evidence changed during the request revision")
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
                **({"reviewed_retry_of": retry_record} if retry_record is not None else {}),
                **({"reviewed_request_revision": revision_record} if revision_record is not None else {}),
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
    parser.add_argument("--reviewed-retry-of", help="Explicitly reviewed original failure SHA-256; reserves one separate attempt without replacing history")
    parser.add_argument("--reviewed-request-revision", action="store_true", help="With --reviewed-retry-of, explicitly reserve a changed canonical prompt after its failed reviewed retry; does not reset history or retry automatically")
    args = parser.parse_args(argv)
    try:
        result = generate_market_brief(artifacts_root=args.artifacts_root, mission_id=args.mission_id,
                                      max_tokens=args.max_tokens, reviewed_retry_of=args.reviewed_retry_of,
                                      reviewed_request_revision=args.reviewed_request_revision)
    except Exception as exc:
        message = str(exc) if isinstance(exc, OracleMarketBriefError) else "market brief invocation failed validation"
        print(message, file=sys.stderr)
        return 1
    print(f"{result.action}: {result.path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
