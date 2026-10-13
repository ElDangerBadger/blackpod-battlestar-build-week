"""Isolated, source-pinned Galactica quantile fitting for explicit SHADOW export.

The existing native feature and model factories are selected from reviewed AST
definitions. Module initializers, joblib cache loading, persistence, providers,
and execution are never imported. Replay checks data-only linear coefficients
against retained inputs; it never fits a model or invokes a provider.
"""
from __future__ import annotations

import ast
import math
import platform
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Dict, Optional, Tuple
from zoneinfo import ZoneInfo

from .contracts.mission_request import parse_rfc3339
from .contracts.trading_accounting import accounting_decimal, accounting_timestamp
from .contracts.trading_reconciliation import symbol_text
from .hashing import canonical_json_bytes, sha256_bytes
from .sentry_history_cache import read_regular

SCHEMA_VERSION = "blackpod.shadow_quantitative_producer.v1"
MODEL_SCHEMA_VERSION = "blackpod.shadow_linear_quantile_model.v1"
SOURCE_PINS = {
    "phase2_forecast_engine.py": "cc1a15539b72507cd8d0c0aca09f7a10132c49b2c8476e5a849976ae71551205",
    "models/model_library.py": "c865de17d1e4bd0efe8161ec9be81cb47ec892358144c23c5e93ab7cd5b5d76b",
}
QUANTILES = (("q10", 0.1), ("q50", 0.5), ("q90", 0.9))
HORIZONS = (1, 2, 3, 4, 5)
_NY = ZoneInfo("America/New_York")
_FEATURE_FUNCTIONS = {"_sma", "_ema", "_rsi", "_macd", "_bollinger", "_atr", "enrich_features"}
_MODEL_FUNCTIONS = {"_select_features", "_make_model"}


class ShadowQuantitativeProducerError(ValueError):
    pass


class QuantitativeDependencyUnavailable(ShadowQuantitativeProducerError):
    """An existing environment lacks required libraries; no install is attempted."""


def _authority():
    return {name: False for name in ("authorization_enabled", "capital_activation_enabled", "execution_enabled", "policy_changes_enabled")}


def capture_quantitative_sources(root):
    root = Path(root)
    result = {path: read_regular(root / path) for path in SOURCE_PINS}
    _sources(result)
    return result


def _sources(sources):
    if not isinstance(sources, dict) or set(sources) != set(SOURCE_PINS):
        raise ShadowQuantitativeProducerError("quantitative producer requires the exact reviewed source closure")
    for path, digest in SOURCE_PINS.items():
        raw = sources[path]
        if not isinstance(raw, bytes) or len(raw) > 1024 * 1024 or sha256_bytes(raw) != digest:
            raise ShadowQuantitativeProducerError("native quantitative source fingerprint differs: " + path)


def native_quantitative_config(sources):
    """Retain the actual source defaults, independent of ambient env overrides.

    CONFIG remains unmodified, including its original persistence declarations.
    Persistence functions are excluded from the selected execution closure.
    """
    _sources(sources)
    tree = ast.parse(sources["phase2_forecast_engine.py"])
    assignment = next(node for node in tree.body if isinstance(node, ast.AnnAssign)
                      and isinstance(node.target, ast.Name) and node.target.id == "CONFIG")
    class DefaultsOnly(ast.NodeTransformer):
        def visit_Call(self, node):
            if (isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name)
                and node.func.value.id == "os" and node.func.attr == "getenv"
                and len(node.args) == 2 and not node.keywords):
                return node.args[1]
            raise ShadowQuantitativeProducerError("native configuration has an unsupported expression")
    return ast.literal_eval(DefaultsOnly().visit(assignment.value))


def _native(sources, *, fitting=False):
    _sources(sources)
    try:
        import numpy as np
        import pandas as pd
    except ImportError as exc:
        raise QuantitativeDependencyUnavailable("existing pandas and numpy are required; no dependencies are installed") from exc
    namespace = {"pd": pd, "np": np, "Dict": Dict, "Optional": Optional, "Tuple": Tuple,
                 "CONFIG": native_quantitative_config(sources), "GradientBoostingRegressor": None}
    if fitting:
        try:
            from sklearn.linear_model import QuantileRegressor
        except ImportError as exc:
            raise QuantitativeDependencyUnavailable("existing scikit-learn and scipy are required for explicit fitting; no dependencies are installed") from exc
        namespace["QuantileRegressor"] = QuantileRegressor
    for path, wanted in (("models/model_library.py", _FEATURE_FUNCTIONS),
                         ("phase2_forecast_engine.py", _MODEL_FUNCTIONS)):
        tree = ast.parse(sources[path])
        selected = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in wanted]
        if {node.name for node in selected} != wanted:
            raise ShadowQuantitativeProducerError("reviewed native source does not contain the required definitions")
        module = ast.Module(body=selected, type_ignores=[])
        exec(compile(ast.fix_missing_locations(module), "retained-quantitative/" + path, "exec"), namespace)
    return namespace, pd, np


