"""Tests for the bar cache: TTL, disk persistence, and stale-on-failure."""
from __future__ import annotations

from typing import List

from src.cache import BarCache
from src.market_model import Bar


def _bars(seed: float, n: int = 5) -> List[Bar]:
    return [Bar(t=1_700_000_000 + i * 86400, o=seed, h=seed + 1, l=seed - 1, c=seed + i, v=100) for i in range(n)]


class _Fetcher:
    """Configurable fake provider fetcher."""

    def __init__(self, bars: List[Bar]):
        self.bars = bars
        self.calls = 0
        self.fail = False
        self.empty = False

    def __call__(self, symbol: str, timeframe: str) -> List[Bar]:
        self.calls += 1
        if self.fail:
            raise RuntimeError("upstream down")
        if self.empty:
            return []
        return self.bars


def test_fresh_fetch_then_memory_hit(tmp_path):
    cache = BarCache(ttl_seconds=100, stale_max_seconds=0, cache_dir=str(tmp_path))
    f = _Fetcher(_bars(10))
    r1 = cache.get_or_fetch("SPY", "1d", f)
    assert r1.source == "provider" and not r1.stale and f.calls == 1
    r2 = cache.get_or_fetch("SPY", "1d", f)
    assert r2.source == "memory" and not r2.stale and f.calls == 1  # no second call


def test_ttl_expiry_triggers_refetch(tmp_path):
    cache = BarCache(ttl_seconds=0, stale_max_seconds=0, cache_dir=str(tmp_path))
    f = _Fetcher(_bars(10))
    cache.get_or_fetch("SPY", "1d", f)
    cache.get_or_fetch("SPY", "1d", f)
    assert f.calls == 2  # ttl=0 means always considered expired


def test_stale_served_on_failure(tmp_path):
    cache = BarCache(ttl_seconds=0, stale_max_seconds=10_000, cache_dir=str(tmp_path))
    f = _Fetcher(_bars(42))
    good = cache.get_or_fetch("SPY", "1d", f)
    assert not good.stale
    # Now upstream fails; cache should serve the last-good bars flagged stale.
    f.fail = True
    stale = cache.get_or_fetch("SPY", "1d", f)
    assert stale.stale is True
    assert [b.c for b in stale.bars] == [b.c for b in good.bars]


def test_empty_result_falls_back_to_stale(tmp_path):
    cache = BarCache(ttl_seconds=0, stale_max_seconds=10_000, cache_dir=str(tmp_path))
    f = _Fetcher(_bars(7))
    cache.get_or_fetch("SPY", "1d", f)
    f.empty = True  # provider returns [] → treated as soft failure
    r = cache.get_or_fetch("SPY", "1d", f)
    assert r.stale is True and len(r.bars) == 5


def test_failure_without_prior_data_raises(tmp_path):
    cache = BarCache(ttl_seconds=0, stale_max_seconds=10_000, cache_dir=str(tmp_path))
    f = _Fetcher(_bars(1))
    f.fail = True
    try:
        cache.get_or_fetch("SPY", "1d", f)
        assert False, "expected exception with no stale fallback available"
    except RuntimeError:
        pass


def test_stale_disabled_when_max_zero(tmp_path):
    # stale_max=0 disables stale fallback even if cached data exists.
    cache = BarCache(ttl_seconds=0, stale_max_seconds=0, cache_dir=str(tmp_path))
    f = _Fetcher(_bars(3))
    cache.get_or_fetch("SPY", "1d", f)
    f.fail = True
    try:
        cache.get_or_fetch("SPY", "1d", f)
        assert False, "expected failure when stale disabled"
    except RuntimeError:
        pass


def test_disk_persistence_across_instances(tmp_path):
    # First cache writes to disk; a fresh instance should warm from disk and,
    # if the provider then fails, serve the disk copy as stale.
    f = _Fetcher(_bars(99))
    c1 = BarCache(ttl_seconds=100, stale_max_seconds=10_000, cache_dir=str(tmp_path))
    c1.get_or_fetch("SPY", "1d", f)

    c2 = BarCache(ttl_seconds=0, stale_max_seconds=10_000, cache_dir=str(tmp_path))
    f2 = _Fetcher(_bars(0))
    f2.fail = True
    r = c2.get_or_fetch("SPY", "1d", f2)
    assert r.stale is True
    assert r.source == "disk"
    assert [b.c for b in r.bars] == [b.c for b in f.bars]