from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import numpy as np

from archetexture.core.fields import ensure_normalized_scalar, validate_scalar_field


def levels(source, parameters: Mapping[str, Any], _width: int, _height: int, _seed: int):
    values = validate_scalar_field(source, name="transform input")
    black = np.asarray(parameters["input_black"], dtype=np.float32)
    white = np.asarray(parameters["input_white"], dtype=np.float32)
    span = white - black
    degenerate = np.abs(span) <= 1e-6
    safe_span = np.where(degenerate, 1.0, span)
    adjusted = np.clip((values - black) / safe_span, 0.0, 1.0)
    adjusted = np.where(degenerate, values >= black, adjusted).astype(np.float32)
    gamma = np.maximum(np.asarray(parameters["gamma"], dtype=np.float32), 0.01)
    adjusted = np.power(adjusted, 1.0 / gamma)
    output_black = np.asarray(parameters["output_black"], dtype=np.float32)
    output_white = np.asarray(parameters["output_white"], dtype=np.float32)
    return ensure_normalized_scalar(output_black + adjusted * (output_white - output_black))


def brightness_contrast(
    source, parameters: Mapping[str, Any], _width: int, _height: int, _seed: int
):
    values = validate_scalar_field(source, name="transform input")
    brightness = np.asarray(parameters["brightness"], dtype=np.float32)
    contrast = np.asarray(parameters["contrast"], dtype=np.float32)
    return ensure_normalized_scalar((values - 0.5) * contrast + 0.5 + brightness)


def normalize(source, _parameters: Mapping[str, Any], _width: int, _height: int, _seed: int):
    values = validate_scalar_field(source, name="transform input")
    minimum, maximum = float(np.min(values)), float(np.max(values))
    span = maximum - minimum
    if span <= 1e-8:
        return np.zeros_like(values, dtype=np.float32)
    return ensure_normalized_scalar((values - minimum) / span)


def _gaussian_blur(values: np.ndarray, sigma: float, context=None) -> np.ndarray:
    if sigma <= 1e-4:
        return values.copy()
    radius = max(1, int(np.ceil(3.0 * sigma)))
    positions = np.arange(-radius, radius + 1, dtype=np.float32)
    weights = np.exp(-(positions * positions) / (2.0 * sigma * sigma)).astype(np.float32)
    weights /= np.sum(weights)
    horizontal = np.zeros_like(values, dtype=np.float32)
    for offset, weight in zip(range(-radius, radius + 1), weights, strict=True):
        if context is not None:
            context.check_cancelled()
        horizontal += np.roll(values, offset, axis=1) * weight
    vertical = np.zeros_like(values, dtype=np.float32)
    for offset, weight in zip(range(-radius, radius + 1), weights, strict=True):
        if context is not None:
            context.check_cancelled()
        vertical += np.roll(horizontal, offset, axis=0) * weight
    return ensure_normalized_scalar(vertical)


def blur(source, parameters: Mapping[str, Any], _width: int, _height: int, _seed: int):
    values = validate_scalar_field(source, name="transform input")
    return _gaussian_blur(values, float(parameters["sigma"]))


def sharpen(source, parameters: Mapping[str, Any], _width: int, _height: int, _seed: int):
    values = validate_scalar_field(source, name="transform input")
    blurred = _gaussian_blur(values, float(parameters["sigma"]))
    amount = float(parameters["amount"])
    return ensure_normalized_scalar(values + amount * (values - blurred))
