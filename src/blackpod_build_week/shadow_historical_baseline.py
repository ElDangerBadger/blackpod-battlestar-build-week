"""One fixed retrospective price-proxy comparison, separate from the live pilot.

This calculator does not produce forecasts, orders, policy changes or qualified
backtest returns. It reuses the pilot's fixed signal and arithmetic, retaining
every returned-calendar opportunity and all reasons a comparison is absent.
"""
from __future__ import annotations

from collections import Counter
from copy import deepcopy
import csv
from decimal import Context, Decimal, InvalidOperation, ROUND_HALF_EVEN, localcontext
from io import StringIO
from pathlib import Path

from .contracts.historical_intake import historical_date, validate_historical_capture
from .contracts.mission_request import parse_strict_json_object_bytes
from .contracts.shadow_experiment import AUTHORITY, CRITERIA, ShadowExperimentProtocol
from .hashing import canonical_json_bytes, sha256_bytes
from .sentry_history_cache import read_regular
from .shadow_experiment import _ratio, _text
from .trading_historical_intake import _calendar

SCHEMA_VERSION = "blackpod.shadow_historical_baseline.v1"
METHOD_VERSION = "blackpod.retrospective_reversal_gross_proxy.v1"
MAX_CUTOFF = "2026-03-05"
UNIVERSE = ("QQQ", "SPY")
CSV_FIELDS = ("date", "open", "high", "low", "close", "adj_close", "volume")
CALCULATION_PATHS = ("shadow_historical_baseline.py", "shadow_experiment.py", "contracts/shadow_experiment.py",
    "trading_historical_intake.py", "contracts/historical_intake.py", "contracts/mission_request.py",
    "contracts/trading_accounting.py", "hashing.py")
LIMITATIONS = [
    "RETROSPECTIVE_RECONSTRUCTION_NOT_PROSPECTIVE_PREDICTIONS_OR_PREREGISTRATION",
    "SOURCE_PRICE_ADJUSTMENT_AND_CORPORATE_ACTION_CONTINUITY_UNVERIFIED",
    "YAHOO_PRICE_BASIS_NOT_VERIFIED_COMPARABLE_TO_FULL_SESSION_IEX_PILOT",
    "NO_ADJUSTED_OPEN_RECONSTRUCTION_OR_DIVIDEND_TOTAL_RETURN_CLAIM",
    "HISTORICAL_PUBLICATION_TIMES_AND_REVISIONS_NOT_POINT_IN_TIME_VERIFIED",
    "GROSS_PRICE_PROXY_NOT_EXECUTABLE_RETURN_OR_REALIZED_TRADE_PNL",
    "COSTS_SLIPPAGE_CAPACITY_RISK_AND_ECONOMIC_SUPPORT_UNQUALIFIED",
    "QQQ_SPY_SURVIVOR_UNIVERSE_AND_ADJACENT_SESSIONS_CORRELATED",
    "HISTORICAL_COHORT_DISTRIBUTIONS_NOT_CONFIDENCE_INTERVALS_OR_FORECAST_PROBABILITIES",
    "ORIGINAL_HOLDOUT_AND_PRIOR_QUALIFICATION_GATES_UNCHANGED",
    "CALENDAR_RECEIPT_IS_LOCAL_SOURCE_BINDING_NOT_PROVIDER_AUTHENTICATION",
]


def _context():
    return Context(prec=60, rounding=ROUND_HALF_EVEN)


def _reference(path, raw):
    return {"path": path, "sha256": sha256_bytes(raw), "size_bytes": len(raw)}


def calculation_evidence():
    """Return the exact local calculation dependency bytes for bundle retention."""
    root = Path(__file__).absolute().parent
    return {"implementation/" + path: read_regular(root / path) for path in CALCULATION_PATHS}


def _price(value, name, *, integer=False):
    if not isinstance(value, str) or not value or len(value) > 100 or value != value.strip():
        raise ValueError(name + " must be a bounded source decimal")
    try:
        number = Decimal(value)
    except InvalidOperation:
        raise ValueError(name + " must be a finite source decimal") from None
    if (not number.is_finite() or number < 0 or number > Decimal("1e20")
            or number.as_tuple().exponent < -40 or (not integer and number == 0)):
        raise ValueError(name + " is outside the source decimal range")
    if integer and number != number.to_integral_value():
        raise ValueError(name + " must be a nonnegative integer")
    return _text(number)


