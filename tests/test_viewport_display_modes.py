from __future__ import annotations

import numpy as np
from PIL import Image
from PySide6.QtCore import QSettings, QSize
from PySide6.QtWidgets import QApplication

from archetexture.core.serialization import save_project
from archetexture.export.image_export import ImageExporter
from archetexture.render.engine import RenderEngine, RenderResult
from archetexture.render.pixels import rgba_float_to_uint8
from archetexture.ui.main_window import MainWindow
from archetexture.ui.theme import palette_for_mode, workspace_checkerboard_colors
from archetexture.ui.viewport import TextureViewport, seam_check_rgba


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


def test_seam_check_rolls_half_both_axes_without_changing_source():
    rgba = np.arange(5 * 7 * 4, dtype=np.float32).reshape((5, 7, 4))
    shifted = seam_check_rgba(rgba)
    np.testing.assert_array_equal(shifted, np.roll(rgba, shift=(2, 3), axis=(0, 1)))
    np.testing.assert_array_equal(rgba, np.arange(5 * 7 * 4, dtype=np.float32).reshape((5, 7, 4)))
    assert shifted is not rgba


def test_tile_3x3_draw_repeats_rendered_pixels_and_keeps_canonical_field(qtbot):
    viewport = TextureViewport()
    qtbot.addWidget(viewport)
    viewport.setPalette(palette_for_mode("dark", QApplication.instance().palette()))
    viewport.resize(360, 300)
    rows, columns = np.indices((6, 9))
    rgba = np.zeros((6, 9, 4), dtype=np.float32)
    rgba[..., 0] = columns / 8.0
    rgba[..., 1] = rows / 5.0
    rgba[..., 2] = 0.35
    rgba[..., 3] = 1.0
    viewport.set_result(RenderResult(None, rgba))
    canonical = viewport.rendered_field.copy()
    assert viewport.display_mode == "single"
    viewport.set_display_mode("tile_3x3")
    viewport.show()
    qtbot.wait(30)

    image = viewport.grab().toImage()
    rects = viewport.tile_preview_rects(viewport.rect().adjusted(12, 12, -12, -12), QSize(9, 6))
    assert len(rects) == 9
    sample_x, sample_y = rects[0].width() // 4, rects[0].height() // 3
    colors = [image.pixelColor(rect.x() + sample_x, rect.y() + sample_y).getRgb() for rect in rects]
    assert all(color == colors[0] for color in colors)
    np.testing.assert_array_equal(viewport.rendered_field, canonical)

    viewport.set_display_mode("seam_check")
    expected = seam_check_rgba(canonical)
    displayed = viewport._presentation_pixmap.toImage()
    expected_bytes = np.rint(expected * 255.0).astype(np.uint8)
    for y, x in ((0, 0), (1, 4), (5, 8)):
        assert displayed.pixelColor(x, y).getRgb() == tuple(expected_bytes[y, x])
    np.testing.assert_array_equal(viewport.rendered_field, canonical)

    viewport.set_display_mode("single")
    assert viewport._presentation_pixmap == viewport._pixmap


def test_alpha_checker_and_theme_colors_remain_visible_in_each_display_mode(qtbot):
    viewport = TextureViewport()
    qtbot.addWidget(viewport)
    viewport.resize(320, 240)
    transparent = np.zeros((1, 1, 4), dtype=np.float32)
    transparent[0, 0] = (1.0, 0.0, 0.0, 0.0)
    viewport.set_result(RenderResult(None, transparent))
    viewport.show()

    for mode in ("single", "tile_3x3", "seam_check"):
        viewport.set_display_mode(mode)
        for theme in ("dark", "light", "system"):
            system = QApplication.instance().style().standardPalette()
            palette = palette_for_mode(theme, system)
            viewport.setPalette(palette)
            _background, first_tile, _second_tile = workspace_checkerboard_colors(palette)
            image = viewport.grab().toImage()
            assert image.pixelColor(viewport.width() // 2, viewport.height() // 2) == first_tile
            assert viewport.rendered_field[0, 0, 3] == 0.0


def test_view_mode_persists_without_changing_project_or_export(tmp_path, qtbot):
    settings = _settings(tmp_path / "settings")
    window = MainWindow()
    qtbot.addWidget(window)
    window._confirm_discard = lambda: True
    assert window.viewport_mode_combo.currentData() == "single"
    recipe_before = window.document.recipe
    dirty_before = window.document.dirty
    can_undo_before = window.document.can_undo

    for mode in ("tile_3x3", "seam_check", "single"):
        window.viewport_mode_combo.setCurrentIndex(window.viewport_mode_combo.findData(mode))
        assert window.viewport.display_mode == mode
        assert window.document.recipe == recipe_before
        assert window.document.dirty == dirty_before
        assert window.document.can_undo == can_undo_before
        assert settings.value("viewport/mode") == mode

    window.viewport_mode_combo.setCurrentIndex(window.viewport_mode_combo.findData("seam_check"))
    project_path = tmp_path / "saved.archetexture"
    save_project(window.document.recipe, project_path)
    window.close()

    window = MainWindow()
    qtbot.addWidget(window)
    window._confirm_discard = lambda: True
    assert window.viewport_mode_combo.currentData() == "seam_check"
    assert window.new_document()
    assert window.viewport_mode_combo.currentData() == "seam_check"
    assert window.open_project(project_path)
    assert window.viewport_mode_combo.currentData() == "seam_check"
    assert not hasattr(window.document.recipe, "viewport_mode")

    png_path = tmp_path / "one-tile.png"
    expected = rgba_float_to_uint8(RenderEngine().render(window.document.recipe).rgba_field)
    ImageExporter().export_png(window.document.recipe, png_path)
    with Image.open(png_path) as image:
        assert image.size == (window.document.recipe.width, window.document.recipe.height)
        np.testing.assert_array_equal(np.asarray(image), expected)
    window.close()


def test_registered_seamless_generators_are_selectable_from_the_real_source_editor(qtbot, tmp_path):
    _settings(tmp_path)
    window = MainWindow()
    qtbot.addWidget(window)
    window._confirm_discard = lambda: True
    recipe = window.document.recipe
    recipe.layers = recipe.layers[:1]
    window.document.commit(recipe)
    window._refresh_document(request_render=False)
    for operation_id in (
        "generator.seamless_value_noise",
        "generator.seamless_fractal_noise",
        "generator.seamless_turbulence",
        "generator.seamless_cellular",
    ):
        index = window.pipeline_panel.source_selector.findData(operation_id)
        assert index >= 0
        window.pipeline_panel.source_selector.setCurrentIndex(index)
        assert window._layer().source.operation_id == operation_id
        assert window.seamlessness_label.text() == "Base Color · Color · Seamless: Yes"
    window.close()
