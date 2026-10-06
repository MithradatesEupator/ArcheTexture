from __future__ import annotations

import numpy as np
from PySide6.QtCore import QRect, QSize, Qt
from PySide6.QtGui import QImage, QPainter, QPixmap
from PySide6.QtWidgets import QWidget

from archetexture.render.engine import RenderResult
from archetexture.render.pixels import rgba_float_to_uint8
from archetexture.ui.theme import workspace_checkerboard_colors


def seam_check_rgba(rgba: np.ndarray) -> np.ndarray:
    """Return a half-width/half-height wrapped presentation copy of one RGBA tile."""
    height, width = rgba.shape[:2]
    return np.roll(rgba, shift=(height // 2, width // 2), axis=(0, 1))


class TextureViewport(QWidget):
    DISPLAY_MODES = ("single", "tile_3x3", "seam_check")

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setMinimumSize(320, 240)
        self._pixmap = QPixmap()
        self._presentation_pixmap = QPixmap()
        self._display_mode = "single"
        self._message = "Render a recipe to see its texture."
        self._rgba: np.ndarray | None = None

    @property
    def rendered_field(self) -> np.ndarray | None:
        return self._rgba

    @property
    def display_mode(self) -> str:
        return self._display_mode

    def set_display_mode(self, mode: str) -> None:
        if mode not in self.DISPLAY_MODES:
            raise ValueError(f"Unknown viewport display mode: {mode}")
        if mode == self._display_mode:
            return
        self._display_mode = mode
        self._update_presentation_pixmap()
        self.update()

    def set_result(self, result: RenderResult) -> None:
        rgba = np.ascontiguousarray(np.clip(result.rgba_field, 0.0, 1.0))
        self._pixmap = self._pixmap_from_rgba(rgba)
        self._rgba = rgba.copy()
        self._message = ""
        self._update_presentation_pixmap()
        self.update()

    @staticmethod
    def _pixmap_from_rgba(rgba: np.ndarray) -> QPixmap:
        height, width, _ = rgba.shape
        pixels = rgba_float_to_uint8(rgba)
        image = QImage(
            pixels.data,
            width,
            height,
            width * 4,
            QImage.Format.Format_RGBA8888,
        ).copy()
        return QPixmap.fromImage(image)

    def _update_presentation_pixmap(self) -> None:
        if self._rgba is None or self._display_mode != "seam_check":
            self._presentation_pixmap = self._pixmap
            return
        shifted = seam_check_rgba(self._rgba)
        self._presentation_pixmap = self._pixmap_from_rgba(shifted)

    def set_error(self, message: str) -> None:
        self._pixmap = QPixmap()
        self._presentation_pixmap = QPixmap()
        self._rgba = None
        self._message = message
        self.update()

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        background, light, dark = workspace_checkerboard_colors(self.palette())
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
        if self._display_mode == "tile_3x3":
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
            bounds = self.rect().adjusted(12, 12, -12, -12)
            for target in self.tile_preview_rects(bounds, self._pixmap.size()):
                painter.drawPixmap(target, self._pixmap)
            return
        available = self.size() - QSize(24, 24)
        fitted = self._presentation_pixmap.scaled(
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

    @staticmethod
    def tile_preview_rects(available: QRect, image_size: QSize) -> tuple[QRect, ...]:
        """Fit a 3x3 repeated-tile grid into the same viewport bounds as Single mode."""
        tile_bounds = QSize(max(1, available.width() // 3), max(1, available.height() // 3))
        tile_size = image_size.scaled(tile_bounds, Qt.AspectRatioMode.KeepAspectRatio)
        grid_width, grid_height = tile_size.width() * 3, tile_size.height() * 3
        origin_x = available.left() + (available.width() - grid_width) // 2
        origin_y = available.top() + (available.height() - grid_height) // 2
        return tuple(
            QRect(
                origin_x + column * tile_size.width(),
                origin_y + row * tile_size.height(),
                tile_size.width(),
                tile_size.height(),
            )
            for row in range(3)
            for column in range(3)
        )
