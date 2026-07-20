"""Read-only Git worktree inspection shared by demo-readiness workflows."""

from __future__ import annotations

import math
import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Sequence


_GIT_TIMEOUT_SECONDS = 10.0
_GIT_REVISION = re.compile(r"[0-9a-fA-F]{40,64}\Z")
_TOKEN_PATTERNS = (
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\b(?:ghp_|github_pat_|xox[baprs]-|hf_)[A-Za-z0-9_-]{20,}\b"),
    re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9_-]{20,}\b"),
)
_ASSIGNED_SECRET = re.compile(
    rb"(?i)\b(?:api[_-]?key|access[_-]?token|client[_-]?secret|password|passwd)"
    rb"\s*[:=]\s*[\"']([^\"'\r\n]{16,512})[\"']"
)
_PRIVATE_KEY_BLOCK = re.compile(
    rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----\s+"
    rb"[A-Za-z0-9+/=\r\n]{80,}"
    rb"-----END (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"
)
_SUSPICIOUS_FILENAMES = {
    ".env",
    "credentials.json",
    "id_dsa",
    "id_ecdsa",
    "id_ed25519",
    "id_rsa",
}
_PLACEHOLDER_MARKERS = (
    "abcdef",
    "dummy",
    "example",
    "fake",
    "placeholder",
    "sample",
    "secret-value",
    "test",
)


class RepositoryStateError(RuntimeError):
    """Raised when a repository cannot be inspected safely and read-only."""


@dataclass(frozen=True, slots=True)
class GitWorktreeState:
    """Validated Git identity and worktree state.

    ``root`` is process-local and intentionally omitted from :meth:`to_dict` so
    callers do not accidentally persist a machine-specific absolute path.
    """

    root: Path
    revision: str
    branch: str | None
    dirty: bool

    def to_dict(self) -> dict[str, object]:
        return {
            "revision": self.revision,
            "branch": self.branch,
            "dirty": self.dirty,
        }


@dataclass(frozen=True, slots=True)
class CommittedSecretFinding:
    """Location-only report for one high-confidence committed credential."""

    path: str
    line: int | None
    code: str

    def to_dict(self) -> dict[str, object]:
        return {"path": self.path, "line": self.line, "code": self.code}


def inspect_git_worktree(root: Path) -> GitWorktreeState:
    """Return a repository's revision, branch, and dirty flag without locks."""

    candidate = Path(root)
    if candidate.is_symlink() or not candidate.is_dir():
        raise RepositoryStateError("Git worktree root must be a non-symlink directory")
    try:
        resolved = candidate.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise RepositoryStateError("Git worktree root could not be resolved") from exc

    revision_result = _run_git(resolved, ("rev-parse", "--verify", "HEAD"))
    if revision_result.returncode != 0:
        raise RepositoryStateError("Git revision is unavailable")
    revision = revision_result.stdout.strip()
    if _GIT_REVISION.fullmatch(revision) is None:
        raise RepositoryStateError("Git revision is malformed")

    branch_result = _run_git(
        resolved, ("symbolic-ref", "--quiet", "--short", "HEAD")
    )
    if branch_result.returncode == 0:
        branch = branch_result.stdout.strip()
        if not branch or "\n" in branch or "\r" in branch:
            raise RepositoryStateError("Git branch is malformed")
    elif branch_result.returncode == 1 and not branch_result.stdout.strip():
        branch = None
    else:
        raise RepositoryStateError("Git branch could not be inspected")

    status_result = _run_git(
        resolved,
        ("status", "--porcelain=v1", "--untracked-files=normal"),
    )
    if status_result.returncode != 0:
        raise RepositoryStateError("Git worktree state could not be inspected")

    return GitWorktreeState(
        root=resolved,
        revision=revision.lower(),
        branch=branch,
        dirty=bool(status_result.stdout),
    )


