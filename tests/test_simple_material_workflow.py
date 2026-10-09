from __future__ import annotations

import copy

import pytest
from PySide6.QtCore import QPoint, QPointF, QSettings, Qt
from PySide6.QtGui import QWheelEvent
from PySide6.QtWidgets import QApplication

from archetexture.core.defaults import default_recipe
from archetexture.core.material_starters import MATERIAL_STARTERS, create_material_starter
from archetexture.ui.main_window import MainWindow


@pytest.mark.parametrize("starter", [starter.name for starter in MATERIAL_STARTERS])
def test_starter_opens_with_usable_simple_channels(starter, qtbot):
    window = MainWindow(create_material_starter(starter))
    qtbot.addWidget(window)

    assert window.right_tabs.tabText(0) == "Simple"
    assert window.right_tabs.currentIndex() == 0
    assert window.preview_controls.mesh.currentText() == "UV Sphere"
    assert window.preview_controls.quality.currentText() == "High"
    assert window.preview_controls.mode.currentText() == "Material"
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
        window.right_tabs.setCurrentIndex(index)
        assert window.document.recipe == recipe_before
        assert window.document.history.entries == history_before
        assert window.document.dirty == dirty_before
        assert (
            window._selected_output_id,
            window._selected_layer_id,
            window._selected_instance_id,
        ) == selection
    assert window.output_selector.isHidden()
    window.right_tabs.setCurrentIndex(1)
    assert not window.output_selector.isHidden()
    window.close()


def test_simple_starter_controls_edit_the_existing_control_field(qtbot):
    recipe = create_material_starter("Wood Grain")
    window = MainWindow(recipe)
    qtbot.addWidget(window)
    window._confirm_discard = lambda: True
    initial_index = window.document.history.index
    initial_scale = recipe.control_fields["Scale"].source.parameters["scale"]
    scale = window.simple_material_panel.control_spins["Scale"]

    scale.setValue(initial_scale + 0.25)

    edited = window.document.recipe.control_fields["Scale"].source.parameters["scale"]
    assert edited == pytest.approx(initial_scale + 0.25)
    assert window.document.history.index == initial_index + 1
    assert window.document.dirty
    assert window.right_tabs.currentIndex() == 0
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
