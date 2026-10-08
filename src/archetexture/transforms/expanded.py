"""Vectorized scalar remaps and spatial filters for procedural materials."""

from __future__ import annotations

import numpy as np

from archetexture.core.fields import ensure_normalized_scalar, validate_scalar_field
from archetexture.transforms.tonal import _gaussian_blur


def _field(source):
    return validate_scalar_field(source, name="transform input")


def clamp_range(source, parameters, _width, _height, _seed):
    values = _field(source)
    low = np.asarray(parameters["input_min"], np.float32)
    high = np.asarray(parameters["input_max"], np.float32)
    span = np.maximum(high - low, 1e-8)
    result = np.clip((values - low) / span, 0.0, 1.0)
    result = np.where(high <= low, values >= low, result)
    return ensure_normalized_scalar(result)


def gamma(source, parameters, _width, _height, _seed):
    values = _field(source)
    exponent = np.maximum(np.asarray(parameters["power"], np.float32), 0.01)
    return ensure_normalized_scalar(np.power(values, exponent))


def sine_remap(source, parameters, _width, _height, _seed):
    values = _field(source)
    cycles = np.asarray(parameters["cycles"], np.float32)
    phase = np.asarray(parameters["phase"], np.float32)
    mode = parameters["mode"]
    wave = 0.5 + 0.5 * np.sin((values * cycles + phase) * (2.0 * np.pi))
    if mode == "triangle":
        frac = np.mod(values * cycles + phase, 1.0)
        wave = 1.0 - np.abs(2.0 * frac - 1.0)
    elif mode == "square":
        wave = (np.mod(values * cycles + phase, 1.0) < 0.5).astype(np.float32)
    return ensure_normalized_scalar(wave)


def fold(source, parameters, _width, _height, _seed):
    values = _field(source)
    center = np.asarray(parameters["center"], np.float32)
    amount = np.asarray(parameters["amount"], np.float32)
    return ensure_normalized_scalar(np.abs(values - center) * amount)


def terrace(source, parameters, _width, _height, _seed):
    values = _field(source)
    steps = np.maximum(np.asarray(parameters["steps"], np.float32), 2.0)
    shaped = values * (steps - 1.0)
    lower = np.floor(shaped)
    fraction = shaped - lower
    smooth = fraction * fraction * (3.0 - 2.0 * fraction)
    amount = np.asarray(parameters["smoothness"], np.float32)
    return ensure_normalized_scalar(
        (lower + fraction * (1.0 - amount) + smooth * amount) / (steps - 1.0)
    )


def smoothstep(source, parameters, _width, _height, _seed):
    values = _field(source)
    low = np.asarray(parameters["edge0"], np.float32)
    high = np.asarray(parameters["edge1"], np.float32)
    span = np.maximum(high - low, 1e-8)
    value = np.clip((values - low) / span, 0.0, 1.0)
    return ensure_normalized_scalar(value * value * (3.0 - 2.0 * value))


def directional_blur(source, parameters, _width, _height, _seed, context=None):
    values = _field(source)
    radius = int(parameters["radius"])
    angle = np.deg2rad(float(parameters["rotation"]))
    dx, dy = int(round(np.cos(angle))), int(round(np.sin(angle)))
    if dx == 0 and dy == 0:
        dx = 1
    samples = np.zeros_like(values)
    weights = np.arange(1, radius + 2, dtype=np.float32)
    weights = np.concatenate((weights, weights[-2::-1]))
    offsets = range(-radius, radius + 1)
    for offset, weight in zip(offsets, weights, strict=True):
        if context is not None:
            context.check_cancelled()
        samples += np.roll(values, shift=(dy * offset, dx * offset), axis=(0, 1)) * weight
    return ensure_normalized_scalar(samples / weights.sum())


def emboss(source, parameters, _width, _height, _seed):
    values = _field(source)
    angle = np.deg2rad(float(parameters["light_angle"]))
    dx = (np.roll(values, -1, axis=1) - np.roll(values, 1, axis=1)) * 0.5
    dy = (np.roll(values, -1, axis=0) - np.roll(values, 1, axis=0)) * 0.5
    relief = dx * np.cos(angle) + dy * np.sin(angle)
    return ensure_normalized_scalar(0.5 + relief * np.asarray(parameters["strength"], np.float32))


def high_pass(source, parameters, _width, _height, _seed, context=None):
    values = _field(source)
    blurred = _gaussian_blur(values, float(parameters["radius"]), context)
    detail = np.abs(values - blurred) * np.asarray(parameters["gain"], np.float32)
    return ensure_normalized_scalar(detail)


def _morph(values: np.ndarray, radius: int, *, dilate: bool, context=None):
    reducer = np.maximum if dilate else np.minimum
    horizontal = values.copy()
    for offset in range(1, radius + 1):
        if context is not None:
            context.check_cancelled()
        horizontal = reducer(horizontal, np.roll(values, offset, axis=1))
        horizontal = reducer(horizontal, np.roll(values, -offset, axis=1))
    result = horizontal.copy()
    for offset in range(1, radius + 1):
        if context is not None:
            context.check_cancelled()
        result = reducer(result, np.roll(horizontal, offset, axis=0))
        result = reducer(result, np.roll(horizontal, -offset, axis=0))
    return ensure_normalized_scalar(result)


def dilate(source, parameters, _width, _height, _seed, context=None):
    return _morph(_field(source), int(parameters["radius"]), dilate=True, context=context)


def erode(source, parameters, _width, _height, _seed, context=None):
    return _morph(_field(source), int(parameters["radius"]), dilate=False, context=context)


