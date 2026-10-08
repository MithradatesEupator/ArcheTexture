from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping

import numpy as np

from archetexture.core.assets import RenderContext
from archetexture.core.recipe import ProjectRecipe
from archetexture.preview.bindings import CHANNELS, PreviewMaterialBinding
from archetexture.render.engine import RenderEngine


@dataclass(frozen=True)
class PreviewMaterialSnapshot:
    request_id: int
    maps: Mapping[str, np.ndarray]
    resolved_output_ids: Mapping[str, str | None]
    width: int
    height: int


class PreviewSnapshotBuilder:
    def __init__(self, engine: RenderEngine | None = None):
        self.engine = engine or RenderEngine()
        self.rendered_outputs = 0
        self.last_requested_output_ids: tuple[str, ...] = ()

    def build(
        self,
        recipe: ProjectRecipe,
        binding: PreviewMaterialBinding,
        request_id: int,
        width: int,
        height: int,
        *,
        inspection: str = "Material",
        render_context: RenderContext | None = None,
    ) -> PreviewMaterialSnapshot:
        resolved = binding.resolve(recipe)
        required = {
            "Material": CHANNELS,
            "Base Color": ("base_color",),
            "Roughness": ("roughness",),
            "Metallic": ("metallic",),
            "Normal": ("normal",),
            "Height": ("height",),
            "Ambient Occlusion": ("ambient_occlusion",),
            "Emissive": ("emissive",),
            "Opacity": ("opacity",),
            "Lighting Only": (),
            "Tangent Normal": ("normal",),
        }.get(inspection, ())
        required = list(required)
        if inspection == "Opacity" and resolved["opacity"] is None and resolved["base_color"]:
            required.append("base_color")
        output_ids = tuple(
            dict.fromkeys(resolved[channel] for channel in required if resolved[channel])
        )
        self.last_requested_output_ids = output_ids
        context = (render_context or RenderContext()).with_runtime(
            self.engine.session.asset_cache, None
        )
        results = self.engine.render_outputs(
            recipe, output_ids, width=width, height=height, render_context=context
        )
        self.rendered_outputs += len(results)
        h, w = height, width
        maps = {
            "base_color": np.broadcast_to(
                np.array([0.5, 0.5, 0.5, 1], np.float32), (h, w, 4)
            ).copy(),
            "roughness": np.full((h, w, 1), 0.5, dtype=np.float32),
            "metallic": np.zeros((h, w, 1), dtype=np.float32),
            "normal": np.broadcast_to(np.array([0.5, 0.5, 1, 1], np.float32), (h, w, 4)).copy(),
            "height": np.full((h, w, 1), 0.5, dtype=np.float32),
            "ambient_occlusion": np.ones((h, w, 1), dtype=np.float32),
            "emissive": np.zeros((h, w, 4), dtype=np.float32),
            "opacity": np.ones((h, w, 1), dtype=np.float32),
        }
        for channel in required:
            output_id = resolved[channel]
            if output_id is None or output_id not in results:
                continue
            result = results[output_id]
            field = result.scalar_field if result.scalar_field is not None else result.rgba_field
            field = np.asarray(field, dtype=np.float32)
            if channel == "opacity" and field.ndim == 2:
                maps[channel] = np.clip(field[..., None], 0, 1)
            elif field.ndim == 2:
                maps[channel] = np.clip(field[..., None], 0, 1)
            else:
                maps[channel] = np.clip(field, 0, 1)
            if channel == "roughness" and recipe.output(output_id).semantic == "glossiness":
                maps[channel] = 1.0 - maps[channel]
        # Opacity falls back to Base Color alpha when no dedicated output is mapped.
        if resolved["opacity"] is None and resolved["base_color"] is not None:
            color = results.get(resolved["base_color"])
            if color is not None and color.rgba_field.shape[-1] >= 4:
                maps["opacity"] = color.rgba_field[..., 3:4].copy()
        for field in maps.values():
            field.setflags(write=False)
        return PreviewMaterialSnapshot(
            request_id,
            MappingProxyType(maps),
            MappingProxyType(dict(resolved)),
            width,
            height,
        )


def snapshot_result_to_bytes(snapshot: PreviewMaterialSnapshot) -> dict[str, bytes]:
    """Stable byte conversion used by upload and screenshot acceptance tests."""
    return {
        name: np.clip(field * 255, 0, 255).astype(np.uint8).tobytes()
        for name, field in snapshot.maps.items()
    }
