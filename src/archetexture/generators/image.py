from __future__ import annotations

from typing import Any, Mapping

import numpy as np

from archetexture.core.assets import (
    AssetReference,
    RenderContext,
    extract_channel,
    fit_image,
    image_to_float_rgba,
)


def image_source(
    _field, params: Mapping[str, Any], width: int, height: int, _seed: int, context: RenderContext
):
    reference = params["asset"]
    if not isinstance(reference, AssetReference):
        raise ValueError("Image source requires an image asset reference")
    pixels = context.load_rgba8(reference)
    return image_to_float_rgba(
        fit_image(pixels, width, height, params["fit"], params["resampling"])
    )


def image_channel(
    _field, params: Mapping[str, Any], width: int, height: int, _seed: int, context: RenderContext
):
    reference = params["asset"]
    if not isinstance(reference, AssetReference):
        raise ValueError("Image Channel source requires an image asset reference")
    pixels = context.load_rgba8(reference)
    scaled = image_to_float_rgba(
        fit_image(pixels, width, height, params["fit"], params["resampling"])
    )
    return np.clip(extract_channel(scaled, params["channel"]), 0.0, 1.0).astype(
        np.float32, copy=False
    )


def extract_image_channel(field: np.ndarray, params: Mapping[str, Any], *_args) -> np.ndarray:
    return np.clip(extract_channel(field, params["channel"]), 0.0, 1.0).astype(
        np.float32, copy=False
    )
