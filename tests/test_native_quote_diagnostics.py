"""Offline witness/count tests; authored quote updates demonstrate no alpha."""
import copy
from datetime import timedelta
from decimal import Inexact, Rounded, localcontext
import json
import re
import socket
import unittest
from unittest.mock import patch

from blackpod_build_week import native_quote_diagnostics as engine
from blackpod_build_week.contracts.decision_journal import JournalEvent
from blackpod_build_week.contracts.mission_request import format_rfc3339, parse_rfc3339
from blackpod_build_week.contracts.train_market_evidence import TrainMarketSegmentRequest, TrainMarketExportRequest
from blackpod_build_week.hashing import canonical_json_bytes, sha256_bytes
from blackpod_build_week.train_market_evidence import prepare_capture_plan
from blackpod_build_week.train_market_evidence_journal import capture_plan_material, segment_material, export_material
from blackpod_build_week.trading_shadow_review_example import fixture_material


def reference(path, raw):
    return {"path": path, "sha256": sha256_bytes(raw), "size_bytes": len(raw)}


def authored_material(original, *, mode="normal", partial=False, failure=None, second_page=False):
    """Append new native-shaped quote sources, leaving frozen inputs unchanged."""
    events, blobs = list(original["events"]), dict(original["blobs"])
    capture = prepare_capture_plan(events, blobs, capture_id="diagnostic-authored-" + mode,
        created_at="2025-04-03T00:00:00Z", base_plan_event_id=original["base_studies"][0]["plan_event"].event_id)
    recorded = capture_plan_material(capture, events, blobs)
    events.append(recorded["event"]); blobs.update({sha256_bytes(raw): raw for raw in recorded["evidence"].values()})
    selected = []
    for segment_index, segment in enumerate(capture.segments):
        if partial and segment_index >= 2: break
        stamp = format_rfc3339(parse_rfc3339(segment["query"]["start"], "open") + timedelta(seconds=1))
        def row(**changes):
            return {"t": stamp, "bp": 100, "ap": 101, "bs": 10, "as": 20, "bx": "V", "ax": "V", "c": ["R"], "z": "C", **changes}
        quote_rows = {symbol: [row()] for symbol in original["dataset"].universe}
        first_symbol = original["dataset"].universe[0]
        if segment_index == 0:
            if mode == "rejections":
                quote_rows[first_symbol] += [row(bp=0, bs=0, c=["A"]), row(ap=0), row(bs=0),
                    row(bp=101, ap=100), row(c=[]), row(c=["R", "A"])]
            elif mode == "wide":
                quote_rows[first_symbol] += [row(bp=100, ap=2000, bs=1, **{"as": 2}),
                    row(bp=100, ap=2000, bs=2, **{"as": 3})]
            elif mode == "threshold":
                quote_rows[first_symbol] += [row(bp=190, ap=210), row(bp=195, ap=205), row(bp="197.5", ap="202.5")]
            elif mode == "lexical":
                quote_rows[first_symbol] = [row(bp="1e2", ap="2.00E+3", bs="1e0", **{"as": "2.00"})]
            elif mode == "empty": quote_rows = {}
            elif mode == "http": quote_rows = {}
        elif mode == "wide" and segment_index == 1:
            quote_rows[first_symbol] += [row(bp=100, ap=2000, bs=1, **{"as": 2})]
        pages = []
        bodies = [quote_rows]
        if second_page and segment_index == 0:
            # Equal extrema across pages are distinct timestamped updates.
            later = copy.deepcopy(quote_rows[first_symbol])
            for item in later: item["t"] = item["t"].replace("01Z", "02Z")
            bodies = [{first_symbol: quote_rows[first_symbol]},
                {symbol: later if symbol == first_symbol else rows for symbol, rows in quote_rows.items()}]
        for page_index, quotes in enumerate(bodies):
            raw = canonical_json_bytes({"quotes": quotes, "next_page_token": "diagnostic-next" if page_index + 1 < len(bodies) else None})
            # Only a newly authored source has explicit exponent number tokens.
            # This preserves their original lexemes rather than float-rounding.
            raw = re.sub(rb'"(bp|ap|bs|as)": "([^"]+)"', rb'"\1": \2', raw)
            prefix = "diagnostic-authored/" + mode + "/" + str(segment_index) + "/" + str(page_index)
            body = reference(prefix + ".raw", raw)
            query = copy.deepcopy(segment["query"])
            if page_index: query["page_token"] = "diagnostic-next"
            receipt = {"schema_version": "blackpod.trading_evidence_capture.v1", "method": "GET",
                "url": "https://data.alpaca.markets/v2/stocks/quotes", "query": query,
                "captured_at": "2025-04-04T00:00:00Z", "status": 403 if mode == "http" and segment_index == 0 else 200,
                "body_sha256": body["sha256"], "size_bytes": len(raw)}
            receipt_raw = canonical_json_bytes(receipt); receipt_ref = reference(prefix + ".receipt.json", receipt_raw)
            blobs.update({body["sha256"]: raw, receipt_ref["sha256"]: receipt_raw})
            pages.append({"body_evidence": body, "receipt_evidence": receipt_ref})
        request = TrainMarketSegmentRequest.from_mapping({"schema_version": "blackpod.train_market_segment_export_request.v1",
            "export_id": "diagnostic-export-" + mode, "capture_plan_event_id": recorded["event"].event_id,
            "segment_id": segment["segment_id"], "pages": pages, "failure": failure if segment_index == 0 else None,
            "exported_at": "2025-04-05T00:00:00Z", "auto_trading_enabled": False, "authority": engine.AUTHORITY})
        material = segment_material(request, events, blobs)
        events.append(material["event"]); selected.append(material["event"])
        blobs.update({sha256_bytes(raw): raw for raw in material["evidence"].values()})
    request = TrainMarketExportRequest.from_mapping({"schema_version": "blackpod.train_market_export_request.v1",
        "export_id": "diagnostic-export-" + mode, "capture_plan_event_id": recorded["event"].event_id,
        "segment_event_ids": sorted(event.event_id for event in selected), "exported_at": "2025-04-05T00:00:00Z",
        "continuity_event_id": None, "coverage_review_evidence": None, "capture_snapshot_evidence": None,
        "capture_checkpoint_evidence": [], "auto_trading_enabled": False, "authority": engine.AUTHORITY})
    exported = export_material(request, events, blobs)
    events.append(exported["event"]); blobs.update({sha256_bytes(raw): raw for raw in exported["evidence"].values()})
    return {"events": tuple(events), "blobs": blobs, "export_event": exported["event"], "segments": selected, "capture": capture}


class NativeQuoteDiagnosticTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with patch.object(socket.socket, "connect", side_effect=AssertionError("network forbidden")):
            cls.original = fixture_material()
            cls.original_hashes = [event.to_bytes() for event in cls.original["events"]]
            cls.complete = authored_material(cls.original)
            cls.rejections = authored_material(cls.original, mode="rejections")
            cls.wide = authored_material(cls.original, mode="wide", second_page=True)
            cls.threshold = authored_material(cls.original, mode="threshold")
            cls.lexical = authored_material(cls.original, mode="lexical")
            cls.partial = authored_material(cls.original, partial=True)
            cls.empty = authored_material(cls.original, mode="empty")
            cls.http = authored_material(cls.original, mode="http")
            cls.reports = {name: engine.diagnose_segmented_quotes(material["export_event"], material["events"], material["blobs"])
                for name, material in (("complete", cls.complete), ("rejections", cls.rejections), ("wide", cls.wide),
                    ("threshold", cls.threshold), ("lexical", cls.lexical), ("partial", cls.partial), ("empty", cls.empty), ("http", cls.http))}

    def setUp(self):
        self.enterContext(patch.object(socket.socket, "connect", side_effect=AssertionError("provider forbidden")))
        self.enterContext(patch("subprocess.run", side_effect=AssertionError("inference forbidden")))
        self.enterContext(patch("subprocess.Popen", side_effect=AssertionError("worker forbidden")))

    def test_full_original_plan_and_admitted_count_reconcile_without_mutation(self):
        report = self.reports["complete"]
        count = len(self.complete["capture"].segments)
        self.assertEqual(report["coverage"], {"planned_segments": count, "provided_segments": count,
            "missing_segments": 0, "capture_complete": True, "coverage_complete": True})
        self.assertEqual(report["totals"]["raw_quote_count"], count * len(self.original["dataset"].universe))
        self.assertEqual(report["totals"]["raw_quote_count"], report["totals"]["admitted_quote_count"])
        self.assertEqual([event.to_bytes() for event in self.original["events"]], self.original_hashes)

    def test_original_rejection_reasons_overlap_without_double_rejected_rows(self):
        report = self.reports["rejections"]
        self.assertEqual(report["totals"]["rejected_quote_count"], 6)
        self.assertEqual(report["totals"]["rejection_reasons"], {"NONPOSITIVE_PRICE": 2, "NONPOSITIVE_SIZE": 2,
            "CROSSED": 2, "CONDITION_NOT_EXACT_REGULAR_R": 3})
        self.assertEqual(report["totals"]["raw_quote_count"] - report["totals"]["admitted_quote_count"], 6)

    def test_wide_quotes_preserved_and_spread_only_counts_are_not_cost_qualification(self):
        report = self.reports["wide"]
        self.assertEqual(report["totals"]["spread_only_exceedance_counts"], {"1": 5, "2": 5, "4": 5})
        self.assertGreater(float(report["symbols"][0]["max_spread_bps"]), 1000)
        self.assertFalse(report["cost_applicability_verified"])
        self.assertEqual(report["spread_only_component_threshold"]["semantics"], "SPREAD_ONLY_NOT_FULL_COST_STRESS_MODEL")

    def test_strict_thresholds_exclude_exact_1000_500_250_boundary_equality(self):
        counts = self.reports["threshold"]["symbols"][0]["spread_only_exceedance_counts"]
        self.assertEqual(counts, {"1": 0, "2": 1, "4": 2})

    def test_witnesses_keep_original_source_numeric_lexemes(self):
        report = self.reports["lexical"]
        witness = report["symbols"][0]["max_spread_witness"]
        self.assertEqual(witness["native_row"]["bp"], "1e2")
        self.assertEqual(witness["native_row"]["ap"], "2.00E+3")
        self.assertEqual(witness["native_row"]["bs"], "1e0")
        self.assertEqual(witness["native_row"]["as"], "2.00")
        self.assertEqual(witness["native_row_sha256"], sha256_bytes(canonical_json_bytes(witness["native_row"])))
        self.assertEqual(report["native_row_number_encoding"], "JSON_NUMBER_TOKENS_AS_STRINGS")

    def test_witness_pointer_replays_exact_retained_body_and_receipt(self):
        for symbol in self.reports["wide"]["symbols"]:
            for field in ("max_spread_witness", "min_side_size_witness"):
                witness = symbol[field]
                body = self.wide["blobs"][witness["body_evidence"]["sha256"]]
                native = json.loads(body, parse_float=str, parse_int=str)
                symbol_key, index = witness["row_pointer"].split("/")[2:]
                self.assertEqual(native["quotes"][symbol_key][int(index)], witness["native_row"])
                receipt = json.loads(self.wide["blobs"][witness["receipt_evidence"]["sha256"]])
                self.assertEqual(receipt["body_sha256"], witness["body_evidence"]["sha256"])

    def test_first_frozen_segment_page_and_array_position_win_ties(self):
        witness = self.reports["wide"]["symbols"][0]["max_spread_witness"]
        self.assertEqual(witness["segment_id"], self.wide["capture"].segments[0]["segment_id"])
        self.assertEqual(witness["body_evidence"], self.wide["segments"][0].payload["request"]["pages"][0]["body_evidence"])
        self.assertEqual(witness["row_pointer"].rsplit("/", 1)[1], "1")

    def test_partial_export_inventories_every_missing_segment_without_false_coverage(self):
        report = self.reports["partial"]
        self.assertEqual(report["coverage"]["provided_segments"], 2)
        self.assertEqual(report["coverage"]["missing_segments"], len(self.partial["capture"].segments) - 2)
        self.assertFalse(report["coverage"]["capture_complete"])
        self.assertTrue(all(row["source_segment_event_id"] is None for row in report["segment_inventory"] if row["status"] == "MISSING"))

    def test_empty_terminal_capture_and_unavailable_page_remain_distinct(self):
        empty, http = self.reports["empty"], self.reports["http"]
        self.assertTrue(empty["coverage"]["capture_complete"])
        self.assertFalse(empty["coverage"]["coverage_complete"])
        self.assertFalse(http["coverage"]["capture_complete"])
        self.assertEqual(http["segment_inventory"][0]["status"], "CAPTURE_INCOMPLETE")
        self.assertEqual(empty["totals"]["raw_quote_count"], http["totals"]["raw_quote_count"])

    def test_deterministic_report_for_dictionary_order_and_later_history(self):
        material = self.partial
        later = self.complete["segments"][-1]
        a = engine.diagnose_segmented_quotes(material["export_event"], material["events"], material["blobs"])
        b = engine.diagnose_segmented_quotes(material["export_event"], (*material["events"], later), dict(reversed(list(material["blobs"].items()))))
        self.assertEqual(canonical_json_bytes(a), canonical_json_bytes(b))

    def test_decimal_math_independent_of_hostile_ambient_precision_and_traps(self):
        with localcontext() as context:
            context.prec = 3; context.traps[Inexact] = True; context.traps[Rounded] = True
            report = engine.diagnose_segmented_quotes(self.lexical["export_event"], self.lexical["events"], self.lexical["blobs"])
        self.assertEqual(report, self.reports["lexical"])

    def test_all_operational_economic_and_authentication_flags_remain_false(self):
        report = self.reports["wide"]
        for key in engine._FALSE_FIELDS: self.assertIs(report[key], False)
        self.assertEqual(report["authority"], engine.AUTHORITY)
        self.assertLess(len(canonical_json_bytes(report)), 8 * 1024 * 1024)

    def test_tampered_original_body_or_missing_blob_rejected(self):
        body = self.partial["segments"][0].payload["request"]["pages"][0]["body_evidence"]
        for replacement in (None, b"{}\n"):
            blobs = dict(self.partial["blobs"])
            if replacement is None: blobs.pop(body["sha256"])
            else: blobs[body["sha256"]] = replacement
            with self.assertRaises(ValueError): engine.diagnose_segmented_quotes(self.partial["export_event"], self.partial["events"], blobs)

    def test_forged_retained_segment_extremum_rejected_by_native_replay(self):
        value = self.partial["segments"][0].to_dict(); value["payload"]["result"]["symbols"][0]["max_spread_bps"] = "0"
        forged = JournalEvent.from_mapping(value)
        events = tuple(forged if event.event_id == forged.event_id else event for event in self.partial["events"])
        with self.assertRaises(ValueError): engine.diagnose_segmented_quotes(self.partial["export_event"], events, self.partial["blobs"])

    def test_forged_export_totals_or_conflicting_same_identity_rejected(self):
        value = self.partial["export_event"].to_dict(); value["payload"]["result"]["counts"]["raw_quote_count"] += 1
        forged = JournalEvent.from_mapping(value)
        with self.assertRaises(ValueError): engine.diagnose_segmented_quotes(forged, self.partial["events"], self.partial["blobs"])

    def test_cherry_picked_segment_or_duplicate_historical_identity_rejected(self):
        for events in (tuple(event for event in self.partial["events"] if event.event_id != self.partial["segments"][0].event_id),
                       (*self.partial["events"], self.partial["segments"][0])):
            with self.assertRaises(ValueError): engine.diagnose_segmented_quotes(self.partial["export_event"], events, self.partial["blobs"])

    def test_non_export_source_cannot_be_diagnosed_as_train_export(self):
        with self.assertRaises(ValueError): engine.diagnose_segmented_quotes(self.partial["segments"][0], self.partial["events"], self.partial["blobs"])

    def test_shape_validator_accepts_original_report_without_normalizing_tokens(self):
        original = copy.deepcopy(self.reports["lexical"])
        self.assertEqual(engine.validate_diagnostics(original), self.reports["lexical"])
        self.assertEqual(original, self.reports["lexical"])

    def test_extra_top_nested_count_and_native_fields_rejected(self):
        for pointer in ((), ("source",), ("coverage",), ("totals",), ("symbols", 0),
                        ("symbols", 0, "max_spread_witness"), ("symbols", 0, "max_spread_witness", "native_row")):
            value = copy.deepcopy(self.reports["wide"]); target = value
            for key in pointer: target = target[key]
            target["unknown"] = True
            with self.assertRaises(ValueError): engine.validate_diagnostics(value)

    def test_bool_counts_or_promoted_authority_rejected(self):
        for pointer in (("totals", "raw_quote_count"), ("coverage", "provided_segments"),
                        ("authority", "execution_enabled"), ("source_authentication_verified",), ("existing_gate_override",)):
            value = copy.deepcopy(self.reports["complete"]); target = value
            for key in pointer[:-1]: target = target[key]
            target[pointer[-1]] = True
            with self.assertRaises(ValueError): engine.validate_diagnostics(value)

    def test_false_reconciliation_or_overlapping_rejection_arithmetic_rejected(self):
        value = copy.deepcopy(self.reports["rejections"]); value["totals"]["rejection_reasons"]["CROSSED"] = 999
        with self.assertRaises(ValueError): engine.validate_diagnostics(value)
        value = copy.deepcopy(self.reports["rejections"]); value["reconciliation"]["counts_match"] = 1
        with self.assertRaises(ValueError): engine.validate_diagnostics(value)

    def test_witness_hash_pointer_calculation_size_condition_and_symbol_tamper_rejected(self):
        for key, replacement in (("native_row_sha256", "0" * 64), ("row_pointer", "/quotes/SYNTHA/10000"),
            ("spread_bps", "0"), ("reported_side_size_native_units", "100"), ("symbol", "SYNTHB"),
            ("segment_id", "missing-segment")):
            value = copy.deepcopy(self.reports["wide"]); value["symbols"][0]["max_spread_witness"][key] = replacement
            with self.assertRaises(ValueError): engine.validate_diagnostics(value)
        value = copy.deepcopy(self.reports["wide"]); value["symbols"][0]["max_spread_witness"]["native_row"]["c"] = ["A"]
        with self.assertRaises(ValueError): engine.validate_diagnostics(value)

    def test_native_witness_numbers_cannot_be_floats_bools_nonfinite_or_huge_exponents(self):
        for number in (100.0, True, "NaN", "1e999999999", "-1", "01"):
            value = copy.deepcopy(self.reports["lexical"]); value["symbols"][0]["max_spread_witness"]["native_row"]["bp"] = number
            with self.assertRaises(ValueError): engine.validate_diagnostics(value)

    def test_monotone_stress_counts_and_exact_threshold_semantics_required(self):
        value = copy.deepcopy(self.reports["wide"]); value["totals"]["spread_only_exceedance_counts"]["4"] = 0
        with self.assertRaises(ValueError): engine.validate_diagnostics(value)
        value = copy.deepcopy(self.reports["wide"]); value["spread_only_component_threshold"]["comparator"] = "GREATER_THAN_OR_EQUAL"
        with self.assertRaises(ValueError): engine.validate_diagnostics(value)

    def test_inventory_conflicts_and_missing_source_promotion_rejected(self):
        for change in ("duplicate", "missing_promoted", "capture_promoted"):
            value = copy.deepcopy(self.reports["partial"])
            if change == "duplicate": value["segment_inventory"][1] = copy.deepcopy(value["segment_inventory"][0])
            elif change == "missing_promoted": value["segment_inventory"][2]["source_segment_event_id"] = value["source_segment_event_ids"][0]
            else: value["coverage"]["capture_complete"] = True
            with self.assertRaises(ValueError): engine.validate_diagnostics(value)

    def test_explicit_limitations_and_fixture_scope_cannot_be_removed_or_relabelled(self):
        value = copy.deepcopy(self.reports["complete"]); value["limitations"] = []
        with self.assertRaises(ValueError): engine.validate_diagnostics(value)
        value = copy.deepcopy(self.reports["complete"]); value["source"]["evidence_scope"] = "RETAINED_HISTORY_RESEARCH"
        with self.assertRaises(ValueError): engine.validate_diagnostics(value)


if __name__ == "__main__":
    unittest.main()
