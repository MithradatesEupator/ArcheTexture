from __future__ import annotations

import copy

import pytest
from PySide6.QtCore import QPoint, QPointF, QSettings, Qt, QTimer
from PySide6.QtGui import QWheelEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialogButtonBox, QDoubleSpinBox

from archetexture.color.ramp import ColorRamp, ColorStop
from archetexture.core.defaults import default_recipe
from archetexture.core.material_starters import MATERIAL_STARTERS, create_material_starter
from archetexture.ui.gradient_editor import GradientEditorDialog
from archetexture.ui.main_window import MainWindow


@pytest.mark.parametrize("starter", [starter.name for starter in MATERIAL_STARTERS])
def test_starter_opens_with_usable_simple_channels(starter, qtbot):
    window = MainWindow(create_material_starter(starter))
    qtbot.addWidget(window)

    assert window.authoring_mode_combo.currentText() == "Simple Editor"
    assert window.right_tabs.tabText(0) == "Layer Editor"
    assert not window.simple_material_panel.add_operation_button.isHidden()
    assert window.preview_controls.mesh.currentText() == "UV Sphere"
    assert window.preview_controls.quality.currentText() == "High"
    assert window.preview_controls.mode.currentText() == "Material"
    assert window.simple_material_panel.source_selector.isHidden()
    assert window.simple_material_panel.channel_buttons["base_color"].isEnabled()
    assert window.simple_material_panel.channel_buttons["normal"].isEnabled()
    assert window.simple_material_panel.channel_buttons["roughness"].isEnabled()
    assert window.simple_material_panel.channel_buttons["metallic"].isEnabled()
    assert set(window.simple_material_panel.control_spins) >= {"Scale", "Wear"}
    window.close()


def test_simple_channels_select_existing_outputs_and_modes_preserve_selection(qtbot):
    window = MainWindow(create_material_starter("Rough Stone"))
    qtbot.addWidget(window)
    window._confirm_discard = lambda: True
    recipe_before = copy.deepcopy(window.document.recipe)
    history_before = copy.deepcopy(window.document.history.entries)
    dirty_before = window.document.dirty

    for semantic in ("base_color", "normal", "roughness", "metallic"):
        window.simple_material_panel.channel_buttons[semantic].click()
        assert window._selected_output().semantic == semantic
        assert window.layers_panel.layer_list.count() > 0
        assert window.layers_panel.pipeline_descriptor.text().startswith(
            dict(window.simple_material_panel.CHANNELS)[semantic]
        )

    selection = (
        window._selected_output_id,
        window._selected_layer_id,
        window._selected_instance_id,
    )
    for index in (1, 0, 1, 0):
        window.authoring_mode_combo.setCurrentIndex(index)
        assert window.document.recipe == recipe_before
        assert window.document.history.entries == history_before
        assert window.document.dirty == dirty_before
        assert (
            window._selected_output_id,
            window._selected_layer_id,
            window._selected_instance_id,
        ) == selection
    assert window.output_selector.isHidden()
    window.authoring_mode_combo.setCurrentIndex(1)
    assert not window.output_selector.isHidden()
    window.close()


def test_simple_starter_controls_edit_the_existing_control_field(qtbot):
    recipe = create_material_starter("Wood Grain")
    window = MainWindow(recipe)
    qtbot.addWidget(window)
    window._confirm_discard = lambda: True
    initial_index = window.document.history.index
    initial_scale = recipe.control_fields["Scale"].source.parameters["cells_x"]
    scale = window.simple_material_panel.control_spins["Scale"]
    destroyed = []
    scale.destroyed.connect(lambda *_: destroyed.append(True))

    scale.setValue(initial_scale + 1)

    edited = window.document.recipe.control_fields["Scale"].source.parameters["cells_x"]
    assert edited == pytest.approx(initial_scale + 1)
    assert window.document.history.index == initial_index + 1
    assert window.simple_material_panel.control_spins["Scale"] is scale
    assert not destroyed
    assert window.document.dirty
    assert window.authoring_mode_combo.currentIndex() == 0
    window.close()


