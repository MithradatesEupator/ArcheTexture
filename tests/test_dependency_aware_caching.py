from __future__ import annotations

import copy

import numpy as np
import pytest
from PIL import Image

from archetexture.core.assets import AssetReference, RenderContext
from archetexture.core.dependencies import (
    control_dependencies,
    control_dependency_definitions,
    control_field_dependencies,
    instance_dependencies,
    layer_content_dependencies,
    layer_mask_dependencies,
    transitive_control_closure,
)
from archetexture.core.parameters import ControlFieldBinding, ControlFieldMapping
from archetexture.core.recipe import (
    ControlFieldRecipe,
    LayerRecipe,
    OperationInstance,
    ProjectRecipe,
)
from archetexture.core.registry import REGISTRY
from archetexture.core.validation import validate_recipe
from archetexture.export.image_export import ImageExporter
from archetexture.render.engine import RenderEngine
from archetexture.render.session import RenderSession


def operation(operation_id: str, instance_id: str, **overrides) -> OperationInstance:
    definition = REGISTRY.get(operation_id)
    parameters = {spec.identifier: spec.default for spec in definition.parameter_specs}
    parameters.update(overrides)
    return OperationInstance(instance_id, operation_id, definition.version, parameters=parameters)


def scalar_control(identifier: str, scale=2.0, *, blur=False, mapping=None) -> ControlFieldRecipe:
    transforms = [operation("transform.blur", f"{identifier}-blur", sigma=0.8)] if blur else []
    return ControlFieldRecipe(
        operation("generator.fractal_noise", f"{identifier}-source", seed=70, scale=scale),
        transforms,
        mapping,
    )


def six_layer_recipe(*, with_mask=True, controls=None) -> ProjectRecipe:
    layers = []
    for index in range(6):
        source = operation(
            "generator.fractal_noise", f"source-{index}", seed=15 + index, scale=3.0 + index
        )
        transforms = [operation("transform.blur", f"blur-{index}", sigma=0.8)]
        layer = LayerRecipe(f"layer-{index}", f"Layer {index}", source, transforms)
        if with_mask:
            layer.mask = ControlFieldBinding("mask")
        layers.append(layer)
    return ProjectRecipe(
        width=24,
        height=18,
        layers=layers,
        control_fields=controls or {"mask": scalar_control("mask", blur=True)},
    )


def _delta(session: RenderSession, before: dict) -> dict:
    after = session.stats
    return {
        "ops": after["operation_executions"] - before["operation_executions"],
        "layer_hits": after["layers"]["hits"] - before["layers"]["hits"],
        "layer_misses": after["layers"]["misses"] - before["layers"]["misses"],
        "control_hits": after["controls"]["hits"] - before["controls"]["hits"],
        "control_misses": after["controls"]["misses"] - before["controls"]["misses"],
    }


def test_dependency_extraction_handles_nested_values_parameters_and_influence():
    first = ControlFieldBinding("first")
    second = ControlFieldBinding("second")
    cyclic_list = [first, {"nested": (second,)}]
    cyclic_list.append(cyclic_list)
    assert control_dependencies(cyclic_list) == {"first", "second"}
    instance = operation("transform.height_to_normal", "modulated")
    instance.parameters["strength"] = first
    instance.influence = second
    assert instance_dependencies(instance) == {"first", "second"}


def test_direct_transitive_and_unrelated_control_closure_is_deterministic_and_cycle_safe():
    controls = {
        "a": scalar_control(
            "a", ControlFieldBinding("b", ControlFieldMapping(output_min=0.5, output_max=3.0))
        ),
        "b": scalar_control(
            "b", ControlFieldBinding("c", ControlFieldMapping(output_min=0.5, output_max=3.0))
        ),
        "c": scalar_control("c", 2.5),
        "unrelated": scalar_control("unrelated", 1.5),
        "extra": scalar_control("extra", 2.3),
    }
    controls["a"].transforms.append(
        OperationInstance(
            "a-blur",
            "transform.blur",
            1,
            parameters={
                "sigma": ControlFieldBinding(
                    "extra", ControlFieldMapping(output_min=0.5, output_max=1.5)
                )
            },
            influence=ControlFieldBinding("b"),
        )
    )
    recipe = six_layer_recipe(controls=controls)
    assert control_field_dependencies(recipe, "a") == {"b", "extra"}
    assert transitive_control_closure(recipe, {"a"}) == ("a", "b", "c", "extra")
    assert set(control_dependency_definitions(recipe, {"a"})) == {"a", "b", "c", "extra"}
    assert "unrelated" not in control_dependency_definitions(recipe, {"a"})

    cyclic = {
        "a": scalar_control("cycle-a", ControlFieldBinding("b")),
        "b": scalar_control("cycle-b", ControlFieldBinding("a")),
    }
    cyclic_recipe = six_layer_recipe(controls=cyclic)
    assert transitive_control_closure(cyclic_recipe, {"a"}) == ("a", "b")
    assert any(
        "cyclic control-field reference" in issue.message
        for issue in validate_recipe(cyclic_recipe)
    )


