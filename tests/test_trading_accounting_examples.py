"""Committed synthetic commands reproduce late-fee updates byte for byte."""
import importlib.util
import io
import json
from pathlib import Path
import socket
import tempfile
import unittest
from unittest.mock import patch

from blackpod_build_week import trading_accounting_cli as cli
from blackpod_build_week.decision_journal_store import JournalStore

ROOT = Path(__file__).resolve().parents[1]


class TradingAccountingExamplesTests(unittest.TestCase):
    def test_example_prelude_pending_fee_and_complete_fee_commands_are_repeatable(self):
        with tempfile.TemporaryDirectory() as directory, \
             patch.object(socket.socket, "connect", side_effect=AssertionError("network forbidden")), \
             patch("subprocess.Popen", side_effect=AssertionError("executor forbidden")), \
             patch("subprocess.run", side_effect=AssertionError("provider forbidden")), \
             patch("blackpod_build_week.auto_trading_runtime.enable_trading", side_effect=AssertionError("activation forbidden")):
            journal = Path(directory).resolve() / "journal"
            spec = importlib.util.spec_from_file_location("accounting_seed_example", ROOT / "examples/trading_accounting/seed_journal.py")
            seed = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(seed)
            with patch("sys.stdout", new_callable=io.StringIO):
                self.assertEqual(seed.main(["--journal-root", str(journal)]), 0)
            store = JournalStore(journal)
            self.assertEqual(store.verify().event_count, 4)
            original = {path: path.read_bytes() for path in (journal / "entries").iterdir()}
            for suffix in ("pending-fees", "complete-fees"):
                arguments = ["record", "--journal-root", str(journal), "--accounting", str(ROOT / f"examples/trading_accounting.{suffix}.paper.v1.json"),
                    "--activities", str(ROOT / f"examples/paper_activities.{suffix}.fixture.v1.json"),
                    "--source-evidence", str(ROOT / f"fixtures/trading_accounting/activity-export.{suffix}.fixture.json")]
                with patch("sys.stdout", new_callable=io.StringIO) as out:
                    self.assertEqual(cli.main(arguments), 0)
                value = json.loads(out.getvalue())
                self.assertTrue(value["written"])
                event = store.events()[-1]
                expected = (ROOT / f"fixtures/trading_accounting/expected-accounting.{suffix}.json").read_bytes()
                self.assertEqual(event.to_bytes(), expected)
                if suffix == "pending-fees":
                    self.assertEqual(event.payload["result"]["status"], "GROSS_RECONCILED_FEES_PENDING")
                    self.assertIsNone(event.payload["result"]["realized_trade_pnl"])
                else:
                    self.assertEqual(event.payload["result"]["realized_trade_pnl"], "15.92")
                for path, raw in original.items():
                    self.assertEqual(path.read_bytes(), raw)
            final_hash = store.verify().last_entry_sha256
            with patch("sys.stdout", new_callable=io.StringIO):
                self.assertEqual(seed.main(["--journal-root", str(journal)]), 0)
                for suffix in ("pending-fees", "complete-fees"):
                    self.assertEqual(cli.main(["record", "--journal-root", str(journal), "--accounting",
                        str(ROOT / f"examples/trading_accounting.{suffix}.paper.v1.json")]), 0)
            self.assertEqual(store.verify().last_entry_sha256, final_hash)
            self.assertEqual(store.verify().event_count, 6)
            self.assertEqual(store.verify().orphan_evidence_count, 0)


if __name__ == "__main__":
    unittest.main()
