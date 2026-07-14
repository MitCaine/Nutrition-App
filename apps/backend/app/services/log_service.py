from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from hashlib import sha256
import json
from uuid import UUID, uuid4

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.domain.nutrition import NutrientDataStatus, NutrientSnapshot
from app.domain.recipe_nutrition_validation import RecipeNutritionValidationError
from app.models.food import FoodItem
from app.models.log import DailyLog
from app.models.recipe_publication import (
    RecipePublicationAmountDefinition,
    RecipePublicationRevision,
)
from app.nutrition.aggregation import aggregate_snapshots
from app.nutrition.calculations import build_log_snapshots, build_revision_log_snapshots
from app.nutrition.resolution import (
    AmbiguousNutrientBasisError,
    NutritionResolutionError,
    UnsupportedNutritionAmountError,
    resolve_nutrition,
)
from app.nutrition.revision_resolution import (
    map_projection_log_amount,
    resolve_revision_nutrition,
)
from app.repositories.food_repository import FoodRepository
from app.repositories.log_repository import LogRepository
from app.repositories.recipe_publication_repository import RecipePublicationRepository
from app.repositories.recipe_repository import RecipeRepository
from app.schemas.log import (
    DailyLogCreateRequest,
    DailyLogEditAmountResponse,
    DailyLogEditContextResponse,
    DailyLogUpdateRequest,
)


def _creation_fingerprint(payload: DailyLogCreateRequest) -> str:
    canonical = {
        "amount_quantity": _canonical_decimal(payload.amount_quantity),
        "amount_unit": payload.amount_unit,
        "food_item_id": str(payload.food_item_id),
        "logged_date": payload.logged_date.isoformat(),
        "meal_type": payload.meal_type,
        "notes": payload.notes,
        "serving_definition_id": (
            str(payload.serving_definition_id)
            if payload.serving_definition_id is not None
            else None
        ),
    }
    encoded = json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode()
    return sha256(encoded).hexdigest()


def _canonical_decimal(value: Decimal) -> str:
    return format(value.normalize(), "f")


def _matching_idempotent_log(log: DailyLog, fingerprint: str | None) -> DailyLog:
    if log.client_request_fingerprint != fingerprint:
        raise LogIdempotencyConflictError(LogIdempotencyConflictError.message)
    return log


def _is_idempotency_unique_conflict(exc: IntegrityError) -> bool:
    diagnostic = getattr(exc.orig, "diag", None)
    if getattr(diagnostic, "constraint_name", None) == "uq_daily_logs_user_client_request":
        return True
    message = str(exc.orig).lower()
    return (
        "daily_logs.user_id, daily_logs.client_request_id" in message
        or "uq_daily_logs_user_client_request" in message
    )


class LogEditConflictError(ValueError):
    code = "source_food_deleted"
    message = "This historical entry cannot be edited because its source food was deleted."


class LogIdempotencyConflictError(ValueError):
    code = "log_idempotency_payload_conflict"
    message = "This request ID was already used for a different Daily Log creation."


