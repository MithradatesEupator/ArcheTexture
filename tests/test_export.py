import numpy as np
import pytest
from PIL import Image

from archetexture.color.ramp import ColorRamp, ColorStop
from archetexture.core.recipe import OperationInstance, ProjectRecipe
from archetexture.export.image_export import ExportError, ImageExporter
from archetexture.render.engine import RenderEngine
from archetexture.render.pixels import rgba_float_to_uint8


def default_recipe() -> ProjectRecipe:
    return ProjectRecipe(
        width=23,
        height=19,
        seed=31,
        source=OperationInstance("source", "generator.white_noise", 1, parameters={"seed": 71}),
        color_ramp=ColorRamp(
            (
                ColorStop(0.0, (0.025, 0.04, 0.11, 0.2)),
                ColorStop(0.48, (0.12, 0.42, 0.64, 0.6)),
                ColorStop(1.0, (0.96, 0.68, 0.27, 0.9)),
            )
        ),
    )


@pytest.mark.parametrize("size", [(17, 9), (12, 12)])
def test_png_is_exact_render_rgba_and_size_override_preserves_recipe(tmp_path, size):
    recipe = default_recipe()
    recipe.width, recipe.height = 31, 27
    before = repr(recipe)
    width, height = size
    destination = tmp_path / "result.png"
    ImageExporter().export_png(recipe, destination, width=width, height=height)
    with Image.open(destination) as image:
        assert image.mode == "RGBA"
        assert image.size == size
        actual = np.asarray(image)
    expected = rgba_float_to_uint8(
        RenderEngine().render(recipe, width=width, height=height).rgba_field
    )
    np.testing.assert_array_equal(actual, expected)
    assert repr(recipe) == before


def test_png_is_deterministic(tmp_path):
    recipe = default_recipe()
    exporter = ImageExporter()
    first, second = tmp_path / "a.png", tmp_path / "b.png"
    exporter.export_png(recipe, first, width=11, height=7)
    exporter.export_png(recipe, second, width=11, height=7)
    np.testing.assert_array_equal(np.asarray(Image.open(first)), np.asarray(Image.open(second)))


def test_grayscale_and_transform_pipeline_export_as_rgba(tmp_path):
    recipe = ProjectRecipe(
        width=8,
        height=5,
        source=OperationInstance("source", "generator.constant", 1, parameters={"value": 0.4}),
        transforms=[OperationInstance("invert", "transform.invert", 1)],
    )
    destination = tmp_path / "gray.png"
    ImageExporter().export_png(recipe, destination)
    pixels = np.asarray(Image.open(destination))
    assert pixels.shape == (5, 8, 4)
    np.testing.assert_array_equal(pixels[..., 0], pixels[..., 1])
    np.testing.assert_array_equal(pixels[..., 1], pixels[..., 2])
    np.testing.assert_array_equal(pixels[..., 3], np.full((5, 8), 255, dtype=np.uint8))


@pytest.mark.parametrize("width,height", [(0, 2), (2, 0), (8193, 1), (True, 1)])
def test_rejects_invalid_dimensions(tmp_path, width, height):
    with pytest.raises(ExportError):
        ImageExporter().export_png(
            default_recipe(), tmp_path / "bad.png", width=width, height=height
        )


def test_failed_render_preserves_existing_destination_and_cleans_temp(tmp_path):
    class BrokenEngine:
        def render(self, *_args, **_kwargs):
            raise RuntimeError("render broke")

    destination = tmp_path / "existing.png"
    destination.write_bytes(b"previous bytes")
    with pytest.raises(ExportError, match="render broke"):
        ImageExporter(BrokenEngine()).export_png(default_recipe(), destination, width=4, height=3)
    assert destination.read_bytes() == b"previous bytes"
    assert list(tmp_path.iterdir()) == [destination]


def test_replace_failure_preserves_destination_and_cleans_temp(tmp_path, monkeypatch):
    import archetexture.export.image_export as module

    destination = tmp_path / "existing.png"
    destination.write_bytes(b"previous bytes")
    monkeypatch.setattr(
        module.os, "replace", lambda *_args: (_ for _ in ()).throw(OSError("replace broke"))
    )
    with pytest.raises(ExportError, match="replace broke"):
        ImageExporter().export_png(default_recipe(), destination, width=4, height=3)
    assert destination.read_bytes() == b"previous bytes"
    assert list(tmp_path.iterdir()) == [destination]


def test_encoder_failure_preserves_destination_and_cleans_temp(tmp_path, monkeypatch):
    destination = tmp_path / "existing.png"
    destination.write_bytes(b"previous bytes")

    def fail_save(*_args, **_kwargs):
        raise OSError("encode broke")

    monkeypatch.setattr(Image.Image, "save", fail_save)
    with pytest.raises(ExportError, match="encode broke"):
        ImageExporter().export_png(default_recipe(), destination, width=4, height=3)
    assert destination.read_bytes() == b"previous bytes"
    assert list(tmp_path.iterdir()) == [destination]


def test_missing_output_directory_is_rejected(tmp_path):
    with pytest.raises(ExportError, match="does not exist"):
        ImageExporter().export_png(
            default_recipe(), tmp_path / "missing" / "out.png", width=2, height=2
        )
