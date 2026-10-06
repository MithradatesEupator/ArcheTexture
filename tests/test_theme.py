from __future__ import annotations

from collections import deque

import numpy as np
from PySide6.QtCore import QSettings
from PySide6.QtGui import QImage, QPalette
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QLineEdit,
    QListWidget,
    QPushButton,
    QSpinBox,
    QToolBar,
)

from archetexture.ui.main_window import MainWindow
from archetexture.ui.theme import palette_for_mode, workspace_checkerboard_colors


def _settings(tmp_path):
    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(tmp_path))
    settings = QSettings(
        QSettings.Format.IniFormat,
        QSettings.Scope.UserScope,
        "ArcheTexture",
        "ArcheTexture",
    )
    settings.clear()
    settings.sync()
    return settings


def test_fresh_install_defaults_dark_and_explicit_theme_choices_persist(qtbot, tmp_path):
    settings = _settings(tmp_path)
    window = MainWindow()
    qtbot.addWidget(window)
    window._confirm_discard = lambda: True
    system_style_name = window._system_style_name

    assert window.theme_actions["dark"].isChecked()
    app_palette = QApplication.instance().palette()
    assert app_palette.color(QPalette.ColorRole.Window).name() == "#1b1d21"
    assert (
        app_palette.color(QPalette.ColorGroup.Disabled, QPalette.ColorRole.ButtonText).name()
        == "#a3a8b0"
    )
    assert settings.value("appearance/theme") is None

    for mode in ("light", "system", "dark"):
        window.theme_actions[mode].trigger()
        assert settings.value("appearance/theme") == mode
        assert window.theme_actions[mode].isChecked()
        window.close()
        window = MainWindow()
        qtbot.addWidget(window)
        window._confirm_discard = lambda: True
        assert window.theme_actions[mode].isChecked()
        if mode == "system":
            assert QApplication.instance().style().objectName() == system_style_name
            assert QApplication.instance().styleSheet() == ""
        else:
            app = QApplication.instance()
            stylesheet = app.styleSheet()
            app.setStyleSheet("")
            assert app.style().objectName().lower() == "fusion"
            app.setStyleSheet(stylesheet)

    window.close()


def test_explicit_palette_covers_disabled_and_inactive_controls():
    palette = palette_for_mode("dark", QApplication.instance().palette())
    for group in (QPalette.ColorGroup.Active, QPalette.ColorGroup.Inactive):
        assert palette.color(group, QPalette.ColorRole.Window).name() == "#1b1d21"
        assert palette.color(group, QPalette.ColorRole.Text).name() == "#e7e9ec"
    assert palette.color(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text).name() == "#969ca5"
    assert (
        palette.color(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Button).name() == "#292c31"
    )


def test_workspace_checkerboard_tracks_dark_light_and_system_palettes():
    system = QPalette()
    dark_palette = palette_for_mode("dark", system)
    light_palette = palette_for_mode("light", system)
    dark_colors = workspace_checkerboard_colors(dark_palette)
    light_colors = workspace_checkerboard_colors(light_palette)
    assert tuple(color.name() for color in dark_colors) == ("#17191c", "#22262b", "#2b3036")
    assert tuple(color.name() for color in light_colors) == ("#f0f1f3", "#ffffff", "#f5f6f8")

    system_dark = QPalette(dark_palette)
    assert palette_for_mode("system", system_dark) == system_dark
    assert workspace_checkerboard_colors(system_dark) == dark_colors
    system_light = QPalette(light_palette)
    assert palette_for_mode("system", system_light) == system_light
    assert workspace_checkerboard_colors(system_light) == light_colors


def test_principal_workspace_widgets_construct_under_each_theme(qtbot, tmp_path):
    _settings(tmp_path)
    window = MainWindow()
    qtbot.addWidget(window)
    window._confirm_discard = lambda: True

    for mode in ("dark", "light", "system"):
        window._set_theme(mode, persist=False)
        assert window.layers_panel.palette().color(QPalette.ColorRole.Window).isValid()
        assert (
            window.pipeline_panel.source_selector.palette().color(QPalette.ColorRole.Base).isValid()
        )
        assert (
            window.color_ramp_editor.position_spin.palette()
            .color(QPalette.ColorRole.Text)
            .isValid()
        )
        assert window.property_editor.palette().color(QPalette.ColorRole.WindowText).isValid()
        assert (
            window.control_fields_editor.fields_list.palette()
            .color(QPalette.ColorRole.Base)
            .isValid()
        )

    window.close()


