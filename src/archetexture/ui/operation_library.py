"""Visual browser for registered material operations and editable starters."""

from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import dataclass, field

import numpy as np
from PySide6.QtCore import QObject, QRunnable, Qt, QThreadPool, Signal
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import (
    QComboBox,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from archetexture.color.ramp import ColorRamp, ColorStop
from archetexture.core.material_starters import MATERIAL_STARTERS, create_material_starter
from archetexture.core.outputs import semantic_definition
from archetexture.core.recipe import (
    LayerRecipe,
    MaterialOutputRecipe,
    OperationInstance,
    ProjectRecipe,
)
from archetexture.core.registry import REGISTRY
from archetexture.render.engine import RenderEngine


@dataclass(frozen=True)
class LibraryPreset:
    name: str
    operation_id: str
    category: str
    description: str
    parameters: dict[str, object] = field(default_factory=dict)
    palette_name: str = "Earth"
    palette: tuple[tuple[float, float, float, float], ...] = (
        (0.055, 0.035, 0.025, 1.0),
        (0.34, 0.16, 0.075, 1.0),
        (0.78, 0.53, 0.27, 1.0),
    )
    tileability: str = "Depends on settings"


_EARTH = (
    (0.055, 0.035, 0.025, 1.0),
    (0.34, 0.16, 0.075, 1.0),
    (0.78, 0.53, 0.27, 1.0),
)
_STONE = ((0.035, 0.045, 0.055, 1.0), (0.31, 0.34, 0.35, 1.0), (0.84, 0.86, 0.82, 1.0))
_COOL = ((0.025, 0.055, 0.11, 1.0), (0.07, 0.37, 0.56, 1.0), (0.45, 0.86, 0.88, 1.0))
_COLORFUL = ((0.08, 0.035, 0.16, 1.0), (0.74, 0.08, 0.30, 1.0), (1.0, 0.72, 0.14, 1.0))


def _preset(
    name,
    operation_id,
    category,
    description,
    parameters=None,
    palette_name="Earth",
    palette=_EARTH,
    tileability="Depends on settings",
):
    return LibraryPreset(
        name,
        operation_id,
        category,
        description,
        parameters or {},
        palette_name,
        palette,
        tileability,
    )


# Curated examples stay separate from operation implementations. Parameters are
# validated and clamped to the registered operation's schema when recipes build.
OPERATION_PRESETS = (
    _preset(
        "Linear Gradient",
        "generator.linear_gradient",
        "Gradients and Colors",
        "A directional color transition.",
        {"angle": 30},
        "Sunset",
        _COLORFUL,
        "Not seamless by default",
    ),
    _preset(
        "Radial Gradient",
        "generator.radial_gradient",
        "Gradients and Colors",
        "A centered radial falloff.",
        {"radius": 0.72},
        "Ocean",
        _COOL,
        "Not seamless by default",
    ),
    _preset(
        "Solid Color",
        "generator.constant",
        "Gradients and Colors",
        "A uniform color field.",
        {"value": 0.55},
        "Ocean",
        _COOL,
        "Seamless",
    ),
    _preset(
        "Checker Grid",
        "generator.checker_grid",
        "Patterns",
        "Alternating cells with adjustable grid and pattern.",
        {"cells_x": 8, "cells_y": 8},
        "Color",
        _COLORFUL,
        "Seamless with integer cell counts",
    ),
    _preset(
        "Bands",
        "generator.bands",
        "Patterns",
        "Repeated wave or band structures.",
        {"frequency": 10, "angle": 25},
        "Ocean",
        _COOL,
    ),
    _preset(
        "Brick · Standard",
        "generator.brick",
        "Patterns",
        "Running bond with standard brick proportions.",
        {"columns": 6, "rows": 10},
        "Brick",
        _EARTH,
        "Seamless when rows and columns wrap",
    ),
    _preset(
        "Brick · Narrow",
        "generator.brick",
        "Patterns",
        "A finer running-bond brick pattern.",
        {"columns": 9, "rows": 15, "mortar": 0.045},
        "Brick",
        _EARTH,
        "Seamless when rows and columns wrap",
    ),
    _preset(
        "Brick · Large",
        "generator.brick",
        "Patterns",
        "Broad masonry blocks with visible mortar.",
        {"columns": 4, "rows": 7, "mortar": 0.07},
        "Brick",
        _EARTH,
        "Seamless when rows and columns wrap",
    ),
    _preset(
        "Hexagonal Cells",
        "generator.hex_cells",
        "Patterns",
        "Interlocking honeycomb cells.",
        {"density": 9},
        "Ceramic",
        _COOL,
    ),
    _preset(
        "Truchet Tiles",
        "generator.truchet",
        "Patterns",
        "Seeded quarter-arc tile motifs.",
        {"density": 8},
        "Color",
        _COLORFUL,
    ),
    _preset(
        "Polka Dots",
        "generator.polka_dots",
        "Patterns",
        "Staggered circular dots on a field.",
        {"columns": 8, "rows": 8},
        "Color",
        _COLORFUL,
        "Repeats by cell count",
    ),
    _preset(
        "Concentric Rings",
        "generator.concentric_rings",
        "Patterns",
        "Nested circular rings.",
        {"frequency": 9},
        "Ocean",
        _COOL,
    ),
    _preset(
        "Radial Spokes",
        "generator.radial_spokes",
        "Patterns",
        "Rotating spokes radiating from a center.",
        {"spokes": 18},
        "Color",
        _COLORFUL,
    ),
    _preset(
        "Crosshatch",
        "generator.crosshatch",
        "Patterns",
        "Crossed etched lines.",
        {"frequency": 14},
        "Fabric",
        _EARTH,
    ),
    _preset(
        "Weave",
        "generator.weave",
        "Patterns",
        "Alternating over-under textile threads.",
        {"threads_x": 12, "threads_y": 12},
        "Fabric",
        _COOL,
        "Repeats by thread count",
    ),
    _preset(
        "Wood · Fine Grain",
        "generator.wood_rings",
        "Patterns",
        "Fine growth rings with subtle distortion.",
        {"rings": 28, "distortion": 0.25},
        "Wood",
        _EARTH,
    ),
    _preset(
        "Wood · Broad Rings",
        "generator.wood_rings",
        "Patterns",
        "Broad growth rings with stronger warping.",
        {"rings": 12, "distortion": 0.3},
        "Wood",
        _EARTH,
    ),
    _preset(
        "Marble · Fine Veins",
        "generator.marble_veins",
        "Patterns",
        "Fine branching veins in stone.",
        {"scale": 3.5, "vein_frequency": 12},
        "Marble",
        _STONE,
    ),
    _preset(
        "Marble · Broad Veins",
        "generator.marble_veins",
        "Patterns",
        "Broad flowing mineral veins.",
        {"scale": 2.1, "vein_frequency": 5},
        "Marble",
        _STONE,
    ),
    _preset(
        "Cellular",
        "generator.cellular",
        "Patterns",
        "Voronoi-like cells with adjustable distance mode.",
        {"scale": 8},
        "Stone",
        _STONE,
    ),
    _preset(
        "Fractal Noise",
        "generator.fractal_noise",
        "Patterns",
        "Layered smooth noise for clouds and mottled surfaces.",
        {"scale": 4.2, "octaves": 5},
        "Stone",
        _STONE,
    ),
    _preset(
        "Ridged Noise",
        "generator.ridged_noise",
        "Patterns",
        "Ridge-focused multifractal terrain.",
        {"scale": 4.5, "octaves": 5},
        "Stone",
        _STONE,
    ),
    _preset(
        "Billow Noise",
        "generator.billow_noise",
        "Patterns",
        "Soft rounded multifractal forms.",
        {"scale": 4.5, "octaves": 5},
        "Color",
        _COLORFUL,
    ),
    _preset(
        "Perlin Noise",
        "generator.perlin_noise",
        "Patterns",
        "Directional gradient noise.",
        {"scale": 5.0},
        "Ocean",
        _COOL,
    ),
    _preset(
        "Domain Warp",
        "generator.domain_warp",
        "Patterns",
        "Noise coordinates bent for flowing organic patterns.",
        {"scale": 4.0, "frequency": 3.0, "warp_amount": 0.65},
        "Color",
        _COLORFUL,
    ),
)


def operation_recipe(
    preset: LibraryPreset, *, width: int = 128, height: int = 128, seed: int = 23
) -> ProjectRecipe:
    definition = REGISTRY.get(preset.operation_id)
    parameters = {spec.identifier: spec.default for spec in definition.parameter_specs}
    parameters.update(preset.parameters)
    instance = OperationInstance(
        "library-source", preset.operation_id, definition.version, parameters=parameters
    )
    stops = tuple(
        ColorStop(i / (len(preset.palette) - 1), color) for i, color in enumerate(preset.palette)
    )
    ramp = ColorRamp(stops) if definition.output_type == "scalar" else None
    layer = LayerRecipe("library-layer", preset.name, instance, color_ramp=ramp)
    output_def = semantic_definition("base_color")
    output = MaterialOutputRecipe(
        "library-output", "Base Color", "base_color", output_def.value_type, [layer]
    )
    return ProjectRecipe(width=width, height=height, seed=seed, outputs=[output])


def starter_recipe(name: str, *, width: int = 128, height: int = 128) -> ProjectRecipe:
    recipe = create_material_starter(name, width=width, height=height)
    recipe.seed = 23
    return recipe


def _recipe_for_key(key: str) -> ProjectRecipe:
    if key.startswith("starter:"):
        return starter_recipe(key.partition(":")[2].split(":", maxsplit=1)[0])
    preset_index = int(key.split(":", maxsplit=2)[1])
    return operation_recipe(OPERATION_PRESETS[preset_index])


def _preset_cache_key(index: int, preset: LibraryPreset) -> str:
    identity = {
        "operation": preset.operation_id,
        "parameters": preset.parameters,
        "palette": preset.palette,
        "seed": 23,
        "size": 128,
    }
    digest = hashlib.sha256(
        json.dumps(identity, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()[:16]
    return f"operation:{index}:{digest}"


class _RenderSignals(QObject):
    completed = Signal(str, object)


class _ThumbnailTask(QRunnable):
    def __init__(self, key: str, signals: _RenderSignals):
        super().__init__()
        self.key = key
        self.signals = signals

    def run(self) -> None:
        try:
            recipe = _recipe_for_key(self.key)
            engine = RenderEngine()
            if self.key.startswith("starter:"):
                base_color = next(
                    output for output in recipe.outputs if output.semantic == "base_color"
                )
                image = engine.render_output(
                    recipe, base_color.output_id, width=128, height=128
                ).rgba_field
            else:
                image = engine.render(recipe, width=128, height=128).rgba_field
            pixels = np.clip(image * 255.0 + 0.5, 0, 255).astype(np.uint8)
            self.signals.completed.emit(self.key, pixels.tobytes())
        except Exception as exc:  # Thumbnail failures stay visible in this library tile.
            self.signals.completed.emit(self.key, str(exc))


class OperationLibraryPanel(QWidget):
    """Searchable operation and starter browser with genuine rendered samples."""

    layerRequested = Signal(object)
    starterRequested = Signal(str)
    imageRequested = Signal()
    modeChanged = Signal(str)

    CATEGORIES = ("All", "Patterns", "Gradients and Colors", "Images", "Material Starters")
    _cache: dict[str, bytes] = {}
    _pending: set[str] = set()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("operation-library")
        self._signals = _RenderSignals(self)
        self._signals.completed.connect(self._thumbnail_ready)
        self._cards: dict[str, tuple[QLabel, QPushButton]] = {}
        self._selected_key: str | None = None
        self._selected_preset: LibraryPreset | None = None
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.addWidget(QLabel("BROWSE MATERIALS & OPERATIONS"))
        mode_row = QHBoxLayout()
        self.mode = QComboBox(self)
        self.mode.setObjectName("operation-library-context")
        self.mode.addItems(self.CATEGORIES[1:])
        self.mode.currentTextChanged.connect(self._rebuild)
        mode_row.addWidget(self.mode)
        root.addLayout(mode_row)
        self.search = QLineEdit(self)
        self.search.setObjectName("operation-library-search")
        self.search.setPlaceholderText("Search patterns, materials, and descriptions…")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._rebuild)
        root.addWidget(self.search)
        self.scroll = QScrollArea(self)
        self.scroll.setWidgetResizable(True)
        self.scroll.setMinimumHeight(170)
        self.grid_host = QWidget(self.scroll)
        self.grid = QGridLayout(self.grid_host)
        self.grid.setContentsMargins(2, 2, 2, 2)
        self.grid.setSpacing(6)
        self.scroll.setWidget(self.grid_host)
        self.scroll.verticalScrollBar().valueChanged.connect(self._schedule_visible)
        root.addWidget(self.scroll, 1)
        self.detail_title = QLabel("Choose an item")
        self.detail_title.setObjectName("operation-library-title")
        root.addWidget(self.detail_title)
        self.sample = QLabel("Rendered preview")
        self.sample.setObjectName("operation-library-sample")
        self.sample.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.sample.setMinimumSize(120, 100)
        self.sample.setMaximumHeight(170)
        self.sample.setScaledContents(True)
        root.addWidget(self.sample)
        self.description = QLabel(
            "Samples are rendered by ArcheTexture from deterministic recipes."
        )
        self.description.setWordWrap(True)
        self.description.setObjectName("operation-library-description")
        root.addWidget(self.description)
        self.palette_label = QLabel("")
        root.addWidget(self.palette_label)
        self.action = QPushButton("Add as Layer")
        self.action.setObjectName("operation-library-add")
        self.action.setMinimumHeight(36)
        self.action.setEnabled(False)
        self.action.clicked.connect(self._activate_selected)
        root.addWidget(self.action)
        self._rebuild()

    def _items(self):
        query = self.search.text().strip().casefold()
        context = self.mode.currentText()
        items: list[tuple[str, str, str, object]] = []
        if context in {"Patterns", "Gradients and Colors"}:
            for index, preset in enumerate(OPERATION_PRESETS):
                if preset.category == context:
                    items.append(
                        (_preset_cache_key(index, preset), preset.name, preset.description, preset)
                    )
        elif context == "Material Starters":
            for starter in MATERIAL_STARTERS:
                items.append(
                    (
                        f"starter:{starter.name}:seed-23:size-128",
                        starter.name,
                        starter.description,
                        starter,
                    )
                )
        elif context == "Images":
            items.append(
                ("image:import", "Import Image…", "Use an image file as a material layer.", None)
            )
        if query:
            items = [item for item in items if query in " ".join((item[1], item[2])).casefold()]
        return items

    def _rebuild(self, *_):
        while self.grid.count():
            item = self.grid.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._cards.clear()
        items = self._items()
        for index, (key, name, _description, _data) in enumerate(items):
            card = QPushButton(self.grid_host)
            card.setObjectName("operation-library-card")
            card.setCheckable(True)
            card.setMinimumSize(105, 90)
            card.setStyleSheet(
                "QPushButton { text-align: center; padding: 4px; }\n"
                "QPushButton:checked { border: 2px solid #63a8ff; }"
            )
            box = QVBoxLayout(card)
            thumb = QLabel("Rendering…", card)
            thumb.setMinimumSize(72, 54)
            thumb.setMaximumHeight(62)
            thumb.setAlignment(Qt.AlignmentFlag.AlignCenter)
            thumb.setScaledContents(True)
            label = QLabel(name, card)
            label.setWordWrap(True)
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            box.addWidget(thumb)
            box.addWidget(label)
            card.clicked.connect(lambda _checked=False, item_key=key: self._select(item_key))
            row, col = divmod(index, 3)
            self.grid.addWidget(card, row, col)
            self._cards[key] = (thumb, card)
            if key in self._cache:
                self._set_thumb(key, self._cache[key])
        self._schedule_visible()
        if self._selected_key not in self._cards:
            self._selected_key = None
            self._selected_preset = None
            self.action.setEnabled(False)
            self.detail_title.setText("Choose an item")
            self.description.setText(
                "Samples are rendered by ArcheTexture from deterministic recipes."
            )

    def _render_thumb(self, key: str):
        if key not in self._pending and key not in self._cache:
            self._pending.add(key)
            QThreadPool.globalInstance().start(_ThumbnailTask(key, self._signals))

    def _schedule_visible(self, *_):
        if not self.isVisible():
            return
        first_row = max(0, self.scroll.verticalScrollBar().value() // 100)
        last_row = first_row + 3
        for index, (key, _name, _description, _data) in enumerate(self._items()):
            row = index // 3
            if first_row <= row <= last_row and not key.startswith("image:"):
                self._render_thumb(key)

    def showEvent(self, event):
        super().showEvent(event)
        self._schedule_visible()

    def _thumbnail_ready(self, key: str, result):
        self._pending.discard(key)
        if isinstance(result, str):
            if key in self._cards:
                self._cards[key][0].setText("Preview unavailable")
                self._cards[key][0].setToolTip(result)
            return
        self._cache[key] = result
        if key in self._cards:
            self._set_thumb(key, result)
        if key == self._selected_key:
            self._set_sample(result)

    def _set_thumb(self, key: str, data: bytes):
        label = self._cards[key][0]
        image = QImage(data, 128, 128, 128 * 4, QImage.Format.Format_RGBA8888).copy()
        label.setPixmap(QPixmap.fromImage(image))

    def _set_sample(self, data: bytes):
        image = QImage(data, 128, 128, 128 * 4, QImage.Format.Format_RGBA8888).copy()
        self.sample.setPixmap(QPixmap.fromImage(image))

    def _select(self, key: str):
        self._selected_key = key
        item = next((entry for entry in self._items() if entry[0] == key), None)
        if item is None:
            return
        _, name, description, data = item
        for card_key, (_, card) in self._cards.items():
            card.setChecked(card_key == key)
        self.detail_title.setText(name)
        self.description.setText(description)
        self._selected_preset = data if isinstance(data, LibraryPreset) else None
        self.action.setEnabled(True)
        if key.startswith("starter:"):
            starter = data
            self.action.setText("Create Material from Starter")
            self.palette_label.setText("All 18 editable material starters are available here.")
            self.description.setText(f"{description}\nChannels: {', '.join(starter.channels)}")
        elif key.startswith("image:"):
            self.action.setText("Choose Image File…")
            self.palette_label.setText("Image samples appear after you choose a file.")
            self.sample.clear()
        else:
            preset = data
            self.action.setText("Add as Layer")
            self.palette_label.setText(
                f"Example palette: {preset.palette_name} · Tileability: {preset.tileability}"
            )
            spec_names = [spec.name for spec in REGISTRY.get(preset.operation_id).parameter_specs]
            self.description.setText(f"{description}\nEditable settings: {', '.join(spec_names)}")
            cached = self._cache.get(key)
            if cached:
                self._set_sample(cached)
            else:
                self.sample.setText("Rendering sample…")
                self._render_thumb(key)

    def _activate_selected(self):
        key = self._selected_key
        if key is None:
            return
        if key.startswith("starter:"):
            self.starterRequested.emit(key.partition(":")[2])
        elif key.startswith("image:"):
            self.imageRequested.emit()
        elif self._selected_preset is not None:
            self.layerRequested.emit(copy.deepcopy(self._selected_preset))
            self.modeChanged.emit("Edit Layer")
