from __future__ import annotations

from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.orm import Session, selectinload

from app.models.recipe import Recipe


class RecipeRepository:
    def __init__(self, db: Session):
        self.db = db

    def add(self, recipe: Recipe) -> Recipe:
        self.db.add(recipe)
        self.db.flush()
        self.db.refresh(recipe)
        return self.get_required(recipe.id, recipe.user_id)

    def get(self, recipe_id: UUID, user_id: UUID) -> Recipe | None:
        statement = (
            select(Recipe)
            .where(Recipe.id == recipe_id, Recipe.user_id == user_id, Recipe.deleted_at.is_(None))
            .options(
                selectinload(Recipe.ingredients),
                selectinload(Recipe.published_food_item),
            )
        )
        return self.db.scalars(statement).first()

    def get_required(self, recipe_id: UUID, user_id: UUID) -> Recipe:
        recipe = self.get(recipe_id, user_id)
        if recipe is None:
            raise LookupError("Recipe not found")
        return recipe

    def list(self, user_id: UUID, query: str | None = None) -> list[Recipe]:
        statement = (
            select(Recipe)
            .where(Recipe.user_id == user_id, Recipe.deleted_at.is_(None))
            .options(selectinload(Recipe.ingredients))
            .order_by(Recipe.name)
        )
        if query:
            pattern = f"%{query.strip()}%"
            statement = statement.where(or_(Recipe.name.ilike(pattern), Recipe.notes.ilike(pattern)))
        return list(self.db.scalars(statement).all())