class LogService:
    def __init__(self, db: Session):
        self.db = db
        self.foods = FoodRepository(db)
        self.logs = LogRepository(db)
        self.publications = RecipePublicationRepository(db)
        self.recipes = RecipeRepository(db)

    def create_log(self, user_id: UUID, payload: DailyLogCreateRequest) -> DailyLog:
        fingerprint = _creation_fingerprint(payload) if payload.client_request_id else None
        if payload.client_request_id is not None:
            existing = self.logs.get_by_client_request_id(user_id, payload.client_request_id)
            if existing is not None:
                return _matching_idempotent_log(existing, fingerprint)
        try:
            food = self.foods.get_required(payload.food_item_id, user_id)
            if food.is_recipe or food.source_type == "recipe":
                log = self._create_recipe_log(user_id, food, payload)
            else:
                log = self._create_food_log(user_id, food, payload)
            log.client_request_id = payload.client_request_id
            log.client_request_fingerprint = fingerprint
            created = self.logs.add(log)
            self._after_snapshot_creation(created)
            self.db.commit()
            return created
        except IntegrityError as exc:
            self.db.rollback()
            if (
                payload.client_request_id is None
                or not _is_idempotency_unique_conflict(exc)
            ):
                raise
            existing = self.logs.get_by_client_request_id(user_id, payload.client_request_id)
            if existing is None:
                raise
            return _matching_idempotent_log(existing, fingerprint)
        except Exception:
            self.db.rollback()
            raise

    def _create_food_log(
        self,
        user_id: UUID,
        food: FoodItem,
        payload: DailyLogCreateRequest,
    ) -> DailyLog:
        resolved = resolve_nutrition(
            food,
            payload.amount_quantity,
            payload.amount_unit,
            payload.serving_definition_id,
        )
        log = DailyLog(
            id=uuid4(),
            user_id=user_id,
            food_item_id=food.id,
            food_name_snapshot=food.name,
            logged_date=payload.logged_date,
            meal_type=payload.meal_type,
            amount_quantity=payload.amount_quantity,
            amount_unit=payload.amount_unit,
            serving_definition_id=(
                resolved.amount.serving_definition.id
                if resolved.amount.serving_definition is not None
                else None
            ),
            gram_amount=resolved.amount.gram_amount,
            package_fraction=None,
            notes=payload.notes,
        )
        log.snapshots = build_log_snapshots(food, resolved)
        return log

    def _create_recipe_log(
        self,
        user_id: UUID,
        selected_food: FoodItem,
        payload: DailyLogCreateRequest,
    ) -> DailyLog:
        if not selected_food.is_recipe or selected_food.source_type != "recipe":
            raise ValueError("Selected food is not a valid Recipe compatibility projection")
        if selected_food.source_id is None:
            raise ValueError("Recipe compatibility projection has no source identity")
        try:
            recipe_id = UUID(selected_food.source_id)
        except ValueError as exc:
            raise ValueError("Recipe compatibility projection has invalid source identity") from exc

        recipe = self.recipes.get_for_update(recipe_id, user_id)
        self.db.expire(selected_food)
        food = self.foods.get_required(payload.food_item_id, user_id)
        if (
            not food.is_recipe
            or food.source_type != "recipe"
            or recipe.published_food_item_id != food.id
            or food.source_id != str(recipe.id)
            or food.recipe_publication_revision_id is None
            or recipe.active_publication_revision_id is None
            or food.recipe_publication_revision_id != recipe.active_publication_revision_id
        ):
            raise ValueError("Recipe compatibility projection is not linked to its active publication")

        revision = self.publications.get_required(
            recipe.active_publication_revision_id,
            user_id,
        )
        if revision.recipe_id != recipe.id:
            raise ValueError("Active publication does not belong to the selected Recipe")
        self._after_recipe_revision_lookup(revision)
        selection = map_projection_log_amount(
            food,
            revision,
            payload.amount_unit,
            payload.serving_definition_id,
        )
        self._after_recipe_amount_definition_lookup(selection.revision_amount)
        resolved = resolve_revision_nutrition(
            revision,
            selection.revision_amount.id,
            payload.amount_quantity,
            semantic_amount_mode=payload.amount_unit,
        )
        compatibility_serving_id = (
            selection.compatibility_serving.id
            if selection.compatibility_serving is not None
            else None
        )
        log = DailyLog(
            id=uuid4(),
            user_id=user_id,
            food_item_id=food.id,
            food_name_snapshot=revision.published_name,
            logged_date=payload.logged_date,
            meal_type=payload.meal_type,
            amount_quantity=resolved.entered_quantity,
            amount_unit=resolved.semantic_amount_mode,
            serving_definition_id=compatibility_serving_id,
            recipe_publication_revision_id=revision.id,
            recipe_publication_amount_definition_id=selection.revision_amount.id,
            gram_amount=resolved.resolved_grams,
            package_fraction=None,
            notes=payload.notes,
        )
        log.snapshots = build_revision_log_snapshots(
            food,
            resolved,
            compatibility_serving_id,
        )
        return log

    def _after_recipe_revision_lookup(self, _revision: RecipePublicationRevision) -> None:
        """Test seam after active immutable publication lookup."""

    def _after_recipe_amount_definition_lookup(
        self,
        _amount: RecipePublicationAmountDefinition,
    ) -> None:
        """Test seam after projection selection maps to revision-owned input."""

    def _after_snapshot_creation(self, _log: DailyLog) -> None:
        """Test seam after the log and snapshots are flushed, before commit."""

    def list_logs(self, user_id: UUID, logged_date: date) -> list[DailyLog]:
        return self.logs.list_for_date(user_id, logged_date)

    def edit_context(self, user_id: UUID, log_id: UUID) -> DailyLogEditContextResponse:
        log = self.logs.get_required(log_id, user_id)
        revision_id = log.recipe_publication_revision_id
        if revision_id is None:
            return DailyLogEditContextResponse(
                log_id=log.id,
                source_food_available=log.source_food_available,
                is_revision_backed=False,
                recipe_publication_revision_id=None,
                selected_amount_definition_id=None,
                amount_choices=[],
            )

        revision = self.publications.get(revision_id, user_id)
        if revision is None:
            raise RecipeNutritionValidationError(
                "recipe_log_revision_missing",
                "This entry's publication revision is no longer available.",
            )
        selected_id = log.recipe_publication_amount_definition_id
        if not any(amount.id == selected_id for amount in revision.amount_definitions):
            raise RecipeNutritionValidationError(
                "recipe_log_amount_definition_missing",
                "This entry's saved amount is no longer available in its publication revision.",
            )
        return DailyLogEditContextResponse(
            log_id=log.id,
            source_food_available=log.source_food_available,
            is_revision_backed=True,
            recipe_publication_revision_id=revision.id,
            selected_amount_definition_id=selected_id,
            amount_choices=[
                DailyLogEditAmountResponse(
                    amount_definition_id=amount.id,
                    display_label=amount.display_label,
                    semantic_mode=amount.semantic_mode,
                    display_quantity=amount.display_quantity,
                    display_unit=amount.display_unit,
                    gram_equivalent=amount.gram_equivalent,
                    is_default=amount.is_default,
                    is_selected=amount.id == selected_id,
                )
                for amount in revision.amount_definitions
            ],
        )

    def update_log(self, user_id: UUID, log_id: UUID, payload: DailyLogUpdateRequest) -> DailyLog:
        try:
            log = self.logs.get_for_update(log_id, user_id)
            if log.recipe_publication_revision_id is not None:
                self._update_revision_aware_log(user_id, log, payload)
            else:
                self._update_compatibility_log(user_id, log, payload)
            self.db.commit()
            return self.logs.get_required(log.id, user_id)
        except Exception:
            self.db.rollback()
            raise

    def _update_compatibility_log(
        self,
        user_id: UUID,
        log: DailyLog,
        payload: DailyLogUpdateRequest,
    ) -> None:
        if not log.is_editable:
            raise LogEditConflictError(LogEditConflictError.message)
        food = self.foods.get_required(log.food_item_id, user_id)
        amount_quantity = payload.amount_quantity if payload.amount_quantity is not None else log.amount_quantity
        amount_unit = payload.amount_unit if payload.amount_unit is not None else log.amount_unit
        serving_definition_id = (
            payload.serving_definition_id
            if "serving_definition_id" in payload.model_fields_set
            else log.serving_definition_id
        )
        # Manual Food and legacy Recipe logs intentionally retain their existing
        # mutable-source compatibility behavior.
        resolved = resolve_nutrition(food, amount_quantity, amount_unit, serving_definition_id)

        self.logs.delete_snapshots(log.id)
        self._apply_log_metadata(log, payload)
        log.amount_quantity = amount_quantity
        log.amount_unit = amount_unit
        log.serving_definition_id = (
            resolved.amount.serving_definition.id
            if resolved.amount.serving_definition is not None
            else None
        )
        log.gram_amount = resolved.amount.gram_amount
        log.package_fraction = None
        log.updated_at = datetime.now(timezone.utc)
        log.snapshots = build_log_snapshots(food, resolved)

    def _update_revision_aware_log(
        self,
        user_id: UUID,
        log: DailyLog,
        payload: DailyLogUpdateRequest,
    ) -> None:
        if log.food_item.user_id != user_id:
            raise RecipeNutritionValidationError(
                "recipe_log_source_food_unavailable",
                "This entry's source food is no longer available.",
            )
        revision = self.publications.get(log.recipe_publication_revision_id, user_id)
        if revision is None:
            raise RecipeNutritionValidationError(
                "recipe_log_revision_missing",
                "This entry's publication revision is no longer available.",
            )
        self._after_edit_revision_lookup(revision)
        stored_amount = next(
            (
                amount
                for amount in revision.amount_definitions
                if amount.id == log.recipe_publication_amount_definition_id
            ),
            None,
        )
        if stored_amount is None:
            raise RecipeNutritionValidationError(
                "recipe_log_amount_definition_missing",
                "This entry's saved amount is no longer available in its publication revision.",
            )

        nutritional_edit = (
            payload.amount_quantity is not None
            or payload.amount_unit is not None
            or "serving_definition_id" in payload.model_fields_set
        )
        if not nutritional_edit:
            self._apply_log_metadata(log, payload)
            log.updated_at = datetime.now(timezone.utc)
            return

        amount_quantity = (
            payload.amount_quantity if payload.amount_quantity is not None else log.amount_quantity
        )
        amount_unit = payload.amount_unit if payload.amount_unit is not None else log.amount_unit
        selected_amount = self._select_revision_edit_amount(
            log,
            revision,
            stored_amount,
            payload,
            amount_unit,
        )
        self._after_edit_amount_lookup(selected_amount)
        try:
            resolved = resolve_revision_nutrition(
                revision,
                selected_amount.id,
                amount_quantity,
                semantic_amount_mode=amount_unit,
            )
        except AmbiguousNutrientBasisError as exc:
            raise RecipeNutritionValidationError(
                "recipe_log_nutrient_basis_ambiguous",
                "This entry's publication revision contains conflicting nutrient bases.",
            ) from exc
        except UnsupportedNutritionAmountError as exc:
            raise RecipeNutritionValidationError(
                "recipe_log_conversion_unsupported",
                "This amount cannot be resolved from the entry's publication revision.",
            ) from exc
        except NutritionResolutionError as exc:
            raise RecipeNutritionValidationError(
                "recipe_log_nutrition_invalid",
                "This entry's publication revision contains invalid nutrition data.",
            ) from exc

        compatibility_serving_id = (
            log.serving_definition_id if selected_amount.id == stored_amount.id else None
        )
        self.logs.delete_snapshots(log.id)
        self._apply_log_metadata(log, payload)
        log.amount_quantity = resolved.entered_quantity
        log.amount_unit = resolved.semantic_amount_mode
        log.serving_definition_id = compatibility_serving_id
        log.recipe_publication_amount_definition_id = selected_amount.id
        log.gram_amount = resolved.resolved_grams
        log.package_fraction = None
        log.updated_at = datetime.now(timezone.utc)
        log.snapshots = build_revision_log_snapshots(
            log.food_item,
            resolved,
            compatibility_serving_id,
        )
        self.db.flush()
        self._after_edit_snapshot_regeneration(log)

    def _select_revision_edit_amount(
        self,
        log: DailyLog,
        revision: RecipePublicationRevision,
        stored_amount: RecipePublicationAmountDefinition,
        payload: DailyLogUpdateRequest,
        amount_unit: str,
    ) -> RecipePublicationAmountDefinition:
        amount_unit = amount_unit.strip().lower()
        serving_supplied = "serving_definition_id" in payload.model_fields_set
        requested_id = payload.serving_definition_id
        if serving_supplied and requested_id is not None:
            if requested_id == log.serving_definition_id:
                selected = stored_amount
            else:
                selected = next(
                    (amount for amount in revision.amount_definitions if amount.id == requested_id),
                    None,
                )
                if selected is None:
                    raise RecipeNutritionValidationError(
                        "recipe_log_serving_not_in_revision",
                        "The selected amount is not available in this entry's publication revision.",
                    )
        elif not serving_supplied and amount_unit == log.amount_unit:
            selected = stored_amount
        else:
            candidates = [
                amount
                for amount in revision.amount_definitions
                if amount.semantic_mode == amount_unit
                and (amount_unit == "g" or amount.is_default)
            ]
            if len(candidates) != 1:
                raise RecipeNutritionValidationError(
                    "recipe_log_conversion_unsupported",
                    "This amount cannot be resolved from the entry's publication revision.",
                )
            selected = candidates[0]

        if selected.semantic_mode != amount_unit:
            raise RecipeNutritionValidationError(
                "recipe_log_conversion_unsupported",
                "This amount cannot be resolved from the entry's publication revision.",
            )
        return selected

    def _apply_log_metadata(
        self,
        log: DailyLog,
        payload: DailyLogUpdateRequest,
    ) -> None:
        log.logged_date = payload.logged_date if payload.logged_date is not None else log.logged_date
        log.meal_type = payload.meal_type if payload.meal_type is not None else log.meal_type
        log.notes = payload.notes if payload.notes is not None else log.notes

    def _after_edit_revision_lookup(self, _revision: RecipePublicationRevision) -> None:
        """Test seam after the stored revision is loaded."""

    def _after_edit_amount_lookup(self, _amount: RecipePublicationAmountDefinition) -> None:
        """Test seam after the stored revision amount is selected."""

    def _after_edit_snapshot_regeneration(self, _log: DailyLog) -> None:
        """Test seam after replacement snapshots are flushed."""

    def delete_log(self, user_id: UUID, log_id: UUID) -> None:
        log = self.logs.get_required(log_id, user_id)
        self.logs.delete(log)
        self.db.commit()

    def daily_summary(self, user_id: UUID, logged_date: date):
        snapshots = [
            NutrientSnapshot(
                nutrient_id=snapshot.nutrient_id,
                amount=snapshot.amount,
                unit=snapshot.unit,
                data_status=NutrientDataStatus(snapshot.data_status),
            )
            for snapshot in self.logs.snapshots_for_date(user_id, logged_date)
        ]
        return aggregate_snapshots(snapshots)
