from __future__ import annotations

from dataclasses import dataclass, field

from archetexture.core.recipe import ProjectRecipe


@dataclass
class HistoryManager:
    capacity: int = 32
    entries: list[ProjectRecipe] = field(default_factory=list)
    index: int = -1

    def push(self, recipe: ProjectRecipe) -> None:
        if self.entries and recipe == self.entries[self.index]:
            return
        self.entries = self.entries[: self.index + 1]
        self.entries.append(recipe)
        self.index = len(self.entries) - 1
        if len(self.entries) > self.capacity:
            self.entries = self.entries[-self.capacity:]
            self.index = len(self.entries) - 1

    def undo(self) -> ProjectRecipe | None:
        if self.index <= 0:
            return None
        self.index -= 1
        return self.entries[self.index]

    def redo(self) -> ProjectRecipe | None:
        if self.index >= len(self.entries) - 1:
            return None
        self.index += 1
        return self.entries[self.index]
