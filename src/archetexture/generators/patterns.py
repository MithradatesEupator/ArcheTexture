from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import numpy as np

from archetexture.core.fields import ensure_normalized_scalar
from archetexture.core.sampling import normalized_coordinates


def bands(_input, parameters: Mapping[str, Any], width: int, height: int, _seed: int):
    x, y = normalized_coordinates(width, height)
    angle = np.deg2rad(np.asarray(parameters["angle"], dtype=np.float32))
    cosine, sine = np.cos(angle), np.sin(angle)
    projection = x * cosine + y * sine
    extent = 0.5 * (
        abs(cosine) * (width / min(width, height)) + abs(sine) * (height / min(width, height))
    )
    coordinate = (projection / (2.0 * extent) + 0.5) * np.asarray(
        parameters["frequency"], dtype=np.float32
    )
    coordinate += np.asarray(parameters["phase"], dtype=np.float32)
    fraction = coordinate - np.floor(coordinate)
    waveform = parameters["waveform"]
    if waveform == "triangle":
        result = 1.0 - np.abs(2.0 * fraction - 1.0)
    elif waveform == "saw":
        result = fraction
    elif waveform == "square":
        result = (fraction < 0.5).astype(np.float32)
    else:
        result = 0.5 + 0.5 * np.sin(2.0 * np.pi * coordinate)
    return ensure_normalized_scalar(result)


def checker_grid(_input, parameters: Mapping[str, Any], width: int, height: int, _seed: int):
    x = (np.arange(width, dtype=np.float32) + 0.5) / width
    y = (np.arange(height, dtype=np.float32) + 0.5) / height
    coordinate_x = x * np.asarray(parameters["cells_x"], dtype=np.float32) + parameters["offset_x"]
    coordinate_y = y * np.asarray(parameters["cells_y"], dtype=np.float32) + parameters["offset_y"]
    fraction_x = coordinate_x - np.floor(coordinate_x)
    fraction_y = coordinate_y - np.floor(coordinate_y)
    pattern = parameters["pattern"]
    if pattern == "grid":
        line_width = float(parameters["line_width"])
        lines_x = (fraction_x < line_width) | (fraction_x > 1.0 - line_width)
        lines_y = (fraction_y < line_width) | (fraction_y > 1.0 - line_width)
        result = np.broadcast_to(lines_x[None, :] | lines_y[:, None], (height, width))
    else:
        cell_x = np.floor(coordinate_x).astype(np.int64)
        cell_y = np.floor(coordinate_y).astype(np.int64)
        result = ((cell_x[None, :] + cell_y[:, None]) % 2).astype(bool)
    return ensure_normalized_scalar(np.asarray(result, dtype=np.float32))
