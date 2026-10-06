from __future__ import annotations

import numpy as np
import pytest

from archetexture.color.ramp import ColorRamp, ColorStop
from archetexture.core.parameters import ControlFieldBinding, ControlFieldMapping
from archetexture.core.recipe import (
    ControlFieldRecipe,
    LayerRecipe,
    OperationInstance,
    ProjectRecipe,
)
from archetexture.core.registry import REGISTRY
from archetexture.core.serialization import load_project, save_project
from archetexture.core.validation import ensure_valid_recipe
from archetexture.export.image_export import ImageExporter
from archetexture.render.engine import RenderEngine
from archetexture.render.pixels import rgba_float_to_uint8

GENERATOR_IDS = (
    "generator.value_noise",
    "generator.fractal_noise",
    "generator.turbulence",
    "generator.cellular",
    "generator.bands",
    "generator.checker_grid",
)


def parameters_for(operation_id: str, **overrides):
    definition = REGISTRY.get(operation_id)
    result = {spec.identifier: spec.default for spec in definition.parameter_specs}
    result.update(overrides)
    return result


def generator_recipe(operation_id: str, *, width=72, height=48, **overrides):
    definition = REGISTRY.get(operation_id)
    return ProjectRecipe(
        width=width,
        height=height,
        seed=11,
        layers=[
            LayerRecipe(
                "layer",
                "Layer",
                OperationInstance(
                    "source",
                    operation_id,
                    definition.version,
                    parameters=parameters_for(operation_id, **overrides),
                ),
            )
        ],
    )


def render(operation_id: str, **overrides):
    recipe = generator_recipe(operation_id, **overrides)
    return RenderEngine().render(recipe).scalar_field


def test_noise_generators_are_deterministic_bounded_and_parameterized():
    first = render("generator.value_noise")
    assert np.array_equal(first, render("generator.value_noise"))
    assert not np.array_equal(first, render("generator.value_noise", seed=18))
    assert not np.array_equal(first, render("generator.value_noise", scale=10.0))
    assert not np.array_equal(first, render("generator.value_noise", offset_x=1.25))

    fractal = render("generator.fractal_noise")
    assert np.array_equal(fractal, render("generator.fractal_noise"))
    assert not np.array_equal(fractal, render("generator.fractal_noise", seed=19))
    assert not np.array_equal(fractal, render("generator.fractal_noise", offset_y=-0.75))
    for change in (
        {"octaves": 2},
        {"lacunarity": 3.0},
        {"persistence": 0.85},
        {"scale": 8.0},
    ):
        assert np.mean(np.abs(fractal - render("generator.fractal_noise", **change))) > 0.005

    turbulence = render("generator.turbulence")
    assert np.array_equal(turbulence, render("generator.turbulence"))
    assert not np.array_equal(turbulence, fractal)
    assert not np.array_equal(turbulence, render("generator.turbulence", seed=50))


def test_cellular_and_periodic_generators_respond_to_controls():
    cellular = render("generator.cellular")
    assert np.array_equal(cellular, render("generator.cellular"))
    assert not np.array_equal(cellular, render("generator.cellular", seed=80))
    assert not np.array_equal(cellular, render("generator.cellular", scale=13.0))
    assert not np.array_equal(cellular, render("generator.cellular", jitter=0.0))
    assert not np.array_equal(cellular, render("generator.cellular", distance_mode="edge"))

    bands = render("generator.bands")
    assert not np.array_equal(bands, render("generator.bands", frequency=11.0))
    assert not np.array_equal(bands, render("generator.bands", angle=63.0))
    assert not np.array_equal(bands, render("generator.bands", phase=0.25))
    waveform_outputs = {
        waveform: render("generator.bands", waveform=waveform)
        for waveform in ("sine", "triangle", "saw", "square")
    }
    assert all(
        not np.array_equal(waveform_outputs["sine"], output)
        for output in waveform_outputs.values()
        if output is not waveform_outputs["sine"]
    )

    checker = render("generator.checker_grid", width=67, height=43)
    assert checker.shape == (43, 67)
    assert set(np.unique(checker)).issubset({0.0, 1.0})
    grid = render("generator.checker_grid", pattern="grid")
    assert grid.shape == (48, 72)
    assert not np.array_equal(checker, render("generator.checker_grid", cells_x=13))