def scan_committed_secrets(root: Path) -> tuple[CommittedSecretFinding, ...]:
    """Scan Git-tracked files for high-confidence credential material.

    Findings intentionally contain no matched content. Synthetic redaction test
    strings are not flagged merely because they contain words such as
    ``api_key``; assigned values must also have credential-like entropy.
    """

    state = inspect_git_worktree(root)
    # Read the committed tree rather than the mutable working copy. This keeps
    # the result accurate when tracked files are locally edited or deleted.
    tracked_result = _run_git(
        state.root,
        ("ls-tree", "-r", "-z", "--name-only", "HEAD"),
        text=False,
    )
    if tracked_result.returncode != 0:
        raise RepositoryStateError("Git tracked files could not be inspected")
    raw_stdout = tracked_result.stdout
    if not isinstance(raw_stdout, bytes):  # defensive for injected subprocess seams
        raise RepositoryStateError("Git tracked file listing is malformed")

    findings: list[CommittedSecretFinding] = []
    for raw_relative in raw_stdout.split(b"\0"):
        if not raw_relative:
            continue
        try:
            relative_text = raw_relative.decode("utf-8", "strict")
            relative = PurePosixPath(relative_text)
        except (UnicodeDecodeError, ValueError):
            raise RepositoryStateError("Git tracked path is malformed") from None
        if (
            relative.is_absolute()
            or ".." in relative.parts
            or relative.as_posix() != relative_text
        ):
            raise RepositoryStateError("Git tracked path escapes the repository")
        lower_name = relative.name.lower()
        if (
            lower_name in _SUSPICIOUS_FILENAMES
            or (
                lower_name.startswith(".env.")
                and lower_name not in {".env.example", ".env.sample"}
            )
            or lower_name.endswith((".p12", ".pfx"))
        ):
            findings.append(
                CommittedSecretFinding(relative.as_posix(), None, "secret_filename")
            )

        size_result = _run_git(
            state.root,
            ("cat-file", "-s", f"HEAD:{relative.as_posix()}"),
        )
        if size_result.returncode != 0:
            raise RepositoryStateError("Git committed file size could not be inspected")
        try:
            size = int(size_result.stdout.strip())
        except (TypeError, ValueError) as exc:
            raise RepositoryStateError("Git committed file size is malformed") from exc
        # Credential files should be small. Capping reads also keeps this
        # check bounded for accidentally committed models or binary assets.
        if size > 4 * 1024 * 1024:
            continue
        content_result = _run_git(
            state.root,
            ("show", f"HEAD:{relative.as_posix()}"),
            text=False,
        )
        if content_result.returncode != 0 or not isinstance(content_result.stdout, bytes):
            raise RepositoryStateError("Git committed file could not be read")
        payload = content_result.stdout
        if b"\0" in payload:
            continue
        findings.extend(_content_findings(relative.as_posix(), payload))

    unique = {(item.path, item.line, item.code): item for item in findings}
    ordered = sorted(
        unique,
        key=lambda key: (key[0], -1 if key[1] is None else key[1], key[2]),
    )
    return tuple(unique[key] for key in ordered)


def _content_findings(path: str, payload: bytes) -> list[CommittedSecretFinding]:
    findings: list[CommittedSecretFinding] = []
    if _PRIVATE_KEY_BLOCK.search(payload):
        findings.append(CommittedSecretFinding(path, None, "private_key_material"))

    text = payload.decode("utf-8", "replace")
    for pattern in _TOKEN_PATTERNS:
        for match in pattern.finditer(text):
            token = match.group(0)
            if (
                not any(marker in token.lower() for marker in _PLACEHOLDER_MARKERS)
                and _credential_entropy(token) >= 3.5
            ):
                findings.append(
                    CommittedSecretFinding(
                        path,
                        text.count("\n", 0, match.start()) + 1,
                        "credential_token",
                    )
                )
    for match in _ASSIGNED_SECRET.finditer(payload):
        value = match.group(1).decode("utf-8", "replace")
        if _credential_entropy(value) >= 3.5:
            findings.append(
                CommittedSecretFinding(
                    path,
                    payload.count(b"\n", 0, match.start()) + 1,
                    "assigned_secret",
                )
            )
    return findings


def _credential_entropy(value: str) -> float:
    if not value:
        return 0.0
    counts: dict[str, int] = {}
    for character in value:
        counts[character] = counts.get(character, 0) + 1
    length = len(value)
    return -sum(
        (count / length) * math.log2(count / length) for count in counts.values()
    )


def _run_git(
    root: Path,
    arguments: Sequence[str],
    *,
    text: bool = True,
) -> subprocess.CompletedProcess[str] | subprocess.CompletedProcess[bytes]:
    environment = os.environ.copy()
    environment["GIT_OPTIONAL_LOCKS"] = "0"
    environment["GIT_TERMINAL_PROMPT"] = "0"
    try:
        return subprocess.run(
            ("git", "-C", str(root), *arguments),
            capture_output=True,
            text=text,
            encoding="utf-8" if text else None,
            errors="replace" if text else None,
            check=False,
            timeout=_GIT_TIMEOUT_SECONDS,
            env=environment,
        )
    except FileNotFoundError as exc:
        raise RepositoryStateError("Git is required for repository inspection") from exc
    except subprocess.TimeoutExpired as exc:
        raise RepositoryStateError("Git repository inspection timed out") from exc
    except OSError as exc:
        raise RepositoryStateError("Git repository inspection could not start") from exc
