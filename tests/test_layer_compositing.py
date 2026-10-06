from __future__ import annotations

import json
from threading import Event

import numpy as np

from archetexture.color.ramp import ColorRamp, ColorStop
from archetexture.core.defaults import default_recipe
from archetexture.core.parameters import ControlFieldBinding, ControlFieldMapping
from archetexture.core.recipe import (
    ControlFieldRecipe,
    LayerRecipe,
    OperationInstance,
    ProjectRecipe,
)
from archetexture.core.serialization import load_project, migrate_recipe, save_project
from archetexture.render.coordinator import RenderCoordinator
from archetexture.render.engine import RenderEngine, composite_rgba


def op(operation_id: str, identifier: str, **parameters) -> OperationInstance:
    return OperationInstance(identifier, operation_id, 1, parameters=parameters)


def solid_layer(layer_id, name, value, color, *, opacity=1.0, blend_mode="normal"):
    return LayerRecipe(
        layer_id,
        name,
        op("generator.constant", f"source-{layer_id}", value=value),
        color_ramp=ColorRamp((ColorStop(0.0, (*color, 1.0)), ColorStop(1.0, (*color, 1.0)))),
        opacity=opacity,
        blend_mode=blend_mode,
    )


def test_all_supported_blends_and_opacity_use_float32_source_over():
    base = np.array([[[0.25, 0.5, 0.75, 1.0]]], dtype=np.float32)
    top = np.array([[[0.8, 0.4, 0.2, 1.0]]], dtype=np.float32)
    expected = {
        "normal": (0.8, 0.4, 0.2),
        "multiply": (0.2, 0.2, 0.15),
        "screen": (0.85, 0.7, 0.8),
        "add": (1.0, 0.9, 0.95),
    }
    for mode, rgb in expected.items():
        result = composite_rgba(base, top, 1.0, mode)
        assert result.dtype == np.float32
        assert np.allclose(result[0, 0, :3], rgb)
        assert result[0, 0, 3] == 1.0
    half = composite_rgba(base, top, 0.5, "normal")
    assert np.allclose(half[0, 0, :3], (0.525, 0.45, 0.475))


def test_default_document_visibly_combines_two_procedural_layers():
    recipe = default_recipe()
    assert len(recipe.layers) >= 2
    assert recipe.layers[0].source.operation_id == "generator.fractal_noise"
    assert recipe.layers[1].source.operation_id == "generator.cellular"
    full = RenderEngine().render(recipe).rgba_field
    recipe.layers[1].enabled = False
    noise_only = RenderEngine().render(recipe).rgba_field
    assert not np.array_equal(full, noise_only)


def test_layer_order_opacity_and_visibility_change_composite_pixels():
    bottom = solid_layer("bottom", "Layer 1", 0.5, (0.0, 0.0, 1.0))
    top = solid_layer("top", "Layer 2", 0.5, (1.0, 0.0, 0.0), opacity=0.3)
    recipe = ProjectRecipe(width=3, height=2, layers=[bottom, top])
    engine = RenderEngine()
    first = engine.render(recipe).rgba_field
    assert np.allclose(first[0, 0], (0.3, 0.0, 0.7, 1.0))
    recipe.layers.reverse()
    reversed_result = engine.render(recipe).rgba_field
    assert not np.array_equal(first, reversed_result)
    recipe.layers[0].enabled = False
    hidden = engine.render(recipe).rgba_field
    assert np.allclose(hidden, (0.0, 0.0, 1.0, 1.0))


