from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.food import FoodItem, FoodNutrient, ServingDefinition
from app.models.recipe import Recipe, RecipeIngredient
from app.repositories.food_repository import FoodRepository
from app.schemas.food import (
    FoodCreateRequest,
    FoodDeleteAffectedRecipeResponse,
    FoodDeleteDependencyResponse,
    FoodDeleteResultResponse,
    FoodRecipeDependencyResponse,
    FoodUpdateRequest,
)


class FoodDependencyError(ValueError):
    def __init__(self, dependency: FoodDeleteDependencyResponse):
        super().__init__("Food is used by active recipes")
        self.dependency = dependency


class FoodService:
    def __init__(self, db: Session):
        self.db = db
        self.foods = FoodRepository(db)

    def create_manual_food(self, user_id: UUID, payload: FoodCreateRequest) -> FoodItem:
        food = FoodItem(
            id=uuid4(),
            user_id=user_id,
            name=payload.name.strip(),
            brand=payload.brand.strip() if payload.brand else None,
            notes=payload.notes,
            source_type="manual",
            source_id=None,
            is_recipe=False,
        )
        self._replace_servings(food, payload.serving_definitions)
        self._replace_nutrients(food, payload.nutrients)
        created = self.foods.add(food)
        self.db.commit()
        return created

    def list_foods(self, user_id: UUID, query: str | None = None) -> list[FoodItem]:
        return self.foods.list(user_id, query)

    def get_food(self, user_id: UUID, food_id: UUID) -> FoodItem:
        return self.foods.get_required(food_id, user_id)

    def update_food(self, user_id: UUID, food_id: UUID, payload: FoodUpdateRequest) -> FoodItem:
        food = self.foods.get_required(food_id, user_id)
        if payload.name is not None:
            food.name = payload.name.strip()
        if payload.brand is not None:
            food.brand = payload.brand.strip() if payload.brand else None
        if payload.notes is not None:
            food.notes = payload.notes
        if payload.serving_definitions is not None:
            food.serving_definitions.clear()
            self._replace_servings(food, payload.serving_definitions)
        if payload.nutrients is not None:
            food.nutrients.clear()
            self._replace_nutrients(food, payload.nutrients)
        food.updated_at = datetime.now(timezone.utc)
        self.db.commit()
        return self.foods.get_required(food_id, user_id)

    def soft_delete_food(
        self,
        user_id: UUID,
        food_id: UUID,
        *,
        remove_from_recipes: bool = False,
    ) -> FoodDeleteResultResponse:
        food = self.foods.get_required(food_id, user_id)
        dependencies = self._food_recipe_dependencies(user_id, food_id)
        if dependencies.affected_recipes and not remove_from_recipes:
            raise FoodDependencyError(dependencies)

        now = datetime.now(timezone.utc)
        affected_recipes: list[FoodDeleteAffectedRecipeResponse] = []
        try:
            if remove_from_recipes and dependencies.affected_recipes:
                affected_recipes = self._remove_food_from_recipes(user_id, food_id, now)

            food.deleted_at = now
            food.updated_at = now
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise

        return FoodDeleteResultResponse(
            food_id=food_id,
            deleted=True,
            removed_ingredient_count=sum(recipe.removed_ingredient_count for recipe in affected_recipes),
            affected_recipes=affected_recipes,
        )

    def duplicate_food(self, user_id: UUID, food_id: UUID) -> FoodItem:
        source = self.foods.get_required(food_id, user_id)
        duplicate = FoodItem(
            id=uuid4(),
            user_id=user_id,
            name=f"{source.name} Copy",
            brand=source.brand,
            notes=source.notes,
            source_type="manual",
            source_id=str(source.id),
            is_recipe=False,
        )
        for serving in source.serving_definitions:
            duplicate.serving_definitions.append(
                ServingDefinition(
                    id=uuid4(),
                    label=serving.label,
                    quantity=serving.quantity,
                    unit=serving.unit,
                    gram_weight=serving.gram_weight,
                    is_default=serving.is_default,
                    source="manual",
                    is_user_confirmed=True,
                )
            )
        for nutrient in source.nutrients:
            duplicate.nutrients.append(
                FoodNutrient(
                    id=uuid4(),
                    nutrient_id=nutrient.nutrient_id,
                    amount=nutrient.amount,
                    unit=nutrient.unit,
                    basis=nutrient.basis,
                    data_status=nutrient.data_status,
                    source="manual",
                    is_user_confirmed=True,
                    original_amount=nutrient.original_amount,
                    original_unit=nutrient.original_unit,
                    original_text=nutrient.original_text,
                )
            )
        created = self.foods.add(duplicate)
        self.db.commit()
        return created

    def _food_recipe_dependencies(self, user_id: UUID, food_id: UUID) -> FoodDeleteDependencyResponse:
        statement = (
            select(
                Recipe.id,
                Recipe.name,
                Recipe.published_food_item_id,
                Recipe.needs_republish,
                func.count(RecipeIngredient.id),
            )
            .join(RecipeIngredient, RecipeIngredient.recipe_id == Recipe.id)
            .where(
                Recipe.user_id == user_id,
                Recipe.deleted_at.is_(None),
                RecipeIngredient.food_item_id == food_id,
            )
            .group_by(Recipe.id, Recipe.name, Recipe.published_food_item_id, Recipe.needs_republish)
            .order_by(Recipe.name)
        )
        affected_recipes = [
            FoodRecipeDependencyResponse(
                recipe_id=recipe_id,
                recipe_name=recipe_name,
                ingredient_occurrence_count=occurrence_count,
                is_published=published_food_item_id is not None,
                needs_republish=needs_republish,
            )
            for recipe_id, recipe_name, published_food_item_id, needs_republish, occurrence_count in self.db.execute(statement)
        ]
        return FoodDeleteDependencyResponse(
            food_id=food_id,
            active_recipe_count=len(affected_recipes),
            affected_recipes=affected_recipes,
            total_ingredient_rows_affected=sum(recipe.ingredient_occurrence_count for recipe in affected_recipes),
        )

    def _remove_food_from_recipes(
        self,
        user_id: UUID,
        food_id: UUID,
        now: datetime,
    ) -> list[FoodDeleteAffectedRecipeResponse]:
        statement = (
            select(Recipe)
            .join(RecipeIngredient, RecipeIngredient.recipe_id == Recipe.id)
            .where(
                Recipe.user_id == user_id,
                Recipe.deleted_at.is_(None),
                RecipeIngredient.food_item_id == food_id,
            )
            .order_by(Recipe.name)
            .distinct()
        )
        recipes = list(self.db.scalars(statement).unique().all())
        affected_recipes: list[FoodDeleteAffectedRecipeResponse] = []
        for recipe in recipes:
            removed_count = sum(1 for ingredient in recipe.ingredients if ingredient.food_item_id == food_id)
            if removed_count == 0:
                continue
            remaining = [ingredient for ingredient in recipe.ingredients if ingredient.food_item_id != food_id]
            recipe.ingredients[:] = remaining
            for offset, ingredient in enumerate(recipe.ingredients):
                ingredient.position = 100_000 + offset
            recipe.updated_at = now
            if recipe.published_food_item_id is not None:
                recipe.needs_republish = True
            affected_recipes.append(
                FoodDeleteAffectedRecipeResponse(
                    recipe_id=recipe.id,
                    recipe_name=recipe.name,
                    removed_ingredient_count=removed_count,
                    needs_republish=recipe.needs_republish,
                )
            )
        self.db.flush()
        for recipe in recipes:
            for position, ingredient in enumerate(recipe.ingredients):
                ingredient.position = position
        self.db.flush()
        return affected_recipes

    def _replace_servings(self, food: FoodItem, servings) -> None:
        for serving in servings:
            food.serving_definitions.append(
                ServingDefinition(
                    id=uuid4(),
                    label=serving.label.strip(),
                    quantity=serving.quantity,
                    unit=serving.unit,
                    gram_weight=serving.gram_weight,
                    is_default=serving.is_default,
                    source="manual",
                    is_user_confirmed=True,
                )
            )

    def _replace_nutrients(self, food: FoodItem, nutrients) -> None:
        for nutrient in nutrients:
            original = nutrient.original
            food.nutrients.append(
                FoodNutrient(
                    id=uuid4(),
                    nutrient_id=nutrient.nutrient_id,
                    amount=nutrient.amount,
                    unit=nutrient.unit,
                    basis=nutrient.basis.value,
                    data_status=nutrient.data_status.value,
                    source="manual",
                    is_user_confirmed=True,
                    original_amount=original.amount if original else None,
                    original_unit=original.unit if original else None,
                    original_text=original.text if original else None,
                )
            )
