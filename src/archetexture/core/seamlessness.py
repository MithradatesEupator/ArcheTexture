from __future__ import annotations

from archetexture.core.dependencies import instance_dependencies
from archetexture.core.operations import OperationDefinitionSet, OperationType, Seamlessness
from archetexture.core.recipe import LayerRecipe, OperationInstance, ProjectRecipe
from archetexture.core.registry import REGISTRY


def _has_spatial_binding(instance: OperationInstance) -> bool:
    return bool(instance_dependencies(instance))


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


def recipe_seamlessness(
    recipe: ProjectRecipe,
    registry: OperationDefinitionSet = REGISTRY,
    *,
    output_id: str | None = None,
) -> str:
    """Conservatively report seamlessness for one selected material output."""
    output = recipe.output(output_id) if output_id is not None else recipe.outputs[0]

    output_cache: dict[str, bool | None] = {}
    active_outputs: set[str] = set()
    field_cache: dict[str, bool | None] = {}
    active_fields: set[str] = set()

    def field_state(identifier: str) -> bool | None:
        if identifier in field_cache:
            return field_cache[identifier]
        if identifier in active_fields:
            return None
        field = recipe.control_fields.get(identifier)
        if field is None:
            return None
        active_fields.add(identifier)
        state = layer_state(LayerRecipe("field", identifier, field.source, field.transforms))
        active_fields.remove(identifier)
        field_cache[identifier] = state
        return state

    def dependencies_are_seamless(instance: OperationInstance) -> bool:
        dependencies = instance_dependencies(instance)
        return bool(dependencies) and all(field_state(item) is True for item in dependencies)

    def instance_source_state(instance: OperationInstance) -> bool | None:
        definition = registry.get(instance.operation_id)
        if instance.operation_id == "generator.output_scalar":
            target = instance.parameters.get("target")
            state = output_state(str(target)) if target else None
        elif instance_dependencies(instance):
            if definition.seamlessness == Seamlessness.INHERENT:
                state = True
            elif definition.seamlessness == Seamlessness.WRAP_CAPABLE:
                state = _wrap_capable_state(instance, definition.operation_type)
            elif definition.seamlessness == Seamlessness.BREAKS:
                state = False
            else:
                state = None
        else:
            state = _source_state(instance, registry)
        if instance_dependencies(instance):
            if state is True and dependencies_are_seamless(instance):
                return True
            return None
        return state

    def layer_state(layer: LayerRecipe) -> bool | None:
        state = instance_source_state(layer.source)
        for instance in layer.transforms:
            if not instance.enabled:
                continue
            definition = registry.get(instance.operation_id)
            if instance_dependencies(instance):
                if (
                    state is True
                    and definition.seamlessness == Seamlessness.PRESERVES
                    and dependencies_are_seamless(instance)
                ):
                    continue
                state = None
                continue
            if definition.seamlessness == Seamlessness.PRESERVES:
                pass
            elif (
                definition.seamlessness == Seamlessness.WRAP_CAPABLE
                and instance.operation_id == "transform.height_to_normal"
            ):
                state = state if instance.parameters.get("edge_mode", "wrap") == "wrap" else None
            elif definition.seamlessness == Seamlessness.INHERENT:
                state = True
            elif definition.seamlessness == Seamlessness.BREAKS:
                state = False
            elif definition.seamlessness == Seamlessness.WRAP_CAPABLE:
                state = _wrap_capable_state(instance, definition.operation_type)
            else:
                state = None
        return state

    def output_state(identifier: str) -> bool | None:
        if identifier in output_cache:
            return output_cache[identifier]
        if identifier in active_outputs:
            return None
        try:
            candidate = recipe.output(identifier)
        except (KeyError, StopIteration):
            return None
        active_outputs.add(identifier)
        states = [
            with_mask(layer) for layer in candidate.layers if layer.enabled and layer.opacity > 0.0
        ]
        if not states:
            result = None
        elif any(item is False for item in states):
            result = False
        elif all(item is True for item in states):
            result = True
        else:
            result = None
        active_outputs.remove(identifier)
        output_cache[identifier] = result
        return result

    def with_mask(layer: LayerRecipe) -> bool | None:
        state = layer_state(layer)
        if layer.mask is None:
            return state
        mask_state = field_state(layer.mask.source_id)
        if state is False or mask_state is False:
            return False
        if state is True and mask_state is True:
            return True
        return None

    result = output_state(output.output_id)
    return "Yes" if result is True else "No" if result is False else "Unknown"


def tile_edge_metrics(field) -> tuple[float, float]:
    """Return wrapped-edge gradient and adjacent gradients just inside the border."""
    import numpy as np

    values = np.asarray(field, dtype=np.float32)
    if values.ndim < 2 or values.shape[0] < 2 or values.shape[1] < 2:
        raise ValueError("Tile edge measurement requires an image at least 2×2 pixels")
    horizontal_seam = np.abs(values[:, 0] - values[:, -1]).mean(dtype=np.float64)
    vertical_seam = np.abs(values[0] - values[-1]).mean(dtype=np.float64)
    horizontal_inner = np.abs(np.diff(values, axis=1)).mean(dtype=np.float64)
    vertical_inner = np.abs(np.diff(values, axis=0)).mean(dtype=np.float64)
    return float(max(horizontal_seam, vertical_seam)), float(max(horizontal_inner, vertical_inner))


def measure_tileability(field, *, edge_multiplier: float = 2.0) -> tuple[bool, float, float]:
    """Compare the wrap gradient with immediately adjacent border gradients."""
    edge, interior = tile_edge_metrics(field)
    tolerance = max(interior * edge_multiplier, 1e-4)
    return edge <= tolerance, edge, interior