def test_multilayer_v2_round_trip_preserves_bindings_and_render(tmp_path):
    recipe = ProjectRecipe(
        width=12,
        height=8,
        seed=42,
        layers=[
            LayerRecipe(
                "noise",
                "Noise floor",
                op("generator.white_noise", "noise-source", seed=9),
                [op("transform.invert", "noise-invert")],
                ColorRamp((ColorStop(0, (0, 0, 0, 1)), ColorStop(1, (1, 1, 1, 1)))),
            ),
            LayerRecipe(
                "gradient",
                "Tint",
                op(
                    "generator.linear_gradient",
                    "gradient-source",
                    angle=ControlFieldBinding("mask"),
                ),
                [op("transform.quantize", "gradient-quantize", levels=5)],
                ColorRamp((ColorStop(0, (0.2, 0.0, 0.0, 0.1)), ColorStop(1, (1, 0.6, 0.1, 0.8)))),
                opacity=0.35,
                blend_mode="screen",
            ),
        ],
        control_fields={
            "mask": ControlFieldRecipe(op("generator.radial_gradient", "mask-source", radius=0.7))
        },
    )
    expected = RenderEngine().render(recipe).rgba_field
    path = tmp_path / "stack.archetexture"
    save_project(recipe, path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["schema_version"] == 4
    assert len(payload["layers"]) == 2
    assert "source" not in payload
    restored = load_project(path)
    assert restored == recipe
    assert np.array_equal(RenderEngine().render(restored).rgba_field, expected)


def test_v1_migration_creates_one_equivalent_layer_and_preserves_controls():
    legacy = {
        "schema_version": 1,
        "width": 7,
        "height": 5,
        "seed": 13,
        "source": {
            "instance_id": "legacy-source",
            "operation_id": "generator.constant",
            "operation_version": 1,
            "enabled": True,
            "parameters": {"value": 0.35},
            "influence": 1.0,
        },
        "transforms": [],
        "color_ramp": {
            "stops": [
                {"position": 0.0, "color": [0.0, 0.1, 0.2, 1.0]},
                {"position": 1.0, "color": [0.8, 0.7, 0.6, 1.0]},
            ]
        },
        "control_fields": {
            "mask": {
                "source": {
                    "instance_id": "legacy-mask",
                    "operation_id": "generator.constant",
                    "operation_version": 1,
                    "enabled": True,
                    "parameters": {"value": 0.4},
                    "influence": 1.0,
                },
                "transforms": [],
                "mapping": None,
            }
        },
    }
    migrated = migrate_recipe(legacy)
    assert migrated.schema_version == 4
    assert len(migrated.layers) == 1
    assert migrated.layers[0].layer_id == "layer-1"
    assert migrated.control_fields.keys() == {"mask"}
    assert np.allclose(RenderEngine().render(migrated).rgba_field[0, 0], (0.28, 0.31, 0.34, 1.0))


def test_async_renderer_returns_multilayer_composite():
    recipe = ProjectRecipe(
        width=16,
        height=10,
        layers=[
            solid_layer("async-base", "Base", 0.3, (0.1, 0.2, 0.3)),
            solid_layer("async-top", "Top", 0.7, (0.8, 0.4, 0.2), opacity=0.4),
        ],
    )
    completed = Event()
    outcomes = []
    coordinator = RenderCoordinator(
        on_complete=lambda result: (outcomes.append(result), completed.set())
    )
    coordinator.request(recipe, width=16, height=10)
    assert completed.wait(5)
    coordinator.close()
    assert outcomes[0].error is None
    expected = RenderEngine().render(recipe).rgba_field
    assert np.array_equal(outcomes[0].result.rgba_field, expected)


def test_control_field_modulates_source_in_a_different_layer():
    ramp = ColorRamp((ColorStop(0.0, (0.0, 0.0, 0.0, 1.0)), ColorStop(1.0, (1.0, 1.0, 1.0, 1.0))))
    recipe = ProjectRecipe(
        width=19,
        height=13,
        layers=[
            solid_layer("field-base", "Base", 0.2, (0.1, 0.2, 0.3)),
            LayerRecipe(
                "field-gradient",
                "Modulated gradient",
                op("generator.linear_gradient", "field-gradient-source", angle=0.0),
                color_ramp=ramp,
                opacity=0.5,
            ),
        ],
        control_fields={
            "mask": ControlFieldRecipe(op("generator.radial_gradient", "field-mask", radius=0.7))
        },
    )
    engine = RenderEngine()
    fixed = engine.render(recipe).rgba_field
    recipe.layers[1].source.parameters["angle"] = ControlFieldBinding(
        "mask", ControlFieldMapping(output_min=0.0, output_max=360.0)
    )
    modulated = engine.render(recipe).rgba_field
    assert not np.allclose(fixed, modulated)
