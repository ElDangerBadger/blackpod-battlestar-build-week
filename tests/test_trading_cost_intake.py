"""Native quote/assumption reconstruction and honest cost deferral tests."""
import copy
from decimal import Decimal, localcontext
import unittest
from unittest.mock import patch

from blackpod_build_week.contracts.mission_request import ContractValidationError
from blackpod_build_week.contracts.trading_cost_intake import CostAssumptionReview, CostIntakeRequest
from blackpod_build_week.hashing import canonical_json_bytes, sha256_bytes
from blackpod_build_week.trading_cost_intake import build_cost_intake, verify_cost_intake
from blackpod_build_week.trading_historical_intake import build_historical_intake
from test_trading_historical_intake_contracts import source_material


def _ref(path, raw):
    return {"path": path, "sha256": sha256_bytes(raw), "size_bytes": len(raw)}


def cost_fixture_material(*, assumptions=True):
    history_request, _, history_blobs = source_material()
    history_request["availability_assumption"]["declared_by"] = "synthetic-fixture-author"
    history = build_historical_intake(history_request, history_blobs)
    dataset = history["dataset"]
    dataset_ref = history["export"].dataset_evidence
    quotes = {symbol: [{"t": session["open_at"].replace("Z", ".123456789Z"), "bp": 100,
                       "bs": 50, "bx": "V", "ap": 100.1, "as": 60, "ax": "V", "c": ["R"], "z": "C"}
                      for session in dataset.sessions] for symbol in dataset.universe}
    body = {"quotes": quotes, "next_page_token": None}
    receipt = {"schema_version": "blackpod.trading_evidence_capture.v1", "method": "GET",
               "url": "https://data.alpaca.markets/v2/stocks/quotes", "query": {"symbols": ",".join(dataset.universe),
                   "start": dataset.sessions[0]["open_at"], "end": "2026-01-21T14:31:00Z", "limit": 10000,
                   "feed": "iex", "currency": "USD", "sort": "asc", "asof": "-"},
               "captured_at": "2026-01-22T23:02:00Z", "status": 200, "body_sha256": "0" * 64, "size_bytes": 0}
    review = {"schema_version": "blackpod.trading_cost_assumption_review.v1", "review_id": "synthetic-cost-assumptions",
              "recorded_at": "2026-01-22T23:02:30Z", "dataset_evidence": dataset_ref, "universe": dataset.universe,
              "coverage_start_session_id": dataset.sessions[0]["session_id"], "coverage_end_session_id": dataset.sessions[-1]["session_id"],
              "evidence_scope": "SYNTHETIC_FIXTURE_ONLY", "status": "REVIEWED_SHADOW_ASSUMPTIONS",
              "parameters": {"slippage_bps": "1", "fee_bps": "0.5", "fee_per_fill": "0.02"},
              "origin_evidence": [], "reviewer_id": "fixture-reviewer", "review_notes": "Authored conservative test assumptions, not observations or a fee schedule.",
              "auto_trading_enabled": False, "authority": history_request["authority"]}
    request = {"schema_version": "blackpod.trading_cost_intake_request.v1", "run_id": "synthetic-cost-intake",
               "recorded_at": "2026-01-22T23:03:00Z", "domain": "TRADING", "mode": "SHADOW_RESEARCH",
               "scope": "COST_EVIDENCE_INTAKE_ONLY", "evidence_scope": "SYNTHETIC_FIXTURE_ONLY",
               "dataset_evidence": dataset_ref, "quote_pages": [], "assumption_review_evidence": None,
               "reviewer_id": "fixture-reviewer", "review_notes": "Strict full fixture opening quote coverage only; no live execution authority.",
               "auto_trading_enabled": False, "authority": history_request["authority"]}
    values = {"pages": [(body, receipt)], "assumptions": review if assumptions else None,
              "assumption_origin": b"Authored fixture assumptions. No observed execution costs.\n"}
    return refresh_cost_fixture(request, values, history["blobs"])


