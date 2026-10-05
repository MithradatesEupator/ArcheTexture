from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from archetexture.core.recipe import ProjectRecipe


def migrate_recipe(data: dict[str, Any]) -> ProjectRecipe:
    version = int(data.get("schema_version", 1))
    if version != 1:
        raise ValueError(f"Unsupported schema version: {version}")
    source = data.get("source")
    transforms = data.get("transforms", [])
    return ProjectRecipe(
        schema_version=1,
        width=int(data.get("width", 256)),
        height=int(data.get("height", 256)),
        seed=int(data.get("seed", 0)),
        source=source,
        transforms=transforms,
        color_ramp=data.get("color_ramp"),
    )


def load_project(path: str | Path) -> ProjectRecipe:
    with open(path, "r", encoding="utf-8") as fh:
        payload = json.load(fh)
    return migrate_recipe(payload)


def save_project(recipe: ProjectRecipe, path: str | Path) -> None:
    payload = {
        "schema_version": recipe.schema_version,
        "width": recipe.width,
        "height": recipe.height,
        "seed": recipe.seed,
        "source": recipe.source,
        "transforms": recipe.transforms,
        "color_ramp": recipe.color_ramp,
    }
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, sort_keys=True)
