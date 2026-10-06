from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QSpinBox,
    QVBoxLayout,
)

from archetexture.core.recipe import ProjectRecipe


class ExportImageDialog(QDialog):
    def __init__(self, recipe: ProjectRecipe, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Export PNG")
        self.width_spin = QSpinBox(self)
        self.height_spin = QSpinBox(self)
        for spin, value in ((self.width_spin, recipe.width), (self.height_spin, recipe.height)):
            spin.setRange(1, 8192)
            spin.setValue(value)
            spin.setSuffix(" px")
        self.lock_aspect = QCheckBox("Lock aspect ratio", self)
        self.lock_aspect.setChecked(True)
        self._ratio = recipe.width / recipe.height
        self._updating = False
        self.width_spin.valueChanged.connect(self._width_changed)
        self.height_spin.valueChanged.connect(self._height_changed)
        self.lock_aspect.toggled.connect(lambda _checked: self._update_summary())
        self.info_label = QLabel(self)
        self.info_label.setWordWrap(True)
        form = QFormLayout()
        form.addRow("Format", QLabel("PNG (8-bit RGBA)", self))
        form.addRow("Width", self.width_spin)
        form.addRow("Height", self.height_spin)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(self.lock_aspect)
        layout.addWidget(self.info_label)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            parent=self,
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Export")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self._update_summary()

    @property
    def dimensions(self) -> tuple[int, int]:
        return self.width_spin.value(), self.height_spin.value()

    def _width_changed(self, width: int) -> None:
        if self.lock_aspect.isChecked() and not self._updating:
            self._updating = True
            self.height_spin.setValue(max(1, min(8192, round(width / self._ratio))))
            self._updating = False
        self._update_summary()

    def _height_changed(self, height: int) -> None:
        if self.lock_aspect.isChecked() and not self._updating:
            self._updating = True
            self.width_spin.setValue(max(1, min(8192, round(height * self._ratio))))
            self._updating = False
        self._update_summary()

    def _update_summary(self) -> None:
        width, height = self.dimensions
        count = width * height
        warning = (
            " Warning: dimensions above 4096 pixels may take considerably longer to export."
            if max(width, height) > 4096
            else ""
        )
        self.info_label.setText(f"{count:,} pixels." + warning)
