"""Deterministic, source-bound two-desk research and PAPER test proposals.

This pure module accepts retained evidence and a verified journal prefix. It
does not read credentials, import the native application, install ownership,
activate a budget, or place an order. Native attention and Senate discussion
remain descriptive evidence; the functional pilot is not a return forecast.
"""
from __future__ import annotations

from datetime import date, timedelta
from decimal import Context, Decimal, ROUND_DOWN, localcontext
import re
from .contracts.desk_candidate_review import DeskReviewInput, DESK_REVIEW_METHOD_VERSION, DESK_REVIEW_LIMITATIONS
from .contracts.decision_journal import JournalEvent
from .contracts.mission_request import parse_rfc3339, parse_strict_json_object_bytes
from .contracts.paper_test_budget import PaperTestBudget
from .contracts.trading_accounting import accounting_decimal
from .contracts.trading_reconciliation import symbol_text
from .hashing import canonical_json_bytes, sha256_bytes
from .paper_test_budget import validate_budget_source

REVIEW_EVENT_TYPE = "SHADOW_DESK_REVIEW_RECORDED"
REVIEW_SOURCE_KIND = "SHADOW_DESK_REVIEW"
REVIEW_EVIDENCE_PATH = "shadow-desk/review.json"
ZERO = Decimal("0")
LIMITATIONS = DESK_REVIEW_LIMITATIONS


class DeskCandidateReviewError(ValueError):
    """Retained research evidence or an immutable relationship cannot replay."""


def _text(value):
    if value is None:
        return None
    if value == ZERO:
        return "0"
    text = format(value, "f")
    return text.rstrip("0").rstrip(".") if "." in text else text


def _number(value, name, *, positive=False, nonnegative=False):
    # Provider JSON uses finite numbers; their literal decimal representation
    # is retained in the original bytes. Calculations never use float algebra.
    if type(value) not in (str, int, float):
        raise DeskCandidateReviewError(name + " must be a numeric observation")
    try:
        return Decimal(accounting_decimal(str(value), name, positive=positive, nonnegative=nonnegative))
    except ValueError as exc:
        raise DeskCandidateReviewError(name + " is not a bounded numeric observation") from exc


def _timestamp(value, name):
    # Alpaca timestamps may carry nanoseconds. Preserve those source bytes and
    # compare at supported microsecond precision, as the other passive imports.
    if not isinstance(value, str):
        raise DeskCandidateReviewError(name + " must be a timestamp")
    try:
        comparable = re.sub(r"(\.\d{6})\d{1,3}(?=Z$|[+-]\d{2}:\d{2}$)", r"\1", value)
        return parse_rfc3339(comparable, name)
    except ValueError as exc:
        raise DeskCandidateReviewError(name + " is not a valid timestamp") from exc


def _blob(blobs, reference):
    raw = blobs.get(reference["sha256"])
    if not isinstance(raw, bytes) or sha256_bytes(raw) != reference["sha256"] or len(raw) != reference["size_bytes"]:
        raise DeskCandidateReviewError("retained desk review evidence is missing or differs in hash/size")
    return raw


def _json(blobs, reference):
    try:
        return parse_strict_json_object_bytes(_blob(blobs, reference))
    except ValueError as exc:
        raise DeskCandidateReviewError("retained desk evidence must be strict JSON") from exc


def _identity(prefix, value):
    return prefix + "-" + sha256_bytes(canonical_json_bytes(value))


def _retry_prefix(document, events):
    for index, event in enumerate(events):
        if event.event_type == REVIEW_EVENT_TYPE and event.payload["review"]["review_id"] == document.review_id:
            if canonical_json_bytes(event.payload["review"]) != document.to_bytes():
                raise DeskCandidateReviewError("desk review identity conflicts with changed input bytes")
            return events[:index]
    return events


