from __future__ import annotations

import json

import numpy as np
import pytest
from PIL import Image

from archetexture.core.defaults import default_recipe
from archetexture.core.material_presets import (
    MATERIAL_PRESETS,
    apply_material_preset,
    duplicate_material_output,
)
from archetexture.core.outputs import OUTPUT_CATEGORIES, OUTPUT_SEMANTICS
from archetexture.core.recipe import (
    LayerRecipe,
    MaterialOutputRecipe,
    OperationInstance,
    ProjectRecipe,
)
from archetexture.core.serialization import (
    _encode_layer,
    load_project,
    migrate_recipe,
    save_project,
)
from archetexture.core.validation import ValidationError, ensure_valid_recipe
from archetexture.export.texture_set import (
    OutputExportSpec,
    PackedChannelSpec,
    PackedMapSpec,
    TextureSetExporter,
    TextureSetExportError,
    TextureSetExportPlan,
    packed_preset,
)
from archetexture.render.engine import RenderEngine, composite_scalar


def _scalar_recipe(value: float = 0.75, *, semantic: str = "custom_scalar") -> ProjectRecipe:
    return ProjectRecipe(
        width=8,
        height=6,
        outputs=[
            MaterialOutputRecipe(
                "scalar-output",
                "Scalar Output",
                semantic,
                "scalar",
                [
                    LayerRecipe(
                        "scalar-layer",
                        "Scalar Layer",
                        OperationInstance(
                            "scalar-source", "generator.constant", 1, parameters={"value": value}
                        ),
                    )
                ],
            )
        ],
    )


def test_semantic_registry_is_complete_grouped_and_has_safe_suffixes():
    expected = {
        "base_color",
        "roughness",
        "metallic",
        "normal",
        "height",
        "ambient_occlusion",
        "opacity",
        "emissive",
        "diffuse",
        "specular_color",
        "specular_level",
        "glossiness",
        "displacement",
        "transmission",
        "thickness",
        "clearcoat",
        "clearcoat_roughness",
        "sheen",
        "sheen_roughness",
        "anisotropy",
        "anisotropy_rotation",
        "subsurface",
        "curvature",
        "cavity",
        "mask",
        "data",
        "custom_color",
        "custom_scalar",
    }
    assert set(OUTPUT_SEMANTICS) == expected
    assert len(OUTPUT_SEMANTICS) == len({item.identifier for item in OUTPUT_SEMANTICS.values()})
    assert OUTPUT_CATEGORIES == (
        "Standard PBR",
        "Specular / Legacy",
        "Advanced",
        "Utility",
        "Custom",
    )
    assert all(
        item.export_suffix and "/" not in item.export_suffix for item in OUTPUT_SEMANTICS.values()
    )


def test_new_project_uses_lightweight_six_output_default():
    recipe = default_recipe()
    assert [item.semantic for item in recipe.outputs] == [
        "base_color",
        "roughness",
        "metallic",
        "normal",
        "height",
        "ambient_occlusion",
    ]
    assert [len(item.layers) for item in recipe.outputs] == [2, 1, 1, 1, 1, 1]
    ensure_valid_recipe(recipe)


def test_default_outputs_render_as_declared_channels():
    recipe = default_recipe()
    engine = RenderEngine()
    for output in recipe.outputs:
        result = engine.render_output(recipe, output.output_id, width=12, height=10)
        assert result.value_type == output.value_type
        assert result.rgba_field.shape == (10, 12, 4)
        if output.value_type == "scalar":
            assert result.scalar_field is not None
            assert result.scalar_field.shape == (10, 12)
        else:
            assert result.scalar_field is None


