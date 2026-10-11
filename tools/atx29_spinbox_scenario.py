from __future__ import annotations

import json
import os
import time
from pathlib import Path

from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QWheelEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import (
    QApplication,
    QDoubleSpinBox,
    QScrollArea,
    QSpinBox,
    QStyle,
    QStyleOptionSpinBox,
    QWidget,
)

from archetexture.core.defaults import default_recipe
from archetexture.core.material_starters import create_material_starter
from archetexture.core.serialization import load_project, save_project
from archetexture.ui.main_window import MainWindow


def _arrow_rect(spin: QDoubleSpinBox, up: bool):
    option = QStyleOptionSpinBox()
    option.initFrom(spin)
    option.frame = spin.hasFrame()
    option.buttonSymbols = spin.buttonSymbols()
    option.stepEnabled = spin.stepEnabled()
    subcontrol = QStyle.SubControl.SC_SpinBoxUp if up else QStyle.SubControl.SC_SpinBoxDown
    return spin.style().subControlRect(QStyle.ComplexControl.CC_SpinBox, option, subcontrol, spin)


def _history_step(window: MainWindow, spin: QDoubleSpinBox, action, expected_delta: int = 1):
    before_value = spin.value()
    before_index = window.document.history.index
    action()
    QApplication.processEvents()
    assert spin.value() != before_value, "spin-box input did not change its value"
    assert window.document.history.index == before_index + expected_delta, (
        f"edit created {window.document.history.index - before_index} history entries; "
        f"expected {expected_delta}"
    )


def _click_arrow(spin: QDoubleSpinBox, up: bool) -> None:
    QTest.mouseClick(
        spin,
        Qt.MouseButton.LeftButton,
        pos=_arrow_rect(spin, up).center(),
    )


def _scroll_owner(widget):
    parent = widget.parentWidget()
    while parent is not None:
        if isinstance(parent, QScrollArea):
            return parent
        parent = parent.parentWidget()
    return None


