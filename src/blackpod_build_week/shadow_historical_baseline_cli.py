"""Explicit offline historical reconstruction, separate from the live pilot."""
from __future__ import annotations

import argparse
import csv
from io import StringIO
import json
import os
from pathlib import Path
import sys

from .contracts.decision_journal import validate_evidence_path
from .contracts.historical_intake import validate_historical_capture
from .contracts.mission_request import parse_rfc3339, parse_strict_json_object_bytes
from .contracts.trading_research import TradingResearchPlan
from .decision_journal_store import JournalStore, JournalStoreError, check_separate_root
from .desk_candidate_review_cli import _write
from .hashing import canonical_json_bytes, sha256_bytes
from .sentry_history_cache import read_regular
from .shadow_experiment import read_experiment_view
from .shadow_experiment_capture import ExperimentCaptureError
from .shadow_experiment_cli import _credentials, _off, _safe_root
from .shadow_historical_calendar import MAX_DATE, calendar_get
from .trading_historical_intake import _calendar

BUNDLE_VERSION = "blackpod.shadow_historical_baseline_bundle.v1"
DATA_SEMANTICS = {"source_price_basis": "UNKNOWN", "adjustment_applied_by_baseline": False,
    "corporate_actions_verified": False, "historical_publication_verified": False,
    "same_feed_as_prospective_iex": False, "net_costs_available": False,
    "source_manifest_not_provider_authentication": True}


def _ref(path, raw):
    return {"path": path, "sha256": sha256_bytes(raw), "size_bytes": len(raw)}


def _json(raw):
    return parse_strict_json_object_bytes(raw)


def _output_root(path):
    root = _safe_root(path)
    for parent in (root, *root.parents):
        if os.path.lexists(parent / ".journal.lock"):
            raise ValueError("baseline artifacts must be separate from all journals")
    return root


def _calendar_material(root):
    raw = read_regular(Path(root) / "calendar.json", max_bytes=4 * 1024 * 1024)
    receipt_raw = read_regular(Path(root) / "calendar.receipt.json", max_bytes=64 * 1024)
    receipt = validate_historical_capture(_json(receipt_raw), "calendar")
    if receipt["body_sha256"] != sha256_bytes(raw) or receipt["size_bytes"] != len(raw):
        raise ValueError("calendar body differs from retained receipt")
    _calendar(raw, receipt)
    return raw, receipt_raw


def protected_scope(root):
    """Derive the cutoff from retained plan/calendar metadata, not price data."""
    paths = {"protected-plan.json": "trading-research/registered-plan.v2.json",
             "protected-calendar.json": "source/calendar.raw",
             "protected-calendar.receipt.json": "source/calendar.receipt.v1.json"}
    evidence = {"sources/" + name: read_regular(Path(root) / path, max_bytes=4 * 1024 * 1024)
                for name, path in paths.items()}
    return protected_scope_from_bytes(evidence), evidence


def protected_scope_from_bytes(evidence):
    """Validate retained scope provenance equally during publication and replay."""
    plan = TradingResearchPlan.from_bytes(evidence["sources/protected-plan.json"])
    raw = evidence["sources/protected-calendar.json"]
    receipt = validate_historical_capture(_json(evidence["sources/protected-calendar.receipt.json"]), "calendar")
    if sha256_bytes(raw) != receipt["body_sha256"] or len(raw) != receipt["size_bytes"]:
        raise ValueError("protected calendar differs from its receipt")
    dates = list(_calendar(raw, receipt))
    protocol = plan.protocol
    end_index = max(fold["test"]["end_index"] for fold in protocol["folds"])
    holdout = protocol["final_holdout"]
    if (plan.universe != ["QQQ", "SPY"] or end_index + 1 >= len(dates)
            or holdout["end_index"] >= len(dates) or dates[end_index] != MAX_DATE):
        raise ValueError("protected research scope does not establish the fixed cutoff")
    scope = {"maximum_scored_date": dates[end_index], "embargo_start": dates[end_index + 1],
             "holdout_start": dates[holdout["start_index"]], "holdout_end": dates[holdout["end_index"]],
             "original_plan_evidence": _ref("sources/protected-plan.json", evidence["sources/protected-plan.json"]),
             "original_calendar_evidence": _ref("sources/protected-calendar.json", raw),
             "original_calendar_receipt_evidence": _ref("sources/protected-calendar.receipt.json", evidence["sources/protected-calendar.receipt.json"]),
             "verification_scope": "PLAN_STRUCTURE_AND_RETAINED_CALENDAR_NOT_FULL_JOURNAL_REPLAY"}
    return scope


