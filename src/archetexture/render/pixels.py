from __future__ import annotations

import numpy as np

from archetexture.core.fields import RGBAField, validate_rgba_field


def rgba_float_to_uint8(field: RGBAField) -> np.ndarray:
    """Convert normalized float RGBA to contiguous, lossless 8-bit channel data."""
    rgba = validate_rgba_field(field)
    return np.ascontiguousarray(np.rint(np.clip(rgba, 0.0, 1.0) * 255.0).astype(np.uint8))
