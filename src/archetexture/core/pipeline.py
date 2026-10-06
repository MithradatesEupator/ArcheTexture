from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np

from archetexture.core.control_fields import ControlFieldEvaluator
from archetexture.core.fields import (
    RGBAField,
    ScalarField,
    ensure_normalized_scalar,
    validate_rgba_field,
    validate_scalar_field,
)
from archetexture.core.operations import OperationDefinitionSet, OperationType
from archetexture.core.parameters import (
    ControlFieldBinding,
    ParameterSpec,
    ParameterType,
)
from archetexture.core.recipe import OperationInstance, ProjectRecipe
from archetexture.core.registry import REGISTRY
from archetexture.core.validation import ensure_valid_recipe

Field = ScalarField | RGBAField


@dataclass
class _Evaluation:
    recipe: ProjectRecipe
    width: int
    height: int
    registry: OperationDefinitionSet
    control_cache: dict[str, ScalarField] = field(default_factory=dict)
    control_stack: set[str] = field(default_factory=set)

    def resolve_binding(self, binding: ControlFieldBinding) -> ScalarField:
        try:
            raw = self.control_field(binding.source_id)
        except KeyError as exc:
            raise ValueError(f"Unknown control field: {binding.source_id}") from exc
        return ControlFieldEvaluator.evaluate(binding, raw, width=self.width, height=self.height)

    def control_field(self, identifier: str) -> ScalarField:
        if identifier in self.control_cache:
            return self.control_cache[identifier]
        if identifier in self.control_stack:
            raise ValueError(f"Cyclic control-field reference: {identifier}")
        control = self.recipe.control_fields.get(identifier)
        if control is None:
            raise KeyError(identifier)
        self.control_stack.add(identifier)
        try:
            raw = _evaluate_pipeline(
                control.source,
                control.transforms,
                self,
                self.recipe.seed,
            )
            scalar = validate_scalar_field(raw, name=f"control field {identifier}")
            if control.mapping is not None:
                scalar = ControlFieldEvaluator.map_field(control.mapping, scalar)
            self.control_cache[identifier] = ensure_normalized_scalar(scalar)
            return self.control_cache[identifier]
        finally:
            self.control_stack.remove(identifier)


def _coerce_parameter(
    value: Any,
    spec: ParameterSpec,
    evaluation: _Evaluation,
) -> Any:
    is_modulated = isinstance(value, ControlFieldBinding)
    if is_modulated:
        value = evaluation.resolve_binding(value)
    if spec.type in {
        ParameterType.FLOAT,
        ParameterType.INTEGER,
        ParameterType.SEED,
        ParameterType.ANGLE,
        ParameterType.PERCENT,
    }:
        if is_modulated:
            array = np.asarray(value, dtype=np.float32)
            if spec.type in {ParameterType.INTEGER, ParameterType.SEED}:
                array = np.rint(array)
            if spec.min_value is not None:
                array = np.maximum(array, spec.min_value)
            if spec.max_value is not None:
                array = np.minimum(array, spec.max_value)
            return array.astype(np.float32, copy=False)
        if spec.type in {ParameterType.INTEGER, ParameterType.SEED}:
            return int(value)
        return float(value)
    if spec.type == ParameterType.BOOLEAN:
        return bool(value)
    if spec.type in {ParameterType.COLOR, ParameterType.POSITION_2D}:
        return tuple(value)
    return value


