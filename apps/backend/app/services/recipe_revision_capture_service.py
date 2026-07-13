from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.domain.nutrition import NutrientBasis, NutrientDataStatus
from app.models.food import FoodItem
from app.models.recipe import Recipe
from app.models.recipe_publication import RecipePublicationRevision
from app.publication.recipe_revision import (
    build_revision,
    content_from_projection,
    revision_content_digest,
)
from app.nutrition.resolution import NutritionResolutionError, resolve_nutrition
from app.repositories.recipe_publication_repository import RecipePublicationRepository

CAPTURE_ORIGIN = "legacy_projection_capture"
CAPTURE_CONFIDENCE = "transition_baseline"


class CaptureCategory(str, Enum):
    ELIGIBLE = "eligible"
    STALE_ELIGIBLE = "stale_eligible"
    ALREADY_MANAGED = "already_managed"
    UNPUBLISHED = "unpublished"
    DELETED_RECIPE = "deleted_recipe"
    DELETED_PROJECTION = "deleted_projection"
    MISSING_PROJECTION = "missing_projection"
    INCONSISTENT_LINKAGE = "inconsistent_linkage"
    AMBIGUOUS = "ambiguous"
    FAILED_VALIDATION = "failed_validation"
    UNEXPECTED_FAILURE = "unexpected_failure"


@dataclass(frozen=True)
class CaptureResult:
    recipe_id: UUID
    user_id: UUID
    category: CaptureCategory
    reason: str
    stale_state_preserved: bool
    proposed_revision_number: int | None = None
    proposed_origin: str | None = None
    proposed_provenance_confidence: str | None = None
    proposed_content_digest: str | None = None
    captured_revision_id: UUID | None = None
    captured: bool = False
    dry_run: bool = True

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["recipe_id"] = str(self.recipe_id)
        payload["user_id"] = str(self.user_id)
        payload["category"] = self.category.value
        if self.captured_revision_id is not None:
            payload["captured_revision_id"] = str(self.captured_revision_id)
        return payload


@dataclass(frozen=True)
class CaptureReport:
    dry_run: bool
    results: tuple[CaptureResult, ...]

    @property
    def counts(self) -> dict[str, int]:
        counts = {category.value: 0 for category in CaptureCategory}
        for result in self.results:
            counts[result.category.value] += 1
        counts.update(
            {
                "total_recipes_inspected": len(self.results),
                "eligible_captures": sum(
                    result.category in {CaptureCategory.ELIGIBLE, CaptureCategory.STALE_ELIGIBLE}
                    for result in self.results
                ),
                "successful_captures": sum(result.captured for result in self.results),
                "stale_captured": sum(
                    result.captured and result.category == CaptureCategory.STALE_ELIGIBLE
                    for result in self.results
                ),
            }
        )
        return counts

    def to_dict(self) -> dict[str, Any]:
        return {
            "dry_run": self.dry_run,
            "counts": self.counts,
            "results": [result.to_dict() for result in self.results],
        }


@dataclass(frozen=True)
class _CaptureProposal:
    revision: RecipePublicationRevision
    revision_number: int
    content_digest: str


@dataclass(frozen=True)
class _Assessment:
    result: CaptureResult
    recipe: Recipe
    projection: FoodItem | None = None
    proposal: _CaptureProposal | None = None


