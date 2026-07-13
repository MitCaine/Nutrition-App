from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy.orm import Session

from app.catalog.nutrients import NUTRIENT_CATALOG
from app.domain.nutrition import AggregatedNutrientTotal, NutrientBasis, NutrientDataStatus, NutrientSnapshot
from app.models.food import FoodItem, FoodNutrient, ServingDefinition
from app.models.recipe import Recipe, RecipeIngredient
from app.nutrition.aggregation import aggregate_snapshots
from app.nutrition.resolution import resolve_amount, resolve_nutrition
from app.repositories.food_repository import FoodRepository
from app.repositories.recipe_repository import RecipeRepository
from app.schemas.recipe import (
    RecipeCreateRequest,
    RecipeIngredientInput,
    RecipeUpdateRequest,
    _validate_display_metadata,
)

UNITS_BY_NUTRIENT_ID = {nutrient.id: nutrient.default_unit for nutrient in NUTRIENT_CATALOG}
DECIMAL_PLACES = Decimal("0.000001")


class RecipeService:
    def __init__(self, db: Session):
        self.db = db
        self.foods = FoodRepository(db)
        self.recipes = RecipeRepository(db)

    def create_recipe(self, user_id: UUID, payload: RecipeCreateRequest) -> Recipe:
        recipe = Recipe(
            id=uuid4(),
            user_id=user_id,
            name=payload.name.strip(),
            notes=payload.notes,
            serving_count_yield=payload.serving_count_yield,
            final_cooked_weight_grams=payload.final_cooked_weight_grams,
            final_cooked_weight_display_quantity=payload.final_cooked_weight_display_quantity,
            final_cooked_weight_display_unit=payload.final_cooked_weight_display_unit,
        )
        self._replace_ingredients(user_id, recipe, payload.ingredients)
        created = self.recipes.add(recipe)
        self.db.commit()
        return created

    def list_recipes(self, user_id: UUID, query: str | None = None) -> list[Recipe]:
        return self.recipes.list(user_id, query)

    def get_recipe(self, user_id: UUID, recipe_id: UUID) -> Recipe:
        return self.recipes.get_required(recipe_id, user_id)

    def update_recipe(self, user_id: UUID, recipe_id: UUID, payload: RecipeUpdateRequest) -> Recipe:
        recipe = self.recipes.get_required(recipe_id, user_id)
        fields = payload.model_fields_set
        if payload.name is not None:
            recipe.name = payload.name.strip()
        if "notes" in fields:
            recipe.notes = payload.notes
        if "serving_count_yield" in fields:
            recipe.serving_count_yield = payload.serving_count_yield
        self._apply_final_cooked_weight_update(recipe, payload)
        if payload.ingredients is not None:
            ingredients = self._build_ingredients(user_id, recipe, payload.ingredients)
            recipe.ingredients.clear()
            self.db.flush()
            recipe.ingredients.extend(ingredients)
        if recipe.published_food_item_id is not None and fields:
            recipe.needs_republish = True
        recipe.updated_at = datetime.now(timezone.utc)
        self.db.commit()
        return self.recipes.get_required(recipe_id, user_id)

    def _apply_final_cooked_weight_update(self, recipe: Recipe, payload: RecipeUpdateRequest) -> None:
        fields = payload.model_fields_set
        grams_supplied = "final_cooked_weight_grams" in fields
        display_supplied = bool(
            {
                "final_cooked_weight_display_quantity",
                "final_cooked_weight_display_unit",
            }.intersection(fields)
        )

        if grams_supplied:
            recipe.final_cooked_weight_grams = payload.final_cooked_weight_grams
            if payload.final_cooked_weight_grams is None:
                recipe.final_cooked_weight_display_quantity = None
                recipe.final_cooked_weight_display_unit = None
                return
            if not display_supplied:
                recipe.final_cooked_weight_display_quantity = None
                recipe.final_cooked_weight_display_unit = None
                return

        if display_supplied:
            normalized_grams = (
                payload.final_cooked_weight_grams
                if grams_supplied
                else recipe.final_cooked_weight_grams
            )
            quantity, unit = _validate_display_metadata(
                quantity=payload.final_cooked_weight_display_quantity,
                unit=payload.final_cooked_weight_display_unit,
                normalized_grams=normalized_grams,
                field_name="final cooked weight",
            )
            recipe.final_cooked_weight_display_quantity = quantity
            recipe.final_cooked_weight_display_unit = unit

    def soft_delete_recipe(self, user_id: UUID, recipe_id: UUID) -> None:
        recipe = self.recipes.get_required(recipe_id, user_id)
        now = datetime.now(timezone.utc)
        recipe.deleted_at = now
        recipe.updated_at = now
        if recipe.published_food_item is not None:
            recipe.published_food_item.deleted_at = now
            recipe.published_food_item.updated_at = now
        self.db.commit()

    def nutrition(self, user_id: UUID, recipe_id: UUID) -> dict[str, list[AggregatedNutrientTotal] | None]:
        recipe = self.recipes.get_required(recipe_id, user_id)
        totals = self._calculate_totals(recipe)
        return {
            "totals": totals,
            "per_serving": self._divide_totals(totals, recipe.serving_count_yield),
            "per_100g": self._divide_totals(
                totals,
                recipe.final_cooked_weight_grams / Decimal("100") if recipe.final_cooked_weight_grams else None,
            ),
        }

    def publish(self, user_id: UUID, recipe_id: UUID) -> tuple[Recipe, FoodItem]:
        recipe = self.recipes.get_required(recipe_id, user_id)
        if not recipe.serving_count_yield and not recipe.final_cooked_weight_grams:
            raise ValueError("Publishing requires serving_count_yield or final_cooked_weight_grams")

        totals = self._calculate_totals(recipe)
        per_serving = self._divide_totals(totals, recipe.serving_count_yield)
        per_100g = self._divide_totals(
            totals,
            recipe.final_cooked_weight_grams / Decimal("100") if recipe.final_cooked_weight_grams else None,
        )

        food = recipe.published_food_item
        if food is None:
            food = FoodItem(
                id=uuid4(),
                user_id=user_id,
                name=recipe.name,
                brand=None,
                notes=recipe.notes,
                source_type="recipe",
                source_id=str(recipe.id),
                is_recipe=True,
            )
            self.db.add(food)
            recipe.published_food_item = food
        food.name = recipe.name
        food.notes = recipe.notes
        food.is_recipe = True
        food.source_type = "recipe"
        food.source_id = str(recipe.id)
        food.updated_at = datetime.now(timezone.utc)
        food.serving_definitions.clear()
        food.nutrients.clear()
        self.db.flush()

        if recipe.serving_count_yield:
            food.serving_definitions.append(
                ServingDefinition(
                    id=uuid4(),
                    label="1 serving",
                    quantity=Decimal("1"),
                    unit="serving",
                    gram_weight=(
                        recipe.final_cooked_weight_grams / recipe.serving_count_yield
                        if recipe.final_cooked_weight_grams
                        else None
                    ),
                    is_default=True,
                    source="recipe",
                    is_user_confirmed=True,
                )
            )
            self._append_food_nutrients(food, per_serving or [], NutrientBasis.PER_SERVING)
        if recipe.final_cooked_weight_grams:
            food.serving_definitions.append(
                ServingDefinition(
                    id=uuid4(),
                    label="100 g",
                    quantity=Decimal("100"),
                    unit="g",
                    gram_weight=Decimal("100"),
                    is_default=not bool(recipe.serving_count_yield),
                    source="recipe",
                    is_user_confirmed=True,
                )
            )
            self._append_food_nutrients(food, per_100g or [], NutrientBasis.PER_100G)

        recipe.needs_republish = False
        recipe.updated_at = datetime.now(timezone.utc)
        self.db.commit()
        return self.recipes.get_required(recipe_id, user_id), self.foods.get_required(food.id, user_id)

    def _replace_ingredients(self, user_id: UUID, recipe: Recipe, ingredients: list[RecipeIngredientInput]) -> None:
        recipe.ingredients.extend(self._build_ingredients(user_id, recipe, ingredients))

    def _build_ingredients(
        self,
        user_id: UUID,
        recipe: Recipe,
        ingredients: list[RecipeIngredientInput],
    ) -> list[RecipeIngredient]:
        positions = [ingredient.position for ingredient in ingredients]
        if len(positions) != len(set(positions)):
            raise ValueError("ingredient positions must be unique")
        built: list[RecipeIngredient] = []
        for ingredient in sorted(ingredients, key=lambda item: item.position):
            food = self.foods.get_required(ingredient.food_item_id, user_id)
            self._validate_no_recipe_cycle(user_id, recipe, food)
            resolved = resolve_amount(
                food,
                ingredient.amount_quantity,
                ingredient.amount_unit,
                ingredient.serving_definition_id,
            )
            built.append(
                RecipeIngredient(
                    id=uuid4(),
                    food_item_id=food.id,
                    position=ingredient.position,
                    amount_quantity=ingredient.amount_quantity,
                    amount_unit=ingredient.amount_unit,
                    amount_display_quantity=ingredient.amount_display_quantity,
                    amount_display_unit=ingredient.amount_display_unit,
                    serving_definition_id=resolved.serving_definition.id if resolved.serving_definition else None,
                    resolved_gram_amount=resolved.gram_amount,
                    preparation_note=ingredient.preparation_note,
                )
            )
        return built

    def _validate_no_recipe_cycle(self, user_id: UUID, recipe: Recipe, food: FoodItem) -> None:
        if recipe.published_food_item_id is not None and food.id == recipe.published_food_item_id:
            raise ValueError("Recipe cannot include its own published food")
        if food.source_type != "recipe" or food.source_id is None:
            return
        try:
            ingredient_recipe_id = UUID(food.source_id)
        except ValueError as exc:
            raise ValueError("Ingredient recipe food has invalid source identity") from exc
        if ingredient_recipe_id == recipe.id:
            raise ValueError("Recipe cannot include its own published food")
        if self._recipe_references_recipe(user_id, ingredient_recipe_id, recipe.id, set()):
            raise ValueError("Recipe ingredient would create a recipe cycle")

    def _recipe_references_recipe(
        self,
        user_id: UUID,
        recipe_id: UUID,
        target_recipe_id: UUID,
        seen: set[UUID],
    ) -> bool:
        if recipe_id in seen:
            return False
        seen.add(recipe_id)
        recipe = self.recipes.get_required(recipe_id, user_id)
        for ingredient in recipe.ingredients:
            food = ingredient.food_item
            if food.source_type != "recipe" or food.source_id is None:
                continue
            try:
                ingredient_recipe_id = UUID(food.source_id)
            except ValueError:
                continue
            if ingredient_recipe_id == target_recipe_id:
                return True
            if self._recipe_references_recipe(user_id, ingredient_recipe_id, target_recipe_id, seen):
                return True
        return False

    def _calculate_totals(self, recipe: Recipe) -> list[AggregatedNutrientTotal]:
        snapshots: list[NutrientSnapshot] = []
        for ingredient in recipe.ingredients:
            resolved = resolve_nutrition(
                ingredient.food_item,
                ingredient.amount_quantity,
                ingredient.amount_unit,
                ingredient.serving_definition_id,
            )
            ingredient.resolved_gram_amount = resolved.amount.gram_amount
            for nutrient in resolved.nutrients:
                snapshots.append(
                    NutrientSnapshot(
                        nutrient_id=nutrient.nutrient_id,
                        amount=nutrient.amount,
                        unit=nutrient.unit,
                        data_status=nutrient.data_status,
                    )
                )
        return [self._quantize_total(total) for total in aggregate_snapshots(snapshots)]

    def _divide_totals(
        self,
        totals: list[AggregatedNutrientTotal],
        divisor: Decimal | None,
    ) -> list[AggregatedNutrientTotal] | None:
        if divisor is None or divisor <= 0:
            return None
        return [
            AggregatedNutrientTotal(
                nutrient_id=total.nutrient_id,
                amount_known=(total.amount_known / divisor).quantize(DECIMAL_PLACES),
                amount_estimated=(total.amount_estimated / divisor).quantize(DECIMAL_PLACES),
                unit=total.unit,
                has_unknown_contributors=total.has_unknown_contributors,
                unknown_contributor_count=total.unknown_contributor_count,
            )
            for total in totals
        ]

    def _append_food_nutrients(
        self,
        food: FoodItem,
        totals: list[AggregatedNutrientTotal],
        basis: NutrientBasis,
    ) -> None:
        for total in totals:
            status = NutrientDataStatus.UNKNOWN if total.has_unknown_contributors else NutrientDataStatus.KNOWN
            amount = None if status == NutrientDataStatus.UNKNOWN else total.amount_known + total.amount_estimated
            if amount == 0 and status == NutrientDataStatus.KNOWN:
                status = NutrientDataStatus.ZERO
            food.nutrients.append(
                FoodNutrient(
                    id=uuid4(),
                    nutrient_id=total.nutrient_id,
                    amount=amount,
                    unit=total.unit,
                    basis=basis.value,
                    data_status=status.value,
                    source="recipe",
                    is_user_confirmed=True,
                )
            )

    def _quantize_total(self, total: AggregatedNutrientTotal) -> AggregatedNutrientTotal:
        return AggregatedNutrientTotal(
            nutrient_id=total.nutrient_id,
            amount_known=total.amount_known.quantize(DECIMAL_PLACES),
            amount_estimated=total.amount_estimated.quantize(DECIMAL_PLACES),
            unit=total.unit,
            has_unknown_contributors=total.has_unknown_contributors,
            unknown_contributor_count=total.unknown_contributor_count,
        )
