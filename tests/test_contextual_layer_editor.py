from __future__ import annotations

import copy

import pytest
from PySide6.QtGui import QColor

from archetexture.color.ramp import ColorRamp, ColorStop
from archetexture.core.defaults import default_recipe
from archetexture.ui.main_window import MainWindow
from archetexture.ui.numeric_control import NumericControl
from archetexture.ui.operation_library import OPERATION_PRESETS


def _preset(name: str):
    return next(preset for preset in OPERATION_PRESETS if preset.name == name)


def test_pattern_parameters_preview_then_apply_or_cancel_as_one_edit(qtbot):
    window = MainWindow(default_recipe())
    qtbot.addWidget(window)
    window._confirm_discard = lambda: True
    window.show()
    preset = _preset("Brick · Standard")

    window._add_library_operation(preset)
    layer = window._layer()
    assert layer.source.operation_id == "generator.brick"
    assert layer.color_ramp is not None
    assert window.simple_inspector_pages.currentWidget() is window.simple_edit_page
    assert "masonry" in window.layer_context_description.text().lower()
    mortar = window.property_editor.findChild(NumericControl, "parameter-mortar")
    assert mortar is not None
    assert mortar.decrement.geometry().center().x() < mortar.increment.geometry().center().x()

    committed_before = copy.deepcopy(window.document.recipe)
    history_index = window.document.history.index
    previewed_value = 0.13
    window.property_editor.valueChanged.emit("mortar", previewed_value)
    assert window._edit_draft_recipe is not None
    assert window.document.recipe == committed_before
    assert window.document.history.index == history_index
    assert window._layer(window._edit_draft_recipe).source.parameters["mortar"] == pytest.approx(
        previewed_value
    )
    window.cancel_layer_edit_button.click()
    assert window._edit_draft_recipe is None
    assert window.document.recipe == committed_before
    assert window.document.history.index == history_index

    committed_index = window.document.history.index
    window.property_editor.valueChanged.emit("mortar", 0.17)
    assert window.document.recipe == committed_before
    window.apply_layer_edit_button.click()
    assert window.document.recipe != committed_before
    assert window.document.history.index == committed_index + 1
    assert window._layer().source.parameters["mortar"] == pytest.approx(0.17)
    applied = copy.deepcopy(window.document.recipe)
    window.undo()
    assert window.document.recipe == committed_before
    window.redo()
    assert window.document.recipe == applied
    window.close()


def test_library_add_keeps_palette_and_selects_each_generator_context(qtbot):
    window = MainWindow(default_recipe())
    qtbot.addWidget(window)
    window._confirm_discard = lambda: True
    window.show()

    for preset_name, operation_id, parameter_id in (
        ("Wood · Fine Grain", "generator.wood_rings", "rings"),
        ("Marble · Fine Veins", "generator.marble_veins", "vein_frequency"),
        ("Weave", "generator.weave", "threads_x"),
    ):
        window._add_library_operation(_preset(preset_name))
        layer = window._layer()
        assert layer.name.startswith(preset_name.split(" · ")[0])
        assert layer.color_ramp is not None
        assert layer.source.operation_id == operation_id
        assert (
            window.property_editor.findChild(NumericControl, f"parameter-{parameter_id}")
            is not None
        )
        selected_id = layer.layer_id
        other = next(
            item
            for item in window._layers_for(window.document.recipe)
            if item.layer_id != selected_id
        )
        window._select_layer(other.layer_id)
        assert window._layer().layer_id == other.layer_id
        assert window.property_editor.findChild(NumericControl, f"parameter-{parameter_id}") is None
    window.close()


def test_ramp_blend_opacity_and_solid_color_share_preview_transaction(qtbot, monkeypatch):
    window = MainWindow(default_recipe())
    qtbot.addWidget(window)
    window._confirm_discard = lambda: True
    window.show()
    window.authoring_mode_combo.setCurrentIndex(0)
    window._select_simple_channel("base_color")
    window._add_library_operation(_preset("Weave"))
    original = copy.deepcopy(window.document.recipe)
    history_index = window.document.history.index
    ramp = ColorRamp(
        (
            ColorStop(0.0, (0.0, 0.0, 0.0, 1.0)),
            ColorStop(0.5, (0.95, 0.1, 0.2, 1.0)),
            ColorStop(1.0, (1.0, 0.9, 0.1, 1.0)),
        )
    )
    window.color_ramp_editor.rampEdited.emit(ramp)
    window.context_opacity.setValue(0.64)
    window.context_blend.setCurrentIndex(window.context_blend.findData("multiply"))
    assert window.document.recipe == original
    assert window.document.history.index == history_index
    draft_layer = window._layer(window._edit_draft_recipe)
    assert draft_layer.color_ramp == ramp
    assert draft_layer.opacity == pytest.approx(0.64)
    assert draft_layer.blend_mode == "multiply"
    window.apply_layer_edit_button.click()
    assert window.document.history.index == history_index + 1

    window._simple_operation_added("solid_color")
    constant = window._layer()
    assert constant.source.operation_id == "generator.constant"
    monkeypatch.setattr(
        "archetexture.ui.main_window.QColorDialog.getColor",
        lambda *_args, **_kwargs: QColor(12, 120, 220, 255),
    )
    window._choose_context_solid_color()
    assert window._edit_draft_recipe is not None
    solid_ramp = window._layer(window._edit_draft_recipe).color_ramp
    assert solid_ramp is not None
    assert len(solid_ramp.stops) == 2
    assert solid_ramp.stops[0].color == solid_ramp.stops[1].color
    assert window.document.recipe != window._edit_draft_recipe
    window.cancel_layer_edit_button.click()
    window.close()


def test_workspace_view_labels_distinguish_property_and_combined_material(qtbot):
    window = MainWindow(default_recipe())
    qtbot.addWidget(window)
    window._confirm_discard = lambda: True
    window.workspace_mode_combo.setCurrentIndex(0)
    assert window.workspace_mode_combo.itemText(0).startswith("Edited Property")
    assert window.workspace_mode_combo.itemText(1).startswith("Combined Material")
    assert window.preview_content_label.text().startswith("EDITED PROPERTY")
    window.close()


def test_switching_to_advanced_discards_unapplied_context_draft(qtbot):
    window = MainWindow(default_recipe())
    qtbot.addWidget(window)
    window._confirm_discard = lambda: True
    window.show()
    window.authoring_mode_combo.setCurrentIndex(0)
    window._select_simple_channel("base_color")
    window._add_library_operation(_preset("Brick · Standard"))
    layer_id = window._selected_layer_id
    original_recipe = copy.deepcopy(window.document.recipe)
    history_index = window.document.history.index
    assert window.authoring_mode_combo.currentIndex() == 0
    assert window.simple_inspector_pages.currentWidget() is window.simple_edit_page
    assert window._layer().source.parameters.get("mortar") is not None

    window.property_editor.valueChanged.emit("mortar", 0.18)
    assert window._edit_draft_recipe is not None
    window.authoring_mode_combo.setCurrentIndex(1)

    assert window._edit_draft_recipe is None
    assert window.document.recipe == original_recipe
    assert window.document.history.index == history_index
    assert window._layer().layer_id == layer_id
    window.close()