def _number(value, name, *, positive=False):
    if type(value) not in (int, float, str):
        raise ShadowQuantitativeProducerError(name + " must be a finite observation")
    try:
        result = Decimal(accounting_decimal(str(value), name, positive=positive, nonnegative=True))
    except ValueError as exc:
        raise ShadowQuantitativeProducerError(name + " must be a finite bounded observation") from exc
    if result > Decimal("1e20"):
        raise ShadowQuantitativeProducerError(name + " exceeds the supported observation range")
    return float(result)


def _value(number):
    number = float(number)
    if not math.isfinite(number):
        raise ShadowQuantitativeProducerError("native quantitative analysis produced a nonfinite value")
    return accounting_decimal(format(Decimal(repr(number)), "f"), "native quantitative value", output=True)


def _calendar(calendar, issued_at):
    if not isinstance(calendar, dict) or set(calendar) != {"captured_at", "sessions"}:
        raise ShadowQuantitativeProducerError("calendar requires explicit capture and normalized session evidence")
    captured = parse_rfc3339(accounting_timestamp(calendar["captured_at"], "calendar captured_at"), "calendar captured_at")
    if captured > issued_at:
        raise ShadowQuantitativeProducerError("calendar capture cannot follow forecast issuance")
    sessions, previous, days = [], None, set()
    if not isinstance(calendar["sessions"], list) or not 6 <= len(calendar["sessions"]) <= 10000:
        raise ShadowQuantitativeProducerError("calendar requires a bounded historical and future session sequence")
    for row in calendar["sessions"]:
        if not isinstance(row, dict) or set(row) != {"date", "opens_at", "closes_at"}:
            raise ShadowQuantitativeProducerError("calendar sessions require explicit date, open and close")
        try:
            day = date.fromisoformat(row["date"])
        except (TypeError, ValueError) as exc:
            raise ShadowQuantitativeProducerError("session date must be ISO date") from exc
        opened = parse_rfc3339(accounting_timestamp(row["opens_at"], "session open"), "session open")
        closed = parse_rfc3339(accounting_timestamp(row["closes_at"], "session close"), "session close")
        if (day.isoformat() != row["date"] or opened.astimezone(_NY).date() != day
            or closed.astimezone(_NY).date() != day or not opened < closed
            or previous is not None and not previous < opened or day in days):
            raise ShadowQuantitativeProducerError("calendar sessions must be unique, ordered, nonoverlapping and date-bound")
        days.add(day); previous = closed
        sessions.append((day, row["opens_at"], row["closes_at"], closed))
    return sessions


def _history(history, issued_at):
    if not isinstance(history, dict) or not {"captured_at", "bars"} <= set(history):
        raise ShadowQuantitativeProducerError("history requires frozen capture and daily bars")
    captured = parse_rfc3339(accounting_timestamp(history["captured_at"], "history captured_at"), "history captured_at")
    if captured > issued_at:
        raise ShadowQuantitativeProducerError("history capture cannot follow forecast issuance")
    if not isinstance(history["bars"], dict) or not 1 <= len(history["bars"]) <= 128:
        raise ShadowQuantitativeProducerError("daily-bar universe must be bounded and nonempty")
    for symbol in history["bars"]:
        symbol_text(symbol)
    return captured


