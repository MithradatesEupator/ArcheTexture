from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import numpy as np

from archetexture.core.fields import ensure_normalized_scalar
from archetexture.core.sampling import (
    lattice_random,
    normalized_coordinates,
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
    parameters: Mapping[str, Any], width: int, height: int, seed: int, *, turbulence: bool
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
        return np.zeros((height, width), dtype=np.float32)
    return ensure_normalized_scalar(total / amplitude_sum)


def fractal_noise(_input, parameters: Mapping[str, Any], width: int, height: int, seed: int):
    return _fractal(parameters, width, height, seed, turbulence=False)


def turbulence(_input, parameters: Mapping[str, Any], width: int, height: int, seed: int):
    return _fractal(parameters, width, height, seed, turbulence=True)


def cellular(_input, parameters: Mapping[str, Any], width: int, height: int, seed: int):
    """Worley F1 or F2-F1 using a bounded 3x3 cell neighborhood."""
    frequency = np.asarray(parameters["scale"], dtype=np.float32)
    jitter = float(parameters["jitter"])
    x, y = normalized_coordinates(width, height)
    gx, gy = x * frequency, y * frequency
    base_x, base_y = np.floor(gx).astype(np.int64), np.floor(gy).astype(np.int64)
    nearest = np.full((height, width), np.inf, dtype=np.float32)
    second = np.full((height, width), np.inf, dtype=np.float32)
    combined_seed = int(seed) ^ int(parameters["seed"])
    for delta_y in (-1, 0, 1):
        cell_y = base_y + delta_y
        for delta_x in (-1, 0, 1):
            cell_x = base_x + delta_x
            feature_x = (
                cell_x + 0.5 + (lattice_random(cell_x, cell_y, combined_seed, 1) - 0.5) * jitter
            )
            feature_y = (
                cell_y + 0.5 + (lattice_random(cell_x, cell_y, combined_seed, 2) - 0.5) * jitter
            )
            distance = np.sqrt((gx - feature_x) ** 2 + (gy - feature_y) ** 2)
            is_nearer = distance < nearest
            second = np.where(is_nearer, nearest, np.minimum(second, distance))
            nearest = np.minimum(nearest, distance)
    if parameters["distance_mode"] == "edge":
        result = np.clip(1.0 - 2.0 * (second - nearest), 0.0, 1.0)
    else:
        result = np.clip(nearest / np.float32(np.sqrt(2.0)), 0.0, 1.0)
    return ensure_normalized_scalar(result)
