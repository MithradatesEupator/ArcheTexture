from __future__ import annotations

import numpy as np
import pytest
from PIL import Image
from PySide6.QtCore import QSettings
from PySide6.QtGui import QPalette

from archetexture.core.assets import RenderContext
from archetexture.core.cancellation import CancellationToken, RenderCancelled
from archetexture.core.material_starters import (
    MATERIAL_STARTERS,
    create_material_starter,
)
from archetexture.core.operations import OperationType, Seamlessness
from archetexture.core.parameters import ControlFieldBinding, ParameterType
from archetexture.core.recipe import (
    LayerRecipe,
    MaterialOutputRecipe,
    OperationInstance,
    ProjectRecipe,
)
from archetexture.core.registry import REGISTRY
from archetexture.core.seamlessness import recipe_seamlessness
from archetexture.core.serialization import load_project, save_project
from archetexture.core.validation import ensure_valid_recipe
from archetexture.export.texture_set import (
    OutputExportSpec,
    TextureSetExporter,
    TextureSetExportPlan,
)
from archetexture.preview.bindings import PreviewMaterialBinding
from archetexture.preview.snapshot import PreviewSnapshotBuilder
from archetexture.render.engine import RenderEngine
from archetexture.ui.material_starter_dialog import MaterialStarterDialog
from archetexture.ui.pipeline_panel import PipelinePanel

GENERATOR_IDS = tuple(
    identifier
    for identifier, definition in REGISTRY.definitions.items()
    if identifier.startswith("generator.")
    and identifier
    in {
        "generator.ridged_noise",
        "generator.billow_noise",
        "generator.perlin_noise",
        "generator.domain_warp",
        "generator.brick",
        "generator.hex_cells",
        "generator.truchet",
        "generator.wood_rings",
        "generator.marble_veins",
        "generator.polka_dots",
        "generator.concentric_rings",
        "generator.radial_spokes",
        "generator.weave",
        "generator.crosshatch",
    }
)
TRANSFORM_IDS = tuple(
    identifier
    for identifier in REGISTRY.definitions
    if identifier.startswith("transform.")
    and identifier
    in {
        "transform.clamp_range",
        "transform.gamma",
        "transform.sine_remap",
        "transform.fold",
        "transform.terrace",
        "transform.smoothstep",
        "transform.directional_blur",
        "transform.emboss",
        "transform.high_pass",
        "transform.dilate",
        "transform.erode",
        "transform.warp",
        "transform.swirl",
        "transform.polar",
        "transform.kaleidoscope",
        "transform.tile_scale_rotate",
        "transform.pixelate",
        "transform.edge_detect",
    }
)


def _parameters(operation_id: str) -> dict:
    return {spec.identifier: spec.default for spec in REGISTRY.get(operation_id).parameter_specs}


def _source_recipe(operation_id: str, *, width=64, height=48, seed=13, parameters=None):
    definition = REGISTRY.get(operation_id)
    source = OperationInstance(
        "source",
        operation_id,
        definition.version,
        parameters=_parameters(operation_id) if parameters is None else parameters,
    )
    if definition.operation_type == OperationType.GENERATOR:
        return ProjectRecipe(
            width=width,
            height=height,
            seed=seed,
            outputs=[
                MaterialOutputRecipe(
                    "output",
                    "Output",
                    "custom_scalar",
                    "scalar",
                    [LayerRecipe("layer", "Layer", source)],
                )
            ],
        )
    return None


@pytest.mark.parametrize("operation_id", GENERATOR_IDS)
def test_expanded_generators_are_deterministic_float_fields_with_visible_structure(operation_id):
    engine = RenderEngine()
    recipe = _source_recipe(operation_id)
    first = engine.render(recipe).scalar_field
    second = engine.render_uncached(recipe).scalar_field
    np.testing.assert_array_equal(first, second)
    assert first.dtype == np.float32
    assert np.isfinite(first).all()
    assert 0.0 <= float(first.min()) <= float(first.max()) <= 1.0
    assert float(first.std()) > 0.015, operation_id
    assert REGISTRY.get(operation_id).seamlessness != Seamlessness.INHERENT


