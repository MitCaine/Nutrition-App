from __future__ import annotations

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.models.recipe import Recipe
from app.models.recipe_publication import RecipePublicationRevision


class RecipePublicationRepository:
    """Append-only access to immutable Recipe publication history."""

    def __init__(self, db: Session):
        self.db = db

    def add(self, revision: RecipePublicationRevision) -> RecipePublicationRevision:
        self.db.add(revision)
        self.db.flush()
        return self.get_required(revision.id, revision.user_id)

    def get(self, revision_id: UUID, user_id: UUID) -> RecipePublicationRevision | None:
        statement = (
            select(RecipePublicationRevision)
            .where(
                RecipePublicationRevision.id == revision_id,
                RecipePublicationRevision.user_id == user_id,
            )
            .options(
                selectinload(RecipePublicationRevision.amount_definitions),
                selectinload(RecipePublicationRevision.nutrients),
            )
        )
        return self.db.scalars(statement).first()

    def get_required(self, revision_id: UUID, user_id: UUID) -> RecipePublicationRevision:
        revision = self.get(revision_id, user_id)
        if revision is None:
            raise LookupError("Recipe publication revision not found")
        return revision

    def list_for_recipe(self, recipe_id: UUID, user_id: UUID) -> list[RecipePublicationRevision]:
        statement = (
            select(RecipePublicationRevision)
            .where(
                RecipePublicationRevision.recipe_id == recipe_id,
                RecipePublicationRevision.user_id == user_id,
            )
            .options(
                selectinload(RecipePublicationRevision.amount_definitions),
                selectinload(RecipePublicationRevision.nutrients),
            )
            .order_by(RecipePublicationRevision.revision_number)
        )
        return list(self.db.scalars(statement).all())

    def next_revision_number(self, recipe_id: UUID, user_id: UUID) -> int:
        latest = self.db.scalar(
            select(func.max(RecipePublicationRevision.revision_number)).where(
                RecipePublicationRevision.recipe_id == recipe_id,
                RecipePublicationRevision.user_id == user_id,
            )
        )
        return (latest or 0) + 1

    def get_active_for_recipe(
        self, recipe_id: UUID, user_id: UUID
    ) -> RecipePublicationRevision | None:
        statement = (
            select(RecipePublicationRevision)
            .join(Recipe, Recipe.active_publication_revision_id == RecipePublicationRevision.id)
            .where(Recipe.id == recipe_id, Recipe.user_id == user_id)
            .options(
                selectinload(RecipePublicationRevision.amount_definitions),
                selectinload(RecipePublicationRevision.nutrients),
            )
        )
        return self.db.scalars(statement).first()
