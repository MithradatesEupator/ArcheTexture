from __future__ import annotations

from dataclasses import dataclass, field

from archetexture.core.assets import RenderContext
from archetexture.core.cancellation import CancellationToken
from archetexture.core.recipe import ProjectRecipe


@dataclass(frozen=True)
class RenderRequest:
    request_id: int
    recipe: ProjectRecipe
    width: int
    height: int
    render_context: RenderContext | None
    cancellation_token: CancellationToken = field(default_factory=CancellationToken, compare=False)
