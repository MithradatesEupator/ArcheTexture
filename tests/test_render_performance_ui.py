from __future__ import annotations

import threading
from pathlib import Path

import numpy as np
from PIL import Image
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDoubleSpinBox, QFileDialog, QMessageBox

from archetexture.color.ramp import ColorRamp, ColorStop
from archetexture.core.assets import AssetReference, RenderContext
from archetexture.core.parameters import ControlFieldBinding, ControlFieldMapping
from archetexture.core.recipe import (
    ControlFieldRecipe,
    LayerRecipe,
    OperationInstance,
    ProjectRecipe,
)
from archetexture.core.registry import REGISTRY
from archetexture.export.image_export import ImageExporter
from archetexture.render.coordinator import RenderOutcome
from archetexture.render.engine import RenderEngine
from archetexture.ui.main_window import build_main_window


def _operation(operation_id: str, identifier: str, **overrides) -> OperationInstance:
    definition = REGISTRY.get(operation_id)
    parameters = {spec.identifier: spec.default for spec in definition.parameter_specs}
    parameters.update(overrides)
    return OperationInstance(identifier, operation_id, definition.version, parameters=parameters)


def _recipe(image_path: Path) -> ProjectRecipe:
    layers = [
        LayerRecipe(
            "procedural",
            "Procedural",
            _operation("generator.fractal_noise", "procedural-source", seed=31, scale=3.0),
            [_operation("transform.blur", "procedural-blur", sigma=0.7)],
            color_ramp=ColorRamp(
                (ColorStop(0.0, (0.0, 0.02, 0.1, 1.0)), ColorStop(1.0, (0.9, 0.5, 0.1, 1.0)))
            ),
            mask=ControlFieldBinding("shared"),
        ),
        LayerRecipe(
            "image",
            "Image",
            _operation("generator.image", "image-source", asset=AssetReference(str(image_path))),
        ),
    ]
    return ProjectRecipe(
        width=32,
        height=24,
        layers=layers,
        control_fields={
            "shared": ControlFieldRecipe(
                _operation("generator.fractal_noise", "mask-source", seed=93, scale=2.0)
            )
        },
    )


def _wait_for_latest_displayed_render(window, qtbot):
    coordinator = window.render_coordinator
    expected_request_id = coordinator.latest_request_id

    def is_published():
        return (
            coordinator.latest_request_id == expected_request_id
            and window._latest_displayed_request_id == expected_request_id
            and not coordinator.is_running
            and coordinator.pending_request is None
        )

    qtbot.waitUntil(is_published, timeout=5000)
    return expected_request_id


