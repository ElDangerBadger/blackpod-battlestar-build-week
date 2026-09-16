"""Bounded, credential-free relay of canonical Navigator's live price overlay.

This is separate from immutable mission publications. It never constructs bars,
calculates indicators, reads account credentials, or calls a broker endpoint.
"""
from __future__ import annotations

import http.client
import json
import math
import re
from datetime import datetime, timezone
from typing import Iterator
from urllib.parse import urlsplit

from .contracts.mission_request import parse_strict_json_object_bytes

SCHEMA = "navigator.live_price.v1"
MAX_EVENT_BYTES = 4096
SYMBOL = re.compile(r"^[A-Z][A-Z0-9.-]{0,7}$")
_UTC = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,9})?Z$")
_FIELDS = {"schema_version", "symbol", "provider", "feed", "status", "price",
           "trade_at", "received_at", "checked_at", "message"}


class LivePriceUnavailable(RuntimeError):
    """Sanitized boundary failure; never expose upstream response bodies."""


def _timestamp(value: object) -> datetime:
    if not isinstance(value, str) or not _UTC.fullmatch(value):
        raise ValueError("invalid live timestamp")
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def validate_live_price(payload: bytes, symbol: str, *, now: datetime | None = None) -> dict:
    if len(payload) > MAX_EVENT_BYTES:
        raise ValueError("oversized live event")
    value = parse_strict_json_object_bytes(payload)
    if set(value) != _FIELDS or value["schema_version"] != SCHEMA:
        raise ValueError("invalid live event fields")
    if not SYMBOL.fullmatch(symbol) or value["symbol"] != symbol or value["provider"] != "alpaca":
        raise ValueError("live source identity mismatch")
    if (not isinstance(value["feed"], str) or value["feed"] not in {"iex", "sip"}
            or not isinstance(value["status"], str) or value["status"] not in {"CONNECTING", "LIVE", "WAITING", "STALE", "UNAVAILABLE"}):
        raise ValueError("unsupported live state")
    if not isinstance(value["message"], str) or len(value["message"]) > 200 or any(ord(c) < 32 for c in value["message"]):
        raise ValueError("invalid live status message")
    checked = _timestamp(value["checked_at"])
    clock = now or datetime.now(timezone.utc)
    if (checked - clock).total_seconds() > 5 or (clock - checked).total_seconds() > 60:
        raise ValueError("live heartbeat outside clock window")
    quote = (value["price"], value["trade_at"], value["received_at"])
    if all(item is None for item in quote):
        if value["status"] == "LIVE":
            raise ValueError("live state has no price")
    else:
        price = value["price"]
        if isinstance(price, bool) or not isinstance(price, (int, float)) or not 0 < price <= 1e100 or not math.isfinite(price):
            raise ValueError("invalid live price")
        trade, received = _timestamp(value["trade_at"]), _timestamp(value["received_at"])
        if (trade - received).total_seconds() > 5 or (received - checked).total_seconds() > 5 or (trade - clock).total_seconds() > 5:
            raise ValueError("live timestamp ordering mismatch")
        if value["status"] == "LIVE" and (clock - trade).total_seconds() > 60:
            value = {**value, "status": "STALE", "message": "Last trade is older than 60 seconds; not a current quote."}
    return value


def encode_event(value: dict) -> bytes:
    return b"data: " + json.dumps(value, allow_nan=False, separators=(",", ":")).encode("utf-8") + b"\n\n"


def unavailable_event(symbol: str, prior: dict | None = None) -> bytes:
    return encode_event({
        "schema_version": SCHEMA, "symbol": symbol, "provider": "alpaca",
        "feed": prior["feed"] if prior else "iex", "status": "UNAVAILABLE",
        "price": prior["price"] if prior else None,
        "trade_at": prior["trade_at"] if prior else None,
        "received_at": prior["received_at"] if prior else None,
        "checked_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "message": "Canonical live price feed disconnected. Saved mission evidence is unchanged.",
    })


class NavigatorLiveBridge:
    """Only the fixed canonical price route on an explicit loopback port."""

    def __init__(self, base_url: str):
        parsed = urlsplit(base_url)
        if (parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost"}
                or parsed.username is not None or parsed.password is not None
                or parsed.path not in {"", "/"} or parsed.query or parsed.fragment
                or parsed.port is None or not 1 <= parsed.port <= 65535):
            raise ValueError("Navigator live URL must be an explicit loopback HTTP origin and port")
        # Never resolve a configurable hostname or follow HTTP redirects.
        self.port = parsed.port

    def events(self, symbol: str) -> Iterator[dict]:
        if not SYMBOL.fullmatch(symbol):
            raise LivePriceUnavailable("unsupported live symbol")
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=15)
        try:
            connection.request("GET", f"/api/live-price/{symbol}", headers={"Accept": "text/event-stream"})
            response = connection.getresponse()
            if response.status != 200 or response.getheader("Content-Type", "").split(";")[0] != "text/event-stream":
                raise LivePriceUnavailable("canonical live feed unavailable")
            previous: dict | None = None
            pending: bytes | None = None
            while True:
                line = response.readline(MAX_EVENT_BYTES + 1)
                if not line:
                    raise LivePriceUnavailable("canonical live feed closed")
                if len(line) > MAX_EVENT_BYTES:
                    raise LivePriceUnavailable("canonical live event too large")
                line = line.rstrip(b"\r\n")
                if line.startswith(b":"):
                    continue
                if line.startswith(b"data: "):
                    if pending is not None:
                        raise LivePriceUnavailable("ambiguous canonical live event")
                    pending = line[6:]
                elif not line and pending is not None:
                    event = validate_live_price(pending, symbol)
                    pending = None
                    if previous:
                        if event["feed"] != previous["feed"] or _timestamp(event["checked_at"]) < _timestamp(previous["checked_at"]):
                            raise LivePriceUnavailable("canonical live source changed")
                        if event["trade_at"] and previous["trade_at"] and _timestamp(event["trade_at"]) < _timestamp(previous["trade_at"]):
                            continue
                    previous = event
                    yield event
                elif line:
                    raise LivePriceUnavailable("unsupported canonical live event")
        except (OSError, http.client.HTTPException, ValueError, TypeError, OverflowError):
            raise LivePriceUnavailable("canonical live feed unavailable") from None
        finally:
            connection.close()
