from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import numpy as np

from archetexture.core.fields import ensure_normalized_scalar, validate_scalar_field


def offset(source, parameters: Mapping[str, Any], _width: int, _height: int, _seed: int):
    values = validate_scalar_field(source, name="transform input")
    return np.roll(
        values,
        shift=(int(parameters["offset_y"]), int(parameters["offset_x"])),
        axis=(0, 1),
    ).astype(np.float32, copy=False)


def flip(source, parameters: Mapping[str, Any], _width: int, _height: int, _seed: int):
    values = validate_scalar_field(source, name="transform input")
    axis = 1 if parameters["axis"] == "horizontal" else 0
    return np.flip(values, axis=axis).copy()


def edge_detail(source, _parameters: Mapping[str, Any], _width: int, _height: int, _seed: int):
    values = validate_scalar_field(source, name="transform input")
    gradient_x = (np.roll(values, -1, axis=1) - np.roll(values, 1, axis=1)) * 0.5
    gradient_y = (np.roll(values, -1, axis=0) - np.roll(values, 1, axis=0)) * 0.5
    magnitude = np.sqrt(gradient_x * gradient_x + gradient_y * gradient_y)
    maximum = float(np.max(magnitude))
    if maximum <= 1e-8:
        return np.zeros_like(values, dtype=np.float32)
    return ensure_normalized_scalar(magnitude / maximum)


def height_to_normal(source, parameters: Mapping[str, Any], width: int, height: int, _seed: int):
    """Encode a scalar height field as tangent-space RGBA normals.

    Image rows define positive input Y. Wrap samples periodic neighbors; Clamp
    replicates the nearest edge sample before taking the same central difference.
    Derivatives are per normalized texture coordinate, independent of resolution.
    """
    values = validate_scalar_field(source, name="transform input")
    if values.shape != (height, width):
        raise ValueError("Height to Normal dimensions must match its input field")
    if parameters["edge_mode"] == "wrap":
        dx = (np.roll(values, -1, axis=1) - np.roll(values, 1, axis=1)) * np.float32(width * 0.5)
        dy = (np.roll(values, -1, axis=0) - np.roll(values, 1, axis=0)) * np.float32(height * 0.5)
    else:
        padded = np.pad(values, ((1, 1), (1, 1)), mode="edge")
        dx = (padded[1:-1, 2:] - padded[1:-1, :-2]) * np.float32(width * 0.5)
        dy = (padded[2:, 1:-1] - padded[:-2, 1:-1]) * np.float32(height * 0.5)

    strength = np.asarray(parameters["strength"], dtype=np.float32)
    nx = -strength * dx
    ny = strength * dy
    if parameters["convention"] == "directx":
        ny = -ny
    nz = np.ones_like(nx, dtype=np.float32)
    magnitude = np.sqrt(nx * nx + ny * ny + nz * nz)
    normals = np.empty((height, width, 4), dtype=np.float32)
    normals[..., 0] = nx / magnitude * 0.5 + 0.5
    normals[..., 1] = ny / magnitude * 0.5 + 0.5
    normals[..., 2] = nz / magnitude * 0.5 + 0.5
    normals[..., 3] = 1.0
    return normals