def calculate_symbol_metrics(snapshot, bars, *, captured_at):
    """Decimal OHLC/quote measures; ATR is the mean of the last 14 true ranges.

    Daily bars must be distinct, ordered, completed observations. IEX dollar
    volume describes this supplied feed and is not consolidated market volume.
    Insufficient history produces explicit null measures, not fabricated data.
    """
    if not isinstance(snapshot, dict) or not isinstance(bars, list) or len(bars) > 10000:
        raise DeskCandidateReviewError("snapshot and bounded daily bar list are required")
    cutoff = _timestamp(captured_at, "captured_at")
    quote, trade = snapshot.get("latestQuote"), snapshot.get("latestTrade")
    if not isinstance(quote, dict) or not isinstance(trade, dict):
        raise DeskCandidateReviewError("latest quote and trade are required")
    bid, ask = _number(quote.get("bp"), "bid", nonnegative=True), _number(quote.get("ap"), "ask", nonnegative=True)
    last = _number(trade.get("p"), "last", positive=True)
    for row in (quote, trade):
        if _timestamp(row.get("t"), "market timestamp") > cutoff:
            raise DeskCandidateReviewError("market observation postdates capture")
    parsed, previous = [], None
    for row in bars:
        if not isinstance(row, dict):
            raise DeskCandidateReviewError("daily bar must be an object")
        stamp = _timestamp(row.get("t"), "daily bar timestamp")
        if stamp > cutoff or previous is not None and stamp <= previous:
            raise DeskCandidateReviewError("daily bars must be strictly ordered and precede capture")
        previous = stamp
        values = {field: _number(row.get(key), "daily bar " + field, positive=field != "volume", nonnegative=field == "volume")
                  for field, key in (("open", "o"), ("high", "h"), ("low", "l"), ("close", "c"), ("volume", "v"))}
        if values["low"] > min(values["open"], values["close"]) or values["high"] < max(values["open"], values["close"]) or values["low"] > values["high"]:
            raise DeskCandidateReviewError("daily bar OHLC relationship is invalid")
        # The packet has no exchange close/corporate-action attestation. Match
        # the Spyglass replay's conservative exclusion of unproven same-day
        # daily bars, while retaining every original source observation.
        if stamp.date() >= cutoff.date():
            continue
        parsed.append(values)
    with localcontext(Context(prec=64)):
        closes = [row["close"] for row in parsed]
        ranges = [max(row["high"] - row["low"], abs(row["high"] - closes[index - 1]), abs(row["low"] - closes[index - 1]))
                  for index, row in enumerate(parsed) if index]
        atr = sum(ranges[-14:], ZERO) / 14 if len(ranges) >= 14 else None
        sma20 = sum(closes[-20:], ZERO) / 20 if len(closes) >= 20 else None
        sma50 = sum(closes[-50:], ZERO) / 50 if len(closes) >= 50 else None
        ret20 = (closes[-1] / closes[-21] - 1) * 100 if len(closes) >= 21 else None
        ret60 = (closes[-1] / closes[-61] - 1) * 100 if len(closes) >= 61 else None
        avg_volume = sum((row["close"] * row["volume"] for row in parsed[-20:]), ZERO) / 20 if len(parsed) >= 20 else None
        daily = snapshot.get("dailyBar") or {}
        high = _number(daily.get("h"), "snapshot daily high", positive=True) if daily.get("h") is not None else None
        low = _number(daily.get("l"), "snapshot daily low", positive=True) if daily.get("l") is not None else None
        if high is not None and low is not None and high < low:
            raise DeskCandidateReviewError("snapshot daily high is below low")
        result = {"last": last, "bid": bid, "ask": ask,
                  "spread_pct": ((ask - bid) / ((ask + bid) / 2) * 100) if bid > 0 and ask >= bid else None,
                  "atr14": atr, "sma20": sma20, "sma50": sma50, "return20_pct": ret20, "return60_pct": ret60,
                  "range_pct": (high - low) / last * 100 if high is not None and low is not None else None,
                  "iex_average_dollar_volume20": avg_volume}
        return {key: _text(value) for key, value in result.items()}


def _source_references(packet):
    refs = packet.get("source_evidence", [])
    if isinstance(refs, dict):
        refs = [reference for reference in refs.values() if reference is not None]
    if not isinstance(refs, list):
        raise DeskCandidateReviewError("packet source_evidence must contain explicit retained references")
    from .contracts.trading_reconciliation import evidence_reference
    return [evidence_reference(reference) for reference in refs]


