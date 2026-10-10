from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QGridLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from archetexture.core.operations import OperationType
from archetexture.core.parameters import ParameterType
from archetexture.core.recipe import ProjectRecipe
from archetexture.core.registry import REGISTRY


class SimpleMaterialPanel(QWidget):
    """Friendly channel selection and controls backed by the active recipe."""

    channelSelected = Signal(str)
    sourceSelected = Signal(str)
    controlParameterChanged = Signal(str, str, str, object)

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

        self.controls_widget = QWidget(self)
        controls_layout = QVBoxLayout(self.controls_widget)
        controls_layout.setContentsMargins(0, 0, 0, 0)
        self.guidance = QLabel(
            "Choose a material property. Select its layers on the left and edit their "
            "parameters above. Changes update the sphere automatically."
        )
        self.guidance.setWordWrap(True)
        self.guidance.setObjectName("simple-material-guidance")
        controls_layout.addWidget(self.guidance)
        controls_layout.addWidget(QLabel("STARTER CONTROLS"))
        self.tileability = QLabel("Tileability: Unknown", self.controls_widget)
        self.tileability.setObjectName("simple-tileability-status")
        self.tileability.setToolTip(
            "Measured across the rendered image borders. This predicts edge continuity when tiled."
        )
        controls_layout.addWidget(self.tileability)
        self.control_form = QFormLayout()
        controls_layout.addLayout(self.control_form)
        self.control_spins: dict[str, QDoubleSpinBox] = {}
        self.control_targets: dict[str, tuple[str, str]] = {}
        controls_layout.addStretch(1)
        layout.addWidget(self.channel_widget)
        layout.addWidget(self.controls_widget)
        self.setMinimumWidth(270)

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

        while self.control_form.rowCount():
            self.control_form.removeRow(0)
        self.control_spins.clear()
        self.control_targets.clear()
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
            spin = QDoubleSpinBox(self)
            spin.setObjectName(f"simple-control-{control_name.casefold().replace(' ', '-')}")
            spin.setRange(
                float(spec.min_value if spec.min_value is not None else -1_000_000),
                float(spec.max_value if spec.max_value is not None else 1_000_000),
            )
            spin.setDecimals(3 if spec.type == ParameterType.FLOAT else 0)
            spin.setSingleStep(
                float(
                    spec.step
                    if spec.step is not None
                    else 1
                    if spec.type == ParameterType.INTEGER
                    else 0.1
                )
            )
            parameter_id = spec.identifier
            spin.setValue(float(source.parameters.get(parameter_id, spec.default)))
            label = "Pattern Scale" if control_name == "Scale" else control_name
            self.control_form.addRow(label, spin)
            self.control_spins[control_name] = spin
            self.control_targets[control_name] = (source.instance_id, parameter_id)
            spin.valueChanged.connect(
                lambda value, key=control_name: self._control_changed(key, value)
            )

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
