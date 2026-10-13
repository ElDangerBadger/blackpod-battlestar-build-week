"""Journal intent stays distinct from actual runtime and investment authority."""
import copy
from pathlib import Path
import unittest
from blackpod_build_week.contracts.trading_automation import TradingAutomationControl
from blackpod_build_week.trading_automation import (
    auto_trading_status, build_automation_event, validate_automation_event,
)
from blackpod_build_week.hashing import sha256_bytes


class TradingAutomationTests(unittest.TestCase):
    def setUp(self):
        self.control = TradingAutomationControl.from_bytes(
            (Path(__file__).resolve().parents[1] / "examples/auto_trading.control.off.v1.json").read_bytes())

    def test_default_off_without_any_record(self):
        result = auto_trading_status([])
        self.assertFalse(result["effective_enabled"])
        self.assertEqual(result["state"], "OFF")

    def test_requested_on_never_authorizes_execution(self):
        value = self.control.to_dict()
        value["requested_enabled"] = True
        event = build_automation_event(TradingAutomationControl.from_mapping(value))
        result = auto_trading_status([event])
        self.assertEqual(result["state"], "BLOCKED")
        self.assertFalse(result["broker_calls_permitted"])
        self.assertFalse(result["investment_approval_applies"])
        self.assertFalse(result["capital_transfers_permitted"])

    def test_strict_control_rejects_scope_domain_authority_and_implicit_boolean(self):
        for field, changed in (("domain", "INVESTMENT"), ("scope", "EXECUTE"), ("execution_mode", "LIVE"),
                               ("requested_enabled", 1), ("origin", "LLM"), ("switch_id", "capital")):
            with self.subTest(field=field), self.assertRaises(ValueError):
                value = self.control.to_dict()
                value[field] = changed
                TradingAutomationControl.from_mapping(value)
        value = self.control.to_dict()
        value["execution_enabled"] = True
        with self.assertRaises(ValueError):
            TradingAutomationControl.from_mapping(value)

    def test_retained_control_and_exact_projection_required(self):
        event = build_automation_event(self.control)
        blobs = {sha256_bytes(self.control.to_bytes()): self.control.to_bytes()}
        validate_automation_event(event, [], blobs)
        with self.assertRaises(ValueError):
            validate_automation_event(event, [], {})
        modified = event.to_dict()
        modified["payload"]["status"]["effective_enabled"] = True
        with self.assertRaises(ValueError):
            type(event).from_mapping(modified)

    def test_recording_time_cannot_retreat(self):
        original = build_automation_event(self.control)
        value = self.control.to_dict()
        value.update(control_id="earlier", recorded_at="2026-10-10T00:00:00Z")
        control = TradingAutomationControl.from_mapping(value)
        with self.assertRaises(ValueError):
            validate_automation_event(build_automation_event(control), [original], {sha256_bytes(control.to_bytes()): control.to_bytes()})

    def test_identity_deterministic_and_nested_input_is_immutable(self):
        value = self.control.to_dict()
        control = TradingAutomationControl.from_mapping(value)
        before = build_automation_event(control).to_bytes()
        value["requested_enabled"] = True
        self.assertEqual(before, build_automation_event(control).to_bytes())
        self.assertEqual(before, build_automation_event(self.control).to_bytes())


if __name__ == "__main__":
    unittest.main()
