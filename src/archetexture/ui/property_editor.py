from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QCheckBox,
    QColorDialog,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from archetexture.core.operations import OperationDefinition, OperationType
from archetexture.core.parameters import ControlFieldBinding, ParameterSpec, ParameterType
from archetexture.core.recipe import OperationInstance


class _DirectSpinBox(QSpinBox):
    def wheelEvent(self, event) -> None:
        if self.hasFocus():
            super().wheelEvent(event)
        else:
            event.ignore()


class _DirectDoubleSpinBox(QDoubleSpinBox):
    def wheelEvent(self, event) -> None:
        if self.hasFocus():
            super().wheelEvent(event)
        else:
            event.ignore()


class PropertyEditor(QWidget):
    valueChanged = Signal(str, object)
    bindingRequested = Signal(str, object, object)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._form = QFormLayout()
        self._control_fields: dict = {}
        self._layout = QVBoxLayout(self)
        self._heading = QLabel("Properties")
        self._heading.setStyleSheet("font-weight: 600; font-size: 15px")
        self._layout.addWidget(self._heading)
        self._layout.addLayout(self._form)
        self._layout.addStretch(1)
        self.setMinimumWidth(260)

    def set_operation(
        self,
        instance: OperationInstance | None,
        definition: OperationDefinition | None,
    ) -> None:
        self._clear_form()
        if instance is None or definition is None:
            self._heading.setText("Properties")
            self._form.addRow(QLabel("Select a source or transform."))
            return
        self._heading.setText(definition.name)
        for spec in definition.parameter_specs:
            value = instance.parameters.get(spec.identifier, spec.default)
            self._form.addRow(spec.name, self._make_widget(spec, value))
        if definition.operation_type == OperationType.TRANSFORM:
            influence_spec = ParameterSpec(
                "influence",
                "Influence",
                ParameterType.PERCENT,
                default=1.0,
                min_value=0.0,
                max_value=1.0,
                step=0.01,
                description="Blend between the previous field and this transform.",
            )
            self._form.addRow("Influence", self._make_widget(influence_spec, instance.influence))

    def _clear_form(self) -> None:
        while self._form.rowCount():
            self._form.removeRow(0)

    def _make_widget(self, spec: ParameterSpec, value) -> QWidget:
        if isinstance(value, ControlFieldBinding):
            container = QWidget()
            row = QHBoxLayout(container)
            row.setContentsMargins(0, 0, 0, 0)
            row.addWidget(QLabel(f"Control field: {value.source_id}"), 1)
            actions = QWidget()
            action_row = QHBoxLayout(actions)
            action_row.setContentsMargins(0, 0, 0, 0)
            edit = QPushButton("Edit binding")
            edit.setObjectName(f"edit-binding-{spec.identifier}")
            edit.setEnabled(bool(self._control_fields))
            edit.clicked.connect(
                lambda _checked=False, key=spec.identifier, parameter=spec, current=value: (
                    self.bindingRequested.emit(key, parameter, current)
                )
            )
            action_row.addWidget(edit)
            unlink = QPushButton("Use constant")
            unlink.setObjectName(f"unbind-{spec.identifier}")
            unlink.clicked.connect(
                lambda _checked=False, key=spec.identifier, default=spec.default: (
                    self.valueChanged.emit(key, default)
                )
            )
            action_row.addWidget(unlink)
            row.addWidget(actions)
            container.setObjectName(f"parameter-{spec.identifier}")
            container.setToolTip(spec.description)
            return container

        if spec.type == ParameterType.BOOLEAN:
            widget = QCheckBox()
            widget.setChecked(bool(value))
            widget.toggled.connect(
                lambda changed, key=spec.identifier: self.valueChanged.emit(key, changed)
            )
        elif spec.type == ParameterType.ENUM:
            widget = QComboBox()
            widget.addItems(list(spec.options))
            index = widget.findText(str(value))
            widget.setCurrentIndex(index)
            widget.currentTextChanged.connect(
                lambda changed, key=spec.identifier: self.valueChanged.emit(key, changed)
            )
        elif spec.type in {ParameterType.INTEGER, ParameterType.SEED}:
            widget = _DirectSpinBox()
            widget.setRange(
                int(spec.min_value if spec.min_value is not None else -(2**31)),
                int(spec.max_value if spec.max_value is not None else 2**31 - 1),
            )
            widget.setSingleStep(max(1, int(spec.step or 1)))
            widget.setValue(int(value))
            widget.valueChanged.connect(
                lambda changed, key=spec.identifier: self.valueChanged.emit(key, changed)
            )
        elif spec.type in {ParameterType.FLOAT, ParameterType.ANGLE, ParameterType.PERCENT}:
            widget = _DirectDoubleSpinBox()
            widget.setDecimals(3)
            widget.setRange(
                spec.min_value if spec.min_value is not None else -1e6,
                spec.max_value if spec.max_value is not None else 1e6,
            )
            widget.setSingleStep(spec.step or 0.01)
            widget.setValue(float(value))
            widget.valueChanged.connect(
                lambda changed, key=spec.identifier: self.valueChanged.emit(key, changed)
            )
        elif spec.type == ParameterType.COLOR:
            widget = QPushButton()
            color = self._color(value)
            self._paint_color_button(widget, color)

            def choose_color(_checked=False, key=spec.identifier, button=widget, initial=color):
                chosen = QColorDialog.getColor(
                    initial,
                    self,
                    "Choose color",
                    QColorDialog.ColorDialogOption.ShowAlphaChannel,
                )
                if chosen.isValid():
                    self._paint_color_button(button, chosen)
                    self.valueChanged.emit(key, tuple(chosen.getRgbF()))

            widget.clicked.connect(choose_color)
        elif spec.type == ParameterType.POSITION_2D:
            widget = QWidget()
            row = QHBoxLayout(widget)
            row.setContentsMargins(0, 0, 0, 0)
            fields = []
            for component in value:
                spin = _DirectDoubleSpinBox()
                spin.setRange(-1e6, 1e6)
                spin.setDecimals(3)
                spin.setSingleStep(spec.step or 0.01)
                spin.setValue(float(component))
                row.addWidget(spin)
                fields.append(spin)
            for spin in fields:
                spin.valueChanged.connect(
                    lambda _changed, key=spec.identifier, controls=fields: self.valueChanged.emit(
                        key, tuple(control.value() for control in controls)
                    )
                )
        else:
            widget = QLabel(str(value))
            widget.setEnabled(False)
        widget.setObjectName(f"parameter-{spec.identifier}")
        widget.setToolTip(spec.description)
        if spec.allows_modulation and spec.type in {
            ParameterType.FLOAT,
            ParameterType.INTEGER,
            ParameterType.ANGLE,
            ParameterType.PERCENT,
        }:
            container = QWidget()
            row = QHBoxLayout(container)
            row.setContentsMargins(0, 0, 0, 0)
            row.addWidget(widget, 1)
            modulate = QPushButton("Modulate…")
            modulate.setObjectName(f"modulate-{spec.identifier}")
            modulate.setEnabled(bool(self._control_fields))
            modulate.setToolTip(
                "Create a control field first" if not self._control_fields else spec.description
            )
            modulate.clicked.connect(
                lambda _checked=False, key=spec.identifier, parameter=spec: (
                    self.bindingRequested.emit(key, parameter, None)
                )
            )
            row.addWidget(modulate)
            return container
        return widget

    def set_control_fields(self, control_fields: dict) -> None:
        self._control_fields = control_fields

    @staticmethod
    def _color(value) -> QColor:
        channels = tuple(value)
        if len(channels) == 3:
            channels = (*channels, 1.0)
        color = QColor()
        color.setRgbF(*channels)
        return color

    @staticmethod
    def _paint_color_button(button: QPushButton, color: QColor) -> None:
        button.setText(color.name(QColor.NameFormat.HexArgb))
        button.setStyleSheet(
            f"background-color: {color.name(QColor.NameFormat.HexArgb)};"
            "border: 1px solid palette(mid); padding: 5px;"
        )
