from __future__ import annotations

from dataclasses import dataclass, field
from threading import Event


class RenderCancelled(Exception):
    """Raised at a cooperative render checkpoint after a request becomes stale."""


@dataclass
class CancellationToken:
    _event: Event = field(default_factory=Event, repr=False)

    def cancel(self) -> None:
        self._event.set()

    @property
    def cancelled(self) -> bool:
        return self._event.is_set()

    def check(self) -> None:
        if self.cancelled:
            raise RenderCancelled("Render request was superseded")
