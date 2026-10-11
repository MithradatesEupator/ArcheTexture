from __future__ import annotations

import copy
from dataclasses import dataclass, field

from archetexture.core.recipe import ProjectRecipe


@dataclass
class HistoryManager:
    capacity: int = 64
    entries: list[ProjectRecipe] = field(default_factory=list)
    index: int = -1
    _group_base_index: int | None = field(default=None, init=False, repr=False)
    _group_entry_index: int | None = field(default=None, init=False, repr=False)

    def __post_init__(self) -> None:
        if self.capacity < 1:
            raise ValueError("History capacity must be positive")

    def reset(self, recipe: ProjectRecipe) -> None:
        self.end_group()
        self.entries = [copy.deepcopy(recipe)]
        self.index = 0

    def push(self, recipe: ProjectRecipe) -> None:
        snapshot = copy.deepcopy(recipe)
        if self.entries and snapshot == self.entries[self.index]:
            return
        if self._group_base_index is not None and self._group_entry_index is not None:
            self.entries[self._group_entry_index] = snapshot
            self.index = self._group_entry_index
            return
        self.entries = self.entries[: self.index + 1]
        self.entries.append(snapshot)
        self.index = len(self.entries) - 1
        if self._group_base_index is not None:
            self._group_entry_index = self.index
        if len(self.entries) > self.capacity:
            overflow = len(self.entries) - self.capacity
            self.entries = self.entries[overflow:]
            self.index -= overflow
            if self._group_entry_index is not None:
                self._group_entry_index -= overflow

    def begin_group(self) -> None:
        if self._group_base_index is None:
            self._group_base_index = self.index
            self._group_entry_index = None

    def end_group(self) -> None:
        self._group_base_index = None
        self._group_entry_index = None

    def undo(self) -> ProjectRecipe | None:
        self.end_group()
        if self.index <= 0:
            return None
        self.index -= 1
        return copy.deepcopy(self.entries[self.index])

    def redo(self) -> ProjectRecipe | None:
        self.end_group()
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
