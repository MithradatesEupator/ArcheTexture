from __future__ import annotations

import json
import os
import time
from pathlib import Path

import numpy as np
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QImage
from PySide6.QtTest import QSignalSpy, QTest
from PySide6.QtWidgets import QApplication, QColorDialog, QDialog, QDialogButtonBox, QLineEdit

from archetexture.core.defaults import default_recipe
from archetexture.core.material_starters import MATERIAL_STARTERS
from archetexture.core.pipeline_types import pipeline_output_type
from archetexture.core.serialization import load_project
from archetexture.ui.main_window import MainWindow
from archetexture.ui.numeric_control import NumericControl


def _wait(predicate, message: str, timeout: float = 45.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        QApplication.processEvents()
        if predicate():
            return
        QTest.qWait(20)
    raise AssertionError(message)


def _image_bytes(widget, evidence_name: str | None = None) -> np.ndarray:
    QTest.qWait(100)
    image = widget.grab().toImage().convertToFormat(QImage.Format.Format_RGBA8888)
    assert not image.isNull(), f"could not capture {widget.objectName()}"
    filename = evidence_name or f"{widget.objectName() or 'canvas'}.png"
    path = Path(os.environ["ATX31_EVIDENCE_DIR"]) / filename
    image.save(str(path))
    return np.frombuffer(image.bits(), dtype=np.uint8, count=image.sizeInBytes()).copy()


def _wait_for_render(window: MainWindow) -> None:
    target = window.render_coordinator.latest_request_id
    _wait(
        lambda: (
            window._latest_displayed_request_id is not None
            and window._latest_displayed_request_id >= target
        ),
        f"2D request {target} did not finish",
    )


def _edit_ramp_color(window: MainWindow, color: str) -> None:
    def choose_color() -> None:
        dialog = QApplication.activeModalWidget()
        assert isinstance(dialog, QColorDialog), "ramp color picker did not open"
        entry = dialog.findChild(QLineEdit, "qt_colorname_lineedit")
        assert entry is not None, "color picker has no editable color field"
        entry.setFocus()
        QTest.keyClick(entry, Qt.Key.Key_A, Qt.KeyboardModifier.ControlModifier)
        QTest.keyClicks(entry, color)
        buttons = dialog.findChild(QDialogButtonBox)
        assert buttons is not None
        QTest.mouseClick(
            buttons.button(QDialogButtonBox.StandardButton.Ok), Qt.MouseButton.LeftButton
        )

    QTimer.singleShot(200, choose_color)
    QTest.mouseClick(window.color_ramp_editor.color_button, Qt.MouseButton.LeftButton)


def _choose_card(window: MainWindow, context: str, query: str) -> str:
    library = window.operation_library
    library.mode.setCurrentText(context)
    library.search.setText(query)
    _wait(lambda: bool(library._cards), f"No library result for {query}")
    key = next(iter(library._cards))
    QTest.mouseClick(library._cards[key][1], Qt.MouseButton.LeftButton)
    if not key.startswith("starter:") and not key.startswith("image:"):
        _wait(lambda: library.sample.pixmap() is not None, f"{query} sample did not render")
    return key


def main() -> int:
    root = Path(os.environ["ATX31_EVIDENCE_DIR"])
    root.mkdir(parents=True, exist_ok=True)
    application = QApplication.instance() or QApplication([])
    assert application is not None
    window = MainWindow(default_recipe())
    window._confirm_discard = lambda: True
    window.show()
    _wait_for_render(window)
    _wait(
        lambda: window.preview_viewport.available or window.preview_viewport._gl_error,
        "3D viewport did not initialize",
    )
    baseline_recipe = window.document.recipe
    baseline_history = list(window.document.history.entries)
    baseline_dirty = window.document.dirty

    # Browse real, deterministic samples without touching project state.
    window.browse_operations_button.click()
    _choose_card(window, "Patterns", "Brick · Standard")
    brick = _image_bytes(window.operation_library.sample, "brick-sample.png")
    _choose_card(window, "Patterns", "Wood · Fine Grain")
    wood = _image_bytes(window.operation_library.sample, "wood-sample.png")
    _choose_card(window, "Patterns", "Marble · Fine Veins")
    marble = _image_bytes(window.operation_library.sample, "marble-sample.png")
    _choose_card(window, "Patterns", "Weave")
    weave = _image_bytes(window.operation_library.sample, "weave-sample.png")
    _choose_card(window, "Patterns", "Checker Grid")
    checker = _image_bytes(window.operation_library.sample, "checker-sample.png")
    assert all(
        not np.array_equal(a, b)
        for i, a in enumerate((brick, wood, marble, weave, checker))
        for b in (brick, wood, marble, weave, checker)[i + 1 :]
    )
    assert window.document.recipe == baseline_recipe
    assert window.document.history.entries == baseline_history
    assert window.document.dirty == baseline_dirty

    # Add a real pattern and edit it with native mouse and keyboard input.
    _choose_card(window, "Patterns", "Weave")
    QTest.mouseClick(window.operation_library.action, Qt.MouseButton.LeftButton)
    _wait_for_render(window)
    source_id = window._layer().source.instance_id
    threads = window.property_editor.findChild(NumericControl, "parameter-threads_x")
    assert threads is not None, "Weave thread count is not shown in contextual settings"
    before_threads = threads.value()
    QTest.mouseClick(threads.increment, Qt.MouseButton.LeftButton)
    assert threads.value() > before_threads
    threads.editor.setFocus()
    threads.editor.selectAll()
    QTest.keyClicks(threads.editor, "16")
    QTest.keyClick(threads.editor, Qt.Key.Key_Return)
    assert window._layer().source.parameters["threads_x"] == 16
    assert window.color_ramp_editor.isVisible()
    QTest.mouseClick(window.color_ramp_editor.add_button, Qt.MouseButton.LeftButton)
    _edit_ramp_color(window, "#247bcc")
    _wait_for_render(window)
    canvas_before_3d = _image_bytes(window.viewport, "2d-canvas-pattern-edit.png")

    # Exercise the 3D workspace through the visible selector.
    QTest.mouseClick(window.workspace_mode_combo, Qt.MouseButton.LeftButton)
    QTest.keyClick(window.workspace_mode_combo, Qt.Key.Key_Down)
    QTest.keyClick(window.workspace_mode_combo, Qt.Key.Key_Enter)
    _wait(
        lambda: window.preview_viewport.snapshot is not None or window.preview_viewport._gl_error,
        "3D material preview did not produce a snapshot or graceful fallback",
        timeout=90.0,
    )
    if window.preview_viewport.available:
        _image_bytes(window.preview_viewport, "3d-material-preview.png")
        base_color_map = window.preview_viewport.snapshot.maps["base_color"]
        assert float(base_color_map.std()) > 0.01, "3D base color preview is spatially flat"
    camera_before = (
        window.preview_viewport.camera.yaw,
        window.preview_viewport.camera.pitch,
        window.preview_viewport.camera.distance,
        tuple(window.preview_viewport.camera.target),
    )

    # Scalar properties accept the same generator; normal output adds the typed
    # height-to-normal conversion rather than inserting a color ramp.
    for semantic, expected in (("roughness", "scalar"), ("metallic", "scalar"), ("normal", "rgba")):
        QTest.mouseClick(
            window.simple_material_panel.channel_buttons[semantic], Qt.MouseButton.LeftButton
        )
        QTest.mouseClick(window.browse_operations_button, Qt.MouseButton.LeftButton)
        _choose_card(window, "Patterns", "Checker Grid")
        QTest.mouseClick(window.operation_library.action, Qt.MouseButton.LeftButton)
        _wait_for_render(window)
        layer = window._layer()
        assert pipeline_output_type(layer.source, layer.transforms) == expected
    camera_after = (
        window.preview_viewport.camera.yaw,
        window.preview_viewport.camera.pitch,
        window.preview_viewport.camera.distance,
        tuple(window.preview_viewport.camera.target),
    )
    assert camera_before == camera_after, "ordinary layer edits moved the 3D camera"

    # The entire starter catalog remains browsable with genuine render samples.
    QTest.mouseClick(window.browse_operations_button, Qt.MouseButton.LeftButton)
    _choose_card(window, "Material Starters", "Brick")
    assert len(MATERIAL_STARTERS) == 18
    window.operation_library.search.clear()
    assert len(window.operation_library._items()) == 18

    # Add the existing Gradient Editor workflow as another layer.
    QTest.mouseClick(
        window.simple_material_panel.channel_buttons["base_color"], Qt.MouseButton.LeftButton
    )
    assert window._selected_output(window.document.recipe).semantic == "base_color"
    QTest.mouseClick(window.browse_operations_button, Qt.MouseButton.LeftButton)
    _choose_card(window, "Gradients and Colors", "Linear Gradient")
    layer_request_spy = QSignalSpy(window.operation_library.layerRequested)
    QTimer.singleShot(
        250,
        lambda: (
            QApplication.activeModalWidget().accept()
            if isinstance(QApplication.activeModalWidget(), QDialog)
            else None
        ),
    )
    QTest.mouseClick(window.operation_library.action, Qt.MouseButton.LeftButton)
    assert layer_request_spy.count() == 1
    _wait_for_render(window)
    assert any(
        layer.source.operation_id == "generator.linear_gradient"
        for output in window.document.recipe.outputs
        for layer in output.layers
    )

    QTest.mouseClick(window.authoring_mode_combo, Qt.MouseButton.LeftButton)
    QTest.keyClick(window.authoring_mode_combo, Qt.Key.Key_Down)
    QTest.keyClick(window.authoring_mode_combo, Qt.Key.Key_Enter)
    layer_list = window.layers_panel.layer_list
    before_order = [
        layer_list.item(index).data(Qt.ItemDataRole.UserRole) for index in range(layer_list.count())
    ]
    layer_list.setCurrentRow(0)
    QApplication.processEvents()
    assert window.layers_panel.down_button.isEnabled()
    QTest.mouseClick(window.layers_panel.down_button, Qt.MouseButton.LeftButton)
    after_move = [
        layer_list.item(index).data(Qt.ItemDataRole.UserRole) for index in range(layer_list.count())
    ]
    assert after_move != before_order, "layer reorder control did not change layer order"
    layer_list.setFocus()
    enabled_before = layer_list.currentItem().checkState()
    QTest.keyClick(layer_list, Qt.Key.Key_Space)
    assert layer_list.currentItem().checkState() != enabled_before

    # Save/reopen, undo/redo, and Advanced/Simple preserve the recipe.
    project_path = root / "native-roundtrip.archetexture"
    assert window.save_project(project_path)
    saved = load_project(project_path)
    assert window.open_project(project_path)
    assert window.document.recipe == saved
    window.undo_action.trigger()
    window.redo_action.trigger()
    assert window.authoring_mode_combo.currentIndex() == 1
    QTest.mouseClick(window.authoring_mode_combo, Qt.MouseButton.LeftButton)
    QTest.keyClick(window.authoring_mode_combo, Qt.Key.Key_Up)
    QTest.keyClick(window.authoring_mode_combo, Qt.Key.Key_Enter)
    assert window.authoring_mode_combo.currentIndex() == 0
    assert source_id in {
        layer.source.instance_id for layer in window._all_layers(window.document.recipe)
    }
    assert not np.array_equal(
        canvas_before_3d, _image_bytes(window.viewport, "2d-canvas-after-edits.png")
    )

    summary = {
        "result": "passed",
        "native_qt": True,
        "visible_window": window.isVisible(),
        "3d_available": window.preview_viewport.available,
        "3d_fallback": window.preview_viewport.unavailable_message
        if not window.preview_viewport.available
        else "",
        "library_patterns_distinct": True,
        "browsing_non_destructive": True,
        "typed_property_pipelines": True,
        "camera_unchanged": True,
        "all_starters_accessible": len(MATERIAL_STARTERS),
        "saved_recipe_roundtrip": True,
    }
    Path(os.environ["ATX31_REPORT"]).write_text(json.dumps(summary, indent=2), encoding="utf-8")
    window.close()
    QApplication.processEvents()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