def _context(document, events, blobs):
    budget = PaperTestBudget.from_bytes(_blob(blobs, document.budget["proposal_evidence"]))
    validate_budget_source(budget, events)
    if budget.account_id != document.account_id or budget.mode != document.mode:
        raise DeskCandidateReviewError("desk budget belongs to a different account or mode")
    if (budget.basis["snapshot_event_id"] != document.budget["source_snapshot_event_id"]
            or budget.basis["snapshot_sha256"] != document.budget["source_snapshot_sha256"]):
        raise DeskCandidateReviewError("review budget snapshot binding differs")
    if _timestamp(budget.recorded_at, "budget timestamp") > _timestamp(document.recorded_at, "review timestamp"):
        raise DeskCandidateReviewError("budget was recorded after review")
    market = _json(blobs, document.sources["market_evidence"])
    analysis = _json(blobs, document.sources["analysis_evidence"])
    issuer = _json(blobs, document.sources["issuer_evidence"])
    if (market.get("schema_version") != "blackpod.shadow_market_packet.v1" or market.get("feed") != "IEX"
            or market.get("adjustment") != "RAW"):
        raise DeskCandidateReviewError("desk market packet must declare the IEX raw observation contract")
    if _timestamp(market.get("captured_at"), "market capture") > _timestamp(document.recorded_at, "review recorded_at"):
        raise DeskCandidateReviewError("market capture postdates review")
    if issuer.get("schema_version") != "blackpod.shadow_issuer_facts.v1":
        raise DeskCandidateReviewError("unsupported issuer facts packet")
    if _timestamp(issuer.get("captured_at"), "issuer capture") > _timestamp(document.recorded_at, "review recorded_at"):
        raise DeskCandidateReviewError("issuer capture postdates review")
    from .desk_review_sources import validate_market_packet, validate_issuer_packet
    validate_market_packet(market, blobs)
    validate_issuer_packet(issuer, blobs)
    from .shadow_native_analysis import validate_native_analysis
    # The native adapter replays retained, explicitly allowlisted source ASTs;
    # it does not load or invoke the application or a provider.
    if analysis.get("schema_version") == "blackpod.shadow_analysis_bundle.v1":
        if set(analysis) != {"schema_version", "native", "galactica", "source_evidence"}:
            raise DeskCandidateReviewError("shadow analysis bundle fields differ from the supported contract")
        validate_native_analysis(analysis["native"], market, blobs)
        from .shadow_galactica_analysis import validate_shadow_galactica_analysis
        validate_shadow_galactica_analysis(analysis["galactica"], market, blobs)
        if _timestamp(analysis["galactica"].get("generated_at"), "Galactica analysis generated_at") > _timestamp(document.recorded_at, "review recorded_at"):
            raise DeskCandidateReviewError("Galactica analysis postdates review")
        merged = _source_references(analysis["native"]) + _source_references(analysis["galactica"])
        expected = {reference["path"]: reference for reference in merged}
        retained = {reference["path"]: reference for reference in _source_references(analysis)}
        if len(expected) != len(merged) or retained != expected:
            raise DeskCandidateReviewError("shadow analysis bundle must retain the exact distinct code and advisor evidence union")
    else:
        validate_native_analysis(analysis, market, blobs)
    evidence = {document.budget["proposal_evidence"]["path"]: _blob(blobs, document.budget["proposal_evidence"])}
    for reference in document.sources.values():
        evidence[reference["path"]] = _blob(blobs, reference)
    for packet in (market, analysis, issuer):
        for reference in _source_references(packet):
            raw = _blob(blobs, reference)
            if reference["path"] in evidence and evidence[reference["path"]] != raw:
                raise DeskCandidateReviewError("desk source evidence paths collide")
            evidence[reference["path"]] = raw
    if REVIEW_EVIDENCE_PATH in evidence:
        raise DeskCandidateReviewError("source path collides with desk review input")
    return budget, market, analysis, issuer, evidence


def _floor(value):
    return int(value.to_integral_value(rounding=ROUND_DOWN))