def _csv_source(raw, symbol, calendar, cutoff):
    if not isinstance(raw, bytes) or not 0 < len(raw) <= 16 * 1024 * 1024:
        raise ValueError("historical CSV must be bounded nonempty bytes")
    try:
        reader = csv.reader(StringIO(raw.decode("utf-8")), strict=True)
        if tuple(next(reader)) != CSV_FIELDS:
            raise ValueError("historical CSV requires exact date/OHLC/adj_close/volume columns")
        values, prior, first, last, total = {}, None, None, None, 0
        for record in reader:
            total += 1
            if total > 10000 or len(record) != len(CSV_FIELDS):
                raise ValueError("historical CSV rows must be bounded and complete")
            row = dict(zip(CSV_FIELDS, record))
            day = historical_date(row["date"], symbol + ".date")
            if prior is not None and day <= prior:
                raise ValueError("historical CSV dates must be unique and chronological")
            first, last, prior = first or day, day, day
            # Rows beyond the fixed cutoff are retained source evidence only.
            # No post-cutoff price is normalized, selected, or scored.
            if day > cutoff:
                continue
            if day not in calendar:
                raise ValueError("historical source date is absent from retained market calendar")
            normalized = {field: _price(row[field], symbol + "." + field, integer=field == "volume")
                          for field in CSV_FIELDS[1:]}
            low, high = Decimal(normalized["low"]), Decimal(normalized["high"])
            if low > high or any(not low <= Decimal(normalized[field]) <= high for field in ("open", "close")):
                raise ValueError("historical source OHLC relationship is invalid")
            values[day] = normalized
    except (UnicodeError, csv.Error, StopIteration):
        raise ValueError("historical CSV is malformed") from None
    if not values:
        raise ValueError("historical CSV has no source rows before the fixed cutoff")
    return values, {"symbol": symbol, "source_row_count": total, "source_first_date": first,
                    "source_last_date": last, "scored_source_row_count": len(values),
                    "first_scored_source_date": min(values), "last_scored_source_date": max(values),
                    "price_basis": "UNKNOWN", "adjusted_close_used": False}


def _summary(rows):
    paired = [row for row in rows if row["pair_eligible"]]
    candidates = sum(row["status"] == "OBSERVATIONAL_CANDIDATE" for row in rows)
    counts = dict(sorted(Counter(row["status"] for row in rows).items()))
    mean = control = excess = positive = None
    if paired:
        with localcontext(_context()):
            mean = _text(sum(Decimal(row["candidate_gross_return"]) for row in paired) / len(paired))
            control = _text(sum(Decimal(row["control_gross_return"]) for row in paired) / len(paired))
            excess = _text(sum(Decimal(row["excess_over_control"]) for row in paired) / len(paired))
            positive = _text(Decimal(sum(Decimal(row["candidate_gross_return"]) > 0 for row in paired)) / len(paired))
    return {"signal_session_count": len({row["signal_session"] for row in rows}),
        "opportunity_count": len(rows), "status_counts": counts, "candidate_count": candidates,
        "paired_candidate_count": len(paired), "unpaired_candidate_count": candidates - len(paired),
        "abstention_count": counts.get("ABSTAIN_NONNEGATIVE_RETURN", 0),
        "missing_input_count": counts.get("DEFER_MISSING_INPUT", 0) + counts.get("DEFER_INSUFFICIENT_LOOKBACK", 0),
        "source_not_yet_available_count": counts.get("SOURCE_NOT_YET_AVAILABLE", 0),
        "mean_gross_return": mean, "mean_control_gross_return": control,
        "mean_gross_excess_over_control": excess, "positive_gross_outcome_fraction": positive,
        "cash_return": "0" if paired else None, "net_return": None, "realized_trade_pnl": None,
        "sample_policy": "PAIRED_CANDIDATE_OPPORTUNITIES_ONLY_ALL_OTHER_ROWS_RETAINED",
        "economic_support": "NOT_EVALUABLE"}


