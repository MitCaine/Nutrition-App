from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from hashlib import sha256
import json
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.domain.log_contracts import MAX_NOTE_CODE_POINTS, normalize_meal, normalize_note
from app.domain.nutrition import NutrientDataStatus, NutrientSnapshot
from app.domain.recipe_nutrition_validation import RecipeNutritionValidationError
from app.models.food import FoodItem
from app.models.log import DailyLog
from app.models.create_idempotency import CreateOperationIdempotency
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
    resolve_food_amount_definitions,
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
    DailyLogDeleteRequest,
    DailyLogEditAmountResponse,
    DailyLogEditContextResponse,
    DailyLogMutationStatusResponse,
    DailyLogResponse,
    DailyLogUpdateRequest,
)
from app.services.calendar_service import (
    CalendarService,
    AuthoritativeTimeZoneRequiredError,
    require_authoritative_time_zone,
)
from app.services.create_idempotency import (
    CreateIdempotencyCoordinator,
    CreateOperationIdempotencyConflictError,
    CreateOperationResultUnavailableError,
)


def _creation_fingerprint(payload: DailyLogCreateRequest) -> str:
    canonical = {
        "amount_quantity": _canonical_decimal(payload.amount_quantity),
        "amount_unit": payload.amount_unit,
        "food_item_id": str(payload.food_item_id),
        "logged_date": payload.logged_date.isoformat(),
        "meal_type": normalize_meal(payload.meal_type),
        "notes": normalize_note(payload.notes),
        "serving_definition_id": (
            str(payload.serving_definition_id)
            if payload.serving_definition_id is not None
            else None
        ),
        "source_food_updated_at": (
            payload.source_food_updated_at.isoformat()
            if payload.source_food_updated_at is not None
            else None
        ),
        "source_recipe_publication_revision_id": (
            str(payload.source_recipe_publication_revision_id)
            if payload.source_recipe_publication_revision_id is not None
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
    message = "This logging attempt was already submitted with different details. Start a new log and try again."


class LogSourceChangedError(ValueError):
    """Raised when the reviewed source generation is no longer current."""

    code = "stale_log_source"
    message = (
        "The source nutrition changed after review. Refresh the Food and review "
        "the current amount choices before saving."
    )


class LogSourceAmountChangedError(ValueError):
    """Raised when a reviewed serving or immutable amount is no longer valid."""

    code = "stale_log_amount"
    message = (
        "The selected serving or amount changed or is no longer available. "
        "Choose a current amount before saving."
    )


class LogSourceUnavailableError(ValueError):
    """Raised when the selected source can no longer produce a log."""

    code = "source_food_unavailable"
    message = (
        "This Food is no longer available for logging. Return to Add Food and "
        "choose another Food."
    )


class LogMutationPayloadConflictError(ValueError):
    """Raised when an intent identity is reused for a different mutation."""

    code = "log_mutation_payload_conflict"
    message = (
        "This log mutation was already submitted with different details. "
        "Start a new mutation and review the current entry."
    )


class StaleLogMutationError(ValueError):
    """Raised when a mutation's entry precondition no longer matches."""

    code = "stale_log_entry"
    message = (
        "This Daily Log entry changed or was deleted elsewhere. "
        "Refresh it and review the latest state before trying again."
    )


class LogMutationResultUnavailableError(ValueError):
    """Raised when a reserved intent has no durable terminal response."""

    code = "log_mutation_unresolved"
    message = (
        "The outcome of this log mutation is not yet available. "
        "Check its status before starting another mutation."
    )


class LogMutationReplay:
    """A prior committed response returned without reapplying the mutation."""

    def __init__(self, snapshot: dict, log_id: UUID):
        self.snapshot = snapshot
        self.log_id = log_id

    @property
    def id(self) -> UUID:
        """Expose the affected resource identity for service-level callers."""

        return self.log_id


def _mutation_fingerprint(
    operation: str,
    log_id: UUID,
    payload: DailyLogUpdateRequest | DailyLogDeleteRequest,
) -> str:
    """Hash the exact canonical intent, including PATCH presence semantics."""

    values = payload.model_dump(mode="python", exclude={"client_request_id"})
    if isinstance(payload, DailyLogUpdateRequest):
        values["_fields_set"] = sorted(payload.model_fields_set)
    canonical = {
        "operation": operation,
        "log_id": str(log_id),
        "payload": _canonicalize_mutation_value(values),
    }
    encoded = json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode()
    return sha256(encoded).hexdigest()


def _canonicalize_mutation_value(value):
    if isinstance(value, Decimal):
        return _canonical_decimal(value)
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): _canonicalize_mutation_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_canonicalize_mutation_value(item) for item in value]
    return value


