"""Explicit isolated CPU production, governed export and passive journal intake."""
import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import json
import fcntl
import os
from pathlib import Path
import subprocess
import stat
import sys

from .contracts.forecast_producer import ForecastProducerRequest
from .contracts.mission_request import parse_strict_json_object_bytes
from .contracts.trading_reconciliation import evidence_reference
from .decision_journal_store import JournalStore, JournalStoreError, check_separate_root
from .desk_candidate_review_cli import _references, _write, load_evidence
from .forecast_intake import evidence_for_forecast_intake
from .forecast_journal import build_forecast_intake_event
from .forecast_producer_export import build_forecast_producer_export, validate_forecast_producer_export_bundle
from .forecast_producer_journal import build_forecast_producer_event
from .hashing import canonical_json_bytes, sha256_bytes
from .sentry_history_cache import read_regular, RecoveryError


def load_export_evidence(root, references, retained=None, *, calendar_sha256):
    from .decision_journal_store import _check_existing_ancestors
    root = Path(root).absolute()
    _check_existing_ancestors(root)
    blobs, pending, visited = dict(retained or {}), list(references), set()
    while pending:
        reference = evidence_reference(pending.pop())
        key = (reference["path"], reference["sha256"], reference["size_bytes"])
        if key in visited:
            continue
        if len(visited) >= 256:
            raise ValueError("producer closure exceeds its retained-file bound")
        visited.add(key)
        raw = blobs.get(reference["sha256"])
        if raw is None:
            _check_existing_ancestors(root / Path(reference["path"]).parent)
            raw = read_regular(root / reference["path"])
        if sha256_bytes(raw) != reference["sha256"] or len(raw) != reference["size_bytes"]:
            raise ValueError("producer evidence differs in hash or size")
        blobs[reference["sha256"]] = raw
        if reference["path"].endswith(".json") and reference["sha256"] != calendar_sha256:
            pending.extend(_references(parse_strict_json_object_bytes(raw)))
    return blobs


def load_producer_evidence(root, request, retained=None):
    """The raw calendar is a JSON list; only other supported packets recurse."""
    return load_export_evidence(root, _references(request.to_dict()), retained,
        calendar_sha256=request.sources["calendar_evidence"]["sha256"])


def _publish(directory, material, protected=()):
    directory = Path(directory).absolute()
    for path, raw in material["evidence"].items():
        _write(directory / "evidence" / path, raw, protected)
    _write(directory / "export.json", canonical_json_bytes(material["export"]), protected)
    _write(directory / "intake.json", material["intake"].to_bytes(), protected)
    return {"export": str(directory / "export.json"), "intake": str(directory / "intake.json"),
        "evidence_root": str(directory / "evidence"), "admitted_count": material["intake_result"]["admitted_count"],
        "deferred_count": material["intake_result"]["deferred_count"], "provider_calls": 0, "orders_submitted": 0,
        "auto_trading_changed": False}


def _source_material(request, blobs):
    from .forecast_producer_export import _material
    return _material(request, blobs)


def _check_destination(directory):
    from .auto_trading_runtime import RuntimeLedger
    from .decision_journal_store import _check_existing_ancestors, _reject_source_storage
    directory = Path(directory).absolute()
    _check_existing_ancestors(directory)
    _reject_source_storage(directory)
    package_root = Path(__file__).absolute().parents[2]
    for ancestor in (directory, *directory.parents):
        if any((ancestor / name).exists() for name in ("ledger.lock", "worker.lock")):
            raise ValueError("producer output must remain separate from installed trading runtime")
        if ancestor.name == ".git":
            raise ValueError("producer output cannot write repository metadata")
        if (ancestor / ".git").exists() and not (ancestor == package_root and directory.is_relative_to(ancestor / "output")):
            raise ValueError("producer output cannot write repository source trees")
    RuntimeLedger(directory)  # Validation only; no lock or directory creation.


@contextmanager
def _production_lock(directory):
    from .sentry_history_cache import _directory
    parent, descriptor = _directory(directory), None
    flags = os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK
    try:
        for attempt in range(4):
            try:
                descriptor = os.open(".forecast-production.lock", flags | os.O_CREAT | os.O_EXCL, 0o600, dir_fd=parent)
                os.fsync(parent)
                break
            except FileExistsError:
                try:
                    descriptor = os.open(".forecast-production.lock", flags, dir_fd=parent)
                    break
                except FileNotFoundError:
                    if attempt == 3:
                        raise ValueError("concurrent production lock publication did not settle safely") from None
        if descriptor is None:
            raise ValueError("production lock could not be opened safely")
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
            raise ValueError("production lock must be an unlinked regular lock file")
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        yield
    finally:
        if descriptor is not None:
            os.close(descriptor)
        os.close(parent)


