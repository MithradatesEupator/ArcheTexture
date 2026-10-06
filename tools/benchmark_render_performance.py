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
from archetexture.core.parameters import ControlFieldBinding, ControlFieldMapping
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


def _stats_snapshot(session: RenderSession) -> dict:
    return session.stats


def _stats_delta(before: dict, after: dict) -> dict:
    return {
        "layer_cache_hits": after["layers"]["hits"] - before["layers"]["hits"],
        "layer_cache_misses": after["layers"]["misses"] - before["layers"]["misses"],
        "control_cache_hits": after["controls"]["hits"] - before["controls"]["hits"],
        "control_cache_misses": after["controls"]["misses"] - before["controls"]["misses"],
        "operation_executions": after["operation_executions"] - before["operation_executions"],
    }


def _measure_edit(label: str, engine: RenderEngine, recipe: ProjectRecipe, project: Path) -> dict:
    before = _stats_snapshot(engine.session)
    result = timed(
        label, engine, recipe, lambda: RenderContext(project, engine.session.asset_cache)
    )
    result.update(_stats_delta(before, _stats_snapshot(engine.session)))
    return result


def run_dependency_scenarios(project_path: Path) -> list[dict]:
    rows = []

    mask_only = procedural_scene(512, 512, shared_mask=True)
    mask_session = RenderSession()
    mask_engine = RenderEngine(session=mask_session)
    rows.append(_measure_edit("dependency.mask_only.cold", mask_engine, mask_only, project_path))
    rows.append(
        _measure_edit("dependency.mask_only.warm_identical", mask_engine, mask_only, project_path)
    )

    mask_edit = copy.deepcopy(mask_only)
    mask_edit.control_fields["shared"].source.parameters["scale"] += 0.25
    rows.append(
        _measure_edit("dependency.mask_only.control_edit", mask_engine, mask_edit, project_path)
    )
    mask_mapping_edit = copy.deepcopy(mask_edit)
    mask_mapping_edit.layers[0].mask = ControlFieldBinding(
        "shared", ControlFieldMapping(invert=True)
    )
    rows.append(
        _measure_edit(
            "dependency.mask_only.mapping_edit", mask_engine, mask_mapping_edit, project_path
        )
    )
    opacity_edit = copy.deepcopy(mask_mapping_edit)
    opacity_edit.layers[0].opacity = 0.6
    rows.append(
        _measure_edit("dependency.mask_only.opacity_edit", mask_engine, opacity_edit, project_path)
    )
    rows.append({"measurement": "dependency.mask_only.stats", "stats": mask_session.stats})

    modulated = procedural_scene(512, 512)
    modulated.control_fields["modulation"] = ControlFieldRecipe(
        operation("generator.fractal_noise", "modulation-source", scale=2.5, octaves=5),
        [operation("transform.blur", "modulation-blur", sigma=0.8)],
    )
    modulated.layers[0].source.parameters["scale"] = ControlFieldBinding(
        "modulation", ControlFieldMapping(output_min=3.0, output_max=5.0)
    )
    mod_session = RenderSession()
    mod_engine = RenderEngine(session=mod_session)
    rows.append(_measure_edit("dependency.modulated.cold", mod_engine, modulated, project_path))
    rows.append(
        _measure_edit("dependency.modulated.warm_identical", mod_engine, modulated, project_path)
    )
    mod_edit = copy.deepcopy(modulated)
    mod_edit.control_fields["modulation"].source.parameters["scale"] += 0.25
    rows.append(
        _measure_edit("dependency.modulated.control_edit", mod_engine, mod_edit, project_path)
    )
    rows.append({"measurement": "dependency.modulated.stats", "stats": mod_session.stats})

    unrelated = procedural_scene(512, 512, shared_mask=True)
    unrelated.control_fields["unused"] = ControlFieldRecipe(
        operation("generator.fractal_noise", "unused-source", scale=1.7)
    )
    unrelated_session = RenderSession()
    unrelated_engine = RenderEngine(session=unrelated_session)
    rows.append(
        _measure_edit("dependency.unrelated.cold", unrelated_engine, unrelated, project_path)
    )
    rows.append(
        _measure_edit(
            "dependency.unrelated.warm_identical", unrelated_engine, unrelated, project_path
        )
    )
    unrelated_edit = copy.deepcopy(unrelated)
    unrelated_edit.control_fields["unused"].source.parameters["scale"] += 0.25
    rows.append(
        _measure_edit(
            "dependency.unrelated.control_edit", unrelated_engine, unrelated_edit, project_path
        )
    )
    rows.append({"measurement": "dependency.unrelated.stats", "stats": unrelated_session.stats})
    return rows


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
        rows.extend(run_dependency_scenarios(project))
    print(json.dumps(rows, indent=2))


if __name__ == "__main__":
    main()
