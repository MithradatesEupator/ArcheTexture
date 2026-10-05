from __future__ import annotations

from archetexture.core.operations import (
    OperationDefinition,
    OperationDefinitionSet,
    OperationType,
    Seamlessness,
)
from archetexture.core.parameters import ParameterSpec, ParameterType
from archetexture.generators import basic as generators
from archetexture.transforms import basic as transforms

REGISTRY = OperationDefinitionSet()


def _spec(
    identifier: str,
    name: str,
    kind: ParameterType,
    default,
    minimum: float,
    maximum: float,
    step: float,
) -> ParameterSpec:
    return ParameterSpec(
        identifier,
        name,
        kind,
        default=default,
        min_value=minimum,
        max_value=maximum,
        step=step,
    )


def builtin_definitions() -> tuple[OperationDefinition, ...]:
    return (
        OperationDefinition(
            "generator.constant",
            1,
            "Constant",
            "Generator",
            "Produces a constant scalar field.",
            OperationType.GENERATOR,
            (),
            "scalar",
            (_spec("value", "Value", ParameterType.FLOAT, 0.5, 0.0, 1.0, 0.01),),
            Seamlessness.INHERENT,
            generators.constant,
        ),
        OperationDefinition(
            "generator.white_noise",
            1,
            "White Noise",
            "Generator",
            "Deterministic uniform scalar noise.",
            OperationType.GENERATOR,
            (),
            "scalar",
            (
                ParameterSpec(
                    "seed",
                    "Seed",
                    ParameterType.SEED,
                    default=0,
                    min_value=0,
                    max_value=2**31 - 1,
                    step=1,
                    allows_modulation=False,
                ),
            ),
            Seamlessness.UNKNOWN,
            generators.white_noise,
        ),
        OperationDefinition(
            "generator.linear_gradient",
            1,
            "Linear Gradient",
            "Generator",
            "Projects a normalized gradient along the selected angle.",
            OperationType.GENERATOR,
            (),
            "scalar",
            (_spec("angle", "Angle", ParameterType.ANGLE, 0.0, 0.0, 360.0, 1.0),),
            Seamlessness.UNKNOWN,
            generators.linear_gradient,
        ),
        OperationDefinition(
            "generator.radial_gradient",
            1,
            "Radial Gradient",
            "Generator",
            "Produces a centered falloff whose radius is measured against the image width.",
            OperationType.GENERATOR,
            (),
            "scalar",
            (_spec("radius", "Radius", ParameterType.FLOAT, 0.5, 0.01, 1.0, 0.01),),
            Seamlessness.UNKNOWN,
            generators.radial_gradient,
        ),
        OperationDefinition(
            "transform.invert",
            1,
            "Invert",
            "Transform",
            "Inverts scalar values.",
            OperationType.TRANSFORM,
            ("scalar",),
            "scalar",
            (),
            Seamlessness.PRESERVES,
            transforms.invert,
        ),
        OperationDefinition(
            "transform.threshold",
            1,
            "Threshold",
            "Transform",
            "Maps values at or above the threshold to one.",
            OperationType.TRANSFORM,
            ("scalar",),
            "scalar",
            (_spec("threshold", "Threshold", ParameterType.FLOAT, 0.5, 0.0, 1.0, 0.01),),
            Seamlessness.PRESERVES,
            transforms.threshold,
        ),
        OperationDefinition(
            "transform.quantize",
            1,
            "Quantize",
            "Transform",
            "Quantizes normalized values to the selected number of levels.",
            OperationType.TRANSFORM,
            ("scalar",),
            "scalar",
            (_spec("levels", "Levels", ParameterType.INTEGER, 8, 2, 256, 1),),
            Seamlessness.PRESERVES,
            transforms.quantize,
        ),
    )


def register_builtin_operations(target: OperationDefinitionSet = REGISTRY) -> None:
    for definition in builtin_definitions():
        if definition.identifier not in target.definitions:
            target.register(definition)


register_builtin_operations()
