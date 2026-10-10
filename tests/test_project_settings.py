from __future__ import annotations

import copy

import numpy as np
import pytest
from PIL import Image
from PySide6.QtCore import QSettings
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QDialog

from archetexture.core.defaults import default_recipe
from archetexture.core.parameters import ControlFieldBinding, ControlFieldMapping
from archetexture.core.recipe import (
    ControlFieldRecipe,
    LayerRecipe,
    OperationInstance,
    ProjectRecipe,
)
from archetexture.core.registry import REGISTRY
from archetexture.core.sampling import sample_periodic_value_noise_at
from archetexture.core.serialization import load_project, save_project
from archetexture.core.validation import (
    MAX_PROJECT_DIMENSION,
    MAX_PROJECT_SEED,
    ValidationError,
    ensure_valid_recipe,
)
from archetexture.export.image_export import ImageExporter
from archetexture.render.engine import RenderEngine
from archetexture.ui.export_image_dialog import ExportImageDialog
from archetexture.ui.main_window import MainWindow
from archetexture.ui.project_settings_dialog import ProjectSettingsDialog


def _settings(tmp_path):
    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(tmp_path))
    settings = QSettings(
        QSettings.Format.IniFormat,
        QSettings.Scope.UserScope,
        "ArcheTexture",
        "ArcheTexture",
    )
    settings.clear()
    settings.sync()
    return settings


def _window(qtbot, tmp_path):
    _settings(tmp_path)
    window = MainWindow()
    qtbot.addWidget(window)
    window._confirm_discard = lambda: True
    return window


def test_dialog_initializes_from_current_recipe_and_shows_custom_for_rectangles(qtbot):
    recipe = default_recipe()
    recipe.width, recipe.height, recipe.seed = 768, 384, 731
    dialog = ProjectSettingsDialog(recipe)
    qtbot.addWidget(dialog)
    assert dialog.windowTitle() == "Project Settings"
    assert dialog.proposed_settings == (768, 384, 731)
    assert dialog.lock_aspect.isChecked()
    assert dialog.preset_combo.currentText() == "Custom"
    assert recipe.width == 768 and recipe.height == 384 and recipe.seed == 731
    dialog.close()


def test_aspect_lock_updates_opposite_dimension_and_presets(qtbot):
    dialog = ProjectSettingsDialog(default_recipe())
    qtbot.addWidget(dialog)
    dialog.width_spin.setValue(1024)
    assert dialog.proposed_settings[:2] == (1024, 1024)
    dialog.height_spin.setValue(512)
    assert dialog.proposed_settings[:2] == (512, 512)

    dialog.preset_combo.setCurrentText("2048 × 2048")
    assert dialog.proposed_settings[:2] == (2048, 2048)
    assert dialog.preset_combo.currentText() == "2048 × 2048"
    dialog.close()


def test_unlock_allows_arbitrary_dimensions_and_custom_preset(qtbot):
    recipe = default_recipe()
    recipe.width, recipe.height = 800, 400
    dialog = ProjectSettingsDialog(recipe)
    qtbot.addWidget(dialog)
    dialog.lock_aspect.setChecked(False)
    dialog.width_spin.setValue(1000)
    dialog.height_spin.setValue(333)
    assert dialog.proposed_settings[:2] == (1000, 333)
    assert dialog.preset_combo.currentText() == "Custom"
    dialog.preset_combo.setCurrentText("Custom")
    assert dialog.proposed_settings[:2] == (1000, 333)
    dialog.close()


def test_aspect_lock_uses_creation_ratio_and_clamps_dimensions(qtbot):
    recipe = default_recipe()
    recipe.width, recipe.height = 800, 400
    dialog = ProjectSettingsDialog(recipe)
    qtbot.addWidget(dialog)
    dialog.width_spin.setValue(1200)
    assert dialog.proposed_settings[:2] == (1200, 600)
    dialog.height_spin.setValue(1)
    assert dialog.proposed_settings[:2] == (2, 1)
    dialog.height_spin.setValue(MAX_PROJECT_DIMENSION)
    assert dialog.proposed_settings[:2] == (MAX_PROJECT_DIMENSION, MAX_PROJECT_DIMENSION)
    dialog.close()