def _prepared_symbols(history, calendar, sources, issued_at, symbols):
    namespace, pd, np = _native(sources)
    issue = parse_rfc3339(accounting_timestamp(issued_at, "issued_at"), "issued_at")
    captured = _history(history, issue)
    sessions = _calendar(calendar, issue)
    by_day = {row[0]: (index, row) for index, row in enumerate(sessions)}
    selected = sorted(history["bars"]) if symbols is None else list(symbols)
    if not selected or len(selected) > 128 or len(set(selected)) != len(selected):
        raise ShadowQuantitativeProducerError("producer symbols must be a unique bounded nonempty list")
    for symbol in selected:
        symbol_text(symbol)
        if symbol not in history["bars"]:
            raise ShadowQuantitativeProducerError("requested symbol has no frozen daily history")
    prepared = []
    for symbol in selected:
        bars = history["bars"][symbol]
        if not isinstance(bars, list) or not 1 <= len(bars) <= 10000:
            raise ShadowQuantitativeProducerError("daily bars must be a bounded nonempty list")
        points, previous, days, excluded = [], None, set(), 0
        for row in bars:
            if not isinstance(row, dict) or set(row) - {"t", "o", "h", "l", "c", "v", "n", "vw"} or not {"t", "o", "h", "l", "c", "v"} <= set(row):
                raise ShadowQuantitativeProducerError("daily bars require explicit retained Alpaca OHLCV fields")
            when = parse_rfc3339(accounting_timestamp(row["t"], "daily bar timestamp"), "daily bar timestamp")
            day = when.astimezone(_NY).date()
            if when > captured or previous is not None and when <= previous or day in days:
                raise ShadowQuantitativeProducerError("daily bars must be ordered unique observations before capture")
            previous = when; days.add(day)
            if day not in by_day:
                raise ShadowQuantitativeProducerError("daily-bar date has no retained exchange session")
            _, session = by_day[day]
            values = {key: _number(row[key], key, positive=key != "v") for key in ("o", "h", "l", "c", "v")}
            if not values["l"] <= min(values["o"], values["c"]) <= max(values["o"], values["c"]) <= values["h"]:
                raise ShadowQuantitativeProducerError("daily-bar OHLC prices are inconsistent")
            if session[3] > captured:
                excluded += 1
                continue
            points.append((session[2], *(values[key] for key in ("o", "h", "l", "c", "v"))))
        if not points:
            raise ShadowQuantitativeProducerError("no completed daily bars are available")
        frame = pd.DataFrame(points, columns=["Date", "Open", "High", "Low", "Close", "Volume"])
        frame["Date"] = pd.to_datetime(frame["Date"], utc=True)
        cfg = namespace["CONFIG"]
        feature_cfg = {key: cfg["features"][key] for key in ("rsi_period", "macd_fast", "macd_slow", "macd_signal")}
        features = namespace["enrich_features"](frame, cfg=feature_cfg)
        if features.empty:
            raise ShadowQuantitativeProducerError("no usable native features remain after warmup")
        # Native dropna can remove interior sessions. Its shift(-h) then means h
        # feature rows, rather than h exchange sessions. Refuse that ambiguity.
        feature_dates = [value.to_pydatetime().astimezone(_NY).date() for value in features["Date"]]
        indices = [by_day[day][0] for day in feature_dates]
        if indices != list(range(indices[0], indices[-1] + 1)):
            raise ShadowQuantitativeProducerError("native feature rows have missing exchange sessions; target horizon is ambiguous")
        if features["Date"].iloc[-1] != frame["Date"].iloc[-1]:
            raise ShadowQuantitativeProducerError("latest completed session has no usable native features")
        window = cfg["model"]["window"]
        train = features.iloc[-window:].copy() if len(features) > window else features.copy()
        x, y, names = namespace["_select_features"](train)
        if len(x) < 30 or not names or len(names) > 128 or not np.isfinite(x.to_numpy()).all() or not np.isfinite(y.to_numpy()).all():
            raise ShadowQuantitativeProducerError("native feature matrix is insufficient or nonfinite")
        anchor_day = feature_dates[-1]
        anchor_index = by_day[anchor_day][0]
        future = sessions[anchor_index + 1:anchor_index + 1 + max(HORIZONS)]
        if len(future) != max(HORIZONS):
            raise ShadowQuantitativeProducerError("five actual future target sessions are required")
        if future[0][3] <= issue:
            raise ShadowQuantitativeProducerError("first forecast target session is no longer in the future")
        observations = [{"observed_at": value.isoformat().replace("+00:00", "Z"),
            "values": {name: _value(train[name].iloc[index]) for name in names}}
            for index, value in enumerate(train["Date"])]
        horizons = []
        for h in HORIZONS:
            targets = y.shift(-h)
            valid = targets.notna()
            if int(valid.sum()) < 30:
                continue  # Matches native minimum; do not invent missing models.
            training = []
            for index in range(len(train) - h):
                training.append({"observed_at": observations[index]["observed_at"],
                    "target_observed_at": observations[index + h]["observed_at"],
                    "values": dict(observations[index]["values"], target_close=_value(targets.iloc[index]))})
            horizons.append({"horizon_count": h, "training_cutoff": training[-1]["target_observed_at"],
                "training_observations": training, "target_at": future[h - 1][2]})
        if not horizons:
            raise ShadowQuantitativeProducerError("native producer has no horizon with thirty training labels")
        # Calendar close proves the regular session ended, not that every
        # daily feature had its retained value then. Alpaca daily Volume can
        # continue incorporating extended-hours trades. Stamp availability of
        # the latest OHLCV-derived feature vector at its actual capture; retain
        # regular-close event times for the reference price and training labels.
        reference_at = observations[-1]["observed_at"]
        observations[-1]["observed_at"] = accounting_timestamp(history["captured_at"], "feature captured_at")
        prepared.append({"symbol": symbol, "bar_count": len(bars), "completed_bar_count": len(points),
            "excluded_incomplete_bar_count": excluded, "feature_cutoff": observations[-1]["observed_at"],
            "reference_price": _value(train["Close"].iloc[-1]), "reference_at": reference_at,
            "feature_names": names, "feature_observations": observations, "horizons": horizons})
    return prepared