def validate_provenance(material, manifest, evidence):
    if (manifest["schema_version"] != "blackpod.shadow_historical_source_manifest.v1"
            or canonical_json_bytes(manifest["data_semantics"]) != canonical_json_bytes(DATA_SEMANTICS)):
        raise ValueError("source provenance cannot silently acquire verified semantics")
    if manifest["protected_scope"] != protected_scope_from_bytes(evidence):
        raise ValueError("protected scope differs from original retained metadata")
    original_raw = evidence["sources/backfill-manifest.json"]
    if manifest["backfill_manifest_evidence"] != _ref("sources/backfill-manifest.json", original_raw):
        raise ValueError("backfill provenance differs from its named retained evidence")
    original = _json(original_raw)
    if (original["provider"] != "yfinance" or original["interval"] != "1d"
            or manifest["provider"] != "yfinance" or manifest["source_price_basis"] != "UNKNOWN"
            or manifest["collection_vintage_at"] != original["generated_at"]
            or manifest["collection_vintage_scope"] != "DECLARED_MANIFEST_METADATA_NOT_AUTHENTICATED_CAPTURE_TIME"):
        raise ValueError("historical source metadata has changed semantics")
    for coverage in material["report"]["source_coverage"]:
        symbol = coverage["symbol"]
        matches = [row for row in original["series"] if row["symbol"] == symbol]
        if len(matches) != 1:
            raise ValueError("backfill provenance must identify each symbol once")
        series = matches[0]
        ref = manifest["sources"][symbol]
        raw = evidence["sources/" + symbol + ".csv"]
        if any(ref[key] != value for key, value in _ref("sources/" + symbol + ".csv", raw).items()):
            raise ValueError("historical source reference has changed identity")
        if ref["original_series"] != series or any(coverage[key] != series[field] for key, field in (
                ("source_row_count", "row_count"), ("source_first_date", "first_date"), ("source_last_date", "last_date"))):
            raise ValueError("historical source coverage differs from backfill provenance")


