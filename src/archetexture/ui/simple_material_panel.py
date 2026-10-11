from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QKeyEvent, QWheelEvent
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QGridLayout,
    QLabel,
    QMenu,
    QPushButton,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from archetexture.core.operations import OperationType
from archetexture.core.parameters import ParameterType
from archetexture.core.recipe import ProjectRecipe
from archetexture.core.registry import REGISTRY
from archetexture.ui.numeric_control import NumericControl


class _SimpleControlSpinBox(QDoubleSpinBox):
    editStarted = Signal()
    editFinished = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._editing = False
        self.setKeyboardTracking(False)
        self.editingFinished.connect(self._finish_edit)

    def _begin_edit(self) -> None:
        if not self._editing:
            self._editing = True
            self.editStarted.emit()

    def _finish_edit(self) -> None:
        if self._editing:
            self._editing = False
            self.editFinished.emit()

    def focusInEvent(self, event) -> None:
        super().focusInEvent(event)
        self._begin_edit()

    def focusOutEvent(self, event) -> None:
        super().focusOutEvent(event)
        self._finish_edit()

    def mousePressEvent(self, event) -> None:
        self._begin_edit()
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        super().mouseReleaseEvent(event)
        self._finish_edit()

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() in {Qt.Key.Key_Up, Qt.Key.Key_Down} or event.text().isprintable():
            self._begin_edit()
        super().keyPressEvent(event)

    def keyReleaseEvent(self, event: QKeyEvent) -> None:
        super().keyReleaseEvent(event)
        if event.key() in {Qt.Key.Key_Up, Qt.Key.Key_Down}:
            self._finish_edit()

    def wheelEvent(self, event: QWheelEvent) -> None:
        self._begin_edit()
        super().wheelEvent(event)
        self._finish_edit()


