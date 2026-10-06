from __future__ import annotations

import re
import sys
import uuid
from pathlib import Path

from PySide6.QtCore import QObject, QSettings, Qt, Signal
from PySide6.QtGui import QActionGroup
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QSplitter,
    QTabWidget,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from archetexture.color.ramp import ColorRamp
from archetexture.core.document import DocumentController
from archetexture.core.operations import OperationType
from archetexture.core.parameters import ControlFieldBinding
from archetexture.core.recipe import (
    ControlFieldRecipe,
    LayerRecipe,
    OperationInstance,
    ProjectRecipe,
)
from archetexture.core.registry import REGISTRY
from archetexture.core.seamlessness import recipe_seamlessness
from archetexture.export.coordinator import ExportCoordinator, ExportOutcome
from archetexture.render.coordinator import RenderCoordinator, RenderOutcome
from archetexture.ui.binding_dialog import BindingDialog
from archetexture.ui.color_ramp_editor import ColorRampEditor
from archetexture.ui.control_fields_editor import ControlFieldsEditor
from archetexture.ui.export_image_dialog import ExportImageDialog
from archetexture.ui.layers_panel import LayersPanel
from archetexture.ui.pipeline_panel import PipelinePanel
from archetexture.ui.property_editor import PropertyEditor
from archetexture.ui.theme import palette_for_mode, theme_stylesheet
from archetexture.ui.viewport import TextureViewport


class _RenderBridge(QObject):
    completed = Signal(object)


class _ExportBridge(QObject):
    completed = Signal(object)


