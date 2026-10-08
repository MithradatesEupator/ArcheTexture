from __future__ import annotations

import numpy as np


def decode_normal(
    encoded: np.ndarray, *, directx: bool = False, strength: float = 1.0
) -> np.ndarray:
    normal = np.asarray(encoded, dtype=np.float32)[..., :3] * 2.0 - 1.0
    if directx:
        normal[..., 1] *= -1.0
    normal[..., :2] *= float(np.clip(strength, 0.0, 2.0))
    normal /= np.maximum(np.linalg.norm(normal, axis=-1, keepdims=True), 1e-8)
    return normal


def cook_torrance(
    base_color: np.ndarray,
    normal: np.ndarray,
    view: np.ndarray,
    light: np.ndarray,
    roughness: np.ndarray | float,
    metallic: np.ndarray | float,
    *,
    ao: np.ndarray | float = 1.0,
    emissive: np.ndarray | float = 0.0,
    light_color: np.ndarray | float = 1.0,
    intensity: float = 1.0,
) -> np.ndarray:
    """Finite reference metallic-roughness BRDF (linear, not color managed)."""
    color = np.asarray(base_color, dtype=np.float32)
    n = _normalize(normal)
    v = _normalize(view)
    light_direction = _normalize(light)
    h = _normalize(v + light_direction)
    rough = np.clip(np.asarray(roughness, dtype=np.float32), 0.04, 1.0)
    metal = np.clip(np.asarray(metallic, dtype=np.float32), 0.0, 1.0)
    ndotl = np.clip(np.sum(n * light_direction, axis=-1, keepdims=True), 0.0, 1.0)
    ndotv = np.clip(np.sum(n * v, axis=-1, keepdims=True), 1e-4, 1.0)
    ndoth = np.clip(np.sum(n * h, axis=-1, keepdims=True), 0.0, 1.0)
    vdoth = np.clip(np.sum(v * h, axis=-1, keepdims=True), 0.0, 1.0)
    alpha = rough * rough
    alpha2 = alpha * alpha
    denom = ndoth * ndoth * (alpha2 - 1.0) + 1.0
    distribution = alpha2 / np.maximum(np.pi * denom * denom, 1e-7)
    k = (rough + 1.0) ** 2 / 8.0
    gv = ndotv / (ndotv * (1.0 - k) + k)
    gl = ndotl / (ndotl * (1.0 - k) + k)
    geometry = gv * gl
    f0 = 0.04 * (1.0 - metal) + color * metal
    fresnel = f0 + (1.0 - f0) * (1.0 - vdoth) ** 5
    specular = distribution * geometry * fresnel / np.maximum(4.0 * ndotv * ndotl, 1e-5)
    diffuse = (1.0 - fresnel) * (1.0 - metal) * color / np.pi
    radiance = np.asarray(light_color, dtype=np.float32) * float(intensity)
    result = (diffuse + specular) * radiance * ndotl
    result = result * np.asarray(ao, dtype=np.float32) + np.asarray(emissive, dtype=np.float32)
    return np.nan_to_num(np.maximum(result, 0.0), nan=0.0, posinf=65504.0, neginf=0.0).astype(
        np.float32
    )


def _normalize(value: np.ndarray) -> np.ndarray:
    vector = np.asarray(value, dtype=np.float32)
    return vector / np.maximum(np.linalg.norm(vector, axis=-1, keepdims=True), 1e-8)
