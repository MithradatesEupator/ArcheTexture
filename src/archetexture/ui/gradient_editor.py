from __future__ import annotations

import copy

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QVBoxLayout,
)

from archetexture.color.ramp import ColorRamp, ColorStop
from archetexture.core.recipe import LayerRecipe
from archetexture.ui.color_ramp_editor import ColorRampEditor
from archetexture.ui.numeric_control import NumericControl


class GradientEditorDialog(QDialog):
    """Edits one gradient layer as a single undoable material operation."""

    previewChanged = Signal(object)

    def __init__(self, layer: LayerRecipe, parent=None):
        super().__init__(parent)
        self.setObjectName("gradient-editor-dialog")
        self.setWindowTitle(f"Gradient Editor · {layer.name}")
        self.setModal(True)
        self._layer = copy.deepcopy(layer)

        layout = QVBoxLayout(self)
        heading = QLabel(layer.name)
        heading.setObjectName("gradient-editor-layer-name")
        layout.addWidget(heading)
        self.description = QLabel(
            "Edit the gradient colors and shape. Changes preview live; Apply adds one undo step."
        )
        self.description.setWordWrap(True)
        layout.addWidget(self.description)

        form = QFormLayout()
        self.kind = QComboBox(self)
        self.kind.setObjectName("gradient-kind")
        self.kind.addItem("Linear Gradient", "generator.linear_gradient")
        self.kind.addItem("Radial Gradient", "generator.radial_gradient")
        form.addRow("Gradient", self.kind)
        self.angle = NumericControl(
            0.0, minimum=0.0, maximum=360.0, step=1.0, decimals=1, unit="°", parent=self
        )
        self.angle.setObjectName("gradient-angle")
        form.addRow("Direction", self.angle)
        self.radius = NumericControl(
            0.5, minimum=0.01, maximum=1.0, step=0.01, decimals=2, parent=self
        )
        self.radius.setObjectName("gradient-radius")
        form.addRow("Radius", self.radius)
        self.opacity = NumericControl(
            1.0, minimum=0.0, maximum=1.0, step=0.05, decimals=2, unit="Opacity", parent=self
        )
        self.opacity.setObjectName("gradient-opacity")
        form.addRow("Opacity", self.opacity)
        layout.addLayout(form)

        self.ramp_editor = ColorRampEditor(self)
        self.ramp_editor.setObjectName("gradient-color-stops")
        self.ramp_editor.set_context_name(layer.name)
        self.ramp_editor.create_button.hide()
        self.ramp_editor.remove_ramp_button.hide()
        layout.addWidget(self.ramp_editor)

        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Cancel | QDialogButtonBox.StandardButton.Apply,
            parent=self,
        )
        self.buttons.button(QDialogButtonBox.StandardButton.Apply).setText("Apply")
        layout.addWidget(self.buttons)
        self.buttons.rejected.connect(self.reject)
        self.buttons.button(QDialogButtonBox.StandardButton.Apply).clicked.connect(self.accept)

        operation_id = self._layer.source.operation_id
        index = self.kind.findData(operation_id)
        if index < 0:
            index = self.kind.findData("generator.linear_gradient")
        self.kind.setCurrentIndex(index)
        self.kind.currentIndexChanged.connect(self._kind_changed)
        self.angle.valueChanged.connect(self._angle_changed)
        self.radius.valueChanged.connect(self._radius_changed)
        self.opacity.valueChanged.connect(self._opacity_changed)
        self.ramp_editor.rampEdited.connect(self._ramp_changed)
        self.ramp_editor.previewRequested.connect(self._ramp_changed)
        self._sync_controls()
        self.resize(500, 650)

    @staticmethod
    def default_ramp() -> ColorRamp:
        return ColorRamp(
            (
                ColorStop(0.0, (0.055, 0.12, 0.22, 1.0)),
                ColorStop(1.0, (0.95, 0.55, 0.20, 1.0)),
            )
        )

    @property
    def edited_layer(self) -> LayerRecipe:
        layer = copy.deepcopy(self._layer)
        layer.color_ramp = self.ramp_editor.ramp
        layer.opacity = self.opacity.value()
        return layer

    def _sync_controls(self) -> None:
        operation_id = self._layer.source.operation_id
        self.kind.blockSignals(True)
        self.kind.setCurrentIndex(max(0, self.kind.findData(operation_id)))
        self.kind.blockSignals(False)
        self.angle.blockSignals(True)
        self.angle.setValue(float(self._layer.source.parameters.get("angle", 0.0)))
        self.angle.blockSignals(False)
        self.radius.blockSignals(True)
        self.radius.setValue(float(self._layer.source.parameters.get("radius", 0.5)))
        self.radius.blockSignals(False)
        self.opacity.blockSignals(True)
        self.opacity.setValue(float(self._layer.opacity))
        self.opacity.blockSignals(False)
        ramp = self._layer.color_ramp or self.default_ramp()
        self.ramp_editor.set_ramp(ramp, reset_selection=True, applicable=True)
        self.angle.setVisible(operation_id == "generator.linear_gradient")
        self.radius.setVisible(operation_id == "generator.radial_gradient")

    def _kind_changed(self, _index: int) -> None:
        operation_id = str(self.kind.currentData())
        self._layer.source.operation_id = operation_id
        if operation_id == "generator.linear_gradient":
            self._layer.source.parameters = {"angle": self.angle.value()}
        else:
            self._layer.source.parameters = {"radius": self.radius.value()}
        self._sync_controls()
        self._emit_preview()

    def _angle_changed(self, value: float) -> None:
        self._layer.source.parameters["angle"] = value
        self._emit_preview()

    def _radius_changed(self, value: float) -> None:
        self._layer.source.parameters["radius"] = value
        self._emit_preview()

    def _opacity_changed(self, value: float) -> None:
        self._layer.opacity = value
        self._emit_preview()

    def _ramp_changed(self, ramp: ColorRamp | None) -> None:
        if ramp is not None:
            self._layer.color_ramp = ramp
            self._emit_preview()

    def _emit_preview(self) -> None:
        self.previewChanged.emit(self.edited_layer)
