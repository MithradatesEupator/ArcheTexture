from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtGui import QColor, QFont
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

from archetexture.core.assets import AssetReference, RenderContext
from archetexture.core.operations import OperationDefinition, OperationType
from archetexture.core.output_dependencies import transitive_output_dependencies
from archetexture.core.parameters import ControlFieldBinding, ParameterSpec, ParameterType
from archetexture.core.recipe import OperationInstance
from archetexture.ui.delayed_help import DelayedHelp
from archetexture.ui.numeric_control import NumericControl


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
    assetBrowseRequested = Signal(str, object)
    editStarted = Signal()
    editFinished = Signal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("property-editor")
        self._form = QFormLayout()
        self._control_fields: dict = {}
        self._material_outputs = []
        self._current_output_id: str | None = None
        self._cycle_targets: set[str] = set()
        self._project_path = None
        self._simple_mode = False
        self._operation_signature = None
        self._parameter_values: dict[str, object] = {}
        self._layout = QVBoxLayout(self)
        self._heading = QLabel("Properties")
        heading_font = QFont(self._heading.font())
        heading_font.setWeight(QFont.Weight.DemiBold)
        heading_font.setPointSize(15)
        self._heading.setFont(heading_font)
        self._layout.addWidget(self._heading)
        self._layout.addLayout(self._form)
        self._layout.addStretch(1)
        self.setMinimumWidth(260)

    def set_operation(
        self,
        instance: OperationInstance | None,
        definition: OperationDefinition | None,
    ) -> None:
        visible_specs = []
        signature = None
        if instance is not None and definition is not None:
            visible_specs = [
                spec
                for spec in definition.parameter_specs
                if not self._simple_mode
                or spec.identifier not in {"seed", "offset_x", "offset_y", "rotation"}
            ]
            self._parameter_values = {
                spec.identifier: instance.parameters.get(spec.identifier, spec.default)
                for spec in visible_specs
            }
            signature = (
                instance.instance_id,
                definition.identifier,
                self._simple_mode,
                tuple(
                    (
                        spec.identifier,
                        spec.type,
                        type(instance.parameters.get(spec.identifier, spec.default)),
                    )
                    for spec in visible_specs
                ),
                (
                    type(instance.influence)
                    if definition.operation_type == OperationType.TRANSFORM
                    else None
                ),
            )
            if signature == self._operation_signature and self._sync_existing_values(
                instance, definition, visible_specs
            ):
                self._heading.setText(definition.name)
                return

        self._clear_form()
        self._operation_signature = signature
        if instance is None or definition is None:
            self._heading.setText("Properties")
            self._form.addRow(QLabel("Select a source or transform."))
            return
        if self._simple_mode and definition.operation_type == OperationType.TRANSFORM:
            self._heading.setText("Advanced transform")
            self._form.addRow(QLabel("Switch to Advanced Editor to edit transforms."))
            return
        self._heading.setText(definition.name)
        operation_id = definition.identifier
        mode = instance.parameters.get("mode", "Direct")
        for spec in visible_specs:
            value = instance.parameters.get(spec.identifier, spec.default)
            widget = self._make_widget(spec, value)
            if spec.description:
                DelayedHelp.register(widget, spec.description)
            if spec.type == ParameterType.MATERIAL_OUTPUT and isinstance(widget, QComboBox):
                blocked = widget.blockSignals(True)
                widget.clear()
                for output in self._material_outputs:
                    if (
                        output.output_id == self._current_output_id
                        or output.output_id in self._cycle_targets
                    ):
                        continue
                    if (
                        operation_id == "generator.output_scalar"
                        and mode == "Direct"
                        and output.value_type != "scalar"
                    ):
                        continue
                    if (
                        operation_id == "generator.output_scalar"
                        and mode != "Direct"
                        and output.value_type == "scalar"
                    ):
                        continue
                    widget.addItem(f"{output.name} · {output.value_type.title()}", output.output_id)
                index = widget.findData(value)
                if index < 0:
                    widget.addItem("Missing output" if value else "Select an output", value)
                    index = widget.count() - 1
                widget.setCurrentIndex(index)
                widget.blockSignals(blocked)
            label = spec.name
            if self._simple_mode and spec.identifier in {"scale", "frequency", "density"}:
                label = "Pattern Scale"
            elif (
                self._simple_mode
                and operation_id == "transform.height_to_normal"
                and spec.identifier == "strength"
            ):
                label = "Surface Depth"
            self._form.addRow(label, widget)
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
            influence_widget = self._make_widget(influence_spec, instance.influence)
            DelayedHelp.register(influence_widget, influence_spec.description)
            self._form.addRow("Influence", influence_widget)

    def _sync_existing_values(self, instance, definition, specs) -> bool:
        for spec in specs:
            value = instance.parameters.get(spec.identifier, spec.default)
            widget = self.findChild(QWidget, f"parameter-{spec.identifier}")
            if widget is None:
                return False
            if isinstance(value, ControlFieldBinding):
                label = widget.findChild(QLabel)
                if label is None:
                    return False
                label.setText(f"Control field: {value.source_id}")
                edit_button = widget.findChild(QPushButton, f"edit-binding-{spec.identifier}")
                if edit_button is not None:
                    edit_button.setEnabled(bool(self._control_fields))
            elif spec.type == ParameterType.IMAGE_ASSET:
                label = widget.findChild(QLabel)
                button = widget.findChild(QPushButton)
                if label is None or button is None:
                    return False
                path = value.path if isinstance(value, AssetReference) else ""
                missing = bool(path) and not RenderContext(self._project_path).exists(value)
                label.setText(("Missing · " if missing else "") + (path or "No image selected"))
                label.setToolTip(path)
                button.setText("Relink…" if missing else "Replace…" if path else "Browse…")
            elif spec.type == ParameterType.BOOLEAN and isinstance(widget, QCheckBox):
                blocked = widget.blockSignals(True)
                widget.setChecked(bool(value))
                widget.blockSignals(blocked)
            elif spec.type == ParameterType.ENUM and isinstance(widget, QComboBox):
                blocked = widget.blockSignals(True)
                index = widget.findText(str(value))
                if index >= 0:
                    widget.setCurrentIndex(index)
                widget.blockSignals(blocked)
            elif spec.type == ParameterType.MATERIAL_OUTPUT and isinstance(widget, QComboBox):
                blocked = widget.blockSignals(True)
                widget.clear()
                for output in self._material_outputs:
                    if output.output_id == self._current_output_id:
                        continue
                    if output.output_id in self._cycle_targets:
                        continue
                    widget.addItem(f"{output.name} · {output.value_type.title()}", output.output_id)
                index = widget.findData(value)
                if index < 0:
                    widget.addItem("Missing output" if value else "Select an output", value)
                    index = widget.count() - 1
                widget.setCurrentIndex(index)
                widget.blockSignals(blocked)
            elif spec.type in {ParameterType.INTEGER, ParameterType.SEED} and isinstance(
                widget, QSpinBox
            ):
                blocked = widget.blockSignals(True)
                widget.setValue(int(value))
                widget.blockSignals(blocked)
            elif isinstance(widget, NumericControl):
                blocked = widget.blockSignals(True)
                widget.setValue(
                    float(value) * 100.0 if spec.type == ParameterType.PERCENT else value
                )
                widget.blockSignals(blocked)
            elif spec.type in {
                ParameterType.FLOAT,
                ParameterType.ANGLE,
                ParameterType.PERCENT,
            } and isinstance(widget, QDoubleSpinBox):
                blocked = widget.blockSignals(True)
                widget.setValue(float(value))
                widget.blockSignals(blocked)
            elif spec.type == ParameterType.COLOR and isinstance(widget, QPushButton):
                self._paint_color_button(widget, self._color(value))
            elif spec.type == ParameterType.POSITION_2D:
                spins = widget.findChildren(QDoubleSpinBox)
                if len(spins) != len(value):
                    return False
                for spin, component in zip(spins, value, strict=True):
                    blocked = spin.blockSignals(True)
                    spin.setValue(float(component))
                    spin.blockSignals(blocked)
            else:
                return False
            for button in self.findChildren(QPushButton, f"modulate-{spec.identifier}"):
                button.setEnabled(bool(self._control_fields))
        if definition.operation_type == OperationType.TRANSFORM:
            influence = self.findChild(QDoubleSpinBox, "parameter-influence")
            if influence is None:
                return False
            blocked = influence.blockSignals(True)
            influence.setValue(instance.influence)
            influence.blockSignals(blocked)
            modulate = self.findChild(QPushButton, "modulate-influence")
            if modulate is not None:
                modulate.setEnabled(bool(self._control_fields))
        return True

    def _clear_form(self) -> None:
        while self._form.rowCount():
            self._form.removeRow(0)

    def set_simple_mode(self, simple: bool) -> None:
        self._simple_mode = simple

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
                lambda _checked=False, key=spec.identifier, parameter=spec: (
                    self.bindingRequested.emit(
                        key, parameter, self._parameter_values.get(key, value)
                    )
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

        if spec.type == ParameterType.IMAGE_ASSET:
            container = QWidget()
            row = QHBoxLayout(container)
            row.setContentsMargins(0, 0, 0, 0)
            path = value.path if isinstance(value, AssetReference) else ""
            missing = bool(path) and not RenderContext(self._project_path).exists(value)
            label = QLabel(("Missing · " if missing else "") + (path or "No image selected"))
            label.setToolTip(path)
            button = QPushButton("Relink…" if missing else "Replace…" if path else "Browse…")
            button.clicked.connect(
                lambda _checked=False, key=spec.identifier: self.assetBrowseRequested.emit(
                    key, self._parameter_values.get(key)
                )
            )
            row.addWidget(label, 1)
            row.addWidget(button)
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
        elif spec.type == ParameterType.MATERIAL_OUTPUT:
            widget = QComboBox()
            for output in self._material_outputs:
                if (
                    output.output_id != self._current_output_id
                    and output.output_id not in self._cycle_targets
                ):
                    widget.addItem(f"{output.name} · {output.value_type.title()}", output.output_id)
            index = widget.findData(value)
            if index < 0 and value:
                widget.addItem("Missing output", value)
                index = widget.count() - 1
            widget.setCurrentIndex(index)
            widget.currentIndexChanged.connect(
                lambda _changed, combo=widget, key=spec.identifier: self.valueChanged.emit(
                    key, combo.currentData()
                )
            )
        elif self._simple_mode and spec.type in {ParameterType.INTEGER, ParameterType.SEED}:
            widget = NumericControl(
                int(value),
                minimum=int(spec.min_value if spec.min_value is not None else -(2**31)),
                maximum=int(spec.max_value if spec.max_value is not None else 2**31 - 1),
                step=max(1, int(spec.step or 1)),
                decimals=0,
                parent=self,
            )
            widget.valueChanged.connect(
                lambda changed, key=spec.identifier: self.valueChanged.emit(key, changed)
            )
            widget.editStarted.connect(self.editStarted)
            widget.editFinished.connect(self.editFinished)
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
        elif self._simple_mode and spec.type in {
            ParameterType.FLOAT,
            ParameterType.ANGLE,
            ParameterType.PERCENT,
        }:
            unit = (
                "°"
                if spec.type == ParameterType.ANGLE
                else "%"
                if spec.type == ParameterType.PERCENT
                else ""
            )
            initial = float(value) * 100.0 if spec.type == ParameterType.PERCENT else float(value)
            minimum = float(spec.min_value if spec.min_value is not None else -1e6)
            maximum = float(spec.max_value if spec.max_value is not None else 1e6)
            step = float(spec.step or 0.01)
            if spec.type == ParameterType.PERCENT:
                minimum, maximum, step = minimum * 100.0, maximum * 100.0, step * 100.0
            widget = NumericControl(
                initial,
                minimum=minimum,
                maximum=maximum,
                step=step,
                decimals=2 if spec.type == ParameterType.PERCENT else 3,
                unit=unit,
                parent=self,
            )
            widget.valueChanged.connect(
                lambda changed, key=spec.identifier, kind=spec.type: self.valueChanged.emit(
                    key, float(changed) / 100.0 if kind == ParameterType.PERCENT else changed
                )
            )
            widget.editStarted.connect(self.editStarted)
            widget.editFinished.connect(self.editFinished)
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

    def set_material_outputs(self, recipe, current_output_id: str | None) -> None:
        self._material_outputs = list(recipe.outputs)
        self._current_output_id = current_output_id
        self._cycle_targets = {
            output.output_id
            for output in recipe.outputs
            if current_output_id in transitive_output_dependencies(recipe, output.output_id)
        }

    def set_project_path(self, project_path) -> None:
        self._project_path = project_path

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
