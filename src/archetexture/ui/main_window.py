from __future__ import annotations

import os

from PySide6.QtWidgets import QApplication, QLabel, QMainWindow, QSplitter, QWidget


def build_main_window() -> QMainWindow:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    QApplication.instance() or QApplication([])
    window = QMainWindow()
    window.setWindowTitle("ArcheTexture")
    window.resize(1200, 800)

    central = QWidget()
    splitter = QSplitter()
    left = QLabel("Pipeline")
    middle = QLabel("Viewport")
    right = QLabel("Properties")
    splitter.addWidget(left)
    splitter.addWidget(middle)
    splitter.addWidget(right)
    central_layout = None
    from PySide6.QtWidgets import QHBoxLayout
    central_layout = QHBoxLayout(central)
    central_layout.addWidget(splitter)
    window.setCentralWidget(central)
    return window


def main() -> int:
    app = QApplication.instance() or QApplication([])
    window = build_main_window()
    window.show()
    return app.exec()
