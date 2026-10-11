from __future__ import annotations

import copy
import faulthandler
import json
import os
import time
from pathlib import Path

import numpy as np
from PySide6.QtCore import QPoint, Qt, QTimer
from PySide6.QtGui import QImage
from PySide6.QtTest import QTest
from PySide6.QtWidgets import (
    QApplication,
    QColorDialog,
    QDialogButtonBox,
    QLineEdit,
)

from archetexture.color.ramp import ColorRamp, ColorStop
from archetexture.core.defaults import default_recipe
from archetexture.core.material_starters import create_material_starter
from archetexture.core.recipe import LayerRecipe, OperationInstance
from archetexture.core.serialization import load_project, save_project
from archetexture.ui.gradient_editor import GradientEditorDialog
from archetexture.ui.main_window import MainWindow


def _wait_until(predicate, timeout: float = 30.0, message: str = "condition timed out") -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        QApplication.processEvents()
        if predicate():
            return
        QTest.qWait(20)
    raise AssertionError(message)


def _capture(widget, path: Path) -> np.ndarray:
    QApplication.processEvents()
    image = widget.grab().toImage().convertToFormat(QImage.Format.Format_RGBA8888)
    assert not image.isNull(), f"could not capture {widget.objectName()}"
    image.save(str(path))
    bits = image.bits()
    pixels = np.frombuffer(bits, dtype=np.uint8, count=image.sizeInBytes())
    return pixels.reshape(image.height(), image.width(), 4).copy()


def _qimage_bytes(image: QImage) -> np.ndarray:
    bits = image.bits()
    return np.frombuffer(bits, dtype=np.uint8, count=image.sizeInBytes()).copy()


def _output_id(recipe, semantic: str) -> str:
    return next(output.output_id for output in recipe.outputs if output.semantic == semantic)


def _edit_color(editor, value: str) -> None:
    def complete_color_dialog() -> None:
        dialog = QApplication.activeModalWidget()
        print(f"Color picker callback for {value}: {type(dialog).__name__}", flush=True)
        assert isinstance(dialog, QColorDialog), "native color picker did not open"
        value_entry = dialog.findChild(QLineEdit, "qt_colorname_lineedit")
        assert value_entry is not None, "color picker has no editable color value"
        value_entry.setFocus(Qt.FocusReason.OtherFocusReason)
        QTest.keyClick(value_entry, Qt.Key.Key_A, Qt.KeyboardModifier.ControlModifier)
        QTest.keyClicks(value_entry, value)
        buttons = dialog.findChild(QDialogButtonBox)
        assert buttons is not None
        QTest.mouseClick(
            buttons.button(QDialogButtonBox.StandardButton.Ok), Qt.MouseButton.LeftButton
        )

    QTimer.singleShot(150, complete_color_dialog)
    QTest.mouseClick(editor.color_button, Qt.MouseButton.LeftButton)


def _configure_gradient(
    window: MainWindow, baseline_recipe, baseline_pixels: np.ndarray, evidence_dir: Path
) -> None:
    print("Waiting for Gradient Editor", flush=True)
    dialog = QApplication.activeModalWidget()
    assert isinstance(dialog, GradientEditorDialog), "Gradient Editor did not open"
    print("Gradient Editor opened", flush=True)
    original_ramp_count = len(dialog.ramp_editor.ramp.stops)
    angle_before = dialog.angle.value()
    dialog.angle.setFocus(Qt.FocusReason.OtherFocusReason)
    QTest.keyClick(dialog.angle, Qt.Key.Key_Up)
    assert dialog.angle.value() > angle_before, "direction did not respond to keyboard input"

    _edit_color(dialog.ramp_editor, "#1769c2")
    print("First gradient color edited", flush=True)
    ramp_preview = dialog.ramp_editor.preview
    end_stop = QPoint(
        round(ramp_preview.x_from_position(1.0)), ramp_preview.track_rect().bottom() + 9
    )
    QTest.mouseClick(ramp_preview, Qt.MouseButton.LeftButton, pos=end_stop)
    _edit_color(dialog.ramp_editor, "#f0b43c")
    print("Second gradient color edited", flush=True)

    QTest.mouseClick(dialog.ramp_editor.add_button, Qt.MouseButton.LeftButton)
    assert len(dialog.ramp_editor.ramp.stops) == original_ramp_count + 1

    dialog.kind.setFocus(Qt.FocusReason.OtherFocusReason)
    QTest.keyClick(dialog.kind, Qt.Key.Key_Down)
    assert dialog.kind.currentData() == "generator.radial_gradient"
    assert dialog.radius.isVisible()
    for _ in range(8):
        QTest.keyClick(dialog.radius, Qt.Key.Key_Up)
    assert dialog.radius.value() > 0.5
    dialog.opacity.setFocus(Qt.FocusReason.OtherFocusReason)
    QTest.keyClick(dialog.opacity, Qt.Key.Key_Down)
    assert dialog.opacity.value() < 1.0
    print("Gradient shape and opacity edited", flush=True)
    _wait_for_render(window)
    live_gradient = _capture(window.viewport, evidence_dir / "atx30-gradient-live-before-apply.png")
    live_difference = float(
        np.mean(np.abs(baseline_pixels.astype(np.float32) - live_gradient.astype(np.float32)))
    )
    assert live_difference > 1.0, "gradient controls did not update the 2D canvas live"
    assert window.document.recipe == baseline_recipe, (
        "live preview changed the document before Apply"
    )
    assert not window.document.dirty, "cancelable gradient edits dirtied the document early"
    print("Live gradient preview verified", flush=True)
    QTest.mouseClick(
        dialog.buttons.button(QDialogButtonBox.StandardButton.Apply), Qt.MouseButton.LeftButton
    )


