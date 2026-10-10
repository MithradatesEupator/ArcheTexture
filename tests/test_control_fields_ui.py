from __future__ import annotations

import copy

import numpy as np
import pytest
from PIL import Image
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDoubleSpinBox,
    QMessageBox,
    QPushButton,
    QSpinBox,
)

from archetexture.core.parameters import (
    ControlFieldBinding,
    ControlFieldMapping,
    ParameterSpec,
    ParameterType,
)
from archetexture.core.recipe import ControlFieldRecipe, OperationInstance, ProjectRecipe
from archetexture.core.validation import validate_recipe
from archetexture.render.engine import RenderEngine
from archetexture.render.pixels import rgba_float_to_uint8
from archetexture.ui.binding_dialog import BindingDialog
from archetexture.ui.main_window import build_main_window


def recipe(fields=None, transforms=None):
    return ProjectRecipe(
        width=28,
        height=18,
        seed=17,
        source=OperationInstance("source", "generator.constant", 1, parameters={"value": 0.2}),
        transforms=transforms or [],
        control_fields=fields or {},
    )


def control_field(identifier, operation="generator.linear_gradient"):
    params = {"angle": 0.0} if operation == "generator.linear_gradient" else {"value": 0.5}
    return ControlFieldRecipe(
        source=OperationInstance(f"{identifier}-source", operation, 1, parameters=params)
    )


@pytest.fixture
def window(qtbot, monkeypatch):
    monkeypatch.setattr(
        QMessageBox, "question", lambda *_a, **_k: QMessageBox.StandardButton.Discard
    )
    main = build_main_window(recipe())
    main.authoring_mode_combo.setCurrentIndex(1)
    qtbot.addWidget(main)
    main.show()
    qtbot.waitUntil(lambda: main.viewport.rendered_field is not None, timeout=5000)
    return main


def wait_render(qtbot, main):
    qtbot.waitUntil(lambda: main.statusBar().currentMessage() != "Rendering…", timeout=5000)


def test_create_unique_ids_and_undo_redo(window, qtbot):
    editor = window.control_fields_editor
    assert not window.property_editor.findChild(QPushButton, "modulate-value").isEnabled()
    editor.create_button.click()
    editor.create_button.click()
    assert list(window.document.recipe.control_fields) == ["control-1", "control-2"]
    assert editor.selected_field_id == "control-2"
    window.undo()
    assert list(window.document.recipe.control_fields) == ["control-1"]
    window.redo()
    assert list(window.document.recipe.control_fields) == ["control-1", "control-2"]
    wait_render(qtbot, window)


def test_rename_rewrites_nested_main_and_control_bindings_with_undo(window, qtbot):
    binding = ControlFieldBinding("mask", ControlFieldMapping(0.1, 0.9, invert=True))
    other = ControlFieldRecipe(
        source=OperationInstance(
            "other-source", "generator.constant", 1, parameters={"value": binding}
        ),
        transforms=[
            OperationInstance(
                "other-transform",
                "transform.threshold",
                1,
                parameters={"threshold": binding},
                influence=binding,
            )
        ],
    )
    initial = recipe(
        {"mask": control_field("mask"), "other": other},
        [
            OperationInstance(
                "main-transform",
                "transform.threshold",
                1,
                parameters={"threshold": binding},
                influence=binding,
            )
        ],
    )
    initial.source.parameters["value"] = binding
    window.document.new_document(initial)
    window._selected_control_field_id = "mask"
    window._refresh_document(request_render=True)
    before = window.document.recipe
    window._rename_control_field("mask", "renamed-mask")
    result = window.document.recipe
    assert "mask" not in result.control_fields
    assert result.source.parameters["value"].source_id == "renamed-mask"
    assert result.transforms[0].parameters["threshold"].source_id == "renamed-mask"
    assert result.transforms[0].influence.source_id == "renamed-mask"
    nested = result.control_fields["other"]
    assert nested.source.parameters["value"].source_id == "renamed-mask"
    assert nested.transforms[0].parameters["threshold"].source_id == "renamed-mask"
    assert nested.transforms[0].influence.source_id == "renamed-mask"
    assert not validate_recipe(result)
    window.undo()
    assert window.document.recipe == before
    window.redo()
    assert window.document.recipe == result
    wait_render(qtbot, window)


def test_duplicate_rename_is_rejected_and_referenced_delete_is_blocked(window, monkeypatch):
    binding = ControlFieldBinding("mask")
    initial = recipe({"mask": control_field("mask"), "other": control_field("other")})
    initial.source.parameters["value"] = binding
    window.document.new_document(initial)
    window._refresh_document(request_render=False)
    before = window.document.recipe
    history = copy.deepcopy(window.document.history)
    window._rename_control_field("mask", "other")
    assert window.document.recipe == before
    assert window.document.history == history
    messages = []
    monkeypatch.setattr(QMessageBox, "information", lambda *_a: messages.append(_a[-1]))
    window._remove_control_field("mask")
    assert window.document.recipe == before
    assert "main source" in messages[0]


