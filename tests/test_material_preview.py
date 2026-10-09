from __future__ import annotations

import numpy as np
import pytest

from archetexture.core.defaults import default_recipe
from archetexture.preview.bindings import PreviewMaterialBinding
from archetexture.preview.camera import CameraState, projection_matrix, view_matrix
from archetexture.preview.gl_viewport import (
    INSPECTION_MODES,
    LIGHTING_PRESETS,
    MaterialGLViewport,
    _set_typed_uniform,
)
from archetexture.preview.mesh import MESH_QUALITIES, MESH_TYPES, generate_mesh
from archetexture.preview.pbr import cook_torrance, decode_normal
from archetexture.preview.snapshot import PreviewSnapshotBuilder


@pytest.mark.parametrize("mesh_type", MESH_TYPES)
@pytest.mark.parametrize("quality", MESH_QUALITIES)
def test_all_meshes_have_valid_tangent_basis(mesh_type, quality):
    mesh = generate_mesh(mesh_type, quality)
    mesh.validate()
    assert mesh.positions.shape[1] == mesh.normals.shape[1] == 3
    assert mesh.uvs.shape[1] == 2
    assert mesh.tangents.shape[1] == 4
    np.testing.assert_allclose(np.linalg.norm(mesh.normals, axis=1), 1, atol=1e-5)
    np.testing.assert_allclose(np.linalg.norm(mesh.tangents[:, :3], axis=1), 1, atol=1e-5)


def test_mesh_cache_and_invalid_options():
    assert generate_mesh("Cube", "Low") is generate_mesh("Cube", "Low")
    with pytest.raises(ValueError):
        generate_mesh("Icosahedron", "High")


def test_uv_sphere_qualities_are_smooth_and_ordered():
    meshes = [generate_mesh("UV Sphere", quality) for quality in MESH_QUALITIES]
    vertex_counts = [len(mesh.positions) for mesh in meshes]
    assert vertex_counts == sorted(vertex_counts)
    assert vertex_counts[0] >= 800
    for mesh in meshes:
        np.testing.assert_allclose(mesh.positions, mesh.normals, atol=1e-5)


def test_glsl_float_uniforms_use_float_upload_even_for_integer_item_data():
    class Program:
        def uniformLocation(self, name):
            return {b"tileU": 3, b"wire": 4}[name]

        def setUniformValue(self, location, value):
            raise AssertionError("numeric uniforms should use typed OpenGL uploads")

    class Functions:
        def __init__(self):
            self.floats = []
            self.ints = []

        def glUniform1f(self, location, value):
            self.floats.append((location, value))

        def glUniform1i(self, location, value):
            self.ints.append((location, value))

    functions = Functions()
    program = Program()
    _set_typed_uniform(program, functions, "tileU", 1)
    _set_typed_uniform(program, functions, "wire", True)
    assert functions.floats == [(3, 1.0)]
    assert functions.ints == [(4, 1)]


def test_auto_bindings_use_semantics_and_ids_not_names():
    recipe = default_recipe()
    binding = PreviewMaterialBinding()
    assert binding.resolve(recipe) == {
        "base_color": "base-color",
        "roughness": "roughness",
        "metallic": "metallic",
        "normal": "normal",
        "height": "height",
        "ambient_occlusion": "ambient-occlusion",
        "emissive": None,
        "opacity": None,
    }
    recipe.output("base-color").name = "Renamed color map"
    assert binding.resolve(recipe)["base_color"] == "base-color"


def test_binding_fallback_preferences_and_manual_override():
    recipe = default_recipe()
    recipe.outputs[0].semantic = "diffuse"
    recipe.outputs[1].semantic = "glossiness"
    recipe.outputs[1].output_id = "gloss"
    recipe.outputs[1].name = "Gloss"
    binding = PreviewMaterialBinding({"roughness": "missing"})
    mapped = binding.resolve(recipe)
    assert mapped["base_color"] == "base-color"
    assert mapped["roughness"] == "gloss"
    assert mapped["height"] == "height"


def test_camera_orbit_zoom_pan_reset_views_and_projection():
    camera = CameraState()
    start = camera.position.copy()
    camera.orbit(30, 20)
    assert not np.allclose(camera.position, start)
    before = camera.distance
    camera.zoom(2)
    assert camera.distance < before
    center = camera.target.copy()
    camera.pan(12, -8)
    assert not np.allclose(camera.target, center)
    camera.set_view("Front")
    assert camera.yaw == 0 and camera.pitch == 0
    assert np.isfinite(view_matrix(camera)).all()
    assert not np.allclose(
        projection_matrix(camera, 1.0),
        projection_matrix(CameraState(projection="Orthographic"), 1.0),
    )
    camera.reset()
    assert camera.distance == 3.2 and camera.projection == "Perspective"