def test_schema_v5_round_trip_uses_outputs_as_the_canonical_structure(tmp_path):
    recipe = default_recipe()
    path = tmp_path / "material.archetexture"
    save_project(recipe, path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["schema_version"] == 5
    assert "outputs" in payload and "layers" not in payload
    restored = load_project(path)
    assert restored == recipe


def test_v4_migration_preserves_rendered_pixels_as_custom_color(tmp_path):
    recipe = default_recipe()
    engine = RenderEngine()
    legacy = ProjectRecipe(
        width=recipe.width, height=recipe.height, layers=recipe.outputs[0].layers
    )
    expected = engine.render(legacy).rgba_field
    modern = json.loads(
        json.dumps(
            {
                "schema_version": 4,
                "width": legacy.width,
                "height": legacy.height,
                "seed": legacy.seed,
                "layers": [_encode_layer(layer) for layer in legacy.layers],
                "control_fields": {},
            }
        )
    )
    migrated = migrate_recipe(modern)
    assert migrated.outputs[0].semantic == "custom_color"
    assert migrated.outputs[0].value_type == "color"
    np.testing.assert_array_equal(engine.render(migrated).rgba_field, expected)
    path = tmp_path / "legacy.archetexture"
    path.write_text(json.dumps(modern), encoding="utf-8")
    assert load_project(path).outputs[0].semantic == "custom_color"


@pytest.mark.parametrize("preset", tuple(MATERIAL_PRESETS))
def test_material_presets_add_outputs_without_removing_existing(preset):
    recipe = _scalar_recipe()
    before = recipe.outputs[0]
    added = apply_material_preset(recipe, preset)
    assert recipe.outputs[0] == before
    assert len(added) == len(MATERIAL_PRESETS[preset])
    apply_material_preset(recipe, preset)
    assert len(recipe.outputs) == 1 + len(added)


def test_duplicate_output_ids_and_empty_material_are_rejected():
    recipe = _scalar_recipe()
    recipe.outputs.append(recipe.outputs[0])
    with pytest.raises(ValidationError, match="identifiers must be unique"):
        ensure_valid_recipe(recipe)
    empty = ProjectRecipe(outputs=[])
    with pytest.raises(ValidationError, match="at least one material output"):
        ensure_valid_recipe(empty)


def test_scalar_render_retains_authoritative_field_and_grayscale_preview():
    recipe = _scalar_recipe(0.375)
    result = RenderEngine().render_output(recipe, "scalar-output")
    assert result.scalar_field.dtype == np.float32
    np.testing.assert_allclose(result.scalar_field, 0.375)
    np.testing.assert_array_equal(result.rgba_field[..., 0], result.scalar_field)
    np.testing.assert_array_equal(result.rgba_field[..., 1], result.scalar_field)
    np.testing.assert_array_equal(result.rgba_field[..., 3], 1.0)


@pytest.mark.parametrize(
    ("mode", "expected"),
    (("normal", 0.575), ("multiply", 0.475), ("screen", 0.6), ("add", 0.7)),
)
def test_scalar_blend_modes_apply_float32_opacity_and_mask(mode, expected):
    backdrop = np.full((2, 2), 0.5, dtype=np.float32)
    source = np.full((2, 2), 0.8, dtype=np.float32)
    mask = np.full((2, 2), 0.5, dtype=np.float32)
    result = composite_scalar(backdrop, source, 0.5, mode, mask)
    assert result.dtype == np.float32
    np.testing.assert_allclose(result, expected, atol=1e-6)


def test_output_switch_reuses_layer_cache_and_unrelated_outputs_are_isolated():
    recipe = default_recipe()
    engine = RenderEngine()
    base = engine.render_output(recipe, "base-color")
    roughness = engine.render_output(recipe, "roughness")
    again = engine.render_output(recipe, "base-color")
    np.testing.assert_array_equal(base.rgba_field, again.rgba_field)
    assert roughness.scalar_field is not None
    assert engine.session.stats["layers"]["hits"] >= 2
    assert len(recipe.outputs) == 6


def test_editing_one_output_preserves_other_output_cache_entries():
    recipe = default_recipe()
    engine = RenderEngine()
    engine.render_output(recipe, "base-color")
    engine.render_output(recipe, "metallic")
    before = engine.session.stats["layers"]
    recipe.output("metallic").layers[0].source.parameters["value"] = 0.9
    engine.render_output(recipe, "metallic")
    engine.render_output(recipe, "base-color")
    after = engine.session.stats["layers"]
    assert after["misses"] - before["misses"] == 1
    assert after["hits"] - before["hits"] == 2


def test_shared_control_field_invalidates_only_dependent_outputs():
    from archetexture.core.parameters import ControlFieldBinding
    from archetexture.core.recipe import ControlFieldRecipe

    recipe = default_recipe()
    recipe.control_fields["shared"] = ControlFieldRecipe(
        OperationInstance("shared-source", "generator.constant", 1, parameters={"value": 0.25})
    )
    for identifier in ("roughness", "metallic"):
        recipe.output(identifier).layers[0].source.parameters["value"] = ControlFieldBinding(
            "shared"
        )
    ensure_valid_recipe(recipe)
    engine = RenderEngine()
    engine.render_output(recipe, "base-color")
    engine.render_output(recipe, "roughness")
    engine.render_output(recipe, "metallic")
    before = engine.session.stats["layers"]
    recipe.control_fields["shared"].source.parameters["value"] = 0.75
    engine.render_output(recipe, "roughness")
    engine.render_output(recipe, "metallic")
    engine.render_output(recipe, "base-color")
    after = engine.session.stats["layers"]
    assert after["misses"] - before["misses"] == 2
    assert after["hits"] - before["hits"] == 2


def test_cross_output_layer_clone_uses_fresh_ids_and_keeps_bindings():
    from archetexture.core.parameters import ControlFieldBinding
    from archetexture.ui.main_window import MainWindow

    layer = default_recipe().output("base-color").layers[0]
    layer.mask = ControlFieldBinding("material-seed")
    cloned = MainWindow._clone_layer(layer)
    assert cloned is not layer
    assert cloned.layer_id != layer.layer_id
    assert cloned.source.instance_id != layer.source.instance_id
    assert cloned.mask == ControlFieldBinding("material-seed")


def test_scalar_export_supports_8_bit_and_16_bit_png(tmp_path):
    recipe = _scalar_recipe(0.5)
    exporter = TextureSetExporter()
    for depth, dtype in ((8, np.uint8), (16, np.uint16)):
        plan = TextureSetExportPlan(
            str(tmp_path),
            f"map{depth}",
            8,
            6,
            (OutputExportSpec("scalar-output", "Height", True, depth),),
        )
        (exported,) = exporter.export(recipe, plan)
        pixels = np.asarray(Image.open(exported))
        assert pixels.dtype == dtype
        assert np.all(pixels == round(0.5 * ((1 << depth) - 1)))


def test_orm_packing_and_custom_inversion_match_scalar_sources(tmp_path):
    recipe = default_recipe()
    exporter = TextureSetExporter()
    orm = packed_preset("ORM", recipe)
    plan = TextureSetExportPlan(str(tmp_path), "mat", 8, 6, (), (orm,))
    (path,) = exporter.export(recipe, plan)
    pixels = np.asarray(Image.open(path))
    np.testing.assert_array_equal(pixels[0, 0], [255, 128, 0, 255])
    custom = PackedMapSpec(
        "Custom",
        {
            "R": PackedChannelSpec("roughness", invert=True),
            "G": PackedChannelSpec(constant=0),
            "B": PackedChannelSpec(constant=0),
            "A": PackedChannelSpec(constant=1),
        },
    )
    custom_plan = TextureSetExportPlan(str(tmp_path), "mat2", 8, 6, (), (custom,))
    (custom_path,) = exporter.export(recipe, custom_plan)
    np.testing.assert_array_equal(np.asarray(Image.open(custom_path))[0, 0], [128, 0, 0, 255])


def test_packing_preflight_rejects_missing_semantics_and_filename_collisions(tmp_path):
    recipe = _scalar_recipe()
    with pytest.raises(TextureSetExportError, match="requires a ambient occlusion"):
        packed_preset("ORM", recipe)
    pack = PackedMapSpec("Same", {key: PackedChannelSpec(constant=0) for key in "RGBA"})
    plan = TextureSetExportPlan(
        str(tmp_path),
        "mat",
        8,
        6,
        (OutputExportSpec("scalar-output", "Same"),),
        (pack,),
    )
    with pytest.raises(TextureSetExportError, match="Filename collision"):
        TextureSetExporter().preflight(recipe, plan)


def test_export_plan_is_deterministically_serializable():
    plan = TextureSetExportPlan(
        "out",
        "material",
        64,
        32,
        (OutputExportSpec("roughness", "Roughness", True, 16),),
        (PackedMapSpec("ORM", {key: PackedChannelSpec(constant=1) for key in "RGBA"}),),
    )
    encoded = json.dumps(plan.to_dict(), sort_keys=True)
    assert json.loads(encoded)["width"] == 64


def test_output_selector_switches_to_rendered_scalar_preview(qtbot):
    from archetexture.ui.main_window import build_main_window

    window = build_main_window()
    qtbot.addWidget(window)
    window.show()

    def published():
        return (
            window._latest_displayed_request_id == window.render_coordinator.latest_request_id
            and not window.render_coordinator.is_running
            and window.render_coordinator.pending_request is None
        )

    qtbot.waitUntil(published, timeout=10000)
    index = window.output_selector.findData("roughness")
    window.output_selector.setCurrentIndex(index)
    qtbot.waitUntil(published, timeout=10000)
    assert window._latest_render_result.scalar_field is not None
    image = window.viewport.rendered_field
    np.testing.assert_array_equal(image[..., 0], image[..., 1])
    np.testing.assert_array_equal(image[..., 1], image[..., 2])
    assert window.seamlessness_label.text().startswith("Roughness · Scalar")
    window.close()


def test_schema_v3_migration_uses_unknown_custom_color_semantics():
    recipe = default_recipe()
    legacy = {
        "schema_version": 3,
        "width": recipe.width,
        "height": recipe.height,
        "seed": recipe.seed,
        "layers": [_encode_layer(layer) for layer in recipe.outputs[0].layers],
        "control_fields": {},
    }
    migrated = migrate_recipe(legacy)
    assert [(item.semantic, item.value_type) for item in migrated.outputs] == [
        ("custom_color", "color")
    ]
    np.testing.assert_array_equal(
        RenderEngine().render(recipe).rgba_field,
        RenderEngine().render(migrated).rgba_field,
    )


def test_output_type_validation_rejects_mismatch_and_invalid_layer_chains():
    recipe = _scalar_recipe()
    recipe.outputs[0].semantic = "base_color"
    with pytest.raises(ValidationError, match="does not match semantic"):
        ensure_valid_recipe(recipe)

    recipe.outputs[0].semantic = "normal"
    recipe.outputs[0].value_type = "normal"
    with pytest.raises(ValidationError):
        ensure_valid_recipe(recipe)


def test_duplicate_output_keeps_identity_independent_and_copies_bindings():
    output = default_recipe().outputs[0]
    duplicate = duplicate_material_output(output)
    assert duplicate.output_id != output.output_id
    assert duplicate.layers[0].layer_id != output.layers[0].layer_id
    assert duplicate.layers[0].source.instance_id != output.layers[0].source.instance_id
    assert duplicate.layers[0].source.parameters == output.layers[0].source.parameters
    assert duplicate.layers[0] is not output.layers[0]


@pytest.mark.parametrize(
    ("preset", "expected"),
    (
        ("RMA", [128, 0, 255, 255]),
        ("MRA", [0, 128, 255, 255]),
        ("Unity HDRP-like Mask Map", [0, 255, 255, 128]),
    ),
)
def test_packing_presets_produce_expected_channel_order(tmp_path, preset, expected):
    recipe = default_recipe()
    packed = packed_preset(preset, recipe)
    plan = TextureSetExportPlan(str(tmp_path), "preset", 8, 6, (), (packed,))
    (path,) = TextureSetExporter().export(recipe, plan)
    np.testing.assert_array_equal(np.asarray(Image.open(path))[0, 0], expected)


def test_separate_export_uses_suffix_and_pixels_match_direct_render(tmp_path):
    recipe = default_recipe()
    plan = TextureSetExportPlan(
        str(tmp_path),
        "Stone",
        8,
        6,
        (
            OutputExportSpec("base-color", "BaseColor"),
            OutputExportSpec("roughness", "Roughness", bit_depth=16),
        ),
    )
    paths = TextureSetExporter().export(recipe, plan)
    assert [path.name for path in paths] == ["Stone_BaseColor.png", "Stone_Roughness.png"]
    expected = RenderEngine().render_output(recipe, "base-color", width=8, height=6)
    np.testing.assert_array_equal(
        np.asarray(Image.open(paths[0])),
        np.rint(expected.rgba_field * 255).astype(np.uint8),
    )


def test_output_manager_adds_duplicate_and_applies_preset_with_real_widgets(qtbot):
    from archetexture.ui.output_manager import AddOutputDialog, OutputManagerDialog

    recipe = default_recipe()
    manager = OutputManagerDialog(recipe, "base-color")
    qtbot.addWidget(manager)
    original_count = len(manager.recipe.outputs)
    manager._duplicate()
    duplicate = manager.recipe.outputs[1]
    assert len(manager.recipe.outputs) == original_count + 1
    assert duplicate.output_id != manager.recipe.outputs[0].output_id
    manager.preset_combo.setCurrentText("Metallic / Roughness PBR")
    manager._apply_preset()
    assert {"base_color", "roughness", "metallic", "normal"}.issubset(
        {output.semantic for output in manager.recipe.outputs}
    )

    add = AddOutputDialog(manager)
    qtbot.addWidget(add)
    assert [add.tabs.tabText(index) for index in range(add.tabs.count())] == list(OUTPUT_CATEGORIES)
    add.tabs.setCurrentIndex(add.tabs.indexOf(add.semantic_lists["Custom"]))
    listing = add.semantic_lists["Custom"]
    custom = next(
        listing.item(index)
        for index in range(listing.count())
        if listing.item(index).data(256) == "custom_scalar"
    )
    listing.setCurrentItem(custom)
    add.name_edit.setText("Dust Mask")
    assert add.selection == ("custom_scalar", "Dust Mask")


def test_texture_set_dialog_builds_scalar_depth_aware_export_plan(qtbot, tmp_path):
    from archetexture.ui.export_texture_set_dialog import ExportTextureSetDialog

    recipe = default_recipe()
    dialog = ExportTextureSetDialog(recipe)
    qtbot.addWidget(dialog)
    dialog.destination.setText(str(tmp_path))
    dialog.filename_base.setText("stone")
    dialog.scalar_depth.setCurrentIndex(dialog.scalar_depth.findData(16))
    dialog.orm.setChecked(True)
    plan = dialog.plan
    assert len(plan.outputs) == len(recipe.outputs)
    assert all(
        spec.bit_depth == (16 if recipe.output(spec.output_id).value_type == "scalar" else 8)
        for spec in plan.outputs
    )
    assert len(plan.packed_maps) == 1
    assert len(TextureSetExporter().preflight(recipe, plan)) == len(recipe.outputs) + 1
