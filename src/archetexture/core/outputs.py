from __future__ import annotations

from dataclasses import dataclass
from typing import TypeAlias

ClearValue: TypeAlias = float | tuple[float, float, float, float]


@dataclass(frozen=True)
class OutputSemantic:
    identifier: str
    name: str
    category: str
    value_type: str
    clear_value: ClearValue
    export_suffix: str
    description: str
    color_ramp_applicable: bool = False


def _semantic(
    identifier: str,
    name: str,
    category: str,
    value_type: str,
    clear_value: ClearValue,
    suffix: str,
    description: str,
    *,
    color_ramp: bool = False,
) -> OutputSemantic:
    return OutputSemantic(
        identifier, name, category, value_type, clear_value, suffix, description, color_ramp
    )


_DEFINITIONS = (
    _semantic(
        "base_color",
        "Base Color",
        "Standard PBR",
        "color",
        (0, 0, 0, 0),
        "BaseColor",
        "Primary surface color.",
        color_ramp=True,
    ),
    _semantic(
        "roughness",
        "Roughness",
        "Standard PBR",
        "scalar",
        0.5,
        "Roughness",
        "Surface microsurface roughness.",
    ),
    _semantic("metallic", "Metallic", "Standard PBR", "scalar", 0.0, "Metallic", "Metalness mask."),
    _semantic(
        "normal",
        "Normal",
        "Standard PBR",
        "normal",
        (0.5, 0.5, 1.0, 1.0),
        "Normal",
        "Tangent-space normal encoding; height-to-normal is supported.",
    ),
    _semantic(
        "height", "Height", "Standard PBR", "scalar", 0.5, "Height", "Normalized height field."
    ),
    _semantic(
        "ambient_occlusion",
        "Ambient Occlusion",
        "Standard PBR",
        "scalar",
        1.0,
        "AO",
        "Ambient occlusion mask.",
    ),
    _semantic("opacity", "Opacity", "Standard PBR", "scalar", 1.0, "Opacity", "Surface opacity."),
    _semantic(
        "emissive",
        "Emissive",
        "Standard PBR",
        "color",
        (0, 0, 0, 1),
        "Emissive",
        "Emitted surface color.",
        color_ramp=True,
    ),
    _semantic(
        "diffuse",
        "Diffuse",
        "Specular / Legacy",
        "color",
        (0, 0, 0, 0),
        "Diffuse",
        "Diffuse reflectance color.",
        color_ramp=True,
    ),
    _semantic(
        "specular_color",
        "Specular Color",
        "Specular / Legacy",
        "color",
        (0.04, 0.04, 0.04, 1),
        "Specular",
        "Specular reflectance color.",
        color_ramp=True,
    ),
    _semantic(
        "specular_level",
        "Specular Level",
        "Specular / Legacy",
        "scalar",
        0.5,
        "SpecularLevel",
        "Scalar specular intensity.",
    ),
    _semantic(
        "glossiness",
        "Glossiness",
        "Specular / Legacy",
        "scalar",
        0.5,
        "Glossiness",
        "Inverse roughness convention.",
    ),
    _semantic(
        "displacement",
        "Displacement",
        "Specular / Legacy",
        "scalar",
        0.5,
        "Displacement",
        "Normalized displacement field.",
    ),
    _semantic(
        "transmission",
        "Transmission",
        "Advanced",
        "scalar",
        0.0,
        "Transmission",
        "Transmission weight.",
    ),
    _semantic(
        "thickness",
        "Thickness",
        "Advanced",
        "scalar",
        0.0,
        "Thickness",
        "Normalized thickness field.",
    ),
    _semantic(
        "clearcoat", "Clearcoat", "Advanced", "scalar", 0.0, "Clearcoat", "Clearcoat weight."
    ),
    _semantic(
        "clearcoat_roughness",
        "Clearcoat Roughness",
        "Advanced",
        "scalar",
        0.0,
        "ClearcoatRoughness",
        "Clearcoat roughness.",
    ),
    _semantic("sheen", "Sheen", "Advanced", "scalar", 0.0, "Sheen", "Sheen weight."),
    _semantic(
        "sheen_roughness",
        "Sheen Roughness",
        "Advanced",
        "scalar",
        0.5,
        "SheenRoughness",
        "Sheen roughness.",
    ),
    _semantic(
        "anisotropy", "Anisotropy", "Advanced", "scalar", 0.0, "Anisotropy", "Anisotropy amount."
    ),
    _semantic(
        "anisotropy_rotation",
        "Anisotropy Rotation",
        "Advanced",
        "scalar",
        0.0,
        "AnisotropyRotation",
        "Anisotropy orientation.",
    ),
    _semantic(
        "subsurface",
        "Subsurface Weight",
        "Advanced",
        "scalar",
        0.0,
        "Subsurface",
        "Subsurface scattering weight.",
    ),
    _semantic(
        "curvature", "Curvature", "Utility", "scalar", 0.5, "Curvature", "Curvature utility field."
    ),
    _semantic("cavity", "Cavity", "Utility", "scalar", 0.0, "Cavity", "Cavity utility field."),
    _semantic("mask", "Generic Mask", "Utility", "scalar", 0.0, "Mask", "Generic utility mask."),
    _semantic(
        "data", "Generic Data", "Utility", "scalar", 0.0, "Data", "Generic normalized scalar data."
    ),
    _semantic(
        "custom_color",
        "Custom Color",
        "Custom",
        "color",
        (0, 0, 0, 0),
        "CustomColor",
        "User-defined color output.",
        color_ramp=True,
    ),
    _semantic(
        "custom_scalar",
        "Custom Scalar",
        "Custom",
        "scalar",
        0.0,
        "CustomScalar",
        "User-defined scalar output.",
    ),
)

OUTPUT_SEMANTICS = {definition.identifier: definition for definition in _DEFINITIONS}
OUTPUT_CATEGORIES = ("Standard PBR", "Specular / Legacy", "Advanced", "Utility", "Custom")


def semantic_definition(identifier: str) -> OutputSemantic:
    try:
        return OUTPUT_SEMANTICS[identifier]
    except KeyError as exc:
        raise ValueError(f"Unknown material output semantic: {identifier}") from exc


def semantics_in_category(category: str) -> tuple[OutputSemantic, ...]:
    return tuple(item for item in _DEFINITIONS if item.category == category)