def test_default_material_exposes_recipe_backed_simple_controls(qtbot):
    window = MainWindow(default_recipe())
    qtbot.addWidget(window)
    window._confirm_discard = lambda: True
    assert set(window.simple_material_panel.control_spins) >= {"Scale", "Wear"}
    initial_index = window.document.history.index
    initial_scale = window.document.recipe.control_fields["Scale"].source.parameters["cells_x"]
    scale = window.simple_material_panel.control_spins["Scale"]
    destroyed = []
    scale.destroyed.connect(lambda *_: destroyed.append(True))

    scale.setValue(initial_scale + 1)

    assert (
        window.document.recipe.control_fields["Scale"].source.parameters["cells_x"]
        == initial_scale + 1
    )
    assert window.document.history.index == initial_index + 1
    assert window.document.dirty
    assert window.simple_material_panel.control_spins["Scale"] is scale
    assert not destroyed
    window.close()


def test_advanced_parameter_refresh_preserves_active_spinbox(qtbot):
    window = MainWindow(create_material_starter("Wood Grain"))
    qtbot.addWidget(window)
    window._confirm_discard = lambda: True
    window.authoring_mode_combo.setCurrentIndex(1)
    spin = window.property_editor.findChild(QDoubleSpinBox, "parameter-persistence")
    assert spin is not None
    destroyed = []
    spin.destroyed.connect(lambda *_: destroyed.append(True))
    initial = spin.value()
    history_index = window.document.history.index

    spin.setValue(initial + 0.1)

    assert window.property_editor.findChild(QDoubleSpinBox, "parameter-persistence") is spin
    assert not destroyed
    assert window.document.history.index == history_index + 1
    assert window.document.dirty
    window.close()


def test_simple_source_selector_edits_the_selected_layer_source(qtbot):
    window = MainWindow(create_material_starter("Wood Grain"))
    qtbot.addWidget(window)
    window._confirm_discard = lambda: True
    window.authoring_mode_combo.setCurrentIndex(1)
    selector = window.pipeline_panel.source_selector
    index = selector.findData("generator.seamless_cellular")
    assert index >= 0
    selector.setCurrentIndex(index)
    assert window._layer().source.operation_id == "generator.seamless_cellular"
    assert selector.currentData() == window._layer().source.operation_id
    assert window.authoring_mode_combo.currentIndex() == 1
    window.close()


def test_gradient_add_applies_one_coherent_recipe_edit_and_cancel_discards(qtbot, tmp_path):
    window = MainWindow(default_recipe())
    qtbot.addWidget(window)
    window._confirm_discard = lambda: True
    window.resize(1400, 900)
    window.show()
    original = copy.deepcopy(window.document.recipe)
    history_index = window.document.history.index
    selection = (window._selected_output_id, window._selected_layer_id)

    def cancel_dialog():
        dialog = QApplication.activeModalWidget()
        assert isinstance(dialog, GradientEditorDialog)
        assert dialog.angle.isVisible()
        QTest.mouseClick(
            dialog.buttons.button(QDialogButtonBox.StandardButton.Cancel),
            Qt.MouseButton.LeftButton,
        )

    QTimer.singleShot(0, cancel_dialog)
    window._simple_operation_added("gradient")
    assert window.document.recipe == original
    assert window.document.history.index == history_index
    assert (window._selected_output_id, window._selected_layer_id) == selection

    def apply_dialog():
        dialog = QApplication.activeModalWidget()
        assert isinstance(dialog, GradientEditorDialog)
        dialog.kind.setCurrentIndex(dialog.kind.findData("generator.radial_gradient"))
        assert dialog.radius.isVisible()
        dialog.radius.setValue(0.72)
        dialog.opacity.setValue(0.65)
        ramp = ColorRamp(
            (
                ColorStop(0.0, (0.06, 0.12, 0.24, 1.0)),
                ColorStop(0.5, (0.88, 0.2, 0.12, 1.0)),
                ColorStop(1.0, (0.98, 0.8, 0.28, 1.0)),
            )
        )
        dialog.ramp_editor.set_ramp(ramp)
        dialog._ramp_changed(ramp)
        QTest.mouseClick(
            dialog.buttons.button(QDialogButtonBox.StandardButton.Apply),
            Qt.MouseButton.LeftButton,
        )

    before_apply = window.document.history.index
    QTimer.singleShot(0, apply_dialog)
    window._simple_operation_added("gradient")
    result = window.document.recipe
    added = result.output("base-color").layers[-1]
    assert added.name == "Gradient"
    assert added.source.operation_id == "generator.radial_gradient"
    assert added.source.parameters["radius"] == pytest.approx(0.72)
    assert added.opacity == pytest.approx(0.65)
    assert len(added.color_ramp.stops) == 3
    assert window.document.history.index == before_apply + 1
    assert window.document.can_undo
    window.undo_action.trigger()
    assert window.document.recipe == original
    window.redo_action.trigger()
    assert window.document.recipe == result

    project = tmp_path / "gradient.archetexture"
    window.document.save(project)
    from archetexture.core.serialization import load_project

    assert load_project(project) == result
    window.close()