def test_layer_content_and_mask_dependencies_are_separate():
    layer = LayerRecipe(
        "layer",
        "Layer",
        operation("generator.fractal_noise", "source", scale=ControlFieldBinding("source")),
        [
            OperationInstance(
                "normal",
                "transform.height_to_normal",
                1,
                parameters={"strength": ControlFieldBinding("parameter")},
                influence=ControlFieldBinding("influence"),
            )
        ],
        mask=ControlFieldBinding("mask"),
    )
    assert layer_content_dependencies(layer) == {"source", "parameter", "influence"}
    assert layer_mask_dependencies(layer) == {"mask"}


def test_mask_only_field_and_mask_mapping_edits_preserve_all_layer_content(tmp_path):
    recipe = six_layer_recipe()
    session = RenderSession()
    engine = RenderEngine(session=session)
    engine.render(recipe)

    edited = copy.deepcopy(recipe)
    edited.control_fields["mask"].source.parameters["scale"] += 0.4
    before = session.stats
    engine.render(edited)
    assert _delta(session, before) == {
        "ops": 2,
        "layer_hits": 6,
        "layer_misses": 0,
        "control_hits": 0,
        "control_misses": 1,
    }
    np.testing.assert_array_equal(
        engine.render(edited).rgba_field, RenderEngine().render_uncached(edited).rgba_field
    )
    mapped = copy.deepcopy(edited)
    mapped.layers[0].mask = ControlFieldBinding("mask", ControlFieldMapping(invert=True))
    before = session.stats
    mapped_result = engine.render(mapped)
    assert _delta(session, before) == {
        "ops": 0,
        "layer_hits": 6,
        "layer_misses": 0,
        "control_hits": 1,
        "control_misses": 0,
    }
    np.testing.assert_array_equal(
        mapped_result.rgba_field, RenderEngine().render_uncached(mapped).rgba_field
    )
    opacity_edit = copy.deepcopy(mapped)
    opacity_edit.layers[0].opacity = 0.6
    result = engine.render(opacity_edit)
    destination = tmp_path / "dependency-export.png"
    ImageExporter().export_png(opacity_edit, destination)
    with Image.open(destination) as saved:
        np.testing.assert_array_equal(
            np.asarray(saved), np.rint(result.rgba_field * 255.0).astype(np.uint8)
        )


def test_unrelated_control_field_edit_preserves_layers_and_mask_cache():
    recipe = six_layer_recipe(
        controls={"mask": scalar_control("mask", blur=True), "unused": scalar_control("unused")}
    )
    session = RenderSession()
    engine = RenderEngine(session=session)
    engine.render(recipe)
    edited = copy.deepcopy(recipe)
    edited.control_fields["unused"].source.parameters["scale"] += 0.7
    before = session.stats
    engine.render(edited)
    assert _delta(session, before) == {
        "ops": 0,
        "layer_hits": 6,
        "layer_misses": 0,
        "control_hits": 1,
        "control_misses": 0,
    }


@pytest.mark.parametrize("usage", ["source", "transform_parameter", "transform_influence"])
def test_modulation_edit_invalidates_only_content_that_depends_on_field(usage):
    recipe = six_layer_recipe(with_mask=False, controls={"mod": scalar_control("mod", blur=True)})
    layer = recipe.layers[0]
    if usage == "source":
        layer.source.parameters["scale"] = ControlFieldBinding(
            "mod", ControlFieldMapping(output_min=2.0, output_max=5.0)
        )
    else:
        height_normal = operation("transform.height_to_normal", "height-normal", strength=0.8)
        if usage == "transform_parameter":
            height_normal.parameters["strength"] = ControlFieldBinding(
                "mod", ControlFieldMapping(output_min=0.5, output_max=1.5)
            )
        else:
            height_normal.influence = ControlFieldBinding("mod")
        layer.transforms = [height_normal]

    session = RenderSession()
    engine = RenderEngine(session=session)
    engine.render(recipe)
    edited = copy.deepcopy(recipe)
    edited.control_fields["mod"].source.parameters["scale"] += 0.35
    before = session.stats
    changed = engine.render(edited)
    delta = _delta(session, before)
    assert delta["ops"] == 4  # two field operations and only the dependent layer pipeline
    assert delta["layer_hits"] == 5
    assert delta["layer_misses"] == 1
    assert delta["control_misses"] == 1
    np.testing.assert_array_equal(
        changed.rgba_field, RenderEngine().render_uncached(edited).rgba_field
    )