def _same_timestamp(left: datetime, right: datetime) -> bool:
    """Compare SQLite-naive and PostgreSQL-aware timestamps by UTC instant."""

    def aware(value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    return aware(left) == aware(right)


def _source_precondition_supplied(
    payload: DailyLogCreateRequest | DailyLogUpdateRequest,
) -> bool:
    return (
        payload.source_food_updated_at is not None
        or payload.source_recipe_publication_revision_id is not None
    )


def _parse_receipt_date(value: object) -> date | None:
    if not isinstance(value, str):
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _snapshot_signature(log: DailyLog) -> tuple[str, ...]:
    """Canonical persisted nutrition semantics for Complete invalidation decisions."""

    rows: list[str] = []
    for snapshot in log.snapshots:
        canonical = {
            "source_food_item_id": snapshot.source_food_item_id,
            "source_food_nutrient_id": snapshot.source_food_nutrient_id,
            "serving_definition_id": snapshot.serving_definition_id,
            "nutrient_id": snapshot.nutrient_id,
            "amount": snapshot.amount,
            "unit": snapshot.unit,
            "data_status": snapshot.data_status,
            "consumed_amount_quantity": snapshot.consumed_amount_quantity,
            "consumed_amount_unit": snapshot.consumed_amount_unit,
            "consumed_gram_amount": snapshot.consumed_gram_amount,
            "consumed_package_fraction": snapshot.consumed_package_fraction,
            "calculation_metadata": snapshot.calculation_metadata,
        }
        rows.append(
            json.dumps(
                _canonicalize_mutation_value(canonical),
                sort_keys=True,
                separators=(",", ":"),
            )
        )
    return tuple(sorted(rows))


class LogService:
    def __init__(self, db: Session):
        self.db = db
        self.foods = FoodRepository(db)
        self.logs = LogRepository(db)
        self.publications = RecipePublicationRepository(db)
        self.recipes = RecipeRepository(db)
        # The existing receipt table is operation-scoped and already stores a
        # canonical fingerprint plus terminal response snapshot. Reusing it
        # keeps log mutation replay within the established transaction model.
        self.mutation_receipts = CreateIdempotencyCoordinator(db)

    def _invalidate_complete_dates(
        self,
        user_id: UUID,
        logged_dates: set[date],
    ) -> set[date]:
        invalidated = {
            logged_date
            for logged_date in logged_dates
            if self.logs.clear_day_completion(user_id, logged_date)
        }
        if invalidated:
            self._after_complete_invalidation(invalidated)
        return invalidated

    def _after_complete_invalidation(self, _logged_dates: set[date]) -> None:
        """Test seam after Complete deletion and before the surrounding commit."""

    def create_log(self, user_id: UUID, payload: DailyLogCreateRequest) -> DailyLog:
        if payload.calendar_revision is None:
            require_authoritative_time_zone(self.db, user_id)
        else:
            try:
                CalendarService(self.db).validate_mutation_context(
                    user_id,
                    payload.calendar_revision,
                    payload.logged_date,
                )
            except Exception:
                self.db.rollback()
                raise
        # Revalidate at the authoritative service boundary for callers that do
        # not arrive through Pydantic request parsing.  A revision check may
        # have opened a transaction, so contract failures must roll it back.
        try:
            normalize_meal(payload.meal_type)
            normalize_note(payload.notes)
            fingerprint = _creation_fingerprint(payload) if payload.client_request_id else None
        except Exception:
            self.db.rollback()
            raise
        if payload.client_request_id is not None:
            existing = self.logs.get_by_client_request_id(user_id, payload.client_request_id)
            if existing is not None:
                return _matching_idempotent_log(existing, fingerprint)
        try:
            # E4-02 mark-Complete serializes through the first Log on a date.
            # Take that same anchor before source locks so a create and a
            # concurrent Complete assertion have one ordering authority.
            self.logs.lock_first_for_dates(user_id, {payload.logged_date})
            try:
                food = self.foods.get_required(payload.food_item_id, user_id)
            except LookupError as exc:
                if _source_precondition_supplied(payload):
                    raise LogSourceUnavailableError(LogSourceUnavailableError.message) from exc
                raise
            if food.is_recipe or food.source_type == "recipe":
                log = self._create_recipe_log(user_id, food, payload)
            else:
                # Mutable Food resolver inputs must be loaded after the Food row
                # lock so servings and nutrients describe one committed generation.
                try:
                    food = self.foods.get_for_update(payload.food_item_id, user_id)
                except LookupError as exc:
                    if _source_precondition_supplied(payload):
                        raise LogSourceUnavailableError(LogSourceUnavailableError.message) from exc
                    raise
                self._after_mutable_food_lock(food)
                log = self._create_food_log(user_id, food, payload)
            log.client_request_id = payload.client_request_id
            log.client_request_fingerprint = fingerprint
            created = self.logs.add(log)
            self._after_snapshot_creation(created)
            if payload.calendar_revision is not None:
                CalendarService(self.db).validate_mutation_context(
                    user_id,
                    payload.calendar_revision,
                    created.logged_date,
                )
            self._invalidate_complete_dates(user_id, {created.logged_date})
            self.db.commit()
            return created
        except IntegrityError as exc:
            self.db.rollback()
            if payload.client_request_id is None or not _is_idempotency_unique_conflict(exc):
                raise
            existing = self.logs.get_by_client_request_id(user_id, payload.client_request_id)
            if existing is None:
                raise
            return _matching_idempotent_log(existing, fingerprint)
        except Exception:
            self.db.rollback()
            raise

    def _after_mutable_food_lock(self, _food: FoodItem) -> None:
        """Test seam after mutable Food generation lock and child refresh."""

    @staticmethod
    def _validate_food_source_precondition(
        food: FoodItem,
        payload: DailyLogCreateRequest | DailyLogUpdateRequest,
    ) -> None:
        """Validate a reviewed mutable Food generation after its row is locked."""

        if payload.source_recipe_publication_revision_id is not None:
            raise LogSourceChangedError(LogSourceChangedError.message)
        if payload.amount_unit == "serving":
            if payload.serving_definition_id is None or not any(
                serving.id == payload.serving_definition_id
                for serving in food.serving_definitions
            ):
                if _source_precondition_supplied(payload):
                    raise LogSourceAmountChangedError(LogSourceAmountChangedError.message)
        if (
            payload.source_food_updated_at is not None
            and not _same_timestamp(food.updated_at, payload.source_food_updated_at)
        ):
            raise LogSourceChangedError(LogSourceChangedError.message)

    def _create_food_log(
        self,
        user_id: UUID,
        food: FoodItem,
        payload: DailyLogCreateRequest,
    ) -> DailyLog:
        self._validate_food_source_precondition(food, payload)
        try:
            resolved = resolve_nutrition(
                food,
                payload.amount_quantity,
                payload.amount_unit,
                payload.serving_definition_id,
            )
        except (AmbiguousNutrientBasisError, UnsupportedNutritionAmountError) as exc:
            if _source_precondition_supplied(payload):
                raise LogSourceAmountChangedError(LogSourceAmountChangedError.message) from exc
            raise
        log = DailyLog(
            id=uuid4(),
            user_id=user_id,
            food_item_id=food.id,
            food_name_snapshot=food.name,
            logged_date=payload.logged_date,
            meal_type=normalize_meal(payload.meal_type),
            amount_quantity=payload.amount_quantity,
            amount_unit=payload.amount_unit,
            serving_definition_id=(
                resolved.amount.serving_definition.id
                if resolved.amount.serving_definition is not None
                else None
            ),
            gram_amount=resolved.amount.gram_amount,
            package_fraction=None,
            notes=normalize_note(payload.notes),
        )
        log.snapshots = build_log_snapshots(food, resolved)
        return log

    def _create_recipe_log(
        self,
        user_id: UUID,
        selected_food: FoodItem,
        payload: DailyLogCreateRequest,
    ) -> DailyLog:
        # Recipe publication uses the repository-wide Food-then-Recipe lock
        # order.  Re-read the compatibility projection under its row lock
        # before deriving the Recipe identity so a concurrent publication or
        # mutable Food update cannot mix projection and revision generations.
        try:
            selected_food = self.foods.get_for_update(payload.food_item_id, user_id)
        except LookupError as exc:
            if _source_precondition_supplied(payload):
                raise LogSourceUnavailableError(LogSourceUnavailableError.message) from exc
            raise
        if not selected_food.is_recipe or selected_food.source_type != "recipe":
            if _source_precondition_supplied(payload):
                raise LogSourceUnavailableError(LogSourceUnavailableError.message)
            raise ValueError("Selected food is not a valid Recipe compatibility projection")
        if selected_food.source_id is None:
            if _source_precondition_supplied(payload):
                raise LogSourceUnavailableError(LogSourceUnavailableError.message)
            raise ValueError("Recipe compatibility projection has no source identity")
        try:
            recipe_id = UUID(selected_food.source_id)
        except ValueError as exc:
            if _source_precondition_supplied(payload):
                raise LogSourceUnavailableError(LogSourceUnavailableError.message) from exc
            raise ValueError("Recipe compatibility projection has invalid source identity") from exc

        try:
            recipe = self.recipes.get_for_update(recipe_id, user_id)
        except LookupError as exc:
            if _source_precondition_supplied(payload):
                raise LogSourceUnavailableError(LogSourceUnavailableError.message) from exc
            raise
        food = selected_food
        if (
            not food.is_recipe
            or food.source_type != "recipe"
            or recipe.published_food_item_id != food.id
            or food.source_id != str(recipe.id)
            or food.recipe_publication_revision_id is None
            or recipe.active_publication_revision_id is None
            or food.recipe_publication_revision_id != recipe.active_publication_revision_id
        ):
            if _source_precondition_supplied(payload):
                raise LogSourceUnavailableError(LogSourceUnavailableError.message)
            raise ValueError(
                "Recipe compatibility projection is not linked to its active publication"
            )

        if (
            payload.source_recipe_publication_revision_id is not None
            and payload.source_recipe_publication_revision_id
            != recipe.active_publication_revision_id
        ):
            raise LogSourceChangedError(LogSourceChangedError.message)
        if (
            payload.source_food_updated_at is not None
            and not _same_timestamp(food.updated_at, payload.source_food_updated_at)
        ):
            raise LogSourceChangedError(LogSourceChangedError.message)

        try:
            revision = self.publications.get_required(
                recipe.active_publication_revision_id,
                user_id,
            )
        except LookupError as exc:
            if _source_precondition_supplied(payload):
                raise LogSourceUnavailableError(LogSourceUnavailableError.message) from exc
            raise
        if revision.recipe_id != recipe.id:
            if _source_precondition_supplied(payload):
                raise LogSourceUnavailableError(LogSourceUnavailableError.message)
            raise ValueError("Active publication does not belong to the selected Recipe")
        self._after_recipe_revision_lookup(revision)
        try:
            selection = map_projection_log_amount(
                food,
                revision,
                payload.amount_unit,
                payload.serving_definition_id,
            )
        except (AmbiguousNutrientBasisError, UnsupportedNutritionAmountError, ValueError) as exc:
            if _source_precondition_supplied(payload):
                raise LogSourceAmountChangedError(LogSourceAmountChangedError.message) from exc
            raise
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
            meal_type=normalize_meal(payload.meal_type),
            amount_quantity=resolved.entered_quantity,
            amount_unit=resolved.semantic_amount_mode,
            serving_definition_id=compatibility_serving_id,
            recipe_publication_revision_id=revision.id,
            recipe_publication_amount_definition_id=selection.revision_amount.id,
            gram_amount=resolved.resolved_grams,
            package_fraction=None,
            notes=normalize_note(payload.notes),
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
        calendar = CalendarService(self.db).state(user_id)
        if calendar.today is not None and logged_date > calendar.today:
            return []
        return self.logs.list_for_date(user_id, logged_date)

    def list_future_entries(self, user_id: UUID, logged_date: date) -> list[DailyLog]:
        """Return owner-scoped legacy rows on one future date.

        Future dates are a cleanup-only read surface.  Once the authoritative
        calendar is available, ordinary Daily Log reads intentionally return no
        rows for those dates; this endpoint is the explicit discovery path for
        rows written before that rule existed.
        """
        calendar = CalendarService(self.db).state(user_id)
        if calendar.today is None:
            raise AuthoritativeTimeZoneRequiredError()
        if logged_date <= calendar.today:
            return []
        return self.logs.list_for_date(user_id, logged_date)

    def list_recent_entries(self, user_id: UUID) -> list[dict[str, object]]:
        """Return the ten newest eligible historical intents for Repeat.

        Eligibility is evaluated against the owner's authoritative calendar and
        current source projection by the repository query.  This read never
        reconstructs or mutates historical snapshots; the normal create-log
        operation remains the authority when a user confirms a Repeat.
        """
        calendar = CalendarService(self.db).state(user_id)
        if calendar.today is None:
            raise AuthoritativeTimeZoneRequiredError()
        entries = self.logs.list_recent_entries(user_id, calendar.today, limit=None)
        eligible: list[dict[str, object]] = []
        for entry in entries:
            response = self._recent_entry_response(user_id, entry)
            if not response["current_source_loggable"]:
                continue
            eligible.append(response)
            if len(eligible) == 10:
                break
        return eligible

    def _recent_entry_response(self, user_id: UUID, entry: DailyLog) -> dict[str, object]:
        """Project one historical event plus an authoritative current reuse decision."""

        food = entry.food_item
        if food is None:
            reuse = self._unavailable_reuse(False)
            current_revision_id = None
        elif food.is_recipe or food.source_type == "recipe":
            reuse, current_revision_id = self._recipe_reuse(user_id, entry, food)
        else:
            reuse = self._food_reuse(entry, food)
            current_revision_id = None

        note_reference = entry.notes if isinstance(entry.notes, str) and entry.notes.strip() else None
        note_copy_allowed = bool(
            note_reference is not None
            and len(note_reference) <= MAX_NOTE_CODE_POINTS
        )
        historical_label = reuse.pop("historical_serving_label", None)
        return {
            "id": entry.id,
            "food_item_id": entry.food_item_id,
            "food_name_snapshot": entry.food_name_snapshot,
            "logged_date": entry.logged_date,
            "meal_type": entry.meal_type,
            "amount_quantity": entry.amount_quantity,
            "amount_unit": entry.amount_unit,
            "serving_definition_id": entry.serving_definition_id,
            "recipe_publication_revision_id": entry.recipe_publication_revision_id,
            "recipe_publication_amount_definition_id": entry.recipe_publication_amount_definition_id,
            "historical_serving_label": historical_label,
            "notes": entry.notes,
            "note_present": note_reference is not None,
            "note_reference": note_reference,
            "note_copy_allowed": note_copy_allowed,
            "created_at": entry.created_at,
            "source_food_updated_at": food.updated_at if food is not None else None,
            "source_recipe_publication_revision_id": current_revision_id,
            **reuse,
        }

    @staticmethod
    def _same_decimal(left: Decimal | None, right: Decimal | None) -> bool:
        if left is None or right is None:
            return left is right
        return left.normalize() == right.normalize()

    @classmethod
    def _food_is_loggable(cls, food: FoodItem) -> bool:
        try:
            if resolve_food_amount_definitions(food):
                return True
        except NutritionResolutionError:
            # A serving choice may be ambiguous or unsupported while the
            # source still authoritatively supports direct gram logging.
            # Check that independent mode before declaring the source unusable.
            pass
        try:
            resolve_nutrition(food, Decimal("1"), "g")
            return True
        except NutritionResolutionError:
            return False

    @classmethod
    def _food_reuse(cls, entry: DailyLog, food: FoodItem) -> dict[str, object]:
        current_loggable = cls._food_is_loggable(food)
        if not current_loggable:
            return cls._unavailable_reuse(False)

        if entry.amount_unit == "g":
            try:
                resolved = resolve_nutrition(food, entry.amount_quantity, "g")
            except NutritionResolutionError:
                return cls._unavailable_reuse(True)
            return {
                "current_source_loggable": True,
                "current_amount_unit": "g",
                "current_amount_definition_id": resolved.amount_definition_id,
                "current_amount_label": resolved.display_label,
                "reuse_status": "exact",
                "historical_serving_label": None,
            }

        historical_serving = next(
            (serving for serving in food.serving_definitions if serving.id == entry.serving_definition_id),
            None,
        )
        if historical_serving is not None:
            try:
                resolved = resolve_nutrition(
                    food,
                    entry.amount_quantity,
                    "serving",
                    historical_serving.id,
                )
            except NutritionResolutionError:
                return cls._unavailable_reuse(True)
            return {
                "current_source_loggable": True,
                "current_amount_unit": "serving",
                "current_amount_definition_id": resolved.amount_definition_id,
                "current_amount_label": historical_serving.label,
                "reuse_status": "exact",
                "historical_serving_label": historical_serving.label,
            }

        # A deleted ServingDefinition leaves no authoritative quantity/unit
        # semantics on DailyLog.  Gram weight alone is insufficient to prove
        # equivalence, so preserve eligibility while requiring reselection.
        return cls._unavailable_reuse(True)

    def _recipe_reuse(
        self,
        user_id: UUID,
        entry: DailyLog,
        food: FoodItem,
    ) -> tuple[dict[str, object], UUID | None]:
        try:
            recipe_id = UUID(food.source_id or "")
            recipe = self.recipes.get_required(recipe_id, user_id)
            revision_id = recipe.active_publication_revision_id
            if revision_id is None or food.recipe_publication_revision_id != revision_id:
                return self._unavailable_reuse(False), None
            revision = self.publications.get_required(revision_id, user_id)
        except (LookupError, ValueError):
            return self._unavailable_reuse(False), None

        current_amounts = list(revision.amount_definitions)
        loggable_amounts = [
            amount for amount in current_amounts if self._revision_amount_is_loggable(revision, amount)
        ]
        if not loggable_amounts:
            return self._unavailable_reuse(False), revision.id

        historical_revision = None
        if entry.recipe_publication_revision_id is not None:
            historical_revision = self.publications.get(
                entry.recipe_publication_revision_id,
                user_id,
            )
        historical_amount = next(
            (
                amount
                for amount in historical_revision.amount_definitions
                if amount.id == entry.recipe_publication_amount_definition_id
            ),
            None,
        ) if historical_revision is not None and entry.recipe_publication_amount_definition_id else None

        if historical_amount is None:
            return {
                **self._unavailable_reuse(True),
                "historical_serving_label": None,
            }, revision.id

        exact = next((amount for amount in loggable_amounts if amount.id == historical_amount.id), None)
        if exact is not None:
            return {
                "current_source_loggable": True,
                "current_amount_unit": exact.semantic_mode,
                "current_amount_definition_id": exact.id,
                "current_amount_label": exact.display_label,
                "reuse_status": "exact",
                "historical_serving_label": historical_amount.display_label,
            }, revision.id

        candidates = [
            amount for amount in loggable_amounts
            if amount.semantic_mode == historical_amount.semantic_mode
            and self._same_decimal(amount.display_quantity, historical_amount.display_quantity)
            and amount.display_unit.strip().casefold() == historical_amount.display_unit.strip().casefold()
            and self._same_decimal(amount.gram_equivalent, historical_amount.gram_equivalent)
        ]
        if len(candidates) != 1:
            return {
                "current_source_loggable": True,
                "current_amount_unit": None,
                "current_amount_definition_id": None,
                "current_amount_label": None,
                "reuse_status": "ambiguous" if len(candidates) > 1 else "unavailable",
                "historical_serving_label": historical_amount.display_label,
            }, revision.id
        successor = candidates[0]
        return {
            "current_source_loggable": True,
            "current_amount_unit": successor.semantic_mode,
            "current_amount_definition_id": successor.id,
            "current_amount_label": successor.display_label,
            "reuse_status": "equivalent",
            "historical_serving_label": historical_amount.display_label,
        }, revision.id

    @staticmethod
    def _revision_amount_is_loggable(revision, amount) -> bool:
        try:
            resolve_revision_nutrition(
                revision,
                amount.id,
                Decimal("1"),
                semantic_amount_mode=amount.semantic_mode,
            )
            return True
        except NutritionResolutionError:
            return False

    @staticmethod
    def _unavailable_reuse(source_loggable: bool) -> dict[str, object]:
        return {
            "current_source_loggable": source_loggable,
            "current_amount_unit": None,
            "current_amount_definition_id": None,
            "current_amount_label": None,
            "reuse_status": "unavailable",
            "historical_serving_label": None,
        }

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
            # A corrupt or retired historical publication must not make the
            # metadata-only edit surface unusable. There is no honest
            # historical amount list to present, so expose the saved identity
            # as display-only and explicitly mark current nutrition authority
            # unavailable.
            return DailyLogEditContextResponse(
                log_id=log.id,
                source_food_available=log.source_food_available,
                is_revision_backed=True,
                recipe_publication_revision_id=revision_id,
                selected_amount_definition_id=log.recipe_publication_amount_definition_id,
                amount_choices=[],
                current_source_food_updated_at=(
                    log.food_item.updated_at
                    if log.food_item is not None and log.food_item.user_id == user_id
                    else None
                ),
                current_source_loggable=False,
                current_amount_choices=[],
            )
        selected_id = log.recipe_publication_amount_definition_id
        stored_amount = next(
            (amount for amount in revision.amount_definitions if amount.id == selected_id),
            None,
        )
        if stored_amount is None:
            return DailyLogEditContextResponse(
                log_id=log.id,
                source_food_available=log.source_food_available,
                is_revision_backed=True,
                recipe_publication_revision_id=revision.id,
                selected_amount_definition_id=selected_id,
                amount_choices=[],
                current_source_food_updated_at=(
                    log.food_item.updated_at
                    if log.food_item is not None and log.food_item.user_id == user_id
                    else None
                ),
                current_source_loggable=False,
                current_amount_choices=[],
            )
        context = DailyLogEditContextResponse(
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
        food = log.food_item
        if food is None or food.source_id is None:
            context.current_source_food_updated_at = (
                food.updated_at if food is not None and food.user_id == user_id else None
            )
            context.current_source_loggable = False
            context.current_amount_choices = []
            return context
        if food.user_id != user_id or food.deleted_at is not None:
            context.current_source_food_updated_at = food.updated_at
            context.current_source_loggable = False
            context.current_amount_choices = []
            return context

        # E1-13 reviews the current active Recipe revision. Keep the stored
        # revision choices above for historical presentation and compatibility,
        # while exposing a separate current choice set for the edit surface.
        try:
            recipe_id = UUID(food.source_id)
            recipe = self.recipes.get(recipe_id, user_id)
        except (TypeError, ValueError):
            recipe = None
        current_revision = None
        if (
            recipe is not None
            and recipe.deleted_at is None
            and recipe.active_publication_revision_id is not None
            and food.recipe_publication_revision_id == recipe.active_publication_revision_id
        ):
            current_revision = self.publications.get(
                recipe.active_publication_revision_id,
                user_id,
            )

        if current_revision is None:
            context.current_source_food_updated_at = food.updated_at
            context.current_source_loggable = False
            context.current_amount_choices = []
            return context

        current_amounts = list(current_revision.amount_definitions)
        current_loggable = [
            amount
            for amount in current_amounts
            if self._revision_amount_is_loggable(current_revision, amount)
        ]
        exact = next((amount for amount in current_loggable if amount.id == stored_amount.id), None)
        equivalent = [
            amount
            for amount in current_loggable
            if amount.semantic_mode == stored_amount.semantic_mode
            and self._same_decimal(amount.display_quantity, stored_amount.display_quantity)
            and amount.display_unit.strip().casefold() == stored_amount.display_unit.strip().casefold()
            and self._same_decimal(amount.gram_equivalent, stored_amount.gram_equivalent)
        ]
        selected_current = exact if exact is not None else equivalent[0] if len(equivalent) == 1 else None
        context.current_source_food_updated_at = food.updated_at
        context.current_recipe_publication_revision_id = current_revision.id
        context.current_source_loggable = bool(current_loggable)
        context.current_selected_amount_definition_id = selected_current.id if selected_current else None
        context.current_amount_choices = [
            DailyLogEditAmountResponse(
                amount_definition_id=amount.id,
                display_label=amount.display_label,
                semantic_mode=amount.semantic_mode,
                display_quantity=amount.display_quantity,
                display_unit=amount.display_unit,
                gram_equivalent=amount.gram_equivalent,
                is_default=amount.is_default,
                is_selected=amount.id == (selected_current.id if selected_current else None),
            )
            for amount in current_loggable
        ]
        return context

    def _find_mutation_receipt(
        self,
        user_id: UUID,
        operation: str,
        client_request_id: UUID,
        fingerprint: str,
    ):
        try:
            return self.mutation_receipts.find(
                user_id,
                operation,
                client_request_id,
                fingerprint,
            )
        except CreateOperationIdempotencyConflictError as exc:
            raise LogMutationPayloadConflictError(LogMutationPayloadConflictError.message) from exc

    def _replay_mutation_receipt(self, receipt) -> LogMutationReplay:
        try:
            snapshot = self.mutation_receipts.replay_snapshot(receipt)
        except CreateOperationResultUnavailableError as exc:
            raise LogMutationResultUnavailableError(LogMutationResultUnavailableError.message) from exc
        return LogMutationReplay(snapshot, receipt.resource_id)

    @staticmethod
    def _update_response_snapshot(log: DailyLog, source_logged_date: date) -> dict:
        snapshot = DailyLogResponse.model_validate(log).model_dump(mode="json")
        # Keep move reconciliation self-contained without changing the public
        # DailyLog response shape. Pydantic ignores these private receipt keys
        # when the replay is returned through the normal update endpoint.
        snapshot["_source_logged_date"] = source_logged_date.isoformat()
        snapshot["_destination_logged_date"] = log.logged_date.isoformat()
        return snapshot

    def _mutation_status(
        self,
        user_id: UUID,
        operation: str,
        client_request_id: UUID,
    ) -> DailyLogMutationStatusResponse:
        """Read a receipt without changing domain state.

        A missing receipt is a confirmed non-commit under the transaction model:
        reservations and domain writes commit atomically, so no row means the
        intent did not commit. An incomplete row is retained as unresolved.
        """

        if operation == "create":
            log = self.logs.get_by_client_request_id(user_id, client_request_id)
            return DailyLogMutationStatusResponse(
                operation=operation,
                client_request_id=client_request_id,
                status="confirmed_success" if log is not None else "confirmed_non_commit",
                log_id=log.id if log is not None else None,
                result=DailyLogResponse.model_validate(log) if log is not None else None,
            )

        receipt = self.db.scalar(
            select(CreateOperationIdempotency).where(
                CreateOperationIdempotency.user_id == user_id,
                CreateOperationIdempotency.operation == f"log.{operation}",
                CreateOperationIdempotency.client_request_id == client_request_id,
            )
        )
        if receipt is None:
            return DailyLogMutationStatusResponse(
                operation=operation,
                client_request_id=client_request_id,
                status="confirmed_non_commit",
            )
        if receipt.response_snapshot is None or receipt.completed_at is None:
            return DailyLogMutationStatusResponse(
                operation=operation,
                client_request_id=client_request_id,
                status="unresolved",
                log_id=receipt.resource_id,
            )
        if operation == "update":
            result = DailyLogResponse.model_validate(receipt.response_snapshot)
            return DailyLogMutationStatusResponse(
                operation=operation,
                client_request_id=client_request_id,
                status="confirmed_success",
                log_id=receipt.resource_id,
                source_logged_date=_parse_receipt_date(
                    receipt.response_snapshot.get("_source_logged_date")
                ),
                destination_logged_date=_parse_receipt_date(
                    receipt.response_snapshot.get("_destination_logged_date")
                ),
                result=result,
            )
        return DailyLogMutationStatusResponse(
            operation=operation,
            client_request_id=client_request_id,
            status="confirmed_success",
            log_id=receipt.resource_id,
        )

    def mutation_status(
        self,
        user_id: UUID,
        client_request_id: UUID,
        operation: str | None = None,
    ) -> DailyLogMutationStatusResponse:
        """Return owner-scoped status for create, update, or delete intent."""

        normalized = {
            "log.create": "create",
            "log.update": "update",
            "log.edit": "update",
            "log.move": "update",
            "log.delete": "delete",
            "edit": "update",
            "move": "update",
        }.get(operation or "", operation or "")
        if normalized not in {"create", "update", "delete"}:
            # A request identity is normally unique within one operation. If
            # callers omit operation, prefer an existing terminal record in a
            # stable order and otherwise report a non-commit create status.
            create = self._mutation_status(user_id, "create", client_request_id)
            if create.status == "confirmed_success":
                return create
            for candidate in ("update", "delete"):
                status = self._mutation_status(user_id, candidate, client_request_id)
                if status.status != "confirmed_non_commit":
                    return status
            return create
        return self._mutation_status(user_id, normalized, client_request_id)

    def update_log(
        self,
        user_id: UUID,
        log_id: UUID,
        payload: DailyLogUpdateRequest,
    ) -> DailyLog | LogMutationReplay:
        """Edit one DailyLog with a receipt and locked optimistic precondition."""
        if payload.calendar_revision is None:
            require_authoritative_time_zone(self.db, user_id)
        if "meal_type" in payload.model_fields_set:
            normalize_meal(payload.meal_type)
        if "notes" in payload.model_fields_set:
            normalize_note(payload.notes)
        fingerprint = (
            _mutation_fingerprint("log.update", log_id, payload)
            if payload.client_request_id is not None
            else None
        )
        try:
            receipt = None
            if payload.client_request_id is not None:
                receipt = self._find_mutation_receipt(
                    user_id,
                    "log.update",
                    payload.client_request_id,
                    fingerprint,
                )
                if receipt is not None:
                    return self._replay_mutation_receipt(receipt)
            try:
                log = self.logs.get_for_update(log_id, user_id)
            except LookupError as exc:
                if payload.expected_updated_at is not None:
                    raise StaleLogMutationError(StaleLogMutationError.message) from exc
                raise
            # A concurrent identical request may have waited on the row lock
            # while the first request committed its receipt. Recheck before
            # applying the stale precondition so it replays that outcome.
            if payload.client_request_id is not None:
                receipt = self._find_mutation_receipt(
                    user_id,
                    "log.update",
                    payload.client_request_id,
                    fingerprint,
                )
                if receipt is not None:
                    return self._replay_mutation_receipt(receipt)
            if (
                payload.expected_updated_at is not None
                and not _same_timestamp(log.updated_at, payload.expected_updated_at)
            ):
                raise StaleLogMutationError(StaleLogMutationError.message)
            source_logged_date = log.logged_date
            destination_logged_date = (
                payload.logged_date if payload.logged_date is not None else source_logged_date
            )
            self.logs.lock_first_for_dates(
                user_id,
                {source_logged_date, destination_logged_date},
            )
            before_snapshot_signature = _snapshot_signature(log)
            if payload.client_request_id is not None:
                try:
                    receipt = self.mutation_receipts.reserve(
                        user_id,
                        "log.update",
                        payload.client_request_id,
                        fingerprint,
                        log.id,
                    )
                except IntegrityError:
                    # A concurrent identical request may have committed while
                    # this transaction waited for the entry lock.
                    self.db.rollback()
                    receipt = self._find_mutation_receipt(
                        user_id,
                        "log.update",
                        payload.client_request_id,
                        fingerprint,
                    )
                    if receipt is None:
                        raise
                    return self._replay_mutation_receipt(receipt)
            if payload.calendar_revision is not None:
                CalendarService(self.db).validate_mutation_context(
                    user_id,
                    payload.calendar_revision,
                    destination_logged_date,
                )
            if log.recipe_publication_revision_id is not None:
                self._update_revision_aware_log(user_id, log, payload)
            else:
                self._update_compatibility_log(user_id, log, payload)
            if payload.calendar_revision is not None:
                CalendarService(self.db).validate_mutation_context(
                    user_id,
                    payload.calendar_revision,
                    log.logged_date,
                )
            self.db.flush()
            after_snapshot_signature = _snapshot_signature(log)
            invalidation_dates: set[date] = set()
            if source_logged_date != log.logged_date:
                invalidation_dates.update({source_logged_date, log.logged_date})
            elif before_snapshot_signature != after_snapshot_signature:
                invalidation_dates.add(log.logged_date)
            self._invalidate_complete_dates(user_id, invalidation_dates)
            # Serialize the same refreshed ORM view that will be returned after
            # commit, so an exact replay is wire-equivalent to the first result.
            self.db.expire(log)
            response_snapshot = self._update_response_snapshot(
                self.logs.get_required(log.id, user_id),
                source_logged_date,
            )
            if receipt is not None:
                self.mutation_receipts.complete(receipt, response_snapshot)
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
        nutritional_edit = (
            payload.amount_quantity is not None
            or payload.amount_unit is not None
            or "serving_definition_id" in payload.model_fields_set
        )
        if not log.is_editable:
            if log.food_item is not None and log.food_item.user_id != user_id:
                raise LogEditConflictError(LogEditConflictError.message)
            if nutritional_edit:
                raise LogEditConflictError(LogEditConflictError.message)
            # A deleted mutable source still permits explicit metadata and
            # date corrections; it cannot be used to regenerate nutrition.
            self._apply_log_metadata(log, payload)
            log.updated_at = datetime.now(timezone.utc)
            return
        # No mutation path locks an existing DailyLog after holding its Food.
        # Keep explicit edits in DailyLog-then-Food order and refresh all Food
        # children under that lock so serving and nutrient inputs are coherent.
        food = self.foods.get_for_update(log.food_item_id, user_id)
        self._after_edit_mutable_food_lock(food)
        if _source_precondition_supplied(payload):
            self._validate_food_source_precondition(food, payload)
        if not nutritional_edit:
            self._apply_log_metadata(log, payload)
            log.updated_at = datetime.now(timezone.utc)
            return
        amount_quantity = (
            payload.amount_quantity if payload.amount_quantity is not None else log.amount_quantity
        )
        amount_unit = payload.amount_unit if payload.amount_unit is not None else log.amount_unit
        serving_definition_id = (
            payload.serving_definition_id
            if "serving_definition_id" in payload.model_fields_set
            else log.serving_definition_id
        )
        # Manual Food and legacy Recipe logs intentionally retain their existing
        # mutable-source compatibility behavior.
        try:
            resolved = resolve_nutrition(food, amount_quantity, amount_unit, serving_definition_id)
        except (AmbiguousNutrientBasisError, UnsupportedNutritionAmountError) as exc:
            if _source_precondition_supplied(payload):
                raise LogSourceAmountChangedError(LogSourceAmountChangedError.message) from exc
            raise

        with self.logs.snapshot_replacement_scope(user_id, log.id):
            self.logs.delete_snapshots(log.id, user_id)
            # The approved PostgreSQL routine deletes the rows outside the
            # ORM unit-of-work. Reload the relationship before installing the
            # replacement generation so SQLAlchemy does not delete them twice.
            self.db.expire(log, ["snapshots"])
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
            self.db.flush()
            self._after_edit_snapshot_regeneration(log)

    def _update_revision_aware_log(
        self,
        user_id: UUID,
        log: DailyLog,
        payload: DailyLogUpdateRequest,
    ) -> None:
        nutritional_edit = (
            payload.amount_quantity is not None
            or payload.amount_unit is not None
            or "serving_definition_id" in payload.model_fields_set
        )

        # Metadata and valid date corrections do not reconstruct nutrition. They
        # therefore remain available for an owned historical entry even when
        # its current compatibility projection or Recipe is gone. Ownership is
        # still checked before taking this compatibility path.
        if log.food_item is not None and log.food_item.user_id != user_id:
            raise RecipeNutritionValidationError(
                "recipe_log_source_food_unavailable",
                "This entry's source food is no longer available.",
            )

        if not nutritional_edit:
            self._apply_log_metadata(log, payload)
            log.updated_at = datetime.now(timezone.utc)
            return

        # Nutrition edits always use the current authoritative Recipe source.
        # Hold shared Food-then-Recipe authority locks: edits to different
        # DailyLogs may read the same publication generation concurrently,
        # while publication and source mutation still require exclusive locks.
        try:
            source_food = self.foods.get_for_share(log.food_item_id, user_id)
            if (
                source_food.deleted_at is not None
                or not source_food.is_recipe
                or source_food.source_type != "recipe"
                or source_food.source_id is None
            ):
                raise LogSourceUnavailableError(LogSourceUnavailableError.message)
            recipe = self.recipes.get_for_share(UUID(source_food.source_id), user_id)
            if (
                recipe.deleted_at is not None
                or recipe.published_food_item_id != source_food.id
                or source_food.recipe_publication_revision_id is None
                or recipe.active_publication_revision_id is None
                or source_food.recipe_publication_revision_id
                != recipe.active_publication_revision_id
            ):
                raise LogSourceUnavailableError(LogSourceUnavailableError.message)
            if (
                payload.source_recipe_publication_revision_id is not None
                and payload.source_recipe_publication_revision_id
                != recipe.active_publication_revision_id
            ):
                raise LogSourceChangedError(LogSourceChangedError.message)
            if (
                payload.source_food_updated_at is not None
                and not _same_timestamp(source_food.updated_at, payload.source_food_updated_at)
            ):
                raise LogSourceChangedError(LogSourceChangedError.message)
            revision = self.publications.get(
                recipe.active_publication_revision_id,
                user_id,
            )
            if revision is None or revision.recipe_id != recipe.id:
                raise LogSourceUnavailableError(LogSourceUnavailableError.message)
        except (LookupError, ValueError) as exc:
            if isinstance(exc, (LogSourceChangedError, LogSourceUnavailableError)):
                raise
            raise LogSourceUnavailableError(LogSourceUnavailableError.message) from exc

        stored_revision = self.publications.get(log.recipe_publication_revision_id, user_id)
        if stored_revision is None:
            raise RecipeNutritionValidationError(
                "recipe_log_revision_missing",
                "This entry's publication revision is no longer available.",
            )

        self._after_edit_revision_lookup(revision)
        stored_amount = next(
            (
                amount
                for amount in stored_revision.amount_definitions
                if amount.id == log.recipe_publication_amount_definition_id
            ),
            None,
        )
        if stored_amount is None:
            raise RecipeNutritionValidationError(
                "recipe_log_amount_definition_missing",
                "This entry's saved amount is no longer available in its publication revision.",
            )

        if not nutritional_edit:
            self._apply_log_metadata(log, payload)
            log.updated_at = datetime.now(timezone.utc)
            return

        amount_quantity = (
            payload.amount_quantity if payload.amount_quantity is not None else log.amount_quantity
        )
        amount_unit = payload.amount_unit if payload.amount_unit is not None else log.amount_unit
        if revision.id != stored_revision.id:
            current_amounts = list(revision.amount_definitions)
            selected_amount = self._select_current_revision_edit_amount(
                log,
                current_amounts,
                stored_amount,
                payload,
                amount_unit,
            )
        else:
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

        projection_selection = map_projection_log_amount(
            source_food,
            revision,
            amount_unit,
            selected_amount.id,
        )
        compatibility_serving_id = (
            projection_selection.compatibility_serving.id
            if projection_selection.compatibility_serving is not None
            else None
        )
        with self.logs.snapshot_replacement_scope(user_id, log.id):
            self.logs.delete_snapshots(log.id, user_id)
            # The approved PostgreSQL routine deletes the rows outside the
            # ORM unit-of-work. Reload the relationship before installing the
            # replacement generation so SQLAlchemy does not delete them twice.
            self.db.expire(log, ["snapshots"])
            self._apply_log_metadata(log, payload)
            log.amount_quantity = resolved.entered_quantity
            log.amount_unit = resolved.semantic_amount_mode
            log.serving_definition_id = compatibility_serving_id
            # The replacement snapshots and their publication authority are
            # one atomic generation. Never leave a current snapshot set paired
            # with a historical revision or amount association.
            log.recipe_publication_revision_id = revision.id
            log.recipe_publication_amount_definition_id = selected_amount.id
            log.gram_amount = resolved.resolved_grams
            log.package_fraction = None
            log.updated_at = datetime.now(timezone.utc)
            log.snapshots = build_revision_log_snapshots(
                source_food or log.food_item,
                resolved,
                compatibility_serving_id,
            )
            self.db.flush()
            self._after_edit_snapshot_regeneration(log)

    def _select_current_revision_edit_amount(
        self,
        log: DailyLog,
        current_amounts: list[RecipePublicationAmountDefinition],
        stored_amount: RecipePublicationAmountDefinition,
        payload: DailyLogUpdateRequest,
        amount_unit: str,
    ) -> RecipePublicationAmountDefinition:
        """Select an explicitly reviewed amount from the active revision."""

        amount_unit = amount_unit.strip().lower()
        if "serving_definition_id" in payload.model_fields_set:
            requested_id = payload.serving_definition_id
            if requested_id is None and amount_unit == "g":
                gram_candidates = [
                    amount for amount in current_amounts if amount.semantic_mode == "g"
                ]
                if len(gram_candidates) == 1:
                    return gram_candidates[0]
            selected = next(
                (
                    amount
                    for amount in current_amounts
                    if amount.id == requested_id and amount.semantic_mode == amount_unit
                ),
                None,
            )
            if selected is None:
                raise RecipeNutritionValidationError(
                    "recipe_log_serving_not_in_revision",
                    "The selected amount is not available in the active publication revision.",
                )
            return selected

        candidates = [
            amount for amount in current_amounts
            if amount.semantic_mode == amount_unit
            and amount.semantic_mode == stored_amount.semantic_mode
            and self._same_decimal(amount.display_quantity, stored_amount.display_quantity)
            and amount.display_unit.strip().casefold() == stored_amount.display_unit.strip().casefold()
            and self._same_decimal(amount.gram_equivalent, stored_amount.gram_equivalent)
        ]
        if len(candidates) != 1:
            raise RecipeNutritionValidationError(
                "recipe_log_conversion_unsupported",
                "Choose a current amount before saving this edit.",
            )
        return candidates[0]

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
                if amount.semantic_mode == amount_unit and (amount_unit == "g" or amount.is_default)
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
        log.logged_date = (
            payload.logged_date if payload.logged_date is not None else log.logged_date
        )
        if "meal_type" in payload.model_fields_set:
            log.meal_type = normalize_meal(payload.meal_type)
        if "notes" in payload.model_fields_set:
            log.notes = normalize_note(payload.notes)

    def _after_edit_revision_lookup(self, _revision: RecipePublicationRevision) -> None:
        """Test seam after the stored revision is loaded."""

    def _after_edit_amount_lookup(self, _amount: RecipePublicationAmountDefinition) -> None:
        """Test seam after the stored revision amount is selected."""

    def _after_edit_snapshot_regeneration(self, _log: DailyLog) -> None:
        """Test seam after replacement snapshots are flushed."""

    def _after_edit_mutable_food_lock(self, _food: FoodItem) -> None:
        """Test seam after an explicit edit locks its mutable Food generation."""

    def delete_log(
        self,
        user_id: UUID,
        log_id: UUID,
        payload: DailyLogDeleteRequest | None = None,
    ) -> None | LogMutationReplay:
        """Delete one DailyLog exactly once, subject to its read precondition."""
        intent = payload or DailyLogDeleteRequest()
        if intent.calendar_revision is None:
            require_authoritative_time_zone(self.db, user_id)
        fingerprint = (
            _mutation_fingerprint("log.delete", log_id, intent)
            if intent.client_request_id is not None
            else None
        )
        try:
            receipt = None
            if intent.client_request_id is not None:
                receipt = self._find_mutation_receipt(
                    user_id,
                    "log.delete",
                    intent.client_request_id,
                    fingerprint,
                )
                if receipt is not None:
                    return self._replay_mutation_receipt(receipt)
            try:
                # Serialize deletes with edits and other deletes using the
                # established owned-row lock path before checking the
                # precondition or reserving a replay receipt.
                log = self.logs.get_for_update(log_id, user_id)
            except LookupError as exc:
                if intent.client_request_id is not None:
                    receipt = self._find_mutation_receipt(
                        user_id,
                        "log.delete",
                        intent.client_request_id,
                        fingerprint,
                    )
                    if receipt is not None:
                        return self._replay_mutation_receipt(receipt)
                if intent.expected_updated_at is not None:
                    raise StaleLogMutationError(StaleLogMutationError.message) from exc
                raise
            if intent.client_request_id is not None:
                receipt = self._find_mutation_receipt(
                    user_id,
                    "log.delete",
                    intent.client_request_id,
                    fingerprint,
                )
                if receipt is not None:
                    return self._replay_mutation_receipt(receipt)
            if (
                intent.expected_updated_at is not None
                and not _same_timestamp(log.updated_at, intent.expected_updated_at)
            ):
                raise StaleLogMutationError(StaleLogMutationError.message)
            source_logged_date = log.logged_date
            self.logs.lock_first_for_dates(user_id, {source_logged_date})
            if intent.calendar_revision is not None:
                CalendarService(self.db).validate_delete_context(
                    user_id,
                    intent.calendar_revision,
                )
            if intent.client_request_id is not None:
                try:
                    receipt = self.mutation_receipts.reserve(
                        user_id,
                        "log.delete",
                        intent.client_request_id,
                        fingerprint,
                        log.id,
                    )
                except IntegrityError:
                    self.db.rollback()
                    receipt = self._find_mutation_receipt(
                        user_id,
                        "log.delete",
                        intent.client_request_id,
                        fingerprint,
                    )
                    if receipt is None:
                        raise
                    return self._replay_mutation_receipt(receipt)
            self.logs.delete(log, user_id)
            self.db.flush()
            self._after_log_delete_flush(log)
            self._invalidate_complete_dates(user_id, {source_logged_date})
            if receipt is not None:
                self.mutation_receipts.complete(
                    receipt,
                    {"deleted": True, "log_id": str(log.id)},
                )
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise

    def _after_log_delete_flush(self, _log: DailyLog) -> None:
        """Test seam after DailyLog deletion and cascades are flushed."""

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
