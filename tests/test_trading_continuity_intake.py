"""Offline native corporate-action pagination, coverage and replay adversaries."""
import copy
from decimal import localcontext
import unittest
from unittest.mock import patch

from blackpod_build_week.contracts.mission_request import ContractValidationError
from blackpod_build_week.contracts.trading_continuity_intake import (
    ContinuityIntakeRequest, ContinuityIntakeExport, ContinuityCoverageReview, CONTINUITY_LIMITATIONS,
)
from blackpod_build_week.hashing import canonical_json_bytes, sha256_bytes
from blackpod_build_week.trading_continuity_intake import (
    build_continuity_intake, verify_continuity_intake, verify_continuity_review,
)
from blackpod_build_week.trading_historical_intake import build_historical_intake
from test_trading_historical_intake_contracts import source_material, authority


def reference(path, raw):
    return {"path": path, "sha256": sha256_bytes(raw), "size_bytes": len(raw)}


def native_action(group="cash_dividends", number=1, effective="2026-01-09", process="2026-01-12"):
    common = {"id": f"00000000-0000-0000-0000-{number:012d}", "process_date": process}
    symbol = {"symbol": "SYNTHA", "cusip": "000000001"}
    actions = {
        "forward_splits": {**symbol, "new_rate": 2, "old_rate": 1, "ex_date": effective},
        "reverse_splits": {"symbol": "SYNTHA", "old_cusip": "000000001", "new_cusip": "000000002", "new_rate": 1, "old_rate": 2, "ex_date": effective},
        "unit_splits": {"old_symbol": "SYNTHA", "old_cusip": "000000001", "old_rate": 1, "new_symbol": "OTHER", "new_cusip": "000000002", "new_rate": 1, "alternate_symbol": "ALTERNATE", "alternate_cusip": "000000003", "alternate_rate": 1, "effective_date": effective},
        "cash_dividends": {**symbol, "rate": 0.5, "special": False, "foreign": False, "ex_date": effective},
        "stock_dividends": {**symbol, "rate": 0.1, "ex_date": effective},
        "spin_offs": {"source_symbol": "SYNTHA", "source_cusip": "000000001", "source_rate": 1, "new_symbol": "OTHER", "new_cusip": "000000002", "new_rate": 0.1, "ex_date": effective},
        "cash_mergers": {"acquiree_symbol": "SYNTHA", "acquiree_cusip": "000000001", "rate": 100, "effective_date": effective},
        "stock_mergers": {"acquirer_symbol": "OTHER", "acquirer_cusip": "000000002", "acquirer_rate": 1, "acquiree_symbol": "SYNTHA", "acquiree_cusip": "000000001", "acquiree_rate": 0.5, "effective_date": effective},
        "stock_and_cash_mergers": {"acquirer_symbol": "OTHER", "acquirer_cusip": "000000002", "acquirer_rate": 1, "acquiree_symbol": "SYNTHA", "acquiree_cusip": "000000001", "acquiree_rate": 0.5, "cash_rate": 2, "effective_date": effective},
        "redemptions": {**symbol, "rate": 5},
        "name_changes": {"old_symbol": "SYNTHA", "old_cusip": "000000001", "new_symbol": "OTHER", "new_cusip": "000000002"},
        "worthless_removals": symbol,
        "rights_distributions": {"source_symbol": "SYNTHA", "source_cusip": "000000001", "new_symbol": "OTHER", "new_cusip": "000000002", "rate": 0.1, "ex_date": effective},
    }
    return {**common, **actions[group]}


