from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from PIL import Image, ImageOps


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


@dataclass
class RenderContext:
    """Runtime-only project path and bounded decoded image cache."""

    project_path: Path | str | None = None
    cache_entries: int = 8
    _cache: OrderedDict[tuple[str, int, int], np.ndarray] = field(
        default_factory=OrderedDict, init=False, repr=False
    )

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

    def load_rgba8(self, reference: AssetReference) -> np.ndarray:
        path = self.resolve(reference)
        try:
            stat = path.stat()
            key = (str(path), stat.st_size, stat.st_mtime_ns)
            cached = self._cache.get(key)
            if cached is not None:
                self._cache.move_to_end(key)
                return cached
            with Image.open(path) as image:
                rgba = np.asarray(ImageOps.exif_transpose(image).convert("RGBA"), dtype=np.uint8)
        except (OSError, ValueError) as exc:
            raise AssetResolutionError(reference, str(exc)) from exc
        rgba.setflags(write=False)
        if self.cache_entries > 0:
            self._cache[key] = rgba
            self._cache.move_to_end(key)
            while len(self._cache) > self.cache_entries:
                self._cache.popitem(last=False)
        return rgba


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
