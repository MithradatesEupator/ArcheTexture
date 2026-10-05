from __future__ import annotations

from archetexture.core.operations import (
    OperationDefinition,
    OperationDefinitionSet,
    OperationType,
    Seamlessness,
)
from archetexture.core.parameters import ParameterSpec, ParameterType

REGISTRY = OperationDefinitionSet()


def register_builtin_operations() -> None:
    if REGISTRY.definitions:
        return

    defs: list[OperationDefinition] = [
        OperationDefinition(
            identifier="generator.constant",
            version=1,
            name="Constant",
            category="Generator",
            description="Produces a constant scalar field.",
            operation_type=OperationType.GENERATOR,
            input_types=(),
            output_type="scalar",
            parameter_specs=(
                ParameterSpec(
                    "value",
                    "Value",
                    ParameterType.FLOAT,
                    default=0.5,
                    min_value=0.0,
                    max_value=1.0,
                    step=0.01,
                ),
            ),
            seamlessness=Seamlessness.INHERENT,
        ),
        OperationDefinition(
            identifier="generator.white_noise",
            version=1,
            name="White Noise",
            category="Generator",
            description="Generates random scalar noise.",
            operation_type=OperationType.GENERATOR,
            input_types=(),
            output_type="scalar",
            parameter_specs=(
                ParameterSpec(
                    "seed",
                    "Seed",
                    ParameterType.SEED,
                    default=0,
                    min_value=0,
                    max_value=2**31 - 1,
                    step=1,
                ),
            ),
            seamlessness=Seamlessness.UNKNOWN,
        ),
        OperationDefinition(
            identifier="generator.linear_gradient",
            version=1,
            name="Linear Gradient",
            category="Generator",
            description="Generates a linear gradient field.",
            operation_type=OperationType.GENERATOR,
            input_types=(),
            output_type="scalar",
            parameter_specs=(
                ParameterSpec(
                    "angle",
                    "Angle",
                    ParameterType.ANGLE,
                    default=0.0,
                    min_value=0.0,
                    max_value=360.0,
                    step=1.0,
                ),
            ),
            seamlessness=Seamlessness.UNKNOWN,
        ),
        OperationDefinition(
            identifier="generator.radial_gradient",
            version=1,
            name="Radial Gradient",
            category="Generator",
            description="Generates a radial gradient field.",
            operation_type=OperationType.GENERATOR,
            input_types=(),
            output_type="scalar",
            parameter_specs=(
                ParameterSpec(
                    "radius",
                    "Radius",
                    ParameterType.FLOAT,
                    default=0.5,
                    min_value=0.0,
                    max_value=1.0,
                    step=0.01,
                ),
            ),
            seamlessness=Seamlessness.UNKNOWN,
        ),
        OperationDefinition(
            identifier="transform.invert",
            version=1,
            name="Invert",
            category="Transform",
            description="Inverts scalar values.",
            operation_type=OperationType.TRANSFORM,
            input_types=("scalar",),
            output_type="scalar",
            parameter_specs=(),
            seamlessness=Seamlessness.PRESERVES,
        ),
        OperationDefinition(
            identifier="transform.threshold",
            version=1,
            name="Threshold",
            category="Transform",
            description="Thresholds values.",
            operation_type=OperationType.TRANSFORM,
            input_types=("scalar",),
            output_type="scalar",
            parameter_specs=(
                ParameterSpec(
                    "threshold",
                    "Threshold",
                    ParameterType.FLOAT,
                    default=0.5,
                    min_value=0.0,
                    max_value=1.0,
                    step=0.01,
                ),
            ),
            seamlessness=Seamlessness.PRESERVES,
        ),
        OperationDefinition(
            identifier="transform.quantize",
            version=1,
            name="Quantize",
            category="Transform",
            description="Quantizes to bands.",
            operation_type=OperationType.TRANSFORM,
            input_types=("scalar",),
            output_type="scalar",
            parameter_specs=(
                ParameterSpec(
                    "levels",
                    "Levels",
                    ParameterType.INTEGER,
                    default=8,
                    min_value=2,
                    max_value=256,
                    step=1,
                ),
            ),
            seamlessness=Seamlessness.PRESERVES,
        ),
    ]
    for definition in defs:
        REGISTRY.register(definition)


register_builtin_operations()