def refresh_cost_fixture(request, values, blobs):
    request, values, blobs = copy.deepcopy(request), copy.deepcopy(values), dict(blobs)
    request["quote_pages"] = []
    for index, (body, receipt) in enumerate(values["pages"]):
        body_raw = body if isinstance(body, bytes) else canonical_json_bytes(body)
        receipt["body_sha256"], receipt["size_bytes"] = sha256_bytes(body_raw), len(body_raw)
        receipt_raw = canonical_json_bytes(receipt)
        refs = {"body_evidence": _ref(f"quotes/page-{index:03}.raw", body_raw),
                "receipt_evidence": _ref(f"quotes/page-{index:03}-receipt.json", receipt_raw)}
        request["quote_pages"].append(refs)
        blobs[sha256_bytes(body_raw)] = body_raw
        blobs[sha256_bytes(receipt_raw)] = receipt_raw
    if values["assumptions"] is not None:
        origin = values["assumption_origin"]
        values["assumptions"]["origin_evidence"] = [_ref("cost-review/assumptions.raw", origin)]
        blobs[sha256_bytes(origin)] = origin
        raw = canonical_json_bytes(values["assumptions"])
        request["assumption_review_evidence"] = _ref("cost-review/assumptions.v1.json", raw)
        blobs[sha256_bytes(raw)] = raw
    else:
        request["assumption_review_evidence"] = None
    return request, values, blobs


class CostContractTests(unittest.TestCase):
    def test_immutable_roundtrip(self):
        request, values, _ = cost_fixture_material()
        for cls, value in ((CostIntakeRequest, request), (CostAssumptionReview, values["assumptions"])):
            doc = cls.from_mapping(value)
            raw = doc.to_bytes()
            value["authority"].clear()
            doc.authority.clear()
            self.assertEqual(cls.from_bytes(raw).to_bytes(), raw)
            self.assertEqual(doc.to_bytes(), raw)

    def test_request_strict_closed_fields(self):
        for mutation in (lambda row: row.pop("quote_pages"), lambda row: row.update(secret="hidden"),
                         lambda row: row.update(evidence_scope="REAL"), lambda row: row.update(mode="PAPER"),
                         lambda row: row.update(domain="INVESTMENT"), lambda row: row.update(auto_trading_enabled=True)):
            request, _, _ = cost_fixture_material(); mutation(request)
            with self.assertRaises(ContractValidationError): CostIntakeRequest.from_mapping(request)

    def test_authority_booleans_are_strictly_disabled(self):
        for key in cost_fixture_material()[0]["authority"]:
            for value in (True, 0, "false"):
                request, values, _ = cost_fixture_material()
                for cls, row in ((CostIntakeRequest, request), (CostAssumptionReview, values["assumptions"])):
                    row["authority"][key] = value
                    with self.assertRaises(ContractValidationError): cls.from_mapping(row)

    def test_quote_pages_distinct_opaque_raw_and_bounded(self):
        for mutation in (lambda row: row.update(quote_pages=[]),
                         lambda row: row["quote_pages"][0]["body_evidence"].update(path="quotes/data.json"),
                         lambda row: row["quote_pages"][0].update(receipt_evidence=row["quote_pages"][0]["body_evidence"]),
                         lambda row: row.update(quote_pages=row["quote_pages"] * 129)):
            request, _, _ = cost_fixture_material(); mutation(request)
            with self.assertRaises(ContractValidationError): CostIntakeRequest.from_mapping(request)

    def test_assumption_parameters_are_explicit_no_observed_cost_claim(self):
        for mutation in (lambda row: row.update(status="EMPIRICALLY_VERIFIED"), lambda row: row.update(parameters=None),
                         lambda row: row["parameters"].update(fee_bps="-1"), lambda row: row["parameters"].update(slippage_bps=1),
                         lambda row: row["parameters"].update(spread_bps="1"), lambda row: row.update(origin_evidence=[])):
            _, values, _ = cost_fixture_material(); row = values["assumptions"]; mutation(row)
            with self.assertRaises(ContractValidationError): CostAssumptionReview.from_mapping(row)

    def test_unresolved_assumptions_can_explicitly_omit_parameters(self):
        _, values, _ = cost_fixture_material(); row = values["assumptions"]
        row.update(status="UNRESOLVED", parameters=None)
        self.assertIsNone(CostAssumptionReview.from_mapping(row).parameters)


