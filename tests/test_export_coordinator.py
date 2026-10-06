from pathlib import Path
from threading import Event

from archetexture.core.recipe import OperationInstance, ProjectRecipe
from archetexture.export.coordinator import ExportCoordinator


def test_export_coordinator_snapshots_recipes_and_queues_every_request(tmp_path):
    started = Event()
    release = Event()
    finished = Event()
    calls = []
    outcomes = []

    class BlockingExporter:
        def export_png(self, recipe, destination, *, width, height):
            calls.append((recipe.source.parameters["value"], width, height))
            if len(calls) == 1:
                started.set()
                assert release.wait(5)
            Path(destination).write_bytes(b"png")
            return Path(destination)

    def on_complete(outcome):
        outcomes.append(outcome)
        if len(outcomes) == 2:
            finished.set()

    coordinator = ExportCoordinator(BlockingExporter(), on_complete)
    recipe = ProjectRecipe(
        width=6,
        height=4,
        source=OperationInstance("source", "generator.constant", 1, parameters={"value": 0.2}),
    )
    first = coordinator.request(recipe, tmp_path / "one.png", width=3, height=2)
    assert started.wait(5)
    recipe.source.parameters["value"] = 0.9
    second = coordinator.request(recipe, tmp_path / "two.png", width=8, height=5)
    assert coordinator.is_running
    release.set()
    first.result(timeout=5)
    second.result(timeout=5)
    assert finished.wait(5)
    coordinator.close()

    assert calls == [(0.2, 3, 2), (0.9, 8, 5)]
    assert [outcome.error for outcome in outcomes] == [None, None]
    assert (tmp_path / "one.png").read_bytes() == b"png"
    assert (tmp_path / "two.png").read_bytes() == b"png"