def prepare_shadow_quantitative_features(history, calendar, sources, *, issued_at, symbols=None):
    """Provider-free native feature and completed-label preparation, without fit."""
    return _prepared_symbols(history, calendar, sources, issued_at, symbols)


def _fingerprint():
    import importlib.metadata as metadata
    result = {"python": platform.python_version()}
    for name in ("numpy", "pandas", "scikit-learn", "scipy"):
        try:
            result[name] = metadata.version(name)
        except metadata.PackageNotFoundError as exc:
            raise QuantitativeDependencyUnavailable("required existing quantitative runtime library is unavailable: " + name) from exc
    return result


def _artifact(model, q, names, training, config):
    return {"schema_version": MODEL_SCHEMA_VERSION, "model_kind": "QUANTILE_LINEAR", "quantile": _value(q),
        "feature_names": list(names), "training_sha256": sha256_bytes(canonical_json_bytes(training)),
        "config_sha256": sha256_bytes(canonical_json_bytes(config)), "intercept": _value(model.intercept_),
        "coefficients": [_value(value) for value in model.coef_],
        "params": {"alpha": "0.0", "fit_intercept": True, "solver": "highs", "solver_options": None},
        "n_iter": int(model.n_iter_)}


def build_shadow_quantitative_forecasts(history, calendar, sources, *, issued_at, symbols=None):
    """Explicit CPU fit and prediction using existing libraries and native rules.

    No cache is read or written. The caller alone retains returned evidence.
    Raw labeled quantiles govern intake; native sorted output is evidence only.
    """
    issued_at = accounting_timestamp(issued_at, "issued_at")
    prepared = _prepared_symbols(history, calendar, sources, issued_at, symbols)
    namespace, pd, np = _native(sources, fitting=True)
    config = native_quantitative_config(sources)
    if config["model"]["type"] != "quantile_linear":
        raise ShadowQuantitativeProducerError("this reviewed shadow producer supports the unchanged native linear defaults only")
    runtime = _fingerprint()
    for symbol in prepared:
        names = symbol["feature_names"]
        live = pd.DataFrame([[float(symbol["feature_observations"][-1]["values"][name]) for name in names]], columns=names)
        for horizon in symbol["horizons"]:
            training = horizon["training_observations"]
            x = pd.DataFrame([[float(row["values"][name]) for name in names] for row in training], columns=names)
            y = np.asarray([float(row["values"]["target_close"]) for row in training])
            raw, models = {}, {}
            for label, q in QUANTILES:
                model = namespace["_make_model"](q)
                try:
                    model.fit(x, y)
                    raw[label] = _value(model.predict(live)[0])
                except (ValueError, TypeError, ArithmeticError, RuntimeError) as exc:
                    raise ShadowQuantitativeProducerError("native quantile fit/prediction failed; no fallback or repair: "
                        + symbol["symbol"] + "/h" + str(horizon["horizon_count"]) + "/" + label) from exc
                models[label] = _artifact(model, q, names, training, config)
            horizon["raw_quantiles"] = raw
            horizon["native_sorted_quantiles"] = dict(zip((label for label, _ in QUANTILES), sorted(raw.values(), key=Decimal)))
            horizon["model_artifacts"] = models
    return {"schema_version": SCHEMA_VERSION, "issued_at": issued_at,
        "history_sha256": sha256_bytes(canonical_json_bytes(history)), "calendar_sha256": sha256_bytes(canonical_json_bytes(calendar)),
        "native_source_sha256": dict(SOURCE_PINS), "runtime_fingerprint": runtime, "config": config,
        "symbols": prepared, "authority": _authority()}