def _plan(document, candidates, trading_budget, investment_budget):
    policy = document.policy
    max_entry = (trading_budget * Decimal(policy["max_entry_fraction"])).quantize(Decimal("0.01"), rounding=ROUND_DOWN)
    scenario_budget = (trading_budget * Decimal(policy["scenario_risk_fraction"])).quantize(Decimal("0.01"), rounding=ROUND_DOWN)
    available = [row for row in candidates if row["category"] == "TRADING_PILOT"]
    trading = {"status": "DEFER", "symbol": None, "qty": 0, "max_entry_notional_usd": _text(max_entry),
        "buffered_price_usd": None, "estimated_notional_usd": "0", "total_round_trip_notional_usd": "0",
        "stop_distance_usd": None, "scenario_loss_usd": None, "maximum_completed_cycles": 1,
        "max_active_entries": 1, "time_exit_minutes": 30, "expiry": policy["expires_at"],
        "authorization_required": True, "purpose": "EXECUTION_AND_ACCOUNTING_TEST", "return_expectation": None}
    chosen = None
    for row in available:
        metrics = row["metrics"]
        price = Decimal(metrics["ask"]) * (1 + Decimal(policy["price_buffer_fraction"]))
        distance = Decimal(metrics["atr14"]) * Decimal(policy["atr_multiple"])
        qty = min(_floor(max_entry / price), _floor(scenario_budget / distance)) if 0 < distance < price else 0
        if qty:
            chosen = row["symbol"]
            notional = price * qty
            trading.update({"status": "CONDITIONAL_FUNCTIONAL_PILOT", "symbol": chosen, "qty": qty,
                "buffered_price_usd": _text(price), "estimated_notional_usd": _text(notional),
                "total_round_trip_notional_usd": _text(notional * 2), "stop_distance_usd": _text(distance),
                "scenario_loss_usd": _text(distance * qty)})
            break
    investment = []
    cap = (investment_budget * Decimal(policy["investment_candidate_fraction"])).quantize(Decimal("0.01"), rounding=ROUND_DOWN)
    remaining = investment_budget
    for row in candidates:
        if row["category"] != "INVESTMENT_RESEARCH" or row["symbol"] == chosen or len(investment) >= 3:
            continue
        price = Decimal(row["metrics"]["ask"]) * (1 + Decimal(policy["price_buffer_fraction"]))
        qty = _floor(min(cap, remaining) / price)
        if qty <= 0:
            continue
        cost = price * qty
        remaining -= cost
        symbol, benchmark = row["symbol"], policy["benchmark_symbol"]
        investment.append({"symbol": symbol, "qty": qty, "buffered_price_usd": _text(price), "estimated_notional_usd": _text(cost),
            "hypothesis": (f"Proposed research hypothesis: over {policy['investment_horizon_days']} days, retain and evaluate {symbol}'s "
                f"mandate exposure and total-return/drawdown observations against {benchmark}; economic outperformance is not established."),
            "invalidation_conditions": ["Fund mandate or structure changes", "Unaccounted split, distribution, or other corporate action",
                "Independent economic and fundamental evidence fails to support a thesis before authorization"],
            "expected_return": None})
    inv_plan = {"status": "RESEARCH_ONLY", "horizon_days": policy["investment_horizon_days"], "candidates": investment,
                "total_notional_usd": _text(investment_budget - remaining), "cash_reserve_usd": _text(remaining), "allocation_authorized": False}
    return trading, inv_plan


def _issuer_facts(packet, captured_at):
    facts = packet.get("facts")
    if not isinstance(facts, list) or len(facts) > 256:
        raise DeskCandidateReviewError("issuer facts must be a bounded array")
    result = {}
    for row in facts:
        if not isinstance(row, dict):
            raise DeskCandidateReviewError("issuer fact must be an object")
        symbol = symbol_text(row.get("symbol"))
        if symbol in result:
            raise DeskCandidateReviewError("issuer facts must have unique symbols")
        for field in ("fund_name", "issuer", "mandate", "structure", "asset_class", "source_url", "as_of"):
            if not isinstance(row.get(field), str) or not row[field].strip() or len(row[field]) > 10000:
                raise DeskCandidateReviewError("issuer " + field + " must be a bounded nonempty string")
        if not row["source_url"].startswith("https://"):
            raise DeskCandidateReviewError("issuer source must identify an HTTPS source")
        if type(row.get("corporate_action_before_horizon")) is not bool:
            raise DeskCandidateReviewError("issuer corporate action flag must be explicit")
        cutoff = _timestamp(captured_at, "issuer capture cutoff")
        try:
            if len(row["as_of"]) == 10:
                if date.fromisoformat(row["as_of"]) > cutoff.date():
                    raise DeskCandidateReviewError("issuer fact postdates capture")
            elif _timestamp(row["as_of"], "issuer as_of") > cutoff:
                raise DeskCandidateReviewError("issuer fact postdates capture")
        except ValueError as exc:
            raise DeskCandidateReviewError("issuer as_of must be a valid prior date or timestamp") from exc
        result[symbol] = row
    return result


