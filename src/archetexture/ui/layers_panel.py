from __future__ import annotations

import copy

import numpy as np
from PySide6.QtCore import QObject, QRunnable, Qt, QThreadPool, Signal
from PySide6.QtGui import QIcon, QImage, QPixmap
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from archetexture.core.assets import RenderContext
from archetexture.core.fingerprinting import structural_fingerprint
from archetexture.core.recipe import ProjectRecipe
from archetexture.render.engine import RenderEngine
from archetexture.ui.numeric_control import NumericControl


class _LayerPreviewSignals(QObject):
    completed = Signal(str, str, object)


class _LayerPreviewTask(QRunnable):
    def __init__(self, layer_id, key, recipe, output_id, signals):
        super().__init__()
        self.layer_id, self.key, self.recipe = layer_id, key, recipe
        self.output_id, self.signals = output_id, signals

    def run(self) -> None:
        try:
            rgba = (
                RenderEngine()
                .render_output(self.recipe, self.output_id, width=64, height=48)
                .rgba_field
            )
            pixels = np.clip(rgba * 255.0 + 0.5, 0, 255).astype(np.uint8)
            self.signals.completed.emit(self.layer_id, self.key, pixels.tobytes())
        except Exception as exc:
            self.signals.completed.emit(self.layer_id, self.key, str(exc))


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
    maskChanged = Signal(str, object)
    maskEditRequested = Signal(str)
    addMaskRequested = Signal(str)
    addImageMaskRequested = Signal(str)
    maskNavigateRequested = Signal(str)
    copyToOutputRequested = Signal(str)
    moveToOutputRequested = Signal(str)
    createOutputRequested = Signal(str)
    opacityEditStarted = Signal()
    opacityEditFinished = Signal()
    thumbnailReady = Signal(str, object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._syncing = False
        self._known: dict[str, tuple[str, bool]] = {}
        self._thumbnail_signals = _LayerPreviewSignals(self)
        self._thumbnail_signals.completed.connect(self._thumbnail_ready)
        self._thumbnail_cache: dict[str, bytes] = {}
        self._thumbnail_pending: set[str] = set()
        self._current_thumbnail_keys: dict[str, str] = {}
        self._thumbnail_recipes: dict[str, tuple[str, ProjectRecipe, str]] = {}
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.addWidget(QLabel("LAYERS"))
        self.layer_list = QListWidget()
        self.layer_list.setObjectName("layer-list")
        self.layer_list.setEditTriggers(
            self.layer_list.EditTrigger.DoubleClicked | self.layer_list.EditTrigger.EditKeyPressed
        )
        self.layer_list.currentItemChanged.connect(self._selected)
        self.layer_list.itemChanged.connect(self._changed)
        layout.addWidget(self.layer_list, 1)
        self.pipeline_descriptor = QLabel("Select a layer to inspect its pipeline.", self)
        self.pipeline_descriptor.setObjectName("layer-pipeline-descriptor")
        self.pipeline_descriptor.setWordWrap(True)
        self.pipeline_descriptor.setToolTip(
            "Derived from the selected layer's source and transforms."
        )
        layout.addWidget(self.pipeline_descriptor)
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
        self.more_layer_actions = QPushButton("Layer actions ▾")
        transfer_menu = QMenu(self.more_layer_actions)
        self.copy_output_button = transfer_menu.addAction("Copy to Output…")
        self.move_output_button = transfer_menu.addAction("Move to Output…")
        self.create_output_button = transfer_menu.addAction("New Output from Layer")
        self.more_layer_actions.setMenu(transfer_menu)
        layout.addWidget(self.more_layer_actions)
        self.opacity = NumericControl(
            1.0,
            minimum=0.0,
            maximum=1.0,
            step=0.01,
            decimals=2,
            unit="Opacity",
            parent=self,
        )
        self.opacity.setObjectName("layer-opacity")
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
        self.copy_output_button.triggered.connect(self._copy_to_output)
        self.move_output_button.triggered.connect(self._move_to_output)
        self.create_output_button.triggered.connect(self._create_output)
        self.opacity.valueChanged.connect(self._opacity_changed)
        self.opacity.editStarted.connect(self.opacityEditStarted)
        self.opacity.editFinished.connect(self.opacityEditFinished)
        self.blend.currentIndexChanged.connect(self._blend_changed)
        self.mask_combo = QComboBox(self)
        self.mask_combo.setObjectName("layer-mask-control")
        self.mask_combo.addItem("No mask", None)
        self.mask_combo.currentIndexChanged.connect(self._mask_changed)
        self.mask_title = QLabel("LAYER MASK")
        layout.addWidget(self.mask_title)
        layout.addWidget(self.mask_combo)
        mask_buttons = QVBoxLayout()
        mask_actions = QHBoxLayout()
        mask_edit = QHBoxLayout()
        self.add_mask_button = QPushButton("Add Mask")
        self.add_image_mask_button = QPushButton("Image Mask…")
        self.edit_mask_button = QPushButton("Edit Mapping")
        self.open_mask_button = QPushButton("Open Field")
        self.clear_mask_button = QPushButton("Clear")
        mask_actions.addWidget(self.add_mask_button)
        mask_actions.addWidget(self.add_image_mask_button)
        mask_actions.addWidget(self.clear_mask_button)
        mask_edit.addWidget(self.edit_mask_button)
        mask_edit.addWidget(self.open_mask_button)
        mask_buttons.addLayout(mask_actions)
        mask_buttons.addLayout(mask_edit)
        layout.addLayout(mask_buttons)
        self.add_mask_button.clicked.connect(self._add_mask)
        self.add_image_mask_button.clicked.connect(self._add_image_mask)
        self.edit_mask_button.clicked.connect(self._edit_mask)
        self.open_mask_button.clicked.connect(self._open_mask)
        self.clear_mask_button.clicked.connect(lambda: self._set_mask(None))
        self.setMinimumWidth(230)
        self._simple_mode = False

    def set_simple_mode(self, simple: bool) -> None:
        self._simple_mode = simple
        self.pipeline_descriptor.setVisible(not simple)
        self.add_button.setVisible(True)
        self.add_button.setText("Add Layer" if simple else "Add")
        self.add_button.setMinimumHeight(34 if simple else 0)
        self.duplicate_button.setVisible(not simple)
        self.remove_button.setVisible(not simple)
        self.up_button.setVisible(not simple)
        self.down_button.setVisible(not simple)
        self.more_layer_actions.setVisible(not simple)
        self.opacity.setVisible(not simple)
        self.blend.setVisible(not simple)
        self.mask_combo.setVisible(not simple)
        self.mask_title.setVisible(not simple)
        for button in (
            self.add_mask_button,
            self.add_image_mask_button,
            self.edit_mask_button,
            self.open_mask_button,
            self.clear_mask_button,
        ):
            button.setVisible(not simple)
        # The mask heading and action rows share a parent layout; keep their
        # controls available only from the Advanced editor.

    def set_recipe(
        self, recipe: ProjectRecipe, selected_id: str | None, output_id: str | None = None
    ) -> None:
        owner = recipe.output(output_id) if output_id else recipe.outputs[0]
        layers = owner.layers
        self._syncing = True
        self.layer_list.blockSignals(True)
        self.layer_list.clear()
        self._known = {}
        selected = None
        for layer in layers:
            item = QListWidgetItem(layer.name)
            item.setData(Qt.ItemDataRole.UserRole, layer.layer_id)
            thumbnail_recipe = copy.deepcopy(recipe)
            thumbnail_recipe.width = 64
            thumbnail_recipe.height = 48
            thumbnail_owner = thumbnail_recipe.output(owner.output_id)
            thumbnail_owner.layers = [copy.deepcopy(layer)]
            key = structural_fingerprint(
                {
                    "layer": layer,
                    "seed": recipe.seed,
                    "semantic": owner.semantic,
                    "size": (64, 48),
                },
                RenderContext(),
            )
            self._current_thumbnail_keys[layer.layer_id] = key
            cached = self._thumbnail_cache.get(key)
            if cached is not None:
                item.setIcon(self._icon_from_bytes(cached))
                item.setToolTip("Rendered layer preview")
            else:
                item.setToolTip("Rendering layer preview…")
                self._thumbnail_recipes[layer.layer_id] = (
                    key,
                    thumbnail_recipe,
                    owner.output_id,
                )
                if self.isVisible():
                    self._schedule_thumbnail(layer.layer_id)
            item.setFlags(
                item.flags() | Qt.ItemFlag.ItemIsEditable | Qt.ItemFlag.ItemIsUserCheckable
            )
            item.setCheckState(Qt.CheckState.Checked if layer.enabled else Qt.CheckState.Unchecked)
            self._known[layer.layer_id] = (layer.name, layer.enabled)
            self.layer_list.addItem(item)
            if not layer.enabled:
                item.setForeground(
                    self.palette().color(
                        self.palette().ColorGroup.Disabled, self.palette().ColorRole.Text
                    )
                )
            if layer.layer_id == selected_id:
                selected = item
        if selected:
            self.layer_list.setCurrentItem(selected)
        layer = next((item for item in layers if item.layer_id == selected_id), None)
        self.opacity.setEnabled(layer is not None)
        self.blend.setEnabled(layer is not None)
        if layer:
            self.opacity.setValue(layer.opacity)
            self.blend.setCurrentIndex(max(0, self.blend.findData(layer.blend_mode)))
        self.mask_combo.blockSignals(True)
        self.mask_combo.clear()
        self.mask_combo.addItem("No mask", None)
        for identifier in recipe.control_fields:
            self.mask_combo.addItem(identifier, identifier)
        if layer is not None and layer.mask is not None:
            mask_index = self.mask_combo.findData(layer.mask.source_id)
            if mask_index >= 0:
                self.mask_combo.setCurrentIndex(mask_index)
        self.mask_combo.blockSignals(False)
        self.mask_combo.setEnabled(layer is not None and bool(recipe.control_fields))
        self.add_mask_button.setEnabled(layer is not None)
        self.add_image_mask_button.setEnabled(layer is not None)
        self.edit_mask_button.setEnabled(layer is not None and layer.mask is not None)
        self.open_mask_button.setEnabled(layer is not None and layer.mask is not None)
        self.clear_mask_button.setEnabled(layer is not None and layer.mask is not None)
        self.layer_list.blockSignals(False)
        self._syncing = False
        row = self.layer_list.currentRow()
        self.up_button.setEnabled(row > 0)
        self.down_button.setEnabled(row >= 0 and row < self.layer_list.count() - 1)
        self.remove_button.setEnabled(len(layers) > 1 and row >= 0)
        self.duplicate_button.setEnabled(row >= 0)
        self.copy_output_button.setEnabled(row >= 0)
        self.move_output_button.setEnabled(row >= 0)
        self.create_output_button.setEnabled(row >= 0)

    @staticmethod
    def _icon_from_bytes(data: bytes) -> QIcon:
        image = QImage(data, 64, 48, 64 * 4, QImage.Format.Format_RGBA8888).copy()
        return QIcon(QPixmap.fromImage(image))

    def _thumbnail_ready(self, layer_id: str, key: str, result) -> None:
        self._thumbnail_pending.discard(key)
        if isinstance(result, str):
            for index in range(self.layer_list.count()):
                item = self.layer_list.item(index)
                if item.data(Qt.ItemDataRole.UserRole) == layer_id:
                    item.setToolTip(f"Layer preview unavailable: {result}")
            return
        self._thumbnail_cache[key] = result
        if self._current_thumbnail_keys.get(layer_id) != key:
            return
        for index in range(self.layer_list.count()):
            item = self.layer_list.item(index)
            if item.data(Qt.ItemDataRole.UserRole) == layer_id:
                pixmap = QPixmap.fromImage(
                    QImage(result, 64, 48, 64 * 4, QImage.Format.Format_RGBA8888).copy()
                )
                item.setIcon(QIcon(pixmap))
                item.setToolTip("Rendered layer preview")
                self.thumbnailReady.emit(layer_id, pixmap)

    def _schedule_thumbnail(self, layer_id: str) -> None:
        pending = self._thumbnail_recipes.get(layer_id)
        if pending is None:
            return
        key, recipe, output_id = pending
        if key in self._thumbnail_pending or key in self._thumbnail_cache:
            return
        self._thumbnail_pending.add(key)
        QThreadPool.globalInstance().start(
            _LayerPreviewTask(layer_id, key, recipe, output_id, self._thumbnail_signals)
        )

    def showEvent(self, event) -> None:
        super().showEvent(event)
        for layer_id in tuple(self._thumbnail_recipes):
            self._schedule_thumbnail(layer_id)

    def set_pipeline_descriptor(self, descriptor: str) -> None:
        self.pipeline_descriptor.setText(descriptor)
        self.pipeline_descriptor.setToolTip(descriptor)

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
        # Signals may synchronously rebuild the list and delete this item.
        # Snapshot its state and update bookkeeping before emitting anything.
        name = item.text()
        enabled = item.checkState() == Qt.CheckState.Checked
        self._known[identifier] = (name, enabled)
        if name and name != old_name:
            self.renameRequested.emit(identifier, name)
        if enabled != old_enabled:
            self.enabledChanged.emit(identifier, enabled)

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

    def _copy_to_output(self) -> None:
        identifier = self._selected_id()
        if identifier:
            self.copyToOutputRequested.emit(identifier)

    def _move_to_output(self) -> None:
        identifier = self._selected_id()
        if identifier:
            self.moveToOutputRequested.emit(identifier)

    def _create_output(self) -> None:
        identifier = self._selected_id()
        if identifier:
            self.createOutputRequested.emit(identifier)

    def _opacity_changed(self, value: float) -> None:
        identifier = self._selected_id()
        if not self._syncing and identifier:
            self.opacityChanged.emit(identifier, value)

    def _blend_changed(self, _index: int) -> None:
        identifier = self._selected_id()
        if not self._syncing and identifier:
            self.blendModeChanged.emit(identifier, str(self.blend.currentData()))

    def _set_mask(self, source_id: str | None) -> None:
        identifier = self._selected_id()
        if identifier:
            self.maskChanged.emit(identifier, source_id)

    def _mask_changed(self, _index: int) -> None:
        if not self._syncing:
            self._set_mask(self.mask_combo.currentData())

    def _add_mask(self) -> None:
        identifier = self._selected_id()
        if identifier:
            self.addMaskRequested.emit(identifier)

    def _add_image_mask(self) -> None:
        identifier = self._selected_id()
        if identifier:
            self.addImageMaskRequested.emit(identifier)

    def _edit_mask(self) -> None:
        identifier = self._selected_id()
        if identifier:
            self.maskEditRequested.emit(identifier)

    def _open_mask(self) -> None:
        identifier = self._selected_id()
        if identifier:
            self.maskNavigateRequested.emit(identifier)
