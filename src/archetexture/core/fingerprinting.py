from __future__ import annotations

import hashlib
import json
from dataclasses import fields, is_dataclass
from enum import Enum
from pathlib import Path
from typing import Any

import numpy as np

from archetexture.core.assets import AssetReference, RenderContext


def _normalize(value: Any) -> Any:
    if isinstance(value, AssetReference):
        return {"type": "asset", "path": value.path, "mode": value.mode, "kind": value.kind}
    if is_dataclass(value):
        return {
            "type": type(value).__qualname__,
            **{item.name: _normalize(getattr(value, item.name)) for item in fields(value)},
        }
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, dict):
        return {str(key): _normalize(value[key]) for key in sorted(value, key=str)}
    if isinstance(value, (tuple, list)):
        return [_normalize(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    raise TypeError(f"Cannot fingerprint {type(value).__name__}")


def _asset_references(value: Any):
    if isinstance(value, AssetReference):
        yield value
    elif is_dataclass(value):
        for item in fields(value):
            yield from _asset_references(getattr(value, item.name))
    elif isinstance(value, dict):
        for item in value.values():
            yield from _asset_references(item)
    elif isinstance(value, (tuple, list)):
        for item in value:
            yield from _asset_references(item)


def structural_fingerprint(payload: Any, context: RenderContext) -> str:
    references = sorted(
        set(_asset_references(payload)), key=lambda ref: (ref.mode, ref.path, ref.kind)
    )
    normalized = {
        "value": _normalize(payload),
        "assets": [context.asset_signature(reference) for reference in references],
    }
    encoded = json.dumps(normalized, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()
