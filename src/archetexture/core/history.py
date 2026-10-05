from __future__ import annotations

import copy
from dataclasses import dataclass, field

from archetexture.core.recipe import ProjectRecipe


@dataclass
class HistoryManager:
    capacity: int = 64
    entries: list[ProjectRecipe] = field(default_factory=list)
    index: int = -1

    def __post_init__(self) -> None:
        if self.capacity < 1:
            raise ValueError("History capacity must be positive")

    def reset(self, recipe: ProjectRecipe) -> None:
        self.entries = [copy.deepcopy(recipe)]
        self.index = 0

    def push(self, recipe: ProjectRecipe) -> None:
        snapshot = copy.deepcopy(recipe)
        if self.entries and snapshot == self.entries[self.index]:
            return
        self.entries = self.entries[: self.index + 1]
        self.entries.append(snapshot)
        self.index = len(self.entries) - 1
        if len(self.entries) > self.capacity:
            overflow = len(self.entries) - self.capacity
            self.entries = self.entries[overflow:]
            self.index -= overflow

    def undo(self) -> ProjectRecipe | None:
        if self.index <= 0:
            return None
        self.index -= 1
        return copy.deepcopy(self.entries[self.index])

    def redo(self) -> ProjectRecipe | None:
        if self.index >= len(self.entries) - 1:
            return None
        self.index += 1
        return copy.deepcopy(self.entries[self.index])

    @property
    def can_undo(self) -> bool:
        return self.index > 0

    @property
    def can_redo(self) -> bool:
        return self.index >= 0 and self.index < len(self.entries) - 1
