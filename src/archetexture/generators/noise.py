from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import numpy as np

from archetexture.core.fields import ensure_normalized_scalar
from archetexture.core.sampling import (
    lattice_random,
    normalized_coordinates,
    periodic_lattice_coordinates,
    sample_periodic_value_noise,
    sample_periodic_value_noise_at,
    sample_value_noise,
)


def value_noise(_input, parameters: Mapping[str, Any], width: int, height: int, seed: int):
    return sample_value_noise(
        width,
        height,
        int(seed) ^ int(parameters["seed"]),
        parameters["scale"],
        parameters["offset_x"],
        parameters["offset_y"],
    )


def _fractal(
    parameters: Mapping[str, Any],
    width: int,
    height: int,
    seed: int,
    *,
    turbulence: bool,
    context=None,
) -> np.ndarray:
    seed = int(seed) ^ int(parameters["seed"])
    scale = np.asarray(parameters["scale"], dtype=np.float32)
    offset_x = parameters["offset_x"]
    offset_y = parameters["offset_y"]
    lacunarity = float(parameters["lacunarity"])
    persistence = float(parameters["persistence"])
    octaves = int(parameters["octaves"])
    total = np.zeros((height, width), dtype=np.float32)
    amplitude = 1.0
    amplitude_sum = 0.0
    for octave in range(octaves):
        if context is not None:
            context.check_cancelled()
        values = sample_value_noise(
            width,
            height,
            seed + octave * 0x9E3779B1,
            scale * lacunarity**octave,
            offset_x * lacunarity**octave,
            offset_y * lacunarity**octave,
        )
        if turbulence:
            values = np.abs(values * 2.0 - 1.0)
        total += values * amplitude
        amplitude_sum += amplitude
        amplitude *= persistence
    if amplitude_sum <= 1e-12:
        return np.zeros_like(total)
    return ensure_normalized_scalar(total / amplitude_sum)


def fractal_noise(
    _input, parameters: Mapping[str, Any], width: int, height: int, seed: int, context=None
):
    return _fractal(parameters, width, height, seed, turbulence=False, context=context)


def turbulence(
    _input, parameters: Mapping[str, Any], width: int, height: int, seed: int, context=None
):
    return _fractal(parameters, width, height, seed, turbulence=True, context=context)


def seamless_value_noise(_input, parameters: Mapping[str, Any], width: int, height: int, seed: int):
    return sample_periodic_value_noise(
        width,
        height,
        int(seed) ^ int(parameters["seed"]),
        int(parameters["cells_x"]),
        int(parameters["cells_y"]),
        parameters["offset_x"],
        parameters["offset_y"],
    )


def _periodic_fractal(
    parameters: Mapping[str, Any],
    width: int,
    height: int,
    seed: int,
    *,
    turbulence: bool,
    context=None,
) -> np.ndarray:
    seed = int(seed) ^ int(parameters["seed"])
    cells_x = int(parameters["cells_x"])
    cells_y = int(parameters["cells_y"])
    grid_x, grid_y = periodic_lattice_coordinates(width, height, cells_x, cells_y)
    return _periodic_fractal_at(
        grid_x,
        grid_y,
        seed=seed,
        cells_x=cells_x,
        cells_y=cells_y,
        octaves=int(parameters["octaves"]),
        lacunarity=int(parameters["lacunarity"]),
        persistence=float(parameters["persistence"]),
        offset_x=float(parameters["offset_x"]),
        offset_y=float(parameters["offset_y"]),
        turbulence=turbulence,
        context=context,
    )