def main() -> int:
    if os.name != "nt":
        raise RuntimeError("This scenario requires native Windows Qt.")
    report_path = Path(os.environ["ATX29_REPORT"])
    starter = os.environ.get("ATX29_STARTER", "default")
    recipe = default_recipe() if starter == "default" else create_material_starter(starter)
    app = QApplication.instance() or QApplication([])
    window = MainWindow(recipe)
    window._confirm_discard = lambda: True
    window.resize(1500, 950)
    window.show()
    assert QTest.qWaitForWindowExposed(window)
    assert app.platformName().lower() in {"windows", "windows:fonts"}

    start_camera = (
        window.preview_viewport.camera.yaw,
        window.preview_viewport.camera.pitch,
        window.preview_viewport.camera.distance,
        tuple(window.preview_viewport.camera.target),
    )
    output_before_edits = window._selected_output_id
    layer_before_edits = window._selected_layer_id
    edited_controls = []
    for control_name in ("Scale", "Wear"):
        spin = window.simple_material_panel.control_spins[control_name]
        destroyed: list[bool] = []
        spin.destroyed.connect(lambda *_args, events=destroyed: events.append(True))
        identity = id(spin)
        start_value = spin.value()
        scroll = _scroll_owner(spin)
        scroll_value = scroll.verticalScrollBar().value() if scroll else None

        _history_step(
            window,
            spin,
            lambda spin=spin: _click_arrow(spin, True),
        )
        assert QApplication.focusWidget() is spin, "spin-box focus was lost during its commit"
        assert (scroll.verticalScrollBar().value() if scroll else None) == scroll_value, (
            "editor scroll position changed during a simple control edit"
        )
        _history_step(
            window,
            spin,
            lambda spin=spin: _click_arrow(spin, False),
        )

        hold_up = spin.value() < spin.maximum()
        hold_direction = _arrow_rect(spin, hold_up).center()
        before_index = window.document.history.index
        spin.setFocus(Qt.FocusReason.OtherFocusReason)
        QTest.mousePress(spin, Qt.MouseButton.LeftButton, pos=hold_direction)
        QTest.qWait(650)
        QTest.mouseRelease(spin, Qt.MouseButton.LeftButton, pos=hold_direction)
        QApplication.processEvents()
        assert spin.value() != start_value, "held arrow button did not change the value"
        assert window.document.history.index == before_index + 1, (
            "holding an arrow button created more than one history entry"
        )

        before_index = window.document.history.index
        target = min(spin.maximum(), start_value + max(2.0, spin.singleStep() * 2))
        spin.setFocus(Qt.FocusReason.OtherFocusReason)
        spin.lineEdit().selectAll()
        QTest.keyClicks(spin.lineEdit(), f"{target:g}")
        QTest.keyClick(spin.lineEdit(), Qt.Key.Key_Enter)
        QApplication.processEvents()
        assert spin.value() == target
        assert window.document.history.index == before_index + 1, (
            f"direct entry created {window.document.history.index - before_index} history entries"
        )

        _history_step(
            window,
            spin,
            lambda spin=spin: QTest.keyClick(spin, Qt.Key.Key_Up),
        )
        _history_step(
            window,
            spin,
            lambda spin=spin: QTest.keyClick(spin, Qt.Key.Key_Down),
        )

        spin.setFocus(Qt.FocusReason.OtherFocusReason)
        before_value = spin.value()
        before_index = window.document.history.index
        point = spin.rect().center()
        global_point = spin.mapToGlobal(point)
        event = QWheelEvent(
            QPointF(point),
            QPointF(global_point),
            QPoint(0, 0),
            QPoint(0, 120),
            Qt.MouseButton.NoButton,
            Qt.KeyboardModifier.NoModifier,
            Qt.ScrollPhase.ScrollUpdate,
            False,
        )
        QApplication.sendEvent(spin, event)
        QApplication.processEvents()
        wheel_changed = spin.value() != before_value
        if wheel_changed:
            assert window.document.history.index == before_index + 1

        for _ in range(5):
            _history_step(
                window,
                spin,
                lambda spin=spin: _click_arrow(spin, True),
            )

        assert window.simple_material_panel.control_spins[control_name] is spin
        assert not destroyed
        assert spin.value() != start_value
        assert (
            window._selected_output_id,
            window._selected_layer_id,
            window.control_fields_editor.selected_field_id,
        ) == (output_before_edits, layer_before_edits, control_name)
        edited_controls.append(
            {
                "name": control_name,
                "identity_preserved": id(window.simple_material_panel.control_spins[control_name])
                == identity,
                "value": spin.value(),
                "native_arrow_clicks": 7,
                "held_click_grouped": True,
                "direct_entry_grouped": True,
                "keyboard_steps": 2,
                "wheel_changed": wheel_changed,
                "history_and_value_verified": True,
            }
        )

    # Switching material channels and authoring modes is view/selection work; it
    # must not replace the live Simple Editor controls or change the recipe.
    scale = window.simple_material_panel.control_spins["Scale"]
    recipe_before_switches = window.document.recipe
    for semantic in ("roughness", "normal", "metallic", "base_color"):
        button = window.simple_material_panel.channel_buttons[semantic]
        if button.isEnabled():
            button.click()
            assert window.document.recipe == recipe_before_switches
    window.authoring_mode_combo.setCurrentIndex(1)
    parameter_spins = [
        item
        for item in (
            window.property_editor.findChildren(QDoubleSpinBox)
            + window.property_editor.findChildren(QSpinBox)
        )
        if item.objectName().startswith("parameter-")
        and (item.maximum() > item.value() or item.minimum() < item.value())
    ]
    if parameter_spins:
        advanced_spin = parameter_spins[0]
        advanced_destroyed: list[bool] = []
        advanced_spin.destroyed.connect(lambda *_args: advanced_destroyed.append(True))
        advance_up = advanced_spin.value() < advanced_spin.maximum()
        _history_step(
            window,
            advanced_spin,
            lambda advanced_spin=advanced_spin, up=advance_up: _click_arrow(advanced_spin, up),
        )
        assert window.property_editor.findChild(QWidget, advanced_spin.objectName()) is (
            advanced_spin
        ), "source parameter spin box was destroyed during its own value callback"
        assert not advanced_destroyed
        advanced_lifetime_checked = True
    else:
        advanced_lifetime_checked = False
    recipe_after_advanced_edit = window.document.recipe
    window.authoring_mode_combo.setCurrentIndex(0)
    assert window.simple_material_panel.control_spins["Scale"] is scale
    assert window.document.recipe == recipe_after_advanced_edit

    camera_after_edits = (
        window.preview_viewport.camera.yaw,
        window.preview_viewport.camera.pitch,
        window.preview_viewport.camera.distance,
        tuple(window.preview_viewport.camera.target),
    )
    assert camera_after_edits == start_camera, "spin-box edits changed the preview camera"

    path = report_path.with_suffix(".archetexture")
    save_project(window.document.recipe, path)
    assert load_project(path) == window.document.recipe
    old_recipe = window.document.recipe
    assert window.document.can_undo
    window.undo_action.trigger()
    assert window.document.recipe != old_recipe
    window.redo_action.trigger()
    assert window.document.recipe == old_recipe

    # Exercise both preview refresh paths after the rapid edit burst.
    for mode in ("2D Texture", "3D Material"):
        index = window.workspace_mode_combo.findData(mode)
        assert index >= 0
        window.workspace_mode_combo.setCurrentIndex(index)
        QApplication.processEvents()
        QTest.qWait(150)
    window.close()
    QApplication.processEvents()
    report_path.write_text(
        json.dumps(
            {
                "result": "passed",
                "starter": starter,
                "platform": app.platformName(),
                "controls": edited_controls,
                "channel_and_mode_switches_non_destructive": True,
                "advanced_parameter_widget_lifetime": advanced_lifetime_checked,
                "undo_redo": True,
                "save_reopen": True,
                "2d_3d_refresh": True,
                "camera_unchanged": True,
                "closed_cleanly": True,
                "time": time.time(),
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