def _compute(document, budget, market, analysis, issuer):
    from .shadow_native_analysis import native_symbol_states
    snapshots, dailybars = market.get("snapshots"), market.get("bars")
    if not isinstance(snapshots, dict) or not snapshots or len(snapshots) > 256 or not isinstance(dailybars, dict):
        raise DeskCandidateReviewError("market packet requires a bounded nonempty symbol universe")
    if set(snapshots) != set(dailybars):
        raise DeskCandidateReviewError("snapshot and daily bar universes differ")
    facts = _issuer_facts(issuer, market["captured_at"])
    if set(facts) - set(snapshots):
        raise DeskCandidateReviewError("issuer fact symbol is outside market universe")
    native_analysis = analysis.get("native", analysis)
    galactica = analysis.get("galactica")
    native_states = native_symbol_states(native_analysis)
    outputs = native_analysis["outputs"]
    native_candidates = {row["symbol"]: row for row in outputs["trading_candidate_report"]["candidates"]}
    candidates, categories = [], {"TRADING_PILOT": [], "INVESTMENT_RESEARCH": [], "DEFER": [], "EXCLUDE": []}
    cutoff = _timestamp(market["captured_at"], "market capture")
    reasons = {"AUTOMATION_REMAINS_OFF", "PROPOSED_OWNERSHIP_AND_LIMITS_REQUIRE_HUMAN_AUTHORIZATION",
               "INDEPENDENT_ECONOMIC_AND_FUNDAMENTAL_EVIDENCE_MISSING", "EXPECTED_RETURNS_NOT_ESTIMATED",
               "QUOTE_REFRESH_AND_REGULAR_SESSION_CHECK_REQUIRED_BEFORE_ANY_TEST", "US_EQUITY_AND_TECH_CORRELATION_REQUIRES_REVIEW"}
    if galactica is None:
        reasons.add("SPYGLASS_AND_BRIGADE_EVIDENCE_NOT_INCLUDED")
    elif galactica["brigade"]["status"] == "HISTORICAL_INPUT_ONLY":
        reasons.add("BRIGADE_HISTORICAL_OPINIONS_ARE_CONTEXT_ONLY_NOT_CURRENT_VOTES")
    else:
        reasons.add("BRIGADE_CURRENT_FORECASTS_UNAVAILABLE_INFERENCE_NOT_RUN")
    for symbol in sorted(snapshots):
        symbol_text(symbol)
        metrics = calculate_symbol_metrics(snapshots[symbol], dailybars[symbol], captured_at=market["captured_at"])
        contribution = native_states.get(symbol, {"candidate_state": None, "senate_disposition": None})
        confidence = native_candidates.get(symbol, {}).get("confidence")
        native = {"candidate_state": contribution.get("candidate_state"), "senate_disposition": contribution.get("senate_disposition"),
                  "confidence_label": None if confidence is None else str(confidence) + " (heuristic, not probability)"}
        category, why = "DEFER", []
        fact = facts.get(symbol)
        complete = all(metrics[field] is not None for field in ("spread_pct", "atr14", "sma50", "return60_pct", "iex_average_dollar_volume20"))
        positive_quotes = Decimal(metrics["bid"]) > 0 and Decimal(metrics["ask"]) > 0
        quote_age = cutoff - _timestamp(snapshots[symbol]["latestQuote"]["t"], "quote timestamp")
        trade_age = cutoff - _timestamp(snapshots[symbol]["latestTrade"]["t"], "trade timestamp")
        completed_bars = [row for row in dailybars[symbol] if _timestamp(row["t"], "daily bar cutoff").date() < cutoff.date()]
        history_age = cutoff - _timestamp(completed_bars[-1]["t"], "daily bar cutoff") if completed_bars else timedelta(days=10000)
        review_age = _timestamp(document.recorded_at, "review recorded_at") - cutoff
        # These are conservative proposal filters, not changes to native rules.
        usable = (complete and positive_quotes and Decimal(metrics["atr14"] or "0") > 0
                  and Decimal(metrics["spread_pct"] or "100") <= Decimal("0.50")
                  and Decimal(metrics["iex_average_dollar_volume20"] or "0") >= Decimal("100000")
                  and quote_age <= timedelta(hours=24) and trade_age <= timedelta(hours=24)
                  and history_age <= timedelta(days=5) and review_age <= timedelta(hours=24))
        if symbol == "VXZ" or fact is not None and fact["structure"] != "ETF":
            category, why = "EXCLUDE", ["ETN_OR_NON_ETF_STRUCTURE_OUTSIDE_INITIAL_ACCOUNTING_SCOPE"]
        elif fact is not None and fact["corporate_action_before_horizon"]:
            category, why = "EXCLUDE", ["KNOWN_CORPORATE_ACTION_INSIDE_PROPOSED_HORIZON"]
        elif not usable:
            why = ["INSUFFICIENT_HISTORY_QUOTES_OR_FEED_LIQUIDITY_FOR_PROPOSED_SIZE"]
        elif fact is not None:
            category, why = "INVESTMENT_RESEARCH", ["RETAINED_ISSUER_MANDATE_FOR_RESEARCH_ONLY", "INDEPENDENT_THESIS_NOT_YET_ESTABLISHED"]
        elif native["candidate_state"] == "REJECT" or native["senate_disposition"] in {"BLOCKED", "UNFAVORABLE"}:
            why = ["NATIVE_PASSIVE_REVIEW_BLOCKED_OR_UNFAVORABLE"]
        else:
            category, why = "TRADING_PILOT", ["HISTORY_SPREAD_AND_FEED_ACTIVITY_SUPPORT_FUNCTIONAL_TEST", "NO_ECONOMIC_TRADE_AUTHORIZATION"]
        if galactica is not None:
            from .shadow_galactica_analysis import symbol_challenges, symbol_gate
            why.extend(symbol_challenges(galactica).get(symbol, []))
            if category == "TRADING_PILOT":
                gate = symbol_gate(galactica, symbol, metrics["ask"], _text(Decimal(metrics["atr14"]) * Decimal(document.policy["atr_multiple"])))
                if gate["blocking_reason_codes"]:
                    category = "DEFER"
                    why.extend(gate["blocking_reason_codes"])
        why = sorted(set(why))
        row = {"symbol": symbol, "category": category, "rank": None, "metrics": metrics, "native": native, "reason_codes": why}
        categories[category].append(row)
    # Prioritize native attention; use observed spread and feed dollar volume to
    # choose an operational pilot, not historical return as a promised outcome.
    native_priority = {"REVIEW": 0, "WATCH": 1, "OBSERVE": 2, "REJECT": 3, None: 4}
    categories["TRADING_PILOT"].sort(key=lambda row: (native_priority[row["native"]["candidate_state"]],
        Decimal(row["metrics"]["spread_pct"]), -Decimal(row["metrics"]["iex_average_dollar_volume20"]), row["symbol"]))
    # A broad core then lower-volatility mandate is a research ordering. The
    # mandate alone supplies no independent fundamental investment evidence.
    asset_order = {"BROAD_EQUITY": 0, "LOW_VOL_EQUITY": 1, "FACTOR_EQUITY": 2}
    categories["INVESTMENT_RESEARCH"].sort(key=lambda row: (asset_order.get(facts[row["symbol"]]["asset_class"], 3), row["symbol"]))
    for category in ("TRADING_PILOT", "INVESTMENT_RESEARCH", "DEFER", "EXCLUDE"):
        for index, row in enumerate(categories[category], 1):
            row["rank"] = index if category in {"TRADING_PILOT", "INVESTMENT_RESEARCH"} else None
            candidates.append(row)
    trading, investment = _plan(document, candidates, Decimal(budget.desk_budgets_usd["TRADING"]), Decimal(budget.desk_budgets_usd["INVESTMENT"]))
    if not any(row["native"]["candidate_state"] == "REVIEW" and row["native"]["senate_disposition"] == "FAVORABLE" for row in candidates):
        reasons.add("ECONOMIC_TRADE_DEFERRED_NO_NATIVE_REVIEW_AND_FAVORABLE_DISCUSSION")
    if trading["symbol"] is None:
        reasons.add("FUNCTIONAL_PILOT_DEFERRED_NO_SUITABLE_WHOLE_SHARE_SIZE")
    report = outputs["trading_candidate_report"]
    deliberation = outputs["senate_deliberation"]
    result = {"status": "SHADOW_REVIEW_ONLY", "method_version": DESK_REVIEW_METHOD_VERSION, "account_id": document.account_id,
        "budget_source_snapshot_event_id": document.budget["source_snapshot_event_id"], "budgets_usd": budget.desk_budgets_usd,
        "market_as_of": market["captured_at"], "native_summary": {"oracle_state": outputs["oracle_report"].get("risk_regime_posture") or None,
            "candidate_counts": {state: sum(row["candidate_state"] == state for row in report["candidates"]) for state in ("REVIEW", "WATCH", "OBSERVE", "REJECT")},
            "senate_counts": {state: sum(row["deliberation_state"] == state for row in deliberation["items"]) for state in ("FAVORABLE", "MONITOR", "HOLD", "UNFAVORABLE", "BLOCKED")},
            "independent_evidence": False}, "candidates": candidates, "trading_plan": trading, "investment_plan": investment,
        "ownership_proposal": {"TRADING": [] if trading["symbol"] is None else [trading["symbol"]],
            "INVESTMENT": [row["symbol"] for row in investment["candidates"]], "status": "PROPOSED_NOT_INSTALLED"},
        "readiness": False, "auto_trading_enabled": False, "realized_trade_pnl": None, "authority": document.authority,
        "reason_codes": sorted(reasons), "limitations": list(LIMITATIONS)}
    from .contracts.desk_candidate_review import validate_review_result
    return validate_review_result(result, document)


