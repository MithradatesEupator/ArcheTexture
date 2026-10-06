"""Repeatable, non-CI render benchmark for ATX performance work.

Run with ``python tools/benchmark_render_performance.py`` from the repository root.
The report is deliberately observational; it has no timing pass/fail thresholds.
"""

from __future__ import annotations

import copy
import json
import tempfile
import time
from pathlib import Path
from threading import Event

import numpy as np
from PIL import Image

from archetexture.core.assets import AssetReference, RenderContext
from archetexture.core.parameters import ControlFieldBinding
from archetexture.core.recipe import (
    ControlFieldRecipe,
    LayerRecipe,
    OperationInstance,
    ProjectRecipe,
)
from archetexture.core.registry import REGISTRY
from archetexture.render.coordinator import RenderCoordinator
from archetexture.render.engine import RenderEngine
from archetexture.render.session import RenderSession


def operation(operation_id: str, instance_id: str, **overrides) -> OperationInstance:
    definition = REGISTRY.get(operation_id)
    parameters = {spec.identifier: spec.default for spec in definition.parameter_specs}
    parameters.update(overrides)
    return OperationInstance(instance_id, operation_id, definition.version, parameters=parameters)


def procedural_scene(width: int, height: int, *, shared_mask: bool = False) -> ProjectRecipe:
    layers = []
    controls = {}
    if shared_mask:
        controls["shared"] = ControlFieldRecipe(
            operation("generator.fractal_noise", "shared-src", scale=4.0, octaves=5),
            [operation("transform.blur", "shared-blur", sigma=1.1)],
        )
    for index in range(6):
        source_id = "generator.fractal_noise" if index % 2 == 0 else "generator.cellular"
        transforms = [operation("transform.blur", f"blur-{index}", sigma=0.8)]
        layer = LayerRecipe(
            f"layer-{index}",
            f"Layer {index}",
            operation(source_id, f"source-{index}", seed=17 + index, scale=4.0 + index),
            transforms,
        )
        if shared_mask:
            layer.mask = ControlFieldBinding("shared")
        layers.append(layer)
    return ProjectRecipe(
        width=width, height=height, seed=27, layers=layers, control_fields=controls
    )


def simple_scene(width: int, height: int) -> ProjectRecipe:
    return ProjectRecipe(
        width=width,
        height=height,
        layers=[
            LayerRecipe(
                "simple-a", "A", operation("generator.constant", "simple-src-a", value=0.3)
            ),
            LayerRecipe(
                "simple-b", "B", operation("generator.constant", "simple-src-b", value=0.7)
            ),
        ],
    )


def mixed_scene(width: int, height: int, image: Path) -> ProjectRecipe:
    recipe = procedural_scene(width, height, shared_mask=True)
    recipe.layers[0].source = operation(
        "generator.image", "mixed-image", asset=AssetReference(str(image))
    )
    recipe.layers[0].transforms = [
        operation("transform.extract_channel", "mixed-channel", channel="Luminance"),
        operation("transform.height_to_normal", "mixed-normal", strength=1.2),
    ]
    recipe.layers[0].mask = None
    return recipe


def timed(label: str, engine: RenderEngine, recipe: ProjectRecipe, context_factory) -> dict:
    started = time.perf_counter()
    engine.render(recipe, render_context=context_factory())
    return {"measurement": label, "seconds": time.perf_counter() - started}


