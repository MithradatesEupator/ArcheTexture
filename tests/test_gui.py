from __future__ import annotations

from PySide6.QtWidgets import QApplication

from archetexture.ui.main_window import build_main_window


def test_main_window_smoke(qtbot):
    QApplication.instance() or QApplication([])
    win = build_main_window()
    qtbot.addWidget(win)
    win.show()
    assert win.isVisible()
    assert win.windowTitle() == "ArcheTexture"
