from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from threading import Lock
from typing import Callable

from archetexture.core.assets import RenderContext
from archetexture.core.recipe import ProjectRecipe
from archetexture.export.image_export import ImageExporter, validate_export_dimension


@dataclass(frozen=True)
class ExportOutcome:
    destination: Path
    width: int
    height: int
    error: Exception | None = None


class ExportCoordinator:
    """Dedicated, non-coalescing queue for user-requested file exports."""

    def __init__(
        self,
        exporter: ImageExporter | None = None,
        on_complete: Callable[[ExportOutcome], None] | None = None,
    ):
        self.exporter = exporter or ImageExporter()
        self.on_complete = on_complete
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="archetexture-export")
        self._lock = Lock()
        self._closed = False
        self._active = 0

    @property
    def is_running(self) -> bool:
        with self._lock:
            return self._active > 0

    def request(
        self,
        recipe: ProjectRecipe,
        destination: str | Path,
        *,
        width: int,
        height: int,
        render_context: RenderContext | None = None,
    ) -> Future:
        snapshot = deepcopy(recipe)
        width = validate_export_dimension(width, "Width")
        height = validate_export_dimension(height, "Height")
        path = Path(destination)
        with self._lock:
            if self._closed:
                raise RuntimeError("Export coordinator is closed")
            self._active += 1
        kwargs = {"width": width, "height": height}
        if render_context is not None:
            kwargs["render_context"] = render_context
        future = self._executor.submit(self.exporter.export_png, snapshot, path, **kwargs)
        future.add_done_callback(lambda done: self._finished(done, path, width, height))
        return future

    def _finished(self, future: Future, path: Path, width: int, height: int) -> None:
        try:
            future.result()
            outcome = ExportOutcome(path, width, height)
        except Exception as exc:
            outcome = ExportOutcome(path, width, height, exc)
        finally:
            with self._lock:
                self._active -= 1
        if self.on_complete is not None:
            self.on_complete(outcome)

    def close(self, *, wait: bool = True) -> None:
        with self._lock:
            self._closed = True
        self._executor.shutdown(wait=wait, cancel_futures=False)
