"""Differential original-format replay and bounded invocation-cache safety."""
import copy
import json
from contextlib import redirect_stdout
import io
from types import SimpleNamespace
from unittest.mock import patch

import test_train_market_capture as fixtures
from blackpod_build_week import train_market_capture as original
from blackpod_build_week import train_market_capture_incremental as incremental
from blackpod_build_week.hashing import sha256_bytes


class IncrementalCaptureRunnerTests(fixtures.CaptureRunnerTests):
    """Run every original runner behavior test against the additive runner."""
    def run_capture(self, *, plan=None, budget=None, source=True, transport=None, clock=None):
        return incremental.capture_train_quotes_incremental(plan or self.plan, self.root, fixtures.CREDS,
            source_blobs=self.blobs if source else None, request_budget=budget,
            transport=transport or self.transport, clock=clock or (lambda: fixtures.CAPTURED),
            sleeper=self.sleeps.append)

    def original_capture(self, root, budget=None):
        return original.capture_train_quotes(self.plan, root, fixtures.CREDS,
            source_blobs=self.blobs, request_budget=budget,
            transport=fixtures.AuthoredTransport(self.quotes), clock=lambda: fixtures.CAPTURED,
            sleeper=lambda seconds: None)

    def test_full_capture_is_byte_identical_to_original_checkpoint_format(self):
        old_root = self.root.parent / "original"
        before = self.original_capture(old_root)
        after = self.run_capture()
        self.assertEqual(before, {key: value for key, value in after.items() if key != "runner_method_version"})
        old = original.read_capture(self.plan, old_root, exported_at=fixtures.EXPORTED)
        self.assertEqual(old, self.snapshot())

    def test_original_and_incremental_runners_can_resume_each_other(self):
        self.original_capture(self.root, budget=2)
        second = self.run_capture(budget=2, source=False)
        self.assertEqual(second["complete_segment_count"], 4)
        third = self.original_capture(self.root, budget=2)
        self.assertEqual(third["complete_segment_count"], 6)
        proof = self.snapshot()
        blobs = {sha256_bytes(raw): raw for raw in proof["evidence"].values()}
        self.assertEqual(original.validate_capture_snapshot(self.plan, proof["snapshot"], blobs)["snapshot"], proof["snapshot"])

    def test_full_boundary_replay_occurs_twice_per_successful_invocation(self):
        with patch.object(original, "_load", wraps=original._load) as replay:
            result = self.run_capture()
        self.assertEqual(result["requests_this_invocation"], 12)
        self.assertEqual(replay.call_count, 2)

    def test_tamper_during_invocation_is_rejected_by_final_full_replay(self):
        count = 0
        def transport(query, credentials, **kwargs):
            nonlocal count
            count += 1
            if count == 2:
                leaf = self.root / "source/attempt-000001.body.raw"
                leaf.write_bytes(leaf.read_bytes() + b" ")
            return self.transport(query, credentials, **kwargs)
        with self.assertRaisesRegex(ValueError, "hash or size"):
            self.run_capture(budget=2, transport=transport)
        with self.assertRaises(ValueError):
            self.snapshot()

    def test_duplicate_across_pages_is_not_lost_by_temporary_cursor_state(self):
        native = None
        def transport(query, credentials, **kwargs):
            nonlocal native
            if native is None:
                native = json.loads(self.transport(query, credentials, **kwargs).body)
                native["quotes"] = {"SYNTHA": native["quotes"]["SYNTHA"]}
                native["next_page_token"] = "same-row-again"
            value = copy.deepcopy(native)
            if "page_token" in query:
                value["next_page_token"] = None
            return original.MarketResponse(200, original.canonical_json_bytes(value))
        result = self.run_capture(budget=2, transport=transport)
        self.assertEqual(result["stop_reason"], "INVALID_RESPONSE")
        self.assertEqual(result["complete_segment_count"], 0)
        self.assertEqual(len(self.snapshot()["snapshot"]["segments"][0]["pages"]), 1)

    def test_boolean_and_negative_invocation_limits_reject_before_get(self):
        for value in (True, -1, 33):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.run_capture(budget=value)
        self.assertEqual(self.transport.calls, [])

    def test_returned_method_is_separate_and_all_authority_stays_disabled(self):
        result = self.run_capture(budget=1)
        self.assertEqual(result["runner_method_version"], "blackpod.invocation_local_train_capture.v2")
        self.assertFalse(result["auto_trading_enabled"])
        self.assertEqual(result["orders_submitted"], 0)

    def test_cli_incremental_path_is_explicit_and_default_path_is_preserved(self):
        from blackpod_build_week import train_market_evidence_cli as cli
        keys = self.root.parent / "keys" / "fixture.yaml"
        keys.parent.mkdir()
        keys.write_bytes(b"EXPLICIT_FIXTURE_ONLY_NOT_A_KEY")
        arguments = ["capture", "--plan-event-id", "journal-event-" + "a" * 64,
            "--journal-root", str(self.root.parent / "journal"),
            "--capture-root", str(self.root), "--credential-source", str(keys),
            "--credential-format", "GALACTICA_YAML", "--request-budget", "2", "--allow-market-data-get"]
        for opt_in in (False, True):
            with self.subTest(opt_in=opt_in), \
                    patch.object(cli.JournalStore, "verified_contents", return_value=((), {})), \
                    patch.object(cli, "registered_capture_context", return_value={"plan": SimpleNamespace(evidence_scope="RETAINED_HISTORY_RESEARCH")}), \
                    patch("blackpod_build_week.paper_account_probe.parse_credentials", return_value=fixtures.CREDS), \
                    patch.object(original, "capture_train_quotes", return_value={"auto_trading_enabled": False}) as old, \
                    patch.object(incremental, "capture_train_quotes_incremental", return_value={"auto_trading_enabled": False}) as new, \
                    redirect_stdout(io.StringIO()):
                code = cli.main(arguments + (["--verified-invocation-cache"] if opt_in else []))
            self.assertEqual(code, 0)
            self.assertEqual(old.call_count, int(not opt_in))
            self.assertEqual(new.call_count, int(opt_in))
            called = new if opt_in else old
            self.assertEqual(called.call_args.kwargs["request_budget"], 2)

    def test_cli_opt_in_still_rejects_fixture_before_reading_credentials(self):
        from blackpod_build_week import train_market_evidence_cli as cli
        with patch.object(cli.JournalStore, "verified_contents", return_value=((), {})), \
                patch.object(cli, "registered_capture_context", return_value={"plan": self.plan}), \
                patch.object(cli, "_read", side_effect=AssertionError("credentials forbidden")), \
                redirect_stdout(io.StringIO()) as output:
            code = cli.main(["capture", "--plan-event-id", "journal-event-" + "a" * 64,
                "--journal-root", str(self.root.parent / "journal"),
                "--capture-root", str(self.root), "--credential-source", "unread.yaml",
                "--credential-format", "GALACTICA_YAML", "--request-budget", "2",
                "--allow-market-data-get", "--verified-invocation-cache"])
        self.assertEqual(code, 2)
        self.assertIn("real-history", json.loads(output.getvalue())["error"])
