from __future__ import annotations

from collections.abc import Mapping
from dataclasses import fields, is_dataclass
from typing import Any

from archetexture.core.parameters import ControlFieldBinding
from archetexture.core.recipe import (
    ControlFieldRecipe,
    LayerRecipe,
    OperationInstance,
    ProjectRecipe,
)


def iter_control_bindings(value: Any):
    """Yield bindings nested in supported parameter containers/dataclasses once."""
    seen: set[int] = set()

    def visit(item: Any):
        if isinstance(item, ControlFieldBinding):
            yield item
            return
        if not isinstance(item, (Mapping, list, tuple, set, frozenset)) and not is_dataclass(item):
            return
        identity = id(item)
        if identity in seen:
            return
        seen.add(identity)
        if isinstance(item, Mapping):
            children = item.values()
        elif isinstance(item, (list, tuple, set, frozenset)):
            children = item
        else:
            children = (getattr(item, field.name) for field in fields(item))
        for child in children:
            yield from visit(child)

    yield from visit(value)


def control_dependencies(value: Any) -> frozenset[str]:
    """Return direct Control Field identifiers referenced anywhere in a value."""
    return frozenset(binding.source_id for binding in iter_control_bindings(value))


def instance_dependencies(instance: OperationInstance) -> frozenset[str]:
    return control_dependencies((instance.parameters, instance.influence))


def control_field_dependencies(recipe: ProjectRecipe, control_id: str) -> frozenset[str]:
    control = recipe.control_fields.get(control_id)
    if not isinstance(control, ControlFieldRecipe):
        return frozenset()
    return frozenset(
        dependency
        for instance in (control.source, *control.transforms)
        for dependency in instance_dependencies(instance)
    )


def layer_content_dependencies(layer: LayerRecipe) -> frozenset[str]:
    """Dependencies that can change pre-composite pixels; excludes the layer mask."""
    return frozenset(
        dependency
        for instance in (layer.source, *layer.transforms)
        for dependency in instance_dependencies(instance)
    )


def layer_mask_dependencies(layer: LayerRecipe) -> frozenset[str]:
    return control_dependencies(layer.mask)


def transitive_control_closure(recipe: ProjectRecipe, roots) -> tuple[str, ...]:
    """Return a sorted, cycle-safe closure of defined Control Fields."""
    pending = sorted(set(roots), reverse=True)
    visited: set[str] = set()
    while pending:
        identifier = pending.pop()
        if identifier in visited or identifier not in recipe.control_fields:
            continue
        visited.add(identifier)
        dependencies = control_field_dependencies(recipe, identifier)
        pending.extend(sorted(dependencies - visited, reverse=True))
    return tuple(sorted(visited))


def control_dependency_definitions(recipe: ProjectRecipe, roots) -> dict[str, ControlFieldRecipe]:
    """Return only the defined Control Field recipes in a dependency closure."""
    return {
        identifier: recipe.control_fields[identifier]
        for identifier in transitive_control_closure(recipe, roots)
    }