@pytest.mark.parametrize(
    "operation_id",
    (
        "generator.ridged_noise",
        "generator.billow_noise",
        "generator.perlin_noise",
        "generator.domain_warp",
        "generator.brick",
        "generator.hex_cells",
        "generator.truchet",
        "generator.wood_rings",
        "generator.marble_veins",
        "generator.polka_dots",
        "generator.weave",
    ),
)
def test_seeded_sources_change_with_project_seed(operation_id):
    engine = RenderEngine()
    parameters = _parameters(operation_id)
    if operation_id == "generator.polka_dots":
        parameters["jitter"] = 0.15
    recipe = _source_recipe(operation_id, seed=3, parameters=parameters)
    first = engine.render(recipe).scalar_field
    recipe.seed = 19
    second = RenderEngine().render(recipe).scalar_field
    assert not np.array_equal(first, second), operation_id


@pytest.mark.parametrize("operation_id", (*GENERATOR_IDS, *TRANSFORM_IDS))
def test_expanded_operation_parameter_limits_produce_valid_fields(operation_id):
    definition = REGISTRY.get(operation_id)
    width, height = 29, 23
    source = np.linspace(0.0, 1.0, width * height, dtype=np.float32).reshape(height, width)

    def run(parameters):
        args = (
            (None, parameters, width, height, 71)
            if definition.operation_type == OperationType.GENERATOR
            else (source, parameters, width, height, 71)
        )
        if definition.requires_render_context:
            result = definition.implementation(*args, RenderContext())
        else:
            result = definition.implementation(*args)
        result = np.asarray(result, np.float32)
        assert result.shape == (height, width), operation_id
        assert np.isfinite(result).all(), operation_id
        assert float(result.min()) >= 0.0 and float(result.max()) <= 1.0

    base = _parameters(operation_id)
    run(base)
    for spec in definition.parameter_specs:
        for endpoint in (spec.min_value, spec.max_value):
            if endpoint is None:
                continue
            value = (
                int(endpoint)
                if spec.type in (ParameterType.INTEGER, ParameterType.SEED)
                else endpoint
            )
            run({**base, spec.identifier: value})
        if spec.type == ParameterType.ENUM and spec.options:
            run({**base, spec.identifier: spec.options[-1]})
        if spec.type == ParameterType.BOOLEAN:
            run({**base, spec.identifier: not bool(spec.default)})


@pytest.mark.parametrize("operation_id", TRANSFORM_IDS)
def test_new_transforms_participate_in_scalar_type_flow_and_wrap_metadata(operation_id):
    definition = REGISTRY.get(operation_id)
    assert definition.operation_type == OperationType.TRANSFORM
    assert definition.input_types == ("scalar",)
    assert definition.output_type == "scalar"
    assert definition.seamlessness in {
        Seamlessness.PRESERVES,
        Seamlessness.UNKNOWN,
        Seamlessness.BREAKS,
    }


def test_wrap_preserving_transforms_commute_with_periodic_translation():
    width, height = 37, 29
    x = (np.arange(width, dtype=np.float32) + 0.5) / width
    y = (np.arange(height, dtype=np.float32) + 0.5) / height
    xx, yy = np.meshgrid(x, y)
    source = (0.5 + 0.25 * np.sin(2 * np.pi * xx) + 0.2 * np.cos(4 * np.pi * yy)).astype(np.float32)
    for operation_id in TRANSFORM_IDS:
        definition = REGISTRY.get(operation_id)
        if definition.seamlessness != Seamlessness.PRESERVES:
            continue
        parameters = _parameters(operation_id)
        args = (source, parameters, width, height, 9)
        result = (
            definition.implementation(*args, RenderContext())
            if definition.requires_render_context
            else definition.implementation(*args)
        )
        shifted = np.roll(source, (4, -7), axis=(0, 1))
        shifted_args = (shifted, parameters, width, height, 9)
        shifted_result = (
            definition.implementation(*shifted_args, RenderContext())
            if definition.requires_render_context
            else definition.implementation(*shifted_args)
        )
        np.testing.assert_allclose(
            shifted_result,
            np.roll(result, (4, -7), axis=(0, 1)),
            atol=2e-6,
            err_msg=operation_id,
        )


