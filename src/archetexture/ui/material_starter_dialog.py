from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
)

from archetexture.core.material_starters import MATERIAL_STARTERS, MaterialStarter


class MaterialStarterDialog(QDialog):
    """Searchable picker for editable material recipes."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("New from Material")
        self.setObjectName("material-starter-dialog")
        self.resize(720, 480)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Choose an editable procedural material starter."))
        self.search = QLineEdit(self)
        self.search.setObjectName("material-starter-search")
        self.search.setPlaceholderText("Search material starters…")
        self.search.setClearButtonEnabled(True)
        layout.addWidget(self.search)
        body = QHBoxLayout()
        self.material_list = QListWidget(self)
        self.material_list.setObjectName("material-starter-list")
        self.details = QLabel(self)
        self.details.setObjectName("material-starter-details")
        self.details.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self.details.setWordWrap(True)
        body.addWidget(self.material_list, 1)
        body.addWidget(self.details, 2)
        layout.addLayout(body, 1)
        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Cancel | QDialogButtonBox.StandardButton.Ok,
            parent=self,
        )
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Create Material")
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)
        self.search.textChanged.connect(self._filter)
        self.material_list.currentItemChanged.connect(self._show_details)
        self._filter("")

    @property
    def selected_starter(self) -> MaterialStarter | None:
        item = self.material_list.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item else None

    def _filter(self, query: str) -> None:
        query = query.strip().casefold()
        previous = self.selected_starter.name if self.selected_starter else None
        self.material_list.blockSignals(True)
        self.material_list.clear()
        for starter in MATERIAL_STARTERS:
            searchable = " ".join((starter.name, starter.description, *starter.channels)).casefold()
            if query and query not in searchable:
                continue
            item = QListWidgetItem(starter.name)
            item.setData(Qt.ItemDataRole.UserRole, starter)
            self.material_list.addItem(item)
            if starter.name == previous:
                self.material_list.setCurrentItem(item)
        if self.material_list.currentRow() < 0 and self.material_list.count():
            self.material_list.setCurrentRow(0)
        self.material_list.blockSignals(False)
        self._show_details(self.material_list.currentItem())
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(
            self.material_list.count() > 0
        )

    def _show_details(self, item: QListWidgetItem | None, _previous=None) -> None:
        starter = item.data(Qt.ItemDataRole.UserRole) if item else None
        if starter is None:
            self.details.setText("No matching materials.")
            return
        channels = "<br>".join(f"• {channel}" for channel in starter.channels)
        self.details.setText(
            f"<h2>{starter.name}</h2><p>{starter.description}</p>"
            f"<p><b>Editable recipe channels</b><br>{channels}</p>"
            "<p>Generated from procedural sources, shared Scale and Wear control fields, "
            "and live Height-derived material outputs. This is an artistic starter, not "
            "a physically measured material.</p>"
        )
