"""Offline command boundaries and immutable segmented qualification lifecycle."""
from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import shutil
import socket
import tempfile
import unittest
from unittest.mock import patch

from blackpod_build_week.decision_journal_store import JournalStore, JournalStoreError
from blackpod_build_week.segmented_evidence_qualification_cli import main, build_parser, _read
from blackpod_build_week.hashing import canonical_json_bytes
from test_segmented_evidence_qualification_journal import retained_fixture


class OfflineBoundaryCliTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(patch.object(socket.socket, "connect", side_effect=AssertionError("network forbidden")))
        self.enterContext(patch("subprocess.Popen", side_effect=AssertionError("workers forbidden")))
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()

    def call(self, args):
        out = io.StringIO()
        with redirect_stdout(out):
            code = main(args)
        return code, json.loads(out.getvalue())

    def test_verify_missing_journal_does_not_create_it(self):
        missing = self.root / "missing"
        code, result = self.call(["verify", "--journal-root", str(missing)])
        self.assertEqual(code, 2)
        self.assertFalse(result["auto_trading_enabled"])
        self.assertFalse(missing.exists())

    def test_commands_have_no_capture_credentials_broker_or_activation_options(self):
        parser = build_parser()
        subparsers = next(action for action in parser._actions if hasattr(action, "choices") and isinstance(action.choices, dict))
        self.assertEqual(set(subparsers.choices), {"prepare", "register", "assess", "record", "verify", "show"})
        for command in subparsers.choices.values():
            options = {option for action in command._actions for option in action.option_strings}
            self.assertFalse(options & {"--credential-source", "--allow-market-data-get", "--auto-trading", "--activate", "--broker"})

    def test_leaf_symlink_rejected(self):
        target = self.root / "target.json"
        target.write_bytes(b"{}")
        link = self.root / "link.json"
        link.symlink_to(target)
        with self.assertRaises((OSError, ValueError)):
            _read(link)

    def test_ancestor_symlink_rejected(self):
        target = self.root / "target"
        target.mkdir()
        (target / "source.json").write_bytes(b"{}")
        link = self.root / "link"
        link.symlink_to(target, target_is_directory=True)
        with self.assertRaises((OSError, ValueError, JournalStoreError)):
            _read(link / "source.json")

    def test_parent_traversal_rejected(self):
        with self.assertRaisesRegex(ValueError, "traverse"):
            _read(self.root / "folder" / ".." / "source.json")

    def test_missing_prepare_inputs_do_not_create_journal_or_output(self):
        journal, output = self.root / "missing", self.root / "binding.json"
        code, result = self.call(["prepare", "--journal-root", str(journal), "--output", str(output),
            "--binding-id", "missing-source", "--recorded-at", "2025-04-05T00:00:00Z",
            "--qualification-policy-event-id", "journal-event-" + "a" * 64,
            "--capture-plan-event-id", "journal-event-" + "b" * 64])
        self.assertEqual(code, 2)
        self.assertFalse(result["auto_trading_enabled"])
        self.assertFalse(journal.exists())
        self.assertFalse(output.exists())


class SegmentedCliLifecycleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.material, cls.base, cls.retained_temp = retained_fixture()

    def setUp(self):
        self.enterContext(patch.object(socket.socket, "connect", side_effect=AssertionError("network forbidden")))
        self.enterContext(patch("subprocess.Popen", side_effect=AssertionError("workers forbidden")))
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.journal = self.root / "journal"
        shutil.copytree(self.base, self.journal)
        self.inputs = self.root / "input"
        self.inputs.mkdir()
        self.binding_path, self.request_path = self.inputs / "binding.json", self.inputs / "request.json"
        self.binding_path.write_bytes(self.material["binding"].to_bytes())
        self.request_path.write_bytes(self.material["request"].to_bytes())

    def call(self, arguments):
        out = io.StringIO()
        with redirect_stdout(out):
            code = main(arguments)
        return code, json.loads(out.getvalue())

    def register(self):
        return self.call(["register", "--binding", str(self.binding_path), "--journal-root", str(self.journal)])

    def test_prepare_verifies_sources_without_calibration_or_append(self):
        output = self.root / "prepared" / "binding.json"
        before = JournalStore(self.journal).verify().to_dict()
        code, result = self.call(["prepare", "--journal-root", str(self.journal),
            "--binding-id", "prepared-cli-binding", "--recorded-at", self.material["binding"].recorded_at,
            "--qualification-policy-event-id", self.material["policy_event"].event_id,
            "--capture-plan-event-id", self.material["capture_plan_event"].event_id,
            "--output", str(output)])
        self.assertEqual(code, 0, result)
        self.assertFalse(result["calibration_performed"])
        self.assertEqual(result["provider_calls"], 0)
        self.assertFalse(result["auto_trading_enabled"])
        self.assertEqual(JournalStore(self.journal).verify().to_dict(), before)

    def test_register_record_exact_retry_show_and_verify(self):
        code, registered = self.register()
        self.assertEqual(code, 0, registered)
        self.assertTrue(registered["written"])
        self.assertFalse(self.register()[1]["written"])
        arguments = ["record", "--request", str(self.request_path), "--journal-root", str(self.journal)]
        code, recorded = self.call(arguments)
        self.assertEqual(code, 0, recorded)
        self.assertEqual(recorded["status"], "READY_FOR_QUALIFIED_STUDY_DESIGN")
        self.assertFalse(self.call(arguments)[1]["written"])
        code, shown = self.call(["show", "--event-id", recorded["event_id"], "--journal-root", str(self.journal)])
        self.assertEqual(code, 0, shown)
        self.assertFalse(shown["payload"]["result"]["economic_hypothesis_supported"])
        code, verified = self.call(["verify", "--journal-root", str(self.journal)])
        self.assertEqual(code, 0, verified)
        self.assertEqual(verified["event_count"], len(self.material["events"]) + 2)

    def test_assess_exports_exact_immutable_report_without_append(self):
        self.assertEqual(self.register()[0], 0)
        before = JournalStore(self.journal).verify().to_dict()
        output = self.root / "reports" / "qualification.json"
        arguments = ["assess", "--request", str(self.request_path), "--journal-root", str(self.journal), "--output", str(output)]
        code, result = self.call(arguments)
        self.assertEqual(code, 0, result)
        original = output.read_bytes()
        self.assertEqual(self.call(arguments)[0], 0)
        self.assertEqual(output.read_bytes(), original)
        self.assertEqual(JournalStore(self.journal).verify().to_dict(), before)

    def test_journal_cannot_be_used_as_output_storage(self):
        self.register()
        code, result = self.call(["assess", "--request", str(self.request_path), "--journal-root", str(self.journal),
            "--output", str(self.journal / "forbidden.json")])
        self.assertEqual(code, 2, result)
        self.assertFalse((self.journal / "forbidden.json").exists())

    def test_repository_source_cannot_be_used_as_output_storage(self):
        self.register()
        output = Path(__file__).resolve().parents[1] / "src" / "forbidden-segmented.json"
        code, result = self.call(["assess", "--request", str(self.request_path), "--journal-root", str(self.journal), "--output", str(output)])
        self.assertEqual(code, 2, result)
        self.assertFalse(output.exists())

    def test_binding_symlink_rejected_without_journal_change(self):
        target = self.root / "original-binding.json"
        self.binding_path.rename(target)
        self.binding_path.symlink_to(target)
        before = JournalStore(self.journal).verify().to_dict()
        self.assertEqual(self.register()[0], 2)
        self.assertEqual(JournalStore(self.journal).verify().to_dict(), before)

    def test_wrong_request_schema_returns_structured_error(self):
        self.register()
        request = self.material["request"].to_dict()
        request["schema_version"] = "future"
        self.request_path.write_bytes(canonical_json_bytes(request))
        code, result = self.call(["record", "--request", str(self.request_path), "--journal-root", str(self.journal)])
        self.assertEqual(code, 2, result)
        self.assertFalse(result["auto_trading_enabled"])

    def test_old_source_event_cannot_be_shown_as_new_qualification(self):
        code, result = self.call(["show", "--event-id", self.material["aggregate_export_event"].event_id,
            "--journal-root", str(self.journal)])
        self.assertEqual(code, 2, result)
