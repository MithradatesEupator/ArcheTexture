from __future__ import annotations

import numpy as np
import pytest
from PIL import Image
from PySide6.QtWidgets import QComboBox

from archetexture.core.assets import AssetReference
from archetexture.core.defaults import default_recipe
from archetexture.core.material_presets import apply_material_preset
from archetexture.core.output_dependencies import topological_output_order
from archetexture.core.recipe import (
    LayerRecipe,
    MaterialOutputRecipe,
    OperationInstance,
    ProjectRecipe,
)
from archetexture.core.serialization import load_project, save_project
from archetexture.core.validation import ValidationError, ensure_valid_recipe
from archetexture.export.texture_set import (
    OutputExportSpec,
    TextureSetExporter,
    TextureSetExportPlan,
)
from archetexture.render.engine import RenderEngine


def _output(output_id, name, value_type, source, *, transforms=None):
    semantic = {"scalar": "custom_scalar", "color": "custom_color", "normal": "normal"}[value_type]
    return MaterialOutputRecipe(
        output_id,
        name,
        semantic,
        value_type,
        [LayerRecipe(f"layer-{output_id}", "Layer", source, transforms or [])],
    )


def _source(instance_id, value):
    return OperationInstance(instance_id, "generator.constant", 1, parameters={"value": value})


def test_default_normal_is_a_live_height_reference():
    recipe = default_recipe()
    normal = recipe.output("normal").layers[0]
    assert normal.source.operation_id == "generator.output_scalar"
    assert normal.source.parameters == {"target": "height", "mode": "Direct"}
    ensure_valid_recipe(recipe)


@pytest.mark.parametrize(
    "mode",
    [
        "Red",
        "Green",
        "Blue",
        "Alpha",
        "Luminance",
        "Average RGB",
        "Minimum RGB",
        "Maximum RGB",
    ],
)
def test_output_scalar_extracts_authoritative_color_channels(mode, tmp_path):
    image_path = tmp_path / "channels.png"
    Image.fromarray(np.array([[[51, 102, 153, 204]]], dtype=np.uint8)).save(image_path)
    recipe = ProjectRecipe(
        width=3,
        height=2,
        outputs=[
            _output(
                "base",
                "Base",
                "color",
                OperationInstance(
                    "image",
                    "generator.image",
                    1,
                    parameters={"asset": AssetReference(str(image_path), "absolute")},
                ),
            ),
            _output(
                "derived",
                "Derived",
                "scalar",
                OperationInstance(
                    "extract",
                    "generator.output_scalar",
                    1,
                    parameters={"target": "base", "mode": mode},
                ),
            ),
        ],
    )
    engine = RenderEngine()
    color = engine.render_output(recipe, "base").rgba_field
    result = engine.render_output(recipe, "derived")
    rgb = color[..., :3]
    expected = {
        "Red": color[..., 0],
        "Green": color[..., 1],
        "Blue": color[..., 2],
        "Alpha": color[..., 3],
        "Luminance": rgb[..., 0] * 0.2126 + rgb[..., 1] * 0.7152 + rgb[..., 2] * 0.0722,
        "Average RGB": np.mean(rgb, axis=-1),
        "Minimum RGB": np.min(rgb, axis=-1),
        "Maximum RGB": np.max(rgb, axis=-1),
    }[mode]
    np.testing.assert_allclose(result.scalar_field, expected, atol=1e-6)


def test_live_reference_render_memoization_and_rename_stability(tmp_path):
    height = _output(
        "height",
        "Height",
        "scalar",
        OperationInstance(
            "height-source", "generator.linear_gradient", 1, parameters={"angle": 0.0}
        ),
    )
    normal_source = OperationInstance(
        "normal-source",
        "generator.output_scalar",
        1,
        parameters={"target": "height", "mode": "Direct"},
    )
    normal = _output(
        "normal",
        "Normal",
        "normal",
        normal_source,
        transforms=[
            OperationInstance(
                "height-normal",
                "transform.height_to_normal",
                1,
                parameters={"strength": 1.0, "convention": "opengl", "edge_mode": "wrap"},
            )
        ],
    )
    recipe = ProjectRecipe(width=8, height=8, outputs=[normal, height])
    ensure_valid_recipe(recipe)
    engine = RenderEngine()
    first = engine.render_output(recipe, "normal")
    recipe.output("height").name = "Renamed Height"
    second = engine.render_material(recipe).outputs["normal"]
    np.testing.assert_array_equal(first.rgba_field, second.rgba_field)
    path = tmp_path / "linked.archetexture"
    save_project(recipe, path)
    assert load_project(path).output("normal").layers[0].source.parameters["target"] == "height"
    recipe.output("height").layers[0].source.parameters["angle"] = 90.0
    updated = engine.render_output(recipe, "normal")
    assert not np.array_equal(second.rgba_field, updated.rgba_field)