def _run_instance(
    instance: OperationInstance,
    input_field: Field | None,
    evaluation: _Evaluation,
    seed: int,
) -> Field:
    definition = evaluation.registry.get(instance.operation_id)
    if input_field is not None:
        if definition.input_types and "any" not in definition.input_types:
            input_type = "scalar" if input_field.ndim == 2 else "rgba"
            if input_type not in definition.input_types:
                raise ValueError(f"{definition.identifier} cannot accept {input_type} input")
    implementation = definition.implementation
    if implementation is None:
        raise RuntimeError(f"Operation has no implementation: {definition.identifier}")
    raw_parameters = instance.parameters
    parameters = {
        spec.identifier: _coerce_parameter(
            raw_parameters.get(spec.identifier, spec.default), spec, evaluation
        )
        for spec in definition.parameter_specs
    }
    result = np.asarray(
        implementation(input_field, parameters, evaluation.width, evaluation.height, seed),
        dtype=np.float32,
    )
    if definition.output_type == "scalar":
        return ensure_normalized_scalar(validate_scalar_field(result, name=definition.identifier))
    if definition.output_type == "rgba":
        return np.clip(validate_rgba_field(result, name=definition.identifier), 0.0, 1.0).astype(
            np.float32, copy=False
        )
    raise ValueError(f"Unsupported output field type: {definition.output_type}")


def _blend(previous: Field, transformed: Field, influence: float | np.ndarray) -> Field:
    if previous.shape != transformed.shape:
        raise ValueError("Transform output shape does not match its input")
    alpha = np.asarray(influence, dtype=np.float32)
    if previous.ndim == 3 and alpha.ndim == 2:
        alpha = alpha[..., None]
    result = previous * (1.0 - alpha) + transformed * alpha
    if result.ndim == 2:
        return ensure_normalized_scalar(result)
    return np.clip(validate_rgba_field(result), 0.0, 1.0).astype(np.float32, copy=False)


def _evaluate_pipeline(
    source: OperationInstance,
    transforms: list[OperationInstance],
    evaluation: _Evaluation,
    seed: int,
) -> Field:
    field_value = _run_instance(source, None, evaluation, seed)
    for instance in transforms:
        if not instance.enabled:
            continue
        definition = evaluation.registry.get(instance.operation_id)
        if definition.operation_type != OperationType.TRANSFORM:
            raise ValueError(f"Pipeline stage is not a transform: {instance.operation_id}")
        transformed = _run_instance(instance, field_value, evaluation, seed)
        if isinstance(instance.influence, ControlFieldBinding):
            influence_spec = ParameterSpec(
                "influence",
                "Influence",
                ParameterType.PERCENT,
                default=1.0,
                min_value=0.0,
                max_value=1.0,
            )
            influence = _coerce_parameter(instance.influence, influence_spec, evaluation)
        else:
            influence = float(instance.influence)
        field_value = _blend(field_value, transformed, influence)
    return field_value


def evaluate_recipe(
    recipe: ProjectRecipe,
    *,
    width: int | None = None,
    height: int | None = None,
    registry: OperationDefinitionSet = REGISTRY,
) -> Field:
    ensure_valid_recipe(recipe, registry)
    output_width = recipe.width if width is None else width
    output_height = recipe.height if height is None else height
    for name, dimension in (("width", output_width), ("height", output_height)):
        if not isinstance(dimension, int) or isinstance(dimension, bool) or dimension <= 0:
            raise ValueError(f"Render {name} must be a positive integer")
    evaluation = _Evaluation(recipe, output_width, output_height, registry)
    layer = recipe.layers[0]
    return _evaluate_pipeline(layer.source, layer.transforms, evaluation, recipe.seed)


def evaluate_layer(
    recipe: ProjectRecipe,
    layer,
    *,
    width: int | None = None,
    height: int | None = None,
    registry: OperationDefinitionSet = REGISTRY,
) -> Field:
    """Evaluate one layer using the document's shared control-field namespace."""
    ensure_valid_recipe(recipe, registry)
    if layer not in recipe.layers:
        raise ValueError("Layer does not belong to this recipe")
    output_width = recipe.width if width is None else width
    output_height = recipe.height if height is None else height
    for name, dimension in (("width", output_width), ("height", output_height)):
        if not isinstance(dimension, int) or isinstance(dimension, bool) or dimension <= 0:
            raise ValueError(f"Render {name} must be a positive integer")
    evaluation = _Evaluation(recipe, output_width, output_height, registry)
    return _evaluate_pipeline(layer.source, layer.transforms, evaluation, recipe.seed)