class SimpleMaterialPanel(QWidget):
    """Friendly channel selection and controls backed by the active recipe."""

    channelSelected = Signal(str)
    sourceSelected = Signal(str)
    controlParameterChanged = Signal(str, str, str, object)
    controlEditStarted = Signal()
    controlEditFinished = Signal()
    operationAdded = Signal(str)

    CHANNELS = (
        ("base_color", "Color"),
        ("normal", "Surface Detail"),
        ("roughness", "Roughness"),
        ("metallic", "Metalness"),
    )
    SCALE_PARAMETERS = ("scale", "density", "frequency", "rings", "threads_x", "cells_x")

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("simple-material-panel")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.channel_widget = QWidget(self)
        channel_layout = QVBoxLayout(self.channel_widget)
        channel_layout.setContentsMargins(0, 0, 0, 0)
        channel_layout.addWidget(QLabel("MATERIAL PROPERTIES"))
        self._channel_group = QButtonGroup(self)
        self._channel_group.setExclusive(True)
        self.channel_buttons: dict[str, QPushButton] = {}
        grid = QGridLayout()
        for index, (semantic, label) in enumerate(self.CHANNELS):
            button = QPushButton(label, self.channel_widget)
            button.setCheckable(True)
            button.setObjectName(f"simple-channel-{semantic}")
            button.setToolTip(f"Select the {label.lower()} output and its editable layers.")
            self._channel_group.addButton(button)
            self.channel_buttons[semantic] = button
            grid.addWidget(button, index // 2, index % 2)
            button.clicked.connect(
                lambda _checked=False, key=semantic: self.channelSelected.emit(key)
            )
        channel_layout.addLayout(grid)
        self.add_operation_button = QToolButton(self.channel_widget)
        self.add_operation_button.setObjectName("simple-add-operation")
        self.add_operation_button.setText("Add operation")
        self.add_operation_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        self.add_operation_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.add_operation_menu = QMenu(self.add_operation_button)
        for label, key in (
            ("Gradient", "gradient"),
            ("Solid Color", "solid_color"),
            ("Noise / Pattern", "pattern"),
            ("Image", "image"),
        ):
            action = self.add_operation_menu.addAction(label)
            action.setData(key)
            action.triggered.connect(
                lambda _checked=False, operation=key: self.operationAdded.emit(operation)
            )
        self.add_operation_button.setMenu(self.add_operation_menu)
        channel_layout.addWidget(self.add_operation_button)
        self.source_selector = QComboBox(self.channel_widget)
        self.source_selector.setObjectName("simple-source-selector")
        common_source_ids = {
            "generator.seamless_value_noise",
            "generator.seamless_fractal_noise",
            "generator.seamless_turbulence",
            "generator.seamless_cellular",
            "generator.checker_grid",
            "generator.constant",
            "generator.image",
        }
        generators = sorted(
            (
                definition
                for definition in REGISTRY.definitions.values()
                if definition.operation_type == OperationType.GENERATOR
                and definition.identifier in common_source_ids
            ),
            key=lambda definition: (definition.category, definition.name),
        )
        for definition in generators:
            self.source_selector.addItem(definition.name, definition.identifier)
        self.source_selector.currentIndexChanged.connect(
            lambda index: (
                self.sourceSelected.emit(str(self.source_selector.itemData(index)))
                if index >= 0
                else None
            )
        )
        channel_layout.addWidget(QLabel("Source"))
        channel_layout.addWidget(self.source_selector)
        self.source_label = channel_layout.itemAt(channel_layout.count() - 1).widget()

        self.controls_widget = QWidget(self)
        controls_layout = QVBoxLayout(self.controls_widget)
        controls_layout.setContentsMargins(0, 0, 0, 0)
        self.guidance = QLabel(
            "Choose a material property, add a layer, and edit the selected layer. "
            "The canvas and material preview update as you work."
        )
        self.guidance.setWordWrap(True)
        self.guidance.setObjectName("simple-material-guidance")
        controls_layout.addWidget(self.guidance)
        controls_layout.addWidget(QLabel("MATERIAL CONTROLS"))
        self.tileability = QLabel("Tileability: Unknown", self.controls_widget)
        self.tileability.setObjectName("simple-tileability-status")
        self.tileability.setToolTip(
            "Measured across the rendered image borders. This predicts edge continuity when tiled."
        )
        controls_layout.addWidget(self.tileability)
        self.control_form = QFormLayout()
        controls_layout.addLayout(self.control_form)
        self.control_spins: dict[str, NumericControl] = {}
        self.control_targets: dict[str, tuple[str, str]] = {}
        self._control_parameter_ids: dict[str, str] = {}
        self._control_labels: dict[str, QLabel] = {}
        controls_layout.addStretch(1)
        layout.addWidget(self.channel_widget)
        layout.addWidget(self.controls_widget)
        self.setMinimumWidth(270)
        self.set_simple_mode(True)

    def set_simple_mode(self, simple: bool) -> None:
        # Operation discovery now lives in the visual browser. This legacy menu
        # remains available to Advanced Editor integrations only.
        self.add_operation_button.setVisible(not simple)
        self.source_selector.setVisible(not simple)
        self.source_label.setVisible(not simple)
        self.tileability.setVisible(not simple)
        self.controls_widget.setVisible(simple)
        if self.controls_widget.layout() is not None:
            for index in range(self.controls_widget.layout().count()):
                item = self.controls_widget.layout().itemAt(index)
                widget = item.widget() if item else None
                if isinstance(widget, QLabel) and widget.text() == "STARTER CONTROLS":
                    widget.setVisible(not simple)

    def set_recipe(
        self,
        recipe: ProjectRecipe,
        selected_output_id: str | None,
        source_operation_id: str | None = None,
    ) -> None:
        selected_output = next(
            (output for output in recipe.outputs if output.output_id == selected_output_id), None
        )
        for semantic, label in self.CHANNELS:
            outputs = self.outputs_for_semantic(recipe, semantic)
            button = self.channel_buttons[semantic]
            button.setEnabled(bool(outputs))
            button.setToolTip(
                f"Select the {label.lower()} output and its editable layers."
                if outputs
                else f"This material has no {label.lower()} output."
            )
            button.setChecked(selected_output is not None and selected_output.semantic == semantic)

        self.source_selector.blockSignals(True)
        source_index = self.source_selector.findData(source_operation_id)
        if source_index < 0 and source_operation_id:
            try:
                source_name = REGISTRY.get(source_operation_id).name
            except KeyError:
                source_name = "Current source"
            self.source_selector.insertItem(0, f"Current: {source_name}", source_operation_id)
            source_index = 0
        if source_index >= 0:
            self.source_selector.setCurrentIndex(source_index)
            self.source_selector.setToolTip(REGISTRY.get(str(source_operation_id)).name)
        self.source_selector.blockSignals(False)

        controls: dict[str, tuple[object, str, str, float]] = {}
        for control_name, control in recipe.control_fields.items():
            source = control.source
            definition = REGISTRY.get(source.operation_id)
            spec = next(
                (
                    item
                    for identifier in self.SCALE_PARAMETERS
                    if (
                        item := next(
                            (
                                candidate
                                for candidate in definition.parameter_specs
                                if candidate.identifier == identifier
                            ),
                            None,
                        )
                    )
                    is not None
                    and item.type in {ParameterType.FLOAT, ParameterType.INTEGER}
                    and isinstance(
                        source.parameters.get(item.identifier, item.default), (int, float)
                    )
                ),
                None,
            )
            if spec is None:
                continue
            parameter_id = spec.identifier
            label = "Pattern Scale" if control_name == "Scale" else control_name
            controls[control_name] = (
                spec,
                source.instance_id,
                parameter_id,
                float(source.parameters.get(parameter_id, spec.default)),
            )

        # Recipe commits happen synchronously inside valueChanged. Keep the active
        # input widget alive while its own mouse/key event unwinds; reconcile rows
        # by control and parameter identity instead of clearing the form each time.
        structure_changed = (
            set(controls) != set(self.control_spins)
            or any(
                self._control_parameter_ids.get(name) != control[2]
                for name, control in controls.items()
            )
            or any(self.control_spins.get(name) is None for name in controls)
        )
        if structure_changed:
            while self.control_form.rowCount():
                self.control_form.takeRow(0)

        previous_focus = QApplication.focusWidget()
        retired_widgets: list[QWidget] = []
        for control_name, (spec, instance_id, parameter_id, value) in controls.items():
            spin = self.control_spins.get(control_name)
            if spin is None or self._control_parameter_ids.get(control_name) != parameter_id:
                if spin is not None:
                    retired_widgets.extend((spin, self._control_labels.pop(control_name)))
                spin = NumericControl(
                    float(value),
                    minimum=float(spec.min_value if spec.min_value is not None else -1_000_000),
                    maximum=float(spec.max_value if spec.max_value is not None else 1_000_000),
                    step=float(
                        spec.step
                        if spec.step is not None
                        else 1
                        if spec.type == ParameterType.INTEGER
                        else 0.1
                    ),
                    decimals=0 if spec.type == ParameterType.INTEGER else 3,
                    parent=self,
                )
                spin.setObjectName(f"simple-control-{control_name.casefold().replace(' ', '-')}")
                spin.valueChanged.connect(
                    lambda changed, key=control_name: self._control_changed(key, changed)
                )
                spin.editStarted.connect(self.controlEditStarted)
                spin.editFinished.connect(self.controlEditFinished)
                self.control_spins[control_name] = spin
                self._control_parameter_ids[control_name] = parameter_id
                self._control_labels[control_name] = QLabel(
                    "Pattern Scale" if control_name == "Scale" else control_name, self
                )
                structure_changed = True
            blocked = spin.blockSignals(True)
            spin.setValue(value)
            spin.blockSignals(blocked)
            self.control_targets[control_name] = (instance_id, parameter_id)

        removed_names = set(self.control_spins) - set(controls)
        for name in removed_names:
            retired_widgets.extend((self.control_spins.pop(name), self._control_labels.pop(name)))
            self.control_targets.pop(name, None)
            self._control_parameter_ids.pop(name, None)

        for widget in retired_widgets:
            widget.deleteLater()

        if structure_changed:
            for control_name in controls:
                self.control_form.addRow(
                    self._control_labels[control_name], self.control_spins[control_name]
                )
        if previous_focus in self.control_spins.values():
            previous_focus.setFocus(Qt.FocusReason.OtherFocusReason)

    def set_tileability(self, status: str, explanation: str) -> None:
        label = "Tileable" if status in {"Yes", "No"} else "Tileability"
        self.tileability.setText(f"{label}: {status}")
        self.tileability.setToolTip(explanation)

    @classmethod
    def outputs_for_semantic(cls, recipe: ProjectRecipe, semantic: str):
        output_semantic = (
            "height"
            if semantic == "normal"
            and not any(output.semantic == "normal" for output in recipe.outputs)
            else semantic
        )
        return [output for output in recipe.outputs if output.semantic == output_semantic]

    def _control_changed(self, control_name: str, value: float) -> None:
        target = self.control_targets.get(control_name)
        if target is not None:
            instance_id, parameter_id = target
            self.controlParameterChanged.emit(control_name, instance_id, parameter_id, value)