def test_real_gui_edits_converge_and_document_switches_clear_previous_view(
    qtbot, monkeypatch, tmp_path
):
    first_image = tmp_path / "first.png"
    second_image = tmp_path / "second.png"
    Image.new("RGBA", (16, 16), (220, 25, 20, 255)).save(first_image)
    Image.new("RGBA", (16, 16), (15, 210, 45, 255)).save(second_image)
    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda *_args, **_kwargs: QMessageBox.StandardButton.Discard,
    )
    window = build_main_window(_recipe(first_image))
    qtbot.addWidget(window)
    window.show()

    def settled():
        return _wait_for_latest_displayed_render(window, qtbot)

    settled()
    session = window.render_session
    executions = session.stats["operation_executions"]

    window._select_layer("procedural")
    scale = window.property_editor.findChild(QDoubleSpinBox, "parameter-scale")
    assert scale is not None
    scale.setValue(scale.value() + 0.4)
    settled()
    assert session.stats["operation_executions"] - executions == 2
    assert session.stats["layers"]["hits"] >= 1

    # Composition-only widget edits reuse evaluated layer outputs.
    executions = session.stats["operation_executions"]
    window.layers_panel.opacity.setValue(0.65)
    settled()
    window.layers_panel.blend.setCurrentIndex(window.layers_panel.blend.findData("multiply"))
    settled()
    window.layers_panel.layer_list.setCurrentRow(1)
    window.layers_panel.up_button.click()
    settled()
    item = window.layers_panel.layer_list.item(0)
    item.setCheckState(Qt.CheckState.Unchecked)
    settled()
    item = window.layers_panel.layer_list.item(0)
    item.setCheckState(Qt.CheckState.Checked)
    settled()
    assert session.stats["operation_executions"] == executions

    window._select_layer("procedural")
    ramp = ColorRamp((ColorStop(0.0, (0.1, 0.1, 0.1, 1.0)), ColorStop(1.0, (1.0, 0.8, 0.3, 1.0))))
    window.color_ramp_editor.rampEdited.emit(ramp)
    settled()
    window.control_fields_editor.select_field("shared")
    control = window.document.recipe.control_fields["shared"]
    window.control_fields_editor.valueChanged.emit(
        "shared", (control.source.instance_id, "scale"), 3.25
    )
    settled()

    monkeypatch.setattr(
        QFileDialog, "getOpenFileName", lambda *_args, **_kwargs: (str(second_image), "")
    )
    window._select_layer("image")
    image_layer = next(
        layer for layer in window.document.recipe.layers if layer.layer_id == "image"
    )
    window.property_editor.assetBrowseRequested.emit(
        "asset", image_layer.source.parameters["asset"]
    )
    settled()
    decodes = session.asset_cache.stats["decodes"]
    Image.new("RGBA", (16, 16), (20, 40, 240, 255)).save(second_image)
    window._request_render()
    settled()
    assert session.asset_cache.stats["decodes"] == decodes + 1

    window._select_layer("procedural")
    for value in (5.1, 5.2, 5.3, 5.4):
        window.property_editor.valueChanged.emit("scale", value)
    settled()
    window.undo()
    settled()
    window.redo()
    settled()
    reference = RenderEngine().render(
        window.document.recipe,
        width=32,
        height=24,
        render_context=RenderContext(window.document.project_path),
    )
    np.testing.assert_array_equal(window.viewport.rendered_field, reference.rgba_field)
    assert "QWidget" in window._application.styleSheet()

    project_path = tmp_path / "gui-session.archetexture"
    window.document.save(project_path)
    assert window.open_project(project_path)
    assert window.viewport.rendered_field is None
    settled()
    assert window.new_document()
    assert window.viewport.rendered_field is None
    settled()
    assert session.stats["layers"]["entries"] > 0
    window.close()


def _dependency_recipe() -> ProjectRecipe:
    mask = ControlFieldRecipe(
        _operation("generator.fractal_noise", "mask-source", seed=82, scale=2.4),
        [_operation("transform.blur", "mask-blur", sigma=0.8)],
    )
    mod = ControlFieldRecipe(
        _operation("generator.fractal_noise", "mod-source", seed=83, scale=2.1)
    )
    unrelated = ControlFieldRecipe(
        _operation("generator.fractal_noise", "unrelated-source", seed=84, scale=1.7)
    )
    layers = []
    for index in range(6):
        scale = 3.0 + index
        if index == 0:
            scale = ControlFieldBinding("mod", ControlFieldMapping(output_min=2.0, output_max=5.0))
        layers.append(
            LayerRecipe(
                f"dependent-{index}",
                f"Dependent {index}",
                _operation(
                    "generator.fractal_noise", f"layer-source-{index}", seed=20 + index, scale=scale
                ),
                [_operation("transform.blur", f"layer-blur-{index}", sigma=0.75)],
                color_ramp=ColorRamp(
                    (
                        ColorStop(0.0, (0.05, 0.1, 0.2, 1.0)),
                        ColorStop(1.0, (0.9, 0.7, 0.3, 1.0)),
                    )
                ),
                mask=ControlFieldBinding("mask"),
            )
        )
    return ProjectRecipe(
        width=96,
        height=96,
        layers=layers,
        control_fields={"mask": mask, "mod": mod, "unrelated": unrelated},
    )


