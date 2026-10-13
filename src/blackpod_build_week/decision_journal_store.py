"""Offline append-only Decision Journal; never operates on source mission storage.

The immutable entries are the commit record. Evidence is published first, so an
interruption can leave harmless, verifiable orphan blobs but no partial event.
There is deliberately no mutable head/index to recover.
"""
from __future__ import annotations

import fcntl
import os
import re
import stat
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .contracts.decision_journal import JournalEvent, validate_evidence_path
from .contracts.mission_request import (
    ContractValidationError, parse_rfc3339, parse_strict_json_object_bytes,
)
from .contracts.mission_snapshot import MissionSnapshot
from .hashing import canonical_json_bytes, sha256_bytes

ENTRY_SCHEMA_VERSION = "blackpod.decision_journal_entry.v1"
_DIGEST = re.compile(r"[0-9a-f]{64}\Z")
_ENTRY = re.compile(r"([0-9]{8,})\.json\Z")
_TEMP = re.compile(r"\.publish-[0-9a-f]{32}\.tmp\Z")
_MAX_FILE_BYTES = 64 * 1024 * 1024
_ENTRY_FIELDS = {"schema_version", "sequence", "previous_entry_sha256", "event_sha256", "event"}


class JournalStoreError(RuntimeError):
    """Base class for journal errors."""


class JournalUnsafePathError(JournalStoreError):
    """A symlink, external hardlink, nonregular file, or unsafe path was found."""


class JournalVerificationError(JournalStoreError):
    """Journal contents or retained evidence fail verification."""


class JournalConflictError(JournalStoreError):
    """An immutable identity is already bound to different content."""


class JournalPersistenceError(JournalStoreError):
    """Publishing or synchronizing durable journal files failed."""


@dataclass(frozen=True, slots=True)
class JournalAppendResult:
    event_id: str
    written: bool
    sequence: int


@dataclass(frozen=True, slots=True)
class JournalVerification:
    event_count: int
    evidence_count: int
    orphan_evidence_count: int
    staging_orphan_count: int
    last_entry_sha256: str | None

    def to_dict(self) -> dict[str, Any]:
        return {"event_count": self.event_count, "evidence_count": self.evidence_count,
                "orphan_evidence_count": self.orphan_evidence_count,
                "staging_orphan_count": self.staging_orphan_count,
                "last_entry_sha256": self.last_entry_sha256}


def _absolute_path(path: Path) -> Path:
    path = Path(path).expanduser()
    if ".." in path.parts:
        raise JournalUnsafePathError("parent traversal is not permitted")
    return Path(os.path.abspath(path))


def _check_existing_ancestors(path: Path) -> None:
    current = Path(path.anchor)
    for part in path.parts[1:]:
        current /= part
        try:
            mode = current.lstat().st_mode
        except FileNotFoundError:
            return
        if stat.S_ISLNK(mode):
            raise JournalUnsafePathError(f"symlink in journal/source path: {current}")
        if not stat.S_ISDIR(mode):
            raise JournalUnsafePathError(f"journal/source ancestor is not a directory: {current}")


def _reject_source_storage(path: Path) -> None:
    """Protect canonical mission/producer storage for every journal command."""
    for ancestor in (path, *path.parents):
        if ancestor.name == "missions":
            raise JournalUnsafePathError("journal root cannot be inside a missions directory")
        for marker in (ancestor / "mission_snapshot.json",
                       ancestor / "request/mission_request.json",
                       ancestor / "missions"):
            try:
                marker.lstat()
            except (FileNotFoundError, NotADirectoryError):
                continue
            raise JournalUnsafePathError("journal root cannot overlap canonical mission or producer storage")


def check_separate_root(journal_root: Path, source_root: Path) -> None:
    """Reject equal/nested roots without resolving through unsafe symlinks."""
    journal = _absolute_path(journal_root)
    source = _absolute_path(source_root)
    _check_existing_ancestors(journal)
    _check_existing_ancestors(source)
    if journal == source or journal.is_relative_to(source) or source.is_relative_to(journal):
        raise JournalUnsafePathError("journal and source mission roots must be separate and not nested")


