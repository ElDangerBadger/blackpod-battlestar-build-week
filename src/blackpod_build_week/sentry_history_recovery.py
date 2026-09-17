"""Checkpointed acquisition around canonical H25; never a scanner or a selector.

Only Build Week artifacts are writable. Canonical H25 owns CSV normalization
and manifest creation; this adapter owns pacing, recovery, and cache provenance.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
import fcntl
import hashlib
import importlib
import json
import math
import os
from pathlib import Path
import stat
import sys
import tempfile
import time
import warnings

import yaml

from blackpod_build_week.sentry_history_cache import (
    CheckpointStore, RecoveryError, atomic_write, read_regular, validate_csv,
)


@dataclass(frozen=True)
class RecoveryOptions:
    min_delay: float = 2.0
    timeout: float = 15.0
    max_attempts: int = 2
    retry_delay: float = 10.0
    cooldown: float = 900.0
    max_requests: int = 25

    def __post_init__(self):
        for key in ("min_delay", "timeout", "retry_delay", "cooldown"):
            value = getattr(self, key)
            if isinstance(value, bool) or not math.isfinite(value) or value <= 0:
                raise RecoveryError(f"{key} must be positive and finite")
        if not 1 <= self.min_delay <= 60 or self.timeout > 60 or not 60 <= self.cooldown <= 86400:
            raise RecoveryError("pace 1–60s, timeout <= 60s and cooldown 60–86400s required")
        if type(self.max_attempts) is not int or not 1 <= self.max_attempts <= 5:
            raise RecoveryError("max_attempts must be between 1 and 5")
        if type(self.max_requests) is not int or not 0 <= self.max_requests <= 10000:
            raise RecoveryError("max_requests must be between 0 and 10000")


def _iso(epoch):
    return datetime.fromtimestamp(epoch, timezone.utc).isoformat().replace("+00:00", "Z")


def _digest(data):
    return hashlib.sha256(data).hexdigest()


def _guard(path: Path, root: Path) -> Path:
    """Reject symlinks before resolving, including existing parent components."""
    path = Path(os.path.abspath(path))
    if not path.is_relative_to(root) or path == root:
        raise RecoveryError("recovery paths must be inside the Build Week artifacts root")
    for part in (path, *path.parents):
        if part.is_symlink():
            raise RecoveryError("symlink paths are not permitted")
    return path


def _guard_tree(root, artifacts_root):
    _guard(root, artifacts_root)
    for directory, dirs, files in os.walk(root, followlinks=False):
        for name in (*dirs, *files):
            path = _guard(Path(directory) / name, artifacts_root)
            if path.exists() and not (path.is_file() or path.is_dir()):
                raise RecoveryError("special files are not permitted in recovery packages")
            if path.is_file() and path.stat().st_nlink != 1:
                raise RecoveryError("hard-linked package files are not permitted")


@contextmanager
def _lock(root):
    root.mkdir(parents=True, exist_ok=True)
    path = root / ".lock"
    descriptor = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        details = os.fstat(descriptor)
        if details.st_nlink != 1 or not stat.S_ISREG(details.st_mode):
            raise RecoveryError("unsafe recovery lock")
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RecoveryError("another recovery process owns this package") from exc
        yield
    finally:
        os.close(descriptor)


class CanonicalBridge:
    """Import the explicit read-only checkout, never a bundled replacement."""

    def __init__(self, root):
        self.root = Path(root).resolve(strict=True)
        sys.dont_write_bytecode = True
        sys.path.insert(0, str(self.root))
        try:
            self.bootstrap = importlib.import_module("microcap_sentry.universe.bootstrap")
            self.h25 = importlib.import_module("blackpod.runtime.yfinance_historical_backfill")
            self.history = importlib.import_module("blackpod.runtime.historical_store")
        finally:
            sys.path.pop(0)
        for module in (self.bootstrap, self.h25, self.history):
            if not Path(module.__file__).resolve().is_relative_to(self.root):
                raise RecoveryError("canonical module was loaded from a different checkout")

    def load(self, package):
        return self.bootstrap.load_bootstrap_package(package)

    def config(self, package):
        return self.h25.load_historical_backfill_config(package / "bootstrap_backfill.generated.yaml")

    def filename(self, symbol):
        return self.history.safe_symbol_filename(symbol) + ".csv"

    def run(self, **kwargs):
        return self.h25.run_historical_backfill(**kwargs)

    def validate_handoff(self, loaded):
        return self.bootstrap.validate_bootstrap_h25_handoff(loaded)

    def code_identity(self):
        paths = ("blackpod/runtime/yfinance_historical_backfill.py",
                 "blackpod/runtime/historical_store.py",
                 "microcap_sentry/universe/classification.py")
        return {name: _digest(read_regular(self.root / name)) for name in paths}


def _provider(cache_root):
    import yfinance
    # This redirects timezone, cookie and ISIN caches, not only data artifacts.
    yfinance.set_tz_cache_location(str(cache_root))
    return yfinance


def _json(path):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise RecoveryError("duplicate recovery JSON key")
            result[key] = value
        return result

    try:
        result = json.loads(read_regular(path).decode("utf-8"), object_pairs_hook=unique)
        if not isinstance(result, dict):
            raise RecoveryError("recovery JSON must be an object")
        return result
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise RecoveryError("invalid recovery JSON") from exc


def _write_json(path, value):
    atomic_write(path, (json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + "\n").encode())


def _sleep(seconds, sleeper):
    # Keep waits interruptible, including in an interactive agent session.
    while seconds > 0:
        chunk = min(30.0, seconds)
        sleeper(chunk)
        seconds -= chunk


class RecordedUnavailable(Exception):
    """Fresh, repeated provider missing-data result retained in recovery metadata."""


def recover(package, canonical, *, artifacts_root, adopt_existing=False,
            offline=False, publish_h25=False, options=None, provider_factory=None,
            now=time.time, sleep=time.sleep, progress=lambda value: None):
    options = options or RecoveryOptions()
    artifacts_root = Path(os.path.abspath(artifacts_root))
    package = _guard(Path(package), artifacts_root)
    _guard_tree(package, artifacts_root)
    recovery = _guard(package / "recovery", artifacts_root)
    if offline and publish_h25:
        raise RecoveryError("offline audit cannot publish an H25 manifest")
    with _lock(recovery):
        progress({"status": "VALIDATING_BOOTSTRAP"})
        loaded = canonical.load(package)
        config = canonical.config(package)
        plan = loaded.plan
        symbols = tuple(plan.provisional_symbols)
        start, end = plan.history_start.isoformat(), plan.history_end_inclusive.isoformat()
        expected = {
            "out_dir": package / "h25_daily",
            "manifest": package / "bootstrap_backfill_manifest.json",
            "ledger": package / "bootstrap_backfill_ledger.jsonl",
        }
        if config.provider != "yfinance" or config.interval != "1d" or config.start != start or config.end != end:
            raise RecoveryError("canonical history request differs from the saved bootstrap")
        if tuple(Path(item) for item in config.fleets) != (package / "provisional_universe.yaml",):
            raise RecoveryError("canonical fleet must be the exact package-local provisional fleet")
        for field, path in expected.items():
            if getattr(config, field) is None or Path(getattr(config, field)) != path:
                raise RecoveryError(f"unsafe canonical {field} path")
            _guard(path, artifacts_root)
        names = {symbol: canonical.filename(symbol) for symbol in symbols}
        if (not symbols or len(set(symbols)) != len(symbols)
                or len(set(names.values())) != len(names)
                or any(Path(name).name != name or not name.endswith(".csv") for name in names.values())):
            raise RecoveryError("empty fleet, duplicate symbols or unsafe/colliding canonical filenames")
        identity = {
            "package": str(package), "bootstrap_id": plan.bootstrap_id,
            "source_snapshot_id": plan.snapshot_id,
            "bootstrap_manifest_sha256": _digest(read_regular(package / "bootstrap_manifest.json")),
            "canonical_code": canonical.code_identity(),
        }
        store = CheckpointStore(recovery, identity, start, end, symbols, lambda: _iso(now()))
        control_path = recovery / "control.json"
        control = _json(control_path) if control_path.exists() else {}
        if control and control.get("identity") != identity:
            raise RecoveryError("cooldown identity differs from checkpoint")
        consecutive_unavailable = control.get("provider_missing_streak", 0)
        if type(consecutive_unavailable) is not int or consecutive_unavailable < 0:
            raise RecoveryError("invalid persisted provider missing streak")
        # Recover a missing-state write interrupted after an entry commit.
        # Adopted files are not evidence of the provider's current health.
        trailing_missing = 0
        for entry in sorted((item for item in store.entries.values() if item["source_kind"] == "provider"),
                            key=lambda item: item["first_seen_at"]):
            trailing_missing = trailing_missing + 1 if entry["status"] == "unavailable" else 0
        consecutive_unavailable = max(consecutive_unavailable, trailing_missing)

        def save_progress(status, symbol=None, error=None, until=0):
            _write_json(control_path, {"identity": identity, "status": status,
                        "symbol": symbol, "error_type": error, "retry_not_before": until,
                        "provider_missing_streak": consecutive_unavailable, "checked_at": _iso(now())})

        def report(status, **extra):
            entries = store.entries
            value = {"status": status, "total": len(symbols),
                     "ready": sum(entry["status"] == "ready" for entry in entries.values()),
                     "unavailable": sum(entry["status"] == "unavailable" for entry in entries.values()),
                     "pending": len(symbols) - len(entries), **extra}
            progress(value)
            return value

        def pause(status, symbol, error, delay):
            until = now() + delay
            save_progress(status, symbol, error, until)
            return report(status, symbol=symbol, error_type=error, retry_not_before=_iso(until))

        # Never overwrite or re-acquire into a published handoff. Verify it.
        if expected["manifest"].exists():
            if len(store.entries) != len(symbols):
                raise RecoveryError("existing H25 manifest has no complete recovery checkpoint")
            canonical.validate_handoff(loaded)
            return report("COMPLETE", manifest=str(expected["manifest"]))

        adopted = 0
        invalid_existing = 0
        completed = set(store.entries)
        if adopt_existing:
            for symbol in symbols:
                if symbol in completed:
                    continue
                old_path = expected["out_dir"] / names[symbol]
                if not old_path.exists():
                    continue
                data = read_regular(old_path)
                try:
                    validate_csv(data, start, end)
                except RecoveryError:
                    # Malformed/empty legacy files have no completed fetch claim.
                    # Keep them intact and require a new request; never bless them.
                    invalid_existing += 1
                else:
                    store.adopt(symbol, data, source_kind="adopted_partial_h25",
                                source_path=str(old_path), source_time=None)
                    adopted += 1
                    completed.add(symbol)
        report("CHECKPOINT_VERIFIED", adopted=adopted, invalid_existing=invalid_existing)
        if offline:
            return report("OFFLINE_AUDIT", adopted=adopted, invalid_existing=invalid_existing)
        if control:
            until = control.get("retry_not_before", 0)
            if isinstance(until, bool) or not isinstance(until, (float, int)) or not math.isfinite(until):
                raise RecoveryError("invalid persisted cooldown")
            if until > now():
                return report("COOLDOWN", retry_not_before=_iso(until))

        provider = None
        requests = 0
        last_request = None
        for symbol in symbols:
            if symbol in completed:
                continue
            missing_errors = []
            for attempt in range(options.max_attempts):
                if requests >= options.max_requests:
                    return report("BUDGET_PAUSED", requests=requests)
                if last_request is not None:
                    _sleep(max(0, options.min_delay - (now() - last_request)), sleep)
                if attempt:
                    _sleep(min(options.retry_delay * 2 ** (attempt - 1), options.cooldown), sleep)
                if provider is None:
                    provider = (provider_factory or _provider)(recovery / "yfinance-cache")
                requests += 1
                last_request = now()
                captured_at = _iso(now())
                frame_error = []
                wrapped_provider = provider

                class ProxyTicker:
                    def __init__(self, requested):
                        if requested != symbol:
                            raise RecoveryError("unexpected staging symbol")

                    def history(self, **kwargs):
                        try:
                            with warnings.catch_warnings():
                                warnings.simplefilter("ignore", DeprecationWarning)
                                return wrapped_provider.Ticker(symbol).history(
                                    **kwargs, timeout=options.timeout, raise_errors=True,
                                )
                        except Exception as exc:
                            frame_error.append(exc)
                            raise

                class Proxy:
                    Ticker = ProxyTicker

                with tempfile.TemporaryDirectory(prefix="capture-", dir=recovery) as directory:
                    stage = Path(directory)
                    fleet_path = stage / "fleet.yaml"
                    atomic_write(fleet_path, yaml.safe_dump({
                        "fleet_id": "sentry-history-recovery-single",
                        "name": "sentry_history_recovery", "purpose": "Read-only history acquisition",
                        "symbols": [{"symbol": symbol, "name": symbol, "asset_type": "EQUITY",
                                     "role": "validation_universe_bootstrap", "sector": "Unspecified",
                                     "enabled": True, "tags": ["history_recovery"]}],
                    }).encode())
                    canonical.run(fleet_paths=(str(fleet_path),), start=start, end=end,
                                  interval="1d", out_dir=stage / "daily", yf_module=Proxy,
                                  generated_at=captured_at)
                    data = read_regular(stage / "daily" / names[symbol])
                if frame_error:
                    exc = frame_error[-1]
                    code = type(exc).__name__
                    if code == "YFRateLimitError" or getattr(getattr(exc, "response", None), "status_code", None) == 429:
                        return pause("RATE_LIMITED", symbol, code, options.cooldown)
                    if code in {"YFPricesMissingError", "YFTzMissingError"}:
                        missing_errors.append(code)
                        if len(missing_errors) >= 2 and len(set(missing_errors)) == 1:
                            consecutive_unavailable += 1
                            if consecutive_unavailable >= 3:
                                # A provider-wide outage must not quietly become
                                # a fully populated fleet of missing histories.
                                return pause("PROVIDER_UNAVAILABLE", symbol, code, options.cooldown)
                            store.record_unavailable(symbol, code, source_time=captured_at)
                            completed.add(symbol)
                            save_progress("ACQUIRING", symbol, code)
                            break
                    else:
                        missing_errors.append("OTHER")
                    error = code
                else:
                    try:
                        validate_csv(data, start, end)
                    except RecoveryError:
                        # Silent empty frames or invalid bars are never completed.
                        missing_errors.append("INVALID_DATA")
                        error = "EMPTY_OR_INVALID_PROVIDER_DATA"
                    else:
                        store.record(symbol, data, source_kind="provider", source_time=captured_at)
                        completed.add(symbol)
                        consecutive_unavailable = 0
                        save_progress("ACQUIRING", symbol)
                        break
                if attempt + 1 == options.max_attempts:
                    return pause("RETRY_EXHAUSTED", symbol, error, options.cooldown)
            if requests % 10 == 0:
                report("ACQUIRING", requests=requests)
        if len(store.entries) != len(symbols):
            raise RecoveryError("full checkpoint coverage required before publication")
        if not publish_h25:
            return report("READY_TO_PUBLISH", requests=requests)

        # Validate the entire cache BEFORE canonical code can swallow a cache
        # exception as an ordinary failed fetch. Assembly consumes this verified
        # in-memory snapshot, not files that might change mid-publication.
        cached_entries = store.entries
        cached_rows = {symbol: store.rows(symbol) for symbol in symbols}
        for symbol in symbols:
            rows = cached_rows[symbol]
            if rows is None or (not rows and cached_entries[symbol]["status"] != "unavailable"):
                raise RecoveryError("cache incomplete before final assembly")
        canonical.load(package)  # Recheck saved source derivation after acquisition.

        # Preserve ALL old CSV bytes before canonical H25 replaces partial outputs.
        backup = recovery / "original_daily"
        backup_manifest = recovery / "original_daily.json"
        if backup_manifest.exists():
            for name, digest in _json(backup_manifest).items():
                if Path(name).name != name or _digest(read_regular(backup / name)) != digest:
                    raise RecoveryError("original history backup changed")
        else:
            hashes = {}
            for path in sorted(expected["out_dir"].glob("*.csv")):
                data = read_regular(path)
                target = backup / path.name
                if target.exists() and read_regular(target) != data:
                    raise RecoveryError("original history backup conflicts")
                atomic_write(target, data)
                hashes[path.name] = _digest(data)
            _write_json(backup_manifest, hashes)
        _guard_tree(package, artifacts_root)

        class CachedTicker:
            def __init__(self, symbol):
                self.symbol = symbol

            def history(self, **kwargs):
                if cached_entries[self.symbol]["status"] == "unavailable":
                    raise RecordedUnavailable(cached_entries[self.symbol]["reason"])
                return cached_rows[self.symbol]

        class CachedProvider:
            Ticker = CachedTicker

        report("ASSEMBLING_CACHED_HANDOFF")
        canonical.run(fleet_paths=config.fleets, start=start, end=end, interval="1d",
                      out_dir=config.out_dir, manifest_path=config.manifest,
                      ledger_path=config.ledger, yf_module=CachedProvider,
                      generated_at=_iso(now()))
        # Publication time is not substituted for the capture/adoption times in
        # the independent, hash-pinned per-symbol recovery provenance.
        canonical.validate_handoff(loaded)
        save_progress("COMPLETE")
        return report("COMPLETE", requests=requests, manifest=str(expected["manifest"]))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bootstrap-package", required=True, type=Path)
    parser.add_argument("--battlestar-path", required=True, type=Path)
    parser.add_argument("--adopt-existing", action="store_true",
                        help="Audit and pin nonempty package-local partial files; never infer fetch timestamps.")
    parser.add_argument("--offline", action="store_true", help="Validate/adopt only; no provider or final publication.")
    parser.add_argument("--publish-h25", action="store_true", help="Assemble canonical H25 only when every symbol is checkpointed.")
    parser.add_argument("--max-requests", type=int, default=25)
    parser.add_argument("--pace-seconds", type=float, default=2.0)
    parser.add_argument("--timeout-seconds", type=float, default=15.0)
    parser.add_argument("--max-attempts", type=int, default=2)
    parser.add_argument("--retry-seconds", type=float, default=10.0)
    parser.add_argument("--cooldown-seconds", type=float, default=900.0)
    args = parser.parse_args(argv)
    try:
        options = RecoveryOptions(args.pace_seconds, args.timeout_seconds, args.max_attempts,
                                  args.retry_seconds, args.cooldown_seconds, args.max_requests)
        result = recover(args.bootstrap_package, CanonicalBridge(args.battlestar_path),
                         artifacts_root=Path(__file__).resolve().parents[2] / "artifacts",
                         adopt_existing=args.adopt_existing, offline=args.offline,
                         publish_h25=args.publish_h25, options=options,
                         progress=lambda value: print(json.dumps(value), flush=True))
        return 0 if result["status"] in {"COMPLETE", "OFFLINE_AUDIT", "READY_TO_PUBLISH"} else 3
    except KeyboardInterrupt:
        print(json.dumps({"status": "INTERRUPTED", "message": "Validated checkpoints retained; resume the same package."}), flush=True)
        return 130
    except (RecoveryError, OSError, ValueError) as exc:
        print(json.dumps({"status": "ERROR", "message": str(exc)}), flush=True)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
