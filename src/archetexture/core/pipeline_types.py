from __future__ import annotations

from collections.abc import Iterable

from archetexture.core.operations import OperationDefinitionSet, OperationType
from archetexture.core.recipe import OperationInstance
from archetexture.core.registry import REGISTRY


def accepts_input(definition, input_type: str | None) -> bool:
    return input_type is not None and (
        not definition.input_types
        or "any" in definition.input_types
        or input_type in definition.input_types
    )


def pipeline_output_type(
    source: OperationInstance,
    transforms: Iterable[OperationInstance],
    registry: OperationDefinitionSet = REGISTRY,
) -> str | None:
    """Return the effective field type after enabled stages in a layer pipeline."""
    try:
        current = registry.get(source.operation_id).output_type
        for instance in transforms:
            definition = registry.get(instance.operation_id)
            if definition.operation_type != OperationType.TRANSFORM:
                return None
            if not accepts_input(definition, current):
                return None
            if instance.enabled:
                current = definition.output_type
        return current
    except (AttributeError, KeyError, TypeError):
        return None


def valid_transform_chain(
    source: OperationInstance,
    transforms: Iterable[OperationInstance],
    *,
    color_ramp_active: bool = False,
    registry: OperationDefinitionSet = REGISTRY,
) -> bool:
    output_type = pipeline_output_type(source, transforms, registry)
    return output_type is not None and not (color_ramp_active and output_type != "scalar")


def compatible_append_transforms(
    source: OperationInstance,
    transforms: Iterable[OperationInstance],
    *,
    color_ramp_active: bool = False,
    registry: OperationDefinitionSet = REGISTRY,
):
    """Return registered transforms that can be appended without breaking output types."""
    current = pipeline_output_type(source, transforms, registry)
    if current is None:
        return ()
    compatible = []
    for definition in registry.definitions.values():
        if definition.operation_type != OperationType.TRANSFORM:
            continue
        if not accepts_input(definition, current):
            continue
        if color_ramp_active and definition.output_type != "scalar":
            continue
        compatible.append(definition)
    return tuple(compatible)
