from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QCheckBox,
    QColorDialog,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from archetexture.preview.bindings import CHANNEL_LABELS, CHANNELS, compatible_output_ids
from archetexture.preview.gl_viewport import BACKGROUNDS, INSPECTION_MODES, LIGHTING_PRESETS


class PreviewControls(QWidget):
    settingChanged = Signal(str)
    saveRequested = Signal(str)
    copyRequested = Signal()
    resetRequested = Signal()
    backgroundColorChanged = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.mesh = QComboBox(self)
        self.mesh.addItems(("UV Sphere", "Cube", "Plane", "Cylinder", "Torus", "Rounded Cube"))
        self.quality = QComboBox(self)
        self.quality.addItems(("Low", "Medium", "High"))
        self.quality.setCurrentText("High")
        self.mode = QComboBox(self)
        self.mode.addItems(INSPECTION_MODES)
        self.resolution = QComboBox(self)
        for label, value in (
            ("128", 128),
            ("256", 256),
            ("512", 512),
            ("1024", 1024),
            ("Project Resolution", 0),
        ):
            self.resolution.addItem(label, value)
        self.resolution.setCurrentIndex(2)
        self.projection = QComboBox(self)
        self.projection.addItems(("Perspective", "Orthographic"))
        self.fov = QSpinBox(self)
        self.fov.setRange(15, 90)
        self.fov.setValue(45)
        self.view = QComboBox(self)
        self.view.addItems(("Orbit", "Front", "Back", "Left", "Right", "Top", "Bottom"))
        self.lighting = QComboBox(self)
        self.lighting.addItems(LIGHTING_PRESETS)
        self.rig_rotation = self._spin(-180, 180, 1, 0)
        self.key_intensity = self._spin(0, 4, 0.1, 2.5)
        self.fill_intensity = self._spin(0, 4, 0.1, 0.6)
        self.rim_intensity = self._spin(0, 4, 0.1, 1.0)
        self.ambient_intensity = self._spin(0, 4, 0.1, 1.0)
        self.background = QComboBox(self)
        self.background.addItems(BACKGROUNDS)
        self.custom_background = QColor("#35363a")
        self.background_color_button = QPushButton("Choose…")
        self.background_color_button.clicked.connect(self._choose_background_color)
        self.exposure = self._spin(-4, 4, 0.1, 1)
        self.tile_u = QComboBox(self)
        self.tile_v = QComboBox(self)
        for combo in (self.tile_u, self.tile_v):
            for value in (0.25, 0.5, 1, 2, 4, 8, 16):
                combo.addItem(f"{value:g}×", value)
            combo.setCurrentIndex(2)
        self.rotation = QComboBox(self)
        self.rotation.addItems(("0°", "90°", "180°", "270°"))
        self.normal_convention = QComboBox(self)
        self.normal_convention.addItems(("OpenGL", "DirectX"))
        self.normal_strength = self._spin(0, 2, 0.05, 1)
        self.alpha = QComboBox(self)
        self.alpha.addItems(("Opaque", "Alpha Blend", "Alpha Clip"))
        self.clip = self._spin(0, 1, 0.01, 0.5)
        self.wire = QCheckBox("Show wireframe overlay")
        self.cull = QCheckBox("Back-face culling")
        self.auto_rotate = QCheckBox("Auto-rotate")
        self.auto_speed = self._spin(-180, 180, 1, 20)
        controls = (
            ("Geometry", self.mesh),
            ("Mesh Quality", self.quality),
            ("Map Resolution", self.resolution),
            ("Projection", self.projection),
            ("Field of View", self.fov),
            ("Camera View", self.view),
            ("Lighting Rig", self.lighting),
            ("Rig Rotation", self.rig_rotation),
            ("Key Intensity", self.key_intensity),
            ("Fill Intensity", self.fill_intensity),
            ("Rim Intensity", self.rim_intensity),
            ("Ambient Intensity", self.ambient_intensity),
            ("Background", self.background),
            ("Custom Background Color", self.background_color_button),
            ("Exposure (EV)", self.exposure),
            ("U Tiling", self.tile_u),
            ("V Tiling", self.tile_v),
            ("UV Rotation", self.rotation),
            ("Normal Convention", self.normal_convention),
            ("Normal Strength", self.normal_strength),
            ("Alpha Display", self.alpha),
            ("Clip Threshold", self.clip),
            ("Auto-rotate Speed", self.auto_speed),
        )
        form.addRow("Inspection Mode", self.mode)
        for title, widget in controls:
            form.addRow(title, widget)
        for widget in (self.wire, self.cull, self.auto_rotate):
            form.addRow(widget)
        layout.addLayout(form)
        layout.addWidget(QLabel("Output overrides (preview only)"))
        self.bindings = {}
        for channel in CHANNELS:
            combo = QComboBox(self)
            combo.setObjectName(f"preview-binding-{channel}")
            self.bindings[channel] = combo
            layout.addWidget(QLabel(CHANNEL_LABELS[channel]))
            layout.addWidget(combo)
            combo.currentIndexChanged.connect(
                lambda _index, c=channel: self.settingChanged.emit(f"binding:{c}")
            )
        buttons = QHBoxLayout()
        self.save = QPushButton("Save Preview Image…")
        self.copy = QPushButton("Copy Image")
        self.reset = QPushButton("Reset Preview")
        for button in (self.save, self.copy, self.reset):
            buttons.addWidget(button)
        layout.addLayout(buttons)
        layout.addStretch(1)
        self.save.clicked.connect(self._save)
        self.copy.clicked.connect(self.copyRequested)
        self.reset.clicked.connect(self.resetRequested)
        for widget in (
            self.mesh,
            self.quality,
            self.resolution,
            self.projection,
            self.fov,
            self.view,
            self.lighting,
            self.rig_rotation,
            self.key_intensity,
            self.fill_intensity,
            self.rim_intensity,
            self.ambient_intensity,
            self.background,
            self.exposure,
            self.tile_u,
            self.tile_v,
            self.rotation,
            self.normal_convention,
            self.normal_strength,
            self.alpha,
            self.clip,
            self.wire,
            self.cull,
            self.auto_rotate,
            self.auto_speed,
        ):
            signal = (
                getattr(widget, "valueChanged", None)
                or getattr(widget, "currentIndexChanged", None)
                or getattr(widget, "toggled", None)
            )
            signal.connect(lambda *_args: self.settingChanged.emit("view"))
        self.mode.currentTextChanged.connect(lambda _value: self.settingChanged.emit("inspection"))
        self.mesh.currentTextChanged.connect(lambda value: self.settingChanged.emit("mesh"))
        self.quality.currentTextChanged.connect(lambda value: self.settingChanged.emit("mesh"))

    @staticmethod
    def _spin(minimum, maximum, step, value):
        spin = QDoubleSpinBox()
        spin.setRange(minimum, maximum)
        spin.setSingleStep(step)
        spin.setValue(value)
        return spin

    def set_recipe(self, recipe, binding):
        resolved = binding.resolve(recipe)
        for channel, combo in self.bindings.items():
            combo.blockSignals(True)
            combo.clear()
            combo.addItem("Automatic", None)
            for output in recipe.outputs:
                if output.output_id in compatible_output_ids(recipe, channel):
                    combo.addItem(output.name, output.output_id)
            current = binding.overrides.get(channel)
            if current is None:
                combo.setCurrentIndex(0)
            else:
                index = combo.findData(current)
                combo.setCurrentIndex(index if index >= 0 else 0)
            combo.setToolTip(f"Automatic: {resolved[channel] or 'fallback'}")
            combo.blockSignals(False)

    def binding_overrides(self):
        return {
            channel: combo.currentData()
            for channel, combo in self.bindings.items()
            if combo.currentIndex() > 0
        }

    def _choose_background_color(self):
        color = QColorDialog.getColor(self.custom_background, self, "Preview Background")
        if color.isValid():
            self.custom_background = color
            self.backgroundColorChanged.emit(color.name(QColor.NameFormat.HexArgb))

    def _save(self):
        path, _ = QFileDialog.getSaveFileName(self, "Save Preview Image", "", "PNG image (*.png)")
        if path:
            self.saveRequested.emit(path)

    def view_state(self):
        return {
            "mesh": self.mesh.currentText(),
            "quality": self.quality.currentText(),
            "inspection": self.mode.currentText(),
            "resolution": self.resolution.currentData(),
            "projection": self.projection.currentText(),
            "view": self.view.currentText(),
            "fov": self.fov.value(),
            "lighting": self.lighting.currentText(),
            "rig_rotation": self.rig_rotation.value(),
            "key_intensity": self.key_intensity.value(),
            "fill_intensity": self.fill_intensity.value(),
            "rim_intensity": self.rim_intensity.value(),
            "ambient_intensity": self.ambient_intensity.value(),
            "background": self.background.currentText(),
            "custom_background": self.custom_background.name(QColor.NameFormat.HexArgb),
            "exposure": self.exposure.value(),
            "tile_u": self.tile_u.currentData(),
            "tile_v": self.tile_v.currentData(),
            "rotation": (0, 90, 180, 270)[self.rotation.currentIndex()],
            "directx": self.normal_convention.currentText() == "DirectX",
            "normal_strength": self.normal_strength.value(),
            "alpha": self.alpha.currentText(),
            "clip": self.clip.value(),
            "wire": self.wire.isChecked(),
            "cull": self.cull.isChecked(),
            "auto_rotate": self.auto_rotate.isChecked(),
            "auto_speed": self.auto_speed.value(),
        }
