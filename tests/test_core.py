from __future__ import annotations

import json
import subprocess
import sys
import threading

import numpy as np
import pytest

from archetexture.color.ramp import ColorRamp, ColorStop
from archetexture.core.defaults import default_recipe
from archetexture.core.document import DocumentController
from archetexture.core.operations import (
    OperationDefinition,
    OperationDefinitionSet,
    OperationType,
    Seamlessness,
)
from archetexture.core.parameters import (
    ControlFieldBinding,
    ControlFieldMapping,
    ParameterSpec,
    ParameterType,
)
from archetexture.core.pipeline import evaluate_recipe
from archetexture.core.recipe import ControlFieldRecipe, OperationInstance, ProjectRecipe
from archetexture.core.registry import REGISTRY, register_builtin_operations
from archetexture.core.serialization import (
    ProjectFormatError,
    UnsupportedSchemaVersion,
    load_project,
    save_project,
)
from archetexture.core.validation import ValidationError, ensure_valid_recipe, validate_recipe
from archetexture.render.coordinator import RenderCoordinator, RenderOutcome
from archetexture.render.engine import RenderEngine, RenderResult


def operation(
    operation_id: str,
    instance_id: str,
    *,
    parameters: dict | None = None,
    enabled: bool = True,
    influence=1.0,
) -> OperationInstance:
    return OperationInstance(
        instance_id,
        operation_id,
        1,
        enabled=enabled,
        parameters=parameters or {},
        influence=influence,
    )


def constant_recipe(value: float = 0.25, *, width: int = 32, height: int = 24) -> ProjectRecipe:
    return ProjectRecipe(
        width=width,
        height=height,
        seed=7,
        source=operation("generator.constant", "source", parameters={"value": value}),
    )


def test_default_recipe_is_deterministic_and_has_useful_color_output():
    recipe = default_recipe()
    first = RenderEngine().render(recipe)
    second = RenderEngine().render(recipe)
    assert first.scalar_field.dtype == np.float32
    assert first.scalar_field.shape == (512, 512)
    assert first.rgba_field.shape == (512, 512, 4)
    assert np.array_equal(first.scalar_field, second.scalar_field)
    assert np.array_equal(first.rgba_field, second.rgba_field)
    assert np.unique(first.scalar_field).size > 100


def test_generator_parameters_are_effective_and_noise_is_deterministic():
    constant = constant_recipe(0.37)
    constant_field = evaluate_recipe(constant)
    assert np.all(constant_field == np.float32(0.37))

    noise = ProjectRecipe(
        width=32,
        height=24,
        seed=9,
        source=operation("generator.white_noise", "source", parameters={"seed": 123}),
    )
    assert np.array_equal(evaluate_recipe(noise), evaluate_recipe(noise))
    noise.source.parameters["seed"] = 124
    assert not np.array_equal(
        evaluate_recipe(noise),
        evaluate_recipe(
            noise.__class__(
                width=32,
                height=24,
                seed=9,
                source=operation("generator.white_noise", "source", parameters={"seed": 123}),
            )
        ),
    )


def test_gradient_angle_and_radial_radius_change_the_field():
    horizontal = ProjectRecipe(
        width=40,
        height=32,
        source=operation("generator.linear_gradient", "source", parameters={"angle": 0.0}),
    )
    vertical = ProjectRecipe(
        width=40,
        height=32,
        source=operation("generator.linear_gradient", "source", parameters={"angle": 90.0}),
    )
    horizontal_field = evaluate_recipe(horizontal)
    vertical_field = evaluate_recipe(vertical)
    assert np.allclose(horizontal_field[0], horizontal_field[-1])
    assert np.allclose(vertical_field[:, 0], vertical_field[:, -1], atol=1e-6)
    assert not np.allclose(horizontal_field, vertical_field)

    radial_small = ProjectRecipe(
        width=65,
        height=65,
        source=operation("generator.radial_gradient", "source", parameters={"radius": 0.25}),
    )
    radial_large = ProjectRecipe(
        width=65,
        height=65,
        source=operation("generator.radial_gradient", "source", parameters={"radius": 0.8}),
    )
    small = evaluate_recipe(radial_small)
    large = evaluate_recipe(radial_large)
    assert small[32, 32] == large[32, 32] == 1.0
    assert small[32, 48] < large[32, 48]