def produce(request, blobs, directory, python_executable, *, runner=subprocess.run):
    from .auto_trading_runtime import RuntimeLedger
    directory = Path(directory).absolute()
    _check_destination(directory)
    declared_executable = Path(python_executable).absolute()
    executable = declared_executable.resolve(strict=True)
    if not executable.is_file() or not os.access(executable, os.X_OK):
        raise ValueError("the explicitly selected existing quantitative interpreter is unavailable")
    market, calendar, sources = _source_material(request, blobs)
    from .sentry_history_cache import _directory
    for attempt in range(3):
        try:
            descriptor = _directory(directory, create=True)
            os.close(descriptor)
            break
        except FileExistsError:
            if attempt == 2:
                raise ValueError("concurrent destination preparation did not settle safely") from None
    with _production_lock(directory):
        intent_path, result_path, receipt_path = directory / "intent.json", directory / "worker/result.json", directory / "worker/receipt.json"
        interpreter_sha = sha256_bytes(read_regular(executable, max_bytes=64 * 1024 * 1024))
        binding = {"request_sha256": sha256_bytes(request.to_bytes()), "interpreter_sha256": interpreter_sha,
            "python_executable": str(declared_executable), "resolved_python_executable": str(executable)}
        if intent_path.exists():
            intent = parse_strict_json_object_bytes(read_regular(intent_path))
            from .contracts.investment_review import disabled_authority
            if set(intent) != {"schema_version", *binding, "started_at", "automatic_refit_allowed", "authority"} or intent["schema_version"] != "blackpod.forecast_production_intent.v1" or intent["automatic_refit_allowed"] is not False:
                raise ValueError("CPU production reservation has unsupported fields or retry authority")
            disabled_authority(intent["authority"])
            if any(intent.get(key) != value for key, value in binding.items()):
                raise ValueError("forecast production identity is bound to different inputs or runtime")
            if not result_path.exists() or not receipt_path.exists():
                raise ValueError("CPU production attempt was interrupted; no automatic refit; preserve its output and use an explicit export or new run identity")
            native = parse_strict_json_object_bytes(read_regular(result_path))
            receipt = parse_strict_json_object_bytes(read_regular(receipt_path))
            _receipt_window(intent["started_at"], receipt, native)
            material = _export_material(request, native, receipt, blobs)
            output = _publish(directory, material)
            output.update(reused_capture=True, models_fitted_this_invocation=0)
            return output
        if result_path.exists() or result_path.is_symlink() or receipt_path.exists() or receipt_path.is_symlink():
            raise ValueError("unclaimed existing worker output cannot trigger a new fit or reservation")
        started = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        _write(intent_path, canonical_json_bytes({"schema_version": "blackpod.forecast_production_intent.v1", **binding,
            "started_at": started, "automatic_refit_allowed": False, "authority": request.authority}), ())
        inputs = directory / "inputs"
        _write(inputs / "history.json", canonical_json_bytes(market), ())
        _write(inputs / "calendar.json", canonical_json_bytes(calendar), ())
        for path, raw in sources.items():
            _write(inputs / "native" / path, raw, ())
        environment = dict(os.environ)
        environment.update(PYTHONDONTWRITEBYTECODE="1", PYTHONPATH=str(Path(__file__).absolute().parents[1]))
        try:
            # Invoke the declared virtualenv launcher. Resolving its symlink
            # for hashing must not discard the environment's library prefix.
            completed = runner([str(declared_executable), "-m", "blackpod_build_week.shadow_quantitative_producer",
                "--history", str(inputs / "history.json"), "--calendar", str(inputs / "calendar.json"),
                "--sources-root", str(inputs / "native"), "--output", str(result_path), "--symbols", *request.symbols],
                env=environment, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=120, check=False)
        except subprocess.TimeoutExpired:
            raise ValueError("quantitative CPU attempt timed out; no automatic refit") from None
        if completed.returncode != 0:
            error = completed.stderr if isinstance(completed.stderr, bytes) else b""
            _write(directory / "failure.json", canonical_json_bytes({"returncode": completed.returncode,
                "stderr_sha256": sha256_bytes(error), "stderr_bytes": len(error), "automatic_refit_allowed": False}), ())
            raise ValueError("native quantitative production failed; retained failure fingerprint; no replacement algorithm or automatic refit")
        receipt = parse_strict_json_object_bytes(completed.stdout)
        _write(receipt_path, canonical_json_bytes(receipt), ())
        native = parse_strict_json_object_bytes(read_regular(result_path))
        _receipt_window(started, receipt, native)
        material = _export_material(request, native, receipt, blobs)
        output = _publish(directory, material)
        output.update(reused_capture=False, models_fitted_this_invocation=receipt["model_fit_count"])
        return output


def _receipt_window(started, receipt, native):
    from .contracts.mission_request import parse_rfc3339
    if not parse_rfc3339(started, "attempt started_at") <= parse_rfc3339(receipt["started_at"], "worker started_at") <= parse_rfc3339(receipt["completed_at"], "worker completed_at") <= parse_rfc3339(native["issued_at"], "issued_at"):
        raise ValueError("worker processing window predates its actual reserved CPU attempt")


