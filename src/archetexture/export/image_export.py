from __future__ import annotations

import os
import tempfile
from copy import deepcopy
from pathlib import Path

from PIL import Image

from archetexture.core.assets import RenderContext
from archetexture.core.recipe import ProjectRecipe
from archetexture.render.engine import RenderEngine
from archetexture.render.pixels import rgba_float_to_uint8


class ExportError(RuntimeError):
    """A PNG could not be rendered or safely written."""


def validate_export_dimension(value: int, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 8192:
        raise ExportError(f"{name} must be an integer from 1 to 8192 pixels.")
    return value


class ImageExporter:
    def __init__(self, engine: RenderEngine | None = None):
        self.engine = engine or RenderEngine()

    def export_png(
        self,
        recipe: ProjectRecipe,
        destination: str | Path,
        *,
        width: int | None = None,
        height: int | None = None,
        render_context: RenderContext | None = None,
    ) -> Path:
        snapshot = deepcopy(recipe)
        width = validate_export_dimension(snapshot.width if width is None else width, "Width")
        height = validate_export_dimension(snapshot.height if height is None else height, "Height")
        destination = Path(destination)
        if destination.suffix.lower() != ".png":
            raise ExportError("PNG output path must have a .png extension.")
        if not destination.parent.is_dir():
            raise ExportError(f"Output directory does not exist: {destination.parent}")

        try:
            result = self.engine.render(
                snapshot, width=width, height=height, render_context=render_context
            )
            pixels = rgba_float_to_uint8(result.rgba_field)
        except Exception as exc:
            raise ExportError(f"Could not render PNG: {exc}") from exc

        temporary_path: str | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w+b",
                dir=destination.parent,
                prefix=f".{destination.name}.",
                suffix=".tmp",
                delete=False,
            ) as stream:
                temporary_path = stream.name
                Image.fromarray(pixels, mode="RGBA").save(stream, format="PNG")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary_path, destination)
            temporary_path = None
            return destination
        except Exception as exc:
            raise ExportError(f"Could not write PNG {destination}: {exc}") from exc
        finally:
            if temporary_path is not None:
                try:
                    os.unlink(temporary_path)
                except FileNotFoundError:
                    pass