def test_transforms_consume_input_and_honor_enablement_and_influence():
    chained = constant_recipe(0.2)
    chained.transforms = [
        operation("transform.invert", "chain-invert"),
        operation("transform.threshold", "chain-threshold", parameters={"threshold": 0.5}),
    ]
    assert np.all(evaluate_recipe(chained) == 1.0)

    recipe = constant_recipe(0.2)
    recipe.transforms = [operation("transform.invert", "invert", influence=0.25)]
    blended = evaluate_recipe(recipe)
    assert np.allclose(blended, 0.35)

    recipe.transforms[0].enabled = False
    assert np.allclose(evaluate_recipe(recipe), 0.2)
    recipe.transforms[0].enabled = True
    recipe.transforms[0].influence = 1.0
    assert np.allclose(evaluate_recipe(recipe), 0.8)

    thresholded = constant_recipe(0.6)
    thresholded.transforms = [
        operation("transform.threshold", "threshold", parameters={"threshold": 0.5})
    ]
    assert np.all(evaluate_recipe(thresholded) == 1.0)
    thresholded.transforms[0].parameters["threshold"] = 0.7
    assert np.all(evaluate_recipe(thresholded) == 0.0)

    quantized = constant_recipe(0.6)
    quantized.transforms = [operation("transform.quantize", "quantize", parameters={"levels": 4})]
    result = evaluate_recipe(quantized)
    assert np.all(result == np.float32(2.0 / 3.0))


def test_newly_registered_transform_runs_without_pipeline_changes():
    registry = OperationDefinitionSet()
    register_builtin_operations(registry)

    def half(source, _parameters, _width, _height, _seed):
        return source * np.float32(0.5)

    registry.register(
        OperationDefinition(
            identifier="test.transform.half",
            version=1,
            name="Half",
            category="Transform",
            description="Test transform",
            operation_type=OperationType.TRANSFORM,
            input_types=("scalar",),
            output_type="scalar",
            seamlessness=Seamlessness.PRESERVES,
            implementation=half,
        )
    )
    recipe = constant_recipe(0.8)
    recipe.transforms = [operation("test.transform.half", "half")]
    assert np.allclose(evaluate_recipe(recipe, registry=registry), 0.4)


def test_validation_rejects_incompatible_declared_field_types():
    registry = OperationDefinitionSet()
    register_builtin_operations(registry)

    def rgba_source(_input, _parameters, width, height, _seed):
        return np.zeros((height, width, 4), dtype=np.float32)

    registry.register(
        OperationDefinition(
            identifier="test.generator.rgba",
            version=1,
            name="RGBA Source",
            category="Generator",
            description="Produces RGBA data",
            operation_type=OperationType.GENERATOR,
            input_types=(),
            output_type="rgba",
            seamlessness=Seamlessness.UNKNOWN,
            implementation=rgba_source,
        )
    )
    recipe = ProjectRecipe(
        source=operation("test.generator.rgba", "rgba-source"),
        transforms=[operation("transform.invert", "scalar-invert")],
    )
    issues = validate_recipe(recipe, registry)
    assert any("cannot accept the preceding rgba field type" in issue.message for issue in issues)