def test_cellular_exposes_voronoi_distance_variants():
    definition = REGISTRY.get("generator.cellular")
    spec = next(item for item in definition.parameter_specs if item.identifier == "distance_mode")
    assert spec.options == ("nearest", "second", "edge", "gap")
    outputs = []
    for mode in spec.options:
        recipe = _source_recipe(
            "generator.cellular",
            parameters={**_parameters("generator.cellular"), "distance_mode": mode},
        )
        outputs.append(RenderEngine().render(recipe).scalar_field)
    assert all(np.mean(np.abs(outputs[0] - item)) > 0.01 for item in outputs[1:])


def test_expensive_generators_and_filters_observe_cancellation():
    for operation_id in ("generator.ridged_noise", "generator.marble_veins", "transform.dilate"):
        token = CancellationToken()
        token.cancel()
        if operation_id.startswith("generator."):
            recipe = _source_recipe(operation_id)
        else:
            source = OperationInstance(
                "source",
                "generator.fractal_noise",
                1,
                parameters=_parameters("generator.fractal_noise"),
            )
            transform = OperationInstance(
                operation_id, operation_id, 1, parameters=_parameters(operation_id)
            )
            recipe = ProjectRecipe(
                width=48, height=40, layers=[LayerRecipe("layer", "Layer", source, [transform])]
            )
        with pytest.raises(RenderCancelled):
            RenderEngine().render(recipe, render_context=RenderContext(cancel_token=token))


@pytest.mark.parametrize("starter", MATERIAL_STARTERS, ids=lambda item: item.name)
def test_material_starters_validate_and_render_coherent_live_channels(starter):
    recipe = create_material_starter(starter.name, width=48, height=40)
    ensure_valid_recipe(recipe)
    assert {item.semantic for item in recipe.outputs} == {
        "base_color",
        "roughness",
        "metallic",
        "normal",
        "height",
        "ambient_occlusion",
    }
    assert set(recipe.control_fields) == {"Scale", "Wear"}
    height = next(item for item in recipe.outputs if item.semantic == "height")
    normal = next(item for item in recipe.outputs if item.semantic == "normal")
    assert normal.layers[0].source.operation_id == "generator.output_scalar"
    assert normal.layers[0].source.parameters["target"] == height.output_id
    assert normal.layers[0].transforms[0].operation_id == "transform.height_to_normal"
    assert "Scale" in {
        value.source_id
        for instance in [height.layers[0].source, *height.layers[0].transforms]
        for value in instance.parameters.values()
        if isinstance(value, ControlFieldBinding)
    }
    assert any(
        isinstance(value, ControlFieldBinding) and value.source_id == "Wear"
        for instance in [*height.layers[0].transforms]
        for value in instance.parameters.values()
    )
    for semantic in ("base_color", "roughness", "metallic", "ambient_occlusion"):
        output = next(item for item in recipe.outputs if item.semantic == semantic)
        assert output.layers[0].source.parameters["target"] == height.output_id

    engine = RenderEngine()
    rendered = engine.render_material(recipe)
    by_semantic = {recipe.output(key).semantic: value for key, value in rendered.outputs.items()}
    height_field = by_semantic["height"].scalar_field
    base_color = by_semantic["base_color"].rgba_field
    assert height_field.shape == (40, 48)
    assert float(height_field.std()) > 0.01
    assert float(base_color[..., :3].std()) > 0.02
    assert by_semantic["normal"].rgba_field.shape == (40, 48, 4)
    assert all(np.isfinite(value.rgba_field).all() for value in rendered.outputs.values())
    assert recipe_seamlessness(recipe, output_id=height.output_id) in {"Yes", "No", "Unknown"}
    # Warm and uncached rendering must agree, including derived channels.
    warm = engine.render_material(recipe)
    reference = RenderEngine().render_material(recipe)
    for output_id in rendered.outputs:
        np.testing.assert_array_equal(
            warm.outputs[output_id].rgba_field, reference.outputs[output_id].rgba_field
        )