def test_large_canvas_warning_and_supported_boundaries(qtbot):
    dialog = ProjectSettingsDialog(default_recipe())
    qtbot.addWidget(dialog)
    assert dialog.warning_label.isHidden()
    dialog.width_spin.setValue(4096)
    assert dialog.warning_label.isHidden()
    dialog.width_spin.setValue(4097)
    assert not dialog.warning_label.isHidden()
    assert "memory" in dialog.warning_label.text()
    assert "render time" in dialog.warning_label.text()
    dialog.lock_aspect.setChecked(False)
    dialog.height_spin.setValue(8192)
    assert dialog.proposed_settings[:2] == (4097, 8192)
    assert not dialog.warning_label.isHidden()
    dialog.close()


def test_randomize_seed_changes_only_dialog_local_value(monkeypatch, qtbot):
    recipe = default_recipe()
    dialog = ProjectSettingsDialog(recipe)
    qtbot.addWidget(dialog)
    monkeypatch.setattr("archetexture.ui.project_settings_dialog.random.randint", lambda _a, _b: 31)
    dialog.randomize_button.click()
    assert dialog.seed_spin.value() == 32
    assert dialog.seed_spin.minimum() == 0
    assert dialog.seed_spin.maximum() == MAX_PROJECT_SEED
    assert recipe.seed == 31
    dialog.close()


def test_project_settings_menu_command_and_shortcut(qtbot, tmp_path):
    window = _window(qtbot, tmp_path)
    assert window.project_settings_action.text() == "Project Settings…"
    assert window.project_settings_action.shortcut().toString() == "Ctrl+Shift+P"
    window.close()


def test_cancel_has_no_recipe_history_dirty_status_or_render_effect(monkeypatch, qtbot, tmp_path):
    window = _window(qtbot, tmp_path)
    recipe_before = window.document.recipe
    index_before = window.document.history.index
    entries_before = len(window.document.history.entries)
    dirty_before = window.document.dirty
    request_before = window.render_coordinator.request_counter

    def cancel(dialog):
        dialog.width_spin.setValue(1024)
        dialog.seed_spin.setValue(987)
        dialog.randomize_button.click()
        return QDialog.DialogCode.Rejected

    monkeypatch.setattr(ProjectSettingsDialog, "exec", cancel)
    assert not window._show_project_settings()
    assert window.document.recipe == recipe_before
    assert window.document.history.index == index_before
    assert len(window.document.history.entries) == entries_before
    assert window.document.dirty is dirty_before
    assert window.render_coordinator.request_counter == request_before
    assert window.project_status_label.text() == "512 × 512 · Seed 31"
    window.close()


def test_accept_commits_three_settings_once_and_undo_redo_updates_status_and_preview(
    monkeypatch, qtbot, tmp_path
):
    window = _window(qtbot, tmp_path)
    saved_path = tmp_path / "saved-before.archetexture"
    assert window.save_project(saved_path)
    layers_before = copy.deepcopy(window.document.recipe.layers)
    ramp_stops_before = copy.deepcopy(window.document.recipe.layers[0].color_ramp.stops)
    history_index = window.document.history.index
    render_requests = window.render_coordinator.request_counter

    def accept(dialog):
        dialog.lock_aspect.setChecked(False)
        dialog.width_spin.setValue(96)
        dialog.height_spin.setValue(48)
        dialog.seed_spin.setValue(72)
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(ProjectSettingsDialog, "exec", accept)
    assert window._show_project_settings()
    recipe = window.document.recipe
    assert (recipe.width, recipe.height, recipe.seed) == (96, 48, 72)
    assert window.document.history.index == history_index + 1
    assert window.render_coordinator.request_counter == render_requests + 1
    assert window.document.dirty
    assert window.project_status_label.text() == "96 × 48 · Seed 72"
    assert recipe.layers == layers_before
    assert recipe.layers[0].color_ramp.stops == ramp_stops_before
    qtbot.waitUntil(
        lambda: (
            window.viewport.rendered_field is not None
            and window.viewport.rendered_field.shape == (48, 96, 4)
        ),
        timeout=10000,
    )

    window.undo()
    assert (
        window.document.recipe.width,
        window.document.recipe.height,
        window.document.recipe.seed,
    ) == (
        512,
        512,
        31,
    )
    assert not window.document.dirty
    assert window.project_status_label.text() == "512 × 512 · Seed 31"
    window.redo()
    assert (
        window.document.recipe.width,
        window.document.recipe.height,
        window.document.recipe.seed,
    ) == (
        96,
        48,
        72,
    )
    assert window.document.dirty
    assert window.project_status_label.text() == "96 × 48 · Seed 72"
    window.close()


