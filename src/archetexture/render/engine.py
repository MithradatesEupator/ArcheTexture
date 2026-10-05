from __future__ import annotations

from archetexture.core.pipeline import evaluate_recipe
from archetexture.core.recipe import ProjectRecipe


class RenderEngine:
    def render(self, recipe: ProjectRecipe, *, width: int, height: int):
        return evaluate_recipe(recipe, width=width, height=height)