def test_control_field_transform_parameters_and_influence_are_dependency_tracked():
    levels = operation("transform.levels", "mask-levels")
    levels.parameters["input_black"] = ControlFieldBinding(
        "driver", ControlFieldMapping(output_min=0.1, output_max=0.4)
    )
    levels.influence = ControlFieldBinding("driver")
    recipe = six_layer_recipe(
        controls={"mask": scalar_control("mask"), "driver": scalar_control("driver")}
    )
    recipe.control_fields["mask"].transforms = [levels]
    assert control_field_dependencies(recipe, "mask") == {"driver"}

    session = RenderSession()
    engine = RenderEngine(session=session)
    engine.render(recipe)
    edited = copy.deepcopy(recipe)
    edited.control_fields["driver"].source.parameters["scale"] += 0.35
    before = session.stats
    changed = engine.render(edited)
    delta = _delta(session, before)
    assert delta["ops"] == 3
    assert delta["control_misses"] == 2
    assert delta["layer_hits"] == 6
    assert delta["layer_misses"] == 0
    fresh = RenderEngine().render_uncached(edited)
    np.testing.assert_array_equal(changed.rgba_field, fresh.rgba_field)
    np.testing.assert_array_equal(changed.mask_fields["layer-0"], fresh.mask_fields["layer-0"])


def test_dual_use_mask_and_content_field_invalidates_both_domains():
    recipe = six_layer_recipe()
    recipe.layers[0].source.parameters["scale"] = ControlFieldBinding(
        "mask", ControlFieldMapping(output_min=2.0, output_max=5.0)
    )
    session = RenderSession()
    engine = RenderEngine(session=session)
    original = engine.render(recipe)
    edited = copy.deepcopy(recipe)
    edited.control_fields["mask"].source.parameters["scale"] += 0.35
    before = session.stats
    changed = engine.render(edited)
    delta = _delta(session, before)
    assert delta["ops"] == 4
    assert delta["layer_hits"] == 5
    assert delta["layer_misses"] == 1
    np.testing.assert_array_equal(
        changed.rgba_field, RenderEngine().render_uncached(edited).rgba_field
    )
    assert not np.array_equal(original.rgba_field, changed.rgba_field)


def test_global_control_mapping_is_applied_after_raw_cached_control_output():
    recipe = six_layer_recipe()
    recipe.control_fields["mask"].mapping = ControlFieldMapping(output_min=0.1, output_max=0.7)
    session = RenderSession()
    engine = RenderEngine(session=session)
    original = engine.render(recipe)
    edited = copy.deepcopy(recipe)
    edited.control_fields["mask"].mapping = ControlFieldMapping(output_min=0.3, output_max=0.95)
    before = session.stats
    changed = engine.render(edited)
    delta = _delta(session, before)
    assert delta["ops"] == 0
    assert delta["layer_hits"] == 6
    assert delta["control_hits"] == 1
    assert not np.array_equal(original.mask_fields["layer-0"], changed.mask_fields["layer-0"])
    fresh = RenderEngine().render_uncached(edited)
    np.testing.assert_array_equal(changed.rgba_field, fresh.rgba_field)
    np.testing.assert_array_equal(changed.mask_fields["layer-0"], fresh.mask_fields["layer-0"])


def test_control_cache_reuses_raw_value_for_mapping_edit_but_dependencies_invalidate(tmp_path):
    controls = {
        "root": scalar_control(
            "root",
            ControlFieldBinding("middle", ControlFieldMapping(output_min=0.5, output_max=3.0)),
            mapping=ControlFieldMapping(),
        ),
        "middle": scalar_control(
            "middle",
            ControlFieldBinding("leaf", ControlFieldMapping(output_min=0.5, output_max=3.0)),
        ),
        "leaf": scalar_control("leaf", 2.0),
        "unrelated": scalar_control("unrelated", 1.5),
    }
    recipe = six_layer_recipe(controls=controls)
    recipe.layers[0].mask = ControlFieldBinding("root")
    recipe.layers[1:] = []
    session = RenderSession()
    engine = RenderEngine(session=session)
    engine.render(recipe)

    unrelated_edit = copy.deepcopy(recipe)
    unrelated_edit.control_fields["unrelated"].source.parameters["scale"] += 0.2
    before = session.stats
    engine.render(unrelated_edit)
    delta = _delta(session, before)
    assert delta["ops"] == 0
    assert delta["control_hits"] == 1 and delta["control_misses"] == 0

    transitive_edit = copy.deepcopy(unrelated_edit)
    transitive_edit.control_fields["leaf"].source.parameters["scale"] += 0.3
    before = session.stats
    engine.render(transitive_edit)
    delta = _delta(session, before)
    assert delta["ops"] == 3
    assert delta["control_misses"] == 3

    mapping_edit = copy.deepcopy(transitive_edit)
    mapping_edit.control_fields["root"].mapping = ControlFieldMapping(
        output_min=0.2, output_max=0.8
    )
    before = session.stats
    engine.render(mapping_edit)
    delta = _delta(session, before)
    assert delta["ops"] == 0
    assert delta["control_hits"] == 1 and delta["control_misses"] == 0
    assert session.stats["controls"]["hits"] > before["controls"]["hits"]


