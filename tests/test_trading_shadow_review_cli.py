"""Safe offline commands, typed closure and opaque native/origin evidence."""
from __future__ import annotations

import contextlib
import copy
import io
import json
from pathlib import Path
import socket
import tempfile
import unittest
from unittest.mock import patch

from blackpod_build_week.contracts.trading_continuity_intake import ContinuityIntakeRequest
from blackpod_build_week.contracts.trading_cost_intake import CostIntakeRequest
from blackpod_build_week.hashing import canonical_json_bytes, sha256_bytes
from blackpod_build_week.decision_journal_store import JournalStoreError
from blackpod_build_week.decision_journal_store import JournalStore
from blackpod_build_week.contracts.trading_shadow_review import ReviewedShadowStudy
from blackpod_build_week.contracts.trading_shadow_risk_review import RISK_REVIEW_LIMITATIONS
from blackpod_build_week.trading_continuity_intake import build_continuity_intake, verify_continuity_intake
from blackpod_build_week.trading_cost_intake import build_cost_intake, verify_cost_intake
from blackpod_build_week.trading_shadow_review_cli import main, load_reviewed_evidence, build_parser
from blackpod_build_week.trading_shadow_example import fixture_material as foundation_fixture
from test_trading_continuity_intake import continuity_fixture, refresh_continuity, reference
from test_trading_cost_intake import cost_fixture_material


