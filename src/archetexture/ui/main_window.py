from __future__ import annotations

import copy
import re
import sys
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from PySide6.QtCore import QObject, QSettings, Qt, Signal
from PySide6.QtGui import QActionGroup, QColor, QKeySequence, QPalette
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSplitter,
    QStyleFactory,
    QTabWidget,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from archetexture import __version__
from archetexture.color.ramp import ColorRamp
from archetexture.core.assets import AssetReference, RenderContext
from archetexture.core.document import DocumentController
from archetexture.core.material_starters import create_material_starter
from archetexture.core.operations import OperationType
from archetexture.core.parameters import (
    ControlFieldBinding,
    ControlFieldMapping,
    ParameterSpec,
    ParameterType,
)
from archetexture.core.pipeline_types import pipeline_output_type, valid_transform_chain
from archetexture.core.recipe import (
    ControlFieldRecipe,
    LayerRecipe,
    MaterialOutputRecipe,
    OperationInstance,
    ProjectRecipe,
)
from archetexture.core.registry import REGISTRY
from archetexture.core.seamlessness import recipe_seamlessness
from archetexture.core.validation import ValidationError, ensure_valid_recipe
from archetexture.export.coordinator import ExportCoordinator, ExportOutcome
from archetexture.export.image_export import ImageExporter
from archetexture.preview.bindings import PreviewMaterialBinding
from archetexture.preview.gl_viewport import MaterialGLViewport
from archetexture.preview.snapshot import PreviewSnapshotBuilder
from archetexture.render.coordinator import RenderCoordinator, RenderOutcome
from archetexture.render.engine import RenderEngine
from archetexture.render.session import RenderSession
from archetexture.ui.binding_dialog import BindingDialog
from archetexture.ui.color_ramp_editor import ColorRampEditor
from archetexture.ui.control_fields_editor import ControlFieldsEditor
from archetexture.ui.export_image_dialog import ExportImageDialog
from archetexture.ui.export_texture_set_dialog import ExportTextureSetDialog
from archetexture.ui.layers_panel import LayersPanel
from archetexture.ui.material_starter_dialog import MaterialStarterDialog
from archetexture.ui.pipeline_panel import PipelinePanel
from archetexture.ui.preview_controls import PreviewControls
from archetexture.ui.project_settings_dialog import ProjectSettingsDialog
from archetexture.ui.property_editor import PropertyEditor
from archetexture.ui.simple_material_panel import SimpleMaterialPanel
from archetexture.ui.theme import palette_for_mode, theme_stylesheet
from archetexture.ui.viewport import TextureViewport


class _RenderBridge(QObject):
    completed = Signal(object)


class _ExportBridge(QObject):
    completed = Signal(object)
    progress = Signal(str)


class _PreviewBridge(QObject):
    completed = Signal(object)


