from __future__ import annotations

import copy
import logging
import threading
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Callable

from archetexture.core.assets import RenderContext
from archetexture.core.cancellation import RenderCancelled
from archetexture.core.recipe import ProjectRecipe
from archetexture.render.engine import RenderEngine, RenderResult
from archetexture.render.request import RenderRequest

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RenderOutcome:
    request_id: int
    result: RenderResult | None = None
    error: Exception | None = None


@dataclass
class RenderCoordinator:
    engine: RenderEngine = field(default_factory=RenderEngine)
    on_complete: Callable[[RenderOutcome], None] | None = None
    request_counter: int = 0
    active_request: RenderRequest | None = None
    pending_request: RenderRequest | None = None
    _latest_request_id: int = 0
    _callbacks: dict[int, Callable[[RenderOutcome], None]] = field(default_factory=dict)
    _lock: threading.RLock = field(default_factory=threading.RLock, repr=False)
    _closed: bool = False
    _executor: ThreadPoolExecutor = field(
        default_factory=lambda: ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="archetexture-render"
        ),
        repr=False,
    )

    def request(
        self,
        recipe: ProjectRecipe,
        *,
        width: int,
        height: int,
        callback: Callable[[RenderOutcome], None] | None = None,
        render_context: RenderContext | None = None,
        output_id: str | None = None,
    ) -> RenderRequest:
        for name, dimension in (("width", width), ("height", height)):
            if not isinstance(dimension, int) or isinstance(dimension, bool) or dimension <= 0:
                raise ValueError(f"Render {name} must be a positive integer")
        snapshot = copy.deepcopy(recipe)
        with self._lock:
            if self._closed:
                raise RuntimeError("Render coordinator is closed")
            self.request_counter += 1
            request = RenderRequest(self.request_counter, snapshot, width, height, render_context, output_id)
            self._latest_request_id = request.request_id
            if callback is not None:
                self._callbacks[request.request_id] = callback
            if self.active_request is None:
                self.active_request = request
                launch = request
            else:
                self.active_request.cancellation_token.cancel()
                if self.pending_request is not None:
                    self._callbacks.pop(self.pending_request.request_id, None)
                    self.pending_request.cancellation_token.cancel()
                self.pending_request = request
                launch = None
        if launch is not None:
            self._launch(launch)
        return request

    def _launch(self, request: RenderRequest) -> None:
        kwargs = {"width": request.width, "height": request.height}
        context = request.render_context or RenderContext()
        if hasattr(self.engine, "session"):
            context = context.with_runtime(
                self.engine.session.asset_cache, request.cancellation_token
            )
            kwargs["render_context"] = context
        else:
            if request.render_context is not None:
                context = RenderContext(
                    context.project_path,
                    context.asset_cache,
                    request.cancellation_token,
                )
                kwargs["render_context"] = context
        if request.output_id is None:
            future = self._executor.submit(self.engine.render, request.recipe, **kwargs)
        else:
            future = self._executor.submit(
                self.engine.render_output, request.recipe, request.output_id, **kwargs
            )
        future.add_done_callback(lambda completed: self._finished(request, completed))

    def _finished(self, request: RenderRequest, future: Future[RenderResult]) -> None:
        try:
            outcome = RenderOutcome(request.request_id, result=future.result())
        except RenderCancelled:
            outcome = None
        except Exception as exc:  # Errors are delivered through the same UI-safe result path.
            outcome = RenderOutcome(request.request_id, error=exc)

        with self._lock:
            if self._closed:
                return
            is_latest = request.request_id == self._latest_request_id
            callback = self._callbacks.pop(request.request_id, None) if is_latest else None
            self.active_request = None
            next_request = self.pending_request
            self.pending_request = None
            if next_request is not None:
                self.active_request = next_request

        if is_latest and outcome is not None:
            receiver = callback or self.on_complete
            if receiver is not None:
                try:
                    receiver(outcome)
                except Exception:
                    logger.exception("Render completion callback failed")
        if next_request is not None:
            self._launch(next_request)

    def close(self, *, wait: bool = True) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            if self.active_request is not None:
                self.active_request.cancellation_token.cancel()
            if self.pending_request is not None:
                self.pending_request.cancellation_token.cancel()
            self.pending_request = None
            self._callbacks.clear()
        self._executor.shutdown(wait=wait, cancel_futures=True)

    @property
    def latest_request_id(self) -> int:
        with self._lock:
            return self._latest_request_id

    @property
    def is_running(self) -> bool:
        with self._lock:
            return self.active_request is not None
