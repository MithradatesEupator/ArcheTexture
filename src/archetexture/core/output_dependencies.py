from __future__ import annotations

from collections.abc import Iterable, Iterator

from archetexture.core.recipe import OperationInstance, ProjectRecipe

OUTPUT_REFERENCE_OPERATIONS = frozenset({"generator.output_scalar", "generator.output_color"})


def iter_output_references(instance: OperationInstance) -> Iterator[str]:
    if instance.operation_id in OUTPUT_REFERENCE_OPERATIONS:
        target = (
            instance.parameters.get("target") if isinstance(instance.parameters, dict) else None
        )
        if isinstance(target, str) and target:
            yield target


def output_direct_dependencies(recipe: ProjectRecipe, output_id: str) -> set[str]:
    output = recipe.output(output_id)
    found: set[str] = set()
    for layer in output.layers:
        for instance in [layer.source, *layer.transforms]:
            found.update(iter_output_references(instance))
    return found


def output_dependency_graph(recipe: ProjectRecipe) -> dict[str, set[str]]:
    return {
        output.output_id: output_direct_dependencies(recipe, output.output_id)
        for output in recipe.outputs
    }


def transitive_output_dependencies(recipe: ProjectRecipe, output_id: str) -> set[str]:
    graph = output_dependency_graph(recipe)
    found: set[str] = set()
    pending = list(graph.get(output_id, ()))
    while pending:
        item = pending.pop()
        if item not in found:
            found.add(item)
            pending.extend(graph.get(item, ()))
    return found


def topological_output_order(
    recipe: ProjectRecipe, requested_outputs: Iterable[str] | None = None
) -> tuple[str, ...]:
    graph = output_dependency_graph(recipe)
    roots = list(requested_outputs if requested_outputs is not None else graph)
    order: list[str] = []
    visiting: list[str] = []
    visited: set[str] = set()

    def visit(output_id: str) -> None:
        if output_id in visiting:
            path = visiting[visiting.index(output_id) :] + [output_id]
            names = {output.output_id: output.name for output in recipe.outputs}
            raise ValueError(
                "Output dependency cycle: " + " → ".join(names.get(item, item) for item in path)
            )
        if output_id in visited:
            return
        if output_id not in graph:
            raise ValueError(f"Missing output dependency: {output_id}")
        visiting.append(output_id)
        for dependency in graph[output_id]:
            visit(dependency)
        visiting.pop()
        visited.add(output_id)
        order.append(output_id)

    for output_id in roots:
        visit(output_id)
    return tuple(order)