def continuity_fixture(groups=None, *, coverage=False, status=200, pages=None):
    """Entirely authored responses and local receipts, never provider evidence."""
    historical_request, _, historical_blobs = source_material()
    historical_request["availability_assumption"]["declared_by"] = "synthetic-fixture-author"
    history = build_historical_intake(historical_request, historical_blobs)
    evidence = dict(history["evidence"])
    dataset = history["dataset"]
    dataset_ref = reference("historical-intake/dataset.v2.json", dataset.to_bytes())
    request = {"schema_version": "blackpod.trading_continuity_intake_request.v1", "run_id": "fixture-continuity",
        "recorded_at": "2026-01-23T01:01:00Z", "domain": "TRADING", "mode": "SHADOW_RESEARCH",
        "scope": "RETAINED_CORPORATE_ACTION_INTAKE_ONLY", "evidence_scope": "SYNTHETIC_FIXTURE_ONLY",
        "dataset_evidence": dataset_ref, "universe": dataset.universe,
        "process_date_range": {"start": "2026-01-05", "end": "2026-01-21"}, "pages": [],
        "coverage_basis": "REVIEWED_EX_DATE_COVERAGE" if coverage else "EX_DATE_COVERAGE_UNVERIFIED",
        "coverage_review_evidence": None, "reviewer_id": "synthetic-fixture-author",
        "review_notes": "Authored offline fixture, not a vendor capture or real-security coverage review.",
        "auto_trading_enabled": False, "authority": authority()}
    pages = pages or [{"corporate_actions": groups or {}, "next_page_token": None}]
    values = {"pages": [], "receipts": [], "coverage": None}
    token = None
    for index, page in enumerate(pages):
        query = {"symbols": ",".join(dataset.universe), "start": "2026-01-05", "end": "2026-01-21", "limit": 1000, "sort": "asc"}
        if token is not None: query["page_token"] = token
        receipt = {"schema_version": "blackpod.trading_evidence_capture.v1", "method": "GET",
            "url": "https://data.alpaca.markets/v1/corporate-actions", "query": query,
            "captured_at": "2026-01-23T01:00:00Z", "status": status,
            "body_sha256": "0" * 64, "size_bytes": 0}
        values["pages"].append(page); values["receipts"].append(receipt)
        token = page["next_page_token"]
    if coverage:
        origin = b"Authored fixture independent review of every effective date and action type. No real-security completeness claim.\n"
        origin_ref = reference("fixture/coverage-review-origin.raw", origin); evidence[origin_ref["path"]] = origin
        values["coverage"] = {"schema_version": "blackpod.trading_continuity_coverage_review.v1",
            "review_id": "fictional-complete-action-coverage", "recorded_at": "2026-01-22T23:02:00Z",
            "dataset_evidence": dataset_ref, "universe": dataset.universe,
            "coverage_start_session_id": dataset.sessions[0]["session_id"],
            "coverage_end_session_id": dataset.sessions[-1]["session_id"],
            "coverage_policy": "ALL_ACTION_TYPES_EFFECTIVE_DATE_COVERAGE_INDEPENDENTLY_REVIEWED",
            "status": "SUPPORTED", "reviewer_id": "synthetic-fixture-author",
            "review_notes": "All authored fixture actions and dates checked; this is not provider authentication.",
            "source_evidence": [origin_ref], "auto_trading_enabled": False, "authority": authority()}
    return refresh_continuity(request, values, evidence)


def refresh_continuity(request, values, evidence):
    request, values, evidence = copy.deepcopy(request), copy.deepcopy(values), dict(evidence)
    request["pages"] = []
    for index, (value, receipt) in enumerate(zip(values["pages"], values["receipts"])):
        raw = canonical_json_bytes(value); body_ref = reference(f"fixture/actions-{index}.raw", raw)
        receipt["body_sha256"], receipt["size_bytes"] = body_ref["sha256"], body_ref["size_bytes"]
        receipt_raw = canonical_json_bytes(receipt); receipt_ref = reference(f"fixture/actions-{index}-receipt.json", receipt_raw)
        evidence[body_ref["path"]], evidence[receipt_ref["path"]] = raw, receipt_raw
        request["pages"].append({"response_evidence": body_ref, "capture_receipt_evidence": receipt_ref})
    if values["coverage"] is not None:
        raw = canonical_json_bytes(values["coverage"]); ref = reference("fixture/coverage-review.v1.json", raw)
        evidence[ref["path"]] = raw; request["coverage_review_evidence"] = ref
    return request, values, evidence, {sha256_bytes(raw): raw for raw in evidence.values()}