def test_enum_color_and_position_metadata_validation_and_serialization(tmp_path):
    def source(_input, _parameters, width, height, _seed):
        return np.full((height, width), 0.4, dtype=np.float32)

    definition = OperationDefinition(
        identifier="test.generator.structured",
        version=1,
        name="Structured",
        category="Generator",
        description="Exercises structured parameters",
        operation_type=OperationType.GENERATOR,
        input_types=(),
        output_type="scalar",
        parameter_specs=(
            ParameterSpec(
                "mode",
                "Mode",
                ParameterType.ENUM,
                default="smooth",
                options=("smooth", "sharp"),
                allows_modulation=False,
            ),
            ParameterSpec(
                "color",
                "Color",
                ParameterType.COLOR,
                default=(0.1, 0.2, 0.3, 1.0),
                allows_modulation=False,
            ),
            ParameterSpec(
                "position",
                "Position",
                ParameterType.POSITION_2D,
                default=(0.25, 0.75),
                allows_modulation=False,
            ),
        ),
        implementation=source,
    )
    REGISTRY.register(definition)
    try:
        recipe = ProjectRecipe(
            width=8,
            height=6,
            source=operation(
                definition.identifier,
                "structured-source",
                parameters={
                    "mode": "sharp",
                    "color": (0.4, 0.5, 0.6, 1.0),
                    "position": (0.2, 0.8),
                },
            ),
        )
        assert validate_recipe(recipe) == []
        path = tmp_path / "structured.archetexture"
        save_project(recipe, path)
        loaded = load_project(path)
        assert loaded.source.parameters["position"] == (0.2, 0.8)
        assert isinstance(loaded.source.parameters["position"], tuple)

        recipe.source.parameters["mode"] = "invalid"
        recipe.source.parameters["color"] = (2.0, 0.0, 0.0, 1.0)
        issues = validate_recipe(recipe)
        assert any(issue.path == "source.parameters.mode" for issue in issues)
        assert any(issue.path == "source.parameters.color" for issue in issues)
    finally:
        REGISTRY.unregister(definition.identifier)


def _populated_recipe() -> ProjectRecipe:
    recipe = ProjectRecipe(
        width=32,
        height=20,
        seed=44,
        source=operation("generator.linear_gradient", "source", parameters={"angle": 17.0}),
        transforms=[
            operation(
                "transform.threshold",
                "threshold",
                parameters={
                    "threshold": ControlFieldBinding(
                        "mask",
                        ControlFieldMapping(0.2, 0.8, invert=True, curve="smoothstep"),
                    )
                },
                influence=0.75,
            ),
            operation("transform.invert", "invert", enabled=False),
        ],
        color_ramp=ColorRamp(
            (
                ColorStop(0.0, (0.02, 0.04, 0.12, 1.0)),
                ColorStop(0.5, (0.2, 0.5, 0.7, 0.8)),
                ColorStop(1.0, (0.9, 0.7, 0.2, 1.0)),
            )
        ),
        control_fields={
            "mask": ControlFieldRecipe(
                source=operation("generator.white_noise", "mask-source", parameters={"seed": 5}),
                transforms=[operation("transform.invert", "mask-invert")],
                mapping=ControlFieldMapping(0.0, 1.0, curve="smoothstep"),
            )
        },
    )
    return recipe


def test_populated_json_round_trip_restores_domain_types_and_render():
    recipe = _populated_recipe()
    expected = RenderEngine().render(recipe)
    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "populated.archetexture"
        save_project(recipe, path)
        document = json.loads(path.read_text(encoding="utf-8"))
        assert document["source"]["operation_id"] == "generator.linear_gradient"
        assert (
            document["transforms"][0]["parameters"]["threshold"]["$type"] == "control_field_binding"
        )
        loaded = load_project(path)
    assert loaded == recipe
    assert isinstance(loaded.source, OperationInstance)
    assert isinstance(loaded.transforms[0], OperationInstance)
    assert isinstance(loaded.transforms[0].parameters["threshold"], ControlFieldBinding)
    assert isinstance(loaded.control_fields["mask"], ControlFieldRecipe)
    actual = RenderEngine().render(loaded)
    assert np.array_equal(expected.scalar_field, actual.scalar_field)
    assert np.array_equal(expected.rgba_field, actual.rgba_field)


def test_control_field_transforms_chain_and_modulate_numeric_parameters():
    recipe = ProjectRecipe(
        width=16,
        height=8,
        source=operation("generator.constant", "source", parameters={"value": 0.5}),
        transforms=[
            operation(
                "transform.threshold",
                "threshold",
                parameters={
                    "threshold": ControlFieldBinding(
                        "mask", ControlFieldMapping(0.2, 0.8, curve="linear")
                    )
                },
            )
        ],
        control_fields={
            "mask": ControlFieldRecipe(
                source=operation(
                    "generator.linear_gradient", "mask-source", parameters={"angle": 0.0}
                ),
                transforms=[
                    operation("transform.invert", "mask-invert-a"),
                    operation("transform.invert", "mask-invert-b"),
                ],
            )
        },
    )
    result = evaluate_recipe(recipe)
    assert np.all(result[:, 0] == 1.0)
    assert np.all(result[:, -1] == 0.0)


