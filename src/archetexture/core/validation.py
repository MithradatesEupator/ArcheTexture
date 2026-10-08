from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from archetexture.color.ramp import ColorRamp, ColorStop
from archetexture.core.assets import AssetReference
from archetexture.core.dependencies import iter_control_bindings
from archetexture.core.operations import OperationDefinitionSet, OperationType
from archetexture.core.output_dependencies import (
    OUTPUT_REFERENCE_OPERATIONS,
    iter_output_references,
)
from archetexture.core.outputs import OUTPUT_SEMANTICS
from archetexture.core.parameters import (
    ControlFieldBinding,
    ControlFieldMapping,
    ParameterSpec,
    ParameterType,
)
from archetexture.core.pipeline_types import accepts_input
from archetexture.core.recipe import (
    ControlFieldRecipe,
    LayerRecipe,
    MaterialOutputRecipe,
    OperationInstance,
    ProjectRecipe,
)
from archetexture.core.registry import REGISTRY

MAX_PROJECT_DIMENSION = 8192
MAX_PROJECT_SEED = 2**31 - 1


@dataclass(frozen=True)
class ValidationIssue:
    path: str
    message: str


class ValidationError(ValueError):
    def __init__(self, issues: list[ValidationIssue]):
        self.issues = tuple(issues)
        message = "; ".join(f"{issue.path}: {issue.message}" for issue in issues)
        super().__init__(message or "Validation failed")


def _finite_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _validate_mapping(
    mapping: ControlFieldMapping,
    path: str,
    issues: list[ValidationIssue],
    spec: ParameterSpec | None = None,
) -> None:
    if not _finite_number(mapping.output_min) or not _finite_number(mapping.output_max):
        issues.append(ValidationIssue(path, "mapping bounds must be finite numbers"))
    elif spec is not None:
        for name, value in (("output_min", mapping.output_min), ("output_max", mapping.output_max)):
            if spec.min_value is not None and value < spec.min_value:
                issues.append(ValidationIssue(f"{path}.{name}", "is below the parameter minimum"))
            if spec.max_value is not None and value > spec.max_value:
                issues.append(ValidationIssue(f"{path}.{name}", "is above the parameter maximum"))
    if not isinstance(mapping.invert, bool):
        issues.append(ValidationIssue(f"{path}.invert", "must be a boolean"))
    if not isinstance(mapping.curve, str) or mapping.curve not in (
        "linear",
        "smoothstep",
        "stepped",
    ):
        issues.append(ValidationIssue(f"{path}.curve", "must be linear, smoothstep, or stepped"))
    if mapping.quantize is not None and (
        not _finite_number(mapping.quantize) or mapping.quantize < 1
    ):
        issues.append(ValidationIssue(f"{path}.quantize", "must be a finite value of at least one"))


def _walk_bindings(value: Any):
    yield from iter_control_bindings(value)


