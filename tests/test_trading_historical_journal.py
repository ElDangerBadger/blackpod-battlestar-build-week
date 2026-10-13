"""Passive catalog/intake linkage and governed v14 source-only replay."""
import copy
import json
from pathlib import Path
import socket
import tempfile
import unittest
from unittest.mock import patch

from blackpod_build_week.contracts.decision_journal import JournalEvent
from blackpod_build_week.contracts.trading_research import TradingResearchPlan, TradingResearchIntents
from blackpod_build_week.decision_journal_store import JournalStore, JournalConflictError, JournalVerificationError, JournalPersistenceError
from blackpod_build_week.hashing import canonical_json_bytes, sha256_bytes
from blackpod_build_week.trading_historical_intake import build_historical_intake
from blackpod_build_week.trading_hypotheses import catalog_hypotheses, catalog_documents, hypothesis_research_strategy
from blackpod_build_week.trading_research_intake_journal import (
    build_catalog_event, build_intake_event, catalog_evidence, intake_evidence,
)
from blackpod_build_week.trading_research_journal import build_plan_event, build_evaluation_event, evidence_for_research
from test_trading_historical_intake_contracts import source_material
from test_trading_research_contracts import plan_mapping, authority


CATALOG_CLOCK = "2026-01-22T23:01:00Z"
INTAKE_CLOCK = "2026-01-22T23:02:00Z"
PLAN_CLOCK = "2026-01-23T00:00:00Z"
EVAL_CLOCK = "2026-01-23T00:01:00Z"


def journal_material():
    request, _, blobs = source_material()
    material = build_historical_intake(request, blobs)
    catalog = catalog_hypotheses(CATALOG_CLOCK, "synthetic-journal-author")
    catalog_event = build_catalog_event(catalog)
    intake_event = build_intake_event(material["export"], material["blobs"], recorded_at=INTAKE_CLOCK)
    hypothesis = next(doc for doc in catalog_documents(catalog) if doc.hypothesis_id == "previous-session-reversal-v1")
    hypothesis_path = "trading-hypotheses/" + hypothesis.hypothesis_id + ".v1.json"
    value = plan_mapping()
    value.update(schema_version="blackpod.trading_research_plan.v2", plan_id="governed-journal-plan",
                 registered_at=PLAN_CLOCK, universe=material["dataset"].universe,
                 evaluation_purpose="DATA_QUALITY_ONLY")
    value.update(hypothesis_research_strategy(hypothesis))
    value["dataset_evidence"] = material["export"].dataset_evidence
    value["frozen_hypothesis_evidence"] = {"path": hypothesis_path, "sha256": sha256_bytes(hypothesis.to_bytes()), "size_bytes": len(hypothesis.to_bytes())}
    value["protocol"]["final_holdout"] = {"start_index": 11, "end_index": 11}
    value["trial_registry"] = {"trial_id": "governed-journal-trial", "prior_trial_ids": []}
    intents = TradingResearchIntents.from_mapping({"schema_version": "blackpod.trading_research_intents.v1",
        "intent_set_id": "governed-journal-empty-intents", "plan_id": value["plan_id"], "created_at": "2026-01-22T23:03:00Z",
        "origin": "EXTERNALLY_AUTHORED_RESEARCH_ONLY", "decisions": [], "authority": authority()})
    value["intents_evidence"] = {"path": "research/empty-intents.json", "sha256": sha256_bytes(intents.to_bytes()), "size_bytes": len(intents.to_bytes())}
    blobs = dict(material["blobs"])
    blobs.update({sha256_bytes(raw): raw for raw in catalog_evidence(catalog).values()})
    blobs[sha256_bytes(intents.to_bytes())] = intents.to_bytes()
    plan = TradingResearchPlan.from_mapping(value)
    plan_event = build_plan_event(plan, (catalog_event, intake_event), blobs)
    return {**material, "catalog": catalog, "catalog_event": catalog_event, "intake_event": intake_event,
            "plan": plan, "intents": intents, "plan_event": plan_event, "blobs": blobs}


class HistoricalJournalTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(patch.object(socket.socket, "connect", side_effect=AssertionError("network forbidden")))
        self.enterContext(patch("subprocess.Popen", side_effect=AssertionError("strategy worker forbidden")))
        temporary = tempfile.TemporaryDirectory(); self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve(); self.store = JournalStore(self.root / "journal")
        self.m = journal_material()

    def sources(self):
        a = self.store.append(self.m["catalog_event"], catalog_evidence(self.m["catalog"]))
        b = self.store.append(self.m["intake_event"], intake_evidence(self.m["export"], self.m["blobs"]))
        return a, b

    def register(self):
        self.sources()
        events, blobs = self.store.verified_contents(); blobs.update(self.m["blobs"])
        event = build_plan_event(self.m["plan"], events, blobs)
        return self.store.append(event, evidence_for_research(self.m["plan"], blobs))

    def evaluate(self, evaluation_id="governed-journal-evaluation", recorded_at=EVAL_CLOCK):
        events, blobs = self.store.verified_contents()
        event = build_evaluation_event(self.m["plan"], events, blobs, evaluation_id=evaluation_id, recorded_at=recorded_at)
        return self.store.append(event, evidence_for_research(self.m["plan"], blobs)), event

    def test_complete_chain_records_source_links_and_no_performance_authority(self):
        self.register(); result, event = self.evaluate()
        self.assertEqual(result.sequence, 4)
        self.assertEqual(event.schema_version, "blackpod.decision_journal_event.v14")
        self.assertEqual(event.payload["hypothesis_event_id"], self.m["catalog_event"].event_id)
        self.assertEqual(event.payload["intake_event_id"], self.m["intake_event"].event_id)
        self.assertIsNone(event.payload["result"]["realized_trade_pnl"])
        self.assertFalse(event.payload["result"]["auto_trading_enabled"])
        self.assertFalse(any(event.payload["result"]["authority"].values()))
        self.assertEqual(self.store.verify().event_count, 4)
        self.assertEqual(self.store.verify().orphan_evidence_count, 0)

    def test_catalog_and_intake_alone_are_passive_v13_events(self):
        self.sources()
        self.assertEqual([event.schema_version for event in self.store.events()], ["blackpod.decision_journal_event.v13"] * 2)
        self.assertEqual(self.store.verify().event_count, 2)

    def test_exact_retries_preserve_all_entry_and_evidence_bytes(self):
        self.register(); self.evaluate()
        paths = [path for folder in ("entries", "evidence") for path in (self.store.root / folder).iterdir()]
        before = {str(path): path.read_bytes() for path in paths}
        self.assertFalse(self.sources()[0].written); self.assertFalse(self.sources()[1].written)
        self.assertFalse(self.register().written); self.assertFalse(self.evaluate()[0].written)
        self.assertEqual(before, {str(path): path.read_bytes() for path in paths})

    def test_later_evaluation_appends_without_rewriting_original_sources(self):
        self.register(); self.evaluate(); original = [event.to_bytes() for event in self.store.events()]
        self.evaluate("later-data-quality-evaluation", "2026-01-23T00:02:00Z")
        self.assertEqual([event.to_bytes() for event in self.store.events()[:4]], original)
        self.assertEqual(self.store.verify().event_count, 5)

    def test_same_catalog_id_conflicting_source_is_not_a_revision(self):
        self.sources()
        catalog = catalog_hypotheses(CATALOG_CLOCK, "different-local-author")
        with self.assertRaises(JournalConflictError): self.store.append(build_catalog_event(catalog), catalog_evidence(catalog))

    def test_same_intake_clock_change_conflicts_not_rewrites(self):
        self.sources()
        event = build_intake_event(self.m["export"], self.m["blobs"], recorded_at="2026-01-22T23:02:01Z")
        with self.assertRaises(JournalConflictError): self.store.append(event, intake_evidence(self.m["export"], self.m["blobs"]))

    def test_intake_clock_cannot_predate_source_capture_or_request(self):
        with self.assertRaises(ValueError):
            build_intake_event(self.m["export"], self.m["blobs"], recorded_at="2026-01-22T22:59:00Z")

    def test_plan_requires_both_preceding_sources(self):
        for events in ((), (self.m["catalog_event"],), (self.m["intake_event"],)):
            with self.assertRaises(ValueError): build_plan_event(self.m["plan"], events, self.m["blobs"])

    def test_plan_clock_cannot_predate_frozen_catalog_or_intake(self):
        value = self.m["plan"].to_dict(); value["registered_at"] = "2026-01-22T23:01:30Z"
        with self.assertRaises(ValueError): build_plan_event(value, (self.m["catalog_event"], self.m["intake_event"]), self.m["blobs"])

    def test_plan_strategy_horizon_must_match_frozen_hypothesis(self):
        for mutation in (lambda row: row["strategy"].update(expected_edge="A different undisclosed experiment."),
                         lambda row: row["horizon"].update(max_holding_sessions=2)):
            value = self.m["plan"].to_dict(); mutation(value)
            with self.assertRaises(ValueError): build_plan_event(value, (self.m["catalog_event"], self.m["intake_event"]), self.m["blobs"])

    def test_ambiguous_catalog_source_is_rejected(self):
        catalog = catalog_hypotheses(CATALOG_CLOCK, "synthetic-journal-author", catalog_id="duplicate-catalog-with-same-frozen-proposal")
        events = (self.m["catalog_event"], build_catalog_event(catalog), self.m["intake_event"])
        with self.assertRaises(ValueError): build_plan_event(self.m["plan"], events, self.m["blobs"])

    def test_unbound_changed_dataset_rehashed_cannot_replace_intake(self):
        value = self.m["plan"].to_dict(); data = self.m["dataset"].to_dict()
        data["sessions"][0]["bars"][0]["close"] = "100"
        raw = canonical_json_bytes(data); value["dataset_evidence"].update(sha256=sha256_bytes(raw), size_bytes=len(raw))
        blobs = dict(self.m["blobs"]); blobs[sha256_bytes(raw)] = raw
        with self.assertRaises(ValueError): build_plan_event(value, (self.m["catalog_event"], self.m["intake_event"]), blobs)

    def test_dataset_path_identity_cannot_be_changed_to_unjournaled_source(self):
        value = self.m["plan"].to_dict(); value["dataset_evidence"]["path"] = "other/unbound-dataset.json"
        with self.assertRaises(ValueError): build_plan_event(value, (self.m["catalog_event"], self.m["intake_event"]), self.m["blobs"])

    def test_frozen_hypothesis_path_must_bind_preceding_catalog_evidence(self):
        value = self.m["plan"].to_dict(); value["frozen_hypothesis_evidence"]["path"] = "other/unfrozen-proposal.json"
        with self.assertRaises(ValueError): build_plan_event(value, (self.m["catalog_event"], self.m["intake_event"]), self.m["blobs"])

    def test_catalog_event_missing_evidence_cannot_pass_replay(self):
        value = self.m["catalog_event"].to_dict(); value["evidence"].pop()
        event = JournalEvent.from_mapping(value)
        evidence = catalog_evidence(self.m["catalog"])
        evidence = {ref["path"]: evidence[ref["path"]] for ref in event.evidence}
        with self.assertRaises(JournalVerificationError): self.store.append(event, evidence)

    def test_intake_coverage_tamper_rehashed_source_still_fails_replay(self):
        value = self.m["intake_event"].to_dict(); value["payload"]["export"]["coverage"]["included_start_session"] = "2026-01-06"
        raw = canonical_json_bytes(value["payload"]["export"]); value["source"]["source_sha256"] = sha256_bytes(raw)
        for ref in value["evidence"]:
            if ref["path"] == "historical-intake/export.v1.json": ref.update(sha256=sha256_bytes(raw), size_bytes=len(raw))
        event = JournalEvent.from_mapping(value); evidence = intake_evidence(self.m["export"], self.m["blobs"])
        evidence["historical-intake/export.v1.json"] = raw
        with self.assertRaises(JournalVerificationError): self.store.append(event, evidence)

    def test_plan_link_tampering_cannot_pass_storage_replay(self):
        self.sources()
        for field in ("hypothesis_event_id", "intake_event_id"):
            value = self.m["plan_event"].to_dict(); value["payload"][field] = self.m["plan_event"].event_id
            with self.assertRaises(JournalVerificationError): self.store.append(JournalEvent.from_mapping(value), evidence_for_research(self.m["plan"], self.m["blobs"]))

    def test_evaluation_link_and_quality_result_tampering_cannot_pass_replay(self):
        self.register(); events, blobs = self.store.verified_contents()
        original = build_evaluation_event(self.m["plan"], events, blobs, evaluation_id="tamper-test", recorded_at=EVAL_CLOCK)
        for mutation in (lambda row: row["payload"].update(intake_event_id=row["event_id"]),
                         lambda row: row["payload"]["result"]["trial_registry"].update(declared_trial_count_at_registration=100)):
            value = original.to_dict(); mutation(value)
            with self.assertRaises(JournalVerificationError): self.store.append(JournalEvent.from_mapping(value), evidence_for_research(self.m["plan"], blobs))

    def test_retained_source_files_are_readonly_and_sufficient_for_replay(self):
        self.register(); self.evaluate()
        for event in self.store.events():
            for ref in event.evidence:
                path = self.store.root / "evidence" / ref["sha256"]
                self.assertEqual(path.stat().st_mode & 0o777, 0o444)
                self.assertEqual(sha256_bytes(path.read_bytes()), ref["sha256"])
        self.m.clear()
        self.assertEqual(self.store.verify().event_count, 4)

    def test_provider_or_native_file_lookup_not_needed_for_verified_read(self):
        self.register(); self.evaluate()
        with patch("urllib.request.urlopen", side_effect=AssertionError("no providers")), patch("builtins.__import__", wraps=__import__) as imports:
            self.assertEqual(self.store.verify().event_count, 4)
        self.assertFalse(any("galactica" in str(call.args[0]).lower() for call in imports.call_args_list))

    def test_missing_or_corrupted_retained_source_prevents_verify(self):
        self.sources(); reference = self.m["request"].sources["calendar_evidence"]
        path = self.store.root / "evidence" / reference["sha256"]
        path.chmod(0o600); path.write_bytes(b"corrupted source")
        with self.assertRaises(JournalVerificationError): self.store.verify()

    def test_source_only_interrupted_entry_publication_recovers_on_exact_retry(self):
        import blackpod_build_week.decision_journal_store as module
        self.store.append(self.m["catalog_event"], catalog_evidence(self.m["catalog"]))
        original = module._publish_immutable
        def interrupt(staging, target, name, raw):
            if name.endswith(".json"): raise OSError("injected intake entry publication interruption")
            return original(staging, target, name, raw)
        with patch.object(module, "_publish_immutable", side_effect=interrupt), self.assertRaises((OSError, JournalPersistenceError)):
            self.store.append(self.m["intake_event"], intake_evidence(self.m["export"], self.m["blobs"]))
        self.assertEqual(self.store.verify().event_count, 1)
        self.assertTrue(self.store.append(self.m["intake_event"], intake_evidence(self.m["export"], self.m["blobs"])).written)
        self.assertEqual(self.store.verify().event_count, 2)
        self.assertEqual(self.store.verify().staging_orphan_count, 0)

    def test_v13_and_v14_cannot_be_swapped_to_old_semantics(self):
        for original, replacement in ((self.m["catalog_event"], "blackpod.decision_journal_event.v12"),
                                      (self.m["plan_event"], "blackpod.decision_journal_event.v13")):
            value = original.to_dict(); value["schema_version"] = replacement
            with self.assertRaises(ValueError): JournalEvent.from_mapping(value)

    def test_only_bound_source_evidence_is_persisted(self):
        event = self.m["catalog_event"]; evidence = catalog_evidence(self.m["catalog"])
        unrelated = b"unrelated bytes must not be persisted"
        evidence["unrelated/account-key.raw"] = unrelated
        self.store.append(event, evidence)
        self.assertFalse((self.store.root / "evidence" / sha256_bytes(unrelated)).exists())
        self.assertEqual(self.store.verify().orphan_evidence_count, 0)

    def test_missing_bound_source_bytes_reject_before_publication(self):
        event = self.m["catalog_event"]; evidence = catalog_evidence(self.m["catalog"])
        evidence.pop(event.evidence[0]["path"])
        with self.assertRaises(JournalVerificationError): self.store.append(event, evidence)
        self.assertEqual(self.store.verify().event_count, 0)


if __name__ == "__main__": unittest.main()
