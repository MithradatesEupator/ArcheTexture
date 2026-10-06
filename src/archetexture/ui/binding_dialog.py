from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QLabel,
    QVBoxLayout,
)

from archetexture.core.parameters import ControlFieldBinding, ControlFieldMapping, ParameterSpec


class BindingDialog(QDialog):
    """Edit a reusable control-field reference and its parameter mapping."""

    def __init__(
        self,
        control_fields: dict,
        spec: ParameterSpec,
        binding: ControlFieldBinding | None = None,
        parent=None,
    ):
        super().__init__(parent)
        self.setWindowTitle(f"Modulate {spec.name}")
        self.spec = spec
        self.field_combo = QComboBox(self)
        self.field_combo.setObjectName("binding-control-field")
        for identifier in control_fields:
            self.field_combo.addItem(identifier, identifier)
        if binding is not None:
            mapping = binding.mapping
        else:
            output_min = spec.min_value if spec.min_value is not None else 0.0
            if spec.max_value is not None:
                output_max = spec.max_value
            else:
                output_max = max(1.0, output_min + 1.0)
            if spec.max_value is not None and spec.min_value is None:
                output_min = min(0.0, spec.max_value - 1.0)
            mapping = ControlFieldMapping(output_min=output_min, output_max=output_max)
        if binding is not None:
            index = self.field_combo.findData(binding.source_id)
            if index >= 0:
                self.field_combo.setCurrentIndex(index)

        low = spec.min_value if spec.min_value is not None else min(0.0, mapping.output_min)
        high = spec.max_value if spec.max_value is not None else max(1.0, mapping.output_max)
        high = max(low, high)
        self.minimum = self._spin(low, high, mapping.output_min, "binding-output-min")
        self.maximum = self._spin(low, high, mapping.output_max, "binding-output-max")
        self.invert = QCheckBox("Invert", self)
        self.invert.setChecked(mapping.invert)
        self.curve = QComboBox(self)
        self.curve.setObjectName("binding-curve")
        self.curve.addItems(("linear", "smoothstep", "stepped"))
        self.curve.setCurrentText(mapping.curve)
        self.quantize = self._spin(0.0, 256.0, mapping.quantize or 0.0, "binding-quantize")
        self.quantize.setToolTip("0 disables quantization")
        self.notice = QLabel("Quantize levels: 0 disables quantization", self)
        form = QFormLayout()
        form.addRow("Control field", self.field_combo)
        form.addRow("Output minimum", self.minimum)
        form.addRow("Output maximum", self.maximum)
        form.addRow(self.invert)
        form.addRow("Curve", self.curve)
        form.addRow("Quantize levels", self.quantize)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel, self
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Apply")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(self.notice)
        layout.addWidget(buttons)

    @staticmethod
    def _spin(minimum: float, maximum: float, value: float, name: str) -> QDoubleSpinBox:
        spin = QDoubleSpinBox()
        spin.setObjectName(name)
        spin.setDecimals(4)
        spin.setRange(minimum, maximum)
        spin.setSingleStep(0.01)
        spin.setValue(value)
        return spin

    @property
    def binding(self) -> ControlFieldBinding:
        return ControlFieldBinding(
            str(self.field_combo.currentData()),
            ControlFieldMapping(
                output_min=self.minimum.value(),
                output_max=self.maximum.value(),
                invert=self.invert.isChecked(),
                curve=self.curve.currentText(),
                quantize=self.quantize.value() or None,
            ),
        )