def _periodic_fractal_at(
    x: np.ndarray,
    y: np.ndarray,
    *,
    seed: int,
    cells_x: int,
    cells_y: int,
    octaves: int,
    lacunarity: int,
    persistence: float,
    offset_x: float,
    offset_y: float,
    turbulence: bool,
    context=None,
) -> np.ndarray:
    total = np.zeros(np.broadcast_shapes(np.shape(x), np.shape(y)), dtype=np.float32)
    amplitude = 1.0
    amplitude_sum = 0.0
    for octave in range(int(octaves)):
        if context is not None:
            context.check_cancelled()
        multiplier = lacunarity**octave
        octave_cells_x = cells_x * multiplier
        octave_cells_y = cells_y * multiplier
        values = sample_periodic_value_noise_at(
            np.asarray(x, dtype=np.float64) * multiplier + offset_x * multiplier,
            np.asarray(y, dtype=np.float64) * multiplier + offset_y * multiplier,
            seed + octave * 0x9E3779B1,
            octave_cells_x,
            octave_cells_y,
        )
        if turbulence:
            values = np.abs(values * np.float32(2.0) - np.float32(1.0))
        total += values * np.float32(amplitude)
        amplitude_sum += amplitude
        amplitude *= persistence
    if amplitude_sum <= 1e-12:
        return np.zeros_like(total)
    return ensure_normalized_scalar(total / np.float32(amplitude_sum))


def seamless_fractal_noise(
    _input, parameters: Mapping[str, Any], width: int, height: int, seed: int, context=None
):
    return _periodic_fractal(parameters, width, height, seed, turbulence=False, context=context)


def seamless_turbulence(
    _input, parameters: Mapping[str, Any], width: int, height: int, seed: int, context=None
):
    return _periodic_fractal(parameters, width, height, seed, turbulence=True, context=context)


def cellular(_input, parameters: Mapping[str, Any], width: int, height: int, seed: int):
    """Worley F1 or F2-F1 using a bounded 3x3 cell neighborhood."""
    frequency = np.asarray(parameters["scale"], dtype=np.float32)
    x, y = normalized_coordinates(width, height)
    return _cellular_from_lattice(
        x * frequency,
        y * frequency,
        seed=int(seed) ^ int(parameters["seed"]),
        jitter=float(parameters["jitter"]),
        distance_mode=parameters["distance_mode"],
    )


def seamless_cellular(_input, parameters: Mapping[str, Any], width: int, height: int, seed: int):
    """Periodic Worley field; feature hashes repeat by tile cell period."""
    cells_x = int(parameters["cells_x"])
    cells_y = int(parameters["cells_y"])
    x, y = periodic_lattice_coordinates(width, height, cells_x, cells_y)
    return _cellular_from_lattice(
        x,
        y,
        seed=int(seed) ^ int(parameters["seed"]),
        jitter=float(parameters["jitter"]),
        distance_mode=parameters["distance_mode"],
        period_x=cells_x,
        period_y=cells_y,
    )


def _cellular_from_lattice(
    gx: np.ndarray,
    gy: np.ndarray,
    *,
    seed: int,
    jitter: float,
    distance_mode: str,
    period_x: int | None = None,
    period_y: int | None = None,
) -> np.ndarray:
    base_x, base_y = np.floor(gx).astype(np.int64), np.floor(gy).astype(np.int64)
    nearest = np.full(gx.shape, np.inf, dtype=np.float32)
    second = np.full(gx.shape, np.inf, dtype=np.float32)
    for delta_y in (-1, 0, 1):
        cell_y = base_y + delta_y
        for delta_x in (-1, 0, 1):
            cell_x = base_x + delta_x
            hash_x = np.mod(cell_x, period_x) if period_x is not None else cell_x
            hash_y = np.mod(cell_y, period_y) if period_y is not None else cell_y
            feature_x = cell_x + 0.5 + (lattice_random(hash_x, hash_y, seed, 1) - 0.5) * jitter
            feature_y = cell_y + 0.5 + (lattice_random(hash_x, hash_y, seed, 2) - 0.5) * jitter
            distance = np.sqrt((gx - feature_x) ** 2 + (gy - feature_y) ** 2)
            is_nearer = distance < nearest
            second = np.where(is_nearer, nearest, np.minimum(second, distance))
            nearest = np.minimum(nearest, distance)
    if distance_mode == "edge":
        result = np.clip(1.0 - 2.0 * (second - nearest), 0.0, 1.0)
    elif distance_mode == "second":
        result = np.clip(second / np.float32(np.sqrt(2.0)), 0.0, 1.0)
    elif distance_mode == "gap":
        result = np.clip(second - nearest, 0.0, 1.0)
    else:
        result = np.clip(nearest / np.float32(np.sqrt(2.0)), 0.0, 1.0)
    return ensure_normalized_scalar(result)