class MainWindow(QMainWindow):
    def __init__(self, recipe: ProjectRecipe | None = None, parent=None):
        application = QApplication.instance() or QApplication(sys.argv)
        super().__init__(parent)
        self._application = application
        self.document = DocumentController(recipe)
        self._selected_layer_id = self.document.recipe.layers[0].layer_id
        self._selected_instance_id: str | None = None
        self._selected_control_field_id: str | None = None
        self._closing = False
        self._export_status_text: str | None = None
        self._export_bridge = _ExportBridge(self)
        self.export_coordinator = ExportCoordinator(on_complete=self._export_bridge.completed.emit)
        self._export_bridge.completed.connect(
            self._on_export_complete, Qt.ConnectionType.QueuedConnection
        )
        self._render_bridge = _RenderBridge(self)
        self.render_coordinator = RenderCoordinator(on_complete=self._render_bridge.completed.emit)
        self._render_bridge.completed.connect(
            self._on_render_complete,
            Qt.ConnectionType.QueuedConnection,
        )

        self.setWindowTitle("ArcheTexture")
        self.resize(1360, 850)
        self.pipeline_panel = PipelinePanel(self)
        self.layers_panel = LayersPanel(self)
        self.viewport = TextureViewport(self)
        self.color_ramp_editor = ColorRampEditor(self)
        self.property_editor = PropertyEditor(self)
        self.control_fields_editor = ControlFieldsEditor(self)
        self.pipeline_panel.sourceChanged.connect(self._source_changed)
        self.pipeline_panel.transformAdded.connect(self._transform_added)
        self.pipeline_panel.transformRemoved.connect(self._transform_removed)
        self.pipeline_panel.transformMoved.connect(self._transform_moved)
        self.pipeline_panel.transformEnabled.connect(self._transform_enabled)
        self.pipeline_panel.selectionChanged.connect(self._select_instance)
        self.property_editor.valueChanged.connect(self._property_changed)
        self.property_editor.bindingRequested.connect(self._main_binding_requested)
        self.control_fields_editor.createRequested.connect(self._create_control_field)
        self.control_fields_editor.fieldSelected.connect(self._control_field_selected)
        self.control_fields_editor.renameRequested.connect(self._rename_control_field)
        self.control_fields_editor.removeRequested.connect(self._remove_control_field)
        self.control_fields_editor.sourceChanged.connect(self._control_source_changed)
        self.control_fields_editor.transformAdded.connect(self._control_transform_added)
        self.control_fields_editor.transformRemoved.connect(self._control_transform_removed)
        self.control_fields_editor.transformMoved.connect(self._control_transform_moved)
        self.control_fields_editor.transformEnabled.connect(self._control_transform_enabled)
        self.control_fields_editor.valueChanged.connect(self._control_value_changed)
        self.control_fields_editor.bindingRequested.connect(self._control_binding_requested)
        self.color_ramp_editor.rampEdited.connect(self._color_ramp_changed)
        self.color_ramp_editor.previewRequested.connect(self._preview_color_ramp)
        self.layers_panel.addRequested.connect(self._add_layer)
        self.layers_panel.removeRequested.connect(self._remove_layer)
        self.layers_panel.duplicateRequested.connect(self._duplicate_layer)
        self.layers_panel.renameRequested.connect(self._rename_layer)
        self.layers_panel.selectionChanged.connect(self._select_layer)
        self.layers_panel.enabledChanged.connect(self._layer_enabled)
        self.layers_panel.moved.connect(self._layer_moved)
        self.layers_panel.opacityChanged.connect(self._layer_opacity_changed)
        self.layers_panel.blendModeChanged.connect(self._layer_blend_changed)

        center_panel = QWidget(self)
        center_layout = QVBoxLayout(center_panel)
        center_layout.setContentsMargins(0, 0, 0, 0)
        center_layout.setSpacing(4)
        view_row = QHBoxLayout()
        view_row.setContentsMargins(8, 2, 8, 0)
        view_row.addWidget(QLabel("View:"))
        self.viewport_mode_combo = QComboBox(center_panel)
        self.viewport_mode_combo.setObjectName("viewport-display-mode")
        for label, mode in (
            ("Single", "single"),
            ("Tile 3×3", "tile_3x3"),
            ("Seam Check", "seam_check"),
        ):
            self.viewport_mode_combo.addItem(label, mode)
        saved_view_mode = self._theme_settings().value("viewport/mode", "single")
        selected_view_index = self.viewport_mode_combo.findData(saved_view_mode)
        if selected_view_index < 0:
            selected_view_index = self.viewport_mode_combo.findData("single")
        self.viewport_mode_combo.setCurrentIndex(selected_view_index)
        self.viewport.set_display_mode(self.viewport_mode_combo.currentData())
        self.viewport_mode_combo.currentIndexChanged.connect(self._viewport_mode_changed)
        view_row.addWidget(self.viewport_mode_combo)
        self.seamlessness_label = QLabel("Seamless: Unknown")
        self.seamlessness_label.setObjectName("seamlessness-status")
        self.seamlessness_label.setToolTip(
            "Conservative status for enabled, visible layer sources and transforms."
        )
        view_row.addWidget(self.seamlessness_label)
        view_row.addStretch(1)
        center_layout.addLayout(view_row)
        center_layout.addWidget(self.viewport, 1)
        center_layout.addWidget(self.color_ramp_editor, 0)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        left_panel = QWidget(self)
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.addWidget(self.layers_panel, 1)
        left_layout.addWidget(self.pipeline_panel, 1)
        splitter.addWidget(left_panel)
        splitter.addWidget(center_panel)
        self.right_tabs = QTabWidget(self)
        self.right_tabs.addTab(self.property_editor, "Properties")
        self.right_tabs.addTab(self.control_fields_editor, "Control Fields")
        self.right_tabs.setObjectName("right-side-tabs")
        splitter.addWidget(self.right_tabs)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setStretchFactor(2, 0)
        splitter.setSizes([250, 820, 300])
        self.setCentralWidget(splitter)

        self._create_actions()
        self._selected_instance_id = self._layer().source.instance_id
        self._configure_theme()
        self._refresh_document(request_render=True)

    def _create_actions(self) -> None:
        file_menu = self.menuBar().addMenu("&File")
        edit_menu = self.menuBar().addMenu("&Edit")
        view_menu = self.menuBar().addMenu("&View")
        appearance_menu = view_menu.addMenu("&Appearance")
        self.new_action = file_menu.addAction("&New")
        self.open_action = file_menu.addAction("&Open…")
        self.save_action = file_menu.addAction("&Save")
        self.save_as_action = file_menu.addAction("Save &As…")
        self.export_action = file_menu.addAction("Export PNG…")
        self.export_action.setShortcut("Ctrl+Shift+E")
        file_menu.addSeparator()
        self.exit_action = file_menu.addAction("E&xit")
        self.undo_action = edit_menu.addAction("&Undo")
        self.redo_action = edit_menu.addAction("&Redo")
        self.theme_actions = {}
        group = QActionGroup(self)
        group.setExclusive(True)
        for mode in ("System", "Light", "Dark"):
            selected_mode = mode.lower()
            action = appearance_menu.addAction(mode)
            action.setCheckable(True)
            group.addAction(action)
            action.triggered.connect(
                lambda _checked=False, selected=selected_mode: self._set_theme(selected)
            )
            self.theme_actions[selected_mode] = action

        toolbar = QToolBar("Document", self)
        self.addToolBar(toolbar)
        for action in (
            self.new_action,
            self.open_action,
            self.save_action,
            self.save_as_action,
        ):
            toolbar.addAction(action)
        toolbar.addSeparator()
        toolbar.addAction(self.undo_action)
        toolbar.addAction(self.redo_action)

        self.new_action.triggered.connect(lambda: self.new_document())
        self.open_action.triggered.connect(lambda: self.open_project())
        self.save_action.triggered.connect(lambda: self.save_project())
        self.save_as_action.triggered.connect(lambda: self.save_project(save_as=True))
        self.export_action.triggered.connect(self.export_png)
        self.exit_action.triggered.connect(self.close)
        self.undo_action.triggered.connect(self.undo)
        self.redo_action.triggered.connect(self.redo)
        self.statusBar().showMessage("Ready")

    def _configure_theme(self) -> None:
        self._system_palette = self._application.style().standardPalette()
        settings = self._theme_settings()
        mode = settings.value("appearance/theme", "dark")
        self._set_theme(mode if mode in {"system", "light", "dark"} else "dark", persist=False)

    def _set_theme(self, mode: str, *, persist: bool = True) -> None:
        if mode not in {"system", "light", "dark"}:
            mode = "dark"
        self._application.setPalette(palette_for_mode(mode, self._system_palette))
        self._application.setStyleSheet(theme_stylesheet(mode))
        if hasattr(self, "theme_actions"):
            self.theme_actions[mode].setChecked(True)
        if persist:
            settings = self._theme_settings()
            settings.setValue("appearance/theme", mode)
            settings.sync()

    @staticmethod
    def _theme_settings() -> QSettings:
        return QSettings(
            QSettings.Format.IniFormat,
            QSettings.Scope.UserScope,
            "ArcheTexture",
            "ArcheTexture",
        )

    def _viewport_mode_changed(self, index: int) -> None:
        mode = self.viewport_mode_combo.itemData(index)
        if mode not in TextureViewport.DISPLAY_MODES:
            mode = "single"
        self.viewport.set_display_mode(mode)
        settings = self._theme_settings()
        settings.setValue("viewport/mode", mode)
        settings.sync()

    def _layer(self, recipe: ProjectRecipe | None = None) -> LayerRecipe:
        recipe = recipe or self.document.recipe
        layer = next(
            (item for item in recipe.layers if item.layer_id == self._selected_layer_id), None
        )
        if layer is None:
            layer = recipe.layers[0]
            self._selected_layer_id = layer.layer_id
        return layer

    def _refresh_document(
        self,
        *,
        request_render: bool,
        refresh_properties: bool = True,
        reset_ramp_selection: bool = False,
    ) -> None:
        recipe = self.document.recipe
        layer = self._layer(recipe)
        self.seamlessness_label.setText(f"Seamless: {recipe_seamlessness(recipe)}")
        if self._selected_instance_id is None or not self._contains_instance(
            recipe, self._selected_instance_id
        ):
            self._selected_instance_id = layer.source.instance_id if layer.source else None
        self.layers_panel.set_recipe(recipe, self._selected_layer_id)
        self.pipeline_panel.set_recipe(recipe, self._selected_instance_id, layer)
        self.property_editor.set_control_fields(recipe.control_fields)
        self.control_fields_editor.set_recipe(recipe, self._selected_control_field_id)
        self._selected_control_field_id = self.control_fields_editor.selected_field_id
        self.color_ramp_editor.set_ramp(
            layer.color_ramp,
            reset_selection=reset_ramp_selection,
        )
        if refresh_properties:
            self._refresh_property_editor(recipe)
        self._update_title_and_actions()
        if request_render:
            self._request_render()

    @staticmethod
    def _contains_instance(recipe: ProjectRecipe, instance_id: str) -> bool:
        instances = [
            instance for layer in recipe.layers for instance in [layer.source, *layer.transforms]
        ]
        return any(item is not None and item.instance_id == instance_id for item in instances)

    def _refresh_property_editor(self, recipe: ProjectRecipe) -> None:
        instance = None
        layer = self._layer(recipe)
        instance = (
            layer.source
            if layer.source.instance_id == self._selected_instance_id
            else next(
                (
                    item
                    for item in layer.transforms
                    if item.instance_id == self._selected_instance_id
                ),
                None,
            )
        )
        definition = REGISTRY.get(instance.operation_id) if instance is not None else None
        self.property_editor.set_operation(instance, definition)

    def _update_title_and_actions(self) -> None:
        path = Path(self.document.project_path).name if self.document.project_path else "Untitled"
        dirty = "*" if self.document.dirty else ""
        self.setWindowTitle(f"{path}{dirty} — ArcheTexture")
        self.undo_action.setEnabled(self.document.can_undo)
        self.redo_action.setEnabled(self.document.can_redo)
        self.save_action.setEnabled(True)

    def _request_render(self, recipe: ProjectRecipe | None = None) -> None:
        if self._closing:
            return
        recipe = recipe or self.document.recipe
        self.statusBar().showMessage("Rendering…")
        try:
            self.render_coordinator.request(
                recipe,
                width=recipe.width,
                height=recipe.height,
            )
        except Exception as exc:
            self.viewport.set_error(str(exc))
            self.statusBar().showMessage(f"Render request failed: {exc}")

    def _color_ramp_changed(self, color_ramp: ColorRamp | None) -> None:
        recipe = self.document.recipe
        self._layer(recipe).color_ramp = color_ramp
        self._commit_recipe(recipe, self._selected_instance_id)

    def _preview_color_ramp(self, color_ramp: ColorRamp) -> None:
        recipe = self.document.recipe
        self._layer(recipe).color_ramp = color_ramp
        self._request_render(recipe)

    def _on_render_complete(self, outcome: RenderOutcome) -> None:
        if self._closing or outcome.request_id != self.render_coordinator.latest_request_id:
            return
        if outcome.error is not None:
            self.viewport.set_error(str(outcome.error))
            self.statusBar().showMessage(f"Render failed: {outcome.error}")
            return
        if outcome.result is None:
            self.viewport.set_error("Render returned no result.")
            self.statusBar().showMessage("Render failed")
            return
        self.viewport.set_result(outcome.result)
        self.statusBar().showMessage(self._export_status_text or "Ready", 3000)

    def export_png(self, *_args) -> bool:
        dialog = ExportImageDialog(self.document.recipe, self)
        if dialog.exec() != dialog.DialogCode.Accepted:
            return False
        width, height = dialog.dimensions
        suggestion = (
            Path(self.document.project_path).with_suffix(".png").name
            if self.document.project_path
            else "Untitled.png"
        )
        destination, _selected_filter = QFileDialog.getSaveFileName(
            self, "Export PNG", suggestion, "PNG Image (*.png)"
        )
        if not destination:
            return False
        destination_path = Path(destination)
        if destination_path.suffix.lower() != ".png":
            destination_path = (
                destination_path.with_suffix(".png")
                if destination_path.suffix
                else Path(f"{destination_path}.png")
            )
        return self._start_export(destination_path, width, height)

    def _start_export(self, destination: str | Path, width: int, height: int) -> bool:
        try:
            self.export_coordinator.request(
                self.document.recipe, destination, width=width, height=height
            )
        except Exception as exc:
            QMessageBox.critical(self, "Export failed", str(exc))
            return False
        self.export_action.setEnabled(False)
        self._export_status_text = f"Exporting {Path(destination).name}…"
        self.statusBar().showMessage(self._export_status_text)
        return True

    def _on_export_complete(self, outcome: ExportOutcome) -> None:
        if self._closing:
            return
        self.export_action.setEnabled(True)
        self._export_status_text = None
        if outcome.error is not None:
            self.statusBar().showMessage("PNG export failed")
            QMessageBox.critical(self, "Export failed", str(outcome.error))
            return
        self.statusBar().showMessage(f"Exported {outcome.destination.name}", 5000)

    def _commit_recipe(
        self,
        recipe: ProjectRecipe,
        selected_id: str | None = None,
        *,
        refresh_properties: bool = True,
        control_field_id: str | None = None,
    ) -> None:
        try:
            self.document.commit(recipe)
        except Exception as exc:
            self.statusBar().showMessage(f"Edit rejected: {exc}", 5000)
            self._refresh_document(request_render=False)
            return
        if selected_id is not None:
            self._selected_instance_id = selected_id
        if control_field_id is not None:
            self._selected_control_field_id = control_field_id
        self._refresh_document(
            request_render=True,
            refresh_properties=refresh_properties,
        )

    def _source_changed(self, operation_id: str) -> None:
        recipe = self.document.recipe
        layer = self._layer(recipe)
        if layer.source is not None and layer.source.operation_id == operation_id:
            return
        definition = REGISTRY.get(operation_id)
        if definition.operation_type != OperationType.GENERATOR:
            return
        instance_id = layer.source.instance_id if layer.source else f"source-{uuid.uuid4().hex[:8]}"
        layer.source = OperationInstance(
            instance_id,
            operation_id,
            definition.version,
            parameters={spec.identifier: spec.default for spec in definition.parameter_specs},
        )
        self._commit_recipe(recipe, instance_id)

    def _transform_added(self, operation_id: str) -> None:
        recipe = self.document.recipe
        layer = self._layer(recipe)
        definition = REGISTRY.get(operation_id)
        if definition.operation_type != OperationType.TRANSFORM:
            return
        instance_id = f"transform-{uuid.uuid4().hex[:12]}"
        layer.transforms.append(
            OperationInstance(
                instance_id,
                operation_id,
                definition.version,
                parameters={spec.identifier: spec.default for spec in definition.parameter_specs},
            )
        )
        self._commit_recipe(recipe, instance_id)

    def _transform_removed(self, instance_id: str) -> None:
        recipe = self.document.recipe
        layer = self._layer(recipe)
        old_index = next(
            (
                index
                for index, item in enumerate(layer.transforms)
                if item.instance_id == instance_id
            ),
            None,
        )
        if old_index is None:
            return
        del layer.transforms[old_index]
        selected_id = layer.source.instance_id if layer.source else None
        if layer.transforms:
            selected_id = layer.transforms[min(old_index, len(layer.transforms) - 1)].instance_id
        self._commit_recipe(recipe, selected_id)

    def _transform_moved(self, instance_id: str, target_index: int) -> None:
        recipe = self.document.recipe
        transforms = self._layer(recipe).transforms
        old_index = next(
            (index for index, item in enumerate(transforms) if item.instance_id == instance_id),
            None,
        )
        if old_index is None or not 0 <= target_index < len(transforms):
            return
        item = transforms.pop(old_index)
        transforms.insert(target_index, item)
        self._commit_recipe(recipe, instance_id)

    def _transform_enabled(self, instance_id: str, enabled: bool) -> None:
        recipe = self.document.recipe
        layer = self._layer(recipe)
        instance = next(
            (item for item in layer.transforms if item.instance_id == instance_id),
            None,
        )
        if instance is None or instance.enabled == enabled:
            return
        instance.enabled = enabled
        self._commit_recipe(recipe, instance_id)

    def _select_instance(self, instance_id: str) -> None:
        self._selected_instance_id = instance_id
        self._refresh_property_editor(self.document.recipe)

    def _property_changed(self, parameter_id: str, value) -> None:
        recipe = self.document.recipe
        layer = self._layer(recipe)
        instance = next(
            (
                item
                for item in [layer.source, *layer.transforms]
                if item is not None and item.instance_id == self._selected_instance_id
            ),
            None,
        )
        if instance is None:
            return
        if parameter_id == "influence":
            refresh_properties = isinstance(instance.influence, ControlFieldBinding)
            instance.influence = value
        else:
            refresh_properties = isinstance(
                instance.parameters.get(parameter_id), ControlFieldBinding
            )
            instance.parameters[parameter_id] = value
        self._commit_recipe(
            recipe,
            instance.instance_id,
            refresh_properties=refresh_properties,
        )

    def _select_layer(self, layer_id: str) -> None:
        if not any(layer.layer_id == layer_id for layer in self.document.recipe.layers):
            return
        self._selected_layer_id = layer_id
        layer = self._layer()
        self._selected_instance_id = layer.source.instance_id
        self._refresh_document(request_render=False, reset_ramp_selection=True)

    def _add_layer(self) -> None:
        recipe = self.document.recipe
        number = 1
        names = {layer.name for layer in recipe.layers}
        while f"Layer {number}" in names:
            number += 1
        layer_id = f"layer-{uuid.uuid4().hex[:12]}"
        recipe.layers.append(
            LayerRecipe(
                layer_id,
                f"Layer {number}",
                OperationInstance(
                    f"source-{uuid.uuid4().hex[:12]}",
                    "generator.constant",
                    1,
                    parameters={"value": 0.5},
                ),
            )
        )
        self._selected_layer_id = layer_id
        self._selected_instance_id = recipe.layers[-1].source.instance_id
        self._commit_recipe(recipe, self._selected_instance_id)

    def _remove_layer(self, layer_id: str) -> None:
        recipe = self.document.recipe
        if len(recipe.layers) <= 1:
            self.statusBar().showMessage("A project must keep at least one layer", 5000)
            return
        index = next(
            (i for i, layer in enumerate(recipe.layers) if layer.layer_id == layer_id), None
        )
        if index is None:
            return
        del recipe.layers[index]
        selected = recipe.layers[min(index, len(recipe.layers) - 1)]
        self._selected_layer_id = selected.layer_id
        self._selected_instance_id = selected.source.instance_id
        self._commit_recipe(recipe, self._selected_instance_id)

    def _duplicate_layer(self, layer_id: str) -> None:
        import copy

        recipe = self.document.recipe
        index = next(
            (i for i, layer in enumerate(recipe.layers) if layer.layer_id == layer_id), None
        )
        if index is None:
            return
        duplicate = copy.deepcopy(recipe.layers[index])
        duplicate.layer_id = f"layer-{uuid.uuid4().hex[:12]}"
        duplicate.name = f"{duplicate.name} Copy"
        for instance in [duplicate.source, *duplicate.transforms]:
            instance.instance_id = f"op-{uuid.uuid4().hex[:12]}"
        recipe.layers.insert(index + 1, duplicate)
        self._selected_layer_id = duplicate.layer_id
        self._selected_instance_id = duplicate.source.instance_id
        self._commit_recipe(recipe, self._selected_instance_id)

    def _rename_layer(self, layer_id: str, name: str) -> None:
        recipe = self.document.recipe
        layer = next((item for item in recipe.layers if item.layer_id == layer_id), None)
        name = name.strip()
        if layer is None or not name or layer.name == name:
            self._refresh_document(request_render=False)
            return
        layer.name = name
        self._commit_recipe(recipe)

    def _layer_enabled(self, layer_id: str, enabled: bool) -> None:
        recipe = self.document.recipe
        layer = next((item for item in recipe.layers if item.layer_id == layer_id), None)
        if layer is not None and layer.enabled != enabled:
            layer.enabled = enabled
            self._commit_recipe(recipe)

    def _layer_moved(self, layer_id: str, target_index: int) -> None:
        recipe = self.document.recipe
        old_index = next(
            (i for i, layer in enumerate(recipe.layers) if layer.layer_id == layer_id), None
        )
        if old_index is None or not 0 <= target_index < len(recipe.layers):
            return
        recipe.layers.insert(target_index, recipe.layers.pop(old_index))
        self._commit_recipe(recipe)

    def _layer_opacity_changed(self, layer_id: str, opacity: float) -> None:
        recipe = self.document.recipe
        layer = next((item for item in recipe.layers if item.layer_id == layer_id), None)
        if layer is not None and layer.opacity != opacity:
            layer.opacity = opacity
            self._commit_recipe(recipe)

    def _layer_blend_changed(self, layer_id: str, mode: str) -> None:
        recipe = self.document.recipe
        layer = next((item for item in recipe.layers if item.layer_id == layer_id), None)
        if layer is not None and layer.blend_mode != mode:
            layer.blend_mode = mode
            self._commit_recipe(recipe)

    def _control_field_selected(self, identifier: str) -> None:
        self._selected_control_field_id = identifier

    def _create_control_field(self) -> None:
        recipe = self.document.recipe
        index = 1
        while f"control-{index}" in recipe.control_fields:
            index += 1
        identifier = f"control-{index}"
        definition = next(
            (
                item
                for item in REGISTRY.definitions.values()
                if item.operation_type == OperationType.GENERATOR and item.output_type == "scalar"
            ),
            None,
        )
        if definition is None:
            self.statusBar().showMessage("No scalar generators are registered", 5000)
            return
        recipe.control_fields[identifier] = ControlFieldRecipe(
            source=OperationInstance(
                f"{identifier}-source",
                definition.identifier,
                definition.version,
                parameters={spec.identifier: spec.default for spec in definition.parameter_specs},
            )
        )
        self._commit_recipe(recipe, control_field_id=identifier)

    @staticmethod
    def _rewrite_binding_value(value, old_id: str, new_id: str):
        if isinstance(value, ControlFieldBinding):
            if value.source_id == old_id:
                return ControlFieldBinding(new_id, value.mapping)
            return value
        if isinstance(value, dict):
            return {
                key: MainWindow._rewrite_binding_value(item, old_id, new_id)
                for key, item in value.items()
            }
        if isinstance(value, list):
            return [MainWindow._rewrite_binding_value(item, old_id, new_id) for item in value]
        if isinstance(value, tuple):
            return tuple(MainWindow._rewrite_binding_value(item, old_id, new_id) for item in value)
        return value

    @classmethod
    def _rewrite_instance_bindings(cls, instance: OperationInstance, old_id: str, new_id: str):
        instance.parameters = cls._rewrite_binding_value(instance.parameters, old_id, new_id)
        instance.influence = cls._rewrite_binding_value(instance.influence, old_id, new_id)

    def _rename_control_field(self, old_id: str, new_id: str) -> None:
        new_id = new_id.strip()
        recipe = self.document.recipe
        if old_id not in recipe.control_fields:
            return
        if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_.-]*", new_id):
            self.statusBar().showMessage(
                "Use a letter followed by letters, numbers, dots, underscores, or hyphens.", 6000
            )
            self._refresh_document(request_render=False)
            return
        if new_id == old_id:
            return
        if new_id in recipe.control_fields:
            self.statusBar().showMessage(f"Control field '{new_id}' already exists", 5000)
            self._refresh_document(request_render=False)
            return
        recipe.control_fields[new_id] = recipe.control_fields.pop(old_id)
        instances = [
            instance for layer in recipe.layers for instance in [layer.source, *layer.transforms]
        ]
        for control in recipe.control_fields.values():
            instances.extend((control.source, *control.transforms))
        for instance in instances:
            if instance is not None:
                self._rewrite_instance_bindings(instance, old_id, new_id)
        self._commit_recipe(recipe, control_field_id=new_id)

    @staticmethod
    def _iter_control_bindings(value, path: str):
        if isinstance(value, ControlFieldBinding):
            yield value, path
        elif isinstance(value, dict):
            for key, item in value.items():
                yield from MainWindow._iter_control_bindings(item, f"{path}.{key}")
        elif isinstance(value, (tuple, list)):
            for index, item in enumerate(value):
                yield from MainWindow._iter_control_bindings(item, f"{path}[{index}]")

    def _first_control_reference(self, recipe: ProjectRecipe, identifier: str) -> str | None:
        instances = []
        for layer in recipe.layers:
            label = "main source" if len(recipe.layers) == 1 else f"{layer.name} source"
            instances.append((label, layer.source))
            instances.extend(
                (f"{layer.name} transform {item.operation_id}", item) for item in layer.transforms
            )
        for field_id, control in recipe.control_fields.items():
            instances.append((f"control field {field_id} source", control.source))
            instances.extend(
                (f"control field {field_id} transform {item.operation_id}", item)
                for item in control.transforms
            )
        for description, instance in instances:
            if instance is None:
                continue
            values = [("parameter", instance.parameters), ("influence", instance.influence)]
            for label, value in values:
                for binding, path in self._iter_control_bindings(value, label):
                    if binding.source_id == identifier:
                        return f"{description} ({path})"
        return None

    def _remove_control_field(self, identifier: str) -> None:
        recipe = self.document.recipe
        if identifier not in recipe.control_fields:
            return
        reference = self._first_control_reference(recipe, identifier)
        if reference is not None:
            QMessageBox.information(
                self,
                "Control field is in use",
                f"'{identifier}' is referenced by {reference}. Remove that binding first.",
            )
            return
        del recipe.control_fields[identifier]
        self._commit_recipe(recipe, control_field_id=next(iter(recipe.control_fields), None))

    def _control_source_changed(self, identifier: str, operation_id: str) -> None:
        recipe = self.document.recipe
        control = recipe.control_fields.get(identifier)
        if control is None:
            return
        definition = REGISTRY.get(operation_id)
        if (
            definition.operation_type != OperationType.GENERATOR
            or definition.output_type != "scalar"
        ):
            return
        control.source = OperationInstance(
            control.source.instance_id,
            operation_id,
            definition.version,
            parameters={spec.identifier: spec.default for spec in definition.parameter_specs},
        )
        self._commit_recipe(recipe, control_field_id=identifier)

    def _control_transform_added(self, identifier: str, operation_id: str) -> None:
        recipe = self.document.recipe
        control = recipe.control_fields.get(identifier)
        if control is None:
            return
        definition = REGISTRY.get(operation_id)
        if not (
            definition.operation_type == OperationType.TRANSFORM
            and definition.output_type == "scalar"
            and ("scalar" in definition.input_types or "any" in definition.input_types)
        ):
            return
        instance_id = f"{identifier}-transform-{uuid.uuid4().hex[:10]}"
        control.transforms.append(
            OperationInstance(
                instance_id,
                operation_id,
                definition.version,
                parameters={spec.identifier: spec.default for spec in definition.parameter_specs},
            )
        )
        self.control_fields_editor.select_operation(instance_id)
        self._commit_recipe(recipe, control_field_id=identifier)

    def _control_transform_removed(self, identifier: str, instance_id: str) -> None:
        recipe = self.document.recipe
        control = recipe.control_fields.get(identifier)
        if control is None:
            return
        if self.control_fields_editor._selected_operation_id == instance_id:
            self.control_fields_editor.select_operation(None)
        control.transforms = [
            item for item in control.transforms if item.instance_id != instance_id
        ]
        self._commit_recipe(recipe, control_field_id=identifier)

    def _control_transform_moved(self, identifier: str, instance_id: str, target: int) -> None:
        recipe = self.document.recipe
        control = recipe.control_fields.get(identifier)
        if control is None:
            return
        old = next(
            (i for i, item in enumerate(control.transforms) if item.instance_id == instance_id),
            None,
        )
        if old is None or not 0 <= target < len(control.transforms):
            return
        item = control.transforms.pop(old)
        control.transforms.insert(target, item)
        self._commit_recipe(recipe, control_field_id=identifier)

    def _control_transform_enabled(self, identifier: str, instance_id: str, enabled: bool) -> None:
        recipe = self.document.recipe
        control = recipe.control_fields.get(identifier)
        item = (
            next((item for item in control.transforms if item.instance_id == instance_id), None)
            if control
            else None
        )
        if item is None or item.enabled == enabled:
            return
        item.enabled = enabled
        self._commit_recipe(recipe, control_field_id=identifier)

    def _control_value_changed(self, identifier: str, key: str, value) -> None:
        recipe = self.document.recipe
        control = recipe.control_fields.get(identifier)
        if control is None:
            return
        if key == "mapping":
            control.mapping = value
        else:
            instance_id, parameter_id = key
            instance = (
                control.source
                if control.source.instance_id == instance_id
                else next(
                    (item for item in control.transforms if item.instance_id == instance_id), None
                )
            )
            if instance is None:
                return
            if parameter_id == "influence":
                instance.influence = value
            else:
                instance.parameters[parameter_id] = value
        self._commit_recipe(recipe, control_field_id=identifier)

    def _main_binding_requested(self, key: str, spec, existing) -> None:
        recipe = self.document.recipe
        if not recipe.control_fields:
            self.right_tabs.setCurrentWidget(self.control_fields_editor)
            self.statusBar().showMessage("Create a control field before binding a parameter", 5000)
            return
        dialog = BindingDialog(recipe.control_fields, spec, existing, self)
        if dialog.exec() != dialog.DialogCode.Accepted:
            return
        instance = next(
            (
                item
                for item in [self._layer(recipe).source, *self._layer(recipe).transforms]
                if item is not None and item.instance_id == self._selected_instance_id
            ),
            None,
        )
        if instance is None:
            return
        if key == "influence":
            instance.influence = dialog.binding
        else:
            instance.parameters[key] = dialog.binding
        self._commit_recipe(recipe, instance.instance_id, refresh_properties=True)

    def _control_binding_requested(self, identifier: str, key: str, spec, existing) -> None:
        recipe = self.document.recipe
        if not recipe.control_fields:
            return
        dialog = BindingDialog(recipe.control_fields, spec, existing, self)
        if dialog.exec() != dialog.DialogCode.Accepted:
            return
        control = recipe.control_fields.get(identifier)
        if control is None:
            return
        instance_id, parameter_id = key
        instance = (
            control.source
            if control.source.instance_id == instance_id
            else next(
                (item for item in control.transforms if item.instance_id == instance_id), None
            )
        )
        if instance is None:
            return
        if parameter_id == "influence":
            instance.influence = dialog.binding
        else:
            instance.parameters[parameter_id] = dialog.binding
        self._commit_recipe(recipe, control_field_id=identifier)

    def undo(self) -> None:
        if not self.document.can_undo:
            return
        self.document.undo()
        self._refresh_document(request_render=True)

    def redo(self) -> None:
        if not self.document.can_redo:
            return
        self.document.redo()
        self._refresh_document(request_render=True)

    def _confirm_discard(self) -> bool:
        if not self.document.dirty:
            return True
        choice = QMessageBox.question(
            self,
            "Unsaved changes",
            "Save changes before continuing?",
            QMessageBox.StandardButton.Save
            | QMessageBox.StandardButton.Discard
            | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Save,
        )
        if choice == QMessageBox.StandardButton.Save:
            return self.save_project()
        return choice == QMessageBox.StandardButton.Discard

    def new_document(self, *_args) -> bool:
        if not self._confirm_discard():
            return False
        recipe = self.document.new_document()
        self._selected_layer_id = recipe.layers[0].layer_id
        self._selected_instance_id = recipe.layers[0].source.instance_id
        self._refresh_document(request_render=True, reset_ramp_selection=True)
        return True

    def open_project(self, path: str | Path | None = None, *_args) -> bool:
        if path is None:
            path, _selected_filter = QFileDialog.getOpenFileName(
                self,
                "Open ArcheTexture project",
                "",
                "ArcheTexture Project (*.archetexture)",
            )
        if not path:
            return False
        path = str(path)
        try:
            candidate = self.document.prepare_project(path)
        except Exception as exc:
            QMessageBox.critical(self, "Open failed", str(exc))
            return False
        if not self._confirm_discard():
            return False
        recipe = self.document.replace_with_project(candidate)
        self._selected_layer_id = recipe.layers[0].layer_id
        self._selected_instance_id = recipe.layers[0].source.instance_id
        self._refresh_document(request_render=True, reset_ramp_selection=True)
        return True

    def save_project(self, path: str | Path | None = None, *, save_as: bool = False) -> bool:
        destination = str(path) if path is not None else None
        if save_as or destination is None and self.document.project_path is None:
            suggestion = self.document.project_path or "Untitled.archetexture"
            destination, _selected_filter = QFileDialog.getSaveFileName(
                self,
                "Save ArcheTexture project",
                suggestion,
                "ArcheTexture Project (*.archetexture)",
            )
        if not destination:
            return False
        if not destination.lower().endswith(".archetexture"):
            destination += ".archetexture"
        try:
            self.document.save(destination)
        except Exception as exc:
            QMessageBox.critical(self, "Save failed", str(exc))
            return False
        self._update_title_and_actions()
        self.statusBar().showMessage(f"Saved {destination}", 3000)
        return True

    def closeEvent(self, event) -> None:
        if not self._confirm_discard():
            event.ignore()
            return
        self._closing = True
        self.render_coordinator.close(wait=False)
        self.export_coordinator.close(wait=True)
        event.accept()


def build_main_window(recipe: ProjectRecipe | None = None) -> MainWindow:
    return MainWindow(recipe)


def main() -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    window = build_main_window()
    window.show()
    return app.exec()