def test_remove_unused_control_is_undoable(window, qtbot):
    window.document.new_document(recipe({"free": control_field("free")}))
    window._refresh_document(request_render=True)
    window._remove_control_field("free")
    assert not window.document.recipe.control_fields
    window.undo()
    assert "free" in window.document.recipe.control_fields
    wait_render(qtbot, window)


def test_scalar_source_parameters_transform_chain_and_global_mapping(window, qtbot):
    editor = window.control_fields_editor
    editor.create_button.click()
    identifier = editor.selected_field_id
    editor.source_combo.setCurrentIndex(editor.source_combo.findData("generator.radial_gradient"))
    current = window.document.recipe.control_fields[identifier]
    assert current.source.parameters == {"radius": 0.5}
    window.undo()
    assert (
        window.document.recipe.control_fields[identifier].source.operation_id
        == "generator.constant"
    )
    window.redo()
    assert (
        window.document.recipe.control_fields[identifier].source.operation_id
        == "generator.radial_gradient"
    )
    editor.edit_source_button.click()
    radius = editor.property_editor.findChild(QDoubleSpinBox, "parameter-radius")
    assert radius is not None
    radius.setValue(0.7)
    assert window.document.recipe.control_fields[identifier].source.parameters["radius"] == 0.7

    for operation in ("transform.invert", "transform.quantize"):
        editor.transform_combo.setCurrentIndex(editor.transform_combo.findData(operation))
        editor.add_transform_button.click()
    current = window.document.recipe.control_fields[identifier]
    assert [item.operation_id for item in current.transforms] == [
        "transform.invert",
        "transform.quantize",
    ]
    levels = editor.property_editor.findChild(QSpinBox, "parameter-levels")
    assert levels is not None
    levels.setValue(12)
    assert (
        window.document.recipe.control_fields[identifier].transforms[1].parameters["levels"] == 12
    )
    editor.move_up_button.click()
    current = window.document.recipe.control_fields[identifier]
    assert [item.operation_id for item in current.transforms] == [
        "transform.quantize",
        "transform.invert",
    ]
    selected = editor.transform_list.currentItem()
    selected.setCheckState(Qt.CheckState.Unchecked)
    assert not window.document.recipe.control_fields[identifier].transforms[0].enabled
    editor.remove_transform_button.click()
    assert len(window.document.recipe.control_fields[identifier].transforms) == 1

    editor.mapping_enabled.click()
    editor.mapping_min.setValue(0.2)
    editor.mapping_max.setValue(0.8)
    editor.mapping_invert.setChecked(True)
    mapping = window.document.recipe.control_fields[identifier].mapping
    assert mapping == ControlFieldMapping(0.2, 0.8, invert=True)
    editor.mapping_enabled.setChecked(False)
    assert window.document.recipe.control_fields[identifier].mapping is None
    editor.mapping_enabled.setChecked(True)
    wait_render(qtbot, window)


def test_main_parameter_binding_mapping_unbinding_and_png(window, qtbot, monkeypatch, tmp_path):
    editor = window.control_fields_editor
    editor.create_button.click()
    identifier = editor.selected_field_id
    editor.source_combo.setCurrentIndex(editor.source_combo.findData("generator.linear_gradient"))
    original_pixels = window.viewport.rendered_field.copy()

    def accept(dialog):
        dialog.minimum.setValue(0.1)
        dialog.maximum.setValue(0.9)
        dialog.curve.setCurrentText("smoothstep")
        dialog.quantize.setValue(5)
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(BindingDialog, "exec", accept)
    modulate = window.property_editor.findChild(QPushButton, "modulate-value")
    assert modulate is not None and modulate.isEnabled()
    modulate.click()
    binding = window.document.recipe.source.parameters["value"]
    assert isinstance(binding, ControlFieldBinding)
    assert binding.source_id == identifier
    assert binding.mapping == ControlFieldMapping(0.1, 0.9, curve="smoothstep", quantize=5)
    wait_render(qtbot, window)
    assert not np.array_equal(original_pixels, window.viewport.rendered_field)

    path = tmp_path / "modulated.png"
    assert window._start_export(path, 15, 9)
    qtbot.waitUntil(lambda: window.export_action.isEnabled(), timeout=5000)
    with Image.open(path) as image:
        assert image.size == (15, 9)
        expected = rgba_float_to_uint8(
            RenderEngine().render(window.document.recipe, width=15, height=9).rgba_field
        )
        np.testing.assert_array_equal(np.asarray(image), expected)

    monkeypatch.setattr(BindingDialog, "exec", lambda _dialog: QDialog.DialogCode.Accepted)
    window.property_editor.findChild(QPushButton, "edit-binding-value").click()
    window.property_editor.findChild(QPushButton, "unbind-value").click()
    assert window.document.recipe.source.parameters["value"] == pytest.approx(0.5)
    window.undo()
    assert isinstance(window.document.recipe.source.parameters["value"], ControlFieldBinding)