def _add_operation(window: MainWindow, operation: str, configure=None) -> None:
    button = window.simple_material_panel.add_operation_button
    menu = button.menu()
    action = next(item for item in menu.actions() if item.data() == operation)

    def choose_action() -> None:
        if configure is not None:
            QTimer.singleShot(150, configure)
        print(f"Choosing Add operation: {operation}", flush=True)
        QTest.mouseClick(menu, Qt.MouseButton.LeftButton, pos=menu.actionGeometry(action).center())

    QTimer.singleShot(150, choose_action)
    QTest.mouseClick(button, Qt.MouseButton.LeftButton)
    QApplication.processEvents()
    print(f"Add operation complete: {operation}", flush=True)


def _wait_for_render(window: MainWindow) -> None:
    request_id = window.render_coordinator.latest_request_id
    _wait_until(
        lambda: (
            window._latest_displayed_request_id is not None
            and window._latest_displayed_request_id >= request_id
        ),
        message=f"2D render request {request_id} did not complete",
    )


def _wait_for_preview(window: MainWindow) -> None:
    request_id = window._preview_request_id
    _wait_until(
        lambda: (
            window.preview_viewport.snapshot is not None
            and window.preview_viewport.snapshot.request_id >= request_id
        ),
        timeout=90,
        message=f"3D preview request {request_id} did not complete",
    )


def _switch_combo_by_key(combo, key: Qt.Key) -> None:
    QTest.mouseClick(combo, Qt.MouseButton.LeftButton)
    QTest.keyClick(combo, key)
    QTest.keyClick(combo, Qt.Key.Key_Enter)
    QApplication.processEvents()


