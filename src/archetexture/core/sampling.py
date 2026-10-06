"""Small deterministic coordinate and lattice-sampling helpers for generators."""

from __future__ import annotations

import numpy as np


def normalized_coordinates(width: int, height: int) -> tuple[np.ndarray, np.ndarray]:
    """Return centered float32 coordinates with aspect-correct, unit-short-side scale."""
    if width <= 0 or height <= 0:
        raise ValueError("Sampling dimensions must be positive")
    unit = float(min(width, height))
    x = (np.arange(width, dtype=np.float32) + 0.5 - width / 2.0) / unit
    y = (np.arange(height, dtype=np.float32) + 0.5 - height / 2.0) / unit
    return np.meshgrid(x, y)


def _hash_u64(x: np.ndarray, y: np.ndarray, seed: int, salt: int = 0) -> np.ndarray:
    """Coordinate-addressed SplitMix64 hash; results do not depend on traversal order."""
    x_values = np.asarray(x, dtype=np.int64).astype(np.uint64, copy=False)
    y_values = np.asarray(y, dtype=np.int64).astype(np.uint64, copy=False)
    value = (
        x_values * np.uint64(0x9E3779B185EBCA87)
        ^ y_values * np.uint64(0xC2B2AE3D27D4EB4F)
        ^ np.uint64(seed & 0xFFFFFFFFFFFFFFFF)
        ^ np.uint64(salt & 0xFFFFFFFFFFFFFFFF)
    )
    value = (value ^ (value >> np.uint64(30))) * np.uint64(0xBF58476D1CE4E5B9)
    value = (value ^ (value >> np.uint64(27))) * np.uint64(0x94D049BB133111EB)
    return value ^ (value >> np.uint64(31))


def lattice_random(x: np.ndarray, y: np.ndarray, seed: int, salt: int = 0) -> np.ndarray:
    """Map integer lattice coordinates to deterministic normalized float32 values."""
    hashed = _hash_u64(x, y, seed, salt)
    mantissa = (hashed >> np.uint64(40)).astype(np.uint32)
    return mantissa.astype(np.float32) * np.float32(1.0 / 16777216.0)


def sample_value_noise(
    width: int,
    height: int,
    seed: int,
    frequency: float | np.ndarray,
    offset_x: float | np.ndarray = 0.0,
    offset_y: float | np.ndarray = 0.0,
) -> np.ndarray:
    """Sample smoothly interpolated 2D value noise on an aspect-correct lattice."""
    x, y = normalized_coordinates(width, height)
    grid_x = x * np.asarray(frequency, dtype=np.float32) + np.asarray(offset_x, dtype=np.float32)
    grid_y = y * np.asarray(frequency, dtype=np.float32) + np.asarray(offset_y, dtype=np.float32)
    return _interpolate_lattice_values(grid_x, grid_y, seed)


def periodic_lattice_coordinates(
    width: int,
    height: int,
    cells_x: int,
    cells_y: int,
    offset_x: float = 0.0,
    offset_y: float = 0.0,
) -> tuple[np.ndarray, np.ndarray]:
    """Return pixel-center coordinates in a rectangular periodic lattice domain."""
    if width <= 0 or height <= 0:
        raise ValueError("Sampling dimensions must be positive")
    if (
        not isinstance(cells_x, int)
        or isinstance(cells_x, bool)
        or not isinstance(cells_y, int)
        or isinstance(cells_y, bool)
        or cells_x <= 0
        or cells_y <= 0
    ):
        raise ValueError("Periodic cell counts must be positive")
    x = (np.arange(width, dtype=np.float32) + np.float32(0.5)) / np.float32(width)
    y = (np.arange(height, dtype=np.float32) + np.float32(0.5)) / np.float32(height)
    grid_x = x[None, :] * np.float32(cells_x) + np.asarray(offset_x, dtype=np.float32)
    grid_y = y[:, None] * np.float32(cells_y) + np.asarray(offset_y, dtype=np.float32)
    return np.broadcast_arrays(grid_x, grid_y)


def sample_periodic_value_noise_at(
    x: np.ndarray,
    y: np.ndarray,
    seed: int,
    period_x: int,
    period_y: int,
) -> np.ndarray:
    """Sample smooth value noise whose lattice repeats at integer X/Y periods."""
    if (
        not isinstance(period_x, int)
        or isinstance(period_x, bool)
        or not isinstance(period_y, int)
        or isinstance(period_y, bool)
        or period_x <= 0
        or period_y <= 0
    ):
        raise ValueError("Periodic lattice periods must be positive")
    return _interpolate_lattice_values(x, y, seed, period_x, period_y)


def sample_periodic_value_noise(
    width: int,
    height: int,
    seed: int,
    cells_x: int,
    cells_y: int,
    offset_x: float = 0.0,
    offset_y: float = 0.0,
) -> np.ndarray:
    """Sample one tile, keeping its conceptual cell counts independent of resolution."""
    grid_x, grid_y = periodic_lattice_coordinates(
        width, height, cells_x, cells_y, offset_x, offset_y
    )
    return sample_periodic_value_noise_at(grid_x, grid_y, seed, cells_x, cells_y)


def _interpolate_lattice_values(
    grid_x: np.ndarray,
    grid_y: np.ndarray,
    seed: int,
    period_x: int | None = None,
    period_y: int | None = None,
) -> np.ndarray:
    coordinate_dtype = np.float64 if period_x is not None else np.float32
    grid_x = np.asarray(grid_x, dtype=coordinate_dtype)
    grid_y = np.asarray(grid_y, dtype=coordinate_dtype)
    cell_x = np.floor(grid_x).astype(np.int64)
    cell_y = np.floor(grid_y).astype(np.int64)
    blend_x = grid_x - cell_x
    blend_y = grid_y - cell_y
    blend_x = blend_x * blend_x * (3.0 - 2.0 * blend_x)
    blend_y = blend_y * blend_y * (3.0 - 2.0 * blend_y)
    if period_x is not None and period_y is not None:
        x0, x1 = np.mod(cell_x, period_x), np.mod(cell_x + 1, period_x)
        y0, y1 = np.mod(cell_y, period_y), np.mod(cell_y + 1, period_y)
    else:
        x0, x1, y0, y1 = cell_x, cell_x + 1, cell_y, cell_y + 1
    lower_left = lattice_random(x0, y0, seed)
    lower_right = lattice_random(x1, y0, seed)
    upper_left = lattice_random(x0, y1, seed)
    upper_right = lattice_random(x1, y1, seed)
    lower = lower_left + (lower_right - lower_left) * blend_x
    upper = upper_left + (upper_right - upper_left) * blend_x
    return np.asarray(lower + (upper - lower) * blend_y, dtype=np.float32)
