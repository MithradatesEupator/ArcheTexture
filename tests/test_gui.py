from __future__ import annotations

import copy
import json

import numpy as np
import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QWidget,
)

from archetexture.color.ramp import ColorRamp, ColorStop
from archetexture.core.operations import OperationDefinition, OperationType, Seamlessness
from archetexture.core.parameters import ParameterSpec, ParameterType
from archetexture.core.recipe import OperationInstance, ProjectRecipe
from archetexture.core.registry import REGISTRY
from archetexture.ui.export_image_dialog import ExportImageDialog
from archetexture.ui.main_window import build_main_window


def small_recipe() -> ProjectRecipe:
    return ProjectRecipe(
        width=48,
        height=32,
        seed=13,
        source=OperationInstance(
            "source",
            "generator.constant",
            1,
            parameters={"value": 0.2},
        ),
        color_ramp=ColorRamp(
            (
                ColorStop(0.0, (0.02, 0.03, 0.08, 1.0)),
                ColorStop(1.0, (0.9, 0.7, 0.25, 1.0)),
            )
        ),
    )


@pytest.fixture
def workbench(qtbot, monkeypatch):
    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda *_args, **_kwargs: QMessageBox.StandardButton.Discard,
    )
    window = build_main_window(small_recipe())
    qtbot.addWidget(window)
    window.show()
    qtbot.waitUntil(lambda: window.viewport.rendered_field is not None, timeout=5000)
    return window


def test_workbench_shows_pipeline_properties_and_rendered_viewport(workbench):
    assert workbench.isVisible()
    assert workbench.pipeline_panel.source_selector.count() >= 4
    assert workbench.pipeline_panel.transform_selector.count() >= 3
    assert workbench.property_editor.findChild(QDoubleSpinBox, "parameter-value") is not None
    assert workbench.viewport.rendered_field.shape == (32, 48, 4)
    assert workbench.viewport.rendered_field.dtype == np.float32


@pytest.mark.parametrize("dirty", [False, True])
def test_png_export_keeps_document_state_unchanged(workbench, qtbot, tmp_path, dirty):
    document = workbench.document
    if dirty:
        edited_recipe = document.recipe
        edited_recipe.seed += 1
        document.commit(edited_recipe)
    snapshot = copy.deepcopy(document.recipe)
    history_entries = copy.deepcopy(document.history.entries)
    history_index = document.history.index
    selected_id = workbench._selected_instance_id
    destination = tmp_path / "workbench.png"

    assert workbench._start_export(destination, 13, 7)
    assert not workbench.export_action.isEnabled()
    qtbot.waitUntil(
        lambda: destination.exists() and workbench.export_action.isEnabled(), timeout=5000
    )

    assert document.recipe == snapshot
    assert document.project_path is None
    assert document.dirty is dirty
    assert document.history.entries == history_entries
    assert document.history.index == history_index
    assert workbench._selected_instance_id == selected_id
    assert workbench.statusBar().currentMessage() == "Exported workbench.png"


def test_export_dialog_defaults_dimensions_and_lock_ratio(qtbot):
    dialog = ExportImageDialog(small_recipe())
    qtbot.addWidget(dialog)
    assert dialog.dimensions == (48, 32)
    assert dialog.lock_aspect.isChecked()
    dialog.width_spin.setValue(96)
    assert dialog.dimensions == (96, 64)
    assert "6,144 pixels" in dialog.info_label.text()


def test_property_editor_builds_enum_boolean_color_and_position_controls(qtbot, monkeypatch):
    def structured_source(_input, parameters, width, height, _seed):
        return np.full((height, width), parameters["amount"], dtype=np.float32)

    definition = OperationDefinition(
        identifier="test.generator.ui-parameters",
        version=1,
        name="UI Parameters",
        category="Generator",
        description="Exercises generated property controls",
        operation_type=OperationType.GENERATOR,
        input_types=(),
        output_type="scalar",
        parameter_specs=(
            ParameterSpec(
                "mode",
                "Mode",
                ParameterType.ENUM,
                default="soft",
                options=("soft", "hard"),
                allows_modulation=False,
            ),
            ParameterSpec(
                "enabled",
                "Enabled",
                ParameterType.BOOLEAN,
                default=True,
                allows_modulation=False,
            ),
            ParameterSpec(
                "color",
                "Color",
                ParameterType.COLOR,
                default=(0.1, 0.2, 0.3, 1.0),
                allows_modulation=False,
            ),
            ParameterSpec(
                "position",
                "Position",
                ParameterType.POSITION_2D,
                default=(0.25, 0.75),
                allows_modulation=False,
            ),
            ParameterSpec(
                "amount",
                "Amount",
                ParameterType.PERCENT,
                default=0.4,
                min_value=0.0,
                max_value=1.0,
                step=0.01,
            ),
        ),
        seamlessness=Seamlessness.INHERENT,
        implementation=structured_source,
    )
    REGISTRY.register(definition)
    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda *_args, **_kwargs: QMessageBox.StandardButton.Discard,
    )
    recipe = ProjectRecipe(
        width=20,
        height=12,
        source=OperationInstance(
            "source",
            definition.identifier,
            1,
            parameters={
                "mode": "soft",
                "enabled": True,
                "color": (0.1, 0.2, 0.3, 1.0),
                "position": (0.25, 0.75),
                "amount": 0.4,
            },
        ),
    )
    window = build_main_window(recipe)
    qtbot.addWidget(window)
    try:
        window.show()
        qtbot.waitUntil(lambda: window.viewport.rendered_field is not None, timeout=5000)
        mode = window.property_editor.findChild(QComboBox, "parameter-mode")
        enabled = window.property_editor.findChild(QCheckBox, "parameter-enabled")
        color = window.property_editor.findChild(QPushButton, "parameter-color")
        position = window.property_editor.findChild(QWidget, "parameter-position")
        amount = window.property_editor.findChild(QDoubleSpinBox, "parameter-amount")
        assert mode is not None and enabled is not None and color is not None
        assert position is not None and amount is not None

        mode.setCurrentText("hard")
        enabled.setChecked(False)
        position.findChildren(QDoubleSpinBox)[0].setValue(0.5)
        amount.setValue(0.6)
        assert window.document.recipe.source.parameters["mode"] == "hard"
        assert window.document.recipe.source.parameters["enabled"] is False
        assert window.document.recipe.source.parameters["position"] == (0.5, 0.75)
        assert window.document.recipe.source.parameters["amount"] == pytest.approx(0.6)
        qtbot.waitUntil(lambda: window.statusBar().currentMessage() != "Rendering…", timeout=5000)
    finally:
        window.close()
        REGISTRY.unregister(definition.identifier)