def _replay_model(model, names, training, config, live, np):
    fields = {"schema_version", "model_kind", "quantile", "feature_names", "training_sha256", "config_sha256",
              "intercept", "coefficients", "params", "n_iter"}
    if not isinstance(model, dict) or set(model) != fields or model["schema_version"] != MODEL_SCHEMA_VERSION or model["model_kind"] != "QUANTILE_LINEAR":
        raise ShadowQuantitativeProducerError("retained linear model artifact has an unsupported schema")
    if (model["feature_names"] != names or model["training_sha256"] != sha256_bytes(canonical_json_bytes(training))
        or model["config_sha256"] != sha256_bytes(canonical_json_bytes(config))
        or model["params"] != {"alpha": "0.0", "fit_intercept": True, "solver": "highs", "solver_options": None}
        or type(model["n_iter"]) is not int or model["n_iter"] < 0):
        raise ShadowQuantitativeProducerError("retained linear model does not bind the native training/configuration")
    if not isinstance(model["coefficients"], list) or len(model["coefficients"]) != len(names):
        raise ShadowQuantitativeProducerError("retained coefficient count differs from the actual feature count")
    coefficients = [float(accounting_decimal(value, "coefficient", output=True)) for value in model["coefficients"]]
    intercept = float(accounting_decimal(model["intercept"], "intercept", output=True))
    # QuantileRegressor retains coef_ as params[1:] after its intercept. Keep
    # that data-only layout: a newly aligned standalone coefficient array can
    # change the native BLAS reduction's last float bits, despite equal values.
    params = np.asarray([intercept] + coefficients)
    result = np.asarray([[float(live[name]) for name in names]]) @ params[1:] + params[0]
    return _value(result[0])


def validate_shadow_quantitative_forecasts(result, history, calendar, sources):
    """Recreate native features and verify retained data-only predictions.

    Model fitting and optimality/calibration are not reverified during replay.
    A runtime fingerprint is a source-bound declaration, not an attestation.
    """
    fields = {"schema_version", "issued_at", "history_sha256", "calendar_sha256", "native_source_sha256",
              "runtime_fingerprint", "config", "symbols", "authority"}
    if not isinstance(result, dict) or set(result) != fields or result["schema_version"] != SCHEMA_VERSION:
        raise ShadowQuantitativeProducerError("quantitative producer result has unsupported fields")
    _sources(sources)
    config = native_quantitative_config(sources)
    if (result["history_sha256"] != sha256_bytes(canonical_json_bytes(history))
        or result["calendar_sha256"] != sha256_bytes(canonical_json_bytes(calendar))
        or result["native_source_sha256"] != SOURCE_PINS or result["config"] != config or result["authority"] != _authority()):
        raise ShadowQuantitativeProducerError("quantitative producer result differs from retained source bindings")
    fingerprint = result["runtime_fingerprint"]
    if not isinstance(fingerprint, dict) or set(fingerprint) != {"python", "numpy", "pandas", "scikit-learn", "scipy"} or any(not isinstance(value, str) or not value or len(value) > 64 for value in fingerprint.values()):
        raise ShadowQuantitativeProducerError("quantitative runtime fingerprint has unsupported fields")
    if not isinstance(result["symbols"], list) or not result["symbols"] or any(not isinstance(row, dict) or "symbol" not in row for row in result["symbols"]):
        raise ShadowQuantitativeProducerError("quantitative producer result requires symbol records")
    prepared = _prepared_symbols(history, calendar, sources, result["issued_at"], [row["symbol"] for row in result["symbols"]])
    _, _, np = _native(sources)
    for observed, expected in zip(result["symbols"], prepared):
        if set(observed) != set(expected) or any(observed[key] != value for key, value in expected.items() if key != "horizons"):
            raise ShadowQuantitativeProducerError("quantitative feature observations differ from native replay")
        if not isinstance(observed["horizons"], list) or len(observed["horizons"]) != len(expected["horizons"]):
            raise ShadowQuantitativeProducerError("quantitative horizon coverage differs from native replay")
        for horizon, target in zip(observed["horizons"], expected["horizons"]):
            if not isinstance(horizon, dict) or set(horizon) != set(target) | {"raw_quantiles", "native_sorted_quantiles", "model_artifacts"} or any(horizon[key] != value for key, value in target.items()):
                raise ShadowQuantitativeProducerError("quantitative target observations differ from native replay")
            raw, models = horizon["raw_quantiles"], horizon["model_artifacts"]
            if not isinstance(raw, dict) or set(raw) != {label for label, _ in QUANTILES} or not isinstance(models, dict) or set(models) != set(raw):
                raise ShadowQuantitativeProducerError("quantitative output requires all three labeled quantile models")
            for label, q in QUANTILES:
                if not isinstance(models[label], dict) or models[label].get("quantile") != _value(q):
                    raise ShadowQuantitativeProducerError("retained model quantile differs from its label")
                replay = _replay_model(models[label], observed["feature_names"], target["training_observations"], config,
                    observed["feature_observations"][-1]["values"], np)
                if raw[label] != replay:
                    raise ShadowQuantitativeProducerError("retained raw quantile differs from coefficient replay")
            if horizon["native_sorted_quantiles"] != dict(zip((label for label, _ in QUANTILES), sorted(raw.values(), key=Decimal))):
                raise ShadowQuantitativeProducerError("retained native sorted preview differs from raw model outputs")
    return result


