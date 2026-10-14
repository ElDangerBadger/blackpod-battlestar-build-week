"""Small, explicitly configured read-only Cabin view of one shadow experiment.

The experiment module owns protocol, prediction, outcome, and chain validation.
This adapter has no collection, mutation, scheduling, provider, or broker path.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import threading

from .hashing import canonical_json_bytes
from .sentry_reader import _safe_json_tree


SCHEMA_VERSION = "blackpod.shadow_experiment_feed.v1"
MAX_FEED_BYTES = 512 * 1024


def _read_experiment_view(root: Path) -> dict:
    from .shadow_experiment import read_experiment_view

    return read_experiment_view(root)


class ShadowExperimentReader:
    """Read exactly one operator-selected local experiment; never discover one."""

    def __init__(self, root: Path | None = None):
        if root is not None and (".." in Path(root).parts or any(ord(c) < 32 for c in str(root))):
            raise ValueError("Shadow experiment root must be a normalized path.")
        self.root = None if root is None else Path(root)
        self._lock = threading.Lock()

    def current(self) -> dict:
        with self._lock:
            checked_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
            result = {"schema_version": SCHEMA_VERSION, "checked_at": checked_at,
                      "status": "NOT_CONFIGURED", "message": "No shadow experiment is configured. No substitute predictions are shown.",
                      "experiment": None}
            if self.root is None:
                return result
            try:
                experiment = _read_experiment_view(self.root)
                result.update(status="READY", message="Recorded shadow experiment; reading does not collect prices or make decisions.",
                              experiment=experiment)
                _safe_json_tree(result)
                if len(canonical_json_bytes(result)) > MAX_FEED_BYTES:
                    raise ValueError("Experiment view exceeds its display limit.")
                return result
            except (OSError, ValueError, TypeError, KeyError, RuntimeError, RecursionError, OverflowError):
                return {**result, "status": "UNAVAILABLE", "experiment": None,
                        "message": "The configured experiment is missing, changing, or failed validation. No substitute results are shown."}
