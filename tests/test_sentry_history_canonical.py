"""Optional real canonical H25 integration with synthetic, network-free prices."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from blackpod_build_week.sentry_history_recovery import CanonicalBridge, RecoveryOptions, recover


@unittest.skipUnless(os.environ.get("BATTLESTAR_PATH"), "explicit canonical checkout not configured")
class CanonicalHistoryRecoveryTests(unittest.TestCase):
    def test_real_canonical_staging_cache_resume_and_complete_handoff_without_network(self):
        canonical = CanonicalBridge(Path(os.environ["BATTLESTAR_PATH"]))
        from microcap_sentry.cli import prepare_validation_universe_command
        from microcap_sentry.universe.providers import UrllibHttpTransport

        class YFPricesMissingError(Exception):
            pass

        with tempfile.TemporaryDirectory() as temporary, patch.object(
            UrllibHttpTransport, "get", side_effect=AssertionError("unexpected source network call"),
        ), patch("socket.create_connection", side_effect=AssertionError("unexpected socket")):
            artifacts = Path(temporary).resolve() / "artifacts"
            prepared = prepare_validation_universe_command(
                config_path=canonical.root / "configs/microcap_sentry.example.yaml",
                target_count=3, as_of=date(2026, 7, 15), offline=True,
                fixture=canonical.root / "tests/microcap_sentry/fixtures/validation_universe",
                output_root=artifacts / "universes",
            )
            package = Path(prepared["package_path"])
            symbols = prepared["provisional_symbols"]
            self.assertGreater(len(symbols), 3)
            old_csv = package / "h25_daily" / canonical.filename(symbols[0])
            original = b"date,open,high,low,close,adj_close,volume\n2026-07-14,10,12,9,11,11,10000\n"
            old_csv.write_bytes(original)
            clock = [datetime(2026, 9, 17, tzinfo=timezone.utc).timestamp()]
            calls = []

            def sleep(seconds):
                clock[0] += seconds

            class Provider:
                @staticmethod
                def Ticker(symbol):
                    class Ticker:
                        def history(self, **kwargs):
                            calls.append((symbol, kwargs))
                            if symbol == symbols[-1]:
                                raise YFPricesMissingError("synthetic unavailable result")
                            return [{"Date": date(2026, 6, 16) + timedelta(days=offset),
                                     "Open": 10, "High": 12, "Low": 9, "Close": 11,
                                     "Adj Close": 11, "Volume": 10000} for offset in range(20)]
                    return Ticker()

            parameters = dict(artifacts_root=artifacts, now=lambda: clock[0], sleep=sleep,
                              provider_factory=lambda root: Provider)
            result = recover(package, canonical, adopt_existing=True, offline=True, **parameters)
            self.assertEqual(result["ready"], 1)
            self.assertEqual(calls, [])
            self.assertEqual(old_csv.read_bytes(), original)
            paused = recover(package, canonical, options=RecoveryOptions(max_requests=1), **parameters)
            self.assertEqual(paused["status"], "BUDGET_PAUSED")
            self.assertEqual(paused["ready"], 2)
            self.assertFalse((package / "bootstrap_backfill_manifest.json").exists())
            result = recover(package, canonical, publish_h25=True,
                             options=RecoveryOptions(max_requests=100), **parameters)
            self.assertEqual(result["status"], "COMPLETE")
            self.assertEqual(result["ready"], len(symbols) - 1)
            self.assertEqual(result["unavailable"], 1)
            self.assertEqual(result["pending"], 0)
            self.assertNotIn(symbols[0], [symbol for symbol, _ in calls])
            self.assertEqual(len(calls), len(symbols))  # one adopted, one extra missing-data retry
            self.assertTrue(all(kwargs["end"] == "2026-07-16" for _, kwargs in calls))
            self.assertTrue(all(kwargs["raise_errors"] for _, kwargs in calls))
            self.assertEqual((package / "recovery/original_daily" / old_csv.name).read_bytes(), original)
            status = canonical.validate_handoff(canonical.load(package))
            self.assertTrue(status["complete"])
            manifest = json.loads((package / "bootstrap_backfill_manifest.json").read_text())
            self.assertEqual(manifest["symbol_count_requested"], len(symbols))
            self.assertEqual(manifest["symbol_count_failed"], 1)
            self.assertEqual([row["symbol"] for row in manifest["series"]], symbols)
            self.assertIn("RecordedUnavailable", manifest["series"][-1]["blockers"][0])
            count = len(calls)
            again = recover(package, canonical, publish_h25=True, **parameters)
            self.assertEqual(again["status"], "COMPLETE")
            self.assertEqual(len(calls), count)


if __name__ == "__main__":
    unittest.main()
