"""Retained PAPER activity normalization; no network, runtime or SDK imports."""
from __future__ import annotations

import copy
from decimal import Inexact, Rounded, localcontext
import socket
import unittest
from unittest.mock import patch

from blackpod_build_week.contracts.trading_accounting import PaperActivitiesInput
from blackpod_build_week.hashing import canonical_json_bytes, sha256_bytes
from blackpod_build_week import paper_activity_import as importer


def fill(identity="fill-1", **changes):
    value = {"activity_type": "FILL", "id": identity, "order_id": "order-1", "symbol": "MSFT", "side": "buy",
             "qty": "0.2", "price": "10.123456789012345678", "transaction_time": "2026-10-15T12:00:00.123456Z",
             "type": "partial_fill", "cum_qty": "0.2", "leaves_qty": "0.8"}
    value.update(changes)
    return value


def fee(identity="fee-1", **changes):
    value = {"activity_type": "FEE", "id": identity, "net_amount": "-0.01", "date": "2026-10-15"}
    value.update(changes)
    return value


def export_source(activities=None, **changes):
    value = {"schema_version": "blackpod.paper_activity_export.v1", "recorded_at": "2026-10-16T01:00:00Z",
             "account_id": "fixture-account", "mode": "PAPER", "currency": "USD",
             "window": {"started_at": "2026-10-15T00:00:00Z", "ended_at": "2026-10-16T00:00:00Z"},
             "coverage": {"fills_complete": True, "fees_complete": False, "scope_order_ids": ["order-1"]},
             "source_kind": "SYNTHETIC_FIXTURE", "activities": [fill()] if activities is None else activities}
    value.update(changes)
    return value


class PaperActivityImportTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(patch.object(socket.socket, "connect", side_effect=AssertionError("network forbidden")))
        self.enterContext(patch("subprocess.Popen", side_effect=AssertionError("runtime forbidden")))
        self.enterContext(patch("subprocess.run", side_effect=AssertionError("provider forbidden")))

    def imported(self, source=None):
        raw = canonical_json_bytes(source or export_source())
        return importer.activities_input_from_export(raw, activity_set_id="activities-1", evidence_path="broker/activities.json"), raw

    def assert_invalid(self, source):
        with self.assertRaises(importer.PaperActivityImportError):
            self.imported(source)

    def test_individual_fill_facts_and_original_source_are_preserved(self):
        document, raw = self.imported()
        self.assertEqual(document.fills[0]["qty"], "0.2")
        self.assertEqual(document.fills[0]["price"], "10.123456789012345678")
        self.assertEqual(document.fills[0]["occurred_at"], "2026-10-15T12:00:00.123456Z")
        self.assertEqual(document.provenance["source_evidence"], {
            "path": "broker/activities.json", "sha256": sha256_bytes(raw), "size_bytes": len(raw),
        })
        self.assertFalse(document.provenance["provider_verified"])
        self.assertTrue(all(value is False for value in document.authority.values()))
        importer.validate_activities_source(document, raw)

    def test_cumulative_order_quantity_never_becomes_fill_quantity(self):
        first = fill(qty="0.2", cum_qty="0.2")
        second = fill("fill-2", qty="0.3", cum_qty="0.5", transaction_time="2026-10-15T12:00:01Z")
        document, _ = self.imported(export_source([second, first]))
        self.assertEqual([item["qty"] for item in document.fills], ["0.3", "0.2"])

    def test_byte_identical_duplicate_rows_deduplicate_without_rewriting_evidence(self):
        row = fill()
        document, raw = self.imported(export_source([row, copy.deepcopy(row)]))
        self.assertEqual(len(document.fills), 1)
        self.assertEqual(document.provenance["source_evidence"]["sha256"], sha256_bytes(raw))
        self.assertEqual(len(importer.normalize_activity_export(raw)["fills"]), 1)

    def test_duplicate_changed_facts_or_raw_cumulative_metadata_reject(self):
        for changes in ({"qty": "0.1"}, {"price": "10"}, {"cum_qty": "0.3"}, {"leaves_qty": "0.7"}, {"description": "changed"}):
            with self.subTest(changes=changes):
                self.assert_invalid(export_source([fill(), fill(**changes)]))

    def test_fill_and_fee_cannot_share_provider_activity_identity(self):
        self.assert_invalid(export_source([fill(), fee("fill-1")]))

    def test_unallocated_date_only_fee_preserves_precision_and_turns_debit_into_expense(self):
        document, raw = self.imported(export_source([fill(), fee()]))
        selected = document.fees[0]
        self.assertEqual(selected["amount"], "0.01")
        self.assertEqual(selected["occurred_at"], "2026-10-15")
        self.assertEqual(selected["fee_type"], "OTHER")
        self.assertIsNone(selected["order_id"])
        self.assertIsNone(selected["fill_activity_id"])
        self.assertIsNone(selected["symbol"])
        self.assertFalse(document.coverage["fees_complete"])
        importer.validate_activities_source(document, raw)

    def test_positive_cashflow_fee_credit_becomes_negative_expense(self):
        document, _ = self.imported(export_source([fee(net_amount="0.001")]))
        self.assertEqual(document.fees[0]["amount"], "-0.001")

    def test_zero_fee_cashflow_has_no_invented_charge_or_credit(self):
        for spelling in ("0", "-0", "0.00", "-0.00"):
            with self.subTest(spelling=spelling):
                document, _ = self.imported(export_source([fee(net_amount=spelling)]))
                self.assertEqual(document.fees[0]["amount"], "0")

    def test_source_backed_optional_fee_binding_is_preserved(self):
        document, _ = self.imported(export_source([fill(), fee(order_id="order-1", fill_activity_id="fill-1", symbol="MSFT")]))
        selected = document.fees[0]
        self.assertEqual(selected["order_id"], "order-1")
        self.assertEqual(selected["fill_activity_id"], "fill-1")
        self.assertEqual(selected["symbol"], "MSFT")

    def test_descriptions_and_unrecognized_fee_subtypes_do_not_create_attribution(self):
        document, _ = self.imported(export_source([fee(description="fee for MSFT order-1", fee_type="REGULATORY")]))
        self.assertEqual(document.fees[0]["fee_type"], "OTHER")
        self.assertIsNone(document.fees[0]["order_id"])

    def test_unknown_financial_activity_types_fail_closed(self):
        for kind in ("DIV", "SSP", "JNLS", "CSD", "CSW", "REORG", "CFEE", "TRD", "unknown"):
            with self.subTest(kind=kind):
                self.assert_invalid(export_source([{"activity_type": kind, "id": "other-1", "net_amount": "1"}]))

    def test_all_required_fill_fields_must_be_source_backed(self):
        for field in ("id", "order_id", "symbol", "side", "qty", "price", "transaction_time"):
            row = fill()
            del row[field]
            with self.subTest(field=field):
                self.assert_invalid(export_source([row]))

    def test_fee_amount_date_and_identity_are_required(self):
        for field in ("id", "net_amount", "date"):
            row = fee()
            del row[field]
            with self.subTest(field=field):
                self.assert_invalid(export_source([row]))

    def test_numeric_inputs_never_accept_float_boolean_exponent_or_rounded_precision(self):
        for value in (0.2, True, "NaN", "Infinity", "1e-2", "0.0000000000000000001", "01", "+1", ".1", "-1", "0"):
            with self.subTest(value=value):
                self.assert_invalid(export_source([fill(qty=value)]))
        for value in (False, "-Infinity", "1e-2", "0.0000000000000000001"):
            with self.subTest(fee_value=value):
                self.assert_invalid(export_source([fee(net_amount=value)]))

    def test_source_cumulative_facts_cannot_contradict_execution_qty(self):
        self.assert_invalid(export_source([fill(cum_qty="0.1")]))
        self.assert_invalid(export_source([fill(leaves_qty="-1")]))
        self.assert_invalid(export_source([fill(), fill("fill-2", transaction_time="2026-10-15T12:00:01Z", cum_qty="0.2")]))
        self.assert_invalid(export_source([fill(), fill("fill-2", transaction_time="2026-10-15T12:00:01Z", cum_qty="0.5")]))

    def test_incomplete_coverage_retains_a_cumulative_gap_without_inventing_missing_fill(self):
        source = export_source([fill(), fill("fill-2", transaction_time="2026-10-15T12:00:01Z", cum_qty="0.5")])
        source["coverage"]["fills_complete"] = False
        document, _ = self.imported(source)
        self.assertEqual(len(document.fills), 2)
        self.assertFalse(document.coverage["fills_complete"])

    def test_submicrosecond_fill_times_reject_instead_of_losing_fifo_order(self):
        self.assert_invalid(export_source([fill(transaction_time="2026-10-15T12:00:00.123456789Z")]))
        self.assert_invalid(export_source([fill(transaction_time="2026-10-15T12:00:00")]))
        self.assert_invalid(export_source([fill(transaction_time="2026-10-15")]))

    def test_timezone_normalization_preserves_exact_execution_instant(self):
        document, _ = self.imported(export_source([fill(transaction_time="2026-10-15T05:00:00.123456-07:00")]))
        self.assertEqual(document.fills[0]["occurred_at"], "2026-10-15T12:00:00.123456Z")

    def test_date_only_fee_requires_the_whole_utc_day_in_window(self):
        for window in ({"started_at": "2026-10-15T00:00:01Z", "ended_at": "2026-10-16T00:00:00Z"},
                       {"started_at": "2026-10-15T00:00:00Z", "ended_at": "2026-10-15T23:59:59Z"}):
            with self.subTest(window=window):
                self.assert_invalid(export_source([fee()], window=window))
        self.assert_invalid(export_source([fee(date="2026-02-30")]))

    def test_exact_timestamp_fee_keeps_its_actual_time(self):
        document, _ = self.imported(export_source([fee(date="2026-10-15T23:00:00Z")]))
        self.assertEqual(document.fees[0]["occurred_at"], "2026-10-15T23:00:00Z")

    def test_fill_scope_and_fee_scope_are_explicit(self):
        self.assert_invalid(export_source([fill(order_id="unscoped-order")]))
        self.assert_invalid(export_source([fee(order_id="unscoped-order")]))
        self.assert_invalid(export_source(coverage={"fills_complete": True, "fees_complete": False, "scope_order_ids": ["order-1", "order-1"]}))

    def test_account_mode_currency_and_provider_kind_cannot_default(self):
        for changes in ({"mode": "LIVE"}, {"mode": None}, {"currency": "EUR"}, {"account_id": "../account"},
                        {"source_kind": "VERIFIED_BROKER"}, {"schema_version": "blackpod.paper_activity_export.v0"}):
            with self.subTest(changes=changes):
                self.assert_invalid(export_source(**changes))
        self.assert_invalid(export_source([fee(currency="EUR")]))
        for field in ("recorded_at", "account_id", "window", "coverage", "source_kind"):
            source = export_source()
            del source[field]
            with self.subTest(field=field):
                self.assert_invalid(source)

    def test_explicit_row_identity_mode_and_currency_cannot_be_relabelled(self):
        for factory in (fill, fee):
            for changes in ({"account_id": "another-account"}, {"mode": "LIVE"}, {"currency": "EUR"},
                            {"account_id": None}, {"mode": None}, {"currency": None}):
                with self.subTest(kind=factory.__name__, changes=changes):
                    self.assert_invalid(export_source([factory(**changes)]))

    def test_matching_optional_row_identity_is_preserved_in_original_evidence(self):
        document, raw = self.imported(export_source([
            fill(account_id="fixture-account", mode="PAPER", currency="USD"),
            fee(account_id="fixture-account", mode="PAPER", currency="USD"),
        ]))
        self.assertEqual(document.account_id, "fixture-account")
        self.assertFalse(document.provenance["provider_verified"])
        importer.validate_activities_source(document, raw)

    def test_explicit_fee_binding_cannot_contradict_source_fill(self):
        for changes in ({"order_id": "other-order", "fill_activity_id": "fill-1"},
                        {"order_id": "order-1", "fill_activity_id": "fill-1", "symbol": "AAPL"}):
            source = export_source([fill(), fee(**changes)])
            source["coverage"]["scope_order_ids"].append("other-order")
            with self.subTest(changes=changes):
                self.assert_invalid(source)

    def test_unknown_source_fee_fill_identity_stays_an_explicit_unresolved_hint(self):
        document, raw = self.imported(export_source([fill(), fee(order_id="order-1", fill_activity_id="unobserved-fill")]))
        self.assertEqual(document.fees[0]["fill_activity_id"], "unobserved-fill")
        # A missing source fill is not guessed from symbol/order/amount. The
        # accounting engine will retain this fee as unallocated and withhold net.
        importer.validate_activities_source(document, raw)

    def test_explicit_empty_activity_set_is_not_given_execution_or_fee_completeness(self):
        source = export_source([], coverage={"fills_complete": False, "fees_complete": False, "scope_order_ids": []})
        document, _ = self.imported(source)
        self.assertEqual(document.fills, [])
        self.assertEqual(document.fees, [])
        self.assertFalse(document.coverage["fills_complete"])
        self.assertFalse(document.coverage["fees_complete"])

    def test_source_validation_rejects_rehashed_changes_to_selected_import_facts(self):
        document, raw = self.imported()
        changed = document.to_dict()
        changed["fills"][0]["price"] = "999"
        changed = PaperActivitiesInput.from_mapping(changed)
        with self.assertRaises(importer.PaperActivityImportError):
            importer.validate_activities_source(changed, raw)
        altered_raw = canonical_json_bytes(export_source([fill(price="999")]))
        with self.assertRaises(importer.PaperActivityImportError):
            importer.validate_activities_source(document, altered_raw)

    def test_source_validation_rejects_invented_fee_order_binding(self):
        document, raw = self.imported(export_source([fill(), fee()]))
        changed = document.to_dict()
        changed["fees"][0]["order_id"] = "order-1"
        changed = PaperActivitiesInput.from_mapping(changed)
        with self.assertRaises(importer.PaperActivityImportError):
            importer.validate_activities_source(changed, raw)

    def test_explicit_source_kind_does_not_attest_provider_identity(self):
        document, raw = self.imported(export_source(source_kind="ALPACA_PAPER_ACTIVITY_IMPORT"))
        self.assertFalse(document.provenance["provider_verified"])
        importer.validate_activities_source(document, raw)

    def test_import_identity_is_explicit_alias_is_supported(self):
        raw = canonical_json_bytes(export_source())
        document = importer.activities_input_from_export(raw, import_id="explicit-import", evidence_path="broker/source.json")
        self.assertEqual(document.activity_set_id, "explicit-import")
        for kwargs in ({}, {"activity_set_id": "one", "import_id": "two"}):
            with self.subTest(kwargs=kwargs), self.assertRaises(importer.PaperActivityImportError):
                importer.activities_input_from_export(raw, evidence_path="broker/source.json", **kwargs)

    def test_invalid_json_duplicate_keys_unicode_and_deep_nesting_fail_cleanly(self):
        invalid = [b"[]", b"{}", b"{\"account_id\":\"one\",\"account_id\":\"two\"}", b"{\"x\":NaN}", b"\xff",
                   b'{"x":' + b"[" * 2000 + b"0" + b"]" * 2000 + b"}"]
        for raw in invalid:
            with self.subTest(raw_size=len(raw)), self.assertRaises(importer.PaperActivityImportError):
                importer.normalize_activity_export(raw)

    def test_changed_coverage_cannot_be_claimed_over_original_source(self):
        document, raw = self.imported()
        changed = document.to_dict()
        changed["coverage"]["fees_complete"] = True
        changed = PaperActivitiesInput.from_mapping(changed)
        with self.assertRaises(importer.PaperActivityImportError):
            importer.validate_activities_source(changed, raw)

    def test_ambient_decimal_context_cannot_change_cumulative_validation(self):
        source = export_source([fill(qty="0.111111111111111111", cum_qty="0.111111111111111111"),
                                fill("fill-2", qty="0.111111111111111111", cum_qty="0.222222222222222222", transaction_time="2026-10-15T12:00:01Z")])
        with localcontext() as context:
            context.prec = 2
            document, _ = self.imported(source)
        self.assertEqual(document.fills[1]["qty"], "0.111111111111111111")

    def test_ambient_decimal_context_cannot_round_signed_fee_expense(self):
        with localcontext() as context:
            context.prec = 2
            document, raw = self.imported(export_source([fee(net_amount="-123456789.123456789012345678")]))
            importer.validate_activities_source(document, raw)
        self.assertEqual(document.fees[0]["amount"], "123456789.123456789012345678")

    def test_ambient_exponent_limits_and_rounding_traps_cannot_change_import(self):
        source = export_source([
            fill(qty="123456789.111111111111111111", cum_qty="123456789.111111111111111111"),
            fill("fill-2", qty="123456789.111111111111111111", cum_qty="246913578.222222222222222222",
                 transaction_time="2026-10-15T12:00:01Z"),
            fee(net_amount="-123456789.123456789012345678"),
        ])
        expected, raw = self.imported(source)
        with localcontext() as context:
            context.prec, context.Emax, context.Emin = 2, 1, -1
            context.traps[Inexact] = True
            context.traps[Rounded] = True
            actual = importer.activities_input_from_export(raw, activity_set_id="activities-1", evidence_path="broker/activities.json")
            importer.validate_activities_source(actual, raw)
        self.assertEqual(actual.to_bytes(), expected.to_bytes())


if __name__ == "__main__":
    unittest.main()