def test_pbr_reference_math_and_normal_conventions_are_finite():
    color = np.array([[[0.7, 0.2, 0.1]]], dtype=np.float32)
    normal = np.array([[[0.0, 0.0, 1.0]]], dtype=np.float32)
    view = np.array([[[0.0, 0.0, 1.0]]], dtype=np.float32)
    light = np.array([[[0.2, 0.3, 1.0]]], dtype=np.float32)
    dielectric = cook_torrance(color, normal, view, light, 0.4, 0)
    metal = cook_torrance(color, normal, view, light, 0.4, 1)
    smooth = cook_torrance(color, normal, view, light, 0.08, 0.5)
    rough = cook_torrance(color, normal, view, light, 0.95, 0.5)
    assert np.isfinite(dielectric).all()
    assert not np.allclose(dielectric, metal)
    assert not np.allclose(smooth, rough)
    assert np.all(cook_torrance(color, normal, view, light, 0.4, 0, ao=0) < dielectric)
    assert np.all(cook_torrance(color, normal, view, light, 0.4, 0, emissive=0.5) > dielectric)
    encoded = np.array([[[0.5, 0.75, 1.0]]], dtype=np.float32)
    gl = decode_normal(encoded, strength=1)
    dx = decode_normal(encoded, directx=True, strength=1)
    assert gl[0, 0, 1] == pytest.approx(-dx[0, 0, 1])
    assert np.isfinite(decode_normal(encoded, strength=2)).all()


def test_snapshot_channel_minimization_and_live_normal_dependency():
    recipe = default_recipe()
    builder = PreviewSnapshotBuilder()
    snapshot = builder.build(recipe, PreviewMaterialBinding(), 1, 32, 32, inspection="Roughness")
    assert builder.last_requested_output_ids == ("roughness",)
    assert snapshot.maps["roughness"].shape == (32, 32, 1)
    assert not snapshot.maps["roughness"].flags.writeable
    with pytest.raises(TypeError):
        snapshot.maps["roughness"] = np.zeros((32, 32, 1), dtype=np.float32)
    normal = builder.build(recipe, PreviewMaterialBinding(), 2, 32, 32, inspection="Normal")
    assert builder.last_requested_output_ids == ("normal",)
    assert np.isfinite(normal.maps["normal"]).all()
    checker = builder.build(recipe, PreviewMaterialBinding(), 3, 32, 32, inspection="UV Checker")
    assert builder.last_requested_output_ids == ()
    assert builder.rendered_outputs == 2
    assert checker.maps["base_color"].shape == (32, 32, 4)


def test_inspection_and_lighting_option_catalogs_are_complete():
    assert set(INSPECTION_MODES) >= {
        "Material",
        "Base Color",
        "Roughness",
        "Metallic",
        "Normal",
        "Height",
        "Ambient Occlusion",
        "Emissive",
        "Opacity",
        "UV Checker",
        "World Normal",
    }
    assert len(LIGHTING_PRESETS) == 8


def test_snapshot_view_rejects_stale_request_without_context(qtbot):
    widget = MaterialGLViewport()
    qtbot.addWidget(widget)
    builder = PreviewSnapshotBuilder()
    first = builder.build(
        default_recipe(), PreviewMaterialBinding(), 2, 16, 16, inspection="UV Checker"
    )
    stale = builder.build(
        default_recipe(), PreviewMaterialBinding(), 1, 16, 16, inspection="UV Checker"
    )
    widget.set_snapshot(first)
    widget.set_snapshot(stale)
    assert widget.snapshot.request_id == 2
    widget.cleanup_gl()


