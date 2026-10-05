from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Any

from archetexture.core.recipe import ProjectRecipe
from archetexture.render.engine import RenderEngine
from archetexture.render.request import RenderRequest


@dataclass
class RenderCoordinator:
    engine: RenderEngine = field(default_factory=RenderEngine)
    active_request: RenderRequest | None = None
    pending_request: RenderRequest | None = None
    request_counter: int = 0
    lock: threading.Lock = field(default_factory=threading.Lock)

    def request(self, recipe: ProjectRecipe, *, width: int, height: int) -> RenderRequest:
        with self.lock:
            self.request_counter += 1
            req = RenderRequest(self.request_counter, recipe, width, height)
            self.pending_request = req
            return req

    def flush(self) -> Any:
        with self.lock:
            target = self.pending_request or self.active_request
            if target is None:
                return None
            self.active_request = target
            self.pending_request = None
        result = self.engine.render(target.recipe, width=target.width, height=target.height)
        with self.lock:
            if self.active_request and self.active_request.request_id != target.request_id:
                return None
            self.active_request = None
            return result
