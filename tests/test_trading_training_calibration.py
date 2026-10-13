"""Training qualification fixtures contain no security performance claims."""
import ast
import copy
from datetime import timedelta
from decimal import Decimal, Inexact, Rounded, localcontext
import inspect
import json
import socket
import unittest
from unittest.mock import patch

from blackpod_build_week import trading_training_calibration as engine
from blackpod_build_week.contracts.mission_request import ContractValidationError, format_rfc3339, parse_rfc3339
from blackpod_build_week.contracts.trading_evidence_qualification import TradingEvidenceQualificationPolicy
from blackpod_build_week.contracts.trading_research import TradingResearchPlan
from blackpod_build_week.hashing import canonical_json_bytes, sha256_bytes
from blackpod_build_week.trading_shadow_review_example import fixture_material as frozen_fixture_material


def _ref(path, body):
    return {"path": path, "sha256": sha256_bytes(body), "size_bytes": len(body)}


def refresh_training_fixture(policy, values, blobs):
    policy, values, blobs = copy.deepcopy(policy), copy.deepcopy(values), dict(blobs)
    chains = []
    for fold_id, pages in values["chains"]:
        refs = []
        for index, (body, receipt) in enumerate(pages):
            raw = body if isinstance(body, bytes) else canonical_json_bytes(body)
            receipt["body_sha256"], receipt["size_bytes"] = sha256_bytes(raw), len(raw)
            receipt_raw = canonical_json_bytes(receipt)
            body_ref = _ref("training-fixture/%s-page-%03d.raw" % (fold_id, index), raw)
            receipt_ref = _ref("training-fixture/%s-page-%03d-receipt.json" % (fold_id, index), receipt_raw)
            refs.append({"body_evidence": body_ref, "receipt_evidence": receipt_ref})
            blobs[body_ref["sha256"]], blobs[receipt_ref["sha256"]] = raw, receipt_raw
        chains.append({"fold_id": fold_id, "pages": refs})
    policy["training_quote_chains"] = chains
    policy["training_cost_assumptions_evidence"] = None
    if values["assumptions"] is not None:
        origin = values["assumption_origin"]
        origin_ref = _ref("training-fixture/cost-capacity-assumptions-origin.raw", origin)
        values["assumptions"]["origin_evidence"] = [origin_ref]
        raw = canonical_json_bytes(values["assumptions"])
        policy["training_cost_assumptions_evidence"] = _ref("training-fixture/cost-capacity-assumptions.v1.json", raw)
        blobs[sha256_bytes(raw)], blobs[origin_ref["sha256"]] = raw, origin
    return policy, values, blobs


