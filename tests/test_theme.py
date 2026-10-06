from __future__ import annotations

from PySide6.QtCore import QSettings
from PySide6.QtGui import QPalette
from PySide6.QtWidgets import QApplication

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