def _wheel_event(local: QPoint, global_position: QPoint) -> QWheelEvent:
    return QWheelEvent(
        QPointF(local),
        QPointF(global_position),
        QPoint(0, 0),
        QPoint(0, 120),
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
        Qt.ScrollPhase.ScrollUpdate,
        False,
    )


def test_camera_zoom_only_changes_for_a_wheel_over_the_3d_viewport(qtbot):
    settings = QSettings(
        QSettings.Format.IniFormat,
        QSettings.Scope.UserScope,
        "ArcheTexture",
        "ArcheTexture",
    )
    settings.clear()
    settings.sync()
    window = MainWindow(default_recipe())
    qtbot.addWidget(window)
    window._confirm_discard = lambda: True
    window.resize(1100, 720)
    window.show()
    window.right_tabs.setCurrentIndex(1)
    window.advanced_tabs.setCurrentWidget(window.preview_controls_scroll)
    window.workspace_mode_combo.setCurrentIndex(1)
    qtbot.wait(80)
    view = window.preview_viewport
    start_distance = view.camera.distance

    combo = window.preview_controls.view
    combo_point = combo.rect().center()
    combo_global = combo.mapToGlobal(combo_point)
    QApplication.sendEvent(combo, _wheel_event(combo_point, combo_global))
    assert view.camera.distance == pytest.approx(start_distance)
    # Selecting a camera view changes orientation only; it never reframes the camera.
    window.preview_controls.view.setCurrentText("Front")
    assert view.camera.distance == pytest.approx(start_distance)

    viewport_point = view.rect().center()
    viewport_global = view.mapToGlobal(viewport_point)
    QApplication.sendEvent(view, _wheel_event(viewport_point, viewport_global))
    assert view.camera.distance < start_distance

    after_zoom = view.camera.distance
    outside_point = QPoint(view.width() + 20, view.height() + 20)
    outside_global = view.mapToGlobal(outside_point)
    view.wheelEvent(_wheel_event(outside_point, outside_global))
    assert view.camera.distance == pytest.approx(after_zoom)
    window.close()


def test_non_camera_edits_leave_camera_and_central_viewport_geometry_unchanged(qtbot, tmp_path):
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
    window = MainWindow(create_material_starter("Rough Stone"))
    qtbot.addWidget(window)
    window.resize(1360, 850)
    window.show()
    qtbot.wait(160)
    qtbot.wait(200)
    splitter = window.centralWidget()
    camera = window.preview_viewport.camera

    def capture():
        return (
            camera.distance,
            camera.fov,
            camera.projection,
            tuple(camera.target),
            camera.yaw,
            camera.pitch,
            window.workspace_stack.size(),
            window.preview_viewport.size(),
            tuple(splitter.sizes()),
        )

    before = capture()
    for semantic in ("base_color", "normal", "roughness", "metallic", "base_color"):
        window.simple_material_panel.channel_buttons[semantic].click()
        window.layers_panel.layer_list.setCurrentRow(0)
        window.authoring_mode_combo.setCurrentIndex(1)
        window.authoring_mode_combo.setCurrentIndex(0)
        qtbot.wait(80)
        assert capture() == before, f"central view or camera changed while editing {semantic}"
    window.close()
