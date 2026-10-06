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
