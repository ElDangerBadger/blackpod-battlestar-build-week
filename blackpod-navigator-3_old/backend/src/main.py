"""BlackPod Navigator FastAPI app.

Production hardening (Phase 1):
  * env-driven CORS allowlist (no wildcard-with-credentials),
  * per-IP rate limiting + security headers,
  * provider/cache abstraction with stale-on-failure fallback,
  * "not investment advice" disclaimer surfaced in metadata,
  * liveness (/health) + readiness (/ready) probes,
  * optional single-container static frontend serving.
"""
from __future__ import annotations

import os
import re

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from .config import get_settings
from .data_engine import SYMBOLS, TIMEFRAMES, fetch_bars_cached, list_tickers
from .market_model import derive_summary, enrich_bars
from .providers import get_provider

settings = get_settings()

ALLOWED_MA = {20, 50, 100, 200, 250}
DISCLAIMER = (
    "BlackPod Navigator is a market-data visualization for educational and "
    "informational purposes only. It is NOT investment advice, a recommendation, "
    "or an offer to buy or sell any security. Data may be delayed, inaccurate, or "
    "incomplete. Do your own research and consult a licensed financial advisor."
)

limiter = Limiter(key_func=get_remote_address, default_limits=[settings.rate_limit_default])

app = FastAPI(title="BlackPod Navigator API", version="0.2.0")
app.state.limiter = limiter


@app.exception_handler(RateLimitExceeded)
async def _rate_limit_handler(request: Request, exc: RateLimitExceeded):
    return JSONResponse(
        status_code=429,
        content={"detail": f"rate limit exceeded: {exc.detail}"},
    )


# --- CORS -----------------------------------------------------------------
cors_kwargs = dict(
    allow_credentials=False,  # we don't use cookies; safe with explicit origins
    allow_methods=["GET", "OPTIONS"],
    allow_headers=["*"],
)
if settings.allow_e2b_preview:
    # Allow the configured origins AND any *.e2b.app preview host.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.allowed_origins_list,
        allow_origin_regex=r"https://[\w.-]+\.e2b\.app",
        **cors_kwargs,
    )
else:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.allowed_origins_list,
        **cors_kwargs,
    )


# --- Security headers ------------------------------------------------------
@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    response.headers.setdefault("X-BPN-Disclaimer", "not-investment-advice")
    return response


# --- Probes / meta ---------------------------------------------------------
@app.get("/health")
def health_check():
    """Liveness — process is up."""
    return {"status": "healthy"}


@app.get("/ready")
def readiness_check():
    """Readiness — provider configured and instrument registry loaded."""
    try:
        provider_name = get_provider().name
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=503, detail=f"provider unavailable: {e}") from e
    return {
        "status": "ready",
        "provider": provider_name,
        "environment": settings.environment,
        "symbols": len(SYMBOLS),
        "timeframes": list(TIMEFRAMES.keys()),
    }


@app.get("/api/meta")
@limiter.limit(settings.rate_limit_tickers)
def get_meta(request: Request):
    return {
        "version": app.version,
        "provider": get_provider().name,
        "disclaimer": DISCLAIMER,
        "ma_periods": sorted(ALLOWED_MA),
        "timeframes": list(TIMEFRAMES.keys()),
    }


@app.get("/api/tickers")
@limiter.limit(settings.rate_limit_tickers)
def get_tickers(request: Request):
    return list_tickers()


@app.get("/api/ohlc")
@limiter.limit(settings.rate_limit_ohlc)
def get_ohlc(
    request: Request,
    symbol: str = Query(..., min_length=1, max_length=8),
    timeframe: str = Query("1d"),
    ma: int = Query(200),
):
    symbol = symbol.upper()
    if symbol not in SYMBOLS:
        raise HTTPException(status_code=400, detail=f"unsupported symbol: {symbol}")
    if timeframe not in TIMEFRAMES:
        raise HTTPException(status_code=400, detail=f"unsupported timeframe: {timeframe}")
    if ma not in ALLOWED_MA:
        raise HTTPException(status_code=400, detail=f"unsupported ma period: {ma}")

    try:
        result = fetch_bars_cached(symbol, timeframe)
    except Exception as e:  # noqa: BLE001 — provider failed with no stale fallback
        raise HTTPException(status_code=502, detail=f"data unavailable: {e}") from e

    bars = result.bars
    if not bars:
        raise HTTPException(status_code=404, detail="no data")

    bars = enrich_bars(bars, ma_period=ma)
    summary = derive_summary(bars, ma_period=ma)
    info = SYMBOLS[symbol]

    return {
        "symbol": symbol,
        "name": info["name"],
        "category": info["category"],
        "timeframe": timeframe,
        "ma_period": ma,
        "currency": "USD",
        "disclaimer": DISCLAIMER,
        "data": {
            "stale": result.stale,
            "age_seconds": round(result.age_seconds, 1),
            "source": result.source,
            "provider": get_provider().name,
        },
        "points": [
            {
                "t": b.t,
                "o": round(b.o, 4),
                "h": round(b.h, 4),
                "l": round(b.l, 4),
                "c": round(b.c, 4),
                "v": int(b.v),
                "ma": round(b.ma, 4) if b.ma is not None else None,
                "atr": round(b.atr, 4) if b.atr is not None else None,
            }
            for b in bars
        ],
        "summary": summary,
    }


# --- Optional single-container static frontend serving ---------------------
_static_dir = settings.static_dir or os.path.join(os.path.dirname(__file__), "..", "static")
if os.path.isdir(_static_dir):
    from fastapi.staticfiles import StaticFiles

    app.mount("/", StaticFiles(directory=_static_dir, html=True), name="static")