def test_transform_influence_modulation(window, qtbot, monkeypatch):
    panel = window.pipeline_panel
    panel.transform_selector.setCurrentIndex(panel.transform_selector.findData("transform.invert"))
    panel.add_button.click()
    panel.transform_list.setCurrentRow(0)
    fields = window.control_fields_editor
    fields.create_button.click()
    fields.source_combo.setCurrentIndex(fields.source_combo.findData("generator.linear_gradient"))
    monkeypatch.setattr(BindingDialog, "exec", lambda _dialog: QDialog.DialogCode.Accepted)
    button = window.property_editor.findChild(QPushButton, "modulate-influence")
    assert button is not None and button.isEnabled()
    button.click()
    assert isinstance(window.document.recipe.transforms[0].influence, ControlFieldBinding)
    wait_render(qtbot, window)
    assert not np.allclose(window.viewport.rendered_field[..., 0], 0.2)


def test_cycle_candidate_rejected_without_document_history_or_preview_change(
    window, qtbot, monkeypatch
):
    fields = window.control_fields_editor
    fields.create_button.click()
    identifier = fields.selected_field_id
    fields.property_editor.findChild(QDoubleSpinBox, "parameter-value").setValue(0.6)
    window.undo()
    wait_render(qtbot, window)
    old_recipe = window.document.recipe
    old_history = copy.deepcopy(window.document.history)
    old_pixels = window.viewport.rendered_field.copy()
    old_dirty = window.document.dirty
    old_selection = window._selected_instance_id

    def choose_self(dialog):
        dialog.field_combo.setCurrentIndex(dialog.field_combo.findData(identifier))
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(BindingDialog, "exec", choose_self)
    fields.edit_source_button.click()
    fields.property_editor.findChild(QPushButton, "modulate-value").click()
    assert window.document.recipe == old_recipe
    assert window.document.history == old_history
    assert window.document.dirty == old_dirty
    assert window.document.can_redo
    assert window._selected_instance_id == old_selection
    assert "cyclic control-field reference" in window.statusBar().currentMessage()
    np.testing.assert_array_equal(window.viewport.rendered_field, old_pixels)
    wait_render(qtbot, window)


def test_save_open_refreshes_control_field_tab(window, qtbot, tmp_path):
    fields = window.control_fields_editor
    fields.create_button.click()
    identifier = fields.selected_field_id
    fields.source_combo.setCurrentIndex(fields.source_combo.findData("generator.linear_gradient"))
    updated = window.document.recipe
    updated.source.parameters["value"] = ControlFieldBinding(
        identifier, ControlFieldMapping(0.15, 0.85, curve="smoothstep")
    )
    window._commit_recipe(updated)
    destination = tmp_path / "controls.archetexture"
    assert window.save_project(str(destination))
    expected = window.document.recipe
    pixels = RenderEngine().render(expected).rgba_field
    assert window.new_document()
    assert fields.fields_list.count() == 2
    assert window.open_project(str(destination))
    assert fields.fields_list.count() == 1
    assert fields.selected_field_id == identifier
    assert window.document.recipe == expected
    wait_render(qtbot, window)
    np.testing.assert_array_equal(window.viewport.rendered_field, pixels)


def test_non_modulatable_boolean_has_no_modulation_action(qtbot):
    from archetexture.core.operations import OperationDefinition, OperationType
    from archetexture.core.parameters import ParameterSpec, ParameterType
    from archetexture.ui.property_editor import PropertyEditor

    editor = PropertyEditor()
    definition = OperationDefinition(
        "test.boolean",
        1,
        "Boolean",
        "Generator",
        "test",
        OperationType.GENERATOR,
        (),
        "scalar",
        (
            ParameterSpec("flag", "Flag", ParameterType.BOOLEAN, default=True),
            ParameterSpec("seed", "Seed", ParameterType.SEED, default=1, allows_modulation=False),
        ),
    )
    editor.set_control_fields({"mask": control_field("mask")})
    editor.set_operation(
        OperationInstance("test", "test.boolean", 1, parameters={"flag": True}), definition
    )
    assert editor.findChild(QCheckBox, "parameter-flag") is not None
    assert editor.findChild(QPushButton, "modulate-flag") is None
    assert editor.findChild(QPushButton, "modulate-seed") is None


def test_binding_mapping_controls_respect_parameter_spec_range(qtbot):
    angle = ParameterSpec(
        "angle", "Angle", ParameterType.ANGLE, default=90.0, min_value=0.0, max_value=360.0
    )
    dialog = BindingDialog({"mask": control_field("mask")}, angle)
    assert dialog.minimum.minimum() == 0.0
    assert dialog.minimum.maximum() == 360.0
    assert dialog.maximum.minimum() == 0.0
    assert dialog.maximum.maximum() == 360.0
    assert dialog.binding.source_id == "mask"