@pytest.mark.parametrize("targets", [("a",), ("b", "a"), ("b", "c", "a"), ("b", "c", "d", "a")])
def test_output_cycles_are_rejected_with_path(targets):
    ids = ("a", *targets)
    outputs = []
    for index, output_id in enumerate(ids):
        target = ids[(index + 1) % len(ids)]
        source = OperationInstance(
            f"source-{output_id}",
            "generator.output_scalar",
            1,
            parameters={"target": target, "mode": "Direct"},
        )
        outputs.append(_output(output_id, output_id.upper(), "scalar", source))
    with pytest.raises(ValidationError, match="Output dependency cycle"):
        ensure_valid_recipe(ProjectRecipe(width=2, height=2, outputs=outputs))


def test_output_color_promotes_scalar_to_opaque_grayscale():
    recipe = ProjectRecipe(
        width=2,
        height=2,
        outputs=[
            _output("scalar", "Scalar", "scalar", _source("constant", 0.3)),
            _output(
                "color",
                "Color",
                "color",
                OperationInstance(
                    "promote", "generator.output_color", 1, parameters={"target": "scalar"}
                ),
            ),
        ],
    )
    result = RenderEngine().render_output(recipe, "color")
    expected = np.broadcast_to(np.array([0.3, 0.3, 0.3, 1.0]), result.rgba_field.shape)
    np.testing.assert_allclose(result.rgba_field, expected)


def test_dependency_order_is_independent_of_output_list_order():
    source = _output("source", "Source", "scalar", _source("source-generator", 0.3))
    derived = _output(
        "derived",
        "Derived",
        "scalar",
        OperationInstance(
            "derived-source",
            "generator.output_scalar",
            1,
            parameters={"target": "source", "mode": "Direct"},
        ),
    )
    recipe = ProjectRecipe(width=2, height=2, outputs=[derived, source])
    assert topological_output_order(recipe) == ("source", "derived")


def test_texture_export_renders_hidden_upstream_dependency(tmp_path):
    height = _output(
        "height",
        "Height",
        "scalar",
        OperationInstance(
            "height-generator", "generator.linear_gradient", 1, parameters={"angle": 0.0}
        ),
    )
    normal = _output(
        "normal",
        "Normal",
        "normal",
        OperationInstance(
            "normal-reference",
            "generator.output_scalar",
            1,
            parameters={"target": "height", "mode": "Direct"},
        ),
        transforms=[
            OperationInstance(
                "height-to-normal",
                "transform.height_to_normal",
                1,
                parameters={"strength": 1.0, "convention": "opengl", "edge_mode": "wrap"},
            )
        ],
    )
    recipe = ProjectRecipe(width=8, height=8, outputs=[height, normal])
    plan = TextureSetExportPlan(
        str(tmp_path),
        "OnlyNormal",
        8,
        8,
        outputs=(OutputExportSpec("normal", "Normal"),),
    )
    (path,) = TextureSetExporter().export(recipe, plan)
    from PIL import Image

    exported = np.asarray(Image.open(path))
    expected = np.rint(RenderEngine().render_output(recipe, "normal").rgba_field * 255).astype(
        np.uint8
    )
    np.testing.assert_array_equal(exported, expected)
    assert [item.name for item in tmp_path.iterdir()] == ["OnlyNormal_Normal.png"]


def test_control_fields_explicitly_reject_output_references():
    from archetexture.core.recipe import ControlFieldRecipe

    recipe = default_recipe()
    recipe.control_fields["derived"] = ControlFieldRecipe(
        OperationInstance(
            "cf-output",
            "generator.output_scalar",
            1,
            parameters={"target": "height", "mode": "Direct"},
        )
    )
    with pytest.raises(ValidationError, match="not supported inside Control Fields"):
        ensure_valid_recipe(recipe)


def test_missing_and_invalid_direct_references_are_rejected():
    recipe = ProjectRecipe(
        width=2,
        height=2,
        outputs=[
            _output("color", "Color", "color", _source("constant", 0.3)),
            _output(
                "scalar",
                "Scalar",
                "scalar",
                OperationInstance(
                    "direct",
                    "generator.output_scalar",
                    1,
                    parameters={"target": "color", "mode": "Direct"},
                ),
            ),
        ],
    )
    with pytest.raises(ValidationError, match="Direct mode requires a scalar target"):
        ensure_valid_recipe(recipe)
    recipe.output("scalar").layers[0].source.parameters.update(target="absent", mode="Luminance")
    with pytest.raises(ValidationError, match="references missing output"):
        ensure_valid_recipe(recipe)


