from __future__ import annotations

import numpy as np
from PySide6.QtCore import QRect, QSize, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPixmap
from PySide6.QtWidgets import QWidget

from archetexture.render.engine import RenderResult
from archetexture.render.pixels import rgba_float_to_uint8


class TextureViewport(QWidget):
    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setMinimumSize(320, 240)
        self._pixmap = QPixmap()
        self._message = "Render a recipe to see its texture."
        self._rgba: np.ndarray | None = None

    @property
    def rendered_field(self) -> np.ndarray | None:
        return self._rgba

    def set_result(self, result: RenderResult) -> None:
        rgba = np.ascontiguousarray(np.clip(result.rgba_field, 0.0, 1.0))
        height, width, _ = rgba.shape
        pixels = rgba_float_to_uint8(rgba)
        image = QImage(
            pixels.data,
            width,
            height,
            width * 4,
            QImage.Format.Format_RGBA8888,
        ).copy()
        self._pixmap = QPixmap.fromImage(image)
        self._rgba = rgba.copy()
        self._message = ""
        self.update()

    def set_error(self, message: str) -> None:
        self._pixmap = QPixmap()
        self._rgba = None
        self._message = message
        self.update()

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        dark_mode = self.palette().color(self.palette().ColorRole.Window).lightness() < 128
        background = QColor("#202329") if dark_mode else QColor("#d8dce2")
        light = QColor("#30343b") if dark_mode else QColor("#eef0f3")
        dark = QColor("#272a30") if dark_mode else QColor("#dfe3e8")
        painter.fillRect(self.rect(), background)
        tile_size = 18
        for row in range(0, self.height(), tile_size):
            for column in range(0, self.width(), tile_size):
                color = light if (row // tile_size + column // tile_size) % 2 == 0 else dark
                painter.fillRect(QRect(column, row, tile_size, tile_size), color)
        if self._pixmap.isNull():
            painter.setPen(self.palette().color(self.palette().ColorRole.Text))
            painter.drawText(
                self.rect(),
                Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap,
                self._message,
            )
            return
        available = self.size() - QSize(24, 24)
        fitted = self._pixmap.scaled(
            available,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        target = QRect(
            (self.width() - fitted.width()) // 2,
            (self.height() - fitted.height()) // 2,
            fitted.width(),
            fitted.height(),
        )
        painter.drawPixmap(target, fitted)
