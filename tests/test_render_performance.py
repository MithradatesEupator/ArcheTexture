from __future__ import annotations

import threading

import numpy as np
import pytest
from PIL import Image

from archetexture.color.ramp import ColorRamp, ColorStop
from archetexture.core.assets import AssetReference, RenderContext
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
from archetexture.core.recipe import (
    ControlFieldRecipe,
    LayerRecipe,
    OperationInstance,
    ProjectRecipe,
)
from archetexture.core.registry import REGISTRY
from archetexture.export.image_export import ImageExporter
from archetexture.render.coordinator import RenderCoordinator, RenderOutcome
from archetexture.render.engine import RenderEngine
from archetexture.render.session import LayerResultCache, RenderSession


def op(operation_id: str, identifier: str, **overrides) -> OperationInstance:
    definition = REGISTRY.get(operation_id)
    parameters = {spec.identifier: spec.default for spec in definition.parameter_specs}
    parameters.update(overrides)
    return OperationInstance(identifier, operation_id, definition.version, parameters=parameters)


def recipe(*, width: int = 32, height: int = 24, with_mask: bool = False) -> ProjectRecipe:
    ramp = ColorRamp((ColorStop(0.0, (0.0, 0.05, 0.2, 1.0)), ColorStop(1.0, (0.9, 0.7, 0.2, 1.0))))
    layers = [
        LayerRecipe(
            f"layer-{index}",
            f"Layer {index}",
            op("generator.fractal_noise", f"source-{index}", seed=20 + index, scale=4.0 + index),
            [op("transform.blur", f"blur-{index}", sigma=0.8)],
            color_ramp=ramp,
        )
        for index in range(3)
    ]
    controls = {}
    if with_mask:
        controls["shared"] = ControlFieldRecipe(
            op("generator.fractal_noise", "mask-source", seed=77, scale=3.0),
            [op("transform.blur", "mask-blur", sigma=1.0)],
        )
        layers[0].mask = ControlFieldBinding("shared")
        layers[1].mask = ControlFieldBinding("shared")
    return ProjectRecipe(
        width=width, height=height, seed=19, layers=layers, control_fields=controls
    )


def render_with(
    coordinator: RenderCoordinator, recipe_value: ProjectRecipe, context: RenderContext
):
    event = threading.Event()
    outcomes: list[RenderOutcome] = []
    request = coordinator.request(
        recipe_value,
        width=recipe_value.width,
        height=recipe_value.height,
        render_context=context,
        callback=lambda result: (outcomes.append(result), event.set()),
    )
    assert event.wait(5)
    assert outcomes[0].error is None
    return request, outcomes[0].result


def test_identical_layer_cache_and_uncached_reference_are_pixel_equal():
    project = recipe(with_mask=True)
    engine = RenderEngine()
    cold = engine.render(project)
    executions = engine.session.stats["operation_executions"]
    warm = engine.render(project)
    assert engine.session.stats["operation_executions"] == executions
    assert engine.session.stats["layers"]["hits"] >= len(project.layers)
    reference = engine.render_uncached(project)
    np.testing.assert_array_equal(cold.rgba_field, warm.rgba_field)
    np.testing.assert_array_equal(cold.rgba_field, reference.rgba_field)
    np.testing.assert_array_equal(cold.mask_fields["layer-0"], reference.mask_fields["layer-0"])


def test_opacity_blend_reorder_visibility_and_one_layer_edits_reuse_unrelated_layers():
    project = recipe()
    engine = RenderEngine()
    engine.render(project)
    initial_execs = engine.session.stats["operation_executions"]
    project.layers[0].opacity = 0.4
    project.layers[1].blend_mode = "multiply"
    project.layers.reverse()
    engine.render(project)
    assert engine.session.stats["operation_executions"] == initial_execs
    assert engine.session.stats["layers"]["hits"] == 3

    project.layers[0].source.parameters["scale"] += 0.5
    before = engine.session.stats["operation_executions"]
    engine.render(project)
    assert engine.session.stats["operation_executions"] - before == 2
    assert engine.session.stats["layers"]["hits"] == 5

    # Hiding a layer skips its pipeline; showing it again reuses its immutable output.
    project.layers[0].enabled = False
    before = engine.session.stats["operation_executions"]
    engine.render(project)
    assert engine.session.stats["operation_executions"] == before
    project.layers[0].enabled = True
    engine.render(project)
    assert engine.session.stats["operation_executions"] == before


