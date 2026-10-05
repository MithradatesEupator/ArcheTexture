from __future__ import annotations

import numpy as np

from archetexture.core.control_fields import ControlFieldEvaluator
from archetexture.core.fields import ScalarField, as_scalar_field, ensure_normalized_scalar
from archetexture.core.recipe import ControlFieldRecipe, OperationInstance, ProjectRecipe
from archetexture.core.registry import REGISTRY


def _resolve_parameter(value: object, *, width: int, height: int, seed: int) -> object:
    return value


def _evaluate_instance(
    instance: OperationInstance,
    *,
    width: int,
    height: int,
    seed: int,
) -> ScalarField:
    definition = REGISTRY.get(instance.operation_id)
    params = instance.parameters
    if definition.identifier == "generator.constant":
        value = float(params.get("value", definition.parameter_specs[0].default))
        return np.full((height, width), value, dtype=np.float32)
    if definition.identifier == "generator.white_noise":
        noise_seed = int(params.get("seed", 0)) if params.get("seed") is not None else 0
        rng = np.random.default_rng(seed + noise_seed)
        return rng.random((height, width), dtype=np.float32)
    if definition.identifier == "generator.linear_gradient":
        angle = float(params.get("angle", 0.0))
        y, x = np.mgrid[0:height, 0:width]
        nx = x / max(width - 1, 1)
        ny = y / max(height - 1, 1)
        theta = np.deg2rad(angle)
        v = nx * np.cos(theta) + ny * np.sin(theta)
        return ensure_normalized_scalar((v - v.min()) / max(v.max() - v.min(), 1e-6))
    if definition.identifier == "generator.radial_gradient":
        y, x = np.mgrid[0:height, 0:width]
        cx = 0.5
        cy = 0.5
        dist = np.sqrt((x / max(width - 1, 1) - cx) ** 2 + (y / max(height - 1, 1) - cy) ** 2)
        dist = 1.0 - np.clip(dist, 0.0, 1.0)
        return ensure_normalized_scalar(dist)
    if definition.identifier == "transform.invert":
        source = params.get("_input", np.zeros((height, width), dtype=np.float32))
        return 1.0 - as_scalar_field(source)
    if definition.identifier == "transform.threshold":
        threshold = float(params.get("threshold", 0.5))
        source = params.get("_input", np.zeros((height, width), dtype=np.float32))
        src = as_scalar_field(source)
        return (src >= threshold).astype(np.float32)
    if definition.identifier == "transform.quantize":
        levels = max(2, int(params.get("levels", 8)))
        source = params.get("_input", np.zeros((height, width), dtype=np.float32))
        src = as_scalar_field(source)
        return np.round(src * levels) / levels
    raise NotImplementedError(
        f"Operation {definition.identifier} not implemented in pipeline evaluator"
    )


def evaluate_control_field(control: ControlFieldRecipe, *, width: int, height: int) -> ScalarField:
    field = _evaluate_instance(control.source, width=width, height=height, seed=0)
    for item in control.transforms:
        field = _evaluate_instance(item, width=width, height=height, seed=0)
    if control.mapping is not None:
        return ControlFieldEvaluator.evaluate(control.mapping, field, width=width, height=height)
    return ensure_normalized_scalar(field)


def evaluate_recipe(
    recipe: ProjectRecipe,
    *,
    width: int | None = None,
    height: int | None = None,
) -> ScalarField:
    w = int(width or recipe.width)
    h = int(height or recipe.height)
    if recipe.source is None:
        return np.zeros((h, w), dtype=np.float32)
    field = _evaluate_instance(recipe.source, width=w, height=h, seed=recipe.seed)
    for transform in recipe.transforms:
        param_values = dict(transform.parameters)
        if transform.enabled is False:
            continue
        param_values["_input"] = field
        transform = OperationInstance(
            instance_id=transform.instance_id,
            operation_id=transform.operation_id,
            operation_version=transform.operation_version,
            enabled=transform.enabled,
            parameters=param_values,
            influence=transform.influence,
        )
        transformed = _evaluate_instance(transform, width=w, height=h, seed=recipe.seed)
        influence = transform.influence
        if isinstance(influence, (int, float)):
            field = (1.0 - float(influence)) * field + float(influence) * transformed
        else:
            field = field  # control field modulation is evaluated in a future-compatible path
    return ensure_normalized_scalar(field)
