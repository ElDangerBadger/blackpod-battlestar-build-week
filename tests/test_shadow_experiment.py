"""Deterministic fixtures; no provider,broker,model,or historical journal scans."""
from copy import deepcopy
from datetime import datetime, timedelta
from decimal import localcontext, ROUND_UP, ROUND_DOWN
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock
from zoneinfo import ZoneInfo

from blackpod_build_week.contracts.decision_journal import JournalEvent
from blackpod_build_week.contracts.mission_request import ContractValidationError
from blackpod_build_week.contracts.shadow_experiment import ShadowExperimentProtocol, AUTHORITY
from blackpod_build_week.decision_journal_store import JournalStore, JournalConflictError, JournalVerificationError
from blackpod_build_week.hashing import canonical_json_bytes, sha256_bytes
from blackpod_build_week.shadow_experiment import (
    CALENDAR_PATH, CALENDAR_RECEIPT_PATH, HYPOTHESIS_PATH, build_protocol,
    freeze_experiment, collect_observation, read_experiment_view,
)
from blackpod_build_week.trading_hypotheses import catalog_documents, catalog_hypotheses

NY = ZoneInfo("America/New_York")


def fixture():
    first = datetime(2026, 10, 1)
    days = [first + timedelta(days=offset) for offset in range(60) if (first + timedelta(days=offset)).weekday() < 5]
    raw_calendar = json.dumps([{"date": day.date().isoformat(), "open": "09:30", "close": "16:00",
        "session_open": "0400", "session_close": "2000", "settlement_date": day.date().isoformat()} for day in days]).encode()
    calendar_receipt = receipt(raw_calendar, "2026-10-02T13:59:00Z", "calendar", days[0].date().isoformat(), days[-1].date().isoformat())
    hypothesis = next(row for row in catalog_documents(catalog_hypotheses("2026-10-01T12:00:00Z", "fixture-author"))
                      if row.hypothesis_id == "previous-session-reversal-v1").to_bytes()
    protocol = build_protocol(experiment_id="prospective-fixture", frozen_at="2026-10-02T14:00:00Z",
        first_signal_session="2026-10-02", calendar_captured_at="2026-10-02T13:59:00Z", calendar_raw=raw_calendar,
        hypothesis_raw=hypothesis, calendar_receipt_raw=calendar_receipt)
    return protocol, {CALENDAR_PATH: raw_calendar, CALENDAR_RECEIPT_PATH: calendar_receipt, HYPOTHESIS_PATH: hypothesis}


def receipt(body, captured_at, kind, start, end):
    query = {"start": start, "end": end}
    if kind == "bars":
        query.update(symbols="QQQ,SPY", timeframe="1Day", feed="iex", adjustment="raw", sort="asc", limit=10000)
    return canonical_json_bytes({"schema_version": "blackpod.read_only_historical_capture.v1", "method": "GET",
        "url": "https://data.alpaca.markets/v2/stocks/bars" if kind == "bars" else "https://paper-api.alpaca.markets/v2/calendar",
        "query": query, "captured_at": captured_at, "status": 200, "body_sha256": sha256_bytes(body), "size_bytes": len(body)})


def snapshot(protocol, evidence, captured_at, *, mutate=None, bars_clock=None):
    calendar = evidence[CALENDAR_PATH]
    clock = datetime.fromisoformat(captured_at.replace("Z", "+00:00"))
    response = {"bars": {"QQQ": [], "SPY": []}, "next_page_token": None}
    for index, row in enumerate(protocol["context_sessions"]):
        midnight = datetime.fromisoformat(row["date"]).replace(tzinfo=NY)
        if midnight > clock:
            continue
        for symbol in ("QQQ", "SPY"):
            close = 100 - index if symbol == "QQQ" else 100 + index
            response["bars"][symbol].append({"t": midnight.isoformat(), "o": 100 + index,
                "h": 200, "l": 1, "c": close, "v": 100000, "n": 1000, "vw": 100})
    if mutate is not None:
        mutate(response)
    bars = json.dumps(response, separators=(",", ":")).encode()
    return dict(captured_at=captured_at, calendar_raw=calendar, bars_raw=bars,
        calendar_receipt_raw=receipt(calendar, captured_at, "calendar", "2026-10-01", "2026-11-30"),
        bars_receipt_raw=receipt(bars, bars_clock or captured_at, "bars", "2026-10-01T00:00:00Z", captured_at))


class ShadowExperimentTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve() / "journal"
        self.protocol, self.evidence = fixture()

    def freeze(self):
        return freeze_experiment(self.root, self.protocol, self.evidence)

    def collect(self, captured_at="2026-10-03T01:00:00Z", **kwargs):
        return collect_observation(self.root, **snapshot(self.protocol, self.evidence, captured_at, **kwargs))

    def test_frozen_protocol_retains_original_horizon_and_proxy_limitation(self):
        view = self.freeze()["view"]
        self.assertEqual(len(view["protocol"]["sessions"]), 30)
        self.assertEqual(len(view["protocol"]["context_sessions"]), 33)
        self.assertEqual(view["summary"]["opportunity_count"], 60)
        self.assertEqual(view["protocol"]["original_horizon"]["entry_clock"], "NEXT_SESSION_OPEN_AFTER_INPUT_AVAILABILITY")
        self.assertIn("PROXY_BASIS_DIFFERS", " ".join(view["limitations"]))
        self.assertEqual(view["summary"]["economic_support"], "NOT_EVALUABLE")
        self.assertIsNone(view["summary"]["net_return"])
        self.assertEqual(view["authority"], AUTHORITY)

    def test_exact_protocol_retry_is_idempotent(self):
        self.assertTrue(self.freeze()["written"])
        self.assertFalse(self.freeze()["written"])
        self.assertEqual(JournalStore(self.root).verify().event_count, 1)

    def test_changed_protocol_identity_conflicts(self):
        self.freeze()
        changed = deepcopy(self.protocol)
        changed["frozen_at"] = "2026-10-02T14:01:00Z"
        with self.assertRaises(JournalConflictError):
            freeze_experiment(self.root, changed, self.evidence)

    def test_late_protocol_rejected(self):
        changed = deepcopy(self.protocol)
        changed["frozen_at"] = "2026-10-02T20:00:00Z"
        with self.assertRaises(ContractValidationError):
            freeze_experiment(self.root, changed, self.evidence)

    def test_protocol_altered_rule_rejected(self):
        for field, value in (("auto_trading_enabled", True), ("realized_trade_pnl", "1"), ("universe", ["SPY"])):
            with self.subTest(field=field):
                changed = deepcopy(self.protocol)
                changed[field] = value
                with self.assertRaises(ContractValidationError):
                    ShadowExperimentProtocol.from_mapping(changed)

    def test_unknown_protocol_field_rejected(self):
        with self.assertRaises(ContractValidationError):
            ShadowExperimentProtocol.from_mapping({**self.protocol, "orders": []})

    def test_missing_freeze_evidence_rejected(self):
        with self.assertRaises(ValueError):
            freeze_experiment(self.root, self.protocol, {CALENDAR_PATH: self.evidence[CALENDAR_PATH]})

    def test_wrong_hypothesis_rejected(self):
        source = next(row for row in catalog_documents(catalog_hypotheses("2026-10-01T12:00:00Z", "fixture-author"))
                      if row.hypothesis_id != "previous-session-reversal-v1").to_bytes()
        with self.assertRaises(ValueError):
            build_protocol(experiment_id="other", frozen_at=self.protocol["frozen_at"], first_signal_session="2026-10-02",
                calendar_captured_at=self.protocol["calendar_captured_at"], calendar_raw=self.evidence[CALENDAR_PATH],
                hypothesis_raw=source, calendar_receipt_raw=self.evidence[CALENDAR_RECEIPT_PATH])

    def test_initial_snapshot_has_zero_predictions(self):
        self.freeze()
        result = self.collect("2026-10-02T15:00:00Z")
        self.assertEqual(result["new_prediction_count"], 0)
        self.assertEqual(result["new_outcome_count"], 0)

    def test_regular_close_is_not_final_daily_close(self):
        self.freeze()
        self.assertEqual(self.collect("2026-10-02T21:00:00Z")["new_prediction_count"], 0)

    def test_completed_source_negative_and_nonnegative_rows(self):
        self.freeze()
        result = self.collect()
        self.assertEqual(result["new_prediction_count"], 2)
        self.assertEqual([row["status"] for row in result["view"]["predictions"]], ["OBSERVATIONAL_CANDIDATE", "ABSTAIN_NONNEGATIVE_RETURN"])
        self.assertEqual(result["view"]["predictions"][0]["entry_open_at"], "2026-10-05T08:00:00Z")

    def test_exact_observation_retry(self):
        self.freeze()
        first = self.collect()
        again = self.collect()
        self.assertFalse(again["written"])
        self.assertEqual(first["event_id"], again["event_id"])
        self.assertEqual(again["view"]["journal"]["event_count"], 2)

    def test_same_clock_different_source_conflicts(self):
        self.freeze()
        self.collect()
        def alter(body):
            body["bars"]["QQQ"][1]["c"] = 90
        with self.assertRaises(JournalConflictError):
            self.collect(mutate=alter)

    def test_source_captured_before_finality_is_missing_not_admitted_later(self):
        self.freeze()
        result = self.collect(bars_clock="2026-10-02T23:59:00Z")
        self.assertEqual(result["view"]["predictions"][0]["status"], "DEFER_MISSING_INPUT")

    def test_after_premarket_before_regular_open_is_late(self):
        self.freeze()
        result = self.collect("2026-10-05T10:00:00Z")
        self.assertEqual({row["status"] for row in result["view"]["predictions"]}, {"MISSED_PREDICTION_DEADLINE"})
        self.assertTrue(all(row["signal_return"] is None for row in result["view"]["predictions"]))

    def test_exact_deadline_is_late(self):
        self.freeze()
        result = self.collect("2026-10-05T07:55:00Z")
        self.assertEqual(result["view"]["summary"]["missed_count"], 2)

    def test_missing_symbol_is_recorded_without_imputation(self):
        self.freeze()
        result = self.collect(mutate=lambda body: body["bars"].pop("QQQ"))
        self.assertEqual(result["view"]["summary"]["missing_input_count"], 1)

    def test_empty_source_is_recorded_as_missing(self):
        self.freeze()
        result = self.collect(mutate=lambda body: body.update(bars=None))
        self.assertEqual(result["view"]["summary"]["missing_input_count"], 2)

    def test_original_prediction_never_revised_by_later_source(self):
        self.freeze()
        original = self.collect()["view"]["predictions"]
        def revise(body):
            body["bars"]["QQQ"][1]["c"] = 150
        later = self.collect("2026-10-03T02:00:00Z", mutate=revise)
        self.assertEqual(later["view"]["predictions"], original)
        self.assertEqual(later["new_prediction_count"], 0)

    def test_adjacent_nonoverlapping_holding_intervals_can_be_recorded(self):
        self.freeze()
        self.collect()
        result = self.collect("2026-10-06T01:00:00Z")
        qqq = [row for row in result["view"]["predictions"] if row["symbol"] == "QQQ"]
        self.assertEqual([row["status"] for row in qqq], ["OBSERVATIONAL_CANDIDATE"] * 2)
        self.assertEqual(qqq[0]["exit_open_at"], qqq[1]["entry_open_at"])

    def test_outcome_waits_for_exit_daily_bar_finality(self):
        self.freeze()
        self.collect()
        result = self.collect("2026-10-06T15:00:00Z")
        self.assertEqual(result["new_outcome_count"], 0)

    def test_paired_outcome_is_gross_only_linked_and_immutable(self):
        self.freeze()
        first = self.collect()["view"]["predictions"]
        result = self.collect("2026-10-07T01:00:00Z")
        outcomes = result["view"]["outcomes"]
        self.assertEqual(len(outcomes), 2)
        self.assertEqual(outcomes[0]["prediction_id"], first[0]["prediction_id"])
        self.assertEqual(outcomes[0]["status"], "OBSERVED_GROSS_PROXY_ONLY")
        self.assertEqual(outcomes[0]["candidate_gross_return"], outcomes[0]["control_gross_return"])
        self.assertEqual(outcomes[0]["excess_over_control"], "0")
        self.assertIsNone(outcomes[1]["candidate_gross_return"])
        self.assertIsNone(result["view"]["summary"]["net_return"])
        later = self.collect("2026-10-07T02:00:00Z")
        self.assertEqual(later["view"]["outcomes"], outcomes)

    def test_missing_control_pair_leaves_candidate_outcome_pending(self):
        self.freeze()
        self.collect()
        def missing(body):
            body["bars"]["SPY"] = [row for row in body["bars"]["SPY"] if not row["t"].startswith("2026-10-06")]
        result = self.collect("2026-10-07T01:00:00Z", mutate=missing)
        self.assertEqual(result["view"]["summary"]["observed_outcome_count"], 0)
        self.assertEqual(result["new_outcome_count"], 1)

    def test_late_opportunities_never_become_measured(self):
        self.freeze()
        result = self.collect("2026-10-07T01:00:00Z")
        self.assertEqual(result["view"]["summary"]["observed_outcome_count"], 0)
        self.assertTrue(all(row["status"] == "UNMEASURABLE" for row in result["view"]["outcomes"]))

    def test_receipt_hash_mismatch_fails(self):
        self.freeze()
        args = snapshot(self.protocol, self.evidence, "2026-10-03T01:00:00Z")
        args["bars_raw"] += b" "
        with self.assertRaises(ValueError):
            collect_observation(self.root, **args)

    def test_future_receipt_fails(self):
        self.freeze()
        with self.assertRaises(ValueError):
            self.collect(bars_clock="2026-10-03T02:00:00Z")

    def test_calendar_revision_fails_closed(self):
        self.freeze()
        args = snapshot(self.protocol, self.evidence, "2026-10-03T01:00:00Z")
        body = json.loads(args["calendar_raw"])
        body[1]["open"] = "10:00"
        args["calendar_raw"] = canonical_json_bytes(body)
        args["calendar_receipt_raw"] = receipt(args["calendar_raw"], args["captured_at"], "calendar", "2026-10-01", "2026-11-30")
        with self.assertRaises(ValueError):
            collect_observation(self.root, **args)

    def test_paginated_response_fails_closed(self):
        self.freeze()
        with self.assertRaises(ValueError):
            self.collect(mutate=lambda body: body.update(next_page_token="more"))

    def test_zero_and_tiny_negative_sign_uses_exact_prices(self):
        self.freeze()
        def tiny(body):
            for row, close in zip(body["bars"]["QQQ"], [10000000000000000000, 9999999999999999999]):
                row.update(c=close, h=10000000000000000000, o=close, vw=close)
        result = self.collect(mutate=tiny)
        self.assertEqual(result["view"]["predictions"][0]["status"], "OBSERVATIONAL_CANDIDATE")

    def test_host_decimal_rounding_does_not_change_results(self):
        self.freeze()
        with localcontext() as context:
            context.prec, context.rounding = 6, ROUND_UP
            first = self.collect()
        with localcontext() as context:
            context.prec, context.rounding = 3, ROUND_DOWN
            again = self.collect()
        self.assertEqual(first["view"], again["view"])
        self.assertFalse(again["written"])

    def test_forged_prediction_does_not_pass_semantic_replay(self):
        self.freeze()
        self.collect()
        events, blobs = JournalStore(self.root).verified_contents()
        event = events[-1].to_dict()
        event["payload"]["predictions"][0]["status"] = "ABSTAIN_NONNEGATIVE_RETURN"
        event["source"]["source_sha256"] = sha256_bytes(canonical_json_bytes(event["payload"]))
        forged = JournalEvent.from_mapping(event)
        from blackpod_build_week.shadow_experiment import validate_shadow_experiment_event
        with self.assertRaises(ValueError):
            validate_shadow_experiment_event(forged, events[:1], blobs)

    def test_staging_interruption_recovers_on_exact_retry(self):
        self.freeze()
        from blackpod_build_week import decision_journal_store as module
        publish = module._publish_immutable
        def interrupt(staging, target, name, payload):
            if name.endswith(".json"):
                raise OSError("fixture interruption")
            return publish(staging, target, name, payload)
        with mock.patch.object(module, "_publish_immutable", side_effect=interrupt):
            with self.assertRaises(Exception):
                self.collect()
        result = self.collect()
        self.assertTrue(result["written"])
        verified = JournalStore(self.root).verify()
        self.assertEqual(verified.event_count, 2)
        self.assertEqual(verified.orphan_evidence_count, 0)

    def test_read_view_is_read_only_and_reproducible(self):
        self.freeze()
        self.collect()
        before = {path: path.read_bytes() for path in self.root.rglob("*") if path.is_file()}
        first, second = read_experiment_view(self.root), read_experiment_view(self.root)
        self.assertEqual(first, second)
        self.assertEqual(before, {path: path.read_bytes() for path in self.root.rglob("*") if path.is_file()})

    def test_no_provider_broker_or_subprocess_needed(self):
        with mock.patch("socket.socket.connect", side_effect=AssertionError("network prohibited")), \
             mock.patch("subprocess.Popen", side_effect=AssertionError("worker prohibited")):
            self.freeze()
            self.collect()
            self.assertFalse(read_experiment_view(self.root)["auto_trading_enabled"])

    def test_declared_limit_and_future_native_bar_rejected(self):
        self.freeze()
        args = snapshot(self.protocol, self.evidence, "2026-10-03T01:00:00Z")
        declared = json.loads(args["bars_receipt_raw"])
        declared["query"]["limit"] = 1
        args["bars_receipt_raw"] = canonical_json_bytes(declared)
        with self.assertRaises(ValueError):
            collect_observation(self.root, **args)
        def future(body):
            body["bars"]["QQQ"][-1]["t"] = "2026-10-05T00:00:00-04:00"
        with self.assertRaises(ValueError):
            self.collect(mutate=future)

    def test_complete_calendar_without_prospective_records_is_inconclusive(self):
        self.freeze()
        last = datetime.fromisoformat(self.protocol["context_sessions"][-1]["session_close_at"].replace("Z", "+00:00")) + timedelta(hours=1)
        view = self.collect(last.isoformat().replace("+00:00", "Z"))["view"]
        self.assertEqual(view["summary"]["recorded_prediction_count"], 60)
        self.assertEqual(view["summary"]["missed_count"], 60)
        self.assertEqual(view["summary"]["conclusion"], "INCONCLUSIVE_MISSING_EVIDENCE")
        self.assertEqual(view["summary"]["economic_support"], "NOT_EVALUABLE")

    def test_full_pilot_is_descriptive_only_even_when_gross_proxy_positive(self):
        self.freeze()
        def open_proxy(body):
            for symbol in ("QQQ", "SPY"):
                for index, row in enumerate(body["bars"][symbol]):
                    row["o"] = 100 + 2 * index if symbol == "QQQ" else 100
        for signal in self.protocol["sessions"]:
            captured = datetime.fromisoformat(signal["session_close_at"].replace("Z", "+00:00")) + timedelta(hours=1)
            self.collect(captured.isoformat().replace("+00:00", "Z"), mutate=open_proxy)
        final = datetime.fromisoformat(self.protocol["context_sessions"][-1]["session_close_at"].replace("Z", "+00:00")) + timedelta(hours=1)
        view = self.collect(final.isoformat().replace("+00:00", "Z"), mutate=open_proxy)["view"]
        self.assertEqual(view["summary"]["observed_outcome_count"], 30)
        self.assertEqual(view["summary"]["conclusion"], "DESCRIPTIVE_POSITIVE_PROXY_ONLY")
        self.assertEqual(view["summary"]["economic_support"], "NOT_EVALUABLE")
        self.assertEqual(view["summary"]["pending_outcome_count"], 0)
        self.assertEqual(view["authority"], AUTHORITY)
        self.assertEqual(view["summary"]["next_action"], "MANUAL_REVIEW_AFTER_PILOT_NO_AUTOMATIC_EXTENSION")

    def _completed_pilot(self, mutate=None):
        self.freeze()
        for signal in self.protocol["sessions"]:
            captured = datetime.fromisoformat(signal["session_close_at"].replace("Z", "+00:00")) + timedelta(hours=1)
            self.collect(captured.isoformat().replace("+00:00", "Z"), mutate=mutate)
        final = datetime.fromisoformat(self.protocol["context_sessions"][-1]["session_close_at"].replace("Z", "+00:00")) + timedelta(hours=1)
        return self.collect(final.isoformat().replace("+00:00", "Z"), mutate=mutate)["view"]

    def test_positive_candidate_return_without_control_excess_is_not_positive_result(self):
        view = self._completed_pilot()
        self.assertGreater(float(view["summary"]["mean_gross_return"]), 0)
        self.assertEqual(view["summary"]["mean_gross_excess_over_control"], "0")
        self.assertEqual(view["summary"]["conclusion"], "DESCRIPTIVE_NONPOSITIVE_PROXY")
        self.assertEqual(view["summary"]["economic_support"], "NOT_EVALUABLE")

    def test_complete_cohort_without_candidates_is_inconclusive_not_success(self):
        def zero_signals(body):
            for rows in body["bars"].values():
                for row in rows:
                    row["c"] = 100
        view = self._completed_pilot(zero_signals)
        self.assertEqual(view["summary"]["abstention_count"], 60)
        self.assertEqual(view["summary"]["pending_outcome_count"], 0)
        self.assertEqual(view["summary"]["conclusion"], "INCONCLUSIVE_TOO_FEW_CANDIDATES")
        self.assertIsNone(view["summary"]["mean_gross_return"])


if __name__ == "__main__":
    unittest.main()