def _csv_rows(rows):
    output = StringIO(newline="")
    if rows:
        writer = csv.DictWriter(output, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({key: json.dumps(value, separators=(",", ":")) if isinstance(value, (list, dict)) else value
                             for key, value in row.items()})
    return output.getvalue().encode()


def _derived_files(material):
    from .shadow_historical_presentation import render_historical_baseline
    return {"report.json": canonical_json_bytes(material["report"]),
            "rows.json": canonical_json_bytes(material["rows"]),
            "cohorts.json": canonical_json_bytes(material["cohorts"]),
            "rows.csv": _csv_rows(material["rows"]),
            "report.html": render_historical_baseline(material).encode()}


def build_bundle(args):
    from .shadow_historical_baseline import build_historical_baseline, calculation_evidence
    root = _output_root(args.output_root)
    sources = tuple(path.absolute() for path in (args.experiment_root, args.history_root,
        args.backfill_manifest.parent, args.calendar_root, args.protected_study_root))
    for source in sources:
        check_separate_root(root, source)
    _off(args.runtime_root)
    view = read_experiment_view(args.experiment_root)
    events, blobs = JournalStore(args.experiment_root).verified_contents()
    protocol = view["protocol"]
    hypothesis = blobs[protocol["hypothesis_evidence"]["sha256"]]
    calendar_raw, calendar_receipt_raw = _calendar_material(args.calendar_root)
    original_manifest_raw = read_regular(args.backfill_manifest, max_bytes=4 * 1024 * 1024)
    original_manifest = _json(original_manifest_raw)
    if original_manifest["provider"] != "yfinance" or original_manifest["interval"] != "1d":
        raise ValueError("baseline requires the declared daily yfinance source")
    scope, evidence = protected_scope(args.protected_study_root)
    series = {}
    for symbol in ("QQQ", "SPY"):
        matches = [row for row in original_manifest["series"] if row["symbol"] == symbol]
        if len(matches) != 1:
            raise ValueError("source manifest must declare both series exactly once")
        series[symbol] = matches[0]
    csvs = {symbol: read_regular(args.history_root / (symbol + ".csv"), max_bytes=8 * 1024 * 1024) for symbol in ("QQQ", "SPY")}
    manifest = {"schema_version": "blackpod.shadow_historical_source_manifest.v1", "provider": "yfinance",
        "source_price_basis": "UNKNOWN", "collection_vintage_at": original_manifest["generated_at"],
        "collection_vintage_scope": "DECLARED_MANIFEST_METADATA_NOT_AUTHENTICATED_CAPTURE_TIME",
        "sources": {symbol: {**_ref("sources/" + symbol + ".csv", raw),
            "original_path": str((args.history_root / (symbol + ".csv")).absolute()), "original_series": series[symbol]}
            for symbol, raw in csvs.items()},
        "backfill_manifest_evidence": _ref("sources/backfill-manifest.json", original_manifest_raw),
        "protected_scope": scope,
        "data_semantics": dict(DATA_SEMANTICS)}
    material = build_historical_baseline(protocol, csvs, calendar_raw=calendar_raw,
        calendar_receipt_raw=calendar_receipt_raw, source_manifest=manifest, cutoff=scope["maximum_scored_date"])
    evidence.update({"sources/" + symbol + ".csv": raw for symbol, raw in csvs.items()})
    evidence.update({"sources/calendar.json": calendar_raw, "sources/calendar.receipt.json": calendar_receipt_raw,
        "sources/source-manifest.json": canonical_json_bytes(manifest), "sources/protocol.json": canonical_json_bytes(protocol),
        "sources/hypothesis.json": hypothesis, "sources/backfill-manifest.json": original_manifest_raw})
    validate_provenance(material, manifest, evidence)
    evidence.update(calculation_evidence())
    package = Path(__file__).absolute().parent
    for path in ("shadow_historical_baseline_cli.py", "shadow_historical_calendar.py", "shadow_historical_presentation.py"):
        evidence["implementation/" + path] = read_regular(package / path)
    evidence.update(_derived_files(material))
    bundle = {"schema_version": BUNDLE_VERSION, "report_id": material["report"]["report_id"],
        "files": [_ref(path, raw) for path, raw in sorted(evidence.items())]}
    existed = (root / "bundle-manifest.json").exists()
    _off(args.runtime_root)
    for path, raw in sorted(evidence.items()):
        _write(root / path, raw, sources)
    _write(root / "bundle-manifest.json", canonical_json_bytes(bundle), sources)
    return {"report_id": bundle["report_id"], "output_root": str(root), "written": not existed,
            "file_count": len(evidence), "summary": material["report"]["summary"],
            "provider_calls": 0, "auto_trading_changed": False}


def verify_bundle(root):
    from .shadow_historical_baseline import build_historical_baseline, calculation_evidence
    root = _output_root(root)
    bundle = _json(read_regular(root / "bundle-manifest.json", max_bytes=1024 * 1024))
    if set(bundle) != {"schema_version", "report_id", "files"} or bundle["schema_version"] != BUNDLE_VERSION:
        raise ValueError("unsupported baseline bundle")
    if not isinstance(bundle["files"], list) or not 1 <= len(bundle["files"]) <= 100:
        raise ValueError("baseline file list must be bounded")
    retained = {}
    for ref in bundle["files"]:
        if set(ref) != {"path", "sha256", "size_bytes"}:
            raise ValueError("invalid baseline evidence reference")
        path = validate_evidence_path(ref["path"])
        raw = read_regular(root / path, max_bytes=64 * 1024 * 1024)
        if path in retained or sha256_bytes(raw) != ref["sha256"] or len(raw) != ref["size_bytes"]:
            raise ValueError("baseline retained file identity differs")
        retained[path] = raw
    protocol, manifest = (_json(retained["sources/" + name + ".json"]) for name in ("protocol", "source-manifest"))
    from .contracts.trading_hypothesis import TradingHypothesis
    hypothesis_raw = retained["sources/hypothesis.json"]
    hypothesis = TradingHypothesis.from_bytes(hypothesis_raw)
    if (sha256_bytes(hypothesis_raw) != protocol["hypothesis_evidence"]["sha256"]
            or len(hypothesis_raw) != protocol["hypothesis_evidence"]["size_bytes"]
            or hypothesis.hypothesis_id != protocol["original_hypothesis_id"]
            or hypothesis.horizon != protocol["original_horizon"]
            or parse_rfc3339(hypothesis.recorded_at, "hypothesis clock") > parse_rfc3339(protocol["frozen_at"], "freeze clock")):
        raise ValueError("baseline source hypothesis differs")
    material = build_historical_baseline(protocol, {symbol: retained["sources/" + symbol + ".csv"] for symbol in ("QQQ", "SPY")},
        calendar_raw=retained["sources/calendar.json"], calendar_receipt_raw=retained["sources/calendar.receipt.json"],
        source_manifest=manifest, cutoff=manifest["protected_scope"]["maximum_scored_date"])
    validate_provenance(material, manifest, retained)
    for path, raw in {**_derived_files(material), **calculation_evidence()}.items():
        if retained.get(path) != raw:
            raise ValueError("baseline differs from exact retained-source replay")
    if material["report"]["report_id"] != bundle["report_id"]:
        raise ValueError("baseline report identity differs")
    return {"valid": True, "report_id": bundle["report_id"], "file_count": len(retained), "provider_calls": 0}


def main(argv=None):
    parser = argparse.ArgumentParser(description="Historical context for the fixed shadow pilot; no execution")
    commands = parser.add_subparsers(dest="command", required=True)
    capture = commands.add_parser("capture-calendar")
    capture.add_argument("--output-root", type=Path, required=True)
    capture.add_argument("--start", default="1998-01-01")
    capture.add_argument("--end", default=MAX_DATE)
    capture.add_argument("--credentials-file", type=Path, required=True)
    capture.add_argument("--credential-format", required=True, choices=("GALACTICA_YAML", "PAPER_ENV", "NAVIGATOR_ENV"))
    capture.add_argument("--runtime-root", type=Path, required=True)
    build = commands.add_parser("build")
    for name in ("experiment-root", "history-root", "backfill-manifest", "calendar-root", "protected-study-root", "output-root", "runtime-root"):
        build.add_argument("--" + name, type=Path, required=True)
    verify = commands.add_parser("verify")
    verify.add_argument("--output-root", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        root = _output_root(args.output_root)
        if args.command == "verify":
            result = verify_bundle(root)
        elif args.command == "build":
            result = build_bundle(args)
        else:
            _off(args.runtime_root)
            if (root / "calendar.receipt.json").exists():
                raw, receipt_raw = _calendar_material(root)
                if _json(receipt_raw)["query"] != {"start": args.start, "end": args.end}:
                    raise ValueError("existing calendar capture has another immutable scope")
                result = {"written": False, "provider_calls": 0, "calendar_sha256": sha256_bytes(raw)}
            else:
                raw, receipt_raw = calendar_get(args.start, args.end, _credentials(args, root))
                _off(args.runtime_root)
                sources = (args.credentials_file.absolute().parent,)
                _write(root / "calendar.json", raw, sources)
                _write(root / "calendar.receipt.json", receipt_raw, sources)
                result = {"written": True, "provider_calls": 1, "calendar_sha256": sha256_bytes(raw)}
        print(json.dumps({"command": args.command, **result}, sort_keys=True))
        return 0
    except ExperimentCaptureError as exc:
        print(json.dumps({"error": exc.code, "http_status": exc.http_status}), file=sys.stderr)
        return 2
    except (ValueError, OSError, TypeError, KeyError, JournalStoreError, RecursionError):
        print("shadow-historical-baseline: rejected; check retained sources, cutoff, bundle and OFF runtime", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