def training_calibration_fixture():
    """Slice training observations from unchanged, already authored old quotes.

    The new receipt is explicitly authored verification material. The original
    raw responses, plans, hypotheses and native journal events are unchanged.
    """
    material = frozen_fixture_material()
    row, data = material["studies"][0], material["dataset"]
    plan, train = row["plan"], row["plan"].protocol["folds"][0]["train"]
    opens = {session["open_at"] for session in data.sessions[train["start_index"]:train["end_index"] + 1]}
    original = json.loads(material["evidence"]["synthetic-reviewed/quotes.raw"])
    quotes = {symbol: [item for item in native if format_rfc3339(parse_rfc3339(item["t"], "fixture quote") - timedelta(seconds=1)) in opens]
              for symbol, native in original["quotes"].items()}
    body = {"quotes": quotes, "next_page_token": None}
    receipt = {"schema_version": "blackpod.trading_evidence_capture.v1", "method": "GET", "url": engine.QUOTES_URL,
        "query": {"symbols": ",".join(data.universe), "start": data.sessions[train["start_index"]]["open_at"],
            "end": format_rfc3339(parse_rfc3339(data.sessions[train["end_index"]]["open_at"], "training open") + timedelta(seconds=60)),
            "limit": 10000, "feed": "iex", "currency": "USD", "sort": "asc", "asof": "-"},
        "captured_at": "2025-04-01T11:30:00Z", "status": 200, "body_sha256": "0" * 64, "size_bytes": 0}
    policy = {"schema_version": "blackpod.trading_evidence_qualification_policy.v1", "policy_id": "synthetic-training-qualification",
        "recorded_at": "2025-04-01T16:00:00Z", "domain": "TRADING", "mode": "SHADOW_RESEARCH",
        "scope": "DEVELOPMENT_EVIDENCE_QUALIFICATION_ONLY", "status": "REVIEWED_FOR_SHADOW_QUALIFICATION",
        "base_plan_event_id": row["plan_event"].event_id,
        "base_plan_evidence": row["risk_review"].base_plan_evidence, "dataset_evidence": plan.dataset_evidence,
        "hypothesis_evidence": plan.frozen_hypothesis_evidence,
        "continuity_event_id": None, "cost_event_id": None, "risk_review_event_id": None,
        "training_quote_chains": [], "training_cost_assumptions_evidence": None,
        "evidence_scope": "SYNTHETIC_FIXTURE_ONLY", "continuity_policy": "RAW_PRICE_BOUNDARY_SUSPENSION_NO_ADJUSTMENT",
        "cost_policy": "PER_FOLD_TRAIN_ONLY_MAX_SPREAD_NO_CLIPPING", "uncertainty_protocol": None,
        "supporting_evidence": row["risk_review"].source_evidence, "reviewer_id": "synthetic-fixture-author",
        "review_notes": "Authored training-only verification declaration, not a trading policy or a market-capacity claim.",
        "supersedes_policy_event_id": None, "auto_trading_enabled": False, "authority": plan.authority}
    assumptions = {"schema_version": "blackpod.trading_training_assumptions.v1", "assumptions_id": "synthetic-training-cost-capacity",
        "recorded_at": "2025-04-01T15:00:00Z", "base_plan_evidence": policy["base_plan_evidence"],
        "dataset_evidence": plan.dataset_evidence, "evidence_scope": "SYNTHETIC_FIXTURE_ONLY",
        "status": "REVIEWED_FOR_SHADOW_QUALIFICATION", "parameters": material["assumptions"].parameters,
        "capacity": {"max_daily_volume_participation_fraction": plan.risk["max_volume_participation_fraction"]},
        "origin_evidence": [], "reviewer_id": "synthetic-fixture-author",
        "review_notes": "Reuse the unchanged prior fixture's toy fees/slippage and volume fraction as explicit declarations, not measurements.",
        "auto_trading_enabled": False, "authority": plan.authority}
    values = {"chains": [(plan.protocol["folds"][0]["fold_id"], [(body, receipt)])], "assumptions": assumptions,
              "assumption_origin": b"Authored training assumptions: unchanged toy fee/slippage and daily volume participation. No execution capacity is observed.\n"}
    policy, values, blobs = refresh_training_fixture(policy, values, material["blobs"])
    return policy, plan, data, values, blobs


class TrainingCalibrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.frozen = training_calibration_fixture()

    def setUp(self):
        self.enterContext(patch.object(socket.socket, "connect", side_effect=AssertionError("network forbidden")))
        self.enterContext(patch("subprocess.Popen", side_effect=AssertionError("worker forbidden")))
        self.enterContext(patch("subprocess.run", side_effect=AssertionError("provider forbidden")))
        policy, self.plan, self.data, values, blobs = self.frozen
        self.policy, self.values, self.blobs = copy.deepcopy(policy), copy.deepcopy(values), dict(blobs)

    def refresh(self):
        self.policy, self.values, self.blobs = refresh_training_fixture(self.policy, self.values, self.blobs)

    def assess(self):
        return engine.calibrate_training_evidence(self.policy, self.plan, self.data, self.blobs)

    def fold(self):
        return self.assess()["assessment"]["folds"][0]

    def page(self):
        return self.values["chains"][0][1][0]

    def test_full_training_coverage_preserves_measured_costs_and_declared_assumptions(self):
        assessment = self.assess()["assessment"]
        self.assertTrue(assessment["eligible"])
        fold = assessment["folds"][0]
        self.assertEqual(fold["missing_symbol_sessions"], [])
        self.assertEqual(fold["cost_model"]["slippage_bps"], "5")
        self.assertEqual(fold["cost_model"]["fee_per_fill"], "0.10")
        self.assertEqual([row["multiplier"] for row in fold["cost_stress_assessment"]], ["1", "2", "4"])
        self.assertFalse(assessment["cost_applicability_verified"])
        self.assertFalse(assessment["opening_execution_capacity_verified"])

    def test_capacity_proxy_uses_training_volume_and_reviewed_fraction_only(self):
        fold = self.fold()
        train = self.plan.protocol["folds"][0]["train"]
        for row in fold["capacity_proxy"]:
            volumes = [Decimal(next(bar["volume"] for bar in session["bars"] if bar["symbol"] == row["symbol"]))
                       for session in self.data.sessions[train["start_index"]:train["end_index"] + 1]]
            self.assertEqual(Decimal(row["minimum_training_daily_volume"]), min(volumes))
            self.assertEqual(Decimal(row["maximum_training_daily_volume"]), max(volumes))
            self.assertEqual(Decimal(row["daily_quantity_research_proxy"]), min(volumes) * Decimal("0.01"))
            self.assertIn("NOT_OPENING_FILL_CAPACITY", row["semantics"])

    def test_no_quote_chain_defers_without_zerocost_invention(self):
        self.values["chains"] = []; self.refresh()
        fold = self.fold()
        self.assertFalse(fold["eligible"])
        self.assertIn("TRAINING_QUOTE_CHAIN_MISSING", fold["reason_codes"])
        self.assertEqual(len(fold["missing_symbol_sessions"]), len(self.data.universe) * (fold["training_range"]["end_index"] + 1))
        self.assertIsNone(fold["cost_model"])

    def test_explicit_empty_fold_chain_is_auditable_deferral(self):
        self.values["chains"][0] = (self.values["chains"][0][0], []); self.refresh()
        self.assertIn("TRAINING_QUOTE_CHAIN_MISSING", self.fold()["reason_codes"])

    def test_missing_assumptions_does_not_invent_slippage_fees_or_capacity(self):
        self.values["assumptions"] = None; self.refresh()
        fold = self.fold()
        self.assertIn("TRAINING_COST_AND_CAPACITY_ASSUMPTIONS_MISSING", fold["reason_codes"])
        self.assertIsNone(fold["cost_model"])
        self.assertTrue(all(row["daily_quantity_research_proxy"] is None for row in fold["capacity_proxy"]))

    def test_unresolved_assumptions_never_become_reviewed_capacity(self):
        self.values["assumptions"]["status"] = "UNRESOLVED"; self.refresh()
        fold = self.fold()
        self.assertIn("TRAINING_ASSUMPTIONS_NOT_REVIEWED", fold["reason_codes"])
        self.assertIsNone(fold["cost_model"])
        self.assertTrue(all(row["reviewed_daily_volume_participation_fraction"] is None for row in fold["capacity_proxy"]))

    def test_missing_one_symbol_session_is_not_extrapolated(self):
        body, _ = self.page(); body["quotes"][self.data.universe[0]].pop(); self.refresh()
        fold = self.fold()
        self.assertEqual(len(fold["missing_symbol_sessions"]), 1)
        self.assertIsNone(fold["cost_model"])
        self.assertIsNotNone(fold["training_measurements"][0]["max_spread_bps"])

    def test_validation_test_and_holdout_queries_are_retained_but_excluded(self):
        for role in ("validation", "test", "final_holdout"):
            with self.subTest(role=role):
                _, _, _, original_values, original_blobs = self.frozen
                self.values, self.blobs = copy.deepcopy(original_values), dict(original_blobs)
                interval = self.plan.protocol[role] if role == "final_holdout" else self.plan.protocol["folds"][0][role]
                session = self.data.sessions[interval["start_index"]]
                body, receipt = self.page()
                receipt["query"].update(start=session["open_at"], end=format_rfc3339(parse_rfc3339(session["open_at"], "test open") + timedelta(seconds=60)))
                body["quotes"] = {symbol: [{**native[0], "t": format_rfc3339(parse_rfc3339(session["open_at"], "open") + timedelta(seconds=1))}]
                                  for symbol, native in body["quotes"].items()}
                self.refresh(); report = self.assess(); fold = report["assessment"]["folds"][0]
                self.assertTrue(fold["quote_evidence_contaminated"])
                self.assertIn("NONTRAINING_QUOTE_EVIDENCE_REJECTED", fold["reason_codes"])
                self.assertIsNone(fold["training_measurements"])
                self.assertIsNone(fold["cost_model"])
                self.assertEqual(fold["cost_stress_assessment"], [])
                page = self.policy["training_quote_chains"][0]["pages"][0]
                self.assertIn(page["body_evidence"]["path"], report["evidence"])

    def test_broad_query_including_holdout_cannot_be_trimmed_to_training_rows(self):
        _, receipt = self.page(); receipt["query"]["end"] = self.data.sessions[-1]["open_at"]
        self.refresh(); fold = self.fold()
        self.assertTrue(fold["quote_evidence_contaminated"])
        self.assertIsNone(fold["training_measurements"])

    def test_exact_60_second_boundary_admitted_one_ns_later_not_admitted(self):
        symbol = self.data.universe[0]
        body, _ = self.page()
        opening = self.data.sessions[0]["open_at"]
        body["quotes"][symbol][0]["t"] = format_rfc3339(parse_rfc3339(opening, "open") + timedelta(seconds=60))
        self.refresh(); self.assertTrue(self.fold()["eligible"])
        body, _ = self.page(); body["quotes"][symbol][0]["t"] = body["quotes"][symbol][0]["t"].replace("Z", ".000000001Z")
        self.refresh(); self.assertEqual(len(self.fold()["missing_symbol_sessions"]), 1)

    def test_same_nanosecond_distinct_updates_preserved_identical_duplicate_rejects(self):
        body, _ = self.page(); rows = body["quotes"][self.data.universe[0]]
        rows.insert(1, {**rows[0], "as": rows[0]["as"] + 1})
        self.refresh(); self.assertTrue(self.fold()["eligible"])
        body, _ = self.page(); rows = body["quotes"][self.data.universe[0]]; rows.insert(2, copy.deepcopy(rows[0]))
        self.refresh()
        with self.assertRaisesRegex(ValueError, "duplicate"):
            self.assess()

    def test_maximum_spread_retains_every_eligible_observation_and_no_clipping(self):
        body, _ = self.page(); body["quotes"][self.data.universe[0]][0]["ap"] = 11
        self.refresh(); fold = self.fold()
        self.assertGreater(Decimal(fold["training_measurements"][0]["max_spread_bps"]), Decimal("600"))
        self.assertIn("TRAINING_COST_STRESS_EXCEEDS_EXISTING_MODEL_BOUND", fold["reason_codes"])
        self.assertIsNone(fold["cost_model"])
        self.assertGreater(Decimal(fold["cost_stress_assessment"][-1]["declared_cost_model"]["spread_bps"]), Decimal("1000"))

    def test_spread_ceil18_places_and_arithmetic_context_independent(self):
        before = self.assess()
        row = before["assessment"]["folds"][0]["training_measurements"][0]
        body, _ = self.page()
        expected = max(Decimal(str(q["ap"])) - Decimal(str(q["bp"])) for q in body["quotes"][row["symbol"]])
        self.assertGreater(expected, 0)
        self.assertLessEqual(len(row["max_spread_bps"].split(".")[-1]), 18)
        with localcontext() as context:
            context.prec = 7; context.traps[Inexact] = context.traps[Rounded] = True
            self.assertEqual(before, self.assess())

    def test_cost_stress_scales_all_declared_components(self):
        fold = self.fold()
        for stress in fold["cost_stress_assessment"]:
            for field, value in fold["cost_model"].items():
                self.assertEqual(Decimal(stress["declared_cost_model"][field]), Decimal(value) * Decimal(stress["multiplier"]))

    def test_partial_forward_token_defers_without_repair(self):
        body, _ = self.page(); body["next_page_token"] = "unfinished"; self.refresh()
        fold = self.fold()
        self.assertIn("TRAINING_QUOTE_PAGINATION_INCOMPLETE", fold["reason_codes"])
        self.assertIsNone(fold["cost_model"])

    def test_complete_forward_chain_binds_native_tokens_and_base_query(self):
        body, receipt = self.page(); symbol = self.data.universe[0]
        first = {"quotes": {symbol: body["quotes"][symbol]}, "next_page_token": "second"}
        second = {"quotes": {self.data.universe[1]: body["quotes"][self.data.universe[1]]}, "next_page_token": None}
        second_receipt = copy.deepcopy(receipt); second_receipt["query"]["page_token"] = "second"
        self.values["chains"][0] = (self.values["chains"][0][0], [(first, receipt), (second, second_receipt)])
        self.refresh(); self.assertTrue(self.fold()["eligible"])
        self.values["chains"][0][1][1][1]["query"]["page_token"] = "forged"; self.refresh()
        with self.assertRaisesRegex(ValueError, "pagination"):
            self.assess()

    def test_http_unavailable_is_deferral_not_empty_measured_bound(self):
        body, receipt = self.page(); receipt["status"] = 403
        self.values["chains"][0][1][0] = (b'{"message":"unavailable"}', receipt)
        self.refresh(); fold = self.fold()
        self.assertIn("TRAINING_QUOTE_RESPONSE_UNAVAILABLE", fold["reason_codes"])
        self.assertIsNone(fold["cost_model"])

    def test_hash_size_receipt_body_endpoint_query_and_clocks_reject(self):
        for mutate in (lambda row: row["training_quote_chains"][0]["pages"][0]["body_evidence"].update(sha256="a" * 64),
                       lambda row: row["training_quote_chains"][0]["pages"][0]["body_evidence"].update(size_bytes=1),
                       lambda row: row.update(dataset_evidence={**row["dataset_evidence"], "path": "wrong/dataset.json"}),
                       lambda row: row.update(hypothesis_evidence={**row["hypothesis_evidence"], "sha256": "a" * 64})):
            with self.subTest(mutate=mutate):
                policy = copy.deepcopy(self.policy); mutate(policy)
                with self.assertRaises(ValueError): engine.calibrate_training_evidence(policy, self.plan, self.data, self.blobs)
        _, receipt = self.page(); receipt["captured_at"] = "2025-04-01T17:00:00Z"; self.refresh()
        with self.assertRaisesRegex(ValueError, "capture"):
            self.assess()

    def test_wrong_assumption_scope_binding_or_clock_cannot_clear(self):
        for mutate in (lambda row: row.update(evidence_scope="RETAINED_HISTORY_RESEARCH"),
                       lambda row: row.update(recorded_at="2025-04-01T17:00:00Z"),
                       lambda row: row.update(dataset_evidence={**row["dataset_evidence"], "sha256": "a" * 64})):
            with self.subTest(mutate=mutate):
                _, _, _, values, blobs = self.frozen
                self.values, self.blobs = copy.deepcopy(values), dict(blobs)
                mutate(self.values["assumptions"]); self.refresh()
                with self.assertRaises(ValueError): self.assess()

    def test_native_numbers_and_extra_fields_cannot_be_repaired(self):
        for mutate in (lambda row: row.update(bp="10"), lambda row: row.update(bs=True),
                       lambda row: row.update(bs=1.5), lambda row: row.update(ap=-1),
                       lambda row: row.update(unexpected="field")):
            with self.subTest(mutate=mutate):
                _, _, _, values, blobs = self.frozen
                self.values, self.blobs = copy.deepcopy(values), dict(blobs)
                mutate(self.page()[0]["quotes"][self.data.universe[0]][0]); self.refresh()
                with self.assertRaises(ValueError): self.assess()

    def test_inadmissible_regular_quotes_do_not_satisfy_training_coverage(self):
        for mutate in (lambda row: row.update(bs=0), lambda row: row.update(c=["C"]), lambda row: row.update(ap=1)):
            with self.subTest(mutate=mutate):
                _, _, _, values, blobs = self.frozen
                self.values, self.blobs = copy.deepcopy(values), dict(blobs)
                mutate(self.page()[0]["quotes"][self.data.universe[0]][0]); self.refresh()
                fold = self.fold()
                self.assertEqual(len(fold["missing_symbol_sessions"]), 1)
                self.assertIsNone(fold["cost_model"])

    def test_unknown_fold_cannot_supply_coverage(self):
        self.values["chains"][0] = ("unknown-fold", self.values["chains"][0][1]); self.refresh()
        with self.assertRaisesRegex(ValueError, "unknown original fold"):
            self.assess()

    def test_prior_test_and_validation_cannot_silently_become_later_training_data(self):
        # This new unit-only declaration tests the conservative partition rule;
        # it neither rewrites the frozen example nor evaluates any new return.
        value = self.plan.to_dict()
        value["plan_id"] = "synthetic-overlapping-training-plan"
        value["protocol"]["folds"][0]["test"]["end_index"] = 24
        value["protocol"]["folds"].append({"fold_id": "later-fold", "train": {"start_index": 0, "end_index": 24},
            "validation": {"start_index": 28, "end_index": 28}, "test": {"start_index": 32, "end_index": 34}})
        self.plan = TradingResearchPlan.from_mapping(value)
        self.policy["base_plan_evidence"] = _ref("training-fixture/overlapping-plan.v2.json", self.plan.to_bytes())
        self.values["assumptions"]["base_plan_evidence"] = self.policy["base_plan_evidence"]
        self.values["chains"].append(("later-fold", [])); self.refresh()
        report = self.assess()["assessment"]
        first, second = report["folds"]
        self.assertTrue(first["eligible"])
        self.assertIn("TRAIN_INTERVAL_OVERLAPS_HELD_OUT_PARTITION", second["reason_codes"])
        self.assertEqual(second["excluded_global_held_out_indices"], list(range(15, 20)) + [23, 24])
        self.assertIsNone(second["cost_model"])
        self.assertIsNone(second["training_measurements"])
        self.assertIsNone(second["capacity_proxy"])

    def test_extra_native_keys_duplicates_nonfinite_json_are_rejected(self):
        _, receipt = self.page()
        for body in (b'{"quotes":{},"quotes":{},"next_page_token":null}',
                     b'{"quotes":{},"next_page_token":NaN}',
                     b'{"quotes":{},"next_page_token":null,"extra":true}'):
            with self.subTest(body=body):
                self.values["chains"][0][1][0] = (body, receipt)
                self.refresh()
                with self.assertRaises(ValueError): self.assess()

    def test_query_identity_and_endpoint_cannot_be_changed(self):
        for mutate in (lambda receipt: receipt.update(url="https://data.alpaca.markets/v1/corporate-actions"),
                       lambda receipt: receipt["query"].update(feed="sip"),
                       lambda receipt: receipt["query"].update(asof="2025-01-01"),
                       lambda receipt: receipt["query"].update(limit=True),
                       lambda receipt: receipt["query"].update(page_token="orphaned-page")):
            with self.subTest(mutate=mutate):
                _, _, _, values, blobs = self.frozen
                self.values, self.blobs = copy.deepcopy(values), dict(blobs)
                mutate(self.page()[1]); self.refresh()
                with self.assertRaises(ValueError): self.assess()

    def test_sources_and_original_plan_remain_immutable_and_retry_deterministic(self):
        before = (copy.deepcopy(self.policy), self.plan.to_bytes(), self.data.to_bytes(), dict(self.blobs))
        first = self.assess(); second = self.assess()
        self.assertEqual(first, second)
        self.assertEqual(before, (self.policy, self.plan.to_bytes(), self.data.to_bytes(), self.blobs))
        first["assessment"]["folds"].clear(); first["evidence"].clear()
        self.assertEqual(second, self.assess())

    def test_authority_pit_and_execution_capacity_never_acquired(self):
        assessment = self.assess()["assessment"]
        for field in ("auto_trading_enabled", "historical_point_in_time_verified", "source_authentication_verified",
                      "cost_applicability_verified", "opening_execution_capacity_verified", "holdout_scored", "strategy_tuning_performed"):
            self.assertIs(assessment[field], False)
        self.assertFalse(any(assessment["authority"].values()))
        self.assertNotIn("returns", assessment)

    def test_imports_no_provider_execution_or_legacy_strategy(self):
        tree = ast.parse(inspect.getsource(engine))
        imports = [node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)]
        imports += [alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names]
        for forbidden in ("galactica", "alpaca", "navigator", "modeldock", "subprocess", "socket", "auto_trading"):
            self.assertFalse(any(forbidden in item.lower() for item in imports), forbidden)


if __name__ == "__main__":
    unittest.main()