def main() -> int:
    if os.name != "nt":
        raise RuntimeError("ATX 30 native scenario requires Windows Qt.")
    report_path = Path(os.environ["ATX30_REPORT"])
    faulthandler.dump_traceback_later(45, file=__import__("sys").stderr)
    evidence_dir = Path(os.environ["ATX30_EVIDENCE_DIR"])
    evidence_dir.mkdir(parents=True, exist_ok=True)
    starter = os.environ.get("ATX30_STARTER", "blank")
    recipe = default_recipe() if starter == "blank" else create_material_starter(starter)
    base_color_output_id = _output_id(recipe, "base_color")
    if starter == "blank":
        recipe.width = recipe.height = 128
        recipe.output(base_color_output_id).layers = [
            LayerRecipe(
                "layer-blank-background",
                "Background",
                OperationInstance(
                    "source-blank-background",
                    "generator.constant",
                    1,
                    parameters={"value": 0.5},
                ),
                color_ramp=ColorRamp(
                    (
                        ColorStop(0.0, (0.42, 0.42, 0.42, 1.0)),
                        ColorStop(1.0, (0.42, 0.42, 0.42, 1.0)),
                    )
                ),
            )
        ]
    app = QApplication.instance() or QApplication([])
    window = MainWindow(recipe)
    window._confirm_discard = lambda: True
    window.resize(1500, 960)
    window.show()
    assert QTest.qWaitForWindowExposed(window)
    assert app.platformName().lower() in {"windows", "windows:fonts"}
    _wait_for_render(window)
    window.preview_controls.resolution.setCurrentIndex(
        window.preview_controls.resolution.findData(512)
    )

    initial_recipe = copy.deepcopy(window.document.recipe)
    initial_history = window.document.history.index
    camera_before = (
        window.preview_viewport.camera.yaw,
        window.preview_viewport.camera.pitch,
        window.preview_viewport.camera.distance,
        tuple(window.preview_viewport.camera.target),
    )
    _switch_combo_by_key(window.workspace_mode_combo, Qt.Key.Key_Down)
    _wait_for_preview(window)
    initial_3d = window.preview_viewport.grabFramebuffer().convertToFormat(
        QImage.Format.Format_RGBA8888
    )
    initial_3d.save(str(evidence_dir / "atx30-before-3d.png"))
    _switch_combo_by_key(window.workspace_mode_combo, Qt.Key.Key_Up)
    initial_2d = _capture(window.viewport, evidence_dir / "atx30-before-2d.png")
    color_button = window.simple_material_panel.channel_buttons["base_color"]
    QTest.mouseClick(color_button, Qt.MouseButton.LeftButton)
    _add_operation(
        window,
        "gradient",
        lambda: _configure_gradient(window, initial_recipe, initial_2d, evidence_dir),
    )
    _wait_for_render(window)
    assert window.document.history.index == initial_history + 1
    gradient = window.document.recipe.output(base_color_output_id).layers[-1]
    assert gradient.source.operation_id == "generator.radial_gradient"
    assert len(gradient.color_ramp.stops) >= 3
    assert gradient.opacity < 1.0
    updated_2d = _capture(window.viewport, evidence_dir / "atx30-after-gradient-2d.png")
    difference_2d = float(
        np.mean(np.abs(initial_2d.astype(np.float32) - updated_2d.astype(np.float32)))
    )
    assert difference_2d > 1.0, f"gradient changed no visible 2D pixels ({difference_2d:.3f})"
    _switch_combo_by_key(window.workspace_mode_combo, Qt.Key.Key_Down)
    _wait_for_preview(window)
    gradient_3d = window.preview_viewport.grabFramebuffer().convertToFormat(
        QImage.Format.Format_RGBA8888
    )
    gradient_3d.save(str(evidence_dir / "atx30-after-gradient-3d.png"))
    initial_3d_array = _qimage_bytes(initial_3d)
    gradient_3d_array = _qimage_bytes(gradient_3d)
    assert initial_3d_array.shape == gradient_3d_array.shape
    difference_3d = float(
        np.mean(np.abs(initial_3d_array.astype(np.float32) - gradient_3d_array.astype(np.float32)))
    )
    assert difference_3d > 0.25, f"gradient changed no visible 3D pixels ({difference_3d:.3f})"
    _switch_combo_by_key(window.workspace_mode_combo, Qt.Key.Key_Up)

    _add_operation(window, "pattern")
    pattern_layer = window.document.recipe.output(base_color_output_id).layers[-1]
    pattern_item = next(
        item
        for item in (
            window.layers_panel.layer_list.item(index)
            for index in range(window.layers_panel.layer_list.count())
        )
        if item.data(Qt.ItemDataRole.UserRole) == pattern_layer.layer_id
    )
    row_rect = window.layers_panel.layer_list.visualItemRect(pattern_item)
    initial_pattern_state = pattern_item.checkState()
    history_before_toggle = window.document.history.index
    QTest.mouseClick(
        window.layers_panel.layer_list.viewport(),
        Qt.MouseButton.LeftButton,
        pos=QPoint(row_rect.left() + 9, row_rect.center().y()),
    )
    QApplication.processEvents()
    assert window.document.recipe.output(base_color_output_id).layers[-1].enabled != (
        initial_pattern_state == Qt.CheckState.Checked
    ), "pattern layer visibility control did not toggle"
    assert window.document.history.index == history_before_toggle + 1
    _wait_for_render(window)
    _capture(window.viewport, evidence_dir / "atx30-pattern-hidden-2d.png")
    window.undo_action.trigger()
    assert window.document.recipe.output(base_color_output_id).layers[-1].enabled
    window.redo_action.trigger()
    assert not window.document.recipe.output(base_color_output_id).layers[-1].enabled

    recipe_before_switches = window.document.recipe
    selected_before_switches = (window._selected_output_id, window._selected_layer_id)
    _switch_combo_by_key(window.authoring_mode_combo, Qt.Key.Key_Down)
    assert window.document.recipe == recipe_before_switches
    _switch_combo_by_key(window.authoring_mode_combo, Qt.Key.Key_Up)
    assert window.document.recipe == recipe_before_switches
    assert (window._selected_output_id, window._selected_layer_id) == selected_before_switches

    saved_path = evidence_dir / "atx30-journey.archetexture"
    saved_recipe = window.document.recipe
    save_project(saved_recipe, saved_path)
    assert load_project(saved_path) == saved_recipe

    normal_button = window.simple_material_panel.channel_buttons["normal"]
    QTest.mouseClick(normal_button, Qt.MouseButton.LeftButton)
    _switch_combo_by_key(window.authoring_mode_combo, Qt.Key.Key_Down)
    _switch_combo_by_key(window.workspace_mode_combo, Qt.Key.Key_Down)
    _wait_for_preview(window)
    valid_frame = window.preview_viewport.grabFramebuffer().convertToFormat(
        QImage.Format.Format_RGBA8888
    )
    valid_frame.save(str(evidence_dir / "atx30-normal-before-rejected-edit.png"))
    valid_snapshot = window.preview_viewport.snapshot
    _wait_for_render(window)
    valid_normal = window.document.recipe
    history_before_rejection = window.document.history.index
    normal_layer = window._layer()
    converter = normal_layer.transforms[0]
    converter_item = next(
        item
        for item in (
            window.pipeline_panel.transform_list.item(index)
            for index in range(window.pipeline_panel.transform_list.count())
        )
        if item.data(Qt.ItemDataRole.UserRole) == converter.instance_id
    )
    item_rect = window.pipeline_panel.transform_list.visualItemRect(converter_item)
    QTest.mouseClick(
        window.pipeline_panel.transform_list.viewport(),
        Qt.MouseButton.LeftButton,
        pos=QPoint(item_rect.left() + 8, item_rect.center().y()),
    )
    QApplication.processEvents()
    assert window.document.recipe == valid_normal
    assert window.document.history.index == history_before_rejection
    assert window._layer().transforms[0].enabled
    assert "Edit rejected" in window.statusBar().currentMessage()
    restored_item = window.pipeline_panel.transform_list.item(0)
    assert restored_item.checkState() == Qt.CheckState.Checked
    unchanged_frame = window.preview_viewport.grabFramebuffer().convertToFormat(
        QImage.Format.Format_RGBA8888
    )
    unchanged_frame.save(str(evidence_dir / "atx30-normal-after-rejected-edit.png"))
    assert valid_frame == unchanged_frame, "rejected normal edit replaced the last good sphere"
    assert window.preview_viewport.snapshot is valid_snapshot

    _wait_for_preview(window)
    material_frame = window.preview_viewport.grabFramebuffer().convertToFormat(
        QImage.Format.Format_RGBA8888
    )
    material_frame.save(str(evidence_dir / "atx30-final-3d.png"))
    frame_bits = material_frame.bits()
    frame = np.frombuffer(frame_bits, dtype=np.uint8, count=material_frame.sizeInBytes()).reshape(
        material_frame.height(), material_frame.width(), 4
    )
    center = frame[
        frame.shape[0] // 4 : 3 * frame.shape[0] // 4,
        frame.shape[1] // 4 : 3 * frame.shape[1] // 4,
        :3,
    ]
    assert int(center.max()) - int(center.min()) > 20, "material sphere preview is nearly black"
    assert window.preview_viewport.snapshot is not None
    assert window.preview_viewport.available
    camera_after = (
        window.preview_viewport.camera.yaw,
        window.preview_viewport.camera.pitch,
        window.preview_viewport.camera.distance,
        tuple(window.preview_viewport.camera.target),
    )
    assert camera_after == camera_before, "material edits unexpectedly moved the preview camera"

    window.close()
    QApplication.processEvents()
    faulthandler.cancel_dump_traceback_later()
    report_path.write_text(
        json.dumps(
            {
                "result": "passed",
                "starter": starter,
                "platform": app.platformName(),
                "gradient_type": gradient.source.operation_id,
                "gradient_stops": len(gradient.color_ramp.stops),
                "gradient_angle": gradient.source.parameters.get("angle"),
                "gradient_radius": gradient.source.parameters.get("radius"),
                "gradient_opacity": gradient.opacity,
                "2d_frame_mean_difference": difference_2d,
                "3d_frame_mean_difference": difference_3d,
                "layer_visibility_and_history": True,
                "undo_redo": True,
                "save_reopen": True,
                "advanced_simple_preserved_selection": True,
                "normal_incompatible_edit_rejected_and_restored": True,
                "3d_material_visible": True,
                "blank_material_supported": (
                    starter != "blank"
                    or initial_recipe.output(base_color_output_id).layers[0].name == "Background"
                ),
                "camera_unchanged": camera_after == camera_before,
                "closed_cleanly": True,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
