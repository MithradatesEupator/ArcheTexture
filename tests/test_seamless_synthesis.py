from __future__ import annotations

import numpy as np
import pytest
from PIL import Image

from archetexture.color.ramp import ColorRamp, ColorStop
from archetexture.core.operations import Seamlessness
from archetexture.core.parameters import ControlFieldBinding
from archetexture.core.recipe import LayerRecipe, OperationInstance, ProjectRecipe
from archetexture.core.registry import REGISTRY
from archetexture.core.sampling import (
    periodic_lattice_coordinates,
    sample_periodic_value_noise,
    sample_periodic_value_noise_at,
)
from archetexture.core.seamlessness import recipe_seamlessness
from archetexture.core.serialization import load_project, save_project
from archetexture.core.validation import ValidationError, ensure_valid_recipe
from archetexture.export.image_export import ImageExporter
from archetexture.generators.noise import _cellular_from_lattice, _periodic_fractal_at
from archetexture.render.engine import RenderEngine
from archetexture.render.pixels import rgba_float_to_uint8

PERIODIC_GENERATORS = (
    "generator.seamless_value_noise",
    "generator.seamless_fractal_noise",
    "generator.seamless_turbulence",
    "generator.seamless_cellular",
)


def parameters_for(operation_id: str, **overrides):
    definition = REGISTRY.get(operation_id)
    parameters = {spec.identifier: spec.default for spec in definition.parameter_specs}
    parameters.update(overrides)
    return parameters


def make_recipe(operation_id: str, *, width=96, height=64, **overrides):
    definition = REGISTRY.get(operation_id)
    return ProjectRecipe(
        width=width,
        height=height,
        seed=83,
        layers=[
            LayerRecipe(
                "periodic-layer",
                "Periodic layer",
                OperationInstance(
                    "periodic-source",
                    operation_id,
                    definition.version,
                    parameters=parameters_for(operation_id, **overrides),
                ),
                color_ramp=ColorRamp(
                    (
                        ColorStop(0.0, (0.03, 0.04, 0.1, 1.0)),
                        ColorStop(1.0, (0.9, 0.72, 0.32, 1.0)),
                    )
                ),
            )
        ],
    )


def render(operation_id: str, **overrides):
    return RenderEngine().render(make_recipe(operation_id, **overrides))


@pytest.mark.parametrize("seed", [0, 19, 2**31 - 1])
def test_periodic_value_sampling_repeats_x_y_both_negative_and_offset_coordinates(seed):
    rng = np.random.default_rng(seed + 5)
    x = rng.uniform(-18.0, 22.0, size=(9, 13)).astype(np.float32)
    y = rng.uniform(-12.0, 16.0, size=(9, 13)).astype(np.float32)
    cells_x, cells_y = 7, 5
    offsets = (-2.375, 4.125)
    original = sample_periodic_value_noise_at(
        x + offsets[0], y + offsets[1], seed, cells_x, cells_y
    )
    for shifted_x, shifted_y in (
        (x + cells_x + offsets[0], y + offsets[1]),
        (x + offsets[0], y + cells_y + offsets[1]),
        (x + cells_x + offsets[0], y + cells_y + offsets[1]),
    ):
        shifted = sample_periodic_value_noise_at(shifted_x, shifted_y, seed, cells_x, cells_y)
        np.testing.assert_allclose(shifted, original, rtol=0.0, atol=3e-6)


def test_periodic_coordinates_keep_cell_period_independent_of_output_resolution():
    low_x, low_y = periodic_lattice_coordinates(64, 40, 9, 6, -1.25, 2.5)
    high_x, high_y = periodic_lattice_coordinates(256, 160, 9, 6, -1.25, 2.5)
    low = sample_periodic_value_noise(64, 40, 17, 9, 6, -1.25, 2.5)
    high = sample_periodic_value_noise(256, 160, 17, 9, 6, -1.25, 2.5)
    assert low.shape == (40, 64)
    assert high.shape == (160, 256)
    assert low.dtype == high.dtype == np.float32
    assert np.isfinite(high).all()
    assert np.isclose(low_x[0, 0], 0.5 / 64 * 9 - 1.25)
    assert np.isclose(high_x[0, 0], 0.5 / 256 * 9 - 1.25)
    assert np.isclose(low_x[0, -1] + 0.5 / 64 * 9, 9.0 - 1.25)
    assert np.isclose(high_x[0, -1] + 0.5 / 256 * 9, 9.0 - 1.25)
    assert np.isclose(low_y[-1, 0] + 0.5 / 40 * 6, 6.0 + 2.5)
    assert np.isclose(high_y[-1, 0] + 0.5 / 160 * 6, 6.0 + 2.5)