def _directory_flags() -> int:
    return os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW


def _open_root(path: Path, *, create: bool) -> int:
    """Walk directories using held descriptors; no following swapped symlinks."""
    descriptor = os.open(path.anchor, _directory_flags())
    try:
        for part in path.parts[1:]:
            try:
                child = os.open(part, _directory_flags(), dir_fd=descriptor)
            except FileNotFoundError:
                if not create:
                    raise JournalVerificationError(f"journal root does not exist: {path}")
                try:
                    os.mkdir(part, mode=0o700, dir_fd=descriptor)
                    os.fsync(descriptor)
                except FileExistsError:
                    pass  # Another writer may prepare the same root concurrently.
                child = os.open(part, _directory_flags(), dir_fd=descriptor)
            except OSError as exc:
                raise JournalUnsafePathError(f"unsafe journal ancestor {part}: {exc}") from exc
            os.close(descriptor)
            descriptor = child
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def _open_child_directory(parent: int, name: str, *, create: bool) -> int:
    try:
        descriptor = os.open(name, _directory_flags(), dir_fd=parent)
    except FileNotFoundError:
        if not create:
            raise JournalVerificationError(f"journal directory is missing: {name}")
        try:
            os.mkdir(name, mode=0o700, dir_fd=parent)
            os.fsync(parent)
        except FileExistsError:
            pass
        descriptor = os.open(name, _directory_flags(), dir_fd=parent)
    except OSError as exc:
        raise JournalUnsafePathError(f"unsafe journal directory {name}: {exc}") from exc
    return descriptor


def _read_regular(directory: int, name: str) -> tuple[bytes, os.stat_result]:
    try:
        descriptor = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
    except OSError as exc:
        raise JournalUnsafePathError(f"cannot safely open journal file {name}: {exc}") from exc
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            raise JournalUnsafePathError(f"journal file is not regular: {name}")
        if metadata.st_size > _MAX_FILE_BYTES:
            raise JournalVerificationError(f"journal file exceeds 64 MiB limit: {name}")
        pieces = []
        total = 0
        while True:
            piece = os.read(descriptor, 1024 * 1024)
            if not piece:
                break
            total += len(piece)
            if total > _MAX_FILE_BYTES:
                raise JournalVerificationError(f"journal file exceeds 64 MiB limit: {name}")
            pieces.append(piece)
        def fingerprint(details: os.stat_result) -> tuple[int, ...]:
            return (details.st_dev, details.st_ino, details.st_mode, details.st_nlink,
                    details.st_size, details.st_mtime_ns, details.st_ctime_ns)
        current = os.stat(name, dir_fd=directory, follow_symlinks=False)
        if (fingerprint(metadata) != fingerprint(os.fstat(descriptor)) or
                fingerprint(metadata) != fingerprint(current) or total != metadata.st_size):
            raise JournalVerificationError(f"journal file changed during read: {name}")
        return b"".join(pieces), metadata
    finally:
        os.close(descriptor)


def _publish_immutable(staging: int, target_directory: int, name: str, payload: bytes) -> None:
    """Publish whole fsynced bytes without overwriting any existing identity."""
    temporary = f".publish-{uuid.uuid4().hex}.tmp"
    descriptor: int | None = None
    created = False
    try:
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                             0o600, dir_fd=staging)
        created = True
        with os.fdopen(descriptor, "wb") as handle:
            descriptor = None
            handle.write(payload)
            handle.flush()
            os.fchmod(handle.fileno(), 0o444)
            os.fsync(handle.fileno())
        os.link(temporary, name, src_dir_fd=staging, dst_dir_fd=target_directory,
                follow_symlinks=False)
        os.fsync(target_directory)
    except FileExistsError as exc:
        raise JournalConflictError(f"immutable journal file already exists: {name}") from exc
    except OSError as exc:
        raise JournalPersistenceError(f"could not publish immutable journal file {name}: {exc}") from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)
        if created:
            try:
                os.unlink(temporary, dir_fd=staging)
            except FileNotFoundError:
                pass
            os.fsync(staging)


