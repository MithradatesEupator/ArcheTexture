from __future__ import annotations

import json
import shutil

import numpy as np
import pytest
from PIL import Image

from archetexture.core.assets import AssetReference, AssetResolutionError, RenderContext
from archetexture.core.recipe import LayerRecipe, OperationInstance, ProjectRecipe
from archetexture.core.registry import REGISTRY
from archetexture.core.serialization import load_project, migrate_recipe, save_project
from archetexture.render.engine import RenderEngine


def _recipe(reference: AssetReference, operation: str = "generator.image") -> ProjectRecipe:
    definition = REGISTRY.get(operation)
    parameters = {spec.identifier: spec.default for spec in definition.parameter_specs}
    parameters["asset"] = reference
    return ProjectRecipe(
        width=4,
        height=4,
        layers=[
            LayerRecipe(
                "layer", "Image", OperationInstance("source", operation, 1, parameters=parameters)
            )
        ],
    )


def test_image_source_preserves_alpha_and_renders_float32_rgba(tmp_path):
    source = np.array([[[255, 32, 16, 128], [0, 128, 255, 255]]], dtype=np.uint8)
    path = tmp_path / "source.png"
    Image.fromarray(source, "RGBA").save(path)
    recipe = _recipe(AssetReference(str(path)))
    recipe.width, recipe.height = 2, 1
    rendered = RenderEngine().render(recipe).rgba_field
    assert rendered.dtype == np.float32
    np.testing.assert_allclose(rendered[0, 0], (1, 32 / 255, 16 / 255, 128 / 255))
    np.testing.assert_allclose(rendered[0, 1], (0, 128 / 255, 1, 1))


def test_decode_applies_exif_orientation_and_tile_fit_repeats_pixels(tmp_path):
    oriented_path = tmp_path / "oriented.jpg"
    exif = Image.Exif()
    exif[274] = 6
    Image.new("RGB", (2, 1), (40, 80, 120)).save(oriented_path, exif=exif)
    oriented = RenderContext().load_rgba8(AssetReference(str(oriented_path)))
    assert oriented.shape == (2, 1, 4)

    tile_path = tmp_path / "tile.png"
    Image.fromarray(np.array([[[255, 0, 0, 255], [0, 0, 255, 255]]], dtype=np.uint8), "RGBA").save(
        tile_path
    )
    recipe = _recipe(AssetReference(str(tile_path)))
    recipe.width, recipe.height = 4, 1
    recipe.layers[0].source.parameters["fit"] = "Tile"
    recipe.layers[0].source.parameters["resampling"] = "Nearest"
    rendered = RenderEngine().render(recipe).rgba_field
    np.testing.assert_allclose(rendered[0, :, 0], [1, 0, 1, 0])


def test_image_channel_mask_and_extract_channel_are_scalar(tmp_path):
    path = tmp_path / "mask.png"
    Image.fromarray(np.array([[[255, 0, 0, 128]]], dtype=np.uint8), "RGBA").save(path)
    recipe = _recipe(AssetReference(str(path)), "generator.image_channel")
    recipe.width = recipe.height = 1
    recipe.layers[0].source.parameters["channel"] = "Alpha"
    result = RenderEngine().render(recipe)
    np.testing.assert_allclose(result.scalar_field, [[128 / 255]])

    rgba_recipe = _recipe(AssetReference(str(path)))
    rgba_recipe.width = rgba_recipe.height = 1
    rgba_recipe.layers[0].transforms.append(
        OperationInstance(
            "extract",
            "transform.extract_channel",
            1,
            parameters={"channel": "Red"},
        )
    )
    extracted = RenderEngine().render(rgba_recipe).scalar_field
    np.testing.assert_allclose(extracted, [[1.0]])


def test_project_relative_reference_round_trip_and_schema3_migration(tmp_path):
    assets = tmp_path / "assets"
    assets.mkdir()
    Image.new("RGBA", (1, 1), (1, 2, 3, 255)).save(assets / "sample.png")
    project = tmp_path / "project.archetexture"
    recipe = _recipe(AssetReference("assets/sample.png", "project_relative"))
    save_project(recipe, project)
    payload = json.loads(project.read_text())
    assert payload["schema_version"] == 5
    assert (
        payload["outputs"][0]["layers"][0]["source"]["parameters"]["asset"]["$type"]
        == "asset_reference"
    )
    restored = load_project(project)
    assert restored == recipe
    assert RenderEngine().render(
        restored, render_context=RenderContext(project)
    ).rgba_field.shape == (4, 4, 4)
    relocated = tmp_path / "relocated"
    relocated.mkdir()
    shutil.copytree(assets, relocated / "assets")
    moved_project = relocated / project.name
    shutil.copy2(project, moved_project)
    moved = load_project(moved_project)
    assert RenderEngine().render(
        moved, render_context=RenderContext(moved_project)
    ).rgba_field.shape == (4, 4, 4)
    old = migrate_recipe(
        {
            "schema_version": 3,
            "layers": [
                {
                    "layer_id": "l",
                    "name": "L",
                    "source": {
                        "instance_id": "s",
                        "operation_id": "generator.constant",
                        "operation_version": 1,
                        "parameters": {"value": 0.5},
                    },
                }
            ],
        }
    )
    assert old.schema_version == 5


def test_missing_asset_loads_but_fails_at_render_boundary(tmp_path):
    project = tmp_path / "missing.archetexture"
    save_project(_recipe(AssetReference("lost.png", "project_relative")), project)
    restored = load_project(project)
    with pytest.raises(AssetResolutionError, match="Cannot resolve image asset"):
        RenderEngine().render(restored, render_context=RenderContext(project))


def test_image_cache_is_bounded_and_invalidates_changed_files(tmp_path):
    path = tmp_path / "cache.png"
    Image.new("RGBA", (1, 1), (0, 0, 0, 255)).save(path)
    ref = AssetReference(str(path))
    context = RenderContext(cache_entries=1)
    first = context.load_rgba8(ref)
    assert context.load_rgba8(ref) is first
    Image.new("RGBA", (2, 1), (255, 0, 0, 255)).save(path)
    second = context.load_rgba8(ref)
    assert first.shape != second.shape
    assert context.asset_cache.stats["entries"] == 1
