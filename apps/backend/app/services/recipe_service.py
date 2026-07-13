from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy.orm import Session

from app.catalog.nutrients import NUTRIENT_CATALOG
from app.domain.nutrition import AggregatedNutrientTotal, NutrientSnapshot
from app.domain.recipe_nutrition_validation import RecipeNutritionValidationError
from app.models.food import FoodItem
from app.models.recipe import Recipe, RecipeIngredient
from app.nutrition.aggregation import aggregate_snapshots
from app.nutrition.resolution import (
    AmbiguousNutrientBasisError,
    NutritionResolutionError,
    UnsupportedNutritionAmountError,
    resolve_amount,
    resolve_nutrition,
)
from app.publication.recipe_revision import (
    apply_revision_to_projection,
    build_revision,
    content_from_recipe_output,
    projection_matches_revision,
    validate_revision_resolver_input,
)
from app.repositories.food_repository import FoodRepository
from app.repositories.recipe_publication_repository import RecipePublicationRepository
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
        self.publications = RecipePublicationRepository(db)

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
        recipe = self.recipes.get_for_update(recipe_id, user_id)
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
        try:
            recipe = self.recipes.get_for_update(recipe_id, user_id)
            if not recipe.serving_count_yield and not recipe.final_cooked_weight_grams:
                raise ValueError(
                    "Publishing requires serving_count_yield or final_cooked_weight_grams"
                )

            totals = self._calculate_totals(recipe)
            per_serving = self._divide_totals(totals, recipe.serving_count_yield)
            per_100g = self._divide_totals(
                totals,
                (
                    recipe.final_cooked_weight_grams / Decimal("100")
                    if recipe.final_cooked_weight_grams
                    else None
                ),
            )
            revision_number = self.publications.next_revision_number(recipe.id, user_id)
            is_republish = revision_number > 1 or recipe.published_food_item_id is not None
            revision = build_revision(
                recipe_id=recipe.id,
                user_id=user_id,
                revision_number=revision_number,
                creation_origin=("explicit_republish" if is_republish else "normal_publication"),
                provenance_confidence="complete",
                content=content_from_recipe_output(
                    published_name=recipe.name,
                    published_notes=recipe.notes,
                    serving_count_yield=recipe.serving_count_yield,
                    final_cooked_weight_grams=recipe.final_cooked_weight_grams,
                    per_serving=per_serving,
                    per_100g=per_100g,
                ),
            )
            validate_revision_resolver_input(revision)
            self.publications.add(revision)
            self._after_revision_insert(revision)

            self._assign_active_revision(recipe, revision.id)
            self.db.flush()
            self._after_active_revision_assignment(recipe)
            projection = self._select_or_create_projection(recipe, user_id)
            apply_revision_to_projection(
                projection,
                revision,
                recipe_id=recipe.id,
                user_id=user_id,
                updated_at=datetime.now(timezone.utc),
            )
            self.db.flush()
            self._after_projection_refresh(projection)
            self._link_projection(projection, revision.id)
            self.db.flush()
            self._after_projection_link(projection)
            if not projection_matches_revision(projection, revision):
                raise ValueError("Compatibility projection does not match publication revision")

            recipe.published_food_item = projection
            recipe.needs_republish = False
            recipe.updated_at = datetime.now(timezone.utc)
            self.db.flush()
            self.db.commit()
            return self.recipes.get_required(recipe_id, user_id), self.foods.get_required(
                projection.id,
                user_id,
            )
        except Exception:
            self.db.rollback()
            raise

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
            try:
                resolved = resolve_nutrition(
                    ingredient.food_item,
                    ingredient.amount_quantity,
                    ingredient.amount_unit,
                    ingredient.serving_definition_id,
                )
            except AmbiguousNutrientBasisError as exc:
                raise RecipeNutritionValidationError(
                    "ingredient_nutrient_basis_ambiguous",
                    f"Cannot calculate nutrition for {ingredient.food_item.name} because its nutrient data has conflicting bases.",
                    food_name=ingredient.food_item.name,
                ) from exc
            except UnsupportedNutritionAmountError as exc:
                raise self._ingredient_amount_error(ingredient) from exc
            except NutritionResolutionError as exc:
                raise RecipeNutritionValidationError(
                    "ingredient_nutrition_invalid",
                    f"Cannot calculate nutrition for {ingredient.food_item.name} because its nutrient data is invalid.",
                    food_name=ingredient.food_item.name,
                ) from exc
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

    def _ingredient_amount_error(
        self,
        ingredient: RecipeIngredient,
    ) -> RecipeNutritionValidationError:
        food = ingredient.food_item
        selected_serving = next(
            (
                serving
                for serving in food.serving_definitions
                if serving.id == ingredient.serving_definition_id
            ),
            None,
        )
        if selected_serving is None and ingredient.serving_definition_id is None:
            selected_serving = next(
                (serving for serving in food.serving_definitions if serving.is_default),
                None,
            )
        if selected_serving is None and ingredient.amount_unit == "serving":
            return RecipeNutritionValidationError(
                "ingredient_serving_definition_missing",
                f"Cannot calculate nutrition for {food.name} because its serving is no longer available.",
                food_name=food.name,
            )
        if selected_serving is not None and selected_serving.gram_weight is None:
            return RecipeNutritionValidationError(
                "ingredient_serving_missing_gram_weight",
                f"Cannot calculate nutrition for {food.name} because the serving '{selected_serving.label}' has no gram weight.",
                food_name=food.name,
                serving_label=selected_serving.label,
            )
        return RecipeNutritionValidationError(
            "ingredient_conversion_unsupported",
            f"Cannot calculate nutrition for {food.name} using the selected amount.",
            food_name=food.name,
        )

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

    def _select_or_create_projection(self, recipe: Recipe, user_id: UUID) -> FoodItem:
        active = self.foods.list_active_by_source(user_id, "recipe", str(recipe.id))
        if len(active) > 1:
            raise ValueError("Recipe has multiple active compatibility projections")
        if active:
            return active[0]
        projection = FoodItem(
            id=uuid4(),
            user_id=user_id,
            name=recipe.name,
            brand=None,
            notes=recipe.notes,
            source_type="recipe",
            source_id=str(recipe.id),
            is_recipe=True,
        )
        self.db.add(projection)
        return projection

    def _assign_active_revision(self, recipe: Recipe, revision_id: UUID) -> None:
        recipe.active_publication_revision_id = revision_id

    def _link_projection(self, projection: FoodItem, revision_id: UUID) -> None:
        projection.recipe_publication_revision_id = revision_id

    def _after_revision_insert(self, _revision) -> None:
        """Test seam after immutable revision graph insertion, before activation."""

    def _after_active_revision_assignment(self, _recipe: Recipe) -> None:
        """Test seam after active designation, before projection refresh."""

    def _after_projection_refresh(self, _projection: FoodItem) -> None:
        """Test seam after projection mutation, before revision linkage."""

    def _after_projection_link(self, _projection: FoodItem) -> None:
        """Test seam after projection linkage, before final validation and commit."""

    def _quantize_total(self, total: AggregatedNutrientTotal) -> AggregatedNutrientTotal:
        return AggregatedNutrientTotal(
            nutrient_id=total.nutrient_id,
            amount_known=total.amount_known.quantize(DECIMAL_PLACES),
            amount_estimated=total.amount_estimated.quantize(DECIMAL_PLACES),
            unit=total.unit,
            has_unknown_contributors=total.has_unknown_contributors,
            unknown_contributor_count=total.unknown_contributor_count,
        )
