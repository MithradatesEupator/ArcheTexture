from __future__ import annotations

import json
import os
import traceback
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDoubleSpinBox, QSpinBox

from archetexture.core.defaults import default_recipe
from archetexture.core.material_starters import create_material_starter
from archetexture.ui.main_window import MainWindow


def _edit_numeric_control(window: MainWindow, counts: dict[str, int]) -> None:
    controls = window.property_editor.findChildren(QDoubleSpinBox)
    if not controls:
        controls = window.property_editor.findChildren(QSpinBox)
    if not controls:
        return
    control = controls[0]
    old_value = control.value()
    new_value = min(control.maximum(), old_value + max(control.singleStep(), 0.1))
    if new_value == old_value:
        new_value = max(control.minimum(), old_value - max(control.singleStep(), 0.1))
    control.setFocus()
    QTest.keyClick(control, Qt.Key.Key_A, Qt.KeyboardModifier.ControlModifier)
    QTest.keyClicks(control, str(new_value))
    QTest.keyClick(control, Qt.Key.Key_Return)
    QApplication.processEvents()
    counts["parameter_edits"] += 1


def _edit_source(window: MainWindow, counts: dict[str, int]) -> None:
    selector = window.pipeline_panel.source_selector
    current = str(selector.currentData())
    candidate = "generator.constant"
    if candidate == current:
        candidate = "generator.white_noise"
    index = selector.findData(candidate)
    if index >= 0:
        selector.setCurrentIndex(index)
        QApplication.processEvents()
        counts["source_selections"] += 1
        _edit_numeric_control(window, counts)


def _edit_transforms(window: MainWindow, counts: dict[str, int]) -> None:
    panel = window.pipeline_panel
    for _ in range(2):
        if panel.transform_selector.count() == 0:
            break
        panel.transform_selector.setCurrentIndex(0)
        panel.add_button.click()
        QApplication.processEvents()
        counts["transforms_added"] += 1
    if panel.transform_list.count() == 0:
        return
    panel.transform_list.setCurrentRow(0)
    QApplication.processEvents()
    _edit_numeric_control(window, counts)
    item = panel.transform_list.item(0)
    item.setCheckState(
        Qt.CheckState.Unchecked
        if item.checkState() == Qt.CheckState.Checked
        else Qt.CheckState.Checked
    )
    QApplication.processEvents()
    counts["transforms_toggled"] += 1
    if panel.transform_list.count() > 1:
        panel.transform_list.setCurrentRow(1)
        panel.up_button.click()
        QApplication.processEvents()
        counts["transforms_reordered"] += 1
    panel.transform_list.setCurrentRow(0)
    panel.remove_button.click()
    QApplication.processEvents()
    counts["transforms_removed"] += 1


def _edit_layer_controls(window: MainWindow, layer_id: str, counts: dict[str, int]) -> None:
    panel = window.layers_panel
    opacity = panel.opacity.value()
    panel.opacity.setValue(max(0.0, min(1.0, opacity - 0.1)))
    if panel.opacity.value() != opacity:
        counts["opacity_edits"] += 1
    if panel.blend.count() > 1:
        panel.blend.setCurrentIndex((panel.blend.currentIndex() + 1) % panel.blend.count())
        counts["blend_edits"] += 1
    if panel.add_mask_button.isEnabled():
        panel.add_mask_button.click()
        QApplication.processEvents()
        if window._layer().mask is not None:
            counts["mask_edits"] += 1
    ramp = window.color_ramp_editor
    if ramp._applicable:
        if ramp.ramp is None:
            ramp.create_ramp()
        else:
            ramp.add_stop()
        QApplication.processEvents()
        if ramp.ramp is not None:
            ramp.add_stop()
            QApplication.processEvents()
            counts["ramp_edits"] += 1