@pytest.mark.parametrize("lacunarity", [2, 3, 4])
@pytest.mark.parametrize("turbulence", [False, True])
def test_periodic_fractal_and_turbulence_repeat_for_every_supported_lacunarity(
    lacunarity, turbulence
):
    rng = np.random.default_rng(14)
    x = rng.uniform(-8.0, 11.0, size=(7, 11)).astype(np.float64)
    y = rng.uniform(-6.0, 9.0, size=(7, 11)).astype(np.float64)
    kwargs = dict(
        seed=71,
        cells_x=5,
        cells_y=3,
        octaves=6,
        lacunarity=lacunarity,
        persistence=0.55,
        offset_x=-1.75,
        offset_y=2.125,
        turbulence=turbulence,
    )
    original = _periodic_fractal_at(x, y, **kwargs)
    np.testing.assert_allclose(_periodic_fractal_at(x + 5, y, **kwargs), original, atol=5e-6)
    np.testing.assert_allclose(_periodic_fractal_at(x, y + 3, **kwargs), original, atol=5e-6)
    np.testing.assert_allclose(_periodic_fractal_at(x + 5, y + 3, **kwargs), original, atol=5e-6)


@pytest.mark.parametrize("distance_mode", ["nearest", "edge"])
def test_periodic_cellular_features_and_distance_outputs_repeat(distance_mode):
    rng = np.random.default_rng(23)
    cells_x, cells_y = 5, 8
    x = rng.uniform(-9.0, 13.0, size=(8, 12)).astype(np.float32)
    y = rng.uniform(-7.0, 10.0, size=(8, 12)).astype(np.float32)
    kwargs = dict(
        seed=29,
        jitter=0.85,
        distance_mode=distance_mode,
        period_x=cells_x,
        period_y=cells_y,
    )
    original = _cellular_from_lattice(x, y, **kwargs)
    np.testing.assert_allclose(
        _cellular_from_lattice(x + cells_x, y, **kwargs), original, atol=5e-6
    )
    np.testing.assert_allclose(
        _cellular_from_lattice(x, y + cells_y, **kwargs), original, atol=5e-6
    )
    np.testing.assert_allclose(
        _cellular_from_lattice(x + cells_x, y + cells_y, **kwargs), original, atol=5e-6
    )


@pytest.mark.parametrize("operation_id", PERIODIC_GENERATORS)
def test_seamless_generators_are_deterministic_normalized_and_rectangular(operation_id):
    kwargs = {"width": 97, "height": 61, "cells_x": 7, "cells_y": 5}
    if "fractal" in operation_id or "turbulence" in operation_id:
        kwargs.update(octaves=6, lacunarity=3)
    first = render(operation_id, **kwargs).scalar_field
    second = render(operation_id, **kwargs).scalar_field
    different_seed = render(operation_id, seed=100, **kwargs).scalar_field
    assert first.shape == (61, 97)
    assert first.dtype == np.float32
    assert np.isfinite(first).all()
    assert first.min() >= 0.0 and first.max() <= 1.0
    np.testing.assert_array_equal(first, second)
    assert not np.array_equal(first, different_seed)
    assert not np.array_equal(
        first, render(operation_id, **(kwargs | {"cells_x": 11})).scalar_field
    )
    assert not np.array_equal(first, render(operation_id, **(kwargs | {"cells_y": 9})).scalar_field)


def test_seamless_octaves_and_cellular_modes_change_structure_and_registration_is_new():
    for operation_id in PERIODIC_GENERATORS:
        definition = REGISTRY.get(operation_id)
        assert definition.version == 1
        assert definition.seamlessness == Seamlessness.INHERENT
    assert REGISTRY.get("generator.value_noise").version == 1
    assert REGISTRY.get("generator.fractal_noise").version == 1
    assert REGISTRY.get("generator.turbulence").version == 1
    assert REGISTRY.get("generator.cellular").version == 1

    fractal = render("generator.seamless_fractal_noise").scalar_field
    assert not np.array_equal(
        fractal, render("generator.seamless_fractal_noise", octaves=2).scalar_field
    )
    assert not np.array_equal(
        fractal, render("generator.seamless_fractal_noise", lacunarity=4).scalar_field
    )
    assert not np.array_equal(
        render("generator.seamless_cellular").scalar_field,
        render("generator.seamless_cellular", distance_mode="edge").scalar_field,
    )