class TradingShadowReviewCLITests(unittest.TestCase):
    def setUp(self):
        self.enterContext(patch.object(socket.socket, "connect", side_effect=AssertionError("network forbidden")))
        self.enterContext(patch("subprocess.Popen", side_effect=AssertionError("process forbidden")))
        self.enterContext(patch("subprocess.run", side_effect=AssertionError("provider forbidden")))
        temporary = tempfile.TemporaryDirectory(); self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.input, self.sources, self.output = self.root / "input", self.root / "sources", self.root / "output"
        self.input.mkdir(); self.sources.mkdir()

    def write(self, evidence):
        for path, raw in evidence.items():
            target = self.sources / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(raw)

    def fixture(self, kind="CONTINUITY", *, coverage=True, assumptions=True):
        if kind == "CONTINUITY":
            request, _, _, blobs = continuity_fixture(coverage=coverage)
            material = build_continuity_intake(request, blobs)
        else:
            request, _, blobs = cost_fixture_material(assumptions=assumptions)
            material = build_cost_intake(request, blobs)
        self.write(material["evidence"])
        request_path = self.input / (kind.lower() + ".json")
        request_path.write_bytes(material["request"].to_bytes())
        return material, request_path

    def call(self, arguments):
        output, error = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(error):
            status = main(list(map(str, arguments)))
        return status, json.loads(output.getvalue()) if output.getvalue() else None, error.getvalue()

    def export(self, kind="CONTINUITY", **options):
        material, request_path = self.fixture(kind, **options)
        status, result, error = self.call(["export-" + kind.lower(), "--request", request_path,
                                          "--evidence-root", self.sources, "--output-directory", self.output])
        return material, status, result, error

    def test_both_exporters_run_without_network_brokers_or_inference(self):
        for kind in ("CONTINUITY", "COST"):
            with self.subTest(kind=kind):
                self.output = self.root / ("output-" + kind.lower())
                material, status, result, error = self.export(kind)
                self.assertEqual(status, 0, error)
                self.assertEqual(result["intake_id"], material["export"].intake_id if kind == "CONTINUITY" else material["export"]["intake_id"])
                self.assertEqual(result["orders_submitted"], 0)
                self.assertEqual(result["provider_calls"], 0)
                self.assertFalse(result["auto_trading_changed"])

    def test_export_publishes_full_source_closure_and_array_calendar_opaque(self):
        material, status, result, error = self.export()
        self.assertEqual(status, 0, error)
        for path, raw in material["evidence"].items():
            self.assertEqual((self.output / path).read_bytes(), raw)
        calendar_ref = material["dataset"].provenance["source_evidence"][3]
        self.assertEqual((self.output / calendar_ref["path"]).read_bytes(), material["blobs"][calendar_ref["sha256"]])
        self.assertTrue(Path(result["export_path"]).exists())

    def test_exported_continuity_replays_from_published_files_without_original_sources(self):
        material, status, result, error = self.export()
        self.assertEqual(status, 0, error)
        exported = json.loads(Path(result["export_path"]).read_bytes())
        blobs = load_reviewed_evidence(self.output, exported)
        replay = verify_continuity_intake(exported, blobs)
        self.assertEqual(replay["export"].to_bytes(), material["export"].to_bytes())

    def test_exported_cost_replays_from_published_files_without_original_sources(self):
        material, status, result, error = self.export("COST")
        self.assertEqual(status, 0, error)
        exported = json.loads(Path(result["export_path"]).read_bytes())
        blobs = load_reviewed_evidence(self.output, exported)
        self.assertEqual(verify_cost_intake(exported, blobs)["export"], material["export"])

    def test_unreviewed_continuity_is_not_promoted_to_effective_date_coverage(self):
        _, status, result, error = self.export(coverage=False)
        self.assertEqual(status, 0, error)
        exported = json.loads(Path(result["export_path"]).read_bytes())
        self.assertFalse(exported["coverage_review_supported"])
        self.assertTrue(exported["pagination_complete"])
        self.assertEqual(exported["derived_event_count"], 0)

    def test_missing_cost_assumptions_remain_unresolved_with_no_invented_cost_model(self):
        _, status, result, error = self.export("COST", assumptions=False)
        self.assertEqual(status, 0, error)
        self.assertEqual(result["status"], "UNRESOLVED")
        exported = json.loads(Path(result["export_path"]).read_bytes())
        self.assertIsNone(exported["source_evidence"])
        self.assertIn("EXPLICIT_COST_ASSUMPTIONS_MISSING", exported["assessment"]["reason_codes"])

    def test_exact_export_retry_is_immutable_and_deterministic(self):
        material, request_path = self.fixture()
        args = ["export-continuity", "--request", request_path, "--evidence-root", self.sources, "--output-directory", self.output]
        first = self.call(args); second = self.call(args)
        self.assertEqual(first[0], 0, first[2]); self.assertEqual(first, second)
        for path, raw in material["evidence"].items():
            self.assertEqual((self.output / path).read_bytes(), raw)

    def test_export_conflict_never_overwrites_existing_artifact(self):
        material, request_path = self.fixture()
        target = self.output / "historical-intake/request.v1.json"
        target.parent.mkdir(parents=True); target.write_bytes(b"original protected bytes")
        status, _, error = self.call(["export-continuity", "--request", request_path, "--evidence-root", self.sources, "--output-directory", self.output])
        self.assertEqual(status, 2)
        self.assertTrue(error)
        self.assertEqual(target.read_bytes(), b"original protected bytes")

    def test_export_output_cannot_overlap_source_root(self):
        _, request_path = self.fixture()
        status, _, error = self.call(["export-continuity", "--request", request_path,
                                      "--evidence-root", self.sources, "--output-directory", self.sources / "new"])
        self.assertEqual(status, 2)
        self.assertTrue(error)
        self.assertFalse((self.sources / "new").exists())

    def test_export_output_cannot_overlap_request_root(self):
        _, request_path = self.fixture()
        status, _, error = self.call(["export-continuity", "--request", request_path,
                                      "--evidence-root", self.sources, "--output-directory", self.input / "new"])
        self.assertEqual(status, 2)
        self.assertTrue(error)
        self.assertFalse((self.input / "new").exists())

    def test_request_symlink_is_rejected_before_writes(self):
        _, request_path = self.fixture()
        linked = self.input / "link.json"; linked.symlink_to(request_path)
        status, _, _ = self.call(["export-continuity", "--request", linked, "--evidence-root", self.sources, "--output-directory", self.output])
        self.assertEqual(status, 2)
        self.assertFalse(self.output.exists())

    def test_source_symlink_is_rejected_before_writes(self):
        material, request_path = self.fixture()
        ref = material["request"].pages[0]["response_evidence"]
        source = self.sources / ref["path"]
        other = self.input / "source.raw"; other.write_bytes(source.read_bytes())
        source.unlink(); source.symlink_to(other)
        status, _, _ = self.call(["export-continuity", "--request", request_path, "--evidence-root", self.sources, "--output-directory", self.output])
        self.assertEqual(status, 2)
        self.assertFalse(self.output.exists())

    def test_invalid_request_rejects_before_any_publication(self):
        _, request_path = self.fixture()
        value = json.loads(request_path.read_bytes()); value["authority"]["execution_enabled"] = True
        request_path.write_bytes(canonical_json_bytes(value))
        status, _, error = self.call(["export-continuity", "--request", request_path, "--evidence-root", self.sources, "--output-directory", self.output])
        self.assertEqual(status, 2)
        self.assertIn("disabled", error)
        self.assertFalse(self.output.exists())

    def test_native_source_hash_mismatch_rejects_before_publication(self):
        material, request_path = self.fixture()
        ref = material["request"].pages[0]["response_evidence"]
        (self.sources / ref["path"]).write_bytes(b"tampered")
        status, _, error = self.call(["export-continuity", "--request", request_path, "--evidence-root", self.sources, "--output-directory", self.output])
        self.assertEqual(status, 2)
        self.assertIn("hash or size", error)
        self.assertFalse(self.output.exists())

    def test_loader_accepts_typed_requests_and_reconstructs_historical_closure(self):
        for kind, cls in (("CONTINUITY", ContinuityIntakeRequest), ("COST", CostIntakeRequest)):
            material, _ = self.fixture(kind)
            loaded = load_reviewed_evidence(self.sources, cls.from_mapping(material["request"].to_mapping()))
            for ref in material["dataset"].provenance["source_evidence"] if "dataset" in material else []:
                self.assertIn(ref["sha256"], loaded)

    def test_loader_following_cost_request_retains_explicit_assumption_origin(self):
        material, _ = self.fixture("COST")
        loaded = load_reviewed_evidence(self.sources, material["request"])
        review_ref = material["request"].assumption_review_evidence
        review = json.loads(loaded[review_ref["sha256"]])
        for ref in review["origin_evidence"]:
            self.assertEqual(loaded[ref["sha256"]], material["blobs"][ref["sha256"]])

    def test_loader_does_not_parse_or_follow_references_inside_opaque_origin_json(self):
        request, values, evidence, _ = continuity_fixture(coverage=True)
        opaque = canonical_json_bytes({"fake_reference": {"path": "secrets/never-read", "sha256": "a" * 64, "size_bytes": 1}})
        ref = reference("fixture/origin.json", opaque)
        evidence[ref["path"]] = opaque
        values["coverage"]["source_evidence"] = [ref]
        request, values, evidence, _ = refresh_continuity(request, values, evidence)
        self.write(evidence)
        loaded = load_reviewed_evidence(self.sources, request)
        self.assertEqual(loaded[ref["sha256"]], opaque)
        self.assertNotIn("a" * 64, loaded)

    def test_loader_accepts_opaque_json_array_origin_without_object_parsing(self):
        request, values, evidence, _ = continuity_fixture(coverage=True)
        opaque = b'["local evidence", {"not_a_declaration": true}]\n'
        ref = reference("fixture/origin-array.json", opaque)
        evidence[ref["path"]] = opaque
        values["coverage"]["source_evidence"] = [ref]
        request, values, evidence, _ = refresh_continuity(request, values, evidence)
        self.write(evidence)
        loaded = load_reviewed_evidence(self.sources, request)
        self.assertEqual(loaded[ref["sha256"]], opaque)

    def test_loader_retained_bytes_do_not_require_source_files(self):
        material, _ = self.fixture()
        with patch("blackpod_build_week.trading_research_intake_cli.read_regular", side_effect=AssertionError("filesystem read forbidden")):
            loaded = load_reviewed_evidence(self.root / "missing", material["request"], material["blobs"])
        self.assertEqual(loaded, material["blobs"])

    def test_loader_reference_list_is_opaque_leaf_compatibility_api(self):
        raw = b'[1, 2, {"schema_version": "not interpreted"}]'
        ref = reference("provider/array.json", raw)
        self.write({ref["path"]: raw})
        self.assertEqual(load_reviewed_evidence(self.sources, [ref]), {ref["sha256"]: raw})

    def test_loader_rejects_unsupported_declaration(self):
        with self.assertRaises(ValueError): load_reviewed_evidence(self.sources, {"schema_version": "future.v1"})

    def test_loader_rejects_conflicting_path_identities(self):
        a, b = b"a", b"b"
        refs = [reference("same.raw", a), reference("same.raw", b)]
        with self.assertRaises(ValueError):
            load_reviewed_evidence(self.sources, refs, {sha256_bytes(a): a, sha256_bytes(b): b})

    def test_loader_rejects_hash_and_size_mismatch_in_retained_bytes(self):
        raw = b"source"
        ref = reference("safe.raw", raw)
        for supplied in (b"tampered", b"sourcf"):
            with self.assertRaises(ValueError): load_reviewed_evidence(self.sources, [ref], {ref["sha256"]: supplied})

    def test_loader_safe_path_and_symlink_root_checks(self):
        raw = b"source"; ref = reference("../escape.raw", raw)
        with self.assertRaises(ValueError): load_reviewed_evidence(self.sources, [ref], {ref["sha256"]: raw})
        link = self.root / "linked-source-root"; link.symlink_to(self.sources, target_is_directory=True)
        with self.assertRaises(JournalStoreError): load_reviewed_evidence(link, [reference("safe.raw", raw)], {sha256_bytes(raw): raw})

    def test_loader_resource_file_count_bound(self):
        raw = b"a"
        refs = [reference("leaf-" + str(index) + ".raw", raw) for index in range(257)]
        with self.assertRaises(ValueError): load_reviewed_evidence(self.sources, refs, {sha256_bytes(raw): raw})

    def test_loader_resource_total_byte_bound_before_file_read(self):
        ref = {"path": "large.raw", "sha256": "a" * 64, "size_bytes": 64 * 1024 * 1024}
        second = {"path": "one.raw", "sha256": "b" * 64, "size_bytes": 1}
        with patch("blackpod_build_week.trading_shadow_review_cli.load_intake_evidence", return_value={}):
            with self.assertRaises(ValueError): load_reviewed_evidence(self.sources, [ref, second])

    def test_loader_does_not_follow_injected_refs_in_cost_assessment(self):
        material, _ = self.fixture("COST")
        export = copy.deepcopy(material["export"])
        export["assessment"]["untrusted_reference"] = {"path": "secret/no-read", "sha256": "a" * 64, "size_bytes": 1}
        loaded = load_reviewed_evidence(self.sources, export)
        self.assertNotIn("a" * 64, loaded)
        with self.assertRaises(ValueError): verify_cost_intake(export, loaded)

    def test_record_both_adapter_exports_preserves_exact_replay_and_idempotency(self):
        for kind in ("CONTINUITY", "COST"):
            with self.subTest(kind=kind):
                self.output = self.root / ("record-input-" + kind.lower())
                material, status, result, error = self.export(kind)
                self.assertEqual(status, 0, error)
                journal = self.root / ("journal-" + kind.lower())
                arguments = ["record-" + kind.lower(), "--export", result["export_path"], "--evidence-root", self.output,
                             "--journal-root", journal, "--recorded-at", "2026-01-23T02:00:00Z"]
                first, second = self.call(arguments), self.call(arguments)
                self.assertEqual(first[0], 0, first[2]); self.assertEqual(second[0], 0, second[2])
                self.assertTrue(first[1]["written"]); self.assertFalse(second[1]["written"])
                self.assertEqual(first[1]["event_id"], second[1]["event_id"])
                verified = JournalStore(journal).verify()
                self.assertEqual(verified.event_count, 1)
                self.assertEqual(verified.orphan_evidence_count, 0)

    def test_record_export_cannot_overlap_journal_or_forge_measurements(self):
        _, status, result, error = self.export("COST")
        self.assertEqual(status, 0, error)
        target = Path(result["export_path"])
        status, _, _ = self.call(["record-cost", "--export", target, "--evidence-root", self.output,
                                  "--journal-root", self.output / "unsafe-journal", "--recorded-at", "2026-01-23T02:00:00Z"])
        self.assertEqual(status, 2)
        self.assertFalse((self.output / "unsafe-journal").exists())
        export = json.loads(target.read_bytes()); export["assessment"]["native_quote_count"] += 1
        target.write_bytes(canonical_json_bytes(export))
        journal = self.root / "forged-journal"
        status, _, _ = self.call(["record-cost", "--export", target, "--evidence-root", self.output,
                                  "--journal-root", journal, "--recorded-at", "2026-01-23T02:00:00Z"])
        self.assertEqual(status, 2)
        self.assertFalse(journal.exists())

    def test_parser_has_explicit_commands_and_no_activation_toggle(self):
        parser = build_parser()
        options = parser._subparsers._group_actions[0].choices
        self.assertEqual(set(options), {"export-continuity", "export-cost", "record-continuity", "record-cost", "record-risk", "prepare", "register", "evaluate", "record", "verify", "show", "render"})
        for command in options.values():
            flags = {option for action in command._actions for option in action.option_strings}
            self.assertNotIn("--activate", flags)
            self.assertNotIn("--auto-trading", flags)
            self.assertNotIn("--execute", flags)


class ReviewedShadowPipelineCLITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.material = foundation_fixture()

    def setUp(self):
        self.enterContext(patch.object(socket.socket, "connect", side_effect=AssertionError("network forbidden")))
        self.enterContext(patch("subprocess.Popen", side_effect=AssertionError("process forbidden")))
        self.enterContext(patch("subprocess.run", side_effect=AssertionError("provider forbidden")))
        temporary = tempfile.TemporaryDirectory(); self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.journal, self.input, self.evidence = self.root / "journal", self.root / "input", self.root / "evidence"
        self.input.mkdir(); self.evidence.mkdir()
        self.store = JournalStore(self.journal)
        for event, evidence in zip(self.material["events"], self.material["event_evidence"]):
            self.store.append(event, evidence)
        plan = self.material["studies"][0]["plan"]
        plan_ref = self.material["studies"][0]["study"].base_plan_evidence
        brief = b"Fictional explicit simulation review only, with no activated budget.\n"
        ref = reference("review/brief.raw", brief)
        self.review_value = {
            "schema_version": "blackpod.trading_shadow_risk_review.v1", "risk_review_id": "cli-fixture-risk",
            "recorded_at": "2025-04-01T11:30:00Z", "reviewer_id": "synthetic-fixture-author",
            "review_notes": "Explicit unapproved simulation proposal, not optimal sizing or human execution approval.",
            "domain": "TRADING", "mode": "SHADOW_RESEARCH", "scope": "SIMULATION_SIZING_ONLY",
            "status": "PROPOSED", "base_plan_evidence": plan_ref, "evidence_scope": "SYNTHETIC_FIXTURE_ONLY",
            "simulation_risk": {**plan.risk, "initial_cash": "2000", "max_order_notional": "150"},
            "sizing": {"method": "KNOWN_CLOSE_WHOLE_QUANTITY", "per_symbol_notional": "80"},
            "source_evidence": [ref], "limitations": list(RISK_REVIEW_LIMITATIONS),
            "auto_trading_enabled": False, "authority": plan.authority,
        }
        self.review_path = self.input / "risk-review.json"
        self.review_path.write_bytes(canonical_json_bytes(self.review_value))
        evidence = {**self.material["evidence"], ref["path"]: brief}
        for path, raw in evidence.items():
            target = self.evidence / path; target.parent.mkdir(parents=True, exist_ok=True); target.write_bytes(raw)

    def call(self, command, *extra):
        args = [command, "--journal-root", str(self.journal), *map(str, extra)]
        output, error = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(error):
            status = main(args)
        return status, json.loads(output.getvalue()) if output.getvalue() else None, error.getvalue()

    def risk(self):
        status, result, error = self.call("record-risk", "--review", self.review_path, "--evidence-root", self.evidence)
        self.assertEqual(status, 0, error)
        return result

    def prepare(self, *, study_id="cli-reviewed-study", experiment_id="cli-reviewed-experiment", output=None):
        risk = self.risk()
        return self.call("prepare", "--base-plan-event-id", self.material["studies"][0]["plan_event"].event_id,
                         "--risk-review-event-id", risk["event_id"], "--study-id", study_id,
                         "--experiment-id", experiment_id, "--registered-at", "2025-04-01T12:30:00Z",
                         "--output-directory", output or self.root / "prepared")

    def register(self, prepared):
        status, result, error = self.call("register", "--study", prepared["study_path"],
                                          "--evidence-root", Path(prepared["study_path"]).parent.parent)
        self.assertEqual(status, 0, error)
        return result

    def record(self):
        status, prepared, error = self.prepare(); self.assertEqual(status, 0, error)
        self.register(prepared)
        status, result, error = self.call("record", "--study", prepared["study_path"], "--evaluation-id", "cli-reviewed-eval",
                                          "--recorded-at", "2025-04-01T13:30:00Z")
        self.assertEqual(status, 0, error)
        return result

    def test_record_risk_preserves_proposed_status_and_is_idempotent(self):
        first, second = self.risk(), self.risk()
        self.assertEqual(first["status"], "PROPOSED")
        self.assertTrue(first["written"]); self.assertFalse(second["written"])
        self.assertEqual(first["event_id"], second["event_id"])
        events, _ = self.store.verified_contents()
        self.assertFalse(events[-1].payload["assessment"]["eligible"])
        self.assertEqual(events[-1].payload["review"]["simulation_risk"], self.review_value["simulation_risk"])
        self.assertEqual(events[-1].payload["review"]["sizing"], self.review_value["sizing"])

    def test_record_risk_can_retry_using_only_retained_journal_support(self):
        first = self.risk()
        status, second, error = self.call("record-risk", "--review", self.review_path)
        self.assertEqual(status, 0, error)
        self.assertFalse(second["written"])
        self.assertEqual(first["event_id"], second["event_id"])

    def test_record_risk_cannot_create_missing_foundation(self):
        self.journal = self.root / "empty-journal"
        status, _, error = self.call("record-risk", "--review", self.review_path, "--evidence-root", self.evidence)
        self.assertEqual(status, 2)
        self.assertIn("preceding", error)
        self.assertFalse(self.journal.exists())

    def test_record_risk_source_hash_mismatch_cannot_append(self):
        ref = self.review_value["source_evidence"][0]
        (self.evidence / ref["path"]).write_bytes(b"changed")
        status, _, _ = self.call("record-risk", "--review", self.review_path, "--evidence-root", self.evidence)
        self.assertEqual(status, 2)
        self.assertEqual(self.store.verify().event_count, 6)

    def test_prepare_writes_validated_declaration_without_registration(self):
        status, prepared, error = self.prepare()
        self.assertEqual(status, 0, error)
        self.assertFalse(prepared["registered"])
        self.assertFalse(prepared["assessment"]["eligible"])
        study = ReviewedShadowStudy.from_bytes(Path(prepared["study_path"]).read_bytes())
        self.assertEqual(study.sizing, self.review_value["sizing"])
        self.assertEqual(study.evidence_scope, self.review_value["evidence_scope"])
        self.assertIsNone(study.continuity_intake_evidence)
        self.assertIsNone(study.cost_intake_evidence)
        self.assertFalse(study.auto_trading_enabled)
        self.assertEqual(self.store.verify().event_count, 7)

    def test_preparation_does_not_upgrade_proposal_or_replace_original_risk(self):
        status, prepared, error = self.prepare(); self.assertEqual(status, 0, error)
        self.register(prepared)
        events, _ = self.store.verified_contents()
        original_plan = next(row for row in events if row.event_id == self.material["studies"][0]["plan_event"].event_id)
        self.assertEqual(original_plan.payload["plan"]["risk"], self.material["studies"][0]["plan"].risk)
        self.assertFalse(events[-1].payload["risk_assessment"]["eligible"])
        self.assertIn("RISK_REVIEW_NOT_APPROVED_FOR_SHADOW", events[-1].payload["gate_assessment"]["reason_codes"])

    def test_explicit_fixture_approval_projects_risk_but_missing_adapters_still_block_intents(self):
        self.review_value["status"] = "APPROVED_FOR_SHADOW"
        self.review_path.write_bytes(canonical_json_bytes(self.review_value))
        recorded = self.record()
        status, shown, error = self.call("show", "--event-id", recorded["event_id"])
        self.assertEqual(status, 0, error)
        result = shown["payload"]["result"]
        self.assertTrue(result["internal_risk_projection_prepared"])
        self.assertEqual(result["reviewed_simulation_risk"], self.review_value["simulation_risk"])
        self.assertEqual(result["original_simulation_risk"], self.material["studies"][0]["plan"].risk)
        self.assertFalse(result["gate_assessment"]["eligible"])
        self.assertEqual(shown["payload"]["production"]["intents"]["decisions"], [])
        self.assertEqual(result["calculation_result"]["cost_stress_runs"], [])
        self.assertEqual(result["final_holdout"]["scoring_status"], "WITHHELD")

    def test_prepare_exact_retry_preserves_all_artifact_bytes(self):
        first = self.prepare(); second = self.prepare()
        self.assertEqual(first[0], 0, first[2]); self.assertEqual(first, second)

    def test_prepare_oversized_identity_rejects_before_writes(self):
        output = self.root / "oversized"
        status, _, _ = self.prepare(study_id="a" * 111, output=output)
        self.assertEqual(status, 2)
        self.assertFalse(output.exists())

    def test_prepare_requires_recorded_risk_and_base_event_identities(self):
        self.risk()
        status, _, _ = self.call("prepare", "--base-plan-event-id", "missing", "--risk-review-event-id", "missing",
                                  "--study-id", "missing-study", "--experiment-id", "missing-experiment",
                                  "--registered-at", "2025-04-01T12:30:00Z", "--output-directory", self.root / "unwritten")
        self.assertEqual(status, 2)
        self.assertFalse((self.root / "unwritten").exists())

    def test_prepare_output_cannot_overlap_journal(self):
        status, _, _ = self.prepare(output=self.journal / "unsafe")
        self.assertEqual(status, 2)
        self.assertFalse((self.journal / "unsafe").exists())

    def test_evaluate_requires_registration(self):
        status, prepared, error = self.prepare(); self.assertEqual(status, 0, error)
        status, _, error = self.call("evaluate", "--study", prepared["study_path"], "--evidence-root", self.root / "prepared")
        self.assertEqual(status, 2)
        self.assertIn("registration", error)
        self.assertEqual(self.store.verify().event_count, 7)

    def test_register_retry_is_idempotent(self):
        status, prepared, error = self.prepare(); self.assertEqual(status, 0, error)
        first, second = self.register(prepared), self.register(prepared)
        self.assertTrue(first["written"]); self.assertFalse(second["written"])
        self.assertEqual(first["event_id"], second["event_id"])
        self.assertEqual(self.store.verify().event_count, 8)

    def test_evaluation_is_pure_and_preserves_deferred_zero_intents(self):
        status, prepared, error = self.prepare(); self.assertEqual(status, 0, error)
        self.register(prepared)
        before = self.store.verify().to_dict()
        status, result, error = self.call("evaluate", "--study", prepared["study_path"])
        self.assertEqual(status, 0, error)
        self.assertEqual(result["result"]["status"], "DEFER_EVIDENCE_GATES")
        self.assertEqual(result["production"]["intents"]["decisions"], [])
        self.assertIsNone(result["result"]["realized_trade_pnl"])
        self.assertEqual(result["result"]["calculation_result"]["cost_stress_runs"], [])
        self.assertEqual(self.store.verify().to_dict(), before)
        self.assertEqual(result["orders_submitted"], 0)
        self.assertEqual(result["provider_calls"], 0)

    def test_record_show_verify_exact_replay_and_original_risk_visible(self):
        recorded = self.record()
        status, shown, error = self.call("show", "--event-id", recorded["event_id"])
        self.assertEqual(status, 0, error)
        self.assertEqual(shown["schema_version"], "blackpod.decision_journal_event.v16")
        result = shown["payload"]["result"]
        self.assertEqual(result["original_simulation_risk"], self.material["studies"][0]["plan"].risk)
        self.assertEqual(result["reviewed_simulation_risk"], self.review_value["simulation_risk"])
        self.assertFalse(result["internal_risk_projection_prepared"])
        self.assertIsNone(result["realized_trade_pnl"])
        status, verified, error = self.call("verify")
        self.assertEqual(status, 0, error)
        self.assertEqual(verified["event_count"], 9)
        self.assertEqual(verified["orphan_evidence_count"], 0)

    def test_evaluation_record_exact_retry_is_idempotent(self):
        first, second = self.record(), self.record()
        self.assertTrue(first["written"]); self.assertFalse(second["written"])
        self.assertEqual(first["event_id"], second["event_id"])
        self.assertEqual(self.store.verify().event_count, 9)

    def test_render_preserves_unassessed_risk_and_escapes_source_notes(self):
        self.review_value["review_notes"] = "<script>do_not_execute()</script>"
        self.review_path.write_bytes(canonical_json_bytes(self.review_value))
        recorded = self.record()
        target = self.root / "reports" / "report.html"
        status, result, error = self.call("render", "--event-id", recorded["event_id"], "--output", target)
        self.assertEqual(status, 0, error)
        rendered = target.read_text()
        self.assertNotIn("<script>", rendered)
        self.assertIn("&lt;script&gt;", rendered)
        self.assertIn("DEFER_EVIDENCE_GATES", rendered)
        self.assertIn("ALL EXECUTION AUTHORITY OFF", rendered)
        self.assertIn("original_simulation_risk", rendered)
        self.assertEqual(result["sha256"], sha256_bytes(target.read_bytes()))

    def test_render_cannot_overwrite_journal_or_render_registration(self):
        status, prepared, error = self.prepare(); self.assertEqual(status, 0, error)
        registered = self.register(prepared)
        status, _, _ = self.call("render", "--event-id", registered["event_id"], "--output", self.root / "bad.html")
        self.assertEqual(status, 2)
        recorded = self.record()
        status, _, _ = self.call("render", "--event-id", recorded["event_id"], "--output", self.journal / "report.html")
        self.assertEqual(status, 2)
        self.assertFalse((self.journal / "report.html").exists())

    def test_unknown_event_show_rejects(self):
        status, _, _ = self.call("show", "--event-id", "unknown")
        self.assertEqual(status, 2)

    def test_full_source_study_loader_reconstructs_only_declared_closure(self):
        status, prepared, error = self.prepare(); self.assertEqual(status, 0, error)
        study = ReviewedShadowStudy.from_bytes(Path(prepared["study_path"]).read_bytes())
        loaded = load_reviewed_evidence(self.root / "prepared", study)
        for ref in (study.base_plan_evidence, study.risk_review_evidence):
            self.assertIn(ref["sha256"], loaded)
        plan = self.material["studies"][0]["plan"]
        for ref in plan.to_mapping()["dataset_evidence"], plan.to_mapping()["intents_evidence"], plan.to_mapping()["frozen_hypothesis_evidence"]:
            self.assertIn(ref["sha256"], loaded)


class CompleteReviewedShadowCLITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from blackpod_build_week.trading_shadow_review_example import fixture_material
        cls.material = fixture_material()

    def setUp(self):
        self.enterContext(patch.object(socket.socket, "connect", side_effect=AssertionError("network forbidden")))
        self.enterContext(patch("subprocess.Popen", side_effect=AssertionError("process forbidden")))
        self.enterContext(patch("subprocess.run", side_effect=AssertionError("provider forbidden")))
        temporary = tempfile.TemporaryDirectory(); self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.journal, self.evidence, self.input = self.root / "journal", self.root / "evidence", self.root / "input"
        self.evidence.mkdir(); self.input.mkdir()
        store = JournalStore(self.journal)
        for event, evidence in zip(self.material["events"], self.material["event_evidence"]):
            store.append(event, evidence)
        for path, raw in self.material["evidence"].items():
            target = self.evidence / path; target.parent.mkdir(parents=True, exist_ok=True); target.write_bytes(raw)
        self.risk_path = self.input / "risk-review.json"
        self.risk_path.write_bytes(self.material["studies"][0]["risk_review"].to_bytes())

    def call(self, command, *extra):
        output, error = io.StringIO(), io.StringIO()
        args = [command, "--journal-root", str(self.journal), *map(str, extra)]
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(error):
            status = main(args)
        return status, json.loads(output.getvalue()) if output.getvalue() else None, error.getvalue()

    def prepare(self, study_id="complete-cli-study", experiment_id="complete-cli-experiment", output_name="prepared"):
        records = {}
        for command, source in (("record-continuity", "synthetic-reviewed/continuity-intake.v1.json"),
                                ("record-cost", "synthetic-reviewed/cost-intake.v1.json")):
            status, result, error = self.call(command, "--export", self.evidence / source,
                                              "--evidence-root", self.evidence, "--recorded-at", "2025-04-01T12:10:00Z")
            self.assertEqual(status, 0, error); records[command] = result["event_id"]
        status, risk, error = self.call("record-risk", "--review", self.risk_path, "--evidence-root", self.evidence)
        self.assertEqual(status, 0, error)
        status, prepared, error = self.call("prepare", "--base-plan-event-id", self.material["studies"][0]["plan_event"].event_id,
                "--risk-review-event-id", risk["event_id"], "--continuity-event-id", records["record-continuity"],
                "--cost-event-id", records["record-cost"], "--study-id", study_id, "--experiment-id", experiment_id,
                "--registered-at", "2025-04-01T14:00:00Z", "--output-directory", self.root / output_name)
        self.assertEqual(status, 0, error)
        return prepared

    def register(self, prepared):
        status, result, error = self.call("register", "--study", prepared["study_path"],
                                          "--evidence-root", Path(prepared["study_path"]).parent.parent)
        self.assertEqual(status, 0, error)
        return result

    def test_optional_adapter_ids_and_explicit_fixture_review_allow_shadow_only_pipeline(self):
        prepared = self.prepare()
        self.assertTrue(prepared["assessment"]["eligible"])
        self.assertFalse(prepared["registered"])
        self.assertEqual(JournalStore(self.journal).verify().event_count, 9)
        registered = self.register(prepared)
        status, result, error = self.call("evaluate", "--study", prepared["study_path"])
        self.assertEqual(status, 0, error)
        self.assertEqual(result["result"]["status"], "SHADOW_SIMULATED")
        self.assertTrue(result["production"]["intents"]["decisions"])
        self.assertEqual(len(result["result"]["calculation_result"]["cost_stress_runs"]), 3)
        self.assertIsNone(result["result"]["realized_trade_pnl"])
        self.assertEqual(result["result"]["final_holdout"]["scoring_status"], "WITHHELD")
        status, recorded, error = self.call("record", "--study", prepared["study_path"], "--evaluation-id", "complete-cli-eval",
                                            "--recorded-at", "2025-04-01T15:00:00Z")
        self.assertEqual(status, 0, error)
        status, shown, error = self.call("show", "--event-id", recorded["event_id"])
        self.assertEqual(status, 0, error)
        self.assertEqual(shown["payload"]["study_event_id"], registered["event_id"])
        self.assertIsNotNone(shown["payload"]["continuity_event_id"])
        self.assertIsNotNone(shown["payload"]["cost_event_id"])
        self.assertTrue(all(value is False for value in shown["payload"]["result"]["authority"].values()))
        report = self.root / "reports" / "eligible.html"
        status, rendered, error = self.call("render", "--event-id", recorded["event_id"], "--output", report)
        self.assertEqual(status, 0, error)
        self.assertIn("Development-only cost sensitivities", report.read_text())
        self.assertIn("Original frozen plan", report.read_text())
        self.assertEqual(rendered["sha256"], sha256_bytes(report.read_bytes()))
        self.assertEqual(JournalStore(self.journal).verify().event_count, 11)
        self.assertEqual(JournalStore(self.journal).verify().orphan_evidence_count, 0)

    def test_complete_declaration_loader_uses_export_request_and_origin_closure(self):
        prepared = self.prepare()
        study = ReviewedShadowStudy.from_bytes(Path(prepared["study_path"]).read_bytes())
        loaded = load_reviewed_evidence(self.root / "prepared", study)
        for ref in (study.continuity_intake_evidence, study.cost_intake_evidence, study.risk_review_evidence):
            self.assertIn(ref["sha256"], loaded)
        origin = self.material["assumptions"].origin_evidence[0]
        self.assertIn(origin["sha256"], loaded)
        coverage_origin = self.material["coverage_review"].source_evidence[0]
        self.assertIn(coverage_origin["sha256"], loaded)

    def test_prepare_trial_registry_retains_original_registration_retry_prefix(self):
        first = self.prepare(study_id="complete-trial-one", experiment_id="complete-shared-experiment", output_name="one")
        self.register(first)
        second = self.prepare(study_id="complete-trial-two", experiment_id="complete-shared-experiment", output_name="two")
        study = ReviewedShadowStudy.from_bytes(Path(second["study_path"]).read_bytes())
        self.assertEqual(study.trial_registry["prior_trial_ids"], ["complete-trial-one-trial-1"])
        self.register(second)
        retry = self.prepare(study_id="complete-trial-one", experiment_id="complete-shared-experiment", output_name="one")
        self.assertEqual(first, retry)

    def test_prepare_rejects_wrong_typed_adapter_event_identity_before_writes(self):
        prepared = self.prepare()
        events, _ = JournalStore(self.journal).verified_contents()
        risk = next(event for event in events if event.event_type == "TRADING_SHADOW_RISK_REVIEW_RECORDED")
        status, _, _ = self.call("prepare", "--base-plan-event-id", self.material["studies"][0]["plan_event"].event_id,
                "--risk-review-event-id", risk.event_id, "--continuity-event-id", risk.event_id,
                "--study-id", "mistyped-study", "--experiment-id", "mistyped-experiment", "--registered-at", "2025-04-01T14:00:00Z",
                "--output-directory", self.root / "mistyped")
        self.assertEqual(status, 2)
        self.assertFalse((self.root / "mistyped").exists())


if __name__ == "__main__": unittest.main()
