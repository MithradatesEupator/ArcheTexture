from __future__ import annotations

from archetexture.core.history import HistoryManager
from archetexture.core.recipe import ProjectRecipe
from archetexture.core.validation import ValidationError


class DocumentController:
    def __init__(self, recipe: ProjectRecipe | None = None):
        self.recipe = recipe or ProjectRecipe()
        self.project_path: str | None = None
        self.dirty = False
        self.history = HistoryManager()
        self.history.push(self.recipe)

    def replace_recipe(self, new_recipe: ProjectRecipe) -> ProjectRecipe:
        if not isinstance(new_recipe, ProjectRecipe):
            raise ValidationError([])
        self.recipe = new_recipe
        self.dirty = True
        self.history.push(new_recipe)
        return new_recipe

    def undo(self) -> ProjectRecipe:
        recipe = self.history.undo()
        if recipe is None:
            return self.recipe
        self.recipe = recipe
        self.dirty = True
        return recipe

    def redo(self) -> ProjectRecipe:
        recipe = self.history.redo()
        if recipe is None:
            return self.recipe
        self.recipe = recipe
        self.dirty = True
        return recipe
