from __future__ import annotations

from dataclasses import dataclass, field

from archetexture.core.recipe import ProjectRecipe

CHANNELS = (
    "base_color",
    "roughness",
    "metallic",
    "normal",
    "height",
    "ambient_occlusion",
    "emissive",
    "opacity",
)
CHANNEL_LABELS = {
    "base_color": "Base Color",
    "roughness": "Roughness",
    "metallic": "Metallic",
    "normal": "Normal",
    "height": "Height",
    "ambient_occlusion": "Ambient Occlusion",
    "emissive": "Emissive",
    "opacity": "Opacity",
}


@dataclass
class PreviewMaterialBinding:
    """Preview-only mapping from PBR channels to stable material output IDs."""

    overrides: dict[str, str | None] = field(default_factory=dict)

    def resolve(self, recipe: ProjectRecipe) -> dict[str, str | None]:
        by_semantic: dict[str, list[str]] = {}
        for output in recipe.outputs:
            by_semantic.setdefault(output.semantic, []).append(output.output_id)
        automatic = {
            "base_color": first(by_semantic, "base_color", "diffuse"),
            "roughness": first(by_semantic, "roughness", "glossiness"),
            "metallic": first(by_semantic, "metallic"),
            "normal": first(by_semantic, "normal"),
            "height": first(by_semantic, "height", "displacement"),
            "ambient_occlusion": first(by_semantic, "ambient_occlusion"),
            "emissive": first(by_semantic, "emissive"),
            "opacity": first(by_semantic, "opacity"),
        }
        for channel, output_id in self.overrides.items():
            if channel in CHANNELS and output_id in compatible_output_ids(recipe, channel):
                automatic[channel] = output_id
        return automatic


def first(by_semantic: dict[str, list[str]], *semantics: str) -> str | None:
    return next((by_semantic[item][0] for item in semantics if by_semantic.get(item)), None)


def compatible_output_ids(recipe: ProjectRecipe, channel: str) -> tuple[str, ...]:
    types = {
        "base_color": {"color"},
        "roughness": {"scalar"},
        "metallic": {"scalar"},
        "normal": {"normal"},
        "height": {"scalar"},
        "ambient_occlusion": {"scalar"},
        "emissive": {"color"},
        "opacity": {"scalar"},
    }
    expected = types[channel]
    return tuple(output.output_id for output in recipe.outputs if output.value_type in expected)