def _validate_parameter_value(
    value: Any,
    spec: ParameterSpec,
    path: str,
    control_ids: set[str],
    issues: list[ValidationIssue],
) -> None:
    if isinstance(value, ControlFieldBinding):
        if not spec.allows_modulation or spec.type not in {
            ParameterType.FLOAT,
            ParameterType.INTEGER,
            ParameterType.ANGLE,
            ParameterType.PERCENT,
        }:
            issues.append(
                ValidationIssue(path, "this parameter does not allow control-field modulation")
            )
        if not isinstance(value.source_id, str) or value.source_id not in control_ids:
            issues.append(ValidationIssue(path, f"unknown control field: {value.source_id!r}"))
        if not isinstance(value.mapping, ControlFieldMapping):
            issues.append(ValidationIssue(f"{path}.mapping", "must be a ControlFieldMapping"))
        else:
            _validate_mapping(value.mapping, f"{path}.mapping", issues, spec)
        return

    kind = spec.type
    valid = True
    if kind in {ParameterType.FLOAT, ParameterType.ANGLE, ParameterType.PERCENT}:
        valid = _finite_number(value)
    elif kind in {ParameterType.INTEGER, ParameterType.SEED}:
        valid = isinstance(value, int) and not isinstance(value, bool)
    elif kind == ParameterType.BOOLEAN:
        valid = isinstance(value, bool)
    elif kind == ParameterType.ENUM:
        valid = isinstance(value, str) and value in spec.options
    elif kind == ParameterType.COLOR:
        valid = (
            isinstance(value, (tuple, list))
            and len(value) in {3, 4}
            and all(_finite_number(component) and 0.0 <= component <= 1.0 for component in value)
        )
    elif kind == ParameterType.POSITION_2D:
        valid = (
            isinstance(value, (tuple, list))
            and len(value) == 2
            and all(_finite_number(component) for component in value)
        )
    elif kind == ParameterType.IMAGE_ASSET:
        valid = (
            isinstance(value, AssetReference)
            and bool(value.path.strip())
            and value.kind == "image"
            and value.mode in {"absolute", "project_relative"}
            and not (value.mode == "absolute" and not Path(value.path).is_absolute())
            and not (
                value.mode == "project_relative"
                and (Path(value.path).is_absolute() or ".." in Path(value.path).parts)
            )
        )
    elif kind == ParameterType.MATERIAL_OUTPUT:
        valid = isinstance(value, str) and bool(value)
    if not valid:
        issues.append(ValidationIssue(path, f"must have type {kind.value}"))
        return

    if kind not in {
        ParameterType.BOOLEAN,
        ParameterType.ENUM,
        ParameterType.COLOR,
        ParameterType.POSITION_2D,
        ParameterType.IMAGE_ASSET,
        ParameterType.MATERIAL_OUTPUT,
    }:
        number = float(value)
        if spec.min_value is not None and number < spec.min_value:
            issues.append(ValidationIssue(path, f"must be at least {spec.min_value:g}"))
        if spec.max_value is not None and number > spec.max_value:
            issues.append(ValidationIssue(path, f"must be at most {spec.max_value:g}"))


def _validate_instance(
    instance: OperationInstance,
    path: str,
    expected_type: OperationType,
    registry: OperationDefinitionSet,
    control_ids: set[str],
    issues: list[ValidationIssue],
) -> str | None:
    if not isinstance(instance, OperationInstance):
        issues.append(ValidationIssue(path, "must be an operation instance"))
        return None
    try:
        definition = registry.get(instance.operation_id)
    except (KeyError, TypeError):
        issues.append(
            ValidationIssue(f"{path}.operation_id", f"unknown operation: {instance.operation_id!r}")
        )
        return None
    if definition.operation_type != expected_type:
        issues.append(
            ValidationIssue(
                path,
                f"operation must be a {expected_type.value}, got {definition.operation_type.value}",
            )
        )
    if (
        not isinstance(instance.operation_version, int)
        or isinstance(instance.operation_version, bool)
        or instance.operation_version != definition.version
    ):
        issues.append(
            ValidationIssue(
                f"{path}.operation_version",
                "version "
                f"{instance.operation_version!r} is not supported; "
                f"expected {definition.version}",
            )
        )
    if not isinstance(instance.enabled, bool):
        issues.append(ValidationIssue(f"{path}.enabled", "must be a boolean"))
    if not isinstance(instance.parameters, dict):
        issues.append(ValidationIssue(f"{path}.parameters", "must be an object"))
        params = {}
    else:
        params = instance.parameters
    known = {spec.identifier: spec for spec in definition.parameter_specs}
    for name, value in params.items():
        spec = known.get(name)
        if spec is None:
            issues.append(ValidationIssue(f"{path}.parameters.{name}", "unknown parameter"))
            continue
        _validate_parameter_value(
            value,
            spec,
            f"{path}.parameters.{name}",
            control_ids,
            issues,
        )
    for name, spec in known.items():
        if name not in params:
            if spec.required:
                issues.append(ValidationIssue(f"{path}.parameters.{name}", "is required"))
            else:
                _validate_parameter_value(
                    spec.default,
                    spec,
                    f"{path}.parameters.{name}",
                    control_ids,
                    issues,
                )
    influence = instance.influence
    if isinstance(influence, ControlFieldBinding):
        if not isinstance(influence.source_id, str) or influence.source_id not in control_ids:
            issues.append(
                ValidationIssue(
                    f"{path}.influence", f"unknown control field: {influence.source_id!r}"
                )
            )
        if not isinstance(influence.mapping, ControlFieldMapping):
            issues.append(
                ValidationIssue(f"{path}.influence.mapping", "must be a ControlFieldMapping")
            )
        else:
            _validate_mapping(
                influence.mapping,
                f"{path}.influence.mapping",
                issues,
                ParameterSpec("influence", "Influence", ParameterType.PERCENT, 1.0, 0.0, 1.0),
            )
    elif not _finite_number(influence) or not 0.0 <= float(influence) <= 1.0:
        issues.append(ValidationIssue(f"{path}.influence", "must be between zero and one"))
    if expected_type == OperationType.GENERATOR:
        if instance.enabled is False:
            issues.append(
                ValidationIssue(f"{path}.enabled", "a source generator cannot be disabled")
            )
        if isinstance(influence, ControlFieldBinding) or not (
            _finite_number(influence) and float(influence) == 1.0
        ):
            issues.append(
                ValidationIssue(
                    f"{path}.influence", "source generators do not use influence blending"
                )
            )
    return definition.output_type


