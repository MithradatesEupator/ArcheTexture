from __future__ import annotations

import copy
from dataclasses import replace

import numpy as np
import pytest
from PIL import Image
from PySide6.QtWidgets import QComboBox, QDoubleSpinBox, QMessageBox

from archetexture.core.operations import OperationDefinitionSet, Seamlessness
from archetexture.core.parameters import ControlFieldBinding, ControlFieldMapping
from archetexture.core.pipeline import evaluate_layer
from archetexture.core.pipeline_types import (
    compatible_append_transforms,
    pipeline_output_type,
    valid_transform_chain,
)
from archetexture.core.recipe import (
    ControlFieldRecipe,
    LayerRecipe,
    OperationInstance,
    ProjectRecipe,
)
from archetexture.core.registry import REGISTRY
from archetexture.core.seamlessness import recipe_seamlessness
from archetexture.core.serialization import load_project, save_project
from archetexture.core.validation import ValidationError, ensure_valid_recipe
from archetexture.export.image_export import ImageExporter
from archetexture.render.engine import RenderEngine
from archetexture.render.pixels import rgba_float_to_uint8
from archetexture.transforms.spatial import height_to_normal
from archetexture.ui.color_ramp_editor import ColorRampEditor
from archetexture.ui.main_window import build_main_window


def instance(identifier: str, operation_id: str, parameters=None, *, enabled=True):
    return OperationInstance(
        identifier,
        operation_id,
        1,
        enabled=enabled,
        parameters={} if parameters is None else parameters,
    )


def normal_recipe(width=24, height=16, *, source_id="generator.constant", params=None):
    return ProjectRecipe(
        width=width,
        height=height,
        seed=31,
        layers=[
            LayerRecipe(
                "layer",
                "Normal layer",
                instance("source", source_id, params),
            )
        ],
    )


def run_normal(field, strength=1.0, convention="opengl", edge_mode="clamp"):
    height, width = field.shape
    return height_to_normal(
        field,
        {"strength": strength, "convention": convention, "edge_mode": edge_mode},
        width,
        height,
        0,
    )


