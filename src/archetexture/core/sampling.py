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
    cell_x = np.floor(grid_x).astype(np.int64)
    cell_y = np.floor(grid_y).astype(np.int64)
    blend_x = grid_x - cell_x
    blend_y = grid_y - cell_y
    blend_x = blend_x * blend_x * (3.0 - 2.0 * blend_x)
    blend_y = blend_y * blend_y * (3.0 - 2.0 * blend_y)
    lower_left = lattice_random(cell_x, cell_y, seed)
    lower_right = lattice_random(cell_x + 1, cell_y, seed)
    upper_left = lattice_random(cell_x, cell_y + 1, seed)
    upper_right = lattice_random(cell_x + 1, cell_y + 1, seed)
    lower = lower_left + (lower_right - lower_left) * blend_x
    upper = upper_left + (upper_right - upper_left) * blend_x
    return np.asarray(lower + (upper - lower) * blend_y, dtype=np.float32)
