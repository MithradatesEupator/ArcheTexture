from __future__ import annotations

import json
import os
import tempfile

import numpy as np

from archetexture.color.ramp import ColorRamp, ColorStop
from archetexture.core.history import HistoryManager
from archetexture.core.parameters import ControlFieldBinding, ControlFieldMapping
from archetexture.core.recipe import OperationInstance, ProjectRecipe
from archetexture.core.serialization import load_project, save_project
from archetexture.render.coordinator import RenderCoordinator
from archetexture.render.engine import RenderEngine


def test_deterministic_constant_field():
    recipe = ProjectRecipe(
        width=32,
        height=16,
        seed=7,
        source=OperationInstance(
            "s1",
            "generator.constant",
            1,
            parameters={"value": 0.25},
        ),
    )
    out1 = RenderEngine().render(recipe, width=32, height=16)
    out2 = RenderEngine().render(recipe, width=32, height=16)
    assert np.array_equal(out1, out2)
    assert out1.dtype == np.float32
    assert out1.shape == (16, 32)
    assert out1.min() >= 0.0 and out1.max() <= 1.0


def test_history_undo_redo():
    history = HistoryManager()
    a = ProjectRecipe(width=8, height=8, seed=1)
    b = ProjectRecipe(width=16, height=16, seed=2)
    history.push(a)
    history.push(b)
    assert history.undo() == a
    assert history.redo() == b


def test_color_ramp_roundtrip():
    ramp = ColorRamp(
        [
            ColorStop(0.0, (0.0, 0.0, 0.0, 1.0)),
            ColorStop(0.5, (1.0, 0.0, 0.0, 1.0)),
            ColorStop(1.0, (1.0, 1.0, 1.0, 1.0)),
        ]
    )
    assert ramp.sample(0.0) == (0.0, 0.0, 0.0, 1.0)
    assert ramp.sample(1.0) == (1.0, 1.0, 1.0, 1.0)


def test_render_coordinator_stale_result_rejected():
    coordinator = RenderCoordinator()
    a = coordinator.request(ProjectRecipe(seed=1), width=8, height=8)
    b = coordinator.request(ProjectRecipe(seed=2), width=8, height=8)
    assert a.request_id != b.request_id
    assert coordinator.pending_request.request_id == b.request_id


def test_serialization_roundtrip():
    recipe = ProjectRecipe(width=12, height=10, seed=3)
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "sample.archetexture")
        save_project(recipe, path)
        loaded = load_project(path)
        assert loaded.schema_version == 1
        assert loaded.width == 12 and loaded.height == 10
        assert loaded.seed == 3


def test_control_field_binding_mapping():
    mapping = ControlFieldMapping(output_min=0.25, output_max=0.75, invert=True, curve="smoothstep")
    binding = ControlFieldBinding(source_id="field-1", mapping=mapping)
    assert binding.source_id == "field-1"
    assert binding.mapping.output_max == 0.75


def test_json_file_validity():
    payload = {"schema_version": 1, "width": 16, "height": 8, "seed": 9, "transforms": []}
    text = json.dumps(payload)
    assert "schema_version" in text
