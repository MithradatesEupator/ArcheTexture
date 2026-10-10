from __future__ import annotations

from PySide6.QtCore import QSettings, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDoubleSpinBox

from archetexture.ui.main_window import MainWindow


def test_default_workspace_layers_history_selected_pipeline_and_direct_parameter(qtbot):
    window = MainWindow()
    window.authoring_mode_combo.setCurrentIndex(1)
    qtbot.addWidget(window)
    window._confirm_discard = lambda: True
    assert len(window.document.recipe.layers) >= 2
    assert window.document.recipe.layers[0].enabled
    assert window.document.recipe.layers[1].enabled

    original_count = len(window.document.recipe.layers)
    window._add_layer()
    added_id = window._selected_layer_id
    assert len(window.document.recipe.layers) == original_count + 1
    window._duplicate_layer(added_id)
    duplicate_id = window._selected_layer_id
    duplicate = window._layer()
    original = next(layer for layer in window.document.recipe.layers if layer.layer_id == added_id)
    assert duplicate.layer_id != original.layer_id
    assert duplicate.source.instance_id != original.source.instance_id
    duplicate.source.parameters["value"] = 0.9
    assert original.source.parameters["value"] == 0.5
    window._layer_opacity_changed(duplicate_id, 0.4)
    window.undo_action.trigger()
    assert window._layer().opacity == 1.0
    window.redo_action.trigger()
    assert window._layer().opacity == 0.4
    window.undo()
    window.undo()
    assert len(window.document.recipe.layers) == original_count + 1
    window.redo()
    assert len(window.document.recipe.layers) == original_count + 2

    layer_id = window.document.recipe.layers[1].layer_id
    window._select_layer(layer_id)
    window._source_changed("generator.linear_gradient")
    assert window._layer().source.operation_id == "generator.linear_gradient"
    assert window.pipeline_panel.source_selector.currentData() == "generator.linear_gradient"
    window._select_instance(window._layer().source.instance_id)
    numeric = window.property_editor.findChild(QDoubleSpinBox, "parameter-angle")
    assert numeric is not None
    numeric.setFocus()
    numeric.selectAll()
    QTest.keyClicks(numeric, "37")
    QTest.keyClick(numeric, Qt.Key.Key_Return)
    assert window._layer().source.parameters["angle"] == 37.0
    window._transform_added("transform.invert")
    assert window._layer().transforms[-1].operation_id == "transform.invert"
    assert window.document.can_undo
    window.close()


def test_theme_actions_apply_palette_and_persist(qtbot, tmp_path, monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(tmp_path))
    window = MainWindow()
    window.authoring_mode_combo.setCurrentIndex(1)
    qtbot.addWidget(window)
    window._confirm_discard = lambda: True
    window.theme_actions["dark"].trigger()
    assert (
        QApplication.instance()
        .palette()
        .color(QApplication.instance().palette().ColorRole.Window)
        .lightness()
        < 128
    )
    settings = QSettings(
        QSettings.Format.IniFormat,
        QSettings.Scope.UserScope,
        "ArcheTexture",
        "ArcheTexture",
    )
    assert settings.value("appearance/theme") == "dark"
    window.theme_actions["light"].trigger()
    assert window.theme_actions["light"].isChecked()
    window.theme_actions["system"].trigger()
    assert window.theme_actions["system"].isChecked()
    assert settings.value("appearance/theme") == "system"
    window.close()
    restarted = MainWindow()
    restarted.authoring_mode_combo.setCurrentIndex(1)
    qtbot.addWidget(restarted)
    assert restarted.theme_actions["system"].isChecked()
    restarted._confirm_discard = lambda: True
    restarted.close()


def test_rename_visibility_reorder_opacity_and_blend_edits_undo_redo(qtbot):
    window = MainWindow()
    window.authoring_mode_combo.setCurrentIndex(1)
    qtbot.addWidget(window)
    window._confirm_discard = lambda: True
    recipe = window.document.recipe
    first_id, second_id = (layer.layer_id for layer in recipe.layers[:2])
    original_order = [layer.layer_id for layer in recipe.layers]

    window._rename_layer(first_id, "Foundation")
    window._layer_enabled(first_id, False)
    window._layer_opacity_changed(second_id, 0.27)
    window._layer_blend_changed(second_id, "multiply")
    window._layer_moved(second_id, 0)
    edited = window.document.recipe
    assert edited.layers[0].layer_id == second_id
    assert edited.layers[1].name == "Foundation"
    assert not edited.layers[1].enabled
    assert edited.layers[0].opacity == 0.27
    assert edited.layers[0].blend_mode == "multiply"

    for _ in range(5):
        window.undo()
    restored = window.document.recipe
    assert [layer.layer_id for layer in restored.layers] == original_order
    assert restored.layers[0].enabled
    assert restored.layers[1].opacity == 0.3
    for _ in range(5):
        window.redo()
    assert window.document.recipe == edited
    window.close()


def test_layer_removal_is_undoable(qtbot):
    window = MainWindow()
    window.authoring_mode_combo.setCurrentIndex(1)
    qtbot.addWidget(window)
    window._confirm_discard = lambda: True
    layers = window.document.recipe.layers
    removed_id = layers[0].layer_id
    window._remove_layer(removed_id)
    assert len(window.document.recipe.layers) == 1
    assert window.document.recipe.layers[0].layer_id != removed_id
    window.undo()
    assert len(window.document.recipe.layers) == 2
    assert window.document.recipe.layers[0].layer_id == removed_id
    window.redo()
    assert len(window.document.recipe.layers) == 1
    window.close()


def test_layer_identity_context_and_parameters_stay_visible(qtbot):
    window = MainWindow()
    qtbot.addWidget(window)
    window._confirm_discard = lambda: True
    layer_id = window._selected_layer_id
    layer = window._layer()
    item = window.layers_panel.layer_list.currentItem()
    assert window.layers_panel.layer_list.EditTrigger.DoubleClicked
    assert window.layers_panel.layer_list.EditTrigger.EditKeyPressed
    assert window.layers_panel.pipeline_descriptor.text() == (
        f"Color — {window._layer_descriptor(layer)}"
    )
    assert layer.name in window.color_ramp_editor.title_label.text()
    assert window.property_editor.isVisible() or not window.property_editor.isHidden()
    assert layer.name in window.context_breadcrumb.text()

    window._rename_layer(layer_id, "Stone Breakup")
    assert window._layer().name == "Stone Breakup"
    assert window._layer().name in window.color_ramp_editor.title_label.text()
    assert "Stone Breakup" in window.context_breadcrumb.text()

    original_name = window._layer().name
    window.authoring_mode_combo.setCurrentIndex(1)
    window._source_changed("generator.cellular")
    assert window._layer().name == original_name
    assert window.layers_panel.pipeline_descriptor.text() == window._layer_descriptor(
        window._layer()
    )
    assert item is not None
    window._add_layer()
    assert window._layer().name.startswith("Constant")
    window.close()
