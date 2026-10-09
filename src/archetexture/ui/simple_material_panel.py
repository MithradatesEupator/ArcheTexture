from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from archetexture.core.parameters import ParameterType
from archetexture.core.recipe import ProjectRecipe
from archetexture.core.registry import REGISTRY


class SimpleMaterialPanel(QWidget):
    """Friendly channel selection and controls backed by the active recipe."""

    channelSelected = Signal(str)
    controlParameterChanged = Signal(str, str, str, object)

    CHANNELS = (
        ("base_color", "Color"),
        ("normal", "Surface Detail"),
        ("roughness", "Roughness"),
        ("metallic", "Metalness"),
    )
    SCALE_PARAMETERS = ("scale", "density", "frequency", "rings", "threads_x")

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("simple-material-panel")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.channel_widget = QWidget(self)
        channel_layout = QVBoxLayout(self.channel_widget)
        channel_layout.setContentsMargins(0, 0, 0, 0)
        channel_layout.addWidget(QLabel("MATERIAL PROPERTIES"))
        self._channel_group = QButtonGroup(self)
        self._channel_group.setExclusive(True)
        self.channel_buttons: dict[str, QPushButton] = {}
        for semantic, label in self.CHANNELS:
            button = QPushButton(label, self)
            button.setCheckable(True)
            button.setObjectName(f"simple-channel-{semantic}")
            button.setToolTip(f"Select the {label.lower()} output and its editable layers.")
            self._channel_group.addButton(button)
            self.channel_buttons[semantic] = button
            channel_layout.addWidget(button)
            button.clicked.connect(
                lambda _checked=False, key=semantic: self.channelSelected.emit(key)
            )

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
        self.control_form = QFormLayout()
        controls_layout.addLayout(self.control_form)
        self.control_spins: dict[str, QDoubleSpinBox] = {}
        self.control_targets: dict[str, tuple[str, str]] = {}
        controls_layout.addStretch(1)
        layout.addWidget(self.channel_widget)
        layout.addWidget(self.controls_widget)

    def set_recipe(self, recipe: ProjectRecipe, selected_output_id: str | None) -> None:
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
            spin.setSingleStep(float(spec.step if spec.step is not None else 0.1))
            parameter_id = spec.identifier
            spin.setValue(float(source.parameters.get(parameter_id, spec.default)))
            self.control_form.addRow(control_name, spin)
            self.control_spins[control_name] = spin
            self.control_targets[control_name] = (source.instance_id, parameter_id)
            spin.valueChanged.connect(
                lambda value, key=control_name: self._control_changed(key, value)
            )

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