def test_global_mapping_change_invalidates_transitive_dependent_content():
    controls = {
        "root-map": scalar_control(
            "root-map", 2.0, mapping=ControlFieldMapping(output_min=0.1, output_max=0.9)
        ),
        "child": scalar_control(
            "child",
            ControlFieldBinding("root-map", ControlFieldMapping(output_min=2.0, output_max=5.0)),
        ),
    }
    recipe = six_layer_recipe(with_mask=False, controls=controls)
    recipe.layers[0].source.parameters["scale"] = ControlFieldBinding(
        "child", ControlFieldMapping(output_min=2.0, output_max=5.0)
    )
    session = RenderSession()
    engine = RenderEngine(session=session)
    engine.render(recipe)
    edited = copy.deepcopy(recipe)
    edited.control_fields["root-map"].mapping = ControlFieldMapping(output_min=0.3, output_max=0.8)
    before = session.stats
    engine.render(edited)
    delta = _delta(session, before)
    assert delta["ops"] == 3
    assert delta["control_hits"] == 1
    assert delta["control_misses"] == 1
    assert delta["layer_hits"] == 5
    assert delta["layer_misses"] == 1
    original_solo = copy.deepcopy(recipe)
    original_solo.layers = original_solo.layers[:1]
    edited_solo = copy.deepcopy(edited)
    edited_solo.layers = edited_solo.layers[:1]
    original_pixels = RenderEngine().render_uncached(original_solo).rgba_field
    changed_pixels = RenderEngine().render_uncached(edited_solo).rgba_field
    assert not np.array_equal(original_pixels, changed_pixels)
    np.testing.assert_array_equal(
        engine.render(edited_solo).rgba_field,
        RenderEngine().render_uncached(edited_solo).rgba_field,
    )


def test_asset_change_in_mask_control_invalidates_mask_but_not_layer_content(tmp_path):
    image_path = tmp_path / "mask.png"
    Image.new("RGBA", (8, 8), (255, 0, 0, 255)).save(image_path)
    mask_control = ControlFieldRecipe(
        operation(
            "generator.image",
            "mask-image",
            asset=AssetReference(str(image_path)),
        ),
        [operation("transform.extract_channel", "red-channel", channel="Red")],
    )
    recipe = six_layer_recipe(controls={"mask": mask_control})
    session = RenderSession()
    engine = RenderEngine(session=session)
    context = RenderContext(tmp_path / "project.atx", session.asset_cache)
    engine.render(recipe, render_context=context)

    Image.new("RGBA", (8, 8), (0, 0, 255, 255)).save(image_path)
    before = session.stats
    changed = engine.render(recipe, render_context=context)
    delta = _delta(session, before)
    assert delta["ops"] == 2
    assert delta["layer_hits"] == 6
    assert delta["layer_misses"] == 0
    assert session.asset_cache.stats["decodes"] == 2
    fresh = RenderEngine().render_uncached(
        recipe, render_context=RenderContext(tmp_path / "project.atx")
    )
    np.testing.assert_array_equal(changed.rgba_field, fresh.rgba_field)
    np.testing.assert_array_equal(changed.mask_fields["layer-0"], fresh.mask_fields["layer-0"])
    np.testing.assert_array_equal(
        changed.mask_fields["layer-0"], np.zeros((18, 24), dtype=np.float32)
    )

    unrelated_path = tmp_path / "unused.png"
    Image.new("RGBA", (8, 8), (120, 40, 10, 255)).save(unrelated_path)
    unrelated = copy.deepcopy(recipe)
    unrelated.control_fields["unused"] = ControlFieldRecipe(
        operation("generator.image", "unused-image", asset=AssetReference(str(unrelated_path))),
        [operation("transform.extract_channel", "unused-channel", channel="Red")],
    )
    before = session.stats
    engine.render(unrelated, render_context=context)
    assert _delta(session, before)["ops"] == 0
    Image.new("RGBA", (8, 8), (10, 20, 240, 255)).save(unrelated_path)
    before = session.stats
    engine.render(unrelated, render_context=context)
    delta = _delta(session, before)
    assert delta["ops"] == 0
    assert delta["layer_hits"] == 6
    assert session.asset_cache.stats["decodes"] == 2