def test_ramp_transform_mask_and_seed_changes_invalidate_render_dependencies():
    project = recipe(with_mask=True)
    engine = RenderEngine()
    engine.render(project)
    project.layers[0].color_ramp = ColorRamp(
        (
            ColorStop(0.0, (0.0, 0.0, 0.0, 1.0)),
            ColorStop(1.0, (1.0, 1.0, 1.0, 1.0)),
        )
    )
    before = engine.session.stats["operation_executions"]
    engine.render(project)
    assert engine.session.stats["operation_executions"] - before == 2

    project.layers[0].transforms[0].parameters["sigma"] = 1.4
    before = engine.session.stats["operation_executions"]
    engine.render(project)
    assert engine.session.stats["operation_executions"] - before == 2

    project.layers[0].mask = ControlFieldBinding("shared", ControlFieldMapping(invert=True))
    before = engine.session.stats["operation_executions"]
    engine.render(project)
    assert engine.session.stats["operation_executions"] > before

    project.control_fields["shared"].source.parameters["scale"] += 0.4
    before = engine.session.stats["operation_executions"]
    engine.render(project)
    assert engine.session.stats["operation_executions"] > before

    project.seed += 1
    before = engine.session.stats["operation_executions"]
    engine.render(project)
    assert engine.session.stats["operation_executions"] - before >= len(project.layers) * 2


def test_project_relative_asset_cache_persists_and_invalidates_changed_pixels(tmp_path):
    project_path = tmp_path / "project.archetexture"
    image_path = tmp_path / "source.png"
    Image.new("RGBA", (8, 8), (255, 0, 0, 255)).save(image_path)
    image_recipe = ProjectRecipe(
        width=8,
        height=8,
        layers=[
            LayerRecipe(
                "image-layer",
                "Image",
                op(
                    "generator.image",
                    "image-source",
                    asset=AssetReference("source.png", "project_relative"),
                ),
            )
        ],
    )
    session = RenderSession()
    coordinator = RenderCoordinator(engine=RenderEngine(session=session))
    try:
        context = RenderContext(project_path)
        _, first = render_with(coordinator, image_recipe, context)
        _, warm = render_with(coordinator, image_recipe, context)
        assert session.asset_cache.stats["decodes"] == 1
        np.testing.assert_array_equal(first.rgba_field, warm.rgba_field)

        Image.new("RGBA", (8, 8), (0, 255, 0, 255)).save(image_path)
        _, changed = render_with(coordinator, image_recipe, context)
        assert session.asset_cache.stats["decodes"] == 2
        assert not np.array_equal(first.rgba_field, changed.rgba_field)
        fresh = RenderEngine().render(image_recipe, render_context=RenderContext(project_path))
        np.testing.assert_array_equal(changed.rgba_field, fresh.rgba_field)
    finally:
        coordinator.close()