class ContinuityContractTests(unittest.TestCase):
    def test_closed_contract_and_immutable_roundtrip(self):
        request, _, _, _ = continuity_fixture()
        typed = ContinuityIntakeRequest.from_mapping(request); original = typed.to_bytes()
        request["pages"].clear(); typed.universe.clear()
        self.assertEqual(original, typed.to_bytes())
        self.assertEqual(original, ContinuityIntakeRequest.from_bytes(original).to_bytes())

    def test_request_rejects_missing_unknown_unsafe_fields(self):
        request, _, _, _ = continuity_fixture()
        mutations = [lambda r: r.pop("pages"), lambda r: r.update(extra=True), lambda r: r.update(domain="INVESTMENT"),
            lambda r: r.update(mode="PAPER"), lambda r: r.update(auto_trading_enabled=True),
            lambda r: r.update(auto_trading_enabled=0), lambda r: r["authority"].update(execution_enabled=True),
            lambda r: r["authority"].update(execution_enabled=0), lambda r: r.update(review_notes=" "),
            lambda r: r.update(reviewer_id=""), lambda r: r.update(evidence_scope="REAL"),
            lambda r: r["process_date_range"].update(start="2026-01-30"),
            lambda r: r["process_date_range"].update(start="2026-01-32"),
            lambda r: r.update(pages=[]), lambda r: r.update(coverage_basis="REVIEWED_EX_DATE_COVERAGE")]
        for mutate in mutations:
            with self.subTest(mutate=mutate):
                value = copy.deepcopy(request); mutate(value)
                with self.assertRaises(ContractValidationError): ContinuityIntakeRequest.from_mapping(value)

    def test_coverage_contract_cannot_hide_scope_or_enable_authority(self):
        _, values, _, _ = continuity_fixture(coverage=True); original = values["coverage"]
        for mutate in (lambda v: v.pop("coverage_policy"), lambda v: v.update(status="AUTHORIZES_TRADING"),
            lambda v: v.update(source_evidence=[]), lambda v: v.update(extra=True),
            lambda v: v.update(auto_trading_enabled=True), lambda v: v["authority"].update(policy_changes_enabled=True)):
            value = copy.deepcopy(original); mutate(value)
            with self.assertRaises(ContractValidationError): ContinuityCoverageReview.from_mapping(value)


