from __future__ import annotations

import json
import os
import time
from pathlib import Path

import numpy as np
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QImage
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QColorDialog, QDialogButtonBox, QLineEdit

from archetexture.core.defaults import default_recipe
from archetexture.core.material_starters import MATERIAL_STARTERS, create_material_starter
from archetexture.core.serialization import load_project
from archetexture.render.engine import RenderEngine
from archetexture.ui.main_window import MainWindow
from archetexture.ui.numeric_control import NumericControl
from archetexture.ui.operation_library import OPERATION_PRESETS


def _wait(predicate, message: str, timeout: float = 75.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        QApplication.processEvents()
        if predicate():
            return
        QTest.qWait(20)
    raise AssertionError(message)


def _capture(widget, filename: str) -> np.ndarray:
    QTest.qWait(100)
    image = widget.grab().toImage().convertToFormat(QImage.Format.Format_RGBA8888)
    assert not image.isNull(), f"Could not capture {widget.objectName()}"
    path = Path(os.environ["ATX32_EVIDENCE_DIR"]) / filename
    image.save(str(path))
    return np.frombuffer(image.bits(), dtype=np.uint8, count=image.sizeInBytes()).copy()


def _wait_for_render(window: MainWindow) -> None:
    target = window.render_coordinator.latest_request_id
    _wait(
        lambda: (
            window._latest_displayed_request_id is not None
            and window._latest_displayed_request_id >= target
        ),
        f"2D render {target} did not complete",
    )


def _preset(name: str):
    return next(item for item in OPERATION_PRESETS if item.name == name)


def _choose_library_item(window: MainWindow, category: str, query: str) -> None:
    QTest.mouseClick(window.browse_operations_button, Qt.MouseButton.LeftButton)
    library = window.operation_library
    library.mode.setCurrentText(category)
    library.search.setText(query)
    _wait(lambda: bool(library._cards), f"Library item not found: {query}")
    key = next(iter(library._cards))
    QTest.mouseClick(library._cards[key][1], Qt.MouseButton.LeftButton)
    if not key.startswith("starter:") and not key.startswith("image:"):
        _wait(lambda: library.sample.pixmap() is not None, f"Sample did not render: {query}")


def _add_pattern(window: MainWindow, name: str) -> None:
    _choose_library_item(window, "Patterns", name)
    QTest.mouseClick(window.operation_library.action, Qt.MouseButton.LeftButton)
    _wait_for_render(window)
    assert window.simple_inspector_pages.currentWidget() is window.simple_edit_page
    assert window._layer().source.operation_id == _preset(name).operation_id


def _edit_numeric(window: MainWindow, identifier: str, value: str | None = None) -> float:
    control = window.property_editor.findChild(NumericControl, f"parameter-{identifier}")
    assert control is not None, f"Missing contextual parameter {identifier}"
    assert control.decrement.geometry().center().x() < control.increment.geometry().center().x()
    original = float(control.value())
    QTest.mouseClick(control.increment, Qt.MouseButton.LeftButton)
    if value is not None:
        control.editor.setFocus()
        control.editor.selectAll()
        QTest.keyClicks(control.editor, value)
        QTest.keyClick(control.editor, Qt.Key.Key_Return)
    assert window._edit_draft_recipe is not None
    return original


def _apply(window: MainWindow) -> None:
    assert window._edit_draft_recipe is not None
    history_before = window.document.history.index
    QTest.mouseClick(window.apply_layer_edit_button, Qt.MouseButton.LeftButton)
    assert window._edit_draft_recipe is None
    assert window.document.history.index == history_before + 1
    _wait_for_render(window)


def _set_color_in_native_dialog(window: MainWindow, color: str) -> None:
    def enter_color() -> None:
        dialog = QApplication.activeModalWidget()
        assert isinstance(dialog, QColorDialog), "Color picker did not open"
        field = dialog.findChild(QLineEdit, "qt_colorname_lineedit")
        assert field is not None, "Color picker does not expose its color value field"
        field.setFocus()
        QTest.keyClick(field, Qt.Key.Key_A, Qt.KeyboardModifier.ControlModifier)
        QTest.keyClicks(field, color)
        buttons = dialog.findChild(QDialogButtonBox)
        assert buttons is not None
        QTest.mouseClick(
            buttons.button(QDialogButtonBox.StandardButton.Ok), Qt.MouseButton.LeftButton
        )

    QTimer.singleShot(250, enter_color)
    QTest.mouseClick(window.color_ramp_editor.color_button, Qt.MouseButton.LeftButton)


def _capture_current_map(window: MainWindow, filename: str) -> np.ndarray:
    _wait_for_render(window)
    assert window._latest_render_result is not None
    image = _capture(window.viewport, filename)
    pixels = np.asarray(window._latest_render_result.rgba_field)
    assert np.isfinite(pixels).all()
    assert float(pixels.std()) > 0.01, f"{filename} has no visible variation"
    return image


def main() -> int:
    evidence = Path(os.environ["ATX32_EVIDENCE_DIR"])
    evidence.mkdir(parents=True, exist_ok=True)
    QApplication.instance() or QApplication([])
    window = MainWindow(default_recipe())
    window._confirm_discard = lambda: True
    window.resize(1560, 980)
    window.show()
    window.workspace_mode_combo.setCurrentIndex(0)
    window._select_simple_channel("base_color")
    _wait_for_render(window)
    _wait(
        lambda: window.preview_viewport.available or window.preview_viewport._gl_error,
        "Native 3D viewport did not initialize or report its fallback",
    )

    # Brick: add, change mortar by clicking the horizontal control, and cancel.
    _add_pattern(window, "Brick · Standard")
    original_recipe = window.document.recipe
    original_index = window.document.history.index
    before_brick = _capture_current_map(window, "brick-before.png")
    _edit_numeric(window, "mortar", "0.14")
    assert window.document.recipe == original_recipe, "Preview edit committed before Apply"
    assert window.document.history.index == original_index
    _wait_for_render(window)
    _capture(window.viewport, "brick-mortar-preview.png")
    QTest.mouseClick(window.cancel_layer_edit_button, Qt.MouseButton.LeftButton)
    assert window.document.recipe == original_recipe
    assert window.document.history.index == original_index
    _wait_for_render(window)
    assert np.array_equal(before_brick, _capture(window.viewport, "brick-cancel-restored.png"))

    # Apply one mortar edit and recolor ramp stops with the native picker.
    _edit_numeric(window, "mortar", "0.18")
    _wait_for_render(window)
    _apply(window)
    brick_layer = window._layer()
    assert brick_layer.source.parameters["mortar"] == 0.18
    assert window.color_ramp_editor.ramp is not None
    window.color_ramp_editor.add_button.click()
    _set_color_in_native_dialog(window, "#d86a31")
    assert window._edit_draft_recipe is not None
    _wait_for_render(window)
    _capture(window.viewport, "brick-color-preview.png")
    _apply(window)
    brick_color = _capture_current_map(window, "brick-final.png")
    assert not np.array_equal(before_brick, brick_color)

    # Wood: ring count and distortion share one contextual edit transaction.
    _add_pattern(window, "Wood · Fine Grain")
    _edit_numeric(window, "rings", "34")
    _edit_numeric(window, "distortion", "8.5")
    _wait_for_render(window)
    _capture(window.viewport, "wood-customized.png")
    _apply(window)
    wood = _capture_current_map(window, "wood-final.png")
    assert not np.array_equal(brick_color, wood)

    # Marble: edit its scale and vein frequency in the selected source context.
    _add_pattern(window, "Marble · Fine Veins")
    _edit_numeric(window, "scale", "4.1")
    _edit_numeric(window, "vein_frequency", "15")
    _wait_for_render(window)
    _capture(window.viewport, "marble-customized.png")
    _apply(window)
    marble = _capture_current_map(window, "marble-final.png")
    assert not np.array_equal(wood, marble)

    # Weave proves horizontal and vertical thread controls use the same editor.
    _add_pattern(window, "Weave")
    _edit_numeric(window, "threads_x", "17")
    _edit_numeric(window, "threads_y", "11")
    _apply(window)
    weave = _capture_current_map(window, "weave-final.png")
    assert not np.array_equal(marble, weave)

    # A gradient is added as a layer, with direction and color stops in context.
    _choose_library_item(window, "Gradients and Colors", "Linear Gradient")
    QTest.mouseClick(window.operation_library.action, Qt.MouseButton.LeftButton)
    _wait_for_render(window)
    assert window._layer().color_ramp is not None
    _edit_numeric(window, "angle", "62")
    window.color_ramp_editor.add_button.click()
    _set_color_in_native_dialog(window, "#258ac5")
    _wait_for_render(window)
    _capture(window.viewport, "gradient-customized.png")
    _apply(window)
    _capture_current_map(window, "gradient-final.png")

    # Roughness and Metalness are direct property maps and remain distinct from the base color.
    window.simple_material_panel.channel_buttons["roughness"].click()
    _add_pattern(window, "Fractal Noise")
    _edit_numeric(window, "scale", "6.5")
    _wait_for_render(window)
    roughness = _capture_current_map(window, "roughness-property.png")
    _apply(window)

    window.simple_material_panel.channel_buttons["metallic"].click()
    _add_pattern(window, "Marble · Broad Veins")
    _edit_numeric(window, "vein_frequency", "7")
    _wait_for_render(window)
    metalness = _capture_current_map(window, "metalness-property.png")
    _apply(window)
    assert not np.array_equal(roughness, metalness)

    # Surface Detail applies a valid Height-to-Normal conversion in its own editor.
    window.simple_material_panel.channel_buttons["normal"].click()
    _add_pattern(window, "Wood · Broad Rings")
    assert window._layer().transforms
    assert window._layer().transforms[0].operation_id == "transform.height_to_normal"
    _edit_numeric(window, "rings", "20")
    _wait_for_render(window)
    normal = _capture_current_map(window, "surface-detail-property.png")
    _apply(window)
    assert not np.array_equal(metalness, normal)

    # Combined material view is distinct from the directly edited property.
    camera = (
        window.preview_viewport.camera.yaw,
        window.preview_viewport.camera.pitch,
        window.preview_viewport.camera.distance,
        tuple(window.preview_viewport.camera.target),
    )
    window.preview_controls.resolution.setCurrentIndex(
        window.preview_controls.resolution.findData(512)
    )
    window.workspace_mode_combo.setCurrentIndex(1)
    material_request_id = window._preview_request_id
    _wait(
        lambda target_id=material_request_id: (
            window.preview_viewport._gl_error
            or (
                window.preview_viewport.snapshot is not None
                and window.preview_viewport.snapshot.request_id >= target_id
            )
        ),
        "Combined material preview did not render or report graceful fallback",
        timeout=100.0,
    )
    if window.preview_viewport.available:
        material_view = _capture(window.preview_viewport, "combined-material-sphere.png")
        assert window.preview_viewport.snapshot.maps["base_color"].std() > 0.01
        assert window.preview_viewport.snapshot.maps["roughness"].std() > 0.01
        assert window.preview_viewport.snapshot.maps["metallic"].std() > 0.01
        assert window.preview_viewport.snapshot.maps["normal"].std() > 0.01
        inspection_frames = [material_view]
        for mode in ("Base Color", "Roughness", "Metallic", "Normal"):
            window.preview_controls.mode.setCurrentText(mode)
            request_id = window._preview_request_id
            _wait(
                lambda target_id=request_id: (
                    window.preview_viewport.snapshot is not None
                    and window.preview_viewport.snapshot.request_id >= target_id
                ),
                f"{mode} inspection did not finish",
                timeout=90.0,
            )
            inspection_frames.append(
                _capture(
                    window.preview_viewport, f"inspection-{mode.lower().replace(' ', '-')}.png"
                )
            )
        assert all(
            not np.array_equal(first, second)
            for index, first in enumerate(inspection_frames)
            for second in inspection_frames[index + 1 :]
        ), "Material, Base Color, Roughness, Metallic, and Normal views were not distinct"
    assert window.preview_content_label.text().startswith("COMBINED MATERIAL")
    assert camera == (
        window.preview_viewport.camera.yaw,
        window.preview_viewport.camera.pitch,
        window.preview_viewport.camera.distance,
        tuple(window.preview_viewport.camera.target),
    )

    # All 18 starters still resolve, render valid output, and retain distinct names.
    starters = [
        create_material_starter(item.name, width=64, height=64) for item in MATERIAL_STARTERS
    ]
    assert len({item.name for item in MATERIAL_STARTERS}) == 18
    engine = RenderEngine()
    for starter in starters:
        result = engine.render(starter, width=64, height=64)
        pixels = np.asarray(result.rgba_field)
        assert pixels.shape[:2] == (64, 64)
        assert np.isfinite(pixels).all()
        assert float(pixels.std()) > 0.005, f"Starter rendered flat: {starter.outputs[0].name}"

    # Save/reopen retains committed parameters and layer identity; undo/redo round trips them.
    recipe_before_save = window.document.recipe
    identity = window._layer().layer_id
    window.undo_action.trigger()
    assert window.document.recipe != recipe_before_save
    window.redo_action.trigger()
    assert window.document.recipe == recipe_before_save
    project = Path(os.environ["ATX32_PROJECT_PATH"])
    assert window.save_project(project)
    assert load_project(project) == recipe_before_save
    assert window.open_project(project)
    assert window.document.recipe == recipe_before_save
    assert identity in {layer.layer_id for layer in window._all_layers(window.document.recipe)}

    summary = {
        "result": "passed",
        "native_qt": True,
        "visible_window": window.isVisible(),
        "3d_available": window.preview_viewport.available,
        "3d_fallback": ""
        if window.preview_viewport.available
        else window.preview_viewport.unavailable_message,
        "contextual_patterns": ["Brick", "Wood", "Marble", "Weave", "Gradient"],
        "edited_property_maps_distinct": True,
        "preview_transaction_cancel_apply_undo_redo": True,
        "native_color_picker": True,
        "solid_material_starters_rendered": len(starters),
        "save_reopen_identity": identity,
        "camera_unchanged": True,
    }
    Path(os.environ["ATX32_REPORT"]).write_text(json.dumps(summary, indent=2), encoding="utf-8")
    window.close()
    QApplication.processEvents()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
