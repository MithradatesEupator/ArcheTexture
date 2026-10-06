from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from archetexture.core.operations import OperationType
from archetexture.core.pipeline_types import (
    compatible_append_transforms,
    pipeline_output_type,
    valid_transform_chain,
)
from archetexture.core.recipe import LayerRecipe, ProjectRecipe
from archetexture.core.registry import REGISTRY


class PipelinePanel(QWidget):
    sourceChanged = Signal(str)
    transformAdded = Signal(str)
    transformRemoved = Signal(str)
    transformMoved = Signal(str, int)
    transformEnabled = Signal(str, bool)
    selectionChanged = Signal(str)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._syncing = False
        self._layer: LayerRecipe | None = None
        self.setMinimumWidth(220)
        layout = QVBoxLayout(self)

        layout.addWidget(QLabel("SOURCE"))
        self.source_selector = QComboBox()
        self._generators = [
            definition
            for definition in REGISTRY.definitions.values()
            if definition.operation_type == OperationType.GENERATOR
        ]
        self._generators.sort(key=lambda definition: (definition.category, definition.name))
        for definition in self._generators:
            self.source_selector.addItem(
                f"{definition.category} / {definition.name}", definition.identifier
            )
        self.source_selector.currentIndexChanged.connect(self._source_selected)
        layout.addWidget(self.source_selector)

        layout.addWidget(QLabel("TRANSFORMS"))
        self.transform_list = QListWidget()
        self.transform_list.currentItemChanged.connect(self._item_selected)
        self.transform_list.itemChanged.connect(self._item_changed)
        layout.addWidget(self.transform_list, 1)

        self.transform_selector = QComboBox()
        layout.addWidget(self.transform_selector)

        controls = QHBoxLayout()
        self.add_button = QPushButton("Add")
        self.remove_button = QPushButton("Remove")
        controls.addWidget(self.add_button)
        controls.addWidget(self.remove_button)
        layout.addLayout(controls)

        order = QHBoxLayout()
        self.up_button = QPushButton("Move up")
        self.down_button = QPushButton("Move down")
        order.addWidget(self.up_button)
        order.addWidget(self.down_button)
        layout.addLayout(order)

        self.add_button.clicked.connect(self._add_selected)
        self.remove_button.clicked.connect(self._remove_selected)
        self.up_button.clicked.connect(lambda: self._move_selected(-1))
        self.down_button.clicked.connect(lambda: self._move_selected(1))
        layout.addWidget(QLabel("COLOR / OUTPUT"))
        self.output_description = QLabel("Linear float fields · RGBA display")
        self.output_description.setWordWrap(True)
        layout.addWidget(self.output_description)

    def set_recipe(
        self,
        recipe: ProjectRecipe,
        selected_instance_id: str | None = None,
        layer: LayerRecipe | None = None,
    ) -> None:
        layer = layer or (recipe.layers[0] if recipe.layers else None)
        self._syncing = True
        self._layer = layer
        self.source_selector.blockSignals(True)
        self.transform_list.blockSignals(True)
        if layer is not None and layer.source is not None:
            source_index = self.source_selector.findData(layer.source.operation_id)
            self.source_selector.setCurrentIndex(source_index)
        self.transform_list.clear()
        for instance in layer.transforms if layer is not None else ():
            definition = REGISTRY.get(instance.operation_id)
            item = QListWidgetItem(definition.name)
            item.setData(Qt.ItemDataRole.UserRole, instance.instance_id)
            item.setFlags(
                item.flags()
                | Qt.ItemFlag.ItemIsEnabled
                | Qt.ItemFlag.ItemIsSelectable
                | Qt.ItemFlag.ItemIsUserCheckable
            )
            item.setCheckState(
                Qt.CheckState.Checked if instance.enabled else Qt.CheckState.Unchecked
            )
            self.transform_list.addItem(item)
        selected_item = None
        if selected_instance_id:
            selected_item = self._find_item(selected_instance_id)
        if selected_item is not None:
            self.transform_list.setCurrentItem(selected_item)
        self.source_selector.blockSignals(False)
        self.transform_list.blockSignals(False)
        self._syncing = False
        self._refresh_transform_choices(layer)
        self._update_buttons()
        self.output_description.setText(self._describe_output(layer))

    def _refresh_transform_choices(self, layer: LayerRecipe | None) -> None:
        previous = self.transform_selector.currentData()
        self.transform_selector.blockSignals(True)
        self.transform_selector.clear()
        compatible = (
            compatible_append_transforms(
                layer.source,
                layer.transforms,
                color_ramp_active=layer.color_ramp is not None,
            )
            if layer is not None and layer.source is not None
            else ()
        )
        for definition in sorted(compatible, key=lambda item: (item.category, item.name)):
            self.transform_selector.addItem(
                f"{definition.category} / {definition.name}", definition.identifier
            )
        if previous is not None:
            index = self.transform_selector.findData(previous)
            if index >= 0:
                self.transform_selector.setCurrentIndex(index)
        if not compatible:
            self.transform_selector.addItem("No compatible transforms", None)
            self.transform_selector.setEnabled(False)
            self.add_button.setEnabled(False)
        else:
            self.transform_selector.setEnabled(True)
            self.add_button.setEnabled(True)
        self.transform_selector.blockSignals(False)

    @staticmethod
    def _describe_output(layer: LayerRecipe | None) -> str:
        if layer is None or layer.source is None:
            return "No pipeline output"
        stages = [REGISTRY.get(layer.source.operation_id).output_type.capitalize()]
        for instance in layer.transforms:
            if instance.enabled:
                stages.append(REGISTRY.get(instance.operation_id).name)
        output_type = pipeline_output_type(layer.source, layer.transforms)
        if layer.color_ramp is not None:
            return " → ".join((stages[0], "Color Ramp", "RGBA"))
        elif output_type == "rgba":
            stages.append("RGBA")
        else:
            return f"{stages[0]} → Grayscale RGBA"
        return " → ".join(stages)

    def _find_item(self, instance_id: str) -> QListWidgetItem | None:
        for index in range(self.transform_list.count()):
            item = self.transform_list.item(index)
            if item.data(Qt.ItemDataRole.UserRole) == instance_id:
                return item
        return None

    def _selected_instance_id(self) -> str | None:
        item = self.transform_list.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item is not None else None

    def _source_selected(self, index: int) -> None:
        if not self._syncing and index >= 0:
            self.sourceChanged.emit(str(self.source_selector.itemData(index)))

    def _item_selected(self, current: QListWidgetItem | None, _previous) -> None:
        if not self._syncing and current is not None:
            self.selectionChanged.emit(str(current.data(Qt.ItemDataRole.UserRole)))
        self._update_buttons()

    def _item_changed(self, item: QListWidgetItem) -> None:
        if not self._syncing:
            self.transformEnabled.emit(
                str(item.data(Qt.ItemDataRole.UserRole)),
                item.checkState() == Qt.CheckState.Checked,
            )

    def _add_selected(self) -> None:
        operation_id = self.transform_selector.currentData()
        if operation_id:
            self.transformAdded.emit(str(operation_id))

    def _remove_selected(self) -> None:
        instance_id = self._selected_instance_id()
        if instance_id is not None:
            self.transformRemoved.emit(instance_id)

    def _move_selected(self, offset: int) -> None:
        instance_id = self._selected_instance_id()
        row = self.transform_list.currentRow()
        target = row + offset
        if instance_id is not None and 0 <= target < self.transform_list.count():
            self.transformMoved.emit(instance_id, target)

    def _update_buttons(self) -> None:
        row = self.transform_list.currentRow()
        has_selection = row >= 0
        self.up_button.setEnabled(row > 0 and self._can_move(row, row - 1))
        self.down_button.setEnabled(
            has_selection and row < self.transform_list.count() - 1 and self._can_move(row, row + 1)
        )
        self.remove_button.setEnabled(has_selection)

    def _can_move(self, row: int, target: int) -> bool:
        if (
            self._layer is None
            or self._layer.source is None
            or not 0 <= row < len(self._layer.transforms)
        ):
            return False
        transforms = list(self._layer.transforms)
        item = transforms.pop(row)
        transforms.insert(target, item)
        return valid_transform_chain(
            self._layer.source,
            transforms,
            color_ramp_active=self._layer.color_ramp is not None,
        )