def run_transform(operation_id: str, source: np.ndarray, **overrides) -> np.ndarray:
    definition = REGISTRY.get(operation_id)
    parameters = parameters_for(operation_id, **overrides)
    result = definition.implementation(source, parameters, source.shape[1], source.shape[0], 0)
    return np.asarray(result, dtype=np.float32)


def test_tonal_transforms_have_documented_mapping_and_constant_safety():
    source = np.array([[0.2, 0.35, 0.5, 0.8]], dtype=np.float32)
    leveled = run_transform(
        "transform.levels",
        source,
        input_black=0.2,
        input_white=0.8,
        gamma=1.0,
        output_black=0.1,
        output_white=0.9,
    )
    assert np.allclose(leveled, [[0.1, 0.3, 0.5, 0.9]])
    brightened_midtones = run_transform("transform.levels", source, gamma=2.0)
    assert brightened_midtones[0, 2] > source[0, 2]
    degenerate = run_transform("transform.levels", source, input_black=0.5, input_white=0.5)
    assert np.isfinite(degenerate).all()
    assert (
        run_transform("transform.brightness_contrast", source, brightness=0.2)[0, 0] > source[0, 0]
    )
    contrasted = run_transform("transform.brightness_contrast", source, contrast=2.0)
    assert contrasted[0, 0] < source[0, 0] and contrasted[0, -1] == 1.0
    assert np.array_equal(
        run_transform("transform.normalize", np.full((3, 4), 0.4, np.float32)),
        np.zeros((3, 4), np.float32),
    )


def test_blur_sharpen_spatial_and_edge_transforms_change_fields_usefully():
    checker = render("generator.checker_grid", cells_x=16, cells_y=12)
    blurred = run_transform("transform.blur", checker, sigma=1.4)
    assert blurred.std() < checker.std()
    sharpened = run_transform("transform.sharpen", blurred, amount=2.0, sigma=0.7)
    assert sharpened.std() > blurred.std()

    source = np.arange(30, dtype=np.float32).reshape(5, 6) / 29.0
    shifted = run_transform("transform.offset", source, offset_x=2, offset_y=-1)
    assert np.array_equal(shifted, np.roll(source, (-1, 2), axis=(0, 1)))
    assert np.array_equal(
        run_transform("transform.flip", source, axis="horizontal"), np.flip(source, axis=1)
    )
    assert np.array_equal(
        run_transform("transform.flip", source, axis="vertical"), np.flip(source, axis=0)
    )
    edges = run_transform("transform.edge_detail", source)
    assert edges.min() >= 0.0 and edges.max() == 1.0


@pytest.mark.parametrize("operation_id", GENERATOR_IDS)
def test_registered_generator_dispatch_returns_valid_float32_fields(operation_id):
    definition = REGISTRY.get(operation_id)
    recipe = generator_recipe(operation_id)
    output = RenderEngine().render(recipe).scalar_field
    assert output.shape == (48, 72)
    assert output.dtype == np.float32
    assert np.isfinite(output).all()
    assert 0.0 <= output.min() <= output.max() <= 1.0
    assert callable(definition.implementation)


def test_all_new_operation_defaults_pass_domain_validation():
    transforms = {
        "transform.levels",
        "transform.brightness_contrast",
        "transform.blur",
        "transform.sharpen",
        "transform.normalize",
        "transform.offset",
        "transform.flip",
        "transform.edge_detail",
    }
    for identifier in GENERATOR_IDS:
        recipe = generator_recipe(identifier)
        recipe.layers[0].source.parameters = {}
        ensure_valid_recipe(recipe)
    for identifier in transforms:
        definition = REGISTRY.get(identifier)
        recipe = ProjectRecipe(
            width=8,
            height=8,
            layers=[
                LayerRecipe(
                    "layer",
                    "Layer",
                    OperationInstance("source", "generator.constant", 1, parameters={}),
                    [OperationInstance("transform", identifier, definition.version, parameters={})],
                )
            ],
        )
        ensure_valid_recipe(recipe)


def test_procedural_gallery_outputs_are_distinct_and_valid():
    samples = {identifier: render(identifier) for identifier in GENERATOR_IDS}
    for sample in samples.values():
        assert sample.shape == (48, 72)
        assert sample.dtype == np.float32
        assert np.isfinite(sample).all()
        assert sample.min() >= 0.0 and sample.max() <= 1.0
    identifiers = tuple(samples)
    for left_index, left in enumerate(identifiers):
        for right in identifiers[left_index + 1 :]:
            assert np.mean(np.abs(samples[left] - samples[right])) > 0.02


