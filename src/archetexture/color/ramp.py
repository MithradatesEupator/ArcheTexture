from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass
class ColorStop:
    position: float
    color: tuple[float, float, float, float]


@dataclass
class ColorRamp:
    stops: list[ColorStop]

    def sample(self, value: float) -> tuple[float, float, float, float]:
        if not self.stops:
            return (0.0, 0.0, 0.0, 1.0)
        if len(self.stops) == 1:
            return self.stops[0].color
        arr = np.asarray([stop.position for stop in self.stops], dtype=np.float32)
        colors = np.asarray([stop.color for stop in self.stops], dtype=np.float32)
        v = float(np.clip(value, 0.0, 1.0))
        idx = np.searchsorted(arr, v, side="right") - 1
        idx = min(max(idx, 0), len(arr) - 1)
        if idx >= len(arr) - 1:
            return tuple(float(c) for c in colors[-1])
        left = arr[idx]
        right = arr[idx + 1]
        if right <= left:
            return tuple(float(c) for c in colors[idx])
        t = (v - left) / (right - left)
        return tuple(float(c) for c in (colors[idx] * (1.0 - t) + colors[idx + 1] * t))
