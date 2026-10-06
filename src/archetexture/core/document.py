from __future__ import annotations

import copy
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from archetexture.core.defaults import default_recipe
from archetexture.core.history import HistoryManager
from archetexture.core.recipe import ProjectRecipe
from archetexture.core.serialization import load_project, save_project
from archetexture.core.validation import ensure_valid_recipe


@dataclass(frozen=True)
class PreparedProject:
    """A fully decoded project with replacement document state ready to install."""

    recipe: ProjectRecipe
    saved_recipe: ProjectRecipe
    history: HistoryManager
    path: str


class DocumentController:
    """Owns the canonical recipe, its history, file path, and save point."""

    def __init__(self, recipe: ProjectRecipe | None = None):
        initial = copy.deepcopy(recipe) if recipe is not None else default_recipe()
        ensure_valid_recipe(initial)
        self._recipe = initial
        self.project_path: str | None = None
        self.history = HistoryManager()
        self.history.reset(initial)
        self._saved_recipe = copy.deepcopy(initial)

    @property
    def recipe(self) -> ProjectRecipe:
        return copy.deepcopy(self._recipe)

    @property
    def dirty(self) -> bool:
        return self._recipe != self._saved_recipe

    @property
    def can_undo(self) -> bool:
        return self.history.can_undo

    @property
    def can_redo(self) -> bool:
        return self.history.can_redo

    def commit(self, recipe: ProjectRecipe) -> ProjectRecipe:
        ensure_valid_recipe(recipe)
        snapshot = copy.deepcopy(recipe)
        if snapshot == self._recipe:
            return self.recipe
        self.history.push(snapshot)
        self._recipe = snapshot
        return self.recipe

    def edit(self, edit: Callable[[ProjectRecipe], None]) -> ProjectRecipe:
        updated = self.recipe
        edit(updated)
        return self.commit(updated)

    def undo(self) -> ProjectRecipe:
        previous = self.history.undo()
        if previous is not None:
            self._recipe = previous
        return self.recipe

    def redo(self) -> ProjectRecipe:
        following = self.history.redo()
        if following is not None:
            self._recipe = following
        return self.recipe

    def new_document(self, recipe: ProjectRecipe | None = None) -> ProjectRecipe:
        new_recipe = copy.deepcopy(recipe) if recipe is not None else default_recipe()
        ensure_valid_recipe(new_recipe)
        self._recipe = new_recipe
        self.project_path = None
        self.history.reset(new_recipe)
        self._saved_recipe = copy.deepcopy(new_recipe)
        return self.recipe

    def prepare_project(self, path: str | Path) -> PreparedProject:
        loaded = load_project(path)
        ensure_valid_recipe(loaded)
        candidate_recipe = copy.deepcopy(loaded)
        candidate_saved_recipe = copy.deepcopy(candidate_recipe)
        candidate_history = HistoryManager(capacity=self.history.capacity)
        candidate_history.reset(candidate_recipe)
        return PreparedProject(
            recipe=candidate_recipe,
            saved_recipe=candidate_saved_recipe,
            history=candidate_history,
            path=str(Path(path)),
        )

    def replace_with_project(self, candidate: PreparedProject) -> ProjectRecipe:
        if not isinstance(candidate, PreparedProject):
            raise TypeError("candidate must be a PreparedProject")
        result = copy.deepcopy(candidate.recipe)
        self._recipe, self._saved_recipe, self.history, self.project_path = (
            candidate.recipe,
            candidate.saved_recipe,
            candidate.history,
            candidate.path,
        )
        return result

    def open_project(self, path: str | Path) -> ProjectRecipe:
        return self.replace_with_project(self.prepare_project(path))

    def save(self, path: str | Path | None = None) -> str:
        destination = (
            Path(path)
            if path is not None
            else (Path(self.project_path) if self.project_path is not None else None)
        )
        if destination is None:
            raise ValueError("Save As requires a project path")
        save_project(self._recipe, destination)
        self.project_path = str(destination)
        self._saved_recipe = copy.deepcopy(self._recipe)
        return self.project_path