def test_starter_project_save_reopen_2d_3d_snapshot_and_texture_set_export(tmp_path):
    recipe = create_material_starter("Rough Stone", width=64, height=48)
    path = tmp_path / "rough-stone.archetexture"
    save_project(recipe, path)
    reopened = load_project(path)
    ensure_valid_recipe(reopened)
    engine = RenderEngine()
    output_ids = [item.output_id for item in reopened.outputs]
    results = engine.render_outputs(reopened, output_ids)
    base_id = next(item.output_id for item in reopened.outputs if item.semantic == "base_color")
    assert results[base_id].rgba_field.shape == (48, 64, 4)  # 2D display field

    snapshot = PreviewSnapshotBuilder(engine).build(
        reopened, PreviewMaterialBinding(), 1, 32, 24, inspection="Material"
    )
    assert snapshot.maps["base_color"].shape == (24, 32, 4)
    assert snapshot.maps["normal"].shape == (24, 32, 4)
    assert np.isfinite(snapshot.maps["base_color"]).all()

    specs = tuple(OutputExportSpec(item.output_id, item.export_suffix) for item in reopened.outputs)
    files = TextureSetExporter(engine).export(
        reopened,
        TextureSetExportPlan(str(tmp_path / "exports"), "stone", 32, 24, outputs=specs),
    )
    assert len(files) == 6
    for path in files:
        with Image.open(path) as image:
            assert image.size == (32, 24)
            assert image.mode in {"L", "RGB", "RGBA"}


def test_material_starter_renders_in_the_2d_workspace(qtbot):
    from archetexture.ui.main_window import MainWindow

    recipe = create_material_starter("Brick", width=48, height=40)
    window = MainWindow(recipe)
    qtbot.addWidget(window)
    qtbot.waitUntil(
        lambda: (
            window.viewport.rendered_field is not None
            and window._latest_displayed_request_id == window.render_coordinator.latest_request_id
        ),
        timeout=15000,
    )
    assert window.workspace_stack.currentWidget() is window.viewport
    assert window.viewport.rendered_field.shape == (40, 48, 4)
    assert float(window.viewport.rendered_field[..., :3].std()) > 0.02
    window.close()


def test_searchable_pipeline_and_material_picker_show_categories_and_channel_descriptions(qtbot):
    panel = PipelinePanel()
    qtbot.addWidget(panel)
    assert panel.source_selector.count() > 20
    panel.source_search.setText("honeycomb")
    assert panel.source_selector.count() == 1
    assert panel.source_selector.currentData() == "generator.hex_cells"
    panel.source_search.clear()
    panel.set_recipe(_source_recipe("generator.fractal_noise"))
    panel.transform_search.setText("morphology")
    assert panel.transform_selector.count() == 2
    assert {panel.transform_selector.itemData(index) for index in range(2)} == {
        "transform.dilate",
        "transform.erode",
    }

    dialog = MaterialStarterDialog()
    qtbot.addWidget(dialog)
    dialog.search.setText("ceramic")
    assert dialog.material_list.count() == 1
    assert dialog.selected_starter.name == "Ceramic / Tile"
    assert "Ambient Occlusion" in dialog.details.text()


def test_new_material_command_is_available_and_dark_theme_stays_active(qtbot, tmp_path):
    from archetexture.ui.main_window import MainWindow

    QSettings.setPath(QSettings.Format.IniFormat, QSettings.Scope.UserScope, str(tmp_path))
    QSettings(
        QSettings.Format.IniFormat,
        QSettings.Scope.UserScope,
        "ArcheTexture",
        "ArcheTexture",
    ).clear()
    window = MainWindow()
    qtbot.addWidget(window)
    assert window.new_from_material_action.text() == "New from Material…"
    assert window._application.palette().color(QPalette.ColorRole.Window).lightness() < 150
    assert window._application.palette().color(QPalette.ColorRole.Window).name() == "#1b1d21"
    assert window.document.dirty is False
    window.close()