def main(argv=None):
    """Explicit fresh-fit worker; output alone is written to a separate root."""
    import argparse
    import json
    import sys
    from .contracts.mission_request import parse_strict_json_object_bytes
    from .desk_candidate_review_cli import _write
    from .decision_journal_store import JournalStoreError, _check_existing_ancestors, _reject_source_storage, check_separate_root
    from .auto_trading_runtime import RuntimeLedger, TradingRuntimeError
    parser = argparse.ArgumentParser(description="Explicit source-pinned native quantile SHADOW fitting; no providers, caches or execution")
    parser.add_argument("--history", type=Path, required=True)
    parser.add_argument("--calendar", type=Path, required=True)
    parser.add_argument("--sources-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--symbols", nargs="+", required=True)
    args = parser.parse_args(argv)
    started_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    try:
        output = args.output.absolute()
        _check_existing_ancestors(output.parent); _reject_source_storage(output.parent)
        for source_root in (args.sources_root, args.history.parent, args.calendar.parent):
            check_separate_root(output.parent, source_root)
        RuntimeLedger(output.parent)  # Path checks alone; no control or journal writes.
        package_root = Path(__file__).absolute().parents[2]
        for ancestor in (output.parent, *output.parent.parents):
            if any((ancestor / name).exists() for name in ("ledger.lock", "worker.lock")):
                raise ShadowQuantitativeProducerError("fit output overlaps installed trading runtime storage")
            if ancestor.name == ".git":
                raise ShadowQuantitativeProducerError("fit output cannot use repository metadata")
            if (ancestor / ".git").exists():
                if ancestor == package_root and output.relative_to(ancestor).parts[0] == "output":
                    break
                raise ShadowQuantitativeProducerError("fit output cannot use repository source trees")
        try:
            output.lstat()
        except FileNotFoundError:
            pass
        else:
            raise ShadowQuantitativeProducerError("fit output already exists; replay the retained export without fitting again")
        history = parse_strict_json_object_bytes(read_regular(args.history))
        calendar = parse_strict_json_object_bytes(read_regular(args.calendar))
        sources = capture_quantitative_sources(args.sources_root)
        result = build_shadow_quantitative_forecasts(history, calendar, sources, issued_at=started_at, symbols=args.symbols)
        # The issue clock follows completed fitting. It is never backdated to a
        # daily bar label, invocation start, or historical price observation.
        completed_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        result["issued_at"] = completed_at
        validate_shadow_quantitative_forecasts(result, history, calendar, sources)
        raw = canonical_json_bytes(result)
        _write(output, raw, (args.sources_root, args.history.parent, args.calendar.parent))
        print(json.dumps({"schema_version": "blackpod.shadow_quantitative_worker_receipt.v1", "started_at": started_at,
            "completed_at": completed_at, "output_sha256": sha256_bytes(raw), "size_bytes": len(raw),
            "symbol_count": len(result["symbols"]), "model_fit_count": sum(3 * len(row["horizons"]) for row in result["symbols"]),
            "provider_calls": 0, "orders_submitted": 0, "auto_trading_enabled": False}, sort_keys=True))
        return 0
    except (ValueError, OSError, TypeError, JournalStoreError, TradingRuntimeError) as exc:
        print("shadow-quantitative-producer: " + str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
