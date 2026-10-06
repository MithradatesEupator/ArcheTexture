from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDoubleSpinBox, QFileDialog, QMessageBox

from archetexture.color.ramp import ColorRamp, ColorStop
from archetexture.core.assets import AssetReference, RenderContext
from archetexture.core.parameters import ControlFieldBinding
from archetexture.core.recipe import (
    ControlFieldRecipe,
    LayerRecipe,
    OperationInstance,
    ProjectRecipe,
)
from archetexture.core.registry import REGISTRY
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
        qtbot.waitUntil(
            lambda: (
                not window.render_coordinator.is_running
                and window._latest_render_result is not None
            ),
            timeout=5000,
        )

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
