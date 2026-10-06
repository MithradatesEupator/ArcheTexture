from __future__ import annotations

from collections import OrderedDict
from threading import RLock

import numpy as np

from archetexture.core.assets import AssetCache


class LayerResultCache:
    """Memory-bounded LRU of immutable pre-composite layer outputs."""

    def __init__(self, max_bytes: int = 256 * 1024 * 1024):
        self.max_bytes = max(0, int(max_bytes))
        self._entries: OrderedDict[str, tuple[np.ndarray, np.ndarray | None]] = OrderedDict()
        self._bytes = 0
        self._hits = 0
        self._misses = 0
        self._lock = RLock()

    @property
    def stats(self) -> dict[str, int]:
        with self._lock:
            return {
                "hits": self._hits,
                "misses": self._misses,
                "entries": len(self._entries),
                "bytes": self._bytes,
                "max_bytes": self.max_bytes,
            }

    def get(self, key: str) -> tuple[np.ndarray, np.ndarray | None] | None:
        with self._lock:
            result = self._entries.get(key)
            if result is None:
                self._misses += 1
                return None
            self._entries.move_to_end(key)
            self._hits += 1
            return result

    def put(self, key: str, rgba: np.ndarray, scalar: np.ndarray | None) -> None:
        rgba_view = np.asarray(rgba, dtype=np.float32).copy()
        rgba_view.setflags(write=False)
        scalar_view = None
        if scalar is not None:
            scalar_view = np.asarray(scalar, dtype=np.float32).copy()
            scalar_view.setflags(write=False)
        size = rgba_view.nbytes + (scalar_view.nbytes if scalar_view is not None else 0)
        if size > self.max_bytes or not self.max_bytes:
            return
        with self._lock:
            old = self._entries.pop(key, None)
            if old is not None:
                self._bytes -= old[0].nbytes + (old[1].nbytes if old[1] is not None else 0)
            self._entries[key] = (rgba_view, scalar_view)
            self._bytes += size
            while self._bytes > self.max_bytes:
                _, (old_rgba, old_scalar) = self._entries.popitem(last=False)
                self._bytes -= old_rgba.nbytes + (
                    old_scalar.nbytes if old_scalar is not None else 0
                )

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()
            self._bytes = 0


class ScalarFieldCache:
    """Small bounded cache for completed Control Field scalar arrays."""

    def __init__(self, max_bytes: int = 32 * 1024 * 1024):
        self.max_bytes = max(0, int(max_bytes))
        self._entries: OrderedDict[str, np.ndarray] = OrderedDict()
        self._bytes = 0
        self._hits = 0
        self._misses = 0
        self._lock = RLock()

    @property
    def stats(self) -> dict[str, int]:
        with self._lock:
            return {
                "hits": self._hits,
                "misses": self._misses,
                "entries": len(self._entries),
                "bytes": self._bytes,
                "max_bytes": self.max_bytes,
            }

    def get(self, key: str) -> np.ndarray | None:
        with self._lock:
            result = self._entries.get(key)
            if result is None:
                self._misses += 1
                return None
            self._entries.move_to_end(key)
            self._hits += 1
            return result

    def put(self, key: str, value: np.ndarray) -> None:
        array = np.asarray(value, dtype=np.float32).copy()
        array.setflags(write=False)
        if array.nbytes > self.max_bytes or not self.max_bytes:
            return
        with self._lock:
            old = self._entries.pop(key, None)
            if old is not None:
                self._bytes -= old.nbytes
            self._entries[key] = array
            self._bytes += array.nbytes
            while self._bytes > self.max_bytes:
                _, evicted = self._entries.popitem(last=False)
                self._bytes -= evicted.nbytes

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()
            self._bytes = 0


class RenderSession:
    """Explicit owner of runtime caches shared across viewport requests."""

    def __init__(
        self,
        *,
        layer_cache_bytes: int = 224 * 1024 * 1024,
        asset_cache_bytes: int = 128 * 1024 * 1024,
        control_cache_bytes: int = 32 * 1024 * 1024,
    ):
        self.layer_cache = LayerResultCache(layer_cache_bytes)
        self.asset_cache = AssetCache(asset_cache_bytes)
        self.control_cache = ScalarFieldCache(control_cache_bytes)
        self._operations = 0
        self._cancellations = 0
        self._lock = RLock()

    @property
    def stats(self) -> dict[str, dict[str, int] | int]:
        with self._lock:
            return {
                "layers": self.layer_cache.stats,
                "assets": self.asset_cache.stats,
                "controls": self.control_cache.stats,
                "operation_executions": self._operations,
                "cancellations": self._cancellations,
            }

    def operation_executed(self) -> None:
        with self._lock:
            self._operations += 1

    def cancellation_observed(self) -> None:
        with self._lock:
            self._cancellations += 1

    def clear(self) -> None:
        self.layer_cache.clear()
        self.asset_cache.clear()
        self.control_cache.clear()
        with self._lock:
            self._operations = 0
            self._cancellations = 0