class MainWindow(QMainWindow):
    def __init__(self, recipe: ProjectRecipe | None = None, parent=None):
        application = QApplication.instance() or QApplication(sys.argv)
        super().__init__(parent)
        self._application = application
        self.document = DocumentController(recipe)
        self._selected_output_id = self.document.recipe.outputs[0].output_id
        self._selected_layer_id = self._layers_for(self.document.recipe)[0].layer_id
        self._selected_instance_id: str | None = None
        self._selected_control_field_id: str | None = None
        self._closing = False
        self._export_status_text: str | None = None
        self._latest_render_result = None
        self._latest_displayed_request_id: int | None = None
        self.preview_binding = PreviewMaterialBinding()
        self._preview_request_id = 0
        self._preview_executor = ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="archetexture-preview"
        )
        self.render_session = RenderSession()
        render_engine = RenderEngine(session=self.render_session)
        self.preview_builder = PreviewSnapshotBuilder(render_engine)
        self._export_bridge = _ExportBridge(self)
        self.export_coordinator = ExportCoordinator(
            exporter=ImageExporter(engine=render_engine),
            on_complete=self._export_bridge.completed.emit,
        )
        self._export_bridge.completed.connect(
            self._on_export_complete, Qt.ConnectionType.QueuedConnection
        )
        self._export_bridge.progress.connect(self.statusBar().showMessage)
        self._render_bridge = _RenderBridge(self)
        self.render_coordinator = RenderCoordinator(
            engine=render_engine,
            on_complete=self._render_bridge.completed.emit,
        )
        self._render_bridge.completed.connect(
            self._on_render_complete,
            Qt.ConnectionType.QueuedConnection,
        )
        self._preview_bridge = _PreviewBridge(self)
        self._preview_bridge.completed.connect(
            self._on_preview_complete, Qt.ConnectionType.QueuedConnection
        )

        self.setWindowTitle("ArcheTexture")
        self.resize(1360, 850)
        self.pipeline_panel = PipelinePanel(self)
        self.layers_panel = LayersPanel(self)
        self.viewport = TextureViewport(self)
        self.preview_viewport = MaterialGLViewport(self)
        self.preview_controls = PreviewControls(self)
        self.simple_material_panel = SimpleMaterialPanel(self)
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
        self.property_editor.assetBrowseRequested.connect(self._browse_main_asset)
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
        self.control_fields_editor.property_editor.assetBrowseRequested.connect(
            self._browse_control_asset
        )
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
        self.layers_panel.maskChanged.connect(self._layer_mask_changed)
        self.layers_panel.maskEditRequested.connect(self._edit_layer_mask)
        self.layers_panel.addMaskRequested.connect(self._add_layer_mask)
        self.layers_panel.addImageMaskRequested.connect(self._add_image_layer_mask)
        self.layers_panel.maskNavigateRequested.connect(self._navigate_to_layer_mask)
        self.layers_panel.copyToOutputRequested.connect(self._copy_layer_to_output)
        self.layers_panel.moveToOutputRequested.connect(self._move_layer_to_output)
        self.layers_panel.createOutputRequested.connect(self._create_output_from_layer)
        self.simple_material_panel.channelSelected.connect(self._select_simple_channel)
        self.simple_material_panel.controlParameterChanged.connect(self._simple_control_changed)

        center_panel = QWidget(self)
        center_layout = QVBoxLayout(center_panel)
        center_layout.setContentsMargins(0, 0, 0, 0)
        center_layout.setSpacing(4)
        view_row = QHBoxLayout()
        view_row.setContentsMargins(8, 2, 8, 0)
        view_row.addWidget(QLabel("Workspace:"))
        self.workspace_mode_combo = QComboBox(center_panel)
        self.workspace_mode_combo.setObjectName("workspace-mode-selector")
        self.workspace_mode_combo.addItem("2D Texture", "2D Texture")
        self.workspace_mode_combo.addItem("3D Material", "3D Material")
        view_row.addWidget(self.workspace_mode_combo)
        self.edit_output_label = QLabel("Edit Output:", center_panel)
        view_row.addWidget(self.edit_output_label)
        self.output_selector = QComboBox(center_panel)
        self.output_selector.setObjectName("material-output-selector")
        view_row.addWidget(self.output_selector)
        self.output_selector.currentIndexChanged.connect(self._output_selection_changed)
        self.manage_outputs_button = QPushButton("Manage Outputs…", center_panel)
        self.manage_outputs_button.clicked.connect(self._manage_outputs)
        view_row.addWidget(self.manage_outputs_button)
        self.viewport_mode_label = QLabel("2D View:", center_panel)
        view_row.addWidget(self.viewport_mode_label)
        self.viewport_mode_combo = QComboBox(center_panel)
        self.viewport_mode_combo.setObjectName("viewport-display-mode")
        for label, mode in (
            ("Single", "single"),
            ("Tile 3×3", "tile_3x3"),
            ("Seam Check", "seam_check"),
            ("Mask Preview", "mask_preview"),
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
        self.preview_mode_label = QLabel("Preview Mode:", center_panel)
        self.preview_mode_combo = self.preview_controls.mode
        self.preview_mode_combo.setObjectName("preview-mode-selector")
        self.preview_mode_combo.setToolTip(
            "Choose the combined material view or inspect an individual material channel."
        )
        self.preview_mode_label.hide()
        self.seamlessness_label = QLabel("Seamless: Unknown")
        self.seamlessness_label.setObjectName("seamlessness-status")
        self.seamlessness_label.setToolTip(
            "Conservative status for enabled, visible layer sources and transforms."
        )
        view_row.addWidget(self.seamlessness_label)
        view_row.addStretch(1)
        center_layout.addLayout(view_row)
        self.context_breadcrumb = QLabel(center_panel)
        self.context_breadcrumb.setObjectName("editing-context-breadcrumb")
        self.context_breadcrumb.setContentsMargins(10, 2, 8, 2)
        center_layout.addWidget(self.context_breadcrumb)
        self.preview_mode_indicator = QLabel("MATERIAL PREVIEW", center_panel)
        self.preview_mode_indicator.setObjectName("preview-mode-indicator")
        self.preview_mode_indicator.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview_mode_indicator.setVisible(False)
        center_layout.addWidget(self.preview_mode_indicator)
        from PySide6.QtWidgets import QStackedWidget

        self.workspace_stack = QStackedWidget(center_panel)
        self.workspace_stack.addWidget(self.viewport)
        self.workspace_stack.addWidget(self.preview_viewport)
        self.preview_unavailable_label = QLabel("Initializing 3D material preview…", center_panel)
        self.preview_unavailable_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview_unavailable_label.setObjectName("preview-unavailable-message")
        self.workspace_stack.addWidget(self.preview_unavailable_label)
        center_layout.addWidget(self.workspace_stack, 1)
        center_layout.addWidget(self.color_ramp_editor, 0)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        left_panel = QWidget(self)
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.addWidget(self.simple_material_panel.channel_widget, 0)
        left_layout.addWidget(self.layers_panel, 1)
        left_layout.addWidget(self.pipeline_panel, 1)
        splitter.addWidget(left_panel)
        splitter.addWidget(center_panel)
        self.right_tabs = QTabWidget(self)
        self.simple_controls_scroll = QScrollArea(self)
        self.simple_controls_scroll.setWidgetResizable(True)
        self.simple_controls_scroll.setWidget(self.simple_material_panel.controls_widget)
        self.right_tabs.addTab(self.simple_controls_scroll, "Simple")
        self.advanced_tabs = QTabWidget(self)
        self.advanced_tabs.setObjectName("advanced-inspector-tabs")
        self.advanced_tabs.addTab(self.control_fields_editor, "Control Fields")
        self.advanced_tabs.setTabToolTip(
            0,
            "Reusable value fields that drive layer parameters, masks, and derived outputs.",
        )
        self.preview_controls_scroll = QScrollArea(self)
        self.preview_controls_scroll.setWidgetResizable(True)
        self.preview_controls_scroll.setWidget(self.preview_controls)
        self.advanced_tabs.addTab(self.preview_controls_scroll, "View Settings")
        self.right_tabs.addTab(self.advanced_tabs, "Advanced")
        self.right_tabs.setObjectName("right-side-tabs")
        self.right_tabs.setCurrentIndex(0)
        self.right_tabs.setMinimumWidth(285)
        self.right_tabs.currentChanged.connect(self._authoring_mode_changed)
        self.inspector_splitter = QSplitter(Qt.Orientation.Vertical, self)
        self.property_editor_scroll = QScrollArea(self)
        self.property_editor_scroll.setWidgetResizable(True)
        self.property_editor_scroll.setWidget(self.property_editor)
        self.property_editor_scroll.setMinimumWidth(270)
        self.inspector_splitter.addWidget(self.property_editor_scroll)
        self.inspector_splitter.addWidget(self.right_tabs)
        self.inspector_splitter.setStretchFactor(0, 3)
        self.inspector_splitter.setStretchFactor(1, 2)
        self.inspector_splitter.setSizes([470, 340])
        splitter.addWidget(self.inspector_splitter)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setStretchFactor(2, 0)
        splitter.setSizes([250, 820, 300])
        self.setCentralWidget(splitter)
        self.workspace_mode_combo.currentIndexChanged.connect(self._workspace_mode_changed)
        self.preview_controls.set_recipe(self.document.recipe, self.preview_binding)
        self._restore_preview_settings()
        self.preview_controls.settingChanged.connect(self._preview_control_changed)
        self.preview_controls.backgroundColorChanged.connect(self._preview_background_color_changed)
        self.preview_controls.saveRequested.connect(self._save_preview_image)
        self.preview_controls.copyRequested.connect(self._copy_preview_image)
        self.preview_controls.resetRequested.connect(self._reset_preview)
        self.preview_viewport.initializationChanged.connect(self._preview_gl_initialized)
        self.preview_viewport.viewChanged.connect(self._preview_camera_changed)

        self._create_actions()
        self._selected_instance_id = self._layer().source.instance_id
        self._configure_theme()
        self._refresh_document(request_render=True)
        self._authoring_mode_changed(self.right_tabs.currentIndex())

    def _create_actions(self) -> None:
        file_menu = self.menuBar().addMenu("&File")
        edit_menu = self.menuBar().addMenu("&Edit")
        view_menu = self.menuBar().addMenu("&View")
        help_menu = self.menuBar().addMenu("&Help")
        self.about_action = help_menu.addAction("About ArcheTexture")
        self.about_action.triggered.connect(self._show_about)
        appearance_menu = view_menu.addMenu("&Appearance")
        self.new_action = file_menu.addAction("&New")
        self.new_from_material_action = file_menu.addAction("New from Material…")
        self.open_action = file_menu.addAction("&Open…")
        self.save_action = file_menu.addAction("&Save")
        self.save_as_action = file_menu.addAction("Save &As…")
        self.export_action = file_menu.addAction("Export PNG…")
        self.export_texture_set_action = file_menu.addAction("Export Texture Set…")
        self.save_preview_action = file_menu.addAction("Save Preview Image…")
        self.import_image_action = file_menu.addAction("Import Image as Layer…")
        self.export_action.setShortcut("Ctrl+Shift+E")
        file_menu.addSeparator()
        self.exit_action = file_menu.addAction("E&xit")
        self.undo_action = edit_menu.addAction("&Undo")
        self.redo_action = edit_menu.addAction("&Redo")
        edit_menu.addSeparator()
        self.project_settings_action = edit_menu.addAction("Project Settings…")
        self.project_settings_action.setShortcut(QKeySequence("Ctrl+Shift+P"))
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
        self.new_from_material_action.triggered.connect(self.new_from_material)
        self.open_action.triggered.connect(lambda: self.open_project())
        self.save_action.triggered.connect(lambda: self.save_project())
        self.save_as_action.triggered.connect(lambda: self.save_project(save_as=True))
        self.export_action.triggered.connect(self.export_png)
        self.export_texture_set_action.triggered.connect(self.export_texture_set)
        self.save_preview_action.triggered.connect(lambda: self.preview_controls._save())
        self.import_image_action.triggered.connect(self._import_image_as_layer)
        self.exit_action.triggered.connect(self.close)
        self.undo_action.triggered.connect(self.undo)
        self.redo_action.triggered.connect(self.redo)
        self.project_settings_action.triggered.connect(self._show_project_settings)
        self.statusBar().showMessage("Ready")
        self.project_status_label = QLabel(self)
        self.project_status_label.setObjectName("project-status")
        self.project_status_label.setMargin(4)
        self.project_status_label.setToolTip("Current project canvas size and global seed")
        self.statusBar().addPermanentWidget(self.project_status_label)

    def _show_about(self) -> None:
        QMessageBox.about(
            self,
            "About ArcheTexture",
            f"<b>ArcheTexture {__version__}</b><br>"
            "Procedural texture generation and transformation workstation.<br>"
            "GNU General Public License version 3.0 only (GPL-3.0-only).<br>"
            '<a href="https://www.gnu.org/licenses/gpl-3.0.html">License text</a><br>'
            '<a href="https://github.com/MithradatesEupator/ArcheTexture">Project repository</a>',
        )

    def _configure_theme(self) -> None:
        if not hasattr(self._application, "_archetexture_system_style_name"):
            self._application._archetexture_system_style_name = (
                self._application.style().objectName()
            )
            self._application._archetexture_system_palette = QPalette(
                self._application.style().standardPalette()
            )
        self._system_style_name = self._application._archetexture_system_style_name
        self._system_palette = QPalette(self._application._archetexture_system_palette)
        settings = self._theme_settings()
        mode = settings.value("appearance/theme", "dark")
        self._set_theme(mode if mode in {"system", "light", "dark"} else "dark", persist=False)

    def _set_theme(self, mode: str, *, persist: bool = True) -> None:
        if mode not in {"system", "light", "dark"}:
            mode = "dark"
        if mode == "system":
            system_style = QStyleFactory.create(self._system_style_name)
            if system_style is not None:
                self._application.setStyle(system_style)
            self._application.setPalette(self._system_palette)
        else:
            fusion_style = QStyleFactory.create("Fusion")
            if fusion_style is not None:
                self._application.setStyle(fusion_style)
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

    def _workspace_mode_changed(self, index: int) -> None:
        is_3d = self.workspace_mode_combo.itemData(index) == "3D Material"
        self.preview_mode_label.hide()
        self.preview_mode_indicator.setVisible(is_3d)
        self.viewport_mode_label.setVisible(not is_3d)
        self.viewport_mode_combo.setVisible(not is_3d)
        if not is_3d:
            self._preview_request_id += 1
        self.workspace_stack.setCurrentIndex(
            (2 if self.preview_viewport._gl_error else 1) if is_3d else 0
        )
        if is_3d:
            # A new 3D workspace always begins in the complete material view.
            self.preview_controls.mode.setCurrentText("Material")
            self.preview_controls.set_recipe(self.document.recipe, self.preview_binding)
            self._apply_preview_settings()
            self.preview_viewport.set_mesh(
                self.preview_controls.mesh.currentText(),
                self.preview_controls.quality.currentText(),
            )
            self._update_preview_mode_indicator()
            self._request_preview()
        settings = self._theme_settings()
        settings.setValue("preview/workspace", "3D Material" if is_3d else "2D Texture")
        settings.sync()

    def _authoring_mode_changed(self, index: int) -> None:
        simple = index == 0
        self.simple_material_panel.channel_widget.setVisible(simple)
        self.edit_output_label.setVisible(not simple)
        self.output_selector.setVisible(not simple)
        self.manage_outputs_button.setVisible(not simple)
        self.simple_material_panel.set_recipe(self.document.recipe, self._selected_output_id)
        self._refresh_document(request_render=False, refresh_properties=False)

    def _show_control_fields(self) -> None:
        self.right_tabs.setCurrentWidget(self.advanced_tabs)
        self.advanced_tabs.setCurrentWidget(self.control_fields_editor)

    def _select_simple_channel(self, semantic: str) -> None:
        outputs = SimpleMaterialPanel.outputs_for_semantic(self.document.recipe, semantic)
        if not outputs:
            return
        index = self.output_selector.findData(outputs[0].output_id)
        if index >= 0:
            self.output_selector.setCurrentIndex(index)

    def _simple_control_changed(
        self, control_name: str, instance_id: str, parameter_id: str, value
    ) -> None:
        recipe = copy.deepcopy(self.document.recipe)
        control = recipe.control_fields.get(control_name)
        if control is None:
            return
        instance = (
            control.source
            if control.source.instance_id == instance_id
            else next(
                (item for item in control.transforms if item.instance_id == instance_id), None
            )
        )
        if instance is None or instance.parameters.get(parameter_id) == value:
            return
        instance.parameters[parameter_id] = value
        self._commit_recipe(recipe, control_field_id=control_name)

    def _preview_gl_initialized(self, available: bool, message: str) -> None:
        if available:
            self.preview_unavailable_label.setText("")
            if self.workspace_mode_combo.currentData() == "3D Material":
                self.workspace_stack.setCurrentWidget(self.preview_viewport)
                self._request_preview()
        else:
            self.preview_mode_indicator.setText("3D PREVIEW UNAVAILABLE")
            self.preview_unavailable_label.setText(
                message or self.preview_viewport.unavailable_message
            )
            if self.workspace_mode_combo.currentData() == "3D Material":
                self.workspace_stack.setCurrentWidget(self.preview_unavailable_label)

    def _preview_camera_changed(self) -> None:
        if self.preview_controls.view.currentText() != "Orbit":
            self.preview_controls.view.blockSignals(True)
            self.preview_controls.view.setCurrentText("Orbit")
            self.preview_controls.view.blockSignals(False)

    def _update_preview_mode_indicator(self) -> None:
        inspection = self.preview_viewport.inspection
        text = (
            "MATERIAL PREVIEW" if inspection == "Material" else f"{inspection.upper()} INSPECTION"
        )
        self.preview_mode_indicator.setText(text)
        self.preview_mode_indicator.setToolTip(f"3D shader mode: {inspection}")

    def _preview_background_color_changed(self, color: str) -> None:
        self.preview_controls.custom_background = QColor(color)
        self._apply_preview_settings()

    def _apply_preview_settings(self) -> None:
        state = self.preview_controls.view_state()
        view = self.preview_viewport
        view.inspection = state["inspection"]
        self._update_preview_mode_indicator()
        view.mesh_type, view.quality = state["mesh"], state["quality"]
        view.lighting, view.background, view.exposure = (
            state["lighting"],
            state["background"],
            state["exposure"],
        )
        view.custom_background = QColor(state["custom_background"])
        view.rig_rotation = state["rig_rotation"]
        view.key_intensity = state["key_intensity"]
        view.fill_intensity = state["fill_intensity"]
        view.rim_intensity = state["rim_intensity"]
        view.ambient_intensity = state["ambient_intensity"]
        view.normal_strength, view.directx_normal = state["normal_strength"], state["directx"]
        view.tile_u, view.tile_v, view.rotation_uv = (
            state["tile_u"],
            state["tile_v"],
            state["rotation"],
        )
        view.alpha_mode, view.clip_threshold = state["alpha"], state["clip"]
        view.wire_overlay, view.backface_culling = state["wire"], state["cull"]
        view.camera.projection, view.camera.fov = state["projection"], state["fov"]
        view.camera.auto_rotate, view.camera.auto_rotate_speed = (
            state["auto_rotate"],
            state["auto_speed"],
        )
        if state["view"] != "Orbit":
            view.camera.set_view(state["view"])
        settings = self._theme_settings()
        for key, value in state.items():
            settings.setValue(f"preview/{key}", value)
        settings.sync()
        view.update()

    def _restore_preview_settings(self) -> None:
        settings = self._theme_settings()
        saved_bindings = settings.value("preview/bindings", {})
        if isinstance(saved_bindings, dict):
            self.preview_binding.overrides = {
                str(key): str(value)
                for key, value in saved_bindings.items()
                if value not in {None, ""}
            }
        self.preview_controls.set_recipe(self.document.recipe, self.preview_binding)
        state = self.preview_controls.view_state()
        for key in state:
            if key in {"mesh", "quality", "inspection"}:
                continue
            saved = settings.value(f"preview/{key}", None)
            if saved is None:
                continue
            widget = {
                "mesh": self.preview_controls.mesh,
                "quality": self.preview_controls.quality,
                "inspection": self.preview_controls.mode,
                "projection": self.preview_controls.projection,
                "lighting": self.preview_controls.lighting,
                "background": self.preview_controls.background,
                "alpha": self.preview_controls.alpha,
            }.get(key)
            if widget is not None:
                widget.setCurrentText(str(saved))
            elif key in {"resolution", "tile_u", "tile_v"}:
                combo = {
                    "resolution": self.preview_controls.resolution,
                    "tile_u": self.preview_controls.tile_u,
                    "tile_v": self.preview_controls.tile_v,
                }[key]
                index = combo.findData(int(saved) if key == "resolution" else float(saved))
                if index >= 0:
                    combo.setCurrentIndex(index)
            elif key == "rotation":
                self.preview_controls.rotation.setCurrentIndex((0, 90, 180, 270).index(int(saved)))
            elif key in {"fov", "exposure", "normal_strength", "clip", "auto_speed"}:
                spin = {
                    "fov": self.preview_controls.fov,
                    "exposure": self.preview_controls.exposure,
                    "normal_strength": self.preview_controls.normal_strength,
                    "clip": self.preview_controls.clip,
                    "auto_speed": self.preview_controls.auto_speed,
                }[key]
                spin.setValue(float(saved))
            elif key in {
                "rig_rotation",
                "key_intensity",
                "fill_intensity",
                "rim_intensity",
                "ambient_intensity",
            }:
                spin = {
                    "rig_rotation": self.preview_controls.rig_rotation,
                    "key_intensity": self.preview_controls.key_intensity,
                    "fill_intensity": self.preview_controls.fill_intensity,
                    "rim_intensity": self.preview_controls.rim_intensity,
                    "ambient_intensity": self.preview_controls.ambient_intensity,
                }[key]
                spin.setValue(float(saved))
            elif key == "custom_background":
                self.preview_controls.custom_background = QColor(str(saved))
            elif key in {"directx", "wire", "cull", "auto_rotate"}:
                if key == "directx":
                    self.preview_controls.normal_convention.setCurrentText(
                        "DirectX" if str(saved).lower() == "true" else "OpenGL"
                    )
                else:
                    {
                        "wire": self.preview_controls.wire,
                        "cull": self.preview_controls.cull,
                        "auto_rotate": self.preview_controls.auto_rotate,
                    }[key].setChecked(str(saved).lower() == "true")
        workspace = settings.value("preview/workspace", "2D Texture")
        index = self.workspace_mode_combo.findData(workspace)
        if index >= 0:
            self.workspace_mode_combo.setCurrentIndex(index)
        self.preview_controls.mesh.setCurrentText("UV Sphere")
        self.preview_controls.quality.setCurrentText("High")
        self.preview_controls.mode.setCurrentText("Material")
        if self.preview_controls.view.currentText() == "Reset / Frame":
            self.preview_controls.view.setCurrentText("Orbit")

    def _preview_control_changed(self, kind: str) -> None:
        if kind.startswith("binding:"):
            self.preview_binding.overrides = self.preview_controls.binding_overrides()
            settings = self._theme_settings()
            settings.setValue("preview/bindings", self.preview_binding.overrides)
            settings.sync()
            self.preview_controls.set_recipe(self.document.recipe, self.preview_binding)
            self._request_preview()
        elif kind == "inspection":
            self._apply_preview_settings()
            self._request_preview()
        else:
            self._apply_preview_settings()
            if kind == "mesh":
                self.preview_viewport.set_mesh(
                    self.preview_controls.mesh.currentText(),
                    self.preview_controls.quality.currentText(),
                )
        if kind in {"mesh", "view"}:
            self.statusBar().showMessage("Preview updated", 1200)

    def _request_preview(self) -> None:
        if (
            self._closing
            or self.workspace_mode_combo.currentData() != "3D Material"
            or not self.preview_viewport.available
        ):
            return
        state = self.preview_controls.view_state()
        self._preview_request_id += 1
        request_id = self._preview_request_id
        recipe = copy.deepcopy(self.document.recipe)
        if state["resolution"]:
            width = height = state["resolution"]
        else:
            width, height = recipe.width, recipe.height
        binding = copy.deepcopy(self.preview_binding)
        inspection = state["inspection"]
        project_path = self.document.project_path

        def render_snapshot():
            try:
                result = self.preview_builder.build(
                    recipe,
                    binding,
                    request_id,
                    width,
                    height,
                    inspection=inspection,
                    render_context=RenderContext(project_path),
                )
                return request_id, result, None
            except Exception as exc:
                return request_id, None, exc

        future = self._preview_executor.submit(render_snapshot)
        future.add_done_callback(
            lambda completed: (
                self._preview_bridge.completed.emit(completed.result())
                if not completed.cancelled() and not self._closing
                else None
            )
        )
        self.statusBar().showMessage("Updating 3D material preview…")

    def _on_preview_complete(self, outcome) -> None:
        request_id, snapshot, error = outcome
        if self._closing or request_id != self._preview_request_id:
            return
        if error is not None:
            self.preview_unavailable_label.setText(f"Preview render failed: {error}")
            self.statusBar().showMessage(f"Preview render failed: {error}", 5000)
            return
        self.preview_viewport.set_snapshot(snapshot)
        self.statusBar().showMessage("3D preview ready", 2000)

    def _save_preview_image(self, path: str) -> None:
        if not self.preview_viewport.save_preview_image(path):
            QMessageBox.warning(
                self, "Preview unavailable", "The OpenGL preview could not be captured."
            )

    def _copy_preview_image(self) -> None:
        if not self.preview_viewport.copy_preview_image():
            QMessageBox.warning(
                self, "Preview unavailable", "The OpenGL preview could not be copied."
            )

    def _reset_preview(self) -> None:
        self.preview_viewport.reset_preview()
        self.preview_controls.mesh.setCurrentText("UV Sphere")
        self.preview_controls.quality.setCurrentText("High")
        self.preview_controls.mode.setCurrentText("Material")
        self.preview_controls.lighting.setCurrentText("Neutral Studio")
        self.preview_controls.background.setCurrentText("Dark Neutral")
        self.preview_controls.custom_background = QColor("#35363a")
        self.preview_controls.projection.setCurrentText("Perspective")
        self.preview_controls.exposure.setValue(1)
        self.preview_controls.tile_u.setCurrentIndex(self.preview_controls.tile_u.findData(1.0))
        self.preview_controls.tile_v.setCurrentIndex(self.preview_controls.tile_v.findData(1.0))
        self.preview_controls.rotation.setCurrentIndex(0)
        self.preview_controls.normal_strength.setValue(1.0)
        self.preview_controls.rig_rotation.setValue(0)
        self.preview_controls.key_intensity.setValue(2.5)
        self.preview_controls.fill_intensity.setValue(0.6)
        self.preview_controls.rim_intensity.setValue(1.0)
        self.preview_controls.ambient_intensity.setValue(1.0)
        self.preview_controls.normal_convention.setCurrentIndex(0)
        self.preview_controls.alpha.setCurrentText("Opaque")
        self.preview_controls.clip.setValue(0.5)
        self.preview_controls.wire.setChecked(False)
        self.preview_controls.cull.setChecked(False)
        self.preview_controls.auto_rotate.setChecked(False)
        self._apply_preview_settings()

    def _layer(self, recipe: ProjectRecipe | None = None) -> LayerRecipe:
        recipe = recipe or self.document.recipe
        layers = self._layers_for(recipe)
        layer = next((item for item in layers if item.layer_id == self._selected_layer_id), None)
        if layer is None:
            layer = layers[0] if layers else None
            if layer is None:
                raise ValueError("The selected output has no editable layer")
            self._selected_layer_id = layer.layer_id
        return layer

    def _selected_output(self, recipe: ProjectRecipe | None = None) -> MaterialOutputRecipe:
        recipe = recipe or self.document.recipe
        for output in recipe.outputs:
            if output.output_id == self._selected_output_id:
                return output
        self._selected_output_id = recipe.outputs[0].output_id
        return recipe.outputs[0]

    def _output_selection_changed(self, index: int) -> None:
        output_id = self.output_selector.itemData(index)
        if not output_id or output_id == self._selected_output_id:
            return
        self._selected_output_id = str(output_id)
        output = self._selected_output()
        self._selected_layer_id = output.layers[0].layer_id if output.layers else ""
        self._selected_instance_id = output.layers[0].source.instance_id if output.layers else None
        self._refresh_document(request_render=True, reset_ramp_selection=True)

    def _manage_outputs(self) -> None:
        from archetexture.ui.output_manager import OutputManagerDialog

        recipe = self.document.recipe
        dialog = OutputManagerDialog(recipe, self._selected_output_id, self)
        if dialog.exec() != dialog.DialogCode.Accepted:
            return
        self._selected_output_id = dialog.selected_output_id
        self._selected_layer_id = ""
        self._selected_instance_id = None
        self._commit_recipe(dialog.recipe, refresh_properties=True)

    def _layers_for(self, recipe: ProjectRecipe) -> list[LayerRecipe]:
        if not recipe.outputs:
            return []
        output = next(
            (item for item in recipe.outputs if item.output_id == self._selected_output_id),
            recipe.outputs[0],
        )
        return output.layers

    @staticmethod
    def _all_layers(recipe: ProjectRecipe) -> list[LayerRecipe]:
        return [layer for output in recipe.outputs for layer in output.layers]

    def _refresh_document(
        self,
        *,
        request_render: bool,
        refresh_properties: bool = True,
        reset_ramp_selection: bool = False,
    ) -> None:
        recipe = self.document.recipe
        output = self._selected_output(recipe)
        layer = self._layer(recipe)
        self.seamlessness_label.setText(
            f"{output.name} · {output.value_type.title()} · Seamless: "
            f"{recipe_seamlessness(recipe, output_id=output.output_id)}"
        )
        self.output_selector.blockSignals(True)
        self.output_selector.clear()
        for item in recipe.outputs:
            self.output_selector.addItem(f"{item.name} · {item.value_type.title()}", item.output_id)
        self.output_selector.setCurrentIndex(
            max(0, self.output_selector.findData(output.output_id))
        )
        self.output_selector.blockSignals(False)
        if self._selected_instance_id is None or not self._contains_instance(
            recipe, self._selected_instance_id
        ):
            self._selected_instance_id = layer.source.instance_id if layer.source else None
        self.layers_panel.set_recipe(recipe, self._selected_layer_id, output.output_id)
        descriptor = self._layer_descriptor(layer)
        if self.right_tabs.currentIndex() == 0:
            channel = dict(SimpleMaterialPanel.CHANNELS).get(output.semantic)
            if channel:
                descriptor = f"{channel} — {descriptor}"
        self.layers_panel.set_pipeline_descriptor(descriptor)
        source_name = REGISTRY.get(layer.source.operation_id).name
        transform = next(
            (item for item in layer.transforms if item.instance_id == self._selected_instance_id),
            None,
        )
        selected_name = REGISTRY.get(transform.operation_id).name if transform else source_name
        self.context_breadcrumb.setText(
            f"{output.name}  ›  {layer.name}  ›  {source_name}"
            + (f"  ›  {selected_name}" if transform else "")
        )
        self.context_breadcrumb.setToolTip(self.context_breadcrumb.text())
        mask_index = self.viewport_mode_combo.findData("mask_preview")
        if mask_index >= 0:
            masked = layer.mask is not None
            self.viewport_mode_combo.model().item(mask_index).setEnabled(masked)
            if not masked and self.viewport_mode_combo.currentData() == "mask_preview":
                self.viewport_mode_combo.setCurrentIndex(
                    self.viewport_mode_combo.findData("single")
                )
        self.pipeline_panel.set_recipe(recipe, self._selected_instance_id, layer)
        self.property_editor.set_control_fields(recipe.control_fields)
        self.property_editor.set_material_outputs(recipe, output.output_id)
        self.property_editor.set_project_path(self.document.project_path)
        self.control_fields_editor.set_recipe(recipe, self._selected_control_field_id)
        self.preview_controls.set_recipe(recipe, self.preview_binding)
        self.simple_material_panel.set_recipe(recipe, output.output_id)
        self.control_fields_editor.property_editor.set_project_path(self.document.project_path)
        self._selected_control_field_id = self.control_fields_editor.selected_field_id
        self.color_ramp_editor.set_ramp(
            layer.color_ramp,
            reset_selection=reset_ramp_selection,
            applicable=(
                output.value_type == "color"
                and pipeline_output_type(layer.source, layer.transforms) == "scalar"
            ),
        )
        self.color_ramp_editor.set_context_name(layer.name)
        self.control_fields_editor.set_affected_by(self._control_field_impact_labels(recipe))
        if refresh_properties:
            self._refresh_property_editor(recipe)
        self._update_title_and_actions()
        if request_render:
            self._request_render()
            self._request_preview()

    @staticmethod
    def _contains_instance(recipe: ProjectRecipe, instance_id: str) -> bool:
        instances = [
            instance
            for layer in MainWindow._all_layers(recipe)
            for instance in [layer.source, *layer.transforms]
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
        recipe = self.document.recipe
        self.project_status_label.setText(f"{recipe.width} × {recipe.height} · Seed {recipe.seed}")
        self.undo_action.setEnabled(self.document.can_undo)
        self.redo_action.setEnabled(self.document.can_redo)
        self.save_action.setEnabled(True)

    def _request_render(self, recipe: ProjectRecipe | None = None) -> None:
        if self._closing:
            return
        recipe = recipe or self.document.recipe
        render_recipe = copy.deepcopy(recipe)
        selected = next(
            (item for item in render_recipe.outputs if item.output_id == self._selected_output_id),
            render_recipe.outputs[0],
        )
        self.statusBar().showMessage("Rendering…")
        try:
            self.render_coordinator.request(
                render_recipe,
                width=render_recipe.width,
                height=render_recipe.height,
                render_context=RenderContext(self.document.project_path),
                output_id=selected.output_id,
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
        if (
            self._closing
            or outcome.request_id != self.render_coordinator.latest_request_id
            or (
                self._latest_displayed_request_id is not None
                and outcome.request_id < self._latest_displayed_request_id
            )
        ):
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
        self._latest_render_result = outcome.result
        self._latest_displayed_request_id = outcome.request_id
        self.viewport.set_mask_preview(
            (outcome.result.mask_fields or {}).get(self._selected_layer_id)
        )
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
            recipe = copy.deepcopy(self.document.recipe)
            selected = next(
                item for item in recipe.outputs if item.output_id == self._selected_output_id
            )
            recipe.outputs = [
                selected,
                *(item for item in recipe.outputs if item.output_id != selected.output_id),
            ]
            self.export_coordinator.request(
                recipe,
                destination,
                width=width,
                height=height,
                render_context=RenderContext(self.document.project_path),
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
        self.export_texture_set_action.setEnabled(True)
        self._export_status_text = None
        if outcome.error is not None:
            self.statusBar().showMessage("PNG export failed")
            QMessageBox.critical(self, "Export failed", str(outcome.error))
            return
        if outcome.files:
            self.statusBar().showMessage(f"Exported {len(outcome.files)} texture-set maps", 5000)
        else:
            self.statusBar().showMessage(f"Exported {outcome.destination.name}", 5000)

    def export_texture_set(self, *_args) -> bool:
        dialog = ExportTextureSetDialog(self.document.recipe, self)
        if dialog.exec() != dialog.DialogCode.Accepted:
            return False
        try:
            self.export_coordinator.request_texture_set(
                self.document.recipe,
                dialog.plan,
                render_context=RenderContext(self.document.project_path),
                progress=self._export_bridge.progress.emit,
            )
        except Exception as exc:
            QMessageBox.critical(self, "Texture-set export failed", str(exc))
            return False
        self.export_action.setEnabled(False)
        self.export_texture_set_action.setEnabled(False)
        self._export_status_text = "Exporting texture set…"
        self.statusBar().showMessage(self._export_status_text)
        return True

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

    def _show_project_settings(self, *_args) -> bool:
        dialog = ProjectSettingsDialog(self.document.recipe, self)
        if dialog.exec() != dialog.DialogCode.Accepted:
            return False
        width, height, seed = dialog.proposed_settings
        recipe = self.document.recipe
        if (width, height, seed) == (recipe.width, recipe.height, recipe.seed):
            return False
        recipe.width = width
        recipe.height = height
        recipe.seed = seed
        try:
            ensure_valid_recipe(recipe)
        except ValidationError as exc:
            QMessageBox.warning(self, "Invalid Project Settings", str(exc))
            return False
        self._commit_recipe(recipe)
        return True

    def _source_changed(self, operation_id: str) -> None:
        recipe = self.document.recipe
        layer = self._layer(recipe)
        if layer.source is not None and layer.source.operation_id == operation_id:
            return
        definition = REGISTRY.get(operation_id)
        if definition.operation_type != OperationType.GENERATOR:
            return
        selected_asset = None
        if operation_id in {"generator.image", "generator.image_channel"}:
            path = self._choose_image()
            if not path:
                self._refresh_document(request_render=False)
                return
            selected_asset = self._asset_reference(path)
        instance_id = layer.source.instance_id if layer.source else f"source-{uuid.uuid4().hex[:8]}"
        parameters = {spec.identifier: spec.default for spec in definition.parameter_specs}
        if selected_asset is not None:
            parameters["asset"] = selected_asset
        if definition.output_type == "rgba":
            layer.color_ramp = None
        layer.source = OperationInstance(
            instance_id,
            operation_id,
            definition.version,
            parameters=parameters,
        )
        self._commit_recipe(recipe, instance_id)

    def _transform_added(self, operation_id: str) -> None:
        recipe = self.document.recipe
        layer = self._layer(recipe)
        definition = REGISTRY.get(operation_id)
        if definition.operation_type != OperationType.TRANSFORM:
            return
        instance_id = f"transform-{uuid.uuid4().hex[:12]}"
        candidate = OperationInstance(
            instance_id,
            operation_id,
            definition.version,
            parameters={spec.identifier: spec.default for spec in definition.parameter_specs},
        )
        if not valid_transform_chain(
            layer.source,
            [*layer.transforms, candidate],
            color_ramp_active=layer.color_ramp is not None,
        ):
            return
        layer.transforms.append(candidate)
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
        if not valid_transform_chain(
            self._layer(recipe).source,
            transforms,
            color_ramp_active=self._layer(recipe).color_ramp is not None,
        ):
            return
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
        recipe = self.document.recipe
        self._refresh_property_editor(recipe)
        self._refresh_context_breadcrumb(recipe)

    @staticmethod
    def _layer_descriptor(layer: LayerRecipe) -> str:
        stages = [REGISTRY.get(layer.source.operation_id).name]
        stages.extend(
            REGISTRY.get(item.operation_id).name
            if item.enabled
            else f"{REGISTRY.get(item.operation_id).name} (disabled)"
            for item in layer.transforms
        )
        if layer.color_ramp is not None:
            stages.append("Color Ramp")
        return " → ".join(stages)

    def _refresh_context_breadcrumb(self, recipe: ProjectRecipe) -> None:
        output, layer = self._selected_output(recipe), self._layer(recipe)
        source_name = REGISTRY.get(layer.source.operation_id).name
        selected = next(
            (item for item in layer.transforms if item.instance_id == self._selected_instance_id),
            None,
        )
        text = f"{output.name}  ›  {layer.name}  ›  {source_name}"
        if selected is not None:
            text += f"  ›  {REGISTRY.get(selected.operation_id).name}"
        self.context_breadcrumb.setText(text)
        self.context_breadcrumb.setToolTip(text)

    @staticmethod
    def _control_field_impact_labels(recipe: ProjectRecipe) -> dict[str, list[str]]:
        from archetexture.core.parameters import ControlFieldBinding

        impacts = {identifier: [] for identifier in recipe.control_fields}

        def add_bindings(value, label):
            if isinstance(value, ControlFieldBinding):
                if value.source_id in impacts and label not in impacts[value.source_id]:
                    impacts[value.source_id].append(label)
            elif isinstance(value, dict):
                for child in value.values():
                    add_bindings(child, label)
            elif isinstance(value, (tuple, list)):
                for child in value:
                    add_bindings(child, label)

        for output in recipe.outputs:
            for layer in output.layers:
                if layer.mask is not None and layer.mask.source_id in impacts:
                    impacts[layer.mask.source_id].append(f"{output.name} › {layer.name} mask")
                for instance in [layer.source, *layer.transforms]:
                    for parameter, value in instance.parameters.items():
                        add_bindings(value, f"{output.name} › {layer.name} › {parameter}")
                    add_bindings(instance.influence, f"{output.name} › {layer.name} influence")
        for identifier, control in recipe.control_fields.items():
            for instance in [control.source, *control.transforms]:
                for parameter, value in instance.parameters.items():
                    add_bindings(value, f"Control Field {identifier} › {parameter}")
        return impacts

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
            if instance.operation_id == "generator.output_scalar" and parameter_id == "mode":
                refresh_properties = True
                target_id = instance.parameters.get("target")
                target = next(
                    (item for item in recipe.outputs if item.output_id == target_id), None
                )
                target_is_scalar = target is not None and target.value_type == "scalar"
                needs_scalar = value == "Direct"
                if target is None or target_is_scalar != needs_scalar:
                    compatible = next(
                        (
                            item
                            for item in recipe.outputs
                            if item.output_id != self._selected_output_id
                            and (item.value_type == "scalar") == needs_scalar
                        ),
                        None,
                    )
                    if compatible is not None:
                        instance.parameters["target"] = compatible.output_id
        self._commit_recipe(
            recipe,
            instance.instance_id,
            refresh_properties=refresh_properties,
        )

    def _select_layer(self, layer_id: str) -> None:
        recipe = self.document.recipe
        if not any(layer.layer_id == layer_id for layer in self._layers_for(recipe)):
            return
        self._selected_layer_id = layer_id
        layer = self._layer()
        self._selected_instance_id = layer.source.instance_id
        self._refresh_document(request_render=False, reset_ramp_selection=True)
        if self._latest_render_result is not None:
            self.viewport.set_mask_preview(
                (self._latest_render_result.mask_fields or {}).get(layer_id)
            )

    def _add_layer(self) -> None:
        recipe = self.document.recipe
        base_name = REGISTRY.get("generator.constant").name
        name = base_name
        number = 2
        names = {layer.name for layer in self._layers_for(recipe)}
        while name in names:
            name = f"{base_name} {number}"
            number += 1
        layer_id = f"layer-{uuid.uuid4().hex[:12]}"
        self._layers_for(recipe).append(
            LayerRecipe(
                layer_id,
                name,
                OperationInstance(
                    f"source-{uuid.uuid4().hex[:12]}",
                    "generator.constant",
                    1,
                    parameters={"value": 0.5},
                ),
            )
        )
        self._selected_layer_id = layer_id
        self._selected_instance_id = self._layers_for(recipe)[-1].source.instance_id
        self._commit_recipe(recipe, self._selected_instance_id)

    def _remove_layer(self, layer_id: str) -> None:
        recipe = self.document.recipe
        if len(self._layers_for(recipe)) <= 1:
            self.statusBar().showMessage("A project must keep at least one layer", 5000)
            return
        index = next(
            (i for i, layer in enumerate(self._layers_for(recipe)) if layer.layer_id == layer_id),
            None,
        )
        if index is None:
            return
        del self._layers_for(recipe)[index]
        selected = self._layers_for(recipe)[min(index, len(self._layers_for(recipe)) - 1)]
        self._selected_layer_id = selected.layer_id
        self._selected_instance_id = selected.source.instance_id
        self._commit_recipe(recipe, self._selected_instance_id)

    def _duplicate_layer(self, layer_id: str) -> None:
        import copy

        recipe = self.document.recipe
        index = next(
            (i for i, layer in enumerate(self._layers_for(recipe)) if layer.layer_id == layer_id),
            None,
        )
        if index is None:
            return
        duplicate = copy.deepcopy(self._layers_for(recipe)[index])
        duplicate.layer_id = f"layer-{uuid.uuid4().hex[:12]}"
        duplicate.name = f"{duplicate.name} Copy"
        for instance in [duplicate.source, *duplicate.transforms]:
            instance.instance_id = f"op-{uuid.uuid4().hex[:12]}"
        self._layers_for(recipe).insert(index + 1, duplicate)
        self._selected_layer_id = duplicate.layer_id
        self._selected_instance_id = duplicate.source.instance_id
        self._commit_recipe(recipe, self._selected_instance_id)

    @staticmethod
    def _clone_layer(layer: LayerRecipe) -> LayerRecipe:
        duplicate = copy.deepcopy(layer)
        duplicate.layer_id = f"layer-{uuid.uuid4().hex[:12]}"
        for instance in [duplicate.source, *duplicate.transforms]:
            instance.instance_id = f"op-{uuid.uuid4().hex[:12]}"
        duplicate.name = f"{duplicate.name} Copy"
        return duplicate

    def _choose_output(self, recipe: ProjectRecipe, title: str) -> MaterialOutputRecipe | None:
        choices = [
            (f"{output.name} · {output.value_type.title()}", output.output_id)
            for output in recipe.outputs
            if output.output_id != self._selected_output_id
        ]
        if not choices:
            self.statusBar().showMessage("Add another output first", 4000)
            return None
        label, accepted = QInputDialog.getItem(
            self, title, "Target output:", [item[0] for item in choices], 0, False
        )
        if not accepted:
            return None
        output_id = next(identifier for text, identifier in choices if text == label)
        return recipe.output(output_id)

    def _copy_layer_to_output(self, layer_id: str) -> None:
        recipe = self.document.recipe
        layer = next((item for item in self._layers_for(recipe) if item.layer_id == layer_id), None)
        target = self._choose_output(recipe, "Copy Layer to Output")
        if layer is None or target is None:
            return
        result_type = pipeline_output_type(layer.source, layer.transforms)
        if (
            target.value_type == "scalar"
            and (result_type != "scalar" or layer.color_ramp is not None)
        ) or (target.value_type == "normal" and result_type != "rgba"):
            QMessageBox.warning(
                self, "Incompatible layer", "This layer does not match the target output type."
            )
            return
        candidate = copy.deepcopy(recipe)
        candidate.output(target.output_id).layers.append(self._clone_layer(layer))
        try:
            ensure_valid_recipe(candidate)
        except ValidationError as exc:
            QMessageBox.warning(self, "Cannot copy layer", str(exc))
            return
        self._commit_recipe(candidate)

    def _move_layer_to_output(self, layer_id: str) -> None:
        recipe = self.document.recipe
        source_output = self._selected_output(recipe)
        layer = next((item for item in source_output.layers if item.layer_id == layer_id), None)
        target = self._choose_output(recipe, "Move Layer to Output")
        if layer is None or target is None:
            return
        if len(source_output.layers) <= 1:
            QMessageBox.information(
                self, "Keep one layer", "Copy this layer or add another before moving it."
            )
            return
        result_type = pipeline_output_type(layer.source, layer.transforms)
        if (
            target.value_type == "scalar"
            and (result_type != "scalar" or layer.color_ramp is not None)
        ) or (target.value_type == "normal" and result_type != "rgba"):
            QMessageBox.warning(
                self, "Incompatible layer", "This layer does not match the target output type."
            )
            return
        candidate = copy.deepcopy(recipe)
        candidate_source = candidate.output(source_output.output_id)
        candidate_target = candidate.output(target.output_id)
        candidate_layer = next(
            item for item in candidate_source.layers if item.layer_id == layer.layer_id
        )
        candidate_source.layers.remove(candidate_layer)
        candidate_target.layers.append(candidate_layer)
        try:
            ensure_valid_recipe(candidate)
        except ValidationError as exc:
            QMessageBox.warning(self, "Cannot move layer", str(exc))
            return
        self._selected_output_id = target.output_id
        self._selected_layer_id = candidate_layer.layer_id
        self._selected_instance_id = candidate_layer.source.instance_id
        self._commit_recipe(candidate, self._selected_instance_id)

    def _create_output_from_layer(self, layer_id: str) -> None:
        recipe = self.document.recipe
        layer = next((item for item in self._layers_for(recipe) if item.layer_id == layer_id), None)
        if layer is None:
            return
        result_type = pipeline_output_type(layer.source, layer.transforms)
        if result_type not in {"scalar", "rgba"}:
            QMessageBox.warning(
                self, "Invalid layer", "The selected layer has no valid output type."
            )
            return
        semantic = "custom_scalar" if result_type == "scalar" else "custom_color"
        output = MaterialOutputRecipe(
            f"output-{uuid.uuid4().hex[:12]}",
            f"{layer.name} Output",
            semantic,
            result_type if result_type == "scalar" else "color",
            [self._clone_layer(layer)],
        )
        recipe.outputs.append(output)
        self._selected_output_id = output.output_id
        self._selected_layer_id = output.layers[0].layer_id
        self._selected_instance_id = output.layers[0].source.instance_id
        self._commit_recipe(recipe, self._selected_instance_id)

    def _rename_layer(self, layer_id: str, name: str) -> None:
        recipe = self.document.recipe
        layer = next((item for item in self._layers_for(recipe) if item.layer_id == layer_id), None)
        name = name.strip()
        if layer is None or not name or layer.name == name:
            self._refresh_document(request_render=False)
            return
        layer.name = name
        self._commit_recipe(recipe)

    def _layer_enabled(self, layer_id: str, enabled: bool) -> None:
        recipe = self.document.recipe
        layer = next((item for item in self._layers_for(recipe) if item.layer_id == layer_id), None)
        if layer is not None and layer.enabled != enabled:
            layer.enabled = enabled
            self._commit_recipe(recipe)

    def _layer_moved(self, layer_id: str, target_index: int) -> None:
        recipe = self.document.recipe
        old_index = next(
            (i for i, layer in enumerate(self._layers_for(recipe)) if layer.layer_id == layer_id),
            None,
        )
        if old_index is None or not 0 <= target_index < len(self._layers_for(recipe)):
            return
        self._layers_for(recipe).insert(target_index, self._layers_for(recipe).pop(old_index))
        self._commit_recipe(recipe)

    def _layer_opacity_changed(self, layer_id: str, opacity: float) -> None:
        recipe = self.document.recipe
        layer = next((item for item in self._layers_for(recipe) if item.layer_id == layer_id), None)
        if layer is not None and layer.opacity != opacity:
            layer.opacity = opacity
            self._commit_recipe(recipe)

    def _layer_blend_changed(self, layer_id: str, mode: str) -> None:
        recipe = self.document.recipe
        layer = next((item for item in self._layers_for(recipe) if item.layer_id == layer_id), None)
        if layer is not None and layer.blend_mode != mode:
            layer.blend_mode = mode
            self._commit_recipe(recipe)

    def _layer_mask_changed(self, layer_id: str, source_id: str | None) -> None:
        recipe = self.document.recipe
        layer = next((item for item in self._layers_for(recipe) if item.layer_id == layer_id), None)
        if layer is None:
            return
        if source_id is None:
            layer.mask = None
        else:
            old = layer.mask
            mapping = (
                old.mapping
                if old is not None and old.source_id == source_id
                else ControlFieldMapping()
            )
            layer.mask = ControlFieldBinding(str(source_id), mapping)
        self._commit_recipe(recipe)

    def _edit_layer_mask(self, layer_id: str) -> None:
        recipe = self.document.recipe
        layer = next((item for item in self._layers_for(recipe) if item.layer_id == layer_id), None)
        if layer is None or layer.mask is None:
            return
        spec = ParameterSpec("mask", "Layer mask", ParameterType.PERCENT, 1.0, 0.0, 1.0)
        dialog = BindingDialog(recipe.control_fields, spec, layer.mask, self)
        if dialog.exec() != dialog.DialogCode.Accepted:
            return
        layer.mask = dialog.binding
        self._commit_recipe(recipe)

    def _navigate_to_layer_mask(self, layer_id: str) -> None:
        recipe = self.document.recipe
        layer = next((item for item in self._layers_for(recipe) if item.layer_id == layer_id), None)
        if layer is None or layer.mask is None:
            return
        self._show_control_fields()
        self.control_fields_editor.select_field(layer.mask.source_id)
        self._selected_control_field_id = layer.mask.source_id

    def _add_layer_mask(self, layer_id: str) -> None:
        recipe = self.document.recipe
        layer = next((item for item in self._layers_for(recipe) if item.layer_id == layer_id), None)
        if layer is None:
            return
        stem = re.sub(r"[^A-Za-z0-9]+", "-", layer.name).strip("-").lower() or layer_id
        if not stem[0].isalpha():
            stem = f"layer-{stem}"
        identifier = f"{stem}-mask"
        base = identifier
        suffix = 2
        while identifier in recipe.control_fields:
            identifier = f"{base}-{suffix}"
            suffix += 1
        definition = REGISTRY.get("generator.radial_gradient")
        recipe.control_fields[identifier] = ControlFieldRecipe(
            source=OperationInstance(
                f"{identifier}-source",
                definition.identifier,
                definition.version,
                parameters={spec.identifier: spec.default for spec in definition.parameter_specs},
            )
        )
        layer.mask = ControlFieldBinding(identifier)
        self._selected_control_field_id = identifier
        self._show_control_fields()
        self._commit_recipe(recipe, control_field_id=identifier)

    def _asset_reference(self, path: str | Path) -> AssetReference:
        selected = Path(path).resolve()
        project = Path(self.document.project_path).resolve() if self.document.project_path else None
        if project is not None:
            try:
                relative = selected.relative_to(project.parent)
                return AssetReference(relative.as_posix(), "project_relative")
            except ValueError:
                pass
        return AssetReference(str(selected), "absolute")

    def _choose_image(self) -> str:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Choose image",
            "",
            "Images (*.png *.jpg *.jpeg *.bmp *.tif *.tiff *.webp);;All files (*)",
        )
        return path

    def _browse_main_asset(self, key: str, _current) -> None:
        path = self._choose_image()
        if path:
            self._property_changed(key, self._asset_reference(path))

    def _browse_control_asset(self, key: str, _current) -> None:
        path = self._choose_image()
        if not path or not self._selected_control_field_id:
            return
        control = self.document.recipe.control_fields.get(self._selected_control_field_id)
        if control is None:
            return
        instance = (
            control.source
            if control.source.instance_id == self.control_fields_editor._selected_operation_id
            else next(
                (
                    item
                    for item in control.transforms
                    if item.instance_id == self.control_fields_editor._selected_operation_id
                ),
                None,
            )
        )
        if instance is not None:
            self._control_value_changed(
                self._selected_control_field_id,
                (instance.instance_id, key),
                self._asset_reference(path),
            )

    def _import_image_as_layer(self, *_args) -> None:
        path = self._choose_image()
        if not path:
            return
        recipe = self.document.recipe
        definition = REGISTRY.get("generator.image")
        name = Path(path).stem or "Image"
        source = OperationInstance(
            f"source-{uuid.uuid4().hex[:12]}",
            definition.identifier,
            definition.version,
            parameters={
                "asset": self._asset_reference(path),
                "fit": "Stretch",
                "resampling": "Bilinear",
            },
        )
        layer = LayerRecipe(f"layer-{uuid.uuid4().hex[:12]}", name, source, color_ramp=None)
        self._layers_for(recipe).append(layer)
        self._selected_layer_id, self._selected_instance_id = layer.layer_id, source.instance_id
        self._commit_recipe(recipe, source.instance_id)

    def _add_image_layer_mask(self, layer_id: str) -> None:
        path = self._choose_image()
        if not path:
            return
        recipe = self.document.recipe
        layer = next((item for item in self._layers_for(recipe) if item.layer_id == layer_id), None)
        if layer is None:
            return
        stem = re.sub(r"[^A-Za-z0-9]+", "-", layer.name).strip("-").lower() or "layer"
        identifier = f"{stem}-image-mask"
        suffix = 2
        while identifier in recipe.control_fields:
            identifier = f"{stem}-image-mask-{suffix}"
            suffix += 1
        definition = REGISTRY.get("generator.image_channel")
        source = OperationInstance(
            f"{identifier}-source",
            definition.identifier,
            definition.version,
            parameters={
                "asset": self._asset_reference(path),
                "channel": "Luminance",
                "fit": "Stretch",
                "resampling": "Bilinear",
            },
        )
        recipe.control_fields[identifier] = ControlFieldRecipe(source)
        layer.mask = ControlFieldBinding(identifier)
        self._selected_control_field_id = identifier
        self._show_control_fields()
        self._commit_recipe(recipe, control_field_id=identifier)

    def _control_field_selected(self, identifier: str) -> None:
        self._selected_control_field_id = identifier

    def _create_control_field(self) -> None:
        recipe = self.document.recipe
        index = 1
        while f"control-{index}" in recipe.control_fields:
            index += 1
        identifier = f"control-{index}"
        definition = REGISTRY.get("generator.constant")
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
            instance
            for layer in self._all_layers(recipe)
            for instance in [layer.source, *layer.transforms]
        ]
        for control in recipe.control_fields.values():
            instances.extend((control.source, *control.transforms))
        for instance in instances:
            if instance is not None:
                self._rewrite_instance_bindings(instance, old_id, new_id)
        for layer in self._all_layers(recipe):
            if layer.mask is not None:
                layer.mask = self._rewrite_binding_value(layer.mask, old_id, new_id)
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
        all_layers = self._all_layers(recipe)
        for layer in all_layers:
            if layer.mask is not None and layer.mask.source_id == identifier:
                return f"{layer.name} mask"
        instances = []
        for layer in all_layers:
            label = "main source" if len(all_layers) == 1 else f"{layer.name} source"
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
            self._show_control_fields()
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
        self._selected_output_id = recipe.outputs[0].output_id
        self.render_session.clear()
        self._latest_render_result = None
        self._latest_displayed_request_id = None
        self.viewport.set_error("Rendering…")
        self._selected_layer_id = self._layers_for(recipe)[0].layer_id
        self._selected_instance_id = self._layers_for(recipe)[0].source.instance_id
        self._refresh_document(request_render=True, reset_ramp_selection=True)
        return True

    def new_from_material(self, *_args) -> bool:
        dialog = MaterialStarterDialog(self)
        if dialog.exec() != dialog.DialogCode.Accepted or dialog.selected_starter is None:
            return False
        if not self._confirm_discard():
            return False
        try:
            recipe = create_material_starter(dialog.selected_starter.name)
        except Exception as exc:
            QMessageBox.critical(self, "Material creation failed", str(exc))
            return False
        recipe = self.document.new_document(recipe)
        self._selected_output_id = next(
            item.output_id for item in recipe.outputs if item.semantic == "base_color"
        )
        self._selected_layer_id = self._layers_for(recipe)[0].layer_id
        self._selected_instance_id = self._layers_for(recipe)[0].source.instance_id
        self._selected_control_field_id = "Scale"
        self.render_session.clear()
        self._latest_render_result = None
        self._latest_displayed_request_id = None
        self.viewport.set_error("Rendering…")
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
        self._selected_output_id = recipe.outputs[0].output_id
        self.render_session.clear()
        self._latest_render_result = None
        self._latest_displayed_request_id = None
        self.viewport.set_error("Rendering…")
        self._selected_layer_id = self._layers_for(recipe)[0].layer_id
        self._selected_instance_id = self._layers_for(recipe)[0].source.instance_id
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
        previous_path = self.document.project_path
        try:
            self.document.save(destination)
        except Exception as exc:
            QMessageBox.critical(self, "Save failed", str(exc))
            return False
        self._update_title_and_actions()
        self.statusBar().showMessage(f"Saved {destination}", 3000)
        if previous_path != self.document.project_path:
            self.render_session.clear()
            self._request_render()
        return True

    def closeEvent(self, event) -> None:
        if not self._confirm_discard():
            event.ignore()
            return
        self._closing = True
        self._preview_request_id += 1
        self._preview_executor.shutdown(wait=False, cancel_futures=True)
        self.preview_viewport.cleanup_gl()
        self.render_coordinator.close(wait=False)
        self.export_coordinator.close(wait=True)
        event.accept()


def build_main_window(recipe: ProjectRecipe | None = None) -> MainWindow:
    return MainWindow(recipe)


def main() -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    try:
        window = build_main_window()
    except Exception as exc:
        QMessageBox.critical(
            None,
            "ArcheTexture startup failed",
            f"The main window could not be initialized.\n\n{exc}",
        )
        return 1
    window.show()
    return app.exec()
