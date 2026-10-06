from __future__ import annotations

import numpy as np
import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QColorDialog, QMessageBox

from archetexture.color.ramp import ColorRamp, ColorStop
from archetexture.core.recipe import OperationInstance, ProjectRecipe
from archetexture.core.serialization import save_project
from archetexture.ui.color_ramp_editor import ColorRampEditor
from archetexture.ui.main_window import build_main_window


def three_stop_ramp() -> ColorRamp:
    return ColorRamp(
        (
            ColorStop(0.0, (1.0, 0.0, 0.0, 1.0)),
            ColorStop(0.5, (0.0, 1.0, 0.0, 0.65)),
            ColorStop(1.0, (0.0, 0.0, 1.0, 1.0)),
        )
    )


def recipe_with_ramp(ramp: ColorRamp | None) -> ProjectRecipe:
    return ProjectRecipe(
        width=32,
        height=24,
        seed=5,
        source=OperationInstance(
            "source",
            "generator.constant",
            1,
            parameters={"value": 0.2},
        ),
        color_ramp=ramp,
    )


@pytest.fixture
def workbench(qtbot, monkeypatch):
    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda *_args, **_kwargs: QMessageBox.StandardButton.Discard,
    )
    window = build_main_window(recipe_with_ramp(three_stop_ramp()))
    qtbot.addWidget(window)
    window.show()
    qtbot.waitUntil(lambda: window.statusBar().currentMessage() != "Rendering…", timeout=5000)
    return window


def wait_for_render(qtbot, window) -> None:
    qtbot.waitUntil(
        lambda: (
            window.viewport.rendered_field is not None
            and window.statusBar().currentMessage() != "Rendering…"
        ),
        timeout=5000,
    )


def render_preview(editor: ColorRampEditor) -> QImage:
    image = QImage(editor.preview.size(), QImage.Format.Format_ARGB32)
    image.fill(QColor("transparent"))
    painter = QPainter(image)
    editor.preview.render(painter, QPoint(0, 0))
    painter.end()
    return image


def click_stop(qtbot, editor: ColorRampEditor, position: float) -> None:
    preview = editor.preview
    point = QPoint(round(preview.x_from_position(position)), preview.track_rect().bottom() + 9)
    qtbot.mouseClick(preview, Qt.MouseButton.LeftButton, pos=point)


def test_editor_previews_three_stops_in_sorted_color_order(workbench):
    editor = workbench.color_ramp_editor
    unsorted = ColorRamp(
        tuple(
            ColorStop(stop.position, (*stop.color[:3], 1.0))
            for stop in (
                three_stop_ramp().stops[2],
                three_stop_ramp().stops[0],
                three_stop_ramp().stops[1],
            )
        )
    )
    editor.set_ramp(unsorted, reset_selection=True)

    assert editor.preview.displayed_stops == tuple(
        sorted(unsorted.stops, key=lambda stop: stop.position)
    )
    image = render_preview(editor)
    y = editor.preview.track_rect().center().y()
    for position, expected in ((0.0, (255, 0, 0)), (0.5, (0, 255, 0)), (1.0, (0, 0, 255))):
        x = round(editor.preview.x_from_position(position))
        if position == 0.0:
            x += 1
        elif position == 1.0:
            x -= 2
        color = image.pixelColor(x, y)
        assert abs(color.red() - expected[0]) <= 3
        assert abs(color.green() - expected[1]) <= 3
        assert abs(color.blue() - expected[2]) <= 3


def test_preview_checkerboard_remains_visible_behind_transparency(workbench):
    editor = workbench.color_ramp_editor
    editor.set_ramp(ColorRamp((ColorStop(0.5, (1.0, 0.0, 0.0, 0.0)),)), reset_selection=True)
    image = render_preview(editor)
    track = editor.preview.track_rect()

    dark_tile = image.pixelColor(track.left() + 11, track.top() + 5)
    light_tile = image.pixelColor(track.left() + 20, track.top() + 5)
    assert dark_tile.red() < light_tile.red()
    assert dark_tile.green() < light_tile.green()


def test_selecting_stop_updates_precise_position_and_color_controls(workbench, qtbot):
    editor = workbench.color_ramp_editor
    click_stop(qtbot, editor, 0.5)

    assert editor.selected_stop == three_stop_ramp().stops[1]
    assert editor.position_spin.value() == pytest.approx(0.5)
    assert "0.000, 1.000, 0.000" in editor.color_button.toolTip()
    assert editor.position_spin.decimals() >= 3