def test_source_selection_and_metadata_driven_property_edit(workbench, qtbot):
    selector = workbench.pipeline_panel.source_selector
    selector.setCurrentIndex(selector.findData("generator.radial_gradient"))
    recipe = workbench.document.recipe
    assert recipe.source.operation_id == "generator.radial_gradient"
    assert workbench.document.dirty
    radius = workbench.property_editor.findChild(QDoubleSpinBox, "parameter-radius")
    assert radius is not None
    radius.setValue(0.8)
    assert workbench.document.recipe.source.parameters["radius"] == pytest.approx(0.8)
    qtbot.waitUntil(
        lambda: (
            workbench.viewport.rendered_field is not None
            and workbench.statusBar().currentMessage() != "Rendering…"
        ),
        timeout=5000,
    )


def test_transform_add_edit_toggle_reorder_and_remove(workbench, qtbot):
    initial = workbench.viewport.rendered_field.copy()
    panel = workbench.pipeline_panel
    panel.transform_selector.setCurrentIndex(panel.transform_selector.findData("transform.invert"))
    panel.add_button.click()
    panel.transform_selector.setCurrentIndex(
        panel.transform_selector.findData("transform.quantize")
    )
    panel.add_button.click()
    assert [item.operation_id for item in workbench.document.recipe.transforms] == [
        "transform.invert",
        "transform.quantize",
    ]

    panel.transform_list.setCurrentRow(1)
    levels = workbench.property_editor.findChild(QSpinBox, "parameter-levels")
    assert levels is not None
    levels.setValue(4)
    assert workbench.document.recipe.transforms[1].parameters["levels"] == 4

    panel.transform_list.setCurrentRow(0)
    influence = workbench.property_editor.findChild(QDoubleSpinBox, "parameter-influence")
    assert influence is not None
    influence.setValue(0.5)
    assert workbench.document.recipe.transforms[0].influence == pytest.approx(0.5)
    panel.down_button.click()
    assert [item.operation_id for item in workbench.document.recipe.transforms] == [
        "transform.quantize",
        "transform.invert",
    ]

    item = panel.transform_list.item(0)
    item.setCheckState(Qt.CheckState.Unchecked)
    assert not workbench.document.recipe.transforms[0].enabled
    item = panel.transform_list.item(0)
    item.setCheckState(Qt.CheckState.Checked)
    assert workbench.document.recipe.transforms[0].enabled
    qtbot.waitUntil(
        lambda: (
            workbench.viewport.rendered_field is not None
            and not np.array_equal(initial, workbench.viewport.rendered_field)
        ),
        timeout=5000,
    )

    panel.transform_list.setCurrentRow(0)
    panel.remove_button.click()
    assert len(workbench.document.recipe.transforms) == 1


def test_property_edits_support_undo_and_redo(workbench):
    value = workbench.property_editor.findChild(QDoubleSpinBox, "parameter-value")
    value.setValue(0.7)
    assert workbench.document.recipe.source.parameters["value"] == pytest.approx(0.7)
    assert workbench.undo_action.isEnabled()
    workbench.undo()
    assert workbench.document.recipe.source.parameters["value"] == pytest.approx(0.2)
    assert workbench.document.dirty is False
    workbench.redo()
    assert workbench.document.recipe.source.parameters["value"] == pytest.approx(0.7)