def _run_case() -> dict[str, int]:
    application = QApplication.instance() or QApplication([])
    if application.platformName().lower() != "windows":
        raise RuntimeError(f"Expected native Windows Qt, got {application.platformName()!r}")

    starter_name = os.environ.get("ATX25_STARTER", "default")
    if starter_name.casefold() == "default":
        recipe = default_recipe()
        recipe.width = recipe.height = 32
    else:
        recipe = create_material_starter(starter_name, width=32, height=32)

    window = MainWindow(recipe)
    window._confirm_discard = lambda: True
    window.show()
    application.processEvents()
    counts = {
        "output_switches": 0,
        "layer_selections": 0,
        "source_selections": 0,
        "parameter_edits": 0,
        "transforms_added": 0,
        "transforms_toggled": 0,
        "transforms_reordered": 0,
        "transforms_removed": 0,
        "opacity_edits": 0,
        "blend_edits": 0,
        "mask_edits": 0,
        "ramp_edits": 0,
        "undo_redo_pairs": 0,
        "preview_toggles": 0,
    }
    outputs = list(window.document.recipe.outputs)

    try:
        # Revisit all outputs repeatedly; this includes the referenced Normal
        # output that triggered the confirmed editor rebuild recursion.
        for _ in range(3):
            for output in outputs:
                index = window.output_selector.findData(output.output_id)
                window.output_selector.setCurrentIndex(index)
                application.processEvents()
                counts["output_switches"] += 1

        for output in list(window.document.recipe.outputs):
            index = window.output_selector.findData(output.output_id)
            window.output_selector.setCurrentIndex(index)
            application.processEvents()
            for layer in list(window._layers_for(window.document.recipe)):
                row = next(
                    row
                    for row in range(window.layers_panel.layer_list.count())
                    if window.layers_panel.layer_list.item(row).data(Qt.ItemDataRole.UserRole)
                    == layer.layer_id
                )
                window.layers_panel.layer_list.setCurrentRow(row)
                application.processEvents()
                counts["layer_selections"] += 1
                _edit_source(window, counts)
                _edit_transforms(window, counts)
                _edit_layer_controls(window, layer.layer_id, counts)
                if window.document.can_undo:
                    window.undo()
                    application.processEvents()
                    window.redo()
                    application.processEvents()
                    counts["undo_redo_pairs"] += 1

        if window.workspace_mode_combo.findData("3D Material") >= 0:
            window.workspace_mode_combo.setCurrentIndex(
                window.workspace_mode_combo.findData("3D Material")
            )
            for _ in range(100):
                QTest.qWait(20)
                application.processEvents()
                if window.preview_viewport.available or window.preview_unavailable_label.text() != (
                    "Initializing 3D material preview…"
                ):
                    break
            counts["preview_gl_available"] = int(window.preview_viewport.available)
            counts["preview_fallback_visible"] = int(
                not window.preview_viewport.available
                and bool(window.preview_unavailable_label.text())
            )
            if not window.preview_viewport.available and not counts["preview_fallback_visible"]:
                raise AssertionError("3D preview neither initialized nor reported its fallback")
            application.processEvents()
            window.workspace_mode_combo.setCurrentIndex(
                window.workspace_mode_combo.findData("2D Texture")
            )
            application.processEvents()
            counts["preview_toggles"] += 1
        for _ in range(100):
            application.processEvents()
            if window.viewport.rendered_field is not None:
                break
            QTest.qWait(20)
        if window.viewport.rendered_field is None:
            raise AssertionError("The 2D workspace did not produce a rendered field")
        if not window.isVisible():
            raise AssertionError("The ArcheTexture main window was not visible during automation")
        if window.viewport is None:
            raise AssertionError("The 2D workspace did not initialize")
        return counts
    finally:
        window.close()
        application.processEvents()


def main() -> int:
    report_path = Path(os.environ["ATX25_REPORT"])
    report = {
        "starter": os.environ.get("ATX25_STARTER", "default"),
        "qt_platform": "windows",
        "visible_window": False,
        "result": "failed",
    }
    try:
        report["counts"] = _run_case()
        report["visible_window"] = True
        report["result"] = "passed"
    except BaseException as exc:
        report["error"] = f"{type(exc).__name__}: {exc}"
        report["traceback"] = traceback.format_exc()
        print(report["traceback"])
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return 0 if report["result"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