def _identity(prefix: str, value: Mapping[str, Any]) -> str:
    return f"{prefix}-{sha256_bytes(canonical_json_bytes(value))}"


class JournalStore:
    """Single-writer filesystem journal with verified immutable retry behavior."""

    def __init__(self, root: Path, *, source_root: Path | None = None) -> None:
        self.root = _absolute_path(root)
        _check_existing_ancestors(self.root)
        _reject_source_storage(self.root)
        if source_root is not None:
            check_separate_root(self.root, source_root)

    @staticmethod
    def _preflight_root(root: int) -> None:
        allowed = {"entries", "evidence", "staging", ".journal.lock"}
        names = set(os.listdir(root))
        if names - allowed:
            raise JournalVerificationError("unexpected file in journal root")
        for name in names:
            metadata = os.stat(name, dir_fd=root, follow_symlinks=False)
            if name == ".journal.lock":
                if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
                    raise JournalUnsafePathError("journal lock must be a regular file without hardlinks")
            elif not stat.S_ISDIR(metadata.st_mode):
                raise JournalUnsafePathError(f"journal child must be an unlinked directory: {name}")

    def _scan(self, root: int) -> tuple[JournalVerification, tuple[JournalEvent, ...], dict[str, bytes]]:
        self._preflight_root(root)
        directories: dict[str, int] = {}
        try:
            for name in ("entries", "evidence", "staging"):
                directories[name] = _open_child_directory(root, name, create=False)
            inventory: list[tuple[str, str, os.stat_result]] = []
            if ".journal.lock" in os.listdir(root):
                _, metadata = _read_regular(root, ".journal.lock")
                inventory.append(("root", ".journal.lock", metadata))
            blobs: dict[str, bytes] = {}
            for name in sorted(os.listdir(directories["evidence"])):
                if not _DIGEST.fullmatch(name):
                    raise JournalVerificationError(f"unexpected evidence filename: {name}")
                payload, metadata = _read_regular(directories["evidence"], name)
                inventory.append(("evidence", name, metadata))
                if sha256_bytes(payload) != name:
                    raise JournalVerificationError(f"retained evidence hash mismatch: {name}")
                blobs[name] = payload
            staging_names = sorted(os.listdir(directories["staging"]))
            for name in staging_names:
                if not _TEMP.fullmatch(name):
                    raise JournalVerificationError(f"unexpected staging filename: {name}")
                _, metadata = _read_regular(directories["staging"], name)
                inventory.append(("staging", name, metadata))
            names = sorted(os.listdir(directories["entries"]))
            events: list[JournalEvent] = []
            previous: str | None = None
            referenced: set[str] = set()
            for sequence, name in enumerate(names, 1):
                if not _ENTRY.fullmatch(name) or name != f"{sequence:08d}.json":
                    raise JournalVerificationError("entry sequence has a gap, reorder, or invalid filename")
                raw, metadata = _read_regular(directories["entries"], name)
                inventory.append(("entries", name, metadata))
                try:
                    entry = parse_strict_json_object_bytes(raw, document_name="journal entry")
                    if set(entry) != _ENTRY_FIELDS or entry["schema_version"] != ENTRY_SCHEMA_VERSION:
                        raise JournalVerificationError("invalid journal entry envelope")
                    if type(entry["sequence"]) is not int or entry["sequence"] != sequence:
                        raise JournalVerificationError("journal entry sequence mismatch")
                    if entry["previous_entry_sha256"] != previous:
                        raise JournalVerificationError("journal entry predecessor hash mismatch")
                    if canonical_json_bytes(entry) != raw:
                        raise JournalVerificationError("journal entry bytes are not canonical")
                    event = JournalEvent.from_mapping(entry["event"])
                    if sha256_bytes(event.to_bytes()) != entry["event_sha256"]:
                        raise JournalVerificationError("journal event hash mismatch")
                except (ContractValidationError, RecursionError) as exc:
                    raise JournalVerificationError(f"invalid journal event: {exc}") from exc
                self._validate_event(event, tuple(events), blobs)
                for reference in event.evidence:
                    referenced.add(reference["sha256"])
                events.append(event)
                previous = sha256_bytes(raw)
            self._validate_links(inventory)
            return (JournalVerification(len(events), len(blobs), len(set(blobs) - referenced),
                                        len(staging_names), previous), tuple(events), blobs)
        finally:
            for descriptor in directories.values():
                os.close(descriptor)

    @staticmethod
    def _validate_links(inventory: list[tuple[str, str, os.stat_result]]) -> None:
        grouped: dict[tuple[int, int], list[tuple[str, str, os.stat_result]]] = {}
        for item in inventory:
            grouped.setdefault((item[2].st_dev, item[2].st_ino), []).append(item)
        for files in grouped.values():
            metadata = files[0][2]
            if metadata.st_nlink == 1 and len(files) == 1:
                continue
            # A kill between link and unlink can leave one internal staging link.
            # External links and links between committed files are always unsafe.
            if (metadata.st_nlink == 2 and len(files) == 2 and
                    sum(item[0] == "staging" for item in files) == 1 and
                    sum(item[0] in {"entries", "evidence"} for item in files) == 1):
                continue
            raise JournalUnsafePathError(f"journal file has an external or unexpected hardlink: {files[0][1]}")

    @staticmethod
    def _validate_event(event: JournalEvent, previous_events: tuple[JournalEvent, ...],
                        blobs: Mapping[str, bytes]) -> None:
        source = event.source
        payload = event.payload
        for reference in event.evidence:
            raw = blobs.get(reference["sha256"])
            if raw is None or len(raw) != reference["size_bytes"] or sha256_bytes(raw) != reference["sha256"]:
                raise JournalVerificationError(f"missing or mismatched retained evidence: {reference['path']}")
        if source["source_sha256"] not in {item["sha256"] for item in event.evidence}:
            raise JournalVerificationError("event source is not retained in its evidence references")
        matching = tuple(item for item in previous_events if item.decision_id == event.decision_id)
        if any(item.domain != event.domain for item in matching):
            raise JournalConflictError("decision domain cannot change after import")
        if any(item.event_id == event.event_id for item in previous_events):
            raise JournalConflictError("duplicate event identity in immutable chain")
        if source["kind"] == "MISSION":
            identity = {"kind": "MISSION", "mission_id": source["mission_id"],
                        "request_id": source["request_id"], "run_mode": source["run_mode"]}
            if event.decision_id != _identity("journal-decision", identity):
                raise JournalVerificationError("mission decision identity mismatch")
            expected_event = {"decision_id": event.decision_id, "event_type": event.event_type,
                              "revision": source["revision"]}
            if event.event_id != _identity("journal-event", expected_event):
                raise JournalVerificationError("mission event identity mismatch")
            path = f"snapshots/mission_snapshot-r{source['revision']:04d}.json"
            if not any(item["path"] == path and item["sha256"] == source["source_sha256"]
                       for item in event.evidence):
                raise JournalVerificationError("source snapshot evidence reference mismatch")
            try:
                value = parse_strict_json_object_bytes(blobs[source["source_sha256"]])
                snapshot = MissionSnapshot.from_mapping(value)
            except ContractValidationError as exc:
                raise JournalVerificationError(f"invalid retained source snapshot: {exc}") from exc
            for key in ("mission_id", "request_id", "run_mode", "revision"):
                observed = getattr(snapshot, key)
                if observed != source[key]:
                    raise JournalVerificationError(f"retained snapshot source {key} mismatch")
            missions = tuple(item for item in matching if item.source["kind"] == "MISSION")
            expected_revision = missions[-1].source["revision"] + 1 if missions else 1
            if source["revision"] != expected_revision:
                raise JournalConflictError("mission revisions must append contiguously from revision 1")
            previous_hash = missions[-1].source["source_sha256"] if missions else None
            if snapshot.previous_snapshot_sha256 != previous_hash:
                raise JournalVerificationError("source snapshot predecessor hash mismatch")
            if missions:
                prior = MissionSnapshot.from_mapping(parse_strict_json_object_bytes(
                    blobs[missions[-1].source["source_sha256"]]))
                if snapshot.started_at != prior.started_at:
                    raise JournalVerificationError("source snapshot started_at changed")
                old_artifacts = {item.name: item for item in prior.artifacts}
                new_artifacts = {item.name: item for item in snapshot.artifacts}
                if any(new_artifacts.get(name) != artifact for name, artifact in old_artifacts.items()):
                    raise JournalVerificationError("source snapshot removed or changed prior artifacts")
                if any(snapshot.components.get(name) != component for name, component in prior.components.items()):
                    raise JournalVerificationError("source snapshot removed or changed prior component provenance")
            refs = {item["path"]: item for item in event.evidence}
            for artifact in snapshot.artifacts:
                reference = refs.get(artifact.path)
                if reference is None or reference["sha256"] != artifact.sha256:
                    raise JournalVerificationError("snapshot artifact evidence is missing or mismatched")
            # Recompute the pure projection from retained bytes. A correctly
            # rehashed entry must still preserve native decision semantics.
            from .decision_journal_projection import (
                HistoryVerificationError, VerifiedHistory, project_history,
            )
            files = {item["path"]: blobs[item["sha256"]] for item in event.evidence}
            try:
                history = VerifiedHistory(Path("/"), files["request/mission_request.json"],
                                          (blobs[source["source_sha256"]],), files)
                projected = project_history(history, event.domain,
                                            payload["classification"]["reason"])[0]
            except (KeyError, ValueError, HistoryVerificationError) as exc:
                raise JournalVerificationError(f"retained source projection failed: {exc}") from exc
            if projected.to_bytes() != event.to_bytes():
                raise JournalVerificationError("event does not match retained source projection")
        elif source["kind"] == "INVESTMENT_HYPOTHESIS":
            # Hypotheses are independent, shadow-only decisions. Validate their
            # retained drafts and links against the already verified chain both
            # while reading and under the append writer lock.
            from .investment_hypothesis import validate_hypothesis_event
            try:
                validate_hypothesis_event(event, previous_events, blobs)
            except ValueError as exc:
                raise JournalVerificationError(f"invalid investment hypothesis: {exc}") from exc
        elif source["kind"] in {"INVESTMENT_CHALLENGE", "INVESTMENT_OUTCOME_EVALUATION"}:
            # Reviews append to the original hypothesis decision. Recompute
            # derived assessments from retained input and already verified
            # evidence under the same lock as publication. This also runs on
            # every read, so rehashing a tampered report cannot validate it.
            from .investment_review import validate_review_event
            try:
                validate_review_event(event, previous_events, blobs)
            except ValueError as exc:
                raise JournalVerificationError(f"invalid investment review: {exc}") from exc
        elif source["kind"] == "INVESTMENT_DECISION_PROPOSAL":
            from .investment_governance import validate_proposal_event
            try:
                validate_proposal_event(event, previous_events, blobs)
            except ValueError as exc:
                raise JournalVerificationError(f"invalid investment proposal: {exc}") from exc
        elif source["kind"] == "INVESTMENT_SHADOW_APPROVAL":
            from .investment_approval import validate_approval_event
            try:
                validate_approval_event(event, previous_events, blobs)
            except ValueError as exc:
                raise JournalVerificationError(f"invalid investment approval: {exc}") from exc
        elif source["kind"] == "TRADING_AUTOMATION_CONTROL":
            from .trading_automation import validate_automation_event
            try:
                validate_automation_event(event, previous_events, blobs)
            except ValueError as exc:
                raise JournalVerificationError(f"invalid trading automation control: {exc}") from exc
        elif source["kind"] in {"PAPER_BROKER_SNAPSHOT", "TRADING_DESK_OWNERSHIP", "TRADING_EXECUTION_RECONCILIATION"}:
            # Reproduce passive paper-account observations, ownership versions
            # and receipt reconciliation from retained evidence. Reads and
            # appends use the same verified historical prefix; source files,
            # Alpaca clients and runtime executors are never consulted here.
            from .trading_reconciliation import validate_trading_reconciliation_event
            try:
                validate_trading_reconciliation_event(event, previous_events, blobs)
            except ValueError as exc:
                raise JournalVerificationError(f"invalid trading reconciliation: {exc}") from exc
        elif source["kind"] == "TRADING_FILL_LOT_ACCOUNTING":
            # Accounting replays individual retained fills and fees against
            # verified paper observations. It never changes mission decisions,
            # runtime controls or broker state, including when reading a chain.
            from .trading_accounting import validate_accounting_event
            try:
                validate_accounting_event(event, previous_events, blobs)
            except ValueError as exc:
                raise JournalVerificationError(f"invalid fill-lot accounting: {exc}") from exc
        elif source["kind"] == "SHADOW_DESK_REVIEW":
            # A two-desk research proposal is not a policy, installed book or
            # order. Rebuild its metrics and bounded sizes from retained
            # evidence on both append and read, without any runtime operation.
            from .desk_candidate_review import validate_desk_review_event
            try:
                validate_desk_review_event(event, previous_events, blobs)
            except ValueError as exc:
                raise JournalVerificationError(f"invalid shadow desk review: {exc}") from exc
        elif source["kind"] == "FORECAST_PRODUCER_EXPORT":
            from .forecast_producer_journal import validate_forecast_producer_event
            try:
                validate_forecast_producer_event(event, previous_events, blobs)
            except ValueError as exc:
                raise JournalVerificationError(f"invalid governed producer export: {exc}") from exc
        elif source["kind"] in {"FORECAST_INTAKE", "BRIGADE_SHADOW_ANALYSIS"}:
            from .forecast_journal import validate_forecast_intake_event, validate_brigade_shadow_event
            validator = validate_forecast_intake_event if source["kind"] == "FORECAST_INTAKE" else validate_brigade_shadow_event
            try:
                validator(event, previous_events, blobs)
            except ValueError as exc:
                raise JournalVerificationError(f"invalid governed forecast/Brigade evidence: {exc}") from exc
        elif source["kind"] in {"TRADING_HYPOTHESIS_CATALOG", "TRADING_HISTORICAL_INTAKE"}:
            from .trading_research_intake_journal import validate_intake_event
            try:
                validate_intake_event(event, previous_events, blobs)
            except ValueError as exc:
                raise JournalVerificationError(f"invalid historical research intake: {exc}") from exc
        elif source["kind"] in {"TRADING_CONTINUITY_INTAKE", "TRADING_COST_INTAKE", "TRADING_SHADOW_RISK_REVIEW",
                               "TRADING_REVIEWED_SHADOW_STUDY", "TRADING_REVIEWED_SHADOW_EVALUATION"}:
            from .trading_shadow_review_journal import validate_reviewed_event
            try:
                validate_reviewed_event(event, previous_events, blobs)
            except ValueError as exc:
                raise JournalVerificationError(f"invalid governed evidence/review: {exc}") from exc
        elif source["kind"] in {"TRADING_SHADOW_STUDY", "TRADING_SHADOW_EVALUATION"}:
            from .trading_shadow_journal import validate_shadow_event
            try:
                validate_shadow_event(event, previous_events, blobs)
            except ValueError as exc:
                raise JournalVerificationError(f"invalid governed shadow study: {exc}") from exc
        elif source["kind"] in {"TRADING_RESEARCH_PLAN", "TRADING_RESEARCH_EVALUATION"}:
            from .trading_research_journal import validate_research_event
            try:
                validate_research_event(event, previous_events, blobs)
            except ValueError as exc:
                raise JournalVerificationError(f"invalid offline trading research: {exc}") from exc
        elif source["kind"] == "RESEARCH_ASSESSMENT":
            from .research_acceptance_journal import validate_assessment_event
            try:
                validate_assessment_event(event, previous_events, blobs)
            except ValueError as exc:
                raise JournalVerificationError(f"invalid research acceptance assessment: {exc}") from exc
        elif source["kind"] in {"TRADING_EVIDENCE_QUALIFICATION_POLICY", "TRADING_EVIDENCE_QUALIFICATION"}:
            from .trading_evidence_qualification_journal import validate_qualification_event
            try:
                validate_qualification_event(event, previous_events, blobs)
            except ValueError as exc:
                raise JournalVerificationError(f"invalid trading evidence qualification: {exc}") from exc
        elif source["kind"] in {"TRAIN_MARKET_CAPTURE_PLAN", "TRAIN_MARKET_CAPTURE_SEGMENT", "TRAIN_MARKET_CAPTURE_EXPORT"}:
            from .train_market_evidence_journal import validate_train_market_event
            try:
                validate_train_market_event(event, previous_events, blobs)
            except ValueError as exc:
                raise JournalVerificationError(f"invalid TRAIN market capture/export: {exc}") from exc
        elif source["kind"] in {"SEGMENTED_TRAIN_EVIDENCE_BINDING", "SEGMENTED_TRAIN_EVIDENCE_QUALIFICATION"}:
            from .segmented_evidence_qualification_journal import validate_segmented_qualification_event
            try:
                validate_segmented_qualification_event(event, previous_events, blobs)
            except ValueError as exc:
                raise JournalVerificationError(f"invalid segmented evidence qualification: {exc}") from exc
        elif source["kind"] == "EVALUATION":
            missions = tuple(item for item in matching if item.source["kind"] == "MISSION")
            if not missions:
                raise JournalConflictError("evaluation requires an existing imported mission decision")
            if payload["execution_status"] != missions[-1].payload["execution_status"]:
                raise JournalConflictError("evaluation execution status must match latest imported mission")
            if parse_rfc3339(event.recorded_at, "recorded_at") < parse_rfc3339(
                    missions[-1].recorded_at, "source observed_at"):
                raise JournalConflictError("evaluation cannot predate latest imported mission evidence")
            original = {key: value for key, value in payload.items() if key != "execution_status"}
            if blobs[source["source_sha256"]] != canonical_json_bytes(original):
                raise JournalVerificationError("retained evaluation source differs from canonical payload")
            expected = {"decision_id": event.decision_id, "event_type": event.event_type,
                        "evaluation_id": source["evaluation_id"]}
            if event.event_id != _identity("journal-event", expected):
                raise JournalVerificationError("evaluation event identity mismatch")
        elif source["kind"] == "CAPITAL_POLICY":
            if blobs[source["source_sha256"]] != canonical_json_bytes(payload):
                raise JournalVerificationError("retained capital policy source differs from canonical payload")
            identity = {"kind": "CAPITAL_POLICY", "policy_id": source["policy_id"]}
            if event.decision_id != _identity("journal-decision", identity):
                raise JournalVerificationError("capital policy decision identity mismatch")
            expected = {"decision_id": event.decision_id, "event_type": event.event_type}
            if event.event_id != _identity("journal-event", expected):
                raise JournalVerificationError("capital policy event identity mismatch")

    def verify(self) -> JournalVerification:
        """Read-only verification; never creates files, directories, or locks."""
        root = _open_root(self.root, create=False)
        try:
            return self._scan(root)[0]
        finally:
            os.close(root)

    def events(self) -> tuple[JournalEvent, ...]:
        root = _open_root(self.root, create=False)
        try:
            return self._scan(root)[1]
        finally:
            os.close(root)

    def verified_contents(self) -> tuple[tuple[JournalEvent, ...], dict[str, bytes]]:
        """Return events and retained bytes from one read-only verified scan.

        The returned mapping is caller-owned; modifying it cannot change the
        retained journal. Consumers can resolve references without a second
        scan or reads from the original mission storage.
        """
        root = _open_root(self.root, create=False)
        try:
            _, events, blobs = self._scan(root)
            return events, dict(blobs)
        finally:
            os.close(root)

    def append(self, event: JournalEvent, evidence: Mapping[str, bytes]) -> JournalAppendResult:
        """Validate retained history, then append exactly once under an exclusive lock."""
        event = JournalEvent.from_mapping(event.to_dict())
        if len(event.to_bytes()) > _MAX_FILE_BYTES:
            raise JournalVerificationError("journal event exceeds 64 MiB limit")
        root: int | None = None
        lock: int | None = None
        directories: dict[str, int] = {}
        try:
            _check_existing_ancestors(self.root)
            _reject_source_storage(self.root)
            root = _open_root(self.root, create=True)
            self._preflight_root(root)
            # EXCL creation avoids an APFS concurrent O_CREAT/NOFOLLOW race.
            # If another writer creates it, open that inode without following links.
            for attempt in range(8):
                try:
                    lock = os.open(".journal.lock", os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                                   0o600, dir_fd=root)
                    break
                except FileExistsError:
                    try:
                        lock = os.open(".journal.lock", os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK,
                                       dir_fd=root)
                        break
                    except FileNotFoundError:
                        if attempt == 7:
                            raise
            if lock is None:
                raise JournalPersistenceError("could not acquire journal lock file")
            metadata = os.fstat(lock)
            if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
                raise JournalUnsafePathError("journal lock must be a regular file without hardlinks")
            fcntl.flock(lock, fcntl.LOCK_EX)
            os.fsync(root)
            for name in ("entries", "evidence", "staging"):
                directories[name] = _open_child_directory(root, name, create=True)
            summary, existing, blobs = self._scan(root)
            # Only verified staging files can be discarded, under the writer lock.
            for name in os.listdir(directories["staging"]):
                os.unlink(name, dir_fd=directories["staging"])
            os.fsync(directories["staging"])
            supplied: dict[str, bytes] = {}
            references = {item["path"]: item for item in event.evidence}
            for key, raw in evidence.items():
                if not isinstance(key, str) or not isinstance(raw, bytes):
                    raise JournalVerificationError("evidence must map SHA-256 digests or relative paths to bytes")
                if len(raw) > _MAX_FILE_BYTES:
                    raise JournalVerificationError("supplied evidence exceeds 64 MiB limit")
                digest = sha256_bytes(raw)
                if _DIGEST.fullmatch(key):
                    if digest != key:
                        raise JournalVerificationError("supplied evidence hash mismatch")
                else:
                    try:
                        validate_evidence_path(key)
                    except ContractValidationError as exc:
                        raise JournalVerificationError(str(exc)) from exc
                    if key in references and digest != references[key]["sha256"]:
                        raise JournalVerificationError("supplied source-path evidence hash mismatch")
                if digest in blobs and blobs[digest] != raw:
                    raise JournalConflictError("retained evidence identity conflict")
                supplied[digest] = raw
            identical = next((item for item in existing if item.event_id == event.event_id), None)
            if identical is not None:
                if identical.to_bytes() != event.to_bytes():
                    raise JournalConflictError("event identity is already bound to different content")
                # Complete durability after a previous publication whose directory
                # fsync failed; the immutable file may already have committed.
                os.fsync(directories["evidence"])
                os.fsync(directories["entries"])
                return JournalAppendResult(event.event_id, False, existing.index(identical) + 1)
            candidates = {**blobs, **supplied}
            self._validate_event(event, existing, candidates)
            sequence = summary.event_count + 1
            entry = {"schema_version": ENTRY_SCHEMA_VERSION, "sequence": sequence,
                     "previous_entry_sha256": summary.last_entry_sha256,
                     "event_sha256": sha256_bytes(event.to_bytes()), "event": event.to_dict()}
            entry_bytes = canonical_json_bytes(entry)
            if len(entry_bytes) > _MAX_FILE_BYTES:
                raise JournalVerificationError("journal entry exceeds 64 MiB limit")
            needed = {item["sha256"] for item in event.evidence}
            for digest in sorted(needed - set(blobs)):
                _publish_immutable(directories["staging"], directories["evidence"], digest, candidates[digest])
            # Orphan blobs from a failed earlier directory fsync are now durable.
            os.fsync(directories["evidence"])
            _publish_immutable(directories["staging"], directories["entries"],
                               f"{sequence:08d}.json", entry_bytes)
            return JournalAppendResult(event.event_id, True, sequence)
        except JournalStoreError:
            raise
        except OSError as exc:
            raise JournalPersistenceError(f"journal persistence failed: {exc}") from exc
        finally:
            for descriptor in directories.values():
                os.close(descriptor)
            if lock is not None:
                os.close(lock)
            if root is not None:
                os.close(root)
