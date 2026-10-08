from __future__ import annotations

import os
import re
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable

import numpy as np
from PIL import Image

from archetexture.core.assets import RenderContext
from archetexture.core.recipe import ProjectRecipe
from archetexture.core.validation import ValidationError, ensure_valid_recipe
from archetexture.render.engine import MaterialOutputResult, RenderEngine
from archetexture.render.pixels import rgba_float_to_uint8


class TextureSetExportError(RuntimeError):
    pass


@dataclass(frozen=True)
class OutputExportSpec:
    output_id: str
    suffix: str
    include: bool = True
    bit_depth: int = 8


@dataclass(frozen=True)
class PackedChannelSpec:
    source_output_id: str | None = None
    component: str | None = None
    constant: float | None = None
    invert: bool = False


@dataclass(frozen=True)
class PackedMapSpec:
    suffix: str
    channels: dict[str, PackedChannelSpec]
    name: str = "Custom RGBA Pack"


@dataclass(frozen=True)
class TextureSetExportPlan:
    destination: str
    filename_base: str
    width: int
    height: int
    outputs: tuple[OutputExportSpec, ...] | None = None
    packed_maps: tuple[PackedMapSpec, ...] = ()
    overwrite: bool = False

    def to_dict(self) -> dict:
        return {
            "destination": self.destination,
            "filename_base": self.filename_base,
            "width": self.width,
            "height": self.height,
            "outputs": None if self.outputs is None else [asdict(item) for item in self.outputs],
            "packed_maps": [
                {
                    "suffix": item.suffix,
                    "name": item.name,
                    "channels": {key: asdict(value) for key, value in item.channels.items()},
                }
                for item in self.packed_maps
            ],
            "overwrite": self.overwrite,
        }


def packed_preset(
    name: str,
    recipe: ProjectRecipe,
    *,
    detail_output_id: str | None = None,
    detail_channel: PackedChannelSpec | None = None,
) -> PackedMapSpec:
    output_ids = {}
    for semantic in ("ambient_occlusion", "roughness", "metallic"):
        matches = [item.output_id for item in recipe.outputs if item.semantic == semantic]
        if len(matches) > 1:
            raise TextureSetExportError(
                f"Packing preset {name} is ambiguous: multiple {semantic} outputs exist"
            )
        if matches:
            output_ids[semantic] = matches[0]

    def source(semantic: str, component: str | None = None) -> PackedChannelSpec:
        output_id = output_ids.get(semantic)
        if output_id is None:
            raise TextureSetExportError(
                f"Packing preset {name} requires a {semantic.replace('_', ' ')} output"
            )
        return PackedChannelSpec(output_id, component)

    one = PackedChannelSpec(constant=1.0)
    if name == "ORM":
        channels = {
            "R": source("ambient_occlusion"),
            "G": source("roughness"),
            "B": source("metallic"),
            "A": one,
        }
    elif name == "RMA":
        channels = {
            "R": source("roughness"),
            "G": source("metallic"),
            "B": source("ambient_occlusion"),
            "A": one,
        }
    elif name == "MRA":
        channels = {
            "R": source("metallic"),
            "G": source("roughness"),
            "B": source("ambient_occlusion"),
            "A": one,
        }
    elif name == "Unity HDRP-like Mask Map":
        detail = detail_channel or (
            PackedChannelSpec(source_output_id=detail_output_id) if detail_output_id else one
        )
        roughness = source("roughness")
        channels = {
            "R": source("metallic"),
            "G": source("ambient_occlusion"),
            "B": detail,
            "A": PackedChannelSpec(roughness.source_output_id, roughness.component, invert=True),
        }
    else:
        raise TextureSetExportError(f"Unknown channel-packing preset: {name}")
    return PackedMapSpec(name.replace(" ", ""), channels, name)


def _safe_part(value: str) -> str:
    result = re.sub(r"[^A-Za-z0-9_.-]+", "_", value.strip()).strip("._-")
    if not result or result in {".", ".."}:
        raise TextureSetExportError("Filename and suffix must contain at least one safe character")
    return result


