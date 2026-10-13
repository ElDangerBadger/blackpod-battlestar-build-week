"""Committed synthetic examples reproduce append-only observations offline."""
import contextlib
import io
import json
from pathlib import Path
import socket
import tempfile
import unittest
from unittest import mock

from blackpod_build_week import trading_reconciliation_cli as cli
from blackpod_build_week.decision_journal_store import JournalStore
from blackpod_build_week.hashing import canonical_json_bytes, sha256_bytes


class TradingReconciliationExamplesTests(unittest.TestCase):
    def test_committed_example_commands_reproduce_expected_event_and_no_authority(self):
        repo = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as directory, mock.patch.object(socket.socket, "connect", side_effect=AssertionError("network forbidden")), mock.patch("subprocess.Popen", side_effect=AssertionError("execution forbidden")):
            journal = Path(directory).resolve() / "journal"
            ownership = json.loads((repo / "examples/trading_ownership.paper.v1.json").read_text())
            commands = [
                ["import-snapshot", "--snapshot", str(repo / "examples/paper_broker_snapshot.fixture.v1.json"),
                 "--evidence", str(repo / "fixtures/trading_reconciliation/paper-broker-source.fixture.json")],
                ["record-ownership", "--ownership", str(repo / "examples/trading_ownership.paper.v1.json"),
                 "--confirm-account-id", "paper-account-example", "--confirm-desk-scope-sha256", sha256_bytes(canonical_json_bytes(ownership["desks"]))],
                ["record-reconciliation", "--reconciliation", str(repo / "examples/trading_reconciliation.paper.v1.json")],
            ]
            for command in commands:
                with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                    self.assertEqual(cli.main(command + ["--journal-root", str(journal)]), 0)
            store = JournalStore(journal)
            before = [event.to_bytes() for event in store.events()]
            expected = (repo / "fixtures/trading_reconciliation/expected-reconciliation-event.json").read_bytes()
            self.assertEqual(before[-1], expected)
            result = store.events()[-1].payload["result"]
            self.assertEqual(result["status"], "NO_EXECUTION_OBSERVED")
            self.assertFalse(result["execution_authority_granted"])
            self.assertIsNone(result["realized_trade_pnl"])
            for command in commands:
                with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                    self.assertEqual(cli.main(command + ["--journal-root", str(journal)]), 0)
            self.assertEqual(before, [event.to_bytes() for event in store.events()])
            self.assertEqual(store.verify().event_count, 3)


if __name__ == "__main__":
    unittest.main()