def test_dark_palette_assigns_required_roles_for_active_inactive_and_disabled():
    roles = (
        QPalette.ColorRole.Window,
        QPalette.ColorRole.Base,
        QPalette.ColorRole.AlternateBase,
        QPalette.ColorRole.Button,
        QPalette.ColorRole.Text,
        QPalette.ColorRole.WindowText,
        QPalette.ColorRole.ButtonText,
        QPalette.ColorRole.Highlight,
        QPalette.ColorRole.HighlightedText,
    )
    palette = palette_for_mode("dark", QApplication.instance().palette())
    for group in (
        QPalette.ColorGroup.Active,
        QPalette.ColorGroup.Inactive,
        QPalette.ColorGroup.Disabled,
    ):
        for role in roles:
            assert palette.color(group, role).isValid(), (group, role)
        for role in roles[:4]:
            assert palette.color(group, role).lightness() < 110, (group, role)


def _rendered_luminance(widget):
    image = widget.grab().toImage().convertToFormat(QImage.Format.Format_RGBA8888)
    height, width = image.height(), image.width()
    pixels = np.frombuffer(image.bits(), dtype=np.uint8, count=image.sizeInBytes())
    pixels = pixels.reshape(height, image.bytesPerLine())[:, : width * 4].reshape(height, width, 4)
    return 0.2126 * pixels[..., 0] + 0.7152 * pixels[..., 1] + 0.0722 * pixels[..., 2]


def _assert_widget_is_dark(widget, name, minimum_fraction=0.7):
    luminance = _rendered_luminance(widget)
    if luminance.shape[0] > 8 and luminance.shape[1] > 8:
        luminance = luminance[4:-4, 4:-4]
    fraction = float(np.mean(luminance < 150))
    assert fraction >= minimum_fraction, f"{name} rendered only {fraction:.1%} dark pixels"


def _assert_no_large_near_white_surface(window):
    luminance = _rendered_luminance(window)
    height, width = luminance.shape
    masked = np.zeros((height, width), dtype=bool)
    for widget in (window.viewport, window.color_ramp_editor):
        origin = widget.mapTo(window, widget.rect().topLeft())
        masked[
            origin.y() : origin.y() + widget.height(), origin.x() : origin.x() + widget.width()
        ] = True

    block_size = 4
    rows, columns = height // block_size, width // block_size
    near_white = np.zeros((rows, columns), dtype=bool)
    for row in range(rows):
        for column in range(columns):
            y, x = row * block_size, column * block_size
            surface = ~masked[y : y + block_size, x : x + block_size]
            if surface.sum() >= 8:
                patch = luminance[y : y + block_size, x : x + block_size][surface]
                near_white[row, column] = np.mean(patch >= 220) >= 0.8

    seen = np.zeros_like(near_white)
    largest_component = 0
    for row, column in zip(*np.nonzero(near_white & ~seen), strict=False):
        queue = deque([(row, column)])
        seen[row, column] = True
        size = 0
        while queue:
            current_row, current_column = queue.popleft()
            size += 1
            for next_row, next_column in (
                (current_row - 1, current_column),
                (current_row + 1, current_column),
                (current_row, current_column - 1),
                (current_row, current_column + 1),
            ):
                if (
                    0 <= next_row < rows
                    and 0 <= next_column < columns
                    and near_white[next_row, next_column]
                    and not seen[next_row, next_column]
                ):
                    seen[next_row, next_column] = True
                    queue.append((next_row, next_column))
        largest_component = max(largest_component, size)
    assert largest_component < 100, (
        f"near-white application surface covers {largest_component * block_size**2} pixels"
    )


