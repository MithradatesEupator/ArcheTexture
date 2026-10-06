from __future__ import annotations

import random

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from archetexture.core.recipe import ProjectRecipe
from archetexture.core.validation import MAX_PROJECT_DIMENSION, MAX_PROJECT_SEED

RESOLUTION_PRESETS = (
    ("256 × 256", (256, 256)),
    ("512 × 512", (512, 512)),
    ("1024 × 1024", (1024, 1024)),
    ("2048 × 2048", (2048, 2048)),
    ("4096 × 4096", (4096, 4096)),
)


class ProjectSettingsDialog(QDialog):
    """Dialog-local editor for canonical project dimensions and seed."""

    def __init__(self, recipe: ProjectRecipe, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle("Project Settings")
        self.setModal(True)
        self._aspect_ratio = recipe.width / recipe.height
        self._updating = False

        self.preset_combo = QComboBox(self)
        self.preset_combo.setObjectName("project-resolution-preset")
        self.preset_combo.addItem("Custom", None)
        for label, dimensions in RESOLUTION_PRESETS:
            self.preset_combo.addItem(label, dimensions)

        self.width_spin = QSpinBox(self)
        self.width_spin.setObjectName("project-width")
        self.width_spin.setRange(1, MAX_PROJECT_DIMENSION)
        self.width_spin.setValue(recipe.width)
        self.width_spin.setSuffix(" px")
        self.height_spin = QSpinBox(self)
        self.height_spin.setObjectName("project-height")
        self.height_spin.setRange(1, MAX_PROJECT_DIMENSION)
        self.height_spin.setValue(recipe.height)
        self.height_spin.setSuffix(" px")

        self.lock_aspect = QCheckBox("Lock aspect ratio", self)
        self.lock_aspect.setObjectName("project-lock-aspect")
        self.lock_aspect.setChecked(True)

        self.seed_spin = QSpinBox(self)
        self.seed_spin.setObjectName("project-global-seed")
        self.seed_spin.setRange(0, MAX_PROJECT_SEED)
        self.seed_spin.setValue(recipe.seed)
        self.randomize_button = QPushButton("Randomize Seed", self)
        self.randomize_button.setObjectName("randomize-project-seed")
        self.warning_label = QLabel(self)
        self.warning_label.setObjectName("project-size-warning")
        self.warning_label.setWordWrap(True)

        form = QFormLayout()
        form.addRow("Resolution preset", self.preset_combo)
        form.addRow("Width", self.width_spin)
        form.addRow("Height", self.height_spin)
        form.addRow("Global Seed", self.seed_spin)
        form.addRow("", self.randomize_button)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            parent=self,
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(self.lock_aspect)
        layout.addWidget(self.warning_label)
        layout.addWidget(buttons)

        self.preset_combo.currentIndexChanged.connect(self._preset_selected)
        self.width_spin.valueChanged.connect(self._width_changed)
        self.height_spin.valueChanged.connect(self._height_changed)
        self.randomize_button.clicked.connect(self.randomize_seed)
        self._sync_preset()
        self._update_warning()

    @property
    def proposed_settings(self) -> tuple[int, int, int]:
        return self.width_spin.value(), self.height_spin.value(), self.seed_spin.value()

    def randomize_seed(self) -> None:
        seed = random.randint(0, MAX_PROJECT_SEED)
        if seed == self.seed_spin.value():
            seed = (seed + 1) % (MAX_PROJECT_SEED + 1)
        self.seed_spin.setValue(seed)

    def _preset_selected(self, index: int) -> None:
        if self._updating:
            return
        dimensions = self.preset_combo.itemData(index)
        if dimensions is None:
            return
        self._updating = True
        self.width_spin.setValue(dimensions[0])
        self.height_spin.setValue(dimensions[1])
        self._updating = False
        self._update_warning()

    def _width_changed(self, width: int) -> None:
        if not self._updating and self.lock_aspect.isChecked():
            self._updating = True
            self.height_spin.setValue(self._clamp_dimension(round(width / self._aspect_ratio)))
            self._updating = False
        if not self._updating:
            self._sync_preset()
            self._update_warning()

    def _height_changed(self, height: int) -> None:
        if not self._updating and self.lock_aspect.isChecked():
            self._updating = True
            self.width_spin.setValue(self._clamp_dimension(round(height * self._aspect_ratio)))
            self._updating = False
        if not self._updating:
            self._sync_preset()
            self._update_warning()

    @staticmethod
    def _clamp_dimension(value: int) -> int:
        return max(1, min(MAX_PROJECT_DIMENSION, value))

    def _sync_preset(self) -> None:
        dimensions = (self.width_spin.value(), self.height_spin.value())
        selected = next(
            (
                index
                for index in range(1, self.preset_combo.count())
                if self.preset_combo.itemData(index) == dimensions
            ),
            0,
        )
        self.preset_combo.blockSignals(True)
        self.preset_combo.setCurrentIndex(selected)
        self.preset_combo.blockSignals(False)

    def _update_warning(self) -> None:
        is_large = max(self.width_spin.value(), self.height_spin.value()) > 4096
        self.warning_label.setText(
            "Large procedural canvases may require substantially more memory and render time."
            if is_large
            else ""
        )
        self.warning_label.setVisible(is_large)
