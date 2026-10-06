from __future__ import annotations

import json

import numpy as np
import pytest

from archetexture.color.ramp import ColorRamp, ColorStop
from archetexture.core.defaults import default_recipe
from archetexture.core.document import DocumentController
from archetexture.core.parameters import ControlFieldBinding, ControlFieldMapping
from archetexture.core.recipe import (
    ControlFieldRecipe,
    LayerRecipe,
    OperationInstance,
    ProjectRecipe,
)
from archetexture.core.seamlessness import recipe_seamlessness
from archetexture.core.serialization import load_project, migrate_recipe, save_project
from archetexture.core.validation import ValidationError, ensure_valid_recipe
from archetexture.export.image_export import ImageExporter
from archetexture.render.engine import RenderEngine, RenderResult, composite_rgba
from archetexture.render.pixels import rgba_float_to_uint8
from archetexture.ui.main_window import MainWindow
from archetexture.ui.viewport import TextureViewport


def instance(op_id: str, name: str, **params) -> OperationInstance:
    return OperationInstance(name, op_id, 1, parameters=params)


def field(identifier: str, value: float) -> ControlFieldRecipe:
    return ControlFieldRecipe(instance("generator.constant", f"{identifier}-src", value=value))


def masked_recipe(mask: float, *, opacity: float = 1.0, blend: str = "normal"):
    ramp_blue = ColorRamp((ColorStop(0, (0, 0, 1, 1)), ColorStop(1, (0, 0, 1, 1))))
    ramp_red = ColorRamp((ColorStop(0, (1, 0, 0, 1)), ColorStop(1, (1, 0, 0, 1))))
    return ProjectRecipe(
        width=3,
        height=2,
        layers=[
            LayerRecipe(
                "base",
                "Base",
                instance("generator.constant", "base-src", value=0.5),
                color_ramp=ramp_blue,
            ),
            LayerRecipe(
                "top",
                "Top",
                instance("generator.constant", "top-src", value=0.5),
                color_ramp=ramp_red,
                opacity=opacity,
                blend_mode=blend,
                mask=ControlFieldBinding("mask"),
            ),
        ],
        control_fields={"mask": field("mask", mask)},
    )


@pytest.mark.parametrize("mode", ["normal", "multiply", "screen", "add"])
def test_mask_scales_layer_alpha_before_each_blend_mode(mode):
    recipe = masked_recipe(0.4, opacity=0.5, blend=mode)
    result = RenderEngine().render(recipe).rgba_field
    expected = composite_rgba(
        np.broadcast_to(np.array([0, 0, 1, 1], np.float32), (2, 3, 4)).copy(),
        np.broadcast_to(np.array([1, 0, 0, 1], np.float32), (2, 3, 4)).copy(),
        0.2,
        mode,
    )
    np.testing.assert_allclose(result, expected)


def test_mask_zero_one_intermediate_and_opacity_multiply():
    zero = RenderEngine().render(masked_recipe(0.0)).rgba_field
    full = RenderEngine().render(masked_recipe(1.0)).rgba_field
    partial = RenderEngine().render(masked_recipe(0.4, opacity=0.5)).rgba_field
    np.testing.assert_allclose(
        zero, np.broadcast_to(np.array([0, 0, 1, 1], np.float32), zero.shape)
    )
    np.testing.assert_allclose(full[0, 0], (1, 0, 0, 1))
    np.testing.assert_allclose(partial[0, 0], (0.2, 0, 0.8, 1))


def test_source_alpha_is_multiplied_by_opacity_and_mask():
    base = np.array([[[0.0, 0.0, 1.0, 1.0]]], dtype=np.float32)
    top = np.array([[[1.0, 0.0, 0.0, 0.6]]], dtype=np.float32)
    result = composite_rgba(base, top, 0.5, mask=np.array([[0.5]], dtype=np.float32))
    np.testing.assert_allclose(result[0, 0], (0.15, 0.0, 0.85, 1.0))


def test_mask_binding_invert_mapping_and_quantization_are_applied():
    recipe = masked_recipe(0.25)
    recipe.layers[1].mask = ControlFieldBinding(
        "mask", ControlFieldMapping(output_min=0.2, output_max=0.8, invert=True, quantize=4)
    )
    result = RenderEngine().render(recipe)
    expected_mask = np.full((2, 3), 0.65, np.float32)
    np.testing.assert_allclose(result.mask_fields["top"], expected_mask)


