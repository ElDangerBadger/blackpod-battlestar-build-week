"""Offline commands retain accounting evidence without changing execution state."""
import copy
import io
import json
from pathlib import Path
import socket
import stat
import tempfile
import unittest
from unittest.mock import patch

from blackpod_build_week import trading_accounting_cli as cli
from blackpod_build_week.contracts.paper_test_budget import PaperTestBudget, budget_amounts
from blackpod_build_week.decision_journal_store import JournalStore
from blackpod_build_week.hashing import sha256_bytes
from blackpod_build_week.paper_test_budget import build_paper_test_budget, validate_budget_source
from test_trading_accounting_engine import AccountingFixture, RECORDED


class TradingAccountingCliTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(patch.object(socket.socket, "connect", side_effect=AssertionError("network forbidden")))
        self.enterContext(patch("subprocess.Popen", side_effect=AssertionError("executor forbidden")))
        self.enterContext(patch("subprocess.run", side_effect=AssertionError("provider forbidden")))
        self.enterContext(patch("blackpod_build_week.auto_trading_runtime.enable_trading", side_effect=AssertionError("activation forbidden")))
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.base = Path(directory.name).resolve()
        self.inputs = self.base / "inputs"
        self.inputs.mkdir()
        self.root = self.base / "journal"
        self.f = AccountingFixture()
        self.addCleanup(self.f.close)
        self.accounting = self.write("accounting.json", self.f.accounting.to_bytes())
        self.activities = self.write("activities.json", self.f.activities.to_bytes())
        self.source = self.write("source.json", self.f.rawsource)

    def write(self, name, raw):
        path = self.inputs / name
        path.write_bytes(raw)
        return path

    def seed(self):
        store = JournalStore(self.root)
        for event in self.f.events:
            store.append(event, self.f.blobs)
        return store

    def invoke(self, *args):
        with patch("sys.stdout", new_callable=io.StringIO) as out, patch("sys.stderr", new_callable=io.StringIO) as err:
            try:
                code = cli.main(list(args))
            except SystemExit as exc:
                code = exc.code
        return code, json.loads(out.getvalue()) if out.getvalue() else None, err.getvalue()

    def args(self, command, include_source=True):
        args = [command, "--journal-root", str(self.root), "--accounting", str(self.accounting)]
        if include_source:
            args += ["--activities", str(self.activities), "--source-evidence", str(self.source)]
        return args

    def retained(self):
        return {str(path.relative_to(self.root)): path.read_bytes() for path in self.root.rglob("*") if path.is_file()}

    def test_assess_computes_partial_close_without_writing_journal_or_runtime(self):
        self.seed()
        before = self.retained()
        code, value, error = self.invoke(*self.args("assess"))
        self.assertEqual((code, error), (0, ""))
        self.assertEqual(value["result"]["totals"]["gross_realized_pnl"], "16")
        self.assertEqual(value["result"]["realized_trade_pnl"], "15.92")
        self.assertEqual(value["orders_submitted"], 0)
        self.assertFalse(value["auto_trading_changed"])
        self.assertEqual(self.retained(), before)
        self.assertFalse((self.base / "runtime").exists())

    def test_record_then_retry_uses_retained_source_after_input_files_removed(self):
        store = self.seed()
        code, value, error = self.invoke(*self.args("record"))
        self.assertEqual((code, error), (0, ""))
        self.assertTrue(value["written"])
        before = self.retained()
        self.source.unlink()
        self.activities.unlink()
        code, repeated, error = self.invoke(*self.args("record", False))
        self.assertEqual((code, error), (0, ""))
        self.assertFalse(repeated["written"])
        self.assertEqual(value["event_id"], repeated["event_id"])
        self.assertEqual(self.retained(), before)
        self.assertEqual(store.verify().orphan_evidence_count, 0)

    def test_missing_activity_evidence_does_not_publish_an_entry(self):
        store = self.seed()
        before = self.retained()
        code, value, _ = self.invoke(*self.args("record", False))
        self.assertEqual(code, 2)
        self.assertIsNone(value)
        self.assertEqual(self.retained(), before)
        self.assertEqual(store.verify().event_count, len(self.f.events))

    def test_changed_source_bytes_cannot_be_substituted_for_bound_activities(self):
        self.seed()
        before = self.retained()
        self.source.write_bytes(b'{"schema_version":"changed"}')
        code, _, _ = self.invoke(*self.args("record"))
        self.assertEqual(code, 2)
        self.assertEqual(self.retained(), before)

    def test_source_tree_cannot_be_used_as_journal_root(self):
        args = self.args("record")
        args[args.index("--journal-root") + 1] = str(self.inputs / "journal")
        code, _, _ = self.invoke(*args)
        self.assertEqual(code, 2)
        self.assertFalse((self.inputs / "journal").exists())

    def test_show_verifies_accounting_and_leaves_all_files_unchanged(self):
        self.seed()
        _, result, _ = self.invoke(*self.args("record"))
        before = self.retained()
        code, value, error = self.invoke("show", "--journal-root", str(self.root), "--event-id", result["event_id"])
        self.assertEqual((code, error), (0, ""))
        self.assertEqual(value["schema_version"], "blackpod.decision_journal_event.v7")
        self.assertEqual(self.retained(), before)

    def test_unknown_accounting_event_does_not_create_storage(self):
        code, value, _ = self.invoke("show", "--journal-root", str(self.root), "--event-id", "unknown")
        self.assertEqual(code, 2)
        self.assertIsNone(value)
        self.assertFalse(self.root.exists())

    def test_normalize_is_private_immutable_source_bound_and_repeatable(self):
        target = self.base / "normalized" / "activities.json"
        args = ["normalize-activities", "--export", str(self.source), "--activity-set-id", "cli-normalized", "--output", str(target)]
        code, value, error = self.invoke(*args)
        self.assertEqual((code, error), (0, ""))
        self.assertEqual(stat.S_IMODE(target.stat().st_mode), 0o600)
        self.assertEqual(value["activities_sha256"], sha256_bytes(target.read_bytes()))
        before = target.read_bytes()
        self.assertEqual(self.invoke(*args)[0], 0)
        self.assertEqual(target.read_bytes(), before)
        validation = self.invoke("validate-activities", "--activities", str(target), "--source-evidence", str(self.source))
        self.assertEqual(validation[0], 0)
        self.assertTrue(validation[1]["valid"])
        args[args.index("--activity-set-id") + 1] = "changed-id"
        self.assertEqual(self.invoke(*args)[0], 2)
        self.assertEqual(target.read_bytes(), before)

    def test_normalize_rejects_source_and_canonical_output_locations(self):
        mission = self.base / "missions" / "fake"
        mission.mkdir(parents=True)
        for target in (self.inputs / "normalized.json", mission / "normalized.json"):
            code, _, _ = self.invoke("normalize-activities", "--export", str(self.source), "--activity-set-id", "cli-normalized", "--output", str(target))
            self.assertEqual(code, 2)
            self.assertFalse(target.exists())

    def test_incomplete_fees_remain_unknown_through_record_and_show(self):
        self.f.set_activities([row for row in self.f.rows if row["activity_type"] == "FILL"], fees_complete=False)
        self.accounting.write_bytes(self.f.accounting_for().to_bytes())
        self.activities.write_bytes(self.f.activities.to_bytes())
        self.source.write_bytes(self.f.rawsource)
        self.seed()
        code, value, error = self.invoke(*self.args("record"))
        self.assertEqual((code, error), (0, ""))
        self.assertEqual(value["result"]["status"], "GROSS_RECONCILED_FEES_PENDING")
        self.assertIsNone(value["result"]["realized_trade_pnl"])

    def budget_args(self):
        return ["plan-paper-test-budget", "--journal-root", str(self.root), "--snapshot-event-id", self.f.end_snapshot_event.event_id,
            "--budget-id", "paper-test-25-percent", "--recorded-at", RECORDED, "--declared-by", "fixture-human",
            "--confirm-account-id", "fixture-account", "--output-root", str(self.base / "budgets")]

    def test_inactive_budget_has_exact_equity_link_no_authority_or_runtime_installation(self):
        self.seed()
        before = self.retained()
        code, value, error = self.invoke(*self.budget_args())
        self.assertEqual((code, error), (0, ""))
        budget = value["budget"]
        self.assertEqual(budget["test_cap_usd"], "25000.00")
        self.assertEqual(budget["desk_budgets_usd"], {"TRADING": "12500.00", "INVESTMENT": "12500.00"})
        self.assertEqual(budget["status"], "DECLARED_INACTIVE")
        self.assertEqual(budget["enforcement_status"], "NOT_INSTALLED")
        self.assertIsNone(budget["max_entry_notional_usd"])
        self.assertTrue(all(flag is False for flag in budget["authority"].values()))
        self.assertEqual(self.retained(), before)
        code, result, error = self.invoke("validate-paper-test-budget", "--journal-root", str(self.root), "--budget", value["evidence_path"])
        self.assertEqual((code, error), (0, ""))
        self.assertTrue(result["valid"])
        before_budget = Path(value["evidence_path"]).read_bytes()
        self.assertEqual(self.invoke(*self.budget_args())[0], 0)
        self.assertEqual(Path(value["evidence_path"]).read_bytes(), before_budget)

    def test_budget_rejects_wrong_account_and_stale_selected_equity(self):
        self.seed()
        args = self.budget_args()
        args[args.index("--confirm-account-id") + 1] = "different-account"
        self.assertEqual(self.invoke(*args)[0], 2)
        args = self.budget_args()
        args[args.index("--snapshot-event-id") + 1] = self.f.start_event.event_id
        self.assertEqual(self.invoke(*args)[0], 2)
        self.assertFalse((self.base / "budgets").exists())


