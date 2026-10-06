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
from archetexture.core.recipe import ProjectRecipe
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
        self.setMinimumWidth(220)
        layout = QVBoxLayout(self)

        layout.addWidget(QLabel("SOURCE"))
        self.source_selector = QComboBox()
        self._generators = [
            definition
            for definition in REGISTRY.definitions.values()
            if definition.operation_type == OperationType.GENERATOR
        ]
        for definition in self._generators:
            self.source_selector.addItem(definition.name, definition.identifier)
        self.source_selector.currentIndexChanged.connect(self._source_selected)
        layout.addWidget(self.source_selector)

        layout.addWidget(QLabel("TRANSFORMS"))
        self.transform_list = QListWidget()
        self.transform_list.currentItemChanged.connect(self._item_selected)
        self.transform_list.itemChanged.connect(self._item_changed)
        layout.addWidget(self.transform_list, 1)

        self.transform_selector = QComboBox()
        self._transforms = [
            definition
            for definition in REGISTRY.definitions.values()
            if definition.operation_type == OperationType.TRANSFORM
        ]
        for definition in self._transforms:
            self.transform_selector.addItem(definition.name, definition.identifier)
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

    def set_recipe(self, recipe: ProjectRecipe, selected_instance_id: str | None = None) -> None:
        self._syncing = True
        self.source_selector.blockSignals(True)
        self.transform_list.blockSignals(True)
        if recipe.source is not None:
            source_index = self.source_selector.findData(recipe.source.operation_id)
            self.source_selector.setCurrentIndex(source_index)
        self.transform_list.clear()
        for instance in recipe.transforms:
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
        self._update_buttons()
        self.output_description.setText(
            "Scalar → Color Ramp → RGBA"
            if recipe.color_ramp is not None
            else "Scalar → Grayscale RGBA"
        )

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
        self.remove_button.setEnabled(has_selection)
        self.up_button.setEnabled(row > 0)
        self.down_button.setEnabled(has_selection and row < self.transform_list.count() - 1)
