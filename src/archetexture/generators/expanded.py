"""Vectorized procedural sources added for the material starter library."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import numpy as np

from archetexture.core.fields import ensure_normalized_scalar
from archetexture.core.sampling import lattice_random, normalized_coordinates


def _grid(width: int, height: int, scale: float | np.ndarray, angle: float = 0.0):
    x, y = normalized_coordinates(width, height)
    radians = np.deg2rad(np.asarray(angle, dtype=np.float32))
    cosine, sine = np.cos(radians), np.sin(radians)
    return (x * cosine - y * sine) * scale, (x * sine + y * cosine) * scale


def _value_at(x: np.ndarray, y: np.ndarray, seed: int) -> np.ndarray:
    ix, iy = np.floor(x).astype(np.int64), np.floor(y).astype(np.int64)
    fx, fy = x - ix, y - iy
    fx = fx * fx * (3.0 - 2.0 * fx)
    fy = fy * fy * (3.0 - 2.0 * fy)
    a = lattice_random(ix, iy, seed)
    b = lattice_random(ix + 1, iy, seed)
    c = lattice_random(ix, iy + 1, seed)
    d = lattice_random(ix + 1, iy + 1, seed)
    return np.asarray(
        (a + (b - a) * fx) + ((c + (d - c) * fx) - (a + (b - a) * fx)) * fy, np.float32
    )


def _octaves(
    parameters: Mapping[str, Any], width: int, height: int, seed: int, mode: str, context=None
):
    scale = np.asarray(parameters["scale"], dtype=np.float32)
    offset_x = np.asarray(parameters["offset_x"], dtype=np.float32)
    offset_y = np.asarray(parameters["offset_y"], dtype=np.float32)
    angle = float(parameters["rotation"])
    total = np.zeros((height, width), np.float32)
    weight_sum = 0.0
    amplitude = 1.0
    frequency = 1.0
    for octave in range(int(parameters["octaves"])):
        if context is not None:
            context.check_cancelled()
        x, y = _grid(width, height, scale * frequency, angle)
        value = _value_at(
            x + offset_x * frequency, y + offset_y * frequency, seed + octave * 0x9E3779B1
        )
        if mode == "ridge":
            value = 1.0 - np.abs(2.0 * value - 1.0)
        elif mode == "billow":
            value = np.abs(2.0 * value - 1.0)
        total += value * np.float32(amplitude)
        weight_sum += amplitude
        amplitude *= float(parameters["persistence"])
        frequency *= float(parameters["lacunarity"])
    return ensure_normalized_scalar(total / max(weight_sum, 1e-12))


def ridged_noise(_input, parameters, width, height, seed, context=None):
    return _octaves(parameters, width, height, seed ^ int(parameters["seed"]), "ridge", context)


def billow_noise(_input, parameters, width, height, seed, context=None):
    return _octaves(parameters, width, height, seed ^ int(parameters["seed"]), "billow", context)


def perlin_noise(_input, parameters, width, height, seed, context=None):
    x, y = _grid(width, height, np.asarray(parameters["scale"], np.float32), parameters["rotation"])
    x += np.asarray(parameters["offset_x"], np.float32)
    y += np.asarray(parameters["offset_y"], np.float32)
    ix, iy = np.floor(x).astype(np.int64), np.floor(y).astype(np.int64)
    fx, fy = x - ix, y - iy
    fade_x = fx**3 * (fx * (fx * 6.0 - 15.0) + 10.0)
    fade_y = fy**3 * (fy * (fy * 6.0 - 15.0) + 10.0)
    dots = []
    for dx, dy in ((0, 0), (1, 0), (0, 1), (1, 1)):
        gx, gy = ix + dx, iy + dy
        theta = lattice_random(gx, gy, seed ^ int(parameters["seed"]), 41) * (2.0 * np.pi)
        dots.append(np.cos(theta) * (fx - dx) + np.sin(theta) * (fy - dy))
    lower = dots[0] + fade_x * (dots[1] - dots[0])
    upper = dots[2] + fade_x * (dots[3] - dots[2])
    value = np.clip(0.5 + (lower + fade_y * (upper - lower)) * 0.8, 0.0, 1.0)
    return ensure_normalized_scalar(value)


def domain_warp(_input, parameters, width, height, seed, context=None):
    if context is not None:
        context.check_cancelled()
    scale = np.asarray(parameters["scale"], np.float32)
    x, y = _grid(width, height, scale, parameters["rotation"])
    seed ^= int(parameters["seed"])
    warp_scale = float(parameters["warp_scale"])
    wx = _value_at(x * warp_scale + 17.0, y * warp_scale - 9.0, seed) - 0.5
    wy = _value_at(x * warp_scale - 23.0, y * warp_scale + 31.0, seed + 1) - 0.5
    amount = float(parameters["warp_amount"])
    frequency = np.asarray(parameters["frequency"], np.float32)
    return ensure_normalized_scalar(
        _value_at(x * frequency + wx * amount, y * frequency + wy * amount, seed + 2)
    )


def brick(_input, parameters, width, height, seed):
    rows, columns = int(parameters["rows"]), int(parameters["columns"])
    x, y = normalized_coordinates(width, height)
    gy = y * rows + float(parameters["offset_y"])
    row = np.floor(gy).astype(np.int64)
    gx = x * columns + (row % 2) * 0.5 + float(parameters["offset_x"])
    cell_x = np.floor(gx).astype(np.int64)
    fx, fy = gx - cell_x, gy - row
    jitter = float(parameters["jitter"])
    jx = (lattice_random(cell_x, row, seed, 1) - 0.5) * jitter
    jy = (lattice_random(cell_x, row, seed, 2) - 0.5) * jitter
    mortar = np.asarray(parameters["mortar"], np.float32)
    inside = (
        (fx > mortar + jx)
        & (fx < 1.0 - mortar + jx)
        & (fy > mortar + jy)
        & (fy < 1.0 - mortar + jy)
    )
    variation = lattice_random(cell_x, row, seed, 3) * float(parameters["variation"])
    return ensure_normalized_scalar(np.where(inside, 0.72 + variation, 0.08))


def hex_cells(_input, parameters, width, height, seed):
    x, y = normalized_coordinates(width, height)
    density = np.asarray(parameters["density"], np.float32)
    gy = y * density * 0.8660254
    row = np.floor(gy + 0.5).astype(np.int64)
    gx = x * density + (row & 1) * 0.5
    cell_x, cell_y = np.floor(gx + 0.5).astype(np.int64), row
    dx = gx - cell_x
    dy = gy - cell_y
    dist = np.abs(dx) * 0.8660254 + np.abs(dy) * 0.5
    edge = float(parameters["edge_width"])
    shade = np.where(dist > 0.5 - edge, 0.1, 0.55 + 0.4 * lattice_random(cell_x, cell_y, seed))
    return ensure_normalized_scalar(shade)


def truchet(_input, parameters, width, height, seed):
    x, y = normalized_coordinates(width, height)
    density = np.asarray(parameters["density"], np.float32)
    gx, gy = (x + 0.5) * density, (y + 0.5) * density
    ix, iy = np.floor(gx).astype(np.int64), np.floor(gy).astype(np.int64)
    fx, fy = gx - ix, gy - iy
    flip = lattice_random(ix, iy, seed ^ int(parameters["seed"]), 5) > 0.5
    radius_a = np.sqrt(fx * fx + fy * fy)
    radius_b = np.sqrt((1.0 - fx) ** 2 + (1.0 - fy) ** 2)
    radius = np.where(flip, radius_a, radius_b)
    stroke = float(parameters["line_width"])
    return ensure_normalized_scalar((np.abs(radius - 0.5) < stroke).astype(np.float32))


def wood_rings(_input, parameters, width, height, seed, context=None):
    if context is not None:
        context.check_cancelled()
    x, y = normalized_coordinates(width, height)
    x += float(parameters["center_x"])
    y += float(parameters["center_y"])
    grain = (
        _value_at(
            x * float(parameters["distortion"]),
            y * float(parameters["distortion"]),
            seed ^ int(parameters["seed"]),
        )
        - 0.5
    )
    rings = np.sqrt(x * x + y * y) * np.asarray(parameters["rings"], np.float32) + grain * float(
        parameters["warp"]
    )
    phase = np.mod(rings, 1.0)
    return ensure_normalized_scalar(np.clip(0.5 + 0.5 * np.cos(phase * (2.0 * np.pi)), 0.0, 1.0))


def marble_veins(_input, parameters, width, height, seed, context=None):
    x, y = _grid(
        width, height, np.asarray(parameters["scale"], np.float32), float(parameters["rotation"])
    )
    seed ^= int(parameters["seed"])
    turbulence = np.zeros((height, width), np.float32)
    amplitude, frequency, total = 1.0, 1.0, 0.0
    for octave in range(int(parameters["octaves"])):
        if context is not None:
            context.check_cancelled()
        turbulence += (
            np.abs(_value_at(x * frequency, y * frequency, seed + octave * 97) * 2.0 - 1.0)
            * amplitude
        )
        total += amplitude
        amplitude *= 0.5
        frequency *= 2.0
    veins = np.sin(
        (
            x * float(parameters["vein_frequency"])
            + turbulence / total * float(parameters["distortion"])
        )
        * np.pi
    )
    return ensure_normalized_scalar(np.clip(0.5 + 0.5 * veins, 0.0, 1.0))


def dots(_input, parameters, width, height, seed):
    x, y = normalized_coordinates(width, height)
    cols, rows = int(parameters["columns"]), int(parameters["rows"])
    gx, gy = x * cols + 0.5, y * rows + 0.5
    ix, iy = np.floor(gx).astype(np.int64), np.floor(gy).astype(np.int64)
    fx, fy = gx - ix - 0.5, gy - iy - 0.5
    if parameters["stagger"]:
        fx += (iy % 2) * 0.25 - 0.125
    jitter = float(parameters["jitter"])
    fx -= (lattice_random(ix, iy, seed, 1) - 0.5) * jitter
    fy -= (lattice_random(ix, iy, seed, 2) - 0.5) * jitter
    radius = np.sqrt(fx * fx + fy * fy)
    return ensure_normalized_scalar(
        (radius < np.asarray(parameters["radius"], np.float32)).astype(np.float32)
    )


def concentric_rings(_input, parameters, width, height, _seed):
    x, y = normalized_coordinates(width, height)
    radius = np.sqrt(
        (x - float(parameters["center_x"])) ** 2 + (y - float(parameters["center_y"])) ** 2
    )
    phase = np.mod(radius * np.asarray(parameters["frequency"], np.float32), 1.0)
    width_value = float(parameters["line_width"])
    result = (
        np.where(phase < width_value, 1.0, 0.0)
        if parameters["mode"] == "lines"
        else 0.5 + 0.5 * np.cos(2.0 * np.pi * phase)
    )
    return ensure_normalized_scalar(result)


def radial_spokes(_input, parameters, width, height, _seed):
    x, y = normalized_coordinates(width, height)
    angle = np.arctan2(y, x) + float(parameters["rotation"]) * np.pi / 180.0
    wave = np.cos(angle * int(parameters["spokes"]))
    value = np.clip(0.5 + 0.5 * wave, 0.0, 1.0)
    if float(parameters["center_fade"]) > 0:
        radius = np.sqrt(x * x + y * y)
        value = 0.5 + (value - 0.5) * np.clip(radius / float(parameters["center_fade"]), 0.0, 1.0)
    return ensure_normalized_scalar(value)


def weave(_input, parameters, width, height, seed):
    x, y = normalized_coordinates(width, height)
    gx = x * np.asarray(parameters["threads_x"], np.float32)
    gy = y * np.asarray(parameters["threads_y"], np.float32)
    fx, fy = gx - np.floor(gx), gy - np.floor(gy)
    width_value = float(parameters["thread_width"])
    vertical = np.abs(fx - 0.5) < width_value
    horizontal = np.abs(fy - 0.5) < width_value
    row, col = np.floor(gy).astype(np.int64), np.floor(gx).astype(np.int64)
    vertical_over = ((row + int(parameters["seed"])) % 2) == 0
    value = np.where(
        vertical & horizontal,
        np.where(vertical_over, 0.82, 0.58),
        np.where(vertical | horizontal, 0.68, 0.16),
    )
    value += (lattice_random(col, row, seed, 8) - 0.5) * float(parameters["variation"])
    return ensure_normalized_scalar(value)


def crosshatch(_input, parameters, width, height, _seed):
    x, y = normalized_coordinates(width, height)
    scale = np.asarray(parameters["frequency"], np.float32)
    angle = np.deg2rad(float(parameters["rotation"]))
    a = x * np.cos(angle) - y * np.sin(angle)
    b = x * np.cos(angle + np.pi / 2) - y * np.sin(angle + np.pi / 2)
    phase_a = np.abs(np.mod(a * scale, 1.0) - 0.5)
    phase_b = np.abs(np.mod(b * scale, 1.0) - 0.5)
    width_value = float(parameters["line_width"])
    result = ((phase_a < width_value) | (phase_b < width_value)).astype(np.float32)
    if parameters["single_direction"]:
        result = (phase_a < width_value).astype(np.float32)
    return ensure_normalized_scalar(result)