def test_control_field_cycles_are_reported_as_validation_issues():
    recipe = constant_recipe()
    recipe.control_fields = {
        "loop": ControlFieldRecipe(
            source=operation(
                "generator.constant",
                "loop-source",
                parameters={"value": ControlFieldBinding("loop")},
            )
        )
    }
    issues = validate_recipe(recipe)
    assert any("cyclic" in issue.message for issue in issues)
    with pytest.raises(ValidationError):
        ensure_valid_recipe(recipe)

    missing = constant_recipe()
    missing.transforms = [
        operation(
            "transform.threshold",
            "missing-control-binding",
            parameters={"threshold": ControlFieldBinding("missing")},
        )
    ]
    assert any("unknown control field" in issue.message for issue in validate_recipe(missing))


def test_control_field_can_drive_transform_influence():
    recipe = constant_recipe(0.2, width=16, height=8)
    recipe.transforms = [
        operation(
            "transform.invert",
            "influence-invert",
            influence=ControlFieldBinding("mask"),
        )
    ]
    recipe.control_fields = {
        "mask": ControlFieldRecipe(
            source=operation(
                "generator.linear_gradient",
                "influence-mask",
                parameters={"angle": 0.0},
            )
        )
    }
    result = evaluate_recipe(recipe)
    assert np.allclose(result[:, 0], 0.2)
    assert np.allclose(result[:, -1], 0.8)


def test_color_ramp_is_vectorized_and_keeps_float_scalar_field():
    ramp = ColorRamp(
        (
            ColorStop(0.0, (0.0, 0.0, 0.0, 0.25)),
            ColorStop(1.0, (1.0, 0.5, 0.25, 1.0)),
        )
    )
    values = np.array([[0.0, 0.5, 1.0]], dtype=np.float32)
    rgba = ramp.apply(values)
    assert rgba.shape == (1, 3, 4)
    assert rgba.dtype == np.float32
    assert np.allclose(rgba[0, 1], (0.5, 0.25, 0.125, 0.625))
    recipe = constant_recipe(0.4)
    recipe.color_ramp = ramp
    rendered = RenderEngine().render(recipe)
    assert rendered.scalar_field.shape == (24, 32)
    assert np.allclose(rendered.rgba_field[0, 0], ramp.sample(0.4))


def test_document_history_snapshots_branching_and_dirty_savepoint(tmp_path):
    document = DocumentController(constant_recipe(0.1))
    document.edit(lambda recipe: recipe.source.parameters.__setitem__("value", 0.2))
    document.edit(lambda recipe: setattr(recipe, "width", 48))
    assert document.dirty
    document.undo()
    assert document.recipe.source.parameters["value"] == 0.2
    document.undo()
    assert document.recipe.source.parameters["value"] == 0.1
    document.redo()
    assert document.recipe.source.parameters["value"] == 0.2
    document.edit(lambda recipe: recipe.source.parameters.__setitem__("value", 0.3))
    assert not document.can_redo

    detached = document.recipe
    detached.source.parameters["value"] = 0.9
    assert document.recipe.source.parameters["value"] == 0.3
    path = tmp_path / "saved.archetexture"
    document.save(path)
    assert not document.dirty
    document.edit(lambda recipe: recipe.source.parameters.__setitem__("value", 0.4))
    assert document.dirty
    document.undo()
    assert not document.dirty
    reopened = DocumentController(constant_recipe(0.8))
    reopened.open_project(path)
    assert reopened.recipe == document.recipe
    assert not reopened.dirty


def test_validation_reports_dimensions_versions_parameters_and_unknown_operations():
    recipe = constant_recipe()
    recipe.width = 0
    recipe.source.parameters["value"] = 1.5
    recipe.transforms = [operation("transform.invert", "invert")]
    recipe.transforms[0].operation_version = 8
    issues = validate_recipe(recipe)
    paths = {issue.path for issue in issues}
    assert "width" in paths
    assert "source.parameters.value" in paths
    assert "transforms[0].operation_version" in paths

    recipe.source.operation_id = "generator.missing"
    assert any("unknown operation" in issue.message for issue in validate_recipe(recipe))


