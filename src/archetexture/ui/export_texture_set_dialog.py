from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
)

from archetexture.core.recipe import ProjectRecipe
from archetexture.export.texture_set import (
    OutputExportSpec,
    PackedChannelSpec,
    PackedMapSpec,
    TextureSetExporter,
    TextureSetExportPlan,
    packed_preset,
)


class ExportTextureSetDialog(QDialog):
    def __init__(self, recipe: ProjectRecipe, parent=None):
        super().__init__(parent)
        self.recipe = recipe
        self.setWindowTitle("Export Texture Set")
        self.resize(700, 680)
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.destination = QLineEdit(str(Path.cwd()))
        browse = QPushButton("Browse…")
        browse.clicked.connect(self._browse)
        destination_row = QHBoxLayout()
        destination_row.addWidget(self.destination, 1)
        destination_row.addWidget(browse)
        destination_widget = QVBoxLayout()
        destination_widget.addLayout(destination_row)
        destination_container = QLabel(self)
        destination_container.setLayout(destination_widget)
        self.filename_base = QLineEdit("Material")
        form.addRow("Destination", destination_container)
        form.addRow("Filename base", self.filename_base)
        layout.addLayout(form)

        resolution_row = QHBoxLayout()
        self.use_project_resolution = QCheckBox("Use project resolution", self)
        self.use_project_resolution.setChecked(True)
        self.width_spin = QSpinBox(self)
        self.height_spin = QSpinBox(self)
        self.width_spin.setRange(1, 8192)
        self.height_spin.setRange(1, 8192)
        self.width_spin.setValue(recipe.width)
        self.height_spin.setValue(recipe.height)
        self.width_spin.setSuffix(" px")
        self.height_spin.setSuffix(" px")
        self.lock_aspect = QCheckBox("Lock aspect", self)
        self.lock_aspect.setChecked(True)
        self._ratio = recipe.width / recipe.height
        self._updating = False
        self.use_project_resolution.toggled.connect(self._resolution_mode)
        self.width_spin.valueChanged.connect(self._width_changed)
        self.height_spin.valueChanged.connect(self._height_changed)
        resolution_row.addWidget(self.use_project_resolution)
        resolution_row.addWidget(self.width_spin)
        resolution_row.addWidget(self.height_spin)
        resolution_row.addWidget(self.lock_aspect)
        layout.addLayout(resolution_row)
        layout.addWidget(QLabel("Separate maps · output suffixes preview the manager settings"))
        self.outputs = QListWidget(self)
        self.outputs.setObjectName("texture-set-output-list")
        for output in recipe.outputs:
            item = QListWidgetItem(f"{output.name}  →  _{output.export_suffix}.png")
            item.setData(Qt.ItemDataRole.UserRole, output.output_id)
            item.setCheckState(Qt.CheckState.Checked if output.enabled else Qt.CheckState.Unchecked)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            self.outputs.addItem(item)
        layout.addWidget(self.outputs, 1)

        packing_row = QHBoxLayout()
        self.orm = QCheckBox("ORM", self)
        self.rma = QCheckBox("RMA", self)
        self.mra = QCheckBox("MRA", self)
        self.unity = QCheckBox("Unity HDRP-like Mask Map", self)
        for checkbox in (self.orm, self.rma, self.mra, self.unity):
            packing_row.addWidget(checkbox)
        layout.addLayout(packing_row)
        self.unity_detail = QComboBox(self)
        self.unity_detail.addItem("Constant 1", PackedChannelSpec(constant=1.0))
        self.unity_detail.addItem("Constant 0", PackedChannelSpec(constant=0.0))
        layout.addWidget(QLabel("Custom RGBA pack"))
        self.custom_pack = QCheckBox("Export custom pack", self)
        self.custom_suffix = QLineEdit("CustomPack", self)
        custom_header = QHBoxLayout()
        custom_header.addWidget(self.custom_pack)
        custom_header.addWidget(QLabel("Suffix"))
        custom_header.addWidget(self.custom_suffix, 1)
        layout.addLayout(custom_header)
        output_choices = []
        for output in recipe.outputs:
            if output.value_type == "scalar":
                output_choices.append(
                    (output.name, PackedChannelSpec(source_output_id=output.output_id))
                )
            else:
                for channel in "RGBA":
                    output_choices.append(
                        (f"{output.name} · {channel}", PackedChannelSpec(output.output_id, channel))
                    )
        for label, spec in output_choices:
            self.unity_detail.addItem(label, spec)
        layout.addWidget(QLabel("Unity-like B channel · Detail Mask source"))
        layout.addWidget(self.unity_detail)
        self.channel_sources: dict[str, QComboBox] = {}
        self.channel_inverts: dict[str, QCheckBox] = {}
        channels_layout = QFormLayout()
        for channel in "RGBA":
            combo = QComboBox(self)
            combo.addItem("Constant 0", PackedChannelSpec(constant=0.0))
            combo.addItem("Constant 1", PackedChannelSpec(constant=1.0))
            for label, spec in output_choices:
                combo.addItem(label, spec)
            invert = QCheckBox("Invert", self)
            row = QHBoxLayout()
            row.addWidget(combo, 1)
            row.addWidget(invert)
            container = QLabel(self)
            container.setLayout(row)
            channels_layout.addRow(channel, container)
            self.channel_sources[channel] = combo
            self.channel_inverts[channel] = invert
        layout.addLayout(channels_layout)
        scalar_row = QHBoxLayout()
        scalar_row.addWidget(QLabel("Scalar depth"))
        self.scalar_depth = QComboBox(self)
        self.scalar_depth.addItem("8-bit grayscale PNG", 8)
        self.scalar_depth.addItem("16-bit grayscale PNG", 16)
        scalar_row.addWidget(self.scalar_depth)
        self.overwrite = QCheckBox("Allow replacing existing files", self)
        scalar_row.addWidget(self.overwrite)
        layout.addLayout(scalar_row)
        self.info = QLabel("Channels are normalized to 8-bit RGBA for packed maps.", self)
        self.info.setWordWrap(True)
        layout.addWidget(self.info)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel, parent=self
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Export")
        buttons.accepted.connect(self._preflight)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self._resolution_mode(True)

    def _browse(self) -> None:
        path = QFileDialog.getExistingDirectory(
            self, "Choose texture-set directory", self.destination.text()
        )
        if path:
            self.destination.setText(path)

    def _resolution_mode(self, use_project: bool) -> None:
        self.width_spin.setEnabled(not use_project)
        self.height_spin.setEnabled(not use_project)

    def _width_changed(self, width: int) -> None:
        if (
            self.lock_aspect.isChecked()
            and not self._updating
            and not self.use_project_resolution.isChecked()
        ):
            self._updating = True
            self.height_spin.setValue(max(1, min(8192, round(width / self._ratio))))
            self._updating = False

    def _height_changed(self, height: int) -> None:
        if (
            self.lock_aspect.isChecked()
            and not self._updating
            and not self.use_project_resolution.isChecked()
        ):
            self._updating = True
            self.width_spin.setValue(max(1, min(8192, round(height * self._ratio))))
            self._updating = False

    @property
    def plan(self) -> TextureSetExportPlan:
        width, height = (
            (self.recipe.width, self.recipe.height)
            if self.use_project_resolution.isChecked()
            else (self.width_spin.value(), self.height_spin.value())
        )
        depth = int(self.scalar_depth.currentData())
        specs = tuple(
            OutputExportSpec(
                output.output_id,
                output.export_suffix,
                item.checkState() == Qt.CheckState.Checked,
                depth if output.value_type == "scalar" else 8,
            )
            for index, output in enumerate(self.recipe.outputs)
            if (item := self.outputs.item(index)) is not None
        )
        packed = []
        for checked, name in (
            (self.orm, "ORM"),
            (self.rma, "RMA"),
            (self.mra, "MRA"),
            (self.unity, "Unity HDRP-like Mask Map"),
        ):
            if checked.isChecked():
                packed.append(
                    packed_preset(
                        name,
                        self.recipe,
                        detail_channel=self.unity_detail.currentData()
                        if checked is self.unity
                        else None,
                    )
                )
        if self.custom_pack.isChecked():
            channels = {}
            for key, combo in self.channel_sources.items():
                selected = combo.currentData()
                channels[key] = PackedChannelSpec(
                    selected.source_output_id,
                    selected.component,
                    selected.constant,
                    self.channel_inverts[key].isChecked(),
                )
            packed.append(PackedMapSpec(self.custom_suffix.text(), channels))
        return TextureSetExportPlan(
            self.destination.text(),
            self.filename_base.text(),
            width,
            height,
            specs,
            tuple(packed),
            self.overwrite.isChecked(),
        )

    def _preflight(self) -> None:
        try:
            TextureSetExporter().preflight(self.recipe, self.plan)
        except Exception as exc:
            QMessageBox.warning(self, "Export preflight failed", str(exc))
            return
        self.accept()
