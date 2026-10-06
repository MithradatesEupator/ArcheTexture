from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from archetexture.core.operations import OperationDefinition, OperationType
from archetexture.core.parameters import ControlFieldMapping
from archetexture.core.recipe import ControlFieldRecipe, ProjectRecipe
from archetexture.core.registry import REGISTRY
from archetexture.ui.property_editor import PropertyEditor


class ControlFieldsEditor(QWidget):
    createRequested = Signal()
    renameRequested = Signal(str, str)
    removeRequested = Signal(str)
    fieldSelected = Signal(str)
    sourceChanged = Signal(str, str)
    transformAdded = Signal(str, str)
    transformRemoved = Signal(str, str)
    transformMoved = Signal(str, str, int)
    transformEnabled = Signal(str, str, bool)
    valueChanged = Signal(str, object, object)
    bindingRequested = Signal(str, object, object, object)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._recipe = ProjectRecipe()
        self._selected_id: str | None = None
        self._selected_operation_id: str | None = None
        self._syncing = False
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.addWidget(QLabel("Reusable scalar recipes can modulate numeric parameters."))

        self.fields_list = QListWidget(self)
        self.fields_list.setObjectName("control-fields-list")
        self.fields_list.currentItemChanged.connect(self._field_selected)
        layout.addWidget(self.fields_list, 1)
        management = QHBoxLayout()
        self.create_button = QPushButton("Create")
        self.create_button.setObjectName("create-control-field")
        self.name_input = QLineEdit(self)
        self.name_input.setObjectName("control-field-name")
        self.name_input.setPlaceholderText("control identifier")
        self.rename_button = QPushButton("Rename")
        self.remove_field_button = QPushButton("Remove")
        management.addWidget(self.create_button)
        management.addWidget(self.name_input, 1)
        management.addWidget(self.rename_button)
        management.addWidget(self.remove_field_button)
        layout.addLayout(management)
        self.create_button.clicked.connect(self.createRequested.emit)
        self.rename_button.clicked.connect(self._rename)
        self.remove_field_button.clicked.connect(self._remove)

        self.details = QWidget(self)
        detail_layout = QVBoxLayout(self.details)
        detail_layout.setContentsMargins(0, 0, 0, 0)
        self.source_combo = QComboBox(self.details)
        self.source_combo.setObjectName("control-source")
        self._generators = self._compatible_generators()
        for definition in self._generators:
            self.source_combo.addItem(definition.name, definition.identifier)
        self.source_combo.currentIndexChanged.connect(self._source_selected)
        source_form = QFormLayout()
        source_form.addRow("Scalar source", self.source_combo)
        detail_layout.addLayout(source_form)
        self.edit_source_button = QPushButton("Edit source parameters", self.details)
        self.edit_source_button.clicked.connect(self._select_source)
        detail_layout.addWidget(self.edit_source_button)

        self.transform_list = QListWidget(self.details)
        self.transform_list.setObjectName("control-transform-list")
        self.transform_list.currentItemChanged.connect(self._transform_selected)
        self.transform_list.itemChanged.connect(self._transform_toggled)
        detail_layout.addWidget(self.transform_list, 1)
        chain_add = QHBoxLayout()
        self.transform_combo = QComboBox(self.details)
        self.transform_combo.setObjectName("control-transform-type")
        self._transforms = self._compatible_transforms()
        for definition in self._transforms:
            self.transform_combo.addItem(definition.name, definition.identifier)
        self.add_transform_button = QPushButton("Add transform")
        self.remove_transform_button = QPushButton("Remove")
        chain_add.addWidget(self.transform_combo, 1)
        chain_add.addWidget(self.add_transform_button)
        chain_add.addWidget(self.remove_transform_button)
        detail_layout.addLayout(chain_add)
        chain_order = QHBoxLayout()
        self.move_up_button = QPushButton("Move up")
        self.move_down_button = QPushButton("Move down")
        chain_order.addWidget(self.move_up_button)
        chain_order.addWidget(self.move_down_button)
        detail_layout.addLayout(chain_order)
        self.add_transform_button.clicked.connect(self._add_transform)
        self.remove_transform_button.clicked.connect(self._remove_transform)
        self.move_up_button.clicked.connect(lambda: self._move_transform(-1))
        self.move_down_button.clicked.connect(lambda: self._move_transform(1))

        self.mapping_enabled = QCheckBox("Apply global mapping", self.details)
        self.mapping_enabled.setObjectName("control-global-mapping-enabled")
        self.mapping_min = QDoubleSpinBox(self.details)
        self.mapping_min.setObjectName("control-global-mapping-min")
        self.mapping_max = QDoubleSpinBox(self.details)
        self.mapping_max.setObjectName("control-global-mapping-max")
        for spin in (self.mapping_min, self.mapping_max):
            spin.setRange(0.0, 1.0)
            spin.setDecimals(3)
            spin.setSingleStep(0.01)
        self.mapping_invert = QCheckBox("Invert", self.details)
        self.mapping_curve = QComboBox(self.details)
        self.mapping_curve.setObjectName("control-global-mapping-curve")
        self.mapping_curve.addItems(("linear", "smoothstep", "stepped"))
        self.mapping_quantize = QDoubleSpinBox(self.details)
        self.mapping_quantize.setObjectName("control-global-mapping-quantize")
        self.mapping_quantize.setRange(0, 256)
        self.mapping_quantize.setDecimals(1)
        self.mapping_quantize.setToolTip("0 disables quantization")
        mapping_form = QFormLayout()
        mapping_form.addRow(self.mapping_enabled)
        mapping_form.addRow("Output minimum", self.mapping_min)
        mapping_form.addRow("Output maximum", self.mapping_max)
        mapping_form.addRow(self.mapping_invert)
        mapping_form.addRow("Curve", self.mapping_curve)
        mapping_form.addRow("Quantize levels (0 = off)", self.mapping_quantize)
        detail_layout.addLayout(mapping_form)
        self.property_editor = PropertyEditor(self.details)
        self.property_editor.setObjectName("control-operation-properties")
        self.property_editor.valueChanged.connect(self._operation_value_changed)
        self.property_editor.bindingRequested.connect(self._operation_binding_requested)
        detail_layout.addWidget(self.property_editor, 2)

        self.mapping_enabled.toggled.connect(self._mapping_toggled)
        self.mapping_invert.toggled.connect(self._mapping_changed)
        for widget in (self.mapping_min, self.mapping_max, self.mapping_quantize):
            widget.valueChanged.connect(self._mapping_changed)
        self.mapping_curve.currentTextChanged.connect(self._mapping_changed)
        layout.addWidget(self.details, 3)
        self.setMinimumWidth(280)

    @staticmethod
    def _compatible_generators() -> list[OperationDefinition]:
        return [
            definition
            for definition in REGISTRY.definitions.values()
            if definition.operation_type == OperationType.GENERATOR
            and definition.output_type == "scalar"
        ]

    @staticmethod
    def _compatible_transforms() -> list[OperationDefinition]:
        return [
            definition
            for definition in REGISTRY.definitions.values()
            if definition.operation_type == OperationType.TRANSFORM
            and definition.output_type == "scalar"
            and ("scalar" in definition.input_types or "any" in definition.input_types)
        ]

    @property
    def selected_field_id(self) -> str | None:
        return self._selected_id

    def set_recipe(self, recipe: ProjectRecipe, selected_id: str | None = None) -> None:
        previous_field = self._selected_id
        previous_operation = self._selected_operation_id
        self._recipe = recipe
        if selected_id is not None:
            self._selected_id = selected_id
        if self._selected_id != previous_field:
            self._selected_operation_id = None
        else:
            self._selected_operation_id = previous_operation
        if self._selected_id not in recipe.control_fields:
            self._selected_id = next(iter(recipe.control_fields), None)
        self._syncing = True
        self.fields_list.blockSignals(True)
        self.fields_list.clear()
        for identifier in recipe.control_fields:
            item = QListWidgetItem(identifier)
            item.setData(Qt.ItemDataRole.UserRole, identifier)
            self.fields_list.addItem(item)
            if identifier == self._selected_id:
                self.fields_list.setCurrentItem(item)
        self.fields_list.blockSignals(False)
        self._syncing = False
        self._load_selected()

    def select_field(self, identifier: str) -> None:
        for row in range(self.fields_list.count()):
            item = self.fields_list.item(row)
            if item.data(Qt.ItemDataRole.UserRole) == identifier:
                self.fields_list.setCurrentItem(item)
                return

    def select_operation(self, instance_id: str | None) -> None:
        self._selected_operation_id = instance_id

    def _field_selected(self, current, _previous) -> None:
        if self._syncing or current is None:
            return
        self._selected_id = str(current.data(Qt.ItemDataRole.UserRole))
        self._selected_operation_id = None
        self._load_selected()
        self.fieldSelected.emit(self._selected_id)

    def _load_selected(self) -> None:
        self._syncing = True
        identifier = self._selected_id
        control = self._recipe.control_fields.get(identifier) if identifier else None
        enabled = control is not None
        self.details.setEnabled(enabled)
        self.rename_button.setEnabled(enabled)
        self.remove_field_button.setEnabled(enabled)
        self.name_input.setText(identifier or "")
        if control is None:
            self.transform_list.clear()
            self.property_editor.set_operation(None, None)
            self.property_editor.set_control_fields(self._recipe.control_fields)
            self.mapping_enabled.setChecked(False)
            self.mapping_min.setValue(0.0)
            self.mapping_max.setValue(1.0)
            self._update_chain_buttons()
            self._syncing = False
            return
        self.source_combo.blockSignals(True)
        source_index = self.source_combo.findData(control.source.operation_id)
        if source_index >= 0:
            self.source_combo.setCurrentIndex(source_index)
        self.source_combo.blockSignals(False)
        self.transform_list.blockSignals(True)
        self.transform_list.clear()
        for instance in control.transforms:
            definition = REGISTRY.get(instance.operation_id)
            item = QListWidgetItem(definition.name)
            item.setData(Qt.ItemDataRole.UserRole, instance.instance_id)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(
                Qt.CheckState.Checked if instance.enabled else Qt.CheckState.Unchecked
            )
            self.transform_list.addItem(item)
        selected_row = next(
            (
                row
                for row in range(self.transform_list.count())
                if self.transform_list.item(row).data(Qt.ItemDataRole.UserRole)
                == self._selected_operation_id
            ),
            -1,
        )
        self.transform_list.setCurrentRow(selected_row)
        self.transform_list.blockSignals(False)
        mapping = control.mapping
        self.mapping_enabled.blockSignals(True)
        self.mapping_enabled.setChecked(mapping is not None)
        self.mapping_enabled.blockSignals(False)
        mapping = mapping or ControlFieldMapping()
        self.mapping_min.setValue(mapping.output_min)
        self.mapping_max.setValue(mapping.output_max)
        self.mapping_invert.setChecked(mapping.invert)
        self.mapping_curve.setCurrentText(mapping.curve)
        self.mapping_quantize.setValue(mapping.quantize or 0.0)
        self.property_editor.set_control_fields(self._recipe.control_fields)
        self._refresh_operation(control)
        for widget in (
            self.mapping_min,
            self.mapping_max,
            self.mapping_invert,
            self.mapping_curve,
            self.mapping_quantize,
        ):
            widget.setEnabled(control.mapping is not None)
        self._syncing = False
        self._update_chain_buttons()

    def _refresh_operation(self, control: ControlFieldRecipe) -> None:
        selected = self.transform_list.currentItem()
        instance_id = selected.data(Qt.ItemDataRole.UserRole) if selected else None
        self._selected_operation_id = instance_id
        instance = (
            control.source
            if instance_id is None
            else next(
                (item for item in control.transforms if item.instance_id == instance_id), None
            )
        )
        definition = REGISTRY.get(instance.operation_id) if instance else None
        self.property_editor.set_operation(instance, definition)

    def _rename(self) -> None:
        if self._selected_id is not None:
            self.renameRequested.emit(self._selected_id, self.name_input.text().strip())

    def _remove(self) -> None:
        if self._selected_id is not None:
            self.removeRequested.emit(self._selected_id)

    def _source_selected(self, index: int) -> None:
        if not self._syncing and self._selected_id and index >= 0:
            self.sourceChanged.emit(self._selected_id, str(self.source_combo.itemData(index)))

    def _add_transform(self) -> None:
        operation_id = self.transform_combo.currentData()
        if self._selected_id and operation_id:
            self.transformAdded.emit(self._selected_id, str(operation_id))

    def _current_transform_id(self) -> str | None:
        item = self.transform_list.currentItem()
        return str(item.data(Qt.ItemDataRole.UserRole)) if item is not None else None

    def _remove_transform(self) -> None:
        identifier = self._current_transform_id()
        if self._selected_id and identifier:
            self.transformRemoved.emit(self._selected_id, identifier)

    def _move_transform(self, offset: int) -> None:
        identifier = self._current_transform_id()
        row = self.transform_list.currentRow()
        target = row + offset
        if self._selected_id and identifier and 0 <= target < self.transform_list.count():
            self.transformMoved.emit(self._selected_id, identifier, target)

    def _transform_selected(self, _current, _previous) -> None:
        if not self._syncing and self._selected_id:
            self._selected_operation_id = self._current_transform_id()
            control = self._recipe.control_fields.get(self._selected_id)
            if control is not None:
                self._refresh_operation(control)
        self._update_chain_buttons()

    def _select_source(self) -> None:
        self.transform_list.blockSignals(True)
        self.transform_list.setCurrentRow(-1)
        self.transform_list.blockSignals(False)
        self._selected_operation_id = None
        if self._selected_id:
            control = self._recipe.control_fields.get(self._selected_id)
            if control is not None:
                self._refresh_operation(control)
        self._update_chain_buttons()

    def _transform_toggled(self, item: QListWidgetItem) -> None:
        if not self._syncing and self._selected_id:
            self.transformEnabled.emit(
                self._selected_id,
                str(item.data(Qt.ItemDataRole.UserRole)),
                item.checkState() == Qt.CheckState.Checked,
            )

    def _update_chain_buttons(self) -> None:
        row = self.transform_list.currentRow()
        self.remove_transform_button.setEnabled(row >= 0)
        self.move_up_button.setEnabled(row > 0)
        self.move_down_button.setEnabled(row >= 0 and row < self.transform_list.count() - 1)

    def _mapping_changed(self, *_args) -> None:
        if self._syncing or self._selected_id is None:
            return
        mapping = None
        if self.mapping_enabled.isChecked():
            mapping = ControlFieldMapping(
                output_min=self.mapping_min.value(),
                output_max=self.mapping_max.value(),
                invert=self.mapping_invert.isChecked(),
                curve=self.mapping_curve.currentText(),
                quantize=self.mapping_quantize.value() or None,
            )
        self.valueChanged.emit(self._selected_id, "mapping", mapping)

    def _mapping_toggled(self, enabled: bool) -> None:
        for widget in (
            self.mapping_min,
            self.mapping_max,
            self.mapping_invert,
            self.mapping_curve,
            self.mapping_quantize,
        ):
            widget.setEnabled(enabled)
        self._mapping_changed()

    def _operation_value_changed(self, key: str, value) -> None:
        if self._selected_id:
            instance_id = self._current_transform_id()
            if instance_id is None:
                instance_id = self._recipe.control_fields[self._selected_id].source.instance_id
            self.valueChanged.emit(self._selected_id, (instance_id, key), value)

    def _operation_binding_requested(self, key: str, spec, binding) -> None:
        if self._selected_id:
            instance_id = self._current_transform_id()
            if instance_id is None:
                instance_id = self._recipe.control_fields[self._selected_id].source.instance_id
            self.bindingRequested.emit(self._selected_id, (instance_id, key), spec, binding)
