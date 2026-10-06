from __future__ import annotations

import sys
import uuid
from pathlib import Path

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QMainWindow,
    QMessageBox,
    QSplitter,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from archetexture.color.ramp import ColorRamp
from archetexture.core.document import DocumentController
from archetexture.core.operations import OperationType
from archetexture.core.parameters import ControlFieldBinding
from archetexture.core.recipe import OperationInstance, ProjectRecipe
from archetexture.core.registry import REGISTRY
from archetexture.render.coordinator import RenderCoordinator, RenderOutcome
from archetexture.ui.color_ramp_editor import ColorRampEditor
from archetexture.ui.pipeline_panel import PipelinePanel
from archetexture.ui.property_editor import PropertyEditor
from archetexture.ui.viewport import TextureViewport


class _RenderBridge(QObject):
    completed = Signal(object)


class MainWindow(QMainWindow):
    def __init__(self, recipe: ProjectRecipe | None = None, parent=None):
        application = QApplication.instance() or QApplication(sys.argv)
        super().__init__(parent)
        self._application = application
        self.document = DocumentController(recipe)
        self._selected_instance_id: str | None = None
        self._closing = False
        self._render_bridge = _RenderBridge(self)
        self.render_coordinator = RenderCoordinator(on_complete=self._render_bridge.completed.emit)
        self._render_bridge.completed.connect(
            self._on_render_complete,
            Qt.ConnectionType.QueuedConnection,
        )

        self.setWindowTitle("ArcheTexture")
        self.resize(1360, 850)
        self.pipeline_panel = PipelinePanel(self)
        self.viewport = TextureViewport(self)
        self.color_ramp_editor = ColorRampEditor(self)
        self.property_editor = PropertyEditor(self)
        self.pipeline_panel.sourceChanged.connect(self._source_changed)
        self.pipeline_panel.transformAdded.connect(self._transform_added)
        self.pipeline_panel.transformRemoved.connect(self._transform_removed)
        self.pipeline_panel.transformMoved.connect(self._transform_moved)
        self.pipeline_panel.transformEnabled.connect(self._transform_enabled)
        self.pipeline_panel.selectionChanged.connect(self._select_instance)
        self.property_editor.valueChanged.connect(self._property_changed)
        self.color_ramp_editor.rampEdited.connect(self._color_ramp_changed)
        self.color_ramp_editor.previewRequested.connect(self._preview_color_ramp)

        center_panel = QWidget(self)
        center_layout = QVBoxLayout(center_panel)
        center_layout.setContentsMargins(0, 0, 0, 0)
        center_layout.setSpacing(4)
        center_layout.addWidget(self.viewport, 1)
        center_layout.addWidget(self.color_ramp_editor, 0)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self.pipeline_panel)
        splitter.addWidget(center_panel)
        splitter.addWidget(self.property_editor)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setStretchFactor(2, 0)
        splitter.setSizes([250, 820, 300])
        self.setCentralWidget(splitter)

        self._create_actions()
        self._selected_instance_id = self.document.recipe.source.instance_id
        self._refresh_document(request_render=True)

    def _create_actions(self) -> None:
        file_menu = self.menuBar().addMenu("&File")
        edit_menu = self.menuBar().addMenu("&Edit")
        self.new_action = file_menu.addAction("&New")
        self.open_action = file_menu.addAction("&Open…")
        self.save_action = file_menu.addAction("&Save")
        self.save_as_action = file_menu.addAction("Save &As…")
        file_menu.addSeparator()
        self.exit_action = file_menu.addAction("E&xit")
        self.undo_action = edit_menu.addAction("&Undo")
        self.redo_action = edit_menu.addAction("&Redo")

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
        self.exit_action.triggered.connect(self.close)
        self.undo_action.triggered.connect(self.undo)
        self.redo_action.triggered.connect(self.redo)
        self.statusBar().showMessage("Ready")

    def _refresh_document(
        self,
        *,
        request_render: bool,
        refresh_properties: bool = True,
        reset_ramp_selection: bool = False,
    ) -> None:
        recipe = self.document.recipe
        if self._selected_instance_id is None or not self._contains_instance(
            recipe, self._selected_instance_id
        ):
            self._selected_instance_id = recipe.source.instance_id if recipe.source else None
        self.pipeline_panel.set_recipe(recipe, self._selected_instance_id)
        self.color_ramp_editor.set_ramp(
            recipe.color_ramp,
            reset_selection=reset_ramp_selection,
        )
        if refresh_properties:
            self._refresh_property_editor(recipe)
        self._update_title_and_actions()
        if request_render:
            self._request_render()

    @staticmethod
    def _contains_instance(recipe: ProjectRecipe, instance_id: str) -> bool:
        instances = [recipe.source, *recipe.transforms]
        return any(item is not None and item.instance_id == instance_id for item in instances)

    def _refresh_property_editor(self, recipe: ProjectRecipe) -> None:
        instance = None
        if recipe.source is not None and recipe.source.instance_id == self._selected_instance_id:
            instance = recipe.source
        else:
            instance = next(
                (
                    item
                    for item in recipe.transforms
                    if item.instance_id == self._selected_instance_id
                ),
                None,
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
        recipe.color_ramp = color_ramp
        self._commit_recipe(recipe, self._selected_instance_id)

    def _preview_color_ramp(self, color_ramp: ColorRamp) -> None:
        recipe = self.document.recipe
        recipe.color_ramp = color_ramp
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
        self.statusBar().showMessage("Ready", 3000)

    def _commit_recipe(
        self,
        recipe: ProjectRecipe,
        selected_id: str | None = None,
        *,
        refresh_properties: bool = True,
    ) -> None:
        try:
            self.document.commit(recipe)
        except Exception as exc:
            self.statusBar().showMessage(f"Edit rejected: {exc}", 5000)
            return
        if selected_id is not None:
            self._selected_instance_id = selected_id
        self._refresh_document(
            request_render=True,
            refresh_properties=refresh_properties,
        )

    def _source_changed(self, operation_id: str) -> None:
        recipe = self.document.recipe
        if recipe.source is not None and recipe.source.operation_id == operation_id:
            return
        definition = REGISTRY.get(operation_id)
        if definition.operation_type != OperationType.GENERATOR:
            return
        instance_id = recipe.source.instance_id if recipe.source else "source"
        recipe.source = OperationInstance(
            instance_id,
            operation_id,
            definition.version,
            parameters={spec.identifier: spec.default for spec in definition.parameter_specs},
        )
        self._commit_recipe(recipe, instance_id)

    def _transform_added(self, operation_id: str) -> None:
        recipe = self.document.recipe
        definition = REGISTRY.get(operation_id)
        if definition.operation_type != OperationType.TRANSFORM:
            return
        instance_id = f"transform-{uuid.uuid4().hex[:12]}"
        recipe.transforms.append(
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
        old_index = next(
            (
                index
                for index, item in enumerate(recipe.transforms)
                if item.instance_id == instance_id
            ),
            None,
        )
        if old_index is None:
            return
        del recipe.transforms[old_index]
        selected_id = recipe.source.instance_id if recipe.source else None
        if recipe.transforms:
            selected_id = recipe.transforms[min(old_index, len(recipe.transforms) - 1)].instance_id
        self._commit_recipe(recipe, selected_id)

    def _transform_moved(self, instance_id: str, target_index: int) -> None:
        recipe = self.document.recipe
        old_index = next(
            (
                index
                for index, item in enumerate(recipe.transforms)
                if item.instance_id == instance_id
            ),
            None,
        )
        if old_index is None or not 0 <= target_index < len(recipe.transforms):
            return
        item = recipe.transforms.pop(old_index)
        recipe.transforms.insert(target_index, item)
        self._commit_recipe(recipe, instance_id)

    def _transform_enabled(self, instance_id: str, enabled: bool) -> None:
        recipe = self.document.recipe
        instance = next(
            (item for item in recipe.transforms if item.instance_id == instance_id),
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
        instance = next(
            (
                item
                for item in [recipe.source, *recipe.transforms]
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
        self._selected_instance_id = recipe.source.instance_id if recipe.source else None
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
        self._selected_instance_id = recipe.source.instance_id if recipe.source else None
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
        event.accept()


def build_main_window(recipe: ProjectRecipe | None = None) -> MainWindow:
    return MainWindow(recipe)


def main() -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    window = build_main_window()
    window.show()
    return app.exec()