def test_flat_ramp_strength_normalization_rectangular_and_resolution_independence():
    flat = run_normal(np.full((9, 13), 0.4, dtype=np.float32))
    assert flat.shape == (9, 13, 4)
    np.testing.assert_allclose(
        flat,
        np.broadcast_to(np.array((0.5, 0.5, 1.0, 1.0), dtype=np.float32), flat.shape),
        atol=1e-7,
    )

    width, height = 41, 23
    horizontal = np.tile(np.linspace(0.0, 1.0, width, dtype=np.float32), (height, 1))
    vertical = np.tile(np.linspace(0.0, 1.0, height, dtype=np.float32)[:, None], (1, width))
    weak = run_normal(horizontal, strength=0.5)
    strong = run_normal(horizontal, strength=2.0)
    assert weak[height // 2, width // 2, 0] < 0.5
    assert strong[height // 2, width // 2, 0] < weak[height // 2, width // 2, 0]
    assert strong[height // 2, width // 2, 2] < weak[height // 2, width // 2, 2]
    assert run_normal(vertical)[height // 2, width // 2, 1] > 0.5
    decoded = strong[..., :3] * 2.0 - 1.0
    np.testing.assert_allclose(np.linalg.norm(decoded, axis=-1), 1.0, atol=1e-6)
    assert np.isfinite(strong).all()
    assert np.all(strong[..., 3] == 1.0)

    def sampled_ramp(w, h):
        x = (np.arange(w, dtype=np.float32) + 0.5) / w
        y = (np.arange(h, dtype=np.float32) + 0.5) / h
        return np.broadcast_to(x[None, :] + y[:, None] * 0.2, (h, w)).copy()

    low = run_normal(sampled_ramp(64, 32), edge_mode="wrap")
    high = run_normal(sampled_ramp(256, 128), edge_mode="wrap")
    np.testing.assert_allclose(low[8:-8, 8:-8], high[32:-32:4, 32:-32:4], atol=2e-5)


def test_opengl_directx_only_flip_green_and_wrap_uses_opposite_edge_samples():
    y, x = np.mgrid[:11, :17].astype(np.float32)
    field = (x / 17.0 + y / 11.0) % 1.0
    gl = run_normal(field, convention="opengl", edge_mode="wrap")
    dx = run_normal(field, convention="directx", edge_mode="wrap")
    np.testing.assert_allclose(gl[..., 0], dx[..., 0])
    np.testing.assert_allclose(gl[..., 2:], dx[..., 2:])
    np.testing.assert_allclose(gl[..., 1] + dx[..., 1], 1.0, atol=1e-7)
    expected_dx = (np.roll(field, -1, axis=1) - np.roll(field, 1, axis=1)) * (17 / 2)
    expected_dy = (np.roll(field, -1, axis=0) - np.roll(field, 1, axis=0)) * (11 / 2)
    denominator = np.sqrt(expected_dx**2 + expected_dy**2 + 1.0)
    expected_nx = -expected_dx / denominator
    np.testing.assert_allclose(gl[..., 0], expected_nx * 0.5 + 0.5, atol=1e-6)
    ramp = np.tile(np.linspace(0.0, 1.0, 17, dtype=np.float32), (11, 1))
    clamped = run_normal(ramp, edge_mode="clamp")
    clamped_dx = (ramp[:, 1] - ramp[:, 0]) * (17 * 0.5)
    expected_first_red = -clamped_dx / np.sqrt(clamped_dx**2 + 1.0) * 0.5 + 0.5
    np.testing.assert_allclose(clamped[:, 0, 0], expected_first_red, atol=1e-6)


def test_registered_type_flow_compatibility_and_control_field_exclusion():
    scalar = instance("s", "generator.constant", {"value": 0.5})
    normal = instance(
        "n",
        "transform.height_to_normal",
        {"strength": 1.0, "convention": "opengl", "edge_mode": "wrap"},
    )
    blur = instance("b", "transform.blur", {"sigma": 1.0})
    assert REGISTRY.get("transform.height_to_normal").output_type == "rgba"
    assert pipeline_output_type(scalar, []) == "scalar"
    assert pipeline_output_type(scalar, [normal]) == "rgba"
    assert (
        pipeline_output_type(
            scalar,
            [
                instance(
                    "disabled",
                    "transform.height_to_normal",
                    {
                        "strength": 1.0,
                        "convention": "opengl",
                        "edge_mode": "wrap",
                    },
                    enabled=False,
                )
            ],
        )
        == "scalar"
    )
    assert valid_transform_chain(scalar, [blur, normal])
    assert not valid_transform_chain(scalar, [normal, blur])
    assert not valid_transform_chain(scalar, [normal], color_ramp_active=True)
    assert "transform.height_to_normal" not in {
        definition.identifier
        for definition in compatible_append_transforms(scalar, [], color_ramp_active=True)
    }
    assert all(
        definition.output_type == "scalar"
        for definition in compatible_append_transforms(scalar, [])
        if definition.identifier in {"transform.invert", "transform.blur"}
    )
    from archetexture.ui.control_fields_editor import ControlFieldsEditor

    assert "transform.height_to_normal" not in {
        definition.identifier for definition in ControlFieldsEditor._compatible_transforms()
    }


def test_type_changing_pipeline_validation_ramp_and_render(tmp_path):
    recipe = normal_recipe(21, 13, source_id="generator.linear_gradient", params={"angle": 0.0})
    operation = instance(
        "normal",
        "transform.height_to_normal",
        {"strength": 3.0, "convention": "directx", "edge_mode": "clamp"},
    )
    recipe.layers[0].transforms.append(operation)
    ensure_valid_recipe(recipe)
    rendered = RenderEngine().render(recipe).rgba_field
    assert rendered.shape == (13, 21, 4)
    assert not np.allclose(rendered[..., :3], rendered[..., :1])

    invalid_ramp = copy.deepcopy(recipe)
    invalid_ramp.layers[0].color_ramp = None
    from archetexture.color.ramp import ColorRamp, ColorStop

    invalid_ramp.layers[0].color_ramp = ColorRamp(
        (ColorStop(0.0, (0, 0, 0, 1)), ColorStop(1.0, (1, 1, 1, 1)))
    )
    with pytest.raises(ValidationError, match="color ramps require scalar source output"):
        ensure_valid_recipe(invalid_ramp)

    destination = tmp_path / "normal.png"
    ImageExporter().export_png(recipe, destination, width=15, height=9)
    with Image.open(destination) as image:
        assert image.mode == "RGBA"
        actual = np.asarray(image)
    expected = rgba_float_to_uint8(RenderEngine().render(recipe, width=15, height=9).rgba_field)
    np.testing.assert_array_equal(actual, expected)
    np.testing.assert_array_equal(actual[..., 3], 255)
    assert (recipe.width, recipe.height) == (21, 13)

    project_path = tmp_path / "normal.archetexture"
    save_project(recipe, project_path)
    reopened = load_project(project_path)
    assert reopened.layers[0].transforms[0] == operation
    np.testing.assert_array_equal(RenderEngine().render(reopened).rgba_field, rendered)


def test_wrap_seamlessness_and_clamp_is_conservative():
    recipe = normal_recipe(
        32,
        24,
        source_id="generator.seamless_value_noise",
        params={"seed": 5, "cells_x": 5, "cells_y": 4, "offset_x": 0.0, "offset_y": 0.0},
    )
    wrap = instance(
        "normal",
        "transform.height_to_normal",
        {"strength": 1.0, "convention": "opengl", "edge_mode": "wrap"},
    )
    recipe.layers[0].transforms = [wrap]
    assert recipe_seamlessness(recipe) == "Yes"
    normal_field = evaluate_layer(recipe, recipe.layers[0])
    assert normal_field.shape == (24, 32, 4)
    clamp_recipe = copy.deepcopy(recipe)
    clamp_recipe.layers[0].transforms[0].parameters["edge_mode"] = "clamp"
    assert recipe_seamlessness(clamp_recipe) == "Unknown"
    unknown_recipe = copy.deepcopy(recipe)
    unknown_recipe.layers[0].source = instance(
        "linear", "generator.linear_gradient", {"angle": 0.0}
    )
    assert recipe_seamlessness(unknown_recipe) == "Unknown"
    broken_recipe = copy.deepcopy(recipe)
    broken_recipe.layers[0].source = instance("white", "generator.white_noise", {"seed": 23})
    registry = OperationDefinitionSet(definitions=dict(REGISTRY.definitions))
    registry.definitions["generator.white_noise"] = replace(
        REGISTRY.get("generator.white_noise"), seamlessness=Seamlessness.BREAKS
    )
    assert recipe_seamlessness(broken_recipe, registry) == "No"


def test_strength_control_binding_renders_and_makes_seam_status_conservative():
    recipe = normal_recipe(
        20,
        14,
        source_id="generator.seamless_value_noise",
        params={"seed": 5, "cells_x": 4, "cells_y": 3, "offset_x": 0.0, "offset_y": 0.0},
    )
    recipe.control_fields["strength-field"] = ControlFieldRecipe(
        instance(
            "control-source",
            "generator.seamless_value_noise",
            {
                "seed": 8,
                "cells_x": 2,
                "cells_y": 2,
                "offset_x": 0.0,
                "offset_y": 0.0,
            },
        )
    )
    recipe.layers[0].transforms = [
        instance(
            "normal",
            "transform.height_to_normal",
            {
                "strength": ControlFieldBinding(
                    "strength-field", ControlFieldMapping(output_min=0.5, output_max=2.0)
                ),
                "convention": "opengl",
                "edge_mode": "wrap",
            },
        )
    ]
    rendered = RenderEngine().render(recipe).rgba_field
    assert rendered.shape == (14, 20, 4)
    assert np.isfinite(rendered).all()
    assert recipe_seamlessness(recipe) == "Unknown"


def test_pipeline_ui_append_reorder_output_description_undo_redo_and_dark(qtbot, monkeypatch):
    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda *_args, **_kwargs: QMessageBox.StandardButton.Discard,
    )
    recipe = normal_recipe(32, 24, source_id="generator.linear_gradient", params={"angle": 0.0})
    recipe.layers[0].color_ramp = ColorRampEditor.default_ramp()
    recipe.layers[0].transforms.extend(
        (
            instance("invert", "transform.invert"),
            instance("blur", "transform.blur", {"sigma": 0.6}),
        )
    )
    window = build_main_window(recipe)
    qtbot.addWidget(window)
    window.show()
    qtbot.waitUntil(lambda: window.viewport.rendered_field is not None, timeout=5000)
    panel = window.pipeline_panel
    assert panel.transform_selector.findData("transform.height_to_normal") == -1
    window._color_ramp_changed(None)
    assert panel.transform_selector.findData("transform.height_to_normal") >= 0
    blur_row = next(
        row
        for row in range(panel.transform_list.count())
        if panel.transform_list.item(row).data(256) == "blur"
    )
    panel.transform_list.setCurrentRow(blur_row)
    assert panel.up_button.isEnabled()
    assert "transform.height_to_normal" in {
        panel.transform_selector.itemData(i) for i in range(panel.transform_selector.count())
    }
    window._transform_added("transform.height_to_normal")
    qtbot.waitUntil(lambda: window.viewport.rendered_field.shape == (24, 32, 4), timeout=5000)
    qtbot.waitUntil(
        lambda: (
            not np.allclose(
                window.viewport.rendered_field[..., :3], window.viewport.rendered_field[..., :1]
            )
        ),
        timeout=5000,
    )
    assert not np.allclose(
        window.viewport.rendered_field[..., :3], window.viewport.rendered_field[..., :1]
    )
    assert pipeline_output_type(window._layer().source, window._layer().transforms) == "rgba"
    assert window.property_editor.findChild(QDoubleSpinBox) is not None
    enum_values = [
        [combo.itemText(i) for i in range(combo.count())]
        for combo in window.property_editor.findChildren(QComboBox)
    ]
    assert ["opengl", "directx"] in enum_values
    assert ["wrap", "clamp"] in enum_values
    assert panel.transform_selector.count() == 1
    assert panel.transform_selector.itemData(0) == "transform.extract_channel"
    assert panel.transform_selector.isEnabled()
    assert panel.add_button.isEnabled()
    assert "Height to Normal → RGBA" in panel.output_description.text()
    assert window.color_ramp_editor.inapplicable_label.isVisible()
    assert not window.color_ramp_editor.create_button.isVisible()

    normal_row = panel.transform_list.count() - 1
    panel.transform_list.setCurrentRow(normal_row)
    assert not panel.up_button.isEnabled()
    before = window.document.recipe
    window._transform_moved(window._layer().transforms[-1].instance_id, 0)
    assert window.document.recipe == before

    window.undo()
    assert pipeline_output_type(window._layer().source, window._layer().transforms) == "scalar"
    window.redo()
    assert pipeline_output_type(window._layer().source, window._layer().transforms) == "rgba"
    panel.transform_list.setCurrentRow(panel.transform_list.count() - 1)
    window._set_theme("dark")
    for widget in (
        window.property_editor.findChild(QDoubleSpinBox),
        window.property_editor.findChildren(QComboBox)[0],
    ):
        assert widget.palette().color(widget.palette().ColorRole.Window).lightness() < 100
    assert (
        window.color_ramp_editor.palette()
        .color(window.color_ramp_editor.palette().ColorRole.Window)
        .lightness()
        < 100
    )
    window.close()


def test_height_to_normal_parameter_edits_are_ordinary_undoable_history():
    from archetexture.core.document import DocumentController

    recipe = normal_recipe()
    recipe.layers[0].transforms = [
        instance(
            "normal",
            "transform.height_to_normal",
            {"strength": 1.0, "convention": "opengl", "edge_mode": "wrap"},
        )
    ]
    document = DocumentController(recipe)
    snapshots = [
        ("strength", 3.0),
        ("convention", "directx"),
        ("edge_mode", "clamp"),
    ]
    for parameter, value in snapshots:
        updated = document.recipe
        updated.layers[0].transforms[0].parameters[parameter] = value
        document.commit(updated)
    assert document.dirty
    assert [
        document.recipe.layers[0].transforms[0].parameters[key]
        for key in ("strength", "convention", "edge_mode")
    ] == [3.0, "directx", "clamp"]
    for expected in ((3.0, "directx", "wrap"), (3.0, "opengl", "wrap"), (1.0, "opengl", "wrap")):
        document.undo()
        assert (
            tuple(
                document.recipe.layers[0].transforms[0].parameters[key]
                for key in ("strength", "convention", "edge_mode")
            )
            == expected
        )
    assert not document.dirty
    for _ in snapshots:
        document.redo()
    assert tuple(
        document.recipe.layers[0].transforms[0].parameters[key]
        for key in ("strength", "convention", "edge_mode")
    ) == (3.0, "directx", "clamp")