def _sample_bilinear(values: np.ndarray, u: np.ndarray, v: np.ndarray):
    height, width = values.shape
    x = np.mod(u, 1.0) * width - 0.5
    y = np.mod(v, 1.0) * height - 0.5
    x0, y0 = np.floor(x).astype(np.int64), np.floor(y).astype(np.int64)
    fx, fy = (x - x0).astype(np.float32), (y - y0).astype(np.float32)
    x0, y0 = np.mod(x0, width), np.mod(y0, height)
    x1, y1 = (x0 + 1) % width, (y0 + 1) % height
    a, b = values[y0, x0], values[y0, x1]
    c, d = values[y1, x0], values[y1, x1]
    lower, upper = a + (b - a) * fx, c + (d - c) * fx
    return lower + (upper - lower) * fy


def warp(source, parameters, width, height, _seed):
    values = _field(source)
    x = (np.arange(width, dtype=np.float32) + 0.5) / width
    y = (np.arange(height, dtype=np.float32) + 0.5) / height
    u, v = np.meshgrid(x, y)
    dx = np.asarray(parameters["offset_x"], np.float32)
    dy = np.asarray(parameters["offset_y"], np.float32)
    return ensure_normalized_scalar(_sample_bilinear(values, u + dx, v + dy))


def _spatial_sample(source, width, height, u, v):
    return ensure_normalized_scalar(_sample_bilinear(_field(source), u, v))


def swirl(source, parameters, width, height, _seed):
    x = (np.arange(width, dtype=np.float32) + 0.5) / width - 0.5
    y = (np.arange(height, dtype=np.float32) + 0.5) / height - 0.5
    u, v = np.meshgrid(x, y)
    radius = np.sqrt(u * u + v * v)
    falloff = np.clip(1.0 - radius / max(float(parameters["radius"]), 1e-4), 0.0, 1.0)
    angle = falloff * falloff * float(parameters["angle"]) * (np.pi / 180.0)
    cosine, sine = np.cos(angle), np.sin(angle)
    ru, rv = u * cosine - v * sine, u * sine + v * cosine
    return _spatial_sample(source, width, height, ru + 0.5, rv + 0.5)


def polar_coordinates(source, parameters, width, height, _seed):
    x = (np.arange(width, dtype=np.float32) + 0.5) / width - 0.5
    y = (np.arange(height, dtype=np.float32) + 0.5) / height - 0.5
    u, v = np.meshgrid(x, y)
    angle = (np.arctan2(v, u) + np.pi) / (2.0 * np.pi)
    radius = np.sqrt(u * u + v * v) * float(parameters["radial_scale"])
    return _spatial_sample(source, width, height, angle, radius)


def kaleidoscope(source, parameters, width, height, _seed):
    x = (np.arange(width, dtype=np.float32) + 0.5) / width - 0.5
    y = (np.arange(height, dtype=np.float32) + 0.5) / height - 0.5
    u, v = np.meshgrid(x, y)
    radius = np.sqrt(u * u + v * v)
    angle = np.arctan2(v, u) + np.deg2rad(float(parameters["rotation"]))
    wedge = 2.0 * np.pi / int(parameters["segments"])
    local = np.mod(angle, wedge)
    local = np.minimum(local, wedge - local)
    folded = local * int(parameters["segments"]) / (2.0 * np.pi)
    return _spatial_sample(
        source, width, height, folded, radius * float(parameters["radial_scale"])
    )


def tile_transform(source, parameters, width, height, _seed):
    x = (np.arange(width, dtype=np.float32) + 0.5) / width - 0.5
    y = (np.arange(height, dtype=np.float32) + 0.5) / height - 0.5
    u, v = np.meshgrid(x, y)
    angle = np.deg2rad(float(parameters["rotation"]))
    cosine, sine = np.cos(angle), np.sin(angle)
    scale = np.asarray(parameters["scale"], np.float32)
    ru = (u * cosine - v * sine) * scale
    rv = (u * sine + v * cosine) * scale
    return _spatial_sample(source, width, height, ru + 0.5, rv + 0.5)


def pixelate(source, parameters, width, height, _seed):
    values = _field(source)
    block = int(parameters["block_size"])
    y = (np.arange(height) // block) * block + block // 2
    x = (np.arange(width) // block) * block + block // 2
    return ensure_normalized_scalar(
        values[np.minimum(y, height - 1)[:, None], np.minimum(x, width - 1)[None, :]]
    )


def edge_detect(source, parameters, _width, _height, _seed):
    values = _field(source)
    left, right = np.roll(values, 1, axis=1), np.roll(values, -1, axis=1)
    up, down = np.roll(values, 1, axis=0), np.roll(values, -1, axis=0)
    if parameters["method"] == "laplacian":
        result = np.abs(left + right + up + down - 4.0 * values)
    else:
        gx = (right - left) * 0.5
        gy = (down - up) * 0.5
        if parameters["method"] == "prewitt":
            gx = (
                np.roll(down, 1, axis=1)
                + down
                + np.roll(down, -1, axis=1)
                - np.roll(up, 1, axis=1)
                - up
                - np.roll(up, -1, axis=1)
            ) / 6.0
            gy = (
                np.roll(right, 1, axis=0)
                + right
                + np.roll(right, -1, axis=0)
                - np.roll(left, 1, axis=0)
                - left
                - np.roll(left, -1, axis=0)
            ) / 6.0
        result = np.sqrt(gx * gx + gy * gy)
    maximum = float(np.max(result))
    return ensure_normalized_scalar(result / maximum if maximum > 1e-8 else np.zeros_like(result))
