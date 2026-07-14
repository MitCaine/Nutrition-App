from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.food import FoodItem, FoodNutrient, FoodSource, ServingDefinition
from app.models.log import DailyLog, DailyLogNutrientSnapshot
from app.models.recipe import Recipe, RecipeIngredient
from app.models.recipe_publication import (
    RecipePublicationAmountDefinition,
    RecipePublicationNutrient,
    RecipePublicationRevision,
)


class RetentionCategory(str, Enum):
    ACTIVE = "active"
    HISTORICALLY_REFERENCED = "historically_referenced"
    COMPATIBILITY_REFERENCED = "compatibility_referenced"
    SUPERSEDED_UNREFERENCED = "superseded_unreferenced"
    ORPHANED_INCONSISTENT = "orphaned_inconsistent"
    SAFE_TO_PURGE = "safe_to_purge"
    UNSAFE_UNKNOWN = "unsafe_unknown"


@dataclass(frozen=True)
class RetentionRecord:
    entity_type: str
    entity_id: UUID
    owner_id: UUID | None
    category: RetentionCategory
    protected: bool
    purge_eligible: bool
    reason_codes: tuple[str, ...]
    reference_counts: dict[str, int]

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["entity_id"] = str(self.entity_id)
        payload["owner_id"] = str(self.owner_id) if self.owner_id is not None else None
        payload["category"] = self.category.value
        return payload


@dataclass(frozen=True)
class RetentionAuditReport:
    operator_scope: bool
    owner_id: UUID | None
    dry_run: bool
    limitations: tuple[str, ...]
    records: tuple[RetentionRecord, ...]
    counts: dict[str, int]

    def to_dict(self) -> dict[str, Any]:
        return {
            "operator_scope": self.operator_scope,
            "owner_id": str(self.owner_id) if self.owner_id is not None else None,
            "dry_run": self.dry_run,
            "limitations": list(self.limitations),
            "policy": "retain_valid_publication_history_indefinitely",
            "cleanup_supported": False,
            "counts": self.counts,
            "records": [record.to_dict() for record in self.records],
        }


@dataclass(frozen=True)
class _RecipeRow:
    id: UUID
    user_id: UUID
    deleted: bool
    active_revision_id: UUID | None
    projection_id: UUID | None


@dataclass(frozen=True)
class _RevisionRow:
    id: UUID
    recipe_id: UUID
    user_id: UUID
    origin: str


@dataclass(frozen=True)
class _FoodRow:
    id: UUID
    user_id: UUID | None
    deleted: bool
    source_type: str
    source_id: str | None
    is_recipe: bool
    revision_id: UUID | None


@dataclass(frozen=True)
class _LogRow:
    id: UUID
    user_id: UUID
    food_id: UUID
    revision_id: UUID | None
    amount_id: UUID | None


