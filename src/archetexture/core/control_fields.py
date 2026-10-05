from __future__ import annotations

import numpy as np

from archetexture.core.fields import ScalarField, validate_scalar_field
from archetexture.core.parameters import ControlFieldBinding


class ControlFieldEvaluator:
    @staticmethod
    def evaluate(
        binding: ControlFieldBinding,
        field: ScalarField,
        *,
        width: int,
        height: int,
    ) -> ScalarField:
        arr = validate_scalar_field(field, name="control_field")
        mapping = binding.mapping
        output_min = float(mapping.output_min)
        output_max = float(mapping.output_max)
        if mapping.invert:
            arr = 1.0 - arr
        if mapping.curve == "linear":
            mapped = arr * (output_max - output_min) + output_min
        elif mapping.curve == "smoothstep":
            x = np.clip(arr, 0.0, 1.0)
            mapped = x * x * (3.0 - 2.0 * x)
            mapped = mapped * (output_max - output_min) + output_min
        elif mapping.curve == "stepped":
            if mapping.quantize is not None and mapping.quantize > 0:
                steps = max(1, int(mapping.quantize))
                quantized = np.floor(arr * steps) / max(steps, 1)
                arr = quantized
            mapped = arr * (output_max - output_min) + output_min
        else:
            mapped = arr * (output_max - output_min) + output_min
        if mapping.quantize is not None and mapping.quantize > 0 and mapping.curve != "stepped":
            steps = max(1, int(mapping.quantize))
            mapped = np.floor(mapped * steps) / steps
        return mapped.astype(np.float32)