def _row(index, symbol, dates, bars, cutoff, first_dates):
    day = dates[index]
    current = bars[symbol].get(day)
    prior = None if index == 0 else bars[symbol].get(dates[index - 1])
    row = {"symbol": symbol, "signal_session": day,
        "previous_session": None if index == 0 else dates[index - 1],
        "entry_session": dates[index + 1] if index + 1 < len(dates) else None,
        "exit_session": dates[index + 2] if index + 2 < len(dates) else None,
        "status": "DEFER_MISSING_INPUT", "reason_codes": ["MISSING_ADJACENT_CALENDAR_CLOSE_INPUT"],
        "signal_return": None, "signal_close": None, "previous_close": None,
        "candidate_gross_return": None, "control_gross_return": None, "cash_return": None,
        "excess_over_control": None, "entry_price": None, "exit_price": None, "pair_eligible": False}
    if day < first_dates[symbol]:
        row.update(status="SOURCE_NOT_YET_AVAILABLE", reason_codes=["BEFORE_FIRST_RETAINED_SYMBOL_SOURCE_DATE"])
    elif index == 0:
        row.update(status="DEFER_INSUFFICIENT_LOOKBACK", reason_codes=["PREVIOUS_MARKET_SESSION_OUTSIDE_RETAINED_CALENDAR"])
    elif current is not None and prior is not None:
        row.update(signal_return=_ratio(current["close"], prior["close"]),
                   signal_close=current["close"], previous_close=prior["close"])
        if Decimal(current["close"]) >= Decimal(prior["close"]):
            row.update(status="ABSTAIN_NONNEGATIVE_RETURN", reason_codes=["FROZEN_NEGATIVE_CLOSE_CONDITION_NOT_MET"])
        else:
            row.update(status="OBSERVATIONAL_CANDIDATE", reason_codes=["NEGATIVE_RETAINED_PROVIDER_CLOSE_RETURN"])
            entry, exit_ = row["entry_session"], row["exit_session"]
            if entry is None or exit_ is None or exit_ > cutoff:
                row["reason_codes"].append("OUTCOME_OUTSIDE_FIXED_PRE_HOLDOUT_CUTOFF")
            else:
                if all(day_ in bars[symbol] for day_ in (entry, exit_)):
                    row["entry_price"], row["exit_price"] = (bars[symbol][day_]["open"] for day_ in (entry, exit_))
                    row["candidate_gross_return"] = _ratio(row["exit_price"], row["entry_price"])
                if all(day_ in bars[other] for other in UNIVERSE for day_ in (entry, exit_)):
                    with localcontext(_context()):
                        control = sum(Decimal(_ratio(bars[other][exit_]["open"], bars[other][entry]["open"])) for other in UNIVERSE) / 2
                        row.update(control_gross_return=_text(control), cash_return="0", pair_eligible=True,
                            excess_over_control=_text(Decimal(row["candidate_gross_return"]) - control))
                else:
                    row["reason_codes"].append("MISSING_IDENTICAL_DATE_CANDIDATE_OR_CONTROL_OPEN")
    return row


def _cohorts(rows, dates, bars):
    anchor = next((index for index in range(1, len(dates))
                   if all(day in bars[symbol] for symbol in UNIVERSE for day in dates[index - 1:index + 1])), None)
    if anchor is None:
        return [], None
    by_date = {day: [] for day in dates}
    for row in rows:
        by_date[row["signal_session"]].append(row)
    cohorts = []
    for start in range(anchor, len(dates), 30):
        window = dates[start:start + 30]
        summary = _summary([row for day in window for row in by_date[day]])
        if len(window) != 30:
            conclusion = "INCONCLUSIVE_INCOMPLETE_COHORT"
        elif summary["missing_input_count"] or summary["source_not_yet_available_count"] or summary["unpaired_candidate_count"]:
            conclusion = "INCONCLUSIVE_MISSING_EVIDENCE"
        elif summary["paired_candidate_count"] < CRITERIA["minimum_observed_candidates"]:
            conclusion = "INCONCLUSIVE_TOO_FEW_CANDIDATES"
        elif Decimal(summary["mean_gross_return"]) > 0 and Decimal(summary["mean_gross_excess_over_control"]) > 0:
            conclusion = "DESCRIPTIVE_POSITIVE_PROXY_ONLY"
        else:
            conclusion = "DESCRIPTIVE_NONPOSITIVE_PROXY"
        cohorts.append({"cohort_index": len(cohorts) + 1, "first_signal_session": window[0],
                        "last_signal_session": window[-1], "conclusion": conclusion, **summary})
    return cohorts, dates[anchor]


