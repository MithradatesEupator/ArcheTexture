from __future__ import annotations

from typing import Final

import numpy as np

ScalarField = np.ndarray
RGBAField = np.ndarray

SCALAR_DTYPE: Final[np.dtype] = np.float32
RGBA_DTYPE: Final[np.dtype] = np.float32


def validate_scalar_field(field: ScalarField, *, name: str = "field") -> ScalarField:
    arr = np.asarray(field, dtype=np.float32)
    if arr.ndim != 2:
        raise ValueError(f"{name} must be 2D scalar field, got shape {arr.shape!r}")
    if not np.isfinite(arr).all():
        raise ValueError(f"{name} contains non-finite values")
    return arr


def validate_rgba_field(field: RGBAField, *, name: str = "field") -> RGBAField:
    arr = np.asarray(field, dtype=np.float32)
    if arr.ndim != 3 or arr.shape[2] != 4:
        raise ValueError(f"{name} must be RGBA shape (H, W, 4), got {arr.shape!r}")
    if not np.isfinite(arr).all():
        raise ValueError(f"{name} contains non-finite values")
    return arr


def ensure_normalized_scalar(field: ScalarField, *, name: str = "field") -> ScalarField:
    arr = validate_scalar_field(field, name=name)
    arr = np.clip(arr, 0.0, 1.0)
    return arr.astype(np.float32, copy=False)


def as_scalar_field(field: ScalarField | np.ndarray, *, name: str = "field") -> ScalarField:
    return validate_scalar_field(field, name=name).astype(np.float32, copy=False)


def make_scalar_field(height: int, width: int, value: float = 0.0) -> ScalarField:
    return np.full((height, width), value, dtype=np.float32)


def make_rgba_field(
    height: int,
    width: int,
    color: tuple[float, float, float, float] | None = None,
) -> RGBAField:
    if color is None:
        color = (0.0, 0.0, 0.0, 1.0)
    arr = np.empty((height, width, 4), dtype=np.float32)
    arr[:] = np.asarray(color, dtype=np.float32)
    return arr
