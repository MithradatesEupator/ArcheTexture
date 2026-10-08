"""Editable multi-output starter recipes built from registered operations."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from archetexture.color.ramp import ColorRamp, ColorStop
from archetexture.core.outputs import semantic_definition
from archetexture.core.parameters import ControlFieldBinding, ControlFieldMapping
from archetexture.core.recipe import (
    ControlFieldRecipe,
    LayerRecipe,
    MaterialOutputRecipe,
    OperationInstance,
    ProjectRecipe,
)
from archetexture.core.registry import REGISTRY


@dataclass(frozen=True)
class MaterialStarter:
    name: str
    description: str
    generator: str
    colors: tuple[
        tuple[float, float, float], tuple[float, float, float], tuple[float, float, float]
    ]
    metallic: float = 0.0
    roughness_power: float = 1.0
    scale: float = 4.0

    @property
    def channels(self) -> tuple[str, ...]:
        return ("Base Color", "Roughness", "Metallic", "Normal", "Height", "Ambient Occlusion")


MATERIAL_STARTERS = (
    MaterialStarter(
        "Rough Stone",
        "Coarse fractured stone with broad mineral variation.",
        "generator.ridged_noise",
        ((0.07, 0.065, 0.055), (0.31, 0.29, 0.25), (0.68, 0.64, 0.57)),
        scale=4.2,
    ),
    MaterialStarter(
        "Polished Stone / Marble",
        "Polished pale stone crossed by warped mineral veins.",
        "generator.marble_veins",
        ((0.12, 0.10, 0.09), (0.57, 0.51, 0.45), (0.91, 0.87, 0.80)),
        roughness_power=1.35,
        scale=3.0,
    ),
    MaterialStarter(
        "Concrete",
        "Fine mottled concrete with subdued aggregate variation.",
        "generator.domain_warp",
        ((0.16, 0.15, 0.14), (0.43, 0.41, 0.37), (0.68, 0.65, 0.59)),
        scale=3.5,
    ),
    MaterialStarter(
        "Brick",
        "Running-bond masonry with readable recessed mortar.",
        "generator.brick",
        ((0.12, 0.035, 0.022), (0.47, 0.13, 0.065), (0.78, 0.34, 0.17)),
        scale=8.0,
    ),
    MaterialStarter(
        "Weathered Metal",
        "Dark metal with irregular surface oxidation and wear.",
        "generator.ridged_noise",
        ((0.035, 0.045, 0.05), (0.20, 0.22, 0.21), (0.55, 0.49, 0.38)),
        metallic=0.78,
        roughness_power=0.75,
        scale=5.0,
    ),
    MaterialStarter(
        "Brushed Metal",
        "Directional fine striations for a brushed metal surface.",
        "generator.bands",
        ((0.12, 0.14, 0.16), (0.38, 0.42, 0.45), (0.77, 0.79, 0.80)),
        metallic=0.9,
        roughness_power=0.78,
        scale=18.0,
    ),
    MaterialStarter(
        "Rusted Metal",
        "Warm oxide patches over a dark metallic base.",
        "generator.billow_noise",
        ((0.06, 0.035, 0.02), (0.36, 0.13, 0.045), (0.70, 0.36, 0.12)),
        metallic=0.68,
        roughness_power=0.72,
        scale=4.0,
    ),
    MaterialStarter(
        "Painted Metal",
        "Layered enamel color over a lightly textured metal substrate.",
        "generator.perlin_noise",
        ((0.025, 0.055, 0.10), (0.08, 0.25, 0.43), (0.34, 0.58, 0.72)),
        metallic=0.48,
        roughness_power=1.12,
        scale=6.0,
    ),
    MaterialStarter(
        "Wood Grain",
        "Curved growth rings with restrained grain distortion.",
        "generator.wood_rings",
        ((0.06, 0.025, 0.01), (0.34, 0.15, 0.055), (0.70, 0.43, 0.20)),
        scale=26.0,
    ),
    MaterialStarter(
        "Worn Wood",
        "Aged wood with broad grain, faded color, and softened relief.",
        "generator.wood_rings",
        ((0.08, 0.055, 0.035), (0.36, 0.24, 0.13), (0.70, 0.55, 0.34)),
        scale=18.0,
        roughness_power=0.85,
    ),
    MaterialStarter(
        "Fabric",
        "Soft woven textile with alternating thread relief.",
        "generator.weave",
        ((0.025, 0.055, 0.07), (0.16, 0.28, 0.32), (0.44, 0.58, 0.59)),
        scale=14.0,
    ),
    MaterialStarter(
        "Woven Cloth",
        "Crossed textile fibers with a subtle diagonal grain.",
        "generator.crosshatch",
        ((0.08, 0.045, 0.035), (0.34, 0.15, 0.08), (0.68, 0.39, 0.22)),
        scale=14.0,
    ),
    MaterialStarter(
        "Leather-like",
        "Pebbled organic grain with warm color variation.",
        "generator.cellular",
        ((0.035, 0.012, 0.008), (0.24, 0.075, 0.035), (0.55, 0.25, 0.12)),
        scale=8.0,
        roughness_power=0.82,
    ),
    MaterialStarter(
        "Ceramic / Tile",
        "Glazed honeycomb tiles with softened edge relief.",
        "generator.hex_cells",
        ((0.015, 0.07, 0.09), (0.04, 0.30, 0.38), (0.31, 0.73, 0.76)),
        roughness_power=1.4,
        scale=9.0,
    ),
    MaterialStarter(
        "Ground / Soil",
        "Layered earth with scattered, irregular fine structure.",
        "generator.domain_warp",
        ((0.035, 0.02, 0.008), (0.22, 0.12, 0.045), (0.45, 0.31, 0.13)),
        scale=4.2,
    ),
    MaterialStarter(
        "Rock / Cliff",
        "Rugged ridges and shadowed relief for cliff faces.",
        "generator.ridged_noise",
        ((0.045, 0.04, 0.035), (0.25, 0.23, 0.20), (0.58, 0.53, 0.44)),
        scale=5.5,
    ),
    MaterialStarter(
        "Sci-fi Panel",
        "Seeded ornamental panel relief with a cool synthetic finish.",
        "generator.truchet",
        ((0.008, 0.025, 0.05), (0.035, 0.14, 0.25), (0.15, 0.48, 0.63)),
        metallic=0.72,
        roughness_power=1.18,
        scale=8.0,
    ),
    MaterialStarter(
        "Generic Organic Surface",
        "Soft folded procedural forms for organic materials.",
        "generator.domain_warp",
        ((0.025, 0.05, 0.02), (0.18, 0.34, 0.11), (0.52, 0.65, 0.30)),
        roughness_power=0.88,
        scale=3.2,
    ),
)


def _instance(operation_id: str, parameters: dict, *, prefix: str = "op") -> OperationInstance:
    definition = REGISTRY.get(operation_id)
    return OperationInstance(
        f"{prefix}-{uuid.uuid4().hex[:10]}",
        operation_id,
        definition.version,
        parameters=parameters,
    )


def _default_parameters(operation_id: str) -> dict:
    return {spec.identifier: spec.default for spec in REGISTRY.get(operation_id).parameter_specs}


def _output(
    operation_id: str, semantic: str, name: str, parameters: dict, transforms=(), ramp=None
):
    output_id = f"output-{uuid.uuid4().hex[:10]}"
    source = _instance(operation_id, parameters, prefix="source")
    layer = LayerRecipe(
        f"layer-{uuid.uuid4().hex[:10]}", name, source, list(transforms), color_ramp=ramp
    )
    definition = semantic_definition(semantic)
    return MaterialOutputRecipe(
        output_id, name, semantic, definition.value_type, [layer]
    ), output_id


def create_material_starter(name: str, *, width: int = 256, height: int = 256) -> ProjectRecipe:
    """Build a deterministic editable recipe with shared controls and live channels."""
    starter = next((item for item in MATERIAL_STARTERS if item.name == name), None)
    if starter is None:
        raise ValueError(f"Unknown material starter: {name}")
    recipe = ProjectRecipe(width=width, height=height, seed=23)

    scale_source = _default_parameters("generator.value_noise")
    scale_source.update(seed=201, scale=1.35)
    wear_source = _default_parameters("generator.fractal_noise")
    wear_source.update(seed=307, scale=2.5, octaves=4)
    recipe.control_fields = {
        "Scale": ControlFieldRecipe(
            _instance("generator.value_noise", scale_source, prefix="control-scale")
        ),
        "Wear": ControlFieldRecipe(
            _instance("generator.fractal_noise", wear_source, prefix="control-wear")
        ),
    }

    height_id = f"output-{uuid.uuid4().hex[:10]}"
    source_parameters = _default_parameters(starter.generator)
    if "seed" in source_parameters:
        source_parameters["seed"] = 101 + MATERIAL_STARTERS.index(starter)
    if "scale" in source_parameters:
        spec = next(
            spec
            for spec in REGISTRY.get(starter.generator).parameter_specs
            if spec.identifier == "scale"
        )
        center = min(
            max(starter.scale, spec.min_value or starter.scale), spec.max_value or starter.scale
        )
        source_parameters["scale"] = ControlFieldBinding(
            "Scale",
            ControlFieldMapping(
                max(spec.min_value or 0.0, center * 0.8), min(spec.max_value or 48.0, center * 1.2)
            ),
        )
    elif "density" in source_parameters:
        spec = next(
            spec
            for spec in REGISTRY.get(starter.generator).parameter_specs
            if spec.identifier == "density"
        )
        center = starter.scale
        source_parameters["density"] = ControlFieldBinding(
            "Scale",
            ControlFieldMapping(
                max(spec.min_value or 0.0, center * 0.8), min(spec.max_value or 64.0, center * 1.2)
            ),
        )
    elif "frequency" in source_parameters:
        spec = next(
            spec
            for spec in REGISTRY.get(starter.generator).parameter_specs
            if spec.identifier == "frequency"
        )
        center = starter.scale
        source_parameters["frequency"] = ControlFieldBinding(
            "Scale",
            ControlFieldMapping(
                max(spec.min_value or 0.0, center * 0.8), min(spec.max_value or 128.0, center * 1.2)
            ),
        )
    elif "rings" in source_parameters:
        spec = next(
            spec
            for spec in REGISTRY.get(starter.generator).parameter_specs
            if spec.identifier == "rings"
        )
        center = starter.scale
        source_parameters["rings"] = ControlFieldBinding(
            "Scale",
            ControlFieldMapping(
                max(spec.min_value or 0.0, center * 0.8), min(spec.max_value or 128.0, center * 1.2)
            ),
        )
    elif "threads_x" in source_parameters:
        spec = next(
            spec
            for spec in REGISTRY.get(starter.generator).parameter_specs
            if spec.identifier == "threads_x"
        )
        center = starter.scale
        source_parameters["threads_x"] = ControlFieldBinding(
            "Scale",
            ControlFieldMapping(
                max(spec.min_value or 0.0, center * 0.8), min(spec.max_value or 128.0, center * 1.2)
            ),
        )
    elif "radius" in source_parameters:
        spec = next(
            spec
            for spec in REGISTRY.get(starter.generator).parameter_specs
            if spec.identifier == "radius"
        )
        source_parameters["radius"] = ControlFieldBinding(
            "Scale", ControlFieldMapping(0.18, min(spec.max_value or 0.49, 0.32))
        )
    if "distance_mode" in source_parameters:
        source_parameters["distance_mode"] = "edge"
    if starter.generator == "generator.bands":
        source_parameters.update(angle=0.0, waveform="sine")
    if starter.generator == "generator.brick":
        source_parameters.update(columns=10, rows=7)
        source_parameters["mortar"] = ControlFieldBinding("Scale", ControlFieldMapping(0.025, 0.11))
    height_gamma = _instance(
        "transform.gamma",
        {"power": ControlFieldBinding("Wear", ControlFieldMapping(0.65, 1.45))},
    )
    height_layer = LayerRecipe(
        f"layer-{uuid.uuid4().hex[:10]}",
        "Editable Height Field",
        _instance(starter.generator, source_parameters, prefix="height-source"),
        [height_gamma],
    )
    height = MaterialOutputRecipe(height_id, "Height", "height", "scalar", [height_layer])
    recipe.outputs.append(height)

    color_ramp = ColorRamp(
        (
            ColorStop(0.0, (*starter.colors[0], 1.0)),
            ColorStop(0.52, (*starter.colors[1], 1.0)),
            ColorStop(1.0, (*starter.colors[2], 1.0)),
        )
    )

    def ref(mode="Direct"):
        return {"target": height_id, "mode": mode}

    base, _ = _output("generator.output_scalar", "base_color", "Base Color", ref(), ramp=color_ramp)
    roughness_power = _instance(
        "transform.gamma",
        {
            "power": ControlFieldBinding(
                "Wear",
                ControlFieldMapping(
                    max(0.1, starter.roughness_power * 0.65),
                    min(4.0, starter.roughness_power * 1.45),
                ),
            )
        },
    )
    roughness, _ = _output(
        "generator.output_scalar", "roughness", "Roughness", ref(), (roughness_power,)
    )
    metallic_low = max(0.0, starter.metallic * 0.65)
    metallic_high = min(1.0, starter.metallic + 0.2) if starter.metallic > 0.05 else metallic_low
    metallic_remap = _instance(
        "transform.levels",
        {
            "input_black": 0.0,
            "input_white": 1.0,
            "gamma": 1.0,
            "output_black": metallic_low,
            "output_white": metallic_high,
        },
    )
    metallic, _ = _output(
        "generator.output_scalar", "metallic", "Metallic", ref(), (metallic_remap,)
    )
    ao_transforms = (
        _instance("transform.invert", {}),
        _instance("transform.smoothstep", {"edge0": 0.12, "edge1": 0.92}),
    )
    ao, _ = _output(
        "generator.output_scalar", "ambient_occlusion", "Ambient Occlusion", ref(), ao_transforms
    )
    normal_source = _default_parameters("generator.output_scalar")
    normal_source.update(target=height_id, mode="Direct")
    normal_transform = _instance(
        "transform.height_to_normal", _default_parameters("transform.height_to_normal")
    )
    normal, _ = _output(
        "generator.output_scalar", "normal", "Normal", normal_source, (normal_transform,)
    )
    recipe.outputs.extend((base, roughness, metallic, normal, ao))
    return recipe