def test_dark_mode_renders_right_tabs_and_representative_controls(qtbot, tmp_path):
    _settings(tmp_path)
    window = MainWindow()
    qtbot.addWidget(window)
    window._confirm_discard = lambda: True
    window._set_theme("dark", persist=False)
    window.resize(1360, 850)
    window.show()
    qtbot.wait(50)

    window.right_tabs.setCurrentIndex(0)
    qtbot.wait(20)
    _assert_widget_is_dark(window.right_tabs, "Properties tab pane")
    _assert_widget_is_dark(window.property_editor, "Properties body")
    _assert_widget_is_dark(window.right_tabs.tabBar(), "right tab bar")
    spin = window.property_editor.findChild(QSpinBox, "parameter-seed")
    double_spin = window.property_editor.findChild(QDoubleSpinBox, "parameter-scale")
    assert spin is not None and double_spin is not None
    _assert_widget_is_dark(spin, "QSpinBox", 0.55)
    _assert_widget_is_dark(double_spin, "QDoubleSpinBox", 0.55)

    window.right_tabs.setCurrentIndex(1)
    qtbot.wait(20)
    _assert_widget_is_dark(window.right_tabs, "Control Fields tab pane")
    _assert_widget_is_dark(window.control_fields_editor, "Control Fields body")
    disabled_numeric = window.control_fields_editor.mapping_min
    assert not disabled_numeric.isEnabled()
    _assert_widget_is_dark(disabled_numeric, "disabled numeric input", 0.55)
    assert not window.control_fields_editor.source_combo.isEnabled()
    _assert_widget_is_dark(window.control_fields_editor.source_combo, "disabled combo box", 0.55)
    assert isinstance(window.control_fields_editor.mapping_enabled, QCheckBox)
    _assert_widget_is_dark(window.control_fields_editor.mapping_enabled, "disabled checkbox", 0.55)
    disabled_button = window.property_editor.findChild(QPushButton, "modulate-scale")
    assert disabled_button is not None and not disabled_button.isEnabled()
    _assert_widget_is_dark(disabled_button, "disabled button", 0.55)
    line_edit = window.control_fields_editor.name_input
    assert isinstance(line_edit, QLineEdit)
    _assert_widget_is_dark(line_edit, "line edit", 0.55)
    line_edit.setEnabled(False)
    _assert_widget_is_dark(line_edit, "disabled line edit", 0.55)
    line_edit.setEnabled(True)

    widgets = (
        (window.pipeline_panel.source_selector, QComboBox, "left source combo"),
        (window.viewport_mode_combo, QComboBox, "viewport mode combo"),
        (window.seamlessness_label, None, "seamlessness status"),
        (window.layers_panel.add_button, QPushButton, "left Add button"),
        (window.layers_panel.layer_list, QListWidget, "Layers list"),
        (window.menuBar(), None, "menu bar"),
        (window.findChild(QToolBar), QToolBar, "toolbar"),
        (window.statusBar(), None, "status bar"),
    )
    for widget, expected_type, name in widgets:
        if expected_type is not None:
            assert isinstance(widget, expected_type)
        _assert_widget_is_dark(widget, name)

    window.viewport_mode_combo.showPopup()
    qtbot.wait(20)
    _assert_widget_is_dark(window.viewport_mode_combo.view(), "combo-box popup")
    window.viewport_mode_combo.hidePopup()

    _assert_no_large_near_white_surface(window)
    window.close()


def test_theme_switches_are_repeatable_and_restore_system_style(qtbot, tmp_path):
    _settings(tmp_path)
    window = MainWindow()
    qtbot.addWidget(window)
    window._confirm_discard = lambda: True
    app = QApplication.instance()
    system_style_name = window._system_style_name
    window.show()
    qtbot.wait(30)
    for mode in ("dark", "system", "light", "dark", "light", "system", "dark"):
        window._set_theme(mode, persist=False)
        if mode == "system":
            assert app.style().objectName() == system_style_name
            assert app.styleSheet() == ""
        else:
            assert "QTabWidget::pane" in app.styleSheet()
            explicit_stylesheet = app.styleSheet()
            app.setStyleSheet("")
            assert app.style().objectName().lower() == "fusion"
            app.setStyleSheet(explicit_stylesheet)
            app.processEvents()
        if mode == "light":
            light_luminance = _rendered_luminance(window.right_tabs)
            assert float(np.mean(light_luminance > 190)) > 0.7
    window.close()
