from __future__ import annotations

import json
import math
import os
import tempfile
from pathlib import Path
from typing import Any

from archetexture.color.ramp import ColorRamp, ColorStop
from archetexture.core.parameters import ControlFieldBinding, ControlFieldMapping
from archetexture.core.recipe import (
    ControlFieldRecipe,
    LayerRecipe,
    OperationInstance,
    ProjectRecipe,
)
from archetexture.core.validation import ensure_valid_recipe

CURRENT_SCHEMA_VERSION = 3


class ProjectFormatError(ValueError):
    pass


class UnsupportedSchemaVersion(ProjectFormatError):
    pass


def _encode_value(value: Any) -> Any:
    if isinstance(value, ControlFieldBinding):
        return {
            "$type": "control_field_binding",
            "source_id": value.source_id,
            "mapping": _encode_mapping(value.mapping),
        }
    if isinstance(value, tuple):
        return {"$type": "tuple", "items": [_encode_value(item) for item in value]}
    if isinstance(value, list):
        return [_encode_value(item) for item in value]
    if isinstance(value, dict):
        if any(not isinstance(key, str) for key in value):
            raise ProjectFormatError("Nested parameter object keys must be strings")
        return {key: _encode_value(item) for key, item in value.items()}
    if isinstance(value, float) and not math.isfinite(value):
        raise ProjectFormatError("Project parameters cannot contain non-finite numbers")
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise ProjectFormatError(f"Unsupported project value: {type(value).__name__}")


def _decode_value(value: Any) -> Any:
    if isinstance(value, list):
        return [_decode_value(item) for item in value]
    if isinstance(value, dict):
        tagged_type = value.get("$type")
        if tagged_type == "tuple":
            items = value.get("items")
            if not isinstance(items, list):
                raise ProjectFormatError("Tuple encoding must contain an items array")
            return tuple(_decode_value(item) for item in items)
        if tagged_type == "control_field_binding":
            mapping = _decode_mapping(value.get("mapping", {}))
            return ControlFieldBinding(str(value.get("source_id", "")), mapping)
        return {key: _decode_value(item) for key, item in value.items()}
    return value


def _encode_mapping(mapping: ControlFieldMapping) -> dict[str, Any]:
    return {
        "output_min": mapping.output_min,
        "output_max": mapping.output_max,
        "invert": mapping.invert,
        "curve": mapping.curve,
        "quantize": mapping.quantize,
    }


def _decode_mapping(payload: Any) -> ControlFieldMapping:
    if not isinstance(payload, dict):
        raise ProjectFormatError("Control field mapping must be an object")
    return ControlFieldMapping(
        output_min=payload.get("output_min", 0.0),
        output_max=payload.get("output_max", 1.0),
        invert=payload.get("invert", False),
        curve=payload.get("curve", "linear"),
        quantize=payload.get("quantize"),
    )


def _encode_instance(instance: OperationInstance | None) -> dict[str, Any] | None:
    if instance is None:
        return None
    return {
        "instance_id": instance.instance_id,
        "operation_id": instance.operation_id,
        "operation_version": instance.operation_version,
        "enabled": instance.enabled,
        "parameters": _encode_value(instance.parameters),
        "influence": _encode_value(instance.influence),
    }


def _decode_instance(payload: Any, *, allow_none: bool = False) -> OperationInstance | None:
    if payload is None and allow_none:
        return None
    if not isinstance(payload, dict):
        raise ProjectFormatError("Operation instances must be JSON objects")
    params = _decode_value(payload.get("parameters", {}))
    if not isinstance(params, dict):
        raise ProjectFormatError("Operation parameters must be an object")
    return OperationInstance(
        instance_id=payload.get("instance_id", ""),
        operation_id=payload.get("operation_id", ""),
        operation_version=payload.get("operation_version", 0),
        enabled=payload.get("enabled", True),
        parameters=params,
        influence=_decode_value(payload.get("influence", 1.0)),
    )


def _encode_ramp(ramp: ColorRamp | None) -> dict[str, Any] | None:
    if ramp is None:
        return None
    return {
        "stops": [{"position": stop.position, "color": list(stop.color)} for stop in ramp.stops]
    }


def _decode_ramp(payload: Any) -> ColorRamp | None:
    if payload is None:
        return None
    if not isinstance(payload, dict) or not isinstance(payload.get("stops"), list):
        raise ProjectFormatError("Color ramp must contain a stops array")
    stops = []
    for item in payload["stops"]:
        if not isinstance(item, dict) or not isinstance(item.get("color"), list):
            raise ProjectFormatError("Color stops must contain position and color fields")
        stops.append(ColorStop(item.get("position"), tuple(item["color"])))
    return ColorRamp(tuple(stops))


def _encode_control(control: ControlFieldRecipe) -> dict[str, Any]:
    return {
        "source": _encode_instance(control.source),
        "transforms": [_encode_instance(item) for item in control.transforms],
        "mapping": _encode_mapping(control.mapping) if control.mapping is not None else None,
    }


