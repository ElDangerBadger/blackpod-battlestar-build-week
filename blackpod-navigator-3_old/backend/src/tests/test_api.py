"""API contract tests (synthetic provider, offline)."""
from __future__ import annotations


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "healthy"


def test_ready_reports_provider(client):
    r = client.get("/ready")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ready"
    assert body["provider"] == "synthetic"
    assert body["symbols"] == 10


def test_meta_has_disclaimer(client):
    r = client.get("/api/meta")
    assert r.status_code == 200
    body = r.json()
    assert "disclaimer" in body and "not investment advice" in body["disclaimer"].lower()
    assert set(body["ma_periods"]) == {20, 50, 100, 200, 250}


def test_tickers(client):
    r = client.get("/api/tickers")
    assert r.status_code == 200
    items = r.json()
    assert len(items) == 10
    assert all(set(i.keys()) == {"symbol", "name", "category"} for i in items)


def test_ohlc_contract(client):
    r = client.get("/api/ohlc?symbol=SPY&timeframe=1d&ma=200")
    assert r.status_code == 200
    body = r.json()
    # top-level contract
    for k in ("symbol", "timeframe", "ma_period", "disclaimer", "data", "points", "summary"):
        assert k in body
    assert body["symbol"] == "SPY"
    assert body["data"]["stale"] is False
    assert body["data"]["provider"] == "synthetic"
    # point shape
    p = body["points"][0]
    assert set(p.keys()) == {"t", "o", "h", "l", "c", "v", "ma", "atr"}
    # summary shape
    for k in ("last_price", "pct_vs_ma", "position", "volatility", "trend_slope_pct"):
        assert k in body["summary"]


def test_ohlc_security_headers(client):
    r = client.get("/api/ohlc?symbol=SPY&timeframe=1d&ma=200")
    assert r.headers.get("x-content-type-options") == "nosniff"
    assert r.headers.get("x-frame-options") == "DENY"


def test_ohlc_rejects_bad_symbol(client):
    r = client.get("/api/ohlc?symbol=NOPE&timeframe=1d&ma=200")
    assert r.status_code == 400


def test_ohlc_rejects_bad_timeframe(client):
    r = client.get("/api/ohlc?symbol=SPY&timeframe=13m&ma=200")
    assert r.status_code == 400


def test_ohlc_rejects_bad_ma(client):
    r = client.get("/api/ohlc?symbol=SPY&timeframe=1d&ma=33")
    assert r.status_code == 400


def test_ohlc_symbol_is_case_insensitive(client):
    r = client.get("/api/ohlc?symbol=spy&timeframe=1d&ma=50")
    assert r.status_code == 200
    assert r.json()["symbol"] == "SPY"


def test_cors_preflight_allows_known_origin(client):
    r = client.options(
        "/api/tickers",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert r.status_code in (200, 204)
    assert r.headers.get("access-control-allow-origin") == "http://localhost:3000"