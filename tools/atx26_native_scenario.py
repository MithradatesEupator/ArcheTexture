from __future__ import annotations

import copy
import ctypes
import json
import os
import time
import traceback
import uuid
from pathlib import Path

import numpy as np
from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import QCursor, QImage, QWheelEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDoubleSpinBox,
    QPushButton,
    QSpinBox,
    QToolTip,
)

from archetexture.color.ramp import ColorRamp, ColorStop
from archetexture.core.defaults import default_recipe
from archetexture.core.material_starters import create_material_starter
from archetexture.core.recipe import OperationInstance
from archetexture.core.registry import REGISTRY
from archetexture.core.seamlessness import measure_tileability
from archetexture.core.serialization import load_project, save_project
from archetexture.preview import gl_viewport
from archetexture.preview.snapshot import PreviewMaterialSnapshot
from archetexture.ui.main_window import MainWindow

_uv_branch = "else if(mode==4 || mode==12)c=ts*0.5+0.5;"
assert _uv_branch in gl_viewport._FRAGMENT
gl_viewport._FRAGMENT = gl_viewport._FRAGMENT.replace(
    _uv_branch,
    _uv_branch
    + "\n else if(mode==13)c=vec3(UV,0.0);"
    + "\n else if(mode==14)c=texture(baseMap,UV).rgb;"
    + "\n else if(mode==15)c=vec3(q,0.0);"
    + "\n else if(mode==16)c=vec3(tileU,tileV,0.0);"
    + "\n else if(mode==17)c=vec3(rough);",
)
gl_viewport.INSPECTION_MODES = (
    *gl_viewport.INSPECTION_MODES,
    "UV RGB",
    "Direct UV Base",
    "Transformed UV RGB",
    "Tile Uniforms RGB",
    "Roughness Map RGB",
)


def _wait_until(predicate, timeout: float = 20.0, message: str = "condition timed out") -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        QApplication.processEvents()
        if predicate():
            return
        QTest.qWait(20)
    raise AssertionError(message)


def _render_preview(window: MainWindow):
    window._request_preview()
    request_id = window._preview_request_id
    _wait_until(
        lambda: (
            window.preview_viewport.snapshot is not None
            and window.preview_viewport.snapshot.request_id >= request_id
        ),
        timeout=90,
        message=f"preview request {request_id} did not finish",
    )
    window.preview_viewport.update()
    QApplication.processEvents()
    window.preview_viewport.repaint()
    QTest.qWait(100)
    image = window.preview_viewport.grabFramebuffer().convertToFormat(QImage.Format.Format_RGBA8888)
    raw = np.frombuffer(image.bits(), dtype=np.uint8).reshape(image.height(), image.width(), 4)
    return image, raw.copy(), window.preview_viewport.snapshot


def _capture_preview_frame(window: MainWindow):
    viewport = window.preview_viewport
    viewport.update()
    QApplication.processEvents()
    viewport.repaint()
    QTest.qWait(100)
    image = viewport.grabFramebuffer().convertToFormat(QImage.Format.Format_RGBA8888)
    raw = np.frombuffer(image.bits(), dtype=np.uint8).reshape(image.height(), image.width(), 4)
    return image, raw.copy()


def _image_difference(first: np.ndarray, second: np.ndarray) -> float:
    height = min(first.shape[0], second.shape[0])
    width = min(first.shape[1], second.shape[1])
    y0_first, x0_first = (first.shape[0] - height) // 2, (first.shape[1] - width) // 2
    y0_second, x0_second = (second.shape[0] - height) // 2, (second.shape[1] - width) // 2
    a = first[y0_first : y0_first + height, x0_first : x0_first + width]
    b = second[y0_second : y0_second + height, x0_second : x0_second + width]
    return float(np.mean(np.abs(a.astype(np.float32) - b.astype(np.float32))))


def _check_material_frame(raw: np.ndarray, name: str) -> dict[str, float]:
    rgb = raw[..., :3].astype(np.float32)
    assert float(rgb.std()) > 7.0, f"{name}: material image is flat or blank (std={rgb.std():.2f})"
    assert float(rgb.max() - rgb.min()) > 40.0, f"{name}: material frame lacks visible range"
    center = rgb[
        rgb.shape[0] // 4 : 3 * rgb.shape[0] // 4, rgb.shape[1] // 4 : 3 * rgb.shape[1] // 4
    ]
    assert float(center.std()) > 4.0, f"{name}: object interior looks featureless"
    return {"stddev": float(rgb.std()), "range": float(rgb.max() - rgb.min())}