def test_linear_gradient_mask_varies_spatial_contribution_and_inversion_reverses_it():
    recipe = masked_recipe(0.5)
    recipe.control_fields["mask"] = ControlFieldRecipe(
        instance("generator.linear_gradient", "gradient-mask", angle=0.0)
    )
    recipe.width = 31
    normal = RenderEngine().render(recipe)
    values = normal.mask_fields["top"]
    assert values.min() < values.max()
    left_to_right = normal.rgba_field[values.shape[0] // 2, :, 0]
    recipe.layers[1].mask = ControlFieldBinding("mask", ControlFieldMapping(invert=True))
    inverted = RenderEngine().render(recipe)
    assert np.corrcoef(left_to_right, inverted.rgba_field[values.shape[0] // 2, :, 0])[0, 1] < -0.95


def test_fractal_noise_and_cellular_layers_blend_spatially_through_gradient_mask():
    recipe = default_recipe()
    recipe.width = 64
    recipe.height = 40
    recipe.layers[1].color_ramp = ColorRamp(
        (ColorStop(0, (1, 0, 0, 1)), ColorStop(1, (1, 0, 0, 1)))
    )
    recipe.layers[1].mask = ControlFieldBinding("spatial-mask")
    recipe.control_fields["spatial-mask"] = ControlFieldRecipe(
        instance("generator.linear_gradient", "spatial-mask-source", angle=0.0)
    )
    masked = RenderEngine().render(recipe)
    recipe.layers[1].enabled = False
    base_only = RenderEngine().render(recipe).rgba_field
    row = recipe.height // 2
    mask = masked.mask_fields[recipe.layers[1].layer_id][row]
    contribution = np.linalg.norm(masked.rgba_field[row, :, :3] - base_only[row, :, :3], axis=1)
    assert masked.mask_fields[recipe.layers[1].layer_id].min() == 0.0
    assert masked.mask_fields[recipe.layers[1].layer_id].max() == 1.0
    assert contribution[-1] > contribution[0]
    assert mask[-1] > mask[0]


def test_height_to_normal_rgba_output_is_masked_without_modifying_rgb_field():
    recipe = masked_recipe(0.0)
    top = recipe.layers[1]
    top.source = instance("generator.linear_gradient", "height-src", angle=0.0)
    top.transforms = [instance("transform.height_to_normal", "normal", strength=1.0)]
    top.color_ramp = None
    zero = RenderEngine().render(recipe).rgba_field
    np.testing.assert_allclose(
        zero, np.broadcast_to(np.array([0, 0, 1, 1], np.float32), zero.shape)
    )
    recipe.layers[1].mask = ControlFieldBinding("mask", ControlFieldMapping())
    recipe.control_fields["mask"] = field("mask", 1.0)
    full = RenderEngine().render(recipe).rgba_field
    assert not np.array_equal(zero, full)
    assert np.all((full[..., :3] >= 0.0) & (full[..., :3] <= 1.0))
    np.testing.assert_allclose(full[..., 3], 1.0)


def test_masked_render_export_and_schema3_round_trip_are_equal(tmp_path):
    recipe = masked_recipe(0.37, opacity=0.6)
    rendered = RenderEngine().render(recipe).rgba_field
    project_path = tmp_path / "masked.archetexture"
    save_project(recipe, project_path)
    payload = json.loads(project_path.read_text(encoding="utf-8"))
    assert payload["schema_version"] == 3
    assert payload["layers"][1]["mask"]["source_id"] == "mask"
    reopened = load_project(project_path)
    assert reopened == recipe
    np.testing.assert_array_equal(RenderEngine().render(reopened).rgba_field, rendered)
    png = tmp_path / "masked.png"
    ImageExporter().export_png(reopened, png)
    from PIL import Image

    with Image.open(png) as exported:
        np.testing.assert_array_equal(np.asarray(exported), rgba_float_to_uint8(rendered))


def test_mask_mapping_change_is_undoable_and_redoable():
    document = DocumentController(masked_recipe(0.5))
    initial = document.recipe.layers[1].mask
    edited = document.recipe
    edited.layers[1].mask = ControlFieldBinding(
        "mask", ControlFieldMapping(output_min=0.2, output_max=0.8, invert=True)
    )
    document.commit(edited)
    changed = document.recipe.layers[1].mask
    assert changed != initial
    document.undo()
    assert document.recipe.layers[1].mask == initial
    document.redo()
    assert document.recipe.layers[1].mask == changed


def test_schema1_and_schema2_migrate_to_canonical_schema3_without_masks():
    v1 = {
        "schema_version": 1,
        "source": {
            "instance_id": "source",
            "operation_id": "generator.constant",
            "operation_version": 1,
            "parameters": {"value": 0.5},
        },
    }
    migrated1 = migrate_recipe(v1)
    assert migrated1.schema_version == 3 and migrated1.layers[0].mask is None
    v2 = {
        "schema_version": 2,
        "layers": [
            {
                "layer_id": "layer",
                "name": "Layer",
                "source": {
                    "instance_id": "source",
                    "operation_id": "generator.constant",
                    "operation_version": 1,
                    "parameters": {"value": 0.5},
                },
            }
        ],
    }
    migrated2 = migrate_recipe(v2)
    assert migrated2.schema_version == 3 and migrated2.layers[0].mask is None


def test_malformed_or_missing_mask_reference_is_rejected():
    recipe = masked_recipe(0.5)
    recipe.layers[1].mask = ControlFieldBinding("missing")
    with pytest.raises(ValidationError, match="unknown control field"):
        ensure_valid_recipe(recipe)
    payload = {
        "schema_version": 3,
        "layers": [
            {
                "layer_id": "layer",
                "name": "Layer",
                "source": {
                    "instance_id": "source",
                    "operation_id": "generator.constant",
                    "operation_version": 1,
                    "parameters": {"value": 0.5},
                },
                "mask": "bad",
            }
        ],
    }
    with pytest.raises(ValidationError):
        migrate_recipe(payload)


def test_seamlessness_accounts_for_layer_mask():
    recipe = ProjectRecipe(
        layers=[
            LayerRecipe(
                "layer",
                "Layer",
                instance("generator.constant", "src", value=0.5),
                mask=ControlFieldBinding("mask"),
            )
        ],
        control_fields={
            "mask": ControlFieldRecipe(instance("generator.constant", "mask-src", value=0.5))
        },
    )
    # A constant source is inherent and therefore proves periodicity for both layer and mask.
    assert recipe_seamlessness(recipe) == "Yes"
    recipe.control_fields["mask"] = ControlFieldRecipe(
        instance("generator.radial_gradient", "radial", radius=0.5)
    )
    assert recipe_seamlessness(recipe) != "Yes"


def test_gui_add_mask_selects_field_and_exposes_preview_and_navigation(qtbot):
    window = MainWindow()
    qtbot.addWidget(window)
    window._confirm_discard = lambda: True
    window.layers_panel.add_mask_button.click()
    layer = window._layer()
    assert layer.mask is not None
    assert layer.mask.source_id in window.document.recipe.control_fields
    assert window.right_tabs.currentWidget() is window.control_fields_editor
    assert window.control_fields_editor.selected_field_id == layer.mask.source_id
    assert window.viewport_mode_combo.findData("mask_preview") >= 0
    window.layers_panel.open_mask_button.click()
    assert window.control_fields_editor.selected_field_id == layer.mask.source_id
    window.undo()
    assert window._layer().mask is None
    window.redo()
    assert window._layer().mask is not None
    source_combo = window.control_fields_editor.source_combo
    source_index = source_combo.findData("generator.linear_gradient")
    assert source_index >= 0
    source_combo.setCurrentIndex(source_index)
    assert window.document.recipe.control_fields[layer.mask.source_id].source.operation_id == (
        "generator.linear_gradient"
    )
    transform_combo = window.control_fields_editor.transform_combo
    if transform_combo.count():
        window.control_fields_editor.add_transform_button.click()
        assert window.document.recipe.control_fields[layer.mask.source_id].transforms
    window.close()


def test_control_field_rename_updates_mask_and_referenced_delete_is_blocked(qtbot, monkeypatch):
    from archetexture.ui import main_window as main_window_module

    window = MainWindow()
    qtbot.addWidget(window)
    window._confirm_discard = lambda: True
    window.layers_panel.add_mask_button.click()
    original_id = window._layer().mask.source_id
    renamed_id = "renamed-mask"
    window._rename_control_field(original_id, renamed_id)
    assert window._layer().mask.source_id == renamed_id
    assert renamed_id in window.document.recipe.control_fields
    messages = []
    monkeypatch.setattr(
        main_window_module.QMessageBox,
        "information",
        lambda *args: messages.append(args),
    )
    window._remove_control_field(renamed_id)
    assert renamed_id in window.document.recipe.control_fields
    assert messages
    window.undo()
    assert window._layer().mask.source_id == original_id
    window.redo()
    assert window._layer().mask.source_id == renamed_id
    window.close()


def test_mask_preview_is_grayscale_presentation_only(qtbot):
    rgba = np.full((2, 3, 4), (0.2, 0.4, 0.8, 1.0), dtype=np.float32)
    mask = np.array([[0.0, 0.5, 1.0], [1.0, 0.5, 0.0]], dtype=np.float32)
    result = RenderResult(None, rgba.copy(), {"layer": mask.copy()})
    viewport = TextureViewport()
    qtbot.addWidget(viewport)
    viewport.set_result(result)
    rendered_before = viewport.rendered_field.copy()
    viewport.set_mask_preview(result.mask_fields["layer"])
    viewport.set_display_mode("mask_preview")
    assert viewport._presentation_pixmap.cacheKey() == viewport._mask_pixmap.cacheKey()
    np.testing.assert_array_equal(viewport.rendered_field, rendered_before)
    assert not np.array_equal(viewport.rendered_field, mask)
