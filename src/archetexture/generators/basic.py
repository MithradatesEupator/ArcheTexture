from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import numpy as np

from archetexture.core.fields import ensure_normalized_scalar


def constant(_input, parameters: Mapping[str, Any], width: int, height: int, _seed: int):
    return ensure_normalized_scalar(np.broadcast_to(parameters["value"], (height, width)))


def white_noise(_input, parameters: Mapping[str, Any], width: int, height: int, seed: int):
    sequence = np.random.SeedSequence([int(seed), int(parameters["seed"])])
    return np.random.default_rng(sequence).random((height, width), dtype=np.float32)


def linear_gradient(_input, parameters: Mapping[str, Any], width: int, height: int, _seed: int):
    angle = np.deg2rad(np.asarray(parameters["angle"], dtype=np.float32))
    y, x = np.mgrid[0:height, 0:width].astype(np.float32)
    nx = x / max(width - 1, 1) - 0.5
    ny = 0.5 - y / max(height - 1, 1)
    cosine = np.cos(angle)
    sine = np.sin(angle)
    projection = nx * cosine + ny * sine
    extent = 0.5 * (np.abs(cosine) + np.abs(sine))
    normalized = (
        np.divide(
            projection,
            2.0 * extent,
            out=np.zeros_like(projection, dtype=np.float32),
            where=extent > 1e-8,
        )
        + 0.5
    )
    return ensure_normalized_scalar(normalized)


def radial_gradient(_input, parameters: Mapping[str, Any], width: int, height: int, _seed: int):
    radius = np.asarray(parameters["radius"], dtype=np.float32)
    y, x = np.mgrid[0:height, 0:width].astype(np.float32)
    nx = x / max(width - 1, 1) - 0.5
    ny = y / max(height - 1, 1) - 0.5
    distance = np.sqrt(nx * nx + ny * ny)
    normalized = 1.0 - np.clip(distance / np.maximum(radius, 1e-6), 0.0, 1.0)
    return ensure_normalized_scalar(normalized)