def _decode_control(payload: Any) -> ControlFieldRecipe:
    if not isinstance(payload, dict):
        raise ProjectFormatError("Control field recipes must be objects")
    transforms = payload.get("transforms", [])
    if not isinstance(transforms, list):
        raise ProjectFormatError("Control field transforms must be an array")
    mapping = payload.get("mapping")
    return ControlFieldRecipe(
        source=_decode_instance(payload.get("source")),
        transforms=[_decode_instance(item) for item in transforms],
        mapping=_decode_mapping(mapping) if mapping is not None else None,
    )


def _encode_layer(layer: LayerRecipe) -> dict[str, Any]:
    return {
        "layer_id": layer.layer_id,
        "name": layer.name,
        "enabled": layer.enabled,
        "opacity": layer.opacity,
        "blend_mode": layer.blend_mode,
        "source": _encode_instance(layer.source),
        "transforms": [_encode_instance(item) for item in layer.transforms],
        "color_ramp": _encode_ramp(layer.color_ramp),
        "mask": _encode_value(layer.mask),
    }


def _decode_layer(payload: Any, index: int, *, supports_masks: bool = True) -> LayerRecipe:
    if not isinstance(payload, dict):
        raise ProjectFormatError(f"layers[{index}] must be an object")
    transforms = payload.get("transforms", [])
    if not isinstance(transforms, list):
        raise ProjectFormatError(f"layers[{index}].transforms must be an array")
    return LayerRecipe(
        layer_id=payload.get("layer_id", ""),
        name=payload.get("name", ""),
        enabled=payload.get("enabled", True),
        opacity=payload.get("opacity", 1.0),
        blend_mode=payload.get("blend_mode", "normal"),
        source=_decode_instance(payload.get("source")),
        transforms=[_decode_instance(item) for item in transforms],
        color_ramp=_decode_ramp(payload.get("color_ramp")),
        mask=_decode_value(payload.get("mask")) if supports_masks else None,
    )


def migrate_recipe(data: dict[str, Any]) -> ProjectRecipe:
    if not isinstance(data, dict):
        raise ProjectFormatError("Project root must be a JSON object")
    version = data.get("schema_version", CURRENT_SCHEMA_VERSION)
    if not isinstance(version, int) or isinstance(version, bool):
        raise ProjectFormatError("schema_version must be an integer")
    if version > CURRENT_SCHEMA_VERSION:
        raise UnsupportedSchemaVersion(
            f"Project schema {version} is newer than supported schema {CURRENT_SCHEMA_VERSION}"
        )
    if version not in (1, 2, CURRENT_SCHEMA_VERSION):
        raise UnsupportedSchemaVersion(f"Unsupported project schema version: {version}")
    control_fields = data.get("control_fields", {})
    if not isinstance(control_fields, dict):
        raise ProjectFormatError("control_fields must be an object")
    if version == 1:
        transforms = data.get("transforms", [])
        if not isinstance(transforms, list):
            raise ProjectFormatError("transforms must be an array")
        source = _decode_instance(data.get("source"), allow_none=True)
        layers = (
            [
                LayerRecipe(
                    "layer-1",
                    "Layer 1",
                    source,
                    [_decode_instance(item) for item in transforms],
                    _decode_ramp(data.get("color_ramp")),
                )
            ]
            if source is not None
            else []
        )
    else:
        raw_layers = data.get("layers")
        if not isinstance(raw_layers, list):
            raise ProjectFormatError("layers must be an array")
        layers = [
            _decode_layer(item, index, supports_masks=version >= 3)
            for index, item in enumerate(raw_layers)
        ]
    recipe = ProjectRecipe(
        schema_version=CURRENT_SCHEMA_VERSION,
        width=data.get("width", 256),
        height=data.get("height", 256),
        seed=data.get("seed", 0),
        layers=layers,
        control_fields={key: _decode_control(value) for key, value in control_fields.items()},
    )
    ensure_valid_recipe(recipe)
    return recipe


def load_project(path: str | Path) -> ProjectRecipe:
    try:
        with Path(path).open("r", encoding="utf-8") as source:
            payload = json.load(source)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ProjectFormatError(f"Malformed project JSON: {exc}") from exc
    except OSError as exc:
        raise ProjectFormatError(f"Cannot read project file: {exc}") from exc
    return migrate_recipe(payload)


def _encode_recipe(recipe: ProjectRecipe) -> dict[str, Any]:
    return {
        "schema_version": recipe.schema_version,
        "width": recipe.width,
        "height": recipe.height,
        "seed": recipe.seed,
        "layers": [_encode_layer(item) for item in recipe.layers],
        "control_fields": {
            key: _encode_control(recipe.control_fields[key])
            for key in sorted(recipe.control_fields)
        },
    }


def save_project(recipe: ProjectRecipe, path: str | Path) -> None:
    ensure_valid_recipe(recipe)
    payload = _encode_recipe(recipe)
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=output.parent,
            prefix=f".{output.name}.",
            suffix=".tmp",
            delete=False,
        ) as destination:
            temporary_path = destination.name
            json.dump(payload, destination, indent=2, sort_keys=True, allow_nan=False)
            destination.write("\n")
            destination.flush()
            os.fsync(destination.fileno())
        os.replace(temporary_path, output)
    except (OSError, TypeError, ValueError) as exc:
        if temporary_path is not None:
            try:
                os.unlink(temporary_path)
            except OSError:
                pass
        if isinstance(exc, ProjectFormatError):
            raise
        raise ProjectFormatError(f"Cannot write project file: {exc}") from exc
