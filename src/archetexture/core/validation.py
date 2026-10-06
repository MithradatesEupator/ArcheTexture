from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from archetexture.color.ramp import ColorRamp, ColorStop
from archetexture.core.operations import OperationDefinitionSet, OperationType
from archetexture.core.parameters import (
    ControlFieldBinding,
    ControlFieldMapping,
    ParameterSpec,
    ParameterType,
)
from archetexture.core.recipe import (
    ControlFieldRecipe,
    LayerRecipe,
    OperationInstance,
    ProjectRecipe,
)
from archetexture.core.registry import REGISTRY


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
    if isinstance(value, ControlFieldBinding):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from _walk_bindings(item)
    elif isinstance(value, (tuple, list)):
        for item in value:
            yield from _walk_bindings(item)


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
    if not valid:
        issues.append(ValidationIssue(path, f"must have type {kind.value}"))
        return

    if kind not in {
        ParameterType.BOOLEAN,
        ParameterType.ENUM,
        ParameterType.COLOR,
        ParameterType.POSITION_2D,
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
    elif recipe.schema_version != 2:
        issues.append(ValidationIssue("schema_version", "supported schema version is 2"))
    for name in ("width", "height"):
        value = getattr(recipe, name)
        if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
            issues.append(ValidationIssue(name, "must be a positive integer"))
    if not isinstance(recipe.seed, int) or isinstance(recipe.seed, bool) or recipe.seed < 0:
        issues.append(ValidationIssue("seed", "must be a non-negative integer"))
    if not isinstance(recipe.layers, list):
        issues.append(ValidationIssue("layers", "must be a list"))
        layers = []
    else:
        layers = recipe.layers
    if not layers:
        issues.append(ValidationIssue("layers", "at least one layer is required"))
    if not isinstance(recipe.control_fields, dict):
        issues.append(ValidationIssue("control_fields", "must be an object"))
        control_fields = {}
    else:
        control_fields = recipe.control_fields
    control_ids = set(control_fields)

    layer_ids: set[str] = set()
    all_instances: list[OperationInstance | None] = []
    for layer_index, layer in enumerate(layers):
        path = f"layers[{layer_index}]"
        if not isinstance(layer, LayerRecipe):
            issues.append(ValidationIssue(path, "must be a LayerRecipe"))
            continue
        if not isinstance(layer.layer_id, str) or not layer.layer_id:
            issues.append(ValidationIssue(f"{path}.layer_id", "must be a non-empty string"))
        elif layer.layer_id in layer_ids:
            issues.append(ValidationIssue(f"{path}.layer_id", "layer identifiers must be unique"))
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
                if definition is not None and previous_type not in definition.input_types:
                    issues.append(
                        ValidationIssue(
                            item_path,
                            f"cannot accept the preceding {previous_type or 'unknown'} field type",
                        )
                    )
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
                            ValidationIssue(f"{stop_path}.position", "must be between zero and one")
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
                if definition is not None and control_type not in definition.input_types:
                    issues.append(
                        ValidationIssue(item_path, "cannot accept the preceding control field")
                    )
            control_type = current_type
        if control_type not in {None, "scalar"}:
            issues.append(ValidationIssue(path, "control fields must produce scalar output"))
        if control.mapping is not None:
            if not isinstance(control.mapping, ControlFieldMapping):
                issues.append(ValidationIssue(f"{path}.mapping", "must be a ControlFieldMapping"))
            else:
                _validate_mapping(control.mapping, f"{path}.mapping", issues)
                for bound in control.mapping.normalized_range():
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
