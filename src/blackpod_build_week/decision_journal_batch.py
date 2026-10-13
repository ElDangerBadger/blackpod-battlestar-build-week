"""Bounded immutable batches using the journal's original verifier/publication.

The whole candidate suffix is validated under one writer lock before any new
entry is published. Commits remain per event; an interruption leaves a valid
prefix and possibly orphan evidence, recoverable by an exact batch retry.
Existing JournalStore.append behavior and entry formats remain unchanged.
"""
import fcntl
import os
import stat
from collections.abc import Mapping

from .contracts.decision_journal import JournalEvent, validate_evidence_path
from .contracts.mission_request import ContractValidationError
from .hashing import canonical_json_bytes, sha256_bytes
from . import decision_journal_store as original

MAX_BATCH_EVENTS = 4096
MAX_BATCH_SUPPLIED_BYTES = 768 * 1024 * 1024


def append_journal_batch(store, materials):
    """Append a validated suffix once, preserving exact retries and recovery."""
    if not isinstance(store, original.JournalStore):
        raise original.JournalVerificationError("batch requires an existing JournalStore interface")
    if not isinstance(materials, (list, tuple)) or not 1 <= len(materials) <= MAX_BATCH_EVENTS:
        raise original.JournalVerificationError("journal batch requires a nonempty bounded record list")
    prepared, supplied, identities, supplied_bytes = [], {}, set(), 0
    for material in materials:
        if not isinstance(material, Mapping) or "event" not in material or "evidence" not in material:
            raise original.JournalVerificationError("batch materials require event and evidence")
        value = material["event"]
        event = JournalEvent.from_mapping(value.to_dict() if isinstance(value, JournalEvent) else value)
        if event.event_id in identities:
            raise original.JournalConflictError("batch contains duplicate immutable event identities")
        identities.add(event.event_id)
        if len(event.to_bytes()) > original._MAX_FILE_BYTES:
            raise original.JournalVerificationError("journal event exceeds 64 MiB limit")
        evidence = material["evidence"]
        if not isinstance(evidence, Mapping):
            raise original.JournalVerificationError("batch evidence requires a mapping")
        references = {ref["path"]: ref for ref in event.evidence}
        for key, raw in evidence.items():
            if not isinstance(key, str) or not isinstance(raw, bytes) or len(raw) > original._MAX_FILE_BYTES:
                raise original.JournalVerificationError("batch evidence requires bounded raw bytes")
            digest = sha256_bytes(raw)
            if original._DIGEST.fullmatch(key):
                if key != digest:
                    raise original.JournalVerificationError("supplied evidence hash mismatch")
            else:
                try:
                    validate_evidence_path(key)
                except ContractValidationError as exc:
                    raise original.JournalVerificationError(str(exc)) from exc
                if key in references and digest != references[key]["sha256"]:
                    raise original.JournalVerificationError("supplied source-path evidence hash mismatch")
            if digest in supplied and supplied[digest] != raw:
                raise original.JournalConflictError("batch evidence identity conflict")
            if digest not in supplied:
                supplied_bytes += len(raw)
                if supplied_bytes > MAX_BATCH_SUPPLIED_BYTES:
                    raise original.JournalVerificationError("batch exceeds its distinct supplied-byte bound")
            supplied[digest] = raw
        prepared.append(event)
    root = lock = None
    directories = {}
    try:
        original._check_existing_ancestors(store.root)
        original._reject_source_storage(store.root)
        root = original._open_root(store.root, create=True)
        store._preflight_root(root)
        for attempt in range(8):
            try:
                lock = os.open(".journal.lock", os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                    0o600, dir_fd=root)
                break
            except FileExistsError:
                try:
                    lock = os.open(".journal.lock", os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=root)
                    break
                except FileNotFoundError:
                    if attempt == 7:
                        raise
        if lock is None:
            raise original.JournalPersistenceError("could not acquire journal lock file")
        metadata = os.fstat(lock)
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
            raise original.JournalUnsafePathError("journal lock must be a regular file without hardlinks")
        fcntl.flock(lock, fcntl.LOCK_EX)
        os.fsync(root)
        for name in ("entries", "evidence", "staging"):
            directories[name] = original._open_child_directory(root, name, create=True)
        summary, existing, blobs = store._scan(root)
        for name in os.listdir(directories["staging"]):
            os.unlink(name, dir_fd=directories["staging"])
        os.fsync(directories["staging"])
        for digest, raw in supplied.items():
            if digest in blobs and blobs[digest] != raw:
                raise original.JournalConflictError("retained evidence identity conflict")
        candidates = {**blobs, **supplied}
        prefix, predecessor, sequence = list(existing), summary.last_entry_sha256, summary.event_count
        planned = []
        for event in prepared:
            identical = next((old for old in prefix if old.event_id == event.event_id), None)
            if identical is not None:
                if identical.to_bytes() != event.to_bytes():
                    raise original.JournalConflictError("event identity is already bound to different content")
                planned.append((event, None, prefix.index(identical) + 1))
                continue
            store._validate_event(event, tuple(prefix), candidates)
            sequence += 1
            entry = {"schema_version": original.ENTRY_SCHEMA_VERSION, "sequence": sequence,
                "previous_entry_sha256": predecessor, "event_sha256": sha256_bytes(event.to_bytes()),
                "event": event.to_dict()}
            raw = canonical_json_bytes(entry)
            if len(raw) > original._MAX_FILE_BYTES:
                raise original.JournalVerificationError("journal entry exceeds 64 MiB limit")
            planned.append((event, raw, sequence))
            prefix.append(event)
            predecessor = sha256_bytes(raw)
        # Every source link, declaration and derived result has now passed the
        # exact original verifier against its preceding candidate prefix.
        results, retained = [], set(blobs)
        for event, entry, sequence in planned:
            if entry is not None:
                needed = {ref["sha256"] for ref in event.evidence}
                for digest in sorted(needed - retained):
                    original._publish_immutable(directories["staging"], directories["evidence"],
                        digest, candidates[digest])
                    retained.add(digest)
                os.fsync(directories["evidence"])
                original._publish_immutable(directories["staging"], directories["entries"],
                    "%08d.json" % sequence, entry)
            results.append(original.JournalAppendResult(event.event_id, entry is not None, sequence))
        # Finish durability even after an earlier successful publication whose
        # directory fsync failed; an identical retry never writes new events.
        os.fsync(directories["evidence"])
        os.fsync(directories["entries"])
        return tuple(results)
    except original.JournalStoreError:
        raise
    except OSError as exc:
        raise original.JournalPersistenceError("journal batch persistence failed: " + str(exc)) from exc
    finally:
        for descriptor in directories.values():
            os.close(descriptor)
        if lock is not None:
            os.close(lock)
        if root is not None:
            os.close(root)
