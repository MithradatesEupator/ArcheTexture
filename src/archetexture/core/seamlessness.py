from __future__ import annotations

from archetexture.core.operations import OperationDefinitionSet, OperationType, Seamlessness
from archetexture.core.parameters import ControlFieldBinding
from archetexture.core.recipe import LayerRecipe, OperationInstance, ProjectRecipe
from archetexture.core.registry import REGISTRY


def _has_spatial_binding(instance: OperationInstance) -> bool:
    return isinstance(instance.influence, ControlFieldBinding) or any(
        isinstance(value, ControlFieldBinding) for value in instance.parameters.values()
    )


def _wrap_capable_state(instance: OperationInstance, operation_type: OperationType) -> bool | None:
    if (
        operation_type == OperationType.GENERATOR
        and instance.operation_id == "generator.checker_grid"
    ):
        pattern = instance.parameters.get("pattern", "checker")
        cells_x = instance.parameters.get("cells_x", 8)
        cells_y = instance.parameters.get("cells_y", 8)
        if (
            not isinstance(cells_x, int)
            or isinstance(cells_x, bool)
            or not isinstance(cells_y, int)
            or isinstance(cells_y, bool)
            or cells_x <= 0
            or cells_y <= 0
        ):
            return None
        if pattern == "grid":
            return True
        if pattern == "checker":
            return cells_x % 2 == 0 and cells_y % 2 == 0
    return None


def _source_state(instance: OperationInstance, registry: OperationDefinitionSet) -> bool | None:
    definition = registry.get(instance.operation_id)
    if _has_spatial_binding(instance):
        return None
    match definition.seamlessness:
        case Seamlessness.INHERENT:
            return True
        case Seamlessness.BREAKS:
            return False
        case Seamlessness.WRAP_CAPABLE:
            return _wrap_capable_state(instance, definition.operation_type)
        case _:
            return None


def _layer_state(layer: LayerRecipe, registry: OperationDefinitionSet) -> bool | None:
    state = _source_state(layer.source, registry)
    for instance in layer.transforms:
        if not instance.enabled:
            continue
        definition = registry.get(instance.operation_id)
        if _has_spatial_binding(instance):
            state = None
        elif definition.seamlessness == Seamlessness.PRESERVES:
            pass
        elif (
            definition.seamlessness == Seamlessness.WRAP_CAPABLE
            and instance.operation_id == "transform.height_to_normal"
        ):
            if instance.parameters.get("edge_mode", "wrap") != "wrap":
                state = None
        elif definition.seamlessness == Seamlessness.INHERENT:
            state = True
        elif definition.seamlessness == Seamlessness.BREAKS:
            state = False
        else:
            state = _wrap_capable_state(instance, definition.operation_type)
    return state


def recipe_seamlessness(recipe: ProjectRecipe, registry: OperationDefinitionSet = REGISTRY) -> str:
    """Conservatively report whether the visible composite is proven tile-periodic."""
    states = [
        _layer_state(layer, registry)
        for layer in recipe.layers
        if layer.enabled and layer.opacity > 0.0
    ]
    if not states:
        return "Unknown"
    if any(state is False for state in states):
        return "No"
    if all(state is True for state in states):
        return "Yes"
    return "Unknown"
