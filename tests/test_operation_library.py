from __future__ import annotations

import copy

import numpy as np
from PySide6.QtCore import Qt, QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog

from archetexture.core.material_starters import MATERIAL_STARTERS, create_material_starter
from archetexture.core.pipeline_types import pipeline_output_type
from archetexture.core.validation import ensure_valid_recipe
from archetexture.render.engine import RenderEngine
from archetexture.ui.layers_panel import LayersPanel
from archetexture.ui.main_window import MainWindow
from archetexture.ui.numeric_control import NumericControl
from archetexture.ui.operation_library import (
    OPERATION_PRESETS,
    operation_recipe,
)


def test_library_covers_registered_generators_and_all_material_starters(qtbot):
    from archetexture.core.registry import REGISTRY

    expected = {
        "generator.linear_gradient",
        "generator.radial_gradient",
        "generator.constant",
        "generator.checker_grid",
        "generator.bands",
        "generator.brick",
        "generator.hex_cells",
        "generator.truchet",
        "generator.polka_dots",
        "generator.concentric_rings",
        "generator.radial_spokes",
        "generator.crosshatch",
        "generator.weave",
        "generator.wood_rings",
        "generator.marble_veins",
        "generator.cellular",
        "generator.fractal_noise",
        "generator.ridged_noise",
        "generator.billow_noise",
        "generator.perlin_noise",
        "generator.domain_warp",
    }
    assert expected <= {preset.operation_id for preset in OPERATION_PRESETS}
    for preset in OPERATION_PRESETS:
        ensure_valid_recipe(operation_recipe(preset, width=48, height=48))
    assert len(MATERIAL_STARTERS) == 18
    from archetexture.ui.operation_library import OperationLibraryPanel

    library = OperationLibraryPanel()
    qtbot.addWidget(library)
    library.mode.setCurrentText("Material Starters")
    assert {item[1] for item in library._items()} == {starter.name for starter in MATERIAL_STARTERS}
    assert all(REGISTRY.get(preset.operation_id) for preset in OPERATION_PRESETS)


def test_visual_samples_are_real_and_distinct_for_representative_patterns():
    engine = RenderEngine()
    names = {preset.name: preset for preset in OPERATION_PRESETS}
    samples = {}
    for name in (
        "Brick · Standard",
        "Wood · Fine Grain",
        "Marble · Fine Veins",
        "Weave",
        "Checker Grid",
    ):
        sample = engine.render(operation_recipe(names[name], width=64, height=64)).rgba_field
        assert np.isfinite(sample).all()
        assert float(sample.std()) > 0.01
        samples[name] = sample
    for name, sample in samples.items():
        for other_name, other in samples.items():
            if name != other_name:
                assert not np.array_equal(sample, other)


def test_browsing_is_non_destructive_and_pattern_addition_uses_typed_output(qtbot):
    window = MainWindow(create_material_starter("Rough Stone"))
    qtbot.addWidget(window)
    window._confirm_discard = lambda: True
    before = copy.deepcopy(window.document.recipe)
    history_before = copy.deepcopy(window.document.history.entries)
    dirty_before = window.document.dirty

    window.operation_library.mode.setCurrentText("Patterns")
    window.operation_library.search.setText("Weave")
    key = next(iter(window.operation_library._cards))
    window.operation_library._select(key)
    assert window.document.recipe == before
    assert window.document.history.entries == history_before
    assert window.document.dirty == dirty_before

    weave = next(preset for preset in OPERATION_PRESETS if preset.name == "Weave")
    for semantic, expected_type in (
        ("base_color", "scalar"),
        ("roughness", "scalar"),
        ("metallic", "scalar"),
        ("normal", "rgba"),
    ):
        window._select_simple_channel(semantic)
        layer_count = len(window._layers_for(window.document.recipe))
        history_index = window.document.history.index
        window._add_library_operation(weave)
        layer = window._layer()
        assert layer.source.operation_id == weave.operation_id
        assert len(window._layers_for(window.document.recipe)) == layer_count + 1
        assert window.document.history.index == history_index + 1
        assert pipeline_output_type(layer.source, layer.transforms) == expected_type
        ensure_valid_recipe(window.document.recipe)
    window.close()


def test_numeric_control_supports_mouse_steps_and_typed_values(qtbot):
    control = NumericControl(
        0.5,
        minimum=0.0,
        maximum=1.0,
        step=0.1,
        decimals=2,
        unit="Scale",
    )
    qtbot.addWidget(control)
    changes = []
    control.valueChanged.connect(changes.append)
    qtbot.mouseClick(control.increment, Qt.MouseButton.LeftButton)
    assert control.value() == 0.6
    control.editor.setFocus()
    control.editor.selectAll()
    QTest.keyClicks(control.editor, "0.37")
    QTest.keyClick(control.editor, Qt.Key.Key_Return)
    assert control.value() == 0.37
    QTest.keyClick(control.editor, Qt.Key.Key_Up)
    assert control.value() == 0.47
    assert changes == [0.6, 0.37, 0.47]


def test_layer_stack_thumbnail_comes_from_the_render_engine(qtbot):
    recipe = create_material_starter("Brick")
    output = next(item for item in recipe.outputs if item.semantic == "base_color")
    panel = LayersPanel()
    qtbot.addWidget(panel)
    panel.set_recipe(recipe, output.layers[0].layer_id, output.output_id)
    panel.show()
    qtbot.waitUntil(lambda: not panel.layer_list.item(0).icon().isNull(), timeout=15000)
    assert panel.layer_list.item(0).toolTip() == "Rendered layer preview"


def test_gradient_library_action_uses_the_existing_gradient_editor(qtbot):
    window = MainWindow(create_material_starter("Rough Stone"))
    qtbot.addWidget(window)
    window._confirm_discard = lambda: True
    window.show()
    window.operation_library.mode.setCurrentText("Gradients and Colors")
    window.operation_library.search.setText("Linear Gradient")
    key = next(iter(window.operation_library._cards))
    qtbot.mouseClick(window.operation_library._cards[key][1], Qt.MouseButton.LeftButton)
    assert window.operation_library.action.isEnabled()
    QTimer.singleShot(
        250,
        lambda: (
            QApplication.activeModalWidget().accept()
            if isinstance(QApplication.activeModalWidget(), QDialog)
            else None
        ),
    )
    qtbot.mouseClick(window.operation_library.action, Qt.MouseButton.LeftButton)
    assert any(
        layer.source.operation_id == "generator.linear_gradient"
        for output in window.document.recipe.outputs
        for layer in output.layers
    )
    window.close()