class RecipeRevisionCaptureService:
    """Deliberate, rerunnable transition-baseline capture for legacy Recipe projections."""

    def __init__(self, db: Session):
        self.db = db
        self.revisions = RecipePublicationRepository(db)

    def capture_all(self, *, dry_run: bool = True) -> CaptureReport:
        recipe_ids = list(self.db.scalars(select(Recipe.id).order_by(Recipe.id)).all())
        results = tuple(self.capture_one(recipe_id, dry_run=dry_run) for recipe_id in recipe_ids)
        return CaptureReport(dry_run=dry_run, results=results)

    def capture_one(self, recipe_id: UUID, *, dry_run: bool = True) -> CaptureResult:
        recipe = self._load_recipe(recipe_id, lock=not dry_run)
        if recipe is None:
            raise LookupError("Recipe not found")
        recipe_user_id = recipe.user_id
        stale_state = recipe.needs_republish
        try:
            assessment = self._assess(recipe, dry_run=dry_run, lock=not dry_run)
        except Exception as exc:
            self.db.rollback()
            return CaptureResult(
                recipe_id=recipe_id,
                user_id=recipe_user_id,
                category=CaptureCategory.UNEXPECTED_FAILURE,
                reason=f"classification failed: {type(exc).__name__}",
                stale_state_preserved=stale_state,
                dry_run=dry_run,
            )
        if dry_run or assessment.proposal is None or assessment.projection is None:
            return assessment.result

        revision = assessment.proposal.revision
        try:
            self.revisions.add(revision)
            self._assign_links(assessment.recipe, assessment.projection, revision)
            self.db.flush()
            result = replace(
                assessment.result,
                captured_revision_id=revision.id,
                captured=True,
                dry_run=False,
            )
            self.db.commit()
            return result
        except Exception as exc:
            self.db.rollback()
            return CaptureResult(
                recipe_id=assessment.recipe.id,
                user_id=recipe_user_id,
                category=CaptureCategory.UNEXPECTED_FAILURE,
                reason=f"capture transaction failed: {type(exc).__name__}",
                stale_state_preserved=stale_state,
                proposed_revision_number=assessment.proposal.revision_number,
                proposed_origin=CAPTURE_ORIGIN,
                proposed_provenance_confidence=CAPTURE_CONFIDENCE,
                proposed_content_digest=assessment.proposal.content_digest,
                dry_run=False,
            )

    def _load_recipe(self, recipe_id: UUID, *, lock: bool) -> Recipe | None:
        statement = select(Recipe).where(Recipe.id == recipe_id)
        if lock:
            statement = statement.with_for_update()
        return self.db.scalars(statement).first()

    def _load_projection(self, food_id: UUID, *, lock: bool) -> FoodItem | None:
        statement = (
            select(FoodItem)
            .where(FoodItem.id == food_id)
            .options(
                selectinload(FoodItem.nutrients),
                selectinload(FoodItem.serving_definitions),
                selectinload(FoodItem.sources),
            )
        )
        if lock:
            statement = statement.with_for_update()
        return self.db.scalars(statement).first()

    def _assess(self, recipe: Recipe, *, dry_run: bool, lock: bool) -> _Assessment:
        base = {
            "recipe_id": recipe.id,
            "user_id": recipe.user_id,
            "stale_state_preserved": recipe.needs_republish,
            "dry_run": dry_run,
        }
        if recipe.deleted_at is not None:
            return _Assessment(
                result=CaptureResult(
                    **base,
                    category=CaptureCategory.DELETED_RECIPE,
                    reason="Recipe is soft-deleted",
                ),
                recipe=recipe,
            )

        source_matches = self._source_matches(recipe)
        if recipe.published_food_item_id is None:
            if any(food.deleted_at is None for food in source_matches):
                return _Assessment(
                    result=CaptureResult(
                        **base,
                        category=CaptureCategory.INCONSISTENT_LINKAGE,
                        reason="active generated projection exists but Recipe does not reference it",
                    ),
                    recipe=recipe,
                )
            if source_matches:
                return _Assessment(
                    result=CaptureResult(
                        **base,
                        category=CaptureCategory.DELETED_PROJECTION,
                        reason="only soft-deleted generated projections remain",
                    ),
                    recipe=recipe,
                )
            return _Assessment(
                result=CaptureResult(
                    **base,
                    category=CaptureCategory.UNPUBLISHED,
                    reason="Recipe has no compatibility projection",
                ),
                recipe=recipe,
            )

        projection = self._load_projection(recipe.published_food_item_id, lock=lock)
        if projection is None:
            return _Assessment(
                result=CaptureResult(
                    **base,
                    category=CaptureCategory.MISSING_PROJECTION,
                    reason="referenced compatibility projection is absent",
                ),
                recipe=recipe,
            )
        if projection.deleted_at is not None:
            return _Assessment(
                result=CaptureResult(
                    **base,
                    category=CaptureCategory.DELETED_PROJECTION,
                    reason="referenced compatibility projection is soft-deleted",
                ),
                recipe=recipe,
                projection=projection,
            )

        active_source_matches = [food for food in source_matches if food.deleted_at is None]
        if len(active_source_matches) > 1:
            return self._blocked(
                base,
                recipe,
                projection,
                CaptureCategory.INCONSISTENT_LINKAGE,
                "multiple active generated projections identify this Recipe",
            )
        linkage_reason = self._linkage_inconsistency(recipe, projection)
        if linkage_reason is not None:
            return self._blocked(
                base,
                recipe,
                projection,
                CaptureCategory.INCONSISTENT_LINKAGE,
                linkage_reason,
            )

        managed_reason = self._managed_state(recipe, projection)
        if managed_reason == "consistent":
            managed_revision = self.revisions.get(
                recipe.active_publication_revision_id,
                recipe.user_id,
            )
            ambiguity = self._projection_ambiguity(recipe, projection)
            validation_error = self._validate_projection(projection)
            if ambiguity is not None or validation_error is not None:
                return self._blocked(
                    base,
                    recipe,
                    projection,
                    CaptureCategory.INCONSISTENT_LINKAGE,
                    "managed projection no longer has trustworthy publication content",
                )
            proposal = self._build_proposal(
                recipe,
                projection,
                revision_number=managed_revision.revision_number,
            )
            if revision_content_digest(managed_revision) != managed_revision.content_digest:
                return self._blocked(
                    base,
                    recipe,
                    projection,
                    CaptureCategory.INCONSISTENT_LINKAGE,
                    "managed revision content does not match its diagnostic digest",
                )
            if proposal.content_digest != managed_revision.content_digest:
                return self._blocked(
                    base,
                    recipe,
                    projection,
                    CaptureCategory.INCONSISTENT_LINKAGE,
                    "managed projection content differs from its linked revision",
                )
            return _Assessment(
                result=CaptureResult(
                    **base,
                    category=CaptureCategory.ALREADY_MANAGED,
                    reason="Recipe and projection already reference the same managed revision",
                    proposed_revision_number=managed_revision.revision_number,
                    proposed_origin=managed_revision.creation_origin,
                    proposed_provenance_confidence=managed_revision.provenance_confidence,
                    proposed_content_digest=managed_revision.content_digest,
                    captured_revision_id=managed_revision.id,
                ),
                recipe=recipe,
                projection=projection,
            )
        if managed_reason is not None:
            return self._blocked(
                base,
                recipe,
                projection,
                CaptureCategory.INCONSISTENT_LINKAGE,
                managed_reason,
            )

        history = self.revisions.list_for_recipe(recipe.id, recipe.user_id)
        if history:
            return self._blocked(
                base,
                recipe,
                projection,
                CaptureCategory.INCONSISTENT_LINKAGE,
                "Recipe has revision history but no consistent active managed state",
            )

        ambiguity = self._projection_ambiguity(recipe, projection)
        if ambiguity is not None:
            return self._blocked(
                base,
                recipe,
                projection,
                CaptureCategory.AMBIGUOUS,
                ambiguity,
            )
        validation_error = self._validate_projection(projection)
        if validation_error is not None:
            return self._blocked(
                base,
                recipe,
                projection,
                CaptureCategory.FAILED_VALIDATION,
                validation_error,
            )

        proposal = self._build_proposal(recipe, projection, revision_number=1)
        category = (
            CaptureCategory.STALE_ELIGIBLE if recipe.needs_republish else CaptureCategory.ELIGIBLE
        )
        return _Assessment(
            result=CaptureResult(
                **base,
                category=category,
                reason="projection is eligible for transition-baseline capture",
                proposed_revision_number=proposal.revision_number,
                proposed_origin=CAPTURE_ORIGIN,
                proposed_provenance_confidence=CAPTURE_CONFIDENCE,
                proposed_content_digest=proposal.content_digest,
            ),
            recipe=recipe,
            projection=projection,
            proposal=proposal,
        )

    def _source_matches(self, recipe: Recipe) -> list[FoodItem]:
        statement = (
            select(FoodItem)
            .where(FoodItem.source_type == "recipe", FoodItem.source_id == str(recipe.id))
            .options(
                selectinload(FoodItem.nutrients),
                selectinload(FoodItem.serving_definitions),
                selectinload(FoodItem.sources),
            )
        )
        return list(self.db.scalars(statement).all())

    def _linkage_inconsistency(self, recipe: Recipe, projection: FoodItem) -> str | None:
        if projection.user_id != recipe.user_id:
            return "projection owner does not match Recipe owner"
        if projection.source_type != "recipe":
            return "referenced FoodItem is not a Recipe projection"
        if projection.source_id != str(recipe.id):
            return "projection source identity does not match Recipe"
        return None

    def _managed_state(self, recipe: Recipe, projection: FoodItem) -> str | None:
        active_id = recipe.active_publication_revision_id
        projection_id = projection.recipe_publication_revision_id
        if active_id is None and projection_id is None:
            return None
        if active_id is None or projection_id is None:
            return "only one side of the managed revision linkage is populated"
        if active_id != projection_id:
            return "Recipe active revision and projection revision disagree"
        revision = self.revisions.get(active_id, recipe.user_id)
        if revision is None or revision.recipe_id != recipe.id:
            return "managed revision does not belong to this Recipe and owner"
        return "consistent"

    def _projection_ambiguity(self, recipe: Recipe, projection: FoodItem) -> str | None:
        if not projection.is_recipe:
            return "projection no longer identifies itself as generated Recipe content"
        if projection.brand is not None:
            return "projection has display metadata not produced by Recipe publication"
        if projection.sources:
            return "projection has external source records not produced by Recipe publication"
        if any(
            serving.source != "recipe" or not serving.is_user_confirmed
            for serving in projection.serving_definitions
        ):
            return "projection servings show independent Food editing"
        if any(
            nutrient.source != "recipe" or not nutrient.is_user_confirmed
            for nutrient in projection.nutrients
        ):
            return "projection nutrients show independent Food editing"
        if not recipe.needs_republish and (
            projection.name != recipe.name or projection.notes != recipe.notes
        ):
            return "active projection display content differs without stale Recipe state"
        if _timestamp_is_after(projection.updated_at, recipe.updated_at):
            return "projection was modified after the Recipe's last authored update"
        return None

    def _validate_projection(self, projection: FoodItem) -> str | None:
        servings = list(projection.serving_definitions)
        if not servings:
            return "projection has no serving definitions"
        if sum(serving.is_default for serving in servings) != 1:
            return "projection must have exactly one default serving"
        semantic_labels: set[str] = set()
        for serving in servings:
            label_key = serving.label.strip().casefold()
            if not label_key or label_key in semantic_labels:
                return "projection has duplicate or empty serving labels"
            semantic_labels.add(label_key)
            if serving.quantity <= 0:
                return "projection has a non-positive serving quantity"
            if serving.gram_weight is not None and serving.gram_weight <= 0:
                return "projection has a non-positive gram equivalent"
            try:
                resolve_nutrition(projection, Decimal("1"), "serving", serving.id)
            except (NutritionResolutionError, ValueError) as exc:
                return f"serving resolution failed: {exc}"

        identities: set[tuple[str, str]] = set()
        for nutrient in projection.nutrients:
            try:
                basis = NutrientBasis(nutrient.basis)
                status = NutrientDataStatus(nutrient.data_status)
            except ValueError as exc:
                return f"nutrient classification is invalid: {exc}"
            identity = (nutrient.nutrient_id, basis.value)
            if identity in identities:
                return "projection has duplicate nutrient identity and basis"
            identities.add(identity)
            if status in {NutrientDataStatus.KNOWN, NutrientDataStatus.ESTIMATED}:
                if nutrient.amount is None:
                    return f"{status.value} nutrient is missing an amount"
                if status == NutrientDataStatus.KNOWN and nutrient.amount == 0:
                    return "known zero nutrient must use explicit zero status"
            elif status == NutrientDataStatus.UNKNOWN and nutrient.amount is not None:
                return "unknown nutrient includes an amount"
            elif status == NutrientDataStatus.ZERO and nutrient.amount != 0:
                return "explicit zero nutrient does not contain zero"
        return None

    def _build_proposal(
        self,
        recipe: Recipe,
        projection: FoodItem,
        *,
        revision_number: int,
    ) -> _CaptureProposal:
        revision = build_revision(
            recipe_id=recipe.id,
            user_id=recipe.user_id,
            revision_number=revision_number,
            creation_origin=CAPTURE_ORIGIN,
            provenance_confidence=CAPTURE_CONFIDENCE,
            content=content_from_projection(projection),
        )
        return _CaptureProposal(
            revision=revision,
            revision_number=revision_number,
            content_digest=revision.content_digest,
        )

    def _assign_links(
        self,
        recipe: Recipe,
        projection: FoodItem,
        revision: RecipePublicationRevision,
    ) -> None:
        recipe.active_publication_revision_id = revision.id
        projection.recipe_publication_revision_id = revision.id

    def _blocked(
        self,
        base: dict[str, Any],
        recipe: Recipe,
        projection: FoodItem,
        category: CaptureCategory,
        reason: str,
    ) -> _Assessment:
        return _Assessment(
            result=CaptureResult(**base, category=category, reason=reason),
            recipe=recipe,
            projection=projection,
        )


def _timestamp_is_after(left: datetime | None, right: datetime | None) -> bool:
    if left is None or right is None:
        return False
    if left.tzinfo is None:
        left = left.replace(tzinfo=timezone.utc)
    if right.tzinfo is None:
        right = right.replace(tzinfo=timezone.utc)
    return left > right
