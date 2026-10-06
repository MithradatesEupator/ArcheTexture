from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from archetexture.core.recipe import ProjectRecipe


class _OpacitySpinBox(QDoubleSpinBox):
    def wheelEvent(self, event) -> None:
        if self.hasFocus():
            super().wheelEvent(event)
        else:
            event.ignore()


class LayersPanel(QWidget):
    addRequested = Signal()
    removeRequested = Signal(str)
    duplicateRequested = Signal(str)
    renameRequested = Signal(str, str)
    selectionChanged = Signal(str)
    enabledChanged = Signal(str, bool)
    moved = Signal(str, int)
    opacityChanged = Signal(str, float)
    blendModeChanged = Signal(str, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._syncing = False
        self._known: dict[str, tuple[str, bool]] = {}
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.addWidget(QLabel("LAYERS"))
        self.layer_list = QListWidget()
        self.layer_list.currentItemChanged.connect(self._selected)
        self.layer_list.itemChanged.connect(self._changed)
        layout.addWidget(self.layer_list, 1)
        row = QHBoxLayout()
        for label, slot in (("Add", self.addRequested.emit),):
            button = QPushButton(label)
            button.clicked.connect(slot)
            row.addWidget(button)
            if label == "Add":
                self.add_button = button
        self.duplicate_button = QPushButton("Duplicate")
        self.remove_button = QPushButton("Remove")
        row.addWidget(self.duplicate_button)
        row.addWidget(self.remove_button)
        layout.addLayout(row)
        order = QHBoxLayout()
        self.up_button = QPushButton("Move up")
        self.down_button = QPushButton("Move down")
        order.addWidget(self.up_button)
        order.addWidget(self.down_button)
        layout.addLayout(order)
        self.opacity = _OpacitySpinBox()
        self.opacity.setRange(0.0, 1.0)
        self.opacity.setDecimals(2)
        self.opacity.setSingleStep(0.01)
        self.opacity.setPrefix("Opacity ")
        layout.addWidget(self.opacity)
        self.blend = QComboBox()
        self.blend.addItem("Normal", "normal")
        self.blend.addItem("Multiply", "multiply")
        self.blend.addItem("Screen", "screen")
        self.blend.addItem("Add", "add")
        layout.addWidget(self.blend)
        self.duplicate_button.clicked.connect(self._duplicate)
        self.remove_button.clicked.connect(self._remove)
        self.up_button.clicked.connect(lambda: self._move(-1))
        self.down_button.clicked.connect(lambda: self._move(1))
        self.opacity.valueChanged.connect(self._opacity_changed)
        self.blend.currentIndexChanged.connect(self._blend_changed)
        self.setMinimumWidth(230)

    def set_recipe(self, recipe: ProjectRecipe, selected_id: str | None) -> None:
        self._syncing = True
        self.layer_list.blockSignals(True)
        self.layer_list.clear()
        self._known = {}
        selected = None
        for layer in recipe.layers:
            item = QListWidgetItem(layer.name)
            item.setData(Qt.ItemDataRole.UserRole, layer.layer_id)
            item.setFlags(
                item.flags() | Qt.ItemFlag.ItemIsEditable | Qt.ItemFlag.ItemIsUserCheckable
            )
            item.setCheckState(Qt.CheckState.Checked if layer.enabled else Qt.CheckState.Unchecked)
            self._known[layer.layer_id] = (layer.name, layer.enabled)
            self.layer_list.addItem(item)
            if layer.layer_id == selected_id:
                selected = item
        if selected:
            self.layer_list.setCurrentItem(selected)
        layer = next((item for item in recipe.layers if item.layer_id == selected_id), None)
        self.opacity.setEnabled(layer is not None)
        self.blend.setEnabled(layer is not None)
        if layer:
            self.opacity.setValue(layer.opacity)
            self.blend.setCurrentIndex(max(0, self.blend.findData(layer.blend_mode)))
        self.layer_list.blockSignals(False)
        self._syncing = False
        row = self.layer_list.currentRow()
        self.up_button.setEnabled(row > 0)
        self.down_button.setEnabled(row >= 0 and row < self.layer_list.count() - 1)
        self.remove_button.setEnabled(len(recipe.layers) > 1 and row >= 0)
        self.duplicate_button.setEnabled(row >= 0)

    def _selected_id(self) -> str | None:
        item = self.layer_list.currentItem()
        return str(item.data(Qt.ItemDataRole.UserRole)) if item else None

    def _selected(self, current, _previous) -> None:
        if not self._syncing and current:
            self.selectionChanged.emit(str(current.data(Qt.ItemDataRole.UserRole)))

    def _changed(self, item: QListWidgetItem) -> None:
        if self._syncing:
            return
        identifier = str(item.data(Qt.ItemDataRole.UserRole))
        old_name, old_enabled = self._known.get(identifier, ("", False))
        if item.text() and item.text() != old_name:
            self.renameRequested.emit(identifier, item.text())
        enabled = item.checkState() == Qt.CheckState.Checked
        if enabled != old_enabled:
            self.enabledChanged.emit(identifier, enabled)
        self._known[identifier] = (item.text(), enabled)

    def _duplicate(self) -> None:
        identifier = self._selected_id()
        if identifier:
            self.duplicateRequested.emit(identifier)

    def _remove(self) -> None:
        identifier = self._selected_id()
        if identifier:
            self.removeRequested.emit(identifier)

    def _move(self, delta: int) -> None:
        identifier = self._selected_id()
        target = self.layer_list.currentRow() + delta
        if identifier and 0 <= target < self.layer_list.count():
            self.moved.emit(identifier, target)

    def _opacity_changed(self, value: float) -> None:
        identifier = self._selected_id()
        if not self._syncing and identifier:
            self.opacityChanged.emit(identifier, value)

    def _blend_changed(self, _index: int) -> None:
        identifier = self._selected_id()
        if not self._syncing and identifier:
            self.blendModeChanged.emit(identifier, str(self.blend.currentData()))