def test_asset_cache_signature_tracks_relocation_and_export_ignores_viewport_cache(tmp_path):
    first_dir, second_dir = tmp_path / "first", tmp_path / "second"
    first_dir.mkdir()
    second_dir.mkdir()
    Image.new("RGBA", (4, 4), (255, 0, 0, 255)).save(first_dir / "asset.png")
    Image.new("RGBA", (4, 4), (0, 0, 255, 255)).save(second_dir / "asset.png")
    project = ProjectRecipe(
        width=4,
        height=4,
        layers=[
            LayerRecipe(
                "image",
                "Image",
                op(
                    "generator.image",
                    "source",
                    asset=AssetReference("asset.png", "project_relative"),
                ),
            )
        ],
    )
    engine = RenderEngine()
    red = engine.render(project, render_context=RenderContext(first_dir / "doc.atx"))
    blue = engine.render(project, render_context=RenderContext(second_dir / "doc.atx"))
    assert not np.array_equal(red.rgba_field, blue.rgba_field)
    destination = tmp_path / "current.png"
    ImageExporter().export_png(
        project, destination, render_context=RenderContext(second_dir / "doc.atx")
    )
    with Image.open(destination) as saved:
        np.testing.assert_array_equal(
            np.asarray(saved), np.rint(blue.rgba_field * 255).astype(np.uint8)
        )


def test_bounded_lru_evicts_and_cached_arrays_are_read_only():
    cache = LayerResultCache(max_bytes=350)
    rgba = np.zeros((4, 4, 4), dtype=np.float32)
    scalar = np.zeros((4, 4), dtype=np.float32)
    cache.put("one", rgba, scalar)
    cached = cache.get("one")
    assert cached is not None
    assert not cached[0].flags.writeable and not cached[1].flags.writeable
    with pytest.raises(ValueError):
        cached[0][0, 0, 0] = 1.0
    cache.put("two", rgba, scalar)
    assert cache.stats["bytes"] <= cache.max_bytes
    assert cache.stats["entries"] == 1
    assert cache.get("one") is None


def test_deterministic_render_cancellation_coalesces_a_b_and_publishes_only_c():
    a_started = threading.Event()
    release_a = threading.Event()
    stages: dict[float, list[int]] = {1.0: [], 2.0: [], 3.0: []}

    def deliberately_slow(_field, parameters, width, height, _seed, context):
        value = float(parameters["value"])
        for stage in range(4):
            context.check_cancelled()
            stages[value].append(stage)
            if value == 1.0 and stage == 0:
                a_started.set()
                assert release_a.wait(5)
            context.check_cancelled()
        return np.full((height, width), value / 3.0, dtype=np.float32)

    custom = OperationDefinitionSet(definitions=dict(REGISTRY.definitions))
    custom.register(
        OperationDefinition(
            "test.slow",
            1,
            "Test Slow",
            "Test",
            "Event-gated cancellation fixture.",
            OperationType.GENERATOR,
            (),
            "scalar",
            (ParameterSpec("value", "Value", ParameterType.FLOAT, default=1.0),),
            Seamlessness.UNKNOWN,
            deliberately_slow,
            requires_render_context=True,
        )
    )
    output: list[RenderOutcome] = []
    completed = threading.Event()
    coordinator = RenderCoordinator(
        engine=RenderEngine(custom),
        on_complete=lambda outcome: (output.append(outcome), completed.set()),
    )

    def scene(value: float):
        return ProjectRecipe(
            width=3,
            height=3,
            layers=[
                LayerRecipe(
                    "slow",
                    "Slow",
                    OperationInstance("source", "test.slow", 1, parameters={"value": value}),
                )
            ],
        )

    try:
        first = coordinator.request(scene(1.0), width=3, height=3)
        assert a_started.wait(3)
        second = coordinator.request(scene(2.0), width=3, height=3)
        third = coordinator.request(scene(3.0), width=3, height=3)
        release_a.set()
        assert completed.wait(5)
        assert first.cancellation_token.cancelled
        assert second.cancellation_token.cancelled
        assert stages[1.0] == [0]
        assert stages[2.0] == []
        assert stages[3.0] == [0, 1, 2, 3]
        assert [outcome.request_id for outcome in output] == [third.request_id]
        assert output[0].error is None
        assert output[0].result is not None
        assert coordinator.engine.session.stats["cancellations"] == 1
    finally:
        release_a.set()
        coordinator.close()