def test_gui_mask_modulation_undo_rename_and_export_dependency_workflow(
    qtbot, monkeypatch, tmp_path
):
    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda *_args, **_kwargs: QMessageBox.StandardButton.Discard,
    )
    window = build_main_window(_dependency_recipe())
    submitted_recipes = {}
    original_request = window.render_coordinator.request

    def capture_request(recipe, **kwargs):
        request = original_request(recipe, **kwargs)
        submitted_recipes[request.request_id] = request.recipe
        return request

    window.render_coordinator.request = capture_request
    qtbot.addWidget(window)
    window.show()

    def settled():
        return _wait_for_latest_displayed_render(window, qtbot)

    def matches_uncached():
        fresh = RenderEngine().render_uncached(
            window.document.recipe,
            width=window.document.recipe.width,
            height=window.document.recipe.height,
            render_context=RenderContext(window.document.project_path),
        )
        assert window._latest_displayed_request_id == window.render_coordinator.latest_request_id
        np.testing.assert_array_equal(window.viewport.rendered_field, fresh.rgba_field)

    def edit_control(identifier: str, value: float):
        control = window.document.recipe.control_fields[identifier]
        window.control_fields_editor.select_field(identifier)
        window.control_fields_editor.valueChanged.emit(
            identifier, (control.source.instance_id, "scale"), value
        )

    settled()
    session = window.render_session
    before = session.stats
    edit_control("mask", 2.8)
    settled()
    delta = _ui_stats_delta(session.stats, before)
    assert delta == {"ops": 2, "layer_hits": 6, "layer_misses": 0, "cf_hits": 0, "cf_misses": 1}
    matches_uncached()
    window.undo()
    settled()
    matches_uncached()
    window.redo()
    settled()
    matches_uncached()

    before = session.stats
    edit_control("unrelated", 2.4)
    settled()
    matches_uncached()
    delta = _ui_stats_delta(session.stats, before)
    assert delta["ops"] == 0 and delta["layer_hits"] == 6
    assert delta["layer_misses"] == 0
    window.undo()
    settled()
    matches_uncached()
    window.redo()
    settled()
    matches_uncached()

    before = session.stats
    edit_control("mod", 2.7)
    settled()
    delta = _ui_stats_delta(session.stats, before)
    assert delta["ops"] == 3 and delta["layer_hits"] == 5 and delta["layer_misses"] == 1
    matches_uncached()
    window.undo()
    settled()
    matches_uncached()
    window.redo()
    settled()
    matches_uncached()

    editor = window.control_fields_editor
    editor.select_field("mask")
    editor.name_input.setText("surface-mask")
    editor.rename_button.click()
    settled()
    assert "surface-mask" in window.document.recipe.control_fields
    assert all(layer.mask.source_id == "surface-mask" for layer in window.document.recipe.layers)
    matches_uncached()
    window.undo()
    settled()
    assert "mask" in window.document.recipe.control_fields
    assert all(layer.mask.source_id == "mask" for layer in window.document.recipe.layers)
    matches_uncached()
    window.redo()
    settled()
    assert "surface-mask" in window.document.recipe.control_fields
    matches_uncached()

    editor.select_field("surface-mask")
    before = session.stats
    control = window.document.recipe.control_fields["surface-mask"]
    edited_value = control.source.parameters["scale"] + 0.15
    edit_control("surface-mask", edited_value)
    request_id = settled()
    submitted = submitted_recipes[request_id]
    assert submitted.control_fields["surface-mask"].source.parameters["scale"] == edited_value
    assert all(layer.mask.source_id == "surface-mask" for layer in submitted.layers)
    delta = _ui_stats_delta(session.stats, before)
    assert delta["ops"] == 2
    assert delta["layer_hits"] == 6 and delta["layer_misses"] == 0
    assert delta["cf_misses"] == 1
    matches_uncached()
    window.undo()
    settled()
    assert "surface-mask" in window.document.recipe.control_fields
    assert all(layer.mask.source_id == "surface-mask" for layer in window.document.recipe.layers)
    assert (
        window.document.recipe.control_fields["surface-mask"].source.parameters["scale"]
        == control.source.parameters["scale"]
    )
    matches_uncached()
    window.redo()
    settled()
    assert "surface-mask" in window.document.recipe.control_fields
    assert all(layer.mask.source_id == "surface-mask" for layer in window.document.recipe.layers)
    assert (
        window.document.recipe.control_fields["surface-mask"].source.parameters["scale"]
        == edited_value
    )
    matches_uncached()

    project_path = tmp_path / "dependency-gui.archetexture"
    window.document.save(project_path)
    assert window.open_project(project_path)
    settled()
    matches_uncached()
    png_path = tmp_path / "dependency-gui.png"
    ImageExporter().export_png(
        window.document.recipe,
        png_path,
        render_context=RenderContext(window.document.project_path),
    )
    with Image.open(png_path) as exported:
        np.testing.assert_array_equal(
            np.asarray(exported),
            np.rint(window.viewport.rendered_field * 255.0).astype(np.uint8),
        )
    window.close()


