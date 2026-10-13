"""Synthetic GET-only account checks; sockets, subprocesses and brokers forbidden."""
from __future__ import annotations

import io
from http.client import IncompleteRead
import json
import os
from pathlib import Path
import socket
import stat
import tempfile
import unittest
from unittest import mock
from urllib.error import HTTPError, URLError
from urllib.request import Request

from blackpod_build_week import paper_account_probe as probe


NOW = "2026-10-12T01:00:00Z"
PAPER_ENV = b'''# Synthetic fixture credentials, not a broker account.
export ALPACA_KEY_ID_PAPER="fixture-paper-id" # inline comment
ALPACA_SECRET_KEY_PAPER='fixture-paper-secret'
ALPACA_BASE_URL_PAPER=https://paper-api.alpaca.markets/v2
ALPACA_KEY_ID_LIVE=$UNRELATED_LIVE_VALUE
OPENAI_API_KEY=unrelated-provider-value
'''
NAVIGATOR_ENV = b"APCA_API_KEY_ID=fixture-paper-id\nAPCA_API_SECRET_KEY=fixture-paper-secret\nALPACA_PAPER=true\n"
GALACTICA_YAML = b'''# Synthetic legacy credential fixture.
alpaca:
  key_id: "fixture-paper-id"
  secret_key: 'fixture-paper-secret'
other_provider:
  key: unrelated-provider-value
'''


def body(value):
    return probe.PaperResponse(200, json.dumps(value).encode())


def fixture_order(identity="order-1", symbol="MSFT", **values):
    result = {"id": identity, "client_order_id": "session:MSFT:fixture", "symbol": symbol,
              "status": "new", "side": "buy", "type": "limit", "time_in_force": "day",
              "qty": "2", "notional": None, "filled_qty": "0", "filled_avg_price": None,
              "submitted_at": NOW, "legs": None, "unknown_field": "do-not-retain"}
    result.update(values)
    return result


class FakeTransport:
    def __init__(self):
        self.calls = []
        self.values = {
            "/v2/account": {"id": "fixture-account", "status": "ACTIVE", "trading_blocked": False,
                            "account_blocked": False, "equity": "100000.00", "cash": "99500.00",
                            "currency": "USD", "account_number": "private-number",
                            "api_secret": "fixture-paper-secret"},
            "/v2/positions": [{"symbol": "MSFT", "qty": "2", "side": "long", "market_value": "500.00",
                              "avg_entry_price": "240.00", "current_price": "250.00", "unknown_field": "do-not-retain"}],
            "/v2/orders?status=open&limit=500&nested=true": [fixture_order()],
            "/v2/clock": {"timestamp": NOW, "is_open": False, "next_open": "2026-10-12T13:30:00Z",
                          "next_close": "2026-10-12T20:00:00Z", "unknown_field": "do-not-retain"},
        }

    def __call__(self, path, headers, timeout):
        self.calls.append((path, dict(headers), timeout))
        value = self.values[path]
        if isinstance(value, Exception):
            raise value
        return value if isinstance(value, probe.PaperResponse) else body(value)


class PaperAccountProbeTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name).resolve()
        self.source = self.base / "credentials" / "paper.env"
        self.source.parent.mkdir()
        self.source.write_bytes(PAPER_ENV)
        self.output = self.base / "output" / "auto-trading-paper-check"
        self.fetch = FakeTransport()
        self.enterContext(mock.patch.object(socket.socket, "connect", side_effect=AssertionError("network forbidden")))
        self.enterContext(mock.patch("subprocess.Popen", side_effect=AssertionError("process forbidden")))
        self.enterContext(mock.patch("subprocess.run", side_effect=AssertionError("provider forbidden")))

    def run_probe(self, **changes):
        values = {"expected_account_id": "fixture-account", "transport": self.fetch, "now": lambda: NOW}
        values.update(changes)
        return probe.probe_paper_account(self.source, "PAPER_ENV", self.output, **values)

    def test_literal_paper_and_navigator_formats_never_select_live_keys(self):
        credentials = probe.parse_credentials(PAPER_ENV, "PAPER_ENV")
        self.assertEqual(credentials.key_id, "fixture-paper-id")
        self.assertEqual(credentials.secret_key, "fixture-paper-secret")
        self.assertNotIn(credentials.secret_key, repr(credentials))
        self.assertEqual(probe.parse_credentials(NAVIGATOR_ENV, "NAVIGATOR_ENV"), credentials)
        self.assertEqual(probe.parse_credentials(PAPER_ENV.replace(b"=", b" = "), "PAPER_ENV"), credentials)

    def test_galactica_yaml_selects_only_literal_alpaca_pair_with_existing_dependency(self):
        self.assertEqual(probe.parse_credentials(GALACTICA_YAML, "GALACTICA_YAML"),
                         probe.parse_credentials(PAPER_ENV, "PAPER_ENV"))
        self.assertEqual(probe.parse_credentials(GALACTICA_YAML + b"unrelated_provider:\n  key: other-value\n", "GALACTICA_YAML"),
                         probe.parse_credentials(PAPER_ENV, "PAPER_ENV"))

    def test_galactica_yaml_duplicate_selected_fields_and_root_mapping_reject(self):
        for raw in (GALACTICA_YAML + b"alpaca:\n  key_id: ambiguous\n  secret_key: ambiguous\n",
                    GALACTICA_YAML.replace(b"  key_id:", b"  key_id: duplicate\n  key_id:"),
                    GALACTICA_YAML.replace(b"  secret_key:", b"  secret_key: duplicate\n  secret_key:"),
                    b"- alpaca\n", b"alpaca: null\n", b"alpaca: {}\n"):
            with self.subTest(raw=raw[:20]), self.assertRaises(probe.PaperProbeError):
                probe.parse_credentials(raw, "GALACTICA_YAML")

    def test_galactica_yaml_values_tags_expansions_and_errors_do_not_expose_secrets(self):
        for raw in (GALACTICA_YAML.replace(b'"fixture-paper-id"', b"123"),
                    GALACTICA_YAML.replace(b'"fixture-paper-id"', b"false"),
                    GALACTICA_YAML.replace(b"'fixture-paper-secret'", b"null"),
                    GALACTICA_YAML.replace(b"fixture-paper-secret", b"$SECRET"),
                    GALACTICA_YAML.replace(b"fixture-paper-secret", b"`command`"),
                    b"alpaca:\n  key_id: [fixture-paper-id]\n  secret_key: 'fixture-paper-secret'\n",
                    b"alpaca:\n  key_id: !!python/object/apply:os.system ['must-not-run']\n  secret_key: literal\n",
                    GALACTICA_YAML + b"broken: [fixture-paper-secret\n"):
            with self.subTest(raw=raw[:20]), self.assertRaises(probe.PaperProbeError) as caught:
                probe.parse_credentials(raw, "GALACTICA_YAML")
            self.assertNotIn("fixture-paper-secret", str(caught.exception))

    def test_galactica_yaml_optional_configuration_cannot_redirect_to_live(self):
        for optional in (b"  paper: false\n", b"  mode: LIVE\n", b"  base_url: https://api.alpaca.markets/v2\n",
                         b"  paper: true\n  paper: false\n"):
            raw = GALACTICA_YAML.replace(b"other_provider:", optional + b"other_provider:")
            with self.subTest(optional=optional), self.assertRaises(probe.PaperProbeError):
                probe.parse_credentials(raw, "GALACTICA_YAML")
        raw = GALACTICA_YAML.replace(b"other_provider:",
            b"  paper: true\n  mode: PAPER\n  base_url: https://paper-api.alpaca.markets/v2\nother_provider:")
        probe.parse_credentials(raw, "GALACTICA_YAML")

    def test_galactica_yaml_cli_uses_unchanged_fixed_paper_gets_and_retains_no_credentials(self):
        self.source.write_bytes(GALACTICA_YAML)
        original = self.source.read_bytes()
        args = ["--credential-source", str(self.source), "--credential-format", "GALACTICA_YAML", "--output-root", str(self.output)]
        with mock.patch.object(probe, "paper_get", side_effect=self.fetch), mock.patch("sys.stdout", new_callable=io.StringIO) as stdout:
            self.assertEqual(probe.main(args), 0)
        summary = json.loads(stdout.getvalue())
        report = json.loads(Path(summary["evidence_path"]).read_bytes())
        self.assertEqual(report["credential_source"]["format"], "GALACTICA_YAML")
        self.assertEqual([call[0] for call in self.fetch.calls], [path for _, path in probe.ENDPOINTS])
        self.assertEqual(self.source.read_bytes(), original)
        for secret in ("fixture-paper-id", "fixture-paper-secret", "unrelated-provider-value"):
            self.assertNotIn(secret, json.dumps(report))
            self.assertNotIn(secret, stdout.getvalue())

    def test_paper_origin_cannot_be_live_redirect_proxy_or_custom_host(self):
        for url in ("http://paper-api.alpaca.markets", "https://api.alpaca.markets/v2",
                    "https://paper-api.alpaca.markets.evil.invalid", "https://user:pass@paper-api.alpaca.markets",
                    "https://paper-api.alpaca.markets:444/v2", "https://paper-api.alpaca.markets/v2/account",
                    "https://paper-api.alpaca.markets/?x=1", "https://paper-api.alpaca.markets/#fragment"):
            with self.subTest(url=url), self.assertRaises(probe.PaperProbeError):
                probe.parse_credentials(PAPER_ENV.replace(b"https://paper-api.alpaca.markets/v2", b"'" + url.encode() + b"'"), "PAPER_ENV")
        for url in ("https://paper-api.alpaca.markets", "https://paper-api.alpaca.markets/",
                    "https://paper-api.alpaca.markets:443/v2", "https://paper-api.alpaca.markets/v2/"):
            with self.subTest(url=url):
                probe.parse_credentials(PAPER_ENV.replace(b"https://paper-api.alpaca.markets/v2", url.encode()), "PAPER_ENV")

    def test_selected_duplicates_expansion_shell_syntax_and_missing_keys_reject(self):
        for raw in (PAPER_ENV + b"ALPACA_KEY_ID_PAPER=other\n", PAPER_ENV.replace(b"fixture-paper-id", b"$PAPER_KEY"),
                    PAPER_ENV.replace(b"fixture-paper-id", b"$(some_command)"),
                    PAPER_ENV.replace(b"fixture-paper-id", b"`some_command`"),
                    PAPER_ENV + b"ALPACA_SECRET_KEY_PAPER=bad; command\n",
                    b"ALPACA_KEY_ID_PAPER=only-one\n", b"\xff", b"a" * (probe.MAX_CREDENTIAL_BYTES + 1)):
            with self.subTest(raw=raw[:20]), self.assertRaises(probe.PaperProbeError):
                probe.parse_credentials(raw, "PAPER_ENV")
        for raw in (NAVIGATOR_ENV.replace(b"true", b"false"), NAVIGATOR_ENV.replace(b"true", b"")):
            with self.assertRaises(probe.PaperProbeError):
                probe.parse_credentials(raw, "NAVIGATOR_ENV")

    def test_success_retains_only_selected_facts_and_grants_no_execution(self):
        original = self.source.read_bytes()
        result = self.run_probe()
        report = result["report"]
        self.assertEqual(report["result"], "CONFIRMED")
        self.assertTrue(report["account_authenticated"])
        self.assertTrue(report["account_identity_verified"])
        self.assertTrue(report["complete"])
        self.assertEqual([call[0] for call in self.fetch.calls], [path for _, path in probe.ENDPOINTS])
        self.assertTrue(all(item["method"] == "GET" for item in report["requests"]))
        self.assertEqual(report["orders_submitted"], 0)
        for field in ("snapshot_atomic", "execution_authorized", "capital_policy_activated", "auto_trading_enabled",
                      "account_ownership_verified", "runtime_profile_verified", "realized_pnl_evaluated"):
            self.assertFalse(report[field])
        raw = Path(result["evidence_path"]).read_bytes()
        for excluded in (b"fixture-paper-id", b"fixture-paper-secret", b"do-not-retain", b"private-number", b"api_secret"):
            self.assertNotIn(excluded, raw)
        self.assertEqual(self.source.read_bytes(), original)
        self.assertEqual(json.loads(raw), report)
        self.assertEqual(stat.S_IMODE(Path(result["evidence_path"]).stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(self.output.stat().st_mode), 0o700)
        self.assertEqual(Path(result["evidence_path"]).name, "paper-probe-" + result["evidence_sha256"] + ".json")

    def test_401_retained_without_raw_error_or_additional_calls(self):
        self.fetch.values["/v2/account"] = probe.PaperResponse(401, b"secret server message fixture-paper-secret")
        result = self.run_probe()
        report = result["report"]
        self.assertEqual(report["result"], "NOT_CONFIRMED")
        self.assertEqual(len(self.fetch.calls), 1)
        self.assertEqual(report["requests"][0]["http_status"], 401)
        self.assertEqual(report["requests"][0]["failure_code"], "HTTP_ERROR")
        self.assertFalse(report["account_authenticated"])
        self.assertIsNone(report["account"])
        self.assertIsNone(report["positions"])
        self.assertIsNone(report["open_orders"])
        self.assertNotIn(b"secret server message", Path(result["evidence_path"]).read_bytes())

    def test_partial_failure_preserves_account_authentication_not_empty_book(self):
        self.fetch.values["/v2/positions"] = probe.PaperTransportError("TIMEOUT")
        report = self.run_probe()["report"]
        self.assertTrue(report["account_authenticated"])
        self.assertTrue(report["account_identity_verified"])
        self.assertEqual(report["account"]["id"], "fixture-account")
        self.assertIsNone(report["positions"])
        self.assertIsNone(report["open_orders"])
        self.assertEqual(report["result"], "NOT_CONFIRMED")
        self.assertEqual(len(self.fetch.calls), 2)
        self.assertEqual(report["requests"][-1]["path"], "/v2/positions")

    def test_negative_cash_and_blocked_accounts_retain_authenticated_balances(self):
        for change in ({"cash": "-5"}, {"equity": "0"}, {"status": "APPROVAL_PENDING"},
                       {"trading_blocked": True}, {"account_blocked": True}, {"currency": "EUR"}):
            self.fetch = FakeTransport()
            self.fetch.values["/v2/account"].update(change)
            with self.subTest(change=change):
                report = self.run_probe()["report"]
                self.assertEqual(report["result"], "NOT_CONFIRMED")
                self.assertTrue(report["account_authenticated"])
                self.assertTrue(report["account_identity_verified"])
                self.assertEqual(report["account"][next(iter(change))], next(iter(change.values())))
                self.assertEqual(report["requests"][0]["failure_code"], "ACCOUNT_CONSTRAINTS_UNSUPPORTED")
                self.assertEqual(len(self.fetch.calls), 1)

    def test_expected_identity_mismatch_never_confirms_or_queries_positions(self):
        report = self.run_probe(expected_account_id="different-account")["report"]
        self.assertTrue(report["account_authenticated"])
        self.assertFalse(report["account_identity_verified"])
        self.assertEqual(report["requests"][0]["failure_code"], "ACCOUNT_ID_MISMATCH")
        self.assertEqual(len(self.fetch.calls), 1)

    def test_full_order_page_and_nested_duplicate_ids_fail_closed(self):
        for orders in ([fixture_order("order-" + str(index)) for index in range(500)],
                       [fixture_order(legs=[fixture_order()])], [fixture_order(status="filled")],
                       [fixture_order(status={"invalid": True})]):
            self.fetch = FakeTransport()
            self.fetch.values[probe.ENDPOINTS[2][1]] = orders
            with self.subTest(count=len(orders)):
                report = self.run_probe()["report"]
                self.assertTrue(report["account_authenticated"])
                self.assertIsNone(report["open_orders"])
                self.assertEqual(report["result"], "NOT_CONFIRMED")
                self.assertEqual(report["requests"][-1]["failure_code"], "BROKER_DATA_UNVERIFIED")
                self.assertEqual(len(self.fetch.calls), 3)

    def test_nested_legs_are_preserved_and_validated_without_making_them_executable(self):
        self.fetch.values[probe.ENDPOINTS[2][1]] = [fixture_order(legs=[fixture_order("child-order", "AAPL")])]
        report = self.run_probe()["report"]
        self.assertEqual(report["open_orders"][0]["legs"][0]["symbol"], "AAPL")
        self.assertFalse(report["execution_authorized"])

    def test_malformed_nonfinite_duplicate_oversized_broker_json_retains_failure(self):
        for response in (probe.PaperResponse(200, b'{"id":"x","id":"y"}'),
                         probe.PaperResponse(200, b'{"equity":NaN}'),
                         probe.PaperResponse(200, b"not-json"),
                         probe.PaperResponse(200, b'{"oversized_integer":' + b"1" * 5000 + b"}"),
                         probe.PaperResponse(200, b"x" * (probe.MAX_RESPONSE_BYTES + 1)),
                         body({"id": "fixture-account", "status": "ACTIVE", "trading_blocked": "false", "equity": "1", "cash": "1"})):
            self.fetch = FakeTransport()
            self.fetch.values["/v2/account"] = response
            with self.subTest(bytes=len(response.body)):
                report = self.run_probe()["report"]
                self.assertEqual(report["result"], "NOT_CONFIRMED")
                self.assertEqual(report["requests"][0]["http_status"], 200)
                self.assertEqual(report["requests"][0]["failure_code"], "BROKER_DATA_UNVERIFIED")

    def test_position_duplicates_and_sign_inconsistency_are_not_a_complete_book(self):
        position = self.fetch.values["/v2/positions"][0]
        for positions in ([position, position], [{**position, "qty": "-2"}], [{**position, "market_value": "0"}]):
            self.fetch = FakeTransport()
            self.fetch.values["/v2/positions"] = positions
            with self.subTest(count=len(positions)):
                report = self.run_probe()["report"]
                self.assertEqual(report["result"], "NOT_CONFIRMED")
                self.assertIsNone(report["positions"])

    def test_identical_capture_bytes_retry_without_overwriting_retained_evidence(self):
        first = self.run_probe()
        before = Path(first["evidence_path"]).stat()
        second = self.run_probe()
        self.assertTrue(first["written"])
        self.assertFalse(second["written"])
        self.assertEqual(first["evidence_path"], second["evidence_path"])
        self.assertEqual(Path(first["evidence_path"]).stat().st_mtime_ns, before.st_mtime_ns)
        self.assertEqual(len(list(self.output.iterdir())), 1)

    def test_unsafe_source_or_output_rejects_before_any_calls_or_writes(self):
        original_output = self.output
        bad_roots = [self.source.parent, self.source.parent / "output", self.base,
                     self.base / "missions" / "probe", self.base / "src" / "probe", self.base / "output" / ".." / "probe"]
        for output in bad_roots:
            with self.subTest(output=output), self.assertRaises(probe.PaperProbeError):
                probe.probe_paper_account(self.source, "PAPER_ENV", output, transport=self.fetch)
        symlink = self.base / "link"
        symlink.symlink_to(self.source.parent, target_is_directory=True)
        with self.assertRaises(probe.PaperProbeError):
            probe.probe_paper_account(self.source, "PAPER_ENV", symlink / "probe", transport=self.fetch)
        secret_link = self.base / "credentials" / "linked.env"
        secret_link.symlink_to(self.source)
        with self.assertRaises(probe.PaperProbeError):
            probe.probe_paper_account(secret_link, "PAPER_ENV", original_output, transport=self.fetch)
        secret_hardlink = self.base / "credentials" / "hardlinked.env"
        os.link(self.source, secret_hardlink)
        with self.assertRaises(probe.PaperProbeError):
            self.run_probe()
        self.assertEqual(self.fetch.calls, [])
        self.assertFalse(original_output.exists())

    def test_source_and_producer_markers_protect_output_before_any_calls(self):
        for marker in ("blackwell_navigator_trickle.py", "mission_snapshot.json", ".journal.lock", "ledger.lock"):
            root = self.base / ("protected-" + marker.replace(".", "_"))
            root.mkdir()
            (root / marker).write_text("synthetic marker")
            with self.subTest(marker=marker), self.assertRaises(probe.PaperProbeError):
                probe.probe_paper_account(self.source, "PAPER_ENV", root / "probe", transport=self.fetch)
        self.assertEqual(self.fetch.calls, [])

    def test_transport_is_get_fixed_tls_host_noproxy_and_refuses_redirects(self):
        response = mock.MagicMock()
        response.status = 200
        response.geturl.return_value = probe.PAPER_ORIGIN + "/v2/account"
        response.read.return_value = b"{}"
        response.__enter__.return_value = response
        opener = mock.Mock()
        opener.open.return_value = response
        with mock.patch.object(probe, "build_opener", return_value=opener) as build:
            result = probe.paper_get("/v2/account", {"APCA-API-KEY-ID": "fake"}, 10)
        self.assertEqual(result.body, b"{}")
        request = opener.open.call_args.args[0]
        self.assertEqual(request.get_method(), "GET")
        self.assertEqual(request.full_url, probe.PAPER_ORIGIN + "/v2/account")
        self.assertEqual(build.call_args.args[0].proxies, {})
        with self.assertRaises(probe.PaperTransportError):
            probe._RefuseRedirects().redirect_request(Request(probe.PAPER_ORIGIN), None, 302, "raw message", {}, "https://evil.invalid")
        with self.assertRaises(probe.PaperTransportError):
            probe.paper_get("https://evil.invalid/v2/account", {}, 10)

    def test_transport_does_not_read_error_body_or_return_raw_exception(self):
        error = HTTPError(probe.PAPER_ORIGIN + "/v2/account", 401, "sensitive-raw-error", {}, io.BytesIO(b"secret-body"))
        opener = mock.Mock()
        opener.open.side_effect = error
        with mock.patch.object(probe, "build_opener", return_value=opener), self.assertRaises(probe.PaperTransportError) as caught:
            probe.paper_get("/v2/account", {}, 10)
        self.assertEqual(caught.exception.code, "HTTP_ERROR")
        self.assertEqual(caught.exception.http_status, 401)
        self.assertNotIn("sensitive-raw-error", str(caught.exception))
        for error, code in ((URLError("sensitive-raw-error"), "URL_ERROR"), (TimeoutError("secret"), "TIMEOUT"),
                            (IncompleteRead(b"sensitive-response-body", 100), "TRANSPORT_ERROR")):
            opener.open.side_effect = error
            with mock.patch.object(probe, "build_opener", return_value=opener), self.assertRaises(probe.PaperTransportError) as caught:
                probe.paper_get("/v2/account", {}, 10)
            self.assertEqual(caught.exception.code, code)

    def test_cli_success_and_failure_exit_codes_do_not_print_secrets(self):
        args = ["--credential-source", str(self.source), "--credential-format", "PAPER_ENV", "--output-root", str(self.output)]
        for authenticated in (True, False):
            self.fetch = FakeTransport()
            if not authenticated:
                self.fetch.values["/v2/account"] = probe.PaperResponse(401, b"secret-error")
            with mock.patch.object(probe, "paper_get", side_effect=self.fetch), mock.patch("sys.stdout", new_callable=io.StringIO) as stdout:
                code = probe.main(args)
            self.assertEqual(code, 0 if authenticated else 2)
            summary = json.loads(stdout.getvalue())
            self.assertEqual(summary["result"], "CONFIRMED" if authenticated else "NOT_CONFIRMED")
            self.assertFalse(summary["auto_trading_enabled"])
            for secret in ("fixture-paper-id", "fixture-paper-secret", "secret-error"):
                self.assertNotIn(secret, stdout.getvalue())

    def test_cli_relative_output_root_resolves_under_current_checkout(self):
        # Use a real relative output path without traversal by selecting a
        # temporary current directory; no repository files are created.
        previous = Path.cwd()
        try:
            os.chdir(self.base)
            args = ["--credential-source", str(self.source), "--credential-format", "PAPER_ENV",
                    "--output-root", "output/auto-trading-paper-check"]
            with mock.patch.object(probe, "paper_get", side_effect=self.fetch), mock.patch("sys.stdout", new_callable=io.StringIO):
                self.assertEqual(probe.main(args), 0)
        finally:
            os.chdir(previous)
        self.assertEqual(len(list(self.output.glob("paper-probe-*.json"))), 1)

    def test_fractional_capture_times_compare_instants_and_backward_time_rejects(self):
        times = iter([NOW] + ["2026-10-12T01:00:00." + str(index) + "Z" for index in range(1, 10)])
        report = self.run_probe(now=lambda: next(times))["report"]
        self.assertEqual(report["result"], "CONFIRMED")
        self.fetch = FakeTransport()
        times = iter([NOW, "2026-10-12T00:59:59Z"])
        with self.assertRaises(probe.PaperProbeError):
            self.run_probe(now=lambda: next(times))
        self.assertEqual(self.fetch.calls, [])


if __name__ == "__main__":
    unittest.main()