def test_seamless_defaults_validate_and_tile_parameters_do_not_allow_modulation():
    for operation_id in PERIODIC_GENERATORS:
        recipe = make_recipe(operation_id)
        ensure_valid_recipe(recipe)
        for spec in REGISTRY.get(operation_id).parameter_specs:
            assert spec.allows_modulation is False
    recipe = make_recipe("generator.seamless_value_noise")
    recipe.layers[0].source.parameters["offset_x"] = ControlFieldBinding("bad-modulation")
    with pytest.raises(ValidationError, match="does not allow control-field modulation"):
        ensure_valid_recipe(recipe)


def test_seamlessness_metadata_and_conservative_layer_propagation():
    assert REGISTRY.get("generator.constant").seamlessness == Seamlessness.INHERENT
    assert REGISTRY.get("generator.checker_grid").seamlessness == Seamlessness.WRAP_CAPABLE
    for operation_id in (
        "transform.invert",
        "transform.threshold",
        "transform.quantize",
        "transform.levels",
        "transform.blur",
        "transform.sharpen",
        "transform.normalize",
        "transform.offset",
        "transform.flip",
        "transform.edge_detail",
    ):
        assert REGISTRY.get(operation_id).seamlessness == Seamlessness.PRESERVES
    for operation_id in (
        "generator.white_noise",
        "generator.linear_gradient",
        "generator.radial_gradient",
        "generator.value_noise",
        "generator.fractal_noise",
        "generator.turbulence",
        "generator.cellular",
        "generator.bands",
    ):
        assert REGISTRY.get(operation_id).seamlessness == Seamlessness.UNKNOWN

    seamless = make_recipe("generator.seamless_value_noise")
    seamless.layers[0].transforms.append(
        OperationInstance("blur", "transform.blur", 1, parameters={"sigma": 1.4})
    )
    assert recipe_seamlessness(seamless) == "Yes"
    seamless.layers.append(
        LayerRecipe(
            "seamless-overlay",
            "Seamless overlay",
            OperationInstance(
                "cellular-source",
                "generator.seamless_cellular",
                1,
                parameters=parameters_for("generator.seamless_cellular"),
            ),
            color_ramp=seamless.layers[0].color_ramp,
            opacity=0.35,
            blend_mode="screen",
        )
    )
    assert recipe_seamlessness(seamless) == "Yes"
    assert RenderEngine().render(seamless).rgba_field.shape == (64, 96, 4)

    modulated = make_recipe("generator.seamless_value_noise")
    modulated.layers[0].source.parameters["offset_x"] = ControlFieldBinding("spatial-field")
    assert recipe_seamlessness(modulated) == "Unknown"

    checker = make_recipe("generator.checker_grid", cells_x=8, cells_y=10)
    assert recipe_seamlessness(checker) == "Yes"
    checker.layers[0].source.parameters["cells_x"] = 7
    assert recipe_seamlessness(checker) == "No"
    checker.layers[0].source.parameters.update(cells_x=7, pattern="grid")
    assert recipe_seamlessness(checker) == "Yes"

    seamless.layers.append(
        LayerRecipe(
            "legacy-layer",
            "Legacy noise",
            OperationInstance(
                "legacy-source",
                "generator.fractal_noise",
                1,
                parameters=parameters_for("generator.fractal_noise"),
            ),
            opacity=0.0,
        )
    )
    assert recipe_seamlessness(seamless) == "Yes"
    seamless.layers[2].opacity = 1.0
    assert recipe_seamlessness(seamless) == "Unknown"


@pytest.mark.parametrize("operation_id", PERIODIC_GENERATORS)
def test_seamless_recipe_save_load_render_and_png_stay_one_tile(operation_id, tmp_path):
    kwargs = {"width": 47, "height": 31, "cells_x": 5, "cells_y": 7}
    if "fractal" in operation_id or "turbulence" in operation_id:
        kwargs.update(octaves=4, lacunarity=3)
    recipe = make_recipe(operation_id, **kwargs)
    recipe.layers[0].transforms.append(OperationInstance("invert", "transform.invert", 1))
    expected = RenderEngine().render(recipe).rgba_field
    project = tmp_path / f"{operation_id.rsplit('.', 1)[-1]}.archetexture"
    save_project(recipe, project)
    loaded = load_project(project)
    assert loaded == recipe
    np.testing.assert_array_equal(RenderEngine().render(loaded).rgba_field, expected)

    output = tmp_path / f"{operation_id.rsplit('.', 1)[-1]}.png"
    ImageExporter().export_png(loaded, output)
    with Image.open(output) as image:
        assert image.size == (47, 31)
        assert image.mode == "RGBA"
        np.testing.assert_array_equal(np.asarray(image), rgba_float_to_uint8(expected))