def _ui_stats_delta(after: dict, before: dict) -> dict:
    return {
        "ops": after["operation_executions"] - before["operation_executions"],
        "layer_hits": after["layers"]["hits"] - before["layers"]["hits"],
        "layer_misses": after["layers"]["misses"] - before["layers"]["misses"],
        "cf_hits": after["controls"]["hits"] - before["controls"]["hits"],
        "cf_misses": after["controls"]["misses"] - before["controls"]["misses"],
    }


def test_worker_idle_does_not_count_as_latest_render_published(qtbot, monkeypatch):
    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda *_args, **_kwargs: QMessageBox.StandardButton.Discard,
    )
    window = build_main_window(_dependency_recipe())
    qtbot.addWidget(window)
    window.show()
    previous_id = _wait_for_latest_displayed_render(window, qtbot)
    previous_pixels = window.viewport.rendered_field.copy()

    held_outcomes = []
    completed = threading.Event()
    coordinator = window.render_coordinator
    original_completion = coordinator.on_complete

    def hold_completion(outcome):
        held_outcomes.append(outcome)
        completed.set()

    coordinator.on_complete = hold_completion
    control = window.document.recipe.control_fields["mask"]
    window._control_value_changed(
        "mask",
        (control.source.instance_id, "scale"),
        control.source.parameters["scale"] + 0.35,
    )
    latest_id = coordinator.latest_request_id
    assert latest_id > previous_id
    assert completed.wait(5)

    # Worker-idle plus any prior result is not proof the latest UI update landed.
    assert not coordinator.is_running
    assert window._latest_render_result is not None
    assert window._latest_displayed_request_id == previous_id
    assert window._latest_displayed_request_id != latest_id
    assert coordinator.active_request is None and coordinator.pending_request is None
    assert held_outcomes[0].request_id == latest_id
    assert held_outcomes[0].result is not None
    fresh = RenderEngine().render_uncached(
        window.document.recipe,
        render_context=RenderContext(window.document.project_path),
    )
    assert not np.array_equal(previous_pixels, fresh.rgba_field)
    np.testing.assert_array_equal(held_outcomes[0].result.rgba_field, fresh.rgba_field)
    np.testing.assert_array_equal(window.viewport.rendered_field, previous_pixels)

    coordinator.on_complete = original_completion
    original_completion(held_outcomes[0])
    assert _wait_for_latest_displayed_render(window, qtbot) == latest_id
    assert window._latest_displayed_request_id == latest_id
    np.testing.assert_array_equal(window.viewport.rendered_field, fresh.rgba_field)
    window.close()


def test_delayed_old_qt_completion_cannot_regress_displayed_request(qtbot):
    window = build_main_window(_dependency_recipe())
    qtbot.addWidget(window)
    window.show()
    current_id = _wait_for_latest_displayed_render(window, qtbot)
    current_result = window._latest_render_result
    current_pixels = window.viewport.rendered_field.copy()
    assert current_id > 0 and current_result is not None

    old_recipe = _dependency_recipe()
    old_recipe.control_fields["mask"].source.parameters["scale"] = 9.0
    old_result = RenderEngine().render_uncached(old_recipe)
    old_outcome = RenderOutcome(current_id - 1, result=old_result)
    emitted = threading.Event()

    def emit_delayed_completion():
        window._render_bridge.completed.emit(old_outcome)
        emitted.set()

    delayed_worker = threading.Thread(target=emit_delayed_completion)
    delayed_worker.start()
    assert emitted.wait(3)
    delayed_worker.join(timeout=3)
    window._application.processEvents()

    assert window._latest_displayed_request_id == current_id
    assert window._latest_render_result is current_result
    np.testing.assert_array_equal(window.viewport.rendered_field, current_pixels)
    window.close()