class CostProjectionTests(unittest.TestCase):
    def project(self, mutate=None, *, assumptions=True):
        request, values, blobs = cost_fixture_material(assumptions=assumptions)
        if mutate:
            mutate(request, values)
            request, values, blobs = refresh_cost_fixture(request, values, blobs)
        return build_cost_intake(request, blobs)

    def reject(self, mutate):
        with self.assertRaises(ContractValidationError): self.project(mutate)

    def test_supported_full_coverage_has_measured_bounds_separate_assumptions(self):
        material = self.project()
        self.assertEqual(material["assessment"]["status"], "SUPPORTED")
        self.assertEqual(material["assessment"]["eligible_opening_quote_count"], 24)
        self.assertEqual(material["assessment"]["missing_symbol_sessions"], [])
        self.assertEqual(material["source"].observations[0]["spread_bps"], "9.995002498750624688")
        self.assertEqual(material["review"].cost_model["slippage_bps"], "1")
        self.assertEqual(material["source"].basis, "SYNTHETIC_FIXTURE")
        self.assertFalse(material["assessment"]["provider_authenticity_verified"])

    def test_nanoseconds_spelling_is_preserved_without_float_rounding(self):
        material = self.project()
        row = material["assessment"]["measurements"][0]
        self.assertEqual(row["first_native_timestamp"], "2026-01-05T14:30:00.123456789Z")
        self.assertIn(b"14:30:00.123456789Z", material["evidence"]["quotes/page-000.raw"])

    def test_spread_is_round_up_to_18_places_and_context_independent(self):
        material = self.project()
        bound = Decimal(material["review"].cost_model["spread_bps"])
        with localcontext() as context:
            context.prec = 100
            actual = Decimal("0.1") * Decimal("20000") / Decimal("200.1")
        self.assertGreaterEqual(bound, actual)
        self.assertLess(bound - actual, Decimal("1e-18"))
        with localcontext() as context:
            context.prec = 3
            tiny_context = self.project()
        self.assertEqual(tiny_context["review"].to_bytes(), material["review"].to_bytes())

    def test_max_bound_uses_all_eligible_samples_and_max_across_symbols(self):
        material = self.project(lambda request, values: values["pages"][0][0]["quotes"]["SYNTHB"][3].update(ap=100.5))
        self.assertGreater(Decimal(material["review"].cost_model["spread_bps"]), Decimal("49"))
        self.assertEqual(material["review"].cost_model["spread_bps"], material["source"].observations[1]["spread_bps"])

    def test_missing_assumptions_never_invents_zero_slippage_fees(self):
        material = self.project(assumptions=False)
        self.assertEqual(material["assessment"]["status"], "UNRESOLVED")
        self.assertIsNone(material["source"])
        self.assertIsNone(material["review"].cost_model)
        self.assertIn("EXPLICIT_COST_ASSUMPTIONS_MISSING", material["assessment"]["reason_codes"])

    def test_unresolved_assumptions_prevent_supported_source(self):
        material = self.project(lambda request, values: values["assumptions"].update(status="UNRESOLVED", parameters=None))
        self.assertIsNone(material["source"])
        self.assertIn("EXPLICIT_COST_ASSUMPTIONS_UNRESOLVED", material["assessment"]["reason_codes"])

    def test_selective_last_session_never_extrapolates_to_entire_dataset(self):
        def mutate(request, values):
            quotes = values["pages"][0][0]["quotes"]
            for symbol in quotes:
                quotes[symbol] = quotes[symbol][-1:]
        material = self.project(mutate)
        self.assertEqual(len(material["assessment"]["missing_symbol_sessions"]), 22)
        self.assertFalse(material["assessment"]["opening_minute_coverage_complete"])
        self.assertIsNone(material["source"])

    def test_absent_symbol_cannot_be_intersected_away(self):
        material = self.project(lambda request, values: values["pages"][0][0]["quotes"].pop("SYNTHB"))
        self.assertEqual(len(material["assessment"]["missing_symbol_sessions"]), 12)
        self.assertIsNone(material["review"].cost_model)

    def test_empty_native_quotes_are_unresolved_not_zero_spread(self):
        material = self.project(lambda request, values: values["pages"][0][0].update(quotes={}))
        self.assertEqual(material["assessment"]["native_quote_count"], 0)
        self.assertIsNone(material["assessment"]["measurements"][0]["spread_bps_upper_bound"])

    def test_non_200_response_is_unavailable_not_parse_repaired_as_empty_quotes(self):
        for status in (401, 403, 429, 500):
            def mutate(request, values):
                values["pages"][0] = (b'{"message":"not authorized"}', values["pages"][0][1])
                values["pages"][0][1]["status"] = status
            material = self.project(mutate)
            self.assertEqual(material["assessment"]["status"], "UNAVAILABLE")
            self.assertIsNone(material["source"])
            self.assertEqual(material["assessment"]["native_quote_count"], 0)

    def test_pending_page_token_is_explicit_incomplete_coverage(self):
        material = self.project(lambda request, values: values["pages"][0][0].update(next_page_token="native-next"))
        self.assertIn("QUOTE_PAGINATION_INCOMPLETE", material["assessment"]["reason_codes"])
        self.assertFalse(material["assessment"]["eligible"])

    def test_complete_native_page_chain_supports_full_coverage(self):
        def mutate(request, values):
            body, receipt = values["pages"][0]
            second = {"quotes": {"SYNTHB": body["quotes"].pop("SYNTHB")}, "next_page_token": None}
            body["next_page_token"] = "native-next"
            receipt2 = copy.deepcopy(receipt); receipt2["query"]["page_token"] = "native-next"
            values["pages"].append((second, receipt2))
        material = self.project(mutate)
        self.assertEqual(material["assessment"]["status"], "SUPPORTED")
        self.assertEqual(material["assessment"]["native_quote_count"], 24)

    def test_page_query_token_base_and_chain_cycles_reject(self):
        def pages(request, values):
            body, receipt = values["pages"][0]
            second = {"quotes": {"SYNTHB": body["quotes"].pop("SYNTHB")}, "next_page_token": None}
            body["next_page_token"] = "next"
            receipt2 = copy.deepcopy(receipt); receipt2["query"]["page_token"] = "wrong"
            values["pages"].append((second, receipt2))
        self.reject(pages)
        self.reject(lambda request, values: values["pages"][0][1]["query"].update(page_token="orphan"))

    def test_page_base_query_cannot_change_mid_chain(self):
        def mutate(request, values):
            body, receipt = values["pages"][0]
            second = {"quotes": {"SYNTHB": body["quotes"].pop("SYNTHB")}, "next_page_token": None}
            body["next_page_token"] = "next"
            receipt2 = copy.deepcopy(receipt); receipt2["query"].update(page_token="next", limit=9999)
            values["pages"].append((second, receipt2))
        self.reject(mutate)

    def test_page_cycles_and_continuation_after_final_page_reject(self):
        def mutate(request, values):
            body, receipt = values["pages"][0]
            second = {"quotes": {"SYNTHB": body["quotes"].pop("SYNTHB")}, "next_page_token": "next"}
            body["next_page_token"] = "next"
            receipt2 = copy.deepcopy(receipt); receipt2["query"]["page_token"] = "next"
            values["pages"].append((second, receipt2))
        self.reject(mutate)
        def after_final(request, values):
            receipt = copy.deepcopy(values["pages"][0][1]); receipt["query"]["page_token"] = "invented"
            values["pages"].append(({"quotes": {}, "next_page_token": None}, receipt))
        self.reject(after_final)

    def test_second_page_http_failure_retains_partial_measurement_but_defer(self):
        def mutate(request, values):
            body, receipt = values["pages"][0]
            body["quotes"].pop("SYNTHB"); body["next_page_token"] = "next"
            receipt2 = copy.deepcopy(receipt); receipt2["query"]["page_token"] = "next"; receipt2["status"] = 403
            values["pages"].append((b'{"message":"forbidden"}', receipt2))
        material = self.project(mutate)
        self.assertEqual(material["assessment"]["status"], "UNRESOLVED")
        self.assertEqual(material["assessment"]["native_quote_count"], 12)
        self.assertIsNone(material["assessment"]["measurements"][1]["spread_bps_upper_bound"])
        self.assertIn("QUOTE_RESPONSE_UNAVAILABLE", material["assessment"]["reason_codes"])
        self.assertIsNone(material["source"])

    def test_source_json_duplicate_keys_nonfinite_and_type_mismatches_reject(self):
        for raw in (b'{"quotes":{},"quotes":{},"next_page_token":null}',
                    b'{"quotes":{},"next_page_token":NaN}', b'[]', b'\xff'):
            self.reject(lambda request, values: values["pages"].__setitem__(0, (raw, values["pages"][0][1])))

    def test_raw_hash_size_missing_evidence_receipt_body_binding_reject(self):
        request, _, blobs = cost_fixture_material()
        ref = request["quote_pages"][0]["body_evidence"]
        for value in (None, b"{}", b"oops"):
            changed = dict(blobs)
            if value is None: changed.pop(ref["sha256"])
            else: changed[ref["sha256"]] = value
            with self.assertRaises(ContractValidationError): build_cost_intake(request, changed)
        request, _, blobs = cost_fixture_material()
        ref = request["quote_pages"][0]["receipt_evidence"]
        import json
        receipt = json.loads(blobs[ref["sha256"]]); receipt["body_sha256"] = "1" * 64
        raw = canonical_json_bytes(receipt); request["quote_pages"][0]["receipt_evidence"] = _ref(ref["path"], raw); blobs[sha256_bytes(raw)] = raw
        with self.assertRaises(ContractValidationError): build_cost_intake(request, blobs)

    def test_receipt_endpoint_method_clocks_query_mismatch_reject(self):
        for mutation in (lambda request, values: values["pages"][0][1].update(method="POST"),
                         lambda request, values: values["pages"][0][1].update(url="https://api.alpaca.markets/v2/orders"),
                         lambda request, values: values["pages"][0][1].update(captured_at="2026-01-22T23:04:00Z"),
                         lambda request, values: values["pages"][0][1].update(captured_at="2026-01-22T22:00:00Z"),
                         lambda request, values: values["pages"][0][1]["query"].update(end="2026-01-23T00:00:00Z")):
            self.reject(mutation)

    def test_query_feed_currency_sort_mapping_universe_and_limit_reject(self):
        for field, value in (("feed", "sip"), ("currency", "EUR"), ("sort", "desc"), ("asof", "2026-01-01"),
                             ("symbols", "SYNTHB,SYNTHA"), ("limit", 0), ("limit", True), ("limit", 1)):
            self.reject(lambda request, values: values["pages"][0][1]["query"].update({field: value}))

    def test_native_schema_extra_unknown_symbol_missing_tape_or_row_reject(self):
        for mutation in (lambda request, values: values["pages"][0][0].update(extra="hidden"),
                         lambda request, values: values["pages"][0][0]["quotes"].update(OTHER=[]),
                         lambda request, values: values["pages"][0][0]["quotes"]["SYNTHA"][0].pop("z"),
                         lambda request, values: values["pages"][0][0]["quotes"]["SYNTHA"][0].update(z="X"),
                         lambda request, values: values["pages"][0][0]["quotes"].update(SYNTHA={})):
            self.reject(mutation)

    def test_native_row_numbers_cannot_be_strings_boolean_negative_or_fractional_sizes(self):
        for field, value in (("bp", "100"), ("ap", True), ("bs", 1.5), ("as", -1), ("bp", -1), ("c", "R"), ("bx", ""), ("z", {})):
            self.reject(lambda request, values: values["pages"][0][0]["quotes"]["SYNTHA"][0].update({field: value}))

    def test_zero_crossed_condition_or_size_rows_are_retained_but_do_not_satisfy_coverage(self):
        for changes in ({"bp": 0}, {"ap": 0}, {"ap": 99}, {"bs": 0}, {"as": 0}, {"c": ["I"]}, {"c": []}):
            material = self.project(lambda request, values: values["pages"][0][0]["quotes"]["SYNTHA"][0].update(changes))
            self.assertEqual(len(material["assessment"]["missing_symbol_sessions"]), 1)
            self.assertEqual(material["assessment"]["native_quote_count"], 24)

    def test_ns_boundary_one_ns_after_window_not_admitted(self):
        def mutate(request, values):
            values["pages"][0][0]["quotes"]["SYNTHA"][0]["t"] = "2026-01-05T14:31:00.000000001Z"
        material = self.project(mutate)
        self.assertEqual(len(material["assessment"]["missing_symbol_sessions"]), 1)

    def test_exact_60_second_boundary_admitted(self):
        material = self.project(lambda request, values: values["pages"][0][0]["quotes"]["SYNTHA"][0].update(t="2026-01-05T14:31:00.000000000Z"))
        self.assertEqual(material["assessment"]["status"], "SUPPORTED")

    def test_same_microsecond_distinct_nanosecond_samples_order_exactly(self):
        def mutate(request, values):
            quotes = values["pages"][0][0]["quotes"]["SYNTHA"]
            row = dict(quotes[0]); row["t"] = "2026-01-05T14:30:00.123456790Z"; quotes.insert(1, row)
        self.assertEqual(self.project(mutate)["assessment"]["eligible_opening_quote_count"], 25)

    def test_same_exact_timestamp_distinct_quote_updates_are_retained_not_deduplicated(self):
        def mutate(request, values):
            rows = values["pages"][0][0]["quotes"]["SYNTHA"]
            row = dict(rows[0]); row["ap"] = 100.2; rows.insert(1, row)
        material = self.project(mutate)
        self.assertEqual(material["assessment"]["native_quote_count"], 25)
        self.assertEqual(material["assessment"]["eligible_opening_quote_count"], 25)
        self.assertGreater(Decimal(material["review"].cost_model["spread_bps"]), Decimal("19"))

    def test_nonadjacent_identical_quote_within_same_timestamp_group_rejects(self):
        def mutate(request, values):
            rows = values["pages"][0][0]["quotes"]["SYNTHA"]
            row = dict(rows[0]); row["ap"] = 100.2
            rows[1:1] = [row, dict(rows[0])]
        self.reject(mutate)

    def test_same_timestamp_distinct_quote_at_page_boundary_is_retained(self):
        def mutate(request, values):
            body, receipt = values["pages"][0]
            first = body["quotes"]["SYNTHA"][0]
            continuation = dict(first); continuation["ap"] = 100.2
            second = {"quotes": {"SYNTHA": [continuation] + body["quotes"]["SYNTHA"][1:],
                                  "SYNTHB": body["quotes"]["SYNTHB"]}, "next_page_token": None}
            body["quotes"] = {"SYNTHA": [first]}; body["next_page_token"] = "next"
            receipt2 = copy.deepcopy(receipt); receipt2["query"]["page_token"] = "next"
            values["pages"].append((second, receipt2))
        self.assertEqual(self.project(mutate)["assessment"]["native_quote_count"], 25)

    def test_duplicates_out_of_order_out_of_query_and_bad_fraction_reject(self):
        for mutation in (lambda request, values: values["pages"][0][0]["quotes"]["SYNTHA"].reverse(),
                         lambda request, values: values["pages"][0][0]["quotes"]["SYNTHA"].insert(1, values["pages"][0][0]["quotes"]["SYNTHA"][0]),
                         lambda request, values: values["pages"][0][0]["quotes"]["SYNTHA"][0].update(t="2026-01-04T14:30:00Z"),
                         lambda request, values: values["pages"][0][0]["quotes"]["SYNTHA"][0].update(t="2026-01-05T14:30:00.1234567890Z")):
            self.reject(mutation)

    def test_spreads_outside_old_model_range_are_measured_and_deferred_not_discarded(self):
        material = self.project(lambda request, values: values["pages"][0][0]["quotes"]["SYNTHA"][0].update(ap=150))
        self.assertGreater(Decimal(material["assessment"]["measurements"][0]["spread_bps_upper_bound"]), Decimal("1000"))
        self.assertIn("SPREAD_BOUND_EXCEEDS_SUPPORTED_MODEL_RANGE", material["assessment"]["reason_codes"])
        self.assertIsNone(material["source"])

    def test_assumption_dataset_universe_scope_coverage_and_clocks_cannot_clear_wrong_data(self):
        for mutation in (lambda request, values: values["assumptions"]["dataset_evidence"].update(sha256="2" * 64),
                         lambda request, values: values["assumptions"].update(universe=["SYNTHA"]),
                         lambda request, values: values["assumptions"].update(evidence_scope="RETAINED_HISTORY_RESEARCH"),
                         lambda request, values: values["assumptions"].update(coverage_end_session_id="wrong"),
                         lambda request, values: values["assumptions"].update(recorded_at="2026-01-22T22:00:00Z"),
                         lambda request, values: values["assumptions"].update(recorded_at="2026-01-22T23:04:00Z")):
            self.reject(mutation)

    def test_fixture_status_cannot_be_claimed_for_real_scope(self):
        material = self.project(lambda request, values: (request.update(evidence_scope="RETAINED_HISTORY_RESEARCH"),
                                                         values["assumptions"].update(evidence_scope="RETAINED_HISTORY_RESEARCH")))
        self.assertEqual(material["source"].basis, "RETAINED_REVIEW_SOURCE")
        self.assertEqual(material["review"].basis, "RETAINED_COST_REVIEW")

    def test_reserved_paths_cannot_shadow_derivative_material(self):
        for path in ("cost-intake/request.v1.json", "cost-intake/source.v1.json", "cost-intake/review.v1.json", "cost-intake/export.v1.json"):
            request, _, blobs = cost_fixture_material()
            request["quote_pages"][0]["receipt_evidence"]["path"] = path
            with self.assertRaises(ContractValidationError): build_cost_intake(request, blobs)

    def test_full_replay_and_idempotent_identity(self):
        material = self.project(); replay = verify_cost_intake(material["export"], material["blobs"])
        self.assertEqual(material["review"].to_bytes(), replay["review"].to_bytes())
        self.assertEqual(material["source"].to_bytes(), replay["source"].to_bytes())
        self.assertEqual(material["export"], self.project()["export"])

    def test_unresolved_replay_is_first_class_and_preserves_capture(self):
        material = self.project(assumptions=False); replay = verify_cost_intake(material["export"], material["blobs"])
        self.assertEqual(replay["assessment"], material["assessment"])
        self.assertIn("quotes/page-000.raw", replay["evidence"])

    def test_rehashed_measurements_source_and_review_cannot_forge_replay(self):
        material = self.project()
        for mutation in (lambda row: row["assessment"]["measurements"][0].update(spread_bps_upper_bound="0"),
                         lambda row: row["assessment"].update(eligible=False),
                         lambda row: row.update(intake_id="forged"), lambda row: row.update(extra=True)):
            changed = copy.deepcopy(material["export"]); mutation(changed)
            with self.assertRaises(ContractValidationError): verify_cost_intake(changed, material["blobs"])

    def test_original_raw_native_tampering_cannot_be_hidden_by_rehashed_export(self):
        material = self.project(); blobs = dict(material["blobs"])
        ref = material["request"].quote_pages[0]["body_evidence"]
        blobs[ref["sha256"]] = blobs[ref["sha256"]].replace(b'"ap": 100.1', b'"ap": 100.9')
        with self.assertRaises(ContractValidationError): verify_cost_intake(material["export"], blobs)

    def test_supported_source_and_review_retain_immutable_request_assumption_origins(self):
        material = self.project()
        paths = {ref["path"] for ref in material["source"].origin_evidence}
        self.assertTrue({"cost-intake/request.v1.json", "quotes/page-000.raw", "quotes/page-000-receipt.json",
                         "cost-review/assumptions.v1.json", "cost-review/assumptions.raw"}.issubset(paths))
        source_raw = material["source"].to_bytes(); material["source"].observations.clear()
        self.assertEqual(material["source"].to_bytes(), source_raw)

    def test_repeated_recording_timestamps_are_bound_and_change_identity(self):
        original = self.project()
        changed = self.project(lambda request, values: request.update(recorded_at="2026-01-22T23:03:01Z"))
        self.assertNotEqual(original["export"]["intake_id"], changed["export"]["intake_id"])

    def test_no_provider_execution_process_or_legacy_strategy_calls(self):
        with patch("socket.socket", side_effect=AssertionError("network")), patch("subprocess.Popen", side_effect=AssertionError("process")):
            material = self.project()
            self.assertTrue(material["assessment"]["eligible"])
        self.assertFalse(material["review"].auto_trading_enabled)
        self.assertFalse(any(material["source"].authority.values()))


if __name__ == "__main__":
    unittest.main()