def test_invalid_transform_chain_and_future_schema_are_rejected(tmp_path):
    recipe = constant_recipe()
    recipe.transforms = [operation("generator.constant", "wrong-kind")]
    assert any("must be a transform" in issue.message for issue in validate_recipe(recipe))
    future = tmp_path / "future.archetexture"
    future.write_text('{"schema_version": 2}', encoding="utf-8")
    with pytest.raises(UnsupportedSchemaVersion):
        load_project(future)
    malformed = tmp_path / "broken.archetexture"
    malformed.write_text("{broken", encoding="utf-8")
    with pytest.raises(ProjectFormatError):
        load_project(malformed)


def test_history_push_copies_mutable_recipes():
    from archetexture.core.history import HistoryManager

    history = HistoryManager()
    recipe = constant_recipe(0.1)
    history.push(recipe)
    recipe.source.parameters["value"] = 0.8
    history.push(recipe)
    restored = history.undo()
    assert restored.source.parameters["value"] == 0.1


class _GateEngine:
    def __init__(self):
        self.started = threading.Event()
        self.release = threading.Event()
        self.calls = 0
        self.thread_name = ""

    def render(self, recipe, *, width, height):
        self.calls += 1
        self.thread_name = threading.current_thread().name
        if self.calls == 1:
            self.started.set()
            assert self.release.wait(3)
        rgba = np.zeros((height, width, 4), dtype=np.float32)
        rgba[..., 0] = recipe.seed / 10.0
        rgba[..., 3] = 1.0
        return RenderResult(None, rgba)


def test_render_coordinator_runs_in_background_and_only_publishes_newest():
    engine = _GateEngine()
    completed: list[RenderOutcome] = []
    event = threading.Event()

    def on_complete(outcome):
        completed.append(outcome)
        event.set()

    coordinator = RenderCoordinator(engine=engine, on_complete=on_complete)
    first_recipe = constant_recipe()
    first_recipe.seed = 1
    first = coordinator.request(first_recipe, width=4, height=3)
    assert engine.started.wait(2)
    second_recipe = constant_recipe()
    second_recipe.seed = 2
    second = coordinator.request(second_recipe, width=4, height=3)
    third_recipe = constant_recipe()
    third_recipe.seed = 3
    third = coordinator.request(third_recipe, width=4, height=3)
    third_recipe.seed = 9
    engine.release.set()
    try:
        assert event.wait(3)
        assert first.request_id < second.request_id < third.request_id
        assert [outcome.request_id for outcome in completed] == [third.request_id]
        assert completed[0].result.rgba_field[0, 0, 0] == pytest.approx(0.3)
        assert engine.thread_name.startswith("archetexture-render")
        assert engine.calls == 2
    finally:
        coordinator.close(wait=True)


def test_render_coordinator_delivers_failures_without_raising_on_caller():
    class BrokenEngine:
        def render(self, *_args, **_kwargs):
            raise RuntimeError("render failed")

    event = threading.Event()
    outcomes = []
    coordinator = RenderCoordinator(
        engine=BrokenEngine(),
        on_complete=lambda outcome: (outcomes.append(outcome), event.set()),
    )
    coordinator.request(constant_recipe(), width=8, height=8)
    try:
        assert event.wait(2)
        assert isinstance(outcomes[0].error, RuntimeError)
        assert outcomes[0].result is None
    finally:
        coordinator.close(wait=True)


def test_production_entrypoint_does_not_force_offscreen_platform():
    import os

    environment = os.environ.copy()
    environment.pop("QT_QPA_PLATFORM", None)
    subprocess.run(
        [
            sys.executable,
            "-c",
            "import os; import archetexture.__main__; assert 'QT_QPA_PLATFORM' not in os.environ",
        ],
        check=True,
        env=environment,
        cwd=__import__("pathlib").Path(__file__).parents[1],
    )
