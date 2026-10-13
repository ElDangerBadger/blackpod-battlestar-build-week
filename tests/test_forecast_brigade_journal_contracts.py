"""Strict v9 passive source identities and no-authority Brigade requests."""
from __future__ import annotations

import copy
import unittest

from blackpod_build_week.contracts.brigade_shadow import BrigadeShadowRequest
from blackpod_build_week.contracts.decision_journal import JournalEvent
from blackpod_build_week.contracts.forecast_intake import ForecastIntake
from blackpod_build_week.contracts.mission_request import ContractValidationError
from blackpod_build_week.forecast_journal import build_brigade_shadow_event, build_forecast_intake_event
from blackpod_build_week.hashing import sha256_bytes
from test_shadow_brigade_analysis import AUTHORITY, BrigadeFixture, GENERATED_AT


class ForecastBrigadeJournalFixture:
    def __init__(self):
        self.f = BrigadeFixture()
        self.blobs = {**self.f.blobs, **self.f.evidence()}
        self.forecast_event = build_forecast_intake_event(self.f.intake, blobs=self.blobs)
        self.request_value = {"schema_version": "blackpod.brigade_shadow_request.v1", "analysis_id": "fixture-linked-brigade",
            "recorded_at": "2026-10-12T20:02:00Z", "generated_at": GENERATED_AT, "domain": "TRADING", "mode": "SHADOW",
            "scope": "BRIGADE_RECOMMENDATIONS_ONLY", "forecast": {"intake_event_id": self.forecast_event.event_id,
                "intake_id": self.f.intake.intake_id, "intake_source_sha256": sha256_bytes(self.f.intake.to_bytes()),
                "intake_evidence": self.reference("brigade/forecast-intake.json", self.f.intake.to_bytes())},
            "market_evidence": self.reference("brigade/market-packet.json", self.f.raw),
            "source_evidence": {"brigade": self.reference("brigade/blackwell_brigade.py", self.f.brigade),
                                "decay": self.reference("brigade/decay.py", self.f.decay)},
            "symbols": ["AAA"], "inference_mode": "DISABLED", "transcript_evidence": None, "authority": dict(AUTHORITY)}
        self.request = BrigadeShadowRequest.from_mapping(self.request_value)

    def reference(self, path, raw):
        digest = sha256_bytes(raw)
        self.blobs[digest] = raw
        return {"path": path, "sha256": digest, "size_bytes": len(raw)}

    def brigade_event(self):
        return build_brigade_shadow_event(self.request, (self.forecast_event,), self.blobs)


