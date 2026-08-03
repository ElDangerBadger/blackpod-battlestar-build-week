"""Shared pytest fixtures.

Forces the synthetic (network-free, deterministic) provider and an isolated
temp cache dir so the whole suite runs offline and reproducibly.
"""
from __future__ import annotations

import importlib
import os

import pytest


@pytest.fixture(scope="session", autouse=True)
def _force_synthetic_provider(tmp_path_factory):
    os.environ["BPN_PROVIDER"] = "synthetic"
    os.environ["BPN_CACHE_DIR"] = str(tmp_path_factory.mktemp("bpn_cache"))
    os.environ["BPN_CACHE_TTL_SECONDS"] = "300"
    os.environ["BPN_ENVIRONMENT"] = "test"
    # Clear cached settings/provider/cache singletons so env takes effect.
    from src import config

    config.get_settings.cache_clear()
    import src.providers as providers

    providers.get_provider.cache_clear()
    import src.cache as cache_mod

    cache_mod._CACHE = None
    importlib.reload(cache_mod)
    yield


@pytest.fixture
def client():
    from fastapi.testclient import TestClient

    from src.main import app

    return TestClient(app)