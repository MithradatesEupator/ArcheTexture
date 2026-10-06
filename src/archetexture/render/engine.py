from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from archetexture.core.fields import (
    RGBAField,
    ScalarField,
    validate_rgba_field,
    validate_scalar_field,
)
from archetexture.core.operations import OperationDefinitionSet
from archetexture.core.pipeline import _evaluate_pipeline, _Evaluation
from archetexture.core.recipe import ProjectRecipe
from archetexture.core.registry import REGISTRY
from archetexture.core.validation import ensure_valid_recipe


@dataclass(frozen=True)
class RenderResult:
    scalar_field: ScalarField | None
    rgba_field: RGBAField
    mask_fields: dict[str, ScalarField] | None = None


class RenderEngine:
    def __init__(self, registry: OperationDefinitionSet = REGISTRY):
        self.registry = registry

    def render(
        self,
        recipe: ProjectRecipe,
        *,
        width: int | None = None,
        height: int | None = None,
    ) -> RenderResult:
        output_width = recipe.width if width is None else width
        output_height = recipe.height if height is None else height
        ensure_valid_recipe(recipe, self.registry)
        evaluation = _Evaluation(recipe, output_width, output_height, self.registry)
        composite = np.zeros((output_height, output_width, 4), dtype=np.float32)
        scalar_result: ScalarField | None = None
        mask_fields: dict[str, ScalarField] = {}
        for layer in recipe.layers:
            if layer.mask is not None:
                mask_fields[layer.layer_id] = evaluation.resolve_binding(layer.mask)
        visible = [layer for layer in recipe.layers if layer.enabled]
        for layer in visible:
            field = _evaluate_pipeline(layer.source, layer.transforms, evaluation, recipe.seed)
            mask = mask_fields.get(layer.layer_id)
            if field.ndim == 2:
                scalar = validate_scalar_field(field)
                scalar_result = scalar
                if layer.color_ramp is None:
                    rgba = np.empty((*scalar.shape, 4), dtype=np.float32)
                    rgba[..., :3] = scalar[..., None]
                    rgba[..., 3] = 1.0
                else:
                    rgba = layer.color_ramp.apply(scalar)
            else:
                rgba = validate_rgba_field(field)
            composite = composite_rgba(composite, rgba, layer.opacity, layer.blend_mode, mask)
        return RenderResult(scalar_result, validate_rgba_field(composite), mask_fields)


def composite_rgba(
    backdrop: RGBAField,
    source: RGBAField,
    opacity: float,
    blend_mode: str = "normal",
    mask: ScalarField | None = None,
) -> RGBAField:
    """Composite straight-alpha float32 RGBA with the W3C source-over blend equation."""
    base = validate_rgba_field(backdrop)
    top = validate_rgba_field(source)
    if base.shape != top.shape:
        raise ValueError("RGBA layers must have matching dimensions")
    if not np.isfinite(opacity) or not 0.0 <= opacity <= 1.0:
        raise ValueError("Layer opacity must be between zero and one")
    if blend_mode not in {"normal", "multiply", "screen", "add"}:
        raise ValueError(f"Unsupported blend mode: {blend_mode}")
    cb = base[..., :3]
    cs = top[..., :3]
    ab = base[..., 3:4]
    alpha = top[..., 3:4] * np.float32(opacity)
    if mask is not None:
        mask_field = validate_scalar_field(mask, name="layer mask")
        if mask_field.shape != base.shape[:2]:
            raise ValueError("Layer mask dimensions must match the composite")
        alpha = alpha * np.clip(mask_field, 0.0, 1.0)[..., None]
    if blend_mode == "normal":
        blend = cs
    elif blend_mode == "multiply":
        blend = cb * cs
    elif blend_mode == "screen":
        blend = cb + cs - cb * cs
    else:
        blend = np.minimum(cb + cs, 1.0)
    out_alpha = alpha + ab * (1.0 - alpha)
    premultiplied = (1.0 - alpha) * cb * ab + (1.0 - ab) * cs * alpha + ab * alpha * blend
    rgb = np.divide(
        premultiplied,
        out_alpha,
        out=np.zeros_like(premultiplied),
        where=out_alpha > 0.0,
    )
    return np.concatenate((np.clip(rgb, 0.0, 1.0), np.clip(out_alpha, 0.0, 1.0)), axis=-1).astype(
        np.float32, copy=False
    )
