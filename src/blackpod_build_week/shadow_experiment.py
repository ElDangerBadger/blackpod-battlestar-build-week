"""A single prospective observational pilot over the existing reversal proposal.

This module is offline. It records provider-price diagnostics, never orders,
simulated executable fills, net performance, or changes to old research gates.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, time, timedelta
from decimal import Context, Decimal, ROUND_HALF_EVEN, localcontext
from pathlib import Path
from zoneinfo import ZoneInfo

from .contracts.shadow_experiment import (
    AUTHORITY, CRITERIA, KIND, LIMITATIONS, METHOD, JOURNAL_VERSION, OBSERVATION_TYPE,
    OBSERVATION_VERSION, PROTOCOL_TYPE, PROTOCOL_VERSION, VIEW_VERSION,
    ShadowExperimentProtocol,
)
from .contracts.decision_journal import JournalEvent
from .contracts.historical_intake import validate_historical_capture
from .contracts.mission_request import parse_rfc3339, parse_strict_json_object_bytes
from .contracts.trading_accounting import accounting_timestamp
from .contracts.trading_hypothesis import TradingHypothesis
from .decision_journal_store import JournalStore
from .hashing import canonical_json_bytes, sha256_bytes
from .sentry_history_cache import read_regular
from .trading_historical_intake import _calendar, _number, parse_historical_json

CALENDAR_PATH = "shadow-experiment/protocol-calendar.json"
CALENDAR_RECEIPT_PATH = "shadow-experiment/protocol-calendar-receipt.json"
HYPOTHESIS_PATH = "shadow-experiment/hypothesis.json"
CODE_PATHS = ("contracts/shadow_experiment.py", "shadow_experiment.py", "shadow_experiment_cli.py",
    "shadow_experiment_capture.py", "contracts/historical_intake.py", "trading_historical_intake.py",
    "contracts/trading_hypothesis.py", "contracts/trading_accounting.py", "hashing.py")


def _identity(prefix, value):
    return prefix + "-" + sha256_bytes(canonical_json_bytes(value))


def _ref(path, raw):
    if not isinstance(raw, bytes):
        raise ValueError("pilot evidence must be bytes")
    return {"path": path, "sha256": sha256_bytes(raw), "size_bytes": len(raw)}


def _blob(blobs, reference):
    raw = blobs.get(reference["sha256"])
    if not isinstance(raw, bytes) or len(raw) != reference["size_bytes"] or sha256_bytes(raw) != reference["sha256"]:
        raise ValueError("pilot evidence differs from its retained hash or size")
    return raw


def _receipt(raw, body, kind, captured_at):
    row = validate_historical_capture(parse_strict_json_object_bytes(raw), kind)
    if row["body_sha256"] != sha256_bytes(body) or row["size_bytes"] != len(body):
        raise ValueError("pilot capture receipt does not bind the returned body")
    if parse_rfc3339(row["captured_at"], "receipt clock") > parse_rfc3339(captured_at, "capture clock"):
        raise ValueError("pilot receipt follows local record clock")
    return row


def _session_rows(calendar):
    return [{"date": day, **{field + "_at": clocks[field].isoformat().replace("+00:00", "Z")
        for field in ("open", "close", "session_open", "session_close")}} for day, clocks in sorted(calendar.items())]


def build_protocol(*, experiment_id, frozen_at, first_signal_session, calendar_captured_at,
                   calendar_raw, hypothesis_raw, calendar_receipt_raw):
    """Freeze 30 consecutive declared signal sessions, with untouched source spec."""
    frozen_at = accounting_timestamp(frozen_at, "frozen_at")
    calendar_captured_at = accounting_timestamp(calendar_captured_at, "calendar_captured_at")
    receipt = _receipt(calendar_receipt_raw, calendar_raw, "calendar", frozen_at)
    if receipt["captured_at"] != calendar_captured_at:
        raise ValueError("protocol calendar clock must equal the retained receipt clock")
    rows = _session_rows(_calendar(calendar_raw, receipt))
    dates = [row["date"] for row in rows]
    if first_signal_session not in dates:
        raise ValueError("first signal session is absent from retained calendar")
    index = dates.index(first_signal_session)
    if index < 1 or len(rows) < index + 32:
        raise ValueError("calendar must retain a previous session and32 sessions from first signal")
    context = rows[index - 1:index + 32]
    hypothesis = TradingHypothesis.from_bytes(hypothesis_raw)
    if hypothesis.hypothesis_id != "previous-session-reversal-v1":
        raise ValueError("pilot consumes only the existing previous-session reversal proposal")
    if parse_rfc3339(hypothesis.recorded_at, "hypothesis clock") > parse_rfc3339(frozen_at, "freeze clock"):
        raise ValueError("source hypothesis follows protocol freeze")
    return ShadowExperimentProtocol.from_mapping({
        "schema_version": PROTOCOL_VERSION, "method_version": METHOD, "experiment_id": experiment_id,
        "frozen_at": frozen_at, "first_signal_session": first_signal_session, "universe": ["QQQ", "SPY"],
        "sessions": context[1:31], "context_sessions": context,
        "hypothesis_evidence": _ref(HYPOTHESIS_PATH, hypothesis_raw), "calendar_evidence": _ref(CALENDAR_PATH, calendar_raw),
        "calendar_receipt_evidence": _ref(CALENDAR_RECEIPT_PATH, calendar_receipt_raw),
        "calendar_captured_at": calendar_captured_at, "original_hypothesis_id": hypothesis.hypothesis_id,
        "original_horizon": hypothesis.horizon, "observation_basis": "PROVIDER_DAILY_BAR_OPEN_TO_OPEN_GROSS_PROXY",
        "availability_buffer_seconds": 900, "criteria": deepcopy(CRITERIA), "scope": "PROSPECTIVE_OBSERVATION_ONLY",
        "auto_trading_enabled": False, "authority": dict(AUTHORITY), "execution_status": "NOT_EXECUTED",
        "realized_trade_pnl": None, "limitations": list(LIMITATIONS),
    }).to_dict()


def _implementation():
    root = Path(__file__).absolute().parent
    return {"shadow-experiment/implementation/" + path: read_regular(root / path) for path in CODE_PATHS}


def _protocol_event(protocol, blobs):
    protocol = ShadowExperimentProtocol.from_mapping(protocol).to_dict()
    evidence = {protocol[field]["path"]: _blob(blobs, protocol[field]) for field in (
        "hypothesis_evidence", "calendar_evidence", "calendar_receipt_evidence")}
    expected = build_protocol(experiment_id=protocol["experiment_id"], frozen_at=protocol["frozen_at"],
        first_signal_session=protocol["first_signal_session"], calendar_captured_at=protocol["calendar_captured_at"],
        calendar_raw=evidence[CALENDAR_PATH], hypothesis_raw=evidence[HYPOTHESIS_PATH],
        calendar_receipt_raw=evidence[CALENDAR_RECEIPT_PATH])
    if canonical_json_bytes(protocol) != canonical_json_bytes(expected):
        raise ValueError("protocol differs from exact source-derived frozen specification")
    implementation = _implementation()
    evidence.update(implementation)
    evidence["shadow-experiment/protocol.v1.json"] = canonical_json_bytes(protocol)
    decision = _identity("journal-decision", {"kind": KIND, "experiment_id": protocol["experiment_id"]})
    event = JournalEvent.from_mapping({"schema_version": JOURNAL_VERSION,
        "event_id": _identity("journal-event", {"decision_id": decision, "event_type": PROTOCOL_TYPE}),
        "decision_id": decision, "domain": "TRADING", "event_type": PROTOCOL_TYPE, "recorded_at": protocol["frozen_at"],
        "source": {"kind": KIND, "experiment_id": protocol["experiment_id"], "source_sha256": sha256_bytes(canonical_json_bytes(protocol))},
        "evidence": [_ref(path, raw) for path, raw in sorted(evidence.items())],
        "payload": {"protocol": protocol, "implementation_evidence": [_ref(path, raw) for path, raw in sorted(implementation.items())]}})
    return event, evidence


def _history(events):
    if not events or events[0].event_type != PROTOCOL_TYPE or any(event.source["kind"] != KIND for event in events):
        raise ValueError("pilot requires a separate journal beginning with one frozen protocol")
    if sum(event.event_type == PROTOCOL_TYPE for event in events) != 1:
        raise ValueError("pilot journal contains conflicting protocol registrations")
    first = events[0]
    if any(event.decision_id != first.decision_id for event in events):
        raise ValueError("pilot journal mixes experiment identities")
    predictions = [row for event in events[1:] for row in event.payload["predictions"]]
    outcomes = [row for event in events[1:] for row in event.payload["outcomes"]]
    return first, first.payload["protocol"], predictions, outcomes


def _utc(value):
    return parse_rfc3339(value, "pilot clock")


def _plus(value, seconds):
    return (_utc(value) + timedelta(seconds=seconds)).isoformat().replace("+00:00", "Z")


def _text(number):
    if number == 0:
        return "0"
    text = format(number, "f")
    return text.rstrip("0").rstrip(".") if "." in text else text


def _ratio(end, start):
    with localcontext(Context(prec=60, rounding=ROUND_HALF_EVEN)):
        return _text(Decimal(end) / Decimal(start) - 1)


def _source_bars(protocol, captured_at, calendar_raw, bars_raw, calendar_receipt_raw, bars_receipt_raw):
    calendar_receipt = _receipt(calendar_receipt_raw, calendar_raw, "calendar", captured_at)
    bars_receipt = _receipt(bars_receipt_raw, bars_raw, "bars", captured_at)
    calendar = _calendar(calendar_raw, calendar_receipt)
    available_calendar = {row["date"]: row for row in _session_rows(calendar)}
    for row in protocol["context_sessions"]:
        if available_calendar.get(row["date"]) != row:
            raise ValueError("observed calendar omits or changes a frozen pilot session")
    if bars_receipt["query"]["symbols"] != "QQQ,SPY":
        raise ValueError("pilot bars must bind exactly the frozen QQQ,SPY universe")
    source = parse_historical_json(bars_raw)
    if not isinstance(source, dict) or set(source) != {"bars", "next_page_token"} or source["next_page_token"] is not None:
        raise ValueError("pilot requires a complete native bars response with explicit pagination")
    returned = source["bars"]
    if returned is None:
        returned = {}
    if not isinstance(returned, dict) or not set(returned) <= {"QQQ", "SPY"}:
        raise ValueError("pilot source contains an unexpected symbol")
    values = {"QQQ": {}, "SPY": {}}
    query_start, query_end = (_utc(bars_receipt["query"][field]) for field in ("start", "end"))
    if query_end - query_start > timedelta(days=100):
        raise ValueError("pilot bars query exceeds the bounded observation interval")
    if sum(len(rows) for rows in returned.values() if isinstance(rows, list)) > bars_receipt["query"]["limit"]:
        raise ValueError("pilot returned more native bars than its retained query limit")
    source_clock = _utc(bars_receipt["captured_at"])
    ny = ZoneInfo("America/New_York")
    for symbol in ("QQQ", "SPY"):
        rows, prior = returned.get(symbol, []), None
        if not isinstance(rows, list) or len(rows) > 10000:
            raise ValueError("pilot bars must be a bounded native list")
        for row in rows:
            if not isinstance(row, dict) or set(row) != {"t", "o", "h", "l", "c", "v", "n", "vw"}:
                raise ValueError("pilot bars must retain exact native OHLCV,count,and VWAP")
            stamp = _utc(row["t"])
            day = stamp.astimezone(ny).date()
            midnight = datetime.combine(day, time(), ny).astimezone(stamp.tzinfo)
            if stamp != midnight or not query_start <= stamp <= query_end or stamp > source_clock:
                raise ValueError("pilot bar label falls outside its declared capture query or clock")
            if day.isoformat() not in calendar or (prior is not None and stamp <= prior):
                raise ValueError("pilot bar labels must be calendar-bound,distinct,and chronological")
            prior = stamp
            _number(row["n"], "bar.n", integer=True)
            _number(row["vw"], "bar.vw", positive=True)
            normalized = {"symbol": symbol, "open": _number(row["o"], "bar.open", positive=True),
                "high": _number(row["h"], "bar.high", positive=True), "low": _number(row["l"], "bar.low", positive=True),
                "close": _number(row["c"], "bar.close", positive=True), "volume": _number(row["v"], "bar.volume", integer=True)}
            lower, upper = Decimal(normalized["low"]), Decimal(normalized["high"])
            if lower > upper or any(not lower <= Decimal(normalized[field]) <= upper for field in ("open", "close")):
                raise ValueError("pilot native bar OHLC relationship is invalid")
            values[symbol][day.isoformat()] = normalized
    # Only complete extended-session daily aggregates enter a prediction or
    # outcome. Returned but still mutable in-progress bars remain raw evidence.
    clocks = {row["date"]: _utc(_plus(row["session_close_at"], 900)) for row in protocol["context_sessions"]}
    return {symbol: {day: row for day, row in rows.items() if day in clocks and clocks[day] <= source_clock}
            for symbol, rows in values.items()}


def _prediction(protocol, index, symbol, captured_at, bars, previous):
    context = protocol["context_sessions"]
    prior, signal, entry, exit_ = context[index - 1:index + 3]
    status, reasons, signal_return, close, previous_close = "DEFER_MISSING_INPUT", ["MISSING_COMPLETED_CLOSE_INPUT"], None, None, None
    if _utc(captured_at) >= _utc(_plus(entry["session_open_at"], -300)):
        status, reasons = "MISSED_PREDICTION_DEADLINE", ["NO_RECONSTRUCTION_OF_HISTORICAL_PREDICTION"]
    elif prior["date"] in bars[symbol] and signal["date"] in bars[symbol]:
        close, previous_close = bars[symbol][signal["date"]]["close"], bars[symbol][prior["date"]]["close"]
        signal_return = _ratio(close, previous_close)
        if Decimal(close) >= Decimal(previous_close):
            status, reasons = "ABSTAIN_NONNEGATIVE_RETURN", ["FROZEN_NEGATIVE_CLOSE_CONDITION_NOT_MET"]
        elif any(row["symbol"] == symbol and row["status"] == "OBSERVATIONAL_CANDIDATE"
                 and _utc(row["exit_open_at"]) > _utc(entry["session_open_at"]) for row in previous):
            status, reasons = "ABSTAIN_OVERLAP", ["PREVIOUS_CANDIDATE_HOLDING_INTERVAL_STILL_OPEN"]
        else:
            status, reasons = "OBSERVATIONAL_CANDIDATE", ["NEGATIVE_COMPLETED_PROVIDER_CLOSE_RETURN"]
    identity = {"experiment_id": protocol["experiment_id"], "signal_session": signal["date"], "symbol": symbol}
    return {"prediction_id": _identity("shadow-prediction", identity), "symbol": symbol, "signal_session": signal["date"],
        "signal_close_at": signal["close_at"], "signal_available_at": _plus(signal["session_close_at"], 900),
        "entry_session": entry["date"], "entry_open_at": entry["session_open_at"], "exit_session": exit_["date"],
        "exit_open_at": exit_["session_open_at"], "outcome_available_at": _plus(exit_["session_close_at"], 900),
        "recorded_at": captured_at, "status": status, "reason_codes": reasons, "signal_return": signal_return,
        "signal_close": close, "previous_close": previous_close}


def _outcome(prediction, captured_at, bars):
    status, reasons = "NOT_APPLICABLE_ABSTENTION", [prediction["status"]]
    candidate, control, cash, excess, entry, exit_ = None, None, None, None, None, None
    if prediction["status"] == "OBSERVATIONAL_CANDIDATE":
        dates = prediction["entry_session"], prediction["exit_session"]
        if any(day not in bars[symbol] for symbol in ("QQQ", "SPY") for day in dates):
            return None
        entry, exit_ = (bars[prediction["symbol"]][day]["open"] for day in dates)
        candidate = _ratio(exit_, entry)
        with localcontext(Context(prec=60, rounding=ROUND_HALF_EVEN)):
            returns = [Decimal(_ratio(bars[symbol][dates[1]]["open"], bars[symbol][dates[0]]["open"])) for symbol in ("QQQ", "SPY")]
            control = _text(sum(returns) / 2)
            excess = _text(Decimal(candidate) - Decimal(control))
        cash, status, reasons = "0", "OBSERVED_GROSS_PROXY_ONLY", ["COMPLETE_PROVIDER_OPEN_PROXY_PAIR_NO_EXECUTABILITY_OR_NET_CLAIM"]
    elif prediction["status"] in {"MISSED_PREDICTION_DEADLINE", "DEFER_MISSING_INPUT"}:
        status = "UNMEASURABLE"
    return {"outcome_id": _identity("shadow-outcome", {"prediction_id": prediction["prediction_id"]}),
        "prediction_id": prediction["prediction_id"], "symbol": prediction["symbol"], "recorded_at": captured_at,
        "status": status, "candidate_gross_return": candidate, "control_gross_return": control,
        "cash_return": cash, "excess_over_control": excess, "reason_codes": reasons, "entry_price": entry, "exit_price": exit_}


def _observation_event(events, blobs, *, captured_at, calendar_raw, bars_raw, calendar_receipt_raw, bars_receipt_raw):
    original, protocol, previous, old_outcomes = _history(events)
    captured_at = accounting_timestamp(captured_at, "captured_at")
    if _utc(captured_at) <= _utc(events[-1].recorded_at):
        raise ValueError("observation clock must advance beyond its retained predecessor")
    bars = _source_bars(protocol, captured_at, calendar_raw, bars_raw, calendar_receipt_raw, bars_receipt_raw)
    retained = {row["prediction_id"] for row in previous}
    predictions = []
    for index in range(1, 31):
        signal = protocol["context_sessions"][index]
        if _utc(captured_at) < _utc(_plus(signal["session_close_at"], 900)):
            continue
        for symbol in protocol["universe"]:
            row = _prediction(protocol, index, symbol, captured_at, bars, previous + predictions)
            if row["prediction_id"] not in retained:
                predictions.append(row)
    finished = {row["prediction_id"] for row in old_outcomes}
    outcomes = []
    for row in previous + predictions:
        if row["prediction_id"] in finished or _utc(captured_at) < _utc(row["outcome_available_at"]):
            continue
        result = _outcome(row, captured_at, bars)
        if result is not None:
            outcomes.append(result)
    evidence = {"shadow-experiment/observation-calendar.json": calendar_raw,
        "shadow-experiment/observation-calendar-receipt.json": calendar_receipt_raw,
        "shadow-experiment/observation-bars.json": bars_raw,
        "shadow-experiment/observation-bars-receipt.json": bars_receipt_raw}
    references = {path: _ref(path, raw) for path, raw in evidence.items()}
    payload = {"schema_version": OBSERVATION_VERSION, "experiment_id": protocol["experiment_id"], "captured_at": captured_at,
        "protocol_event_id": original.event_id, "previous_observation_event_id": None if len(events) == 1 else events[-1].event_id,
        "calendar_evidence": references["shadow-experiment/observation-calendar.json"],
        "calendar_receipt_evidence": references["shadow-experiment/observation-calendar-receipt.json"],
        "bars_evidence": references["shadow-experiment/observation-bars.json"],
        "bars_receipt_evidence": references["shadow-experiment/observation-bars-receipt.json"],
        "predictions": predictions, "outcomes": outcomes}
    evidence["shadow-experiment/observation.v1.json"] = canonical_json_bytes(payload)
    references["shadow-experiment/observation.v1.json"] = _ref("shadow-experiment/observation.v1.json", evidence["shadow-experiment/observation.v1.json"])
    return JournalEvent.from_mapping({"schema_version": JOURNAL_VERSION,
        "event_id": _identity("journal-event", {"decision_id": original.decision_id, "event_type": OBSERVATION_TYPE, "captured_at": captured_at}),
        "decision_id": original.decision_id, "domain": "TRADING", "event_type": OBSERVATION_TYPE, "recorded_at": captured_at,
        "source": {"kind": KIND, "experiment_id": protocol["experiment_id"], "source_sha256": sha256_bytes(canonical_json_bytes(payload))},
        "evidence": list(references.values()), "payload": payload}), evidence


def validate_shadow_experiment_event(event, previous_events, blobs):
    """Replay exact arithmetic and source bindings during every journal scan."""
    if event.event_type == PROTOCOL_TYPE:
        if previous_events:
            raise ValueError("shadow experiment protocol requires its own empty journal")
        expected, evidence = _protocol_event(event.payload["protocol"], blobs)
    else:
        payload = event.payload
        expected, evidence = _observation_event(tuple(previous_events), blobs, captured_at=event.recorded_at,
            **{field + "_raw": _blob(blobs, payload[field + "_evidence"]) for field in ("calendar", "bars", "calendar_receipt", "bars_receipt")})
    for reference in event.evidence:
        _blob(blobs, reference)
    if event.to_bytes() != expected.to_bytes():
        raise ValueError("shadow experiment event differs from deterministic source-bound replay")
    for path, raw in evidence.items():
        reference = next(ref for ref in event.evidence if ref["path"] == path)
        if _blob(blobs, reference) != raw:
            raise ValueError("shadow experiment implementation or source differs")


def freeze_experiment(root, protocol, evidence):
    """Explicit immutable registration. The caller must stamp its actual clock."""
    protocol = ShadowExperimentProtocol.from_mapping(protocol).to_dict()
    expected_paths = {HYPOTHESIS_PATH, CALENDAR_PATH, CALENDAR_RECEIPT_PATH}
    if set(evidence) != expected_paths:
        raise ValueError("freeze requires exactly the source hypothesis,calendar,and receipt bytes")
    blobs = {sha256_bytes(raw): raw for raw in evidence.values()}
    event, source = _protocol_event(protocol, blobs)
    result = JournalStore(Path(root)).append(event, source)
    return {"event_id": result.event_id, "written": result.written, "sequence": result.sequence,
            "view": read_experiment_view(root)}


def collect_observation(root, *, captured_at, calendar_raw, bars_raw, calendar_receipt_raw, bars_receipt_raw):
    """Append one atomic snapshot; missed forecasts can never be reconstructed."""
    store = JournalStore(Path(root))
    events, blobs = store.verified_contents()
    captured_at = accounting_timestamp(captured_at, "captured_at")
    retries = [index for index, event in enumerate(events) if event.event_type == OBSERVATION_TYPE and event.recorded_at == captured_at]
    previous = events[:retries[0]] if retries else events
    event, evidence = _observation_event(previous, blobs, captured_at=captured_at, calendar_raw=calendar_raw,
        bars_raw=bars_raw, calendar_receipt_raw=calendar_receipt_raw, bars_receipt_raw=bars_receipt_raw)
    result = store.append(event, evidence)
    return {"event_id": result.event_id, "written": result.written, "sequence": result.sequence,
            "new_prediction_count": len(event.payload["predictions"]), "new_outcome_count": len(event.payload["outcomes"]),
            "view": read_experiment_view(root)}


def read_experiment_view(root):
    """Read-only verified projection for the CLI and Cabin; no provider access."""
    store = JournalStore(Path(root))
    events, blobs = store.verified_contents()
    _, protocol, predictions, outcomes = _history(events)
    measured = [row for row in outcomes if row["status"] == "OBSERVED_GROSS_PROXY_ONLY"]
    latest = None if len(events) == 1 else events[-1].recorded_at
    mean, excess, positive = None, None, None
    if measured:
        with localcontext(Context(prec=60, rounding=ROUND_HALF_EVEN)):
            mean = _text(sum(Decimal(row["candidate_gross_return"]) for row in measured) / len(measured))
            excess = _text(sum(Decimal(row["excess_over_control"]) for row in measured) / len(measured))
            positive = _text(Decimal(sum(Decimal(row["candidate_gross_return"]) > 0 for row in measured)) / len(measured))
    complete_at = _plus(protocol["context_sessions"][-1]["session_close_at"], 900)
    completed = latest is not None and _utc(latest) >= _utc(complete_at)
    missing = any(row["status"] in {"MISSED_PREDICTION_DEADLINE", "DEFER_MISSING_INPUT"} for row in predictions)
    if not completed:
        conclusion = "PENDING"
    elif len(predictions) != 60 or len(outcomes) != 60 or missing:
        conclusion = "INCONCLUSIVE_MISSING_EVIDENCE"
    elif len(measured) < CRITERIA["minimum_observed_candidates"]:
        conclusion = "INCONCLUSIVE_TOO_FEW_CANDIDATES"
    elif Decimal(mean) > 0 and Decimal(excess) > 0:
        conclusion = "DESCRIPTIVE_POSITIVE_PROXY_ONLY"
    else:
        conclusion = "DESCRIPTIVE_NONPOSITIVE_PROXY"
    summary = {"opportunity_count": 60, "recorded_prediction_count": len(predictions),
        "pending_prediction_count": 60 - len(predictions),
        "candidate_count": sum(row["status"] == "OBSERVATIONAL_CANDIDATE" for row in predictions),
        "abstention_count": sum(row["status"].startswith("ABSTAIN") for row in predictions),
        "missed_count": sum(row["status"] == "MISSED_PREDICTION_DEADLINE" for row in predictions),
        "missing_input_count": sum(row["status"] == "DEFER_MISSING_INPUT" for row in predictions),
        "observed_outcome_count": len(measured), "pending_outcome_count": len(predictions) - len(outcomes),
        "mean_gross_return": mean, "mean_gross_excess_over_control": excess,
        "positive_gross_outcome_fraction": positive, "conclusion": conclusion,
        "economic_support": "NOT_EVALUABLE", "net_return": None, "next_action": "MANUAL_REVIEW_AFTER_PILOT_NO_AUTOMATIC_EXTENSION"}
    raw = read_regular(Path(root) / "entries" / (f"{len(events):08d}.json"))
    return {"schema_version": VIEW_VERSION, "protocol": deepcopy(protocol),
        "journal": {"event_count": len(events), "evidence_blob_count": len(blobs), "last_entry_sha256": sha256_bytes(raw)},
        "predictions": deepcopy(predictions), "outcomes": deepcopy(outcomes), "summary": summary,
        "latest_captured_at": latest, "auto_trading_enabled": False, "authority": dict(AUTHORITY), "limitations": list(LIMITATIONS)}
