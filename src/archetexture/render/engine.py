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
from archetexture.core.recipe import MaterialOutputRecipe, ProjectRecipe
from archetexture.core.registry import REGISTRY
from archetexture.core.validation import ensure_valid_recipe
from archetexture.render.session import RenderSession


@dataclass(frozen=True)
class RenderResult:
    scalar_field: ScalarField | None
    rgba_field: RGBAField
    mask_fields: dict[str, ScalarField] | None = None


@dataclass(frozen=True)
class MaterialOutputResult:
    output_id: str
    value_type: str
    scalar_field: ScalarField | None
    rgba_field: RGBAField
    mask_fields: dict[str, ScalarField]
    legacy_scalar_field: ScalarField | None = None


@dataclass(frozen=True)
class MaterialRenderResult:
    outputs: dict[str, MaterialOutputResult]


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

    def render_output_uncached(self, recipe: ProjectRecipe, output_id: str, **kwargs):
        return self.render_output(recipe, output_id, use_cache=False, **kwargs)

    def render(
        self,
        recipe: ProjectRecipe,
        *,
        width: int | None = None,
        height: int | None = None,
        render_context: RenderContext | None = None,
        use_cache: bool = True,
    ) -> RenderResult:
        if not recipe.outputs:
            raise ValueError("A material must contain at least one output")
        output = recipe.outputs[0]
        result = self.render_output(
            recipe,
            output.output_id,
            width=width,
            height=height,
            render_context=render_context,
            use_cache=use_cache,
        )
        # Compatibility result for pre-material callers. Scalar outputs expose their
        # actual field; legacy color projects retain the last scalar-layer field.
        scalar = (
            result.scalar_field if result.value_type == "scalar" else result.legacy_scalar_field
        )
        return RenderResult(scalar, result.rgba_field, result.mask_fields)

    def render_material(
        self,
        recipe: ProjectRecipe,
        *,
        width: int | None = None,
        height: int | None = None,
        render_context: RenderContext | None = None,
        use_cache: bool = True,
    ) -> MaterialRenderResult:
        results = {
            output.output_id: self.render_output(
                recipe,
                output.output_id,
                width=width,
                height=height,
                render_context=render_context,
                use_cache=use_cache,
            )
            for output in recipe.outputs
        }
        return MaterialRenderResult(results)

    def render_output(
        self,
        recipe: ProjectRecipe,
        output_id: str,
        *,
        width: int | None = None,
        height: int | None = None,
        render_context: RenderContext | None = None,
        use_cache: bool = True,
    ) -> MaterialOutputResult:
        ensure_valid_recipe(recipe, self.registry)
        output = recipe.output(output_id)
        output_width = recipe.width if width is None else width
        output_height = recipe.height if height is None else height
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
        composite = self._clear_buffer(output, output_height, output_width)
        scalar_result: ScalarField | None = None
        legacy_scalar: ScalarField | None = None
        mask_fields: dict[str, ScalarField] = {}
        try:
            for layer in output.layers:
                context.check_cancelled()
                if layer.mask is not None:
                    mask_fields[layer.layer_id] = evaluation.resolve_binding(layer.mask)
            visible = [layer for layer in output.layers if layer.enabled]
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
                context.check_cancelled()
                mask = mask_fields.get(layer.layer_id)
                if output.value_type == "scalar":
                    if scalar is None:
                        raise ValueError(
                            f"Output {output.name!r} requires scalar layers; "
                            f"{layer.name!r} produced RGBA"
                        )
                    composite = composite_scalar(
                        composite, scalar, layer.opacity, layer.blend_mode, mask
                    )
                else:
                    if output.value_type == "normal" and scalar is not None:
                        raise ValueError(
                            f"Normal output {output.name!r} requires RGBA layers; "
                            "use Height to Normal"
                        )
                    composite = composite_rgba(
                        composite,
                        rgba,
                        layer.opacity,
                        layer.blend_mode,
                        mask,
                    )
                if scalar is not None:
                    legacy_scalar = scalar
                context.check_cancelled()
        except RenderCancelled:
            self.session.cancellation_observed()
            raise
        if output.value_type == "scalar":
            scalar_result = validate_scalar_field(composite)
            preview = np.empty((*scalar_result.shape, 4), dtype=np.float32)
            preview[..., :3] = scalar_result[..., None]
            preview[..., 3] = 1.0
            rgba_result = validate_rgba_field(preview)
        else:
            rgba_result = validate_rgba_field(composite)
        return MaterialOutputResult(
            output_id, output.value_type, scalar_result, rgba_result, mask_fields, legacy_scalar
        )

    @staticmethod
    def _clear_buffer(output: MaterialOutputRecipe, height: int, width: int):
        if output.value_type == "scalar":
            return np.full((height, width), output.clear_value, dtype=np.float32)
        return np.broadcast_to(
            np.asarray(output.clear_value, dtype=np.float32), (height, width, 4)
        ).copy()


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


def composite_scalar(
    backdrop: ScalarField,
    source: ScalarField,
    opacity: float,
    blend_mode: str = "normal",
    mask: ScalarField | None = None,
) -> ScalarField:
    """Composite normalized scalar layers directly, without a luminance round trip."""
    base = validate_scalar_field(backdrop, name="scalar backdrop")
    top = validate_scalar_field(source, name="scalar source")
    if base.shape != top.shape:
        raise ValueError("Scalar layers must have matching dimensions")
    if not np.isfinite(opacity) or not 0.0 <= opacity <= 1.0:
        raise ValueError("Layer opacity must be between zero and one")
    if blend_mode not in {"normal", "multiply", "screen", "add"}:
        raise ValueError(f"Unsupported blend mode: {blend_mode}")
    amount = np.full(base.shape, opacity, dtype=np.float32)
    if mask is not None:
        mask_field = validate_scalar_field(mask, name="layer mask")
        if mask_field.shape != base.shape:
            raise ValueError("Layer mask dimensions must match the composite")
        amount *= np.clip(mask_field, 0.0, 1.0)
    if blend_mode == "normal":
        result = base * (1.0 - amount) + top * amount
    elif blend_mode == "multiply":
        result = base * (1.0 - amount + top * amount)
    elif blend_mode == "screen":
        blended = base + top - base * top
        result = base * (1.0 - amount) + blended * amount
    else:
        result = base + top * amount
    return np.clip(result, 0.0, 1.0).astype(np.float32, copy=False)
