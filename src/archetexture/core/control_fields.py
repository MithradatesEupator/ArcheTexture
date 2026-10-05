from __future__ import annotations

import numpy as np

from archetexture.core.fields import ScalarField, ensure_normalized_scalar
from archetexture.core.parameters import ControlFieldBinding, ControlFieldMapping


class ControlFieldEvaluator:
    @staticmethod
    def map_field(mapping: ControlFieldMapping, field: ScalarField) -> ScalarField:
        values = ensure_normalized_scalar(field)
        if mapping.invert:
            values = 1.0 - values
        values = np.clip(values, 0.0, 1.0)
        if mapping.curve == "smoothstep":
            values = values * values * (3.0 - 2.0 * values)
        elif mapping.curve == "stepped" and mapping.quantize is not None:
            steps = max(1, int(round(mapping.quantize)))
            values = np.floor(values * steps) / steps
        if mapping.quantize is not None and mapping.curve != "stepped":
            steps = max(1, int(round(mapping.quantize)))
            values = np.floor(values * steps) / steps
        low, high = mapping.normalized_range()
        return (values * (high - low) + low).astype(np.float32, copy=False)

    @classmethod
    def evaluate(
        cls,
        binding: ControlFieldBinding,
        field: ScalarField,
        *,
        width: int | None = None,
        height: int | None = None,
    ) -> ScalarField:
        mapped = cls.map_field(binding.mapping, field)
        if width is not None and height is not None and mapped.shape != (height, width):
            raise ValueError("Control field dimensions do not match the requested render size")
        return mapped
