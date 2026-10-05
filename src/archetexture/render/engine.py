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
from archetexture.core.pipeline import evaluate_recipe
from archetexture.core.recipe import ProjectRecipe
from archetexture.core.registry import REGISTRY


@dataclass(frozen=True)
class RenderResult:
    scalar_field: ScalarField | None
    rgba_field: RGBAField


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
        field = evaluate_recipe(
            recipe,
            width=width,
            height=height,
            registry=self.registry,
        )
        if field.ndim == 2:
            scalar = validate_scalar_field(field)
            if recipe.color_ramp is None:
                rgba = np.empty((*scalar.shape, 4), dtype=np.float32)
                rgba[..., :3] = scalar[..., None]
                rgba[..., 3] = 1.0
            else:
                rgba = recipe.color_ramp.apply(scalar)
            return RenderResult(scalar, validate_rgba_field(rgba))
        rgba = validate_rgba_field(field)
        return RenderResult(None, rgba)
