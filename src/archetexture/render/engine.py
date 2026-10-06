from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from archetexture.core.assets import RenderContext
from archetexture.core.cancellation import RenderCancelled
from archetexture.core.dependencies import (
    control_dependency_definitions,
    layer_content_dependencies,
)
from archetexture.core.fields import (
    RGBAField,
    ScalarField,
    validate_rgba_field,
    validate_scalar_field,
)
from archetexture.core.fingerprinting import structural_fingerprint
from archetexture.core.operations import OperationDefinitionSet
from archetexture.core.pipeline import _evaluate_pipeline, _Evaluation
from archetexture.core.recipe import ProjectRecipe
from archetexture.core.registry import REGISTRY
from archetexture.core.validation import ensure_valid_recipe
from archetexture.render.session import RenderSession


@dataclass(frozen=True)
class RenderResult:
    scalar_field: ScalarField | None
    rgba_field: RGBAField
    mask_fields: dict[str, ScalarField] | None = None


class RenderEngine:
    def __init__(
        self,
        registry: OperationDefinitionSet = REGISTRY,
        *,
        session: RenderSession | None = None,
    ):
        self.registry = registry
        self.session = session or RenderSession()

    def render_uncached(self, recipe: ProjectRecipe, **kwargs) -> RenderResult:
        """Correctness reference path that bypasses layer and Control Field caches."""
        return self.render(recipe, use_cache=False, **kwargs)

    def render(
        self,
        recipe: ProjectRecipe,
        *,
        width: int | None = None,
        height: int | None = None,
        render_context: RenderContext | None = None,
        use_cache: bool = True,
    ) -> RenderResult:
        output_width = recipe.width if width is None else width
        output_height = recipe.height if height is None else height
        ensure_valid_recipe(recipe, self.registry)
        context = render_context or RenderContext(asset_cache=self.session.asset_cache)
        evaluation = _Evaluation(
            recipe,
            output_width,
            output_height,
            self.registry,
            render_context=context,
            session=self.session,
            cache_enabled=use_cache,
        )
        composite = np.zeros((output_height, output_width, 4), dtype=np.float32)
        scalar_result: ScalarField | None = None
        mask_fields: dict[str, ScalarField] = {}
        try:
            for layer in recipe.layers:
                context.check_cancelled()
                if layer.mask is not None:
                    mask_fields[layer.layer_id] = evaluation.resolve_binding(layer.mask)
            visible = [layer for layer in recipe.layers if layer.enabled]
            for layer in visible:
                context.check_cancelled()
                cache_key = None
                cached = None
                if use_cache:
                    dependencies = control_dependency_definitions(
                        recipe, layer_content_dependencies(layer)
                    )
                    context.check_cancelled()
                    cache_key = structural_fingerprint(
                        {
                            "width": output_width,
                            "height": output_height,
                            "seed": recipe.seed,
                            "source": layer.source,
                            "transforms": layer.transforms,
                            "color_ramp": layer.color_ramp,
                            "control_dependencies": dependencies,
                        },
                        context,
                    )
                    context.check_cancelled()
                    cached = self.session.layer_cache.get(cache_key)
                if cached is not None:
                    rgba, scalar = cached
                else:
                    field = _evaluate_pipeline(
                        layer.source, layer.transforms, evaluation, recipe.seed
                    )
                    scalar = None
                    if field.ndim == 2:
                        scalar = validate_scalar_field(field)
                        if layer.color_ramp is None:
                            rgba = np.empty((*scalar.shape, 4), dtype=np.float32)
                            rgba[..., :3] = scalar[..., None]
                            rgba[..., 3] = 1.0
                        else:
                            rgba = layer.color_ramp.apply(scalar)
                    else:
                        rgba = validate_rgba_field(field)
                    if cache_key is not None:
                        self.session.layer_cache.put(cache_key, rgba, scalar)
                if scalar is not None:
                    scalar_result = scalar
                context.check_cancelled()
                composite = composite_rgba(
                    composite,
                    rgba,
                    layer.opacity,
                    layer.blend_mode,
                    mask_fields.get(layer.layer_id),
                )
                context.check_cancelled()
        except RenderCancelled:
            self.session.cancellation_observed()
            raise
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