def assess_desk_review(document: DeskReviewInput, events=(), blobs=None):
    events = _retry_prefix(document, events)
    with localcontext(Context(prec=64)):
        budget, market, analysis, issuer, _ = _context(document, events, blobs or {})
        return _compute(document, budget, market, analysis, issuer)


def evidence_for_desk_review(document: DeskReviewInput, events=(), blobs=None):
    events = _retry_prefix(document, events)
    *_, evidence = _context(document, events, blobs or {})
    return {REVIEW_EVIDENCE_PATH: document.to_bytes(), **evidence}


def build_desk_review_event(document: DeskReviewInput, events=(), blobs=None):
    events = _retry_prefix(document, events)
    evidence = evidence_for_desk_review(document, events, blobs)
    decision_id = _identity("journal-decision", {"kind": REVIEW_SOURCE_KIND, "account_id": document.account_id, "mode": document.mode})
    return JournalEvent.from_mapping({"schema_version": "blackpod.decision_journal_event.v8",
        "event_id": _identity("journal-event", {"decision_id": decision_id, "event_type": REVIEW_EVENT_TYPE, "review_id": document.review_id}),
        "decision_id": decision_id, "domain": "CAPITAL_ALLOCATION", "event_type": REVIEW_EVENT_TYPE, "recorded_at": document.recorded_at,
        "source": {"kind": REVIEW_SOURCE_KIND, "review_id": document.review_id, "source_sha256": sha256_bytes(document.to_bytes())},
        "evidence": [{"path": path, "sha256": sha256_bytes(raw), "size_bytes": len(raw)} for path, raw in sorted(evidence.items())],
        "payload": {"review": document.to_dict(), "result": assess_desk_review(document, events, blobs)}})


def validate_desk_review_event(event, previous_events, blobs):
    if event.event_type != REVIEW_EVENT_TYPE:
        raise DeskCandidateReviewError("unsupported desk review event")
    document = DeskReviewInput.from_mapping(event.payload["review"])
    if build_desk_review_event(document, previous_events, blobs).to_bytes() != event.to_bytes():
        raise DeskCandidateReviewError("desk review does not reproduce retained evidence and immutable prefix")


# Predictable interfaces for callers following the other journal projections.
assess_review = assess_desk_review
build_review_event = build_desk_review_event
evidence_for_review = evidence_for_desk_review
validate_review_event = validate_desk_review_event