class ForecastBrigadeJournalContractTests(unittest.TestCase):
    def setUp(self): self.fx = ForecastBrigadeJournalFixture()

    def rejected_request(self, mutation):
        value = copy.deepcopy(self.fx.request_value)
        mutation(value)
        with self.assertRaises(ContractValidationError): BrigadeShadowRequest.from_mapping(value)

    def test_request_is_immutable_and_round_trips_canonically(self):
        raw = self.fx.request.to_bytes()
        self.assertEqual(BrigadeShadowRequest.from_bytes(raw).to_bytes(), raw)
        copy = self.fx.request.to_dict()
        copy["symbols"].append("SPY")
        copy["authority"]["execution_enabled"] = True
        self.assertEqual(self.fx.request.to_bytes(), raw)

    def test_request_rejects_unknown_missing_and_extra_fields(self):
        self.rejected_request(lambda value: value.update(extra="unexpected"))
        self.rejected_request(lambda value: value.pop("scope"))
        self.rejected_request(lambda value: value["forecast"].update(extra="unexpected"))
        self.rejected_request(lambda value: value["source_evidence"].update(new_agent=self.fx.request.source_evidence["brigade"]))

    def test_request_is_trading_shadow_recommendations_only(self):
        for field, values in (("domain", ("INVESTMENT", "CAPITAL_ALLOCATION", "UNCLASSIFIED")),
                             ("mode", ("LIVE", "PAPER")), ("scope", ("ORDER_EXECUTION", "CAPITAL_TRANSFER")),
                             ("inference_mode", ("LIVE", "AUTO", "GENERATE"))):
            for replacement in values:
                with self.subTest(field=field, replacement=replacement):
                    self.rejected_request(lambda value: value.update({field: replacement}))

    def test_all_authority_fields_are_explicitly_false(self):
        for field in AUTHORITY:
            with self.subTest(field=field):
                self.rejected_request(lambda value: value["authority"].update({field: True}))
                self.rejected_request(lambda value: value["authority"].update({field: 0}))

    def test_generated_time_cannot_postdate_recording(self):
        self.rejected_request(lambda value: value.update(generated_at="2026-10-12T20:03:00Z"))

    def test_nanosecond_or_naive_times_are_rejected(self):
        for value in ("2026-10-12T20:01:00.123456789Z", "2026-10-12T20:01:00"):
            self.rejected_request(lambda mapping: mapping.update(generated_at=value))

    def test_symbols_are_one_to_eight_unique_and_canonical_order(self):
        for symbols in ([], ["AAA", "AAA"], ["S" + str(index) for index in range(9)]):
            self.rejected_request(lambda value: value.update(symbols=symbols))
        value = copy.deepcopy(self.fx.request_value)
        value["symbols"] = ["SPY", "AAA"]
        self.assertEqual(BrigadeShadowRequest.from_mapping(value).symbols, ["AAA", "SPY"])

    def test_disabled_mode_cannot_claim_transcript_and_replay_requires_evidence(self):
        self.rejected_request(lambda value: value.update(transcript_evidence=self.fx.request.market_evidence))
        self.rejected_request(lambda value: value.update(inference_mode="RETAINED_TRANSCRIPT"))

    def test_source_paths_cannot_collide_or_escape(self):
        self.rejected_request(lambda value: value.update(market_evidence=value["forecast"]["intake_evidence"]))
        self.rejected_request(lambda value: value["market_evidence"].update(path="../market.json"))
        self.rejected_request(lambda value: value["market_evidence"].update(path="/private/market.json"))

    def test_forecast_event_retains_rows_and_is_v9_without_authority(self):
        event = self.fx.forecast_event
        self.assertEqual(event.schema_version, "blackpod.decision_journal_event.v9")
        self.assertEqual(event.source["kind"], "FORECAST_INTAKE")
        self.assertEqual(event.payload["result"]["admitted_count"], 5)
        self.assertEqual(event.payload["result"]["rows"][0]["source_time_precision"], "DATE_ONLY")
        self.assertFalse(event.payload["result"]["auto_trading_enabled"])
        self.assertFalse(any(event.payload["result"]["authority"].values()))

    def test_investment_intake_is_preserved_and_deferred(self):
        value = self.fx.f.intake.to_dict()
        value.update(domain="INVESTMENT", intake_id="fixture-investment-intake")
        event = build_forecast_intake_event(ForecastIntake.from_mapping(value), blobs=self.fx.blobs)
        self.assertEqual(event.domain, "INVESTMENT")
        self.assertEqual(event.payload["result"]["admitted_count"], 0)
        self.assertTrue(all("SHORT_HORIZON_NOT_INVESTMENT_EVIDENCE" in row["reason_codes"] for row in event.payload["result"]["rows"]))

    def test_brigade_event_links_original_forecast_decision_identity(self):
        event = self.fx.brigade_event()
        self.assertEqual(event.decision_id, self.fx.forecast_event.decision_id)
        self.assertEqual(event.event_type, "BRIGADE_SHADOW_ANALYSIS_RECORDED")
        self.assertFalse(event.payload["analysis"]["auto_trading_enabled"])
        self.assertTrue(all(opinion["recommendation"] is None for opinion in event.payload["analysis"]["symbols"][0]["opinions"]))
        self.assertEqual(JournalEvent.from_bytes(event.to_bytes()).to_bytes(), event.to_bytes())

    def test_brigade_requires_preceding_forecast_intake(self):
        with self.assertRaisesRegex(ValueError, "preceding verified forecast"):
            build_brigade_shadow_event(self.fx.request, (), self.fx.blobs)

    def test_wrong_link_identity_domain_hash_or_intake_is_rejected(self):
        for field, replacement in (("intake_event_id", "journal-event-" + "0" * 64),
                                   ("intake_id", "another-intake"), ("intake_source_sha256", "0" * 64)):
            with self.subTest(field=field):
                value = copy.deepcopy(self.fx.request_value)
                value["forecast"][field] = replacement
                with self.assertRaises(ValueError):
                    build_brigade_shadow_event(BrigadeShadowRequest.from_mapping(value), (self.fx.forecast_event,), self.fx.blobs)
        event = self.fx.forecast_event.to_dict()
        event["domain"] = "INVESTMENT"
        event["payload"]["intake"]["domain"] = "INVESTMENT"
        input_document = ForecastIntake.from_mapping(event["payload"]["intake"])
        investment = build_forecast_intake_event(input_document, blobs=self.fx.blobs)
        value = copy.deepcopy(self.fx.request_value)
        value["forecast"]["intake_event_id"] = investment.event_id
        with self.assertRaisesRegex(ValueError, "domain"):
            build_brigade_shadow_event(BrigadeShadowRequest.from_mapping(value), (investment,), self.fx.blobs)

    def test_forecast_recording_cannot_occur_after_brigade_generation(self):
        value = self.fx.f.intake.to_dict()
        value.update(recorded_at="2026-10-12T20:02:00Z")
        intake = ForecastIntake.from_mapping(value)
        event = build_forecast_intake_event(intake, blobs=self.fx.blobs)
        request_value = copy.deepcopy(self.fx.request_value)
        request_value["forecast"].update(intake_event_id=event.event_id, intake_source_sha256=sha256_bytes(intake.to_bytes()),
                                         intake_evidence=self.fx.reference("brigade/forecast-intake.json", intake.to_bytes()))
        with self.assertRaisesRegex(ValueError, "after Brigade generation"):
            build_brigade_shadow_event(BrigadeShadowRequest.from_mapping(request_value), (event,), self.fx.blobs)

    def test_journal_contract_rejects_activation_or_type_source_mismatch(self):
        original = self.fx.brigade_event().to_dict()
        for mutation in (lambda event: event["payload"]["analysis"].update(auto_trading_enabled=True),
                         lambda event: event["payload"]["analysis"]["authority"].update(execution_enabled=True),
                         lambda event: event["source"].update(kind="FORECAST_INTAKE"),
                         lambda event: event.update(event_type="ORDER_EXECUTED"),
                         lambda event: event["source"].update(source_sha256="0" * 64)):
            with self.subTest(mutation=mutation):
                event = copy.deepcopy(original)
                mutation(event)
                with self.assertRaises(ContractValidationError): JournalEvent.from_mapping(event)


if __name__ == "__main__": unittest.main()
