from __future__ import annotations

import copy
import uuid

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from archetexture.core.output_dependencies import (
    output_direct_dependencies,
    transitive_output_dependencies,
)
from archetexture.core.material_presets import (
    MATERIAL_PRESETS,
    apply_material_preset,
    duplicate_material_output,
    new_material_output,
)
from archetexture.core.outputs import OUTPUT_CATEGORIES, semantics_in_category
from archetexture.core.recipe import LayerRecipe, OperationInstance, ProjectRecipe
from archetexture.core.registry import REGISTRY


class AddOutputDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Add Material Output")
        self.resize(570, 410)
        layout = QVBoxLayout(self)
        layout.addWidget(
            QLabel("Choose an output semantic. The description summarizes its intended data.")
        )
        self.tabs = QTabWidget(self)
        self.semantic_lists: dict[str, QListWidget] = {}
        for category in OUTPUT_CATEGORIES:
            listing = QListWidget(self)
            for definition in semantics_in_category(category):
                item = QListWidgetItem(f"{definition.name}  ·  {definition.description}")
                item.setData(Qt.ItemDataRole.UserRole, definition.identifier)
                listing.addItem(item)
            listing.itemDoubleClicked.connect(lambda _item: self.accept())
            self.semantic_lists[category] = listing
            self.tabs.addTab(listing, category)
        layout.addWidget(self.tabs, 1)
        self.name_edit = QLineEdit(self)
        self.name_edit.setPlaceholderText("Custom output name (for custom semantics)")
        layout.addWidget(self.name_edit)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel, parent=self
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    @property
    def selection(self) -> tuple[str, str | None] | None:
        listing = self.semantic_lists[self.tabs.tabText(self.tabs.currentIndex())]
        item = listing.currentItem()
        if item is None:
            return None
        semantic = str(item.data(Qt.ItemDataRole.UserRole))
        name = self.name_edit.text().strip() or None
        return semantic, name

    def accept(self) -> None:
        if self.selection is None:
            QMessageBox.information(self, "Choose an output", "Select an output semantic first.")
            return
        super().accept()


