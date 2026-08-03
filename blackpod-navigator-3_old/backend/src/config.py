"""Centralized, environment-driven configuration for BlackPod Navigator.

All operational knobs (provider selection, CORS origins, cache TTL/dir, rate
limits) are read from the environment so the same image runs in dev, staging,
and production with no code changes.
"""
from __future__ import annotations

from functools import lru_cache
from typing import List

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="BPN_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- Market data provider ---------------------------------------------
    # Which provider implementation to use: "yfinance" (default) or "synthetic"
    # (deterministic, network-free — used for tests, offline dev, and demos).
    provider: str = "yfinance"

    # --- Cache / stale fallback -------------------------------------------
    cache_ttl_seconds: float = 60.0
    # Max age (seconds) a stale entry may be served when the upstream provider
    # fails. 0 disables stale fallback. Default: 7 days.
    cache_stale_max_seconds: float = 7 * 24 * 3600.0
    # Directory for the on-disk cache (survives restarts). Empty = memory-only.
    cache_dir: str = ".cache"

    # --- CORS / abuse controls --------------------------------------------
    # Comma-separated list of allowed origins. "*" is rejected in production
    # (see is_production). Defaults cover local dev + the e2b preview hosts.
    allowed_origins: str = (
        "http://localhost:3000,http://127.0.0.1:3000,"
        "http://localhost:5173,http://127.0.0.1:5173"
    )
    # Allow any *.e2b.app preview origin (regex). Disable in real production.
    allow_e2b_preview: bool = True

    # Per-IP rate limits (slowapi syntax, e.g. "60/minute").
    rate_limit_ohlc: str = "60/minute"
    rate_limit_tickers: str = "120/minute"
    rate_limit_default: str = "240/minute"

    # --- Deployment -------------------------------------------------------
    environment: str = "development"  # development | staging | production
    # Directory of built frontend assets to serve (single-container deploy).
    static_dir: str = ""

    @property
    def is_production(self) -> bool:
        return self.environment.lower() == "production"

    @property
    def allowed_origins_list(self) -> List[str]:
        return [o.strip() for o in self.allowed_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()