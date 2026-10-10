from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, QTimer
from PySide6.QtWidgets import QApplication, QToolTip, QWidget


class DelayedHelp(QObject):
    """Show registered plain-language help only after a deliberate hover."""

    def __init__(self, parent: QWidget, delay_ms: int = 950):
        super().__init__(parent)
        application = QApplication.instance()
        if application is not None:
            application.installEventFilter(self)
        self._delay_ms = delay_ms
        self._pending: QWidget | None = None
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(delay_ms)
        self._timer.timeout.connect(self._show)
        application.installEventFilter(self)

    @staticmethod
    def register(widget: QWidget, text: str) -> None:
        widget.setProperty("delayedHelpText", text)
        help_system = widget.window().findChild(DelayedHelp)
        if help_system is not None:
            widget.installEventFilter(help_system)

    def eventFilter(self, watched, event):
        if event.type() in {QEvent.Type.Enter, QEvent.Type.MouseMove} and isinstance(
            watched, QWidget
        ):
            if (
                watched.window() is self.parent()
                and watched.property("delayedHelpText")
                and self._pending is not watched
            ):
                self._pending = watched
                self._timer.start(self._delay_ms)
        elif event.type() in {QEvent.Type.Leave, QEvent.Type.MouseButtonPress}:
            if watched is self._pending or event.type() == QEvent.Type.MouseButtonPress:
                self._timer.stop()
                self._pending = None
                QToolTip.hideText()
        return False

    def _show(self) -> None:
        widget = self._pending
        if widget is None or not widget.isVisible():
            return
        text = widget.property("delayedHelpText")
        if text:
            position = widget.mapToGlobal(widget.rect().center())
            QToolTip.showText(position, str(text), widget)