def test_preset_new_normal_links_to_height_without_replacing_existing_normal():
    recipe = default_recipe()
    recipe.outputs = [item for item in recipe.outputs if item.semantic not in {"normal", "height"}]
    apply_material_preset(recipe, "Metallic / Roughness PBR")
    linked_normal = next(item for item in recipe.outputs if item.semantic == "normal")
    linked_height = next(item for item in recipe.outputs if item.semantic == "height")
    assert linked_normal.layers[0].source.parameters["target"] == linked_height.output_id


def test_property_editor_shows_output_names_but_stores_stable_ids(qtbot):
    from archetexture.core.registry import REGISTRY
    from archetexture.ui.property_editor import PropertyEditor

    recipe = default_recipe()
    instance = OperationInstance(
        "ref",
        "generator.output_scalar",
        1,
        parameters={"target": "height", "mode": "Direct"},
    )
    editor = PropertyEditor()
    qtbot.addWidget(editor)
    editor.set_material_outputs(recipe, "normal")
    editor.set_operation(instance, REGISTRY.get(instance.operation_id))
    selector = editor.findChild(QComboBox, "parameter-target")
    assert selector.currentText() == "Height · Scalar"
    assert selector.currentData() == "height"


def test_output_manager_derivation_and_delete_blocker(qtbot, monkeypatch):
    from PySide6.QtWidgets import QInputDialog, QMessageBox

    from archetexture.ui.output_manager import OutputManagerDialog

    recipe = default_recipe()
    manager = OutputManagerDialog(recipe, "base-color")
    qtbot.addWidget(manager)
    selected = []

    def choose(_parent, title, _label, items, *_args):
        if title == "Derive Output":
            return "Custom Scalar from Output…", True
        return "Height · Scalar", True

    monkeypatch.setattr(QInputDialog, "getItem", choose)
    manager._derive()
    derived = next(item for item in manager.recipe.outputs if item.name == "Derived Scalar")
    assert derived.layers[0].source.parameters["target"] == "height"
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: selected.append(args[2]))
    manager.listing.setCurrentRow(
        manager.listing.row(
            next(
                item
                for index in range(manager.listing.count())
                if manager.listing.item(index).data(256) == "height"
                for item in [manager.listing.item(index)]
            )
        )
    )
    manager._delete()
    assert selected and "Normal" in selected[0]


@pytest.mark.parametrize(
    ("helper", "target_label", "operation", "target_id", "mode", "transform"),
    [
        (
            "Normal from Height",
            "Height · Scalar",
            "generator.output_scalar",
            "height",
            "Direct",
            "transform.height_to_normal",
        ),
        (
            "Glossiness from Roughness",
            "Roughness · Scalar",
            "generator.output_scalar",
            "roughness",
            "Direct",
            "transform.invert",
        ),
        (
            "Roughness from Glossiness",
            "Glossiness · Scalar",
            "generator.output_scalar",
            "glossiness-source",
            "Direct",
            "transform.invert",
        ),
        (
            "Opacity from Base Color Alpha",
            "Base Color · Color",
            "generator.output_scalar",
            "base-color",
            "Alpha",
            None,
        ),
        (
            "Height from Base Color Luminance",
            "Base Color · Color",
            "generator.output_scalar",
            "base-color",
            "Luminance",
            None,
        ),
        (
            "Custom Scalar from Output…",
            "Height · Scalar",
            "generator.output_scalar",
            "height",
            "Direct",
            None,
        ),
        (
            "Custom Color from Output…",
            "Roughness · Scalar",
            "generator.output_color",
            "roughness",
            None,
            None,
        ),
    ],
)
def test_derive_output_helpers_build_ordinary_reference_pipelines(
    qtbot, monkeypatch, helper, target_label, operation, target_id, mode, transform
):
    from PySide6.QtWidgets import QInputDialog

    from archetexture.core.material_presets import new_material_output
    from archetexture.ui.output_manager import OutputManagerDialog

    recipe = default_recipe()
    if helper == "Roughness from Glossiness":
        gloss = new_material_output("glossiness", "Glossiness")
        gloss.output_id = "glossiness-source"
        recipe.outputs.append(gloss)
    manager = OutputManagerDialog(recipe, "base-color")
    qtbot.addWidget(manager)
    dialog_choices = iter((helper, target_label))
    monkeypatch.setattr(
        QInputDialog,
        "getItem",
        lambda *_args, **_kwargs: (next(dialog_choices), True),
    )
    manager._derive()
    derived = manager.recipe.output(manager.selected_output_id)
    source = derived.layers[0].source
    assert source.operation_id == operation
    assert source.parameters["target"] == target_id
    if mode is not None:
        assert source.parameters["mode"] == mode
    assert [item.operation_id for item in derived.layers[0].transforms] == (
        [transform] if transform else []
    )