def _instance_bindings(instance: OperationInstance):
    if not isinstance(instance, OperationInstance):
        return
    yield from _walk_bindings(instance.parameters)
    yield from _walk_bindings(instance.influence)


def validate_recipe(
    recipe: ProjectRecipe,
    registry: OperationDefinitionSet = REGISTRY,
) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    if not isinstance(recipe, ProjectRecipe):
        return [ValidationIssue("recipe", "must be a ProjectRecipe")]
    if not isinstance(recipe.schema_version, int) or isinstance(recipe.schema_version, bool):
        issues.append(ValidationIssue("schema_version", "must be an integer"))
    elif recipe.schema_version != 5:
        issues.append(ValidationIssue("schema_version", "supported schema version is 5"))
    for name in ("width", "height"):
        value = getattr(recipe, name)
        if (
            not isinstance(value, int)
            or isinstance(value, bool)
            or not 1 <= value <= MAX_PROJECT_DIMENSION
        ):
            issues.append(
                ValidationIssue(name, f"must be an integer from 1 to {MAX_PROJECT_DIMENSION}")
            )
    if (
        not isinstance(recipe.seed, int)
        or isinstance(recipe.seed, bool)
        or not 0 <= recipe.seed <= MAX_PROJECT_SEED
    ):
        issues.append(ValidationIssue("seed", f"must be an integer from 0 to {MAX_PROJECT_SEED}"))
    outputs = recipe.outputs if isinstance(recipe.outputs, list) else []
    if not isinstance(recipe.outputs, list):
        issues.append(ValidationIssue("outputs", "must be a list"))
    if not outputs:
        issues.append(ValidationIssue("outputs", "at least one material output is required"))
    if not isinstance(recipe.control_fields, dict):
        issues.append(ValidationIssue("control_fields", "must be an object"))
        control_fields = {}
    else:
        control_fields = recipe.control_fields
    control_ids = set(control_fields)

    output_ids: set[str] = set()
    layer_ids: set[str] = set()
    all_instances: list[OperationInstance | None] = []
    for output_index, output in enumerate(outputs):
        output_path = f"outputs[{output_index}]"
        if not isinstance(output, MaterialOutputRecipe):
            issues.append(ValidationIssue(output_path, "must be a MaterialOutputRecipe"))
            continue
        if not isinstance(output.output_id, str) or not output.output_id:
            issues.append(ValidationIssue(f"{output_path}.output_id", "must be a non-empty string"))
        elif output.output_id in output_ids:
            issues.append(
                ValidationIssue(f"{output_path}.output_id", "output identifiers must be unique")
            )
        else:
            output_ids.add(output.output_id)
        if not isinstance(output.name, str) or not output.name.strip():
            issues.append(ValidationIssue(f"{output_path}.name", "must be a non-empty string"))
        if not isinstance(output.enabled, bool):
            issues.append(ValidationIssue(f"{output_path}.enabled", "must be a boolean"))
        definition = OUTPUT_SEMANTICS.get(output.semantic)
        if definition is None:
            issues.append(ValidationIssue(f"{output_path}.semantic", "unknown output semantic"))
        elif output.value_type != definition.value_type:
            issues.append(
                ValidationIssue(f"{output_path}.value_type", "does not match semantic value type")
            )
        if not isinstance(output.export_suffix, str) or not output.export_suffix.strip():
            issues.append(
                ValidationIssue(f"{output_path}.export_suffix", "must be a non-empty string")
            )
        if output.value_type == "scalar":
            if (
                not _finite_number(output.clear_value)
                or not 0.0 <= float(output.clear_value) <= 1.0
            ):
                issues.append(
                    ValidationIssue(
                        f"{output_path}.clear_value", "scalar clear value must be normalized"
                    )
                )
        elif output.value_type in {"color", "normal"}:
            if (
                not isinstance(output.clear_value, (tuple, list))
                or len(output.clear_value) != 4
                or not all(
                    _finite_number(item) and 0.0 <= item <= 1.0 for item in output.clear_value
                )
            ):
                issues.append(
                    ValidationIssue(
                        f"{output_path}.clear_value", "must contain four normalized channels"
                    )
                )
        if not isinstance(output.layers, list):
            issues.append(ValidationIssue(f"{output_path}.layers", "must be a list"))
            layers = []
        else:
            layers = output.layers
        for layer_index, layer in enumerate(layers):
            path = f"{output_path}.layers[{layer_index}]"
            if not isinstance(layer, LayerRecipe):
                issues.append(ValidationIssue(path, "must be a LayerRecipe"))
                continue
            if not isinstance(layer.layer_id, str) or not layer.layer_id:
                issues.append(ValidationIssue(f"{path}.layer_id", "must be a non-empty string"))
            elif layer.layer_id in layer_ids:
                issues.append(
                    ValidationIssue(f"{path}.layer_id", "layer identifiers must be unique")
                )
            else:
                layer_ids.add(layer.layer_id)
            if not isinstance(layer.name, str) or not layer.name.strip():
                issues.append(ValidationIssue(f"{path}.name", "must be a non-empty string"))
            if not isinstance(layer.enabled, bool):
                issues.append(ValidationIssue(f"{path}.enabled", "must be a boolean"))
            if not _finite_number(layer.opacity) or not 0.0 <= float(layer.opacity) <= 1.0:
                issues.append(ValidationIssue(f"{path}.opacity", "must be between zero and one"))
            if not isinstance(layer.blend_mode, str) or layer.blend_mode not in {
                "normal",
                "multiply",
                "screen",
                "add",
            }:
                issues.append(ValidationIssue(f"{path}.blend_mode", "unsupported blend mode"))
            if layer.mask is not None:
                if not isinstance(layer.mask, ControlFieldBinding):
                    issues.append(
                        ValidationIssue(f"{path}.mask", "must be a ControlFieldBinding or None")
                    )
                else:
                    if (
                        not isinstance(layer.mask.source_id, str)
                        or layer.mask.source_id not in control_ids
                    ):
                        issues.append(
                            ValidationIssue(
                                f"{path}.mask", f"unknown control field: {layer.mask.source_id!r}"
                            )
                        )
                    if not isinstance(layer.mask.mapping, ControlFieldMapping):
                        issues.append(
                            ValidationIssue(f"{path}.mask.mapping", "must be a ControlFieldMapping")
                        )
                    else:
                        _validate_mapping(layer.mask.mapping, f"{path}.mask.mapping", issues)
                        if any(
                            not 0.0 <= bound <= 1.0
                            for bound in (
                                layer.mask.mapping.output_min,
                                layer.mask.mapping.output_max,
                            )
                            if _finite_number(bound)
                        ):
                            issues.append(
                                ValidationIssue(
                                    f"{path}.mask.mapping", "mask mapping bounds must be normalized"
                                )
                            )
            if layer.source is None:
                issues.append(ValidationIssue(f"{path}.source", "a source generator is required"))
                previous_type = None
            else:
                previous_type = _validate_instance(
                    layer.source,
                    f"{path}.source",
                    OperationType.GENERATOR,
                    registry,
                    control_ids,
                    issues,
                )
            if not isinstance(layer.transforms, list):
                issues.append(ValidationIssue(f"{path}.transforms", "must be a list"))
                layer_transforms = []
            else:
                layer_transforms = layer.transforms
            for index, instance in enumerate(layer_transforms):
                item_path = f"{path}.transforms[{index}]"
                current_type = _validate_instance(
                    instance, item_path, OperationType.TRANSFORM, registry, control_ids, issues
                )
                if isinstance(instance, OperationInstance):
                    try:
                        definition = registry.get(instance.operation_id)
                    except (KeyError, TypeError):
                        definition = None
                    if definition is not None and not accepts_input(definition, previous_type):
                        issues.append(
                            ValidationIssue(
                                item_path,
                                "cannot accept the preceding "
                                f"{previous_type or 'unknown'} field type",
                            )
                        )
                if isinstance(instance, OperationInstance) and instance.enabled:
                    previous_type = current_type
            ramp = layer.color_ramp
            if ramp is not None:
                ramp_path = f"{path}.color_ramp"
                if not isinstance(ramp, ColorRamp):
                    issues.append(ValidationIssue(ramp_path, "must be a ColorRamp"))
                else:
                    stops = ramp.stops if isinstance(ramp.stops, (tuple, list)) else ()
                    if not stops:
                        issues.append(
                            ValidationIssue(f"{ramp_path}.stops", "must contain at least one stop")
                        )
                    for index, stop in enumerate(stops):
                        stop_path = f"{ramp_path}.stops[{index}]"
                        if not isinstance(stop, ColorStop):
                            issues.append(ValidationIssue(stop_path, "must be a ColorStop"))
                            continue
                        if not _finite_number(stop.position) or not 0.0 <= stop.position <= 1.0:
                            issues.append(
                                ValidationIssue(
                                    f"{stop_path}.position", "must be between zero and one"
                                )
                            )
                        if (
                            not isinstance(stop.color, (tuple, list))
                            or len(stop.color) != 4
                            or not all(_finite_number(c) and 0 <= c <= 1 for c in stop.color)
                        ):
                            issues.append(
                                ValidationIssue(
                                    f"{stop_path}.color", "must contain four normalized channels"
                                )
                            )
                    positions = [
                        float(s.position)
                        for s in stops
                        if isinstance(s, ColorStop) and _finite_number(s.position)
                    ]
                    if len(positions) != len(set(positions)):
                        issues.append(
                            ValidationIssue(f"{ramp_path}.stops", "stop positions must be unique")
                        )
                if previous_type not in {None, "scalar"}:
                    issues.append(
                        ValidationIssue(ramp_path, "color ramps require scalar source output")
                    )
                all_instances.extend([layer.source, *layer_transforms])
                final_type = previous_type
                if output.value_type == "scalar" and (
                    final_type != "scalar" or layer.color_ramp is not None
                ):
                    issues.append(
                        ValidationIssue(
                            path, "scalar outputs require scalar layers without color ramps"
                        )
                    )
                elif output.value_type == "normal" and final_type != "rgba":
                    issues.append(
                        ValidationIssue(
                            path, "normal outputs require RGBA layer output; use Height to Normal"
                        )
                    )

    graph: dict[str, set[str]] = {}
    instance_ids: set[str] = set()
    for control_id, control in control_fields.items():
        path = f"control_fields.{control_id}"
        if not isinstance(control_id, str) or not control_id:
            issues.append(ValidationIssue("control_fields", "keys must be non-empty strings"))
        if not isinstance(control, ControlFieldRecipe):
            issues.append(ValidationIssue(path, "must be a ControlFieldRecipe"))
            continue
        control_type = _validate_instance(
            control.source,
            f"{path}.source",
            OperationType.GENERATOR,
            registry,
            control_ids,
            issues,
        )
        dependencies: set[str] = set()
        if not isinstance(control.transforms, list):
            issues.append(ValidationIssue(f"{path}.transforms", "must be a list"))
            control_transforms = []
        else:
            control_transforms = control.transforms
        nested = [control.source, *control_transforms]
        if any(
            isinstance(item, OperationInstance) and item.operation_id in OUTPUT_REFERENCE_OPERATIONS
            for item in nested
        ):
            issues.append(
                ValidationIssue(
                    path,
                    "material output references are not supported inside Control Fields",
                )
            )
        for binding in (binding for item in nested for binding in _instance_bindings(item)):
            if isinstance(binding.source_id, str):
                dependencies.add(binding.source_id)
        graph[control_id] = dependencies
        for index, item in enumerate(control_transforms):
            item_path = f"{path}.transforms[{index}]"
            current_type = _validate_instance(
                item, item_path, OperationType.TRANSFORM, registry, control_ids, issues
            )
            if isinstance(item, OperationInstance):
                try:
                    definition = registry.get(item.operation_id)
                except (KeyError, TypeError):
                    definition = None
                if definition is not None and not accepts_input(definition, control_type):
                    issues.append(
                        ValidationIssue(item_path, "cannot accept the preceding control field")
                    )
            if isinstance(item, OperationInstance) and item.enabled:
                control_type = current_type
        if control_type not in {None, "scalar"}:
            issues.append(ValidationIssue(path, "control fields must produce scalar output"))
        if control.mapping is not None:
            if not isinstance(control.mapping, ControlFieldMapping):
                issues.append(ValidationIssue(f"{path}.mapping", "must be a ControlFieldMapping"))
            else:
                _validate_mapping(control.mapping, f"{path}.mapping", issues)
                for bound in (control.mapping.output_min, control.mapping.output_max):
                    if _finite_number(bound) and not 0.0 <= bound <= 1.0:
                        issues.append(
                            ValidationIssue(
                                f"{path}.mapping", "control field mapping bounds must be normalized"
                            )
                        )
        all_instances.extend(nested)

    for item in all_instances:
        if isinstance(item, OperationInstance):
            if not isinstance(item.instance_id, str) or not item.instance_id:
                issues.append(ValidationIssue("instance_id", "must be a non-empty string"))
            elif item.instance_id in instance_ids:
                issues.append(
                    ValidationIssue(
                        "instance_id", f"duplicate operation instance id: {item.instance_id}"
                    )
                )
            else:
                instance_ids.add(item.instance_id)
        for binding in _instance_bindings(item):
            if not isinstance(binding.source_id, str) or binding.source_id not in control_ids:
                issues.append(
                    ValidationIssue(
                        "control_fields",
                        f"binding references unknown control field {binding.source_id!r}",
                    )
                )

    output_graph: dict[str, set[str]] = {
        output.output_id: set()
        for output in outputs
        if isinstance(output, MaterialOutputRecipe) and isinstance(output.output_id, str)
    }
    for output in outputs:
        if not isinstance(output, MaterialOutputRecipe) or output.output_id not in output_graph:
            continue
        for layer in output.layers if isinstance(output.layers, list) else []:
            if not isinstance(layer, LayerRecipe):
                continue
            for instance in [
                layer.source,
                *(layer.transforms if isinstance(layer.transforms, list) else []),
            ]:
                if not isinstance(instance, OperationInstance):
                    continue
                if instance.operation_id in OUTPUT_REFERENCE_OPERATIONS:
                    target = next(iter_output_references(instance), None)
                    if target not in output_graph:
                        issues.append(
                            ValidationIssue(
                                f"outputs.{output.output_id}.{layer.name}",
                                f"references missing output {target!r}",
                            )
                        )
                    else:
                        output_graph[output.output_id].add(target)
                        if instance.operation_id == "generator.output_scalar":
                            target_recipe = next(
                                (
                                    item
                                    for item in outputs
                                    if isinstance(item, MaterialOutputRecipe)
                                    and item.output_id == target
                                ),
                                None,
                            )
                            mode = (
                                instance.parameters.get("mode", "Direct")
                                if isinstance(instance.parameters, dict)
                                else "Direct"
                            )
                            if target_recipe is not None:
                                if mode == "Direct" and target_recipe.value_type != "scalar":
                                    target_type = target_recipe.value_type.title()
                                    issues.append(
                                        ValidationIssue(
                                            f"outputs.{output.output_id}.{layer.name}",
                                            "Direct mode requires a scalar target; "
                                            f"is {target_type}.",
                                        )
                                    )
                                elif mode != "Direct" and target_recipe.value_type == "scalar":
                                    issues.append(
                                        ValidationIssue(
                                            f"outputs.{output.output_id}.{layer.name}",
                                            f"{mode} extraction requires a color or normal target.",
                                        )
                                    )
    visiting_outputs: list[str] = []
    visited_outputs: set[str] = set()

    def visit_output(output_id: str) -> None:
        if output_id in visiting_outputs:
            cycle = visiting_outputs[visiting_outputs.index(output_id) :] + [output_id]
            labels = {
                item.output_id: item.name
                for item in outputs
                if isinstance(item, MaterialOutputRecipe)
            }
            issues.append(
                ValidationIssue(
                    "outputs",
                    "Output dependency cycle: "
                    + " → ".join(labels.get(item, item) for item in cycle),
                )
            )
            return
        if output_id in visited_outputs:
            return
        visiting_outputs.append(output_id)
        for dependency in output_graph.get(output_id, ()):
            visit_output(dependency)
        visiting_outputs.pop()
        visited_outputs.add(output_id)

    for output_id in output_graph:
        visit_output(output_id)

    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(control_id: str) -> None:
        if control_id in visiting:
            issues.append(
                ValidationIssue(f"control_fields.{control_id}", "cyclic control-field reference")
            )
            return
        if control_id in visited:
            return
        visiting.add(control_id)
        for dependency in graph.get(control_id, ()):
            if dependency in graph:
                visit(dependency)
        visiting.remove(control_id)
        visited.add(control_id)

    for control_id in graph:
        visit(control_id)
    return issues


def ensure_valid_recipe(
    recipe: ProjectRecipe,
    registry: OperationDefinitionSet = REGISTRY,
) -> None:
    issues = validate_recipe(recipe, registry)
    if issues:
        raise ValidationError(issues)


def ensure_true(value: bool, path: str, message: str) -> None:
    if value is not True:
        raise ValidationError([ValidationIssue(path, message)])


def ensure_allowed(value: Any, *, allowed: tuple[Any, ...], path: str, message: str) -> None:
    if value not in allowed:
        raise ValidationError([ValidationIssue(path, message)])
