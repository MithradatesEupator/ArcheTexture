from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from archetexture.core.fields import RGBAField, ScalarField, validate_scalar_field


@dataclass(frozen=True)
class ColorStop:
    position: float
    color: tuple[float, float, float, float]

    def __post_init__(self) -> None:
        object.__setattr__(self, "color", tuple(self.color))


@dataclass(frozen=True)
class ColorRamp:
    stops: tuple[ColorStop, ...] | list[ColorStop]

    def __post_init__(self) -> None:
        object.__setattr__(self, "stops", tuple(self.stops))

    def sample(self, value: float) -> tuple[float, float, float, float]:
        return tuple(
            float(channel) for channel in self.apply(np.asarray([[value]], np.float32))[0, 0]
        )

    def apply(self, field: ScalarField) -> RGBAField:
        values = np.clip(validate_scalar_field(field), 0.0, 1.0)
        stops = sorted(self.stops, key=lambda stop: stop.position)
        if not stops:
            result = np.empty((*values.shape, 4), dtype=np.float32)
            result[..., :3] = values[..., None]
            result[..., 3] = 1.0
            return result

        positions = np.asarray([stop.position for stop in stops], dtype=np.float32)
        colors = np.asarray([stop.color for stop in stops], dtype=np.float32)
        rgba = np.empty((*values.shape, 4), dtype=np.float32)
        for channel in range(4):
            rgba[..., channel] = np.interp(
                values,
                positions,
                colors[:, channel],
                left=colors[0, channel],
                right=colors[-1, channel],
            )
        return np.clip(rgba, 0.0, 1.0).astype(np.float32, copy=False)