class TextureSetExporter:
    def __init__(self, engine: RenderEngine | None = None):
        self.engine = engine or RenderEngine()

    def preflight(self, recipe: ProjectRecipe, plan: TextureSetExportPlan) -> tuple[Path, ...]:
        try:
            ensure_valid_recipe(recipe, self.engine.registry)
        except ValidationError as exc:
            raise TextureSetExportError(f"Invalid material dependency graph: {exc}") from exc
        if isinstance(plan.width, bool) or not 1 <= plan.width <= 8192:
            raise TextureSetExportError("Export width must be between 1 and 8192")
        if isinstance(plan.height, bool) or not 1 <= plan.height <= 8192:
            raise TextureSetExportError("Export height must be between 1 and 8192")
        if not plan.filename_base.strip():
            raise TextureSetExportError("Filename base cannot be empty")
        destination = Path(plan.destination)
        if destination.exists() and not destination.is_dir():
            raise TextureSetExportError(f"Destination is not a directory: {destination}")
        parent = destination if destination.exists() else destination.parent
        if not parent.exists() or not parent.is_dir():
            raise TextureSetExportError(f"Destination parent is unavailable: {parent}")
        output_by_id = {item.output_id: item for item in recipe.outputs}
        paths = []
        names = set()
        specs = (
            plan.outputs
            if plan.outputs is not None
            else tuple(
                OutputExportSpec(item.output_id, item.export_suffix, item.enabled)
                for item in recipe.outputs
            )
        )
        for spec in specs:
            if not spec.include:
                continue
            output = output_by_id.get(spec.output_id)
            if output is None:
                raise TextureSetExportError(
                    f"Unknown output requested for export: {spec.output_id}"
                )
            if spec.bit_depth not in (8, 16) or (
                spec.bit_depth == 16 and output.value_type != "scalar"
            ):
                raise TextureSetExportError("16-bit export is supported only for scalar outputs")
            paths.append(self._unique_path(destination, plan.filename_base, spec.suffix, names))
        for packed in plan.packed_maps:
            if set(packed.channels) != {"R", "G", "B", "A"}:
                raise TextureSetExportError(f"{packed.name} must define R, G, B, and A channels")
            for channel, source in packed.channels.items():
                if not isinstance(source, PackedChannelSpec):
                    raise TextureSetExportError(f"Packed channel {channel} has an invalid source")
                if source.source_output_id is None:
                    if source.constant not in (0, 1, 0.0, 1.0):
                        raise TextureSetExportError(
                            f"Packed channel {channel} constant must be 0 or 1"
                        )
                elif source.source_output_id not in output_by_id:
                    raise TextureSetExportError(
                        f"Packed channel {channel} references missing output "
                        f"{source.source_output_id}"
                    )
                elif output_by_id[source.source_output_id].value_type == "scalar":
                    if source.component is not None:
                        raise TextureSetExportError(
                            f"Scalar source for channel {channel} cannot select a color component"
                        )
                elif source.component not in {"R", "G", "B", "A"}:
                    raise TextureSetExportError(
                        f"Color source for channel {channel} requires component R, G, B, or A"
                    )
            paths.append(self._unique_path(destination, plan.filename_base, packed.suffix, names))
        if not paths:
            raise TextureSetExportError("Select at least one output or packed map to export")
        if not plan.overwrite:
            conflicts = [path for path in paths if path.exists()]
            if conflicts:
                raise TextureSetExportError(
                    "Files already exist: " + ", ".join(str(p) for p in conflicts)
                )
        return tuple(paths)

    @staticmethod
    def _unique_path(destination: Path, base: str, suffix: str, names: set[str]) -> Path:
        filename = f"{_safe_part(base)}_{_safe_part(suffix)}.png"
        key = filename.casefold()
        if key in names:
            raise TextureSetExportError(f"Filename collision: {filename}")
        names.add(key)
        return destination / filename

    def export(
        self,
        recipe: ProjectRecipe,
        plan: TextureSetExportPlan,
        *,
        render_context: RenderContext | None = None,
        progress: Callable[[str], None] | None = None,
    ) -> tuple[Path, ...]:
        files = self.preflight(recipe, plan)
        destination = Path(plan.destination)
        destination.mkdir(parents=True, exist_ok=True)
        output_by_id = {item.output_id: item for item in recipe.outputs}
        specs = [
            item
            for item in (
                plan.outputs
                if plan.outputs is not None
                else tuple(
                    OutputExportSpec(item.output_id, item.export_suffix, item.enabled)
                    for item in recipe.outputs
                )
            )
            if item.include
        ]
        for spec in specs:
            if progress:
                progress(f"Rendering {output_by_id[spec.output_id].name}…")
        requested_ids = list(spec.output_id for spec in specs)
        requested_ids.extend(
            source.source_output_id
            for packed in plan.packed_maps
            for source in packed.channels.values()
            if source.source_output_id is not None
        )
        try:
            rendered: dict[str, MaterialOutputResult] = self.engine.render_outputs(
                recipe,
                requested_ids,
                width=plan.width,
                height=plan.height,
                render_context=render_context,
            )
        except Exception as exc:
            names = ", ".join(output_by_id[item].name for item in dict.fromkeys(requested_ids))
            raise TextureSetExportError(f"Rendering texture-set outputs {names!r} failed: {exc}") from exc
        for packed in plan.packed_maps:
            if progress:
                progress(f"Packing {packed.name}…")

        written: list[Path] = []
        file_index = 0
        try:
            for spec in specs:
                path = files[file_index]
                file_index += 1
                result = rendered[spec.output_id]
                if progress:
                    progress(f"Writing {path.name}…")
                if result.value_type == "scalar":
                    pixels = _scalar_pixels(result.scalar_field, spec.bit_depth)
                else:
                    pixels = rgba_float_to_uint8(result.rgba_field)
                self._write_png(path, pixels)
                written.append(path)
            for packed in plan.packed_maps:
                path = files[file_index]
                file_index += 1
                channels = []
                for key in ("R", "G", "B", "A"):
                    spec = packed.channels[key]
                    if spec.source_output_id is None:
                        field = np.full((plan.height, plan.width), spec.constant, dtype=np.float32)
                    else:
                        result = rendered[spec.source_output_id]
                        output = output_by_id[spec.source_output_id]
                        if output.value_type == "scalar":
                            field = result.scalar_field
                        else:
                            field = result.rgba_field[..., "RGBA".index(spec.component)]
                    if spec.invert:
                        field = 1.0 - field
                    channels.append(np.clip(field, 0.0, 1.0))
                pixels = np.rint(np.stack(channels, axis=-1) * 255.0).astype(np.uint8)
                if progress:
                    progress(f"Writing {path.name}…")
                self._write_png(path, pixels)
                written.append(path)
        except Exception as exc:
            filename = files[len(written)] if len(written) < len(files) else destination
            raise TextureSetExportError(f"Texture-set export failed at {filename}: {exc}") from exc
        return tuple(written)

    @staticmethod
    def _write_png(path: Path, pixels: np.ndarray) -> None:
        temporary_path = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w+b", dir=path.parent, prefix=f".{path.name}.", suffix=".tmp", delete=False
            ) as stream:
                temporary_path = stream.name
                Image.fromarray(pixels).save(stream, format="PNG")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary_path, path)
            temporary_path = None
        finally:
            if temporary_path:
                try:
                    os.unlink(temporary_path)
                except OSError:
                    pass


def _scalar_pixels(field: np.ndarray | None, bit_depth: int) -> np.ndarray:
    if field is None:
        raise TextureSetExportError("Scalar output did not provide its authoritative scalar field")
    values = np.clip(field, 0.0, 1.0)
    if bit_depth == 16:
        return np.rint(values * 65535.0).astype(np.uint16)
    return np.rint(values * 255.0).astype(np.uint8)