class RetentionAuditService:
    """Read-only retention inspection.

    Owner audits are explicitly scoped. ``audit_operator`` is deliberately global
    for offline operator tooling, mirroring revision capture without establishing a
    user-facing global lookup convention. This service never mutates or purges rows.
    """

    def __init__(self, db: Session):
        self.db = db

    def audit_owner(self, user_id: UUID) -> RetentionAuditReport:
        return self._audit(owner_id=user_id, operator_scope=False)

    def audit_operator(self) -> RetentionAuditReport:
        return self._audit(owner_id=None, operator_scope=True)

    def _audit(
        self,
        *,
        owner_id: UUID | None,
        operator_scope: bool,
    ) -> RetentionAuditReport:
        scope_owner = None if operator_scope else owner_id
        recipes = self._recipes(scope_owner)
        revisions = self._revisions(scope_owner)

        amount_statement = select(
            RecipePublicationAmountDefinition.id,
            RecipePublicationAmountDefinition.revision_id,
        )
        nutrient_statement = select(
            RecipePublicationNutrient.id,
            RecipePublicationNutrient.revision_id,
        )
        if scope_owner is not None:
            amount_statement = amount_statement.join(
                RecipePublicationRevision,
                RecipePublicationAmountDefinition.revision_id
                == RecipePublicationRevision.id,
            )
            nutrient_statement = nutrient_statement.join(
                RecipePublicationRevision,
                RecipePublicationNutrient.revision_id
                == RecipePublicationRevision.id,
            )
            amount_statement = amount_statement.where(
                RecipePublicationRevision.user_id == scope_owner
            )
            nutrient_statement = nutrient_statement.where(
                RecipePublicationRevision.user_id == scope_owner
            )
        amounts = dict(self.db.execute(amount_statement).all())
        revision_nutrients = dict(self.db.execute(nutrient_statement).all())

        foods = self._foods(scope_owner)
        logs = self._logs(scope_owner)
        snapshot_statement = select(
            DailyLogNutrientSnapshot.id,
            DailyLogNutrientSnapshot.daily_log_id,
            DailyLogNutrientSnapshot.source_food_item_id,
        ).join(DailyLog, DailyLogNutrientSnapshot.daily_log_id == DailyLog.id)
        ingredient_statement = select(
            RecipeIngredient.id,
            RecipeIngredient.recipe_id,
            RecipeIngredient.food_item_id,
        ).join(Recipe, RecipeIngredient.recipe_id == Recipe.id)
        if scope_owner is not None:
            snapshot_statement = snapshot_statement.where(
                DailyLog.user_id == scope_owner
            )
            ingredient_statement = ingredient_statement.where(
                Recipe.user_id == scope_owner
            )
        snapshots = list(self.db.execute(snapshot_statement).all())
        ingredients = list(self.db.execute(ingredient_statement).all())
        food_nutrient_counts = self._counts_by_food(FoodNutrient, scope_owner)
        serving_counts = self._counts_by_food(ServingDefinition, scope_owner)
        food_source_counts = self._counts_by_food(FoodSource, scope_owner)

        recipe_by_id = {row.id: row for row in recipes}
        revision_by_id = {row.id: row for row in revisions}
        log_by_id = {row.id: row for row in logs}
        scoped_recipes = recipes
        scoped_revisions = revisions
        scoped_foods = foods

        revision_records = [
            self._revision_record(
                revision,
                recipe_by_id,
                recipes,
                foods,
                logs,
                amounts,
            )
            for revision in scoped_revisions
        ]
        projection_records = [
            self._projection_record(
                food,
                recipe_by_id,
                revision_by_id,
                recipes,
                foods,
                logs,
                snapshots,
                log_by_id,
                ingredients,
                food_nutrient_counts,
                serving_counts,
                food_source_counts,
            )
            for food in scoped_foods
            if self._is_projection_candidate(food, recipes)
        ]
        orphan_records = self._orphan_child_records(
            amounts,
            revision_nutrients,
            revision_by_id,
            operator_scope=operator_scope,
            owner_id=owner_id,
        )
        records = tuple(
            sorted(
                [*revision_records, *projection_records, *orphan_records],
                key=lambda record: (record.entity_type, str(record.entity_id)),
            )
        )
        counts = self._report_counts(
            scoped_recipes,
            scoped_revisions,
            scoped_foods,
            records,
        )
        return RetentionAuditReport(
            operator_scope=operator_scope,
            owner_id=owner_id,
            dry_run=True,
            limitations=(
                ()
                if operator_scope
                else (
                    "owner_scoped_orphan_revision_children_not_reported_"
                    "because_child_owner_is_unknown",
                )
            ),
            records=records,
            counts=counts,
        )

    def _recipes(self, owner_id: UUID | None) -> list[_RecipeRow]:
        statement = select(Recipe)
        if owner_id is not None:
            statement = statement.where(Recipe.user_id == owner_id)
        return [
            _RecipeRow(
                id=row.id,
                user_id=row.user_id,
                deleted=row.deleted_at is not None,
                active_revision_id=row.active_publication_revision_id,
                projection_id=row.published_food_item_id,
            )
            for row in self.db.scalars(statement).all()
        ]

    def _revisions(self, owner_id: UUID | None) -> list[_RevisionRow]:
        statement = select(RecipePublicationRevision)
        if owner_id is not None:
            statement = statement.where(RecipePublicationRevision.user_id == owner_id)
        return [
            _RevisionRow(
                id=row.id,
                recipe_id=row.recipe_id,
                user_id=row.user_id,
                origin=row.creation_origin,
            )
            for row in self.db.scalars(statement).all()
        ]

    def _foods(self, owner_id: UUID | None) -> list[_FoodRow]:
        statement = select(FoodItem)
        if owner_id is not None:
            statement = statement.where(FoodItem.user_id == owner_id)
        return [
            _FoodRow(
                id=row.id,
                user_id=row.user_id,
                deleted=row.deleted_at is not None,
                source_type=row.source_type,
                source_id=row.source_id,
                is_recipe=row.is_recipe,
                revision_id=row.recipe_publication_revision_id,
            )
            for row in self.db.scalars(statement).all()
        ]

    def _logs(self, owner_id: UUID | None) -> list[_LogRow]:
        statement = select(DailyLog)
        if owner_id is not None:
            statement = statement.where(DailyLog.user_id == owner_id)
        return [
            _LogRow(
                id=row.id,
                user_id=row.user_id,
                food_id=row.food_item_id,
                revision_id=row.recipe_publication_revision_id,
                amount_id=row.recipe_publication_amount_definition_id,
            )
            for row in self.db.scalars(statement).all()
        ]

    def _counts_by_food(self, model, owner_id: UUID | None) -> dict[UUID, int]:
        statement = select(model.food_item_id).join(
            FoodItem,
            model.food_item_id == FoodItem.id,
        )
        if owner_id is not None:
            statement = statement.where(FoodItem.user_id == owner_id)
        counts: dict[UUID, int] = {}
        for food_id in self.db.scalars(statement).all():
            counts[food_id] = counts.get(food_id, 0) + 1
        return counts

    def _revision_record(
        self,
        revision: _RevisionRow,
        recipe_by_id: dict[UUID, _RecipeRow],
        recipes: list[_RecipeRow],
        foods: list[_FoodRow],
        logs: list[_LogRow],
        amounts: dict[UUID, UUID],
    ) -> RetentionRecord:
        recipe = recipe_by_id.get(revision.recipe_id)
        active_refs = [row for row in recipes if row.active_revision_id == revision.id]
        log_refs = [row for row in logs if row.revision_id == revision.id]
        amount_log_refs = [
            row
            for row in logs
            if row.amount_id is not None and amounts.get(row.amount_id) == revision.id
        ]
        projection_refs = [row for row in foods if row.revision_id == revision.id]
        inconsistent = (
            recipe is None
            or recipe.user_id != revision.user_id
            or any(
                row.user_id != revision.user_id or row.id != revision.recipe_id
                for row in active_refs
            )
            or any(row.user_id != revision.user_id for row in log_refs)
            or any(row.user_id != revision.user_id for row in amount_log_refs)
            or any(row.revision_id != revision.id for row in amount_log_refs)
            or any(row.user_id != revision.user_id for row in projection_refs)
        )
        is_active = bool(
            recipe is not None
            and recipe.user_id == revision.user_id
            and recipe.active_revision_id == revision.id
        )
        reasons = ["immutable_publication_history_policy"]
        if is_active:
            reasons.append("active_recipe_revision")
        if log_refs:
            reasons.append("daily_log_revision_reference")
        if amount_log_refs:
            reasons.append("daily_log_amount_definition_reference")
        if projection_refs:
            reasons.append("projection_revision_link")
        if recipe is not None and recipe.deleted:
            reasons.append("deleted_recipe_history")
        if revision.origin == "legacy_projection_capture":
            reasons.append("capture_baseline_provenance")
        if inconsistent:
            reasons.append("ownership_or_linkage_inconsistent")
            category = RetentionCategory.ORPHANED_INCONSISTENT
        elif is_active:
            category = RetentionCategory.ACTIVE
        elif log_refs or amount_log_refs:
            category = RetentionCategory.HISTORICALLY_REFERENCED
        elif projection_refs:
            category = RetentionCategory.COMPATIBILITY_REFERENCED
        else:
            reasons.append("valid_superseded_revision_retained")
            category = RetentionCategory.SUPERSEDED_UNREFERENCED
        return RetentionRecord(
            entity_type="publication_revision",
            entity_id=revision.id,
            owner_id=revision.user_id,
            category=category,
            protected=True,
            purge_eligible=False,
            reason_codes=tuple(sorted(set(reasons))),
            reference_counts={
                "active_recipe": len(active_refs),
                "daily_logs": len(log_refs),
                "daily_log_amounts": len(amount_log_refs),
                "projections": len(projection_refs),
            },
        )

    def _projection_record(
        self,
        food: _FoodRow,
        recipe_by_id: dict[UUID, _RecipeRow],
        revision_by_id: dict[UUID, _RevisionRow],
        recipes: list[_RecipeRow],
        foods: list[_FoodRow],
        logs: list[_LogRow],
        snapshots: list[Any],
        log_by_id: dict[UUID, _LogRow],
        ingredients: list[Any],
        food_nutrients: dict[UUID, int],
        servings: dict[UUID, int],
        food_sources: dict[UUID, int],
    ) -> RetentionRecord:
        backlinks = [row for row in recipes if row.projection_id == food.id]
        log_refs = [row for row in logs if row.food_id == food.id]
        snapshot_refs = [row for row in snapshots if row.source_food_item_id == food.id]
        ingredient_refs = [row for row in ingredients if row.food_item_id == food.id]
        # FoodService.duplicate_food is the only production writer that stores a
        # source Food ID on a Manual Food. source_id is otherwise generic, so all
        # duplication markers must be present before treating it as provenance.
        provenance_refs = [
            row
            for row in foods
            if row.id != food.id
            and row.source_type == "manual"
            and not row.is_recipe
            and row.revision_id is None
            and row.source_id == str(food.id)
        ]
        source_recipe = self._source_recipe(food, recipe_by_id)
        revision = revision_by_id.get(food.revision_id) if food.revision_id else None
        coherent_active = bool(
            not food.deleted
            and food.user_id is not None
            and food.is_recipe
            and food.source_type == "recipe"
            and source_recipe is not None
            and source_recipe.user_id == food.user_id
            and source_recipe.projection_id == food.id
            and source_recipe.active_revision_id == food.revision_id
            and revision is not None
            and revision.recipe_id == source_recipe.id
            and revision.user_id == food.user_id
        )
        cross_owner = any(row.user_id != food.user_id for row in backlinks + log_refs)
        cross_owner = cross_owner or bool(
            revision is not None and revision.user_id != food.user_id
        )
        cross_owner = cross_owner or bool(
            source_recipe is not None and source_recipe.user_id != food.user_id
        )
        cross_owner = cross_owner or any(
            recipe_by_id.get(row.recipe_id) is None
            or recipe_by_id[row.recipe_id].user_id != food.user_id
            for row in ingredient_refs
        )
        cross_owner = cross_owner or any(
            log_by_id.get(row.daily_log_id) is None
            or log_by_id[row.daily_log_id].user_id != food.user_id
            for row in snapshot_refs
        )
        cross_owner = cross_owner or any(
            row.user_id != food.user_id for row in provenance_refs
        )
        same_history = any(row.user_id == food.user_id for row in log_refs) or any(
            log_by_id.get(row.daily_log_id) is not None
            and log_by_id[row.daily_log_id].user_id == food.user_id
            for row in snapshot_refs
        )
        same_compatibility = (
            any(row.user_id == food.user_id for row in backlinks)
            or any(
                recipe_by_id.get(row.recipe_id) is not None
                and recipe_by_id[row.recipe_id].user_id == food.user_id
                for row in ingredient_refs
            )
            or food.revision_id is not None
            or any(row.user_id == food.user_id for row in provenance_refs)
        )
        linked_graph = bool(backlinks or food.revision_id is not None)
        reasons: list[str] = []
        if coherent_active:
            reasons.append("active_managed_projection")
        if log_refs:
            reasons.append("daily_log_food_reference")
        if snapshot_refs:
            reasons.append("snapshot_source_food_reference")
        if ingredient_refs:
            reasons.append("recipe_ingredient_reference")
        if backlinks:
            reasons.append("recipe_projection_backlink")
        if food.revision_id is not None:
            reasons.append("projection_revision_link")
        if provenance_refs:
            reasons.append("manual_duplicate_provenance_reference")
        if food.deleted:
            reasons.append("soft_deleted_projection")
        if food_nutrients.get(food.id, 0):
            reasons.append("food_nutrient_children")
        if servings.get(food.id, 0):
            reasons.append("serving_definition_children")
        if food_sources.get(food.id, 0):
            reasons.append("food_source_children")
        if cross_owner:
            reasons.append("cross_user_reference_inconsistent")
            category = RetentionCategory.ORPHANED_INCONSISTENT
        elif coherent_active:
            category = RetentionCategory.ACTIVE
        elif same_history:
            category = RetentionCategory.HISTORICALLY_REFERENCED
        elif linked_graph and source_recipe is None:
            reasons.append("active_link_graph_inconsistent")
            category = RetentionCategory.ORPHANED_INCONSISTENT
        elif same_compatibility:
            category = RetentionCategory.COMPATIBILITY_REFERENCED
        else:
            reasons.extend(("projection_significance_uncertain", "no_positive_purge_proof"))
            category = RetentionCategory.ORPHANED_INCONSISTENT
        return RetentionRecord(
            entity_type="food_projection",
            entity_id=food.id,
            owner_id=food.user_id,
            category=category,
            protected=True,
            purge_eligible=False,
            reason_codes=tuple(sorted(set(reasons))),
            reference_counts={
                "recipe_backlinks": len(backlinks),
                "recipe_ingredients": len(ingredient_refs),
                "daily_logs": len(log_refs),
                "snapshots": len(snapshot_refs),
                "provenance_foods": len(provenance_refs),
            },
        )

    @staticmethod
    def _source_recipe(
        food: _FoodRow,
        recipe_by_id: dict[UUID, _RecipeRow],
    ) -> _RecipeRow | None:
        if food.source_type != "recipe" or food.source_id is None:
            return None
        try:
            return recipe_by_id.get(UUID(food.source_id))
        except ValueError:
            return None

    @staticmethod
    def _is_projection_candidate(food: _FoodRow, recipes: list[_RecipeRow]) -> bool:
        return bool(
            food.is_recipe
            or food.source_type == "recipe"
            or food.revision_id is not None
            or any(recipe.projection_id == food.id for recipe in recipes)
        )

    @staticmethod
    def _orphan_child_records(
        amounts: dict[UUID, UUID],
        nutrients: dict[UUID, UUID],
        revisions: dict[UUID, _RevisionRow],
        *,
        operator_scope: bool,
        owner_id: UUID | None,
    ) -> list[RetentionRecord]:
        records: list[RetentionRecord] = []
        for entity_type, children in (
            ("publication_amount_definition", amounts),
            ("publication_nutrient", nutrients),
        ):
            for child_id, revision_id in children.items():
                revision = revisions.get(revision_id)
                if revision is not None:
                    continue
                if not operator_scope and owner_id is not None:
                    continue
                records.append(
                    RetentionRecord(
                        entity_type=entity_type,
                        entity_id=child_id,
                        owner_id=None,
                        category=RetentionCategory.ORPHANED_INCONSISTENT,
                        protected=True,
                        purge_eligible=False,
                        reason_codes=(
                            "missing_parent_revision",
                            "ownership_unknown",
                            "no_positive_purge_proof",
                        ),
                        reference_counts={},
                    )
                )
        return records

    @staticmethod
    def _report_counts(
        recipes: list[_RecipeRow],
        revisions: list[_RevisionRow],
        foods: list[_FoodRow],
        records: tuple[RetentionRecord, ...],
    ) -> dict[str, int]:
        revision_records = [
            row for row in records if row.entity_type == "publication_revision"
        ]
        projection_records = [row for row in records if row.entity_type == "food_projection"]
        scoped_food_ids = {row.id for row in foods}
        return {
            "recipes_inspected": len(recipes),
            "deleted_recipes_retaining_history": len(
                {
                    revision.recipe_id
                    for revision in revisions
                    if any(row.id == revision.recipe_id and row.deleted for row in recipes)
                }
            ),
            "publication_revisions": len(revision_records),
            "active_revisions": sum(
                "active_recipe_revision" in row.reason_codes
                for row in revision_records
            ),
            "superseded_revisions": sum(
                "active_recipe_revision" not in row.reason_codes
                for row in revision_records
            ),
            "revisions_referenced_by_logs": sum(
                row.reference_counts.get("daily_logs", 0) > 0
                or row.reference_counts.get("daily_log_amounts", 0) > 0
                for row in revision_records
            ),
            "revisions_unreferenced_by_logs": sum(
                row.reference_counts.get("daily_logs", 0) == 0
                and row.reference_counts.get("daily_log_amounts", 0) == 0
                for row in revision_records
            ),
            "capture_origin_revisions": sum(
                revision.origin == "legacy_projection_capture" for revision in revisions
            ),
            "projections": len(projection_records),
            "active_projections": sum(
                "active_managed_projection" in row.reason_codes for row in projection_records
            ),
            "deleted_projections": sum(
                food.deleted
                for food in foods
                if any(row.entity_id == food.id for row in projection_records)
            ),
            "projections_referenced_by_ingredients": sum(
                row.reference_counts.get("recipe_ingredients", 0) > 0
                for row in projection_records
            ),
            "projections_referenced_by_logs": sum(
                row.reference_counts.get("daily_logs", 0) > 0
                for row in projection_records
            ),
            "projections_referenced_by_snapshots": sum(
                row.reference_counts.get("snapshots", 0) > 0
                for row in projection_records
            ),
            "inconsistent_rows": sum(
                row.category == RetentionCategory.ORPHANED_INCONSISTENT
                for row in records
            ),
            "orphan_revision_children": sum(
                row.entity_type
                in {"publication_amount_definition", "publication_nutrient"}
                and "missing_parent_revision" in row.reason_codes
                for row in records
            ),
            "purge_candidates": sum(row.purge_eligible for row in records),
            "scoped_food_rows": len(scoped_food_ids),
        }