class PaperTestBudgetTests(unittest.TestCase):
    def setUp(self):
        self.f = AccountingFixture()
        self.addCleanup(self.f.close)

    def budget(self):
        return build_paper_test_budget(self.f.end_snapshot_event, budget_id="inactive-test", recorded_at=RECORDED, declared_by="fixture-human")

    def test_round_down_conserves_equity_and_never_exceeds_requested_cap(self):
        from decimal import Decimal, Inexact, Rounded, localcontext
        with localcontext() as context:
            context.prec = 2
            context.Emax, context.Emin = 1, -1
            context.traps[Inexact] = context.traps[Rounded] = True
            amounts = budget_amounts("81525.11")
        self.assertEqual(amounts["desk_budgets_usd"], {"TRADING": "10190.63", "INVESTMENT": "10190.63"})
        self.assertEqual(amounts["unassigned_test_reserve_usd"], "0.01")
        self.assertEqual(amounts["outside_test_usd"], "61143.84")
        total = sum((Decimal(number) for number in amounts["desk_budgets_usd"].values()), Decimal("0"))
        self.assertEqual(total + Decimal(amounts["unassigned_test_reserve_usd"]), Decimal(amounts["test_cap_usd"]))
        self.assertEqual(Decimal(amounts["test_cap_usd"]) + Decimal(amounts["outside_test_usd"]), Decimal("81525.11"))
        self.assertLessEqual(Decimal(amounts["test_cap_usd"]), Decimal("81525.11") * Decimal("0.25"))

    def test_source_bound_budget_is_independent_of_ambient_decimal_limits(self):
        from decimal import Inexact, Rounded, localcontext
        original = self.budget()
        with localcontext() as context:
            context.prec = 2
            context.Emax, context.Emin = 1, -1
            context.traps[Inexact] = context.traps[Rounded] = True
            changed = self.budget()
            parsed = PaperTestBudget.from_bytes(original.to_bytes())
        self.assertEqual(changed.to_bytes(), original.to_bytes())
        self.assertEqual(parsed.to_bytes(), original.to_bytes())

    def test_budget_cannot_add_execution_authority_or_missing_trial_parameters(self):
        original = self.budget().to_dict()
        for field, changed in (("mode", "LIVE"), ("status", "ACTIVE"), ("activation_enabled", True), ("max_entry_notional_usd", "100"),
                               ("fraction_of_equity", "0.50"), ("enforcement_status", "INSTALLED")):
            value = copy.deepcopy(original)
            value[field] = changed
            with self.subTest(field=field), self.assertRaises(ValueError):
                PaperTestBudget.from_mapping(value)

    def test_budget_source_tampering_is_rejected_and_original_is_preserved(self):
        budget = self.budget()
        value = budget.to_dict()
        value["basis"]["equity_usd"] = "81525.11"
        value.update(budget_amounts("81525.11"))
        changed = PaperTestBudget.from_mapping(value)
        with self.assertRaises(ValueError):
            validate_budget_source(changed, self.f.events)
        validate_budget_source(budget, self.f.events)

    def test_float_fractional_cent_and_nonpositive_equity_reject(self):
        for value in (81525.11, "1.001", "0", "-1", "0.01", "NaN", "1e5"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                budget_amounts(value)


if __name__ == "__main__":
    unittest.main()
