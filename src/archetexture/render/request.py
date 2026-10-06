from __future__ import annotations

from dataclasses import dataclass

from archetexture.core.assets import RenderContext
from archetexture.core.recipe import ProjectRecipe


@dataclass(frozen=True)
class RenderRequest:
    request_id: int
    recipe: ProjectRecipe
    width: int
    height: int
    render_context: RenderContext | None
