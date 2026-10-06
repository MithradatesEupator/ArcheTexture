from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass, field
from pathlib import Path
from threading import RLock

import numpy as np
from PIL import Image, ImageOps

from archetexture.core.cancellation import CancellationToken


@dataclass(frozen=True)
class AssetReference:
    path: str
    mode: str = "absolute"
    kind: str = "image"


class AssetResolutionError(ValueError):
    def __init__(self, reference: AssetReference, message: str):
        self.reference = reference
        self.path = reference.path
        super().__init__(f"Cannot resolve image asset '{reference.path}': {message}")


class AssetCache:
    """Thread-safe bounded LRU for oriented decoded images."""

    def __init__(self, max_bytes: int = 128 * 1024 * 1024, max_entries: int | None = None):
        self.max_bytes = max(0, int(max_bytes))
        self.max_entries = max_entries
        self._cache: OrderedDict[tuple[str, int, int, int], np.ndarray] = OrderedDict()
        self._bytes = 0
        self._hits = 0
        self._misses = 0
        self._decodes = 0
        self._lock = RLock()

    @property
    def stats(self) -> dict[str, int]:
        with self._lock:
            return {
                "hits": self._hits,
                "misses": self._misses,
                "decodes": self._decodes,
                "entries": len(self._cache),
                "bytes": self._bytes,
                "max_bytes": self.max_bytes,
            }

    def clear(self) -> None:
        with self._lock:
            self._cache.clear()
            self._bytes = 0

    def load_rgba8(self, path: Path, reference: AssetReference) -> np.ndarray:
        try:
            stat = path.stat()
            key = (str(path), stat.st_size, stat.st_mtime_ns, getattr(stat, "st_ino", 0))
            with self._lock:
                cached = self._cache.get(key)
                if cached is not None:
                    self._hits += 1
                    self._cache.move_to_end(key)
                    return cached
                self._misses += 1
                for stale_key in [entry for entry in self._cache if entry[0] == str(path)]:
                    self._bytes -= self._cache.pop(stale_key).nbytes
            with Image.open(path) as image:
                rgba = np.asarray(ImageOps.exif_transpose(image).convert("RGBA"), dtype=np.uint8)
        except (OSError, ValueError) as exc:
            raise AssetResolutionError(reference, str(exc)) from exc
        rgba.setflags(write=False)
        with self._lock:
            self._decodes += 1
            if self.max_bytes and rgba.nbytes <= self.max_bytes:
                self._cache[key] = rgba
                self._bytes += rgba.nbytes
                while self._cache and (
                    self._bytes > self.max_bytes
                    or (self.max_entries is not None and len(self._cache) > self.max_entries)
                ):
                    _, evicted = self._cache.popitem(last=False)
                    self._bytes -= evicted.nbytes
        return rgba


@dataclass(frozen=True)
class RenderContext:
    """Immutable per-request path and runtime handles; never serialized."""

    project_path: Path | str | None = None
    asset_cache: AssetCache = field(default_factory=AssetCache, compare=False)
    cancel_token: CancellationToken | None = field(default=None, compare=False)
    # Compatibility/testing limit; production session caches are byte-bounded.
    cache_entries: int | None = field(default=None, compare=False)

    def __post_init__(self) -> None:
        if self.cache_entries is not None and self.asset_cache.max_entries != self.cache_entries:
            object.__setattr__(
                self,
                "asset_cache",
                AssetCache(max_entries=self.cache_entries),
            )

    def with_runtime(self, asset_cache: AssetCache, token: CancellationToken) -> RenderContext:
        return RenderContext(self.project_path, asset_cache, token)

    def resolve(self, reference: AssetReference) -> Path:
        if not isinstance(reference, AssetReference) or reference.kind != "image":
            raise AssetResolutionError(reference, "invalid image reference")
        raw = Path(reference.path).expanduser()
        if reference.mode == "absolute":
            path = raw
        elif reference.mode == "project_relative":
            if raw.is_absolute() or self.project_path is None:
                raise AssetResolutionError(reference, "project path is unavailable")
            path = Path(self.project_path).resolve().parent / raw
        else:
            raise AssetResolutionError(reference, "unsupported path mode")
        return path.resolve()

    def exists(self, reference: AssetReference) -> bool:
        try:
            return self.resolve(reference).is_file()
        except (AssetResolutionError, OSError):
            return False

    def asset_signature(self, reference: AssetReference) -> tuple:
        try:
            path = self.resolve(reference)
            stat = path.stat()
            return (str(path), True, stat.st_size, stat.st_mtime_ns, getattr(stat, "st_ino", 0))
        except (AssetResolutionError, OSError):
            try:
                path = self.resolve(reference)
                return (str(path), False)
            except AssetResolutionError:
                return (reference.mode, reference.path, False)

    def check_cancelled(self) -> None:
        if self.cancel_token is not None:
            self.cancel_token.check()

    def load_rgba8(self, reference: AssetReference) -> np.ndarray:
        self.check_cancelled()
        path = self.resolve(reference)
        return self.asset_cache.load_rgba8(path, reference)


def image_to_float_rgba(rgba: np.ndarray) -> np.ndarray:
    return rgba.astype(np.float32) / np.float32(255.0)


def fit_image(rgba: np.ndarray, width: int, height: int, fit: str, resampling: str) -> np.ndarray:
    modes = {
        "Nearest": Image.Resampling.NEAREST,
        "Bilinear": Image.Resampling.BILINEAR,
        "Bicubic": Image.Resampling.BICUBIC,
        "Lanczos": Image.Resampling.LANCZOS,
    }
    source = Image.fromarray(rgba, "RGBA")
    sw, sh = source.size
    if fit == "Tile":
        result = np.tile(rgba, (int(np.ceil(height / sh)), int(np.ceil(width / sw)), 1))[
            :height, :width
        ]
        return np.ascontiguousarray(result)
    if fit == "Stretch":
        source = source.resize((width, height), modes[resampling])
    elif fit in {"Contain", "Cover"}:
        scale = min(width / sw, height / sh) if fit == "Contain" else max(width / sw, height / sh)
        size = (max(1, round(sw * scale)), max(1, round(sh * scale)))
        resized = source.resize(size, modes[resampling])
        if fit == "Contain":
            canvas = Image.new("RGBA", (width, height), (0, 0, 0, 0))
            canvas.alpha_composite(resized, ((width - size[0]) // 2, (height - size[1]) // 2))
            source = canvas
        else:
            left, top = (size[0] - width) // 2, (size[1] - height) // 2
            source = resized.crop((left, top, left + width, top + height))
    else:
        raise ValueError(f"Unsupported image fit mode: {fit}")
    return np.asarray(source, dtype=np.uint8).copy()


def extract_channel(rgba: np.ndarray, channel: str) -> np.ndarray:
    if channel == "Red":
        field = rgba[..., 0]
    elif channel == "Green":
        field = rgba[..., 1]
    elif channel == "Blue":
        field = rgba[..., 2]
    elif channel == "Alpha":
        field = rgba[..., 3]
    elif channel == "Luminance":
        field = rgba[..., 0] * 0.2126 + rgba[..., 1] * 0.7152 + rgba[..., 2] * 0.0722
    else:
        raise ValueError(f"Unsupported image channel: {channel}")
    return np.asarray(field, dtype=np.float32)