def test_preview_preferences_and_mode_switch_do_not_dirty_document(qtbot, tmp_path):
    import json

    from PySide6.QtCore import QSettings

    from archetexture.core.material_starters import create_material_starter
    from archetexture.core.serialization import _encode_recipe
    from archetexture.ui.main_window import MainWindow

    QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(tmp_path))
    settings = QSettings(
        QSettings.Format.IniFormat,
        QSettings.Scope.UserScope,
        "ArcheTexture",
        "ArcheTexture",
    )
    settings.clear()
    window = MainWindow(create_material_starter("Rough Stone"))
    qtbot.addWidget(window)
    assert window.preview_controls.mesh.currentText() == "UV Sphere"
    assert window.preview_controls.quality.currentText() == "High"
    assert window.preview_controls.mode.currentText() == "Material"
    window._confirm_discard = lambda: True
    window.preview_controls.mesh.setCurrentText("Cube")
    window.preview_controls.exposure.setValue(1.0)
    window.output_selector.setCurrentIndex(window.output_selector.findData("height"))
    window._layer_opacity_changed(window._selected_layer_id, 0.4)
    window._layer_opacity_changed(window._selected_layer_id, 0.6)
    window.undo()
    window.right_tabs.setCurrentIndex(0)
    window._selected_instance_id = window._layer().transforms[0].instance_id
    window._refresh_document(request_render=False)

    def state():
        return (
            json.dumps(_encode_recipe(window.document.recipe), sort_keys=True),
            window.document.dirty,
            [
                json.dumps(_encode_recipe(item), sort_keys=True)
                for item in window.document.history.entries
            ],
            window.document.history.index,
            window._selected_output_id,
            window._selected_layer_id,
            window._selected_instance_id,
            window.right_tabs.currentWidget(),
        )

    before = state()
    assert before[1] and window.document.can_redo
    window.workspace_mode_combo.setCurrentIndex(1)
    assert state() == before
    assert window.preview_viewport.mesh_type == "Cube"
    assert window.preview_mode_combo.currentText() == "Material"
    assert window.preview_mode_indicator.text() == "MATERIAL PREVIEW"
    assert not window.preview_mode_indicator.isHidden()
    assert window.output_selector.objectName() == "material-output-selector"
    window.workspace_mode_combo.setCurrentIndex(0)
    assert window.workspace_stack.currentWidget() is window.viewport
    assert state() == before
    for _ in range(4):
        window.workspace_mode_combo.setCurrentIndex(1)
        assert state() == before
        window.workspace_mode_combo.setCurrentIndex(0)
        assert state() == before
    assert settings.value("preview/exposure") == 1.0
    window.close()


def test_preview_gl_failure_shows_message_and_keeps_2d_workspace(qtbot):
    from archetexture.ui.main_window import MainWindow

    window = MainWindow()
    qtbot.addWidget(window)
    window._confirm_discard = lambda: True
    window.preview_viewport.initialize_failure("No compatible context")
    window.workspace_mode_combo.setCurrentIndex(1)
    assert window.workspace_stack.currentWidget() is window.preview_unavailable_label
    assert "No compatible context" in window.preview_unavailable_label.text()
    window.workspace_mode_combo.setCurrentIndex(0)
    assert window.workspace_stack.currentWidget() is window.viewport
    window.close()


def test_native_gl_preview_pixels_and_view_changes_when_available(qtbot, tmp_path):
    widget = MaterialGLViewport()
    qtbot.addWidget(widget)
    widget.resize(640, 480)
    widget.show()
    qtbot.waitUntil(lambda: widget.available or bool(widget._gl_error), timeout=1800)
    if not widget.available:
        pytest.skip(widget.unavailable_message)
    snapshot = PreviewSnapshotBuilder().build(
        default_recipe(), PreviewMaterialBinding(), 1, 128, 128, inspection="Material"
    )
    widget.set_snapshot(snapshot)
    qtbot.wait(150)
    material = widget.grabFramebuffer()
    assert material.width() > 0 and material.height() > 0
    material.save(str(tmp_path / "material-preview.png"))
    raw = np.frombuffer(material.bits(), dtype=np.uint8).reshape(
        material.height(), material.width(), 4
    )
    assert np.isfinite(raw).all()
    assert int(raw[..., :3].max()) > int(raw[..., :3].min())
    assert float(raw[..., :3].std()) > 3.0

    widget.inspection = "World Normal"
    widget.update()
    qtbot.wait(100)
    normal = widget.grabFramebuffer()
    normal_raw = np.frombuffer(normal.bits(), dtype=np.uint8).reshape(
        normal.height(), normal.width(), 4
    )
    assert float(np.mean(np.abs(raw.astype(float) - normal_raw.astype(float)))) > 3.0

    widget.set_mesh("Cube")
    widget.camera.orbit(30, 14)
    widget.inspection = "Material"
    widget.update()
    qtbot.wait(100)
    changed = widget.grabFramebuffer()
    changed_raw = np.frombuffer(changed.bits(), dtype=np.uint8).reshape(
        changed.height(), changed.width(), 4
    )
    assert float(np.mean(np.abs(raw.astype(float) - changed_raw.astype(float)))) > 3.0
    widget.cleanup_gl()
