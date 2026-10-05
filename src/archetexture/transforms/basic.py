from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import numpy as np

from archetexture.core.fields import ensure_normalized_scalar, validate_scalar_field


def invert(source, _parameters: Mapping[str, Any], _width: int, _height: int, _seed: int):
    values = validate_scalar_field(source, name="transform input")
    return ensure_normalized_scalar(1.0 - values)


def threshold(source, parameters: Mapping[str, Any], _width: int, _height: int, _seed: int):
    values = validate_scalar_field(source, name="transform input")
    cutoff = np.asarray(parameters["threshold"], dtype=np.float32)
    return (values >= cutoff).astype(np.float32)


def quantize(source, parameters: Mapping[str, Any], _width: int, _height: int, _seed: int):
    values = validate_scalar_field(source, name="transform input")
    levels = np.rint(np.asarray(parameters["levels"], dtype=np.float32))
    levels = np.maximum(levels, 2.0)
    return ensure_normalized_scalar(np.rint(values * (levels - 1.0)) / (levels - 1.0))
