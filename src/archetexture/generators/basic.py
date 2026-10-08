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


def output_scalar(_input, parameters: Mapping[str, Any], width: int, height: int, _seed: int, resolver):
    result = resolver(parameters["target"])
    mode = parameters["mode"]
    if result.scalar_field is not None:
        if mode != "Direct":
            raise ValueError(f"{mode} extraction requires a color or normal output")
        return result.scalar_field
    rgba = result.rgba_field
    if mode == "Direct":
        raise ValueError("Direct mode requires a scalar output")
    if mode == "Red":
        return rgba[..., 0]
    if mode == "Green":
        return rgba[..., 1]
    if mode == "Blue":
        return rgba[..., 2]
    if mode == "Alpha":
        return rgba[..., 3]
    if mode == "Luminance":
        return rgba[..., 0] * 0.2126 + rgba[..., 1] * 0.7152 + rgba[..., 2] * 0.0722
    if mode == "Average RGB":
        return np.mean(rgba[..., :3], axis=-1)
    if mode == "Minimum RGB":
        return np.min(rgba[..., :3], axis=-1)
    if mode == "Maximum RGB":
        return np.max(rgba[..., :3], axis=-1)
    raise ValueError(f"Unsupported output extraction mode: {mode}")


def output_color(_input, parameters: Mapping[str, Any], width: int, height: int, _seed: int, resolver):
    result = resolver(parameters["target"])
    if result.scalar_field is not None:
        scalar = result.scalar_field
        rgba = np.empty((height, width, 4), dtype=np.float32)
        rgba[..., :3] = scalar[..., None]
        rgba[..., 3] = 1.0
        return rgba
    return result.rgba_field