def test_add_stop_uses_largest_gap_and_interpolated_color(workbench, qtbot):
    editor = workbench.color_ramp_editor
    before = workbench.document.recipe.color_ramp
    expected_position = 0.25
    expected_color = before.sample(expected_position)
    initial_history_length = len(workbench.document.history.entries)
    initial_request_id = workbench.render_coordinator.latest_request_id

    editor.add_button.click()
    wait_for_render(qtbot, workbench)
    stops = workbench.document.recipe.color_ramp.stops
    inserted = next(stop for stop in stops if stop.position == expected_position)
    assert inserted.color == pytest.approx(expected_color)
    assert len({stop.position for stop in stops}) == len(stops)
    assert editor.selected_stop == inserted
    assert len(workbench.document.history.entries) == initial_history_length + 1
    assert workbench.render_coordinator.latest_request_id > initial_request_id


def test_remove_stop_keeps_a_valid_ramp_and_disables_last_removal(workbench):
    editor = workbench.color_ramp_editor
    editor.remove_stop()
    assert len(workbench.document.recipe.color_ramp.stops) == 2
    editor.remove_stop()
    assert len(workbench.document.recipe.color_ramp.stops) == 1
    assert not editor.remove_stop_button.isEnabled()
    editor.remove_stop_button.click()
    assert len(workbench.document.recipe.color_ramp.stops) == 1


def test_numeric_position_edit_is_unique_updates_recipe_and_render(workbench, qtbot):
    editor = workbench.color_ramp_editor
    original_pixels = workbench.viewport.rendered_field.copy()
    editor.position_spin.setValue(0.25)
    wait_for_render(qtbot, workbench)
    ramp = workbench.document.recipe.color_ramp
    assert ramp.stops[0].position == pytest.approx(0.25)
    assert np.array_equal(workbench.viewport.rendered_field[0, 0], ramp.sample(0.2))
    assert not np.array_equal(original_pixels, workbench.viewport.rendered_field)

    click_stop(qtbot, editor, 0.5)
    editor.position_spin.setValue(0.25)
    ramp = workbench.document.recipe.color_ramp
    positions = [stop.position for stop in ramp.stops]
    assert len(set(positions)) == len(positions)
    assert editor.selected_stop.position > 0.25


def test_drag_moves_stop_with_one_history_edit_and_undo_redo(workbench, qtbot):
    editor = workbench.color_ramp_editor
    preview = editor.preview
    original_ramp = workbench.document.recipe.color_ramp
    original_pixels = workbench.viewport.rendered_field.copy()
    old_history_length = len(workbench.document.history.entries)
    y = preview.track_rect().bottom() + 9
    start = QPoint(round(preview.x_from_position(0.5)), y)
    middle = QPoint(round(preview.x_from_position(0.65)), y)
    finish = QPoint(round(preview.x_from_position(0.75)), y)

    QTest.mousePress(preview, Qt.MouseButton.LeftButton, pos=start)
    QTest.mouseMove(preview, middle, delay=10)
    QTest.mouseMove(preview, finish, delay=10)
    QTest.mouseRelease(preview, Qt.MouseButton.LeftButton, pos=finish)
    wait_for_render(qtbot, workbench)

    moved = workbench.document.recipe.color_ramp
    assert any(stop.position == pytest.approx(0.75, abs=0.02) for stop in moved.stops)
    assert len(workbench.document.history.entries) == old_history_length + 1
    workbench.undo()
    wait_for_render(qtbot, workbench)
    assert workbench.document.recipe.color_ramp == original_ramp
    assert workbench.color_ramp_editor.selected_stop == original_ramp.stops[1]
    assert np.array_equal(workbench.viewport.rendered_field, original_pixels)
    workbench.redo()
    wait_for_render(qtbot, workbench)
    assert workbench.document.recipe.color_ramp == moved


