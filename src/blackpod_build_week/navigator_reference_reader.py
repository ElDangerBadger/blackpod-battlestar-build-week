"""Read-only transport of canonical, versioned Navigator market references.

No provider, calendar calculation, indicator calculation, or mission execution
is imported here. Battlestar owns those decisions; this boundary verifies its
bounded artifact bytes and expires its explicit freshness deadline.
"""
from __future__ import annotations

from collections import OrderedDict
from datetime import datetime, timedelta, timezone
from pathlib import Path
import re
import threading

from .cabin_context import NavigatorMarket, ALLOWED_MA_PERIODS, ALLOWED_TIMEFRAMES
from .contracts.mission_request import RunMode, parse_rfc3339, parse_strict_json_object_bytes
from .hashing import sha256_bytes
from .navigator_live import SYMBOL
from .sentry_reader import _read_regular

FEED_SCHEMA = "blackpod.navigator_reference_feed.v1"
INDEX_SCHEMA = "navigator.reference_index.v1"
SNAPSHOT_SCHEMA = "navigator.reference_snapshot.v1"
MAX_INDEX_BYTES = 256 * 1024
MAX_SNAPSHOT_BYTES = 2 * 1024 * 1024
MAX_ENTRIES = 32 * 15
HASH = re.compile(r"^[a-f0-9]{64}$")


def _require(condition: bool) -> None:
    if not condition:
        raise ValueError("Invalid canonical Navigator reference")


def _object(value, fields):
    _require(isinstance(value, dict) and set(value) == set(fields.split()))
    return value


def _stamp(value):
    _require(isinstance(value, str) and value.endswith("Z"))
    return parse_rfc3339(value, "reference timestamp")


def _integer(value):
    _require(type(value) is int and value >= 0)
    return value


def _identity(value):
    symbol, timeframe, period = value["symbol"], value["timeframe"], value["ma_period"]
    _require(isinstance(symbol, str) and bool(SYMBOL.fullmatch(symbol)))
    _require(isinstance(timeframe, str) and timeframe in ALLOWED_TIMEFRAMES)
    _require(type(period) is int and period in ALLOWED_MA_PERIODS)
    return symbol, timeframe, period


def validate_reference_snapshot(value: dict, identity: tuple, *, now: datetime, generated: datetime) -> dict:
    _object(value, "schema_version captured_at provider_fetched_at symbol timeframe ma_period bar_policy "
            "latest_bar_at expected_bar_at valid_until calendar_id provider adjustment market")
    _require(value["schema_version"] == SNAPSHOT_SCHEMA and _identity(value) == identity)
    _require(value["bar_policy"] == "completed_regular_session")
    _require(value["provider"] == "yfinance" and value["adjustment"] == "auto_adjust=True")
    _require(isinstance(value["calendar_id"], str) and bool(re.fullmatch(r"sentry-session-calendar-[a-f0-9]{64}", value["calendar_id"])))
    captured, fetched, deadline = map(_stamp, (value["captured_at"], value["provider_fetched_at"], value["valid_until"]))
    _require(fetched <= captured + timedelta(seconds=5) and captured <= generated <= now + timedelta(seconds=5))
    _require(captured < deadline <= captured + timedelta(days=10))
    latest, expected = map(_integer, (value["latest_bar_at"], value["expected_bar_at"]))
    _require(latest == expected and latest <= fetched.timestamp() <= captured.timestamp() + 5)
    market = NavigatorMarket.from_mapping(value["market"], expected_symbol=identity[0], run_mode=RunMode.LIVE).value
    _require((market["symbol"], market["timeframe"], market["ma_period"]) == identity)
    _require(len(market["points"]) <= 20_000 and market["points"][-1]["t"] == latest)
    _require(market["summary"]["last_ma"] is not None)
    provenance = market.get("data", {})
    _require(provenance.get("provider") == value["provider"] and provenance.get("stale") is False)
    for point in market["points"]:
        _require(point["l"] <= min(point["o"], point["c"]) <= max(point["o"], point["c"]) <= point["h"])
    return value


