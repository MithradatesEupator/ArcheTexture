from __future__ import annotations

import copy
import uuid

from archetexture.core.outputs import semantic_definition
from archetexture.core.recipe import (
    LayerRecipe,
    MaterialOutputRecipe,
    OperationInstance,
    ProjectRecipe,
)
from archetexture.core.registry import REGISTRY

MATERIAL_PRESETS = {
    "Minimal PBR": ("base_color", "roughness", "normal"),
    "Metallic / Roughness PBR": (
        "base_color",
        "roughness",
        "metallic",
        "normal",
        "height",
        "ambient_occlusion",
        "emissive",
        "opacity",
    ),
    "Specular / Glossiness PBR": (
        "diffuse",
        "specular_color",
        "glossiness",
        "normal",
        "height",
        "ambient_occlusion",
        "emissive",
        "opacity",
    ),
    "Extended PBR": (
        "base_color",
        "roughness",
        "metallic",
        "normal",
        "height",
        "ambient_occlusion",
        "opacity",
        "emissive",
        "transmission",
        "thickness",
        "clearcoat",
        "clearcoat_roughness",
        "sheen",
        "sheen_roughness",
        "anisotropy",
    ),
    "Mask / Utility Set": ("curvature", "cavity", "ambient_occlusion", "thickness", "mask"),
    "Empty / Custom": (),
}


def new_material_output(semantic: str, name: str | None = None) -> MaterialOutputRecipe:
    definition = semantic_definition(semantic)
    output_id = f"output-{uuid.uuid4().hex[:12]}"
    layer_id = f"layer-{uuid.uuid4().hex[:12]}"
    source_id = f"source-{uuid.uuid4().hex[:12]}"
    if definition.value_type == "scalar":
        value = float(definition.clear_value)
        source = OperationInstance(source_id, "generator.constant", 1, parameters={"value": value})
        layers = [LayerRecipe(layer_id, "Layer 1", source)]
    elif definition.value_type == "normal":
        source = OperationInstance(source_id, "generator.constant", 1, parameters={"value": 0.5})
        transform = REGISTRY.get("transform.height_to_normal")
        operation = OperationInstance(
            f"op-{uuid.uuid4().hex[:12]}",
            transform.identifier,
            transform.version,
            parameters={spec.identifier: spec.default for spec in transform.parameter_specs},
        )
        layers = [LayerRecipe(layer_id, "Layer 1", source, [operation])]
    else:
        value = float(definition.clear_value[0])
        source = OperationInstance(source_id, "generator.constant", 1, parameters={"value": value})
        layers = [LayerRecipe(layer_id, "Layer 1", source)]
    return MaterialOutputRecipe(
        output_id,
        name or definition.name,
        semantic,
        definition.value_type,
        layers,
    )


def apply_material_preset(recipe: ProjectRecipe, preset_name: str) -> tuple[str, ...]:
    """Add missing preset semantics without removing or replacing existing outputs."""
    if preset_name not in MATERIAL_PRESETS:
        raise ValueError(f"Unknown material preset: {preset_name}")
    existing = {output.semantic for output in recipe.outputs}
    added = []
    for semantic in MATERIAL_PRESETS[preset_name]:
        if semantic in existing:
            continue
        output = new_material_output(semantic)
        recipe.outputs.append(output)
        existing.add(semantic)
        added.append(output.output_id)
    return tuple(added)


def duplicate_material_output(output: MaterialOutputRecipe) -> MaterialOutputRecipe:
    duplicate = copy.deepcopy(output)
    duplicate.output_id = f"output-{uuid.uuid4().hex[:12]}"
    duplicate.name = f"{output.name} Copy"
    for layer in duplicate.layers:
        layer.layer_id = f"layer-{uuid.uuid4().hex[:12]}"
        for instance in [layer.source, *layer.transforms]:
            instance.instance_id = f"op-{uuid.uuid4().hex[:12]}"
    return duplicate