@pytest.mark.parametrize("width,height", [(19, 19), (23, 13), (13, 23)])
def test_landscape_and_portrait_render_dimensions(width, height):
    recipe = default_recipe()
    recipe.width, recipe.height = width, height
    result = RenderEngine().render(recipe)
    assert result.rgba_field.shape == (height, width, 4)


def test_control_field_modulation_evaluates_at_resized_dimensions():
    recipe = default_recipe()
    recipe.width, recipe.height = 37, 19
    recipe.control_fields["resize-mask"] = ControlFieldRecipe(
        OperationInstance("resize-mask-source", "generator.constant", 1, parameters={"value": 0.5})
    )
    source_definition = REGISTRY.get("generator.fractal_noise")
    recipe.layers[0].source = OperationInstance(
        "modulated-source",
        source_definition.identifier,
        source_definition.version,
        parameters={spec.identifier: spec.default for spec in source_definition.parameter_specs},
    )
    recipe.layers[0].source.parameters["scale"] = ControlFieldBinding(
        "resize-mask", ControlFieldMapping(output_min=1.0, output_max=4.0)
    )
    ensure_valid_recipe(recipe)
    result = RenderEngine().render(recipe)
    assert result.rgba_field.shape == (19, 37, 4)


def test_seamless_generator_keeps_lattice_period_when_project_resolution_changes():
    recipe = ProjectRecipe(
        width=512,
        height=512,
        seed=31,
        layers=[
            LayerRecipe(
                "seamless-layer",
                "Layer 1",
                OperationInstance(
                    "seamless-source",
                    "generator.seamless_value_noise",
                    1,
                    parameters={
                        "seed": 5,
                        "cells_x": 8,
                        "cells_y": 6,
                        "offset_x": 0.0,
                        "offset_y": 0.0,
                    },
                ),
            ),
        ],
    )
    low = RenderEngine().render(recipe, width=32, height=24).scalar_field
    recipe.width, recipe.height = 64, 48
    high = RenderEngine().render(recipe).scalar_field
    assert low.shape == (24, 32)
    assert high.shape == (48, 64)
    assert recipe.layers[0].source.parameters["cells_x"] == 8
    assert recipe.layers[0].source.parameters["cells_y"] == 6
    np.testing.assert_allclose(
        sample_periodic_value_noise_at(np.array([-0.25, 3.5]), np.array([1.25, 5.5]), 11, 8, 6),
        sample_periodic_value_noise_at(np.array([7.75, 11.5]), np.array([7.25, 11.5]), 11, 8, 6),
    )


def test_global_seed_changes_variant_without_replacing_local_seed():
    recipe = default_recipe()
    recipe.layers = [
        copy.deepcopy(recipe.layers[0]),
    ]
    recipe.layers[0].source = OperationInstance(
        "local-seeded-noise",
        "generator.white_noise",
        1,
        parameters={"seed": 1234},
    )
    first = RenderEngine().render(recipe, width=24, height=16).scalar_field
    again = RenderEngine().render(recipe, width=24, height=16).scalar_field
    np.testing.assert_array_equal(first, again)
    recipe.seed = 72
    variant = RenderEngine().render(recipe, width=24, height=16).scalar_field
    assert recipe.layers[0].source.parameters["seed"] == 1234
    assert not np.array_equal(first, variant)