class NavigatorReferenceReader:
    """Configured artifact root only; failures retain bounded last-verified data."""

    def __init__(self, root: Path | None = None):
        self.root = Path(root).absolute() if root is not None else None
        self._last: OrderedDict[tuple, dict] = OrderedDict()
        self._lock = threading.Lock()

    def current(self, symbol: str, timeframe: str, ma_period: int, *, now: datetime | None = None) -> dict:
        clock = now or datetime.now(timezone.utc)
        identity = _identity(dict(symbol=symbol, timeframe=timeframe, ma_period=ma_period))
        base = {"schema_version": FEED_SCHEMA, "checked_at": clock.isoformat().replace("+00:00", "Z")}
        if self.root is None:
            return {**base, "status": "NOT_CONFIGURED", "snapshot": None,
                    "message": "Current references are not configured. Saved mission captures are unchanged."}
        with self._lock:
            try:
                raw_index = _read_regular(self.root / "current.json", MAX_INDEX_BYTES)
                index = parse_strict_json_object_bytes(raw_index)
                _object(index, "schema_version generated_at entries")
                _require(index["schema_version"] == INDEX_SCHEMA)
                generated = _stamp(index["generated_at"])
                _require(generated <= clock + timedelta(seconds=5))
                entries = index["entries"]
                _require(isinstance(entries, list) and 0 < len(entries) <= MAX_ENTRIES)
                identities, selected = set(), None
                for entry in entries:
                    _object(entry, "symbol timeframe ma_period status reason last_attempt_at snapshot")
                    key = _identity(entry)
                    _require(key not in identities)
                    identities.add(key)
                    _require(isinstance(entry["status"], str) and entry["status"] in {"READY", "STALE", "UNAVAILABLE"})
                    _require(isinstance(entry["reason"], str) and bool(re.fullmatch(r"[A-Z0-9_]{1,100}", entry["reason"])))
                    _require(_stamp(entry["last_attempt_at"]) <= generated)
                    if key == identity:
                        selected = entry
                _require(selected is not None and selected["snapshot"] is not None)
                descriptor = _object(selected["snapshot"], "path sha256 byte_size")
                digest = descriptor["sha256"]
                _require(isinstance(digest, str) and bool(HASH.fullmatch(digest)))
                _require(descriptor["path"] == f"snapshots/{digest}.json")
                _require(0 < _integer(descriptor["byte_size"]) <= MAX_SNAPSHOT_BYTES)
                raw = _read_regular(self.root / descriptor["path"], MAX_SNAPSHOT_BYTES)
                _require(len(raw) == descriptor["byte_size"] and sha256_bytes(raw) == digest)
                snapshot = validate_reference_snapshot(parse_strict_json_object_bytes(raw), identity,
                                                       now=clock, generated=generated)
                _require(_read_regular(self.root / "current.json", MAX_INDEX_BYTES) == raw_index)
                previous = self._last.get(identity)
                _require(previous is None or _stamp(snapshot["captured_at"]) >= _stamp(previous["captured_at"]))
                snapshot = {**snapshot, "snapshot_id": digest}
                self._last[identity] = snapshot
                self._last.move_to_end(identity)
                while len(self._last) > 16:
                    self._last.popitem(last=False)
                ready = selected["status"] == "READY" and clock < _stamp(snapshot["valid_until"])
                return {**base, "status": "READY" if ready else "STALE", "snapshot": snapshot,
                        "message": "Verified latest completed-bar reference; not a live quote." if ready else
                        "Reference update is due or failed. Showing the last verified snapshot, not current market state."}
            except (OSError, ValueError, RuntimeError, TypeError, KeyError, OverflowError):
                previous = self._last.get(identity)
                return {**base, "status": "STALE" if previous else "UNAVAILABLE", "snapshot": previous,
                        "message": "Current reference unavailable or failed verification. Retained data is not current; mission evidence is unchanged."}