def _export_material(request, native, receipt, blobs):
    fields = {"schema_version", "started_at", "completed_at", "output_sha256", "size_bytes", "symbol_count", "model_fit_count",
        "provider_calls", "orders_submitted", "auto_trading_enabled"}
    if set(receipt) != fields or receipt["schema_version"] != "blackpod.shadow_quantitative_worker_receipt.v1":
        raise ValueError("quantitative worker receipt has unsupported fields")
    raw = canonical_json_bytes(native)
    for field in ("size_bytes", "symbol_count", "model_fit_count", "provider_calls", "orders_submitted"):
        if type(receipt[field]) is not int or receipt[field] < 0:
            raise ValueError("quantitative receipt counts must be nonnegative integers")
    if receipt["output_sha256"] != sha256_bytes(raw) or receipt["size_bytes"] != len(raw) or receipt["symbol_count"] != len(native["symbols"]):
        raise ValueError("quantitative worker receipt differs from its retained result")
    if receipt["provider_calls"] != 0 or receipt["orders_submitted"] != 0 or receipt["auto_trading_enabled"] is not False:
        raise ValueError("quantitative worker cannot grant provider or execution authority")
    count = sum(3 * len(row["horizons"]) for row in native["symbols"])
    if type(receipt["model_fit_count"]) is not int or receipt["model_fit_count"] != count:
        raise ValueError("quantitative fit count differs from actual model coverage")
    return build_forecast_producer_export(request, native, blobs, started_at=receipt["started_at"],
        completed_at=receipt["completed_at"], issued_at=native["issued_at"])


def build_parser():
    parser = argparse.ArgumentParser(description="Governed native CPU forecast export; SHADOW only, no execution")
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("produce", "export"):
        sub = commands.add_parser(name)
        sub.add_argument("--request", type=Path, required=True)
        sub.add_argument("--evidence-root", type=Path, required=True)
        sub.add_argument("--output-directory", type=Path, required=True)
        if name == "produce":
            sub.add_argument("--python-executable", type=Path, required=True)
        else:
            sub.add_argument("--native-result", type=Path, required=True)
            sub.add_argument("--worker-receipt", type=Path, required=True)
    for name in ("record", "verify"):
        sub = commands.add_parser(name)
        sub.add_argument("--export", type=Path, required=True)
        sub.add_argument("--evidence-root", type=Path, required=True)
        if name == "record":
            sub.add_argument("--journal-root", type=Path, required=True)
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        if args.command in {"produce", "export"}:
            check_separate_root(args.output_directory, args.evidence_root)
            request = ForecastProducerRequest.from_bytes(read_regular(args.request))
            blobs = load_producer_evidence(args.evidence_root, request)
            if args.command == "produce":
                output = produce(request, blobs, args.output_directory, args.python_executable)
            else:
                check_separate_root(args.output_directory, args.native_result.parent)
                native = parse_strict_json_object_bytes(read_regular(args.native_result))
                receipt = parse_strict_json_object_bytes(read_regular(args.worker_receipt))
                output = _publish(args.output_directory, _export_material(request, native, receipt, blobs), (args.evidence_root, args.native_result.parent))
        else:
            export = parse_strict_json_object_bytes(read_regular(args.export))
            # The raw calendar list is loaded separately, never interpreted as
            # an arbitrary nested JSON evidence packet.
            request_ref = evidence_reference(export["request_evidence"])
            from .decision_journal_store import _check_existing_ancestors
            _check_existing_ancestors(args.evidence_root.absolute())
            request_path = args.evidence_root.absolute() / request_ref["path"]
            _check_existing_ancestors(request_path.parent)
            request_raw = read_regular(request_path)
            if len(request_raw) != request_ref["size_bytes"] or sha256_bytes(request_raw) != request_ref["sha256"]:
                raise ValueError("producer request differs from export source binding")
            request = ForecastProducerRequest.from_bytes(request_raw)
            direct = load_producer_evidence(args.evidence_root, request)
            calendar = request.sources["calendar_evidence"]
            blobs = load_export_evidence(args.evidence_root, export["source_evidence"], direct, calendar_sha256=calendar["sha256"])
            material = validate_forecast_producer_export_bundle(export, blobs)
            output = {"run_id": export["run_id"], "admitted_count": material["intake_result"]["admitted_count"], "deferred_count": material["intake_result"]["deferred_count"]}
            if args.command == "record":
                check_separate_root(args.journal_root, args.evidence_root)
                store = JournalStore(args.journal_root)
                producer_event = build_forecast_producer_event(export, blobs)
                first = store.append(producer_event, material["evidence"])
                events, retained = store.verified_contents()
                intake_event = build_forecast_intake_event(material["intake"], events, retained)
                second = store.append(intake_event, evidence_for_forecast_intake(material["intake"], retained))
                output.update(producer_event_id=producer_event.event_id, producer_written=first.written,
                    intake_event_id=intake_event.event_id, intake_written=second.written)
        print(json.dumps({"command": args.command, **output, "orders_submitted": 0, "auto_trading_changed": False}, sort_keys=True))
        return 0
    except (ValueError, OSError, TypeError, KeyError, JournalStoreError, RecoveryError, RecursionError) as error:
        print("forecast-producer: " + str(error), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