def test_export_defaults_to_project_dimensions_and_override_does_not_mutate_recipe(qtbot, tmp_path):
    recipe = default_recipe()
    recipe.width, recipe.height = 35, 21
    dialog = ExportImageDialog(recipe)
    qtbot.addWidget(dialog)
    assert dialog.dimensions == (35, 21)
    dialog.width_spin.setValue(42)
    dialog.height_spin.setValue(28)
    destination = tmp_path / "override.png"
    ImageExporter().export_png(recipe, destination, width=42, height=28)
    with Image.open(destination) as image:
        assert image.size == (42, 28)
    assert (recipe.width, recipe.height) == (35, 21)
    dialog.close()


def test_save_reopen_preserves_settings_and_rendered_output(tmp_path):
    recipe = default_recipe()
    recipe.width, recipe.height, recipe.seed = 29, 17, 902
    expected = RenderEngine().render(recipe).rgba_field
    path = tmp_path / "project-settings.archetexture"
    save_project(recipe, path)
    loaded = load_project(path)
    assert (loaded.width, loaded.height, loaded.seed) == (29, 17, 902)
    np.testing.assert_array_equal(RenderEngine().render(loaded).rgba_field, expected)


def test_new_and_open_refresh_project_status(qtbot, tmp_path):
    window = _window(qtbot, tmp_path)
    custom = default_recipe()
    custom.width, custom.height, custom.seed = 44, 27, 651
    path = tmp_path / "custom.archetexture"
    save_project(custom, path)
    assert window.new_document()
    assert window.project_status_label.text() == "512 × 512 · Seed 31"
    assert window.open_project(path)
    assert window.project_status_label.text() == "44 × 27 · Seed 651"
    window.close()


@pytest.mark.parametrize(
    "name,value",
    (
        ("width", 0),
        ("width", 8193),
        ("width", True),
        ("height", 8193),
        ("height", False),
        ("seed", -1),
        ("seed", MAX_PROJECT_SEED + 1),
        ("seed", True),
    ),
)
def test_invalid_project_settings_are_rejected(name, value):
    recipe = default_recipe()
    setattr(recipe, name, value)
    with pytest.raises(ValidationError):
        ensure_valid_recipe(recipe)


def _luminance(widget):
    image = widget.grab().toImage().convertToFormat(QImage.Format.Format_RGBA8888)
    pixels = np.frombuffer(image.bits(), dtype=np.uint8, count=image.sizeInBytes())
    pixels = pixels.reshape(image.height(), image.bytesPerLine())[:, : image.width() * 4]
    pixels = pixels.reshape(image.height(), image.width(), 4)
    return 0.2126 * pixels[..., 0] + 0.7152 * pixels[..., 1] + 0.0722 * pixels[..., 2]


def test_dialog_respects_dark_light_and_system_theme(qtbot, tmp_path):
    window = _window(qtbot, tmp_path)
    window.show()
    for mode in ("dark", "light", "system"):
        window._set_theme(mode, persist=False)
        dialog = ProjectSettingsDialog(window.document.recipe, window)
        qtbot.addWidget(dialog)
        dialog.show()
        qtbot.wait(20)
        image_luminance = _luminance(dialog)
        if mode == "dark":
            assert np.mean(image_luminance < 150) > 0.6
            assert np.mean(_luminance(dialog.width_spin) < 150) > 0.5
            dialog.width_spin.setValue(5000)
            qtbot.wait(10)
            assert "memory" in dialog.warning_label.text()
            assert np.mean(_luminance(dialog.warning_label) < 200) > 0.5
        elif mode == "light":
            assert np.mean(image_luminance > 185) > 0.6
        dialog.close()
    window.close()


def test_project_resize_does_not_reset_viewport_mode(qtbot, tmp_path, monkeypatch):
    window = _window(qtbot, tmp_path)
    window.viewport_mode_combo.setCurrentIndex(window.viewport_mode_combo.findData("tile_3x3"))

    def accept(dialog):
        dialog.lock_aspect.setChecked(False)
        dialog.width_spin.setValue(48)
        dialog.height_spin.setValue(24)
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(ProjectSettingsDialog, "exec", accept)
    assert window._show_project_settings()
    assert window.viewport_mode_combo.currentData() == "tile_3x3"
    assert window.viewport.display_mode == "tile_3x3"
    window.close()