class OutputManagerDialog(QDialog):
    def __init__(self, recipe: ProjectRecipe, selected_output_id: str, parent=None):
        super().__init__(parent)
        self.recipe = copy.deepcopy(recipe)
        self.selected_output_id = selected_output_id
        self.setWindowTitle("Manage Material Outputs")
        self.resize(760, 540)
        root = QVBoxLayout(self)
        body = QHBoxLayout()
        self.listing = QListWidget(self)
        self.listing.currentItemChanged.connect(self._selection_changed)
        body.addWidget(self.listing, 1)
        editor = QWidget(self)
        form = QFormLayout(editor)
        self.semantic_label = QLabel()
        self.type_label = QLabel()
        self.name_edit = QLineEdit()
        self.suffix_edit = QLineEdit()
        self.clear_edit = QLineEdit()
        self.enabled_combo = QComboBox()
        self.enabled_combo.addItem("Included in texture-set export", True)
        self.enabled_combo.addItem("Excluded from texture-set export", False)
        form.addRow("Semantic", self.semantic_label)
        form.addRow("Value type", self.type_label)
        form.addRow("Name", self.name_edit)
        form.addRow("Export suffix", self.suffix_edit)
        form.addRow("Clear value", self.clear_edit)
        form.addRow("Export", self.enabled_combo)
        self.name_edit.editingFinished.connect(self._apply_properties)
        self.suffix_edit.editingFinished.connect(self._apply_properties)
        self.clear_edit.editingFinished.connect(self._apply_properties)
        self.enabled_combo.currentIndexChanged.connect(self._apply_properties)
        body.addWidget(editor, 2)
        root.addLayout(body, 1)

        actions = QHBoxLayout()
        self.add_button = QPushButton("Add Output…")
        self.add_button.clicked.connect(self._add_output)
        self.duplicate_button = QPushButton("Duplicate")
        self.duplicate_button.clicked.connect(self._duplicate)
        self.remove_button = QPushButton("Delete")
        self.remove_button.clicked.connect(self._delete)
        self.derive_button = QPushButton("Derive Output…")
        self.derive_button.clicked.connect(self._derive)
        self.up_button = QPushButton("Move up")
        self.up_button.clicked.connect(lambda: self._move(-1))
        self.down_button = QPushButton("Move down")
        self.down_button.clicked.connect(lambda: self._move(1))
        for button in (
            self.add_button,
            self.duplicate_button,
            self.remove_button,
            self.derive_button,
            self.up_button,
            self.down_button,
        ):
            actions.addWidget(button)
        root.addLayout(actions)

        presets = QHBoxLayout()
        self.preset_combo = QComboBox()
        self.preset_combo.addItems(MATERIAL_PRESETS)
        self.apply_preset_button = QPushButton("Add Preset Outputs")
        self.apply_preset_button.clicked.connect(self._apply_preset)
        presets.addWidget(QLabel("Material preset:"))
        presets.addWidget(self.preset_combo, 1)
        presets.addWidget(self.apply_preset_button)
        root.addLayout(presets)
        self.preset_note = QLabel(
            "Applying a preset adds missing semantics and preserves existing outputs."
        )
        root.addWidget(self.preset_note)
        self.dependencies_label = QLabel()
        self.dependencies_label.setObjectName("output-dependencies")
        root.addWidget(self.dependencies_label)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel, parent=self
        )
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)
        self._refresh()

    def _current_id(self) -> str | None:
        item = self.listing.currentItem()
        return str(item.data(Qt.ItemDataRole.UserRole)) if item else None

    def _current_output(self):
        identifier = self._current_id()
        return next((item for item in self.recipe.outputs if item.output_id == identifier), None)

    def _refresh(self) -> None:
        self.listing.blockSignals(True)
        self.listing.clear()
        selected = None
        for output in self.recipe.outputs:
            item = QListWidgetItem(output.name)
            item.setData(Qt.ItemDataRole.UserRole, output.output_id)
            self.listing.addItem(item)
            if output.output_id == self.selected_output_id:
                selected = item
        if selected is None and self.recipe.outputs:
            selected = self.listing.item(0)
            self.selected_output_id = self.recipe.outputs[0].output_id
        self.listing.setCurrentItem(selected)
        self.listing.blockSignals(False)
        self._selection_changed(selected, None)

    def _selection_changed(self, current, _previous) -> None:
        output = self._current_output()
        enabled = output is not None
        for widget in (self.name_edit, self.suffix_edit, self.clear_edit, self.enabled_combo):
            widget.setEnabled(enabled)
        if output is None:
            return
        self.selected_output_id = output.output_id
        self.semantic_label.setText(output.semantic.replace("_", " ").title())
        self.type_label.setText(output.value_type.title())
        self.name_edit.setText(output.name)
        self.suffix_edit.setText(output.export_suffix)
        value = output.clear_value
        self.clear_edit.setText(
            ", ".join(str(item) for item in value) if isinstance(value, tuple) else str(value)
        )
        self.enabled_combo.setCurrentIndex(max(0, self.enabled_combo.findData(output.enabled)))
        self.remove_button.setEnabled(len(self.recipe.outputs) > 1)
        dependencies = output_direct_dependencies(self.recipe, output.output_id)
        labels = [item.name for item in self.recipe.outputs if item.output_id in dependencies]
        self.dependencies_label.setText("Depends on: " + (", ".join(labels) if labels else "None"))
        row = self.listing.currentRow()
        self.up_button.setEnabled(row > 0)
        self.down_button.setEnabled(row >= 0 and row < self.listing.count() - 1)

    def _apply_properties(self, *_args) -> None:
        output = self._current_output()
        if output is None:
            return
        output.name = self.name_edit.text().strip() or output.name
        output.export_suffix = self.suffix_edit.text().strip() or output.export_suffix
        try:
            values = tuple(float(part.strip()) for part in self.clear_edit.text().split(","))
            if output.value_type == "scalar" and len(values) == 1:
                output.clear_value = values[0]
            elif output.value_type in {"color", "normal"} and len(values) == 4:
                output.clear_value = values
        except ValueError:
            pass
        output.enabled = bool(self.enabled_combo.currentData())
        item = self.listing.currentItem()
        if item:
            item.setText(output.name)

    def _add_output(self) -> None:
        dialog = AddOutputDialog(self)
        if dialog.exec() != QDialog.DialogCode.Accepted or dialog.selection is None:
            return
        semantic, name = dialog.selection
        output = new_material_output(semantic, name)
        self.recipe.outputs.append(output)
        self.selected_output_id = output.output_id
        self._refresh()

    def _duplicate(self) -> None:
        output = self._current_output()
        if output is None:
            return
        duplicate = duplicate_material_output(output)
        self.recipe.outputs.insert(self.recipe.outputs.index(output) + 1, duplicate)
        self.selected_output_id = duplicate.output_id
        self._refresh()

    def _delete(self) -> None:
        if len(self.recipe.outputs) <= 1:
            return
        output = self._current_output()
        if output is None:
            return
        dependents = [
            item.name for item in self.recipe.outputs
            if item.output_id != output.output_id
            and output.output_id in output_direct_dependencies(self.recipe, item.output_id)
        ]
        if dependents:
            QMessageBox.warning(
                self, "Output is in use",
                f"Cannot delete {output.name}. Used by: " + ", ".join(dependents),
            )
            return
        index = self.recipe.outputs.index(output)
        self.recipe.outputs.remove(output)
        self.selected_output_id = self.recipe.outputs[
            min(index, len(self.recipe.outputs) - 1)
        ].output_id
        self._refresh()

    def _derive(self) -> None:
        helpers = (
            "Normal from Height", "Glossiness from Roughness", "Roughness from Glossiness",
            "Opacity from Base Color Alpha", "Height from Base Color Luminance",
            "Custom Scalar from Output…", "Custom Color from Output…",
        )
        helper, accepted = QInputDialog.getItem(self, "Derive Output", "Workflow:", helpers, 0, False)
        if not accepted:
            return
        desired = {
            "Normal from Height": "scalar",
            "Glossiness from Roughness": "scalar",
            "Roughness from Glossiness": "scalar",
            "Opacity from Base Color Alpha": "color",
            "Height from Base Color Luminance": "color",
            "Custom Scalar from Output…": None,
            "Custom Color from Output…": None,
        }[helper]
        preferred_semantics = {
            "Normal from Height": "height",
            "Glossiness from Roughness": "roughness",
            "Roughness from Glossiness": "glossiness",
            "Opacity from Base Color Alpha": "base_color",
            "Height from Base Color Luminance": "base_color",
        }
        candidates = [
            item for item in self.recipe.outputs
            if item.output_id != self.selected_output_id
            and self.selected_output_id not in transitive_output_dependencies(self.recipe, item.output_id)
        ]
        if desired:
            candidates = [item for item in candidates if item.value_type == desired]
        preferred = preferred_semantics.get(helper)
        preferred_outputs = [item for item in candidates if item.semantic == preferred]
        if preferred_outputs:
            candidates = preferred_outputs
        if not candidates:
            QMessageBox.information(self, "No source output", "Add a compatible source output first.")
            return
        labels = [f"{item.name} · {item.value_type.title()}" for item in candidates]
        label, accepted = QInputDialog.getItem(self, "Choose Source Output", "Output:", labels, 0, False)
        if not accepted:
            return
        target = candidates[labels.index(label)]
        is_normal = helper == "Normal from Height"
        is_color = helper == "Custom Color from Output…"
        if is_normal:
            semantic, name = "normal", "Normal from Height"
        elif is_color:
            semantic, name = "custom_color", "Derived Color"
        elif helper == "Glossiness from Roughness":
            semantic, name = "glossiness", "Glossiness"
        elif helper == "Roughness from Glossiness":
            semantic, name = "roughness", "Roughness"
        elif helper == "Opacity from Base Color Alpha":
            semantic, name = "opacity", "Opacity"
        elif helper == "Height from Base Color Luminance":
            semantic, name = "height", "Height"
        else:
            semantic, name = "mask", "Derived Scalar"
        output = new_material_output(semantic, name)
        if is_normal:
            source_operation = "generator.output_scalar"
            mode = "Direct"
            transform_id = "transform.height_to_normal"
        elif helper in {"Glossiness from Roughness", "Roughness from Glossiness"}:
            source_operation = "generator.output_scalar"
            mode = "Direct"
            transform_id = "transform.invert"
        elif helper == "Opacity from Base Color Alpha":
            source_operation = "generator.output_scalar"
            mode = "Alpha"
            transform_id = None
        elif helper == "Height from Base Color Luminance":
            source_operation = "generator.output_scalar"
            mode = "Luminance"
            transform_id = None
        elif is_color:
            source_operation = "generator.output_color"
            mode = None
            transform_id = None
        else:
            source_operation = "generator.output_scalar"
            mode = "Direct" if target.value_type == "scalar" else "Luminance"
            transform_id = None
        source = OperationInstance(
            f"source-{uuid.uuid4().hex[:12]}", source_operation, 1,
            parameters={"target": target.output_id, **({"mode": mode} if mode else {})},
        )
        transforms = []
        if transform_id:
            definition = REGISTRY.get(transform_id)
            transforms.append(OperationInstance(
                f"op-{uuid.uuid4().hex[:12]}", transform_id, definition.version,
                parameters={spec.identifier: spec.default for spec in definition.parameter_specs},
            ))
        output.layers[0] = LayerRecipe(
            f"layer-{uuid.uuid4().hex[:12]}", "Derived Layer", source, transforms
        )
        self.recipe.outputs.append(output)
        self.selected_output_id = output.output_id
        self._refresh()

    def _move(self, delta: int) -> None:
        output = self._current_output()
        if output is None:
            return
        index = self.recipe.outputs.index(output)
        target = index + delta
        if 0 <= target < len(self.recipe.outputs):
            self.recipe.outputs.insert(target, self.recipe.outputs.pop(index))
            self._refresh()

    def _apply_preset(self) -> None:
        apply_material_preset(self.recipe, self.preset_combo.currentText())
        self._refresh()

    def _accept(self) -> None:
        self._apply_properties()
        if not self.recipe.outputs:
            QMessageBox.warning(
                self, "Output required", "A project must contain at least one output."
            )
            return
        self.accept()
