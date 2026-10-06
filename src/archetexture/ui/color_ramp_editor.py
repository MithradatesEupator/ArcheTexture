from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRect, Qt, Signal
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import (
    QColorDialog,
    QDoubleSpinBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from archetexture.color.ramp import ColorRamp, ColorStop
from archetexture.ui.theme import ramp_checkerboard_colors


class _RampPositionSpinBox(QDoubleSpinBox):
    def wheelEvent(self, event) -> None:
        if self.hasFocus():
            super().wheelEvent(event)
        else:
            event.ignore()


class RampPreview(QWidget):
    """Paint a checkerboard-backed ramp and draggable stop handles."""

    dragFinished = Signal(object)
    stopSelected = Signal(int)
    rampPreviewed = Signal(object)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("color-ramp-preview")
        self.setMinimumHeight(62)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._ramp: ColorRamp | None = None
        self._selected_index: int | None = None
        self._drag_original: ColorRamp | None = None
        self._drag_changed = False

    @property
    def ramp(self) -> ColorRamp | None:
        return self._ramp

    @property
    def displayed_stops(self) -> tuple[ColorStop, ...]:
        return tuple(sorted(self._ramp.stops, key=lambda stop: stop.position)) if self._ramp else ()

    def set_ramp(self, ramp: ColorRamp | None, selected_index: int | None) -> None:
        self._ramp = ramp
        self._selected_index = selected_index
        self.update()

    def track_rect(self) -> QRect:
        left = 9
        right = max(left + 1, self.width() - 10)
        return QRect(left, 5, right - left, 34)

    def position_from_x(self, x: float) -> float:
        track = self.track_rect()
        return min(1.0, max(0.0, (x - track.left()) / max(1, track.width())))

    def x_from_position(self, position: float) -> float:
        track = self.track_rect()
        return track.left() + min(1.0, max(0.0, position)) * track.width()

    @staticmethod
    def _qcolor(color: tuple[float, float, float, float]) -> QColor:
        return QColor.fromRgbF(*color)

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        palette = self.palette()
        painter.fillRect(self.rect(), palette.color(palette.ColorRole.Window))
        track = self.track_rect()
        tile = 9
        checker_light, checker_dark = ramp_checkerboard_colors(palette)
        for y in range(track.top(), track.bottom() + 1, tile):
            for x in range(track.left(), track.right() + 1, tile):
                shade = (
                    checker_light
                    if ((x - track.left()) // tile + (y - track.top()) // tile) % 2 == 0
                    else checker_dark
                )
                painter.fillRect(QRect(x, y, tile, tile).intersected(track), shade)

        stops = self.displayed_stops
        if stops:
            gradient = QLinearGradient(
                QPointF(track.left(), track.center().y()),
                QPointF(track.right(), track.center().y()),
            )
            if len(stops) == 1:
                color = self._qcolor(stops[0].color)
                gradient.setColorAt(0.0, color)
                gradient.setColorAt(1.0, color)
            else:
                for stop in stops:
                    gradient.setColorAt(stop.position, self._qcolor(stop.color))
            painter.fillRect(track, gradient)
        else:
            painter.setPen(palette.color(palette.ColorRole.Text))
            painter.drawText(track, Qt.AlignmentFlag.AlignCenter, "Grayscale output")

        painter.setPen(QPen(palette.color(palette.ColorRole.Mid), 1))
        painter.drawRect(track)
        for index, stop in enumerate(stops):
            x = self.x_from_position(stop.position)
            center_y = track.bottom() + 9
            radius = 7
            diamond = QPolygonF(
                [
                    QPointF(x, center_y - radius),
                    QPointF(x + radius, center_y),
                    QPointF(x, center_y + radius),
                    QPointF(x - radius, center_y),
                ]
            )
            selected = index == self._selected_index
            outline = palette.color(
                palette.ColorRole.HighlightedText if selected else palette.ColorRole.Window
            )
            fill = palette.color(
                palette.ColorRole.Highlight if selected else palette.ColorRole.WindowText
            )
            painter.setPen(QPen(outline, 1.5 if selected else 1))
            painter.setBrush(fill)
            painter.drawPolygon(diamond)

    def _hit_test(self, x: float, y: float) -> int | None:
        track = self.track_rect()
        if y < track.bottom() - 3 or y > track.bottom() + 19:
            return None
        candidates = [
            (abs(self.x_from_position(stop.position) - x), index)
            for index, stop in enumerate(self.displayed_stops)
        ]
        if not candidates:
            return None
        distance, index = min(candidates)
        return index if distance <= 10 else None

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            index = self._hit_test(event.position().x(), event.position().y())
            if index is not None:
                self._selected_index = index
                self._drag_original = self._ramp
                self._drag_changed = False
                self.stopSelected.emit(index)
                self.update()
                event.accept()
                return
        super().mousePressEvent(event)

    @staticmethod
    def _constrain_position(stops: tuple[ColorStop, ...], index: int, position: float) -> float:
        lower = 0.0 if index == 0 else math.nextafter(stops[index - 1].position, 1.0)
        upper = 1.0 if index == len(stops) - 1 else math.nextafter(stops[index + 1].position, 0.0)
        return min(upper, max(lower, position))

    def mouseMoveEvent(self, event) -> None:
        if self._drag_original is None or not (event.buttons() & Qt.MouseButton.LeftButton):
            super().mouseMoveEvent(event)
            return
        stops = self.displayed_stops
        index = self._selected_index
        if index is None or not stops:
            return
        position = self._constrain_position(
            stops, index, self.position_from_x(event.position().x())
        )
        if position == stops[index].position:
            return
        moved = ColorStop(position, stops[index].color)
        updated = list(stops)
        updated[index] = moved
        updated.sort(key=lambda stop: stop.position)
        self._ramp = ColorRamp(tuple(updated))
        self._selected_index = updated.index(moved)
        self._drag_changed = self._ramp != self._drag_original
        self.rampPreviewed.emit(self._ramp)
        self.update()

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self._drag_original is not None:
            if self._drag_changed and self._ramp is not None:
                self.dragFinished.emit(self._ramp)
            self._drag_original = None
            self._drag_changed = False
            event.accept()
            return
        super().mouseReleaseEvent(event)


class ColorRampEditor(QWidget):
    """Compact editor whose ramp changes are committed by the owning document."""

    rampEdited = Signal(object)
    previewRequested = Signal(object)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("color-ramp-editor")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._ramp: ColorRamp | None = None
        self._selected_key: tuple[float, tuple[float, float, float, float]] | None = None
        self._selection_restore_key: tuple[float, tuple[float, float, float, float]] | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 4, 6, 5)
        layout.setSpacing(3)

        actions = QHBoxLayout()
        actions.setSpacing(5)
        title = QLabel("COLOR RAMP")
        title.setObjectName("color-ramp-title")
        actions.addWidget(title)
        actions.addStretch(1)
        self.create_button = QPushButton("Create color ramp")
        self.create_button.setObjectName("create-color-ramp")
        self.add_button = QPushButton("Add stop")
        self.add_button.setObjectName("add-color-stop")
        self.remove_stop_button = QPushButton("Remove stop")
        self.remove_stop_button.setObjectName("remove-color-stop")
        self.remove_ramp_button = QPushButton("Remove color ramp")
        self.remove_ramp_button.setObjectName("remove-color-ramp")
        for button in (
            self.create_button,
            self.add_button,
            self.remove_stop_button,
            self.remove_ramp_button,
        ):
            button.setMinimumHeight(25)
            actions.addWidget(button)
        layout.addLayout(actions)

        self.preview = RampPreview(self)
        self.preview.stopSelected.connect(self._select_index)
        self.preview.rampPreviewed.connect(self._preview_position)
        self.preview.dragFinished.connect(self._commit_drag_position)
        layout.addWidget(self.preview)

        controls = QHBoxLayout()
        controls.setSpacing(6)
        controls.addWidget(QLabel("Selected stop position"))
        self.position_spin = _RampPositionSpinBox()
        self.position_spin.setObjectName("ramp-position")
        self.position_spin.setDecimals(6)
        self.position_spin.setSingleStep(0.001)
        self.position_spin.setRange(0.0, 1.0)
        self.position_spin.setFixedWidth(112)
        controls.addWidget(self.position_spin)
        self.color_button = QPushButton("Edit color…")
        self.color_button.setObjectName("ramp-color-button")
        self.color_button.setMinimumWidth(130)
        controls.addWidget(self.color_button)
        controls.addStretch(1)
        layout.addLayout(controls)

        self.create_button.clicked.connect(self.create_ramp)
        self.add_button.clicked.connect(self.add_stop)
        self.remove_stop_button.clicked.connect(self.remove_stop)
        self.remove_ramp_button.clicked.connect(self.remove_ramp)
        self.position_spin.valueChanged.connect(self._position_changed)
        self.color_button.clicked.connect(self.choose_color)
        self.set_ramp(None, reset_selection=True)

    @property
    def ramp(self) -> ColorRamp | None:
        return self._ramp

    @property
    def selected_stop(self) -> ColorStop | None:
        stops = self._stops()
        index = self._selected_index()
        return stops[index] if index is not None else None

    @staticmethod
    def default_ramp() -> ColorRamp:
        return ColorRamp(
            (
                ColorStop(0.0, (0.0, 0.0, 0.0, 1.0)),
                ColorStop(1.0, (1.0, 1.0, 1.0, 1.0)),
            )
        )

    def _stops(self) -> tuple[ColorStop, ...]:
        return tuple(sorted(self._ramp.stops, key=lambda stop: stop.position)) if self._ramp else ()

    def _selected_index(self) -> int | None:
        if self._selected_key is None:
            return None
        return next(
            (
                index
                for index, stop in enumerate(self._stops())
                if (stop.position, stop.color) == self._selected_key
            ),
            None,
        )

    def set_ramp(self, ramp: ColorRamp | None, *, reset_selection: bool = False) -> None:
        if reset_selection:
            self._selection_restore_key = None
        old_key = None if reset_selection else self._selected_key
        self._ramp = ramp
        stops = self._stops()
        if not stops:
            self._selected_key = None
        elif self._selection_restore_key in {(stop.position, stop.color) for stop in stops}:
            self._selected_key = self._selection_restore_key
            self._selection_restore_key = None
        elif old_key is not None:
            exact = next(
                (stop for stop in stops if (stop.position, stop.color) == old_key),
                None,
            )
            surviving = exact or min(
                stops, key=lambda stop: (abs(stop.position - old_key[0]), stop.position)
            )
            self._selected_key = (surviving.position, surviving.color)
        else:
            self._selected_key = (stops[0].position, stops[0].color)
        self.preview.set_ramp(self._ramp, self._selected_index())
        self._sync_controls()

    def _sync_controls(self) -> None:
        stops = self._stops()
        selected = self.selected_stop
        has_ramp = self._ramp is not None
        self.create_button.setVisible(not has_ramp)
        self.add_button.setEnabled(has_ramp and self._largest_gap() is not None)
        self.remove_stop_button.setEnabled(has_ramp and len(stops) > 1)
        self.remove_ramp_button.setEnabled(has_ramp)
        self.position_spin.blockSignals(True)
        self.color_button.setEnabled(selected is not None)
        self.position_spin.setEnabled(selected is not None)
        if selected is None:
            self.position_spin.setRange(0.0, 1.0)
            self.position_spin.setValue(0.0)
            self.color_button.setStyleSheet("")
            self.color_button.setToolTip("Create a color ramp to edit stop colors")
        else:
            index = self._selected_index()
            lower = 0.0 if index == 0 else stops[index - 1].position + 0.000001
            upper = 1.0 if index == len(stops) - 1 else stops[index + 1].position - 0.000001
            if lower > upper:
                self.position_spin.setEnabled(False)
                self.position_spin.setRange(0.0, 1.0)
            else:
                self.position_spin.setRange(lower, upper)
            self.position_spin.setValue(selected.position)
            red, green, blue, alpha = (round(channel * 255) for channel in selected.color)
            luminance = (
                0.2126 * selected.color[0] + 0.7152 * selected.color[1] + 0.0722 * selected.color[2]
            )
            text_color = "#ffffff" if luminance < 0.45 else "#111827"
            self.color_button.setStyleSheet(
                "QPushButton {"
                f" background-color: rgba({red}, {green}, {blue}, {alpha});"
                f" color: {text_color}; border: 1px solid #525a66;"
                " }"
            )
            self.color_button.setToolTip(
                f"RGBA {selected.color[0]:.3f}, {selected.color[1]:.3f}, "
                f"{selected.color[2]:.3f}, {selected.color[3]:.3f}"
            )
        self.position_spin.blockSignals(False)
        self.preview.set_ramp(self._ramp, self._selected_index())

    def _select_index(self, index: int) -> None:
        stops = self._stops()
        if 0 <= index < len(stops):
            stop = stops[index]
            self._selected_key = (stop.position, stop.color)
            self._sync_controls()

    def _preview_position(self, ramp: ColorRamp) -> None:
        index = self.preview._selected_index
        stops = tuple(sorted(ramp.stops, key=lambda stop: stop.position))
        if index is None or not 0 <= index < len(stops):
            return
        if self._selection_restore_key is None and self._selected_key is not None:
            self._selection_restore_key = self._selected_key
        self._ramp = ramp
        selected = stops[index]
        self._selected_key = (selected.position, selected.color)
        self._sync_controls()
        self.previewRequested.emit(ramp)

    def _position_changed(self, position: float) -> None:
        stops = self._stops()
        index = self._selected_index()
        if index is None or self._ramp is None:
            return
        position = min(1.0, max(0.0, position))
        candidate = RampPreview._constrain_position(stops, index, position)
        if candidate == stops[index].position:
            return
        updated = list(stops)
        stop = ColorStop(candidate, updated[index].color)
        updated[index] = stop
        updated.sort(key=lambda item: item.position)
        self._ramp = ColorRamp(tuple(updated))
        self._selected_key = (stop.position, stop.color)
        self._sync_controls()
        self.rampEdited.emit(self._ramp)

    def _commit_drag_position(self, ramp: ColorRamp) -> None:
        self._ramp = ramp
        index = self.preview._selected_index
        stops = tuple(sorted(ramp.stops, key=lambda stop: stop.position))
        if index is not None and 0 <= index < len(stops):
            selected = stops[index]
            self._selected_key = (selected.position, selected.color)
        self._sync_controls()
        self.rampEdited.emit(ramp)

    def _largest_gap(self) -> tuple[float, float] | None:
        stops = self._stops()
        if not stops:
            return None
        gaps: list[tuple[float, float]] = []
        if stops[0].position > 0.0:
            gaps.append((0.0, stops[0].position))
        gaps.extend(
            (left.position, right.position) for left, right in zip(stops, stops[1:], strict=False)
        )
        if stops[-1].position < 1.0:
            gaps.append((stops[-1].position, 1.0))
        if not gaps:
            return None
        left, right = max(gaps, key=lambda gap: gap[1] - gap[0])
        midpoint = left + (right - left) / 2.0
        if midpoint <= left or midpoint >= right:
            midpoint = math.nextafter(left, right)
        return (left, right) if left < midpoint < right else None

    def create_ramp(self) -> None:
        if self._ramp is None:
            self._selected_key = None
            self.rampEdited.emit(self.default_ramp())

    def remove_ramp(self) -> None:
        if self._ramp is not None:
            self._selected_key = None
            self.rampEdited.emit(None)

    def add_stop(self) -> None:
        if self._ramp is None:
            self.create_ramp()
            return
        gap = self._largest_gap()
        if gap is None:
            return
        left, right = gap
        position = left + (right - left) / 2.0
        if position <= left or position >= right:
            position = math.nextafter(left, right)
        if any(stop.position == position for stop in self._stops()):
            return
        stop = ColorStop(position, self._ramp.sample(position))
        updated = sorted((*self._stops(), stop), key=lambda item: item.position)
        self._ramp = ColorRamp(tuple(updated))
        self._selected_key = (stop.position, stop.color)
        self._sync_controls()
        self.rampEdited.emit(self._ramp)

    def remove_stop(self) -> None:
        stops = self._stops()
        index = self._selected_index()
        if self._ramp is None or index is None or len(stops) <= 1:
            return
        removed = list(stops)
        removed.pop(index)
        selected = removed[min(index, len(removed) - 1)]
        self._ramp = ColorRamp(tuple(removed))
        self._selected_key = (selected.position, selected.color)
        self._sync_controls()
        self.rampEdited.emit(self._ramp)

    def choose_color(self) -> None:
        stop = self.selected_stop
        if stop is None:
            return
        initial = QColor.fromRgbF(*stop.color)
        color = QColorDialog.getColor(
            initial,
            self,
            "Choose stop color",
            QColorDialog.ColorDialogOption.ShowAlphaChannel,
        )
        if not color.isValid():
            return
        updated_color = (color.redF(), color.greenF(), color.blueF(), color.alphaF())
        if updated_color == stop.color:
            return
        stops = list(self._stops())
        selected = ColorStop(stop.position, updated_color)
        stops[self._selected_index()] = selected
        self._ramp = ColorRamp(tuple(stops))
        self._selected_key = (selected.position, selected.color)
        self._sync_controls()
        self.rampEdited.emit(self._ramp)