def _diagnose_sampling(window: MainWindow, evidence_dir: Path) -> dict[str, object]:
    """Capture native framebuffer probes for UV, procedural, and texture sampling."""
    viewport = window.preview_viewport
    # The UV RGB branch is injected into this native scenario's shader only.
    viewport.inspection = "UV RGB"
    uv_image, uv_raw = _capture_preview_frame(window)
    uv_image.save(str(evidence_dir / "atx26-diagnostic-uv-rgb.png"))
    viewport.makeCurrent()
    gl_error_after_uv_draw = int(viewport.context().functions().glGetError())
    viewport.doneCurrent()
    uv_rgb = uv_raw[..., :3].astype(np.float32)
    uv_center = uv_rgb[
        uv_rgb.shape[0] // 4 : 3 * uv_rgb.shape[0] // 4,
        uv_rgb.shape[1] // 4 : 3 * uv_rgb.shape[1] // 4,
    ]
    mesh = __import__("archetexture.preview.mesh", fromlist=["generate_mesh"]).generate_mesh(
        viewport.mesh_type, viewport.quality
    )
    uv = mesh.uvs
    uv_metrics = {
        "vertex_u_range": float(uv[:, 0].max() - uv[:, 0].min()),
        "vertex_v_range": float(uv[:, 1].max() - uv[:, 1].min()),
        "vertex_uv_unique": int(np.unique(uv, axis=0).shape[0]),
        "native_frame_center_stddev": float(uv_center.std()),
        "native_frame_center_range": int(uv_center.max() - uv_center.min()),
        "gl_error_after_draw": hex(gl_error_after_uv_draw),
        "tile_u_python_type": type(viewport.tile_u).__name__,
        "tile_v_python_type": type(viewport.tile_v).__name__,
    }
    assert uv_metrics["vertex_u_range"] > 0.99 and uv_metrics["vertex_v_range"] > 0.99
    assert uv_metrics["native_frame_center_stddev"] > 10, "interpolated UV framebuffer is flat"

    # This diagnostic texture bypasses RenderEngine and uses QOpenGLTexture upload directly.
    size = 128
    y, x = np.mgrid[:size, :size]
    synthetic = np.empty((size, size, 4), dtype=np.float32)
    synthetic[..., 0] = x / (size - 1)
    synthetic[..., 1] = y / (size - 1)
    synthetic[..., 2] = ((x // 8 + y // 8) % 2).astype(np.float32)
    synthetic[..., 3] = 1.0
    maps = dict(viewport.snapshot.maps)
    maps["base_color"] = synthetic
    synthetic_snapshot = PreviewMaterialSnapshot(
        viewport.snapshot.request_id + 1,
        maps,
        viewport.snapshot.resolved_output_ids,
        size,
        size,
    )
    cpu_bytes = np.clip(synthetic * 255, 0, 255).astype(np.uint8)
    # Force the constructor upload path so this probe does not depend on an
    # earlier RenderEngine snapshot or QOpenGLTexture.setData update.
    viewport.makeCurrent()
    for texture in viewport._textures.values():
        texture.destroy()
    viewport._textures.clear()
    viewport._texture_sizes.clear()
    viewport.doneCurrent()
    viewport.set_snapshot(synthetic_snapshot)
    viewport.inspection = "Base Color"
    viewport.makeCurrent()
    texture_id = viewport._textures["base_color"].textureId()
    gl = ctypes.WinDLL("opengl32.dll")
    gl.glBindTexture.argtypes = (ctypes.c_uint, ctypes.c_uint)
    gl.glGetTexImage.argtypes = (
        ctypes.c_uint,
        ctypes.c_int,
        ctypes.c_uint,
        ctypes.c_uint,
        ctypes.c_void_p,
    )
    readback = (ctypes.c_uint8 * cpu_bytes.nbytes)()
    gl.glBindTexture(0x0DE1, texture_id)
    gl.glGetTexImage(0x0DE1, 0, 0x1908, 0x1401, ctypes.cast(readback, ctypes.c_void_p))
    viewport.doneCurrent()
    gpu_bytes = np.ctypeslib.as_array(readback).reshape(cpu_bytes.shape)
    direct_upload_metrics = {
        "texture_id": int(texture_id),
        "gpu_bytes_unique_rgb": int(np.unique(gpu_bytes[..., :3].reshape(-1, 3), axis=0).shape[0]),
        "cpu_gpu_exact_match": bool(np.array_equal(cpu_bytes, gpu_bytes)),
        "cpu_gpu_vertical_flip_match": bool(np.array_equal(cpu_bytes, gpu_bytes[::-1])),
        "max_abs_byte_difference": int(
            np.abs(cpu_bytes.astype(np.int16) - gpu_bytes.astype(np.int16)).max()
        ),
    }
    np.save(str(evidence_dir / "atx26-diagnostic-synthetic-gpu.npy"), gpu_bytes)
    image, raw = _capture_preview_frame(window)
    image.save(str(evidence_dir / "atx26-diagnostic-synthetic-upload.png"))
    synthetic_stddev = float(raw[..., :3].astype(np.float32).std())
    synthetic_range = int(raw[..., :3].max() - raw[..., :3].min())
    synthetic_metrics = {
        "cpu_bytes_length": int(cpu_bytes.nbytes),
        "cpu_bytes_unique_rgb": int(np.unique(cpu_bytes[..., :3].reshape(-1, 3), axis=0).shape[0]),
        "native_frame_stddev": synthetic_stddev,
        "native_frame_range": synthetic_range,
        "inspection_mode": viewport.inspection,
        "inspection_mode_index": gl_viewport.INSPECTION_MODES.index(viewport.inspection),
        "tile_u": viewport.tile_u,
        "tile_v": viewport.tile_v,
        "rotation_uv": viewport.rotation_uv,
        "gpu_texture_readback": direct_upload_metrics,
    }
    synthetic_center = raw[
        raw.shape[0] // 4 : 3 * raw.shape[0] // 4,
        raw.shape[1] // 4 : 3 * raw.shape[1] // 4,
        :3,
    ].astype(np.float32)
    synthetic_metrics["native_center_stddev"] = float(synthetic_center.std())
    assert synthetic_metrics["native_center_stddev"] > 8, "synthetic texture sampling is flat"
    # Save the CPU bytes alongside the native capture for byte-for-byte inspection.
    np.save(str(evidence_dir / "atx26-diagnostic-synthetic-cpu.npy"), cpu_bytes)

    viewport.inspection = "Direct UV Base"
    direct_image, direct_raw = _capture_preview_frame(window)
    direct_image.save(str(evidence_dir / "atx26-diagnostic-direct-uv-sample.png"))
    direct_center = direct_raw[
        direct_raw.shape[0] // 4 : 3 * direct_raw.shape[0] // 4,
        direct_raw.shape[1] // 4 : 3 * direct_raw.shape[1] // 4,
        :3,
    ].astype(np.float32)
    synthetic_metrics["direct_uv_sample_center_stddev"] = float(direct_center.std())
    synthetic_metrics["direct_uv_sample_center_range"] = int(
        direct_center.max() - direct_center.min()
    )
    viewport.inspection = "Transformed UV RGB"
    q_image, q_raw = _capture_preview_frame(window)
    q_image.save(str(evidence_dir / "atx26-diagnostic-transformed-uv.png"))
    q_center = q_raw[
        q_raw.shape[0] // 4 : 3 * q_raw.shape[0] // 4,
        q_raw.shape[1] // 4 : 3 * q_raw.shape[1] // 4,
        :3,
    ].astype(np.float32)
    synthetic_metrics["transformed_uv_center_stddev"] = float(q_center.std())
    synthetic_metrics["transformed_uv_center_range"] = int(q_center.max() - q_center.min())
    viewport.inspection = "Tile Uniforms RGB"
    uniforms_image, uniforms_raw = _capture_preview_frame(window)
    uniforms_image.save(str(evidence_dir / "atx26-diagnostic-tile-uniforms.png"))
    uniforms_center = uniforms_raw[
        uniforms_raw.shape[0] // 2, uniforms_raw.shape[1] // 2, :3
    ].astype(int)
    synthetic_metrics["tile_uniform_frame_center_rgb"] = uniforms_center.tolist()
    synthetic_metrics["uniform_locations"] = {
        name: int(viewport._program.uniformLocation(name.encode()))
        for name in ("tileU", "tileV", "mode", "baseMap")
    }

    periodic = np.empty_like(synthetic)
    periodic[..., 0] = np.sin(2 * np.pi * x / (size - 1)) * 0.5 + 0.5
    periodic[..., 1] = np.cos(2 * np.pi * y / (size - 1)) * 0.5 + 0.5
    periodic[..., 2] = np.sin(2 * np.pi * (x + y) / (size - 1)) * 0.5 + 0.5
    periodic[..., 3] = 1.0
    periodic_snapshot = PreviewMaterialSnapshot(
        synthetic_snapshot.request_id + 1,
        {**maps, "base_color": periodic},
        synthetic_snapshot.resolved_output_ids,
        size,
        size,
    )
    periodic_ok, periodic_edge, periodic_interior = measure_tileability(periodic)
    assert periodic_ok, "known-periodic synthetic map failed the CPU edge test"
    original_camera_angles = (viewport.camera.yaw, viewport.camera.pitch)
    viewport.camera.yaw = 90.0
    viewport.camera.pitch = 0.0
    viewport.set_snapshot(periodic_snapshot)
    viewport.inspection = "Base Color"
    periodic_image, periodic_raw = _capture_preview_frame(window)
    periodic_image.save(str(evidence_dir / "atx26-diagnostic-periodic-sphere.png"))
    center = periodic_raw.shape[1] // 2
    seam_slice = periodic_raw[
        periodic_raw.shape[0] // 4 : 3 * periodic_raw.shape[0] // 4,
        max(0, center - 4) : center + 5,
        :3,
    ].astype(np.float32)
    seam_jump = float(np.abs(seam_slice[:, 4] - seam_slice[:, 3]).mean())
    neighboring_jump = (
        float(
            np.abs(seam_slice[:, 3] - seam_slice[:, 2]).mean()
            + np.abs(seam_slice[:, 5] - seam_slice[:, 6]).mean()
        )
        / 2
    )
    assert seam_jump <= max(neighboring_jump * 3.0, 18.0), (
        f"periodic synthetic sphere shows an anomalous UV seam: "
        f"{seam_jump:.2f} vs {neighboring_jump:.2f} neighboring gradient"
    )
    synthetic_metrics["periodic_sphere"] = {
        "cpu_edge_gradient": periodic_edge,
        "cpu_interior_gradient": periodic_interior,
        "center_seam_gradient": seam_jump,
        "neighbor_gradient": neighboring_jump,
        "native_frame_stddev": float(periodic_raw[..., :3].astype(np.float32).std()),
    }
    viewport.camera.yaw, viewport.camera.pitch = original_camera_angles

    viewport.inspection = "UV Checker"
    checker_image, checker_raw = _capture_preview_frame(window)
    checker_image.save(str(evidence_dir / "atx26-diagnostic-uv-checker.png"))
    checker_metrics = {
        "native_frame_stddev": float(checker_raw[..., :3].astype(np.float32).std()),
        "native_frame_range": int(checker_raw[..., :3].max() - checker_raw[..., :3].min()),
        "native_center_stddev": float(
            checker_raw[
                checker_raw.shape[0] // 4 : 3 * checker_raw.shape[0] // 4,
                checker_raw.shape[1] // 4 : 3 * checker_raw.shape[1] // 4,
                :3,
            ]
            .astype(np.float32)
            .std()
        ),
    }
    assert checker_metrics["native_frame_stddev"] > 8, "procedural UV Checker is flat"
    return {
        "uv_attributes": uv_metrics,
        "synthetic_upload": synthetic_metrics,
        "procedural_checker": checker_metrics,
    }


def _replace_scalar_output(recipe, semantic: str, value: float) -> None:
    output = next(item for item in recipe.outputs if item.semantic == semantic)
    definition = REGISTRY.get("generator.constant")
    output.layers[0].source = OperationInstance(
        f"atx26-{semantic}-{uuid.uuid4().hex[:8]}",
        definition.identifier,
        definition.version,
        parameters={"value": value},
    )
    output.layers[0].transforms = []
    output.layers[0].color_ramp = None


def _edit_height_source(recipe) -> None:
    output = next(item for item in recipe.outputs if item.semantic == "height")
    source = output.layers[0].source
    seed = source.parameters.get("seed")
    if isinstance(seed, (float, int)):
        source.parameters["seed"] = int(seed) + 913
        return
    definition = REGISTRY.get("generator.fractal_noise")
    source.operation_id = definition.identifier
    source.operation_version = definition.version
    source.parameters = {spec.identifier: spec.default for spec in definition.parameter_specs}
    source.parameters["seed"] = 913


def _select_pipeline_context(window: MainWindow) -> None:
    window.authoring_mode_combo.setCurrentIndex(1)
    window.right_tabs.setCurrentIndex(1)
    window.advanced_tabs.setCurrentWidget(window.control_fields_scroll)
    height_output = next(
        item for item in window.document.recipe.outputs if item.semantic == "height"
    )
    height_index = window.output_selector.findData(height_output.output_id)
    assert height_index >= 0
    window.output_selector.setCurrentIndex(height_index)
    layer = window._layer()
    window.pipeline_panel.source_selector.setCurrentIndex(
        window.pipeline_panel.source_selector.findData(layer.source.operation_id)
    )
    assert not window.property_editor.isHidden()
    for transform in layer.transforms:
        row = next(
            index
            for index in range(window.pipeline_panel.transform_list.count())
            if window.pipeline_panel.transform_list.item(index).data(Qt.ItemDataRole.UserRole)
            == transform.instance_id
        )
        transform_list = window.pipeline_panel.transform_list
        transform_list.setCurrentItem(None)
        transform_list.setCurrentRow(row)
        assert not window.property_editor.isHidden()
        assert window.property_editor._heading.text() == REGISTRY.get(transform.operation_id).name


def _exercise_all_outputs_and_layers(window: MainWindow) -> dict[str, int]:
    counts = {"outputs": 0, "layers": 0, "sources": 0, "transforms": 0}
    for output in window.document.recipe.outputs:
        index = window.output_selector.findData(output.output_id)
        assert index >= 0
        window.output_selector.setCurrentIndex(index)
        counts["outputs"] += 1
        for row, layer in enumerate(output.layers):
            window.layers_panel.layer_list.setCurrentRow(row)
            assert window._selected_layer_id == layer.layer_id
            counts["layers"] += 1
            window._select_instance(layer.source.instance_id)
            assert (
                window.property_editor._heading.text()
                == REGISTRY.get(layer.source.operation_id).name
            )
            assert not window.property_editor.isHidden()
            counts["sources"] += 1
            for transform_row, transform in enumerate(layer.transforms):
                transform_list = window.pipeline_panel.transform_list
                transform_list.setCurrentItem(None)
                transform_list.setCurrentRow(transform_row)
                assert (
                    window.property_editor._heading.text()
                    == REGISTRY.get(transform.operation_id).name
                )
                assert not window.property_editor.isHidden()
                counts["transforms"] += 1
    return counts


def _wheel_event(local: QPoint, global_position: QPoint) -> QWheelEvent:
    return QWheelEvent(
        QPointF(local),
        QPointF(global_position),
        QPoint(0, 0),
        QPoint(0, 120),
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
        Qt.ScrollPhase.ScrollUpdate,
        False,
    )


def _exercise_simple_workflow(window: MainWindow) -> dict[str, object]:
    panel = window.simple_material_panel
    assert window.authoring_mode_combo.currentIndex() == 0
    assert window.output_selector.isHidden()
    assert window.preview_controls.mesh.currentText() == "UV Sphere"
    assert window.preview_controls.quality.currentText() == "High"
    assert window.preview_controls.mode.currentText() == "Material"
    view = window.preview_viewport
    panel_origin = panel.mapTo(window.left_authoring_scroll, QPoint(0, 0))
    layers_origin = window.layers_panel.mapTo(window.left_authoring_scroll, QPoint(0, 0))
    assert abs(panel_origin.x() - layers_origin.x()) <= 2
    assert layers_origin.y() >= panel_origin.y() + panel.height() - 4

    def viewport_state():
        camera = view.camera
        return (
            camera.distance,
            camera.fov,
            camera.projection,
            tuple(camera.target),
            camera.yaw,
            camera.pitch,
            window.workspace_stack.size().width(),
            window.workspace_stack.size().height(),
            view.size().width(),
            view.size().height(),
            tuple(window.centralWidget().sizes()),
        )

    stable_viewport = viewport_state()
    if window.document.recipe.control_fields:
        assert set(panel.control_spins) >= {"Scale", "Wear"}

    tip = panel.tileability
    tip_position = tip.mapToGlobal(tip.rect().center())
    QCursor.setPos(tip_position)
    QTest.mouseMove(tip, tip.rect().center())
    QApplication.sendEvent(tip, QEvent(QEvent.Type.Enter))
    QTest.qWait(window._delayed_help._delay_ms + 150)
    delayed_help_shown = QToolTip.isVisible()
    QToolTip.hideText()
    assert delayed_help_shown, "registered tileability help did not appear after its delay"

    for semantic, _label in panel.CHANNELS:
        panel.channel_buttons[semantic].click()
        assert window._selected_output().semantic == semantic
        assert window.layers_panel.layer_list.count() > 0
        assert viewport_state() == stable_viewport
    panel.channel_buttons["base_color"].click()
    assert window.layers_panel.pipeline_descriptor.text().startswith("Color — ")

    scale_difference = None
    if "Scale" in panel.control_spins:
        _before_control, before_raw, _snapshot = _render_preview(window)
        recipe_before = copy.deepcopy(window.document.recipe)
        scale = panel.control_spins["Scale"]
        start_scale = scale.value()
        target_scale = min(scale.maximum(), max(scale.minimum(), start_scale * 1.65))
        if target_scale == start_scale:
            target_scale = min(scale.maximum(), start_scale + 0.5)
        expected_scale = round(target_scale, scale.decimals())
        scale.setValue(target_scale)
        assert viewport_state() == stable_viewport
        applied_scale = window.document.recipe.control_fields["Scale"].source.parameters[
            panel.control_targets["Scale"][1]
        ]
        assert abs(float(applied_scale) - expected_scale) < 0.001
        _after_control, after_raw, _snapshot = _render_preview(window)
        scale_difference = _image_difference(before_raw, after_raw)
        assert scale_difference > 0.05, "Simple Scale control did not update the material preview"
        window.undo()
        assert window.document.recipe == recipe_before
        _render_preview(window)

    selection = (
        window._selected_output_id,
        window._selected_layer_id,
        window._selected_instance_id,
    )
    state_recipe = copy.deepcopy(window.document.recipe)
    state_history = copy.deepcopy(window.document.history.entries)
    state_index = window.document.history.index
    state_dirty = window.document.dirty
    for index in (1, 0, 1, 0):
        window.authoring_mode_combo.setCurrentIndex(index)
        assert viewport_state() == stable_viewport, (
            f"authoring mode {index} changed viewport state: "
            f"before={stable_viewport!r} after={viewport_state()!r}"
        )
        assert window.document.recipe == state_recipe
        assert window.document.history.entries == state_history
        assert window.document.history.index == state_index
        assert window.document.dirty == state_dirty
        assert (
            window._selected_output_id,
            window._selected_layer_id,
            window._selected_instance_id,
        ) == selection
    assert window.output_selector.isHidden()
    window.authoring_mode_combo.setCurrentIndex(1)
    window.advanced_tabs.setCurrentWidget(window.preview_controls_scroll)
    assert not window.output_selector.isHidden()

    start_distance = view.camera.distance
    combo = window.preview_controls.view
    combo_position = combo.rect().center()
    QApplication.sendEvent(
        combo,
        _wheel_event(combo_position, combo.mapToGlobal(combo_position)),
    )
    assert abs(view.camera.distance - start_distance) < 1e-6
    window.preview_controls.view.setCurrentText("Front")
    assert abs(view.camera.distance - start_distance) < 1e-6
    combo.showPopup()
    QApplication.processEvents()
    popup_view = combo.view()
    popup_position = popup_view.viewport().rect().center()
    QApplication.sendEvent(
        popup_view.viewport(),
        _wheel_event(popup_position, popup_view.viewport().mapToGlobal(popup_position)),
    )
    combo.hidePopup()
    assert abs(view.camera.distance - start_distance) < 1e-6
    scroll_bar = window.preview_controls_scroll.verticalScrollBar()
    scroll_position = window.preview_controls_scroll.viewport().rect().center()
    QApplication.sendEvent(
        window.preview_controls_scroll.viewport(),
        _wheel_event(
            scroll_position,
            window.preview_controls_scroll.viewport().mapToGlobal(scroll_position),
        ),
    )
    assert abs(view.camera.distance - start_distance) < 1e-6

    viewport_position = view.rect().center()
    QApplication.sendEvent(
        view,
        _wheel_event(viewport_position, view.mapToGlobal(viewport_position)),
    )
    assert view.camera.distance < start_distance, "Wheel over the 3D viewport did not zoom"
    window.preview_controls.mode.setCurrentText("Normal")
    assert window.preview_mode_indicator.text() == "NORMAL INSPECTION"
    window.preview_controls.mode.setCurrentText("Material")
    assert window.preview_mode_indicator.text() == "MATERIAL PREVIEW"
    window.preview_controls.view.setCurrentText("Orbit")

    # Confirm the narrow right inspector remains scrollable at a compact common window size.
    window.resize(920, 640)
    window.show()
    window.authoring_mode_combo.setCurrentIndex(1)
    window.advanced_tabs.setCurrentWidget(window.preview_controls_scroll)
    QApplication.processEvents()
    scroll_bar = window.preview_controls_scroll.verticalScrollBar()
    assert scroll_bar.maximum() > 0
    window.preview_controls_scroll.ensureWidgetVisible(window.preview_controls.reset)
    QApplication.processEvents()
    assert scroll_bar.value() == scroll_bar.maximum()
    window.authoring_mode_combo.setCurrentIndex(0)
    window.resize(1560, 980)
    window.preview_controls.mode.setCurrentText("Material")
    return {
        "channels": [semantic for semantic, _label in panel.CHANNELS],
        "scale_control_frame_difference": scale_difference,
        "simple_advanced_preserved_recipe_history_selection": True,
        "combo_popup_and_scroll_no_zoom": True,
        "viewport_wheel_zoomed": True,
        "mode_indicator": window.preview_mode_indicator.text(),
        "compact_window_scroll_reaches_bottom": True,
        "simple_controls_available": list(panel.control_spins),
    }


def main() -> int:
    if os.name != "nt":
        raise RuntimeError("ATX 26 image acceptance requires native Windows Qt.")
    starter_name = os.environ.get("ATX26_STARTER", "default")
    report_path = Path(os.environ["ATX26_REPORT"])
    evidence_dir = Path(os.environ["ATX26_EVIDENCE_DIR"])
    evidence_dir.mkdir(parents=True, exist_ok=True)
    recipe = (
        default_recipe() if starter_name == "default" else create_material_starter(starter_name)
    )
    app = QApplication.instance() or QApplication([])
    window = MainWindow(recipe)
    preview_trace_path = report_path.with_suffix(".preview.log")
    preview_build = window.preview_builder.build
    preview_complete = window._on_preview_complete

    def trace_preview_complete(outcome):
        request_id, snapshot, error, signature = outcome
        with preview_trace_path.open("a", encoding="utf-8") as stream:
            stream.write(
                f"complete request={request_id} size={getattr(snapshot, 'width', None)} "
                f"current={window._preview_request_id} "
                f"signature_matches={signature == window._latest_preview_signature} "
                f"error={error!r}\n"
            )
        preview_complete(outcome)

    window._preview_bridge.completed.disconnect(window._on_preview_complete)
    window._preview_bridge.completed.connect(
        trace_preview_complete, Qt.ConnectionType.QueuedConnection
    )

    def trace_preview_build(*args, **kwargs):
        request_id, width, height = args[2], args[3], args[4]
        with preview_trace_path.open("a", encoding="utf-8") as stream:
            stream.write(f"start request={request_id} size={width}x{height} time={time.time()}\n")
        try:
            result = preview_build(*args, **kwargs)
        except Exception:
            with preview_trace_path.open("a", encoding="utf-8") as stream:
                stream.write(traceback.format_exc() + "\n")
            raise
        with preview_trace_path.open("a", encoding="utf-8") as stream:
            stream.write(f"done request={request_id} size={width}x{height} time={time.time()}\n")
        return result

    window.preview_builder.build = trace_preview_build
    window._confirm_discard = lambda: True
    window.resize(1560, 980)
    window.show()
    _wait_until(lambda: window.isVisible(), message="main window did not appear")
    assert app.platformName().lower() in {"windows", "windows:fonts"}, app.platformName()
    window._reset_preview()
    QApplication.processEvents()
    authoring_widgets = (
        window.left_authoring_scroll.findChildren(QPushButton)
        + window.left_authoring_scroll.findChildren(QComboBox)
        + window.left_authoring_scroll.findChildren(QSpinBox)
        + window.left_authoring_scroll.findChildren(QDoubleSpinBox)
    )
    clipped_controls = [
        f"{widget.objectName() or widget.text()}: {widget.width()} < "
        f"{widget.minimumSizeHint().width()}"
        for widget in authoring_widgets
        if widget.isVisible() and widget.width() + 4 < widget.minimumSizeHint().width()
    ]
    assert not clipped_controls, f"left authoring controls are clipped: {clipped_controls}"

    window.preview_controls.resolution.setCurrentIndex(
        window.preview_controls.resolution.findData(None)
    )
    window.preview_controls.mesh.setCurrentText("UV Sphere")
    window.preview_controls.quality.setCurrentText("High")
    window.workspace_mode_combo.setCurrentIndex(1)
    _wait_until(
        lambda: window.preview_viewport.available or bool(window.preview_viewport._gl_error),
        timeout=12,
        message="OpenGL preview did not initialize",
    )
    assert window.preview_viewport.available, window.preview_viewport.unavailable_message
    assert window.preview_viewport.mesh_type == "UV Sphere"
    assert window.preview_viewport.quality == "High"
    assert window.preview_viewport.inspection == "Material"
    _wait_until(
        lambda: (
            window.preview_viewport.snapshot is not None
            and window.preview_viewport.snapshot.width == 512
        ),
        timeout=60,
        message=(
            "quick Auto preview did not arrive at 512 px; "
            f"snapshot={getattr(window.preview_viewport.snapshot, 'width', None)}, "
            f"request={window._preview_request_id}, "
            f"renders={window.preview_builder.rendered_outputs}, "
            f"status={window.statusBar().currentMessage()!r}, "
            f"error={window.preview_unavailable_label.text()!r}"
        ),
    )
    auto_resolution = window._auto_preview_resolution()
    _wait_until(
        lambda: (
            window.preview_viewport.snapshot is not None
            and window.preview_viewport.snapshot.width >= auto_resolution
        ),
        timeout=120,
        message=(
            "Auto preview did not refine to its viewport-matched resolution; "
            f"expected_at_least={auto_resolution}, "
            f"actual={getattr(window.preview_viewport.snapshot, 'width', None)}"
        ),
    )
    simple_metrics = _exercise_simple_workflow(window)
    window.preview_controls.resolution.setCurrentIndex(
        window.preview_controls.resolution.findData(512)
    )
    window._preview_refine_timer.stop()
    diagnostic_metrics = _diagnose_sampling(window, evidence_dir)
    report_path.write_text(json.dumps({"sampling_diagnostics": diagnostic_metrics}, indent=2))
    print(f"ATX26 native sampling diagnostics: {json.dumps(diagnostic_metrics)}", flush=True)
    window.preview_viewport.inspection = "Material"
    window._request_preview()
    restored_request_id = window._preview_request_id
    _wait_until(
        lambda: (
            window.preview_viewport.snapshot is not None
            and window.preview_viewport.snapshot.request_id >= restored_request_id
        ),
        message=(
            "material preview did not recover after diagnostic snapshot; "
            f"snapshot={getattr(window.preview_viewport.snapshot, 'request_id', None)}, "
            f"request={window._preview_request_id}, "
            f"renders={window.preview_builder.rendered_outputs}, "
            f"status={window.statusBar().currentMessage()!r}, "
            f"error={window.preview_unavailable_label.text()!r}"
        ),
    )
    window.preview_controls.mode.setCurrentText("Material")
    material_image, material_raw, original_snapshot = _render_preview(window)
    safe_starter_name = starter_name.replace("/", "-")
    material_image.save(str(evidence_dir / f"atx26-{safe_starter_name}-material.png"))
    window.preview_controls.mode.setCurrentText("Base Color")
    base_image, base_raw, _ = _render_preview(window)
    base_image.save(str(evidence_dir / f"atx26-{safe_starter_name}-base-color.png"))
    window.preview_controls.mode.setCurrentText("UV Checker")
    checker_image, checker_raw, _ = _render_preview(window)
    checker_image.save(str(evidence_dir / f"atx26-{safe_starter_name}-uv-checker.png"))
    window.preview_controls.mode.setCurrentText("World Normal")
    world_image, world_raw, _ = _render_preview(window)
    world_image.save(str(evidence_dir / f"atx26-{safe_starter_name}-world-normal.png"))
    window.preview_controls.mode.setCurrentText("Normal")
    normal_image, normal_raw, _ = _render_preview(window)
    normal_image.save(str(evidence_dir / f"atx26-{safe_starter_name}-normal.png"))
    window.preview_controls.mode.setCurrentText("Material")
    material_image, material_raw, original_snapshot = _render_preview(window)
    _check_material_frame(base_raw, f"{starter_name} Base Color")
    _check_material_frame(checker_raw, f"{starter_name} UV Checker")
    _check_material_frame(world_raw, f"{starter_name} World Normal")
    window.preview_controls.mode.setCurrentText("Material")
    material_image, material_raw, original_snapshot = _render_preview(window)
    material_metrics = _check_material_frame(material_raw, starter_name)
    base_color_view_difference = _image_difference(base_raw, material_raw)
    normal_view_difference = _image_difference(normal_raw, material_raw)
    assert base_color_view_difference > 2.0, f"{starter_name}: Base Color and Material views match"
    assert normal_view_difference > 2.0, f"{starter_name}: Normal and Material views match"

    # Workspace navigation must leave all document and editing state intact.
    _select_pipeline_context(window)
    selection_counts = _exercise_all_outputs_and_layers(window)
    _select_pipeline_context(window)
    window._layer_opacity_changed(window._selected_layer_id, 0.71)
    window.undo()
    before = (
        window.document.recipe,
        window.document.dirty,
        list(window.document.history.entries),
        window.document.history.index,
        window._selected_output_id,
        window._selected_layer_id,
        window._selected_instance_id,
    )
    for _ in range(3):
        window.workspace_mode_combo.setCurrentIndex(0)
        window.workspace_mode_combo.setCurrentIndex(1)
        assert before == (
            window.document.recipe,
            window.document.dirty,
            window.document.history.entries,
            window.document.history.index,
            window._selected_output_id,
            window._selected_layer_id,
            window._selected_instance_id,
        )
    assert window.preview_mode_combo.currentText() == "Material"
    assert window.preview_mode_indicator.text() == "MATERIAL PREVIEW"
    assert not window.preview_mode_indicator.isHidden()

    # Edit Output and Preview Mode are independent; the combined preview remains bound to all maps.
    metallic_output = next(
        output for output in window.document.recipe.outputs if output.semantic == "metallic"
    )
    metallic_index = window.output_selector.findData(metallic_output.output_id)
    assert metallic_index >= 0
    window.output_selector.setCurrentIndex(metallic_index)
    assert window.preview_mode_combo.currentText() == "Material"
    assert window.preview_viewport.snapshot.resolved_output_ids["base_color"] is not None
    window.preview_controls.mode.setCurrentText("Roughness")
    _wait_until(lambda: window.preview_viewport.snapshot is not None)
    roughness_image, roughness_raw, roughness_snapshot = _render_preview(window)
    roughness_difference = _image_difference(material_raw, roughness_raw)
    assert roughness_difference > 2.0, f"{starter_name}: Material and Roughness views match"
    if starter_name == "Rough Stone":
        roughness_image.save(str(evidence_dir / "atx26-rough-stone-roughness.png"))

    # Editing the Base Color ramp changes the material image.
    color_recipe = window.document.recipe
    base_output = next(item for item in color_recipe.outputs if item.semantic == "base_color")
    ramp_layer = base_output.layers[0]
    assert ramp_layer.color_ramp is not None
    ramp_layer.color_ramp = ColorRamp(
        tuple(
            ColorStop(stop.position, (0.08, 0.75, 0.92, 1.0))
            for stop in ramp_layer.color_ramp.stops
        )
    )
    window.document.commit(color_recipe)
    window._refresh_document(request_render=False)
    window.preview_controls.mode.setCurrentText("Material")
    _, color_raw, color_snapshot = _render_preview(window)
    base_color_difference = _image_difference(material_raw, color_raw)
    assert base_color_difference > 1.5, (
        f"{starter_name}: Base Color edit did not alter material image"
    )

    # Roughness and Metallic must affect reflected lighting in combined Material mode.
    # A controlled inspection rig avoids the user-editable saved light setup masking the
    # material response with ambient fill or tone-map clipping.
    window.preview_controls.exposure.setValue(0.4)
    window.preview_controls.key_intensity.setValue(4.0)
    window.preview_controls.fill_intensity.setValue(0.15)
    window.preview_controls.rim_intensity.setValue(0.25)
    window.preview_controls.ambient_intensity.setValue(0.15)
    window._apply_preview_settings()
    rough_recipe = window.document.recipe
    _replace_scalar_output(rough_recipe, "roughness", 0.04)
    window.document.commit(rough_recipe)
    window._refresh_document(request_render=False)
    _, smooth_raw, smooth_snapshot = _render_preview(window)
    window.preview_viewport.inspection = "Roughness Map RGB"
    roughness_low_image, roughness_low_map_raw = _capture_preview_frame(window)
    roughness_low_image.save(str(evidence_dir / f"{safe_starter_name}-roughness-map-low.png"))
    window.preview_viewport.inspection = "Material"
    rough_recipe = window.document.recipe
    _replace_scalar_output(rough_recipe, "roughness", 0.96)
    window.document.commit(rough_recipe)
    window._refresh_document(request_render=False)
    _, rough_raw, rough_snapshot = _render_preview(window)
    window.preview_viewport.inspection = "Roughness Map RGB"
    roughness_high_image, roughness_high_map_raw = _capture_preview_frame(window)
    roughness_high_image.save(str(evidence_dir / f"{safe_starter_name}-roughness-map-high.png"))
    roughness_map_difference = _image_difference(roughness_low_map_raw, roughness_high_map_raw)
    window.preview_viewport.inspection = "Material"
    window.preview_viewport.update()
    roughness_lighting_difference = _image_difference(smooth_raw, rough_raw)
    roughness_center_difference = _image_difference(
        smooth_raw[
            smooth_raw.shape[0] // 4 : 3 * smooth_raw.shape[0] // 4,
            smooth_raw.shape[1] // 4 : 3 * smooth_raw.shape[1] // 4,
        ],
        rough_raw[
            rough_raw.shape[0] // 4 : 3 * rough_raw.shape[0] // 4,
            rough_raw.shape[1] // 4 : 3 * rough_raw.shape[1] // 4,
        ],
    )
    material_image.save(str(evidence_dir / "atx26-default-material.png"))
    np.save(str(evidence_dir / "atx26-default-roughness-smooth.npy"), smooth_raw)
    np.save(str(evidence_dir / "atx26-default-roughness-rough.npy"), rough_raw)
    print(
        "ATX26 roughness probe: "
        + json.dumps(
            {
                "low_map_mean": float(smooth_snapshot.maps["roughness"].mean()),
                "high_map_mean": float(rough_snapshot.maps["roughness"].mean()),
                "frame_difference": roughness_lighting_difference,
                "object_center_difference": roughness_center_difference,
                "shader_map_difference": roughness_map_difference,
            }
        ),
        flush=True,
    )
    assert roughness_center_difference > 0.5, (
        f"{starter_name}: roughness edit had no lighting effect"
    )

    metal_recipe = window.document.recipe
    _replace_scalar_output(metal_recipe, "metallic", 1.0)
    window.document.commit(metal_recipe)
    window._refresh_document(request_render=False)
    _, metal_raw, _ = _render_preview(window)
    metallic_difference = _image_difference(rough_raw, metal_raw)
    assert metallic_difference > 0.5, f"{starter_name}: metallic edit had no shading effect"

    height_recipe = window.document.recipe
    _edit_height_source(height_recipe)
    window.document.commit(height_recipe)
    window._refresh_document(request_render=False)
    _, height_raw, height_snapshot = _render_preview(window)
    height_difference = _image_difference(metal_raw, height_raw)
    normal_difference = float(
        np.mean(
            np.abs(
                original_snapshot.maps["normal"].astype(np.float32)
                - height_snapshot.maps["normal"].astype(np.float32)
            )
        )
    )
    assert height_difference > 0.5, f"{starter_name}: Height edit did not change material preview"
    assert normal_difference > 0.001, (
        f"{starter_name}: Height edit did not change derived Normal map"
    )
    window.preview_controls.mode.setCurrentText("Normal")
    height_normal_image, height_normal_raw, _ = _render_preview(window)
    height_normal_image.save(str(evidence_dir / f"{safe_starter_name}-height-derived-normal.png"))
    height_normal_difference = _image_difference(normal_raw, height_normal_raw)
    assert height_normal_difference > 1.0, (
        f"{starter_name}: Height -> Normal did not change surface lighting"
    )

    # Camera motion must alter the native framebuffer independently of map edits.
    before_camera = height_raw
    window.preview_viewport.camera.orbit(24, 13)
    window.preview_viewport.update()
    QTest.qWait(100)
    camera_image = window.preview_viewport.grabFramebuffer().convertToFormat(
        QImage.Format.Format_RGBA8888
    )
    camera_raw = (
        np.frombuffer(camera_image.bits(), dtype=np.uint8)
        .reshape(camera_image.height(), camera_image.width(), 4)
        .copy()
    )
    camera_difference = _image_difference(before_camera, camera_raw)
    assert camera_difference > 1.0, f"{starter_name}: camera movement did not alter preview"

    # Save and reopen the edited document through the production serializer.
    base_index = window.output_selector.findData("base-color")
    if base_index < 0:
        base_index = window.output_selector.findData(
            next(
                item.output_id
                for item in window.document.recipe.outputs
                if item.semantic == "base_color"
            )
        )
    window.output_selector.setCurrentIndex(base_index)
    selected_layer = window._layer()
    window._rename_layer(selected_layer.layer_id, f"{selected_layer.name} ATX26")
    assert window._layer().name.endswith("ATX26")
    window.layers_panel.set_recipe(
        window.document.recipe, window._selected_layer_id, window._selected_output_id
    )
    assert window.layers_panel.pipeline_descriptor.text() == window._layer_descriptor(
        window._layer()
    )
    if window._layer().mask is None:
        window._add_layer_mask(window._selected_layer_id)
    assert window._layer().mask is not None
    window._navigate_to_layer_mask(window._selected_layer_id)
    assert window.control_fields_editor.selected_field_id == window._layer().mask.source_id
    assert window._layer().name in window.color_ramp_editor.title_label.text()
    saved_path = evidence_dir / f"{starter_name.replace('/', '-')}-roundtrip.atx"
    save_project(window.document.recipe, saved_path)
    reopened = load_project(saved_path)
    assert reopened == window.document.recipe
    window.document.open_project(saved_path)
    window._refresh_document(request_render=False)

    report = {
        "result": "passed",
        "starter": starter_name,
        "qt_platform": app.platformName(),
        "gl_available": window.preview_viewport.available,
        "material": material_metrics,
        "simple_workflow": simple_metrics,
        "sampling_diagnostics": diagnostic_metrics,
        "material_roughness_view_difference": roughness_difference,
        "base_color_view_difference": base_color_view_difference,
        "normal_view_difference": normal_view_difference,
        "base_color_image_difference": base_color_difference,
        "roughness_lighting_difference": roughness_lighting_difference,
        "roughness_lighting_object_center_difference": roughness_center_difference,
        "metallic_image_difference": metallic_difference,
        "height_to_normal_image_difference": height_difference,
        "height_to_normal_lighting_difference": height_normal_difference,
        "height_to_normal_map_difference": normal_difference,
        "camera_image_difference": camera_difference,
        "outputs": len(recipe.outputs),
        "layers": sum(len(output.layers) for output in recipe.outputs),
        "selection_counts": selection_counts,
        "control_fields": len(recipe.control_fields),
        "ramp_present": any(
            layer.color_ramp for output in recipe.outputs for layer in output.layers
        ),
        "save_reopen": True,
        "mask_edit": True,
        "layer_rename_and_descriptor": True,
    }
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    window.close()
    app.processEvents()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
