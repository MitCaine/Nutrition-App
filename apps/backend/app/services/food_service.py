from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import and_, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.domain.recipe_projection import (
    RecipeProjectionClassification,
    RecipeProjectionKind,
    classify_recipe_projection,
    projection_mutation_error,
)
from app.domain.food_source import classify_food_source
from app.models.food import FoodFavorite, FoodItem, FoodNutrient, ServingDefinition
from app.models.recipe import Recipe, RecipeIngredient
from app.models.recipe_publication import (
    RecipePublicationAmountDefinition,
    RecipePublicationRevision,
)
from app.nutrition.resolution import (
    ResolvedNutrition,
    resolve_food_amount_definitions,
)
from app.nutrition.revision_resolution import resolve_revision_nutrition
from app.repositories.food_repository import FoodRepository
from app.repositories.recipe_repository import RecipeRepository
from app.schemas.food import (
    FoodCreateRequest,
    FoodDeleteAffectedRecipeResponse,
    FoodDeleteDependencyResponse,
    FoodDeleteResultResponse,
    FoodRecipeDependencyResponse,
    FoodResolvedNutritionResponse,
    FoodRecipeServingConflictIngredientResponse,
    FoodRecipeServingConflictRecipeResponse,
    FoodResponse,
    FoodUpdateRecipeServingConflictResponse,
    FoodUpdateRequest,
    ResolvedFoodAmountResponse,
    ResolvedFoodNutrientResponse,
    ServingDefinitionCreateRequest,
)
from app.services.create_idempotency import (
    CreateIdempotencyCoordinator,
    CreateOperationResultUnavailableError,
    create_fingerprint,
    is_create_idempotency_conflict,
)


FAVORITE_IDENTITY_CONSTRAINT = "food_favorites_pkey"
FOOD_DEPENDENCY_RESTART_LIMIT = 3


def _is_favorite_identity_conflict(exc: IntegrityError) -> bool:
    """Recognize only the per-user/Food favorite identity violation.

    PostgreSQL reports the primary-key constraint name. SQLite does not expose a
    constraint name, so its exact two-column UNIQUE diagnostic is the narrow
    equivalent used by unit tests.
    """
    diagnostic = getattr(exc.orig, "diag", None)
    if getattr(diagnostic, "constraint_name", None) == FAVORITE_IDENTITY_CONSTRAINT:
        return True
    message = str(exc.orig).lower()
    return (
        "unique constraint failed: food_favorites.user_id, food_favorites.food_item_id"
        in message
    )


class FoodDependencyError(ValueError):
    def __init__(self, dependency: FoodDeleteDependencyResponse):
        super().__init__("Food is used by active recipes")
        self.dependency = dependency


class FoodUpdateRecipeServingConflictError(ValueError):
    def __init__(self, conflict: FoodUpdateRecipeServingConflictResponse):
        super().__init__(conflict.message)
        self.conflict = conflict


class FoodDependenciesUnstableError(ValueError):
    code = "food_dependencies_unstable"
    message = (
        "Food dependencies changed repeatedly during this operation. "
        "Try again when Recipe edits are complete."
    )

    def __init__(self):
        super().__init__(self.message)

    def detail(self) -> dict[str, str]:
        return {"code": self.code, "message": self.message}