def run_interactive_sequence(name: str, recipe: ProjectRecipe, project_path: Path) -> list[dict]:
    session = RenderSession()

    def context_factory():
        return RenderContext(project_path, session.asset_cache)

    engine = RenderEngine(session=session)
    results = [timed(f"{name}.cold", engine, recipe, context_factory)]
    results.append(timed(f"{name}.warm_identical", engine, recipe, context_factory))

    edited = copy.deepcopy(recipe)
    parameters = edited.layers[0].source.parameters
    for key, value in parameters.items():
        if isinstance(value, bool):
            continue
        if isinstance(value, int):
            parameters[key] = value + 1
            break
        if isinstance(value, float):
            parameters[key] = value + 0.25
            break
        if isinstance(value, str) and key in {"fit", "channel"}:
            parameters[key] = "Tile" if key == "fit" else "Red"
            break
    results.append(timed(f"{name}.single_layer_edit", engine, edited, context_factory))

    if "shared" in edited.control_fields:
        edited.control_fields["shared"].source.parameters["scale"] += 0.25
        results.append(timed(f"{name}.control_field_edit", engine, edited, context_factory))
    else:
        results.append({"measurement": f"{name}.control_field_edit", "seconds": None})

    edited.layers[0].opacity = 0.7
    results.append(timed(f"{name}.opacity_only", engine, edited, context_factory))
    edited.layers[0].blend_mode = "multiply"
    results.append(timed(f"{name}.blend_only", engine, edited, context_factory))
    edited.layers.reverse()
    results.append(timed(f"{name}.reorder", engine, edited, context_factory))
    edited.layers[0].enabled = False
    results.append(timed(f"{name}.visibility", engine, edited, context_factory))
    if edited.layers[0].color_ramp is not None:
        edited.layers[0].color_ramp = None
        results.append(timed(f"{name}.ramp_change", engine, edited, context_factory))
    results.append({"measurement": f"{name}.diagnostics", "stats": session.stats})
    return results


def run_burst(recipe: ProjectRecipe) -> dict:
    completed = Event()
    outcomes = []
    session = RenderSession()
    coordinator = RenderCoordinator(
        engine=RenderEngine(session=session),
        on_complete=lambda outcome: (outcomes.append(outcome), completed.set()),
    )
    started = time.perf_counter()
    submitted = [
        coordinator.request(recipe, width=recipe.width, height=recipe.height) for _ in range(3)
    ]
    submit_seconds = time.perf_counter() - started
    latest = submitted[-1].request_id
    completed.wait(90)
    total_seconds = time.perf_counter() - started
    published = [outcome.request_id for outcome in outcomes]
    coordinator.close(wait=True)
    return {
        "measurement": "burst_A_B_C_latest_completion",
        "submit_seconds": submit_seconds,
        "seconds": total_seconds,
        "latest_request_id": latest,
        "published_request_ids": published,
        "layer_cache": session.layer_cache.stats,
        "operation_executions": session.stats["operation_executions"],
        "cancellations": session.stats["cancellations"],
    }


def main() -> None:
    rows = []
    with tempfile.TemporaryDirectory(prefix="archetexture-benchmark-") as directory:
        root = Path(directory)
        pixels = np.random.default_rng(7).integers(0, 256, (2048, 2048, 4), dtype=np.uint8)
        image = root / "source.png"
        Image.fromarray(pixels, "RGBA").save(image)
        project = root / "project.archetexture"

        rows.extend(run_interactive_sequence("simple_512", simple_scene(512, 512), project))
        heavy = procedural_scene(512, 512)
        rows.extend(run_interactive_sequence("procedural_heavy_512", heavy, project))
        rows.extend(
            run_interactive_sequence(
                "shared_mask_512", procedural_scene(512, 512, shared_mask=True), project
            )
        )
        image_recipe = ProjectRecipe(
            width=512,
            height=512,
            layers=[
                LayerRecipe(
                    "image",
                    "Image",
                    operation("generator.image", "image-src", asset=AssetReference(str(image))),
                )
            ],
        )
        rows.extend(run_interactive_sequence("image_2048_to_512", image_recipe, project))
        image_session = RenderSession()
        image_engine = RenderEngine(session=image_session)

        def image_context():
            return RenderContext(project, image_session.asset_cache)

        rows.append(
            timed("image_repeat_cold_2048_to_512", image_engine, image_recipe, image_context)
        )
        rows.append(
            timed("image_repeat_warm_2048_to_512", image_engine, image_recipe, image_context)
        )
        rows.append({"measurement": "image_repeat_diagnostics", "stats": image_session.stats})
        Image.new("RGBA", (2048, 2048), (20, 90, 170, 255)).save(image)
        rows.append(timed("image_changed_on_disk", image_engine, image_recipe, image_context))
        rows.append({"measurement": "image_changed_diagnostics", "stats": image_session.stats})
        mixed = mixed_scene(512, 512, image)
        rows.extend(run_interactive_sequence("mixed_512", mixed, project))
        rows.append(run_burst(heavy))
    print(json.dumps(rows, indent=2))


if __name__ == "__main__":
    main()
