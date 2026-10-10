from __future__ import annotations

import numpy as np
from PIL import Image
from PySide6.QtCore import QSettings, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QDialog, QDoubleSpinBox, QFileDialog

from archetexture.color.ramp import ColorRamp, ColorStop
from archetexture.core.defaults import default_recipe
from archetexture.render.engine import RenderEngine
from archetexture.render.pixels import rgba_float_to_uint8
from archetexture.ui.export_image_dialog import ExportImageDialog
from archetexture.ui.main_window import MainWindow


def test_vocabulary_widgets_build_save_reload_export_and_undo_stack(qtbot, tmp_path, monkeypatch):
    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(tmp_path))
    recipe = default_recipe()
    recipe.width, recipe.height = 48, 32
    window = MainWindow(recipe)
    window.authoring_mode_combo.setCurrentIndex(1)
    qtbot.addWidget(window)
    window._confirm_discard = lambda: True

    source_selector = window.pipeline_panel.source_selector
    for operation_id in ("generator.turbulence", "generator.fractal_noise"):
        source_selector.setCurrentIndex(source_selector.findData(operation_id))
        assert window._layer().source.operation_id == operation_id

    scale = window.property_editor.findChild(QDoubleSpinBox, "parameter-scale")
    assert scale is not None
    scale.setFocus()
    scale.selectAll()
    QTest.keyClicks(scale, "6.5")
    QTest.keyClick(scale, Qt.Key.Key_Return)
    assert window._layer().source.parameters["scale"] == 6.5

    transform_selector = window.pipeline_panel.transform_selector
    transform_selector.setCurrentIndex(transform_selector.findData("transform.levels"))
    window.pipeline_panel.add_button.click()
    assert window._layer().transforms[-1].operation_id == "transform.levels"
    gamma = window.property_editor.findChild(QDoubleSpinBox, "parameter-gamma")
    assert gamma is not None
    gamma.setValue(1.25)
    assert window._layer().transforms[-1].parameters["gamma"] == 1.25

    window.layers_panel.add_button.click()
    second_layer_id = window._selected_layer_id
    source_selector = window.pipeline_panel.source_selector
    source_selector.setCurrentIndex(source_selector.findData("generator.cellular"))
    assert window._layer().source.operation_id == "generator.cellular"
    window.layers_panel.opacity.setValue(0.3)
    window.layers_panel.blend.setCurrentIndex(window.layers_panel.blend.findData("multiply"))
    window._color_ramp_changed(
        ColorRamp((ColorStop(0, (0.15, 0.02, 0.01, 0.05)), ColorStop(1, (0.95, 0.5, 0.18, 0.8))))
    )
    second = next(
        layer for layer in window.document.recipe.layers if layer.layer_id == second_layer_id
    )
    assert second.opacity == 0.3
    assert second.blend_mode == "multiply"
    assert second.color_ramp is not None

    edited = window.document.recipe
    window.undo_action.trigger()
    window.redo_action.trigger()
    assert window.document.recipe == edited

    qtbot.waitUntil(lambda: window.viewport.rendered_field is not None, timeout=10000)
    project_path = tmp_path / "interactive-stack.archetexture"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *_args: (str(project_path), ""))
    window.save_action.trigger()
    assert project_path.exists()
    saved = window.document.recipe
    window._layer_opacity_changed(second_layer_id, 0.55)
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *_args: (str(project_path), ""))
    assert window.document.dirty
    window.open_action.trigger()
    assert window.document.recipe == saved

    expected = RenderEngine().render(saved, width=48, height=32).rgba_field
    png_path = tmp_path / "interactive-stack.png"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *_args: (str(png_path), ""))
    monkeypatch.setattr(ExportImageDialog, "exec", lambda _dialog: QDialog.DialogCode.Accepted)
    window.export_action.trigger()
    qtbot.waitUntil(lambda: not window.export_coordinator.is_running, timeout=10000)
    with Image.open(png_path) as image:
        np.testing.assert_array_equal(np.asarray(image), rgba_float_to_uint8(expected))

    window.theme_actions["dark"].trigger()
    assert window.theme_actions["dark"].isChecked()
    window.close()