class FoodService:
    def __init__(self, db: Session):
        self.db = db
        self.foods = FoodRepository(db)
        self.recipes = RecipeRepository(db)
        self.create_idempotency = CreateIdempotencyCoordinator(db)

    def create_manual_food(self, user_id: UUID, payload: FoodCreateRequest) -> FoodResponse:
        request_id = payload.client_request_id
        fingerprint = create_fingerprint(payload)
        if request_id is not None:
            receipt = self.create_idempotency.find(
                user_id, "food.create_manual", request_id, fingerprint
            )
            if receipt is not None:
                return self._replay_food_response(user_id, receipt)
        food_id = uuid4()
        try:
            receipt = None
            if request_id is not None:
                receipt = self.create_idempotency.reserve(
                    user_id,
                    "food.create_manual",
                    request_id,
                    fingerprint,
                    food_id,
                )
            food = self.build_manual_food(user_id, payload, food_id=food_id)
            created = self.foods.add(food)
            response = self._food_response(user_id, created)
            if receipt is not None:
                self.create_idempotency.complete(
                    receipt, response.model_dump(mode="json")
                )
            self.db.commit()
            return response
        except IntegrityError as exc:
            self.db.rollback()
            if request_id is None or not is_create_idempotency_conflict(exc):
                raise
            receipt = self.create_idempotency.find(
                user_id, "food.create_manual", request_id, fingerprint
            )
            if receipt is None:
                raise
            return self._replay_food_response(user_id, receipt)
        except Exception:
            self.db.rollback()
            raise

    def build_manual_food(
        self,
        user_id: UUID,
        payload: FoodCreateRequest,
        *,
        food_id: UUID | None = None,
    ) -> FoodItem:
        """Build a normal Manual Food without committing for atomic orchestrators."""
        food = FoodItem(
            id=food_id or uuid4(),
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
        return food

    def list_foods(
        self,
        user_id: UUID,
        query: str | None = None,
        *,
        saved_view: bool = False,
    ) -> list[FoodItem]:
        foods = (
            self.foods.list_saved(user_id, query) if saved_view else self.foods.list(user_id, query)
        )
        return self.present_foods(user_id, foods, exclude_invalid=True)

    def get_food(self, user_id: UUID, food_id: UUID) -> FoodItem:
        food = self.foods.get_required(food_id, user_id)
        classification = classify_recipe_projection(
            food,
            self._linked_recipe(food.id, user_id),
        )
        if classification.kind == RecipeProjectionKind.INTEGRITY_INVALID:
            raise projection_mutation_error(food, classification, "read")
        return self.present_food(user_id, food)

    def present_food(self, user_id: UUID, food: FoodItem) -> FoodItem:
        presented = self.present_foods(user_id, [food], exclude_invalid=False)
        if not presented:
            classification = classify_recipe_projection(food, self._linked_recipe(food.id, user_id))
            raise projection_mutation_error(food, classification, "read")
        return presented[0]

    def present_foods(
        self,
        user_id: UUID,
        foods: list[FoodItem],
        *,
        exclude_invalid: bool,
    ) -> list[FoodItem]:
        if not foods:
            return []
        food_ids = [food.id for food in foods]
        linked_recipes = {
            recipe.published_food_item_id: recipe
            for recipe in self.db.scalars(
                select(Recipe).where(
                    Recipe.user_id == user_id,
                    Recipe.published_food_item_id.in_(food_ids),
                )
            )
            if recipe.published_food_item_id is not None
        }
        favorite_ids = set(
            self.db.scalars(
                select(FoodFavorite.food_item_id).where(
                    FoodFavorite.user_id == user_id,
                    FoodFavorite.food_item_id.in_(food_ids),
                )
            )
        )
        duplicate_source_ids = self._valid_duplicate_source_ids(user_id, foods)
        result = []
        for food in foods:
            trace = food.ocr_confirmation_trace
            classification = classify_food_source(
                food,
                linked_recipes.get(food.id),
                has_same_owner_ocr_trace=bool(
                    trace is not None and trace.user_id == user_id and food.user_id == user_id
                ),
                has_valid_duplicate_source=food.id in duplicate_source_ids,
            )
            if classification is None:
                if exclude_invalid:
                    continue
                projection = classify_recipe_projection(food, linked_recipes.get(food.id))
                raise projection_mutation_error(food, projection, "read")
            food.source_kind = classification.kind
            food.source_label = classification.label
            food.can_favorite = classification.can_favorite
            food.is_favorite = food.id in favorite_ids
            # Invalid Manual duplicate claims fall back to neutral provenance and
            # never expose the malformed, missing, foreign, or self-referential ID.
            food.presented_source_id = (
                None
                if food.source_type == "manual"
                and food.source_id
                and classification.kind == "legacy"
                else food.source_id
            )
            result.append(food)
        return result

    def _valid_duplicate_source_ids(
        self, user_id: UUID, foods: list[FoodItem]
    ) -> set[UUID]:
        """Return candidate Food IDs whose immediate duplicate source is owner-valid.

        The source lookup deliberately includes soft-deleted Foods so a duplicate's
        provenance label remains stable throughout the source lifecycle.
        """
        candidates: dict[UUID, UUID] = {}
        for food in foods:
            if (
                food.user_id != user_id
                or food.source_type != "manual"
                or food.is_recipe is not False
                or food.recipe_publication_revision_id is not None
                or not food.source_id
            ):
                continue
            try:
                source_id = UUID(food.source_id)
            except (TypeError, ValueError, AttributeError):
                continue
            # Production duplication stores the canonical string form of the UUID.
            if food.source_id != str(source_id) or source_id == food.id:
                continue
            candidates[food.id] = source_id
        if not candidates:
            return set()
        existing_source_ids = set(
            self.db.scalars(
                select(FoodItem.id).where(
                    FoodItem.user_id == user_id,
                    FoodItem.id.in_(set(candidates.values())),
                )
            )
        )
        return {
            food_id
            for food_id, source_id in candidates.items()
            if source_id in existing_source_ids
        }

    def list_favorites(self, user_id: UUID) -> list[FoodItem]:
        return self.present_foods(user_id, self.foods.list_favorites(user_id), exclude_invalid=True)

    def list_recent(self, user_id: UUID, limit: int) -> list[dict]:
        rows = self.foods.list_recent(user_id, limit)
        foods = self.present_foods(
            user_id, [food for food, _last_used_at in rows], exclude_invalid=True
        )
        by_id = {food.id: food for food in foods}
        result = []
        for food, last_used_at in rows:
            presented = by_id.get(food.id)
            if presented is None:
                continue
            if last_used_at.tzinfo is None:
                last_used_at = last_used_at.replace(tzinfo=timezone.utc)
            result.append({"food": presented, "last_used_at": last_used_at})
        return result

    def set_favorite(self, user_id: UUID, food_id: UUID, *, favorite: bool) -> FoodItem:
        food = self.foods.get_saved(user_id, food_id)
        if food is None:
            raise LookupError("Food not found")
        row = self.db.get(FoodFavorite, (user_id, food_id))
        attempted_creation = favorite and row is None
        if attempted_creation:
            favorite_row = FoodFavorite(user_id=user_id, food_item_id=food_id)
            self.db.add(favorite_row)
        elif not favorite and row is not None:
            self.db.delete(row)
        try:
            if attempted_creation:
                self.db.flush()
                self._after_favorite_creation(favorite_row)
            self.db.commit()
        except IntegrityError as exc:
            self.db.rollback()
            if not attempted_creation or not _is_favorite_identity_conflict(exc):
                raise
            if self.db.get(FoodFavorite, (user_id, food_id)) is None:
                raise
        return self.present_food(user_id, self.foods.get_required(food_id, user_id))

    def _after_favorite_creation(self, _favorite: FoodFavorite) -> None:
        """Test seam after insert flush and before commit."""

    def resolved_nutrition(
        self,
        user_id: UUID,
        food_id: UUID,
    ) -> FoodResolvedNutritionResponse:
        food, linked_recipe, active_revision = self._food_detail_authorities(user_id, food_id)
        classification = classify_recipe_projection(food, linked_recipe)
        if classification.kind == RecipeProjectionKind.INTEGRITY_INVALID:
            raise projection_mutation_error(food, classification, "read")
        if classification.kind == RecipeProjectionKind.MANUAL:
            return FoodResolvedNutritionResponse(
                nutrition_authority="food_item",
                recipe_id=None,
                recipe_publication_revision_id=None,
                amounts=[
                    self._food_amount_response(amount)
                    for amount in resolve_food_amount_definitions(food)
                    if amount.amount_definition_id is not None
                ],
            )

        if (
            linked_recipe is None
            or active_revision is None
            or active_revision.id != linked_recipe.active_publication_revision_id
            or active_revision.id != food.recipe_publication_revision_id
            or active_revision.recipe_id != linked_recipe.id
            or active_revision.user_id != user_id
        ):
            raise projection_mutation_error(
                food,
                RecipeProjectionClassification(
                    RecipeProjectionKind.INTEGRITY_INVALID,
                    classification.recipe_id,
                ),
                "read",
            )

        return FoodResolvedNutritionResponse(
            nutrition_authority="recipe_publication_revision",
            recipe_id=linked_recipe.id,
            recipe_publication_revision_id=active_revision.id,
            amounts=[
                self._revision_amount_response(active_revision, amount)
                for amount in active_revision.amount_definitions
                if amount.semantic_mode == "serving"
            ],
        )

    def _food_detail_authorities(
        self,
        user_id: UUID,
        food_id: UUID,
    ) -> tuple[FoodItem, Recipe | None, RecipePublicationRevision | None]:
        statement = (
            select(FoodItem, Recipe, RecipePublicationRevision)
            .outerjoin(
                Recipe,
                and_(
                    Recipe.published_food_item_id == FoodItem.id,
                    Recipe.user_id == user_id,
                ),
            )
            .outerjoin(
                RecipePublicationRevision,
                and_(
                    RecipePublicationRevision.id == Recipe.active_publication_revision_id,
                    RecipePublicationRevision.recipe_id == Recipe.id,
                    RecipePublicationRevision.user_id == user_id,
                ),
            )
            .where(
                FoodItem.id == food_id,
                FoodItem.user_id == user_id,
                FoodItem.deleted_at.is_(None),
            )
            .options(
                selectinload(FoodItem.nutrients),
                selectinload(FoodItem.serving_definitions),
                selectinload(RecipePublicationRevision.amount_definitions),
                selectinload(RecipePublicationRevision.nutrients),
            )
        )
        row = self.db.execute(statement).first()
        if row is None:
            raise LookupError("Food not found")
        return row._tuple()

    @staticmethod
    def _food_amount_response(amount: ResolvedNutrition) -> ResolvedFoodAmountResponse:
        return ResolvedFoodAmountResponse(
            amount_definition_id=amount.amount_definition_id,
            display_label=amount.display_label,
            is_default=bool(
                amount.amount.serving_definition and amount.amount.serving_definition.is_default
            ),
            entered_quantity=amount.amount.amount_quantity,
            semantic_amount_mode=amount.amount.amount_unit,
            resolved_grams=amount.amount.gram_amount,
            valid_for_logging=amount.valid_for_logging,
            nutrients=[
                ResolvedFoodNutrientResponse(
                    nutrient_id=nutrient.nutrient_id,
                    amount=nutrient.amount,
                    unit=nutrient.unit,
                    data_status=nutrient.data_status.value,
                    source_basis=nutrient.source_basis.value,
                )
                for nutrient in amount.nutrients
            ],
        )

    @staticmethod
    def _revision_amount_response(
        revision: RecipePublicationRevision,
        amount: RecipePublicationAmountDefinition,
    ) -> ResolvedFoodAmountResponse:
        resolved = resolve_revision_nutrition(
            revision,
            amount.id,
            Decimal("1"),
            semantic_amount_mode=amount.semantic_mode,
        )
        return ResolvedFoodAmountResponse(
            amount_definition_id=amount.id,
            display_label=amount.display_label,
            is_default=amount.is_default,
            entered_quantity=resolved.entered_quantity,
            semantic_amount_mode=resolved.semantic_amount_mode,
            resolved_grams=resolved.resolved_grams,
            valid_for_logging=True,
            nutrients=[
                ResolvedFoodNutrientResponse(
                    nutrient_id=nutrient.nutrient_id,
                    amount=nutrient.amount,
                    unit=nutrient.unit,
                    data_status=nutrient.data_status.value,
                    source_basis=nutrient.source_basis.value,
                )
                for nutrient in resolved.nutrients
            ],
        )

    def update_food(self, user_id: UUID, food_id: UUID, payload: FoodUpdateRequest) -> FoodItem:
        try:
            food, parents = self._lock_food_dependency_graph(user_id, food_id)
            self._assert_generic_mutation_allowed(food, user_id, "update")
            if payload.name is not None:
                food.name = payload.name.strip()
            if payload.brand is not None:
                food.brand = payload.brand.strip() if payload.brand else None
            if payload.notes is not None:
                food.notes = payload.notes
            dependency_affecting = payload.nutrients is not None
            if payload.serving_definitions is not None:
                replacements = self._new_servings(payload.serving_definitions)
                remaps = self._plan_serving_remaps(food, parents, replacements)
                # Release the partial unique default slot before inserting the
                # replacement generation; the enclosing transaction remains atomic.
                for serving in food.serving_definitions:
                    serving.is_default = False
                self.db.flush()
                food.serving_definitions[:] = replacements
                for ingredient, successor in remaps:
                    ingredient.serving_definition_id = successor.id
                    ingredient.resolved_gram_amount = (
                        ingredient.amount_quantity * successor.gram_weight
                        if successor.gram_weight is not None
                        else None
                    )
                dependency_affecting = True
            if payload.nutrients is not None:
                food.nutrients.clear()
                self._replace_nutrients(food, payload.nutrients)
            now = datetime.now(timezone.utc)
            food.updated_at = now
            if dependency_affecting:
                self._mark_published_parents_stale(parents, now)
            self.db.commit()
            return self.foods.get_required(food_id, user_id)
        except Exception:
            self.db.rollback()
            raise

    def soft_delete_food(
        self,
        user_id: UUID,
        food_id: UUID,
        *,
        remove_from_recipes: bool = False,
    ) -> FoodDeleteResultResponse:
        try:
            food, parents = self._lock_food_dependency_graph(user_id, food_id)
            self._assert_generic_mutation_allowed(food, user_id, "delete")
            dependencies = self._food_recipe_dependencies(user_id, food_id)
            if dependencies.affected_recipes and not remove_from_recipes:
                raise FoodDependencyError(dependencies)

            now = datetime.now(timezone.utc)
            affected_recipes: list[FoodDeleteAffectedRecipeResponse] = []
            if remove_from_recipes and dependencies.affected_recipes:
                affected_recipes = self._remove_food_from_locked_recipes(parents, food_id, now)

            food.deleted_at = now
            food.updated_at = now
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise

        return FoodDeleteResultResponse(
            food_id=food_id,
            deleted=True,
            removed_ingredient_count=sum(
                recipe.removed_ingredient_count for recipe in affected_recipes
            ),
            affected_recipes=affected_recipes,
        )

    def duplicate_food(
        self,
        user_id: UUID,
        food_id: UUID,
        client_request_id: UUID | None = None,
    ) -> FoodResponse:
        fingerprint = create_fingerprint(None, context={"food_id": str(food_id)})
        if client_request_id is not None:
            receipt = self.create_idempotency.find(
                user_id, "food.duplicate", client_request_id, fingerprint
            )
            if receipt is not None:
                return self._replay_food_response(user_id, receipt)
        duplicate_id = uuid4()
        try:
            receipt = None
            if client_request_id is not None:
                receipt = self.create_idempotency.reserve(
                    user_id,
                    "food.duplicate",
                    client_request_id,
                    fingerprint,
                    duplicate_id,
                )
            source = self.foods.get_required(food_id, user_id)
            duplicate = FoodItem(
                id=duplicate_id,
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
            response = self._food_response(user_id, created)
            if receipt is not None:
                self.create_idempotency.complete(
                    receipt, response.model_dump(mode="json")
                )
            self.db.commit()
            return response
        except IntegrityError as exc:
            self.db.rollback()
            if client_request_id is None or not is_create_idempotency_conflict(exc):
                raise
            receipt = self.create_idempotency.find(
                user_id, "food.duplicate", client_request_id, fingerprint
            )
            if receipt is None:
                raise
            return self._replay_food_response(user_id, receipt)
        except Exception:
            self.db.rollback()
            raise

    def add_serving_definition(
        self,
        user_id: UUID,
        food_id: UUID,
        payload: ServingDefinitionCreateRequest,
    ) -> FoodResponse:
        # The API uses ServingDefinitionCreateRequest; accepting the historical
        # base schema keeps internal service callers source-compatible.
        request_id = getattr(payload, "client_request_id", None)
        fingerprint = create_fingerprint(payload, context={"food_id": str(food_id)})
        if request_id is not None:
            receipt = self.create_idempotency.find(
                user_id, "food.add_serving", request_id, fingerprint
            )
            if receipt is not None:
                return self._replay_serving_response(user_id, food_id, receipt)
        serving_id = uuid4()
        try:
            receipt = None
            if request_id is not None:
                receipt = self.create_idempotency.reserve(
                    user_id,
                    "food.add_serving",
                    request_id,
                    fingerprint,
                    serving_id,
                )
            food, parents = self._lock_food_dependency_graph(user_id, food_id)
            self._assert_generic_mutation_allowed(food, user_id, "add_serving")
            if payload.is_default:
                for serving in food.serving_definitions:
                    serving.is_default = False
                self.db.flush()
            food.serving_definitions.append(
                ServingDefinition(
                    id=serving_id,
                    label=payload.label.strip(),
                    quantity=payload.quantity,
                    unit=payload.unit,
                    gram_weight=payload.gram_weight,
                    is_default=payload.is_default,
                    source="manual",
                    is_user_confirmed=True,
                )
            )
            now = datetime.now(timezone.utc)
            food.updated_at = now
            if payload.is_default:
                self._mark_published_parents_stale(parents, now)
            response = self._food_response(user_id, food)
            if receipt is not None:
                self.create_idempotency.complete(
                    receipt, response.model_dump(mode="json")
                )
            self.db.commit()
            return response
        except IntegrityError as exc:
            self.db.rollback()
            if request_id is None or not is_create_idempotency_conflict(exc):
                raise
            receipt = self.create_idempotency.find(
                user_id, "food.add_serving", request_id, fingerprint
            )
            if receipt is None:
                raise
            return self._replay_serving_response(user_id, food_id, receipt)
        except Exception:
            self.db.rollback()
            raise

    def _food_response(self, user_id: UUID, food: FoodItem) -> FoodResponse:
        # Snapshot the database-normalized representation (not pre-flush Decimal
        # spellings held by newly appended ORM children).
        self.db.flush()
        self.db.expire(food)
        persisted = self.foods.get_required(food.id, user_id)
        return FoodResponse.model_validate(self.present_food(user_id, persisted))

    def _replay_food_response(
        self,
        user_id: UUID,
        receipt,
    ) -> FoodResponse:
        try:
            self.foods.get_required(receipt.resource_id, user_id)
        except LookupError as exc:
            raise CreateOperationResultUnavailableError() from exc
        return FoodResponse.model_validate(
            self.create_idempotency.replay_snapshot(receipt)
        )

    def _replay_serving_response(
        self,
        user_id: UUID,
        food_id: UUID,
        receipt,
    ) -> FoodResponse:
        serving = self.db.scalar(
            select(ServingDefinition)
            .join(FoodItem, FoodItem.id == ServingDefinition.food_item_id)
            .where(
                ServingDefinition.id == receipt.resource_id,
                ServingDefinition.food_item_id == food_id,
                FoodItem.user_id == user_id,
                FoodItem.deleted_at.is_(None),
            )
        )
        if serving is None:
            raise CreateOperationResultUnavailableError()
        return FoodResponse.model_validate(
            self.create_idempotency.replay_snapshot(receipt)
        )

    def _assert_generic_mutation_allowed(
        self,
        food: FoodItem,
        user_id: UUID,
        operation: str,
    ) -> None:
        linked_recipe = self._linked_recipe(food.id, user_id)
        classification = classify_recipe_projection(food, linked_recipe)
        if classification.kind != RecipeProjectionKind.MANUAL:
            raise projection_mutation_error(food, classification, operation)

    def _linked_recipe(self, food_id: UUID, user_id: UUID) -> Recipe | None:
        return self.db.scalars(
            select(Recipe).where(
                Recipe.user_id == user_id,
                Recipe.published_food_item_id == food_id,
            )
        ).first()

    def _food_recipe_dependencies(
        self, user_id: UUID, food_id: UUID
    ) -> FoodDeleteDependencyResponse:
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
            for recipe_id, recipe_name, published_food_item_id, needs_republish, occurrence_count in self.db.execute(
                statement
            )
        ]
        return FoodDeleteDependencyResponse(
            food_id=food_id,
            active_recipe_count=len(affected_recipes),
            affected_recipes=affected_recipes,
            total_ingredient_rows_affected=sum(
                recipe.ingredient_occurrence_count for recipe in affected_recipes
            ),
        )

    def _dependent_recipe_ids(self, user_id: UUID, food_id: UUID) -> set[UUID]:
        return set(
            self.db.scalars(
                select(Recipe.id)
                .join(RecipeIngredient, RecipeIngredient.recipe_id == Recipe.id)
                .where(
                    Recipe.user_id == user_id,
                    Recipe.deleted_at.is_(None),
                    RecipeIngredient.food_item_id == food_id,
                )
                .order_by(Recipe.id)
                .distinct()
            ).all()
        )

    def _lock_food_dependency_graph(
        self,
        user_id: UUID,
        food_id: UUID,
    ) -> tuple[FoodItem, list[Recipe]]:
        """Lock one Food, then its active parent Recipes in stable UUID order."""
        for _attempt in range(FOOD_DEPENDENCY_RESTART_LIMIT):
            food = self.foods.get_for_update(food_id, user_id)
            if self._has_foreign_dependencies(user_id, food_id):
                # Treat cross-owner dependency corruption as an opaque conflict;
                # never expose or mutate the foreign Recipe graph.
                raise FoodDependenciesUnstableError()
            initial_ids = self._dependent_recipe_ids(user_id, food_id)
            locked = self.recipes.get_many_for_update(initial_ids, user_id)
            final_ids = self._dependent_recipe_ids(user_id, food_id)
            if final_ids == initial_ids and set(locked) == final_ids:
                parents = [locked[recipe_id] for recipe_id in sorted(final_ids)]
                self._after_food_dependency_lock(food, parents)
                return food, parents
            self.db.rollback()
        raise FoodDependenciesUnstableError()

    def _has_foreign_dependencies(self, user_id: UUID, food_id: UUID) -> bool:
        return self.db.scalar(
            select(func.count(RecipeIngredient.id))
            .join(Recipe, Recipe.id == RecipeIngredient.recipe_id)
            .where(
                Recipe.user_id != user_id,
                Recipe.deleted_at.is_(None),
                RecipeIngredient.food_item_id == food_id,
            )
        ) > 0

    def _after_food_dependency_lock(
        self,
        _food: FoodItem,
        _parents: list[Recipe],
    ) -> None:
        """Test seam after Food-then-Recipe dependency locks are complete."""

    @staticmethod
    def _serving_semantic_key(serving: ServingDefinition) -> tuple[Decimal, str, Decimal | None]:
        return (
            serving.quantity.normalize(),
            serving.unit.strip().casefold(),
            serving.gram_weight.normalize() if serving.gram_weight is not None else None,
        )

    def _plan_serving_remaps(
        self,
        food: FoodItem,
        parents: list[Recipe],
        replacements: list[ServingDefinition],
    ) -> list[tuple[RecipeIngredient, ServingDefinition]]:
        old_by_id = {serving.id: serving for serving in food.serving_definitions}
        successors: dict[tuple[Decimal, str, Decimal | None], list[ServingDefinition]] = {}
        for serving in replacements:
            successors.setdefault(self._serving_semantic_key(serving), []).append(serving)

        remaps: list[tuple[RecipeIngredient, ServingDefinition]] = []
        conflicts: list[FoodRecipeServingConflictRecipeResponse] = []
        for recipe in parents:
            recipe_conflicts: list[FoodRecipeServingConflictIngredientResponse] = []
            for ingredient in recipe.ingredients:
                if ingredient.food_item_id != food.id or ingredient.serving_definition_id is None:
                    continue
                old = old_by_id.get(ingredient.serving_definition_id)
                matching = successors.get(self._serving_semantic_key(old), []) if old else []
                if len(matching) == 1:
                    remaps.append((ingredient, matching[0]))
                else:
                    recipe_conflicts.append(
                        FoodRecipeServingConflictIngredientResponse(
                            position=ingredient.position,
                            old_serving_label=old.label if old is not None else "Unavailable serving",
                        )
                    )
            if recipe_conflicts:
                conflicts.append(
                    FoodRecipeServingConflictRecipeResponse(
                        recipe_id=recipe.id,
                        recipe_name=recipe.name,
                        ingredients=recipe_conflicts,
                    )
                )
        if conflicts:
            raise FoodUpdateRecipeServingConflictError(
                FoodUpdateRecipeServingConflictResponse(
                    food_id=food.id,
                    affected_recipes=sorted(conflicts, key=lambda row: str(row.recipe_id)),
                )
            )
        return remaps

    @staticmethod
    def _mark_published_parents_stale(parents: list[Recipe], now: datetime) -> None:
        for recipe in parents:
            if recipe.published_food_item_id is not None:
                recipe.needs_republish = True
                recipe.updated_at = now

    @staticmethod
    def _new_servings(servings) -> list[ServingDefinition]:
        return [
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
            for serving in servings
        ]

    def _remove_food_from_locked_recipes(
        self,
        recipes: list[Recipe],
        food_id: UUID,
        now: datetime,
    ) -> list[FoodDeleteAffectedRecipeResponse]:
        affected_recipes: list[FoodDeleteAffectedRecipeResponse] = []
        for recipe in recipes:
            removed_count = sum(
                1 for ingredient in recipe.ingredients if ingredient.food_item_id == food_id
            )
            if removed_count == 0:
                continue
            remaining = [
                ingredient
                for ingredient in recipe.ingredients
                if ingredient.food_item_id != food_id
            ]
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
        food.serving_definitions.extend(self._new_servings(servings))

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
