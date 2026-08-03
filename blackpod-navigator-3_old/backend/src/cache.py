"""Bar cache with TTL, on-disk persistence, and stale-on-failure fallback.

Design goals (Phase 1):
  * Fresh hit  → serve from memory (fast path).
  * Miss/expired → call provider; on success, refresh memory + disk.
  * Provider failure → serve the last-good value (memory or disk) if it is within
    ``cache_stale_max_seconds``, flagged as stale, instead of erroring.
  * Persistence → survive process restarts (and warm a fresh instance) without a
    database. A real multi-instance deployment would swap this for Redis/Postgres
    behind the same ``CacheResult`` contract.
"""
from __future__ import annotations

import json
import os
import threading
import time
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional, Tuple

from .config import get_settings
from .market_model import Bar


@dataclass
class CacheResult:
    bars: List[Bar]
    fetched_at: float          # epoch seconds the data was retrieved upstream
    stale: bool                # True if served past TTL due to provider failure
    source: str                # "memory" | "disk" | "provider"
    age_seconds: float         # now - fetched_at


def _bars_to_json(bars: List[Bar]) -> list:
    return [[b.t, b.o, b.h, b.l, b.c, b.v] for b in bars]


def _bars_from_json(rows: list) -> List[Bar]:
    return [Bar(t=int(r[0]), o=r[1], h=r[2], l=r[3], c=r[4], v=r[5]) for r in rows]


class BarCache:
    def __init__(
        self,
        ttl_seconds: Optional[float] = None,
        stale_max_seconds: Optional[float] = None,
        cache_dir: Optional[str] = None,
    ) -> None:
        s = get_settings()
        self.ttl = s.cache_ttl_seconds if ttl_seconds is None else ttl_seconds
        self.stale_max = (
            s.cache_stale_max_seconds if stale_max_seconds is None else stale_max_seconds
        )
        self.cache_dir = s.cache_dir if cache_dir is None else cache_dir
        self._mem: Dict[Tuple[str, str], Tuple[float, List[Bar]]] = {}
        self._lock = threading.Lock()
        if self.cache_dir:
            os.makedirs(self.cache_dir, exist_ok=True)

    # --- disk helpers -----------------------------------------------------
    def _disk_path(self, key: Tuple[str, str]) -> str:
        return os.path.join(self.cache_dir, f"{key[0]}_{key[1]}.json")

    def _read_disk(self, key: Tuple[str, str]) -> Optional[Tuple[float, List[Bar]]]:
        if not self.cache_dir:
            return None
        path = self._disk_path(key)
        try:
            with open(path, "r", encoding="utf-8") as f:
                payload = json.load(f)
            return float(payload["fetched_at"]), _bars_from_json(payload["bars"])
        except (OSError, ValueError, KeyError, TypeError):
            return None

    def _write_disk(self, key: Tuple[str, str], fetched_at: float, bars: List[Bar]) -> None:
        if not self.cache_dir:
            return
        path = self._disk_path(key)
        tmp = f"{path}.tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump({"fetched_at": fetched_at, "bars": _bars_to_json(bars)}, f)
            os.replace(tmp, path)  # atomic
        except OSError:
            # Cache persistence is best-effort; never fail a request over it.
            pass

    # --- main entry point -------------------------------------------------
    def get_or_fetch(
        self,
        symbol: str,
        timeframe: str,
        fetcher: Callable[[str, str], List[Bar]],
    ) -> CacheResult:
        key = (symbol, timeframe)
        now = time.time()

        # 1. Fresh memory hit.
        with self._lock:
            mem_entry = self._mem.get(key)
        if mem_entry and now - mem_entry[0] < self.ttl:
            return CacheResult(mem_entry[1], mem_entry[0], False, "memory", now - mem_entry[0])

        # 2. Warm memory from disk if empty (e.g. just after a restart).
        disk_entry: Optional[Tuple[float, List[Bar]]] = None
        if mem_entry is None and self.cache_dir:
            disk_entry = self._read_disk(key)
            if disk_entry is not None:
                with self._lock:
                    self._mem[key] = disk_entry
                if now - disk_entry[0] < self.ttl:
                    return CacheResult(disk_entry[1], disk_entry[0], False, "disk", now - disk_entry[0])

        # Best last-good entry to fall back on, with its true origin.
        last_good = mem_entry if mem_entry is not None else disk_entry
        last_good_source = "memory" if mem_entry is not None else "disk"

        # 3. Try the provider.
        try:
            bars = fetcher(symbol, timeframe)
            if bars:
                with self._lock:
                    self._mem[key] = (now, bars)
                self._write_disk(key, now, bars)
                return CacheResult(bars, now, False, "provider", 0.0)
            # Empty result is treated like a soft failure → fall through to stale.
            raise RuntimeError("provider returned no data")
        except Exception:  # noqa: BLE001 — any provider failure triggers stale logic
            # stale_max <= 0 disables the stale fallback entirely.
            if self.stale_max > 0 and last_good is not None:
                age = now - last_good[0]
                if age <= self.stale_max:
                    return CacheResult(last_good[1], last_good[0], True, last_good_source, age)
            raise


# Module-level singleton used by the app.
_CACHE: Optional[BarCache] = None
_CACHE_LOCK = threading.Lock()


def get_cache() -> BarCache:
    global _CACHE
    if _CACHE is None:
        with _CACHE_LOCK:
            if _CACHE is None:
                _CACHE = BarCache()
    return _CACHE