def test_color_and_alpha_edits_render_and_survive_save_reopen(
    workbench, qtbot, monkeypatch, tmp_path
):
    editor = workbench.color_ramp_editor
    replacement = QColor.fromRgbF(0.9, 0.15, 0.3, 0.25)
    options_seen = []

    def choose_color(_initial, _parent, _title, options):
        options_seen.append(options)
        return replacement

    monkeypatch.setattr(QColorDialog, "getColor", choose_color)
    initial_pixels = workbench.viewport.rendered_field.copy()
    editor.color_button.click()
    wait_for_render(qtbot, workbench)

    ramp = workbench.document.recipe.color_ramp
    assert options_seen and options_seen[0] & QColorDialog.ColorDialogOption.ShowAlphaChannel
    assert ramp.stops[0].color == pytest.approx(
        (replacement.redF(), replacement.greenF(), replacement.blueF(), replacement.alphaF())
    )
    assert workbench.viewport.rendered_field[0, 0] == pytest.approx(ramp.sample(0.2))
    assert workbench.viewport.rendered_field[0, 0, 3] < 1.0
    assert not np.array_equal(initial_pixels, workbench.viewport.rendered_field)

    path = tmp_path / "ramp.archetexture"
    assert workbench.save_project(str(path))
    saved_ramp = workbench.document.recipe.color_ramp
    saved_pixels = workbench.viewport.rendered_field.copy()
    editor.position_spin.setValue(0.1)
    wait_for_render(qtbot, workbench)
    assert workbench.open_project(str(path))
    wait_for_render(qtbot, workbench)
    assert workbench.document.recipe.color_ramp == saved_ramp
    assert np.array_equal(workbench.viewport.rendered_field, saved_pixels)


def test_create_remove_ramp_grayscale_undo_and_redo(workbench, qtbot):
    workbench.document.new_document(recipe_with_ramp(None))
    workbench._refresh_document(request_render=True, reset_ramp_selection=True)
    editor = workbench.color_ramp_editor
    wait_for_render(qtbot, workbench)
    assert editor.create_button.isVisible()
    assert not editor.add_button.isEnabled()

    editor.create_button.click()
    wait_for_render(qtbot, workbench)
    created = workbench.document.recipe.color_ramp
    assert created == ColorRamp(
        (ColorStop(0.0, (0.0, 0.0, 0.0, 1.0)), ColorStop(1.0, (1.0, 1.0, 1.0, 1.0)))
    )
    assert workbench.pipeline_panel.output_description.text() == "Scalar → Color Ramp → RGBA"

    editor.remove_ramp_button.click()
    wait_for_render(qtbot, workbench)
    assert workbench.document.recipe.color_ramp is None
    grayscale = workbench.viewport.rendered_field
    assert np.allclose(grayscale[..., :3], 0.2)
    assert np.allclose(grayscale[..., 3], 1.0)
    assert workbench.pipeline_panel.output_description.text() == "Scalar → Grayscale RGBA"

    workbench.undo()
    wait_for_render(qtbot, workbench)
    assert workbench.document.recipe.color_ramp == created
    workbench.redo()
    wait_for_render(qtbot, workbench)
    assert workbench.document.recipe.color_ramp is None


def test_new_and_open_refresh_ramp_editor(workbench, qtbot, tmp_path):
    path = tmp_path / "without-ramp.archetexture"
    save_project(recipe_with_ramp(None), path)
    assert workbench.open_project(str(path))
    wait_for_render(qtbot, workbench)
    assert workbench.color_ramp_editor.ramp is None
    assert workbench.color_ramp_editor.create_button.isVisible()

    assert workbench.new_document()
    wait_for_render(qtbot, workbench)
    assert workbench.color_ramp_editor.ramp == workbench.document.recipe.color_ramp
    assert workbench.color_ramp_editor.ramp is not None
    assert not workbench.color_ramp_editor.create_button.isVisible()


def test_source_transform_and_open_regressions_remain_available(workbench, qtbot, tmp_path):
    panel = workbench.pipeline_panel
    panel.transform_selector.setCurrentIndex(panel.transform_selector.findData("transform.invert"))
    panel.add_button.click()
    assert len(workbench.document.recipe.transforms) == 1
    workbench.undo()
    assert not workbench.document.recipe.transforms

    path = tmp_path / "roundtrip.archetexture"
    assert workbench.save_project(str(path))
    assert workbench.open_project(str(path))
    wait_for_render(qtbot, workbench)
    assert workbench.document.recipe.color_ramp is not None


def test_ramp_editor_stays_compact_beneath_the_viewport(workbench):
    editor = workbench.color_ramp_editor
    assert 100 <= editor.height() <= 150
    assert workbench.viewport.height() > editor.height()