def test_fractal_scale_supports_existing_control_field_modulation():
    recipe = generator_recipe("generator.fractal_noise", width=64, height=42)
    recipe.layers[0].source.parameters["scale"] = ControlFieldBinding(
        "scale-field", ControlFieldMapping(1.0, 18.0)
    )
    recipe.control_fields["scale-field"] = ControlFieldRecipe(
        OperationInstance(
            "scale-source",
            "generator.linear_gradient",
            1,
            parameters={"angle": 0.0},
        )
    )
    modulated = RenderEngine().render(recipe).scalar_field
    fixed = render("generator.fractal_noise", width=64, height=42, scale=8.0)
    assert not np.allclose(modulated, fixed)


def test_new_operations_compose_round_trip_and_export_together(tmp_path):
    recipe = ProjectRecipe(
        width=64,
        height=48,
        seed=6,
        layers=[
            LayerRecipe(
                "stone-base",
                "Stone base",
                OperationInstance(
                    "stone-source",
                    "generator.fractal_noise",
                    1,
                    parameters=parameters_for(
                        "generator.fractal_noise",
                        scale=ControlFieldBinding("scale-map", ControlFieldMapping(2.0, 13.0)),
                    ),
                ),
                [
                    OperationInstance(
                        "stone-levels",
                        "transform.levels",
                        1,
                        parameters=parameters_for(
                            "transform.levels", input_black=0.12, input_white=0.86, gamma=1.1
                        ),
                    ),
                    OperationInstance(
                        "stone-blur",
                        "transform.blur",
                        1,
                        parameters={"sigma": 0.45},
                    ),
                ],
                ColorRamp(
                    (
                        ColorStop(0, (0.08, 0.045, 0.025, 1)),
                        ColorStop(1, (0.7, 0.48, 0.27, 1)),
                    )
                ),
            ),
            LayerRecipe(
                "bands-overlay",
                "Bands",
                OperationInstance(
                    "bands-source",
                    "generator.bands",
                    1,
                    parameters=parameters_for("generator.bands", angle=34.0, waveform="triangle"),
                ),
                color_ramp=ColorRamp(
                    (ColorStop(0, (0.2, 0.03, 0.02, 0.05)), ColorStop(1, (0.9, 0.55, 0.24, 0.7)))
                ),
                opacity=0.3,
                blend_mode="multiply",
            ),
            LayerRecipe(
                "cell-detail",
                "Cell detail",
                OperationInstance(
                    "cell-source",
                    "generator.cellular",
                    1,
                    parameters=parameters_for(
                        "generator.cellular", scale=9.0, distance_mode="edge"
                    ),
                ),
                [
                    OperationInstance("cell-invert", "transform.invert", 1),
                    OperationInstance(
                        "cell-levels",
                        "transform.levels",
                        1,
                        parameters=parameters_for(
                            "transform.levels", input_black=0.15, input_white=0.9
                        ),
                    ),
                ],
                color_ramp=ColorRamp(
                    (ColorStop(0, (0.1, 0.04, 0.015, 0.0)), ColorStop(1, (1, 0.8, 0.4, 0.8)))
                ),
                opacity=0.2,
                blend_mode="screen",
            ),
        ],
        control_fields={
            "scale-map": ControlFieldRecipe(
                OperationInstance(
                    "scale-control",
                    "generator.linear_gradient",
                    1,
                    parameters={"angle": 0.0},
                )
            )
        },
    )
    engine = RenderEngine()
    expected = engine.render(recipe).rgba_field
    for index in range(3):
        solo = ProjectRecipe(
            width=recipe.width,
            height=recipe.height,
            seed=recipe.seed,
            layers=[recipe.layers[index]],
            control_fields=recipe.control_fields,
        )
        assert not np.array_equal(expected, engine.render(solo).rgba_field)

    project_path = tmp_path / "synthesis.archetexture"
    save_project(recipe, project_path)
    loaded = load_project(project_path)
    assert loaded == recipe
    actual = engine.render(loaded).rgba_field
    assert np.array_equal(actual, expected)

    png_path = tmp_path / "synthesis.png"
    ImageExporter(engine).export_png(loaded, png_path, width=64, height=48)
    from PIL import Image

    with Image.open(png_path) as image:
        assert np.array_equal(np.asarray(image), rgba_float_to_uint8(expected))