def _cohort_summary(cohorts):
    comparable = [row for row in cohorts if row["conclusion"].startswith("DESCRIPTIVE_")]
    quantiles = {}
    for field in ("mean_gross_return", "mean_gross_excess_over_control", "paired_candidate_count"):
        values = sorted(Decimal(str(row[field])) for row in comparable)
        quantiles[field] = {"p" + str(percentile): None if not values else _text(values[max(0, (len(values) * percentile + 99) // 100 - 1)])
                            for percentile in (10, 50, 90)}
    return {"cohort_count": len(cohorts), "conclusion_counts": dict(sorted(Counter(row["conclusion"] for row in cohorts).items())),
        "distribution_cohort_count": len(comparable), "quantile_method": "EMPIRICAL_NEAREST_RANK",
        "distribution_population": "COMPLETE_30_SESSION_COHORTS_NO_MISSING_EVIDENCE_AT_LEAST_12_PAIRED_CANDIDATES",
        "interpretation": "HISTORICAL_DESCRIPTION_NOT_CONFIDENCE_INTERVAL_OR_PREDICTIVE_PROBABILITY",
        "quantiles": quantiles}


def build_historical_baseline(protocol, source_blobs, *, calendar_raw, calendar_receipt_raw,
                              source_manifest, cutoff=MAX_CUTOFF):
    """Return a deterministic report, every opportunity, and fixed 30-day blocks.

    Callers own immutable publication. Source manifest provenance is retained as
    supplied metadata; hash matching never upgrades its economic qualifications.
    No input or source file is modified and no provider is contacted.
    """
    cutoff = historical_date(cutoff, "historical cutoff")
    if cutoff > MAX_CUTOFF:
        raise ValueError("historical baseline cannot score the original withheld holdout")
    protocol = ShadowExperimentProtocol.from_mapping(protocol).to_dict()
    if not isinstance(source_blobs, dict) or set(source_blobs) != set(UNIVERSE):
        raise ValueError("historical baseline requires exactly QQQ and SPY source bytes")
    manifest = deepcopy(source_manifest)
    if not isinstance(manifest, dict) or not isinstance(manifest.get("sources"), dict) or set(manifest["sources"]) != set(UNIVERSE):
        raise ValueError("source manifest requires exactly QQQ and SPY identities")
    manifest_raw = canonical_json_bytes(manifest)
    for symbol in UNIVERSE:
        reference, raw = manifest["sources"][symbol], source_blobs[symbol]
        if (not isinstance(reference, dict) or not isinstance(raw, bytes)
                or type(reference.get("size_bytes")) is not int or reference["size_bytes"] != len(raw)
                or reference.get("sha256") != sha256_bytes(raw)):
            raise ValueError("historical source differs from its exact manifest hash or size")
    receipt = validate_historical_capture(parse_strict_json_object_bytes(calendar_receipt_raw), "calendar")
    if receipt["body_sha256"] != sha256_bytes(calendar_raw) or receipt["size_bytes"] != len(calendar_raw):
        raise ValueError("historical calendar receipt differs from retained source bytes")
    if not receipt["query"]["start"] <= "1998-01-01" or receipt["query"]["end"] < cutoff:
        raise ValueError("historical calendar request must cover 1998 through the fixed cutoff")
    calendar = _calendar(calendar_raw, receipt)
    dates = sorted(day for day in calendar if "1998-01-01" <= day <= cutoff)
    if len(dates) < 3:
        raise ValueError("historical baseline requires at least three returned market sessions")
    calendar = {day: calendar[day] for day in dates}
    bars, coverage = {}, []
    for symbol in UNIVERSE:
        bars[symbol], inventory = _csv_source(source_blobs[symbol], symbol, calendar, cutoff)
        coverage.append(inventory)
    first_dates = {symbol: min(bars[symbol]) for symbol in UNIVERSE}
    rows = [_row(index, symbol, dates, bars, cutoff, first_dates) for index in range(len(dates)) for symbol in UNIVERSE]
    cohorts, anchor = _cohorts(rows, dates, bars)
    report = {"schema_version": SCHEMA_VERSION, "method_version": METHOD_VERSION,
        "scope": "RETROSPECTIVE_RECONSTRUCTION_GROSS_PRICE_PROXY_ONLY", "cutoff": cutoff,
        "protocol_sha256": sha256_bytes(canonical_json_bytes(protocol)),
        "hypothesis_sha256": protocol["hypothesis_evidence"]["sha256"],
        "source_manifest_sha256": sha256_bytes(manifest_raw), "source_manifest": manifest,
        "calendar_evidence": _reference("sources/calendar.json", calendar_raw),
        "calendar_receipt_evidence": _reference("sources/calendar.receipt.json", calendar_receipt_raw),
        "source_coverage": coverage, "first_signal_session": dates[0], "last_signal_session": dates[-1],
        "cohort_anchor": anchor, "fixed_criteria": deepcopy(CRITERIA),
        "summary": _summary(rows),
        "per_symbol": [{"symbol": symbol, **_summary([row for row in rows if row["symbol"] == symbol])} for symbol in UNIVERSE],
        "per_year": [{"year": year, **_summary([row for row in rows if row["signal_session"][:4] == year])}
                     for year in sorted({day[:4] for day in dates})],
        "cohort_summary": _cohort_summary(cohorts),
        "rows_evidence": _reference("rows.json", canonical_json_bytes(rows)),
        "cohorts_evidence": _reference("cohorts.json", canonical_json_bytes(cohorts)),
        "calculation_sources": [_reference(path, raw) for path, raw in calculation_evidence().items()],
        "historical_availability_assumption": "COMPLETED_DAILY_CLOSE_BEFORE_NEXT_SESSION_RECONSTRUCTED_NOT_VERIFIED",
        "auto_trading_enabled": False, "authority": dict(AUTHORITY), "execution_status": "NOT_EXECUTED",
        "net_return": None, "realized_trade_pnl": None, "economic_support": "NOT_EVALUABLE", "limitations": list(LIMITATIONS)}
    report["report_id"] = "shadow-historical-baseline-" + sha256_bytes(canonical_json_bytes(report))
    return {"report": report, "rows": rows, "cohorts": cohorts}
