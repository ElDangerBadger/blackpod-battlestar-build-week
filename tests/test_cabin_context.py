from __future__ import annotations

import json
import tempfile
import unittest
from email.message import Message
from pathlib import Path

from blackpod_build_week.cabin_context import (
    CABIN_CONTEXT_SCHEMA_VERSION,
    NAVIGATOR_MARKET_PATH,
    PORTFOLIO_SNAPSHOT_PATH,
    CabinContext,
    CabinContextError,
    CabinContextConflictError,
    CaptureStatus,
    CaptureTransport,
    NavigatorMarket,
    PortfolioSnapshot,
    capture_cabin_context,
    fetch_navigator_market,
)
from blackpod_build_week.contracts import ContractValidationError, MissionRequest
from blackpod_build_week.hashing import sha256_bytes
from blackpod_build_week.mission_store import MissionStore


CAPTURED_AT = "2026-07-19T18:30:00Z"
REVISION = "a" * 40


def request() -> MissionRequest:
    return MissionRequest.from_mapping(
        {
            "schema_version": "blackpod.mission_request.v1",
            "request_id": "request-cabin-context-001",
            "mission_id": "mission-cabin-context-001",
            "run_mode": "LIVE",
            "symbol": "AAPL",
            "requested_at": CAPTURED_AT,
            "operator_id": "operator-cabin",
            "metadata": {},
        }
    )


def market_value() -> dict:
    return {
        "symbol": "AAPL",
        "name": "Apple Inc.",
        "category": "equity",
        "timeframe": "1d",
        "ma_period": 250,
        "currency": "USD",
        "points": [
            {"t": 100, "o": 190.0, "h": 192.0, "l": 189.0, "c": 191.0, "v": 1000, "ma": None, "atr": None},
            {"t": 200, "o": 191.0, "h": 194.0, "l": 190.0, "c": 193.0, "v": 1200, "ma": 188.0, "atr": 3.0},
        ],
        "summary": {
            "last_price": 193.0,
            "last_ma": 188.0,
            "pct_vs_ma": 2.6596,
            "position": "above",
            "trend_slope_pct": 0.5,
            "volatility": "moderate",
            "atr": 3.0,
            "atr_pct": 1.5544,
            "ma_period": 250,
            "bar_count": 2,
        },
    }


def market_bytes() -> bytes:
    # Deliberately not canonical formatting: the exact validated response bytes
    # must be preserved by the presentation supplement.
    return (json.dumps(market_value(), separators=(",", ":")) + "\n").encode()


def portfolio_value() -> dict:
    return {
        "schema_version": "blackpod.portfolio_snapshot.v1",
        "captured_at": CAPTURED_AT,
        "source_identity": "local-paper-ledger",
        "mode": "LIVE",
        "account_type": "PAPER",
        "currency": "USD",
        "cash": 8000.0,
        "equity": 10000.0,
        "total_exposure": 2000.0,
        "positions": [
            {
                "symbol": "AAPL",
                "name": "Apple Inc.",
                "quantity": 10,
                "market_value": 1930.0,
                "allocation_percent": 19.3,
                "unrealized_pnl": 30.0,
            }
        ],
    }


def portfolio_bytes() -> bytes:
    return (json.dumps(portfolio_value(), indent=1) + "\n").encode()


class CabinContextTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.base = Path(self.temporary_directory.name)
        self.store = MissionStore(self.base / "artifacts")
        mission_request = request()
        self.initialized = self.store.initialize(
            mission_request,
            mission_id=mission_request.mission_id or "",
            started_at=CAPTURED_AT,
            observed_at=CAPTURED_AT,
        )

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def capture(self):
        return capture_cabin_context(
            self.store,
            mission_id=self.initialized.snapshot.mission_id,
            captured_at=CAPTURED_AT,
            market_bytes=market_bytes(),
            market_transport=CaptureTransport.LOCAL_JSON,
            market_source_identity="navigator-fixture-aapl",
            navigator_git_revision=REVISION,
            portfolio_bytes=portfolio_bytes(),
        )

    def test_validates_exact_navigator_contract_without_deriving_values(self) -> None:
        validated = NavigatorMarket.from_mapping(market_value(), expected_symbol="AAPL")

        self.assertEqual(validated.to_dict(), market_value())
        self.assertEqual(validated.to_dict()["summary"]["trend_slope_pct"], 0.5)
        for changed, message in (
            ({**market_value(), "unknown": True}, "unknown fields"),
            ({**market_value(), "timeframe": "5m"}, "timeframe"),
            ({**market_value(), "ma_period": 13}, "ma_period"),
            ({**market_value(), "symbol": "MSFT"}, "mission request"),
        ):
            with self.subTest(message=message), self.assertRaisesRegex(
                ContractValidationError, message
            ):
                NavigatorMarket.from_mapping(changed, expected_symbol="AAPL")

        unordered = market_value()
        unordered["points"][1]["t"] = 50
        with self.assertRaisesRegex(ContractValidationError, "strictly increasing"):
            NavigatorMarket.from_mapping(unordered)

    def test_portfolio_contract_is_strict_read_only_and_preserves_rows(self) -> None:
        validated = PortfolioSnapshot.from_mapping(portfolio_value())
        self.assertEqual(validated.to_dict()["positions"], portfolio_value()["positions"])

        invalid = portfolio_value()
        invalid["positions"][0]["broker_action"] = "SUBMIT_ORDER"
        with self.assertRaisesRegex(ContractValidationError, "unknown fields"):
            PortfolioSnapshot.from_mapping(invalid)

        invalid = portfolio_value()
        invalid["cash"] = -1
        with self.assertRaisesRegex(ContractValidationError, "nonnegative"):
            PortfolioSnapshot.from_mapping(invalid)

    def test_portfolio_capture_mode_must_match_mission_transport(self) -> None:
        replay_request = MissionRequest.from_mapping(
            {
                **request().to_dict(),
                "mission_id": "mission-cabin-context-replay-001",
                "request_id": "request-cabin-context-replay-001",
                "run_mode": "REPLAY",
            }
        )
        replay = self.store.initialize(
            replay_request,
            mission_id=replay_request.mission_id or "",
            started_at=CAPTURED_AT,
            observed_at=CAPTURED_AT,
        )

        with self.assertRaisesRegex(ContractValidationError, "portfolio mode"):
            capture_cabin_context(
                self.store,
                mission_id=replay.snapshot.mission_id,
                captured_at=CAPTURED_AT,
                portfolio_bytes=portfolio_bytes(),
            )

        frozen = portfolio_value()
        frozen["mode"] = "FROZEN"
        result = capture_cabin_context(
            self.store,
            mission_id=replay.snapshot.mission_id,
            captured_at=CAPTURED_AT,
            portfolio_bytes=(json.dumps(frozen) + "\n").encode(),
        )
        self.assertEqual(result.context.run_mode.value, "REPLAY")
        self.assertEqual(PortfolioSnapshot.from_bytes(result.portfolio_path.read_bytes()).mode.value, "FROZEN")

    def test_capture_preserves_bytes_and_correlates_mission_references(self) -> None:
        snapshot_before = self.initialized.paths.current_snapshot.read_bytes()
        revisions_before = tuple(self.initialized.paths.snapshots_dir.iterdir())
        result = self.capture()

        self.assertTrue(result.written)
        self.assertEqual(result.context.schema_version, CABIN_CONTEXT_SCHEMA_VERSION)
        self.assertEqual(result.context.request_id, request().request_id)
        self.assertEqual(result.context.symbol, "AAPL")
        self.assertEqual(result.context.run_mode.value, "LIVE")
        self.assertEqual(
            result.context.capture_provenance.market_status, CaptureStatus.CAPTURED
        )
        self.assertEqual(result.market_path.read_bytes(), market_bytes())
        self.assertEqual(result.portfolio_path.read_bytes(), portfolio_bytes())
        self.assertEqual(result.context.market_artifact.sha256, sha256_bytes(market_bytes()))
        self.assertEqual(
            result.context.portfolio_artifact.sha256, sha256_bytes(portfolio_bytes())
        )
        self.assertEqual(result.context.market_artifact.path, NAVIGATOR_MARKET_PATH)
        self.assertEqual(result.context.portfolio_artifact.path, PORTFOLIO_SNAPSHOT_PATH)
        self.assertNotIn(str(self.base), result.context_path.read_text(encoding="utf-8"))
        parsed = CabinContext.from_mapping(
            json.loads(result.context_path.read_text(encoding="utf-8"))
        )
        self.assertEqual(parsed, result.context)
        self.assertEqual(
            self.initialized.paths.current_snapshot.read_bytes(), snapshot_before
        )
        self.assertEqual(
            tuple(self.initialized.paths.snapshots_dir.iterdir()), revisions_before
        )

    def test_no_sources_records_not_configured_honestly(self) -> None:
        result = capture_cabin_context(
            self.store,
            mission_id=self.initialized.snapshot.mission_id,
            captured_at=CAPTURED_AT,
        )

        self.assertIsNone(result.context.market_artifact)
        self.assertIsNone(result.context.portfolio_artifact)
        self.assertEqual(
            result.context.capture_provenance.market_status,
            CaptureStatus.NOT_CONFIGURED,
        )
        self.assertEqual(
            result.context.capture_provenance.portfolio_status,
            CaptureStatus.NOT_CONFIGURED,
        )

    def test_identical_repeat_is_no_op_without_rewriting_files(self) -> None:
        first = self.capture()
        paths = (first.market_path, first.portfolio_path, first.context_path)
        before = {path: (path.read_bytes(), path.stat().st_mtime_ns) for path in paths}

        second = self.capture()

        self.assertFalse(second.written)
        self.assertEqual(
            {path: (path.read_bytes(), path.stat().st_mtime_ns) for path in paths},
            before,
        )

    def test_conflicting_context_or_artifact_is_never_overwritten(self) -> None:
        first = self.capture()
        before = first.context_path.read_bytes()
        changed_market = market_value()
        changed_market["points"][0]["o"] = 189.5

        with self.assertRaises(CabinContextConflictError):
            capture_cabin_context(
                self.store,
                mission_id=self.initialized.snapshot.mission_id,
                captured_at=CAPTURED_AT,
                market_bytes=(json.dumps(changed_market) + "\n").encode(),
                market_transport=CaptureTransport.LOCAL_JSON,
                market_source_identity="navigator-fixture-aapl",
                navigator_git_revision=REVISION,
                portfolio_bytes=portfolio_bytes(),
            )

        self.assertEqual(first.context_path.read_bytes(), before)
        self.assertEqual(first.market_path.read_bytes(), market_bytes())

    def test_missing_market_provenance_and_absolute_source_identity_are_rejected(self) -> None:
        with self.assertRaisesRegex(ContractValidationError, "revision"):
            capture_cabin_context(
                self.store,
                mission_id=self.initialized.snapshot.mission_id,
                captured_at=CAPTURED_AT,
                market_bytes=market_bytes(),
                market_transport=CaptureTransport.LOCAL_JSON,
                market_source_identity="navigator-fixture-aapl",
            )
        with self.assertRaisesRegex(ContractValidationError, "filesystem path"):
            capture_cabin_context(
                self.store,
                mission_id=self.initialized.snapshot.mission_id,
                captured_at=CAPTURED_AT,
                market_bytes=market_bytes(),
                market_transport=CaptureTransport.LOCAL_JSON,
                market_source_identity="/Users/example/input.json",
                navigator_git_revision=REVISION,
            )

    def test_http_capture_uses_one_explicit_local_url_without_fallback(self) -> None:
        class FakeResponse:
            status = 200

            def __init__(self, payload: bytes) -> None:
                self.payload = payload
                self.headers = Message()
                self.headers["Content-Type"] = "application/json"

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def getcode(self) -> int:
                return self.status

            def read(self, size: int) -> bytes:
                return self.payload[:size]

        class FakeOpener:
            def __init__(self) -> None:
                self.calls = []

            def open(self, request, timeout):
                self.calls.append((request.full_url, timeout))
                return FakeResponse(market_bytes())

        opener = FakeOpener()
        url = "http://127.0.0.1:8787/api/ohlc?symbol=AAPL&timeframe=1d&ma=250"

        captured = fetch_navigator_market(
            url,
            expected_symbol="AAPL",
            timeout_seconds=3,
            opener=opener,
        )

        self.assertEqual(captured, market_bytes())
        self.assertEqual(opener.calls, [(url, 3.0)])
        with self.assertRaisesRegex(CabinContextError, "loopback"):
            fetch_navigator_market(
                "https://navigator.example/api/ohlc?symbol=AAPL&timeframe=1d&ma=250",
                expected_symbol="AAPL",
                opener=opener,
            )
        self.assertEqual(len(opener.calls), 1)


if __name__ == "__main__":
    unittest.main()