def test_new_document_discards_only_after_explicit_confirmation(workbench, qtbot):
    workbench.property_editor.findChild(QDoubleSpinBox, "parameter-value").setValue(0.9)
    assert workbench.document.dirty
    assert workbench.new_document()
    recipe = workbench.document.recipe
    assert recipe.source.operation_id == "generator.fractal_noise"
    assert not workbench.document.dirty
    qtbot.waitUntil(
        lambda: (
            workbench.viewport.rendered_field is not None
            and workbench.viewport.rendered_field.shape == (512, 512, 4)
        ),
        timeout=5000,
    )


def test_save_load_render_equivalence_and_dirty_document_protection(
    workbench, qtbot, monkeypatch, tmp_path
):
    path = tmp_path / "workbench.archetexture"
    assert workbench.save_project(str(path))
    saved_pixels = workbench.viewport.rendered_field.copy()
    assert not workbench.document.dirty

    value = workbench.property_editor.findChild(QDoubleSpinBox, "parameter-value")
    value.setValue(0.8)
    assert workbench.document.dirty

    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda *_args, **_kwargs: QMessageBox.StandardButton.Cancel,
    )
    assert not workbench.new_document()
    assert not workbench.open_project(str(path))
    assert workbench.document.recipe.source.parameters["value"] == pytest.approx(0.8)

    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda *_args, **_kwargs: QMessageBox.StandardButton.Discard,
    )
    assert workbench.open_project(str(path))
    assert not workbench.document.dirty
    qtbot.waitUntil(
        lambda: (
            workbench.viewport.rendered_field is not None
            and workbench.statusBar().currentMessage() != "Rendering…"
        ),
        timeout=5000,
    )
    assert np.array_equal(saved_pixels, workbench.viewport.rendered_field)

    workbench.property_editor.findChild(QDoubleSpinBox, "parameter-value").setValue(0.6)
    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda *_args, **_kwargs: QMessageBox.StandardButton.Cancel,
    )
    assert not workbench.close()
    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda *_args, **_kwargs: QMessageBox.StandardButton.Discard,
    )
    assert workbench.close()


def test_failed_open_preserves_dirty_work_and_successful_open_still_works(
    workbench, qtbot, monkeypatch, tmp_path
):
    valid_path = tmp_path / "valid.archetexture"
    assert workbench.save_project(str(valid_path))
    saved_pixels = workbench.viewport.rendered_field.copy()

    value = workbench.property_editor.findChild(QDoubleSpinBox, "parameter-value")
    value.setValue(0.4)
    workbench.property_editor.findChild(QDoubleSpinBox, "parameter-value").setValue(0.5)
    workbench.undo()
    qtbot.waitUntil(
        lambda: workbench.statusBar().currentMessage() != "Rendering…",
        timeout=5000,
    )
    assert workbench.document.dirty
    assert workbench.document.can_undo and workbench.document.can_redo

    invalid_payload = json.loads(valid_path.read_text(encoding="utf-8"))
    invalid_payload["layers"][0]["source"]["operation_id"] = "definitely.invalid.operation"
    invalid_path = tmp_path / "invalid-operation.archetexture"
    invalid_path.write_text(json.dumps(invalid_payload), encoding="utf-8")

    expected_recipe = workbench.document.recipe
    expected_history = copy.deepcopy(workbench.document.history)
    expected_path = workbench.document.project_path
    expected_selection = workbench._selected_instance_id
    expected_pixels = workbench.viewport.rendered_field.copy()
    expected_title = workbench.windowTitle()
    errors = []
    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda *_args, **_kwargs: pytest.fail(
            "Invalid Open must be rejected before prompting to save or discard"
        ),
    )
    monkeypatch.setattr(
        QMessageBox,
        "critical",
        lambda _parent, title, message: errors.append((title, message)),
    )

    assert not workbench.open_project(str(invalid_path))
    assert len(errors) == 1
    assert errors[0][0] == "Open failed"
    assert "unknown operation" in errors[0][1]
    assert "Traceback" not in errors[0][1]
    assert workbench.document.recipe == expected_recipe
    assert workbench.document.dirty
    assert workbench.document.project_path == expected_path
    assert workbench.document.history == expected_history
    assert workbench.document.can_undo and workbench.document.can_redo
    assert workbench._selected_instance_id == expected_selection
    assert workbench.windowTitle() == expected_title
    assert np.array_equal(workbench.viewport.rendered_field, expected_pixels)

    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda *_args, **_kwargs: QMessageBox.StandardButton.Discard,
    )
    assert workbench.open_project(str(valid_path))
    assert workbench.document.recipe == small_recipe()
    assert not workbench.document.dirty
    assert workbench.document.project_path == str(valid_path)
    assert not workbench.document.can_undo and not workbench.document.can_redo
    qtbot.waitUntil(
        lambda: workbench.statusBar().currentMessage() != "Rendering…",
        timeout=5000,
    )
    assert np.array_equal(workbench.viewport.rendered_field, saved_pixels)


def test_save_as_adds_project_extension(workbench, tmp_path):
    path = tmp_path / "new-project"
    assert workbench.save_project(str(path))
    assert (tmp_path / "new-project.archetexture").exists()
