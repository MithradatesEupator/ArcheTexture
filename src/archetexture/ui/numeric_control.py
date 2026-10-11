"""Large, keyboard-friendly numeric input for the Simple Editor."""

from __future__ import annotations

from PySide6.QtCore import QEvent, Qt, Signal
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QHBoxLayout, QLabel, QLineEdit, QPushButton, QVBoxLayout, QWidget


class NumericControl(QWidget):
    """Editable number with distinct, repeatable increment and decrement buttons."""

    valueChanged = Signal(object)
    editStarted = Signal()
    editFinished = Signal()

    def __init__(
        self,
        value: int | float,
        *,
        minimum: float,
        maximum: float,
        step: float,
        decimals: int,
        unit: str = "",
        parent=None,
    ):
        super().__init__(parent)
        self._minimum = minimum
        self._maximum = maximum
        self._step = step
        self._decimals = decimals
        self._integer = decimals == 0
        self._value = value
        self._editing = False
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        self.editor = QLineEdit(self)
        self.editor.setObjectName("numeric-value")
        self.editor.setMinimumWidth(88)
        self.editor.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.editor.installEventFilter(self)
        row.addWidget(self.editor, 1)
        self.unit_label = QLabel(unit, self)
        self.unit_label.setObjectName("numeric-unit")
        self.unit_label.setMinimumWidth(18)
        self.unit_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        row.addWidget(self.unit_label)
        buttons = QVBoxLayout()
        buttons.setContentsMargins(0, 0, 0, 0)
        buttons.setSpacing(1)
        self.increment = QPushButton("+", self)
        self.decrement = QPushButton("−", self)
        for button in (self.increment, self.decrement):
            button.setAutoRepeat(True)
            button.setAutoRepeatDelay(350)
            button.setAutoRepeatInterval(75)
            button.setFixedSize(30, 20)
            buttons.addWidget(button)
        row.addLayout(buttons)
        self.increment.pressed.connect(self._begin)
        self.decrement.pressed.connect(self._begin)
        self.increment.clicked.connect(lambda: self._step_by(1))
        self.decrement.clicked.connect(lambda: self._step_by(-1))
        self.increment.released.connect(self._finish)
        self.decrement.released.connect(self._finish)
        self.editor.editingFinished.connect(self._commit_text)
        self.setFocusProxy(self.editor)
        self.setValue(value)

    def value(self):
        return self._value

    def setValue(self, value):
        bounded = min(self._maximum, max(self._minimum, float(value)))
        normalized = int(round(bounded)) if self._integer else round(bounded, self._decimals)
        changed = normalized != self._value
        self._value = normalized
        self.editor.setText(self._format(normalized))
        if changed:
            self.valueChanged.emit(normalized)

    def setRange(self, minimum: float, maximum: float):
        self._minimum, self._maximum = minimum, maximum
        self.setValue(self._value)

    def minimum(self):
        return self._minimum

    def maximum(self):
        return self._maximum

    def setSingleStep(self, step: float):
        self._step = step

    def singleStep(self):
        return self._step

    def setDecimals(self, decimals: int):
        self._decimals = decimals
        self._integer = decimals == 0
        self.setValue(self._value)

    def decimals(self):
        return self._decimals

    def _format(self, value):
        return str(int(value)) if self._integer else f"{float(value):.{self._decimals}f}"

    def _begin(self):
        if not self._editing:
            self._editing = True
            self.editStarted.emit()

    def _finish(self):
        if self._editing:
            self._editing = False
            self.editFinished.emit()

    def _step_by(self, direction: int):
        self.setValue(self._value + direction * self._step)

    def _commit_text(self):
        try:
            value = float(self.editor.text().strip())
        except ValueError:
            self.editor.setText(self._format(self._value))
            return
        self.setValue(value)

    def keyPressEvent(self, event: QKeyEvent):
        if event.key() in {Qt.Key.Key_Up, Qt.Key.Key_Down}:
            self._begin()
            self._step_by(1 if event.key() == Qt.Key.Key_Up else -1)
            event.accept()
            return
        super().keyPressEvent(event)

    def keyReleaseEvent(self, event: QKeyEvent):
        if event.key() in {Qt.Key.Key_Up, Qt.Key.Key_Down}:
            self._finish()
            event.accept()
            return
        super().keyReleaseEvent(event)

    def eventFilter(self, watched, event):
        if watched is self.editor and event.type() == QEvent.Type.KeyPress:
            if event.key() in {Qt.Key.Key_Up, Qt.Key.Key_Down}:
                self._begin()
                self._step_by(1 if event.key() == Qt.Key.Key_Up else -1)
                return True
        elif watched is self.editor and event.type() == QEvent.Type.KeyRelease:
            if event.key() in {Qt.Key.Key_Up, Qt.Key.Key_Down}:
                self._finish()
                return True
        return super().eventFilter(watched, event)