class ContinuityProjectionTests(unittest.TestCase):
    def project(self, groups=None, *, coverage=False, status=200, pages=None, mutate=None):
        request, values, evidence, blobs = continuity_fixture(groups, coverage=coverage, status=status, pages=pages)
        if mutate:
            mutate(request, values)
            request, values, evidence, blobs = refresh_continuity(request, values, evidence)
        return build_continuity_intake(request, blobs)

    def rejects(self, mutate, *, groups=None, coverage=False, pages=None):
        with self.assertRaises(ContractValidationError): self.project(groups, coverage=coverage, pages=pages, mutate=mutate)

    def test_empty_complete_process_window_cannot_prove_continuity(self):
        material = self.project()
        self.assertEqual(material["export"].status, "AVAILABLE")
        self.assertTrue(material["export"].pagination_complete)
        self.assertFalse(material["source"].coverage_complete)
        self.assertEqual(material["review"].status, "UNRESOLVED")
        self.assertEqual(material["source"].events, [])

    def test_independently_reviewed_complete_empty_fixture_may_support_continuity(self):
        material = self.project(coverage=True)
        self.assertTrue(material["source"].coverage_complete)
        self.assertEqual(material["review"].status, "CONTINUITY_SUPPORTED")
        self.assertEqual(material["source"].basis, "SYNTHETIC_FIXTURE")

    def test_cash_distribution_defer_and_exact_native_origin(self):
        row = native_action(); material = self.project({"cash_dividends": [row]}, coverage=True)
        self.assertEqual(material["review"].status, "UNRESOLVED")
        self.assertEqual(material["source"].events[0]["kind"], "CASH_DISTRIBUTION")
        self.assertEqual(material["source"].events[0]["effective_session_id"], "alpaca-session-2026-01-09")
        self.assertEqual(material["export"].native_actions[0]["native_id"], row["id"])
        self.assertEqual(material["export"].native_actions[0]["process_date"], "2026-01-12")
        self.assertEqual(material["evidence"]["fixture/actions-0.raw"], canonical_json_bytes({"corporate_actions": {"cash_dividends": [row]}, "next_page_token": None}))

    def test_all_thirteen_native_types_map_or_explicitly_defer_unknown_effective_dates(self):
        groups = ["forward_splits", "reverse_splits", "unit_splits", "cash_dividends", "stock_dividends", "spin_offs",
                  "cash_mergers", "stock_mergers", "stock_and_cash_mergers", "redemptions", "name_changes", "worthless_removals", "rights_distributions"]
        expected = ["SPLIT", "SPLIT", "SPLIT", "CASH_DISTRIBUTION", "STOCK_DISTRIBUTION", "STOCK_DISTRIBUTION", "MERGER", "MERGER", "MERGER", "OTHER_PRICE_DISCONTINUITY", "SYMBOL_CHANGE", "OTHER_PRICE_DISCONTINUITY", "STOCK_DISTRIBUTION"]
        for index, (group, kind) in enumerate(zip(groups, expected)):
            with self.subTest(group=group):
                material = self.project({group: [native_action(group, index + 1)]}, coverage=True)
                self.assertEqual(material["source"].events[0]["kind"], kind)
                self.assertEqual(material["review"].status, "UNRESOLVED")
                if group in {"redemptions", "name_changes", "worthless_removals"}:
                    self.assertEqual(material["export"].native_actions[0]["effective_date_basis"], "UNKNOWN")
                    self.assertEqual(material["source"].events[0]["effective_session_id"], material["dataset"].sessions[0]["session_id"])

    def test_weekend_effective_date_maps_to_next_returned_session(self):
        material = self.project({"cash_dividends": [native_action(effective="2026-01-10")]})
        self.assertEqual(material["source"].events[0]["effective_session_id"], "alpaca-session-2026-01-12")
        self.assertEqual(material["export"].native_actions[0]["effective_date"], "2026-01-10")

    def test_actions_outside_dataset_retained_without_unknown_session_ids(self):
        material = self.project({"cash_dividends": [native_action(number=1, effective="2026-01-04"), native_action(number=2, effective="2026-01-25")]})
        self.assertEqual(material["source"].events, [])
        self.assertEqual([a["dataset_disposition"] for a in material["export"].native_actions], ["BEFORE_DATASET", "AFTER_DATASET"])
        self.assertTrue(all(a["mapped_session_id"] is None for a in material["export"].native_actions))

    def test_symbol_change_preserves_native_new_symbol_and_only_emits_requested_ownership(self):
        material = self.project({"name_changes": [native_action("name_changes")]})
        self.assertEqual(material["export"].native_actions[0]["affected_symbols"], ["OTHER", "SYNTHA"])
        self.assertEqual([e["symbol"] for e in material["source"].events], ["SYNTHA"])

    def test_optional_null_dates_and_acquirer_preserved_raw(self):
        row = native_action("cash_mergers"); row.update(acquirer_symbol=None, acquirer_cusip=None, payable_date=None)
        self.assertEqual(self.project({"cash_mergers": [row]})["export"].derived_event_count, 1)

    def test_ordered_complete_pagination_retains_all_pages(self):
        pages = [{"corporate_actions": {"cash_dividends": [native_action(number=1, process="2026-01-09")]}, "next_page_token": "next"},
                 {"corporate_actions": {"stock_dividends": [native_action("stock_dividends", number=2, process="2026-01-12")]}, "next_page_token": None}]
        material = self.project(pages=pages, coverage=True)
        self.assertTrue(material["export"].pagination_complete)
        self.assertEqual(material["export"].derived_event_count, 2)
        self.assertIn("fixture/actions-1.raw", material["evidence"])

    def test_missing_final_page_is_incomplete_and_never_supported(self):
        material = self.project(pages=[{"corporate_actions": {}, "next_page_token": "missing"}], coverage=True)
        self.assertEqual(material["export"].status, "INCOMPLETE")
        self.assertFalse(material["source"].coverage_complete)
        self.assertEqual(material["review"].status, "UNRESOLVED")

    def test_http_errors_are_unavailable_not_empty_no_action_findings(self):
        for status in (401, 403, 429, 500):
            with self.subTest(status=status):
                material = self.project(status=status, coverage=True)
                self.assertEqual(material["export"].status, "UNAVAILABLE")
                self.assertEqual(material["source"].events, [])
                self.assertFalse(material["source"].coverage_complete)
                self.assertEqual(material["review"].status, "UNRESOLVED")

    def test_error_after_first_page_preserves_prior_audit_without_inferred_events(self):
        pages = [{"corporate_actions": {"cash_dividends": [native_action()]}, "next_page_token": "next"},
                 {"corporate_actions": {}, "next_page_token": None}]
        material = self.project(pages=pages, mutate=lambda r, v: v["receipts"][1].update(status=403))
        self.assertEqual(material["export"].status, "UNAVAILABLE")
        self.assertEqual(len(material["export"].native_actions), 1)
        self.assertEqual(material["export"].derived_event_count, 0)

    def test_endpoint_query_filters_feed_or_sort_changes_reject(self):
        changes = [{"types": "cash_dividend"}, {"limit": 999}, {"limit": True}, {"sort": "desc"},
                   {"symbols": "SYNTHB,SYNTHA"}, {"start": "2026-01-06"}, {"cusips": "000000001"}]
        for change in changes:
            self.rejects(lambda r, v: v["receipts"][0]["query"].update(change))
        self.rejects(lambda r, v: v["receipts"][0].update(url="https://data.alpaca.markets/v2/stocks/quotes"))

    def test_native_unknown_group_missing_extra_and_bad_field_types_reject(self):
        self.rejects(lambda r, v: v["pages"][0]["corporate_actions"].update(unknown=[]))
        self.rejects(lambda r, v: v["pages"][0].update(extra="unexpected"))
        self.rejects(lambda r, v: v["pages"][0].pop("next_page_token"))
        for mutate in (lambda row: row.pop("ex_date"), lambda row: row.update(extra="hidden"),
            lambda row: row.update(id="not-an-id"), lambda row: row.update(symbol="OTHER"),
            lambda row: row.update(symbol="syntha"), lambda row: row.update(rate="0.5"),
            lambda row: row.update(rate=True), lambda row: row.update(rate=-1),
            lambda row: row.update(special=0), lambda row: row.update(ex_date="2026-02-30"),
            lambda row: row.update(cusip=""), lambda row: row.update(process_date="2026-01-22")):
            row = native_action(); mutate(row)
            with self.assertRaises(ContractValidationError): self.project({"cash_dividends": [row]})

    def test_native_split_rates_must_be_positive_not_implied_unit_defaults(self):
        for field in ("new_rate", "old_rate"):
            for bad in (0, -1, True, "1"):
                row = native_action("forward_splits"); row[field] = bad
                with self.assertRaises(ContractValidationError): self.project({"forward_splits": [row]})

    def test_native_pagination_shape_tokens_and_total_limit_reject(self):
        for mutate in (lambda r, v: v["pages"][0].update(corporate_actions=[]),
                       lambda r, v: v["pages"][0].update(next_page_token=True),
                       lambda r, v: v["pages"][0].update(next_page_token=""),
                       lambda r, v: v["pages"][0]["corporate_actions"].update(cash_dividends=None)):
            self.rejects(mutate)
        with self.assertRaises(ContractValidationError):
            self.project({"cash_dividends": [native_action(number=index + 1) for index in range(1001)]})

    def test_http_error_bytes_need_not_be_action_json_and_remain_exact(self):
        request, _, evidence, blobs = continuity_fixture(status=403)
        page = request["pages"][0]; body = b"Forbidden; no corporate-action payload.\n"
        page["response_evidence"] = reference(page["response_evidence"]["path"], body)
        from blackpod_build_week.contracts.trading_evidence_capture import CaptureReceipt
        receipt = CaptureReceipt.from_bytes(blobs[page["capture_receipt_evidence"]["sha256"]]).to_dict()
        receipt.update(body_sha256=sha256_bytes(body), size_bytes=len(body))
        raw = canonical_json_bytes(receipt); page["capture_receipt_evidence"] = reference(page["capture_receipt_evidence"]["path"], raw)
        blobs[sha256_bytes(body)], blobs[sha256_bytes(raw)] = body, raw
        material = build_continuity_intake(request, blobs)
        self.assertEqual(material["export"].status, "UNAVAILABLE")
        self.assertEqual(material["evidence"][page["response_evidence"]["path"]], body)

    def test_duplicate_nonfinite_and_excessive_numeric_native_json_reject(self):
        request, _, _, blobs = continuity_fixture()
        for body in (b'{"corporate_actions":{},"corporate_actions":{},"next_page_token":null}',
                     b'{"corporate_actions":{"cash_dividends":[NaN]},"next_page_token":null}',
                     b'{"corporate_actions":{"cash_dividends":[1e999999]},"next_page_token":null}'):
            from blackpod_build_week.contracts.trading_evidence_capture import CaptureReceipt
            altered = copy.deepcopy(request); page = altered["pages"][0]
            page["response_evidence"] = reference(page["response_evidence"]["path"], body)
            receipt = CaptureReceipt.from_bytes(blobs[page["capture_receipt_evidence"]["sha256"]]).to_dict()
            receipt.update(body_sha256=sha256_bytes(body), size_bytes=len(body))
            raw = canonical_json_bytes(receipt); page["capture_receipt_evidence"] = reference(page["capture_receipt_evidence"]["path"], raw)
            changed = {**blobs, sha256_bytes(body): body, sha256_bytes(raw): raw}
            with self.assertRaises(ContractValidationError): build_continuity_intake(altered, changed)

    def test_combined_evidence_size_bound_rejects_before_source_parsing(self):
        request, _, _, blobs = continuity_fixture()
        request["pages"][0]["response_evidence"]["size_bytes"] = 64 * 1024 * 1024
        with self.assertRaisesRegex(ContractValidationError, "combined retained"):
            build_continuity_intake(request, blobs)

    def test_duplicate_native_ids_across_groups_and_pages_reject(self):
        self.rejects(lambda r, v: None, groups={"cash_dividends": [native_action()], "stock_dividends": [native_action("stock_dividends")]})
        pages = [{"corporate_actions": {"cash_dividends": [native_action()]}, "next_page_token": "next"},
                 {"corporate_actions": {"cash_dividends": [native_action()]}, "next_page_token": None}]
        self.rejects(lambda r, v: None, pages=pages)

    def test_native_group_order_does_not_invent_global_process_sort_requirement(self):
        row1 = native_action(number=1, process="2026-01-12")
        row2 = native_action(number=2, process="2026-01-09"); row2["symbol"] = "SYNTHB"
        material = self.project({"cash_dividends": [row1, row2]})
        self.assertEqual([a["native_id"] for a in material["export"].native_actions], [row1["id"], row2["id"]])
        self.assertEqual(material["export"].derived_event_count, 2)

    def test_pagination_token_mismatch_cycle_unrequested_extra_pages_reject(self):
        pages = [{"corporate_actions": {}, "next_page_token": "next"}, {"corporate_actions": {}, "next_page_token": None}]
        self.rejects(lambda r, v: v["receipts"][1]["query"].update(page_token="wrong"), pages=pages)
        self.rejects(lambda r, v: v["pages"][1].update(next_page_token="next"), pages=pages)
        self.rejects(lambda r, v: v["pages"][0].update(next_page_token=None), pages=pages)
        self.rejects(lambda r, v: v["receipts"][0].update(status=403), pages=pages)

    def test_capture_and_coverage_clocks_do_not_override_historical_origins(self):
        self.rejects(lambda r, v: v["receipts"][0].update(captured_at="2026-01-23T02:00:00Z"))
        self.rejects(lambda r, v: r.update(recorded_at="2026-01-22T22:00:00Z"))
        self.rejects(lambda r, v: v["coverage"].update(recorded_at="2026-01-23T02:00:00Z"), coverage=True)
        self.rejects(lambda r, v: v["coverage"].update(recorded_at="2026-01-22T22:00:00Z"), coverage=True)

    def test_reviewed_coverage_must_bind_whole_dataset_and_independent_evidence(self):
        for mutate in (lambda r, v: v["coverage"].update(universe=["SYNTHA"]),
            lambda r, v: v["coverage"].update(coverage_start_session_id="alpaca-session-2026-01-06"),
            lambda r, v: v["coverage"].update(dataset_evidence={**r["dataset_evidence"], "sha256": "1" * 64}),
            lambda r, v: v["coverage"].update(source_evidence=[r["pages"][0]["response_evidence"]])):
            self.rejects(mutate, coverage=True)
        material = self.project(coverage=True, mutate=lambda r, v: v["coverage"].update(status="UNRESOLVED"))
        self.assertFalse(material["source"].coverage_complete)

    def test_fixture_scope_cannot_relabel_nonfixture_dataset(self):
        request, _, _, blobs = continuity_fixture()
        from blackpod_build_week.contracts.trading_research import TradingResearchDataset
        dataset = TradingResearchDataset.from_bytes(blobs[request["dataset_evidence"]["sha256"]])
        self.assertTrue(all(symbol.startswith("SYNTH") for symbol in dataset.universe))
        # A valid fictional dataset is explicitly marked by its retained request;
        # swapping only the raw declared author breaks deterministic dataset replay.
        raw = dataset.to_dict(); raw["provenance"]["availability_assumption"]["declared_by"] = "other"
        altered = canonical_json_bytes(raw); request["dataset_evidence"] = reference(request["dataset_evidence"]["path"], altered)
        blobs[sha256_bytes(altered)] = altered
        with self.assertRaises(ContractValidationError): build_continuity_intake(request, blobs)

    def test_reserved_paths_and_dataset_scope_mismatch_reject(self):
        self.rejects(lambda r, v: r.update(universe=["SYNTHA"]))
        request, values, evidence, blobs = continuity_fixture()
        for path in ("continuity-intake/request.v1.json", "continuity-intake/source.v1.json", "continuity-intake/review.v1.json"):
            altered = copy.deepcopy(request); altered["pages"][0]["response_evidence"]["path"] = path
            with self.assertRaises(ContractValidationError): build_continuity_intake(altered, blobs)

    def test_hash_size_and_receipt_body_binding_reject_even_if_wrappers_rehash(self):
        request, values, evidence, blobs = continuity_fixture()
        wrong = dict(blobs); wrong[request["pages"][0]["response_evidence"]["sha256"]] = b"{}"
        with self.assertRaises(ContractValidationError): build_continuity_intake(request, wrong)
        ref = request["pages"][0]["capture_receipt_evidence"]
        receipt = values["receipts"][0]; receipt["body_sha256"] = "1" * 64
        raw = canonical_json_bytes(receipt); request["pages"][0]["capture_receipt_evidence"] = reference(ref["path"], raw); blobs[sha256_bytes(raw)] = raw
        with self.assertRaises(ContractValidationError): build_continuity_intake(request, blobs)

    def test_replay_idempotence_and_review_verification(self):
        material = self.project({"cash_dividends": [native_action()]})
        replay = verify_continuity_intake(material["export"], material["blobs"])
        self.assertEqual(material["export"].to_bytes(), replay["export"].to_bytes())
        self.assertEqual(material["source"].to_bytes(), verify_continuity_review(material["review"], material["blobs"])["source"].to_bytes())

    def test_standalone_review_verifier_preserves_opaque_json_array_support(self):
        request, values, evidence, _ = continuity_fixture(coverage=True)
        raw = canonical_json_bytes([{"fixture_review": "all authored effective dates checked"}])
        origin_ref = {"path": "fixture/independent-coverage-origin.json", "sha256": sha256_bytes(raw), "size_bytes": len(raw)}
        evidence[origin_ref["path"]] = raw
        values["coverage"]["source_evidence"] = [origin_ref]
        request, _, _, blobs = refresh_continuity(request, values, evidence)
        material = build_continuity_intake(request, blobs)
        replay = verify_continuity_review(material["review"], material["blobs"])
        self.assertEqual(material["review"].to_bytes(), replay["review"].to_bytes())
        self.assertEqual(replay["evidence"][origin_ref["path"]], raw)

    def test_forged_derived_review_and_manifest_cannot_pass_replay(self):
        material = self.project()
        row = material["export"].to_dict(); row["pagination_complete"] = False
        with self.assertRaises(ContractValidationError): verify_continuity_intake(row, material["blobs"])
        review = material["review"].to_dict(); review["status"] = "CONTINUITY_SUPPORTED"
        with self.assertRaises(ContractValidationError): verify_continuity_review(review, material["blobs"])

    def test_export_cannot_hide_original_refs_or_reclassify_unknown_effective_dates(self):
        material = self.project({"name_changes": [native_action("name_changes")]})
        for mutate in (lambda r: r["source_evidence"].pop(0),
                       lambda r: r.update(status="INCOMPLETE"),
                       lambda r: r["native_actions"][0].update(effective_date="2026-01-12"),
                       lambda r: r["native_actions"][0].update(mapped_session_id=None),
                       lambda r: r["native_actions"][0].update(dataset_disposition="IN_DATASET")):
            row = material["export"].to_dict(); mutate(row)
            with self.assertRaises(ContractValidationError): ContinuityIntakeExport.from_mapping(row)

    def test_export_limitations_authority_and_unavailable_count_stay_closed(self):
        material = self.project(status=403)
        for mutate in (lambda r: r["limitations"].pop(), lambda r: r.update(derived_event_count=1),
                       lambda r: r.update(auto_trading_enabled=True), lambda r: r.update(extra=True)):
            row = material["export"].to_dict(); mutate(row)
            with self.assertRaises(ContractValidationError): ContinuityIntakeExport.from_mapping(row)
        self.assertEqual(material["export"].limitations, list(CONTINUITY_LIMITATIONS))

    def test_no_network_subprocess_or_ambient_decimal_dependence(self):
        expected = self.project({"cash_dividends": [native_action()]})["export"].to_bytes()
        with patch("socket.socket", side_effect=AssertionError("network forbidden")), patch("subprocess.Popen", side_effect=AssertionError("process forbidden")), localcontext() as context:
            context.prec = 2
            material = self.project({"cash_dividends": [native_action()]})
        self.assertEqual(expected, material["export"].to_bytes())


if __name__ == "__main__": unittest.main()
